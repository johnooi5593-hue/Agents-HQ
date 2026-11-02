"""Shared pieces of Orbit Pop (环绕弹字): the type (Noto Sans SC Black / Oswald Bold with bevel, gradient fill, stroke, glow and
shadow), the colours, the safe zones, the plan checks and the planning page. Speech timing, compositing and ffmpeg helpers come
from the caption-card / poster-kinetic skills next to this one (the same way Gold Stack uses them).

The brand sheet (owner-approved 2026-11-02, with the owner's 5 answers): Documents/Style Guides/orbit-pop/guideline.pdf
  type      Noto Sans SC Black (tracking -2 %, no overlap): XL 270 / L 210 / M 150 / S 100, tilt 240 (220-260), column 136;
            Oswald Bold: numbers 400 px (digits never overlap), English sub-word cap height 88-100 px
  colour    (owner answer 1: the ad's own gradients, not Sunrise) key lime diagonal #F2F538 (top right) -> #AAEF40 (bottom left),
            glow #C8F23C 40 %, blur 14 % of the size; flat_yellow #FAF535 and mint #7BF7F6 -> #B3F4E5 at most once each;
            numbers green vertical #86D53F -> #416122; text #F9F9F9 -> #D7D2D2 (top left -> bottom right);
            English sub-word #EEECED -> #C1C0C0 (vertical); stroke / shadow #0E1014
  layers    bevel (inner edge 3 % of size: light top-left +45 %, dark bottom-right -30 %), fill, 3 px stroke #0E1014 70 %,
            key glow, shadow black 65 % blur 9 % of size 4 % down
  safe      text x 86..994; nothing at x > 950 for y 1000..1700 (rows reaching below y 1000 end at x <= 950); nothing above
            y 200 or below y 1620; zone C top >= chin + 40 per framing; behind the head (top band, tilt, column) as big as
            possible, shrinking only while less than 35 % of a character shows (owner 2026-11-02, as Gold Stack)
"""
import functools, os, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CCS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "caption-card", "scripts")
if not os.path.isdir(CCS):
    CCS = "D:/Agents HQ/.claude/skills/caption-card/scripts"
if CCS not in sys.path:
    sys.path.insert(0, CCS)
import cc  # noqa: E402
from cc import (F1, FPS, display, char_times, is_cjk, load, save, report, probe, sub_time, keys, ease_out, ease_io, put, NEG, norm)  # noqa: E402,F401

