"""Render a clip in the Orbit Pop style (环绕弹字) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--map tight.cutmap.json] [--matte matte.mp4] [--frame crop|blur]
                        [--focus 0.5] [--to SECONDS] [--phone] [--no-text] [--preset medium]

Each line is one block placed around the speaker. Zone C (default): rows over the chest, top at least 40 px under the chin of
every framing the block is on screen in; supporting words Settle (O1: 106 % -> 100 % in 2 frames), middle rows Rise (O3), the
line's "key" Pops (O2: 12 45 85 122 108 102 100 %, peak f3 on the syllable). Line "move": slide (O4 XL first word slides in) /
mixed (O6 XL first word + small rest in one row) / number (O7 digit drop, Oswald; "number", optional "unit", "lead") /
tilt (O5 two characters either side of the head at -8.5 / +18 deg, behind it; "word") / column (O9 the closing takeaway down
the left side with a light streak and a lime-white bloom; "word"). Line "zone": "A" puts the key in the top band behind the
head (person matte), as big as possible, shrinking only while < 35 % of a character shows. "sub": the English sub-word (O8 type-on). "exit": "kick" (X1: 88 108 155
88 % from the block's top-centre, then gone; "glitch": true = O10 slice glitch on f0; "push": true = C2 push cut 100 -> 115 %
under it) or plain (2 frames to 90 % and 0 %). Plan "camera": {"face", "chin", "head_top", "alternate", "push" (C1 opening push
100 -> 112 % in 14 frames), "drift"}: with --map it switches between the wide and a 1.15x tight framing at pause cuts, on the
exact frame the picture cuts, each framing at least 1.2 s (as Gold Stack). Text is pinned to the screen.
One sounded moment per block: an incoming kick (or the opening push on block 1) is the block's sound and its pop stays silent;
otherwise its first sounded move (slide > number > tilt > column > key pop) sounds and the others stay silent.
Writes <out>.mp4, .srt, .pk.json (preview events), .sfx-events.json (sfx skill), a copy of plan.json; --phone also
<out>_phone.mp4 under 28 MiB. Prints one JSON line.
"""
import argparse, math, os, queue, re, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import op  # noqa: E402
from op import (F1, FPS, W, H, SIZES, display, disp_times, sub_time, keys, ease_out, ease_io, load, save, report, is_cjk,
                sprite, tokens, nchars)  # noqa: E402

CX_C = (op.SAFE_L + op.SAFE_RB) / 2                    # 518: blocks in zone C centre here
STROKE = 3                                             # the stroke reaches about 3 px past the ink
ROW_GAP = 28                                           # rows 24-32 px apart
STEP = 70                                              # each row steps right of the one above (the ad steps 90-220 px)
POP = (0.12, 0.45, 0.85, 1.22, 1.08, 1.02, 1.00)       # O2 per frame
TILT_POP = (0.15, 0.49, 0.88, 1.06, 1.02, 1.00)        # O5 per frame
KICK = (0.88, 1.08, 1.55, 0.88)                        # X1 f0..f3, gone on f4
GLITCH = (-24, 18, -12)                                # O10 band offsets (px)
VIS_MIN = op.BEHIND_SHOW                               # behind the head: shrink only while less than 35 % of a character shows
VIS_AIM = 1 - op.BEHIND_IN                             # ... and sit as close to the head as hides at most 40 % (Gold Stack)
TOUCH_MIN = 0.15                                       # a character less than 15 % behind the head on every frame falls back to zone C
C1_F, C1_Z = 14, 1.12                                  # C1: 100 -> 112 % in 14 frames, then the shot holds at 112 %
C1_JOIN = (C1_F + 6) / FPS                             # 0.67 s: block 1's first move by then shares the opening push's moment
TIGHT = 1.15                                           # the tight framing (Pong recipe)
PUSH_F = 6                                             # C2: 6 frames, ease-in-out
TILT_ROT = (8.5, -18.0)                                # PIL degrees (positive = counter-clockwise): -8.5 deg left, +18 deg right


def snap(t):
    """A time on the 30 fps frame grid, so every keyframe table lands on whole frames (the 122 % and 155 % peaks show)."""
    return round(t * FPS) / FPS


def table(f, vals):
    """Linear interpolation through per-frame values (f0, f1, ...)."""
    if f <= 0:
        return vals[0]
    if f >= len(vals) - 1:
        return vals[-1]
    i = int(f)
    return vals[i] + (vals[i + 1] - vals[i]) * (f - i)


def right_lim(y0, y1):
    """The right margin for an ink box spanning y0..y1: 950 where it reaches the button band (y 1000-1700), else 994."""
    return op.SAFE_RB if y1 > op.BAND[0] and y0 < op.BAND[1] else op.SAFE_R


def fit_k(x, y, w, h, s=1.0, top=None):
    """The largest scale (around its centre) at which a w x h ink box at (x, y) stays inside x 86..994 (950 in the button
    band) and y 200..1620; s = the scale it is drawn at, for the band test (Gold Stack's clamp)."""
    rl = right_lim(y - h * s / 2, y + h * s / 2)
    k = 9.9
    if w > 0:
        k = min(k, 2 * (x - op.SAFE_L - STROKE) / w, 2 * (rl - STROKE - x) / w)
    if h > 0:
        k = min(k, 2 * (y - max(op.TOP + STROKE, top or 0)) / h, 2 * (op.BOTTOM - STROKE - y) / h)
    return k


def prep(img, s=1.0, rot=0.0, alpha=1.0, blur=0.0, mblur=0.0):
    """The sprite as it will be pasted (cc.put's steps), so it can be measured before it goes on the frame."""
    if alpha <= 0.01 or s <= 0.01:
        return None
    if abs(s - 1) > 0.004:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
    if abs(rot) > 0.3:
        img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
    if blur > 0.5:
        g = int(blur * 2) + 2
        big = Image.new("RGBA", (img.width + 2 * g, img.height + 2 * g)); big.alpha_composite(img, (g, g))
        img = big.convert("RGBa").filter(ImageFilter.GaussianBlur(blur)).convert("RGBA")
    if mblur >= 2:
        img = op.cc.hblur(img, mblur)
    if alpha < 0.995:
        img = img.copy(); img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    return img


def paste(fr, img, cx, cy):
    if img is not None:
        op.cc._paste(fr, img, cx, cy)


def put(fr, img, cx, cy, s=1.0, rot=0.0, alpha=1.0, blur=0.0, mblur=0.0):
    paste(fr, prep(img, s, rot, alpha, blur, mblur), cx, cy)


# ---- units and rows ----------------------------------------------------------------------------------------------------------
class Unit:
    """One word on screen: its sprite, ink size, place (ink centre), entrance kind and the time of its f0."""
    def __init__(self, text, size, colour, t0, kind="settle", tracking=None):
        self.text, self.colour, self.t0, self.kind, self.tracking = text, colour, snap(t0), kind, tracking
        self.x = self.y = 0.0
        self.x0 = None                                    # slide start
        self.resize(size)

    def resize(self, size):
        self.size = size
        self.img, self.w, self.h, self.dy = sprite(self.text, size, self.colour, self.tracking)

    def land(self):
        return self.t0 + {"settle": 2, "rise": 5, "pop": 6, "xlpop": 6, "slide": 6, "unitpop": 6}.get(self.kind, 2) * F1


class Row:
    def __init__(self, units, align="base", gap=None):
        self.units, self.align, self.gap = units, align, gap

    def gap_of(self, a, b):
        """The fixed gap (14 px after an XL word, 16 px around a number) next to the big unit; else the type's own spacing."""
        if self.gap is not None and (a.kind in ("number", "xlpop", "slide") or b.kind == "number"):
            return self.gap
        cjk = is_cjk(a.text[-1]) and is_cjk(b.text[0])
        sz = min(a.size, b.size) if self.gap is not None else max(a.size, b.size)
        return sz * (0.06 if cjk else 0.22)

    def width(self):
        u = self.units
        return sum(x.w for x in u) + sum(self.gap_of(a, b) for a, b in zip(u, u[1:]))

    def extent(self):
        """(top, bottom) of the ink relative to the row's reference line (baseline / centre / bottom)."""
        if self.align == "centre":
            return -max(u.h for u in self.units) / 2, max(u.h for u in self.units) / 2
        if self.align == "bottom":
            return -max(u.h for u in self.units), 0.0
        return min(u.dy - u.h / 2 for u in self.units), max(u.dy + u.h / 2 for u in self.units)

    def height(self):
        a, b = self.extent()
        return b - a

    def place(self, left, top):
        a, _ = self.extent()
        ref = top - a
        x = left
        for k, u in enumerate(self.units):
            if k:
                x += self.gap_of(self.units[k - 1], u)
            u.x = x + u.w / 2
            u.y = {"centre": ref, "bottom": ref - u.h / 2}.get(self.align, ref + u.dy)
            x += u.w

    def scale(self, k):
        for u in self.units:
            u.resize(u.size * k)


def char_t(ln, i):
    """Spoken time of the character at index i of the line's display text (display() drops punctuation)."""
    ct = op.char_times(ln)
    src, d = ln["text"], display(ln["text"])
    k = 0
    for q, c in enumerate(d):                            # walk the display text along the source text
        if not c.strip():
            continue
        k2 = src.find(c, k)
        if k2 < 0:
            break
        if q >= i:
            return ct[k2] if k2 < len(ct) else ln["start"]
        k = k2 + 1
    return ct[-1] if ct else ln["start"]


def word_units(ln, text, size, colour="white", kind="settle", lead=2):
    """Units for a displayed piece of the line, each landing as it is spoken (f0 `lead` frames before its first syllable)."""
    times = disp_times(ln, text)
    out, i = [], 0
    for tok in tokens(text):
        j = text.find(tok, i)
        if j < 0:
            j = i
        out.append(Unit(tok, size, colour, times[min(j, len(times) - 1)] - lead * F1, kind)); i = j + len(tok)
    return out


def merge_punct(units):
    """A piece that is only punctuation ('?' after the key) joins the word before it, never a row of its own."""
    out = []
    for u in units:
        if out and not any(c.isalnum() or is_cjk(c) for c in u.text):
            out[-1].text += u.text.strip(); out[-1].resize(out[-1].size)
        else:
            out.append(u)
    return out


