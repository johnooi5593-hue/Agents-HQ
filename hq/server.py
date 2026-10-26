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
import datetime, hashlib, hmac, json, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, webbrowser
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from status import CLIP_EXT, brain_entities, brain_notes, collect  # noqa: E402
import activity  # noqa: E402  (watches every Claude Code session on this computer)

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
STATIC = {"/hud.js", "/hud.css", "/office3d.js"}
STATUSES = ("todo", "doing", "review", "done")
KINDS = ("task", "approval", "post", "meeting")
SCHEDULED_KINDS = ("post", "meeting")
TASK_DEFAULTS = {"team": "", "agent": "", "note": "", "kind": "task", "subtitle": "", "progress": None, "date": None, "time": None, "done_at": None}
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


def tool_status(tool, servers):
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
        team["tools"] = [{**tool, "status": tool_status(tool, servers)} for tool in t.get("tools", []) if isinstance(tool, dict)]
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
    """Move out/<name> to approved/<name>. Returns (http code, payload)."""
    src = safe_join(os.path.join(ROOT, "out"), name) if name else None
    if not name or not SAFE_NAME.match(name) or not src or not os.path.isdir(src):
        return 404, {"error": "no such work folder"}
    os.makedirs(os.path.join(ROOT, "approved"), exist_ok=True)
    dst = os.path.join(ROOT, "approved", name)
    if os.path.exists(dst):
        return 409, {"error": "already approved"}
    shutil.move(src, dst)
    return 200, {"approved": name}


def task_action(body):
    """POST /api/tasks: add, move, remove, approve, progress. Returns (http code, payload)."""
    action = body.get("action")
    with TASK_LOCK:
        db = load_tasks()
        task = next((t for t in db["tasks"] if t.get("id") == body.get("id")), None)
        if action == "add" and isinstance(body.get("title"), str) and body["title"].strip():
            nid = "t" + str(max([0] + [int(t["id"][1:]) for t in db["tasks"] if str(t.get("id", "t"))[1:].isdigit()]) + 1)
            new = {"id": nid, "title": body["title"].strip()[:200], "team": str(body.get("team") or "")[:40], "agent": str(body.get("agent") or "")[:60],
                   "status": body.get("status") if body.get("status") in STATUSES else "todo", "kind": body.get("kind") if body.get("kind") in KINDS else "task",
                   "note": str(body.get("note") or "")[:500], "subtitle": str(body.get("subtitle") or "")[:200], "progress": clean_progress(body.get("progress")),
                   "date": clean_date(body.get("date")), "time": clean_time(body.get("time")), "created": now_iso(), "updated": now_iso(),
                   "done_at": now_iso() if body.get("status") == "done" else None}
            db["tasks"].append(normalize_task(new)); save_tasks(db)
            return 201, {"added": new}
        if action == "move" and task and body.get("status") in STATUSES:
            set_status(task, body["status"]); save_tasks(db)
            return 200, {"moved": task}
        if action == "remove":
            n = len(db["tasks"]); db["tasks"] = [t for t in db["tasks"] if t.get("id") != body.get("id")]; save_tasks(db)
            return 200, {"removed": n - len(db["tasks"])}
        if action == "approve":
            if not task:
                return 404, {"error": "no such task"}
            moved, warning = None, None
            m = re.search(r"out:([^\s,;]+)", task.get("note") or "")
            if m:                                   # the task waits on a work folder: approve that too
                name = m[1].strip("/")
                code, res = approve_folder(name)
                if code in (200, 409):
                    moved = name
                else:
                    warning = f"{res['error']}: out/{name}"
            set_status(task, "done"); save_tasks(db)
            out = {"approved": task, "moved": moved}
            if warning:
                out["warning"] = warning
            return 200, out
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
    return 400, {"error": "action: add (title, team, kind?, date?, time?, subtitle?), move (id, status), remove (id), approve (id) or progress (id, progress, subtitle)"}


def calendar_payload(month):
    """Tasks with a date in the month, by day."""
    month = month or datetime.date.today().strftime("%Y-%m")
    if not MONTH_RE.match(month):
        return None
    days = {}
    for t in load_tasks()["tasks"]:
        if isinstance(t.get("date"), str) and t["date"].startswith(month + "-"):
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


def status_payload():
    ensure_coffee_chat()
    s = collect()
    ag, running, tasks = agents()["agents"], events()["running"], load_tasks()["tasks"]
    s["desk"], s["auth"], s["running"], s["tasks"] = desk.state(), bool(PASSWORD), running, tasks
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
                    if cur[1] in SCHEDULED_KINDS and cur[2] and cur[2] >= today:
                        self._item(fresh, team, f"{title} scheduled · {when}", "scheduled", iso_ms(t.get("updated")), task=tid)
                    continue
                if prev is None or prev[0] != cur[0]:
                    if cur[0] == "review":
                        self._item(fresh, team, f"{title} ready for your OK", "waiting", iso_ms(t.get("updated")), task=tid)
                    elif cur[0] == "done":
                        self._item(fresh, team, f"{title} done", "done", iso_ms(t.get("done_at") or t.get("updated")), task=tid)
                if (prev is None or prev[1:] != cur[1:]) and cur[1] in SCHEDULED_KINDS and cur[2]:
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


def auto_update():
    """Pull the newest Agents HQ from GitHub before starting, so the app keeps itself up to date."""
    if os.environ.get("HQ_NO_UPDATE") or not os.path.isdir(os.path.join(ROOT, ".git")):
        return
    try:
        before = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        p = subprocess.run(["git", "pull", "--ff-only", "--quiet"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        after = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        if p.returncode != 0:
            print("update check skipped:", (p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else "git pull failed")
        elif before != after:
            print(f"Agents HQ updated {before} -> {after}")
        else:
            print(f"Agents HQ is up to date ({after})")
    except (OSError, subprocess.SubprocessError) as e:
        print("update check skipped:", e)


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
        secure = SECURE or (TRUST_PROXY and self.headers.get("X-Forwarded-Proto", "").lower() == "https")
        return ("Set-Cookie", f"hq_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else ""))

    def authed(self):
        if not PASSWORD:
            return True
        if LOCAL_TRUST and not TRUST_PROXY and self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1") \
                and not self.headers.get("X-Forwarded-For"):
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
        if not self.guard():
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
        if path == "/api/approve":
            name = self.read_json().get("name") or ""
            code, payload = approve_folder(name if isinstance(name, str) else "")
            return self.send_json(payload, code)
        return self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        if not self.guard():
            return
        m = re.match(r"^/api/inbox/(clips|radar|stats|messages)/([^/]+)$", path)
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
    auto_update()
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
