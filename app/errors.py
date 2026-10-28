class UrlError(ValueError):
    """The pasted URL is missing, malformed, or not allowed."""


class JobError(Exception):
    def __init__(self, message: str, *, needs_cookies: bool = False, detail: str = ""):
        super().__init__(message)
        self.needs_cookies = needs_cookies
        self.detail = detail or message


class CookieFormatError(ValueError):
    """Uploaded text is not a Netscape cookie file."""


class TooManyJobs(Exception):
    """Too many downloads are already queued."""


COOKIE_SITES = {"douyin", "xiaohongshu", "wechat"}

_COOKIE_MARKERS = (
    "cookie",
    "cookies",
    "sign in",
    "signin",
    "login required",
    "logged in",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "not a bot",
    "http error 403",
    "forbidden",
    "fresh cookies",
    "use --cookies",
)

_UNAVAILABLE_MARKERS = (
    "private video",
    "video unavailable",
    "this video is unavailable",
    "has been removed",
    "members-only",
    "members only",
    "join this channel",
)


def humanize_error(exc: BaseException, site_key: str | None) -> tuple[str, str, bool]:
    raw = str(exc).strip() or exc.__class__.__name__
    low = raw.lower()
    detail = raw[:800]
    if any(marker in low for marker in _UNAVAILABLE_MARKERS):
        return "这个视频目前不可用，可能已删除、设为私密，或你的账号没有观看权限。", detail, False
    if "playlist" in low and "unsupported url" not in low:
        return "请粘贴单个视频链接，暂不支持整份播放列表。", detail, False
    if "larger than max" in low or "max-filesize" in low or "文件大小超过" in raw:
        return "文件超过大小限制。可以调低清晰度，或提高 MAX_FILESIZE_MB。", detail, False
    if "412" in low or "precondition failed" in low:
        return "站点拒绝了这次请求。可以上传该站点的 Cookie 后再试，或稍后再试。", detail, True
    if "timed out" in low or "timeout" in low or "unable to download webpage" in low:
        return "网络超时或页面打不开。可以重试，或检查这台服务器能否访问该站点。", detail, False
    if "remux" in low or "postprocessing" in low or "conversion failed" in low:
        return "封装或转码失败。可以改用「最佳可用」，或确认服务器已安装 ffmpeg。", detail, False
    cookie_hit = any(marker in low for marker in _COOKIE_MARKERS)
    if cookie_hit or (site_key in COOKIE_SITES and ("403" in low or "401" in low)):
        return "站点要求登录。请上传该站点的 cookies.txt 后再试。", detail, True
    if "unsupported url" in low or "no suitable extractor" in low:
        if site_key in COOKIE_SITES:
            return "暂时解析不了。这个站点通常需要浏览器 Cookie，上传后再试一次。", detail, True
        return "yt-dlp 无法识别这个链接。", detail, False
    if "requested format is not available" in low:
        return "没有符合所选清晰度或格式的流。可以改成「最佳」或「最佳可用」。", detail, False
    if site_key in COOKIE_SITES:
        return "下载失败。这个站点经常需要你自己的 Cookie，上传后再试。", detail, True
    return "下载失败。可以更换格式或清晰度，或为该站点上传 Cookie 后重试。", detail, False
