"""Step 5 of the kids-review skill: a bright, clean, NEUTRAL grade for kids' event footage (built on the 1107 Children
review v4: DJI indoor footage under fluorescent light). Copied from work/creative/1107-children/scripts/grade.py
(2026-11-08, task t200) with the per-shot fixes moved out of the code into a per-video file (--fix).

usage:
  python grade.py <in.mp4> <out.mp4> [--shots shots.json] [--fix grade-fix.json] [--strength 1.0] [--look neutral|warm]
  python grade.py <in.mp4> <sheet.jpg> --sheet [--shots shots.json] [--look ...]   before/after contact sheet, one frame per shot
  python grade.py <in.mp4> <dir> --stills [--shots shots.json] [--look ...]        full-size before/after PNGs, one per shot

Looks (--look):
  neutral  (default since v4, owner 2026-11-08: "don't make the video too orange and too warm")
           White balance corrected FULLY to neutral, measured per shot on the white walls / tables (bright, low-chroma
           pixels; the near-neutral midtones when a shot has no white surface; the clip average when it has neither),
           pulled 25 % toward the clip average so the shots match. Same exposure lift and highlight shoulder as v3.
           No warm bias, no peach highlights; a whisper of teal in the deep shadows only. A gentle filmic S-curve,
           a light NEUTRAL bloom, a very light vignette (the caption renderer adds its own), saturation +5 % with skin
           held at about +0 %, and a soft pull of over-saturated orange skin back toward natural.
  warm     the v3 look exactly (grade.before-v4.py): grey-world WB with warm/cool corrected only 25 %, a 1 % warm bias,
           teal shadows + peach highlights, a warm bloom, -12 % vignette, saturation +10 %. Only when the owner asks.
--fix      per-shot overrides of THIS video (template ../templates/grade-fix.json): {"shots": [{"from": <shot start s>,
           "stop": .., "wb": [r, g, b], "warm_desat": .., "why": ".."}]}. Without it, every shot is graded automatically.
           (1107 v4 used {"from": 34.2, "stop": 0.12, "wb": [0.985, 1.0, 1.03], "warm_desat": 0.25} on the mum-and-baby shot.)

Works for any size (1080x1920, 1920x1080, ...). Audio is copied unchanged; video is libx264 crf 14, yuv420p, 30 fps.
If the input video is a frame short of its audio (the blur pass's -shortest), the last frame is held to the audio length.

How it works (numpy through an ffmpeg pipe):
 1. Analysis pass at 192 px: per shot, the median luma, the grey-world cast of the near-neutral midtones and (neutral
    look) the cast of the white surfaces, in linear light. Shots come from shots.json or from cut detection.
 2. Per shot, a 3x256 LUT (cv2.LUT): white balance, exposure in linear light (+0.45 stop on average; darker shots get
    more, brighter less, 0.25-0.85 stop), a filmic contrast, a soft tanh shoulder from display 0.78 (faces and windows
    never clip) and a 1.2 % film black.
 3. Per pixel: saturation (skin protected), split tone, bloom / halation (quarter-res blur, screen blend), vignette.
 Skin = a soft YCrCb skin mask. The caption-card renderer adds its own (now near-neutral) grade arc later.
"""
import json, math, os, subprocess, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

