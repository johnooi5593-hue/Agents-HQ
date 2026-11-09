"""Measured colour-grade check for the brand check (board t204, 2026-11-08).

The owner's colour-grade rule (Brand rules, 2026-11-08): bright and clean, never too orange or too warm, neutral
whites, natural skin. This tool turns that rule into numbers so every brand-checker measures the same way.

usage:
  python gradecheck.py <video.mp4> <out.json> [--step 0.5] [--faces faces.json] [--shots shots.json]
                       [--ref other.mp4] [--sheet out.jpg] [--profile kids|sermon]

Per sample frame (one every --step seconds, decoded at 640 px on the long side):
  white     near-white, low-saturation pixels (L* > 65, HSV S < 0.28, |a*| < 10, not blown out: min channel < 245): mean a*, b* (CIELAB, D65)
            b* > 0 = yellow / warm, a* > 0 = magenta / red cast
  skin      --faces boxes (intersected with a loose skin mask, so hair and background in the box don't count),
            otherwise a YCrCb skin mask (Cr 133-185, Cb 77-127, Y > 60, HSV S 0.18-0.75, hue 0-40): mean hue (deg), mean HSV S,
            % of skin pixels with R >= 250 or any channel >= 254
  exposure  median Rec.709 luma (0-255), % crushed (< 8), % clipped (> 250)
  colour    mean HSV saturation of the frame, warmth index = mean b* of the near-neutral mid-tones
            (L* 25-75, C* < 25, skin left out)
Shots: --shots json (grade.py format {"shots":[{"d":..}],"dur":..}, {"cuts":[s,..]}, [[start,end],..] or
[{"start":..,"end":..}]) or cut detection (32-bin luma histogram, distance > 0.35, shots >= 0.5 s, as grade.py).
Flags (per shot on the shot's mean, and overall) are in PROFILES below; README-gradecheck.md has the calibration.
Shots shorter than 1.0 s are measured but not judged (verdict SHORT).
--ref adds ref numbers and deltas (this - ref) per shot (ref sampled in the same time windows) and overall.
--sheet writes a contact sheet, one frame per shot with its numbers; flagged shots get a red frame and label.

Exit code: 0 = PASS, 1 = FAIL (at least one flag), 2 = the video can't be read (e.g. a render still in progress).
"""
import json
import math
import os
import subprocess
import tempfile
import sys

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

ANALYSIS_LONG = 640
MIN_DECODED = 0.9          # fewer frames than this x duration x fps = a failed decode, not a verdict
MIN_SKIN_FRAC = 0.004       # below this share of the frame a sample has no skin reading
MIN_WHITE_FRAC = 0.005      # below this share of the frame a sample has no white reading

# Thresholds. kids = the default (children / event reviews, any neutral look). sermon = owner-approved warm sermon
# grades: only the warmth limits are looser (see README-gradecheck.md for the numbers they were calibrated on).
PROFILES = {
    # warm_b_max 8 (not the brief's 10): the warmth index leaves out saturated colours and skin, so it reads lower
    # than a plain mid-tone mean; 8 fails 7 of the 25 v3 shots (8.6-12.4) and none of v4 (worst 6.3)
    "kids": dict(skin_sat_max=0.45, skin_hue_min=10.0, skin_hue_max=35.0, skin_clip_max=1.0,
                 white_b_max=8.0, white_a_max=4.0, crushed_max=3.0, warm_b_max=8.0),
    # the owner-approved CAN 1106-01 / PJ 1101-01 worst judged shots, plus a small margin (README-gradecheck.md):
    # white b* 10.9 -> 12, white a* 4.7 -> 5, skin S 0.534 -> 0.55, skin clip 2.1 % -> 2.5 %, crushed 31.9 %
    # (designed near-black stage and caption backgrounds) -> 35 %, warmth 8.4 -> 12
    "sermon": dict(skin_sat_max=0.55, skin_hue_min=10.0, skin_hue_max=35.0, skin_clip_max=2.5,
                   white_b_max=12.0, white_a_max=5.0, crushed_max=35.0, warm_b_max=12.0),
}
MIN_JUDGED_SHOT = 1.0       # shots shorter than this (s) are measured but not judged: flashes, light leaks, blur wipes

FLAG_TEXT = {
    "skin_sat": "skin too saturated (orange/tanned)",
    "skin_hue_low": "skin hue too red/pink",
    "skin_hue_high": "skin hue too yellow",
    "skin_clip": "skin clipped",
    "white_warm": "whites yellow/warm",
    "white_magenta": "whites magenta/red",
    "crushed": "blacks crushed",
    "too_warm": "too warm overall",
}


