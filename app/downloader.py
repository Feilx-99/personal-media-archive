from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

from app import db
from app.config import Settings, get_settings
from app.cookies import cookie_for_download
from app.errors import JobError, humanize_error
from app.formats import build_format
from app.present import to_public
from app.sites import classify, site_from_extractor

log = logging.getLogger("archive.downloader")

MEDIA_EXT = {
    ".mp4",
    ".mkv",
    ".webm",
    ".flv",
    ".mov",
    ".m4v",
    ".avi",
    ".mp3",
    ".m4a",
    ".aac",
    ".opus",
    ".ogg",
    ".wav",
    ".flac",
}

Publish = Callable[[str, str, dict], None]


def job_dir(job_id: str) -> Path:
    root = get_settings().downloads_dir.resolve()
    path = (root / job_id).resolve()
    if path.parent != root:
        raise JobError("任务编号无效")
    return path


def remove_job_dir(job_id: str) -> None:
    path = job_dir(job_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _js_runtimes() -> dict:
    runtimes = {}
    for name in ("deno", "node"):
        found = shutil.which(name)
        if found:
            runtimes[name] = {"path": found}
    return runtimes or {"deno": {}}


def _ffmpeg_dir() -> str | None:
    found = shutil.which("ffmpeg")
    if not found:
        return None
    return str(Path(found).parent)


def format_speed(speed: float | None) -> str | None:
    if speed is None or speed < 0:
        return None
    value = float(speed)
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{value:.0f} {units[index]}"
    return f"{value:.1f} {units[index]}"


def _phase_for(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in {".m4a", ".mp3", ".aac", ".opus", ".ogg", ".weba", ".wav", ".flac"}:
        return "audio"
    return "video"


def _pp_phase(name: str) -> str:
    if "ExtractAudio" in name:
        return "audio-extract"
    if any(token in name for token in ("Merger", "Remux", "Convert", "FFmpeg")):
        return "merging"
    return "processing"


def _estimate_size(info: dict) -> int | None:
    direct = info.get("filesize") or info.get("filesize_approx")
    formats = info.get("requested_formats") or []
    total = 0
    seen = False
    for fmt in formats:
        part = fmt.get("filesize") or fmt.get("filesize_approx")
        if part:
            total += int(part)
            seen = True
    if seen:
        return total
    if direct:
        return int(direct)
    return None


def _find_cause(exc: BaseException, kind: type) -> BaseException | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, kind):
            return current
        info = getattr(current, "exc_info", None)
        nested = None
        if isinstance(info, tuple) and len(info) >= 2 and isinstance(info[1], BaseException):
            nested = info[1]
        current = current.__cause__ or nested or current.__context__
    return None


def _settle_output(directory: Path, max_bytes: int | None) -> Path:
    cookies = directory / "cookies.txt"
    if cookies.exists():
        cookies.unlink()
    candidates: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        name = path.name
        suffix = path.suffix.lower()
        if name.startswith(".") or name.endswith(".part") or suffix in {".part", ".ytdl", ".tmp", ".temp"}:
            path.unlink(missing_ok=True)
            continue
        if suffix not in MEDIA_EXT:
            path.unlink(missing_ok=True)
            continue
        candidates.append(path)
    if not candidates:
        raise JobError("下载结束但没有找到媒体文件。可以换一种格式再试。")
    candidates.sort(key=lambda item: item.stat().st_size, reverse=True)
    keep = candidates[0]
    for extra in candidates[1:]:
        extra.unlink(missing_ok=True)
    size = keep.stat().st_size
    if size <= 0:
        raise JobError("下载到的文件是空的。")
    if max_bytes and size > max_bytes:
        raise JobError("文件大小超过限制。可以调低清晰度，或提高 MAX_FILESIZE_MB。")
    return keep


def _publish(publish: Publish, job_id: str, event: str) -> None:
    row = db.get_job(job_id)
    if row is None:
        return
    try:
        publish(job_id, event, to_public(row))
    except Exception:
        log.exception("failed to publish job %s", job_id)


def run_job(job_id: str, cancel: threading.Event, publish: Publish) -> None:
    if not db.claim_job(job_id):
        return
    settings = get_settings()
    try:
        if cancel.is_set():
            raise DownloadCancelled("已取消")
        job = db.get_job(job_id)
        if job is None:
            return
        _download(job, settings, cancel, publish)
        _publish(publish, job_id, "done")
    except DownloadCancelled:
        remove_job_dir(job_id)
        db.cancel_job(job_id)
        _publish(publish, job_id, "done")
    except Exception as exc:
        if cancel.is_set() or _find_cause(exc, DownloadCancelled) is not None:
            remove_job_dir(job_id)
            db.cancel_job(job_id)
            _publish(publish, job_id, "done")
            return
        cause = _find_cause(exc, JobError)
        if isinstance(cause, JobError):
            message, needs, detail = str(cause), cause.needs_cookies, cause.detail
        else:
            current = db.get_job(job_id) or {}
            message, detail, needs = humanize_error(exc, current.get("site_key"))
        detail = detail.replace(str(settings.data_dir), "[data]")
        log.info("job %s failed: %s", job_id, detail)
        remove_job_dir(job_id)
        db.fail_job(job_id, error=message, detail=detail, needs_cookies=needs)
        _publish(publish, job_id, "done")


def _download(job: dict, settings: Settings, cancel: threading.Event, publish: Publish) -> None:
    job_id = job["id"]
    url = job["url"]
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    site = classify(url)
    cookie_path, _source = cookie_for_download(site.key, job.get("cookie_id"))
    if cookie_path is not None:
        target = directory / "cookies.txt"
        shutil.copyfile(cookie_path, target)
        target.chmod(0o600)
        cookie_file = str(target)
    else:
        cookie_file = None

    db.update_active(
        job_id,
        status="preparing",
        phase="metadata",
        site_key=site.key,
        site_label=site.label,
    )
    _publish(publish, job_id, "progress")

    throttle = {"at": 0.0, "percent": -1.0}

    def ensure_running() -> None:
        if cancel.is_set():
            raise DownloadCancelled("已取消")

    def remember_metadata(info: dict) -> None:
        chosen = site_from_extractor(info.get("extractor_key")) or classify(info.get("webpage_url") or url)
        title = " ".join(str(info.get("title") or "").split())[:180] or "未命名视频"
        duration = info.get("duration")
        duration_sec = int(duration) if isinstance(duration, (int, float)) and duration >= 0 else None
        db.update_active(
            job_id,
            title=title,
            site_key=chosen.key,
            site_label=chosen.label,
            duration_sec=duration_sec,
            status="preparing",
            phase="metadata",
        )
        _publish(publish, job_id, "progress")

    def match_filter(info: dict, *, incomplete: bool = False):
        ensure_running()
        if info.get("_type") in {"playlist", "multi_video"}:
            raise JobError("请粘贴单个视频链接，暂不支持整份播放列表。")
        if info.get("is_live"):
            raise JobError("暂不支持正在直播的内容。")
        if incomplete:
            return None
        remember_metadata(info)
        duration = info.get("duration")
        if settings.max_duration_sec and isinstance(duration, (int, float)) and duration > settings.max_duration_sec:
            raise JobError(f"视频时长 {int(duration)} 秒，超过限制 {settings.max_duration_sec} 秒。")
        size = _estimate_size(info)
        if settings.max_filesize_bytes and size and size > settings.max_filesize_bytes:
            raise JobError("文件大小超过限制。可以调低清晰度，或提高 MAX_FILESIZE_MB。")
        return None

    def on_progress(event: dict) -> None:
        ensure_running()
        if event.get("postprocessor"):
            phase = _pp_phase(str(event.get("postprocessor")))
            status = "processing" if event.get("status") == "started" else "processing"
            db.update_active(job_id, status=status, phase=phase, speed=None, eta=None)
            _publish(publish, job_id, "progress")
            return
        if event.get("status") != "downloading":
            return
        downloaded = int(event.get("downloaded_bytes") or 0)
        total = event.get("total_bytes") or event.get("total_bytes_estimate")
        if settings.max_filesize_bytes and total and int(total) > settings.max_filesize_bytes:
            raise JobError("文件大小超过限制。可以调低清晰度，或提高 MAX_FILESIZE_MB。")
        if settings.max_filesize_bytes and downloaded > settings.max_filesize_bytes:
            raise JobError("文件大小超过限制。可以调低清晰度，或提高 MAX_FILESIZE_MB。")
        percent = None
        if total:
            percent = min(99.9, round(downloaded / float(total) * 100, 1))
        now = time.monotonic()
        moved = percent is not None and abs(percent - throttle["percent"]) >= 1
        if not moved and now - throttle["at"] < 0.45:
            return
        throttle["at"] = now
        if percent is not None:
            throttle["percent"] = percent
        eta = event.get("eta")
        eta_i = int(eta) if isinstance(eta, (int, float)) and eta >= 0 else None
        db.update_active(
            job_id,
            status="downloading",
            phase=_phase_for(str(event.get("filename") or "")),
            percent=percent,
            speed=format_speed(event.get("speed")),
            eta=eta_i,
        )
        _publish(publish, job_id, "progress")

    fmt = build_format(job["format"], job["quality"])
    opts: dict = {
        "paths": {"home": str(directory), "temp": str(directory)},
        "outtmpl": {"default": "media.%(ext)s"},
        "restrictfilenames": True,
        "noplaylist": True,
        "playlistend": 1,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "no_color": True,
        "retries": 3,
        "fragment_retries": 5,
        "extractor_retries": 2,
        "file_access_retries": 2,
        "concurrent_fragment_downloads": 3,
        "socket_timeout": 30,
        "overwrites": True,
        "continuedl": True,
        "ignoreerrors": False,
        "cachedir": str(settings.cache_dir),
        "match_filter": match_filter,
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_progress],
        "js_runtimes": _js_runtimes(),
        **fmt,
    }
    ffmpeg_dir = _ffmpeg_dir()
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir
    if cookie_file:
        opts["cookiefile"] = cookie_file
    if settings.max_filesize_bytes:
        opts["max_filesize"] = settings.max_filesize_bytes

    host = urlsplit(url).hostname
    log.info("job %s start host=%s format=%s", job_id, host, job["format"])
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except DownloadError as exc:
        cause = _find_cause(exc, JobError) or _find_cause(exc, DownloadCancelled)
        if cause is not None:
            raise cause from exc
        raise

    ensure_running()
    final = _settle_output(directory, settings.max_filesize_bytes)
    current = db.get_job(job_id) or job
    saved = db.finish_job(
        job_id,
        file_path=str(final),
        file_size=final.stat().st_size,
        title=current.get("title"),
    )
    if not saved:
        remove_job_dir(job_id)
        if not cancel.is_set():
            raise JobError("任务状态已变化，没有保存文件。")