def greedy_rows(units, key_u=None, limit=op.MAXCH["M"]):
    """Rows of at most `limit` characters; the key stands on its own row."""
    rows, cur, n = [], [], 0.0
    for u in units:
        c = nchars(u.text)
        if u is key_u:
            if cur:
                rows.append(cur); cur, n = [], 0.0
            rows.append([u]); continue
        if cur and n + c > limit:
            rows.append(cur); cur, n = [], 0.0
        cur.append(u); n += c
    if cur:
        rows.append(cur)
    return [Row(r) for r in rows]


def plan_rows(ln, units, skip=""):
    """The plan's "rows" as rows of whole units; `skip` = a part drawn elsewhere (top band, tilt, column)."""
    rds = [display(r).replace(" ", "") for r in ln["rows"]]
    counts = [len(rd) for rd in rds]
    sk = skip.replace(" ", "")
    p = "".join(rds).find(sk) if sk else -1
    if p >= 0:
        acc = 0
        for i, c in enumerate(list(counts)):
            counts[i] -= max(0, min(acc + c, p + len(sk)) - max(acc, p)); acc += c
    rows, k = [], 0
    for c in counts:
        row, n = [], 0
        while k < len(units) and n < c:
            row.append(units[k]); n += len(units[k].text.replace(" ", "")); k += 1
        if row:
            rows.append(row)
    if k < len(units):
        if rows:
            rows[-1] += units[k:]
        else:
            rows.append(units[k:])
    return [Row(r) for r in rows if r]


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


# ---- the camera --------------------------------------------------------------------------------------------------------------
class Cam:
    """C1 opening push, the wide / 1.15x tight framing at pause cuts (Gold Stack's switch-on-the-real-cut logic), C2 push
    cuts and a slight drift. Text is never moved by it (pinned to the screen)."""
    def __init__(self, plan, joins, dur):
        cam = plan.get("camera") or {}
        self.on = cam.get("on", True)
        fx, fy = cam.get("face") or [0.5, 0.3]
        self.fx, self.fy = fx * W, fy * H
        self.chin = float(cam["chin"]) if cam.get("chin") is not None else 0.45 * H
        self.chin_given = cam.get("chin") is not None
        self.head_top = float(cam["head_top"]) if cam.get("head_top") is not None else self.fy - 0.17 * H
        self.c1 = self.on and cam.get("push", True)
        self.drift = max(0.0, min(1.0, float(cam.get("drift", 0.4)))) if self.on else 0.0
        self.alternate = self.on and cam.get("alternate", True) and bool(joins)
        self.dur = dur
        self.frames = [(0.0, 1.0, 0)]                    # (time, framing zoom, push frames: 0 = a hard switch at a cut)
        last = 0.0
        for j in joins:
            if self.alternate and j - last >= 1.2 and dur - j >= 1.2:
                self.frames.append((j, TIGHT if self.frames[-1][1] == 1.0 else 1.0, 0)); last = j
        self.warn = []
        self.reset()

    def reset(self):
        self.active = [self.frames[0]]
        self.pending = list(self.frames[1:])

    def add_push(self, tp):
        """C2 at tp (a kick's f0): push wide -> tight over 6 frames; it replaces the next hard switch to tight within 0.6 s
        (the push hides that jump cut). Returns False (and warns) when the framing is already tight there."""
        cur = [f for f in self.frames if f[0] <= tp + 1e-6][-1]
        if cur[1] != 1.0:
            self.warn.append(f"push cut at {tp:.2f}s: the framing is already tight there (C2 needs the wide framing); no push")
            return False
        nxt = [f for f in self.frames if tp < f[0] <= tp + 0.6 and f[1] == TIGHT]
        self.frames = [f for f in self.frames if f not in nxt] + [(tp, TIGHT, PUSH_F)]
        self.frames.sort()
        # the alternation after it continues from tight (the next switch is the wide C3)
        out = [self.frames[0]]
        for t, z, p in self.frames[1:]:
            out.append((t, z if p else (TIGHT if out[-1][1] == 1.0 else 1.0), p))
        self.frames = out
        self.reset()
        return True

    def hold(self, t0):
        """The closing glow column keeps the framing it starts in (zone D needs the room beside the head): the hard
        switches and push cuts from t0 - 0.3 s on are dropped (it runs after add_push, so the hold wins)."""
        dropped = [f for f in self.frames[1:] if f[0] >= t0 - 0.3]
        if dropped:
            self.frames = [f for f in self.frames if f not in dropped]
            self.reset()
        return dropped

    def switches(self):
        return [t for t, _, p in self.frames[1:] if not p]

    def see(self, t, cut):
        """Once per frame: a planned hard switch happens on the frame the picture really cuts (searched from 1.5 frames
        before to 3.5 frames after its time); a push starts on its own time."""
        while self.pending and (self.pending[0][2] and t >= self.pending[0][0] - 0.5 * F1 or t > self.pending[0][0] + 3.5 * F1):
            s, z, p = self.pending.pop(0); self.active.append((s if p else t, z, p))
        if self.pending and not self.pending[0][2] and cut and t >= self.pending[0][0] - 1.5 * F1:
            s, z, p = self.pending.pop(0); self.active.append((t, z, p))

    def base(self, t):
        if not self.c1:
            return C1_Z
        return 1.0 + (C1_Z - 1.0) * ease_out(min(1.0, t * FPS / C1_F))

    def coeffs(self, zf, t):
        """The inverse affine (a, c, e, f): input = (a x + c, e y + f) for framing zf at time t."""
        zb = self.base(t)
        z = zb * zf
        cx, cy = (self.fx, self.fy) if zf > 1.0 else (W / 2, H / 2)
        ramp = (zb - 1.0) / (C1_Z - 1.0) if C1_Z > 1 else 1.0
        tx = 18 * self.drift * ramp * math.sin(2 * math.pi * t / 7.3)
        ty = 14 * self.drift * ramp * math.sin(2 * math.pi * t / 9.1 + 1.3)
        return 1 / z, cx - (cx + tx) / z, 1 / z, cy - (cy + ty) / z

    def state(self, t, planned=False):
        """(framing before, framing now, progress 0..1) at t."""
        fr = [f for f in self.frames if f[0] <= t + 1e-9] if planned else self.active
        cur = fr[-1]
        prev = fr[-2] if len(fr) > 1 else cur
        if cur[2]:
            p = ease_io(min(1.0, (t - cur[0]) * FPS / cur[2]))
            return prev[1], cur[1], p
        return cur[1], cur[1], 1.0

    def transform(self, img, t, planned=False, resample=Image.BILINEAR):
        if not self.on:
            return img
        z0, z1, p = self.state(t, planned)
        c1 = self.coeffs(z1, t)
        if p < 1.0:
            c0 = self.coeffs(z0, t)
            c1 = tuple(a + (b - a) * p for a, b in zip(c0, c1))
        a, c, e, f = c1
        return img.transform((W, H), Image.AFFINE, (a, 0, c, 0, e, f), resample=resample)

    def out_y(self, y, zf):
        """Where a source row y lands on the output in framing zf, after the opening push (worst drift down included)."""
        cy = self.fy if zf > 1.0 else H / 2
        return cy + (y - cy) * C1_Z * zf + 14 * self.drift

    def chin_out(self, zf):
        y = self.out_y(self.chin, zf)
        if zf == 1.0 and self.c1:
            y = max(y, self.chin)                          # during the opening push (from 100 %)
        return y

    def chin_during(self, t0, t1):
        """The lowest chin on the output while a block is on screen between t0 and t1 (every framing it meets)."""
        if not self.on:
            return self.chin
        zs = {f[1] for f in self.frames if t0 - 1e-9 <= f[0] <= t1}
        zs.add(self.state(t0, True)[1]); zs.add(self.state(t0, True)[0])
        return max(self.chin_out(z) for z in zs)


