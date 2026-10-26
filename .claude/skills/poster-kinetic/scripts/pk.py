"""Shared pieces of the Poster Kinetic (大字海报动态) scripts: the guide's numbers, the sermon palette, plan checks and
the planning page. Text units, speech timing and the ffmpeg helpers come from the yellow-serif and reel skills, so all
three skills transcribe, cut and report the same way.
"""
import importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SKILLS = os.path.dirname(SKILL)
YS = os.path.join(SKILLS, "yellow-serif", "scripts")
REEL = os.path.join(SKILLS, "reel", "scripts")
for p in (REEL, YS):
    if p not in sys.path:
        sys.path.insert(0, p)
import common as ys  # noqa: E402  (yellow-serif: units, char_times, display, width_units, probe, report, run, load, save)
from common import (FFMPEG, char_times, display, has_cjk, is_cjk, load, probe, report, run, save, units,  # noqa: E402,F401
                    width_units, NEG)


def ys_plan():
    """The yellow-serif plan.py module (transcribe, group, to_simplified, src_time), loaded without running it."""
    spec = importlib.util.spec_from_file_location("ys_plan", os.path.join(YS, "plan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- the guide in numbers (1080 x 1920, 30 fps) -------------------------------------------------------------------
FPS = 30
W0, H0 = 1080, 1920
SAFE = {"left": 90, "right": 990, "top": 120, "bottom": 1400}      # guide p.18: nothing below 1400 (platform UI)
EXTRUDE = (0x1B, 0x18, 0x13)                                        # measured #1B1813
WHITE = (0xFC, 0xFC, 0xFA)                                          # measured #FCFCFA

# Sizes at 1080 wide (guide p.4: hero 250-290, mid 100-140, small 58-92)
HERO_PX = 262
HERO_SHORT_PX = 288          # 1-3 characters
HERO_MIN_PX = 170
STACK_PX = 200
LEAD_PX = 100                # white lead-in / tail around a hero
CAPTION_PX = 78              # ordinary caption lines (sermon adaptation: every spoken line stays readable)
CAPTION_MIN_PX = 64
KEY_SCALE = 1.08

# Zones: the hero's visual centre (y at 1920 high). Speaker crops have the face around 25-40% of the height.
ZONES = {"top": 300, "middle": 820, "low": 1060}
CAPTION_BASE_Y = 1372        # baseline of the last caption row

# Motion timings in frames (guide pages 7-10, measured)
DROP = {"stagger": 1, "in": 3, "from_y": -36, "from_scale": 1.12, "blur": 14}
ZOOM = {"in": 3, "settle": 5, "from_scale": 1.10, "blur": 18}
WHIP = {"in": 3, "travel": 0.40, "mblur": 60, "drift": 40, "drift_frames": 16}
STACK = {"stagger": 5, "in": 2, "blur": 10}
CAPTION_IN = 2               # each word ghost -> solid in 2 frames
BLUR_OUT = 6                 # hero exit
CAPTION_OUT = 4              # caption morph into the next line
SWAP = {"out": 3, "drop": 60}
LEAD_FRAMES = 2              # a hero lands 0-4 frames before its word is spoken
HERO_MIN_HOLD = 1.0          # seconds a hero stays readable after it lands
CARD = {"in": 12, "from_scale": 0.55, "from_rot_y": -35, "rest_rot_y": -9, "rest_rot_x": 4, "blur": 10, "out": 8}
FLASH_T = 12                 # zoom-blur white flash transition, frames
WHIP_T = 5                   # whip-blur transition, frames
PUNCH = 0.045                # picture punch-in during a hero (sermon adaptation, the reference's camera moves)

# The sermon palette: the reel's measured colours, each given a meaning. "light" is used automatically when the
# colour would be too dark on the picture behind it (render.py measures the background).
PALETTE = {
    "white": {"hex": "#FCFCFA", "light": None, "use": "default, lead-ins, ordinary words"},
    "gold":  {"hex": "#F8EA98", "light": None, "use": "grace, hope, promise, blessing, God's love (the default key colour)"},
    "cream": {"hex": "#FBF4CA", "light": None, "use": "scripture, quotes, names of books"},
    "peach": {"hex": "#F8CCA2", "light": None, "use": "people, love, family, warmth"},
    "lime":  {"hex": "#ACD744", "light": None, "use": "life, growth, action, go, a way forward"},
    "ice":   {"hex": "#C5FFFC", "light": None, "use": "the Holy Spirit, peace, new, heaven, invitation"},
    "red":   {"hex": "#90132F", "light": "#F0657A", "use": "sin, warning, contrast, what is NOT (不是, 拒绝); at most twice a clip"},
    "navy":  {"hex": "#253C69", "light": "#8FB4FF", "use": "numbers and facts on a bright picture"},
    "blue":  {"hex": "#0A64BC", "light": "#5FA8FF", "use": "welcome, church, a section title"},
}
FILLS = ("solid", "gradient", "metal")
MODES = ("caption", "poster", "stack")
MOTIONS = ("whip", "drop", "zoom")
FROMS = ("left", "right", "top")
TRANSITIONS = (None, "", "flash", "whip", "push", "zoom_through")
OVERLAYS = ("title", "card", "name", "question")


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colour(name, light=False):
    """Palette name or #hex -> rgb. light=True gives the light variant when the colour has one."""
    if not name:
        name = "gold"
    if name.startswith("#"):
        return rgb(name)
    p = PALETTE.get(name, PALETTE["gold"])
    return rgb(p["light"] if light and p["light"] else p["hex"])


def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def norm(s):
    """Text without punctuation or spaces, for matching a card against the speech."""
    return re.sub(r"[\s，。、；：,.;:…·“”\"‘’「」『』！？!?（）()《》]", "", s or "")


def split_kw(text, kw):
    """(lead, keyword, tail) of a line around its key word (first occurrence)."""
    p = text.find(kw)
    return text[:p], kw, text[p + len(kw):]


# ---- checks -------------------------------------------------------------------------------------------------------
def check(plan):
    """The guide's rules as errors (must fix) and warnings (look again)."""
    err, warn = [], []
    lines = plan.get("lines", [])
    heroes, reds, trans = [], 0, []
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"
        t = ln.get("text", "")
        mode = ln.get("mode") or "caption"
        if mode not in MODES:
            err.append(f"{tag}: mode must be one of {MODES}")
            continue
        for kw in ln.get("keywords") or []:
            if not kw or kw not in t:
                err.append(f"{tag}: keyword '{kw}' is not an exact part of the line '{t}'")
        if len(ln.get("keywords") or []) > 2:
            err.append(f"{tag}: at most 2 inline keywords")
        interp = norm("".join(x.get("text", "") for x in plan.get("interpretation") or []))
        if ln.get("gloss") and norm(ln["gloss"]) not in interp + norm(t):
            err.append(f"{tag}: gloss '{ln['gloss']}' must be words actually spoken (the line or the interpretation)")
        if mode in ("poster", "stack") and ln.get("hero_from") == "interpretation":
            kw = ln.get("keyword")
            if not kw or norm(kw) not in interp:
                err.append(f"{tag}: hero '{kw}' is not in the interpreter's words (plan \"interpretation\")")
            if ln.get("hero_at") and ln["hero_at"] not in t:
                err.append(f"{tag}: hero_at '{ln['hero_at']}' is not an exact part of the line '{t}'")
            if mode == "stack" and not (kw and 2 <= len(display(kw)) <= 4):
                err.append(f"{tag}: stack is for 2-4 characters")
            heroes.append(ln.get("start", 0))
            if (ln.get("color") or "gold") == "red":
                reds += 1
        elif mode in ("poster", "stack"):
            kw = ln.get("keyword")
            if not kw or kw not in t:
                err.append(f"{tag}: {mode} needs \"keyword\", an exact part of the line '{t}'")
                continue
            p = t.find(kw)
            before = t[max(0, p - 2):p]
            if p > 0 and (t[p - 1] in NEG or before in ("不是", "没有")) and kw[0] not in NEG:
                warn.append(f"{tag}: the hero '{kw}' leaves out the negation before it; make the hero the whole phrase so the meaning stays")
            wu = width_units(display(kw))
            if mode == "stack" and not (2 <= len(display(kw)) <= 4 and all(is_cjk(c) for c in display(kw))):
                err.append(f"{tag}: stack is for 2-4 Chinese characters; '{kw}' does not fit, use poster")
            if mode == "poster" and wu > 6:
                warn.append(f"{tag}: hero '{kw}' is {wu:.0f} characters wide; heroes read best at 2-5 (it will shrink)")
            lead, _, tail = split_kw(t, kw)
            if width_units(display(lead)) + width_units(display(tail)) > 16:
                warn.append(f"{tag}: {mode} line has {width_units(display(lead + tail)):.0f} characters around the hero; split the line (plan.py --split) or use caption")
            heroes.append(ln.get("start", 0))
            if (ln.get("color") or "gold") == "red":
                reds += 1
            c = ln.get("color")
            if c and not (c in PALETTE or re.fullmatch(r"#[0-9a-fA-F]{6}", c)):
                err.append(f"{tag}: color '{c}' is not a palette name ({', '.join(PALETTE)}) or #hex")
            if ln.get("fill") and ln["fill"] not in FILLS:
                err.append(f"{tag}: fill must be one of {FILLS}")
            if ln.get("fill") == "gradient" and not ln.get("color2"):
                err.append(f"{tag}: gradient needs color2")
            if mode == "poster" and (ln.get("motion") or "whip") not in MOTIONS:
                err.append(f"{tag}: motion must be one of {MOTIONS}")
            if ln.get("from") and ln["from"] not in FROMS:
                err.append(f"{tag}: from must be one of {FROMS}")
            if ln.get("zone") and ln["zone"] not in ZONES:
                err.append(f"{tag}: zone must be one of {tuple(ZONES)}")
        if ln.get("transition") not in TRANSITIONS:
            err.append(f"{tag}: transition must be null, flash, whip, push or zoom_through")
        elif ln.get("transition"):
            trans.append(ln.get("start", 0))
        if i and ln.get("start", 0) < lines[i - 1].get("end", 0) - 0.05:
            warn.append(f"{tag}: starts before the line before it ends")
    n = len(lines)
    if n and len(heroes) > max(2, int(n * 0.45)):
        warn.append(f"{len(heroes)} heroes in {n} lines; one hero every 4-8 s keeps each one strong (guide: one point per screen)")
    for a, b in zip(heroes, heroes[1:]):
        if b - a < 2.0:
            warn.append(f"heroes at {a:.1f}s and {b:.1f}s are under 2 s apart; let each one be read")
    if reds > 2:
        warn.append(f"red is used {reds} times; keep it for the one contrast or warning that matters (at most 2)")
    if len(trans) > 4:
        warn.append(f"{len(trans)} transitions; 2-4 per clip, at section starts")
    for a, b in zip(trans, trans[1:]):
        if b - a < 6:
            warn.append(f"transitions at {a:.1f}s and {b:.1f}s are under 6 s apart")
    for k, pt in enumerate(plan.get("picture_transitions") or []):
        if pt.get("kind") not in ("flash", "whip", "push", "zoom_through") or not isinstance(pt.get("t"), (int, float)):
            err.append(f"picture_transitions {k + 1}: needs t (seconds) and kind flash / whip / push / zoom_through")
    # overlays
    spoken = norm("".join(ln.get("text", "") for ln in lines))
    titles = [o for o in plan.get("overlays") or [] if o.get("kind") == "title"]
    if len(titles) > 1:
        warn.append("more than one title overlay; one opening title is enough")
    for k, o in enumerate(plan.get("overlays") or []):
        tag = f"overlay {k + 1} ({o.get('kind')})"
        if o.get("kind") not in OVERLAYS:
            err.append(f"{tag}: kind must be one of {OVERLAYS}")
            continue
        if not (isinstance(o.get("start"), (int, float)) and isinstance(o.get("end"), (int, float)) and o["end"] > o["start"]):
            err.append(f"{tag}: needs numeric start < end (seconds in the clip)")
        if o["kind"] == "card":
            body = norm(o.get("text"))
            if not body:
                err.append(f"{tag}: a card needs text")
            elif body not in spoken:
                err.append(f"{tag}: card text must be the words actually spoken (exact, punctuation aside); not found in the transcript")
            if o.get("ref"):
                warn.append(f"{tag}: check the scripture reference '{o['ref']}' by hand (only use one the preacher names or the slide shows)")
        if o["kind"] in ("name", "question"):
            continue
        if o["kind"] == "title":
            if not o.get("main"):
                err.append(f"{tag}: a title needs main")
            warn.append(f"{tag}: title text is not from the speech; confirm the sermon title and preacher's name")
    import moments
    moments.check(plan, spoken + norm("".join(x.get("text", "") for x in plan.get("interpretation") or [])), norm, err, warn)
    return err, warn


# ---- the planning page --------------------------------------------------------------------------------------------
MODE_ZH = {"caption": "字幕", "poster": "大字海报", "stack": "竖排关键字"}
MOTION_ZH = {"whip": "甩入", "drop": "逐字落下", "zoom": "模糊缩放弹入"}


def ts(t):
    t = max(0.0, float(t))
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def plan_md(plan):
    src = os.path.basename(plan.get("video", ""))
    out = [f"# 企划页 · Planning page (Poster Kinetic): {src}", "",
           f"Language {plan.get('language', '?')} · {plan.get('duration', '?')} s · speech-to-text {plan.get('engine', '?')}", ""]
    for m in plan.get("moments") or []:
        out.append(f"- 特别时刻 Moment **{m.get('kind')}** {ts(m['start'])}-{ts(m['end'])}: {m.get('why') or ''}")
    for o in plan.get("overlays") or []:
        if o.get("kind") == "title":
            out.append(f"- 片头标题 Title {ts(o['start'])}-{ts(o['end'])}: **{o.get('main')}** / {o.get('sub') or ''}")
        elif o.get("kind") == "name":
            out.append(f"- 名字标签 Name {ts(o['start'])}-{ts(o['end'])}: {o.get('name')} / {o.get('sub') or ''}")
        elif o.get("kind") == "question":
            out.append(f"- 问题栏 Question {ts(o['start'])}-{ts(o['end'])}: {o.get('text')}")
        else:
            out.append(f"- 经文卡 Card {ts(o['start'])}-{ts(o['end'])}: {o.get('text')}  ({o.get('ref') or 'no reference'})")
    if plan.get("overlays"):
        out.append("")
    has_src = any("src_start" in ln and ln["src_start"] is not None for ln in plan.get("lines", []))
    out += ["| # | " + ("原片 source | " if has_src else "") + "时间 time | 讲话原句 line | 形式 mode | 大字 / 重点 hero / keys | 颜色 colour | 动作 motion | 备注 notes |",
            "|" + "---|" * (9 if has_src else 8)]
    for ln in plan.get("lines", []):
        mode = ln.get("mode") or "caption"
        hero = ln.get("keyword") if mode != "caption" else "、".join(ln.get("keywords") or []) or "-"
        mv = "-" if mode == "caption" else ("竖排 stack" if mode == "stack" else f"{MOTION_ZH.get(ln.get('motion') or 'whip')} {ln.get('motion') or 'whip'}"
                                             + (f" from {ln['from']}" if ln.get("from") else ""))
        notes = []
        if mode != "caption":
            notes.append(f"zone {ln.get('zone') or plan.get('zone_default', 'low')}")
            if ln.get("slant"):
                notes.append("斜体 slant")
            if ln.get("fill") and ln["fill"] != "solid":
                notes.append(f"fill {ln['fill']}" + (f" → {ln.get('color2')}" if ln.get("color2") else ""))
            if ln.get("behind"):
                notes.append("字在人后 behind speaker")
        if ln.get("hero_from") == "interpretation":
            notes.append(f"大字取自传译 hero from the interpreter, on '{ln.get('hero_at') or ''}'")
        if ln.get("gloss"):
            notes.append(f"副字 gloss: {ln['gloss']}")
        if ln.get("transition"):
            notes.append(f"转场 {ln['transition']}")
        if ln.get("note"):
            notes.append(ln["note"])
        src = f"{ts(ln['src_start'])}-{ts(ln['src_end'])} | " if has_src and ln.get("src_start") is not None else ("- | " if has_src else "")
        out.append(f"| {ln.get('id')} | {src}{ts(ln['start'])}-{ts(ln['end'])} | {ln['text']} | {MODE_ZH[mode]} {mode} | {hero} | "
                   f"{(ln.get('color') or ('gold' if mode != 'caption' else '-'))} | {mv} | {'; '.join(notes)} |")
    out += ["", "Rules: the original words, negations and conditions stay; a hero is an exact part of its line; one point per "
            "screen; red only for the one contrast that matters; nothing below y 1400 or over the face.", "",
            "Waiting for the owner's OK before rendering (skip when the owner asked for the video directly)."]
    return "\n".join(out) + "\n"
