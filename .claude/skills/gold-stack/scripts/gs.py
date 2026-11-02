"""Shared pieces of Gold Stack (金色叠字): the type (Noto Sans SC Black, white or brand gold, stroke, shadow, glow), the
staircase layout, the plan checks and the planning page. Speech timing, compositing and ffmpeg helpers come from the
caption-card / poster-kinetic skills next to this one, so every style transcribes and reports the same way.

The brand sheet (owner-approved 2026-11-01): Documents/Style Guides/gold-stack/guideline.pdf
  type      Noto Sans SC Black for everything (CJK, Latin, digits); sizes S 72 / M 120 / L 180 / N 300 px
  colour    white #FFFFFF -> #E2E5EA, one gold #FBC238 per block (key word or number), glow = gold at 45 %
            (plan key_style "negative", only when the owner asks for it: the gold item as a photo negative; see negative-key)
  layers    shadow black 70 % (blur 12 % of size, 5 % down), stroke 3 px #08090B 60 %, glow (gold only), fill
  safe      text x 86..994, nothing at x > 950 for y 1000..1700, top >= 200, block bottom <= 1620, 40 px below the chin
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
SIZES = {"S": 72, "M": 120, "L": 180, "N": 300}
MAXCH = {"S": 8, "M": 6, "L": 4, "N": 4}
GOLD = (251, 194, 56)
INK = (8, 9, 11)
WHITE = ((255, 255, 255), (226, 229, 234))
GREY = ((168, 172, 180), (140, 144, 152))
GLOW_WHITE = (255, 240, 205)                     # the warm halo around white words
SAFE_L, SAFE_R, SAFE_RB = 86, 994, 950           # sides; right edge between y 1000 and 1700 (platform buttons)
TOP, BOTTOM = 200, 1620
MOVES = (None, "", "title", "slam", "number", "writeon", "spin", "question", "behind")
TRANSITIONS = (None, "", "leak")
EXITS = (None, "", "plain", "pulse")
KEY_STYLES = (None, "", "gold", "negative")          # plan key_style: gold (also when left out) or negative (on request)
MONEY = re.compile(r"[$￥¥€£]|RM|块钱|美金|元|令吉|奉献|捐|money|dollar", re.I)


@functools.lru_cache(maxsize=64)
def font(size):
    if not NOTO:
        raise SystemExit("Noto Sans SC (NotoSansSC-VF.ttf) is not installed; Gold Stack needs it (SIL OFL, every church character)")
    f = ImageFont.truetype(NOTO, max(8, int(round(size))))
    f.set_variation_by_name("Black")
    return f


def mask(text, size, tracking=0.0):
    """Text as an L mask with a padding border; returns (mask, pad, ink_w, ink_h)."""
    f = font(size)
    pad = int(size * 0.85) + 12                    # room for the wide bloom
    if tracking:
        adv = [f.getlength(c) for c in text]
        width = sum(adv) + tracking * size * max(0, len(text) - 1)
    else:
        width = f.getlength(text)
    x0, y0, x1, y1 = f.getbbox(text, anchor="ls")
    asc = -y0
    w, h = int(max(width, x1 - x0)) + 2 * pad, int(y1 - y0) + 2 * pad
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if tracking:
        x = pad
        for c, a in zip(text, adv):
            d.text((x, pad + asc), c, font=f, fill=255, anchor="ls")
            x += a + tracking * size
    else:
        d.text((pad - x0, pad + asc), text, font=f, fill=255, anchor="ls")
    bb = m.getbbox() or (0, 0, w, h)
    return m, pad, bb[2] - bb[0], bb[3] - bb[1], bb


@functools.lru_cache(maxsize=4096)
def sprite(text, size, colour="white", tracking=0.0, glow=None):
    """The layered text as RGBA, cropped so its ink sits at the image centre. colour: white | gold | ink | grey | neg
    (neg = the letter shape only, plain white with no shadow, stroke or glow: the mask a negative key word is cut with,
    same canvas as the other colours so it lands in the same place). Returns (img, ink_w, ink_h)."""
    m, pad, iw, ih, bb = mask(text, size, round(tracking, 2))
    w, h = m.size
    out = np.zeros((h, w, 4), np.float32)

    def over(col, a):
        a = a[..., None]
        out[..., :3] = np.asarray(col, np.float32) * a + out[..., :3] * (1 - a)
        out[..., 3:] = a + out[..., 3:] * (1 - a)
    if colour not in ("ink", "neg"):
        sh = Image.new("L", (w, h)); sh.paste(m, (0, int(size * 0.05)))
        over((0, 0, 0), np.asarray(sh.filter(ImageFilter.GaussianBlur(size * 0.12)), np.float32) / 255 * 0.70)
    if (glow if glow is not None else colour in ("gold", "white")):
        # more glow (owner 2026-11-01): gold gets a wide bloom and a strong close glow, white a soft warm halo
        g1 = np.asarray(m.filter(ImageFilter.GaussianBlur(size * 0.40)), np.float32) / 255
        g2 = np.asarray(m.filter(ImageFilter.GaussianBlur(size * 0.15)), np.float32) / 255
        if colour == "gold":
            over(GOLD, np.clip(g1 * 1.6, 0, 1) * 0.40)
            over((255, 214, 110), np.clip(g2 * 1.8, 0, 1) * 0.75)
        else:
            over(GLOW_WHITE, np.clip(g1 * 1.6, 0, 1) * 0.22)
            over(GLOW_WHITE, np.clip(g2 * 1.8, 0, 1) * 0.30)
    if colour not in ("ink", "neg"):
        over(INK, np.asarray(m.filter(ImageFilter.MaxFilter(7)), np.float32) / 255 * 0.60)
    fa = np.asarray(m, np.float32) / 255
    if colour in ("white", "grey"):
        top, bot = WHITE if colour == "white" else GREY
        t = np.clip((np.arange(h, dtype=np.float32) - bb[1]) / max(1, bb[3] - bb[1]), 0, 1)[:, None, None]
        fill = np.asarray(top, np.float32) + (np.asarray(bot, np.float32) - np.asarray(top, np.float32)) * t
        fill = np.broadcast_to(fill, (h, w, 3))
    else:
        fill = np.broadcast_to(np.asarray(GOLD if colour == "gold" else (255, 255, 255) if colour == "neg" else INK, np.float32), (h, w, 3))
    a = fa[..., None]
    out[..., :3] = fill * a + out[..., :3] * (1 - a)
    out[..., 3:] = a + out[..., 3:] * (1 - a)
    out[..., 3] *= 255
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    # re-centre on the ink
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    half_w = int(max(cx, w - cx)) + 1; half_h = int(max(cy, h - cy)) + 1
    canvas = Image.new("RGBA", (2 * half_w, 2 * half_h))
    canvas.alpha_composite(img, (int(round(half_w - cx)), int(round(half_h - cy))))
    return canvas, iw, ih


def ink_w(text, size, tracking=0.0):
    return mask(text, size, tracking)[2]


# ---- words and rows ------------------------------------------------------------------------------------------------------
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
    for p in parts:                                            # keep digits+unit and short particles with their word
        if out and not any(c.isalnum() or is_cjk(c) for c in p):  # punctuation stays with the word before it (no lone "?")
            out[-1] += p; continue
        if out and (len(p) == 1 and is_cjk(p) and len(out[-1]) < 4 and p in "的了吗呢吧啊着过们地得"):
            out[-1] += p
        else:
            out.append(p)
    return out


def neg_before(t, sub):
    p = t.find(sub)
    return p > 0 and (t[p - 1] in NEG or t[max(0, p - 2):p] in ("不是", "没有")) and sub[0] not in NEG


# ---- checks & planning page ---------------------------------------------------------------------------------------------
def moments(plan):
    """Designed moments as (time, name, group) with pairs folded into one group."""
    out = []
    lines = plan.get("lines", [])
    for i, ln in enumerate(lines):
        mv = ln.get("move") or ""
        t = ln.get("start", 0)
        if ln.get("transition") == "leak":
            out.append((t, "leak", i))
        if mv in ("title", "slam", "number", "writeon", "spin", "question", "behind"):
            sub = {"slam": ln.get("a"), "number": ln.get("number"), "writeon": ln.get("number"), "spin": ln.get("word"),
                   "behind": ln.get("word")}.get(mv)
            if sub and sub in ln.get("text", "") and ln.get("words"):
                t = sub_time(ln, sub)                          # when the move really happens: its word is spoken
            out.append((t, mv, i))
        if ln.get("track") and ln.get("transition") != "leak":
            out.append((t, "track", i))
        if ln.get("exit") == "pulse":
            out.append((ln.get("end", t), "pulse", i))
    if plan.get("close"):
        out.append(((plan.get("duration") or 0) - 1.5, "close", len(lines)))
    return sorted(out)


def check(plan, ms=None):
    """The rules as (errors, warnings). ms = the designed moves' hit times [(t, move, group)] for the 2 s rule (render.py
    move_hits()[0], the frame each move lands); without it, an estimate from the lines' spoken times."""
    err, warn = [], []
    lines = plan.get("lines", [])
    dur = plan.get("duration") or (lines[-1]["end"] if lines else 0)
    count = {}
    if plan.get("key_style") not in KEY_STYLES:
        err.append('key_style is "gold" (the normal look, also when left out) or "negative" (the key word as a photo negative, only when the owner asks)')
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"; t = ln.get("text", "")
        mv = ln.get("move") or ""
        if mv not in MOVES:
            err.append(f"{tag}: move must be one of {[m for m in MOVES if m]}"); continue
        if ln.get("transition") not in TRANSITIONS:
            err.append(f"{tag}: transition is null or \"leak\"")
        if ln.get("exit") not in EXITS:
            err.append(f"{tag}: exit is null, \"plain\" or \"pulse\"")
        count[mv] = count.get(mv, 0) + 1
        fields = {"slam": ["a", "b"], "number": ["number"], "writeon": ["number"], "spin": ["word"], "behind": ["word"]}.get(mv, [])
        if mv == "behind" and ln.get("word"):
            n_ = sum(1 for c in display(ln["word"]) if c.strip())
            if n_ > 4:
                warn.append(f"{tag}: a word behind the speaker reads best at 2-4 characters ('{ln['word']}' will shrink)")
            if ln.get("key"):
                warn.append(f"{tag}: the word behind the speaker is the line's gold item; the key is not used")
        for f_ in fields:
            if not ln.get(f_):
                err.append(f"{tag}: move {mv} needs \"{f_}\"")
        for f_ in ("key", "a", "b", "number", "unit", "word"):
            v = ln.get(f_)
            if v and v not in t:
                err.append(f"{tag}: {f_} '{v}' is not an exact part of the line '{t}'")
        for r in ln.get("rows") or []:
            if r not in t:
                err.append(f"{tag}: row '{r}' is not an exact part of the line '{t}'")
        if ln.get("rows") and norm("".join(ln["rows"])) != norm(t):
            err.append(f"{tag}: rows must cover the whole line, in order (every word shows)")
        for f_ in ("key", "b", "word"):
            v = ln.get(f_)
            if v and v in t and neg_before(t, v):
                err.append(f"{tag}: {f_} '{v}' leaves out the negation before it; include it so the meaning stays")
        if mv == "slam" and ln.get("a") and ln.get("b") and ln["a"] in t and ln["b"] in t and t.find(ln["b"]) < t.find(ln["a"]):
            err.append(f"{tag}: slam a must come before b in the line")
        if mv in ("number", "writeon"):
            if ln.get("number") and not re.search(r"[0-9]", ln["number"]):
                err.append(f"{tag}: number '{ln['number']}' must be digits (write numbers as digits)")
            if MONEY.search(t):
                err.append(f"{tag}: never money, offerings or $ as a gold number (brand sheet)")
        if mv == "slam" and ln.get("start", 0) < 3.0:
            err.append(f"{tag}: the Giant Slam is the main point: at least 3 s in, never the opening")
        if mv == "title" and i != 0:
            err.append(f"{tag}: the Title Rise is the opening line only")
        if mv == "title" and sum(1 for c in display(t) if c.strip()) > 8:
            warn.append(f"{tag}: a title reads best at 2-6 characters; this one is long (it shrinks to fit)")
        if ln.get("key"):
            d = display(ln["key"]); c = sum(1 for x in d if is_cjk(x))
            if c > 4 or (not c and len(d.split()) > 2):
                warn.append(f"{tag}: key '{ln['key']}' is long; an L row holds 4 characters (it will shrink)")
        if "巴仙" in t:
            err.append(f"{tag}: write percentages as % (brand rule), not 巴仙")
    for mv, cap in (("title", 1), ("slam", 1), ("spin", 1), ("behind", 2)):
        if count.get(mv, 0) > cap:
            err.append(f"at most {cap} {mv} per video ({count[mv]} now)")
    flashes = sum(1 for ln in lines if ln.get("flash"))
    if flashes > 2:
        err.append(f"at most 2 flash frames per video ({flashes} now)")
    for ln in lines:
        if ln.get("flash") and (ln.get("move") or "") != "slam":
            warn.append(f"line {ln.get('id')}: a flash frame belongs straight after the slam (or inside the closing push)")
    leaks = sum(1 for ln in lines if ln.get("transition") == "leak")
    if leaks > 2:
        warn.append(f"{leaks} light leaks; 1-2 per video keeps each chapter change special")
    if sum(1 for ln in lines if ln.get("track") and ln.get("transition") != "leak") > 3:
        warn.append("more than 3 tracking-close section starts")
    ms = moments(plan) if ms is None else ms
    for (a, na, ga), (b, nb, gb) in zip(ms, ms[1:]):
        if ga != gb and b - a < 2.0 and not (na == "leak" and nb != "leak" and gb == ga):
            warn.append(f"designed moments {na} at {a:.1f}s and {nb} at {b:.1f}s are under 2 s apart")
    pts = [0.0] + [m[0] for m in ms] + [dur]
    for a, b in zip(pts, pts[1:]):
        if b - a > 10.5:
            warn.append(f"no designed moment between {a:.1f}s and {b:.1f}s; the brand rule asks for one at least every 10 s")
    if dur > 45.5:
        warn.append(f"the clip is {dur:.0f}s; the brand rule is 45 s maximum")
    return err, warn


def ts(t):
    t = max(0.0, float(t)); return f"{int(t // 60):02d}:{t % 60:05.2f}"


MOVE_ZH = {"": "叠字", "title": "标题升起", "slam": "巨字砸入", "number": "数字长大", "writeon": "手写数字", "spin": "3D翻转", "question": "金色划线",
           "behind": "字在人后"}


def plan_md(plan):
    out = [f"# 企划页 · Planning page (Gold Stack): {os.path.basename(plan.get('video') or '')}", "",
           "| # | 时间 time | 讲话原句 line | 动作 move | 金色 gold | 细节 | 转场 / 出场 |", "|---|---|---|---|---|---|---|"]
    for ln in plan.get("lines", []):
        mv = ln.get("move") or ""
        gold = ln.get("b") or ln.get("number") or ln.get("key") or "-"
        det = " ".join(x for x in (ln.get("a") and f"A {ln['a']}", ln.get("unit") and f"unit {ln['unit']}", ln.get("word") and f"{'behind' if mv == 'behind' else 'spin'} {ln['word']}",
                                    ln.get("rows") and "rows " + " / ".join(ln["rows"]), ln.get("flash") and "flash") if x)
        tr = " ".join(x for x in (ln.get("transition") or "", ln.get("track") and "track", ln.get("exit") or "") if x)
        out.append(f"| {ln.get('id')} | {ts(ln['start'])}-{ts(ln['end'])} | {ln['text']} | {MOVE_ZH.get(mv, mv)} {mv} | {gold} | {det} | {tr} |")
    cam = plan.get("camera") or {}
    if plan.get("key_style") == "negative":
        out += ["", "Key word: photo negative (the picture inverted inside the letters)."]
    out += ["", f"Camera: {'slight' if cam.get('strength', 1.0) < 0.7 else 'strong'} movement {'on' if cam.get('on', True) else 'off'}; face {cam.get('face') or [0.5, 0.3]}, chin y {cam.get('chin') or 'auto'}; "
            f"wide / 1.15x tight at pause cuts {'on' if cam.get('alternate', True) else 'off'}. Closing push: {'yes' if plan.get('close') else 'no'}.",
            "", "Rules: the speaker's own words only (interpreter cut), one gold item per block, negations whole, never money; "
            "a designed moment every 3-5 s, none within 2 s of another.", "",
            "Waiting for the owner's OK before rendering (skip when the owner asked for the video directly)."]
    return "\n".join(out) + "\n"
