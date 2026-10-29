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
# two thumbnails per video, always: 9:16 goes on YouTube and Facebook, 3:4 on Instagram (owner, 2026-10-28)
SIZES = {"main": {"size": [1080, 1920], "cover": COVER, "job": "thumbJob", "label": "9:16 · YouTube + Facebook"},
         "ig": {"size": [1080, 1440], "cover": "cover-codex-ig.png", "job": "thumbJobIg", "label": "3:4 · Instagram"}}
SHOWN = 3                                                       # thumbnails on the pick screen (the Codex engine always makes 4)
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")


class Packages:
    def __init__(self, root, thumbs, task_action, approve_folder, load_tasks, start_job, job_progress=None):
        self.root, self.thumbs, self.task_action, self.approve_folder = root, thumbs, task_action, approve_folder
        self.load_tasks, self.start_job, self.lock = load_tasks, start_job, threading.RLock()
        self.job_progress = job_progress or (lambda prefix: None)   # a running lead job's estimated %, None when none runs
        self.job_running = lambda prefix: self.job_progress(prefix) is not None

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

    def _job(self, name, pkg, slot="main"):
        """This video's thumbnail request in one size: one newer than the package's pick (a remake from a new title),
        else the package's pick, else the newest request; a failed try never hides thumbnails that came back."""
        data = self.thumbs._load()
        jobs, templates = data["jobs"], data["templates"]
        when = lambda j: j.get("approvedAt") or j.get("createdAt") or 0
        size = lambda j: [j.get("width"), j.get("height")] if j.get("width") else [(templates.get(j.get("templateId")) or {}).get(k) for k in ("width", "height")]
        mine = sorted((j for j in jobs.values() if j.get("folder") == "out/" + name and size(j) == SIZES[slot]["size"]), key=when, reverse=True)
        picked = jobs.get(pkg.get(SIZES[slot]["job"]) or (pkg.get("thumbJob") if slot == "ig" else None))   # older videos: their one pick was 3:4
        if picked and size(picked) != SIZES[slot]["size"]:
            picked = None
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
            channel, templates = self._templates(name)
            thumbs, rows = {}, {}
            for slot in SIZES:
                rows[slot] = self._job(name, pkg, slot)
                thumbs[slot] = self._thumb(d, rows[slot], templates, slot)
            row, thumb = rows["main"] or rows["ig"], thumbs["main"]
            pick = pkg.get("caption")
            picked = isinstance(pick, int) and 0 <= pick < len(captions)
            # the caption counts once the owner confirms it (older videos: thumbnails already made from this very title)
            confirmed = picked and bool(pkg.get("captionOkAt") or (row and row.get("title") == captions[pick]["title"]))
            # the style: only this video's own pick, never the channel default or an earlier request's template
            style = pkg.get("templateId")
            if style not in {t["id"] for t in templates}:
                style = None
            both = all(thumbs[slot] and thumbs[slot]["picked"] for slot in SIZES)
            done = {"video": bool(pkg.get("videoOkAt") or (row and row.get("mode", "video") == "video")),   # Codex only starts on an approved video
                    "caption": confirmed,
                    "thumbnail": both}
            return {"preset": pkg["preset"], "name": NAMES[pkg["preset"]], "stages": stages, "done": done, "captions": captions,
                    "caption": pick if picked else None, "captionOk": confirmed, "thumb": thumb, "thumbs": thumbs,
                    "sizes": {k: v["label"] for k, v in SIZES.items()},
                    "cover": COVER if both else None, "coverIg": SIZES["ig"]["cover"] if both else None,
                    "channel": channel, "templates": templates, "style": style, "ready": all(done[s] for s in stages),
                    "captionsBusy": self.job_running(self._captions_job(name)), "captionsProgress": self.job_progress(self._captions_job(name))}

    def _thumb(self, d, row, templates, slot):
        """One size's thumbnails for the card: status, progress, the 3 options shown, and whether the owner picked one."""
        if not row:
            return None
        job = self.thumbs._public_job(row)
        t = {k: job.get(k) for k in ("id", "status", "progress", "title", "instructions", "error", "selectedOption", "options", "optionsError")}
        if t["options"]:                                    # Codex makes 4; the owner picks from 3, keeping an earlier pick in view
            opts = t["options"]
            shown = opts[:SHOWN]
            chosen = next((o for o in opts if o.get("name") == t["selectedOption"]), None)
            t["options"] = shown if not chosen or chosen in shown else shown[:-1] + [chosen]
        t["reference"] = row.get("referenceName") or ""     # the owner's reference picture the thumbnails follow
        t["style"] = next((x["name"] for x in templates if x["id"] == row.get("templateId")), "")
        cover = os.path.join(d, SIZES[slot]["cover"])
        if slot == "ig" and t["selectedOption"] and not os.path.isfile(cover):
            try:                                            # an older video's one pick was 3:4: it becomes the Instagram cover
                file, _ = self.thumbs._verified_option(row, t["selectedOption"])
                shutil.copyfile(file, cover)
            except Exception:
                pass
        t["picked"] = bool(t["selectedOption"] and os.path.isfile(cover))
        return t

    @staticmethod
    def _captions_job(name):
        return f"Posting pass for out/{name}:"

    def _templates(self, name):
        """This video's channel and that channel's saved thumbnail styles (newest first)."""
        try:
            channel = self.thumbs._source("out/" + name, list_videos=False)[2]
        except (DesignError, OSError):
            return None, []
        rows = [t for t in self.thumbs._load()["templates"].values() if t["channel"] == channel]
        rows.sort(key=lambda t: t.get("createdAt") or 0, reverse=True)
        return channel, [{k: t[k] for k in ("id", "name", "width", "height")} | {"url": self.thumbs._public_template(t)["previewUrl"]} for t in rows]

    def ready(self, name):
        try:
            return self.state(name)["ready"]
        except (DesignError, OSError, ValueError, KeyError):
            return False

    def _review_task(self, name):
        marker = "out:" + name
        return next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split() and t.get("status") == "review"), None)

    def _start_thumbs(self, name, title, reference=None, feeling="", template_id=None, slot="main"):
        """Ask Codex for thumbnails from this title; reference: the owner's picture {name, dataUrl} to follow, if any;
        feeling: the mood and elements the owner wants, sent as the video's art direction."""
        ctx = self.thumbs.context("out/" + name)
        rank = lambda v: (0 if re.match(r"(edit|final|reel)\b", v["name"], re.I) else 2 if re.search(r"clean|nocap", v["name"], re.I) else 1, v["path"])
        videos = sorted(ctx["videos"], key=rank)
        if not videos:
            raise DesignError("This folder has no video to make thumbnails for.", 409)
        body = {"approval": True, "folder": "out/" + name, "taskId": ctx["taskId"], "title": title,
                "videoPath": videos[0]["path"], "videoSha256": videos[0]["sha256"],
                "retry": True,                                  # Try again after a failure: a new request, not the failed one back
                "width": SIZES[slot]["size"][0], "height": SIZES[slot]["size"][1]}
        if template_id:
            body["templateId"] = template_id                    # this video's own style, never the channel default by itself
        if reference:
            body["sourceImage"] = reference
        if feeling:
            body["instructions"] = "The owner wants this feeling and these elements: " + feeling
        return self.thumbs.approve_video(body)

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
                if self.job_running(self._captions_job(name)):
                    return self.state(name)                      # already writing: a second click starts nothing
                note = body.get("note") or ""
                if not isinstance(note, str) or len(note) > 800:
                    raise DesignError("Keep your comment under 800 characters.", 400)
                note = " ".join(note.split())
                again = os.path.isfile(os.path.join(self._dir(name), "post.md"))
                self.start_job(f"Posting pass for out/{name}: write out/{name}/post.md following the relay skill, with exactly 3 options under ## Captions, "
                               f"each \"### Option N\" with a \"Title:\" line, the caption and its hashtags. The owner picks one in the app; nothing is posted."
                               + (" These replace the current options: first copy the current post.md into work/social/" + name + "-captions/ (one dated file, a README line) so nothing is lost." if again else "")
                               + (f" The owner's comment on the captions (follow it): {note}" if note else ""))
                pkg.pop("caption", None)                         # new sets: the owner picks and confirms again
                pkg.pop("captionOkAt", None)
                self._write(name, pkg)
                return self.state(name)
            elif act == "caption":
                st = self.state(name)
                i = body.get("option")
                if not st["done"]["video"]:
                    raise DesignError("Approve the video first.", 409)
                if not isinstance(i, int) or not 0 <= i < len(st["captions"]):
                    raise DesignError("Choose one of the caption sets.", 400)
                if pkg.get("caption") != i:
                    pkg.pop("captionOkAt", None)            # a different pick needs confirming again
                pkg["caption"] = i
            elif act == "caption-ok":                           # the owner confirms the pick: the thumbnail step opens
                st = self.state(name)
                if st["caption"] is None:
                    raise DesignError("Pick a title and caption first.", 409)
                pkg["captionOkAt"] = time.time()
            elif act == "style":                                # the thumbnail style for this video only
                tid = body.get("templateId")
                if tid not in {t["id"] for t in self._templates(name)[1]}:
                    raise DesignError("Choose one of this channel's thumbnail styles.", 400)
                pkg["templateId"] = tid
            elif act == "thumbs":                               # Generate: thumbnails from the confirmed title, following the owner's reference picture if given
                st = self.state(name)
                if not st["captionOk"]:
                    raise DesignError("Confirm a title and caption first.", 409)
                if not st["style"]:
                    raise DesignError("Pick a thumbnail style for this video first.", 409)
                ref = body.get("reference")
                if ref is not None and not (isinstance(ref, dict) and isinstance(ref.get("dataUrl"), str)):
                    raise DesignError("Choose a PNG, JPG or WebP reference picture.", 400)
                feeling = body.get("feeling") or ""
                if not isinstance(feeling, str) or len(feeling) > 600:
                    raise DesignError("Keep the feeling under 600 characters.", 400)
                slots = [body["size"]] if body.get("size") in SIZES else list(SIZES)   # Generate makes both; Try again only the size that failed
                for slot in slots:
                    t = st["thumbs"].get(slot)
                    if t and t["status"] in ("watching", "dispatching"):
                        continue                                 # that size is already being made
                    self._start_thumbs(name, st["captions"][st["caption"]]["title"], ref, " ".join(feeling.split()), st["style"], slot)
                return self.state(name)
            elif act == "thumb":
                slot = body.get("size") if body.get("size") in SIZES else "main"
                row = self._job(name, pkg, slot)
                if not row:
                    raise DesignError("No thumbnails yet in this size.", 409)
                self.thumbs.select_option({"jobId": row["id"], "optionName": body.get("option"), "expectedHash": body.get("sha256")})
                file, _ = self.thumbs._verified_option(row, body.get("option"))
                shutil.copyfile(file, os.path.join(self._dir(name), SIZES[slot]["cover"]))
                pkg[SIZES[slot]["job"]] = row["id"]
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
        for t in (st["thumbs"].values() if "thumbnail" in st["stages"] else []):
            if not t:
                continue
            marker = "out:thumbnail-final-" + t["id"]
            final = next((x for x in self.load_tasks().get("tasks", []) if marker in (x.get("note") or "").split() and x.get("status") == "review"), None)
            if final:
                code, res = self.task_action({"action": "approve", "id": final["id"]})
                if code >= 400:
                    raise DesignError(res.get("error") or "The thumbnail package could not be approved.", code)
        task = self._review_task(name)
        code, res = self.task_action({"action": "approve", "id": task["id"]}) if task else self.approve_folder(name)
        if code >= 400 and not os.path.isdir(os.path.join(self.root, "approved", name)):
            raise DesignError(res.get("error") or "The video could not be approved.", code)
        self._close_unpicked(name, st)
        return {**st, "approved": "approved/" + name}

    def _close_unpicked(self, name, st):
        """The thumbnail sets this video didn't use leave the board (cancelled, so they can still be restored)."""
        used = {t["id"] for t in st["thumbs"].values() if t}
        jobs = self.thumbs._load()["jobs"]
        for t in self.load_tasks().get("tasks", []):
            m = re.search(r"out:thumbnail-final-([0-9a-f]{32})", t.get("note") or "")
            if t.get("status") == "review" and m and m[1] not in used and (jobs.get(m[1]) or {}).get("folder") == "out/" + name:
                self.task_action({"action": "move", "id": t["id"], "status": "cancelled"})
        unused = [f"thumbnail-final-{j}" for j, row in jobs.items() if row.get("folder") == "out/" + name and j not in used
                  and os.path.isdir(os.path.join(self.root, "out", f"thumbnail-final-{j}"))]
        if unused:                                          # their folders leave the board too (Deleted tab, files kept)
            self.task_action({"action": "folder-hide", "folders": unused})
