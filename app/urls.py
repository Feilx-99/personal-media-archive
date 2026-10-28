from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from app.errors import UrlError

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.internal",
}
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain")
_DOTTED = re.compile(r"^(?:\d+\.){3}\d+$")


def _mapped(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _mapped(ip)
    return not ip.is_global


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        try:
            return ipaddress.ip_address(int(host))
        except (ValueError, OverflowError):
            return None
    if not _DOTTED.fullmatch(host):
        return None
    parts = host.split(".")
    if any((part.startswith("0") and part != "0") or int(part) > 255 for part in parts):
        raise UrlError("链接地址无效")
    try:
        return ipaddress.ip_address(".".join(str(int(part)) for part in parts))
    except ValueError:
        return None


def _blocked_name(host: str) -> bool:
    if host in _BLOCKED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)


def validate_public_http_url(
    url: str,
    *,
    resolve: bool = True,
    resolver: Callable[..., list] | None = None,
) -> str:
    """Accept a single public http(s) URL and reject obvious SSRF targets."""
    url = (url or "").strip()
    if not url:
        raise UrlError("请先粘贴视频链接")
    if len(url) > 2048:
        raise UrlError("链接过长")
    if any(ch.isspace() or ch == "\x00" for ch in url):
        raise UrlError("链接里不能有空格或换行")
    if "\\" in url:
        raise UrlError("链接无效")

    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise UrlError("只接受 http 或 https 链接")
    if parts.username or parts.password:
        raise UrlError("链接里不能带账号密码")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host or host == ".":
        raise UrlError("链接缺少域名")
    if _blocked_name(host):
        raise UrlError("不允许访问本机或内网地址")

    literal = _literal_ip(host)
    if literal is not None and _blocked_ip(literal):
        raise UrlError("不允许访问本机或内网地址")

    if resolve and literal is None:
        lookup = resolver or socket.getaddrinfo
        try:
            infos = lookup(host, None)
        except socket.gaierror as exc:
            raise UrlError("无法解析这个域名") from exc
        except UrlError:
            raise
        except Exception as exc:
            raise UrlError("无法解析这个域名") from exc
        if not infos:
            raise UrlError("无法解析这个域名")
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError) as exc:
                raise UrlError("无法解析这个域名") from exc
            if _blocked_ip(ip):
                raise UrlError("不允许访问本机或内网地址")
    return url
