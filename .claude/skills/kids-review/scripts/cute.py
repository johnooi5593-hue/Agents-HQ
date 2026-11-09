"""cute.py: the kids' "cute" edition of the Caption Card renderer (kids-review skill; built on the 1107 Children review,
owner 2026-11-07: "add more motion graphic and word cute animation"; owner-approved v3 "Niceee!").

Size-agnostic: make_renderers.py copies this file next to <work>/cc916/render.py (1080x1920) and <work>/cc16/render.py
(1920x1080) and hooks it into each. It is ON with `--cute [config.json]`, or when the plan says "edition": "cute ..."
(turn it off with --no-cute; --classic always turns it off). The caption-card skill itself is never touched.
Settings: cute.json in the PLAN's folder (template kids-review/templates/cute.json), else --cute <file>, else the one
next to this file: "bubbles" (line id -> tail side), "stickers" (the sticker plan per size, relative to cute.json,
so card pops are thinned against sticker sounds), "card_y" (per-size card heights per line id).

What it draws (every word stays exactly the plan's text; only the motion and the look change):
  cards      a puffy sticker: rounded pill, thick white outline, soft pink-dark shadow, a top gloss. It wobbles in with a
             squishy elastic scale (x and y out of step), breathes and bobs while held, and pops out with a quick shrink
             and a 'poof' of 5 dots. Lines with "bubble": "left" / "right" (in the plan line, or in cute.json "bubbles")
             are speech bubbles with a tail.
  characters each character hops in one after another with jelly squash and stretch (stretched in flight, lands
             squashed, stretches up, settles) and a small overshoot rotation. The line's entrance ("anim", or the
             renderer's take-turns choice) picks the variant so neighbours still differ:
             rise -> hop, slide -> side, slam -> pop, stagger -> drop (bouncing ball), wipe -> wave, cut -> hop.
             Held characters bob and breathe gently, out of phase per character.
  key word   (plan "key") as it is spoken: a bouncy pop (1.3x with squash), then a slow scale pulse; candy gradient
             (hot pink -> peach-orange) with a white sticker rim; three sparkles twinkle at its corners.
  big type   hook: rows drop in letter by letter like bouncing balls, the key row jelly-pops; writeon: each character
             stretches in like rubber; punch: characters drop and bounce with a tilt. All with a rainbow outline (one
             candy colour per character) over a white rim and a dark soft shadow, a gentle bob while held, sparkles
             once landed, and a staggered shrink-pop exit.
  sound      one quiet "pop" per card line (its first card's entrance, 10 dB under the impact hits: pop category
             -13 dB + db -2 = -15 dB under the voice), a bubble pop on speech bubbles; dropped when a sticker sound
             (stickers.json in cute.json) is within 0.35 s, so a cut never gets two pops. Never per character; the
             poof is silent.
"""
import json, math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import cc
from cc import FPS, F1, keys, rgb, put, display, is_cjk

try:
    import cv2                                                  # fast round dilation for the outlines
except Exception:                                               # pragma: no cover
    cv2 = None

ON = False
W, H = 1080, 1920
SAFE = {"left": 70, "right": 1010, "top": 140, "bottom": 1420}
CFG = {}
STICKER_T = []
WARN = None

CANDY = ("#FF2E88", "#FF8A2B")                                  # key word fill: hot pink -> peach-orange
KEY_RIM = "#C8166A"                                             # dark pink rim outside the white key rim
RAINBOW = ["#FF4F9A", "#FF9F1C", "#FFC93C", "#2FCB78", "#3FA0F5", "#9B6BFF"]
SPARK = (255, 228, 92)
OUT_FRAMES = {"hook": 6, "number": 6, "writeon": 6, "punch": 6, "breathe": 8}
BIG_KINDS = ("hook", "writeon", "punch")
VARIANT = {"rise": "hop", "slide": "side", "slam": "pop", "stagger": "drop", "wipe": "wave", "cut": "hop"}
ROT0 = [-9, 7, -6, 10, -8, 6, -7, 9]
CUTE_FILL = {"yellow": ("#FFEB5C", "#FFB21F"), "key": ("#FFEB5C", "#FFB21F"), "lime": ("#C8F55A", "#6FD23C"),
             "green": ("#9BEA6A", "#3FC46A")}                   # candy versions of the skill's acid colours


def wants(plan):
    return str(plan.get("edition") or "").lower().startswith("cute")


