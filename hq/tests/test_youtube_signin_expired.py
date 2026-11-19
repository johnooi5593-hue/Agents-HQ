"""A refused YouTube token refresh says what to do (2026-11-19, Pong 1121: the card only showed "400: Bad Request")."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish


class YoutubeSigninExpiredTests(unittest.TestCase):
    def accounts(self):
        a = publish.Accounts.__new__(publish.Accounts)
        a.get = lambda platform, channel="": {"refresh_token": "r", "client_id": "c", "client_secret": "s"}
        return a

    def test_refused_refresh_says_reconnect(self):
        def http(*a, **k):
            raise publish.PostError("400: Bad Request")
        with mock.patch.object(publish, "http", http):
            with self.assertRaises(publish.PostError) as e:
                self.accounts().youtube_token("pong-gospel")
        self.assertIn("Reconnect YouTube", str(e.exception))
        self.assertIn("Nothing was changed on YouTube", str(e.exception))

    def test_other_errors_pass_through(self):
        def http(*a, **k):
            raise publish.PostError("no connection (timed out)")
        with mock.patch.object(publish, "http", http):
            with self.assertRaises(publish.PostError) as e:
                self.accounts().youtube_token()
        self.assertEqual(str(e.exception), "no connection (timed out)")

    def test_ok_returns_the_token(self):
        with mock.patch.object(publish, "http", lambda *a, **k: (200, {}, {"access_token": "tok"})):
            self.assertEqual(self.accounts().youtube_token(), "tok")


if __name__ == "__main__":
    unittest.main()
