"""Step 7a (renderers): build this video's two cute caption renderers FROM the caption-card skill, at run time.

usage: python make_renderers.py <work folder> [--check]

Makes <work>/cc916/ (1080x1920) and <work>/cc16/ (1920x1080). Each gets a FRESH copy of the caption-card skill's
render.py and cc.py (.claude/skills/caption-card/scripts/), then:
  cc16   the landscape patch (REPL16 below): W, H = 1920, 1080, landscape SAFE margins, cards in the lower third (y 0.82,
         110 px type, max width 1500), smaller big type (hook rows 104/150 px, write-on 230, punch 190), layout16.json
         beside the plan (per line "x" / "y", and "card_y"), flatter rings, smaller orbs / halo, particles over the
         landscape frame, cut detection on a 128x72 copy. The plan's 9:16 "card_y" / line "y" are not used.
  both   the cute patch (REPL_CUTE below): puffy pink sticker cards that wobble in, hopping / jelly characters, candy
         key words with sparkles, bouncy rainbow-outline big type, speech-bubble cards, 6-frame shrink-pop exits with
         poofs, one quiet pop per card line, and the v3 fix (card chunks under 0.4 s join their neighbour, every
         character lands 4 frames before its card ends). It is ON when the plan says "edition": "cute ..." (makeplan.py
         writes that) or with --cute; --no-cute turns it off. Since caption-card t207 (2026-11-08) the skill itself
         keeps whole words on the cards, joins chunks under 0.4 s and runs its grade arc / warm light at half strength
         ("grade": "neutral" for an already graded source), so the cute fix only catches what is left.
  and    cute.py and sfx_dryrun.py from this skill's scripts/ are copied next to render.py. cute.py reads cute.json
         from the PLAN's folder (template ../templates/cute.json; --cute <file> picks another one).
Every replacement must match EXACTLY ONCE in the skill's current render.py. If the caption-card skill changed so that
one doesn't, this stops LOUDLY, names the line it could not find and writes nothing: update the patch here (compare
the skill's new render.py with the old one), never edit the renderer copies by hand. A caption-card update that leaves
these lines alone flows straight into the kids look. --check only tests that every patch still applies.
Run it again whenever the caption-card skill changes; it overwrites the two folders' render.py / cc.py / cute.py.
Prints one JSON line.
"""
import json, os, shutil, sys

NL = "\n"
HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.normpath(os.environ.get("CAPTION_CARD_SCRIPTS") or os.path.join(HERE, "..", "..", "caption-card", "scripts"))
#    (env CAPTION_CARD_SCRIPTS: another caption-card scripts folder, e.g. to test a new caption-card version first)

