"""Post approved work to Facebook, Instagram and YouTube, only when the owner presses Post in the app.

Agents never call this: the office makes the work, the owner approves it, and the owner's Post button is the only thing
that publishes. Accounts are connected once in the app (user menu → Accounts) and kept in .hq-accounts.json in the
office folder: on this computer only, never committed, never read by the agents (.claude/settings.json denies it).

    Facebook + Instagram: one Meta app (developers.facebook.com) with Facebook Login for Business. The owner pastes the
        App ID, the App secret and a user token from the Graph API Explorer; we swap it for a long-lived one and keep
        the Page token (it does not expire) and the Instagram professional account linked to that Page.
    YouTube: a Google Cloud OAuth client of type "Desktop app". The owner pastes its client_secret.json, signs in
        once in the browser, and we keep the refresh token. Google keeps uploads from a new, unaudited API project
        private until the project passes Google's audit; the app says so after each upload.

Stdlib only. Every post writes approved/<name>/posted.json as it goes, so the app shows progress and links.
"""
import json, math, os, re, secrets, shutil, subprocess, tempfile, threading, time, urllib.error, urllib.parse, urllib.request

from channels import folder_channel

GRAPH = "https://graph.facebook.com/v23.0"
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PLATFORMS = ("facebook", "instagram", "youtube")
VIDEO_EXT = (".mp4", ".mov", ".m4v")


class PostError(Exception):
    pass


PROGRESS = threading.local()                                   # the post this thread works on: progress() shows on its row


def progress(pct, step=""):
    """How far this thread's post is (0-99) and what it is doing, for the owner's Posting… row."""
    report = getattr(PROGRESS, "report", None)
    if report:
        report(pct, step)


class Sending:
    """A video file going up: http.client reads it in blocks, and each block moves the % from lo to hi."""

    def __init__(self, f, size, lo, hi, step="uploading the video"):
        self.f, self.size, self.lo, self.hi, self.step, self.sent = f, max(1, size), lo, hi, step, 0

    def read(self, n=-1):
        block = self.f.read(n)
        self.sent += len(block)
        progress(self.lo + (self.hi - self.lo) * self.sent / self.size, self.step)
        return block


def http(method, url, data=None, headers=None, body=None, timeout=120):
    """One HTTP call. data: dict sent as a form; body: bytes or a file object (with Content-Length in headers)."""
    headers = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, dict(r.headers), (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
            err = j.get("error")
            msg = (err.get("message") if isinstance(err, dict) else None) or j.get("error_description") or err or raw
        except ValueError:
            msg = raw[:300]
        raise PostError(f"{e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise PostError(f"no connection ({e.reason})") from None


META_PERMS = ("pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic", "instagram_content_publish")


def meta_error(e):
    """A Meta permission error in plain words: which box to tick and where."""
    msg = str(e)
    for perm in META_PERMS:
        if perm in msg:
            return PostError(f"the Meta token is missing the {perm} permission. In Graph API Explorer, Get User Access Token again "
                             f"with {perm} ticked, then paste the new token in Accounts for posting → Facebook & Instagram → Connect. ({msg})")
    return e


def duration(video):
    """The video's length in seconds (from ffmpeg's banner), or None."""
    ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ff:
        return None
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", video], capture_output=True, text=True, timeout=60,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        h, mi, sec = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr).groups()
        return int(h) * 3600 + int(mi) * 60 + float(sec)
    except (OSError, subprocess.SubprocessError, AttributeError):
        return None


def ig_ready(video):
    """An Instagram-ready copy of the video, to Meta's Reels rules (H.264 with closed GOPs, AAC 128k 48 kHz, at most 25 Mbps,
    index at the front, no edit lists: ffmpeg writes those by default and Instagram refuses them), or None without ffmpeg."""
    ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ff:
        return None
    fd, out = tempfile.mkstemp(prefix="hq-ig-", suffix=".mp4")
    os.close(fd)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "20M", "-bufsize", "40M", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", "-use_editlist", "0", out]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=1800, creationflags=0x08000000 if os.name == "nt" else 0)
        if r.returncode == 0 and os.path.getsize(out) > 0:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        os.remove(out)
    except OSError:
        pass
    return None


def cover_jpeg(cover):
    """The owner's thumbnail as a JPEG every platform takes (YouTube wants at most 2 MB, Instagram's cover is a JPEG,
    a Codex pick is a large PNG), or None without ffmpeg. The picked file itself stays as it is."""
    ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not cover or not ff or not os.path.isfile(cover):
        return None
    fd, out = tempfile.mkstemp(prefix="hq-cover-", suffix=".jpg")
    os.close(fd)
    for q, scale in ((2, None), (4, None), (5, "1080:-2")):   # smaller only when it has to be
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", cover, "-frames:v", "1", "-q:v", str(q)] + (["-vf", "scale=" + scale] if scale else []) + [out]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=0x08000000 if os.name == "nt" else 0)
            if r.returncode == 0 and 0 < os.path.getsize(out) <= 2 * 1024 * 1024:
                return out
        except (OSError, subprocess.SubprocessError):
            break
    try:
        os.remove(out)
    except OSError:
        pass
    return None


def multipart(fields, name, filename, data, ctype="image/jpeg"):
    """A multipart/form-data body with plain fields and one file: (body, headers)."""
    b = "hq" + secrets.token_hex(8)
    body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in fields.items())
    body += f"--{b}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={b}"}