FPS = 30
LOOKS = {
    # v3 (2026-11-07), unchanged
    "warm": dict(
        wb_mode="grey", base_stop=0.45, stop_min=0.25, stop_max=0.85, balance=0.6, target_med=0.44,
        tint_strength=0.7, temp_strength=0.25, wb_to_mean=0.5, warm_r=1.01, warm_b=0.99,
        pivot=0.42, contrast=1.10, s_curve=0.0, knee=0.78, black=0.012,
        sat=0.10, sat_skin=-0.14, skin_tame=0.0,
        teal=(-0.55, 0.12, 0.50), teal_amt=0.040, peach=(0.55, 0.28, -0.45), peach_amt=0.032,
        bloom=0.18, bloom_thr=0.70, bloom_sigma=0.018, halation=(1.0, 0.78, 0.62),
        vignette=0.12,
    ),
    # v4 (2026-11-08): bright, clean, neutral
    "neutral": dict(
        wb_mode="white", base_stop=0.45, stop_min=0.25, stop_max=0.85, balance=0.6, target_med=0.44,
        tint_strength=1.0, temp_strength=1.0, wb_to_mean=0.45, warm_r=1.0, warm_b=1.0,
        wb_clamp=(0.8, 1.32), white_min=0.55, white_chroma=0.22, white_frac=0.015,
        pivot=0.42, contrast=1.0, s_curve=0.16, knee=0.78, black=0.012,
        sat=0.05, sat_skin=-0.04, skin_tame=0.38, skin_tame_from=0.40,
        teal=(-0.55, 0.12, 0.50), teal_amt=0.008, peach=(0.55, 0.28, -0.45), peach_amt=0.0,
        bloom=0.14, bloom_thr=0.72, bloom_sigma=0.018, halation=(1.0, 0.98, 0.96),
        vignette=0.06,
    ),
}
# Per-shot overrides, matched by the shot's start time (s):
#   stop  exposure (replaces the computed stop)   wb  white-balance gains (replace the computed ones; neutral look: leave out)
#   warm_desat  extra desaturation (0-1) on orange / skin hues (hue 0-45 deg, any skin tone, soft ramps)
SHOT_FIXES = {"warm": [], "neutral": []}                 # per video now: --fix grade-fix.json
LOOK = "neutral"
P = LOOKS[LOOK]
SHOT_FIX = SHOT_FIXES[LOOK]


def set_look(name):
    global LOOK, P, SHOT_FIX
    LOOK, P, SHOT_FIX = name, LOOKS[name], SHOT_FIXES[name]


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration,nb_frames",
                          "-of", "json", p], capture_output=True, text=True).stdout
    st = json.loads(out)["streams"]
    v = next(s for s in st if s["codec_type"] == "video")
    a = next((s for s in st if s["codec_type"] == "audio"), None)
    return int(v["width"]), int(v["height"]), int(v.get("nb_frames", 0)), float(a["duration"]) if a else None


def decode(p, w=None, h=None, ss=None, n=None):
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    cmd += ["-i", p]
    if n is not None:
        cmd += ["-frames:v", str(n)]
    if w:
        cmd += ["-vf", f"scale={w}:{h}:flags=area"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE)


def lin(x):
    return np.power(np.clip(x, 0, None), 2.2)


def enc(x):
    return np.power(np.clip(x, 0, None), 1 / 2.2)


# ---------- shots ----------
def shots_from_json(path, nframes):
    d = json.load(open(path, encoding="utf-8"))
    t, cuts = 0.0, []
    for s in d["shots"]:
        cuts.append(int(round(t * FPS)))
        t += s.get("d", d.get("dur", 2.0))
    cuts.append(max(nframes, int(round(t * FPS))))
    return cuts


def detect_cuts(hists, nframes):
    cuts = [0]
    for i in range(1, len(hists)):
        d = 0.5 * np.abs(hists[i] - hists[i - 1]).sum()
        if d > 0.35 and i - cuts[-1] >= 15:
            cuts.append(i)
    cuts.append(nframes)
    return cuts


