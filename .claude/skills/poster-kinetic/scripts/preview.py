"""Contact sheet of a Poster Kinetic render: frames picked at the events render.py wrote (hero moving and landed, stacks,
cards, titles, transitions, captions), so an agent or the brand-checker can look at it with the Read tool.

usage: python preview.py <video> <out.jpg> [--frames 12] [--at 12.3,14.6]
Reads <video>.pk.json; without it, frames are spread evenly. --at shows exactly the given times in big tiles.
"""
import argparse, json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from pk import FFMPEG, probe, report  # noqa: E402

PRIORITY = ["poster whip (moving)", "poster drop (moving)", "poster zoom (moving)", "poster (landed)", "stack stack (moving)",
            "stack (landed)", "card (entering)", "card (resting)", "title (entering)", "title (resting)", "transition flash",
            "transition whip", "caption"]

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("out")
ap.add_argument("--frames", type=int, default=12)
ap.add_argument("--at", default=None)
a = ap.parse_args()
info = probe(a.video); W, H, dur = info["width"], info["height"], info["duration"]
side = os.path.splitext(a.video)[0] + ".pk.json"
events = json.load(open(side, encoding="utf-8"))["events"] if os.path.isfile(side) else []
pick = [{"t": float(x), "kind": "", "line": None} for x in a.at.split(",")] if a.at else []
if a.at:
    events, a.frames = [], len(pick)
for kind in PRIORITY:
    for e in events:
        if e["kind"] == kind and all(abs(e["t"] - p["t"]) > 0.15 for p in pick):
            pick.append(e); break
    if len(pick) >= a.frames:
        break
for e in events:
    if len(pick) >= a.frames:
        break
    if "caption" not in e["kind"] and all(abs(e["t"] - p["t"]) > 0.3 for p in pick):
        pick.append(e)
k = 0
while len(pick) < a.frames and k < 60:
    t = dur * (k + 0.5) / a.frames; k += 1
    if all(abs(t - p["t"]) > 0.4 for p in pick):
        pick.append({"t": t, "kind": "", "line": None})
pick = sorted(pick[:a.frames], key=lambda e: e["t"])
tw = 360 if a.at else 270
th = int(tw * H / W); cols = 4; rows = (len(pick) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * (th + 30) + 8), (12, 12, 16)); d = ImageDraw.Draw(sheet)
try:
    lab = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf"), 15)
except OSError:
    lab = ImageFont.load_default()
for i, e in enumerate(pick):
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{e['t']:.3f}", "-i", a.video, "-frames:v", "1",
                          "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if len(raw) < tw * th * 3:
        continue
    x, y = 8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 30)
    sheet.paste(Image.frombuffer("RGB", (tw, th), raw), (x, y + 22))
    d.text((x + 2, y + 2), f"{e['t']:.2f}s {e['kind']}" + (f" #{e['line']}" if e.get("line") else ""), fill=(248, 234, 152), font=lab)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
sheet.save(a.out, quality=88)
report(tool="preview", out=a.out, frames=[{"t": round(e["t"], 2), "kind": e["kind"], "line": e.get("line")} for e in pick])
