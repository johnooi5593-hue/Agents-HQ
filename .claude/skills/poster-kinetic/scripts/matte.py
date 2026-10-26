"""Speaker matte for text BEHIND the speaker (person segmentation), one grey mp4 the size of the render.

usage: python matte.py <video> <out/matte.mp4> [--frame crop|blur] [--crop X:Y:W:H] [--focus 0.5] [--size 1080x1920]
Give it the same --frame / --crop / --focus you will give render.py (or none for a clip that is already 1080x1920), then
render with --matte <out/matte.mp4> and set "behind": true on the poster / stack lines (zone top or middle, where the
head is). White = person.

Model: Robust Video Matting (MobileNetV3, ONNX, GPL-3.0 code / model from github.com/PeterL1n/RobustVideoMatting,
15 MB) at D:/AI OFFICE/tools/models/rvm/rvm_mobilenetv3_fp32.onnx, run with onnxruntime on the CPU. It is a video
model: it keeps state from frame to frame, so the edge does not flicker. Each picture cut resets the state (a shot
change is detected by a big frame difference). About 15-25 frames per second at 540x960.
"""
import argparse, os, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from pk import FFMPEG, probe, report  # noqa: E402

MODEL = os.environ.get("PK_RVM", "D:/AI OFFICE/tools/models/rvm/rvm_mobilenetv3_fp32.onnx")
ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("out")
ap.add_argument("--frame", choices=["crop", "blur"], default="crop")
ap.add_argument("--crop", default=None)
ap.add_argument("--focus", type=float, default=0.5)
ap.add_argument("--size", default="1080x1920")
ap.add_argument("--work", default="540x960", help="matting resolution (the matte is scaled up to --size)")
a = ap.parse_args()
if not os.path.isfile(MODEL):
    report(tool="matte", ok=False, error=f"model not found: {MODEL} (download rvm_mobilenetv3_fp32.onnx from the RVM GitHub release)"); sys.exit(1)
import onnxruntime as ort
W, H = (int(v) for v in a.size.split("x")); w, h = (int(v) for v in a.work.split("x"))
pre = ""
if a.crop:
    x, y, cw, ch = a.crop.split(":"); pre = f"crop={cw}:{ch}:{x}:{y},"
if a.frame == "crop":
    vf = pre + f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})*{a.focus}:(in_h-{H})/2,scale={w}:{h},fps=30"
else:
    vf = pre + f"scale={W}:-2,scale={w}:-2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=30"
sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", a.video, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
enc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "30",
                        "-i", "-", "-vf", f"scale={W}:{H}:flags=bicubic", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", a.out],
                       stdin=subprocess.PIPE)
z = np.zeros((1, 1, 1, 1), np.float32)
rec = [z, z, z, z]
ratio = np.array([0.4], np.float32)
prev, n, cuts = None, 0, 0
while True:
    buf = dec.stdout.read(w * h * 3)
    if len(buf) < w * h * 3:
        break
    fr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    small = fr[::8, ::8].astype(np.float32)
    if prev is not None and np.abs(small - prev).mean() > 28:      # a picture cut: start the recurrent state fresh
        rec = [z, z, z, z]; cuts += 1
    prev = small
    src = (fr.astype(np.float32) / 255).transpose(2, 0, 1)[None]
    fgr, pha, *rec = sess.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2], "r4i": rec[3], "downsample_ratio": ratio})
    enc.stdin.write((np.clip(pha[0, 0], 0, 1) * 255).astype(np.uint8).tobytes())
    n += 1
enc.stdin.close(); enc.wait(); dec.wait()
report(tool="matte", ok=True, out=a.out, frames=n, cuts_detected=cuts, seconds=round(n / 30, 2), model=os.path.basename(MODEL),
       note="render with --matte and the same framing options; behind=true on lines whose hero should go behind the speaker")
