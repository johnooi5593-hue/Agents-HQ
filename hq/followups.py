"""After-approval follow-ups.

A work folder in out/<name>/ may carry a followups.json:

    {"title": "...", "output": "<name>-cover-post",
     "steps": [{"title": "...", "team": "Creative", "agent": "thumbnail-designer", "brief": "..."},
               {"title": "...", "team": "Shop", "agent": "copywriter", "brief": "..."}]}

When the owner approves that folder (Work screen, a board task with note out:<name>, the phone, or the chief
of staff calling /api/approve), out/<name> moves to approved/<name> as before. Then this module:
  1. adds one board task per step (the first one "doing", the rest "todo"),
  2. sends the chief of staff one message that runs the steps in order, without another OK in between.
If the chief of staff is busy, the message waits and is retried every few seconds; the state lives in the
followups.json itself (queued_at, sent_at), so a restart of the app resumes it. Each step's result still
waits for the owner's own OK. Nothing is published.
"""
import datetime, json, os, sys, threading, time

SPEC = "followups.json"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class FollowUps:
    def __init__(self, root, start_lead, add_task, interval=8):
        self.root, self.start_lead, self.add_task, self.interval = root, start_lead, add_task, interval
        self.lock = threading.Lock()
        self.thread = None

    def _path(self, name):
        return os.path.join(self.root, "approved", name, SPEC)

    def _load(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(spec, dict) or not isinstance(spec.get("steps"), list) or not spec["steps"]:
            return None
        return spec

    def _save(self, name, spec):
        path = self._path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)

    def approved(self, name):
        """out/<name> was just approved. Queue its follow-up once. Returns True when something was queued."""
        with self.lock:
            spec = self._load(name)
            if not spec or spec.get("queued_at"):
                return False
            output = spec.get("output") or f"{name}-cover-post"
            ids = []
            for i, step in enumerate(spec["steps"]):
                task = self.add_task(title=str(step.get("title") or f"Follow-up {i + 1}: {name}")[:200],
                                     team=str(step.get("team") or "Creative"), agent=str(step.get("agent") or ""),
                                     status="doing" if i == 0 else "todo", kind="task",
                                     note=f"out:{output}", subtitle="started after your OK" if i == 0 else "waits for the step before")
                ids.append(task["id"])
            spec["task_ids"], spec["queued_at"], spec["output"] = ids, now_iso(), output
            self._save(name, spec)
        self.kick()
        return True

    def prompt(self, name, spec):
        lines = [f'The owner approved the video in approved/{name}/ ({", ".join(sorted(os.listdir(os.path.join(self.root, "approved", name))))}).',
                 f'Run its after-approval follow-up now, without asking for another OK in between, and keep the board current.',
                 f'Write every new file into out/{spec["output"]}/ (create it). Do not change anything inside approved/{name}/.', '']
        for i, step in enumerate(spec["steps"]):
            tid = (spec.get("task_ids") or [None] * len(spec["steps"]))[i]
            who = step.get("agent") or "the right agent"
            lines.append(f'Step {i + 1} of {len(spec["steps"])} (board task {tid}, agent {who}): {step.get("brief", "").strip()}')
            lines.append('')
        lines += ['Run the steps in order: a later step uses the files of the step before it.',
                  'When a step starts, run node hq/tasks.js move TASKID doing; when its files are ready, run node hq/tasks.js move TASKID review '
                  f'(the tasks already carry note out:{spec["output"]}, so the owner approves them in the app).',
                  'Report the file paths in two or three lines. Nothing is published, posted, uploaded or scheduled.']
        # One line, no characters cmd.exe treats specially: on Windows the engine starts claude through claude.cmd,
        # and cmd.exe cuts an argument at its first line break (the rest of the command line, flags included, is lost).
        text = " ".join(line.strip() for line in lines if line.strip())
        for bad, good in (('"', "'"), ("<", "("), (">", ")"), ("&", "and"), ("|", "/"), ("^", ""), ("%", " percent"), ("\r", " "), ("\n", " ")):
            text = text.replace(bad, good)
        return text

    def kick(self):
        """Send every queued, unsent follow-up to the chief of staff while it is free."""
        base = os.path.join(self.root, "approved")
        if not os.path.isdir(base):
            return
        with self.lock:
            for name in sorted(os.listdir(base)):
                spec = self._load(name) if os.path.isfile(self._path(name)) else None
                if not spec or not spec.get("queued_at") or spec.get("sent_at"):
                    continue
                run = self.start_lead(self.prompt(name, spec))
                if not run:
                    return                      # the chief of staff is busy: try again on the next tick
                spec["sent_at"], spec["run_id"] = now_iso(), getattr(run, "id", None)
                self._save(name, spec)

    def _loop(self):
        while True:
            try:
                self.kick()
            except Exception as e:              # never take the office down over a follow-up
                sys.stderr.write(f"follow-ups: {e}\n")
            time.sleep(self.interval)

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
