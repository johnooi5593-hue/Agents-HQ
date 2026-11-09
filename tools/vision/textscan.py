"""Text scan: flag every piece of readable text (names on badges, bottles, whiteboards, door charts) in a video.

usage: python textscan.py <video.mp4> <out.json> [--step 0.5] [--min-height 0.012] [--sheet out.jpg] [--ignore words.txt]
                          [--tiles 2] [--zoom 2] [--min-conf 0.5] [--no-labels]

Samples one frame every --step seconds and runs OCR (RapidOCR: PP-OCRv4 Chinese + English models on the CPU) on the
whole frame and on a --tiles x --tiles grid of overlapping tiles enlarged --zoom times (small text such as a lanyard badge
is only found on the enlarged tiles). A reading is kept when it has at least 2 letters/characters, confidence >= --min-conf
and a text height of at least --min-height of the frame's short side. The same text in neighbouring samples is merged into
one range. Output:

  {"size": [W, H], "step": 0.5, "hits": [{"id": 1, "start": 10.0, "end": 12.5, "box": [x0, y0, x1, y1],
     "text": "VICKY ONG", "conf": 0.74, "kind": "name-like|brand|other", "keys": [[t, x0, y0, x1, y1], ...]}]}

box and keys are fractions of the frame (box = the union of every sample's box); start is the first sample that shows the
text and end is one step after the last one (the text may still be there until the next sample). kind:
  name-like  Latin words in Title Case or ALL CAPS (2-3 words, not all everyday English words; or one small 6+ letter
             word, because OCR drops the space in "VICKY ONG"), or 2-4 Chinese characters that start with a common
             surname; never anything on the allow-list
  label      text "[label]": no readable text, but a small light sticker / badge card / chart with dark marks in it
             (water-bottle name stickers are often too small for OCR). Off with --no-labels.
  brand      a known brand (Vitagen, adidas, Emirates ...)
  other      every other reading (signs, shirt prints, misreads): still listed, a human glances at it on the sheet
--ignore adds words to the allow-list (one per line, # comments). --sheet draws every hit, name-like first (frame +
zoomed crop + text). Runtime: about 5-6 s per sample on this PC's CPU (whole frame + 4 tiles), so ~10 min for 52 s.
Prints one JSON line with the hit counts, or {"ok": false, "error": ...} with exit code 1 (no video stream or duration,
ffmpeg stopping early, under 90% of the expected samples decoded): never "no names" for a video it could not read.
"""
import argparse, difflib, json, re, subprocess, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Signs and common words seen on church / event footage (1107 Children review) plus everyday words: never a name.
COMMON = ["Prayer Room", "祷告室", "禱告室", "出口", "入口", "安全出口", "KELUAR", "MASUK", "EXIT", "ENTRANCE", "SHARK SIGHTED",
          "NO SWIMMING", "Mongolia", "蒙古包", "PJ", "SPORT", "SPORTS", "TOILET", "TANDAS", "洗手间", "厕所", "WELCOME", "欢迎",
          "欢迎光临", "小心", "小心地滑", "禁止吸烟", "NO SMOKING", "PUSH", "PULL", "OPEN", "CLOSED", "OFFICE", "STAFF", "VISITOR",
          "Sunday School", "主日学", "儿童", "儿童主日学", "Children", "Kids", "Kids Church", "教会", "圣经", "祝福", "喜乐", "平安",
          "哈利路亚", "Hallelujah", "Jesus", "耶稣", "上帝", "生日快乐", "Happy Birthday", "Merry Christmas", "圣诞快乐",
          "New Life", "新生命", "NLRC", "NLRCC", "Restoration Centre", "THANK YOU", "谢谢", "LOVE", "HAPPY", "AWESOME", "Mandarin",
          "Malaysia", "Kuala Lumpur", "Petaling Jaya", "NO PARKING", "FIRE EXIT", "FIRE EXTINGUISHER", "DANGER", "CAUTION",
          # more prints read on the 1107 footage (shirts, bottles, the Emirates kit, signs)
          "WARNING", "ALWAYS", "Fly Better", "MOCHI", "ROSE", "Cool Buddy", "Cost Buddy"]
