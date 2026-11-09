"""t208: the app's model picker. model_for(prompt, choice): the owner's pick ("opus" | "fable") wins; without one, the
words in the message ("use Fable…", "fable: …", "/fable …") decide; anything else is Opus 5.5."""
import ast
import io
import json
import os
import re
import threading
import time
import unittest
import uuid
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    consts = ("DEFAULT_MODEL", "FABLE_MODEL", "FABLE_ASK", "MODEL_CHOICES", "FABLE_NOTE", "OPUS_NOTE", "TASK_REF")
    body = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in consts for t in n.targets)]
    body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("model_for", "model_choice")]
    body += [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ("Run", "Desk")]
    env = {"os": os, "re": re, "uuid": uuid, "threading": threading, "time": time, "json": json}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server-models", "exec"), env)
    return env


class ModelForTests(unittest.TestCase):
    def setUp(self):
        self.env = load()
        self.opus, self.fable = self.env["DEFAULT_MODEL"], self.env["FABLE_MODEL"]

    def test_defaults(self):
        self.assertEqual(self.opus, os.environ.get("HQ_MODEL", "claude-opus-5-5"))
        self.assertEqual(self.fable, os.environ.get("HQ_FABLE_MODEL", "claude-fable-5-1"))

    def test_the_message_decides_without_a_pick(self):
        mf = self.env["model_for"]
        self.assertEqual(mf("edit the reels"), self.opus)
        self.assertEqual(mf("use Fable to edit the reels"), self.fable)
        self.assertEqual(mf("fable: write three hooks"), self.fable)
        self.assertEqual(mf("/fable plan the week"), self.fable)
        self.assertEqual(mf("a fable about a lighthouse"), self.opus)     # the word alone is not a request
        self.assertEqual(mf("use fable", None), self.fable)

    def test_an_explicit_pick_wins(self):
        mf = self.env["model_for"]
        self.assertEqual(mf("edit the reels", "fable"), self.fable)
        self.assertEqual(mf("use Fable to edit the reels", "opus"), self.opus)
        self.assertEqual(mf("edit", "opus"), self.opus)

    def test_only_the_two_choices_are_accepted(self):
        mc = self.env["model_choice"]
        self.assertIsNone(mc(None))
        self.assertIsNone(mc(""))
        self.assertEqual(mc("fable"), "fable")
        self.assertEqual(mc(" Opus "), "opus")
        for bad in ("claude-opus-5-5", "haiku", 1, True, ["fable"], {"m": "fable"}):
            with self.assertRaises(ValueError):
                mc(bad)

    def test_run_summary_names_the_model(self):
        Run, Desk = self.env["Run"], self.env["Desk"]
        self.assertEqual(Run("hello").summary()["model"], "opus")
        self.assertEqual(Run("hello", [], "fable").summary()["model"], "fable")
        desk = Desk()
        desk._work = lambda run: None                                    # nothing really runs
        import types
        self.env["threading"] = types.SimpleNamespace(Thread=lambda target, args, daemon: types.SimpleNamespace(start=lambda: None), Lock=threading.Lock)
        self.assertEqual(desk.start("use fable: plan it").summary()["model"], "fable")
        desk.current = None
        self.assertEqual(desk.start("use fable: plan it", (), "opus").summary()["model"], "opus")
        desk.current = None
        self.assertEqual(desk.start("plan it", (), "fable").summary()["model"], "fable")


class RunCommandTests(unittest.TestCase):
    """Desk._run passes the picked model to claude, and tells the lead to give Fable to its sub-agents."""

    def setUp(self):
        self.env = load()
        self.cmds = []
        env = self.env

        class FakeProc:
            def __init__(proc, cmd, **kw):
                self.cmds.append(cmd)
                proc.stdout = io.StringIO(json.dumps({"type": "result"}) + "\n")
                proc.stderr = io.StringIO("")
                proc.returncode = 0

            def wait(proc):
                return 0
        import types
        env.update({"with_skills": lambda p: p, "claude_argv": lambda: ["claude"], "CLAUDE": "claude", "COPY_NOTE": "note", "allow_list": lambda: [],
                    "extra_dirs": lambda: [], "CHILD_HIDDEN": set(), "ROOT": ".", "FRESH_AFTER_IDLE": 1e9, "FRESH_AFTER_CONTEXT": 1e9,
                    "FRESH_AFTER_COST": 1e9, "translate": lambda obj: [{"type": "result", "text": "ok", "is_error": False}],
                    "subprocess": types.SimpleNamespace(Popen=FakeProc, PIPE=-1)})

    def run_with(self, prompt, model):
        desk = self.env["Desk"]()
        run = self.env["Run"](prompt, [], model)
        desk._run(run)
        cmd = self.cmds[-1]
        return cmd[cmd.index("--model") + 1], cmd[cmd.index("-p") + 1]

    def test_picked_fable(self):
        model, prompt = self.run_with("edit the reels", "fable")
        self.assertEqual(model, self.env["FABLE_MODEL"])
        self.assertIn('model: "fable"', prompt)

    def test_picked_opus_over_the_words(self):
        model, prompt = self.run_with("use Fable to edit the reels", "opus")
        self.assertEqual(model, self.env["DEFAULT_MODEL"])
        self.assertIn("not Fable", prompt)

    def test_no_pick_follows_the_message(self):
        self.assertEqual(self.run_with("use Fable to edit", None)[0], self.env["FABLE_MODEL"])
        model, prompt = self.run_with("edit the reels", None)
        self.assertEqual(model, self.env["DEFAULT_MODEL"])
        self.assertEqual(prompt, "edit the reels")                       # nothing added without a pick


if __name__ == "__main__":
    unittest.main()
