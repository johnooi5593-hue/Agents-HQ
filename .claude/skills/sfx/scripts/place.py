"""Mix real CC0 sound effects into a finished video, each sound's loudest moment on the frame of its motion.

    python3 .claude/skills/sfx/scripts/place.py <video.mp4> <events.json> <out.mp4>

events.json:
    {"events": [
      {"frame": 120, "sound": "swish_soft", "what": "iris opens"},          # frame of the video (preferred), or
      {"t": 13.27, "sound": "whoosh_fast", "pan": 0.4, "what": "whip-in"},   # seconds, snapped to the nearest frame
      {"frame": 1441, "sound": "impact", "db": -2, "what": "punchline word"},
      {"t": 28.8, "sound": "rain", "bed": 15.7, "what": "storm bed"}        # a bed: no peak, plays from t for bed seconds
    ]}
"sound" is a category (see library/sounds.json; takes turns between that category's sounds) or one exact sound name, e.g. "impact_2".
"kind" may stand in for "sound": whip, zoom, iris, sweep, slide, title, hit, flash, slam, door_open, shine, flare, leak, pop, rain.
"db" nudges one sound up or down from its category's level; "pan" is -1 (left) to 1 (right).

The video stream is copied untouched; the audio is the video's own audio plus the effects, loudness-normalised to -14 LUFS / -1.5 dBTP.
Writes <out>.sfx.json (every placement with its check) and prints one JSON line.
"""
import json, os, subprocess, sys, tempfile
import numpy as np
from sfxlib import SR, HOP, CATEGORIES, LIB, NOWIN, ffmpeg, library, load_stereo, read_wav, envelope, peak_index, win_rms, write_wav, video_info, out

KIND = {'whip': 'whoosh_fast', 'whip_pan': 'whoosh_fast', 'zoom': 'whoosh_zoom', 'zoomblur': 'whoosh_zoom', 'zoom_through': 'whoosh_zoom',
        'iris': 'swish_soft', 'sweep': 'swish_soft', 'slide': 'swish_soft', 'title': 'swish_soft', 'card': 'swish_soft', 'name': 'swish_soft',
        'hit': 'impact', 'punch': 'impact', 'flash': 'impact', 'stamp': 'impact', 'slam': 'door_slam', 'door_open': 'door_creak',
        'shine': 'chime', 'sparkle': 'chime', 'flare': 'chime', 'reveal': 'chime', 'leak': 'chime_soft', 'glow': 'chime_soft',
        'pop': 'pop', 'icon': 'pop', 'chip': 'pop', 'sticker': 'pop', 'rain': 'rain', 'storm': 'rain'}


