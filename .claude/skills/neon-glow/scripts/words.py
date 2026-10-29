"""Kinetic words for the ordinary (non-neon) lines of Neon Glow: each line gets a placement and a word animation, varied
line by line so the wording keeps moving, plus one emphasised word in warm gold glow.

Placements: center, left, right, stagger (each word or pair on its own row, alternating offset and size), tilt (the
line turned about 5 degrees). Animations (per word, at the moment it is spoken): rise, pop, slide, drop, wave, zoom, flash.
Plan line fields "place" / "anim" / "emph" override the automatic choice; plan "auto_motion": false keeps every ordinary
line centred with the rise.
"""
import math, re
import numpy as np
from PIL import Image
import ng
from ng import cc, F1, FPS, display, is_cjk, keys, ease_out

W, H = 1080, 1920
PLACES = ("center", "left", "stagger", "right")       # no tilt: the owner wants words animated, never rotated
ANIMS = ("rise", "pop", "slide", "drop", "wave", "zoom", "flash")
STOP = set("a an the and or but if to of in on at for with from by is are was were be been am we you he she it they i me my our your "
           "his her their them us that this these those so then than as not do does did can will would could should has have had "
           "when what which who how why there here just very also into out up down all any some no".split())
cc.PALETTE["emph"] = ("#FFF4C4", "#E8C24E", "#F2CF5E")
SHADOW = ("#0A0C10", 7, 5, 0.85)


def unit_image(text, size, colour):
    gl, ink = cc.styled_line(text, "hook", size, colour, glow=(colour == "emph"), shadow=SHADOW, glow_r=max(8, size * 0.14))
    if not gl:
        return None, ink
    xs0 = [g["cx"] - g["img"].width / 2 for g in gl]; xs1 = [g["cx"] + g["img"].width / 2 for g in gl]
    ys0 = [g["cy"] - g["img"].height / 2 for g in gl]; ys1 = [g["cy"] + g["img"].height / 2 for g in gl]
    X0, Y0, X1, Y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    cv = Image.new("RGBA", (int(X1 - X0) + 2, int(Y1 - Y0) + 2), (0, 0, 0, 0))
    for g, x, y in zip(gl, xs0, ys0):
        cv.alpha_composite(g["img"], (int(round(x - X0)), int(round(y - Y0))))
    # anchor: the canvas centre sits at ink centre + (X0 + X1) / 2, (Y0 + Y1) / 2
    return {"img": cv, "ox": (X0 + X1) / 2, "oy": (Y0 + Y1) / 2}, ink


def tokens(ln, text):
    """Word units with spoken times: Latin words, or Chinese grouped two characters at a time."""
    times = ng.disp_times(ln, text)
    out, i, n = [], 0, len(text)
    cjk = any(is_cjk(c) for c in text)
    while i < n:
        if not text[i].strip():
            i += 1; continue
        if is_cjk(text[i]):
            j = i + 1
            while j < n and j - i < 2 and is_cjk(text[j]):
                j += 1
        else:
            j = i
            while j < n and text[j].strip() and not is_cjk(text[j]):
                j += 1
        out.append({"text": text[i:j], "t": times[i]}); i = j
    if cjk and len(out) > 1 and len(out[-1]["text"]) == 1:          # no lone last character
        out[-2]["text"] += out[-1]["text"]; out.pop()
    return out


def pick_emph(units, given):
    if given:
        for k, u in enumerate(units):
            if given in u["text"] or u["text"] in given:
                return k
        return None
    best, bk = 0, None
    for k, u in enumerate(units):
        w = re.sub(r"[^A-Za-z']", "", u["text"]).lower()
        if w and w not in STOP and len(w) > best:
            best, bk = len(w), k
    return bk if best >= 4 else None


