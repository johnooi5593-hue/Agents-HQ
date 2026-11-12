"""The owner's cover as the very first frames of the video, so every platform picks it as the thumbnail by itself.

Buffer (and the Instagram and TikTok apps) cannot take a separate cover picture for a video: they use a frame of the
video, frame 0 unless the owner picks another one. So the copy that goes to Buffer starts with the cover shown for a
few frames (3 at 30 fps = 0.1 s, a blink; HQ_COVER_FLASH_FRAMES changes it) and then the edit plays as it was. The same
frame becomes the thumbnail on Instagram and on TikTok, so both show exactly the owner's cover. Facebook and YouTube
keep getting the original edit with the cover set through their APIs.

    python hq/cover_flash.py <edit.mp4> <cover.jpg> <out.mp4> [frames]

The cover is fitted to the video's size: a 9:16 cover fills the frame; a 3:4 one sits whole in the middle over a blurred
copy of itself (the way publish.cover_jpeg does for Instagram). Silence of the same length is put before the audio, so
sound and picture stay in step. The result follows Instagram's Reel rules (H.264 closed GOPs, AAC 128k 48 kHz, at most
20 Mbps, index first, no edit lists), so the same file suits Instagram, TikTok and Buffer. verify() reads frame 0 back
and checks that it really is the cover. Stdlib + ffmpeg only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STALL = 180          # seconds without a sign of life from ffmpeg before the encode is stopped as stuck
FRAMES = max(1, min(30, int(os.environ.get("HQ_COVER_FLASH_FRAMES", "3") or 3)))
SAMPLE = 53                                                   # verify() compares every 53rd pixel: enough, and fast
MATCH = 14.0                                                  # mean colour distance (0-255) under which a frame is "the cover"


def ffmpeg_path():
    return os.environ.get("FFMPEG") or shutil.which("ffmpeg")


def ffprobe_path():
    return os.environ.get("FFPROBE") or shutil.which("ffprobe")


def probe(video, run=subprocess.run):
    """{"fps": "30/1", "fps_value": 30.0, "width", "height", "duration", "audio": bool, "ok": bool, "error"}."""
    exe = ffprobe_path()
    if not exe:
        return {"ok": False, "error": "ffprobe is not installed"}
    cmd = [exe, "-v", "error", "-protocol_whitelist", "file", "-show_entries",
           "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,start_time,nb_frames:format=duration", "-of", "json", video]
    try:
        p = run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
        data = json.loads(p.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "error": f"ffprobe did not run: {e}"}
    if p.returncode != 0:
        return {"ok": False, "error": (p.stderr or "").strip()[-300:] or f"ffprobe exit {p.returncode}"}
    info = {"ok": True, "error": "", "audio": False, "fps": "30/1", "fps_value": 30.0, "width": 0, "height": 0, "duration": 0.0, "start": 0.0, "frames": 0}
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"], info["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
            try:
                info["start"], info["frames"] = float(s.get("start_time") or 0), int(s.get("nb_frames") or 0)
            except ValueError:
                pass
            rate = s.get("avg_frame_rate") if s.get("avg_frame_rate") not in (None, "", "0/0") else s.get("r_frame_rate")
            m = re.match(r"^(\d+)(?:/(\d+))?$", str(rate or ""))
            if m and int(m[2] or 1):
                info["fps"], info["fps_value"] = f"{m[1]}/{m[2] or 1}", int(m[1]) / int(m[2] or 1)
        elif s.get("codec_type") == "audio":
            info["audio"] = True
    try:
        info["duration"] = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        pass
    if not info["width"] or not info["height"] or info["fps_value"] <= 0:
        return {"ok": False, "error": "no video stream found"}
    return info


def seconds(frames, fps_value):
    return frames / fps_value


def fit_filter(src, w, h, out):
    """The cover fitted to w x h: whole, centred, over a blurred copy of itself where it doesn't fill the frame."""
    return (f"[{src}]split[cf_b][cf_f];[cf_b]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=40:2,eq=brightness=-0.1[cf_bg];"
            f"[cf_f]scale={w}:{h}:force_original_aspect_ratio=decrease[cf_fg];[cf_bg][cf_fg]overlay=(W-w)/2:(H-h)/2[{out}]")