# ---- the landscape patch (from the 1107 16:9 renderer, cc16/patch16.py) -------------------------------------------------
REPL16 = [
    ('"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).' + NL,
     '"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).' + NL + NL +
     "cc16: a LANDSCAPE copy (1920x1080) of .claude/skills/caption-card/scripts/render.py made by the kids-review skill," + NL +
     "changed only by kids-review/scripts/make_renderers.py (frame size, card / big-type sizes and positions, layout16.json, accents," + NL +
     "particles, cut detection). Everything else is the skill's v2 renderer unchanged." + NL),
    ("W, H = 1080, 1920" + NL,
     "W, H = 1920, 1080                                           # cc16: the landscape (16:9) copy of the skill's renderer" + NL +
     'SAFE = {"left": 110, "right": 1810, "top": 70, "bottom": 1010}' + NL +
     "CARD_Y16 = 0.82                                             # cc16: cards in the lower third" + NL +
     'BIG_Y16 = {"hook": 0.66, "writeon": 0.70, "punch": 0.70, "number": 0.56, "breathe": 0.64}' + NL +
     "LAYOUT16 = {}                                               # cc16: filled from layout16.json beside the plan" + NL),
    ('size, gs, box = fit_size(text, "card", 150, 900, None, 0.0, 70)',
     'size, gs, box = fit_size(text, "card", 110, 1500, None, 0.0, 50)'),
    ("gy = keys(fe, [0, 4, 6], [70, -6, 0])", "gy = keys(fe, [0, 4, 6], [45, -4, 0])"),
    ('self.yf = ln.get("y")',
     'lay = LAYOUT16.get("lines", {}).get(str(self.id), {})       # cc16: layout16.json beside the plan, per line id' + NL +
     '        self.yf = lay.get("y") or BIG_Y16.get(self.kind)     # cc16: the plan\'s "y" is a 9:16 position' + NL +
     '        self.xc = float(lay.get("x", 0.5)) * W                # cc16: big type can sit left or right of centre'),
    ("sizes = [210 if i == key else 150 for i in range(len(rows))]", "sizes = [150 if i == key else 104 for i in range(len(rows))]"),
    ('s, _, b = fit_size(txt, "hook", sizes[i], 940, None, 0.0, 60)', 's, _, b = fit_size(txt, "hook", sizes[i], 1500, None, 0.0, 44)'),
    ("gap = 14" + NL, "gap = 10" + NL),
    ('fit_size(txt, "hook", 205 if i == key else 128, 900, None, 0.0, 60)', 'fit_size(txt, "hook", 140 if i == key else 90, 1500, None, 0.0, 44)'),
    ('fit_size(num, "number", 1400, 790, H * 0.45, 0.0, 120)', 'fit_size(num, "number", 900, 1200, H * 0.5, 0.0, 90)'),
    ('fit_size(lt, "hook", 165, 900, None, 0.0, 30)', 'fit_size(lt, "hook", 110, 1300, None, 0.0, 30)'),
    ('fit_size(ph, "writeon", 340, 920, H * 0.17, 0.0, 80)', 'fit_size(ph, "writeon", 230, 1400, H * 0.24, 0.0, 60)'),
    ('fit_size(st, "writeon", 130, self.ink[0] * 1.0 + 40, None, 0.0, 50)', 'fit_size(st, "writeon", 90, self.ink[0] * 1.0 + 40, None, 0.0, 40)'),
    ("target = W * 0.86" + NL, "target = 1400" + NL),
    ("s, _, b = fit_size(ph, role, 260, target, H * 0.14, 0.0, 70)", "s, _, b = fit_size(ph, role, 190, target, H * 0.2, 0.0, 56)"),
    ("gw, gh = 72, 128", "gw, gh = 128, 72"),
    ("PARTS = [dict(x=float(_rng.uniform(40, 1040)), y=float(_rng.uniform(100, 1850)),",
     "PARTS = [dict(x=float(_rng.uniform(40, 1880)), y=float(_rng.uniform(40, 1040)),"),
    ('y = (q["y"] - q["vy"] * (t - a0)) % 1900 + 10', 'y = (q["y"] - q["vy"] * (t - a0)) % 1060 + 10'),
    ("r = keys(f, [0, 16], [110, 720]);", "r = keys(f, [0, 16], [90, 620]);"),
    ("ry = min(r, 300)", "ry = min(r, 200)"),
    ("ring(fr, W / 2, cy, f, 0); ring(fr, W / 2, cy, f, 5, (255, 255, 255))", "ring(fr, b.xc, cy, f, 0); ring(fr, b.xc, cy, f, 5, (255, 255, 255))"),
    ('_ORB["orb"] = orb(190, (255, 196, 92))', '_ORB["orb"] = orb(150, (255, 196, 92))'),
    ('put(fr, _ORB["orb"], 150 + 320 * p, y, alpha=al); put(fr, _ORB["orb"], 930 - 320 * p, y, alpha=al)',
     'put(fr, _ORB["orb"], W * 0.14 + 420 * p, y, alpha=al); put(fr, _ORB["orb"], W * 0.86 - 420 * p, y, alpha=al)'),
    ('_ORB["halo"] = orb(420, (255, 205, 110))', '_ORB["halo"] = orb(300, (255, 205, 110))'),
    ('put(fr, _ORB["halo"], W / 2, cy,', 'put(fr, _ORB["halo"], b.xc, cy,'),
    ("    pdir = os.path.dirname(os.path.abspath(a.plan))" + NL,
     "    pdir = os.path.dirname(os.path.abspath(a.plan))" + NL +
     '    if os.path.isfile(os.path.join(pdir, "layout16.json")):     # cc16: the landscape layout of this plan' + NL +
     '        LAYOUT16.update(load(os.path.join(pdir, "layout16.json")))' + NL),
    ('cards = CardRenderer(plan.get("card") or {}, (plan.get("card_y") or 0.51) * H, neg=Big.NEG)',
     'cards = CardRenderer(plan.get("card") or {}, (LAYOUT16.get("card_y") or CARD_Y16) * H, neg=Big.NEG)   # cc16'),
]

