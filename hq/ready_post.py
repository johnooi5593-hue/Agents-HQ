"""Post a video (owner, 2026-11-13): a ready-made video the owner uploads skips the editors.

The owner uploads the finished video, adds their own thumbnail (a picture, or a frame of the video) and types the
title and caption; then the usual posting screen takes over (where and when, the Post button). Nothing here posts.

The video lands in approved/<name>/ as final.<ext>: uploading your own finished video is the approval. The folder holds
ready.json (so only folders made here can be changed here), channel.txt for another channel, cover.jpg / cover.png and
post.md with the one caption. A board task (Social, "out:<name>" in its note) is the video's card.
Only the owner's own requests reach this (the server's login and same-site checks); agents never call it.
"""
import json
import os
import re
import subprocess
import time

VIDEO_EXT = (".mp4", ".mov", ".m4v")
IMAGE_EXT = (".jpg", ".jpeg", ".png")
MAX_COVER = 25 * 1024 * 1024
TITLE_MAX, CAPTION_MAX = 100, 2200                             # Instagram's caption limit; a title every platform takes
SAFE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 ._()\-]{0,119}[A-Za-z0-9_()\-])?$")   # never ends in a dot or a space (Windows drops them)
VIDEO_NAME = re.compile(r"final\.(?:mp4|mov|m4v)")              # the only video this screen ever reads back
MARK = "ready.json"


class ReadyError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def slug(filename):
    """A folder name from the file's name: lower-case words joined by dashes, never empty, never a dot name."""
    stem = os.path.splitext(os.path.basename(str(filename or "")))[0]
    s = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:60].strip("-")
    return s or "video"


