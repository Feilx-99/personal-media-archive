from __future__ import annotations

from app import db
from app.config import get_settings
from app.downloader import manager, remove_job_dir
from app.errors import JobError, TooManyJobs, UrlError
from app.present import ACTIVE
from app.sites import classify
from app.urls import validate_public_http_url


def create_job(url: str, fmt: str, quality: str, cookie_id: str | None) -> dict:
    normalized = validate_public_http_url(url, resolve=True)
    if cookie_id and db.get_cookie(cookie_id) is None:
        raise JobError("选择的 Cookie 不存在")
    settings = get_settings()
    if db.count_active() >= settings.max_concurrent * 8:
        raise TooManyJobs()
    site = classify(normalized)
    row = db.insert_job(
        url=normalized,
        fmt=fmt,
        quality=quality,
        cookie_id=cookie_id,
        site_key=site.key,
        site_label=site.label,
    )
    manager.submit(row["id"])
    return row


def retry_job(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] in ACTIVE:
        raise JobError("任务还在进行，可以先取消再重试。")
    cookie_id = job.get("cookie_id")
    if cookie_id and db.get_cookie(cookie_id) is None:
        cookie_id = None
    return create_job(job["url"], job["format"], job["quality"], cookie_id)


def cancel_running(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] in ACTIVE:
        manager.cancel(job_id)
        db.cancel_job(job_id)
    current = db.get_job(job_id)
    assert current is not None
    return current


def delete_finished(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] in ACTIVE:
        raise JobError("任务还在进行，请先取消。")
    remove_job_dir(job_id)
    db.delete_job(job_id)


def inspect_target(url: str) -> dict:
    try:
        normalized = validate_public_http_url(url, resolve=False)
    except UrlError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "site_key": None,
            "site_label": None,
            "needs_cookies_likely": False,
            "hint": None,
            "cookie_ready": False,
            "cookie_source": None,
        }
    site = classify(normalized)
    from app.cookies import cookie_for_download

    _path, source = cookie_for_download(site.key, None)
    return {
        "ok": True,
        "error": None,
        "site_key": site.key,
        "site_label": site.label,
        "needs_cookies_likely": site.needs_cookies_likely,
        "hint": site.hint,
        "cookie_ready": source is not None,
        "cookie_source": source,
    }
