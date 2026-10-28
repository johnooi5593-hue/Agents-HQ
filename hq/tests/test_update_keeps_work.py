import ast
import base64
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

# auto_update straight from server.py (importing it would start the office), on a real clone of a temp "GitHub".
SERVER = Path(__file__).resolve().parents[1] / "server.py"
NAMES = {"office_conf", "access_key_text", "git_ssh", "git", "adopt_folder", "merge_brain", "local_edits", "auto_update", "newer_version_waiting"}


def sh(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class UpdateKeepsWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        t = Path(self.temp.name)
        self.hub, self.dev, self.office = t / "hub.git", t / "dev", t / "office"
        sh(t, "init", "--bare", "-q", "-b", "main", str(self.hub))
        sh(t, "clone", "-q", str(self.hub), str(self.dev))
        (self.dev / "brain").mkdir()
        (self.dev / "hud.js").write_text("one\n", encoding="utf-8")
        (self.dev / "brain" / "memory.jsonl").write_text('{"type": "entity", "name": "Lessons", "observations": ["a"]}\n', encoding="utf-8")
        sh(self.dev, "add", "-A"); sh(self.dev, "commit", "-qm", "v1"); sh(self.dev, "push", "-q", "origin", "HEAD:main")
        sh(t, "clone", "-q", str(self.hub), str(self.office))
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
        self.env = {"os": os, "re": re, "json": json, "html": html, "base64": base64, "subprocess": subprocess, "shutil": shutil, "time": time,
                    "ROOT": str(self.office), "REPO_URL": str(self.hub), "REPO_BRANCH": "main", "OFFICE_FILE": str(self.office / ".hq-office.json"),
                    "_OFFICE": {"mtime": None, "data": {}}, "ACCESS_KEY": "", "ACCESS_PREFIX": "HQ1.", "USER_DATA": ("brain/memory.jsonl",),
                    "UPDATE": {"ok": None, "version": "", "from": "", "message": "", "at": 0}}
        exec(compile(ast.Module(body=body, type_ignores=[]), "server-update", "exec"), self.env)
        os.environ.pop("HQ_UPDATE_NOTE", None); os.environ.pop("HQ_NO_UPDATE", None)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, text):
        (self.dev / "hud.js").write_text(text, encoding="utf-8")
        sh(self.dev, "commit", "-qam", "v2"); sh(self.dev, "push", "-q", "origin", "HEAD:main")

    def test_unfinished_work_in_a_file_the_update_also_changes_is_left_exactly_as_it_is(self):
        self.publish("two\n")
        (self.office / "hud.js").write_text("one\nmy unfinished work\n", encoding="utf-8")
        before = sh(self.office, "rev-parse", "HEAD")
        self.assertFalse(self.env["newer_version_waiting"]())             # no restart for an update that would wait
        self.env["auto_update"]()
        self.assertEqual((self.office / "hud.js").read_text(encoding="utf-8"), "one\nmy unfinished work\n")
        self.assertEqual(sh(self.office, "rev-parse", "HEAD"), before)
        self.assertEqual(sh(self.office, "stash", "list"), "")
        self.assertIs(self.env["UPDATE"]["ok"], False)
        self.assertIn("hud.js", self.env["UPDATE"]["message"])

    def test_with_only_the_brain_changed_the_update_goes_ahead_and_keeps_the_brain(self):
        self.publish("two\n")
        brain = self.office / "brain" / "memory.jsonl"
        brain.write_text('{"type": "entity", "name": "Lessons", "observations": ["a", "mine"]}\n', encoding="utf-8")
        self.assertTrue(self.env["newer_version_waiting"]())
        self.env["auto_update"]()
        self.assertTrue(self.env["UPDATE"]["ok"], self.env["UPDATE"])
        self.assertEqual((self.office / "hud.js").read_text(encoding="utf-8"), "two\n")
        self.assertIn("mine", brain.read_text(encoding="utf-8"))

    def test_a_clean_office_updates(self):
        self.publish("two\n")
        self.env["auto_update"]()
        self.assertTrue(self.env["UPDATE"]["ok"])
        self.assertEqual((self.office / "hud.js").read_text(encoding="utf-8"), "two\n")


if __name__ == "__main__":
    unittest.main()
