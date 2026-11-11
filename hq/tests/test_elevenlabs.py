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

    def test_credits_reads_used_and_left_and_never_writes_the_key_file(self):
        elevenlabs.save({"api_key": KEY, "used": 5, "limit": 100000}, self.root)
        before = open(elevenlabs.path(self.root), "rb").read()
        with mock.patch.object(elevenlabs, "_open", Fake({"/v1/user/subscription": SUB})):
            c = elevenlabs.credits(self.root)
        self.assertEqual(c, {"tier": "creator", "used": 1200, "limit": 100000, "left": 98800})
        self.assertEqual(open(elevenlabs.path(self.root), "rb").read(), before)   # parallel editors can't clobber it

    def test_spent_exact_cost_partial_readings_and_estimates(self):
        c = {"tier": "creator", "used": 1200, "limit": 100000, "left": 98800}
        lagging = elevenlabs.spent(c, c, cost=54)                            # the counter hasn't caught up yet
        self.assertEqual(lagging, {"used_now": 54, "left": 98746, "limit": 100000, "tier": "creator"})
        self.assertEqual(elevenlabs.spent(c, {**c, "used": 1254, "left": 98746}),       # no cost known: the counter,
                         {"used_now": 54, "left": 98746, "limit": 100000, "tier": "creator", "estimate": True})  # marked
        self.assertEqual(elevenlabs.spent(None, None, cost=54), {"used_now": 54})       # no User: Read: the cost alone
        self.assertEqual(elevenlabs.spent(c, None, cost=54)["left"], 98746)             # the after-reading failed
        self.assertEqual(elevenlabs.spent(None, c, 9, exact=False)["estimate"], True)
        self.assertIsNone(elevenlabs.spent(None, None))
        self.assertEqual(elevenlabs.take_cost({"cost": 27}, "abc"), (27, True))
        self.assertEqual(elevenlabs.take_cost({}, "哇好开心"), (4, False))             # no header: the length, estimated

    def test_speak_reports_the_exact_cost_from_the_header(self):
        elevenlabs.save({"api_key": KEY}, self.root)
        r = Resp(json.dumps({"audio_base64": base64.b64encode(b"ID3fake").decode(), "alignment": {}}).encode())
        r.headers = {"character-cost": "27"}
        meta = {}
        with mock.patch.object(elevenlabs, "_open", lambda req, timeout=None: r):
            elevenlabs.speak("hi", "Voice0000000001", os.path.join(self.root, "a.mp3"), root=self.root, meta=meta)
        self.assertEqual(meta, {"cost": 27})
        meta = {}
        r2 = Resp(json.dumps({"audio_base64": base64.b64encode(b"ID3fake").decode(), "alignment": {}}).encode())
        with mock.patch.object(elevenlabs, "_open", lambda req, timeout=None: r2):   # no headers at all
            elevenlabs.speak("hi", "Voice0000000001", os.path.join(self.root, "a.mp3"), root=self.root, meta=meta)
        self.assertEqual(meta, {})

    def test_credits_is_none_without_a_key_or_without_user_read(self):
        with mock.patch.object(elevenlabs, "_open", Fake({})):
            self.assertIsNone(elevenlabs.credits(self.root))                 # no key: no call at all
        elevenlabs.save({"api_key": KEY}, self.root)
        no = Fake({"/v1/user/subscription": http_error(401, {"status": "missing_permissions", "message": "needs user_read"})})
        with mock.patch.object(elevenlabs, "_open", no):
            self.assertIsNone(elevenlabs.credits(self.root))

    def test_free_plan_library_voice_is_a_plan_problem_not_credits(self):
        elevenlabs.save({"api_key": KEY}, self.root)
        fake = Fake({"/v1/text-to-speech/": http_error(402, {"status": "payment_required",
                     "message": "Free users cannot use library voices via the API."})})
        with mock.patch.object(elevenlabs, "_open", fake), self.assertRaises(elevenlabs.ElevenError) as cm:
            elevenlabs.speak("hi", "Voice0000000001", os.path.join(self.root, "a.mp3"), root=self.root)
        self.assertIn("paid plan", str(cm.exception))
        self.assertIn("Free users cannot use library voices", str(cm.exception))
        self.assertNotIn("credits are used up", str(cm.exception))


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

    def test_say_prints_the_cost_and_credits_left(self):
        def fake_speak(text, voice, out, model=None, settings=None, root=None, meta=None):
            meta["cost"] = 4
            return [["哇", 0.0, 0.3]]
        readings = iter([{"tier": "starter", "used": 100, "limit": 40000, "left": 39900}] * 2)
        with tempfile.TemporaryDirectory() as d:
            elevenlabs.save({"api_key": KEY}, d)
            with mock.patch.object(elevenlabs, "speak", fake_speak), \
                    mock.patch.object(elevenlabs, "credits", lambda root=None: next(readings)):
                code, out = self.run_tool(d, "say", "Voice0000000001", os.path.join(d, "a.mp3"), "哇")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["credits"], {"used_now": 4, "left": 39896, "limit": 40000, "tier": "starter"})

    def test_a_charged_take_that_fails_is_still_counted(self):
        def fake_speak(text, voice, out, model=None, settings=None, root=None, meta=None):
            meta["cost"] = 7
            raise elevenlabs.ElevenError("ElevenLabs sent no audio for this line.")
        with tempfile.TemporaryDirectory() as d:
            elevenlabs.save({"api_key": KEY}, d)
            with mock.patch.object(elevenlabs, "speak", fake_speak), mock.patch.object(elevenlabs, "credits", lambda root=None: None):
                code, out = self.run_tool(d, "say", "Voice0000000001", os.path.join(d, "a.mp3"), "哇")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["credits"], {"used_now": 7})


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "needs ffmpeg")
class VoElevenTest(unittest.TestCase):
    """vo.py --eleven end to end, with ElevenLabs replaced by a 0.6 s tone and made-up character times."""
    def test_lines_get_real_chars_and_reuse_never_keeps_a_3b_take(self):
        import subprocess
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "kids-review" / "scripts"))
        import vo
        calls = []

        def fake_speak(text, voice_id, out, model=None, settings=None, root=None, meta=None):
            calls.append(text)
            meta["cost"] = 3
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
            readings = iter([{"tier": "starter", "used": 100, "limit": 40000, "left": 39900},
                             {"tier": "starter", "used": 110, "limit": 40000, "left": 39890}])
            with mock.patch.object(elevenlabs, "has_key", lambda root=None: True), mock.patch.object(elevenlabs, "speak", fake_speak), \
                    mock.patch.object(elevenlabs, "credits", lambda root=None: next(readings)), \
                    mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdout", out):
                vo.main()
            lines = json.load(open(os.path.join(old, "lines.json"), encoding="utf-8"))
        # the takes' own cost (2 x 3), not the lagging counter (10); left = before minus that cost
        self.assertEqual(json.loads(out.getvalue())["credits"], {"used_now": 6, "left": 39890, "limit": 40000, "tier": "starter"})
        self.assertEqual(len(calls), 2)                                  # the old 3B line was spoken again, not reused
        self.assertIn("elevenlabs:Voice0000000001", out.getvalue())
        self.assertEqual([c[0] for c in lines[0]["chars"]], ["哇", "！", "好"])
        self.assertAlmostEqual(lines[0]["chars"][0][1], 0.03, places=2)  # trimmed 0.03 s before the first character

    def test_a_stop_midway_reports_the_credits_spent_so_far(self):
        import subprocess
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "kids-review" / "scripts"))
        import vo
        n = []

        def fake_speak(text, voice_id, out, model=None, settings=None, root=None, meta=None):
            n.append(text)
            if len(n) == 2:                                          # line 2: no header, then quota refused
                raise elevenlabs.ElevenError("Your ElevenLabs credits are used up for this month.")
            meta["cost"] = 5
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", out], check=True)
            return [["哇", 0.0, 0.5]]
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:d=4", "-c:v", "libx264", video], check=True)
            script = os.path.join(d, "lines.json")
            with open(script, "w", encoding="utf-8") as f:
                json.dump({"lines": [{"t": 0.2, "text": "哇"}, {"t": 2.0, "text": "好"}]}, f)
            argv = ["vo.py", video, script, os.path.join(d, "vo"), os.path.join(d, "out.mp4"), "--eleven", "Voice0000000001"]
            reading = {"tier": "starter", "used": 100, "limit": 40000, "left": 39900}
            with mock.patch.object(elevenlabs, "has_key", lambda root=None: True), mock.patch.object(elevenlabs, "speak", fake_speak), \
                    mock.patch.object(elevenlabs, "credits", lambda root=None: reading), mock.patch.object(sys, "argv", argv), \
                    self.assertRaises(SystemExit) as cm:
                vo.main()
        self.assertIn("Credits: used 5, left 39895 of 40000.", str(cm.exception.code))
        self.assertIn("Lines 1-1 are kept", str(cm.exception.code))


class MakeplanCharsTest(unittest.TestCase):
    def test_real_character_times_are_used(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "kids-review" / "scripts"))
        import makeplan
        ws = makeplan.chars_for([["哇", 0.0, 0.2], ["！", 0.2, 0.25], ["好", 0.3, 0.3]], 1.0)
        self.assertEqual(ws, [{"t": "哇", "start": 1.0, "end": 1.2}, {"t": "好", "start": 1.3, "end": 1.32}])


if __name__ == "__main__":
    unittest.main()
