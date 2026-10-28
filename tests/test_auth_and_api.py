from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from app import db
from app.auth import issue_token, verify_token
from app.config import get_settings, password_is_weak
from app.cookies import parse_netscape
from app.downloader import job_dir
from app.errors import CookieFormatError
import pytest


NETSCAPE = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	2000000000	CONSENT	YES
#HttpOnly_.douyin.com	TRUE	/	TRUE	2000000000	sessionid	abc
"""


def test_password_and_session_token():
    assert password_is_weak("changeme") is True
    assert password_is_weak("test-password-please") is False
    settings = get_settings()
    token = issue_token(settings.username, settings, now=1_000)
    assert verify_token(token, settings, now=1_000 + settings.session_seconds - 1) == "admin"
    assert verify_token(token, settings, now=1_000 + settings.session_seconds + 5) is None
    assert verify_token(token + "x", settings, now=1_000) is None


def test_health_is_public_and_downloads_require_login(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/jobs", json={"url": "https://youtu.be/abc"}).status_code == 401


def test_login_and_reject_bad_urls(auth_client):
    bad = auth_client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    denied = auth_client.post("/api/jobs", json={"url": "file:///etc/passwd", "format": "mp4"})
    assert denied.status_code == 400
    assert "http" in denied.json()["detail"]
    created = auth_client.post(
        "/api/jobs",
        json={"url": "https://www.youtube.com/watch?v=abc", "format": "mp3", "quality": "best"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "queued"
    assert body["site_label"] == "YouTube"
    assert body["format"] == "mp3"
    listed = auth_client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["id"] == body["id"]


def test_cookie_round_trip_and_inspect(auth_client):
    with pytest.raises(CookieFormatError):
        parse_netscape('[{"name":"a"}]')
    parsed = parse_netscape(NETSCAPE)
    assert "sessionid" in parsed
    saved = auth_client.post("/api/cookies", data={"site_key": "douyin", "content": NETSCAPE})
    assert saved.status_code == 201, saved.text
    assert saved.json()["label"] == "抖音"
    replaced = auth_client.post("/api/cookies", data={"site_key": "douyin", "content": NETSCAPE})
    assert replaced.status_code == 201
    listing = auth_client.get("/api/cookies").json()["cookies"]
    assert len(listing) == 1
    hint = auth_client.get("/api/inspect", params={"url": "https://v.douyin.com/abc/"})
    assert hint.status_code == 200
    payload = hint.json()
    assert payload["needs_cookies_likely"] is True
    assert payload["cookie_ready"] is True
    assert payload["cookie_source"] == "douyin"
    removed = auth_client.delete(f"/api/cookies/{saved.json()['id']}")
    assert removed.status_code == 200
    assert auth_client.get("/api/cookies").json()["cookies"] == []


def test_file_download_is_authorized_and_confined(auth_client):
    created = auth_client.post("/api/jobs", json={"url": "https://www.bilibili.com/video/BV1xx411c7mD"})
    job_id = created.json()["id"]
    assert db.claim_job(job_id)
    directory = job_dir(job_id)
    directory.mkdir(parents=True)
    media = directory / "media.mp4"
    media.write_bytes(b"hello-video")
    assert db.finish_job(job_id, file_path=str(media), file_size=media.stat().st_size, title="测试视频")
    auth_client.cookies.clear()
    blocked = auth_client.get(f"/api/jobs/{job_id}/file")
    assert blocked.status_code == 401
    auth_client.post("/api/login", json={"username": "admin", "password": "test-password-please"})
    downloaded = auth_client.get(f"/api/jobs/{job_id}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello-video"
    assert "测试视频.mp4" in unquote(downloaded.headers["content-disposition"])
    assert auth_client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert not media.exists()


def test_login_rate_limit(client):
    for _ in range(10):
        response = client.post("/api/login", json={"username": "admin", "password": "wrong-password"})
        assert response.status_code == 401
    locked = client.post("/api/login", json={"username": "admin", "password": "test-password-please"})
    assert locked.status_code == 429


def test_cleanup_removes_old_files_only():
    from app.cleanup import cleanup_once

    old_id = db.insert_job(
        url="https://example.com/old",
        fmt="mp4",
        quality="720",
        cookie_id=None,
        site_key="other",
        site_label="example.com",
    )["id"]
    assert db.claim_job(old_id)
    old_dir = job_dir(old_id)
    old_dir.mkdir(parents=True)
    old_file = old_dir / "media.mp4"
    old_file.write_bytes(b"old")
    assert db.finish_job(old_id, file_path=str(old_file), file_size=3, title="旧文件")
    fresh_id = db.insert_job(
        url="https://example.com/new",
        fmt="mp4",
        quality="720",
        cookie_id=None,
        site_key="other",
        site_label="example.com",
    )["id"]
    assert db.claim_job(fresh_id)
    fresh_dir = job_dir(fresh_id)
    fresh_dir.mkdir(parents=True)
    fresh_file = fresh_dir / "media.mp4"
    fresh_file.write_bytes(b"new")
    assert db.finish_job(fresh_id, file_path=str(fresh_file), file_size=3, title="新文件")
    stamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn = db.connect()
    try:
        conn.execute("UPDATE jobs SET finished_at = ? WHERE id = ?", (stamp, old_id))
        conn.commit()
    finally:
        conn.close()
    removed = cleanup_once()
    assert removed >= 1
    assert not old_file.exists()
    assert db.get_job(old_id)["file_path"] is None
    assert fresh_file.exists()
