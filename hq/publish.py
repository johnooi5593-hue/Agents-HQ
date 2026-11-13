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
    TikTok: a TikTok developer app (developers.tiktok.com) with Login Kit and the Content Posting API (video.upload). The
        owner pastes its Client key and Client secret, signs in once, and we keep the refresh token (365 days). A post
        goes to the account's TikTok drafts (inbox): the owner opens the TikTok notification, adds the caption and posts.
    Buffer (owner, 2026-11-09): Instagram and TikTok through buffer.com instead, with one caption for both and the
        owner's cover as the first frames of the video, so both show the same thumbnail (buffer_post.py). By hand from
        the Buffer package next to the approved video, or from the Post button with a Buffer API key and a public media
        host. Facebook and YouTube keep going out from here as before.

Stdlib only. Every post writes approved/<name>/posted.json as it goes, so the app shows progress and links.
"""
import calendar, json, math, os, re, secrets, shutil, subprocess, tempfile, threading, time, urllib.error, urllib.parse, urllib.request

import buffer_post
from channels import folder_channel

GRAPH = "https://graph.facebook.com/v23.0"
YT_SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
             "https://www.googleapis.com/auth/youtube")        # youtube: open a Short only once its thumbnail is on
PLATFORMS = ("facebook", "instagram", "youtube", "tiktok", "buffer")      # buffer: Instagram + TikTok through buffer.com
PLATFORM_NAMES = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok", "buffer": "Buffer"}
TT_API = "https://open.tiktokapis.com/v2"
TT_SCOPES = "user.info.basic,video.upload"                      # drafts: the video lands in the TikTok inbox, the owner posts it
VIDEO_EXT = (".mp4", ".mov", ".m4v")
# the phone copy (t206: phone.mp4, 1080p ≤ 30 MB, for watching on the phone) is never posted: only the approved edit.mp4
# goes out. The same "phone" word video_package.NOT_FINAL skips (tests/test_phone_copy.py checks the two agree).
PHONE_COPY = re.compile(r"(^|[-_. ])phone([-_. ]|$)", re.I)
COVER_IG = "cover-codex-ig.png"                                # Instagram's 3:4 Codex cover, next to the 9:16 cover-codex.png


class PostError(Exception):
    pass


class Unconfirmed(PostError):
    """The platform took a change but did not read it back: it may or may not have happened."""


class IgRefused(PostError):
    """Instagram's upload host refused the Reel. It often takes the same file later, so Agents HQ tries again by itself."""


IG_LATER = (30 * 60, 60 * 60, 2 * 3600, 4 * 3600, 8 * 3600)    # Instagram refused: try again after these waits, then give up


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


REEL_COVER = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:2,eq=brightness=-0.1[bg];"
              "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")


