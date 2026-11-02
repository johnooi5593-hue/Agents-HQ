"""Render a clip in the Gold Stack style (金色叠字) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--map tight.cutmap.json] [--frame crop|blur] [--focus 0.5]
                        [--to SECONDS] [--phone] [--no-text] [--preset medium]

Every line builds as a staircase of word units (S 72 / M 120 / L 180 px, Noto Sans SC Black, white with stroke and shadow),
each unit landing 0-3 frames before it is spoken (M2); the line's "key" is the one gold item and blooms in (M3). Line
"move": title (M1, line 1 only), slam (M4 with Light Split M5; "a", "b"), number (M6 + M7; "number", optional "unit"),
writeon (M10; "number"), spin (M9; "word"), question (M12 marker swipe). Line "transition": "leak" (T2 light-leak burn,
then the chapter vignette and a tracking close M8 on its first row); "track": true (M8 at a hard section cut, with a pop);
"exit": "pulse" (M11); "flash": true (M13, one gold frame after the slam). Plan "close": true (M14 closing push);
plan "camera": {"on", "face": [x, y], "chin": px, "alternate"} = the slight camera move: a slow drift, sway and breathing
zoom on every shot, a 3 % kick on the slam, and (with --map) a wide / 1.15x tight framing switch at pause cuts.
Plan "key_style": "negative" (only when the owner asks for the negative key word, see negative-key) draws every gold item
(key word, title key, slam B, number, write-on, spin, word behind) as a photo negative of the picture behind it over a
soft dark shadow, with no gold glow. Left out (or "gold"), the brand-gold look renders exactly as before.
Writes <out>.mp4, .srt, .pk.json (preview events), .sfx-events.json (for the sfx skill), a copy of plan.json; --phone also
<out>_phone.mp4 under 28 MiB. Prints one JSON line.
"""
import argparse, math, os, queue, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gs  # noqa: E402
from gs import (F1, FPS, W, H, SIZES, GOLD, display, disp_times, sub_time, keys, ease_out, ease_io, put, load, save, report,
                is_cjk, sprite, ink_w, tokens)  # noqa: E402

CX_SAFE = (gs.SAFE_L + gs.SAFE_RB) / 2                  # 518: centre of the caption safe zone
MAXW = gs.SAFE_RB - gs.SAFE_L                           # 864
# speech-to-text times run about 0.1 s early (measured on Pong 1101 against the voice), so a word that starts 1 frame
# before its time lands (f3) about 1 frame before the voice: the sheet's 0-3 frames early
LEAD = 1 * F1
# the word behind the speaker is largest as it rises in (1.12x at f0); its hold (+4 %) and a pulse exit stay under that
BEHIND_MAX = 1.12
BEHIND_IN = 0.40                                        # share of each of the two characters behind the head (owner 2026-11-02: larger)
BEHIND_W = 300.0                                        # a behind character starts at least this big (owner 2026-11-02: "more bigger")
BEHIND_SHOW = 0.35                                      # ... and shrinks only while it would show less than this much of itself
PULSE_F = 4                                             # a pulse exit: swell to f2, gone at f4 (a plain exit: 2 frames)
STROKE = 2                                              # the dark stroke reaches about 2 px past the ink: rows clear the margin by it


# ---- the negative key word (on request only) --------------------------------------------------------------------------------
KEY_NEG = False                                         # set from plan key_style by timeline(): True only for "negative"
NEG_SHADOW, NEG_BLUR = 0.45, 10                         # the soft dark shadow under a negative word
_LAYER = [None]                                         # the frame's negative layer while text is drawn (begin_neg / end_neg)


def gcol(colour):
    """The sprite colour a unit is drawn with: a gold item is its bare letter shape ("neg") in negative mode."""
    return "neg" if KEY_NEG and colour == "gold" else colour


def tgt(fr, colour):
    """Where a sprite of this colour is drawn: a gold item goes on the negative layer in negative mode, all else on fr."""
    return _LAYER[0] if KEY_NEG and colour == "gold" and _LAYER[0] is not None else fr


def begin_neg(fr):
    if KEY_NEG:
        _LAYER[0] = Image.new("RGBA", fr.size)


def end_neg(fr, base):
    """fr with the letters on the negative layer as a photo negative of `base` (the picture before the text went on),
    over a soft dark shadow; fr itself when the layer is empty or negative mode is off."""
    layer, _LAYER[0] = _LAYER[0], None
    if layer is None:
        return fr
    al = layer.getchannel("A")
    bb = al.getbbox()
    if not bb:
        return fr
    g = 3 * NEG_BLUR
    box = (max(0, bb[0] - g), max(0, bb[1] - g), min(fr.width, bb[2] + g), min(fr.height, bb[3] + g))
    ac = al.crop(box)
    a = np.asarray(ac, np.float32)[..., None] / 255
    sh = np.asarray(ac.filter(ImageFilter.GaussianBlur(NEG_BLUR)), np.float32)[..., None] / 255 * NEG_SHADOW
    top = np.asarray(fr.crop(box).convert("RGB"), np.float32)
    under = np.asarray(base.crop(box).convert("RGB"), np.float32)
    out = top * (1 - sh)
    out = out * (1 - a) + (255 - under) * a            # invert what was behind, before the shadow darkened it
    piece = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert(fr.mode)
    fr.paste(piece, box[:2])
    return fr


def ease_in(x):
    x = min(1, max(0, x)); return x * x


def tint(img, rgb, alpha):
    """A solid-colour ghost of a sprite (Light Split)."""
    g = Image.new("RGBA", img.size, rgb + (0,))
    g.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    return g


_HALO = {}


def halo(img, size):
    """A soft gold light the shape of a word (blurred once, cached): the glow burst and pulse on gold words."""
    key = (id(img), int(size))
    if key not in _HALO:
        g = tint(img, (255, 200, 80), 1.0)
        pad = int(size * 0.3)
        big = Image.new("RGBA", (g.width + 2 * pad, g.height + 2 * pad)); big.alpha_composite(g, (pad, pad))
        _HALO[key] = big.convert("RGBa").filter(ImageFilter.GaussianBlur(size * 0.22)).convert("RGBA")
    return _HALO[key]


def glow_pulse(fr, img, size, x, y, f, t, s=1.0, a=1.0):
    """Glow burst as the gold word lands (up to 1.0 at f6, settling by f16), then a gentle pulse while it holds. None on
    a negative word (an inverted glow would be a bright blob): its soft dark shadow is drawn by end_neg."""
    if f < 0 or KEY_NEG:
        return
    k = keys(f, [0, 6, 16], [0.2, 1.0, 0.45])
    if f > 16:
        k = 0.45 + 0.15 * math.sin(2 * math.pi * 0.9 * (f - 16) / FPS)
    put(fr, halo(img, size), x, y, s * keys(f, [0, 6, 16], [1.25, 1.12, 1.04]), alpha=k * a)


def fit_k(x, y, w, h, s=1.0):
    """The largest scale (around its centre) at which a w x h ink box at (x, y) stays inside x 86..994 (950 in the
    button band y 1000-1700) and y 200..1620; s = the scale it is drawn at, for the band test."""
    rl = gs.SAFE_RB if y + h * s / 2 > 1000 and y - h * s / 2 < 1700 else gs.SAFE_R
    k = 9.9
    if w > 0:
        k = min(k, 2 * (x - gs.SAFE_L) / w, 2 * (rl - x) / w)
    if h > 0:
        k = min(k, 2 * (y - gs.TOP) / h, 2 * (gs.BOTTOM - y) / h)
    return k


def fit_size(text, size, max_w, max_size=None):
    s = min(size, max_size or size)
    while s > 30 and ink_w(text, s) > max_w:
        s *= 0.95
    return s


# ---- the staircase ----------------------------------------------------------------------------------------------------------
class Unit:
    def __init__(self, text, size, colour, t0, kind="word"):
        self.text, self.size, self.colour, self.t0, self.kind = text, size, colour, t0, kind
        self.img, self.w, self.h = sprite(text, size, gcol(colour))
        self.x = self.y = 0.0

    def resize(self, size):
        self.size = size; self.img, self.w, self.h = sprite(self.text, size, gcol(self.colour))


def nominal_h(size):
    return size * 0.9


