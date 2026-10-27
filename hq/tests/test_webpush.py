import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpush  # noqa: E402


@unittest.skipUnless(webpush.AVAILABLE, "the cryptography package is not installed")
class WebPushTests(unittest.TestCase):
    def test_encryption_matches_the_rfc_8291_example(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        sender = ec.derive_private_key(int.from_bytes(webpush.unb64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
        body = webpush.encrypt(b"When I grow up, I want to be a watermelon",
                               "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                               "BTBZMqHH6r4Tts7J_aSIgg", sender=sender, salt=webpush.unb64("DGv6ra1nlYgDCS1FRnbzlw"))
        self.assertEqual(webpush.b64(body), "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz"
                                            "AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")

    def test_the_sender_token_is_signed_with_the_offices_key(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        with tempfile.TemporaryDirectory() as root:
            push = webpush.Push(root)
            data = push._load()
            key = push._key(data)
            header = push._vapid(key, "https://fcm.googleapis.com/fcm/send/abc")
            token, k = header[len("vapid t="):].split(", k=")
            self.assertEqual(k, push.public_key())
            head, claims, sig = token.split(".")
            self.assertEqual(json.loads(webpush.unb64(claims))["aud"], "https://fcm.googleapis.com")
            raw = webpush.unb64(sig)
            key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                                    f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))       # raises if the signature is wrong
            self.assertEqual(push.public_key(), webpush.Push(root).public_key())                   # the key is kept

    def test_only_real_push_services_are_accepted(self):
        good = {"p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", "auth": "BTBZMqHH6r4Tts7J_aSIgg"}
        with tempfile.TemporaryDirectory() as root:
            push = webpush.Push(root)
            for url in ("https://web.push.apple.com/QGuQyavXut", "https://fcm.googleapis.com/fcm/send/x", "https://wns2-db5p.notify.windows.com/w/?token=1"):
                push.subscribe({"endpoint": url, "keys": good})
            self.assertEqual(push.count(), 3)
            for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://evil.example/fcm.googleapis.com", "file:///etc/passwd"):
                with self.assertRaises(ValueError):
                    push.subscribe({"endpoint": bad, "keys": good})
            push.subscribe({"endpoint": "https://web.push.apple.com/QGuQyavXut", "keys": good})     # the same phone again: no duplicate
            self.assertEqual(push.count(), 3)
            push.unsubscribe("https://fcm.googleapis.com/fcm/send/x")
            self.assertEqual(push.count(), 2)


    def test_sending_seals_the_message_and_forgets_phones_that_left(self):
        import urllib.error
        from unittest import mock
        keys = {"p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", "auth": "BTBZMqHH6r4Tts7J_aSIgg"}
        sent = []

        class Reply:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout):
            sent.append(req)
            if "gone" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
            return Reply()
        with tempfile.TemporaryDirectory() as root:
            push = webpush.Push(root)
            push.subscribe({"endpoint": "https://web.push.apple.com/phone", "keys": keys})
            push.subscribe({"endpoint": "https://fcm.googleapis.com/fcm/send/gone", "keys": keys})
            with mock.patch.object(webpush.urllib.request, "urlopen", fake_urlopen):
                self.assertEqual(push.send("Lead asks you · t19", "Should I re-render?", "/?task=t19", "task-t19"), 1)
            self.assertEqual(push.count(), 1)                                    # the phone that left is forgotten
            req = sent[0]
            self.assertEqual(req.get_header("Content-encoding"), "aes128gcm")
            self.assertTrue(req.get_header("Authorization").startswith("vapid t="))
            self.assertNotIn(b"Should I re-render", req.data)                   # only the phone can read it


if __name__ == "__main__":
    unittest.main()