class WordLine:
    def __init__(self, ln, place, anim, emph=None, seed=0):
        text = display(ln["text"]).strip()
        place = "center" if place == "tilt" else place          # words are never rotated
        self.place, self.anim, self.seed = place, anim, seed
        self.units = tokens(ln, text)
        if not self.units:
            self.units = [{"text": text, "t": ln["start"]}]
        cjk = any(is_cjk(c) for c in text)
        ek = pick_emph(self.units, emph)
        n = len(self.units)
        base = 134 if n <= 4 else 116 if n <= 7 else 100
        if place == "stagger":
            base = 146 if n <= 4 else 122
        for k, u in enumerate(self.units):
            big = (k == ek)
            size = base * (1.4 if big else 1.0)
            if place == "stagger":
                size *= (1.18, 0.86, 1.04)[k % 3] if not big else 1.15
            u["size"] = size
            u["sprite"], u["ink"] = unit_image(u["text"], size, "emph" if big else "chrome")
            if u["ink"][0] > 860:                                   # never wider than the safe area
                size = float(size * 860 / float(u["ink"][0])); u["size"] = size
                u["sprite"], u["ink"] = unit_image(u["text"], size, "emph" if big else "chrome")
            u["emph"] = big
        self.layout(cjk)
        self.t_in = min(u["t"] for u in self.units)

    # ---- placement ------------------------------------------------------------------------------------------------------
    def layout(self, cjk):
        gap = lambda u: 0 if cjk else u["size"] * 0.34
        maxw = 940 if self.place in ("center", "tilt") else 860
        rows, cur, wsum = [], [], 0.0
        if self.place == "stagger":
            per = 1 if len(self.units) <= 4 else 2
            rows = [self.units[i:i + per] for i in range(0, len(self.units), per)]
        else:
            for u in self.units:
                w = u["ink"][0]
                if cur and wsum + gap(u) + w > maxw:
                    rows.append(cur); cur, wsum = [], 0.0
                wsum += (gap(u) if cur else 0) + w; cur.append(u)
            if cur:
                rows.append(cur)
        for r in rows:                                            # a row never wider than the safe area
            rw = sum(u["ink"][0] for u in r) + sum(gap(u) for u in r[1:])
            if rw > 930:
                k = 930 / rw
                for u in r:
                    u["size"] = float(u["size"] * k)
                    u["sprite"], u["ink"] = unit_image(u["text"], u["size"], "emph" if u["emph"] else "chrome")
        heights = [max(max(u["ink"][1], u["size"] * 0.78) for u in r) for r in rows]
        lead = 1.16 if self.place != "tilt" else 1.3
        total = sum(h * lead for h in heights)
        cy0 = {"center": 0.66, "tilt": 0.63, "left": 0.6, "right": 0.6, "stagger": 0.58}[self.place] * H - total / 2
        if cy0 + total > 1420:
            cy0 = 1420 - total
        y = cy0
        for r_i, (r, hgt) in enumerate(zip(rows, heights)):
            rw = sum(u["ink"][0] for u in r) + sum(gap(u) for u in r[1:])
            if self.place == "left":
                x = 90
            elif self.place == "right":
                x = max(70, 990 - rw)
            elif self.place == "stagger":
                x = W / 2 - rw / 2 + (110 if r_i % 2 else -110) * (1 if (self.seed % 2) else -1)
                x = min(max(x, 70), 1010 - rw)
            else:
                x = W / 2 - rw / 2
            cy = y + hgt * lead / 2
            for k, u in enumerate(r):
                if k:
                    x += gap(u)
                u["x"], u["y"] = x + u["ink"][0] / 2, cy + (hgt - u["ink"][1]) * 0.35
                x += u["ink"][0]
            y += hgt * lead
        self.cx = W / 2; self.cy = cy0 + total / 2
        self.angle = 0.0
        if self.place == "tilt":
            self.angle = 5.0 if self.seed % 2 else -5.0
            th = math.radians(self.angle)
            for u in self.units:
                dx, dy = u["x"] - self.cx, u["y"] - self.cy
                u["x"] = self.cx + dx * math.cos(th) + dy * math.sin(th)
                u["y"] = self.cy - dx * math.sin(th) + dy * math.cos(th)

    # ---- animation -----------------------------------------------------------------------------------------------------------
    def draw(self, fr, t, t_out):
        q = 0.0 if t <= t_out else (t - t_out) * FPS / 5
        if q >= 1:
            return
        hold = max(0.0, t - self.t_in)
        if not hasattr(self, "plate"):
            xs = [u["x"] for u in self.units]; ys = [u["y"] for u in self.units]
            w = max(xs) - min(xs) + max(u["ink"][0] for u in self.units) + 200
            h = max(ys) - min(ys) + max(u["ink"][1] for u in self.units) + 220
            self.plate = (plate(min(w, 1300), h), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
        env = min(1.0, (t - self.t_in) * FPS / 5) * (1 - q)
        cc.put(fr, self.plate[0], self.plate[1], self.plate[2], 1.0, alpha=0.42 * env)
        for k, u in enumerate(self.units):
            sp = u["sprite"]
            if sp is None:
                continue
            f = (t - u["t"] + 1 * F1) * FPS
            if f < 0:
                continue
            x, y = u["x"], u["y"]
            s, rot, a, blur, mb, br = 1.0, self.angle, 1.0, 0.0, 0.0, 1.0
            an = self.anim
            if an == "rise":
                p = min(1, f / 4); y += 34 * (1 - ease_out(p)); a = 0.15 + 0.85 * ease_out(p); blur = 10 * (1 - p)
            elif an == "pop":
                s = keys(f, [0, 3, 5, 7], [0.2, 1.22, 0.95, 1.0]); a = min(1, 0.3 + f / 3); blur = keys(f, [0, 2], [6, 0])
            elif an == "slide":
                d = -1 if (k + self.seed) % 2 else 1
                x += d * 240 * (1 - ease_out(min(1, f / 5))); mb = keys(f, [0, 4], [70, 0]); a = min(1, 0.2 + f / 3)
            elif an == "drop":
                y += keys(f, [0, 4, 7, 9], [-150, 14, -4, 0]); a = min(1, 0.3 + f / 2)
                blur = keys(f, [0, 3], [5, 0])
            elif an == "wave":
                p = min(1, f / 6); y += 40 * (1 - ease_out(p)) + (10 if k % 2 else -10) * math.sin(math.pi * p)
                s = 0.6 + 0.4 * ease_out(p); a = 0.2 + 0.8 * ease_out(p)
            elif an == "zoom":
                s = keys(f, [0, 4, 6], [2.1, 0.96, 1.0]); blur = keys(f, [0, 4], [16, 0]); a = min(1, 0.15 + f / 3)
            elif an == "flash":
                br = keys(f, [0, 2, 6], [2.4, 1.6, 1.0]); s = keys(f, [0, 3, 5], [1.25, 0.98, 1.0]); a = min(1, 0.4 + f / 2)
                blur = keys(f, [0, 2], [8, 0])
            if u["emph"] and f >= 0:                           # the key word lands a beat harder and glows
                s *= keys(f, [2, 5, 8], [1.0, 1.12, 1.0])
                br = max(br, keys(f, [3, 6, 12], [1.0, 1.45, 1.0]))
            # gentle float and push while held
            y += 4.0 * math.sin(2 * math.pi * 0.6 * hold + k * 0.9)
            s *= 1 + 0.015 * min(1.0, hold / 2.0)
            if q > 0:
                a *= 1 - q; blur = max(blur, 12 * q); y -= 26 * q; s *= 1 - 0.05 * q
            ox, oy = sp["ox"], sp["oy"]
            cc.put(fr, sp["img"], x + ox * s, y + oy * s, s, 0.0, alpha=a, blur=blur, mblur=mb, bright=br)
            if u["emph"] and 3 <= f < 13:                      # a quick glint on the key word
                kk = math.sin(math.pi * (f - 3) / 10)
                cc.put(fr, ng.star(u["size"] * 0.42), x + u["ink"][0] * 0.42, y - u["ink"][1] * 0.38, 0.5 + 0.7 * kk, rot=f * 5, alpha=kk * a)


def choose(lines_meta):
    """Deterministic varied (place, anim) per ordinary line: never the same placement or animation twice in a row."""
    out, lp, la = [], None, None
    for i, (lid, ntok, cjk) in enumerate(lines_meta):
        places = [p for p in PLACES if not (p == "stagger" and ntok > 6)]
        p = places[(lid * 3 + 1) % len(places)]
        if p == lp:
            p = places[(places.index(p) + 1) % len(places)]
        a = ANIMS[(lid * 5 + 2) % len(ANIMS)]
        if a == la:
            a = ANIMS[(ANIMS.index(a) + 1) % len(ANIMS)]
        out.append((p, a)); lp, la = p, a
    return out


_PL = {}


def plate(w, h):
    from PIL import ImageDraw, ImageFilter
    key = (int(w) // 10, int(h) // 10)
    if key not in _PL:
        m = Image.new("L", (int(w) // 4 + 2, int(h) // 4 + 2), 0)
        ImageDraw.Draw(m).ellipse((m.width * 0.1, m.height * 0.15, m.width * 0.9, m.height * 0.85), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(min(m.width, m.height) * 0.18)).resize((int(w), int(h)), Image.BILINEAR)
        im = Image.new("RGBA", (int(w), int(h)), (5, 5, 4, 0)); im.putalpha(m); _PL[key] = im
    return _PL[key]
