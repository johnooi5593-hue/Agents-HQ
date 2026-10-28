"""Restart Agents HQ from a terminal (or ask Claude to): the same as Restart HQ in the app's user menu.

    py -3 hq/restart.py           restart, unless lead jobs or posts are under way (it says what is running)
    py -3 hq/restart.py --force   restart anyway: running jobs and posts stop mid-way

HQ starts again by itself with its latest code, in a few seconds. Only works on this computer (localhost).
"""
import json, os, sys, time, urllib.error, urllib.request

PORT = int(os.environ.get("HQ_PORT", "7331"))
BASE = f"http://127.0.0.1:{PORT}"


def call(force):
    req = urllib.request.Request(BASE + "/api/restart", data=json.dumps({"force": force}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": e.reason}


def back():
    """True once HQ answers again (a login page counts: it is running)."""
    try:
        with urllib.request.urlopen(BASE + "/api/status", timeout=5):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def main():
    force = "--force" in sys.argv
    try:
        code, res = call(force)
    except (urllib.error.URLError, OSError):
        sys.exit(f"HQ isn't running on port {PORT}. Start it from the Agents HQ app.")
    if code == 404:
        sys.exit("This HQ is older than the restart command: use Restart engine in the tray once.")
    if code != 200:
        sys.exit((res.get("error") or f"HQ refused ({code})") + ("\nRun again with --force to restart anyway." if res.get("busy") and not force else ""))
    print("Restarting HQ" + (f" (stopped: {', '.join(res['stopped'])})" if res.get("stopped") else "") + "...", flush=True)
    time.sleep(3)                                              # the old one is shutting down
    for _ in range(80):                                        # up to 2 minutes for the launcher to start it again
        if back():
            print("HQ is back.")
            return
        time.sleep(1.5)
    sys.exit("HQ hasn't come back after 2 minutes. Use Restart engine in the tray.")


if __name__ == "__main__":
    main()
