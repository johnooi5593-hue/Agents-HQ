"""Post a video: the owner's ready-made video, own thumbnail and caption (owner, 2026-11-13)."""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish
import ready_post

FF = shutil.which("ffmpeg")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 600
JPG = b"\xff\xd8\xff\xe0" + b"0" * 600


class ReadyPostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "approved").mkdir()
        self.tasks = []

        def task_action(body):
            self.tasks.append(body)
            return 201, {"added": {"id": "t77"}}
        self.board = {"tasks": [{"id": "t77", "status": "review", "note": "out:clip"}, {"id": "t5", "status": "cancelled", "note": "out:other"}]}
        self.rp = ready_post.ReadyPosts(str(self.root), task_action, channel_ok=lambda k: k == "pong", max_upload=5000, load_tasks=lambda: self.board)

    def upload(self, name="My Video (final).mp4", data=b"v" * 1000, channel=""):
        return self.rp.save_video(name, channel, len(data), io.BytesIO(data))

    def test_a_video_lands_in_its_own_approved_folder_with_a_card(self):
        st = self.upload(channel="pong")
        d = self.root / "approved" / "my-video-final"
        self.assertEqual((st["name"], st["folder"], st["video"], st["task"], st["channel"]), ("my-video-final", "approved/my-video-final", "final.mp4", "t77", "pong"))
        self.assertEqual((d / "final.mp4").read_bytes(), b"v" * 1000)
        self.assertEqual((d / "channel.txt").read_text(encoding="utf-8"), "pong")
        add = self.tasks[0]
        self.assertEqual((add["action"], add["note"], add["status"], add["team"], add["channel"]), ("add", "out:my-video-final", "review", "Social", "pong"))
        self.assertEqual(publish.media_files(str(d))["video"], ["final.mp4"])                 # the posting screen finds it

    def test_the_same_name_twice_gets_its_own_folder(self):
        self.upload("clip.mp4")
        (self.root / "out" / "clip-2").mkdir(parents=True)                                    # taken by the office
        self.assertEqual(self.upload("clip.mp4")["name"], "clip-3")
        self.assertEqual((self.root / "approved" / "clip" / "final.mp4").read_bytes(), b"v" * 1000)   # the first is untouched

    def test_bad_uploads_are_refused(self):
        for name, data, channel in (("x.exe", b"v", ""), ("../x.mp4", b"v", ""), ("x.mp4", b"", ""), ("x.mp4", b"v" * 6000, ""),
                                    ("x.mp4", b"v", "nope"), (".mp4", b"v", ""), ("a/b.mp4", b"v", "")):
            with self.assertRaises(ready_post.ReadyError, msg=name):
                self.upload(name, data, channel)
        self.assertEqual((list((self.root / "approved").iterdir()), self.tasks), ([], []))

    def test_an_upload_that_stops_halfway_is_not_a_video(self):
        with self.assertRaises(ready_post.ReadyError):
            self.rp.save_video("clip.mp4", "", 1000, io.BytesIO(b"v" * 400))
        d = self.root / "approved" / "clip"
        self.assertFalse((d / "final.mp4").exists())
        self.assertFalse((d / "ready.json").exists())
        self.assertEqual(self.tasks, [])

    def test_only_folders_made_here_can_be_changed(self):
        office = self.root / "approved" / "office-edit"
        office.mkdir()
        (office / "edit.mp4").write_bytes(b"v")
        for name in ("office-edit", "..", "nope", "a/b", ""):
            for call in (lambda n: self.rp.save_cover(n, "c.png", len(PNG), io.BytesIO(PNG)), lambda n: self.rp.save_caption(n, "T", "c"),
                         lambda n: self.rp.frame_cover(n, 1), lambda n: self.rp.state(n)):
                with self.assertRaises(ready_post.ReadyError, msg=name):
                    call(name)
        self.assertEqual(sorted(p.name for p in office.iterdir()), ["edit.mp4"])

    def test_the_owners_thumbnail_and_an_earlier_one_is_kept(self):
        name = self.upload("clip.mp4")["name"]
        d = self.root / "approved" / name
        self.assertEqual(self.rp.save_cover(name, "pic.PNG", len(PNG), io.BytesIO(PNG))["cover"], "cover.png")
        self.assertEqual(self.rp.save_cover(name, "pic.jpeg", len(JPG), io.BytesIO(JPG))["cover"], "cover.jpg")
        self.assertEqual((d / "cover.jpg").read_bytes(), JPG)
        earlier = [p for p in d.iterdir() if p.name.startswith("earlier-thumbnail-")]
        self.assertEqual([p.read_bytes() for p in earlier], [PNG])
        self.assertEqual(publish.media_files(str(d))["image"][0], "cover.jpg")                # the new one is the default pick
        for fn, data in (("pic.gif", PNG), ("pic.png", b"<svg>" * 200), ("pic.png", b""), ("pic.jpg", PNG[:-1] + b"")):
            if fn == "pic.jpg":
                continue
            with self.assertRaises(ready_post.ReadyError):
                self.rp.save_cover(name, fn, len(data), io.BytesIO(data))
        self.assertEqual((d / "cover.jpg").read_bytes(), JPG)

    def test_the_caption_becomes_the_posting_screens_one_option(self):
        name = self.upload("clip.mp4")["name"]
        d = self.root / "approved" / name
        st = self.rp.save_caption(name, "  My   title ", "first line\r\n第二行\n#tag #标签")
        self.assertEqual((st["title"], st["caption"]), ("My title", "first line\n第二行\n#tag #标签"))
        dr = publish.drafts(str(d))
        self.assertEqual(len(dr["options"]), 1)
        self.assertEqual((dr["options"][0]["title"], dr["options"][0]["caption"]), ("My title", "first line\n第二行\n#tag #标签"))
        for title, caption in (("", "c"), ("t", ""), ("t" * 101, "c"), ("t", "c" * 2201), ("t", "line\n## Captions\nx"), ("# t", "c")):
            with self.assertRaises(ready_post.ReadyError):
                self.rp.save_caption(name, title, caption)
        self.assertEqual(self.rp.state(name)["title"], "My title")

    def test_posting_moves_the_card_to_done_and_ignores_other_folders(self):
        name = self.upload("clip.mp4")["name"]
        self.rp.posting(str(self.root / "approved" / name))
        self.assertEqual(self.tasks[-1], {"action": "move", "id": "t77", "status": "done"})
        office = self.root / "approved" / "office-edit"
        office.mkdir()
        self.rp.posting(str(office))
        self.assertEqual(len(self.tasks), 2)
        # a planted ready.json never moves another video's task, or one that is not waiting
        (office / "ready.json").write_text(json.dumps({"video": "final.mp4", "task": "t5"}), encoding="utf-8")
        self.rp.posting(str(office))
        (office / "ready.json").write_text(json.dumps({"video": "final.mp4", "task": "t77"}), encoding="utf-8")
        self.rp.posting(str(office))
        self.assertEqual(len(self.tasks), 2)

    def test_a_planted_ready_json_cannot_point_the_frame_at_another_file(self):
        secret = self.root / "private.jpg"
        secret.write_bytes(JPG)
        other = self.root / "approved" / "planted"
        other.mkdir()
        for video in (str(secret), "../../private.jpg", "..\\..\\private.jpg", "final.mp4/../../../private.jpg", "edit.mp4", ""):
            (other / "ready.json").write_text(json.dumps({"video": video}), encoding="utf-8")
            with self.assertRaises(ready_post.ReadyError, msg=video):
                self.rp.frame_cover("planted", 0)
        self.assertEqual(sorted(p.name for p in other.iterdir()), ["ready.json"])

    def test_no_kind_of_line_break_smuggles_a_section_into_the_caption(self):
        name = self.upload("clip.mp4")["name"]
        for brk in ("\r", "\u2028", "\u2029", "\x0b", "\x0c", "\x85"):
            with self.assertRaises(ready_post.ReadyError, msg=repr(brk)):
                self.rp.save_caption(name, "T", "hi" + brk + "## YouTube" + brk + "other text")
        self.assertEqual(self.rp.save_caption(name, "T", "a\rb\u2028c")["caption"], "a\nb\nc")

    def test_names_never_end_in_a_dot_or_a_space(self):
        for bad in ("clip.", "clip ", "clip.mp4.", "clip.mp4 "):
            with self.assertRaises(ready_post.ReadyError, msg=bad):
                self.upload(bad)
            with self.assertRaises(ready_post.ReadyError, msg=bad):
                self.rp.state(bad)

    @unittest.skipUnless(FF, "ffmpeg is needed")
    def test_a_frame_of_the_video_as_the_thumbnail(self):
        src = self.root / "src.mp4"
        subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=10:duration=2", "-pix_fmt", "yuv420p", str(src)], check=True)
        rp = ready_post.ReadyPosts(str(self.root), lambda b: (201, {"added": {"id": "t1"}}))
        data = src.read_bytes()
        name = rp.save_video("clip.mp4", "", len(data), io.BytesIO(data))["name"]
        st = rp.frame_cover(name, 1.0)
        cover = self.root / "approved" / name / "cover.jpg"
        self.assertEqual(st["cover"], "cover.jpg")
        self.assertTrue(cover.read_bytes().startswith(b"\xff\xd8\xff"))
        for bad in ("soon", -1, None, 99999999):
            with self.assertRaises(ready_post.ReadyError):
                rp.frame_cover(name, bad)
        with self.assertRaises(ready_post.ReadyError):
            rp.frame_cover(name, 500)                                                         # past the end: no frame
        self.assertTrue(cover.is_file())


if __name__ == "__main__":
    unittest.main()
