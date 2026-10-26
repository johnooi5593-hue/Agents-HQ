"""The planning page (企划页) for Poster Kinetic: transcribe a clip, write plan.json (for the agent to edit) and plan.md.

usage: python plan.py <video> <out/plan.json> [--max-chars 12] [--map cutmap.json] [--zone low]
       python plan.py --md <plan.json>                rewrite plan.md after editing plan.json
       python plan.py --check <plan.json>             check plan.json against the guide's rules
       python plan.py --merge <plan.json> <id> <id2>  merge lines id..id2 into one (for a verse card or a short poster)
       python plan.py --split <plan.json> <id> <text-of-first-part>   split a line where the first part ends

Speech-to-text and caption grouping are the yellow-serif skill's (faster-whisper, env YS_WHISPER_MODEL default "small",
env YS_LANG e.g. zh or yue, Simplified Chinese out). Every line starts as an ordinary caption; the agent then picks the
few lines that become posters, stacks, a title or a scripture card.
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
# This PC has an NVIDIA card but no CUDA runtime (cublas64_12.dll), so faster-whisper must run on the CPU unless
# PK_CUDA=1. Use the local large-v3-turbo model when no model is named, so nothing is downloaded.
if os.environ.get("PK_CUDA") != "1":
    try:
        import faster_whisper
        _WM = faster_whisper.WhisperModel

        class _CPUModel(_WM):
            def __init__(self, *args, **kw):
                kw.setdefault("device", "cpu")
                super().__init__(*args, **kw)
        faster_whisper.WhisperModel = _CPUModel
    except ImportError:
        pass
_LOCAL = "D:/AI OFFICE/tools/models/whisper-large-v3-turbo"
if not os.environ.get("YS_WHISPER_MODEL") and os.path.isdir(_LOCAL):
    os.environ["YS_WHISPER_MODEL"] = _LOCAL
from pk import FPS, check, load, plan_md, probe, report, save  # noqa: E402


def blank_line(i, ws, cmap, ysp):
    ln = {"id": i, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["t"] for w in ws).strip(),
          "words": [{"t": w["t"].strip(), "start": w["start"], "end": w["end"]} for w in ws],
          "mode": "caption", "keywords": [], "keyword": None, "color": None, "motion": None, "from": None, "zone": None,
          "slant": False, "fill": None, "color2": None, "behind": False, "transition": None, "note": ""}
    if cmap:
        ln["src_start"], ln["src_end"] = ysp.src_time(ln["start"], cmap), ysp.src_time(ln["end"], cmap)
    return ln


def renumber(plan):
    for i, ln in enumerate(plan["lines"]):
        ln["id"] = i + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--max-chars", type=float, default=12)
    ap.add_argument("--map", default=None)
    ap.add_argument("--zone", default="low", choices=["top", "middle", "low"], help="zone_default for heroes")
    ap.add_argument("--md", default=None, metavar="PLAN")
    ap.add_argument("--check", default=None, metavar="PLAN")
    ap.add_argument("--merge", nargs=3, default=None, metavar=("PLAN", "ID", "ID2"))
    ap.add_argument("--split", nargs=3, default=None, metavar=("PLAN", "ID", "FIRST"))
    a = ap.parse_args()

    if a.merge or a.split:
        path = (a.merge or a.split)[0]
        plan = load(path); L = plan["lines"]
        if a.merge:
            i0, i1 = int(a.merge[1]), int(a.merge[2])
            grp = [ln for ln in L if i0 <= ln["id"] <= i1]
            if len(grp) < 2:
                sys.exit("merge needs two or more line ids")
            m = dict(grp[0]); m["text"] = "".join(g["text"] for g in grp); m["words"] = [w for g in grp for w in g["words"]]
            m["end"] = grp[-1]["end"]
            if "src_end" in grp[-1]:
                m["src_end"] = grp[-1]["src_end"]
            plan["lines"] = [ln for ln in L if ln["id"] < i0] + [m] + [ln for ln in L if ln["id"] > i1]
        else:
            lid, first = int(a.split[1]), a.split[2]
            ln = next(x for x in L if x["id"] == lid)
            if not ln["text"].startswith(first) or first == ln["text"]:
                sys.exit(f"'{first}' must be the beginning of line {lid}: '{ln['text']}'")
            acc, k = "", 0
            while k < len(ln["words"]) and len(acc) < len(first):
                acc += ln["words"][k]["t"]; k += 1
            if acc != first:
                sys.exit(f"split must fall between words; the words are: {' | '.join(w['t'] for w in ln['words'])}")
            b = dict(ln); a1 = dict(ln)
            a1["text"], a1["words"], a1["end"] = first, ln["words"][:k], ln["words"][k - 1]["end"]
            b["text"], b["words"], b["start"] = ln["text"][len(first):], ln["words"][k:], ln["words"][k]["start"]
            b["keywords"], b["keyword"], b["mode"] = [], None, "caption"
            a1["keywords"] = [x for x in a1.get("keywords") or [] if x in first]
            if a1.get("keyword") and a1["keyword"] not in first:
                a1["keyword"], a1["mode"] = None, "caption"
            i = L.index(ln); plan["lines"] = L[:i] + [a1, b] + L[i + 1:]
        renumber(plan); save(path, plan)
        with open(os.path.splitext(path)[0] + ".md", "w", encoding="utf-8") as f:
            f.write(plan_md(plan))
        err, warn = check(plan)
        report(tool="plan-edit", plan=path, lines=len(plan["lines"]), errors=err, warnings=warn)
        return
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
        ap.error("give <video> <out plan.json>, or --md / --check / --merge / --split")

    from pk import ys_plan
    ysp = ys_plan()
    info = probe(a.video)
    words, lang, engine = ysp.transcribe(a.video)
    conv = None
    if (lang or "").startswith("zh") or (lang or "") == "yue":
        hows = set()
        for w in words:
            w["t"], how = ysp.to_simplified(w["t"]); hows.add(how)
        conv = next((h for h in hows if h != "simplified"), "simplified")
    cmap = load(a.map) if a.map else None
    lines = [blank_line(i + 1, ws, cmap, ysp) for i, ws in enumerate(ysp.group(words, a.max_chars))]
    import pfonts
    plan = {"style": "poster-kinetic", "video": os.path.abspath(a.video), "fps": FPS, "width": info["width"], "height": info["height"],
            "duration": round(info["duration"], 2), "language": lang, "engine": engine, "zone_default": a.zone,
            "fonts": {k: (v or {}).get("name") for k, v in pfonts.resolve().items()},
            "topics": (cmap or {}).get("topics", []), "source": (cmap or {}).get("source"), "overlays": [], "lines": lines}
    save(a.out, plan)
    md = os.path.splitext(a.out)[0] + ".md"
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(plan_md(plan))
    report(tool="plan", out=a.out, md=md, language=lang, engine=engine, chinese_script=conv, lines=len(lines), words=len(words),
           transcript=" / ".join(f"{ln['id']}:{ln['text']}" for ln in lines)[:1500])


if __name__ == "__main__":
    main()
