"""Video-title binding tests with temporary local evidence and no model calls."""
import json
import unittest
from pathlib import Path
from unittest import mock

import test_thumbnail_posts as posts
from test_sermon_design import Handler
from thumbnail_design import BASE, DesignError, digest


class SourceTests(unittest.TestCase):
    setUp = posts.PostTests.setUp
    tearDown = posts.PostTests.tearDown
    add_task = posts.PostTests.add_task
    template = posts.PostTests.template
    body = posts.PostTests.body
    start = posts.PostTests.start
    output = posts.PostTests.output
    finish = posts.PostTests.finish

    def video(self, title="一句话的力量 · Facebook + Instagram", name="edit.mp4", channel="", folder="real-video"):
        base = self.office / "out" / folder; base.mkdir(parents=True, exist_ok=True)
        file = base / name; file.write_bytes(b"synthetic local video bytes " + name.encode())
        if title is not None: (base / "post.md").write_text("# " + title + "\n\n## Captions\n### Option 1\nTitle: Alternate draft one\nCaption one\n### Option 2\nTitle: Alternate draft two\nCaption two", encoding="utf-8")
        if not any(t.get("note") == "out:" + folder for t in self.tasks):
            self.tasks.append({"id": "t" + str(len(self.tasks) + 1), "status": "review", "title": "Audio fix · operational task label", "channel": channel, "note": "out:" + folder})
        return base, file
    def source(self, channel=""):
        return self.bridge.sources(channel)["sources"][0]
    def linked(self, source):
        return {k: source[k] for k in ("sourceId", "titleRevision")}

    def test_sources_are_read_only_authoritative_and_strip_only_platform_suffix(self):
        self.video()
        handler = Handler(BASE + "/sources?channel="); self.bridge.handle(handler)
        source = handler.payload["sources"][0]
        self.assertEqual(source["title"], "一句话的力量")
        self.assertEqual(source["titleSource"], "post.md")
        self.assertEqual(source["videoUrl"], "/files/out/real-video/edit.mp4")
        self.assertEqual(len(source["sourceId"]), 64)
        self.assertEqual(self.source()["titleRevision"], source["titleRevision"])
        self.assertFalse(self.engine.calls)
        self.assertEqual(len(self.tasks), 2)

    def test_semantic_middle_dot_not_removed_and_draft_option_one_not_guessed(self):
        self.video("只把我所有的给你 · 灯塔")
        source = self.source()
        self.assertEqual(source["title"], "只把我所有的给你 · 灯塔")
        self.assertNotIn("Alternate draft", source["title"])

    def test_edit_and_clean_variants_share_title_but_distinct_source_identity(self):
        self.video(); self.video(name="clean.mp4")
        sources = self.bridge.sources("")["sources"]
        self.assertEqual(len(sources), 2)
        self.assertEqual({s["title"] for s in sources}, {"一句话的力量"})
        self.assertEqual(len({s["sourceId"] for s in sources}), 2)

    def test_unrelated_multi_video_folder_has_no_guessed_shared_title(self):
        self.video(name="video1.mp4"); base, _ = self.video(name="video2.mp4")
        sources = self.bridge.sources("")["sources"]
        self.assertTrue(all(not s["title"] and s["warnings"] for s in sources))
        (base / "video2.metadata.json").write_text(json.dumps({"title": "Second exact video", "subtitle": "Exact English"}))
        sources = self.bridge.sources("")["sources"]
        self.assertEqual([s["title"] for s in sources], ["", "Second exact video"])
        self.assertEqual(sources[1]["subtitle"], "Exact English")

    def test_explicit_owner_caption_pick_is_used_but_unpicked_options_never_are(self):
        base, _ = self.video()
        self.assertEqual(self.source()["title"], "一句话的力量")
        (base / "package.json").write_text('{"preset":"full","caption":1}')
        source = self.source()
        self.assertEqual(source["title"], "Alternate draft two")
        self.assertEqual({e["path"] for e in source["titleEvidence"]}, {"post.md", "package.json"})

    def test_missing_title_never_uses_task_label_or_template_words(self):
        self.video(title=None)
        source = self.source()
        self.assertEqual(source["title"], "")
        with self.assertRaisesRegex(DesignError, "no unambiguous"):
            self.start(sourceVideo=self.linked(source), title="Golden Apple")
        self.assertFalse(self.engine.calls)

    def test_known_channel_required_and_cross_brand_sources_never_link(self):
        base, _ = self.video(channel=None)
        self.assertEqual(self.bridge.sources("")["sources"], [])
        (base / "channel.txt").write_text("pong-gospel")
        pong = self.source("pong-gospel")
        with self.assertRaisesRegex(DesignError, "changed"):
            self.start(sourceVideo=self.linked(pong))
        self.assertFalse(self.engine.calls)
        (base / "channel.txt").write_text("unknown-brand")
        self.assertEqual(self.bridge.sources("")["sources"], [])

    def test_legacy_main_alias_validates_without_loosening_review_guard(self):
        base, _ = self.video(channel="")
        self.tasks[-1]["note"] += " channel:main"
        context = self.bridge.context("out/real-video")
        self.assertTrue(context["channelKnown"])
        self.assertEqual(context["channel"], "")
        self.assertEqual(context["videos"][0]["title"], "一句话的力量")
        self.tasks[-1]["status"] = "doing"
        self.assertEqual(len(self.bridge.sources("main")["sources"]), 1)
        with self.assertRaisesRegex(DesignError, "review"):
            self.bridge.context("out/real-video", self.tasks[-1]["id"])
        self.tasks[-1]["note"] = "out:real-video channel:unknown-brand"
        with self.assertRaises(DesignError): self.bridge.context("out/real-video", self.tasks[-1]["id"])

    def test_linked_post_overrides_client_template_headline_and_freezes_source(self):
        self.video(); source = self.source()
        ident = self.start(sourceVideo=self.linked(source), title="Wrong template headline", subtitle="Wrong template subtitle")
        request = self.engine.jobs[ident]["request"]
        self.assertEqual(request["title"], source["title"])
        self.assertEqual(request["subtitle"], source["subtitle"])
        self.assertEqual(request["provenance"]["sourceVideo"], source)
        self.assertNotIn("approvedAt", request["provenance"])
        same = self.start(sourceVideo=self.linked(source), title="ignored client words")
        self.assertEqual(same, ident)
        job = self.finish(ident)
        self.assertEqual(job["status"], "delivered")
        self.assertEqual(job["sourceVideo"]["titleRevision"], source["titleRevision"])
        manifest = json.loads((self.office / job["delivery"]["folder"] / "thumbnail-final.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["postRequest"]["sourceVideo"], source)
        self.assertTrue(all(t["status"] == "review" for t in self.tasks))

    def test_source_title_or_bytes_changes_reject_stale_before_dispatch(self):
        base, file = self.video(); source = self.source()
        (base / "post.md").write_text("# New exact title", encoding="utf-8")
        with self.assertRaisesRegex(DesignError, "changed"):
            self.start(sourceVideo=self.linked(source))
        current = self.source()
        self.assertEqual(current["sourceId"], source["sourceId"])
        self.assertNotEqual(current["titleRevision"], source["titleRevision"])
        file.write_bytes(b"new video bytes")
        with self.assertRaisesRegex(DesignError, "changed"):
            self.start(sourceVideo=self.linked(current))
        self.assertFalse(self.engine.calls)

    def test_frozen_linked_title_change_blocks_delivery_without_model_replay(self):
        base, _ = self.video(); source = self.source()
        ident = self.start(sourceVideo=self.linked(source))
        (base / "post.md").write_text("# changed source title", encoding="utf-8")
        self.assertEqual(self.finish(ident)["status"], "delivery-error")
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 1)

    def test_approval_binding_checks_exact_video_and_staleness(self):
        base, file = self.video(); source = self.source()
        body = {"approval": True, "folder": "out/real-video", "taskId": self.tasks[-1]["id"], "channel": "", "videoPath": "edit.mp4", "videoSha256": digest(file), "title": "wrong client title", "sourceVideo": self.linked(source)}
        with mock.patch.object(self.bridge, "_frame", return_value=None):
            job = self.bridge.approve_video(body)["job"]
        self.assertEqual(job["title"], source["title"])
        self.assertEqual(job["sourceVideo"]["sourceId"], source["sourceId"])
        (base / "post.md").write_text("# changed")
        with self.assertRaisesRegex(DesignError, "changed"):
            self.bridge.approve_video(body)
        self.assertEqual(sum(m == "POST" for m, _ in self.engine.calls), 1)

    def test_changed_title_during_reference_preparation_cannot_dispatch(self):
        base, file = self.video(); source = self.source()
        body = {"approval": True, "folder": "out/real-video", "taskId": self.tasks[-1]["id"], "channel": "", "videoPath": "edit.mp4", "videoSha256": digest(file), "sourceVideo": self.linked(source)}
        with mock.patch.object(self.bridge, "_frame", side_effect=lambda *args: (base / "post.md").write_text("# Changed during preparation")):
            with self.assertRaisesRegex(DesignError, "changed"):
                self.bridge.approve_video(body)
        self.assertFalse(any(m == "POST" for m, _ in self.engine.calls))
        self.assertFalse(self.bridge._load()["jobs"])

    def test_sources_exclude_artwork_tasks_and_unowned_folders(self):
        for folder in ("thumbnail-final-abc", "sermon-studio-abc", "unowned"):
            base, _ = self.video(folder=folder)
        self.tasks = [t for t in self.tasks if t.get("note") != "out:unowned"]
        self.assertEqual(self.bridge.sources("")["sources"], [])

    def test_all_validated_owners_are_exposed_without_foreign_task_ids(self):
        self.video()
        primary = self.tasks[-1]["id"]
        self.tasks.append({"id": "second-owner", "status": "review", "channel": "", "note": "out:real-video", "title": "Second legitimate review"})
        self.tasks.append({"id": "foreign-task", "status": "review", "channel": "pong-gospel", "note": "out:another-folder", "title": "Unrelated"})
        source = self.source()
        self.assertEqual(source["taskId"], primary)
        self.assertEqual(source["taskIds"], [primary, "second-owner"])
        context = self.bridge.context("out/real-video", "second-owner")
        self.assertEqual(context["taskId"], "second-owner")
        self.assertIn("second-owner", context["sources"][0]["taskIds"])
        with self.assertRaisesRegex(DesignError, "does not own"):
            self.bridge.context("out/real-video", "foreign-task")


if __name__ == "__main__": unittest.main()