# Everyday English words: a line made only of these is not a name ("BEST FRIEND", "SUPER COOL").
WORDS = set("""a an the and or of to in on at for with by from up out no not yes is are be my your our his her its we you
i me he she they it this that all any one two three new old big small best good great super cool fun happy love team
club school church kids kid boys girls boy girl baby family friend friends home house room hall door exit entry open
closed push pull stop go keep left right top bottom front back side free sale shop store water bottle food drink snack
cake milk juice tea coffee rice day days week time today tomorrow morning night summer winter spring autumn fall camp
game games play player sport sports run runner fly better fast strong brave smart king queen star stars sun moon world
city park beach sea ocean shark fish bear cat dog lion tiger panda bunny duck bird dragon unicorn hero heroes power
dream dreams hope faith joy peace grace life light only just more less made make with every never always warning
danger caution safety first aid fire police toilet male female men women ladies gents staff only private office
welcome hello thank thanks you please sorry merry christmas birthday party gift gifts color colour red blue green
yellow black white pink purple orange gold silver mini max pro plus original classic premium natural fresh pure
north south east west kuala lumpur malaysia singapore china mongolia mongolian edition limited official""".split())
STOP_REPEAT = re.compile(r"(.)\1\1", re.I)          # "IAAAAAN": three of the same letter in a row is never a name
SINGLE_MAX = 0.035                                  # a merged one-word name is small text (badge / sticker)
BRANDS = ["Vitagen", "adidas", "Emirates", "Fly Emirates", "Nike", "Puma", "Under Armour", "Milo", "Nestle", "100PLUS",
          "Coca-Cola", "Pepsi", "Tupperware", "Lock&Lock", "Thermos", "Zojirushi", "Tiger", "Disney", "Pokemon", "Hello Kitty",
          "Sanrio", "LEGO", "Uniqlo", "H&M", "Samsung", "Apple", "iPhone", "Canon", "Sony", "DJI", "Dutch Lady", "Yakult",
          "Marigold", "Spritzer", "Cactus", "Mamee", "Julie's", "Gardenia", "Ribena", "Ayam Brand", "Real Madrid", "Barcelona",
          "Manchester United", "Liverpool", "Arsenal", "Chelsea"]
SURNAMES = set("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪"
               "范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤赖庄洪温翁傅简萧颜柯游詹欧甘辜"
               "涂骆康邝伍关麦区古车巫饶阮凌吕柳殷池卓蓝戚"
               "陳黃張劉楊鄭謝許羅葉蘇盧賴莊鍾馮鄧蕭顏歐駱鄺吳趙孫馬韓曹蔣譚陸賈閆龔邱鄒薛劉")
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def norm(s):
    """Lower case, letters/digits/CJK only (OCR drops or adds spaces)."""
    return "".join(c for c in s.lower() if c.isalnum())


def meaningful(s):
    return sum(1 for c in s if c.isalnum())


