"""Authenticated, bounded bridge to the local Codex Sermon Design renderer.

This module never invokes Claude or starts a production model task. Its only
upstream is the fixed loopback renderer, and verified deliveries join this HQ's
existing out/ review workflow. Importing it has no filesystem/process effects.
"""
import hashlib
import http.client
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

ENGINE_ROOT = Path(r"D:\AI OFFICE")
ENGINE_HOST, ENGINE_PORT = "127.0.0.1", 4341
ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
STATIC = {"/sermon-studio.html", "/sermon-studio.css", "/sermon-studio.js"}
# "Back to HQ" in the studio page pointed at another address (the older office). This Agents HQ serves the page, so its
# way back is this same HQ: the office at "/", or the review task the studio was opened from (?task=<id>), same tab.
# The code rides along at the end of the studio's own sermon-studio.js (a strict page may block any other script), and
# once more inline in the page for a page that loads no script; it also adds a small "Agents HQ" button that always works.
BACK_TO_HQ_JS = b"""
;(function () {
  if (window.__hqBack) return; window.__hqBack = true;
  var top = window.top || window;
  function home() { var t = new URLSearchParams(location.search).get("task"); return "/" + (t ? "?task=" + encodeURIComponent(t) : ""); }
  function wouldBlock() {                                  // ask the studio's own "don't leave" handlers (held by HOLD_UNLOAD_JS)
    var stop = false, probe = { preventDefault: function () { stop = true; }, set returnValue(v) { stop = true; }, get returnValue() { return ""; } };
    (window.__hqUnload || []).forEach(function (fn) { try { fn.call(window, probe); } catch (e) { /* a broken handler does not hold the page */ } });
    return stop;
  }
  function go() {
    if (window.SermonStudio && typeof window.SermonStudio.navigateHome === "function") { window.SermonStudio.navigateHome(); return; }
    if (wouldBlock() && !window.confirm(__LEAVE_MSG__)) return;
    window.__hqLeaving = true;
    try { top.location.assign(home()); } catch (e) { location.assign(home()); }
  }
  function isBack(el) { var t = (el && el.textContent || "").replace(/\\s+/g, " ").trim(); return t.length < 40 && /^back to (?:claude |agents? |the )?hq\\b/i.test(t); }
  function backOf(node) { for (var el = node, i = 0; el && el.nodeType === 1 && i < 6; el = el.parentElement, i++) if (isBack(el)) return el; return null; }
  function fix() { document.querySelectorAll("a").forEach(function (a) { if (isBack(a)) { a.href = home(); a.removeAttribute("target"); } }); }
  ["pointerdown", "mousedown", "touchstart", "click", "auxclick"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      if (!backOf(e.target)) return;
      e.preventDefault(); e.stopImmediatePropagation();
      if (type === "click" || type === "auxclick") go();
    }, { capture: true, passive: false });
  });
  window.addEventListener("keydown", function (e) { if ((e.key === "Enter" || e.key === " ") && backOf(e.target)) { e.preventDefault(); e.stopImmediatePropagation(); go(); } }, true);
  function pill() {
    if (window !== top || document.getElementById("hq-home-pill") || !document.body) return;
    var b = document.createElement("a"); b.id = "hq-home-pill"; b.href = home(); b.textContent = "\\u2190 Agents HQ";
    b.setAttribute("style", "position:fixed;left:14px;bottom:14px;z-index:2147483647;padding:8px 14px;border-radius:999px;background:#f5b82e;color:#1a1300;font:700 13px system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 18px rgba(0,0,0,.45)");
    b.addEventListener("click", function (e) { e.preventDefault(); go(); });
    document.body.appendChild(b);
  }
  function ready() { fix(); pill(); new MutationObserver(fix).observe(document.documentElement, { childList: true, subtree: true }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready); else ready();
})();
"""
# While a design is generating (or has unsaved edits) the studio holds the page with a "beforeunload" handler. A browser
# then asks "Leave site?", but the desktop app (Electron) asks nothing and just stays, so Back to HQ looked dead until the
# job ended. An accepted job keeps running and comes back to HQ through the delivery watcher, so leaving is safe once
# asked. This runs before the studio's code and keeps its beforeunload handlers: Back to HQ asks in words, then leaves.
HOLD_UNLOAD_JS = b"""
;(function () {
  if (window.__hqUnload) return;
  var held = window.__hqUnload = [], add = window.addEventListener;
  window.addEventListener = function (type, fn, options) {
    if (type === "beforeunload" && typeof fn === "function") {
      var own = fn; held.push(own);
      fn = function (e) { if (!window.__hqLeaving) return own.call(this, e); };
    }
    return add.call(this, type, fn, options);
  };
})();
"""
LEAVE_MSG = ("这个设计正在生成，或有未保存的修改。\n已经开始的生成会继续，完成后回到 Agents HQ 等你审核；这个页面上未保存的修改会丢失。\n\n"
             "A design is generating or has unsaved changes. Generation that has started keeps running and comes back to "
             "Agents HQ for your OK; unsaved changes on this page will be lost.\n\n现在回到 Agents HQ？ / Go back to Agents HQ now?")
