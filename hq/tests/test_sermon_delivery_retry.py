import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sermon_design
import test_sermon_design as fixtures
from sermon_design import BASE, DesignError


class DeliveryRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BridgeTests()
        self.fixture.setUp()
        self.bridge = self.fixture.bridge
    def tearDown(self): self.fixture.tearDown()
    def project(self): return self.fixture.project()
    def test_oversized_source_duplicates_copy_final_png_and_keep_downloadable_source_manifest(self):
        project = self.project()
        total = sum(row["size"] for row in project["lastExport"]["files"])
        with mock.patch.object(sermon_design, "COPY_LIMIT", total - 1):
            first = self.bridge.register(project)
            self.assertEqual(first["deliveryMode"], "pictures-first")
            self.assertEqual([row["name"] for row in first["files"]], ["Sermon_Title_Design_01.png"])
            self.assertEqual(len(first["sourceFiles"]), 2)
            self.assertTrue(first["warnings"])
            self.assertEqual(self.bridge.register(copy.deepcopy(project))["taskId"], first["taskId"])
        self.assertEqual(len(self.fixture.tasks), 1)
        source = first["sourceFiles"][0]
        handler = fixtures.Handler(BASE + "/download?path=" + source["path"])
        self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
    def test_final_png_exceeds_copy_bound_is_not_discarded(self):
        project = self.project()
        with mock.patch.object(sermon_design, "COPY_LIMIT", 1):
            with self.assertRaisesRegex(DesignError, "pictures exceed"):
                self.bridge.register(project)
        self.assertEqual(self.fixture.tasks, [])
    def test_corrupt_required_png_not_skipped_even_when_hash_matches(self):
        project = self.project(); row = project["lastExport"]["files"][0]
        data = b"not a real PNG"; Path(row["path"]).write_bytes(data)
        row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(DesignError, "required PNG artwork is corrupt"):
            self.bridge.register(project)
        self.assertEqual(self.fixture.tasks, [])
    def wire(self, current, frozen=None, job=None, job_code=200):
        upstream = self.fixture.upstream
        def request(method, route, data, headers):
            if route == BASE + "/projects/project-one": value, code = {"project": copy.deepcopy(current)}, 200
            elif route == BASE + "/projects/project-one?revision=4": value, code = {"project": copy.deepcopy(frozen)}, 200
            elif route == BASE + "/jobs/job-one": value, code = {"job": copy.deepcopy(job)}, job_code
            else: return upstream(method, route, data, headers)
            self.fixture.calls.append((method, route, data, headers))
            return code, {"Content-Type": "application/json"}, json.dumps(value).encode()
        self.bridge.request_impl = request
    def test_retry_only_collects_exact_frozen_export_and_is_idempotent(self):
        frozen = self.project(); current = copy.deepcopy(frozen)
        current.update(revision=8, titles={"chinese": "Later draft"})
        self.wire(current, frozen, {"id": "job-one", "status": "succeeded", "projectId": current["id"], "projectRevision": 4})
        body = {"deliveryAction": "retry", "expectedRevision": 8, "projectRevision": 4, "jobId": "job-one"}
        one = self.bridge.retry_delivery("project-one", body)
        two = self.bridge.retry_delivery("project-one", body)
        self.assertEqual(one["delivery"]["projectRevision"], 4)
        self.assertEqual(one["hqTaskId"], two["hqTaskId"])
        self.assertEqual(one["project"]["titles"]["chinese"], "Later draft")
        self.assertEqual(self.fixture.tasks[0]["title"], "Sermon Title 16:9 · 认识神的声音")
        self.assertFalse(any(call[0] != "GET" for call in self.fixture.calls))
    def test_retry_refuses_unknown_running_failed_cancelled_or_wrong_job_revision(self):
        current = self.project()
        for status, code, revision in [("running", 200, 4), ("failed", 200, 4), ("cancelled", 200, 4), ("succeeded", 404, 4), ("succeeded", 200, 3)]:
            self.wire(current, job={"id": "job-one", "status": status, "projectId": current["id"], "projectRevision": revision}, job_code=code)
            with self.assertRaisesRegex(DesignError, "assigned image job"):
                self.bridge.retry_delivery("project-one", {"expectedRevision": 4, "projectRevision": 4, "jobId": "job-one"})
        self.assertEqual(self.fixture.tasks, [])
    def test_retry_requires_explicit_revision_and_refuses_mixed_generation_or_deleted_project(self):
        current = self.project(); self.wire(current)
        for body in [{"expectedRevision": 4}, {"expectedRevision": 4, "projectRevision": 4, "useAi": True}]:
            with self.assertRaises(DesignError): self.bridge.retry_delivery("project-one", body)
        current["deletedAt"] = "2026-10-29"; self.wire(current)
        with self.assertRaisesRegex(DesignError, "deleted, cancelled"):
            self.bridge.retry_delivery("project-one", {"expectedRevision": 4, "projectRevision": 4})
        self.assertEqual(self.fixture.tasks, [])
    def test_succeeded_job_delivery_failure_is_not_generation_failure(self):
        project = self.project()
        self.fixture.reply = {"job": {"id": "job-one", "projectId": project["id"], "status": "succeeded", "completedImages": 4, "totalImages": 4, "projectRevision": 4}, "project": project}
        handler = fixtures.Handler(BASE + "/jobs/job-one")
        with mock.patch.object(self.bridge, "register", side_effect=DesignError("copy failed", 502)):
            self.bridge.handle(handler)
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["job"]["status"], "succeeded")
        self.assertEqual(handler.payload["delivery"]["status"], "failed")
        self.assertEqual(handler.payload["job"]["completedImages"], 4)


if __name__ == "__main__": unittest.main()
