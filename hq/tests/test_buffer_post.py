"""Instagram + TikTok through Buffer (owner, 2026-11-09): the cover as frame 1 of the video, one caption for both, the
Buffer package next to the approved video, Buffer's GraphQL calls and the public media host. Real ffmpeg on a tiny
synthetic clip; Buffer and the bucket are small fake HTTP servers on 127.0.0.1. Nothing reaches the internet."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import buffer_post
import cover_flash
import publish

FF = cover_flash.ffmpeg_path()
W, H, FPS, SECS = 540, 960, 30, 2


def make_clip(path, color="0x204080"):
    """A 2-second 540x960 test clip with a tone, like a small reel."""
    subprocess.run([FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(SECS), "-c:v", "libx264", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path], check=True, capture_output=True)


def make_cover(path, size, color):
    subprocess.run([FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:size={size}",
                    "-frames:v", "1", path], check=True, capture_output=True)


@unittest.skipUnless(FF, "ffmpeg is needed")
class CoverFlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.clip = str(cls.root / "edit.mp4")
        cls.cover = str(cls.root / "cover.png")
        cls.cover34 = str(cls.root / "cover-ig.png")
        make_clip(cls.clip)
        make_cover(cls.cover, f"{W}x{H}", "0xE0B030")             # a yellow 9:16 cover
        make_cover(cls.cover34, "540x720", "0x30B0E0")              # a blue 3:4 cover

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_probe_reads_the_clip(self):
        info = cover_flash.probe(self.clip)
        self.assertTrue(info["ok"], info)
        self.assertEqual((info["width"], info["height"], info["fps"], info["audio"]), (W, H, "30/1", True))
        self.assertAlmostEqual(info["duration"], SECS, delta=0.1)

    def test_the_cover_is_the_first_frames_and_nothing_else_changes(self):
        out = str(self.root / "flash.mp4")
        seen = []
        r = cover_flash.make(self.clip, self.cover, out, frames=3, progress=seen.append)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["frames"], 3)
        self.assertAlmostEqual(r["hold"], 0.1, places=3)
        self.assertEqual(r["start"], 0.0)                                        # picture from the very first instant, in step with the sound
        self.assertEqual(r["total_frames"], r["source_frames"] + 3)             # the edit's frames, plus exactly the flash
        self.assertTrue(seen and 0 <= min(seen) <= max(seen) <= 99)
        v = cover_flash.verify(out, self.cover, 3)
        self.assertTrue(v["ok"], v)
        self.assertLess(v["first"], 5)                                          # frame 0 is the cover
        self.assertLess(v["last"], 5)                                           # so is frame 2
        want = cover_flash._raw_frame(FF, self.cover, W, H, image=True)
        fourth = cover_flash._raw_frame(FF, out, W, H, 3)
        self.assertGreater(cover_flash.distance(want, fourth), cover_flash.MATCH)   # frame 3 is the edit again
        done = cover_flash.probe(out)
        self.assertTrue(done["audio"])                                           # sound kept (silence under the flash)
        self.assertEqual(done["fps"], "30/1")
        info = subprocess.run([cover_flash.ffprobe_path(), "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", out], capture_output=True, text=True).stdout
        self.assertIn("h264", info)
        self.assertIn("aac", info)

    def test_a_3x4_cover_sits_whole_in_the_middle(self):
        out = str(self.root / "flash34.mp4")
        r = cover_flash.make(self.clip, self.cover34, out, frames=2)
        self.assertTrue(r["ok"], r)
        v = cover_flash.verify(out, self.cover34, 2)
        self.assertTrue(v["ok"], v)
        frame = cover_flash._raw_frame(FF, out, W, H, 0)
        mid = frame[(H // 2 * W + W // 2) * 3:(H // 2 * W + W // 2) * 3 + 3]       # the middle pixel: the blue cover
        self.assertGreater(mid[2], 150)
        self.assertLess(mid[0], 90)

    def test_verify_refuses_the_wrong_cover_and_the_plain_edit(self):
        out = str(self.root / "flash2.mp4")
        self.assertTrue(cover_flash.make(self.clip, self.cover, out, frames=3)["ok"])
        self.assertFalse(cover_flash.verify(out, self.cover34, 3)["ok"])
        self.assertFalse(cover_flash.verify(self.clip, self.cover, 3)["ok"])

    def test_missing_files_fail_softly(self):
        self.assertFalse(cover_flash.make(str(self.root / "nope.mp4"), self.cover, str(self.root / "x.mp4"))["ok"])
        self.assertFalse(cover_flash.make(self.clip, str(self.root / "nope.png"), str(self.root / "x.mp4"))["ok"])

    def test_an_edit_that_switches_colour_range_part_way_still_encodes(self):
        """Clips joined from a phone (full range) and a camera (TV range): ffmpeg used to stop dead at the switch."""
        parts = []
        for i, (fmt, rng) in enumerate((("yuvj420p", "pc"), ("yuv420p", "tv"), ("yuvj420p", "pc"))):
            part = str(self.root / f"mix{i}.ts")
            subprocess.run([FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:v", "libx264", "-preset", "veryfast",
                            "-pix_fmt", fmt, "-color_range", rng, "-c:a", "aac", "-shortest", part], check=True, capture_output=True)
            parts.append(part)
        mixed = str(self.root / "mixed.mp4")
        subprocess.run([FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", "concat:" + "|".join(parts), "-c", "copy", mixed],
                       check=True, capture_output=True)
        out = str(self.root / "mixed-out.mp4")
        r = cover_flash.make(mixed, self.cover, out, frames=3, stall=20)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["total_frames"], r["source_frames"] + 3)
        self.assertTrue(cover_flash.verify(out, self.cover)["ok"])

    def test_an_encode_that_stops_moving_is_stopped_and_said(self):
        def frozen(cmd, **kw):
            return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], **kw)
        began = time.time()
        r = cover_flash.make(self.clip, self.cover, str(self.root / "frozen.mp4"), popen=frozen, stall=1)
        self.assertFalse(r["ok"])
        self.assertIn("stopped moving", r["error"])
        self.assertLess(time.time() - began, 30)
        self.assertFalse(os.path.exists(str(self.root / "frozen.mp4")))
        self.assertFalse(os.path.exists(self.root / "x.mp4.part"))


@unittest.skipUnless(FF, "ffmpeg is needed")
class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "approved" / "clip"
        self.folder.mkdir(parents=True)
        self.clip, self.cover = str(self.folder / "edit.mp4"), str(self.folder / "cover.jpg")
        make_clip(self.clip)
        make_cover(self.cover, f"{W}x{H}", "0xE0B030")
        self.pk = buffer_post.CoverPackages(frames=3)

    def tearDown(self):
        self.temp.cleanup()

    def wait(self):
        job = self.pk.jobs[str(self.folder)]
        self.assertTrue(job["done"].wait(120))

    def test_the_package_is_made_in_the_background_with_its_texts(self):
        st = self.pk.start(str(self.folder), self.clip, self.cover, "一句话 #tag", "标题")
        self.assertEqual(st["state"], "making")
        self.wait()
        st = self.pk.state(str(self.folder), self.clip, self.cover)
        self.assertEqual(st["state"], "ready", st)
        d = self.folder / "buffer"
        self.assertEqual(set(st["files"].values()), {"buffer/final.mp4", "buffer/cover.jpg", "buffer/caption.txt", "buffer/title.txt"})
        self.assertEqual((d / "caption.txt").read_text(encoding="utf-8"), "一句话 #tag\n")
        self.assertEqual((d / "title.txt").read_text(encoding="utf-8"), "标题\n")
        meta = json.loads((d / "package.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["video"], meta["cover"], meta["frames"]), ("edit.mp4", "cover.jpg", 3))
        self.assertLess(meta["verify"]["first"], 5)
        self.assertTrue(cover_flash.verify(str(d / "final.mp4"), str(d / "cover.jpg"), 3)["ok"])   # cover.jpg is frame 1 itself

    def test_another_pick_makes_it_stale_and_texts_can_change(self):
        self.pk.start(str(self.folder), self.clip, self.cover, "a", "b"); self.wait()
        other = str(self.folder / "cover-codex.png")
        make_cover(other, f"{W}x{H}", "0x3030E0")
        self.assertEqual(self.pk.state(str(self.folder), self.clip, other)["state"], "stale")
        self.assertEqual(self.pk.state(str(self.folder), self.clip, self.cover)["state"], "ready")
        self.pk.start(str(self.folder), self.clip, self.cover, "new words", None)          # ready already: only the text changes
        self.assertEqual((self.folder / "buffer" / "caption.txt").read_text(encoding="utf-8"), "new words\n")
        self.assertEqual((self.folder / "buffer" / "title.txt").read_text(encoding="utf-8"), "b\n")
        self.pk.start(str(self.folder), self.clip, other); self.wait()
        self.assertEqual(self.pk.state(str(self.folder), self.clip, other)["state"], "ready")

    def test_a_second_start_while_making_does_not_start_twice(self):
        self.pk.start(str(self.folder), self.clip, self.cover)
        job = self.pk.jobs[str(self.folder)]
        self.pk.start(str(self.folder), self.clip, self.cover)
        self.assertIs(self.pk.jobs[str(self.folder)], job)
        self.wait()

    def test_ensure_makes_it_now_and_fails_loudly_without_a_cover(self):
        st = self.pk.ensure(str(self.folder), self.clip, self.cover, "c", "t")
        self.assertEqual(st["state"], "ready")
        with self.assertRaises(buffer_post.BufferError):
            self.pk.ensure(str(self.folder), self.clip, str(self.folder / "missing.png"))


class DraftsTests(unittest.TestCase):
    def test_tiktok_and_buffer_get_instagrams_words_and_the_title(self):
        d = tempfile.mkdtemp()
        Path(d, "post.md").write_text("# x\n\n## Captions\n### Option 1\nTitle: 别再坚强\n第一行\n#a #b\n### Option 2\nTitle: Two\nline\n#c\n\n## TikTok\nsomething else entirely #zz\n", encoding="utf-8")
        r = publish.drafts(d)
        for o in r["options"]:
            self.assertEqual(o["tiktok"]["caption"], o["instagram"]["caption"])
            self.assertEqual(o["buffer"]["caption"], o["instagram"]["caption"])
            self.assertEqual(o["buffer"]["title"], o["title"])
        self.assertEqual(r["options"][0]["buffer"]["title"], "别再坚强")
        self.assertNotIn("something else", r["options"][0]["tiktok"]["caption"])
        self.assertEqual(r["buffer"], r["options"][0]["buffer"])
        shutil.rmtree(d, ignore_errors=True)


class FakeBuffer(BaseHTTPRequestHandler):
    """A Buffer that answers the calls Agents HQ makes, and records what it was asked. gone: post ids deleted in Buffer."""
    calls, fail, status, gone = [], None, {}, set()

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeBuffer.calls.append({"auth": self.headers.get("Authorization"), "query": body.get("query", ""), "variables": body.get("variables") or {}})
        q = body.get("query", "")
        if FakeBuffer.fail == "key":
            out, code = {"data": None, "errors": [{"message": "Not authorized", "extensions": {"code": "UNAUTHORIZED"}}]}, 200
        elif FakeBuffer.fail == "401":
            out, code = {"message": "Unauthorized"}, 401
        elif "organizations" in q:
            out, code = {"data": {"account": {"organizations": [{"id": "org1", "name": "Church"}]}}}, 200
        elif q.startswith("query { channels"):
            out, code = {"data": {"channels": [{"id": "ch_ig", "name": "nlrcc", "displayName": "@nlrcc", "service": "instagram", "avatar": "", "isDisconnected": False, "isLocked": False, "isQueuePaused": False},
                                               {"id": "ch_tt", "name": "nlrcc.tv", "service": "tiktok", "avatar": "", "isDisconnected": False, "isLocked": False, "isQueuePaused": False},
                                               {"id": "ch_fb", "name": "Page", "service": "facebook", "avatar": "", "isDisconnected": True, "isLocked": False, "isQueuePaused": False}]}}, 200
        elif "createPost" in q:
            inp = body["variables"]["input"]
            if FakeBuffer.fail == "metadata" and inp.get("metadata"):
                out, code = {"data": {"createPost": {"message": "Variable \"$input\" got invalid value: Field \"metadata\" is not defined"}}}, 200
            elif FakeBuffer.fail == "tiktok" and inp["channelId"] == "ch_tt":
                out, code = {"data": {"createPost": {"message": "Failed to create post: channel is locked"}}}, 200
            else:
                out, code = {"data": {"createPost": {"post": {"id": "p_" + inp["channelId"], "status": "scheduled" if inp.get("dueAt") else "sending", "dueAt": inp.get("dueAt"), "externalLink": None}}}}, 200
        elif "editPost" in q:
            inp = body["variables"]["input"]
            if FakeBuffer.fail == "metadata" and inp.get("metadata"):
                out, code = {"data": {"editPost": {"message": "Field \"metadata\" is not defined"}}}, 200
            elif FakeBuffer.fail == "edit-tiktok" and inp["id"] == "p_ch_tt":
                out, code = {"data": {"editPost": {"message": "This post can no longer be edited"}}}, 200
            else:
                out, code = {"data": {"editPost": {"post": {"id": inp["id"], "status": "scheduled", "dueAt": inp.get("dueAt"), "externalLink": None}}}}, 200
        elif "deletePost" in q:
            pid = body["variables"]["input"]["id"]
            if pid in FakeBuffer.gone:
                out, code = {"data": {"deletePost": {"message": "Post not found"}}}, 200
            else:
                FakeBuffer.gone.add(pid)
                out, code = {"data": {"deletePost": {"id": pid}}}, 200
        elif q.startswith("query { post(") and q.split('"')[1] in FakeBuffer.gone:
            out, code = {"data": {"post": None}}, 200
        elif q.startswith("query { post("):
            pid = q.split('"')[1]
            out, code = {"data": {"post": dict({"id": pid, "status": "scheduled", "dueAt": None, "sentAt": None, "externalLink": None, "error": None}, **FakeBuffer.status.get(pid, {}))}}, 200
        else:
            out, code = {"data": None, "errors": [{"message": "unknown query"}]}, 200
        raw = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FakeBucket(BaseHTTPRequestHandler):
    """An S3-like bucket: PUT stores, GET (public) returns, DELETE removes. Records the signed headers."""
    store, puts = {}, []

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    @staticmethod
    def key(path):
        """The S3 endpoint is path-style (/<bucket>/<key>); the public address serves the key at its root."""
        return path.split("/", 2)[2] if path.count("/") >= 2 else path.lstrip("/")

    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        FakeBucket.puts.append({"path": self.path, "auth": self.headers.get("Authorization", ""), "sha": self.headers.get("x-amz-content-sha256"),
                                "date": self.headers.get("x-amz-date"), "ctype": self.headers.get("Content-Type"), "size": len(data)})
        if hashlib.sha256(data).hexdigest() != self.headers.get("x-amz-content-sha256"):
            return self._send(400, b"<Error><Code>XAmzContentSHA256Mismatch</Code><Message>hash</Message></Error>")
        if not self.headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256 Credential="):
            return self._send(403, b"<Error><Code>AccessDenied</Code><Message>no signature</Message></Error>")
        FakeBucket.store[self.key(self.path)] = data
        self._send(200)

    def do_GET(self):
        data = FakeBucket.store.get(self.path.lstrip("/"))
        if data is None:
            return self._send(404, b"<Error><Code>NoSuchKey</Code></Error>")
        self._send(200, data)

    def do_DELETE(self):
        FakeBucket.store.pop(self.key(self.path), None)
        self._send(204)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def to_local(base):
    """An opener that sends every request to the fake server instead, keeping method, body and headers."""
    def opener(req, timeout):
        path = urllib.request.urlparse(req.full_url).path or "/"
        local = urllib.request.Request(base + path, data=req.data, method=req.get_method(), headers=dict(req.header_items()))
        return urllib.request.urlopen(local, timeout=timeout)
    return opener


class BufferApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve(FakeBuffer)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeBuffer.calls, FakeBuffer.fail, FakeBuffer.status = [], None, {}
        self.api = buffer_post.Buffer("key123", opener=to_local(self.base))

    def test_channels_come_with_their_organization_and_service(self):
        chans = self.api.all_channels()
        self.assertEqual([(c["id"], c["service"], c["problem"]) for c in chans], [("ch_ig", "instagram", ""), ("ch_tt", "tiktok", ""), ("ch_fb", "facebook", "disconnected in Buffer")])
        self.assertEqual(chans[0]["name"], "@nlrcc")
        self.assertTrue(all(c["auth"] == "Bearer key123" for c in FakeBuffer.calls))

    def test_an_instagram_reel_now_and_a_tiktok_post_scheduled(self):
        p = self.api.create_post("ch_ig", "instagram", "words #tag", "https://pub.example/v.mp4", None, "Title", 50)
        self.assertEqual(p["id"], "p_ch_ig")
        inp = FakeBuffer.calls[-1]["variables"]["input"]
        self.assertEqual(inp["mode"], "shareNow")
        self.assertEqual(inp["schedulingType"], "automatic")
        self.assertNotIn("dueAt", inp)
        self.assertEqual(inp["assets"], [{"video": {"url": "https://pub.example/v.mp4", "metadata": {"thumbnailOffset": 50}}}])
        self.assertEqual(inp["metadata"], {"instagram": {"type": "reel", "shouldShareToFeed": True}})
        when = 1794621600                                                        # Sat 14 Nov 2026 10:00 in Malaysia = 02:00 UTC
        p = self.api.create_post("ch_tt", "tiktok", "words #tag", "https://pub.example/v.mp4", when, "A title that is long " * 6, 50)
        self.assertEqual(p["status"], "scheduled")
        inp = FakeBuffer.calls[-1]["variables"]["input"]
        self.assertEqual((inp["mode"], inp["dueAt"]), ("customScheduled", "2026-11-14T02:00:00.000Z"))
        self.assertEqual(inp["metadata"]["tiktok"]["title"], ("A title that is long " * 6)[:90])

    def test_unknown_metadata_is_tried_once_more_without_it(self):
        FakeBuffer.fail = "metadata"
        p = self.api.create_post("ch_ig", "instagram", "w", "https://pub.example/v.mp4")
        self.assertEqual(p["id"], "p_ch_ig")
        self.assertEqual(len(FakeBuffer.calls), 2)
        self.assertNotIn("metadata", FakeBuffer.calls[-1]["variables"]["input"])

    def test_a_refused_post_is_an_error_with_buffers_words(self):
        FakeBuffer.fail = "tiktok"
        with self.assertRaises(buffer_post.BufferError) as cm:
            self.api.create_post("ch_tt", "tiktok", "w", "https://pub.example/v.mp4")
        self.assertIn("channel is locked", str(cm.exception))

    def test_a_bad_key_says_so_both_ways(self):
        for how in ("key", "401"):
            FakeBuffer.fail = how
            with self.assertRaises(buffer_post.BufferError) as cm:
                self.api.organizations()
            self.assertIn("API key", str(cm.exception))

    def test_post_status_and_link(self):
        FakeBuffer.status["p_1"] = {"status": "sent", "externalLink": "https://www.instagram.com/reel/abc/"}
        p = self.api.post("p_1")
        self.assertEqual((p["status"], p["externalLink"]), ("sent", "https://www.instagram.com/reel/abc/"))


class MediaHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve(FakeBucket)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeBucket.store, FakeBucket.puts = {}, []
        self.cfg = {"endpoint": "https://acct.r2.cloudflarestorage.com", "bucket": "agents-hq-media", "access_key": "AKIDEXAMPLE",
                    "secret_key": "secret", "public_url": "https://pub-abc.r2.dev/"}
        self.host = buffer_post.MediaHost(self.cfg, opener=to_local(self.base), now=lambda: 1794600000)

    def test_config_is_checked(self):
        with self.assertRaises(buffer_post.BufferError):
            buffer_post.MediaHost(dict(self.cfg, secret_key=""))
        with self.assertRaises(buffer_post.BufferError):
            buffer_post.MediaHost(dict(self.cfg, public_url="http://pub-abc.r2.dev"))
        self.assertEqual(self.host.cfg["region"], "auto")
        self.assertEqual(self.host.cfg["prefix"], "agents-hq/")
        self.assertFalse(buffer_post.host_ready({}))
        self.assertTrue(buffer_post.host_ready(self.cfg))

    def test_keys_are_unguessable_and_names_safe(self):
        k = self.host.key("Pong+Gospel 1114 别再坚强.mp4")
        self.assertRegex(k, r"^agents-hq/[0-9a-f]{24}/Pong-Gospel-1114-\.mp4$")
        self.assertNotEqual(k, self.host.key("Pong+Gospel 1114 别再坚强.mp4"))
        self.assertEqual(self.host.url("agents-hq/x/a b.mp4"), "https://pub-abc.r2.dev/agents-hq/x/a%20b.mp4")

    def test_signature_v4_headers(self):
        url, h = self.host._sign("PUT", "agents-hq/abc/v.mp4", "0" * 64, "video/mp4", {"content-length": "5"}, when=1794600000)
        self.assertEqual(url, "https://acct.r2.cloudflarestorage.com/agents-hq-media/agents-hq/abc/v.mp4")
        self.assertEqual(h["x-amz-date"], "20261113T200000Z")
        self.assertTrue(h["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261113/auto/s3/aws4_request, SignedHeaders=content-length;content-type;host;x-amz-content-sha256;x-amz-date, Signature="), h["Authorization"])
        again = self.host._sign("PUT", "agents-hq/abc/v.mp4", "0" * 64, "video/mp4", {"content-length": "5"}, when=1794600000)
        self.assertEqual(h, again[1])                                                    # deterministic
        other = buffer_post.MediaHost(dict(self.cfg, secret_key="other"), now=lambda: 1794600000)._sign("PUT", "agents-hq/abc/v.mp4", "0" * 64, "video/mp4", {"content-length": "5"}, when=1794600000)
        self.assertNotEqual(h["Authorization"], other[1]["Authorization"])

    def test_put_check_and_delete_through_the_bucket(self):
        d = tempfile.mkdtemp()
        f = Path(d, "v.mp4"); f.write_bytes(b"movie" * 1000)
        seen = []
        url = self.host.put(str(f), "agents-hq/k1/v.mp4", "video/mp4", progress=seen.append, lo=41, hi=80)
        self.assertEqual(url, "https://pub-abc.r2.dev/agents-hq/k1/v.mp4")
        self.assertEqual(FakeBucket.puts[-1]["path"], "/agents-hq-media/agents-hq/k1/v.mp4")
        self.assertEqual(FakeBucket.puts[-1]["ctype"], "video/mp4")
        self.assertEqual(FakeBucket.puts[-1]["sha"], hashlib.sha256(b"movie" * 1000).hexdigest())
        self.assertTrue(seen and seen[0] >= 41 and abs(seen[-1] - 80) < 0.01)
        status, got = self.host.fetch_public(url, 10)
        self.assertEqual(got[:5], b"movie")
        checked = self.host.check()
        self.assertTrue(checked.startswith("https://pub-abc.r2.dev/agents-hq/"))
        self.assertEqual([p for p in FakeBucket.store if p.endswith("agents-hq-check.txt")], [])   # removed again
        shutil.rmtree(d, ignore_errors=True)

    def test_a_private_bucket_is_a_clear_error(self):
        with self.assertRaises(buffer_post.BufferError) as cm:
            self.host.fetch_public("https://pub-abc.r2.dev/agents-hq-media/nothing.txt")
        self.assertIn("404", str(cm.exception))


class FakeAccounts:
    def __init__(self, buffer=None, media=None):
        self.data = {"buffer": buffer or {}, "media": media or {}}

    def get(self, kind, channel=""):
        return self.data.get(kind) or {}

    def summary(self, channel=""):
        b = self.data["buffer"]
        return {p: {"connected": False} for p in publish.PLATFORMS} | {"buffer": {"connected": bool(b.get("api_key")), "host": buffer_post.host_ready(self.data["media"])}}


@unittest.skipUnless(FF, "ffmpeg is needed")
class BufferPublisherBase(unittest.TestCase):
    """A Publisher wired to a fake Buffer and a fake bucket, with one approved clip."""

    @classmethod
    def setUpClass(cls):
        cls.bsrv, cls.bbase = serve(FakeBuffer)
        cls.ssrv, cls.sbase = serve(FakeBucket)

    @classmethod
    def tearDownClass(cls):
        cls.bsrv.shutdown(); cls.ssrv.shutdown()

    def setUp(self):
        FakeBuffer.calls, FakeBuffer.fail, FakeBuffer.status, FakeBuffer.gone = [], None, {}, set()
        FakeBucket.store, FakeBucket.puts = {}, []
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "approved" / "clip"
        self.folder.mkdir(parents=True)
        make_clip(str(self.folder / "edit.mp4"))
        make_cover(str(self.folder / "cover.jpg"), f"{W}x{H}", "0xE0B030")
        (self.folder / "post.md").write_text("# c\n\n## Captions\n### Option 1\nTitle: T1\nwords here\n#a\n", encoding="utf-8")
        media = {"endpoint": "https://acct.r2.cloudflarestorage.com", "bucket": "b", "access_key": "k", "secret_key": "s", "public_url": "https://pub.r2.dev"}
        self.acc = FakeAccounts({"api_key": "key", "instagram": "ch_ig", "tiktok": "ch_tt"}, media)
        self.pub = publish.Publisher(str(self.root), self.acc)
        mock.patch.object(buffer_post, "_open", to_local(self.bbase)).start()
        real_host = buffer_post.MediaHost
        mock.patch.object(buffer_post, "MediaHost", lambda cfg, **k: real_host(cfg, opener=to_local(self.sbase))).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.temp.cleanup()

    def record(self):
        return self.pub.record(str(self.folder)).get("buffer") or {}

    def wait(self):
        for _ in range(600):
            if str(self.folder) not in self.pub.busy and self.record().get("state") not in ("waiting", "posting", "uploading", None):
                return
            time.sleep(0.2)
        self.fail("the post never finished: " + json.dumps(self.record()))



class PublisherBufferTests(BufferPublisherBase):
    """The Post button with Buffer ticked: package → bucket → two posts in Buffer, then the links when Buffer has sent them."""

    def test_payload_shows_the_package_state_and_the_same_caption(self):
        pl = self.pub.payload(str(self.folder))
        self.assertEqual(pl["buffer"]["state"], "none")
        self.assertTrue(pl["buffer"]["approved"])
        self.assertEqual(pl["buffer"]["base"], "approved/clip")
        self.assertEqual(pl["drafts"]["buffer"], {"caption": "words here\n#a", "title": "T1"})
        self.pub.buffer_make(str(self.folder), "", "", "words here\n#a", "T1")
        self.pub.covers.jobs[str(self.folder)]["done"].wait(120)
        pl = self.pub.payload(str(self.folder))
        self.assertEqual(pl["buffer"]["state"], "ready")
        self.assertEqual(pl["buffer"]["files"]["video"], "buffer/final.mp4")
        self.assertEqual((self.folder / "buffer" / "caption.txt").read_text(encoding="utf-8"), "words here\n#a\n")

    def test_post_now_through_buffer(self):
        started = self.pub.start(str(self.folder), {"buffer": {"caption": "words here\n#a", "title": "T1"}})
        self.assertEqual(started, ["buffer"])
        self.wait()
        r = self.record()
        self.assertEqual(r["state"], "posted", r)
        self.assertEqual(set(r["posts"]), {"instagram", "tiktok"})
        self.assertEqual(r["posts"]["instagram"]["id"], "p_ch_ig")
        self.assertEqual(r["link"], buffer_post.DASH)
        self.assertTrue(r["media"]["url"].startswith("https://pub.r2.dev/agents-hq/"))
        self.assertTrue((self.folder / "buffer" / "final.mp4").is_file())
        put = FakeBucket.puts[-1]
        self.assertEqual(put["size"], (self.folder / "buffer" / "final.mp4").stat().st_size)   # the flash copy went up, not edit.mp4
        creates = [c["variables"]["input"] for c in FakeBuffer.calls if "createPost" in c["query"]]
        self.assertEqual([c["channelId"] for c in creates], ["ch_ig", "ch_tt"])
        self.assertEqual({c["text"] for c in creates}, {"words here\n#a"})
        self.assertEqual(creates[0]["assets"][0]["video"]["url"], r["media"]["url"])
        self.assertEqual(creates[0]["assets"][0]["video"]["metadata"]["thumbnailOffset"], 50)
        self.assertEqual(creates[1]["metadata"]["tiktok"]["title"], "T1")
        # Buffer sends them: the links arrive on the next status check
        FakeBuffer.status["p_ch_ig"] = {"status": "sent", "externalLink": "https://www.instagram.com/reel/x/"}
        FakeBuffer.status["p_ch_tt"] = {"status": "sent", "externalLink": "https://www.tiktok.com/@n/video/1"}
        self.pub.run_due(now=time.time() + 700)
        r = self.record()
        self.assertEqual(r["state"], "posted")
        self.assertEqual(r["link"], "https://www.instagram.com/reel/x/")
        self.assertEqual(r["posts"]["tiktok"]["link"], "https://www.tiktok.com/@n/video/1")

    def test_scheduled_through_buffer_waits_for_buffer(self):
        when = int(time.time()) + 3600
        self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "T1"}}, when=when)
        self.wait()
        r = self.record()
        self.assertEqual((r["state"], r["when"]), ("scheduled", when))
        creates = [c["variables"]["input"] for c in FakeBuffer.calls if "createPost" in c["query"]]
        self.assertEqual({c["mode"] for c in creates}, {"customScheduled"})
        self.assertEqual(creates[0]["dueAt"], buffer_post.iso_utc(when))
        self.pub.run_due(now=when + 60)                         # due, still "scheduled" in Buffer: stays scheduled here
        self.assertEqual(self.record()["state"], "scheduled")
        FakeBuffer.status["p_ch_ig"] = {"status": "error", "error": {"message": "Instagram rejected the media"}}
        FakeBuffer.status["p_ch_tt"] = {"status": "sent", "externalLink": "https://www.tiktok.com/@n/video/2"}
        self.pub.run_due(now=when + 700)
        r = self.record()
        self.assertEqual(r["state"], "failed")
        self.assertIn("Instagram rejected", r["error"])

    def test_one_of_two_failing_is_a_warning_not_a_loss(self):
        FakeBuffer.fail = "tiktok"
        self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "T1"}})
        self.wait()
        r = self.record()
        self.assertEqual(r["state"], "posted")
        self.assertEqual(list(r["posts"]), ["instagram"])
        self.assertIn("TikTok", r["warning"])

    def test_without_a_media_host_the_post_explains(self):
        self.acc.data["media"] = {}                              # key and channels, but nowhere public to put the video
        self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "t"}})
        self.wait()
        r = self.record()
        self.assertEqual(r["state"], "failed")
        self.assertIn("media host", r["error"])

    def test_posted_by_hand_in_buffer(self):
        self.pub.buffer_done(str(self.folder), "", "", "final words", "T1")
        r = self.record()
        self.assertEqual((r["state"], r["manual"], r["link"]), ("posted", True, buffer_post.DASH))
        self.assertEqual((self.folder / "buffer" / "caption.txt").exists(), False)   # no package yet: nothing to write into
        self.pub.covers.make(str(self.folder), str(self.folder / "edit.mp4"), str(self.folder / "cover.jpg"))
        self.pub.buffer_done(str(self.folder), "", "", "final words", "T1")
        self.assertEqual((self.folder / "buffer" / "caption.txt").read_text(encoding="utf-8"), "final words\n")


class NeverTwiceTests(BufferPublisherBase):
    """Buffer posts Instagram and TikTok itself, so the same video never goes there directly as well (or the reverse)."""

    def setUp(self):
        super().setUp()
        self.acc.summary = lambda channel="": {p: {"connected": True} for p in publish.PLATFORMS} | {"buffer": {"connected": True, "host": True}}

    def test_instagram_ticked_directly_and_through_buffer_is_refused(self):
        with self.assertRaises(publish.PostError) as e:
            self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "t"}, "instagram": {"caption": "w"}})
        self.assertIn("ticked twice", str(e.exception))
        self.assertEqual(FakeBuffer.calls, [])
        self.assertEqual(self.record(), {})

    def test_buffer_is_refused_after_a_direct_instagram_post(self):
        for state in ("posted", "scheduled", "posting"):
            self.pub.note(str(self.folder), "instagram", state=state)
            with self.assertRaises(publish.PostError) as e:
                self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "t"}})
            self.assertIn("Instagram already went out", str(e.exception))
        self.assertEqual(FakeBuffer.calls, [])

    def test_a_failed_direct_post_does_not_block_buffer(self):
        self.pub.note(str(self.folder), "instagram", state="failed")
        self.assertEqual(self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "t"}}), ["buffer"])
        self.wait()

    def test_direct_tiktok_is_refused_once_it_is_in_buffer(self):
        self.pub.note(str(self.folder), "buffer", state="scheduled")
        with self.assertRaises(publish.PostError) as e:
            self.pub.start(str(self.folder), {"tiktok": {"title": "t"}})
        self.assertIn("already in Buffer", str(e.exception))

    def test_a_platform_buffer_does_not_post_is_not_blocked(self):
        self.acc.data["buffer"].pop("tiktok")                      # Buffer has Instagram only
        self.pub.note(str(self.folder), "tiktok", state="posted")
        self.assertEqual(self.pub.start(str(self.folder), {"buffer": {"caption": "w", "title": "t"}}), ["buffer"])
        self.wait()


class BufferSyncTests(BufferPublisherBase):
    """A Buffer post scheduled from Agents HQ stays in step: changed or cancelled here → in Buffer too; changed in Buffer → here."""

    def setUp(self):
        super().setUp()
        self.board = []
        self.pub = publish.Publisher(str(self.root), self.acc, on_schedule=lambda f, w, ps: "t9",
                                     on_finish=lambda f, t, st: self.board.append(("done", t, st)),
                                     on_move=lambda f, t, w: self.board.append(("moved", t, w)))
        self.when = int(time.time()) + 3 * 3600
        self.pub.start(str(self.folder), {"buffer": {"caption": "old words", "title": "T1"}}, when=self.when)
        self.wait()
        self.assertEqual(self.record()["state"], "scheduled")
        FakeBuffer.calls = []

    def calls(self, name):
        return [c["variables"]["input"] for c in FakeBuffer.calls if name in c["query"]]

    def test_a_new_time_caption_and_title_are_made_in_buffer_too(self):
        later = self.when + 86400
        self.pub.buffer_change(str(self.folder), later, "new words", "T2")
        edits = self.calls("editPost")
        self.assertEqual([e["id"] for e in edits], ["p_ch_ig", "p_ch_tt"])
        self.assertEqual({(e["mode"], e["dueAt"], e["text"]) for e in edits}, {("customScheduled", buffer_post.iso_utc(later), "new words")})
        self.assertEqual(edits[0]["metadata"], {"instagram": {"type": "reel", "shouldShareToFeed": True}})   # stays a Reel
        self.assertEqual(edits[1]["metadata"], {"tiktok": {"title": "T2"}})
        r = self.record()
        self.assertEqual((r["state"], r["when"], r["warning"]), ("scheduled", later, ""))
        self.assertEqual((self.folder / "buffer" / "caption.txt").read_text(encoding="utf-8"), "new words\n")
        self.assertEqual((self.folder / "buffer" / "title.txt").read_text(encoding="utf-8"), "T2\n")
        self.assertEqual(self.board, [("moved", "t9", later)])

    def test_only_the_time_leaves_the_words_alone(self):
        later = self.when + 600
        self.pub.buffer_change(str(self.folder), later)
        for e in self.calls("editPost"):
            self.assertEqual(set(e), {"id", "mode", "dueAt"})

    def test_one_post_buffer_wont_edit_is_a_warning(self):
        FakeBuffer.fail = "edit-tiktok"
        self.pub.buffer_change(str(self.folder), caption="new words")
        r = self.record()
        self.assertEqual(r["state"], "scheduled")
        self.assertIn("Instagram only", r["warning"])
        self.assertIn("no longer be edited", r["warning"])

    def test_a_title_buffer_would_not_take_is_said(self):
        FakeBuffer.fail = "metadata"
        later = self.when + 3600
        self.pub.buffer_change(str(self.folder), later, title="T2")
        r = self.record()
        self.assertEqual(r["when"], later)                         # the new time went through
        self.assertIn("did not take the new TikTok title", r["warning"])
        self.assertEqual((self.folder / "buffer" / "title.txt").read_text(encoding="utf-8"), "T1\n")

    def test_the_caption_files_stay_inside_the_approved_folder(self):
        outside = self.root / "elsewhere"
        (outside / "buffer").mkdir(parents=True)
        (outside / "x.mp4").write_bytes(b"x")
        self.pub.note(str(self.folder), "buffer", video="../../elsewhere/x.mp4")
        self.pub.buffer_change(str(self.folder), caption="safe words")
        self.assertFalse((outside / "buffer" / "caption.txt").exists())
        self.assertEqual((self.folder / "buffer" / "caption.txt").read_text(encoding="utf-8"), "safe words\n")

    def test_a_title_only_change_buffer_refuses_is_an_error(self):
        FakeBuffer.fail = "metadata"
        with self.assertRaisesRegex(publish.PostError, "did not take the new TikTok title"):
            self.pub.buffer_change(str(self.folder), title="T2")
        self.assertEqual([e["id"] for e in self.calls("editPost")], ["p_ch_tt"])       # Instagram has no title: not asked

    def test_cancel_leaves_a_post_that_went_out_since_the_last_check(self):
        FakeBuffer.status["p_ch_ig"] = {"status": "sent", "sentAt": "2026-11-11T10:00:00.000Z", "externalLink": "https://www.instagram.com/reel/z/"}
        self.pub.cancel(str(self.folder), "buffer")
        self.assertEqual([d["id"] for d in self.calls("deletePost")], ["p_ch_tt"])
        r = self.record()
        self.assertEqual((r["state"], r["posts"]["instagram"]["status"]), ("posted", "sent"))
        self.assertIn("TikTok was deleted in Buffer", r["warning"])
        self.assertIn("Instagram went out", r["warning"])

    def test_change_leaves_a_post_that_went_out_since_the_last_check(self):
        FakeBuffer.status["p_ch_tt"] = {"status": "sent", "externalLink": "https://www.tiktok.com/@n/video/3"}
        self.pub.buffer_change(str(self.folder), caption="new words")
        self.assertEqual([e["id"] for e in self.calls("editPost")], ["p_ch_ig"])
        self.assertIn("TikTok had already gone out", self.record()["warning"])

    def test_a_sent_post_never_turns_into_deleted(self):
        t0 = time.time()
        FakeBuffer.status["p_ch_ig"] = FakeBuffer.status["p_ch_tt"] = {"status": "sent"}      # sent, but no link yet
        self.pub.run_due(now=t0)
        self.assertEqual(self.record()["state"], "posted")
        FakeBuffer.gone.update({"p_ch_ig", "p_ch_tt"})                                      # later gone from Buffer's history
        self.pub.run_due(now=t0 + 700)
        r = self.record()
        self.assertEqual(r["state"], "posted")
        self.assertEqual({p["status"] for p in r["posts"].values()}, {"sent"})

    def test_one_post_moved_in_buffer_keeps_the_time_and_says_so(self):
        t0 = time.time()
        self.pub.run_due(now=t0)
        FakeBuffer.status["p_ch_tt"] = {"dueAt": buffer_post.iso_utc(self.when + 7200)}
        FakeBuffer.status["p_ch_ig"] = {"dueAt": buffer_post.iso_utc(self.when)}
        self.pub.run_due(now=t0 + 31 * 60)
        r = self.record()
        self.assertEqual(r["when"], self.when)
        self.assertIn("different times in Buffer", r["warning"])
        self.assertEqual(self.board, [])

    def test_one_post_deleted_in_buffer_says_which(self):
        FakeBuffer.gone.add("p_ch_ig")
        self.pub.run_due(now=time.time() + 31 * 60)
        r = self.record()
        self.assertEqual(r["state"], "scheduled")
        self.assertIn("Instagram was deleted in Buffer", r["warning"])
        self.assertIn("TikTok still goes out", r["warning"])

    def test_bad_changes_are_refused_before_buffer_is_asked(self):
        with self.assertRaisesRegex(publish.PostError, "10 minutes"):
            self.pub.buffer_change(str(self.folder), int(time.time()) + 60)
        with self.assertRaisesRegex(publish.PostError, "2200"):
            self.pub.buffer_change(str(self.folder), caption="x" * 2201)
        with self.assertRaisesRegex(publish.PostError, "nothing to change"):
            self.pub.buffer_change(str(self.folder))
        self.assertEqual(self.calls("editPost"), [])

    def test_cancel_deletes_both_posts_in_buffer(self):
        self.pub.cancel(str(self.folder), "buffer")
        self.assertEqual([d["id"] for d in self.calls("deletePost")], ["p_ch_ig", "p_ch_tt"])
        r = self.record()
        self.assertEqual(r["state"], "cancelled")
        self.assertEqual({p["status"] for p in r["posts"].values()}, {"deleted"})
        self.assertEqual(self.board, [("done", "t9", ["cancelled"])])
        with self.assertRaisesRegex(publish.PostError, "only a Buffer post scheduled"):
            self.pub.buffer_change(str(self.folder), caption="too late")

    def test_cancel_counts_a_post_already_deleted_in_buffer(self):
        FakeBuffer.gone.add("p_ch_tt")
        self.pub.cancel(str(self.folder), "buffer")
        self.assertEqual(self.record()["state"], "cancelled")

    def test_a_sent_post_is_left_alone(self):
        posts = self.record()["posts"]
        posts["instagram"].update(status="sent", link="https://www.instagram.com/reel/y/")
        self.pub.note(str(self.folder), "buffer", posts=posts)
        self.pub.cancel(str(self.folder), "buffer")
        self.assertEqual([d["id"] for d in self.calls("deletePost")], ["p_ch_tt"])
        self.assertEqual(self.record()["state"], "posted")         # Instagram went out; TikTok won't

    def test_a_new_time_set_in_buffer_shows_here(self):
        moved = self.when + 7200
        t0 = time.time()
        self.pub.run_due(now=t0)                                # the first check after scheduling
        FakeBuffer.status["p_ch_ig"] = FakeBuffer.status["p_ch_tt"] = {"dueAt": buffer_post.iso_utc(moved)}
        FakeBuffer.calls = []
        self.pub.run_due(now=t0 + 60)                           # checked less than half an hour ago: not asked yet
        self.assertEqual([c for c in FakeBuffer.calls if "query { post(" in c["query"]], [])
        self.assertEqual(self.record()["when"], self.when)
        self.pub.run_due(now=t0 + 31 * 60)
        r = self.record()
        self.assertEqual((r["state"], r["when"]), ("scheduled", moved))
        self.assertEqual(self.board, [("moved", "t9", moved)])

    def test_posts_deleted_in_buffer_show_as_cancelled(self):
        FakeBuffer.gone.update({"p_ch_ig", "p_ch_tt"})
        self.pub.run_due(now=time.time() + 31 * 60)
        r = self.record()
        self.assertEqual(r["state"], "cancelled")
        self.assertIn("Deleted in Buffer", r["warning"])
        self.assertEqual(self.board, [("done", "t9", ["cancelled"])])

    def test_a_post_made_by_hand_in_buffer_is_changed_in_buffer(self):
        self.pub.buffer_done(str(self.folder), "", "", "w", "T1")
        with self.assertRaisesRegex(publish.PostError, "changed in Buffer"):
            self.pub.buffer_change(str(self.folder), caption="x")


class BufferClientEditTests(unittest.TestCase):
    def test_dueAt_reads_back_as_unix_time(self):
        self.assertEqual(buffer_post.from_iso(buffer_post.iso_utc(1794621600)), 1794621600)
        self.assertIsNone(buffer_post.from_iso(None))
        self.assertIsNone(buffer_post.from_iso("soon"))
        self.assertEqual(buffer_post.from_iso("2026-11-14T02:00:00"), 1794621600)      # no time zone: Buffer means UTC

    def test_not_found_is_recognised(self):
        self.assertTrue(buffer_post.gone("Buffer: Post not found (NOT_FOUND)"))
        self.assertTrue(buffer_post.gone("Post not found"))
        self.assertFalse(buffer_post.gone("Buffer: rate limited"))
        self.assertFalse(buffer_post.gone("Buffer answered 404: Not Found"))     # a proxy or endpoint fault, not a deleted post
        self.assertFalse(buffer_post.gone("Buffer: Channel not found"))
        self.assertFalse(buffer_post.gone("Buffer answered 404: Post not found (NOT_FOUND)"))

    def test_a_far_future_or_infinite_time_is_refused(self):
        for bad in (float("inf"), "soon", None, 10 ** 12):
            with self.assertRaises(publish.PostError):
                publish.check_when(bad)


class AccountsBufferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve(FakeBuffer)
        cls.ssrv, cls.sbase = serve(FakeBucket)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.ssrv.shutdown()

    def setUp(self):
        FakeBuffer.calls, FakeBuffer.fail = [], None
        FakeBucket.store = {}
        self.temp = tempfile.TemporaryDirectory()
        self.acc = publish.Accounts(self.temp.name)
        mock.patch.object(buffer_post, "_open", to_local(self.base)).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.temp.cleanup()

    def test_connect_picks_instagram_and_tiktok_and_the_summary_hides_the_key(self):
        r = self.acc.connect_buffer("key123")
        self.assertEqual((r["instagram"], r["tiktok"]), ("ch_ig", "ch_tt"))
        s = self.acc.summary()["buffer"]
        self.assertEqual((s["connected"], s["key"], s["host"]), (True, True, False))
        self.assertEqual(s["name"], "Instagram @nlrcc + TikTok nlrcc.tv")
        self.assertNotIn("key123", json.dumps(s))
        self.acc.buffer_channels({"tiktok": ""})
        s = self.acc.summary()["buffer"]
        self.assertEqual((s["tiktok"]["id"], s["connected"]), ("", True))
        with self.assertRaises(publish.PostError):
            self.acc.buffer_channels({"instagram": "ch_fb"})
        self.acc.connect_buffer("")                                   # an empty key: the saved one, channels read again
        self.assertEqual(self.acc.get("buffer")["api_key"], "key123")
        self.assertEqual(self.acc.get("buffer")["instagram"], "ch_ig")
        self.acc.disconnect("buffer")
        self.assertFalse(self.acc.summary()["buffer"]["key"])

    def test_media_host_is_tested_before_it_is_saved(self):
        real_host = buffer_post.MediaHost
        mock.patch.object(buffer_post, "MediaHost", lambda cfg, **k: real_host(cfg, opener=to_local(self.sbase))).start()
        cfg = {"endpoint": "https://acct.r2.cloudflarestorage.com", "bucket": "b", "access_key": "k", "secret_key": "s", "public_url": "https://pub.r2.dev"}
        url = self.acc.connect_host(cfg)
        self.assertTrue(url.startswith("https://pub.r2.dev/agents-hq/"))
        s = self.acc.summary()["buffer"]
        self.assertEqual((s["host"], s["hostName"]), (True, "b · https://pub.r2.dev"))
        self.acc.connect_host(dict(cfg, secret_key=""))               # an empty secret keeps the saved one
        self.assertEqual(self.acc.get("media")["secret_key"], "s")
        with self.assertRaises(publish.PostError) as cm:             # a wrong public address: the read-back fails, nothing is saved
            self.acc.connect_host(dict(cfg, public_url="https://pub.r2.dev/wrong"))
        self.assertIn("404", str(cm.exception))
        self.assertEqual(self.acc.get("media")["public_url"], "https://pub.r2.dev")
        self.assertEqual(self.acc.summary("pong-gospel")["buffer"]["hostShared"], True)   # a channel uses the main host


if __name__ == "__main__":
    unittest.main()