class Classifier:
    def __init__(self, extra=()):
        self.common = {norm(w) for w in list(COMMON) + list(extra) if norm(w)}
        self.brands = {norm(w) for w in BRANDS if norm(w)}
        self.extra = [norm(w) for w in extra if norm(w)]      # --ignore lines: any 2+ character piece of them is known

    def _in_extra(self, n):
        return len(n) >= 2 and any(n in w for w in self.extra)

    def _known(self, n, words):
        """n is (fuzzily) one known word, or is made of known words, or holds a known Latin phrase of 5+ letters (a sign)."""
        if not n:
            return False
        for w in words:
            if n == w:
                return True
            if len(n) >= 4 and difflib.SequenceMatcher(None, n, w).ratio() >= (0.7 if len(n) >= 6 else 0.75):
                return True
            if len(w) >= 5 and w.isascii() and w in n:          # a sign: "PrayerRoom请含室"
                return True
            if len(n) >= 4 and n in w:                           # a fragment: "LUAR" of KELUAR, "SIGHTED"
                return True
        rest = n
        for w in sorted(words, key=len, reverse=True):
            if len(w) >= 2:
                rest = rest.replace(w, "")
        return meaningful(rest) == 0

    def known(self, text):
        n = norm(text)
        return self._known(n, self.brands) or self._known(n, self.common) or self._in_extra(n)

    def kind(self, text, size=None):
        """size: character height as a fraction of the frame's short side (None = unknown)."""
        n = norm(text)
        if self._known(n, self.brands):
            return "brand"
        if self._known(n, self.common) or self._in_extra(n):
            return "other"
        if self.name_like(text, size):
            return "name-like"
        return "other"

    @staticmethod
    def name_like(text, size=None):
        cjk = "".join(CJK.findall(text))
        if 2 <= len(cjk) <= 4 and cjk[0] in SURNAMES:
            # Chinese name: 2-4 characters, nothing else Chinese on the line, starting with a common surname
            runs = re.findall(r"[\u3400-\u9fff\uf900-\ufaff]+", text)
            if len(runs) == 1:
                return True
        latin = re.sub(r"[\u3400-\u9fff\uf900-\ufaff]+", " ", text)
        toks = re.findall(r"[A-Za-z]+", latin)
        if not toks or re.search(r"\d", latin):
            return False
        cased = all(t.isupper() or (t[0].isupper() and t[1:].islower()) for t in toks)
        if not cased or any(STOP_REPEAT.search(t) for t in toks):
            return False
        if all(t.lower() in WORDS for t in toks):
            return False
        if 2 <= len(toks) <= 3 and all(len(t) >= 2 for t in toks):
            return True
        # "VICXYONG": OCR merged the two words of a badge. Only small text: big single words are prints and signs.
        return len(toks) == 1 and 6 <= len(toks[0]) <= 16 and (size is None or size <= SINGLE_MAX)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def overlap_small(a, b):
    """Intersection over the smaller box (one reading inside another)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def similar(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0 if min(len(na), len(nb)) >= 2 else 0.5
    return difflib.SequenceMatcher(None, na, nb).ratio()


def dedupe(reads):
    """One frame: drop a reading that sits inside a better reading of the same text (full frame + overlapping tiles)."""
    out = []
    for r in sorted(reads, key=lambda r: -r["conf"]):
        if any(overlap_small(r["box"], o["box"]) >= 0.5 and (similar(r["text"], o["text"]) >= 0.5 or overlap_small(r["box"], o["box"]) >= 0.8)
               for o in out):
            continue
        out.append(r)
    return out


def merge(samples, step, duration=None, gap=1):
    """samples: [(t, [reading{box,text,conf}])] in time order -> ranges. A reading joins a range whose last sample is at
    most gap+1 steps back and whose text is similar (>= 0.6) near the same place, or which it overlaps (IoU >= 0.3) with
    loosely similar text (>= 0.34)."""
    ranges, eps = [], step * 0.01
    for t, reads in samples:
        for r in reads:
            best, score = None, 0.0
            for g in ranges:
                if t - g["last"] > (gap + 1) * step + eps or t <= g["last"] + eps:
                    continue
                lb = g["keys"][-1][1:]
                s = similar(r["text"], g["text"])
                ov = iou(r["box"], lb)
                cx = abs((r["box"][0] + r["box"][2]) - (lb[0] + lb[2])) / 2
                cy = abs((r["box"][1] + r["box"][3]) - (lb[1] + lb[3])) / 2
                ok = (s >= 0.6 and cx < 0.25 and cy < 0.25) or (ov >= 0.3 and s >= 0.34)
                if ok and s + ov > score:
                    best, score = g, s + ov
            if best is None:
                best = {"start": t, "last": t, "keys": [], "reads": [], "text": r["text"], "conf": 0.0}
                ranges.append(best)
            best["last"] = t
            best["keys"].append([t] + list(r["box"]))
            best["reads"].append(r)
            if r["conf"] > best["conf"]:
                best["conf"], best["text"], best["best"] = r["conf"], r["text"], r
    for g in ranges:
        xs = [k for k in g["keys"]]
        g["box"] = [min(k[1] for k in xs), min(k[2] for k in xs), max(k[3] for k in xs), max(k[4] for k in xs)]
        g["end"] = g["last"] + step if duration is None else min(duration, g["last"] + step)
    return sorted(ranges, key=lambda g: (g["start"], g["box"][1]))


def finish(ranges, clf):
    hits = []
    for i, g in enumerate(ranges, 1):
        # the best reading decides, but one name-like reading anywhere in the range (VICXYONG / VICKY ONG) is enough,
        # unless the best reading is a known brand or sign
        best = g.get("best") or g["reads"][0]
        if best.get("label"):
            kind = "label"
        else:
            kind = clf.kind(g["text"], best.get("size"))
            if kind == "other" and not clf.known(g["text"]) and \
                    any(clf.kind(r["text"], r.get("size")) == "name-like" for r in g["reads"]):
                kind = "name-like"
        hits.append({"id": i, "start": round(g["start"], 3), "end": round(g["end"], 3), "box": [round(v, 4) for v in g["box"]],
                     "text": g["text"], "conf": round(g["conf"], 3), "kind": kind,
                     "keys": [[round(k[0], 3)] + [round(v, 4) for v in k[1:]] for k in g["keys"]]})
    return hits


# ---------- video + OCR ----------

def probe(path):
    """Displayed size (rotation tag applied, ffmpeg autorotates) and duration."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,duration:stream_side_data=rotation:format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    if p.returncode != 0 or not (p.stdout or "").strip():
        raise ScanError(f"ffprobe can't read {path}: {(p.stderr or '').strip()[:200]}")
    try:
        r = json.loads(p.stdout)
    except ValueError:
        raise ScanError(f"ffprobe gave no readable answer for {path}")
    if not r.get("streams"):
        raise ScanError(f"no video stream in {path}")
    st = r["streams"][0]
    try:
        W, H = int(st["width"]), int(st["height"])
    except (KeyError, TypeError, ValueError):
        raise ScanError(f"the video stream of {path} has no width / height")
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:                     # other side-data entries (display matrix etc.) must not reset it
            rot = int(float(sd["rotation"]))
    if abs(rot) % 180 == 90:
        W, H = H, W
    dur = 0.0
    for v in ((r.get("format") or {}).get("duration"), st.get("duration")):
        try:
            dur = dur or float(v)
        except (TypeError, ValueError):
            pass
    if not dur > 0:
        raise ScanError(f"no duration for {path} (a still image, or a broken file)")
    return W, H, dur


