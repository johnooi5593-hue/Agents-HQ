"""Optional moments for Poster Kinetic (from the sermon technique guide, Documents/Style Guides/sermon-edit-techniques).
None of these is on by default: each one is placed by hand in plan.json at the moment it fits, with a "why".

plan.json, top level:
  "moments": [ {"kind": ..., "start": s, "end": e, "why": "...", ...} ]   picture moments, drawn under the text
      grade_wipe  cold grey picture, a white line wipes right-to-left (30 f) to a warm grade. Line about change. Once.
      moody       soft reflective grade (highlights down, blacks up, saturation 0.85, vignette). Prayer / quiet moments.
      tight       tighter framing (scale 1.15, centred at cy 0.3): alternate on jump cuts of one speaker shot.
      freeze      the picture freezes, 10 f later shrinks into a rounded window top left (12 f) over a blurred background;
                  grows back over 8 f at the end. Use after a question; the answer lands as a hero. 2-3 s, max 2.
      wall        3x3 grid: the live picture in the centre, 8 of OUR OWN B-roll clips pop in clockwise, one per frame.
                  "clips": [{"file": path, "in": seconds} x 8]. Line about the church family. Once.
  "overlays" gains:
      {"kind": "name", "start", "end", "name", "sub", "face_box": [x, y, size]}  avatar circle + name slides out. Once.
      {"kind": "question", "start", "end", "text"}  the preacher's question types into a rounded bar (text = his words).
  "caption_style": "active" (plan or line): 3 words / 6 characters at a time, only the spoken word on a gold box.
  picture_transitions / line transition kinds gain "whip" (6+6 frame whip pan, replaces the old 5-frame blur) and
  "zoom_through" (the shot shrinks into itself 3 levels deep for 1.2 s, then pushes into the next shot). Once.
"""
import math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pfonts

FPS = 30; F1 = 1 / FPS
GOLD, DARK, WHITE = (0xF8, 0xEA, 0x98), (0x1B, 0x18, 0x13), (0xFC, 0xFC, 0xFA)
LIMITS = {"grade_wipe": 1, "wall": 1, "freeze": 2, "moody": 2, "tight": 99, "name": 1, "question": 2, "zoom_through": 1}


def ease_out(x): x = min(1, max(0, x)); return 1 - (1 - x) ** 3
def ease_in(x): x = min(1, max(0, x)); return x ** 3
def ease_io(x): x = min(1, max(0, x)); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def rounded(img, r):
    m = Image.new("L", img.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, img.width - 1, img.height - 1), r, fill=255)
    out = img.convert("RGBA"); out.putalpha(m); return out


def zoom(arr, s, cy=0.45):
    H, W = arr.shape[:2]
    if abs(s - 1) < 1e-3:
        return arr
    w, h = W / s, H / s; x0 = (W - w) / 2; y0 = min(max(0.0, H * cy - h * cy), H - h)
    return np.asarray(Image.fromarray(arr).resize((W, H), Image.BICUBIC, box=(max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h))))


def hblur(a, k):
    k = int(k)
    if k < 2:
        return a
    p = np.pad(a.astype(np.float32), ((0, 0), (k, k), (0, 0)), mode="edge"); c = np.cumsum(p, axis=1)
    return ((c[:, 2 * k:] - c[:, :-2 * k]) / (2 * k))[:, :a.shape[1]].clip(0, 255).astype(np.uint8)


def shift(a, dx):
    dx = int(dx); out = np.roll(a, dx, axis=1)
    if dx > 0:
        out[:, :dx] = a[:, :1]
    elif dx < 0:
        out[:, dx:] = a[:, -1:]
    return out


def sat(a, k):
    f = a.astype(np.float32); g = f.mean(2, keepdims=True)
    return g + (f - g) * k


def grade_cold(a):
    f = sat(a, 0.25); f = (f - 128) * 0.92 + 128 - 8; f[..., 2] += 14; f[..., 0] -= 4
    return f.clip(0, 255).astype(np.uint8)


def grade_warm(a):
    f = a.astype(np.float32) * np.array([1.12, 1.06, 0.98], np.float32)
    return sat(f.clip(0, 255), 1.15).clip(0, 255).astype(np.uint8)


_LUT = np.interp(np.arange(256) / 255, [0, 0.5, 1], [0.06, 0.47, 0.88]) * 255
_VIG = {}


