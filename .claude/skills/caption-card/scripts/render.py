"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).

usage: python render.py <video> <plan.json> <out.mp4> [--frame crop|blur] [--crop X:Y:W:H] [--focus 0.5]
                        [--from SECONDS] [--to SECONDS] [--hr FOOTAGE.mp4 [--hr-map cutmap.json]]
                        [--no-punch] [--phone] [--no-text] [--preset medium] [--classic]

--from / --to   a preview of part of the clip. Everything (big type, cards, camera pieces, cuts, pull-back) is planned on
                the whole clip first, so the preview's frames are the full render's frames. The .srt, .pk.json and
                .sfx-events.json of a preview use the preview file's own time (it starts at 0).
--hr            the full-resolution camera footage of the same edit (same length, same cuts), e.g. cut_hr.mp4. The
                picture comes from it, the sound from <video>. Without --hr-map it must have the same framing as
                <video> (just bigger): it is decoded with up to 1.35x headroom, so pushes and punch-ins don't enlarge.
--hr-map        with --hr when the footage is the whole camera frame: {"ranges": [{"cut": [t0, t1], "frame": "wide"}],
                "wide": [w, h, x, y], "tight": [w, h, x, y], "anchor": [x, y]} in footage pixels (the edit's cutmap.json).
                Each shot is cut out of the footage at its own box and the camera zooms inside it around the face;
                the cuts come from the map. "anchor" (optional) is the face in footage pixels; without it, plan
                camera "face" is read on the first shot's box.
                Plan "hr" and "hr_map" (paths, relative to the plan's folder) do the same without the flags: when
                the footage is there every render and preview uses it (a missing hr is a warning, a missing hr_map
                with hr is an error, since the framing would be wrong).
Prints max_upscale (output pixels per source pixel at the strongest zoom; above 1.0 the picture is enlarged).

v2 (the default, owner-approved on Pong+Gospel 11/14, 2026-10-30):
  cards     every line is a caption card (cyan box, blue slanted words, 2-6 characters or 1-3 English words a card).
            Each line animates in with its own entrance ("anim": rise, slide, slam, stagger, wipe, or cut = a hard cut);
            without "anim" the lines take turns so neighbours never match. Follow-on cards of a line use a quicker
            version; the line's last card swells and blurs out. "key": the stressed word(s) of the line: a yellow bar
            wipes in under it at the moment it is spoken, the word turns deep blue and pops 1.22x.
  big type  hook, number, writeon, punch (as in v1) and breathe: 2-3 rows that fade, rise and unblur slowly, the group
            drifts and dissolves up (the quiet, heavy line). Layered type: heavy face, top-light gradient, dark soft
            shadow, outer glow, the picture blurred and dimmed underneath.
  camera    on a frame decoded with up to 1.35x headroom (or cut from --hr footage): a slow push-in or a sideways
            drift on every piece (pieces start at the cuts in the clip, each big-type entry except a punch, and each
            transition), handheld sway on lines with "sway": true, a 1.25x punch-in on punch lines (it eases back out
            over 8 frames, or ends on the cut / flash that follows it), "punch_in": 1.15 on any line, a slow
            pull-back on the last line. Always zoomed around plan "camera": {"face": [x, y]}. Cuts: "auto" finds them
            from frame differences (wide / tight re-framings and jump cuts too), or give the list of times.
  picture   plan "grade": [[t, g], ...] (g -1 cool and dim ... 0 neutral ... +1 warm) with a vignette; a warm light
            leak after every "flash"; "leak": true on a line adds a soft leak at its start; plan "light" adds a warm
            bloom and floating light particles (kept off the face) to the end: true (from where the grade turns
            warm), a time in seconds, or {"from": t, "to": t, "bloom": 0.16, "particles": true}.
  accents   per line "accent": rings (two light rings open as it lands), orbs (two soft lights drift together),
            halo (a soft gold glow behind it).
--classic (or plan "motion": "classic") renders the v1 look: hard-cut cards, no camera, grade, light or accents, and
a 1.35x picture punch-in on punch lines.
Line "transition": "flash" (a 4-frame white: one before the cut, the peak on it, two after) or "blurcut" (the new shot starts blurred and sharpens in 3 frames).
Writes <out>.mp4, <out>.srt, <out>.pk.json (events for the poster-kinetic preview.py), <out>.sfx-events.json (for the sfx
skill), a copy of plan.json; --phone also writes <out>_phone.mp4 under 28 MiB. Prints one JSON line.
"""
import argparse, math, os, queue, re, shutil, subprocess, sys, threading, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cc  # noqa: E402
from cc import (CARD, DEFAULT_COLOR, F1, FFMPEG, FPS, SAFE, ease_io, ease_out, keys, load,  # noqa: E402
                put, report, rgb, save, styled_line, sub_time, char_times, display, is_cjk, fit_size)

W, H = 1080, 1920
BAR = "#FFE45C"; KEY1, KEY2 = "#0A1A9C", "#06127A"          # key word: yellow bar, deep blue word
AUTO_ANIMS = ["rise", "slide", "slam", "stagger", "slide", "wipe"]   # neighbours never match, also across the wrap


# ---- caption cards ----------------------------------------------------------------------------------------------------
def chunk_words(ln):
    """The line -> card chunks: 2-6 CJK characters or 1-3 Latin words, never across a pause > 0.35 s or a sentence end.
    The card text is always the line's own "text" (the corrected wording); the speech-to-text "words" only give the
    timing and where a spoken word starts and ends, so a word is never split across two cards. Each chunk keeps its
    character span in the line text ("span": (a, b)) so key words map onto it exactly."""
    text = ln["text"]
    ct = char_times(ln)
    words = [w for w in ln.get("words") or [] if (w.get("t") or "").strip()]
    toks = []                                                   # display units: one CJK character or one Latin word
    for u in cc.units(text):
        if u["gap"]:
            if toks and u["brk"]:
                toks[-1]["brk"] = True                          # a comma or sentence end follows this token
            continue
        a = u["idx"][0]
        toks.append({"a": a, "b": u["idx"][-1] + 1, "t": ct[a], "text": u["text"], "brk": False})
    if not toks:
        return []
    for k, tk in enumerate(toks):                               # which spoken word each token belongs to
        wi = None
        for j, w in enumerate(words):
            if w["start"] <= tk["t"] + 1e-6:
                wi = j
        tk["w"] = ("tok", k) if wi is None else ("word", wi)
    groups = []
    for tk in toks:
        if groups and groups[-1]["w"] == tk["w"]:
            g = groups[-1]; g["b"] = tk["b"]; g["toks"].append(tk); g["brk"] = tk["brk"]
        else:
            groups.append({"w": tk["w"], "a": tk["a"], "b": tk["b"], "start": tk["t"], "toks": [tk], "brk": tk["brk"]})
    for k, g in enumerate(groups):
        if g["w"][0] == "word":
            g["end"] = max(g["start"], words[g["w"][1]]["end"])
        else:
            g["end"] = groups[k + 1]["start"] if k + 1 < len(groups) else max(g["start"], ln["end"])
        g["cjk"] = any(is_cjk(c) for t_ in g["toks"] for c in t_["text"])
        g["size"] = sum(1.0 if (is_cjk(t_["text"][0]) or len(t_["text"]) == 1) else 1.0 if len(t_["text"]) < 9 else 1.6 for t_ in g["toks"])
    out, cur, n = [], [], 0
    for g in groups:
        limit = 6 if g["cjk"] else 3
        gap = cur and (g["start"] - cur[-1]["end"] > 0.35)
        if cur and (n + g["size"] > limit or gap):
            out.append(cur); cur, n = [], 0
        cur.append(g); n += g["size"]
        if g["brk"] and n >= (2 if g["cjk"] else 1):
            out.append(cur); cur, n = [], 0
    if cur:
        if out and len(cur) == 1 and len(cur[0]["toks"]) == 1 and is_cjk(cur[0]["toks"][0]["text"][0]) \
                and len(display(text[out[-1][0]["a"]:out[-1][-1]["b"]])) < 6:
            out[-1] += cur                                      # no lone single character card
        else:
            out.append(cur)
    return [{"text": display(text[ch[0]["a"]:ch[-1]["b"]]), "t": ch[0]["start"], "end": ch[-1]["end"],
             "span": (ch[0]["a"], ch[-1]["b"])} for ch in out]


def display_map(text, a, b):
    """{index in text: index in display(text[a:b])} for every character that shows on the card."""
    m, pos = {}, 0
    for u in cc.units(text[a:b]):
        if not u["gap"]:
            for k, i in enumerate(u["idx"]):
                m[a + i] = pos + k
        pos += len(u["text"])
    return m


class CardRenderer:
    """Caption cards with their entrance, key-word bar and swell-before-exit. A settled card is cached as one sprite."""

    def __init__(self, colors, y):
        self.box, self.c1, self.c2 = colors.get("box", CARD["box"]), colors.get("text", CARD["text"]), colors.get("text2", CARD["text2"])
        self.y = y; self.cache = {}

    def build(self, text):
        if text in self.cache:
            return self.cache[text]
        size, gs, box = fit_size(text, "card", 150, 900, None, 0.0, 70)
        tw, th = box[2] - box[0], box[3] - box[1]
        bh = int(size * 0.75); padx = int(size * 0.27); bw = int(tw + 2 * padx)
        cw, ch = bw + 160, int(max(th, bh) + 160)
        idx = [i for i, c in enumerate(text) if c.strip()]
        glyphs = []
        for k, g in enumerate(gs):
            spr, _ = cc.layered(g["mask"], self.c1, self.c2, box[1], box[3], g["y"], None, ("#0B1446", 5, 3, 0.35))
            kspr, _ = cc.layered(g["mask"], KEY1, KEY2, box[1], box[3], g["y"], None, ("#6B5200", 5, 3, 0.25))
            glyphs.append({"img": spr, "kimg": kspr, "cx": g["cx"], "cy": g["cy"], "ci": idx[k] if k < len(idx) else k,
                           "l": g["pen"] - (box[0] + box[2]) / 2, "r": g["pen"] + g["adv"] - (box[0] + box[2]) / 2})
        d = {"size": size, "glyphs": glyphs, "bw": bw, "bh": bh, "cw": cw, "ch": ch, "cx": cw / 2, "cy": ch / 2, "settled": {}}
        self.cache[text] = d
        return d

    def layer(self, d, keyset, box_sx, anchor_l, char_fn, reveal=None, streak=0.0):
        """keyset: [(a, b, bar progress 0..1, frames since the key was spoken)], one entry per key word on screen."""
        img = Image.new("RGBA", (d["cw"], d["ch"]), (0, 0, 0, 0)); dr = ImageDraw.Draw(img)
        cx, cy, bw, bh = d["cx"], d["cy"], d["bw"], d["bh"]
        if box_sx > 0.01:
            if anchor_l:
                x0 = cx - bw / 2; x1 = x0 + bw * box_sx
            else:
                x0 = cx - bw / 2 * box_sx; x1 = cx + bw / 2 * box_sx
            dr.rectangle((x0, cy - bh / 2, x1, cy + bh / 2), fill=rgb(self.box) + (255,))
            if streak > 0.02 and anchor_l:                     # wipe: a light streak rides the box's leading edge
                s = Image.new("RGBA", (60, int(bh * 1.6)), (255, 255, 255, 0)); sd = ImageDraw.Draw(s)
                sd.rectangle((22, 0, 38, s.height), fill=(255, 255, 255, int(230 * streak)))
                s = s.filter(ImageFilter.GaussianBlur(7)); img.alpha_composite(s, (int(x1 - 30), int(cy - s.height / 2)))
        for (a, b, bp, _) in keyset:                            # key bars under the stressed words, each at its own pace
            ks = [g for g in d["glyphs"] if a <= g["ci"] < b]
            if not ks or bp <= 0.01:
                continue
            l = min(g["l"] for g in ks) - d["size"] * 0.06; r = max(g["r"] for g in ks) + d["size"] * 0.02
            r = l + (r - l) * min(1, bp)
            dr.rectangle((cx + l, cy - bh * 0.56, cx + r, cy + bh * 0.56), fill=rgb(BAR) + (255,))
        for i, g in enumerate(d["glyphs"]):
            dy, s, a = char_fn(i, len(d["glyphs"]), g)
            if a <= 0.01:
                continue
            if reveal is not None and anchor_l and (cx - bw / 2 + bw * reveal) < cx + g["cx"] - d["size"] * 0.2:
                continue
            k = next((k for k in keyset if k[0] <= g["ci"] < k[1]), None)
            src = g["kimg"] if (k and k[2] >= 0.5) else g["img"]
            pop = keys(k[3], [0, 2, 5], [1.0, 1.22, 1.0]) if k else 1.0
            put(img, src, cx + g["cx"], cy + g["cy"] + dy, s * pop, alpha=a)
        return img

    def draw(self, fr, c, t):
        """c: card chunk (text, t0, t1, anim, dir, first, last, exit, keys [(a, b, t_key)])"""
        d = self.build(c["text"])
        sp = 1.0 if c["first"] else 1.7                         # follow-on chunks move faster
        fe = (t - c["t0"]) * FPS * sp
        anim = c["anim"]
        gx = gy = 0.0; gs = 1.0; ga = 1.0; gbl = 0.0; gmb = 0.0; gbr = 1.0
        box_sx, anchor_l, reveal, streak = 1.0, False, None, 0.0
        char_fn = lambda i, n, g: (0.0, 1.0, 1.0)
        settle_f = 8
        if anim == "cut":
            settle_f = 0
        elif anim == "rise":
            gy = keys(fe, [0, 4, 6], [70, -6, 0]); ga = min(1, 0.15 + fe / 3); gbl = keys(fe, [0, 4], [10, 0])
            box_sx = keys(fe, [0, 4], [0.85, 1.0])
        elif anim == "slide":
            dd = c["dir"]; gx = keys(fe, [0, 4, 7], [-260 * dd, 14 * dd, 0]); gmb = keys(fe, [0, 4], [60, 0]); ga = min(1, 0.3 + fe / 2)
        elif anim == "slam":
            gs = keys(fe, [0, 3, 5, 7], [1.55, 0.95, 1.02, 1.0]); gbl = keys(fe, [0, 3], [9, 0]); ga = min(1, 0.2 + fe / 2)
        elif anim == "stagger":
            n = len(d["glyphs"]); step = 1.5 if n <= 4 else 1.0
            box_sx = keys(fe, [0, 4, 6], [0.0, 1.04, 1.0])

            def char_fn(i, n, g, fe=fe, step=step):
                fi = fe - 2 - i * step
                if fi < 0:
                    return 0.0, 1.0, 0.0
                return keys(fi, [0, 3, 5], [-46, 5, 0]), keys(fi, [0, 3, 5], [0.6, 1.12, 1.0]), min(1, fi / 2)
            settle_f = 2 + n * step + 5
        elif anim == "wipe":
            box_sx = ease_out(min(1, fe / 5)); anchor_l = True; reveal = box_sx; streak = 1 - min(1, fe / 7)

            def char_fn(i, n, g, fe=fe, bw=d["bw"]):
                fi = fe - 5 * (g["cx"] + bw / 2) / bw
                if fi < 0:
                    return 0.0, 1.0, 0.0
                return 0.0, keys(fi, [0, 2, 4], [0.7, 1.1, 1.0]), min(1, fi / 1.5 + 0.2)
            settle_f = 10
        keyset = []                                             # key bars wipe in when spoken, never before the card lands
        for (a, b, tk) in c["keys"]:
            tk = max(tk, c["t0"] + (settle_f / sp) * F1 * 0.7)
            kp = (t - tk) * FPS
            if kp >= 0:
                keyset.append((a, b, keys(kp, [0, 3], [0, 1]), kp))
        popping = any(k[3] < 6 for k in keyset)
        ex = (c["t1"] - t) * FPS                                # swell before exit on a line's last card
        swell = c["last"] and c["exit"] and ex < 4
        if swell:
            e = 4 - ex
            gs *= keys(e, [0, 1.5, 4], [1.0, 1.05, 0.9]); gbr = keys(e, [0, 1.5, 4], [1.0, 1.18, 1.0])
            ga *= keys(e, [0, 1.5, 4], [1.0, 1.0, 0.0]); gbl = max(gbl, keys(e, [0, 1.5, 4], [0, 0, 8]))
        if not ((fe < settle_f + 1) or popping or swell):
            kk = tuple((a, b) for a, b, _, _ in keyset)
            img = d["settled"].get(kk)
            if img is None:
                img = d["settled"][kk] = self.layer(d, [(a, b, 1.0, 99) for a, b in kk], 1.0, False, char_fn)
            cc._paste(fr, img, W / 2, self.y)
            return
        img = self.layer(d, keyset, box_sx, anchor_l, char_fn, reveal, streak)
        put(fr, img, W / 2 + gx, self.y + gy, gs, alpha=ga, blur=gbl, mblur=gmb, bright=gbr)


def card_timeline(lines, bigs, dur, classic, warn=None):
    """Every card chunk with its time, entrance and key-word bars. Cards wait while big type is up. A key word that
    spans two cards gets a bar on each part; a key that can't show (its card is cut away for big type) is a warning."""
    warn = [] if warn is None else warn
    tl, sdir, auto, prev = [], 1, 0, None
    for i, ln in enumerate(lines):
        if (ln.get("kind") or "card") != "card":
            continue
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else dur
        ch = chunk_words(ln)
        ct = char_times(ln)
        text = ln["text"]
        if classic:
            anim = "cut"
        elif ln.get("anim"):
            anim = ln["anim"]
        else:
            # never the same entrance as the card line before, nor as an explicit "anim" on the card line after
            nxt_ln = next((l for l in lines[i + 1:] if (l.get("kind") or "card") == "card"), None)
            avoid = {prev, (nxt_ln or {}).get("anim")}
            anim = AUTO_ANIMS[auto % len(AUTO_ANIMS)]; auto += 1
            for _ in range(len(AUTO_ANIMS)):
                if anim not in avoid:
                    break
                anim = AUTO_ANIMS[auto % len(AUTO_ANIMS)]; auto += 1
        prev = anim
        if anim == "slide":
            sdir = -sdir                                        # slides alternate left / right
        placed = {}
        for k, c in enumerate(ch):
            # a card ends one frame before the next one starts (next t0 = its t - F1), so two cards never share a frame
            end = ch[k + 1]["t"] - F1 if k + 1 < len(ch) else min(ln["end"] + 0.3, nxt - F1)
            a, b = c["span"]
            dm = display_map(text, a, b)
            ks = []
            for key in ([] if classic else cc.line_keys(ln)):
                kp = text.find(key)
                if kp < 0:
                    continue
                hit = [i_ for i_ in range(max(kp, a), min(kp + len(key), b)) if i_ in dm]
                if not hit:
                    continue
                tk = ct[hit[0]] if ct[hit[0]] is not None else c["t"]
                ks.append((dm[hit[0]], dm[hit[-1]] + 1, tk - F1))
                placed.setdefault(key, []).append(len(tl))
            tl.append({"t0": max(c["t"] - F1, 0), "t1": end, "text": c["text"], "anim": anim, "dir": sdir, "first": k == 0,
                       "last": k == len(ch) - 1, "keys": ks, "line": ln.get("id"), "exit": not classic})
        for key in ([] if classic else cc.line_keys(ln)):
            if key in text and key not in placed:
                warn.append(f"line {ln.get('id')}: key '{key}' is not on any card (nothing of it shows on screen)")
    for b in bigs:
        for c in tl:
            if c["t0"] < b.t_out + 6 * F1 and c["t1"] > b.t_in:
                if c["t0"] >= b.t_in:
                    c["t0"] = b.t_out + 6 * F1
                else:
                    c["t1"] = min(c["t1"], b.t_in); c["exit"] = False    # cut away for big type, no swell
    out = []
    for c in tl:
        alive = c["t1"] - c["t0"] > 2 * F1
        for (ka, kb, tk) in c["keys"]:
            if not alive or max(tk, c["t0"]) >= c["t1"] - 2 * F1:
                warn.append(f"line {c['line']}: key '{c['text'][ka:kb]}' never shows: its card '{c['text']}' is "
                            f"{'cut away' if not alive else 'gone before the word is spoken'} (big type at that moment)")
        if alive:
            out.append(c)
    return out


# ---- big moments -----------------------------------------------------------------------------------------------------------
OUT_FRAMES = {"hook": 3, "number": 5, "writeon": 5, "punch": 1, "breathe": 8}


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

    def centre_y(self):
        if hasattr(self, "cy"):
            return self.cy
        return sum(r["cy"] for r in self.rows) / len(self.rows)

    def landed(self):
        """When the type has landed (for accents)."""
        if self.kind == "punch":
            return self.t_in + (2 * (max(self.unit_of) if self.unit_of else 0) + 2) * F1
        return self.settle

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

    # breathe: rows fade, rise and unblur slowly character by character; the group drifts; dissolves up
    def build_breathe(self, warn):
        rows = self.ln["rows"]; key = self.ln.get("key_row")
        key = len(rows) - 1 if key is None else int(key)
        built = []
        for i, r in enumerate(rows):
            txt = display(r); s, _, _ = fit_size(txt, "hook", 205 if i == key else 128, 900, None, 0.0, 60)
            gl, ink = styled_line(txt, "hook", s, self.color if i == key else "white", glow=(i == key), shadow=("#0A0F1A", 18, 8, 0.7))
            built.append((gl, ink, i == key))
        gap = 18; total = sum(ink[1] for _, ink, _ in built) + gap * (len(built) - 1)
        y = (self.yf or 0.5) * H - total / 2
        self.rows = []
        for i, (gl, ink, isk) in enumerate(built):
            cy = y + ink[1] / 2; y += ink[1] + gap
            self.rows.append({"glyphs": gl, "cy": cy, "t": self.t_of(rows[i]), "key": isk})
        self.step = 2.5
        self.t_in = self.rows[0]["t"]
        self.settle = max(r["t"] + (len(r["glyphs"]) - 1) * self.step * F1 + 8 * F1 for r in self.rows)
        self.events.append({"t": self.t_in, "kind": "breathe in", "sfx": "chime_soft"})

    def draw_breathe(self, fr, t, out_p):
        drift = 1.0 + 0.012 * (t - self.t_in)                  # the group slowly grows
        for r in self.rows:
            for i, g in enumerate(r["glyphs"]):
                fi = (t - r["t"]) * FPS - i * self.step
                if fi < 0:
                    continue
                p = ease_out(min(1, fi / 8))
                oe = max(0.0, min(1.0, out_p - i * 0.05))
                put(fr, g["img"], W / 2 + g["cx"] * drift, r["cy"] + g["cy"] * drift + 26 * (1 - p) - 30 * oe, drift * (1.06 - 0.06 * p),
                    alpha=(0.1 + 0.9 * p) * (1 - oe), blur=max(12 * (1 - p), 14 * oe))

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
        self.unit_of, u, prev_cjk = [], -1, None
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
        self.events.append({"t": self.t_in - 3 * F1, "kind": "punch-in", "sfx": "whoosh_fast"})
        self.events.append({"t": self.t_in + 2 * (nunits - 1) * F1 + 2 * F1, "kind": "punch (last word lands)", "sfx": "impact"})

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
        of = OUT_FRAMES[self.kind]
        if t < self.t_in - 1e-6 or t > self.t_out + (of + 2) * F1:
            return
        out_p = 0.0 if t <= self.t_out else min(1.0, (t - self.t_out) * FPS / of)
        if out_p >= 1:
            return
        getattr(self, "draw_" + self.kind)(fr, t, out_p)


# ---- camera (v2) -----------------------------------------------------------------------------------------------------------
def detect_cuts(video, crop=None, ratio=2.0, floor=2.0):
    """Times of the hard cuts in the clip, or None when the clip can't be read. Frame differences on a tiny grey copy:
    a cut is one frame that differs from the one before at least `ratio` times more than its neighbours (+-2 frames)
    differ, and by at least `floor` grey levels; a jump in the picture of 12+ levels is always a cut. This finds wide /
    tight re-framings and jump cuts of the same camera, which the ffmpeg scene score misses (1114: 24 of 24, no false
    hits on an 80 s uncut take). Always run on the whole clip, so a preview gets the same cuts as the full render."""
    pre = ""
    if crop:
        x, y, w, h = crop.split(":"); pre = f"crop={w}:{h}:{x}:{y},"
    gw, gh = 72, 128
    r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video, "-an", "-vf", f"{pre}scale={gw}:{gh},fps={FPS},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    n = len(r.stdout) // (gw * gh)
    if r.returncode != 0 or n < 3:
        return None
    f = np.frombuffer(r.stdout[:n * gw * gh], np.uint8).reshape(n, gh, gw)
    d = np.zeros(n, np.float32)
    for s in range(1, n, 512):
        e = min(n, s + 512)
        d[s:e] = np.abs(f[s:e].astype(np.int16) - f[s - 1:e - 1].astype(np.int16)).mean(axis=(1, 2))
    hits = []
    for i in range(1, n):
        nb = [d[j] for j in (i - 2, i - 1, i + 1, i + 2) if 0 < j < n]
        ref = max(nb) if nb else 0.0
        if d[i] >= 12 or (d[i] >= floor and d[i] >= ratio * max(ref, 0.5)):
            if not hits or i - hits[-1] > 9:
                hits.append(i)
    return [round(i / FPS, 3) for i in hits]


def load_map(path, hr_size):
    """The framing map for full-resolution footage: {"ranges": [{"cut": [t0, t1], "frame": "wide"}, ...],
    "wide": [w, h, x, y], "tight": [...], "anchor": [x, y] (optional, the face in footage pixels)}. Boxes are in the
    footage's pixels. Returns (ranges [(t0, t1, box)], cut times, anchor or None)."""
    m = load(path)
    rs = []
    for r in m.get("ranges") or []:
        box = r.get("box") or m.get(r.get("frame"))
        if not box or len(box) != 4:
            raise SystemExit(f"--hr-map: range {r} has no box (give \"frame\": a name with [w, h, x, y], or \"box\")")
        bw, bh, bx, by = (float(v) for v in box)
        if bx < 0 or by < 0 or bx + bw > hr_size[0] + 0.5 or by + bh > hr_size[1] + 0.5:
            raise SystemExit(f"--hr-map: box {box} is outside the {hr_size[0]}x{hr_size[1]} footage")
        snap = lambda x: round(float(x) * FPS) / FPS            # the frame the new shot shows on; the camera resets on it too
        rs.append((snap(r["cut"][0]), snap(r["cut"][1]), (bw, bh, bx, by)))
    if not rs:
        raise SystemExit("--hr-map: no ranges")
    rs.sort(key=lambda r: r[0])
    return rs, [r[0] for r in rs[1:]], m.get("anchor")


class Camera:
    """Push / drift per piece, sway windows, punch-ins and a pull-back, zoomed around the face. Pieces start at the clip's
    cuts, each big-type entry (the picture is blurred there, so the move restarts unseen) and each transition."""
    PATTERN = [("push", 0), ("push", 0), ("drift", 1), ("push", 0), ("drift", -1)]

    PUNCH_OUT = 8                                                # frames to ease back out of a punch-in (no hard drop)

    def __init__(self, cfg, lines, bigs, trans, dur, cuts, no_punch):
        self.face = cfg.get("face") or [0.5, 0.3]
        snap = lambda x: round(x * FPS) / FPS                    # on the frame grid: the decoder's fps filter shows the new
        cuts = [snap(c) for c in cuts]                           # shot from that frame, so the zoom resets on the same one
        trans = [(snap(tc), k) for tc, k in trans]
        hidden = sorted(list(cuts) + [tc for tc, _ in trans])  # moments that hide a jump in the zoom (a cut, a flash)
        self.punch = []
        for b in ([] if no_punch else [b for b in bigs if b.kind == "punch"]):
            p0, p1 = b.t_in - 3 * F1, b.t_out
            # a punch ends at the first cut or transition inside it (or just after it) with a snap the cut hides,
            # otherwise it eases back out over PUNCH_OUT frames
            hc = next((h for h in hidden if p0 + 0.1 <= h <= p1 + 0.1), None)
            self.punch.append({"p0": p0, "p1": hc if hc is not None else p1, "s": float(cfg.get("punch_scale", 1.25)),
                               "snap": hc is not None})
        # a new push / drift starts at each cut, transition and big-type entry (the picture is blurred there); never
        # during a punch line: its picture is only half blurred, so a restart there shows as a zoom jump
        resets = [0.0] + list(cuts) + [snap(b.t_in + 2 * F1) for b in bigs if b.kind != "punch"] + [tc for tc, _ in trans]
        rs = []
        for r in sorted(resets):
            if 0 <= r < dur - 0.3 and (not rs or r - rs[-1] >= 0.8):
                rs.append(r)
        self.pieces = []
        for k, a0 in enumerate(rs):
            a1 = rs[k + 1] if k + 1 < len(rs) else dur
            mv, d = self.PATTERN[k % len(self.PATTERN)]
            if a1 - a0 < 1.2:
                mv, d = "push", 0                               # short pieces only push
            to = 1.0 + min(0.07, 0.025 + 0.008 * (a1 - a0))
            self.pieces.append({"start": a0, "end": a1, "move": mv, "dir": d, "from": 1.0 if mv == "push" else 1.04,
                                "to": to if mv == "push" else 1.04})
        self.sway = [(ln["start"] - 0.1, ln["end"] + 0.2) for ln in lines if ln.get("sway")] + [(float(w[0]), float(w[1])) for w in cfg.get("sway") or []]
        self.pins = []
        for ln in lines:
            if ln.get("punch_in"):
                k = self.piece_index(ln["start"] + 0.1)
                self.pins.append((ln["start"], float(ln["punch_in"]), k, ln.get("id")))
        pb = cfg.get("pull_back", "auto")
        self.pb = None
        if pb == "auto" and lines and dur - lines[-1]["start"] >= 1.5:
            self.pb = {"start": lines[-1]["start"], "end": dur, "to": 1.0}
        elif isinstance(pb, dict):
            self.pb = {"start": float(pb["start"]), "end": float(pb.get("end", dur)), "to": float(pb.get("to", 1.0))}
        if self.pb:
            # the pull-back scales whatever the zoom is (a push, a punch-in on the last line) so that it lands on "to"
            # at the end: nothing is overwritten, so a punch_in on the last line still shows before it eases back
            self.pb["s_end"] = self.base(self.pb["end"] - 1e-3)[0]
        self.smax = 1.0

    def piece_index(self, t):
        for k, p in enumerate(self.pieces):
            if p["start"] <= t < p["end"]:
                return k
        return len(self.pieces) - 1

    def base(self, t):
        k = self.piece_index(t); p = self.pieces[k]
        q = min(1.0, max(0.0, (t - p["start"]) / max(1e-6, p["end"] - p["start"])))
        s = p["from"] + (p["to"] - p["from"]) * q
        dx = p["dir"] * (-18 + 36 * q) if p["move"] == "drift" else 0.0
        for pt, to, pk_, _ in self.pins:
            if pk_ == k and t >= pt:
                s *= keys((t - pt) * FPS, [0, 4, 6], [1.0, to * 1.015, to])
        return s, dx

    def at(self, t):
        s, dx = self.base(t); dy = 0.0
        if self.pb and t >= self.pb["start"]:
            q = min(1, (t - self.pb["start"]) / max(1e-6, self.pb["end"] - self.pb["start"]))
            s *= 1 + (self.pb["to"] / self.pb["s_end"] - 1) * ease_io(q)
        for p in self.punch:
            if p["p0"] <= t < p["p1"]:
                s *= keys((t - p["p0"]) * FPS, [0, 3], [1.0, p["s"]])
            elif not p["snap"] and p["p1"] <= t < p["p1"] + self.PUNCH_OUT * F1:
                s *= 1 + (p["s"] - 1) * (1 - ease_io((t - p["p1"]) * FPS / self.PUNCH_OUT))
        e = 0.0
        for a, b in self.sway:
            e = max(e, min(1, (t - a) / 0.35, (b - t) / 0.35))
        if e > 0:
            dx += e * (11 * math.sin(2 * math.pi * 0.31 * t) + 5 * math.sin(2 * math.pi * 0.77 * t + 1.3))
            dy += e * (7 * math.sin(2 * math.pi * 0.23 * t + 0.4) + 3 * math.sin(2 * math.pi * 0.91 * t + 2.1))
            s *= 1 + 0.02 * e
        return min(max(s, 1.0), 1.35), dx, dy                     # under 1x the picture wouldn't fill the frame

    def box(self, t, base, full, anchor):
        """The source box for time t: the shot's framing base = (w, h, x, y) zoomed by the camera around the face
        anchor (source pixels), shifted by the sway / drift, kept inside the full source frame full = (w, h)."""
        s, dx, dy = self.at(t)
        self.smax = max(self.smax, s)
        bw, bh, bx, by = base
        w, h = bw / s, bh / s
        x0 = anchor[0] - (anchor[0] - bx) / s - dx * w / W; y0 = anchor[1] - (anchor[1] - by) / s - dy * h / H
        x0 = min(max(0.0, x0), full[0] - w); y0 = min(max(0.0, y0), full[1] - h)
        return (x0, y0, x0 + w, y0 + h)

    def events(self):
        ev = [{"t": pt, "kind": f"camera punch-in (line {lid})", "sfx": "whoosh_zoom"} for pt, _, _, lid in self.pins]
        if self.pb:
            ev.append({"t": (self.pb["start"] + self.pb["end"]) / 2, "kind": "camera pull-back", "sfx": "swish_soft"})
        return ev


# ---- picture (v2): grade, vignette, leaks, bloom, particles, accents ----------------------------------------------------
def interp(pts, t):
    if t <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if t <= b:
            return va + (vb - va) * ease_io((t - a) / max(1e-6, b - a))
    return pts[-1][1]


_VIG = None
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def grade(arr, g):
    """g: -1 cool, desaturated and dim with a heavier vignette ... 0 neutral (light vignette) ... +1 warm."""
    global _VIG
    if _VIG is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W * 0.5) / (W * 0.62)) ** 2 + ((yy - H * 0.42) / (H * 0.62)) ** 2)
        _VIG = (np.clip((r - 0.55) / 0.75, 0, 1) ** 1.6).astype(np.float32)
    c, w = max(0.0, -g), max(0.0, g)
    gain = np.array([1 - 0.06 * c + 0.07 * w, 1 - 0.015 * c + 0.015 * w, 1 + 0.05 * c - 0.09 * w], np.float32) * (1 - 0.10 * c + 0.03 * w)
    a = arr.astype(np.float32) * gain
    lu = (a @ LUMA)[..., None]
    a = lu + (a - lu) * (1 - 0.14 * c + 0.07 * w)
    k = 0.34 * c + 0.22 * w + 0.26 * (1 - c - w)
    a *= (1 - k * _VIG)[..., None]
    return a


