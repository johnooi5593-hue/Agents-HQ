"""Contact sheets of a video at chosen times, any size, every frame labelled with its time. For the name hunt (step 4,
with --crop for a native-resolution zoom), the grade check (step 5) and every brand-check look.

usage: python sheet.py <video> <out_prefix> [--at t1,t2,...] [--shots shots.json] [--every S] [--cols 3] [--w 640]
                       [--crop x,y,w,h]
  --at       these times; --shots: 3 per shot of shots.json (start + 0.05, middle, end - 0.08); --every: one every S s
  --crop     a zoomed look at one region, in pixels of the video (e.g. a badge), shown at its own size
Writes <out_prefix>_NN.jpg, 12 frames each, and prints one JSON line.
"""
import argparse, json, subprocess
from PIL import Image, ImageDraw, ImageFont


def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-show_entries", "format=duration", "-of", "json", video], capture_output=True, text=True).stdout
    j = json.loads(r)
    return int(j["streams"][0]["width"]), int(j["streams"][0]["height"]), float(j["format"]["duration"])


def grab(video, t, W, H, crop):
    vf = f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}" if crop else "null"
    b = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf", vf,
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    w, h = (crop[2], crop[3]) if crop else (W, H)
    if len(b) < w * h * 3:
        return Image.new("RGB", (w, h), (40, 0, 0))
    return Image.frombytes("RGB", (w, h), b[:w * h * 3])


def font(px):
    for p in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--at"); ap.add_argument("--shots"); ap.add_argument("--every", type=float)
    ap.add_argument("--cols", type=int, default=3); ap.add_argument("--w", type=int, default=None); ap.add_argument("--crop")
    a = ap.parse_args()
    W, H, D = probe(a.video)
    crop = [int(v) for v in a.crop.split(",")] if a.crop else None
    if a.at:
        ts = [float(x) for x in a.at.split(",")]
    elif a.shots:
        cfg = json.load(open(a.shots, encoding="utf-8")); ts, t = [], 0.0
        for s in cfg["shots"]:
            d = round(s.get("d", cfg.get("dur", 2.0)) * 30) / 30
            ts += [t + 0.05, t + d / 2, t + d - 0.08]; t += d
    else:
        step = a.every or 1.0
        ts = [round(i * step, 3) for i in range(int(D / step) + 1) if i * step < D - 0.02]
    w = a.w or (crop[2] if crop else (360 if H > W else 640))
    f = font(max(14, w // 24))
    outs = []
    for k in range(0, len(ts), 12):
        part = ts[k:k + 12]
        ims = [grab(a.video, t, W, H, crop) for t in part]
        h = round(w * ims[0].height / ims[0].width)
        cols = a.cols if a.cols else 3
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * h), (20, 20, 20))
        for i, (im, t) in enumerate(zip(ims, part)):
            im = im.resize((w, h), Image.LANCZOS); d = ImageDraw.Draw(im)
            d.rectangle((0, 0, w // 5 + 20, w // 18 + 10), fill=(0, 0, 0)); d.text((6, 3), f"{t:.2f}", fill=(255, 255, 0), font=f)
            sheet.paste(im, ((i % cols) * w, (i // cols) * h))
        p = f"{a.out}_{k // 12 + 1:02d}.jpg"; sheet.save(p, quality=85); outs.append(p)
    print(json.dumps({"sheets": outs, "frames": len(ts), "size": f"{W}x{H}"}))


if __name__ == "__main__":
    main()
