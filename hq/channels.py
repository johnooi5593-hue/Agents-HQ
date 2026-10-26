"""Channels: the brands Agents HQ works for, and the Google Drive folder each one's raw footage arrives in.

The main channel uses the brain's "Company" and "Brand rules", inbox/ and the posting accounts it always had. Every other
channel has its own brain entities ("<name> · Company", "<name> · Brand rules"), its own inbox/<key>/ folder and its own
posting accounts. The list lives in .hq-channels.json (the owner's, never in git).

A Drive folder is a folder Google Drive for desktop syncs to this computer (G:\\My Drive\\…). New videos there are copied
(never moved, never deleted) into the channel's inbox, and each one becomes a "New footage" task that waits for the owner's
Edit button.
"""
import json, os, re, shutil, threading, time

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
RESERVED = {"radar", "stats", "messages", "channels", "done"}
SETTLE = 60                                         # seconds a file must stay unchanged: Drive may still be downloading it


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40]
    return s or "channel"


def safe_file(name):
    base, ext = os.path.splitext(os.path.basename(name))
    base = re.sub(r"[^A-Za-z0-9 ._()\-]+", "-", base).strip(" .-")[:100] or "clip"
    return base + ext.lower()


class Channels:
    def __init__(self, root, add_task=None, add_brain=None):
        self.root, self.path = root, os.path.join(root, ".hq-channels.json")
        self.ledger_path = os.path.join(root, ".hq-imported.json")
        self.add_task, self.add_brain = add_task, add_brain
        self.lock, self.seen = threading.Lock(), {}

    # ------------------------------------------------------------------ the list
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d.setdefault("main", {"name": "", "drive": ""})
        d.setdefault("channels", [])
        return d

    def save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, key):
        """The channel with that key ("" is the main one), or None."""
        d = self.load()
        if not key:
            return dict(d["main"], key="")
        return next((dict(c) for c in d["channels"] if c.get("key") == key), None)

    def name(self, key):
        c = self.get(key)
        return (c or {}).get("name") or ("Main channel" if not key else key)

    def brain_names(self, key):
        """The brain entities a channel's agents read: its own Company instead of the main one, and the shared Brand rules
        (the same procedures for every channel) with the channel's own rules on top."""
        if not key:
            return ["Company", "Brand rules"]
        n = self.name(key)
        return [f"{n} · Company", "Brand rules", f"{n} · Brand rules"]

    def footage_task(self, rel, key):
        """A New footage task: the video waits in the inbox for the owner's Edit button."""
        if self.add_task:
            label = os.path.splitext(os.path.basename(rel))[0]
            who = f" ({self.name(key)})" if key else ""
            self.add_task(title=f"New footage · {label}{who}", team="Creative", status="todo",
                          note=(f"channel:{key} " if key else "") + f"inbox:{rel}")   # the path last: it may hold spaces

    def inbox(self, key):
        return os.path.join(self.root, "inbox", key) if key else os.path.join(self.root, "inbox")

    def payload(self):
        d = self.load()
        out = [dict(d["main"], key="", main=True)] + [dict(c, main=False) for c in d["channels"]]
        for c in out:
            c["drive_ok"] = bool(c.get("drive")) and os.path.isdir(c["drive"])
            c["brain"] = self.brain_names(c["key"])
        return {"channels": out}

    def add(self, name, about="", drive=""):
        name = re.sub(r"\s+", " ", str(name or "")).strip()[:60]
        if not name:
            raise ValueError("give the channel a name")
        drive = self.check_drive(drive)
        with self.lock:
            d = self.load()
            names = [d["main"].get("name", "").lower()] + [c.get("name", "").lower() for c in d["channels"]]
            if name.lower() in names:
                raise ValueError("there is already a channel with that name")
            key, n = slug(name), 2
            while key in RESERVED or any(c.get("key") == key for c in d["channels"]):
                key, n = f"{slug(name)}-{n}", n + 1
            d["channels"].append({"key": key, "name": name, "drive": drive, "at": int(time.time())})
            self.save(d)
        os.makedirs(self.inbox(key), exist_ok=True)
        if self.add_brain:                               # the new brand's own memory, for the chief of staff to fill in
            about = str(about or "").strip()[:600]
            self.add_brain(f"{name} · Company", "company",
                           [about] if about else [f"Not set up yet. Owner: tell the chief of staff what {name} is about, who it is for and how it should sound."])
            self.add_brain(f"{name} · Brand rules", "style_guide",
                           [f"{name} works with the same procedures as the main channel: follow every rule in \"Brand rules\" too (format, "
                            f"length, captions, covers, posting). Rules saved here are {name}'s own and win where they differ. Never use the "
                            f"main channel's name, logo, slogans or hashtags for {name}."])
        return key

    def update(self, key, name=None, drive=None):
        with self.lock:
            d = self.load()
            c = d["main"] if not key else next((c for c in d["channels"] if c.get("key") == key), None)
            if c is None:
                raise ValueError("no such channel")
            if drive is not None:
                c["drive"] = self.check_drive(drive)
            if name is not None and not key:                 # the main channel's display name; others keep theirs (the brain uses it)
                c["name"] = re.sub(r"\s+", " ", str(name)).strip()[:60]
            self.save(d)

    @staticmethod
    def check_drive(drive):
        drive = str(drive or "").strip().strip('"')
        if drive and not os.path.isdir(drive):
            raise ValueError(f"this computer has no folder {drive}. Is Google Drive for desktop running? Copy the folder's path from File Explorer")
        return drive

    # ------------------------------------------------------------------ the Drive watcher
    def ledger(self):
        try:
            with open(self.ledger_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def scan(self):
        """Copy the settled new videos from every channel's Drive folder into its inbox. Returns what was imported."""
        got = []
        d = self.load()
        for c in [dict(d["main"], key="")] + d["channels"]:
            src = c.get("drive")
            if not src or not os.path.isdir(src):
                continue
            try:
                names = sorted(os.listdir(src))
            except OSError:
                continue
            for fn in names:
                p = os.path.join(src, fn)
                if os.path.splitext(fn)[1].lower() not in VIDEO_EXT or fn.startswith((".", "~")) or not os.path.isfile(p):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sig = f"{st.st_size}:{int(st.st_mtime)}"
                led = self.ledger()
                if led.get(p) == sig or st.st_size == 0:
                    continue
                if self.seen.get(p) != sig or time.time() - st.st_mtime < SETTLE:
                    self.seen[p] = sig                     # look again next round: still syncing?
                    continue
                dst_dir = self.inbox(c["key"])
                os.makedirs(dst_dir, exist_ok=True)
                name = safe_file(fn)
                base, ext = os.path.splitext(name)
                k = 2
                while os.path.exists(os.path.join(dst_dir, name)) or os.path.exists(os.path.join(self.root, "done", name)):
                    name, k = f"{base} ({k}){ext}", k + 1
                tmp = os.path.join(dst_dir, name + ".part")
                try:
                    shutil.copyfile(p, tmp)                  # a copy: the Drive file stays where the owner put it
                    os.replace(tmp, os.path.join(dst_dir, name))
                except OSError as e:
                    print("drive import:", fn, e)
                    continue
                with self.lock:
                    led = self.ledger()
                    led[p] = sig
                    tmp = self.ledger_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(led, f, indent=1, ensure_ascii=False)
                    os.replace(tmp, self.ledger_path)
                rel = os.path.relpath(os.path.join(dst_dir, name), self.root).replace(os.sep, "/")
                got.append(rel)
                self.footage_task(rel, c["key"])
        return got

    def run_watcher(self, every=30):
        def loop():
            while True:
                try:
                    self.scan()
                except Exception as e:                        # keep watching whatever one folder does
                    print("drive watcher:", e)
                time.sleep(every)
        threading.Thread(target=loop, daemon=True).start()


def folder_channel(folder):
    """The channel a work folder belongs to: channel.txt in it (or in the clip folder above a topic), else the main one."""
    for d in (folder, os.path.dirname(folder)):
        try:
            with open(os.path.join(d, "channel.txt"), encoding="utf-8") as f:
                key = f.read().strip()
            if re.match(r"^[a-z0-9][a-z0-9-]{0,50}$", key):
                return key
        except OSError:
            continue
    return ""