BACK_TO_HQ_JS = BACK_TO_HQ_JS.replace(b"__LEAVE_MSG__", json.dumps(LEAVE_MSG).encode())
BACK_TO_HQ = b"<script>" + BACK_TO_HQ_JS + b"</script>"
BASE = "/api/sermon-design"


class DesignError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def allowed(method, path):
    if method in ("GET", "HEAD"):
        return path in STATIC or path in (BASE + "/capabilities", BASE + "/projects", BASE + "/download") or bool(
            re.fullmatch(BASE + r"/jobs/" + ID, path) or
            re.fullmatch(BASE + r"/projects/" + ID + r"(?:/assets/" + ID + r"|/designs/" + ID + r"/preview)?", path))
    if method == "POST":
        return path in (BASE + "/projects", BASE + "/assets") or bool(re.fullmatch(
            BASE + r"/projects/" + ID + r"(?:/(?:generate|preview|export|restore|recap|trash|untrash))?", path))
    return method == "PUT" and bool(re.fullmatch(BASE + r"/projects/" + ID, path))


def inside(root, candidate):
    root, original = Path(root).resolve(), Path(candidate).absolute()
    cursor = original
    while cursor != cursor.parent:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise DesignError("Linked design files are not served.", 403)
        if cursor == root:
            break
        cursor = cursor.parent
    candidate = original.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise DesignError("The design file is outside its verified delivery folder.", 403)
    return candidate