def command(ff, video, cover, out, info, frames=FRAMES):
    """The ffmpeg command: the cover for `frames` frames, then the edit, Instagram-ready."""
    w, h, fps, fpsv = info["width"], info["height"], info["fps"], info["fps_value"]
    hold = seconds(frames, fpsv)
    graph = (fit_filter("1:v", w, h, "cf_fit") +
             f";[cf_fit]setsar=1,format=yuv420p,fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS[c];"
             f"[0:v]setsar=1,format=yuv420p,fps={fps},setpts=PTS-STARTPTS[v];[c][v]concat=n=2:v=1:a=0[outv]")
    maps = ["-map", "[outv]"]
    if info.get("audio"):
        graph += (f";anullsrc=r=48000:cl=stereo,atrim=duration={hold:.6f},asetpts=PTS-STARTPTS[sil];"
                  f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a0];[sil][a0]concat=n=2:v=0:a=1[outa]")
        maps += ["-map", "[outa]"]
    gop = max(1, int(round(fpsv * 2)))                      # closed 2-second GOPs, as Instagram asks
    # -reinit_filter 0: an edit joined from clips can switch pixel format or colour range part-way (yuvj420p <-> yuv420p);
    # rebuilding this filter graph at that frame makes ffmpeg stop dead, so the graph stays and scale converts each frame
    cmd = [ff, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-reinit_filter", "0", "-i", video,
           "-loop", "1", "-framerate", fps, "-t", f"{hold + 1:.3f}", "-i", cover,
           "-filter_complex", graph] + maps + [
           # no B-frames: with "no edit lists" (Instagram's rule) B-frames would push the picture 2 frames behind the sound
           # and the file's start to 0.067 s; without them frame 0 sits at exactly 0, under the first sample of audio
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "20M", "-bufsize", "40M", "-profile:v", "high",
           "-bf", "0", "-pix_fmt", "yuv420p", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0", "-fps_mode", "cfr",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           # no edit lists (Instagram's rule) and negative_cts_offsets: without the latter the muxer makes up for the AAC
           # priming by shifting every picture frame 21 ms, so frame 1 lasted 54 ms and the frame rate read 29.7
           "-movflags", "+faststart+negative_cts_offsets", "-use_editlist", "0", "-f", "mp4", out]
    return cmd


