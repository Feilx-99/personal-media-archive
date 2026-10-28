from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Site:
    key: str
    label: str
    needs_cookies_likely: bool
    hint: str


SITES: dict[str, Site] = {
    "youtube": Site(
        "youtube",
        "YouTube",
        False,
        "公开视频一般可以直接下载。如果提示人机验证，再上传 YouTube 的 Cookie。",
    ),
    "bilibili": Site(
        "bilibili",
        "哔哩哔哩",
        False,
        "公开视频一般可以直接下载。大会员清晰度需要哔哩哔哩的 Cookie。",
    ),
    "twitter": Site(
        "twitter",
        "X / Twitter",
        False,
        "公开帖子通常可以直接下载。受限内容再上传 X 的 Cookie。",
    ),
    "douyin": Site(
        "douyin",
        "抖音",
        True,
        "抖音通常需要你本人浏览器导出的 Cookie，否则会失败。",
    ),
    "xiaohongshu": Site(
        "xiaohongshu",
        "小红书",
        True,
        "小红书通常需要你本人浏览器导出的 Cookie，否则会失败。",
    ),
    "wechat": Site(
        "wechat",
        "视频号",
        True,
        "视频号支持不稳定。请先上传微信 Cookie，即使这样也可能失败。",
    ),
}

# Longer suffixes are listed explicitly; matching is exact or subdomain.
_HOSTS: tuple[tuple[str, str], ...] = (
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("youtube-nocookie.com", "youtube"),
    ("bilibili.com", "bilibili"),
    ("b23.tv", "bilibili"),
    ("bilibili.tv", "bilibili"),
    ("twitter.com", "twitter"),
    ("x.com", "twitter"),
    ("douyin.com", "douyin"),
    ("iesdouyin.com", "douyin"),
    ("douyin.cn", "douyin"),
    ("xiaohongshu.com", "xiaohongshu"),
    ("xhslink.com", "xiaohongshu"),
    ("channels.weixin.qq.com", "wechat"),
    ("weixin.qq.com", "wechat"),
    ("finder.video.qq.com", "wechat"),
    ("mp.weixin.qq.com", "wechat"),
)

COOKIE_LABELS = {
    "global": "全局",
    "youtube": "YouTube",
    "bilibili": "哔哩哔哩",
    "twitter": "X / Twitter",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "wechat": "视频号",
    "custom": "自定义",
}

PRESET_COOKIE_KEYS = (
    "global",
    "youtube",
    "bilibili",
    "twitter",
    "douyin",
    "xiaohongshu",
    "wechat",
)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def classify(url: str) -> Site:
    host = _host(url)
    for domain, key in _HOSTS:
        if host == domain or host.endswith("." + domain):
            return SITES[key]
    label = host or "未知站点"
    return Site(
        "other",
        label,
        False,
        "会交给 yt-dlp 尝试。失败时可以上传该站的 Cookie 再试。",
    )


def site_from_extractor(extractor_key: str | None) -> Site | None:
    key = (extractor_key or "").lower()
    if not key:
        return None
    if "youtube" in key:
        return SITES["youtube"]
    if "bili" in key:
        return SITES["bilibili"]
    if "twitter" in key:
        return SITES["twitter"]
    if "douyin" in key:
        return SITES["douyin"]
    if "xiaohongshu" in key or "redbook" in key:
        return SITES["xiaohongshu"]
    if "weixin" in key or "wechat" in key:
        return SITES["wechat"]
    return None


def describe(url: str, *, cookie_ready: bool, cookie_source: str | None) -> dict:
    site = classify(url)
    return {
        "ok": True,
        "error": None,
        "site_key": site.key,
        "site_label": site.label,
        "needs_cookies_likely": site.needs_cookies_likely,
        "hint": site.hint,
        "cookie_ready": cookie_ready,
        "cookie_source": cookie_source,
    }
