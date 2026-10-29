"""Watch every Claude Code session on this computer, so the office lights up whenever Claude is working.

Claude Code writes a live log of each session to ~/.claude/projects/<folder>/<session>.jsonl, and of each sub-agent
to <session>/subagents/agent-<id>.jsonl with a .meta.json beside it ({"agentType", "description", "finished"}).
This happens for every folder, so the office also sees work started outside the Agents HQ folder (for example a
Claude session opened on D:\\ to edit a sermon). The hook feed (hq/events.jsonl) only covers sessions inside the
office folder; the server merges both.

Read-only: it never writes to ~/.claude. Set HQ_WATCH_CLAUDE=0 to turn it off, CLAUDE_CONFIG_DIR to point elsewhere.

    scan(now=None, agent_names=()) -> {"running": {agent: count}, "text": {agent: str}, "sessions": [...]}
"""
import glob, json, os, re, time

ACTIVE_SECONDS = 20          # a session log touched this recently is working
PENDING_SECONDS = 30 * 60    # a tool still waiting for its result counts as working for this long (renders take minutes)
SUBAGENT_SECONDS = 15 * 60   # an unfinished sub-agent whose log moved within this window is running
TAIL_BYTES = 96 * 1024

# a skill or a script tells us which desk in the office is doing the work
SKILL_AGENT = {"reel": "clip-editor", "yellow-serif": "clip-editor", "poster-kinetic": "clip-editor", "sermon-moments": "clip-editor", "caption-card": "clip-editor", "neon-glow": "clip-editor","pixel": "thumbnail-designer", "quill": "script-writer",
               "radar": "trend-scout", "relay": "copywriter", "pulse": "data-analyst", "edit-clips": "creative-director",
               "script": "script-writer", "whats-next": "trend-scout", "post-copy": "copywriter", "stats": "data-analyst",
               "research": "research-director", "campaign": "social-media-manager", "brief": "chief of staff"}
SCRIPT_AGENT = [(re.compile(r"skills[\\/](reel|yellow-serif|poster-kinetic|sermon-moments|caption-card|neon-glow)[\\/]"), "clip-editor"),
                (re.compile(r"skills[\\/]pixel[\\/]"), "thumbnail-designer"),
                (re.compile(r"\bffmpeg\b|\bffprobe\b"), "clip-editor"),
                (re.compile(r"hq[\\/]tasks\.js"), "chief of staff")]
# an agent type Claude Code invents (general-purpose, Explore…) is placed by the words of its task
WORD_AGENT = [(re.compile(r"clip|video|edit|caption|subtitle|reel|字幕|剪|视频|影片|sermon|讲道", re.I), "clip-editor"),
              (re.compile(r"thumbnail|cover|封面", re.I), "thumbnail-designer"),
              (re.compile(r"script|hook|脚本|文案", re.I), "script-writer"),
              (re.compile(r"research|market|competitor|trend|调研", re.I), "market-analyst"),
              (re.compile(r"brand|review|check", re.I), "brand-checker"),
              (re.compile(r"post|caption copy|title|hashtag", re.I), "copywriter"),
              (re.compile(r"stat|analytic|report|数据", re.I), "data-analyst"),
              (re.compile(r"code|bug|test|build|app|server", re.I), "engineering-lead"),
              (re.compile(r"email|inbox|reply|邮件", re.I), "inbox-manager")]


def claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def place(agent_type, words, names):
    """Which office agent a Claude Code agent type (plus its task words) belongs to."""
    if agent_type in names:
        return agent_type
    for rx, who in WORD_AGENT:
        if rx.search(words or ""):
            return who
    return "chief of staff"


def tail_lines(path, size=TAIL_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if end > size and lines:
        lines = lines[1:]                                     # the first line is cut in half
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def session_state(path, names, now):
    """What one main session is doing: pending tools mapped to agents, and the prompt it is working on."""
    recs = tail_lines(path)
    uses, done, prompt, title = {}, set(), "", ""
    for r in recs:
        t = r.get("type")
        if t == "last-prompt":
            prompt = r.get("lastPrompt") or prompt
        elif t == "ai-title":
            title = r.get("aiTitle") or title
        content = (r.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if t == "assistant" and b.get("type") == "tool_use":
                uses[b.get("id")] = (b.get("name") or "", b.get("input") or {})
            elif t == "user" and b.get("type") == "tool_result":
                done.add(b.get("tool_use_id"))
    pending = [(k, v) for k, v in uses.items() if k not in done]
    return pending, (prompt or title).strip()


def scan(now=None, agent_names=()):
    now = now or time.time()
    names = set(agent_names)
    running, text, sessions = {}, {}, []
    if os.environ.get("HQ_WATCH_CLAUDE", "1") in ("0", "false"):
        return {"running": running, "text": text, "sessions": sessions}
    base = os.path.join(claude_dir(), "projects")

    def light(who, words):
        running[who] = running.get(who, 0) + 1
        if words and who not in text:
            text[who] = re.sub(r"\s+", " ", str(words)).strip()[:60]

    seen_tool_ids = set()
    # sub-agents first: their meta says exactly what they are and whether they finished
    for meta in glob.glob(os.path.join(base, "*", "*", "subagents", "agent-*.meta.json")):
        log = meta[: -len(".meta.json")] + ".jsonl"
        try:
            if now - os.path.getmtime(log) > SUBAGENT_SECONDS:
                continue
            with open(meta, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("finished"):
            continue
        desc = m.get("description") or ""
        light(place(m.get("agentType") or "", desc, names), desc)
        if m.get("toolUseId"):
            seen_tool_ids.add(m["toolUseId"])

    for path in glob.glob(os.path.join(base, "*", "*.jsonl")):
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age > PENDING_SECONDS:
            continue
        pending, prompt = session_state(path, names, now)
        if age > ACTIVE_SECONDS and not pending:
            continue                                          # finished its turn and went quiet
        sessions.append({"session": os.path.basename(path)[:-6], "folder": os.path.basename(os.path.dirname(path)), "prompt": prompt[:80]})
        light("chief of staff", prompt or "working")
        for tid, (tool, inp) in pending:
            if tid in seen_tool_ids:
                continue
            if tool in ("Agent", "Task"):
                desc = inp.get("description") or inp.get("prompt") or ""
                light(place(inp.get("subagent_type") or "", desc, names), desc)
            elif tool == "Skill":
                who = SKILL_AGENT.get(str(inp.get("skill") or "").split(":")[-1])
                if who:
                    light(who, inp.get("args") or inp.get("skill"))
            elif tool == "Bash":
                cmd = str(inp.get("command") or "")
                for rx, who in SCRIPT_AGENT:
                    if rx.search(cmd):
                        light(who, inp.get("description") or cmd)
                        break
    if running.get("chief of staff", 0) > 1:
        running["chief of staff"] = 1                         # several sessions still mean one lead at the front desk
    return {"running": running, "text": text, "sessions": sessions}


if __name__ == "__main__":
    print(json.dumps(scan(), ensure_ascii=False, indent=1))
