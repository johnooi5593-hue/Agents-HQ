"""Render a clip in the Yellow Serif Kinetic style from its planning page (plan.json).

usage: python3 .claude/skills/yellow-serif/scripts/render.py <video> <plan.json> <out.mp4> [--size 1080x1920] [--frame crop|blur] [--font-size 84]
       python3 .claude/skills/yellow-serif/scripts/render.py <video> <plan.json> <clean.mp4> --no-captions   (vertical, no captions: for the cover)

White heavy-serif captions with a soft dark shadow; key words in #FBC238 at 1.08x; per line one main motion:
  type   characters appear as they are spoken, 2-3 frames each (never ahead of the speech)
  pop    key words pop: 85% -> 108% -> 100% over 0.22 s with a fade in (the rest of the line types)
  burst  a standalone big phrase (brush font, 1.8x) lands over the line: 1.35x -> 1.0 in 0.28 s, short shake, zoom blur;
         the line behind it turns grey; held at least 0.6 s
  flash  the line appears in 0.14 s with a 2-frame bright edge and a light-leak flare
  + shine: a narrow slanted bright band sweeps through the key words' glyphs once (0.35 s) after they have settled
Layouts per line: subtitle (bottom, 8% sides, 15% bottom, two rows max), fullscreen (#08090B with a perspective grid),
darken (picture at ~45% with big vertical yellow words), torn (picture in a torn-paper frame, captions below).
A line with "transition": "leak" opens with a light-leak transition (owner overlay clip from assets/overlays/ if present).

Writes <out>.mp4 (audio from the source), <out>.ass (editable captions with the styling and timings for Aegisub; CapCut
reads <out>.srt), <out>.ys.json (events for preview.py) and a copy of plan.json beside the output. Prints one JSON line.
"""
import argparse, os, queue, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from common import (BASE_PX, BLACK, BOTTOM, BURST, BURST_HOLD, BURST_SCALE, COMMA, FLASH, FPS, FFMPEG, GREY, GREY_ALPHA, KEY_SCALE,  # noqa: E402
                    LEAK, POP, SHINE, SHINE_RGB, SIDE, WHITE, YELLOW, char_times, check, display, find_all, load, report, save, units,
                    width_units)
import fonts, leaks  # noqa: E402

BREAK_BEFORE = set("像是在但就而所因如可然还也都又才把被让给从和与或先再即")
BREAK_AFTER = set("的了吗呢吧啊么着过")
CJK_MID = 0.38          # a CJK glyph's visual centre sits about 0.38 em above the baseline


def ease_out(x): x = min(1.0, max(0.0, x)); return 1 - (1 - x) ** 3
def ease_io(x): x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)
def rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---- glyph sprites (cached) ---------------------------------------------------------------------------------------
_SPR = {}


def sprite(text, role, size, color, alpha=1.0, shadow=1.0):
    """Text rendered once: premultiplied float32 fill and shadow layers plus the offset of the canvas from the pen
    position (left, baseline)."""
    size = max(6, int(round(size)))
    key = (text, role, size, color, round(alpha, 2), round(shadow, 2))
    if key in _SPR:
        return _SPR[key]
    ft = fonts.font(role, size)
    bold = max(1, round(size * 0.022)) if role == "brush" else 0          # brush strokes a little heavier (photo 2)
    so = max(2, round(size * 0.035))
    x0, y0, x1, y1 = ft.getbbox(text, anchor="ls", stroke_width=bold + so)
    pad = int(size * 0.2) + 4
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    ox, oy = x0 - pad, y0 - pad
    org = (-ox, -oy)
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text(org, text, font=ft, fill=255, anchor="ls", stroke_width=bold, stroke_fill=255)
    ms = Image.new("L", (w, h)); ImageDraw.Draw(ms).text((org[0], org[1] + size * 0.03), text, font=ft, fill=255, anchor="ls",
                                                         stroke_width=bold + so, stroke_fill=255)
    fa = np.asarray(m, np.float32) / 255
    if role == "brush":                                                    # dry-brush edges
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
        nz = np.asarray(Image.fromarray((rng.random((max(1, h // 3), max(1, w // 3))) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
        fa = np.clip((fa - nz * 0.3) * 1.45, 0, 1)
    blur = np.asarray(ms.filter(ImageFilter.GaussianBlur(size * 0.07)), np.float32) / 255
    sa = np.maximum(blur * 0.8, np.asarray(ms, np.float32) / 255 * 0.35) * shadow
    c = np.array(color, np.float32) / 255
    fill = np.dstack([fa[..., None] * c * alpha, fa * alpha]).astype(np.float32)
    shad = np.dstack([np.zeros((h, w, 3), np.float32), sa]).astype(np.float32)
    sp = {"fill": fill, "shad": shad, "ox": ox, "oy": oy, "adv": ft.getlength(text), "w": w, "h": h, "size": size}
    if len(_SPR) > 4000:
        _SPR.clear()
    _SPR[key] = sp
    return sp


def glow_of(sp):
    """A soft bright halo around the glyphs (the flash's light edge)."""
    if "glow" not in sp:
        a = Image.fromarray((sp["fill"][..., 3] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(2, sp["size"] * 0.09)))
        g = np.asarray(a, np.float32) / 255
        sp["glow"] = g[..., None] * np.array([1.0, 0.96, 0.82], np.float32)
    return sp["glow"]


def blit(fr, arr, x, y, a=1.0, add=False, shine=None):
    """Composite a premultiplied RGBA float sprite (or an additive RGB glow) onto the uint8 frame at (x, y)."""
    H, W = fr.shape[:2]; h, w = arr.shape[:2]; x, y = int(round(x)), int(round(y))
    xa, ya, xb, yb = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if xb <= xa or yb <= ya or a <= 0.002:
        return
    sub = arr[ya - y:yb - y, xa - x:xb - x]
    reg = fr[ya:yb, xa:xb].astype(np.float32)
    if add:
        reg += sub * (255 * a)
    else:
        rgbp, al = sub[..., :3], sub[..., 3:4]
        if shine is not None:                                               # bright band, only inside the glyphs
            uc, bw, ymid, k = shine
            gy, gx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
            band = np.exp(-(((gx + (gy - ymid) * 0.36) - uc) / bw) ** 2)[..., None] * k
            rgbp = rgbp + (np.array(SHINE_RGB, np.float32) / 255 * al - rgbp) * band
        reg = reg * (1 - al * a) + rgbp * (255 * a)
    fr[ya:yb, xa:xb] = np.clip(reg + 0.5, 0, 255).astype(np.uint8)


# ---- backgrounds ------------------------------------------------------------------------------------------------
def grid_bg(W, H):
    """Near-black #08090B with a faint perspective grid floor and ceiling (photos 1, 5, 7)."""
    s = 2
    im = Image.new("RGB", (W * s, H * s), BLACK); d = ImageDraw.Draw(im, "RGBA")
    vx = W * s / 2
    for (yh, yend, al) in ((H * s * 0.62, H * s, 70), (H * s * 0.30, 0, 42)):
        for i in range(-10, 11):
            xb = vx + i * W * s * 0.2
            d.line([(vx + (xb - vx) * 0.16, yh), (xb, yend)], fill=(170, 172, 182, al), width=2 * s)
        for k in range(1, 9):
            f = (k / 8) ** 1.9
            yk = yh + (yend - yh) * f
            d.line([(0, yk), (W * s, yk)], fill=(170, 172, 182, int(al * (0.5 + 0.5 * f))), width=2 * s)
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(im, np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vig = 1 - 0.55 * np.clip(((xx / W - 0.5) ** 2 * 1.2 + (yy / H - 0.5) ** 2) * 2.2, 0, 1)
    base = np.array(BLACK, np.float32)
    return np.clip(base + (a - base) * vig[..., None], 0, 255).astype(np.uint8)


def torn_frame(W, H, seed=11):
    """Box, inner (picture) mask and paper-rim mask of a torn-paper frame in the upper part (photo 1)."""
    bx0, bx1, by0, by1 = int(W * 0.065), W - int(W * 0.065), int(H * 0.035), int(H * 0.60)
    bw, bh = bx1 - bx0, by1 - by0
    rng = np.random.default_rng(seed); A = W * 0.016

    def prof(n, amp):
        """Torn edge: slow wander, irregular chunks, a little fibre."""
        lo = np.cumsum(rng.normal(0, 1, n)); lo -= np.linspace(lo[0], lo[-1], n)
        lo = lo / (np.abs(lo).max() + 1e-6) * amp * 0.45
        mid = np.convolve(rng.normal(0, 1, n), np.ones(29) / 29, "same"); mid = mid / (np.abs(mid).max() + 1e-6) * amp * 0.7
        hf = np.convolve(rng.normal(0, 1, n), np.ones(5) / 5, "same") * amp * 0.12
        return np.clip(amp * 0.6 + lo + mid + hf, 0, None)
    xs, ys = np.arange(bw, dtype=np.float32)[None, :], np.arange(bh, dtype=np.float32)[:, None]
    outer = [prof(bh, A), prof(bh, A), prof(bw, A), prof(bw, A)]
    inner = [o + A * 1.1 + prof(len(o), A * 1.2) for o in outer]

    def mask(p):
        l, r, t, b = p
        d = np.minimum(np.minimum(xs - l[:, None], (bw - 1 - xs) - r[:, None]), np.minimum(ys - t[None, :], (bh - 1 - ys) - b[None, :]))
        return np.clip(d + 0.5, 0, 1).astype(np.float32)
    mo, mi = mask(outer), mask(inner)
    rim = mo * (1 - mi)
    grain = 0.86 + 0.14 * np.asarray(Image.fromarray((rng.random((bh // 2, bw // 2)) * 255).astype(np.uint8)).resize((bw, bh)), np.float32) / 255
    return (bx0, by0, bx1, by1), mi[..., None], rim[..., None], grain[..., None]


# ---- layout -----------------------------------------------------------------------------------------------------
def measure(us, size, kcover, role="serif"):
    for u in us:
        u["size"] = size * (KEY_SCALE if u["kw"] is not None else 1.0)
        u["adv"] = size * 0.42 if u["gap"] else fonts.font(role, u["size"]).getlength(u["text"])


def break_rows(us, max_w, text):
    """One row, or two rows split by meaning: a comma first, then a clause word, then even halves. Never inside a
    key word or a Latin word. Returns a list of unit lists, or None if two rows do not fit."""
    tot = sum(u["adv"] for u in us)
    has_brk = any(u["gap"] and u["brk"] for u in us)
    if tot <= max_w and not (has_brk and tot > max_w * 0.62):
        return [us]
    best = None
    for i in range(1, len(us)):
        a, b = [u for u in us[:i]], [u for u in us[i:]]
        while a and a[-1]["gap"]: a = a[:-1]
        while b and b[0]["gap"]: b = b[1:]
        if not a or not b:
            continue
        if us[i - 1]["kw"] is not None and us[i - 1]["kw"] == us[i]["kw"]:
            continue
        wa, wb = sum(u["adv"] for u in a), sum(u["adv"] for u in b)
        if wa > max_w or wb > max_w:
            continue
        brk = us[i]["gap"] and us[i]["brk"] or us[i - 1]["gap"] and us[i - 1]["brk"]
        score = abs(wa - wb) / max(1, max_w) - (5 if brk else 0) - (0.6 if (b[0]["text"][:1] in BREAK_BEFORE or a[-1]["text"][-1:] in BREAK_AFTER) else 0)
        score += 0.4 if us[i]["gap"] is False and us[i - 1]["gap"] is False and not brk else 0
        if best is None or score < best[0]:
            best = (score, a, b)
    return [best[1], best[2]] if best else None


def place_rows(line, ct, kcover, size, max_w, cx, anchor_y, anchor="bottom", min_size=None, role="serif", warn=None):
    """Lay a caption out in rows at `size` (shrinking if needed); returns units with x (pen) and y (baseline)."""
    text = line["text"]; min_size = min_size or size * 0.78
    us0 = units(text)
    s = size
    while True:
        us = [dict(u, kw=next((kcover[i] for i in u["idx"] if i in kcover), None)) for u in us0]
        measure(us, s, kcover, role)
        rows = break_rows(us, max_w, text)
        if rows or s <= min_size:
            break
        s *= 0.95
    if rows is None:
        rows = [us]; warn.append(f"line {line.get('id')}: does not fit in two rows even at {s:.0f}px; shorten the caption (plan.py --max-chars)")
        while sum(u["adv"] for u in us) > max_w and s > 20:
            s *= 0.95; measure(us, s, kcover, role)
    elif s < size - 0.5:
        warn.append(f"line {line.get('id')}: shrunk to {s:.0f}px to fit two rows")
    row_h = s * 1.3
    block_h = s * 1.12 + (len(rows) - 1) * row_h
    top = anchor_y - block_h if anchor == "bottom" else anchor_y - block_h / 2 if anchor == "center" else anchor_y
    out = []
    for r, row in enumerate(rows):
        x = cx - sum(u["adv"] for u in row) / 2
        base = top + s * 0.92 + r * row_h
        for u in row:
            if not u["gap"]:
                out.append({"text": u["text"], "kw": u["kw"], "size": u["size"], "x": x, "y": base, "row": r, "adv": u["adv"],
                            "t": min(ct[i] for i in u["idx"]), "role": role, "idx": u["idx"]})
            x += u["adv"]
    return out, (top, top + block_h), s


class Line:
    pass


def build(line, plan, W, H, base, warn):
    L = Line(); L.src = line; L.id = line.get("id")
    L.layout = line.get("layout") or plan.get("layout_default") or "subtitle"
    L.motion = line.get("motion") or "type"
    text = line["text"]; ct = char_times(line)
    kws = [k for k in (line.get("keywords") or []) if k and k in text]
    kcover = find_all(text, kws)
    sa = line.get("standalone") if line.get("standalone") and line["standalone"] in text else None
    max_w = W * (1 - 2 * SIDE)
    L.units, L.column, L.head, L.burst = [], [], [], None
    if L.layout == "darken":
        col = sa or (kws[0] if kws else None) or (text if width_units(display(text)) <= 6 else None)
        if col:
            ci = text.find(col); chars = [(c, ci + k) for k, c in enumerate(col) if c.strip() and display(c)]
            n = max(1, len(chars))
            cs = max(base * 1.8, min(H * 0.60 / n, W * 0.30, base * 3.6))
            step = cs * 1.02; cy0 = H * 0.42 - (n - 1) * step / 2
            role = "brush" if line.get("standalone_font") == "brush" else "serif"
            for k, (c, i) in enumerate(chars):
                adv = fonts.font(role, cs).getlength(c)
                L.column.append({"text": c, "kw": 0, "size": cs, "x": W / 2 - adv / 2, "y": cy0 + k * step + cs * CJK_MID, "adv": adv,
                                 "t": ct[i], "role": role, "color": YELLOW})
            gtop = cy0 + (n - 1) * step + cs * 0.62 + base * 0.35
            L.units, L.box, L.size = place_rows(line, ct, {}, base * 0.9, max_w, W / 2, gtop, "top", warn=warn)
            for u in L.units:
                u["color"] = (0xB4, 0xB4, 0xB4); u["alpha"] = 0.85
            if L.box[1] > H * (1 - BOTTOM) + 2:
                warn.append(f"line {L.id}: the grey line under the column reaches into the bottom margin")
        else:
            warn.append(f"line {L.id}: darken needs a standalone phrase or a keyword for the vertical words; showing the line centred")
            L.units, L.box, L.size = place_rows(line, ct, kcover, base * 1.55, W * 0.84, W / 2, H * 0.46, "center", warn=warn)
    elif L.layout == "fullscreen":
        size = base * 1.55
        L.units, L.box, L.size = place_rows(line, ct, kcover, size, W * 0.84, W / 2, H * 0.47, "center", warn=warn)
        hd = line.get("head")
        if hd:
            items = [(hd.get("big"), base * 3.2, YELLOW), (hd.get("word"), base * 0.95, WHITE), (hd.get("gloss"), base * 0.78, WHITE)]
            items = [it for it in items if it[0]]
            hh = sum(sz * (0.98 if k == 0 else 1.18) for k, (_, sz, _) in enumerate(items)) + base * 0.45
            shift = hh / 2
            for u in L.units:
                u["y"] += shift
            L.box = (L.box[0] + shift, L.box[1] + shift)
            y = L.box[0] - hh
            t0 = min(u["t"] for u in L.units) if L.units else line["start"]
            for k, (txt, sz, col) in enumerate(items):
                y += sz * (0.98 if k == 0 else 1.18) * (0.86 if k == 0 else 0.84)
                adv = fonts.font("serif", sz).getlength(txt)
                L.head.append({"text": txt, "kw": None, "size": sz, "x": W / 2 - adv / 2, "y": y, "adv": adv, "t": t0, "role": "serif", "color": col})
                y += sz * (0.98 if k == 0 else 1.18) * (0.14 if k == 0 else 0.16)
    elif L.layout == "torn":
        L.units, L.box, L.size = place_rows(line, ct, kcover, base * 1.3, max_w, W / 2, H * 0.725, "center", warn=warn)
    else:
        L.units, L.box, L.size = place_rows(line, ct, kcover, base, max_w, W / 2, H * (1 - BOTTOM), "bottom", warn=warn)
    for u in L.units:
        u.setdefault("color", YELLOW if u["kw"] is not None else WHITE)
    allu = L.units + L.column
    L.t_in = min([u["t"] for u in allu] or [line["start"]])
    if L.motion == "flash":
        for u in allu + L.head:
            u["t"] = L.t_in
    # pop groups: each key word (or the whole line when there is none) pops as one piece
    L.groups = []
    if L.motion == "pop":
        if kws and L.layout != "darken":
            for k in range(len(kws)):
                g = [u for u in L.units if u["kw"] == k]
                if g:
                    L.groups.append(g)
        elif L.layout == "darken":
            L.groups = [[u] for u in L.column]
        else:
            for r in sorted({u["row"] for u in L.units}):
                L.groups.append([u for u in L.units if u["row"] == r])
        for g in L.groups:
            t = min(u["t"] for u in g)
            for u in g:
                u["t"] = t; u["grp"] = g
    if L.motion == "burst" and L.layout == "darken" and L.column:
        t = min(u["t"] for u in L.column)
        for u in L.column:
            u["t"] = t; u["grp"] = L.column
        L.land = t + BURST
    elif L.motion == "burst":
        phrase = sa or (kws[0] if kws else display(text))
        pi = text.find(phrase)
        role = line.get("standalone_font") or "brush"
        role = role if role in ("brush", "serif") else "brush"
        bs = max(base * BURST_SCALE, L.size * 1.25)
        sp = sprite(display(phrase), role, bs, YELLOW)
        if sp["adv"] > W * 0.9:
            bs *= W * 0.9 / sp["adv"]
        cy = (L.box[0] + L.box[1]) / 2
        L.burst = {"text": display(phrase), "role": role, "size": bs, "cx": W / 2, "cy": cy, "t": ct[pi] if pi >= 0 else L.t_in}
        L.land = L.burst["t"] + BURST
        # the rest of the line steps back in grey, packed into one row whose lower edge tucks behind the top of the
        # big phrase (photo 2); the phrase's own words are not repeated in grey (no double caption)
        span = set(range(pi, pi + len(phrase))) if pi >= 0 else set()
        rest = [dict(u) for u in L.units if not (set(u["idx"]) & span)]
        if rest:
            gs = L.size * (1.0 if L.layout == "subtitle" else 0.8)
            for u in rest:
                u["size"] = gs; u["adv"] = fonts.font("serif", gs).getlength(u["text"])
            tw = sum(u["adv"] for u in rest) + gs * 0.3 * sum(1 for a, b in zip(rest, rest[1:]) if b["idx"][0] - a["idx"][-1] > 1)
            x = W / 2 - tw / 2; gy = cy - bs * 0.36
            for k, u in enumerate(rest):
                if k and u["idx"][0] - rest[k - 1]["idx"][-1] > 1:
                    x += gs * 0.3
                u["x"], u["y"] = x, gy; x += u["adv"]
        L.burst["rest"] = rest
    else:
        L.land = None
    # shine target and time: after the target has settled
    L.shine = None
    if line.get("shine"):
        if L.burst:
            tgt, settle = "burst", L.land
        elif L.column:
            tgt, settle = "column", max(u["t"] for u in L.column) + (BURST if L.motion == "burst" else POP if L.motion == "pop" else FLASH)
        else:
            ks = [u for u in L.units if u["kw"] is not None] or L.units
            tgt = "keys" if any(u["kw"] is not None for u in L.units) else "line"
            settle = max(u["t"] for u in ks) + (POP if L.motion == "pop" else FLASH if L.motion == "flash" else 2 / FPS)
        L.shine = {"target": tgt, "t": settle + 0.12}
    return L


def timing(Ls, dur, warn):
    """When each line leaves: after its last word plus a short hold, never over the next line, bursts held >= 0.6 s."""
    for i, L in enumerate(Ls):
        nxt = Ls[i + 1].t_in if i + 1 < len(Ls) else dur
        want = L.src["end"] + 0.35
        if L.land:
            want = max(want, L.land + BURST_HOLD)
        if L.shine:
            want = max(want, L.shine["t"] + SHINE + 0.15)
        L.t_out = min(want, nxt - 0.01) if i + 1 < len(Ls) else min(want + 0.3, dur)
        L.fade = (nxt - L.t_out) >= 0.2
        if L.land and L.t_out < L.land + BURST_HOLD - 0.02:
            warn.append(f"line {L.id}: the burst is held only {max(0, L.t_out - L.land):.2f}s before the next line (guide: leave reading time)")
        if L.shine and L.shine["t"] + SHINE > L.t_out:
            L.shine["t"] = max(L.t_in, L.t_out - SHINE - 0.05)
            warn.append(f"line {L.id}: little time for the shine after the words settle; it runs at {L.shine['t']:.2f}s")


# ---- per frame --------------------------------------------------------------------------------------------------
def shine_params(L, t, units_box):
    if not L.shine:
        return None
    p = (t - L.shine["t"]) / SHINE
    if not 0 <= p <= 1:
        return None
    x0, x1, y0, y1 = units_box
    bw = max(10.0, (y1 - y0) * 0.22)
    uc = x0 - 2 * bw + (x1 - x0 + 4 * bw + (y1 - y0) * 0.36) * ease_io(p)
    return (uc, bw, (y0 + y1) / 2, 0.95)


def box_of(us):
    return (min(u["x"] for u in us), max(u["x"] + u["adv"] for u in us), min(u["y"] - u["size"] * 0.9 for u in us), max(u["y"] + u["size"] * 0.15 for u in us))


def draw_line(fr, L, t, W, H, stats):
    out_a = 1.0
    if L.fade and t > L.t_out - 0.1:
        out_a = max(0.0, (L.t_out - t) / 0.1)
    shad, fill, glow = [], [], []
    grey_k = 0.0
    if L.burst:
        grey_k = ease_io((t - L.burst["t"]) / 0.12)
    shine_us = None
    if L.shine:
        tg = L.shine["target"]
        shine_us = [u for u in L.units if u["kw"] is not None] if tg == "keys" else L.units if tg == "line" else L.column if tg == "column" else None
    sp_box = box_of(shine_us) if shine_us else None
    sh = shine_params(L, t, sp_box) if sp_box else None

    def add(u, s=1.0, a=1.0, cx=None, cy=None, color=None, alpha=1.0, shadow=1.0, shine=None, g=0.0, dx=0.0, dy=0.0):
        col = color or u["color"]
        sp = sprite(u["text"], u["role"], u["size"] * s, col, alpha * u.get("alpha", 1.0), shadow)
        if s != 1.0 and cx is not None:
            px = cx + (u["x"] - cx) * s; py = cy + (u["y"] - cy) * s
        else:
            px, py = u["x"], u["y"]
        px += dx; py += dy
        shad.append((sp["shad"], px + sp["ox"], py + sp["oy"], a * out_a))
        fill.append((sp["fill"], px + sp["ox"], py + sp["oy"], a * out_a, shine))
        if g > 0:
            glow.append((glow_of(sp), px + sp["ox"], py + sp["oy"], g * out_a))

    def unit_state(u):
        """(visible, scale, alpha, centre, glow) of a unit at time t, by the line's motion."""
        dt = t - u["t"]
        if dt < -1e-6:
            return None
        if L.motion == "flash":
            p = dt / FLASH; f = int(round(dt * FPS))
            g = {2: 0.55, 3: 1.0, 4: 0.45}.get(f, 0.0)
            return (1.0 + 0.06 * (1 - ease_out(p)) if p < 1 else 1.0, ease_out(p) if p < 1 else 1.0, None, g)
        if "grp" in u and L.motion in ("pop", "burst"):
            g = u["grp"]; dur = POP if L.motion == "pop" else BURST
            p = dt / dur
            if p < 1:
                if L.motion == "pop":
                    s = 0.85 + 0.23 * ease_out(p / 0.55) if p < 0.55 else 1.08 - 0.08 * ease_io((p - 0.55) / 0.45)
                    a = min(1.0, p / 0.45)
                else:
                    s = 1.35 - 0.38 * ease_out(p / 0.65) if p < 0.65 else 0.97 + 0.03 * ease_io((p - 0.65) / 0.35)
                    a = min(1.0, 0.34 + dt * FPS * 0.33)
                gx0, gx1 = min(v["x"] for v in g), max(v["x"] + v["adv"] for v in g)
                gy = sum(v["y"] - v["size"] * CJK_MID for v in g) / len(g)
                return (s, a, ((gx0 + gx1) / 2, gy), 0.0)
            return (1.0, 1.0, None, 0.0)
        return (1.0, min(1.0, dt * FPS / 2 + 0.5), None, 0.0)

    for u in L.head + L.units:
        st = unit_state(u)
        if st is None:
            continue
        s, a, c, g = st
        sx = sh if (shine_us is not None and u in shine_us) else None
        kw = dict(s=s, a=a, cx=c[0] if c else None, cy=c[1] if c else None, shine=sx, g=g)
        if grey_k > 0:                                  # the line gives way to the burst phrase
            if grey_k < 1:
                add(u, a=a * (1 - grey_k), **{k: v for k, v in kw.items() if k != "a"})
        else:
            add(u, **kw)
    if grey_k > 0:
        for u in L.burst["rest"]:
            if t >= u["t"]:
                add(u, a=grey_k, color=GREY, alpha=GREY_ALPHA, shadow=0.4)
    # vertical column (darken)
    for u in L.column:
        st = unit_state(u)
        if st is None:
            continue
        s, a, c, g = st
        dx = dy = 0.0
        if L.motion == "burst" and c is not None:
            f = int(round((t - u["t"]) * FPS)); k = u["size"] * 0.03
            dx, dy = {5: (k, -0.6 * k), 6: (-0.8 * k, 0.7 * k), 7: (0.4 * k, -0.3 * k)}.get(f, (0.0, 0.0))
        add(u, s=s, a=a, cx=c[0] if c else None, cy=c[1] if c else None, shine=sh if shine_us is L.column else None, g=g, dx=dx, dy=dy)
    # standalone burst phrase over the line
    bsh, bfill = [], []
    if L.burst and t >= L.burst["t"]:
        b = L.burst; dt = t - b["t"]; p = dt / BURST; f = int(round(dt * FPS))
        if p < 1:
            s = 1.35 - 0.38 * ease_out(p / 0.65) if p < 0.65 else 0.97 + 0.03 * ease_io((p - 0.65) / 0.35)
        else:
            s = 1.0
        a = min(1.0, 0.34 + dt * FPS * 0.33)
        k = b["size"] * 0.03
        dx, dy = {5: (k, -0.6 * k), 6: (-0.8 * k, 0.7 * k), 7: (0.4 * k, -0.3 * k)}.get(f, (0.0, 0.0))
        copies = [(s * 1.10, 0.28), (s * 1.05, 0.45), (s, 1.0)] if f <= 2 else [(s, 1.0)]       # zoom blur on impact
        bsp = sprite(b["text"], b["role"], b["size"], YELLOW)
        for sc, wgt in copies:
            sp = sprite(b["text"], b["role"], b["size"] * sc, YELLOW)
            px = b["cx"] - sp["adv"] / 2 + dx; py = b["cy"] + sp["size"] * CJK_MID + dy
            bsh.append((sp["shad"], px + sp["ox"], py + sp["oy"], a * wgt * out_a))
            shn = None
            if L.shine and L.shine["target"] == "burst" and sc == s:
                bx0 = b["cx"] - bsp["adv"] / 2; by = b["cy"] + bsp["size"] * CJK_MID
                shn = shine_params(L, t, (bx0, bx0 + bsp["adv"], by - bsp["size"] * 0.9, by + bsp["size"] * 0.15))
            bfill.append((sp["fill"], px + sp["ox"], py + sp["oy"], a * wgt * out_a, shn))
    items = [(arr, x, y, a, None) for arr, x, y, a in shad] + fill + [(arr, x, y, a, None) for arr, x, y, a in bsh] + bfill
    if any(it[4] is not None for it in items):       # a shine band moves every frame: draw directly
        for arr, x, y, a, shn in items:
            blit(fr, arr, x, y, a, shine=shn)
    elif items:                                      # same picture as last frame (most frames): reuse one composed layer
        sig = tuple((id(arr), int(round(x)), int(round(y)), round(a, 3)) for arr, x, y, a, _ in items)
        if getattr(L, "cache", (None,))[0] != sig:
            L.cache = (sig,) + compose(items, W, H)
        blit(fr, L.cache[1], L.cache[2], L.cache[3])
    for arr, x, y, a in glow:
        blit(fr, arr, x, y, a, add=True)


def compose(items, W, H):
    """Premultiplied 'over' of all sprites into one canvas: (canvas, x, y)."""
    x0 = max(0, min(int(round(x)) for _, x, _, _, _ in items)); y0 = max(0, min(int(round(y)) for _, _, y, _, _ in items))
    x1 = min(W, max(int(round(x)) + arr.shape[1] for arr, x, _, _, _ in items)); y1 = min(H, max(int(round(y)) + arr.shape[0] for arr, _, y, _, _ in items))
    cv = np.zeros((max(1, y1 - y0), max(1, x1 - x0), 4), np.float32)
    for arr, x, y, a, _ in items:
        x, y = int(round(x)), int(round(y)); h, w = arr.shape[:2]
        xa, ya, xb, yb = max(x0, x), max(y0, y), min(x1, x + w), min(y1, y + h)
        if xb <= xa or yb <= ya or a <= 0.002:
            continue
        sub = arr[ya - y:yb - y, xa - x:xb - x]
        reg = cv[ya - y0:yb - y0, xa - x0:xb - x0]
        reg *= 1 - sub[..., 3:4] * a
        reg += sub * a
    return cv, x0, y0


# ---- editable captions ------------------------------------------------------------------------------------------
KEY_ASS = "&H38C2FB&"          # #FBC238 in ASS (BGR) order


def ass_color(c, alpha=0):
    return f"&H{alpha:02X}{c[2]:02X}{c[1]:02X}{c[0]:02X}"


def ass_time(t):
    t = max(0.0, t); cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(path, Ls, W, H, base, fnt):
    serif, brush = fnt["serif"]["name"] or "Serif", fnt["brush"]["name"] or "Serif"
    sty = "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    st = lambda n, f, sz, c, al, mv, a=0: f"Style: {n},{f},{int(sz)},{ass_color(c, a)},{ass_color(c, a)},&H64000000,&H8C000000,-1,0,0,0,100,100,0,0,1,{max(2, int(sz * 0.035))},{max(2, int(sz * 0.04))},{al},{int(W * SIDE)},{int(W * SIDE)},{int(mv)},1"
    out = ["[Script Info]", "; Yellow Serif Kinetic captions (render.py). Key words #FBC238, motions as \\t transforms; shine and light leaks are",
           "; only in the rendered mp4. Backgrounds per line are noted in the Comment lines.", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
           "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", sty,
           st("YS-Main", serif, base, WHITE, 2, H * BOTTOM), st("YS-Center", serif, base * 1.55, WHITE, 5, 0),
           st("YS-Burst", brush, base * BURST_SCALE, YELLOW, 5, 0), st("YS-Grey", serif, base, GREY, 5, 0, 0x66), "",
           "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for L in Ls:
        t0 = L.t_in; ms = lambda t: int(round((t - t0) * 1000))
        out.append(f"Comment: 0,{ass_time(t0)},{ass_time(L.t_out)},YS-Main,,0,0,0,,layout={L.layout} motion={L.motion}"
                   + (f" shine@{L.shine['t']:.2f}s" if L.shine else "") + (" transition=leak" if L.src.get("transition") == "leak" else ""))
        rows = {}
        for u in L.units:
            a, b = ms(u["t"]), ms(u["t"]) + 66
            tag = ""
            if u["kw"] is not None and L.layout != "darken":
                tag += "\\c" + KEY_ASS
                if "grp" in u and L.motion == "pop":
                    tag += f"\\fscx92\\fscy92\\alpha&HFF&\\t({a},{a + 120},\\fscx117\\fscy117\\alpha&H00&)\\t({a + 120},{a + 220},\\fscx108\\fscy108)"
                else:
                    tag += f"\\fscx108\\fscy108\\alpha&HFF&\\t({a},{b},\\alpha&H00&)"
            else:
                tag += f"\\alpha&HFF&\\t({a},{b},\\alpha&H00&)"
            rows.setdefault(u["row"], []).append("{" + tag + "}" + u["text"] + "{\\r}")
        body = "\\N".join("".join(r) for _, r in sorted(rows.items()))
        if L.motion == "flash":
            body = "{\\fad(140,0)}" + body.replace("\\alpha&HFF&", "\\alpha&H00&")
        if L.layout == "subtitle" or (L.layout == "torn"):
            pos = "" if L.layout == "subtitle" else f"{{\\an5\\pos({W // 2},{int((L.box[0] + L.box[1]) / 2)})\\fs{int(L.size)}}}"
            out.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(L.t_out)},YS-Main,,0,0,0,,{pos}{body}")
        elif L.layout == "fullscreen":
            out.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(L.t_out)},YS-Center,,0,0,0,,{{\\an5\\pos({W // 2},{int((L.box[0] + L.box[1]) / 2)})}}{body}")
            for u in L.head:
                out.append(f"Dialogue: 1,{ass_time(t0)},{ass_time(L.t_out)},YS-Center,,0,0,0,,{{\\an5\\pos({W // 2},{int(u['y'] - u['size'] * CJK_MID)})\\fs{int(u['size'])}\\c{KEY_ASS if u['color'] == YELLOW else '&HFFFFFF&'}}}{u['text']}")
        else:  # darken
            if L.column:
                cy = int(sum(u["y"] - u["size"] * CJK_MID for u in L.column) / len(L.column))
                col = "\\N".join(u["text"] for u in L.column)
                ani = "\\fscx135\\fscy135\\t(0,280,\\fscx100\\fscy100)" if L.motion == "burst" else ""
                out.append(f"Dialogue: 1,{ass_time(L.column[0]['t'])},{ass_time(L.t_out)},YS-Center,,0,0,0,,{{\\an5\\pos({W // 2},{cy})\\fs{int(L.column[0]['size'])}\\c&H38C2FB&{ani}}}{col}")
            out.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(L.t_out)},YS-Grey,,0,0,0,,{{\\an5\\pos({W // 2},{int((L.box[0] + L.box[1]) / 2)})}}{body}")
        if L.burst:
            b = L.burst
            out.append(f"Dialogue: 2,{ass_time(b['t'])},{ass_time(L.t_out)},YS-Burst,,0,0,0,,{{\\an5\\pos({W // 2},{int(b['cy'])})\\fs{int(b['size'])}"
                       + (f"\\fn{serif}" if b["role"] == "serif" else "") + f"\\fscx135\\fscy135\\t(0,180,\\fscx97\\fscy97)\\t(180,280,\\fscx100\\fscy100)}}{b['text']}")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(out) + "\n")


def write_srt(path, Ls):
    def ts(t): ms = int(round(max(0, t) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    with open(path, "w", encoding="utf-8") as f:
        for i, L in enumerate(Ls):
            rows = {}
            for u in L.units:
                rows.setdefault(u["row"], []).append(u["text"])
            txt = "\n".join("".join(r) for _, r in sorted(rows.items()))
            if L.column:
                txt = "".join(u["text"] for u in L.column) + "\n" + txt
            f.write(f"{i + 1}\n{ts(L.t_in)} --> {ts(L.t_out)}\n{txt}\n\n")


# ---- main -------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop", help="how a wide clip becomes vertical")
    ap.add_argument("--font-size", type=float, default=BASE_PX, help="normal caption size in px at 1080 wide (guide: 74-96)")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    ap.add_argument("--no-captions", action="store_true", help="only reframe to the vertical size (a clean clip for the pixel cover)")
    a = ap.parse_args()
    t_start = time.time()
    W, H = (int(v) for v in a.size.lower().split("x"))
    S = W / 1080 if H >= W else H / 1080 * 0.9
    base = a.font_size * S
    plan = load(a.plan)
    err, warn = check(plan)
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    fnt = fonts.resolve()
    from common import probe
    info = probe(a.video); dur = info["duration"]
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    Ls = [build(ln, plan, W, H, base, warn) for ln in lines]
    timing(Ls, dur, warn)
    for L in Ls:                                    # nothing outside the side margins
        for u in L.units + L.column:
            if u["x"] < W * SIDE * 0.5 - 1 or u["x"] + u["adv"] > W * (1 - SIDE * 0.5) + 1:
                warn.append(f"line {L.id}: '{u['text']}' reaches into the side margin"); break
    grid = grid_bg(W, H) if any(L.layout in ("fullscreen", "torn") for L in Ls) else None
    torn = torn_frame(W, H) if any(L.layout == "torn" for L in Ls) else None
    # light leaks: transitions into lines marked "leak", and a short flare on each flash
    ovs = leaks.overlay_files()
    fx = []
    for k, L in enumerate(Ls):
        if L.src.get("transition") == "leak":
            fx.append({"t0": L.src["start"] - LEAK * 0.45, "dur": LEAK, "kind": "transition", "seed": 101 + k, "line": L.id})
        if L.motion == "flash":
            fx.append({"t0": L.t_in - 0.03, "dur": 0.45, "kind": "flash", "seed": 301 + k, "line": L.id})
    for k, e in enumerate(f for f in fx if f["kind"] == "transition" and ovs):
        e["overlay"] = ovs[k % len(ovs)]

    if a.frame == "crop":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    else:
        vf = f"split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"
    if a.no_captions:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        from common import run
        run(["-i", a.video, "-filter_complex" if a.frame == "blur" else "-vf", vf, "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf,
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", a.out])
        report(tool="render", ok=True, out=a.out, captions=False, seconds=round(dur, 2)); return
    acodec = ["-c:a", "copy"] if "Audio: aac" in subprocess.run([FFMPEG, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr else ["-c:a", "aac", "-b:a", "192k"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", a.video, "-filter_complex" if a.frame == "blur" else "-vf", vf,
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", a.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf,
                            "-pix_fmt", "yuv420p", *acodec, "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    n, cur, ov_cache = 0, 0, {}
    stats = {}
    fsz = W * H * 3
    qin, qout = queue.Queue(12), queue.Queue(12)

    def reader():                                    # decode ahead while the main thread composes
        while True:
            buf = dec.stdout.read(fsz)
            if len(buf) < fsz:
                qin.put(None); return
            qin.put(buf)

    def writer():                                    # encode behind
        while True:
            b = qout.get()
            if b is None:
                return
            enc.stdin.write(b)
    th_r, th_w = threading.Thread(target=reader, daemon=True), threading.Thread(target=writer, daemon=True)
    th_r.start(); th_w.start()
    while True:
        buf = qin.get()
        if buf is None:
            break
        t = n / FPS; n += 1
        fr = np.frombuffer(bytearray(buf), np.uint8).reshape(H, W, 3)
        while cur + 1 < len(Ls) and t >= Ls[cur + 1].t_in:
            cur += 1
        act = next((L for L in Ls[max(0, cur - 1):cur + 2] if L.t_in <= t < L.t_out), None)
        lay = (act or (Ls[cur] if Ls and t >= Ls[0].t_in else (Ls[0] if Ls else None)))
        layout = lay.layout if lay else "subtitle"
        if layout == "fullscreen":
            fr = grid.copy()
        elif layout == "darken":
            fr = (fr.astype(np.uint16) * 115 >> 8).astype(np.uint8)
        elif layout == "torn":
            (bx0, by0, bx1, by1), mi, rim, grain = torn
            bw, bh = bx1 - bx0, by1 - by0
            ch = min(H, int(W * bh / bw)); cy0 = max(0, min(H - ch, int(H * 0.42 - ch / 2)))
            pic = np.asarray(Image.fromarray(fr[cy0:cy0 + ch]).resize((bw, bh), Image.BILINEAR), np.float32)
            g = grid.copy(); reg = g[by0:by1, bx0:bx1].astype(np.float32)
            reg = reg * (1 - mi - rim) + pic * mi + np.array([236, 233, 226], np.float32) * grain * rim
            g[by0:by1, bx0:bx1] = np.clip(reg, 0, 255).astype(np.uint8)
            fr = g
        for e in fx:                                 # light leaks under the captions, so the words stay clear
            p = (t - e["t0"]) / e["dur"]
            if 0 <= p <= 1:
                if e.get("overlay"):
                    key = id(e)
                    if key not in ov_cache:
                        ovd = probe(e["overlay"])["duration"]
                        off = ((e["seed"] * 1.37) % max(0.01, ovd - e["dur"])) if ovd > e["dur"] else 0
                        ov_cache[key] = leaks.overlay_frames(e["overlay"], off, e["dur"], W, H, FFMPEG, FPS)
                    frs = ov_cache[key]
                    if frs:
                        env = min(1.0, p / 0.15, (1 - p) / 0.15)
                        leaks.screen(fr, frs[min(len(frs) - 1, int(p * len(frs)))], env)
                else:
                    leaks.screen(fr, leaks.leak(p, e["seed"], W, H, e["kind"]))
            elif p > 1 and id(e) in ov_cache:
                del ov_cache[id(e)]
        if act is not None:
            draw_line(fr, act, t, W, H, stats)
        qout.put(np.ascontiguousarray(fr).tobytes())
    qout.put(None); th_w.join()
    enc.stdin.close(); enc.wait(); dec.wait()

    base_out = os.path.splitext(a.out)[0]
    write_ass(base_out + ".ass", Ls, W, H, base, fnt)
    write_srt(base_out + ".srt", Ls)
    plan_copy = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
    if os.path.abspath(a.plan) != plan_copy:
        shutil.copyfile(a.plan, plan_copy)
    events = []
    for L in Ls:
        mid = (L.t_in + L.t_out) / 2
        if L.layout != "subtitle":
            events.append({"t": mid, "kind": f"layout {L.layout}", "line": L.id})
        if L.motion == "type":
            last = max(u["t"] for u in L.units + L.column) if L.units + L.column else L.t_in
            events.append({"t": (L.t_in + last) / 2, "kind": "typing", "line": L.id})
        for g in L.groups:
            events.append({"t": g[0]["t"] + POP * 0.5, "kind": "pop (108%)", "line": L.id})
            events.append({"t": g[0]["t"] + POP + 0.05, "kind": "pop (settled)", "line": L.id})
        if L.land:
            events.append({"t": L.land - BURST * 0.75, "kind": "burst (impact)", "line": L.id})
            events.append({"t": L.land + 0.15, "kind": "burst (landed)", "line": L.id})
        if L.shine:
            events.append({"t": L.shine["t"] + SHINE * 0.45, "kind": "shine (band)", "line": L.id})
            events.append({"t": L.shine["t"] + SHINE + 0.08, "kind": "shine (after)", "line": L.id})
        if L.motion == "flash":
            events.append({"t": L.t_in + 3 / FPS, "kind": "flash (edge)", "line": L.id})
    for e in fx:
        if e["kind"] == "transition":
            events.append({"t": e["t0"] + e["dur"] * 0.42, "kind": "light leak", "line": e["line"]})
    events = [e for e in events if 0 <= e["t"] < dur]
    events.sort(key=lambda e: e["t"])
    counts = {m: sum(1 for L in Ls if L.motion == m) for m in ("type", "pop", "burst", "flash")}
    counts["shine"] = sum(1 for L in Ls if L.shine); counts["leak"] = sum(1 for e in fx if e["kind"] == "transition")
    layouts = {k: sum(1 for L in Ls if L.layout == k) for k in ("subtitle", "fullscreen", "darken", "torn")}
    side = {"video": os.path.abspath(a.out), "size": [W, H], "fps": FPS, "events": events, "fonts": fonts.used(), "warnings": warn,
            "lines": [{"id": L.id, "t_in": round(L.t_in, 3), "t_out": round(L.t_out, 3), "layout": L.layout, "motion": L.motion} for L in Ls]}
    save(base_out + ".ys.json", side)
    report(tool="render", ok=True, out=a.out, ass=base_out + ".ass", srt=base_out + ".srt", plan=plan_copy, frames=n,
           seconds=round(n / FPS, 2), render_seconds=round(time.time() - t_start, 1), fonts=fonts.used(), motions=counts, layouts=layouts,
           overlay=os.path.basename(ovs[0]) if ovs else "procedural light leaks", warnings=warn)


if __name__ == "__main__":
    main()
