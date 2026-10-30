"""Scripts first: before a long RAW is cut, the owner sees the passages the office picked and decides.

The editor transcribes the RAW once and writes out/<name>/scripts.json: the picks it wants to make (as many as the owner asked
for) plus two spares, each with the exact words from the RAW. The footage task moves to review with "scripts:<name>" in its
note, and the board shows the Scripts card: the owner keeps, swaps, trims or asks for different picks, then presses Make
videos. Each kept pick becomes its own video with its own package (script · video · caption · thumbnail → READY) and its
words kept in out/<video>/script.md, so the title, caption and thumbnail are written from the words the owner approved.

scripts.json: {"source": "inbox/<file>", "channel": "<key or empty>", "package": "full", "want": 3, "language": "zh",
               "picks": [{"id": "p1", "name": "<slug>", "title": "...", "start": s, "end": s, "why": "...", "text": "...",
                          "status": "keep" | "spare" | "dropped", "trim": "the owner's note"}, ...],
               "made_at": null | time, "videos": ["<out folder>", ...]}
"""
import json
import os
import re
import time

from sermon_design import DesignError

SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,120}$")
STATUSES = ("keep", "spare", "dropped")
MARK = re.compile(r"(?:^|\s)scripts:([^\s,;]+)")


class Scripts:
    def __init__(self, root, task_action, load_tasks, start_job):
        self.root, self.task_action, self.load_tasks, self.start_job = root, task_action, load_tasks, start_job

    def _file(self, name):
        if not (isinstance(name, str) and SAFE.match(name)):
            raise DesignError("No such scripts.", 404)
        return os.path.join(self.root, "out", name, "scripts.json")

    def read(self, name):
        """The scripts of out/<name>, or None when the editor has not written them yet."""
        try:
            with open(self._file(name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, DesignError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("picks"), list):
            return None
        picks = []
        for i, p in enumerate(data["picks"]):
            if not isinstance(p, dict):
                continue
            picks.append({"id": str(p.get("id") or f"p{i + 1}"), "name": str(p.get("name") or f"part-{i + 1}")[:60],
                          "title": str(p.get("title") or "")[:120], "start": p.get("start"), "end": p.get("end"),
                          "why": str(p.get("why") or "")[:300], "text": str(p.get("text") or "")[:4000],
                          "status": p.get("status") if p.get("status") in STATUSES else "spare", "trim": str(p.get("trim") or "")[:400]})
        want = data.get("want") if isinstance(data.get("want"), int) and 1 <= data["want"] <= 8 else 3
        return {"name": name, "source": str(data.get("source") or ""), "channel": str(data.get("channel") or ""),
                "package": data.get("package") if data.get("package") in ("video", "caption", "full") else "full",
                "want": want, "picks": picks, "made_at": data.get("made_at"), "videos": [v for v in data.get("videos") or [] if isinstance(v, str)]}

    def _write(self, name, data):
        path = self._file(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def task_name(task):
        """The out/ folder whose scripts a task shows, from scripts:<name> in its note."""
        m = MARK.search(task.get("note") or "")
        return m[1].strip("/") if m else None

    def for_task(self, task):
        name = self.task_name(task)
        return self.read(name) if name else None

    def action(self, body):
        name, act = body.get("name"), body.get("action")
        data = self.read(name)
        if not data:
            raise DesignError("The scripts are not there yet.", 404)
        if data["made_at"]:
            raise DesignError("The videos are already being made from these scripts.", 409)
        pick = next((p for p in data["picks"] if p["id"] == body.get("pick")), None)
        if act in ("keep", "spare", "dropped"):
            if not pick:
                raise DesignError("No such pick.", 404)
            pick["status"] = act
        elif act == "trim":
            if not pick:
                raise DesignError("No such pick.", 404)
            trim = body.get("trim")
            if not isinstance(trim, str) or len(trim) > 400:
                raise DesignError("Keep the note under 400 characters.", 400)
            pick["trim"] = " ".join(trim.split())
        elif act == "go":
            keep = [p for p in data["picks"] if p["status"] == "keep"]
            if not keep:
                raise DesignError("Keep at least one script first.", 409)
            data["made_at"] = time.time()
            self._write(name, data)
            self.start_job(self.go_prompt(data, body.get("task")))
            return data
        else:
            raise DesignError("Unknown action.", 400)
        self._write(name, data)
        return data

    @staticmethod
    def go_prompt(data, task_id=None):
        """The lead's instruction for Make videos: one video per kept script, its own package, its words kept."""
        keep = [p for p in data["picks"] if p["status"] == "keep"]
        lines = []
        for p in keep:
            trim = f' The owner\'s note on this one (follow it): "{p["trim"]}".' if p.get("trim") else ""
            lines.append(f'- {p["id"]} "{p["title"]}" ({p["start"]}-{p["end"]} s, folder out/{p["name"]}).{trim}')
        ch = f" Channel key: {data['channel']}." if data["channel"] else ""
        return (f"Make videos from the approved scripts in out/{data['name']}/scripts.json (source {data['source']}; package {data['package']}).{ch} "
                f"Follow the edit-clips command's Make videos step: {len(keep)} video(s), one clip-editor each in the same message, one board task per video "
                f"(\"Video · <title>\", --note \"out:<folder>" + (" scripts-task:" + task_id if task_id else "") + "\"), each cut to exactly its script's range "
                f"(plus the owner's note), rendered in the channel's caption style, with the script's words kept in out/<folder>/script.md. Nothing is posted.\n"
                + "\n".join(lines))
