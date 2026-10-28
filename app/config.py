from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

WEAK_PASSWORDS = {
    "changeme",
    "password",
    "admin",
    "123456",
    "12345678",
    "secret",
    "passw0rd",
}


_ENV_LOADED = False


def load_local_env() -> None:
    """Load a local .env without overriding variables already set in the process."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    path = Path.cwd() / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def password_is_weak(password: str) -> bool:
    return len(password) < 12 or password.lower() in WEAK_PASSWORDS


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    secret: str
    data_dir: Path
    downloads_dir: Path
    cookies_dir: Path
    db_path: Path
    cache_dir: Path
    retention_days: int
    max_concurrent: int
    max_filesize_mb: int
    max_duration_sec: int
    cookie_secure: bool
    session_seconds: int

    @property
    def max_filesize_bytes(self) -> int | None:
        if self.max_filesize_mb <= 0:
            return None
        return self.max_filesize_mb * 1024 * 1024

    @property
    def weak_password(self) -> bool:
        return password_is_weak(self.password)


def get_settings() -> Settings:
    load_local_env()
    data = Path(os.environ.get("DATA_DIR", "./data")).expanduser().resolve()
    username = os.environ.get("AUTH_USERNAME", "admin").strip() or "admin"
    password_file = os.environ.get("AUTH_PASSWORD_FILE", "").strip()
    if password_file:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    else:
        password = os.environ.get("AUTH_PASSWORD", "")
    secret = os.environ.get("AUTH_SECRET", "").strip()
    if not secret:
        secret = hashlib.sha256(f"personal-archive|{password}".encode()).hexdigest()
    return Settings(
        username=username,
        password=password,
        secret=secret,
        data_dir=data,
        downloads_dir=data / "downloads",
        cookies_dir=data / "cookies",
        db_path=data / "db" / "app.db",
        cache_dir=data / "cache",
        retention_days=max(0, _int("RETENTION_DAYS", 3)),
        max_concurrent=max(1, _int("MAX_CONCURRENT", 2)),
        max_filesize_mb=max(0, _int("MAX_FILESIZE_MB", 2048)),
        max_duration_sec=max(0, _int("MAX_DURATION_SEC", 0)),
        cookie_secure=_bool("COOKIE_SECURE", False),
        session_seconds=max(1, _int("SESSION_DAYS", 14)) * 86400,
    )


def ensure_dirs(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    for path in (
        settings.data_dir,
        settings.downloads_dir,
        settings.cookies_dir,
        settings.db_path.parent,
        settings.cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings
