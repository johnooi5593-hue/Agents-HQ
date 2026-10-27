"""Shared pieces of Caption Card (字卡动效): fonts per role, the pro layered type renderer, colours, timing helpers and the
plan checks. Speech timing, text units and ffmpeg helpers come from the poster-kinetic / yellow-serif / reel skills next
to this one, so every skill transcribes and reports the same way.

The guide in numbers (measured from the reference reel; see Documents/Style Guides/xixi-trading-reel/guideline.pdf):
  card     cyan #63E6DA box 112 px high, blue #1D3AF5 slanted text 150 px (overhangs the box), centre y 0.51, hard cuts
  hook     white #E9E7E4 rows 125 px, key row yellow #FAF536 165 px; rows blur in 4 f; key row scatters 2.2x and gathers 5 f
  number   condensed digits, ink height 0.47 of the frame, gradient #8CD941 -> #689634; in 6 f (0.45 -> 1.15 -> 0.97 -> 1.0)
  writeon  each character drawn left to right with a light trail, 4 f each, 2 f apart; bloom exit 5 f
  punch    each character pops 2 f apart: 0.4 -> 1.35 -> 1.0, rotation +-15 -> 0, with a 1.35x picture punch-in
  layers   heavy face, top-light gradient, dark soft shadow #192113, outer glow, background blurred and dimmed under big type
"""
import functools, math, os, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
PKS = os.path.join(SKILLS, "poster-kinetic", "scripts")
if PKS not in sys.path:
    sys.path.insert(0, PKS)
import pk  # noqa: E402  (poster-kinetic: display, char_times, units, probe, report, load, save, FFMPEG, norm, NEG, is_cjk)
import pfonts  # noqa: E402
from pk import FFMPEG, NEG, char_times, display, is_cjk, load, norm, probe, report, save  # noqa: E402,F401

FPS = 30; F1 = 1 / FPS; W0, H0 = 1080, 1920
SAFE = {"left": 70, "right": 1010, "top": 140, "bottom": 1420}
KINDS = ("card", "hook", "number", "writeon", "punch")
TRANSITIONS = (None, "", "flash", "blurcut")


def rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# (top, bottom, glow) gradients for big type; "glow": None = no outer glow
PALETTE = {
    "lime":   ("#8CD941", "#689634", "#6BBA46"),     # the reel's "90"
    "green":  ("#86DD46", "#479745", "#6BBA46"),     # the reel's $12,800
    "yellow": ("#F0EF3B", "#9BA228", "#F4F260"),     # the reel's punch line
    "key":    ("#FCF94A", "#E5DC2A", "#FAF536"),     # the reel's hook key row
    "white":  ("#F4F3F0", "#D6D4CF", None),          # hook rows, labels
    "gold":   ("#FFE17A", "#D99A1E", "#FFC94A"),     # sermon: grace, promise
    "cyan":   ("#9AF7EE", "#3FB8AE", "#63E6DA"),     # sermon: peace, Spirit
    "rose":   ("#FFB3B8", "#D5576A", "#FF8A96"),     # sermon: love, warning
}
DEFAULT_COLOR = {"hook": "key", "number": "lime", "writeon": "green", "punch": "yellow"}
SHADOW = ("#192113", 18, 10, 0.85)                    # colour, blur, dy, alpha
CARD = {"box": "#63E6DA", "text": "#1D3AF5", "text2": "#1530D8"}


# ---- fonts per role -------------------------------------------------------------------------------------------------
UF, WF = pfonts.UF, pfonts.WF
PUNCH_FONT = pfonts._find("庞门正道标题体.ttf")
BEBAS = pfonts._find("BebasNeue Bold.otf") or pfonts._find("Oswald-Bold.ttf")
ARIAL_BLACK = pfonts._find("ariblk.ttf")


