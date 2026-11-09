"""Step 1 (footage): probe every clip in the event's source folder and write contact sheets to choose shots from.

usage: python probe.py <source folder> <work folder> [--no-sheets] [--ext .mp4,.mov]

Reads the source folder only (it may be on D:, which is read-only for the office). Writes into the work folder:
  clips.json      one entry per clip: i, name, dur, w, h (decoded size, so a 90-degree rotation tag counts), rot, fps, audio
  sheet-N.jpg     5 frames per clip (5 / 25 / 50 / 75 / 95 %), 11 clips per sheet, labelled "NN #<id> <dur>s <w>x<h>"
                  (<id> = the clip's short id, the token build.py's "src" matches: DJI_..._0636_D.MP4 -> 0636)
Prints one JSON line per clip, then a summary line.
"""
import json, os, re, subprocess, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console
from PIL import Image, ImageDraw


def frame(p, t, w, h):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", p, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return Image.frombytes("RGB", (w, h), r.stdout) if len(r.stdout) == w * h * 3 else None


def short_id(name):
    """DJI_20261107180136_0636_D.MP4 -> 0636; IMG_1234.MOV -> 1234; otherwise the file stem."""
    stem = os.path.splitext(name)[0]
    m = re.search(r"_(\d{3,5})_[A-Z]$", stem) or re.search(r"(\d{3,6})$", stem)
    return m.group(1) if m else stem


def main():
    args = sys.argv[1:]
    sheets = "--no-sheets" not in args
    exts = (".mp4", ".mov")
    if "--ext" in args:
        exts = tuple(e.strip().lower() for e in args[args.index("--ext") + 1].split(","))
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--ext")]
    if len(pos) != 2:
        raise SystemExit(__doc__)
    src, out = pos
    os.makedirs(out, exist_ok=True)
    clips = []
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith(exts):
            continue
        p = os.path.join(src, name)
        j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                       "format=duration:stream=codec_type,width,height,r_frame_rate:stream_side_data=rotation",
                                       "-of", "json", p], capture_output=True, text=True).stdout)
        v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
        if v is None:
            continue
        rot = 0
        for sd in v.get("side_data_list", []):
            rot = int(sd.get("rotation", 0) or 0)
        w, h = (v["height"], v["width"]) if abs(rot) == 90 else (v["width"], v["height"])
        clips.append({"i": len(clips), "name": name, "dur": round(float(j["format"]["duration"]), 2), "w": w, "h": h, "rot": rot,
                      "fps": v["r_frame_rate"], "audio": any(s["codec_type"] == "audio" for s in j["streams"])})
        print(json.dumps(clips[-1], ensure_ascii=False), flush=True)
    json.dump(clips, open(os.path.join(out, "clips.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    made = []
    CELL, PER = 240, 11
    if sheets:
        for s in range(0, len(clips), PER):
            group = clips[s:s + PER]
            sheet = Image.new("RGB", (5 * (CELL + 2), len(group) * (CELL + 4)), (20, 20, 20))
            d = ImageDraw.Draw(sheet)
            for r, c in enumerate(group):
                sc = CELL / max(c["w"], c["h"])
                fw, fh = int(c["w"] * sc) // 2 * 2, int(c["h"] * sc) // 2 * 2
                for k, f in enumerate((0.05, 0.25, 0.5, 0.75, 0.95)):
                    im = frame(os.path.join(src, c["name"]), c["dur"] * f, fw, fh)
                    if im:
                        sheet.paste(im, (k * (CELL + 2), r * (CELL + 4)))
                d.rectangle((0, r * (CELL + 4), 200, r * (CELL + 4) + 18), fill=(0, 0, 0))
                d.text((3, r * (CELL + 4) + 3), f"{c['i']:02d} #{short_id(c['name'])} {c['dur']}s {c['w']}x{c['h']}", fill=(255, 255, 0))
            p = os.path.join(out, f"sheet-{s // PER}.jpg")
            sheet.save(p, quality=80); made.append(p)
    print(json.dumps({"clips": len(clips), "clips_json": os.path.join(out, "clips.json"), "sheets": made}, ensure_ascii=False))


if __name__ == "__main__":
    main()
