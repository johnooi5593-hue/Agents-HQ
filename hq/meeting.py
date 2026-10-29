"""Call an all-hands meeting from a terminal (or ask Claude to): the same as /meeting in the app's chat boxes.

    py -3 hq/meeting.py                      everyone walks to the 6F Meeting Hall; the heads write how to improve
    py -3 hq/meeting.py "why are IG views down?"   the same, and they discuss that topic first

One AI job. The notes go to work/meetings/ and up on the hall's projector. Nothing is posted. Only works on this
computer (localhost).
"""
import json, os, sys, urllib.error, urllib.request

PORT = int(os.environ.get("HQ_PORT", "7331"))
BASE = f"http://127.0.0.1:{PORT}"


def main():
    topic = " ".join(sys.argv[1:]).strip()
    req = urllib.request.Request(BASE + "/api/meeting", data=json.dumps({"action": "start", "topic": topic}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"HQ refused the meeting ({e.code}).")
    except (urllib.error.URLError, OSError):
        sys.exit(f"HQ isn't running on port {PORT}. Start it from the Agents HQ app.")
    print(f"Meeting started (board task {res.get('task')}). Everyone is walking to the 6F Meeting Hall."
          f" The heads' notes go to {res.get('file')}" + (f", starting with: {topic}" if topic else "") + ".")


if __name__ == "__main__":
    main()
