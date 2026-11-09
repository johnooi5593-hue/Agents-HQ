"""tools/vision/faces.py (t202): box maths, tracking across flicker and cuts, range merging, the faces.json schema,
faces_check, the kids-review stickers.py --faces hook, and an end-to-end run on synthetic 9:16 and 16:9 video.
Run: python -m unittest hq.tests.test_faces"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "vision"))
import faces as F  # noqa: E402
import faces_check as C  # noqa: E402

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
MODEL = Path(F.ULTRAFACE).exists()
REAL = ROOT / "work" / "creative" / "1107-children" / "vo-video-blur.mp4"


def det(x0, y0, x1, y1, c=0.95):
    return [x0, y0, x1, y1, c]


class BoxMaths(unittest.TestCase):
    def test_iou_and_union(self):
        self.assertAlmostEqual(F.iou([0, 0, 1, 1], [0, 0, 1, 1]), 1.0)
        self.assertEqual(F.iou([0, 0, 0.1, 0.1], [0.5, 0.5, 0.6, 0.6]), 0.0)
        self.assertAlmostEqual(F.iou([0, 0, 0.2, 0.2], [0.1, 0, 0.3, 0.2]), 1 / 3, places=6)
        self.assertEqual(F.union([0.1, 0.2, 0.3, 0.4], [0.0, 0.3, 0.2, 0.5]), [0.0, 0.2, 0.3, 0.5])

    def test_nms_keeps_best_and_drops_contained(self):
        keep = F.nms([det(0.1, 0.1, 0.3, 0.3, 0.9), det(0.11, 0.1, 0.31, 0.3, 0.8),   # duplicate
                      det(0.12, 0.12, 0.2, 0.2, 0.7),                                   # inside the first (tile cut)
                      det(0.6, 0.6, 0.7, 0.7, 0.6)])
        self.assertEqual(len(keep), 2)
        self.assertEqual(keep[0][4], 0.9)

    def test_pad_box_grows_top_more_and_clamps(self):
        b = F.pad_box([0.4, 0.4, 0.6, 0.6], 0.25)
        self.assertAlmostEqual(b[0], 0.35); self.assertAlmostEqual(b[2], 0.65); self.assertAlmostEqual(b[3], 0.65)
        self.assertAlmostEqual(b[1], 0.4 - 0.25 * F.TOP_PAD * 0.2)
        self.assertEqual(F.pad_box([0.0, 0.0, 0.2, 0.2], 0.5)[:2], [0.0, 0.0])

    def test_clean_drops_small_faces_and_clamps(self):
        W, H = 1080, 1920
        res = F.clean([det(-0.1, 0.1, 0.2, 0.2), det(0.5, 0.5, 0.52, 0.51)], 0.04, W, H)   # 2nd: 21 px < 43 px
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 0.0)
        self.assertIsInstance(res[0][0], float)


class Tracking(unittest.TestCase):
    STEP = 0.1

    def samples(self, n, missing=(), box=(0.4, 0.2, 0.5, 0.3), move=0.0, conf=0.95):
        out = []
        for i in range(n):
            t = round(i * self.STEP, 4)
            b = [box[0] + move * i, box[1], box[2] + move * i, box[3]]
            out.append((t, [] if i in missing else [b + [conf]]))
        return out

    def test_flicker_gap_is_filled(self):
        s = self.samples(20, missing={7, 8})                 # detector loses the face for 0.2 s
        tr = F.track(s, self.STEP, max_gap=0.3)
        self.assertEqual(len(tr), 1)
        self.assertEqual(len(tr[0]["pts"]), 20)
        self.assertEqual(sum(not p["real"] for p in tr[0]["pts"]), 2)
        fr = F.ranges(tr, self.STEP, duration=2.0, pad=0.25)
        self.assertEqual(len(fr), 1)
        self.assertEqual(fr[0]["start"], 0.0)
        self.assertAlmostEqual(fr[0]["end"], 1.95)
        self.assertEqual(fr[0]["hits"], 18)

    def test_long_gap_starts_a_new_track(self):
        tr = F.track(self.samples(20, missing=set(range(5, 12))), self.STEP, max_gap=0.3)
        self.assertEqual(len(tr), 2)

    def test_tracks_break_at_cuts(self):
        tr = F.track(self.samples(20), self.STEP, cuts=[0.0, 1.0], max_gap=0.3)
        self.assertEqual(len(tr), 2)
        fr = F.ranges(tr, self.STEP, cuts=[0.0, 1.0], duration=2.0)
        self.assertEqual(len(fr), 2)
        self.assertLessEqual(fr[0]["end"], 1.0)          # half-step padding never crosses the cut
        self.assertGreaterEqual(fr[1]["start"], 1.0)

    def test_two_faces_stay_two_tracks(self):
        s = [(round(i * self.STEP, 4), [det(0.1, 0.1, 0.2, 0.2), det(0.7, 0.1, 0.8, 0.2)]) for i in range(10)]
        tr = F.track(s, self.STEP)
        self.assertEqual(len(tr), 2)
        self.assertTrue(all(len(k["pts"]) == 10 for k in tr))

    def test_single_low_conf_flicker_is_dropped_high_conf_kept(self):
        low = F.ranges(F.track([(0.0, [det(0.1, 0.1, 0.2, 0.2, 0.5)])], self.STEP), self.STEP)
        high = F.ranges(F.track([(0.0, [det(0.1, 0.1, 0.2, 0.2, 0.9)])], self.STEP), self.STEP)
        self.assertEqual(low, [])
        self.assertEqual(len(high), 1)

    def test_moving_face_is_split_not_one_huge_box(self):
        s = self.samples(20, box=(0.0, 0.4, 0.1, 0.5), move=0.04)   # walks across the frame
        fr = F.ranges(F.track(s, self.STEP), self.STEP, duration=2.0, pad=0.25, grow=1.5)
        self.assertGreater(len(fr), 2)
        for f in fr:
            self.assertLess(F.area(f["box"]) / F.area(f["face"]), 2 * (1.5 * (1 + 0.25 * (1 + F.TOP_PAD))) + 1e-6)
        self.assertAlmostEqual(fr[0]["start"], 0.0)
        for a, b in zip(fr, fr[1:]):                        # contiguous: no hole between the pieces
            self.assertLessEqual(b["start"] - a["end"], self.STEP + 1e-6)

    def test_smooth_removes_one_sample_jump(self):
        pts = [{"t": i / 10, "box": [0.4, 0.4, 0.5, 0.5], "conf": 1, "real": True} for i in range(5)]
        pts[2]["box"] = [0.9, 0.9, 1.0, 1.0]
        self.assertEqual(F.smooth(pts)[2]["box"], [0.4, 0.4, 0.5, 0.5])


class Schema(unittest.TestCase):
    def make(self):
        s = [(round(i * 0.1, 4), [det(0.4, 0.2, 0.5, 0.3)]) for i in range(10)]
        fr = F.ranges(F.track(s, 0.1), 0.1, duration=1.0)
        pf = {f"{t:.3f}": d for t, d in s}
        return F.result(1080, 1920, 1.0, 0.1, "test", {"pad": 0.25, "min": 0.04, "cuts": [0.0], "conf": 0.4}, fr, pf)

    def test_result_validates_and_round_trips(self):
        d = self.make()
        self.assertTrue(F.validate(d))
        self.assertEqual(d["aspect"], "9x16")
        self.assertEqual(F.aspect(1920, 1080), "16x9")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "faces.json")
            F.write_json(d, p)
            back = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertEqual(back["faces"], d["faces"])
        self.assertEqual(set(back["faces"][0]), {"start", "end", "box", "face", "conf", "hits", "track"})
        F.validate(back)

    def test_numpy_float32_detections_round_trip(self):
        """Regression (gradecheck worker, 2026-11-08): detector output is numpy float32; json.dump crashed on it."""
        import numpy as np
        raw = [np.array([0.4, 0.2, 0.5, 0.3, 0.97], np.float32)]
        s = [(round(i * 0.1, 4), F.clean(raw, 0.04, 1080, 1920)) for i in range(6)]
        fr = F.ranges(F.track(s, 0.1), 0.1, duration=0.6)
        pf = {f"{t:.3f}": [[round(v, 4) for v in x[:4]] + [round(x[4], 3)] for x in d] for t, d in s}
        d = F.result(1080, 1920, 0.6, 0.1, "test", {"cuts": [0.0]}, fr, pf)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "faces.json")
            F.write_json(d, p)
            back = json.loads(Path(p).read_text(encoding="utf-8"))
        F.validate(back)
        self.assertAlmostEqual(back["faces"][0]["conf"], 0.97, places=3)
        self.assertEqual(len(back["per_frame"]), 6)

    def test_validate_rejects_bad_boxes(self):
        d = self.make()
        d["faces"][0]["box"] = [0.5, 0.2, 0.4, 0.3]
        with self.assertRaises(ValueError):
            F.validate(d)
        with self.assertRaises(ValueError):
            F.validate({"size": [1080], "faces": []})

    def test_rebuild_from_per_frame(self):
        d = self.make()
        r = F.rebuild(d, pad=0.5)
        self.assertEqual(r["params"]["pad"], 0.5)
        self.assertGreater(F.area(r["faces"][0]["box"]), F.area(d["faces"][0]["box"]))
        self.assertEqual(F.rebuild(d, min_frac=0.5)["faces"], [])      # every face is smaller than half the frame

    def test_cut_times_from_shots_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "shots.json")
            Path(p).write_text(json.dumps({"dur": 2.0, "shots": [{"d": 2.2}, {}, {"d": 3.0}]}), encoding="utf-8")
            self.assertEqual(F.cut_times(p), [0.0, 2.2, 4.2])
            Path(p).write_text(json.dumps({"cuts": [1.5, 0.5]}), encoding="utf-8")
            self.assertEqual(F.cut_times(p), [0.0, 0.5, 1.5])
        self.assertEqual(F.cut_times(None), [0.0])


class Check(unittest.TestCase):
    def test_read_table_parses_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "build_stickers.py")
            Path(p).write_text("raise SystemExit('must not run')\nFACES9 = [(0.0, 2.2, [0.1, 0.1, 0.3, 0.3], 'boy')]\n",
                               encoding="utf-8")
            rows = C.read_table(p, "FACES9")
        self.assertEqual(rows, [{"start": 0.0, "end": 2.2, "box": [0.1, 0.1, 0.3, 0.3], "what": "boy"}])

    def test_evaluate_recall_and_misses(self):
        faces = {"params": {"pad": 0.25}, "faces": [
            {"start": 0.0, "end": 2.0, "box": [0.1, 0.1, 0.3, 0.3], "face": [0.15, 0.15, 0.25, 0.25], "conf": 1, "hits": 20}]}
        hand = [{"start": 0.0, "end": 2.0, "box": [0.05, 0.05, 0.35, 0.4], "what": "found"},
                {"start": 0.0, "end": 2.0, "box": [0.7, 0.7, 0.9, 0.9], "what": "missed"}]
        r = C.evaluate(faces, hand)
        self.assertEqual(r["recall"], 0.5)
        self.assertEqual([m["what"] for m in r["misses"]], ["missed"])
        self.assertEqual(r["wild"], [])


class StickersHook(unittest.TestCase):
    """kids-review stickers.py --faces: a faces.json adds avoid boxes for the aspect it was detected on."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / ".claude" / "skills" / "kids-review" / "scripts"))
        try:
            import stickers
        except Exception as e:                      # pragma: no cover
            raise unittest.SkipTest(f"stickers.py does not import here: {e}")
        cls.SK = stickers

    def test_faces_avoid_and_check(self):
        SK = self.SK
        with tempfile.TemporaryDirectory() as tmp:
            fj = F.result(1080, 1920, 3.0, 0.1, "test", {}, [
                {"start": 0.9, "end": 2.2, "box": [0.82, 0.3, 1.0, 0.7], "face": [0.87, 0.35, 1.0, 0.63], "conf": 0.9,
                 "hits": 12, "track": 1}])
            fp = os.path.join(tmp, "faces916.json")
            F.write_json(fj, fp)
            av = SK.faces_avoid(fp)
            self.assertEqual(list(av[0]["box"]), ["9x16"])
            plan = {"avoid": [], "stickers": [{"t": 0.7, "dur": 1.55, "kind": "sparkle", "size": 0.12,
                                               "pos": {"9x16": [0.91, 0.47], "16x9": [0.5, 0.5]}, "group": "burst:hook"}]}
            pp = os.path.join(tmp, "stickers.json")
            Path(pp).write_text(json.dumps(plan), encoding="utf-8")
            spec, sts = SK.load_plan(pp)
            self.assertEqual(SK.check(spec, sts, 1080, 1920)[1], [])         # no faces: nothing to warn about
            spec, sts = SK.load_plan(pp, [fp])
            _, warns, _ = SK.check(spec, sts, 1080, 1920)
            self.assertTrue(any("face (auto" in w for w in warns))
            spec, sts = SK.load_plan(pp, [fp])
            self.assertEqual(SK.check(spec, sts, 1920, 1080)[1], [])         # a 9:16 face never blocks the 16:9 plan


