"""The 2026-11-09 security review (FIX, items 1-6) and code review (A1-A14) of the HQ 1108 upgrade: one test per
finding where a test makes sense."""
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HQ = Path(__file__).resolve().parents[1]
VISION = HQ.parent / "tools" / "vision"
sys.path.insert(0, str(HQ))
sys.path.insert(0, str(VISION))
import media_check  # noqa: E402
import phone_copy  # noqa: E402
import stall_watch  # noqa: E402
import blur_hits  # noqa: E402

try:
    import numpy  # noqa: F401
    import faces  # noqa: E402
except ImportError:                                            # faces needs numpy
    faces = None


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind.encode() + payload


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        stall_watch._walks.clear()
        media_check._cache.clear()

    def tearDown(self):
        self.temp.cleanup()


class StallFolderSafetyTests(Temp):
    """Security 1: names from task notes go through SAFE_NAME + safe_join; nothing outside the office is looked at."""

    def test_unsafe_out_names_give_no_folder_and_no_disk_access_outside_root(self):
        root = str(self.root)
        (self.root / "work" / "creative").mkdir(parents=True)
        seen = []
        real_isdir, real_walk, real_listdir, real_scandir = os.path.isdir, os.walk, os.listdir, os.scandir

        def spy(fn):
            def wrapped(p, *a, **kw):
                seen.append(str(p))
                return fn(p, *a, **kw)
            return wrapped
        bad = [r"out:\\host\share", r"out:C:\Users", "out:../x", "out:..", r"out:..\x", "out:C:/Windows", "out:.hidden"]
        with mock.patch("os.path.isdir", spy(real_isdir)), mock.patch("os.walk", spy(real_walk)), \
                mock.patch("os.listdir", spy(real_listdir)), mock.patch("os.scandir", spy(real_scandir)):
            for note in bad:
                t = {"id": "t1", "status": "doing", "note": note, "team": "Creative", "updated": iso(time.time() - 3600)}
                self.assertEqual(stall_watch.task_folders(root, t), [], note)
                stall_watch.stalled([t], set(), root, limit=60)
        base = os.path.realpath(root)
        self.assertEqual([p for p in seen if not os.path.realpath(p).startswith(base)], [])

    def test_work_folders_stay_inside_work(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        (self.root / "work" / "creative" / "clip-render").mkdir(parents=True)
        t = {"note": "out:clip", "team": "Creative"}
        got = stall_watch.task_folders(str(self.root), t)
        self.assertEqual([Path(p).name for p in got], ["clip", "clip-render"])
        self.assertEqual(stall_watch.task_folders(str(self.root), {"note": "out:clip", "team": "../../x"}), got[:1])


class StallRuleTests(Temp):
    """A4 (20 min, no age-only stall without a folder), A5 (folder mtimes, newest first, time budget), A12 (kinds)."""

    def setUp(self):
        super().setUp()
        self.out = self.root / "out" / "clip"
        (self.out / "frames").mkdir(parents=True)
        for p in (self.out / "frames", self.out):
            age(p, 3600)
        self.now = time.time()

    def task(self, **kw):
        return {"id": "t1", "status": "doing", "note": "out:clip", "team": "Creative", "updated": iso(self.now - 1800), **kw}

    def test_default_is_20_minutes(self):
        self.assertEqual(stall_watch.STALL_MIN, 20.0)
        self.assertEqual(stall_watch.stalled([self.task(updated=iso(self.now - 900))], set(), str(self.root), self.now), {})

    def test_meeting_approval_and_post_tasks_are_skipped(self):
        for kind in ("post", "meeting", "approval"):
            self.assertEqual(stall_watch.stalled([self.task(kind=kind)], set(), str(self.root), self.now, 600), {}, kind)
        self.assertIn("t1", stall_watch.stalled([self.task()], set(), str(self.root), self.now, 600))

    def test_a_new_frame_counts_through_its_folder(self):
        f = self.out / "frames" / "f_9999.png"
        f.write_bytes(b"x")
        age(f, 3600)                                              # the file looks old, its folder just changed
        self.assertEqual(stall_watch.stalled([self.task()], set(), str(self.root), self.now, 600), {})

    def test_newest_folder_is_walked_first_and_found_early(self):
        for i in range(30):
            d = self.out / f"old{i}"
            d.mkdir()
            age(d, 7200)
        new = self.out / "zz-new"
        new.mkdir()
        age(self.out, 7200)
        found = stall_watch.newest_change(str(self.out), after=self.now - 60)
        self.assertGreater(found, self.now - 60)

    def test_out_of_time_counts_as_alive(self):
        with mock.patch.object(stall_watch, "WALK_BUDGET", -1):
            self.assertIs(stall_watch.newest_change(str(self.out), after=0, now=self.now + 999), stall_watch.UNKNOWN)
            stall_watch._walks.clear()
            self.assertEqual(stall_watch.stalled([self.task()], set(), str(self.root), self.now, 600), {})


class PhoneJobsTests(Temp):
    def setUp(self):
        super().setUp()
        self.out_root = self.root / "out"
        self.d = self.out_root / "clip"
        self.d.mkdir(parents=True)
        (self.d / "edit.mp4").write_bytes(b"x")
        self.patch = mock.patch.object(phone_copy, "WORK", str(self.root / "work"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_release_refuses_want_until_moved_and_says_whether_it_stopped(self):
        """Security 2 / A1."""
        started, gate = threading.Event(), threading.Event()

        def stubborn(folder, stop=None):
            started.set()
            gate.wait(5)                                          # ignores stop for a while
            return {"status": "failed", "error": "stopped"}
        jobs = phone_copy.PhoneJobs(stubborn, log=lambda m: None, out_root=str(self.out_root))
        self.assertTrue(jobs.want(str(self.d)))
        self.assertTrue(started.wait(5))
        self.assertFalse(jobs.release(str(self.d), wait=0.3))     # still stopping: the approve answers 409
        gate.set()
        for _ in range(100):
            if not jobs.making(str(self.d)):
                break
            time.sleep(0.05)
        jobs.done.clear()
        self.assertFalse(jobs.want(str(self.d)))                  # refused while it is being released
        self.assertTrue(jobs.release(str(self.d)))                # nothing runs any more
        jobs.moved(str(self.d))
        self.assertTrue(jobs.want(str(self.d)))                   # the move is over (it failed and stayed): allowed again
        jobs.release(str(self.d))

    def test_only_folders_really_inside_out(self):
        """Security 4: a folder whose real path is outside out/ (a junction) is never queued."""
        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "edit.mp4").write_bytes(b"x")
        jobs = phone_copy.PhoneJobs(lambda f, stop=None: {"status": "made"}, log=lambda m: None, out_root=str(self.out_root))
        self.assertFalse(jobs.want(str(outside)))
        with mock.patch("os.path.realpath", side_effect=lambda p: str(outside) if str(p).endswith("clip") else os.path.abspath(p)):
            self.assertFalse(jobs.want(str(self.d)))

    def test_worker_never_strands_a_job_at_its_idle_timeout(self):
        """Security 3 / A3: a folder queued just as the 5-minute wait times out is still made."""
        seen = []
        jobs = phone_copy.PhoneJobs(lambda f, stop=None: (seen.append(f), {"status": "made"})[1], log=lambda m: None)
        jobs.cleaned = True
        real, fired = jobs.cond, []

        class Cond:
            def __enter__(self):
                return real.__enter__()

            def __exit__(self, *a):
                return real.__exit__(*a)

            def notify_all(self):
                real.notify_all()

            def wait(self, timeout=None):
                if timeout == 300:
                    if not fired:
                        fired.append(1)
                        jobs.queue.append("late-folder")          # arrives right as the wait times out
                    return False
                return real.wait(timeout)
        jobs.cond = Cond()
        jobs.thread = threading.current_thread()
        jobs._loop()                                              # runs here; ends at the second idle timeout
        self.assertEqual(seen, ["late-folder"])
        self.assertIsNone(jobs.thread)                            # set under the lock: want() starts a new worker

    def test_stale_part_files_are_cleaned_and_nothing_else(self):
        """Security 6."""
        w = self.root / "work"
        w.mkdir()
        old, new, other = w / "a.mp4.part", w / "b.mp4.part", w / "keep.mp4"
        for f in (old, new, other):
            f.write_bytes(b"x")
        age(old, 2 * 86400)
        age(other, 2 * 86400)
        self.assertEqual(phone_copy.clean_stale(str(w)), ["a.mp4.part"])
        self.assertEqual(sorted(p.name for p in w.iterdir()), ["b.mp4.part", "keep.mp4"])

    def test_ffmpeg_errors_never_fill_an_unread_pipe(self):
        """A6: 200 kB of stderr and a failure: no hang, and the error text comes back."""
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000 + 'THE END'); sys.exit(3)"]
        with self.assertRaises(subprocess.CalledProcessError) as e:
            phone_copy._run_stoppable(cmd, threading.Event())
        self.assertIn("THE END", e.exception.stderr)

    def test_folder_gone_during_encode_fails_cleanly(self):
        """A13: approved while encoding: a clean "failed", never an exception, and phone.mp4 only via os.replace."""
        moved = self.root / "approved-clip"

        def run(cmd, **kw):
            Path(cmd[-1]).write_bytes(b"phone")
            os.rename(self.d, moved)                              # the approve moved the folder meanwhile
            return subprocess.CompletedProcess(cmd, 0)
        info = {"ok": True, "video": "hevc", "audio": "aac", "faststart": True, "width": 1080, "height": 1920, "duration": 5}
        with mock.patch.object(phone_copy, "ffmpeg_path", return_value="ffmpeg"):
            r = phone_copy.make(str(self.d), run=run, probe=lambda p: dict(info))
        self.assertEqual(r["status"], "failed")
        self.assertFalse((moved / "phone.mp4").exists())

    def test_protocol_whitelist_on_every_input(self):
        """Security 6: ffmpeg and ffprobe read local files only."""
        cmd = phone_copy.command("ffmpeg", "in.mp4", "out.part", {"width": 1080, "height": 1920})
        self.assertEqual(cmd[cmd.index("-i") - 2:cmd.index("-i")], ["-protocol_whitelist", "file"])
        calls = []
        media_check._ffprobe("x.mp4", "ffprobe", run=lambda c, **kw: (calls.append(c), subprocess.CompletedProcess(c, 1, "", "no"))[1])
        self.assertIn("-protocol_whitelist", calls[0])
        self.assertEqual(calls[0][calls[0].index("-protocol_whitelist") + 1], "file")


class MediaCheckTests(Temp):
    def test_ffprobe_ok_but_boxes_broken_is_broken(self):
        """A9."""
        f = self.root / "edit.mp4"
        f.write_bytes(box("ftyp", b"isom") + box("mdat", b"\x00" * 64))
        answer = json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 8, "height": 8}], "format": {"duration": "1"}})
        with mock.patch.object(media_check, "ffprobe_path", return_value="ffprobe"):
            r = media_check.probe(str(f), run=lambda c, **kw: subprocess.CompletedProcess(c, 0, answer, ""))
        self.assertFalse(r["ok"])
        self.assertIn("moov", r["error"])

    def test_status_requests_never_wait_for_ffprobe(self):
        """A7: not probed yet counts as readable at once; the background thread fills the cache."""
        f = self.root / "edit.mp4"
        f.write_bytes(box("ftyp", b"isom") + box("mdat", b"\x00" * 64))
        gate = threading.Event()
        real = media_check.probe

        def slow(path, run=subprocess.run):
            gate.wait(5)
            return real(path, run)
        with mock.patch.object(media_check, "probe", slow), mock.patch.object(media_check, "ffprobe_path", return_value=None):
            t = time.time()
            self.assertTrue(media_check.readable_nowait(str(f)))
            self.assertIsNone(phone_copy.state(str(self.root)))      # not probed yet: no phone line, no wait
            self.assertLess(time.time() - t, 1)
            gate.set()
            for _ in range(100):
                if media_check.cached(str(f)) is not None:
                    break
                time.sleep(0.05)
            self.assertFalse(media_check.readable_nowait(str(f)))    # now known: broken