# ---- the matte sampler (layout) ----------------------------------------------------------------------------------------------
class Matte:
    """The person matte on the output frame at a time (moved by the planned camera), at a quarter of the size."""
    Q = 4

    def __init__(self, path, cam):
        self.path, self.cam, self.cache = path, cam, {}

    def at(self, t):
        n = int(round(max(0.0, t) * FPS))
        if n not in self.cache:
            raw = subprocess.run([op.cc.FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{n / FPS:.3f}", "-i", self.path,
                                  "-frames:v", "1", "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
            if len(raw) < W * H:
                self.cache[n] = None
            else:
                im = self.cam.transform(Image.frombytes("L", (W, H), raw[:W * H]), n / FPS, planned=True)
                self.cache[n] = np.asarray(im.resize((W // self.Q, H // self.Q), Image.BILINEAR), np.float32) / 255
        return self.cache[n]

    def head(self, t):
        """(head top y, left x, right x) of the face box on the output at t: in each matte row above the chin, the run of
        person pixels through the face centre (a raised hand or the chair beside the head is not the face)."""
        m = self.at(t)
        if m is None:
            return None
        q = self.Q
        cam = self.cam
        zf = cam.state(t, True)[1]
        cx = cam.fx if zf > 1.0 else W / 2 + (cam.fx - W / 2) * C1_Z
        c = min(max(int(cx) // q, 0), m.shape[1] - 1)        # a face near the edge (x >= 0.95) stays on the matte
        chin = cam.chin_out(zf)
        runs = []
        for y in range(0, min(int(chin) // q, m.shape[0])):
            row = m[y] > 0.5
            if not row[c]:
                continue
            a = c
            while a > 0 and row[a - 1]:
                a -= 1
            b = c
            while b < len(row) - 1 and row[b + 1]:
                b += 1
            runs.append((y * q, a * q, (b + 1) * q))
        if not runs:
            return None
        top = runs[0][0]
        skull = max([r_ - l_ for y, l_, r_ in runs if y <= top + 0.55 * (chin - top)] or [0])
        l, r = None, None
        for y, l_, r_ in runs:                               # down to the shoulder line (the run widens past the skull)
            if skull and r_ - l_ > 1.05 * skull and y > top + 0.55 * (chin - top):
                break
            l = l_ if l is None else min(l, l_)
            r = r_ if r is None else max(r, r_)
        return float(top), float(l), float(r)


def visible(m, img, cx, cy):
    """Share of a pasted sprite's ink that the person (matte m, quarter size) leaves visible."""
    q = Matte.Q
    a = np.asarray(img.getchannel("A").resize((max(1, img.width // q), max(1, img.height // q)), Image.BILINEAR), np.float32) / 255
    a = (a > 0.5).astype(np.float32)                        # the letters (fill + stroke), not the soft shadow
    x0, y0 = int(round((cx - img.width / 2) / q)), int(round((cy - img.height / 2) / q))
    h, w = a.shape
    tot = a.sum()
    if tot <= 0:
        return 1.0
    mm = np.zeros_like(a)
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(m.shape[1], x0 + w), min(m.shape[0], y0 + h)
    if X1 > X0 and Y1 > Y0:
        mm[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] = m[Y0:Y1, X0:X1]
    return float((a * (1 - mm)).sum() / tot)


# ---- one block ---------------------------------------------------------------------------------------------------------------
class Block:
    def __init__(self, ln, i, R):
        self.ln, self.i, self.id, self.R = ln, i, ln.get("id", i + 1), R
        self.mv = ln.get("move") or ""
        self.zone = "D" if self.mv == "column" else (ln.get("zone") or "C")
        self.kick = ln.get("exit") == "kick"
        self.rows, self.behind, self.digits, self.letters = [], [], [], []
        self.column = None
        self.cands = []                                    # sounded moves in priority order: (kind, [(t, sound, db, what)])
        self.quiet = []                                    # designed moves that never sound (the O6 XL pop): [(t, kind)]
        self.ev = []
        self.notes = []
        self.text = display(ln["text"]).strip()
        kc = ln.get("key_colour") or "lime"
        self.kc = kc if kc in op.KEY_COLOURS else "lime"
        dkey = display(ln.get("key") or "").strip() or None
        mv = self.mv
        if mv == "number":
            self.build_number(ln)
        elif mv == "column":
            self.build_column(ln, dkey)
        elif mv == "tilt":
            self.build_tilt(ln, dkey)
        else:
            self.build_words(ln, dkey)
        self.units = [u for r in self.rows for u in r.units]
        starts = [u.t0 for u in self.units] + [p["t0"] for p in self.behind] + [d["t0"] for d in self.digits]
        if self.column:
            starts.append(self.column["t0"])
        self.t_in = min(starts) if starts else ln["start"]
        lands = [u.land() for u in self.units] + [p["t0"] + 6 * F1 for p in self.behind] + [d["t0"] + 2 * F1 for d in self.digits]
        if self.column:
            lands.append(self.column["t0"] + 18 * F1)
        self.t_land = max(lands) if lands else ln["end"]

    # zone C words, with a key (O2), an XL first word (O4 slide / O6 mixed) and the zone A top band
    def build_words(self, ln, dkey):
        text = self.text
        key_up = dkey if self.zone == "A" and dkey else None
        units, key_u = [], None
        first = None
        if self.mv in ("slide", "mixed"):
            fw = op.first_word(text)
            if fw and text.replace(" ", "").startswith(fw):
                p = text.find(fw[0])
                t_fw = disp_times(ln, fw)[0]
                kind = "slide" if self.mv == "slide" else "xlpop"
                colour = self.kc if dkey == fw else "white"
                first = Unit(fw, SIZES["XL"], colour, t_fw - (2 if kind == "slide" else 3) * F1, kind)
                text = text[p + len(fw):].strip()
                if dkey == fw:
                    key_u = first; dkey = None; key_up = None   # (check: never the XL word and the top band at once)
                if kind == "slide":
                    self.cands.append(("slide", [(first.t0 + 1 * F1, "swish_soft", -2, f"line {self.id}: side slide ({fw})")]))
                    self.ev += [(first.t0 + 1 * F1, "slide (moving)"), (first.t0 + 6 * F1, "slide (landed)")]
                else:
                    self.ev += [(first.t0 + 3 * F1, "mixed XL (peak)"), (first.t0 + 8 * F1, "mixed row (built)")]
                    if dkey != fw:
                        self.quiet.append((first.t0 + 3 * F1, "mixed"))
        for piece, tag in pieces(text, [("key", dkey)]):
            if tag == "key" and key_up:
                continue                                    # drawn in the top band
            if tag == "key":
                t_k = disp_times(ln, piece)[0]
                key_u = Unit(piece, SIZES["L"], self.kc, t_k - 3 * F1, "pop")
                units.append(key_u)
            else:
                units += word_units(ln, piece, SIZES["M"])
        units = merge_punct(units)
        if key_u is not None and key_u is not first:
            self.cands.append(("pop", [(key_u.t0 + 3 * F1, "pop", -4, f"line {self.id}: key pops ({key_u.text})")]))
            self.ev += [(key_u.t0 + 3 * F1, "pop (peak)"), (key_u.t0 + 8 * F1, "pop (landed)")]
        elif first is not None and key_u is first:
            self.cands.append(("pop", [(first.t0 + 3 * F1, "pop", -4, f"line {self.id}: key pops ({first.text})")]))
        if key_up:
            self.build_top_band(ln, key_up)
        rows = []
        if first is not None:
            # O6: the XL first word, a 14 px gap, then at most 4 M or 6 S characters centred on it; the row <= 864 px
            small = sum(nchars(u.text) for u in units if u is not key_u) > 4
            size, cap = (SIZES["S"], 6) if small else (SIZES["M"], 4)
            rest, n = [], 0.0
            for u in units:
                if u is key_u or n + nchars(u.text) > cap:
                    break
                rest.append(u); n += nchars(u.text)
            for u in rest:
                u.resize(size)
            row = Row([first] + rest, "centre", 14)
            while row.width() > op.SAFE_RB - op.SAFE_L - 2 * STROKE and rest:
                row.units.pop(); rest.pop().resize(SIZES["M"])
            for u in rest:                                  # the small words settle after the big one lands
                u.t0 = max(u.t0, first.t0 + (6 if first.kind == "slide" else 3) * F1)
            rows.append(row)
            units = units[len(rest):]
        if ln.get("rows") and first is None:
            rows += plan_rows(ln, units, key_up or "")
        else:
            rows += greedy_rows(units, key_u)
        for r in rows:
            for u in r.units:
                if u is key_u and u.kind == "pop" and nchars(u.text) > op.MAXCH["L"]:
                    u.resize(min(SIZES["L"], (op.SAFE_RB - op.SAFE_L - 2 * STROKE) / max(1, u.w) * u.size))
        if len(rows) >= 3:                                  # middle rows rise (O3)
            for r in rows[1:-1]:
                for u in r.units:
                    if u.kind == "settle":
                        u.kind = "rise"
        self.rows = rows
        self.key_u = key_u

    def build_top_band(self, ln, dk):
        """Zone A: the key in the top band, behind the head (placed later on the matte), popping as the block's key."""
        t_k = disp_times(ln, dk)[0]
        chars = [c for c in dk if c.strip()]
        half = (len(chars) + 1) // 2
        groups = ["".join(chars[:half]), "".join(chars[half:])] if len(chars) > 1 else ["".join(chars)]
        for gi, g in enumerate(groups):
            if g:
                self.behind.append({"text": g, "colour": self.kc, "size": SIZES["L"], "rot": 0.0, "t0": snap(t_k - 3 * F1), "curve": POP,
                                    "side": gi if len(groups) > 1 else -1, "kind": "top"})
        self.cands.append(("pop", [(t_k, "pop", -4, f"line {self.id}: top-band key pops ({dk})")]))
        self.ev += [(t_k, "top band (peak)"), (t_k + 5 * F1, "top band (landed)")]

    def build_tilt(self, ln, dkey):
        """O5: the two characters of the turn word either side of the head, behind it; the rest of the line in zone C."""
        dw = display(ln["word"]).strip()
        t_w = disp_times(ln, dw)
        for k, c in enumerate(dw[:2]):
            t0 = (t_w[0] - 3 * F1) if k == 0 else max(t_w[0] - 3 * F1 + 7 * F1, t_w[min(k, len(t_w) - 1)] - 3 * F1)
            self.behind.append({"text": c, "colour": "white", "size": op.TILT, "rot": TILT_ROT[k], "t0": snap(t0), "curve": TILT_POP,
                                "side": k, "kind": "tilt"})
        ev = [(p["t0"] + 3 * F1, "pop", -5, f"line {self.id}: tilted {p['text']} pops") for p in self.behind]
        self.cands.append(("tilt", ev))
        self.ev += [(self.behind[0]["t0"] + 3 * F1, "tilt (first)"), (self.behind[-1]["t0"] + 6 * F1, "tilt (landed)")]
        text = self.text
        p = text.find(dw)
        rest = (text[:p] + " " + text[p + len(dw):]).strip() if p >= 0 else text
        units, key_u = [], None
        for piece, tag in pieces(rest, [("key", dkey)]):
            if tag == "key":
                key_u = Unit(piece, SIZES["L"], self.kc, disp_times(ln, piece)[0] - 3 * F1, "pop"); units.append(key_u)
            else:
                units += word_units(ln, piece, SIZES["M"])
        for u in units:
            u.t0 = max(u.t0, self.behind[0]["t0"] + 3 * F1)
        if key_u:
            self.cands.append(("pop", [(key_u.t0 + 3 * F1, "pop", -4, f"line {self.id}: key pops ({key_u.text})")]))
        units = merge_punct(units)
        self.rows = plan_rows(ln, units, dw) if ln.get("rows") else greedy_rows(units, key_u)
        for r in self.rows:
            for u in r.units:
                if u is key_u and nchars(u.text) > op.MAXCH["L"]:
                    u.resize(min(SIZES["L"], (op.SAFE_RB - op.SAFE_L - 2 * STROKE) / max(1, u.w) * u.size))
        if len(self.rows) >= 3:
            for r in self.rows[1:-1]:
                for u in r.units:
                    if u.kind == "settle":
                        u.kind = "rise"
        self.key_u = key_u

    def build_number(self, ln):
        """O7: the number (Oswald 400, green) drops in digit by digit and breathes; lead / unit on its baseline."""
        dn = ln["number"]; du = display(ln.get("unit") or "").strip() or None; dl = display(ln.get("lead") or "").strip() or None
        rows, num_row = [], None
        before, after = [], []
        t_n = sub_time(ln, ln["number"])
        text = self.text
        p = text.find(dn)                                   # the number first; lead / unit only when right beside it
        a0, a1 = p, p + len(dn)
        pre, post_t = text[:a0], text[a1:]
        lead = dl if dl and pre.rstrip(" ").endswith(dl) else None
        unit_t = du if du and post_t.lstrip(" ").startswith(du) else None
        if lead:
            pre = pre.rstrip(" ")[:-len(lead)]
        if unit_t:
            post_t = post_t.lstrip(" ")[len(unit_t):]
        if pre.strip():
            before.append((None, pre.strip()))
        if lead:
            before.append(("lead", lead))
        num = Unit(dn, op.NUMBER, "number", t_n - 1 * F1, "number", tracking=-0.04)
        num_row = [num]
        if unit_t:
            num_row.append(Unit(unit_t, SIZES["S"], "white", 0, "unitpop"))
        if post_t.strip():
            after.append((None, post_t.strip()))
        lead_u = None
        pre_units = []
        for tag, piece in before:
            if tag == "lead":
                lt = char_t(ln, a0 - len(piece))
                lead_u = Unit(piece, SIZES["M"], "white", lt - 2 * F1, "settle")
            else:
                pre_units += word_units(ln, piece, SIZES["M"])
        if pre_units:
            rows += greedy_rows(pre_units)
        num = num_row[0]
        if lead_u:
            num_row.insert(0, lead_u)
        offs = op.char_offsets(num.text, num.size, "number", -0.04)
        n = len(offs)
        for k, (c, dx, dy) in enumerate(offs):
            self.digits.append({"c": c, "dx": dx, "dy": dy, "t0": num.t0 + 2 * k * F1, "spr": sprite(c, num.size, "number")[0]})
        self.t_breath = num.t0 + (2 * (n - 1) + 2) * F1
        unit = next((u for u in num_row if u.kind == "unitpop"), None)
        if unit:
            unit.t0 = snap(max(self.t_breath, char_t(ln, a1) - 3 * F1))
        post = []
        for _, piece in after:
            post += word_units(ln, piece, SIZES["S"])
        post = merge_punct(post)
        # the words after the number stay on its baseline in S (as 在 90 天) while they fit (6 S characters, row <= 864 px)
        keep = []
        n_ = sum(nchars(u.text) for u in num_row if u.kind == "unitpop")
        for u in post:
            if n_ + nchars(u.text) > op.MAXCH["S"] - 1:
                break
            keep.append(u); n_ += nchars(u.text)
        row = Row(num_row + keep, "bottom", 16)
        while row.width() > op.SAFE_RB - op.SAFE_L - 2 * STROKE and keep:
            row.units.pop(); keep.pop()
        rows.append(row)
        post = post[len(keep):]
        for u in post:
            u.resize(SIZES["M"])
        if post:
            rows += greedy_rows(post)
        self.rows = rows
        self.num = num
        self.key_u = None
        self.cands.append(("number", [(num.t0, "impact", -3, f"line {self.id}: number drops ({num.text})")]))
        self.ev += [(num.t0, "number (first digit)"), (self.t_breath + 6 * F1, "number (breathing)"), (self.t_breath + 14 * F1, "number (landed)")]

    def build_column(self, ln, dkey):
        """O9: the closing takeaway as a column down the left (zone D) with a light streak and a lime-white bloom."""
        dw = display(ln.get("word") or ln.get("key")).strip()
        t_w = disp_times(ln, dw)[0]
        self.column = {"text": dw.replace(" ", ""), "size": op.COLUMN, "t0": snap(t_w - 10 * F1)}
        self.cands.append(("column", [(t_w, "whoosh_zoom", -2, f"line {self.id}: glow column flares ({dw})")]))
        self.ev += [(t_w - 5 * F1, "column (streak)"), (t_w, "column (flare)"), (t_w + 10 * F1, "column (held)")]
        text = self.text
        p = text.find(dw)
        rest = (text[:p] + " " + text[p + len(dw):]).strip() if p >= 0 else text
        units = []
        for piece, _ in pieces(rest, []):
            units += word_units(ln, piece, SIZES["M"])
        units = merge_punct(units)
        self.rows = plan_rows(ln, units, dw) if ln.get("rows") else greedy_rows(units)
        self.key_u = None

    # ---- placement (after the exits are known: the chin of every framing the block meets) -------------------------------------
    def place(self, matte, warn):
        R = self.R
        t_gone = self.t_out + (4 if self.kick else 2) * F1     # its last drawn frame is before this
        chin = R.chin_during(self.t_in - 2 * F1, t_gone - 0.5 * F1)
        for br in R.broll:                                  # B-roll: zone C from y 870, 40 px under any face in the shot
            if br["from"] < t_gone and br["to"] > self.t_in - 2 * F1:
                chin = max(chin, 830.0, (br.get("face") or [0, 0, 0, 0])[3])
        top_min = chin + 40
        if top_min + SIZES["S"] * 0.95 > op.BOTTOM - STROKE:
            warn.append(f"ERROR line {self.id}: no room under the chin (y {chin:.0f} + 40 + one S row > 1620); reframe or change camera.chin")
            top_min = op.BOTTOM - STROKE - SIZES["S"] * 0.95
        x_lo, x_hi = op.SAFE_L, op.SAFE_RB
        if self.kick and self.ln.get("glitch"):            # room for the slice glitch's bands (-24 / +18 px) inside the margins
            x_lo, x_hi = x_lo - min(GLITCH), x_hi - max(GLITCH)
        if self.column:
            self.place_column(matte, warn)
            x_lo = max(x_lo, self.column["x1"] + 30)
            top_min = max(top_min, op.COL_Y)
        sub = self.ln.get("sub")
        sub_h = 0.0
        if sub:
            sub_h = op.SUB_CAP + 16
        self.top_lim = top_min                             # no ink above this, overshoots included (chin + 40)
        peak = {"pop": 1.22, "xlpop": 1.22, "unitpop": 1.22, "settle": 1.06, "number": 1.16 * 1.06}
        head = max([(peak.get(u.kind, 1.0) - 1) / 2 * u.h for u in self.rows[0].units] or [0.0]) if self.rows else 0.0
        self.top = top_min + head                          # the first row starts lower by its own overshoot, so it can pop
        self.layout_c(self.top, x_lo, x_hi, sub_h)
        small = [u.size for u in self.units if u.kind != "number" and u.size < SIZES["S"] - 0.5]
        if small:
            warn.append(f"line {self.id}: the block shrinks to {min(small):.0f} px to fit (below S {SIZES['S']}); split the line")
        if self.digits:                                     # the layout may have scaled the number: digit places at its size
            offs = op.char_offsets(self.num.text, self.num.size, "number", -0.04)
            for d, (c, dx, dy) in zip(self.digits, offs):
                d["dx"], d["dy"] = dx, dy
        if sub and self.rows:
            self.place_sub(sub)
        if self.behind:
            self.place_behind(matte, warn)
        if self.column:
            self.place_streak()
        self.chin = chin

    def layout_c(self, top_min, x_lo, x_hi, extra_h=0.0):
        rows = self.rows
        if not rows:
            self.box = (CX_C, top_min, CX_C, top_min)
            return
        lim = (x_hi - x_lo) - 2 * STROKE
        for r in rows:
            for _ in range(8):
                w = r.width()
                if w <= lim:
                    break
                r.scale(lim / w * 0.995)
        def total():
            return sum(r.height() for r in rows) + ROW_GAP * (len(rows) - 1) + extra_h
        avail = max(SIZES["S"] * 0.95, op.BOTTOM - STROKE - top_min)
        for _ in range(6):
            tt = total()
            if tt <= avail:
                break
            k = max(0.05, (avail - extra_h) / max(1.0, tt - extra_h) * 0.995)
            for r in rows:
                r.scale(k)
        n = len(rows)
        cx = (x_lo + x_hi) / 2
        y = top_min
        for i, r in enumerate(rows):
            w = r.width()
            off = STEP * (i - (n - 1) / 2) if n > 1 else 0.0
            left = min(max(cx + off - w / 2, x_lo + STROKE), x_hi - STROKE - w)
            r.place(left, y)
            y += r.height() + ROW_GAP
        for r in rows:                                     # a slide starts 30 % of its width outside the side margin (O4)
            for u in r.units:
                if u.kind == "slide":
                    u.x0 = op.SAFE_L - 0.3 * u.w + u.w / 2
        us = [u for r in rows for u in r.units]
        self.box = (min(u.x - u.w / 2 for u in us), min(u.y - u.h / 2 for u in us), max(u.x + u.w / 2 for u in us), max(u.y + u.h / 2 for u in us))

    def place_sub(self, sub):
        """O8: the English sub-word under the block, cap height fixed; only the tracking changes to reach the width of the
        row above (up to +15 % of the font size per gap); short = right-aligned; long = no extra tracking, right-aligned."""
        size = op.sub_size()
        last = self.rows[-1]
        if self.mv == "number":
            num_row = next(r for r in self.rows if any(u.kind == "number" for u in r.units))
            last = num_row if num_row is self.rows[-1] else last
        x0 = min(u.x - u.w / 2 for u in last.units); x1 = max(u.x + u.w / 2 for u in last.units)
        y_top = max(u.y + u.h / 2 for u in last.units) + 16
        target = x1 - x0
        nat = sprite(sub, size, "sub", 0.0)[1]
        tr = 0.0
        if nat < target and len(sub) > 1:
            lo, hi = 0.0, 0.15
            if sprite(sub, size, "sub", hi)[1] < target:
                tr = hi
            else:
                for _ in range(14):
                    mid = (lo + hi) / 2
                    if sprite(sub, size, "sub", round(mid, 4))[1] < target:
                        lo = mid
                    else:
                        hi = mid
                tr = round(lo, 4)
        img, w, h, _ = sprite(sub, size, "sub", tr)
        left = x1 - w
        left = max(left, op.SAFE_L + STROKE)
        right = left + w
        if right > right_lim(y_top, y_top + h) - STROKE:
            left -= right - (right_lim(y_top, y_top + h) - STROKE)
        cx, cy = left + w / 2, y_top + h / 2
        start = max(u.land() for u in last.units) if not self.digits else self.t_breath
        if self.ln.get("sub_at") is not None:
            start = snap(float(self.ln["sub_at"]))
        elif op.sub_ok(sub, self.ln["text"])[1] == "verse reference":
            # a verse reference types on as its chapter number lands (JOHN 21 under 约翰福音21章 starts with the 21)
            ch = (re.findall(r"\d+", sub) or [""])[0]
            if self.digits and ch == self.num.text:
                start = self.digits[-1]["t0"] + 2 * F1
            else:
                hit = [u for u in self.units if ch and ch in u.text]
                if hit:
                    start = hit[0].land()
        offs = op.char_offsets(sub, size, "sub", tr)
        n = len(offs)
        per = 1 if n <= 6 else (2 if n <= 12 else 3)       # one letter a frame up to 6, then two; never longer than 6 frames
        for k, (c, dx, dy) in enumerate(offs):
            self.letters.append({"c": c, "x": cx + dx, "y": cy + dy, "t0": start + (k // per) * F1,
                                 "spr": sprite(c, size, "sub")})
        self.sub_box = (left, y_top, left + w, y_top + h)
        self.ev.append((start + 6 * F1, "sub-word (typed)"))
        self.box = (min(self.box[0], left), self.box[1], max(self.box[2], left + w), max(self.box[3], y_top + h))

    def place_behind(self, matte, warn):
        """Zone A / O5: each character (group) beside the head, behind it (Gold Stack's rule, owner 2026-11-02 "as big as
        possible"): at its target size, as close to the head as lets at most 40 % of it go behind the head, inside x 86..994,
        top >= 200; it shrinks only while less than 35 % of a character would show on some frame (matte every 2nd frame)."""
        R = self.R
        t_hold0 = min(p["t0"] for p in self.behind) + 4 * F1
        samples = list(np.arange(t_hold0, self.t_out + 2 * F1 + 1e-6, 2 * F1))      # every 2nd frame it is on screen
        ms = [matte.at(t) for t in samples] if matte else []
        ms = [m for m in ms if m is not None]
        hd = matte.head(t_hold0) if matte else None
        head_top = hd[0] if hd else R.out_y(R.head_top, R.state(t_hold0, True)[1])
        chin = R.chin_out(R.state(t_hold0, True)[1])
        kind = self.behind[0]["kind"]
        hds = [h for h in (matte.head(t) for t in samples[::3]) if h] if matte else []
        hc = float(np.median([(h[1] + h[2]) / 2 for h in hds])) if hds else (CX_C if not matte else None)
        # as big as possible (owner 2026-11-02, as Gold Stack): start at the target, shrink only while a character shows < 35 %
        sizes = (list(range(op.SIZES["L"], 99, -10)) if kind == "top" else list(range(op.TILT, 139, -10)))
        best = None
        for size in sizes:
            parts, ok, worst = [], True, 1.0
            for p in self.behind:
                img, iw, ih, _ = sprite(p["text"], size, p["colour"])
                rimg = prep(img, 1.0, p["rot"])
                ab = Image.new("L", rimg.size); ab.paste(rimg.getchannel("A").point(lambda v: 255 if v > 200 else 0))
                bb = ab.getbbox() or (0, 0, rimg.width, rimg.height)
                rw, rh = bb[2] - bb[0], bb[3] - bb[1]
                ccx = (bb[0] + bb[2]) / 2 - rimg.width / 2   # ink centre offset inside the rotated image
                ccy = (bb[1] + bb[3]) / 2 - rimg.height / 2
                side = p["side"]
                if side == -1 and hd:                       # one group: the side with more room
                    side = 0 if hd[1] - op.SAFE_L > op.SAFE_R - hd[2] else 1
                pk = max(p["curve"])                         # room for the pop's overshoot (O2 122 %, O5 106 %) inside the margins
                y_hi = max((op.TOP_A if kind == "top" else op.TOP) + rh / 2, op.TOP + STROKE + pk * rh / 2) + 2
                if kind == "top":
                    cys = [y_hi]                             # zone A: the top band
                else:                                        # O5: beside the head, from as high as allowed down the side
                    y_lo = max(y_hi, head_top + 0.25 * (chin - head_top))
                    cys = sorted({y_hi, *np.arange(y_hi, y_lo + 1, 20.0).tolist(), y_lo})
                found = None
                for cy in cys:
                    xl, xr = op.SAFE_L + STROKE + pk * rw / 2, right_lim(cy - pk * rh / 2, cy + pk * rh / 2) - STROKE - pk * rw / 2
                    if hc is not None and side == 1:         # (the right side's 4 px grid starts at the head's centre)
                        xl = max(xl, hc)
                    xs = np.arange(xl, xr + 1, 4.0)
                    if hc is not None:                       # each side's whole ink stays on its side of the head: never 改悔 / 是而
                        xs = xs[xs <= hc - pk * rw / 2] if side != 1 else xs[xs >= hc + pk * rw / 2]
                    if not len(xs):
                        continue
                    if side == 1:
                        xs = xs[::-1]
                    good, gv = None, 0.0
                    for x in xs:                             # from the margin toward the head: the closest that stays >= aim
                        v = min([visible(m, rimg, x - ccx, cy - ccy) for m in ms] or [1.0])
                        if v >= VIS_AIM:
                            good, gv = x, v
                        else:
                            break
                    if good is None:
                        v0 = min([visible(m, rimg, xs[0] - ccx, cy - ccy) for m in ms] or [1.0])
                        if found is None or v0 > found[2]:
                            found = (xs[0], cy, v0, False)
                        continue
                    found = (good, cy, gv, True)
                    break
                if found is None:                            # no room on its side of the head at this size
                    ok = False; worst = 0.0
                    break
                good, cy, gv, hit = found
                touch = max([1 - visible(m, rimg, good - ccx, cy - ccy) for m in ms] or [1.0])
                if gv < VIS_MIN:
                    ok = False
                worst = min(worst, gv)
                parts.append(dict(p, size=size, x=float(good - ccx), y=float(cy - ccy), ix=float(good), iy=float(cy), vis=round(gv, 3),
                                  w=rw, h=rh, touch=touch, ink=(good - rw / 2, cy - rh / 2, good + rw / 2, cy + rh / 2)))
            if len(parts) < len(self.behind):
                continue
            if best is None or worst > best[1]:
                best = (parts, worst)
            if ok:
                best = (parts, worst)
                break
        if best is None:
            warn.append(f"ERROR line {self.id}: no room beside the head for the characters behind it; use zone C")
            self.behind = []
            return
        parts, worst = best
        thin = [p["text"] for p in parts if p["touch"] < TOUCH_MIN]
        if thin:                                             # hardly behind the head at all: zone C reads better
            self.fallback = f"'{'/'.join(thin)}' would hardly meet the head (less than {TOUCH_MIN:.0%} behind it)"
            return
        if worst < VIS_MIN:
            warn.append(f"line {self.id}: a character behind the head shows only {worst:.0%} (at least 35 %); choose another line or zone C")
        target = op.SIZES["L"] if kind == "top" else op.TILT
        if parts[0]["size"] < target:
            warn.append(f"line {self.id}: the {'top band' if kind == 'top' else 'tilted pair'} shrank to {parts[0]['size']} px "
                        f"(target {target}) so every character shows at least 35 %")
        for p in parts:
            img = sprite(p["text"], p["size"], p["colour"])[0]
            p["img"] = img
        self.behind = parts
        self.behind_report = [{"text": p["text"], "size": p["size"], "ink_box": [round(v) for v in p["ink"]], "visible_planned": p["vis"]} for p in parts]

    def place_column(self, matte, warn):
        """Zone D: x 86-236 from y 290, behind the head and hair (person matte), as big as possible (owner 2026-11-02, as
        Gold Stack): 136 px, shrinking only while less than 35 % of one of its characters shows on some frame (every 2nd frame
        from its ghost to the end). The matte keeps the face in front."""
        c = self.column
        R = self.R
        size = c["size"]
        ts_ = list(np.arange(c["t0"] + 4 * F1, R.dur, 2 * F1))
        ms = [m for m in ((matte.at(t) for t in ts_) if matte else []) if m is not None]
        x0 = op.COL_X + STROKE
        worst = 1.0
        while True:
            img, w, h, _ = sprite(c["text"], size, "white", vertical=True)
            chars = self.column_chars(c["text"], size, x0 + w / 2, op.COL_Y + h / 2)
            worst = min([visible(m, ci, cx, cy) for m in ms for ci, cx, cy, _ in chars] or [1.0])
            if worst >= VIS_MIN or size <= 80:
                break
            size -= 4
        if worst < VIS_MIN:
            warn.append(f"line {self.id}: a glow column character shows only {worst:.0%} (at least 35 %)")
        if size != c["size"]:
            warn.append(f"line {self.id}: the glow column shrank to {size} px (target {c['size']}) so every character shows at least 35 %")
        face_l = None
        y0 = op.COL_Y
        if y0 + h > op.BOTTOM - STROKE:
            k = (op.BOTTOM - STROKE - y0) / h
            size = int(size * k); img, w, h, _ = sprite(c["text"], size, "white", vertical=True)
        c.update(size=size, img=img, w=w, h=h, x=x0 + w / 2, y=y0 + h / 2, x1=x0 + w, y1=y0 + h, face_l=face_l)
        m = op.mask(c["text"], size, "noto", None, True)[0]
        pad = 40
        big = Image.new("L", (m.width + 2 * pad, m.height + 2 * pad)); big.paste(m.filter(ImageFilter.MaxFilter(5)), (pad, pad))
        bb = op.mask(c["text"], size, "noto", None, True)[1]
        cx_m, cy_m = (bb[0] + bb[2]) / 2 + pad, (bb[1] + bb[3]) / 2 + pad
        left = (x0 + w / 2) - cx_m                             # where the glow image's left edge lands on the frame
        ramp = np.clip((left + np.arange(big.width) - op.SAFE_L) / 24.0, 0, 1)[None, :]   # the glow fades to nothing at x 86

        def glow_img(col, r, gain):
            g = Image.new("RGBA", big.size, col + (0,))
            a = np.asarray(big.filter(ImageFilter.GaussianBlur(r)), np.float32) * gain * ramp
            g.putalpha(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
            return g, cx_m, cy_m
        c["bloom"] = glow_img(op.BLOOM, 30, 1.6)                # #EAFFB0, blur 30 px
        c["wide"] = glow_img(op.HALO, 60, 1.2)                  # the lime halo around it
        c["chars"] = self.column_chars(c["text"], size, c["x"], c["y"])
        self.column_report = {"text": c["text"], "size": size, "ink_box": [round(x0), round(y0), round(x0 + w), round(y0 + h)],
                              "visible_planned": round(worst, 3)}

    @staticmethod
    def column_chars(text, size, cx, cy):
        """Each column character as (sprite, x, y, char) at the place the whole column puts it (for its visibility)."""
        return [(sprite(ch, size, "white")[0], cx + dx, cy + dy, ch) for ch, dx, dy in op.char_offsets(text, size, "white", None, True)]

    def place_streak(self):
        """The light streak along the chest line, under the text, ending at x <= 950."""
        y = self.top + 30
        s = Image.new("L", (W // 2, 64), 0)
        ImageDraw.Draw(s).ellipse((0, 18, W // 2 - 1, 46), fill=255)
        s = s.filter(ImageFilter.GaussianBlur(5))
        self.streak = {"y": y, "core": s}

    # ---- exits ---------------------------------------------------------------------------------------------------------------
    def tf(self, t):
        """(scale, alpha, mode, f): the block's exit transform."""
        if t <= self.t_out:
            return 1.0, 1.0, "hold", 0.0
        f = round((t - self.t_out) * FPS, 4)
        if self.kick:
            if f >= 4:
                return 0.0, 0.0, "gone", f
            return table(f, KICK), 1.0, "kick", f
        if f >= 2:
            return 0.0, 0.0, "gone", f
        return 1 - 0.10 * f / 2, 1 - f / 2, "plain", f

    def kick_cap(self):
        """The largest block scale (from its top-centre) that keeps every unit inside the margins (kick f0, f1, f3)."""
        if not hasattr(self, "_kcap"):
            ox, oy = (self.box[0] + self.box[2]) / 2, self.box[1]
            k = 9.9
            items = [(u.x, u.y, u.w, u.h) for u in self.units] + [(l["x"], l["y"], l["spr"][1], l["spr"][2]) for l in self.letters]
            for x, y, w, h in items:
                for s in (1.08,):
                    y0, y1 = oy + (y - h / 2 - oy) * s, oy + (y + h / 2 - oy) * s
                    rl = right_lim(y0, y1)
                    for edge, o, lim in ((x - w / 2, ox, op.SAFE_L + STROKE), (x + w / 2, ox, rl - STROKE), (y + h / 2, oy, op.BOTTOM - STROKE)):
                        if abs(edge - o) > 1e-6 and (lim - o) / (edge - o) > 0:
                            k = min(k, (lim - o) / (edge - o))
            self._kcap = max(1.0, k)
        return self._kcap

    # ---- drawing -------------------------------------------------------------------------------------------------------------
    def unit_draw(self, fr, u, t, sb, ab, o, clamp=True, mblur=0.0):
        f = (t - u.t0) * FPS
        if f < 0:
            return
        x, y = o[0] + (u.x - o[0]) * sb, o[1] + (u.y - o[1]) * sb
        s, a, blur = 1.0, 1.0, 0.0
        k = u.kind
        if k == "settle":
            s = keys(f, [0, 2], [1.06, 1.0])
        elif k == "rise":
            p = ease_out(min(1.0, f / 5)); y += 1.1 * u.h * (1 - p) * sb; a = p; blur = 8 * (1 - p)
        elif k in ("pop", "xlpop", "unitpop"):
            s = table(f, POP)
        elif k == "slide":
            p = 1 - (1 - min(1.0, f / 6)) ** 5
            x = o[0] + ((u.x0 + (u.x - u.x0) * p) - o[0]) * sb
        if clamp and s > 1.0:
            s = min(s, max(1.0, fit_k(x, y, u.w * sb, u.h * sb, s, self.top_lim)))     # the overshoot stays inside the margins
        put(fr, u.img, x, y, s * sb, alpha=a * ab, blur=blur, mblur=mblur)

    def draw_digits(self, fr, t, sb, ab, o, clamp=True, mblur=0.0):
        u = self.num
        breath = 1.0
        fb = (t - self.t_breath) * FPS
        if 0 <= fb <= 12:
            breath = 1 + 0.06 * math.sin(math.pi * fb / 3) * (1 - fb / 12)
        cx, cy = o[0] + (u.x - o[0]) * sb, o[1] + (u.y - o[1]) * sb
        if clamp and breath > 1:
            breath = min(breath, max(1.0, fit_k(cx, cy, u.w * sb, u.h * sb, breath, self.top_lim)))
        for d in self.digits:
            f = (t - d["t0"]) * FPS
            if f < 0:
                continue
            s = keys(f, [0, 2], [1.16, 1.0])
            x, y = cx + d["dx"] * breath * sb, cy + d["dy"] * breath * sb
            img, w, h, _ = sprite(d["c"], u.size, "number")
            if clamp and s > 1:
                s = min(s, max(1.0, fit_k(x, y, w * sb * breath, h * sb * breath, s, self.top_lim)))
            put(fr, img, x, y, s * breath * sb, alpha=ab, mblur=mblur)

    def draw_letters(self, fr, t, sb, ab, o, clamp=True, mblur=0.0):
        for l in self.letters:
            f = (t - l["t0"]) * FPS
            if f < 0:
                continue
            s = keys(f, [0, 2], [1.15, 1.0])
            x, y = o[0] + (l["x"] - o[0]) * sb, o[1] + (l["y"] - o[1]) * sb
            img, w, h, _ = l["spr"]
            if clamp and s > 1:
                s = min(s, max(1.0, fit_k(x, y, w * sb, h * sb, s, self.top_lim)))
            put(fr, img, x, y, s * sb, alpha=ab, mblur=mblur)

    def draw_front(self, fr, t):
        """Zone C rows, the number, the sub-word (in front of the speaker)."""
        sb, ab, mode, f = self.tf(t)
        if ab <= 0.01:
            return
        if mode == "kick":
            o = ((self.box[0] + self.box[2]) / 2, self.box[1])       # from the block's top-centre (grows down, away from the face)
            burst = int(f) == 2
            if not burst:
                sb = min(sb, self.kick_cap())
            if int(f) == 0 and self.ln.get("glitch"):
                return self.draw_glitch(fr, t)
            mb = 6.0 if burst else 0.0
            self._draw_c(fr, t, sb, ab, o, clamp=not burst, mblur=mb)
            return
        o = ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)
        self._draw_c(fr, t, sb, ab, o)

    def _draw_c(self, fr, t, sb, ab, o, clamp=True, mblur=0.0):
        for u in self.units:
            if u.kind == "number":
                self.draw_digits(fr, t, sb, ab, o, clamp, mblur)
            else:
                self.unit_draw(fr, u, t, sb, ab, o, clamp, mblur)
        if self.letters:
            self.draw_letters(fr, t, sb, ab, o, clamp, mblur)

    def draw_glitch(self, fr, t):
        """O10: f0 of the Kick Exit: the block cut into 3 horizontal bands, offset -24 / +18 / -12 px (less when a band
        would leave the margins), no colour split."""
        layer = Image.new("RGBA", (W, H))
        o = ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)
        self._draw_c(layer, self.t_out, 1.0, 1.0, o)        # the block as it stood, cut into bands
        bb = layer.getbbox()
        if not bb:
            return
        y0, y1 = bb[1], bb[3]
        hs = (y1 - y0) / 3
        x0i, x1i = self.box[0], self.box[2]
        for k, dx in enumerate(GLITCH):
            a, b = int(y0 + k * hs), (int(y0 + (k + 1) * hs) if k < 2 else y1)
            rl = right_lim(a, b)
            dx = int(max(dx, min(0, op.SAFE_L + STROKE - x0i)) if dx < 0 else min(dx, max(0, rl - STROKE - x1i)))
            if dx >= 0:
                band = layer.crop((0, a, W - dx, b)); fr.alpha_composite(band, (dx, a))
            else:
                band = layer.crop((-dx, a, W, b)); fr.alpha_composite(band, (0, a))
        self.glitched = True

    def draw_behind(self, fr, t, person=None, meas=None):
        """Zone A / O5 characters (drawn before the speaker goes back on top). meas: list for the per-frame visibility."""
        if not self.behind:
            return
        sb, ab, mode, f = self.tf(t)
        if ab <= 0.01:
            return
        for p in self.behind:
            fp = (t - p["t0"]) * FPS
            if fp < 0:
                continue
            s = table(fp, p["curve"])
            a_ = ab
            if mode == "kick":                              # behind the head a kick is a plain exit: no burst toward the face
                k = s * (1 - 0.10 * min(1.0, f / 2)); a_ = max(0.0, 1 - f / 2)
            else:
                k = s * sb
            if k > 1.0:                                      # the overshoot stays inside (room was kept for it when placed)
                k = min(k, max(1.0, fit_k(p["ix"], p["iy"], p["w"], p["h"], k)))
            if mode == "hold" and fp <= len(p["curve"]):
                p["peak"] = max(p.get("peak", 0.0), k)
            img = prep(p["img"], k, p["rot"], a_, 0.0, 0.0)
            if img is None:
                continue
            if meas is not None and person is not None and a_ >= 0.5:
                settled = mode == "hold" and fp >= len(p["curve"]) - 1
                meas.append((self.id, p["text"], visible(person, img, p["x"], p["y"]), settled))
            paste(fr, img, p["x"], p["y"])

    def draw_streak(self, fr, t):
        """O9 light streak f0-f10 (grows from the left edge to x <= 950), fading f10-f18."""
        if not self.column:
            return
        f = (t - self.column["t0"]) * FPS
        if f < 0 or f > 18:
            return
        p = ease_out(min(1.0, f / 10))
        a = 1.0 if f <= 10 else max(0.0, 1 - (f - 10) / 8)
        x1 = op.SAFE_L + (op.SAFE_RB - op.SAFE_L) * p
        x0 = max(-150.0, x1 - 900)
        width = max(4, int(x1 - x0))
        core = self.streak["core"].resize((width, 64), Image.BILINEAR)
        y = self.streak["y"]
        halo = Image.new("RGBA", (width + 120, 184), op.HALO + (0,))
        hm = Image.new("L", (width + 120, 184)); hm.paste(core, (60, 60))
        halo.putalpha(hm.filter(ImageFilter.GaussianBlur(28)).point(lambda v: int(min(255, v * 1.4) * 0.55 * a)))
        cimg = Image.new("RGBA", (width, 64), op.STREAK + (0,))
        cimg.putalpha(core.point(lambda v: int(v * 0.85 * a)))
        for im in (halo, cimg):                              # never past x 950 in the button band (y 1000-1700)
            left, top = (x0 + x1) / 2 - im.width / 2, y - im.height / 2
            xs_ = left + np.arange(im.width)[None, :]
            ys_ = top + np.arange(im.height)[:, None]
            band = (ys_ > op.BAND[0] - 24) & (ys_ < op.BAND[1])
            k_ = np.where(band, np.clip((op.SAFE_RB - STROKE - xs_) / 24.0, 0, 1), 1.0)
            al = np.asarray(im.getchannel("A"), np.float32) * k_
            im.putalpha(Image.fromarray(np.clip(al, 0, 255).astype(np.uint8)))
            paste(fr, im, (x0 + x1) / 2, y)
        if f < 4:                                            # the sparkle at the left edge
            sp = Image.new("L", (90, 90)); ImageDraw.Draw(sp).ellipse((30, 30, 60, 60), fill=255)
            sp = sp.filter(ImageFilter.GaussianBlur(9))
            s_img = Image.new("RGBA", (90, 90), op.STREAK + (0,)); s_img.putalpha(sp.point(lambda v: int(v * (1 - f / 4))))
            paste(fr, s_img, op.SAFE_L + 10, y)

    def draw_column(self, fr, t, person=None, meas=None):
        """O9, drawn before the speaker goes back on top (behind the head and hair). meas: per-frame visibility."""
        c = self.column
        if not c:
            return
        f = (t - c["t0"]) * FPS
        if f < 4:
            return
        if f < 8:
            a = 0.3 * (f - 4 + 1) / 4; g = 0.0
        elif f <= 10:
            a = 0.3 + 0.7 * (f - 7) / 3; g = (f - 7) / 3
        else:
            a = 1.0; g = max(0.25, 1 - 0.75 * min(1.0, (f - 10) / 8))
        if g > 0.01:
            for key, gain in (("wide", 0.55), ("bloom", 1.0)):
                img, cx_m, cy_m = c[key]
                gi = img.copy(); gi.putalpha(img.getchannel("A").point(lambda v: int(v * min(1.0, g * gain))))
                paste(fr, gi, c["x"] + (gi.width / 2 - cx_m), c["y"] + (gi.height / 2 - cy_m))
        put(fr, c["img"], c["x"], c["y"], 1.0, alpha=min(1.0, a), blur=0.0)
        if meas is not None and person is not None and f >= 18:
            for ci, cx, cy, ch in c["chars"]:
                meas.append((self.id, "column " + ch, visible(person, ci, cx, cy), True))


# ---- the timeline ----------------------------------------------------------------------------------------------------------
def timeline(plan, dur, joins=(), matte=None):
    """The plan's lines as blocks on one timeline; a block whose characters behind the head fall back to zone C is built
    again from its line (the whole timeline is rebuilt, so exits and sounds follow). Returns (cam, lines, blocks, warnings)."""
    over, fb_warn = {}, []
    for _ in range(len(plan.get("lines", [])) + 2):         # a block falls back at most once
        cam, lines, B, warn = _timeline(plan, dur, joins, matte, over)
        fb = [b for b in B if getattr(b, "fallback", None)]
        if not fb:
            break
        if all(b.i in over for b in fb):
            raise SystemExit(f"behind-the-head fallback did not settle: lines {[b.id for b in fb]}")
        for b in fb:
            kind = "tilted pair" if b.mv == "tilt" else "top band"
            ln2 = dict(b.ln, zone="C")
            if b.mv == "tilt":
                ln2.update(move=None, word=None)
            over[b.i] = ln2
            fb_warn.append(f"line {b.id}: {b.fallback}, so its {kind} falls back to zone C")
    return cam, lines, B, fb_warn + warn


def _timeline(plan, dur, joins=(), matte=None, over=None):
    """The plan's lines as blocks on one timeline: exits (each block gone before the next comes in and before a framing
    switch), push cuts, placement, and the sounds (one sounded moment per block). Returns (cam, lines, blocks, warnings)."""
    cam = Cam(plan, list(joins), dur)
    cam.broll = [b for b in (plan.get("broll") or []) if isinstance(b, dict) and "from" in b and "to" in b]
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    B = [Block((over or {}).get(i, ln), i, cam) for i, ln in enumerate(lines)]
    warn = []
    ms = Matte(matte, cam) if matte else None
    if ms:                                                      # behind the head needs a head in the shot, up in its band
        for i, b in enumerate(B):
            if not b.behind:
                continue
            kind = b.behind[0]["kind"]
            # the head must reach the middle of the band the characters sit in
            band_lo = op.TOP_A + 0.5 * 0.95 * op.SIZES["L"] if kind == "top" else op.TOP + 0.55 * 1.1 * op.TILT
            ts_ = np.arange(b.t_in + 4 * F1, b.ln["end"] + 0.35, 6 * F1)
            hs = [ms.head(t) for t in ts_]
            why = ("no head in the shot" if any(h is None for h in hs) else
                   "the head does not reach the band" if min(h[0] for h in hs) > band_lo else None)
            if why:
                ln2 = dict(b.ln, zone="C")
                if kind == "tilt":
                    ln2.update(move=None, word=None)
                B[i] = Block(ln2, i, cam)
                warn.append(f"line {b.id}: {why} at {b.ln['start']:.2f}s, so its {'top band' if kind == 'top' else 'tilted pair'} falls back to zone C")

    def exits():
        sw = cam.switches()
        for i, b in enumerate(B):
            nxt = B[i + 1].t_in if i + 1 < len(B) else None
            if nxt is None and dur - b.ln["end"] < 2.5 or b.column:
                b.t_out = dur + 1.0; b.kick = False             # the takeaway holds to the last frame
                continue
            ex = 4 if b.kick else 2
            t_out = b.ln["end"] + (1 * F1 if b.kick else 0.35)
            if nxt is not None:
                t_out = min(t_out, nxt - ex * F1)
            pushed = b.kick and b.ln.get("push")
            if not pushed:                                      # gone (1 frame early) before a framing switch it would straddle
                for s in sw:
                    if b.t_land - 2 * F1 <= s <= t_out + (ex + 1) * F1:
                        t_out = min(t_out, s - (ex + 1) * F1)
            b.t_out = snap(max(t_out, b.t_in + 6 * F1))
    exits()
    for b in B:
        if b.kick and b.ln.get("push"):
            if not cam.add_push(b.t_out):
                b.ln = dict(b.ln, push=False)
    if (plan.get("camera") or {}).get("hold_column", True):     # after the pushes, so the column's hold wins
        for b in B:
            if b.column:
                for f in cam.hold(b.column["t0"]):
                    cam.warn.append(f"{'push cut' if f[2] else 'framing switch'} at {f[0]:.2f}s skipped: the glow column holds the framing it starts in")
                    for pb in B:
                        if f[2] and pb.kick and pb.ln.get("push") and abs(pb.t_out - f[0]) < 1e-3:
                            pb.ln = dict(pb.ln, push=False)
    exits()
    if ms:
        ms.cache.clear()                                        # the camera's framings changed: sample the matte again
    for b in B:
        b.place(ms, warn)
    # sounds: one sounded moment per block
    first = min([t for _, evs in B[0].cands for t, *_ in evs] + [t for t, _ in B[0].quiet], default=None) if B else None
    # the opening push and block 1 are one moment only when block 1's first move peaks by f14 + 6 (0.65 s); else each is its own
    c1_alone = cam.c1 and (not B or (first is not None and first > C1_JOIN) or (first is None and B[0].ln["start"] > 1.0))
    for i, b in enumerate(B):
        incoming = None
        if i == 0 and cam.c1 and not c1_alone:
            incoming = ("open", [(2 * F1, "whoosh_zoom", -3, "C1 opening push")])
        elif i > 0 and B[i - 1].kick:
            pb = B[i - 1]
            what = f"line {pb.id}: kick exit bursts" + (" (push cut)" if pb.ln.get("push") else "")
            incoming = ("kick", [(pb.t_out + 2 * F1, "whoosh_fast", -2, what)])
        chosen = incoming or (b.cands[0] if b.cands else None)
        b.sound = chosen
        b.silent = [c[0] for c in b.cands if c is not chosen]
        b.sfx = list(chosen[1]) if chosen else []
        b.hits = [(t, chosen[0], i) for t, *_ in chosen[1]] if chosen else []
        # every designed move is a moment, sounded or not (one block = one moment; the incoming kick / push belongs to it)
        b.moves = sorted(set(b.hits + [(t, kind, i) for kind, evs in b.cands for t, *_ in evs] + [(t, k, i) for t, k in b.quiet]))
    if c1_alone and B:
        B[0].sfx = [(2 * F1, "whoosh_zoom", -3, "C1 opening push")] + B[0].sfx
        B[0].moves = sorted(B[0].moves + [(2 * F1, "open", -1)])
    for b in B:                                                 # a move must land before its block starts to leave
        for t, mv, _ in b.moves:
            if mv not in ("kick", "open") and t > b.t_out - 1 * F1:
                warn.append(f"line {b.id}: its {mv} lands {round((t - b.t_out) * FPS)} frames after its exit starts; give it more room")
    for b in B:
        if b.kick:
            b.ev += [(b.t_out, "kick (f0" + (" glitch)" if b.ln.get("glitch") else ")")), (b.t_out + 2 * F1, "kick (burst)")]
    warn += cam.warn
    return cam, lines, B, warn


def move_hits(plan, dur=None, joins=(), matte=None):
    """Every designed moment [(t, kind, group)], sounded or silent (group = block; a kick folds into the next block, the
    opening push into block 1 when it starts within 1 s), and the sound plan per line, from the same timeline the render
    uses (give the cut map's joins: framing switches move the exits). Returns (hits, warnings, sounds); a warning that
    starts with "ERROR" is an error."""
    lines = plan.get("lines", [])
    dur = dur or plan.get("duration") or max([ln.get("end", 0) for ln in lines] + [0])
    _, _, B, warn = timeline(plan, dur, joins, matte)
    hits = sorted(h for b in B for h in b.moves if 0 <= h[0] <= dur)
    sounds = [{"line": b.id, "sound": (f"{b.sound[0]}: " + ", ".join(s for _, s, *_ in b.sound[1])) if b.sound else "none",
               "silent": ", ".join(b.silent)} for b in B]
    return hits, warn, sounds


def video_dur(path, fallback):
    probe = os.path.join(os.path.dirname(op.cc.FFMPEG), "ffprobe") if os.path.dirname(op.cc.FFMPEG) else "ffprobe"
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
    ap.add_argument("--map", default=None, help="cut map (tight.cutmap.json / joins.cutmap.json): pause cuts for the wide / tight switch")
    ap.add_argument("--matte", default=None, help="matte.mp4 from poster-kinetic matte.py (same framing): needed for zone A, tilt and column")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop"); ap.add_argument("--focus", type=float, default=0.5)
    ap.add_argument("--to", type=float, default=None)
    ap.add_argument("--no-text", action="store_true"); ap.add_argument("--phone", action="store_true")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    t_start = time.time()
    plan = load(a.plan)
    err, warn = op.check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    dur = full = video_dur(a.video, op.probe(a.video)["duration"])
    if a.to:
        dur = min(dur, a.to)
    joins = []
    if a.map and os.path.isfile(a.map):
        segs = load(a.map).get("segments") or []
        joins = [float(s[2]) for s in segs[1:] if len(s) >= 3]
    hits, hw, sounds = move_hits(plan, full, joins)
    err, warn = op.check(plan, hits)
    err += [w for w in hw if w.startswith("ERROR")]; warn += [w for w in hw if not w.startswith("ERROR")]
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    matte = a.matte if a.matte and os.path.isfile(a.matte) else None
    needs = any((ln.get("zone") == "A" or ln.get("move") in ("tilt", "column")) for ln in plan.get("lines", []))
    if needs and not matte:
        report(tool="render", ok=False, errors=["zone A, move tilt and move column need --matte (poster-kinetic matte.py on the same clip)"], warnings=warn)
        sys.exit(1)
    if matte:                                               # a matte shorter than the clip would leave the end uncut
        md = video_dur(matte, 1e9)
        if md + 0.5 * F1 < dur:
            report(tool="render", ok=False, errors=[f"matte.mp4 is shorter than the clip ({md:.2f}s vs {dur:.2f}s): make it again from the same clip"], warnings=warn)
            sys.exit(1)
    cam, lines, B, tw = timeline(plan, full, joins, matte)
    terr = [w for w in tw if w.startswith("ERROR")]
    if terr:
        report(tool="render", ok=False, errors=terr, warnings=warn); sys.exit(1)
    warn += [w for w in tw if w not in warn]
    if any("falls back to zone C" in w for w in tw):          # the matte changed the plan's moves: check the pacing again
        hits2 = sorted(h for b in B for h in b.moves if 0 <= h[0] <= full)
        e2, _ = op.check(plan, hits2)
        warn += [f"after the zone C fallback: {x}" for x in e2 if x not in err]
        sounds = [{"line": b.id, "sound": (f"{b.sound[0]}: " + ", ".join(s_ for _, s_, *_ in b.sound[1])) if b.sound else "none",
                   "silent": ", ".join(b.silent)} for b in B]
    if not cam.chin_given:
        warn.append("camera chin not set: zone C assumes the chin at y 864; measure it on 3 frames per shot and set plan camera.chin")
    behind = [b for b in B if b.behind or b.column]
    mdec = None
    if behind:
        mdec = subprocess.Popen([op.cc.FFMPEG, "-hide_banner", "-loglevel", "error", "-t", f"{dur:.3f}", "-i", matte, "-vf", f"scale={W}:{H},fps={FPS}",
                                 "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    if a.frame == "crop":
        vf, vflag = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,setsar=1,fps={FPS}", "-vf"
    else:
        vf, vflag = (f"[0:v]split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
                     f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"), "-filter_complex"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = ["-t", f"{dur:.3f}"]; FF = op.cc.FFMPEG
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FF, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    dec = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", *tl, "-i", a.video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    # every drawn frame is kept (no -shortest), so a --no-text clean.mp4 has exactly the edit's frame count
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
    meas = []
    zooms = []
    matte_short = False
    while True:
        buf = qin.get()
        if buf is None:
            break
        t = n / FPS
        src = Image.frombytes("RGB", (W, H), buf)
        small = np.asarray(src.convert("L").resize((135, 240), Image.BILINEAR), np.float32)
        cut = prev_small is not None and float(np.abs(small - prev_small).mean()) > 9.0
        prev_small = small
        cam.see(t, cut)
        z0, z1, p = cam.state(t)
        zooms.append(round(z0 + (z1 - z0) * p, 4))
        fr = cam.transform(src, t).convert("RGBA")
        mbuf = mdec.stdout.read(W * H) if mdec else b""
        if not a.no_text:
            for b in B:                                      # the O9 light streak is part of the column: not in clean.mp4
                if b.column:
                    b.draw_streak(fr, t)
            live = [b for b in behind if min([p_["t0"] for p_ in b.behind] + ([b.column["t0"]] if b.column else [])) - 0.01 <= t <= b.t_out + 5 * F1]
            if live and len(mbuf) != W * H:
                matte_short = True
            if live and len(mbuf) == W * H:
                # the speaker back on top; 2 px wider so the soft hair edge covers the letters behind it
                person = cam.transform(Image.frombytes("L", (W, H), mbuf), t).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.2))
                pq = np.asarray(person.resize((W // Matte.Q, H // Matte.Q), Image.BILINEAR), np.float32) / 255
                pic = fr.copy()
                for b in live:
                    b.draw_behind(fr, t, pq, meas)
                    b.draw_column(fr, t, pq, meas)
                fr = Image.composite(pic, fr, person)
            for b in B:
                if b.t_in - 0.01 <= t <= b.t_out + 5 * F1:
                    b.draw_front(fr, t)
        qout.put(np.asarray(fr.convert("RGB")).tobytes())
        n += 1
    qout.put(None); thw.join(); enc.stdin.close(); enc.wait(); dec.wait()
    if mdec:
        mdec.stdout.close(); mdec.wait()
    base = os.path.splitext(a.out)[0]
    out = {"tool": "render", "ok": True, "out": a.out, "frames": n, "seconds": round(n / FPS, 2), "render_seconds": round(time.time() - t_start, 1),
           "camera": {"on": cam.on, "opening_push": cam.c1, "framing_switches": len(cam.active) - 1,
                      "pushes": [round(f[0], 2) for f in cam.frames if f[2]],
                      "chin_wide": round(cam.chin_out(1.0)), "chin_tight": round(cam.chin_out(TIGHT))}}
    if not a.no_text:
        def st(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base + ".srt", "w", encoding="utf-8") as fh:
            for i, ln in enumerate(lines):
                end = ln["end"] + 0.3 if i + 1 == len(lines) else min(ln["end"] + 0.3, lines[i + 1]["start"])
                fh.write(f"{i + 1}\n{st(ln['start'])} --> {st(end)}\n{display(ln['text'])}\n\n")
        ev, sfx = [], []
        for b in B:
            ev.append({"t": b.t_in + 0.25, "kind": "caption", "line": b.id})
            ev += [{"t": tt, "kind": k, "line": b.id} for tt, k in b.ev]
            for tt, snd, db, what in b.sfx:
                e = {"frame": int(round(tt * FPS)), "sound": snd, "what": what}
                if db:
                    e["db"] = db
                sfx.append(e)
        save(base + ".pk.json", {"video": os.path.abspath(a.out), "events": sorted([e for e in ev if 0 <= e["t"] < dur], key=lambda e: e["t"]), "warnings": warn})
        save(base + ".sfx-events.json", {"fps": FPS, "events": sorted([e for e in sfx if 0 <= e["frame"] < n], key=lambda e: e["frame"]),
                                          "note": "one sounded moment per block, loudest on its frame (Orbit Pop sheet p.11); none on caption words or plain cuts"})
        pc = base + ".plan.json"                             # the plan this render used, next to it (never over a plan.json)
        if os.path.abspath(a.plan) != os.path.abspath(pc):
            shutil.copyfile(a.plan, pc)
        vis, vis_all = {}, {}
        for lid, txt, v, settled in meas:
            k_ = f"line {lid} {txt}"
            vis_all[k_] = min(vis_all.get(k_, 1.0), v)
            if settled:
                vis[k_] = min(vis.get(k_, 1.0), v)
        out.update(srt=base + ".srt", sfx_events=base + ".sfx-events.json", lines=len(B), sounds=sounds,
                   behind={f"line {b.id}": b.behind_report for b in B if b.behind},
                   behind_visible_min={k: round(v, 3) for k, v in vis.items()},
                   behind_visible_min_all_frames={k: round(v, 3) for k, v in vis_all.items()},
                   behind_pop_peak={f"line {b.id} {p['text']}": round(p.get("peak", 0.0), 3) for b in B for p in b.behind},
                   column={f"line {b.id}": b.column_report for b in B if b.column},
                   blocks=[{"line": b.id, "in": round(b.t_in, 2), "out": round(b.t_out, 2), "chin": round(b.chin), "top": round(b.top),
                            "box": [round(v) for v in b.box], "exit": "kick" if b.kick else "plain"} for b in B],
                   kick_bursts=[int(round((b.t_out + 2 * F1) * FPS)) for b in B if b.kick])
    save(base + ".zoom.json", {"fps": FPS, "zoom": zooms})
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
    if matte_short:
        out.update(ok=False, errors=["the matte ran out before the clip did: the end is not cut out; make matte.mp4 again"])
    report(**out)


if __name__ == "__main__":
    main()
