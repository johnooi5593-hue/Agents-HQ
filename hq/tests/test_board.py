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
        names = {"normalize_task", "set_status", "clean_progress", "clean_date", "clean_time", "safe_join", "task_channel", "_task_action", "add_chat", "after_run"}
        body = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("STATUSES", "KINDS", "TASK_DEFAULTS", "OFFICE", "FOOTAGE", "DATE_RE", "TIME_RE", "SAFE_NAME", "CHAT_KEEP", "ASKS", "TASK_REF") for t in n.targets)]
        body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        body += [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ("Run", "Desk")]
        self.db = {"tasks": []}
        self.env = {"re": re, "os": os, "datetime": datetime, "shutil": __import__("shutil"), "ROOT": str(self.root), "channels": Channels(), "TASK_LOCK": __import__("threading").Lock(),
                    "load_tasks": lambda: self.db, "uuid": __import__("uuid"), "threading": __import__("threading"), "time": __import__("time"), "sys": sys, "save_tasks": lambda db: None, "now_iso": lambda: "2026-10-27T00:00:00Z"}
        exec(compile(ast.Module(body=body, type_ignores=[]), "server-board-fixture", "exec"), self.env)
        self.act = self.env["_task_action"]
        self.env["channels"].name = lambda key: "Pong+Gospel" if key else "NLRCC"
        self.started = []

        class FakeDesk:                                     # records what would go to the lead
            def start(desk, prompt, tasks=()):
                run = self.env["Run"](prompt, tasks)
                self.started.append(run)
                return run
        self.env["desk"] = FakeDesk()

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

    def test_deleted_tasks_wait_in_deleted_and_can_be_restored(self):
        t = self.add(title="Keep me", channel="pong-gospel")
        self.act({"action": "remove", "id": t["id"]})
        self.assertEqual(self.db["tasks"], [])
        self.assertEqual(self.db["deleted"][0]["title"], "Keep me")
        self.assertNotEqual(self.add()["id"], t["id"])                     # a deleted task keeps its id
        self.assertEqual(self.act({"action": "restore", "id": t["id"]})[0], 200)
        back = next(x for x in self.db["tasks"] if x["id"] == t["id"])
        self.assertEqual((back["title"], back["channel"], "deleted_at" in back), ("Keep me", "pong-gospel", False))
        self.assertEqual(self.db["deleted"], [])
        self.assertEqual(self.act({"action": "restore", "id": t["id"]})[0], 404)    # never twice

    def test_reedit_starts_a_new_version_and_keeps_the_approved_one(self):
        old = self.root / "approved" / "clip-a"
        old.mkdir(parents=True)
        (old / "edit.mp4").write_bytes(b"v1")
        (self.root / "out").mkdir()
        t = self.add(status="done", note="out:clip-a channel:pong-gospel")
        code, res = self.act({"action": "reedit", "id": t["id"]})
        self.assertEqual((code, res["folder"]), (200, "out/clip-a-v2"))
        self.assertEqual((self.root / "out" / "clip-a-v2" / "edit.mp4").read_bytes(), b"v1")
        self.assertTrue((old / "edit.mp4").is_file())                         # the approved (maybe posted) version stays
        self.assertEqual((t["status"], t["note"]), ("doing", "out:clip-a-v2 channel:pong-gospel"))
        t2 = self.add(status="done", note="out:clip-a")
        self.assertEqual(self.act({"action": "reedit", "id": t2["id"]})[1]["folder"], "out/clip-a-v3")
        self.assertEqual(self.act({"action": "reedit", "id": self.add(status="done")["id"]})[0], 409)   # nothing approved

    def test_a_folder_without_a_task_can_be_filed_and_taken_off_the_board(self):
        clip = self.root / "out" / "clip-1"
        clip.mkdir(parents=True)
        (clip / "edit.mp4").write_bytes(b"x")
        self.assertEqual(self.act({"action": "folder-channel", "folder": "clip-1", "channel": "pong-gospel"})[0], 200)
        self.assertEqual((clip / "channel.txt").read_text(encoding="utf-8"), "pong-gospel")
        self.assertEqual(self.act({"action": "folder-channel", "folder": "clip-1", "channel": "no-such"})[0], 400)
        self.assertEqual(self.act({"action": "folder-channel", "folder": "../tasks", "channel": ""})[0], 404)
        (self.root / "out" / "thumbnail-final-abc").mkdir()
        self.assertEqual(self.act({"action": "folder-channel", "folder": "thumbnail-final-abc", "channel": ""})[0], 409)
        (self.root / "out" / "clip-2").mkdir()
        self.assertEqual(self.act({"action": "folder-channel", "folders": ["clip-1", "clip-2"], "channel": ""})[0], 200)
        self.assertEqual((self.root / "out" / "clip-2" / "channel.txt").read_text(encoding="utf-8"), "")
        self.act({"action": "folder-hide", "folders": ["clip-1", "clip-2"]})          # every version of one project at once
        self.assertEqual([h["name"] for h in self.db["hidden_out"]], ["clip-1", "clip-2"])
        self.assertTrue((clip / "edit.mp4").is_file())                         # taking it off the board keeps its files
        self.act({"action": "folder-show", "folders": ["clip-1", "clip-2"]})
        self.assertEqual(self.db["hidden_out"], [])


    def test_run_again_and_chat_go_to_the_lead_tied_to_the_task(self):
        t = self.add(title="Subtitle fix", team="Creative", status="doing", subtitle="Blocked: old note", note="out:clip channel:pong-gospel")
        code, res = self.act({"action": "run", "id": t["id"]})
        self.assertEqual((code, res["run"]["tasks"]), (202, [t["id"]]))
        self.assertIn("stopped before it was finished", self.started[-1].prompt)
        self.assertEqual(t["subtitle"], "")                                      # the stale "Blocked" note goes
        self.assertEqual(self.act({"action": "say", "id": t["id"], "text": "  "})[0], 400)
        t["asks"] = True
        self.act({"action": "say", "id": t["id"], "text": "Make the title yellow"})
        self.assertEqual(t["chat"][-1]["from"], "owner")
        self.assertFalse(t["asks"])                                              # answered
        self.assertIn("Make the title yellow", self.started[-1].prompt)
        self.assertIn("channel Pong+Gospel", self.started[-1].prompt)

    def test_the_leads_reply_lands_in_the_task_chat_and_a_question_flags_it(self):
        t = self.add(title="Audio fix")
        run = self.env["Run"]("work", [t["id"]])
        run.add({"type": "result", "text": "Done. Should I also fix clip 2?"})
        self.env["after_run"](run)
        self.assertEqual((t["chat"][-1]["from"], t["asks"]), ("lead", True))
        run = self.env["Run"]("work", [t["id"]])
        run.add({"type": "result", "text": "Sent to Creative, it is in the work folder."})
        self.env["after_run"](run)
        self.assertFalse(t["asks"])
        run = self.env["Run"]("work", [t["id"]])
        run.add({"type": "error", "text": "claude exited with code 1"})
        self.env["after_run"](run)
        self.assertTrue(t["chat"][-1]["error"] and t["asks"])                   # a run that broke also waits for the owner
        many = self.env["Run"]("standup", ["t1", "t2", "t3", "t4"])
        many.add({"type": "result", "text": "?"})
        self.env["after_run"](many)                                             # office-wide work stays out of task chats

    def test_a_run_finds_the_tasks_it_works_on(self):
        run = self.env["Run"]("/brief something (board task t7, team Dev)")
        run.add({"type": "tool", "text": 'Bash: node hq/tasks.js move t8 doing'})
        run.add({"type": "tool_done", "text": '{"added": {"id": "t9", "title": "x"}}'})
        self.assertEqual(run.tasks, ["t7", "t8", "t9"])

    def test_the_desk_lines_up_messages_while_the_lead_works(self):
        import threading
        gate, done = threading.Event(), []
        desk = self.env["Desk"]()
        desk._run = lambda run: (gate.wait(5), setattr(run, "done", True))
        desk.on_done = lambda run: done.append(run.id)
        a = desk.start("first", ["t1"])
        b = desk.start("second", ["t2"])
        self.assertTrue(b.summary()["queued"])
        self.assertEqual(desk.working_on(), {"t1": {"state": "working", "step": "starting"}, "t2": {"state": "queued"}})
        gate.set()
        for _ in range(100):
            if len(done) == 2:
                break
            __import__("time").sleep(0.02)
        self.assertEqual(done, [a.id, b.id])                                    # the second started by itself after the first


if __name__ == "__main__":
    unittest.main()
