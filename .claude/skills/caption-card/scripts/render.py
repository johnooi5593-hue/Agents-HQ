"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--frame crop|blur] [--crop X:Y:W:H] [--focus 0.5] [--to SECONDS]
                        [--no-punch] [--phone] [--no-text] [--preset medium]

Every line is a caption card: a cyan box with blue slanted words, 2-6 characters (or 1-3 English words) at a time, hard
cuts on the first word of each chunk. A line with "kind" gets a big-type moment instead of cards, built with the pro
layered type (heavy face, top-light gradient, dark soft shadow, outer glow, background blurred and dimmed underneath):
  hook     up to 3 rows; rows blur in as spoken; the key row scatters wide and small, gathers with overshoot, ghosts once
  number   a giant number (0.47 of the frame) grows from spread digits 0.45 -> 1.15 -> 0.97 -> 1.0; optional label above
           (tracking collapses) and unit beside it; exit swells 8 % and brightens, then shrinks and blurs away
  writeon  a phrase drawn on left to right like a light pen (each character 4 f, 2 f apart, a motion trail); optional sub
           line; exit blooms into light
  punch    the picture punches in 1.35x; each character slams in 2 f apart: 0.4 -> 1.35 -> 1.0, tilted +-15 -> 0
Line "transition": "flash" (3-frame white) or "blurcut" (the new shot starts blurred and sharpens in 3 frames).
Writes <out>.mp4, <out>.srt, <out>.pk.json (events for the poster-kinetic preview.py), <out>.sfx-events.json (for the sfx
skill), a copy of plan.json; --phone also writes <out>_phone.mp4 under 28 MiB. Prints one JSON line.
"""
import argparse, math, os, queue, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cc  # noqa: E402
from cc import (CARD, DEFAULT_COLOR, F1, FFMPEG, FPS, SAFE, ease_expo, ease_io, ease_out, keys, layout, load,  # noqa: E402
                put, report, rgb, save, styled_line, sub_time, char_times, display, is_cjk, fit_size)

W, H = 1080, 1920


# ---- caption cards ----------------------------------------------------------------------------------------------------
def chunk_words(ln):
    """Words -> card chunks: 2-6 CJK characters or 1-3 Latin words, never across a pause > 0.35 s or a sentence end."""
    ws = [dict(w, t=display(w["t"]).strip()) for w in ln.get("words", [])]
    ws = [w for w in ws if w["t"]]
    out, cur, n = [], [], 0
    for i, w in enumerate(ws):
        cjk = any(is_cjk(c) for c in w["t"])
        size = len(w["t"]) if cjk else 1.0 if len(w["t"]) < 9 else 1.6
        limit = 6 if cjk else 3
        gap = cur and (w["start"] - cur[-1]["end"] > 0.35)
        if cur and (n + size > limit or gap):
            out.append(cur); cur, n = [], 0
        cur.append(w); n += size
        raw = ln.get("words", [])[i]["t"] if i < len(ln.get("words", [])) else ""
        if raw.strip()[-1:] in "，。！？,.!?；;" and n >= (2 if cjk else 1):
            out.append(cur); cur, n = [], 0
    if cur:
        if out and len(cur) == 1 and len(cur[0]["t"]) == 1 and len("".join(x["t"] for x in out[-1])) < 6:
            out[-1] += cur                                      # no lone single character card
        else:
            out.append(cur)
    res = []
    for ch in out:
        txt = ""
        for w in ch:
            if txt and not is_cjk(txt[-1]) and not is_cjk(w["t"][0]):
                txt += " "
            txt += w["t"]
        res.append({"text": txt, "t": ch[0]["start"], "end": ch[-1]["end"]})
    return res


class CardRenderer:
    def __init__(self, colors, y):
        self.box, self.c1, self.c2 = colors.get("box", CARD["box"]), colors.get("text", CARD["text"]), colors.get("text2", CARD["text2"])
        self.y = y; self.cache = {}

    def sprite(self, text):
        if text in self.cache:
            return self.cache[text]
        size, gs, box = fit_size(text, "card", 150, 900, None, 0.0, 70)
        tw, th = box[2] - box[0], box[3] - box[1]
        bh = int(size * 0.75); padx = int(size * 0.27)
        bw = int(tw + 2 * padx)
        cw, ch = bw + 40, int(max(th, bh) + 60)
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        cxm, cym = cw / 2, ch / 2
        ImageDraw.Draw(img).rectangle((cxm - bw / 2, cym - bh / 2, cxm + bw / 2, cym + bh / 2), fill=rgb(self.box) + (255,))
        for g in gs:
            spr, pad = cc.layered(g["mask"], self.c1, self.c2, box[1], box[3], g["y"], None, ("#0B1446", 5, 3, 0.35))
            x = cxm + g["cx"] - spr.width / 2; yy = cym + g["cy"] - spr.height / 2
            img.alpha_composite(spr, (int(round(x)), int(round(yy))))
        self.cache[text] = img
        return img

    def draw(self, fr, text):
        cc._paste(fr, self.sprite(text), W / 2, self.y)


# ---- big moments -----------------------------------------------------------------------------------------------------------
class Big:
    """One big-type moment: builds its sprites, knows its entry time and draws itself at time t."""

    def __init__(self, ln, warn):
        self.ln = ln; self.kind = ln["kind"]; self.id = ln.get("id")
        self.ct = char_times(ln); self.color = ln.get("color") or DEFAULT_COLOR[self.kind]
        self.yf = ln.get("y")
        self.events = []
        getattr(self, "build_" + self.kind)(warn)

    def t_of(self, sub):
        return sub_time(self.ln, sub, self.ct) - 2 * F1

    # hook: rows blur in, key row scatters and gathers
    def build_hook(self, warn):
        rows = self.ln["rows"]; key = self.ln.get("key_row")
        key = len(rows) - 1 if key is None else int(key)
        self.rows = []
        sizes = [210 if i == key else 150 for i in range(len(rows))]
        built = []
        for i, r in enumerate(rows):
            txt = display(r)
            s, _, b = fit_size(txt, "hook", sizes[i], 940, None, 0.0, 60)
            col = self.color if i == key else "white"
            gl, ink = styled_line(txt, "hook", s, col, glow=(i == key), shadow=("#0D0F0A", 16, 8, 0.75))
            built.append((gl, ink, s, i == key))
        gap = 14
        total = sum(ink[1] for _, ink, _, _ in built) + gap * (len(built) - 1)
        y = (self.yf or 0.5) * H - total / 2
        for i, (gl, ink, s, isk) in enumerate(built):
            cy = y + ink[1] / 2; y += ink[1] + gap
            self.rows.append({"glyphs": gl, "cy": cy, "key": isk, "t": self.t_of(rows[i]), "size": s})
            self.events.append({"t": self.rows[-1]["t"] + (0 if not isk else 5 * F1), "kind": "hook key (gathered)" if isk else "hook row",
                                "sfx": "impact" if isk else "swish_soft"})
        self.t_in = self.rows[0]["t"]; self.settle = max(r["t"] for r in self.rows) + 9 * F1

    def draw_hook(self, fr, t, out_p):
        for r in self.rows:
            f = (t - r["t"]) * FPS
            if f < 0:
                continue
            ea, eb = 1 - out_p, 18 * out_p
            if not r["key"]:
                p = min(1, f / 4)
                for g in r["glyphs"]:
                    put(fr, g["img"], W / 2 + g["cx"], r["cy"] + g["cy"] + 10 * (1 - ease_out(p)), 1.04 - 0.04 * ease_out(p),
                        alpha=(0.3 + 0.7 * ease_out(p)) * ea, blur=max(16 * (1 - ease_out(p)), eb))
            else:
                spread = keys(f, [0, 5], [2.2, 1.0]); sc = keys(f, [0, 3, 5, 7], [0.45, 1.12, 0.98, 1.0])
                bl = keys(f, [0, 4], [14, 0])
                ghost = 1.0 if 6 <= f < 9 else 0.0
                for g in r["glyphs"]:
                    x = W / 2 + g["cx"] * spread * sc; y = r["cy"] + g["cy"] * sc
                    if ghost:
                        put(fr, g["img"], x - 12, y + 4, sc * 1.06, alpha=0.35 * ea, blur=4)
                    put(fr, g["img"], x, y, sc, alpha=min(1, 0.4 + f / 3) * ea, blur=max(bl, eb))

    # number: grows from spread digits; label tracking collapses; unit beside
    def build_number(self, warn):
        num = display(self.ln["number"]).replace(" ", "")
        s, _, b = fit_size(num, "number", 1400, 790, H * 0.45, 0.0, 120)
        self.num, self.nink = styled_line(num, "number", s, self.color, glow_r=26)
        self.cy = (self.yf or 0.52) * H
        self.t_in = self.t_of(self.ln["number"]); self.settle = self.t_in + 8 * F1
        self.label = self.unit = None
        if self.ln.get("label"):
            lt = display(self.ln["label"]); ls, _, _ = fit_size(lt, "hook", 165, 900, None, 0.0, 30)
            gl, ink = styled_line(lt, "hook", ls, "white", glow=False, shadow=("#0D0F0A", 16, 8, 0.75))
            self.label = {"glyphs": gl, "ink": ink, "cy": self.cy - self.nink[1] / 2 - ink[1] / 2 - 26, "t": min(self.t_of(self.ln["label"]), self.t_in)}
        if self.ln.get("unit"):
            ut = display(self.ln["unit"]); us = max(80, self.nink[1] * 0.14)
            gl, ink = styled_line(ut, "hook", us, "white", glow=False, shadow=("#0D0F0A", 12, 6, 0.75))
            self.unit = {"glyphs": gl, "ink": ink, "cx": W / 2 + self.nink[0] / 2 + ink[0] / 2 - 10,
                         "cy": self.cy + self.nink[1] / 2 - ink[1] / 2, "t": max(self.t_in + 5 * F1, self.t_of(self.ln["unit"]))}
            if self.unit["cx"] + ink[0] / 2 > SAFE["right"] + 30:
                self.unit["cx"] = SAFE["right"] + 30 - ink[0] / 2
        top = self.cy - self.nink[1] / 2 - (self.label["ink"][1] + 26 if self.label else 0)
        if top < SAFE["top"]:
            d = SAFE["top"] - top; self.cy += d
            if self.label: self.label["cy"] += d
            if self.unit: self.unit["cy"] += d
        self.events.append({"t": self.t_in, "kind": "number (moving)", "sfx": "whoosh_zoom"})
        self.events.append({"t": self.settle + 0.2, "kind": "number (landed)", "sfx": None})

    def draw_number(self, fr, t, out_p):
        f = (t - self.t_in) * FPS
        sw = keys(out_p * 5, [0, 2, 5], [1.0, 1.08, 0.7]) if out_p > 0 else 1.0
        br = keys(out_p * 5, [0, 2, 5], [1.0, 1.5, 1.0]) if out_p > 0 else 1.0
        ob = keys(out_p * 5, [0, 2, 5], [0, 4, 20]) if out_p > 0 else 0
        oa = 1 - max(0, (out_p * 5 - 2) / 3) if out_p > 0 else 1
        if self.label:
            lf = (t - self.label["t"]) * FPS
            if lf >= 0:
                tr = keys(lf, [0, 6], [1.0, 0.0])
                for g in self.label["glyphs"]:
                    put(fr, g["img"], W / 2 + g["cx"] * (1 + tr * 0.9), self.label["cy"] + g["cy"], alpha=min(1, 0.3 + lf / 4) * oa, blur=max(8 * (1 - min(1, lf / 4)), ob))
        if f >= 0:
            sc = keys(f, [0, 3, 5, 6], [0.45, 1.15, 0.97, 1.0]) * sw
            spread = keys(f, [0, 5], [1.8, 1.0]); bl = keys(f, [0, 4], [18, 0])
            for g in self.num:
                put(fr, g["img"], W / 2 + g["cx"] * spread * sc, self.cy + g["cy"] * sc, sc, alpha=min(1, 0.3 + f / 3) * oa,
                    blur=max(bl, ob), bright=br)
        if self.unit:
            uf = (t - self.unit["t"]) * FPS
            if uf >= 0:
                us = keys(uf, [0, 2, 4], [0.5, 1.2, 1.0])
                for g in self.unit["glyphs"]:
                    put(fr, g["img"], self.unit["cx"] + g["cx"] * us, self.unit["cy"] + g["cy"] * us, us, alpha=oa, blur=ob)

    # writeon: drawn left to right with a light trail; bloom exit
    def build_writeon(self, warn):
        ph = display(self.ln["phrase"])
        s, _, b = fit_size(ph, "writeon", 340, 920, H * 0.17, 0.0, 80)
        self.gl, self.ink = styled_line(ph, "writeon", s, self.color, glow_r=22)
        self.cy = (self.yf or 0.5) * H
        self.t_in = self.t_of(self.ln["phrase"])
        n = len(self.gl); self.step = 2 if any(is_cjk(c) for c in ph) else 1
        self.settle = self.t_in + (self.step * (n - 1) + 6) * F1
        self.sub = None
        if self.ln.get("sub"):
            st = display(self.ln["sub"]); ss, _, _ = fit_size(st, "writeon", 130, self.ink[0] * 1.0 + 40, None, 0.0, 50)
            gl, ink = styled_line(st, "writeon", ss, self.color, glow_r=14)
            self.sub = {"glyphs": gl, "ink": ink, "cy": self.cy + self.ink[1] / 2 + ink[1] / 2 + 28,
                        "t": max(self.settle + 4 * F1, self.t_of(self.ln["sub"]))}
            self.settle = max(self.settle, self.sub["t"] + 3 * F1)
        self.events.append({"t": self.t_in, "kind": "writeon (drawing)", "sfx": "swish_soft"})
        self.events.append({"t": self.t_in + (self.step * (n - 1) + 6) * F1, "kind": "writeon (written)", "sfx": None})

    def draw_writeon(self, fr, t, out_p):
        f = (t - self.t_in) * FPS
        br = 1 + 0.8 * min(1, out_p * 2.5); ob = 30 * out_p; oa = 1 - max(0, (out_p - 0.4) / 0.6)
        for i, g in enumerate(self.gl):
            gf = f - self.step * i
            if gf < 0:
                continue
            p = min(1, gf / 4)
            img = g["img"]
            if p < 1:                                   # wipe the character on from the left, with a trailing streak
                w = img.width; cut = int(w * ease_out(p))
                m = Image.new("L", img.size, 0); ImageDraw.Draw(m).rectangle((0, 0, cut, img.height), fill=255)
                m = m.filter(ImageFilter.GaussianBlur(6))
                a = np.minimum(np.asarray(img.getchannel("A")), np.asarray(m)); img = img.copy(); img.putalpha(Image.fromarray(a))
                put(fr, g["img"], W / 2 + g["cx"] + 0.6 * w * (1 - p), self.cy + g["cy"], 1.0, alpha=0.45 * (1 - p), mblur=60 * (1 - p))
            put(fr, img, W / 2 + g["cx"], self.cy + g["cy"], alpha=oa, blur=ob, bright=br)
        if self.sub:
            sf = (t - self.sub["t"]) * FPS
            if sf >= 0:
                p = min(1, sf / 3)
                for g in self.sub["glyphs"]:
                    put(fr, g["img"], W / 2 + g["cx"], self.sub["cy"] + g["cy"] + 12 * (1 - p), alpha=p * oa, blur=max(8 * (1 - p), ob), bright=br)

    # punch: characters slam in one by one with overshoot and tilt
    def build_punch(self, warn):
        ph = display(self.ln["phrase"])
        target = W * 0.86
        role = "punch"                        # one face for the whole phrase: if the title face lacks a character, use the heavy sans
        if cc.PUNCH_FONT and any(not c.isascii() and c.strip() and not cc.pfonts.has_glyph(cc.PUNCH_FONT, None, c) for c in ph):
            role = "hook"
        s, _, b = fit_size(ph, role, 260, target, H * 0.14, 0.0, 70)
        self.gl, self.ink = styled_line(ph, role, s, self.color, glow_r=18, shadow=("#141A0E", 26, 14, 1.0))
        self.cy = (self.yf or 0.45) * H
        self.t_in = self.t_of(self.ln["phrase"])
        # stagger unit: each Chinese character, or each Latin word (letters of one word land together)
        self.unit_of, u, prev_cjk, gi = [], -1, None, 0
        words = []
        for ch in ph:
            if not ch.strip():
                prev_cjk = None; continue
            cj = is_cjk(ch)
            if cj or prev_cjk is not False:
                u += 1
            prev_cjk = cj
            self.unit_of.append(u)
        nunits = u + 1
        self.settle = self.t_in + (2 * (nunits - 1) + 5) * F1
        rng = np.random.default_rng(len(ph) * 31 + int(self.t_in * 7))
        self.rot = [float(rng.uniform(-15, 15)) for _ in range(nunits)]
        units = range(nunits)
        self.events.append({"t": self.t_in - 3 * F1, "kind": "punch-in", "sfx": "whoosh_fast"})
        self.events.append({"t": self.t_in + 2 * (len(units) - 1) * F1 + 2 * F1, "kind": "punch (last word lands)", "sfx": "impact"})

    def draw_punch(self, fr, t, out_p):
        f = (t - self.t_in) * FPS
        for i, g in enumerate(self.gl):
            ui = self.unit_of[i] if i < len(self.unit_of) else i
            gf = f - 2 * ui
            if gf < 0:
                continue
            sc = keys(gf, [0, 2, 4, 5], [0.4, 1.35, 0.95, 1.0]); rot = keys(gf, [0, 4], [self.rot[ui], 0])
            dx = keys(gf, [0, 3], [-60, 0])
            put(fr, g["img"], W / 2 + g["cx"] + dx, self.cy + g["cy"], sc, rot, alpha=min(1, 0.5 + gf / 2), blur=keys(gf, [0, 2], [6, 0]),
                mblur=keys(gf, [0, 2], [40, 0]))

    def draw(self, fr, t):
        if t < self.t_in - 1e-6 or t > self.t_out + 6 * F1:
            return
        out_frames = {"hook": 3, "number": 5, "writeon": 5, "punch": 1}[self.kind]
        out_p = 0.0 if t <= self.t_out else min(1.0, (t - self.t_out) * FPS / out_frames)
        if out_p >= 1:
            return
        getattr(self, "draw_" + self.kind)(fr, t, out_p)


# ---- picture effects -----------------------------------------------------------------------------------------------------
def zoom(arr, s, cy=0.4):
    if s <= 1.001:
        return arr
    w, h = W / s, H / s; x0 = (W - w) / 2; y0 = min(max(0.0, H * cy - h * cy), H - h)
    return np.asarray(Image.fromarray(arr).resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h)))


def stage(arr, e):
    """The stage under big type: blurred and dimmed by envelope e (0..1). Blur at half size for speed."""
    if e <= 0.01:
        return arr
    small = Image.fromarray(arr).resize((W // 2, H // 2), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4 * e))
    b = np.asarray(small.resize((W, H), Image.BILINEAR), np.float32)
    out = arr.astype(np.float32) * (1 - e) + b * e
    return np.clip(out * (1 - 0.32 * e), 0, 255).astype(np.uint8)


# ---- main ------------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop")
    ap.add_argument("--crop", default=None); ap.add_argument("--focus", type=float, default=0.5)
    ap.add_argument("--to", type=float, default=None)
    ap.add_argument("--no-punch", action="store_true", help="no picture punch-in on punch lines")
    ap.add_argument("--no-text", action="store_true"); ap.add_argument("--phone", action="store_true")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    t0 = time.time()
    plan = load(a.plan)
    err, warn = cc.check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    dur = cc.probe(a.video)["duration"]
    if a.to:
        dur = min(dur, a.to)
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    cards = CardRenderer(plan.get("card") or {}, (plan.get("card_y") or 0.51) * H)
    bigs, timeline = [], []                      # timeline: (t_in, t_out, text) card chunks
    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else dur
        if (ln.get("kind") or "card") != "card":
            b = Big(ln, warn)
            b.t_out = min(max(ln["end"] + 0.25, b.settle + 0.6), nxt + 0.6, dur)
            if b.t_out < b.settle + 0.5:
                warn.append(f"line {b.id}: the {b.kind} is up only {max(0, b.t_out - b.settle):.2f}s after it lands; give it a longer line")
            bigs.append(b)
        else:
            ch = cards_ = chunk_words(ln)
            for k, c in enumerate(ch):
                end = ch[k + 1]["t"] if k + 1 < len(ch) else min(ln["end"] + 0.3, nxt)
                timeline.append([max(c["t"] - F1, 0), end, c["text"]])
    for b in bigs:                                # cards wait while big type is up (one caption set at a time)
        for c in timeline:
            if c[0] < b.t_out + 6 * F1 and c[1] > b.t_in:
                if c[0] >= b.t_in:
                    c[0] = b.t_out + 6 * F1
                else:
                    c[1] = min(c[1], b.t_in)
    timeline = [c for c in timeline if c[1] - c[0] > 2 * F1]
    trans = [(ln["start"], ln["transition"]) for ln in lines if ln.get("transition")]
    punches = [(b.t_in - 3 * F1, b.t_out) for b in bigs if b.kind == "punch"] if not a.no_punch else []

    def stage_env(t):
        e = 0.0
        for b in bigs:
            k = 0.55 if b.kind == "punch" else 1.0      # punch: a lighter dim, the punch-in carries it
            e = max(e, k * min(1, (t - (b.t_in - 2 * F1)) * FPS / 4, (b.t_out + 4 * F1 - t) * FPS / 4))
        return max(0.0, e)

    pre = ""
    if a.crop:
        x, y, w, h = a.crop.split(":"); pre = f"crop={w}:{h}:{x}:{y},"
    if a.frame == "crop":
        vf, vflag = pre + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,setsar=1,fps={FPS}", "-vf"
    else:
        vf, vflag = (f"[0:v]{pre}split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
                     f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"), "-filter_complex"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = ["-t", f"{dur:.3f}"]
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FFMPEG, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", *tl, "-i", a.video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            *tl, "-i", a.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf, "-pix_fmt", "yuv420p",
                            *acodec, "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
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
    while True:
        buf = qin.get()
        if buf is None:
            break
        t = n / FPS; n += 1
        arr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        if any(p0 <= t <= p1 for p0, p1 in punches):
            arr = zoom(arr, 1.35)
        for tc, kind in trans:
            j = (t - tc) * FPS
            if kind == "flash" and -1 <= j < 3:
                k = {-1: 0.5, 0: 0.9, 1: 0.6, 2: 0.25}.get(int(math.floor(j)), 0)
                arr = (arr.astype(np.float32) * (1 - k) + 255 * k).astype(np.uint8)
            elif kind == "blurcut" and 0 <= j < 3:
                arr = np.asarray(Image.fromarray(arr).filter(ImageFilter.GaussianBlur(14 * (1 - j / 3) + 0.01)))
        if a.no_text:
            qout.put(np.ascontiguousarray(arr).tobytes()); continue
        arr = stage(arr, stage_env(t))
        fr = Image.fromarray(arr).convert("RGBA")
        for c in timeline:
            if c[0] <= t < c[1]:
                cards.draw(fr, c[2])
        for b in bigs:
            b.draw(fr, t)
        qout.put(np.asarray(fr.convert("RGB")).tobytes())
    qout.put(None); thw.join(); enc.stdin.close(); enc.wait(); dec.wait()
    base = os.path.splitext(a.out)[0]
    out = {"tool": "render", "ok": True, "out": a.out, "frames": n, "seconds": round(n / FPS, 2), "render_seconds": round(time.time() - t0, 1)}
    if not a.no_text:
        def srt_t(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base + ".srt", "w", encoding="utf-8") as f:
            for i, ln in enumerate(lines):
                f.write(f"{i + 1}\n{srt_t(ln['start'])} --> {srt_t(ln['end'] + 0.3)}\n{display(ln['text'])}\n\n")
        ev = [{"t": c[0] + 0.15, "kind": "card", "line": None} for c in timeline[::4]]
        sfx = []
        for b in bigs:
            for e in b.events:
                ev.append({"t": e["t"] + 1.5 * F1, "kind": f"{b.kind}: {e['kind']}", "line": b.id})
                if e.get("sfx"):
                    sfx.append({"frame": int(round(e["t"] * FPS)), "sound": e["sfx"], "what": f"line {b.id} {b.kind}: {e['kind']}"})
            ev.append({"t": b.t_out + 2 * F1, "kind": f"{b.kind} (exit)", "line": b.id})
        for tc, kind in trans:
            ev.append({"t": tc, "kind": f"transition {kind}", "line": None})
            if kind == "flash":
                sfx.append({"frame": int(round(tc * FPS)), "sound": "whoosh_zoom", "what": "white flash transition"})
        ev = sorted([e for e in ev if 0 <= e["t"] < dur], key=lambda e: e["t"])
        save(base + ".pk.json", {"video": os.path.abspath(a.out), "events": ev, "warnings": warn})
        save(base + ".sfx-events.json", {"events": sorted(sfx, key=lambda e: e["frame"]),
                                         "note": "draft from the caption-card plan: keep the true punchlines, delete the rest (a sermon stays reverent)"})
        pc = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
        if os.path.abspath(a.plan) != pc:
            shutil.copyfile(a.plan, pc)
        out.update(srt=base + ".srt", sfx_events=base + ".sfx-events.json", cards=len(timeline),
                   big={k: sum(1 for b in bigs if b.kind == k) for k in ("hook", "number", "writeon", "punch")}, transitions=len(trans))
    if a.phone:
        phone = base + "_phone.mp4"
        if os.path.getsize(a.out) <= 28 * 1048576:
            shutil.copyfile(a.out, phone)
        else:
            kbps = int((28 * 8 * 1024 * 1024 / max(1.0, dur) - 160_000) / 1000)
            for k in (1.0, 0.85, 0.7):
                subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", a.out, "-c:v", "libx264", "-preset", "medium", "-b:v", f"{int(kbps * k)}k",
                                "-maxrate", f"{int(kbps * k * 1.4)}k", "-bufsize", f"{int(kbps * k * 2)}k", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", phone])
                if os.path.getsize(phone) <= 28.5 * 1048576:
                    break
        out.update(phone=phone, phone_mb=round(os.path.getsize(phone) / 1048576, 1))
    out["warnings"] = warn
    report(**out)


if __name__ == "__main__":
    main()
