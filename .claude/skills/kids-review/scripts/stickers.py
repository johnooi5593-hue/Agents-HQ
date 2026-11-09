"""Step 8 of the kids-review skill. Cute kids' stickers (QQ-style emoji faces + doodles) and motion graphics popped onto a
finished caption render (built on the owner-approved 1107 Children review v3). Size-agnostic: one plan renders on
1080x1920 (9:16) and 1920x1080 (16:9) alike. Every sticker is drawn here with PIL / numpy (supersampled), no emoji font,
no downloaded art, so there is no licence question.

USAGE
    python stickers.py plan   <stickers.json> [--aspect 9x16|16x9] [--faces faces916.json] [--faces faces16.json]
        Checks the plan for both sizes (or one): unknown kinds, stickers off the frame, stickers on an "avoid" box
        (faces, caption cards), more than "max_on_screen" (default 4) on screen outside the bursts, the same kind twice
        in a row at the cuts. Prints a timeline and one JSON line.
        --faces (t202, repeatable): a faces.json from tools/vision/faces.py; every face range is added to the avoid
        list for the aspect of the video it was detected on (its "size"), on top of the typed boxes.
    python stickers.py render <in.mp4> <stickers.json> <out.mp4> [--sfx-events in.json out.json] [--from S] [--to S]
                              [--task <board id> --pct 50:85] [--faces faces.json ...]
        Streams the frames through ffmpeg (rawvideo pipe), draws the stickers, writes libx264 crf 16 (yuv420p), copies
        the audio stream. --from/--to render only that part (quick look; times stay the plan's times).
        --sfx-events merges the video's own sfx events (in.json) with one sound per sticker pop (its first frame) into
        out.json for the sfx skill's place.py. A sticker sound within 2 frames of another sound is dropped (warned).
        --task / --pct (or env HQ_TASK / HQ_PCT) report the real frame count to the HQ board.
    python stickers.py sfx    <video> <stickers.json> <in.json> <out.json>
        Only the sound merge of render --sfx-events (no picture work), e.g. after changing a sticker's sfx or sfx_adjust.
    python stickers.py sheet  <video> <out.jpg> [--every 1] [--at t1,t2,...] [--cols 8] [--width 240] [--boxes stickers.json]
        A contact sheet (one frame every --every seconds, or at --at times) to look at with the Read tool.
        --boxes draws the plan's avoid boxes that are live at each time (for planning on the clean video).
    python stickers.py swatch <out.png>      every sticker kind on one page.

THE PLAN (stickers.json)
    {
      "max_on_screen": 4,
      "avoid": [ {"start": 2.35, "end": 3.95, "what": "caption card",
                  "box": {"9x16": [0.06, 0.60, 0.94, 0.73], "16x9": [0.25, 0.66, 0.75, 0.84]}} ],
      "sfx_adjust": [ {"frame": 989, "sound": "chime", "db": -5, "why": "masked by the voice"} ],   # change / nudge the video's own events
      "stickers": [
        {"t": 0.15, "dur": 2.0, "kind": "face_star", "pos": {"9x16": [0.80, 0.16], "16x9": [0.88, 0.22]},
         "size": 0.22, "rot": -8, "group": "hook", "sfx": "pop", "sfx_db": 1, "what": "hook: star eyes"},
        {"t": 8.4, "dur": 1.2, "kind": "confetti", "pos": [0.5, 0.9], "count": 40, "clip": {"9x16": [0, 0.72, 1, 1]}}
      ]
    }
    t / dur      seconds on the video's timeline (dur includes the pop-in and pop-out).
    pos          [x, y] centre as FRACTIONS of the frame, or {"9x16": [x, y], "16x9": [x, y]} (a key that is missing
                 falls back to "default", then to the first entry). Aspect key = "9x16" when H > W, "16x9" when W > H.
    size         art size as a fraction of the frame's SHORT side (1080 on both sizes), or a per-aspect dict.
    kind         face_smile face_laugh face_star face_heart face_wink face_wow face_wave star heart sparkle rainbow
                 cloud sun note thumbs vhand camera question squiggle confetti
                 v3: bubble (text, style round|shout, tail bl|br|tl|tr) word (text) twinkle balloon
                     trail (to, count, item, colors, bend) frame (box, arm) arrow (to, bend, text, label_pos, label_size)
                     underline (width) wipe (dir, cell, stars: a shot transition, t = cut - dur/2, sfx_offset = dur/2)
    sfx_offset   seconds after t for the sticker's sound (the wipe's middle frame).
    clip         (sprites too) only drawn inside this box; the checks use the clipped box.
    color        star / heart / note / question / squiggle / sparkle: pink rose light yellow mint sky purple orange or #hex
    motion       pop (default: overshoot in, wobble, pop out), float (rises and sways, fades; default for heart, note),
                 wave (big rocking, default for face_wave), bounce (hops while it holds)
    rot          base rotation in degrees (positive = counter-clockwise). rise: float height (short-side fraction, 0.22).
    group        any name; stickers whose group starts with "burst" don't count towards max_on_screen.
    sfx          a sound category or name from .claude/skills/sfx/library (pop, chime, shutter ...), or null for none.
                 Default: "pop" for every sticker except confetti. sfx_db nudges it (default -2; pops sit ~8 dB under
                 the main impact hits at -2 -> about 10 dB under; +1 -> about 7 dB under).
    confetti     count (36), speed (1.0), spread [deg_min, deg_max] (default [-150, -30], 0 = right, -90 = up),
                 clip box: particles are only drawn inside it (keeps them off faces).
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import cv2

SS = 3                                    # supersampling of the sticker art
FF = os.environ.get('FFMPEG', 'ffmpeg')
NOWIN = 0x08000000 if os.name == 'nt' else 0
IN_T, OUT_T = 0.34, 0.22                  # pop-in and pop-out seconds

PALETTE = {'pink': '#FF7AC8', 'rose': '#F0347F', 'light': '#FFD3EA', 'yellow': '#FFE45C', 'mint': '#7BF7C8',
           'sky': '#7CC8FF', 'purple': '#B68CFF', 'orange': '#FFA24C', 'red': '#FF4D6D', 'white': '#FFFFFF'}
KINDS = ['face_smile', 'face_laugh', 'face_star', 'face_heart', 'face_wink', 'face_wow', 'face_wave', 'star', 'heart',
         'sparkle', 'rainbow', 'cloud', 'sun', 'note', 'thumbs', 'vhand', 'camera', 'question', 'squiggle', 'confetti',
         'bubble', 'word', 'twinkle', 'balloon', 'trail', 'frame', 'arrow', 'wipe', 'underline']
LIVE = ('trail', 'frame', 'arrow', 'wipe', 'underline')
MOTION_DEFAULT = {'heart': 'float', 'note': 'float', 'face_wave': 'wave', 'bubble': 'shake', 'word': 'shake',
                  'twinkle': 'blink', 'balloon': 'rise'}
INK = '#4A2A12'


def out(**kw):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(json.dumps(kw, ensure_ascii=False))


def rgb(c):
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    c = PALETTE.get(c, c).lstrip('#')
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def light(c, t=0.45):
    return mix(c, '#FFFFFF', t)


def dark(c, t=0.3):
    return mix(c, '#000000', t)


# ---------------------------------------------------------------- drawing ---------------------------------------------
class Art:
    """A square art box of S px (drawn at SS x) inside a canvas 1.5 S wide, so the outline and shadow fit."""

    def __init__(self, S):
        self.A = int(round(S)) * SS
        self.C = int(round(S * 1.5)) * SS
        self.o = (self.C - self.A) / 2
        self.img = np.zeros((self.C, self.C, 4), np.float32)          # straight RGBA 0..1
        yy, xx = np.mgrid[0:self.C, 0:self.C].astype(np.float32)
        self.ux = (xx - self.o) / self.A; self.uy = (yy - self.o) / self.A   # unit coordinates of every pixel

    def p(self, x, y):
        return (self.o + x * self.A, self.o + y * self.A)

    def bx(self, x0, y0, x1, y1):
        return [*self.p(x0, y0), *self.p(x1, y1)]

    def L(self, v):
        return max(1, int(round(v * self.A)))

    def new(self):
        m = Image.new('L', (self.C, self.C), 0)
        return m, ImageDraw.Draw(m)

    # masks (PIL 'L' images, 255 = inside)
    def ellipse(self, x0, y0, x1, y1):
        m, d = self.new(); d.ellipse(self.bx(x0, y0, x1, y1), fill=255); return m

    def circle(self, cx, cy, r):
        return self.ellipse(cx - r, cy - r, cx + r, cy + r)

    def poly(self, pts):
        m, d = self.new(); d.polygon([self.p(x, y) for x, y in pts], fill=255); return m

    def rrect(self, x0, y0, x1, y1, r):
        m, d = self.new(); d.rounded_rectangle(self.bx(x0, y0, x1, y1), radius=self.L(r), fill=255); return m

    def stroke(self, pts, w):
        """A thick polyline with round caps and joins."""
        m, d = self.new(); P = [self.p(x, y) for x, y in pts]; W = self.L(w)
        d.line(P, fill=255, width=W, joint='curve')
        for x, y in P:
            d.ellipse([x - W / 2, y - W / 2, x + W / 2, y + W / 2], fill=255)
        return m

    def arc(self, cx, cy, rx, ry, a0, a1, w, n=48):
        """Arc stroke; angles in degrees, 0 = right, 90 = down (screen coordinates)."""
        pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
               for a in np.linspace(a0, a1, n)]
        return self.stroke(pts, w)

    @staticmethod
    def union(*ms):
        a = np.maximum.reduce([np.asarray(m, np.uint8) for m in ms]); return Image.fromarray(a)

    @staticmethod
    def minus(m, n):
        a = np.asarray(m, np.int16) - np.asarray(n, np.int16); return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    @staticmethod
    def inter(m, n):
        a = np.minimum(np.asarray(m, np.uint8), np.asarray(n, np.uint8)); return Image.fromarray(a)

    def blur(self, m, r):
        return m.filter(ImageFilter.GaussianBlur(r * self.A))

    # paint a mask with a colour or a gradient, optionally clipped by another mask, with an opacity
    def paint(self, m, fill, clip=None, alpha=1.0):
        a = np.asarray(m, np.float32) / 255 * alpha
        if clip is not None:
            a = a * (np.asarray(clip, np.float32) / 255)
        if isinstance(fill, tuple) and fill and fill[0] in ('v', 'r'):
            if fill[0] == 'v':                                   # ('v', c_top, c_bottom, y0, y1)
                _, c1, c2, y0, y1 = fill
                t = np.clip((self.uy - y0) / max(1e-6, y1 - y0), 0, 1)
                stops = [(0, c1), (1, c2)]
            else:                                                # ('r', cx, cy, radius, c_in, c_mid, c_out)
                _, cx, cy, rad, *cs = fill
                t = np.clip(np.hypot(self.ux - cx, self.uy - cy) / rad, 0, 1)
                stops = [(i / (len(cs) - 1), c) for i, c in enumerate(cs)]
            col = np.zeros((self.C, self.C, 3), np.float32)
            for (t0, c0), (t1, c1_) in zip(stops, stops[1:]):
                seg = (t >= t0) & (t <= t1)
                k = ((t - t0) / max(1e-6, t1 - t0))[..., None]
                c0v = np.array(rgb(c0), np.float32) / 255; c1v = np.array(rgb(c1_), np.float32) / 255
                col = np.where(seg[..., None], c0v + (c1v - c0v) * k, col)
        else:
            col = np.broadcast_to(np.array(rgb(fill), np.float32) / 255, (self.C, self.C, 3))
        ia = self.img[..., 3:4]; na = a[..., None]
        oa = na + ia * (1 - na)
        self.img[..., :3] = np.where(oa > 1e-6, (col * na + self.img[..., :3] * ia * (1 - na)) / np.maximum(oa, 1e-6), 0)
        self.img[..., 3:4] = oa

    def gloss(self, shape, x0, y0, x1, y1, a=0.55, dot=None):
        """Glossy highlight: a soft white ellipse (and a small dot) clipped to the shape."""
        self.paint(self.blur(self.ellipse(x0, y0, x1, y1), 0.025), '#FFFFFF', clip=shape, alpha=a)
        if dot:
            self.paint(self.blur(self.circle(*dot), 0.006), '#FFFFFF', clip=shape, alpha=0.85)

    def finish(self, outline=0.075, shadow=True):
        """White sticker outline + soft shadow, then down-sample. Returns a premultiplied 'RGBa' PIL image."""
        alpha = (self.img[..., 3] > 0.04).astype(np.uint8)
        r = max(1, self.L(outline))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        o = cv2.dilate(alpha, k)
        o = cv2.morphologyEx(o, cv2.MORPH_CLOSE, k)
        o = cv2.GaussianBlur(o.astype(np.float32), (0, 0), SS * 0.6)
        res = np.zeros_like(self.img)
        if shadow:
            sh = cv2.GaussianBlur(o, (0, 0), 0.035 * self.A)
            dx, dy = int(0.02 * self.A), int(0.045 * self.A)
            sh2 = np.zeros_like(sh); sh2[dy:, dx:] = sh[:sh.shape[0] - dy, :sh.shape[1] - dx]; sh = sh2 * 0.34
            res[..., :3] = np.array(rgb('#4A1E46'), np.float32) / 255; res[..., 3] = sh
        # white outline over the shadow
        a2 = o; ia = res[..., 3]
        oa = a2 + ia * (1 - a2)
        res[..., :3] = (1.0 * a2[..., None] + res[..., :3] * (ia * (1 - a2))[..., None]) / np.maximum(oa, 1e-6)[..., None]
        res[..., 3] = oa
        # the art on top
        na = self.img[..., 3]; ia = res[..., 3]; oa = na + ia * (1 - na)
        res[..., :3] = (self.img[..., :3] * na[..., None] + res[..., :3] * (ia * (1 - na))[..., None]) / np.maximum(oa, 1e-6)[..., None]
        res[..., 3] = oa
        im = Image.fromarray((np.clip(res, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA').convert('RGBa')
        return im.resize((self.C // SS, self.C // SS), Image.LANCZOS)


# ---- faces ----
def face_base(a):
    shape = a.ellipse(0.04, 0.04, 0.96, 0.96)
    a.paint(shape, ('r', 0.42, 0.34, 0.66, '#FFF59A', '#FFD93B', '#FFB21A'))
    a.paint(a.minus(shape, a.ellipse(0.075, 0.075, 0.925, 0.925)), '#F29A00', alpha=0.55)        # warm rim
    for x in (0.2, 0.8):                                                                         # blush
        a.paint(a.blur(a.ellipse(x - 0.095, 0.6, x + 0.095, 0.7), 0.012), '#FF6FA0', alpha=0.7)
    return shape


def eye(a, kind, cx, cy, s=1.0, side=1):
    if kind == 'dot':
        a.paint(a.ellipse(cx - 0.055 * s, cy - 0.085 * s, cx + 0.055 * s, cy + 0.085 * s), INK)
        a.paint(a.circle(cx + 0.018 * s, cy - 0.035 * s, 0.024 * s), '#FFFFFF')
    elif kind == 'big':
        a.paint(a.ellipse(cx - 0.07 * s, cy - 0.105 * s, cx + 0.07 * s, cy + 0.105 * s), INK)
        a.paint(a.circle(cx + 0.022 * s, cy - 0.04 * s, 0.032 * s), '#FFFFFF')
        a.paint(a.circle(cx - 0.025 * s, cy + 0.04 * s, 0.014 * s), '#FFFFFF')
    elif kind == 'happy':                                                                        # ^ closed, smiling
        a.paint(a.arc(cx, cy + 0.03 * s, 0.075 * s, 0.07 * s, 200, 340, 0.04 * s), INK)
    elif kind == 'star':
        m = a.poly(star_pts(cx, cy, 0.13 * s, 0.06 * s))
        a.paint(m, ('r', cx - 0.02, cy - 0.03, 0.14 * s, '#FFE07A', '#FF7A1A', '#FF4A2A'))
        a.paint(a.circle(cx - 0.03 * s, cy - 0.035 * s, 0.022 * s), '#FFFFFF', alpha=0.9)
    elif kind == 'heart':
        m = a.poly(heart_pts(cx, cy + 0.005, 0.15 * s))
        a.paint(m, ('r', cx - 0.03, cy - 0.04, 0.15 * s, '#FF9AC0', '#FF3A75', '#E01E5A'))
        a.paint(a.circle(cx - 0.035 * s, cy - 0.03 * s, 0.022 * s), '#FFFFFF', alpha=0.9)


def mouth(a, kind, cx=0.5, cy=0.66, s=1.0):
    if kind == 'smile':
        a.paint(a.arc(cx, cy - 0.06 * s, 0.17 * s, 0.13 * s, 25, 155, 0.042 * s), INK)
    elif kind == 'open':                                                                         # D-shaped laugh
        m = a.poly([(cx + 0.2 * s * math.cos(math.radians(t)), cy - 0.03 * s + 0.2 * s * math.sin(math.radians(t)))
                    for t in np.linspace(0, 180, 40)])
        a.paint(m, '#8E1F2E')
        a.paint(a.ellipse(cx - 0.11 * s, cy + 0.06 * s, cx + 0.11 * s, cy + 0.2 * s), '#FF7D8E', clip=m)
        a.paint(a.rrect(cx - 0.17 * s, cy - 0.05 * s, cx + 0.17 * s, cy + 0.015 * s, 0.01), '#FFFFFF', clip=m)
    elif kind == 'o':
        m = a.ellipse(cx - 0.075 * s, cy - 0.06 * s, cx + 0.075 * s, cy + 0.1 * s)
        a.paint(m, '#8E1F2E')
        a.paint(a.ellipse(cx - 0.045 * s, cy + 0.03 * s, cx + 0.045 * s, cy + 0.095 * s), '#FF7D8E', clip=m)
    elif kind == 'tongue':
        a.paint(a.arc(cx, cy - 0.06 * s, 0.17 * s, 0.13 * s, 25, 155, 0.042 * s), INK)
        t = a.ellipse(cx + 0.02 * s, cy + 0.02 * s, cx + 0.12 * s, cy + 0.14 * s)
        a.paint(t, '#FF7D8E'); a.paint(a.stroke([(cx + 0.07 * s, cy + 0.04 * s), (cx + 0.07 * s, cy + 0.09 * s)], 0.012 * s), '#E0566A')


def mini_face(a, cx, cy, s, eyes='dot'):
    """The small cute face on stars, suns and clouds."""
    for dx in (-0.12, 0.12):
        eye(a, eyes, cx + dx * s, cy - 0.02 * s, 0.75 * s)
    a.paint(a.arc(cx, cy + 0.02 * s, 0.09 * s, 0.07 * s, 25, 155, 0.035 * s), INK)
    for dx in (-0.22, 0.22):
        a.paint(a.blur(a.ellipse(cx + dx * s - 0.06 * s, cy + 0.05 * s, cx + dx * s + 0.06 * s, cy + 0.11 * s), 0.008), '#FF6FA0', alpha=0.65)


def draw_face(a, expr):
    shape = face_base(a)
    E = {'face_smile': ('dot', 'dot', 'smile'), 'face_laugh': ('happy', 'happy', 'open'), 'face_star': ('star', 'star', 'open'),
         'face_heart': ('heart', 'heart', 'smile'), 'face_wink': ('dot', 'happy', 'tongue'), 'face_wow': ('big', 'big', 'o'),
         'face_wave': ('happy', 'happy', 'smile')}[expr]
    s = 1.25 if E[0] in ('star', 'heart') else 1.0
    eye(a, E[0], 0.34, 0.42, s, -1); eye(a, E[1], 0.66, 0.42, s, 1)
    if expr == 'face_wow':
        for x in (0.34, 0.66):
            a.paint(a.arc(x, 0.27, 0.07, 0.04, 200, 340, 0.03), INK)
    mouth(a, E[2])
    a.gloss(shape, 0.17, 0.09, 0.56, 0.3, 0.55, dot=(0.66, 0.15, 0.03))
    if expr == 'face_wave':                                                                      # a little waving hand
        hand = a.union(a.ellipse(0.7, 0.62, 1.0, 0.92),
                       *[a.stroke([(0.75 + i * 0.062, 0.7), (0.72 + i * 0.085, 0.5 - (0.035 if i in (1, 2) else 0))], 0.07) for i in range(4)])
        a.paint(hand, ('v', '#FFF07A', '#FFB21A', 0.45, 0.95))
        a.paint(a.arc(0.9, 0.56, 0.17, 0.17, -80, -30, 0.026), '#FF7AC8')
        a.paint(a.arc(0.9, 0.56, 0.24, 0.24, -75, -35, 0.026), '#7CC8FF')


# ---- doodles ----
def star_pts(cx, cy, R, r, n=5, rot=-90):
    pts = []
    for i in range(2 * n):
        rr = R if i % 2 == 0 else r; ang = math.radians(rot + i * 180 / n)
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


def heart_pts(cx, cy, size):
    pts = []
    for t in np.linspace(0, 2 * math.pi, 120):
        x = 16 * math.sin(t) ** 3; y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x / 34 * size * 2, cy - y / 34 * size * 2 + 0.03 * size))
    return pts


def sparkle_pts(cx, cy, R, k=0.22):
    pts = []
    for i in range(8):
        ang = math.radians(-90 + i * 45); rr = R if i % 2 == 0 else R * k
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


def draw_star(a, c):
    m = a.poly(star_pts(0.5, 0.54, 0.5, 0.24))
    # round the points a little
    m = a.blur(m, 0.012).point(lambda v: 255 if v > 110 else 0)
    a.paint(m, ('r', 0.42, 0.38, 0.6, light(c, 0.5), c, mix(c, '#FF8A00', 0.55)))
    a.gloss(m, 0.3, 0.2, 0.56, 0.42, 0.5)
    mini_face(a, 0.5, 0.56, 0.9)


def draw_heart(a, c):
    m = a.poly(heart_pts(0.5, 0.5, 0.48))
    a.paint(m, ('r', 0.38, 0.32, 0.65, light(c, 0.5), c, dark(c, 0.15)))
    a.gloss(m, 0.17, 0.16, 0.42, 0.36, 0.6, dot=(0.5, 0.3, 0.025))


def draw_sparkle(a, c):
    for cx, cy, R in ((0.42, 0.55, 0.42), (0.82, 0.2, 0.16), (0.84, 0.84, 0.1)):
        m = a.poly(sparkle_pts(cx, cy, R))
        a.paint(m, ('r', cx, cy, R * 0.95, '#FFFFFF', c, mix(c, '#FF9A00', 0.45)))


def draw_rainbow(a):
    cols = ['#FF5E7E', '#FFA24C', '#FFE45C', '#7BF7C8', '#7CC8FF', '#B68CFF']
    R = 0.48; band = 0.058; cx, cy = 0.5, 0.74
    half = a.poly([(-1, -1), (2, -1), (2, cy), (-1, cy)])
    for i, c in enumerate(cols):
        ring = a.minus(a.circle(cx, cy, R - i * band), a.circle(cx, cy, R - (i + 1) * band))
        a.paint(a.inter(ring, half), c)
    a.gloss(a.inter(a.circle(cx, cy, R), half), 0.18, 0.28, 0.42, 0.4, 0.35)
    for x in (0.16, 0.84):
        cloud_shape(a, x, 0.76, 0.42)


def cloud_shape(a, cx, cy, s):
    m = a.union(a.circle(cx - 0.2 * s, cy + 0.02 * s, 0.17 * s), a.circle(cx, cy - 0.08 * s, 0.24 * s),
                a.circle(cx + 0.22 * s, cy + 0.0 * s, 0.18 * s), a.rrect(cx - 0.36 * s, cy - 0.02 * s, cx + 0.38 * s, cy + 0.18 * s, 0.09 * s))
    a.paint(m, ('v', '#FFFFFF', '#CFE8FF', cy - 0.3 * s, cy + 0.2 * s))
    return m


def draw_cloud(a):
    m = cloud_shape(a, 0.5, 0.56, 1.25)
    a.gloss(m, 0.25, 0.3, 0.55, 0.42, 0.6)
    mini_face(a, 0.5, 0.6, 0.8)


def draw_sun(a):
    rays = []
    for i in range(12):
        ang = math.radians(i * 30 + 15)
        tip = (0.5 + 0.49 * math.cos(ang), 0.5 + 0.49 * math.sin(ang))
        l = (0.5 + 0.3 * math.cos(ang - 0.2), 0.5 + 0.3 * math.sin(ang - 0.2))
        r = (0.5 + 0.3 * math.cos(ang + 0.2), 0.5 + 0.3 * math.sin(ang + 0.2))
        rays.append(a.poly([l, tip, r]))
    rm = a.blur(a.union(*rays), 0.01).point(lambda v: 255 if v > 100 else 0)
    a.paint(rm, ('r', 0.5, 0.5, 0.5, '#FFD23B', '#FF9F1C', '#FF7A1A'))
    disk = a.circle(0.5, 0.5, 0.31)
    a.paint(disk, ('r', 0.42, 0.4, 0.34, '#FFF59A', '#FFD93B', '#FFB21A'))
    a.gloss(disk, 0.3, 0.24, 0.52, 0.36, 0.55)
    mini_face(a, 0.5, 0.52, 1.0, 'happy')


def draw_note(a, c):
    heads = [a.ellipse(0.12, 0.66, 0.42, 0.88), a.ellipse(0.56, 0.56, 0.86, 0.78)]
    stems = [a.stroke([(0.39, 0.76), (0.39, 0.2)], 0.075), a.stroke([(0.83, 0.66), (0.83, 0.1)], 0.075)]
    beam = a.poly([(0.355, 0.13), (0.865, 0.03), (0.865, 0.19), (0.355, 0.29)])
    m = a.union(*heads, *stems, beam)
    a.paint(m, ('v', light(c, 0.35), dark(c, 0.18), 0.0, 0.9))
    a.gloss(m, 0.17, 0.68, 0.3, 0.75, 0.6)
    a.gloss(m, 0.6, 0.58, 0.74, 0.65, 0.6)


def hand_fill(a, m):
    a.paint(m, ('r', 0.45, 0.4, 0.6, '#FFF07A', '#FFD23B', '#FFAE1A'))


def draw_thumbs(a):
    fist = a.rrect(0.3, 0.42, 0.8, 0.9, 0.12)
    thumb = a.rrect(0.33, 0.06, 0.55, 0.6, 0.11)
    m = a.union(fist, thumb)
    hand_fill(a, m)
    for y in (0.56, 0.68, 0.8):
        a.paint(a.arc(0.8, y, 0.2, 0.05, 110, 200, 0.02), '#E08A00')
    cuff = a.rrect(0.12, 0.46, 0.32, 0.94, 0.06)
    a.paint(cuff, ('v', '#9AD7FF', '#3A8DFF', 0.46, 0.94))
    a.gloss(m, 0.37, 0.1, 0.47, 0.35, 0.5)


def draw_vhand(a):
    palm = a.rrect(0.3, 0.5, 0.74, 0.94, 0.14)
    f1 = a.stroke([(0.42, 0.6), (0.27, 0.1)], 0.14)
    f2 = a.stroke([(0.6, 0.6), (0.7, 0.07)], 0.14)
    m = a.union(palm, f1, f2)
    hand_fill(a, m)
    a.paint(a.ellipse(0.28, 0.62, 0.52, 0.8), '#FFC43A')                    # folded thumb
    a.paint(a.minus(a.ellipse(0.28, 0.62, 0.52, 0.8), a.ellipse(0.295, 0.635, 0.505, 0.785)), '#E08A00')
    a.gloss(m, 0.24, 0.12, 0.33, 0.35, 0.45)
    a.gloss(m, 0.62, 0.1, 0.71, 0.33, 0.45)


def draw_camera(a):
    body = a.rrect(0.06, 0.32, 0.94, 0.88, 0.13)
    bump = a.rrect(0.22, 0.2, 0.46, 0.4, 0.05)
    m = a.union(body, bump)
    a.paint(m, ('v', '#FFB0E0', '#F0347F', 0.2, 0.9))
    a.paint(a.circle(0.5, 0.6, 0.22), '#FFFFFF')
    lens = a.circle(0.5, 0.6, 0.17)
    a.paint(lens, ('r', 0.45, 0.55, 0.18, '#BDE6FF', '#3A8DFF', '#1E3A8A'))
    a.paint(a.circle(0.44, 0.54, 0.045), '#FFFFFF', alpha=0.9)
    a.paint(a.rrect(0.72, 0.4, 0.86, 0.48, 0.02), '#FFE45C')
    a.gloss(m, 0.12, 0.36, 0.4, 0.44, 0.45)
    fl = a.poly(star_pts(0.86, 0.14, 0.17, 0.06, 8))
    a.paint(fl, ('r', 0.86, 0.14, 0.17, '#FFFFFF', '#FFE45C', '#FFB21A'))


def draw_question(a, c):
    m = a.union(a.arc(0.5, 0.3, 0.22, 0.2, 180, 405, 0.15),
                a.stroke([(0.5 + 0.22 * math.cos(math.radians(45)), 0.3 + 0.2 * math.sin(math.radians(45))), (0.5, 0.52), (0.5, 0.64)], 0.15),
                a.circle(0.5, 0.86, 0.09))
    a.paint(m, ('v', light(c, 0.35), dark(c, 0.15), 0.05, 0.95))
    a.gloss(m, 0.28, 0.12, 0.45, 0.26, 0.55)


def draw_squiggle(a, c):
    pts = [(0.05 + 0.9 * i / 60, 0.5 + 0.13 * math.sin(i / 60 * math.pi * 4.5)) for i in range(61)]
    m = a.stroke(pts, 0.1)
    a.paint(m, ('v', light(c, 0.3), dark(c, 0.1), 0.35, 0.65))


def make_sprite(kind, S, color=None, opts=None):
    a = Art(S); o = opts or {}
    if kind.startswith('face_'):
        draw_face(a, kind)
    elif kind == 'star':
        draw_star(a, color or 'yellow')
    elif kind == 'heart':
        draw_heart(a, color or 'pink')
    elif kind == 'sparkle':
        draw_sparkle(a, color or 'yellow')
    elif kind == 'rainbow':
        draw_rainbow(a)
    elif kind == 'cloud':
        draw_cloud(a)
    elif kind == 'sun':
        draw_sun(a)
    elif kind == 'note':
        draw_note(a, color or 'sky')
    elif kind == 'thumbs':
        draw_thumbs(a)
    elif kind == 'vhand':
        draw_vhand(a)
    elif kind == 'camera':
        draw_camera(a)
    elif kind == 'question':
        draw_question(a, color or 'sky')
    elif kind == 'squiggle':
        draw_squiggle(a, color or 'pink')
    elif kind == 'bubble':
        draw_bubble(a, color or 'yellow', o.get('text', '哇！'), o.get('style', 'round'), o.get('tail', 'bl'))
    elif kind == 'word':
        draw_bubble(a, color or 'rose', o.get('text', '看！'), 'none')
    elif kind == 'twinkle':
        draw_twinkle(a, color or 'yellow')
    elif kind == 'balloon':
        draw_balloon(a, color or 'pink')
    else:
        raise SystemExit(f'unknown sticker kind: {kind}')
    return a.finish(outline=0.06 if kind in ('sparkle', 'squiggle') else 0.045 if kind in ('twinkle', 'balloon') else 0.075)


# ---------------------------------------------------------------- v3 kinds (owner 2026-11-07: "more motion graphic") ---
# (Merged in for the kids-review skill: one self-contained file, nothing is patched in any more.)
#   bubble     kids' speech / shout bubble with a short cute word (text, style round|shout, tail bl|br|tl|tr), pops + shakes
#   word       the same lettering without the bubble (used for the arrow's 看！ label)
#   twinkle    a small 4-point star that blinks (motion blink, blink = Hz)
#   balloon    a glossy balloon on a string that rises (motion rise, rise = height in short-side units, clip = band)
#   trail      3-4 small hearts / stars hopping one after another along an arc (pos -> to, count, item, colors, bend)
#   frame      crayon corner brackets that draw themselves on around a box (box, arm, width, color)
#   arrow      a hand-drawn arrow that draws on from pos to to, pokes at the target, optional label (text, label_pos)
#   underline  a cute dashed wavy underline that draws on left to right (pos = centre, width = fraction of frame width)
#   wipe       a shot transition: candy bubbles (and stars) grow across the frame, cover it on the cut, then clear
#              (dir right|left|down|up|diag, cell, stars); set t = cut - dur/2 and sfx_offset = dur/2.
# Crayon lines "boil" (their wobble changes every 4 frames) like a child's drawing; nothing is ever static.
FONT_CANDIDATES = [os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts', '975MaruSC-Bold.ttf'),
                   r'C:\Windows\Fonts\975MaruSC-Bold.ttf',
                   os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts', 'NotoSansSC-VF.ttf'),
                   r'C:\Windows\Fonts\msyhbd.ttc']
_font_path = []


def font_path():
    if not _font_path:
        env = os.environ.get('STK_FONT')
        for p in ([env] if env else []) + FONT_CANDIDATES:
            if p and os.path.exists(p):
                _font_path.append(p); break
        else:
            raise SystemExit('no CJK font found for the bubbles (set STK_FONT)')
    return _font_path[0]


def text_masks(a, text, cx, cy, maxw, maxh, stroke):
    """(fill mask, fill+stroke mask) of the text fitted into maxw x maxh (unit coords), centred at cx, cy."""
    from PIL import ImageFont
    W = maxw * a.A; H = maxh * a.A; sw = max(1, int(round(stroke * a.A)))
    size = max(8, int(H * 1.1))
    while True:
        f = ImageFont.truetype(font_path(), size)
        l, t_, r, b = f.getbbox(text, stroke_width=sw)
        if (r - l <= W and b - t_ <= H) or size <= 8:
            break
        size = max(8, int(size * 0.94))
    px, py = a.p(cx, cy)
    x = px - (l + r) / 2; y = py - (t_ + b) / 2
    m1, d1 = a.new(); d1.text((x, y), text, font=f, fill=255)
    m2, d2 = a.new(); d2.text((x, y), text, font=f, fill=255, stroke_width=sw, stroke_fill=255)
    return m1, m2


def bubble_shape(a, style, tail):
    if style == 'shout':
        pts = []
        n = 15
        for i in range(2 * n):
            ang = math.radians(-90 + i * 180 / n)
            rr = (0.5 if i % 2 == 0 else 0.385) * (1 + 0.05 * math.sin(i * 2.3))
            pts.append((0.5 + rr * math.cos(ang) * 0.98, 0.47 + rr * math.sin(ang) * 0.8))
        return a.blur(a.poly(pts), 0.006).point(lambda v: 255 if v > 120 else 0)
    body = a.ellipse(0.03, 0.14, 0.97, 0.80)
    tails = {'bl': [(0.2, 0.66), (0.42, 0.76), (0.07, 0.97)], 'br': [(0.8, 0.66), (0.58, 0.76), (0.93, 0.97)],
             'tl': [(0.2, 0.28), (0.42, 0.18), (0.07, -0.03)], 'tr': [(0.8, 0.28), (0.58, 0.18), (0.93, -0.03)]}
    if tail in tails:
        body = a.union(body, a.blur(a.poly(tails[tail]), 0.004).point(lambda v: 255 if v > 120 else 0))
    return body


BUBBLE_INK, BUBBLE_INK_BLUE, BLUE_BUBBLES = '#D81B60', '#1565C0', ('sky', 'blue')   # v3: bubble text ink
TEXT_INK = {'yellow': '#FF4F8B', 'light': '#F0347F', 'pink': '#F0347F', 'rose': '#D81B60', 'mint': '#12A57A',
            'sky': '#2D7BE5', 'purple': '#7A45E0', 'orange': '#F26A1B', 'red': '#E0244A'}


def erode(a, m, r):
    k = max(1, a.L(r)); ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    return Image.fromarray(cv2.erode(np.asarray(m, np.uint8), ker))


def draw_bubble(a, c, text, style='round', tail='bl'):
    ink = TEXT_INK.get(c, dark(c, 0.25)) if isinstance(c, str) else dark(c, 0.25)
    if style == 'none':                                       # lettering only (thick white sticker outline from finish)
        m1, m2 = text_masks(a, text, 0.5, 0.5, 0.96, 0.66, 0.02)
        a.paint(m2, dark(ink, 0.25))
        a.paint(m1, ('v', light(ink, 0.3), ink, 0.2, 0.8))
        a.paint(a.inter(m1, a.ellipse(0.0, 0.05, 1.0, 0.42)), '#FFFFFF', alpha=0.3)
        return
    body = bubble_shape(a, style, tail)
    a.paint(body, ('v', '#FFFFFF', light(c, 0.55), 0.12, 0.85))
    a.paint(a.minus(body, erode(a, body, 0.04)), c)                                   # candy rim
    a.gloss(erode(a, body, 0.04), 0.14, 0.18, 0.5, 0.3, 0.6, dot=(0.8, 0.26, 0.02))
    # v3 brand check: the old same-colour 0.016 stroke filled the counters (酷, 害 blobbed). Now a solid dark ink fill over a
    # thick WHITE outline drawn under it, no shine on the text, and a bigger text area in the shout star.
    mw, mh, cy = (0.74, 0.46, 0.47) if style == 'shout' else (0.86, 0.5, 0.47)
    m1, m2 = text_masks(a, text, 0.5, cy, mw, mh, 0.03)                              # m2 = fill + thick white outline
    a.paint(m2, '#FFFFFF')
    a.paint(m1, BUBBLE_INK_BLUE if c in BLUE_BUBBLES else BUBBLE_INK)


def draw_twinkle(a, c):
    m = a.poly(sparkle_pts(0.5, 0.5, 0.48, 0.15))
    m = a.blur(m, 0.006).point(lambda v: 255 if v > 110 else 0)
    a.paint(m, ('r', 0.5, 0.5, 0.46, '#FFFFFF', c, mix(c, '#FF9A00', 0.35)))
    a.paint(a.circle(0.5, 0.5, 0.06), '#FFFFFF')


def draw_balloon(a, c):
    a.paint(a.stroke([(0.5, 0.74), (0.54, 0.82), (0.46, 0.9), (0.52, 0.99)], 0.014), '#8A6F8F')
    a.paint(a.poly([(0.44, 0.76), (0.56, 0.76), (0.5, 0.68)]), dark(c, 0.2))
    body = a.ellipse(0.22, 0.02, 0.78, 0.71)
    a.paint(body, ('r', 0.4, 0.24, 0.52, light(c, 0.55), c, dark(c, 0.22)))
    a.gloss(body, 0.3, 0.09, 0.45, 0.27, 0.7, dot=(0.35, 0.33, 0.02))


# ---- live kinds (drawn on the frame each time, no single sprite) ----
def fpx(s, p):
    return (float(p[0]) * s.W, float(p[1]) * s.H)


def arc_ctrl(a, b, bend, up=True):
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy) or 1.0
    nx, ny = dy / L, -dx / L
    if up and ny > 0:
        nx, ny = -nx, -ny
    return (mx + nx * bend, my + ny * bend)


def bez(p0, p1, p2, u):
    v = 1 - u
    return (v * v * p0[0] + 2 * v * u * p1[0] + u * u * p2[0], v * v * p0[1] + 2 * v * u * p1[1] + u * u * p2[1])


def densify(pts, step):
    res = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for k in range(1, n + 1):
            res.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return res


def crayon(pts, amp, seed):
    """A hand-drawn wobble; the seed changes every few frames so the line boils like a child's drawing."""
    return [(x + amp * (math.sin(i * 0.23 + seed * 1.7) + 0.5 * math.sin(i * 0.61 + seed * 2.9)),
             y + amp * (math.cos(i * 0.19 + seed * 2.3) + 0.5 * math.sin(i * 0.47 + seed * 1.3))) for i, (x, y) in enumerate(pts)]


