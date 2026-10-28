from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.cleanup import cleanup_loop, cleanup_once
from app.config import ensure_dirs, get_settings
from app.db import fail_interrupted, init_db
from app.downloader import manager

log = logging.getLogger("archive")

_ASSET_EXT = {
    ".js",
    ".css",
    ".map",
    ".svg",
    ".png",
    ".ico",
    ".woff",
    ".woff2",
    ".webp",
    ".txt",
    ".json",
}
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def static_dir() -> Path | None:
    import os

    candidates = []
    env = os.environ.get("STATIC_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent.parent
    candidates.extend([here / "static", here / "frontend" / "dist"])
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.password:
        raise RuntimeError("必须设置环境变量 AUTH_PASSWORD（或 AUTH_PASSWORD_FILE）")
    ensure_dirs(settings)
    init_db(settings)
    interrupted = fail_interrupted()
    if interrupted:
        log.info("marked %s interrupted job(s) as failed", interrupted)
    if settings.weak_password:
        log.warning("AUTH_PASSWORD 过于简单。公开到网上之前请换成至少 12 位的口令。")
    loop = asyncio.get_running_loop()
    manager.start(settings.max_concurrent, loop)
    removed = cleanup_once()
    if removed:
        log.info("startup cleanup removed %s file(s)", removed)
    stop = asyncio.Event()
    task = asyncio.create_task(cleanup_loop(stop))
    try:
        yield
    finally:
        stop.set()
        manager.shutdown()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="个人媒体存档", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router, prefix="/api")


@app.get("/healthz")
def healthz() -> dict:
    from app.api import tool_status

    tools = tool_status()
    return {"ok": True, **tools}


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "请求参数不正确"})


class SecurityHeaders:
    """Pure ASGI middleware so SSE responses are not buffered."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.asgi_app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                        (b"content-security-policy", _CSP.encode()),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.asgi_app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeaders)


def _mount_ui(application: FastAPI) -> None:
    folder = static_dir()
    if folder is None:
        return
    assets = folder / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(folder / "index.html")

    @application.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        root = folder.resolve()
        candidate = (folder / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        if Path(full_path).suffix.lower() in _ASSET_EXT:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(folder / "index.html")


_mount_ui(app)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


configure_logging()