class ScanError(RuntimeError):
    """Reported as one JSON line {"error": ...} with exit code 1: never "no names" on a video that wasn't read."""


MIN_DECODED = 0.9


def frames(path, step, W, H):
    import tempfile
    err = tempfile.TemporaryFile()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=1/{step}:round=near", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=err)
    import numpy as np
    k, size = 0, W * H * 3
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield k * step, np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            k += 1
        p.stdout.close()
        if p.wait() != 0:
            err.seek(0)
            msg = err.read().decode("utf-8", "replace").strip().splitlines()
            raise ScanError(f"ffmpeg stopped with code {p.returncode} after {k} samples of {path}: "
                            f"{msg[-1][:200] if msg else 'no message'}")
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close(); p.wait(); err.close()


_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_frame(img, tiles=2, zoom=2.0, min_px=13, min_conf=0.5, keep_all=False):
    """All readings in one BGR frame as {box (fractions), text, conf}. Whole frame + enlarged overlapping tiles."""
    import cv2
    H, W = img.shape[:2]
    jobs = [(0, 0, W, H, 1.0)]
    if tiles and tiles > 1 and zoom > 1:
        tw, th, ov = W / tiles, H / tiles, 0.15
        for i in range(tiles):
            for j in range(tiles):
                jobs.append((int(max(0, (i - ov) * tw)), int(max(0, (j - ov) * th)),
                             int(min(W, (i + 1 + ov) * tw)), int(min(H, (j + 1 + ov) * th)), zoom))
    reads = []
    for x0, y0, x1, y1, z in jobs:
        part = img[y0:y1, x0:x1]
        if z != 1.0:
            part = cv2.resize(part, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC)
        res, _ = engine()(part, text_score=0.0 if keep_all else min_conf * 0.6, box_thresh=0.4)
        for quad, text, conf in res or []:
            xs = [x0 + p[0] / z for p in quad]; ys = [y0 + p[1] / z for p in quad]
            text, conf = str(text).strip(), float(conf)
            hpx = min(max(ys) - min(ys), max(xs) - min(xs))      # character size, for horizontal and vertical lines
            if not keep_all and (conf < min_conf or meaningful(text) < 2 or hpx < min_px):
                continue
            reads.append({"box": [max(0.0, min(xs) / W), max(0.0, min(ys) / H), min(1.0, max(xs) / W), min(1.0, max(ys) / H)],
                          "text": text, "conf": conf, "size": hpx / min(W, H)})
    return dedupe(reads)


