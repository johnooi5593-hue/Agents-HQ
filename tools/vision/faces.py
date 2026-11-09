"""Face boxes over time, for the avoid lists of stickers, bubbles and caption cards (board t202, 2026-11-08).

USAGE
    python faces.py <video.mp4> <out.json> [--step 0.1] [--shots shots.json] [--min 0.04] [--pad 0.35]
                    [--conf 0.4] [--grow 1.5] [--detector auto|yunet|ultraface|haar] [--sheet out.jpg]
                    [--sheet-every 0.5] [--no-per-frame]

    --step     seconds between samples (0.1 = 10 looks a second).
    --shots    a kids-review shots.json ({"dur": 2.0, "shots": [{"d": 2.2}, ...]}) or {"cuts": [s, ...]}: tracks and
               ranges never run across a cut.
    --min      smallest face kept, as a fraction of the frame's SHORT side (0.04 = 43 px on 1080). Also sets the
               detector's tiling so faces this small are seen.
    --pad      grow every face box by this fraction of its width / height on each side (the top by 1.4x as much,
               for hair and paper hats).
    --conf     detector score threshold (0..1).
    --grow     a face range is split when its box would grow past this x the mean padded face box (a moving face
               gets several snug boxes instead of one huge one).
    --sheet    a contact sheet with the boxes drawn (yellow = raw detection, red = the padded range box in the JSON),
               one frame every --sheet-every seconds, for a human check with the Read tool.

OUTPUT (out.json)
    {"size": [W, H], "aspect": "9x16", "duration": 52.2, "step": 0.1, "detector": "ultraface-rfb-640",
     "faces": [{"start": 0.0, "end": 2.25, "box": [x0, y0, x1, y1], "face": [x0, y0, x1, y1], "conf": 0.97,
                "hits": 21, "track": 3}],
     "per_frame": {"0.000": [[x0, y0, x1, y1, conf], ...]}}           (per_frame = raw, unpadded detections)
    box = the padded avoid box (the union over the range); face = the mean unpadded detection in the range.
    box values are FRACTIONS of the frame, like every avoid box in stickers.json. "size" is the displayed size
    (a 90-degree rotation tag is applied, as ffmpeg does when it decodes).

DETECTORS (no downloads). --detector auto = ultraface, else haar. YuNet is never chosen on its own.
    ultraface  UltraFace RFB-640 (MIT, ONNX Model Zoo) in tools/vision/models/ultraface-rfb-640/, run with
               onnxruntime on overlapping 4:3 tiles plus one whole-frame pass; both model files must match
               model-manifest.json AND the PINNED sizes + sha256 in this script before they load
    haar       OpenCV's frontal + profile Haar cascades from cv2.data.haarcascades (not shipped with the
               opencv-python-headless 5.0.0 on this computer)
    yunet      only with an explicit --detector yunet: a *yunet*.onnx in tools/vision/models, listed in a
               model-manifest.json beside it AND pinned in PINNED (none is today, so it is refused until a pin is
               added on purpose); loaded from the verified bytes
Prints one JSON line when done: {"ok": true, ...}, or {"ok": false, "error": "..."} with exit code 1 (an unreadable
video, no video stream or duration, ffmpeg stopping early or decoding under 90% of the expected samples, a model that
fails its checksum). It never reports "no faces" for a video it could only half decode.
"""
import argparse, bisect, hashlib, json, math, os, subprocess, sys, tempfile, threading, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
MODELS = os.path.join(HERE, 'models')
ULTRAFACE = os.path.join(MODELS, 'ultraface-rfb-640', 'version-RFB-640.onnx')
MANIFEST = os.path.join(MODELS, 'ultraface-rfb-640', 'model-manifest.json')
FF = os.environ.get('FFMPEG', 'ffmpeg')
FP = os.environ.get('FFPROBE', 'ffprobe')
NOWIN = 0x08000000 if os.name == 'nt' else 0
TOP_PAD = 1.4                      # the top of a face box grows this much more than the sides (hair, hats)
MIN_DECODED = 0.9                  # fewer samples than this x duration / step = a failed decode, not "no faces"
# The UltraFace files, pinned here as well as in model-manifest.json (security review 2026-11-09): a swapped model
# file AND an edited manifest still don't load. Change both together, on purpose, if the model is ever replaced.
PINNED = {'version-RFB-640.onnx': (1588012, '8f4c659275977e7a3bfbfa339a9c769ad793df50f9c0baa8c14b11baa1646430'),
          'version-RFB-640.ort-ready.onnx': (1577010, 'a9e7cb5308de493844547e3ffdc4458f68fc81da9672f33f1074ed149db36578')}


