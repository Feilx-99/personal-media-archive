from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.db import delete_cookie_row, find_cookie_site, get_cookie, upsert_cookie
from app.errors import CookieFormatError
from app.sites import COOKIE_LABELS

_MAX_BYTES = 1_000_000
_LABEL = re.compile(r"[\r\n\t]+")


def parse_netscape(text: str) -> str:
    if text is None:
        raise CookieFormatError("Cookie 是空的")
    if "\x00" in text:
        raise CookieFormatError("文件内容无效")
    if len(text.encode("utf-8")) > _MAX_BYTES:
        raise CookieFormatError("Cookie 文件过大（上限 1 MB）")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        raise CookieFormatError("这看起来是 JSON，不是 Netscape cookies.txt。请用浏览器扩展导出 cookies.txt。")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    valid = 0
    for line in text.split("\n"):
        raw = line.strip()
        if not raw:
            continue
        if raw.startswith("#") and not raw.startswith("#HttpOnly_"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[0] and parts[5]:
            valid += 1
    if valid == 0:
        raise CookieFormatError(
            "未识别为 Netscape cookies.txt。请从浏览器导出制表符分隔的 cookies.txt，而不是 JSON 或请求头。"
        )
    if not text.endswith("\n"):
        text += "\n"
    return text


def clean_label(label: str | None, *, site_key: str) -> str:
    if site_key != "custom":
        return COOKIE_LABELS.get(site_key, site_key)
    text = _LABEL.sub(" ", (label or "")).strip()
    text = re.sub(r"\s+", " ", text)[:40]
    if not text:
        raise CookieFormatError("自定义 Cookie 需要一个名称")
    return text


def cookie_for_download(site_key: str, override_id: str | None) -> tuple[Path | None, str | None]:
    """Return the cookie file to pass to yt-dlp and which slot it came from."""
    if override_id:
        row = get_cookie(override_id)
        if row is None:
            return None, None
        path = _safe_path(row["file_path"])
        if path is None or not path.is_file():
            return None, None
        return path, row["site_key"]
    row = find_cookie_site(site_key) if site_key != "global" else None
    source = site_key
    if row is None:
        row = find_cookie_site("global")
        source = "global"
    if row is None:
        return None, None
    path = _safe_path(row["file_path"])
    if path is None or not path.is_file():
        return None, None
    return path, source


def _safe_path(raw: str) -> Path | None:
    root = get_settings().cookies_dir.resolve()
    path = Path(raw).resolve()
    if not path.is_relative_to(root):
        return None
    return path


def save_cookie(*, site_key: str, label: str | None, text: str) -> dict:
    parsed = parse_netscape(text)
    shown = clean_label(label, site_key=site_key)
    settings = get_settings()
    settings.cookies_dir.mkdir(parents=True, exist_ok=True)
    existing = find_cookie_site(site_key) if site_key != "custom" else None
    cookie_id = existing["id"] if existing else str(uuid.uuid4())
    path = (settings.cookies_dir / f"{cookie_id}.txt").resolve()
    if not path.is_relative_to(settings.cookies_dir.resolve()):
        raise CookieFormatError("无法保存 Cookie")
    tmp = path.with_suffix(".txt.tmp")
    tmp.write_text(parsed, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    if existing and Path(existing["file_path"]).resolve() != path:
        old = Path(existing["file_path"])
        if old.is_file() and _safe_path(str(old)):
            old.unlink(missing_ok=True)
    return upsert_cookie(
        site_key=site_key,
        label=shown,
        file_path=str(path),
        size_bytes=path.stat().st_size,
        cookie_id=cookie_id,
    )


def remove_cookie(cookie_id: str) -> bool:
    row = delete_cookie_row(cookie_id)
    if row is None:
        return False
    path = _safe_path(row["file_path"])
    if path is not None and path.is_file():
        path.unlink(missing_ok=True)
    return True
