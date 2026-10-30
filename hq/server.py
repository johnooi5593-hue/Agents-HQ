#!/usr/bin/env python3
"""Agents HQ app: a web app over the Claude Code team in this folder.

usage: python3 hq/server.py            (opens http://localhost:7331 in your browser)
       HQ_PORT=8000 python3 hq/server.py --no-browser

Every button in the app sends a message to the lead, which runs Claude Code headless (`claude -p`) in this folder
with the same permission rules as the terminal (`.claude/settings.json`). Uploads go to inbox/, finished work is
served from out/, and Approve moves a folder from out/ to approved/. Nothing is posted anywhere.

The API is listed in docs/build-contract.md ("Backend API"): status, teams (hq/teams.json plus live counts), agents,
the hook feed, the board (hq/tasks.json), notifications, the calendar, the brain, runs, uploads and approvals.

By default only your own machine can reach the app (it listens on 127.0.0.1). The hosted version sets
HQ_HOST=0.0.0.0 and HQ_PASSWORD: then every screen and call needs a login, kept in a signed cookie.
  HQ_PASSWORD       the owner's password (required when HQ_HOST is not loopback)
  HQ_SECRET         cookie signing secret; random at every start if unset, so a restart logs everyone out
  HQ_SECURE=1       mark the cookie Secure (set when the app is served over HTTPS; X-Forwarded-Proto also works)
  HQ_MAX_UPLOAD_MB  largest upload accepted (default 2048)
  HQ_TRUST_PROXY=1  behind a reverse proxy (Caddy, Fly): read the client address from X-Forwarded-For
  HQ_LOCAL_TRUST=1  phone access from the desktop app: requests from this computer itself need no login, every other
                    device (a phone on Wi-Fi or Tailscale) does. Never combine with HQ_TRUST_PROXY.
"""
import base64, datetime, gzip, hashlib, hmac, html, json, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, webbrowser
import datetime, gzip, hashlib, hmac, html, json, math, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, webbrowser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from followups import FollowUps
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from status import CLIP_EXT, brain_entities, brain_notes, collect, files  # noqa: E402
import channels as channels_mod  # noqa: E402
import activity  # noqa: E402  (watches every Claude Code session on this computer)
import publish  # noqa: E402  (posts approved work, only when the owner presses Post)
import webpush  # noqa: E402  (phone notifications for the installed app)
from sermon_design import SermonDesignBridge  # noqa: E402  (native renderer; no Claude execution)
from sermon_design import DesignError  # noqa: E402
from video_package import Packages  # noqa: E402  (each video's steps: video, caption, thumbnails → READY)
from scripts_step import Scripts  # noqa: E402  (scripts first: the owner approves the passages before any video is cut)
from thumbnail_design import ThumbnailDesignBridge  # noqa: E402
from thumbnail_design import small_image as thumbnail_preview, send_preview as thumbnail_send_preview  # noqa: E402

