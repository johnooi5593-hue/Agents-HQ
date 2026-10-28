"""Access codes for clients: one read-only key per client on the private product repo.

    py -3 release/new_client.py "Acme Sdn Bhd"       make a code for a new client (prints it once)
    py -3 release/new_client.py --list               every client key on the product repo
    py -3 release/new_client.py --revoke <id>        stop a client's updates (the id from --list)

The code is "HQ1." and a new SSH key, added to the product repo as a read-only deploy key named after the client. The
client pastes it into the app's setup screen; their office then updates from the repo with it (hq/server.py, git_ssh).
Revoking a key stops that client's updates and nobody else's. Needs the GitHub CLI (gh), signed in as the repo owner.
"""
import argparse
import base64
import datetime
import os
import re
import subprocess
import sys
import tempfile

PRODUCT_REPO = "johnooi5593-hue/Agents-HQ-Client"


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def new_code(client, repo):
    slug = re.sub(r"[^A-Za-z0-9 ._-]+", "", client).strip()[:60]
    if not slug:
        sys.exit("stop: give the client a name, e.g. \"Acme Sdn Bhd\"")
    title = f"client: {slug} ({datetime.date.today().isoformat()})"
    with tempfile.TemporaryDirectory() as tmp:
        key = os.path.join(tmp, "key")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", title, "-f", key], check=True)
        gh("repo", "deploy-key", "add", key + ".pub", "--repo", repo, "--title", title)    # read-only unless --allow-write
        with open(key, encoding="ascii") as f:
            text = f.read().replace("\r\n", "\n")
    code = "HQ1." + base64.urlsafe_b64encode(text.encode("ascii")).decode("ascii").rstrip("=")
    print(f"Access code for {slug} (read-only, key \"{title}\" on {repo}). Send it with the installer; it is shown only this once:\n")
    print(code)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("client", nargs="?", help="the client's name")
    ap.add_argument("--repo", default=PRODUCT_REPO)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revoke", metavar="ID")
    a = ap.parse_args()
    if a.list:
        print(gh("repo", "deploy-key", "list", "--repo", a.repo) or "No client keys yet.")
    elif a.revoke:
        gh("repo", "deploy-key", "delete", a.revoke, "--repo", a.repo)
        print(f"Key {a.revoke} removed: that client's office no longer updates.")
    elif a.client:
        new_code(a.client, a.repo)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
