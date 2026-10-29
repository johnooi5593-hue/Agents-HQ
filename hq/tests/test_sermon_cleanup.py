import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sermon_cleanup import plan_cleanup, execute_cleanup, atomic_json
import sermon_cleanup
from sermon_design import SermonDesignBridge, BASE
from test_sermon_design import Handler


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hq, self.runtime = self.root / "hq", self.root / "runtime"
        (self.hq / "hq").mkdir(parents=True)
        self.runtime.mkdir()
        self.index = {"version": 1, "deliveries": {}}
        self.tasks = {"tasks": [], "deleted": []}
    def tearDown(self):
        self.temp.cleanup()
    def save(self):
        atomic_json(self.hq / "hq/sermon-project-links.json", self.index)
        atomic_json(self.hq / "hq/tasks.json", self.tasks)
    def delivery(self, pid="p1", purged=True, area="out"):
        folder = f"sermon-studio-{pid}-r3-a1"
        directory = self.hq / area / folder
        directory.mkdir(parents=True)
        data = b"generated delivery copy"
        (directory / "picture.png").write_bytes(data)
        (directory / "README.md").write_text("# Sermon Design Studio delivery\n\nNative Resvg/Sharp renderer; fixture\n\nProject: " + pid + "\nRevision: 3\n", encoding="utf-8")
        task = "t" + pid
        self.index["deliveries"][pid + ":3:1"] = {"projectId": pid, "revision": 3, "attempt": 1, "taskId": task, "folder": folder, "files": [{"name": "picture.png", "path": ".studio/jobs/x/picture.png", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
        self.tasks["tasks"].append({"id": task, "note": "out:" + folder, "status": "review"})
        if purged:
            atomic_json(self.runtime / ".studio/sermon-design/purged" / (pid + ".json"), {"version": 1, "projectId": pid, "status": "purged"})
        self.save()
        return directory
    def test_exact_receipted_copies_removed_but_active_originals_and_unrelated_are_kept(self):
        old = self.delivery()
        active = self.delivery("active", False)
        source = self.runtime / "original.png"; source.write_bytes(b"original")
        unrelated = self.hq / "out/thumbnail-final-other"; unrelated.mkdir(); (unrelated / "keep.png").write_bytes(b"keep")
        plan = plan_cleanup(self.hq, self.runtime)
        self.assertEqual(plan["fileCount"], 2)
        result = execute_cleanup(self.hq, self.runtime, plan)
        self.assertEqual(result["status"], "purged")
        self.assertFalse(old.exists()); self.assertTrue(active.exists()); self.assertEqual(source.read_bytes(), b"original"); self.assertTrue(unrelated.exists())
        db = json.loads((self.hq / "hq/tasks.json").read_text())
        self.assertEqual([t["id"] for t in db["tasks"]], ["tactive"])
        self.assertTrue(db["deleted"][0]["studioPermanentlyDeleted"])
        self.assertEqual(plan_cleanup(self.hq, self.runtime)["folders"], [])
    def test_changed_unknown_shared_and_approved_copies_are_blocked(self):
        unknown = self.delivery("unknown"); (unknown / "my-original.png").write_bytes(b"user file")
        changed = self.delivery("changed"); (changed / "picture.png").write_bytes(b"modified")
        shared = self.delivery("shared"); self.tasks["tasks"].append({"id": "foreign", "note": "out:" + shared.name})
        approved = self.delivery("approved", area="approved")
        self.save()
        preview = plan_cleanup(self.hq, self.runtime)
        self.assertEqual(len(preview["kept"]), 4); self.assertEqual(preview["folders"], [])
        self.assertTrue(unknown.exists()); self.assertTrue(changed.exists()); self.assertTrue(shared.exists()); self.assertTrue(approved.exists())
    def test_stale_scope_or_file_hash_rejected_before_unlink(self):
        directory = self.delivery()
        preview = plan_cleanup(self.hq, self.runtime)
        (directory / "picture.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed since"):
            execute_cleanup(self.hq, self.runtime, preview)
        self.assertTrue((directory / "README.md").exists())
    def test_missing_folder_reconciles_with_zero_freed_bytes_and_task_error_retries(self):
        directory = self.delivery()
        for file in directory.iterdir(): file.unlink()
        directory.rmdir()
        preview = plan_cleanup(self.hq, self.runtime)
        result = execute_cleanup(self.hq, self.runtime, preview, lambda body: (503, {}))
        self.assertEqual(result["status"], "partial"); self.assertEqual(result["deletedBytes"], 0)
        again = plan_cleanup(self.hq, self.runtime)
        self.assertEqual(len(again["folders"]), 1)
        result = execute_cleanup(self.hq, self.runtime, again, lambda body: (200, {}))
        self.assertEqual(result["status"], "purged"); self.assertEqual(plan_cleanup(self.hq, self.runtime)["folders"], [])
    def test_partial_engine_purge_and_live_current_project_never_release_copy(self):
        directory = self.delivery()
        atomic_json(self.runtime / ".studio/sermon-design/projects/p1/project.json", {"id": "p1"})
        self.assertEqual(plan_cleanup(self.hq, self.runtime)["folders"], [])
        self.assertTrue(directory.exists())
    def test_task_update_during_file_cleanup_is_preserved_and_retry_syncs_only_linked_card(self):
        directory = self.delivery()
        preview = plan_cleanup(self.hq, self.runtime)
        file_record = sermon_cleanup.file_record
        injected = False
        count = 0
        def check(root, file):
            nonlocal injected
            nonlocal count
            if Path(file).name == "picture.png": count += 1
            if Path(file).name == "picture.png" and count == 2 and not injected:
                injected = True
                # File work does not hold the board lock. A concurrent app update wins.
                self.assertFalse((self.hq / "hq/tasks.lock").exists())
                db = json.loads((self.hq / "hq/tasks.json").read_text())
                db["tasks"].append({"id": "new-task", "note": "unrelated"})
                atomic_json(self.hq / "hq/tasks.json", db)
            return file_record(root, file)
        with mock.patch.object(sermon_cleanup, "file_record", check):
            result = execute_cleanup(self.hq, self.runtime, preview)
        self.assertTrue(injected)
        self.assertEqual(result["status"], "partial")
        self.assertGreater(result["deletedBytes"], 0)
        db = json.loads((self.hq / "hq/tasks.json").read_text())
        self.assertEqual(len(db["tasks"]), 2)
        result = execute_cleanup(self.hq, self.runtime, plan_cleanup(self.hq, self.runtime))
        self.assertEqual(result["status"], "purged")
        self.assertEqual([row["id"] for row in json.loads((self.hq / "hq/tasks.json").read_text())["tasks"]], ["new-task"])
    def test_bridge_direct_engine_reconciliation_and_stale_registration_keep_tombstone(self):
        directory = self.delivery()
        bridge = SermonDesignBridge(self.hq, lambda body: (200, {}), lambda: self.tasks, runtime_root=self.runtime, engine_root=self.root, auto_start=False)
        try:
            stale = bridge._index()
            result = bridge.reconcile_purged_deliveries()
            self.assertEqual(result["status"], "purged"); self.assertFalse(directory.exists())
            stale["deliveries"]["new"] = {"projectId": "new", "folder": "sermon-studio-new-r1-a1", "taskId": "tnew", "files": [{"name": "a", "path": "a", "size": 1, "sha256": "a" * 64}]}
            bridge._save_index(stale)
            self.assertEqual(bridge._index()["deliveries"]["p1:3:1"]["cleanup"]["status"], "purged")
            self.assertIn("new", bridge._index()["deliveries"])
        finally:
            bridge.stop_delivery_watcher()
    def test_busy_offline_board_after_copy_removal_keeps_actual_counts_and_pending_audit(self):
        directory = self.delivery()
        preview = plan_cleanup(self.hq, self.runtime)
        with mock.patch.object(sermon_cleanup, "board_lock", side_effect=ValueError("busy board")):
            result = execute_cleanup(self.hq, self.runtime, preview)
        self.assertFalse(directory.exists())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deletedFiles"], 2)
        self.assertGreater(result["deletedBytes"], 0)
        audit = json.loads(Path(result["receiptPath"]).read_text())
        self.assertEqual(audit["deletedBytes"], result["deletedBytes"])
        index = json.loads((self.hq / "hq/sermon-project-links.json").read_text())
        self.assertTrue(index["deliveries"]["p1:3:1"]["cleanup"]["taskRemovalPending"])
    def test_proxy_hook_only_runs_after_actual_confirmed_purge_ids(self):
        directory = self.delivery()
        payload = {"weekPurge": {"status": "purged", "purgedProjectIds": ["p1"]}}
        def request(method, route, data, headers):
            if route == "/api/runtime":
                value = {"app": "sermon-design-engine", "workspaceRoot": str(self.runtime), "sourceRoot": str(self.root)}
            elif route == BASE + "/capabilities":
                value = {"dimensions": {"title": [3840, 2160]}, "defaultProvider": "codex", "providers": [{"id": "codex"}]}
            else: value = payload
            return 200, {"Content-Type": "application/json"}, json.dumps(value).encode()
        bridge = SermonDesignBridge(self.hq, lambda body: (200, {}), lambda: self.tasks, runtime_root=self.runtime, engine_root=self.root, auto_start=False, request=request)
        try:
            # Disable the independent reconciler here to isolate the POST release hook.
            with mock.patch.object(bridge, "resume_pending"):
                handler = Handler(BASE + "/projects/p1", "POST", {"management": {"action": "preview-week-purge"}})
                bridge.handle(handler); self.assertTrue(directory.exists()); self.assertNotIn("hqCleanup", handler.payload)
                handler = Handler(BASE + "/projects/p1", "POST", {"management": {"action": "purge-week", "token": "checked"}})
                bridge.handle(handler); self.assertFalse(directory.exists()); self.assertEqual(handler.payload["hqCleanup"]["status"], "purged")
        finally: bridge.stop_delivery_watcher()


if __name__ == "__main__": unittest.main()
