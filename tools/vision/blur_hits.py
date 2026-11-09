"""Turn textscan hits into blurs: a box json for kids-review's scripts/blur.py, and/or an ffmpeg filtergraph.

usage: python blur_hits.py <scan.json> <boxes.json> [--ids 1,4,7] [--kinds name-like] [--all] [--pad 0.3] [--pad-y 1.2]
                           [--video in.mp4] [--size 1920x1080] [--ffmpeg graph.txt]

Picks the hits to blur: --ids (the #numbers on the textscan sheet), else every hit whose kind is in --kinds
(default name-like), or --all. Each hit becomes one blur.py box:
  {"what": "textscan #3 'VICKY ONG' (name-like)", "t0": start, "t1": end, "keys": [[t, x, y, w, h], ...]}
in pixels of --size (default: the scanned video's size; give the other size only when the picture is the same, scaled).
Every OCR box grows by --pad of its width on the left and right and by --pad-y of its height above and below (at
least 8 px): OCR boxes hug one text line, and a badge has more lines (VICKY ONG over 王美婷). Labels grow by --pad only.
Timing: the text was seen from its first sample to its last; it may be on screen up to one --step around them. With
--video the blur starts at the cut up to two steps before the first sample (else one step earlier) and stops at the
first cut up to two steps after the last sample (else one step later), so it never lands on the next shot (blur.py's rule). Without
--video it runs from half a step before the first sample to one step after the last.
--ffmpeg also writes a filtergraph for `ffmpeg -i in.mp4 -/filter_complex graph.txt -map "[vout]" -map 0:a? ...`
(ffmpeg 7.1+ syntax; this PC has ffmpeg 9, where -filter_complex_script is gone)
with one fixed box per hit (the union of its moving keys) and the same blur strength as blur.py.
Then: python .claude/skills/kids-review/scripts/blur.py <in.mp4> <boxes.json> <out.mp4>
"""
import argparse, json, math, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def pick(hits, ids=None, kinds=("name-like",), everything=False):
    if ids:
        want = set(ids)
        return [h for h in hits if h["id"] in want]
    if everything:
        return list(hits)
    return [h for h in hits if h["kind"] in kinds]


def cuts(video, threshold=10.0):
    """Scene cuts (seconds) found by ffmpeg's scdet filter."""
    import re, subprocess
    err = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-i", video, "-an", "-vf", f"scdet=threshold={threshold}",
                          "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    return sorted(float(m) for m in re.findall(r"lavfi\.scd\.time: ([0-9.]+)", err))


def num(v):
    """A time from scan.json as a finite float: anything else raises, so it can never be pasted into the filtergraph."""
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"not a finite time: {v!r}")
    return f


def timing(h, step, cut_list=None, duration=None):
    keys = h.get("keys") or [[h["start"]]]
    first, last = num(keys[0][0]), num(keys[-1][0])
    end = min(num(h["end"]), duration) if duration else num(h["end"])
    if cut_list is None:
        return max(0.0, first - step / 2), end
    # OCR misses a sample now and then (textscan bridges one), so look two steps out for the shot's own cut
    before = [c for c in cut_list if first - 2 * step < c <= first]
    after = [c for c in cut_list if last < c <= last + 2 * step]
    t0 = max(before) if before else max(0.0, first - step)
    t1 = min(after) if after else (min(last + step, duration) if duration else last + step)
    return round(t0, 3), round(t1, 3)


def to_px(frac_box, W, H, pad, pad_y=None):
    x0, y0, x1, y1 = frac_box
    w, h = (x1 - x0) * W, (y1 - y0) * H
    px, py = max(8.0, w * pad), max(8.0, h * (pad if pad_y is None else pad_y))
    X0, Y0 = max(0.0, x0 * W - px), max(0.0, y0 * H - py)
    X1, Y1 = min(float(W), x1 * W + px), min(float(H), y1 * H + py)
    return [int(round(X0)), int(round(Y0)), int(round(X1 - X0)), int(round(Y1 - Y0))]


