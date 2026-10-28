"""One video, one package: the steps it needs and what the owner picked at each.

The owner picks the package before the edit (or later on the video's card):
  video    the edit only
  caption  the edit, then one of three title + caption + hashtag sets
  full     the edit, a caption set, then Codex thumbnails made from that set's title
The video is READY when every step of its package is done. Its choices live in out/<name>/package.json
(an agent may leave the package word in package.txt before the owner has touched it).
"""
import json
import os
import re
import shutil
import threading
import time

import publish
from sermon_design import DesignError

PRESETS = {"video": ["video"], "caption": ["video", "caption"], "full": ["video", "caption", "thumbnail"]}
NAMES = {"video": "Video only", "caption": "Video + caption", "full": "Full set"}
COVER = "cover-codex.png"                                       # the picked Codex thumbnail, copied next to the video
SHOWN = 3                                                       # thumbnails on the pick screen (the Codex engine always makes 4)
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")


class Packages:
    def __init__(self, root, thumbs, task_action, approve_folder, load_tasks, start_job):
        self.root, self.thumbs, self.task_action, self.approve_folder = root, thumbs, task_action, approve_folder
        self.load_tasks, self.start_job, self.lock = load_tasks, start_job, threading.RLock()

    def _dir(self, name):
        d = os.path.join(self.root, "out", name) if isinstance(name, str) and SAFE.match(name) and not name.startswith(("thumbnail-final-", "sermon-studio-")) else None
        if not d or not os.path.isdir(d):
            raise DesignError("This video is no longer waiting in out/.", 404)
        return d

    def read(self, name):
        d = os.path.join(self.root, "out", name)
        try:
            with open(os.path.join(d, "package.json"), encoding="utf-8") as f:
                pkg = json.load(f)
            if isinstance(pkg, dict) and pkg.get("preset") in PRESETS:
                return pkg
        except (OSError, ValueError):
            pass
        try:                                                    # the package the owner chose at Edit, written by the editor
            with open(os.path.join(d, "package.txt"), encoding="utf-8") as f:
                word = f.read(40).strip().lower()
            if word in PRESETS:
                return {"preset": word}
        except OSError:
            pass
        return {"preset": "full"}

    def _write(self, name, pkg):
        d = self._dir(name)
        tmp = os.path.join(d, ".package.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pkg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(d, "package.json"))

    def _job(self, name, pkg):
        """The thumbnail request of this video: one newer than the package's pick (a remake from a new title), else the
        package's pick, else the newest request for its folder; a failed try never hides thumbnails that came back."""
        jobs = self.thumbs._load()["jobs"]
        when = lambda j: j.get("approvedAt") or j.get("createdAt") or 0
        mine = sorted((j for j in jobs.values() if j.get("folder") == "out/" + name), key=when, reverse=True)
        picked = jobs.get(pkg.get("thumbJob"))
        live = [j for j in mine if j.get("status") != "failed"]
        if picked and not (live and when(live[0]) > when(picked)):
            return picked
        return (live or mine or [None])[0]

    def state(self, name):
        """What the board and the pick screen show for out/<name>."""
        with self.thumbs.lock:
            pkg = self.read(name)
            stages = PRESETS[pkg["preset"]]
            d = os.path.join(self.root, "out", name)
            captions = []
            if os.path.isfile(os.path.join(d, "post.md")):
                captions = [{"title": o.get("title") or "", "caption": o.get("caption") or ""} for o in publish.drafts(d)["options"] if (o.get("caption") or "").strip()]
            row = self._job(name, pkg)
            job = self.thumbs._public_job(row) if row else None
            thumb = {k: job.get(k) for k in ("id", "status", "progress", "title", "error", "selectedOption", "options", "optionsError")} if job else None
            if thumb and thumb["options"]:                      # Codex makes 4; the owner picks from 3, keeping an earlier pick in view
                opts = thumb["options"]
                shown = opts[:SHOWN]
                chosen = next((o for o in opts if o.get("name") == thumb["selectedOption"]), None)
                thumb["options"] = shown if not chosen or chosen in shown else shown[:-1] + [chosen]
            pick = pkg.get("caption")
            done = {"video": bool(pkg.get("videoOkAt") or (row and row.get("mode", "video") == "video")),   # Codex only starts on an approved video
                    "caption": isinstance(pick, int) and 0 <= pick < len(captions),
                    "thumbnail": bool(thumb and thumb["selectedOption"] and os.path.isfile(os.path.join(d, COVER)))}
            return {"preset": pkg["preset"], "name": NAMES[pkg["preset"]], "stages": stages, "done": done, "captions": captions,
                    "caption": pick if done["caption"] else None, "thumb": thumb, "cover": COVER if done["thumbnail"] else None,
                    "ready": all(done[s] for s in stages)}

    def ready(self, name):
        try:
            return self.state(name)["ready"]
        except (DesignError, OSError, ValueError, KeyError):
            return False

    def _review_task(self, name):
        marker = "out:" + name
        return next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split() and t.get("status") == "review"), None)

    def _start_thumbs(self, name, title):
        ctx = self.thumbs.context("out/" + name)
        rank = lambda v: (0 if re.match(r"(edit|final|reel)\b", v["name"], re.I) else 2 if re.search(r"clean|nocap", v["name"], re.I) else 1, v["path"])
        videos = sorted(ctx["videos"], key=rank)
        if not videos:
            raise DesignError("This folder has no video to make thumbnails for.", 409)
        return self.thumbs.approve_video({"approval": True, "folder": "out/" + name, "taskId": ctx["taskId"], "title": title,
                                          "videoPath": videos[0]["path"], "videoSha256": videos[0]["sha256"]})

    def action(self, body):
        name, act = body.get("name"), body.get("action")
        self._dir(name)
        with self.thumbs.lock:
            pkg = self.read(name)
            if act == "preset":
                if body.get("preset") not in PRESETS:
                    raise DesignError("Choose Video only, Video + caption or Full set.", 400)
                pkg["preset"] = body["preset"]
            elif act == "video-ok":
                pkg["videoOkAt"] = pkg.get("videoOkAt") or time.time()
            elif act == "write-captions":                       # Social writes the three title + caption + hashtag sets
                self.start_job(f"Posting pass for out/{name}: write out/{name}/post.md following the relay skill, with exactly 3 options under ## Captions, "
                               f"each \"### Option N\" with a \"Title:\" line, the caption and its hashtags. The owner picks one in the app; nothing is posted.")
                return self.state(name)
            elif act == "caption":
                st = self.state(name)
                i = body.get("option")
                if not st["done"]["video"]:
                    raise DesignError("Approve the video first.", 409)
                if not isinstance(i, int) or not 0 <= i < len(st["captions"]):
                    raise DesignError("Choose one of the caption sets.", 400)
                pkg["caption"] = i
                self._write(name, pkg)
                # Full set: the thumbnails follow this title. Codex starts by itself the first time; a video that already
                # has thumbnails keeps them until the owner asks for new ones from this title.
                if "thumbnail" in PRESETS[pkg["preset"]] and not st["thumb"]:
                    self._start_thumbs(name, st["captions"][i]["title"])
                return self.state(name)
            elif act == "thumbs":                               # new thumbnails from the picked title
                st = self.state(name)
                if st["caption"] is None:
                    raise DesignError("Pick a title and caption first.", 409)
                self._start_thumbs(name, st["captions"][st["caption"]]["title"])
                return self.state(name)
            elif act == "thumb":
                row = self._job(name, pkg)
                if not row:
                    raise DesignError("No thumbnails yet for this video.", 409)
                self.thumbs.select_option({"jobId": row["id"], "optionName": body.get("option"), "expectedHash": body.get("sha256")})
                file, _ = self.thumbs._verified_option(row, body.get("option"))
                shutil.copyfile(file, os.path.join(self._dir(name), COVER))
                pkg["thumbJob"] = row["id"]
            elif act == "final":
                return self.final(name)
            else:
                raise DesignError("Unknown package step.", 400)
            self._write(name, pkg)
            return self.state(name)

    def final(self, name):
        """READY → approved/: the Codex package first (so the source check still sees the video in out/), then the video."""
        st = self.state(name)
        if not st["ready"]:
            raise DesignError("Finish every step of this video's package first.", 409)
        if st["thumb"] and "thumbnail" in st["stages"]:
            marker = "out:thumbnail-final-" + st["thumb"]["id"]
            final = next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split() and t.get("status") == "review"), None)
            if final:
                code, res = self.task_action({"action": "approve", "id": final["id"]})
                if code >= 400:
                    raise DesignError(res.get("error") or "The thumbnail package could not be approved.", code)
        task = self._review_task(name)
        code, res = self.task_action({"action": "approve", "id": task["id"]}) if task else self.approve_folder(name)
        if code >= 400 and not os.path.isdir(os.path.join(self.root, "approved", name)):
            raise DesignError(res.get("error") or "The video could not be approved.", code)
        return {**st, "approved": "approved/" + name}
