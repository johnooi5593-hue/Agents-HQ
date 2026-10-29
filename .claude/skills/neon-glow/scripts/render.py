"""Render a clip in the Neon Glow style (霓虹发光字) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--frame crop|blur] [--crop X:Y:W:H] [--focus 0.5] [--to SECONDS]
                        [--phone] [--no-text] [--preset medium]

Every line is typed on in chrome (#E8EFF6 -> #B5C5D3), one character as it is spoken. A line with "keyword" becomes a stack:
the "lead" (or the rest of the line) in chrome above, the keyword below as a neon word (near-white yellow core, dark rim,
olive glow) that switches on without moving: opacity 0.25 -> 1, saturation 0.3 -> 1, brightness 0.55 -> 1, glow 0 -> 1 over
8 frames, ease-out. "over": white text laid over the lower half of the neon word, blurring in. "layout": "number": the neon
word left-aligned and huge (0.23 of the frame), the lead under it. Line "transition": "blurdark" (blur into darkness,
0.35 s). Plan "moments": [{"kind": "window", "start", "end"}] put B-roll inside a dark rounded frame. Plan "overlays":
[{"kind": "bubble", "start", "end", "text"}] a chat bubble with typing dots, then the words.
Writes <out>.mp4, .srt, .pk.json (events for poster-kinetic preview.py), .sfx-events.json (for the sfx skill), a copy of
plan.json; --phone also <out>_phone.mp4 under 28 MiB. Prints one JSON line.
"""
import argparse, math, os, queue, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ng  # noqa: E402
from ng import cc, F1, FPS, Neon, display, disp_times, keys, ease_out, sub_time, is_cjk, load, save, report  # noqa: E402
ease_io = cc.ease_io

W, H = 1080, 1920
LEFT, RIGHT = 70, 1010


def neon_role(text):
    return "hook" if any(is_cjk(c) for c in text) else "number"


def chrome_rows(text, size, max_w=940, min_size=70):
    """One or two chrome rows that fit; returns (size, [row strings])."""
    s = size
    while s >= min_size:
        if cc.layout(text, "hook", s)[1][2] - cc.layout(text, "hook", s)[1][0] <= max_w:
            return s, [text]
        s *= 0.94
    words = text.split(" ") if not any(is_cjk(c) for c in text) else None
    best = None
    if words and len(words) > 1:
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:]); d = abs(len(a) - len(b))
            if best is None or d < best[0]: best = (d, a, b)
    else:
        mid = len(text) // 2; cut = mid
        for off in range(0, mid):
            for q in (mid - off, mid + off):
                if 0 < q < len(text) and text[q - 1] in "，、,":
                    cut = q; break
            else:
                continue
            break
        best = (0, text[:cut], text[cut:])
    rows = [best[1].strip(), best[2].strip()]
    s = size
    while s > 50 and max(cc.layout(r, "hook", s)[1][2] - cc.layout(r, "hook", s)[1][0] for r in rows) > max_w:
        s *= 0.94
    return s, rows


class ChromeRow:
    """A chrome text row typed on per character at the spoken times."""

    rise = 0.0

    def __init__(self, text, times, size, cx, cy, align="center", left=None, shadow=("#0A0C10", 6, 4, 0.8)):
        self.dy = 0.0
        gl, ink = cc.styled_line(text, "hook", size, "chrome", glow=False, shadow=shadow)
        self.gl, self.ink = gl, ink
        nonspace = [t for ch, t in zip(text, times) if ch.strip()]
        self.times = nonspace + [nonspace[-1] if nonspace else 0] * max(0, len(gl) - len(nonspace))
        self.cx = cx if align == "center" else left + ink[0] / 2
        self.cy = cy

    def draw(self, fr, t, alpha=1.0, blur=0.0):
        for g, gt in zip(self.gl, self.times):
            f = (t - gt) * FPS
            if f < 0:
                continue
            p = min(1.0, f / (3 if self.rise else 2))
            dy = self.rise * (1 - ease_out(p))
            sc = 1.0 + (0.08 * (1 - ease_out(p)) if self.rise else 0)
            cc.put(fr, g["img"], self.cx + g["cx"], self.cy + g["cy"] + dy + self.dy, sc, alpha=(0.2 + 0.8 * ease_out(p)) * alpha,
                   blur=max((9 if self.rise else 6) * (1 - p), blur))


