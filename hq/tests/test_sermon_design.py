import ast
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sermon_design import BACK_TO_HQ_JS, BASE, HOLD_UNLOAD_JS, DesignError, SermonDesignBridge, allowed, inside


class Handler:
    def __init__(self, path, method="GET", body=None, headers=None):
        self.path, self.command = path, method
        encoded = json.dumps(body).encode() if body is not None else b""
        self.headers = {"Host": "office.example.ts.net", **({"Content-Type": "application/json", "Content-Length": str(len(encoded))} if body is not None else {}), **(headers or {})}
        self.rfile, self.wfile = io.BytesIO(encoded), io.BytesIO()
        self.code, self.payload, self.response_headers = None, None, {}
        self.response_codes = []
    def send_json(self, payload, code=200):
        self.payload, self.code = payload, code; self.response_codes.append(code)
    def send_static(self, file):
        self.code = 200; self.wfile.write(Path(file).read_bytes())
    def send_response(self, code):
        self.code = code; self.response_codes.append(code)
    def send_header(self, key, value):
        self.response_headers[key] = value
    def end_headers(self):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine, self.office = self.root / "engine", self.root / "office"
        self.engine.mkdir(); self.office.mkdir()
        self.tasks, self.calls = [], []
        self.bridge = SermonDesignBridge(self.office, self.task_action, lambda: {"tasks": self.tasks}, engine_root=self.engine, request=self.upstream, auto_start=False)
        self.reply = {}
    def tearDown(self):
        self.bridge.stop_delivery_watcher()
        for bridge in getattr(self, "other_bridges", []):
            bridge.stop_delivery_watcher()
        self.temp.cleanup()
    def task_action(self, body):
        task = {**body, "id": "t" + str(len(self.tasks) + 1)}
        self.tasks.append(task)
        return 201, {"added": task}
    def upstream(self, method, route, data, headers):
        self.calls.append((method, route, data, headers))
        if route == "/api/runtime":
            payload = {"app": "sermon-design-engine", "workspaceRoot": str(self.bridge.runtime_root), "sourceRoot": str(self.engine)}
        elif route == BASE + "/capabilities":
            payload = {"dimensions": {"title": [3840, 2160]}, "providers": [{"id": "codex", "configured": False}, {"id": "openai-api", "configured": False}], "defaultProvider": "codex"}
        else:
            payload = copy.deepcopy(self.reply)
        return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode()
    def project(self):
        folder = self.bridge.runtime_root / ".studio" / "jobs" / "native-task" / "attempt-1" / "export-a"
        folder.mkdir(parents=True)
        rows = []
        for name, data, fmt in [("Sermon_Title_Design_01.png", b"independent PNG test fixture", "png"), ("fonts/OFL.txt", b"license fixture", "txt"), ("Sermon_Title_r3.zip", b"zip fixture", "zip")]:
            file = folder / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(data)
            rows.append({"path": str(file), "name": name, "format": fmt, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        return {"id": "project-one", "kind": "title", "name": "Sermon", "titles": {"chinese": "认识神的声音"}, "revision": 4, "hqTaskId": "native-task", "lastExport": {"projectRevision": 4, "hqAttempt": 1, "files": rows}}
    def test_route_allowlist_has_no_generic_proxy_or_run(self):
        for method, route in [("GET", BASE + "/capabilities"), ("POST", BASE + "/projects/p1/recap"), ("PUT", BASE + "/projects/p1"), ("HEAD", "/sermon-studio.js")]:
            self.assertTrue(allowed(method, route))
        for method, route in [("POST", "/api/run"), ("GET", "/api/output"), ("GET", BASE + "/provider-config"), ("POST", BASE + "/projects/p1/approve"), ("DELETE", BASE + "/projects/p1"), ("GET", "http://evil.example/")]:
            self.assertFalse(allowed(method, route))
    def test_studio_script_lets_back_to_hq_leave_a_busy_page(self):
        # the studio holds the page with beforeunload while a job runs; the desktop app then never leaves. HQ's code goes
        # before the studio's (to keep those handlers) and after it (Back to HQ asks, then leaves).
        public = self.engine / "studio" / "public"
        public.mkdir(parents=True)
        (public / "sermon-studio.js").write_bytes(b"/* studio */ addEventListener('beforeunload', e => e.preventDefault());")
        handler = Handler("/sermon-studio.js")
        self.assertTrue(self.bridge.handle(handler))
        served = handler.wfile.getvalue()
        self.assertTrue(served.startswith(HOLD_UNLOAD_JS))
        self.assertIn(b"/* studio */", served)
        self.assertTrue(served.endswith(BACK_TO_HQ_JS))
        self.assertNotIn(b"__LEAVE_MSG__", BACK_TO_HQ_JS)
        self.assertIn(b"window.confirm(", BACK_TO_HQ_JS)

    def test_registration_copies_actual_files_once_and_keeps_approval(self):
        project = self.project()
        first = self.bridge.register(project)
        second = self.bridge.register(copy.deepcopy(project))
        self.assertEqual(first, second); self.assertEqual(len(self.tasks), 1)
        task = self.tasks[0]
        self.assertEqual((task["team"], task["agent"], task["status"], task["kind"]), ("Design", "sermon-designer", "review", "approval"))
        self.assertIn("Native Design Studio", task["note"])
        out = self.office / "out" / first["folder"]
        for row in project["lastExport"]["files"]:
            self.assertEqual((out / row["name"]).read_bytes(), Path(row["path"]).read_bytes())
        (self.office / "approved").mkdir()
        shutil.move(str(out), self.office / "approved" / first["folder"])
        self.assertEqual(self.bridge.register(project)["taskId"], first["taskId"])
        self.assertFalse(out.exists()); self.assertEqual(len(self.tasks), 1)
    def test_path_escape_and_hash_failure_create_no_task(self):
        project = self.project()
        project["lastExport"]["files"][0]["path"] = str(self.root / "private.txt")
        with self.assertRaises(DesignError):
            self.bridge.register(project)
        self.assertEqual(self.tasks, [])
        project = self.project_existing()
        project["lastExport"]["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(DesignError):
            self.bridge.register(project)
        self.assertEqual(self.tasks, [])
    def project_existing(self):
        # Rebuild metadata without recreating the directory.
        folder = self.bridge.runtime_root / ".studio" / "jobs" / "native-task" / "attempt-1" / "export-a"
        rows = [{"path": str(p), "name": str(p.relative_to(folder)).replace("\\", "/"), "format": p.suffix[1:], "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in folder.rglob("*") if p.is_file()]
        return {"id": "project-one", "kind": "title", "revision": 4, "hqTaskId": "native-task", "lastExport": {"projectRevision": 4, "hqAttempt": 1, "files": rows}}
    def test_crash_retry_finds_existing_review_task(self):
        project = self.project()
        first = self.bridge.register(project)
        self.bridge.index_path.unlink()
        retry = self.bridge.register(project)
        self.assertEqual(first["taskId"], retry["taskId"]); self.assertEqual(len(self.tasks), 1)
    def test_cached_delivery_rechecks_local_files_and_does_not_restore_removed_task(self):
        project = self.project(); delivery = self.bridge.register(project)
        artifact = self.office / "out" / delivery["folder"] / project["lastExport"]["files"][0]["name"]
        artifact.write_bytes(b"tampered")
        with self.assertRaisesRegex(DesignError, "incomplete|changed"):
            self.bridge.register(project)
        self.assertEqual(len(self.tasks), 1)
        artifact.write_bytes(b"independent PNG test fixture")
        self.tasks.clear()
        with self.assertRaisesRegex(DesignError, "removed"):
            self.bridge.register(project)
        self.assertEqual(self.tasks, [])
    def test_malformed_runtime_identity_is_a_controlled_error(self):
        self.bridge.request_impl = lambda *args: (200, {}, b"[]")
        with self.assertRaisesRegex(DesignError, "unrecognized"):
            self.bridge.ensure_engine()
    def test_symbolic_link_exports_are_rejected(self):
        target = self.root / "target.txt"; target.write_text("private")
        link = self.root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("This Windows account cannot create symbolic links")
        with self.assertRaisesRegex(DesignError, "Linked"):
            inside(self.root, link)
    def test_adaptation_uses_actual_hq_task_and_download_allowlist(self):
        project = self.project()
        source = project["lastExport"]["files"][0]
        relative = str(Path(source["path"]).relative_to(self.bridge.runtime_root)).replace("\\", "/")
        payload = self.bridge.adapt({"project": project, "url": "/api/output?path=" + relative + "&download=1"})
        self.assertEqual(payload["project"]["hqTaskId"], "t1")
        self.assertEqual(payload["project"]["nativeTaskId"], "native-task")
        self.assertTrue(payload["url"].startswith(BASE + "/download?"))
        self.assertNotIn("path", payload["project"]["lastExport"]["files"][0])
        download = Handler(payload["url"])
        self.bridge.handle(download)
        self.assertEqual(download.code, 200); self.assertEqual(download.wfile.getvalue(), b"independent PNG test fixture")
        self.assertIn("attachment", download.response_headers["Content-Disposition"])
        bad = Handler(BASE + "/download?path=.studio/jobs/other/private.txt")
        self.bridge.handle(bad); self.assertEqual(bad.code, 404)
    def test_json_proxy_is_bounded_origin_checked_and_fixed_upstream(self):
        self.reply = {"project": {"id": "p1", "assets": []}}
        handler = Handler(BASE + "/projects", "POST", {"kind": "title"}, {"Origin": "https://office.example.ts.net", "X-Forwarded-Proto": "https"})
        self.bridge.handle(handler); self.assertEqual(handler.code, 200)
        proxied = self.calls[-1]
        self.assertEqual(proxied[0:2], ("POST", BASE + "/projects"))
        self.assertEqual(proxied[3]["Origin"], "http://127.0.0.1:4341")
        self.assertEqual(proxied[3]["Host"], "127.0.0.1:4341")
        cross = Handler(BASE + "/projects", "POST", {}, {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
        self.bridge.handle(cross); self.assertEqual(cross.code, 403)
        wrong_scheme = Handler(BASE + "/projects", "POST", {}, {"Origin": "http://office.example.ts.net", "X-Forwarded-Proto": "https"})
        self.bridge.handle(wrong_scheme); self.assertEqual(wrong_scheme.code, 403)
        huge = Handler(BASE + "/projects", "POST", {}, {"Content-Length": str(3 * 1024 * 1024)})
        self.bridge.handle(huge); self.assertEqual(huge.code, 413)
    def download_url(self):
        project = self.project(); source = project["lastExport"]["files"][0]
        relative = str(Path(source["path"]).relative_to(self.bridge.runtime_root)).replace("\\", "/")
        self.bridge.register(project)
        return BASE + "/download?path=" + relative
    def test_download_full_and_range_head_and_resuming(self):
        url = self.download_url(); content = b"independent PNG test fixture"
        full = Handler(url, "HEAD")
        self.bridge.handle(full)
        self.assertEqual(full.code, 200)
        self.assertEqual(full.response_headers["Content-Length"], str(len(content)))
        self.assertEqual(full.response_headers["Accept-Ranges"], "bytes")
        self.assertEqual(full.wfile.getvalue(), b"")
        for method, header, expected in [("GET", "bytes=0-4", content[:5]), ("GET", "bytes=5-", content[5:]), ("GET", "bytes=-3", content[-3:]), ("GET", "bytes=3-99999", content[3:]), ("HEAD", "bytes=0-4", b"")]:
            with self.subTest(method=method, header=header):
                request = Handler(url, method, headers={"Range": header})
                self.bridge.handle(request)
                self.assertEqual(request.code, 206)
                self.assertEqual(request.wfile.getvalue(), expected)
                self.assertTrue(request.response_headers["Content-Range"].startswith("bytes "))
                self.assertEqual(request.response_headers["ETag"], full.response_headers["ETag"])
        changed = Handler(url, headers={"Range": "bytes=5-", "If-Range": '"old-version"'})
        self.bridge.handle(changed)
        self.assertEqual(changed.code, 200); self.assertEqual(changed.wfile.getvalue(), content)
    def test_download_rejects_unsatisfiable_or_multiple_ranges(self):
        url = self.download_url()
        for method in ("GET", "HEAD"):
            for value in ("bytes=999-", "bytes=4-2", "bytes=-0", "bytes=", "bytes=0-2,4-5", "items=0-1", "bytes=" + "1" * 257 + "-"):
                with self.subTest(method=method, value=value):
                    request = Handler(url, method, headers={"Range": value})
                    self.bridge.handle(request)
                    self.assertEqual(request.code, 416)
                    self.assertEqual(request.response_headers["Content-Range"], "bytes */" + str(len(b"independent PNG test fixture")))
                    self.assertEqual(request.response_headers["Content-Length"], "0")
                    self.assertEqual(request.wfile.getvalue(), b"")
    def test_cancelled_download_never_sends_a_second_error_response(self):
        url = self.download_url()
        class AbortedWriter:
            def write(self, chunk):
                raise ConnectionAbortedError("browser cancelled the download")
        for headers, status in [({}, 200), ({"Range": "bytes=5-"}, 206)]:
            request = Handler(url, headers=headers); request.wfile = AbortedWriter()
            self.bridge.handle(request)
            self.assertEqual(request.response_codes, [status])
            self.assertTrue(request.close_connection)
            self.assertIsNone(request.payload)
    def wait_for(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail("Background delivery did not reach the expected state")
    def watch_record(self, bridge=None):
        bridge = bridge or self.bridge
        with bridge.watch_lock:
            return bridge._pending()["jobs"]["accepted-job"]
    def queued_job_fixture(self, outcome="succeeded", historical=False, stale_titles=False):
        project, completed, original = self.project(), threading.Event(), self.upstream
        job = {"id": "accepted-job", "projectId": project["id"], "status": "running"}
        def request(method, route, data, headers):
            if method == "POST" and route == BASE + "/projects/project-one/generate":
                self.calls.append((method, route, data, headers))
                return 202, {"Content-Type": "application/json"}, json.dumps({"job": job, "project": {"id": project["id"], "assets": []}}).encode()
            if route == BASE + "/jobs/accepted-job":
                self.calls.append((method, route, data, headers))
                result = {**job, "status": outcome if completed.is_set() else "running"}
                if result["status"] == "succeeded":
                    result["projectRevision"] = 4
                if result["status"] == "failed":
                    result["error"] = "Fixture generation failed"
                current = copy.deepcopy(project)
                if historical:
                    current["lastExport"]["projectRevision"] = 9
                if stale_titles:
                    current["revision"] = 5
                    current["titles"] = {"chinese": "Later draft title must not label old files"}
                return 200, {"Content-Type": "application/json"}, json.dumps({"job": result, "project": current}).encode()
            if route == BASE + "/projects/project-one?revision=4":
                self.calls.append((method, route, data, headers))
                return 200, {"Content-Type": "application/json"}, json.dumps({"project": project}).encode()
            return original(method, route, data, headers)
        self.bridge.request_impl = request; self.bridge.delivery_poll_seconds = .01
        return completed, request
    def test_accepted_job_delivers_without_any_client_poll_or_extra_post(self):
        completed, _ = self.queued_job_fixture()
        request = Handler(BASE + "/projects/project-one/generate", "POST", {"useAi": False})
        self.bridge.handle(request)
        self.assertEqual(request.code, 202); self.assertEqual(self.tasks, [])
        completed.set()
        self.wait_for(lambda: len(self.tasks) == 1)
        self.wait_for(lambda: self.watch_record()["status"] == "delivered")
        self.bridge.resume_pending(); time.sleep(.03)
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(sum(method == "POST" for method, *_ in self.calls), 1)
        self.assertTrue(any(route == BASE + "/jobs/accepted-job" for _, route, *_ in self.calls))
    def test_saved_pending_watch_resumes_read_only_after_restart(self):
        completed, upstream = self.queued_job_fixture(historical=True)
        self.bridge.handle(Handler(BASE + "/projects/project-one/generate", "POST", {}))
        self.bridge.stop_delivery_watcher()
        second = SermonDesignBridge(self.office, self.task_action, lambda: {"tasks": self.tasks}, engine_root=self.engine, request=upstream, auto_start=False, delivery_poll_seconds=.01)
        self.other_bridges = [second]
        completed.set()
        with mock.patch("sermon_design.subprocess.Popen") as launch:
            second.resume_pending()
            self.wait_for(lambda: self.watch_record(second)["status"] == "delivered")
            launch.assert_not_called()
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(sum(method == "POST" for method, *_ in self.calls), 1)
        self.assertTrue(any(route == BASE + "/projects/project-one?revision=4" for _, route, *_ in self.calls))
    def test_failed_watch_records_evidence_without_creating_finished_task(self):
        completed, _ = self.queued_job_fixture(outcome="failed")
        self.bridge.handle(Handler(BASE + "/projects/project-one/generate", "POST", {}))
        completed.set()
        self.wait_for(lambda: self.watch_record()["status"] == "failed")
        self.assertEqual(self.tasks, [])
        self.assertIn("Fixture generation failed", self.watch_record()["lastError"])
        self.assertEqual(sum(method == "POST" for method, *_ in self.calls), 1)
    def test_watcher_uses_exact_revision_when_new_draft_keeps_old_export(self):
        completed, _ = self.queued_job_fixture(stale_titles=True)
        self.bridge.handle(Handler(BASE + "/projects/project-one/generate", "POST", {}))
        completed.set()
        self.wait_for(lambda: self.watch_record()["status"] == "delivered")
        self.assertIn("认识神的声音", self.tasks[0]["title"])
        self.assertNotIn("Later draft", self.tasks[0]["title"])
        self.assertTrue(any(route == BASE + "/projects/project-one?revision=4" for _, route, *_ in self.calls))
    def test_manual_reopen_registers_exported_title_not_later_draft_title(self):
        original = self.project(); self.reply = {"project": original}
        draft = copy.deepcopy(original); draft["revision"] = 5; draft["titles"]["chinese"] = "Later draft"
        self.bridge.register(draft)
        self.assertIn("认识神的声音", self.tasks[0]["title"])
        self.assertNotIn("Later draft", self.tasks[0]["title"])
    def test_watch_expiry_does_not_generate_or_import_a_task(self):
        self.queued_job_fixture()
        self.bridge.handle(Handler(BASE + "/projects/project-one/generate", "POST", {}))
        with self.bridge.watch_lock:
            pending = self.bridge._pending(); pending["jobs"]["accepted-job"]["deadlineAt"] = time.time() - 1
            self.bridge._save_pending(pending)
        self.wait_for(lambda: self.watch_record()["status"] == "expired")
        self.assertEqual(self.tasks, [])
        self.assertEqual(sum(method == "POST" for method, *_ in self.calls), 1)
    def test_no_restart_when_another_service_owns_engine_port(self):
        self.bridge.request_impl = lambda *args: (200, {}, json.dumps({"app": "unrecognized", "workspaceRoot": str(self.root)}).encode())
        self.bridge.auto_start = True
        with mock.patch("sermon_design.subprocess.Popen") as launch:
            with self.assertRaisesRegex(DesignError, "different or unrecognized"):
                self.bridge.ensure_engine()
            launch.assert_not_called()
    def test_probe_requires_codex_default_and_keeps_service_unchanged(self):
        original = self.upstream
        for capabilities in [
            {"dimensions": {"title": [3840, 2160]}},
            {"dimensions": {"title": [3840, 2160]}, "defaultProvider": "openai-api", "providers": [{"id": "codex"}]},
            {"dimensions": {"title": [3840, 2160]}, "defaultProvider": "codex", "providers": [{"id": "openai-api"}]},
        ]:
            def stale(method, route, data, headers):
                if route == BASE + "/capabilities":
                    return 200, {}, json.dumps(capabilities).encode()
                return original(method, route, data, headers)
            self.bridge.request_impl = stale
            with self.subTest(capabilities=capabilities), mock.patch("sermon_design.subprocess.Popen") as launch:
                with self.assertRaisesRegex(DesignError, "prepared update"):
                    self.bridge._probe()
                launch.assert_not_called()
    def test_capability_probe_allows_codex_signin_time_without_slowing_runtime_probe(self):
        self.bridge.request_impl = None
        with mock.patch("sermon_design.http.client.HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200; response.read.return_value = b"{}"
            response.getheader.return_value = "application/json"
            response.getheaders.return_value = [("Content-Type", "application/json")]
            self.bridge._request("GET", "/api/runtime")
            self.assertEqual(connection.call_args.kwargs["timeout"], 3)
            self.bridge._request("GET", BASE + "/capabilities")
            self.assertEqual(connection.call_args.kwargs["timeout"], 20)
    def test_down_engine_starts_only_fixed_installed_node_script(self):
        (self.engine / "studio").mkdir(); (self.engine / "studio" / "sermon-design-server.mjs").write_text("// fixture")
        original = self.bridge.request_impl
        count = [0]
        def first_down(*args):
            count[0] += 1
            if count[0] == 1:
                raise ConnectionRefusedError()
            return original(*args)
        self.bridge.request_impl = first_down; self.bridge.auto_start = True
        with mock.patch("sermon_design.shutil.which", return_value=sys.executable), mock.patch("sermon_design.subprocess.Popen") as launch:
            self.bridge.ensure_engine()
            args, kwargs = launch.call_args
            self.assertEqual(args[0], [str(Path(sys.executable).resolve()), str(self.bridge.engine_root / "studio" / "sermon-design-server.mjs")])
            self.assertEqual(kwargs["cwd"], self.bridge.engine_root); self.assertEqual(kwargs["env"]["PORT"], "4341")
            self.assertEqual(launch.call_count, 1)
    def test_existing_guard_precedes_every_bridge_route(self):
        source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Handler")
        for name in ("do_GET", "do_POST", "do_PUT", "do_HEAD"):
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
            bridge_line = next(n.lineno for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "sermon_design")
            guards = [n.lineno for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "guard"]
            self.assertTrue(any(line < bridge_line for line in guards), name)


if __name__ == "__main__":
    unittest.main()
