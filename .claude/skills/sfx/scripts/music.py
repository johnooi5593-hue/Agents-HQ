"""Blend the owner's music under a finished edit: ducked under the voice, up a little in the gaps, faded in and out,
matched to any music the video already has, loudness-normalised. Shared by every edit skill; run it after the render and
before the sound effects (place.py).

usage: python music.py <video> <music file or folder> <out.mp4> [--duck 12] [--bed 5] [--start 0] [--offset 0]
                       [--fade-in 1.5] [--fade-out 2.5] [--lufs -14] [--room]

<music>     the track the owner gave (mp3 / wav / m4a / flac), or a folder of them (the first one, by name)
--duck      dB the music sits under the voice while someone speaks (brand rule, owner 2026-11-02: 12, the Sandy blend;
            21 was too quiet to hear on a phone)
--bed       dB under the voice in the gaps and before / after the talk (louder, so the music is heard)
--start     where in the video the music comes in (s); --offset: where in the track it starts (s)
--lufs      the loudness of the finished mix (-14, the platforms' level), true peak -1.5 dBTP
--room      the video's gaps hold only room sound, not music: never lower the bed to match them

Voice: the Silero speech detector inside faster-whisper (local, CPU). The voice level is measured on the video's own
audio while speech is detected. If the video already has music under the talk (its gaps are loud), the new track's bed is
lowered to that music's level so the two blend instead of fighting; the report says so. A track shorter than the video
loops with a 2 s crossfade. The video stream is copied untouched. Prints one JSON line.
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")


def decode(path, ch=2, sr=SR):
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).copy()


def db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def frame_rms(x, n):
    m = x.mean(1) if x.ndim == 2 else x
    k = len(m) // n
    return np.sqrt((m[:k * n].reshape(k, n) ** 2).mean(1) + 1e-12)


def speech_mask(video, frames, hop):
    """Per 10 ms frame: 1 while someone speaks (Silero VAD at 16 kHz), 0 otherwise."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    pcm = decode(video, 1, 16000)[:, 0]
    ts = get_speech_timestamps(pcm, VadOptions(min_silence_duration_ms=300, speech_pad_ms=120))
    m = np.zeros(frames, np.float32)
    for t in ts:
        m[int(t["start"] / 16000 / hop):int(t["end"] / 16000 / hop) + 1] = 1
    return m, len(ts)


def loop_to(x, n, xf):
    if len(x) >= n:
        return x[:n]
    out = x.copy()
    ramp = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
    while len(out) < n:
        out = np.concatenate([out[:-xf], out[-xf:] * (1 - ramp) + x[:xf] * ramp, x[xf:]])
    return out[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("music"); ap.add_argument("out")
    ap.add_argument("--duck", type=float, default=12.0); ap.add_argument("--bed", type=float, default=5.0)
    ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--fade-in", type=float, default=1.5); ap.add_argument("--fade-out", type=float, default=2.5)
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--room", action="store_true")
    a = ap.parse_args()
    track = a.music
    if os.path.isdir(track):
        files = sorted(f for f in os.listdir(track) if f.lower().endswith(AUDIO_EXT))
        if not files:
            sys.exit(f"no music file in {track}")
        track = os.path.join(track, files[0])
    vid = decode(a.video)
    if not len(vid):
        sys.exit(f"{a.video} has no audio")
    n = len(vid); hop = 0.01; hs = int(SR * hop); frames = n // hs + 1
    mask, n_speech = speech_mask(a.video, frames, hop)
    rms = frame_rms(np.vstack([vid, np.zeros((hs, 2), np.float32)]), hs)[:frames]
    sp = rms[mask[:len(rms)] > 0]
    voice_db = db(np.percentile(sp, 70)) if len(sp) > 20 else db(np.percentile(rms, 90))
    gaps = rms[mask[:len(rms)] == 0]
    gap_db = db(np.median(gaps)) if len(gaps) > 50 else -90.0
    bed = a.bed
    existing = gap_db > voice_db - 24 and not a.room                      # the video's own gaps are loud: it already has music / room
    if existing:
        bed = max(bed, voice_db - gap_db + 1)               # sit at that music's level, not on top of it
    mus = decode(track)[int(a.offset * SR):]
    start = int(a.start * SR)
    body = loop_to(mus, n - start, 2 * SR)
    mus_db = db(np.percentile(frame_rms(body, hs), 70))
    # gain per 10 ms frame: -duck under speech, -bed in the gaps; speech pulls it down fast (0.12 s), gaps let it up slowly (0.6 s)
    mm = np.maximum.reduce([np.roll(mask, k) for k in range(-12, 1)])        # duck 0.12 s before the voice starts
    target = np.where(mm > 0, voice_db - a.duck, voice_db - bed) - mus_db
    g = np.empty_like(target); g[0] = target[0]
    down, up = 1 - np.exp(-hop / 0.12), 1 - np.exp(-hop / 0.6)
    for i in range(1, len(target)):
        g[i] = g[i - 1] + (target[i] - g[i - 1]) * (down if target[i] < g[i - 1] else up)
    gain = 10 ** (g / 20)
    env = np.interp(np.arange(n - start) + start, np.arange(frames) * hs, gain).astype(np.float32)
    t = np.arange(n - start, dtype=np.float32) / SR
    env *= np.clip(t / max(a.fade_in, 1e-3), 0, 1) * np.clip((len(t) / SR - t) / max(a.fade_out, 1e-3), 0, 1)
    mix = vid.copy()
    mix[start:] += body * env[:, None]
    fd, wav = tempfile.mkstemp(suffix=".f32"); os.close(fd)
    mix.astype(np.float32).tofile(wav)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", a.video, "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", wav,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", f"loudnorm=I={a.lufs}:TP=-1.5:LRA=11", "-ar", str(SR),
                        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", a.out], capture_output=True, text=True)
    os.unlink(wav)
    if p.returncode:
        sys.exit(p.stderr[-1500:])
    print(__import__("json").dumps({
        "tool": "music", "out": a.out, "music": track, "speech_parts": n_speech, "voice_db": round(voice_db, 1),
        "music_under_voice_db": -round(a.duck, 1), "music_in_gaps_db": -round(bed, 1),
        "video_had_music": bool(existing), "video_gap_db": round(gap_db, 1),
        "note": ("the video already has music or room sound in its gaps; the new track sits at that level to blend" if existing else ""),
        "looped": len(mus) < n - start, "lufs": a.lufs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
