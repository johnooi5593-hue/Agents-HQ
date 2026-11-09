"""The phone copy of a finished reel (t206). The owner watches reels on the phone, and the rule (owner, 2026-11) is:
every finished reel goes out as 1080p and at most 30 MB; when the edit is bigger, re-encode at about 3.5 Mbit/s,
never down to 720p.

    python hq/phone_copy.py <folder-or-edit.mp4>

writes <folder>/phone.mp4 only when edit.mp4 is over 30 MB or is not H.264 + AAC with faststart (moov first), and prints
one JSON line: {"status": "made" | "current" | "not-needed" | "broken" | "no-video" | "no-ffmpeg" | "failed", ...}.
Idempotent: a phone.mp4 newer than edit.mp4 is kept as it is. libx264 3500k (maxrate 4000k, bufsize 7000k), AAC 160k,
+faststart, the same resolution (only a source over 1080 on its short side is brought down to 1080). A long reel whose
3.5 Mbit/s copy would pass 30 MB gets the bitrate that fits. The encode is written to hq/.phone-work/ and moved into the
folder when done, so the folder never holds a half-written file (and can be approved while it runs).

The server runs it in the background (PhoneJobs): one job at a time, for out/ folders whose video is settled and readable.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import media_check  # noqa: E402

LIMIT = 30 * 1024 * 1024                                    # 30 MB: the phone limit (owner's rule)
VIDEO_K, MAXRATE_K, BUFSIZE_K, AUDIO_K = 3500, 4000, 7000, 160
MIN_VIDEO_K = 1500                                          # never starve a long reel below this (it stays 1080p)
SHORT_SIDE = 1080
EDIT, PHONE = "edit.mp4", "phone.mp4"
WORK = os.path.join(HERE, ".phone-work")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0
# below normal + no window: the editors' renders come first (HQ_PHONE_LOW=0 runs it at normal priority)
LOW_PRIORITY = NO_WINDOW | (0 if os.environ.get("HQ_PHONE_LOW", "1") == "0" else BELOW_NORMAL)


def ffmpeg_path():
    return os.environ.get("FFMPEG") or shutil.which("ffmpeg")


def paths(target):
    """(folder, edit.mp4) for a folder or an edit.mp4 path."""
    if os.path.isdir(target):
        return target, os.path.join(target, EDIT)
    return os.path.dirname(os.path.abspath(target)), target


def needs_copy(size, info):
    """(True/False, why) from the edit's size and its probe: over 30 MB, or not H.264 + AAC + faststart."""
    if size > LIMIT:
        return True, f"{size / 1048576:.1f} MB is over 30 MB"
    if (info.get("video") or "") and info["video"] != "h264":
        return True, f"video is {info['video']}, not H.264"
    if (info.get("audio") or "") not in ("", "aac"):
        return True, f"audio is {info['audio']}, not AAC"
    if info.get("faststart") is False:
        return True, "not faststart (moov after mdat)"
    return False, "edit.mp4 is already phone-ready"


def current(folder):
    """True when phone.mp4 exists and is newer than edit.mp4."""
    try:
        return os.path.getmtime(os.path.join(folder, PHONE)) >= os.path.getmtime(os.path.join(folder, EDIT))
    except OSError:
        return False


def video_kbps(duration):
    """3500k, or less for a long reel so video + audio fit in 30 MB (with 3 % for the container)."""
    if not duration or duration <= 0:
        return VIDEO_K
    fit = int(LIMIT * 8 * 0.97 / duration / 1000) - AUDIO_K
    return max(MIN_VIDEO_K, min(VIDEO_K, fit))


def command(ff, src, dst, info):
    v = video_kbps(info.get("duration"))
    w, h = info.get("width") or 0, info.get("height") or 0
    cmd = [ff, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-b:v", f"{v}k", "-maxrate", f"{round(v * MAXRATE_K / VIDEO_K)}k", "-bufsize", f"{round(v * BUFSIZE_K / VIDEO_K)}k"]
    if w and h and min(w, h) > SHORT_SIDE:                    # a 4K export comes down to 1080p, never below
        cmd += ["-vf", f"scale={'-2:' + str(SHORT_SIDE) if w >= h else str(SHORT_SIDE) + ':-2'}"]
    cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_K}k", "-movflags", "+faststart", "-f", "mp4", dst]
    return cmd


