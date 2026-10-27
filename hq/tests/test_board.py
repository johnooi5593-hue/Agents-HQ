import ast
import datetime
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

# The board actions straight from server.py (importing it would start the office), with an in-memory board.
SERVER = Path(__file__).resolve().parents[1] / "server.py"


class Channels:
    def get(self, key):
        return {"key": ""} if not key else ({"key": key} if key == "pong-gospel" else None)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        names = {"normalize_task", "set_status", "clean_progress", "clean_date", "clean_time", "safe_join", "task_channel", "_task_action"}
        body = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("STATUSES", "KINDS", "TASK_DEFAULTS", "OFFICE", "FOOTAGE", "DATE_RE", "TIME_RE") for t in n.targets)]
        body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.db = {"tasks": []}
        self.env = {"re": re, "os": os, "datetime": datetime, "ROOT": str(self.root), "channels": Channels(), "TASK_LOCK": __import__("threading").Lock(),
                    "load_tasks": lambda: self.db, "save_tasks": lambda db: None, "now_iso": lambda: "2026-10-27T00:00:00Z"}
        exec(compile(ast.Module(body=body, type_ignores=[]), "server-board-fixture", "exec"), self.env)
        self.act = self.env["_task_action"]

    def tearDown(self):
        self.temp.cleanup()

    def add(self, **body):
        return self.act({"action": "add", "title": "x", **body})[1]["added"]

    def test_channel_is_worked_out_and_can_be_chosen(self):
        ch = self.env["task_channel"]
        (self.root / "out" / "pong-clip").mkdir(parents=True)
        (self.root / "out" / "pong-clip" / "channel.txt").write_text("pong-gospel", encoding="utf-8")
        (self.root / "out" / "main-clip").mkdir(parents=True)
        self.assertEqual(ch(self.add(note="out:pong-clip")), "pong-gospel")
        self.assertEqual(ch(self.add(note="out:main-clip")), "")           # a folder without channel.txt: the main channel
        self.assertEqual(ch(self.add(note="channel:pong-gospel Poster")), "pong-gospel")
        self.assertIsNone(ch(self.add(title="Coffee chat")))                # no folder, no channel: the whole office
        t = self.add(channel="pong-gospel")
        self.assertEqual(ch(t), "pong-gospel")
        code, _ = self.act({"action": "channel", "id": t["id"], "channel": "@office"})
        self.assertEqual(code, 200)
        self.assertIsNone(ch(t))
        self.assertEqual(self.act({"action": "channel", "id": t["id"], "channel": "no-such"})[0], 400)
        self.act({"action": "channel", "id": t["id"], "channel": None})       # back to automatic: nothing to go on, whole office
        self.assertIsNone(ch(t))

    def test_cancel_restore_and_delete(self):
        t = self.add(status="review", note="out:somewhere")
        self.assertEqual(self.act({"action": "move", "id": t["id"], "status": "cancelled"})[0], 200)
        self.assertEqual(t["status"], "cancelled")
        self.assertIsNone(t["done_at"])
        self.act({"action": "move", "id": t["id"], "status": "todo"})
        self.assertEqual(t["status"], "todo")
        (self.root / "out" / "somewhere").mkdir(parents=True)
        self.assertEqual(self.act({"action": "remove", "id": t["id"]})[1]["removed"], 1)
        self.assertEqual(self.db["tasks"], [])
        self.assertTrue((self.root / "out" / "somewhere").is_dir())           # deleting a task never touches its files


if __name__ == "__main__":
    unittest.main()
