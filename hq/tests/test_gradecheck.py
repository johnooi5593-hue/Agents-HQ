"""tools/vision/gradecheck.py: the measured colour check (board t204) judges synthetic frames the way the brand check needs."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "vision"))
import gradecheck as gc  # noqa: E402


def neutral_frame(h=640, w=360):
    """A clean, neutral picture: mid-grey room, a white wall across the top, a dark-grey floor."""
    f = np.full((h, w, 3), 128, np.uint8)
    f[: h // 3] = 232                      # white wall
    f[-h // 6:] = 60                        # floor
    return f


def tint(frame, r, g, b):
    return np.clip(frame.astype(np.float32) * np.array([r, g, b], np.float32), 0, 255).astype(np.uint8)


class FrameMetricTests(unittest.TestCase):
    def test_neutral_grey_frame_passes(self):
        m = gc.frame_metrics(neutral_frame())
        self.assertAlmostEqual(m["white_b"], 0.0, delta=0.5)
        self.assertAlmostEqual(m["white_a"], 0.0, delta=0.5)
        self.assertAlmostEqual(m["warmth"], 0.0, delta=0.5)
        self.assertIsNone(m["skin_sat"])                     # no skin in a grey room
        self.assertEqual(m["crushed"], 0.0)
        self.assertEqual(gc.evaluate(m, "kids"), [])
        self.assertEqual(gc.evaluate(m, "sermon"), [])

    def test_orange_tinted_frame_fails(self):
        m = gc.frame_metrics(tint(neutral_frame(), 1.06, 1.0, 0.82))     # white wall -> (246, 232, 190)
        self.assertGreater(m["white_b"], 8)
        self.assertGreater(m["warmth"], 8)
        fl = gc.evaluate(m, "kids")
        self.assertIn("white_warm", fl)
        self.assertIn("too_warm", fl)

    def test_clipped_skin_patch_fails(self):
        f = neutral_frame()
        f[250:450, 100:260] = (255, 200, 160)              # a face pushed until red clips: hue 25 deg, S 0.37
        m = gc.frame_metrics(f)
        self.assertIsNotNone(m["skin_clip"])
        self.assertGreater(m["skin_clip"], 90)
        self.assertAlmostEqual(m["skin_hue"], 25.3, delta=1.5)
        self.assertLess(m["skin_sat"], 0.45)
        self.assertEqual(gc.evaluate(m, "kids"), ["skin_clip"])

    def test_natural_skin_patch_passes(self):
        f = neutral_frame()
        f[250:450, 100:260] = (214, 168, 140)              # natural light skin: hue 23 deg, S 0.35, nothing clipped
        m = gc.frame_metrics(f)
        self.assertEqual(m["skin_clip"], 0.0)
        self.assertEqual(gc.evaluate(m, "kids"), [])

    def test_orange_skin_fails_on_saturation(self):
        f = neutral_frame()
        f[250:450, 100:260] = (230, 140, 80)               # the 1107 v3 "tanned / orange" look: S 0.65
        m = gc.frame_metrics(f)
        self.assertIn("skin_sat", gc.evaluate(m, "kids"))

    def test_face_boxes_limit_the_skin_reading(self):
        f = neutral_frame()
        f[250:450, 100:260] = (255, 200, 160)
        self.assertIsNone(gc.frame_metrics(f, boxes=[])["skin_clip"])          # faces given, none in this frame
        m = gc.frame_metrics(f, boxes=[(100, 250, 160, 200)])
        self.assertGreater(m["skin_clip"], 90)

    def test_crushed_blacks_fail_kids_not_sermon(self):
        f = neutral_frame()
        f[-160:] = 2                                         # 25 % of the frame at 2/255
        m = gc.frame_metrics(f)
        self.assertGreater(m["crushed"], 20)
        self.assertIn("crushed", gc.evaluate(m, "kids"))
        self.assertNotIn("crushed", gc.evaluate(m, "sermon"))

    def test_sermon_profile_is_looser_on_warmth_only_up_to_its_limit(self):
        m = {"warmth": 10.0, "white_b": 6.0}
        self.assertIn("too_warm", gc.evaluate(m, "kids"))
        self.assertEqual(gc.evaluate(m, "sermon"), [])
        self.assertIn("too_warm", gc.evaluate({"warmth": 13.0}, "sermon"))


class FacesJsonTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, d):
        p = self.dir / "faces.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        return str(p)

    def test_faces_py_per_frame_and_ranges(self):
        # tools/vision/faces.py schema: fractions [x0, y0, x1, y1]; analysis frame 360x640 for a 1080x1920 source
        p = self.write({"size": [1080, 1920], "step": 0.1,
                        "faces": [{"start": 0.0, "end": 2.0, "box": [0.1, 0.1, 0.5, 0.4], "conf": 0.9}],
                        "per_frame": {"0.000": [[0.25, 0.25, 0.75, 0.5, 0.95]], "0.100": []}})
        f = gc.read_faces(p, 1080, 1920, 1 / 3)
        self.assertEqual([tuple(round(v) for v in b) for b in gc.faces_at(f, 0.0)], [(90, 160, 180, 160)])
        self.assertEqual(gc.faces_at(f, 0.1), [])
        self.assertEqual(gc.faces_at(f, 1.0), [])                 # per_frame wins: no detection near 1.0 s
        f2 = gc.read_faces(self.write({"faces": [{"start": 0.0, "end": 2.0, "box": [0.1, 0.1, 0.5, 0.4]}]}), 1080, 1920, 1 / 3)
        self.assertEqual(len(gc.faces_at(f2, 1.0)), 1)
        self.assertEqual(gc.faces_at(f2, 2.5), [])


class ShotsTests(unittest.TestCase):
    def test_grade_py_shots_format(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        p = d / "shots.json"
        p.write_text(json.dumps({"dur": 2.0, "shots": [{"src": "a"}, {"src": "b", "d": 1.5}, {"src": "c"}]}), encoding="utf-8")
        self.assertEqual(gc.read_shots(str(p), 6.0), [(0.0, 2.0), (2.0, 3.5), (3.5, 6.0)])
        p.write_text(json.dumps({"cuts": [1.0, 2.5]}), encoding="utf-8")
        self.assertEqual(gc.read_shots(str(p), 4.0), [(0.0, 1.0), (1.0, 2.5), (2.5, 4.0)])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class VideoTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def make(self, name, colour):
        p = self.dir / name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=360x640:d=2:r=30",
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "10", str(p)], check=True)
        return p

    def test_cli_pass_fail_ref_and_sheet(self):
        grey, warm = self.make("grey.mp4", "0xE8E8E8"), self.make("warm.mp4", "0xF0E2B8")
        out, sheet = self.dir / "r.json", self.dir / "s.jpg"
        self.assertEqual(gc.main([str(grey), str(out)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["verdict"], "PASS")
        self.assertEqual(gc.main([str(warm), str(out), "--ref", str(grey), "--sheet", str(sheet)]), 1)
        rep = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rep["verdict"], "FAIL")
        self.assertIn("white_warm", rep["overall"]["flags"])
        self.assertEqual(rep["ref"]["verdict"], "PASS")
        self.assertGreater(rep["delta_overall"]["white_b"], 8)
        self.assertTrue(sheet.exists())

    def test_unreadable_video_is_exit_2(self):
        bad = self.dir / "partial.mp4"
        bad.write_bytes(b"\x00\x00\x00\x18ftypmp42 not finished")
        self.assertEqual(gc.main([str(bad), str(self.dir / "r.json")]), 2)


if __name__ == "__main__":
    unittest.main()
