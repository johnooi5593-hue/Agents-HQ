"""t206: the automatic phone copy. Every finished reel reaches the owner's phone as 1080p and at most 30 MB
(re-encoded at about 3.5 Mbit/s when over, never 720p)."""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media_check  # noqa: E402
import phone_copy  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
OK = {"ok": True, "video": "h264", "audio": "aac", "faststart": True, "width": 1080, "height": 1920, "duration": 45.0}


class DecisionTests(unittest.TestCase):
    def test_when_a_copy_is_needed(self):
        self.assertFalse(phone_copy.needs_copy(20 << 20, OK)[0])
        self.assertTrue(phone_copy.needs_copy(31 << 20, OK)[0])
        self.assertTrue(phone_copy.needs_copy(5 << 20, {**OK, "video": "hevc"})[0])
        self.assertTrue(phone_copy.needs_copy(5 << 20, {**OK, "audio": "pcm_s16le"})[0])
        self.assertTrue(phone_copy.needs_copy(5 << 20, {**OK, "faststart": False})[0])
        self.assertFalse(phone_copy.needs_copy(5 << 20, {**OK, "audio": ""})[0])          # a silent reel is fine

    def test_bitrate_fits_30_mb_but_never_starves(self):
        self.assertEqual(phone_copy.video_kbps(45), 3500)
        self.assertEqual(phone_copy.video_kbps(None), 3500)
        long = phone_copy.video_kbps(120)
        self.assertLess(long, 3500)
        self.assertLessEqual((long + 160) * 1000 * 120 / 8, 30 << 20)
        self.assertEqual(phone_copy.video_kbps(3600), 1500)

    def test_command_keeps_1080p(self):
        cmd = phone_copy.command("ffmpeg", "in.mp4", "out.part", OK)
        s = " ".join(cmd)
        for part in ("-c:v libx264", "-b:v 3500k", "-maxrate 4000k", "-bufsize 7000k", "-c:a aac", "-b:a 160k", "-movflags +faststart", "-f mp4"):
            self.assertIn(part, s)
        self.assertNotIn("-vf", cmd)                                   # the same resolution
        big = phone_copy.command("ffmpeg", "in.mp4", "out.part", {**OK, "width": 2160, "height": 3840})
        self.assertEqual(big[big.index("-vf") + 1], "scale=1080:-2")   # 4K comes down to 1080, never to 720
        wide = phone_copy.command("ffmpeg", "in.mp4", "out.part", {**OK, "width": 3840, "height": 2160})
        self.assertEqual(wide[wide.index("-vf") + 1], "scale=-2:1080")


class MakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = Path(self.temp.name) / "clip"
        self.d.mkdir()
        self.work = Path(self.temp.name) / "work"
        self.patch = mock.patch.object(phone_copy, "WORK", str(self.work))
        self.patch.start()
        self.edit = self.d / "edit.mp4"
        self.edit.write_bytes(b"\x00" * 1000)
        t = time.time() - 600
        os.utime(self.edit, (t, t))

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def fake_run(self, calls):
        def run(cmd, **kw):
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"phone" * 100)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        return run

    def test_big_edit_gets_a_copy_once(self):
        calls, probe = [], lambda p: {**OK}
        with mock.patch.object(phone_copy, "ffmpeg_path", return_value="ffmpeg"), mock.patch.object(phone_copy, "LIMIT", 500):
            r = phone_copy.make(str(self.d), run=self.fake_run(calls), probe=probe)
            self.assertEqual(r["status"], "made")
            self.assertTrue((self.d / "phone.mp4").is_file())
            self.assertEqual(phone_copy.make(str(self.edit), run=self.fake_run(calls), probe=probe)["status"], "current")
            self.assertEqual(len(calls), 1)                            # idempotent
            st = phone_copy.state(str(self.d))
            self.assertEqual((st["file"], st["ready"]), ("phone.mp4", True))
            t = time.time() + 5                                         # a re-render: the copy is out of date
            os.utime(self.edit, (t, t))
            self.assertFalse(phone_copy.current(str(self.d)))
        self.assertEqual(list(self.d.glob("*.part")), [])               # the half-written file never sits in the folder

    def test_small_phone_ready_edit_needs_nothing(self):
        r = phone_copy.make(str(self.d), run=self.fake_run([]), probe=lambda p: {**OK})
        self.assertEqual(r["status"], "not-needed")
        self.assertFalse((self.d / "phone.mp4").exists())

    def test_broken_or_missing_video(self):
        self.assertEqual(phone_copy.make(str(self.d), probe=lambda p: {"ok": False, "error": "moov atom not found"})["status"], "broken")
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        self.assertEqual(phone_copy.make(str(empty))["status"], "no-video")

    def test_no_ffmpeg(self):
        with mock.patch.object(phone_copy, "ffmpeg_path", return_value=None):
            self.assertEqual(phone_copy.make(str(self.d), probe=lambda p: {**OK, "video": "hevc"})["status"], "no-ffmpeg")

    def test_worker_runs_one_job_at_a_time_in_the_background(self):
        gate, seen, active, most = threading.Event(), [], [0], [0]

        def maker(folder, stop=None):
            active[0] += 1; most[0] = max(most[0], active[0]); seen.append(folder)
            gate.wait(5)
            active[0] -= 1
            return {"status": "made"}
        other = Path(self.temp.name) / "clip2"
        other.mkdir()
        (other / "edit.mp4").write_bytes(b"x")
        jobs = phone_copy.PhoneJobs(maker, log=lambda m: None)
        self.assertTrue(jobs.want(str(self.d)))                        # returns at once: the request is never blocked
        self.assertFalse(jobs.want(str(self.d)))                       # already in line or being made
        self.assertTrue(jobs.want(str(other)))
        self.assertTrue(jobs.making(str(other)))
        gate.set()
        for _ in range(100):
            if len(seen) == 2 and not jobs.making(str(other)):
                break
            time.sleep(0.05)
        self.assertEqual(len(seen), 2)
        self.assertEqual(most[0], 1)
        self.assertFalse(jobs.want(str(self.d)))                       # tried for this version already

    def test_release_ends_the_running_job(self):
        started = threading.Event()

        def maker(folder, stop=None):
            started.set()
            stop.wait(5)
            return {"status": "failed", "error": "stopped"}
        jobs = phone_copy.PhoneJobs(maker, log=lambda m: None)
        jobs.want(str(self.d))
        self.assertTrue(started.wait(5))
        t = time.time()
        jobs.release(str(self.d))
        self.assertLess(time.time() - t, 5)
        self.assertFalse(jobs.making(str(self.d)))

    @unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg not installed")
    def test_real_one_second_clip(self):
        src = self.d / "edit.mp4"                                       # ffmpeg's default: moov at the end, not faststart
        subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=25:duration=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(src)], check=True, capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
        t = time.time() - 600
        os.utime(src, (t, t))
        media_check._cache.clear()
        self.assertFalse(media_check.probe(str(src))["faststart"])
        with mock.patch.object(phone_copy, "LOW_PRIORITY", phone_copy.NO_WINDOW):   # the test runs next to the owner's renders
            r = phone_copy.make(str(self.d))
        self.assertEqual(r["status"], "made", r)
        info = media_check.probe(str(self.d / "phone.mp4"))
        self.assertEqual((info["video"], info["audio"], info["width"], info["height"], info["faststart"]), ("h264", "aac", 320, 568, True))
        self.assertEqual(subprocess.run([sys.executable, str(Path(phone_copy.__file__)), str(self.d)], capture_output=True, text=True,
                                        env={**os.environ}).stdout.count('"status": "current"'), 1)


class PostingNeverUsesThePhoneCopyTests(unittest.TestCase):
    """Only the approved edit.mp4 is ever posted: phone.mp4 is not offered on the posting screen and is refused."""

    def setUp(self):
        import publish
        self.publish = publish
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.d = self.root / "approved" / "clip"
        self.d.mkdir(parents=True)
        for n in ("edit.mp4", "phone.mp4", "cover-codex.png"):
            (self.d / n).write_bytes(b"x")

    def tearDown(self):
        self.temp.cleanup()

    def test_posting_screen_lists_only_the_edit(self):
        f = self.publish.media_files(str(self.d))
        self.assertEqual(f["video"], ["edit.mp4"])
        self.assertEqual(self.publish.media(str(self.d))[0], str(self.d / "edit.mp4"))

    def test_phone_copy_is_refused(self):
        pub = self.publish.Publisher(str(self.root), accounts=None)
        with self.assertRaisesRegex(self.publish.PostError, "not in this folder"):
            pub.start(str(self.d), {"facebook": {}}, video_name="phone.mp4")

    def test_a_folder_with_only_a_phone_copy_has_nothing_to_post(self):
        (self.d / "edit.mp4").rename(self.d / "edit-old.mov.bak")
        self.assertEqual(self.publish.media_files(str(self.d))["video"], [])
        other = self.root / "approved" / "thumbs"
        other.mkdir()
        (other / "post.md").write_text("Video: approved/clip/phone.mp4", encoding="utf-8")
        self.assertEqual(self.publish.media_files(str(other))["video"], [])   # never linked from another folder either

    def test_same_rule_as_the_package(self):
        import video_package
        for n in ("phone.mp4", "PHONE.MP4", "edit-phone.mp4", "phone_1080.mp4", "edit.phone.mp4"):
            self.assertTrue(self.publish.PHONE_COPY.search(n), n)
            self.assertTrue(video_package.NOT_FINAL.search(n), n)
        for n in ("edit.mp4", "iphone-demo.mp4", "final.mp4", "headphones.mp4"):
            self.assertFalse(self.publish.PHONE_COPY.search(n), n)


if __name__ == "__main__":
    unittest.main()