def bloom(a, strength):
    if strength <= 0.005:
        return a
    small = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).resize((W // 4, H // 4), Image.BILINEAR)
    s = np.asarray(small, np.float32); s = np.clip(s - 150, 0, None) * (255 / 105)
    s = Image.fromarray(s.astype(np.uint8)).filter(ImageFilter.GaussianBlur(9)).resize((W, H), Image.BILINEAR)
    s = np.asarray(s, np.float32) * np.array([1.0, 0.85, 0.6], np.float32)
    return 255 - (255 - a) * (255 - s * strength) / 255


_ly, _lx = np.mgrid[0:H // 8, 0:W // 8].astype(np.float32)


def leak(a, t, lk):
    """A warm light leak sweeping left to right (screen blend), brightest in the middle of its time."""
    p = (t - lk["t"]) / lk["dur"]
    if not 0 <= p <= 1:
        return a
    amp = lk["amp"] * math.sin(math.pi * p)
    cx = (-0.35 + 1.7 * p) * W / 8; cy = (0.30 + 0.12 * math.sin(3 * p)) * H / 8
    m = np.exp(-(((_lx - cx) / (W / 8 * 0.55)) ** 2 + ((_ly - cy) / (H / 8 * 0.42)) ** 2))
    m2 = np.exp(-(((_lx - cx * 0.6 - W / 16) / (W / 8 * 0.9)) ** 2 + ((_ly - H / 8 * 0.75) / (H / 8 * 0.5)) ** 2)) * 0.5
    col = np.stack([m * 255 + m2 * 255, m * 170 + m2 * 205, m * 70 + m2 * 120], -1).clip(0, 255).astype(np.uint8)
    L = np.asarray(Image.fromarray(col).resize((W, H), Image.BICUBIC), np.float32) * amp
    return 255 - (255 - a) * (255 - L) / 255


_rng = np.random.default_rng(1114)
PARTS = [dict(x=float(_rng.uniform(40, 1040)), y=float(_rng.uniform(100, 1850)), vy=float(_rng.uniform(14, 40)), amp=float(_rng.uniform(6, 22)),
              fr=float(_rng.uniform(0.1, 0.35)), ph=float(_rng.uniform(0, 6.28)), r=float(_rng.uniform(3, 11)), a=float(_rng.uniform(0.18, 0.42)))
         for _ in range(26)]
_dots = {}


def dot(r):
    r = int(round(r))
    if r not in _dots:
        s = r * 6; im = Image.new("RGBA", (s, s), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=(255, 236, 190, 255))
        _dots[r] = im.filter(ImageFilter.GaussianBlur(r * 0.9))
    return _dots[r]


def particles(fr, t, a0, face):
    """Floating warm light from a0 on, faded out around the face."""
    if t < a0:
        return
    env = min(1, (t - a0) / 1.5); fx, fy = face[0] * W, face[1] * H
    for q in PARTS:
        y = (q["y"] - q["vy"] * (t - a0)) % 1900 + 10
        x = q["x"] + q["amp"] * math.sin(2 * math.pi * q["fr"] * t + q["ph"])
        dface = math.hypot((x - fx) / 330, (y - fy) / 300)
        al = q["a"] * env * min(1, max(0.0, dface - 0.6) / 0.5) * (0.75 + 0.25 * math.sin(2 * math.pi * 0.6 * t + q["ph"]))
        if al > 0.02:
            put(fr, dot(q["r"]), x, y, alpha=al)


def ring(fr, cx, cy, f, delay, col=(255, 246, 176)):
    f -= delay
    if not 0 <= f < 16:
        return
    r = keys(f, [0, 16], [110, 720]); a = keys(f, [0, 3, 16], [0.0, 0.75, 0.0]); wdt = keys(f, [0, 16], [9, 2])
    ry = min(r, 300)                                           # a flat ring: it stays off the face
    sw, sh = int(r * 2 + 40), int(ry * 2 + 40); im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((20, 20, sw - 20, sh - 20), outline=col + (255,), width=max(1, int(wdt)))
    put(fr, im.filter(ImageFilter.GaussianBlur(1.5)), cx, cy, alpha=a)


def orb(r, col):
    s = int(r * 3); im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((s / 2 - r * 0.6, s / 2 - r * 0.6, s / 2 + r * 0.6, s / 2 + r * 0.6), fill=col + (255,))
    return im.filter(ImageFilter.GaussianBlur(r * 0.45))


_ORB = {}


def accent(fr, t, b, kind):
    if t < b.t_in - F1 or t > b.t_out + 6 * F1:
        return
    fade = 1.0 if t <= b.t_out else max(0.0, 1 - (t - b.t_out) * FPS / 5)
    cy = b.centre_y()
    if kind == "rings":
        f = (t - b.landed()) * FPS
        ring(fr, W / 2, cy, f, 0); ring(fr, W / 2, cy, f, 5, (255, 255, 255))
    elif kind == "orbs":
        if "orb" not in _ORB:
            _ORB["orb"] = orb(190, (255, 196, 92))
        f = (t - b.t_in) * FPS; p = ease_io(min(1, f / 30))
        y = (b.rows[0]["cy"] if hasattr(b, "rows") else cy) + 40
        al = min(1, f / 8) * 0.5 * fade * (0.9 + 0.1 * math.sin(t * 4))
        put(fr, _ORB["orb"], 150 + 320 * p, y, alpha=al); put(fr, _ORB["orb"], 930 - 320 * p, y, alpha=al)
    elif kind == "halo":
        if "halo" not in _ORB:
            _ORB["halo"] = orb(420, (255, 205, 110))
        f = (t - b.t_in) * FPS
        put(fr, _ORB["halo"], W / 2, cy, 1.0 + 0.04 * math.sin(t * 2.2), alpha=min(1, f / 18) * 0.42 * fade)


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


def flash_k(t, tc):
    j = (t - tc) * FPS
    return {-1: 0.5, 0: 0.9, 1: 0.6, 2: 0.25}.get(int(math.floor(j)), 0) if -1 <= j < 3 else 0.0


# ---- main ------------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--frame", choices=["crop", "blur"], default="crop")
    ap.add_argument("--crop", default=None); ap.add_argument("--focus", type=float, default=0.5)
    ap.add_argument("--to", type=float, default=None, help="preview: stop at this time of the clip")
    ap.add_argument("--from", dest="frm", type=float, default=0.0, help="preview: start at this time of the clip")
    ap.add_argument("--hr", default=None, help="the full-resolution camera footage of the same edit (same length and cuts); "
                                               "the picture comes from it, the sound from <video>")
    ap.add_argument("--hr-map", default=None, help="with --hr: the framing of each shot in the footage's pixels (cutmap.json)")
    ap.add_argument("--no-punch", action="store_true", help="no picture punch-in on punch lines")
    ap.add_argument("--no-text", action="store_true"); ap.add_argument("--phone", action="store_true")
    ap.add_argument("--classic", action="store_true", help="the v1 look: hard-cut cards, no camera, grade or light")
    ap.add_argument("--crf", default="18"); ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    t0 = time.time()
    plan = load(a.plan)
    classic = a.classic or plan.get("motion") == "classic"
    err, warn = cc.check(plan)
    # the full-resolution footage named in the plan ("hr", "hr_map": paths, relative to the plan's folder) is used
    # whenever it is there, so every render and preview of the clip gets it without the flags
    pdir = os.path.dirname(os.path.abspath(a.plan))
    pth = lambda p: p if os.path.isabs(p) else os.path.join(pdir, p)
    if not a.hr and plan.get("hr") and not classic:
        if os.path.isfile(pth(plan["hr"])):
            a.hr = pth(plan["hr"])
            if not a.hr_map and plan.get("hr_map"):
                if os.path.isfile(pth(plan["hr_map"])):
                    a.hr_map = pth(plan["hr_map"])
                else:
                    err.append(f"plan hr_map {plan['hr_map']} is missing; without it the footage's framing would be wrong")
        else:
            warn.append(f"plan hr {plan['hr']} is missing; rendering from {a.video} (punch-ins and pushes enlarge it)")
    elif plan.get("hr_map") and not plan.get("hr") and not a.hr:
        err.append("plan hr_map needs plan hr (the footage the map's boxes are in)")
    elif a.hr and not a.hr_map and plan.get("hr_map"):
        warn.append("--hr without --hr-map: the plan's hr_map is not used, so the footage must have the edit's framing")
    if a.hr_map and not a.hr:
        err.append("--hr-map needs --hr (the footage the map's boxes are in)")
    if err:
        report(tool="render", ok=False, errors=err, warnings=warn); sys.exit(1)
    info = cc.probe(a.video)
    full = info["duration"]                                     # everything is planned on the whole clip, so a preview
    end = min(full, a.to) if a.to else full                     # (--from / --to) shows exactly the frames of the full render
    frm = round(max(0.0, a.frm or 0.0) * FPS) / FPS           # on the frame grid, so a preview's frames are the full render's
    if end - frm < 2 * F1:
        report(tool="render", ok=False, errors=[f"nothing to render between --from {frm} and --to {end}"], warnings=warn); sys.exit(1)
    preview = frm > 0 or end < full
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    cards = CardRenderer(plan.get("card") or {}, (plan.get("card_y") or 0.51) * H)
    bigs = []
    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else full
        if (ln.get("kind") or "card") != "card":
            b = Big(ln, warn)
            b.t_out = min(max(ln["end"] + 0.25, b.settle + 0.6), nxt + 0.6, full)
            if b.t_out < b.settle + 0.5:
                warn.append(f"line {b.id}: the {b.kind} is up only {max(0, b.t_out - b.settle):.2f}s after it lands; give it a longer line")
            bigs.append(b)
    timeline = card_timeline(lines, bigs, full, classic, warn)
    trans = [(ln["start"], ln["transition"]) for ln in lines if ln.get("transition")]
    by_line = {b.id: b for b in bigs}
    accents = [] if classic else [(by_line[ln.get("id")], ln["accent"]) for ln in lines if ln.get("accent") and ln.get("id") in by_line]
    ccfg = plan.get("camera") or {}
    face = ccfg.get("face") or [0.5, 0.3]

    # the picture source: <video> itself, or with --hr the full-resolution footage of the same edit
    src_video = a.hr or a.video
    hmap = None
    if a.hr:
        hinfo = cc.probe(a.hr)
        if abs(hinfo["duration"] - full) > 0.25:
            warn.append(f"--hr footage is {hinfo['duration']:.2f}s long and the clip {full:.2f}s; they should be the same edit")
        if a.hr_map:
            hmap = load_map(a.hr_map, (hinfo["width"], hinfo["height"]))
            RW, RH = int(hinfo["width"]), int(hinfo["height"])
    use_cam = not classic and ccfg.get("on", True)
    if hmap:
        # footage + framing map: decode at full size, cut each shot's box out of it (no upscale until the zoom
        # passes the footage's own resolution)
        FW, FH, hr = RW, RH, None
    else:
        # the frame: v2 decodes with up to 1.35x headroom (the camera's largest zoom) when the source allows it
        if a.crop:
            sw, sh = (int(v) for v in a.crop.split(":")[2:])
        else:
            si = hinfo if a.hr else info
            sw, sh = si.get("width") or W, si.get("height") or H
        hr = max(1.0, min(1.35, sw / W, sh / H)) if a.frame == "crop" and (use_cam or a.hr) else 1.0
        if not use_cam:
            hr = 1.0                                            # no camera: decode straight to 1080x1920
        FW, FH = int(round(W * hr / 2)) * 2, int(round(H * hr / 2)) * 2
    cam = None
    if use_cam:
        cuts = ccfg.get("cuts", "auto")
        if hmap:
            cuts = hmap[1]                                      # the map knows every cut exactly
        elif cuts == "auto":
            cuts = detect_cuts(a.video, a.crop, float(ccfg.get("cut_ratio", 2.0)), float(ccfg.get("cut_floor", 2.0)))
            if cuts is None:
                warn.append("camera cuts: the clip could not be read for cut detection; the camera moves ignore its cuts")
        cam = Camera(ccfg, lines, bigs, trans, full, [float(c) for c in cuts or []], a.no_punch)
    if hmap:
        rb0 = hmap[0][0][2]
        anchor = hmap[2] or (rb0[2] + face[0] * rb0[0], rb0[3] + face[1] * rb0[1])

        def frame_box(t):
            rb = next((r[2] for r in hmap[0] if r[0] <= t < r[1]), hmap[0][-1][2] if t >= hmap[0][-1][0] else hmap[0][0][2])
            if cam:
                return cam.box(t, rb, (RW, RH), anchor)
            return (rb[2], rb[3], rb[2] + rb[0], rb[3] + rb[1])
    elif cam:
        def frame_box(t):
            return cam.box(t, (FW, FH, 0, 0), (FW, FH), (face[0] * FW, face[1] * FH))
    else:
        frame_box = None
    # the picture punch on punch lines when the camera doesn't carry it: classic (v1, 1.35x) or v2 with the camera off
    punches = [(b.t_in - 3 * F1, b.t_out) for b in bigs if b.kind == "punch"] if (not cam and not a.no_punch) else []
    punch_zoom = 1.35 if classic else float(ccfg.get("punch_scale", 1.25))
    gpts = None
    if not classic:
        gpts = plan.get("grade", [[0.0, 0.0]])                 # default: neutral, with the light vignette
        gpts = sorted([float(p[0]), float(p[1])] for p in gpts) if gpts else None   # "grade": false / [] = no grade
    light = None if classic else cc.light_of(plan)              # "light": true / a time / {"from": t, ...}
    bloom_pts = None
    if light:
        lf = float(light["from"]); lt = float(light.get("to", full)); bs = float(light.get("bloom", 0.16))
        bloom_pts = [[lf, 0.0], [min(lt, lf + 3.0), bs], [lt, bs]]
    leaks = [] if classic else (
        [{"t": tc, "dur": 0.9, "amp": 0.55, "what": "after the flash"} for tc, k in trans if k == "flash"]
        + [{"t": ln["start"], "dur": 1.5, "amp": 0.38, "what": f"line {ln.get('id')}"} for ln in lines if ln.get("leak")]
        + [dict({"dur": 1.0, "amp": 0.5, "what": "plan"}, **lk) for lk in plan.get("leaks") or []])

    def stage_env(t):
        e = 0.0
        for b in bigs:
            k = 0.55 if b.kind == "punch" else (0.8 if b.kind == "breathe" else 1.0)   # punch: the punch-in carries it
            e = max(e, k * min(1, (t - (b.t_in - 2 * F1)) * FPS / 4, (b.t_out + 4 * F1 - t) * FPS / 4))
        return max(0.0, e)

    pre = ""
    if a.crop and not hmap:
        x, y, w, h = a.crop.split(":"); pre = f"crop={w}:{h}:{x}:{y},"
    if hmap:
        vf, vflag = f"setsar=1,fps={FPS}", "-vf"
    elif a.frame == "crop":
        vf, vflag = pre + f"scale={FW}:{FH}:force_original_aspect_ratio=increase,crop={FW}:{FH}:(in_w-{FW})*{a.focus}:(in_h-{FH})/2,setsar=1,fps={FPS}", "-vf"
    else:
        vf, vflag = (f"[0:v]{pre}split[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg];"
                     f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"), "-filter_complex"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = (["-ss", f"{frm:.3f}"] if frm > 0 else []) + ["-t", f"{end - frm:.3f}"]
    has_aac = "Audio: aac" in subprocess.run([FFMPEG, "-hide_banner", "-i", a.video], capture_output=True, text=True).stderr
    acodec = ["-c:a", "copy"] if (has_aac and frm == 0) else ["-c:a", "aac", "-b:a", "192k"]   # a cut-in preview re-encodes
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", *tl, "-i", src_video, vflag, vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            *tl, "-i", a.video, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", a.preset, "-crf", a.crf, "-pix_fmt", "yuv420p",
                            *acodec, "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    qin, qout = queue.Queue(4 if hmap else 6), queue.Queue(6); fsz = FW * FH * 3
    werr = []

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
            if werr:
                continue                                        # the encoder is gone: keep draining so nothing hangs
            try:
                enc.stdin.write(b)
            except OSError as e:
                werr.append(str(e))
    threading.Thread(target=reader, daemon=True).start(); thw = threading.Thread(target=writer, daemon=True); thw.start()
    n = 0; upmax = 0.0
    while True:
        buf = qin.get()
        if buf is None:
            break
        if werr:
            break
        t = (round(frm * FPS) + n) / FPS; n += 1               # exact frame times, as the full render's
        if frame_box:
            src = Image.frombuffer("RGB", (FW, FH), buf, "raw", "RGB", 0, 1)
            bx = frame_box(t)
            upmax = max(upmax, W / max(1e-6, bx[2] - bx[0]))    # output pixels per decoded pixel (> 1 = enlarged)
            arr = np.asarray(src.resize((W, H), Image.LANCZOS if hmap else Image.BICUBIC, box=bx))
        else:
            arr = np.frombuffer(buf, np.uint8).reshape(FH, FW, 3)
            upmax = max(upmax, 1.0)
        if any(p0 <= t <= p1 for p0, p1 in punches):
            arr = zoom(arr, punch_zoom)
        af = grade(arr, interp(gpts, t)) if gpts else arr.astype(np.float32)
        if bloom_pts and t >= bloom_pts[0][0]:
            af = bloom(af, interp(bloom_pts, t))
        for tc, kind in trans:
            k = flash_k(t, tc) if kind == "flash" else 0.0
            if k:
                af = af * (1 - k) + 255 * k
        for lk in leaks:
            af = leak(af, t, lk)
        arr = np.clip(af, 0, 255).astype(np.uint8)
        for tc, kind in trans:
            j = (t - tc) * FPS
            if kind == "blurcut" and 0 <= j < 3:
                arr = np.asarray(Image.fromarray(arr).filter(ImageFilter.GaussianBlur(14 * (1 - j / 3) + 0.01)))
        if a.no_text:
            qout.put(np.ascontiguousarray(arr).tobytes()); continue
        arr = stage(arr, stage_env(t))
        fr = Image.fromarray(arr).convert("RGBA")
        if light and light.get("particles", True):
            particles(fr, t, float(light["from"]), face)
        for b, kind in accents:
            accent(fr, t, b, kind)
        for c in timeline:
            if c["t0"] <= t < c["t1"]:
                cards.draw(fr, c, t)
        for b in bigs:
            b.draw(fr, t)
        qout.put(np.asarray(fr.convert("RGB")).tobytes())
    qout.put(None); thw.join()
    try:
        enc.stdin.close()
    except OSError:
        pass
    enc.wait(); dec.stdout.close(); dec.wait()
    base = os.path.splitext(a.out)[0]
    want = int(round((end - frm) * FPS))
    fail = []
    if werr or enc.returncode != 0:
        fail.append(f"the encoder (ffmpeg) failed (exit {enc.returncode}{'; ' + werr[0] if werr else ''}); {a.out} is not usable")
    if dec.returncode not in (0, None) and n < want - 2:
        fail.append(f"the decoder (ffmpeg) failed on {src_video} (exit {dec.returncode})")
    if n < want - 2:
        fail.append(f"only {n} of {want} frames were rendered")
    if fail:
        report(tool="render", ok=False, out=a.out, frames=n, errors=fail, warnings=warn); sys.exit(1)
    out = {"tool": "render", "ok": True, "out": a.out, "motion": "classic" if classic else "v2", "frames": n, "seconds": round(n / FPS, 2),
           "render_seconds": round(time.time() - t0, 1)}
    if preview:
        out.update(preview=[round(frm, 3), round(end, 3)])
    out.update(source=src_video, max_upscale=round(upmax, 3))
    if cam:
        out.update(camera_pieces=len(cam.pieces), max_zoom=round(cam.smax, 3))
        if hr:
            out.update(headroom=round(hr, 3))
    if not a.no_text:
        def srt_t(x):
            ms = int(round(max(0, x) * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        with open(base + ".srt", "w", encoding="utf-8") as f:             # times in the rendered file (a preview starts at 0)
            k = 0
            for ln in lines:
                if ln["end"] + 0.3 <= frm or ln["start"] >= end:
                    continue
                k += 1
                f.write(f"{k}\n{srt_t(ln['start'] - frm)} --> {srt_t(min(ln['end'] + 0.3, end) - frm)}\n{display(ln['text'])}\n\n")
        ev = [{"t": c["t0"] + 0.15, "kind": f"card ({c['anim']})", "line": c["line"]} for c in timeline if c["first"]]
        ev += [{"t": tk + 3 * F1, "kind": "card key word", "line": c["line"]} for c in timeline for (_, _, tk) in c["keys"]]
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
        for lk in leaks:
            sfx.append({"frame": int(round((lk["t"] + lk["dur"] / 2) * FPS)), "sound": "chime_soft", "what": f"light leak brightest ({lk['what']})"})
        for e in (cam.events() if cam else []):
            ev.append({"t": e["t"], "kind": e["kind"], "line": None})
            sfx.append({"frame": int(round(e["t"] * FPS)), "sound": e["sfx"], "what": e["kind"]})
        ev = sorted([dict(e, t=round(e["t"] - frm, 4)) for e in ev if frm <= e["t"] < end], key=lambda e: e["t"])   # file time
        f0 = int(round(frm * FPS))
        sfx = [dict(e, frame=e["frame"] - f0) for e in sfx if 0 <= e["frame"] - f0 < n]
        save(base + ".pk.json", {"video": os.path.abspath(a.out), "events": ev, "warnings": warn})
        save(base + ".sfx-events.json", {"events": sorted(sfx, key=lambda e: e["frame"]),
                                         "note": "draft from the caption-card plan: keep the true punchlines, delete the rest (a sermon stays reverent)"})
        pc = os.path.join(os.path.dirname(os.path.abspath(a.out)), "plan.json")
        if os.path.abspath(a.plan) != pc:
            shutil.copyfile(a.plan, pc)
        out.update(srt=base + ".srt", sfx_events=base + ".sfx-events.json", cards=len(timeline),
                   big={k: sum(1 for b in bigs if b.kind == k) for k in cc.KINDS if k != "card"}, transitions=len(trans))
    if a.phone:
        phone = base + "_phone.mp4"
        if os.path.getsize(a.out) <= 28 * 1048576:
            shutil.copyfile(a.out, phone)
        else:
            kbps = int((28 * 8 * 1024 * 1024 / max(1.0, end - frm) - 160_000) / 1000)
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
