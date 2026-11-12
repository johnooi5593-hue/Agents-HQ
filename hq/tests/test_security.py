import ast
import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# The security checks straight from server.py (importing it would start the office): the Handler methods are rebuilt
# on a small BaseHTTPRequestHandler subclass with a fake request, the module functions run on their own.
SERVER = Path(__file__).resolve().parents[1] / "server.py"
TEXT = SERVER.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)
HANDLER = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "Handler")


def method_source(name):
    fn = next(n for n in HANDLER.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return textwrap.dedent(ast.get_source_segment(TEXT, fn))


def class_attr_source(name):
    node = next(n for n in HANDLER.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return textwrap.dedent(ast.get_source_segment(TEXT, node))


def module_function(name, env):
    fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "server-" + name, "exec"), env)
    return env[name]


def build_handler(password=None):
    body = "\n".join([class_attr_source("PLAIN_TYPES")] + [method_source(n) for n in ("same_site", "read_json", "guard", "relayed", "end_headers", "send_file")])
    src = "class H(BaseHTTPRequestHandler):\n" + textwrap.indent(body, "    ") + "\n    def authed(self):\n        return True\n    def log_request(self, *a, **k):\n        pass\n"
    env = {"BaseHTTPRequestHandler": BaseHTTPRequestHandler, "os": os, "re": __import__("re"), "json": json, "mimetypes": __import__("mimetypes"),
           "urlparse": urlparse, "PASSWORD": password, "MAX_JSON": 8 * 1024 * 1024}
    exec(src, env)
    return env["H"]


def fake(cls, headers, body=b""):
    h = cls.__new__(cls)
    h.headers, h.rfile, h.wfile, h.request_version, h.status = headers, io.BytesIO(body), io.BytesIO(), "HTTP/1.1", None
    h._headers_buffer, h.sent = [], {}
    h.send_json = lambda obj, code=200, extra=(): setattr(h, "status", code)
    return h


class SameSite(unittest.TestCase):
    def test_a_page_on_another_site_is_refused(self):
        H = build_handler()
        h = fake(H, {"Origin": "http://evil.example", "Host": "localhost:7332"})
        self.assertFalse(h.same_site()); self.assertEqual(h.status, 403)
        h = fake(H, {"Sec-Fetch-Site": "cross-site", "Host": "localhost:7332"})
        self.assertFalse(h.same_site()); self.assertEqual(h.status, 403)
        h = fake(H, {"Origin": "null", "Host": "localhost:7332"})
        self.assertFalse(h.same_site())

    def test_the_office_s_own_pages_and_local_tools_pass(self):
        H = build_handler()
        self.assertTrue(fake(H, {"Origin": "http://localhost:7332", "Host": "localhost:7332", "Sec-Fetch-Site": "same-origin"}).same_site())
        self.assertTrue(fake(H, {"Host": "127.0.0.1:7332"}).same_site())                      # hq/restart.py: no Origin at all
        # a phone through tailscale serve: https, the forwarded host
        phone = {"Origin": "https://pc.tail.ts.net:8443", "Host": "pc.tail.ts.net:8443", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "pc.tail.ts.net:8443"}
        self.assertTrue(fake(H, phone).same_site())
        wrong_scheme = dict(phone, Origin="http://pc.tail.ts.net:8443")
        self.assertFalse(fake(H, wrong_scheme).same_site())


class JsonBody(unittest.TestCase):
    def test_a_huge_or_broken_length_is_not_read(self):
        H = build_handler()
        self.assertEqual(fake(H, {"Content-Length": str(9 * 1024 * 1024)}).read_json(), {})
        self.assertEqual(fake(H, {"Content-Length": "lots"}).read_json(), {})
        self.assertEqual(fake(H, {"Content-Length": "9"}, b'{"a": 1}\n').read_json(), {"a": 1})


class NoPassword(unittest.TestCase):
    def test_a_proxied_phone_is_refused_without_a_password(self):
        H = build_handler(password=None)
        h = fake(H, {"Host": "pc.tail.ts.net:8443"})
        self.assertFalse(h.guard()); self.assertEqual(h.status, 403)
        h = fake(H, {"Host": "127.0.0.1:7332", "X-Forwarded-For": "100.1.2.3"})
        self.assertFalse(h.guard())
        self.assertTrue(fake(H, {"Host": "localhost:7332"}).guard())        # this computer's own window

    def test_with_a_password_the_login_decides(self):
        H = build_handler(password="x")
        self.assertTrue(fake(H, {"Host": "pc.tail.ts.net:8443"}).guard())   # authed() is the fake's True here


class Headers(unittest.TestCase):
    def test_every_reply_gets_nosniff_and_pages_cannot_be_framed(self):
        H = build_handler()
        h = fake(H, {})
        h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8"); h.end_headers()
        out = h.wfile.getvalue().decode()
        self.assertIn("X-Content-Type-Options: nosniff", out); self.assertIn("X-Frame-Options: SAMEORIGIN", out)
        h = fake(H, {})
        h.send_response(200); h.send_header("Content-Type", "application/json"); h.end_headers()
        out = h.wfile.getvalue().decode()
        self.assertIn("X-Content-Type-Options: nosniff", out); self.assertNotIn("X-Frame-Options", out)
        self.assertEqual(out.count("X-Content-Type-Options"), 1)


class WorkFiles(unittest.TestCase):
    def test_an_html_file_from_out_is_shown_as_text(self):
        H = build_handler()
        with tempfile.TemporaryDirectory() as d:
            page, note = os.path.join(d, "post.html"), os.path.join(d, "post.md")
            Path(page).write_text("<script>alert(1)</script>", encoding="utf-8"); Path(note).write_text("# hi", encoding="utf-8")
            h = fake(H, {}); h.send_file(page, plain_markup=True)
            self.assertIn("Content-Type: text/plain; charset=utf-8", h.wfile.getvalue().decode())
            h = fake(H, {}); h.send_file(page)                                    # the studios' own static files keep their type
            self.assertIn("Content-Type: text/html", h.wfile.getvalue().decode())
            h = fake(H, {}); h.send_file(note, plain_markup=True)
            self.assertNotIn("text/plain", h.wfile.getvalue().decode().split("\r\n\r\n")[0].replace("Content-Type: text/markdown", ""))


class ClaudeCommand(unittest.TestCase):
    def test_the_npm_shim_is_replaced_by_the_exe_it_starts(self):
        with tempfile.TemporaryDirectory() as d:
            shim = os.path.join(d, "claude.cmd")
            Path(shim).write_text("@echo off\r\n", encoding="utf-8")
            exe = os.path.join(d, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
            env = {"os": os, "shutil": shutil, "CLAUDE": shim}
            claude_argv = module_function("claude_argv", env)
            self.assertEqual(claude_argv(), [shim])                                # no exe beside it: the shim as before
            os.makedirs(os.path.dirname(exe)); Path(exe).write_bytes(b"MZ")
            self.assertEqual(claude_argv(), [exe])                                 # the exe itself: no cmd.exe in between
            env["CLAUDE"] = os.path.join(d, "other-claude")                        # a plain path is used as it is
            self.assertEqual(claude_argv(), [os.path.join(d, "other-claude")])

    def test_the_password_and_secret_never_reach_an_agent(self):
        hidden = next(n for n in TREE.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CHILD_HIDDEN" for t in n.targets))
        names = ast.literal_eval(hidden.value)
        self.assertTrue({"HQ_PASSWORD", "HQ_SECRET", "CLAUDECODE"} <= set(names))
        self.assertIn("if k not in CHILD_HIDDEN", TEXT)


if __name__ == "__main__":
    unittest.main()
