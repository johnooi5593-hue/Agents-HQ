"""Render a clip in the Poster Kinetic style (大字海报动态) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--frame crop|blur] [--crop X:Y:W:H] [--focus 0.5]
                        [--matte matte.mp4] [--no-punch] [--phone] [--no-text]

What it draws (guide: Semenyih shoplot reel, measured; sermon adaptations marked *):
  caption  every ordinary line*, heavy white sans (Alibaba PuHuiTi Heavy) at 78 px above y 1400, inline key words in
           their meaning colour at 1.08x; each word ghosts in over 2 frames as it is spoken; the old line blurs into
           the next over 4 frames (E4 morph)
  poster   one giant hero word (250-290 px) with a short dark extrusion #1B1813, the rest of the line as small white
           lead-in (above) and tail (below); hero motion whip (2-4 frames + motion blur, then 40 px drift), drop (letters
           fall in 1 frame apart, blur to sharp) or zoom (1.10 -> 1.00 with blur); blur-out exit in 6 frames, or a swap
           (old hero drops away in 3 frames) when the next hero lands in the same zone
  stack    2-4 characters stacked vertically, 5 frames apart, each ghosting in over 2 frames, lead-in beside them
  overlays title* (sermon title in metal-gradient letters that drop in, preacher's name 6 frames later) and card*
           (scripture card that flies in from depth in 12 frames with a 3D turn, the guide's data-card motion)
  picture  transitions flash (zoom-blur white flash, 12 frames) and whip (horizontal blur, 5 frames) at section starts;
           a slow 4.5% punch-in while a hero is up*; text behind the speaker when a matte is given (matte.py)
  colour   a hero's colour comes from the sermon palette; a dark colour on a dark picture switches to its light variant*
Writes <out>.mp4, <out>.srt, <out>.pk.json (events for preview.py, warnings) and a copy of plan.json; --phone also writes
<out>_phone.mp4 under 28 MiB for sending to a phone. Prints one JSON line.
"""
import argparse, math, os, queue, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pk  # noqa: E402
from pk import (BLUR_OUT, CAPTION_BASE_Y, CAPTION_IN, CAPTION_MIN_PX, CAPTION_OUT, CAPTION_PX, CARD, DROP, EXTRUDE, FFMPEG,  # noqa: E402
                FLASH_T, FPS, HERO_MIN_HOLD, HERO_MIN_PX, HERO_PX, HERO_SHORT_PX, KEY_SCALE, LEAD_FRAMES, LEAD_PX, PUNCH,
                SAFE, STACK, STACK_PX, SWAP, WHIP, WHIP_T, WHITE, ZONES, ZOOM, char_times, check, colour, contrast, display,
                has_cjk, is_cjk, load, luminance, norm, probe, report, save, split_kw, units)
import pfonts  # noqa: E402
import moments  # noqa: E402

BREAK_BEFORE = set("像是在但就而所因如可然还也都又才把被让给从和与或先再即")
BREAK_AFTER = set("的了吗呢吧啊么着过")
LATIN_K = 1.06
F1 = 1 / FPS


def ease_out(x): x = min(1.0, max(0.0, x)); return 1 - (1 - x) ** 3
def ease_expo(x): x = min(1.0, max(0.0, x)); return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)
def smooth(x): x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)


# ---- glyph sprites ------------------------------------------------------------------------------------------------
_SPR = {}


def piece_role(text, slant, tier):
    if tier == "text":
        return "cjk_text"
    if tier == "caption":
        return "cjk"
    if tier == "narrow" and not has_cjk(text):
        return "latin_narrow"
    if has_cjk(text) or not any(c.isascii() and c.isalnum() for c in text):
        return "cjk_slant" if slant else "cjk"
    return "latin_italic" if slant else "latin"


def get_font(text, role, size):
    if role.startswith("cjk"):
        ft, sl, _ = pfonts.glyph_font(text[0], role, size)
        return ft, sl
    return pfonts.font(role, size), 0.0


