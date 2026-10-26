"""Shared helpers for the sfx skill: audio in and out through ffmpeg, the loudest moment of a sound, the library index."""
import json, os, shutil, subprocess, sys, wave
import numpy as np

SR = 48000
HOP = 240                                    # 5 ms at 48 kHz: "loudest moment" = the loudest 5 ms
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(SKILL, 'library')
INDEX = os.path.join(LIB, 'sounds.json')
NOWIN = 0x08000000 if os.name == 'nt' else 0

# What each category is for, and how loud it sits against the video's own voice and music (dB, RMS over +-150 ms at its loudest
# moment vs the programme's active RMS). Tuned by ear on the 10/18 sermon reels: moves well under the voice, hits a little under it.
CATEGORIES = {
    'whoosh_fast': ('whip pans, fast slide-ins, whip transitions', -14.5),
    'whoosh_zoom': ('zoom-ins, zoom-blur, punch-throughs, things flying at the camera', -13.5),
    'swish_soft':  ('soft moves: iris, light sweep, name label, cards and steps sliding in, end titles', -14.5),
    'impact':      ('hits: a punchline word landing, flash cuts, big stamps', -5.0),
    'door_slam':   ('a door or doors slamming shut', -1.5),
    'door_creak':  ('a door swinging open', -10.0),
    'chime':       ('gold shine, sparkle, a light flare, a reveal', -7.0),
    'chime_soft':  ('light leaks, gentle glows', -17.0),
    'pop':         ('icons, chips, stickers and bubbles popping in', -13.0),
    'shutter':     ('a camera click on a freeze frame or a photo snap', -10.0),
    'rain':        ('a rain or storm bed under a scene (no peak; give "bed" seconds)', -21.0),
}


def out(**kw):
    """The scripts print one JSON line."""
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(kw, ensure_ascii=False))


def ffmpeg():
    return os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'ffmpeg'


def load_mono(path, start=None, dur=None):
    cmd = [ffmpeg(), '-v', 'error']
    if start is not None: cmd += ['-ss', f'{start:.3f}']
    if dur is not None: cmd += ['-t', f'{dur:.3f}']
    cmd += ['-i', path, '-vn', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True, creationflags=NOWIN).stdout
    return np.frombuffer(raw, np.float32).copy()


def load_stereo(path):
    raw = subprocess.run([ffmpeg(), '-v', 'error', '-i', path, '-vn', '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True, creationflags=NOWIN).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def envelope(x):
    n = len(x) // HOP
    return np.sqrt(np.mean(x[:n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-12)


def peak_index(x):
    """The loudest sample inside the loudest 5 ms."""
    env = envelope(x); j = int(np.argmax(env))
    return j * HOP + int(np.argmax(np.abs(x[j * HOP:(j + 1) * HOP])))


def win_rms(x, p, half=.15):
    a, b = max(0, p - int(half * SR)), min(len(x), p + int(half * SR))
    return float(np.sqrt(np.mean(x[a:b] ** 2) + 1e-12))


def write_wav(path, x, channels=1):
    w = wave.open(path, 'wb'); w.setnchannels(channels); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()


def read_wav(path):
    w = wave.open(path); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return x.reshape(-1, w.getnchannels())[:, 0] if w.getnchannels() > 1 else x


def library():
    with open(INDEX, encoding='utf-8') as f:
        return json.load(f)


def save_library(idx):
    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    rows = [f"| {m['file']} | {m['category']} | {m['title']} | {m['creator']} | {m['license']} | {m['landing']} |" for m in idx.values()]
    with open(os.path.join(LIB, 'CREDITS.md'), 'w', encoding='utf-8') as f:
        f.write("# Sound library\n\nEvery sound was found with the Openverse API (license=cc0). CC0 is public domain: no credit is required, "
                "but the sources are listed here. Each file is trimmed around its loudest moment; `sounds.json` records where that moment "
                "sits (`peak_s`).\n\n| File | Category | Original title | Creator | License | Source |\n|---|---|---|---|---|---|\n"
                + "\n".join(rows) + "\n")


def video_info(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate:format=duration',
                        '-of', 'json', path], capture_output=True, text=True, creationflags=NOWIN)
    j = json.loads(p.stdout or '{}'); fr = (j.get('streams') or [{}])[0].get('r_frame_rate', '30/1')
    a, b = fr.split('/'); fps = float(a) / float(b or 1)
    has_audio = bool(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', path],
                                    capture_output=True, text=True, creationflags=NOWIN).stdout.strip())
    return fps, float(j.get('format', {}).get('duration', 0)), has_audio
