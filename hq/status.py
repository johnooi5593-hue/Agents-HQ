"""Agents HQ status: what is waiting, what is done, what the brain holds. One JSON line on stdout.

usage: python3 hq/status.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
SPECIAL = ("scripts", "radar", "pulse")


def files(path, exts=None):
    if not os.path.isdir(path):
        return []
    names = sorted(n for n in os.listdir(path) if not n.startswith(".") and os.path.isfile(os.path.join(path, n)))
    return [n for n in names if exts is None or os.path.splitext(n)[1].lower() in exts]


def work_folders(base):
    """Every folder under out/ (or approved/) with what it contains."""
    result = {}
    if not os.path.isdir(base):
        return result
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        have = files(full)
        if name in SPECIAL:
            result[name] = {"files": have}
            continue
        result[name] = {
            "edit": "edit.mp4" in have,
            "cover": "cover.jpg" in have,
            "captions": "captions.srt" in have,
            "notes": "notes.md" in have,
            "post_copy": "post.md" in have,
            "files": have,
        }
    return result


def brain_entities():
    """The entities in brain/memory.jsonl with their observations (deleted observations applied)."""
    entities = {}
    path = os.path.join(ROOT, "brain", "memory.jsonl")
    if not os.path.isfile(path):
        return entities
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
                entities[row["name"]] = list(row.get("observations", []))
    return entities


def brain_notes():
    """Every observation in the brain, counted: the number under THE BRAIN in the office."""
    return sum(len(v) for v in brain_entities().values())


def collect():
    out = work_folders(os.path.join(ROOT, "out"))
    brain = brain_entities()
    return {
        "inbox": {
            "clips": files(os.path.join(ROOT, "inbox"), CLIP_EXT),
            "radar": files(os.path.join(ROOT, "inbox", "radar")),
            "stats": files(os.path.join(ROOT, "inbox", "stats"), {".csv"}),
            "messages": files(os.path.join(ROOT, "inbox", "messages")),
        },
        "out": out,
        "approved": work_folders(os.path.join(ROOT, "approved")),
        "done": len(files(os.path.join(ROOT, "done"), CLIP_EXT)),
        "brain": {k: len(v) for k, v in brain.items()},
        "brain_notes": sum(len(v) for v in brain.values()),
        "waiting_for_approval": sorted(k for k, v in out.items() if k not in SPECIAL and v.get("edit")),
    }


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, ensure_ascii=False)
    print()
