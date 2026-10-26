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
import json, os, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request

GRAPH = "https://graph.facebook.com/v23.0"
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PLATFORMS = ("facebook", "instagram", "youtube")
VIDEO_EXT = (".mp4", ".mov", ".m4v")


class PostError(Exception):
    pass


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

    def summary(self):
        """What the app may show: names only, never a token."""
        a = self.load()
        m, y = a.get("meta") or {}, a.get("youtube") or {}
        return {
            "facebook": {"connected": bool(m.get("page_token")), "name": m.get("page_name", "")},
            "instagram": {"connected": bool(m.get("page_token") and m.get("ig_id")), "name": ("@" + m["ig_username"]) if m.get("ig_username") else "",
                          "problem": "" if not m.get("page_token") or m.get("ig_id") else "no Instagram professional account is linked to this Facebook Page"},
            "youtube": {"connected": bool(y.get("refresh_token")), "name": y.get("channel", ""), "client": bool(y.get("client_id"))},
        }

    # ---------------------------------------------------------------- Meta
    def connect_meta(self, app_id, app_secret, user_token, page=""):
        app_id, app_secret, user_token = (str(x or "").strip() for x in (app_id, app_secret, user_token))
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
        with self.lock:
            a = self.load()
            a["meta"] = {"app_id": app_id, "app_secret": app_secret, "user_token": long_user, "page_id": chosen["id"],
                         "page_name": chosen.get("name", ""), "page_token": chosen["access_token"],
                         "ig_id": ig.get("id", ""), "ig_username": ig.get("username", ""), "at": int(time.time())}
            self.save(a)
        return {"page": chosen.get("name"), "pages": [p.get("name") for p in pages], "instagram": ig.get("username", "")}

    # ---------------------------------------------------------------- YouTube
    def youtube_begin(self, client_json, redirect):
        """Start the Google sign-in. client_json: the downloaded client_secret.json (or its text). Returns the URL to open."""
        a = self.load()
        y = a.get("youtube") or {}
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
        self.pending = {state: (cid, csec, redirect, time.time())}
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": YT_SCOPES,
            "access_type": "offline", "prompt": "consent", "state": state})

    def youtube_finish(self, state, code):
        got = self.pending.pop(state, None) if state else None
        if not got or time.time() - got[3] > 900:
            raise PostError("this sign-in link expired; press Connect YouTube again")
        cid, csec, redirect, _ = got
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
            a["youtube"] = {"client_id": cid, "client_secret": csec, "refresh_token": j["refresh_token"], "channel": channel, "at": int(time.time())}
            self.save(a)
        return channel

    def youtube_token(self):
        y = self.load().get("youtube") or {}
        if not y.get("refresh_token"):
            raise PostError("YouTube is not connected")
        _, _, j = http("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": y["client_id"], "client_secret": y["client_secret"], "refresh_token": y["refresh_token"], "grant_type": "refresh_token"})
        return j["access_token"]

    def disconnect(self, which):
        with self.lock:
            a = self.load()
            a.pop("meta" if which in ("meta", "facebook", "instagram") else which, None)
            self.save(a)


# -------------------------------------------------------------------- the post copy
def sections(text):
    """post.md → {"youtube": [option, ...], "instagram": [...], "facebook": [...], "tiktok": [...], "pinned": [...]}.
    A "## Platform" section is one option, or several under "### Option 1", "### Option 2"… for the owner to choose."""
    out, cur, opts, buf = {}, None, [], []

    def flush():
        if cur:
            opts.append("\n".join(buf).strip())
            out[cur] = [o for o in opts if o]
    for line in (text or "").replace("\r", "").split("\n"):
        m2 = re.match(r"^##\s+(.*)$", line)
        m3 = re.match(r"^###\s+(.*)$", line)
        if m2:
            flush()
            h = m2[1].lower()
            cur = ("youtube" if "youtube" in h else "instagram" if "instagram" in h else "facebook" if "facebook" in h
                   else "tiktok" if "tiktok" in h else "pinned" if "pinned" in h else None)
            opts, buf = [], []
        elif m3 and cur:
            if "\n".join(buf).strip():
                opts.append("\n".join(buf).strip())
            buf = []
        elif cur:
            buf.append(line)
    flush()
    return out


def clean(text):
    return re.sub(r"\*\*|__", "", text or "").strip()