class VisionError(RuntimeError):
    """A failure faces.py reports as one JSON line ({"ok": false, "error": ...}) and exit code 1."""


def out(**kw):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(json.dumps(kw, ensure_ascii=False))


# ---------------------------------------------------------------- boxes ----------------------------------------------
def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b):
    i = inter(a, b)
    u = area(a) + area(b) - i
    return i / u if u > 0 else 0.0


def union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def nms(dets, thr=0.3, contain=0.7):
    """dets: [[x0, y0, x1, y1, conf], ...]. Keeps the best box of each cluster; also drops a box mostly inside a kept
    one (a face cut by a tile edge)."""
    keep = []
    for d in sorted(dets, key=lambda d: -d[4]):
        ok = True
        for k in keep:
            i = inter(d, k)
            if iou(d, k) > thr or (min(area(d), area(k)) > 0 and i / min(area(d), area(k)) > contain):
                ok = False
                break
        if ok:
            keep.append(list(d))
    return keep


def pad_box(b, pad, top=TOP_PAD):
    w, h = b[2] - b[0], b[3] - b[1]
    return [max(0.0, b[0] - pad * w), max(0.0, b[1] - pad * top * h), min(1.0, b[2] + pad * w), min(1.0, b[3] + pad * h)]


# ---------------------------------------------------------------- video ----------------------------------------------
def probe(video):
    p = subprocess.run([FP, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate,duration:stream_side_data=rotation:stream_tags=rotate',
                        '-show_entries', 'format=duration', '-of', 'json', video],
                       capture_output=True, text=True, creationflags=NOWIN)
    if p.returncode != 0 or not p.stdout.strip():
        raise VisionError(f'ffprobe could not read {video}: {p.stderr.strip()[:300]}')
    try:
        j = json.loads(p.stdout)
    except ValueError:
        raise VisionError(f'ffprobe gave no readable answer for {video}')
    if not j.get('streams'):
        raise VisionError(f'no video stream in {video}')
    s = j['streams'][0]
    try:
        W, H = int(s['width']), int(s['height'])
    except (KeyError, TypeError, ValueError):
        raise VisionError(f'the video stream of {video} has no width / height')
    dur = 0.0
    for v in ((j.get('format') or {}).get('duration'), s.get('duration')):
        try:
            dur = dur or float(v)
        except (TypeError, ValueError):
            pass
    if not dur > 0:
        raise VisionError(f'no duration for {video} (a still image, or a broken file)')
    rot = 0
    for sd in s.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    if not rot and (s.get('tags') or {}).get('rotate'):
        rot = int(float(s['tags']['rotate']))
    if abs(rot) % 180 == 90:                       # DJI clips: stored 1728x3072 with a 90-degree tag (Lessons 2026-11-03)
        W, H = H, W
    try:
        num, den = (s.get('r_frame_rate') or '30/1').split('/')
        fps = float(num) / float(den) if float(den) else 30.0
    except ValueError:
        fps = 30.0
    return W, H, dur, fps


def cut_times(path, fps=30.0):
    """Cut times in seconds (0 first) from a kids-review shots.json, or a {"cuts": [...]} / plain list file."""
    if not path:
        return [0.0]
    with open(path, encoding='utf-8') as f:
        j = json.load(f)
    if isinstance(j, list):
        cuts = [float(x) for x in j]
    elif 'cuts' in j:
        cuts = [float(x) for x in j['cuts']]
    else:
        cuts, t = [], 0.0
        for s in j.get('shots', []):
            cuts.append(round(t, 3))
            t += round(float(s.get('d', j.get('dur', 2.0))) * fps) / fps
    cuts = sorted(set([0.0] + [round(c, 3) for c in cuts]))
    return cuts