# ---- the cute patch (from the 1107 v3 renderers, cute_patch.py) --------------------------------------------------------
REPL_CUTE = [
    ('"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).' + NL,
     '"""Render a clip in the Caption Card style (字卡动效) from its planning page (plan.json).' + NL +
     "cute: the kids' cute edition is hooked in by kids-review/scripts/make_renderers.py (cute.py next to this file; --cute / --no-cute)." + NL),
    ("import cc  # noqa: E402" + NL,
     "import cc  # noqa: E402" + NL + "import cute  # noqa: E402  (cute: the kids' edition, cute.py next to this file)" + NL),
    ('"mimg": cc.mask_sprite(g["mask"]) if self.neg else None})',
     '"mimg": cc.mask_sprite(g["mask"]) if self.neg else None,' + NL +
     '                           "mask": g["mask"], "my": g["y"]})                       # cute: the sticker letters need the mask'),
    ('d = {"size": size, "glyphs": glyphs, "bw": bw, "bh": bh, "cw": cw, "ch": ch, "cx": cw / 2, "cy": ch / 2, "settled": {}}',
     'd = {"size": size, "glyphs": glyphs, "bw": bw, "bh": bh, "cw": cw, "ch": ch, "cx": cw / 2, "cy": ch / 2, "settled": {},' + NL +
     '             "ink": (box[1], box[3]), "tw": tw}                                    # cute'),
    ('        d = self.build(c["text"])' + NL + '        sp = 1.0 if c["first"] else 1.7',
     '        if cute.ON:                                             # cute: the kids\' sticker card' + NL +
     '            return cute.draw_card(self, fr, c, t)' + NL +
     '        d = self.build(c["text"])' + NL + '        sp = 1.0 if c["first"] else 1.7'),
    # caption-card 2026-11-08 (t207): the skill's card entries carry "span" and "li" themselves and join short chunks
    # itself (join_short, before cute.fix_timeline, which then only catches what is left)
    ('"line": ln.get("id"), "exit": not classic, "span": (a, b), "li": i})',
     '"line": ln.get("id"), "exit": not classic, "span": (a, b), "li": i,' + NL +
     '                       "bubble": ln.get("bubble"),                                # cute: speech-bubble cards' + NL +
     '                       "ltext": text})                                            # cute v3: lets short chunks join'),
    ("        if alive:" + NL + "            out.append(c)" + NL + "    return out" + NL,
     "        if alive:" + NL + "            out.append(c)" + NL +
     "    if cute.ON:                                                 # cute v3: chunks under 0.4 s join their neighbour" + NL +
     "        out = cute.fix_timeline(out, warn)" + NL + "    return out" + NL),
    ('self.gl, self.ink = styled_line(ph, "writeon", s, self.color, glow_r=22)',
     'self.gl, self.ink = styled_line(ph, "writeon", s, self.color, glow_r=22); self.size = s   # cute: size kept'),
    ('self.gl, self.ink = styled_line(ph, role, s, self.color, glow_r=18, shadow=("#141A0E", 26, 14, 1.0))',
     'self.gl, self.ink = styled_line(ph, role, s, self.color, glow_r=18, shadow=("#141A0E", 26, 14, 1.0))' + NL +
     '        self.size, self.role = s, role                         # cute: size and font role kept'),
    ("        of = OUT_FRAMES[self.kind]" + NL,
     "        of = (cute.OUT_FRAMES if cute.ON else OUT_FRAMES)[self.kind]   # cute: 6-frame shrink-pop exits" + NL),
    ('        getattr(self, "draw_" + self.kind)(fr, t, out_p)' + NL,
     '        if cute.ON and self.kind in cute.BIG_KINDS:              # cute: bouncy kid entrances, rainbow outline' + NL +
     '            return cute.draw_big(self, fr, t, out_p)' + NL +
     '        getattr(self, "draw_" + self.kind)(fr, t, out_p)' + NL),
    ('ap.add_argument("--classic", action="store_true", help="the v1 look: hard-cut cards, no camera, grade or light")',
     'ap.add_argument("--classic", action="store_true", help="the v1 look: hard-cut cards, no camera, grade or light")' + NL +
     '    ap.add_argument("--cute", nargs="?", const="", default=None, help="cute: the kids\' edition (optional config json; '
     'default cute.json next to cute.py); also on when plan edition starts with cute")' + NL +
     '    ap.add_argument("--no-cute", action="store_true", help="cute: off even when the plan says edition cute")'),
    ("    pth = lambda p: p if os.path.isabs(p) else os.path.join(pdir, p)" + NL,
     "    pth = lambda p: p if os.path.isabs(p) else os.path.join(pdir, p)" + NL +
     "    cute.setup(W, H, SAFE, (a.cute is not None or cute.wants(plan)) and not a.no_cute and not classic, pdir," + NL +
     "               a.cute or None, warn)                           # cute" + NL),
    ("        for c in timeline:" + NL + '            if c["t0"] <= t < c["t1"]:' + NL + "                cards.draw(fr, c, t)" + NL,
     "        if cute.ON:                                             # cute: exit poofs, under the cards" + NL +
     "            cute.poofs(fr, cards, timeline, t)" + NL +
     "        for c in timeline:" + NL + '            if c["t0"] <= t < c["t1"]:' + NL + "                cards.draw(fr, c, t)" + NL),
    ("        for e in (cam.events() if cam else []):" + NL,
     "        if cute.ON:                                             # cute: one quiet pop per card line" + NL +
     "            sfx += cute.sfx_events(timeline)" + NL +
     "        for e in (cam.events() if cam else []):" + NL),
    ('    out["warnings"] = warn' + NL,
     '    out["edition"] = "cute" if cute.ON else "standard"          # cute' + NL + '    out["warnings"] = warn' + NL),
]


