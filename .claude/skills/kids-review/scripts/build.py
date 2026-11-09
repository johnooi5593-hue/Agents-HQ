"""Step 2 (montage): build the framed montage of the chosen shots, for 9:16 or 16:9, with each shot's room sound.

usage: python build.py <source folder> <shots.json> <out.mp4> --size 9x16|16x9 [--over shots16.json] [--to SECONDS]
                       [--eq "<ffmpeg eq filter>"]

shots.json (template: ../templates/shots.json): {"dur": 2.0, "shots": [{"src": "0673", "t": 0.9, "d": 2.2, "cx": 0.42,
"cy": 0.5, "zoom": 1.0, "drift": 0.0, "fit": false, "what": "..."}]}
  src    the clip: an exact file name, or its short id (probe.py's #id: DJI_..._0636_D.MP4 -> "0636"), or any unique
         part of the file name
  t / d  start in the clip and seconds (d defaults to "dur"); each shot is rounded to whole frames at 30 fps
  9x16   1080x1920, cropped to fill around (cx, cy) (fractions of the 16:9 source) from a 3413x1920 decode (real pixels),
         an optional "zoom" (> 1 = tighter) and a sideways "drift" (fraction, eased); "fit": true keeps the whole 16:9
         picture over a blurred, dimmed fill of itself (posed group photos only, brand rule)
  16x9   1920x1080, the camera's whole picture (no fill, no crop); --over shots16.json gives a gentle crop per shot:
         {"shots": {"<index>": {"z": 1.1, "cx": 0.45, "cy": 0.5}}}
--to     build only the first SECONDS (a quick test); the shots after it are skipped, the last one is cut short
--eq     the light pre-grade every frame gets (default: the 1107 one, below). grade.py does the real grade later, so keep
         this gentle; "null" switches it off.
The camera moves (push / drift / punch / pull-back) come from the caption-card renderer later, so the shots stay steady.
Writes <out>, plus <out>.video.mp4 (picture only) and <out>.room.f32 (the room sound), and prints one JSON line per shot.
"""
import json, os, subprocess, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

FPS, SR = 30, 48000
EQ_1107 = "eq=gamma=1.12:contrast=1.05:saturation=1.18:brightness=0.01"


def ease_io(x):
    x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)


def find_clip(src_dir, src):
    names = [n for n in os.listdir(src_dir) if not n.startswith(".")]
    if src in names:
        return os.path.join(src_dir, src)
    for rule in (lambda n: os.path.splitext(n)[0].upper().endswith(f"_{src}_D".upper()),
                 lambda n: os.path.splitext(n)[0].endswith(src),
                 lambda n: src in n):
        hit = [n for n in names if rule(n)]
        if len(hit) == 1:
            return os.path.join(src_dir, hit[0])
        if len(hit) > 1:
            raise SystemExit(f"build: shot src {src!r} matches {len(hit)} files ({hit[:3]}...); use the full file name")
    raise SystemExit(f"build: no clip for shot src {src!r} in {src_dir}")


def box(W, H, OW, OH, cx, cy, z):
    h = H / z
    w = h * OW / OH
    x0 = min(max(cx * W - w / 2, 0), W - w)
    y0 = min(max(cy * H - h / 2, 0), H - h)
    return (x0, y0, x0 + w, y0 + h)


