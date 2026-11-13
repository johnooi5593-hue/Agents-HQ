"""One click moves every scheduled post of a video to a new time (owner, 2026-11-13)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish


class FakeAccounts:
    def get(self, kind, channel=""):
        return {"page_token": "PAGE-TOKEN", "page_id": "p"} if kind == "meta" else {}

    def youtube_token(self, channel=""):
        return "YT-TOKEN"


class RescheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "approved" / "clip"
        self.folder.mkdir(parents=True)
        self.moves = []
        self.pub = publish.Publisher(self.temp.name, FakeAccounts(), on_move=lambda folder, task, when: self.moves.append((task, when)))
        self.calls, self.refuse = [], set()

        self.fb = {"published": False, "scheduled_publish_time": None}     # what Facebook holds
        self.yt = {"privacyStatus": "private", "publishAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)), "license": "creativeCommon", "embeddable": False, "uploadStatus": "processed"}
        self.ignore = set()                                                  # platforms that answer OK but change nothing

        def http(method, url, data=None, headers=None, body=None, timeout=120):
            self.calls.append((method, url, data, headers, body))
            if method != "GET" and any(x in url for x in self.refuse):
                raise publish.PostError("refused by the platform")
            if "graph.facebook.com" in url:
                if method == "POST" and "facebook" not in self.ignore:
                    self.fb["scheduled_publish_time"] = int(data["scheduled_publish_time"])
                return 200, {}, dict(self.fb)
            if method == "PUT" and "youtube" not in self.ignore:
                self.yt.update(json.loads(body)["status"])
            return 200, {}, ({"items": [{"status": dict(self.yt)}]} if method == "GET" else {"status": dict(self.yt)})
        mock.patch.object(publish, "http", http).start()
        self.addCleanup(mock.patch.stopall)
        self.old, self.new = int(time.time()) + 3600, int(time.time()) + 2 * 86400
        self.fb["scheduled_publish_time"] = self.old
        self.f = str(self.folder)

    def rec(self, p):
        return self.pub.record(self.f).get(p) or {}

    def test_facebook_youtube_and_a_waiting_instagram_move_together(self):
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.pub.note(self.f, "instagram", state="scheduled", when=self.old, job={"video": "edit.mp4", "text": {}})
        self.pub.note(self.f, "_task", value="t9")
        res = self.pub.reschedule(self.f, self.new)
        self.assertEqual((res["moved"], res["kept"]), (["facebook", "instagram", "youtube"], {}))
        self.assertEqual([self.rec(p)["when"] for p in ("facebook", "instagram", "youtube")], [self.new] * 3)
        self.assertEqual(self.rec("instagram")["job"], {"video": "edit.mp4", "text": {}})        # still waits here
        fb = [c for c in self.calls if "graph.facebook.com" in c[1]]
        yt = [c for c in self.calls if "googleapis.com" in c[1]]
        self.assertEqual([c[0] for c in fb], ["GET", "POST", "GET"])                             # asked, changed, read back
        self.assertEqual((fb[1][1], fb[1][2]["scheduled_publish_time"]), (publish.GRAPH + "/123456", str(self.new)))
        self.assertEqual([c[0] for c in yt], ["GET", "PUT"])
        sent = json.loads(yt[1][4])
        self.assertEqual((sent["id"], sent["status"]["privacyStatus"]), ("abc_DEF-123", "private"))
        self.assertEqual(sent["status"]["publishAt"], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.new)))
        self.assertEqual((sent["status"]["license"], sent["status"]["embeddable"]), ("creativeCommon", False))   # its other settings stay
        self.assertNotIn("uploadStatus", sent["status"])
        self.assertEqual(self.moves, [("t9", self.new)])                                        # the board's dated task moves too
        self.assertNotIn(self.f, self.pub.busy)

    def test_a_platform_that_refuses_keeps_its_old_time_and_says_so(self):
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.refuse.add("graph.facebook.com")
        res = self.pub.reschedule(self.f, self.new)
        self.assertEqual(res["moved"], ["youtube"])
        self.assertIn("facebook", res["kept"])
        self.assertEqual((self.rec("facebook")["when"], self.rec("youtube")["when"]), (self.old, self.new))
        self.assertIn("Meta Business Suite", self.rec("facebook")["warning"])
        self.assertNotIn("PAGE-TOKEN", json.dumps(res) + self.rec("facebook")["warning"])

    def test_nothing_moved_is_an_error_and_nothing_scheduled_too(self):
        with self.assertRaises(publish.PostError) as e:
            self.pub.reschedule(self.f, self.new)
        self.assertIn("nothing is scheduled", str(e.exception))
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.refuse.add("graph.facebook.com")
        with self.assertRaises(publish.PostError) as e:
            self.pub.reschedule(self.f, self.new)
        self.assertIn("nothing was rescheduled", str(e.exception))
        self.assertEqual((self.rec("facebook")["when"], self.moves), (self.old, []))
        self.assertNotIn(self.f, self.pub.busy)

    def test_posted_and_failed_rows_are_left_alone(self):
        self.pub.note(self.f, "facebook", state="posted", when=self.old, link="https://www.facebook.com/reel/1")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        res = self.pub.reschedule(self.f, self.new)
        self.assertEqual(res["moved"], ["youtube"])
        self.assertEqual((self.rec("facebook")["state"], self.rec("facebook")["when"]), ("posted", self.old))
        self.assertFalse([c for c in self.calls if "graph.facebook.com" in c[1]])

    def test_the_time_must_be_ahead_and_a_bad_link_is_never_sent(self):
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://evil.example/x?shorts=1")
        for bad in (int(time.time()) + 60, "soon", None, int(time.time()) + 60 * 86400):
            with self.assertRaises(publish.PostError):
                self.pub.reschedule(self.f, bad)
        with self.assertRaises(publish.PostError):
            self.pub.reschedule(self.f, self.new)
        self.assertEqual(self.calls, [])

    def test_a_video_that_is_already_public_is_never_pulled_back(self):
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.yt.update(privacyStatus="public"); self.fb.update(published=True)
        with self.assertRaises(publish.PostError):
            self.pub.reschedule(self.f, self.new)
        self.assertEqual([c[0] for c in self.calls], ["GET", "GET"])                             # asked, never changed
        self.assertIn("no longer holds it as scheduled", self.rec("youtube")["warning"])

    def test_a_post_whose_time_has_come_stays(self):
        soon = int(time.time()) + 30
        self.pub.note(self.f, "youtube", state="scheduled", when=soon, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.pub.note(self.f, "instagram", state="scheduled", when=soon, job={"video": "edit.mp4", "text": {}})
        with self.assertRaises(publish.PostError) as e:
            self.pub.reschedule(self.f, self.new)
        self.assertIn("its time has come", str(e.exception))
        self.assertEqual((self.calls, self.rec("instagram")["when"]), ([], soon))

    def test_an_ok_answer_that_changed_nothing_is_not_reported_as_moved(self):
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.ignore.update(("facebook", "youtube"))
        with self.assertRaises(publish.PostError) as e:
            self.pub.reschedule(self.f, self.new)
        self.assertIn("did not confirm", str(e.exception))
        self.assertEqual((self.rec("facebook")["when"], self.rec("youtube")["when"]), (self.old, self.old))

    def test_an_unexpected_error_on_one_platform_does_not_stop_the_others(self):
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        mock.patch.object(self.pub.accounts, "get", lambda kind, channel="": None).start()
        res = self.pub.reschedule(self.f, self.new)
        self.assertEqual((res["moved"], res["kept"]["facebook"]), (["youtube"], "TypeError"))
        self.assertNotIn(self.f, self.pub.busy)

    def test_the_platforms_own_time_decides_not_ours(self):
        # the owner moved it to "in 30 seconds" in Studio / Business Suite: our record still says an hour ahead
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        soon = time.time() + 30
        self.fb["scheduled_publish_time"] = int(soon)
        self.yt["publishAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(soon))
        with self.assertRaises(publish.PostError):
            self.pub.reschedule(self.f, self.new)
        self.assertEqual([c[0] for c in self.calls], ["GET", "GET"])

    def test_an_unconfirmed_change_says_it_may_have_moved(self):
        self.pub.note(self.f, "facebook", state="scheduled", when=self.old, job=None, link="https://www.facebook.com/reel/123456")
        self.ignore.add("facebook")
        with self.assertRaises(publish.PostError):
            self.pub.reschedule(self.f, self.new)
        self.assertIn("may have moved", self.rec("facebook")["warning"])
        self.assertEqual(self.rec("facebook")["when"], self.old)

    def test_a_moved_instagram_job_drops_its_old_retry_note(self):
        self.pub.note(self.f, "instagram", state="scheduled", when=self.old, job={"video": "edit.mp4", "text": {}, "tries": 1},
                      warning="Instagram refused the upload just now. Agents HQ tries again by itself at 10:20")
        self.pub.reschedule(self.f, self.new)
        self.assertEqual((self.rec("instagram")["when"], self.rec("instagram")["warning"]), (self.new, ""))

    def test_cancel_waits_for_a_folder_that_is_being_posted(self):
        self.pub.note(self.f, "instagram", state="scheduled", when=self.old, job={"video": "edit.mp4", "text": {}})
        self.pub.busy.add(self.f)
        with self.assertRaises(publish.PostError):
            self.pub.cancel(self.f, "instagram")
        self.assertEqual(self.rec("instagram")["state"], "scheduled")
        self.pub.busy.discard(self.f)
        self.pub.cancel(self.f, "instagram")
        self.assertEqual((self.rec("instagram")["state"], self.f in self.pub.busy), ("cancelled", False))

    def test_facebook_time_formats(self):
        self.assertEqual(publish.fb_time("1794500000"), 1794500000)
        self.assertEqual(publish.fb_time("2026-11-13T02:00:00+0000"), 1794535200)
        self.assertEqual((publish.fb_time(None), publish.fb_time("soon")), (0, 0))

    def test_a_folder_being_posted_is_not_touched(self):
        self.pub.note(self.f, "youtube", state="scheduled", when=self.old, job=None, link="https://youtube.com/shorts/abc_DEF-123")
        self.pub.busy.add(self.f)
        with self.assertRaises(publish.PostError):
            self.pub.reschedule(self.f, self.new)
        self.assertEqual((self.calls, self.rec("youtube")["when"]), ([], self.old))


if __name__ == "__main__":
    unittest.main()
