"""The dead-run watchdog (t205). A clip-editor run died mid-render at 19:34 on 2026-11-08 and the board showed
"doing 85%" for an hour. A task is STALLED when all of these hold:
  - its status is doing (and it is not a post, meeting or approval task, the kinds the package's editing check skips),
  - its `updated` is older than HQ_STALL_MIN minutes (default 20),
  - no lead job in the app that references it is alive (Desks.working_on(): Run.tasks, filled from TASK_REF),
  - with out:<name> in its note: nothing in out/<name>/ (and work/<team>/<name>*/) changed in that time (files and the
    folders' own mtimes, newest folders first, within a time budget; when the budget runs out it counts as alive),
  - without out:<name>: an app run for it really ended (age alone never marks it).
Blind spot: a render that writes only outside these folders (to %TEMP%, or a project on D:) shows no growth here.
The task's status on disk is never changed; the status payload gets `stalled` + `stalled_since`, and one
{"event": "stalled", ...} line goes to hq/events.jsonl per stall (not every poll), so the chief of staff's feed shows it.
"""
import calendar
import json
import os
import re
import threading
import time

STALL_MIN = 20.0                                            # the Dev lesson: long renders go quiet for a while
OUT_REF = re.compile(r"(?:^|\s)out:([^\s,;]+)")
SKIP_KINDS = ("post", "meeting", "approval")                # the kinds video_package._editing skips
WALK_BUDGET = 0.5                                           # seconds one folder walk may take; past it: unknown (alive)
WALK_CACHE = 10                                             # seconds a folder's answer is reused (the board polls often)
UNKNOWN = object()                                          # the walk ran out of time before it found a change
_walks, _walk_lock = {}, threading.Lock()


def stall_seconds():
    try:
        return max(1.0, float(os.environ.get("HQ_STALL_MIN") or STALL_MIN)) * 60
    except ValueError:
        return STALL_MIN * 60


def iso(s):
    """The board's UTC timestamps (2026-11-08T11:34:00.000Z) as epoch seconds; None when missing or unreadable."""
    try:
        return calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")) if s else None
    except ValueError:
        return None


def newest_change(folder, after=None, now=None, budget=None):
    """A sign of life under folder: the first mtime newer than `after` (files and the folders themselves; a new frame
    changes its folder's mtime), else the newest mtime seen, None when empty, or UNKNOWN when the walk ran out of time.
    Folders are walked newest first. Reused for WALK_CACHE seconds."""
    now = time.time() if now is None else now
    key = (folder, after)
    with _walk_lock:
        hit = _walks.get(key)
    if hit and 0 <= now - hit[0] < WALK_CACHE:
        return hit[1]
    found = _walk(folder, after, WALK_BUDGET if budget is None else budget)
    with _walk_lock:
        if len(_walks) > 256:
            _walks.clear()
        _walks[key] = (now, found)
    return found


def _junction(entry):
    """True for a Windows junction or a symbolic link (os.DirEntry.is_junction is Python 3.12+; older: the reparse flag)."""
    try:
        if entry.is_symlink():
            return True
        is_j = getattr(entry, "is_junction", None)
        if is_j is not None:
            return bool(is_j())
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & 0x400)                          # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True                                         # can't tell: don't walk it


def _walk(folder, after, budget):
    deadline = time.monotonic() + budget
    newest, stack = None, [folder]
    while stack:
        if time.monotonic() > deadline:
            return UNKNOWN
        d = stack.pop()
        try:
            m = os.stat(d).st_mtime
            entries = list(os.scandir(d))
        except OSError:
            continue
        newest = m if newest is None or m > newest else newest
        if after is not None and m > after:
            return m
        subs = []
        for e in entries:
            if e.name.startswith(".") or _junction(e):
                continue                                    # a junction (or link) inside the folder is never walked
            try:
                if e.is_dir(follow_symlinks=False):
                    subs.append((e.stat(follow_symlinks=False).st_mtime, e.path))
                elif e.is_file(follow_symlinks=False):
                    fm = e.stat(follow_symlinks=False).st_mtime
                    newest = fm if newest is None or fm > newest else newest
                    if after is not None and fm > after:
                        return fm
            except OSError:
                continue
        stack += [p for _, p in sorted(subs)]               # the newest folder ends up on top: walked first
    return newest


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")    # the same rule as server.py's SAFE_NAME


def safe_join(base, rel):
    """Absolute path of rel under base, or None if it escapes (the same as server.py's safe_join; junctions resolved)."""
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, rel))
    return full if full == base or full.startswith(base + os.sep) else None