def fitted(img, OW, OH):
    """Whole 16:9 picture across the width, over a blurred, dimmed fill of itself (9:16 group photos)."""
    bg = img.resize((OW, OH), Image.BICUBIC, box=box(img.width, img.height, OW, OH, 0.5, 0.5, 1.0)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.62)
    fh = round(OW * img.height / img.width)
    fg = img.resize((OW, fh), Image.LANCZOS)
    bg.paste(fg, (0, (OH - fh) // 2 - 40))
    return bg


def crop16(z, cx, cy):
    if z <= 1.0001:
        return ""
    return (f"crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2:"
            f"min(max(iw*{cx}-iw/{z}/2\\,0)\\,iw-iw/{z}):min(max(ih*{cy}-ih/{z}/2\\,0)\\,ih-ih/{z}),")


def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def main():
    args = sys.argv[1:]
    size = opt(args, "--size")
    over_p, to, eq = opt(args, "--over"), opt(args, "--to"), opt(args, "--eq", EQ_1107)
    flags = {"--size", "--over", "--to", "--eq"}
    pos = [a for i, a in enumerate(args) if a not in flags and (i == 0 or args[i - 1] not in flags)]
    if len(pos) != 3 or size not in ("9x16", "16x9"):
        raise SystemExit(__doc__)
    src_dir, shots_path, dst = pos
    tall = size == "9x16"
    OW, OH = (1080, 1920) if tall else (1920, 1080)
    cfg = json.load(open(shots_path, encoding="utf-8"))
    over = json.load(open(over_p, encoding="utf-8")).get("shots", {}) if over_p else {}
    to = float(to) if to else None
    eqf = "" if eq in ("", "null", "none") else "," + eq
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(FPS),
                            "-i", "-", "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p",
                            dst + ".video.mp4"], stdin=subprocess.PIPE)
    audio, total, built = [], 0.0, 0
    for k, s in enumerate(cfg["shots"]):
        if to is not None and total >= to - 1e-6:
            break
        dur = s.get("d", cfg.get("dur", 2.0))
        n = round(dur * FPS)
        if to is not None:
            n = min(n, round((to - total) * FPS))
        dur = n / FPS
        path = find_clip(src_dir, str(s["src"]))
        if tall:
            W, H = (1920, 1080) if s.get("fit") else (3413, 1920)
            vf = f"fps={FPS},scale={W}:{H}:flags=lanczos{eqf}"
        else:
            W, H = OW, OH
            o = over.get(str(k), {})
            vf = f"fps={FPS},{crop16(float(o.get('z', 1.0)), float(o.get('cx', 0.5)), float(o.get('cy', 0.5)))}" \
                 f"scale={OW}:{OH}:flags=lanczos,setsar=1{eqf}"
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{s['t']:.3f}", "-i", path, "-t", f"{dur + 0.2:.3f}",
                              "-vf", vf, "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        got, last, fsz = 0, None, W * H * 3
        while got < n:
            b = p.stdout.read(fsz)
            if len(b) < fsz:
                if last is None:
                    raise SystemExit(f"build: shot {k} ({s['src']} at {s['t']} s) gave no frames")
                b = last
            last = b
            if tall:
                img = Image.frombytes("RGB", (W, H), b)
                if s.get("fit"):
                    img = fitted(img, OW, OH)
                else:
                    q = got / max(1, n - 1)
                    cx = s["cx"] + s.get("drift", 0.0) * (ease_io(q) - 0.5)
                    img = img.resize((OW, OH), Image.BICUBIC, box=box(W, H, OW, OH, cx, s.get("cy", 0.5), s.get("zoom", 1.0)))
                b = img.tobytes()
            enc.stdin.write(b)
            got += 1
        p.stdout.close(); p.wait()
        a = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{s['t']:.3f}", "-i", path, "-t", f"{dur:.3f}", "-vn", "-ac", "2",
                            "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
        a = np.frombuffer(a, np.float32).reshape(-1, 2).copy()
        need = round(dur * SR)
        a = np.pad(a, ((0, max(0, need - len(a))), (0, 0)))[:need]
        f = min(240, need // 2)
        a[:f] *= np.linspace(0, 1, f)[:, None]; a[-f:] *= np.linspace(1, 0, f)[:, None]
        audio.append(a)
        print(json.dumps({"shot": k, "src": s["src"], "start": round(total, 3), "d": round(dur, 3), "what": s.get("what", "")},
                         ensure_ascii=False), flush=True)
        total += dur; built += 1
    enc.stdin.close(); enc.wait()
    wav = dst + ".room.f32"
    np.concatenate(audio).astype(np.float32).tofile(wav)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", dst + ".video.mp4", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", dst], check=True)
    print(json.dumps({"out": dst, "size": f"{OW}x{OH}", "shots": built, "seconds": round(total, 3)}))


if __name__ == "__main__":
    main()