# ---------- analysis ----------
def analyse(src, W, H, shots_path):
    aw = 192
    ah = int(round(H * aw / W / 2)) * 2
    pr = decode(src, aw, ah)
    meds, neut, white, hists, n = [], [], [], [], 0
    while True:
        b = pr.stdout.read(aw * ah * 3)
        if len(b) < aw * ah * 3:
            break
        f = np.frombuffer(b, np.uint8).reshape(ah, aw, 3).astype(np.float32) / 255
        Y = f @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        meds.append(float(np.median(Y)))
        hists.append(np.histogram(Y, 32, (0, 1))[0] / Y.size)
        L = lin(f)
        mx, mn = f.max(2), f.min(2)
        m = (Y > 0.15) & (Y < 0.85) & ((mx - mn) < 0.18)
        neut.append(L[m].mean(0) if m.sum() > 50 else np.array([np.nan] * 3))
        # white surfaces (walls, tables, ceiling): bright, low chroma, not clipped
        wm = (Y > P.get("white_min", 0.55)) & (mx < 0.985) & ((mx - mn) < P.get("white_chroma", 0.22))
        white.append(L[wm].mean(0) if wm.mean() > P.get("white_frac", 0.015) else np.array([np.nan] * 3))
        n += 1
    pr.wait()
    cuts = shots_from_json(shots_path, n) if shots_path else detect_cuts(hists, n)
    shots = []
    for a, b in zip(cuts, cuts[1:]):
        b = min(b, n)
        if b <= a:
            continue
        med = float(np.median(meds[a:b]))
        nm = np.nanmean(np.array(neut[a:b]), 0)
        wh = np.array(white[a:b])
        ok = ~np.any(np.isnan(wh), 1)
        wv = wh[ok].mean(0) if ok.mean() >= 0.3 else np.array([np.nan] * 3)
        shots.append(dict(a=a, b=b, med=med, neutral=nm.tolist(), white=wv.tolist()))
    gains, src_of = [], []
    for s in shots:
        nm, wv = np.array(s["neutral"]), np.array(s["white"])
        if P["wb_mode"] == "white" and not np.any(np.isnan(wv)):
            g, k = wv.mean() / wv, "white"
        elif not np.any(np.isnan(nm)):
            g, k = nm.mean() / nm, "midtones"
        else:
            g, k = None, "clip mean"
        gains.append(g); src_of.append(k)
    if P["wb_mode"] == "grey":                                  # v3 exactly: a shot without neutrals counts as gain 1
        gains = [np.ones(3) if g is None else g for g in gains]
    known = [g for g in gains if g is not None]
    gmean = np.exp(np.mean(np.log(np.array(known)), 0)) if known else np.ones(3)
    gains = [gmean if g is None else g for g in gains]
    want = [math.log2(lin(P["target_med"]) / max(1e-4, lin(s["med"]))) for s in shots]
    wmean = float(np.mean(want))
    for s, g, w, k in zip(shots, gains, want, src_of):
        g = np.exp((1 - P["wb_to_mean"]) * np.log(g) + P["wb_to_mean"] * np.log(gmean))
        g = g / g[1]
        temp = math.sqrt(g[2] / g[0])          # > 1: the measurement wants it cooler (bluer)
        tint = 1 / math.sqrt(g[0] * g[2])      # < 1: green cast to pull out (toward magenta)
        ts = temp ** P["temp_strength"]
        g = np.array([1 / ts, tint ** P["tint_strength"], ts])
        g = g * np.array([P["warm_r"], 1.0, P["warm_b"]])
        g = np.clip(g / (g @ np.array([0.2126, 0.7152, 0.0722])), *P.get("wb_clamp", (0.85, 1.2)))
        s["wb"] = [round(float(x), 4) for x in g]
        s["wb_from"] = k
        s["stop"] = round(float(np.clip(P["base_stop"] + P["balance"] * (w - wmean), P["stop_min"], P["stop_max"])), 3)
    for s in shots:                                             # per-shot fixes
        for fx in SHOT_FIX:
            if abs(s["a"] / FPS - fx["from"]) < 0.05:
                s["stop_auto"], s["wb_auto"] = s["stop"], s["wb"]
                s["stop"] = fx.get("stop", s["stop"])
                if "wb" in fx:
                    s["wb"] = list(fx["wb"])
                s["warm_desat"], s["fix"] = fx.get("warm_desat", 0), fx["why"]
    return n, shots


# ---------- grade ----------
def make_lut(wb, stop):
    x = np.arange(256, dtype=np.float32) / 255
    k = P["knee"]
    out = np.zeros((256, 3), np.float32)
    for c in range(3):
        d = enc(lin(x) * wb[c] * (2 ** stop))            # exposure in linear light, back to display
        d = P["pivot"] * np.power(d / P["pivot"], P["contrast"])   # filmic contrast around the pivot
        if P.get("s_curve"):                             # gentle S: a soft toe and a soft lift into the shoulder
            e = np.clip(d, 0, 1)
            d = d + P["s_curve"] * (e * e * (3 - 2 * e) - e)
        d = np.where(d <= k, d, k + (1 - k) * np.tanh((d - k) / (1 - k)))  # soft shoulder, never reaches 1.0 hard
        d = P["black"] + (1 - P["black"]) * d
        out[:, c] = d
    return np.clip(np.round(out * 255), 0, 255).astype(np.uint8).reshape(1, 256, 3)


