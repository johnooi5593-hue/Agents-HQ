import ast
import base64
import html
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

# The office's name and access code straight from server.py (importing it would start the office), in a temp office.
SERVER = Path(__file__).resolve().parents[1] / "server.py"
NAMES = {"office_conf", "office_name", "named", "access_key_text", "git_ssh"}
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n-----END OPENSSH PRIVATE KEY-----\n"


def load(root, repo_url):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    env = {"os": os, "re": re, "json": json, "html": html, "base64": base64, "ROOT": root, "REPO_URL": repo_url,
           "OFFICE_FILE": os.path.join(root, ".hq-office.json"), "_OFFICE": {"mtime": None, "data": {}},
           "ACCESS_KEY": os.path.join(root, ".hq-access-key"), "ACCESS_PREFIX": "HQ1."}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server-office", "exec"), env)
    return env


class OfficeConfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        os.environ.pop("HQ_OFFICE_NAME", None)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        path = os.path.join(self.root, ".hq-office.json")
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        os.utime(path, ns=(os.stat(path).st_mtime_ns + 10**9,) * 2)        # a fresh mtime, as a real save gives

    def test_without_a_file_it_is_agents_hq_and_pages_are_untouched(self):
        env = load(self.root, "https://github.com/x/y")
        self.assertEqual(env["office_name"](), "Agents HQ")
        self.assertEqual(env["named"](b"<title>Agents HQ</title>", "text/html"), b"<title>Agents HQ</title>")

    def test_the_clients_name_goes_on_pages_and_the_phone_app_safely(self):
        env = load(self.root, "https://github.com/x/y")
        self.write({"name": 'Acme <script>"HQ"</script>'})
        name = env["office_name"]()
        self.assertEqual(name, "Acme scriptHQ/script")
        self.assertEqual(env["named"](b"<title>Agents HQ</title>", "text/html; charset=utf-8"), f"<title>{name}</title>".encode())
        self.write({"name": "Kopi & Co"})
        self.assertEqual(env["office_name"](), "Kopi  Co")
        self.write({"name": "Café 新加坡 HQ"})
        manifest = env["named"](b'{"name": "Agents HQ"}', "application/manifest+json")
        self.assertEqual(json.loads(manifest)["name"], "Café 新加坡 HQ")
        self.assertEqual(env["named"](b"var a='Agents HQ'", "text/javascript"), b"var a='Agents HQ'")   # scripts keep the app's name

    def test_a_broken_file_is_ignored(self):
        env = load(self.root, "https://github.com/x/y")
        Path(self.root, ".hq-office.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(env["office_name"](), "Agents HQ")

    def test_https_updates_need_no_key(self):
        env = load(self.root, "https://github.com/x/y")
        self.write({"access": "HQ1." + base64.urlsafe_b64encode(KEY.encode()).decode().rstrip("=")})
        self.assertEqual(env["git_ssh"](), "")

    def test_a_private_repo_uses_the_key_in_the_access_code_and_never_prompts(self):
        env = load(self.root, "git@github.com:x/y.git")
        cmd = env["git_ssh"]()
        self.assertIn("BatchMode=yes", cmd)
        self.assertNotIn(" -i ", cmd)                                     # no code yet: fails fast instead of asking
        self.assertFalse(os.path.exists(os.path.join(self.root, ".hq-access-key")))
        code = "HQ1." + base64.urlsafe_b64encode(KEY.encode()).decode().rstrip("=")
        self.write({"access": code[:40] + "\n  " + code[40:]})           # pasted with a line break
        cmd = env["git_ssh"]()
        key = os.path.join(self.root, ".hq-access-key")
        self.assertIn('-i "' + key.replace(os.sep, "/") + '"', cmd)
        self.assertIn("IdentitiesOnly=yes", cmd)
        self.assertEqual(Path(key).read_bytes(), KEY.encode())               # LF line endings, as ssh wants

    def test_only_a_real_key_counts_as_an_access_code(self):
        env = load(self.root, "git@github.com:x/y.git")
        akt = env["access_key_text"]
        self.assertEqual(akt("HQ1." + base64.urlsafe_b64encode(KEY.encode()).decode()), KEY)
        self.assertEqual(akt("HQ1." + base64.urlsafe_b64encode(b"hello").decode()), "")
        self.assertEqual(akt("HQ1.%%%"), "")
        self.assertEqual(akt(""), "")
        self.assertEqual(akt(None), "")


if __name__ == "__main__":
    unittest.main()
