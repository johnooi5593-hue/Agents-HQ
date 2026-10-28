import ast
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

# "Leads at once" straight from server.py (importing it would start the office).
SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load(conf):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("leads_setting", "save_office")]
    body += [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MAX_LEADS" for t in n.targets)]
    body += [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Gate"]
    env = {"os": os, "json": json, "threading": threading, "office_conf": lambda: conf}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server-leads", "exec"), env)
    return env


class LeadsTests(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.pop("HQ_PARALLEL", None)

    def tearDown(self):
        os.environ.pop("HQ_PARALLEL", None)
        if self.old is not None:
            os.environ["HQ_PARALLEL"] = self.old

    def test_the_setting_is_3_by_default_and_1_to_10(self):
        self.assertEqual(load({})["leads_setting"](), 3)
        self.assertEqual(load({"leads": 10})["leads_setting"](), 10)
        self.assertEqual(load({"leads": 25})["leads_setting"](), 10)
        self.assertEqual(load({"leads": 0})["leads_setting"](), 3)          # 0 means not set
        self.assertEqual(load({"leads": -4})["leads_setting"](), 1)
        self.assertEqual(load({"leads": "lots"})["leads_setting"](), 3)
        os.environ["HQ_PARALLEL"] = "6"
        self.assertEqual(load({"leads": 10})["leads_setting"](), 6)          # the computer's own setting wins

    def test_more_slots_start_waiting_jobs_and_fewer_let_running_ones_finish(self):
        g = load({})["Gate"](3)
        self.assertTrue(all(g.acquire(blocking=False) for _ in range(3)))
        self.assertFalse(g.acquire(blocking=False))
        started = []
        waiter = threading.Thread(target=lambda: started.append(g.acquire()))
        waiter.start()
        time.sleep(0.1)
        self.assertEqual(started, [])
        g.resize(10)                                                          # a waiting job starts at once
        waiter.join(2)
        self.assertEqual(started, [True])
        g.resize(2)                                                           # 4 running, 2 allowed: nothing new starts
        self.assertFalse(g.acquire(blocking=False))
        g.release(); g.release()
        self.assertFalse(g.acquire(blocking=False))                           # 2 still running
        g.release()
        self.assertTrue(g.acquire(blocking=False))

    def test_the_choice_is_kept_in_the_office_file_with_its_other_settings(self):
        with tempfile.TemporaryDirectory() as root:
            env = load({"name": "Acme HQ"})
            env["OFFICE_FILE"] = os.path.join(root, ".hq-office.json")
            env["save_office"]({"leads": 8})
            self.assertEqual(json.loads(Path(env["OFFICE_FILE"]).read_text(encoding="utf-8")), {"name": "Acme HQ", "leads": 8})


if __name__ == "__main__":
    unittest.main()