@unittest.skipUnless(FFMPEG and MODEL, "needs ffmpeg/ffprobe and tools/vision/models/ultraface-rfb-640")
class EndToEnd(unittest.TestCase):
    def run_size(self, w, h):
        with tempfile.TemporaryDirectory() as tmp:
            v = os.path.join(tmp, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration=1",
                            "-pix_fmt", "yuv420p", v], check=True, creationflags=F.NOWIN)
            out, sheet = os.path.join(tmp, "faces.json"), os.path.join(tmp, "sheet.jpg")
            with contextlib.redirect_stdout(io.StringIO()):
                F.main([v, out, "--step", "0.25", "--sheet", sheet])
            d = json.loads(Path(out).read_text(encoding="utf-8"))
            F.validate(d)
            self.assertEqual(d["size"], [w, h])
            self.assertEqual(d["detector"], "ultraface-rfb-640")
            self.assertEqual(len(d["per_frame"]), 4)
            self.assertTrue(Path(sheet).stat().st_size > 1000)

    def test_portrait(self):
        self.run_size(1080, 1920)

    def test_landscape(self):
        self.run_size(1920, 1080)

    @unittest.skipUnless(REAL.exists(), "1107 Children review footage not on this computer")
    def test_real_frame_finds_the_teacher(self):
        """6.5 s of the 1107 9:16 review: the teacher's face, by eye at about x 0.3-0.65, y 0.02-0.24."""
        import numpy as np
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", "6.5", "-i", str(REAL), "-frames:v", "1", "-vf", "scale=720:1280",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, creationflags=F.NOWIN)
        fr = np.frombuffer(p.stdout, np.uint8).reshape(1280, 720, 3)
        found = F.make_detector("ultraface", 0.4, 0.04).detect(fr)
        self.assertTrue(any(F.inter(d[:4], [0.3, 0.02, 0.65, 0.24]) > 0 for d in found), found)