def drafts(folder):
    """The text each platform gets, from post.md (the owner can edit it in the app before posting)."""
    try:
        with open(os.path.join(folder, "post.md"), encoding="utf-8") as f:
            s = sections(f.read())
    except OSError:
        s = {}

    def youtube(yt):
        yt = clean(yt)
        title = re.search(r"^\s*[-*]?\s*title\s*[:：]\s*(.+)$", yt, re.I | re.M)
        desc = re.search(r"^\s*[-*]?\s*description\s*[:：]\s*(.*)$", yt, re.I | re.M | re.S)
        title = title[1].strip() if title else (yt.split("\n")[0].strip() if yt else os.path.basename(folder).replace("-", " "))
        description = desc[1].strip() if desc else "\n".join(yt.split("\n")[1:]).strip()
        description = re.sub(r"^\s*[-*]?\s*(hashtags|tags)\s*[:：]\s*", "", description, flags=re.I | re.M)
        if "#shorts" not in (title + description).lower():
            description = (description + "\n#Shorts").strip()
        return {"title": title[:100], "description": description[:4900]}
    yts = [youtube(o) for o in s.get("youtube") or [""]]
    igs = [{"caption": clean(o)[:2200]} for o in s.get("instagram") or []] or [{"caption": ""}]
    fbs = [{"caption": clean(o)} for o in s.get("facebook") or []] or [dict(o) for o in igs]
    return {"youtube": {**yts[0], "options": yts}, "instagram": {**igs[0], "options": igs}, "facebook": {**fbs[0], "options": fbs}}