def frames(video, step, W, H, short=720):
    """Yields (index, RGB frame) every `step` seconds, decoded at `short` px on the short side (never upscaled)."""
    k = min(1.0, short / min(W, H))
    Wd, Hd = int(round(W * k / 2)) * 2, int(round(H * k / 2)) * 2
    r = Fraction(1 / step).limit_denominator(1000)
    cmd = [FF, '-v', 'error', '-i', video, '-vf', f'fps={r.numerator}/{r.denominator},scale={Wd}:{Hd}:flags=area',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    err = tempfile.TemporaryFile()                  # ffmpeg's messages (a pipe could fill up and stall the decode)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, creationflags=NOWIN)
    n, fsz = 0, Wd * Hd * 3
    try:
        while True:
            raw = p.stdout.read(fsz)
            if len(raw) < fsz:
                break
            yield n, np.frombuffer(raw, np.uint8).reshape(Hd, Wd, 3)
            n += 1
        p.stdout.close()
        if p.wait() != 0:                           # reached only when ffmpeg ended by itself (not when the caller stops)
            err.seek(0)
            msg = err.read().decode('utf-8', 'replace').strip().splitlines()
            raise VisionError(f'ffmpeg stopped with code {p.returncode} after {n} samples of {video}: '
                              f'{msg[-1][:300] if msg else "no message"}')
    finally:
        if p.poll() is None:                        # the caller stopped early: don't leave ffmpeg running
            p.kill()
        p.stdout.close()
        p.wait()
        err.close()


# ---------------------------------------------------------------- detectors ------------------------------------------
def find_yunet():
    for base in (MODELS,):                         # only the office's own model folder (security review 2026-11-09)
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in ('node_modules', '.git', '__pycache__')]
            for f in fn:
                if 'yunet' in f.lower() and f.lower().endswith('.onnx'):
                    return os.path.join(dp, f)
    return None


def haar_paths():
    import cv2
    d = getattr(getattr(cv2, 'data', None), 'haarcascades', '') or ''
    fr, pr = os.path.join(d, 'haarcascade_frontalface_default.xml'), os.path.join(d, 'haarcascade_profileface.xml')
    return (fr, pr) if os.path.exists(fr) else None


def model_sums(manifest=MANIFEST):
    """{file name: (bytes, sha256)} for the UltraFace files model-manifest.json lists (the original and the ort-ready copy)."""
    with open(manifest, encoding='utf-8') as f:
        m = json.load(f)
    out = {}
    for e in (m, m.get('ortReady') or {}):
        if e.get('file') and e.get('sha256'):
            out[e['file']] = (e.get('bytes'), str(e['sha256']).lower())
    return out


def verify_model(path, manifest=MANIFEST, pinned=PINNED, require_pin=False):
    """Raises VisionError unless path is listed in the manifest with this exact size and sha256, and (for a file named in
    PINNED) the manifest entry and the file both match the pin in this script. require_pin: a file with no pin is
    refused outright (YuNet). Returns the verified bytes."""
    name = os.path.basename(path)
    if require_pin and name not in pinned:
        raise VisionError(f'{name} is not pinned in faces.py (PINNED): refusing to load it')
    try:
        sums = model_sums(manifest)
    except (OSError, ValueError) as e:
        raise VisionError(f'model manifest unreadable ({manifest}): {e}')
    want = sums.get(name)
    if not want:
        raise VisionError(f'{name} is not listed in {manifest}: refusing to load it')
    pin = pinned.get(name)
    if pin and (want[1] != pin[1] or (want[0] is not None and want[0] != pin[0])):
        raise VisionError(f'{manifest} lists another sha256 for {name} than faces.py pins: refusing to load it')
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        raise VisionError(f'cannot read {path}: {e}')
    if (want[0] is not None and len(data) != want[0]) or hashlib.sha256(data).hexdigest() != want[1]:
        raise VisionError(f'{name} does not match its sha256 in {manifest}: refusing to load it')
    return data                                     # load THESE bytes, not the path again (no swap after the check)