def fake_probe(stdout, returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=json.dumps(stdout) if not isinstance(stdout, str) else stdout,
                                       stderr="")


class ReviewFixes(unittest.TestCase):
    """Code review of tools/vision, 2026-11-09 (B1-B5, C4, the model checksum)."""

    @classmethod
    def setUpClass(cls):
        import gradecheck
        import textscan
        cls.GC, cls.TS = gradecheck, textscan

    # B1: a side-data entry without "rotation" after the display matrix must not reset the 90-degree turn
    DJI = {"streams": [{"width": 1920, "height": 1080, "r_frame_rate": "30/1",
                        "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90},
                                           {"side_data_type": "Ambient viewing environment"}]}],
           "format": {"duration": "5.0"}}

    def test_b1_rotation_survives_other_side_data(self):
        from unittest import mock
        for mod, fn in ((F, F.probe), (self.TS, self.TS.probe), (self.GC, self.GC.probe)):
            with mock.patch.object(mod.subprocess, "run", return_value=fake_probe(self.DJI)):
                r = fn("dji.mp4")
            self.assertEqual(tuple(r[:2]), (1080, 1920), mod.__name__)

    # B4: no video stream / no duration -> a clear error, not a traceback
    def test_b4_no_stream_or_duration_is_a_clear_error(self):
        from unittest import mock
        no_stream = {"streams": [], "format": {"duration": "3.0"}}
        no_dur = {"streams": [{"width": 640, "height": 360}], "format": {}}
        for doc, words in ((no_stream, "no video stream"), (no_dur, "no duration")):
            with mock.patch.object(F.subprocess, "run", return_value=fake_probe(doc)):
                with self.assertRaisesRegex(F.VisionError, words):
                    F.probe("x.mp4")
            with mock.patch.object(self.TS.subprocess, "run", return_value=fake_probe(doc)):
                with self.assertRaisesRegex(self.TS.ScanError, words):
                    self.TS.probe("x.mp4")
        with mock.patch.object(self.GC.subprocess, "run", return_value=fake_probe(no_stream)):
            with self.assertRaisesRegex(RuntimeError, "no video stream"):
                self.GC.probe("x.mp4")

    # B2: too few decoded samples is an error, never "no faces"
    def test_b2_check_decoded(self):
        F.check_decoded(95, 10.0, 0.1)
        with self.assertRaisesRegex(F.VisionError, "decoded only 50"):
            F.check_decoded(50, 10.0, 0.1)

    # B3: YuNet / Haar objects are not thread-safe: one worker
    def test_b3_one_worker_unless_ultraface(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"HQ_VISION_WORKERS": "4"}):
            self.assertEqual(F.worker_count(F.UltraFace.__new__(F.UltraFace)), 4)
            self.assertEqual(F.worker_count(F.YuNet.__new__(F.YuNet)), 1)
            self.assertEqual(F.worker_count(F.Haar.__new__(F.Haar)), 1)

    # B5: --sweep with an empty hand table prints "-", no crash
    def test_b5_sweep_with_empty_table(self):
        s = [(round(i * 0.1, 4), [det(0.4, 0.2, 0.5, 0.3)]) for i in range(10)]
        d = F.result(1080, 1920, 1.0, 0.1, "test", {"pad": 0.25, "min": 0.04, "conf": 0.4, "cuts": [0.0]},
                     F.ranges(F.track(s, 0.1), 0.1, duration=1.0), {f"{t:.3f}": v for t, v in s})
        with tempfile.TemporaryDirectory() as tmp:
            fj, build = os.path.join(tmp, "faces.json"), os.path.join(tmp, "b.py")
            F.write_json(d, fj)
            Path(build).write_text("FACES9 = []\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                C.main([fj, build, "--table", "FACES9", "--sweep"])
        rows = buf.getvalue().splitlines()[1:]
        self.assertTrue(rows)
        self.assertTrue(all(" - " in r for r in rows), rows[:2])

    # C4: a faces*.json that is not a faces.json (a faces_check report) is refused by stickers.py and skipped by the
    # build_stickers template, with a warning
    def test_c4_bad_faces_file_is_skipped(self):
        sys.path.insert(0, str(ROOT / ".claude" / "skills" / "kids-review" / "scripts"))
        import stickers as SK
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "faces-check.json")
            Path(report).write_text(json.dumps({"recall": 0.87, "misses": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                SK.faces_avoid(report)
            good = os.path.join(tmp, "faces916.json")
            F.write_json(F.result(1080, 1920, 52.2, 0.1, "test", {}, [
                {"start": 0.9, "end": 2.2, "box": [0.82, 0.3, 1.0, 0.7], "conf": 0.9}]), good)
            shutil.copy(ROOT / ".claude" / "skills" / "kids-review" / "templates" / "build_stickers.py", tmp)
            Path(tmp, "shots.json").write_text(json.dumps({"dur": 2.0, "shots": [{} for _ in range(26)]}), encoding="utf-8")
            p = subprocess.run([sys.executable, os.path.join(tmp, "build_stickers.py")], capture_output=True, text=True,
                               encoding="utf-8", creationflags=F.NOWIN, timeout=300)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            self.assertIn("faces-check.json skipped", p.stdout)
            spec = json.loads(Path(tmp, "stickers.json").read_text(encoding="utf-8"))
            self.assertTrue(any("auto faces916.json" in a["what"] for a in spec["avoid"]))

    # security review: model files must match the manifest AND the pins; YuNet only from tools/vision/models
    def test_model_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "version-RFB-640.onnx")
            Path(bad).write_bytes(b"not the model")
            man = os.path.join(tmp, "m.json")
            Path(man).write_text(json.dumps({"file": "version-RFB-640.onnx", "sha256": "0" * 64}), encoding="utf-8")
            with self.assertRaisesRegex(F.VisionError, "pins"):              # the manifest was edited: the pin wins
                F.verify_model(bad, man)
            with self.assertRaisesRegex(F.VisionError, "does not match"):  # a file without a pin: the manifest decides
                F.verify_model(bad, man, pinned={})
            import hashlib
            Path(man).write_text(json.dumps({"file": "version-RFB-640.onnx",
                                             "sha256": hashlib.sha256(b"not the model").hexdigest()}), encoding="utf-8")
            with self.assertRaisesRegex(F.VisionError, "pins"):              # swapped file + matching manifest: refused
                F.verify_model(bad, man)
            self.assertEqual(F.verify_model(bad, man, pinned={}), b"not the model")
            with self.assertRaisesRegex(F.VisionError, "not listed"):
                F.verify_model(os.path.join(tmp, "other.onnx"), man)
        if MODEL:
            for name in F.PINNED:
                p = os.path.join(os.path.dirname(F.ULTRAFACE), name)
                if os.path.exists(p):
                    self.assertEqual(len(F.verify_model(p)), F.PINNED[name][0])

    def test_dropped_yunet_is_refused_and_never_auto(self):
        """A *yunet*.onnx dropped into tools/vision/models: found only there, refused on --detector yunet (unpinned,
        even when a manifest beside it lists it), and ignored by --detector auto (the pinned UltraFace runs)."""
        import hashlib
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(F, "MODELS", tmp):
                self.assertIsNone(F.find_yunet())
                with self.assertRaisesRegex(F.VisionError, "no \\*yunet\\*.onnx"):
                    F.make_detector("yunet")
                Path(tmp, "face_detection_yunet.onnx").write_bytes(b"x")
                self.assertTrue(F.find_yunet().endswith("face_detection_yunet.onnx"))
                with self.assertRaisesRegex(F.VisionError, "not pinned"):
                    F.make_detector("yunet")
                Path(tmp, "model-manifest.json").write_text(json.dumps(          # a manifest written to match it
                    {"file": "face_detection_yunet.onnx", "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}),
                    encoding="utf-8")
                with self.assertRaisesRegex(F.VisionError, "not pinned"):
                    F.make_detector("yunet")
                with mock.patch.dict(F.PINNED, {"face_detection_yunet.onnx": (1, "0" * 64)}):   # pinned, wrong hash
                    with self.assertRaisesRegex(F.VisionError, "pins"):
                        F.make_detector("yunet")
                with self.assertRaisesRegex(F.VisionError, "verified model"):            # no bypass via the class
                    F.YuNet(str(Path(tmp, "face_detection_yunet.onnx")))
                if MODEL:
                    self.assertIsInstance(F.make_detector("auto"), F.UltraFace)

    @unittest.skipUnless(FFMPEG, "needs ffmpeg")
    def test_dropped_yunet_cli_gives_json_error(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            v = os.path.join(tmp, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1",
                            "-pix_fmt", "yuv420p", v], check=True, creationflags=F.NOWIN)
            Path(tmp, "x_yunet.onnx").write_bytes(b"x")
            buf = io.StringIO()
            with mock.patch.object(F, "MODELS", tmp), contextlib.redirect_stdout(buf):
                code = F.main([v, os.path.join(tmp, "f.json"), "--detector", "yunet"])
            self.assertEqual(code, 1)
            msg = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertFalse(msg["ok"])
            self.assertIn("not pinned", msg["error"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "f.json")))


@unittest.skipUnless(FFMPEG and MODEL, "needs ffmpeg/ffprobe and the UltraFace model")
class BrokenVideos(unittest.TestCase):
    """B2 / B4 end to end: a cut-short or audio-only file gives one JSON error line and a non-zero exit."""

    @classmethod
    def setUpClass(cls):
        import gradecheck
        import textscan
        cls.GC, cls.TS = gradecheck, textscan
        cls.tmp = tempfile.mkdtemp()
        full = os.path.join(cls.tmp, "full.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", full], check=True, creationflags=F.NOWIN)
        data = Path(full).read_bytes()
        cls.cut = os.path.join(cls.tmp, "cut.mp4")             # moov at the front: duration 6 s, frames for ~2 s
        Path(cls.cut).write_bytes(data[:int(len(data) * 0.35)])
        cls.audio = os.path.join(cls.tmp, "audio.m4a")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2", cls.audio], check=True,
                       creationflags=F.NOWIN)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cli(self, fn, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fn(args)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        return code, json.loads(lines[-1])

    def test_faces_cut_short(self):
        out = os.path.join(self.tmp, "f.json")
        code, msg = self.run_cli(F.main, [self.cut, out, "--step", "0.5"])
        self.assertEqual(code, 1)
        self.assertFalse(msg["ok"])
        self.assertRegex(msg["error"], "decoded only|ffmpeg stopped")
        self.assertFalse(os.path.exists(out))

    def test_faces_audio_only(self):
        code, msg = self.run_cli(F.main, [self.audio, os.path.join(self.tmp, "a.json")])
        self.assertEqual(code, 1)
        self.assertIn("no video stream", msg["error"])

    def test_textscan_cut_short_and_audio_only(self):
        code, msg = self.run_cli(self.TS.main, [self.cut, os.path.join(self.tmp, "t.json"), "--step", "0.5",
                                                "--tiles", "0", "--no-labels"])
        self.assertEqual(code, 1)
        self.assertRegex(msg["error"], "decoded only|ffmpeg stopped")
        code, msg = self.run_cli(self.TS.main, [self.audio, os.path.join(self.tmp, "t2.json")])
        self.assertEqual(code, 1)
        self.assertIn("no video stream", msg["error"])

    def test_gradecheck_cut_short(self):
        code, msg = self.run_cli(self.GC.main, [self.cut, os.path.join(self.tmp, "g.json")])
        self.assertEqual(code, 2)
        self.assertRegex(msg["error"], "decoded only|ffmpeg stopped")


if __name__ == "__main__":
    unittest.main()