def media(folder):
    """The finished video and the cover in an approved folder."""
    names = sorted(os.listdir(folder))
    vids = [n for n in names if n.lower().endswith(VIDEO_EXT)]
    rank = lambda n: (0 if re.match(r"(edit|final|reel)\b", n, re.I) else 2 if re.search(r"clean|nocap|no-captions", n, re.I) else 3 if n.lower().startswith("cut") else 1)
    vids.sort(key=rank)
    covers = [n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png"))]
    covers.sort(key=lambda n: 0 if "cover" in n.lower() else 1)
    return (os.path.join(folder, vids[0]) if vids else None), (os.path.join(folder, covers[0]) if covers else None)


# -------------------------------------------------------------------- posting
class Publisher:
    def __init__(self, root, accounts):
        self.root, self.accounts, self.lock, self.busy = root, accounts, threading.Lock(), set()

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
            r[platform] = {**r.get(platform, {}), **kw, "at": int(time.time())}
            with open(self.record_path(folder), "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1, ensure_ascii=False)

    def payload(self, folder):
        video, cover = media(folder)
        return {"accounts": self.accounts.summary(), "drafts": drafts(folder), "posted": self.record(folder),
                "video": os.path.basename(video) if video else "", "cover": os.path.basename(cover) if cover else "",
                "busy": folder in self.busy}

    def start(self, folder, chosen, video_name="", cover_name=""):
        """chosen: {platform: {text fields}}; video_name / cover_name: the files the owner picked in the folder.
        Posts in the background; returns the platforms started."""
        video, cover = media(folder)
        names = set(os.listdir(folder))
        if video_name:
            if video_name not in names or not video_name.lower().endswith(VIDEO_EXT):
                raise PostError("that video is not in this folder")
            video = os.path.join(folder, video_name)
        if cover_name:
            if cover_name not in names or not cover_name.lower().endswith((".jpg", ".jpeg", ".png")):
                raise PostError("that thumbnail is not in this folder")
            cover = os.path.join(folder, cover_name)
        if not video:
            raise PostError("no video in this folder")
        summary = self.accounts.summary()
        todo = [p for p in PLATFORMS if p in chosen and summary[p]["connected"]]
        if not todo:
            raise PostError("pick at least one connected account")
        done = self.record(folder)
        again = [p for p in todo if (done.get(p) or {}).get("state") == "posted" and not chosen[p].get("again")]
        if again:
            raise PostError(f"already posted to {', '.join(again)}; tick 'post again' to post a second time")
        if folder in self.busy:
            raise PostError("still posting this one")
        self.busy.add(folder)
        for p in todo:
            self.note(folder, p, state="waiting", error="", warning="", link=done.get(p, {}).get("link", ""),
                      video=os.path.basename(video), cover=os.path.basename(cover) if cover else "")

        def one(p):                                             # every platform at the same time
            self.note(folder, p, state="posting", error="")
            try:
                link, extra = getattr(self, "post_" + p)(video, cover, chosen[p])
                self.note(folder, p, state="posted", link=link, error="", **extra)
            except Exception as e:                              # one platform failing never stops the others
                self.note(folder, p, state="failed", error=str(e)[:400])

        def work():
            try:
                threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in todo]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                self.busy.discard(folder)
        threading.Thread(target=work, daemon=True).start()
        return todo

    # Facebook Page Reel: start → upload the file to rupload → finish (published)
    def post_facebook(self, video, cover, text):
        m = self.accounts.load().get("meta") or {}
        tok, page = m["page_token"], m["page_id"]
        _, _, j = http("POST", f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok})
        vid, upload = j["video_id"], j.get("upload_url") or f"https://rupload.facebook.com/video-upload/v23.0/{j['video_id']}"
        size = os.path.getsize(video)
        with open(video, "rb") as f:
            http("POST", upload, body=f, headers={"Authorization": "OAuth " + tok, "offset": "0", "file_size": str(size),
                                                    "Content-Length": str(size)}, timeout=1800)
        http("POST", f"{GRAPH}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                         "description": text.get("caption", ""), "access_token": tok})
        return f"https://www.facebook.com/reel/{vid}", {}

    def cover_url(self, cover, m):
        """Instagram wants the cover as a URL: park it on the Page as an unpublished photo and use its address."""
        if not cover:
            return ""
        try:
            boundary = "hq" + secrets.token_hex(8)
            with open(cover, "rb") as f:
                img = f.read()
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"published\"\r\n\r\nfalse\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"access_token\"\r\n\r\n{m['page_token']}\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; filename=\"cover.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() \
                + img + f"\r\n--{boundary}--\r\n".encode()
            _, _, j = http("POST", f"{GRAPH}/{m['page_id']}/photos", body=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            _, _, p = http("GET", f"{GRAPH}/{j['id']}?" + urllib.parse.urlencode({"fields": "images", "access_token": m["page_token"]}))
            return (p.get("images") or [{}])[0].get("source", "")
        except (PostError, KeyError, OSError):
            return ""                                          # Instagram then picks a frame itself

    # Instagram Reel: container (resumable) → upload to rupload → wait until processed → publish
    def post_instagram(self, video, cover, text):
        m = self.accounts.load().get("meta") or {}
        tok, ig = m["page_token"], m["ig_id"]
        params = {"media_type": "REELS", "upload_type": "resumable", "caption": text.get("caption", ""), "share_to_feed": "true", "access_token": tok}
        url = self.cover_url(cover, m)
        if url:
            params["cover_url"] = url
        _, _, j = http("POST", f"{GRAPH}/{ig}/media", data=params)
        cid = j["id"]
        size = os.path.getsize(video)
        with open(video, "rb") as f:
            http("POST", j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v23.0/{cid}", body=f,
                 headers={"Authorization": "OAuth " + tok, "offset": "0", "file_size": str(size), "Content-Length": str(size)}, timeout=1800)
        for _ in range(120):                                   # up to 10 minutes of processing
            _, _, s = http("GET", f"{GRAPH}/{cid}?" + urllib.parse.urlencode({"fields": "status_code,status", "access_token": tok}))
            if s.get("status_code") == "FINISHED":
                break
            if s.get("status_code") in ("ERROR", "EXPIRED"):
                raise PostError("Instagram could not process the video: " + str(s.get("status") or s.get("status_code")))
            time.sleep(5)
        else:
            raise PostError("Instagram is still processing the video after 10 minutes; try Post again later")
        _, _, p = http("POST", f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok})
        link = ""
        try:
            _, _, q = http("GET", f"{GRAPH}/{p['id']}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tok}))
            link = q.get("permalink", "")
        except PostError:
            pass
        return link, {}

    # YouTube Short: resumable upload (vertical and short is what makes it a Short), then the cover as thumbnail
    def post_youtube(self, video, cover, text):
        tok = self.accounts.youtube_token()
        meta = {"snippet": {"title": text.get("title") or "Short", "description": text.get("description", ""), "categoryId": "22"},
                "status": {"privacyStatus": text.get("privacy") if text.get("privacy") in ("public", "unlisted", "private") else "public",
                           "selfDeclaredMadeForKids": False}}
        size = os.path.getsize(video)
        _, h, _ = http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                       body=json.dumps(meta).encode(), headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json; charset=UTF-8",
                                                               "X-Upload-Content-Type": "video/*", "X-Upload-Content-Length": str(size)})
        where = next((v for k, v in h.items() if k.lower() == "location"), None)
        if not where:
            raise PostError("YouTube did not start the upload")
        with open(video, "rb") as f:
            _, _, v = http("PUT", where, body=f, headers={"Authorization": "Bearer " + tok, "Content-Type": "video/*", "Content-Length": str(size)}, timeout=3600)
        vid, extra = v["id"], {}
        privacy = (v.get("status") or {}).get("privacyStatus", "")
        if privacy and privacy != meta["status"]["privacyStatus"]:
            extra["warning"] = (f"YouTube set it to {privacy}: uploads from a new Google API project stay private until Google audits "
                                "the project. Make it public in YouTube Studio if it lets you, or apply for the audit.")
        if cover:
            try:
                with open(cover, "rb") as f:
                    img = f.read()
                http("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", body=img,
                     headers={"Authorization": "Bearer " + tok, "Content-Type": "image/png" if cover.lower().endswith(".png") else "image/jpeg"})
            except PostError as e:
                extra["warning"] = (extra.get("warning", "") + f" The cover was not set ({e}); custom thumbnails need a verified channel.").strip()
        return f"https://youtube.com/shorts/{vid}", extra