def grade_moody(a):
    H, W = a.shape[:2]
    if (H, W) not in _VIG:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 1.414
        _VIG[(H, W)] = (1 - 0.45 * np.clip((r - 0.35) / 0.65, 0, 1) ** 1.6)[..., None]
    f = _LUT[a].astype(np.float32)
    return (sat(f, 0.85) * _VIG[(H, W)]).clip(0, 255).astype(np.uint8)


def clip_frames(path, t0, dur, size):
    n = round(dur * FPS) + 2
    v = f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=increase,crop={size[0]}:{size[1]},fps={FPS}"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", path, "-t", f"{dur + 0.3:.3f}", "-vf", v, "-frames:v", str(n),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8); m = len(a) // (size[0] * size[1] * 3)
    return a[:m * size[0] * size[1] * 3].reshape(m, size[1], size[0], 3)


class Moments:
    def __init__(self, plan, W, H, warn):
        self.W, self.H, self.warn = W, H, warn
        self.pm = [dict(m) for m in plan.get("moments") or []]
        self.state = {}
        for k, m in enumerate(self.pm):
            if m["kind"] == "wall":
                m["_tiles"] = [clip_frames(c["file"], float(c.get("in", 0)), m["end"] - m["start"], (340, 604)) for c in m.get("clips", [])[:8]]

    def active(self, t):
        return any(m["start"] <= t <= m["end"] + 0.3 for m in self.pm if m["kind"] in ("freeze", "wall"))

    # ---- picture moments (before transitions and text) --------------------------------------------------------------
    def picture(self, arr, t):
        W, H = self.W, self.H
        for k, m in enumerate(self.pm):
            s, e = m["start"], m["end"]
            if not (s <= t <= e + 0.3):
                continue
            kind = m["kind"]
            if kind == "tight" and t <= e:
                arr = zoom(arr, float(m.get("scale", 1.15)), float(m.get("cy", 0.3)))
            elif kind == "moody" and t <= e:
                g = grade_moody(arr); a_ = min(1.0, (t - s) / 0.3, (e - t) / 0.3)
                arr = (arr * (1 - a_) + g * a_).astype(np.uint8)
            elif kind == "grade_wipe" and t <= e:
                f = (t - s) * FPS
                p = ease_io((f - m.get("hold", 12)) / m.get("wipe", 30))
                x = int(W * (1 - p))
                out = grade_warm(arr)
                if x > 0:
                    out[:, :x] = grade_cold(arr[:, :x])
                if 0 < p < 1:
                    out[:, max(0, x - 3):x + 3] = 255
                if e - t < 0.3:                                      # ease back to the normal picture
                    q = (e - t) / 0.3; out = (arr * (1 - q) + out * q).astype(np.uint8)
                arr = out
            elif kind == "freeze":
                st = self.state.setdefault(k, {})
                if "frozen" not in st:
                    st["frozen"] = arr.copy()
                    bg = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(26)).convert("RGBA")
                    bg.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 110)))
                    st["bg"] = bg
                f = (t - s) * FPS
                grow = max(0.0, (t - (e - 8 * F1)) / (8 * F1)) if t > e - 8 * F1 else 0.0
                p = ease_out((f - 10) / 12) * (1 - ease_out(grow)) if f >= 10 else 0.0
                if t > e:
                    continue
                sc = 1 - (1 - 0.46) * p; cx = W / 2 - (W / 2 - 300) * p; cy = H / 2 - (H / 2 - 520) * p
                cv = st["bg"].copy() if p > 0.001 else Image.fromarray(st["frozen"]).convert("RGBA")
                if p > 0.001:
                    win = rounded(Image.fromarray(st["frozen"]).resize((int(W * sc), int(H * sc)), Image.BICUBIC), int(40 * p) + 1)
                    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(sh).rounded_rectangle((cx - win.width / 2 + 10, cy - win.height / 2 + 24, cx + win.width / 2 + 10, cy + win.height / 2 + 24),
                                                         40, fill=(0, 0, 0, int(110 * p)))
                    cv.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
                    cv.alpha_composite(win, (int(cx - win.width / 2), int(cy - win.height / 2)))
                arr = np.asarray(cv.convert("RGB"))
            elif kind == "wall" and t <= e:
                f = int((t - s) * FPS)
                cv = Image.new("RGB", (W, H), (12, 12, 14))
                gx, gy, tw, th, g = 18, 52, 340, 604, 12
                order = [0, 1, 2, 5, 8, 7, 6, 3]
                centre = rounded(Image.fromarray(arr).resize((tw, th), Image.BICUBIC), 22)
                ent = ease_out(f / 8)
                if ent < 1:                                          # the live shot shrinks into the centre tile
                    sc = 1 - (1 - tw / W) * ent
                    big = rounded(Image.fromarray(arr).resize((int(W * sc), int(H * sc)), Image.BICUBIC), int(22 * ent) + 1)
                    cx = W / 2 + ((gx + tw + g + tw / 2) - W / 2) * ent; cy = H / 2 + ((gy + th + g + th / 2) - H / 2) * ent
                    cv.paste(big, (int(cx - big.width / 2), int(cy - big.height / 2)), big)
                else:
                    cv.paste(centre, (gx + tw + g, gy + th + g), centre)
                for i, tiles in enumerate(m["_tiles"]):
                    if f < 8 + i or not len(tiles):
                        continue
                    r, c = divmod(order[i], 3); x, y = gx + c * (tw + g), gy + r * (th + g)
                    e2 = ease_out((f - 8 - i) / 6); im = rounded(Image.fromarray(tiles[min(f, len(tiles) - 1)]), 22)
                    s2 = 0.6 + 0.4 * e2; im = im.resize((max(1, int(tw * s2)), max(1, int(th * s2))))
                    cv.paste(im, (int(x + tw * (1 - s2) / 2), int(y + th * (1 - s2) / 2)), im)
                arr = np.asarray(cv)
        return arr

    # ---- transitions -------------------------------------------------------------------------------------------------
    @staticmethod
    def whip_pan(arr, t, tc):
        W = arr.shape[1]
        j = (t - tc) * FPS
        if -6 <= j < 0:
            e = ease_in((j + 7) / 6)
            return hblur(shift(arr, -0.08 * W * e), 80 * e)
        if 0 <= j < 6:
            e = ease_out((j + 1) / 6)
            return hblur(shift(arr, 0.08 * W * (1 - e)), 80 * (1 - e))
        return arr

    @staticmethod
    def zoom_through(arr, t, tc):
        H, W = arr.shape[:2]
        j = (t - tc) * FPS
        if -36 <= j < 0:
            p = ease_io((j + 36) / 36)
            base = Image.fromarray(arr); cv = base.copy(); s = 1 - 0.55 * p
            for lvl in range(1, 4):
                sc = s ** lvl
                if sc > 0.98:
                    continue
                im = rounded(base.resize((int(W * sc), int(H * sc))), int(30 * sc) + 2)
                cv.paste(im, (int((W - im.width) / 2), int(H * 0.30 - im.height * 0.30)), im)
            return np.asarray(cv)
        if 0 <= j < 8:
            e = ease_out((j + 1) / 8)
            return np.asarray(Image.fromarray(zoom(arr, 1.4 - 0.4 * e, 0.5)).filter(ImageFilter.GaussianBlur(10 * (1 - e) + 0.01)))
        return arr

    def grab_faces(self, overlays, arr, t):
        for o in overlays:
            if o.get("kind") == "name" and "_face" not in o and t >= o["start"] + 0.3:
                x, y, sz = o.get("face_box") or (self.W / 2 - 200, 260, 400)
                face = Image.fromarray(arr).crop((int(x), int(y), int(x + sz), int(y + sz))).resize((120, 120), Image.LANCZOS)
                mk = Image.new("L", (120, 120), 0); ImageDraw.Draw(mk).ellipse((0, 0, 119, 119), fill=255); face.putalpha(mk)
                ring = Image.new("RGBA", (128, 128), (0, 0, 0, 0)); ImageDraw.Draw(ring).ellipse((0, 0, 127, 127), fill=GOLD + (255,))
                ring.alpha_composite(face, (4, 4)); o["_face"] = ring


