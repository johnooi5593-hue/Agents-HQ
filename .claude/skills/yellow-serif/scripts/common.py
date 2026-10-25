"""Shared pieces of the Yellow Serif Kinetic scripts: the guide's numbers, text units, timing, plan checks and plan.md.

The ffmpeg helpers (FFMPEG, probe, audio, run, report, speech_segments) come from the reel skill's media.py, so both
skills decode and report the same way.
"""
import difflib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REEL = os.path.join(os.path.dirname(SKILL), "reel", "scripts")
sys.path.insert(0, HERE)
sys.path.insert(1, REEL)
from media import FFMPEG, audio, probe, report, run, speech_segments  # noqa: E402,F401  (reel skill)

# ---- the guide, in numbers (1080 x 1920 at 30 fps) --------------------------------------------------------------
FPS = 30
WHITE, YELLOW, BLACK = (255, 255, 255), (0xFB, 0xC2, 0x38), (0x08, 0x09, 0x0B)
GREY, GREY_ALPHA = (0x8A, 0x8A, 0x8A), 0.60          # the background sentence behind a burst (photo 2)
SHINE_RGB = (255, 250, 222)                          # white to pale yellow band
BASE_PX = 84                                         # normal captions 74-96 px at 1080 wide
KEY_SCALE = 1.08                                     # inline key words 1.0-1.15x
BURST_SCALE = 1.8                                    # standalone big words 1.5-2.1x
SIDE, BOTTOM = 0.08, 0.15                            # side margins 8%, bottom margin 15%
POP = 0.22                                           # pop 0.18-0.28 s: 85% -> 108% -> 100%
BURST = 0.28                                         # burst 0.22-0.35 s: big first, then settle
BURST_HOLD = 0.6                                     # reading time after a burst lands
SHINE = 0.35                                         # shine 0.25-0.45 s
FLASH = 0.14                                         # flash 0.10-0.18 s
LEAK = 0.8                                           # light-leak transition 0.6-1.0 s
MOTIONS = ("type", "pop", "burst", "flash")
LAYOUTS = ("subtitle", "fullscreen", "darken", "torn")

SENT_END = "。！？!?；;…"
COMMA = "，,、：:"
DROP = "，。、；：,.;:…·“”\"‘’「」『』"             # not shown in burned-in captions (a comma becomes a line break or a gap)
KEEP_PUNCT = "？！?!%《》（）()"
NEG = "不没别非无未莫勿"
LATIN = re.compile(r"[A-Za-z0-9%+\-'.$€£¥@#&]")


def is_cjk(c):
    o = ord(c)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F or 0x20000 <= o <= 0x2FFFF


def has_cjk(s):
    return any(is_cjk(c) for c in s)


def width_units(s):
    """Rough display width in CJK characters: a CJK character is 1, a Latin letter or digit about 0.55, a space 0.3."""
    return sum(1 if is_cjk(c) else 0.3 if c.isspace() else 0 if c in DROP else 0.55 for c in s)


