import copy
import hashlib
import json
import sys
import time
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
    def test_retry_refuses_bool_string_and_float_job_revision_spoofs(self):
        current = self.project(); current["revision"] = 1
        current["lastExport"]["projectRevision"] = 1
        for revision in (True, "1", 1.0):
            self.wire(current, job={"id": "job-one", "status": "succeeded", "projectId": current["id"], "projectRevision": revision})
            with self.assertRaisesRegex(DesignError, "assigned image job"):
                self.bridge.retry_delivery("project-one", {"expectedRevision": 1, "projectRevision": 1, "jobId": "job-one"})
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
        self.assertEqual(handler.payload["delivery"]["projectId"], project["id"])
        self.assertEqual(handler.payload["delivery"]["projectRevision"], 4)

    def job_payload(self, project, revision=4, status="succeeded", job_id="job-one"):
        return {"job": {"id": job_id, "projectId": project["id"], "status": status, "completedImages": 4, "totalImages": 4, "projectRevision": revision}, "project": copy.deepcopy(project)}

    def poll(self, payload, job_id="job-one"):
        self.fixture.reply = copy.deepcopy(payload)
        handler = fixtures.Handler(BASE + "/jobs/" + job_id)
        self.bridge.handle(handler)
        return handler

    def test_succeeded_job_explicitly_acknowledges_exact_delivery_and_is_idempotent(self):
        project = self.project()
        first = self.poll(self.job_payload(project))
        second = self.poll(self.job_payload(project))
        self.assertEqual(first.code, 200)
        self.assertEqual(first.payload["delivery"], second.payload["delivery"])
        self.assertEqual(first.payload["delivery"]["status"], "delivered")
        self.assertEqual(first.payload["delivery"]["projectRevision"], 4)
        self.assertEqual(first.payload["delivery"]["taskId"], "t1")
        self.assertEqual(first.payload["project"]["hqTaskId"], "t1")
        self.assertEqual(len(self.fixture.tasks), 1)
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.calls))

    def test_two_jobs_of_same_project_never_collect_each_others_revision(self):
        old = self.project(); latest = copy.deepcopy(old)
        latest.update(revision=8, titles={"chinese": "New exact title"})
        latest["lastExport"]["projectRevision"] = 8
        upstream = self.fixture.upstream
        calls = self.fixture.calls
        def request(method, route, data, headers):
            if route == BASE + "/projects/project-one?revision=4":
                calls.append((method, route, data, headers))
                return 200, {"Content-Type": "application/json"}, json.dumps({"project": old}).encode()
            return upstream(method, route, data, headers)
        self.bridge.request_impl = request
        first = self.poll(self.job_payload(latest, revision=4))
        second = self.poll(self.job_payload(latest, revision=8, job_id="job-two"), "job-two")
        self.assertEqual((first.code, second.code), (200, 200))
        self.assertEqual(first.payload["delivery"]["projectRevision"], 4)
        self.assertEqual(second.payload["delivery"]["projectRevision"], 8)
        self.assertNotEqual(first.payload["hqTaskId"], second.payload["hqTaskId"])
        self.assertEqual(self.fixture.tasks[0]["title"], "Sermon Title 16:9 · 认识神的声音")
        self.assertEqual(self.fixture.tasks[1]["title"], "Sermon Title 16:9 · New exact title")
        self.assertEqual(first.payload["project"]["titles"]["chinese"], "New exact title")
        self.assertIsNone(first.payload["project"]["hqTaskId"])
        self.assertTrue(all(call[0] == "GET" for call in calls))

    def test_running_failed_cancelled_jobs_never_collect_prior_or_latest_export(self):
        project = self.project()
        with mock.patch.object(self.bridge, "register") as register:
            for status in ("queued", "running", "failed", "cancelled", "canceled"):
                handler = self.poll(self.job_payload(project, status=status))
                self.assertEqual(handler.code, 200)
                self.assertNotIn("delivery", handler.payload)
                self.assertIsNone(handler.payload["project"]["hqTaskId"])
            register.assert_not_called()

    def test_unconfirmed_revision_never_binds_current_draft_or_registers_it(self):
        project = self.project()
        for revision in (None, True, 0, "4"):
            with mock.patch.object(self.bridge, "register") as register:
                handler = self.poll(self.job_payload(project, revision=revision))
                self.assertEqual(handler.code, 200)
                self.assertEqual(handler.payload["job"]["status"], "succeeded")
                self.assertEqual(handler.payload["delivery"]["status"], "failed")
                self.assertNotIn("projectRevision", handler.payload["delivery"])
                register.assert_not_called()
        handler = fixtures.Handler(BASE + "/jobs/job-one")
        with mock.patch.object(self.bridge, "ensure_engine", side_effect=DesignError("unavailable", 502)):
            self.bridge.handle(handler)
        self.assertNotIn("projectRevision", handler.payload["delivery"])
        self.assertNotIn("projectId", handler.payload["delivery"])

    def test_notification_failure_does_not_downgrade_committed_delivery(self):
        project = self.project()
        self.bridge.notify = mock.Mock(side_effect=TypeError("fixture display disconnected"))
        one = self.poll(self.job_payload(project))
        two = self.poll(self.job_payload(project))
        self.assertEqual(one.payload["delivery"]["status"], "delivered")
        self.assertEqual(two.payload["delivery"]["taskId"], one.payload["delivery"]["taskId"])
        self.assertIn("TypeError", self.bridge.notification_error)
        self.assertEqual(len(self.fixture.tasks), 1)
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.calls))

    def test_verified_refresh_reconciles_delivery_error_or_expired_but_not_failed_watch(self):
        project = self.project()
        for status in ("delivery-error", "expired", "failed"):
            now = time.time()
            self.bridge._save_pending({"version": 1, "jobs": {"job-one": {"jobId": "job-one", "projectId": project["id"], "status": status, "queuedAt": now, "deadlineAt": now + 100, "lastError": "old collection error"}}})
            handler = self.poll(self.job_payload(project))
            self.assertEqual(handler.payload["delivery"]["status"], "delivered")
            row = self.bridge._pending()["jobs"]["job-one"]
            self.assertEqual(row["status"], "failed" if status == "failed" else "delivered")
            if status != "failed":
                self.assertNotIn("lastError", row)
                self.assertEqual(row["projectRevision"], 4)
        self.assertEqual(len(self.fixture.tasks), 1)

    def test_later_cancelled_deleted_or_failed_project_is_not_revived_by_old_job(self):
        project = self.project()
        with mock.patch.object(self.bridge, "register") as register:
            for status in ("cancelled", "canceled", "failed"):
                current = copy.deepcopy(project); current["status"] = status
                handler = self.poll(self.job_payload(current))
                self.assertEqual(handler.payload["delivery"]["status"], "failed")
            current = copy.deepcopy(project); current["deletedAt"] = "2026-11-05"
            handler = self.poll(self.job_payload(current))
            self.assertFalse(handler.payload["delivery"]["retryable"])
            register.assert_not_called()

    def test_retry_response_preserves_confirmed_job_binding_after_io_failure(self):
        project = self.project()
        self.wire(project, job=self.job_payload(project)["job"])
        body = {"expectedRevision": 4, "projectRevision": 4, "jobId": "job-one"}
        handler = fixtures.Handler(BASE + "/projects/project-one/delivery", "POST", body)
        with mock.patch.object(self.bridge, "register", side_effect=OSError("copy fixture")):
            self.bridge.handle(handler)
        self.assertEqual(handler.code, 502)
        self.assertEqual(handler.payload["delivery"]["projectRevision"], 4)
        self.assertEqual(handler.payload["delivery"]["projectId"], project["id"])
        self.assertTrue(handler.payload["delivery"]["retryable"])
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.calls))

    def test_four_pictures_survive_oversized_duplicate_source_delivery(self):
        project = self.project(); rows = project["lastExport"]["files"]
        original = rows[0]; folder = Path(original["path"]).parent
        for number in range(2, 5):
            name = "Sermon_Title_Design_%02d.png" % number
            target = folder / name; target.write_bytes(fixtures.PNG_FIXTURE)
            rows.append({**original, "name": name, "path": str(target)})
        png_total = sum(row["size"] for row in rows if row["format"] == "png")
        with mock.patch.object(sermon_design, "COPY_LIMIT", png_total):
            handler = self.poll(self.job_payload(project))
        self.assertEqual(handler.payload["delivery"]["status"], "delivered")
        delivery = next(iter(self.bridge._index()["deliveries"].values()))
        self.assertEqual(delivery["deliveryMode"], "pictures-first")
        self.assertEqual(len(delivery["files"]), 4)
        for row in delivery["files"]:
            actual = self.fixture.office / "out" / delivery["folder"] / row["name"]
            self.assertEqual(hashlib.sha256(actual.read_bytes()).hexdigest(), row["sha256"])
        self.assertEqual(len(delivery["sourceFiles"]), 2)
        self.assertTrue(all(Path(row["path"]).is_file() for row in rows))
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.calls))
    def test_cancelled_review_task_and_durable_purge_marker_never_recreate_delivery(self):
        project = self.project(); delivery = self.bridge.register(project)
        self.fixture.tasks[0]["status"] = "cancelled"
        with self.assertRaisesRegex(DesignError, "cancelled"):
            self.bridge.register(project)
        marker = self.bridge.runtime_root / ".studio/sermon-design/purged/project-one.json"
        marker.parent.mkdir(parents=True); marker.write_text('{"projectId":"project-one","status":"purged"}')
        with self.assertRaisesRegex(DesignError, "Permanent deletion"):
            self.bridge.register(project)
        self.assertEqual(len(self.fixture.tasks), 1)


if __name__ == "__main__": unittest.main()