class Accounts:
    def __init__(self, root):
        self.path = os.path.join(root, ".hq-accounts.json")
        self.lock = threading.Lock()
        self.pending = {}                                   # YouTube sign-in: state -> (client_id, client_secret, redirect)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def section(a, channel=""):
        """The accounts of one channel inside the file: the main channel at the top level, the others under "channels"."""
        return a if not channel else (a.get("channels") or {}).get(channel) or {}

    @staticmethod
    def slot(a, channel=""):
        return a if not channel else a.setdefault("channels", {}).setdefault(channel, {})

    def get(self, kind, channel=""):
        return self.section(self.load(), channel).get(kind) or {}

    def summary(self, channel=""):
        """What the app may show: names only, never a token."""
        a = self.section(self.load(), channel)
        m, y = a.get("meta") or {}, a.get("youtube") or {}
        return {
            "facebook": {"connected": bool(m.get("page_token")), "name": m.get("page_name", "")},
            "instagram": {"connected": bool(m.get("page_token") and m.get("ig_id")), "name": ("@" + m["ig_username"]) if m.get("ig_username") else "",
                          "problem": "" if not m.get("page_token") or m.get("ig_id") else "no Instagram professional account is linked to this Facebook Page"},
            "youtube": {"connected": bool(y.get("refresh_token")), "name": y.get("channel", ""), "client": bool(y.get("client_id"))},
        }

    # ---------------------------------------------------------------- Meta
    def connect_meta(self, app_id, app_secret, user_token, page="", channel=""):
        app_id, app_secret, user_token = (str(x or "").strip() for x in (app_id, app_secret, user_token))
        if not (app_id and app_secret):                     # another channel may use the same Meta app: only a new token needed
            known = self.get("meta", channel) or self.get("meta")
            app_id, app_secret = app_id or known.get("app_id", ""), app_secret or known.get("app_secret", "")
        if not (app_id and app_secret and user_token):
            raise PostError("App ID, App secret and the token are all needed")
        _, _, j = http("GET", f"{GRAPH}/oauth/access_token?" + urllib.parse.urlencode(
            {"grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret, "fb_exchange_token": user_token}))
        long_user = j.get("access_token") if isinstance(j, dict) else None
        if not long_user:
            raise PostError("Facebook did not return a long-lived token")
        _, _, j = http("GET", f"{GRAPH}/me/accounts?" + urllib.parse.urlencode(
            {"fields": "id,name,access_token,instagram_business_account{id,username}", "access_token": long_user, "limit": 100}))
        pages = (j or {}).get("data") or []
        if not pages:
            raise PostError("this Facebook user manages no Pages, or the token lacks pages_show_list")
        want = str(page or "").strip().lower()
        chosen = next((p for p in pages if want and (want == p.get("id") or want in p.get("name", "").lower())), pages[0])
        ig = chosen.get("instagram_business_account") or {}
        missing = []
        try:                                                # what the token may do: posting fails later without these
            _, _, pj = http("GET", f"{GRAPH}/me/permissions?" + urllib.parse.urlencode({"access_token": long_user}))
            granted = {x.get("permission") for x in (pj or {}).get("data") or [] if x.get("status") == "granted"}
            missing = [x for x in META_PERMS if x not in granted]
        except PostError:
            pass
        with self.lock:
            a = self.load()
            self.slot(a, channel)["meta"] = {"app_id": app_id, "app_secret": app_secret, "user_token": long_user, "page_id": chosen["id"],
                         "page_name": chosen.get("name", ""), "page_token": chosen["access_token"],
                         "ig_id": ig.get("id", ""), "ig_username": ig.get("username", ""), "at": int(time.time())}
            self.save(a)
        return {"page": chosen.get("name"), "pages": [p.get("name") for p in pages], "instagram": ig.get("username", ""), "missing": missing}

    # ---------------------------------------------------------------- YouTube
    def youtube_begin(self, client_json, redirect, channel=""):
        """Start the Google sign-in. client_json: the downloaded client_secret.json (or its text); without it the channel's
        (or the main channel's) Google client is used again. Returns the URL to open."""
        y = self.get("youtube", channel) or self.get("youtube")
        cid, csec = y.get("client_id"), y.get("client_secret")
        if client_json:
            try:
                c = json.loads(client_json) if isinstance(client_json, str) else client_json
                c = c.get("installed") or c.get("web") or c
                cid, csec = c["client_id"], c["client_secret"]
            except (ValueError, KeyError, TypeError, AttributeError):
                raise PostError("that is not a Google OAuth client file (client_secret_….json, type Desktop app)") from None
        if not (cid and csec):
            raise PostError("paste the client_secret.json of a Desktop app OAuth client first")
        state = secrets.token_urlsafe(16)
        self.pending = {state: (cid, csec, redirect, time.time(), channel)}
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": YT_SCOPES,
            "access_type": "offline", "prompt": "consent", "state": state})

    def youtube_finish(self, state, code):
        got = self.pending.pop(state, None) if state else None
        if not got or time.time() - got[3] > 900:
            raise PostError("this sign-in link expired; press Connect YouTube again")
        cid, csec, redirect, _, channel = got
        _, _, j = http("POST", "https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": cid, "client_secret": csec, "redirect_uri": redirect, "grant_type": "authorization_code"})
        if not j.get("refresh_token"):
            raise PostError("Google gave no refresh token; remove Agents HQ at myaccount.google.com/permissions and connect again")
        channel = ""
        try:
            _, _, c = http("GET", "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                           headers={"Authorization": "Bearer " + j["access_token"]})
            channel = ((c.get("items") or [{}])[0].get("snippet") or {}).get("title", "")
        except PostError:
            pass
        with self.lock:
            a = self.load()
            self.slot(a, channel)["youtube"] = {"client_id": cid, "client_secret": csec, "refresh_token": j["refresh_token"], "channel": channel, "at": int(time.time())}
            self.save(a)
        return channel

    def youtube_token(self, channel=""):
        y = self.get("youtube", channel)
        if not y.get("refresh_token"):
            raise PostError("YouTube is not connected")
        _, _, j = http("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": y["client_id"], "client_secret": y["client_secret"], "refresh_token": y["refresh_token"], "grant_type": "refresh_token"})
        return j["access_token"]

    def disconnect(self, which, channel=""):
        with self.lock:
            a = self.load()
            self.slot(a, channel).pop("meta" if which in ("meta", "facebook", "instagram") else which, None)
            self.save(a)