PORT = int(os.environ.get("HQ_PORT", "7331"))
HOST = os.environ.get("HQ_HOST", "127.0.0.1")
PASSWORD = os.environ.get("HQ_PASSWORD") or None
SECRET = (os.environ.get("HQ_SECRET") or secrets.token_hex(32)).encode()
SECURE = os.environ.get("HQ_SECURE", "") not in ("", "0", "false")
TRUST_PROXY = os.environ.get("HQ_TRUST_PROXY", "") not in ("", "0", "false")
LOCAL_TRUST = os.environ.get("HQ_LOCAL_TRUST", "") not in ("", "0", "false")   # the desktop app: this computer's own window skips the login
MAX_UPLOAD = int(os.environ.get("HQ_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
SESSION_DAYS = 30
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")
UPLOAD_DIRS = {"clips": "inbox", "radar": os.path.join("inbox", "radar"), "stats": os.path.join("inbox", "stats"),
               "messages": os.path.join("inbox", "messages")}
UPLOAD_EXT = {"clips": CLIP_EXT, "radar": {".txt", ".md", ".csv", ".json"}, "stats": {".csv"},
              "messages": {".txt", ".md", ".eml", ".json", ".csv", ".html"}}
FALLBACK_TEAM_ORDER = ["Research", "Scripts", "Social", "Creative", "Analytics", "Shop", "Dev", "Inbox"]
EVENTS = os.path.join(HERE, "events.jsonl")
TASKS = os.path.join(HERE, "tasks.json")
TEAMS_FILE = os.path.join(HERE, "teams.json")
MCP_FILE = os.path.join(ROOT, ".mcp.json")
STATIC = {"/hud.js", "/hud.css", "/office3d.js", "/thumbnail-studio.html", "/thumbnail-studio.js", "/thumbnail-studio.css"}
APP_GZ, APP_GZ_LOCK = {}, threading.Lock()                 # gzipped app files, by path: (etag, bytes)
PWA_FILES = {"/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"), "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
             "/offline.html": ("offline.html", "text/html; charset=utf-8"), "/icons/icon-192.png": ("icon-192.png", "image/png"),
             "/icons/icon-512.png": ("icon-512.png", "image/png"), "/icons/icon-maskable-512.png": ("icon-maskable-512.png", "image/png"),
             "/icons/apple-touch-icon.png": ("apple-touch-icon.png", "image/png")}
STATUSES = ("todo", "doing", "review", "done", "cancelled")   # cancelled: dropped by the owner, kept so it can come back
KINDS = ("task", "approval", "post", "meeting")
SCHEDULED_KINDS = ("post", "meeting")
TASK_DEFAULTS = {"team": "", "agent": "", "note": "", "kind": "task", "subtitle": "", "progress": None, "date": None, "time": None, "done_at": None, "channel": None}
OFFICE = "@office"      # task.channel: None = worked out from the task (task_channel), a channel key, or OFFICE = whole office
ACRONYMS = {"seo": "SEO", "qa": "QA", "ai": "AI", "ux": "UX", "ui": "UI", "pr": "PR", "hq": "HQ"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class BoardLock:
    """The board's lock: one thread at a time in this server, and one process at a time across the office through
    hq/tasks.lock, which hq/tasks.js takes too (several lead jobs can run `node hq/tasks.js` at the same moment).
    A lock older than STALE seconds was left by a process that died; waiting longer than WAIT goes on without it."""
    STALE, WAIT = 15, 10

    def __init__(self, path):
        self.path, self.local, self.depth, self.fd = path, threading.RLock(), 0, None

    def __enter__(self):
        self.local.acquire()
        self.depth += 1
        if self.depth == 1:
            end = time.time() + self.WAIT
            while self.fd is None and time.time() < end:
                try:
                    self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    try:
                        if time.time() - os.path.getmtime(self.path) > self.STALE:
                            os.remove(self.path)      # our own lock file, left behind by a process that stopped
                            continue
                    except OSError:
                        pass
                    time.sleep(0.02)
                except OSError:
                    break                             # a read-only folder: the in-process lock still holds
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        if self.depth == 0 and self.fd is not None:
            os.close(self.fd)
            self.fd = None
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.local.release()


TASK_LOCK = BoardLock(os.path.join(HERE, "tasks.lock"))


# small helpers
def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_iso(s):
    """An aware datetime from an ISO string such as 2026-10-25T03:09:06.957Z, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def iso_ms(s):
    """Milliseconds since the epoch for an ISO string, or now when it does not parse."""
    d = parse_iso(s)
    return int(d.timestamp() * 1000) if d else int(time.time() * 1000)


def is_today(s):
    d = parse_iso(s)
    return bool(d) and d.astimezone().date() == datetime.date.today()


def label_of(name):
    """clip-editor -> Clip Editor, seo-specialist -> SEO Specialist."""
    return " ".join(ACRONYMS.get(p, p.capitalize()) for p in re.split(r"[-_\s]+", name or "") if p)


def team_key(team):
    return re.sub(r"\s+", "-", (team or "office").strip().lower())


def slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def qs_int(qs, key, default=0):
    try:
        return max(0, int(qs.get(key, [default])[0]))
    except (TypeError, ValueError):
        return default


# teams: hq/teams.json plus what is live
def load_teams():
    try:
        with open(TEAMS_FILE, encoding="utf-8") as f:
            return [t for t in json.load(f).get("teams", []) if isinstance(t, dict) and t.get("key") and t.get("name")]
    except (OSError, ValueError):
        return []


def team_order():
    return [t["name"] for t in load_teams()] or list(FALLBACK_TEAM_ORDER)


def mcp_servers():
    """The server names in .mcp.json, slugged, so a tool named like one counts as connected."""
    try:
        with open(MCP_FILE, encoding="utf-8") as f:
            return {slug(k) for k in json.load(f).get("mcpServers", {})}
    except (OSError, ValueError):
        return set()


POSTING_TOOLS = {"facebook": "facebook", "instagram": "instagram", "youtube": "youtube"}


def posting_account(tool):
    """Facebook, Instagram and YouTube are the posting accounts (user menu → Accounts for posting), whatever an older
    teams.json says about them."""
    return tool.get("account") or POSTING_TOOLS.get(slug(tool.get("name") or ""))


def tool_status(tool, servers):
    acct = posting_account(tool)
    if acct:                                               # an account connected under Accounts for posting
        return "connected" if (accounts.summary().get(acct) or {}).get("connected") else "not connected"
    if tool.get("via") == "skill":
        script = tool.get("script") or ""
        return "connected" if script and os.path.isfile(os.path.join(ROOT, script)) else "not connected"
    names = {slug(tool.get("name"))} | {slug(a) for a in tool.get("mcp", []) if isinstance(a, str)}
    return "connected" if names & servers else "not connected"


def teams_payload(agent_list=None, running=None):
    """Every team in the fixed order with its live agent and running counts."""
    agent_list = agents()["agents"] if agent_list is None else agent_list
    running = events()["running"] if running is None else running
    servers, out = mcp_servers(), []
    for t in load_teams():
        members = sorted((a for a in agent_list if a["team"] == t["name"]), key=lambda a: (a["role"] != "head", a["name"]))
        team = dict(t)
        team["lead_label"] = label_of(t.get("lead", ""))
        tools = [tool for tool in t.get("tools", []) if isinstance(tool, dict)]
        if t.get("key") == "social":                       # the Social team always shows the three posting accounts first
            have = {posting_account(x) for x in tools}
            tools = [{"name": n.title() if n != "youtube" else "YouTube", "account": n} for n in ("facebook", "instagram", "youtube") if n not in have] + tools
            tools.sort(key=lambda x: 0 if posting_account(x) else 1)
        team["tools"] = [{**tool, **({"via": "posting", "account": posting_account(tool), "detail": (accounts.summary().get(posting_account(tool)) or {}).get("name", "")} if posting_account(tool) else {}),
                          "status": tool_status(tool, servers)} for tool in tools]
        team["skills"] = [s for s in t.get("skills", []) if isinstance(s, dict)]
        team["agents"] = [a["name"] for a in members]
        team["agent_count"] = len(members)
        team["running"] = sum(running.get(a["name"], 0) for a in members)
        out.append(team)
    return out


def agents():
    """Every agent in .claude/agents/*.md: frontmatter fields the office needs."""
    out = []
    folder = os.path.join(ROOT, ".claude", "agents")
    colors = {t["name"]: t.get("color", "") for t in load_teams()}
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not fn.endswith(".md"):
            continue
        try:
            text = open(os.path.join(folder, fn), encoding="utf-8").read()
        except OSError:
            continue
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            continue
        fm, skills = {}, []
        for line in m.group(1).splitlines():
            if line.startswith("  - "):
                skills.append(line[4:].strip())
            elif ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        name, team = fm.get("name", fn[:-3]), fm.get("team", "Office")
        out.append({"name": name, "label": label_of(name), "team": team, "teamKey": team_key(team), "teamColor": colors.get(team, ""),
                    "role": fm.get("role", "worker"), "model": fm.get("model", ""), "description": fm.get("description", ""),
                    "tools": [t.strip() for t in fm.get("tools", "").split(",") if t.strip()], "skills": skills, "color": fm.get("color", "")})
    order = team_order()
    teams = [t for t in order if any(a["team"] == t for a in out)] + sorted({a["team"] for a in out} - set(order))
    return {"agents": out, "teams": teams}


def events(after=0):
    """The hook feed: events after line `after`, and which agents are running now (started, not stopped)."""
    lines = []
    try:
        with open(EVENTS, encoding="utf-8") as f:
            for line in f:
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    open_ids, running = {}, {}
    cutoff = time.time() * 1000 - 6 * 3600 * 1000           # a start older than six hours without a stop is a crash, not a run
    for e in lines:
        if e.get("event") == "start" and e.get("ts", 0) > cutoff:
            open_ids[e.get("id") or e.get("agent")] = e.get("agent")
        elif e.get("event") == "stop":
            open_ids.pop(e.get("id") or e.get("agent"), None)
    for name in open_ids.values():
        running[name] = running.get(name, 0) + 1
    act = claude_activity()                                   # Claude sessions anywhere on this computer (see hq/activity.py)
    for name, n in act["running"].items():
        running[name] = max(running.get(name, 0), n)          # the same work seen twice counts once
    return {"events": lines[after:], "offset": after, "total": len(lines), "running": running,
            "activity": act["text"], "sessions": act["sessions"]}


_activity_cache = {"t": 0.0, "v": {"running": {}, "text": {}, "sessions": []}}
_activity_lock = threading.Lock()


def claude_activity():
    """activity.scan() at most once every 1.5 s, shared by every request."""
    with _activity_lock:
        if time.time() - _activity_cache["t"] > 1.5:
            try:
                names = [a["name"] for a in agents()["agents"]]
                _activity_cache["v"] = activity.scan(agent_names=names)
            except Exception as e:                               # never let the watcher break the office
                sys.stderr.write(f"activity watch skipped: {e}\n")
            _activity_cache["t"] = time.time()
        return _activity_cache["v"]


# the board: hq/tasks.json, shared with hq/tasks.js
def normalize_task(t):
    for k, v in TASK_DEFAULTS.items():
        t.setdefault(k, v)
    if t.get("status") not in STATUSES:
        t["status"] = "todo"
    if t.get("kind") not in KINDS:
        t["kind"] = "task"
    return t


def load_tasks():
    try:
        with open(TASKS, encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        db = {"tasks": []}
    if not isinstance(db, dict):
        db = {"tasks": []}
    db["tasks"] = [normalize_task(t) for t in db.get("tasks", []) if isinstance(t, dict)]
    return db


def save_tasks(db):
    """Write the board whole, then swap it in: a reader (hq/tasks.js, another lead job) never sees half a file."""
    tmp = f"{TASKS}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
        f.write("\n")
    for attempt in range(20):                  # Windows refuses the swap while another process is reading the file
        try:
            os.replace(tmp, TASKS)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, TASKS)


def clean_date(s):
    s = (s or "").strip() if isinstance(s, str) else ""
    if not DATE_RE.match(s):
        return None
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return None
    return s


def clean_time(s):
    s = (s or "").strip() if isinstance(s, str) else ""
    return s if TIME_RE.match(s) else None


def clean_progress(p):
    if p is None or p == "":
        return None
    try:
        return max(0, min(100, int(float(p))))
    except (TypeError, ValueError):
        return None


def set_status(t, status):
    t["status"], t["updated"] = status, now_iso()
    if status == "done":
        t["done_at"] = t.get("done_at") or now_iso()
        if t.get("progress") is not None:
            t["progress"] = 100
    else:
        t["done_at"] = None


def approve_folder(name):
    """Serialize final approval against new thumbnail revisions."""
    bridge = globals().get("thumbnail_design")
    if bridge:
        with bridge.lock:
            return _approve_folder(name)
    return _approve_folder(name)


def _approve_folder(name):
    """Move out/<name> to approved/<name>. Returns (http code, payload)."""
    src = safe_join(os.path.join(ROOT, "out"), name) if name else None
    if not name or not SAFE_NAME.match(name) or not src or not os.path.isdir(src):
        return 404, {"error": "no such work folder"}
    if "thumbnail_design" in globals():
        # a READY video (every step of its package picked) goes through; its Codex package was approved just before
        error = None if not name.startswith("thumbnail-final-") and "packages" in globals() and packages.ready(name) else thumbnail_design.guard_approval(name)
        if error:
            return 409, {"error": error, "thumbnailWorkflow": True}
    os.makedirs(os.path.join(ROOT, "approved"), exist_ok=True)
    dst = os.path.join(ROOT, "approved", name)
    if os.path.exists(dst):
        return 409, {"error": "already approved"}
    shutil.move(src, dst)
    on_approved(name)
    return 200, {"approved": name}


html_escape = html.escape
accounts = publish.Accounts(ROOT)


def post_scheduled(folder, when, platforms):
    """A scheduled post becomes a dated "post" task on the board, so it shows in the Calendar."""
    t = time.localtime(int(when))
    names = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok"}
    code, r = task_action({"action": "add", "title": "Post: " + os.path.relpath(folder, os.path.join(ROOT, "approved")).replace(os.sep, " / "),
                           "team": "Social", "kind": "post", "status": "todo", "date": time.strftime("%Y-%m-%d", t),
                           "time": time.strftime("%H:%M", t), "note": ", ".join(names.get(p, p) for p in platforms)})
    return r.get("added", {}).get("id") if code < 400 else None


def post_finished(folder, task_id, states):
    task_action({"action": "move", "id": task_id, "status": "done"})


publisher = publish.Publisher(ROOT, accounts, on_schedule=post_scheduled, on_finish=post_finished)
BRAIN_LOCK = threading.Lock()


def brain_add(name, kind, observations):
    """A new entity in the brain (a new channel's Company and Brand rules); an existing one is left as it is."""
    path = os.path.join(ROOT, "brain", "memory.jsonl")
    with BRAIN_LOCK:
        if name in brain_entities():
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a+", encoding="utf-8") as f:
            f.seek(0)
            text = f.read()
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(json.dumps({"type": "entity", "name": name, "entityType": kind, "observations": observations}, ensure_ascii=False) + "\n")


channels = channels_mod.Channels(ROOT, add_task=lambda **t: task_action({"action": "add", **t}), add_brain=brain_add)


def channels_action(body):
    """POST /api/channels: add a channel, or set a channel's Drive folder (and the main channel's name)."""
    try:
        if body.get("action") == "add":
            key = channels.add(body.get("name"), body.get("about"), body.get("drive"))
            return 201, {"added": key, **channels.payload()}
        if body.get("action") == "update":
            channels.update(str(body.get("key") or ""), body.get("name"), body.get("drive"))
            return 200, channels.payload()
        if body.get("action") == "scan":
            return 200, {"imported": channels.scan(), **channels.payload()}
    except ValueError as e:
        return 400, {"error": str(e)}
    return 400, {"error": "action: add (name, about?, drive?), update (key, drive?, name?) or scan"}


FOOTAGE = re.compile(r"inbox:(inbox/.+?)\s*$", re.M)                 # the path is the rest of the line: it may hold spaces


def task_footage(task):
    """New footage waiting in the inbox: (its path, its channel key), or None once it was edited (moved to done/)."""
    m = FOOTAGE.search(task.get("note") or "")
    if not m:
        return None
    path = safe_join(ROOT, m[1])
    ch = re.search(r"channel:([a-z0-9-]+)", task.get("note") or "")
    return (m[1], ch[1] if ch else "") if path and os.path.isfile(path) else None


def task_channel(task):
    """The channel a task belongs to (a key, "" for the main channel) or None for the whole office: the owner's choice,
    else channel:<key> in its note, else new footage in inbox/ (the main channel), else its work folder's channel.txt
    (a folder without one is the main channel's)."""
    ch, note = task.get("channel"), task.get("note") or ""
    if ch == OFFICE:
        return None
    if isinstance(ch, str) and channels.get(ch):
        return ch
    m = re.search(r"(?:^|\s)channel:([a-z0-9-]+)", note)
    if m and channels.get(m[1]):
        return m[1]
    if FOOTAGE.search(note):
        return ""
    m = re.search(r"out:([^\s,;]+)", note)
    if m:
        name = m[1].strip("/").split("/")[0]
        for area in ("out", "approved"):
            d = safe_join(os.path.join(ROOT, area), name)
            if d and os.path.isdir(d):
                try:
                    with open(os.path.join(d, "channel.txt"), encoding="utf-8") as f:
                        key = f.read(200).strip()
                except OSError:
                    key = ""
                return key if channels.get(key) else ""
    return None


PACKAGE_LINES = {
    "video": "Package: video. The owner wants the edit only: no post.md and no cover.",
    "caption": "Package: caption. The owner wants the edit and 3 title + caption sets (post.md); no cover.",
    "full": "Package: full. The owner wants the edit, 3 title + caption sets (post.md), and Codex thumbnails after picking a title.",
}


def edit_prompt(rel, ch, task_id, package="full", videos=0):
    """The lead's instruction for the Edit button: edit-clips for that one video, for its channel and its package."""
    n = channels.name(ch)
    who = (f" Channel: {n} (key {ch}). Same procedures as the main channel: follow \"Brand rules\" and \"Lessons\" as always, read "
           f"\"{n} · Company\" instead of \"Company\" and \"{n} · Brand rules\" on top (its rules win where they differ); never use the "
           f"main channel's name, logo, slogans or hashtags.") if ch else ""
    first = (f" Scripts first: {videos}. The owner wants to see the picked passages before any video is cut: pick {videos} plus 2 spares, "
             f"write out/<name>/scripts.json, move the task to review with scripts:<name> in its note, and stop there.") if videos else ""
    return f'/edit-clips "{rel}"{who} {PACKAGE_LINES.get(package, PACKAGE_LINES["full"])}{first} Board task {task_id} is this video\'s New footage task.'


def approved_dir(folder, areas=("approved",)):
    """approved/<name> → its path, or None. Only approved work can be posted; the overview may also read out/."""
    m = re.match(r"^(approved|out)/([^/]+)(?:/([^/]+))?$", str(folder or ""))         # a clip, or one topic of a long talk
    ok = m and m[1] in areas and SAFE_NAME.match(m[2]) and (not m[3] or SAFE_NAME.match(m[3]))
    d = safe_join(os.path.join(ROOT, m[1]), m[2] + ("/" + m[3] if m[3] else "")) if ok else None
    return d if d and os.path.isdir(d) else None


TT_BACK = {"url": None, "at": 0}


def tiktok_redirect():
    """The https address TikTok returns to after sign-in: this computer's Tailscale name on port 8443 (which serves Agents
    HQ), e.g. https://<computer>.<tailnet>.ts.net:8443/oauth/tiktok. HQ_TIKTOK_REDIRECT overrides it. None without one."""
    if os.environ.get("HQ_TIKTOK_REDIRECT"):
        return os.environ["HQ_TIKTOK_REDIRECT"]
    if TT_BACK["url"] is None or time.time() - TT_BACK["at"] > 600:
        url = ""
        try:
            out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=15,
                                 creationflags=0x08000000 if os.name == "nt" else 0).stdout
            name = (json.loads(out).get("Self") or {}).get("DNSName", "").rstrip(".")
            url = f"https://{name}:8443/oauth/tiktok" if name else ""
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        TT_BACK.update(url=url, at=time.time())
    return TT_BACK["url"] or None


def accounts_action(body, redirect):
    """POST /api/accounts: connect Meta, start the YouTube sign-in, or disconnect, for one channel. Returns (http code, payload)."""
    act, ch = body.get("action"), str(body.get("channel") or "")
    if ch and not channels.get(ch):
        return 404, {"error": "no such channel"}
    try:
        if act == "meta":
            r = accounts.connect_meta(body.get("app_id"), body.get("app_secret"), body.get("token"), body.get("page"), ch)
            return 200, {**r, "accounts": accounts.summary(ch)}
        if act == "youtube":
            return 200, {"url": accounts.youtube_begin(body.get("client_json"), redirect, ch)}
        if act == "tiktok":                              # TikTok only returns to an https address: the Tailscale link
            back = tiktok_redirect()
            if not back:
                return 409, {"error": "TikTok needs an https return address. Turn on phone access (Tailscale) for Agents HQ first, then connect again."}
            return 200, {"url": accounts.tiktok_begin(body.get("client_key"), body.get("client_secret"), back, ch)}
        if act == "disconnect" and body.get("which") in ("meta", "youtube", "tiktok"):
            accounts.disconnect(body["which"], ch)
            return 200, {"accounts": accounts.summary(ch)}
    except publish.PostError as e:
        return 400, {"error": str(e)}
    return 400, {"error": "unknown action"}


CHAT_KEEP = 40                                       # messages kept per task
ASKS = re.compile(r"[?？]|reply ok|your ok|approve|please (confirm|choose|decide)|let me know", re.I)


def add_chat(task, who, text, error=False):
    """One message in a task's chat: the owner's, or the lead's reply about that task."""
    msg = {"from": who, "text": str(text)[:4000], "at": now_iso()}
    if error:
        msg["error"] = True
    task["chat"] = (task.get("chat") or [])[-(CHAT_KEEP - 1):] + [msg]


def after_run(run):
    """The lead's reply lands in the chat of the board task(s) it worked on (up to three; more is office-wide work, like
    a standup). A reply that asks the owner something, or waits for an OK, flags the task: the board puts it under
    Waiting for you with "Lead asks you"."""
    if not run.tasks or len(run.tasks) > 3:
        return
    res = next((e for e in reversed(run.events) if e.get("type") == "result"), None)
    err = next((e for e in reversed(run.events) if e.get("type") == "error"), None)
    if getattr(run, "stopped", False):
        with TASK_LOCK:
            db = load_tasks()
            for t in db["tasks"]:
                if t.get("id") in run.tasks:
                    add_chat(t, "lead", "Stopped by you. What was already made stays in its folder; press Run again to start this task over.")
                    t["asks"], t["updated"] = False, now_iso()
            save_tasks(db)
        return
    text = (res or {}).get("text") or ("The lead stopped before it finished: " + err["text"][-400:] if err else "")
    if not text.strip():
        return
    failed = not res or bool(res.get("is_error"))
    # the reply names the video folder it made (out/<name>/): link the task to it, so the board shows one card per video
    # and approving the video's card also closes this task
    named = next((m for m in re.findall(r"out/([A-Za-z0-9][A-Za-z0-9._()\-]{0,120})/", text)
                  if not m.startswith(("thumbnail-final-", "sermon-studio-")) and os.path.isdir(os.path.join(ROOT, "out", m))), None)
    with TASK_LOCK:
        db = load_tasks()
        for t in db["tasks"]:
            if t.get("id") in run.tasks and named and len(run.tasks) == 1 and not re.search(r"(?:^|\s)out:", t.get("note") or ""):
                t["note"] = ((t.get("note") or "") + " out:" + named).strip()
            if t.get("id") in run.tasks:
                add_chat(t, "lead", text, error=failed)
                t["asks"] = failed or bool(ASKS.search(text[-500:]))
                t["updated"] = now_iso()
        save_tasks(db)


def remove_group(body):
    """One whole card: every task to Deleted, every folder off the board, and (studio) its Codex Studio projects to the
    Studio's Trash. Returns (http code, what was done)."""
    ids = [i for i in (body.get("ids") or []) if isinstance(i, str) and re.match(r"^t\d+$", i)]
    folders = [f for f in (body.get("folders") or []) if isinstance(f, str) and SAFE_NAME.match(f)]
    if not ids and not folders:
        return 400, {"error": "nothing to delete"}
    removed = 0
    for i in ids:
        code, _ = task_action({"action": "remove", "id": i})
        removed += code == 200
    if folders:
        task_action({"action": "folder-hide", "folders": folders})
    trashed, failed = [], []
    if body.get("studio") is True:
        notes = " ".join(t.get("note") or "" for t in (load_tasks().get("deleted") or []) if t.get("id") in ids)
        pids = sorted(set(re.findall(r"sermon-studio-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", notes + " " + " ".join(folders))))
        for pid in pids:
            try:
                code, _, raw = sermon_design._request("GET", f"/api/sermon-design/projects/{pid}")
                proj = (json.loads(raw or b"{}") or {}).get("project") or {}
                if code == 404 or proj.get("deletedAt"):
                    continue                                 # gone already or in Trash already
                # clean: the Studio's own cleanup, which removes only the pictures it generated (uploads are kept) to free space
                act = {"management": {"action": "trash-clean-generated" if body.get("clean") is True else "trash"}, "expectedRevision": proj.get("revision")}
                code, _, raw = sermon_design._request("POST", f"/api/sermon-design/projects/{pid}", json.dumps(act).encode(), {"Content-Type": "application/json"})
                (trashed if code < 300 else failed).append(pid)
            except Exception as e:                           # the Studio is off: the board part still happened
                sys.stderr.write(f"studio trash {pid}: {e}\n")
                failed.append(pid)
    return 200, {"removed": removed, "folders": len(folders), "studioTrashed": len(trashed), "studioFailed": len(failed), "cleaned": body.get("clean") is True}


def task_action(body):
    """Use the same bridge→task lock order as thumbnail delivery callbacks."""
    if body.get("action") == "remove-group":
        return remove_group(body)
    bridge = globals().get("thumbnail_design")
    if bridge:
        with bridge.lock:
            return _task_action(body)
    return _task_action(body)


def _task_action(body):
    """POST /api/tasks: add, move, remove, approve, progress. Returns (http code, payload)."""
    action = body.get("action")
    with TASK_LOCK:
        db = load_tasks()
        task = next((t for t in db["tasks"] if t.get("id") == body.get("id")), None)
        if action == "add" and isinstance(body.get("title"), str) and body["title"].strip():
            every = db["tasks"] + db.get("deleted", [])  # a deleted task keeps its id, so Restore never clashes
            nid = "t" + str(max([0] + [int(t["id"][1:]) for t in every if str(t.get("id", "t"))[1:].isdigit()]) + 1)
            new = {"id": nid, "title": body["title"].strip()[:200], "team": str(body.get("team") or "")[:40], "agent": str(body.get("agent") or "")[:60],
                   "status": body.get("status") if body.get("status") in STATUSES else "todo", "kind": body.get("kind") if body.get("kind") in KINDS else "task",
                   "note": str(body.get("note") or "")[:500], "subtitle": str(body.get("subtitle") or "")[:200], "progress": clean_progress(body.get("progress")),
                   "date": clean_date(body.get("date")), "time": clean_time(body.get("time")), "created": now_iso(), "updated": now_iso(),
                   "done_at": now_iso() if body.get("status") == "done" else None}
            ch = body.get("channel")
            if ch == OFFICE or (isinstance(ch, str) and channels.get(ch)):
                new["channel"] = ch
            db["tasks"].append(normalize_task(new)); save_tasks(db)
            return 201, {"added": new}
        if action == "move" and task and body.get("status") in STATUSES:
            if body.get("status") == "done":
                match = re.search(r"out:([^\s,;]+)", task.get("note") or "")
                if match and "thumbnail_design" in globals():
                    reason = thumbnail_design.guard_approval(match[1])
                    if reason or match[1].startswith("thumbnail-final-"):
                        return 409, {"error": reason or "Use the final approval control for this thumbnail package."}
            set_status(task, body["status"]); save_tasks(db)
            return 200, {"moved": task}
        if action == "remove":                      # into the Deleted tab (Restore brings it back); its files stay where they are
            if not task:
                return 404, {"error": "no such task"}
            db["tasks"].remove(task)
            db.setdefault("deleted", []).append({**task, "deleted_at": now_iso()}); save_tasks(db)
            return 200, {"removed": 1, "task": task}
        if action == "restore":                     # out of the Deleted tab, back on the board as it was
            gone = next((t for t in db.get("deleted", []) if t.get("id") == body.get("id")), None)
            if not gone:
                return 404, {"error": "that task is not in Deleted"}
            match = re.search(r"out:([^\s,;]+)", gone.get("note") or "")
            studio = globals().get("sermon_design")
            if gone.get("studioPermanentlyDeleted") or (studio and match and studio.delivery_permanently_deleted(match[1])):
                return 409, {"error": "This Studio project and its delivery were permanently deleted. Create a new project instead."}
            db["deleted"].remove(gone); gone.pop("deleted_at", None)
            db["tasks"].append(normalize_task(gone)); save_tasks(db)
            return 200, {"restored": gone}
        if action == "reedit":                      # a finished task goes back to work: a copy of its approved folder becomes
            if not task:                            # out/<name>-v2 (approved/ stays as it was, it may be posted already)
                return 404, {"error": "no such task"}
            m = re.search(r"out:([^\s,;]+)", task.get("note") or "")
            name = m[1].strip("/").split("/")[0] if m else ""
            src = safe_join(os.path.join(ROOT, "approved"), name) if name and SAFE_NAME.match(name) else None
            if not src or not os.path.isdir(src):
                return 409, {"error": "this task has no approved folder to start from"}
            if name.startswith("thumbnail-final-"):
                return 409, {"error": "a thumbnail package is re-made in Thumbnail Studio"}
            base, n = re.sub(r"-v\d+$", "", name), 2
            while any(os.path.exists(os.path.join(ROOT, area, f"{base}-v{n}")) for area in ("out", "approved")):
                n += 1
            new = f"{base}-v{n}"
            shutil.copytree(src, os.path.join(ROOT, "out", new))
            task["note"] = (task.get("note") or "").replace("out:" + m[1], "out:" + new, 1)
            set_status(task, "doing"); task["subtitle"] = "Re-edit · waiting for the team"; save_tasks(db)
            return 200, {"reedit": task, "from": "approved/" + name, "folder": "out/" + new}
        if action in ("folder-hide", "folder-show", "folder-channel"):
            # finished out/ folders without a task (one, or every version of one project): the owner files them under a
            # channel (their channel.txt, which the posting screen reads) or moves them to the Deleted tab; files stay in out/
            names = body.get("folders") if isinstance(body.get("folders"), list) else [body.get("folder")]
            names = [str(n or "").strip("/") for n in names][:50]
            dirs = [safe_join(os.path.join(ROOT, "out"), n) if SAFE_NAME.match(n) else None for n in names]
            hidden = db.setdefault("hidden_out", [])
            if not names:
                return 400, {"error": "no folder"}
            if action == "folder-show":
                db["hidden_out"] = [h for h in hidden if (h["name"] if isinstance(h, dict) else h) not in names]; save_tasks(db)
                return 200, {"shown": names}
            if not all(d and os.path.isdir(d) for d in dirs):
                return 404, {"error": "no such folder in out/"}
            if action == "folder-hide":
                have = {h["name"] if isinstance(h, dict) else h for h in hidden}
                hidden += [{"name": n, "deleted_at": now_iso()} for n in names if n not in have]; save_tasks(db)
                return 200, {"hidden": names}
            ch = body.get("channel")
            if not isinstance(ch, str) or not channels.get(ch):
                return 400, {"error": "choose an existing channel"}
            if any(n.startswith("thumbnail-final-") for n in names):
                return 409, {"error": "a thumbnail package keeps the channel it was made for"}
            for d in dirs:
                with open(os.path.join(d, "channel.txt"), "w", encoding="utf-8") as f:
                    f.write(ch)
            return 200, {"folders": names, "channel": ch}
        if action == "team":                        # a task moves to another department (e.g. the Studios' tasks to Design)
            if not task:
                return 404, {"error": "no such task"}
            name = str(body.get("team") or "")
            if name not in {t["name"] for t in teams_payload()}:
                return 400, {"error": "choose an existing team"}
            task["team"], task["updated"] = name, now_iso(); save_tasks(db)
            return 200, {"team": task}
        if action == "channel":                     # the owner files a task under a channel (None: worked out again)
            if not task:
                return 404, {"error": "no such task"}
            ch = body.get("channel")
            if ch is not None and ch != OFFICE and not (isinstance(ch, str) and channels.get(ch)):
                return 400, {"error": "choose an existing channel"}
            task["channel"], task["updated"] = ch, now_iso(); save_tasks(db)
            return 200, {"channel": task}
        if action == "approve":
            if not task:
                return 404, {"error": "no such task"}
            moved, warning = None, None
            m = re.search(r"out:([^\s,;]+)", task.get("note") or "")
            if m:                                   # the task waits on a work folder: approve that too
                name = m[1].strip("/")
                if name.startswith("thumbnail-final-") and task.get("status") == "done" and os.path.isdir(os.path.join(ROOT, "approved", name)):
                    return 200, {"approved": task, "moved": name, "alreadyApproved": True}
                code, res = approve_folder(name)
                if res.get("thumbnailWorkflow") or (name.startswith("thumbnail-final-") and code != 200):
                    return code, res
                if code in (200, 409):
                    moved = name
                else:
                    warning = f"{res['error']}: out/{name}"
            set_status(task, "done")
            if moved and moved.startswith("thumbnail-final-"):
                thumbnail_design.complete_source(task, db, set_status)
            save_tasks(db)
            out = {"approved": task, "moved": moved}
            if warning:
                out["warning"] = warning
            return 200, out
        if action == "edit":                        # the owner's Edit button on a "New footage" task
            got = task_footage(task) if task else None
            if not got:
                return 404, {"error": "that video is no longer waiting in the inbox"}
            task["package"] = body.get("package") if body.get("package") in ("video", "caption", "full") else "full"
            videos = body.get("videos") if isinstance(body.get("videos"), int) and 1 <= body["videos"] <= 8 else 0   # scripts first: how many
            run = desk.start(edit_prompt(*got, task["id"], task["package"], videos), tasks=[task["id"]])
            set_status(task, "doing"); save_tasks(db)
            return 202, {"editing": task, "run": run.summary()}
        if action in ("run", "say"):                # Run / Run again, or the owner's message in the task's chat
            if not task:
                return 404, {"error": "no such task"}
            text = str(body.get("text") or "").strip()[:2000]
            if action == "say" and not text:
                return 400, {"error": "empty message"}
            ch = task_channel(task)
            head = (f"board task {task['id']} ({task['title']}; team {task.get('team') or 'auto'}"
                    f"{'; channel ' + channels.name(ch) if ch is not None else ''}; note: {task.get('note') or 'none'})")
            keep = (f"Keep the board task moving: node hq/tasks.js move {task['id']} doing while it is worked on, review when it "
                    f"waits for the owner. If you need the owner's decision, end your reply with one clear question.")
            if action == "say":
                add_chat(task, "owner", text); task["asks"] = False
                prompt = f"The owner writes about {head}: {text} / Reply to the owner in a few short lines; if it needs work, route it to the right team. {keep}"
            else:
                again = "This task was started before and stopped before it was finished: check what is already done, then finish it. " if task["status"] == "doing" else ""
                prompt = f"/brief {task['title']} ({head}). {again}{keep}"
                set_status(task, "doing"); task["subtitle"], task["asks"] = "", False
            run = desk.start(prompt, tasks=[task["id"]])
            save_tasks(db)
            return 202, {"run": run.summary(), "task": task}
        if action == "progress":
            if not task:
                return 404, {"error": "no such task"}
            if "progress" in body:
                p = clean_progress(body["progress"])
                if p is None and body["progress"] not in (None, ""):
                    return 400, {"error": "progress must be a number from 0 to 100"}
                task["progress"] = p
            if "subtitle" in body:
                task["subtitle"] = str(body.get("subtitle") or "")[:200]
            task["updated"] = now_iso(); save_tasks(db)
            return 200, {"progress": task}
    return 400, {"error": "action: add (title, team, kind?, date?, time?, subtitle?, channel?), move (id, status), remove (id), channel (id, channel), approve (id) or progress (id, progress, subtitle)"}


def calendar_payload(month):
    """Tasks with a date in the month, by day."""
    month = month or datetime.date.today().strftime("%Y-%m")
    if not MONTH_RE.match(month):
        return None
    days = {}
    for t in load_tasks()["tasks"]:
        if isinstance(t.get("date"), str) and t["date"].startswith(month + "-") and t["status"] != "cancelled":
            days.setdefault(t["date"], []).append(t)
    for rows in days.values():
        rows.sort(key=lambda t: (t.get("time") is None, t.get("time") or "", t.get("created") or ""))
    return {"month": month, "days": dict(sorted(days.items()))}


BRAIN_ENTITIES = ("Company", "Brand rules", "Lessons", "Ideas")


def brain_payload():
    """GET /api/brain: the four contract entities, each [] until brain/memory.jsonl has it, plus any other entity found."""
    brain = {name: [] for name in BRAIN_ENTITIES}
    brain.update(brain_entities())
    return brain


LESSON_TAG = re.compile(r"^\[\s*(?:from\s+)?([^\]·|>→]+?)\s*(?:(?:·|\||→|->|>)\s*(?:for\s+)?([^\]]+?))?\s*\]\s*(.+)$", re.I)


def parse_lesson(text):
    """'[Creative · for Scripts, Social] Hooks under 8 words kept viewers longer' -> team, for_teams, text.
    Untagged lessons belong to the whole office."""
    m = LESSON_TAG.match(str(text).strip())
    if not m:
        return {"team": "", "for": [], "text": str(text).strip()}
    others = [t.strip() for t in re.split(r"[,&/]| and ", m.group(2) or "") if t.strip()]
    return {"team": m.group(1).strip(), "for": others, "text": m.group(3).strip()}


def chatter_payload():
    """GET /api/chatter: what the office talks about over coffee, all from real data. Lessons (with the team they came
    from and the teams they help), ideas, brand rules and today's finished work. The office turns these into the
    speech bubbles of agents who visit each other; an empty brain gives friendly small talk only."""
    brain, tasks = brain_entities(), load_tasks()["tasks"]
    keys = {t["name"].lower(): t["key"] for t in teams_payload()}
    key = lambda name: keys.get((name or "").lower(), "")
    topics = []
    for raw in brain.get("Lessons", [])[-40:]:
        l = parse_lesson(raw)
        topics.append({"kind": "lesson", "team": l["team"], "teamKey": key(l["team"]), "for": l["for"],
                       "forKeys": [key(t) for t in l["for"] if key(t)], "text": l["text"]})
    for raw in brain.get("Ideas", [])[-15:]:
        topics.append({"kind": "idea", "team": "", "teamKey": "", "for": [], "forKeys": [], "text": str(raw)})
    for raw in brain.get("Brand rules", [])[-12:]:
        topics.append({"kind": "rule", "team": "", "teamKey": "", "for": [], "forKeys": [], "text": str(raw)})
    for t in tasks:
        if t.get("status") == "done" and is_today(t.get("done_at")):
            topics.append({"kind": "done", "team": t.get("team", ""), "teamKey": key(t.get("team")), "for": [], "forKeys": [], "text": t.get("title", "")})
    return {"topics": topics, "lessons": sum(1 for x in topics if x["kind"] == "lesson")}


def ensure_coffee_chat(today=None):
    """Every Monday the board gets a "Coffee chat" meeting (the weekly cross-team review, /coffee-chat), once per week.
    Set HQ_COFFEE_CHAT=0 to stop it."""
    if os.environ.get("HQ_COFFEE_CHAT", "1") in ("0", "false"):
        return
    today = today or datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    with TASK_LOCK:
        db = load_tasks()
        for t in db["tasks"]:
            if t.get("title") == "Coffee chat" and (t.get("date") or "") >= monday.isoformat():
                return
        nid = "t" + str(max([0] + [int(t["id"][1:]) for t in db["tasks"] if str(t.get("id", "t"))[1:].isdigit()]) + 1)
        db["tasks"].append(normalize_task({"id": nid, "title": "Coffee chat", "team": "The Brain", "agent": "", "status": "todo", "kind": "meeting",
                                           "note": "Weekly cross-team review of lessons. Press Run, or type /coffee-chat.",
                                           "subtitle": "every team head · share what worked", "progress": None,
                                           "date": monday.isoformat(), "time": "10:00", "created": now_iso(), "updated": now_iso(), "done_at": None}))
        save_tasks(db)


WORK_KIND = {".mp4": "video", ".mov": "video", ".m4v": "video", ".webm": "video", ".mkv": "video",
             ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".gif": "image",
             ".md": "text", ".txt": "text", ".srt": "text", ".ass": "text", ".json": "text", ".csv": "text", ".vtt": "text"}


def work_payload(folder):
    """GET /api/work?folder=out/<name> (or approved/<name>): every file in a finished work folder, so the review screen
    can show videos, images and texts in the app instead of opening raw links. Small text files come with their content."""
    m = re.match(r"^(out|approved)/([^/]+)$", folder or "")
    base = safe_join(os.path.join(ROOT, m[1]), m[2]) if m else None
    if not base or not os.path.isdir(base):
        return None
    files = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if os.path.relpath(dirpath, base).count(os.sep) >= 2:
            continue
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            ext = os.path.splitext(fn)[1].lower()
            item = {"name": fn, "path": rel, "url": f"/files/{m[1]}/{m[2]}/{rel}", "kind": WORK_KIND.get(ext, "other"),
                    "size": os.path.getsize(full), "mtime": int(os.path.getmtime(full))}
            if item["kind"] == "text" and item["size"] <= 96 * 1024:
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        item["text"] = f.read()
                except OSError:
                    pass
            files.append(item)
    return {"folder": folder, "area": m[1], "name": m[2], "files": files}


def task_final(task):
    """True when the work folder a task names (out:<name>, approved/ once approved) has a video, a thumbnail and a caption."""
    m = re.search(r"out:([^\s,;]+)", task.get("note") or "")
    if not m:
        return False
    name = m.group(1).strip("/")
    for area in ("out", "approved"):
        d = safe_join(os.path.join(ROOT, area), name)
        if d and os.path.isdir(d):
            try:
                f = publish.media_files(d)
                caps = publish.drafts(d)["options"]
                return bool(f["video"] and f["image"] and os.path.isfile(os.path.join(d, "post.md")) and any((o.get("caption") or "").strip() for o in caps))
            except OSError:
                return False
    return False


def status_payload():
    ensure_coffee_chat()
    s = collect()
    db = load_tasks()
    ag, running, tasks = agents()["agents"], events()["running"], db["tasks"]
    hidden = {h["name"]: h.get("deleted_at") for h in (db.get("hidden_out") or []) if isinstance(h, dict)}
    hidden.update({h: None for h in (db.get("hidden_out") or []) if isinstance(h, str)})
    for name, info in s["out"].items():                   # each finished folder: its channel, and whether the owner deleted it from the board
        if "edit" in info:
            info["ch"] = channels_mod.folder_channel(os.path.join(ROOT, "out", name))
            info["hidden"] = name in hidden
            if name in hidden:
                info["deleted_at"] = hidden[name]
            if not name.startswith(("thumbnail-final-", "sermon-studio-")):
                try:
                    info["pkg"] = packages.state(name)                 # its steps and what the owner picked: the board's card
                except Exception as e:
                    sys.stderr.write(f"package of {name}: {e}\n")
    s["deleted"] = sorted(db.get("deleted") or [], key=lambda t: t.get("deleted_at") or "", reverse=True)
    for t in s["deleted"]:
        t["ch"] = task_channel(t)
    s["waiting_for_approval"] = [n for n in s["waiting_for_approval"] if n not in hidden]
    live = desk.working_on()
    try:
        thumb_jobs = thumbnail_design._load()["jobs"]
    except Exception:
        thumb_jobs = {}
    posted_cache = {}
    for t in tasks:                                        # Final: the video, the thumbnail and the caption are all there
        t["live"] = live.get(t["id"])                       # the lead is on it right now ("working"), or it waits in line ("queued")
        t["video"] = task_video(t, thumb_jobs)              # the video it belongs to: the board groups a project's tasks by it
        if t["video"] and t["status"] == "done":
            if t["video"] not in posted_cache:
                sched = {}
                posted_cache[t["video"]] = (posted_platforms(t["video"], sched), sched or None)
            t["posted"], t["scheduled"] = posted_cache[t["video"]]   # out already: purple; waiting for its time: SCHEDULED
        t["final"] = task_final(t)
        t["footage"] = bool(task_footage(t))                # New footage that waits for the Edit button
        t["scripts"] = scripts.for_task(t)                  # the picked passages the owner approves before any video is cut
        t["ch"] = task_channel(t)                           # its channel (key, "" main) or None: the whole office
    s["channels"] = [{"key": c["key"], "name": c.get("name") or ("Main channel" if c["main"] else c["key"])} for c in channels.payload()["channels"]]
    for c in s["channels"][1:]:                             # a channel's clips wait in inbox/<key>/
        s["inbox"]["clips"] += [c["key"] + "/" + n for n in files(channels.inbox(c["key"]), CLIP_EXT)]
    s["desk"], s["auth"], s["running"], s["tasks"] = desk.state(), bool(PASSWORD), running, tasks
    s["update"] = dict(UPDATE)
    s["staff_jobs"] = desk.staff_jobs()                     # what each sub-agent is really doing: the cards are named after it
    s["office_name"] = office_name()
    s["studios"] = sermon_design.engine_root.is_dir()      # the design studios run on AI OFFICE: hidden on a computer without it
    s["boot"] = BOOT                                        # changes on every start: open windows reload to the new app
    s["brain_notes"] = sum(s.get("brain", {}).values())
    s["counts"] = {"agents": len(ag), "running": sum(running.values()),
                   "tasks_running": sum(1 for t in tasks if t["status"] == "doing"),
                   "tasks_waiting": sum(1 for t in tasks if t["status"] == "review"),
                   "tasks_done_today": sum(1 for t in tasks if t["status"] == "done" and is_today(t.get("done_at")))}
    return s


class Notifier:
    """The bell: an append-only list for the server's lifetime, derived from the hook feed and board changes.
    Seeded on the first call from the last 50 hook events and the board; the HUD polls with after=total."""
    GAP_MS = 10_000

    def __init__(self):
        self.items, self.lock, self.seeded = [], threading.Lock(), False
        self.offset, self.last_ts = 0, 0        # how far into events.jsonl we have read, and the newest ts seen
        self.bursts = {}                         # team -> {"last": ts, "agents": [names]} of starts not yet reported
        self.board = {}                          # task id -> (status, kind, date, time) last seen
        self.asked = {}                          # task id -> the lead was waiting on the owner's answer, last seen

    def _item(self, fresh, team, body, kind, ts, **extra):
        team = team or "Office"
        fresh.append({"id": 0, "ts": ts, "team": team, "teamKey": team_key(team), "title": team, "body": body, "kind": kind,
                      "text": f"{team} · {body}", **extra})

    def _close(self, team, burst, fresh):
        if len(burst["agents"]) >= 2:
            self._item(fresh, team, f"{len(burst['agents'])} sub-agents started", "started", burst["last"], agents=burst["agents"])

    def refresh(self):
        with self.lock:
            fresh, now = [], int(time.time() * 1000)
            # the hook feed: bursts of starts in one team
            team_of = {a["name"]: a["team"] for a in agents()["agents"]}
            feed = events()
            lines = feed["events"]
            if not self.seeded:
                new = lines[-50:]
            elif feed["total"] >= self.offset:
                new = lines[self.offset:]
            else:                                # the hook trimmed the file: keep what is newer than what we saw
                new = [e for e in lines if e.get("ts", 0) > self.last_ts]
            self.offset = feed["total"]
            for e in new:
                ts = e.get("ts", 0) or now
                self.last_ts = max(self.last_ts, ts)
                team = team_of.get(e.get("agent")) if e.get("event") == "start" else None
                if not team:
                    continue
                b = self.bursts.get(team)
                if b and ts - b["last"] <= self.GAP_MS:
                    b["last"] = ts; b["agents"].append(e.get("agent"))
                else:
                    if b:
                        self._close(team, b, fresh)
                    self.bursts[team] = {"last": ts, "agents": [e.get("agent")]}
            for team, b in list(self.bursts.items()):
                if now - b["last"] > self.GAP_MS:
                    self._close(team, b, fresh); del self.bursts[team]
            # the board
            today, seen, phone = datetime.date.today().isoformat(), set(), []     # phone: what also goes to the owner's phone
            seeded = self.seeded
            for t in load_tasks()["tasks"]:
                tid = t.get("id"); seen.add(tid)
                cur, prev = (t["status"], t["kind"], t.get("date"), t.get("time")), self.board.get(tid)
                self.board[tid] = cur
                team, title = t.get("team") or "Office", t.get("title", "")
                when = t["time"] or t["date"]
                if not self.seeded:                  # what is still worth a bell when the server starts
                    self.asked[tid] = bool(t.get("asks"))
                    if cur[0] == "review":
                        self._item(fresh, team, f"{title} ready for your OK", "waiting", iso_ms(t.get("updated")), task=tid)
                    elif cur[0] == "done" and is_today(t.get("done_at")):
                        self._item(fresh, team, f"{title} done", "done", iso_ms(t.get("done_at")), task=tid)
                    if cur[1] in SCHEDULED_KINDS and cur[2] and cur[2] >= today and cur[0] != "cancelled":
                        self._item(fresh, team, f"{title} scheduled · {when}", "scheduled", iso_ms(t.get("updated")), task=tid)
                    continue
                asks, was = bool(t.get("asks")) and cur[0] in ("todo", "doing", "review"), self.asked.get(tid)
                self.asked[tid] = asks
                if asks and not was:
                    last = next((m.get("text") for m in reversed(t.get("chat") or []) if m.get("from") == "lead"), "")
                    phone.append(("Lead asks you · " + title[:60], re.sub(r"\s+", " ", last or "Open the task to answer.")[:200], tid))
                if prev is None or prev[0] != cur[0]:
                    if cur[0] == "review":
                        self._item(fresh, team, f"{title} ready for your OK", "waiting", iso_ms(t.get("updated")), task=tid)
                        if not asks:
                            phone.append(("Ready for your OK", f"{title} · {team}", tid))
                    elif cur[0] == "done":
                        self._item(fresh, team, f"{title} done", "done", iso_ms(t.get("done_at") or t.get("updated")), task=tid)
                if (prev is None or prev[1:] != cur[1:]) and cur[1] in SCHEDULED_KINDS and cur[2] and cur[0] != "cancelled":
                    self._item(fresh, team, f"{title} scheduled · {when}", "scheduled", iso_ms(t.get("updated")), task=tid)
            for tid in [k for k in self.board if k not in seen]:
                del self.board[tid]
            if not self.seeded:
                fresh.sort(key=lambda i: i["ts"]); self.seeded = True
            for i in fresh:
                i["id"] = len(self.items) + 1; self.items.append(i)
            total = len(self.items)
        if seeded:                                   # never a burst of old news when HQ starts
            for title, body, tid in phone:
                push.send_later(title, body, f"/?task={tid}", f"task-{tid}")
        return total

    def payload(self, after=0):
        total = self.refresh()
        with self.lock:
            return {"items": self.items[after:], "offset": after, "total": total}


push = webpush.Push(ROOT)
notifier = Notifier()


OFFICE_FILE = os.path.join(ROOT, ".hq-office.json")
_OFFICE = {"mtime": None, "data": {}}


def office_conf():
    """This office's own settings, written by the desktop app's setup and never uploaded: its name ("Acme HQ") and, for
    a client edition, the access code it updates with. Read again whenever the file changes."""
    try:
        mtime = os.path.getmtime(OFFICE_FILE)
    except OSError:
        return {}
    if mtime != _OFFICE["mtime"]:
        try:
            with open(OFFICE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        _OFFICE.update(mtime=mtime, data=data if isinstance(data, dict) else {})
    return _OFFICE["data"]


def office_name():
    """The name on the office's pages and the phone app: the client's own ("Acme HQ"), or Agents HQ."""
    name = re.sub(r'[\x00-\x1f<>"&\\]', "", str(os.environ.get("HQ_OFFICE_NAME") or office_conf().get("name") or "")).strip()[:40]
    return name or "Agents HQ"


def named(data, ctype):
    """A page or the phone app's description with this office's name in place of "Agents HQ"."""
    name = office_name()
    if name == "Agents HQ" or not ctype.startswith(("text/html", "application/manifest")):
        return data
    safe = html.escape(name) if ctype.startswith("text/html") else json.dumps(name)[1:-1]
    return data.replace(b"Agents HQ", safe.encode("utf-8"))


UPDATE = {"ok": None, "version": "", "from": "", "message": "not checked", "at": 0}
USER_DATA = ("brain/memory.jsonl",)          # the owner's own data inside tracked files: never lost in an update


def git(*args, timeout=60):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")     # never sit waiting for a password nobody sees
    ssh = git_ssh()
    if ssh:
        env["GIT_SSH_COMMAND"] = ssh
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)


REPO_URL = os.environ.get("HQ_REPO_URL", "https://github.com/johnooi5593-hue/Agents-HQ")
REPO_BRANCH = os.environ.get("HQ_REPO_BRANCH", "main")
ACCESS_KEY = os.path.join(ROOT, ".hq-access-key")
ACCESS_PREFIX = "HQ1."


def access_key_text(code):
    """The private key inside an access code ("HQ1." + base64url of a read-only deploy key), or "" for anything else."""
    code = re.sub(r"\s+", "", str(code or ""))
    if not code.startswith(ACCESS_PREFIX):
        return ""
    try:
        text = base64.urlsafe_b64decode(code[len(ACCESS_PREFIX):] + "=" * (-len(code) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return ""
    return text if text.startswith("-----BEGIN OPENSSH PRIVATE KEY-----") else ""


def git_ssh():
    """How git reaches an SSH remote: a client edition updates from a private GitHub repo with the read-only key in its
    access code (from setup, kept in .hq-access-key). Never interactive: no key or a refused key fails at once."""
    if not REPO_URL.startswith("git@"):
        return ""
    q = lambda p: '"' + p.replace(os.sep, "/") + '"'
    cmd = f"ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={q(os.path.join(ROOT, '.hq-known-hosts'))}"
    key = access_key_text(office_conf().get("access"))
    if not key:
        return cmd
    try:
        with open(ACCESS_KEY, encoding="ascii") as f:
            same = f.read() == key
    except OSError:
        same = False
    if not same:
        with open(ACCESS_KEY, "w", encoding="ascii", newline="\n") as f:
            f.write(key)
    return cmd + f" -o IdentitiesOnly=yes -i {q(ACCESS_KEY)}"


def adopt_folder(now):
    """An office copied from the app (no Git history) is turned into a normal Git checkout of GitHub, in place, so it
    can update like any other. Files that differ from GitHub are backed up to .hq-backup/ first; the brain is merged,
    never replaced; files GitHub doesn't know (inbox, out, approved, work, the board) are left alone. True when done."""
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        if git("init", "--quiet").returncode != 0:
            return False
    if git("rev-parse", "--verify", "--quiet", "HEAD").returncode == 0:
        return True                                           # already has history: the normal update handles it
    if git("remote", "get-url", "origin").returncode != 0:
        git("remote", "add", "origin", REPO_URL)
    f = git("fetch", "--quiet", "origin", REPO_BRANCH, timeout=300)
    if f.returncode != 0:
        UPDATE.update(ok=False, message="couldn't download from GitHub: " + (f.stderr.strip().splitlines() or ["fetch failed"])[-1], at=now)
        return False
    git("symbolic-ref", "HEAD", "refs/heads/" + REPO_BRANCH)
    git("reset", "--quiet", "origin/" + REPO_BRANCH)          # history and index from GitHub, the files on disk untouched
    git("branch", "--quiet", "--set-upstream-to=origin/" + REPO_BRANCH)
    changed = [l for l in git("diff", "--name-only").stdout.splitlines() if l.strip()]
    backup = os.path.join(ROOT, ".hq-backup", time.strftime("%Y%m%d-%H%M%S") + "-before-git")
    saved = {}
    for rel in changed:
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
            shutil.copy2(src, os.path.join(backup, rel))
            if rel in USER_DATA:
                with open(src, encoding="utf-8", errors="replace") as fh:
                    saved[rel] = fh.read()
    git("checkout", "--", ".")                                # every file GitHub has, at its newest version
    for rel, text in saved.items():
        path = os.path.join(ROOT, rel)
        with open(path, encoding="utf-8", errors="replace") as fh:
            upstream = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(merge_brain(text, upstream))
    after = git("rev-parse", "--short", "HEAD").stdout.strip()
    UPDATE.update(ok=True, version=after, **{"from": "copy"}, message=f"connected to GitHub and updated to {after}", at=now)
    print(f"Agents HQ: this folder is now linked to GitHub ({after}); {len(changed)} older files backed up in .hq-backup")
    return True


def merge_brain(mine, theirs):
    """Union of two memory.jsonl files: every entity, every observation from both, the owner's order first."""
    def parse(text):
        rows = []
        for line in (text or "").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows
    out, index = [], {}
    for row in parse(mine) + parse(theirs):
        if row.get("type") == "entity":
            key = ("entity", row.get("name"))
            if key in index:
                obs = index[key]["observations"]
                for o in row.get("observations", []):
                    if o not in obs:
                        obs.append(o)
                continue
            row = dict(row, observations=list(row.get("observations", [])))
            index[key] = row
        else:
            key = ("other", json.dumps(row, sort_keys=True))
            if key in index:
                continue
            index[key] = row
        out.append(row)
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out)


def local_edits():
    """Tracked files changed on this computer and not committed, other than the brain (which an update merges). Work in
    progress, by the owner or another tool: an update never sets it aside, it waits until the work is committed."""
    out = git("status", "--porcelain", "--untracked-files=no").stdout
    return [l[3:].strip().strip('"') for l in out.splitlines() if l.strip() and l[3:].strip().strip('"') not in USER_DATA]


def auto_update():
    """Pull the newest Agents HQ from GitHub before starting, so the app keeps itself up to date.
    Robust to the owner's own changes: files the office edits locally (the brain) are backed up, the update is applied,
    and the two brains are merged so no rule or lesson is lost. Local commits are merged, never thrown away. The result
    is kept in UPDATE and shown in the app (user menu, and a warning when an update could not be applied)."""
    now = int(time.time())
    if os.environ.get("HQ_UPDATE_NOTE"):                  # restarted into the version just pulled: keep that result
        try:
            UPDATE.update(json.loads(os.environ.pop("HQ_UPDATE_NOTE")), changed=False)
            return
        except ValueError:
            pass
    if os.environ.get("HQ_NO_UPDATE"):
        try:
            UPDATE["version"] = git("rev-parse", "--short", "HEAD", timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        UPDATE.update(ok=None, message="updates off", at=now)
        return
    try:
        if not adopt_folder(now):
            if UPDATE["ok"] is not False:
                UPDATE.update(ok=False, message="this folder isn't linked to GitHub and Git couldn't link it", at=now)
            print("update check skipped:", UPDATE["message"]); return
        if UPDATE.get("from") == "copy":
            UPDATE["changed"] = True
            return
        before = git("rev-parse", "--short", "HEAD").stdout.strip()
        UPDATE.update(version=before, **{"from": before})
        f = git("fetch", "--quiet")
        if f.returncode != 0:
            UPDATE.update(ok=False, message="no internet or GitHub refused: " + (f.stderr.strip().splitlines() or ["fetch failed"])[-1], at=now)
            print("update check skipped:", UPDATE["message"]); return
        if git("rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
            UPDATE.update(ok=False, message="this folder has no upstream branch to update from", at=now)
            print("update check skipped:", UPDATE["message"]); return
        if git("merge-base", "--is-ancestor", "@{u}", "HEAD").returncode == 0:
            UPDATE.update(ok=True, message="up to date", at=now); print(f"Agents HQ is up to date ({before})"); return
        edits = local_edits()
        if edits:                                           # unfinished work in tracked files: leave it exactly as it is
            UPDATE.update(ok=False, message=f"update waiting: {len(edits)} file(s) changed on this computer and not committed ("
                          + ", ".join(edits[:4]) + (", …" if len(edits) > 4 else "") + "). Commit them, then restart Agents HQ.", at=now)
            print("update not applied:", UPDATE["message"]); return
        # only the brain changed here: back it up, set it aside, update, then merge it back
        dirty = [l[3:].strip().strip('"') for l in git("status", "--porcelain", "--untracked-files=no").stdout.splitlines() if l.strip()]
        saved = {}
        if dirty:
            backup = os.path.join(ROOT, ".hq-backup", time.strftime("%Y%m%d-%H%M%S"))
            for rel in dirty:
                src = os.path.join(ROOT, rel)
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
                    shutil.copy2(src, os.path.join(backup, rel))
                    with open(src, encoding="utf-8", errors="replace") as fh:
                        saved[rel] = fh.read()
            git("stash", "push", "--quiet", "-m", "agents-hq auto-update")
        m = git("merge", "--ff-only", "--quiet", "@{u}")
        if m.returncode != 0:                                  # the office committed on this computer too: merge, don't drop
            m = git("-c", "user.name=Agents HQ", "-c", "user.email=agents-hq@localhost", "merge", "--no-edit", "--quiet", "@{u}")
            if m.returncode != 0:
                git("merge", "--abort")
        merged_ok = m.returncode == 0
        if dirty:
            pop = git("stash", "pop", "--quiet")
            if pop.returncode != 0:                            # both sides changed a file: keep the update, restore the owner's data
                git("reset", "--quiet")                         # clear the half-merged state, then take the update's files
                git("checkout", "--", ".")
                for rel, text in saved.items():
                    path = os.path.join(ROOT, rel)
                    if rel in USER_DATA:
                        with open(path, encoding="utf-8", errors="replace") as fh:
                            upstream = fh.read()
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(merge_brain(text, upstream))
                if all(rel in USER_DATA for rel in saved):      # anything else stays in the stash and in .hq-backup
                    git("stash", "drop", "--quiet")
        after = git("rev-parse", "--short", "HEAD").stdout.strip()
        if merged_ok:
            UPDATE.update(ok=True, version=after, message=f"updated {before} -> {after}", at=now, changed=before != after)
            print(f"Agents HQ updated {before} -> {after}" + (f" (your local changes kept; backup in .hq-backup)" if dirty else ""))
        else:
            UPDATE.update(ok=False, version=after, message="the update conflicts with changes made on this computer: " + ((m.stderr or m.stdout).strip().splitlines() or ["merge failed"])[-1], at=now)
            print("update not applied:", UPDATE["message"])
    except (OSError, subprocess.SubprocessError) as e:
        UPDATE.update(ok=False, message=f"update check failed: {e}", at=now)
        print("update check skipped:", e)


def allow_list():
    """The allow entries of .claude/settings.json, passed to claude -p so the app works before the folder is trusted."""
    try:
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            return list(json.load(f).get("permissions", {}).get("allow", []))
    except (OSError, ValueError):
        return []


def extra_dirs():
    """Folders outside the office the agents may read (permissions.additionalDirectories in .claude/settings.json, such as
    D:\\), passed to claude -p as --add-dir: settings alone only count once the folder is trusted. Missing ones are skipped."""
    try:
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            dirs = json.load(f).get("permissions", {}).get("additionalDirectories", [])
    except (OSError, ValueError):
        return []
    return [d for d in dirs if isinstance(d, str) and os.path.isdir(d)]


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
        u = obj.get("usage") or {}
        tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        return [{"type": "result", "text": obj.get("result") or "", "is_error": bool(obj.get("is_error")),
                 "cost_usd": obj.get("total_cost_usd"), "duration_ms": obj.get("duration_ms"), "turns": obj.get("num_turns"),
                 "context": tokens // max(1, int(obj.get("num_turns") or 1))}]      # average tokens Claude read per turn
    return []


DEFAULT_MODEL = os.environ.get("HQ_MODEL", "claude-opus-5-5")
FABLE_MODEL = os.environ.get("HQ_FABLE_MODEL", "claude-fable-5-1")
FABLE_ASK = re.compile(r"\b(use|with|on|switch to)\s+fable\b|^\s*fable\s*[:,]|^\s*/fable\b|用\s*fable", re.I)


def model_for(prompt):
    """The office runs on Opus 5.5. Fable only when the owner asks for it in the message ("use Fable…", "fable: …",
    "/fable …"); that one run, and the sub-agents it starts, use Fable."""
    return FABLE_MODEL if FABLE_ASK.search(prompt or "") else DEFAULT_MODEL


TASK_REF = re.compile(r"hq/tasks\.js\"?\s+(?:move|progress|note|channel)\s+(t\d+)|\"added\":\s*\{\s*\"id\":\s*\"(t\d+)\"|\bboard task (t\d+)\b")


class Run:
    """One message to the lead. tasks: the board tasks it works on (the one it was started from, and any it adds or moves),
    so the board shows which task is really being worked on and the lead's reply lands in that task's chat."""
    def __init__(self, prompt, tasks=()):
        self.id, self.prompt, self.events, self.done, self.ok = uuid.uuid4().hex[:8], prompt, [], False, None
        self.tasks, self.started, self.started_at = list(dict.fromkeys(tasks)), False, None
        self.proc, self.stopped = None, False                # the claude process, and whether the owner pressed Stop
        self._link(prompt)

    def _link(self, text):
        for m in TASK_REF.finditer(text or ""):
            tid = next(g for g in m.groups() if g)
            if tid not in self.tasks:
                self.tasks.append(tid)

    def add(self, event):
        self.events.append(event)
        if event.get("type") in ("tool", "tool_done"):
            self._link(event.get("text") or "")

    def last_step(self):
        """What the lead is doing right now, in a few words (its last message or step)."""
        for ev in reversed(self.events):
            if ev.get("type") in ("text", "tool") and (ev.get("text") or ev.get("name")):
                return re.sub(r"\s+", " ", str(ev.get("text") or ev.get("name")))[:120]
        return "starting"

    def staff_jobs(self):
        """The sub-agents this run has working now, each with the job the lead gave it: [{id, staff, text}]. One sent to
        the background stays until the run ends (its own result comes later)."""
        if self.done or not self.started:
            return []
        open_ = {}
        for ev in list(self.events):
            if ev.get("type") == "tool" and ev.get("staff"):
                open_[ev.get("id")] = {"id": ev.get("id"), "staff": ev["staff"], "text": re.sub(r"^[^:]+:\s*", "", ev.get("text") or "")}
            elif ev.get("type") == "tool_done" and ev.get("id") in open_ and not re.search(r"background", ev.get("text") or "", re.I):
                del open_[ev["id"]]
        return list(open_.values())

    def summary(self):
        return {"id": self.id, "prompt": self.prompt, "done": self.done, "ok": self.ok, "events": len(self.events),
                "tasks": self.tasks, "queued": not self.started and not self.done}


class RunTimes:
    """How long finished lead jobs took, per kind of desk (a video, a task, the Lead tab), so a running job can show
    about how far along it is. Kept in hq/run-times.json across restarts."""
    PATH = os.path.join(HERE, "run-times.json")
    DEFAULT = {"out": 15 * 60, "task": 6 * 60, "lead": 4 * 60}

    def __init__(self):
        self.lock = threading.Lock()
        try:
            with open(self.PATH, encoding="utf-8") as f:
                self.seen = {k: [float(x) for x in v][-15:] for k, v in json.load(f).items() if k in self.DEFAULT}
        except (OSError, ValueError, TypeError, AttributeError):
            self.seen = {}

    @staticmethod
    def kind(lane):
        return lane.split(":")[0] if lane.split(":")[0] in RunTimes.DEFAULT else "lead"

    def add(self, lane, seconds):
        with self.lock:
            rows = self.seen.setdefault(self.kind(lane), [])
            rows[:] = (rows + [max(60.0, seconds)])[-15:]
            try:
                with open(self.PATH, "w", encoding="utf-8") as f:
                    json.dump(self.seen, f)
            except OSError:
                pass

    def progress(self, lane, run):
        """About how far along a running job is: 95 % at most until it is really done, so it never claims to be finished."""
        rows = sorted(self.seen.get(self.kind(lane)) or [])
        typical = rows[len(rows) // 2] if rows else self.DEFAULT[self.kind(lane)]
        gone = time.time() - (run.started_at or time.time())
        return max(1, min(95, int(95 * (1 - math.exp(-1.6 * gone / typical)))))


run_times = RunTimes()


FRESH_AFTER_IDLE = float(os.environ.get("HQ_LEAD_IDLE_MIN", "30")) * 60    # Claude's cache is gone by then: resuming re-buys the history
FRESH_AFTER_CONTEXT = int(os.environ.get("HQ_LEAD_MAX_CONTEXT", "120000"))  # tokens per turn: past this a new chat is far cheaper
FRESH_AFTER_COST = float(os.environ.get("HQ_LEAD_MAX_COST", "3"))           # dollars spent in one conversation


def end_process_tree(p):
    """End a lead job's claude process and everything it started (on Windows claude.cmd runs node, which runs tools)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            p.kill()
    except (OSError, subprocess.SubprocessError) as e:
        sys.stderr.write(f"could not stop process {p.pid}: {e}\n")


class Desk:
    """One lead conversation. Each message resumes it, so "OK" and corrections keep their context. To save tokens a new
    conversation starts after a long pause, or once the old one grew big or expensive (the brain and the files carry over).
    gate: shared by every desk (see Desks), it caps how many lead jobs run at the same time."""

    def __init__(self, gate=None, name="lead"):
        self.gate, self.name = gate, name
        self.session_id, self.resumable, self.runs, self.order, self.current = str(uuid.uuid4()), False, {}, [], None
        self.last_at, self.spent, self.context = 0.0, 0.0, 0
        self.queue, self.on_done = [], None              # messages waiting for the lead to finish; on_done(run) after each
        self.lock = threading.Lock()

    def fresh_reason(self):
        if not self.resumable:
            return ""
        if time.time() - self.last_at > FRESH_AFTER_IDLE:
            return f"over {int(FRESH_AFTER_IDLE // 60)} min since the last message"
        if self.context > FRESH_AFTER_CONTEXT:
            return "the conversation got long"
        if self.spent > FRESH_AFTER_COST:
            return f"this conversation cost over ${FRESH_AFTER_COST:g}"
        return ""

    def note_usage(self, ev):
        self.spent += float(ev.get("cost_usd") or 0)
        self.context = max(self.context, int(ev.get("context") or 0))

    def start(self, prompt, tasks=()):
        """Start a message, or line it up behind the one the lead is working on (it starts by itself when that is done)."""
        with self.lock:
            run = Run(prompt, tasks)
            self.runs[run.id] = run
            self.order.append(run.id)
            if self.current and not self.current.done:
                self.queue.append(run)
                run.add({"type": "system", "text": f"waiting: {'the lead finishes your previous message first' if self.name == 'lead' else 'an earlier job on the same video finishes first'} ({len(self.queue)} in line)"})
                return run
            self.current = run
        threading.Thread(target=self._work, args=(run,), daemon=True).start()
        return run

    def _work(self, run):
        if self.gate and not self.gate.acquire(blocking=False):
            run.add({"type": "system", "text": "waiting for a free slot: the most lead jobs that run at once are already running"})
            self.gate.acquire()
        run.started, run.started_at = True, time.time()
        try:
            if run.stopped:                                  # stopped while it waited for a free slot
                run.ok, run.done = False, True
            else:
                self._run(run)
        finally:
            if self.gate:
                self.gate.release()
            if run.ok:
                run_times.add(self.name, time.time() - run.started_at)
            if self.on_done:
                try:
                    self.on_done(run)
                except Exception as e:                    # the board never stops the lead
                    sys.stderr.write(f"after run {run.id}: {e}\n")
            with self.lock:
                nxt = self.queue.pop(0) if self.queue else None
                if nxt:
                    self.current = nxt
            if nxt:
                threading.Thread(target=self._work, args=(nxt,), daemon=True).start()

    def working_on(self):
        """{task id: "working" step text, or "queued"} for the lead's current and waiting messages."""
        with self.lock:
            cur, waiting = self.current, list(self.queue)
        out = {}
        for r in waiting:
            for tid in r.tasks:
                out[tid] = {"state": "queued"}
        if cur and not cur.done:
            for tid in cur.tasks:
                out[tid] = {"state": "working", "step": cur.last_step(), "progress": run_times.progress(self.name, cur)} if cur.started else {"state": "queued"}
        return out

    def _run(self, run):
        why = self.fresh_reason()
        if why:
            self.session_id, self.resumable, self.spent, self.context = str(uuid.uuid4()), False, 0.0, 0
            run.add({"type": "system", "text": f"new conversation to save tokens ({why}); the brain and files carry over"})
        for attempt in (1, 2):
            # one line: claude.cmd on Windows cuts -p at the first newline and drops the flags after it
            prompt = re.sub(r"\s*\n+\s*", " / ", with_skills(run.prompt).strip())
            cmd = [CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model_for(prompt)]
            cmd += ["--append-system-prompt", COPY_NOTE]       # prompts go in their own block: the app gives each one a Copy button
            allowed = allow_list()
            if allowed:
                cmd += ["--allowedTools", *allowed]
            for d in extra_dirs():                         # readable folders outside the office, such as the D: drive
                cmd += ["--add-dir", d]
            cmd += ["--resume", self.session_id] if self.resumable else ["--session-id", self.session_id]
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            try:
                p = run.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
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
                    if ev["type"] == "result":
                        self.note_usage(ev)
                    run.add(ev)
            err = p.stderr.read().strip()
            p.wait()
            if run.stopped:                                  # the owner pressed Stop: no retry, no error to explain
                run.ok = False
                run.add({"type": "system", "text": "stopped by you"})
                break
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
        self.last_at = time.time()
        run.done = True

    def stop(self, match):
        """Stop this desk's jobs that match(run): the running one is ended, waiting ones leave the line."""
        stopped = []
        with self.lock:
            cur, waiting = self.current, list(self.queue)
            for r in waiting:
                if match(r):
                    self.queue.remove(r)
                    r.stopped, r.ok, r.done = True, False, True
                    r.add({"type": "system", "text": "taken out of line by you"})
                    stopped.append(r)
        if cur and not cur.done and match(cur):
            cur.stopped = True
            if cur.proc and cur.proc.poll() is None:
                end_process_tree(cur.proc)
            stopped.append(cur)
        for r in stopped:
            if r is not cur and self.on_done:            # a job taken out of line still tells its task
                try:
                    self.on_done(r)
                except Exception as e:
                    sys.stderr.write(f"after stopping {r.id}: {e}\n")
        return stopped

    def state(self):
        with self.lock:
            cur = self.current
        return {"busy": bool(cur and not cur.done), "current": cur.id if cur else None, "queued": len(self.queue),
                "runs": [self.runs[i].summary() for i in self.order[-20:]]}


MAX_LEADS = 10                                                      # the most lead jobs the owner can let run at once


def leads_setting():
    """How many lead jobs run at the same time: HQ_PARALLEL, else the owner's choice in the menu (.hq-office.json), else 3."""
    try:
        n = int(os.environ.get("HQ_PARALLEL") or office_conf().get("leads") or 3)
    except (TypeError, ValueError):
        n = 3
    return max(1, min(MAX_LEADS, n))


def save_office(patch):
    """Merge `patch` into .hq-office.json (written whole, then renamed into place)."""
    data = dict(office_conf())
    data.update(patch)
    tmp = OFFICE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OFFICE_FILE)


class Gate:
    """The free slots for lead jobs. Unlike a semaphore its size can change while jobs run: more slots start waiting jobs
    at once, fewer let the running ones finish and start nothing new until the count is under the new limit."""

    def __init__(self, limit):
        self.limit, self.used, self.cond = limit, 0, threading.Condition()

    def acquire(self, blocking=True):
        with self.cond:
            while self.used >= self.limit:
                if not blocking:
                    return False
                self.cond.wait()
            self.used += 1
            return True

    def release(self):
        with self.cond:
            self.used = max(0, self.used - 1)
            self.cond.notify_all()

    def resize(self, limit):
        with self.cond:
            self.limit = limit
            self.cond.notify_all()


MAX_PARALLEL = leads_setting()                                     # lead jobs that run at the same time (the menu changes it)


def lane_of(tasks):
    """Which desk a message goes to: one per video folder (a task's out:<name>), so work on different videos runs at the
    same time and two jobs never edit the same folder at once; a task without a folder gets its own; anything else
    (the Lead tab, follow-ups) goes to the lead's own conversation."""
    if not tasks:
        return "lead"
    task = next((t for t in load_tasks()["tasks"] if t.get("id") == tasks[0]), None)
    m = re.search(r"out:([^\s,;]+)", (task or {}).get("note") or "")
    return "out:" + re.sub(r"-v\d+$", "", m[1].strip("/").split("/")[0]) if m else "task:" + tasks[0]


class Desks:
    """Several lead conversations at once: the lead's own (the Lead tab) and one per video or task. Each keeps its own
    context, so a task's chat resumes that task's conversation. At most MAX_PARALLEL run at the same time; the rest wait
    for a free slot, and a second job for the same video waits for the first."""

    def __init__(self, limit=MAX_PARALLEL):
        self.gate, self.lanes, self.runs, self.order, self.on_done = Gate(limit), {}, {}, [], None
        self.lock = threading.Lock()

    @property
    def limit(self):
        return self.gate.limit

    def set_limit(self, n):
        self.gate.resize(n)

    def lane(self, key):
        with self.lock:
            if key not in self.lanes:
                d = self.lanes[key] = Desk(self.gate, key)
                d.on_done = lambda run: self.on_done and self.on_done(run)
            return self.lanes[key]

    def start(self, prompt, tasks=()):
        run = self.lane(lane_of(list(tasks))).start(prompt, tasks)
        with self.lock:
            self.runs[run.id] = run
            self.order.append(run.id)
        return run

    def stop(self, task=None, run=None, everything=False):
        """The owner's Stop: one task's jobs, one job, or everything the lead is doing. Returns the jobs stopped."""
        match = lambda r: everything or (run and r.id == run) or (task and task in r.tasks)
        out = []
        for d in list(self.lanes.values()):
            out += d.stop(match)
        return [{"id": r.id, "tasks": r.tasks, "prompt": r.prompt[:120]} for r in out]

    def progress_of(self, prefix):
        """A lead job whose prompt starts with prefix: its estimated % (0 while it waits in line), or None when none runs."""
        for d in list(self.lanes.values()):
            with d.lock:
                cur, waiting = d.current, list(d.queue)
            if cur and not cur.done and cur.prompt.startswith(prefix):
                return run_times.progress(d.name, cur) if cur.started else 0
            if any(r.prompt.startswith(prefix) for r in waiting):
                return 0
        return None

    def staff_jobs(self):
        """Every sub-agent at work across the running lead jobs, with its job and the board tasks of its lead job."""
        with self.lock:
            busy = [d.current for d in self.lanes.values() if d.current and not d.current.done]
        return [dict(job, tasks=list(run.tasks)) for run in busy for job in run.staff_jobs()]

    def working_on(self):
        out = {}
        for d in list(self.lanes.values()):
            for tid, live in d.working_on().items():
                if tid not in out or live["state"] == "working":
                    out[tid] = live
        return out

    def state(self):
        with self.lock:
            runs = [self.runs[i] for i in self.order[-20:]]
            busy = [d.current for d in self.lanes.values() if d.current and not d.current.done]
        working = [r for r in busy if r.started]
        newest = max(working, key=lambda r: self.order.index(r.id), default=None)
        return {"busy": bool(busy), "current": newest.id if newest else None, "running": len(working), "limit": self.limit,
                "queued": sum(len(d.queue) for d in self.lanes.values()) + len(busy) - len(working),
                "runs": [r.summary() for r in runs]}


desk = Desks()
desk.on_done = lambda run: (after_run(run), notifier.refresh())


# after-approval follow-ups (hq/followups.py): approved/<name>/followups.json hands the work on to the chief of staff
followups = FollowUps(ROOT, desk.start, lambda **task: task_action({"action": "add", **task})[1]["added"])
sermon_design = SermonDesignBridge(ROOT, task_action, load_tasks, notify=lambda: notifier.refresh())
thumbnail_design = ThumbnailDesignBridge(ROOT, sermon_design, channels, task_action, load_tasks, notify=lambda: notifier.refresh())
scripts = Scripts(ROOT, task_action, load_tasks, lambda prompt: desk.start(prompt))
packages = Packages(ROOT, thumbnail_design, task_action, approve_folder, load_tasks, lambda prompt: desk.start(prompt),
                    lambda prefix: desk.progress_of(prefix))   # a job for it: its estimated %, or None when none runs


def on_approved(name):
    """Called right after out/<name> moved to approved/<name>. Runs in its own thread: the caller may hold TASK_LOCK."""
    def work():
        try:
            if followups.approved(name):
                notifier.refresh()
        except Exception as e:
            sys.stderr.write(f"follow-ups for {name}: {e}\n")
    threading.Thread(target=work, daemon=True).start()


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
    base = os.path.realpath(base)
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
        secure = SECURE or ((TRUST_PROXY or LOCAL_TRUST) and self.headers.get("X-Forwarded-Proto", "").lower() == "https")
        return ("Set-Cookie", f"hq_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else ""))

    def authed(self):
        if not PASSWORD:
            return True
        if LOCAL_TRUST and not TRUST_PROXY and self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1") \
                and not self.relayed():
            return True
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "hq_session" in jar and token_ok(jar["hq_session"].value)

    def relayed(self):
        """True when a local proxy forwarded the request from another device (tailscale serve for https, or any
        reverse proxy): it must log in like any phone, even though it reaches us from 127.0.0.1."""
        h = self.headers
        host = (h.get("Host") or "").strip().lower()
        if host and not re.match(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", host):
            return True                                   # a phone typed a .ts.net or LAN name: never this computer's own window
        return any(h.get(k) for k in ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-IP",
                                       "Tailscale-User-Login", "Tailscale-User-Name", "Tailscale-Headers-Info"))

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
            obj = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}
        return obj if isinstance(obj, dict) else {}

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

    def send_typed(self, full, ctype):
        """A small public file with its exact type (the app's worker must be served as JavaScript). The pages and the
        app description carry this office's own name."""
        with open(full, "rb") as f:
            data = named(data=f.read(), ctype=ctype)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def send_page(self, full):
        """app.html and login.html, with this office's name. Never cached: a new name shows on the next open."""
        with open(full, "rb") as f:
            data = named(f.read(), "text/html")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_static(self, full):
        return self.send_file(full) if full and os.path.isfile(full) else self.send_json({"error": "not found"}, 404)

    def send_app_file(self, full):
        """The office's own scripts and styles: gzipped (about a quarter of the size, so a phone over Tailscale gets them
        quickly) and revalidated each time, so a phone keeps what it already has until the file changes (an update)."""
        if not (full and os.path.isfile(full)):
            return self.send_json({"error": "not found"}, 404)
        st = os.stat(full)
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        if etag in (self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        zipped = "gzip" in (self.headers.get("Accept-Encoding") or "") and re.match(r"^(text/|application/(javascript|json))", ctype)
        body = None
        if zipped:
            with APP_GZ_LOCK:
                hit = APP_GZ.get(full)
            body = hit[1] if hit and hit[0] == etag else None
        if body is None:
            with open(full, "rb") as f:
                body = f.read()
            if zipped:
                body = gzip.compress(body, 6)
                with APP_GZ_LOCK:
                    APP_GZ[full] = (etag, body)
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # routes
    def do_GET(self):
        url = urlparse(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        if path == "/login":
            return self.redirect("/") if not PASSWORD or self.authed() else self.send_page(os.path.join(HERE, "login.html"))
        if path in PWA_FILES:                              # the phone app's description, icons, offline page and worker:
            name, ctype = PWA_FILES[path]                  # public, since a phone fetches them before it logs in
            return self.send_typed(os.path.join(HERE, "pwa", name), ctype)
        if path in ("/", "/index.html"):
            return self.guard(page=True) and self.send_page(os.path.join(HERE, "app.html"))
        if path in ("/oauth/youtube", "/oauth/tiktok"):     # Google / TikTok send the browser back here; the one-time state is the check
            which = "TikTok" if path.endswith("tiktok") else "YouTube"
            try:
                if qs.get("error"):
                    raise publish.PostError((qs.get("error_description") or qs["error"])[0])
                finish = accounts.tiktok_finish if which == "TikTok" else accounts.youtube_finish
                name = finish(qs.get("state", [""])[0], qs.get("code", [""])[0])
                msg, ok = f"{which} is connected{(' (' + name + ')') if name else ''}. You can close this tab and go back to Agents HQ.", True
            except publish.PostError as e:
                msg, ok = f"{which} was not connected: {e}", False
            page = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agents HQ</title>'
                    f'<body style="font:16px system-ui;background:#0f1115;color:#e8e8ea;display:grid;place-items:center;height:90vh;text-align:center">'
                    f'<p style="max-width:28em">{"✅" if ok else "⚠️"} {html_escape(msg)}</p></body>').encode()
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if not self.guard():
            return
        if thumbnail_design.handle(self) or sermon_design.handle(self):
            return
        if path == "/api/status":
            return self.send_json(status_payload())
        if path == "/api/teams":
            return self.send_json({"teams": teams_payload(), "brain_notes": brain_notes()})
        if path == "/api/meeting":                         # the Meeting Hall's screens and the meeting times
            return self.send_json(meeting_payload())
        if path == "/api/skills":                          # the / menu in the app's chat boxes
            return self.send_json({"skills": office_slash()})
        if path == "/api/agents":
            return self.send_json(agents())
        if path == "/api/events":
            return self.send_json(events(qs_int(qs, "after")))
        if path == "/api/tasks":
            return self.send_json(load_tasks())
        if path == "/api/notifications":
            return self.send_json(notifier.payload(qs_int(qs, "after")))
        if path == "/api/push":                            # the office's public key, for a phone to subscribe
            return self.send_json({"available": webpush.AVAILABLE, "key": push.public_key(), "phones": push.count()})
        if path == "/api/calendar":
            cal = calendar_payload(qs.get("month", [""])[0])
            return self.send_json(cal) if cal else self.send_json({"error": "month must be YYYY-MM"}, 400)
        if path == "/api/brain":
            return self.send_json(brain_payload())
        if path == "/api/work":
            w = work_payload(qs.get("folder", [""])[0])
            return self.send_json(w) if w else self.send_json({"error": "no such work folder"}, 404)
        if path == "/api/chatter":
            return self.send_json(chatter_payload())
        if path == "/api/accounts":
            return self.send_json({**accounts.summary(qs.get("channel", [""])[0]), "tiktokRedirect": tiktok_redirect() or ""})
        if path == "/api/channels":
            return self.send_json(channels.payload())
        if path == "/api/publish":                         # the posting overview: also for work still waiting for the OK
            d = approved_dir(qs.get("folder", [""])[0], ("approved", "out"))
            if not d:
                return self.send_json({"error": "no such work folder"}, 404)
            pl = publisher.payload(d)
            return self.send_json({**pl, "channel_name": channels.name(pl["channel"])})
        if path == "/api/brain/notes":
            return self.send_json({"notes": brain_notes()})
        if path == "/api/runs":
            return self.send_json(desk.state())
        m = re.match(r"^/api/runs/([0-9a-f]{8})$", path)
        if m:
            run = desk.runs.get(m[1])
            if not run:
                return self.send_json({"error": "no such run"}, 404)
            after = qs_int(qs, "after")
            return self.send_json({**run.summary(), "events": run.events[after:], "offset": after})
        m = re.match(r"^/files/(out|approved)/(.+)$", path)
        if m:
            full = safe_join(os.path.join(ROOT, m[1]), m[2])
            if "phone" in qs and full and full.lower().endswith((".mp4", ".mov", ".m4v")) and os.path.isfile(full):
                full = phone_copy(full) or full             # the phone plays a small copy; the original if it can't be made
            elif "phone" in qs and full and full.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and os.path.isfile(full):
                st = os.stat(full)                          # the phone gets a small preview of a picture
                small = thumbnail_preview(full, f"{os.path.abspath(full)}|{st.st_size}|{st.st_mtime_ns}")
                if small:
                    return thumbnail_send_preview(self, small)
            return self.send_static(full)
        if path in STATIC:
            return self.send_app_file(os.path.join(HERE, path.lstrip("/")))
        m = re.match(r"^/vendor/(.+)$", path)
        if m:
            return self.send_app_file(safe_join(os.path.join(HERE, "vendor"), m[1]))
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/login":
            ip = self.client_ip()
            wait = throttle.wait(ip)
            if wait:
                return self.send_json({"error": f"too many wrong passwords, try again in {wait} s"}, 429)
            given = self.read_json().get("password") or ""
            if not PASSWORD or not isinstance(given, str) or not hmac.compare_digest(given.encode(), PASSWORD.encode()):
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
        LAST_ACTION[0] = time.time()                       # the owner is using HQ: an update restart waits
        if thumbnail_design.handle(self) or sermon_design.handle(self):
            return
        if path == "/api/restart":
            code, res = restart_office(self.read_json().get("force") is True)
            return self.send_json(res, code)
        if path == "/api/leads":                           # the menu's "Leads at once": takes effect now, kept for next time
            n = self.read_json().get("leads")
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_LEADS:
                return self.send_json({"error": f"leads must be a whole number from 1 to {MAX_LEADS}"}, 400)
            save_office({"leads": n})
            desk.set_limit(n)
            return self.send_json({"leads": n, "env": bool(os.environ.get("HQ_PARALLEL"))})
        if path == "/api/meeting":                         # "OK, meeting now" (a real discussion), or the daily review on/off
            body = self.read_json()
            if body.get("action") == "start":
                return self.send_json(start_meeting_review("now", str(body.get("topic") or "")[:600]))
            if body.get("action") == "review" and isinstance(body.get("on"), bool):
                cfg = meeting_config(); cfg["review"] = body["on"]; save_meeting_config(cfg)
                return self.send_json(meeting_payload())
            return self.send_json({"error": "action: start, or review with on true/false"}, 400)
        if path == "/api/stop":                            # the owner's Stop: a task's jobs, one job, or everything
            body = self.read_json()
            task = body.get("task") if isinstance(body.get("task"), str) and re.match(r"^t\d+$", body.get("task")) else None
            run = body.get("run") if isinstance(body.get("run"), str) and re.match(r"^[0-9a-f]{8}$", body.get("run")) else None
            if not (task or run or body.get("all") is True):
                return self.send_json({"error": "say what to stop: task, run or all"}, 400)
            stopped = desk.stop(task=task, run=run, everything=body.get("all") is True)
            return self.send_json({"stopped": stopped})
        if path == "/api/run":
            body = self.read_json()
            prompt = body.get("prompt") or ""
            prompt = prompt.strip() if isinstance(prompt, str) else ""
            if not prompt:
                return self.send_json({"error": "empty message"}, 400)
            task = body.get("task") if isinstance(body.get("task"), str) and re.match(r"^t\d+$", body.get("task")) else None
            run = desk.start(prompt, tasks=[task] if task else ())   # waits in line if the lead is busy
            return self.send_json(run.summary(), 202)
        if path == "/api/tasks":
            code, payload = task_action(self.read_json())
            if code < 400:
                notifier.refresh()               # so the bell rings on the next poll, not the one after
            return self.send_json(payload, code)
        if path == "/api/push":                  # this phone turns notifications on or off, or asks for a test
            body = self.read_json()
            try:
                if body.get("action") == "subscribe":
                    return self.send_json({"phones": push.subscribe(body.get("subscription"), body.get("device"))})
                if body.get("action") == "unsubscribe":
                    push.unsubscribe(str((body.get("subscription") or {}).get("endpoint") or ""))
                    return self.send_json({"phones": push.count()})
                if body.get("action") == "test":
                    sent = push.send("Agents HQ", "Notifications work. You'll hear from the office here when something needs you.", "/", "hq-test")
                    return self.send_json({"sent": sent}, 200 if sent else 502)
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"error": "action: subscribe, unsubscribe or test"}, 400)
        if path == "/api/accounts":
            code, payload = accounts_action(self.read_json(), f"http://127.0.0.1:{self.server.server_address[1]}/oauth/youtube")
            return self.send_json(payload, code)
        if path == "/api/publish":                         # the owner's Post button: the only way anything gets posted
            body = self.read_json()
            d = approved_dir(body.get("folder"))
            if not d:
                return self.send_json({"error": "only approved work can be posted"}, 404)
            try:
                if body.get("cancel") in publish.PLATFORMS:      # cancel a scheduled Instagram post still waiting here
                    publisher.cancel(d, body["cancel"])
                    return self.send_json(publisher.payload(d))
                chosen = {k: v for k, v in (body.get("platforms") or {}).items() if k in publish.PLATFORMS and isinstance(v, dict)}
                started = publisher.start(d, chosen, str(body.get("video") or ""), str(body.get("cover") or ""), body.get("when") or None,
                                          str(body.get("coverIg") or ""))
            except publish.PostError as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"started": started, **publisher.payload(d)}, 202)
        if path == "/api/channels":
            code, payload = channels_action(self.read_json())
            return self.send_json(payload, code)
        if path == "/api/scripts":                         # the Scripts card: keep, spare, trim a pick; Make videos
            try:
                result = scripts.action(self.read_json())
            except DesignError as e:
                return self.send_json({"error": str(e)}, e.status)
            notifier.refresh()
            return self.send_json(result)
        if path == "/api/package":                         # a video's package: its steps, the owner's picks, READY → approved
            try:
                result = packages.action(self.read_json())
            except DesignError as e:
                return self.send_json({"error": str(e)}, e.status)
            notifier.refresh()
            return self.send_json(result)
        if path == "/api/approve":
            name = self.read_json().get("name") or ""
            if isinstance(name, str) and name.startswith("thumbnail-final-"):
                marker = "out:" + name
                task = next((t for t in load_tasks().get("tasks", []) if marker in (t.get("note") or "").split()), None)
                if not task:
                    return self.send_json({"error": "The thumbnail final package has no native review task. Reopen its delivery status before approval."}, 409)
                code, payload = task_action({"action": "approve", "id": task["id"]})
            else:
                code, payload = approve_folder(name if isinstance(name, str) else "")
            return self.send_json(payload, code)
        return self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        if not self.guard():
            return
        if thumbnail_design.handle(self) or sermon_design.handle(self):
            return
        m = re.match(r"^/api/inbox/(clips|radar|stats|messages)/([^/]+)$", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        kind, name = m[1], m[2]
        if int(self.headers.get("Content-Length") or 0) > MAX_UPLOAD:
            return self.send_json({"error": f"file larger than {MAX_UPLOAD // (1024 * 1024)} MB"}, 413)
        if not SAFE_NAME.match(name) or os.path.splitext(name)[1].lower() not in UPLOAD_EXT[kind]:
            return self.send_json({"error": f"{kind} accepts {' '.join(sorted(UPLOAD_EXT[kind]))} files with a plain name"}, 400)
        ch = (parse_qs(urlparse(self.path).query).get("channel") or [""])[0] if kind == "clips" else ""
        if ch and not channels.get(ch):
            return self.send_json({"error": "no such channel"}, 404)
        folder = channels.inbox(ch) if kind == "clips" else os.path.join(ROOT, UPLOAD_DIRS[kind])
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
        rel = os.path.relpath(dst, ROOT).replace(os.sep, "/")
        if kind == "clips":                                 # like a video from Drive: it waits on the board for the Edit button
            channels.footage_task(rel, ch)
        return self.send_json({"saved": rel, "bytes": n}, 201)

    def do_HEAD(self):
        if not self.guard():
            return
        if thumbnail_design.handle(self) or sermon_design.handle(self):
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


RESTART_CODE = 75                                 # the office's exit code for "a newer version is in: start me again"
UPDATE_EVERY = float(os.environ.get("HQ_UPDATE_EVERY_MIN", "60")) * 60   # how often a running HQ looks for a newer version
QUIET_FOR = float(os.environ.get("HQ_QUIET_SEC", "120"))   # seconds without a click or message from the owner before it restarts
RESTART = threading.Event()
LAST_ACTION = [time.time()]                       # the owner's last POST (a click, a message): never restart under them


def supervise():
    """The process the desktop app (or Open Agents HQ) starts: it updates the folder from GitHub, then runs the office as
    its child, and starts it again whenever the office exits with RESTART_CODE (a newer version arrived while it was
    quiet). The office's own threads (posting schedule, Drive watcher, follow-ups) live and die with the child, so an
    update never leaves an old copy of them running. The cookie secret is kept, so phones stay logged in."""
    first = True
    while True:
        auto_update()
        env = dict(os.environ, HQ_CHILD="1", HQ_SECRET=SECRET.decode(),
                   HQ_UPDATE_NOTE=json.dumps({k: v for k, v in UPDATE.items() if k != "changed"}))
        if not first:
            env["HQ_RESTARTED"] = "1"                 # no second browser tab on a restart
            print("Agents HQ: starting the updated version", flush=True)
        try:
            code = subprocess.call([sys.executable] + sys.argv, env=env)
        except KeyboardInterrupt:
            print("\nAgents HQ closed.")
            return 0
        if code != RESTART_CODE:
            return code
        first = False


BOOT = uuid.uuid4().hex[:12]                      # this start of the office (a restart gets a new one)
PHONE_DIR = os.path.join(HERE, ".phone-videos")   # small copies of videos for watching on a phone, made on first view
PHONE_LOCKS, PHONE_LOCK = {}, threading.Lock()


def phone_copy(video):
    """A phone-sized copy of a video (540 wide, about 1.2 Mbit/s): a full-quality edit is too big to stream to a phone
    over Tailscale or mobile data, so it never starts. Made once per version of the file and kept in hq/.phone-videos/;
    None when ffmpeg is missing or fails (the original is sent then)."""
    st = os.stat(video)
    key = hashlib.sha1(f"{os.path.abspath(video)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:20]
    out = os.path.join(PHONE_DIR, key + ".mp4")
    with PHONE_LOCK:
        lock = PHONE_LOCKS.setdefault(key, threading.Lock())
    with lock:                                    # two requests for the same video wait for one copy
        if os.path.isfile(out):
            return out
        ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
        if not ff:
            return None
        os.makedirs(PHONE_DIR, exist_ok=True)
        tmp = out + ".part.mp4"
        try:
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vf", "scale='min(540,iw)':-2",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-maxrate", "1200k", "-bufsize", "2400k",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", tmp],
                           capture_output=True, timeout=600, check=True, creationflags=0x08000000 if os.name == "nt" else 0)
            os.replace(tmp, out)
            return out
        except (OSError, subprocess.SubprocessError) as e:
            sys.stderr.write(f"phone copy of {video}: {e}\n")
            return None


HTTPD = [None]                                    # the running server, so the owner's Restart can stop it


def busy_now():
    """What a restart would cut off, in plain words: lead jobs running or waiting, and posts going out."""
    d = desk.state()
    out = []
    if d["running"] or d["queued"]:
        out.append(f"{d['running']} job{'s' if d['running'] != 1 else ''} running" + (f", {d['queued']} waiting" if d["queued"] else ""))
    if publisher.busy:
        out.append(f"{len(publisher.busy)} post{'s' if len(publisher.busy) != 1 else ''} going out")
    return out


def restart_office(force=False):
    """The owner's Restart HQ (the user menu, or py -3 hq/restart.py): the office exits with RESTART_CODE and supervise()
    starts it again with the latest code, the same way an update restarts it. Refused while work is under way unless
    force, because a restart stops lead jobs and posts mid-way."""
    if not os.environ.get("HQ_CHILD") or not HTTPD[0]:
        return 409, {"error": "This HQ was started without its launcher, so it can't start itself again. Use Restart engine in the tray."}
    busy = busy_now()
    if busy and not force:
        return 409, {"error": "HQ is busy: " + " and ".join(busy) + ". Restarting now stops them.", "busy": busy}
    print("Agents HQ: restarting at the owner's request" + (" (stopping: " + ", ".join(busy) + ")" if busy else ""), flush=True)
    RESTART.set()
    threading.Timer(0.5, HTTPD[0].shutdown).start()       # after this reply has gone out
    return 200, {"ok": True, "stopped": busy}


# the office's skills for the / menu: the editing styles first (a /name in a message makes the worker use exactly that one)
EDITING_SKILLS = ("yellow-serif", "poster-kinetic", "caption-card", "sermon-moments", "reel", "sfx", "pixel")
SKILL_REF = re.compile(r"(?<![\w/.:-])/([a-z][a-z0-9-]{1,40})\b")


OFFICE_COMMANDS = [{"name": "meeting", "about": "All-hands: everyone to the 6F hall; add a topic for the heads to solve", "command": True}]


def office_skills():
    found = []
    base = os.path.join(ROOT, ".claude", "skills")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        try:
            with open(os.path.join(base, name, "SKILL.md"), encoding="utf-8") as f:
                head = f.read(4000)
        except OSError:
            continue
        m = re.search(r"^description:\s*(.+)$", head, re.M)
        desc = (m[1].strip().strip('"') if m else "")
        short = re.split(r"\s+-\s+|[.。]\s", desc, maxsplit=1)[0][:90]
        found.append({"name": name, "about": short, "editing": name in EDITING_SKILLS})
    order = {n: i for i, n in enumerate(EDITING_SKILLS)}
    return sorted(found, key=lambda x: (not x["editing"], order.get(x["name"], 99), x["name"]))


def office_slash():
    """The app's / menu: the office commands, then the skills."""
    return [dict(c) for c in OFFICE_COMMANDS] + office_skills()


COPY_NOTE = ("When you give the owner a prompt or any text meant to be pasted somewhere else (a prompt for Codex or another AI, "
             "a caption, a message, an email, a command), put exactly that text, and nothing else, in its own fenced code block: "
             "the Agents HQ chat shows a Copy button on each block.")


def with_skills(prompt):
    """A /skill the owner typed (e.g. /poster-kinetic): tell the lead to use exactly that skill for this work."""
    names = {x["name"] for x in office_skills()}
    picked = [n for n in dict.fromkeys(SKILL_REF.findall(prompt or "")) if n in names]
    if not picked:
        return prompt
    return prompt + " / The owner picked " + ", ".join("/" + n for n in picked) + ": use exactly " + ("that skill" if len(picked) == 1 else "those skills") + \
        " for this work (read .claude/skills/<name>/SKILL.md and its guide, and pass it to every worker), instead of the default style."


def task_video(t, thumb_jobs):
    """The video folder a task belongs to: its out:<name>; a Codex thumbnail package's own video; New footage's clip name."""
    m = re.search(r"out:([^\s,;]+)", t.get("note") or "")
    name = m[1].strip("/").split("/")[0] if m else ""
    if name.startswith("thumbnail-final-"):
        folder = (thumb_jobs.get(name[len("thumbnail-final-"):]) or {}).get("folder") or ""
        name = folder[4:] if folder.startswith("out/") else name   # a post cover made without a video keeps its own name
    if not name:
        m = re.match(r"New footage\s*·\s*(.+)$", t.get("title") or "")
        name = os.path.splitext(m[1].strip())[0] if m else ""
    if not name:                                          # a title that names the folder, e.g. "Redo post copy: <folder>"
        for slug in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", t.get("title") or ""):
            if any(os.path.isdir(os.path.join(ROOT, area, slug)) for area in ("out", "approved")):
                name = slug
                break
    return re.sub(r"-v\d+$", "", name)


def posted_platforms(name, scheduled=None):
    """Where approved/<name> (or one of its topics) went out: the platforms whose post finished. scheduled, a dict, also
    gets the platforms still waiting for their time and the earliest one: {"platforms": [...], "when": unix time}."""
    base = os.path.join(ROOT, "approved", name)
    if not SAFE_NAME.match(name) or not os.path.isdir(base):
        return []
    found = []
    for folder in [base] + [os.path.join(base, d) for d in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, d))]:
        try:
            with open(os.path.join(folder, "posted.json"), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        found += [p for p in publish.PLATFORMS if isinstance(rec.get(p), dict) and rec[p].get("state") == "posted" and p not in found]
        if scheduled is not None:
            for p in publish.PLATFORMS:
                e = rec.get(p) if isinstance(rec.get(p), dict) else {}
                if e.get("state") in ("scheduled", "uploading") and e.get("when"):
                    scheduled.setdefault("platforms", []).append(p)
                    scheduled["when"] = min(scheduled.get("when") or e["when"], e["when"])
    return found


def office_quiet():
    """No lead job running or waiting, nothing being posted, and the owner hasn't clicked anything for a while."""
    return not desk.state()["busy"] and not publisher.busy and time.time() - LAST_ACTION[0] > QUIET_FOR


def newer_version_waiting():
    if local_edits():                                      # unfinished work here: don't restart for an update it would wait for
        return False
    if git("fetch", "--quiet").returncode != 0 or git("rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        return False
    return git("merge-base", "--is-ancestor", "@{u}", "HEAD").returncode != 0


def watch_for_updates(httpd):
    """While HQ runs: look for a newer version on GitHub every UPDATE_EVERY; when there is one, wait for a quiet moment
    (checked every 2 minutes), then stop serving: the office exits with RESTART_CODE and supervise() updates and starts
    it again. Phones show "can't reach your PC" for a few seconds and come back by themselves."""
    if os.environ.get("HQ_NO_UPDATE") or not os.environ.get("HQ_CHILD"):
        return

    def loop():
        time.sleep(min(600, UPDATE_EVERY))
        while True:
            waiting = False
            try:
                waiting = newer_version_waiting()
                if waiting and office_quiet():
                    print("Agents HQ: a newer version is ready and the office is quiet, restarting into it", flush=True)
                    RESTART.set()
                    httpd.shutdown()
                    return
            except Exception as e:                    # no internet, git busy: try again later
                sys.stderr.write(f"update check: {e}" + chr(10))
            time.sleep(120 if waiting else UPDATE_EVERY)
    threading.Thread(target=loop, daemon=True).start()


STUDIO_REF = re.compile(r"sermon-studio-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def studio_trash_sync():
    """Open board tasks whose Codex Studio project is in the Studio's Trash: off the board, into Deleted. Returns how many."""
    db = load_tasks()
    by_pid = {}
    for t in db["tasks"]:
        if t.get("status") in ("todo", "doing", "review"):
            for pid in set(STUDIO_REF.findall(t.get("note") or "")):
                by_pid.setdefault(pid, []).append(t["id"])
    gone = []
    for pid, ids in by_pid.items():
        try:
            code, _, raw = sermon_design._request("GET", f"/api/sermon-design/projects/{pid}")
            if code == 200 and ((json.loads(raw or b"{}") or {}).get("project") or {}).get("deletedAt"):
                gone += ids
        except Exception:
            return 0                                          # the Studio is off: try again later, change nothing
    for i in dict.fromkeys(gone):
        task_action({"action": "remove", "id": i})
    return len(set(gone))


MEETING_DIR = os.path.join(ROOT, "work", "meetings")
MEETING_CFG = os.path.join(HERE, "meeting.json")
MEETING_LIVE = {"until": 0, "label": ""}


def meeting_config():
    """The meeting times and whether the daily written review runs (hq/meeting.json, the owner's switch)."""
    cfg = {"schedule": ["09:00", "14:00", "20:00"], "minutes": 15, "review": True, "review_at": "20:00"}
    try:
        with open(MEETING_CFG, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def save_meeting_config(cfg):
    with open(MEETING_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def latest_review():
    """The newest meeting notes in work/meetings/: the date, the top actions and one tip per team, for the projector."""
    try:
        files = sorted(f for f in os.listdir(MEETING_DIR) if re.match(r"\d{4}-\d{2}-\d{2}.*\.md$", f))
    except OSError:
        return None
    if not files:
        return None
    text = open(os.path.join(MEETING_DIR, files[-1]), encoding="utf-8").read()
    sections, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            cur = m[1].strip(); sections[cur] = []
        elif cur and re.match(r"^\s*(?:[-*]|\d+\.)\s+", line):
            sections[cur].append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+|\*\*", "", line).strip())
    actions = next((v for k, v in sections.items() if re.search(r"top|action|行动", k, re.I)), [])
    teams = [{"team": re.sub(r"^improve\s*[·:-]\s*", "", k, flags=re.I), "tip": v[0]} for k, v in sections.items() if re.match(r"improve", k, re.I) and v]
    return {"date": files[-1][:10], "file": "work/meetings/" + files[-1], "actions": actions[:5], "teams": teams[:9]}


def meeting_payload():
    """Everything the hall's screens show, for the main channel (NLRCC) only, the owner's wish: numbers with a 7-day
    spark, the latest videos and designs, the review's actions and the meeting times. Other channels stay off the hall."""
    cfg, now = meeting_config(), time.time()
    chans = [{"key": c["key"], "name": c.get("name") or "NLRCC"} for c in channels.payload()["channels"] if not c["key"]]
    known = {c["key"] for c in chans}
    per = {c["key"]: {"days": [0] * 7, "videos": [], "designs": [], "pipeline": 0} for c in chans}
    base = os.path.join(ROOT, "approved")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        d = os.path.join(base, name)
        try:
            rec = json.load(open(os.path.join(d, "posted.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plats = [p for p in publish.PLATFORMS if isinstance(rec.get(p), dict) and rec[p].get("state") in ("posted", "scheduled")]
        if not plats:
            continue
        ch = channels_mod.folder_channel(d)
        if ch not in known:
            continue
        P = per[ch]
        at = max(int(rec[p].get("at") or 0) for p in plats)
        for p in plats:
            if rec[p].get("state") == "posted":
                ago = int((now - int(rec[p].get("at") or 0)) // 86400)
                if 0 <= ago < 7:
                    P["days"][6 - ago] += 1
        cover = next((c for c in ("cover-codex.png", "cover.jpg") if os.path.isfile(os.path.join(d, c))), "")
        video = next((v for v in ("edit.mp4", "edit-sfx.mp4") if os.path.isfile(os.path.join(d, v))), "")
        title = ""
        try:
            opts = publish.drafts(d)["options"]
            pk = json.load(open(os.path.join(d, "package.json"), encoding="utf-8")) if os.path.isfile(os.path.join(d, "package.json")) else {}
            title = (opts[pk.get("caption") or 0] if opts else {}).get("title") or ""
        except Exception:
            pass
        state = "posted" if any(rec[p].get("state") == "posted" for p in plats) else "scheduled"
        P["videos"].append({"name": name, "title": title or name.replace("-", " "), "state": state, "at": at, "ch": ch,
                            "platforms": ", ".join(x.capitalize() for x in plats), "cover": f"/files/approved/{name}/{cover}" if cover else "",
                            "video": f"/files/approved/{name}/{video}" if video else ""})
    try:
        jobs = sorted((j for j in thumbnail_design._load()["jobs"].values() if j.get("status") == "delivered"), key=lambda j: j.get("approvedAt") or j.get("createdAt") or 0, reverse=True)
        for j in jobs:
            P = per.get(j.get("channel") or "")
            if P is not None and len(P["designs"]) < 6:
                P["designs"] += [{"url": o["url"], "ch": j.get("channel") or ""} for o in (thumbnail_design._public_job(j).get("options") or [])[:2] if o.get("url")]
    except Exception:
        pass
    tasks = load_tasks()["tasks"]
    hidden = {h.get("name") if isinstance(h, dict) else h for h in (load_tasks().get("hidden_out") or [])}
    outd = os.path.join(ROOT, "out")
    for n in (os.listdir(outd) if os.path.isdir(outd) else []):
        if n not in hidden and not n.startswith(("thumbnail-final-", "sermon-studio-")) and any(f.lower().endswith(".mp4") for _, _, fs in os.walk(os.path.join(outd, n)) for f in fs):
            ch = channels_mod.folder_channel(os.path.join(outd, n))   # videos still being made or waiting
            if ch in known:
                per[ch]["pipeline"] += 1
    for c in chans:
        P = per[c["key"]]
        P["videos"].sort(key=lambda v: v["at"], reverse=True)
        c["numbers"] = [
            {"label": "posts out\nthis week", "value": sum(P["days"]), "spark": P["days"]},
            {"label": "videos out\n(all time)", "value": sum(1 for v in P["videos"] if v["state"] == "posted")},
            {"label": "scheduled\nto go out", "value": sum(1 for v in P["videos"] if v["state"] == "scheduled")},
            {"label": "videos in\nthe pipeline", "value": P["pipeline"]},
        ]
        c["videos"], c["designs"] = P["videos"][:6], P["designs"][:6]
    days = [sum(per[c["key"]]["days"][k] for c in chans) for k in range(7)]
    numbers = [
        {"label": "posts out\nthis week", "value": sum(days), "spark": days},
        {"label": "videos out\n(all time)", "value": sum(c["numbers"][1]["value"] for c in chans)},
        {"label": "scheduled\nto go out", "value": sum(c["numbers"][2]["value"] for c in chans)},
        {"label": "videos in\nthe pipeline", "value": sum(c["numbers"][3]["value"] for c in chans)},
        {"label": "waiting for\nyour OK", "value": sum(1 for t in tasks if t.get("status") == "review" and (t.get("channel") or "") in known | {"main", "@office"})},
        {"label": "lessons the\noffice learned", "value": len((brain_entities().get("Lessons") or []))},
    ]
    mixed = lambda key, n: [x for row in __import__("itertools").zip_longest(*[c[key] for c in chans]) for x in row if x][:n]
    review = latest_review()
    lines = [("✅ " + a)[:60] for a in (review or {}).get("actions", [])[:5]]
    return {"schedule": cfg["schedule"], "minutes": cfg["minutes"], "reviewOn": cfg["review"], "reviewAt": cfg["review_at"],
            "next": " · ".join(cfg["schedule"]), "numbers": numbers, "channels": chans, "videos": mixed("videos", 6), "designs": mixed("designs", 6),
            "review": review, "lines": lines, "live": dict(MEETING_LIVE) if MEETING_LIVE["until"] > now else None}


def start_meeting_review(when, topic=""):
    """A real discussion: the heads go through the latest videos, posts, designs and numbers and write how to improve.
    One lead job. when: "now" (the owner's button or /meeting) or "daily" (8 pm); topic: what the owner wants discussed."""
    topic = re.sub(r"\s+", " ", topic or "").strip()
    today = time.strftime("%Y-%m-%d")
    os.makedirs(MEETING_DIR, exist_ok=True)
    out = f"work/meetings/{today}{'' if when == 'daily' else time.strftime('-%H%M')}.md"
    MEETING_LIVE.update(until=time.time() + 15 * 60, label="meeting now" if when == "now" else "daily review")
    code, r = task_action({"action": "add", "title": f"All-hands meeting · {today} {time.strftime('%H:%M')}", "team": "Analytics", "status": "doing",
                           "kind": "meeting", "note": "the whole office · " + (topic[:120] if topic else "how to improve"), "channel": "@office"})
    tid = (r.get("added") or {}).get("id")
    prompt = (f"All-hands meeting ({'the owner pressed OK, meeting now' if when == 'now' else 'the daily 8 pm review'}). Run it as the chief of staff with the team heads: "
              "look at what actually happened, then solve problems, don't just report. Read the brain (Company, Brand rules, Lessons, and each channel's entities), "
              "the latest videos in approved/ (their post.md, notes.md, posted.json: what went out, when, where), what waits in out/ and on the board (hq/tasks.json), "
              "any CSVs in inbox/stats/, and the newest work/social, work/analytics and work/design files. Then write " + out + " in exactly this layout: "
              "'# All-hands · <date>', '## Numbers' (3-5 bullets with real figures from the files, never invented), '## What worked' (3 bullets), "
              "This meeting is about NLRCC (the main channel) only: skip other channels' work (folders whose channel.txt holds a key such as pong-gospel, and their board tasks). "
              "one '## Improve · <Team>' section for each team that has something to fix (Creative, Design, Social, Scripts, Research, Analytics, Shop, Inbox, Dev: 1-3 bullets each, "
              "each a concrete fix tied to a real video, post or task), and '## Top 3 actions' (numbered, the three most useful things for this week, with who does them). "
              "Short sentences, plain words. Propose changes; don't make them, don't start other jobs, don't edit skills or agents, and nothing is posted or sent. ")
    if topic:
        prompt += (f"The owner called this meeting about: \"{topic}\". Discuss that first: put a '## The owner\'s question' section right after the title, "
                   "with each relevant head's answer (1-2 bullets each, named) and a clear recommendation. ")
    if tid:
        prompt += f"When done, move board task {tid} to review with: node hq/tasks.js move {tid} review"
    run = desk.start(prompt, tasks=[tid] if tid else ())
    return {"started": True, "task": tid, "run": run.id, "file": out, "live": dict(MEETING_LIVE)}


def keep_meeting_review():
    """The daily written review at review_at (8 pm), once a day, while it is switched on."""
    def loop():
        done_on = None
        while True:
            try:
                cfg = meeting_config()
                if cfg["review"] and time.strftime("%H:%M") == cfg["review_at"] and done_on != time.strftime("%Y-%m-%d"):
                    done_on = time.strftime("%Y-%m-%d")
                    if not os.path.isfile(os.path.join(MEETING_DIR, done_on + ".md")):
                        start_meeting_review("daily")
            except Exception as e:
                sys.stderr.write(f"meeting review: {e}" + chr(10))
            time.sleep(20)
    threading.Thread(target=loop, daemon=True).start()


def keep_studio_in_sync():
    def loop():
        time.sleep(30)
        while True:
            try:
                n = studio_trash_sync()
                if n:
                    print(f"Agents HQ: {n} board task(s) left with their Codex Studio project (in the Studio's Trash)", flush=True)
            except Exception as e:
                sys.stderr.write(f"studio sync: {e}" + chr(10))
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()


def keep_notifying():
    """Phone notifications go out even when no screen is open (the bell is normally refreshed by the app's polls)."""
    def loop():
        while True:
            time.sleep(20)
            try:
                notifier.refresh()
            except Exception as e:
                sys.stderr.write(f"notifications: {e}" + chr(10))
    threading.Thread(target=loop, daemon=True).start()


def main():
    if not os.environ.get("HQ_CHILD"):
        sys.exit(supervise())
    auto_update()                                     # in the office: only reads the launcher's result (HQ_UPDATE_NOTE)
    if HOST not in ("127.0.0.1", "localhost", "::1") and not PASSWORD:
        sys.exit(f"Refusing to listen on {HOST} without HQ_PASSWORD: anyone who reaches this port could run your team.")
    httpd = HTTPD[0] = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        sermon_design.resume_pending()       # only read-only watches for previously accepted native jobs
        thumbnail_design.resume_pending()    # only observes already approved thumbnail requests
    except Exception:
        print("Sermon delivery ledger needs attention; no generation was retried.", flush=True)
    followups.start()                    # also resends a follow-up queued before a restart
    publisher.run_scheduler()            # scheduled Instagram posts go out on time (or as soon as HQ runs again)
    channels.run_watcher()               # new videos in each channel's Google Drive folder become "New footage" tasks
    url = f"http://localhost:{PORT}"
    print(f"Agents HQ is open at {url}   (Ctrl+C to close)" + ("   login required" if PASSWORD else ""))
    if "--no-browser" not in sys.argv and not os.environ.get("HQ_RESTARTED"):
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    watch_for_updates(httpd)
    keep_notifying()
    keep_studio_in_sync()                # a poster deleted in Codex Studio leaves the board too
    keep_meeting_review()                # the all-hands' daily written review (8 pm; meeting.json switches it off)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAgents HQ closed.")
        return
    httpd.server_close()
    if RESTART.is_set():
        sys.exit(RESTART_CODE)


if __name__ == "__main__":
    main()