class PackageMessageTests(Temp):
    def test_video_ok_on_a_broken_edit_says_re_render(self):
        """A11."""
        from thumbnail_design import DesignError
        from video_package import Packages

        class Thumbs:
            lock = threading.RLock()

            def _load(self):
                return {"jobs": {}, "templates": {}}

            def _source(self, folder, list_videos=False):
                return None, None, ""
        d = self.root / "out" / "clip"
        d.mkdir(parents=True)
        f = d / "edit.mp4"
        f.write_bytes(box("ftyp", b"isom") + box("mdat", b"\x00" * 64))
        age(f, 600)
        pk = Packages(str(self.root), Thumbs(), lambda b: (200, {}), lambda n: (200, {}), lambda: {"tasks": []}, lambda p: None,
                      valid=media_check.readable)
        with mock.patch.object(media_check, "ffprobe_path", return_value=None):
            with self.assertRaisesRegex(DesignError, "edit.mp4 is broken - re-render"):
                pk.action({"name": "clip", "action": "video-ok"})
            # the board's own check never probes (A7), but the Approve video click does, before it decides
            media_check._cache.clear()
            pk2 = Packages(str(self.root), Thumbs(), lambda b: (200, {}), lambda n: (200, {}), lambda: {"tasks": []}, lambda p: None,
                           valid=lambda p: (media_check.cached(p) or {}).get("ok") is not False, valid_exact=media_check.readable)
            self.assertFalse(pk2.state("clip")["editing"])           # not probed yet: looks finished on the board
            with self.assertRaisesRegex(DesignError, "edit.mp4 is broken - re-render"):
                pk2.action({"name": "clip", "action": "video-ok"})