class ReadyPosts:
    def __init__(self, root, task_action, channel_ok=lambda key: True, max_upload=2048 * 1024 * 1024, ffmpeg="ffmpeg", load_tasks=None):
        self.root, self.task_action, self.channel_ok = os.path.realpath(root), task_action, channel_ok
        self.load_tasks = load_tasks
        self.max_upload, self.ffmpeg = max_upload, ffmpeg

    # ---- folders
    def _folder(self, name):
        """approved/<name> for a folder made here (it holds ready.json), or a ReadyError."""
        if not SAFE.match(str(name or "")):
            raise ReadyError("no such video", 404)
        base = os.path.join(self.root, "approved")
        d = os.path.realpath(os.path.join(base, name))
        if os.path.dirname(d) != os.path.realpath(base) or not os.path.isfile(os.path.join(d, MARK)):
            raise ReadyError("this is not a video you uploaded on the Post a video screen", 404)
        return d

    def _free_name(self, wanted):
        for n in range(1, 200):
            name = wanted if n == 1 else f"{wanted}-{n}"
            if not any(os.path.exists(os.path.join(self.root, area, name)) for area in ("approved", "out", "done")):
                return name
        raise ReadyError("too many videos with this name: rename the file and try again", 409)

    def _mark(self, d):
        with open(os.path.join(d, MARK), encoding="utf-8") as f:
            mark = json.load(f)
        return mark if isinstance(mark, dict) else {}

    @staticmethod
    def _write_mark(d, mark):
        tmp = os.path.join(d, MARK + ".part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mark, f, indent=1)
        os.replace(tmp, os.path.join(d, MARK))

    def _video(self, d):
        """The uploaded video's path: always final.<ext> in this very folder, whatever ready.json says."""
        v = str(self._mark(d).get("video") or "")
        p = os.path.realpath(os.path.join(d, v)) if VIDEO_NAME.fullmatch(v) else ""
        if not p or os.path.dirname(p) != os.path.realpath(d) or not os.path.isfile(p):
            raise ReadyError("the video is missing from this folder", 404)
        return p

    def state(self, name):
        d = self._folder(name)
        mark = self._mark(d)
        cover = next((f for f in ("cover.jpg", "cover.png") if os.path.isfile(os.path.join(d, f))), None)
        title, caption = self._caption(d)
        stamp = int(os.path.getmtime(os.path.join(d, cover))) if cover else 0
        return {"name": name, "folder": "approved/" + name, "video": mark.get("video"), "source": mark.get("source"),
                "task": mark.get("task"), "channel": mark.get("channel") or "", "cover": cover, "coverAt": stamp,
                "title": title, "caption": caption}

    # ---- step 1: the video
    def save_video(self, filename, channel, length, stream):
        ext = os.path.splitext(str(filename or ""))[1].lower()
        if not SAFE.match(str(filename or "")) or ext not in VIDEO_EXT:
            raise ReadyError(f"a ready video is a {' '.join(VIDEO_EXT)} file with a plain name")
        if length <= 0:
            raise ReadyError("the file is empty")
        if length > self.max_upload:
            raise ReadyError(f"file larger than {self.max_upload // (1024 * 1024)} MB", 413)
        if channel and not self.channel_ok(channel):
            raise ReadyError("no such channel", 404)
        name = self._free_name(slug(filename))
        d = os.path.join(self.root, "approved", name)
        try:
            os.makedirs(d)
        except FileExistsError:                                # two uploads of the same name at the same moment
            raise ReadyError("another upload just took this name. Try again.", 409) from None
        video, tmp = "final" + ext, os.path.join(d, ".upload.part")
        left = length
        try:
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = stream.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
        except OSError:                                        # the connection was reset, or the disk is full
            left = left or 1
        if left:                                               # nothing half-made stays as a video
            try:
                os.replace(tmp, os.path.join(d, "upload-did-not-finish.part"))
            except OSError:
                pass
            raise ReadyError("the upload stopped before the whole file arrived. Try again.")
        os.replace(tmp, os.path.join(d, video))
        if channel:
            with open(os.path.join(d, "channel.txt"), "w", encoding="utf-8") as f:
                f.write(channel)
        pretty = re.sub(r"[-_]+", " ", name).strip().title()
        body = {"action": "add", "title": pretty, "team": "Social", "status": "review", "note": f"out:{name}",
                "subtitle": "Your own video: add the thumbnail and caption, then post"}
        if channel:
            body["channel"] = channel
        mark = {"video": video, "source": str(filename), "channel": channel or "", "task": None, "at": int(time.time())}
        self._write_mark(d, mark)                              # first: the folder is this screen's even if the card fails
        try:
            code, r = self.task_action(body)
            mark["task"] = (r.get("added") or {}).get("id") if code < 300 else None
        except Exception:                                      # the video is safe; it just has no card
            mark["task"] = None
        self._write_mark(d, mark)
        return self.state(name)

    # ---- step 2: the thumbnail
    def _keep_old_cover(self, d):
        for f in ("cover.jpg", "cover.png"):                    # never deleted: an earlier pick moves aside
            p = os.path.join(d, f)
            if os.path.isfile(p):
                os.replace(p, os.path.join(d, f"earlier-thumbnail-{int(time.time() * 1000)}{os.path.splitext(f)[1]}"))

    def save_cover(self, name, filename, length, stream):
        d = self._folder(name)
        ext = os.path.splitext(str(filename or ""))[1].lower()
        if ext not in IMAGE_EXT:
            raise ReadyError("a thumbnail is a .jpg or .png picture")
        if length <= 0 or length > MAX_COVER:
            raise ReadyError(f"a thumbnail is at most {MAX_COVER // (1024 * 1024)} MB")
        data = bytearray()
        while len(data) < length:
            chunk = stream.read(min(1 << 20, length - len(data)))
            if not chunk:
                break
            data += chunk
        data = bytes(data)
        png, jpg = data.startswith(b"\x89PNG\r\n\x1a\n"), data.startswith(b"\xff\xd8\xff")
        if len(data) != length or not (png or jpg):
            raise ReadyError("that file is not a JPEG or PNG picture")
        self._keep_old_cover(d)
        target = os.path.join(d, "cover.png" if png else "cover.jpg")
        with open(target + ".part", "wb") as f:
            f.write(data)
        os.replace(target + ".part", target)
        return self.state(name)

    def frame_cover(self, name, at):
        """A frame of the video as the thumbnail."""
        d = self._folder(name)
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise ReadyError("pick a moment in the video") from None
        if not 0 <= at <= 6 * 3600:
            raise ReadyError("pick a moment in the video")
        video = self._video(d)
        tmp = os.path.join(d, ".frame.jpg")
        cmd = [self.ffmpeg, "-y", "-v", "error", "-protocol_whitelist", "file", "-ss", f"{at:.3f}", "-i", video,
               "-frames:v", "1", "-q:v", "2", "-f", "image2", tmp]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            raise ReadyError("could not read a frame from this video", 500) from None
        if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 500:
            raise ReadyError("there is no frame at that moment: pick an earlier one")
        self._keep_old_cover(d)
        os.replace(tmp, os.path.join(d, "cover.jpg"))
        return self.state(name)

    # ---- step 3: the caption
    @staticmethod
    def _caption(d):
        try:
            with open(os.path.join(d, "post.md"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return "", ""
        m = re.search(r"^### Option 1\s*\nTitle:[ \t]*(.*)\n([\s\S]*)$", text, re.M)
        return (m[1].strip(), m[2].strip()) if m else ("", "")

    def save_caption(self, name, title, caption):
        d = self._folder(name)
        title = re.sub(r"\s+", " ", str(title or "")).strip()
        caption = re.sub("\r\n?|[\u2028\u2029\x0b\x0c\x85]", "\n", str(caption or "")).strip()   # every kind of line break is one "\n"
        if not title or not caption:
            raise ReadyError("write a title and a caption")
        if len(title) > TITLE_MAX:
            raise ReadyError(f"the title is longer than {TITLE_MAX} characters")
        if len(caption) > CAPTION_MAX:
            raise ReadyError(f"the caption is longer than Instagram's {CAPTION_MAX} characters")
        if any(re.match(r"\s*#{1,6}\s", ln) for ln in (title + "\n" + caption).split("\n")):
            raise ReadyError("a line can't start with '# ' (a hashtag has no space after the #)")   # it would read as a new section
        safe = caption
        tmp = os.path.join(d, "post.md.part")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {name}\n\n## Captions\n### Option 1\nTitle: {title}\n{safe}\n")
        os.replace(tmp, os.path.join(d, "post.md"))
        return self.state(name)

    # ---- once it is posting, its card is done (it then shows under Scheduled or Posted)
    def posting(self, folder_path):
        try:
            d = os.path.realpath(folder_path)
            task = self._mark(d).get("task")
        except (OSError, ValueError):
            return
        try:                                                   # only this folder's own card, and only while it waits for the owner
            row = next((t for t in self.load_tasks()["tasks"] if t.get("id") == task), None) if task and self.load_tasks else None
        except Exception:
            row = None
        mine = row and row.get("status") == "review" and re.search(r"(?:^|\s)out:" + re.escape(os.path.basename(d)) + r"(?:\s|$)", row.get("note") or "")
        if mine:
            try:
                self.task_action({"action": "move", "id": task, "status": "done"})
            except Exception:                                   # the board is a nice-to-have
                pass

    def action(self, body):
        name = str(body.get("name") or "")
        if body.get("frame") is not None:
            return self.frame_cover(name, body.get("frame"))
        if "caption" in body or "title" in body:
            return self.save_caption(name, body.get("title"), body.get("caption"))
        return self.state(name)