# -------------------------------------------------------------------- the post copy
def sections(text):
    """post.md → {"options": [...], "youtube": [...], "instagram": [...], "facebook": [...], "tiktok": [...], "pinned": [...],
    "other": [...]}. "## Captions" holds the options used on every platform ("### Option 1", "### Option 2"…); a "## Platform"
    section overrides one platform. Sections with other names (older post.md files) land in "other"."""
    out, cur, opts, buf, num = {}, None, [], [], None

    def flush():
        if cur:
            opts.append((num, "\n".join(buf).strip()))
            out.setdefault(cur, []).extend({"n": n, "text": t} for n, t in opts if t)
    for line in (text or "").replace("\r", "").split("\n"):
        m2 = re.match(r"^##\s+(.*)$", line)
        m3 = re.match(r"^###\s+(.*)$", line)
        if m2:
            flush()
            h = m2[1].lower()
            cur = ("youtube" if "youtube" in h else "instagram" if "instagram" in h else "facebook" if "facebook" in h
                   else "tiktok" if "tiktok" in h else "pinned" if "pinned" in h else "plan" if re.match(r"plan\b", h)
                   else "options" if re.search(r"caption|option|标题|文案", h) else "other")
            opts, buf, num = [], [], None
        elif m3 and cur:
            if "\n".join(buf).strip():
                opts.append((num, "\n".join(buf).strip()))
            buf = []
            n = re.search(r"\d+", m3[1])
            num = int(n[0]) if n else None
        elif cur:
            buf.append(line)
    flush()
    return out


def clean(text):
    """Post text without Markdown bold and without the notes meant for us (file paths, "Video:", "For Facebook…")."""
    keep = [l for l in (text or "").split("\n")
            if not re.search(r"(approved|out|inbox)/\S+\.(mp4|mov|jpe?g|png)", l, re.I)
            and not re.match(r"^\s*[-*]?\s*(video|cover|thumbnail|file|for (facebook|instagram|youtube|tiktok)[^:：]*)\s*[:：(]", l, re.I)]
    return re.sub(r"\*\*|__", "", "\n".join(keep)).strip()


def split_title(text, fallback):
    """An option's "Title: …" line (YouTube) and the rest (the caption everywhere)."""
    t = clean(text)
    m = re.search(r"^\s*[-*]?\s*(?:youtube\s*)?title\s*[:：]\s*(.+)$", t, re.I | re.M)
    title = m[1].strip() if m else ""
    body = (t[:m.start()] + t[m.end():]) if m else t
    body = re.sub(r"^\s*[-*]?\s*(description|caption|hashtags|tags)\s*[:：]\s*", "", body, flags=re.I | re.M).strip()
    if not title:
        first = next((l.strip() for l in body.split("\n") if l.strip() and not l.strip().startswith("#")), "")
        title = first or fallback
    return title[:100], body


