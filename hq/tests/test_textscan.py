import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "vision"))
import textscan
import blur_hits

try:
    import rapidocr_onnxruntime  # noqa: F401
    HAVE_OCR = True
except ImportError:
    HAVE_OCR = False


def font(size):
    from PIL import ImageFont
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def badge_frame(w=960, h=540, text="VICKY ONG", cjk="王美婷", at=(380, 300), size=26):
    """A grey 'room' with a white badge holding a name (and a Chinese name under it)."""
    from PIL import Image, ImageDraw
    import numpy as np
    img = Image.new("RGB", (w, h), (120, 128, 136))
    d = ImageDraw.Draw(img)
    x, y = at
    d.rectangle((x - 16, y - 14, x + 210, y + 2 * size + 30), fill=(250, 250, 250))
    d.text((x, y), text, font=font(size), fill=(20, 20, 20))
    if cjk:
        d.text((x, y + size + 10), cjk, font=font(size), fill=(20, 20, 20))
    return np.array(img)[:, :, ::-1].copy()          # BGR, like the ffmpeg pipe


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.c = textscan.Classifier()

    def test_names(self):
        for t in ("VICKY ONG", "Vicky Ong", "Tan Mei Ling", "王美婷", "林子轩", "VICKY ONG 王美婷", "VICXYONG"):
            self.assertEqual(self.c.kind(t), "name-like", t)

    def test_signs_and_words_from_1107_are_not_names(self):
        for t in ("Prayer Room", "PrayerRoom请含室", "祷告室", "出口", "KELUAR", "SHARK SIGHTED", "NO SWIMMING", "NOSWIMMING",
                  "Monuolia", "蒙古包", "PJ"):
            self.assertEqual(self.c.kind(t), "other", t)

    def test_brands(self):
        for t in ("Vitagen", "adidas", "ADIDAS", "Emirates", "Emintes", "Fly Emirates"):
            self.assertEqual(self.c.kind(t), "brand", t)

    def test_other(self):
        # lower case prose, numbers, CJK not starting with a surname, too many words, 5+ CJK
        for t in ("1/4", "hello there", "累代", "A B C D", "新生命教会儿童", "SPORI", "Room 12"):
            self.assertEqual(self.c.kind(t), "other", t)

    def test_false_positives_seen_on_1107(self):
        # print fragments, everyday words, repeated letters; a big single word is a print, not a badge
        for t in ("LUAR", "ELUAR", "SIGHTED", "Witagen", "LYDETTER", "Cool Bu", "WARNING", "ALWAVS", "IAAAAAN", "BEST FRIEND"):
            self.assertNotEqual(self.c.kind(t), "name-like", t)
        self.assertEqual(self.c.kind("CRUNEH", size=0.19), "other")
        self.assertEqual(self.c.kind("VICXYONG", size=0.013), "name-like")

    def test_captions_srt_as_ignore_list(self):
        d = Path(tempfile.mkdtemp())
        (d / "captions.srt").write_text("1\n00:00:01,000 --> 00:00:02,500\n小朋友们好高兴啊！\n\n2\n00:00:03,000 --> 00:00:04,000\n"
                                        "<b>林子里</b>一起玩\n", encoding="utf-8")
        words = textscan.load_ignore(str(d / "captions.srt"))
        self.assertEqual(words, ["小朋友们好高兴啊！", "林子里一起玩"])
        self.assertEqual(self.c.kind("高兴"), "name-like")                 # 高 is a surname: alone it looks like a name
        c = textscan.Classifier(words)
        self.assertEqual(c.kind("高兴"), "other")                          # but it is the edit's own caption
        self.assertEqual(c.kind("林子里"), "other")
        self.assertEqual(c.kind("王美婷"), "name-like")

    def test_ignore_list(self):
        self.assertEqual(self.c.kind("Grace Tan"), "name-like")
        self.assertEqual(textscan.Classifier(["Grace Tan"]).kind("GRACE TAN"), "other")


