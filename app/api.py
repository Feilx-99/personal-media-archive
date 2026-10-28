from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    clear_failures,
    clear_session_cookie,
    client_ip,
    read_user,
    record_failure,
    require_user,
    safe_eq,
    set_session_cookie,
    too_many_attempts,
)
from app.config import get_settings, password_is_weak
from app.cookies import remove_cookie, save_cookie
from app.db import get_job, list_cookies, list_jobs
from app.downloader import manager
from app.errors import CookieFormatError, JobError, TooManyJobs, UrlError
from app.jobs import cancel_running, create_job, delete_finished, inspect_target, retry_job
from app.present import TERMINAL, cookie_public, to_public
from app.sites import PRESET_COOKIE_KEYS

router = APIRouter()
_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_MEDIA_TYPES = {
    "mp4": "video/mp4",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class JobIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    format: str = "mp4"
    quality: str = "1080"
    cookie_id: str | None = Field(default=None, max_length=80)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("format")
    @classmethod
    def known_format(cls, value: str) -> str:
        if value not in {"mp4", "mp3", "m4a", "best"}:
            raise ValueError("format")
        return value

    @field_validator("quality")
    @classmethod
    def known_quality(cls, value: str) -> str:
        if value not in {"best", "1080", "720", "480"}:
            raise ValueError("quality")
        return value

    @field_validator("cookie_id")
    @classmethod
    def blank_cookie(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


def tool_status() -> dict:
    import yt_dlp.version

    runtime = None
    if shutil.which("deno"):
        runtime = "deno"
    elif shutil.which("node"):
        runtime = "node"
    return {
        "ytdlp": yt_dlp.version.__version__,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "js_runtime": runtime,
    }


def me_payload() -> dict:
    settings = get_settings()
    tools = tool_status()
    return {
        "username": settings.username,
        "retention_days": settings.retention_days,
        "max_concurrent": settings.max_concurrent,
        "max_filesize_mb": settings.max_filesize_mb,
        "max_duration_sec": settings.max_duration_sec,
        "password_is_weak": password_is_weak(settings.password),
        **tools,
    }


def _job_or_404(job_id: str) -> dict:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


def _map_job_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, UrlError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, TooManyJobs):
        return HTTPException(status_code=429, detail="排队任务过多，请等当前下载完成后再试")
    if isinstance(exc, JobError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="任务不存在")
    raise exc


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    if too_many_attempts(ip):
        raise HTTPException(status_code=429, detail="尝试次数过多，请十分钟后再试")
    settings = get_settings()
    if not (safe_eq(body.username, settings.username) and safe_eq(body.password, settings.password)):
        record_failure(ip)
        raise HTTPException(status_code=401, detail="用户名或口令不正确")
    clear_failures(ip)
    set_session_cookie(response, settings)
    return me_payload()


@router.post("/logout")
def logout(response: Response, _user: str = Depends(require_user)) -> dict:
    clear_session_cookie(response, get_settings())
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not read_user(request):
        raise HTTPException(status_code=401, detail="请先登录")
    return me_payload()


@router.get("/inspect")
def inspect(url: str = Query(min_length=1, max_length=2048), _user: str = Depends(require_user)) -> dict:
    return inspect_target(url)


@router.get("/jobs")
def jobs(limit: int = Query(30, ge=1, le=100), _user: str = Depends(require_user)) -> dict:
    return {"jobs": [to_public(row) for row in list_jobs(limit)]}


@router.post("/jobs", status_code=201)
def post_job(body: JobIn, _user: str = Depends(require_user)) -> dict:
    try:
        row = create_job(body.url, body.format, body.quality, body.cookie_id)
    except (UrlError, JobError, TooManyJobs, KeyError) as exc:
        raise _map_job_errors(exc) from exc
    return to_public(row)


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, _user: str = Depends(require_user)) -> dict:
    return to_public(_job_or_404(job_id))


@router.post("/jobs/{job_id}/cancel")
def post_cancel(job_id: str, _user: str = Depends(require_user)) -> dict:
    try:
        row = cancel_running(job_id)
    except (JobError, KeyError) as exc:
        raise _map_job_errors(exc) from exc
    return to_public(row)


@router.post("/jobs/{job_id}/retry", status_code=201)
def post_retry(job_id: str, _user: str = Depends(require_user)) -> dict:
    try:
        row = retry_job(job_id)
    except JobError as exc:
        status = 409 if "还在进行" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except (UrlError, TooManyJobs, KeyError) as exc:
        raise _map_job_errors(exc) from exc
    return to_public(row)


@router.delete("/jobs/{job_id}")
def remove_job(job_id: str, _user: str = Depends(require_user)) -> dict:
    try:
        delete_finished(job_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"ok": True}


def _sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, _user: str = Depends(require_user)) -> StreamingResponse:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        manager.subscribe(job_id, queue)
        try:
            current = get_job(job_id)
            if current is None:
                yield _sse("error", {"detail": "任务不存在"})
                return
            snapshot = to_public(current)
            yield _sse("snapshot", snapshot)
            if snapshot["status"] in TERMINAL:
                return
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(event, data)
                if event == "done" or data.get("status") in TERMINAL:
                    return
        finally:
            manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _safe_filename(title: str | None, ext: str) -> str:
    cleaned = _FILENAME.sub(" ", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:80] or "video"
    extension = ext.lower().lstrip(".") or "bin"
    return f"{cleaned}.{extension}"


@router.get("/jobs/{job_id}/file")
def job_file(job_id: str, _user: str = Depends(require_user)) -> FileResponse:
    row = _job_or_404(job_id)
    raw = row.get("file_path")
    if not raw:
        raise HTTPException(status_code=404, detail="文件不存在或已清理")
    path = Path(raw).resolve()
    root = get_settings().downloads_dir.resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="文件不存在或已清理")
    ext = path.suffix.lstrip(".").lower()
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=_safe_filename(row.get("title"), ext),
        content_disposition_type="attachment",
    )


@router.get("/cookies")
def cookies(_user: str = Depends(require_user)) -> dict:
    return {
        "cookies": [cookie_public(row) for row in list_cookies()],
        "presets": list(PRESET_COOKIE_KEYS),
    }


@router.post("/cookies", status_code=201)
async def post_cookie(
    site_key: str = Form(...),
    label: str | None = Form(None),
    content: str | None = Form(None),
    file: UploadFile | None = File(None),
    _user: str = Depends(require_user),
) -> dict:
    allowed = set(PRESET_COOKIE_KEYS) | {"custom"}
    if site_key not in allowed:
        raise HTTPException(status_code=400, detail="不认识的站点")
    text = content or ""
    if file is not None:
        raw = await file.read(1_000_001)
        if len(raw) > 1_000_000:
            raise HTTPException(status_code=400, detail="Cookie 文件过大（上限 1 MB）")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Cookie 文件需要是 UTF-8 文本") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="请上传或粘贴 cookies.txt")
    try:
        row = save_cookie(site_key=site_key, label=label, text=text)
    except CookieFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cookie_public(row)


@router.delete("/cookies/{cookie_id}")
def delete_cookie(cookie_id: str, _user: str = Depends(require_user)) -> dict:
    if not remove_cookie(cookie_id):
        raise HTTPException(status_code=404, detail="Cookie 不存在")
    return {"ok": True}
