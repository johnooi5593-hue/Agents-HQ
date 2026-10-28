"""The client edition of Agents HQ: a clean office to sell, made from this repository.

    py -3 release/client_edition.py                 build into ../Agents-HQ-Client (a clone of the product repo)
    py -3 release/client_edition.py --out <dir>     build into another folder (a plain folder is fine for a look)
    py -3 release/client_edition.py --push          build, commit and push to the product repo (asks first)

What a client gets: the office, the 31 agents and the general skills, with a fresh brain ("Not set up yet"), no
channels, no tasks and none of the owner's own work. Left out: the owner's brain and lessons, the church tools that
run on AI OFFICE or need the owner's style guides (sermon studio, poster-kinetic, caption-card, sermon-moments,
sermon-poster, xhs-sermon-recap), the owner's notes in docs/, the tests, the D: drive rules, and this release/ folder.
The client's office updates from the private product repo with its own access code (release/new_client.py).

Every edit below is an exact replacement: when the source text changes, the build stops and names the passage, so the
client copy never goes out half cleaned. Nothing is pushed without --push and a yes.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(SRC, "release", "client")
PRODUCT_REPO = "johnooi5593-hue/Agents-HQ-Client"

LEAVE_OUT = (
    "release/", "hq/tests/", "fly.toml", "deploy/", "docs/client-edition.md",
    "docs/CLAUDE-HQ-THUMBNAIL-HANDOFF-", "docs/CODEX-", "docs/channel-thumbnails.md", "docs/sermon-design-studio.md",
    ".claude/skills/caption-card/", ".claude/skills/poster-kinetic/", ".claude/skills/sermon-moments/",
    ".claude/skills/sermon-poster/", ".claude/skills/xhs-sermon-recap/",
)
CHURCH_SKILLS = {"caption-card", "poster-kinetic", "sermon-moments", "sermon-poster", "xhs-sermon-recap"}
FROM_TEMPLATE = {"README.md": "README.md", "brain/memory.jsonl": "memory.jsonl"}
# none of these may be left anywhere in the client copy
PERSONAL = ("John Ooi", "johnooi5593@", "NLRCC", "Pong+Gospel", "Pong Gospel", "Semenyih", "XiXi", "tail9f4f90",
            "Damien Chua", "D:\\Agents HQ", "D:/Agents HQ", "Documents\\Style Guides")


def edits(repo):
    ssh = f"git@github.com:{repo}.git"
    return {
        "hq/server.py": [
            ('REPO_URL = os.environ.get("HQ_REPO_URL", "https://github.com/johnooi5593-hue/Agents-HQ")',
             f'REPO_URL = os.environ.get("HQ_REPO_URL", "{ssh}")'),
        ],
        "hq/webpush.py": [
            ('CONTACT = "https://github.com/johnooi5593-hue/Agents-HQ"', f'CONTACT = "https://github.com/{repo}"'),
        ],
        "desktop/lib.js": [
            ('const REPO_URL = "https://github.com/johnooi5593-hue/Agents-HQ";', f'const REPO_URL = "https://github.com/{repo}";'),
            ("const PRIVATE_EDITION = false;", "const PRIVATE_EDITION = true;"),
        ],
        "desktop/package.json": [
            ('"url": "https://github.com/johnooi5593-hue/Agents-HQ.git"', f'"url": "https://github.com/{repo}.git"'),
        ],
        "CLAUDE.md": [
            (re.compile(r"^- `D:\\`.*\n", re.M), ""),
        ],
        "docs/phone-app.md": [
            ("If another app on the PC (AI OFFICE) already uses", "If another app on the PC already uses"),
        ],
        ".claude/agents/clip-editor.md": [
            ("  - poster-kinetic\n  - caption-card\n  - sermon-moments\n", ""),
            (re.compile(r"^\*\*Poster Kinetic\.\*\*.*\n\n", re.M), ""),
            (re.compile(r"^\*\*Caption Card\.\*\*.*\n\n", re.M), ""),
            (re.compile(r"^\*\*Sermon moments\.\*\*.*\n\n", re.M), ""),
            (re.compile(r"^\*\*Cover from Codex\.\*\*.*\n\n", re.M), ""),
            ("; a sermon keeps hits for its true punchlines", ""),
        ],
        ".claude/agents/creative-director.md": [
            ("skills:\n  - sermon-poster\n  - xhs-sermon-recap\n", ""),
            (re.compile(r"^## Sermon artwork routing\n.*?^For other Creative work, use the existing video/clip procedure below\.\n\n", re.M | re.S), ""),
            (re.compile(r"^For a \*\*sermon highlight\*\*.*\n", re.M), ""),
        ],
        ".claude/agents/thumbnail-designer.md": [
            (re.compile(r"^description: .*$", re.M),
             "description: Makes clip covers with pixel when the lead sends a cover job: a replacement for a cover the brand-checker failed, cover options the owner asked for, or a series that needs matching covers."),
            ("  - sermon-poster\n  - xhs-sermon-recap\n", ""),
            (re.compile(r"^## Sermon artwork routing\n.*?^The remaining instructions apply to ordinary clip-cover assignments\.\n\n", re.M | re.S), ""),
            (re.compile(r" For a sermon cover made from a speaker frame,.*?the phrase is short\."), ""),
        ],
        ".claude/agents/brand-checker.md": [
            (re.compile(r' When `notes\.md` says "Cover: Codex".*?approves the video\.'), ""),
            (re.compile(r"^4\. For a clip made with \*\*poster-kinetic\*\*.*\n", re.M), ""),
            ("5. **Sound effects**", "4. **Sound effects**"),
            ("6. For copy or a script", "5. For copy or a script"),
            ("7. Answer with one line", "6. Answer with one line"),
        ],
    }


def apply(text, rules, rel):
    for old, new in rules:
        if isinstance(old, re.Pattern):
            text, n = old.subn(new, text)
        else:
            n = text.count(old)
            text = text.replace(old, new)
        if n != 1:
            sys.exit(f"stop: {rel}: expected the passage once, found it {n} times: {getattr(old, 'pattern', old)[:90]!r}\n"
                     f"The source changed. Update the matching rule in release/client_edition.py, then build again.")
    return text


def settings(text):
    """The permission rules without the owner's D: drive, and the office's own secrets closed to the agents."""
    d = json.loads(text)
    p = d.setdefault("permissions", {})
    p["deny"] = [r for r in p.get("deny", []) if "//d/" not in r]
    p["deny"] += [r for r in ("Read(.hq-office.json)", "Read(.hq-access-key)", "Bash(*hq-office*)", "Bash(*hq-access*)") if r not in p["deny"]]
    p["additionalDirectories"] = [x for x in p.get("additionalDirectories", []) if not re.match(r"^[A-Za-z]:\\*$", x)]
    if not p["additionalDirectories"]:
        del p["additionalDirectories"]
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def teams(text):
    """The team cards without the church skills."""
    d = json.loads(text)
    for t in d.get("teams", []):
        t["skills"] = [s for s in t.get("skills", []) if s.get("skill") not in CHURCH_SKILLS]
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def git(*args, cwd=SRC):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()}")
    return r.stdout


def build(repo, allow_dirty=False):
    """{path: bytes} for every file of the client edition."""
    if git("status", "--porcelain", "--untracked-files=no").strip() and not allow_dirty:
        sys.exit("stop: this repository has uncommitted changes. Commit them first (or pass --allow-dirty for a look).")
    rules = edits(repo)
    out = {}
    for rel in git("ls-files", "-z").split("\0"):
        if not rel or rel.startswith(LEAVE_OUT) or not os.path.isfile(os.path.join(SRC, rel)):
            continue
        with open(os.path.join(SRC, rel), "rb") as f:
            data = f.read()
        if rel in FROM_TEMPLATE:
            with open(os.path.join(HERE, FROM_TEMPLATE[rel]), "rb") as f:
                data = f.read()
        elif rel in rules or rel in (".claude/settings.json", "hq/teams.json"):
            text = data.decode("utf-8").replace("\r\n", "\n")
            text = apply(text, rules.get(rel, []), rel)
            if rel == ".claude/settings.json":
                text = settings(text)
            if rel == "hq/teams.json":
                text = teams(text)
            data = text.encode("utf-8")
        out[rel] = data
    for rel in rules:
        if rel not in out:
            sys.exit(f"stop: {rel} is not in the repository any more; update release/client_edition.py")
    sha = git("rev-parse", "--short", "HEAD").strip()
    out["EDITION.json"] = (json.dumps({"edition": "client", "repo": repo, "built_from": sha,
                                       "built": datetime.date.today().isoformat()}, indent=2) + "\n").encode()
    found = [(rel, w) for rel, data in out.items() for w in PERSONAL if w.encode() in data]
    if found:
        sys.exit("stop: personal details left in the client copy:\n" + "\n".join(f"  {rel}: {w}" for rel, w in found))
    return out, sha


def write(files, dest):
    """Put the edition in `dest`. In a clone of the product repo, files the edition no longer has are removed from it
    (they stay in its history); nothing outside the repo's own tracked files is touched."""
    os.makedirs(dest, exist_ok=True)
    if os.path.isdir(os.path.join(dest, ".git")):
        for rel in git("ls-files", "-z", cwd=dest).split("\0"):
            if rel and rel not in files and os.path.isfile(os.path.join(dest, rel)):
                os.remove(os.path.join(dest, rel))
    for rel, data in files.items():
        path = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(SRC), "Agents-HQ-Client"))
    ap.add_argument("--repo", default=PRODUCT_REPO, help="the private product repo, owner/name")
    ap.add_argument("--push", action="store_true", help="commit and push the edition to the product repo")
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted changes (never with --push)")
    a = ap.parse_args()
    if a.push and a.allow_dirty:
        sys.exit("stop: --push only ships committed work")
    files, sha = build(a.repo, a.allow_dirty)
    write(files, a.out)
    print(f"Client edition from {sha}: {len(files)} files in {a.out}")
    if not a.push:
        return
    if not os.path.isdir(os.path.join(a.out, ".git")):
        sys.exit(f"stop: {a.out} is not a clone of {a.repo}. Clone it there first: git clone git@github.com:{a.repo}.git")
    git("add", "-A", cwd=a.out)
    if not git("status", "--porcelain", cwd=a.out).strip():
        print("Nothing changed since the last release.")
        return
    print(git("status", "--short", cwd=a.out))
    if input(f"Push this to {a.repo}? Every client gets it at their next update. Type yes: ").strip().lower() != "yes":
        print("Not pushed. The changes are in", a.out)
        return
    git("commit", "-q", "-m", f"Client edition from {sha}", cwd=a.out)
    git("push", "-q", "origin", "HEAD:main", cwd=a.out)
    print(f"Pushed. Clients update within the hour; the installer builds on GitHub ({a.repo}, Actions).")


if __name__ == "__main__":
    main()