def make(video, cover, out, frames=FRAMES, progress=None, popen=subprocess.Popen, stall=STALL):
    """Writes `out`: the cover for `frames` frames, then `video`. progress(pct) gets 0-99 while it encodes.
    Returns {"ok": True, "frames", "hold", "duration", "fps", "width", "height"} or {"ok": False, "error"}."""
    ff = ffmpeg_path()
    if not ff:
        return {"ok": False, "error": "ffmpeg is not installed"}
    if not os.path.isfile(video):
        return {"ok": False, "error": "the video is missing"}
    if not os.path.isfile(cover):
        return {"ok": False, "error": "the cover is missing"}
    info = probe(video)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "the video could not be read"}
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    part = out + ".part"
    cmd = command(ff, video, cover, part, info, frames)
    cmd = cmd[:1] + ["-progress", "pipe:1", "-stats_period", "0.5"] + cmd[1:]
    total = max(0.1, info["duration"] + seconds(frames, info["fps_value"]))
    try:
        p = popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        seen, errs, stuck = [time.monotonic(), -1], [], []

        def drain():                                        # a full stderr pipe would block ffmpeg
            for line in p.stderr:
                errs.append(line)
                del errs[:-40]

        def watch():                                        # ffmpeg alive but not moving: stop it, don't wait for ever
            while p.poll() is None:
                if time.monotonic() - seen[0] > stall:
                    stuck.append(1)
                    p.kill()
                    return
                time.sleep(min(2.0, stall / 4))

        if p.stderr:
            threading.Thread(target=drain, daemon=True).start()
        threading.Thread(target=watch, daemon=True).start()
        for line in p.stdout:
            m = re.match(r"out_time_us=(\d+)", line.strip())
            if m and int(m[1]) != seen[1]:                  # ffmpeg keeps reporting while stuck: only a new time counts
                seen[:] = [time.monotonic(), int(m[1])]
                if progress:
                    progress(min(99.0, 100.0 * int(m[1]) / 1e6 / total))
        code = p.wait(timeout=1800)
        err = "".join(errs).strip()
        if stuck:
            err = f"ffmpeg stopped moving for {int(stall)} seconds while making the Buffer video, so it was stopped. {err}".strip()
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"ffmpeg did not run: {e}"}
    if code != 0 or not os.path.isfile(part) or os.path.getsize(part) == 0:
        try:
            os.remove(part)
        except OSError:
            pass
        return {"ok": False, "error": err[-400:] or f"ffmpeg exit {code}"}
    os.replace(part, out)
    done = probe(out)
    return {"ok": True, "frames": frames, "hold": round(seconds(frames, info["fps_value"]), 4), "fps": info["fps"],
            "width": info["width"], "height": info["height"], "duration": done.get("duration") or 0.0,
            "source_duration": info["duration"], "audio": info["audio"],
            "start": done.get("start", 0.0), "total_frames": done.get("frames", 0), "source_frames": info.get("frames", 0)}


def _raw_frame(ff, path, w, h, index=0, image=False, run=subprocess.run):
    """Frame `index` of a video (or an image fitted like the cover) as RGB bytes, w*h*3, or None."""
    if image:
        graph = fit_filter("0:v", w, h, "f") + ";[f]format=rgb24[o]"
        cmd = [ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-filter_complex", graph, "-map", "[o]", "-frames:v", "1", "-f", "rawvideo", "-"]
    else:
        cmd = [ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-vf", f"select=eq(n\\,{index}),scale={w}:{h},format=rgb24",
               "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-"]
    try:
        p = run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 and len(p.stdout) == w * h * 3 else None


def distance(a, b, step=SAMPLE):
    """Mean colour distance (0-255) between two RGB byte strings, sampled every `step` pixels."""
    if not a or not b or len(a) != len(b):
        return 255.0
    n, total = 0, 0
    for i in range(0, len(a) - 2, step * 3):
        total += abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1]) + abs(a[i + 2] - b[i + 2])
        n += 3
    return total / n if n else 255.0


def verify(out, cover, frames=FRAMES, run=subprocess.run):
    """Reads frame 0 (and the last cover frame) of `out` back and compares them with the cover.
    Returns {"ok": bool, "first": distance, "last": distance, "width", "height", "error"}."""
    ff = ffmpeg_path()
    info = probe(out)
    if not ff or not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "ffmpeg is not installed"}
    w, h = info["width"], info["height"]
    want = _raw_frame(ff, cover, w, h, image=True, run=run)
    first = _raw_frame(ff, out, w, h, 0, run=run)
    last = _raw_frame(ff, out, w, h, max(0, frames - 1), run=run)
    d0, d1 = distance(want, first), distance(want, last)
    ok = d0 <= MATCH and d1 <= MATCH
    return {"ok": ok, "first": round(d0, 2), "last": round(d1, 2), "width": w, "height": h,
            "error": "" if ok else f"frame 0 is not the cover (distance {d0:.1f})"}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    frames = int(argv[3]) if len(argv) > 3 else FRAMES
    r = make(argv[0], argv[1], argv[2], frames, progress=lambda pct: print(f"\r{pct:5.1f}%", end="", file=sys.stderr))
    print(file=sys.stderr)
    if r.get("ok"):
        r["verify"] = verify(argv[2], argv[1], frames)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") and r.get("verify", {}).get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
