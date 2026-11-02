import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish


class FakeAccounts:
    def get(self, kind, channel=""):
        return {"page_token": "t", "ig_id": "ig", "page_id": "p"}


class InstagramUploadTests(unittest.TestCase):
    """Instagram refused Reels with a 3:4 cover (2026-11-02): try without the cover, then again later by itself."""

    def setUp(self):
        self.pub = publish.Publisher(tempfile.mkdtemp(), FakeAccounts())
        self.calls = []
        mock.patch.object(publish.time, "sleep", lambda s: None).start()
        mock.patch.object(publish, "http", lambda *a, **k: (200, {}, {"id": "media1"})).start()
        mock.patch.object(self.pub, "cover_url", lambda cover, m, parked: "https://cdn/cover.jpg").start()
        self.addCleanup(mock.patch.stopall)

    def direct(self, takes):
        """ig_direct that takes an upload only when takes(params) is true."""
        def fake(video, params, m, wait=True):
            self.calls.append("cover" if "cover_url" in params else "plain")
            return ("c1", None) if takes(params) else (None, "upload refused")
        mock.patch.object(self.pub, "ig_direct", fake).start()

    def test_refused_with_the_cover_posts_without_it(self):
        self.direct(lambda p: "cover_url" not in p)
        link, extra = self.pub.post_instagram_file("v.mp4", "c.jpg", {"caption": "hi"}, FakeAccounts().get("meta"))
        self.assertEqual(self.calls, ["cover", "cover", "plain"])
        self.assertIn("without your cover", extra["warning"])

    def test_the_cover_is_kept_when_instagram_takes_it(self):
        self.direct(lambda p: True)
        _, extra = self.pub.post_instagram_file("v.mp4", "c.jpg", {"caption": "hi"}, FakeAccounts().get("meta"))
        self.assertEqual(self.calls, ["cover"])
        self.assertNotIn("warning", extra)

    def test_refused_every_way_is_a_refusal_to_try_later(self):
        self.direct(lambda p: False)
        with self.assertRaises(publish.IgRefused):
            self.pub.post_instagram_file("v.mp4", "c.jpg", {"caption": "hi"}, FakeAccounts().get("meta"))
        self.assertEqual(self.calls, ["cover", "cover", "plain", "plain"])

    def test_a_refusal_is_tried_again_later_then_fails_with_a_reason(self):
        folder = tempfile.mkdtemp()
        job = {"text": {"caption": "hi"}, "video": "edit.mp4", "cover": "cover.jpg"}
        self.pub.later(folder, "instagram", job, "refused", now=1000)
        r = self.pub.record(folder)["instagram"]
        self.assertEqual((r["state"], r["when"], r["job"]["tries"]), ("scheduled", 1000 + publish.IG_LATER[0], 1))
        self.assertIn("tries again by itself", r["warning"])
        for _ in publish.IG_LATER[1:]:
            self.pub.later(folder, "instagram", self.pub.record(folder)["instagram"]["job"], "refused", now=1000)
        self.pub.later(folder, "instagram", self.pub.record(folder)["instagram"]["job"], "refused", now=1000)
        r = self.pub.record(folder)["instagram"]
        self.assertEqual(r["state"], "failed")
        self.assertIn("by hand", r["error"])

    def test_the_scheduler_retries_a_refused_post_when_due(self):
        root = Path(self.pub.root)
        folder = root / "approved" / "clip"
        folder.mkdir(parents=True)
        (folder / "edit.mp4").write_bytes(b"v")
        self.pub.later(str(folder), "instagram", {"text": {"caption": "hi"}, "video": "edit.mp4", "cover": ""}, "refused", now=1000)
        sent = []
        mock.patch.object(self.pub, "send", lambda p, video, cover, text, when, ch: sent.append(p) or ("https://ig/1", {})).start()
        self.pub.run_due(now=1000 + publish.IG_LATER[0] + 1)
        r = self.pub.record(str(folder))["instagram"]
        self.assertEqual((sent, r["state"], r["link"], r.get("warning")), (["instagram"], "posted", "https://ig/1", ""))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class ReelCoverTests(unittest.TestCase):
    def size(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.strip()
        return tuple(int(x) for x in out.split(","))

    def test_a_3x4_cover_becomes_a_9x16_reel_cover(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, "cover-codex-ig.png")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=1080x1440", "-frames:v", "1", src], check=True)
        reel, plain = publish.cover_jpeg(src, reel=True), publish.cover_jpeg(src)
        try:
            self.assertEqual(self.size(reel), (1080, 1920))
            self.assertEqual(self.size(plain), (1080, 1440))
        finally:
            os.remove(reel)
            os.remove(plain)


if __name__ == "__main__":
    unittest.main()
