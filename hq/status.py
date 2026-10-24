"""Agents HQ status: what is waiting, what is done, what the brain holds. One JSON line on stdout.

usage: python3 hq/status.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def files(path, exts=None):
    if not os.path.isdir(path):
        return []
    names = sorted(n for n in os.listdir(path) if not n.startswith(".") and os.path.isfile(os.path.join(path, n)))
    return [n for n in names if exts is None or os.path.splitext(n)[1].lower() in exts]


def out_folders():
    base = os.path.join(ROOT, "out")
    result = {}
    if not os.path.isdir(base):
        return result
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        have = set(files(full))
        if name in ("scripts", "radar", "pulse"):
            result[name] = {"files": sorted(have)}
            continue
        result[name] = {
            "edit": "edit.mp4" in have,
            "cover": "cover.jpg" in have,
            "captions": "captions.srt" in have,
            "notes": "notes.md" in have,
            "post_copy": "post.md" in have,
        }
    return result


def brain():
    counts = {}
    path = os.path.join(ROOT, "brain", "memory.jsonl")
    if not os.path.isfile(path):
        return counts
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "entity":
                counts[row["name"]] = len(row.get("observations", []))
    return counts


status = {
    "inbox": {
        "clips": files(os.path.join(ROOT, "inbox"), CLIP_EXT),
        "radar": files(os.path.join(ROOT, "inbox", "radar")),
        "stats": files(os.path.join(ROOT, "inbox", "stats"), {".csv"}),
    },
    "out": out_folders(),
    "done": len(files(os.path.join(ROOT, "done"), CLIP_EXT)),
    "brain": brain(),
}
status["waiting_for_approval"] = sorted(k for k, v in status["out"].items() if k not in ("scripts", "radar", "pulse") and v.get("edit"))
json.dump(status, sys.stdout, ensure_ascii=False)
print()
