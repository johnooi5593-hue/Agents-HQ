"""Is a finished video really a video? A clip-editor run that dies mid-render leaves an edit.mp4 without its moov atom
(t205, 2026-11-08 19:34: the board showed "doing 85%" for an hour next to a file nothing could play). probe() asks
ffprobe once per version of a file (path, mtime, size) and remembers the answer; readable() is the yes/no the video
package uses. Without ffprobe an .mp4/.mov/.m4v is checked by its top-level boxes (no moov, or a box past the end of
the file, is broken); any other file counts as readable, so a missing tool never hides a video.
"""
import json
import os
import shutil
import subprocess
import threading

MP4_LIKE = (".mp4", ".mov", ".m4v")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_cache, _lock = {}, threading.Lock()
CACHE_MAX = 512


def ffprobe_path():
    return os.environ.get("FFPROBE") or shutil.which("ffprobe")


def boxes(path, limit=64):
    """The top-level MP4 boxes [(type, offset, size)]; raises ValueError when a box runs past the end of the file."""
    out, end = [], os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while pos < end and len(out) < limit:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                raise ValueError("cut off inside a box header")
            size, kind = int.from_bytes(head[:4], "big"), head[4:8].decode("latin-1")
            if size == 1:                                   # 64-bit size follows
                ext = f.read(8)
                if len(ext) < 8:
                    raise ValueError("cut off inside a box header")
                size = int.from_bytes(ext, "big")
            elif size == 0:                                 # runs to the end of the file
                size = end - pos
            if size < 8 or pos + size > end:
                raise ValueError(f"box {kind!r} runs past the end of the file")
            out.append((kind, pos, size))
            pos += size
    return out


def faststart(path):
    """True when moov comes before mdat (a phone starts playing at once), False when after, None when not MP4-like."""
    if not path.lower().endswith(MP4_LIKE):
        return None
    try:
        kinds = [k for k, _, _ in boxes(path)]
    except (OSError, ValueError):
        return None
    if "moov" not in kinds or "mdat" not in kinds:
        return None
    return kinds.index("moov") < kinds.index("mdat")


def _box_check(path):
    if not path.lower().endswith(MP4_LIKE):
        return {"ok": None, "error": "", "via": "none"}
    try:
        kinds = [k for k, _, _ in boxes(path)]
    except (OSError, ValueError) as e:
        return {"ok": False, "error": str(e), "via": "boxes"}
    if "moov" not in kinds:
        return {"ok": False, "error": "moov atom not found", "via": "boxes"}
    return {"ok": True, "error": "", "via": "boxes"}


def _ffprobe(path, exe, run=subprocess.run):
    cmd = [exe, "-v", "error", "-protocol_whitelist", "file", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", path]
    try:
        p = run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": None, "error": f"ffprobe did not run: {e}", "via": "ffprobe"}
    if p.returncode != 0:
        return {"ok": False, "error": (p.stderr or "").strip()[-300:] or f"ffprobe exit {p.returncode}", "via": "ffprobe"}
    try:
        data = json.loads(p.stdout or "{}")
    except ValueError:
        return {"ok": False, "error": "ffprobe gave no readable answer", "via": "ffprobe"}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v:
        return {"ok": False, "error": "no video stream", "via": "ffprobe"}
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"ok": True, "error": "", "via": "ffprobe", "video": v.get("codec_name") or "", "audio": (a or {}).get("codec_name") or "",
            "width": v.get("width"), "height": v.get("height"), "duration": duration}


def probe(path, run=subprocess.run):
    """{"ok": True | False | None (unknown), "error", "via", and with ffprobe: video, audio, width, height, duration;
    "faststart" for MP4-like files}. Cached per (path, mtime, size)."""
    try:
        st = os.stat(path)
    except OSError as e:
        return {"ok": False, "error": str(e), "via": "stat"}
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return dict(hit)
    exe = ffprobe_path()
    res = _ffprobe(path, exe, run) if exe else {"ok": None}
    if res.get("ok") is None:                             # no ffprobe, or it could not run: the box check decides
        res = _box_check(path)
    elif res.get("ok") and path.lower().endswith(MP4_LIKE):
        box = _box_check(path)                            # ffprobe said OK: the boxes must agree (code review A9)
        if box.get("ok") is False:
            res = {**res, "ok": False, "error": box["error"], "via": "ffprobe+boxes"}
    if res.get("ok"):
        res["faststart"] = faststart(path)
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = dict(res)
    return res


def _key(path):
    st = os.stat(path)
    return (os.path.abspath(path), st.st_mtime_ns, st.st_size)


def cached(path):
    """The probe already made for this version of the file, None when there is none yet. Never runs ffprobe."""
    try:
        key = _key(path)
    except OSError as e:
        return {"ok": False, "error": str(e), "via": "stat"}
    with _lock:
        hit = _cache.get(key)
    return dict(hit) if hit is not None else None


_queue, _queue_cond, _worker = [], threading.Condition(), [None]


def schedule(path):
    """Probe path on the background thread (one at a time); returns at once."""
    path = os.path.abspath(path)
    with _queue_cond:
        if path not in _queue:
            _queue.append(path)
        if _worker[0] is None:
            _worker[0] = threading.Thread(target=_probe_loop, daemon=True, name="media-check")
            _worker[0].start()
        _queue_cond.notify_all()


def _probe_loop():
    while True:
        with _queue_cond:
            while not _queue:
                if not _queue_cond.wait(60) and not _queue:
                    _worker[0] = None                     # decided under the lock: schedule() starts a new thread
                    return
            path = _queue.pop(0)
        try:
            probe(path)
        except Exception:                                 # the board never breaks on a probe
            pass


def readable(path):
    """False only when the file is known to be broken; True or None (unknown) count as a video."""
    return probe(path).get("ok") is not False


def readable_nowait(path):
    """readable() for a status request: the cached answer, else True (not probed yet counts as readable) while the
    background thread probes it, so ffprobe never runs inside a request or under the package lock (code review A7)."""
    hit = cached(path)
    if hit is None:
        schedule(path)
        return True
    return hit.get("ok") is not False