class UltraFace:
    name = 'ultraface-rfb-640'
    IW, IH = 640, 480
    MIN_PX = 16                                    # smallest face (model px) the tiles are sized for (anchors: 10-16 px)

    def __init__(self, path=ULTRAFACE, conf=0.6, min_frac=0.04):
        fast = path.replace('.onnx', '.ort-ready.onnx')     # same weights, initializers out of the input list
        self.path = fast if os.path.exists(fast) else path  # (onnx_strip_inputs.py): ~2.5x faster in onnxruntime
        for p in {path, self.path}:                         # both files on disk must match the manifest and the pins
            if os.path.exists(p) or p == self.path:
                data = verify_model(p)
                if p == self.path:
                    self.model = data                        # every session loads these verified bytes
        self.conf, self.min_frac = conf, min_frac
        self.windows = None
        self.local = threading.local()
        self.session()                                       # fail early if the model does not load

    def session(self):
        s = getattr(self.local, 'sess', None)
        if s is None:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.log_severity_level = 3              # the original export prints one warning per weight otherwise
            so.intra_op_num_threads = int(os.environ.get('HQ_VISION_INTRA', '2'))
            s = self.local.sess = ort.InferenceSession(self.model, so, providers=['CPUExecutionProvider'])
            self.inp = s.get_inputs()[0].name
        return s

    def plan(self, Wd, Hd):
        """Whole frame + overlapping 4:3 tiles sized so a min_frac face is >= MIN_PX on the model input."""
        win = [(0, 0, Wd, Hd)]
        need = self.MIN_PX / max(1.0, self.min_frac * min(Wd, Hd))       # model px per decoded px
        if min(self.IW / Wd, self.IH / Hd) < need:
            tw, th = min(Wd, int(self.IW / need)), min(Hd, int(self.IH / need))

            def pos(L, t):
                if t >= L:
                    return [0]
                n = math.ceil((L - 0.25 * t) / (0.75 * t))
                return [int(round(i * (L - t) / max(1, n - 1))) for i in range(max(2, n))]
            win += [(x, y, tw, th) for y in pos(Hd, th) for x in pos(Wd, tw)]
        self.windows = win
        return win

    def _run(self, img):
        x = (img.astype(np.float32) - 127.0) / 128.0
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        scores, boxes = self.session().run(None, {self.inp: x})
        sc = scores[0, :, 1]
        m = sc > self.conf
        return boxes[0][m], sc[m]

    def detect(self, frame):
        import cv2
        Hd, Wd = frame.shape[:2]
        if self.windows is None:
            self.plan(Wd, Hd)
        dets = []
        for x0, y0, tw, th in self.windows:
            s = min(self.IW / tw, self.IH / th)
            tile = frame[y0:y0 + th, x0:x0 + tw]
            rw, rh = max(1, int(round(tw * s))), max(1, int(round(th * s)))
            canvas = np.zeros((self.IH, self.IW, 3), np.uint8)
            canvas[:rh, :rw] = cv2.resize(tile, (rw, rh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            bx, sc = self._run(canvas)
            for b, c in zip(bx, sc):
                px = [b[0] * self.IW / s + x0, b[1] * self.IH / s + y0, b[2] * self.IW / s + x0, b[3] * self.IH / s + y0]
                dets.append([px[0] / Wd, px[1] / Hd, px[2] / Wd, px[3] / Hd, float(c)])
        return clean(nms(dets), self.min_frac, Wd, Hd)


class YuNet:
    name = 'yunet'

    def __init__(self, path, conf=0.6, min_frac=0.04, data=None):
        """data = the bytes verify_model() checked; loaded from memory so the file can't be swapped after the check."""
        import cv2
        if data is None:
            raise VisionError('YuNet needs a verified model (make_detector("yunet"))')
        try:
            self.det = cv2.FaceDetectorYN.create('onnx', np.frombuffer(data, np.uint8), np.empty(0, np.uint8),
                                                 (320, 320), conf, 0.3, 5000)
        except (cv2.error, TypeError):              # an OpenCV without the buffer form: the path, checked just now
            self.det = cv2.FaceDetectorYN.create(path, '', (320, 320), conf, 0.3, 5000)
        self.min_frac, self.size = min_frac, None

    def detect(self, frame):
        import cv2
        Hd, Wd = frame.shape[:2]
        if self.size != (Wd, Hd):
            self.det.setInputSize((Wd, Hd)); self.size = (Wd, Hd)
        _, f = self.det.detect(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        dets = [] if f is None else [[r[0] / Wd, r[1] / Hd, (r[0] + r[2]) / Wd, (r[1] + r[3]) / Hd, float(r[-1])] for r in f]
        return clean(nms(dets), self.min_frac, Wd, Hd)


class Haar:
    name = 'haar-frontal+profile'

    def __init__(self, paths, conf=0.6, min_frac=0.04):
        import cv2
        self.fr, self.pr = cv2.CascadeClassifier(paths[0]), cv2.CascadeClassifier(paths[1])
        self.min_frac = min_frac

    def detect(self, frame):
        import cv2
        Hd, Wd = frame.shape[:2]
        g = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY))
        mn = max(12, int(self.min_frac * min(Wd, Hd)))
        dets = []
        for casc, flip in ((self.fr, False), (self.pr, False), (self.pr, True)):
            img = cv2.flip(g, 1) if flip else g
            for x, y, w, h in casc.detectMultiScale(img, 1.1, 5, minSize=(mn, mn)):
                if flip:
                    x = Wd - x - w
                dets.append([x / Wd, y / Hd, (x + w) / Wd, (y + h) / Hd, 0.5])
        return clean(nms(dets), self.min_frac, Wd, Hd)


def clean(dets, min_frac, W, H):
    """Clamp to the frame and drop faces smaller than min_frac of the short side."""
    res = []
    short = min(W, H)
    for d in dets:
        b = [float(min(1.0, max(0.0, v))) for v in d[:4]]
        if b[2] <= b[0] or b[3] <= b[1]:
            continue
        if max((b[2] - b[0]) * W, (b[3] - b[1]) * H) < min_frac * short:
            continue
        res.append(b + [float(d[4])])
    return res


def make_detector(kind='auto', conf=0.6, min_frac=0.04):
    """auto = the pinned UltraFace, else Haar. YuNet only on an explicit --detector yunet, and only a file listed in a
    model-manifest.json beside it AND pinned in PINNED, with a matching size + sha256 (security review 2026-11-09: a
    file dropped into tools/vision/models must never be picked up on its own)."""
    if kind == 'yunet':
        y = find_yunet()
        if not y:
            raise VisionError('no *yunet*.onnx in tools/vision/models')
        data = verify_model(y, os.path.join(os.path.dirname(y), 'model-manifest.json'), require_pin=True)
        return YuNet(y, conf, min_frac, data)
    if kind in ('auto', 'ultraface'):
        if os.path.exists(ULTRAFACE):
            return UltraFace(ULTRAFACE, conf, min_frac)
        if kind == 'ultraface':
            raise VisionError(f'missing {ULTRAFACE}')
    if kind in ('auto', 'haar'):
        hp = haar_paths()
        if hp:
            return Haar(hp, conf, min_frac)
    raise VisionError('no face detector on disk: no UltraFace model, and cv2.data.haarcascades has no cascades '
                      '(see tools/vision/README.md)')


# ---------------------------------------------------------------- tracking + ranges ----------------------------------
def seg_of(t, cuts):
    return bisect.bisect_right(cuts, t + 1e-6) - 1


def _match(a, b):
    """How well detection b continues track box a (0 = no)."""
    o = iou(a, b)
    if o >= 0.15:
        return o
    ca = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2); cb = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    side = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
    dist = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
    return 0.1 * (1 - dist / (0.6 * side)) if side > 0 and dist < 0.6 * side else 0.0


