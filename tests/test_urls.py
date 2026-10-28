import socket

import pytest

from app.errors import UrlError, humanize_error
from app.sites import classify
from app.urls import validate_public_http_url


def test_rejects_non_http_and_local_targets():
    samples = [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/a",
        "http://127.0.0.1/secret",
        "http://localhost/x",
        "http://169.254.169.254/latest",
        "http://10.1.2.3/a",
        "http://[::1]/a",
        "http://2130706433/",
        "https://user:pass@example.com/a",
        "http://0177.0.0.1/",
        "",
        "https://example.com/a b",
    ]
    for sample in samples:
        with pytest.raises(UrlError):
            validate_public_http_url(sample, resolve=False)


def test_allows_public_video_urls_without_dns():
    url = validate_public_http_url("https://www.youtube.com/watch?v=abc", resolve=False)
    assert url.startswith("https://www.youtube.com/")
    assert classify(url).key == "youtube"
    assert classify("https://b23.tv/abc").key == "bilibili"
    assert classify("https://v.douyin.com/abc").needs_cookies_likely is True
    assert classify("https://www.xiaohongshu.com/explore/1").key == "xiaohongshu"
    assert classify("https://channels.weixin.qq.com/foo").key == "wechat"
    assert classify("https://x.com/a/status/1").label == "X / Twitter"


def test_dns_to_private_address_is_rejected():
    def resolver(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    with pytest.raises(UrlError):
        validate_public_http_url("https://evil.example/watch", resolver=resolver)


def test_error_copy_mentions_cookies_when_a_site_asks_for_login():
    message, _detail, needs = humanize_error(
        Exception("Sign in to confirm you’re not a bot"),
        "youtube",
    )
    assert needs is True
    assert "cookie" in message.lower()
    message, _detail, needs = humanize_error(Exception("HTTP Error 412: Precondition Failed"), "bilibili")
    assert needs is True
    assert "cookie" in message.lower()


def test_dns_to_public_address_is_allowed():
    def resolver(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0))]

    assert validate_public_http_url("https://cdn.example/v", resolver=resolver).startswith("https://")
