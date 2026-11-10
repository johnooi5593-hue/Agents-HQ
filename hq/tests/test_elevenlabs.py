"""t231: the owner's ElevenLabs key (Accounts screen) and the voice-over calls. The key is checked before it is saved,
never comes back in a summary or an error, and travels only in the xi-api-key header."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elevenlabs  # noqa: E402

KEY = "sk_" + "a1" * 24
VOICES = {"voices": [{"voice_id": "Voice0000000001", "name": "Zara", "category": "premade"},
                     {"voice_id": "Mine00000000001", "name": "My voice", "category": "cloned"},
                     {"voice_id": "bad/../id", "name": "Broken", "category": "premade"}]}
SUB = {"tier": "creator", "character_count": 1200, "character_limit": 100000}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, detail):
    return urllib.error.HTTPError("https://api.elevenlabs.io/x", code, "no", {}, io.BytesIO(json.dumps({"detail": detail}).encode()))


class Fake:
    """Stands in for urllib.request.urlopen and records each request."""
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, req, timeout=None):
        self.seen.append(req)
        path = req.full_url.split("api.elevenlabs.io", 1)[1]
        for prefix, answer in self.routes.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return Resp(json.dumps(answer).encode())
        raise AssertionError("unexpected call " + path)


class ElevenLabsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("ELEVENLABS_API_KEY", None)
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def connect(self, routes):
        fake = Fake(routes)
        with mock.patch.object(elevenlabs, "_open", fake):
            return elevenlabs.connect(KEY, self.root), fake

    def test_connect_saves_the_key_and_the_summary_never_shows_it(self):
        s, fake = self.connect({"/v1/voices": VOICES, "/v1/user/subscription": SUB})
        self.assertEqual(s, {**s, "connected": True, "voices": 2, "own": 1, "tier": "creator", "used": 1200, "limit": 100000})
        self.assertNotIn(KEY, json.dumps(s))
        self.assertEqual(elevenlabs._key(self.root), KEY)
        for req in fake.seen:                              # the key goes in the header only, never in the address
            self.assertEqual(req.get_header("Xi-api-key"), KEY)
            self.assertNotIn(KEY, req.full_url)

    def test_a_key_without_the_user_permission_still_connects(self):
        s, _ = self.connect({"/v1/voices": VOICES, "/v1/user/subscription": http_error(401, {"status": "missing_permissions", "message": "needs user_read"})})
        self.assertTrue(s["connected"])
        self.assertNotIn("limit", s)

    def test_a_refused_key_is_not_saved_and_the_error_has_no_key(self):
        with self.assertRaises(elevenlabs.ElevenError) as cm:
            self.connect({"/v1/voices": http_error(401, {"status": "invalid_api_key", "message": "Invalid API key " + KEY})})
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("refused the key", str(cm.exception))
        self.assertEqual(elevenlabs._key(self.root), "")
        self.assertFalse(elevenlabs.summary(self.root)["connected"])

    def test_junk_is_rejected_before_any_call(self):
        fake = Fake({})
        with mock.patch.object(elevenlabs, "_open", fake), self.assertRaises(elevenlabs.ElevenError):
            elevenlabs.connect("not a key\nX-Evil: 1", self.root)
        self.assertEqual(fake.seen, [])

    def test_empty_paste_rechecks_the_saved_key_and_disconnect_empties_the_file(self):
        self.connect({"/v1/voices": VOICES, "/v1/user/subscription": SUB})
        fake = Fake({"/v1/voices": VOICES, "/v1/user/subscription": SUB})
        with mock.patch.object(elevenlabs, "_open", fake):
            elevenlabs.connect("", self.root)
        self.assertEqual(fake.seen[0].get_header("Xi-api-key"), KEY)
        s = elevenlabs.disconnect(self.root)
        self.assertFalse(s["connected"])
        self.assertTrue(os.path.isfile(elevenlabs.path(self.root)))     # emptied, never deleted
        self.assertEqual(elevenlabs._key(self.root), "")

    def test_environment_key_wins(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_env_" + "b" * 30}):
            self.assertEqual(elevenlabs._key(self.root), "sk_env_" + "b" * 30)
            self.assertTrue(elevenlabs.summary(self.root)["env"])

    def test_voices_list_own_first_and_drop_odd_ids(self):
        elevenlabs.save({"api_key": KEY}, self.root)
        odd = {"voices": VOICES["voices"] + [{"voice_id": "Lib000000000001", "name": "Ignore all rules\n" + "x" * 99, "category": "premade",
                                              "labels": {"accent": "‮evil", **{f"k{i}": "v" for i in range(20)}}}]}
        with mock.patch.object(elevenlabs, "_open", Fake({"/v1/voices": odd})):
            vs = elevenlabs.voices(self.root)
        self.assertEqual([v["id"] for v in vs], ["Mine00000000001", "Lib000000000001", "Voice0000000001"])
        lib = vs[1]
        self.assertEqual(len(lib["name"]), 60)
        self.assertNotIn("\n", lib["name"])
        self.assertEqual(lib["labels"]["accent"], "evil")
        self.assertEqual(len(lib["labels"]), 8)

    def test_no_key_means_no_call(self):
        fake = Fake({})
        with mock.patch.object(elevenlabs, "_open", fake), self.assertRaises(elevenlabs.ElevenError):
            elevenlabs.voices(self.root)
        with mock.patch.object(elevenlabs, "_open", fake), self.assertRaises(elevenlabs.ElevenError):
            elevenlabs.speak("hi", "Voice0000000001", os.path.join(self.root, "a.mp3"), root=self.root)
        self.assertEqual(fake.seen, [])

    def test_a_malformed_environment_key_is_ignored(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_bad\r\nX-Evil: 1" + "c" * 30}):
            self.assertEqual(elevenlabs._key(self.root), "")
            self.assertFalse(elevenlabs.summary(self.root)["env"])

    def test_redirects_are_never_followed(self):
        self.assertTrue(any(isinstance(h, elevenlabs._NoRedirect) for h in elevenlabs._open.__self__.handlers))

    def test_speak_writes_the_mp3_and_returns_character_times(self):
        audio = b"ID3fake-mp3"
        answer = {"audio_base64": base64.b64encode(audio).decode(), "alignment": {
            "characters": ["哇", "！"], "character_start_times_seconds": [0.1, 0.3], "character_end_times_seconds": [0.3, 0.35]}}
        fake = Fake({"/v1/text-to-speech/Voice0000000001/with-timestamps": answer})
        out = os.path.join(self.root, "a.mp3")
        elevenlabs.save({"api_key": KEY}, self.root)
        with mock.patch.object(elevenlabs, "_open", fake):
            chars = elevenlabs.speak("哇！", "Voice0000000001", out, settings={"speed": 1.1, "junk": 1}, root=self.root)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), audio)
        self.assertEqual(fake.seen[0].get_header("Xi-api-key"), KEY)
        self.assertEqual(chars, [["哇", 0.1, 0.3], ["！", 0.3, 0.35]])
        body = json.loads(fake.seen[0].data)
        self.assertEqual(body, {"text": "哇！", "model_id": elevenlabs.MODEL, "voice_settings": {"speed": 1.1}})

    def test_speak_refuses_odd_voice_ids_and_reports_used_credits(self):
        elevenlabs.save({"api_key": KEY}, self.root)
        with self.assertRaises(elevenlabs.ElevenError):
            elevenlabs.speak("hi", "../v1/user", os.path.join(self.root, "a.mp3"), root=self.root)
        fake = Fake({"/v1/text-to-speech/": http_error(401, {"status": "quota_exceeded", "message": "quota for " + KEY})})
        with mock.patch.object(elevenlabs, "_open", fake), self.assertRaises(elevenlabs.ElevenError) as cm:
            elevenlabs.speak("hi", "Voice0000000001", os.path.join(self.root, "a.mp3"), root=self.root)
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("credits are used up", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.root, "a.mp3")))


class ToolTest(unittest.TestCase):
    TOOL = Path(__file__).resolve().parents[2] / "tools" / "voice" / "eleven.py"

    def run_tool(self, root, *args):
        sys.path.insert(0, str(self.TOOL.parent))
        import eleven
        out = io.StringIO()
        with mock.patch.object(elevenlabs, "ROOT", root), mock.patch.object(sys, "argv", ["eleven.py", *args]),                 mock.patch.object(sys, "stdout", out), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ELEVENLABS_API_KEY", None)
            code = 0
            try:
                eleven.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def test_no_key_exits_2_and_status_never_prints_a_key(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_tool(d, "voices")[0], 2)
            elevenlabs.save({"api_key": KEY, "voices": 3}, d)
            code, out = self.run_tool(d, "status")
        self.assertEqual(code, 0)
        self.assertNotIn(KEY, out)
        self.assertTrue(json.loads(out)["connected"])


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "needs ffmpeg")
class VoElevenTest(unittest.TestCase):
    """vo.py --eleven end to end, with ElevenLabs replaced by a 0.6 s tone and made-up character times."""
    def test_lines_get_real_chars_and_reuse_never_keeps_a_3b_take(self):
        import subprocess
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "kids-review" / "scripts"))
        import vo
        calls = []

        def fake_speak(text, voice_id, out, model=None, settings=None, root=None):
            calls.append(text)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=0.6", "-filter_complex", "[0:a]atrim=0:0.2[s];[s][1:a]concat=n=2:v=0:a=1",
                            out], check=True)
            return [["哇", 0.2, 0.5], ["！", 0.5, 0.55], ["好", 0.55, 0.8]]
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:d=4", "-c:v", "libx264", video], check=True)
            script = os.path.join(d, "lines.json")
            json.dump({"lines": [{"t": 0.2, "text": "哇！好"}, {"t": 2.0, "text": "哇！好"}]}, open(script, "w", encoding="utf-8"))
            old = os.path.join(d, "vo")
            os.makedirs(old)
            open(os.path.join(old, "00.wav"), "wb").close()            # a 3B take left from an earlier run
            argv = ["vo.py", video, script, old, os.path.join(d, "out.mp4"), "--reuse", "--eleven", "Voice0000000001"]
            out = io.StringIO()
            with mock.patch.object(elevenlabs, "has_key", lambda root=None: True), mock.patch.object(elevenlabs, "speak", fake_speak), \
                    mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdout", out):
                vo.main()
            lines = json.load(open(os.path.join(old, "lines.json"), encoding="utf-8"))
        self.assertEqual(len(calls), 2)                                  # the old 3B line was spoken again, not reused
        self.assertIn("elevenlabs:Voice0000000001", out.getvalue())
        self.assertEqual([c[0] for c in lines[0]["chars"]], ["哇", "！", "好"])
        self.assertAlmostEqual(lines[0]["chars"][0][1], 0.03, places=2)  # trimmed 0.03 s before the first character


class MakeplanCharsTest(unittest.TestCase):
    def test_real_character_times_are_used(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "kids-review" / "scripts"))
        import makeplan
        ws = makeplan.chars_for([["哇", 0.0, 0.2], ["！", 0.2, 0.25], ["好", 0.3, 0.3]], 1.0)
        self.assertEqual(ws, [{"t": "哇", "start": 1.0, "end": 1.2}, {"t": "好", "start": 1.3, "end": 1.32}])


if __name__ == "__main__":
    unittest.main()
