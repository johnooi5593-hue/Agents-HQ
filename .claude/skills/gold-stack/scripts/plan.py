"""The planning page (企划页) for Gold Stack.

usage: python plan.py <video> <out/plan.json> [--max-chars 12]          transcribe (CPU faster-whisper, env YS_LANG=zh)
       python plan.py --from-plan <other plan.json> <out/plan.json>    reuse the lines of another style's plan
       python plan.py --md <plan.json>       rewrite plan.md
       python plan.py --check <plan.json>    check the rules
Every line starts as a plain staircase (words build as spoken). The agent picks each line's gold "key" and the designed
moves ("move", "transition", "exit", "flash", "track") and the plan-level "camera" and "close".
"""
import argparse, importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gs  # noqa: E402

FIELDS = {"key": None, "move": None, "transition": None, "exit": None, "note": ""}


def snap_words(video, lines):
    """Speech-to-text often starts a word 0.3-0.5 s before the voice does. Move each word's start later to the first
    10 ms frame where the voice is really there (never earlier, never past its end). Returns how many moved."""
    import subprocess
    import numpy as np
    raw = subprocess.run([gs.cc.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    pcm = np.frombuffer(raw, np.float32)
    if not len(pcm):
        return 0
    hop = 160
    n = len(pcm) // hop
    rms = 20 * np.log10(np.sqrt((pcm[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    thr = max(np.percentile(rms, 20) + 12, np.percentile(rms, 95) - 28)
    moved = 0
    for ln in lines:
        for w in ln.get("words", []):
            i0, i1 = int(w["start"] * 100), int(min(w["start"] + 0.5, w["end"] - 0.05) * 100)
            if i0 >= n or i1 <= i0 or rms[i0:i0 + 3].max() >= thr:
                continue
            hit = np.nonzero(rms[i0:i1] >= thr)[0]
            if len(hit):
                w["start"] = round((i0 + int(hit[0])) / 100, 2); moved += 1
        if ln.get("words"):
            ln["start"] = ln["words"][0]["start"]
    return moved


def write_md(path, plan):
    md = os.path.splitext(path)[0] + ".md"
    with open(md, "w", encoding="utf-8") as f:
        f.write(gs.plan_md(plan))
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--max-chars", type=float, default=12)
    ap.add_argument("--from-plan", default=None); ap.add_argument("--md", default=None); ap.add_argument("--check", default=None)
    a = ap.parse_args()
    if a.md or a.check:
        p = a.md or a.check; plan = gs.load(p); err, warn = gs.check(plan)
        if not err:                                             # the 2 s rule on the frame each move lands (render.py's timeline)
            try:
                spec = importlib.util.spec_from_file_location("gsrender", os.path.join(HERE, "render.py"))
                gsr = importlib.util.module_from_spec(spec); spec.loader.exec_module(gsr)     # (caption-card has a render.py too)
                hits, hw = gsr.move_hits(plan)
                err, warn = gs.check(plan, hits); warn += hw
            except Exception as e:                              # noqa: BLE001  (keep the estimate's result)
                warn.append(f"hit-time check unavailable: {type(e).__name__}: {e}")
        if a.md:
            gs.report(tool="plan", md=write_md(p, plan), errors=err, warnings=warn)
        else:
            gs.report(tool="plan-check", plan=p, ok=not err, errors=err, warnings=warn)
        sys.exit(1 if err else 0)
    base = {"style": "gold-stack", "camera": {"on": True, "face": [0.5, 0.3], "alternate": True}, "close": True}
    if a.from_plan:
        src = gs.load(a.from_plan); out = a.video or a.out
        lines = [dict({k: ln[k] for k in ("id", "start", "end", "text", "words") if k in ln}, **FIELDS) for ln in src.get("lines", [])]
        plan = dict(base, video=src.get("video"), duration=src.get("duration"), engine=src.get("engine"), lines=lines)
        gs.save(out, plan); gs.report(tool="plan", out=out, md=write_md(out, plan), lines=len(lines)); return
    if not (a.video and a.out):
        ap.error("give <video> <out plan.json>, or --from-plan / --md / --check")
    spec = importlib.util.spec_from_file_location("pkplan", os.path.join(gs.cc.PKS, "plan.py"))
    pkplan = importlib.util.module_from_spec(spec); spec.loader.exec_module(pkplan)     # CPU whisper patch + local model
    ysp = gs.cc.pk.ys_plan()
    info = gs.probe(a.video)
    words, lang, engine = ysp.transcribe(a.video)
    if (lang or "").startswith("zh") or lang == "yue":
        for w in words:
            w["t"], _ = ysp.to_simplified(w["t"])
    lines = [dict({"id": i + 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "".join(w["t"] for w in ws).strip(),
                   "words": [{"t": w["t"].strip(), "start": w["start"], "end": w["end"]} for w in ws]}, **FIELDS)
             for i, ws in enumerate(ysp.group(words, a.max_chars))]
    snapped = snap_words(a.video, lines)
    plan = dict(base, video=os.path.abspath(a.video), duration=round(info["duration"], 2), engine=engine, language=lang, lines=lines)
    gs.save(a.out, plan)
    gs.report(tool="plan", out=a.out, md=write_md(a.out, plan), language=lang, lines=len(lines), words_snapped_to_voice=snapped,
              transcript=" / ".join(f"{l['id']}:{l['text']}" for l in lines)[:1500])


if __name__ == "__main__":
    main()
