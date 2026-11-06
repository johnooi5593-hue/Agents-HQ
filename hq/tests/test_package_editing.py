"""Approve video waits until the edit is really finished (CAN 1106 #3, 2026-11-06: notes.md landed in out/ before the
video, and the panel already offered Approve video)."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from thumbnail_design import DesignError
from video_package import Packages


class Thumbs:
    def __init__(self):
        import threading
        self.lock = threading.RLock()

    def _load(self):
        return {"jobs": {}, "templates": {}}

    def _source(self, folder, list_videos=False):
        return None, None, ""


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks = []
        self.pk = Packages(str(self.root), Thumbs(), lambda b: (200, {}), lambda n: (200, {}), lambda: {"tasks": self.tasks},
                           lambda p: None)
        self.d = self.root / "out" / "clip"
        self.d.mkdir(parents=True)
        (self.d / "notes.md").write_text("notes", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def video(self, age):
        f = self.d / "edit.mp4"
        f.write_bytes(b"v")
        t = time.time() - age
        os.utime(f, (t, t))

    def test_notes_only_is_still_editing(self):
        st = self.pk.state("clip")
        self.assertTrue(st["editing"])
        self.assertFalse(st["done"]["video"])
        with self.assertRaises(DesignError):
            self.pk.action({"name": "clip", "action": "video-ok"})

    def test_video_still_being_copied(self):
        self.video(age=1)
        self.assertTrue(self.pk.state("clip")["editing"])

    def test_running_edit_task_blocks(self):
        self.video(age=600)
        self.tasks.append({"id": "t1", "status": "doing", "progress": 85, "note": "out:clip parent:t0",
                           "updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())})
        st = self.pk.state("clip")
        self.assertTrue(st["editing"])
        self.assertEqual(st["editProgress"], 85)
        with self.assertRaises(DesignError):
            self.pk.action({"name": "clip", "action": "video-ok"})

    def test_finished_video_can_be_approved(self):
        self.video(age=600)
        self.tasks.append({"id": "t1", "status": "review", "note": "out:clip"})
        self.assertFalse(self.pk.state("clip")["editing"])
        st = self.pk.action({"name": "clip", "action": "video-ok"})
        self.assertTrue(st["done"]["video"])

    def test_dead_run_does_not_block_forever(self):
        self.video(age=3600)
        old = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 3600))
        self.tasks.append({"id": "t1", "status": "doing", "progress": 85, "note": "out:clip", "updated": old})
        self.assertFalse(self.pk.state("clip")["editing"])
        fresh = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        self.tasks[0]["updated"] = fresh
        self.pk._task_cache = None
        self.assertTrue(self.pk.state("clip")["editing"])

    def test_clean_copy_alone_is_not_finished(self):
        f = self.d / "clean.mp4"
        f.write_bytes(b"v")
        os.utime(f, (time.time() - 600,) * 2)
        st = self.pk.state("clip")
        self.assertTrue(st["editing"])
        self.assertFalse(st["editRunning"])

    def test_reedit_copy_needs_a_new_ok(self):
        self.video(age=600)
        (self.d / "package.json").write_text('{"preset": "full", "videoOkAt": %d}' % (time.time() - 3000), encoding="utf-8")
        self.assertFalse(self.pk.state("clip")["done"]["video"])   # the OK was for the older video
        self.tasks.append({"id": "t1", "status": "doing", "note": "out:clip", "updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())})
        self.pk._task_cache = None
        with self.assertRaises(DesignError):
            self.pk.action({"name": "clip", "action": "video-ok"})
        self.tasks.clear()
        self.pk._task_cache = None
        self.assertTrue(self.pk.action({"name": "clip", "action": "video-ok"})["done"]["video"])

    def test_approved_folder_keeps_its_ok(self):
        a = self.root / "approved" / "old"
        (a / "sub").mkdir(parents=True)                             # its video lives in a subfolder
        (a / "package.json").write_text('{"preset": "video", "videoOkAt": 1}', encoding="utf-8")
        st = self.pk.state("old")
        self.assertFalse(st["editing"])
        self.assertTrue(st["done"]["video"])

    def test_other_video_task_does_not_block(self):
        self.video(age=600)
        self.tasks.append({"id": "t2", "status": "doing", "note": "out:clip-v2"})
        self.assertFalse(self.pk.state("clip")["editing"])


if __name__ == "__main__":
    unittest.main()