def track(samples, step, cuts=(0.0,), max_gap=0.3):
    """samples: [(t, [[x0, y0, x1, y1, conf], ...]), ...] sorted by t. Links boxes of neighbouring samples into tracks
    (never across a cut) and fills a gap of up to max_gap seconds by interpolation, so a face the detector loses for a
    few samples keeps its box. Returns [{"id", "pts": [{"t", "box", "conf", "real"}]}]."""
    cuts = sorted(set([0.0] + list(cuts)))
    tracks, nid = [], 0
    for t, dets in samples:
        sg = seg_of(t, cuts)
        live = [k for k in tracks if k['seg'] == sg and t - k['pts'][-1]['t'] <= max_gap + step + 1e-6]
        pairs = sorted(((_match(k['pts'][-1]['box'], d[:4]), ki, di) for ki, k in enumerate(live) for di, d in enumerate(dets)),
                       reverse=True)
        used_k, used_d = set(), set()
        for sc, ki, di in pairs:
            if sc <= 0 or ki in used_k or di in used_d:
                continue
            used_k.add(ki); used_d.add(di)
            k, d = live[ki], dets[di]
            last = k['pts'][-1]
            n = int(round((t - last['t']) / step))
            for j in range(1, n):                                     # fill the missed samples
                u = j / n
                k['pts'].append({'t': round(last['t'] + j * step, 4), 'conf': min(last['conf'], d[4]), 'real': False,
                                 'box': [last['box'][i] + (d[i] - last['box'][i]) * u for i in range(4)]})
            k['pts'].append({'t': t, 'box': list(d[:4]), 'conf': d[4], 'real': True})
        for di, d in enumerate(dets):
            if di not in used_d:
                tracks.append({'id': nid, 'seg': sg, 'pts': [{'t': t, 'box': list(d[:4]), 'conf': d[4], 'real': True}]})
                nid += 1
    return tracks


