from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response

from app.config import Settings, get_settings

COOKIE_NAME = "archive_session"
_FAILS: dict[str, list[float]] = defaultdict(list)
_FAIL_LOCK = threading.Lock()
_WINDOW_SECONDS = 600
_MAX_FAILS = 10


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def safe_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(_digest(left), _digest(right))


def issue_token(username: str, settings: Settings, *, now: int | None = None) -> str:
    exp = int(now if now is not None else time.time()) + settings.session_seconds
    body = json.dumps({"u": username, "exp": exp}, separators=(",", ":")).encode()
    sig = hmac.new(settings.secret.encode(), body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(sig)}"


def verify_token(token: str, settings: Settings, *, now: int | None = None) -> str | None:
    if not token or len(token) > 2000 or token.count(".") != 1:
        return None
    try:
        body_s, sig_s = token.split(".", 1)
        body = _b64d(body_s)
        sig = _b64d(sig_s)
        expected = hmac.new(settings.secret.encode(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(body.decode())
        if int(data["exp"]) < int(now if now is not None else time.time()):
            return None
        user = str(data["u"])
    except Exception:
        return None
    if not safe_eq(user, settings.username):
        return None
    return settings.username


def client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host[:80]
    return "unknown"


def _prune(ip: str, now: float) -> list[float]:
    hits = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < _WINDOW_SECONDS]
    if hits:
        _FAILS[ip] = hits
    else:
        _FAILS.pop(ip, None)
    return hits


def too_many_attempts(ip: str) -> bool:
    now = time.time()
    with _FAIL_LOCK:
        return len(_prune(ip, now)) >= _MAX_FAILS


def record_failure(ip: str) -> None:
    now = time.time()
    with _FAIL_LOCK:
        hits = _prune(ip, now)
        hits.append(now)
        _FAILS[ip] = hits


def clear_failures(ip: str) -> None:
    with _FAIL_LOCK:
        _FAILS.pop(ip, None)


def reset_attempts_for_tests() -> None:
    with _FAIL_LOCK:
        _FAILS.clear()


def read_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_token(token, get_settings())


def require_user(request: Request) -> str:
    user = read_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings.username, settings),
        max_age=settings.session_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", samesite="lax", secure=settings.cookie_secure)
