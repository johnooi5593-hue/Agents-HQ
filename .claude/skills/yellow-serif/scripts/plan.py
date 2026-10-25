"""The planning page (企划页): transcribe a clip and write plan.json (for the agent to edit) and plan.md (for the owner).

usage: python3 .claude/skills/yellow-serif/scripts/plan.py <video> <out/plan.json> [--max-chars 12] [--layout subtitle] [--map cutmap.json]
       python3 .claude/skills/yellow-serif/scripts/plan.py --md <plan.json>       rewrite plan.md after editing plan.json
       python3 .claude/skills/yellow-serif/scripts/plan.py --check <plan.json>    check plan.json against the guide's rules

Speech-to-text: faster-whisper with a multilingual model (env YS_WHISPER_MODEL, default "small"), language auto-detected
or set with env YS_LANG (e.g. zh), word timestamps. Chinese has no spaces, so captions are grouped by characters:
punctuation ends a caption, a pause over 0.6 s ends a caption, and a caption holds at most --max-chars characters
(a Latin letter counts about half). Every line starts as motion "type" with no key words; the agent then edits the plan.
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from common import COMMA, FPS, SENT_END, audio, check, load, plan_md, probe, report, save, width_units  # noqa: E402

ZH_PROMPT = "以下是普通话的句子，使用简体中文。"
TRAD = set("們個來這說時會對為與過還當後點樣開關體實現發經頭將問題麼嗎讓學歡話聽講幾邊見聲總無應從長種結構視頻覺電腦書寫讀選擇內沒裡盤")  # Traditional-only


def to_simplified(s):
    """Traditional -> Simplified when zhconv or opencc is installed; (text, how)."""
    if not any(c in TRAD for c in s):
        return s, "simplified"
    try:
        import zhconv
        return zhconv.convert(s, "zh-cn"), "converted with zhconv"
    except ImportError:
        pass
    try:
        import opencc
        return opencc.OpenCC("t2s").convert(s), "converted with opencc"
    except ImportError:
        return s, "Traditional characters left as is (pip install zhconv to convert)"


def transcribe(path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is needed for this skill (multilingual speech-to-text): python3 -m pip install faster-whisper")
    name = os.environ.get("YS_WHISPER_MODEL", "small")
    model = WhisperModel(name, compute_type="int8")
    pcm = audio(path, 16000)                       # decoded by ffmpeg: no PyAV needed
    lang = os.environ.get("YS_LANG") or None
    kw = dict(word_timestamps=True, vad_filter=True, beam_size=5)
    segs, info = model.transcribe(pcm, language=lang, initial_prompt=ZH_PROMPT if (lang or "").startswith("zh") else None, **kw)
    if not lang and info.language == "zh":         # detected Chinese: ask for Simplified with a Simplified prompt
        segs, info = model.transcribe(pcm, language="zh", initial_prompt=ZH_PROMPT, **kw)
    words = [{"t": w.word, "start": round(w.start, 3), "end": round(w.end, 3)} for s in segs for w in (s.words or []) if w.word.strip()]
    return words, info.language, f"faster-whisper {name}"


def _txt(ws):
    return "".join(w["t"] for w in ws).strip()


def _latin(c):
    return c.isascii() and c.isalnum()


BREAK_BEFORE = set("像是在但就而所因如可然还也都又才把被让给从和与或先再即")   # a clause often starts here
BREAK_AFTER = set("的了吗呢吧啊么着过")                                  # a clause often ends here
CUES = ("第一", "第二", "第三", "首先", "其次", "最后", "记住", "所以", "但是", "然后", "总之", "其实", "今天")  # a new point starts


def _word_ends(text):
    """Char offsets where a Chinese word ends, from jieba when it is installed (optional), else None."""
    try:
        import jieba
    except ImportError:
        return None
    ends, p = set(), 0
    for tok in jieba.cut(text):
        p += len(tok); ends.add(p)
    return ends


def _split(ws, max_chars):
    """Split one sentence into captions of at most max_chars. A comma always wins; otherwise a pause, a clause word
    (像, 是, 但, 就 ... before, 的, 了 ... after) and even halves decide. Never inside a Latin word (whisper may give
    "PP" + "T") and, with jieba installed, never inside a Chinese word."""
    inner_commas = sum(1 for w in ws[:-1] if w["t"].strip()[-1:] in COMMA)
    if (width_units(_txt(ws)) <= max_chars and inner_commas < 2) or len(ws) < 2:     # at most two clauses per caption
        return [ws]
    full = "".join(w["t"] for w in ws); ends = _word_ends(full); off = 0
    best = None
    for k in range(1, len(ws)):
        off += len(ws[k - 1]["t"])
        a, b = _txt(ws[:k]), _txt(ws[k:])
        if not a or not b or (_latin(a[-1]) and _latin(b[0])):
            continue
        wl, wr = width_units(a), width_units(b)
        if wl < 2 or wr < 2:
            continue
        comma = a[-1] in COMMA
        score = abs(wl - wr) * 0.5 - (100 if comma else 0) - (1 if ws[k]["start"] - ws[k - 1]["end"] > 0.25 else 0)
        score -= 1.5 if (b[0] in BREAK_BEFORE or a[-1] in BREAK_AFTER) else 0
        if ends is not None and not comma and off not in ends:
            score += 6
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:
        return [ws]
    return _split(ws[:best[1]], max_chars) + _split(ws[best[1]:], max_chars)


def group(words, max_chars):
    """Words -> caption lines, by meaning: a sentence end or a pause over 0.6 s closes a sentence; a sentence longer
    than max_chars is split at a comma or into even halves."""
    sents, cur = [], []
    for i, w in enumerate(words):
        ahead = "".join(x["t"].strip() for x in words[i:i + 3])       # whisper may split 记住 into 记 + 住
        cue = any(ahead.startswith(c) for c in CUES)
        if cur and (w["start"] - cur[-1]["end"] > 0.6 or (cue and cur[-1]["t"].strip()[-1:] in COMMA)):
            sents.append(cur); cur = []
        cur.append(w)
        if w["t"].strip()[-1:] in SENT_END + ".":
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    return [part for s in sents for part in _split(s, max_chars)]


def src_time(t, cmap):
    """Cut time -> source time, from cut_topics.py's cutmap.json."""
    for s0, s1, c0 in cmap["segments"]:
        if c0 - 1e-3 <= t <= c0 + (s1 - s0) + 1e-3:
            return round(s0 + (t - c0), 2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--max-chars", type=float, default=12, help="most characters in one caption (two rows at most)")
    ap.add_argument("--layout", default="subtitle", choices=["subtitle", "fullscreen", "darken", "torn"], help="layout_default")
    ap.add_argument("--map", default=None, help="cutmap.json from cut_topics.py: records source timestamps per line")
    ap.add_argument("--md", default=None, metavar="PLAN", help="only rewrite plan.md from an edited plan.json")
    ap.add_argument("--check", default=None, metavar="PLAN", help="only check an edited plan.json")
    a = ap.parse_args()

    if a.md or a.check:
        path = a.md or a.check; plan = load(path); err, warn = check(plan)
        if a.md:
            md = os.path.splitext(path)[0] + ".md"
            with open(md, "w", encoding="utf-8") as f:
                f.write(plan_md(plan))
            report(tool="plan", md=md, errors=err, warnings=warn)
        else:
            report(tool="plan-check", plan=path, ok=not err, errors=err, warnings=warn)
        sys.exit(1 if err else 0)
    if not (a.video and a.out):
        ap.error("give <video> <out plan.json>, or --md / --check <plan.json>")

    import fonts
    info = probe(a.video)
    words, lang, engine = transcribe(a.video)
    zh = (lang or "").startswith("zh")
    conv = None
    if zh:
        hows = set()
        for w in words:
            w["t"], how = to_simplified(w["t"]); hows.add(how)
        conv = next((h for h in hows if h != "simplified"), "simplified")
    cmap = load(a.map) if a.map else None
    lines = []
    for i, ws in enumerate(group(words, a.max_chars)):
        ln = {"id": i + 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["t"] for w in ws).strip(),
              "words": [{"t": w["t"].strip(), "start": w["start"], "end": w["end"]} for w in ws],
              "keywords": [], "motion": "type", "shine": False, "layout": None, "standalone": None, "standalone_font": None,
              "transition": None, "head": None, "note": ""}
        if cmap:
            ln["src_start"], ln["src_end"] = src_time(ln["start"], cmap), src_time(ln["end"], cmap)
        lines.append(ln)
    f = fonts.resolve()
    plan = {"video": os.path.abspath(a.video), "fps": FPS, "width": info["width"], "height": info["height"], "duration": round(info["duration"], 2),
            "language": lang, "engine": engine, "font_main": f["serif"]["name"] + (" Black" if f["serif"]["weight"] else ""),
            "font_brush": f["brush"]["name"], "layout_default": a.layout, "size": "1080x1920", "topics": (cmap or {}).get("topics", []),
            "source": (cmap or {}).get("source"), "lines": lines}
    save(a.out, plan)
    md = os.path.splitext(a.out)[0] + ".md"
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(plan_md(plan))
    report(tool="plan", out=a.out, md=md, language=lang, engine=engine, chinese_script=conv, lines=len(lines), words=len(words),
           fonts=fonts.used(), transcript=" / ".join(ln["text"] for ln in lines)[:900])


if __name__ == "__main__":
    main()