def units(text):
    """Split a caption into display units: one per CJK character, one per Latin word or number, gaps for spaces and
    commas. Each unit: {"text", "idx": [char indexes in text], "gap": bool, "brk": bool (a comma: preferred row break)}."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            if out and not out[-1]["gap"]:
                out.append({"text": " ", "idx": [i], "gap": True, "brk": False})
            i += 1
        elif c in DROP:
            if c == "." and 0 < i < n - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
                out[-1]["text"] += c; out[-1]["idx"].append(i); i += 1; continue
            if c in COMMA + SENT_END + "." and out and not out[-1]["gap"]:
                out.append({"text": " ", "idx": [i], "gap": True, "brk": True})
            elif out and out[-1]["gap"] and c in COMMA + SENT_END + ".":
                out[-1]["brk"] = True
            i += 1
        elif LATIN.match(c) and not is_cjk(c):
            j = i
            while j < n and LATIN.match(text[j]) and not (text[j] == "." and not (j + 1 < n and text[j + 1].isdigit())):
                j += 1
            j = max(j, i + 1)
            out.append({"text": text[i:j], "idx": list(range(i, j)), "gap": False, "brk": False}); i = j
        else:
            out.append({"text": c, "idx": [i], "gap": False, "brk": False}); i += 1
    while out and out[-1]["gap"]:
        out.pop()
    while out and out[0]["gap"]:
        out.pop(0)
    return out


def display(text):
    """The caption as it is burned in: punctuation dropped, commas as a space."""
    return "".join(u["text"] for u in units(text)).strip()


def char_times(line, fps=FPS):
    """Time each character of line["text"] may appear: never before its word is spoken, 2-3 frames per character
    inside a word. Characters are matched to the words by difflib, so a corrected text still lines up."""
    text, words = line["text"], line.get("words") or []
    src, times = [], []
    for w in words:
        cs = [c for c in w["t"] if not c.isspace()]
        if not cs:
            continue
        step = min(3 / fps, max(2 / fps, (w["end"] - w["start"]) / len(cs)))
        for k, c in enumerate(cs):
            src.append(c); times.append(w["start"] + k * step)
    out = [None] * len(text)
    sm = difflib.SequenceMatcher(None, "".join(src), text, autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal":
            for k in range(b1 - b0):
                out[b0 + k] = times[a0 + k]
    s, e = line["start"], line["end"]
    known = [(i, t) for i, t in enumerate(out) if t is not None]
    if not known:      # no word timing at all: spread the line over its time
        return [s + (e - s) * i / max(1, len(text)) for i in range(len(text))]
    for i in range(len(text)):
        if out[i] is None:
            prev = max((k for k in known if k[0] < i), default=(-1, s), key=lambda k: k[0])
            nxt = min((k for k in known if k[0] > i), default=(len(text), max(e, prev[1])), key=lambda k: k[0])
            f = (i - prev[0]) / max(1, nxt[0] - prev[0])
            out[i] = prev[1] + (nxt[1] - prev[1]) * f
    for i in range(1, len(out)):     # never earlier than the character before it
        out[i] = max(out[i], out[i - 1])
    return out


def find_all(text, kws):
    """Char indexes covered by each key phrase (first occurrence)."""
    cover = {}
    for k, kw in enumerate(kws or []):
        p = text.find(kw)
        if p >= 0:
            for i in range(p, p + len(kw)):
                cover.setdefault(i, k)
    return cover


def check(plan):
    """The guide's rules as errors (must fix) and warnings (look again)."""
    err, warn = [], []
    bursts = []
    lines = plan.get("lines", [])
    for i, ln in enumerate(lines):
        tag = f"line {ln.get('id', i + 1)}"
        t = ln.get("text", "")
        if ln.get("motion", "type") not in MOTIONS:
            err.append(f"{tag}: motion must be one of {MOTIONS}")
        if (ln.get("layout") or plan.get("layout_default", "subtitle")) not in LAYOUTS:
            err.append(f"{tag}: layout must be one of {LAYOUTS} or null")
        kws = ln.get("keywords") or []
        if len(kws) > 2:
            err.append(f"{tag}: {len(kws)} keywords; at most 2 per line")
        for kw in kws:
            if not kw or kw not in t:
                err.append(f"{tag}: keyword '{kw}' is not an exact part of the line '{t}'")
            elif t.find(kw) > 0 and (t[t.find(kw) - 1] in NEG or t[max(0, t.find(kw) - 2):t.find(kw)] in ("不是", "没有")) and kw[0] not in NEG:
                warn.append(f"{tag}: keyword '{kw}' leaves out the negation before it; emphasise the whole phrase so the meaning stays")
        sa = ln.get("standalone")
        if sa and sa not in t:
            err.append(f"{tag}: standalone '{sa}' is not an exact part of the line '{t}'")
        if ln.get("motion") == "burst":
            bursts.append(ln.get("start", 0))
            if sa and width_units(sa) > 6:
                warn.append(f"{tag}: standalone phrase '{sa}' is long; keep big words to a short phrase (2-6 characters)")
        if ln.get("motion") == "flash" and width_units(display(t)) > 8:
            warn.append(f"{tag}: flash is for short cues; this line is {width_units(display(t)):.0f} characters")
        if ln.get("motion") == "pop" and not kws and not sa and ln.get("layout") != "darken" and width_units(display(t)) > 6:
            warn.append(f"{tag}: pop without keywords pops the whole line; pick the key word instead")
        if ln.get("motion") == "flash" and i and lines[i - 1].get("motion") == "flash":
            warn.append(f"{tag}: two flashes in a row; flash must not flicker repeatedly")
        if ln.get("transition") not in (None, "", "leak"):
            err.append(f"{tag}: transition must be null or \"leak\"")
        if i and ln.get("start", 0) < lines[i - 1].get("end", 0) - 0.05:
            warn.append(f"{tag}: starts before the line before it ends")
    for a, b in zip(bursts, bursts[1:]):
        if b - a < 15:
            warn.append(f"bursts at {a:.1f}s and {b:.1f}s are less than 15 s apart; use bursts for a few key conclusions only")
    shines = [ln for ln in lines if ln.get("shine")]
    if lines and len(shines) > max(1, len(lines) // 4):
        warn.append(f"{len(shines)} shines in {len(lines)} lines; shine only where a word needs one more beat")
    return err, warn


MOTION_ZH = {"type": "打字", "pop": "轻弹", "burst": "爆点放大", "flash": "闪现"}
LAYOUT_ZH = {"subtitle": "字幕（保留人物）", "fullscreen": "全屏文字（黑底网格）", "darken": "人物压暗+竖排黄字", "torn": "撕纸边框"}


def ts(t):
    t = max(0.0, float(t)); return f"{int(t // 60):02d}:{t % 60:05.2f}"


def plan_md(plan):
    """The planning page (企划页) as Markdown: one row per sentence."""
    src = os.path.basename(plan.get("video", ""))
    out = [f"# 企划页 · Planning page: {src}", "",
           f"Language {plan.get('language', '?')} · {plan.get('width')}x{plan.get('height')} · {plan.get('fps')} fps · "
           f"fonts: {plan.get('font_main')} / {plan.get('font_brush')} · default layout: {plan.get('layout_default')}", ""]
    for tp in plan.get("topics") or []:
        out.append(f"- Topic **{tp.get('name')}**: source {ts(tp.get('start', 0))}-{ts(tp.get('end', 0))} {tp.get('why', '')}")
    if plan.get("topics"):
        out.append("")
    has_src = any("src_start" in ln for ln in plan.get("lines", []))
    head = "| # | 原片时间 source | 字幕时间 caption |" if has_src else "| # | 时间 time |"
    out += [head + " 讲话原句 original line | 重点词 key words | 主要动作 motion | 画面与备注 picture and notes |",
            "|" + "---|" * (8 if has_src else 7)]
    for ln in plan.get("lines", []):
        mv = MOTION_ZH.get(ln.get("motion", "type"), ln.get("motion")) + f" {ln.get('motion', 'type')}"
        if ln.get("shine"):
            mv += " + 扫光 shine"
        notes = [LAYOUT_ZH.get(ln.get("layout") or plan.get("layout_default", "subtitle"), "")]
        if ln.get("standalone"):
            notes.append(f"独立大字 standalone: {ln['standalone']} ({ln.get('standalone_font') or 'brush'})")
        if ln.get("transition") == "leak":
            notes.append("漏光转场 light-leak transition in")
        if ln.get("head"):
            h = ln["head"]; notes.append(f"字母 head: {h.get('big', '')} {h.get('word', '')} {h.get('gloss', '')}")
        if ln.get("note"):
            notes.append(ln["note"])
        tcell = f"{ts(ln['start'])}-{ts(ln['end'])}"
        lead = f"| {ln.get('id')} | {ts(ln['src_start'])}-{ts(ln['src_end'])} | {tcell} |" if has_src else f"| {ln.get('id')} | {tcell} |"
        out.append(f"{lead} {ln['text']} | {'、'.join(ln.get('keywords') or []) or '-'} | {mv} | {'; '.join(n for n in notes if n)} |")
    out += ["", "Rules: keep the original words, negations and conditions; key words are exact parts of the line; "
            "1-2 key words per line; few bursts; shine only after the text is readable; flash only for short cues.",
            "", "Waiting for the owner's OK before rendering."]
    return "\n".join(out) + "\n"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
