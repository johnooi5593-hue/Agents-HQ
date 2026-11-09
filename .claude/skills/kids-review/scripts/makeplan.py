"""Step 6a (captions plan): the Caption Card cute-edition plan from the host voice lines. One plan for both sizes.

usage: python makeplan.py <script lines.json> <vo/lines.json> <vo-video.mp4> <plan.json>

<script lines.json>  the voice script (template ../templates/lines.json): its "plan" block sets the plan's look, and each
                     line's extra fields (key, kind, rows, phrase, color, y, accent, transition, punch_in, leak, sway,
                     bubble, why, note) go onto that plan line as is.
<vo/lines.json>      what vo.py spoke: each line's real start and length.
Word times: each line's characters are spread evenly over its spoken length (the voice is synthetic and even);
punctuation gets a 0.45 share. Run regroup_words.py next: it merges the characters into whole words.
Defaults of the cute look (the 1107 plan): pink cards #FFD3EA with #F0347F / #C8166A words at card_y 0.66 (under the
faces and the group photos), camera face [0.5, 0.36], punch 1.22, light particles with NO warm bloom (bloom 0), and a
near-neutral grade arc (brand rule 2026-11-08, never orange; the 1107 v4 values): "grade": "auto" = [[0, 0.03],
[0.383 x dur, 0.05], [0.728 x dur, 0.08], [dur, 0.1]] (v3 used 0.15 -> 0.33, v1 0.3 -> 0.65: both read too warm).
"pull_back": "auto" = from 0.05 s after the last line starts to the end.
"""
import json, subprocess, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console

PUNCT = set("！？，、～。…,!?~ ")
BASE = {"kind": "card", "color": None, "rows": None, "key_row": None, "number": None, "label": None, "unit": None,
        "phrase": None, "sub": None, "y": None, "transition": None, "anim": None, "key": [], "sway": False, "punch_in": None,
        "accent": None, "leak": False, "why": "", "note": "host voice 3B line"}
SCRIPT_ONLY = ("t", "text", "shot", "seg", "d")
LOOK = {"card": {"box": "#FFD3EA", "text": "#F0347F", "text2": "#C8166A"}, "card_y": 0.66, "motion": "v2", "cards": 2,
        "camera": {"face": [0.5, 0.36], "cuts": "auto", "pull_back": "auto", "punch_scale": 1.22},
        "grade": "auto", "light": {"from": 0.5, "bloom": 0.0, "particles": True}}


def words_for(text, t0, d):
    w8 = [0.45 if c in PUNCT else 1.0 for c in text]
    tot = sum(w8)
    out, t = [], t0
    for c, w in zip(text, w8):
        dt = d * w / tot
        if c not in PUNCT:
            out.append({"t": c, "start": round(t, 3), "end": round(t + dt, 3)})
        t += dt
    return out


def main():
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    script_p, lines_p, video, out = sys.argv[1:5]
    sc = json.load(open(script_p, encoding="utf-8"))
    spoken = json.load(open(lines_p, encoding="utf-8"))
    if len(spoken) != len(sc["lines"]):
        raise SystemExit(f"makeplan: the script has {len(sc['lines'])} lines, vo/lines.json {len(spoken)}; run vo.py again")
    dur = round(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                     capture_output=True, text=True).stdout), 3)
    lines, warn = [], []
    for i, (ln, sp) in enumerate(zip(sc["lines"], spoken)):
        if ln["text"] != sp["text"]:
            raise SystemExit(f"makeplan: line {i + 1} text differs from what vo.py spoke; run vo.py again")
        ws = words_for(sp["text"], sp["t"], sp["d"])
        e = dict(BASE, **{k: v for k, v in ln.items() if k not in SCRIPT_ONLY})
        for k in (e.get("key") or []):
            if k not in sp["text"]:
                warn.append(f"line {i + 1}: key {k!r} is not in the text")
        lines.append(dict({"id": i + 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": sp["text"], "words": ws}, **e))
    look = json.loads(json.dumps(LOOK))
    for k, v in (sc.get("plan") or {}).items():
        look[k] = dict(look[k], **v) if isinstance(v, dict) and isinstance(look.get(k), dict) else v
    cam = look["camera"]
    if cam.get("pull_back") == "auto":
        cam["pull_back"] = {"start": round(lines[-1]["start"] + 0.05, 2), "end": dur, "to": 1.0}
    if look.get("grade") == "auto":
        # caption-card (2026-11-08) halves a plain list arc by default; "classic-arc" + "grade_arc" keeps these exact v4 values
        look["grade"] = "classic-arc"
        look["grade_arc"] = [[0, 0.03], [round(0.383 * dur, 1), 0.05], [round(0.728 * dur, 1), 0.08], [dur, 0.1]]
    if lines[-1]["end"] > dur - 0.4:
        warn.append(f"the last word ends {lines[-1]['end']} s, the video {dur} s: the clean ending needs 0.4 s of tail")
    plan = {"style": "caption-card", "edition": "cute (kids-review skill)", "video": video, "duration": dur,
            "engine": "script (host voice lines, synthetic)", "language": "zh"}
    plan.update(look)
    plan["lines"] = lines
    json.dump(plan, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"out": out, "lines": len(lines), "duration": dur, "warnings": warn}, ensure_ascii=False))


if __name__ == "__main__":
    main()