W, H = 1080, 1920
NOTO = next((p for p in ("C:/Windows/Fonts/NotoSansSC-VF.ttf", os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts/NotoSansSC-VF.ttf"))
             if os.path.isfile(p)), None)
OSWALD = next((p for p in (os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts/Oswald-Bold.ttf"),
                           "C:/Users/John Ooi/AppData/Local/Microsoft/Windows/Fonts/Oswald-Bold.ttf", "C:/Windows/Fonts/Oswald-Bold.ttf")
               if os.path.isfile(p)), None)
SIZES = {"XL": 270, "L": 210, "M": 150, "S": 100}
MAXCH = {"XL": 2, "L": 4, "M": 5, "S": 7}
TILT = 240                                             # tilted pair target (sheet 220-260)
COLUMN = 136
# behind the head (top band, tilted pair, glow column): as big as possible (owner 2026-11-02, as Gold Stack): start at the
# target size, sit as close to the head as hides at most BEHIND_IN of a character, shrink only while less than BEHIND_SHOW of
# any character shows on some frame; the person matte keeps the head (and the face) in front
BEHIND_IN = 0.40
BEHIND_SHOW = 0.35
NUMBER = 400
SUB_CAP = 92                                           # English sub-word cap height (sheet: 88-100 px)
TRACK = -0.02                                          # Noto tracking -2 % (advance-based: glyphs never overlap)

INK = (14, 16, 20)                                     # #0E1014
FILLS = {                                              # (start, end, direction): tl = top-left -> bottom-right, tr = top-right -> bottom-left
    "white": ((249, 249, 249), (215, 210, 210), "tl"),         # #F9F9F9 -> #D7D2D2
    "lime": ((242, 245, 56), (170, 239, 64), "tr"),            # #F2F538 -> #AAEF40
    "flat_yellow": ((250, 245, 53), (250, 245, 53), "v"),      # #FAF535
    "mint": ((123, 247, 246), (179, 244, 229), "tr"),          # #7BF7F6 -> #B3F4E5
    "number": ((134, 213, 63), (65, 97, 34), "v"),             # #86D53F -> #416122
    "sub": ((238, 236, 237), (193, 192, 192), "v"),            # #EEECED -> #C1C0C0
}
KEY_COLOURS = ("lime", "flat_yellow", "mint")
GLOW = {"lime": (200, 242, 60), "flat_yellow": (250, 245, 53), "mint": (123, 247, 246)}   # lime #C8F23C (sheet); the others in their own colour
STREAK, HALO, BLOOM = (247, 255, 224), (200, 242, 60), (234, 255, 176)                   # O9: #F7FFE0, #C8F23C, #EAFFB0 (owner answer 1)

SAFE_L, SAFE_R, SAFE_RB = 86, 994, 950
TOP, BOTTOM = 200, 1620
BAND = (1000, 1700)
TOP_A = 210                                            # zone A top band starts here
COL_X, COL_Y = 86, 290                                 # zone D column
MOVES = (None, "", "pop", "slide", "mixed", "number", "tilt", "column")
ZONES = (None, "", "C", "A", "D")
EXITS = (None, "", "plain", "kick")
MONEY = re.compile(r"[$￥¥€£]|RM|块钱|美金|元|令吉|奉献|捐|money|dollar", re.I)
CONDITIONS = ("如果", "若是", "假如", "要是", "只要", "除非")
TURN_WORDS = ("其实", "但是", "可是", "原来", "而是", "所以", "然而", "不过", "因为", "于是")

# 和合本 book names -> English (for checking a verse-reference sub-word against what the speaker said)
BOOKS = {"创世记": "GENESIS", "出埃及记": "EXODUS", "利未记": "LEVITICUS", "民数记": "NUMBERS", "申命记": "DEUTERONOMY",
         "约书亚记": "JOSHUA", "士师记": "JUDGES", "路得记": "RUTH", "撒母耳记上": "1 SAMUEL", "撒母耳记下": "2 SAMUEL",
         "列王纪上": "1 KINGS", "列王纪下": "2 KINGS", "历代志上": "1 CHRONICLES", "历代志下": "2 CHRONICLES", "以斯拉记": "EZRA",
         "尼希米记": "NEHEMIAH", "以斯帖记": "ESTHER", "约伯记": "JOB", "诗篇": "PSALM", "箴言": "PROVERBS", "传道书": "ECCLESIASTES",
         "雅歌": "SONG OF SONGS", "以赛亚书": "ISAIAH", "耶利米书": "JEREMIAH", "耶利米哀歌": "LAMENTATIONS", "以西结书": "EZEKIEL",
         "但以理书": "DANIEL", "何西阿书": "HOSEA", "约珥书": "JOEL", "阿摩司书": "AMOS", "俄巴底亚书": "OBADIAH", "约拿书": "JONAH",
         "弥迦书": "MICAH", "那鸿书": "NAHUM", "哈巴谷书": "HABAKKUK", "西番雅书": "ZEPHANIAH", "哈该书": "HAGGAI",
         "撒迦利亚书": "ZECHARIAH", "玛拉基书": "MALACHI", "马太福音": "MATTHEW", "马可福音": "MARK", "路加福音": "LUKE",
         "约翰福音": "JOHN", "使徒行传": "ACTS", "罗马书": "ROMANS", "哥林多前书": "1 CORINTHIANS", "哥林多后书": "2 CORINTHIANS",
         "加拉太书": "GALATIANS", "以弗所书": "EPHESIANS", "腓立比书": "PHILIPPIANS", "歌罗西书": "COLOSSIANS",
         "帖撒罗尼迦前书": "1 THESSALONIANS", "帖撒罗尼迦后书": "2 THESSALONIANS", "提摩太前书": "1 TIMOTHY",
         "提摩太后书": "2 TIMOTHY", "提多书": "TITUS", "腓利门书": "PHILEMON", "希伯来书": "HEBREWS", "雅各书": "JAMES",
         "彼得前书": "1 PETER", "彼得后书": "2 PETER", "约翰一书": "1 JOHN", "约翰二书": "2 JOHN", "约翰三书": "3 JOHN",
         "犹大书": "JUDE", "启示录": "REVELATION"}


# ---- type ------------------------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=64)
def font(size, face="noto"):
    size = max(8, int(round(size)))
    if face == "oswald":
        if not OSWALD:
            raise SystemExit("Oswald Bold (Oswald-Bold.ttf) is not installed; Orbit Pop needs it for numbers and English (SIL OFL)")
        return ImageFont.truetype(OSWALD, size)
    if not NOTO:
        raise SystemExit("Noto Sans SC (NotoSansSC-VF.ttf) is not installed; Orbit Pop needs it (SIL OFL, every church character)")
    f = ImageFont.truetype(NOTO, size)
    f.set_variation_by_name("Black")
    return f


def face_of(colour):
    return "oswald" if colour in ("number", "sub") else "noto"


@functools.lru_cache(maxsize=2048)
def mask(text, size, face="noto", tracking=None, vertical=False):
    """Text as an L mask with room for glow and shadow. Characters are set one by one on their advances (+ tracking x size),
    so neighbours never overlap. Returns (mask, ink bbox, baseline y or None, [(char, pen centre x, pen y)])."""
    tracking = (TRACK if face == "noto" else 0.0) if tracking is None else tracking
    size = max(8, int(round(size)))
    f = font(size, face)
    pad = int(size * 0.42) + 14
    chars = list(text)
    pos = []
    if vertical:
        adv = size * (1 + tracking)
        w, h = size + 2 * pad, int(adv * len(chars)) + 2 * pad
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        for i, c in enumerate(chars):
            cx, cy = pad + size / 2, pad + i * adv + adv / 2
            if c.strip():
                d.text((cx, cy), c, font=f, fill=255, anchor="mm")
            pos.append((c, cx, cy))
        base = None
    else:
        advs = [f.getlength(c) for c in chars]
        width = sum(advs) + tracking * size * max(0, len(chars) - 1)
        asc, desc = f.getmetrics()
        w, h = int(width) + 2 * pad + 2, asc + desc + 2 * pad
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        x, base = float(pad), pad + asc
        for c, a in zip(chars, advs):
            if c.strip():
                d.text((x, base), c, font=f, fill=255, anchor="ls")
            pos.append((c, x + a / 2, base))
            x += a + tracking * size
    bb = m.getbbox() or (0, 0, w, h)
    return m, bb, base, tuple(pos)


def _gradient(w, h, c0, c1, mode):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if mode == "tl":
        t = (xx / max(w, 1) + yy / max(h, 1)) / 2
    elif mode == "tr":
        t = ((w - xx) / max(w, 1) + yy / max(h, 1)) / 2
    else:
        t = yy / max(h, 1)
    t = np.clip(t, 0, 1)[..., None]
    return np.asarray(c0, np.float32) * (1 - t) + np.asarray(c1, np.float32) * t


def _blur(m, r):
    return np.asarray(m.filter(ImageFilter.GaussianBlur(max(0.1, r))), np.float32) / 255


@functools.lru_cache(maxsize=4096)
def sprite(text, size, colour="white", tracking=None, vertical=False, glow=True):
    """The layered word as RGBA, re-centred so its ink sits at the image centre. colour: white | lime | flat_yellow | mint |
    number | sub. Returns (img, ink_w, ink_h, dy) with dy = ink centre minus the baseline (0 for a vertical column)."""
    size = max(8, int(round(size)))
    face = face_of(colour)
    m, bb, base, _ = mask(text, size, face, tracking, vertical)
    w, h = m.size
    out = np.zeros((h, w, 4), np.float32)

    def over(col, a):
        a = np.clip(a, 0, 1)[..., None]
        out[..., :3] = np.asarray(col, np.float32) * a + out[..., :3] * (1 - a)
        out[..., 3:] = a + out[..., 3:] * (1 - a)
    sh = Image.new("L", (w, h)); sh.paste(m, (0, int(round(size * 0.04))))
    over((0, 0, 0), _blur(sh, size * 0.09) * 0.65)                     # shadow: black 65 %, blur 9 %, 4 % down
    if glow and colour in GLOW:
        over(GLOW[colour], _blur(m, size * 0.14) * 0.40)               # key glow 40 %, blur 14 %
    over(INK, np.asarray(m.filter(ImageFilter.MaxFilter(7)), np.float32) / 255 * 0.70)   # 3 px stroke #0E1014 70 %
    a = np.asarray(m, np.float32) / 255
    c0, c1, mode = FILLS[colour]
    fill = np.zeros((h, w, 3), np.float32)
    fill[bb[1]:bb[3], bb[0]:bb[2]] = _gradient(bb[2] - bb[0], bb[3] - bb[1], c0, c1, mode)
    k = max(2, int(round(size * 0.03)))                                  # bevel: inner edge 3 % of the size
    up = np.zeros_like(a); up[k:, k:] = a[:-k, :-k]
    dn = np.zeros_like(a); dn[:-k, :-k] = a[k:, k:]
    hi = np.clip(a - up, 0, 1) * 0.45
    lo = np.clip(a - dn, 0, 1) * 0.30
    fill = fill + (255 - fill) * hi[..., None]
    fill = fill * (1 - lo[..., None])
    av = a[..., None]
    out[..., :3] = fill * av + out[..., :3] * (1 - av)
    out[..., 3:] = av + out[..., 3:] * (1 - av)
    out[..., 3] *= 255
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    hw, hh = int(max(cx, w - cx)) + 1, int(max(cy, h - cy)) + 1
    canvas = Image.new("RGBA", (2 * hw, 2 * hh))
    canvas.alpha_composite(img, (int(round(hw - cx)), int(round(hh - cy))))
    return canvas, bb[2] - bb[0], bb[3] - bb[1], (cy - base) if base is not None else 0.0


def char_offsets(text, size, colour, tracking=None, vertical=False):
    """Each character's own ink centre relative to the whole word's ink centre: [(char, dx, dy)] (spaces skipped).
    Used to animate digits, sub-word letters and characters one by one at exactly the place the whole word puts them."""
    face = face_of(colour)
    m, bb, base, pos = mask(text, size, face, tracking, vertical)
    wcx, wcy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    f = font(size, face)
    out = []
    for c, px, py in pos:
        if not c.strip():
            continue
        if vertical:
            cb = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((px, py), c, font=f, anchor="mm")
        else:
            cb = f.getbbox(c, anchor="ls")
            a = f.getlength(c)
            cb = (px - a / 2 + cb[0], py + cb[1], px - a / 2 + cb[2], py + cb[3])
        out.append((c, (cb[0] + cb[2]) / 2 - wcx, (cb[1] + cb[3]) / 2 - wcy))
    return out


@functools.lru_cache(maxsize=64)
def sub_size(cap=SUB_CAP):
    """Oswald Bold font size whose cap height is `cap` px."""
    f = font(200, "oswald")
    b = f.getbbox("H", anchor="ls")
    return max(20, int(round(200 * cap / max(1, -b[1]))))


# ---- words ------------------------------------------------------------------------------------------------------------------
def disp_times(ln, text):
    """Spoken time for each character of a displayed substring of the line."""
    ct = char_times(ln)
    src = ln["text"]
    start = src.find(text.strip()) if text.strip() in src else 0
    out, j = [], start
    for ch in text:
        k = src.find(ch, j) if ch.strip() else -1
        if k >= 0 and k < len(ct):
            out.append(ct[k]); j = k + 1
        else:
            out.append(out[-1] if out else (ct[min(j, len(ct) - 1)] if ct else ln["start"]))
    return out


def tokens(text):
    """Word units: Chinese words (jieba when installed, else pairs), Latin words."""
    try:
        import jieba
        jieba.setLogLevel(60)
        parts = [p for p in jieba.cut(text) if p.strip()]
    except Exception:                                            # noqa: BLE001
        parts = re.findall(r"[A-Za-z0-9'%.,:]+|[^\sA-Za-z0-9]{1,2}", text)
    out = []
    for p in parts:
        if out and not any(c.isalnum() or is_cjk(c) for c in p):
            out[-1] += p; continue
        if out and (len(p) == 1 and is_cjk(p) and len(out[-1]) < 4 and p in "的了吗呢吧啊着过们地得"):
            out[-1] += p
        elif out and len(out[-1]) == 1 and out[-1] in NEG:      # a lone 不 / 没 goes with its verb: never alone at a row end
            out[-1] += p
        else:
            out.append(p)
    return out


def nchars(s):
    """Width in characters: CJK 1, Latin letters / digits 0.55."""
    return sum(1 if is_cjk(c) else 0 if not c.strip() else 0.55 for c in s)


def neg_before(t, sub):
    p = t.find(sub)
    return p > 0 and (t[p - 1] in NEG or t[max(0, p - 2):p] in ("不是", "没有")) and sub[0] not in NEG


def first_word(text):
    d = display(text).replace(" ", "")
    tk = tokens(d)
    return tk[0] if tk else ""


def verse_ok(sub, text):
    """A verse reference the speaker said: the full 和合本 book name in the line (雅各书, not 雅各) with the chapter (and
    verse) digits right after it (约翰福音21章, 约翰福音 3:16, 诗篇第23篇), and a sub of the English book name (or its first
    3+ letters; PSALMS for PSALM) with the same chapter, and the same verse if the sub gives one."""
    m = re.fullmatch(r"\s*((?:[1-3]\s)?[A-Z][A-Z ]*?)\.?\s+(\d+)(?::(\d+)(?:-(\d+))?)?\s*", sub.upper())
    if not m:
        return False
    book, ch, vs, ve = m.group(1).strip(), m.group(2), m.group(3), m.group(4)
    t = text.replace(" ", "")
    for zh, en in sorted(BOOKS.items(), key=lambda kv: -len(kv[0])):
        if not (en == book or (len(book) >= 3 and en.startswith(book)) or (book.endswith("S") and book[:-1] == en)):
            continue
        for r in re.finditer(re.escape(zh) + r"第?(\d+)(?:[章篇]?[:：](\d+)(?:[-–~至到](\d+))?|[章篇](?:第?(\d+)节)?)?", t):
            c_, v_ = r.group(1), r.group(2) or r.group(4)
            if c_ == ch and (not vs or vs == v_) and (not ve or ve == r.group(3)):
                return True
    return False


def sub_ok(sub, text):
    """(ok, why): English the speaker says (every Latin word of the sub is in the line), or a verse reference he names."""
    said = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    words = re.findall(r"[A-Za-z]+", sub)
    if words and all(w.lower() in said for w in words) and not re.search(r"\d", sub):
        return True, "spoken English"
    if verse_ok(sub, text):
        return True, "verse reference"
    return False, "not English he says and not a verse reference he names (never a translation)"


# ---- checks & planning page ---------------------------------------------------------------------------------------------
def check(plan, hits=None):
    """The rules as (errors, warnings). hits = the sounded designed moments [(t, kind, group)] from render.py move_hits(),
    one group per block (a kick folds into the next block; the opening push into block 1 only when block 1's first move
    peaks within 0.67 s, f14 + 6); without it, an estimate."""
    err, warn = [], []
    lines = plan.get("lines", [])
    dur = plan.get("duration") or (lines[-1]["end"] if lines else 0)
    count = {}
    colours = {}
    last = len(lines) - 1
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"; t = ln.get("text", "")
        mv = ln.get("move") or ""
        zone = ln.get("zone") or "C"
        ex = ln.get("exit") or ""
        if mv not in MOVES:
            err.append(f"{tag}: move must be one of {[m for m in MOVES if m]}"); continue
        if ln.get("zone") not in ZONES:
            err.append(f"{tag}: zone is C (default), A (top band behind the head) or D (glow column)")
        if ln.get("exit") not in EXITS:
            err.append(f"{tag}: exit is null / \"plain\" or \"kick\"")
        kc = ln.get("key_colour") or "lime"
        if kc not in KEY_COLOURS:
            err.append(f"{tag}: key_colour is lime (default), flat_yellow or mint")
        elif ln.get("key") and kc != "lime":
            colours[kc] = colours.get(kc, 0) + 1
        count[mv] = count.get(mv, 0) + 1
        for f_ in ("key", "number", "unit", "lead", "word"):
            v = ln.get(f_)
            if v and v not in t:
                err.append(f"{tag}: {f_} '{v}' is not an exact part of the line '{t}'")
        for r in ln.get("rows") or []:
            if r not in t:
                err.append(f"{tag}: row '{r}' is not an exact part of the line '{t}'")
        if ln.get("rows") and norm("".join(ln["rows"])) != norm(t):
            err.append(f"{tag}: rows must cover the whole line, in order (every word shows)")
        for r in ln.get("rows") or []:
            d = display(r).replace(" ", "")
            if d and (d[-1] in NEG or d.endswith(CONDITIONS)):
                err.append(f"{tag}: row '{r}' ends on a negation or condition; it stays whole in one row (never the 不 on its own)")
        for f_ in ("key", "word"):
            v = ln.get(f_)
            if v and v in t and neg_before(t, v):
                err.append(f"{tag}: {f_} '{v}' leaves out the negation before it; include it so the meaning stays")
        if ln.get("key") and mv == "number":
            err.append(f"{tag}: one key per block: a number block has no key word (the number is its key)")
        if ln.get("key"):
            d = display(ln["key"]); c = nchars(d)
            if zone != "A" and c > 5:
                warn.append(f"{tag}: key '{ln['key']}' is long; an L row holds 4 characters (it shrinks to fit 864 px)")
        if zone == "A":
            if mv in ("tilt", "column"):
                err.append(f"{tag}: zone A (top band) and the {mv} move both sit above the chin: one per block")
            dk = display(ln.get("key") or "").replace(" ", "")
            if not ln.get("key"):
                err.append(f"{tag}: zone A puts the line's key in the top band behind the head: set \"key\"")
            elif nchars(dk) > 4:
                err.append(f"{tag}: the top band holds one short word (at most 4 characters), not '{ln['key']}'")
            elif re.search(r"[A-Za-z0-9]", dk) or not all(is_cjk(c) for c in dk):
                err.append(f"{tag}: the top band splits its word around the head: Chinese characters only, never a Latin word or digits ('{ln['key']}')")
            elif (dk[0] in NEG or dk.startswith(CONDITIONS) or dk[:(len(dk) + 1) // 2][-1] in NEG
                  or (len(dk) > 1 and len(dk[(len(dk) + 1) // 2:]) == 1 and dk[-1] in NEG)):
                err.append(f"{tag}: the top band would split a negation or condition around the head ('{ln['key']}'); use zone C")
            if mv in ("slide", "mixed") and ln.get("key") and first_word(t) and dk.startswith(first_word(t)):
                err.append(f"{tag}: the key is the XL first word and the top-band word at once (drawn twice); use one of them")
        if mv == "column" and zone not in ("C", "D") or zone == "D" and mv != "column":
            err.append(f"{tag}: zone D is the glow column: move \"column\" and zone \"D\" go together")
        if mv == "column":
            w_ = ln.get("word") or ln.get("key")
            if not w_:
                err.append(f"{tag}: move column needs \"word\" (the takeaway, at most 6 characters)")
            elif nchars(display(w_)) > 6:
                err.append(f"{tag}: the glow column holds at most 6 characters ('{w_}')")
            if ln.get("key") and ln.get("word") and ln["key"] != ln["word"]:
                err.append(f"{tag}: one key per block: the column is the block's key (key must be empty or the same word)")
            if i != last:
                err.append(f"{tag}: the glow column is the closing takeaway, held to the end: it must be the last line")
            if ex:
                warn.append(f"{tag}: the glow column holds to the last frame; its exit is ignored")
        if mv == "tilt":
            w_ = display(ln.get("word") or "").replace(" ", "")
            if not w_:
                err.append(f"{tag}: move tilt needs \"word\": the two-character turn word")
            elif len(w_) != 2 or not all(is_cjk(c) for c in w_):
                err.append(f"{tag}: the tilted pair is exactly 2 characters, one each side of the head ('{ln.get('word')}')")
            elif w_[0] in NEG:
                err.append(f"{tag}: never split a negation across the head ('{w_}')")
            elif w_ not in TURN_WORDS:
                warn.append(f"{tag}: the tilted pair is for a turn word (其实, 但是, 可是, 原来, 而是); '{w_}' is not one")
            if ln.get("word") and t.find(ln["word"]) > 2:
                warn.append(f"{tag}: the tilted pair works on a pause at the start of the line; '{ln['word']}' comes late")
            if ln.get("key"):
                warn.append(f"{tag}: the tilted pair is this block's sounded moment; the key pops silently")
        if mv in ("slide", "mixed"):
            fw = first_word(t)
            if not fw or len(fw) > 2 or not all(is_cjk(c) for c in fw):
                err.append(f"{tag}: the XL first word is 1-2 characters ('{fw}'); split the line or use rows")
            elif fw[0] in NEG or display(t).replace(" ", "").startswith(CONDITIONS):
                err.append(f"{tag}: never an XL 不 and never an XL condition: negations and conditions stay whole in one size")
            if ln.get("key") and fw and display(ln["key"]).replace(" ", "").startswith(fw) and len(display(ln["key"]).replace(" ", "")) > len(fw):
                err.append(f"{tag}: the key '{ln['key']}' would be split by the XL first word '{fw}'")
        if mv == "number":
            if not ln.get("number"):
                err.append(f"{tag}: move number needs \"number\" (digits)")
            elif not re.fullmatch(r"[0-9]+%?", ln["number"]):
                err.append(f"{tag}: number '{ln['number']}' must be digits (write numbers as digits, % as %)")
            elif len(ln["number"].rstrip("%")) > 4:
                err.append(f"{tag}: a number holds at most 4 digits")
            if MONEY.search(t):
                err.append(f"{tag}: never money, offerings or $ as a number (brand sheet)")
            n_ = ln.get("number") or ""
            if ln.get("unit") and n_ in t and not t[t.find(n_) + len(n_):].lstrip(" ").startswith(ln["unit"]):
                err.append(f"{tag}: unit '{ln['unit']}' must follow the number directly")
            if ln.get("lead") and n_ in t and not t[:t.find(n_)].rstrip(" ").endswith(ln["lead"]):
                err.append(f"{tag}: lead '{ln['lead']}' must come directly before the number")
        if ln.get("sub"):
            ok, why = sub_ok(ln["sub"], t)
            if not ok:
                err.append(f"{tag}: sub '{ln['sub']}' is {why}")
            if sum(1 for c in ln["sub"] if c.strip()) > 14:
                err.append(f"{tag}: the English sub-word holds at most 14 letters")
        if ln.get("glitch") and ex != "kick":
            err.append(f"{tag}: the slice glitch is only f0 of a Kick Exit (exit \"kick\")")
        if ln.get("push") and ex != "kick":
            err.append(f"{tag}: the push cut (C2) runs under a Kick Exit (exit \"kick\")")
        if ex == "kick":
            if i == last:
                err.append(f"{tag}: the last block holds to the end; a Kick Exit ends a section before the next one")
            elif lines[i + 1].get("start", 0) - ln.get("end", 0) < 0.25 - 1e-6:
                warn.append(f"{tag}: a Kick Exit lands in a pause of at least 0.25 s; here only "
                            f"{lines[i + 1]['start'] - ln['end']:.2f} s before the next line")
        if "巴仙" in t:
            err.append(f"{tag}: write percentages as % (brand rule), not 巴仙")
        if "他" in t and re.search(r"神|主|耶稣|基督|上帝|天父", t):
            warn.append(f"{tag}: check the pronoun: God / Jesus is always 祂; 他 stays only for a person")
    for k, br in enumerate(plan.get("broll") or []):      # B-roll without the speaker (sheet p.6): zone C only
        if not isinstance(br, dict) or not isinstance(br.get("from"), (int, float)) or not isinstance(br.get("to"), (int, float)) or br["to"] <= br["from"]:
            err.append(f"broll {k + 1}: give {{\"from\": s, \"to\": s, \"face\": [x0, y0, x1, y1] or null}} (output pixels)"); continue
        f_ = br.get("face")
        if f_ is not None and not (isinstance(f_, (list, tuple)) and len(f_) == 4 and f_[2] > f_[0] and f_[3] > f_[1]):
            err.append(f"broll {k + 1}: face is [x0, y0, x1, y1] on the 1080x1920 output, or null")
        for i, ln in enumerate(lines):
            if ln.get("start", 0) < br["to"] and ln.get("end", 0) > br["from"]:
                mv = ln.get("move") or ""
                if (ln.get("zone") or "C") == "A" or mv in ("tilt", "column"):
                    err.append(f"line {ln.get('id', i + 1)}: B-roll at {br['from']:.2f}-{br['to']:.2f}s has no speaker: no top band, "
                               f"tilted pair or glow column there (zone C only)")
    for i, ln in enumerate(lines):
        if ln.get("sub_at") is not None:
            v = ln["sub_at"]
            if not isinstance(v, (int, float)) or not ln.get("sub") or not (ln.get("start", 0) - 0.5 <= v <= ln.get("end", 0)):
                err.append(f"line {ln.get('id', i + 1)}: sub_at is the time (s) the sub-word starts typing, inside the line, with a \"sub\"")
    for mv, cap in (("tilt", 2), ("slide", 3), ("column", 1)):
        if count.get(mv, 0) > cap:
            err.append(f"at most {cap} {mv} per video ({count[mv]} now)")
    for kc, n in colours.items():
        if n > 1:
            warn.append(f"key colour {kc} is used {n} times; the sheet allows it once per video")
    kicks = [ln["end"] for ln in lines if ln.get("exit") == "kick"]
    if hits:
        kicks = [t for t, k, _ in hits if k == "kick"] or kicks
    for a, b in zip(kicks, kicks[1:]):
        if b - a < 6.0 - 1e-6:
            err.append(f"Kick Exits at {a:.1f}s and {b:.1f}s are under 6 s apart (at most 1 per 6 s)")
    for f_, gap, what in (("glitch", 10.0, "slice glitch"), ("push", 10.0, "push cut (C2)")):
        ts_ = [ln["end"] for ln in lines if ln.get(f_) and ln.get("exit") == "kick"]
        for a, b in zip(ts_, ts_[1:]):
            if b - a < gap:
                err.append(f"{what}s at {a:.1f}s and {b:.1f}s are under {gap:.0f} s apart")
    ms = sorted(hits) if hits is not None else sorted((ln.get("start", 0), ln.get("move") or "pop", i) for i, ln in enumerate(lines)
                                                     if ln.get("move") or ln.get("key"))
    for (a, na, ga), (b, nb, gb) in zip(ms, ms[1:]):     # every designed move, sounded or silent; one block = one moment
        if ga != gb and b - a < 1.5 - 1e-6:                # an error on render.py's hit times; a rough warning without them
            (err if hits is not None else warn).append(f"designed moments {na} at {a:.2f}s and {nb} at {b:.2f}s are under 1.5 s apart (at least 1.5 s)")
    pts = [0.0] + [m[0] for m in ms] + [dur]
    for a, b in zip(pts, pts[1:]):
        if b - a > 10.5:
            warn.append(f"no designed moment between {a:.1f}s and {b:.1f}s; the brand rule asks for one at least every 10 s")
    if dur > 45.5 and (plan.get("channel") or "main") == "main":
        warn.append(f"the clip is {dur:.0f}s; the main channel's rule is 45 s maximum")
    return err, warn


def ts(t):
    t = max(0.0, float(t)); return f"{int(t // 60):02d}:{t % 60:05.2f}"


MOVE_ZH = {"": "落定", "pop": "弹出", "slide": "侧滑入", "mixed": "大小混排", "number": "数字落定", "tilt": "斜字弹出", "column": "竖排光柱"}
ZONE_ZH = {"C": "胸前 C", "A": "头后顶带 A", "D": "左侧光柱 D"}


def plan_md(plan, sounds=None):
    out = [f"# 企划页 · Planning page (Orbit Pop 环绕弹字): {os.path.basename(plan.get('video') or '')}", "",
           "| # | 时间 time | 讲话原句 line | 区 zone | 动作 move | 主色 key | 细节 | 出场 exit | 音效 sound |", "|---|---|---|---|---|---|---|---|---|"]
    snd = {s["line"]: s for s in (sounds or [])}
    for ln in plan.get("lines", []):
        mv = ln.get("move") or ""
        zone = ln.get("zone") or "C"
        key = ln.get("number") or ln.get("key") or ("-" if mv != "column" else ln.get("word"))
        kc = ln.get("key_colour") or "lime"
        if ln.get("key") and kc != "lime":
            key = f"{key} ({kc})"
        det = " ".join(x for x in (ln.get("word") and mv in ("tilt", "column") and f"word {ln['word']}", ln.get("lead") and f"lead {ln['lead']}",
                                    ln.get("unit") and f"unit {ln['unit']}", ln.get("sub") and f"sub {ln['sub']}",
                                    ln.get("rows") and "rows " + " / ".join(ln["rows"])) if x)
        ex = "held to the end" if mv == "column" else " ".join(x for x in (ln.get("exit") or "plain", ln.get("glitch") and "glitch", ln.get("push") and "push") if x)
        s = snd.get(ln.get("id"))
        sd = (s["sound"] + (f" ({s['silent']})" if s.get("silent") else "")) if s else "-"
        out.append(f"| {ln.get('id')} | {ts(ln['start'])}-{ts(ln['end'])} | {ln['text']} | {ZONE_ZH.get(zone, zone)} | {MOVE_ZH.get(mv, mv)} {mv} | {key} | {det} | {ex} | {sd} |")
    cam = plan.get("camera") or {}
    out += ["", f"Camera: opening push {'on' if cam.get('push', True) else 'off'} (100 -> 112 % in 14 frames); face {cam.get('face') or [0.5, 0.3]}, "
            f"chin y {cam.get('chin') or 'auto'}, head top y {cam.get('head_top') or 'auto'}; wide / 1.15x tight at pause cuts "
            f"{'on' if cam.get('alternate', True) else 'off'}; drift {cam.get('drift', 0.4)}. Text is pinned to the screen.",
            "", "Rules: the speaker's own words only, God is 祂, scripture in 和合本 wording, digits for numbers; one key per block (a key word "
            "or a number), negations whole, never money; English sub-words only for English he says or a verse reference he names; "
            "designed moments at least 1.5 s apart, at least one every 10 s, one sounded moment per block.", "",
            "Waiting for the owner's OK before rendering (skip when the owner asked for the video directly)."]
    return "\n".join(out) + "\n"