# ---------- colour maths ----------
def srgb_to_lab(rgb):
    """rgb float 0-1 (..., 3) -> L* a* b* (D65), numpy only so the result doesn't depend on OpenCV's conventions."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    e = 216 / 24389
    f = np.where(xyz > e, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return L, a, b


def skin_mask_ycrcb(u8):
    """The no-faces skin mask: the classic YCrCb box (Cb 77-127, Y > 60) with Cr widened from 173 to 185 so
    orange / over-pushed skin (the thing this check is for) stays in, narrowed so a warm grade can't
    turn whole walls, white boards and pink caption cards into 'skin': HSV S 0.18-0.75 (warm-tinted white walls and
    paper sit below 0.18), hue 0-40 deg or >= 350 deg. Still catches wood, orange toys and beige clothes; use --faces
    for a face-only reading."""
    ycc = cv2.cvtColor(u8, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)
    h2, s = hsv[..., 0], hsv[..., 1]                            # h2 = degrees / 2, s 0-255
    return ((cr >= 133) & (cr <= 185) & (cb >= 77) & (cb <= 127) & (y > 60)
            & (s >= 46) & (s <= 191) & ((h2 <= 20) | (h2 >= 175)))


def loose_skin_mask(u8):
    """Inside a face box: drop hair, eyes, teeth and background, keep anything skin-ish (also orange / clipped skin)."""
    ycc = cv2.cvtColor(u8, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    return (cr >= 128) & (cr <= 185) & (cb >= 65) & (cb <= 135) & (y > 50)


def frame_metrics(u8, boxes=None):
    """u8: HxWx3 uint8 RGB. boxes: None (use the YCrCb mask) or a list of (x, y, w, h) in this frame's pixels
    ([] = faces were given but there is no face in this frame). Returns a dict of numbers (None = no reading)."""
    H, W = u8.shape[:2]
    f = u8.astype(np.float32) / 255
    L, a, b = srgb_to_lab(f)
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)
    hue = hsv[..., 0].astype(np.float32) * 2
    sat = hsv[..., 1].astype(np.float32) / 255
    mx, mn = u8.max(2), u8.min(2)
    Y =(u8.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    n = float(H * W)
    m = {}
    # white balance
    wm = (L > 65) & (sat < 0.28) & (mn < 245) & (np.abs(a) < 10)  # not blown out; |a*| < 10 keeps pink cards out
    m["white_frac"] = round(float(wm.sum() / n), 4)
    if wm.sum() / n >= MIN_WHITE_FRAC:
        m["white_a"], m["white_b"] = round(float(a[wm].mean()), 2), round(float(b[wm].mean()), 2)
    else:
        m["white_a"] = m["white_b"] = None
    # skin
    if boxes is None:
        sm = skin_mask_ycrcb(u8)
    else:
        box = np.zeros((H, W), bool)
        for (x, y, w, h) in boxes:
            x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
            x1, y1 = min(W, int(round(x + w))), min(H, int(round(y + h)))
            if x1 > x0 and y1 > y0:
                box[y0:y1, x0:x1] = True
        sm = box & loose_skin_mask(u8)
    sk = int(sm.sum())
    m["skin_frac"] = round(sk / n, 4)
    min_px = MIN_SKIN_FRAC * n if boxes is None else max(30, 0.15 * sum(w * h for (_, _, w, h) in boxes) if boxes else 1)
    if sk >= max(30, min_px):
        hh = hue[sm]
        hh = np.where(hh >= 300, hh - 360, hh)                     # pink skin wraps around 0 deg
        px = u8[sm]
        clip = (px[:, 0] >= 250) | (px.max(1) >= 254)
        m["skin_hue"] = round(float(hh.mean()), 1)
        m["skin_sat"] = round(float(sat[sm].mean()), 3)
        m["skin_clip"] = round(float(clip.mean() * 100), 2)
    else:
        m["skin_hue"] = m["skin_sat"] = m["skin_clip"] = None
    # exposure
    m["luma_median"] = round(float(np.median(Y)), 1)
    m["crushed"] = round(float((Y < 8).mean() * 100), 2)
    m["clipped"] = round(float((Y > 250).mean() * 100), 2)
    # colour
    m["sat_mean"] = round(float(sat.mean()), 3)
    # near-neutral mid-tones only, skin left out: a cast shows up there, while orange shirts / toys / wood (C* > 25)
    # and close-up faces (judged by the skin numbers) don't count
    mid = (L >= 25) & (L <= 75) & (np.hypot(a, b) < 25) & ~(sm if boxes is None else (sm | skin_mask_ycrcb(u8)))
    m["warmth"] = round(float(b[mid].mean()), 2) if mid.sum() / n >= 0.01 else None
    return m


KEYS = ["white_a", "white_b", "skin_hue", "skin_sat", "skin_clip", "luma_median", "crushed", "clipped", "sat_mean", "warmth"]


def aggregate(samples):
    """Mean of each metric over the samples that have it, plus the worst skin clip and how many samples had skin."""
    out = {"samples": len(samples)}
    for k in KEYS:
        v = [s[k] for s in samples if s.get(k) is not None]
        out[k] = round(float(np.mean(v)), 3) if v else None
    clips = [s["skin_clip"] for s in samples if s.get("skin_clip") is not None]
    out["skin_clip_max"] = round(float(max(clips)), 2) if clips else None
    out["skin_samples"] = len(clips)
    return out


def evaluate(agg, profile="kids"):
    """Flags for one aggregate (a shot, the whole video, or one frame's metrics)."""
    p = PROFILES[profile]
    fl = []
    if agg.get("skin_sat") is not None and agg["skin_sat"] > p["skin_sat_max"]:
        fl.append("skin_sat")
    if agg.get("skin_hue") is not None and agg["skin_hue"] < p["skin_hue_min"]:
        fl.append("skin_hue_low")
    if agg.get("skin_hue") is not None and agg["skin_hue"] > p["skin_hue_max"]:
        fl.append("skin_hue_high")
    if agg.get("skin_clip") is not None and agg["skin_clip"] > p["skin_clip_max"]:
        fl.append("skin_clip")
    if agg.get("white_b") is not None and agg["white_b"] > p["white_b_max"]:
        fl.append("white_warm")
    if agg.get("white_a") is not None and agg["white_a"] > p["white_a_max"]:
        fl.append("white_magenta")
    if agg.get("crushed") is not None and agg["crushed"] > p["crushed_max"]:
        fl.append("crushed")
    if agg.get("warmth") is not None and agg["warmth"] > p["warm_b_max"]:
        fl.append("too_warm")
    return fl


# ---------- video ----------
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:stream_side_data=rotation:format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe can't read {path}: {r.stderr.strip()[:200]}")
    d = json.loads(r.stdout or "{}")
    if not d.get("streams"):
        raise RuntimeError(f"no video stream in {path}")
    st = d["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:                      # other side-data entries (display matrix etc.) must not reset it
            rot = int(float(sd["rotation"]))
    if abs(rot) % 180 == 90:                      # ffmpeg autorotates: the decoded frame is turned (Lessons, 1101)
        w, h = h, w
    num, den = st.get("r_frame_rate", "30/1").split("/")
    fps = float(num) / float(den or 1) if float(num) else 30.0
    return w, h, fps, float(d.get("format", {}).get("duration", 0) or 0)


def avg_fps(path):
    """The video stream's avg_frame_rate (None if ffprobe has none)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        num, den = r.stdout.strip().split("/")
        return float(num) / float(den) if float(den) and float(num) else None
    except ValueError:
        return None


def analysis_size(w, h):
    k = ANALYSIS_LONG / max(w, h)
    return max(2, int(round(w * k / 2)) * 2), max(2, int(round(h * k / 2)) * 2), k


def read_faces(path, src_w, src_h, k):
    """faces.json -> {"frames": sorted [(t, [(x, y, w, h) in analysis pixels])], "ranges": [(start, end, box)]}.
    1. tools/vision/faces.py output (t202): "per_frame" {"<t>": [[x0, y0, x1, y1, conf], ..]} (raw, unpadded, used
       first) and/or "faces" [{"start", "end", "box": [x0, y0, x1, y1]}] (padded ranges, used when per_frame is
       missing); all fractions of the frame.
    2. A plain list / {"frames": [...]}: each entry "t" (or "time") with "faces"/"boxes" as [x, y, w, h] lists or
       {"x","y","w","h"} / {"box": [...]} dicts. Values all <= 1 are fractions; otherwise source pixels."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    aw, ah = src_w * k, src_h * k
    if isinstance(d, dict) and ("per_frame" in d or ("faces" in d and isinstance(d["faces"], list)
                                                     and all("start" in f for f in d["faces"]))):
        def xywh(b):
            x0, y0, x1, y1 = [float(v) for v in b[:4]]
            return (x0 * aw, y0 * ah, (x1 - x0) * aw, (y1 - y0) * ah)
        if d.get("per_frame"):
            fr = sorted((float(t), [xywh(b) for b in bs]) for t, bs in d["per_frame"].items())
            return {"frames": fr, "ranges": [], "tol": max(0.05, float(d.get("step", 0.1)))}
        return {"frames": [], "ranges": [(float(f["start"]), float(f["end"]), xywh(f["box"])) for f in d["faces"]]}
    frames = d.get("frames", d.get("samples", [])) if isinstance(d, dict) else d
    if isinstance(d, dict) and d.get("width") and d.get("height"):
        src_w, src_h = float(d["width"]), float(d["height"])
        aw, ah = src_w * k, src_h * k
    out = []
    for fr in frames:
        t = fr.get("t", fr.get("time"))
        if t is None:
            continue
        boxes = []
        for b in fr.get("faces", fr.get("boxes", [])) or []:
            if isinstance(b, dict):
                b = b.get("box", b.get("bbox")) or [b.get("x"), b.get("y"), b.get("w"), b.get("h")]
            if not b or any(v is None for v in b[:4]):
                continue
            x, y, w, h = [float(v) for v in b[:4]]
            if max(x, y, w, h) <= 1.0:
                boxes.append((x * aw, y * ah, w * aw, h * ah))
            else:
                boxes.append((x * aw / src_w, y * ah / src_h, w * aw / src_w, h * ah / src_h))
        out.append((float(t), boxes))
    out.sort(key=lambda e: e[0])
    return {"frames": out, "ranges": [], "tol": 0.3}


def faces_at(faces, t):
    """Boxes for time t: the nearest per-frame entry within the tolerance, else every range covering t ([] = no face)."""
    best, tol = None, faces.get("tol", 0.3)
    for ft, boxes in faces["frames"]:
        if abs(ft - t) <= tol + 1e-6 and (best is None or abs(ft - t) < abs(best[0] - t)):
            best = (ft, boxes)
    if best is not None:
        return best[1]
    return [b for (s, e, b) in faces["ranges"] if s <= t < e]


def read_shots(path, duration):
    """-> list of (start, end) seconds."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if isinstance(d, dict) and "shots" in d:
        t, out = 0.0, []
        for s in d["shots"]:
            if "start" in s:
                out.append((float(s["start"]), float(s["end"])))
                continue
            dd = float(s.get("d", d.get("dur", 2.0)))
            out.append((t, t + dd)); t += dd
    elif isinstance(d, dict) and "cuts" in d:
        cuts = [0.0] + [float(c) for c in d["cuts"] if 0 < float(c) < duration] + [duration]
        out = list(zip(cuts, cuts[1:]))
    else:
        out = [(float(s["start"]), float(s["end"])) if isinstance(s, dict) else (float(s[0]), float(s[1])) for s in d]
    if out and duration and out[-1][1] < duration:              # the last shot runs to the end
        out[-1] = (out[-1][0], duration)
    return out


def scan(path, step, faces_path=None):
    """Decode once: a luma histogram every frame (cuts), the metrics and a thumbnail every `step` seconds."""
    W, H, fps, dur = probe(path)
    aw, ah, k = analysis_size(W, H)
    faces = read_faces(faces_path, W, H, k) if faces_path else None
    every = max(1, int(round(step * fps)))
    err = tempfile.TemporaryFile()                # ffmpeg's messages (a full stderr pipe would stall the decode)
    pr = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={aw}:{ah}:flags=area", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=err)
    fsz, i, hists, samples = aw * ah * 3, 0, [], []
    while True:
        b = pr.stdout.read(fsz)
        if len(b) < fsz:
            break
        u8 = np.frombuffer(b, np.uint8).reshape(ah, aw, 3)
        small = u8[::4, ::4]
        Y = small.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32) / 255
        hists.append(np.histogram(Y, 32, (0, 1))[0] / Y.size)
        if i % every == 0:
            t = i / fps
            m = frame_metrics(u8, faces_at(faces, t) if faces is not None else None)
            m["t"] = round(t, 3)
            samples.append((m, u8.copy()))
        i += 1
    pr.stdout.close()
    pr.wait()
    err.seek(0)
    msg = err.read().decode("utf-8", "replace").strip().splitlines()
    err.close()
    if i == 0:
        raise RuntimeError(f"ffmpeg decoded no frames from {path}")
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg stopped with code {pr.returncode} after {i} frames of {path}: "
                           f"{msg[-1][:200] if msg else 'no message'}")
    rate = avg_fps(path) or fps                  # the AVERAGE rate: a phone clip's r_frame_rate can be its peak
    if dur and i < MIN_DECODED * dur * rate:     # half-decoded: an error, never a grade verdict on part of the video
        raise RuntimeError(f"decoded only {i} of about {int(dur * rate)} frames of {path} "
                           f"({i / rate:.1f} of {dur:.1f} s): the file is cut short or damaged")
    return dict(path=path, size=f"{W}x{H}", fps=fps, frames=i, duration=round(dur or i / fps, 3), hists=hists,
                samples=samples)


def detect_shots(hists, fps, nframes):
    cuts, minlen = [0], max(1, int(round(0.5 * fps)))
    for i in range(1, len(hists)):
        if 0.5 * np.abs(hists[i] - hists[i - 1]).sum() > 0.35 and i - cuts[-1] >= minlen:
            cuts.append(i)
    cuts.append(nframes)
    return [(a / fps, b / fps) for a, b in zip(cuts, cuts[1:])]


def in_window(samples, a, b):
    got = [s for s in samples if a <= s[0]["t"] < b]
    if not got and samples:                                     # a shot shorter than the step: nearest sample
        mid = (a + b) / 2
        got = [min(samples, key=lambda s: abs(s[0]["t"] - mid))]
    return got


def mid_sample(got, a, b):
    mid = (a + b) / 2
    return min(got, key=lambda s: abs(s[0]["t"] - mid))


DELTA_KEYS = ["white_a", "white_b", "skin_hue", "skin_sat", "skin_clip", "luma_median", "crushed", "clipped", "sat_mean", "warmth"]


def deltas(a, b):
    return {k: (round(a[k] - b[k], 3) if a.get(k) is not None and b.get(k) is not None else None) for k in DELTA_KEYS}


def check(video, step=0.5, faces=None, shots=None, ref=None, profile="kids"):
    """Returns (report dict, thumbnails for the sheet)."""
    sc = scan(video, step, faces)
    rs = scan(ref, step) if ref else None
    shot_list = read_shots(shots, sc["duration"]) if shots else detect_shots(sc["hists"], sc["fps"], sc["frames"])
    rep = dict(video=video, size=sc["size"], duration=sc["duration"], step=step, profile=profile,
               thresholds=PROFILES[profile], skin_from="faces.json" if faces else "YCrCb mask",
               shots_from=shots or "cut detection", shots=[])
    thumbs = []
    for n, (a, b) in enumerate(shot_list):
        got = in_window(sc["samples"], a, b)
        if not got:
            continue
        agg = aggregate([s[0] for s in got])
        short = (b - a) < MIN_JUDGED_SHOT
        fl = [] if short else evaluate(agg, profile)
        sh = dict(shot=n, start=round(a, 2), end=round(b, 2), **agg, flags=fl,
                  verdict="SHORT" if short else ("FAIL" if fl else "PASS"))
        rthumb = None
        if rs:
            rgot = in_window(rs["samples"], a, b)
            if rgot:
                ragg = aggregate([s[0] for s in rgot])
                sh["ref"] = ragg
                sh["ref_flags"] = [] if short else evaluate(ragg, profile)
                sh["delta"] = deltas(agg, ragg)
                rthumb = mid_sample(rgot, a, b)[1]
        rep["shots"].append(sh)
        thumbs.append((sh, mid_sample(got, a, b)[1], rthumb))
    allm = [s[0] for s in sc["samples"]]
    ov = aggregate(allm)
    ov_flags = evaluate(ov, profile)
    bad = [s for s in rep["shots"] if s["flags"]]
    rep["overall"] = dict(**ov, flags=ov_flags, failed_shots=[f"#{s['shot']} {s['start']:.1f}-{s['end']:.1f}s: "
                                                              + ", ".join(s["flags"]) for s in bad])
    rep["verdict"] = "FAIL" if (bad or ov_flags) else "PASS"
    if rs:
        rov = aggregate([s[0] for s in rs["samples"]])
        rep["ref"] = dict(video=ref, size=rs["size"], duration=rs["duration"], overall=dict(**rov, flags=evaluate(rov, profile)),
                          verdict="FAIL" if (evaluate(rov, profile) or any(s.get("ref_flags") for s in rep["shots"])) else "PASS")
        rep["delta_overall"] = deltas(ov, rov)
    rep["samples"] = allm
    return rep, thumbs


# ---------- sheet ----------
def _font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fmt(v, f="{:.1f}"):
    return "-" if v is None else f.format(v)


def sheet_lines(s):
    return [f"#{s['shot']} {s['start']:.1f}-{s['end']:.1f}s  {s['verdict']}",
            f"white a/b {_fmt(s['white_a'])}/{_fmt(s['white_b'])}  warm {_fmt(s['warmth'])}",
            f"skin hue {_fmt(s['skin_hue'])} sat {_fmt(s['skin_sat'], '{:.2f}')} clip {_fmt(s['skin_clip'])}%",
            f"luma {_fmt(s['luma_median'], '{:.0f}')} crush {_fmt(s['crushed'])}% clip {_fmt(s['clipped'])}%",
            ", ".join(s["flags"][:2]) if s["flags"] else "ok",
            ", ".join(s["flags"][2:])]


def write_sheet(rep, thumbs, dst):
    if not thumbs:
        return
    th0 = thumbs[0][1]
    portrait = th0.shape[0] > th0.shape[1]
    tw = 180 if portrait else 300
    th = int(round(th0.shape[0] * tw / th0.shape[1]))
    pair = any(t[2] is not None for t in thumbs)
    cw = tw * (2 if pair else 1) + (4 if pair else 0)
    per = max(1, 1800 // (cw + 10))
    lab = 6 * 15 + 6
    rows = math.ceil(len(thumbs) / per)
    head = 46
    S = Image.new("RGB", (per * (cw + 10) + 10, head + rows * (th + lab + 14) + 10), (18, 18, 18))
    d = ImageDraw.Draw(S)
    fh, fs = _font(18), _font(12)
    o = rep["overall"]
    title = (f"{os.path.basename(os.path.dirname(rep['video']))}/{os.path.basename(rep['video'])}  {rep['verdict']}  "
             f"profile {rep['profile']}  white b {_fmt(o['white_b'])}  warmth {_fmt(o['warmth'])}  "
             f"skin sat {_fmt(o['skin_sat'], '{:.2f}')}  skin clip {_fmt(o['skin_clip'])}%")
    if pair:
        title += "   (left: ref, right: this)"
    d.text((10, 12), title, fill=(240, 240, 240), font=fh)
    for j, (s, cur, refimg) in enumerate(thumbs):
        x = 10 + (j % per) * (cw + 10)
        y = head + (j // per) * (th + lab + 14)
        col = (220, 50, 50) if s["flags"] else ((150, 150, 150) if s["verdict"] == "SHORT" else (60, 160, 80))
        d.rectangle([x - 3, y - 3, x + cw + 2, y + th + lab + 2], outline=col, width=3)
        px = x
        if pair:
            if refimg is not None:
                S.paste(Image.fromarray(refimg).resize((tw, th), Image.LANCZOS), (px, y))
            px += tw + 4
        S.paste(Image.fromarray(cur).resize((tw, th), Image.LANCZOS), (px, y))
        for k, line in enumerate(sheet_lines(s)):
            d.text((x + 2, y + th + 3 + k * 15), line, fill=col if k in (0, 4, 5) else (225, 225, 225), font=fs)
    S.save(dst, quality=88)


def main(argv):
    args = list(argv)

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default

    step = float(opt("--step", 0.5))
    faces, shots, ref, sheet = opt("--faces"), opt("--shots"), opt("--ref"), opt("--sheet")
    profile = opt("--profile", "kids")
    if profile not in PROFILES or len(args) != 2 or step <= 0:
        print(__doc__)
        return 2
    video, out = args
    try:
        rep, thumbs = check(video, step, faces, shots, ref, profile)
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}))
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    if sheet:
        os.makedirs(os.path.dirname(os.path.abspath(sheet)), exist_ok=True)
        write_sheet(rep, thumbs, sheet)
    o = rep["overall"]
    summary = dict(verdict=rep["verdict"], profile=profile, shots=len(rep["shots"]), failed_shots=o["failed_shots"],
                   overall_flags=o["flags"], white_b=o["white_b"], warmth=o["warmth"], skin_sat=o["skin_sat"],
                   skin_hue=o["skin_hue"], skin_clip=o["skin_clip"], skin_clip_max=o["skin_clip_max"], crushed=o["crushed"],
                   out=out, sheet=sheet)
    if ref:
        summary["ref_verdict"] = rep["ref"]["verdict"]
        summary["delta_overall"] = rep["delta_overall"]
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