class ApproveFolderTests(Temp):
    """A1 + re-check 2: the approve stops the phone copy BEFORE it takes the thumbnail lock (board polls never wait),
    answers 409 when it is still stopping, and moves with os.rename."""

    def load(self, jobs, lock=None):
        tree = ast.parse((HQ / "server.py").read_text(encoding="utf-8"))
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("approve_folder", "_approve_folder")]
        body += [n for n in tree.body if (isinstance(n, ast.ClassDef) and n.name == "phone_released")
                 or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PHONE_STOPPING" for t in n.targets))]
        joined = []
        env = {"os": os, "shutil": mock.Mock(move=lambda *a: (_ for _ in ()).throw(AssertionError("shutil.move used"))),
               "ROOT": str(self.root), "SAFE_NAME": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$"),
               "safe_join": lambda base, name: os.path.join(base, name), "on_approved": joined.append, "phone_jobs": jobs}
        exec(compile(ast.Module(body=body, type_ignores=[]), "server-approve", "exec"), env)
        if lock is not None:
            env["thumbnail_design"] = mock.Mock(lock=lock, guard_approval=lambda name: None)
        return env["approve_folder"], joined

    def jobs(self, released=True):
        return mock.Mock(release=mock.Mock(return_value=released), making=mock.Mock(return_value=False))

    def test_still_stopping_is_a_409_and_nothing_moves(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        jobs = self.jobs(released=False)
        approve, joined = self.load(jobs)
        code, res = approve("clip")
        self.assertEqual(code, 409)
        self.assertIn("still stopping", res["error"])
        self.assertTrue((self.root / "out" / "clip").is_dir())
        jobs.moved.assert_called_once()
        self.assertEqual(joined, [])

    def test_release_happens_before_the_thumbnail_lock(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        lock, held = threading.RLock(), []
        jobs = self.jobs()
        jobs.release.side_effect = lambda src: (held.append(lock._is_owned()), True)[1]
        approve, _ = self.load(jobs, lock)
        self.assertEqual(approve("clip")[0], 200)
        self.assertEqual(held, [False])                           # not under the lock: polls keep going
        jobs.moved.assert_called_once()

    def test_a_poll_is_not_blocked_while_the_phone_copy_stops(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        lock, inside, go = threading.RLock(), threading.Event(), threading.Event()
        jobs = self.jobs()
        jobs.release.side_effect = lambda src: (inside.set(), go.wait(5), True)[2]
        approve, _ = self.load(jobs, lock)
        t = threading.Thread(target=approve, args=("clip",))
        t.start()
        self.assertTrue(inside.wait(5))
        self.assertTrue(lock.acquire(timeout=1))                  # a board poll gets the lock meanwhile
        lock.release()
        go.set()
        t.join(5)

    def test_moves_with_rename_and_lets_the_folder_go(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        (self.root / "out" / "clip" / "edit.mp4").write_bytes(b"x")
        jobs = self.jobs()
        approve, joined = self.load(jobs)
        self.assertEqual(approve("clip")[0], 200)
        self.assertTrue((self.root / "approved" / "clip" / "edit.mp4").is_file())
        jobs.moved.assert_called_once()
        self.assertEqual(joined, ["clip"])

    def test_a_failed_rename_is_a_clean_409(self):
        (self.root / "out" / "clip").mkdir(parents=True)
        approve, _ = self.load(self.jobs())
        with mock.patch("os.rename", side_effect=PermissionError("in use")):
            code, res = approve("clip")
        self.assertEqual(code, 409)
        self.assertTrue((self.root / "out" / "clip").is_dir())


class StoppedIsNotATryTests(Temp):
    """Re-check 1 and 4: an encode stopped by an approve that answered 409 is made again; a failing log never sticks busy."""

    def setUp(self):
        super().setUp()
        self.d = self.root / "out" / "clip"
        self.d.mkdir(parents=True)
        (self.d / "edit.mp4").write_bytes(b"x")
        self.patch = mock.patch.object(phone_copy, "WORK", str(self.root / "work"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def wait_idle(self, jobs):
        for _ in range(100):
            if not jobs.making(str(self.d)):
                return
            time.sleep(0.05)

    def test_stopped_encode_is_made_again_after_the_409(self):
        runs, started = [], threading.Event()

        def maker(folder, stop=None):
            runs.append(folder)
            if len(runs) == 1:
                started.set()
                stop.wait(5)
                return {"status": "failed", "error": "stopped"}
            return {"status": "made"}
        jobs = phone_copy.PhoneJobs(maker, log=lambda m: None, out_root=str(self.root / "out"))
        self.assertTrue(jobs.want(str(self.d)))
        self.assertTrue(started.wait(5))
        self.assertTrue(jobs.release(str(self.d)))
        jobs.moved(str(self.d))                                   # the approve answered 409: the folder stays in out/
        self.assertNotIn(os.path.realpath(str(self.d)), jobs.done)
        self.assertTrue(jobs.want(str(self.d)))                   # the reel still gets its phone.mp4
        self.wait_idle(jobs)
        self.assertEqual(len(runs), 2)

    def test_moved_clears_an_earlier_try(self):
        jobs = phone_copy.PhoneJobs(lambda f, stop=None: {"status": "failed", "error": "boom"}, log=lambda m: None)
        jobs.want(str(self.d))
        self.wait_idle(jobs)
        self.assertFalse(jobs.want(str(self.d)))                  # tried for this version
        jobs.release(str(self.d))
        jobs.moved(str(self.d))
        self.assertTrue(jobs.want(str(self.d)))
        self.wait_idle(jobs)

    def test_a_failing_log_never_leaves_busy_set(self):
        def bad_log(msg):
            raise OSError("stderr closed")
        jobs = phone_copy.PhoneJobs(lambda f, stop=None: {"status": "made"}, log=bad_log)
        jobs.cleaned = True
        jobs.want(str(self.d))
        self.wait_idle(jobs)
        self.assertIsNone(jobs.busy)
        self.assertFalse(jobs.making(str(self.d)))


class JunctionWalkTests(Temp):
    """Re-check 3: a junction or link inside out/<name>/ is never walked."""

    def test_links_are_skipped(self):
        out = self.root / "out" / "clip"
        out.mkdir(parents=True)
        target = self.root / "outside"
        target.mkdir()
        (target / "fresh.png").write_bytes(b"x")
        link = out / "frames"
        try:
            if os.name == "nt":
                r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
                if r.returncode != 0:
                    self.skipTest("cannot make a junction here")
            else:
                os.symlink(target, link)
        except OSError:
            self.skipTest("cannot make a link here")
        age(out, 3600)
        visited = []
        real = os.scandir
        with mock.patch("os.scandir", side_effect=lambda p: (visited.append(os.path.normcase(str(p))), real(p))[1]):
            found = stall_watch.newest_change(str(out), after=time.time() - 60)
        self.assertNotIn(os.path.normcase(str(link)), visited)
        self.assertFalse(found is not None and found is not stall_watch.UNKNOWN and found > time.time() - 60)

    def test_entry_check_falls_back_without_is_junction(self):
        e = mock.Mock(spec=["is_symlink", "stat"])
        e.is_symlink.return_value = False
        e.stat.return_value = mock.Mock(st_file_attributes=0x400)
        self.assertTrue(stall_watch._junction(e))
        e.stat.return_value = mock.Mock(st_file_attributes=0x10)
        self.assertFalse(stall_watch._junction(e))


class BlurNumbersTests(unittest.TestCase):
    """Security 5: hand-edited scan.json times are numbers, never text pasted into the filtergraph."""

    def test_times_must_be_finite_numbers(self):
        h = {"start": "1.5", "end": "4", "keys": [["1.5", 0, 0, 1, 1], ["3", 0, 0, 1, 1]]}
        self.assertEqual(blur_hits.timing(h, 0.5), (1.25, 4.0))
        for bad in ("4)*0+between(t", "nan", "inf", None):
            with self.assertRaises((ValueError, TypeError)):
                blur_hits.timing({**h, "end": bad}, 0.5)
        g = blur_hits.filtergraph([{"t0": "1", "t1": 2, "keys": [[1, 0, 0, 10, 10]]}], 100, 100)
        self.assertIn("enable='gte(t,1.0)*lt(t,2.0)'", g)
        with self.assertRaises(ValueError):
            blur_hits.filtergraph([{"t0": 1, "t1": "2)';[x]", "keys": [[1, 0, 0, 10, 10]]}], 100, 100)


@unittest.skipUnless(faces, "numpy not installed")
class FaceModelTests(unittest.TestCase):
    """Security 6: both UltraFace files are in the manifest and checked by sha256 before they load; YuNet only from models/."""

    def test_both_shipped_files_match_the_manifest(self):
        sums = faces.model_sums()
        self.assertEqual(sorted(sums), ["version-RFB-640.onnx", "version-RFB-640.ort-ready.onnx"])
        self.assertTrue(sums["version-RFB-640.ort-ready.onnx"][1].startswith("a9e7cb53"))
        self.assertTrue(sums["version-RFB-640.ort-ready.onnx"][1].endswith("6578"))
        d = Path(faces.ULTRAFACE).parent
        for name in sums:
            faces.verify_model(str(d / name))

    def test_a_changed_or_unlisted_file_is_refused(self):
        import inspect
        refused = (SystemExit, getattr(faces, "VisionError", SystemExit))
        extra = {"pinned": {}} if "pinned" in inspect.signature(faces.verify_model).parameters else {}
        with tempfile.TemporaryDirectory() as t:
            m, f = Path(t) / "model-manifest.json", Path(t) / "version-RFB-640.onnx"
            f.write_bytes(b"weights")
            m.write_text(json.dumps({"file": f.name, "bytes": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}), encoding="utf-8")
            faces.verify_model(str(f), str(m), **extra)
            f.write_bytes(b"weightz")
            with self.assertRaises(refused):
                faces.verify_model(str(f), str(m), **extra)
            other = Path(t) / "other.onnx"
            other.write_bytes(b"weights")
            with self.assertRaises(refused):
                faces.verify_model(str(other), str(m), **extra)

    def test_yunet_only_from_the_models_folder(self):
        walked = []
        with mock.patch.object(faces.os, "walk", side_effect=lambda b: (walked.append(b), iter(()))[1]):
            faces.find_yunet()
        self.assertEqual(walked, [faces.MODELS])


class AppPickerTests(unittest.TestCase):
    """A8 / A10: static checks of hud.js (the page itself needs a browser)."""

    def setUp(self):
        self.js = (HQ / "hud.js").read_text(encoding="utf-8")

    def test_fable_pick_is_per_window_and_resets_after_a_run(self):
        self.assertIn('sessionStorage.getItem("hq.model")', self.js)
        self.assertNotIn('localStorage.getItem("hq.model")', self.js)
        self.assertNotIn('localStorage.setItem("hq.model"', self.js)
        self.assertRegex(self.js, r'withModel = \(body\) => \{ if \(modelPick\(\) !== "fable"\) return body; if \(!keepFable\(\)\) setModelPick\("opus"\);')

    def test_broken_hint_only_when_no_edit_runs(self):
        self.assertIn("const broken = !pkg.editRunning && (pkg.broken || []).length", self.js)
        self.assertIn("pkg.editing && !pkg.editRunning && (pkg.broken || []).length", self.js)


if __name__ == "__main__":
    unittest.main()