def smooth(pts):
    """Median of 3 on every coordinate (removes one-sample jumps, keeps the ends)."""
    if len(pts) < 3:
        return [dict(p) for p in pts]
    res = []
    for i, p in enumerate(pts):
        w = pts[max(0, i - 1):i + 2]
        q = dict(p)
        q['box'] = [float(np.median([x['box'][c] for x in w])) for c in range(4)]
        res.append(q)
    return res


def ranges(tracks, step, cuts=(0.0,), duration=None, pad=0.25, min_hits=2, single_conf=0.8, grow=1.8):
    """Tracks -> [{"start", "end", "box", "conf", "hits", "track"}]. A track with fewer than min_hits real detections is
    kept only when its best score is >= single_conf (one-sample flicker is usually not a face). A range is split when the
    union of its padded boxes would grow past `grow` x their mean area (a moving face gets several snug boxes, not one
    huge one). Each range covers half a step before its first and after its last sample, inside its shot."""
    cuts = sorted(set([0.0] + list(cuts)))
    res = []
    for k in tracks:
        real = [p for p in k['pts'] if p['real']]
        if not real or (len(real) < min_hits and max(p['conf'] for p in real) < single_conf):
            continue
        sg = k.get('seg', seg_of(k['pts'][0]['t'], cuts))
        s0 = cuts[sg]
        s1 = cuts[sg + 1] if sg + 1 < len(cuts) else (duration if duration is not None else float('inf'))
        pts = smooth(k['pts'])
        groups, cur = [], []
        for p in pts:
            b = pad_box(p['box'], pad)
            if cur:
                u = cur[-1]['u']
                nu = union(u, b)
                mean = (sum(area(c['b']) for c in cur) + area(b)) / (len(cur) + 1)
                if area(nu) > grow * mean:
                    groups.append(cur); cur = []
                else:
                    cur.append({'p': p, 'b': b, 'u': nu}); continue
            cur.append({'p': p, 'b': b, 'u': b})
        if cur:
            groups.append(cur)
        for g in groups:
            hits = [c['p'] for c in g if c['p']['real']]
            st = max(s0, g[0]['p']['t'] - step / 2, 0.0)
            en = min(s1, g[-1]['p']['t'] + step / 2)
            if duration is not None:
                en = min(en, duration)
            src = hits or [c['p'] for c in g]
            face = [round(float(np.mean([h['box'][i] for h in src])), 4) for i in range(4)]
            res.append({'start': round(st, 3), 'end': round(en, 3), 'box': [round(v, 4) for v in g[-1]['u']], 'face': face,
                        'conf': round(max((h['conf'] for h in hits), default=min(c['p']['conf'] for c in g)), 3),
                        'hits': len(hits), 'track': k['id']})
    res.sort(key=lambda r: (r['start'], r['box'][0]))
    return res


GROW = 1.5


def rebuild(d, pad=None, min_frac=None, grow=None, conf=None):
    """Recompute "faces" of a faces.json from its per_frame detections with another --pad / --min / grow / --conf (no
    new detection; --min and --conf can only go UP from the values the detection ran with). Returns a new dict."""
    if d.get('per_frame') is None:
        raise ValueError('this faces.json has no per_frame (it was written with --no-per-frame)')
    p = dict(d.get('params') or {})
    pad = p.get('pad', 0.25) if pad is None else pad
    min_frac = p.get('min', 0.04) if min_frac is None else min_frac
    grow = p.get('grow', GROW) if grow is None else grow
    conf = p.get('conf', 0.0) if conf is None else conf
    W, H = d['size']
    cuts = p.get('cuts') if isinstance(p.get('cuts'), list) else [0.0]
    step = float(d.get('step', p.get('step', 0.1)))
    samples = sorted((float(t), [b for b in clean(v, min_frac, W, H) if b[4] >= conf]) for t, v in d['per_frame'].items())
    faces = ranges(track(samples, step, cuts, max_gap=0.3), step, cuts, d.get('duration'), pad, grow=grow)
    p.update(pad=pad, min=min_frac, grow=grow, conf=conf)
    return result(W, H, d.get('duration', 0), step, d.get('detector'), p, faces, d['per_frame'])


def live_at(faces, t):
    return [f for f in faces if f['start'] <= t <= f['end']]


def aspect(W, H):
    return '9x16' if H > W else ('16x9' if W > H else '1x1')