def text_img(text, size, color, stroke=3):
    ft = pfonts.font("cjk", size)
    x0, y0, x1, y1 = ft.getbbox(text, stroke_width=stroke); pad = int(size * 0.25) + stroke
    im = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), text, font=ft, fill=color + (255,), stroke_width=stroke, stroke_fill=DARK + (255,))
    return im


def draw_name(fr, o, t, W, H):
    if "_face" not in o or t < o["start"] or t > o["end"] + 0.3:
        return
    k = (t - o["start"]) * FPS
    out = max(0.0, (t - o["end"]) / 0.3)
    a = ease_out(k / 12) * (1 - out); y = H * float(o.get("y", 0.55)) + 30 * (1 - ease_out(k / 12))
    p = ease_out((k - 14) / 12) if k >= 14 else 0
    if "_nm" not in o:
        o["_nm"] = text_img(o.get("name", ""), 70, WHITE); o["_sb"] = text_img(o.get("sub", ""), 40, GOLD, 2) if o.get("sub") else None
    nm, sb = o["_nm"], o["_sb"]
    total = 128 + 20 + max(nm.width, sb.width if sb else 0)
    ax = W / 2 - (total / 2 - 64) * p
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if p > 0:
        nx = ax + 64 + 20 - nm.width * (1 - p) * 0.6
        lay.alpha_composite(nm, (int(nx), int(y - nm.height / 2 - (18 if sb else 0))))
        if sb:
            lay.alpha_composite(sb, (int(nx + 6), int(y + 22)))
        clip = Image.new("L", (W, H), 0); ImageDraw.Draw(clip).rectangle((ax, 0, W, H), fill=255)
        al = np.minimum(np.asarray(lay.getchannel("A")), np.asarray(clip)).astype(np.float32) * p * (1 - out)
        lay.putalpha(Image.fromarray(al.astype(np.uint8)))
    fr_rgba = fr.convert("RGBA"); fr_rgba.alpha_composite(lay)
    face = o["_face"].copy(); face.putalpha(face.getchannel("A").point(lambda v: int(v * a)))
    fr_rgba.alpha_composite(face, (int(ax - 64), int(y - 64)))
    fr.paste(fr_rgba.convert("RGB"))