def setup(w, h, safe, on, pdir, cfg_path=None, warn=None):
    """Called by render.py once the plan is read."""
    global ON, W, H, SAFE, CFG, STICKER_T, WARN
    ON, W, H, SAFE, WARN = bool(on), w, h, dict(safe), warn
    if not ON:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    cp = cfg_path or next((p for p in (os.path.join(pdir or here, "cute.json"), os.path.join(here, "cute.json"))
                           if os.path.isfile(p)), os.path.join(here, "cute.json"))   # kids-review: the plan's own cute.json first
    CFG = {}
    if os.path.isfile(cp):
        CFG = json.load(open(cp, encoding="utf-8"))
        cdir = os.path.dirname(os.path.abspath(cp))
    else:
        cdir = here
    st = CFG.get("stickers")
    if isinstance(st, dict):
        st = st.get("9x16" if H > W else "16x9")
    STICKER_T = []
    if st:
        sp = st if os.path.isabs(st) else os.path.join(cdir, st)
        if os.path.isfile(sp):
            for s in json.load(open(sp, encoding="utf-8")).get("stickers", []):
                if s.get("sfx"):
                    STICKER_T.append(float(s["t"]))
        elif warn is not None:
            warn.append(f"cute: stickers file {sp} not found; card pops are not thinned against sticker sounds")


def bubble_of(c):
    b = c.get("bubble")
    if b is None:
        b = (CFG.get("bubbles") or {}).get(str(c.get("line")))
    if b is True:
        b = "left"
    return b if b in ("left", "right") else None