class Grader:
    def __init__(self, W, H, strength=1.0):
        self.W, self.H, self.k = W, H, strength
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        t = np.clip((r - 0.35) / 0.65, 0, 1)
        self.vig = (1 - P["vignette"] * strength * t * t * (3 - 2 * t)).astype(np.float32)[..., None]
        self.teal = np.array(P["teal"], np.float32) * P["teal_amt"] * strength
        self.peach = np.array(P["peach"], np.float32) * P["peach_amt"] * strength
        self.hal = np.array(P["halation"], np.float32)
        self.luts = {}

    def frame(self, rgb, shot):
        key = id(shot)
        if key not in self.luts:
            stop = shot["stop"] * self.k
            wb = [1 + (g - 1) * self.k for g in shot["wb"]]
            self.luts[key] = make_lut(wb, stop)
        u = cv2.LUT(rgb, self.luts[key])
        f = u.astype(np.float32) * (1 / 255)
        Y = f @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        # skin mask (soft) from YCrCb
        ycc = cv2.cvtColor(u, cv2.COLOR_RGB2YCrCb).astype(np.float32)
        dcr, dcb = (ycc[..., 1] - 153) / 20, (ycc[..., 2] - 108) / 22
        skin = np.clip(1.6 - np.sqrt(dcr * dcr + dcb * dcb), 0, 1) * np.clip((ycc[..., 0] - 40) / 40, 0, 1)
        # saturation
        sat = 1 + self.k * (P["sat"] + (P["sat_skin"] - P["sat"]) * skin)
        wd = shot.get("warm_desat", 0)
        if wd or P.get("skin_tame"):
            hsv = cv2.cvtColor(u, cv2.COLOR_RGB2HSV).astype(np.float32)
            hue, sv = hsv[..., 0] * 2.0, hsv[..., 1] / 255           # degrees, 0-1
            hm = np.clip((50 - np.abs(hue - 22)) / 15, 0, 1)        # orange / skin hues
            if wd:                                                  # per-shot: orange / skin hues pulled toward neutral
                sat = sat * (1 - wd * self.k * hm * np.clip((sv - 0.15) / 0.2, 0, 1))
            if P.get("skin_tame"):                                  # neutral look: only skin that is over-saturated (HSV sat > 0.40)
                over = np.clip((sv - P.get("skin_tame_from", 0.42)) / 0.25, 0, 1) * skin * hm
                sat = sat * (1 - P["skin_tame"] * self.k * over)
        f = Y[..., None] + (f - Y[..., None]) * sat[..., None]
        # split tone
        ws = np.clip(1 - Y / 0.5, 0, 1) ** 1.5 * (1 - 0.8 * skin)
        wh = np.clip((Y - 0.55) / 0.45, 0, 1) ** 1.2 * (1 - 0.9 * skin)
        f += ws[..., None] * self.teal + wh[..., None] * self.peach
        # bloom / halation
        if P["bloom"] > 0:
            sw, sh = self.W // 4, self.H // 4
            low = cv2.resize(f, (sw, sh), interpolation=cv2.INTER_AREA)
            ly = low @ np.array([0.2126, 0.7152, 0.0722], np.float32)
            br = low * (np.clip((ly - P["bloom_thr"]) / (1 - P["bloom_thr"]), 0, 1) ** 2)[..., None]
            sig = P["bloom_sigma"] * max(self.W, self.H) / 4
            br = cv2.GaussianBlur(br, (0, 0), sig) * self.hal
            br = cv2.resize(br, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
            a = P["bloom"] * self.k
            f = 1 - (1 - np.clip(f, 0, 1)) * (1 - a * br)
        f *= self.vig
        return np.clip(f * 255 + 0.5, 0, 255).astype(np.uint8)


def shot_at(shots, i):
    for s in shots:
        if s["a"] <= i < s["b"]:
            return s
    return shots[-1]


# ---------- modes ----------
def run(src, dst, shots_path, strength):
    W, H, _, adur = probe(src)
    n, shots = analyse(src, W, H, shots_path)
    target = max(n, int(round(adur * FPS))) if adur else n
    g = Grader(W, H, strength)
    dec = decode(src)
    encp = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "14", "-preset", "medium",
                             "-pix_fmt", "yuv420p", "-c:a", "copy", dst], stdin=subprocess.PIPE)
    fsz, i, last = W * H * 3, 0, None
    while True:
        b = dec.stdout.read(fsz)
        if len(b) < fsz:
            break
        out = g.frame(np.frombuffer(b, np.uint8).reshape(H, W, 3), shot_at(shots, i))
        last = out.tobytes()
        encp.stdin.write(last)
        i += 1
    held = 0
    while i < target and last is not None:
        encp.stdin.write(last); i += 1; held += 1
    encp.stdin.close(); encp.wait(); dec.wait()
    json.dump({"src": src, "look": LOOK, "params": P, "strength": strength, "shots": shots}, open(dst + ".grade.json", "w"), indent=1)
    print(json.dumps({"out": dst, "look": LOOK, "size": f"{W}x{H}", "frames": i, "input_frames": n, "held_last": held, "shots": len(shots),
                      "stops": [s["stop"] for s in shots], "ok": encp.returncode == 0}))


