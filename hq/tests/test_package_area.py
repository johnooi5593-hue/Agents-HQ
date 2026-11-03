"""An approved video's package lives in approved/<name>; a leftover out/<name> without a video must not hide it
(PJ 1101 #3, 2026-11-03: new captions were written into a stray out/ copy and the review panel lost its video)."""
import json
import tempfile
import unittest
from pathlib import Path

import status
from video_package import Packages


class Thumbs:
    def __init__(self):
        import threading
        self.lock = threading.RLock()

    def _load(self):
        return {"jobs": {}, "templates": {}}

    def _source(self, folder, list_videos=False):
        return None, None, ""


class PackageAreaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prompts = []
        self.pk = Packages(str(self.root), Thumbs(), lambda b: (200, {}), lambda n: (200, {}), lambda: {"tasks": []},
                           self.prompts.append)
        self.approved = self.root / "approved" / "clip"
        self.approved.mkdir(parents=True)
        (self.approved / "edit.mp4").write_bytes(b"v")
        (self.approved / "package.json").write_text(json.dumps({"preset": "full", "caption": 1}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_approved_only(self):
        self.assertEqual(self.pk._area("clip"), "approved")
        self.assertEqual(self.pk.read("clip")["caption"], 1)

    def test_leftover_out_copy_is_ignored(self):
        stray = self.root / "out" / "clip"
        stray.mkdir(parents=True)
        (stray / "post.md").write_text("old", encoding="utf-8")
        self.assertEqual(self.pk._area("clip"), "approved")
        self.pk.action({"name": "clip", "action": "write-captions"})
        self.assertIn("write approved/clip/post.md", self.prompts[-1])
        self.assertNotIn("caption", json.loads((self.approved / "package.json").read_text(encoding="utf-8")))
        self.assertFalse((stray / "package.json").exists())
        self.assertNotIn("clip", status.work_folders(str(self.root / "out")))

    def test_out_with_video_still_wins(self):
        out = self.root / "out" / "clip"
        out.mkdir(parents=True)
        (out / "edit.mp4").write_bytes(b"v2")
        self.assertEqual(self.pk._area("clip"), "out")
        self.assertIn("clip", status.work_folders(str(self.root / "out")))


if __name__ == "__main__":
    unittest.main()