def layout(rows, top_min, seed=0, centre_y=0.64 * H):
    """Place rows (lists of Units) as a stepped block inside the safe zone. Returns the block box."""
    if not rows:
        return (CX_SAFE, centre_y, 0, 0)
    lim = MAXW - 2 * STROKE
    for r in rows:                                             # no row wider than the safe zone (and its 2 px of stroke)
        for i in range(8):                                     # (whole-pixel font sizes: a second, slightly smaller try)
            rw = row_w(r)
            if rw <= lim:
                break
            k = lim / rw * (1 if i == 0 else 0.995)
            for u in r:
                u.resize(u.size * k)
    gap = 8

    def heights():
        return [max(nominal_h(u.size) for u in r) for r in rows]
    hs = heights()
    total = sum(hs) + gap * (len(rows) - 1)
    avail = gs.BOTTOM - top_min
    if total > avail:                                          # shrink the whole block to fit under the chin
        k = avail / total
        for r in rows:
            for u in r:
                u.resize(u.size * k)
        hs = heights(); total = sum(hs) + gap * (len(rows) - 1)
    top = max(top_min, centre_y - total / 2)
    top = min(top, gs.BOTTOM - total)
    # stepped lefts: 90 px alternating, then the block centred in the safe zone
    lefts, cur, d = [], 0.0, (-1 if seed % 2 else 1)
    for i, r in enumerate(rows):
        if i:
            cur += 90 * (d if i % 2 else -d)
        lefts.append(cur)
    ws = [row_w(r) for r in rows]
    x0 = min(lefts); x1 = max(l + w for l, w in zip(lefts, ws))
    shift = CX_SAFE - (x0 + x1) / 2
    y = top
    for r, l, w, h in zip(rows, lefts, ws, hs):
        left = min(max(l + shift, gs.SAFE_L + STROKE), gs.SAFE_RB - STROKE - w)   # the stroke stays inside too
        x = left
        for k, u in enumerate(r):
            if k:
                x += unit_gap(r[k - 1], u)
            u.x = x + u.w / 2
            u.y = y + h / 2 + (h - nominal_h(u.size)) * 0.42      # smaller units sit low, on the row's baseline
            x += u.w
        y += h + gap
    xs0 = [u.x - u.w / 2 for r in rows for u in r]; xs1 = [u.x + u.w / 2 for r in rows for u in r]
    return ((min(xs0) + max(xs1)) / 2, top + total / 2, max(xs1) - min(xs0), total)


def unit_gap(a, b):
    cjk = is_cjk(a.text[-1]) and is_cjk(b.text[0])
    return max(a.size, b.size) * (0.04 if cjk else 0.28)


def row_w(r):
    return sum(u.w for u in r) + sum(unit_gap(a, b) for a, b in zip(r, r[1:]))


def word_units(ln, text, size, colour="white", t_shift=-LEAD):
    """Units for a displayed piece of the line, timed on its spoken characters."""
    times = disp_times(ln, text)
    out, i = [], 0
    for tok in tokens(text):
        j = text.find(tok, i)
        if j < 0:
            j = i
        out.append(Unit(tok, size, colour, times[min(j, len(times) - 1)] + t_shift)); i = j + len(tok)
    return out


def rows_from(units, key_unit=None, limit=6):
    """Greedy rows: at most `limit` characters; the key starts its own row unless the row so far is 3 characters or less."""
    rows, cur, n = [], [], 0
    for u in units:
        c = len(u.text.replace(" ", ""))
        if u is key_unit:
            if cur and n > 3:
                rows.append(cur); cur, n = [], 0
            cur.append(u); rows.append(cur); cur, n = [], 0
            continue
        if cur and n + c > limit:
            rows.append(cur); cur, n = [], 0
        cur.append(u); n += c
    if cur:
        rows.append(cur)
    return rows


def plan_rows(ln, units, skip=""):
    """The plan's "rows" as rows of whole units (a unit is never split; what is left over joins the last row). `skip` =
    a part of the line drawn elsewhere (the word behind the speaker): its characters do not count in the rows."""
    rds = [display(r).replace(" ", "") for r in ln["rows"]]
    counts = [len(rd) for rd in rds]
    sk = skip.replace(" ", "")
    p = "".join(rds).find(sk) if sk else -1
    if p >= 0:                                                  # take the skipped characters off the rows they sit in
        acc = 0
        for i, c in enumerate(list(counts)):
            counts[i] -= max(0, min(acc + c, p + len(sk)) - max(acc, p)); acc += c
    rows, k = [], 0
    for c in counts:
        row, n = [], 0
        while k < len(units) and n < c:
            row.append(units[k]); n += len(units[k].text.replace(" ", "")); k += 1
        rows.append(row)
    if k < len(units):
        rows[-1] += units[k:]
    return [r for r in rows if r]


def pieces(text, subs):
    """Split text into [(piece, tag)] around the given exact substrings (tag = the field name, or None)."""
    marks = []
    for tag, s in subs:
        if s:
            p = text.find(s)
            if p >= 0:
                marks.append((p, p + len(s), tag))
    marks.sort()
    out, i = [], 0
    for a, b, tag in marks:
        if a < i:
            continue
        if a > i:
            out.append((text[i:a], None))
        out.append((text[a:b], tag)); i = b
    if i < len(text):
        out.append((text[i:], None))
    return [(p.strip(), t) for p, t in out if p.strip()]


# ---- one line ---------------------------------------------------------------------------------------------------------------
class Line:
    def __init__(self, ln, R):
        self.ln, self.id, self.R = ln, ln.get("id"), R
        self.mv = ln.get("move") or ""
        self.track = False; self.track_sound = False; self.track_u = None     # track_u: the word the tracking close spreads
        self.sfx, self.ev, self.hits = [], [], []              # hits: (time, move) each move lands, for the 2 s rule
        text = display(ln["text"]).strip()
        self.text = text
        top_min = R.chin_eff + 40
        dkey = display(ln.get("key") or "").strip() or None
        if self.mv == "title":
            self.build_title(ln, text, dkey, top_min)
        elif self.mv == "question":
            self.build_question(ln, text, top_min)
        elif self.mv == "slam":
            self.build_slam(ln, text, top_min)
        elif self.mv in ("number", "writeon"):
            self.build_number(ln, text, top_min)
        elif self.mv == "spin":
            self.build_spin(ln, text, top_min)
        elif self.mv == "behind":
            self.build_behind(ln, text, top_min)
        else:
            self.build_plain(ln, text, dkey, top_min)
        us = [u for r in self.rows for u in r]
        self.t_in = min([u.t0 for u in us] + [getattr(self, "t_move", 1e9)])
        self.t_out = ln["end"] + 0.35

    # plain staircase (M2 + M3)
    def build_plain(self, ln, text, dkey, top_min):
        units = []
        key_u = None
        for piece, tag in pieces(text, [("key", dkey)]):
            if units and not any(c.isalnum() or is_cjk(c) for c in piece):   # "?" after the key stays on its row
                units[-1].text += piece; units[-1].resize(units[-1].size); continue
            if tag == "key":
                key_u = Unit(piece, SIZES["L"], "gold", disp_times(ln, piece)[0] - LEAD, "key"); units.append(key_u)
                self.R.kicks.append((key_u.t0 + 3 * F1, 0.025))
            else:
                units += word_units(ln, piece, SIZES["M"])
        if ln.get("rows"):
            rows = plan_rows(ln, units)
        else:
            rows = rows_from(units, key_u)
        for r in rows:                                          # a key row: the other words M; long rows stay M
            for u in r:
                if u is not key_u and u.size != SIZES["M"]:
                    u.resize(SIZES["M"])
        if len(rows) >= 3 and key_u not in rows[0] and len("".join(u.text for u in rows[0])) <= 4:
            for u in rows[0]:
                u.resize(SIZES["S"])
        self.rows = rows
        self.box = layout(rows, top_min, int(self.id or 0))

    def build_behind(self, ln, text, top_min):
        """M15 Word Behind 字在人后: the line's big word sits behind the speaker's head (cut out with the person matte),
        the rest of the line builds as a staircase under the chin."""
        dw = display(ln["word"]).strip()
        units = []
        for piece, tag in pieces(text, [("word", dw)]):
            if tag != "word":
                units += word_units(ln, piece, SIZES["M"])
        self.rows = (plan_rows(ln, units, dw) if ln.get("rows") else rows_from(units)) if units else []
        self.box = layout(self.rows, top_min, int(self.id or 0)) if self.rows else (CX_SAFE, top_min, 0, 0)
        colour = "white" if ln.get("behind_colour") == "white" else "gold"
        self.bcol = colour
        self.tW = sub_time(ln, ln["word"]) - 6 * F1                         # lands (f6) as the word is spoken
        chars = [c for c in dw if c.strip()]
        head = self.R.head_span(self.tW + 0.3) if len(chars) == 2 else None
        head_top = self.R.head_top
        sb = BEHIND_MAX
        for rl in (gs.SAFE_R, gs.SAFE_RB):                     # right margin 994, or 950 when the word reaches the button band
            if head:
                # two characters, one each side of the head (measured on the matte), each inside the side margins at its
                # largest scale. Owner 2026-11-02 "more bigger": they start at BEHIND_W or more and sit high, so the head
                # covers only their lower inner part (the head measured in the rows the word covers); they shrink only
                # while either would show less than BEHIND_SHOW of itself
                room = max(120.0, min(head[0] - gs.SAFE_L, rl - head[1]))
                small = min(460.0, room / (0.5 - BEHIND_IN + sb / 2))
                cw = min(460.0, max(BEHIND_W, small))
                while True:
                    s_ = cw / 0.95
                    imgs = [sprite(c, s_, gcol(colour)) for c in chars]
                    w0, w1 = imgs[0][1], imgs[1][1]
                    self.bh = max(imgs[0][2], imgs[1][2])
                    self.by = max(gs.TOP + 1.05 * self.bh / 2, head_top - 0.1 * self.bh)
                    hl, hr = self.R.head_span(self.tW + 0.3, (self.by - self.bh / 2, self.by + self.bh / 2)) or head
                    xl = max(gs.SAFE_L + sb * w0 / 2, hl + BEHIND_IN * w0 - w0 / 2)
                    xr = min(rl - sb * w1 / 2, hr - BEHIND_IN * w1 + w1 / 2)
                    show = min((hl - (xl - w0 / 2)) / w0, (xr + w1 / 2 - hr) / w1)
                    if show >= BEHIND_SHOW or cw <= small:
                        break
                    cw = max(small, cw * 0.93)
                self.parts = [(imgs[0][0], xl, s_), (imgs[1][0], xr, s_)]
            else:
                tr = 0.12
                sW = 480
                while sW > 30 and ink_w(dw, sW, tr) * sb > rl - gs.SAFE_L:
                    sW *= 0.95
                img, bw, self.bh = sprite(dw, sW, gcol(colour), tr)
                self.parts = [(img, min(max(self.R.fx, gs.SAFE_L + sb * bw / 2), rl - sb * bw / 2), sW)]
                self.by = max(gs.TOP + 1.05 * self.bh / 2, head_top + self.bh * 0.18)     # the head covers the lower part of the word
            if self.by + 120 + sb * self.bh / 2 < 1000 or self.by - sb * self.bh / 2 > 1700:   # (rising from 120 px lower)
                break
        self.t_move = self.tW
        self.sfx.append((self.tW + 6 * F1, "whoosh_zoom", -3, f"line {self.id}: word behind the speaker lands ({dw})"))
        self.hits.append((self.tW + 6 * F1, "behind"))
        self.ev += [(self.tW + 3 * F1, "behind (rising)"), (self.tW + 10 * F1, "behind (landed)")]
        self.R.kicks.append((self.tW + 6 * F1, 0.03))

    def draw_behind(self, layer, t):
        if self.mv != "behind":
            return
        f = (t - self.tW) * FPS
        if f < 0:
            return
        bs, ba = self.block_tf(t)
        p = gs.cc.ease_expo(min(1.0, f / 8))
        hold = max(0.0, t - self.tW - 8 * F1)
        s = (1.12 - 0.12 * p) * (1 + 0.04 * min(1.0, hold / 3.0)) * (0.9 + 0.1 * bs)
        y = self.by + 120 * (1 - p)
        for img, x, size in self.parts:
            if self.bcol == "gold":
                glow_pulse(layer, img, size, x, y, f - 2, t, s, p * ba)
            put(tgt(layer, self.bcol), img, x, y, s, alpha=p * ba, blur=12 * (1 - p))

    def build_title(self, ln, text, dkey, top_min):
        units = []
        for piece, tag in pieces(text, [("key", dkey)]):
            units.append(Unit(piece, SIZES["L"], "gold" if tag else "white", 0, "title"))
        tw = row_w(units)
        lim = min(MAXW, 0.84 * W)
        if tw > lim:
            for u in units:
                u.resize(u.size * lim / tw)
        self.rows = [units]
        h = max(nominal_h(u.size) for u in units)
        cy = max(0.52 * H, top_min + h / 2)
        self.box = layout(self.rows, top_min, 0, centre_y=cy)
        t_sp = disp_times(ln, text)[0]
        self.t_move = max(0.0, t_sp - 12 * F1)
        for u in units:
            u.t0 = self.t_move
        self.sfx.append((self.t_move + 12 * F1, "impact", -6, f"line {self.id}: title lands"))
        self.hits.append((self.t_move + 12 * F1, "title"))
        self.ev += [(self.t_move + 6 * F1, "title (rising)"), (self.t_move + 20 * F1, "title (landed)")]

    def build_question(self, ln, text, top_min):
        s = fit_size(text, SIZES["M"], MAXW - 40)
        t0 = disp_times(ln, text)[0] - LEAD
        u = Unit(text, s, "white", t0, "question")
        self.rows = [[u]]
        self.box = layout(self.rows, top_min, 0, centre_y=top_min + nominal_h(s) / 2)
        self.ink = sprite(text, s, "ink")[0]
        self.t_move = t0
        self.sfx.append((t0 + 2 * F1, "pop", -4, f"line {self.id}: marker swipe"))
        self.hits.append((t0 + 2 * F1, "question"))
        self.ev += [(t0 + 5 * F1, "question (swipe)"), (t0 + 14 * F1, "question (held)")]

    def build_slam(self, ln, text, top_min):
        da, db = display(ln["a"]).strip(), display(ln["b"]).strip()
        rows, a_u, b_u = [], None, None
        for piece, tag in pieces(text, [("a", da), ("b", db)]):
            if tag == "a":
                a_u = Unit(piece, SIZES["M"], "white", 0, "slamA"); rows.append([a_u])
            elif tag == "b":
                b_u = Unit(piece, SIZES["L"], "gold", 0, "slamB"); rows.append([b_u])
            else:
                rows.append(word_units(ln, piece, SIZES["S"] if not rows else SIZES["M"]))
        self.rows = rows
        self.box = layout(rows, top_min, int(self.id or 0))
        self.lead = rows[:rows.index([a_u])] if [a_u] in rows else []
        ct = gs.char_times(ln)
        self.tA = sub_time(ln, ln["a"], ct) - 2 * F1
        self.tB = max(self.tA + 12 * F1, sub_time(ln, ln["b"], ct) - 2 * F1)
        self.tS = max(self.tA + 24 * F1, self.tB + 10 * F1)
        for r in rows:
            for u in r:
                if u not in [x for lr in self.lead for x in lr]:
                    u.t0 = max(u.t0, self.tS + 2 * F1) if u.kind == "word" else self.tS + 2 * F1
        avail = gs.BOTTOM - top_min - 20
        sA = fit_size(da, SIZES["M"] * 4, MAXW); sB = fit_size(db, SIZES["L"] * 4, MAXW)
        hA, hB = nominal_h(sA), nominal_h(sB)
        if hA * 0.644 + hB > avail:
            k = avail / (hA * 0.644 + hB); sA *= k; sB *= k; hA, hB = nominal_h(sA), nominal_h(sB)
        self.gA, self.gB = sprite(da, sA, "white"), sprite(db, sB, gcol("gold"))
        self.gA_ghost = (tint(self.gA[0], (255, 243, 214), 0.6), tint(self.gA[0], GOLD, 0.5))
        self.top, self.hA, self.hB, self.sA, self.sB = top_min, hA, hB, sA, sB
        self.a_u, self.b_u = a_u, b_u
        self.t_move = self.tA
        self.sfx.append((self.tA + 2 * F1, "impact", 0, f"line {self.id}: slam A lands ({da})"))
        self.ev += [(self.tA + 1 * F1, "slam A (moving)"), (self.tA + 6 * F1, "slam A (held)"), (self.tB + 4 * F1, "slam B (landed)"),
                    (self.tS + 6 * F1, "slam (settled)")]
        self.hits.append((self.tB + 4 * F1, "slam"))                         # the hit: B lands
        self.R.kicks.append((self.tA, 0.06))
        if ln.get("flash"):
            self.flash_text = db

    def build_number(self, ln, text, top_min):
        dn = display(ln["number"]).strip(); du = display(ln.get("unit") or "").strip() or None
        rows, num_row = [], None
        for piece, tag in pieces(text, [("number", dn), ("unit", du)]):
            if tag == "number":
                num_row = [Unit(piece, SIZES["N"], "gold", 0, "number")]; rows.append(num_row)
            elif tag == "unit" and num_row is not None:
                num_row.append(Unit(piece, SIZES["M"], "white", 0, "unit"))
            else:
                rows += rows_from(word_units(ln, piece, SIZES["M"]))
        self.rows = rows
        self.box = layout(rows, top_min, int(self.id or 0))
        nu = num_row[0]
        ct = gs.char_times(ln)
        self.tN = sub_time(ln, ln["number"], ct) - LEAD
        self.R.kicks.append((self.tN + 3 * F1, 0.03))
        nu.t0 = self.tN
        self.num = nu
        self.unit = num_row[1] if len(num_row) > 1 else None
        if self.mv == "number":
            self.digits = [(c, sprite(c, nu.size, gcol("gold"))) for c in nu.text]
            if self.unit:
                self.tU = max(self.tN + 6 * F1, sub_time(ln, ln["unit"], ct) - 2 * F1)
                self.unit.t0 = self.tU + 15 * F1
                room = gs.SAFE_RB - (nu.x + nu.w / 2) - 24           # the giant unit fits beside the number, never over it
                su = fit_size(du, SIZES["M"] * 4, max(room, SIZES["M"] * 1.2))
                self.gU = sprite(du, su, "white")
                self.sfx.append((self.tU + 15 * F1, "pop", -3, f"line {self.id}: unit snaps beside the number"))
                self.ev += [(self.tU + 6 * F1, "number unit (giant)")]
            self.ev += [(self.tN + 2 * F1, "number (growing)"), (self.tN + 8 * F1, "number (landed)")]
            self.hits.append((self.tN + 8 * F1, "number"))
        else:
            if self.unit:
                self.unit.t0 = max(self.tN + 10 * F1, sub_time(ln, ln["unit"], ct) - LEAD)
            self.sfx.append((self.tN + 10 * F1, "swish_soft", -2, f"line {self.id}: number written on"))
            self.ev += [(self.tN + 5 * F1, "writeon (drawing)"), (self.tN + 12 * F1, "writeon (done)")]
            self.hits.append((self.tN + 10 * F1, "writeon"))
        self.t_move = self.tN

    def build_spin(self, ln, text, top_min):
        dw = display(ln["word"]).strip()
        pre, post = text.split(dw, 1) if dw in text else (text, "")
        pre_units = word_units(ln, pre, SIZES["M"]) if pre.strip() else []
        post_units = word_units(ln, post, SIZES["M"]) if post.strip() else []
        rows = rows_from(pre_units) if pre_units else []
        self.rows = rows
        self.box = layout(rows, top_min, int(self.id or 0)) if rows else (CX_SAFE, top_min, 0, 0)
        g_top = (self.box[1] + self.box[3] / 2 + 16) if rows else top_min
        post_h = nominal_h(SIZES["M"]) + 12 if post_units else 0
        sW = fit_size(dw, SIZES["L"] * 4, 2 * (CX_SAFE - 0.03 * W - gs.SAFE_L))   # x 86..950, also after its drift left
        hW = nominal_h(sW)
        if g_top + hW + post_h > gs.BOTTOM:
            sW *= max(0.3, (gs.BOTTOM - g_top - post_h) / hW); hW = nominal_h(sW)
        spin_col = "gold" if display(ln.get("key") or "").strip() == dw else "white"     # gold when it is the line's key
        ph = max([u.h for u in post_units], default=0)

        def low(s):                                             # the lowest ink: the spin word, or the row under it
            return max(g_top + (nominal_h(s) + sprite(dw, s, spin_col)[2]) / 2,
                       g_top + nominal_h(s) + 12 + (nominal_h(SIZES["M"]) + ph) / 2 if post_units else 0)
        while sW > 30 and low(sW) > gs.BOTTOM:                  # the ink, not only the nominal height, above y 1620
            sW *= 0.97
        hW = nominal_h(sW)
        self.gW, self.gW_grey = sprite(dw, sW, gcol(spin_col)), sprite(dw, sW, "grey")
        self.spin_col = spin_col
        self.wy = g_top + hW / 2
        # it turns in from the right: from at most 0.4 W, and only as far as keeps the turning word inside the margin
        rl = gs.SAFE_RB if self.wy + self.gW[2] / 2 > 1000 and self.wy - self.gW[2] / 2 < 1700 else gs.SAFE_R
        self.slide = max(0.0, min(0.4 * W, rl - CX_SAFE - self.gW[1] / 2))
        self.tW = sub_time(ln, ln["word"]) - 2 * F1
        self.t_move = self.tW
        if post_units:                                          # the words after the spin word: one row under it
            x = CX_SAFE - row_w(post_units) / 2
            for k, u in enumerate(post_units):
                if k:
                    x += unit_gap(post_units[k - 1], u)
                u.x, u.y = x + u.w / 2, g_top + hW + 12 + nominal_h(u.size) / 2
                u.t0 = max(u.t0, self.tW + 13 * F1)
                x += u.w
            self.rows = rows + [post_units]
        self.sfx.append((self.tW + 13 * F1, "whoosh_fast", -2, f"line {self.id}: spin lands ({dw})"))
        self.hits.append((self.tW + 13 * F1, "spin"))
        self.ev += [(self.tW + 5 * F1, "spin (turning)"), (self.tW + 16 * F1, "spin (landed)")]

    # ---- drawing ---------------------------------------------------------------------------------------------------------
    def block_tf(self, t):
        """Exit transform for the whole block: (scale, alpha)."""
        if t <= self.t_out:
            return 1.0, 1.0
        f = (t - self.t_out) * FPS
        if self.ln.get("exit") == "pulse":
            s = keys(f, [0, 2, 4], [1.0, self.swell(), 0.92]); a = 1.0 if f < 2 else max(0.0, 1 - (f - 2) / 2)
            return s, a
        return 1 - 0.15 * min(1, f / 2), max(0.0, 1 - f / 2)

    def swell(self):
        """The pulse's swell: 1.10x, or less when the swollen block would leave x 86..994 (950 in the button band
        y 1000-1700) or y 200..1620. Each ink box grows around the point the drawing scales it from."""
        if not hasattr(self, "_swell"):
            bc = (self.box[0], self.box[1])
            boxes = [((u.x - u.w / 2, u.y - u.h / 2, u.x + u.w / 2, u.y + u.h / 2), bc) for r in self.rows for u in r]
            if self.mv == "spin":                               # the spin word scales around itself, at its drifted place
                x = CX_SAFE - 0.03 * W; w, h = self.gW[1], self.gW[2]
                boxes.append(((x - w / 2, self.wy - h / 2, x + w / 2, self.wy + h / 2), (x, self.wy)))
            k = 1.10
            for (x0, y0, x1, y1), (cx, cy) in boxes:
                band = cy + (y1 - cy) * 1.10 > 1000 and cy + (y0 - cy) * 1.10 < 1700 or (y1 > 1000 and y0 < 1700)
                rl = gs.SAFE_RB if band else gs.SAFE_R
                for edge, c, lim in ((x0, cx, gs.SAFE_L), (x1, cx, rl), (y0, cy, gs.TOP), (y1, cy, gs.BOTTOM)):
                    if abs(edge - c) > 1e-6 and (lim - c) / (edge - c) > 0:
                        k = min(k, (lim - c) / (edge - c))
            self._swell = max(1.0, k)
        return self._swell

    def draw_unit(self, fr, u, t, bs, ba, bc):
        f = (t - u.t0) * FPS
        if f < 0:
            return
        x, y = bc[0] + (u.x - bc[0]) * bs, bc[1] + (u.y - bc[1]) * bs
        if self.track and u is self.track_u:
            self.draw_tracked(fr, u, f, x, y, bs, ba); return
        if u.kind == "key" or (u.kind == "number" and self.mv == "number" and False):
            s = keys(f, [0, 6], [1.08, 1.0]); bl = keys(f, [0, 3, 6], [24, 8, 0]); a = keys(f, [0, 2], [0.7, 1.0])
            s = min(s, max(1.0, fit_k(x, y, u.w * bs, u.h * bs, s)))     # the landing overshoot stays inside
            glow_pulse(fr, u.img, u.size, x, y, f, t, bs, ba)
            put(tgt(fr, u.colour), u.img, x, y, s * bs, alpha=a * ba, blur=bl)
            return
        if u.kind in ("title", "slamA", "slamB", "unit_rest"):
            if u.colour == "gold":
                glow_pulse(fr, u.img, u.size, x, y, 30 + f, t, bs, ba)
            put(tgt(fr, u.colour), u.img, x, y, bs, alpha=ba); return
        s = keys(f, [0, 3, 5], [1.12, 0.98, 1.0]); a = min(1.0, f / 2); bl = keys(f, [0, 3], [4, 0])
        s = min(s, max(1.0, fit_k(x, y, u.w * bs, u.h * bs, s)))         # the landing overshoot stays inside
        put(tgt(fr, u.colour), u.img, x, y, s * bs, alpha=a * ba, blur=bl)

    def draw_tracked(self, fr, u, f, x, y, bs, ba):
        """M8: the first row's first word closes in from +120 % letter spacing over 6 frames (less spacing when the
        spread word would leave the side margins or reach into the button area)."""
        if not hasattr(u, "chars"):
            f_ = gs.font(u.size); adv = [f_.getlength(c) for c in u.text]; tot = sum(adv); cx = -tot / 2; u.chars = []
            for c, a_ in zip(u.text, adv):
                if c.strip():
                    sp = sprite(c, u.size, gcol(u.colour))
                    u.chars.append((sp[0], cx + a_ / 2, sp[1]))
                cx += a_
        p = ease_out(min(1, f / 6)); k = 1 + 1.2 * (1 - p)
        rl = gs.SAFE_RB if y + u.h * bs / 2 > 1000 and y - u.h * bs / 2 < 1700 else gs.SAFE_R
        for _, dx, w in u.chars:                                # the widest spacing that keeps every letter inside
            lim = gs.SAFE_L if dx < 0 else rl
            if abs(dx) > 1e-6 and (lim - x - w * bs / 2 * (1 if dx > 0 else -1)) / (dx * bs) > 0:
                k = max(1.0, min(k, (lim - x - w * bs / 2 * (1 if dx > 0 else -1)) / (dx * bs)))
        for img, dx, _ in u.chars:
            put(tgt(fr, u.colour), img, x + dx * k * bs, y, bs, alpha=min(1.0, 0.3 + f / 3) * ba, blur=6 * (1 - p))

    def draw(self, fr, t):
        bs, ba = self.block_tf(t)
        if ba <= 0.01:
            return
        bc = (self.box[0], self.box[1])
        mv = self.mv
        if mv == "title":
            return self.draw_title(fr, t, bs, ba)
        if mv == "question":
            return self.draw_question(fr, t, bs, ba)
        if mv == "slam":
            return self.draw_slam(fr, t, bs, ba, bc)
        if mv in ("number", "writeon"):
            for r in self.rows:
                for u in r:
                    if u is self.num:
                        (self.draw_number if mv == "number" else self.draw_writeon)(fr, t, bs, ba, bc)
                    elif u is self.unit and mv == "number":
                        self.draw_unit_snap(fr, t, bs, ba, bc)
                    else:
                        self.draw_unit(fr, u, t, bs, ba, bc)
            return
        if mv == "spin":
            for r in self.rows:
                for u in r:
                    self.draw_unit(fr, u, t, bs, ba, bc)
            return self.draw_spin(fr, t, bs, ba)
        for r in self.rows:
            for u in r:
                self.draw_unit(fr, u, t, bs, ba, bc)

    def draw_title(self, fr, t, bs, ba):
        f = (t - self.t_move) * FPS
        if f < 0:
            return
        p = min(1.0, f / 12); e = gs.cc.ease_expo(p)
        dy = (0.70 * H - self.box[1]) * (1 - e); s = (0.8 + 0.2 * e) * bs
        for u in self.rows[0]:
            x = self.box[0] + (u.x - self.box[0]) * s
            if u.colour == "gold":
                glow_pulse(fr, u.img, u.size, x, u.y + dy, f - 6, t, s, e * ba)
            put(tgt(fr, u.colour), u.img, x, u.y + dy, s, alpha=e * ba, blur=10 * (1 - p))
        if f >= 12:
            q = ease_out(min(1, (f - 12) / 6)); bw = self.box[2] * 0.5 * q
            if bw > 2:
                bar = Image.new("RGBA", (int(bw), 6), GOLD + (255,))
                put(fr, bar, self.box[0], self.box[1] + self.box[3] / 2 + 22, bs, alpha=ba)

    def draw_question(self, fr, t, bs, ba):
        u = self.rows[0][0]; f = (t - u.t0) * FPS
        if f < 0:
            return
        x0 = u.x - u.w / 2 - 18; x1 = u.x + u.w / 2 + 18; bh = u.h * 1.1 + 16
        if 2 <= f:
            r_ = x0 + (x1 - x0) * ease_out(min(1, (f - 2) / 6))
            l_ = x0 + (x1 - x0) * ease_in(min(1, max(0, (f - 20) / 4)))
            if r_ - l_ > 2 and f < 24:
                bar = Image.new("RGBA", (int(r_ - l_), int(bh)), (0, 0, 0, 0))
                ImageDraw.Draw(bar).rounded_rectangle((0, 0, bar.width - 1, bar.height - 1), 8, fill=GOLD + (217,))
                put(fr, bar, (l_ + r_) / 2, u.y, 1.0, alpha=ba)
        s = keys(f, [0, 3, 5], [1.12, 0.98, 1.0])
        s = min(s, max(1.0, fit_k(u.x, u.y, u.w, u.h, s))) * bs                 # the landing overshoot stays inside
        put(fr, u.img, u.x, u.y, s, alpha=min(1.0, f / 2) * ba, blur=keys(f, [0, 3], [4, 0]))
        if 2 <= f < 24:                                         # the words go near-black where the bar covers them
            r_ = x0 + (x1 - x0) * ease_out(min(1, (f - 2) / 6))
            l_ = x0 + (x1 - x0) * ease_in(min(1, max(0, (f - 20) / 4)))
            ink = self.ink; ox = u.x - ink.width / 2
            c0, c1 = int(max(0, l_ - ox)), int(min(ink.width, r_ - ox))
            if c1 > c0:
                piece = ink.crop((c0, 0, c1, ink.height))
                put(fr, piece, ox + (c0 + c1) / 2, u.y, 1.0, alpha=ba)

    def draw_slam(self, fr, t, bs, ba, bc):
        lead_units = [u for r in self.lead for u in r]
        if t >= self.tS + 2 * F1:                               # the settled stack, every word
            for r in self.rows:
                for u in r:
                    if u in lead_units or u.kind == "word":
                        self.draw_unit(fr, u, t, bs, ba, bc)
                    else:
                        put(tgt(fr, u.colour), u.img, bc[0] + (u.x - bc[0]) * bs, bc[1] + (u.y - bc[1]) * bs, bs, alpha=ba)
            return
        if t < self.tA:
            for u in lead_units:
                self.draw_unit(fr, u, t, 1.0, 1.0, bc)
            return
        fA = (t - self.tA) * FPS
        (imA, wA, hA), (imB, wB, hB) = self.gA, self.gB
        top = self.top
        if t >= self.tS:                                        # snap: both giants fly to their resting places (ease-in, 2 frames)
            p = ease_in((t - self.tS) * FPS / 2)
            for g, u, s0, y0 in ((self.gA, self.a_u, 0.644, top + self.hA * 0.322), (self.gB, self.b_u, 0.95, top + self.hA * 0.644 + 20 + self.hB / 2)):
                s1 = u.size / (self.sA if u is self.a_u else self.sB)
                put(tgt(fr, u.colour), g[0], CX_SAFE + (u.x - CX_SAFE) * p, y0 + (u.y - y0) * p, s0 + (s1 - s0) * p)
            return
        # A: rises into place under the chin, Light Split ghosts close in, a small jitter, then a slow push smaller
        sA = keys(fA, [3, 11], [1.0, 0.92])
        yA = top + self.hA * sA / 2
        yA += max(0.0, min(0.30 * H, gs.BOTTOM - hA * sA / 2 - yA)) * (1 - ease_out(min(1, fA / 2.5)))   # rises from inside (ink above 1620)
        jit = max(0.0, min(6.0, (MAXW - wA * sA) / 2))          # the jitter stays inside x 86..950
        xA = CX_SAFE + (jit if int(fA) == 0 else -jit if int(fA) == 1 else 0)
        if t >= self.tB:
            fB = (t - self.tB) * FPS
            sA = 0.92 + (0.644 - 0.92) * ease_out(min(1, fB / 3)); yA = top + self.hA * sA / 2
            yB = top + self.hA * 0.644 + 20 + self.hB / 2
            y0 = max(yB, min(H + self.hB / 2, gs.BOTTOM - hB / 2))      # rises from inside the safe area (ink above 1620)
            yB += (y0 - yB) * (1 - ease_out(min(1, fB / 2.5)))
            put(fr, imA, xA, yA, sA)
            glow_pulse(fr, imB, self.sB, CX_SAFE, yB, fB - 1, t, keys(fB, [3, 11], [1.0, 0.95]))
            put(tgt(fr, "gold"), imB, CX_SAFE, yB, keys(fB, [3, 11], [1.0, 0.95]))
            return
        d = 14 * (1 - ease_out(min(1, fA / 4)))
        if d > 0.5:
            put(fr, self.gA_ghost[0], xA - d, yA, sA, alpha=1.0)
            put(fr, self.gA_ghost[1], xA + d, yA, sA, alpha=1.0)
        put(fr, imA, xA, yA, sA)

    def draw_number(self, fr, t, bs, ba, bc):
        u = self.num; f = (t - u.t0) * FPS
        if f < 0:
            return
        p = ease_out(min(1, f / 4)); s = (0.6 + 0.4 * p) * bs; k = 1 + 0.4 * (1 - p)
        f_ = gs.font(u.size); adv = [f_.getlength(c) for c in u.text]; tot = sum(adv)
        x = bc[0] + (u.x - bc[0]) * bs - tot * s / 2; y = bc[1] + (u.y - bc[1]) * bs
        cxs = []; cx = 0.0
        for a_ in adv:
            cxs.append(cx + a_ / 2); cx += a_
        mid = tot / 2
        glow_pulse(fr, u.img, u.size, x + tot * s / 2, y, f - 2, t, s, ba)        # the light sits behind the digits
        for (c, sp), cxp in zip(self.digits, cxs):
            if c.strip():
                put(tgt(fr, u.colour), sp[0], x + (mid + (cxp - mid) * k) * s, y, s, alpha=min(1.0, f / 2) * ba)

    def draw_unit_snap(self, fr, t, bs, ba, bc):
        u = self.unit
        if u is None:
            return
        f = (t - self.tU) * FPS
        if f < 0:
            return
        img = self.gU[0]
        gw = self.gU[1]
        gx = min(gs.SAFE_RB - gw / 2, self.num.x + self.num.w / 2 + 24 + gw / 2)
        if f < 14:                                              # M7: the unit giant beside the number (not over it), then snaps
            put(fr, img, gx, self.num.y, keys(f, [1, 13], [1.0, 0.92]), alpha=0.6 * ba, blur=6)
            return
        if f < 15:
            put(fr, img, (gx + u.x) / 2, (self.num.y + u.y) / 2, 0.3, alpha=ba); return
        put(tgt(fr, u.colour), u.img, bc[0] + (u.x - bc[0]) * bs, bc[1] + (u.y - bc[1]) * bs, bs, alpha=ba)

    def draw_writeon(self, fr, t, bs, ba, bc):
        u = self.num; f = (t - u.t0) * FPS
        if f < 0:
            return
        img = u.img; x = bc[0] + (u.x - bc[0]) * bs; y = bc[1] + (u.y - bc[1]) * bs
        p = min(1.0, f / 10)
        k = keys(f, [10, 11, 12], [1.0, 1.02, 1.0]) if f >= 10 else 1.0
        s = bs * min(k, max(1.0, fit_k(x, y, u.w * bs, u.h * bs, k)))   # the landing pulse stays inside
        ink_l = img.width / 2 - u.w / 2
        edge = ink_l + u.w * p
        if p < 1:
            piece = img.crop((0, 0, int(max(1, edge)), img.height))
            put(tgt(fr, u.colour), piece, x - img.width / 2 * s + piece.width / 2 * s, y, s, alpha=ba)
        else:
            put(tgt(fr, u.colour), img, x, y, s, alpha=ba)
        if f < 10:                                              # the pen trail just ahead of the reveal edge
            a = 1.0 if f < 8 else max(0.0, 1 - (f - 8) / 2)
            trail = Image.new("RGBA", (120, 12), (0, 0, 0, 0))
            ImageDraw.Draw(trail).rounded_rectangle((0, 0, 119, 11), 6, fill=GOLD + (255,))
            put(fr, trail, x - img.width / 2 + edge + 40, y + u.h / 2 + 10, 1.0, alpha=a * ba)

    def draw_spin(self, fr, t, bs, ba):
        f = (t - self.tW) * FPS
        if f < 0:
            return
        p = ease_io(min(1, f / 13)); th = math.radians(180 * (1 - p))
        sx = max(0.04, abs(math.cos(th)))
        x = CX_SAFE + self.slide * (1 - p)
        if f > 13:
            x -= 0.03 * W * min(1.0, (t - self.tW - 13 * F1) / max(0.3, self.t_out - self.tW - 13 * F1))
        for img, a, col in ((self.gW_grey[0], 1 - p, "grey"), (self.gW[0], p, self.spin_col)):
            if a < 0.02:
                continue
            im = img.resize((max(1, int(img.width * sx)), img.height), Image.BILINEAR)
            if th > math.pi / 2:
                im = ImageOps.mirror(im)
            put(tgt(fr, col), im, x, self.wy, bs, alpha=(0.4 + 0.6 * p) * a * ba)


