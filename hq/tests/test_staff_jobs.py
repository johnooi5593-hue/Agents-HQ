import ast
import re
import threading
import unittest
import uuid
from pathlib import Path

# Run.staff_jobs straight from server.py (importing it would start the office).
SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Run"]
    env = {"re": re, "uuid": uuid, "threading": threading, "TASK_REF": re.compile(r"\bt\d+\b")}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server-run", "exec"), env)
    return env["Run"]


class StaffJobsTests(unittest.TestCase):
    def test_each_sub_agent_carries_the_job_its_lead_gave_it(self):
        run = load()("edit the CAN 1030 highlights", ["t111"])
        run.started = True
        run.events += [
            {"type": "tool", "id": "a", "staff": "clip-editor", "text": "clip-editor: Edit topic 1 of can-1030-raw.mp4 新的开始"},
            {"type": "tool", "id": "b", "staff": "clip-editor", "text": "clip-editor: Edit topic 2 of can-1030-raw.mp4"},
            {"type": "tool", "id": "c", "staff": "clip-editor", "text": "clip-editor: Edit topic 3"},
            {"type": "tool", "id": "d", "name": "Bash", "text": "ls inbox"},
            {"type": "tool_done", "id": "c", "text": "Async agent launched successfully, running in the background"},
            {"type": "tool_done", "id": "b", "text": "Done: out/can-1030-topic-2"},
        ]
        jobs = run.staff_jobs()
        self.assertEqual([j["id"] for j in jobs], ["a", "c"])                   # b finished; c works in the background
        self.assertEqual(jobs[0]["text"], "Edit topic 1 of can-1030-raw.mp4 新的开始")
        run.done = True
        self.assertEqual(run.staff_jobs(), [])

    def test_a_job_waiting_in_line_has_no_one_at_work(self):
        run = load()("later", [])
        run.events.append({"type": "tool", "id": "a", "staff": "clip-editor", "text": "clip-editor: x"})
        self.assertEqual(run.staff_jobs(), [])


if __name__ == "__main__":
    unittest.main()