def result(W, H, duration, step, detector, params, faces, per_frame=None):
    d = {'size': [int(W), int(H)], 'aspect': aspect(W, H), 'duration': round(duration, 3), 'step': step,
         'detector': detector, 'params': params, 'faces': faces}
    if per_frame is not None:
        d['per_frame'] = per_frame
    return d


def validate(d):
    """Raises ValueError if d is not a faces.json (the schema above)."""
    if not isinstance(d, dict):
        raise ValueError('not a faces.json object')
    if not (isinstance(d.get('size'), list) and len(d['size']) == 2 and all(isinstance(v, int) and v > 0 for v in d['size'])):
        raise ValueError('size must be [W, H]')
    if not isinstance(d.get('faces'), list):
        raise ValueError('faces must be a list')
    for f in d['faces']:
        if not isinstance(f, dict):
            raise ValueError(f'a face entry is not an object: {f}')
        for k in ('start', 'end', 'box', 'conf'):
            if k not in f:
                raise ValueError(f'face without {k}: {f}')
        b = f['box']
        if not (isinstance(b, list) and all(isinstance(v, (int, float)) for v in b)
                and all(isinstance(f[k], (int, float)) for k in ('start', 'end'))):
            raise ValueError(f'box / start / end must be numbers: {f}')
        if len(b) != 4 or not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1):
            raise ValueError(f'box must be fractions x0 < x1, y0 < y1: {b}')
        if f['end'] < f['start']:
            raise ValueError(f'end before start: {f}')
    pf = d.get('per_frame')
    if pf is not None and not isinstance(pf, dict):
        raise ValueError('per_frame must be an object')
    return True


