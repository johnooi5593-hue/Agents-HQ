#!/usr/bin/env python3
"""Agents HQ app: a web app over the Claude Code team in this folder.

usage: python3 hq/server.py            (opens http://localhost:7331 in your browser)
       HQ_PORT=8000 python3 hq/server.py --no-browser

Every button in the app sends a message to the lead, which runs Claude Code headless (`claude -p`) in this folder
with the same permission rules as the terminal (`.claude/settings.json`). Uploads go to inbox/, finished work is
served from out/, and Approve moves a folder from out/ to approved/. Nothing is posted anywhere.

By default only your own machine can reach the app (it listens on 127.0.0.1). The hosted version sets
HQ_HOST=0.0.0.0 and HQ_PASSWORD: then every screen and call needs a login, kept in a signed cookie.
  HQ_PASSWORD       the owner's password (required when HQ_HOST is not loopback)
  HQ_SECRET         cookie signing secret; random at every start if unset, so a restart logs everyone out
  HQ_SECURE=1       mark the cookie Secure (set when the app is served over HTTPS; X-Forwarded-Proto also works)
  HQ_MAX_UPLOAD_MB  largest upload accepted (default 2048)
  HQ_TRUST_PROXY=1  behind a reverse proxy (Caddy, Fly): read the client address from X-Forwarded-For
"""
import hashlib, hmac, json, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, webbrowser
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from status import CLIP_EXT, brain_entities, collect  # noqa: E402