@functools.lru_cache(maxsize=100000)
def pick(ch, role):
    """(path, weight, synthetic slant, scale_x) for one character in a role. Every character is checked for a real glyph,
    so Traditional characters and 祂 / 袮 fall back to 思源黑体 Heavy instead of empty boxes."""
    asc = ch.isascii()
    if role == "card":
        if asc:
            r = pfonts.resolve_role("latin_italic")
            if r:
                return r[0], r[3], 0.0, 1.0
        p, wt, sl, _ = pfonts.pick(ch, "cjk_slant")
        return p, wt, sl, 1.0
    if role == "number" and asc and BEBAS:
        return BEBAS, None, 0.0, 0.86
    if role in ("punch",) and not asc and PUNCH_FONT and pfonts.has_glyph(PUNCH_FONT, None, ch):
        return PUNCH_FONT, None, 0.0, 1.0
    if asc and role in ("hook", "punch", "writeon", "number") and ch.strip():
        if role == "writeon" and BEBAS:
            return BEBAS, None, 0.0, 0.9
        if ARIAL_BLACK:
            return ARIAL_BLACK, None, 0.0, 1.0
    p, wt, sl, _ = pfonts.pick(ch, "cjk")
    return p, wt, 0.0, 1.0


@functools.lru_cache(maxsize=20000)
def glyph(ch, role, size):
    """One character as an L mask: (mask, ox, oy, adv) with ox/oy the mask's top-left relative to pen x / baseline."""
    path, wt, sl, sx = pick(ch, role)
    ft = pfonts._load(path, max(6, int(round(size))), wt)
    adv = ft.getlength(ch) * sx
    if not ch.strip():
        return None, 0, 0, adv
    x0, y0, x1, y1 = ft.getbbox(ch, anchor="ls")
    pad = int(size * 0.08) + 2
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text((pad - x0, pad - y0), ch, font=ft, fill=255, anchor="ls")
    ox, oy = x0 - pad, y0 - pad
    if sx != 1.0:
        m = m.resize((max(1, int(round(w * sx))), h), Image.LANCZOS); ox *= sx
    if sl:
        extra = int(abs(sl) * h) + 2
        m2 = Image.new("L", (m.width + extra, h)); m2.paste(m, (0, 0))
        base = -oy                                             # baseline row inside the mask
        m = m2.transform(m2.size, Image.AFFINE, (1, sl, -sl * base, 0, 1, 0), resample=Image.BICUBIC)
    return m, ox, oy, adv


def layout(text, role, size, tracking=0.0):
    """Lay a string out on one baseline. Returns glyphs [{ch, mask, x, y, adv, cx}] (x/y = mask top-left relative to
    pen 0 / baseline 0) and the ink box (x0, y0, x1, y1)."""
    gs, x = [], 0.0
    for ch in text:
        m, ox, oy, adv = glyph(ch, role, size)
        if m is not None:
            gs.append({"ch": ch, "mask": m, "x": x + ox, "y": oy, "adv": adv, "pen": x})
        x += adv + (size * tracking if ch.strip() else 0)
    if not gs:
        return gs, (0, -size * 0.7, 1, 0)
    ink = []
    for g in gs:
        a = np.asarray(g["mask"]); ys, xs = np.nonzero(a > 40)
        if len(xs):
            ink.append((g["x"] + xs.min(), g["y"] + ys.min(), g["x"] + xs.max(), g["y"] + ys.max()))
    if not ink:
        return gs, (0, -size * 0.7, x, 0)
    box = (min(b[0] for b in ink), min(b[1] for b in ink), max(b[2] for b in ink), max(b[3] for b in ink))
    for g in gs:
        g["cx"] = g["x"] + g["mask"].width / 2 - (box[0] + box[2]) / 2
        g["cy"] = g["y"] + g["mask"].height / 2 - (box[1] + box[3]) / 2
    return gs, box


def fit_size(text, role, size, max_w, max_h=None, tracking=0.0, min_size=30):
    """Shrink until the ink fits max_w (and max_h)."""
    s = size
    while True:
        gs, b = layout(text, role, s, tracking)
        if (b[2] - b[0] <= max_w and (max_h is None or b[3] - b[1] <= max_h)) or s <= min_size:
            return s, gs, b
        s *= 0.95