def pairs(src, shots_path, strength):
    W, H, _, _ = probe(src)
    n, shots = analyse(src, W, H, shots_path)
    g = Grader(W, H, strength)
    out = []
    for k, s in enumerate(shots):
        t = (s["a"] + s["b"]) / 2 / FPS
        pr = decode(src, ss=t, n=1)
        b = pr.stdout.read(W * H * 3); pr.wait()
        before = np.frombuffer(b, np.uint8).reshape(H, W, 3)
        out.append((k, t, s, before, g.frame(before, s)))
    return W, H, out


def sheet(src, dst, shots_path, strength):
    W, H, items = pairs(src, shots_path, strength)
    tw = 216 if H > W else 360
    th = int(round(H * tw / W))
    per = 5 if H > W else 4
    rows = math.ceil(len(items) / per)
    gap, lab = 6, 22
    S = Image.new("RGB", (per * (2 * tw + gap) + gap, rows * (th + lab + gap) + gap), (20, 20, 20))
    d = ImageDraw.Draw(S)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for j, (k, t, s, a, b) in enumerate(items):
        x, y = gap + (j % per) * (2 * tw + gap), gap + (j // per) * (th + lab + gap)
        S.paste(Image.fromarray(a).resize((tw, th), Image.LANCZOS), (x, y + lab))
        S.paste(Image.fromarray(b).resize((tw, th), Image.LANCZOS), (x + tw, y + lab))
        d.text((x + 3, y + 3), f"#{k} {t:.1f}s  before | after  {s['stop']:+.2f} st  med {s['med']:.2f}", fill=(230, 230, 230), font=font)
    S.save(dst, quality=90)
    print(json.dumps({"sheet": dst, "look": LOOK, "shots": len(items), "stops": [s["stop"] for _, _, s, _, _ in items],
                      "wb": [s["wb"] for _, _, s, _, _ in items]}))


def stills(src, dst, shots_path, strength):
    os.makedirs(dst, exist_ok=True)
    W, H, items = pairs(src, shots_path, strength)
    for k, t, s, a, b in items:
        Image.fromarray(np.concatenate([a, b], 1)).save(os.path.join(dst, f"shot{k:02d}.jpg"), quality=92)
    print(json.dumps({"dir": dst, "look": LOOK, "shots": len(items)}))


if __name__ == "__main__":
    args = sys.argv[1:]
    def opt(name, default=None):
        if name in args:
            i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
        return default
    shots_path = opt("--shots")
    strength = float(opt("--strength", 1.0))
    set_look(opt("--look", "neutral"))
    fix_path = opt("--fix")
    if fix_path:
        SHOT_FIX = json.load(open(fix_path, encoding="utf-8")).get("shots", [])
    mode = "run"
    for m in ("--sheet", "--stills"):
        if m in args:
            args.remove(m); mode = m[2:]
    src, dst = args[0], args[1]
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    {"run": run, "sheet": sheet, "stills": stills}[mode](src, dst, shots_path, strength)
