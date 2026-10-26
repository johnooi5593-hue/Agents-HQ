"""Long video -> one clip per chosen topic (about 45-60 s each), pauses and filler sounds removed, source timestamps kept.

usage: python3 .claude/skills/yellow-serif/scripts/cut_topics.py <long video> <topics.json> <out folder> [--pause 0.45] [--max 60] [--keep-fillers]

topics.json (or a plan.json with a "topics" list), source times in seconds:
  {"topics": [{"name": "two-structures", "start": 312.4, "end": 371.0, "why": "..."},
              {"name": "give-reasons",   "start": 845.0, "end": 902.5, "why": "..."}]}
For each topic it writes <out folder>/<name>/cut.mp4 (original framing, 30 fps, loudness -14 LUFS, like the reel skill's
cut.py) and <out folder>/<name>/cutmap.json: which source ranges were kept and where they sit in the cut. Then run
plan.py on the cut with --map cutmap.json so the planning page records the source timestamp of every line.
The pause detection, padding and merge rules are the reel skill's (media.speech_segments, cut.py's --pause and --pad).
Like cut.py, a phrase that is only filler sounds (um, uh, ah, oh; 嗯, 呃, 啊) is dropped unless --keep-fillers is given.
"""
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from common import FPS, drop_fillers, load, probe, report, run, save, speech_segments  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("topics"); ap.add_argument("outdir")
ap.add_argument("--pause", type=float, default=0.45, help="cut pauses longer than this (s)")
ap.add_argument("--pad", type=float, default=0.12, help="breathing room kept around each phrase (s)")
ap.add_argument("--max", type=float, default=60, help="longest clip in seconds (the guide: about 45-60 s)")
ap.add_argument("--keep-fillers", action="store_true", help="keep phrases that are only um/uh/ah/oh (嗯/呃/啊)")
a = ap.parse_args()

info = probe(a.src)
topics = load(a.topics).get("topics") or []
if not topics:
    sys.exit("no topics: write {\"topics\": [{\"name\", \"start\", \"end\"}, ...]} with source times in seconds")
results = []
for tp in topics:
    name = re.sub(r"[^\w\-]+", "-", str(tp.get("name") or f"topic-{len(results) + 1}")).strip("-") or f"topic-{len(results) + 1}"
    s0, s1 = max(0.0, float(tp["start"])), min(info["duration"], float(tp["end"]))
    d = os.path.join(a.outdir, name); os.makedirs(d, exist_ok=True)
    raw = os.path.join(d, "range.mp4")                       # the topic's range, re-encoded so the cut is frame exact
    run(["-ss", f"{s0:.3f}", "-to", f"{s1:.3f}", "-i", a.src, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", raw])
    rdur = probe(raw)["duration"]
    segs, fillers, why = speech_segments(raw, min_silence=a.pause), [], None
    if not a.keep_fillers:
        segs, fillers, why = drop_fillers(raw, segs)
    keep = []
    for s, e in segs:                                         # same rules as reel/cut.py: pad, merge, cap
        s, e = max(0.0, s - a.pad), min(rdur, e + a.pad)
        if keep and s <= keep[-1][1]:
            keep[-1] = (keep[-1][0], e)
        else:
            keep.append((s, e))
    segs, total = [], 0.0
    for s, e in keep:
        if total + (e - s) > a.max:
            e = s + (a.max - total)
        if e - s > 0.2:
            segs.append((s, e, total)); total += e - s
        if total >= a.max - 0.05:
            break
    parts = "".join(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS[a{i}];" for i, (s, e, _) in enumerate(segs))
    cat = "".join(f"[v{i}][a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][ca];[ca]loudnorm=I=-14:TP=-1.5[a]"
    out = os.path.join(d, "cut.mp4")
    run(["-i", raw, "-filter_complex", parts + cat, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])
    cmap = {"source": os.path.abspath(a.src), "topic": tp, "topics": [dict(tp, cut=out)],
            "segments": [[round(s0 + s, 3), round(s0 + e, 3), round(c, 3)] for s, e, c in segs]}
    save(os.path.join(d, "cutmap.json"), cmap)
    results.append({"name": name, "cut": out, "cutmap": os.path.join(d, "cutmap.json"), "source": f"{s0:.1f}-{s1:.1f}s",
                    "seconds": round(total, 1), "removed": round((s1 - s0) - total, 1),
                    "fillers": [[round(s0 + s, 2), t] for s, t in fillers]})
    if why:
        results[-1]["fillers_note"] = why
    if not 45 <= total <= 62:
        results[-1]["note"] = "outside the guide's 45-60 s; widen or narrow the topic range"
report(tool="cut_topics", src=a.src, clips=results, note="range.mp4 in each folder is the uncut topic range (kept, not deleted)")
