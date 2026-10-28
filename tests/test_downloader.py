import threading
from pathlib import Path

from app import db
from app.downloader import run_job


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def download(self, urls):
        info = {
            "id": "abc",
            "title": "示例视频",
            "extractor_key": "Youtube",
            "webpage_url": urls[0],
            "duration": 15,
            "is_live": False,
            "filesize": 1200,
            "_type": "video",
            "ext": "mp4",
        }
        match_filter = self.opts.get("match_filter")
        if match_filter:
            match_filter(info, incomplete=False)
        home = Path(self.opts["paths"]["home"])
        home.mkdir(parents=True, exist_ok=True)
        for hook in self.opts.get("progress_hooks") or []:
            hook(
                {
                    "status": "downloading",
                    "filename": str(home / "media.mp4"),
                    "downloaded_bytes": 600,
                    "total_bytes": 1200,
                    "speed": 24000,
                    "eta": 2,
                }
            )
        (home / "media.mp4.part").write_bytes(b"junk")
        (home / "media.mp4").write_bytes(b"x" * 1200)


class LiveYDL(FakeYDL):
    def download(self, urls):
        match_filter = self.opts.get("match_filter")
        match_filter(
            {"_type": "video", "is_live": True, "title": "直播", "webpage_url": urls[0]},
            incomplete=False,
        )


def _events():
    seen = []

    def publish(job_id, event, data):
        seen.append((job_id, event, data["status"]))

    return seen, publish


def test_fake_download_completes(monkeypatch):
    monkeypatch.setattr("app.downloader.yt_dlp.YoutubeDL", FakeYDL)
    job = db.insert_job(
        url="https://www.youtube.com/watch?v=abc",
        fmt="mp4",
        quality="1080",
        cookie_id=None,
        site_key="youtube",
        site_label="YouTube",
    )
    seen, publish = _events()
    run_job(job["id"], threading.Event(), publish)
    saved = db.get_job(job["id"])
    assert saved["status"] == "completed"
    assert saved["title"] == "示例视频"
    assert saved["file_size"] == 1200
    assert Path(saved["file_path"]).read_bytes() == b"x" * 1200
    assert not Path(saved["file_path"]).with_suffix(".mp4.part").exists()
    assert seen[-1][1] == "done"


def test_live_video_fails_clearly(monkeypatch):
    monkeypatch.setattr("app.downloader.yt_dlp.YoutubeDL", LiveYDL)
    job = db.insert_job(
        url="https://www.youtube.com/watch?v=live",
        fmt="mp4",
        quality="best",
        cookie_id=None,
        site_key="youtube",
        site_label="YouTube",
    )
    run_job(job["id"], threading.Event(), lambda *_args: None)
    saved = db.get_job(job["id"])
    assert saved["status"] == "failed"
    assert "直播" in saved["error"]


def test_duration_limit(monkeypatch):
    monkeypatch.setenv("MAX_DURATION_SEC", "10")
    monkeypatch.setattr("app.downloader.yt_dlp.YoutubeDL", FakeYDL)
    job = db.insert_job(
        url="https://www.youtube.com/watch?v=long",
        fmt="best",
        quality="best",
        cookie_id=None,
        site_key="youtube",
        site_label="YouTube",
    )
    run_job(job["id"], threading.Event(), lambda *_args: None)
    saved = db.get_job(job["id"])
    assert saved["status"] == "failed"
    assert "时长" in saved["error"]