def apply(src, repl, name):
    for a, b in repl:
        n = src.count(a)
        if n != 1:
            raise SystemExit(f"make_renderers: the {name} patch no longer fits the caption-card skill's render.py: expected 1 "
                             f"match, found {n}: {a[:90]!r}. The skill changed; update the patch in {os.path.abspath(__file__)}.")
    for a, b in repl:
        src = src.replace(a, b)
    return src


def landscape(src):
    if "cc16:" in src:
        raise SystemExit("make_renderers: the skill's render.py already holds the landscape patch; it must be the skill's own file")
    src = apply(src, REPL16, "landscape (16:9)")
    i, j = src.index("class Big:"), src.index("# ---- camera (v2)")       # big type: "W / 2 + ..." x -> "self.xc + ..."
    k = src[i:j].count("W / 2 + ")
    if k < 8:
        raise SystemExit(f"make_renderers: expected the big-type x positions (W / 2 + ...) in class Big, found {k}")
    return src[:i] + src[i:j].replace("W / 2 + ", "self.xc + ") + src[j:]


def main():
    args = sys.argv[1:]
    check = "--check" in args
    pos = [a for a in args if not a.startswith("--")]
    if len(pos) != 1:
        raise SystemExit(__doc__)
    work = pos[0]
    base = open(os.path.join(CC, "render.py"), encoding="utf-8").read()
    if "import cute" in base:
        raise SystemExit("make_renderers: the caption-card skill's render.py already imports cute; it must be the skill's own file")
    built = {"cc916": apply(base, REPL_CUTE, "cute (9:16)"), "cc16": apply(landscape(base), REPL_CUTE, "cute (16:9)")}
    if check:
        print(json.dumps({"ok": True, "check": True, "skill_render": os.path.join(CC, "render.py"),
                          "patches": {"landscape": len(REPL16), "cute": len(REPL_CUTE)}}))
        return
    out = {}
    for folder, src in built.items():
        d = os.path.join(work, folder)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "render.py"), "w", encoding="utf-8", newline="\n").write(src)
        shutil.copyfile(os.path.join(CC, "cc.py"), os.path.join(d, "cc.py"))
        for f in ("cute.py", "sfx_dryrun.py"):
            shutil.copyfile(os.path.join(HERE, f), os.path.join(d, f))
        out[folder] = d
    print(json.dumps({"ok": True, "renderers": out, "from": CC, "patches": {"landscape": len(REPL16), "cute": len(REPL_CUTE)}}))


if __name__ == "__main__":
    main()
