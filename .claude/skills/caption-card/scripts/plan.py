"""The planning page (企划页) for Caption Card: transcribe a clip (or take the lines of an existing plan), write plan.json
for the agent to edit and plan.md for the owner.

usage: python plan.py <video> <out/plan.json> [--max-chars 12]          transcribe (faster-whisper on the CPU, env YS_LANG=zh)
       python plan.py --from-plan <other plan.json> <out/plan.json>    reuse the lines and word times of a poster-kinetic plan
       python plan.py --md <plan.json>                                 rewrite plan.md after editing
       python plan.py --check <plan.json>                              check the rules
Every line starts as "kind": "card". The agent then picks 3-4 lines a minute for big type (hook, number, writeon, punch).
"""
import argparse, importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cc  # noqa: E402

FIELDS = {"kind": "card", "color": None, "rows": None, "key_row": None, "number": None, "label": None, "unit": None,
          "phrase": None, "sub": None, "y": None, "transition": None, "why": "", "note": ""}


def write_md(path, plan):
    md = os.path.splitext(path)[0] + ".md"
    with open(md, "w", encoding="utf-8") as f:
        f.write(cc.plan_md(plan))
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--max-chars", type=float, default=12)
    ap.add_argument("--from-plan", default=None); ap.add_argument("--md", default=None); ap.add_argument("--check", default=None)
    a = ap.parse_args()
    if a.md or a.check:
        p = a.md or a.check; plan = cc.load(p); err, warn = cc.check(plan)
        if a.md:
            cc.report(tool="plan", md=write_md(p, plan), errors=err, warnings=warn)
        else:
            cc.report(tool="plan-check", plan=p, ok=not err, errors=err, warnings=warn)
        sys.exit(1 if err else 0)
    if a.from_plan:
        src = cc.load(a.from_plan); out = a.video or a.out
        lines = [dict({k: ln[k] for k in ("id", "start", "end", "text", "words") if k in ln}, **FIELDS) for ln in src.get("lines", [])]
        plan = {"style": "caption-card", "video": src.get("video"), "duration": src.get("duration"), "engine": src.get("engine"),
                "language": src.get("language"), "card": dict(cc.CARD), "card_y": 0.51, "lines": lines}
        cc.save(out, plan)
        cc.report(tool="plan", out=out, md=write_md(out, plan), lines=len(lines), from_plan=a.from_plan); return
    if not (a.video and a.out):
        ap.error("give <video> <out plan.json>, or --from-plan / --md / --check")
    spec = importlib.util.spec_from_file_location("pkplan", os.path.join(cc.PKS, "plan.py"))
    pkplan = importlib.util.module_from_spec(spec); spec.loader.exec_module(pkplan)     # CPU whisper patch + local model
    ysp = cc.pk.ys_plan()
    info = cc.probe(a.video)
    words, lang, engine = ysp.transcribe(a.video)
    if (lang or "").startswith("zh") or lang == "yue":
        for w in words:
            w["t"], _ = ysp.to_simplified(w["t"])
    lines = []
    for i, ws in enumerate(ysp.group(words, a.max_chars)):
        lines.append(dict({"id": i + 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["t"] for w in ws).strip(),
                           "words": [{"t": w["t"].strip(), "start": w["start"], "end": w["end"]} for w in ws]}, **FIELDS))
    plan = {"style": "caption-card", "video": os.path.abspath(a.video), "duration": round(info["duration"], 2), "engine": engine,
            "language": lang, "card": dict(cc.CARD), "card_y": 0.51, "lines": lines}
    cc.save(a.out, plan)
    cc.report(tool="plan", out=a.out, md=write_md(a.out, plan), language=lang, lines=len(lines),
              transcript=" / ".join(f"{l['id']}:{l['text']}" for l in lines)[:1500])


if __name__ == "__main__":
    main()
