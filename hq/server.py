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
import datetime, hashlib, hmac, html, json, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, webbrowser
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
from sermon_design import SermonDesignBridge  # noqa: E402  (native renderer; no Claude execution)
from thumbnail_design import ThumbnailDesignBridge  # noqa: E402

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
STATUSES = ("todo", "doing", "review", "done", "cancelled")   # cancelled: dropped by the owner, kept so it can come back
KINDS = ("task", "approval", "post", "meeting")
SCHEDULED_KINDS = ("post", "meeting")
TASK_DEFAULTS = {"team": "", "agent": "", "note": "", "kind": "task", "subtitle": "", "progress": None, "date": None, "time": None, "done_at": None, "channel": None}
OFFICE = "@office"      # task.channel: None = worked out from the task (task_channel), a channel key, or OFFICE = whole office
ACRONYMS = {"seo": "SEO", "qa": "QA", "ai": "AI", "ux": "UX", "ui": "UI", "pr": "PR", "hq": "HQ"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
TASK_LOCK = threading.Lock()


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
    with open(TASKS, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
        f.write("\n")


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
        error = thumbnail_design.guard_approval(name)
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
    names = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube"}
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


def edit_prompt(rel, ch, task_id):
    """The lead's instruction for the Edit button: edit-clips for that one video, for its channel."""
    n = channels.name(ch)
    who = (f" Channel: {n} (key {ch}). Same procedures as the main channel: follow \"Brand rules\" and \"Lessons\" as always, read "
           f"\"{n} · Company\" instead of \"Company\" and \"{n} · Brand rules\" on top (its rules win where they differ); never use the "
           f"main channel's name, logo, slogans or hashtags.") if ch else ""
    return f'/edit-clips "{rel}"{who} Board task {task_id} is this video\'s New footage task.'


def approved_dir(folder, areas=("approved",)):
    """approved/<name> → its path, or None. Only approved work can be posted; the overview may also read out/."""
    m = re.match(r"^(approved|out)/([^/]+)(?:/([^/]+))?$", str(folder or ""))         # a clip, or one topic of a long talk
    ok = m and m[1] in areas and SAFE_NAME.match(m[2]) and (not m[3] or SAFE_NAME.match(m[3]))
    d = safe_join(os.path.join(ROOT, m[1]), m[2] + ("/" + m[3] if m[3] else "")) if ok else None
    return d if d and os.path.isdir(d) else None


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
        if act == "disconnect" and body.get("which") in ("meta", "youtube"):
            accounts.disconnect(body["which"], ch)
            return 200, {"accounts": accounts.summary(ch)}
    except publish.PostError as e:
        return 400, {"error": str(e)}
    return 400, {"error": "unknown action"}


def task_action(body):
    """Use the same bridge→task lock order as thumbnail delivery callbacks."""
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
            run = desk.start(edit_prompt(*got, task["id"]))
            if not run:
                return 409, {"error": "the lead is still working on the previous message; try again when it is done"}
            set_status(task, "doing"); save_tasks(db)
            return 202, {"editing": task, "run": run.summary()}
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
    s["deleted"] = sorted(db.get("deleted") or [], key=lambda t: t.get("deleted_at") or "", reverse=True)
    for t in s["deleted"]:
        t["ch"] = task_channel(t)
    s["waiting_for_approval"] = [n for n in s["waiting_for_approval"] if n not in hidden]
    for t in tasks:                                        # Final: the video, the thumbnail and the caption are all there
        t["final"] = task_final(t)
        t["footage"] = bool(task_footage(t))                # New footage that waits for the Edit button
        t["ch"] = task_channel(t)                           # its channel (key, "" main) or None: the whole office
    s["channels"] = [{"key": c["key"], "name": c.get("name") or ("Main channel" if c["main"] else c["key"])} for c in channels.payload()["channels"]]
    for c in s["channels"][1:]:                             # a channel's clips wait in inbox/<key>/
        s["inbox"]["clips"] += [c["key"] + "/" + n for n in files(channels.inbox(c["key"]), CLIP_EXT)]
    s["desk"], s["auth"], s["running"], s["tasks"] = desk.state(), bool(PASSWORD), running, tasks
    s["update"] = dict(UPDATE)
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
            today, seen = datetime.date.today().isoformat(), set()
            for t in load_tasks()["tasks"]:
                tid = t.get("id"); seen.add(tid)
                cur, prev = (t["status"], t["kind"], t.get("date"), t.get("time")), self.board.get(tid)
                self.board[tid] = cur
                team, title = t.get("team") or "Office", t.get("title", "")
                when = t["time"] or t["date"]
                if not self.seeded:                  # what is still worth a bell when the server starts
                    if cur[0] == "review":
                        self._item(fresh, team, f"{title} ready for your OK", "waiting", iso_ms(t.get("updated")), task=tid)
                    elif cur[0] == "done" and is_today(t.get("done_at")):
                        self._item(fresh, team, f"{title} done", "done", iso_ms(t.get("done_at")), task=tid)
                    if cur[1] in SCHEDULED_KINDS and cur[2] and cur[2] >= today and cur[0] != "cancelled":
                        self._item(fresh, team, f"{title} scheduled · {when}", "scheduled", iso_ms(t.get("updated")), task=tid)
                    continue
                if prev is None or prev[0] != cur[0]:
                    if cur[0] == "review":
                        self._item(fresh, team, f"{title} ready for your OK", "waiting", iso_ms(t.get("updated")), task=tid)
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
            return len(self.items)

    def payload(self, after=0):
        total = self.refresh()
        with self.lock:
            return {"items": self.items[after:], "offset": after, "total": total}


notifier = Notifier()


UPDATE = {"ok": None, "version": "", "from": "", "message": "not checked", "at": 0}
USER_DATA = ("brain/memory.jsonl",)          # the owner's own data inside tracked files: never lost in an update


def git(*args, timeout=60):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")     # never sit waiting for a password nobody sees
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)


REPO_URL = os.environ.get("HQ_REPO_URL", "https://github.com/johnooi5593-hue/Agents-HQ")
REPO_BRANCH = os.environ.get("HQ_REPO_BRANCH", "main")


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


def auto_update():
    """Pull the newest Agents HQ from GitHub before starting, so the app keeps itself up to date.
    Robust to the owner's own changes: files the office edits locally (the brain) are backed up, the update is applied,
    and the two brains are merged so no rule or lesson is lost. Local commits are merged, never thrown away. The result
    is kept in UPDATE and shown in the app (user menu, and a warning when an update could not be applied)."""
    now = int(time.time())
    if os.environ.get("HQ_UPDATE_NOTE"):                  # restarted into the version just pulled: keep that result
        try:
            UPDATE.update(json.loads(os.environ["HQ_UPDATE_NOTE"]), changed=False)
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
        # the owner's local edits to tracked files: back them up, set them aside, update, then put them back
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


class Run:
    def __init__(self, prompt):
        self.id, self.prompt, self.events, self.done, self.ok = uuid.uuid4().hex[:8], prompt, [], False, None

    def add(self, event):
        self.events.append(event)

    def summary(self):
        return {"id": self.id, "prompt": self.prompt, "done": self.done, "ok": self.ok, "events": len(self.events)}


FRESH_AFTER_IDLE = float(os.environ.get("HQ_LEAD_IDLE_MIN", "30")) * 60    # Claude's cache is gone by then: resuming re-buys the history
FRESH_AFTER_CONTEXT = int(os.environ.get("HQ_LEAD_MAX_CONTEXT", "120000"))  # tokens per turn: past this a new chat is far cheaper
FRESH_AFTER_COST = float(os.environ.get("HQ_LEAD_MAX_COST", "3"))           # dollars spent in one conversation


class Desk:
    """One lead conversation. Each message resumes it, so "OK" and corrections keep their context. To save tokens a new
    conversation starts after a long pause, or once the old one grew big or expensive (the brain and the files carry over)."""

    def __init__(self):
        self.session_id, self.resumable, self.runs, self.order, self.current = str(uuid.uuid4()), False, {}, [], None
        self.last_at, self.spent, self.context = 0.0, 0.0, 0
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
        why = self.fresh_reason()
        if why:
            self.session_id, self.resumable, self.spent, self.context = str(uuid.uuid4()), False, 0.0, 0
            run.add({"type": "system", "text": f"new conversation to save tokens ({why}); the brain and files carry over"})
        for attempt in (1, 2):
            # one line: claude.cmd on Windows cuts -p at the first newline and drops the flags after it
            prompt = re.sub(r"\s*\n+\s*", " / ", run.prompt.strip())
            cmd = [CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model_for(prompt)]
            allowed = allow_list()
            if allowed:
                cmd += ["--allowedTools", *allowed]
            for d in extra_dirs():                         # readable folders outside the office, such as the D: drive
                cmd += ["--add-dir", d]
            cmd += ["--resume", self.session_id] if self.resumable else ["--session-id", self.session_id]
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            try:
                p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
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

    def state(self):
        with self.lock:
            cur = self.current
        return {"busy": bool(cur and not cur.done), "current": cur.id if cur else None,
                "runs": [self.runs[i].summary() for i in self.order[-20:]]}


desk = Desk()


# after-approval follow-ups (hq/followups.py): approved/<name>/followups.json hands the work on to the chief of staff
followups = FollowUps(ROOT, desk.start, lambda **task: task_action({"action": "add", **task})[1]["added"])
sermon_design = SermonDesignBridge(ROOT, task_action, load_tasks, notify=lambda: notifier.refresh())
thumbnail_design = ThumbnailDesignBridge(ROOT, sermon_design, channels, task_action, load_tasks, notify=lambda: notifier.refresh())


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

    def send_static(self, full):
        return self.send_file(full) if full and os.path.isfile(full) else self.send_json({"error": "not found"}, 404)

    # routes
    def do_GET(self):
        url = urlparse(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        if path == "/login":
            return self.redirect("/") if not PASSWORD or self.authed() else self.send_file(os.path.join(HERE, "login.html"))
        if path in ("/", "/index.html"):
            return self.guard(page=True) and self.send_file(os.path.join(HERE, "app.html"))
        if path == "/oauth/youtube":                       # Google sends the browser back here; the one-time state is the check
            try:
                if qs.get("error"):
                    raise publish.PostError(qs["error"][0])
                name = accounts.youtube_finish(qs.get("state", [""])[0], qs.get("code", [""])[0])
                msg, ok = f"YouTube is connected{(' (' + name + ')') if name else ''}. You can close this tab and go back to Agents HQ.", True
            except publish.PostError as e:
                msg, ok = f"YouTube was not connected: {e}", False
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
        if path == "/api/agents":
            return self.send_json(agents())
        if path == "/api/events":
            return self.send_json(events(qs_int(qs, "after")))
        if path == "/api/tasks":
            return self.send_json(load_tasks())
        if path == "/api/notifications":
            return self.send_json(notifier.payload(qs_int(qs, "after")))
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
            return self.send_json(accounts.summary(qs.get("channel", [""])[0]))
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
            return self.send_static(safe_join(os.path.join(ROOT, m[1]), m[2]))
        if path in STATIC:
            return self.send_static(os.path.join(HERE, path.lstrip("/")))
        m = re.match(r"^/vendor/(.+)$", path)
        if m:
            return self.send_static(safe_join(os.path.join(HERE, "vendor"), m[1]))
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
        if thumbnail_design.handle(self) or sermon_design.handle(self):
            return
        if path == "/api/run":
            prompt = (self.read_json().get("prompt") or "")
            prompt = prompt.strip() if isinstance(prompt, str) else ""
            if not prompt:
                return self.send_json({"error": "empty message"}, 400)
            run = desk.start(prompt)
            if not run:
                return self.send_json({"error": "the lead is still working on the previous message"}, 409)
            return self.send_json(run.summary(), 202)
        if path == "/api/tasks":
            code, payload = task_action(self.read_json())
            if code < 400:
                notifier.refresh()               # so the bell rings on the next poll, not the one after
            return self.send_json(payload, code)
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
                started = publisher.start(d, chosen, str(body.get("video") or ""), str(body.get("cover") or ""), body.get("when") or None)
            except publish.PostError as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"started": started, **publisher.payload(d)}, 202)
        if path == "/api/channels":
            code, payload = channels_action(self.read_json())
            return self.send_json(payload, code)
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


def restart_into_update():
    """The update changed the code on disk, but this process already loaded the old server: start the new one. On
    Windows the new engine runs as this one's child (the desktop app stops the whole tree); elsewhere it replaces it."""
    env = dict(os.environ, HQ_UPDATE_NOTE=json.dumps({k: v for k, v in UPDATE.items() if k != "changed"}))
    args = [sys.executable] + sys.argv
    print("Agents HQ: starting the updated version", flush=True)
    if os.name == "nt":
        sys.exit(subprocess.call(args, env=env))
    os.execve(sys.executable, args, env)


def main():
    auto_update()
    if UPDATE.get("changed"):
        restart_into_update()
    if HOST not in ("127.0.0.1", "localhost", "::1") and not PASSWORD:
        sys.exit(f"Refusing to listen on {HOST} without HQ_PASSWORD: anyone who reaches this port could run your team.")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
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
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAgents HQ closed.")


if __name__ == "__main__":
    main()
