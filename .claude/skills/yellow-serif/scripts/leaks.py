"""Light leaks for transitions and for the flash cue: soft red, orange, yellow and white gradients and bokeh blobs that
drift and flare, screen-blended over the picture. Made procedurally (nothing copied from the reference video).

If the owner drops a clean overlay clip into .claude/skills/yellow-serif/assets/overlays/ (mp4/mov/webm, light on
black), transitions use pieces of it instead, also screen-blended.
"""
import glob, os, subprocess
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAYS = os.environ.get("YS_OVERLAY_DIR") or os.path.join(os.path.dirname(HERE), "assets", "overlays")
PALETTE = [(0xFF, 0x3B, 0x1F), (0xFF, 0x8A, 0x1F), (0xFF, 0xD2, 0x3F), (255, 246, 232)]


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def leak(p, seed, W, H, kind="transition"):
    """One frame of a light leak at progress p (0..1) as uint8 RGB (H, W, 3); black means no light."""
    rng = np.random.default_rng(seed)
    lw, lh = max(32, W // 6), max(32, H // 6)
    yy, xx = np.mgrid[0:lh, 0:lw].astype(np.float32)
    xx /= lw; yy /= lh
    env = float(_smooth(0.0, 0.35, p) * (1 - _smooth(0.55, 1.0, p)))
    if kind == "flash":                                  # quick bright bloom: up in 2-3 frames, gone in ~0.4 s
        env = float(_smooth(0.0, 0.12, p) * (1 - _smooth(0.25, 1.0, p)))
    img = np.zeros((lh, lw, 3), np.float32)
    side = rng.integers(0, 4)
    for b in range(int(rng.integers(3, 5))):             # big soft gradients drifting across
        col = np.array(PALETTE[int(rng.choice(4, p=[0.42, 0.30, 0.16, 0.12]))], np.float32) / 255
        if side == 0:   x0, y0 = rng.uniform(-0.2, 0.3), rng.uniform(0.1, 0.9)
        elif side == 1: x0, y0 = rng.uniform(0.7, 1.2), rng.uniform(0.1, 0.9)
        elif side == 2: x0, y0 = rng.uniform(0.0, 1.0), rng.uniform(-0.2, 0.25)
        else:           x0, y0 = rng.uniform(0.0, 1.0), rng.uniform(0.75, 1.2)
        dx, dy = rng.uniform(-0.35, 0.35), rng.uniform(-0.25, 0.25)
        cx, cy = x0 + dx * p, y0 + dy * p
        rx, ry = rng.uniform(0.3, 0.75), rng.uniform(0.18, 0.5)
        inten = rng.uniform(0.55, 1.0)
        g = np.exp(-(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2) * 2.2)
        img += g[..., None] * col * inten
    for b in range(int(rng.integers(1, 4))):             # bokeh discs: defocused highlights
        col = np.array(PALETTE[int(rng.integers(1, 4))], np.float32) / 255
        cx, cy = rng.uniform(0.1, 0.9) + rng.uniform(-0.15, 0.15) * p, rng.uniform(0.1, 0.9) + rng.uniform(-0.1, 0.1) * p
        r = rng.uniform(0.05, 0.13)
        d = np.sqrt(((xx - cx) * lw / lh) ** 2 + (yy - cy) ** 2) / r
        img += (1 - _smooth(0.55, 1.0, d))[..., None] * col * rng.uniform(0.18, 0.38)
    flare = float(np.exp(-((p - 0.42) / 0.12) ** 2)) * 0.38
    if kind == "flash":
        flare = float(np.exp(-((p - 0.12) / 0.1) ** 2)) * 0.8
    fc = np.exp(-(((xx - rng.uniform(0.3, 0.7)) / 0.6) ** 2 + ((yy - rng.uniform(0.3, 0.7)) / 0.45) ** 2) * 1.5)
    img += fc[..., None] * np.array([1.0, 0.93, 0.8], np.float32) * flare
    img = np.clip(img * env * (0.95 if kind == "transition" else 0.75), 0, 1)
    small = Image.fromarray((img * 255 + 0.5).astype(np.uint8))
    return np.asarray(small.resize((W, H), Image.BILINEAR))


def screen(fr, L, amount=1.0):
    """Screen blend L over fr in place (both uint8 RGB)."""
    if amount < 1:
        L = (L.astype(np.uint16) * int(amount * 256) >> 8).astype(np.uint8)
    f = fr.astype(np.uint16)
    fr[:] = (f + ((255 - f) * L.astype(np.uint16) + 127) // 255).astype(np.uint8)
    return fr


def overlay_files():
    return sorted(p for ext in ("mp4", "mov", "webm", "m4v") for p in glob.glob(os.path.join(OVERLAYS, f"*.{ext}")))


def overlay_frames(path, offset, dur, W, H, ffmpeg="ffmpeg", fps=30):
    """Frames [offset, offset+dur) of an owner-provided overlay clip, scaled to cover W x H."""
    raw = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{offset:.3f}", "-t", f"{dur:.3f}", "-i", path,
                          "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (W * H * 3)
    return [np.frombuffer(raw, np.uint8, W * H * 3, i * W * H * 3).reshape(H, W, 3) for i in range(n)]
