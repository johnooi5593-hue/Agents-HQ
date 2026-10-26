"""Propose sound-effect events for a finished video: hard cuts, fast moves (whips, zooms, slides) at their fastest frame, and flashes.

    python3 .claude/skills/sfx/scripts/detect.py <video.mp4> <events_draft.json>

It only proposes. Read the draft, look at the frames it names (reel skill frames.py), keep the real moves and hits, fix the sound for
each, delete the rest, and add what it cannot see (a word landing, an icon popping in) from the edit's own plan. Prints one JSON line.
"""
import json, subprocess, sys
import numpy as np
from sfxlib import NOWIN, ffmpeg, video_info, out

W, H = 96, 170


def main(video, dest):
    fps, dur, _ = video_info(video)
    raw = subprocess.run([ffmpeg(), '-v', 'error', '-i', video, '-an', '-vf', f'scale={W}:{H},format=gray', '-f', 'rawvideo', '-'],
                         capture_output=True, check=True, creationflags=NOWIN).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    n = len(f)
    d = np.zeros(n); d[1:] = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))          # how much the picture changes, frame to frame
    bright = f.mean(axis=(1, 2))
    base = np.median(d) + 1e-6
    ev = []
    taken = np.zeros(n, bool)
    # flashes: the picture jumps much brighter for a few frames
    for i in range(1, n):
        if bright[i] - bright[i - 1] > 35 and not taken[max(0, i - 3):i + 3].any():
            ev.append(dict(frame=i, t=round(i / fps, 3), kind='flash', sound='impact', score=round(float(bright[i] - bright[i - 1]), 1),
                           what='flash: the picture jumps brighter')); taken[i] = True
    # hard cuts: one frame changes a lot, its neighbours little
    for i in range(1, n - 1):
        if d[i] > max(18, 5 * base) and d[i - 1] < .45 * d[i] and d[i + 1] < .45 * d[i] and not taken[max(0, i - 3):i + 3].any():
            ev.append(dict(frame=i, t=round(i / fps, 3), kind='cut', sound='swish_soft', score=round(float(d[i]), 1),
                           what='hard cut: give it a sound only if it is a designed transition, most plain cuts stay silent')); taken[i] = True
    # fast moves: several frames in a row change a lot; the sound peaks on the fastest frame
    s = np.convolve(d, np.ones(3) / 3, mode='same')
    i = 1
    while i < n - 1:
        if s[i] > max(8, 3 * base):
            j = i
            while j < n - 1 and s[j] > max(8, 3 * base): j += 1
            if j - i >= 3:
                k = i + int(np.argmax(d[i:j]))
                if not taken[max(0, k - 4):k + 4].any():
                    ev.append(dict(frame=int(k), t=round(k / fps, 3), kind='move', sound='whoosh_fast', score=round(float(d[k]), 1),
                                   what=f'fast move over frames {i}-{j - 1}: whoosh_fast for a whip or slide, whoosh_zoom for a zoom')); taken[k] = True
            i = j
        else:
            i += 1
    ev.sort(key=lambda e: e['frame'])
    with open(dest, 'w', encoding='utf-8') as fh:
        json.dump(dict(video=video, fps=fps, note='A draft. Keep the real moves and hits, fix each sound, delete the rest, add word hits and pops from the plan.',
                       events=ev), fh, ensure_ascii=False, indent=1)
    out(ok=True, draft=dest, fps=round(fps, 3), frames=n, proposed=len(ev),
        kinds={k: sum(1 for e in ev if e['kind'] == k) for k in ('flash', 'cut', 'move')})


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