# ---- picture: camera, vignette, light leak -------------------------------------------------------------------------------
class Render:
    def __init__(self, plan, joins, dur):
        cam = plan.get("camera") or {}
        self.cam_on = cam.get("on", True)
        fx, fy = (cam.get("face") or [0.5, 0.3])
        self.fx, self.fy = fx * W, fy * H
        self.alternate = cam.get("alternate", True) and bool(joins)
        self.kicks = []
        self.dur = dur
        self.close = bool(plan.get("close"))
        k = float(cam.get("strength", 1.0))                   # 1.0 = the owner's "more movement" (2026-11-01); 0.4 = the v1 slight move
        self.k = max(0.0, min(1.5, k))
        self.base = 1 + 0.07 * min(1.0, self.k)               # headroom so the drift and sway never show an edge
        zmax = self.base * (1.15 if self.alternate else 1.0) * (1 + 0.04 * self.k) * (1 + 0.015 * self.k) * 1.06 * (1.07 if self.close else 1.0)
        chin = cam.get("chin")
        self.chin_given = chin is not None
        chin = float(chin) if chin is not None else 0.45 * H
        self.chin_eff = self.fy + (chin - self.fy) * (zmax if self.cam_on else 1.0)
        # framing switches at pause cuts: wide / 1.15x tight, each framing at least 1.2 s
        self.frames = [(0.0, 1.0)]
        last = 0.0
        for j in joins:
            if self.alternate and j - last >= 1.2 and dur - j >= 1.2:
                self.frames.append((j, 1.15 if self.frames[-1][1] == 1.0 else 1.0)); last = j
        self.segs = [s for s, _ in self.frames] + [dur]
        self.active = [self.frames[0]]
        self.pending = list(self.frames[1:])
        self.vig_from = None
        self.leaks = []
        self.matte_path = None
        ht = cam.get("head_top")
        self.head_top = float(ht) if ht is not None else self.fy - 0.17 * H

    def head_span(self, t, band=None):
        """Left / right x of the speaker's head (on the output frame) at time t, from the person matte, in the band where a
        behind word sits (or the output rows `band` = (y0, y1)); None without a matte or with no head in the band."""
        if not self.matte_path:
            return None
        key = round(t, 3)
        if getattr(self, "_mkey", None) != key:
            raw = subprocess.run([gs.cc.FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", self.matte_path,
                                  "-frames:v", "1", "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
            self._mkey, self._m = key, (np.frombuffer(raw[:W * H], np.uint8).reshape(H, W) if len(raw) >= W * H else None)
        m = self._m
        if m is None:
            return None
        z = self.base * 1.12 if self.cam_on else 1.0               # the camera's usual zoom around the frame centre
        if band:
            y0, y1 = (int(H / 2 + (y - H / 2) / z) for y in band)
        else:
            y0, y1 = int(self.head_top + 40), int(self.head_top + 360)
        cols = np.nonzero((m[max(0, y0):min(H, y1)] > 128).any(0))[0]
        if not len(cols):
            return None
        return float(W / 2 + (int(cols.min()) - W / 2) * z), float(W / 2 + (int(cols.max()) - W / 2) * z)

    def see(self, t, cut):
        """Called once per frame before transform: a planned framing switch happens on the frame where the picture really
        cuts (searched from 1 frame before to 3 frames after the cut map's time), so the new framing never shows the old shot."""
        while self.pending and t > self.pending[0][0] + 3.5 * F1:  # no visible cut found: switch at the latest
            s, z = self.pending.pop(0); self.active.append((t, z))
        if self.pending and cut and t >= self.pending[0][0] - 1.5 * F1:
            s, z = self.pending.pop(0); self.active.append((t, z))

    def framing(self, t):
        z, s0 = self.active[-1][1], self.active[-1][0]
        nxt = next((s for s in self.segs if s > t + 3.5 * F1), self.dur)
        return z, (t - s0) / max(1.2, nxt - s0)

    def transform(self, img, t):
        """The camera move (owner 2026-11-01: more movement): base 107 %, a breathing zoom of 1.5 %, a drift of +-18 / +-14 px,
        a sway of +-0.6 deg, a 4 % push within each framing, a 6 % kick on the slam, a 2.5 % punch on each gold word and the
        closing push. camera.strength scales it (0.4 = the earlier slight move)."""
        if not self.cam_on:
            return img
        k = self.k
        zf, prog = self.framing(t)
        z = self.base * zf * (1 + 0.04 * k * ease_io(min(1.0, prog))) * (1 + 0.0075 * k * (1 - math.cos(2 * math.pi * t / 8)))
        for t0, amp in self.kicks:
            if t >= t0:
                z *= 1 + amp * math.exp(-(t - t0) / 0.22)
        if self.close and t > self.dur - 1.5:
            z *= 1 + 0.07 * ease_io((t - (self.dur - 1.5)) / 1.5)
        tx = 18 * k * math.sin(2 * math.pi * t / 7.3); ty = 14 * k * math.sin(2 * math.pi * t / 9.1 + 1.3)
        th = math.radians(0.6 * k * math.sin(2 * math.pi * t / 11.7 + 0.4))
        cx, cy = (self.fx, self.fy) if zf > 1.0 else (W / 2, H / 2)
        c, s = math.cos(th), math.sin(th)
        # output (x, y) -> input: cx + R^-1 ((x - cx - tx), (y - cy - ty)) / z
        a, b = c / z, s / z
        d, e = -s / z, c / z
        cc_ = cx - a * (cx + tx) - b * (cy + ty)
        f = cy - d * (cx + tx) - e * (cy + ty)
        return img.transform((W, H), Image.AFFINE, (a, b, cc_, d, e, f), resample=Image.BILINEAR)


def vignette_mask():
    m = Image.new("L", (W // 4, H // 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((150 // 4, 330 // 4, 930 // 4, 1500 // 4), radius=50, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(130 / 4)).resize((W, H), Image.BILINEAR)
    return np.asarray(m, np.float32)[..., None] / 255


WARM = np.array([1.0, 0.97, 0.90], np.float32)


def apply_vignette(arr, M, corner):
    k = corner + (1 - corner) * M
    return arr * k * (WARM * (1 - M) + M)


def blur_small(arr, r):
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(0.1, r / 4)))
    return np.asarray(im.resize((W, H), Image.BILINEAR), np.float32)


def streaks(f, seed):
    """Gold and amber light streaks for the leak (procedural, low resolution, screen-blended)."""
    lw, lh = W // 8, H // 8
    yy, xx = np.mgrid[0:lh, 0:lw].astype(np.float32)
    u = (xx / lw * 0.8 + yy / lh * 0.35) - 0.06 * f + (seed % 7) * 0.13
    a = 0.5 + 0.5 * np.sin(u * 9.0) * np.sin(u * 3.1 + 1.0)
    b = np.exp(-((xx / lw - 0.3 - 0.04 * f) / 0.35) ** 2)
    col = np.array([255, 179, 71], np.float32) * (1 - b[..., None]) + np.array([255, 241, 208], np.float32) * b[..., None]
    L = col * np.clip(a, 0, 1)[..., None]
    return np.asarray(Image.fromarray(L.astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)


def leak_frame(arr, f, seed):
    """T2 at frame f (0..17, white peak on f12)."""
    if f < 3:
        e = (f + 1) / 3; return arr + (255 - arr) * 0.2 * e
    if f < 7:
        e = (f - 2) / 4
        out = blur_small(arr, 20 * e) * (1 - 0.1 * e) + np.array([30, 14, 0], np.float32) * e
        return out + (255 - out) * 0.2
    amber = np.array([255, 170, 60], np.float32)
    if f <= 12:
        e = (f - 6) / 6
        out = blur_small(arr, 20)
        out = out * (1 - 0.3 * e) + amber * 0.3 * e                # the picture warms toward amber
        L = np.clip(streaks(f, seed) * (0.8 + 0.6 * e), 0, 255)
        out = 255 - (255 - out) * (255 - L) / 255
        return out + (255 - out) * (0.85 * e ** 3)
    e = 1 - (f - 12) / 5
    out = blur_small(arr, 20 * e)
    out = out * (1 - 0.25 * e) + amber * 0.25 * e
    L = streaks(f, seed) * 0.8 * e
    return 255 - (255 - out) * (255 - L) / 255


def flash_frame(text):
    """M13: one full gold frame with the slam's gold words in ink (text None = the gold frame only, for --no-text)."""
    img = Image.new("RGBA", (W, H), GOLD + (255,))
    if not text:
        return np.asarray(img.convert("RGB"), np.float32)
    s = fit_size(text, 600, gs.SAFE_R - gs.SAFE_L)
    sp = sprite(text, s, "ink")[0]
    put(img, tint(sp, (255, 243, 214), 0.6), W / 2 - 14, H / 2)
    put(img, tint(sp, (255, 255, 255), 0.35), W / 2 + 14, H / 2)
    put(img, sp, W / 2, H / 2)
    return np.asarray(img.convert("RGB"), np.float32)


# ---- the timeline ----------------------------------------------------------------------------------------------------------
def timeline(plan, dur, joins=(), matte=None):
    """The plan's lines built as blocks on one timeline: the light leaks, each block's exit (gone before the next block
    or leak starts), the sound events and each move's hit time. Returns (R, lines, Ls, leaks)."""
    global KEY_NEG
    KEY_NEG = plan.get("key_style") == "negative"          # only when the owner asks for the negative key word
    R = Render(plan, list(joins), dur)
    R.matte_path = matte
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    Ls = [Line(ln, R) for ln in lines]
    leaks = []
    for i, L in enumerate(Ls):
        if L.ln.get("transition") == "leak":
            tc = L.t_in - 1 * F1
            leaks.append((tc, i)); L.track = True
            L.sfx.append((tc, "whoosh_zoom", -2, f"line {L.id}: light-leak burn (white frame)"))
            L.ev.append((tc - 2 * F1, "leak (burning)"))
            L.hits.append((L.t_in + 6 * F1, "leak"))                   # the hit: its tracking close lands
            if R.vig_from is None:
                R.vig_from = tc
        elif L.ln.get("track"):
            L.track = True
            L.sfx.append((L.t_in + 6 * F1, "pop", -4, f"line {L.id}: tracking close at a section start"))
            L.hits.append((L.t_in + 6 * F1, "track"))
        if L.track:                                             # the first word drawn as a word (row 1's, unless it is a number row)
            L.track_u = next((u for r in L.rows for u in r if u.kind in ("word", "key")), None)
    for i, L in enumerate(Ls):                                  # each block leaves before the next one starts
        nxt = Ls[i + 1].t_in if i + 1 < len(Ls) else dur
        lk = next((tc for tc, j in leaks if j == i + 1), None)
        gone = nxt if lk is None else lk - 6 * F1
        ex = PULSE_F if L.ln.get("exit") == "pulse" else 2
        L.t_out = min(L.t_out, gone - ex * F1)                 # its exit (2 frames, a pulse 4) is over before the next block
        if i + 1 == len(Ls) and R.close and dur - L.ln["end"] < 2.0:
            L.t_out = dur + 1.0                                  # the takeaway holds to the last frame (M14)
        if L.ln.get("exit") == "pulse":
            L.sfx.append((L.t_out + 2 * F1, "swish_soft", -4, f"line {L.id}: pulse exit"))   # on the swell's peak (f2)
            L.hits.append((L.t_out + 2 * F1, "pulse"))
        if getattr(L, "flash_text", None):
            L.flash_at = int(round((L.t_out + 3 * F1) * FPS))
            L.sfx.append((L.flash_at / FPS, "impact", -2, f"line {L.id}: flash frame"))
    R.warn = []
    for L in Ls:                                                # a move must land before its block starts to leave
        for t, mv in L.hits:
            if mv != "pulse" and t > L.t_out - 2 * F1:
                n = round((t - L.t_out) * FPS)
                fr_ = lambda k: f"{k} frame{'s' if k != 1 else ''}"     # noqa: E731
                when = f"{fr_(n)} after" if n > 0 else "as" if n == 0 else f"only {fr_(-n)} before"
                fix = "use a plain exit or more room before the next line" if L.ln.get("exit") == "pulse" else "give it more room before the next line"
                R.warn.append(f"line {L.id}: its {mv} lands {when} its exit starts; {fix}")
    if R.close and Ls:
        # loudest when the takeaway's gold word lands (f15 of the push), so it rings out under the last second
        # (on the very last frame earshot heard no hit: the file ends before the sound can ring)
        Ls[-1].sfx.append((dur - 1.5 + 15 * F1, "chime_soft", -4, "closing push: the takeaway lands"))
    return R, lines, Ls, leaks


def move_hits(plan, dur=None):
    """Each designed move's hit time, the frame it lands (slam: B lands; leak / track: the tracking close; pulse: the
    exit), from the same timeline as the sound events: [(t, move, group)] for gs.check's 2 s rule. A line's moves are
    one group (slam + flash, leak + its close); the closing push is its own. Returns (hits, warnings): the warnings are
    the timeline's own (a move landing as its block leaves)."""
    lines = plan.get("lines", [])
    dur = dur or plan.get("duration") or max([ln.get("end", 0) for ln in lines] + [0])
    R, _, Ls, _ = timeline(plan, dur)
    out = [(t, mv, i) for i, L in enumerate(Ls) for t, mv in L.hits if 0 <= t <= dur]
    if R.close:
        out.append((dur - 1.5 + 15 * F1, "close", len(Ls)))
    return sorted(out), R.warn


def video_dur(path, fallback):
    """The first video stream's duration (the file's duration is its longest stream, often the audio); fallback when the
    container does not say."""
    probe = os.path.join(os.path.dirname(gs.cc.FFMPEG), "ffprobe") if os.path.dirname(gs.cc.FFMPEG) else "ffprobe"
    try:
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.strip()
        return min(fallback, float(out))
    except (OSError, ValueError):
        return fallback


# ---- main ------------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--map", default=None, help="tight.cutmap.json: pause cuts for the wide / tight framing switch")
    ap.add_argument("--matte", default=None, help="matte.mp4 from poster-kinetic matte.py (same framing): needed for move \"behind\"")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop"); ap.add_argument("--focus", type=float, default=0.5)
    ap.add_argument("--to", type=float, default=None)
    ap.add_argument("--no-text", action="store_true"); ap.add_argument("--phone", action="store_true")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    t0 = time.time()
    plan = load(a.plan)
    err, warn = gs.check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    dur = full = video_dur(a.video, gs.probe(a.video)["duration"])   # the picture's length: audio past it is cut, not frozen
    if a.to:
        dur = min(dur, a.to)
    joins = []
    if a.map and os.path.isfile(a.map):
        segs = load(a.map).get("segments") or []
        joins = [float(s[2]) for s in segs[1:] if len(s) >= 3]
    hits, hw = move_hits(plan, full)
    _, warn = gs.check(plan, hits); warn += hw                  # the 2 s rule on each move's hit time (the whole clip)
    R, lines, Ls, leaks = timeline(plan, dur, joins, a.matte if a.matte and os.path.isfile(a.matte) else None)
    if not R.chin_given:
        warn.append("camera chin not set: captions assume the chin at y 864; measure it on 3 frames per shot and set plan camera.chin")
    behind = [L for L in Ls if L.mv == "behind"]
    if behind and not (a.matte and os.path.isfile(a.matte)):
        report(tool="render", ok=False, errors=["move \"behind\" needs --matte (poster-kinetic matte.py on the same clip)"], warnings=warn)
        sys.exit(1)
    mdec = None
    if behind:
        mdec = subprocess.Popen([gs.cc.FFMPEG, "-hide_banner", "-loglevel", "error", "-t", f"{dur:.3f}", "-i", a.matte, "-vf", f"scale={W}:{H},fps={FPS}",
                                 "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    VM = vignette_mask()
    flashes = {L.flash_at: flash_frame(None if a.no_text else L.flash_text) for L in Ls if getattr(L, "flash_at", None)}
    pre = ""
    if a.frame == "crop":
        vf, vflag = pre + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,setsar=1,fps={FPS}", "-vf"
    else:
        vf, vflag = (f"[0:v]split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
                     f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"), "-filter_complex"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = ["-t", f"{dur:.3f}"]; FF = gs.cc.FFMPEG
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FF, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    dec = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", *tl, "-i", a.video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    # every drawn frame is kept (no -shortest: it cut the video where the audio ends, 0-2 frames early depending on how
    # fast the frames came, so a --no-text clean.mp4 came out shorter than edit.mp4); the audio is already cut to -t
    enc = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            *tl, "-i", a.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf, "-pix_fmt", "yuv420p",
                            *acodec, "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    qin, qout = queue.Queue(8), queue.Queue(8); fsz = W * H * 3

    def reader():
        while True:
            buf = dec.stdout.read(fsz)
            if len(buf) < fsz:
                qin.put(None); return
            qin.put(buf)

    def writer():
        while True:
            b = qout.get()
            if b is None:
                return
            enc.stdin.write(b)
    threading.Thread(target=reader, daemon=True).start(); thw = threading.Thread(target=writer, daemon=True); thw.start()
    n = 0
    prev_small = None
    while True:
        buf = qin.get()
        if buf is None:
            break
        t = n / FPS
        src = Image.frombytes("RGB", (W, H), buf)
        small = np.asarray(src.convert("L").resize((135, 240), Image.BILINEAR), np.float32)
        cut = prev_small is not None and float(np.abs(small - prev_small).mean()) > 9.0
        prev_small = small
        R.see(t, cut)
        img = R.transform(src, t)
        arr = np.asarray(img, np.float32)
        corner = None
        if R.vig_from is not None and t >= R.vig_from:
            corner = 1 - 0.65 * min(1.0, (t - R.vig_from) * FPS / 5)
        if R.close and t > dur - 1.5:
            p = ease_io((t - (dur - 1.5)) / 1.5)
            corner = (corner if corner is not None else 1.0) * (1 - p) + 0.25 * p
        if corner is not None and corner < 0.999:
            arr = apply_vignette(arr, VM, corner)
        for tc, i in leaks:
            f = (t - (tc - 12 * F1)) * FPS
            if 0 <= f <= 17:
                arr = leak_frame(arr, f, i)
        if n in flashes:
            arr = flashes[n]
        fr = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
        mbuf = mdec.stdout.read(W * H) if mdec else b""
        live = [L for L in behind if L.tW - 0.01 <= t <= L.t_out + 5 * F1] if not a.no_text and n not in flashes else []
        if live and len(mbuf) == W * H:
            # M15: the word goes on the picture, then the speaker (matte, moved by the same camera) goes back on top
            person = R.transform(Image.frombytes("L", (W, H), mbuf), t).filter(ImageFilter.GaussianBlur(1.2))
            pic = fr.copy()
            begin_neg(fr)
            for L in live:
                L.draw_behind(fr, t)
            fr = end_neg(fr, pic)                               # a negative word behind: the picture inverted in its letters
            fr = Image.composite(pic, fr, person)
        if not a.no_text and n not in flashes:
            pic = fr.copy() if KEY_NEG else None
            begin_neg(fr)
            for L in Ls:
                if L.t_in - 0.01 <= t <= L.t_out + 5 * F1:
                    L.draw(fr, t)
            fr = end_neg(fr, pic)
        qout.put(np.asarray(fr.convert("RGB")).tobytes())
        n += 1
    qout.put(None); thw.join(); enc.stdin.close(); enc.wait(); dec.wait()
    if mdec:
        mdec.stdout.close(); mdec.wait()
    base = os.path.splitext(a.out)[0]
    out = {"tool": "render", "ok": True, "out": a.out, "frames": n, "seconds": round(n / FPS, 2), "render_seconds": round(time.time() - t0, 1),
           "camera": {"on": R.cam_on, "framing_switches": len(R.frames) - 1, "chin_eff": round(R.chin_eff)}}
    if not a.no_text:
        def st(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base + ".srt", "w", encoding="utf-8") as fh:
            for i, ln in enumerate(lines):                      # a cue ends where the next one starts (never two at once)
                end = ln["end"] + 0.3 if i + 1 == len(lines) else min(ln["end"] + 0.3, lines[i + 1]["start"])
                fh.write(f"{i + 1}\n{st(ln['start'])} --> {st(end)}\n{display(ln['text'])}\n\n")
        ev, sfx = [], []
        for L in Ls:
            ev.append({"t": L.t_in + 0.25, "kind": "caption", "line": L.id})
            ev += [{"t": tt, "kind": k, "line": L.id} for tt, k in L.ev]
            for tt, snd, db, what in L.sfx:
                e = {"frame": int(round(tt * FPS)), "sound": snd, "what": what}
                if db:
                    e["db"] = db
                sfx.append(e)
        save(base + ".pk.json", {"video": os.path.abspath(a.out), "events": sorted([e for e in ev if 0 <= e["t"] < dur], key=lambda e: e["t"]), "warnings": warn})
        save(base + ".sfx-events.json", {"fps": FPS, "events":sorted([e for e in sfx if 0 <= e["frame"] < n], key=lambda e: e["frame"]),
                                          "note": "one sound per designed move, loudest on its frame (Gold Stack sheet p.10); none on caption words or plain cuts"})
        pc = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
        if os.path.abspath(a.plan) != pc:
            shutil.copyfile(a.plan, pc)
        out.update(srt=base + ".srt", sfx_events=base + ".sfx-events.json", lines=len(Ls), moves=sum(1 for L in Ls if L.mv), leaks=len(leaks))
    if a.phone:
        phone = base + "_phone.mp4"
        if os.path.getsize(a.out) <= 28 * 1048576:
            shutil.copyfile(a.out, phone)
        else:
            kbps = int((28 * 8 * 1024 * 1024 / max(1.0, dur) - 160_000) / 1000)
            for k in (1.0, 0.85, 0.7):
                subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", a.out, "-c:v", "libx264", "-preset", "medium", "-b:v", f"{int(kbps * k)}k",
                                "-maxrate", f"{int(kbps * k * 1.4)}k", "-bufsize", f"{int(kbps * k * 2)}k", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", phone])
                if os.path.getsize(phone) <= 28.5 * 1048576:
                    break
        out.update(phone=phone, phone_mb=round(os.path.getsize(phone) / 1048576, 1))
    out["warnings"] = warn
    report(**out)


if __name__ == "__main__":
    main()
