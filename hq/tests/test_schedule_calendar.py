"""The When step's posting calendar: GET /api/schedule lists one channel's scheduled and recently posted videos
(owner, 2026-11-19: "show all NLRCC scheduled posts so I know which one is at which date"; Pong the same)."""
import ast
import json
import math
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

HQ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HQ))
import channels as channels_mod                      # folder_channel reads channel.txt; no office starts
SERVER = HQ / "server.py"


class FakePublish:
    PLATFORMS = ("facebook", "instagram", "youtube", "tiktok", "buffer")

    @staticmethod
    def drafts(d):
        return {"options": [{"title": "Title of " + os.path.basename(d)}]}


class ScheduleCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "schedule_payload"]
        body += [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "SAFE_NAME" for t in n.targets)]
        self.env = {"os": os, "re": re, "json": json, "math": math, "time": time, "ROOT": str(self.root),
                    "publish": FakePublish, "channels_mod": channels_mod}
        exec(compile(ast.Module(body=body, type_ignores=[]), "server-schedule-fixture", "exec"), self.env)
        self.now = time.time()

    def video(self, name, posted, channel=None, sub=None):
        d = self.root / "approved" / name
        if sub:
            d = d / sub
        d.mkdir(parents=True, exist_ok=True)
        if channel is not None:
            (d / "channel.txt").write_text(channel, encoding="utf-8")
        (d / "posted.json").write_text(json.dumps(posted), encoding="utf-8")

    def test_lists_scheduled_and_recent_posts_of_one_channel(self):
        self.video("nl-soon", {"facebook": {"state": "scheduled", "when": self.now + 86400}})
        self.video("nl-yesterday", {"youtube": {"state": "posted", "when": self.now - 86400, "at": self.now - 60}})
        self.video("nl-old", {"youtube": {"state": "posted", "when": self.now - 5 * 86400, "at": self.now - 5 * 86400}})
        self.video("pong-soon", {"buffer": {"state": "scheduled", "when": self.now + 7200}}, channel="pong-gospel")
        main = self.env["schedule_payload"]("")
        self.assertEqual([x["name"] for x in main["items"]], ["nl-yesterday", "nl-soon"])
        self.assertEqual(main["items"][0]["when"], int(self.now - 86400))          # when it went out, not the last write
        self.assertEqual(main["items"][1]["state"], "scheduled")
        self.assertEqual(main["items"][1]["title"], "Title of nl-soon")
        self.assertEqual(self.env["schedule_payload"]("main"), main)
        pong = self.env["schedule_payload"]("pong-gospel")
        self.assertEqual([(x["name"], x["platforms"]) for x in pong["items"]], [("pong-soon", ["buffer"])])

    def test_topics_and_damaged_files(self):
        self.video("talk", {"facebook": {"state": "scheduled", "when": self.now + 3600}}, sub="topic-1")
        self.video("broken", {"facebook": {"state": "scheduled", "when": "soon"}, "youtube": {"state": "posted", "at": {"x": 1}}})
        (self.root / "approved" / "junk").mkdir()
        (self.root / "approved" / "junk" / "posted.json").write_text("not json", encoding="utf-8")
        items = self.env["schedule_payload"]("")["items"]
        self.assertEqual([x["folder"] for x in items], ["approved/talk/topic-1"])

    def test_bad_channel_key(self):
        self.assertEqual(self.env["schedule_payload"]("../secrets")["items"], [])


if __name__ == "__main__":
    unittest.main()
