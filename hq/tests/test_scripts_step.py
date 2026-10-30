import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts_step import Scripts  # noqa: E402
from sermon_design import DesignError  # noqa: E402

PICKS = [{"id": "p1", "name": "can-1030-01-let-go", "title": "Let go of the past", "start": 2400, "end": 2452, "why": "the turn", "text": "不要记念从前的事", "status": "keep"},
         {"id": "p2", "name": "can-1030-02-fire", "title": "What survives the fire", "start": 3100, "end": 3158, "why": "the promise", "text": "...", "status": "keep"},
         {"id": "p3", "name": "can-1030-03-spare", "title": "A spare", "start": 4000, "end": 4050, "why": "", "text": "...", "status": "spare"}]


class ScriptsStepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        os.makedirs(os.path.join(self.root, "out", "can-1030"))
        self.jobs = []
        self.sc = Scripts(self.root, None, lambda: {"tasks": []}, self.jobs.append)
        with open(os.path.join(self.root, "out", "can-1030", "scripts.json"), "w", encoding="utf-8") as f:
            json.dump({"source": "inbox/can-1030/can-1030-raw.mp4", "channel": "", "package": "full", "want": 2, "picks": PICKS}, f, ensure_ascii=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_editors_file_is_read_and_tied_to_its_task(self):
        d = self.sc.for_task({"note": "scripts:can-1030 inbox:inbox/can-1030/can-1030-raw.mp4"})
        self.assertEqual([p["status"] for p in d["picks"]], ["keep", "keep", "spare"])
        self.assertEqual(d["want"], 2)
        self.assertIsNone(self.sc.for_task({"note": "out:can-1030"}))
        self.assertIsNone(self.sc.read("nope"))
        self.assertIsNone(self.sc.read("../etc"))

    def test_the_owner_swaps_a_pick_and_adds_a_note(self):
        self.sc.action({"name": "can-1030", "action": "dropped", "pick": "p2"})
        self.sc.action({"name": "can-1030", "action": "keep", "pick": "p3"})
        d = self.sc.action({"name": "can-1030", "action": "trim", "pick": "p1", "trim": "  start later,\n at 但是神 "})
        self.assertEqual([p["status"] for p in d["picks"]], ["keep", "dropped", "keep"])
        self.assertEqual(d["picks"][0]["trim"], "start later, at 但是神")
        with self.assertRaises(DesignError):
            self.sc.action({"name": "can-1030", "action": "keep", "pick": "p9"})
        with self.assertRaises(DesignError):
            self.sc.action({"name": "can-1030", "action": "trim", "pick": "p1", "trim": "x" * 401})

    def test_make_videos_starts_one_lead_job_for_the_kept_picks_and_locks_the_scripts(self):
        self.sc.action({"name": "can-1030", "action": "trim", "pick": "p1", "trim": "end before the prayer"})
        d = self.sc.action({"name": "can-1030", "action": "go", "task": "t7"})
        self.assertTrue(d["made_at"])
        self.assertEqual(len(self.jobs), 1)
        prompt = self.jobs[0]
        self.assertIn("2 video(s)", prompt)
        self.assertIn('p1 "Let go of the past" (2400-2452 s, folder out/can-1030-01-let-go)', prompt)
        self.assertIn("end before the prayer", prompt)
        self.assertNotIn("A spare", prompt)
        self.assertIn("scripts-task:t7", prompt)
        with self.assertRaises(DesignError):                          # no second click, no more swapping
            self.sc.action({"name": "can-1030", "action": "go"})
        with self.assertRaises(DesignError):
            self.sc.action({"name": "can-1030", "action": "spare", "pick": "p1"})

    def test_make_videos_needs_a_kept_pick(self):
        for p in ("p1", "p2"):
            self.sc.action({"name": "can-1030", "action": "dropped", "pick": p})
        with self.assertRaises(DesignError):
            self.sc.action({"name": "can-1030", "action": "go"})
        self.assertEqual(self.jobs, [])


if __name__ == "__main__":
    unittest.main()
