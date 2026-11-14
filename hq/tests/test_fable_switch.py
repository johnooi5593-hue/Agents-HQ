"""Owner, 2026-11-15: when the Fable limit runs out, the job carries on with Opus 5.5 by itself, once, from where it stopped."""
import ast
import os
import re
import sys
import threading
import time
import types
import unittest
import uuid
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    consts = ("DEFAULT_MODEL", "FABLE_MODEL", "FABLE_ASK", "MODEL_CHOICES", "FABLE_NOTE", "OPUS_NOTE", "TASK_REF",
              "FABLE_LIMIT", "FABLE_429", "FABLE_RESET", "SWITCH_NOTE")
    body = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in consts for t in n.targets)]
    body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("model_for", "model_choice", "fable_limit_hit")]
    body += [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ("Run", "Desk", "Desks")]
    env = {"os": os, "re": re, "uuid": uuid, "threading": threading, "time": time, "sys": sys,
           "run_times": types.SimpleNamespace(add=lambda *a: None), "MAX_PARALLEL": 3, "lane_of": lambda tasks: "lead"}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server-fable", "exec"), env)

    class Gate:                                       # always a free slot
        def __init__(self, limit=3):
            self.limit = limit

        def acquire(self, blocking=True):
            return True

        def release(self):
            pass
    env["Gate"] = Gate
    return env


LIMIT = "You've hit your Fable limit · resets 2am (Asia/Kuala_Lumpur). Switch to another model to continue."


class FableSwitchTests(unittest.TestCase):
    def setUp(self):
        self.env = load()
        self.Run = self.env["Run"]

    def ended(self, text, model="fable", ok=False, kind="result", prompt="edit my latest CAN"):
        run = self.Run(prompt, ["t256"], model)
        run.fable = model == "fable"
        run.add({"type": kind, "text": text, "is_error": not ok})
        run.ok, run.done = ok, True
        return run

    def test_the_fable_limit_is_seen_with_its_reset_time(self):
        hit = self.env["fable_limit_hit"]
        self.assertEqual(hit(self.ended(LIMIT)), "2am (Asia/Kuala_Lumpur)")
        self.assertEqual(hit(self.ended(LIMIT, ok=True)), "2am (Asia/Kuala_Lumpur)")              # the CLI may not call it an error
        self.assertEqual(hit(self.ended("API Error: 429 rate_limit_error model claude-fable-5-1", kind="error")), "later")
        self.assertEqual(hit(self.ended("You\u2019ve hit your fable limit")), "later")
        self.assertEqual(hit(self.ended("You've hit your Fable limit · resets 2.30am")), "2.30am")
        self.assertEqual(hit(self.ended("You've hit your Fable limit · resets Nov 16, 2am")), "Nov 16, 2am")

    def test_only_a_fable_job_that_failed_on_the_limit_switches(self):
        hit = self.env["fable_limit_hit"]
        self.assertEqual(hit(self.ended(LIMIT, model="opus")), "")                                 # Opus: nothing to switch to
        self.assertEqual(hit(self.ended("You've hit your session limit · resets 8:40pm")), "")     # the whole account: Opus is out too
        self.assertEqual(hit(self.ended("Done. Two editors had hit the Fable limit earlier.", ok=True)), "")   # it finished
        self.assertEqual(hit(self.ended("could not render the reel")), "")                         # another failure
        self.assertEqual(hit(self.ended("I stopped: an email said the fable limit ran out")), "")  # only Claude Code's own words
        self.assertEqual(hit(self.ended("You've hit your Fable limit", kind="system")), "")        # raw output lines never count
        self.assertEqual(hit(self.ended("You've hit your Fable limit", kind="error")), "")         # stderr only with the API's 429
        stopped = self.ended(LIMIT)
        stopped.stopped = True
        self.assertEqual(hit(stopped), "")                                                          # the owner's Stop wins
        again = self.ended(LIMIT)
        again.switched_from = "abc"
        self.assertEqual(hit(again), "")                                                            # never twice

    def test_the_desk_lines_up_an_opus_job_first_that_carries_on(self):
        env = self.env
        started = []
        env["threading"] = types.SimpleNamespace(Lock=threading.Lock, Thread=lambda target, args, daemon: types.SimpleNamespace(start=lambda: started.append(args[0])))
        desks = env["Desks"]()
        done = []
        desks.on_done = done.append
        desk = desks.lane("lead")
        later = self.Run("another message", [], None)
        desk.queue.append(later)

        def fake_run(run):
            run.add({"type": "result", "text": LIMIT, "is_error": True})
            run.ok, run.done = False, True
        desk._run = fake_run
        first = self.Run("edit my latest CAN with /caption-card", ["t255", "t256"], "fable")
        first.fable = True
        desk._work(first)
        nxt = started[-1]
        self.assertIsNot(nxt, later)                                       # the switch goes first in line
        self.assertEqual((nxt.model, nxt.fable, nxt.tasks, nxt.switched_from), ("opus", False, ["t255", "t256"], first.id))
        self.assertIn("Carry on from where the Fable run stopped", nxt.prompt)
        self.assertIn("2am (Asia/Kuala_Lumpur)", nxt.prompt)
        self.assertTrue(nxt.prompt.endswith("The request was: edit my latest CAN with /caption-card"))
        self.assertEqual(first.switched, "2am (Asia/Kuala_Lumpur)")
        self.assertEqual(done, [first])                                    # the board hears about the switch
        self.assertIn(nxt.id, desks.runs)                                  # and the app lists the new job
        self.assertEqual(desk.queue, [later])
        self.assertEqual(nxt.summary()["switched_from"], first.id)

        desk._work(nxt)                                                    # the Opus job hits a limit too: no third try
        self.assertIs(started[-1], later)

    def test_stop_reaches_the_switched_job_and_a_stop_at_the_end_wins(self):
        env = self.env
        env["threading"] = types.SimpleNamespace(Lock=threading.Lock, Thread=lambda target, args, daemon: types.SimpleNamespace(start=lambda: None))
        desks = env["Desks"]()
        desk = desks.lane("lead")
        first = self.ended(LIMIT)
        nxt = desk.switch_to_opus(first, "2am")
        desk.current = first
        stopped = desks.stop(run=first.id)                                 # Stop on the Fable job also takes the Opus one out of line
        self.assertIn(nxt.id, [s["id"] for s in stopped])
        self.assertEqual(desk.queue, [])
        late = self.ended(LIMIT)
        late.stopped = True
        self.assertIsNone(desk.switch_to_opus(late, "2am"))
        self.assertFalse(getattr(late, "switched", ""))

    def test_the_lead_restarts_fable_editors_on_opus(self):
        self.assertIn("Fable limit ran out", self.env["FABLE_NOTE"])
        self.assertIn('model: "fable"', self.env["FABLE_NOTE"])


if __name__ == "__main__":
    unittest.main()