def find_labels(img, texts=()):
    """Unreadable labels: small light rectangles (stickers, badge cards, door charts) with dark marks inside, lighter
    than what is around them. OCR can't read 8 px handwriting on a bottle sticker; this at least points at it.
    Two masks: white paper (V > 170, S < 60) and paper lighter than its 61 px neighbourhood (dim, tinted stickers).
    conf = edge density x 4 (how much ink-like detail is inside).
    Skips anything that overlaps a text reading of the same frame."""
    import cv2
    import numpy as np
    H, W = img.shape[:2]
    A = W * H
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v, s = hsv[:, :, 2].astype(np.int16), hsv[:, :, 1]
    loc = cv2.blur(hsv[:, :, 2], (61, 61)).astype(np.int16)
    out = []
    for mask in ((v > 170) & (s < 60), (v > 120) & (s < 70) & (v > loc + 12)):
        mask = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
        for i in range(1, n):
            x, y, w, h, area = (int(q) for q in stats[i])
            if not (A * 0.0004 <= w * h <= A * 0.02) or max(w, h) / max(1, min(w, h)) > 4.5 or area / (w * h) < 0.6:
                continue
            inner = g[y + 2:y + h - 2, x + 2:x + w - 2]
            if inner.size == 0:
                continue
            ink = (lab[y:y + h, x:x + w] != i).sum() / (w * h)              # dark marks inside the light patch
            edges = cv2.Canny(inner, 60, 160).mean() / 255
            x0, y0, x1, y1 = max(0, x - w // 3), max(0, y - h // 3), min(W, x + w + w // 3), min(H, y + h + h // 3)
            lift = g[y:y + h, x:x + w].mean() - g[y0:y1, x0:x1].astype(float).mean()
            # edges >= 0.125 (conf >= 0.5) and not cut off by the frame edge: tuned on 1107 (49 -> 13 extra labels,
            # the door charts and the blue-bottle sticker kept)
            if 0.02 <= ink <= 0.35 and edges >= 0.125 and lift > 15 and x > 0 and y > 0 and x + w < W and y + h < H:
                box = [x / W, y / H, (x + w) / W, (y + h) / H]
                if not any(overlap_small(box, t["box"]) >= 0.3 for t in texts):
                    out.append({"box": box, "text": "[label]", "conf": round(float(min(1.0, edges * 4)), 3), "label": True})
    return dedupe(out)


# ---------- contact sheet ----------

def font(size):
    from PIL import ImageFont
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/NotoSansSC-VF.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/System/Library/Fonts/PingFang.ttc"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


KINDS = ("name-like", "label", "brand", "other")              # sheet order: most likely a name first
COLOURS = {"name-like": (255, 40, 40), "label": (255, 80, 220), "brand": (255, 160, 0), "other": (255, 230, 0)}


def sheet(path, hits, shots, W, H, cols=4):
    """One cell per hit, name-like first, then label, brand, other: the frame (box drawn), a zoomed crop of the box,
    and '#id start-end kind / text conf'."""
    import io
    from PIL import Image, ImageDraw
    hits = sorted(hits, key=lambda h: (KINDS.index(h["kind"]), h["start"]))
    cw = 480; fh = int(cw * H / W) if W >= H else 360; fw = int(fh * W / H) if W < H else cw
    ch = fh + 200 + 64
    rows = max(1, (len(hits) + cols - 1) // cols)
    out = Image.new("RGB", (cols * cw, rows * ch + 50), (24, 24, 28))
    d = ImageDraw.Draw(out)
    counts = ", ".join(f"{sum(h['kind'] == k for h in hits)} {k}" for k in KINDS)
    d.text((10, 10), f"textscan: {len(hits)} hits ({counts}) - red name-like, pink unreadable label, orange brand, yellow other",
           font=font(24), fill=(255, 255, 255))
    f1, f2 = font(18), font(22)
    for n, h in enumerate(hits):
        cx, cy = (n % cols) * cw, 50 + (n // cols) * ch
        jpg = shots.get(h["_t"])
        col = COLOURS[h["kind"]]
        x0, y0, x1, y1 = h["_box"]
        if jpg is not None:
            fr = Image.open(io.BytesIO(jpg.tobytes())).convert("RGB")
            th = fr.resize((fw, fh))
            dd = ImageDraw.Draw(th)
            dd.rectangle((x0 * fw - 3, y0 * fh - 3, x1 * fw + 3, y1 * fh + 3), outline=col, width=3)
            out.paste(th, (cx + (cw - fw) // 2, cy))
            pad = 0.6
            bw, bh = (x1 - x0) * W, (y1 - y0) * H
            crop = fr.crop((int(max(0, x0 * W - bw * pad)), int(max(0, y0 * H - bh * pad - 10)),
                            int(min(W, x1 * W + bw * pad)), int(min(H, y1 * H + bh * pad + 10))))
            s = min((cw - 10) / crop.width, 196 / crop.height)
            crop = crop.resize((max(1, int(crop.width * s)), max(1, int(crop.height * s))))
            out.paste(crop, (cx + (cw - crop.width) // 2, cy + fh + 2))
        d.text((cx + 6, cy + fh + 202), f"#{h['id']} {h['start']:.1f}-{h['end']:.1f}s {h['kind']}", font=f1, fill=col)
        d.text((cx + 6, cy + fh + 224), f"{h['text']}  {h['conf']:.2f}", font=f2, fill=(255, 255, 255))
    out.save(path, quality=88)


SRT_SKIP = re.compile(r"^\d+$|^\d\d:\d\d:\d\d[,.]\d+\s*-->")


def load_ignore(path):
    """Allow-list words, one per line (# comments). A .srt works too (numbers and timecodes skipped), so a finished
    edit's own captions are never flagged."""
    if not path:
        return []
    out = []
    for l in Path(path).read_text(encoding="utf-8-sig").splitlines():
        l = l.strip()
        if l and not l.startswith("#") and not SRT_SKIP.match(l):
            out.append(re.sub(r"<[^>]+>|\{[^}]*\}", "", l))
    return out


def scan(video, step=0.5, min_height=0.012, tiles=2, zoom=2.0, min_conf=0.5, ignore=(), keep_frames=False, labels=True):
    import cv2
    W, H, dur = probe(video)
    min_px = min_height * min(W, H)
    samples, lsamples, shots = [], [], {}
    for t, img in frames(video, step, W, H):
        reads = ocr_frame(img, tiles=tiles, zoom=zoom, min_px=min_px, min_conf=min_conf)
        labs = find_labels(img, reads) if labels else []
        samples.append((t, reads)); lsamples.append((t, labs))
        if keep_frames and (reads or labs):
            shots[t] = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1]
        if len(samples) % 20 == 0:
            print(f"textscan: {len(samples)} samples ({t:.1f} s)", file=sys.stderr, flush=True)
    if len(samples) < MIN_DECODED * dur / step:            # half-decoded: an error, never "no names"
        raise ScanError(f"decoded only {len(samples)} of about {int(dur / step)} samples of {video} "
                        f"({len(samples) * step:.1f} of {dur:.1f} s): the file is cut short or damaged")
    ranges = merge(samples, step, dur or None) + (merge(lsamples, step, dur or None) if labels else [])
    ranges.sort(key=lambda g: (g["start"], g["box"][1]))
    clf = Classifier(ignore)
    hits = finish(ranges, clf)
    for h, g in zip(hits, ranges):
        bt = max(g["reads"], key=lambda r: r["conf"])
        h["_t"] = next(k[0] for k, r in zip(g["keys"], g["reads"]) if r is bt)
        h["_box"] = bt["box"]
    return {"size": [W, H], "step": step, "duration": round(dur, 3), "samples": len(samples), "hits": hits}, shots


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--min-height", type=float, default=0.012)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--tiles", type=int, default=2)
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--sheet")
    ap.add_argument("--ignore")
    ap.add_argument("--no-labels", action="store_true", help="skip the unreadable-label pass (OCR readings only)")
    a = ap.parse_args(argv)
    try:
        if a.step <= 0:
            raise ScanError("--step must be > 0")
        if not Path(a.video).exists():
            raise ScanError(f"no such video: {a.video}")
        res, shots = scan(a.video, a.step, a.min_height, a.tiles, a.zoom, a.min_conf, load_ignore(a.ignore),
                          keep_frames=bool(a.sheet), labels=not a.no_labels)
    except (ScanError, OSError, ValueError) as e:            # one JSON line, no traceback, no result file
        print(json.dumps({"ok": False, "error": str(e), "video": str(a.video)}, ensure_ascii=False))
        return 1
    if a.sheet:
        sheet(a.sheet, res["hits"], shots, *res["size"])
    clean = dict(res, video=str(a.video), hits=[{k: v for k, v in h.items() if not k.startswith("_")} for h in res["hits"]])
    Path(a.out).write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {k: sum(h["kind"] == k for h in res["hits"]) for k in KINDS}
    print(json.dumps({"out": a.out, "size": res["size"], "samples": res["samples"], "hits": len(res["hits"]), **kinds,
                      "name_like": [f"#{h['id']} {h['start']:.1f}-{h['end']:.1f}s {h['text']}" for h in res["hits"] if h["kind"] == "name-like"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
