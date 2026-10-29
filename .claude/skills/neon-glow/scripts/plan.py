"""The planning page (企划页) for Neon Glow.

usage: python plan.py <video> <out/plan.json> [--max-chars 12]          transcribe (CPU faster-whisper, env YS_LANG=zh)
       python plan.py --from-plan <other plan.json> <out/plan.json>    reuse the lines of a poster-kinetic / caption-card plan
       python plan.py --md <plan.json>       rewrite plan.md
       python plan.py --check <plan.json>    check the rules
Every line starts as a chrome typed line. The agent picks the lines that get a neon word ("keyword", optional "lead",
"over", "layout": "number"), plus optional transitions, B-roll windows and a chat bubble.
"""
import argparse, importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ng  # noqa: E402

FIELDS = {"keyword": None, "lead": None, "over": None, "layout": None, "transition": None, "note": ""}


def write_md(path, plan):
    md = os.path.splitext(path)[0] + ".md"
    with open(md, "w", encoding="utf-8") as f:
        f.write(ng.plan_md(plan))
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--max-chars", type=float, default=12)
    ap.add_argument("--from-plan", default=None); ap.add_argument("--md", default=None); ap.add_argument("--check", default=None)
    a = ap.parse_args()
    if a.md or a.check:
        p = a.md or a.check; plan = ng.load(p); err, warn = ng.check(plan)
        if a.md:
            ng.report(tool="plan", md=write_md(p, plan), errors=err, warnings=warn)
        else:
            ng.report(tool="plan-check", plan=p, ok=not err, errors=err, warnings=warn)
        sys.exit(1 if err else 0)
    if a.from_plan:
        src = ng.load(a.from_plan); out = a.video or a.out
        lines = [dict({k: ln[k] for k in ("id", "start", "end", "text", "words") if k in ln}, **FIELDS) for ln in src.get("lines", [])]
        plan = {"style": "neon-glow", "video": src.get("video"), "duration": src.get("duration"), "engine": src.get("engine"),
                "overlays": [], "moments": [], "lines": lines}
        ng.save(out, plan); ng.report(tool="plan", out=out, md=write_md(out, plan), lines=len(lines)); return
    if not (a.video and a.out):
        ap.error("give <video> <out plan.json>, or --from-plan / --md / --check")
    spec = importlib.util.spec_from_file_location("pkplan", os.path.join(ng.cc.PKS, "plan.py"))
    pkplan = importlib.util.module_from_spec(spec); spec.loader.exec_module(pkplan)     # CPU whisper patch + local model
    ysp = ng.cc.pk.ys_plan()
    info = ng.probe(a.video)
    words, lang, engine = ysp.transcribe(a.video)
    if (lang or "").startswith("zh") or lang == "yue":
        for w in words:
            w["t"], _ = ysp.to_simplified(w["t"])
    lines = [dict({"id": i + 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["t"] for w in ws).strip(),
                   "words": [{"t": w["t"].strip(), "start": w["start"], "end": w["end"]} for w in ws]}, **FIELDS)
             for i, ws in enumerate(ysp.group(words, a.max_chars))]
    plan = {"style": "neon-glow", "video": os.path.abspath(a.video), "duration": round(info["duration"], 2), "engine": engine,
            "language": lang, "overlays": [], "moments": [], "lines": lines}
    ng.save(a.out, plan)
    ng.report(tool="plan", out=a.out, md=write_md(a.out, plan), language=lang, lines=len(lines),
              transcript=" / ".join(f"{l['id']}:{l['text']}" for l in lines)[:1500])


if __name__ == "__main__":
    main()