class MergeTests(unittest.TestCase):
    def r(self, text, x=0.4, y=0.6, conf=0.8):
        return {"box": [x, y, x + 0.05, y + 0.03], "text": text, "conf": conf}

    def test_same_text_in_neighbouring_samples_is_one_range(self):
        s = [(10.0, [self.r("VICXYONG", conf=0.72)]), (10.5, [self.r("VICKYONG", x=0.42, conf=0.8)]),
             (11.0, [self.r("VCXYONG", x=0.45, conf=0.7)]), (11.5, []), (12.0, [self.r("VICKYONG", x=0.47)])]
        g = textscan.merge(s, 0.5, duration=52.2)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["start"], g[0]["end"]), (10.0, 12.5))     # one missed sample is bridged
        self.assertEqual(g[0]["text"], "VICKYONG")
        self.assertAlmostEqual(g[0]["box"][0], 0.4)
        self.assertAlmostEqual(g[0]["box"][2], 0.52)
        self.assertEqual(len(g[0]["keys"]), 4)

    def test_far_apart_or_different_text_splits(self):
        s = [(1.0, [self.r("Vitagen"), self.r("王美婷", x=0.1, y=0.1)]), (1.5, [self.r("Vitagen")]),
             (3.0, [self.r("Vitagen")])]                                   # 3 samples later: a new range
        g = textscan.merge(s, 0.5)
        self.assertEqual(sorted((x["text"], x["start"]) for x in g), [("Vitagen", 1.0), ("Vitagen", 3.0), ("王美婷", 1.0)])

    def test_end_is_clamped_to_the_video(self):
        g = textscan.merge([(52.0, [self.r("VICKY ONG")])], 0.5, duration=52.2)
        self.assertAlmostEqual(g[0]["end"], 52.2)

    def test_dedupe_keeps_the_best_reading_of_a_spot(self):
        a = self.r("VICXYONG", conf=0.58); b = self.r("VICXYONG", conf=0.72); c = self.r("PJ", x=0.1)
        out = textscan.dedupe([a, b, c])
        self.assertEqual([o["conf"] for o in out], [0.8, 0.72])

    def test_finish_numbers_and_kinds(self):
        s = [(1.0, [self.r("Prayer Room", x=0.1, y=0.1)]), (1.0, []), (2.0, [self.r("VICKY ONG")])]
        hits = textscan.finish(textscan.merge(s, 0.5), textscan.Classifier())
        self.assertEqual([(h["id"], h["kind"]) for h in hits], [(1, "other"), (2, "name-like")])
        self.assertEqual(set(hits[0]), {"id", "start", "end", "box", "text", "conf", "kind", "keys"})