# ---- drawing helpers ------------------------------------------------------------------------------------------------------
def dilate(M, r):
    r = int(round(r))
    if r < 1:
        return M
    a = np.asarray(M)
    if cv2 is not None:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        return Image.fromarray(cv2.dilate(a, k))
    out = M
    for _ in range(max(1, (r + 1) // 2)):
        out = out.filter(ImageFilter.MaxFilter(5))
    return out


def _mix(a, b, k):
    a, b = np.asarray(rgb(a), np.float32), np.asarray(rgb(b), np.float32)
    return a + (b - a) * k


def glyph_sprite(mask, top, bot, ytop, ybot, my, strokes=(), shadow=None, P=None):
    """A glyph mask -> RGBA sprite: soft shadow, outline strokes [(radius, colour)] outermost first, then the vertical
    gradient fill (top/bottom = the line's ink top/bottom). The sprite's centre is the mask's centre (pad P each side)."""
    rmax = max([r for r, _ in strokes] + [0])
    sb, sdy = (shadow[1], shadow[2]) if shadow else (0, 0)
    P = P if P is not None else int(rmax + sb * 2.2 + abs(sdy)) + 6
    w, h = mask.width + 2 * P, mask.height + 2 * P
    M = Image.new("L", (w, h)); M.paste(mask, (P, P))
    out = np.zeros((h, w, 4), np.float32)

    def over(col, a):
        a = a[..., None]
        out[..., :3] = col * a + out[..., :3] * (1 - a)
        out[..., 3:] = a + out[..., 3:] * (1 - a)
    outer = dilate(M, rmax) if rmax else M
    if shadow:
        sc, sb, sdy, sa = shadow
        s = Image.new("L", (w, h)); s.paste(outer, (0, int(sdy)))
        s = np.asarray(s.filter(ImageFilter.GaussianBlur(sb)), np.float32) / 255 * sa
        over(np.asarray(rgb(sc), np.float32), np.clip(s * 1.2, 0, 1))
    for r, col in strokes:
        m = dilate(M, r).filter(ImageFilter.GaussianBlur(0.8))
        over(np.asarray(rgb(col), np.float32), np.asarray(m, np.float32) / 255)
    yy = (np.arange(h, dtype=np.float32) - P + my - ytop) / max(1.0, ybot - ytop)
    tt = np.clip(yy, 0, 1)[:, None, None]
    t0, t1 = np.asarray(rgb(top), np.float32), np.asarray(rgb(bot), np.float32)
    fill = np.broadcast_to(t0 + (t1 - t0) * tt, (h, w, 3))
    over(fill, np.asarray(M, np.float32) / 255)
    out[..., 3] *= 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def put2(fr, img, cx, cy, sx, sy, rot=0.0, alpha=1.0, blur=0.0):
    """put() with separate x / y scale (squash and stretch)."""
    if alpha <= 0.01 or sx <= 0.01 or sy <= 0.01:
        return
    if abs(sx - 1) > 0.004 or abs(sy - 1) > 0.004:
        img = img.resize((max(1, int(img.width * sx)), max(1, int(img.height * sy))), Image.BILINEAR)
    if abs(rot) > 0.3:
        img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
    put(fr, img, cx, cy, 1.0, 0.0, alpha=alpha, blur=blur)


_SPK, _DOT = {}, {}


def sparkle_img(r):
    """A 4-point twinkle star (white core, warm yellow glow), r = half its span in px."""
    r = max(6, int(round(r / 4)) * 4)
    if r not in _SPK:
        S = 4; s = r * 2 * S + 8 * S; c = s / 2
        m = Image.new("L", (s, s)); d = ImageDraw.Draw(m)
        R, k = r * S, r * S * 0.2
        d.polygon([(c, c - R), (c + k, c - k), (c + R, c), (c + k, c + k), (c, c + R), (c - k, c + k), (c - R, c), (c - k, c - k)], fill=255)
        m = m.resize((s // S, s // S), Image.LANCZOS)
        g = m.filter(ImageFilter.GaussianBlur(r * 0.22))
        im = np.zeros((m.height, m.width, 4), np.float32)
        ga = np.asarray(g, np.float32) / 255 * 0.9; ma = np.asarray(m, np.float32) / 255
        im[..., :3] = np.asarray(SPARK, np.float32); im[..., 3] = np.clip(ga * 1.4, 0, 1)
        a = ma[..., None]
        im[..., :3] = 255 * a + im[..., :3] * (1 - a); im[..., 3] = ma + im[..., 3] * (1 - ma)
        im[..., 3] *= 255
        _SPK[r] = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8), "RGBA")
    return _SPK[r]


def dot_img(r, col):
    key = (max(2, int(round(r))), col)
    if key not in _DOT:
        rr = key[0]; s = rr * 2 + 8
        im = Image.new("RGBA", (s * 3, s * 3), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.ellipse((12, 12, s * 3 - 12, s * 3 - 12), fill=tuple(col) + (255,), outline=(255, 255, 255, 255), width=6)
        _DOT[key] = im.resize((s, s), Image.LANCZOS)
    return _DOT[key]


def twinkles(fr, pts, f, size, delay=6, cycle=22, on=12):
    """Sparkles at pts [(x, y)], each twinkling (grow, spin, shrink) in turn; f = frames since they may start."""
    for j, (x, y) in enumerate(pts):
        u = f - j * delay
        if u < 0:
            continue
        u %= cycle
        if u >= on:
            continue
        sc = math.sin(math.pi * u / on)
        if sc < 0.08:
            continue
        put(fr, sparkle_img(size), x, y, sc, u * 5.0, alpha=min(1.0, sc * 1.4))


def ball(f, D):
    """A bouncing-ball drop from D px above: (dy, sx, sy). Contacts at frames 6, 10 and 13."""
    T = (6.0, 10.0, 13.0)
    if f < T[0]:
        u = f / T[0]; dy = -D * (1 - u * u); st = 0.16 * u          # falls, stretched along the fall
    elif f < T[1]:
        u = (f - T[0]) / (T[1] - T[0]); dy = -D * 0.26 * 4 * u * (1 - u); st = 0.06 * abs(1 - 2 * u)
    elif f < T[2]:
        u = (f - T[1]) / (T[2] - T[1]); dy = -D * 0.07 * 4 * u * (1 - u); st = 0.0
    else:
        dy, st = 0.0, 0.0
    sq = sum(A * max(0.0, 1 - abs(f - c) / 1.7) for c, A in zip(T, (0.32, 0.16, 0.06)))
    return dy, 1 - st * 0.5 + sq * 0.85, 1 + st - sq


def ball_fast(f, D):
    """v3 brand check: the card drop, quicker than the big-type ball (contacts at frames 4, 7 and 9, landed by 10)."""
    T = (4.0, 7.0, 9.0)
    if f < T[0]:
        u = f / T[0]; dy = -D * (1 - u * u); st = 0.14 * u
    elif f < T[1]:
        u = (f - T[0]) / (T[1] - T[0]); dy = -D * 0.2 * 4 * u * (1 - u); st = 0.05 * abs(1 - 2 * u)
    elif f < T[2]:
        u = (f - T[1]) / (T[2] - T[1]); dy = -D * 0.05 * 4 * u * (1 - u); st = 0.0
    else:
        dy, st = 0.0, 0.0
    sq = sum(A * max(0.0, 1 - abs(f - c) / 1.4) for c, A in zip(T, (0.28, 0.12, 0.04)))
    return dy, 1 - st * 0.5 + sq * 0.85, 1 + st - sq


# frames after a character starts until it has fully landed (position, squash and rotation settled), per variant
LAND = {"drop": 10.0, "pop": 12.0, "side": 13.0, "hop": 14.0, "wave": 14.0}
MIN_CHUNK = 0.4                                                  # v3: a card chunk shorter than this joins its neighbour
LAND_MARGIN = 4                                                  # v3: every character lands >= 4 frames before its card ends


def hop(fi, var, rot0, s, dd=1):
    """One character's jelly entrance, fi frames after it starts: (dx, dy, sx, sy, rot, alpha). Settled by LAND[var]."""
    al = min(1.0, 0.25 + fi / 2.5)
    if var == "drop":
        dy, sx, sy = ball_fast(fi, s * 0.9)
        return 0.0, dy, sx, sy, keys(fi, [0, 4, 7, 10], [rot0, -0.4 * rot0, 0.15 * rot0, 0]), al
    if var == "pop":
        sx = keys(fi, [0, 3, 6, 9, 12], [0.15, 1.3, 0.86, 1.06, 1.0]); sy = keys(fi, [0, 3, 6, 9, 12], [0.15, 0.82, 1.15, 0.96, 1.0])
        return 0.0, 0.0, sx, sy, keys(fi, [0, 4, 8, 12], [1.4 * rot0, -0.5 * rot0, 0.15 * rot0, 0]), al
    if var == "side":
        dx = keys(fi, [0, 4, 7, 10], [-0.9 * s * dd, 0.08 * s * dd, -0.03 * s * dd, 0])
        sx = keys(fi, [0, 4, 7, 10, 13], [1.3, 0.82, 1.1, 0.97, 1.0]); sy = keys(fi, [0, 4, 7, 10, 13], [0.8, 1.16, 0.92, 1.02, 1.0])
        return dx, 0.0, sx, sy, keys(fi, [0, 4, 8, 12], [-8 * dd, 4 * dd, -1.5 * dd, 0]), al
    amp = 0.6 if var == "wave" else 1.0                          # hop / wave: up from below, lands squashed
    if fi < 4:
        dy = s * amp * (0.55 - 0.77 * cc.ease_out(fi / 4))          # rises past its place (ease out)
    elif fi < 7:
        u = (fi - 4) / 3; dy = -0.22 * s * amp * (1 - u * u)        # falls back (ease in) and lands at frame 7
    elif fi < 12:
        u = (fi - 7) / 5; dy = -0.05 * s * amp * 4 * u * (1 - u)    # a tiny rebound while it stretches up
    else:
        dy = 0.0
    sx = keys(fi, [0, 4, 7, 10, 14], [0.78, 0.92, 1.26, 0.93, 1.0]); sy = keys(fi, [0, 4, 7, 10, 14], [1.28, 1.1, 0.76, 1.1, 1.0])
    rot = keys(fi, [0, 4, 7, 11, 14], [rot0, -0.5 * rot0, 0.25 * rot0, -0.1 * rot0, 0])
    return 0.0, dy, sx, sy, rot, al


# ---- the sticker card -----------------------------------------------------------------------------------------------------
def sticker(bw, bh, box, ot, bubble=None):
    """The puffy card: RGBA image and the box centre inside it."""
    S = 2
    pad = int(ot + 44); tail = int(bh * 0.42) if bubble else 0
    w, h = int(bw + 2 * pad), int(bh + 2 * pad + tail)
    F = Image.new("L", (w * S, h * S)); d = ImageDraw.Draw(F)
    d.rounded_rectangle((pad * S, pad * S, (pad + bw) * S, (pad + bh) * S), radius=int(bh * 0.46 * S), fill=255)
    cx, cy = w / 2, pad + bh / 2
    if bubble:
        sd = -1 if bubble == "left" else 1
        bx = cx + sd * bw * 0.24
        x0, x1 = bx - bh * 0.2, bx + bh * 0.2
        tip = (bx + sd * bh * 0.34, pad + bh + tail * 0.9)
        d.polygon([(x0 * S, (pad + bh - 6) * S), (x1 * S, (pad + bh - 6) * S), (tip[0] * S, tip[1] * S)], fill=255)
    F = F.resize((w, h), Image.LANCZOS)
    O = dilate(F, ot).filter(ImageFilter.GaussianBlur(0.8))
    out = np.zeros((h, w, 4), np.float32)

    def over(col, a):
        a = a[..., None]
        out[..., :3] = col * a + out[..., :3] * (1 - a)
        out[..., 3:] = a + out[..., 3:] * (1 - a)
    sh = Image.new("L", (w, h)); sh.paste(O, (0, int(bh * 0.07)))
    over(np.asarray(rgb("#7A1446"), np.float32), np.asarray(sh.filter(ImageFilter.GaussianBlur(bh * 0.09)), np.float32) / 255 * 0.36)
    over(np.full(3, 255, np.float32), np.asarray(O, np.float32) / 255)
    yy = np.clip((np.arange(h, dtype=np.float32) - pad) / max(1.0, bh), 0, 1)[:, None, None]
    top, bot = _mix(box, "#FFFFFF", 0.42), _mix(box, "#E0408A", 0.10)
    fa = np.asarray(F, np.float32) / 255
    over(np.broadcast_to(top + (bot - top) * yy, (h, w, 3)), fa)
    g = Image.new("L", (w, h)); ImageDraw.Draw(g).rounded_rectangle(
        (pad + bh * 0.28, pad + bh * 0.10, pad + bw * 0.62, pad + bh * 0.30), radius=int(bh * 0.1), fill=255)
    ga = np.asarray(g.filter(ImageFilter.GaussianBlur(bh * 0.05)), np.float32) / 255 * 0.55 * fa
    over(np.full(3, 255, np.float32), ga)                        # the gloss on top: a puffy sticker
    out[..., 3] *= 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA"), (cx, cy)


_CARDS = {}


def card_build(R, text, bubble):
    key = (text, bubble)
    if key in _CARDS:
        return _CARDS[key]
    d = R.build(text)
    size = d["size"]
    ink_w = d.get("tw") or (d["bw"] - 2 * int(size * 0.27))
    bw, bh = ink_w + 2 * size * 0.42, size * 1.08
    ot = max(6.0, size * 0.1)
    k = min(1.0, (SAFE["right"] - SAFE["left"]) / (bw + 2 * ot + 2 * 24))
    if k < 0.999 and WARN is not None and len(_CARDS) < 200:
        pass                                                    # long cards just get smaller (noted in the README)
    img, (bx, by) = sticker(bw, bh, R.box, ot, bubble)
    ytop, ybot = d.get("ink", (-size * 0.8, size * 0.1))
    P = int(size * 0.09) + int(size * 0.05 * 2.2) + 10
    glyphs = []
    for i, g in enumerate(d["glyphs"]):
        m = g.get("mask")
        if m is None:
            continue
        n = glyph_sprite(m, R.c1, R.c2, ytop, ybot, g["my"], (), ("#9A1F5C", size * 0.035, size * 0.025, 0.22), P)
        kk = glyph_sprite(m, CANDY[0], CANDY[1], ytop, ybot, g["my"], [(size * 0.085, KEY_RIM), (size * 0.055, "#FFFFFF")],
                          ("#7A1446", size * 0.04, size * 0.03, 0.3), P)
        glyphs.append(dict(img=n, kimg=kk, cx=g["cx"], cy=g["cy"], ci=g["ci"], l=g["l"], r=g["r"], rot0=ROT0[i % len(ROT0)]))
    q = {"card": img, "off": (img.width / 2 - bx, img.height / 2 - by), "glyphs": glyphs, "size": size, "k": k,
         "bw": bw, "bh": bh}
    _CARDS[key] = q
    return q


def card_y(R, c):
    """v3: a line's card height for this frame size (cute.json "card_y": {"9x16": {line id: y}}), else the renderer's."""
    m = (CFG.get("card_y") or {}).get("9x16" if H > W else "16x9") or {}
    y = m.get(str(c.get("line")))
    return float(y) * H if y is not None else R.y


def land_speed(c, n, var):
    """v3: how much faster than normal the characters must come in so the last one has fully landed LAND_MARGIN frames
    before the card ends (1.0 = normal speed)."""
    sp = 1.0 if c["first"] else 1.7
    step = (2.0 if var == "wave" else 1.5) if c["first"] else 1.0
    need = (2 if c["first"] else 0.0) + max(0, n - 1) * step + LAND.get(var, 14.0)    # in the card's own frames (x sp)
    avail = (c["t1"] - c["t0"]) * FPS - LAND_MARGIN                                   # real frames
    if avail <= 1:
        return 4.0
    return max(1.0, need / (sp * avail))


def fix_timeline(tl, warn=None):
    """v3 brand check ("words that never land"): a card chunk shorter than MIN_CHUNK joins its neighbour in the same
    line (the next one, else the one before), so no word flashes by. The text is the line's own text over the joined span;
    key bars are re-mapped onto the joined card. Then land_speed() makes every character land in time.
    Since caption-card t207 (2026-11-08) the skill's card_timeline already joins short chunks (join_short) and gives
    every entry its "span", so this only catches what is left (e.g. a card the cute edition times differently)."""
    tl = [dict(c) for c in tl]
    changed = True
    while changed:
        changed = False
        for i, c in enumerate(tl):
            if c["t1"] - c["t0"] >= MIN_CHUNK or "span" not in c:
                continue
            j = i + 1 if i + 1 < len(tl) and tl[i + 1].get("line") == c.get("line") else                 i - 1 if i > 0 and tl[i - 1].get("line") == c.get("line") else None
            if j is None:
                continue
            a_, b_ = (c, tl[j]) if j > i else (tl[j], c)
            if abs(b_["t0"] - a_["t1"]) > 0.1:                  # not back to back (big type in between): leave it
                continue
            ltext = a_["ltext"]
            span = (a_["span"][0], b_["span"][1])
            text = display(ltext[span[0]:span[1]])
            ta, tb = a_["text"], b_["text"]
            oa = text.find(ta) if ta else 0
            ob = text.rfind(tb) if tb else len(text)
            keys_ = [(ka + oa, kb + oa, tk) for ka, kb, tk in a_["keys"]] + [(ka + ob, kb + ob, tk) for ka, kb, tk in b_["keys"]]
            m = dict(a_, t1=b_["t1"], text=text, span=span, keys=keys_, last=b_["last"], exit=b_["exit"])
            if warn is not None:
                warn.append(f"cute: line {c.get('line')}: card '{c['text']}' ({c['t1'] - c['t0']:.2f} s) joined to "
                            f"'{tl[j]['text']}' -> '{text}'")
            lo = min(i, j)
            tl[lo:lo + 2] = [m]
            changed = True
            break
    return tl


def draw_card(R, fr, c, t):
    """The cute card c at time t (replaces CardRenderer.draw)."""
    bub = bubble_of(c)
    q = card_build(R, c["text"], bub)
    k, size = q["k"], q["size"]
    sp = 1.0 if c["first"] else 1.7
    fe = (t - c["t0"]) * FPS * sp
    var = VARIANT.get(c["anim"], "hop")
    dd = c.get("dir", 1) or 1
    X, Y = W / 2, card_y(R, c)
    if c["first"]:
        bsx = keys(fe, [0, 3, 6, 9, 12], [0.25, 1.1, 0.93, 1.03, 1.0]); bsy = keys(fe, [0, 3, 6, 9, 12], [0.25, 0.87, 1.08, 0.98, 1.0])
    else:
        bsx = keys(fe, [0, 2, 4, 7], [0.92, 1.06, 0.98, 1.0]); bsy = keys(fe, [0, 2, 4, 7], [0.92, 0.95, 1.03, 1.0])
    ba = min(1.0, (0.25 if c["first"] else 0.8) + fe / 2.5)
    bx = 0.0
    if var == "side" and c["first"]:
        bx = keys(fe, [0, 5, 8, 11], [-0.42 * W * dd, 18 * dd, -6 * dd, 0])
        bsx *= keys(fe, [0, 5, 8], [1.22, 0.93, 1.0]); bsy *= keys(fe, [0, 5, 8], [0.86, 1.05, 1.0])
    ia = min(1.0, max(0.0, (fe - 12) / 10))                     # idle once settled: breathe and bob
    br = 1 + 0.012 * math.sin(2 * math.pi * 0.7 * t) * ia
    bob = size * k * 0.02 * math.sin(2 * math.pi * 0.55 * t + 0.7) * ia
    ex = (c["t1"] - t) * FPS
    es, ea = 1.0, 1.0
    if c["last"] and c["exit"] and ex < 4:                      # pops out: a quick swell and shrink (the poof follows)
        e = 4 - ex
        es = keys(e, [0, 1.5, 4], [1.0, 1.08, 0.05]); ea = keys(e, [0, 2.6, 4], [1.0, 1.0, 0.0])
    csx, csy = bsx * br * es, bsy * br * es
    put2(fr, q["card"], X + bx + q["off"][0] * k * csx, Y + bob + q["off"][1] * k * csy, k * csx, k * csy, alpha=ba * ea)
    n = len(q["glyphs"])
    step = (2.0 if var == "wave" else 1.5) if c["first"] else 1.0
    lead = 2 if c["first"] else 0.0
    m = land_speed(c, n, var)                                   # v3: >= 1, so the last character lands 4 frames before the end
    settle_f = (2 + n * step + 12) / m
    keyset = []
    for (a, b, tk) in c["keys"]:
        tk = max(tk, c["t0"] + (settle_f / sp) * F1 * 0.7)
        kp = (t - tk) * FPS
        if kp >= 0:
            keyset.append((a, b, kp, tk))
    for i, g in enumerate(q["glyphs"]):
        fi = fe * m - lead - i * step                          # a follow-on card's letters start at once (no empty box)
        if fi < 0:
            continue
        dx, dy, gsx, gsy, rot, al = hop(fi, var, g["rot0"], size * k, dd)
        ph = 2 * math.pi * 0.9 * t + i * 1.1
        gi = min(1.0, max(0.0, (fi - 14) / 8))
        idy = size * k * 0.035 * math.sin(ph) * gi; isc = 1 + 0.03 * math.sin(ph + 1.3) * gi
        kk = next((x for x in keyset if x[0] <= g["ci"] < x[1]), None)
        mix = 0.0
        if kk:
            kp = kk[2]; mix = min(1.0, kp / 3)
            gsx *= keys(kp, [0, 2, 5, 8], [1.0, 1.3, 0.9, 1.0]); gsy *= keys(kp, [0, 2, 5, 8], [1.0, 1.16, 0.94, 1.0])
            pu = 1 + 0.045 * math.sin(2 * math.pi * 1.4 * (kp - 8) / FPS) * min(1.0, max(0.0, (kp - 8) / 6))
            gsx *= pu; gsy *= pu
            rot += keys(kp, [0, 3, 6, 9], [0, -5 if i % 2 else 5, 2 if i % 2 else -2, 0])
        sx, sy = k * gsx * isc * es * br, k * gsy * isc * es * br
        x = X + bx + g["cx"] * k * csx + dx
        y = Y + bob + g["cy"] * k * csy + dy + idy + (1 - gsy) * size * k * 0.38     # squash sits on the baseline
        if mix < 0.99:
            put2(fr, g["img"], x, y, sx, sy, rot, alpha=al * ea * (1 - mix))
        if mix > 0.01:
            put2(fr, g["kimg"], x, y, sx, sy, rot, alpha=al * ea * mix)
    for (a, b, kp, tk) in keyset:                               # sparkles at the key word's corners
        ks = [g for g in q["glyphs"] if a <= g["ci"] < b]
        if not ks or kp < 3 or ea < 0.5:
            continue
        l = X + bx + min(g["l"] for g in ks) * k * csx; r = X + bx + max(g["r"] for g in ks) * k * csx
        top = Y + bob - size * k * 0.62; bot = Y + bob + size * k * 0.40
        pts = [(l - size * k * 0.06, top), (r + size * k * 0.08, top + size * k * 0.14), (r + size * k * 0.02, bot)]
        twinkles(fr, pts, kp - 3, size * k * 0.2)


def poofs(fr, R, timeline, t):
    """The 'poof' of 5 dots as a line's last card pops out (drawn under the cards)."""
    for c in timeline:
        if not (c["last"] and c["exit"]):
            continue
        e = (t - c["t1"]) * FPS + 2.0
        if not 0 <= e < 10:
            continue
        q = card_build(R, c["text"], bubble_of(c))
        k, size = q["k"], q["size"]
        hw, hh = q["bw"] * k / 2, q["bh"] * k / 2
        p = cc.ease_out(e / 10)
        cols = [(255, 255, 255), rgb(R.box), SPARK, (255, 255, 255), rgb(R.c1)]
        for j, ang in enumerate((200, 150, 270, 30, 330)):
            a_ = math.radians(ang)
            ux, uy = math.cos(a_), -math.sin(a_)
            x = W / 2 + ux * (hw * 0.85 + size * k * 0.7 * p); y = card_y(R, c) + uy * (hh * 0.9 + size * k * 0.55 * p)
            r = size * k * (0.11 if j % 2 == 0 else 0.08) * (1.15 - 0.85 * p)
            put(fr, dot_img(r, tuple(int(v) for v in cols[j])), x, y, alpha=0.95 * (1 - e / 10))


# ---- big type -------------------------------------------------------------------------------------------------------------
def _fill_of(colour, key):
    if not key:
        return "#FFFFFF", "#FFF3F8"
    if colour and colour.startswith("#"):
        top = colour; bot = "#" + "".join(f"{int(v):02X}" for v in _mix(colour, "#C8166A", 0.45))
        return top, bot
    if colour in CUTE_FILL:
        return CUTE_FILL[colour]
    top, bot, _ = cc.PALETTE.get(colour, cc.PALETTE["key"])
    return top, bot


def big_build(b):
    if getattr(b, "_cute", None):
        return b._cute
    rows = []
    if b.kind == "hook":
        for ri, (txt0, r) in enumerate(zip(b.ln["rows"], b.rows)):
            rows.append(dict(text=display(txt0), role="hook", size=r["size"], cy=r["cy"], t=r["t"], key=r["key"]))
    elif b.kind == "writeon":
        rows.append(dict(text=display(b.ln["phrase"]), role="writeon", size=b.size, cy=b.cy, t=b.t_in, key=True))
    else:
        rows.append(dict(text=display(b.ln["phrase"]), role=b.role, size=b.size, cy=b.cy, t=b.t_in, key=True))
    widest = 1.0
    ci = 0
    for ri, row in enumerate(rows):
        s = row["size"]
        gs, box = cc.layout(row["text"], row["role"], s)
        top, bot = _fill_of(b.color, row["key"])
        # white rows: white letters with one rainbow outline (a white rim would close the counters and blob them);
        # coloured rows: the colour, a thin white rim, then the rainbow outline
        strokes = (lambda col: [(s * 0.075, col), (s * 0.035, "#FFFFFF")]) if row["key"] else (lambda col: [(s * 0.06, col)])
        r_out = s * (0.075 if row["key"] else 0.06)
        gl = []
        for g in gs:
            img = glyph_sprite(g["mask"], top, bot, box[1], box[3], g["y"], strokes(RAINBOW[ci % len(RAINBOW)]),
                               ("#3A0A24", s * 0.06, s * 0.045, 0.6))
            gl.append(dict(img=img, cx=g["cx"], cy=g["cy"], rot0=ROT0[ci % len(ROT0)] * 1.2))
            ci += 1
        row["glyphs"] = gl; row["w"] = box[2] - box[0] + 2 * r_out; row["h"] = box[3] - box[1] + 2 * r_out
        widest = max(widest, row["w"])
    lim = (SAFE["right"] - SAFE["left"]) if (getattr(b, "xc", W / 2) == W / 2) else 2 * min(getattr(b, "xc") - 40, W - 40 - getattr(b, "xc"))
    kb = min(1.0, lim / (widest * 1.06))
    b._cute = {"rows": rows, "k": kb}
    return b._cute


def draw_big(b, fr, t, out_p):
    """A cute big-type moment at time t (replaces Big.draw_hook / draw_writeon / draw_punch)."""
    q = big_build(b)
    kb = q["k"]; xc = getattr(b, "xc", W / 2)
    land = 14.0
    gi = 0
    allpts = []
    for ri, row in enumerate(q["rows"]):
        s = row["size"] * kb
        n = len(row["glyphs"])
        for i, g in enumerate(row["glyphs"]):
            if b.kind == "punch":
                ui = b.unit_of[i] if i < len(b.unit_of) else i
                f = (t - row["t"]) * FPS - 2 * ui
            elif b.kind == "writeon":
                f = (t - row["t"]) * FPS - b.step * i
            else:
                f = (t - row["t"]) * FPS - 1.6 * i
            gi += 1
            if f < 0:
                continue
            dx = 0.0; rot = 0.0
            if b.kind == "writeon":                             # rubbery stretch in from the left
                sx = keys(f, [0, 4, 7, 10, 13], [0.2, 1.22, 0.88, 1.05, 1.0]); sy = keys(f, [0, 4, 7, 10, 13], [1.55, 0.8, 1.1, 0.97, 1.0])
                dx = keys(f, [0, 4], [-s * 0.35, 0.0]); dy = 0.0; rot = keys(f, [0, 5, 10], [-6, 3, 0])
                al = min(1.0, 0.2 + f / 2)
            elif b.kind == "hook" and row["key"]:              # the key row jelly-pops
                sx = keys(f, [0, 3, 6, 9, 12], [0.1, 1.26, 0.86, 1.06, 1.0]); sy = keys(f, [0, 3, 6, 9, 12], [0.1, 0.82, 1.16, 0.96, 1.0])
                rot = keys(f, [0, 4, 8, 12], [1.5 * g["rot0"], -0.6 * g["rot0"], 0.2 * g["rot0"], 0]); dy = 0.0
                al = min(1.0, 0.3 + f / 2)
            else:                                               # bouncing balls (hook rows, punch)
                D = s * 0.9                                     # a short drop: it never sweeps over a face above
                dy, sx, sy = ball(f, D)
                rot = keys(f, [0, 6, 10, 13], [g["rot0"], -0.3 * g["rot0"], 0.1 * g["rot0"], 0])
                al = min(1.0, 0.35 + f / 2)
            ia = min(1.0, max(0.0, (f - land) / 10))
            ph = 2 * math.pi * 0.8 * t + i * 1.1 + ri * 0.6
            dy += s * 0.025 * math.sin(ph) * ia
            isc = 1 + 0.02 * math.sin(ph + 1.2) * ia
            es, ea = 1.0, 1.0
            if out_p > 0:                                       # staggered shrink-pop exit
                oe = min(1.0, max(0.0, out_p * 1.5 - (gi - 1) * 0.06))
                es = keys(oe, [0, 0.35, 1], [1.0, 1.12, 0.0]); ea = keys(oe, [0, 0.7, 1], [1.0, 1.0, 0.0])
            x = xc + g["cx"] * kb + dx
            y = row["cy"] + g["cy"] * kb + dy + (1 - sy) * s * 0.4
            put2(fr, g["img"], x, y, kb * sx * isc * es, kb * sy * isc * es, rot, alpha=al * ea)
        if row["key"]:
            hw, hh = row["w"] * kb / 2, row["h"] * kb / 2
            allpts.append((row, [(xc - hw - s * 0.05, row["cy"] - hh * 0.9), (xc + hw + s * 0.06, row["cy"] - hh * 0.55),
                                 (xc + hw - s * 0.1, row["cy"] + hh * 0.95), (xc - hw + s * 0.15, row["cy"] + hh * 0.85)], s))
    landed = b.landed() if hasattr(b, "landed") else b.settle
    if out_p < 0.3:
        for row, pts, s in allpts:
            f = (t - max(landed, row["t"] + 10 * F1)) * FPS
            if f >= 0:
                twinkles(fr, pts, f, s * 0.16, delay=5, cycle=24, on=13)


# ---- sound ----------------------------------------------------------------------------------------------------------------
def sfx_events(timeline):
    """One quiet pop per card line (its first card), thinned against the sticker sounds."""
    ev = []
    for c in timeline:
        if not c["first"]:
            continue
        tf = c["t0"] + 3 * F1                                   # the box's first overshoot (frame 3 of the wobble)
        if any(abs(tf - s) < 0.35 for s in STICKER_T):
            continue
        bub = bubble_of(c)
        ev.append({"frame": int(round(tf * FPS)), "sound": "pop_2" if bub else "pop", "db": -2,
                   "what": f"line {c['line']} cute card wobbles in ({'speech bubble' if bub else VARIANT.get(c['anim'], 'hop')}); "
                           f"10 dB under the impact hits"})
    return ev
