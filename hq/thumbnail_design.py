"""Brand-scoped, versioned thumbnail handoff. No generation starts on import/read.

An intentional video approval freezes source bytes and a channel template. Only
that request is dispatched to the signed-in Codex engine; delivery is a second
native review task. The original video is never moved at this intermediate step.
"""
import base64
import hashlib
import json
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
        raise DesignError("Enter " + label + " before approving the video.", 400)
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
        if not isinstance(key, str) or not self.channels.get(key):
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
            return {"channels": channels, "dimensions": DIMENSIONS, "schemaVersion": 1}

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
            key, known = channel_file.read_text(encoding="utf-8").strip(), True
        match = re.search(r"(?:^|\s)channel:([^\s]+)", (task or {}).get("note", ""))
        if match:
            if known and key != match[1]:
                raise DesignError("The video and task channel records disagree.", 409)
            key, known = match[1], True
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
        with self.lock:
            data = self._load()
            template_id = data["defaults"].get(key)
            jobs = [self._public_job(j) for j in data["jobs"].values() if j["folder"] == folder]
            return {"folder": folder, "taskId": task.get("id") if task else None, "channel": key, "channelKnown": known, "channelName": self.channels.name(key), "videos": videos, "templates": [self._public_template(t) for t in data["templates"].values() if t["channel"] == key], "defaultTemplateId": template_id, "enabled": bool(template_id or jobs), "eligible": bool(videos), "jobs": jobs}

    def _public_job(self, row):
        return {key: row[key] for key in ("id", "status", "progress", "folder", "taskId", "channel", "title", "subtitle", "instructions", "templateId", "templateRevision", "videoPath", "videoSha256", "sourceFrameAvailable", "warnings", "approvedAt", "deadlineAt", "error", "delivery") if key in row}

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
        try:
            result = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-ss", "0", "-i", str(video), "-frames:v", "1", "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease", "-y", str(destination)], stdin=subprocess.DEVNULL, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0 or not destination.is_file() or not 0 < destination.stat().st_size < 8 * 1024 * 1024:
                return None
            return {"name": "approved-video-frame.jpg", "dataUrl": "data:image/jpeg;base64," + base64.b64encode(destination.read_bytes()).decode()}
        except (OSError, subprocess.TimeoutExpired):
            return None

    def approve_video(self, body):
        if body.get("approval") is not True:
            raise DesignError("Use Approve video & create thumbnails to approve this exact video version.", 400)
        title = text(body.get("title", ""), 200, "the exact thumbnail title", True)
        subtitle = text(body.get("subtitle", ""), 200, "subtitle")
        direction = text(body.get("instructions", ""), 2000, "video art direction")
        base, task, inferred, known, videos = self._source(body.get("folder"), body.get("taskId"))
        channel = self._channel(body.get("channel", inferred))
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
            signature = hashlib.sha256(json.dumps({"folder": body["folder"], "taskId": task.get("id") if task else None, "video": video, "templateId": template["id"], "title": title, "subtitle": subtitle, "direction": direction, "channel": channel}, sort_keys=True).encode()).hexdigest()
            prior = next((j for j in data["jobs"].values() if j.get("signature") == signature), None)
            if prior and not (body.get("retry") is True and prior["status"] == "failed"):
                return {"job": self._public_job(prior)}
            if any(j["folder"] == body["folder"] and j["status"] in ("dispatching", "watching", "delivery-error", "uncertain") for j in data["jobs"].values()):
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
            row = {"id": ident, "status": "dispatching", "progress": 0, "signature": signature, "folder": body["folder"], "taskId": task.get("id") if task else None, "channel": channel, "title": title, "templateId": template["id"], "templateRevision": template["revision"], "templateSha256": template["sha256"], "videoPath": video["path"], "videoSha256": video["sha256"], "videoSize": video["size"], "approvedAt": time.time(), "deadlineAt": time.time() + self.watch_seconds}
            row.update(subtitle=subtitle, instructions=direction)
            payload = {"requestId": ident, "title": title, "subtitle": subtitle, "width": template["width"], "height": template["height"], "instructions": template["instructions"] + ("\nVideo-specific direction: " + direction if direction else ""), "template": {"name": template["name"], "dataUrl": "data:" + template["mimeType"] + ";base64," + base64.b64encode(frozen_template.read_bytes()).decode()}, "provenance": {k: row[k] for k in ("folder", "taskId", "channel", "templateId", "templateRevision", "templateSha256", "videoPath", "videoSha256", "approvedAt")}}
            if len(payload["instructions"]) > 3000:
                raise DesignError("Keep combined template and video direction under 3000 characters.", 400)
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
            code, result = self.task_action({"action": "add", "title": "Final · " + row["title"], "team": "Creative", "agent": "thumbnail-designer", "status": "review", "kind": "approval", "note": marker + " thumbnail-request:" + row["id"] + (" source-task:" + row["taskId"] if row.get("taskId") else ""), "subtitle": "Approved video + 4 Codex thumbnail options · final OK required"})
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
            newer = any(j["folder"] == row["folder"] and j["videoPath"] == row["videoPath"] and j["approvedAt"] > row["approvedAt"] for j in jobs.values())
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
            query = parse_qs(url.query)
            if method == "GET" and path == BASE + "/config":
                result = self.config()
            elif method == "GET" and path == BASE + "/context":
                result = self.context(query.get("folder", [""])[0], query.get("taskId", [None])[0])
            elif method == "POST" and path == BASE + "/templates":
                result = self.save_template(body)
            elif method == "POST" and path == BASE + "/default":
                result = self.set_default(body)
            elif method == "POST" and path == BASE + "/approve-video":
                result = self.approve_video(body)
            elif method == "GET" and re.fullmatch(BASE + "/jobs/" + ID, path):
                result = self.poll(path.rsplit("/", 1)[1])
            elif method in ("GET", "HEAD") and re.fullmatch(BASE + "/templates/" + ID + "/image", path):
                row = self._load()["templates"].get(path.split("/")[-2])
                if not row:
                    raise DesignError("Template not found.", 404)
                file = inside(self.base / "templates", row["path"])
                if digest(file) != row["sha256"]:
                    raise DesignError("Template changed; upload a new version.", 409)
                handler.send_static(str(file))
                return True
            else:
                raise DesignError("Thumbnail route not found.", 404)
            handler.send_json(result, 202 if path.endswith("/approve-video") else 200)
        except DesignError as error:
            handler.send_json({"error": str(error)}, error.status)
        except (OSError, ValueError, TypeError, KeyError) as error:
            handler.send_json({"error": "Thumbnail request could not finish; saved versions were preserved. " + str(error)[:200]}, 400)
        return True