def main(video, events_path, dest):
    fps, dur, has_audio = video_info(video)
    spf = SR / fps
    with open(events_path, encoding='utf-8') as f:
        spec = json.load(f)
    evs = spec['events'] if isinstance(spec, dict) else spec
    lib = library()
    by_cat = {}
    for name, m in sorted(lib.items()):
        by_cat.setdefault(m['category'], []).append(name)

    prog = load_stereo(video) if has_audio else np.zeros((0, 2), np.float32)
    N = max(len(prog), int(round(dur * SR)))                     # the picture's length: an audio track may end early
    if len(prog) < N:
        prog = np.vstack([prog, np.zeros((N - len(prog), 2), np.float32)])
    mono = prog.mean(axis=1)
    fr = np.sqrt(np.mean(mono[:len(mono) // 2400 * 2400].reshape(-1, 2400) ** 2, axis=1) + 1e-12)   # 50 ms frames
    active = fr[20 * np.log10(fr) > -45]
    ref_db = 20 * np.log10(np.sqrt(np.mean(active ** 2))) if len(active) else -23.0          # the video's own level while something plays

    sfx = np.zeros((N, 2), np.float32); turn = {}; log = []; bad = 0
    for e in evs:
        cat_or_name = e.get('sound') or KIND.get(str(e.get('kind', '')).lower())
        if not cat_or_name:
            raise SystemExit(f'event without a sound or known kind: {e}')
        if cat_or_name in lib:
            name = cat_or_name
        elif cat_or_name in by_cat:
            opts = by_cat[cat_or_name]; j = turn.get(cat_or_name, 0); turn[cat_or_name] = j + 1; name = opts[j % len(opts)]
        else:
            raise SystemExit(f'unknown sound "{cat_or_name}": use a category ({", ".join(sorted(by_cat))}) or a sound name')
        m = lib[name]; cat = m['category']
        frame = int(e['frame']) if 'frame' in e else int(round(float(e['t']) * fps))
        if frame * spf >= N:
            log.append(dict(e, sound=name, frame=frame, placed=False, note='after the end of the video')); continue
        x = read_wav(os.path.join(LIB, m['file']))
        target = 10 ** ((ref_db + CATEGORIES.get(cat, ('', -14))[1] + float(e.get('db', 0))) / 20)
        if m.get('peak_s') is None or e.get('bed'):
            n = int(float(e.get('bed', 10)) * SR); x = np.resize(x, n).copy(); fade = min(int(.8 * SR), n // 3)
            x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
            sig = x * target / float(np.sqrt(np.mean(x ** 2) + 1e-12)); start = int(round(frame * spf)); peak_at = None
        else:
            p = int(round(m['peak_s'] * SR))
            sig = x * target / win_rms(x, p)
            peak_at = int(round(frame * spf + spf / 4))          # a quarter frame in: the whole loudest 5 ms sits inside the frame
            start = peak_at - p
        cut = 0
        if start < 0: cut = -start; sig = sig[cut:]; start = 0
        n = min(len(sig), N - start)
        if n <= 0:
            log.append(dict(e, sound=name, frame=frame, placed=False, note='after the end of the video')); continue
        pan = float(e.get('pan', 0)); l = np.cos((pan + 1) * np.pi / 4) * 1.41; r = np.sin((pan + 1) * np.pi / 4) * 1.41
        sfx[start:start + n, 0] += sig[:n] * l; sfx[start:start + n, 1] += sig[:n] * r
        ok = None
        if peak_at is not None:                                    # check: the loudest 5 ms of what was placed lies in the frame
            env = envelope(sig[:n]); loud = start + int(np.argmax(env)) * HOP + HOP // 2
            ok = int(loud // spf) == frame; bad += not ok
        log.append(dict(e, sound=name, category=cat, frame=frame, time=round(frame / fps, 3), placed=True, on_frame=ok, source=m.get('landing')))

    mix = prog + sfx
    pk = float(np.abs(mix).max()) or 1.0
    tmpd = tempfile.mkdtemp(prefix='sfx-')
    pre = os.path.join(tmpd, 'pre.wav'); fin = os.path.join(tmpd, 'final.wav')
    write_wav(pre, (mix / max(pk, 1.0) * .98).reshape(-1), channels=2)
    p = subprocess.run([ffmpeg(), '-hide_banner', '-i', pre, '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                       capture_output=True, text=True, creationflags=NOWIN)
    j = json.loads(p.stderr[p.stderr.rfind('{'):p.stderr.rfind('}') + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
          f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    subprocess.run([ffmpeg(), '-v', 'error', '-y', '-i', pre, '-af', af, '-ar', str(SR), '-c:a', 'pcm_s16le', fin], check=True, creationflags=NOWIN)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    subprocess.run([ffmpeg(), '-v', 'error', '-y', '-i', video, '-i', fin, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
                    '-b:a', '320k', '-shortest', '-movflags', '+faststart', dest], check=True, creationflags=NOWIN)
    for f in (pre, fin):
        os.remove(f)
    os.rmdir(tmpd)
    with open(dest + '.sfx.json', 'w', encoding='utf-8') as f:
        json.dump(dict(video=os.path.basename(video), fps=fps, events=log), f, ensure_ascii=False, indent=1)
    skipped = [x['frame'] for x in log if not x.get('placed')]
    out(ok=bad == 0, out=dest, log=dest + '.sfx.json', sounds=sum(1 for x in log if x.get('placed')), misaligned=bad, past_the_end=skipped, fps=round(fps, 3),
        note='every sound peaks on its frame' if bad == 0 else 'some sounds missed their frame: see the log')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
