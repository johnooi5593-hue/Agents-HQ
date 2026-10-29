"""Shared pieces of Neon Glow (霓虹发光字): the four-layer neon sprite, the chrome type, the glow-on curve, plan checks and the
planning page. Fonts, glyph layout, motion helpers and speech timing come from the caption-card skill next to this one.

The guide in numbers (measured; Documents/Style Guides/neon-glow-reel/guideline.pdf):
  neon core   near-white yellow, top #F4F184 (paler) -> bottom #F5F358 (more saturated)
  rim         #17160F, tight dark edge about 0.05 x letter height
  glow        olive #C8C830 fading out within about 0.15 x letter height (30 px at 195 px letters)
  glow-on     no movement: opacity 0.25 -> 1, saturation 0.3 -> 1, brightness 0.55 -> 1, glow 0 -> 1 over 8 frames, ease-out
  chrome      Chinese/lead line #E8EFF6 -> #B5C5D3, dark soft shadow, typed one character at a time as spoken
"""
import os, re, sys
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
CCS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "caption-card", "scripts")
if CCS not in sys.path:
    sys.path.insert(0, CCS)
import cc  # noqa: E402
from cc import (F1, FPS, display, char_times, is_cjk, load, save, report, probe, rgb, sub_time, keys, ease_out, NEG)  # noqa: E402,F401

CORE = ("#F4F184", "#F5F358")
RIM = "#17160F"
GLOW = "#C8C830"
BLOOM = "#F5F26B"
CHROME = ("#E8EFF6", "#B5C5D3")
WHITE_OVER = ("#F4F7F9", "#C9D6DD")
cc.PALETTE["chrome"] = (CHROME[0], CHROME[1], None)
LAYOUTS = ("stack", "number")
TRANSITIONS = (None, "", "blurdark", "cut")


def word_mask(text, role, size, tracking=0.0):
    """The whole word as one L mask, plus (ink_w, ink_h)."""
    gs, box = cc.layout(text, role, size, tracking)
    pad = 2
    w, h = int(box[2] - box[0]) + 2 * pad + 4, int(box[3] - box[1]) + 2 * pad + 4
    m = Image.new("L", (max(1, w), max(1, h)))
    for g in gs:
        m.paste(g["mask"], (int(round(g["x"] - box[0] + pad)), int(round(g["y"] - box[1] + pad))), g["mask"])
    return m, (box[2] - box[0], box[3] - box[1])


def fit_word(text, role, size, max_w, max_h, min_size=40):
    s = size
    while True:
        m, ink = word_mask(text, role, s)
        if (ink[0] <= max_w and ink[1] <= max_h) or s <= min_size:
            return s, m, ink
        s *= 0.95


def _odd(n):
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


