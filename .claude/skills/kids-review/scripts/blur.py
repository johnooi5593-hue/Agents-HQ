"""Step 4 (name blurs): blur every readable name in a video, with boxes that can move. Any size (9:16 or 16:9).

usage: python blur.py <in.mp4> <boxes.json> <out.mp4>

boxes.json (one per size: blur916.json for 9:16, blur16.json for 16:9; template ../templates/blur.json):
  {"boxes": [{"what": "teacher's lanyard badge", "t0": 10.15, "t1": 12.2, "keys": [[t, x, y, w, h], ...]}]}
A box is on for t0 <= t < t1 (stop it at the next cut, so it never lands on the next shot). x, y, w, h are pixels of
the OUTPUT frame, linearly interpolated between its keys (held before the first and after the last key). Inside the
box: two box-blur passes, radius 16, with a 3 px soft edge, so nothing in it can be read. An empty "boxes" list copies
the picture through. The sound is copied.
What to box (brand rule: never a readable child's name): name badges and lanyards, name stickers on water bottles and
bags, door charts and lists, whiteboards with names, name cards on tables. Find them on native-resolution zooms of every
shot (sheet.py --crop), not on the small shot sheet. Prints one JSON line with the blurred frame count per box.
"""
import json, subprocess, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console
from PIL import Image, ImageDraw, ImageFilter


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                        "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip().split(",")
    num, den = r[2].split("/")
    return int(r[0]), int(r[1]), float(num) / float(den)


def at(keys, t):
    if t <= keys[0][0]:
        return keys[0][1:]
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            q = (t - a[0]) / max(1e-6, b[0] - a[0])
            return [a[i] + (b[i] - a[i]) * q for i in range(1, 5)]
    return keys[-1][1:]


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    src, boxes_path, dst = sys.argv[1:4]
    W, H, FPS = probe(src)
    boxes = json.load(open(boxes_path, encoding="utf-8")).get("boxes", [])
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{FPS:g}", "-i", "-",
                            "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "15", "-preset", "medium",
                            "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", dst], stdin=subprocess.PIPE)
    fsz, n, hits = W * H * 3, 0, {b["what"]: 0 for b in boxes}
    while True:
        buf = dec.stdout.read(fsz)
        if len(buf) < fsz:
            break
        t = n / FPS; n += 1
        on = [b for b in boxes if b["t0"] <= t < b["t1"]]
        if not on:
            enc.stdin.write(buf); continue
        img = Image.frombytes("RGB", (W, H), buf)
        for b in on:
            x, y, w, h = (int(round(v)) for v in at(b["keys"], t))
            pad = 24
            x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
            reg = img.crop((x0, y0, x1, y1))
            bl = reg.filter(ImageFilter.BoxBlur(16)).filter(ImageFilter.BoxBlur(16))
            m = Image.new("L", reg.size, 0)
            ImageDraw.Draw(m).rectangle((x - x0, y - y0, x - x0 + w, y - y0 + h), fill=255)
            m = m.filter(ImageFilter.GaussianBlur(3))
            img.paste(Image.composite(bl, reg, m), (x0, y0))
            hits[b["what"]] += 1
        enc.stdin.write(img.tobytes())
    enc.stdin.close(); enc.wait(); dec.stdout.close(); dec.wait()
    print(json.dumps({"out": dst, "frames": n, "size": f"{W}x{H}", "blurred_frames": hits, "ok": enc.returncode == 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
