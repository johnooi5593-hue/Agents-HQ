"""t205: the dead-run watchdog and the broken-video check. A clip-editor run died mid-render (2026-11-08 19:34) and
the board showed "doing 85%" for an hour next to an edit.mp4 without its moov atom."""
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
import media_check  # noqa: E402
import stall_watch  # noqa: E402
from video_package import Packages, final_videos, settled_video  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind.encode() + payload


class StallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = time.time()
        self.old = iso(self.now - 30 * 60)
        self.out = self.root / "out" / "clip"
        self.out.mkdir(parents=True)
        f = self.out / "notes.md"
        f.write_text("x", encoding="utf-8")
        age(f, 40 * 60)
        age(self.out, 40 * 60)                                       # the folder's own mtime counts as a change too

    def tearDown(self):
        self.temp.cleanup()

    def task(self, **kw):
        return {"id": "t1", "status": "doing", "progress": 85, "note": "out:clip", "team": "Creative", "updated": self.old, **kw}

    def test_silent_task_with_quiet_folder_is_stalled(self):
        found = stall_watch.stalled([self.task()], set(), str(self.root), self.now, 8 * 60)
        self.assertIn("t1", found)
        self.assertLess(self.now - found["t1"], 41 * 60)

    def test_recent_update_is_not_stalled(self):
        self.assertEqual(stall_watch.stalled([self.task(updated=iso(self.now - 60))], set(), str(self.root), self.now, 480), {})

    def test_live_run_is_not_stalled(self):
        self.assertEqual(stall_watch.stalled([self.task()], {"t1"}, str(self.root), self.now, 480), {})

    def test_growing_file_in_out_folder_is_not_stalled(self):
        (self.out / "frame_0001.png").write_bytes(b"x")              # a render writing frames right now
        self.assertEqual(stall_watch.stalled([self.task()], set(), str(self.root), self.now, 480), {})

    def test_growing_file_in_work_folder_is_not_stalled(self):
        w = self.root / "work" / "creative" / "clip-render"
        w.mkdir(parents=True)
        (w / "part.mp4").write_bytes(b"x")
        self.assertEqual(stall_watch.stalled([self.task()], set(), str(self.root), self.now, 480), {})

    def test_other_statuses_and_posts_are_never_stalled(self):
        tasks = [self.task(id="t2", status="review"), self.task(id="t3", status="todo"), self.task(id="t4", kind="post")]
        self.assertEqual(stall_watch.stalled(tasks, set(), str(self.root), self.now, 480), {})

    def test_task_without_folder_needs_an_ended_run(self):
        t = self.task(id="t9", note="")
        self.assertEqual(stall_watch.stalled([t], set(), str(self.root), self.now, 480), {})          # age alone: no
        self.assertIn("t9", stall_watch.stalled([t], set(), str(self.root), self.now, 480, ended={"t9"}))

    def test_env_sets_the_minutes(self):
        with mock.patch.dict(os.environ, {"HQ_STALL_MIN": "12"}):
            self.assertEqual(stall_watch.stall_seconds(), 720)
        with mock.patch.dict(os.environ, {"HQ_STALL_MIN": "soon"}):
            self.assertEqual(stall_watch.stall_seconds(), 1200)                # the default is 20 min
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HQ_STALL_MIN", None)
            self.assertEqual(stall_watch.stall_seconds(), 1200)

    def test_one_event_per_stall_and_payload_flags(self):
        events = self.root / "events.jsonl"
        events.write_text('{"ts":1,"event":"start","agent":"clip-editor","id":"a"}\n', encoding="utf-8")
        wd = stall_watch.Watchdog(str(self.root), str(events), live=lambda: set())
        tasks = [self.task(), self.task(id="t2", updated=iso(self.now))]
        wd.mark(tasks, self.now)
        wd.mark(tasks, self.now + 5)                                 # the next poll: no second line
        lines = [json.loads(x) for x in events.read_text(encoding="utf-8").splitlines()]
        stalls = [e for e in lines if e["event"] == "stalled"]
        self.assertEqual(len(stalls), 1)
        self.assertEqual(stalls[0]["task"], "t1")
        self.assertEqual(stalls[0]["out"], "clip")
        self.assertTrue(tasks[0]["stalled"])
        self.assertGreaterEqual(tasks[0]["stalled_min"], 20)
        self.assertTrue(tasks[0]["stalled_since"].endswith("Z"))
        self.assertFalse(tasks[1]["stalled"])
        # a restarted server reads the feed and does not write the same stall again
        again = stall_watch.Watchdog(str(self.root), str(events), live=lambda: set())
        again.mark([self.task()], self.now + 10)
        self.assertEqual(sum(1 for x in events.read_text(encoding="utf-8").splitlines() if '"stalled"' in x), 1)
        # it moves again, then dies again: a new stall, a new line
        moved = self.task(updated=iso(self.now))
        again.mark([moved], self.now + 20)
        self.assertFalse(moved["stalled"])
        again.mark([self.task(updated=iso(self.now))], self.now + 30 * 60)
        self.assertEqual(sum(1 for x in events.read_text(encoding="utf-8").splitlines() if '"stalled"' in x), 2)

    def test_live_callback_errors_do_not_break_the_board(self):
        def boom():
            raise RuntimeError("desk gone")
        wd = stall_watch.Watchdog(str(self.root), str(self.root / "e.jsonl"), live=boom)
        self.assertIn("t1", wd.mark([self.task()], self.now))


class BrokenVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name)
        media_check._cache.clear()

    def tearDown(self):
        self.temp.cleanup()

    def no_moov(self, name="edit.mp4"):
        f = self.d / name
        f.write_bytes(box("ftyp", b"isom\x00\x00\x02\x00isomiso2") + box("mdat", b"\x00" * 4000))
        age(f, 600)
        return f

    def test_box_check_without_ffprobe(self):
        f = self.no_moov()
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            r = media_check.probe(str(f))
        self.assertFalse(r["ok"])
        self.assertIn("moov", r["error"])
        good = self.d / "good.mp4"
        good.write_bytes(box("ftyp", b"isom") + box("moov", b"\x00" * 16) + box("mdat", b"\x00" * 64))
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            self.assertTrue(media_check.probe(str(good))["ok"])
        self.assertTrue(media_check.faststart(str(good)))
        cut = self.d / "cut.mp4"
        cut.write_bytes(box("ftyp", b"isom") + (5000).to_bytes(4, "big") + b"mdat" + b"\x00" * 100)
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            self.assertFalse(media_check.probe(str(cut))["ok"])
        other = self.d / "x.webm"
        other.write_bytes(b"whatever")
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            self.assertIsNone(media_check.probe(str(other))["ok"])
            self.assertTrue(media_check.readable(str(other)))         # unknown counts as a video

    def test_ffprobe_answer_is_cached_per_version(self):
        f = self.no_moov()
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "moov atom not found")
        with mock.patch.object(media_check, "ffprobe_path", return_value="ffprobe"):
            self.assertFalse(media_check.probe(str(f), run=run)["ok"])
            self.assertFalse(media_check.probe(str(f), run=run)["ok"])
            self.assertEqual(len(calls), 1)
            with open(f, "ab") as h:                                    # a new version of the file: asked again
                h.write(b"\x00")
            age(f, 600)
            media_check.probe(str(f), run=run)
            self.assertEqual(len(calls), 2)

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_truncated_real_mp4_is_broken(self):
        good = self.d / "full.mp4"
        subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(good)], check=True, capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
        data = good.read_bytes()
        moov = data.find(b"moov")
        self.assertGreater(moov, data.find(b"mdat"))                   # ffmpeg writes moov last: cut it off
        broken = self.d / "edit.mp4"
        broken.write_bytes(data[:moov - 4])
        age(broken, 600)
        self.assertTrue(media_check.probe(str(good))["ok"])
        self.assertEqual(media_check.probe(str(good))["video"], "h264")
        self.assertFalse(media_check.probe(str(broken))["ok"])
        self.assertFalse(media_check.readable(str(broken)))

    def test_broken_edit_is_no_finished_video(self):
        self.no_moov()
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            self.assertEqual(final_videos(str(self.d), media_check.readable), [])
            self.assertFalse(settled_video(str(self.d), valid=media_check.readable))
            self.assertEqual(final_videos(str(self.d)), ["edit.mp4"])     # without the check: as before
            self.assertTrue(settled_video(str(self.d)))

    def test_package_shows_no_video_yet_with_a_hint(self):
        class Thumbs:
            import threading
            lock = threading.RLock()

            def _load(self):
                return {"jobs": {}, "templates": {}}

            def _source(self, folder, list_videos=False):
                return None, None, ""
        out = self.d / "out" / "clip"
        out.mkdir(parents=True)
        f = out / "edit.mp4"
        f.write_bytes(box("ftyp", b"isom") + box("mdat", b"\x00" * 64))
        age(f, 600)
        pk = Packages(str(self.d), Thumbs(), lambda b: (200, {}), lambda n: (200, {}), lambda: {"tasks": []}, lambda p: None,
                      valid=media_check.readable)
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            st = pk.state("clip")
            self.assertTrue(st["editing"])
            self.assertFalse(st["done"]["video"])
            self.assertEqual(st["broken"], ["edit.mp4"])
            self.assertEqual(st["brokenHint"], "broken file - re-render")
            self.assertIsNone(st["phone"])
            f.write_bytes(box("ftyp", b"isom") + box("moov", b"\x00" * 8) + box("mdat", b"\x00" * 64))   # re-rendered
            age(f, 600)
            st = pk.state("clip")
            self.assertFalse(st["editing"])
            self.assertEqual(st["broken"], [])


if __name__ == "__main__":
    unittest.main()
