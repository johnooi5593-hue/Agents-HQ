"""Isolated manual-post contract tests. No live HQ or image-generation calls."""
import base64
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import test_thumbnail_design as video_tests
from test_thumbnail_design import Channels, Engine, PNG
from test_sermon_design import Handler
from thumbnail_design import BASE, ThumbnailDesignBridge, DesignError, digest


def png(width=1080, height=1440, color=42):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    data = zlib.compress((b"\x00" + bytes([color, color, color]) * width) * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


class PostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.office, self.runtime = self.root / "office", self.root / "runtime"
        self.office.mkdir(); self.runtime.mkdir()
        self.tasks = [{"id": "t1", "status": "review", "note": "out:unrelated-video", "title": "Video awaiting OK"}]
        self.engine = Engine(self.runtime)
        self.bridge = ThumbnailDesignBridge(self.office, self.engine, Channels(), self.add_task, lambda: {"tasks": self.tasks}, auto_watch=False)
        self.template_id = self.template()
    def tearDown(self):
        self.bridge.stop.set(); self.temp.cleanup()
    def add_task(self, body):
        row = dict(body, id="t" + str(len(self.tasks) + 1)); self.tasks.append(row)
        return 201, {"added": row}
    def template(self, channel=""):
        self.bridge.save_template({"channel": channel, "name": "Brand template", "dataUrl": "data:image/png;base64," + base64.b64encode(PNG).decode(), "width": 1080, "height": 1440})
        return next(c["defaultTemplateId"] for c in self.bridge.config()["channels"] if c["key"] == channel)
    def body(self, **updates):
        return {"channel": "", "templateId": self.template_id, "title": "准确标题", "subtitle": "Exact subtitle", "instructions": "Preserve the original subject", "width": 1080, "height": 1440, "idempotencyKey": "post-click-1"} | updates
    def start(self, **updates):
        return self.bridge.create_post(self.body(**updates))["job"]["id"]
    def output(self, ident, width=1080, height=1440):
        job = self.engine.jobs[ident]
        folder = self.runtime / ".studio" / "thumbnail-design" / "jobs" / ident / "output"; folder.mkdir(parents=True)
        files = []
        for i in range(1, 5):
            file = folder / ("thumbnail-option-" + str(i) + ".png"); file.write_bytes(png(width, height, i * 30))
            files.append({"name": file.name, "path": str(file), "size": file.stat().st_size, "sha256": digest(file)})
        file = folder / "thumbnail-manifest.json"; file.write_text(json.dumps({"provenance": job["request"]["provenance"]}))
        files.append({"name": file.name, "path": str(file), "size": file.stat().st_size, "sha256": digest(file)})
        job.update(status="succeeded", progress=100, files=files)
    def finish(self, ident):
        self.output(ident)
        return self.bridge.poll(ident)["job"]
    def select(self, job, index=0, **updates):
        option = job["options"][index]
        return self.bridge.select_option({"jobId": job["id"], "optionName": option["name"], "expectedHash": option["sha256"]} | updates)

    def test_config_and_empty_main_channel_history_are_read_only(self):
        handler = Handler(BASE + "/config"); self.bridge.handle(handler)
        self.assertTrue(all(handler.payload[k] for k in ("postCreation", "optionSelection", "jobHistory")))
        self.assertFalse(self.engine.calls)
        ident = self.start()
        pong = self.template("pong-gospel")
        other = self.start(channel="pong-gospel", templateId=pong, idempotencyKey="other-post")
        handler = Handler(BASE + "/jobs?channel="); self.bridge.handle(handler)
        self.assertEqual([j["id"] for j in handler.payload["jobs"]], [ident])
        handler = Handler(BASE + "/jobs?channel=no-such-channel"); self.bridge.handle(handler)
        self.assertEqual(handler.code, 400)
        self.assertNotEqual(ident, other)

    def test_create_post_freezes_true_post_provenance_before_only_dispatch(self):
        original = self.engine._request
        def dispatch(method, route, payload=None, headers=None):
            if method == "POST":
                request = json.loads(payload)
                ledger = self.bridge._load()["jobs"][request["requestId"]]
                self.assertEqual(ledger["status"], "dispatching")
                self.assertTrue((self.bridge.base / "requests" / request["requestId"] / "request.json").is_file())
            return original(method, route, payload, headers)
        with mock.patch.object(self.engine, "_request", side_effect=dispatch):
            ident = self.start()
        request = self.engine.jobs[ident]["request"]
        self.assertEqual(request["provenance"]["mode"], "post")
        self.assertNotIn("approvedAt", request["provenance"])
        self.assertNotIn("videoSha256", request["provenance"])
        self.assertEqual(request["title"], "准确标题")
        self.assertEqual(self.bridge.create_post(self.body())["job"]["id"], ident)
        with self.assertRaisesRegex(DesignError, "different post"):
            self.bridge.create_post(self.body(title="changed"))
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 1)
        self.assertEqual(self.tasks[0]["status"], "review")

    def test_source_reference_frozen_and_not_mislabeled_video(self):
        source = {"name": "speaker.png", "dataUrl": "data:image/png;base64," + base64.b64encode(PNG).decode()}
        ident = self.start(sourceImage=source)
        row = self.bridge._load()["jobs"][ident]
        self.assertEqual(Path(row["sourceImagePath"]).read_bytes(), PNG)
        self.assertEqual(self.engine.jobs[ident]["request"]["sourceFrame"], source)
        Path(row["sourceImagePath"]).write_bytes(b"changed")
        self.assertEqual(self.finish(ident)["status"], "delivery-error")
        self.assertEqual(len(self.tasks), 1)

    def test_four_real_canvas_files_deliver_and_require_selection_then_user_ok(self):
        ident = self.start(); job = self.finish(ident)
        self.assertEqual(job["status"], "delivered")
        self.assertEqual(len(job["options"]), 4)
        folder = self.office / job["delivery"]["folder"]
        self.assertEqual(len(list(folder.glob("*.png"))), 4)
        self.assertFalse(list(folder.glob("*.mp4")))
        self.assertEqual(json.loads((folder / "thumbnail-final.json").read_text())["mode"], "post")
        self.assertIn("Choose one", self.bridge.guard_approval(folder.name))
        chosen = self.select(job, 2)
        self.assertEqual(chosen["job"]["selectedOption"], "thumbnail-option-3.png")
        self.assertFalse(chosen["selection"]["approved"])
        self.assertIsNone(self.bridge.guard_approval(folder.name))
        self.bridge.poll(ident)
        self.assertEqual(len(self.tasks), 2)
        self.assertTrue(all(t["status"] == "review" for t in self.tasks))
        self.assertEqual(job["reviewUrl"], "/?task=t2")

    def test_download_and_head_serve_verified_images_and_not_arbitrary_files(self):
        job = self.finish(self.start()); option = job["options"][0]
        handler = Handler(option["downloadUrl"]); self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.wfile.getvalue(), png(color=30))
        self.assertIn("attachment", handler.response_headers["Content-Disposition"])
        self.assertEqual(handler.response_headers["Content-Type"], "image/png")
        handler = Handler(option["url"], "HEAD"); self.bridge.handle(handler)
        self.assertEqual(handler.code, 200); self.assertEqual(handler.wfile.getvalue(), b"")
        self.assertEqual(int(handler.response_headers["Content-Length"]), len(png(color=30)))
        for path in ("thumbnail-final.json", "../thumbnail-final.json", "thumbnail-option-5.png"):
            handler = Handler(BASE + "/jobs/" + job["id"] + "/options/" + path); self.bridge.handle(handler)
            self.assertEqual(handler.code, 404)

    def test_selection_rejects_stale_cross_channel_and_non_option(self):
        job = self.finish(self.start())
        for patch in ({"expectedHash": "0" * 64}, {"channel": "pong-gospel"}, {"optionName": "thumbnail-final.json"}, {"optionName": "../thumbnail-option-1.png"}):
            with self.assertRaises(DesignError):
                self.select(job, **patch)
        self.assertIsNone(self.bridge._load()["jobs"][job["id"]].get("selection"))
        folder = self.office / job["delivery"]["folder"]
        (folder / "thumbnail-option-1.png").write_bytes(png(color=99))
        with self.assertRaisesRegex(DesignError, "changed"):
            self.select(job)
        handler = Handler(job["options"][0]["url"]); self.bridge.handle(handler)
        self.assertEqual(handler.code, 409)

    def test_selection_receipt_tampering_blocks_native_approval(self):
        job = self.finish(self.start()); self.select(job)
        folder = self.office / job["delivery"]["folder"]
        (folder / "thumbnail-selection.json").write_text("{}")
        self.assertIn("changed", self.bridge.guard_approval(folder.name))

    def test_native_final_ok_completes_only_post_task_and_keeps_downloads(self):
        job = self.finish(self.start()); self.select(job)
        env = video_tests.ThumbnailTests.server_actions(self)
        code, reply = env["task_action"]({"action": "approve", "id": job["delivery"]["taskId"]})
        self.assertEqual(code, 200)
        self.assertEqual([t["status"] for t in self.tasks], ["review", "done"])
        handler = Handler(job["options"][0]["downloadUrl"]); self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
        with self.assertRaisesRegex(DesignError, "already approved"):
            self.select(job, 1)

    def test_bad_dimensions_brief_provenance_and_outside_paths_never_deliver(self):
        for variant in ("dimensions", "brief", "provenance", "path"):
            with self.subTest(variant=variant):
                ident = self.start(idempotencyKey="case-" + variant)
                self.output(ident, width=1920 if variant == "dimensions" else 1080)
                job = self.engine.jobs[ident]
                if variant == "brief": job["request"]["title"] = "wrong"
                if variant == "provenance": job["request"]["provenance"]["channel"] = "pong-gospel"
                if variant == "path": job["files"][0]["path"] = str(self.root / "outside.png")
                self.assertEqual(self.bridge.poll(ident)["job"]["status"], "delivery-error")
                self.assertEqual(len(self.tasks), 1)
                # End the fixture job explicitly to test the next independent rejection.
                data = self.bridge._load(); data["jobs"][ident]["status"] = "failed"; self.bridge._save(data)

    def test_transport_uncertainty_cannot_replay_even_when_retry_requested(self):
        original = self.engine._request
        def lost(method, *args):
            result = original(method, *args)
            if method == "POST": raise OSError("lost response after acceptance")
            return result
        with mock.patch.object(self.engine, "_request", side_effect=lost):
            ident = self.start()
            self.assertEqual(self.bridge._load()["jobs"][ident]["status"], "uncertain")
            self.assertEqual(self.bridge.create_post(self.body(retry=True))["job"]["id"], ident)
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 1)
        self.assertEqual(self.bridge.poll(ident)["job"]["status"], "watching")

    def test_known_rejection_requires_explicit_new_retry(self):
        self.engine.reject = 409
        first = self.start()
        self.assertEqual(self.bridge._load()["jobs"][first]["status"], "failed")
        self.engine.reject = None
        self.assertEqual(self.start(), first)
        second = self.start(retry=True)
        self.assertNotEqual(first, second)
        self.assertEqual(self.start(), second)
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 2)

    def test_frozen_template_and_returned_manifest_tampering_stay_blocked(self):
        ident = self.start()
        row = self.bridge._load()["jobs"][ident]
        Path(row["frozenTemplatePath"]).write_bytes(b"changed")
        self.assertEqual(self.finish(ident)["status"], "delivery-error")
        self.assertEqual(len(self.tasks), 1)

    def test_channel_template_and_source_validation_precede_model_dispatch(self):
        other = self.template("pong-gospel")
        for patch in ({"templateId": other}, {"channel": "NLRCC"}, {"width": True}, {"sourceImage": {"name": "bad.png", "dataUrl": "data:image/png;base64,YmFk"}}):
            with self.assertRaises(DesignError):
                self.bridge.create_post(self.body(**patch))
        self.assertFalse(self.engine.calls)


if __name__ == "__main__":
    unittest.main()