# ---------------------------------------------------------------- sheet ----------------------------------------------
def save_sheet(dest, thumbs, faces, per_frame_raw, cols=8):
    import cv2
    if not thumbs:
        return 0
    th_h, th_w = thumbs[0][1].shape[:2]
    rows = (len(thumbs) + cols - 1) // cols
    sh = np.full((rows * (th_h + 22) + 6, cols * (th_w + 6) + 6, 3), 16, np.uint8)
    for i, (t, im, raw) in enumerate(thumbs):
        im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR).copy()
        for b in raw:
            cv2.rectangle(im, (int(b[0] * th_w), int(b[1] * th_h)), (int(b[2] * th_w), int(b[3] * th_h)), (0, 220, 255), 1)
        for f in live_at(faces, t):
            b = f['box']
            cv2.rectangle(im, (int(b[0] * th_w), int(b[1] * th_h)), (int(b[2] * th_w), int(b[3] * th_h)), (40, 40, 255), 2)
        x, y = 6 + (i % cols) * (th_w + 6), 6 + (i // cols) * (th_h + 22)
        sh[y + 16:y + 16 + th_h, x:x + th_w] = im
        cv2.putText(sh, f'{t:.2f}s  {len(live_at(faces, t))}', (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 230, 255), 1)
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
    ok, buf = cv2.imencode('.jpg', sh, [cv2.IMWRITE_JPEG_QUALITY, 88])
    buf.tofile(dest)                                  # works with non-ASCII paths on Windows
    return len(thumbs)


def write_json(res, path):
    """One face (and one per_frame sample) per line: easy to read and to diff."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    head = {k: v for k, v in res.items() if k not in ('faces', 'per_frame')}
    J = lambda v: json.dumps(v, ensure_ascii=False)
    lines = ['{'] + [f' {J(k)}: {J(v)},' for k, v in head.items()]
    lines.append(' "faces": [' + ','.join('\n  ' + J(f) for f in res['faces']) + ('\n ]' if res['faces'] else ']')
                 + (',' if 'per_frame' in res else ''))
    if 'per_frame' in res:
        items = list(res['per_frame'].items())
        lines.append(' "per_frame": {' + ','.join(f'\n  {J(k)}: {J(v)}' for k, v in items) + ('\n }' if items else '}'))
    lines.append('}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ---------------------------------------------------------------- main -----------------------------------------------
def worker_count(det):
    """Parallel detect() calls: UltraFace keeps one onnxruntime session per thread; cv2.FaceDetectorYN and the Haar
    CascadeClassifier objects are not thread-safe, so they run on one worker."""
    if isinstance(det, UltraFace):
        return max(1, int(os.environ.get('HQ_VISION_WORKERS', '4')))
    return 1


def check_decoded(n, dur, step, video=''):
    """A half-decoded video must fail, never look like a video with no faces."""
    want = dur / step
    if n < MIN_DECODED * want:
        raise VisionError(f'decoded only {n} of about {int(want)} samples of {video} ({n * step:.1f} of {dur:.1f} s): '
                          'the file is cut short or damaged')


def detect_video(video, step=0.1, shots=None, min_frac=0.04, pad=0.35, conf=0.4, detector='auto', sheet=None,
                 sheet_every=0.5, per_frame=True, sheet_width=200, grow=None):
    import cv2
    t0 = time.time()
    W, H, dur, fps = probe(video)
    cuts = cut_times(shots, fps if fps > 1 else 30.0)
    det = make_detector(detector, conf, min_frac)
    samples, pf, thumbs = [], {}, []
    sheet_idx = {int(round(k * sheet_every / step)) for k in range(int(dur / sheet_every) + 1)} if sheet else set()
    workers = worker_count(det)

    def done(i, fr, d):
        t = round(i * step, 4)
        samples.append((t, d))
        if per_frame:
            pf[f'{t:.3f}'] = [[round(v, 4) for v in x[:4]] + [round(x[4], 3)] for x in d]
        if i in sheet_idx:
            h = int(round(sheet_width * fr.shape[0] / fr.shape[1]))
            thumbs.append((t, cv2.resize(fr, (sheet_width, h), interpolation=cv2.INTER_AREA), [x[:4] for x in d]))

    q = deque()                                     # in-order results, at most 2 x workers frames in memory
    with ThreadPoolExecutor(workers) as ex:
        for i, fr in frames(video, step, W, H):
            if i * step > dur + 1e-6:
                break
            if getattr(det, 'windows', 1) is None:
                det.plan(fr.shape[1], fr.shape[0])
            q.append((i, fr, ex.submit(det.detect, fr)))
            while len(q) > 2 * workers:
                a, b, f = q.popleft(); done(a, b, f.result())
        while q:
            a, b, f = q.popleft(); done(a, b, f.result())
    samples.sort(key=lambda s: s[0])
    check_decoded(len(samples), dur, step, video)
    tr = track(samples, step, cuts, max_gap=0.3)
    faces = ranges(tr, step, cuts, dur, pad, grow=grow or GROW)
    params = {'step': step, 'min': min_frac, 'pad': pad, 'conf': conf, 'grow': grow or GROW,
              'shots': os.path.basename(shots) if shots else None, 'cuts': cuts,
              'tiles': len(getattr(det, 'windows', None) or [1])}
    res = result(W, H, dur, step, det.name, params, faces, pf if per_frame else None)
    if sheet:
        save_sheet(sheet, thumbs, faces, pf)
    return res, dict(samples=len(samples), seconds=round(time.time() - t0, 1), tracks=len(tr))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video'); ap.add_argument('out')
    ap.add_argument('--step', type=float, default=0.1)
    ap.add_argument('--shots')
    ap.add_argument('--min', type=float, default=0.04, dest='min_frac')
    ap.add_argument('--pad', type=float, default=0.35)
    ap.add_argument('--conf', type=float, default=0.4)
    ap.add_argument('--grow', type=float, default=None, help=f'split a range when its box grows past this x its mean face box (default {GROW})')
    ap.add_argument('--detector', default='auto', choices=['auto', 'yunet', 'ultraface', 'haar'])
    ap.add_argument('--sheet'); ap.add_argument('--sheet-every', type=float, default=0.5)
    ap.add_argument('--no-per-frame', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.step <= 0:
            raise VisionError('--step must be > 0')
        if not os.path.exists(a.video):
            raise VisionError(f'no such video: {a.video}')
        if a.shots and not os.path.exists(a.shots):
            raise VisionError(f'no such shots file: {a.shots}')
        res, info = detect_video(a.video, a.step, a.shots, a.min_frac, a.pad, a.conf, a.detector, a.sheet, a.sheet_every,
                                 not a.no_per_frame, grow=a.grow)
        validate(res)
        write_json(res, a.out)
    except (VisionError, OSError, ValueError) as e:     # one JSON line, never a traceback or a half-written result
        out(ok=False, error=str(e), video=a.video)
        return 1
    out(ok=True, out=a.out, size=res['size'], detector=res['detector'], faces=len(res['faces']), sheet=a.sheet, **info)
    return 0


if __name__ == '__main__':
    sys.exit(main())