def make(target, run=subprocess.run, probe=media_check.probe, stop=None):
    """Makes <folder>/phone.mp4 when it is needed and not current. Returns the JSON-able result.
    stop: a threading.Event; when set the encode is ended (the folder is being approved)."""
    folder, edit = paths(target)
    if not os.path.isfile(edit):
        return {"status": "no-video", "folder": folder}
    if current(folder):
        return {"status": "current", "file": os.path.join(folder, PHONE), "size": os.path.getsize(os.path.join(folder, PHONE))}
    info = probe(edit)
    if info.get("ok") is False:
        return {"status": "broken", "file": edit, "error": info.get("error") or "unreadable"}
    size = os.path.getsize(edit)
    need, why = needs_copy(size, info)
    if not need:
        return {"status": "not-needed", "file": edit, "size": size, "why": why}
    ff = ffmpeg_path()
    if not ff:
        return {"status": "no-ffmpeg", "why": why}
    stamp = (os.path.getmtime(edit), size)
    os.makedirs(WORK, exist_ok=True)
    key = hashlib.sha1(f"{os.path.abspath(folder)}|{stamp[0]}|{stamp[1]}".encode()).hexdigest()[:20]
    tmp = os.path.join(WORK, key + ".mp4.part")          # the same version always reuses one scratch name (-y overwrites)
    cmd = command(ff, edit, tmp, info)
    started = time.time()
    try:
        if stop is None:
            run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=1800, check=True, creationflags=LOW_PRIORITY)
        else:
            _run_stoppable(cmd, stop)
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "failed", "error": str(e)[-300:], "why": why}
    if not os.path.isdir(folder) or not os.path.isfile(edit):
        return {"status": "failed", "error": "the folder moved (approved) while the copy was made", "why": why}
    try:
        changed = (os.path.getmtime(edit), os.path.getsize(edit)) != stamp
    except OSError:
        changed = True
    if changed:
        return {"status": "failed", "error": "edit.mp4 changed while the copy was made; it is made again next time", "why": why}
    out = os.path.join(folder, PHONE)
    try:
        os.replace(tmp, out)                                # one step: phone.mp4 is the old one or the whole new one
    except OSError as e:
        return {"status": "failed", "error": f"could not put phone.mp4 in place: {e}"[-300:], "why": why}
    new = os.path.getsize(out)
    return {"status": "made", "file": out, "size": new, "mb": round(new / 1048576, 1), "over": new > LIMIT,
            "video_kbps": video_kbps(info.get("duration")), "why": why, "seconds": round(time.time() - started, 1)}


def _run_stoppable(cmd, stop, popen=subprocess.Popen):
    """ffmpeg's errors go to a temporary file, never to an unread pipe (a full pipe would block the encode)."""
    with tempfile.TemporaryFile() as err:
        p = popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err, creationflags=LOW_PRIORITY)
        deadline = time.time() + 1800
        while p.poll() is None:
            if stop.is_set() or time.time() > deadline:
                p.kill()
                p.wait()
                raise subprocess.SubprocessError("stopped" if stop.is_set() else "timed out")
            time.sleep(0.5)
        if p.returncode != 0:
            err.seek(0)
            text = err.read()[-2000:].decode("utf-8", "replace")
            raise subprocess.CalledProcessError(p.returncode, cmd[0], stderr=text[-300:])


def state(folder):
    """What the package panel shows: {"file", "size", "mb", "ready": True} for phone.mp4 (or for edit.mp4 when it is
    phone-ready itself), {"making": True} while the worker is on it, None otherwise."""
    if current(folder):
        size = os.path.getsize(os.path.join(folder, PHONE))
        return {"file": PHONE, "size": size, "mb": round(size / 1048576, 1), "ready": True}
    edit = os.path.join(folder, EDIT)
    if not os.path.isfile(edit):
        return None
    info = media_check.cached(edit)                          # never ffprobe inside a status request (code review A7)
    if info is None:
        media_check.schedule(edit)
        return None
    if info.get("ok") is not True:
        return None
    size = os.path.getsize(edit)
    if not needs_copy(size, info)[0]:
        return {"file": EDIT, "size": size, "mb": round(size / 1048576, 1), "ready": True, "same": True}
    return None


STALE_PART = 24 * 3600                                      # a scratch encode older than a day is a leftover