class SermonDesignBridge:
    def __init__(self, hq_root, task_action, load_tasks, notify=None, engine_root=ENGINE_ROOT, runtime_root=None, request=None, auto_start=True, delivery_poll_seconds=2, delivery_watch_seconds=1800):
        self.hq_root, self.engine_root = Path(hq_root).resolve(), Path(engine_root).resolve()
        self.runtime_root = Path(runtime_root).resolve() if runtime_root else self.engine_root / ".studio" / "sermon-design-runtime"
        self.task_action, self.load_tasks, self.notify = task_action, load_tasks, notify
        self.index_path = self.hq_root / "hq" / "sermon-project-links.json"
        self.pending_path = self.hq_root / "hq" / "sermon-pending-deliveries.json"
        self.lock, self.engine_lock = threading.Lock(), threading.Lock()
        self.watch_lock, self.watch_stop, self.watcher = threading.Lock(), threading.Event(), None
        self.delivery_poll_seconds, self.delivery_watch_seconds = max(.01, delivery_poll_seconds), min(1800, max(1, delivery_watch_seconds))
        self.request_impl, self.auto_start = request, auto_start
        self.engine_ready_at = 0

    def _request(self, method, route, data=None, headers=None):
        if self.request_impl:
            return self.request_impl(method, route, data, headers or {})
        endpoint = route.split("?", 1)[0]
        watch = route.startswith(BASE + "/jobs/") and method == "GET"
        metadata = method == "GET" and bool(re.fullmatch(BASE + r"/projects/" + ID + r"(?:\?revision=\d+)?", route))
        timeout = 20 if endpoint == BASE + "/capabilities" else 3 if endpoint == "/api/runtime" else 5 if watch or metadata else 300
        conn = http.client.HTTPConnection(ENGINE_HOST, ENGINE_PORT, timeout=timeout)
        try:
            conn.request(method, route, body=data, headers=headers or {})
            response = conn.getresponse()
            # Metadata is bounded separately from supported source-image assets.
            limit = (32 if "application/json" in response.getheader("Content-Type", "") else 56) * 1024 * 1024
            body = response.read(limit + 1)
            if len(body) > limit:
                raise DesignError("The renderer response exceeds the studio size limit.", 502)
            return response.status, dict(response.getheaders()), body
        finally:
            conn.close()

    def _probe(self):
        code, _, body = self._request("GET", "/api/runtime")
        runtime = {}
        try:
            runtime = json.loads(body)
            if not isinstance(runtime, dict):
                raise ValueError()
            same = Path(runtime.get("workspaceRoot", "")).resolve() == self.runtime_root and Path(runtime.get("sourceRoot", "")).resolve() == self.engine_root
        except (ValueError, TypeError, OSError):
            same = False
        if code != 200 or not same or not isinstance(runtime, dict) or runtime.get("app") != "sermon-design-engine":
            raise DesignError("Port 4341 belongs to a different or unrecognized design engine. Its service was left unchanged.")
        code, _, body = self._request("GET", BASE + "/capabilities")
        try:
            capabilities = json.loads(body)
            if not isinstance(capabilities, dict) or not isinstance(capabilities.get("dimensions"), dict):
                raise ValueError()
        except ValueError:
            capabilities = {}
        providers = capabilities.get("providers", [])
        has_codex = isinstance(providers, list) and any(isinstance(item, dict) and item.get("id") == "codex" for item in providers)
        if code != 200 or capabilities.get("dimensions", {}).get("title") != [3840, 2160] or capabilities.get("defaultProvider") != "codex" or not has_codex:
            raise DesignError("The design engine needs its prepared update activated. The existing service was left unchanged.")

    def ensure_engine(self):
        if time.monotonic() - self.engine_ready_at < 10:
            return
        with self.engine_lock:
            if time.monotonic() - self.engine_ready_at < 10:
                return
            try:
                self._probe()
            except ConnectionRefusedError:
                if not self.auto_start:
                    raise DesignError("The local design renderer is not running.")
                node = shutil.which("node")
                script = self.engine_root / "studio" / "sermon-design-server.mjs"
                if not node or not script.is_file():
                    raise DesignError("The installed Node runtime or design renderer is missing. No alternative service was started.")
                log_dir = self.engine_root / ".studio" / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                log = log_dir / ("sermon-engine-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".log")
                env = dict(os.environ, PORT=str(ENGINE_PORT))
                with open(log, "ab") as output:
                    subprocess.Popen([str(Path(node).resolve()), str(script)], cwd=self.engine_root, env=env,
                                     stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                deadline = time.monotonic() + 15
                while True:
                    try:
                        self._probe()
                        break
                    except ConnectionRefusedError:
                        if time.monotonic() >= deadline:
                            raise DesignError("The local design engine did not become ready. Saved projects and HQ tasks were preserved.")
                        time.sleep(.2)
            except (OSError, http.client.HTTPException) as error:
                raise DesignError("The local design engine could not be reached. Your request was not replayed.") from error
            self.engine_ready_at = time.monotonic()

    def _index(self):
        if not self.index_path.exists():
            return {"version": 1, "deliveries": {}}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("deliveries"), dict):
                raise ValueError()
            for record in data["deliveries"].values():
                if not isinstance(record, dict) or not re.fullmatch(r"sermon-studio-" + ID + r"-r\d+-a\d+", str(record.get("folder", ""))) or not isinstance(record.get("taskId"), str) or not isinstance(record.get("files"), list) or not record["files"]:
                    raise ValueError()
                for item in record["files"]:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("name"), str) or not isinstance(item.get("size"), int) or item["size"] <= 0 or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))):
                        raise ValueError()
            return data
        except (OSError, ValueError):
            raise DesignError("The saved design delivery index needs repair. It was preserved; no duplicate task was created.", 409)

    def _save_index(self, data):
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_name(self.index_path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.index_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _pending(self):
        if not self.pending_path.exists():
            return {"version": 1, "jobs": {}}
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("jobs"), dict) or len(data["jobs"]) > 250:
                raise ValueError()
            for key, item in data["jobs"].items():
                if not re.fullmatch(ID, key) or not isinstance(item, dict) or item.get("jobId") != key or not re.fullmatch(ID, str(item.get("projectId", ""))) or item.get("status") not in ("watching", "delivered", "failed", "delivery-error", "expired") or any(not isinstance(item.get(field), (int, float)) or not math.isfinite(item[field]) for field in ("queuedAt", "deadlineAt")) or item["deadlineAt"] > item["queuedAt"] + 1800:
                    raise ValueError()
            return data
        except (OSError, ValueError, AttributeError):
            raise DesignError("The saved background delivery ledger needs repair. It was preserved; no job was rerun.", 409)

    def _save_pending(self, data):
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep a bounded history while retaining every still-authorized watch.
        rows = data["jobs"]
        finished = sorted((item for item in rows.values() if item["status"] != "watching"), key=lambda item: item.get("queuedAt", 0), reverse=True)
        keep = {item["jobId"] for item in finished[:150]}
        data["jobs"] = {key: item for key, item in rows.items() if item["status"] == "watching" or key in keep}
        temporary = self.pending_path.with_name(self.pending_path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.pending_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _start_watcher_locked(self, data):
        if self.watch_stop.is_set() or (self.watcher and self.watcher.is_alive()) or not any(item["status"] == "watching" for item in data["jobs"].values()):
            return
        self.watcher = threading.Thread(target=self._watch_deliveries, name="sermon-native-deliveries", daemon=True)
        self.watcher.start()

    def resume_pending(self):
        """Resume only saved read-only watches; never launches or retries jobs."""
        with self.watch_lock:
            data = self._pending()
            self._start_watcher_locked(data)

    def _track_job(self, job):
        if not isinstance(job, dict) or not re.fullmatch(ID, str(job.get("id", ""))) or not re.fullmatch(ID, str(job.get("projectId", ""))):
            raise DesignError("The accepted job returned no safe delivery identity. Reopen the saved project to check its result.", 502)
        with self.watch_lock:
            data = self._pending(); key = job["id"]
            if key not in data["jobs"]:
                if sum(item["status"] == "watching" for item in data["jobs"].values()) >= 64:
                    raise DesignError("Background delivery is at capacity. This accepted job was not repeated; reopen its project to collect its result.", 503)
                queued = time.time()
                data["jobs"][key] = {"jobId": key, "projectId": job["projectId"], "status": "watching", "queuedAt": queued, "deadlineAt": queued + self.delivery_watch_seconds}
                self._save_pending(data)
            self._start_watcher_locked(data)

    def _record_watch(self, job_id, status=None, **details):
        with self.watch_lock:
            data = self._pending(); item = data["jobs"].get(job_id)
            if not item or item["status"] != "watching":
                return
            item.update(details, lastCheckedAt=time.time())
            if status:
                item["status"] = status
            self._save_pending(data)

    def _watch_one(self, item):
        job_id = item["jobId"]
        if time.time() >= item["deadlineAt"]:
            self._record_watch(job_id, "expired", lastError="The 30-minute delivery watch ended. Reopen the saved project to collect an existing result; no generation was retried.")
            return
        try:
            # Read-only identity probe: this watcher deliberately never calls
            # ensure_engine(), starts a service, or repeats a generation POST.
            self._probe()
            code, _, body = self._request("GET", BASE + "/jobs/" + job_id)
            payload = json.loads(body)
            if code != 200 or not isinstance(payload, dict):
                raise DesignError("The accepted job is no longer readable. Reopen its saved project to collect any existing output.")
            job, project = payload.get("job"), payload.get("project")
            if not isinstance(job, dict) or job.get("id") != job_id or job.get("projectId") != item["projectId"]:
                raise DesignError("The background job identity does not match the accepted assignment.")
            if job.get("status") in ("failed", "cancelled", "canceled"):
                self._record_watch(job_id, "failed", lastError=str(job.get("error") or "The accepted job did not succeed; no finished task was created.")[:1000])
                return
            if job.get("status") != "succeeded":
                self._record_watch(job_id)
                return
            revision = job.get("projectRevision")
            if not isinstance(project, dict) or project.get("id") != item["projectId"] or not isinstance(revision, int):
                raise DesignError("The finished job has incomplete project provenance.")
            if project.get("revision") != revision or project.get("lastExport", {}).get("projectRevision") != revision:
                code, _, body = self._request("GET", BASE + "/projects/" + item["projectId"] + "?revision=" + str(revision))
                historical = json.loads(body)
                project = historical.get("project") if isinstance(historical, dict) else None
                if code != 200 or not isinstance(project, dict) or project.get("id") != item["projectId"] or project.get("revision") != revision or project.get("lastExport", {}).get("projectRevision") != revision:
                    raise DesignError("The exact finished project revision is unavailable. No newer revision was substituted.")
            delivery = self.register(project)
            if not delivery:
                raise DesignError("The finished job has no verified export delivery.")
            self._record_watch(job_id, "delivered", taskId=delivery["taskId"], projectRevision=revision)
        except (DesignError, OSError, http.client.HTTPException, ValueError, TypeError, AttributeError) as error:
            self._record_watch(job_id, "delivery-error", lastError=(str(error) if isinstance(error, DesignError) else "The existing result could not be collected. Reopen the saved project to retry delivery; no generation was retried.")[:1000])

    def _watch_deliveries(self):
        try:
            while not self.watch_stop.is_set():
                with self.watch_lock:
                    data = self._pending()
                    pending = [dict(item) for item in data["jobs"].values() if item["status"] == "watching"]
                    if not pending:
                        self.watcher = None
                        return
                for item in pending:
                    if self.watch_stop.is_set():
                        return
                    self._watch_one(item)
                self.watch_stop.wait(self.delivery_poll_seconds)
        except (DesignError, OSError):
            # A corrupt/unwritable ledger is preserved for repair; never turn
            # that failure into a duplicate task or a new model invocation.
            return
        finally:
            with self.watch_lock:
                if self.watcher is threading.current_thread():
                    self.watcher = None

    def stop_delivery_watcher(self):
        """Shutdown/test cleanup; accepted project and pending IDs stay saved."""
        self.watch_stop.set()
        watcher = self.watcher
        if watcher and watcher is not threading.current_thread():
            watcher.join(timeout=6)

    def _verified_file(self, project, item):
        native_id = project.get("hqTaskId")
        export = project.get("lastExport", {})
        if not re.fullmatch(ID, str(native_id or "")) or not isinstance(export.get("hqAttempt"), int):
            raise DesignError("The renderer did not provide a verifiable native task identity.", 502)
        base = self.runtime_root / ".studio" / "jobs" / native_id / ("attempt-" + str(export["hqAttempt"]))
        file = inside(base, item.get("path", ""))
        name = str(item.get("name", "")).replace("\\", "/")
        if not name or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/")) or ":" in name:
            raise DesignError("The renderer returned an unsafe export name.", 502)
        if not file.is_file() or not 0 < file.stat().st_size <= 200 * 1024 * 1024 or file.stat().st_size != item.get("size"):
            raise DesignError("A design export is missing, empty or has changed. It was not registered as finished.", 502)
        with open(file, "rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != item.get("sha256"):
            raise DesignError("A design export failed its checksum. No successful delivery is claimed.", 502)
        return file, name, digest

    def register(self, project):
        export = project.get("lastExport")
        if not export:
            return None
        pid, revision, attempt = project.get("id"), export.get("projectRevision"), export.get("hqAttempt")
        if not re.fullmatch(ID, str(pid or "")) or not isinstance(revision, int) or not isinstance(attempt, int):
            raise DesignError("The renderer returned incomplete delivery provenance.", 502)
        if project.get("revision") != revision:
            # A reopened draft may retain the preceding export. Its new titles
            # and layout are not the provenance of those older finished files.
            code, _, body = self._request("GET", BASE + "/projects/" + pid + "?revision=" + str(revision))
            historical = json.loads(body)
            saved = historical.get("project") if isinstance(historical, dict) else None
            if code != 200 or not isinstance(saved, dict) or saved.get("id") != pid or saved.get("revision") != revision or saved.get("lastExport", {}).get("projectRevision") != revision or saved.get("lastExport", {}).get("hqAttempt") != attempt:
                raise DesignError("The exact exported project revision is unavailable. New draft titles were not substituted.", 409)
            project, export = saved, saved["lastExport"]
        key = f"{pid}:{revision}:{attempt}"
        with self.lock:
            index = self._index()
            if key in index["deliveries"]:
                cached = index["deliveries"][key]
                if not any(t.get("id") == cached.get("taskId") for t in self.load_tasks().get("tasks", [])):
                    raise DesignError("The saved HQ review task was removed. It was not recreated automatically; the editable project is still saved on the design engine.", 409)
                locations = [self.hq_root / area / cached.get("folder", "") for area in ("out", "approved")]
                present = [directory for directory in locations if directory.is_dir()]
                if len(present) != 1:
                    raise DesignError("The saved HQ design delivery is missing or ambiguous. It was not recreated or overwritten.", 409)
                for row in cached.get("files", []):
                    copied = inside(present[0], present[0] / row["name"])
                    if not copied.is_file() or copied.stat().st_size != row["size"]:
                        raise DesignError("The saved HQ design delivery is incomplete. Re-export after repairing the delivery record.", 409)
                    with open(copied, "rb") as source:
                        if hashlib.file_digest(source, "sha256").hexdigest() != row["sha256"]:
                            raise DesignError("The saved HQ design delivery changed after verification. It was not overwritten.", 409)
                return cached
            rows = export.get("files", [])
            if not isinstance(rows, list) or not 1 <= len(rows) <= 150:
                raise DesignError("The design delivery file list is invalid.", 502)
            verified, seen, total = [], set(), 0
            for item in rows:
                source, name, digest = self._verified_file(project, item)
                if name.casefold() in seen:
                    raise DesignError("The design delivery contains duplicate filenames.", 502)
                seen.add(name.casefold()); total += source.stat().st_size
                verified.append((source, name, digest, item))
            if total > 400 * 1024 * 1024 or not any(i.get("format") == "png" for _, _, _, i in verified):
                raise DesignError("The design delivery is too large or has no verified PNG artwork.", 502)
            folder = f"sermon-studio-{pid}-r{revision}-a{attempt}"
            out = self.hq_root / "out"; out.mkdir(parents=True, exist_ok=True)
            destination, temporary = out / folder, out / ("." + folder + "-" + uuid.uuid4().hex)
            if not destination.exists() and not (self.hq_root / "approved" / folder).exists():
                temporary.mkdir()
                try:
                    for source, name, digest, _ in verified:
                        target = inside(temporary, temporary / name); target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                        with open(target, "rb") as copied:
                            if hashlib.file_digest(copied, "sha256").hexdigest() != digest:
                                raise DesignError("A design file changed while being delivered. No review task was created.", 409)
                    (temporary / "README.md").write_text(
                        "# Sermon Design Studio delivery\n\nNative Resvg/Sharp renderer; generated imagery only when provider provenance records it. "
                        "This is not a Claude model run.\n\nProject: " + pid + "\nRevision: " + str(revision) +
                        "\n\nPNG/JPG artwork and source ZIP are separate files. A complete picture has embedded lettering; its SVG/HTML is an image container, not recovered text or layers. Review this exact version; nothing is approved or published.\n",
                        encoding="utf-8")
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            existing = destination if destination.exists() else self.hq_root / "approved" / folder
            for _, name, digest, _ in verified:
                target = inside(existing, existing / name)
                if not target.is_file():
                    raise DesignError("The prior design delivery is incomplete. It was preserved for repair.", 409)
                with open(target, "rb") as copied:
                    if hashlib.file_digest(copied, "sha256").hexdigest() != digest:
                        raise DesignError("The prior design delivery changed. It was not overwritten.", 409)
            # A crash between board creation and index persistence must not duplicate a task.
            marker = "out:" + folder
            prior = next((t for t in self.load_tasks().get("tasks", []) if marker in (t.get("note") or "").split()), None)
            if prior:
                task_id = prior["id"]
            else:
                code, result = self.task_action({"action": "add", "title": ("XHS Sermon Recap Pro" if project.get("kind") == "xhs" else "Sermon Title 16:9") + " · " + str(project.get("titles", {}).get("chinese") or project.get("name") or pid),
                    "team": "Design", "agent": "sermon-designer", "status": "review", "kind": "approval", "note": marker + " Native Design Studio renderer; user OK required.",
                    "subtitle": "Independent artwork + saved source · awaiting your OK"})
                if code != 201 or not result.get("added", {}).get("id"):
                    raise DesignError("Files were copied, but the HQ review task could not be registered. Retry opening the project; no model task was started.", 502)
                task_id = result["added"]["id"]
            delivery = {"projectId": pid, "revision": revision, "attempt": attempt, "taskId": task_id, "folder": folder,
                "nativeTaskId": project["hqTaskId"], "files": [{"path": str(source.relative_to(self.runtime_root)).replace("\\", "/"), "name": name, "sha256": digest, "size": item["size"]} for source, name, digest, item in verified]}
            index["deliveries"][key] = delivery; self._save_index(index)
            if self.notify:
                self.notify()
            return delivery

    def adapt(self, payload, register=True):
        project = payload.get("project") if isinstance(payload, dict) else None
        if isinstance(project, dict):
            delivery = self.register(project) if register else None
            native = project.get("hqTaskId")
            project["nativeTaskId"] = native
            project["hqTaskId"] = delivery["taskId"] if delivery else None
            project["hqReviewUrl"] = "/?task=" + quote(delivery["taskId"]) if delivery else None
            if delivery:
                payload["hqTaskId"] = delivery["taskId"]
            if isinstance(project.get("lastExport"), dict):
                for item in project["lastExport"].get("files", []):
                    item.pop("path", None)
                project["lastExport"].pop("zip", None)
        def rewrite(value):
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, str) and value.startswith("/api/output?"):
                parsed = parse_qs(urlparse(value).query)
                return BASE + "/download?" + urlencode({"path": parsed.get("path", [""])[0]})
            return value
        return rewrite(payload)

    def _download(self, handler, query, head=False):
        requested = parse_qs(query).get("path", [""])[0].replace("\\", "/")
        with self.lock:
            index = self._index()
        item = next((f for d in index["deliveries"].values() for f in d.get("files", []) if f.get("path") == requested), None)
        if not item:
            raise DesignError("Only this studio's verified exports can be downloaded here.", 404)
        file = inside(self.runtime_root / ".studio" / "jobs", self.runtime_root / requested)
        if not file.is_file() or file.stat().st_size != item["size"]:
            raise DesignError("The original design export is no longer available. Re-export this saved project.", 404)
        with open(file, "rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                raise DesignError("The design export changed after verification. Re-export it before downloading.", 409)
        size, start, end, partial = item["size"], 0, item["size"] - 1, False
        etag = '"' + item["sha256"] + '"'
        range_header = handler.headers.get("Range")
        if range_header and handler.headers.get("If-Range", etag) == etag:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header) if len(range_header) <= 256 else None
            valid = bool(match and (match[1] or match[2]))
            if valid:
                if match[1]:
                    start = int(match[1]); end = min(int(match[2]), size - 1) if match[2] else size - 1
                    valid = start < size and end >= start
                else:
                    suffix = int(match[2]); valid = suffix > 0
                    start, end = max(0, size - suffix), size - 1
            if not valid:
                handler._sermon_response_started = True
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{size}")
                handler.send_header("Accept-Ranges", "bytes")
                handler.send_header("ETag", etag)
                handler.send_header("Content-Length", "0")
                handler.send_header("Cache-Control", "private, no-store")
                handler.end_headers()
                return
            partial = True
        handler._sermon_response_started = True
        handler.send_response(206 if partial else 200)
        handler.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        handler.send_header("Content-Length", str(end - start + 1))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("ETag", etag)
        if partial:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.send_header("Content-Disposition", "attachment; filename=\"artwork" + file.suffix + "\"; filename*=UTF-8''" + quote(Path(item["name"]).name))
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        if not head:
            with open(file, "rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(1 << 16, remaining))
                    if not chunk:
                        handler.close_connection = True
                        return
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)

    def handle(self, handler):
        url = urlparse(handler.path); path = unquote(url.path); method = handler.command
        if path not in STATIC and not path.startswith(BASE + "/"):
            return False
        handler._sermon_response_started = False
        try:
            if not allowed(method, path):
                raise DesignError("Design Studio route not allowed.", 404)
            if method in ("POST", "PUT"):
                origin = handler.headers.get("Origin")
                expected = (handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "").lower()
                scheme = (handler.headers.get("X-Forwarded-Proto") or "http").lower()
                parsed_origin = urlparse(origin) if origin else None
                invalid_origin = parsed_origin and (parsed_origin.scheme != scheme or parsed_origin.netloc.lower() != expected or
                    parsed_origin.path not in ("", "/") or parsed_origin.query or parsed_origin.fragment or parsed_origin.username or parsed_origin.password)
                if handler.headers.get("Sec-Fetch-Site") == "cross-site" or invalid_origin:
                    raise DesignError("Open this studio directly in your signed-in Agent HQ.", 403)
            self.resume_pending()
            if path in STATIC:
                file = inside(self.engine_root / "studio" / "public", self.engine_root / "studio" / "public" / path[1:])
                if not file.is_file():
                    raise DesignError("The prepared studio interface is missing.", 503)
                handler._sermon_response_started = True
                if path == "/sermon-studio.html":                 # the page lives on D:, outside this repo: fix its way home here
                    page = file.read_bytes()
                    if b"sermon-studio.js" not in page:          # else the fix rides in that script (an inline one may be blocked)
                        page = page.replace(b"</body>", BACK_TO_HQ + b"</body>", 1) if b"</body>" in page else page + BACK_TO_HQ
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/html; charset=utf-8")
                    handler.send_header("Content-Length", str(len(page)))
                    handler.send_header("Cache-Control", "no-store")
                    handler.end_headers()
                    if method != "HEAD":
                        handler.wfile.write(page)
                    return True
                if path == "/sermon-studio.js":                   # the studio's own script: allowed even on a strict page
                    page = HOLD_UNLOAD_JS + b"\n" + file.read_bytes() + b"\n" + BACK_TO_HQ_JS
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/javascript; charset=utf-8")
                    handler.send_header("Content-Length", str(len(page)))
                    handler.send_header("Cache-Control", "no-store")
                    handler.end_headers()
                    if method != "HEAD":
                        handler.wfile.write(page)
                    return True
                return handler.send_static(str(file)) or True
            if path == BASE + "/download":
                self._download(handler, url.query, method == "HEAD"); return True
            data = None
            if method in ("POST", "PUT"):
                if handler.headers.get("Transfer-Encoding"):
                    raise DesignError("Use a bounded JSON request.", 400)
                try:
                    length = int(handler.headers.get("Content-Length") or 0)
                except ValueError:
                    raise DesignError("Invalid request size.", 400)
                limit = 56 * 1024 * 1024 if path == BASE + "/assets" else 2 * 1024 * 1024
                if length < 0 or length > limit:
                    raise DesignError("The design request is too large.", 413)
                if not handler.headers.get("Content-Type", "").lower().startswith("application/json"):
                    raise DesignError("Design Studio requires JSON.", 415)
                data = handler.rfile.read(length)
                if len(data) != length:
                    raise DesignError("The design upload was interrupted.", 400)
                try:
                    if not isinstance(json.loads(data or b"{}"), dict):
                        raise ValueError()
                except ValueError:
                    raise DesignError("The design request must be a JSON object.", 400)
            self.ensure_engine()
            headers = {"Host": "127.0.0.1:4341", "Accept": handler.headers.get("Accept", "*/*")}
            if data is not None:
                headers.update({"Content-Type": "application/json", "Content-Length": str(len(data)), "Origin": "http://127.0.0.1:4341", "Sec-Fetch-Site": "same-origin"})
            code, response_headers, body = self._request(method, path + ("?" + url.query if url.query else ""), data, headers)
            ctype = next((v for k, v in response_headers.items() if k.lower() == "content-type"), "application/octet-stream")
            if method != "HEAD" and "application/json" in ctype:
                try:
                    payload = json.loads(body)
                except ValueError:
                    raise DesignError("The renderer returned invalid metadata.", 502)
                if 200 <= code < 300:
                    if code == 202 and method == "POST" and re.fullmatch(BASE + r"/projects/" + ID + r"/(?:generate|preview)", path):
                        if not isinstance(payload.get("job"), dict) or payload["job"].get("projectId") != path.split("/")[-2]:
                            raise DesignError("The accepted job does not match its assigned project. No different task was watched.", 502)
                        self._track_job(payload.get("job"))
                    payload = self.adapt(payload, register=not (method == "GET" and "revision" in parse_qs(url.query)))
                handler._sermon_response_started = True
                handler.send_json(payload, code); return True
            handler._sermon_response_started = True
            handler.send_response(code)
            for key, value in response_headers.items():
                if key.lower() in ("content-type", "content-security-policy", "etag", "content-length"):
                    handler.send_header(key, value)
            handler.send_header("Cache-Control", "private, no-store"); handler.end_headers()
            if method != "HEAD":
                handler.wfile.write(body)
            return True
        except DesignError as error:
            if handler._sermon_response_started:
                handler.close_connection = True
            else:
                try:
                    handler.send_json({"error": str(error)}, error.status)
                except OSError:
                    handler.close_connection = True
            return True
        except (OSError, http.client.HTTPException):
            if handler._sermon_response_started:
                # A cancelled/resumed browser download is not a second HTTP
                # response. Its client can request the remaining bytes later.
                handler.close_connection = True
            else:
                try:
                    handler.send_json({"error": "The local design service is unavailable. Saved projects and existing HQ tasks are preserved; the request was not replayed."}, 503)
                except OSError:
                    handler.close_connection = True
            return True
