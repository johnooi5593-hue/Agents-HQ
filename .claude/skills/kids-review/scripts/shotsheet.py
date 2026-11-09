"""Step 1-2 check: 3 frames (start, middle, end) of every shot of a framed montage, 5 shots per row, labelled
"<index> <src>". Works for 9:16 and 16:9. Look at it with the Read tool before you go on: every subject in frame, no
crop through a face, group photos whole.

usage: python shotsheet.py <framed.mp4> <shots.json> <out.jpg>
"""
import json, subprocess, sys
from PIL import Image, ImageDraw


def size(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", p],
                       capture_output=True, text=True).stdout.strip().split(",")
    return int(r[0]), int(r[1])


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    video, shots, out = sys.argv[1:4]
    cfg = json.load(open(shots, encoding="utf-8"))
    W, H = size(video)
    TW, TH = (135, 240) if H > W else (240, 135)
    t, cells = 0.0, []
    for k, s in enumerate(cfg["shots"]):
        d = round(s.get("d", cfg.get("dur", 2.0)) * 30) / 30
        for f in (0.05, 0.5, 0.95):
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t + d * f:.3f}", "-i", video, "-frames:v", "1", "-vf",
                                f"scale={TW}:{TH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
            cells.append((k, Image.frombytes("RGB", (TW, TH), r.stdout) if len(r.stdout) == TW * TH * 3 else None))
        t += d
    per = 5
    rows = (len(cfg["shots"]) + per - 1) // per
    sheet = Image.new("RGB", (per * (3 * TW + 12), rows * (TH + 4)), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    for i, (k, im) in enumerate(cells):
        j = i % 3
        x = (k % per) * (3 * TW + 12) + j * TW
        y = (k // per) * (TH + 4)
        if im:
            sheet.paste(im, (x, y))
        if j == 0:
            dr.rectangle((x, y, x + 60, y + 14), fill=(0, 0, 0)); dr.text((x + 2, y + 1), f"{k} {cfg['shots'][k]['src']}", fill=(255, 255, 0))
    sheet.save(out, quality=82)
    print(json.dumps({"out": out, "shots": len(cfg["shots"]), "size": f"{W}x{H}"}))


if __name__ == "__main__":
    main()
