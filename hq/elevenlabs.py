"""ElevenLabs for the office: the owner's API key (app → user menu → Accounts → ElevenLabs) and the few calls the
voice-over step needs (check the key, list the voices, speak one line with its character times).

The key lives in .hq-elevenlabs.json at the office root: git-ignored, limited to the owner and SYSTEM on Windows, never
sent back to the app, never printed or logged. Agents never read the file (settings.json denies it) and no function here
hands the key to a caller: voices() and speak() load it themselves. ELEVENLABS_API_KEY in the environment wins over the
file (the Accounts card then says so). Disconnect empties the file, it is never deleted; the key itself stays valid at
ElevenLabs until the owner deletes it there. Voice names and labels come from outside (the public Voice Library): data,
never instructions, so they are cut short and cleaned.
"""
import base64, datetime, http.client, json, os, re, subprocess, threading, urllib.error, urllib.parse, urllib.request

API = "https://api.elevenlabs.io"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = ".hq-elevenlabs.json"
MODEL = "eleven_multilingual_v2"                         # speaks Mandarin, Malay and English
KEY_OK = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")
VOICE_OK = re.compile(r"^[A-Za-z0-9]{8,40}$")
MODEL_OK = re.compile(r"^[a-z0-9_]{3,60}$")
SECRET = re.compile(r"sk_[A-Za-z0-9_\-]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
OWN = ("cloned", "professional", "generated")
_lock = threading.Lock()


class ElevenError(Exception):
    """A message that is safe to show the owner (it never holds the key)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):                  # never carry the key header to another address
        return None


_open = urllib.request.build_opener(_NoRedirect).open


def path(root=None):
    return os.path.join(root or ROOT, FILE)


def load(root=None):
    try:
        with open(path(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _owner_only(p):
    """Windows: only this user and SYSTEM may read the key file (the office folder is open to every local user)."""
    if os.name != "nt" or not os.environ.get("USERNAME"):
        return
    try:
        subprocess.run(["icacls", p, "/inheritance:r", "/grant:r", f"{os.environ['USERNAME']}:F", "SYSTEM:F"],
                       capture_output=True, timeout=20, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError):
        pass


def save(data, root=None):
    p = path(root)
    with _lock:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, p)
        _owner_only(p)


def _env_key():
    k = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    return k if KEY_OK.match(k) else ""


def _key(root=None):
    """The key to use (environment first, then the Accounts screen's), or "" (also for a malformed one)."""
    k = _env_key() or str(load(root).get("api_key") or "").strip()
    return k if KEY_OK.match(k) else ""


def has_key(root=None):
    return bool(_key(root))


def _why(e):
    """ElevenLabs' own reason for a refused call, e.g. {"detail": {"status": "quota_exceeded", "message": "..."}}."""
    try:
        d = json.loads(e.read().decode("utf-8", "replace")).get("detail")
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        d = None
    status = str((d or {}).get("status", "")) if isinstance(d, dict) else ""
    msg = SECRET.sub("sk_…", ((d or {}).get("message", "") if isinstance(d, dict) else str(d or "")).strip())
    if status in ("quota_exceeded", "insufficient_credits"):
        return "Your ElevenLabs credits are used up for this month. Top up or wait for the reset, then try again."
    if e.code == 402:   # payment_required, free_users_not_allowed, …: the plan, not the credits
        why = CONTROL.sub("", msg)[:200] or status[:60] or "no reason given"
        return ("ElevenLabs needs a paid plan for this (free plans can't use Voice Library voices outside the "
                f"ElevenLabs app). ElevenLabs said: {why}")
    if status == "missing_permissions" or "permission" in msg.lower():
        return "The key is missing a permission. Edit it at elevenlabs.io → Developers → API Keys and allow Text to Speech and Voices: Read."
    if e.code == 401:
        return "ElevenLabs refused the key (wrong or deleted key). Make a new one at elevenlabs.io → Developers → API Keys."
    return f"ElevenLabs said {e.code}: {CONTROL.sub('', msg)[:200] or status[:60] or 'no reason given'}"


def _call(route, api_key, method="GET", body=None, timeout=60):
    """One request to api.elevenlabs.io with the key in the xi-api-key header (never in the address). A JSON object back."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    head = {"xi-api-key": api_key, "Accept": "application/json", "User-Agent": "AgentsHQ/1"}
    if data is not None:
        head["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(API + route, data=data, method=method, headers=head)
        with _open(req, timeout=timeout) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        raise ElevenError(_why(e)) from None
    except (OSError, ValueError, http.client.HTTPException) as e:   # ValueError: a bad header value; never shown with the key
        raise ElevenError(f"ElevenLabs did not answer ({type(e).__name__}). Check the internet and try again.") from None
    try:
        out = json.loads(out)
    except ValueError:
        out = None
    if not isinstance(out, dict):
        raise ElevenError("ElevenLabs sent an answer Agents HQ could not read.")
    return out


def _clean(s, n):
    return CONTROL.sub("", str(s or ""))[:n]


def _voices(api_key):
    r = _call("/v1/voices", api_key)
    out = []
    for v in r.get("voices") or []:
        if not isinstance(v, dict) or not VOICE_OK.match(str(v.get("voice_id", ""))):
            continue
        labels = v.get("labels") if isinstance(v.get("labels"), dict) else {}
        out.append({"id": v["voice_id"], "name": _clean(v.get("name"), 60), "category": _clean(v.get("category"), 20),
                    "labels": {_clean(k, 20): _clean(x, 30) for k, x in list(labels.items())[:8]},
                    "preview": _clean(v.get("preview_url"), 300)})
    return sorted(out, key=lambda v: (v["category"] not in OWN, v["name"].lower()))


def voices(root=None):
    """Every voice the account can use: [{"id", "name", "category", "labels", "preview"}], the owner's own voices first."""
    k = _key(root)
    if not k:
        raise ElevenError("No ElevenLabs key connected. The owner adds it in the app: user menu → Accounts → ElevenLabs.")
    return _voices(k)


def connect(api_key, root=None):
    """Check a key the owner pasted (it must list the voices) and save it. Credits are shown when the key may read them.
    An empty paste checks the saved key again."""
    k = str(api_key or "").strip() or str(load(root).get("api_key") or "")
    if not k:
        raise ElevenError("Paste your ElevenLabs API key first.")
    if not KEY_OK.match(k):
        raise ElevenError("That doesn't look like an ElevenLabs API key (it usually starts with sk_). Copy it again.")
    vs = _voices(k)
    row = {"api_key": k, "voices": len(vs), "own": sum(v["category"] in OWN for v in vs),
           "checked": datetime.datetime.now().isoformat(timespec="seconds")}
    try:                                                 # needs the User: Read permission; fine without it
        s = _call("/v1/user/subscription", k, timeout=20)
        row.update(tier=_clean(s.get("tier"), 40), used=int(s.get("character_count") or 0), limit=int(s.get("character_limit") or 0))
    except (ElevenError, ValueError, TypeError):
        pass
    save(row, root)
    return summary(root)


def disconnect(root=None):
    save({}, root)
    return summary(root)


def summary(root=None):
    """What the app may show: never the key."""
    d = load(root)
    out = {"connected": bool(d.get("api_key")), "env": bool(_env_key())}
    for k in ("voices", "own", "used", "limit"):
        if isinstance(d.get(k), int):
            out[k] = d[k]
    for k in ("tier", "checked"):
        if d.get(k):
            out[k] = _clean(d[k], 40)
    return out


def speak(text, voice_id, out_mp3, model=MODEL, settings=None, root=None):
    """Speak one line into out_mp3 (44.1 kHz mp3) with the connected key. Returns the character times:
    [[char, start, end], ...] in seconds from the start of the mp3."""
    if not VOICE_OK.match(str(voice_id or "")):
        raise ElevenError(f"Not an ElevenLabs voice id: {_clean(voice_id, 60)!r}. List them with: python tools/voice/eleven.py voices")
    if not MODEL_OK.match(str(model or "")):
        raise ElevenError(f"Not an ElevenLabs model id: {_clean(model, 60)!r}")
    k = _key(root)
    if not k:
        raise ElevenError("No ElevenLabs key connected. The owner adds it in the app: user menu → Accounts → ElevenLabs.")
    body = {"text": str(text), "model_id": model}
    vs = {n: settings[n] for n in ("stability", "similarity_boost", "style", "speed", "use_speaker_boost") if n in (settings or {})}
    if vs:                                               # none given = the voice's own saved settings
        body["voice_settings"] = vs
    r = _call(f"/v1/text-to-speech/{urllib.parse.quote(voice_id)}/with-timestamps?output_format=mp3_44100_128", k,
              method="POST", body=body, timeout=120)
    try:
        audio = base64.b64decode(r.get("audio_base64") or "", validate=True)
    except ValueError:
        audio = b""
    if not audio:
        raise ElevenError("ElevenLabs sent no audio for this line.")
    tmp = out_mp3 + ".part"
    with open(tmp, "wb") as f:
        f.write(audio)
    os.replace(tmp, out_mp3)
    al = r.get("alignment") if isinstance(r.get("alignment"), dict) else {}
    cs, ss, es = al.get("characters") or [], al.get("character_start_times_seconds") or [], al.get("character_end_times_seconds") or []
    try:
        return [[str(c), round(float(s), 3), round(float(e), 3)] for c, s, e in zip(cs, ss, es)]
    except (TypeError, ValueError):
        return []
