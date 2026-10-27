"""Phone notifications for the installed Agents HQ app (Web Push), with no extra package: the `cryptography` library only.

The phone's browser gives the app a subscription (an https address at Apple, Google, Mozilla or Microsoft, plus two
keys). To notify, this computer encrypts a small message for that phone (RFC 8291, aes128gcm) and signs a short token
proving it is this office (VAPID, RFC 8292). The push service only passes the sealed message on; it cannot read it.

The office's own key and the phones' subscriptions are kept in .hq-push.json in the office folder (never committed).
"""
import base64, json, os, threading, time, urllib.error, urllib.parse, urllib.request

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    AVAILABLE = True
except ImportError:                                   # notifications are off; everything else in HQ works
    AVAILABLE = False

# the push services phones use; a subscription pointing anywhere else is refused (the server never calls other hosts)
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")
CONTACT = "https://github.com/johnooi5593-hue/Agents-HQ"     # the VAPID "sub": who to contact about this sender


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text):
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt, info, length, ikm):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _point(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(payload, p256dh, auth, sender=None, salt=None):
    """RFC 8291: the message sealed for one phone (its p256dh public key and auth secret), as the request body."""
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    phone_pub = unb64(p256dh)
    phone_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), phone_pub)
    shared = sender.exchange(ec.ECDH(), phone_key)
    sender_pub = _point(sender)
    ikm = _hkdf(unb64(auth), b"WebPush: info\x00" + phone_pub + sender_pub, 32, shared)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)          # \x02: the last (and only) record
    return salt + (4096).to_bytes(4, "big") + bytes([len(sender_pub)]) + sender_pub + sealed


def allowed_endpoint(url):
    try:
        u = urllib.parse.urlparse(str(url))
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in PUSH_HOSTS or host.endswith(PUSH_SUFFIXES))


class Push:
    """The office's VAPID key, the subscribed phones, and sending."""

    def __init__(self, root):
        self.path, self.lock = os.path.join(root, ".hq-push.json"), threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data.get("subs"), list):
            data["subs"] = []
        if AVAILABLE and not data.get("key"):
            key = ec.generate_private_key(ec.SECP256R1())
            data["key"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()).decode()
            self._save(data)
        return data

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def _key(self, data):
        return serialization.load_pem_private_key(data["key"].encode(), password=None)

    def public_key(self):
        """The office's public key (the app needs it to subscribe), or None when notifications can't work here."""
        if not AVAILABLE:
            return None
        with self.lock:
            return b64(_point(self._key(self._load())))

    def subscribe(self, sub, device=""):
        endpoint = (sub or {}).get("endpoint")
        keys = (sub or {}).get("keys") or {}
        if not allowed_endpoint(endpoint) or not keys.get("p256dh") or not keys.get("auth"):
            raise ValueError("that is not a phone notification subscription")
        unb64(keys["p256dh"]), unb64(keys["auth"])
        with self.lock:
            data = self._load()
            data["subs"] = [s for s in data["subs"] if s.get("endpoint") != endpoint][-19:]
            data["subs"].append({"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                                 "device": str(device or "")[:80], "added": int(time.time())})
            self._save(data)
            return len(data["subs"])

    def unsubscribe(self, endpoint):
        with self.lock:
            data = self._load()
            data["subs"] = [s for s in data["subs"] if s.get("endpoint") != endpoint]
            self._save(data)

    def count(self):
        with self.lock:
            return len(self._load()["subs"])

    def _vapid(self, key, endpoint):
        u = urllib.parse.urlparse(endpoint)
        head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        claims = b64(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": CONTACT}).encode())
        r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        token = f"{head}.{claims}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={b64(_point(key))}"

    def send(self, title, body, url="/", tag=None):
        """Notify every subscribed phone. Returns how many took it. Phones whose subscription ended are forgotten."""
        if not AVAILABLE:
            return 0
        with self.lock:
            data = self._load()
            key, subs = self._key(data), list(data["subs"])
        message = json.dumps({"title": title[:120], "body": body[:240], "url": url, "tag": tag or url}, ensure_ascii=False).encode()
        ok, gone = 0, []
        for sub in subs:
            try:
                req = urllib.request.Request(sub["endpoint"], data=encrypt(message, sub["keys"]["p256dh"], sub["keys"]["auth"]), method="POST",
                                             headers={"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                                                      "TTL": "86400", "Urgency": "high", "Authorization": self._vapid(key, sub["endpoint"])})
                with urllib.request.urlopen(req, timeout=15) as r:
                    ok += 200 <= r.status < 300
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):              # the phone unsubscribed or the app was removed
                    gone.append(sub["endpoint"])
            except (OSError, ValueError):
                pass                                  # offline: the next notification tries again
        for endpoint in gone:
            self.unsubscribe(endpoint)
        return ok

    def send_later(self, title, body, url="/", tag=None):
        """send() in the background, so a slow push service never holds up the office."""
        threading.Thread(target=self.send, args=(title, body, url, tag), daemon=True).start()