class Neon:
    """Pre-rendered layers of one neon word (glow, rim, core) and its glow-on composite per frame."""

    def __init__(self, mask, ink_h, core=CORE, glow=GLOW, rim=RIM, with_glow=True, rim_k=1.0, glow_scale=1.0):
        h = float(max(20.0, ink_h)); self.h = h
        self.pad = int(h * (0.42 + 0.35 * (glow_scale - 1))) + 8
        W, H = mask.width + 2 * self.pad, mask.height + 2 * self.pad
        M = Image.new("L", (W, H)); M.paste(mask, (self.pad, self.pad))
        self.size = (W, H)
        fa = np.asarray(M, np.float32) / 255
        rg = M.filter(ImageFilter.MaxFilter(_odd(h * 0.05 * rim_k)))
        ra = np.asarray(rg.filter(ImageFilter.GaussianBlur(max(2, h * 0.05 * rim_k))), np.float32) / 255
        self.rim_a = np.clip(ra * 1.4, 0, 1); self.rim_c = np.asarray(rgb(rim), np.float32)
        if with_glow:
            gs = glow_scale
            gg = M.filter(ImageFilter.MaxFilter(_odd(h * 0.05 * gs)))
            ga = np.asarray(gg.filter(ImageFilter.GaussianBlur(max(3, h * 0.11 * gs))), np.float32) / 255 * min(1.0, 0.9 * gs)
            ba = np.asarray(M.filter(ImageFilter.GaussianBlur(max(6, h * 0.3 * gs))), np.float32) / 255 * (0.18 * gs * gs)
            # a hot inner glow hugging the letters (the "lit tube" look of the enhanced mode)
            ia = np.asarray(M.filter(ImageFilter.GaussianBlur(max(2, h * 0.035))), np.float32) / 255
            self.inner_a = np.clip(ia * 0.9 * max(0.0, gs - 1.0) * 1.5, 0, 1)
            self.glow_a, self.glow_c = np.clip(ga, 0, 1), np.asarray(rgb(glow), np.float32)
            self.bloom_a, self.bloom_c = np.clip(ba, 0, 1), np.asarray(rgb(BLOOM), np.float32)
        else:
            self.glow_a = None; self.inner_a = None
        ys = np.where(fa.max(1) > 0.2)[0]
        y0, y1 = (ys.min(), ys.max()) if len(ys) else (0, H)
        t = np.clip((np.arange(H, dtype=np.float32) - y0) / max(1, y1 - y0), 0, 1)[:, None, None]
        top, bot = np.asarray(rgb(core[0]), np.float32), np.asarray(rgb(core[1]), np.float32)
        self.core_c = np.broadcast_to(top + (bot - top) * t, (H, W, 3)).astype(np.float32)
        self.core_a = fa
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.diag = (xx + 0.45 * yy) / (W + 0.45 * H)                    # coordinate of the diagonal shine sweep
        # sparkle points: on the top edges of the letters
        edge = (fa > 0.5) & (np.vstack([np.zeros((1, W), np.float32), fa[:-1]]) < 0.3)
        ys_, xs_ = np.nonzero(edge)
        pts = []
        if len(xs_):
            order = np.argsort(xs_)
            for k in np.linspace(0.08, 0.92, 5):
                i = order[int(k * (len(order) - 1))]; pts.append((float(xs_[i]), float(ys_[i])))
        self.sparkle_pts = pts
        self.cache = {}

    def image(self, p, alpha=1.0, blur=0.0, glow_k=1.0, shine=None, bright=1.0):
        """Composite at glow-on progress p (0..1, already eased) with an extra opacity and blur. glow_k scales the halo
        (bursts and pulses), shine is the position (0..1) of a diagonal light band sweeping through the letters, bright
        lifts the core toward white (flares)."""
        key = (round(p, 3), round(alpha, 3), round(blur, 1), round(glow_k, 2), None if shine is None else round(shine, 3), round(bright, 2))
        if key in self.cache:
            return self.cache[key]
        band = None
        if shine is not None:
            band = np.exp(-((self.diag - shine) / 0.06) ** 2)
        op = 0.25 + 0.75 * p; sat = 0.3 + 0.7 * p; br = 0.55 + 0.45 * p
        out = np.zeros(self.size[::-1] + (4,), np.float32)

        def over(col, a):
            a3 = a[..., None]
            out[..., :3] = col * a3 + out[..., :3] * (1 - a3)
            out[..., 3:] = a3 + out[..., 3:] * (1 - a3)
        if self.glow_a is not None:
            gk = glow_k * (1 + (2.0 * band if band is not None else 0))
            over(self.bloom_c, np.clip(self.bloom_a * p * gk, 0, 1))
            over(self.glow_c, np.clip(self.glow_a * p * gk, 0, 1))
        over(self.rim_c, self.rim_a * (0.4 + 0.6 * p))
        c = self.core_c
        g = c.mean(2, keepdims=True)
        c = (g + (c - g) * sat) * br
        if bright != 1.0:
            c = c + (255 - c) * min(1.0, max(0.0, bright - 1.0))
        if band is not None:
            c = c + (np.array([255, 253, 235], np.float32) - c) * (band[..., None] * 0.92)
        over(np.clip(c, 0, 255), self.core_a)
        if self.inner_a is not None and self.glow_a is not None:
            ia = np.clip(self.inner_a * p * glow_k * 0.55, 0, 1)
            out[..., :3] = out[..., :3] + (np.array([255, 255, 220], np.float32) - out[..., :3]) * (ia * self.core_a)[..., None] * 0.35
        out[..., 3] *= op * alpha
        img = Image.fromarray(np.clip(np.dstack([out[..., :3], out[..., 3:] * 255]), 0, 255).astype(np.uint8), "RGBA")
        if blur > 0.5:
            img = img.convert("RGBa").filter(ImageFilter.GaussianBlur(blur)).convert("RGBA")
        if len(self.cache) > 48:
            self.cache.clear()
        self.cache[key] = img
        return img


def disp_times(ln, text):
    """Spoken time for each character of a displayed substring (display() drops punctuation)."""
    ct = char_times(ln)
    src = ln["text"]
    start = src.find(text.strip()) if text.strip() in src else 0
    out, j = [], start
    for ch in text:
        k = src.find(ch, j) if ch.strip() else -1
        if k >= 0:
            out.append(ct[k]); j = k + 1
        else:
            out.append(out[-1] if out else ct[min(j, len(ct) - 1)] if ct else ln["start"])
    return out