class BlurHitsTests(unittest.TestCase):
    scan = {"size": [1920, 1080], "hits": [
        {"id": 1, "start": 10.0, "end": 12.5, "box": [0.45, 0.79, 0.48, 0.81], "text": "VICKY ONG", "conf": 0.8, "kind": "name-like",
         "keys": [[10.0, 0.45, 0.79, 0.47, 0.81], [12.0, 0.46, 0.79, 0.48, 0.81]]},
        {"id": 2, "start": 40.0, "end": 41.0, "box": [0.47, 0.86, 0.58, 0.95], "text": "SHARK SIGHTED", "conf": 0.9, "kind": "other",
         "keys": [[40.0, 0.47, 0.86, 0.58, 0.95]]}]}

    def test_pick(self):
        self.assertEqual([h["id"] for h in blur_hits.pick(self.scan["hits"])], [1])
        self.assertEqual([h["id"] for h in blur_hits.pick(self.scan["hits"], ids=[2])], [2])
        self.assertEqual(len(blur_hits.pick(self.scan["hits"], everything=True)), 2)

    def test_boxes_match_blur_py_format(self):
        b = blur_hits.boxes(blur_hits.pick(self.scan["hits"]), 1920, 1080, pad=0.3, pad_y=1.2)
        self.assertEqual(len(b), 1)
        self.assertEqual((b[0]["t0"], b[0]["t1"]), (9.75, 12.5))        # half a step before the first sample
        t, x, y, w, h = b[0]["keys"][0]
        self.assertEqual(t, 10.0)
        self.assertTrue(x < 0.45 * 1920 and x + w > 0.47 * 1920)
        line = 0.02 * 1080                                                # one text line high: the box covers the next line too
        self.assertTrue(y <= 0.79 * 1080 - line and y + h >= 0.81 * 1080 + line, (y, h))
        self.assertTrue(all(isinstance(v, int) for v in (x, y, w, h)))

    def test_timing_snaps_to_cuts(self):
        h = self.scan["hits"][0]                                          # samples 10.0 .. 12.0, step 0.5
        self.assertEqual(blur_hits.timing(h, 0.5, [3.0, 9.8, 12.2, 20.0]), (9.8, 12.2))
        self.assertEqual(blur_hits.timing(h, 0.5, [9.2, 12.9]), (9.2, 12.9))     # a missed sample: cut two steps out
        self.assertEqual(blur_hits.timing(h, 0.5, [3.0, 20.0]), (9.5, 12.5))   # no cut near: one step either side
        self.assertEqual(blur_hits.timing(h, 0.5, [], duration=12.3), (9.5, 12.3))

    def test_cli_and_filtergraph(self):
        d = Path(tempfile.mkdtemp())
        (d / "scan.json").write_text(json.dumps(self.scan), encoding="utf-8")
        blur_hits.main([str(d / "scan.json"), str(d / "boxes.json"), "--ids", "1,2", "--ffmpeg", str(d / "g.txt")])
        doc = json.loads((d / "boxes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(doc["boxes"]), 2)
        g = (d / "g.txt").read_text(encoding="utf-8")
        self.assertIn("[vout]", g)
        self.assertIn("enable='gte(t,9.75)*lt(t,12.5)'", g)
        self.assertEqual(g.count("boxblur"), 2)
        with self.assertRaises(SystemExit):
            blur_hits.main([str(d / "scan.json"), str(d / "b2.json"), "--ids", "9"])


class LabelTests(unittest.TestCase):
    def frame(self):
        from PIL import Image, ImageDraw
        import numpy as np
        img = Image.new("RGB", (1920, 1080), (60, 70, 80))
        d = ImageDraw.Draw(img)
        d.rectangle((1500, 150, 1700, 700), fill=(30, 90, 200))                 # a blue bottle
        d.rectangle((1540, 300, 1640, 356), fill=(205, 205, 200))               # its name sticker
        for row in (310, 332):                                                  # two rows of scribbled name, too small to read
            for i in range(9):
                d.line((1548 + i * 10, row, 1554 + i * 10, row + 14), fill=(40, 40, 40), width=1)
                d.line((1548 + i * 10, row + 14, 1556 + i * 10, row + 2), fill=(40, 40, 40), width=1)
        return np.array(img)[:, :, ::-1].copy()

    def test_sticker_is_found(self):
        labs = textscan.find_labels(self.frame())
        sticker = [1540 / 1920, 300 / 1080, 1640 / 1920, 356 / 1080]
        self.assertTrue(any(textscan.iou(l["box"], sticker) >= 0.4 for l in labs), labs)
        self.assertTrue(all(l["text"] == "[label]" and l["label"] for l in labs))

    def test_a_readable_text_box_hides_the_label(self):
        texts = [{"box": [1540 / 1920, 300 / 1080, 1640 / 1920, 356 / 1080], "text": "王美婷", "conf": 0.9}]
        self.assertEqual(textscan.find_labels(self.frame(), texts), [])

    def test_plain_frame_has_no_labels(self):
        import numpy as np
        self.assertEqual(textscan.find_labels(np.full((1080, 1920, 3), 90, np.uint8)), [])

    def test_label_ranges_get_the_label_kind(self):
        box = [0.8, 0.28, 0.85, 0.33]
        s = [(1.0, [{"box": box, "text": "[label]", "conf": 0.5, "label": True}]),
             (1.5, [{"box": box, "text": "[label]", "conf": 0.6, "label": True}])]
        hits = textscan.finish(textscan.merge(s, 0.5), textscan.Classifier())
        self.assertEqual([(h["kind"], h["start"], h["end"]) for h in hits], [("label", 1.0, 2.0)])


@unittest.skipUnless(HAVE_OCR, "rapidocr-onnxruntime not installed")
class OcrTests(unittest.TestCase):
    def test_rendered_badge_is_found_and_flagged(self):
        reads = textscan.ocr_frame(badge_frame(), tiles=0)
        texts = [r["text"] for r in reads]
        clf = textscan.Classifier()
        self.assertTrue(any(textscan.similar(t, "VICKY ONG") >= 0.7 for t in texts), texts)
        self.assertTrue(any(clf.kind(t) == "name-like" for t in texts), texts)
        hit = next(r for r in reads if textscan.similar(r["text"], "VICKY ONG") >= 0.7)
        x0, y0, x1, y1 = hit["box"]
        self.assertTrue(0.35 < x0 < 0.45 and 0.5 < y0 < 0.6 and x1 > x0 and y1 > y0, hit["box"])

    def test_small_text_is_found_on_the_enlarged_tiles(self):
        img = badge_frame(1920, 1080, text="VICKY ONG", cjk=None, at=(900, 800), size=14)
        tiled = textscan.ocr_frame(img, tiles=2, zoom=2.0, min_px=8)
        self.assertTrue(any(textscan.similar(r["text"], "VICKY ONG") >= 0.7 for r in tiled), [r["text"] for r in tiled])

    def test_min_height_drops_tiny_text(self):
        reads = textscan.ocr_frame(badge_frame(), tiles=0, min_px=200)
        self.assertEqual(reads, [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not on PATH")
    def test_video_scan_end_to_end(self):
        from PIL import Image
        d = Path(tempfile.mkdtemp())
        Image.fromarray(badge_frame()[:, :, ::-1]).save(d / "badge.png")
        Image.new("RGB", (960, 540), (120, 128, 136)).save(d / "empty.png")
        # 1 s empty, 1 s badge, 1 s empty
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", "1", "-i", str(d / "empty.png"), "-loop", "1", "-t", "1",
                        "-i", str(d / "badge.png"), "-loop", "1", "-t", "1", "-i", str(d / "empty.png"), "-filter_complex",
                        "[0:v][1:v][2:v]concat=n=3:v=1,fps=10,format=yuv420p", "-c:v", "libx264", "-crf", "12", str(d / "v.mp4")],
                       check=True)
        out = d / "scan.json"
        textscan.main([str(d / "v.mp4"), str(out), "--step", "0.25", "--tiles", "0", "--sheet", str(d / "sheet.jpg")])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["size"], [960, 540])
        names = [h for h in doc["hits"] if h["kind"] == "name-like"]
        self.assertTrue(names, doc["hits"])
        self.assertTrue(all(0.9 <= h["start"] <= 1.1 and 1.9 <= h["end"] <= 2.3 for h in names), names)
        self.assertTrue((d / "sheet.jpg").stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
