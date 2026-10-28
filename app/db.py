from __future__ import annotations

import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings

_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    site_key TEXT,
    site_label TEXT,
    format TEXT NOT NULL,
    quality TEXT NOT NULL,
    cookie_id TEXT,
    status TEXT NOT NULL,
    phase TEXT,
    percent REAL,
    speed TEXT,
    eta INTEGER,
    error TEXT,
    error_detail TEXT,
    needs_cookies INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    file_size INTEGER,
    duration_sec INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);
CREATE TABLE IF NOT EXISTS cookies (
    id TEXT PRIMARY KEY,
    site_key TEXT NOT NULL,
    label TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cookies_site ON cookies (site_key);
"""

_ACTIVE = ("queued", "preparing", "downloading", "processing")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = connect(settings)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def _one(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _all(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def insert_job(
    *,
    url: str,
    fmt: str,
    quality: str,
    cookie_id: str | None,
    site_key: str,
    site_label: str,
) -> dict:
    job_id = str(uuid.uuid4())
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, url, site_key, site_label, format, quality, cookie_id,
                    status, phase, needs_cookies, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', NULL, 0, ?, ?)
                """,
                (job_id, url, site_key, site_label, fmt, quality, cookie_id, ts, ts),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
    result = _one(row)
    assert result is not None
    return result


def get_job(job_id: str) -> dict | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
    return _one(row)


def list_jobs(limit: int) -> list[dict]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return _all(rows)


def all_jobs() -> list[dict]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
        finally:
            conn.close()
    return _all(rows)


def count_active() -> int:
    marks = ",".join("?" for _ in _ACTIVE)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM jobs WHERE status IN ({marks})",
                _ACTIVE,
            ).fetchone()
        finally:
            conn.close()
    return int(row["n"] if row else 0)


def claim_job(job_id: str) -> bool:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET status = 'preparing', phase = 'metadata', updated_at = ?
                 WHERE id = ? AND status = 'queued'
                """,
                (ts, job_id),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def update_active(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = utcnow()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id, *_ACTIVE]
    marks = ",".join("?" for _ in _ACTIVE)
    with _lock:
        conn = connect()
        try:
            conn.execute(
                f"UPDATE jobs SET {columns} WHERE id = ? AND status IN ({marks})",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def finish_job(job_id: str, *, file_path: str, file_size: int, title: str | None) -> bool:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET status = 'completed',
                       phase = NULL,
                       percent = 100,
                       speed = NULL,
                       eta = NULL,
                       error = NULL,
                       error_detail = NULL,
                       needs_cookies = 0,
                       file_path = ?,
                       file_size = ?,
                       title = COALESCE(?, title),
                       finished_at = ?,
                       updated_at = ?
                 WHERE id = ? AND status IN ('preparing', 'downloading', 'processing')
                """,
                (file_path, file_size, title, ts, ts, job_id),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def fail_job(
    job_id: str,
    *,
    error: str,
    detail: str = "",
    needs_cookies: bool = False,
) -> bool:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET status = 'failed',
                       phase = NULL,
                       error = ?,
                       error_detail = ?,
                       needs_cookies = ?,
                       finished_at = ?,
                       updated_at = ?
                 WHERE id = ? AND status IN ('preparing', 'downloading', 'processing', 'queued')
                """,
                (error[:400], detail[:800], 1 if needs_cookies else 0, ts, ts, job_id),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def cancel_job(job_id: str) -> bool:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET status = 'cancelled',
                       phase = NULL,
                       error = '已取消',
                       finished_at = ?,
                       updated_at = ?
                 WHERE id = ? AND status IN ('queued', 'preparing', 'downloading', 'processing')
                """,
                (ts, ts, job_id),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def clear_file(job_id: str) -> None:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE jobs SET file_path = NULL, file_size = NULL, updated_at = ? WHERE id = ?",
                (ts, job_id),
            )
            conn.commit()
        finally:
            conn.close()


def delete_job(job_id: str) -> bool:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def fail_interrupted() -> int:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET status = 'failed',
                       error = '服务重启，任务已中断。可以重新下载。',
                       error_detail = '',
                       finished_at = ?,
                       updated_at = ?
                 WHERE status IN ('queued', 'preparing', 'downloading', 'processing')
                """,
                (ts, ts),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def upsert_cookie(
    *,
    site_key: str,
    label: str,
    file_path: str,
    size_bytes: int,
    cookie_id: str | None = None,
) -> dict:
    ts = utcnow()
    with _lock:
        conn = connect()
        try:
            existing = None
            if site_key != "custom":
                existing = conn.execute(
                    "SELECT * FROM cookies WHERE site_key = ? ORDER BY updated_at DESC LIMIT 1",
                    (site_key,),
                ).fetchone()
            if existing is not None:
                cookie_id = existing["id"]
                conn.execute(
                    """
                    UPDATE cookies
                       SET label = ?, file_path = ?, size_bytes = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (label, file_path, size_bytes, ts, cookie_id),
                )
            else:
                cookie_id = cookie_id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO cookies (id, site_key, label, file_path, size_bytes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cookie_id, site_key, label, file_path, size_bytes, ts, ts),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM cookies WHERE id = ?", (cookie_id,)).fetchone()
        finally:
            conn.close()
    result = _one(row)
    assert result is not None
    return result


def list_cookies() -> list[dict]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT * FROM cookies ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
    return _all(rows)


def get_cookie(cookie_id: str) -> dict | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM cookies WHERE id = ?", (cookie_id,)).fetchone()
        finally:
            conn.close()
    return _one(row)


def find_cookie_site(site_key: str) -> dict | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM cookies WHERE site_key = ? ORDER BY updated_at DESC LIMIT 1",
                (site_key,),
            ).fetchone()
        finally:
            conn.close()
    return _one(row)


def delete_cookie_row(cookie_id: str) -> dict | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM cookies WHERE id = ?", (cookie_id,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM cookies WHERE id = ?", (cookie_id,))
            conn.commit()
        finally:
            conn.close()
    return _one(row)


def reset_for_tests() -> None:
    settings = get_settings()
    with _lock:
        conn = connect(settings)
        try:
            conn.execute("DELETE FROM jobs")
            conn.execute("DELETE FROM cookies")
            conn.commit()
        finally:
            conn.close()
    for folder in (settings.downloads_dir, settings.cookies_dir):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