# ---- checks & planning page ---------------------------------------------------------------------------------------------
def check(plan):
    err, warn = [], []
    lines = plan.get("lines", [])
    neon_t = []
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"; t = ln.get("text", "")
        for f in ("keyword", "lead", "over"):
            v = ln.get(f)
            if v and v not in t:
                err.append(f"{tag}: {f} '{v}' is not an exact part of the line '{t}'")
        if ln.get("over") and not ln.get("keyword"):
            err.append(f"{tag}: over needs a keyword to sit on")
        if ln.get("layout") and ln["layout"] not in LAYOUTS:
            err.append(f"{tag}: layout must be one of {LAYOUTS}")
        if ln.get("transition") not in TRANSITIONS:
            err.append(f"{tag}: transition must be null, blurdark or cut")
        kw = ln.get("keyword")
        if kw and kw in t:
            neon_t.append(ln.get("start", 0))
            p = t.find(kw)
            if p > 0 and (t[p - 1] in NEG or t[max(0, p - 2):p] in ("不是", "没有")) and kw[0] not in NEG:
                warn.append(f"{tag}: the neon word '{kw}' leaves out the negation before it; include it or put the negation in the lead")
            d = display(kw); c = sum(1 for x in d if is_cjk(x))
            if c > 5 or (not c and len(d.split()) > 3):
                warn.append(f"{tag}: neon word '{kw}' is long; it glows best at 1-3 words or 2-5 characters (it will shrink)")
    n = len(lines)
    if n and len(neon_t) > max(3, int(n * 0.5)):
        warn.append(f"{len(neon_t)} neon words in {n} lines; one every 3-6 s keeps each glow special")
    for a, b in zip(neon_t, neon_t[1:]):
        if b - a < 1.5:
            warn.append(f"neon words at {a:.1f}s and {b:.1f}s are under 1.5 s apart")
    spoken = cc.norm("".join(ln.get("text", "") for ln in lines))
    for k, o in enumerate(plan.get("overlays") or []):
        if o.get("kind") != "bubble":
            err.append(f"overlay {k + 1}: kind must be bubble"); continue
        if cc.norm(o.get("text")) not in spoken:
            err.append(f"bubble overlay: text '{o.get('text')}' must be words actually spoken")
    for k, m in enumerate(plan.get("moments") or []):
        if m.get("kind") != "window" or not (isinstance(m.get("start"), (int, float)) and m.get("end", 0) > m.get("start", 0)):
            err.append(f"moment {k + 1}: kind window with numeric start < end (B-roll inside a dark rounded frame)")
    return err, warn


def ts(t):
    t = max(0.0, float(t)); return f"{int(t // 60):02d}:{t % 60:05.2f}"


def plan_md(plan):
    out = [f"# 企划页 · Planning page (Neon Glow): {os.path.basename(plan.get('video') or '')}", "",
           "| # | 时间 time | 讲话原句 line | 银色行 lead | 发光词 neon | 叠字 over | 版式 | 转场 |", "|---|---|---|---|---|---|---|---|"]
    for ln in plan.get("lines", []):
        out.append(f"| {ln.get('id')} | {ts(ln['start'])}-{ts(ln['end'])} | {ln['text']} | {ln.get('lead') or ('(whole line)' if not ln.get('keyword') else '-')} | "
                   f"{ln.get('keyword') or '-'} | {ln.get('over') or ''} | {ln.get('layout') or ''} | {ln.get('transition') or ''} |")
    for o in plan.get("overlays") or []:
        out.append(f"- 聊天泡泡 bubble {ts(o['start'])}: {o.get('text')}")
    for m in plan.get("moments") or []:
        out.append(f"- 暗框 window {ts(m['start'])}-{ts(m['end'])}")
    out += ["", "Rules: every line is typed in chrome; one neon word per chosen line (exact words, negations kept), about one every 3-6 s.",
            "", "Waiting for the owner's OK before rendering (skip when the owner asked for the video directly)."]
    return "\n".join(out) + "\n"


_STAR = {}


def star(size, color=(255, 250, 215)):
    """A four-point sparkle with a soft centre, as RGBA."""
    size = max(8, int(size))
    if size in _STAR:
        return _STAR[size]
    n = size * 2 + 1
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) - size
    r = np.sqrt(xx ** 2 + yy ** 2) / size
    ray = np.exp(-(xx / (size * 0.05)) ** 2) * np.clip(1 - np.abs(yy) / size, 0, 1) ** 1.6
    ray = np.maximum(ray, np.exp(-(yy / (size * 0.05)) ** 2) * np.clip(1 - np.abs(xx) / size, 0, 1) ** 1.6)
    core = np.exp(-(r / 0.16) ** 2)
    halo = np.exp(-(r / 0.45) ** 2) * 0.35
    a = np.clip(np.maximum(np.maximum(ray, core), halo), 0, 1)
    img = np.dstack([np.full((n, n), c, np.float32) for c in color] + [a * 255]).astype(np.uint8)
    _STAR[size] = Image.fromarray(img, "RGBA")
    return _STAR[size]


def streak(width, height, color=(255, 248, 200)):
    """A horizontal anamorphic light streak, as RGBA."""
    w, h = max(4, int(width)), max(4, int(height))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.exp(-((yy - h / 2) / (h * 0.18)) ** 2) * np.clip(1 - np.abs(xx - w / 2) / (w / 2), 0, 1) ** 1.3
    a = np.maximum(a, np.exp(-((yy - h / 2) / (h * 0.5)) ** 2) * np.exp(-((xx - w / 2) / (w * 0.08)) ** 2) * 0.8)
    img = np.dstack([np.full((h, w), c, np.float32) for c in color] + [np.clip(a, 0, 1) * 255]).astype(np.uint8)
    return Image.fromarray(img, "RGBA")
