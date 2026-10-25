"""Contact sheet of a Yellow Serif Kinetic render: 8 frames picked at caption events (mid-pop, after a pop, burst impact
and landing, shine band and after, flash edge, light leak, each layout), so an agent or the brand-checker can look at it
with the Read tool.

usage: python3 .claude/skills/yellow-serif/scripts/preview.py <video> <out.jpg> [--frames 8] [--big] [--at 12.3,14.6]
Reads the events render.py wrote to <video>.ys.json; without it, frames are spread evenly. --big makes 360 px wide tiles;
--at shows exactly the given times (to look closely at one moment).
"""
import argparse, json, os, subprocess, sys
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from common import FFMPEG, probe, report  # noqa: E402
import fonts  # noqa: E402

PRIORITY = ["burst (impact)", "burst (landed)", "pop (108%)", "shine (band)", "shine (after)", "flash (edge)", "light leak",
            "layout darken", "layout fullscreen", "layout torn", "pop (settled)", "typing"]

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("out")
ap.add_argument("--frames", type=int, default=8)
ap.add_argument("--big", action="store_true")
ap.add_argument("--at", default=None, help="comma-separated seconds to show instead of the events, e.g. 12.3,14.6 (big tiles)")
a = ap.parse_args()

info = probe(a.video); W, H, dur = info["width"], info["height"], info["duration"]
side = os.path.splitext(a.video)[0] + ".ys.json"
events = json.load(open(side, encoding="utf-8"))["events"] if os.path.isfile(side) else []
pick = [{"t": float(x), "kind": "", "line": None} for x in a.at.split(",")] if a.at else []
if a.at:
    events, a.frames, a.big = [], len(pick), True
for kind in PRIORITY:                                  # one of each kind first, in priority order
    for e in events:
        if e["kind"] == kind and all(abs(e["t"] - p["t"]) > 0.12 for p in pick):
            pick.append(e); break
    if len(pick) >= a.frames:
        break
for e in events:                                       # then more events, spread out
    if len(pick) >= a.frames:
        break
    if all(abs(e["t"] - p["t"]) > 0.6 for p in pick):
        pick.append(e)
k = 0
while len(pick) < a.frames and k < 50:                 # then evenly spaced frames
    t = dur * (k + 0.5) / a.frames; k += 1
    if all(abs(t - p["t"]) > 0.4 for p in pick):
        pick.append({"t": t, "kind": "", "line": None})
pick = sorted(pick[:a.frames], key=lambda e: e["t"])

tw = 360 if a.big else 270; th = int(tw * H / W); cols = 4; rows = (len(pick) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * (th + 30) + 8), (12, 12, 16)); d = ImageDraw.Draw(sheet)
lab = fonts.font("serif", 15)
for i, e in enumerate(pick):
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{e['t']:.3f}", "-i", a.video, "-frames:v", "1",
                          "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if len(raw) < tw * th * 3:
        continue
    x, y = 8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 30)
    sheet.paste(Image.frombuffer("RGB", (tw, th), raw), (x, y + 22))
    d.text((x + 2, y + 2), f"{e['t']:.2f}s {e['kind']}" + (f" #{e['line']}" if e.get("line") else ""), fill=(251, 194, 56), font=lab)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
sheet.save(a.out, quality=88)
report(tool="preview", out=a.out, frames=[{"t": round(e["t"], 2), "kind": e["kind"], "line": e.get("line")} for e in pick])