# ---- the pro layered sprite ---------------------------------------------------------------------------------------------
def layered(mask, top, bot, ytop, ybot, my, glow=None, shadow=SHADOW, glow_r=22, glow_a=0.6):
    """One glyph mask -> RGBA sprite with (bottom to top) outer glow, dark soft shadow and a vertical gradient fill whose
    top/bottom are the LINE's ink top/bottom (ytop/ybot, in baseline coordinates; my = this mask's top in the same frame).
    Returns (image, pad) where pad is the extra border added on each side."""
    sc, sb, sdy, sa = shadow if shadow else (None, 0, 0, 0)
    pad = int(max(glow_r * 2.2 if glow else 0, sb * 2.2 + abs(sdy))) + 4
    w, h = mask.width + 2 * pad, mask.height + 2 * pad
    M = Image.new("L", (w, h)); M.paste(mask, (pad, pad))
    out = np.zeros((h, w, 4), np.float32)

    def over(col, a):
        a = a[..., None]
        out[..., :3] = np.asarray(col, np.float32) * a + out[..., :3] * (1 - a)
        out[..., 3:] = a + out[..., 3:] * (1 - a)
    if glow:
        g = np.asarray(M.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(glow_r)), np.float32) / 255 * glow_a
        over(rgb(glow), g)
    if shadow:
        s = Image.new("L", (w, h)); s.paste(M.filter(ImageFilter.MaxFilter(3)), (0, int(sdy)))
        s = np.asarray(s.filter(ImageFilter.GaussianBlur(sb)), np.float32) / 255 * sa
        over(rgb(sc), np.clip(s * 1.25, 0, 1))
    yy = (np.arange(h, dtype=np.float32) - pad + my - ytop) / max(1.0, ybot - ytop)
    t = np.clip(yy, 0, 1)[:, None, None]
    fill = np.asarray(rgb(top), np.float32) + (np.asarray(rgb(bot), np.float32) - np.asarray(rgb(top), np.float32)) * t
    fa = np.asarray(M, np.float32) / 255
    a = fa[..., None]
    out[..., :3] = np.broadcast_to(fill, (h, w, 3)) * a + out[..., :3] * (1 - a)
    out[..., 3:] = a + out[..., 3:] * (1 - a)
    out[..., 3] *= 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA"), pad


def styled_line(text, role, size, colour, tracking=0.0, glow=True, shadow=SHADOW, glow_r=None):
    """A line as per-glyph pro sprites: [{ch, img, cx, cy, w, h}] centred on the line's ink centre, plus the ink size."""
    gs, box = layout(text, role, size, tracking)
    top, bot, gl = PALETTE.get(colour, PALETTE["key"]) if not colour.startswith("#") else (colour, colour, None)
    out = []
    for g in gs:
        img, pad = layered(g["mask"], top, bot, box[1], box[3], g["y"], gl if glow else None, shadow, glow_r or max(10, size * 0.12))
        out.append({"ch": g["ch"], "img": img, "cx": g["cx"], "cy": g["cy"]})
    return out, (box[2] - box[0], box[3] - box[1])


# ---- motion helpers -------------------------------------------------------------------------------------------------------
def ease_out(x): x = min(1, max(0, x)); return 1 - (1 - x) ** 3
def ease_expo(x): x = min(1, max(0, x)); return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)
def ease_io(x): x = min(1, max(0, x)); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def keys(f, frames, values):
    """Piecewise interpolation of keyframes (frame numbers -> values) with an ease-out on each segment."""
    if f <= frames[0]:
        return values[0]
    for i in range(1, len(frames)):
        if f <= frames[i]:
            p = ease_out((f - frames[i - 1]) / max(1e-6, frames[i] - frames[i - 1]))
            return values[i - 1] + (values[i] - values[i - 1]) * p
    return values[-1]