def draw_question(fr, o, t, W, H, words):
    if t < o["start"] or t > o["end"] + 0.3:
        return
    k = (t - o["start"]) * FPS
    out = max(0.0, (t - o["end"]) / 0.3)
    a = ease_out(k / 10) * (1 - out)
    q = o["text"]
    ws = [w for w in words if o["start"] - 0.2 <= w["start"] <= o["end"]]
    if ws:
        spoken = sum(len(w["t"]) for w in ws if w["start"] <= t); total = max(1, sum(len(w["t"]) for w in ws))
        n = round(len(q) * min(1.0, spoken / total))
    else:
        n = int(len(q) * min(1.0, k / 40))
    ft = pfonts.font("cjk", 50)
    bw, bh = int(W * 0.926), 120; bx, by = (W - bw) // 2, int(H * 0.225) - bh // 2
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rounded_rectangle((bx, by + 14, bx + bw, by + bh + 14), bh // 2, fill=(0, 0, 0, 90))
    lay = lay.filter(ImageFilter.GaussianBlur(10)); d = ImageDraw.Draw(lay)
    d.rounded_rectangle((bx, by, bx + bw, by + bh), bh // 2, fill=(0x2B, 0x2B, 0x2B, 245))
    txt = q[:n] + ("|" if (int(k) // 8) % 2 == 0 and n < len(q) else "")
    while ft.getlength(txt) > bw - 56 - bh - 20 and ft.size > 30:
        ft = pfonts.font("cjk", ft.size - 2)
    d.text((bx + 56, by + bh / 2), txt, font=ft, fill=WHITE + (255,), anchor="lm")
    cx, cy, r = bx + bw - bh / 2, by + bh / 2, bh / 2 - 16
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD + (255,))
    d.line((cx, cy + r * 0.45, cx, cy - r * 0.45), fill=DARK + (255,), width=7)
    d.line((cx - r * 0.38, cy - r * 0.05, cx, cy - r * 0.47, cx + r * 0.38, cy - r * 0.05), fill=DARK + (255,), width=7, joint="curve")
    lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
    fr_rgba = fr.convert("RGBA"); fr_rgba.alpha_composite(lay, (0, int(30 * (1 - ease_out(k / 10)))))
    fr.paste(fr_rgba.convert("RGB"))


def is_zh(s):
    return any(0x2E80 <= ord(c) <= 0x9FFF for c in s)


def draw_active_caption(fr, ln, t, t_out, W, H, y=1300):
    """3 English words / 6 Chinese characters at a time, never across the line; only the spoken word on a gold box."""
    ws = [w for w in ln.get("words", []) if w["t"].strip()]
    if not ws or t < ws[0]["start"] - 0.05 or t > t_out:
        return
    zh = is_zh(ln.get("text", ""))
    chunks, cur, cnt = [], [], 0
    for w in ws:
        n = len(w["t"]) if zh else 1
        if cur and cnt + n > (6 if zh else 3):
            chunks.append(cur); cur, cnt = [], 0
        cur.append(w); cnt += n
    if cur:
        chunks.append(cur)
    ch = next((c for c in reversed(chunks) if c[0]["start"] - 0.03 <= t), chunks[0])
    size = 74; ft = pfonts.font("cjk", size)
    gap = 0 if zh else size * 0.32
    widths = [ft.getlength(w["t"]) for w in ch]
    tot = sum(widths) + gap * (len(ch) - 1)
    while tot > W * 0.82 and size > 52:
        size -= 4; ft = pfonts.font("cjk", size); widths = [ft.getlength(w["t"]) for w in ch]; gap = 0 if zh else size * 0.32
        tot = sum(widths) + gap * (len(ch) - 1)
    x = W / 2 - tot / 2
    act = max([i for i, w in enumerate(ch) if w["start"] <= t + 0.02] or [0])
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for i, (w, wd) in enumerate(zip(ch, widths)):
        if i == act:
            d.rounded_rectangle((x - 12, y - size * 0.62, x + wd + 12, y + size * 0.52), 10, fill=GOLD + (255,))
            d.text((x, y), w["t"], font=ft, fill=DARK + (255,), anchor="lm")
        else:
            d.text((x, y), w["t"], font=ft, fill=WHITE + (255,), anchor="lm", stroke_width=3, stroke_fill=DARK + (255,))
        x += wd + gap
    fr_rgba = fr.convert("RGBA"); fr_rgba.alpha_composite(lay); fr.paste(fr_rgba.convert("RGB"))


def check(plan, spoken_norm, norm, err, warn):
    counts = {}
    for k, m in enumerate(plan.get("moments") or []):
        tag = f"moment {k + 1} ({m.get('kind')})"
        kind = m.get("kind")
        if kind not in ("grade_wipe", "moody", "tight", "freeze", "wall"):
            err.append(f"{tag}: kind must be grade_wipe, moody, tight, freeze or wall"); continue
        counts[kind] = counts.get(kind, 0) + 1
        if not (isinstance(m.get("start"), (int, float)) and isinstance(m.get("end"), (int, float)) and m["end"] > m["start"]):
            err.append(f"{tag}: needs numeric start < end")
            continue
        if kind != "tight" and not (m.get("why") or "").strip():
            err.append(f"{tag}: say why this moment fits (\"why\"): these effects are only for the moment that earns them")
        if kind == "freeze" and m["end"] - m["start"] > 3.2:
            warn.append(f"{tag}: freeze longer than 3 s; picture and voice drift apart")
        if kind == "wall":
            if len(m.get("clips") or []) < 8:
                err.append(f"{tag}: needs 8 clips of our own footage: [{{\"file\", \"in\"}}]")
            if m["end"] - m["start"] < 1.5:
                warn.append(f"{tag}: under 1.5 s; the tiles barely land")
    for o in plan.get("overlays") or []:
        if o.get("kind") in ("name", "question"):
            counts[o["kind"]] = counts.get(o["kind"], 0) + 1
            if o["kind"] == "question" and norm(o.get("text")) not in spoken_norm:
                err.append(f"question overlay: text '{o.get('text')}' must be the preacher's words exactly (punctuation aside)")
            if o["kind"] == "name":
                warn.append("name overlay: confirm the spelling of the name and the church")
                for ln in plan.get("lines", []):
                    if (ln.get("mode") or "caption") != "caption" and ln["start"] < o["end"] and ln["end"] + 1.0 > o["start"]:
                        warn.append(f"name overlay overlaps the hero of line {ln.get('id')}; put the name on a calm caption-only line")
    for tr in (plan.get("picture_transitions") or []) + [{"kind": ln.get("transition")} for ln in plan.get("lines", [])]:
        if tr.get("kind") == "zoom_through":
            counts["zoom_through"] = counts.get("zoom_through", 0) + 1
    for kind, n in counts.items():
        if n > LIMITS.get(kind, 99):
            warn.append(f"{kind} used {n} times; at most {LIMITS[kind]} per video, so it still lands when it comes")
    act = [ln for ln in plan.get("lines", []) if (ln.get("caption_style") or plan.get("caption_style")) == "active"]
    if plan.get("caption_style") == "active":
        warn.append("caption_style active for the whole video: fine for a fast talker; otherwise set it only on the lines that run fast")
    return counts
