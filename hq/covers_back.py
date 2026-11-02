"""Covers back to the footage: when the owner approves a video, its Codex covers are also copied into the Google Drive
folder its raw footage came from, for channels that ask for it ("coversBack": true in .hq-channels.json; Pong+Gospel,
owner 2026-11-02: "everytime finished and thumbnails, please save the thumbnail inside the original folder").

The week folder is found from the date in the video's folder name (pong-gospel-1108-… → 1108) among the channel's
Drive folders, where one folder can hold two posting dates ("1107 08" = 7 and 8 Nov). The covers are named
<MMDD>_<title>_9x16.png and <MMDD>_<title>_3x4.png, the title being the first phrase of post.md's heading.
Copy only: nothing on the Drive is moved, renamed or deleted; a newer cover replaces the same name.
"""
import json, os, re, shutil, time

COVERS = (("cover-codex.png", "9x16"), ("cover-codex-ig.png", "3x4"))


def week_folder(drive, mmdd):
    """The Drive folder for a posting date: "1107" or "1107 08" for 1108 (MMDD, then more days of that month)."""
    try:
        names = sorted(n for n in os.listdir(drive) if os.path.isdir(os.path.join(drive, n)))
    except OSError:
        return None
    for n in names:
        parts = n.split()
        if not parts or not re.fullmatch(r"\d{4}", parts[0]):
            continue
        days = {parts[0]} | {parts[0][:2] + p for p in parts[1:] if re.fullmatch(r"\d{2}", p)}
        if mmdd in days:
            return os.path.join(drive, n)
    return None


def title_of(folder):
    """The first phrase of post.md's heading (# 婚姻能长久，是因为… · Pong+Gospel 11/07 → 婚姻能长久), safe as a file name."""
    try:
        with open(os.path.join(folder, "post.md"), encoding="utf-8") as f:
            head = next((l[2:] for l in f if l.startswith("# ")), "")
    except OSError:
        head = ""
    head = re.split(r"[，,。.!！?？:：;；]", head.split(" · ")[0].strip())[0]
    return re.sub(r'[\\/:*?"<>|]+', "", head).strip()[:24]


def copy_back(root, name, channel_key, channel):
    """approved/<name>'s covers into its week's Drive folder. Returns the copied paths ([] when there is nothing to do)."""
    if not channel_key or not channel or not channel.get("coversBack") or not channel.get("drive"):
        return []
    folder = os.path.join(root, "approved", name)
    m = re.search(r"-(\d{4})(?:-|$)", name)
    have = [(c, size) for c, size in COVERS if os.path.isfile(os.path.join(folder, c))]
    if not m or not have:
        return []
    week = week_folder(channel["drive"], m[1])
    if not week:
        return []
    title = title_of(folder)
    done = []
    for cover, size in have:
        dst = os.path.join(week, f"{m[1]}_{title}_{size}.png" if title else f"{m[1]}_{size}.png")
        shutil.copyfile(os.path.join(folder, cover), dst)
        done.append(dst)
    with open(os.path.join(folder, "covers-back.json"), "w", encoding="utf-8") as f:
        json.dump({"copied": done, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False, indent=1)
    return done