def partial(pts, p):
    if p >= 1:
        return list(pts)
    if p <= 0 or len(pts) < 2:
        return []
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    goal = sum(seg) * p; acc = 0.0; res = [pts[0]]
    for (a, b), L in zip(zip(pts, pts[1:]), seg):
        if acc + L >= goal:
            k = (goal - acc) / L if L else 0
            res.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)); return res
        res.append(b); acc += L
    return res


def composite_np(frame, C, A, x0, y0, alpha=1.0):
    """Premultiplied float colour C (h, w, 3) and alpha A (h, w) onto the frame at x0, y0 (clipped)."""
    H, W = frame.shape[:2]; h, w = A.shape
    fx0, fy0 = max(0, x0), max(0, y0); fx1, fy1 = min(W, x0 + w), min(H, y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    cc = C[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0] * alpha
    aa = A[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0, None] * alpha
    reg = frame[fy0:fy1, fx0:fx1].astype(np.float32) / 255
    frame[fy0:fy1, fx0:fx1] = np.clip((cc + reg * (1 - aa)) * 255 + 0.5, 0, 255).astype(np.uint8)


def stroke_patch(frame, lines, w, color, alpha=1.0):
    """Crayon strokes (lists of px points): soft shadow, white sticker border, the colour, a light highlight."""
    lines = [l for l in lines if len(l) >= 2]
    if not lines or alpha <= 0.01:
        return
    H, W = frame.shape[:2]; ow = w * 0.6; K = 2
    pad = w / 2 + ow + w * 1.5 + 4
    xs = [p[0] for l in lines for p in l]; ys = [p[1] for l in lines for p in l]
    x0, y0 = int(math.floor(min(xs) - pad)), int(math.floor(min(ys) - pad))
    x1, y1 = int(math.ceil(max(xs) + pad)), int(math.ceil(max(ys) + pad))
    if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
        return
    pw, ph = (x1 - x0) * K, (y1 - y0) * K

    def mask(width, dx=0.0, dy=0.0):
        m = Image.new('L', (pw, ph), 0); dr = ImageDraw.Draw(m); Wd = max(1, int(round(width * K)))
        for l in lines:
            P = [((x - x0 + dx) * K, (y - y0 + dy) * K) for x, y in l]
            dr.line(P, fill=255, width=Wd, joint='curve')
            for x, y in (P[0], P[-1]):
                dr.ellipse([x - Wd / 2, y - Wd / 2, x + Wd / 2, y + Wd / 2], fill=255)
        return np.asarray(m, np.float32) / 255

    outer = mask(w + 2 * ow); core = mask(w)
    sh = cv2.GaussianBlur(mask(w + 2 * ow, 0.15 * w, 0.4 * w), (0, 0), max(1.0, w * 0.5 * K)) * 0.32
    hi = mask(max(1.0, w * 0.3), -0.16 * w, -0.16 * w) * core * 0.55
    C = np.zeros((ph, pw, 3), np.float32); A = np.zeros((ph, pw), np.float32)
    for col, a in (('#4A1E46', sh), ('#FFFFFF', outer), (color, core), (light(color, 0.6), hi)):
        cv = np.array(rgb(col), np.float32) / 255
        C = cv * a[..., None] + C * (1 - a[..., None]); A = a + A * (1 - a)
    C = cv2.resize(C, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    A = cv2.resize(A, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    composite_np(frame, C, A, x0, y0, alpha)


WIPE_COLS = ['pink', 'yellow', 'mint', 'sky', 'purple', 'orange', 'light', 'rose']


def wipe_order(dirn, x, y, W, H):
    return {'right': x / W, 'left': 1 - x / W, 'down': y / H, 'up': 1 - y / H}.get(dirn, (x / W + y / H) / 2)


def live_setup(s, sprites=True):
    d, key, sh = s.d, s.key, s.short
    s.color = d.get('color')
    if s.kind == 'trail':
        s.p0 = fpx(s, per_aspect(d.get('pos'), key)); s.p2 = fpx(s, per_aspect(d.get('to'), key))
        s.p1 = arc_ctrl(s.p0, s.p2, float(per_aspect(d.get('bend'), key, 0.12)) * sh)
        s.n = int(d.get('count', 4)); s.gap = float(d.get('gap', 0.11))
        if sprites:
            cols = d.get('colors') or (['pink', 'rose', 'light', 'purple'] if d.get('item', 'heart') == 'heart'
                                       else ['yellow', 'pink', 'mint', 'sky'])
            S = max(8, int(round(s.size * sh * 1.2)))
            s.pieces = [make_sprite(d.get('item', 'heart'), S, cols[i % len(cols)]) for i in range(s.n)]
    elif s.kind == 'frame':
        x0, y0, x1, y1 = per_aspect(d.get('box'), key)
        s.fb = (x0 * s.W, y0 * s.H, x1 * s.W, y1 * s.H)
        s.arm = float(per_aspect(d.get('arm'), key, 0.2)) * min(s.fb[2] - s.fb[0], s.fb[3] - s.fb[1])
        s.lw = float(d.get('width', 0.013)) * sh; s.color = s.color or 'yellow'
    elif s.kind == 'arrow':
        s.p0 = fpx(s, per_aspect(d.get('pos'), key)); s.p2 = fpx(s, per_aspect(d.get('to'), key))
        s.p1 = arc_ctrl(s.p0, s.p2, float(per_aspect(d.get('bend'), key, 0.08)) * sh, up=False)
        s.lw = float(d.get('width', 0.012)) * sh; s.color = s.color or 'rose'
        s.path = [bez(s.p0, s.p1, s.p2, k / 40) for k in range(41)]
        lp = per_aspect(d.get('label_pos'), key, None)
        s.lpos = fpx(s, lp) if lp else None
        s.lsize = float(per_aspect(d.get('label_size'), key, 0.12))
        s.label = None
        if sprites and d.get('text') and s.lpos:
            s.label = make_sprite('word', max(8, int(round(s.lsize * sh * 1.2))), s.color, {'text': d['text']})
    elif s.kind == 'underline':
        cx, cy = per_aspect(d.get('pos'), key); w = float(per_aspect(d.get('width'), key, 0.5)) * s.W
        s.ux0, s.ux1, s.uy = cx * s.W - w / 2, cx * s.W + w / 2, cy * s.H
        s.lw = float(d.get('lw', 0.011)) * sh; s.color = s.color or 'rose'
        dash, gap = 0.05 * sh, 0.03 * sh
        s.nd = max(2, int((w + gap) / (dash + gap))); s.dash = (w - (s.nd - 1) * gap) / s.nd; s.dgap = gap
    elif s.kind == 'wipe' and sprites:
        rng = np.random.default_rng(500 + s.idx); W, H = s.W, s.H
        cell = float(d.get('cell', 0.17)) * sh; dirn = d.get('dir', 'right')
        cols = [rgb(c) for c in (d.get('colors') or WIPE_COLS)]
        s.items = []
        nx, ny = int(W / cell) + 3, int(H / (cell * 0.87)) + 3
        for j in range(ny):
            for i in range(nx):
                x = (i - 1 + (0.5 if j % 2 else 0)) * cell + rng.uniform(-0.2, 0.2) * cell
                y = (j - 1) * cell * 0.87 + rng.uniform(-0.2, 0.2) * cell
                xn = min(1.0, max(0.0, wipe_order(dirn, x, y, W, H) + rng.uniform(-0.04, 0.04)))
                s.items.append(dict(x=x, y=y, r=cell * rng.uniform(0.74, 0.92), c=cols[int(rng.integers(len(cols)))], xn=xn, star=False))
        for k in range(int(d.get('stars', 9))):
            x, y = rng.uniform(0.06, 0.94) * W, rng.uniform(0.06, 0.94) * H
            xn = min(1.0, max(0.0, wipe_order(dirn, x, y, W, H)))
            s.items.append(dict(x=x, y=y, r=cell * rng.uniform(0.5, 0.68), c=rgb('#FFFFFF') if k % 3 == 0 else rgb('#FFE45C'),
                                xn=xn, star=True, a0=rng.uniform(0, 72)))


def trail_piece(s, i, u):
    ui = u - i * s.gap; di = s.dur - i * s.gap
    if ui < 0 or ui >= di:
        return None
    sc = pop_scale(ui, di); sh = s.short
    ht = 0.42 + 0.05 * i; e = ease_out(min(1.0, ui / ht))
    v = 1 - i / max(1, s.n - 1)                       # the first piece hops the farthest, the last stays near the start
    x, y = bez(s.p0, s.p1, s.p2, v * e)
    hops = 1 + int(round(v * 2))
    y -= 0.05 * sh * abs(math.sin(math.pi * hops * e)) * (1 - 0.4 * e)
    rot = 10 * math.sin(2 * math.pi * 1.3 * ui + i)
    if ui > ht:
        y -= 0.012 * sh * abs(math.sin(2 * math.pi * 1.4 * (ui - ht) + i * 0.7))
    return x, y, sc, rot


def frame_lines(s, u, seed):
    x0, y0, x1, y1 = s.fb; a = s.arm; sh = s.short
    hold = u - 0.5
    o = 0.007 * sh * math.sin(2 * math.pi * 1.3 * hold) if hold > 0 else 0.0
    x0 -= o; y0 -= o; x1 += o; y1 += o
    corners = [[(x0, y0 + a), (x0, y0), (x0 + a, y0)], [(x1 - a, y0), (x1, y0), (x1, y0 + a)],
               [(x1, y1 - a), (x1, y1), (x1 - a, y1)], [(x0 + a, y1), (x0, y1), (x0, y1 - a)]]
    left = s.dur - u; res = []
    for k, c in enumerate(corners):
        p = ease_out(min(1.0, max(0.0, (u - k * 0.07) / 0.36)))
        if left < OUT_T:
            p *= max(0.0, left / OUT_T)
        res.append(partial(crayon(densify(c, 6), 0.0022 * sh, seed + k), p))
    return res


def arrow_lines(s, u, seed):
    sh = s.short; p = ease_out(min(1.0, u / 0.42))
    tip = s.path[-1]; prev = s.path[-4]
    dx, dy = tip[0] - prev[0], tip[1] - prev[1]; L = math.hypot(dx, dy) or 1; dx, dy = dx / L, dy / L
    hold = u - 0.42
    nud = 0.014 * sh * max(0.0, math.sin(2 * math.pi * 1.8 * hold)) if hold > 0 else 0.0
    path = [(x + dx * nud, y + dy * nud) for x, y in s.path]
    lines = [partial(crayon(densify(path, 6), 0.002 * sh, seed), p)]
    if hold > 0:
        hs = 1.25 * ease_out(hold / 0.08) if hold < 0.08 else (1.25 - 0.25 * ease_out((hold - 0.08) / 0.14) if hold < 0.22 else 1.0)
        hl = 0.05 * sh * hs; tx, ty = path[-1]; back = math.atan2(-dy, -dx)
        lines.append([(tx + hl * math.cos(back + 0.56), ty + hl * math.sin(back + 0.56)), (tx, ty),
                      (tx + hl * math.cos(back - 0.56), ty + hl * math.sin(back - 0.56))])
    return lines


def underline_lines(s, u):
    sh = s.short; P = min(1.0, u / 0.35); left = s.dur - u; hold = u - 0.35
    vis = 1.0 if left > OUT_T else max(0.0, left / OUT_T)
    res = []
    for i in range(s.nd):
        k = min(1.0, P * s.nd - i)
        if k <= 0 or (i + 1) / s.nd > vis + 1e-6:
            continue
        xa = s.ux0 + i * (s.dash + s.dgap); xb = xa + s.dash * k
        dy = 0.004 * sh * math.sin(2 * math.pi * 2.2 * hold + i * 0.9) if hold > 0 else 0.0
        res.append([(x, s.uy + dy + 0.005 * sh * math.sin((x - s.ux0) / sh * 14)) for x in np.linspace(xa, xb, 6)])
    return res


def pts_box(s, pts, pad):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return ((min(xs) - pad) / s.W, (min(ys) - pad) / s.H, (max(xs) + pad) / s.W, (max(ys) + pad) / s.H)


def live_boxes(s, t):
    u = t - s.t
    if u < 0 or u >= s.dur or s.kind == 'wipe':
        return []
    sh = s.short; res = []
    if s.kind == 'trail':
        for i in range(s.n):
            st = trail_piece(s, i, u)
            if st:
                hw = s.size * sh * max(st[2], 1.0) * 0.55
                res.append(((st[0] - hw) / s.W, (st[1] - hw) / s.H, (st[0] + hw) / s.W, (st[1] + hw) / s.H))
    elif s.kind == 'frame':
        res += [pts_box(s, l, s.lw * 1.1) for l in frame_lines(s, u, 0) if len(l) >= 2]
    elif s.kind == 'arrow':
        res += [pts_box(s, l, s.lw * 1.1) for l in arrow_lines(s, u, 0) if len(l) >= 2]
        if s.lpos:
            hw = s.lsize * sh * 0.6
            res.append(((s.lpos[0] - hw) / s.W, (s.lpos[1] - hw * 0.7) / s.H, (s.lpos[0] + hw) / s.W, (s.lpos[1] + hw * 0.7) / s.H))
    elif s.kind == 'underline':
        res += [pts_box(s, l, s.lw * 1.1) for l in underline_lines(s, u)]
    return res


def live_draw(s, frame, t):
    u = t - s.t
    if u < 0 or u >= s.dur:
        return
    seed = int(t * 7.5)                                   # crayon boil: a new wobble every 4 frames
    if s.kind == 'trail':
        for i in range(s.n):
            st = trail_piece(s, i, u)
            if not st:
                continue
            x, y, sc, rot = st; spr = s.pieces[i]; k = sc / 1.2; w0, h0 = spr.size
            im = spr.resize((max(1, int(round(w0 * k))), max(1, int(round(h0 * k)))), Image.BICUBIC)
            if abs(rot) > 0.05:
                im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
            composite(frame, im, x, y)
    elif s.kind == 'frame':
        for l in frame_lines(s, u, seed):
            stroke_patch(frame, [l], s.lw, s.color)
    elif s.kind == 'arrow':
        left = s.dur - u
        alpha = 1.0 if left > OUT_T else max(0.0, left / OUT_T)
        stroke_patch(frame, arrow_lines(s, u, seed), s.lw, s.color, alpha)
        if s.label is not None:
            sc = pop_scale(u, s.dur) / 1.2
            rot = 9 * math.sin(2 * math.pi * 6 * u) * math.exp(-u * 3) + 4 * math.sin(2 * math.pi * 1.2 * u)
            w0, h0 = s.label.size
            im = s.label.resize((max(1, int(round(w0 * sc))), max(1, int(round(h0 * sc)))), Image.BICUBIC)
            im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
            composite(frame, im, s.lpos[0], s.lpos[1])
    elif s.kind == 'underline':
        stroke_patch(frame, underline_lines(s, u), s.lw, s.color)
    elif s.kind == 'wipe':
        g = u / s.dur; hl = []; stars = []
        for it in s.items:
            a_in = min(1.0, max(0.0, (g - 0.36 * it['xn']) / 0.14))
            a_out = min(1.0, max(0.0, (g - 0.5 - 0.36 * it['xn']) / 0.14))
            r = it['r'] * ease_out(a_in) * (1 - a_out ** 2)
            if r < 1:
                continue
            if it['star']:
                stars.append((it, r)); continue
            cv2.circle(frame, (int(it['x'] * 16), int(it['y'] * 16)), int(r * 16), it['c'], -1, cv2.LINE_AA, 4)
            if r > 8:
                hl.append((it['x'] - 0.38 * r, it['y'] - 0.38 * r, 0.22 * r))
        if hl:
            ov = frame.copy()
            for x, y, r in hl:
                cv2.circle(ov, (int(x * 16), int(y * 16)), int(r * 16), (255, 255, 255), -1, cv2.LINE_AA, 4)
            cv2.addWeighted(frame, 0.45, ov, 0.55, 0, dst=frame)
        for it, r in stars:
            pts = np.array([[int(x * 16), int(y * 16)] for x, y in star_pts(it['x'], it['y'], r, r * 0.46, 5, -90 + it['a0'] + 160 * g)], np.int32)
            cv2.fillPoly(frame, [pts], it['c'], cv2.LINE_AA, 4)



# --------------------------------------------------------------- the plan -------------------------------------------
def aspect_key(W, H):
    return '9x16' if H > W else ('16x9' if W > H else '1x1')


def per_aspect(v, key, default=None):
    if v is None:
        return default
    if isinstance(v, dict):
        if key in v:
            return v[key]
        if 'default' in v:
            return v['default']
        return next(iter(v.values()))
    return v


def ease_out(x):
    return 1 - (1 - x) ** 3


def pop_scale(u, dur):
    """0.25 -> 1.2 -> 0.95 -> 1 on the way in, a small swell then 0 on the way out."""
    if u < IN_T:
        p = u / IN_T
        if p < 0.5:
            return 0.25 + (1.2 - 0.25) * ease_out(p / 0.5)
        if p < 0.78:
            q = (p - 0.5) / 0.28; return 1.2 + (0.95 - 1.2) * (0.5 - 0.5 * math.cos(math.pi * q))
        q = (p - 0.78) / 0.22; return 0.95 + 0.05 * (0.5 - 0.5 * math.cos(math.pi * q))
    left = dur - u
    if left < OUT_T:
        p = 1 - left / OUT_T
        if p < 0.35:
            return 1 + 0.12 * math.sin(p / 0.35 * math.pi / 2)
        q = (p - 0.35) / 0.65; return 1.12 * (1 - q * q)
    return 1.0


class Sticker:
    def __init__(self, d, idx):
        self.d = d; self.idx = idx
        self.kind = d['kind']; self.t = float(d['t']); self.dur = float(d.get('dur', 1.6))
        self.motion = d.get('motion') or MOTION_DEFAULT.get(self.kind, 'pop')
        self.group = str(d.get('group', ''))
        self.burst = self.group.startswith('burst')
        self.phase = (idx * 1.618) % (2 * math.pi)
        self.sprite = None; self.key = None; self.blink = float(d.get('blink', 1.6)); self.clip_px = None; self.clipf = None

    def setup(self, W, H):
        key = aspect_key(W, H); self.key = key; self.W, self.H = W, H
        self.short = min(W, H)
        self.x, self.y = per_aspect(self.d.get('pos'), key, [0.5, 0.5])
        self.size = float(per_aspect(self.d.get('size'), key, 0.12))
        self.rot = float(per_aspect(self.d.get('rot'), key, 0) or 0)
        self.rise = float(per_aspect(self.d.get('rise'), key, 0.22))
        self.geom()
        if self.kind == 'confetti':
            self.setup_confetti(); return
        if self.kind in LIVE:
            live_setup(self); return
        S = max(8, int(round(self.size * self.short * 1.2)))
        self.sprite = make_sprite(self.kind, S, self.d.get('color'),
                                  {k: per_aspect(v, self.key, v) if k in ('text', 'tail', 'style') else v for k, v in self.d.items()})
        self.base_scale = 1 / 1.2

    def geom(self):
        c = per_aspect(self.d.get('clip'), self.key, None) if self.kind != 'confetti' else None
        self.clipf = c
        self.clip_px = (c[0] * self.W, c[1] * self.H, c[2] * self.W, c[3] * self.H) if c else None

    # where and how big at time t (centre px, scale, rotation deg, alpha, dx dy)
    def state(self, t):
        u = t - self.t; dur = self.dur
        if u < 0 or u >= dur:
            return None
        s = pop_scale(u, dur); rot = self.rot; alpha = 1.0; dx = dy = 0.0
        if u < IN_T:
            rot += -18 * (1 - ease_out(u / IN_T)) * (1 if self.idx % 2 else -1)
            alpha = min(1.0, u / 0.05 + 0.4)
        hold = u - IN_T
        if self.motion == 'float':
            p = max(0.0, u) / dur
            dy = -self.rise * self.short * (p ** 0.9)
            dx = 0.018 * self.short * math.sin(2 * math.pi * 0.7 * u + self.phase)
            rot += 9 * math.sin(2 * math.pi * 0.7 * u + self.phase)
            if u > IN_T and dur - u < 0.45:                       # fade and shrink instead of popping out
                k = (dur - u) / 0.45; alpha = k; s = 0.8 + 0.2 * k
            elif u >= IN_T:
                s = 1.0
        elif self.motion == 'wave':
            if hold > 0:
                rot += 14 * math.sin(2 * math.pi * 2.0 * hold) * min(1, hold / 0.15)
                s *= 1 + 0.03 * math.sin(2 * math.pi * 1.5 * hold + self.phase)
        elif self.motion == 'shake':                              # bubbles: a shake on landing, then a gentle sway
            if hold > 0:
                k = math.exp(-hold * 3.5)
                rot += 8 * math.sin(2 * math.pi * 6.5 * hold) * k + 4 * math.sin(2 * math.pi * 1.1 * hold + self.phase) * (1 - k)
                dx = 0.007 * self.short * math.sin(2 * math.pi * 9 * hold) * k
                s *= 1 + 0.04 * math.sin(2 * math.pi * 1.6 * hold + self.phase)
        elif self.motion == 'blink':                              # twinkles: blink and turn while they hold
            if hold > 0:
                b = 0.5 + 0.5 * math.cos(2 * math.pi * self.blink * hold)
                s *= 0.35 + 0.65 * b ** 1.5
                rot += 50 * hold
        elif self.motion == 'rise':                               # balloons: rise and sway, fade at the end
            p = u / dur
            dy = -self.rise * self.short * p
            dx = 0.03 * self.short * math.sin(2 * math.pi * 0.45 * u + self.phase)
            rot = self.rot + 7 * math.sin(2 * math.pi * 0.45 * u + self.phase + 0.6)
            s = 1.0 if u > 0.25 else 0.6 + 0.4 * ease_out(u / 0.25)
            alpha = 1.0 if dur - u > 0.4 else max(0.0, (dur - u) / 0.4)
        elif self.motion == 'bounce':
            if hold > 0:
                dy = -0.035 * self.short * abs(math.sin(2 * math.pi * 1.3 * hold + self.phase))
                rot += 4 * math.sin(2 * math.pi * 1.3 * hold + self.phase)
        else:                                                     # pop: wobble + breathe while it holds
            if hold > 0:
                rot += 6 * math.sin(2 * math.pi * 1.25 * hold + self.phase) * min(1, hold / 0.2)
                s *= 1 + 0.035 * math.sin(2 * math.pi * 1.7 * hold + self.phase)
        return self.x * self.W + dx, self.y * self.H + dy, s, rot, alpha

    def bbox(self, t):
        """Approximate box (fractions) of the art at t, for the checks."""
        st = self.state(t)
        if st is None or self.kind == 'confetti':
            return None
        cx, cy, s, _, _ = st
        half = self.size * self.short * max(s, 1.0) * 0.55
        return ((cx - half) / self.W, (cy - half) / self.H, (cx + half) / self.W, (cy + half) / self.H)

    def boxes(self, t):
        if self.kind in LIVE:
            return live_boxes(self, t)
        b = self.bbox(t)
        if b is None:
            return []
        if self.clipf:
            c = self.clipf
            b = (max(b[0], c[0]), max(b[1], c[1]), min(b[2], c[2]), min(b[3], c[3]))
            if b[2] <= b[0] or b[3] <= b[1]:
                return []
        return [b]

    def draw(self, frame, t):
        if self.kind in LIVE:
            return live_draw(self, frame, t)
        if self.kind == 'confetti':
            return self.draw_confetti(frame, t)
        st = self.state(t)
        if st is None:
            return
        cx, cy, s, rot, alpha = st
        s *= self.base_scale
        w0, h0 = self.sprite.size
        w, h = max(1, int(round(w0 * s))), max(1, int(round(h0 * s)))
        im = self.sprite.resize((w, h), Image.BICUBIC) if (w, h) != (w0, h0) else self.sprite
        if abs(rot) > 0.05:
            im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
        composite(frame, im, cx, cy, alpha, self.clip_px)

    # ---- confetti ----
    def setup_confetti(self):
        rng = np.random.default_rng(1000 + self.idx)
        n = int(self.d.get('count', 36)); sp = float(self.d.get('speed', 1.0))
        lo, hi = self.d.get('spread', [-150, -30])
        cols = ['#FF7AC8', '#F0347F', '#FFE45C', '#7BF7C8', '#7CC8FF', '#B68CFF', '#FFA24C', '#FFFFFF']
        self.parts = []
        unit = self.size * self.short if 'size' in self.d else 0.02 * self.short
        for i in range(n):
            shape = ['rect', 'rect', 'circle', 'star'][i % 4]
            c = cols[int(rng.integers(len(cols)))]
            sz = unit * rng.uniform(0.7, 1.25)
            spr = confetti_sprite(shape, c, sz)
            ang = math.radians(rng.uniform(lo, hi)); v = self.short * sp * rng.uniform(0.9, 1.9)
            self.parts.append(dict(spr=spr, vx=v * math.cos(ang), vy=v * math.sin(ang), spin=rng.uniform(-540, 540),
                                   flip=rng.uniform(4, 9), ph=rng.uniform(0, 6.28), delay=rng.uniform(0, 0.08),
                                   a0=rng.uniform(0, 360)))
        self.clip = per_aspect(self.d.get('clip'), self.key, None)

    def draw_confetti(self, frame, t):
        u = t - self.t
        if u < 0 or u >= self.dur:
            return
        k = 2.6; g = 1.6 * self.short
        x0, y0 = self.x * self.W, self.y * self.H
        for p in self.parts:
            tt = u - p['delay']
            if tt < 0:
                continue
            e = (1 - math.exp(-k * tt)) / k
            x = x0 + p['vx'] * e + 0.02 * self.short * math.sin(p['flip'] * 0.5 * tt + p['ph'])
            y = y0 + p['vy'] * e + g / k * (tt - e)
            alpha = 1.0 if tt < self.dur * 0.65 else max(0.0, (self.dur - u) / (self.dur * 0.35))
            if self.clip:
                cx0, cy0, cx1, cy1 = self.clip
                fx, fy = x / self.W, y / self.H
                m = min(fx - cx0, cx1 - fx, fy - cy0, cy1 - fy)
                if m <= 0:
                    continue
                alpha *= min(1.0, m / 0.025)
            spr = p['spr']; w0, h0 = spr.size
            fw = max(1, int(round(w0 * max(0.15, abs(math.cos(p['flip'] * tt + p['ph']))))))
            im = spr.resize((fw, h0), Image.BICUBIC).rotate(p['a0'] + p['spin'] * tt, resample=Image.BICUBIC, expand=True)
            composite(frame, im, x, y, alpha)


_conf_cache = {}


def confetti_sprite(shape, c, sz):
    key = (shape, c, int(sz))
    if key in _conf_cache:
        return _conf_cache[key]
    S = max(4, int(sz)) * 4
    m = Image.new('L', (S, S), 0); d = ImageDraw.Draw(m)
    if shape == 'rect':
        d.rectangle([S * 0.1, S * 0.3, S * 0.9, S * 0.7], fill=255)
    elif shape == 'circle':
        d.ellipse([S * 0.2, S * 0.2, S * 0.8, S * 0.8], fill=255)
    else:
        d.polygon([(S / 2 + S * 0.45 * math.cos(math.radians(-90 + i * 36)) * (1 if i % 2 == 0 else 0.45),
                    S / 2 + S * 0.45 * math.sin(math.radians(-90 + i * 36)) * (1 if i % 2 == 0 else 0.45)) for i in range(10)], fill=255)
    col = Image.new('RGBA', (S, S), rgb(c) + (0,)); col.putalpha(m)
    im = col.convert('RGBa').resize((S // 4, S // 4), Image.LANCZOS)
    _conf_cache[key] = im
    return im


def composite(frame, im, cx, cy, alpha=1.0, clip=None):
    """Premultiplied 'RGBa' PIL image onto an HxWx3 uint8 frame (in place), centred at (cx, cy), clipped to the frame."""
    H, W = frame.shape[:2]
    arr = np.asarray(im, np.float32) / 255.0
    h, w = arr.shape[:2]
    x0 = int(round(cx - w / 2)); y0 = int(round(cy - h / 2))
    fx0, fy0 = max(0, x0), max(0, y0); fx1, fy1 = min(W, x0 + w), min(H, y0 + h)
    if clip:
        fx0, fy0 = max(fx0, int(clip[0])), max(fy0, int(clip[1])); fx1, fy1 = min(fx1, int(clip[2])), min(fy1, int(clip[3]))
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sub = arr[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = sub[..., 3:4] * alpha; c = sub[..., :3] * alpha
    reg = frame[fy0:fy1, fx0:fx1].astype(np.float32) / 255.0
    frame[fy0:fy1, fx0:fx1] = np.clip((c + reg * (1 - a)) * 255 + 0.5, 0, 255).astype(np.uint8)


def load_plan(path, faces=None):
    with open(path, encoding='utf-8') as f:
        spec = json.load(f)
    if faces:
        spec['avoid'] = list(spec.get('avoid', [])) + [a for p in faces for a in faces_avoid(p)]
    sts = [Sticker(d, i) for i, d in enumerate(spec.get('stickers', []))]
    return spec, sts


def validate_faces(fj):
    """tools/vision/faces.py's own validate(); raises ValueError."""
    vision = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'tools', 'vision'))
    if vision not in sys.path:
        sys.path.insert(0, vision)
    try:
        import faces as _faces
    except ImportError:                                    # tools/vision missing: the minimum this file needs
        if not (isinstance(fj, dict) and isinstance(fj.get('size'), list) and len(fj['size']) == 2
                and isinstance(fj.get('faces'), list)):
            raise ValueError('not a faces.json (needs "size": [W, H] and "faces": [...])')
        return True
    return _faces.validate(fj)


def faces_avoid(path):
    """Avoid entries from a tools/vision/faces.py faces.json (t202): one per face range, for the aspect of the video it
    was detected on. Its "box" is already padded (hair, hats). Raises ValueError for a file that is not a faces.json
    (faces.validate(): e.g. a faces_check report, which has no "size")."""
    with open(path, encoding='utf-8') as f:
        fj = json.load(f)                                  # a broken file: json.JSONDecodeError, a ValueError
    validate_faces(fj)
    W, H = fj['size']
    key = aspect_key(W, H)
    return [{'start': float(fc['start']), 'end': float(fc['end']), 'box': {key: [float(v) for v in fc['box']]},
             'what': f"face (auto {os.path.basename(path)} {fc['start']:.2f}-{fc['end']:.2f}s, conf {fc.get('conf', 0):.2f})",
             'auto': True} for fc in fj.get('faces', [])]


# ---------------------------------------------------------------- checks ---------------------------------------------
def overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0]); h = min(a[3], b[3]) - max(a[1], b[1])
    return w > 0 and h > 0, max(0, w) * max(0, h)


def check(spec, sts, W, H, fps=30):
    key = aspect_key(W, H); warn = []; errs = []
    for s in sts:
        if s.kind not in KINDS:
            errs.append(f"#{s.idx} unknown kind {s.kind}")
    if errs:
        return errs, warn, 0
    for s in sts:
        s.key = key; s.W, s.H = W, H; s.short = min(W, H)
        s.x, s.y = per_aspect(s.d.get('pos'), key, [0.5, 0.5]); s.size = float(per_aspect(s.d.get('size'), key, 0.12))
        s.rot = float(per_aspect(s.d.get('rot'), key, 0) or 0); s.rise = float(per_aspect(s.d.get('rise'), key, 0.22))
        s.geom()
        if s.kind in LIVE:
            live_setup(s, sprites=False)
    avoid = spec.get('avoid', [])
    maxon = int(spec.get('max_on_screen', 4)); worst = 0
    T = max((s.t + s.dur for s in sts), default=0)
    reported = set()
    for f in range(int(T * fps) + 1):
        t = f / fps
        live = [s for s in sts if s.t <= t < s.t + s.dur]
        n = sum(1 for s in live if not s.burst and s.kind not in ('confetti', 'wipe'))
        worst = max(worst, n)
        if n > maxon and ('max', round(t)) not in reported:
            reported.add(('max', round(t))); warn.append(f"{key} {t:.2f}s: {n} stickers on screen outside a burst (max {maxon})")
        for s in live:
            if s.kind == 'wipe':                                  # a transition covers the whole frame for ~10 frames
                continue
            for b in s.boxes(t):
                if (b[0] < -0.02 or b[2] > 1.02 or b[1] < -0.02 or b[3] > 1.02) and ('edge', s.idx) not in reported \
                        and not s.clipf and s.motion != 'rise':
                    reported.add(('edge', s.idx)); warn.append(f"{key} #{s.idx} {s.kind} at {t:.2f}s runs off the frame {tuple(round(v, 2) for v in b)}")
                for j, av in enumerate(avoid):
                    if not (av['start'] <= t <= av['end']):
                        continue
                    bx_ = av.get('box')
                    box = (bx_.get(key) or bx_.get('default')) if isinstance(bx_, dict) else bx_   # no borrowing between sizes
                    if box is None:
                        continue
                    hit, area = overlap(b, box)
                    if hit and area > 0.0004 and (s.idx, j) not in reported:
                        reported.add((s.idx, j))
                        warn.append(f"{key} #{s.idx} {s.kind} at {t:.2f}s touches avoid box '{av.get('what', j)}'")
    cut = [s for s in sts if s.group == 'cut']
    for a, b in zip(cut, cut[1:]):
        if a.kind == b.kind:
            warn.append(f"cut stickers #{a.idx} and #{b.idx} are both {a.kind}")
    return errs, warn, worst


# ---------------------------------------------------------------- video ----------------------------------------------
def probe(video):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
                        '-show_entries', 'format=duration', '-of', 'json', video], capture_output=True, text=True, creationflags=NOWIN)
    j = json.loads(p.stdout); s = j['streams'][0]
    num, den = s['r_frame_rate'].split('/')
    return int(s['width']), int(s['height']), float(num) / float(den), float(j['format']['duration'])


