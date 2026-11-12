"""Instagram and TikTok through Buffer (buffer.com), with the owner's cover as the first frames of the video.

Why Buffer: Instagram's own upload host kept refusing Reels from Agents HQ, and TikTok's API only fills the drafts
folder. Buffer posts to both from one place, with one caption, and the two platforms show the same cover because the
cover is the first frames of the video itself (cover_flash.py): Buffer, Instagram and TikTok all take frame 0 as the
thumbnail. Facebook and YouTube keep going out straight from Agents HQ, as before.

Two ways, both from the posting screen in the app:
  by hand   Agents HQ makes the Buffer package next to the approved video: approved/<name>/buffer/final.mp4 (cover as
            frame 1), cover.jpg, caption.txt and title.txt. The owner drags final.mp4 into Buffer, pastes the one
            caption for Instagram and TikTok, schedules, and presses "Posted in Buffer" so the board knows.
  from HQ   With a Buffer API key (publish.buffer.com/settings/api) and a public media host, the owner's Post button
            uploads final.mp4 to the host and creates the Instagram Reel and the TikTok post in Buffer in one go, now
            or scheduled (Buffer publishes at that time by itself; the computer may be off).

Buffer's API (https://api.buffer.com, GraphQL, "Authorization: Bearer <key>") has no upload: the video must be at a
public https address that stays up until Buffer publishes it. MediaHost is any S3-compatible bucket with public reads
(Cloudflare R2's free plan is enough): the file is PUT there with a Signature V4 and read back once to prove the public
address works. Stdlib only. Agents never call any of this (.claude/settings.json denies /api/publish and /api/accounts).
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import cover_flash

API = "https://api.buffer.com"
DASH = "https://publish.buffer.com"
PKG = "buffer"                                                 # approved/<name>/buffer/: the package for Buffer
FINAL, COVER, CAPTION, TITLE, META = "final.mp4", "cover.jpg", "caption.txt", "title.txt", "package.json"
UA = "AgentsHQ/1.0 (+https://github.com/johnooi5593-hue/Agents-HQ)"
SERVICES = ("instagram", "tiktok")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
TIKTOK_TITLE = 90                                              # TikTok's title field
IG_CAPTION = 2200                                              # Instagram's caption limit: the one caption fits both


class BufferError(Exception):
    pass


def iso_utc(when):
    """A unix time as Buffer's dueAt: 2026-03-10T15:00:00.000Z."""
    return datetime.datetime.fromtimestamp(int(when), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


class Buffer:
    """The Buffer API for one API key."""

    def __init__(self, key, opener=None):
        self.key, self.opener = (key or "").strip(), opener or (lambda req, timeout: _open(req, timeout))
        if not self.key:
            raise BufferError("paste your Buffer API key first (publish.buffer.com → Settings → API)")

    def gql(self, query, variables=None, timeout=90):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with self.opener(req, timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 401:
                raise BufferError("Buffer did not accept this API key. Make a new one at publish.buffer.com → Settings → API and connect again.") from None
            if e.code == 429:
                raise BufferError("Buffer's rate limit was reached; try again in " + (e.headers.get("Retry-After") or "a few") + " seconds.") from None
            raise BufferError(f"Buffer answered {e.code}: {self._message(raw) or raw[:200]}") from None
        except urllib.error.URLError as e:
            raise BufferError(f"no connection to Buffer ({e.reason})") from None
        try:
            j = json.loads(raw)
        except ValueError:
            raise BufferError("Buffer's answer was not JSON: " + raw[:200]) from None
        if j.get("errors"):
            first = j["errors"][0] if isinstance(j["errors"], list) and j["errors"] else {}
            code = ((first.get("extensions") or {}).get("code") or "") if isinstance(first, dict) else ""
            msg = (first.get("message") if isinstance(first, dict) else str(first)) or "unknown error"
            if code == "UNAUTHORIZED":
                raise BufferError("Buffer did not accept this API key. Make a new one at publish.buffer.com → Settings → API and connect again.")
            raise BufferError(f"Buffer: {msg}" + (f" ({code})" if code else ""))
        return j.get("data") or {}

    @staticmethod
    def _message(raw):
        try:
            j = json.loads(raw)
            return (j.get("errors") or [{}])[0].get("message") or j.get("message") or ""
        except (ValueError, AttributeError, IndexError, TypeError):
            return ""

    def organizations(self):
        data = self.gql("query { account { organizations { id name } } }")
        return [o for o in ((data.get("account") or {}).get("organizations") or []) if isinstance(o, dict) and o.get("id")]

    def channels(self, org_id):
        q = ("query { channels(input: { organizationId: %s }) { id name displayName service avatar isDisconnected isLocked isQueuePaused } }"
             % json.dumps(str(org_id)))
        return [c for c in (self.gql(q).get("channels") or []) if isinstance(c, dict) and c.get("id")]

    def all_channels(self):
        """Every channel of every organization the key can see: [{id, name, service, avatar, org, orgName, problem}]."""
        out = []
        for org in self.organizations():
            for c in self.channels(org["id"]):
                problem = "disconnected in Buffer" if c.get("isDisconnected") else "locked in Buffer" if c.get("isLocked") else ""
                out.append({"id": c["id"], "name": c.get("displayName") or c.get("name") or c["id"], "service": str(c.get("service") or "").lower(),
                            "avatar": c.get("avatar") or "", "org": org["id"], "orgName": org.get("name") or "", "problem": problem})
        return out

    def create_post(self, channel_id, service, text, video_url, when=None, title="", thumbnail_ms=None):
        """One post in Buffer: now (shareNow) or at `when` (customScheduled). Returns Buffer's post {id, status, dueAt, ...}."""
        video = {"url": video_url}
        if thumbnail_ms is not None:
            video["metadata"] = {"thumbnailOffset": int(thumbnail_ms)}
        inp = {"channelId": channel_id, "text": text or "", "schedulingType": "automatic",
               "mode": "customScheduled" if when else "shareNow", "assets": [{"video": video}]}
        if when:
            inp["dueAt"] = iso_utc(when)
        meta = None
        if service == "instagram":
            meta = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        elif service == "tiktok" and title:
            meta = {"tiktok": {"title": title[:TIKTOK_TITLE]}}
        attempts = [dict(inp, metadata=meta), inp] if meta else [inp]   # a metadata field Buffer doesn't know yet: once more without it
        for i, attempt in enumerate(attempts):
            try:
                return self._create(attempt)
            except BufferError as e:
                if i == len(attempts) - 1 or not re.search(r"metadata|unknown field|invalid input|not defined", str(e), re.I):
                    raise
        raise BufferError("Buffer did not create the post")

    def _create(self, inp):
        q = ("mutation CreatePost($input: CreatePostInput!) { createPost(input: $input) { "
             "... on PostActionSuccess { post { id status dueAt externalLink } } ... on MutationError { message } } }")
        r = self.gql(q, {"input": inp}).get("createPost") or {}
        if isinstance(r, dict) and r.get("post"):
            return r["post"]
        raise BufferError("Buffer did not create the post: " + str((r or {}).get("message") or "no reason given"))

    def post(self, post_id):
        """Buffer's post, or {} when Buffer no longer has it (deleted in Buffer)."""
        q = "query { post(input: { id: %s }) { id status dueAt sentAt externalLink error { message } } }" % json.dumps(str(post_id))
        try:
            return self.gql(q).get("post") or {}
        except BufferError as e:
            if gone(e):
                return {}
            raise

    def edit_post(self, post_id, service, when=None, text=None, title=None):
        """Change a scheduled post in Buffer: its time (when), its caption (text) and TikTok's title. None keeps a field.
        Instagram keeps its Reel setting when the caption changes. Returns Buffer's post; titleKept: the title didn't change."""
        inp = {"id": str(post_id)}
        if when:
            inp.update(mode="customScheduled", dueAt=iso_utc(when))
        if text is not None:
            inp["text"] = str(text)[:IG_CAPTION]
        meta = None
        if service == "instagram" and text is not None:
            meta = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        elif service == "tiktok" and title is not None:
            meta = {"tiktok": {"title": str(title)[:TIKTOK_TITLE]}}
        attempts = [dict(inp, metadata=meta), inp] if meta else [inp]
        q = ("mutation EditPost($input: EditPostInput!) { editPost(input: $input) { "
             "... on PostActionSuccess { post { id status dueAt externalLink } } ... on MutationError { message } } }")
        for i, attempt in enumerate(attempts):
            try:
                r = self.gql(q, {"input": attempt}).get("editPost") or {}
                if isinstance(r, dict) and r.get("post"):
                    return dict(r["post"], titleKept=bool(i and service == "tiktok"))
                raise BufferError("Buffer did not change the post: " + str((r or {}).get("message") or "no reason given"))
            except BufferError as e:
                unknown = re.search(r"metadata|unknown field|not defined", str(e), re.I)   # a field this Buffer doesn't know yet
                if i == len(attempts) - 1 or not unknown:
                    raise
                if set(attempts[i + 1]) == {"id"}:              # only the title was asked, and Buffer won't take it
                    raise BufferError("Buffer did not take the new TikTok title: " + str(e)) from None
        raise BufferError("Buffer did not change the post")

    def delete_post(self, post_id):
        """Delete a post from Buffer (a scheduled one never goes out). A post Buffer no longer has counts as deleted."""
        q = ("mutation DeletePost($input: DeletePostInput!) { deletePost(input: $input) { "
             "... on DeletePostSuccess { id } ... on MutationError { message } } }")
        try:
            r = self.gql(q, {"input": {"id": str(post_id)}}).get("deletePost") or {}
        except BufferError as e:
            if gone(e):
                return str(post_id)
            raise
        if isinstance(r, dict) and r.get("id"):
            return r["id"]
        msg = str((r or {}).get("message") or "no reason given")
        if gone(msg):                                          # deletePost's own "Post not found": deleted already
            return str(post_id)
        raise BufferError("Buffer did not delete the post: " + msg)


def gone(err):
    """Buffer's GraphQL answer that the post isn't there (any more): its NOT_FOUND code, or deletePost's typed message.
    Never an HTTP 404 or any other text, so a proxy or endpoint fault can't make a live post look deleted."""
    text = str(err)
    if text.startswith("Buffer answered"):
        return False
    return text.rstrip().endswith("(NOT_FOUND)") or bool(re.fullmatch(r"\s*post (was )?not found\.?\s*", text, re.I))


def from_iso(value):
    """Buffer's dueAt (2026-03-10T15:00:00.000Z) as a unix time, or None."""
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:                                      # Buffer's times are UTC, with or without the Z
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


# -------------------------------------------------------------------- the public media host (S3-compatible)
HOST_FIELDS = ("endpoint", "bucket", "access_key", "secret_key", "public_url")


def host_ready(cfg):
    return bool(cfg) and all((cfg or {}).get(k) for k in HOST_FIELDS)


class Sending:
    def __init__(self, f, size, progress, lo=0, hi=100):
        self.f, self.size, self.progress, self.lo, self.hi, self.sent = f, max(1, size), progress, lo, hi, 0

    def read(self, n=-1):
        block = self.f.read(n)
        self.sent += len(block)
        if self.progress:
            self.progress(self.lo + (self.hi - self.lo) * self.sent / self.size)
        return block


class MediaHost:
    """An S3-compatible bucket whose objects are public to read: Cloudflare R2 (free), AWS S3, Backblaze B2, Wasabi…
    cfg: endpoint (https://<account>.r2.cloudflarestorage.com), bucket, access_key, secret_key, public_url
    (https://pub-….r2.dev or the owner's own domain in front of the bucket), region (R2: auto), prefix (agents-hq/)."""

    def __init__(self, cfg, opener=None, now=None):
        self.cfg = {k: str((cfg or {}).get(k) or "").strip() for k in HOST_FIELDS + ("region", "prefix")}
        self.cfg["region"] = self.cfg["region"] or "auto"
        self.cfg["prefix"] = (self.cfg["prefix"] or "agents-hq").strip("/") + "/"
        self.cfg["endpoint"] = self.cfg["endpoint"].rstrip("/")
        self.cfg["public_url"] = self.cfg["public_url"].rstrip("/")
        self.opener, self.now = opener or (lambda req, timeout: _open(req, timeout)), now or time.time
        if not host_ready(self.cfg):
            raise BufferError("the media host needs its endpoint, bucket, access key, secret key and public address")
        if not self.cfg["endpoint"].startswith("https://") or not self.cfg["public_url"].startswith("https://"):
            raise BufferError("the media host's endpoint and public address must start with https://")

    def key(self, name):
        """A fresh, unguessable key for one file: <prefix><random>/<safe name>."""
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "video.mp4"
        return f"{self.cfg['prefix']}{secrets.token_hex(12)}/{safe}"

    def url(self, key):
        return self.cfg["public_url"] + "/" + urllib.parse.quote(key, safe="/")

    def _sign(self, method, key, payload_hash, content_type="", extra=None, when=None):
        """AWS Signature V4 headers for one request to <endpoint>/<bucket>/<key>."""
        when = when or self.now()
        amz = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(when))
        day = amz[:8]
        u = urllib.parse.urlparse(self.cfg["endpoint"])
        host = u.netloc
        path = (u.path.rstrip("/") + "/" + urllib.parse.quote(self.cfg["bucket"], safe="") + "/" + urllib.parse.quote(key, safe="/~"))
        headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz}
        if content_type:
            headers["content-type"] = content_type
        for k, v in (extra or {}).items():
            headers[k.lower()] = v
        names = sorted(headers)
        canonical = "\n".join([method, path, "", "".join(f"{k}:{headers[k].strip()}\n" for k in names), ";".join(names), payload_hash])
        scope = f"{day}/{self.cfg['region']}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = ("AWS4" + self.cfg["secret_key"]).encode()
        for part in (day, self.cfg["region"], "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        auth = f"AWS4-HMAC-SHA256 Credential={self.cfg['access_key']}/{scope}, SignedHeaders={';'.join(names)}, Signature={sig}"
        out = {k: v for k, v in headers.items() if k != "host"}
        out["Authorization"] = auth
        return f"{u.scheme}://{host}{path}", out

    @staticmethod
    def _hash_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    def _request(self, method, url, headers, body=None, timeout=1800):
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers, **{"User-Agent": UA}))
        try:
            with self.opener(req, timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            m = re.search(r"<Message>(.*?)</Message>", raw) or re.search(r"<Code>(.*?)</Code>", raw)
            raise BufferError(f"the media host answered {e.code}" + (f": {m[1]}" if m else "")) from None
        except urllib.error.URLError as e:
            raise BufferError(f"no connection to the media host ({e.reason})") from None

    def put(self, path, key, content_type="application/octet-stream", progress=None, lo=0, hi=100):
        """Uploads a file; returns its public URL."""
        size = os.path.getsize(path)
        digest = self._hash_file(path)
        url, headers = self._sign("PUT", key, digest, content_type, {"content-length": str(size)})
        with open(path, "rb") as f:
            self._request("PUT", url, headers, Sending(f, size, progress, lo, hi))
        return self.url(key)

    def put_bytes(self, data, key, content_type="text/plain"):
        url, headers = self._sign("PUT", key, hashlib.sha256(data).hexdigest(), content_type, {"content-length": str(len(data))})
        self._request("PUT", url, headers, data, timeout=120)
        return self.url(key)

    def delete(self, key):
        url, headers = self._sign("DELETE", key, hashlib.sha256(b"").hexdigest())
        self._request("DELETE", url, headers, timeout=120)

    def fetch_public(self, url, limit=1 << 20):
        """Reads up to `limit` bytes from the public address, with no credentials: what Buffer will see."""
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes=0-{limit - 1}"})
        try:
            with self.opener(req, 60) as r:
                return r.status, r.read(limit)
        except urllib.error.HTTPError as e:
            raise BufferError(f"the public address answered {e.code} ({url}). Is public access on for this bucket, and is the public address right?") from None
        except urllib.error.URLError as e:
            raise BufferError(f"the public address could not be reached ({e.reason})") from None

    def check(self):
        """Uploads a small text file, reads it back from the public address, removes it. Returns the public URL that worked."""
        key, body = self.key("agents-hq-check.txt"), f"Agents HQ media host check {int(self.now())}".encode()
        url = self.put_bytes(body, key)
        _, got = self.fetch_public(url)
        try:
            self.delete(key)
        except BufferError:
            pass
        if got.strip() != body:
            raise BufferError(f"the public address returned something else than the file just uploaded ({url}); check the public address and the bucket")
        return url


# -------------------------------------------------------------------- the package next to the approved video
def stamp(path):
    try:
        st = os.stat(path)
        return f"{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        return ""


def cover_jpeg(ff, cover, out, w, h):
    """The cover exactly as it appears in frame 1 (fitted to the video), as a JPEG."""
    graph = cover_flash.fit_filter("0:v", w, h, "f") + ";[f]format=yuvj420p[o]"
    cmd = [ff, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", cover, "-filter_complex", graph, "-map", "[o]", "-frames:v", "1", "-q:v", "2", out]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, creationflags=NO_WINDOW)
        return r.returncode == 0 and os.path.isfile(out)
    except (OSError, subprocess.SubprocessError):
        return False


class CoverPackages:
    """Makes and tracks approved/<name>/buffer/ for one video + cover pick: final.mp4 (cover as frame 1), cover.jpg,
    caption.txt, title.txt and package.json. One make at a time per folder, in the background, with progress."""

    def __init__(self, frames=None):
        self.frames = frames or cover_flash.FRAMES
        self.lock, self.jobs = threading.Lock(), {}         # folder → {"progress", "video", "cover", "error", "done": Event}

    @staticmethod
    def dir(folder):
        return os.path.join(folder, PKG)

    def read(self, folder):
        try:
            with open(os.path.join(self.dir(folder), META), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, folder, meta):
        d = self.dir(folder)
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, META + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(d, META))

    def state(self, folder, video=None, cover=None):
        """What the posting screen shows: {"state": "none"|"making"|"ready"|"stale"|"failed", "progress", "error", "video",
        "cover", "files", "frames", "hold", "size", "caption", "title", "madeAt"}. video/cover: the owner's current pick
        (absolute paths); the package is "ready" only when it was made from exactly these files."""
        job = self.jobs.get(folder)
        meta = self.read(folder)
        final = os.path.join(self.dir(folder), FINAL)
        out = {"state": "none", "progress": None, "error": "", "frames": self.frames, "hold": None, "files": {}, "madeAt": None,
               "video": meta.get("video") or "", "cover": meta.get("cover") or "", "caption": meta.get("caption") or "", "title": meta.get("title") or ""}
        if job and not job["done"].is_set():
            out.update(state="making", progress=int(job["progress"]), video=os.path.basename(job["video"]), cover=os.path.basename(job["cover"]))
            return out
        if job and job.get("error"):
            out.update(state="failed", error=job["error"])
            return out
        if not meta or not os.path.isfile(final):
            return out
        out.update(hold=meta.get("hold"), frames=meta.get("frames") or self.frames, madeAt=meta.get("madeAt"), size=os.path.getsize(final),
                   files={k: f"{PKG}/{v}" for k, v in (("video", FINAL), ("cover", COVER), ("caption", CAPTION), ("title", TITLE)) if os.path.isfile(os.path.join(self.dir(folder), v))},
                   verify=meta.get("verify"))
        same = (not video or (os.path.basename(video) == meta.get("video") and stamp(video) == meta.get("videoStamp"))) and \
               (not cover or (os.path.basename(cover) == meta.get("cover") and stamp(cover) == meta.get("coverStamp")))
        out["state"] = "ready" if same else "stale"
        return out

    def start(self, folder, video, cover, caption=None, title=None):
        """Makes the package in the background (or just updates the texts when it is already made from these files)."""
        with self.lock:
            job = self.jobs.get(folder)
            if job and not job["done"].is_set():
                return self.state(folder, video, cover)
            st = self.state(folder, video, cover)
            if st["state"] == "ready":
                self.texts(folder, caption, title)
                return self.state(folder, video, cover)
            job = {"progress": 0, "video": video, "cover": cover, "error": "", "done": threading.Event(), "caption": caption, "title": title}
            self.jobs[folder] = job
        threading.Thread(target=self._run, args=(folder, job), daemon=True).start()
        return self.state(folder, video, cover)

    def _run(self, folder, job):
        try:
            self.make(folder, job["video"], job["cover"], job["caption"], job["title"], lambda pct: job.__setitem__("progress", pct))
        except Exception as e:                                # the thread must never die silently
            job["error"] = str(e)[:400]
        finally:
            job["done"].set()

    def make(self, folder, video, cover, caption=None, title=None, progress=None):
        """Makes the package now (this thread). Raises BufferError when it can't."""
        d = self.dir(folder)
        os.makedirs(d, exist_ok=True)
        final = os.path.join(d, FINAL)
        r = cover_flash.make(video, cover, final, self.frames, progress)
        if not r.get("ok"):
            raise BufferError("the Buffer video could not be made: " + (r.get("error") or "ffmpeg failed"))
        v = cover_flash.verify(final, cover, self.frames)
        if not v.get("ok"):
            raise BufferError("the Buffer video was made, but its first frame is not your cover (" + (v.get("error") or "?") + ")")
        ff = cover_flash.ffmpeg_path()
        cover_jpeg(ff, cover, os.path.join(d, COVER), r["width"], r["height"])
        meta = {"video": os.path.basename(video), "videoStamp": stamp(video), "cover": os.path.basename(cover), "coverStamp": stamp(cover),
                "frames": r["frames"], "hold": r["hold"], "fps": r["fps"], "duration": r["duration"], "width": r["width"], "height": r["height"],
                "verify": {"first": v["first"], "last": v["last"]}, "madeAt": int(time.time()),
                "caption": (caption or "")[:IG_CAPTION], "title": (title or "")[:TIKTOK_TITLE]}
        self._write(folder, meta)
        self.texts(folder, caption, title)
        return meta

    def texts(self, folder, caption=None, title=None):
        """caption.txt / title.txt next to final.mp4: the one caption for Instagram and TikTok, and TikTok's title."""
        d = self.dir(folder)
        if not os.path.isdir(d):
            return
        meta = self.read(folder)
        for text, name, key, limit in ((caption, CAPTION, "caption", IG_CAPTION), (title, TITLE, "title", TIKTOK_TITLE)):
            if text is None:
                continue
            text = str(text)[:limit]
            with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text.rstrip("\n") + "\n")
            meta[key] = text
        if meta:
            self._write(folder, meta)

    def ensure(self, folder, video, cover, caption=None, title=None, progress=None, wait=1800):
        """The package for these files, made now if it isn't yet (waits for a running make). Returns its state (ready)."""
        job = self.jobs.get(folder)
        if job and not job["done"].is_set():
            job["done"].wait(wait)
        st = self.state(folder, video, cover)
        if st["state"] != "ready":
            self.make(folder, video, cover, caption, title, progress)
            st = self.state(folder, video, cover)
        else:
            self.texts(folder, caption, title)
        if st["state"] != "ready":
            raise BufferError(st.get("error") or "the Buffer video is not ready")
        return st

    def final(self, folder):
        return os.path.join(self.dir(folder), FINAL)
