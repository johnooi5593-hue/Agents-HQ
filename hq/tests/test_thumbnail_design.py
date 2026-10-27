import base64
import ast
import copy
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thumbnail_design import BASE, ThumbnailDesignBridge, DesignError, digest
from test_sermon_design import Handler

# Real 1x1 PNG fixture; no user content or image/model execution.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=")


class Channels:
    rows = [{"key": "", "name": "NLRCC"}, {"key": "pong-gospel", "name": "Pong+Gospel"}]
    def get(self, key):
        return next((c for c in self.rows if c["key"] == key), None)
    def name(self, key):
        return self.get(key)["name"]
    def payload(self):
        return {"channels": self.rows}


class Engine:
    def __init__(self, root):
        self.runtime_root, self.calls, self.jobs = root, [], {}
        self.reject = None
    def ensure_engine(self):
        pass
    def _probe(self):
        pass
    def _request(self, method, route, payload=None, headers=None):
        self.calls.append((method, route))
        if route.endswith("/capabilities"):
            result = {"schemaVersion": 1}
        elif method == "POST":
            if self.reject:
                return self.reject, {}, json.dumps({"error": "deliberate fixture rejection"}).encode()
            request = json.loads(payload)
            self.jobs[request["requestId"]] = {"id": request["requestId"], "status": "running", "progress": 1, "request": request}
            result = {"job": self.jobs[request["requestId"]]}
        else:
            result = {"job": self.jobs[route.rsplit("/", 1)[1]]}
        return 200, {}, json.dumps(result).encode()


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.office, self.runtime = self.root / "office", self.root / "runtime"
        self.office.mkdir(); self.runtime.mkdir()
        self.folder = self.office / "out" / "video-one"
        self.folder.mkdir(parents=True)
        (self.folder / "final.mp4").write_bytes(b"test approved-video bytes, not a playable video")
        (self.folder / "post.md").write_text("# Caption\nActual supplied caption", encoding="utf-8")
        (self.folder / "followups.json").write_text('{"never":"copy"}')
        self.tasks = [{"id": "t1", "status": "review", "note": "out:video-one", "title": "video"}]
        self.engine = Engine(self.runtime)
        self.bridge = ThumbnailDesignBridge(self.office, self.engine, Channels(), self.add_task, lambda: {"tasks": self.tasks}, auto_watch=False)
        self.frame = mock.patch.object(self.bridge, "_frame", return_value=None)
        self.frame.start()
    def tearDown(self):
        self.frame.stop()
        self.bridge.stop.set()
        self.temp.cleanup()
    def add_task(self, body):
        task = dict(body, id="t" + str(len(self.tasks) + 1))
        self.tasks.append(task)
        return 201, {"added": task}
    def template(self, channel="", name="Template"):
        self.bridge.save_template({"channel": channel, "name": name, "dataUrl": "data:image/png;base64," + base64.b64encode(PNG).decode(), "width": 1080, "height": 1440, "instructions": "Keep this brand", "makeDefault": True})
        return self.bridge.config()["channels"][0 if channel == "" else 1]["defaultTemplateId"]
    def body(self, **patch):
        data = {"folder": "out/video-one", "taskId": "t1", "videoPath": "final.mp4", "videoSha256": digest(self.folder / "final.mp4"), "channel": "", "title": "Exact title", "approval": True}
        return data | patch
    def finish(self, ident):
        job = self.engine.jobs[ident]
        output = self.runtime / ".studio" / "thumbnail-design" / "jobs" / ident / "output"
        output.mkdir(parents=True)
        rows = []
        for i in range(4):
            file = output / ("thumbnail-option-" + str(i + 1) + ".png")
            file.write_bytes(PNG)
            rows.append({"name": file.name, "path": str(file), "size": len(PNG), "sha256": digest(file), "format": "png"})
        manifest = output / "thumbnail-manifest.json"
        manifest.write_text(json.dumps({"provenance": job["request"]["provenance"]}))
        rows.append({"name": manifest.name, "path": str(manifest), "size": manifest.stat().st_size, "sha256": digest(manifest), "format": "json"})
        job.update(status="succeeded", progress=100, files=rows)
        return self.bridge.poll(ident)["job"]

    def test_channel_templates_are_versioned_and_never_cross_brand(self):
        first = self.template()
        second = self.template()
        pong = self.template("pong-gospel")
        config = self.bridge.config()
        self.assertEqual([t["revision"] for t in config["channels"][0]["templates"]], [1, 2])
        self.assertEqual(config["channels"][0]["defaultTemplateId"], second)
        self.assertNotEqual(first, second)
        with self.assertRaises(DesignError):
            self.bridge.set_default({"channel": "", "templateId": pong})
        with self.assertRaises(DesignError):
            self.bridge.approve_video(self.body(templateId=pong))
        self.assertFalse(self.engine.calls)

    def test_video_approval_is_explicit_fresh_and_idempotent(self):
        self.template()
        with self.assertRaises(DesignError):
            self.bridge.approve_video(self.body(approval=False))
        with self.assertRaises(DesignError):
            self.bridge.approve_video(self.body(videoSha256="0" * 64))
        result = self.bridge.approve_video(self.body())["job"]
        again = self.bridge.approve_video(self.body())["job"]
        self.assertEqual(result["id"], again["id"])
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 1)
        self.assertEqual(self.tasks[0]["status"], "review")
        self.assertTrue(self.folder.is_dir())
        self.assertIn("Approve video", self.bridge.guard_approval("video-one"))

    def test_missing_template_and_known_channel_mismatch_block(self):
        with self.assertRaisesRegex(DesignError, "template"):
            self.bridge.approve_video(self.body())
        self.template()
        (self.folder / "channel.txt").write_text("pong-gospel")
        with self.assertRaisesRegex(DesignError, "channel"):
            self.bridge.approve_video(self.body())
        self.assertFalse(self.engine.calls)

    def test_real_files_return_in_separate_final_review_only(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(ident)
        self.assertEqual(result["status"], "delivered")
        folder = self.office / result["delivery"]["folder"]
        self.assertEqual(len(list(folder.glob("*.png"))), 4)
        self.assertEqual((folder / "video.mp4").read_bytes(), (self.folder / "final.mp4").read_bytes())
        self.assertTrue((folder / "post.md").exists())
        self.assertFalse((folder / "followups.json").exists())
        self.assertEqual([t["status"] for t in self.tasks], ["review", "review"])
        self.assertIsNone(self.bridge.guard_approval(folder.name))
        self.bridge.poll(ident)
        self.assertEqual(len(self.tasks), 2)
        (folder / "thumbnail-option-1.png").write_bytes(b"changed")
        self.assertIn("changed", self.bridge.guard_approval(folder.name))

    def test_source_change_blocks_delivery_and_final_approval(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        (self.folder / "final.mp4").write_bytes(b"new unapproved source")
        result = self.finish(ident)
        self.assertEqual(result["status"], "delivery-error")
        self.assertEqual(len(self.tasks), 1)

    def test_wrong_provenance_and_outside_output_do_not_deliver(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        self.engine.jobs[ident]["request"]["provenance"]["channel"] = "pong-gospel"
        result = self.finish(ident)
        self.assertEqual(result["status"], "delivery-error")
        self.assertEqual(len(self.tasks), 1)

    def test_new_revision_invalidates_prior_final_approval(self):
        self.template()
        first = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(first)
        self.bridge.approve_video(self.body(title="New exact title"))
        self.assertIn("newer", self.bridge.guard_approval(Path(result["delivery"]["folder"]).name))

    def test_failed_retry_is_deliberate_and_uncertain_is_not_repeated(self):
        self.template()
        self.engine.reject = 409
        first = self.bridge.approve_video(self.body())["job"]
        self.assertEqual(first["status"], "failed")
        again = self.bridge.approve_video(self.body())["job"]
        self.assertEqual(first["id"], again["id"])
        self.engine.reject = None
        second = self.bridge.approve_video(self.body(retry=True))["job"]
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(second["status"], "watching")

    def test_routes_bound_json_reject_cross_origin_and_no_generic_proxy(self):
        handler = Handler(BASE + "/templates", "POST", {}, {"Origin": "https://evil.invalid"})
        self.bridge.handle(handler)
        self.assertEqual(handler.code, 403)
        handler = Handler(BASE + "/run", "POST", {})
        self.bridge.handle(handler)
        self.assertEqual(handler.code, 404)
        handler = Handler(BASE + "/config")
        self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["channels"][1]["name"], "Pong+Gospel")

    def test_channel_without_template_keeps_plain_approval(self):
        self.assertIsNone(self.bridge.guard_approval("video-one"))
        self.template("pong-gospel")                       # another brand's template does not change this channel
        self.assertIsNone(self.bridge.guard_approval("video-one"))
        (self.folder / "channel.txt").write_text("pong-gospel", encoding="utf-8")
        self.assertIn("Approve video", self.bridge.guard_approval("video-one"))

    def test_generic_source_guard_with_template_without_review_status(self):
        self.template()
        self.tasks[0]["status"] = "doing"
        self.assertIn("Approve video", self.bridge.guard_approval("video-one"))

    def test_unreadable_channel_stays_guarded(self):
        (self.folder / "channel.txt").write_text("no-such-channel", encoding="utf-8")
        self.assertIn("Approve video", self.bridge.guard_approval("video-one"))

    def test_manifest_rewrite_cannot_approve_changed_images(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(ident)
        folder = self.office / result["delivery"]["folder"]
        manifest_path = folder / "thumbnail-final.json"
        manifest = json.loads(manifest_path.read_text())
        image = folder / "thumbnail-option-1.png"
        image.write_bytes(b"changed image bytes")
        manifest["files"][0].update(sha256=digest(image), size=image.stat().st_size)
        manifest_path.write_text(json.dumps(manifest))
        self.assertIn("changed", self.bridge.guard_approval(folder.name))

    def test_multi_video_parent_waits_for_every_final_and_omits_ambiguous_copy(self):
        self.template()
        second = self.folder / "other.mp4"
        second.write_bytes(b"second source")
        first_id = self.bridge.approve_video(self.body())["job"]["id"]
        first = self.finish(first_id)
        first_folder = self.office / first["delivery"]["folder"]
        self.assertFalse((first_folder / "post.md").exists())
        self.assertTrue(any("Ambiguous" in w for w in first["warnings"]))
        (self.office / "approved").mkdir()
        first_folder.rename(self.office / "approved" / first_folder.name)
        mark = lambda task, status: task.update(status=status)
        self.bridge.complete_source(self.tasks[-1], {"tasks": self.tasks}, mark)
        self.assertEqual(self.tasks[0]["status"], "review")
        second_id = self.bridge.approve_video(self.body(videoPath="other.mp4", videoSha256=digest(second)))["job"]["id"]
        final = self.finish(second_id)
        final_folder = self.office / final["delivery"]["folder"]
        final_folder.rename(self.office / "approved" / final_folder.name)
        self.bridge.complete_source(self.tasks[-1], {"tasks": self.tasks}, mark)
        self.assertEqual(self.tasks[0]["status"], "done")

    def test_source_frame_unavailable_is_explicit_provenance(self):
        self.template()
        job = self.bridge.approve_video(self.body())["job"]
        self.assertFalse(job["sourceFrameAvailable"])
        self.assertIn("No video frame", job["warnings"][0])
        self.assertFalse(self.engine.jobs[job["id"]]["request"]["provenance"]["sourceFrameAvailable"])

    def server_actions(self):
        tree = ast.parse((Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8"))
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("approve_folder", "_approve_folder", "task_action", "_task_action")]
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Handler")
        funcs.append(next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "do_POST"))
        env = {"os": os, "re": re, "shutil": shutil, "unquote": unquote, "urlparse": urlparse,
               "ROOT": str(self.office), "SAFE_NAME": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$"),
               "TASK_LOCK": threading.Lock(), "load_tasks": lambda: {"tasks": self.tasks}, "save_tasks": lambda db: None,
               "set_status": lambda task, status: task.update(status=status), "thumbnail_design": self.bridge,
               "sermon_design": mock.Mock(handle=lambda h: False), "on_approved": lambda name: None,
               "safe_join": lambda base, name: os.path.join(base, name), "STATUSES": ("todo", "doing", "review", "done")}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), "server-approval-fixture", "exec"), env)
        return env

    def test_folder_and_task_final_approval_share_one_transition(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(ident)
        name = Path(result["delivery"]["folder"]).name
        env = self.server_actions()
        handler = Handler("/api/approve", "POST", {"name": name})
        handler.guard = lambda: True
        handler.read_json = lambda: {"name": name}
        env["do_POST"](handler)
        self.assertEqual(handler.code, 200)
        self.assertEqual([t["status"] for t in self.tasks], ["done", "done"])
        self.assertTrue((self.office / "approved" / name).is_dir())
        env["do_POST"](handler)
        self.assertEqual(handler.code, 200)
        self.assertTrue(handler.payload["alreadyApproved"])
        code, reply = env["task_action"]({"action": "approve", "id": self.tasks[-1]["id"]})
        self.assertEqual(code, 200)
        self.assertTrue(reply["alreadyApproved"])

    def test_folder_final_without_native_task_cannot_move(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(ident)
        name = Path(result["delivery"]["folder"]).name
        self.tasks.pop()
        env = self.server_actions()
        handler = Handler("/api/approve", "POST", {"name": name})
        handler.guard = lambda: True
        handler.read_json = lambda: {"name": name}
        env["do_POST"](handler)
        self.assertEqual(handler.code, 409)
        self.assertTrue((self.office / "out" / name).is_dir())

    def test_explicit_status_get_recovers_delivery_without_model_retry(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        original = (self.folder / "final.mp4").read_bytes()
        (self.folder / "final.mp4").write_bytes(b"temporarily changed fixture")
        self.assertEqual(self.finish(ident)["status"], "delivery-error")
        (self.folder / "final.mp4").write_bytes(original)
        handler = Handler(BASE + "/jobs/" + ident)
        self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["job"]["status"], "delivered")
        self.assertEqual(sum(method == "POST" for method, _ in self.engine.calls), 1)

    def test_task_change_during_frame_preparation_prevents_dispatch(self):
        self.template()
        self.bridge._frame.side_effect = lambda *args: self.tasks[0].update(status="doing")
        with self.assertRaises(DesignError):
            self.bridge.approve_video(self.body())
        self.assertFalse(any(method == "POST" for method, _ in self.engine.calls))
        self.assertFalse(self.bridge._load()["jobs"])

    def test_channel_change_during_frame_preparation_prevents_dispatch(self):
        self.template()
        self.bridge._frame.side_effect = lambda *args: self.tasks[0].update(note="out:video-one channel:pong-gospel")
        with self.assertRaises(DesignError):
            self.bridge.approve_video(self.body())
        self.assertFalse(any(method == "POST" for method, _ in self.engine.calls))

    def test_source_channel_change_blocks_delivery_and_final_approval(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        (self.folder / "channel.txt").write_text("pong-gospel")
        self.assertEqual(self.finish(ident)["status"], "delivery-error")
        (self.folder / "channel.txt").write_text("")
        result = self.bridge.poll(ident)["job"]
        self.assertEqual(result["status"], "delivered")
        (self.folder / "channel.txt").write_text("pong-gospel")
        self.assertIn("changed", self.bridge.guard_approval(Path(result["delivery"]["folder"]).name))

    def test_final_approval_serializes_against_new_revision(self):
        self.template()
        ident = self.bridge.approve_video(self.body())["job"]["id"]
        result = self.finish(ident)
        env = self.server_actions()
        final_task_id = result["delivery"]["taskId"]
        moving, allow_move, initial_source = threading.Event(), threading.Event(), threading.Event()
        original_move, original_source = shutil.move, self.bridge._source
        outcomes = {}
        def move(*args):
            moving.set()
            if not allow_move.wait(3):
                raise RuntimeError("test coordination timeout")
            return original_move(*args)
        def source(*args):
            value = original_source(*args)
            if threading.current_thread().name == "new-thumbnail-revision":
                initial_source.set()
            return value
        def approve():
            outcomes["approval"] = env["task_action"]({"action": "approve", "id": final_task_id})
        def revision():
            try:
                outcomes["revision"] = self.bridge.approve_video(self.body(title="new revision"))
            except DesignError as error:
                outcomes["revision"] = error
        with mock.patch("shutil.move", side_effect=move), mock.patch.object(self.bridge, "_source", side_effect=source):
            a = threading.Thread(target=approve)
            a.start()
            self.assertTrue(moving.wait(3))
            b = threading.Thread(target=revision, name="new-thumbnail-revision")
            b.start()
            self.assertTrue(initial_source.wait(3))
            allow_move.set()
            a.join(4); b.join(4)
            self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(outcomes["approval"][0], 200)
        self.assertIsInstance(outcomes["revision"], DesignError)
        self.assertEqual(sum(method == "POST" for method, _ in self.engine.calls), 1)


if __name__ == "__main__":
    unittest.main()