def task_folders(root, task):
    """out/<name> and work/<team>/<name>* for a task whose note names out:<name>; [] without one. Every name from the
    note goes through SAFE_NAME and safe_join, like server.py: a backslash, drive letter, UNC path or '..' gives []."""
    m = OUT_REF.search(task.get("note") or "")
    if not m:
        return []
    name = m[1].strip("/").split("/")[0]
    if not SAFE_NAME.match(name):
        return []
    first = safe_join(os.path.join(root, "out"), name)
    if not first:
        return []
    out = [first]
    team = re.sub(r"[^a-z0-9-]", "", str(task.get("team") or "").lower().replace(" ", "-"))
    work = safe_join(os.path.join(root, "work"), team) if team and SAFE_NAME.match(team) else None
    if work and os.path.isdir(work):
        try:
            for d in os.listdir(work):
                full = safe_join(work, d) if d.startswith(name) and SAFE_NAME.match(d) else None
                if full and os.path.isdir(full):
                    out.append(full)
        except OSError:
            pass
    return out


def stalled(tasks, live, root, now=None, limit=None, ended=frozenset()):
    """{task id: stalled_since (epoch s)} for the stalled tasks. live: the ids of tasks a running (or waiting) lead job
    references; ended: the ids of tasks an app run worked on that has ended (a task without out:<name> needs one).
    stalled_since: the last sign of life (the task's update, or a change in its folders)."""
    now = time.time() if now is None else now
    limit = stall_seconds() if limit is None else limit
    out = {}
    for t in tasks:
        if not isinstance(t, dict) or t.get("status") != "doing" or t.get("kind") in SKIP_KINDS or t.get("id") in live:
            continue
        last = iso(t.get("updated"))
        if last is None or now - last < limit:
            continue
        folders = task_folders(root, t)
        if not folders and t.get("id") not in ended:
            continue                                        # no folder to watch and no app run ended: age alone says nothing
        alive = False
        for d in folders:
            m = newest_change(d, last, now) if os.path.isdir(d) else None
            if m is UNKNOWN:
                alive = True                                # too big to check in time: never a false alarm
                break
            if m is not None and m > last:
                last = m
        if not alive and now - last >= limit:
            out[t["id"]] = last
    return out


class Watchdog:
    """Marks stalled tasks in the status payload and writes one events.jsonl line per stall."""

    def __init__(self, root, events_file, live=lambda: set(), ended=lambda: set()):
        self.root, self.events_file, self.live, self.ended = root, events_file, live, ended
        self.reported, self.lock = {}, threading.Lock()   # task id -> stalled_since already written to the feed
        self.seeded = False

    def _seed(self):
        """The stalls already in the feed (written before a restart) are not written again."""
        try:
            with open(self.events_file, encoding="utf-8") as f:
                for line in f:
                    if '"stalled"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("event") == "stalled" and e.get("task"):
                        since = iso(e.get("since"))
                        if since is not None:
                            self.reported[e["task"]] = since
        except OSError:
            pass
        self.seeded = True

    def mark(self, tasks, now=None):
        """Sets t["stalled"] / t["stalled_since"] (ISO, UTC) / t["stalled_min"] on each task dict; returns {id: since}."""
        now = time.time() if now is None else now
        with self.lock:
            if not self.seeded:
                self._seed()
        try:
            live = set(self.live())
        except Exception:
            live = set()
        try:
            ended = set(self.ended())
        except Exception:
            ended = set()
        found = stalled(tasks, live, self.root, now, ended=ended)
        fresh = []
        with self.lock:
            for tid in list(self.reported):
                if tid not in found:                      # moving again (or finished): a later stall is reported again
                    del self.reported[tid]
            for tid, since in found.items():
                if self.reported.get(tid) != int(since):
                    self.reported[tid] = int(since)
                    fresh.append(tid)
        for t in tasks:
            if not isinstance(t, dict):
                continue
            since = found.get(t.get("id"))
            t["stalled"] = since is not None
            if since is not None:
                t["stalled_since"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
                t["stalled_min"] = int((now - since) // 60)
            else:
                t.pop("stalled_since", None)
                t.pop("stalled_min", None)
        for t in tasks:
            if isinstance(t, dict) and t.get("id") in fresh:
                self._event(t, found[t["id"]], now)
        return found

    def _event(self, t, since, now):
        m = OUT_REF.search(t.get("note") or "")
        line = {"ts": int(now * 1000), "event": "stalled", "task": t["id"], "title": str(t.get("title") or "")[:120],
                "team": t.get("team") or "", "progress": t.get("progress"), "out": m[1] if m else "",
                "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)), "minutes": int((now - since) // 60)}
        try:
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass                                          # the feed is best effort, like the hook
