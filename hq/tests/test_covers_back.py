import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import covers_back


def names(done, folder):
    return sorted(Path(p).name for p in done if Path(p).parent == folder)


class CoversBackTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.drive = self.root / "drive"
        for week in ("1107 08", "1114", "1205 06", "notes"):
            (self.drive / week).mkdir(parents=True)
        self.ch = {"key": "pong-gospel", "drive": str(self.drive), "coversBack": True}

    def approved(self, name, heading="# 不是没有人陪伴你，而是没有一个人懂你 · Pong+Gospel 11/08", covers=("cover-codex.png", "cover-codex-ig.png")):
        d = self.root / "approved" / name
        d.mkdir(parents=True)
        (d / "post.md").write_text(heading + "\n## Plan\n", encoding="utf-8")
        for c in covers:
            (d / c).write_bytes(c.encode())
        return d

    def test_week_folder_holds_both_dates(self):
        self.assertEqual(Path(covers_back.week_folder(str(self.drive), "1108")).name, "1107 08")
        self.assertEqual(Path(covers_back.week_folder(str(self.drive), "1107")).name, "1107 08")
        self.assertEqual(Path(covers_back.week_folder(str(self.drive), "1206")).name, "1205 06")
        self.assertEqual(Path(covers_back.week_folder(str(self.drive), "1114")).name, "1114")
        self.assertIsNone(covers_back.week_folder(str(self.drive), "1121"))

    def test_both_covers_go_to_the_week_folder(self):
        d = self.approved("pong-gospel-1108-you-are-not-alone-v2")
        done = covers_back.copy_back(str(self.root), d.name, "pong-gospel", self.ch)
        week = self.drive / "1107 08"
        self.assertEqual(names(done, week), ["1108_不是没有人陪伴你_3x4.png", "1108_不是没有人陪伴你_9x16.png"])
        self.assertEqual((week / "1108_不是没有人陪伴你_9x16.png").read_bytes(), b"cover-codex.png")
        self.assertEqual((week / "1108_不是没有人陪伴你_3x4.png").read_bytes(), b"cover-codex-ig.png")
        self.assertEqual(len(json.loads((d / "covers-back.json").read_text(encoding="utf-8"))["copied"]), 4)   # week + date folder
        # a newer cover replaces the same name, nothing else appears
        (d / "cover-codex.png").write_bytes(b"new")
        covers_back.copy_back(str(self.root), d.name, "pong-gospel", self.ch)
        self.assertEqual((week / "1108_不是没有人陪伴你_9x16.png").read_bytes(), b"new")
        self.assertEqual(len(list(week.iterdir())), 2)

    def test_the_complete_set_goes_back(self):
        d = self.approved("pong-gospel-1108-you-are-not-alone-v2")
        (d / "edit.mp4").write_bytes(b"video")
        (d / "package.json").write_text('{"caption": 1}', encoding="utf-8")
        (d / "post.md").write_text("# 不是没有人陪伴你，而是没有一个人懂你 · Pong+Gospel 11/08\n## Plan\n- Post to: all\n## Captions\n"
                                   "### Option 1\nTitle: A\n第一\n#一\n### Option 2\nTitle: B\n第二\n#二\n## TikTok\n抖音 #t\n## Pinned comment\n留言\n", encoding="utf-8")
        done = covers_back.copy_back(str(self.root), d.name, "pong-gospel", self.ch)
        week = self.drive / "1107 08"
        self.assertEqual(names(done, week), ["1108_不是没有人陪伴你.mp4", "1108_不是没有人陪伴你_3x4.png", "1108_不是没有人陪伴你_9x16.png", "1108_不是没有人陪伴你_captions.txt"])
        self.assertEqual((week / "1108_不是没有人陪伴你.mp4").read_bytes(), b"video")
        text = (week / "1108_不是没有人陪伴你_captions.txt").read_text(encoding="utf-8")
        self.assertTrue(text.index("Title: B") < text.index("抖音") < text.index("留言") < text.index("Title: A"))   # the chosen caption first
        self.assertIn("#二", text); self.assertIn("== Caption (Option 2) ==", text); self.assertNotIn("Post to", text)
        # and the same set in the finished date folder beside the raw folders (PONG/1108/), made when missing
        self.assertEqual(names(done, self.root / "1108"), names(done, week))
        self.assertEqual((self.root / "1108" / "1108_不是没有人陪伴你.mp4").read_bytes(), b"video")

    def test_a_video_without_covers_still_goes_back(self):
        d = self.approved("pong-gospel-1114-dont-be-strong-alone", covers=())
        (d / "edit.mp4").write_bytes(b"video")
        done = covers_back.copy_back(str(self.root), d.name, "pong-gospel", self.ch)
        self.assertEqual(names(done, self.drive / "1114"), ["1114_不是没有人陪伴你.mp4"])            # no caption text yet: no captions file

    def test_nothing_without_opt_in_covers_or_a_week(self):
        d = self.approved("pong-gospel-1114-dont-be-strong-alone")
        self.assertEqual(covers_back.copy_back(str(self.root), d.name, "", dict(self.ch, key="")), [])        # the main channel
        self.assertEqual(covers_back.copy_back(str(self.root), d.name, "pong-gospel", dict(self.ch, coversBack=False)), [])
        self.assertEqual(covers_back.copy_back(str(self.root), d.name, "pong-gospel", None), [])
        none = self.approved("pong-gospel-1114-no-covers", covers=())
        self.assertEqual(covers_back.copy_back(str(self.root), none.name, "pong-gospel", self.ch), [])
        later = self.approved("pong-gospel-1121-love-is-not-a-trade")                                      # no 1121 folder
        self.assertEqual(covers_back.copy_back(str(self.root), later.name, "pong-gospel", self.ch), [])
        self.assertEqual(list((self.drive / "1114").iterdir()), [])

    def test_title_is_the_first_phrase_without_file_name_characters(self):
        d = self.approved("pong-gospel-1205-x", heading='# 你现在的"隐藏"不是失败: 而是 · Pong+Gospel 12/05')
        self.assertEqual(covers_back.title_of(str(d)), "你现在的隐藏不是失败")


if __name__ == "__main__":
    unittest.main()