def hblur(img, k):
    k = int(k)
    if k < 2:
        return img
    a = np.asarray(img.convert("RGBa"), np.float32)
    p = np.pad(a, ((0, 0), (k, k), (0, 0))); c = np.cumsum(p, axis=1)
    o = (c[:, k:-k] - c[:, :-2 * k]) / k if p.shape[1] > 2 * k else a
    o = np.pad(o, ((0, 0), (0, max(0, a.shape[1] - o.shape[1])), (0, 0)))[:, :a.shape[1]]
    return Image.fromarray(o.clip(0, 255).astype(np.uint8), "RGBa").convert("RGBA")


def put(fr, img, cx, cy, s=1.0, rot=0.0, alpha=1.0, blur=0.0, mblur=0.0, bright=1.0):
    """Composite an RGBA sprite centred at (cx, cy) with scale, rotation, opacity, gaussian blur, horizontal motion blur
    and brightness."""
    if alpha <= 0.01 or s <= 0.01:
        return
    if abs(s - 1) > 0.004:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
    if abs(rot) > 0.3:
        img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
    if bright != 1.0:
        a = np.asarray(img, np.float32); a[..., :3] = np.clip(a[..., :3] * bright + (bright - 1) * 40, 0, 255); img = Image.fromarray(a.astype(np.uint8), "RGBA")
    if blur > 0.5:
        g = int(blur * 2) + 2
        big = Image.new("RGBA", (img.width + 2 * g, img.height + 2 * g)); big.alpha_composite(img, (g, g))
        img = big.convert("RGBa").filter(ImageFilter.GaussianBlur(blur)).convert("RGBA")
    if mblur >= 2:
        img = hblur(img, mblur)
    if alpha < 0.995:
        img = img.copy(); img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    _paste(fr, img, cx, cy)


def _paste(fr, img, cx, cy):
    x, y = int(round(cx - img.width / 2)), int(round(cy - img.height / 2))
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(img.width, fr.width - x), min(img.height, fr.height - y)
    if x1 <= x0 or y1 <= y0:
        return
    fr.alpha_composite(img.crop((x0, y0, x1, y1)), (x + x0, y + y0))


# ---- planning helpers ------------------------------------------------------------------------------------------------------
def sub_time(ln, sub, ct=None):
    """Spoken time of the first character of an exact substring of the line."""
    ct = ct or char_times(ln)
    p = ln["text"].find(sub)
    return ct[p] if p >= 0 else ln["start"]


def has_digit(s):
    return bool(re.search(r"[0-9０-９一二三四五六七八九十百千万零两]", s))