class DownloadManager:
    def __init__(self) -> None:
        self._executor = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, workers: int, loop: asyncio.AbstractEventLoop) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._loop = loop
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ytdlp")

    def shutdown(self) -> None:
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, job_id: str) -> None:
        if self._executor is None:
            raise RuntimeError("下载器还没有启动")
        event = threading.Event()
        with self._lock:
            self._cancels[job_id] = event
        self._executor.submit(self._safe, job_id, event)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            event = self._cancels.get(job_id)
        if event is not None:
            event.set()

    def subscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs[job_id].append(queue)

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            buckets = self._subs.get(job_id, [])
            if queue in buckets:
                buckets.remove(queue)

    def publish(self, job_id: str, event: str, data: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            queues = list(self._subs.get(job_id, []))
        for queue in queues:
            try:
                loop.call_soon_threadsafe(self._put, queue, (event, data))
            except RuntimeError:
                return

    @staticmethod
    def _put(queue: asyncio.Queue, item: tuple) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            return

    def _safe(self, job_id: str, event: threading.Event) -> None:
        try:
            run_job(job_id, event, self.publish)
        except Exception:
            log.exception("job %s crashed", job_id)
            db.fail_job(job_id, error="内部错误", detail="worker crashed")
            row = db.get_job(job_id)
            if row is not None:
                self.publish(job_id, "done", to_public(row))
        finally:
            with self._lock:
                self._cancels.pop(job_id, None)


manager = DownloadManager()