def board(task, pct, msg):
    if not task:
        return
    hq = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'hq', 'tasks.js')
    hq = os.path.normpath(hq)
    try:
        subprocess.run(['node', hq, 'progress', task, str(int(pct)), msg], capture_output=True, timeout=20, creationflags=NOWIN)
    except Exception:
        pass


def render(video, plan_path, dest, sfx_in=None, sfx_out=None, t_from=None, t_to=None, task=None, pct=None, faces=None):
    W, H, fps, dur = probe(video)
    spec, sts = load_plan(plan_path, faces)
    errs, warns, _ = check(spec, sts, W, H, fps)
    if errs:
        out(ok=False, errors=errs); sys.exit(1)
    for s in sts:
        s.setup(W, H)
    f0 = int(round((t_from or 0) * fps))
    f1 = int(round((t_to if t_to is not None else dur) * fps))
    nfr = max(0, f1 - f0)
    dec = [FF, '-v', 'error']
    if t_from:
        dec += ['-ss', f'{t_from:.4f}']
    dec += ['-i', video, '-frames:v', str(nfr), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
    enc = [FF, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', f'{fps:g}', '-i', '-']
    if t_from:
        enc += ['-ss', f'{t_from:.4f}']
    enc += ['-i', video, '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
            '-pix_fmt', 'yuv420p', '-c:a', 'copy']
    if t_to is not None or t_from:
        enc += ['-t', f'{nfr / fps:.4f}']
    enc += ['-movflags', '+faststart', dest]
    pd = subprocess.Popen(dec, stdout=subprocess.PIPE, creationflags=NOWIN)
    pe = subprocess.Popen(enc, stdin=subprocess.PIPE, creationflags=NOWIN)
    lo, hi = (pct or '50:85').split(':') if task else (0, 0)
    lo, hi = float(lo), float(hi)
    fsz = W * H * 3; n = 0; step = max(1, nfr // 10)
    order = sorted(sts, key=lambda s: (0 if s.kind == 'confetti' else 2 if s.kind == 'wipe' else 1, s.size, s.idx))   # confetti under, wipes over all
    while n < nfr:
        raw = pd.stdout.read(fsz)
        if len(raw) < fsz:
            break
        t = (f0 + n) / fps
        live = [s for s in order if s.t <= t < s.t + s.dur]
        if live:
            fr = np.frombuffer(raw, np.uint8).reshape(H, W, 3).copy()
            for s in live:
                s.draw(fr, t)
            raw = fr.tobytes()
        pe.stdin.write(raw); n += 1
        if task and n % step == 0:
            board(task, lo + (hi - lo) * n / nfr, f"RENDER · stickers frame {n}/{nfr}")
    pe.stdin.close(); pe.wait(); pd.wait()
    res = dict(ok=pe.returncode == 0 and n == nfr, out=dest, frames=n, expected=nfr, size=f'{W}x{H}', aspect=aspect_key(W, H),
               stickers=len(sts), warnings=warns)
    if sfx_in or sfx_out:
        res.update(merge_sfx(sts, fps, sfx_in, sfx_out, dur, spec.get('sfx_adjust')))
    out(**res)


def merge_sfx(sts, fps, sfx_in, sfx_out, dur, adjust=None):
    base = {'events': []}
    if sfx_in and os.path.exists(sfx_in):
        with open(sfx_in, encoding='utf-8') as f:
            base = json.load(f)
    evs = list(base.get('events', []))
    for e in evs:
        e.setdefault('frame', int(round(float(e.get('t', 0)) * fps)))
    for a in adjust or []:
        for e in evs:
            if int(e['frame']) == int(a['frame']):
                if a.get('sound'):
                    e['sound'] = a['sound']
                e['db'] = float(e.get('db', 0)) + float(a.get('db', 0))
                e['what'] = f"{e.get('what', '')} (level {float(a.get('db', 0)):+g} dB: {a.get('why', '')})"
    taken = [int(e['frame']) for e in evs]
    added, dropped = 0, []
    for s in sorted(sts, key=lambda s: s.t):
        snd = s.d.get('sfx', None if s.kind == 'confetti' else 'pop')
        if not snd:
            continue
        fr = int(round((s.t + float(s.d.get('sfx_offset', 0))) * fps))
        if fr >= int(dur * fps):
            continue
        near = [f for f in taken if abs(f - fr) <= 2]
        if near:
            dropped.append(f"#{s.idx} {s.kind} at frame {fr} (another sound at {near[0]})"); continue
        evs.append({'frame': fr, 'sound': snd, 'db': float(s.d.get('sfx_db', -2)),
                    'what': f"sticker pop: {s.d.get('what', s.kind)}"})
        taken.append(fr); added += 1
    evs.sort(key=lambda e: int(e['frame']))
    res = {'fps': round(fps, 3), 'events': evs, 'note': 'video events + one sound per sticker pop (stickers.py)'}
    with open(sfx_out, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return dict(sfx_out=sfx_out, sfx_added=added, sfx_total=len(evs), sfx_dropped=dropped)


# ---------------------------------------------------------------- sheet / swatch ------------------------------------
def sheet(video, dest, every=1.0, at=None, cols=8, width=240, boxes=None):
    W, H, fps, dur = probe(video)
    times = at or [round(i * every + every / 2 if every >= 1 else i * every, 3) for i in range(int(dur / every))]
    times = [min(t, dur - 1 / fps) for t in times]
    th = int(width * H / W); rows = (len(times) + cols - 1) // cols
    sh = Image.new('RGB', (cols * (width + 6) + 6, rows * (th + 22) + 6), (14, 14, 18)); d = ImageDraw.Draw(sh)
    spec = None
    if boxes:
        with open(boxes, encoding='utf-8') as f:
            spec = json.load(f)
    for i, t in enumerate(times):
        p = subprocess.run([FF, '-v', 'error', '-ss', f'{t:.3f}', '-i', video, '-frames:v', '1', '-vf', f'scale={width}:{th}',
                            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, creationflags=NOWIN)
        if len(p.stdout) < width * th * 3:
            continue
        im = Image.frombuffer('RGB', (width, th), p.stdout[:width * th * 3])
        x, y = 6 + (i % cols) * (width + 6), 6 + (i // cols) * (th + 22)
        sh.paste(im, (x, y + 16))
        d.text((x + 2, y + 2), f'{t:.2f}s', fill=(255, 230, 0))
        if spec:
            key = aspect_key(W, H)
            for av in spec.get('avoid', []):
                if av['start'] <= t <= av['end']:
                    bx_ = av.get('box'); b = (bx_.get(key) or bx_.get('default')) if isinstance(bx_, dict) else bx_
                    if b:
                        d.rectangle([x + b[0] * width, y + 16 + b[1] * th, x + b[2] * width, y + 16 + b[3] * th], outline=(255, 40, 40))
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
    sh.save(dest, quality=88)
    out(ok=True, out=dest, frames=len(times))


def swatch(dest):
    kinds = [k for k in KINDS if k != 'confetti' and k not in LIVE]
    cell = 220; cols = 5; rows = (len(kinds) + cols - 1) // cols
    im = Image.new('RGB', (cols * cell, rows * cell), (120, 150, 170))
    fr = np.array(im)
    for i, k in enumerate(kinds):
        spr = make_sprite(k, 140)
        composite(fr, spr, (i % cols) * cell + cell / 2, (i // cols) * cell + cell / 2)
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
    Image.fromarray(fr).save(dest)
    out(ok=True, out=dest, kinds=kinds)


# ---------------------------------------------------------------- cli ------------------------------------------------
def opt(args, name, n=1, default=None):
    if name in args:
        i = args.index(name); v = args[i + 1:i + 1 + n]; del args[i:i + 1 + n]
        return v if n > 1 else v[0]
    return default


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    cmd = args.pop(0)
    faces = []                                            # --faces faces.json, repeatable (t202)
    while '--faces' in args:
        faces.append(opt(args, '--faces'))
    for p in faces:
        if not os.path.exists(p):
            raise SystemExit(f'no such faces file: {p}')
        try:
            faces_avoid(p)
        except (ValueError, KeyError, TypeError) as e:
            raise SystemExit(f'{p} is not a faces.json from tools/vision/faces.py: {e}')
    if cmd == 'plan':
        asp = opt(args, '--aspect')
        spec, sts = load_plan(args[0], faces)
        sizes = {'9x16': (1080, 1920), '16x9': (1920, 1080)}
        res = {}
        allok = True
        for k, (W, H) in sizes.items():
            if asp and asp != k:
                continue
            errs, warns, worst = check(spec, sts, W, H)
            res[k] = dict(errors=errs, warnings=warns, max_on_screen_outside_bursts=worst)
            allok &= not errs
        for s in sorted(sts, key=lambda s: s.t):
            print(f"{s.t:6.2f}-{s.t + s.dur:6.2f}  #{s.idx:<3} {s.kind:<11} {s.group:<12} {s.d.get('what', '')}")
        out(ok=allok, stickers=len(sts), **res)
    elif cmd == 'render':
        sfx = opt(args, '--sfx-events', 2)
        t_from = opt(args, '--from'); t_to = opt(args, '--to')
        task = opt(args, '--task', default=os.environ.get('HQ_TASK')); pct = opt(args, '--pct', default=os.environ.get('HQ_PCT'))
        render(args[0], args[1], args[2], *(sfx or (None, None)), float(t_from) if t_from else None,
               float(t_to) if t_to else None, task, pct, faces)
    elif cmd == 'sfx':
        W, H, fps, dur = probe(args[0])
        spec, sts = load_plan(args[1])
        out(ok=True, **merge_sfx(sts, fps, args[2], args[3], dur, spec.get('sfx_adjust')))
    elif cmd == 'sheet':
        every = float(opt(args, '--every', default=1)); at = opt(args, '--at'); cols = int(opt(args, '--cols', default=8))
        width = int(opt(args, '--width', default=240)); boxes = opt(args, '--boxes')
        sheet(args[0], args[1], every, [float(x) for x in at.split(',')] if at else None, cols, width, boxes)
    elif cmd == 'swatch':
        swatch(args[0])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