def boxes(hits, W, H, pad=0.3, pad_y=1.2, step=0.5, cut_list=None, duration=None):
    out = []
    for h in hits:
        keys = h.get("keys") or [[h["start"]] + list(h["box"])]
        py = pad if h["kind"] == "label" else pad_y
        t0, t1 = timing(h, step, cut_list, duration)
        out.append({"what": f"textscan #{h['id']} '{h['text']}' ({h['kind']})", "t0": t0, "t1": t1,
                    "keys": [[round(k[0], 3)] + to_px(k[1:5], W, H, pad, py) for k in keys]})
    return out


def filtergraph(bxs, W, H):
    """Chain of crop -> boxblur -> overlay, one per box, enabled on t0 <= t < t1. Output label [vout]."""
    if not bxs:
        return "[0:v]null[vout]"
    parts, cur = [], "0:v"
    for i, b in enumerate(bxs, 1):
        x0 = min(k[1] for k in b["keys"]); y0 = min(k[2] for k in b["keys"])
        x1 = max(k[1] + k[3] for k in b["keys"]); y1 = max(k[2] + k[4] for k in b["keys"])
        x0, y0 = max(0, x0 - x0 % 2), max(0, y0 - y0 % 2)
        w, h = min(W - x0, max(8, x1 - x0)), min(H - y0, max(8, y1 - y0))
        w, h = w - w % 2, h - h % 2
        nxt = "vout" if i == len(bxs) else f"v{i}"
        parts.append(f"[{cur}]split[m{i}][c{i}]")
        parts.append(f"[c{i}]crop={w}:{h}:{x0}:{y0},boxblur=lr='min(16,min(w,h)/2-1)':lp=2:cr='min(16,min(cw,ch)/2-1)':cp=2[b{i}]")
        parts.append(f"[m{i}][b{i}]overlay={x0}:{y0}:enable='gte(t,{num(b['t0'])})*lt(t,{num(b['t1'])})'[{nxt}]")
        cur = nxt
    return ";\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scan"); ap.add_argument("out")
    ap.add_argument("--ids", help="comma list of hit ids from the sheet")
    ap.add_argument("--kinds", default="name-like", help="comma list: name-like,brand,other")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pad", type=float, default=0.3, help="grow each box by this much of its width, left and right")
    ap.add_argument("--pad-y", type=float, default=1.2, help="grow text boxes by this much of their height, up and down")
    ap.add_argument("--video", help="the video to blur: snap the blur's start and end to its scene cuts")
    ap.add_argument("--size", help="WxH of the video to blur (default: the scanned size)")
    ap.add_argument("--ffmpeg", help="also write an ffmpeg filtergraph here")
    a = ap.parse_args(argv)
    scan = json.loads(Path(a.scan).read_text(encoding="utf-8"))
    W, H = (int(v) for v in a.size.lower().split("x")) if a.size else scan["size"]
    ids = [int(v) for v in a.ids.split(",") if v.strip()] if a.ids else None
    chosen = pick(scan["hits"], ids, tuple(k.strip() for k in a.kinds.split(",")), a.all)
    if ids and len(chosen) != len(set(ids)):
        missing = sorted(set(ids) - {h["id"] for h in chosen})
        raise SystemExit(f"no hit with id {missing} in {a.scan}")
    cl = cuts(a.video) if a.video else None
    bxs = boxes(chosen, W, H, a.pad, a.pad_y, scan.get("step", 0.5), cl, scan.get("duration"))
    doc = {"note": f"from textscan {Path(a.scan).name}: {len(bxs)} hit(s), pixels of {W}x{H}, pad {a.pad}/{a.pad_y}, cuts {'from ' + Path(a.video).name if a.video else 'not used'}", "boxes": bxs}
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.ffmpeg:
        Path(a.ffmpeg).write_text(filtergraph(bxs, W, H) + "\n", encoding="utf-8")
    print(json.dumps({"out": a.out, "boxes": len(bxs), "ffmpeg": a.ffmpeg, "what": [b["what"] for b in bxs]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
