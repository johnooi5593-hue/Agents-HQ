"""Brand-scoped, versioned thumbnail handoff. No generation starts on import/read.

An intentional video approval or manual post request freezes its exact evidence
and channel template. A linked cover takes its title from the selected video's
versioned local record. Only that request is dispatched to the signed-in Codex
engine; delivery is a separate native review task. No source video is approved
or moved merely by choosing it for a cover.
"""
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from sermon_design import DesignError, inside

BASE = "/api/thumbnail-design"
ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
DIMENSIONS = [[1920, 1080], [1080, 1920], [1080, 1440]]
VIDEOS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


PREVIEWS = Path(__file__).resolve().parent / ".phone-previews"


def small_image(source, key):
    """A phone-sized JPEG preview (480 px wide) of a picture, made once per version (key) and kept in hq/.phone-previews/.
    A full-size Codex PNG is 2–4 MB, too slow for a phone over Tailscale or mobile data. None when ffmpeg can't make it."""
    out = PREVIEWS / (hashlib.sha1(str(key).encode()).hexdigest()[:24] + ".jpg")
    if out.is_file():
        return out
    ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ff:
        return None
    PREVIEWS.mkdir(exist_ok=True)
    tmp = out.with_suffix(".part.jpg")
    try:
        subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-frames:v", "1", "-vf", "scale='min(480,iw)':-2", "-q:v", "4", str(tmp)],
                       capture_output=True, timeout=60, check=True, creationflags=0x08000000 if os.name == "nt" else 0)
        os.replace(tmp, out)
        return out
    except (OSError, subprocess.SubprocessError):
        return None


def send_preview(handler, file, method="GET"):
    """Send a preview JPEG; it never changes for its key, so the phone may keep it."""
    data = Path(file).read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "image/jpeg")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "private, max-age=86400")
    handler.end_headers()
    if method != "HEAD":
        handler.wfile.write(data)


def digest(file):
    with open(file, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def atomic_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, file)


