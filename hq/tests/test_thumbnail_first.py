import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish


class FakeAccounts:
    def get(self, kind, channel=""):
        return {"page_token": "t", "ig_id": "ig", "page_id": "p"}

    def youtube_token(self, channel=""):
        return "yt"


class ThumbnailFirstTests(unittest.TestCase):
    """Owner, 2026-11-02: no platform ever shows a post without the owner's thumbnail."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.video, self.cover = str(Path(d, "edit.mp4")), str(Path(d, "cover.jpg"))
        Path(self.video).write_bytes(b"v")
        Path(self.cover).write_bytes(b"jpg")
        self.pub = publish.Publisher(d, FakeAccounts())
        self.calls = []
        self.thumb_ok = True
        mock.patch.object(publish.time, "sleep", lambda s: None).start()
        mock.patch.object(publish, "http", self.http).start()
        self.addCleanup(mock.patch.stopall)

    def http(self, method, url, data=None, headers=None, body=None, timeout=120):
        status = None
        if "videos?part=status" in url:
            status = json.loads(body)["status"]
        elif "uploadType=resumable" in url:
            status = json.loads(body)["status"]
        self.calls.append((method, url.split("?")[0].rsplit("/", 1)[-1], (data or {}).get("upload_phase"), status))
        if "thumbnails" in url and not self.thumb_ok:
            raise publish.PostError("400: thumbnail refused")
        if "uploadType=resumable" in url:
            return 200, {"Location": "https://up/1"}, {}
        if url == "https://up/1":
            return 200, {}, {"id": "y1", "status": {"privacyStatus": "private"}}
        if "videos?part=status" in url:
            return 200, {}, {"id": "y1", "status": status}
        return 200, {}, {"video_id": "f1", "upload_url": "https://rupload/f1"}

    def phases(self):
        return [c[2] or c[1] for c in self.calls]

    def test_facebook_thumbnail_goes_on_before_it_is_published(self):
        self.pub.post_facebook(self.video, self.cover, {"caption": "hi"})
        ph = self.phases()
        self.assertLess(ph.index("thumbnails"), ph.index("finish"))

    def test_facebook_is_never_published_when_the_thumbnail_is_refused(self):
        self.thumb_ok = False
        with self.assertRaises(publish.PostError):
            self.pub.post_facebook(self.video, self.cover, {"caption": "hi"})
        self.assertEqual(self.phases().count("finish"), 1)             # only the draft (states checked in the draft test)

    def test_youtube_goes_up_private_and_opens_after_the_thumbnail(self):
        link, extra = self.pub.post_youtube(self.video, self.cover, {"title": "t"})
        up = next(c for c in self.calls if c[1] == "videos" and c[0] == "POST")
        self.assertEqual(up[3]["privacyStatus"], "private")
        names = [c[1] for c in self.calls]
        self.assertLess(names.index("set"), max(i for i, c in enumerate(self.calls) if c[0] == "PUT" and c[1] == "videos"))
        self.assertEqual(self.calls[-1][3]["privacyStatus"], "public")
        self.assertEqual(extra, {})

    def test_youtube_stays_private_when_the_thumbnail_is_refused(self):
        self.thumb_ok = False
        with self.assertRaises(publish.PostError):
            self.pub.post_youtube(self.video, self.cover, {"title": "t"})
        self.assertFalse([c for c in self.calls if c[3] and c[3].get("privacyStatus") != "private"])

    def test_youtube_schedule_is_set_only_after_the_thumbnail(self):
        self.pub.post_youtube(self.video, self.cover, {"title": "t"}, when=2000000000)
        up = next(c for c in self.calls if c[1] == "videos" and c[0] == "POST")
        self.assertNotIn("publishAt", up[3])
        self.assertIn("publishAt", self.calls[-1][3])

    def test_youtube_without_the_edit_permission_stays_private_and_says_so(self):
        real = self.http

        def no_edit(method, url, **k):
            if "videos?part=status" in url:
                raise publish.PostError("403: insufficient scopes")
            return real(method, url, **k)
        mock.patch.object(publish, "http", no_edit).start()
        with self.assertRaises(publish.PostError) as c:
            self.pub.post_youtube(self.video, self.cover, {"title": "t"})
        self.assertIn("still private", str(c.exception))
        self.assertIn("youtube.com/shorts/y1", str(c.exception))

    def test_youtube_schedule_that_passed_during_the_upload_opens_now(self):
        self.pub.post_youtube(self.video, self.cover, {"title": "t"}, when=int(publish.time.time()) + 30)
        self.assertEqual(self.calls[-1][3]["privacyStatus"], "public")
        self.assertNotIn("publishAt", self.calls[-1][3])

    def test_youtube_thumbnail_timeout_is_a_refusal_too(self):
        real = self.http

        def slow(method, url, **k):
            if "thumbnails" in url:
                raise TimeoutError("timed out")
            return real(method, url, **k)
        mock.patch.object(publish, "http", slow).start()
        with self.assertRaises(publish.PostError):
            self.pub.post_youtube(self.video, self.cover, {"title": "t"})

    def test_facebook_refused_thumbnail_leaves_only_a_draft(self):
        self.thumb_ok = False
        finishes = []
        real = self.http

        def watch(method, url, data=None, **k):
            if data and data.get("upload_phase") == "finish":
                finishes.append(data["video_state"])
            return real(method, url, data=data, **k)
        mock.patch.object(publish, "http", watch).start()
        with self.assertRaises(publish.PostError) as c:
            self.pub.post_facebook(self.video, self.cover, {"caption": "hi"})
        self.assertEqual(finishes, ["DRAFT"])
        self.assertIn("draft", str(c.exception))

    def test_facebook_check_after_publishing_never_fails_the_post(self):
        n = []
        real = self.http

        def second_fails(method, url, **k):
            if "thumbnails" in url:
                n.append(1)
                if len(n) > 1:
                    raise publish.PostError("400: busy")
            return real(method, url, **k)
        mock.patch.object(publish, "http", second_fails).start()
        link, extra = self.pub.post_facebook(self.video, self.cover, {"caption": "hi"})
        self.assertTrue(link.endswith("/f1"))

    def test_nothing_is_posted_without_a_thumbnail(self):
        folder = Path(self.pub.root, "approved", "clip")
        folder.mkdir(parents=True)
        (folder / "edit.mp4").write_bytes(b"v")
        self.pub.accounts.summary = lambda ch="": {p: {"connected": True} for p in publish.PLATFORMS}
        with self.assertRaises(publish.PostError) as c:
            self.pub.start(str(folder), {"youtube": {"title": "t"}})
        self.assertIn("thumbnail", str(c.exception))


if __name__ == "__main__":
    unittest.main()