def drafts(folder):
    """The caption options for the posting overview. Each option fills every platform at once: the owner picks one
    (and the thumbnail) and Facebook, Instagram and YouTube all get it; they can still edit a platform's text."""
    try:
        with open(os.path.join(folder, "post.md"), encoding="utf-8") as f:
            s = sections(f.read())
    except OSError:
        s = {}
    name = os.path.basename(folder).replace("-", " ")
    common = s.get("options") or []
    if not common and not any(s.get(k) for k in ("youtube", "instagram", "facebook")):
        common = s.get("other") or []                         # an older post.md: its sections are the options
    plat = {k: s.get(k) or [] for k in ("youtube", "instagram", "facebook")}
    count = max([len(common)] + [max([e["n"] or 0 for e in v] + [len(v)]) for v in plat.values()])

    def pick(entries, i):
        """Option i+1 of a section: its "### Option N" by number, else the one text that serves every option, else by order."""
        if not entries:
            return None
        hit = next((e["text"] for e in entries if e["n"] == i + 1), None)
        if hit is not None:
            return hit
        if any(e["n"] for e in entries):
            return None                                       # numbered, but not this option: no override
        return entries[0]["text"] if len(entries) == 1 else entries[min(i, len(entries) - 1)]["text"]
    options = []
    for i in range(max(count, 1)):
        base_title, base = split_title(pick(common, i) or "", name)
        yt_src = pick(plat["youtube"], i)
        yt_title, yt_body = split_title(yt_src, base_title) if yt_src else (base_title, base)
        ig = clean(pick(plat["instagram"], i) or "") or base
        fb = clean(pick(plat["facebook"], i) or "") or base or ig
        desc = yt_body or base or ig
        if "#shorts" not in (yt_title + desc).lower():
            desc = (desc + "\n#Shorts").strip()
        options.append({"title": yt_title, "caption": base or ig or fb,
                        "youtube": {"title": yt_title, "description": desc[:4900]},
                        "instagram": {"caption": ig[:2200]}, "facebook": {"caption": fb}})
    first = options[0]
    return {"options": options, "youtube": first["youtube"], "instagram": first["instagram"], "facebook": first["facebook"]}


LINKED = re.compile(r"((?:approved|out)/[^\s`'\"()<>]+?\.(?:mp4|mov|m4v))", re.I)


def office_root(folder):
    """The office folder above an approved/ or out/ work folder."""
    p = os.path.abspath(folder)
    while p and os.path.basename(p) not in ("approved", "out"):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    return os.path.dirname(p) if p else None


def linked_videos(folder):
    """Videos another folder holds that this one's post copy or notes name (a thumbnail or copy task whose video was
    edited in the clip's own folder): "approved/<clip>/edit.mp4", or "out/<clip>/…" that has moved to approved/ since."""
    root, out = office_root(folder), []
    if not root:
        return out
    text = ""
    for name in ("post.md", "notes.md", "README.md"):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                text += f.read() + "\n"
        except OSError:
            pass
    for rel in LINKED.findall(text):
        rel = rel.replace("\\", "/").strip("/")
        for cand in (rel, "approved/" + rel[4:] if rel.startswith("out/") else None):
            full = cand and os.path.realpath(os.path.join(root, cand))
            if full and full.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(full) and cand not in out:
                out.append(cand); break
    return out


def media_files(folder):
    """Videos and images that can be posted: in the folder, else one level down (topics), else the video the post copy
    names in another folder; never in work/. `abs` maps a linked video's name to its path."""
    found = {"video": [], "image": [], "abs": {}}
    for depth in (0, 1):
        for dirpath, dirnames, filenames in os.walk(folder):
            rel = os.path.relpath(dirpath, folder)
            level = 0 if rel == "." else rel.count(os.sep) + 1
            dirnames[:] = [d for d in dirnames if d != "work" and not d.startswith(".")]
            if level != depth:
                continue
            for fn in sorted(filenames):
                path = fn if level == 0 else rel.replace(os.sep, "/") + "/" + fn
                if fn.lower().endswith(VIDEO_EXT):
                    found["video"].append(path)
                elif fn.lower().endswith((".jpg", ".jpeg", ".png")):
                    found["image"].append(path)
        if found["video"]:
            break
    if not found["video"]:
        root = office_root(folder)
        for rel in linked_videos(folder):
            found["video"].append(rel); found["abs"][rel] = os.path.join(root, rel)
    rank = lambda n: (0 if re.match(r"(edit|final|reel)\b", os.path.basename(n), re.I) else 2 if re.search(r"clean|nocap|no-captions", n, re.I)
                      else 3 if os.path.basename(n).lower().startswith("cut") else 1)
    found["video"].sort(key=rank)
    found["image"].sort(key=lambda n: (0 if os.path.basename(n).lower() == "cover-codex.png" else 1 if "cover" in os.path.basename(n).lower() else 2, n))   # the owner's Codex pick first
    return found


def media(folder):
    """The default video and cover to post."""
    f = media_files(folder)
    v = f["video"][0] if f["video"] else None
    return (f["abs"].get(v) or os.path.join(folder, v) if v else None), (os.path.join(folder, f["image"][0]) if f["image"] else None)


# -------------------------------------------------------------------- posting
SCHEDULE_MIN, SCHEDULE_MAX = 10 * 60, 28 * 86400              # Facebook wants 10 minutes ahead at least; four weeks is plenty
NATIVE_SCHEDULE = ("facebook", "youtube")                     # these publish at the time by themselves; Instagram is posted by us