def text(value, maximum, label, required=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise DesignError("Invalid " + label + ".", 400)
    value = value.strip()
    if required and not value:
        raise DesignError("Enter " + label + " before creating thumbnails.", 400)
    return value


class ThumbnailDesignBridge:
    def __init__(self, root, engine, channels, task_action, load_tasks, notify=None, watch_seconds=1800, poll_seconds=3, auto_watch=True):
        self.root, self.engine = Path(root).resolve(), engine
        self.channels, self.task_action, self.load_tasks, self.notify = channels, task_action, load_tasks, notify
        self.base = self.root / "hq" / "thumbnail-design"
        self.index = self.base / "index.json"
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.watcher = None
        self.watch_seconds, self.poll_seconds, self.auto_watch = min(1800, watch_seconds), max(.02, poll_seconds), auto_watch

    def _load(self):
        if not self.index.exists():
            return {"version": 1, "templates": {}, "defaults": {}, "jobs": {}}
        try:
            value = json.loads(self.index.read_text(encoding="utf-8"))
            if value.get("version") != 1 or any(not isinstance(value.get(k), dict) for k in ("templates", "defaults", "jobs")):
                raise ValueError()
            return value
        except (OSError, ValueError, AttributeError):
            raise DesignError("The thumbnail ledger needs repair; it was preserved and no request was replayed.", 409)

    def _save(self, data):
        atomic_json(self.index, data)

    def _channel(self, key):
        # Older native tasks recorded `channel:main`, while Channels owns the
        # main brand under the empty key. Do not alias a real named channel.
        if key == "main" and self.channels.get("main") is None and self.channels.get("") is not None:
            key = ""
        if not isinstance(key, str) or self.channels.get(key) is None:
            raise DesignError("Choose an existing HQ channel.", 400)
        return key

    def _public_template(self, row):
        return {k: row[k] for k in ("id", "channel", "name", "revision", "width", "height", "instructions", "sha256", "createdAt")} | {"previewUrl": BASE + "/templates/" + row["id"] + "/image"}

    def config(self):
        with self.lock:
            data = self._load()
            channels = []
            for channel in self.channels.payload()["channels"]:
                key = channel["key"]
                channels.append({"key": key, "name": channel.get("name") or "Main channel", "templates": [self._public_template(t) for t in data["templates"].values() if t["channel"] == key], "defaultTemplateId": data["defaults"].get(key)})
            return {"channels": channels, "dimensions": DIMENSIONS, "schemaVersion": 1, "postCreation": True, "optionSelection": True, "jobHistory": True, "sourceVideos": True}

    def save_template(self, body):
        channel = self._channel(body.get("channel", ""))
        name = text(body.get("name", ""), 120, "a template name", True)
        instructions = text(body.get("instructions", ""), 2000, "template direction")
        if [body.get("width"), body.get("height")] not in DIMENSIONS:
            raise DesignError("Choose a supported thumbnail size.", 400)
        image = body.get("dataUrl")
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", image or "") if isinstance(image, str) and len(image) < 22 * 1024 * 1024 else None
        if not match:
            raise DesignError("Upload a PNG, JPG or WebP template up to 15 MB.", 400)
        try:
            raw = base64.b64decode(match[2], validate=True)
        except ValueError:
            raise DesignError("The template encoding is invalid.", 400)
        valid = (match[1] == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or (match[1] == "jpeg" and raw.startswith(b"\xff\xd8\xff")) or (match[1] == "webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
        if not valid or not 16 <= len(raw) <= 15 * 1024 * 1024:
            raise DesignError("The template bytes do not match the image format.", 400)
        with self.lock:
            data = self._load()
            ident = uuid.uuid4().hex
            revision = 1 + max([0] + [t["revision"] for t in data["templates"].values() if t["channel"] == channel and t["name"] == name])
            filename = self.base / "templates" / (ident + "." + {"jpeg": "jpg"}.get(match[1], match[1]))
            filename.parent.mkdir(parents=True, exist_ok=True)
            with open(filename, "xb") as output:
                output.write(raw)
            row = {"id": ident, "channel": channel, "name": name, "revision": revision, "width": body["width"], "height": body["height"], "instructions": instructions, "path": str(filename), "mimeType": "image/" + match[1], "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "createdAt": time.time()}
            data["templates"][ident] = row
            if body.get("makeDefault", True):
                data["defaults"][channel] = ident
            self._save(data)
        return self.config()

    def set_default(self, body):
        channel = self._channel(body.get("channel", ""))
        with self.lock:
            data = self._load()
            row = data["templates"].get(body.get("templateId"))
            if not row or row["channel"] != channel:
                raise DesignError("Select a template belonging to this channel.", 400)
            data["defaults"][channel] = row["id"]
            self._save(data)
        return self.config()

    def _folder(self, folder):
        if not isinstance(folder, str) or not re.fullmatch(r"out/[A-Za-z0-9][A-Za-z0-9 ._()-]{0,120}", folder):
            raise DesignError("Choose a video folder waiting in out/.", 400)
        result = inside(self.root / "out", self.root / folder)
        if not result.is_dir():
            raise DesignError("The review video folder is no longer available.", 404)
        return result

    def _source(self, folder, task_id=None, list_videos=True):
        base = self._folder(folder)
        if base.name.startswith(("thumbnail-final-", "sermon-studio-")):
            raise DesignError("This is a final artwork delivery, not a new video approval.", 409)
        tasks = self.load_tasks().get("tasks", [])
        marker = "out:" + base.name
        linked = [t for t in tasks if marker in (t.get("note") or "").split()]
        task = next((t for t in linked if t.get("id") == task_id), None) if task_id else next((t for t in linked if t.get("status") == "review"), None)
        if task_id and not task:
            raise DesignError("The selected task does not own this review folder.", 409)
        if task and task.get("status") != "review":
            raise DesignError("The video task must be waiting for your review.", 409)
        key, known = "", False
        channel_file = base / "channel.txt"
        if channel_file.is_file():
            inside(base, channel_file)
            if channel_file.stat().st_size > 200:
                raise DesignError("The video channel record is invalid.", 409)
            key, known = self._channel(channel_file.read_text(encoding="utf-8").strip()), True
        match = re.search(r"(?:^|\s)channel:([^\s]+)", (task or {}).get("note", ""))
        if match:
            recorded = self._channel(match[1])
            if known and key != recorded:
                raise DesignError("The video and task channel records disagree.", 409)
            key, known = recorded, True
        if task and isinstance(task.get("channel"), str):
            recorded = self._channel(task["channel"])
            if known and key != recorded:
                raise DesignError("The video and task channel records disagree.", 409)
            key, known = recorded, True
        self._channel(key)
        videos = []
        for file in sorted(base.rglob("*")) if list_videos else ():
            if file.suffix.lower() in VIDEOS and file.is_file():
                inside(base, file)
                if len(file.relative_to(base).parts) <= 3:
                    videos.append({"path": file.relative_to(base).as_posix(), "name": file.name, "size": file.stat().st_size, "sha256": digest(file)})
        return base, task, key, known, videos

    def context(self, folder, task_id=None):
        base, task, key, known, videos = self._source(folder, task_id)
        source_rows = self._source_rows(base, task, key, videos) if known else []
        by_path = {s["videoPath"]: s for s in source_rows}
        videos = [v | by_path.get(v["path"], {}) for v in videos]
        with self.lock:
            data = self._load()
            template_id = data["defaults"].get(key)
            jobs = [self._public_job(j) for j in data["jobs"].values() if j["folder"] == folder]
            return {"folder": folder, "taskId": task.get("id") if task else None, "channel": key, "channelKnown": known, "channelName": self.channels.name(key), "videos": videos, "sources": source_rows, "templates": [self._public_template(t) for t in data["templates"].values() if t["channel"] == key], "defaultTemplateId": template_id, "enabled": bool(template_id or jobs), "eligible": bool(videos), "jobs": jobs}

    def _source_rows(self, base, task, channel, videos, task_ids=None):
        """Read actual local title evidence; operational task labels are never titles."""
        def read(file):
            file = inside(base, file)
            if not file.is_file() or file.stat().st_size > 2 * 1024 * 1024:
                return None, None
            raw = file.read_bytes()
            return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()
        # edit/clean are explicitly named variants of one video, not arbitrary
        # video1/video2 outputs that merely happen to occupy the same folder.
        current = [v for v in videos if not re.search(r"(?:^|[_-])(prev|old|backup)(?:$|[_-])", Path(v["path"]).stem, re.I)]
        shared = len(current) == 1 or (bool(current) and len({str(Path(v["path"]).parent) for v in current}) == 1 and all(Path(v["path"]).stem.lower() in ("edit", "clean", "final", "reel", "nocap", "no-caption") for v in current))
        result = []
        for video in videos:
            title, subtitle, evidence, warnings = "", "", [], []
            file = base / video["path"]
            candidates = [file.with_suffix(".metadata.json"), file.with_suffix(".json")]
            for metadata in candidates:
                raw, sha = read(metadata)
                if raw is None: continue
                try:
                    doc = json.loads(raw)
                    if not isinstance(doc, dict) or not isinstance(doc.get("title"), str) or not doc["title"].strip(): continue
                    title = text(doc["title"], 200, "recorded video title", True)
                    subtitle = text(doc.get("subtitle", ""), 200, "recorded video subtitle")
                    evidence = [{"path": metadata.relative_to(base).as_posix(), "sha256": sha}]
                    break
                except (ValueError, TypeError, DesignError):
                    warnings.append("The per-video title record needs correction.")
            if not title and shared and video in current:
                post = file.parent / "post.md"
                raw, sha = read(post)
                if raw is not None:
                    # A selected title is explicit owner input, unlike blindly
                    # choosing the first of several drafted caption options.
                    package = file.parent / "package.json"
                    package_raw, package_sha = read(package)
                    try:
                        pick = json.loads(package_raw).get("caption") if package_raw else None
                        if type(pick) is int and pick >= 0:
                            import publish
                            sections = publish.sections(raw)
                            options = sections.get("options") or []
                            chosen = options[pick]["text"] if pick < len(options) else ""
                            match = re.search(r"^\s*[-*]?\s*(?:youtube\s*)?title\s*[:：]\s*(.+)$", publish.clean(chosen), re.I | re.M)
                            if match:
                                title = text(match[1], 200, "selected video title", True)
                                evidence.append({"path": package.relative_to(base).as_posix(), "sha256": package_sha})
                    except (ValueError, TypeError, AttributeError, DesignError):
                        warnings.append("The selected caption title record needs correction.")
                    if not title:
                        match = re.search(r"^#\s+([^\r\n]+)", raw, re.M)
                        if match:
                            heading = re.sub(r"\s+[·|—-]\s+(?:(?:Facebook|Instagram|YouTube(?: Shorts)?|TikTok|Reels)(?:\s*(?:\+|/|and|&)\s*|\s*)?)+$", "", match[1], flags=re.I).strip()
                            if len(heading) <= 200 and not re.match(r"(?:post(?:ing)?|caption|social(?: media)?|notes|review|audio fix|subtitle fix)\b", heading, re.I):
                                title = heading
                    if title: evidence.insert(0, {"path": post.relative_to(base).as_posix(), "sha256": sha})
            if not title:
                warnings.append("No unambiguous video title is recorded. Add an exact per-video title or correct post.md before making a linked cover.")
            folder = "out/" + base.name
            source_id = hashlib.sha256((folder + "\n" + video["path"]).encode()).hexdigest()
            revision = hashlib.sha256(json.dumps({"sourceId": source_id, "channel": channel, "title": title, "subtitle": subtitle, "evidence": evidence, "videoSha256": video["sha256"]}, sort_keys=True).encode()).hexdigest()
            owners = list(dict.fromkeys(task_ids or ([task["id"]] if task and task.get("id") else [])))
            result.append({"sourceId": source_id, "folder": folder, "taskId": (task or {}).get("id"), "taskIds": owners, "videoPath": video["path"], "channel": channel, "title": title, "subtitle": subtitle, "titleSource": evidence[0]["path"] if evidence else None, "titleEvidence": evidence, "titleRevision": revision, "videoSha256": video["sha256"], "videoUrl": "/files/" + quote(folder + "/" + video["path"], safe="/"), "warnings": warnings})
        return result

    def sources(self, channel):
        channel = self._channel(channel)
        rows, tasks = [], self.load_tasks().get("tasks", [])
        output = self.root / "out"
        if not output.is_dir(): return {"sources": rows}
        for base in sorted(output.iterdir(), key=lambda p: p.name):
            if len(rows) >= 200: break
            if not base.is_dir() or base.name.startswith(("thumbnail-final-", "sermon-studio-")) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,120}", base.name): continue
            try:
                inside(output, base)
                linked = [t for t in tasks if "out:" + base.name in (t.get("note") or "").split()]
                if not linked: continue
                keys = set()
                channel_file = inside(base, base / "channel.txt")
                if channel_file.is_file() and channel_file.stat().st_size <= 200:
                    keys.add(self._channel(channel_file.read_text(encoding="utf-8").strip()))
                for task in linked:
                    match = re.search(r"(?:^|\s)channel:([^\s]+)", task.get("note", ""))
                    if match: keys.add(self._channel(match[1]))
                    if isinstance(task.get("channel"), str): keys.add(self._channel(task["channel"]))
                if keys != {channel}: continue
                task = next((t for t in linked if t.get("status") == "review"), linked[0])
                videos = []
                for file in sorted(base.rglob("*")):
                    if file.is_file() and file.suffix.lower() in VIDEOS and len(file.relative_to(base).parts) <= 3:
                        inside(base, file)
                        videos.append({"path": file.relative_to(base).as_posix(), "sha256": digest(file)})
                rows.extend(self._source_rows(base, task, channel, videos, [t["id"] for t in linked if isinstance(t.get("id"), str)]))
            except (OSError, ValueError, DesignError):
                continue  # An unsafe or contradictory source is never reassigned.
        return {"sources": rows[:200]}

    def _linked_source(self, value, channel):
        if not isinstance(value, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sourceId", ""))) or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("titleRevision", ""))):
            raise DesignError("Choose a current video and its recorded title.", 400)
        source = next((s for s in self.sources(channel)["sources"] if s["sourceId"] == value["sourceId"]), None)
        if not source or source["titleRevision"] != value["titleRevision"]:
            raise DesignError("The video or its title changed. Refresh the source and review its current title before generating.", 409)
        if not source["title"]:
            raise DesignError("This video has no unambiguous recorded title. Correct its title first.", 409)
        return source

    def _public_job(self, row):
        result = {key: row[key] for key in ("id", "mode", "status", "progress", "folder", "taskId", "channel", "title", "subtitle", "instructions", "templateId", "templateRevision", "videoPath", "videoSha256", "sourceFrameAvailable", "referenceName", "sourceVideo", "warnings", "approvedAt", "createdAt", "deadlineAt", "error", "delivery", "width", "height") if key in row}
        result.setdefault("mode", "video")
        result["selectedOption"] = (row.get("selection") or {}).get("name")
        result["reviewUrl"] = "/?task=" + quote(row["delivery"]["taskId"]) if row.get("delivery", {}).get("taskId") else None
        result["options"] = []
        if row.get("delivery"):
            try:
                _, manifest = self._delivered_manifest(row)
                for item in manifest["files"]:
                    if re.fullmatch(r"thumbnail-option-[1-4]\.png", item["name"]):
                        url = BASE + "/jobs/" + row["id"] + "/options/" + item["name"]
                        result["options"].append({"name": item["name"], "sha256": item["sha256"], "url": url, "downloadUrl": url + "?download=1", "width": row.get("width"), "height": row.get("height")})
            except DesignError as error:
                result["optionsError"] = str(error)
        return result

    def list_jobs(self, channel=None):
        if channel is not None:
            self._channel(channel)
        with self.lock:
            rows = [j for j in self._load()["jobs"].values() if channel is None or j["channel"] == channel]
            rows.sort(key=lambda j: j.get("createdAt", j.get("approvedAt", 0)), reverse=True)
            return {"jobs": [self._public_job(j) for j in rows[:50]]}

    def _delivered_manifest(self, row):
        delivery = row.get("delivery")
        if not delivery or row.get("status") != "delivered":
            raise DesignError("The four thumbnail files are not ready yet.", 409)
        name = "thumbnail-final-" + row["id"]
        destination = self.root / "out" / name
        if not destination.exists():
            destination = self.root / "approved" / name
        destination = inside(self.root, destination)
        manifest_file = inside(destination, destination / "thumbnail-final.json")
        channel_file = inside(destination, destination / "channel.txt")
        if not manifest_file.is_file() or not channel_file.is_file() or digest(manifest_file) != delivery.get("manifestSha256") or digest(channel_file) != delivery.get("channelSha256"):
            raise DesignError("The thumbnail delivery record changed or is missing.", 409)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest.get("requestId") != row["id"] or manifest.get("channel") != row["channel"]:
            raise DesignError("The thumbnail delivery identity changed.", 409)
        if len([f for f in manifest.get("files", []) if re.fullmatch(r"thumbnail-option-[1-4]\.png", str(f.get("name", "")))]) != 4:
            raise DesignError("This delivery does not contain four independent thumbnail options.", 409)
        return destination, manifest

    def _verified_option(self, row, name):
        if not isinstance(name, str) or not re.fullmatch(r"thumbnail-option-[1-4]\.png", name):
            raise DesignError("Choose one of this request's four thumbnail images.", 400)
        destination, manifest = self._delivered_manifest(row)
        item = next((f for f in manifest["files"] if f["name"] == name), None)
        file = inside(destination, destination / name)
        if not item or not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
            raise DesignError("The selected thumbnail changed or is missing. Reopen its verified result.", 409)
        return file, item

    def select_option(self, body):
        ident = body.get("jobId")
        if not isinstance(ident, str) or not re.fullmatch(ID, ident):
            raise DesignError("Choose an existing thumbnail request.", 400)
        with self.lock:
            data = self._load(); row = data["jobs"].get(ident)
            if not row:
                raise DesignError("Thumbnail request not found.", 404)
            if "channel" in body and self._channel(body["channel"]) != row["channel"]:
                raise DesignError("This thumbnail belongs to a different channel.", 409)
            if (self.root / "approved" / ("thumbnail-final-" + ident)).exists():
                raise DesignError("This version is already approved. Create a new thumbnail version to change the selection.", 409)
            file, item = self._verified_option(row, body.get("optionName"))
            if body.get("expectedHash") != item["sha256"]:
                raise DesignError("The thumbnail selection is stale. Reopen the current four options.", 409)
            selection = {"requestId": ident, "name": item["name"], "sha256": item["sha256"], "channel": row["channel"], "selectedAt": time.time(), "approved": False}
            selection_file = file.parent / "thumbnail-selection.json"
            atomic_json(selection_file, selection)
            row["selection"] = selection
            row["selectionSHA256"] = digest(selection_file)
            self._save(data)
            return {"job": self._public_job(row), "selection": selection, "approval": "Selection saved; final user OK remains in HQ."}

    def _request(self, method, route, payload=None):
        encoded = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        headers = {"Host": "127.0.0.1:4341", "Content-Type": "application/json", "Origin": "http://127.0.0.1:4341"}
        if encoded is not None:
            headers["Content-Length"] = str(len(encoded))
        code, _, raw = self.engine._request(method, route, encoded, headers)
        try:
            result = json.loads(raw)
        except ValueError:
            raise DesignError("The thumbnail engine returned unreadable metadata.", 502)
        if not 200 <= code < 300:
            raise DesignError(str(result.get("error") or "Thumbnail engine unavailable."), code)
        return result

    def _frame(self, video, destination):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            # The middle of the approved video: its first frame is often black or a slate. Second 0 if the length is unknown.
            at, ffprobe = 0.0, shutil.which("ffprobe")
            if ffprobe:
                probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)], stdin=subprocess.DEVNULL, capture_output=True, timeout=15, creationflags=flags)
                try:
                    duration = float(probe.stdout.decode("utf-8", "replace").strip())
                    at = duration / 2 if probe.returncode == 0 and math.isfinite(duration) and duration > 0 else 0.0
                except ValueError:
                    pass
            result = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % at, "-i", str(video), "-frames:v", "1", "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease", "-y", str(destination)], stdin=subprocess.DEVNULL, capture_output=True, timeout=30, creationflags=flags)
            if result.returncode != 0 or not destination.is_file() or not 0 < destination.stat().st_size < 8 * 1024 * 1024:
                return None
            return {"name": "approved-video-frame.jpg", "dataUrl": "data:image/jpeg;base64," + base64.b64encode(destination.read_bytes()).decode()}
        except (OSError, subprocess.TimeoutExpired):
            return None

    def create_post(self, body):
        """Explicit manual post creation; it does not invent a video approval."""
        channel = self._channel(body.get("channel", ""))
        linked = self._linked_source(body["sourceVideo"], channel) if "sourceVideo" in body else None
        title = linked["title"] if linked else text(body.get("title", ""), 200, "the exact thumbnail title", True)
        subtitle = linked["subtitle"] if linked else text(body.get("subtitle", ""), 200, "subtitle")
        direction = text(body.get("instructions", ""), 2000, "post art direction")
        request_key = body.get("idempotencyKey", body.get("requestKey", ""))
        if not isinstance(request_key, str) or (request_key and not re.fullmatch(ID, request_key)):
            raise DesignError("Use a bounded thumbnail request key.", 400)
        source_bytes, source_mime, source_name = self._parse_source(body.get("sourceImage"), "post reference")
        with self.lock:
            if linked:
                linked = self._linked_source(body["sourceVideo"], channel)
            data = self._load()
            template = data["templates"].get(body.get("templateId") or data["defaults"].get(channel))
            if not template or template["channel"] != channel:
                raise DesignError("Upload or choose a template for this channel first.", 409)
            width, height = body.get("width", template["width"]), body.get("height", template["height"])
            if type(width) is not int or type(height) is not int or [width, height] not in DIMENSIONS:
                raise DesignError("Choose a supported post thumbnail size.", 400)
            template_file = inside(self.base / "templates", template["path"])
            if not template_file.is_file() or digest(template_file) != template["sha256"]:
                raise DesignError("The selected template changed. Upload a new version.", 409)
            source_identity = {k: linked[k] for k in ("sourceId", "titleRevision")} if linked else None
            signature = hashlib.sha256(json.dumps({"mode": "post", "channel": channel, "title": title, "subtitle": subtitle, "instructions": direction, "templateId": template["id"], "templateSHA256": template["sha256"], "width": width, "height": height, "sourceVideo": source_identity, "sourceSHA256": hashlib.sha256(source_bytes).hexdigest() if source_bytes else None}, sort_keys=True).encode()).hexdigest()
            prior = next((j for j in reversed(list(data["jobs"].values())) if j.get("mode") == "post" and (j.get("requestKey") == request_key if request_key else j.get("signature") == signature)), None)
            if prior:
                if prior.get("signature") != signature:
                    raise DesignError("This request key belongs to different post settings. Start a new version.", 409)
                if not (body.get("retry") is True and prior["status"] == "failed"):
                    return {"job": self._public_job(prior)}
            if any(j.get("mode") == "post" and j["channel"] == channel and j["status"] in ("dispatching", "watching", "delivery-error", "uncertain") for j in data["jobs"].values()):
                raise DesignError("A post thumbnail request is already accepted or needs checking. Open its status before creating another batch.", 409)
            self.engine.ensure_engine()
            caps = self._request("GET", BASE + "/capabilities")
            if caps.get("schemaVersion") != 1:
                raise DesignError("Load the prepared thumbnail engine update first.", 503)
            ident = uuid.uuid4().hex
            frozen = self.base / "requests" / ident; frozen.mkdir(parents=True)
            frozen_template = frozen / "template" / template_file.name; frozen_template.parent.mkdir()
            shutil.copyfile(template_file, frozen_template)
            if digest(frozen_template) != template["sha256"]:
                raise DesignError("The template changed while saving this post request.", 409)
            now = time.time()
            row = {"id": ident, "mode": "post", "status": "dispatching", "progress": 0, "signature": signature, "requestKey": request_key, "folder": "", "taskId": None, "channel": channel, "title": title, "subtitle": subtitle, "instructions": direction, "width": width, "height": height, "templateId": template["id"], "templateRevision": template["revision"], "templateSha256": template["sha256"], "frozenTemplatePath": str(frozen_template), "createdAt": now, "deadlineAt": now + self.watch_seconds, "warnings": [], "sourceFrameAvailable": bool(source_bytes)}
            provenance = {"mode": "post", "requestId": ident, "channel": channel, "templateId": template["id"], "templateRevision": template["revision"], "templateSha256": template["sha256"], "submittedAt": now, "sourceImageSHA256": hashlib.sha256(source_bytes).hexdigest() if source_bytes else None}
            if linked:
                row["sourceVideo"] = linked
                provenance["sourceVideo"] = linked
            instructions = (template["instructions"] + ("\nPost-specific direction: " + direction if direction else "")).strip()
            if len(instructions) > 3000:
                raise DesignError("Keep combined template and post direction under 3000 characters.", 400)
            payload = {"requestId": ident, "title": title, "subtitle": subtitle, "width": width, "height": height, "instructions": instructions, "template": {"name": template["name"], "dataUrl": "data:" + template["mimeType"] + ";base64," + base64.b64encode(frozen_template.read_bytes()).decode()}, "provenance": provenance}
            if source_bytes:
                source_file = frozen / ("post-reference." + {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[source_mime])
                source_file.write_bytes(source_bytes)
                row.update(sourceImagePath=str(source_file), sourceImageSHA256=provenance["sourceImageSHA256"])
                payload["sourceFrame"] = {"name": source_name, "dataUrl": "data:" + source_mime + ";base64," + base64.b64encode(source_bytes).decode()}
            if linked:
                self._linked_source(body["sourceVideo"], channel)
            row["requestSha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            atomic_json(frozen / "request.json", payload)
            data["jobs"][ident] = row; self._save(data)
            try:
                accepted = self._request("POST", BASE + "/jobs", payload).get("job", {})
                if accepted.get("id") != ident:
                    raise DesignError("The engine returned a different request identity. No generation was repeated.", 502)
                row["status"] = "watching"
            except Exception as error:
                rejected = isinstance(error, DesignError) and error.status in (400, 403, 404, 409, 413, 415)
                row.update(status="failed" if rejected else "uncertain", error=("The engine rejected this request; no generation was accepted. " if rejected else "Submission outcome needs checking; generation was not repeated. ") + str(error)[:500])
            self._save(data); self.resume_pending()
            return {"job": self._public_job(row)}

    @staticmethod
    def _parse_source(source, label):
        """The owner's reference picture (a person or subject the thumbnails must follow), as (bytes, mime, name);
        (None, None, None) when there is none."""
        if source is None:
            return None, None, None
        if not isinstance(source, dict):
            raise DesignError(f"Choose a PNG, JPG or WebP {label}.", 400)
        name = text(source.get("name", label.replace(" ", "-")), 180, label + " name", True)
        encoded = source.get("dataUrl")
        match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)", encoded or "") if isinstance(encoded, str) and len(encoded) < 22 * 1024 * 1024 else None
        if not match:
            raise DesignError(f"Use a PNG, JPG or WebP {label} up to 15 MB.", 400)
        try:
            data = base64.b64decode(match[2], validate=True)
        except ValueError:
            raise DesignError(f"The {label} encoding is invalid.", 400)
        mime = match[1]
        valid = (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff")) or (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        if not valid or not 16 <= len(data) <= 15 * 1024 * 1024:
            raise DesignError(f"The {label} bytes do not match its image format.", 400)
        return data, mime, name

    def approve_video(self, body):
        if body.get("approval") is not True:
            raise DesignError("Use Approve video & create thumbnails to approve this exact video version.", 400)
        # the owner's own reference picture, if any: it replaces the frame taken from the video as the subject reference
        source_bytes, source_mime, source_name = self._parse_source(body.get("sourceImage"), "thumbnail reference")
        title = text(body.get("title", ""), 200, "the exact thumbnail title", "sourceVideo" not in body)
        subtitle = text(body.get("subtitle", ""), 200, "subtitle")
        direction = text(body.get("instructions", ""), 2000, "video art direction")
        base, task, inferred, known, videos = self._source(body.get("folder"), body.get("taskId"))
        channel = self._channel(body.get("channel", inferred))
        linked = self._linked_source(body["sourceVideo"], channel) if "sourceVideo" in body else None
        if linked:
            if linked["folder"] != body.get("folder") or linked["videoPath"] != body.get("videoPath"):
                raise DesignError("The selected title belongs to another video.", 409)
            title, subtitle = linked["title"], linked["subtitle"]
        if known and channel != inferred:
            raise DesignError("The chosen channel differs from this video's saved channel.", 409)
        video = next((v for v in videos if v["path"] == body.get("videoPath")), None)
        if not video or video["sha256"] != body.get("videoSha256"):
            raise DesignError("The video changed or is not selected. Reopen it and approve its current version.", 409)
        with self.lock:
            # The review may have changed while this request waited for the
            # shared mutation lock. Re-read it rather than trusting the form.
            base, current_task, current_channel, current_known, current_videos = self._source(body.get("folder"), body.get("taskId"))
            if (current_task or {}).get("id") != (task or {}).get("id") or (current_known and current_channel != channel):
                raise DesignError("The video task or channel changed. Reopen the current review before approving.", 409)
            if not any(v["path"] == video["path"] and v["sha256"] == video["sha256"] for v in current_videos):
                raise DesignError("The video changed while approval was pending.", 409)
            data = self._load()
            template = data["templates"].get(body.get("templateId") or data["defaults"].get(channel))
            if not template or template["channel"] != channel:
                raise DesignError("Upload or choose this channel's thumbnail template first.", 409)
            template_file = inside(self.base / "templates", template["path"])
            if digest(template_file) != template["sha256"]:
                raise DesignError("The saved template changed. Upload a new version.", 409)
            size = [body.get("width", template["width"]), body.get("height", template["height"])]   # 9:16 for YouTube + Facebook, 3:4 for Instagram
            if size not in DIMENSIONS:
                raise DesignError("Choose 1080×1920, 1080×1440 or 1920×1080.", 400)
            identity = {"folder": body["folder"], "taskId": task.get("id") if task else None, "video": video, "templateId": template["id"], "title": title, "subtitle": subtitle, "direction": direction, "channel": channel}
            if size != [template["width"], template["height"]]: identity["size"] = size
            if linked: identity["sourceVideo"] = {k: linked[k] for k in ("sourceId", "titleRevision")}
            if source_bytes: identity["reference"] = hashlib.sha256(source_bytes).hexdigest()   # a new reference picture is a new request
            signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            prior = next((j for j in data["jobs"].values() if j.get("signature") == signature), None)
            if prior and not (body.get("retry") is True and prior["status"] == "failed"):
                return {"job": self._public_job(prior)}
            if any(j["folder"] == body["folder"] and j["status"] in ("dispatching", "watching", "delivery-error", "uncertain")
                   and [j.get("width"), j.get("height")] in (size, [None, None]) for j in data["jobs"].values()):   # one request per size at a time
                raise DesignError("This video already has an accepted or uncertain thumbnail request. Open its status first.", 409)
            self.engine.ensure_engine()
            caps = self._request("GET", BASE + "/capabilities")
            if caps.get("schemaVersion") != 1:
                raise DesignError("Restart the prepared design engine to activate thumbnails.", 503)
            ident = uuid.uuid4().hex
            frozen = self.base / "requests" / ident
            frozen.mkdir(parents=True)
            frozen_template = frozen / template_file.name
            shutil.copyfile(template_file, frozen_template)
            if digest(frozen_template) != template["sha256"]:
                raise DesignError("Template changed while freezing this request.", 409)
            row = {"id": ident, "status": "dispatching", "progress": 0, "signature": signature, "folder": body["folder"], "taskId": task.get("id") if task else None, "channel": channel, "title": title, "templateId": template["id"], "templateRevision": template["revision"], "templateSha256": template["sha256"], "videoPath": video["path"], "videoSha256": video["sha256"], "videoSize": video["size"], "approvedAt": time.time(), "deadlineAt": time.time() + self.watch_seconds, "width": size[0], "height": size[1]}
            row.update(subtitle=subtitle, instructions=direction)
            payload = {"requestId": ident, "title": title, "subtitle": subtitle, "width": size[0], "height": size[1], "instructions": template["instructions"] + ("\nVideo-specific direction: " + direction if direction else ""), "template": {"name": template["name"], "dataUrl": "data:" + template["mimeType"] + ";base64," + base64.b64encode(frozen_template.read_bytes()).decode()}, "provenance": {k: row[k] for k in ("folder", "taskId", "channel", "templateId", "templateRevision", "templateSha256", "videoPath", "videoSha256", "approvedAt")}}
            if linked:
                row["sourceVideo"] = linked
                payload["provenance"]["sourceVideo"] = linked
            if len(payload["instructions"]) > 3000:
                raise DesignError("Keep combined template and video direction under 3000 characters.", 400)
            if source_bytes:                                  # the owner's reference picture stands in for the video frame
                reference = frozen / ("reference." + {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[source_mime])
                reference.write_bytes(source_bytes)
                row.update(sourceImagePath=str(reference), sourceImageSHA256=hashlib.sha256(source_bytes).hexdigest(), referenceName=source_name)
                payload["provenance"]["referenceSha256"] = row["sourceImageSHA256"]
                frame = {"name": source_name, "dataUrl": "data:" + source_mime + ";base64," + base64.b64encode(source_bytes).decode()}
            else:
                frame = self._frame(base / video["path"], frozen / "source-frame.jpg")
            if frame:
                payload["sourceFrame"] = frame
            row["sourceFrameAvailable"] = bool(frame)
            row["warnings"] = [] if frame else ["No video frame could be extracted. The template is the only visual reference; no video subject identity was verified."]
            payload["provenance"]["sourceFrameAvailable"] = bool(frame)
            _, dispatch_task, dispatch_channel, dispatch_known, dispatch_videos = self._source(body.get("folder"), body.get("taskId"))
            if (dispatch_task or {}).get("id") != (task or {}).get("id") or (dispatch_known and dispatch_channel != channel):
                raise DesignError("The video task or channel changed while preparing its reference. Reopen it before approving.", 409)
            if not any(v["path"] == video["path"] and v["sha256"] == video["sha256"] for v in dispatch_videos):
                raise DesignError("The video changed while preparing its reference. Reopen and approve it again.", 409)
            if linked:
                self._linked_source(body["sourceVideo"], channel)
            row["requestSha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            atomic_json(frozen / "request.json", payload)
            data["jobs"][ident] = row
            self._save(data)  # durable before the only model-generating POST
            try:
                result = self._request("POST", BASE + "/jobs", payload)
                accepted = result.get("job", result)
                if accepted.get("id") != ident:
                    raise DesignError("The engine returned a different request identity; no retry was made.", 502)
                row["status"] = "watching"
            except Exception as error:
                rejected = isinstance(error, DesignError) and error.status in (400, 403, 404, 409, 413, 415)
                row.update(status="failed" if rejected else "uncertain", error=("The engine rejected this request; no generation was accepted. " if rejected else "The request outcome needs checking; generation was not repeated. ") + str(error)[:500])
            self._save(data)
            self.resume_pending()
            return {"job": self._public_job(row)}

    def _verify_source(self, row):
        if row.get("sourceVideo"):
            self._linked_source(row["sourceVideo"], row["channel"])
        base, _, channel, known, _ = self._source(row["folder"], row.get("taskId"))
        if known and channel != row["channel"]:
            raise DesignError("The source channel changed after video approval. No cross-brand final delivery is allowed.", 409)
        video = inside(base, base / row["videoPath"])
        if not video.is_file() or video.stat().st_size != row["videoSize"] or digest(video) != row["videoSha256"]:
            raise DesignError("The approved video changed. These thumbnails cannot be presented as its final package.", 409)
        if row.get("taskId"):
            task = next((t for t in self.load_tasks().get("tasks", []) if t.get("id") == row["taskId"]), None)
            if not task or task.get("status") != "review" or "out:" + base.name not in (task.get("note") or "").split():
                raise DesignError("The source task changed since video approval. No final delivery was substituted.", 409)
        return base, video

    def _verify_post_source(self, row):
        self._channel(row["channel"])
        if row.get("sourceVideo"):
            self._linked_source(row["sourceVideo"], row["channel"])
        frozen = inside(self.base / "requests", self.base / "requests" / row["id"])
        request_file = inside(frozen, frozen / "request.json")
        request = json.loads(request_file.read_text(encoding="utf-8"))
        if hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest() != row["requestSha256"] or request.get("provenance", {}).get("mode") != "post" or request.get("provenance", {}).get("channel") != row["channel"]:
            raise DesignError("The frozen post request changed.", 409)
        template_data = request.get("template", {}).get("dataUrl", "").split(",", 1)
        if len(template_data) != 2 or hashlib.sha256(base64.b64decode(template_data[1], validate=True)).hexdigest() != row["templateSha256"]:
            raise DesignError("The frozen post template changed.", 409)
        if row.get("frozenTemplatePath"):
            template = inside(frozen, row["frozenTemplatePath"])
            if not template.is_file() or digest(template) != row["templateSha256"]:
                raise DesignError("The frozen post template file changed.", 409)
        if row.get("sourceImagePath"):
            image = inside(frozen, row["sourceImagePath"])
            if not image.is_file() or digest(image) != row.get("sourceImageSHA256"):
                raise DesignError("The original post reference changed.", 409)
        return request

    def _deliver_post(self, row, job, request):
        self._verify_post_source(row)
        files = job.get("files") or job.get("result", {}).get("files")
        if not isinstance(files, list) or not 4 <= len(files) <= 20:
            raise DesignError("The engine did not return four independent post thumbnail files.", 502)
        owned = self.engine.runtime_root / ".studio" / "thumbnail-design" / "jobs" / row["id"] / "output"
        verified, names, images = [], set(), set()
        for item in files:
            name = str(item.get("name", ""))
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name) or name.casefold() in names:
                raise DesignError("Unsafe or repeated post thumbnail filename.", 502)
            names.add(name.casefold()); file = inside(owned, item.get("path", ""))
            if not file.is_file() or not 0 < file.stat().st_size <= 40 * 1024 * 1024 or file.stat().st_size != item.get("size") or digest(file) != item.get("sha256"):
                raise DesignError("Post thumbnail checksum failed.", 502)
            if file.suffix.lower() == ".png":
                if not re.fullmatch(r"thumbnail-option-[1-4]\.png", name):
                    raise DesignError("The returned post images are not four independent options.", 502)
                with open(file, "rb") as source:
                    header = source.read(24)
                if len(header) != 24 or not header.startswith(b"\x89PNG\r\n\x1a\n") or int.from_bytes(header[16:20], "big") != request["width"] or int.from_bytes(header[20:24], "big") != request["height"]:
                    raise DesignError("The post thumbnail dimensions do not match the requested canvas.", 502)
                images.add(name)
            elif name != "thumbnail-manifest.json":
                raise DesignError("The post delivery contains an unrelated file.", 502)
            verified.append((file, name, item["sha256"]))
        if images != {"thumbnail-option-" + str(i) + ".png" for i in range(1, 5)}:
            raise DesignError("Exactly four separate PNG post options are required.", 502)
        folder = "thumbnail-final-" + row["id"]; destination = self.root / "out" / folder
        if (self.root / "approved" / folder).exists():
            raise DesignError("This post delivery is already approved and will not be overwritten.", 409)
        if not destination.exists():
            temporary = self.root / "out" / ("." + folder + "-" + uuid.uuid4().hex); temporary.mkdir(parents=True)
            for source, name, checksum in verified:
                target = temporary / name; shutil.copyfile(source, target)
                if digest(target) != checksum:
                    raise DesignError("A post file changed while being delivered; no review success was recorded.", 409)
            (temporary / "channel.txt").write_text(row["channel"], encoding="utf-8")
            manifest = {"schemaVersion": 1, "mode": "post", "requestId": row["id"], "channel": row["channel"], "postRequest": request["provenance"], "status": "awaiting_approval", "files": [{"name": n, "sha256": h, "size": f.stat().st_size} for f, n, h in verified]}
            atomic_json(temporary / "thumbnail-final.json", manifest); os.replace(temporary, destination)
        manifest = json.loads((destination / "thumbnail-final.json").read_text(encoding="utf-8"))
        expected_files = [{"name": n, "sha256": h, "size": f.stat().st_size} for f, n, h in verified]
        if manifest.get("requestId") != row["id"] or manifest.get("mode") != "post" or manifest.get("channel") != row["channel"] or manifest.get("postRequest") != request["provenance"] or manifest.get("files") != expected_files:
            raise DesignError("The existing post package has different request provenance.", 409)
        for _, name, checksum in verified:
            target = inside(destination, destination / name)
            if not target.is_file() or digest(target) != checksum:
                raise DesignError("The existing post thumbnail package changed. It was not overwritten.", 409)
        marker = "out:" + folder
        task = next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split()), None)
        if not task:
            code, result = self.task_action({"action": "add", "title": "Post cover · " + row["title"], "team": "Design", "agent": "poster-designer", "status": "review", "kind": "approval", "note": marker + " thumbnail-request:" + row["id"] + (" channel:" + row["channel"] if row["channel"] else ""), "subtitle": "4 separate post cover choices · choose one, then final OK"})
            if code != 201 or not result.get("added", {}).get("id"):
                raise DesignError("Post files are ready but the review task could not be registered.", 502)
            task = result["added"]
        return {"folder": "out/" + folder, "taskId": task["id"], "manifestSha256": digest(destination / "thumbnail-final.json"), "channelSha256": digest(destination / "channel.txt")}

    def _deliver(self, row, job):
        request = json.loads((self.base / "requests" / row["id"] / "request.json").read_text(encoding="utf-8"))
        if hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest() != row["requestSha256"]:
            raise DesignError("The frozen thumbnail request changed. No final delivery was registered.", 409)
        provenance = job.get("request", {}).get("provenance")
        if provenance != request["provenance"]:
            raise DesignError("The thumbnail result does not match its approved video and template provenance.", 502)
        for field in ("title", "subtitle", "width", "height", "instructions"):
            expected = request[field].strip() if isinstance(request[field], str) else request[field]
            if job.get("request", {}).get(field) != expected:
                raise DesignError("The returned thumbnail brief differs from its frozen request.", 502)
        if row.get("mode") == "post":
            return self._deliver_post(row, job, request)
        source_folder, video = self._verify_source(row)
        files = job.get("files") or job.get("result", {}).get("files")
        if not isinstance(files, list) or not 4 <= len(files) <= 20:
            raise DesignError("The engine did not return four independent thumbnail files.", 502)
        verified, names, count = [], set(), 0
        owned = self.engine.runtime_root / ".studio" / "thumbnail-design" / "jobs" / row["id"] / "output"
        for item in files:
            name = str(item.get("name", ""))
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name) or name.lower() in names:
                raise DesignError("Unsafe or repeated thumbnail delivery name.", 502)
            names.add(name.lower())
            file = inside(owned, item.get("path", ""))
            if not file.is_file() or not 0 < file.stat().st_size <= 40 * 1024 * 1024 or file.stat().st_size != item.get("size") or digest(file) != item.get("sha256"):
                raise DesignError("Thumbnail delivery checksum failed.", 502)
            if file.suffix.lower() == ".png":
                count += 1
            verified.append((file, name, item["sha256"]))
        if count != 4:
            raise DesignError("Exactly four separate PNG choices are required.", 502)
        folder = "thumbnail-final-" + row["id"]
        destination = self.root / "out" / folder
        approved = self.root / "approved" / folder
        if approved.exists():
            raise DesignError("This final delivery was already approved; it will not be replaced.", 409)
        package_files = list(verified) + [(video, "video" + video.suffix.lower(), row["videoSha256"])]
        # Deliberately exclude followups.json, old thumbnails and publication state.
        caption_folder = video.parent
        parent_videos = [p for p in caption_folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEOS]
        for file in caption_folder.iterdir():
            if file.is_file() and (file.name in ("post.md", "notes.md") or file.suffix.lower() in (".srt", ".vtt")):
                inside(source_folder, file)
                unambiguous = len(parent_videos) == 1 or (file.suffix.lower() in (".srt", ".vtt") and file.stem == video.stem)
                if unambiguous and file.stat().st_size <= 2 * 1024 * 1024:
                    package_files.append((file, file.name, digest(file)))
                elif not unambiguous:
                    warning = "Ambiguous companion copy/captions were omitted: " + file.relative_to(source_folder).as_posix()
                    if warning not in row.setdefault("warnings", []):
                        row["warnings"].append(warning)
        if len({name.casefold() for _, name, _ in package_files}) != len(package_files):
            raise DesignError("Final package filenames collide.", 409)
        if not destination.exists():
            temporary = self.root / "out" / ("." + folder + "-" + uuid.uuid4().hex)
            temporary.mkdir(parents=True)
            for source, name, checksum in package_files:
                target = temporary / name
                shutil.copyfile(source, target)
                if digest(target) != checksum:
                    raise DesignError("A source changed during final delivery; the incomplete package was retained for repair.", 409)
            (temporary / "channel.txt").write_text(row["channel"], encoding="utf-8")
            manifest = {"schemaVersion": 1, "requestId": row["id"], "sourceTaskId": row.get("taskId"), "sourceFolder": row["folder"], "channel": row["channel"], "videoApproval": request["provenance"], "status": "awaiting_approval", "warnings": row.get("warnings", []), "files": [{"name": n, "sha256": h, "size": f.stat().st_size} for f, n, h in package_files]}
            atomic_json(temporary / "thumbnail-final.json", manifest)
            os.replace(temporary, destination)
        manifest = json.loads((destination / "thumbnail-final.json").read_text(encoding="utf-8"))
        if manifest.get("requestId") != row["id"]:
            raise DesignError("The existing final package belongs to another request.", 409)
        for source, name, checksum in package_files:
            target = inside(destination, destination / name)
            if not target.is_file() or digest(target) != checksum:
                raise DesignError("The existing final package changed. It was not overwritten.", 409)
        marker = "out:" + folder
        task = next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split()), None)
        if not task:
            code, result = self.task_action({"action": "add", "title": "Final · " + row["title"], "team": "Design", "agent": "codex-graphic-designer", "status": "review", "kind": "approval", "note": marker + " thumbnail-request:" + row["id"] + (" source-task:" + row["taskId"] if row.get("taskId") else ""), "subtitle": "Approved video + 4 Codex thumbnail options · final OK required"})
            if code != 201:
                raise DesignError("Files are ready, but the final review task could not be registered.", 502)
            task = result["added"]
        return {"folder": "out/" + folder, "taskId": task["id"], "manifestSha256": digest(destination / "thumbnail-final.json"), "channelSha256": digest(destination / "channel.txt")}

    def poll(self, ident):
        with self.lock:
            data = self._load()
            row = data["jobs"].get(ident)
            if not row:
                raise DesignError("Thumbnail request not found.", 404)
            if row["status"] not in ("watching", "dispatching", "uncertain", "delivery-error"):
                return {"job": self._public_job(row)}
            try:
                self.engine._probe()  # read-only; never starts an engine or model
                result = self._request("GET", BASE + "/jobs/" + ident)
                job = result.get("job", result)
                if job.get("id") != ident:
                    raise DesignError("Unexpected thumbnail request identity.", 502)
                row["progress"] = max(0, min(100, float(job.get("progress") or 0)))
                if job.get("status") == "succeeded":
                    row["delivery"] = self._deliver(row, job)
                    row.update(status="delivered", progress=100)
                    row.pop("error", None)
                elif job.get("status") in ("failed", "interrupted", "cancelled"):
                    row.update(status="failed", error=str(job.get("error") or "Thumbnail generation failed; no automatic retry was made.")[:1000])
                else:
                    row["status"] = "watching"
            except Exception as error:
                row.update(status="delivery-error", error=str(error)[:1000])
            self._save(data)
        if self.notify:
            self.notify()
        return {"job": self._public_job(row)}

    def resume_pending(self):
        if not self.auto_watch or self.stop.is_set():
            return
        with self.lock:
            if self.watcher and self.watcher.is_alive():
                return
            if not any(j["status"] in ("watching", "dispatching", "uncertain") and j["deadlineAt"] > time.time() for j in self._load()["jobs"].values()):
                return
            self.watcher = threading.Thread(target=self._watch, name="codex-thumbnail-delivery", daemon=True)
            self.watcher.start()

    def _watch(self):
        while not self.stop.is_set():
            with self.lock:
                rows = [j for j in self._load()["jobs"].values() if j["status"] in ("watching", "dispatching", "uncertain") and j["deadlineAt"] > time.time()]
            if not rows:
                return
            for row in rows:
                self.poll(row["id"])
            self.stop.wait(self.poll_seconds)

    def guard_approval(self, name):
        """Called before native folder approval. Final package hashes remain binding."""
        if name.startswith("thumbnail-final-"):
            ident = name[len("thumbnail-final-"):]
            jobs = self._load()["jobs"]
            row = jobs.get(ident)
            if not row or row.get("status") != "delivered":
                return "This thumbnail package has no verified final delivery."
            if row.get("mode") == "post":
                try:
                    self._verify_post_source(row)
                    destination, manifest = self._delivered_manifest(row)
                    selection = row.get("selection")
                    if not selection:
                        return "Choose one of the four post thumbnails in Thumbnail Studio before final OK."
                    selection_file = inside(destination, destination / "thumbnail-selection.json")
                    if not selection_file.is_file() or digest(selection_file) != row.get("selectionSHA256") or json.loads(selection_file.read_text(encoding="utf-8")) != selection:
                        raise ValueError()
                    _, selected = self._verified_option(row, selection["name"])
                    if selected["sha256"] != selection.get("sha256"):
                        raise ValueError()
                    for item in manifest["files"]:
                        file = inside(destination, destination / item["name"])
                        if not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
                            raise ValueError()
                except Exception:
                    return "The selected post thumbnail or its verified package changed. Reopen the current version before final OK."
                return None
            # only a newer request of the same size replaces this one: a video has a 9:16 set and a 3:4 set side by side
            templates = self._load()["templates"]
            size = lambda j: [j.get("width"), j.get("height")] if j.get("width") else [(templates.get(j.get("templateId")) or {}).get(k) for k in ("width", "height")]
            newer = any(j["folder"] == row["folder"] and j.get("videoPath") == row["videoPath"] and (j.get("approvedAt") or 0) > row["approvedAt"]
                        and size(j) == size(row) and j.get("status") != "failed" for j in jobs.values())
            if newer:
                return "A newer thumbnail revision was requested for this video. Review that version before final approval."
            destination = self.root / "out" / name
            try:
                self._verify_source(row)
                if digest(destination / "thumbnail-final.json") != row["delivery"]["manifestSha256"] or digest(destination / "channel.txt") != row["delivery"]["channelSha256"]:
                    raise ValueError()
                manifest = json.loads((destination / "thumbnail-final.json").read_text(encoding="utf-8"))
                if manifest.get("requestId") != ident:
                    raise ValueError()
                for item in manifest["files"]:
                    target = inside(destination, destination / item["name"])
                    if digest(target) != item["sha256"] or target.stat().st_size != item["size"]:
                        raise ValueError()
            except Exception:
                return "The reviewed video or final package changed. Reopen its current version before approving."
            return None
        try:
            base = self._folder("out/" + name)
            videos = any(p.is_file() and p.suffix.lower() in VIDEOS for p in base.rglob("*"))
        except DesignError:
            return None
        if not videos:
            return None
        # A channel without a default template keeps the plain approval (and Approve & post). Once it has one, or this
        # folder already went to Codex, the cover comes first. A folder whose channel cannot be read stays guarded.
        try:
            key = self._source("out/" + name, list_videos=False)[2]
        except DesignError:
            key = None
        with self.lock:
            data = self._load()
            started = any(j["folder"] == "out/" + name for j in data["jobs"].values())
            if key is not None and not data["defaults"].get(key) and not started:
                return None
        return "Use Approve video & create thumbnails first, then approve the returned final package."

    def complete_source(self, final_task, db, set_status):
        """Within the existing TASK_LOCK, after the final folder was actually moved."""
        match = re.search(r"(?:^|\s)thumbnail-request:(" + ID + r")(?:\s|$)", final_task.get("note", ""))
        if not match:
            return
        data = self._load()
        row = data["jobs"].get(match[1])
        if row and row.get("mode") == "post":
            return  # Standalone post covers own no source video task.
        if row and row.get("delivery", {}).get("taskId") == final_task.get("id"):
            source = next((t for t in db["tasks"] if t.get("id") == row.get("taskId")), None)
            if source and source.get("status") == "review":
                # A folder may hold several independently approved videos.
                # Mark its root done only after every current video has an
                # approved latest final, never on the first delivered clip.
                try:
                    _, _, _, _, videos = self._source(row["folder"], source["id"])
                    for video in videos:
                        matches = [j for j in data["jobs"].values() if j["folder"] == row["folder"] and j["videoPath"] == video["path"]]
                        latest = max(matches, key=lambda j: j["approvedAt"]) if matches else None
                        if not latest or latest["videoSha256"] != video["sha256"] or latest.get("status") != "delivered" or not (self.root / "approved" / ("thumbnail-final-" + latest["id"])).is_dir():
                            return
                    if videos:
                        set_status(source, "done")
                except DesignError:
                    return

    def handle(self, handler):
        url = urlparse(handler.path)
        path, method = unquote(url.path), handler.command
        if not path.startswith(BASE + "/"):
            return False
        try:
            body = {}
            if method == "POST":
                origin = handler.headers.get("Origin")
                expected = (handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "").lower()
                scheme = (handler.headers.get("X-Forwarded-Proto") or "http").lower()
                parsed = urlparse(origin) if origin else None
                if handler.headers.get("Sec-Fetch-Site") == "cross-site" or (parsed and (parsed.netloc.lower() != expected or parsed.scheme != scheme or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password)):
                    raise DesignError("Open thumbnails in your signed-in Agent HQ.", 403)
                try:
                    length = int(handler.headers.get("Content-Length") or 0)
                except ValueError:
                    raise DesignError("Invalid request size.", 400)
                if handler.headers.get("Transfer-Encoding") or not 0 < length <= 22 * 1024 * 1024:
                    raise DesignError("Use a bounded thumbnail JSON request.", 413)
                if not handler.headers.get("Content-Type", "").startswith("application/json"):
                    raise DesignError("Send thumbnail settings as JSON.", 415)
                raw = handler.rfile.read(length)
                try:
                    body = json.loads(raw)
                    if len(raw) != length or not isinstance(body, dict):
                        raise ValueError()
                except ValueError:
                    raise DesignError("Invalid thumbnail JSON request.", 400)
            query = parse_qs(url.query, keep_blank_values=True)
            if method == "GET" and path == BASE + "/config":
                result = self.config()
            elif method == "GET" and path == BASE + "/context":
                result = self.context(query.get("folder", [""])[0], query.get("taskId", [None])[0])
            elif method == "GET" and path == BASE + "/sources":
                result = self.sources(query.get("channel", [""])[0])
            elif method == "POST" and path == BASE + "/templates":
                result = self.save_template(body)
            elif method == "POST" and path == BASE + "/default":
                result = self.set_default(body)
            elif method == "POST" and path == BASE + "/approve-video":
                result = self.approve_video(body)
            elif method == "POST" and path == BASE + "/create-post":
                result = self.create_post(body)
            elif method == "POST" and path == BASE + "/select":
                result = self.select_option(body)
            elif method == "GET" and path == BASE + "/jobs":
                result = self.list_jobs(query.get("channel", [None])[0])
            elif method == "GET" and re.fullmatch(BASE + "/jobs/" + ID, path):
                result = self.poll(path.rsplit("/", 1)[1])
            elif method in ("GET", "HEAD") and re.fullmatch(BASE + "/jobs/" + ID + r"/options/thumbnail-option-[1-4]\.png", path):
                ident, name = path.split("/")[-3], path.rsplit("/", 1)[1]
                with self.lock:
                    row = self._load()["jobs"].get(ident)
                    if not row:
                        raise DesignError("Thumbnail request not found.", 404)
                    file, item = self._verified_option(row, name)
                    # Read the same bytes we checked, so a concurrent replacement
                    # cannot be served as the recorded selection.
                    content = file.read_bytes()
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise DesignError("The thumbnail changed while it was opened.", 409)
                if query.get("phone") == ["1"] and query.get("download") != ["1"]:
                    small = small_image(file, item["sha256"])     # keyed by the verified bytes: a changed file gets a new preview
                    if small:
                        send_preview(handler, small, method)
                        return True
                handler.send_response(200)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(content)))
                handler.send_header("Cache-Control", "private, no-store")
                handler.send_header("X-Content-Type-Options", "nosniff")
                handler.send_header("ETag", '"' + item["sha256"] + '"')
                if query.get("download") == ["1"]:
                    handler.send_header("Content-Disposition", 'attachment; filename="' + name + '"')
                handler.end_headers()
                if method != "HEAD":
                    handler.wfile.write(content)
                return True
            elif method in ("GET", "HEAD") and re.fullmatch(BASE + "/templates/" + ID + "/image", path):
                row = self._load()["templates"].get(path.split("/")[-2])
                if not row:
                    raise DesignError("Template not found.", 404)
                file = inside(self.base / "templates", row["path"])
                if digest(file) != row["sha256"]:
                    raise DesignError("Template changed; upload a new version.", 409)
                small = small_image(file, row["sha256"]) if query.get("phone") == ["1"] else None
                if small:
                    send_preview(handler, small, method)
                    return True
                handler.send_static(str(file))
                return True
            else:
                raise DesignError("Thumbnail route not found.", 404)
            handler.send_json(result, 202 if path.endswith(("/approve-video", "/create-post")) else 200)
        except DesignError as error:
            handler.send_json({"error": str(error)}, error.status)
        except (OSError, ValueError, TypeError, KeyError) as error:
            handler.send_json({"error": "Thumbnail request could not finish; saved versions were preserved. " + str(error)[:200]}, 400)
        return True