def clean_stale(work=None, now=None, age=STALE_PART):
    """Removes this tool's own leftovers: *.mp4.part files directly in hq/.phone-work/ older than a day (an encode that
    was stopped by an approve, or a crash). Nothing else is ever touched. Returns the names removed."""
    work = WORK if work is None else work
    now = time.time() if now is None else now
    gone = []
    try:
        names = os.listdir(work)
    except OSError:
        return gone
    for n in names:
        p = os.path.join(work, n)
        try:
            if n.endswith(".mp4.part") and os.path.isfile(p) and not os.path.islink(p) and now - os.path.getmtime(p) > age:
                os.remove(p)
                gone.append(n)
        except OSError:
            pass
    return gone


class PhoneJobs:
    """The server's background maker: one job at a time on its own thread, never blocking a request."""

    def __init__(self, maker=make, log=lambda msg: sys.stderr.write(msg + "\n"), out_root=None):
        self.maker, self.log = maker, log
        self.out_root = os.path.realpath(out_root) if out_root else None   # only folders really inside out/ (no junctions out)
        self.releasing = set()                                  # folders being approved: refused until the move is done
        self.cleaned = False
        self.queue, self.busy, self.done = [], None, {}     # waiting folders, the one being made, folder -> (stamp, result)
        self.cond, self.stop = threading.Condition(), threading.Event()
        self.thread = None

    @staticmethod
    def _stamp(folder):
        try:
            st = os.stat(os.path.join(folder, EDIT))
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def want(self, folder):
        """Queue folder unless it is queued, being made, or was already tried for this version of its edit.mp4."""
        folder = os.path.realpath(folder)
        if self.out_root and not folder.startswith(self.out_root + os.sep):
            return False                                        # its real path is outside out/ (a junction): never
        with self.cond:
            if folder in self.releasing:
                return False
        stamp = self._stamp(folder)
        if stamp is None or current(folder):
            return False
        with self.cond:
            if folder in self.releasing or folder in self.queue or folder == self.busy or (self.done.get(folder) or (None,))[0] == stamp:
                return False
            self.queue.append(folder)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, daemon=True, name="phone-copy")
                self.thread.start()
            self.cond.notify_all()
        return True

    def making(self, folder):
        folder = os.path.realpath(folder)
        with self.cond:
            return folder == self.busy or folder in self.queue

    def release(self, folder, wait=10):
        """Before a folder moves (approve): take it out of line and end its running encode, waiting up to `wait` s.
        True when nothing is being made from it any more; False when the encode is still stopping (the caller answers
        409 and calls moved()). Either way want() refuses the folder until moved(folder)."""
        folder = os.path.realpath(folder)
        with self.cond:
            self.releasing.add(folder)                          # want() refuses it until moved(folder)
            if folder in self.queue:
                self.queue.remove(folder)
            if self.busy != folder:
                return True
            self.stop.set()
            end = time.time() + wait
            while self.busy == folder and time.time() < end:
                self.cond.wait(0.2)
            return self.busy != folder

    def moved(self, folder):
        """The approve's move is over (done or failed): the folder may be queued again (from out/ only, as always)."""
        folder = os.path.realpath(folder)
        with self.cond:
            self.releasing.discard(folder)
            self.done.pop(folder, None)                     # an approve that answered 409 leaves the reel to be made again

    def _loop(self):
        if not self.cleaned:
            self.cleaned = True
            try:
                gone = clean_stale()
                if gone:
                    self.log(f"phone copy: removed {len(gone)} stale scratch file(s) from {WORK}")
            except Exception:
                pass
        while True:
            with self.cond:
                while not self.queue:
                    if not self.cond.wait(300) and not self.queue:
                        self.thread = None                  # idle for 5 min, decided under the lock: want() starts a new one
                        return
                folder = self.busy = self.queue.pop(0)
                self.stop.clear()
            stamp, res = None, {"status": "failed", "error": "not started"}
            try:
                stamp = self._stamp(folder)
                res = self.maker(folder, stop=self.stop)
                if res.get("status") in ("made", "failed"):
                    self.log(f"phone copy of {folder}: {json.dumps(res, ensure_ascii=False)}")
            except Exception as e:                           # never let the phone copy (or its log line) break the office
                res = {"status": "failed", "error": str(e)[-300:]}
            finally:
                with self.cond:
                    if res.get("error") != "stopped":        # stopped by an approve: not a real try, it is made again later
                        self.done[folder] = (stamp, res)
                    self.busy = None
                    self.cond.notify_all()


def main(argv):
    if len(argv) != 1:
        print(json.dumps({"status": "usage", "usage": "python hq/phone_copy.py <folder-or-edit.mp4>"}))
        return 2
    res = make(argv[0])
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["status"] in ("made", "current", "not-needed") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