def check(plan):
    """Rules as errors (must fix) and warnings (look again)."""
    err, warn = [], []
    lines = plan.get("lines", [])
    bigs = []
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"; t = ln.get("text", "")
        kind = ln.get("kind") or "card"
        if kind not in KINDS:
            err.append(f"{tag}: kind must be one of {KINDS}"); continue
        if ln.get("transition") not in TRANSITIONS:
            err.append(f"{tag}: transition must be null, flash or blurcut")
        if ln.get("color") and not (ln["color"] in PALETTE or re.fullmatch(r"#[0-9a-fA-F]{6}", ln["color"])):
            err.append(f"{tag}: color must be one of {tuple(PALETTE)} or #hex")
        if kind == "card":
            continue
        bigs.append((ln.get("start", 0), kind))
        if not (ln.get("why") or "").strip():
            err.append(f"{tag}: a {kind} moment needs \"why\": big type is only for the line whose words earn it")
        fields = {"hook": ["rows"], "number": ["number"], "writeon": ["phrase"], "punch": ["phrase"]}[kind]
        for f_ in fields:
            if not ln.get(f_):
                err.append(f"{tag}: {kind} needs \"{f_}\"")
        subs = list(ln.get("rows") or []) + [ln.get(k) for k in ("number", "label", "unit", "phrase", "sub") if ln.get(k)]
        pos = -1
        for s_ in subs:
            if s_ not in t:
                err.append(f"{tag}: '{s_}' is not an exact part of the line '{t}'")
        for s_ in ln.get("rows") or []:
            p = t.find(s_)
            if p >= 0 and p < pos:
                err.append(f"{tag}: hook rows must follow the order of the words")
            pos = max(pos, p)
        if kind == "hook" and len(ln.get("rows") or []) > 3:
            err.append(f"{tag}: a hook has at most 3 rows")
        for r in ln.get("rows") or []:
            d = display(r); c = sum(1 for x in d if is_cjk(x))
            if c > 7 or (not c and len(d.split()) > 3):
                warn.append(f"{tag}: hook row '{r}' is long; rows read big at 2-6 characters or 1-3 words (it will shrink)")
        if kind == "number" and ln.get("number") and not has_digit(ln["number"]):
            warn.append(f"{tag}: number '{ln['number']}' has no digit; a giant number is for a real number, chapter or count")
        for key in ("phrase", "number"):
            s_ = ln.get(key)
            if s_ and s_ in t:
                p = t.find(s_)
                if p > 0 and (t[p - 1] in NEG or t[max(0, p - 2):p] in ("不是", "没有")) and s_[0] not in NEG:
                    warn.append(f"{tag}: '{s_}' leaves out the negation before it; include it so the meaning stays")
        for key, cmax, wmax in (("phrase", 7, 4), ("label", 6, 3), ("sub", 10, 4)):
            v = ln.get(key)
            if v and kind in ("punch", "writeon", "number"):
                d = display(v); c = sum(1 for x in d if is_cjk(x))
                if (c > cmax) or (not c and len(d.split()) > wmax):
                    warn.append(f"{tag}: {key} '{v}' is long; big type reads big at up to {cmax} characters or {wmax} words (it will shrink)")
    dur = plan.get("duration") or (lines[-1]["end"] if lines else 60)
    cap = max(2, round(dur / 15) + 1)
    if len(bigs) > cap:
        warn.append(f"{len(bigs)} big moments in {dur:.0f} s; about {cap} keeps each one special (cards carry the rest)")
    for (a, ka), (b, kb) in zip(bigs, bigs[1:]):
        if b - a < 3:
            warn.append(f"big moments at {a:.1f}s and {b:.1f}s are under 3 s apart")
    if sum(1 for _, k in bigs if k == "punch") > 2:
        warn.append("more than 2 punch lines; keep it for the call to action")
    return err, warn


KIND_ZH = {"card": "字卡", "hook": "三行钩子", "number": "半屏大数字", "writeon": "写出来", "punch": "行动语蹦出"}


def ts(t):
    t = max(0.0, float(t)); return f"{int(t // 60):02d}:{t % 60:05.2f}"


def plan_md(plan):
    out = [f"# 企划页 · Planning page (Caption Card): {os.path.basename(plan.get('video', ''))}", "",
           f"{plan.get('duration', '?')} s · speech-to-text {plan.get('engine', '?')} · card colours {plan.get('card', CARD)}", "",
           "| # | 时间 time | 讲话原句 line | 形式 kind | 大字内容 big type | 颜色 colour | 转场 | 为什么 why |", "|---|---|---|---|---|---|---|---|"]
    for ln in plan.get("lines", []):
        k = ln.get("kind") or "card"
        big = "-"
        if k == "hook":
            big = " / ".join(ln.get("rows") or [])
        elif k == "number":
            big = " ".join(x for x in (ln.get("label"), ln.get("number"), ln.get("unit")) if x)
        elif k in ("writeon", "punch"):
            big = ln.get("phrase", "") + (f" + {ln['sub']}" if ln.get("sub") else "")
        col = ln.get("color") or (DEFAULT_COLOR.get(k, "-") if k != "card" else "-")
        out.append(f"| {ln.get('id')} | {ts(ln['start'])}-{ts(ln['end'])} | {ln['text']} | {KIND_ZH[k]} {k} | {big} | {col} | "
                   f"{ln.get('transition') or ''} | {ln.get('why') or ''} |")
    out += ["", "Rules: every line is a caption card; 3-4 lines in a minute earn big type (a hook, a number, a phrase written on, a "
            "punch line), each with a why; the words, numbers, negations and scripture stay exactly as spoken.", "",
            "Waiting for the owner's OK before rendering (skip when the owner asked for the video directly)."]
    return "\n".join(out) + "\n"
