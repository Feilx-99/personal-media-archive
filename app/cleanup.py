from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone

from app import db
from app.config import get_settings
from app.downloader import remove_job_dir

log = logging.getLogger("archive.cleanup")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def cleanup_once() -> int:
    settings = get_settings()
    if settings.retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    removed = 0
    active = {"queued", "preparing", "downloading", "processing"}
    known: set[str] = set()
    for job in db.all_jobs():
        known.add(job["id"])
        if job["status"] in active:
            continue
        stamp = _parse(job.get("finished_at")) or _parse(job.get("created_at"))
        if stamp is None or stamp >= cutoff:
            continue
        had_file = bool(job.get("file_path"))
        try:
            remove_job_dir(job["id"])
        except Exception:
            log.exception("failed to remove job dir %s", job["id"])
            continue
        if had_file:
            db.clear_file(job["id"])
            removed += 1
    root = settings.downloads_dir
    if root.exists():
        for child in root.iterdir():
            if not child.is_dir() or child.name in known:
                continue
            try:
                modified = datetime.fromtimestamp(child.stat().st_mtime, timezone.utc)
            except OSError:
                continue
            if modified >= cutoff:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    if removed:
        log.info("removed %s expired download(s)", removed)
    return removed


async def cleanup_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1800)
            return
        except TimeoutError:
            try:
                cleanup_once()
            except Exception:
                log.exception("cleanup failed")