PORT = int(os.environ.get("HQ_PORT", "7331"))
HOST = os.environ.get("HQ_HOST", "127.0.0.1")
PASSWORD = os.environ.get("HQ_PASSWORD") or None
SECRET = (os.environ.get("HQ_SECRET") or secrets.token_hex(32)).encode()
SECURE = os.environ.get("HQ_SECURE", "") not in ("", "0", "false")
TRUST_PROXY = os.environ.get("HQ_TRUST_PROXY", "") not in ("", "0", "false")
MAX_UPLOAD = int(os.environ.get("HQ_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
SESSION_DAYS = 30
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")
UPLOAD_DIRS = {"clips": "inbox", "radar": os.path.join("inbox", "radar"), "stats": os.path.join("inbox", "stats")}
UPLOAD_EXT = {"clips": CLIP_EXT, "radar": {".txt", ".md", ".csv", ".json"}, "stats": {".csv"}}
STAFF = ["clip-editor", "brand-checker", "scriptwriter", "scout", "copywriter", "analyst"]


def allow_list():
    """The allow entries of .claude/settings.json, passed to claude -p so the app works before the folder is trusted."""
    try:
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            return list(json.load(f).get("permissions", {}).get("allow", []))
    except (OSError, ValueError):
        return []


def summarize(block):
    """One line for a tool call, for the console and the staff board."""
    name, inp = block.get("name", ""), block.get("input", {}) or {}
    if name in ("Task", "Agent"):
        return {"staff": inp.get("subagent_type"), "text": f"{inp.get('subagent_type', 'agent')}: {inp.get('description') or inp.get('prompt', '')[:80]}"}
    if name == "Bash":
        return {"text": inp.get("command", "")[:160]}
    if name == "Skill":
        return {"text": f"skill {inp.get('skill', '')} {inp.get('args', '') or ''}".strip()}
    if name in ("Read", "Write", "Edit"):
        return {"text": f"{name.lower()} {inp.get('file_path', '')}"}
    if name.startswith("mcp__memory__"):
        return {"text": f"brain: {name.replace('mcp__memory__', '')} {json.dumps(inp.get('names', inp.get('entityName', '')))}"}
    return {"text": name}


def result_text(block):
    """The first 200 characters of a tool result, so the app can tell a background agent from a finished one."""
    c = block.get("content")
    if isinstance(c, list):
        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return (c or "")[:200] if isinstance(c, str) else ""


def translate(obj):
    """Claude Code stream-json line -> app events."""
    t = obj.get("type")
    if t == "system" and obj.get("subtype") == "init":
        return [{"type": "system", "text": f"lead online ({obj.get('model', 'claude')})"}]
    if t == "assistant":
        events = []
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                events.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "tool_use":
                events.append({"type": "tool", "id": block.get("id"), "name": block.get("name"), **summarize(block)})
        return events
    if t == "user":
        content = obj.get("message", {}).get("content", [])
        return [{"type": "tool_done", "id": b.get("tool_use_id"), "is_error": bool(b.get("is_error")), "text": result_text(b)}
                for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
    if t == "result":
        return [{"type": "result", "text": obj.get("result") or "", "is_error": bool(obj.get("is_error")),
                 "cost_usd": obj.get("total_cost_usd"), "duration_ms": obj.get("duration_ms"), "turns": obj.get("num_turns")}]
    return []


class Run:
    def __init__(self, prompt):
        self.id, self.prompt, self.events, self.done, self.ok = uuid.uuid4().hex[:8], prompt, [], False, None

    def add(self, event):
        self.events.append(event)

    def summary(self):
        return {"id": self.id, "prompt": self.prompt, "done": self.done, "ok": self.ok, "events": len(self.events)}


class Desk:
    """One lead conversation. Each message resumes it, so "OK" and corrections keep their context."""

    def __init__(self):
        self.session_id, self.resumable, self.runs, self.order, self.current = str(uuid.uuid4()), False, {}, [], None
        self.lock = threading.Lock()

    def start(self, prompt):
        with self.lock:
            if self.current and not self.current.done:
                return None
            run = Run(prompt)
            self.runs[run.id], self.current = run, run
            self.order.append(run.id)
        threading.Thread(target=self._work, args=(run,), daemon=True).start()
        return run

    def _work(self, run):
        for attempt in (1, 2):
            cmd = [CLAUDE, "-p", run.prompt, "--output-format", "stream-json", "--verbose"]
            allowed = allow_list()
            if allowed:
                cmd += ["--allowedTools", *allowed]
            cmd += ["--resume", self.session_id] if self.resumable else ["--session-id", self.session_id]
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            try:
                p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            except OSError as e:
                run.add({"type": "error", "text": f"could not start claude: {e}. Is Claude Code installed? (npm install -g @anthropic-ai/claude-code)"})
                break
            got_result = False
            for line in p.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    run.add({"type": "system", "text": line[:300]})
                    continue
                for ev in translate(obj):
                    got_result = got_result or ev["type"] == "result"
                    run.add(ev)
            err = p.stderr.read().strip()
            p.wait()
            if got_result:
                run.ok = not any(e.get("is_error") for e in run.events if e["type"] == "result")
                self.resumable = True
                break
            if self.resumable and attempt == 1:          # the old conversation is gone: start a fresh one
                self.session_id, self.resumable = str(uuid.uuid4()), False
                run.add({"type": "system", "text": "previous conversation not found, starting a new one"})
                continue
            run.ok = False
            run.add({"type": "error", "text": (err or f"claude exited with code {p.returncode}")[-2000:]})
            break
        run.done = True

    def state(self):
        with self.lock:
            cur = self.current
        return {"busy": bool(cur and not cur.done), "current": cur.id if cur else None,
                "runs": [self.runs[i].summary() for i in self.order[-20:]]}


desk = Desk()


# login: a signed, expiring token in an HttpOnly cookie; wrong passwords back off per address
def make_token():
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    return exp + "." + hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()


def token_ok(token):
    exp, _, sig = (token or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest())


class Throttle:
    def __init__(self):
        self.fails, self.lock = {}, threading.Lock()

    def wait(self, ip):
        with self.lock:
            n, until = self.fails.get(ip, (0, 0))
            return max(0, int(until - time.time()))

    def failed(self, ip):
        with self.lock:
            n = self.fails.get(ip, (0, 0))[0] + 1
            delay = 0 if n < 5 else min(3600, 30 * 2 ** (n - 5))
            self.fails[ip] = (n, time.time() + delay)

    def passed(self, ip):
        with self.lock:
            self.fails.pop(ip, None)


throttle = Throttle()


def safe_join(base, rel):
    """Absolute path of rel under base, or None if it escapes."""
    full = os.path.realpath(os.path.join(base, rel))
    return full if full == base or full.startswith(base + os.sep) else None


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentsHQ/1.0"

    def log_message(self, fmt, *args):      # quiet, except errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    # helpers
    def send_json(self, obj, code=200, extra=()):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, to, extra=()):
        self.send_response(303)
        self.send_header("Location", to)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def cookie_header(self, value, max_age):
        secure = SECURE or (TRUST_PROXY and self.headers.get("X-Forwarded-Proto", "").lower() == "https")
        return ("Set-Cookie", f"hq_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else ""))

    def authed(self):
        if not PASSWORD:
            return True
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "hq_session" in jar and token_ok(jar["hq_session"].value)

    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "") if TRUST_PROXY else ""
        return (fwd.split(",")[0].strip() if fwd else "") or self.client_address[0]

    def guard(self, page=False):
        """True when the request may go on; otherwise the refusal has been sent."""
        if self.authed():
            return True
        if page:
            self.redirect("/login")
        else:
            self.send_json({"error": "login required"}, 401)
        return False

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def send_file(self, path):
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if m and (m[1] or m[2]):
            start = int(m[1]) if m[1] else max(0, size - int(m[2]))
            end = int(m[2]) if m[1] and m[2] else end
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # routes
    def do_GET(self):
        url = urlparse(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        if path == "/login":
            return self.redirect("/") if not PASSWORD or self.authed() else self.send_file(os.path.join(HERE, "login.html"))
        if path in ("/", "/index.html"):
            return self.guard(page=True) and self.send_file(os.path.join(HERE, "app.html"))
        if not self.guard():
            return
        if path == "/api/status":
            s = collect()
            s["desk"], s["staff"], s["auth"] = desk.state(), STAFF, bool(PASSWORD)
            return self.send_json(s)
        if path == "/api/brain":
            return self.send_json(brain_entities())
        if path == "/api/runs":
            return self.send_json(desk.state())
        m = re.match(r"^/api/runs/([0-9a-f]{8})$", path)
        if m:
            run = desk.runs.get(m[1])
            if not run:
                return self.send_json({"error": "no such run"}, 404)
            after = int(qs.get("after", ["0"])[0])
            return self.send_json({**run.summary(), "events": run.events[after:], "offset": after})
        m = re.match(r"^/files/(out|approved)/(.+)$", path)
        if m:
            base = os.path.join(ROOT, m[1])
            full = safe_join(base, m[2])
            if not full or not os.path.isfile(full):
                return self.send_json({"error": "not found"}, 404)
            return self.send_file(full)
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/login":
            ip = self.client_ip()
            wait = throttle.wait(ip)
            if wait:
                return self.send_json({"error": f"too many wrong passwords, try again in {wait} s"}, 429)
            given = self.read_json().get("password") or ""
            if not PASSWORD or not hmac.compare_digest(given.encode(), PASSWORD.encode()):
                throttle.failed(ip)
                sys.stderr.write(f"login failed from {ip}\n")
                return self.send_json({"error": "wrong password"}, 401)
            throttle.passed(ip)
            sys.stderr.write(f"login ok from {ip}\n")
            return self.send_json({"ok": True}, 200, [self.cookie_header(make_token(), SESSION_DAYS * 86400)])
        if path == "/logout":
            return self.redirect("/login", [self.cookie_header("", 0)])
        if not self.guard():
            return
        if path == "/api/run":
            prompt = (self.read_json().get("prompt") or "").strip()
            if not prompt:
                return self.send_json({"error": "empty message"}, 400)
            run = desk.start(prompt)
            if not run:
                return self.send_json({"error": "the lead is still working on the previous message"}, 409)
            return self.send_json(run.summary(), 202)
        if path == "/api/approve":
            name = self.read_json().get("name") or ""
            src = safe_join(os.path.join(ROOT, "out"), name)
            if not name or not SAFE_NAME.match(name) or not src or not os.path.isdir(src):
                return self.send_json({"error": "no such work folder"}, 404)
            os.makedirs(os.path.join(ROOT, "approved"), exist_ok=True)
            dst = os.path.join(ROOT, "approved", name)
            if os.path.exists(dst):
                return self.send_json({"error": "already approved"}, 409)
            shutil.move(src, dst)
            return self.send_json({"approved": name})
        return self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        if not self.guard():
            return
        m = re.match(r"^/api/inbox/(clips|radar|stats)/([^/]+)$", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        kind, name = m[1], m[2]
        if int(self.headers.get("Content-Length") or 0) > MAX_UPLOAD:
            return self.send_json({"error": f"file larger than {MAX_UPLOAD // (1024 * 1024)} MB"}, 413)
        if not SAFE_NAME.match(name) or os.path.splitext(name)[1].lower() not in UPLOAD_EXT[kind]:
            return self.send_json({"error": f"{kind} accepts {' '.join(sorted(UPLOAD_EXT[kind]))} files with a plain name"}, 400)
        folder = os.path.join(ROOT, UPLOAD_DIRS[kind])
        os.makedirs(folder, exist_ok=True)
        dst = os.path.join(folder, name)
        if os.path.exists(dst):
            return self.send_json({"error": "a file with that name is already in the inbox"}, 409)
        n, tmp = int(self.headers.get("Content-Length") or 0), dst + ".part"
        with open(tmp, "wb") as f:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        os.replace(tmp, dst)
        return self.send_json({"saved": os.path.relpath(dst, ROOT), "bytes": n}, 201)


def main():
    if HOST not in ("127.0.0.1", "localhost", "::1") and not PASSWORD:
        sys.exit(f"Refusing to listen on {HOST} without HQ_PASSWORD: anyone who reaches this port could run your team.")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Agents HQ is open at {url}   (Ctrl+C to close)" + ("   login required" if PASSWORD else ""))
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAgents HQ closed.")


if __name__ == "__main__":
    main()
