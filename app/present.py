from __future__ import annotations

from pathlib import Path

ACTIVE = ("queued", "preparing", "downloading", "processing")
TERMINAL = ("completed", "failed", "cancelled")


def status_message(status: str, phase: str | None) -> str:
    if status == "downloading" and phase == "audio":
        return "正在下载音频"
    if status == "downloading" and phase == "video":
        return "正在下载视频"
    if status == "downloading":
        return "正在下载"
    if status == "processing" and phase == "audio-extract":
        return "正在转换音频"
    if status == "processing":
        return "正在合并音视频"
    return {
        "queued": "排队中，轮到后会自动开始",
        "preparing": "正在解析链接",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    }.get(status, status)


def to_public(row: dict) -> dict:
    path = row.get("file_path")
    ready = False
    size = None
    if path:
        file = Path(path)
        try:
            if file.is_file():
                ready = True
                size = file.stat().st_size
        except OSError:
            ready = False
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row.get("title"),
        "site_key": row.get("site_key"),
        "site_label": row.get("site_label"),
        "format": row["format"],
        "quality": row["quality"],
        "status": row["status"],
        "phase": row.get("phase"),
        "message": status_message(row["status"], row.get("phase")),
        "error": row.get("error"),
        "error_detail": row.get("error_detail"),
        "needs_cookies": bool(row.get("needs_cookies")),
        "file_ready": ready,
        "file_size": size,
        "percent": row.get("percent"),
        "speed": row.get("speed"),
        "eta": row.get("eta"),
        "duration_sec": row.get("duration_sec"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row.get("finished_at"),
        "download_url": f"/api/jobs/{row['id']}/file" if ready else None,
    }


def cookie_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "site_key": row["site_key"],
        "label": row["label"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
