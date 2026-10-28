from __future__ import annotations


def build_format(fmt: str, quality: str) -> dict:
    """yt-dlp format selectors.

    MP4 prefers H.264/AAC and remuxes when possible. 最佳可用 merges into MKV
    so VP9/AV1 do not have to be re-encoded.
    """
    height = "" if quality == "best" else f"[height<={quality}]"
    if fmt == "mp3":
        return {
            "format": "ba/b",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    if fmt == "m4a":
        return {
            "format": "ba[ext=m4a]/ba/b",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "192",
                }
            ],
        }
    if fmt == "best":
        return {
            "format": f"bv*{height}+ba/b{height}/b",
            "merge_output_format": "mkv",
        }
    return {
        "format": (
            f"bv*[vcodec^=avc1]{height}+ba[acodec^=mp4a]/"
            f"bv*[vcodec^=avc1]{height}+ba/"
            f"bv*{height}+ba/b{height}/b"
        ),
        "merge_output_format": "mp4",
        "postprocessors": [
            {
                "key": "FFmpegVideoRemuxer",
                # yt-dlp's public option keeps this spelling.
                "preferedformat": "mp4",
            }
        ],
    }
