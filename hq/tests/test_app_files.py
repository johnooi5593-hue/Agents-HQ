import ast
import gzip
import io
import mimetypes
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path

# send_app_file straight from server.py (importing it would start the office), on a fake request.
SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_send_app_file():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Handler")
    fn = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "send_app_file")
    env = {"os": os, "re": re, "gzip": gzip, "mimetypes": mimetypes, "APP_GZ": {}, "APP_GZ_LOCK": threading.Lock()}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "server-app-files", "exec"), env)
    return env["send_app_file"]


class FakeRequest:
    def __init__(self, headers):
        self.headers, self.status, self.sent, self.wfile = headers, None, {}, io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass

    def send_json(self, obj, code=200):
        self.status = code


class AppFileTests(unittest.TestCase):
    def setUp(self):
        self.send = load_send_app_file()
        self.temp = tempfile.TemporaryDirectory()
        self.js = os.path.join(self.temp.name, "office3d.js")
        Path(self.js).write_bytes(b"const office = 1;\n" * 2000)

    def tearDown(self):
        self.temp.cleanup()

    def get(self, **headers):
        req = FakeRequest(headers)
        self.send(req, self.js)
        return req

    def test_a_phone_gets_the_script_gzipped_with_an_etag(self):
        r = self.get(**{"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.sent["Content-Encoding"], "gzip")
        self.assertEqual(r.sent["Cache-Control"], "no-cache")
        self.assertTrue(r.sent["Content-Type"].startswith("text/javascript") or r.sent["Content-Type"].startswith("application/javascript"))
        body = r.wfile.getvalue()
        self.assertEqual(int(r.sent["Content-Length"]), len(body))
        self.assertEqual(gzip.decompress(body), Path(self.js).read_bytes())
        self.assertLess(len(body), os.path.getsize(self.js) // 4)

    def test_without_gzip_the_file_comes_as_it_is(self):
        r = self.get()
        self.assertNotIn("Content-Encoding", r.sent)
        self.assertEqual(r.wfile.getvalue(), Path(self.js).read_bytes())

    def test_an_unchanged_file_answers_304_and_a_changed_one_is_sent_again(self):
        etag = self.get(**{"Accept-Encoding": "gzip"}).sent["ETag"]
        again = self.get(**{"If-None-Match": etag, "Accept-Encoding": "gzip"})
        self.assertEqual(again.status, 304)
        self.assertEqual(again.wfile.getvalue(), b"")
        Path(self.js).write_bytes(b"const office = 2;\n")                              # an update changes the file
        os.utime(self.js, ns=(1, 1))
        fresh = self.get(**{"If-None-Match": etag, "Accept-Encoding": "gzip"})
        self.assertEqual(fresh.status, 200)
        self.assertEqual(gzip.decompress(fresh.wfile.getvalue()), b"const office = 2;\n")

    def test_a_missing_file_is_404(self):
        r = FakeRequest({})
        self.send(r, os.path.join(self.temp.name, "nope.js"))
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()