FX = {"enhanced": True}


def neon(mask, h, **kw):
    if FX["enhanced"]:
        return Neon(mask, h, glow_scale=1.65, glow="#E2DA3A", **kw)
    return Neon(mask, h, **kw)


_PLATE = {}


def backplate(w, h):
    """A soft dark oval behind the text group, so the glow reads on bright pictures."""
    key = (int(w) // 8, int(h) // 8)
    if key in _PLATE:
        return _PLATE[key]
    m = Image.new("L", (int(w) // 4 + 2, int(h) // 4 + 2), 0)
    ImageDraw.Draw(m).ellipse((m.width * 0.12, m.height * 0.16, m.width * 0.88, m.height * 0.84), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(min(m.width, m.height) * 0.16)).resize((int(w), int(h)), Image.BILINEAR)
    img = Image.new("RGBA", (int(w), int(h)), (6, 6, 4, 0)); img.putalpha(m)
    _PLATE[key] = img
    return img


class Line:
    def __init__(self, ln, warn):
        self.ln = ln; self.id = ln.get("id"); self.rows = []; self.neon = None; self.over = None
        text = ln["text"]; kw = ln.get("keyword") if ln.get("keyword") and ln["keyword"] in text else None
        self.t_in = ln["start"]
        self.words = None
        if not kw and ln.get("_motion"):
            import words
            pl, an = ln["_motion"]
            self.words = words.WordLine(ln, pl, an, ln.get("emph"), seed=int(ln.get("id") or 0))
            self.t_in = self.words.t_in
            return
        if not kw:
            disp = display(text).strip()
            s, rows = chrome_rows(disp, 112)
            times = disp_times(ln, disp); k = 0
            base = 0.64 * H - (len(rows) - 1) * s * 0.6
            for i, r in enumerate(rows):
                self.rows.append(ChromeRow(r, times[k:k + len(r)], s, W / 2, base + i * s * 1.2)); k += len(r) + 1
            self.t_in = min(times) if times else ln["start"]
            return
        lead = ln.get("lead")
        if lead is None:
            lead = text.replace(kw, " ")
            if ln.get("over"):
                lead = lead.replace(ln["over"], " ")
            lead = " ".join(lead.split()).strip(" ,，.。")
            lead = lead if display(lead).strip() else None
        lead_d = display(lead).strip() if lead else ""
        kd = display(kw).strip()
        role = neon_role(kd)
        layout = ln.get("layout") or "stack"
        self.kw_t = sub_time(ln, kw) - 2 * F1
        if layout == "number":
            s, m, ink = ng.fit_word(kd, role, 1200, 600, H * 0.23)
            self.neon = neon(m, ink[1]); x0 = 106
            self.ncx, self.ncy = x0 + m.width / 2, 0.26 * H
            if lead_d:
                ls, _ = chrome_rows(lead_d, 150, 560)
                self.rows.append(ChromeRow(lead_d, disp_times(ln, lead_d), ls, 0, self.ncy + ink[1] / 2 + ls * 0.75, "left", left=x0))
        else:
            short = len(kd) <= (3 if role == "hook" else 5)
            s, m, ink = ng.fit_word(kd, role, 900, 640 if short else 760, H * (0.226 if short else 0.115))
            self.neon = neon(m, ink[1])
            lead_size = 165 if (lead_d and len(lead_d) <= 6) else 120
            if short and lead_d:
                lead_size = 86
            ls, lrows = chrome_rows(lead_d, lead_size) if lead_d else (0, [])
            lead_h = len(lrows) * ls * 1.15
            total = lead_h + ink[1]
            top = 0.55 * H - total / 2
            k, times = 0, disp_times(ln, lead_d) if lead_d else []
            for i, r in enumerate(lrows):
                self.rows.append(ChromeRow(r, times[k:k + len(r)], ls, W / 2, top + ls * 0.55 + i * ls * 1.15)); k += len(r) + 1
            self.ncx, self.ncy = W / 2, top + lead_h + ink[1] / 2
        if ln.get("over") and ln["over"] in text:
            od = display(ln["over"]).strip()
            os_, om, oink = ng.fit_word(od, neon_role(od) if not any(is_cjk(c) for c in od) else "hook", 140, 640, ink[1] * 0.28)
            self.over = Neon(om, oink[1], core=ng.WHITE_OVER, with_glow=False, rim_k=1.6)
            self.over_t = sub_time(ln, ln["over"]) - 2 * F1
            self.ocx, self.ocy = self.ncx, self.ncy + ink[1] * 0.18
        starts = [r.times[0] for r in self.rows if r.times] + [self.kw_t]
        self.t_in = min(starts)

    def draw(self, fr, t, t_out):
        if t < self.t_in - 1e-6:
            return
        if self.words is not None:
            self.words.draw(fr, t, t_out)
            return
        enh = FX["enhanced"] and self.ln.get("fx", True) is not False
        q = 0.0 if t <= t_out else (t - t_out) * FPS / (6 if (enh and self.neon) else 4)
        if q >= 1:
            return
        a, b = 1 - q, 8 * q
        drift = 1.0
        if enh and self.neon:                                    # the whole group slowly pushes in while it is up
            drift = 1 + 0.025 * min(1.0, max(0.0, t - self.kw_t) / 2.5)
        if enh and self.neon:
            env = min(1.0, max(0.0, (t - self.t_in) * FPS / 6)) * a
            tops = [r.cy - r.ink[1] for r in self.rows] + [self.ncy - self.neon.h * 0.7]
            bots = [self.ncy + self.neon.h * 0.7] + [r.cy + r.ink[1] for r in self.rows]
            gw = max([self.neon.size[0]] + [r.ink[0] + 120 for r in self.rows]) * 1.15
            gh = (max(bots) - min(tops)) * 1.7
            cx = self.ncx if not self.rows or self.ln.get("layout") != "number" else self.ncx + 60
            cc.put(fr, backplate(min(gw, 1400), gh), cx, (max(bots) + min(tops)) / 2, 1.0, alpha=0.62 * env)
        for r in self.rows:
            r.rise = 16.0 if enh else 0.0
            r.dy = (r.cy - self.ncy) * (drift - 1) if self.neon else 0.0
            r.draw(fr, t, a, b)
        if self.neon:
            f = (t - self.kw_t) * FPS
            if f >= 0 and not enh:
                p = ease_out(min(1, f / 8))
                cc.put(fr, self.neon.image(p, a, b), self.ncx, self.ncy)
            elif f >= 0:
                self.draw_enhanced(fr, t, f, q, a, b, drift)
        if self.over:
            if enh:
                self.ocy_d = self.ncy + (self.ocy - self.ncy) * drift
            f = (t - self.over_t) * FPS
            if f >= 0:
                p = min(1, f / 5)
                cy = getattr(self, "ocy_d", self.ocy) + (14 * (1 - ease_out(p)) if enh else 0)
                cc.put(fr, self.over.image(1.0, ease_out(p) * a, max(10 * (1 - p), b)), self.ocx, cy, (1.06 - 0.06 * ease_out(p)) if enh else 1.0)

    def draw_enhanced(self, fr, t, f, q, a, b, drift):
        """The enhanced switch-on: neon flicker, glow burst with overshoot, scale settle, then a shine sweep with sparkles,
        a light streak, a slow glow pulse while held, and a flare as it leaves."""
        N = self.neon
        if f < 4:                                               # two quick flickers, like a tube striking
            lit = [0.7, 0.12, 0.9, 0.3][int(f)]; gk = lit * 1.2
        else:
            lit = ease_out(min(1.0, (f - 4) / 8))
            gk = keys(f, [4, 8, 12, 17], [0.6, 1.75, 0.92, 1.0])
        if f > 17:
            gk = 1.0 + 0.14 * math.sin(2 * math.pi * 1.1 * (t - self.kw_t - 17 * F1))
        sc = keys(f, [0, 10], [1.07, 1.0]) * drift
        shine = None
        if 14 <= f < 30 and self.ln.get("shine", True) is not False:
            shine = -0.12 + 1.24 * ease_io((f - 14) / 16)
        bright = 1.0
        if q > 0:                                               # exit flare: swell, brighten, blur away
            gk *= 1 + 1.2 * min(1, q * 2); bright = 1 + 0.6 * min(1, q * 2); sc *= 1 + 0.05 * q
        cc.put(fr, N.image(lit, a, b, gk, shine, bright), self.ncx, self.ncy, sc)
        h = N.h
        if 4 <= f < 18:                                          # anamorphic light streak at the glow burst
            k = math.sin(math.pi * (f - 4) / 14)
            st = ng.streak(N.size[0] * 1.7, h * 0.75)
            cc.put(fr, st, self.ncx, self.ncy, 1.0, alpha=min(1.0, 1.1 * k) * a)
            cc.put(fr, ng.star(h * 0.55), self.ncx - N.size[0] * 0.28 * (1 - k), self.ncy - h * 0.25, 0.5 + 0.7 * k, rot=f * 4, alpha=0.9 * k * a)
        for i, (px, py) in enumerate(N.sparkle_pts):            # sparkles ride the shine
            sf = f - (15 + 3 * i)
            if 0 <= sf < 11:
                k = math.sin(math.pi * sf / 11)
                x = self.ncx + (px - N.size[0] / 2) * sc; y = self.ncy + (py - N.size[1] / 2) * sc
                cc.put(fr, ng.star(h * 0.42), x, y, 0.4 + 0.9 * k, rot=sf * 6, alpha=k * a)


def window_mask():
    m = Image.new("L", (W // 4, H // 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((int(W * 0.05 / 4), int(H * 0.07 / 4), int(W * 0.95 / 4), int(H * 0.86 / 4)), radius=int(W * 0.12 / 4), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(20 / 4)).resize((W, H), Image.BILINEAR)
    a = np.asarray(m, np.float32)[..., None] / 255
    return a + (1 - a) * 0.1


def blur_small(arr, r):
    im = Image.fromarray(arr).resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(r / 4))
    return np.asarray(im.resize((W, H), Image.BILINEAR))


def vignette():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    return np.clip(1 - np.clip(d - 0.35, 0, 1) * 1.3, 0.1, 1)[..., None]


def draw_bubble(fr, o, t):
    if t < o["start"] or t > o["end"] + 0.2:
        return
    k = (t - o["start"]) * FPS
    a = min(1.0, k / 4) * (1 - max(0, (t - o["end"]) / 0.2))
    typing = (t - o["start"]) < 0.45
    ft = cc.pfonts.font("cjk", 44)
    txt = display(o["text"]).strip()
    w = 150 if typing else int(ft.getlength(txt)) + 64
    h = 92; x, y = 70, int(0.1 * H)
    s = 0.6 + 0.4 * ease_out(min(1, k / 5))
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(255, 255, 255, 245))
    d.polygon([(x + 18, y + h - 10), (x + 4, y + h + 18), (x + 44, y + h - 4)], fill=(255, 255, 255, 245))
    if typing:
        for i in range(3):
            ph = math.sin((t - o["start"]) * 12 - i * 0.9) * 0.5 + 0.5
            cx = x + 45 + i * 30; d.ellipse((cx - 9, y + h / 2 - 9 - 6 * ph, cx + 9, y + h / 2 + 9 - 6 * ph), fill=(110, 110, 118, 255))
    else:
        d.text((x + 32, y + h / 2), txt, font=ft, fill=(20, 20, 24, 255), anchor="lm")
    if s < 0.999:
        lay = lay.resize((int(W * s), int(H * s)), Image.BILINEAR); big = Image.new("RGBA", (W, H)); big.alpha_composite(lay, (int(x * (1 - s)), int(y * (1 - s)))); lay = big
    if a < 1:
        lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
    fr.alpha_composite(lay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop")
    ap.add_argument("--crop", default=None); ap.add_argument("--focus", type=float, default=0.5)
    ap.add_argument("--to", type=float, default=None)
    ap.add_argument("--no-text", action="store_true"); ap.add_argument("--phone", action="store_true")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    t0 = time.time()
    plan = load(a.plan)
    err, warn = ng.check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    dur = ng.probe(a.video)["duration"]
    if a.to:
        dur = min(dur, a.to)
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    hide = set()
    for o in plan.get("overlays") or []:
        for ln in lines:
            if cc.norm(o.get("text")) and cc.norm(o["text"]) in cc.norm(ln["text"]) and ln["start"] < o["end"] and ln["end"] > o["start"] - 0.5:
                hide.add(ln.get("id"))
    if FX["enhanced"] and plan.get("auto_motion", True) is not False:
        import words
        plain = [ln for ln in lines if ln.get("id") not in hide and not (ln.get("keyword") and ln["keyword"] in ln["text"])]
        meta = [(int(ln.get("id") or i), len(words.tokens(ln, display(ln["text"]).strip())), any(is_cjk(c) for c in ln["text"]))
                for i, ln in enumerate(plain)]
        for ln, (pl, an) in zip(plain, words.choose(meta)):
            ln["_motion"] = (ln.get("place") or pl, ln.get("anim") or an)
    Ls = [Line(ln, warn) for ln in lines if ln.get("id") not in hide]
    for i, L in enumerate(Ls):
        nxt = Ls[i + 1].t_in if i + 1 < len(Ls) else dur
        L.t_out = min(L.ln["end"] + 0.35, nxt - 2 * F1) if i + 1 < len(Ls) else min(L.ln["end"] + 0.8, dur)
        if L.neon and L.t_out < L.kw_t + 0.5:
            warn.append(f"line {L.id}: the neon word is up only {max(0, L.t_out - L.kw_t):.2f}s; merge with the next line or pick an earlier word")
    trans = [ln["start"] for ln in lines if ln.get("transition") == "blurdark"]
    wins = [(m["start"], m["end"]) for m in plan.get("moments") or [] if m.get("kind") == "window"]
    WM = window_mask() if wins else None
    VG = vignette() if trans else None
    FX["enhanced"] = (plan.get("fx") or "enhanced") != "reference"
    VGS = vignette() if FX["enhanced"] else None
    pre = ""
    if a.crop:
        x, y, w, h = a.crop.split(":"); pre = f"crop={w}:{h}:{x}:{y},"
    if a.frame == "crop":
        vf, vflag = pre + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,setsar=1,fps={FPS}", "-vf"
    else:
        vf, vflag = (f"[0:v]{pre}split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
                     f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"), "-filter_complex"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = ["-t", f"{dur:.3f}"]; FF = cc.FFMPEG
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FF, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    dec = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", *tl, "-i", a.video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
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
    n = 0; overlays = plan.get("overlays") or []
    while True:
        buf = qin.get()
        if buf is None:
            break
        t = n / FPS; n += 1
        arr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        if WM is not None and any(s <= t <= e for s, e in wins):
            arr = (arr.astype(np.float32) * WM).astype(np.uint8)
        for tc in trans:
            j = (t - tc) * FPS
            if -4 <= j < 0:
                e = (j + 5) / 5; arr = (blur_small(arr, 40 * e).astype(np.float32) * (1 - (1 - VG) * e)).astype(np.uint8)
            elif 0 <= j < 5:
                e = 1 - j / 5; arr = (blur_small(arr, 30 * e).astype(np.float32) * (1 - (1 - VG) * e)).astype(np.uint8)
        if a.no_text:
            qout.put(np.ascontiguousarray(arr).tobytes()); continue
        if FX["enhanced"]:
            env = 0.0
            for L in Ls:
                if L.neon:
                    env = max(env, min(1.0, (t - L.kw_t) * FPS / 6, (L.t_out + 6 * F1 - t) * FPS / 6))
            if env > 0.01:
                arr = (arr.astype(np.float32) * (1 - 0.45 * env * (1 - VGS) - 0.18 * env)).clip(0, 255).astype(np.uint8)
        fr = Image.fromarray(arr).convert("RGBA")
        for L in Ls:
            if L.t_in - 0.01 <= t <= L.t_out + 5 * F1:
                L.draw(fr, t, L.t_out)
        for o in overlays:
            draw_bubble(fr, o, t)
        qout.put(np.asarray(fr.convert("RGB")).tobytes())
    qout.put(None); thw.join(); enc.stdin.close(); enc.wait(); dec.wait()
    base = os.path.splitext(a.out)[0]
    out = {"tool": "render", "ok": True, "out": a.out, "frames": n, "seconds": round(n / FPS, 2), "render_seconds": round(time.time() - t0, 1)}
    if not a.no_text:
        def st(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base + ".srt", "w", encoding="utf-8") as f:
            for i, ln in enumerate(lines):
                f.write(f"{i + 1}\n{st(ln['start'])} --> {st(ln['end'] + 0.3)}\n{display(ln['text'])}\n\n")
        ev, sfx = [], []
        for L in Ls:
            ev.append({"t": L.t_in + 0.2, "kind": "chrome type", "line": L.id})
            if L.neon:
                for dt, k in ((2 * F1, "neon (switching on)"), (0.4, "neon (on)")):
                    ev.append({"t": L.kw_t + dt, "kind": k, "line": L.id})
                sfx.append({"frame": int(round(L.kw_t * FPS)), "sound": "chime_soft", "what": f"line {L.id}: neon word switches on"})
            if L.over:
                ev.append({"t": L.over_t + 0.25, "kind": "over", "line": L.id})
        for tc in trans:
            ev.append({"t": tc - 2 * F1, "kind": "transition blurdark", "line": None})
            sfx.append({"frame": int(round(tc * FPS)), "sound": "whoosh_zoom", "what": "blur into darkness transition"})
        for o in overlays:
            ev.append({"t": o["start"] + 0.2, "kind": "bubble (typing)", "line": None}); ev.append({"t": o["start"] + 0.7, "kind": "bubble (text)", "line": None})
            sfx.append({"frame": int(round(o["start"] * FPS)), "sound": "pop", "what": "chat bubble"})
        save(base + ".pk.json", {"video": os.path.abspath(a.out), "events": sorted([e for e in ev if 0 <= e["t"] < dur], key=lambda e: e["t"]), "warnings": warn})
        save(base + ".sfx-events.json", {"events": sorted(sfx, key=lambda e: e["frame"]), "note": "draft: keep the true punchlines; a sermon stays reverent"})
        pc = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
        if os.path.abspath(a.plan) != pc:
            shutil.copyfile(a.plan, pc)
        out.update(srt=base + ".srt", sfx_events=base + ".sfx-events.json", lines=len(Ls), neon=sum(1 for L in Ls if L.neon), transitions=len(trans))
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