class Publisher:
    """Posts now, or at a time the owner picks. Facebook and YouTube upload at once and publish at that time on their own
    (the computer may sleep); Instagram has no scheduling in its API, so the job waits in posted.json and the scheduler
    here posts it when it is due (as soon as Agents HQ runs again if the computer was off)."""

    def __init__(self, root, accounts, on_schedule=None, on_finish=None):
        self.root, self.accounts, self.lock, self.busy = root, accounts, threading.Lock(), set()
        self.gate = threading.Lock()                               # a post starting vs. the check for interrupted posts
        self.on_schedule, self.on_finish = on_schedule, on_finish     # the board: a dated "post" task, done when all went out

    def record_path(self, folder):
        return os.path.join(folder, "posted.json")

    def record(self, folder):
        try:
            with open(self.record_path(folder), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def note(self, folder, platform, **kw):
        with self.lock:
            r = self.record(folder)
            if platform.startswith("_"):
                r[platform] = kw.get("value")
            else:
                r[platform] = {**r.get(platform, {}), **kw, "at": int(time.time())}
            with open(self.record_path(folder), "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1, ensure_ascii=False)

    def reporter(self, folder, p):
        """progress() for one platform's post: written to posted.json at most once a second, or when the step changes."""
        last = {"pct": -1, "step": None, "at": 0.0}

        def report(pct, step=""):
            pct, now = int(max(0, min(99, pct))), time.time()
            if step == last["step"] and (pct == last["pct"] or now - last["at"] < 1):
                return
            last.update(pct=pct, step=step, at=now)
            self.note(folder, p, progress=pct, step=step)
        return report

    def payload(self, folder):
        f = media_files(folder)
        return {"accounts": self.accounts.summary(folder_channel(folder)), "channel": folder_channel(folder), "drafts": drafts(folder), "posted": self.record(folder),
                "videos": f["video"], "covers": f["image"], "linked": sorted(f["abs"]), "video": (f["video"] or [""])[0], "cover": (f["image"] or [""])[0],
                "busy": folder in self.busy}

    def start(self, folder, chosen, video_name="", cover_name="", when=None):
        """chosen: {platform: {text fields}}; video_name / cover_name: the files the owner picked in the folder;
        when: a unix time to publish at, or None for now. Works in the background; returns the platforms started."""
        video, cover = media(folder)
        files = media_files(folder)
        if video_name:
            if video_name not in files["video"]:
                raise PostError("that video is not in this folder")
            video = files["abs"].get(video_name) or os.path.join(folder, video_name)
        if cover_name:
            if cover_name not in files["image"]:
                raise PostError("that thumbnail is not in this folder")
            cover = os.path.join(folder, cover_name)
        if not video:
            raise PostError("no video in this folder")
        if when is not None:
            try:
                when = int(when)
            except (TypeError, ValueError):
                raise PostError("that is not a time") from None
            ahead = when - time.time()
            if ahead < SCHEDULE_MIN:
                raise PostError("pick a time at least 10 minutes from now")
            if ahead > SCHEDULE_MAX:
                raise PostError("pick a time within the next 4 weeks")
        channel = folder_channel(folder)
        summary = self.accounts.summary(channel)
        todo = [p for p in PLATFORMS if p in chosen and summary[p]["connected"]]
        if not todo:
            raise PostError("pick at least one connected account")
        done = self.record(folder)
        again = [p for p in todo if (done.get(p) or {}).get("state") in ("posted", "scheduled") and not chosen[p].get("again")]
        if again:
            raise PostError(f"already posted or scheduled to {', '.join(again)}")
        with self.gate:
            if folder in self.busy:
                raise PostError("still posting this one")
            self.busy.add(folder)
        rel = lambda path: (os.path.relpath(path, folder).replace(os.sep, "/") if os.path.dirname(os.path.abspath(path)).startswith(os.path.abspath(folder)) else os.path.relpath(path, office_root(folder) or folder).replace(os.sep, "/")) if path else ""
        for p in todo:
            self.note(folder, p, state="waiting", error="", warning="", when=when or 0, job=None, link=done.get(p, {}).get("link", ""),
                      video=rel(video), cover=rel(cover))
        if when and self.on_schedule:
            try:
                self.note(folder, "_task", value=self.on_schedule(folder, when, todo))
            except Exception:                                  # the board is a nice-to-have, never a reason not to post
                pass

        def one(p):                                             # every platform at the same time
            if when and p not in NATIVE_SCHEDULE:               # Instagram: wait here, the scheduler posts it when due
                self.note(folder, p, state="scheduled", job={"text": chosen[p], "video": rel(video), "cover": rel(cover)})
                return
            self.note(folder, p, state="posting" if not when else "uploading", error="", progress=0, step="starting")
            PROGRESS.report = self.reporter(folder, p)
            try:
                link, extra = self.send(p, video, cover, chosen[p], when, channel)
                self.note(folder, p, state="scheduled" if when else "posted", link=link, error="", **extra)
            except Exception as e:                              # one platform failing never stops the others
                self.note(folder, p, state="failed", error=str(e)[:400])
            finally:
                PROGRESS.report = None

        def work():
            try:
                threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in todo]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                self.busy.discard(folder)
                self.check_finished(folder)
        threading.Thread(target=work, daemon=True).start()
        return todo

    def send(self, p, video, cover, text, when, channel):
        """One platform, with the owner's thumbnail as a JPEG every platform takes (the picked file stays as it is)."""
        progress(1, "preparing your thumbnail")
        jpg = cover_jpeg(cover)
        try:
            return getattr(self, "post_" + p)(video, jpg or cover, text, when, channel)
        finally:
            if jpg:
                try:
                    os.remove(jpg)
                except OSError:
                    pass

    def cancel(self, folder, platform):
        """Cancel a scheduled post that is still waiting here (Instagram). Facebook and YouTube already hold theirs."""
        r = self.record(folder).get(platform) or {}
        if r.get("state") != "scheduled" or not r.get("job"):
            raise PostError("only a scheduled Instagram post waiting in Agents HQ can be cancelled here; "
                            "cancel Facebook in Meta Business Suite and YouTube in YouTube Studio")
        self.note(folder, platform, state="cancelled", job=None)
        self.check_finished(folder)

    def check_finished(self, folder):
        r = self.record(folder)
        states = [(r.get(p) or {}).get("state") for p in PLATFORMS if r.get(p)]
        if r.get("_task") and states and all(st in ("posted", "failed", "cancelled") for st in states) and self.on_finish:
            try:
                self.on_finish(folder, r["_task"], states)
            except Exception:
                pass
            self.note(folder, "_task", value=None)

    def folders(self):
        """Every approved folder (and topic) with a posted.json."""
        base = os.path.join(self.root, "approved")
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, base)
            depth = 0 if rel == "." else rel.count(os.sep) + 1        # approved/<name> is 1, approved/<name>/<topic> is 2
            dirnames[:] = [d for d in dirnames if d != "work" and not d.startswith(".")] if depth < 2 else []
            if "posted.json" in filenames:
                found.append(dirpath)
        return found

    def run_due(self, now=None):
        """Post what is due: Instagram jobs waiting here; Facebook and YouTube posts count as out once their time passed."""
        now = now or time.time()
        for folder in self.folders():
            if folder in self.busy:
                continue
            r = self.record(folder)
            for p in PLATFORMS:
                e = r.get(p) or {}
                if e.get("state") != "scheduled" or not e.get("when") or e["when"] > now:
                    continue
                if not e.get("job"):                            # the platform published it by itself
                    self.note(folder, p, state="posted")
                    continue
                job = e["job"]
                self.note(folder, p, state="posting", job=None, progress=0, step="starting")
                PROGRESS.report = self.reporter(folder, p)
                try:
                    video = os.path.join(folder, job["video"])
                    if not os.path.isfile(video) and office_root(folder):
                        video = os.path.join(office_root(folder), job["video"])
                    cover = os.path.join(folder, job["cover"]) if job.get("cover") else None
                    link, extra = self.send(p, video, cover, job["text"], None, folder_channel(folder))
                    late = now - e["when"] > 15 * 60
                    self.note(folder, p, state="posted", link=link, error="",
                              warning=("Posted late: the computer or Agents HQ was off at the scheduled time." if late else ""), **extra)
                except Exception as ex:
                    self.note(folder, p, state="failed", error=str(ex)[:400])
                finally:
                    PROGRESS.report = None
            self.check_finished(folder)

    def interrupted(self):
        """A post still marked under way while nothing here works on it: Agents HQ stopped mid-post (a restart, the
        computer off), so nothing will finish it. Show it as failed, so the owner can check the platform and post again."""
        for folder in self.folders():
            with self.gate:
                if folder in self.busy:
                    continue
                r = self.record(folder)
                stuck = [p for p in PLATFORMS if (r.get(p) or {}).get("state") in ("waiting", "posting", "uploading")]
                for p in stuck:
                    name = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube"}[p]
                    self.note(folder, p, state="failed", error=f"Agents HQ stopped while this was posting, so it never finished. It may still have "
                                                               f"gone out: check {name} first, and if it isn't there, tick it and post again.")
            if stuck:
                self.check_finished(folder)

    def run_scheduler(self, every=30):
        def loop():
            while True:
                try:
                    self.interrupted()                          # before run_due: its own posts finish inside its call
                    self.run_due()
                except Exception as e:                          # keep the scheduler alive whatever one folder does
                    print("scheduler:", e)
                time.sleep(every)
        threading.Thread(target=loop, daemon=True).start()

    # Facebook Page Reel: start → upload the file to rupload → finish (published)
    def post_facebook(self, video, cover, text, when=None, channel=""):
        m = self.accounts.get("meta", channel)
        tok, page = m["page_token"], m["page_id"]
        progress(3, "starting the upload")
        try:
            _, _, j = http("POST", f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok})
        except PostError as e:
            raise meta_error(e) from None
        vid, upload = j["video_id"], j.get("upload_url") or f"https://rupload.facebook.com/video-upload/v23.0/{j['video_id']}"
        size = os.path.getsize(video)
        with open(video, "rb") as f:
            http("POST", upload, body=Sending(f, size, 5, 85), headers={"Authorization": "OAuth " + tok, "offset": "0", "file_size": str(size),
                                                    "Content-Length": str(size)}, timeout=1800)
        finish = {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": text.get("caption", ""), "access_token": tok}
        if when:                                               # Facebook holds it and publishes it at that time
            finish.update(video_state="SCHEDULED", scheduled_publish_time=str(int(when)))
        progress(88, "publishing")
        http("POST", f"{GRAPH}/{page}/video_reels", data=finish)
        extra = {}
        if cover:                                              # without this Facebook shows a frame of the video
            progress(92, "setting your thumbnail")
            try:
                self.fb_thumb(vid, cover, tok)
            except (PostError, OSError) as e:
                extra["warning"] = f"Posted, but Facebook did not take your thumbnail ({e}). Set it in Meta Business Suite."
        return f"https://www.facebook.com/reel/{vid}", extra

    def fb_thumb(self, vid, cover, tok):
        """The owner's thumbnail on a Facebook video; Facebook may still be processing it, so a few tries."""
        with open(cover, "rb") as f:
            img = f.read()
        for wait in (0, 15, 30, 60):
            time.sleep(wait)
            body, headers = multipart({"is_preferred": "true", "access_token": tok}, "source", os.path.basename(cover), img,
                                      "image/png" if cover.lower().endswith(".png") else "image/jpeg")
            try:
                http("POST", f"{GRAPH}/{vid}/thumbnails", body=body, headers=headers)
                return
            except PostError as e:
                last = e
        raise last

    def cover_url(self, cover, m, parked):
        """Instagram wants the cover as a URL: park it on the Page as an unpublished photo and use its address."""
        if not cover:
            return ""
        try:
            with open(cover, "rb") as f:
                img = f.read()
            body, headers = multipart({"published": "false", "access_token": m["page_token"]}, "source", os.path.basename(cover), img,
                                      "image/png" if cover.lower().endswith(".png") else "image/jpeg")
            _, _, j = http("POST", f"{GRAPH}/{m['page_id']}/photos", body=body, headers=headers)
            parked.append(j["id"])
            _, _, p = http("GET", f"{GRAPH}/{j['id']}?" + urllib.parse.urlencode({"fields": "images", "access_token": m["page_token"]}))
            return (p.get("images") or [{}])[0].get("source", "")
        except (PostError, KeyError, OSError):
            return ""                                          # Instagram then picks a frame itself

    def ig_wait(self, cid, tok):
        """Wait until Instagram has processed a container: None when it is ready, else Instagram's error."""
        for i in range(120):                                   # up to 10 minutes of processing
            progress(50 + 45 * (1 - math.exp(-i / 24)), "Instagram is processing the video")
            _, _, s = http("GET", f"{GRAPH}/{cid}?" + urllib.parse.urlencode({"fields": "status_code,status", "access_token": tok}))
            if s.get("status_code") == "FINISHED":
                return None
            if s.get("status_code") in ("ERROR", "EXPIRED"):
                return str(s.get("status") or s.get("status_code"))
            time.sleep(5)
        raise PostError("Instagram is still processing the video after 10 minutes; try Post again later")

    # Instagram Reel: container → the file straight to Instagram's upload host → wait until processed → publish
    def post_instagram(self, video, cover, text, when=None, channel=""):
        progress(2, "checking the video for Instagram")
        ready = ig_ready(video)
        try:
            return self.post_instagram_file(ready or video, cover, text, self.accounts.get("meta", channel))
        finally:
            if ready:
                try:
                    os.remove(ready)                           # the app's own temporary copy
                except OSError:
                    pass

    def ig_direct(self, video, params, m, wait=True):
        """Direct upload: (container id, None), or (None, why). wait=False only checks that the upload is accepted."""
        tok, ig = m["page_token"], m["ig_id"]
        _, _, j = http("POST", f"{GRAPH}/{ig}/media", data=dict(params, upload_type="resumable"))
        size = os.path.getsize(video)
        try:
            with open(video, "rb") as f:                         # the upload host takes the user token, not the Page token
                http("POST", j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v23.0/{j['id']}", body=Sending(f, size, 5, 50) if wait else f,
                     headers={"Authorization": "OAuth " + (m.get("user_token") or tok), "offset": "0", "file_size": str(size),
                              "Content-Length": str(size)}, timeout=1800)
        except PostError as e:
            if "ProcessingFailedError" not in str(e):
                raise
            return None, "upload refused"
        err = self.ig_wait(j["id"], tok) if wait else None
        return (None, err) if err else (j["id"], None)

    def unpark(self, parked, tok):
        for pid in parked:                                     # the hidden cover on the Page isn't needed any more
            try:
                http("DELETE", f"{GRAPH}/{pid}?" + urllib.parse.urlencode({"access_token": tok}))
            except PostError:
                pass
        parked.clear()

    def ig_limit(self, video, base, m):
        """Instagram refused the upload: test clips (never published) tell whether it is the length, and up to how long
        this account takes videos from apps. Returns the longest accepted length in seconds, 0 when the length is not the
        reason, or None when it can't tell."""
        d, ff = duration(video), os.environ.get("FFMPEG") or shutil.which("ffmpeg")
        if not d or not ff:
            return None
        fd, clip = tempfile.mkstemp(prefix="hq-igtest-", suffix=".mp4")
        os.close(fd)

        def takes(sec):
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={sec:.1f}",
                            "-f", "lavfi", "-i", f"sine=f=440:d={sec:.1f}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "38",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                            "-use_editlist", "0", "-shortest", clip],
                           capture_output=True, timeout=600, check=True, creationflags=0x08000000 if os.name == "nt" else 0)
            return bool(self.ig_direct(clip, base, m, wait=False)[0])
        try:
            if takes(d):
                return 0                                       # a clip as long is fine: it's something in the file itself
            lo, hi = 5.0, d
            while hi - lo > 5:
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if takes(mid) else (lo, mid)
            return int(lo)
        except (OSError, subprocess.SubprocessError, PostError):
            return None
        finally:
            try:
                os.remove(clip)
            except OSError:
                pass

    def post_instagram_file(self, video, cover, text, m):
        tok, ig = m["page_token"], m["ig_id"]
        base = {"media_type": "REELS", "caption": text.get("caption", ""), "share_to_feed": "true", "access_token": tok}
        parked, extra = [], {}                                 # the hidden cover on the Page
        try:
            progress(3, "sending your thumbnail")
            url = self.cover_url(cover, m, parked)
            cid, err = self.ig_direct(video, dict(base, cover_url=url) if url else base, m)
            for wait in (30, 90):                              # a refusal can pass later: a 57-second Reel went through
                if cid or err != "upload refused":            # this way on the account that refused a 56-second one
                    break
                progress(5, f"Instagram refused the upload, trying again in {wait} seconds")
                time.sleep(wait)
                cid, err = self.ig_direct(video, dict(base, cover_url=url) if url else base, m)
            if not cid and url and err != "upload refused":   # taken but not processed: try once without the cover
                cid, err2 = self.ig_direct(video, base, m)
                if cid:
                    extra["warning"] = "Posted without your cover: Instagram would not take it."
                else:
                    err = err2
            if not cid and err == "upload refused":
                progress(50, "Instagram refused it three times: finding out why")
                cap, d = self.ig_limit(video, base, m), duration(video)
                long = f"{int(d // 60)}:{int(d % 60):02d}" if d else ""
                if cap:
                    raise PostError(f"Instagram refused this video three times. Its test clips passed only up to about {cap} seconds today, "
                                    f"and this one is {long}, but longer Reels have gone through before, so try Post again later. "
                                    f"Otherwise post it by hand in the Instagram app, or ask Creative for an Instagram cut under {cap} seconds.")
                raise PostError("Instagram refused this video file" + (" (a test clip just as long was fine, so it isn't the length)" if cap == 0 else "")
                                + ". Post this one by hand in the Instagram app, and send a screenshot of this to Claude.")
            if not cid:
                raise PostError(f"Instagram could not process the video ({err}). Try Post again in a few minutes; if it keeps failing, "
                                "post this one by hand in the Instagram app.")
            progress(97, "publishing")
            _, _, p = http("POST", f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok})
        finally:
            self.unpark(parked, tok)
        link = ""
        try:
            _, _, q = http("GET", f"{GRAPH}/{p['id']}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tok}))
            link = q.get("permalink", "")
        except PostError:
            pass
        return link, extra

    # YouTube Short: resumable upload (vertical and short is what makes it a Short), then the cover as thumbnail
    def post_youtube(self, video, cover, text, when=None, channel=""):
        tok = self.accounts.youtube_token(channel)
        meta = {"snippet": {"title": text.get("title") or "Short", "description": text.get("description", ""), "categoryId": "22"},
                "status": {"privacyStatus": text.get("privacy") if text.get("privacy") in ("public", "unlisted", "private") else "public",
                           "selfDeclaredMadeForKids": False}}
        if when:                                               # uploaded private now, YouTube makes it public at that time
            meta["status"].update(privacyStatus="private", publishAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(when))))
        size = os.path.getsize(video)
        _, h, _ = http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                       body=json.dumps(meta).encode(), headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json; charset=UTF-8",
                                                               "X-Upload-Content-Type": "video/*", "X-Upload-Content-Length": str(size)})
        where = next((v for k, v in h.items() if k.lower() == "location"), None)
        if not where:
            raise PostError("YouTube did not start the upload")
        with open(video, "rb") as f:
            _, _, v = http("PUT", where, body=Sending(f, size, 3, 92), headers={"Authorization": "Bearer " + tok, "Content-Type": "video/*", "Content-Length": str(size)}, timeout=3600)
        vid, extra = v["id"], {}
        privacy = (v.get("status") or {}).get("privacyStatus", "")
        if privacy and privacy != meta["status"]["privacyStatus"] and not when:
            extra["warning"] = (f"YouTube set it to {privacy}: uploads from a new Google API project stay private until Google audits "
                                "the project. Make it public in YouTube Studio if it lets you, or apply for the audit.")
        if when:
            extra["warning"] = ("Scheduled in YouTube Studio for that time. If your Google project hasn't passed the YouTube audit yet, "
                                "YouTube keeps it private even then.")
        if cover:
            progress(95, "setting your thumbnail")
            try:
                with open(cover, "rb") as f:
                    img = f.read()
                http("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", body=img,
                     headers={"Authorization": "Bearer " + tok, "Content-Type": "image/png" if cover.lower().endswith(".png") else "image/jpeg"})
            except PostError as e:
                extra["warning"] = (extra.get("warning", "") + f" The cover was not set ({e}); custom thumbnails need a verified channel.").strip()
        return f"https://youtube.com/shorts/{vid}", extra