def sprite(text, role, size, style):
    """One piece (a Chinese character or a Latin word) as an RGBA image with soft shadow, short dark extrusion, optional
    stroke and a solid, gradient or metal fill. style = (kind, c1, c2, gx, gw, extrude_px, shadow, stroke_px, stroke_rgb)."""
    size = max(6, int(round(size)))
    key = (text, role, size, style)
    if key in _SPR:
        return _SPR[key]
    kind, c1, c2, gx, gw, ext, shadow, spx, scol = style
    ft, sl = get_font(text, role, size)
    x0, y0, x1, y1 = ft.getbbox(text, anchor="ls", stroke_width=spx)
    ext = int(ext)
    pad = int(size * 0.10) + ext + spx + 8
    slw = int(abs(sl) * (y1 - y0)) + 2
    w, h = (x1 - x0) + 2 * pad + slw, (y1 - y0) + 2 * pad
    org = (pad - x0, pad - y0)

    def mask(stw):
        m = Image.new("L", (w, h))
        ImageDraw.Draw(m).text(org, text, font=ft, fill=255, anchor="ls", stroke_width=stw, stroke_fill=255)
        if sl:
            m = m.transform((w, h), Image.AFFINE, (1, sl, -sl * org[1], 0, 1, 0), resample=Image.BICUBIC)
        return np.asarray(m, np.float32) / 255
    mf = mask(0)
    ms = mask(spx) if spx else mf
    E = np.zeros_like(ms)
    for i in range(1, ext + 1):
        dx, dy = int(round(i * 0.55)), i
        E[dy:, dx:] = np.maximum(E[dy:, dx:], ms[:h - dy, :w - dx])
    sil = np.maximum(ms, E)
    S = np.zeros_like(sil)
    if shadow > 0:
        sb = Image.fromarray((sil * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(2.0, size * 0.045)))
        s = np.asarray(sb, np.float32) / 255 * 0.55 * shadow
        oy = max(1, int(size * 0.035))
        S[oy:] = s[:h - oy]
    if kind == "grad":
        t = np.clip((np.arange(w, dtype=np.float32) - org[0] + gx) / max(1.0, gw), 0, 1)[None, :, None]
        F = np.array(c1, np.float32) / 255 + (np.array(c2, np.float32) - np.array(c1, np.float32)) / 255 * t
        F = np.broadcast_to(F, (h, w, 3))
    elif kind == "metal":
        t = np.clip((np.arange(h, dtype=np.float32) - (org[1] + y0)) / max(1.0, y1 - y0), 0, 1)[:, None, None]
        top, mid, bot = (np.array(pk.rgb(c), np.float32) / 255 for c in ("#A9D2F4", "#3E96D7", "#1B5487"))
        F = np.where(t < 0.5, top + (mid - top) * (t / 0.5), mid + (bot - mid) * ((t - 0.5) / 0.5))
        F = np.broadcast_to(F, (h, w, 3))
    else:
        F = np.broadcast_to(np.array(c1, np.float32) / 255, (h, w, 3))
    out = np.zeros((h, w, 4), np.float32)

    def over(rgbv, a):
        a3 = a[..., None]
        out[..., :3] = rgbv * a3 + out[..., :3] * (1 - a3)
        out[..., 3] = a + out[..., 3] * (1 - a)
    over(np.zeros(3, np.float32), S)
    if ext:
        over(np.array(EXTRUDE, np.float32) / 255, E)
    if spx:
        over(np.array(scol, np.float32) / 255, ms)
    over(F, mf)
    a = out[..., 3:4]
    col = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0)
    img = Image.fromarray(np.dstack([col * 255, a * 255]).clip(0, 255).astype(np.uint8), "RGBA")
    sp = {"img": img, "ox": -org[0], "oy": -org[1], "adv": ft.getlength(text), "ink": (x0, y0, x1 + slw // 2, y1), "size": size}
    if len(_SPR) > 3000:
        _SPR.clear()
    _SPR[key] = sp
    return sp


def style_for(kind, c1, c2=None, gx=0.0, gw=1.0, size=100, hero=True, stroke=None):
    ext = max(4, int(round(size * 0.04))) if hero else max(2, int(round(size * 0.035)))
    if kind == "metal":
        stroke = stroke or (max(2, int(size * 0.016)), (0x0E, 0x2D, 0x4A))
    spx, scol = stroke if stroke else (0, (0, 0, 0))
    return (kind, tuple(c1), tuple(c2) if c2 else None, round(gx, 1), round(gw, 1), ext, 0.8 if hero else 1.0, spx, scol)


# ---- runs: a row of pieces ----------------------------------------------------------------------------------------
def make_run(text, size, slant=False, tier="hero", fill=("solid", WHITE, None), idx0=0, colours=None, stroke=None):
    """Lay out a text as pieces (CJK characters, Latin words). Returns dict(pieces, adv, ink) with each piece's pen x.
    colours: optional per-character-index colour override (inline key words)."""
    us = units(text)
    pcs, x = [], 0.0
    prev_cjk = False
    for u in us:
        if u["gap"]:
            x += size * 0.28; prev_cjk = False; continue
        role = piece_role(u["text"], slant, tier)
        cj = role.startswith("cjk")
        sz = size * (1.0 if cj else LATIN_K)
        if colours:
            k = next((colours[i] for i in u["idx"] if i in colours), None)
            sz *= KEY_SCALE if k is not None else 1.0
        ft, _ = get_font(u["text"], role, sz)
        if prev_cjk and cj:
            x -= size * 0.02
        pcs.append({"text": u["text"], "role": role, "size": sz, "x": x, "adv": ft.getlength(u["text"]), "idx": [i + idx0 for i in u["idx"]],
                    "kw": (next((colours[i] for i in u["idx"] if i in colours), None) if colours else None)})
        x += pcs[-1]["adv"]; prev_cjk = cj
    kind, c1, c2 = fill
    gw = max(1.0, x)
    for p in pcs:
        c = c1 if p["kw"] is None else p["kw"]
        st = style_for(kind if p["kw"] is None else "solid", c, c2, p["x"], gw, size, hero=(tier in ("hero", "narrow")), stroke=stroke)
        p["sp"] = sprite(p["text"], p["role"], p["size"], st)
    if pcs:
        ink = (min(p["x"] + p["sp"]["ink"][0] for p in pcs), min(p["sp"]["ink"][1] for p in pcs),
               max(p["x"] + p["sp"]["ink"][2] for p in pcs), max(p["sp"]["ink"][3] for p in pcs))
    else:
        ink = (0, -size * 0.8, 1, 0)
    return {"pieces": pcs, "adv": x, "ink": ink, "size": size}


def run_image(run):
    """All pieces of a run composed into one RGBA image; returns (img, pen_x_in_img, baseline_in_img)."""
    if "img" in run:
        return run["img"]
    boxes = [(p["x"] + p["sp"]["ox"], p["sp"]["oy"], p["x"] + p["sp"]["ox"] + p["sp"]["img"].width, p["sp"]["oy"] + p["sp"]["img"].height)
             for p in run["pieces"]]
    X0, Y0 = math.floor(min(b[0] for b in boxes)), math.floor(min(b[1] for b in boxes))
    X1, Y1 = math.ceil(max(b[2] for b in boxes)), math.ceil(max(b[3] for b in boxes))
    cv = Image.new("RGBA", (X1 - X0, Y1 - Y0), (0, 0, 0, 0))
    for p, b in zip(run["pieces"], boxes):
        cv.alpha_composite(p["sp"]["img"], (int(round(b[0] - X0)), int(round(b[1] - Y0))))
    run["img"] = (cv, -X0, -Y0)
    return run["img"]


# ---- pasting with motion --------------------------------------------------------------------------------------------
def hblur(img, k):
    """Horizontal motion blur (box, premultiplied) of an RGBA image."""
    k = int(k)
    if k < 2:
        return img
    a = np.asarray(img.convert("RGBa"), np.float32)
    pad = np.pad(a, ((0, 0), (k, k), (0, 0)))
    cs = np.cumsum(pad, axis=1)
    out = (cs[:, k:-k] - cs[:, :-2 * k]) / k if pad.shape[1] > 2 * k else a
    out = np.pad(out, ((0, 0), (0, a.shape[1] - out.shape[1]), (0, 0)))
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBa").convert("RGBA")


def put(fr, img, ax, ay, X, Y, s=1.0, alpha=1.0, blur=0.0, mblur=0.0):
    """Paste img so its anchor (ax, ay) lands at (X, Y), scaled s about the anchor, with blur / motion blur / opacity."""
    if alpha <= 0.01:
        return
    if abs(s - 1) > 0.004:
        w, h = max(1, int(round(img.width * s))), max(1, int(round(img.height * s)))
        img = img.resize((w, h), Image.BILINEAR); ax *= s; ay *= s
    if mblur >= 2:
        img = hblur(img, mblur)
    if alpha < 0.995:
        img = img.copy(); img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    fr.paste(img, (int(round(X - ax)), int(round(Y - ay))), img)


def put_blur(fr, img, ax, ay, X, Y, s=1.0, alpha=1.0, blur=0.0, mblur=0.0):
    """put() with a Gaussian blur done on premultiplied colour (no dark fringes)."""
    if blur > 0.6 and alpha > 0.01:
        g = int(blur * 2.2) + 2
        big = Image.new("RGBA", (img.width + 2 * g, img.height + 2 * g), (0, 0, 0, 0))
        big.alpha_composite(img, (g, g))
        img = big.convert("RGBa").filter(ImageFilter.GaussianBlur(blur)).convert("RGBA")
        ax += g; ay += g
    put(fr, img, ax, ay, X, Y, s, alpha, 0.0, mblur)


# ---- line layout ----------------------------------------------------------------------------------------------------
def break_rows(us, maxw):
    """Split caption units into one or two rows by meaning; None when two rows do not fit."""
    tot = sum(u["adv"] for u in us)
    if tot <= maxw:
        return [us]
    best = None
    for i in range(1, len(us)):
        a, b = us[:i], us[i:]
        if not a or not b:
            continue
        if a[-1]["kw"] is not None and a[-1]["kw"] == b[0]["kw"] and a[-1].get("kwid") == b[0].get("kwid"):
            continue
        wa, wb = sum(u["adv"] for u in a), sum(u["adv"] for u in b)
        if wa > maxw or wb > maxw:
            continue
        brk = a[-1].get("brk_after", False)
        score = abs(wa - wb) / maxw - (5 if brk else 0) - (0.6 if (b[0]["text"][:1] in BREAK_BEFORE or a[-1]["text"][-1:] in BREAK_AFTER) else 0)
        if best is None or score < best[0]:
            best = (score, a, b)
    return [best[1], best[2]] if best else None


def caption_units(text, ct, size, colours, idx_off=0, stroke=None):
    """Units of a caption with sprites and their spoken times; gaps become small spaces and possible row breaks."""
    run = make_run(text, size, tier="caption", colours=colours, stroke=stroke)
    us = []
    raw = units(text)
    gaps_after = {}
    pi = 0
    for u in raw:
        if u["gap"]:
            if us:
                us[-1]["brk_after"] = us[-1].get("brk_after", False) or u["brk"]
                us[-1]["gap_after"] = size * 0.28
            continue
        p = run["pieces"][pi]; pi += 1
        us.append({"text": p["text"], "sp": p["sp"], "adv": p["adv"], "kw": p["kw"], "t": min(ct[i] for i in u["idx"]),
                   "idx": [i + idx_off for i in u["idx"]], "brk_after": False, "gap_after": 0.0})
    for u in us:
        u["adv_full"] = u["adv"] + u["gap_after"]
    return us


def lay_rows(rows, size, align, x_ref, base_y):
    """Assign pen x / baseline y to units in rows. align left|right|center at x_ref; base_y = first row's baseline."""
    out = []
    for r, row in enumerate(rows):
        wid = sum(u["adv_full"] for u in row) - (row[-1]["gap_after"] if row else 0)
        x = x_ref if align == "left" else x_ref - wid if align == "right" else x_ref - wid / 2
        for u in row:
            u["x"], u["y"], u["row"] = x, base_y + r * size * 1.22, r
            out.append(u); x += u["adv_full"]
    return out


def fit_rows(text, ct, size, minsize, maxw, colours, warn, tag, stroke=None):
    s = size
    while True:
        us = caption_units(text, ct, s, colours, stroke=stroke)
        for u in us:
            u["adv"] = u["adv_full"]
        rows = break_rows(us, maxw)
        if rows or s <= minsize:
            break
        s *= 0.95
    if rows is None:
        warn.append(f"{tag}: does not fit in two rows even at {s:.0f}px; shorten the line (plan.py --split)")
        rows = [us]
    for u in us:
        u["adv"] = u["adv_full"] - u["gap_after"]
    return rows, s


class Line:
    pass


EDGE = (max(3, 4), EXTRUDE)          # dark edge for text over a bright picture (the reel's white words always carry a dark edge)


def make_caption(L, W, warn, stroke=EDGE):
    ln = L.src; text = ln["text"]; ct = char_times(ln)
    left, right = SAFE["left"] + 10, SAFE["right"] - 10
    rows, s = fit_rows(text, ct, CAPTION_PX, CAPTION_MIN_PX, right - left, kw_colours(text, ln.get("keywords"), ln), warn,
                       f"line {L.id}", stroke=stroke)
    top_base = CAPTION_BASE_Y - (len(rows) - 1) * s * 1.22
    L.units = lay_rows(rows, s, "center", W / 2, top_base)


def mean_lum(arr, box):
    x0, y0, x1, y1 = (int(v) for v in box)
    reg = arr[max(0, y0):max(1, y1), max(0, x0):max(1, x1)].reshape(-1, 3)
    return luminance(tuple(reg.mean(0))) if len(reg) else 0.0


def kw_colours(text, kws, ln):
    cmap = {}
    for k, kw in enumerate(kws or []):
        p = text.find(kw)
        if p >= 0:
            c = colour(ln.get("color") or "gold")
            for i in range(p, p + len(kw)):
                cmap.setdefault(i, c)
    return cmap


def build(ln, plan, W, H, warn, k_hero):
    L = Line(); L.src = ln; L.id = ln.get("id"); L.mode = ln.get("mode") or "caption"
    text = ln["text"]; ct = char_times(ln)
    tag = f"line {L.id}"
    L.units, L.hero, L.col, L.zone = [], None, [], ln.get("zone") or plan.get("zone_default") or "low"
    L.behind = bool(ln.get("behind"))
    left, right = SAFE["left"] + 10, SAFE["right"] - 10
    maxw = right - left
    L.color_name = ln.get("color") or "gold"
    L.interp = L.mode != "caption" and ln.get("hero_from") == "interpretation"
    if L.interp and not ln.get("zone"):
        L.zone = "middle"
    if L.mode == "caption" or L.interp:
        make_caption(L, W, warn)
    if L.mode != "caption":
        kw = ln["keyword"]
        if L.interp:                                   # hero from the interpreter: lands on the English word hero_at
            lead, tail, p = "", "", None
            at = ln.get("hero_at"); q = text.find(at) if at else -1
            L.t_kw = (ct[q] if q >= 0 else (min(ct) if ct else ln["start"])) - LEAD_FRAMES * F1
        else:
            lead, _, tail = split_kw(text, kw)
            p = text.find(kw)
            L.t_kw = ct[p] - LEAD_FRAMES * F1
        L.kw_pos = p
        L.slant = bool(ln.get("slant"))
        L.fill = ln.get("fill") or "solid"
        L.zoneY = ZONES.get(L.zone, ZONES["low"])
        L.lead_text, L.tail_text, L.kw_text = lead, tail, display(kw)
        L.ct = ct
        if L.mode == "poster":
            L.motion = ln.get("motion") or "whip"
            L.dir = ln.get("from") or ("left" if k_hero % 2 == 0 else "right")
        else:
            L.motion = "stack"
    L.t_in = min([u["t"] for u in L.units] or [min(ct) if ct else ln["start"]])
    return L


def layout_hero(L, plan, W, H, warn, light=False, bright=False):
    """Build the hero (poster or stack) and its lead / tail at the zone, choosing the light colour variant if asked."""
    ln = L.src; tag = f"line {L.id}"
    c1 = colour(L.color_name, light)
    c2 = colour(ln.get("color2"), light) if ln.get("color2") else None
    fill = ("metal", c1, None) if L.fill == "metal" else ("grad", c1, c2) if L.fill == "gradient" and c2 else ("solid", c1, None)
    left, right = SAFE["left"] + 10, SAFE["right"] - 10
    maxw = right - left
    text = ln["text"]; p = L.kw_pos; kw = ln["keyword"]
    kwc = kw_colours(text, [k for k in ln.get("keywords") or [] if k != kw], ln)
    stk = EDGE
    L.lead, L.tail = [], []
    if L.mode == "poster":
        size = HERO_SHORT_PX if len(L.kw_text) <= 3 else HERO_PX
        while True:
            run = make_run(L.kw_text, size, L.slant, "hero", fill)
            iw = run["ink"][2] - run["ink"][0]
            if iw <= maxw or size <= HERO_MIN_PX:
                break
            size *= 0.94
        if iw > maxw:
            warn.append(f"{tag}: hero '{L.kw_text}' is too long for {HERO_MIN_PX}px; shrunk to fit, choose a shorter hero")
            size *= maxw / iw * 0.98
            run = make_run(L.kw_text, size, L.slant, "hero", fill)
        L.hero_size = size
        ix0, iy0, ix1, iy1 = run["ink"]
        L.hero = run
        L.hx = W / 2 - (ix0 + ix1) / 2                     # pen x
        L.hy = L.zoneY - (iy0 + iy1) / 2                   # baseline
        top, bot, hl, hr = L.hy + iy0, L.hy + iy1, L.hx + ix0, L.hx + ix1
        ls = LEAD_PX
        if display(L.lead_text):
            rows, ls = fit_rows(L.lead_text, L.ct, LEAD_PX, 72, maxw, kwc, warn, tag + " lead", stroke=stk)
            wid = max(sum(u["adv_full"] for u in r) for r in rows)
            x = min(max(left, hl + W * 0.04), right - wid)
            base = top - ls * 0.30 - (len(rows) - 1) * ls * 1.22
            L.lead = lay_rows(rows, ls, "left", x, base)
        if display(L.tail_text):
            off = len(L.lead_text) + len(kw)
            ct_tail = L.ct[off:]
            rows, ts_ = fit_rows(L.tail_text, ct_tail, LEAD_PX, 72, maxw, {i - off: c for i, c in kwc.items() if i >= off}, warn, tag + " tail",
                                 stroke=stk)
            wid = max(sum(u["adv_full"] for u in r) for r in rows)
            xr = max(min(right, hr - W * 0.04), left + wid)
            base = bot + ts_ * 0.95
            L.tail = lay_rows(rows, ts_, "right", xr, base)
            for u in L.tail:
                u["t"] = u["t"]
    else:  # stack
        chars = [c for c in L.kw_text if c.strip()]
        n = len(chars)
        size = STACK_PX
        step = size * 1.0
        if n * step > 900:
            size = 900 / n; step = size
        runs = [make_run(c, size, L.slant, "hero", fill) for c in chars]
        lead_rows = None
        if display(L.lead_text):
            lead_rows, ls = fit_rows(L.lead_text, L.ct, LEAD_PX, 72, maxw, kwc, warn, tag + " lead", stroke=stk)
            lw = max(sum(u["adv_full"] for u in r) for r in lead_rows)
        cx = W / 2
        beside = lead_rows is not None and len(lead_rows) == 1 and lw <= (right - size - 28) - left
        if beside:
            cx = right - size / 2
        y0 = L.zoneY - (n - 1) * step / 2
        L.col = []
        tprev = -1e9
        for k, (c, r) in enumerate(zip(chars, runs)):
            ix0, iy0, ix1, iy1 = r["ink"]
            base_t = (L.ct[p + L.src["keyword"].find(c)] - LEAD_FRAMES * F1) if p is not None else L.t_kw
            t = max(base_t, tprev + STACK["stagger"] * F1)
            tprev = t
            L.col.append({"run": r, "x": cx - (ix0 + ix1) / 2, "y": y0 + k * step - (iy0 + iy1) / 2, "t": t})
        if lead_rows:
            if beside:
                L.lead = lay_rows(lead_rows, ls, "right", cx - size / 2 - 28, L.zoneY + ls * 0.36)
            else:
                ctop = y0 - step / 2
                L.lead = lay_rows(lead_rows, ls, "center", W / 2, ctop - ls * 0.25 - (len(lead_rows) - 1) * ls * 1.22)
        if display(L.tail_text):
            off = len(L.lead_text) + len(kw)
            rows, ts_ = fit_rows(L.tail_text, L.ct[off:], LEAD_PX * 0.9, 64, maxw, {}, warn, tag + " tail")
            L.tail = lay_rows(rows, ts_, "center", cx if beside else W / 2, y0 + (n - 0.5) * step + ts_ * 1.0)
        L.hero_size = size
    if ln.get("gloss"):
        g = ln["gloss"]; gct = [L.t_kw + 4 * F1] * len(g)
        gcol = {i: colour(ln.get("gloss_color") or "cream") for i in range(len(g))}
        rows, gs = fit_rows(g, gct, LEAD_PX * 0.9, 60, maxw, gcol, warn, tag + " gloss", stroke=stk)
        wid = max(sum(u["adv_full"] for u in r) for r in rows)
        if L.mode == "poster":
            bot_now = max([L.hy + L.hero["ink"][3]] + [u["y"] + u["sp"]["size"] * 0.15 for u in L.tail])
            xr = max(min(right, L.hx + L.hero["ink"][2] - W * 0.02), left + wid)
            L.tail += lay_rows(rows, gs, "right", xr, bot_now + gs * 1.0)
        else:
            bot_now = max(c["y"] + c["run"]["ink"][3] for c in L.col)
            cxx = sum(c["x"] + (c["run"]["ink"][0] + c["run"]["ink"][2]) / 2 for c in L.col) / len(L.col)
            L.tail += lay_rows(rows, gs, "center", cxx, bot_now + gs * 1.0)
    # keep the whole composition inside the safe area
    boxes = []
    if L.hero is not None:
        ix0, iy0, ix1, iy1 = L.hero["ink"]; boxes.append((L.hy + iy0, L.hy + iy1))
    for c in L.col:
        ix0, iy0, ix1, iy1 = c["run"]["ink"]; boxes.append((c["y"] + iy0, c["y"] + iy1))
    for u in L.lead + L.tail:
        boxes.append((u["y"] - u["sp"]["size"] * 0.9, u["y"] + u["sp"]["size"] * 0.15))
    top, bot = min(b[0] for b in boxes), max(b[1] for b in boxes)
    dy = SAFE["top"] - top if top < SAFE["top"] else SAFE["bottom"] - bot if bot > SAFE["bottom"] else 0
    if dy:
        if L.hero is not None:
            L.hy += dy
        for c in L.col:
            c["y"] += dy
        for u in L.lead + L.tail:
            u["y"] += dy
    L.box = (top + dy, bot + dy)
    L.hero_t = L.t_kw if L.mode == "poster" else min(c["t"] for c in L.col)
    L.light = light; L.bright = bright


def hero_box_px(L):
    if L.hero is not None:
        ix0, iy0, ix1, iy1 = L.hero["ink"]
        return (L.hx + ix0, L.hy + iy0, L.hx + ix1, L.hy + iy1)
    xs = [c["x"] + c["run"]["ink"][0] for c in L.col] + [c["x"] + c["run"]["ink"][2] for c in L.col]
    ys = [c["y"] + c["run"]["ink"][1] for c in L.col] + [c["y"] + c["run"]["ink"][3] for c in L.col]
    return (min(xs), min(ys), max(xs), max(ys))


def timing(Ls, dur, warn):
    for i, L in enumerate(Ls):
        nxt = Ls[i + 1] if i + 1 < len(Ls) else None
        L.t_out = min(L.src["end"] + 0.35, nxt.t_in) if nxt else min(L.src["end"] + 0.8, dur)
        if L.mode != "caption":
            land = L.hero_t + 0.15
            out = max(L.t_out, land + HERO_MIN_HOLD)
            if nxt:
                out = min(out, nxt.t_in + 0.6)
                same = next((M for M in Ls[i + 1:i + 3] if M.mode != "caption"), None)
                if same is not None and same.zone == L.zone and same.hero_t < out + BLUR_OUT * F1:
                    out = same.hero_t; L.swap = True
            L.hero_out = min(out, dur)
            if L.hero_out < land + 0.6 and land < dur:
                warn.append(f"line {L.id}: the hero is up only {max(0, L.hero_out - land):.2f}s; give it a longer line or merge with the next")
        L.swap = getattr(L, "swap", False)


# ---- per-frame drawing ----------------------------------------------------------------------------------------------
def unit_state(t, u_t, t_out, nframes_in=CAPTION_IN, out_frames=CAPTION_OUT):
    dt = t - u_t
    if dt < -1e-6:
        return None
    p = dt * FPS / nframes_in
    a, b, s = (0.35 + 0.65 * p, 6 * (1 - p), 1.06 - 0.06 * p) if p < 1 else (1.0, 0.0, 1.0)
    if t > t_out:
        q = (t - t_out) * FPS / out_frames
        if q >= 1:
            return None
        a *= 1 - q; b = max(b, 8 * q)
    return a, b, s


def draw_units(fr, us, t, t_out, out_frames=CAPTION_OUT):
    for u in us:
        st = unit_state(t, u["t"], t_out, out_frames=out_frames)
        if st is None:
            continue
        a, b, s = st
        sp = u["sp"]; img = sp["img"]
        ax, ay = -sp["ox"], -sp["oy"]                       # pen point inside the image
        cxa = ax + (sp["ink"][0] + sp["ink"][2]) / 2; cya = ay + (sp["ink"][1] + sp["ink"][3]) / 2
        X = u["x"] + (sp["ink"][0] + sp["ink"][2]) / 2; Y = u["y"] + (sp["ink"][1] + sp["ink"][3]) / 2
        if b > 0.6 or abs(s - 1) > 0.004 or a < 0.995:
            put_blur(fr, img, cxa, cya, X, Y, s, a, b)
        else:
            fr.paste(img, (int(round(u["x"] - ax)), int(round(u["y"] - ay))), img)


def hero_exit(L, t):
    """(alpha, blur, scale, dy) multipliers for the hero's exit."""
    if t <= L.hero_out:
        return 1.0, 0.0, 1.0, 0.0
    if L.swap:
        q = (t - L.hero_out) * FPS / SWAP["out"]
        return (None if q >= 1 else (1 - q, 2 * q, 1.0, SWAP["drop"] * ease_out(q)))
    q = (t - L.hero_out) * FPS / BLUR_OUT
    return None if q >= 1 else (1 - q, 16 * q, 1 + 0.04 * q, 0.0)


def draw_hero(fr, L, t, W, H):
    ex = hero_exit(L, t)
    if ex is None:
        return
    ea, eb, es, edy = ex
    if L.mode == "poster":
        img, pxi, pyi = run_image(L.hero)
        ix0, iy0, ix1, iy1 = L.hero["ink"]
        ax, ay = pxi + (ix0 + ix1) / 2, pyi + (iy0 + iy1) / 2
        X, Y = L.hx + (ix0 + ix1) / 2, L.hy + (iy0 + iy1) / 2 + edy
        f = (t - L.hero_t) * FPS
        if f < 0:
            pass
        elif L.motion == "whip":
            sgn = -1 if L.dir == "left" else 1
            if f < WHIP["in"]:
                e = ease_expo(f / WHIP["in"])
                if L.dir == "top":
                    put_blur(fr, img, ax, ay, X, Y - 0.22 * H * (1 - e), es, ea, max(eb, 10 * (1 - e)))
                else:
                    put_blur(fr, img, ax, ay, X + sgn * WHIP["travel"] * W * (1 - e), Y, es, ea, eb, WHIP["mblur"] * (1 - e) + 2)
            else:
                g = f - WHIP["in"]
                drift = WHIP["drift"] * ease_out(g / WHIP["drift_frames"]) + 12 * max(0, g - WHIP["drift_frames"]) / FPS
                dx = 0 if L.dir == "top" else -sgn * drift
                dy = drift * 0.5 if L.dir == "top" else 0
                put_blur(fr, img, ax, ay, X + dx, Y + dy, es, ea, eb)
        elif L.motion == "zoom":
            s = 1 + (ZOOM["from_scale"] - 1) * (1 - ease_out(f / (ZOOM["in"] + ZOOM["settle"])))
            b = ZOOM["blur"] * max(0, 1 - f / ZOOM["in"])
            a = min(1.0, 0.4 + 0.6 * f / ZOOM["in"])
            put_blur(fr, img, ax, ay, X, Y, s * es, a * ea, max(b, eb))
        else:  # drop: pieces 1 frame apart, recentred while they arrive
            pcs = L.hero["pieces"]
            vis = [k for k in range(len(pcs)) if f >= k * DROP["stagger"]]
            if vis:
                full = L.hero["adv"]
                last = pcs[vis[-1]]
                vis_w = last["x"] + last["adv"]
                shift = (full - vis_w) / 2
                for k in vis:
                    pc = pcs[k]; sp = pc["sp"]
                    pf = (f - k * DROP["stagger"]) / DROP["in"]
                    e = ease_out(pf)
                    cxi = -sp["ox"] + (sp["ink"][0] + sp["ink"][2]) / 2; cyi = -sp["oy"] + (sp["ink"][1] + sp["ink"][3]) / 2
                    Xp = L.hx + pc["x"] + shift + (sp["ink"][0] + sp["ink"][2]) / 2
                    Yp = L.hy + (sp["ink"][1] + sp["ink"][3]) / 2 + DROP["from_y"] * (1 - e) + edy
                    put_blur(fr, sp["img"], cxi, cyi, Xp, Yp, (DROP["from_scale"] - (DROP["from_scale"] - 1) * e) * es,
                             min(1.0, e * 1.3) * ea, max(DROP["blur"] * (1 - e), eb))
    else:
        for c in L.col:
            f = (t - c["t"]) * FPS
            if f < 0:
                continue
            p = min(1.0, f / STACK["in"])
            img, pxi, pyi = run_image(c["run"])
            ix0, iy0, ix1, iy1 = c["run"]["ink"]
            put_blur(fr, img, pxi + (ix0 + ix1) / 2, pyi + (iy0 + iy1) / 2, c["x"] + (ix0 + ix1) / 2, c["y"] + (iy0 + iy1) / 2 + edy,
                     (1.08 - 0.08 * p) * es, (0.3 + 0.7 * p) * ea, max(STACK["blur"] * (1 - p), eb))
    # lead / tail ride with the hero composition and leave with it
    for u in L.lead + L.tail:
        st = unit_state(t, u["t"], L.hero_out, out_frames=SWAP["out"] if L.swap else BLUR_OUT)
        if st is None:
            continue
        a, b, s = st
        sp = u["sp"]
        put_blur(fr, sp["img"], -sp["ox"] + (sp["ink"][0] + sp["ink"][2]) / 2, -sp["oy"] + (sp["ink"][1] + sp["ink"][3]) / 2,
                 u["x"] + (sp["ink"][0] + sp["ink"][2]) / 2, u["y"] + (sp["ink"][1] + sp["ink"][3]) / 2 + edy, s, a, b)


# ---- overlays: scripture card and title -------------------------------------------------------------------------------
def wrap_rows(text, size, role_tier, maxw, color):
    run = make_run(text, size, tier=role_tier, fill=("solid", color, None))
    rows, cur, x = [], [], 0.0
    for p in run["pieces"]:
        if cur and x + p["adv"] > maxw:
            rows.append(cur); cur, x = [], 0.0
        cur.append(p); x += p["adv"]
    if cur:
        rows.append(cur)
    return rows


def card_image(o):
    """The flat scripture card: white, rounded, navy header with the reference, the verse in heavy dark text."""
    Wc, pad, hd = 880, 56, 112
    body = o["text"].strip()
    size = 62
    while True:
        rows = card_rows(body, size, Wc - 2 * pad)
        if len(rows) <= 7 or size <= 44:
            break
        size -= 3
    lh = size * 1.42
    Hc = hd + 46 + int(len(rows) * lh) + 44
    card = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
    m = Image.new("L", (Wc, Hc)); ImageDraw.Draw(m).rounded_rectangle((0, 0, Wc - 1, Hc - 1), radius=46, fill=255)
    base = Image.new("RGBA", (Wc, Hc), (0xFC, 0xFC, 0xFA, 255)); base.putalpha(m)
    card.alpha_composite(base)
    head = Image.new("RGBA", (Wc, Hc), (0x25, 0x3C, 0x69, 255))
    hm = Image.new("L", (Wc, Hc)); ImageDraw.Draw(hm).rectangle((0, 0, Wc, hd), fill=255)
    head.putalpha(Image.fromarray(np.minimum(np.asarray(hm), np.asarray(m))))
    card.alpha_composite(head)
    ref = o.get("ref") or ""
    if ref:
        draw_tokens(card, tokens(ref), pad, hd / 2 + 16, 44, (0xFB, 0xF4, 0xCA))
    ql = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
    ImageDraw.Draw(ql).text((Wc - pad - 110, hd + 4), "“", font=pfonts.font("cjk", 190), fill=(0x25, 0x3C, 0x69, 40))
    card.alpha_composite(ql)
    y = hd + 46 + size * 0.95
    for row in rows:
        draw_tokens(card, row, pad, y, size, (0x1C, 0x22, 0x30))
        y += lh
    return card


def tokens(text):
    """Latin words (with their punctuation) and spaces as tokens; every Chinese character its own token."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if is_cjk(c):
            out.append(c); i += 1
        elif c.isspace():
            out.append(" "); i += 1
            while i < len(text) and text[i].isspace():
                i += 1
        else:
            j = i
            while j < len(text) and not text[j].isspace() and not is_cjk(text[j]):
                j += 1
            out.append(text[i:j]); i = j
    return out


def tok_font(tok, size):
    if any(is_cjk(c) for c in tok):
        return pfonts.glyph_font(tok[0], "cjk_text", size)[0]
    return pfonts.font("cjk_text", size)


def card_rows(text, size, maxw):
    rows, cur, x = [], [], 0.0
    toks = tokens(text)
    for k, tk in enumerate(toks):
        prev = next((t for t in reversed(cur) if t != " "), "")
        new_lang = cur and is_cjk(tk[0]) and prev and not is_cjk(prev[-1]) and prev[-1] in ".!?;:"
        w = tok_font(tk, size).getlength(tk)
        if cur and (new_lang or (x + w > maxw and tk != " ")):
            while cur and cur[-1] == " ":
                cur.pop()
            rows.append(cur); cur, x = [], 0.0
            if tk == " ":
                continue
        if not cur and tk == " ":
            continue
        cur.append(tk); x += w
    if cur:
        rows.append(cur)
    return rows


def draw_tokens(img, toks, x, y, size, color):
    d = ImageDraw.Draw(img)
    for tk in toks:
        ft = tok_font(tk, size)
        d.text((x, y), tk, font=ft, fill=color + (255,), anchor="ls")
        x += ft.getlength(tk)


def find_coeffs(dst, src):
    A = []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(A, float), np.array(src, float).reshape(8))


def perspective(img, ry, rx, s, f=2400.0):
    w, h = img.size
    cy, sy, cx, sx = math.cos(math.radians(ry)), math.sin(math.radians(ry)), math.cos(math.radians(rx)), math.sin(math.radians(rx))
    pts = []
    for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        x, y = x * s, y * s
        x1, z1 = x * cy, -x * sy
        y2, z2 = y * cx - z1 * sx, y * sx + z1 * cx
        k = f / (f + z2)
        pts.append((x1 * k, y2 * k))
    mx, my = min(p[0] for p in pts), min(p[1] for p in pts)
    Mx, My = max(p[0] for p in pts), max(p[1] for p in pts)
    dst = [(p[0] - mx, p[1] - my) for p in pts]
    co = find_coeffs(dst, [(0, 0), (w, 0), (w, h), (0, h)])
    out = img.transform((int(math.ceil(Mx - mx)) + 1, int(math.ceil(My - my)) + 1), Image.PERSPECTIVE, tuple(co), Image.BICUBIC)
    return out, mx, my


def draw_card(fr, o, t):
    f = (t - o["start"]) * FPS
    if f < 0 or t > o["end"] + CARD["out"] * F1:
        return
    if f < CARD["in"]:
        e = ease_out(f / CARD["in"])
        s = CARD["from_scale"] + (1 - CARD["from_scale"]) * e
        ry = CARD["from_rot_y"] + (CARD["rest_rot_y"] - CARD["from_rot_y"]) * e
        rx = CARD["rest_rot_x"] * e
        blur, alpha, dy = CARD["blur"] * (1 - e), min(1.0, 0.25 + 1.2 * f / CARD["in"]), 0.0
    else:
        s, ry, rx, blur, alpha, dy = 1.0, CARD["rest_rot_y"] + 1.5 * math.sin((t - o["start"]) * 2 * math.pi / 4.0), CARD["rest_rot_x"], 0.0, 1.0, 0.0
    if t > o["end"]:
        q = (t - o["end"]) * FPS / CARD["out"]
        alpha *= 1 - q; s *= 1 - 0.08 * q; dy = -40 * q
    img, mx, my = perspective(o["_img"], ry, rx, s)
    X, Y = 540 + mx, o["_cy"] + my + dy
    sh = img.getchannel("A").resize((max(1, img.width // 4), max(1, img.height // 4))).filter(ImageFilter.GaussianBlur(7)).resize(img.size)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0)); shadow.putalpha(sh.point(lambda v: int(v * 0.30 * alpha)))
    fr.paste(shadow, (int(X), int(Y + 34)), shadow)
    put_blur(fr, img, 0, 0, X, Y, 1.0, alpha, blur)


def build_title(o, W):
    main = display(o.get("main") or "")
    tier = "narrow" if not has_cjk(main) else "hero"
    kind = o.get("fill") or ("metal" if not o.get("color") else "solid")
    c1 = colour(o.get("color") or "blue")
    size = 200
    while True:
        r = make_run(main, size, bool(o.get("slant")), tier, ("metal" if kind == "metal" else "solid", c1, None))
        if r["ink"][2] - r["ink"][0] <= 860 or size < 110:
            break
        size *= 0.94
    zy = ZONES.get(o.get("zone") or "top", ZONES["top"])
    ix0, iy0, ix1, iy1 = r["ink"]
    o["_main"] = (r, 540 - (ix0 + ix1) / 2, zy - (iy0 + iy1) / 2)
    o["_sub"] = None
    if o.get("sub"):
        ssz = 62
        while True:
            s = make_run(o["sub"], ssz, False, "caption", ("solid", colour(o.get("sub_color") or "ice"), None), stroke=EDGE)
            if s["ink"][2] - s["ink"][0] <= 860 or ssz <= 36:
                break
            ssz -= 2
        sx0, sy0, sx1, sy1 = s["ink"]
        o["_sub"] = (s, 540 - (sx0 + sx1) / 2, zy - (iy0 + iy1) / 2 + iy1 + 26 - sy0)


def draw_title(fr, o, t):
    f = (t - o["start"]) * FPS
    if f < 0:
        return
    if t > o["end"]:
        q = (t - o["end"]) * FPS / BLUR_OUT
        if q >= 1:
            return
        ea, eb = 1 - q, 16 * q
    else:
        ea, eb = 1.0, 0.0
    r, hx, hy = o["_main"]
    pcs = r["pieces"]
    stag = 2
    for k, pc in enumerate(pcs):
        pf = (f - k * stag) / DROP["in"]
        if pf < 0:
            continue
        e = ease_out(pf); sp = pc["sp"]
        cxi = -sp["ox"] + (sp["ink"][0] + sp["ink"][2]) / 2; cyi = -sp["oy"] + (sp["ink"][1] + sp["ink"][3]) / 2
        put_blur(fr, sp["img"], cxi, cyi, hx + pc["x"] + (sp["ink"][0] + sp["ink"][2]) / 2,
                 hy + (sp["ink"][1] + sp["ink"][3]) / 2 + DROP["from_y"] * (1 - e), DROP["from_scale"] - (DROP["from_scale"] - 1) * e,
                 min(1.0, e * 1.3) * ea, max(DROP["blur"] * (1 - e), eb))
    if o["_sub"] and f >= len(pcs) * stag + DROP["in"] + 6:
        s, sx, sy = o["_sub"]
        img, px, py = run_image(s)
        put_blur(fr, img, px, py, sx, sy, 1.0, ea, eb)


# ---- picture effects ------------------------------------------------------------------------------------------------
def zoom_crop(arr, s, cy_frac=0.45):
    H, W = arr.shape[:2]
    if s <= 1.001:
        return arr
    w, h = W / s, H / s
    x0 = (W - w) / 2; y0 = min(max(0.0, H * cy_frac - h * cy_frac), H - h)
    im = Image.fromarray(arr).resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))
    return np.asarray(im)


def flash_fx(arr, b, white_on=True):
    if b <= 0.01:
        return arr
    acc = arr.astype(np.float32)
    n = 1
    for k in (1, 2, 3):
        acc += zoom_crop(arr, 1 + 0.055 * k * b, 0.5).astype(np.float32); n += 1
    acc /= n
    white = min(1.0, 0.9 * b ** 1.5) if white_on else 0.0
    return np.clip(acc * (1 - white) + 255 * white, 0, 255).astype(np.uint8)


def whip_fx(arr, b):
    k = int(140 * b)
    if k < 3:
        return arr
    a = arr.astype(np.float32)
    pad = np.pad(a, ((0, 0), (k, k), (0, 0)), mode="edge")
    cs = np.cumsum(pad, axis=1)
    out = (cs[:, 2 * k:] - cs[:, :-2 * k]) / (2 * k)
    out = out[:, :arr.shape[1]]
    return np.clip(out, 0, 255).astype(np.uint8)


# ---- main -----------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop")
    ap.add_argument("--crop", default=None, help="source region X:Y:W:H to use before vertical framing (e.g. the stage half of a livestream)")
    ap.add_argument("--focus", type=float, default=0.5, help="horizontal centre of the vertical crop, 0-1")
    ap.add_argument("--matte", default=None, help="matte.mp4 from matte.py: lines with behind=true put the hero behind the speaker")
    ap.add_argument("--no-punch", action="store_true", help="no slow punch-in while a hero is up")
    ap.add_argument("--no-text", action="store_true", help="picture effects only (a clean clip for the cover)")
    ap.add_argument("--phone", action="store_true", help="also write <out>_phone.mp4 under 28 MiB")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    ap.add_argument("--to", type=float, default=None, help="render only the first N seconds (a quick look)")
    a = ap.parse_args()
    t_start = time.time()
    W, H = (int(v) for v in a.size.lower().split("x"))
    if (W, H) != (1080, 1920):
        sys.exit("this renderer lays out at 1080x1920")
    plan = load(a.plan)
    err, warn = check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    info = probe(a.video); dur = info["duration"]
    if a.to:
        dur = min(dur, a.to)
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    Ls, kh = [], 0
    for ln in lines:
        L = build(ln, plan, W, H, warn, kh)
        if L.mode != "caption":
            kh += 1
            layout_hero(L, plan, W, H, warn)
        Ls.append(L)
    overlays = [dict(o) for o in plan.get("overlays") or []]
    for o in overlays:
        if o["kind"] == "card":
            o["_img"] = card_image(o)
            # "cy" (optional) places the card's centre exactly, for a face that sits between the zones
            o["_cy"] = float(o["cy"]) if isinstance(o.get("cy"), (int, float)) else {"top": 560, "middle": 820, "low": 1000}.get(o.get("zone") or "low", 1000)
            if o["_cy"] + o["_img"].height / 2 > SAFE["bottom"]:
                o["_cy"] = SAFE["bottom"] - o["_img"].height / 2
            for L in Ls:
                if L.t_in < o["end"] + 0.1 and L.src["end"] > o["start"] - 0.1:
                    L.hidden = True
                    if L.mode != "caption":
                        warn.append(f"line {L.id}: a {L.mode} under the scripture card is hidden")
        elif o["kind"] == "question":
            for L in Ls:
                if L.t_in < o["end"] + 0.1 and L.src["end"] > o["start"] - 0.1 and L.mode == "caption":
                    L.hidden = True
        elif o["kind"] == "title":
            build_title(o, W)
    timing(Ls, dur, warn)
    MO = moments.Moments(plan, W, H, warn)
    all_words = [w for ln in lines for w in ln.get("words", [])]
    matte_ok = bool(a.matte and os.path.isfile(a.matte))
    if any(L.behind for L in Ls) and not matte_ok:
        warn.append("some lines ask for behind=true but no --matte was given; the heroes are drawn in front (run matte.py)")
    trans = [(L.src["start"], L.src["transition"]) for L in Ls if L.src.get("transition")]
    trans += [(float(p_["t"]), p_["kind"]) for p_ in plan.get("picture_transitions") or []]

    # picture punch-in envelope
    def punch(t):
        if a.no_punch:
            return 1.0
        env = 0.0
        for L in Ls:
            if L.mode == "caption" or getattr(L, "hidden", False):
                continue
            t0, t1 = L.hero_t, L.hero_out + BLUR_OUT * F1
            if t0 <= t <= t1:
                env = max(env, smooth((t - t0) / max(0.5, t1 - t0)) * 0.85 + 0.15 * smooth((t - t0) / 0.2))
            elif t1 < t < t1 + 0.35:
                env = max(env, smooth(1 - (t - t1) / 0.35))
        return 1 + PUNCH * env

    pre = ""
    if a.crop:
        cx_, cy_, cw_, ch_ = a.crop.split(":")
        pre = f"crop={cw_}:{ch_}:{cx_}:{cy_},"
    if a.frame == "crop":
        vf = pre + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,setsar=1,fps={FPS}"
        vflag = "-vf"
    else:
        vf = (f"[0:v]{pre}split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
              f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}")
        vflag = "-filter_complex"
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FFMPEG, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tlim = ["-t", f"{dur:.3f}"]
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", *tlim, "-i", a.video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    mdec = None
    if matte_ok:
        mdec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", a.matte, "-vf", f"scale={W}:{H},fps={FPS}", "-f", "rawvideo",
                                 "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", *tlim, "-i", a.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf,
                            "-pix_fmt", "yuv420p", *acodec, "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    fsz = W * H * 3
    qin, qout = queue.Queue(8), queue.Queue(8)

    def reader():
        while True:
            buf = dec.stdout.read(fsz)
            m = mdec.stdout.read(W * H) if mdec else None
            if len(buf) < fsz:
                qin.put(None); return
            qin.put((buf, m))

    def writer():
        while True:
            b = qout.get()
            if b is None:
                return
            enc.stdin.write(b)
    threading.Thread(target=reader, daemon=True).start()
    thw = threading.Thread(target=writer, daemon=True); thw.start()
    n, prev_m, contrast_notes = 0, None, []
    while True:
        item = qin.get()
        if item is None:
            break
        buf, mbuf = item
        t = n / FPS; n += 1
        arr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        s = punch(t)
        arr = zoom_crop(arr, s)
        arr = MO.picture(arr, t)
        if not a.no_text:
            MO.grab_faces(overlays, arr, t)
        alpha = None
        if mbuf is not None and len(mbuf) == W * H and not MO.active(t):
            m = np.frombuffer(mbuf, np.uint8).reshape(H, W).astype(np.float32) / 255
            m = m if prev_m is None else 0.6 * m + 0.4 * prev_m
            prev_m = m
            alpha = zoom_crop((m * 255).astype(np.uint8), s).astype(np.float32)[..., None] / 255 if s > 1.001 else m[..., None]
        for tc, kind in trans:
            if kind == "flash":
                p = (t - (tc - FLASH_T / 2 * F1)) / (FLASH_T * F1)
                if 0 <= p <= 1:
                    arr = flash_fx(arr, math.sin(math.pi * p))
            elif kind == "whip":
                if -6 * F1 <= t - tc < 6 * F1:
                    arr = moments.Moments.whip_pan(arr, t, tc)
            elif kind == "zoom_through":
                if -36 * F1 <= t - tc < 8 * F1:
                    arr = moments.Moments.zoom_through(arr, t, tc)
            elif kind == "push":
                p = (t - (tc - 4 * F1)) / (8 * F1)
                if 0 <= p <= 1:
                    arr = flash_fx(arr, math.sin(math.pi * p), white_on=False)
        if a.no_text:
            qout.put(np.ascontiguousarray(arr).tobytes()); continue
        base = arr
        fr = Image.fromarray(arr.copy())
        behind_used = False
        for L in Ls:
            if L.mode == "caption" or getattr(L, "hidden", False):
                continue
            if t < min([L.hero_t] + [u["t"] for u in L.lead]) - 1e-6 or t > L.hero_out + 0.5:
                continue
            if not getattr(L, "checked", False) and t >= L.hero_t:
                L.checked = True                               # colour against the actual picture behind the hero
                x0, y0, x1, y1 = (int(v) for v in hero_box_px(L))
                reg = arr[max(0, y0):max(1, y1), max(0, x0):max(1, x1)].reshape(-1, 3)
                bg = tuple(reg.mean(0)) if len(reg) else (128, 128, 128)
                c = colour(L.color_name)
                pal = pk.PALETTE.get(L.color_name, {})
                comp_bright = mean_lum(arr, (SAFE["left"], L.box[0], SAFE["right"], L.box[1])) > 0.5
                use_light = contrast(c, bg) < 2.2 and bool(pal.get("light"))
                if use_light or comp_bright:
                    layout_hero(L, plan, W, H, warn, light=use_light, bright=comp_bright)
                if use_light:
                    contrast_notes.append(f"line {L.id}: {L.color_name} was too dark on this picture; used its light variant {pal['light']}")
                if luminance(c) > 0.55 and luminance(bg) > 0.55:
                    contrast_notes.append(f"line {L.id}: light word on a bright picture (background luminance {luminance(bg):.2f}); consider navy/red or another zone")
            draw_hero(fr, L, t, W, H)
            if L.behind and alpha is not None:
                behind_used = True
        if behind_used:
            drawn = np.asarray(fr, np.float32)
            fr = Image.fromarray((drawn * (1 - alpha) + base.astype(np.float32) * alpha).clip(0, 255).astype(np.uint8))
        for L in Ls:
            if (L.mode == "caption" or L.interp) and not getattr(L, "hidden", False) and L.t_in - 0.01 <= t <= L.t_out + CAPTION_OUT * F1:
                if not getattr(L, "cap_checked", False) and L.units:
                    L.cap_checked = True
                    bx = (min(u["x"] for u in L.units), min(u["y"] for u in L.units) - CAPTION_PX, max(u["x"] + u["adv"] for u in L.units),
                          max(u["y"] for u in L.units) + 10)
                    pass
                if (L.src.get("caption_style") or plan.get("caption_style")) == "active" and L.mode == "caption":
                    moments.draw_active_caption(fr, L.src, t, L.t_out, W, H)
                else:
                    draw_units(fr, L.units, t, L.t_out)
        for o in overlays:
            if o["kind"] == "card":
                draw_card(fr, o, t)
            elif o["kind"] == "name":
                moments.draw_name(fr, o, t, W, H)
            elif o["kind"] == "question":
                moments.draw_question(fr, o, t, W, H, all_words)
            elif o["start"] <= t <= o["end"] + BLUR_OUT * F1:
                draw_title(fr, o, t)
        qout.put(np.asarray(fr).tobytes())
    qout.put(None); thw.join()
    enc.stdin.close(); enc.wait(); dec.wait()
    if mdec:
        mdec.kill()
    warn += contrast_notes
    base_out = os.path.splitext(a.out)[0]
    out = {"tool": "render", "ok": True, "out": a.out, "frames": n, "seconds": round(n / FPS, 2), "render_seconds": round(time.time() - t_start, 1)}
    if not a.no_text:
        def srt_t(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base_out + ".srt", "w", encoding="utf-8") as f:
            for i, L in enumerate(Ls):
                f.write(f"{i + 1}\n{srt_t(L.t_in)} --> {srt_t(max(L.t_out, getattr(L, 'hero_out', 0)))}\n{display(L.src['text'])}\n\n")
        plan_copy = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
        if os.path.abspath(a.plan) != plan_copy:
            shutil.copyfile(a.plan, plan_copy)
        ev = []
        for L in Ls:
            if getattr(L, "hidden", False):
                continue
            if L.mode == "caption":
                ev.append({"t": L.t_in + 0.25, "kind": "caption", "line": L.id})
            else:
                ev.append({"t": L.hero_t + 1.5 * F1, "kind": f"{L.mode} {getattr(L, 'motion', '')} (moving)".strip(), "line": L.id})
                ev.append({"t": L.hero_t + 0.45, "kind": f"{L.mode} (landed)", "line": L.id})
        for o in overlays:
            ev.append({"t": o["start"] + 6 * F1, "kind": f"{o['kind']} (entering)", "line": None})
            ev.append({"t": o["start"] + 0.8, "kind": f"{o['kind']} (resting)", "line": None})
        for tc, kind in trans:
            ev.append({"t": tc, "kind": f"transition {kind}", "line": None})
        ev = sorted([e for e in ev if 0 <= e["t"] < dur], key=lambda e: e["t"])
        save(base_out + ".pk.json", {"video": os.path.abspath(a.out), "events": ev, "warnings": warn, "fonts": pfonts.used(),
                                     "lines": [{"id": L.id, "mode": L.mode, "t_in": round(L.t_in, 3), "t_out": round(L.t_out, 3)} for L in Ls]})
        out.update(srt=base_out + ".srt", plan=plan_copy, fonts=pfonts.used(),
                   modes={m: sum(1 for L in Ls if L.mode == m) for m in ("caption", "poster", "stack")},
                   overlays=[o["kind"] for o in overlays], transitions=len(trans), matte=matte_ok)
    if a.phone:
        size_mb = os.path.getsize(a.out) / 1048576
        phone = base_out + "_phone.mp4"
        if size_mb <= 28:
            shutil.copyfile(a.out, phone)
        else:
            kbps = int((28 * 8 * 1024 * 1024 / max(1.0, dur) - 160_000) / 1000)
            for k in (1.0, 0.85, 0.7):
                subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", a.out, "-c:v", "libx264", "-preset", "medium",
                                "-b:v", f"{int(kbps * k)}k", "-maxrate", f"{int(kbps * k * 1.4)}k", "-bufsize", f"{int(kbps * k * 2)}k",
                                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", phone])
                if os.path.getsize(phone) / 1048576 <= 28.5:
                    break
        out["phone"] = phone; out["phone_mb"] = round(os.path.getsize(phone) / 1048576, 1)
    out["warnings"] = warn
    report(**out)


if __name__ == "__main__":
    main()
