import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channels import folder_channel


class FolderChannelTests(unittest.TestCase):
    def folder(self, text=None, parent=None):
        root = Path(tempfile.mkdtemp())
        clip = root / "clip"
        (clip / "topic").mkdir(parents=True)
        if parent is not None:
            (clip / "channel.txt").write_text(parent, encoding="utf-8")
        if text is not None:
            (clip / "topic" / "channel.txt").write_text(text, encoding="utf-8")
        return str(clip / "topic")

    def test_main_is_the_main_channel(self):
        # agents tag main-channel work "main" (the board's key): the posting screen must look up the main accounts
        self.assertEqual(folder_channel(self.folder("main")), "")
        self.assertEqual(folder_channel(self.folder("main\n")), "")
        self.assertEqual(folder_channel(self.folder(parent="main")), "")

    def test_other_channels_and_no_file(self):
        self.assertEqual(folder_channel(self.folder("pong-gospel")), "pong-gospel")
        self.assertEqual(folder_channel(self.folder(parent="pong-gospel")), "pong-gospel")
        self.assertEqual(folder_channel(self.folder("")), "")
        self.assertEqual(folder_channel(self.folder()), "")


if __name__ == "__main__":
    unittest.main()