def cover_jpeg(cover, reel=False):
    """The owner's thumbnail as a JPEG every platform takes (YouTube wants at most 2 MB, Instagram's cover is a JPEG,
    a Codex pick is a large PNG), or None without ffmpeg. The picked file itself stays as it is.
    reel: Instagram's Reel cover, always 1080x1920. Instagram refuses Reel uploads whose cover is 3:4 (2026-11-02: both
    3:4 Codex covers refused, every 9:16 one taken), so a 3:4 cover sits whole in the middle over a blurred copy of
    itself: the profile grid shows the middle 3:4, which is exactly the owner's 3:4 design."""
    ff = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not cover or not ff or not os.path.isfile(cover):
        return None
    fd, out = tempfile.mkstemp(prefix="hq-cover-", suffix=".jpg")
    os.close(fd)
    for q, scale in ((2, None), (4, None), (5, "1080:-2")):   # smaller only when it has to be
        vf = ["-filter_complex", REEL_COVER] if reel else (["-vf", "scale=" + scale] if scale else [])
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", cover, "-frames:v", "1", "-q:v", str(q)] + vf + [out]
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
        """What the app may show: names only, never a token or a key."""
        full = self.load()
        a = self.section(full, channel)
        m, y, t = a.get("meta") or {}, a.get("youtube") or {}, a.get("tiktok") or {}
        b, md = a.get("buffer") or {}, a.get("media") or (full.get("media") or {} if channel else {})   # one media host serves every channel
        chans = [c for c in (b.get("channels") or []) if isinstance(c, dict)]
        name_of = lambda cid: next((c.get("name", "") for c in chans if c.get("id") == cid), "")
        picked = {s: {"id": b.get(s) or "", "name": name_of(b.get(s))} for s in buffer_post.SERVICES}
        return {
            "facebook": {"connected": bool(m.get("page_token")), "name": m.get("page_name", "")},
            "instagram": {"connected": bool(m.get("page_token") and m.get("ig_id")), "name": ("@" + m["ig_username"]) if m.get("ig_username") else "",
                          "problem": "" if not m.get("page_token") or m.get("ig_id") else "no Instagram professional account is linked to this Facebook Page"},
            "youtube": {"connected": bool(y.get("refresh_token")), "name": y.get("channel", ""), "client": bool(y.get("client_id"))},
            "tiktok": {"connected": bool(t.get("refresh_token")), "name": t.get("name", ""), "client": bool(t.get("client_key")), "mode": "drafts"},
            "buffer": {"connected": bool(b.get("api_key") and (b.get("instagram") or b.get("tiktok"))), "key": bool(b.get("api_key")),
                       "name": " + ".join(f"{PLATFORM_NAMES[s]} {picked[s]['name']}" for s in buffer_post.SERVICES if picked[s]["id"]),
                       "instagram": picked["instagram"], "tiktok": picked["tiktok"],
                       "channels": [{k: c.get(k, "") for k in ("id", "name", "service", "problem")} for c in chans],
                       "host": buffer_post.host_ready(md), "hostName": md.get("bucket", "") + (" · " + md["public_url"] if md.get("public_url") else ""),
                       "hostChecked": md.get("checked_url", ""), "hostShared": bool(channel and not a.get("media") and md)},
        }

    # ---------------------------------------------------------------- Buffer (Instagram + TikTok)
    def connect_buffer(self, api_key, channel=""):
        """Checks the key against Buffer, keeps it with the account's channels, and picks the first Instagram and TikTok
        channel (an earlier pick that still exists is kept). An empty key means the saved one (to read the channels again)."""
        api_key = str(api_key or "").strip() or (self.get("buffer", channel) or self.get("buffer")).get("api_key", "")
        api = buffer_post.Buffer(api_key)
        try:
            chans = api.all_channels()
        except buffer_post.BufferError as e:
            raise PostError(str(e)) from None
        if not chans:
            raise PostError("this Buffer account has no channels yet: connect Instagram and TikTok in Buffer first, then connect again here")
        with self.lock:
            a = self.load()
            old = self.slot(a, channel).get("buffer") or {}
            row = {"api_key": api.key, "channels": chans, "at": int(time.time())}
            for s in buffer_post.SERVICES:
                keep = old.get(s) if any(c["id"] == old.get(s) and c["service"] == s for c in chans) else ""
                row[s] = keep or next((c["id"] for c in chans if c["service"] == s and not c["problem"]), "")
            self.slot(a, channel)["buffer"] = row
            self.save(a)
        return {"channels": chans, "instagram": row["instagram"], "tiktok": row["tiktok"]}

    def buffer_channels(self, picks, channel=""):
        """The owner's choice of Buffer channel for Instagram and for TikTok (an empty pick switches that one off)."""
        with self.lock:
            a = self.load()
            b = self.slot(a, channel).get("buffer")
            if not b or not b.get("api_key"):
                raise PostError("connect Buffer first")
            for s in buffer_post.SERVICES:
                if s not in picks:
                    continue
                v = str(picks.get(s) or "")
                if v and not any(c.get("id") == v and c.get("service") == s for c in b.get("channels") or []):
                    raise PostError(f"that is not one of your Buffer {PLATFORM_NAMES[s]} channels")
                b[s] = v
            self.save(a)

    def connect_host(self, cfg, channel=""):
        """The public media host for Buffer: checked by uploading a small file and reading it back from the public address.
        An empty field keeps what was saved before (so the secret need not be pasted again). Returns the public URL that worked."""
        cfg = cfg or {}
        old = self.get("media", channel) or self.get("media")
        merged = {k: (str(cfg.get(k) or "").strip() or old.get(k, "")) for k in buffer_post.HOST_FIELDS + ("region", "prefix")}
        try:
            host = buffer_post.MediaHost(merged)
            url = host.check()
        except buffer_post.BufferError as e:
            raise PostError(str(e)) from None
        with self.lock:
            a = self.load()
            self.slot(a, channel)["media"] = dict(host.cfg, at=int(time.time()), checked_url=url)
            self.save(a)
        return url

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
        if not got or len(got) != 5 or time.time() - got[3] > 900:
            raise PostError("this sign-in link expired; press Connect YouTube again")
        cid, csec, redirect, _, channel = got
        _, _, j = http("POST", "https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": cid, "client_secret": csec, "redirect_uri": redirect, "grant_type": "authorization_code"})
        if not j.get("refresh_token"):
            raise PostError("Google gave no refresh token; remove Agents HQ at myaccount.google.com/permissions and connect again")
        title = ""
        try:
            _, _, c = http("GET", "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                           headers={"Authorization": "Bearer " + j["access_token"]})
            title = ((c.get("items") or [{}])[0].get("snippet") or {}).get("title", "")
        except PostError:
            pass
        with self.lock:
            a = self.load()
            self.slot(a, channel)["youtube"] = {"client_id": cid, "client_secret": csec, "refresh_token": j["refresh_token"], "channel": title, "at": int(time.time())}
            self.save(a)
        return title

    def youtube_token(self, channel=""):
        y = self.get("youtube", channel)
        if not y.get("refresh_token"):
            raise PostError("YouTube is not connected")
        _, _, j = http("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": y["client_id"], "client_secret": y["client_secret"], "refresh_token": y["refresh_token"], "grant_type": "refresh_token"})
        return j["access_token"]

    # ---------------------------------------------------------------- TikTok
    def tiktok_begin(self, client_key, client_secret, redirect, channel=""):
        """Start the TikTok sign-in. Without a key and secret the channel's (or the main channel's) TikTok app is used
        again. redirect must be an https address registered in the app's Login Kit. Returns the URL to open."""
        t = self.get("tiktok", channel) or self.get("tiktok")
        key, sec = str(client_key or "").strip() or t.get("client_key", ""), str(client_secret or "").strip() or t.get("client_secret", "")
        if not (key and sec):
            raise PostError("paste the Client key and Client secret of your TikTok app first")
        if not str(redirect or "").startswith("https://"):
            raise PostError("TikTok needs an https return address; turn on phone access (Tailscale) so Agents HQ has one")
        state = secrets.token_urlsafe(16)
        self.pending = {state: (key, sec, redirect, time.time(), channel, "tiktok")}
        return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": key, "response_type": "code", "scope": TT_SCOPES, "redirect_uri": redirect, "state": state})

    def tiktok_finish(self, state, code):
        got = self.pending.pop(state, None) if state else None
        if not got or len(got) < 6 or got[5] != "tiktok" or time.time() - got[3] > 900:
            raise PostError("this sign-in link expired; press Connect TikTok again")
        key, sec, redirect, _, channel, _ = got
        _, _, j = http("POST", TT_API + "/oauth/token/", data={
            "client_key": key, "client_secret": sec, "code": code, "grant_type": "authorization_code", "redirect_uri": redirect})
        if not j.get("refresh_token"):
            raise PostError(j.get("error_description") or "TikTok gave no refresh token")
        name = ""
        try:
            _, _, u = http("GET", TT_API + "/user/info/?fields=open_id,display_name", headers={"Authorization": "Bearer " + j["access_token"]})
            name = ((u.get("data") or {}).get("user") or {}).get("display_name", "")
        except PostError:
            pass
        with self.lock:
            a = self.load()
            self.slot(a, channel)["tiktok"] = {"client_key": key, "client_secret": sec, "refresh_token": j["refresh_token"], "open_id": j.get("open_id", ""),
                                               "scope": j.get("scope", ""), "name": name, "at": int(time.time())}
            self.save(a)
        return name

    def tiktok_token(self, channel=""):
        """A fresh access token (they last 24 hours); TikTok may hand back a new refresh token, which replaces the old one."""
        t = self.get("tiktok", channel)
        if not t.get("refresh_token"):
            raise PostError("TikTok is not connected")
        _, _, j = http("POST", TT_API + "/oauth/token/", data={
            "client_key": t["client_key"], "client_secret": t["client_secret"], "grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
        if not j.get("access_token"):
            raise PostError(j.get("error_description") or "TikTok did not renew the sign-in; connect TikTok again")
        if j.get("refresh_token") and j["refresh_token"] != t["refresh_token"]:
            with self.lock:
                a = self.load()
                self.slot(a, channel).setdefault("tiktok", {})["refresh_token"] = j["refresh_token"]
                self.save(a)
        return j["access_token"]

    def disconnect(self, which, channel=""):
        """which: meta (Facebook + Instagram), youtube, tiktok, buffer, or media (Buffer's media host)."""
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
    (and the thumbnail) and Facebook, Instagram and YouTube all get it; they can still edit a platform's text.
    TikTok and Buffer get exactly Instagram's caption (owner, 2026-11-09: the same words on both), plus the option's
    title for TikTok's title field; an older post.md's "## TikTok" section is no longer used."""
    try:
        with open(os.path.join(folder, "post.md"), encoding="utf-8") as f:
            s = sections(f.read())
    except OSError:
        s = {}
    name = os.path.basename(folder).replace("-", " ")
    common = s.get("options") or []
    if not common and not any(s.get(k) for k in ("youtube", "instagram", "facebook")):
        common = s.get("other") or []                         # an older post.md: its sections are the options
    plat = {k: s.get(k) or [] for k in ("youtube", "instagram", "facebook", "tiktok")}
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
        same = {"caption": ig[:buffer_post.IG_CAPTION], "title": base_title[:buffer_post.TIKTOK_TITLE]}   # Instagram's words, on TikTok too
        options.append({"title": yt_title, "caption": base or ig or fb,
                        "youtube": {"title": yt_title, "description": desc[:4900]},
                        "instagram": {"caption": ig[:buffer_post.IG_CAPTION]}, "facebook": {"caption": fb},
                        "tiktok": dict(same), "buffer": dict(same)})
    first = options[0]
    return {"options": options, **{k: first[k] for k in ("youtube", "instagram", "facebook", "tiktok", "buffer")}}


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
            if full and full.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(full) and cand not in out \
                    and not PHONE_COPY.search(os.path.basename(cand)):
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
                    if not PHONE_COPY.search(fn):                  # phone.mp4 is for the owner's phone, never a post
                        found["video"].append(path)
                elif fn.lower().endswith((".jpg", ".jpeg", ".png")):
                    found["image"].append(path)
        if found["video"]:
            break
    if not found["video"]:
        root = office_root(folder)
        for rel in linked_videos(folder):
            found["video"].append(rel); found["abs"][rel] = os.path.join(root, rel)
    # edit.mp4 itself first: kept older versions (edit-v1.mp4, edit-v3-softmusic.mp4) sort before it by name, and CAN 1030
    # reel 2 went to Facebook and YouTube as edit-v1 instead of the approved edit.mp4 (2026-11-02)
    rank = lambda n: (0 if re.fullmatch(r"(edit|final|reel)\.\w+", os.path.basename(n), re.I) else 1 if re.match(r"(edit|final|reel)\b", os.path.basename(n), re.I)
                      else 3 if re.search(r"clean|nocap|no-captions", n, re.I) else 4 if os.path.basename(n).lower().startswith("cut") else 2)
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
NATIVE_SCHEDULE = ("facebook", "youtube", "buffer")           # these publish at the time by themselves; Instagram is posted by us


RESCHEDULE_GUARD = 120                                          # a post this close to its time is never moved


def fb_time(v):
    """Facebook's scheduled_publish_time (unix seconds, or an ISO time) as unix seconds; 0 when it has none."""
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        return calendar.timegm(time.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S")) if str(v)[19:] in ("+0000", "Z", "+00:00") else 0
    except (TypeError, ValueError):
        return 0


def check_when(when):
    """A scheduled time the owner picked, as an int: at least 10 minutes and at most 4 weeks ahead."""
    try:
        when = int(when)
    except (TypeError, ValueError, OverflowError):
        raise PostError("that is not a time") from None
    ahead = when - time.time()
    if ahead < SCHEDULE_MIN:
        raise PostError("pick a time at least 10 minutes from now")
    if ahead > SCHEDULE_MAX:
        raise PostError("pick a time within the next 4 weeks")
    return when


class Publisher:
    """Posts now, or at a time the owner picks. Facebook and YouTube upload at once and publish at that time on their own
    (the computer may sleep); Instagram has no scheduling in its API, so the job waits in posted.json and the scheduler
    here posts it when it is due (as soon as Agents HQ runs again if the computer was off)."""

    def __init__(self, root, accounts, on_schedule=None, on_finish=None, on_move=None):
        self.root, self.accounts, self.lock, self.busy = root, accounts, threading.Lock(), set()
        self.gate = threading.Lock()                               # a post starting vs. the check for interrupted posts
        self.on_schedule, self.on_finish = on_schedule, on_finish     # the board: a dated "post" task, done when all went out
        self.on_move = on_move                                      # the board: that task's new date when the post's time changed
        self.covers = buffer_post.CoverPackages()                   # approved/<name>/buffer/: the video with the cover as frame 1

    def record_path(self, folder):
        return os.path.join(folder, "posted.json")

    def record(self, folder):
        for i in range(5):                                      # Windows: a reader can meet the writer's replace for a moment
            try:
                with open(self.record_path(folder), encoding="utf-8") as f:
                    return json.load(f)
            except PermissionError:
                time.sleep(0.05 * (i + 1))
            except (OSError, ValueError):
                return {}
        return {}

    def note(self, folder, platform, **kw):
        with self.lock:
            r = self.record(folder)
            if platform.startswith("_"):
                r[platform] = kw.get("value")
            else:
                r[platform] = {**r.get(platform, {}), **kw, "at": int(time.time())}
            path = self.record_path(folder)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1, ensure_ascii=False)
            for i in range(5):                                  # whole file or nothing; a reader holding it gets a moment
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    time.sleep(0.05 * (i + 1))
            else:
                shutil.copyfile(tmp, path)

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

    def payload(self, folder, video_name="", cover_name=""):
        """What the posting screen shows. video_name / cover_name: the owner's current pick, for the Buffer package's state."""
        f = media_files(folder)
        try:
            video, cover, _ = self.resolve(folder, video_name, cover_name)
        except PostError:
            video, cover, _ = self.resolve(folder)
        return {"accounts": self.accounts.summary(folder_channel(folder)), "channel": folder_channel(folder), "drafts": drafts(folder), "posted": self.record(folder),
                "videos": f["video"], "covers": f["image"], "linked": sorted(f["abs"]), "video": (f["video"] or [""])[0], "cover": (f["image"] or [""])[0],
                "busy": folder in self.busy, "buffer": self.buffer_state(folder, video, cover)}

    def buffer_state(self, folder, video, cover):
        """The Buffer package for this video + cover pick, with where its files are (relative to the office folder)."""
        if not video:
            return {"state": "none", "files": {}, "dash": buffer_post.DASH}
        pkg_folder = os.path.dirname(os.path.abspath(video))
        root = office_root(folder)
        st = self.covers.state(pkg_folder, video, cover)
        st["base"] = os.path.relpath(pkg_folder, root).replace(os.sep, "/") if root else ""
        st["dash"] = buffer_post.DASH
        parts = os.path.abspath(folder).replace(os.sep, "/").split("/")
        st["approved"] = "approved" in parts[-3:-1]           # approved/<name> or approved/<name>/<topic>: the package can be made
        return st

    def resolve(self, folder, video_name="", cover_name="", cover_ig_name=""):
        """The files one post uses: (video, cover, Instagram's cover), absolute. Names are the owner's picks in the folder."""
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
        # Instagram: the 3:4 Codex cover next to the 9:16 one (owner, 2026-10-28), unless the owner picked another picture
        cover_ig = cover
        if cover_ig_name:
            if cover_ig_name not in files["image"]:
                raise PostError("that Instagram thumbnail is not in this folder")
            cover_ig = os.path.join(folder, cover_ig_name)
        elif os.path.isfile(os.path.join(folder, COVER_IG)) and (not cover_name or cover_name == "cover-codex.png"):
            cover_ig = os.path.join(folder, COVER_IG)
        return video, cover, cover_ig

    def buffer_make(self, folder, video_name="", cover_name="", caption=None, title=None):
        """The posting screen asks for the Buffer package of the current pick (made in the background), with its texts."""
        video, cover, _ = self.resolve(folder, video_name, cover_name)
        if not video:
            raise PostError("no video in this folder")
        if not cover:
            raise PostError("pick your thumbnail first: the Buffer video starts with it")
        self.covers.start(os.path.dirname(os.path.abspath(video)), video, cover, caption, title)
        return self.buffer_state(folder, video, cover)

    def buffer_done(self, folder, video_name="", cover_name="", caption=None, title=None):
        """The owner posted it in Buffer by hand: the board counts it as posted."""
        video, cover, _ = self.resolve(folder, video_name, cover_name)
        if video:
            self.covers.texts(os.path.dirname(os.path.abspath(video)), caption, title)
        rel = lambda p: os.path.basename(p) if p else ""
        self.note(folder, "buffer", state="posted", manual=True, link=buffer_post.DASH, error="", warning="", when=0, job=None,
                  video=rel(video), cover=rel(cover), posts={})
        self.check_finished(folder)

    def start(self, folder, chosen, video_name="", cover_name="", when=None, cover_ig_name=""):
        """chosen: {platform: {text fields}}; video_name / cover_name: the files the owner picked in the folder;
        cover_ig_name: Instagram's own cover (3:4), when it has one; when: a unix time to publish at, or None for now.
        Works in the background; returns the platforms started."""
        video, cover, cover_ig = self.resolve(folder, video_name, cover_name, cover_ig_name)
        if not video:
            raise PostError("no video in this folder")
        cover_of = lambda p: cover_ig if p == "instagram" else cover
        if when is not None:
            when = check_when(when)
        channel = folder_channel(folder)
        summary = self.accounts.summary(channel)
        todo = [p for p in PLATFORMS if p in chosen and summary[p]["connected"]]
        if not todo:
            raise PostError("pick at least one connected account")
        if not cover and any(p != "tiktok" for p in todo):      # owner, 2026-11-02: never posted without the thumbnail
            raise PostError("pick your thumbnail first: nothing is posted without it")
        done = self.record(folder)
        again = [p for p in todo if (done.get(p) or {}).get("state") in ("posted", "scheduled") and not chosen[p].get("again")]
        if again:
            raise PostError(f"already posted or scheduled to {', '.join(again)}")
        # Buffer posts Instagram and TikTok itself: one video never goes to the same place twice (direct and through Buffer)
        b = self.accounts.get("buffer", channel) or {}
        live = ("posted", "scheduled", "waiting", "posting", "uploading")
        covered = [p for p in buffer_post.SERVICES if b.get(p)]
        both = lambda ps: " and ".join(PLATFORM_NAMES[p] for p in ps)
        if "buffer" in todo:
            twice = [p for p in covered if p in todo]
            if twice:
                raise PostError(f"{both(twice)} is ticked twice: directly and through Buffer. Untick one of them.")
            twice = [p for p in covered if (done.get(p) or {}).get("state") in live]
            if twice:
                raise PostError(f"{both(twice)} already went out or is scheduled directly, and Buffer would post it again. "
                                "Cancel the direct one first, or post the other platform by hand in Buffer.")
        elif (done.get("buffer") or {}).get("state") in live:
            twice = [p for p in covered if p in todo and not chosen[p].get("again")]
            if twice:
                raise PostError(f"{both(twice)} is already in Buffer for this video. Posting it directly too would put it up twice.")
        with self.gate:
            if folder in self.busy:
                raise PostError("still posting this one")
            self.busy.add(folder)
        rel = lambda path: (os.path.relpath(path, folder).replace(os.sep, "/") if os.path.dirname(os.path.abspath(path)).startswith(os.path.abspath(folder)) else os.path.relpath(path, office_root(folder) or folder).replace(os.sep, "/")) if path else ""
        for p in todo:
            self.note(folder, p, state="waiting", error="", warning="", when=when or 0, job=None, link=done.get(p, {}).get("link", ""),
                      video=rel(video), cover=rel(cover_of(p)))
        if when and self.on_schedule:
            try:
                self.note(folder, "_task", value=self.on_schedule(folder, when, todo))
            except Exception:                                  # the board is a nice-to-have, never a reason not to post
                pass

        def one(p):                                             # every platform at the same time
            if when and p not in NATIVE_SCHEDULE:               # Instagram: wait here, the scheduler posts it when due
                self.note(folder, p, state="scheduled", job={"text": chosen[p], "video": rel(video), "cover": rel(cover_of(p))})
                return
            self.note(folder, p, state="posting" if not when else "uploading", error="", progress=0, step="starting")
            PROGRESS.report = self.reporter(folder, p)
            try:
                link, extra = self.send(p, video, cover_of(p), chosen[p], when, channel)
                self.note(folder, p, state="scheduled" if when else "posted", link=link, error="", **extra)
            except IgRefused as e:                              # Instagram said no for now: Agents HQ tries again later
                self.later(folder, p, {"text": chosen[p], "video": rel(video), "cover": rel(cover_of(p))}, e)
            except Exception as e:                              # one platform failing never stops the others
                self.note(folder, p, state="failed", error=str(e)[:600])
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
        jpg = cover_jpeg(cover, reel=p == "instagram") if p != "buffer" else None   # Buffer bakes the picked file itself
        try:
            return getattr(self, "post_" + p)(video, jpg or cover, text, when, channel)
        finally:
            if jpg:
                try:
                    os.remove(jpg)
                except OSError:
                    pass

    def later(self, folder, p, job, err, now=None):
        """Instagram refused: park the post as scheduled for a later try (the scheduler runs it), or fail after the last."""
        n = int(job.get("tries") or 0)
        if n >= len(IG_LATER):
            self.note(folder, p, state="failed", job=None, error=(
                f"Instagram refused this Reel {n + 1} times over about {sum(IG_LATER) // 3600} hours. It was never posted without "
                "your thumbnail. Post it by hand in the Instagram app with your thumbnail, and tell Claude."))
            return
        at = int((now or time.time()) + IG_LATER[n])
        self.note(folder, p, state="scheduled", when=at, job=dict(job, tries=n + 1), error="",
                  warning=f"Instagram refused the upload just now ({str(err).rstrip('.')}). Agents HQ tries again by itself at "
                          f"{time.strftime('%H:%M', time.localtime(at))} (try {n + 2} of {len(IG_LATER) + 1}); keep the computer on.")

    def cancel(self, folder, platform):
        """Cancel a scheduled post: one still waiting here (Instagram), or the Buffer posts (deleted in Buffer too).
        Facebook and YouTube already hold theirs."""
        if platform == "buffer":
            return self.buffer_cancel(folder)
        self.claim(folder)                                      # never while the scheduler is about to post it
        try:
            r = self.record(folder).get(platform) or {}
            if r.get("state") != "scheduled" or not r.get("job"):
                raise PostError("only a scheduled Instagram or Buffer post can be cancelled here; "
                                "cancel Facebook in Meta Business Suite and YouTube in YouTube Studio")
            self.note(folder, platform, state="cancelled", job=None)
        finally:
            self.busy.discard(folder)
        self.check_finished(folder)

    def reschedule(self, folder, when):
        """One new time for every post of this video that is still scheduled (owner, 2026-11-13): the Buffer posts (changed
        in Buffer), Facebook's and YouTube's (changed there, they hold the post) and an Instagram post waiting here.
        A post whose time has come is never touched. A platform that does not take the new time, or that does not confirm
        it, keeps its old one and says so on its row. Returns {"moved": [platforms], "kept": {platform: why}}; raises
        when nothing moved."""
        when = check_when(when)
        self.claim(folder)                                      # one claim for all of it: nothing is posted meanwhile
        moved, kept = [], {}
        try:
            r = self.record(folder)
            todo = [p for p in PLATFORMS if (r.get(p) or {}).get("state") == "scheduled"]
            if not todo:
                raise PostError("nothing is scheduled for this video")
            channel, now = folder_channel(folder), time.time()
            for p in todo:
                e = self.record(folder).get(p) or {}
                if e.get("state") != "scheduled":
                    continue
                at = int(e.get("when") or 0)
                if at <= now + RESCHEDULE_GUARD:                # it is going out (or is out): never pulled back
                    kept[p] = "its time has come, so it stays as it is"
                    continue
                try:
                    if p == "buffer":
                        self.buffer_change(folder, when, held=True)
                        e2 = self.record(folder).get("buffer") or {}
                        if e2.get("when") != when:
                            raise PostError(e2.get("warning") or "Buffer changed only one of the two posts")
                    else:
                        if e.get("job"):
                            pass                                # it waits here: the scheduler posts it at the new time
                        elif p == "facebook":
                            self.move_facebook(e, when, channel)
                        elif p == "youtube":
                            self.move_youtube(e, when, channel)
                        else:
                            raise PostError("this post is held by the platform: change the time there")
                        keep = e.get("warning") or ""
                        stale = e.get("job") or keep.startswith("Still set for") or "may have moved" in keep   # said the old time
                        self.note(folder, p, when=when, warning="" if stale else keep)
                    moved.append(p)
                except Exception as ex:                         # one platform never stops the others
                    why = (str(ex) if isinstance(ex, PostError) else type(ex).__name__)[:300]
                    kept[p] = why
                    if p != "buffer":                           # the Buffer row says its own
                        where = {"facebook": "Meta Business Suite", "youtube": "YouTube Studio"}.get(p, "its own app")
                        old = time.strftime("%a %d %b %H:%M", time.localtime(at))
                        if isinstance(ex, Unconfirmed):
                            self.note(folder, p, warning=f"{PLATFORM_NAMES[p]} may have moved to the new time but did not confirm it "
                                                         f"(here it still shows {old}). Check the time in {where}.")
                        else:
                            self.note(folder, p, warning=f"Still set for {old}: {PLATFORM_NAMES[p]} did not take the new time "
                                                         f"({why.rstrip('.')}). Change it in {where}.")
        finally:
            self.busy.discard(folder)
        if not moved:
            raise PostError("nothing was rescheduled. " + "; ".join(f"{PLATFORM_NAMES[p]}: {why}" for p, why in kept.items()))
        self.moved(folder, when)
        return {"moved": moved, "kept": kept}

    def move_facebook(self, e, when, channel=""):
        """A Reel Facebook holds as scheduled: a new publish time on the same video. Only a video Facebook itself says is
        still scheduled is changed, and it counts as moved only when Facebook reads the new time back."""
        m = re.fullmatch(r"https://www\.facebook\.com/reel/(\d{5,25})", e.get("link") or "")
        if not m:
            raise PostError("no Facebook video id on this post")
        vid, tok = m.group(1), self.accounts.get("meta", channel)["page_token"]
        ask = f"{GRAPH}/{vid}?fields=scheduled_publish_time,published&access_token={urllib.parse.quote(tok)}"
        try:
            _, _, j = http("GET", ask)
            if j.get("published") is not False or fb_time(j.get("scheduled_publish_time")) <= time.time() + RESCHEDULE_GUARD:
                raise PostError("Facebook no longer holds it as scheduled")       # by Facebook's own time, not ours
            http("POST", f"{GRAPH}/{vid}", data={"scheduled_publish_time": str(int(when)), "access_token": tok})
        except PostError as ex:
            raise meta_error(ex) from None
        try:
            _, _, j = http("GET", ask)
        except (PostError, OSError):
            raise Unconfirmed("Facebook did not confirm the new time") from None
        if abs(fb_time(j.get("scheduled_publish_time")) - int(when)) > 60:
            raise Unconfirmed("Facebook did not confirm the new time")

    YT_STATUS = ("privacyStatus", "publishAt", "license", "embeddable", "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia")

    def move_youtube(self, e, when, channel=""):
        """A Short YouTube holds as private with a publish time: a new publish time on the same video, its other settings
        as they are. A video that is already public (or has no publish time) is never touched."""
        m = re.fullmatch(r"https://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{6,20})", e.get("link") or "")
        if not m:
            raise PostError("no YouTube video id on this post")
        vid, auth = m.group(1), {"Authorization": "Bearer " + self.accounts.youtube_token(channel)}
        _, _, j = http("GET", f"https://www.googleapis.com/youtube/v3/videos?part=status&id={vid}", headers=auth)
        status = ((j.get("items") or [{}])[0] or {}).get("status") or {}
        if status.get("privacyStatus") != "private" or fb_time(str(status.get("publishAt") or "")[:19] + "Z") <= time.time() + RESCHEDULE_GUARD:
            raise PostError("YouTube no longer holds it as scheduled")            # by YouTube's own time, not ours
        want = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(when)))
        status = {k: v for k, v in status.items() if k in self.YT_STATUS}
        status.update(privacyStatus="private", publishAt=want + "Z")
        _, _, v = http("PUT", "https://www.googleapis.com/youtube/v3/videos?part=status", body=json.dumps({"id": vid, "status": status}).encode(),
                       headers=dict(auth, **{"Content-Type": "application/json; charset=UTF-8"}))
        got = (v.get("status") or {})
        if got.get("privacyStatus") != "private" or str(got.get("publishAt") or "")[:19] != want:
            raise Unconfirmed("YouTube did not confirm the new time")

    # A Buffer post scheduled from here stays in step with Buffer: a change or a cancel here is made in Buffer too,
    # and a change made in Buffer (a new time, a deleted post) shows here at the next status check.
    def buffer_scheduled(self, folder):
        """The Buffer record and API client for a Buffer post scheduled from Agents HQ, or PostError."""
        r = self.record(folder).get("buffer") or {}
        if r.get("state") != "scheduled" or r.get("manual") or not r.get("posts"):
            raise PostError("only a Buffer post scheduled from Agents HQ can be changed here; "
                            "one you made in Buffer yourself is changed in Buffer")
        b = self.accounts.get("buffer", folder_channel(folder))
        if not b.get("api_key"):
            raise PostError("Buffer is not connected any more (user menu → Accounts → Buffer)")
        return r, buffer_post.Buffer(b["api_key"])

    @staticmethod
    def buffer_open(p):
        """A Buffer post that is still waiting to go out."""
        return bool(p.get("id")) and p.get("status") not in ("sent", "error", "deleted")

    @staticmethod
    def buffer_take(p, q):
        """Buffer's answer about one post into our copy of it. A post that went out never turns into anything else."""
        link = q.get("externalLink") or p.get("link") or ""
        if p.get("status") == "sent":
            p["link"] = link
            return
        status = "sent" if q.get("sentAt") and q.get("status") != "error" else q.get("status") or p.get("status")
        p.update(status=status, link=link, error=((q.get("error") or {}).get("message") or "") if isinstance(q.get("error"), dict) else "")
        due = buffer_post.from_iso(q.get("dueAt"))
        if due:
            p["due"] = due

    def buffer_fresh(self, api, posts):
        """Ask Buffer how each waiting post stands right now, before changing or cancelling it: one that went out since
        the last check is left alone."""
        for p in posts.values():
            if not self.buffer_open(p):
                continue
            try:
                q = api.post(p["id"])
            except buffer_post.BufferError as e:
                raise PostError(f"Buffer did not answer, so nothing was changed: {e}") from None
            if q:
                self.buffer_take(p, q)
            else:
                p.update(status="deleted", link="")

    def claim(self, folder):
        """This folder is being worked on: no second post, change, cancel or status check on it meanwhile."""
        with self.gate:
            if folder in self.busy:
                raise PostError("still posting this one")
            self.busy.add(folder)

    def buffer_change(self, folder, when=None, caption=None, title=None, held=False):
        """New time, caption or TikTok title for the scheduled Buffer posts: changed in Buffer first, then here.
        held: the caller already claimed the folder (reschedule moves every platform under one claim)."""
        if when is None and caption is None and title is None:
            raise PostError("nothing to change")
        when = check_when(when) if when is not None else None
        if caption is not None and len(caption) > buffer_post.IG_CAPTION:
            raise PostError(f"the caption is longer than Instagram's {buffer_post.IG_CAPTION} characters")
        if not held:
            self.claim(folder)
        try:
            r, api = self.buffer_scheduled(folder)
            posts = {s: dict(p) for s, p in r["posts"].items()}
            self.buffer_fresh(api, posts)
            changed, errors, notes = [], [], []
            for service, p in posts.items():
                if not self.buffer_open(p):
                    if p.get("status") == "sent":
                        notes.append(f"{PLATFORM_NAMES[service]} had already gone out, so it stays as it is.")
                    continue
                if service != "tiktok" and when is None and caption is None:
                    continue                                    # only the TikTok title changes: nothing to tell Instagram
                try:
                    q = api.edit_post(p["id"], service, when=when, text=caption, title=title if service == "tiktok" else None)
                    p.update(status=q.get("status") or p.get("status"), due=buffer_post.from_iso(q.get("dueAt")) or when or p.get("due"))
                    changed.append(service)
                    if q.get("titleKept"):
                        title = None                            # title.txt keeps the title Buffer still has
                        notes.append("Buffer did not take the new TikTok title: change it in Buffer.")
                except buffer_post.BufferError as e:
                    errors.append(f"{PLATFORM_NAMES[service]}: {e}")
            if not changed:
                self.note(folder, "buffer", **self.buffer_outcome(r, posts))
                raise PostError("; ".join(errors + notes) or "Buffer has already sent or removed these posts, so there is nothing left to change")
            if errors:
                notes.insert(0, f"Changed in Buffer for {' and '.join(PLATFORM_NAMES[s] for s in changed)} only ({'; '.join(errors)}). "
                                "Change the other one in Buffer if it still needs it.")
            out = self.buffer_outcome(r, posts)
            upd = dict(out, warning=" ".join(notes + ([out["mix"]] if out["mix"] else [])))
            if when and not errors:
                upd["when"] = when
            self.note(folder, "buffer", **upd)
            if caption is not None or title is not None:      # caption.txt / title.txt next to the posted video match Buffer
                self.covers.texts(self.package_folder(folder, r.get("video")), caption, title)
        finally:
            if not held:
                self.busy.discard(folder)
        if upd.get("when"):
            self.moved(folder, when)
        if out["state"] in ("posted", "failed", "cancelled"):
            self.check_finished(folder)

    def buffer_cancel(self, folder):
        """Delete the scheduled Buffer posts, so they never go out. A post Buffer already sent stays sent."""
        self.claim(folder)
        try:
            r, api = self.buffer_scheduled(folder)
            posts = {s: dict(p) for s, p in r["posts"].items()}
            self.buffer_fresh(api, posts)
            errors = []
            for service, p in posts.items():
                if not self.buffer_open(p):
                    continue
                try:
                    api.delete_post(p["id"])
                    p.update(status="deleted", link="")
                except buffer_post.BufferError as e:
                    errors.append(f"{PLATFORM_NAMES[service]}: {e}")
            if errors and not any(p.get("status") == "deleted" for p in posts.values()):
                raise PostError("; ".join(errors))
            out = self.buffer_outcome(r, posts)
            warn = [f"Buffer did not delete one of them ({'; '.join(errors)}): delete it in Buffer."] if errors else []
            self.note(folder, "buffer", **out, checked=int(time.time()), warning=" ".join(warn + ([out["mix"]] if out["mix"] else [])))
        finally:
            self.busy.discard(folder)
        self.check_finished(folder)

    @staticmethod
    def buffer_outcome(e, posts):
        """The Buffer row's state, posts, link and error from its posts' statuses in Buffer; mix: what to say when the
        two posts no longer go together (one deleted, one sent or still waiting)."""
        names = lambda ss: " and ".join(PLATFORM_NAMES[s] for s in ss)
        gone = [s for s, p in posts.items() if p.get("status") == "deleted"]
        live = {s: p.get("status") for s, p in posts.items() if p.get("status") != "deleted"}
        state = ("cancelled" if not live else "posted" if all(v == "sent" for v in live.values())
                 else "failed" if any(v == "error" for v in live.values()) else e.get("state"))
        link = posts.get("instagram", {}).get("link") or posts.get("tiktok", {}).get("link") or e.get("link") or buffer_post.DASH
        error = "; ".join(f"{PLATFORM_NAMES[s]}: {p['error']}" for s, p in posts.items() if p.get("error"))
        mix = ""
        if gone and live:
            sent = [s for s, v in live.items() if v == "sent"]
            mix = (f"{names(gone)} was deleted in Buffer and won't go out; " +
                   (f"{names(sent)} went out." if len(sent) == len(live) else f"{names([s for s in live if s not in sent])} still goes out."))
        return {"state": state, "posts": posts, "link": link, "error": error, "mix": mix}

    def package_folder(self, folder, video):
        """The folder of the posted video (its buffer/ package sits next to it), only ever inside this approved folder."""
        base = os.path.realpath(folder)
        if video:
            for top in (folder, office_root(folder)):
                path = os.path.realpath(os.path.join(top, video)) if top else ""
                if path and os.path.isfile(path) and os.path.commonpath([base, path]) == base:
                    return os.path.dirname(path)
        return folder

    def moved(self, folder, when):
        """The post's time changed: its dated task on the board moves with it."""
        task = self.record(folder).get("_task")
        if task and self.on_move:
            try:
                self.on_move(folder, task, when)
            except Exception:                                  # the board is a nice-to-have
                pass

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
            try:
                self.claim(folder)                              # a Change or Cancel on this folder waits, and the other way round
            except PostError:
                continue
            try:
                self.refresh_buffer(folder, self.record(folder), now)   # Buffer publishes by itself: ask it how the posts went
            except Exception as e:
                print("buffer status:", e)
            finally:
                self.busy.discard(folder)
            try:
                self.claim(folder)                              # a reschedule or cancel waits, and the other way round
            except PostError:
                continue
            try:
                for p in PLATFORMS:
                    e = self.record(folder).get(p) or {}     # fresh: a reschedule may just have moved it
                    if p == "buffer" or e.get("state") != "scheduled" or not e.get("when") or e["when"] > now:
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
                                  warning=("Posted late: the computer or Agents HQ was off at the scheduled time." if late and not job.get("tries") else ""), **extra)
                    except IgRefused as ex:
                        self.later(folder, p, job, ex, now)
                    except Exception as ex:
                        self.note(folder, p, state="failed", error=str(ex)[:600])
                    finally:
                        PROGRESS.report = None
            finally:
                self.busy.discard(folder)
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
                    name = PLATFORM_NAMES[p]
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
        if cover:                                              # owner, 2026-11-02: never public without the thumbnail, so it goes
            progress(86, "setting your thumbnail")             # on before the finish call publishes the Reel
            try:
                self.fb_thumb(vid, cover, tok, waits=(0, 10, 20))
            except (PostError, OSError) as e:                  # before the finish Facebook may not take it yet: keep it a
                draft = {"upload_phase": "finish", "video_id": vid, "video_state": "DRAFT",     # draft, never public
                         "description": text.get("caption", ""), "access_token": tok}
                try:
                    http("POST", f"{GRAPH}/{page}/video_reels", data=draft)
                    self.fb_thumb(vid, cover, tok)
                    how = "Your thumbnail is on it: check it in Meta Business Suite (Content → Drafts) and publish it there"
                except (PostError, OSError):
                    how = "Set your thumbnail on it in Meta Business Suite (Content → Drafts), then publish it there"
                raise PostError(f"Facebook would not take your thumbnail before publishing ({str(e)[:120]}), so the Reel was saved as "
                                f"a draft, not public. {how}.") from None
        finish = {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": text.get("caption", ""), "access_token": tok}
        if when:                                               # Facebook holds it and publishes it at that time
            finish.update(video_state="SCHEDULED", scheduled_publish_time=str(int(when)))
        progress(90, "publishing")
        http("POST", f"{GRAPH}/{page}/video_reels", data=finish)
        if cover:                                              # once more after the finish, in case processing dropped it
            try:
                self.fb_thumb(vid, cover, tok, waits=(5,))
            except (PostError, OSError):
                pass                                           # the one set before the finish stays
        return f"https://www.facebook.com/reel/{vid}", {}

    def fb_thumb(self, vid, cover, tok, waits=(0, 15, 30, 60)):
        """The owner's thumbnail on a Facebook video; Facebook may still be processing it, so a few tries."""
        with open(cover, "rb") as f:
            img = f.read()
        for wait in waits:
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

    def post_instagram_file(self, video, cover, text, m):
        tok, ig = m["page_token"], m["ig_id"]
        base = {"media_type": "REELS", "caption": text.get("caption", ""), "share_to_feed": "true", "access_token": tok}
        parked, extra = [], {}                                 # the hidden cover on the Page
        try:
            progress(3, "sending your thumbnail")
            # the owner's thumbnail always goes with it (owner, 2026-11-02: "don't keep forgetting"): never post without
            # it. No cover link, or Instagram refuses: try again in a moment, then later by itself (IgRefused)
            url = self.cover_url(cover, m, parked) if cover else ""
            if cover and not url:
                raise IgRefused("Instagram's copy of your thumbnail could not be made")
            cid = err = None
            for wait in (0, 30, 90):                           # a refusal can pass a moment later
                if wait:
                    progress(5, f"Instagram refused the upload, trying again in {wait} seconds")
                    time.sleep(wait)
                cid, err = self.ig_direct(video, dict(base, cover_url=url) if url else base, m)
                if cid or err != "upload refused":
                    break
            if not cid and err == "upload refused":
                raise IgRefused("Instagram refused the upload")
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

    # TikTok draft: init an inbox upload → PUT the file in chunks → wait until TikTok has it in the account's inbox
    def post_tiktok(self, video, cover, text, when=None, channel=""):
        tok = self.accounts.tiktok_token(channel)
        auth = {"Authorization": "Bearer " + tok, "Content-Type": "application/json; charset=UTF-8"}
        size = os.path.getsize(video)
        # one piece up to 64 MB; above that 10 MB pieces, the rest joined to the last (TikTok: 5–64 MB each, the last up to 128 MB)
        chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
        count = max(1, size // chunk)
        progress(3, "starting the TikTok upload")
        _, _, j = http("POST", TT_API + "/post/publish/inbox/video/init/", headers=auth, body=json.dumps(
            {"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}}).encode())
        err = (j.get("error") or {}) if isinstance(j, dict) else {}
        data = (j.get("data") or {}) if isinstance(j, dict) else {}
        if err.get("code") not in (None, "", "ok") or not data.get("upload_url"):
            raise PostError("TikTok refused the upload: " + (err.get("message") or err.get("code") or "no upload address"))
        ctype = "video/quicktime" if video.lower().endswith(".mov") else "video/mp4"
        with open(video, "rb") as f:
            for i in range(count):
                first = i * chunk
                last = size - 1 if i == count - 1 else first + chunk - 1
                f.seek(first)
                part = f.read(last - first + 1)
                progress(5 + 80 * (i + 1) / count, "uploading the video to TikTok")
                http("PUT", data["upload_url"], body=part, timeout=1800,
                     headers={"Content-Type": ctype, "Content-Length": str(len(part)), "Content-Range": f"bytes {first}-{last}/{size}"})
        for i in range(60):                                    # up to 5 minutes for TikTok to put it in the inbox
            progress(86 + 12 * (1 - math.exp(-i / 10)), "TikTok is processing the video")
            _, _, st = http("POST", TT_API + "/post/publish/status/fetch/", headers=auth, body=json.dumps({"publish_id": data["publish_id"]}).encode())
            d = (st.get("data") or {}) if isinstance(st, dict) else {}
            if d.get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                return "", {"warning": "Sent to your TikTok drafts. Open TikTok, tap the notification in your inbox, paste the caption (copy it on the "
                                       "posting screen), add a sound if you like, and post."}
            if d.get("status") == "FAILED":
                raise PostError("TikTok could not take the video: " + str(d.get("fail_reason") or "no reason given"))
            time.sleep(5)
        return "", {"warning": "TikTok is still processing the video. It should appear in your TikTok inbox soon; check the TikTok app."}

    # Buffer: the video with the cover as frame 1 → the public media host → one Instagram Reel + one TikTok post in Buffer
    BUFFER_EVERY = 10 * 60                                     # ask Buffer about a video's posts at most this often

    def post_buffer(self, video, cover, text, when=None, channel=""):
        b = self.accounts.get("buffer", channel)
        if not b.get("api_key"):
            raise PostError("Buffer is not connected (user menu → Accounts → Buffer)")
        targets = [(s, b.get(s)) for s in buffer_post.SERVICES if b.get(s)]
        if not targets:
            raise PostError("pick your Instagram and TikTok channels under Accounts → Buffer first")
        host_cfg = self.accounts.get("media", channel) or self.accounts.get("media")
        if not buffer_post.host_ready(host_cfg):
            raise PostError("Buffer needs a public address for the video: set up the media host under Accounts → Buffer, "
                            "or post this one by hand in Buffer with the package below")
        if not cover:
            raise PostError("pick your thumbnail first: the Buffer video starts with it")
        folder = os.path.dirname(os.path.abspath(video))
        step = "making the Buffer video with your cover as frame 1"
        progress(2, step)
        try:
            st = self.covers.ensure(folder, video, cover, text.get("caption"), text.get("title"), progress=lambda pct: progress(2 + 0.38 * pct, step))
            host = buffer_post.MediaHost(host_cfg)
            key = host.key(os.path.basename(folder) + ".mp4")
            progress(41, "uploading the video to your media host")
            url = host.put(self.covers.final(folder), key, "video/mp4", progress=lambda pct: progress(pct, "uploading the video to your media host"), lo=41, hi=80)
            progress(81, "checking the public address")
            host.fetch_public(url, 4096)
        except buffer_post.BufferError as e:
            raise PostError(str(e)) from None
        api = buffer_post.Buffer(b["api_key"])
        thumb_ms = int((st.get("hold") or 0.1) * 1000 / 2)    # the middle of the cover flash, as Buffer's thumbnail frame
        made, errors = {}, []
        for i, (service, cid) in enumerate(targets):
            progress(84 + 6 * i, f"creating the {PLATFORM_NAMES[service]} post in Buffer")
            try:
                p = api.create_post(cid, service, text.get("caption", ""), url, when, text.get("title", ""), thumb_ms)
                made[service] = {"id": p.get("id"), "status": p.get("status") or ("scheduled" if when else "sending"), "link": p.get("externalLink") or ""}
            except buffer_post.BufferError as e:
                errors.append(f"{PLATFORM_NAMES[service]}: {e}")
        if not made:
            raise PostError("; ".join(errors))
        extra = {"posts": made, "media": {"key": key, "url": url}, "checked": 0}
        if errors:
            extra["warning"] = (f"Buffer has the {' and '.join(PLATFORM_NAMES[s] for s in made)} post; the other failed ({'; '.join(errors)}). "
                                "Make that one in Buffer by hand with the same video and caption.")
        return buffer_post.DASH, extra

    BUFFER_FAR = 30 * 60                                       # ...and every half hour while its time is still over an hour off

    def refresh_buffer(self, folder, r, now):
        """Buffer posts and publishes on its own schedule: once in a while ask it how each post went, keep the links,
        and pick up what the owner changed in Buffer itself (a new time, a deleted post). run_due holds the folder."""
        e = r.get("buffer") or {}
        posts = e.get("posts") or {}
        if e.get("state") not in ("scheduled", "posted") or not posts or e.get("manual"):
            return
        out_since = (e.get("when") or e.get("at") or now) + 86400       # a sent post without a link: stop asking after a day
        finished = lambda p: p.get("status") in ("error", "deleted") or (p.get("status") == "sent" and (p.get("link") or now > out_since))
        if all(finished(p) for p in posts.values()):
            return
        far = e.get("state") == "scheduled" and e.get("when") and e["when"] > now + 3600
        if now - (e.get("checked") or 0) < (self.BUFFER_FAR if far else self.BUFFER_EVERY):
            return
        b = self.accounts.get("buffer", folder_channel(folder))
        if not b.get("api_key"):
            return
        api = buffer_post.Buffer(b["api_key"])
        posts = {s: dict(p) for s, p in posts.items()}
        for service, p in posts.items():
            if not p.get("id") or finished(p):
                continue
            try:
                q = api.post(p["id"])
            except buffer_post.BufferError as ex:
                self.note(folder, "buffer", checked=now, warning=f"Buffer did not answer about the {PLATFORM_NAMES[service]} post: {str(ex)[:200]}")
                return
            if q:
                self.buffer_take(p, q)
            elif p.get("status") != "sent":                     # the owner deleted it in Buffer (a sent post stays sent)
                p.update(status="deleted", link="")
        out = self.buffer_outcome(e, posts)
        upd = dict(out, checked=now)
        dues = {s: p["due"] for s, p in posts.items() if self.buffer_open(p) and p.get("due")}
        times = set(dues.values())
        say = lambda t: time.strftime("%a %d %b %H:%M", time.localtime(t))
        if out["state"] == "cancelled":
            upd["warning"] = "Deleted in Buffer, so it won't go out."
        elif len(times) > 1:                                    # moved in Buffer, one post only
            upd["warning"] = ("Instagram and TikTok are at different times in Buffer: " +
                              ", ".join(f"{PLATFORM_NAMES[s]} {say(t)}" for s, t in dues.items()) + ". " + out["mix"]).strip()
        else:
            upd["warning"] = out["mix"] or ("" if out["state"] == "posted" else e.get("warning", ""))
            if len(times) == 1 and e.get("when") and abs(min(times) - e["when"]) > 60:   # moved in Buffer
                upd["when"] = min(times)
        self.note(folder, "buffer", **upd)
        if upd.get("when"):
            self.moved(folder, upd["when"])
        if out["state"] in ("posted", "failed", "cancelled"):
            self.check_finished(folder)

    # YouTube Short: resumable upload (vertical and short is what makes it a Short), then the cover as thumbnail
    def post_youtube(self, video, cover, text, when=None, channel=""):
        tok = self.accounts.youtube_token(channel)
        meta = {"snippet": {"title": text.get("title") or "Short", "description": text.get("description", ""), "categoryId": "22"},
                "status": {"privacyStatus": text.get("privacy") if text.get("privacy") in ("public", "unlisted", "private") else "public",
                           "selfDeclaredMadeForKids": False}}
        want = dict(meta["status"])
        if when:                                               # private now, YouTube makes it public at that time
            want.update(privacyStatus="private", publishAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(when))))
        # owner, 2026-11-02: never public without the thumbnail. With one it goes up private (no publish time) and opens
        # (or gets its schedule) only once the thumbnail is on; if YouTube refuses the thumbnail it simply stays private.
        meta["status"] = {k: v for k, v in dict(want, privacyStatus="private").items() if k != "publishAt"} if cover else want
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
        auth = {"Authorization": "Bearer " + tok}
        if cover:
            progress(94, "setting your thumbnail")
            err = None
            with open(cover, "rb") as f:
                img = f.read()
            for wait in (0, 15, 45):                           # YouTube may still be processing the upload
                time.sleep(wait)
                try:
                    http("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", body=img,
                         headers=dict(auth, **{"Content-Type": "image/png" if cover.lower().endswith(".png") else "image/jpeg"}))
                    err = None
                    break
                except (PostError, OSError) as e:
                    err = e
            if err:                                            # it went up private, so it simply stays private
                raise PostError(f"YouTube would not take your thumbnail ({err}), so the Short stays private, never public: "
                                f"https://youtube.com/shorts/{vid} . Set the thumbnail in YouTube Studio and make it public there.")
            if when and when - time.time() < 120:              # the upload took past the time: open it now
                want = {k: v for k, v in want.items() if k != "publishAt"}
                want["privacyStatus"] = text.get("privacy") if text.get("privacy") in ("public", "unlisted") else "public"
            if want != meta["status"]:
                progress(97, "scheduling it" if "publishAt" in want else f"making it {want['privacyStatus']}")
                try:
                    _, _, v = http("PUT", "https://www.googleapis.com/youtube/v3/videos?part=status", body=json.dumps(
                        {"id": vid, "status": want}).encode(), headers=dict(auth, **{"Content-Type": "application/json; charset=UTF-8"}))
                except (PostError, OSError) as e:              # e.g. connected before the edit permission was asked for
                    raise PostError(f"On YouTube with your thumbnail, but still private ({e}): https://youtube.com/shorts/{vid} . "
                                    f"Make it {'scheduled' if 'publishAt' in want else want['privacyStatus']} in YouTube Studio, and "
                                    "reconnect YouTube once (user menu → Accounts) so it happens by itself.") from None
        privacy = (v.get("status") or {}).get("privacyStatus", "")
        if privacy and privacy != want["privacyStatus"] and not when:
            extra["warning"] = (f"YouTube set it to {privacy}: uploads from a new Google API project stay private until Google audits "
                                "the project. Make it public in YouTube Studio if it lets you, or apply for the audit.")
        if when:
            extra["warning"] = ("Scheduled in YouTube Studio for that time. If your Google project hasn't passed the YouTube audit yet, "
                                "YouTube keeps it private even then.")
        return f"https://youtube.com/shorts/{vid}", extra
