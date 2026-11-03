"""Back to the footage: when the owner approves a video, the complete set is also copied into the Google Drive folder
its raw footage came from, for channels that ask for it ("coversBack": true in .hq-channels.json; Pong+Gospel, owner
2026-11-02: "everytime finished and thumbnails, please save the thumbnail inside the original folder", then "once i
done approve the video, must have one complete video, captions and #, thumbnails, all in original folder with file
name"): the finished edit, its captions with the hashtags, and both Codex covers.

The week folder is found from the date in the video's folder name (pong-gospel-1108-… → 1108) among the channel's
Drive folders, where one folder can hold two posting dates ("1107 08" = 7 and 8 Nov). The files are named
<MMDD>_<title>.mp4, <MMDD>_<title>_captions.txt, <MMDD>_<title>_9x16.png and <MMDD>_<title>_3x4.png (in the week folder
and again in the finished date folder beside it, PONG/<MMDD>/), the title being
the first phrase of post.md's heading. Copy only: nothing on the Drive is moved, renamed or deleted; a newer version
replaces the same name.
"""
import json, os, re, shutil, time

COVERS = (("cover-codex.png", "9x16"), ("cover-codex-ig.png", "3x4"))
VIDEO = "edit.mp4"


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


def captions_text(folder):
    """post.md's posting text for the Drive: the chosen caption first (package.json "caption", 0-based) with its title
    and hashtags, then the TikTok text, the pinned comment and the other options. "" when there is no post.md."""
    try:
        with open(os.path.join(folder, "post.md"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    head, parts, cur = "", {}, None
    for line in lines:
        if line.startswith("# ") and not head:
            head = line[2:].strip()
        elif line.startswith("## "):
            cur = line[3:].strip().lower(); parts[cur] = []
        elif cur is not None:
            parts[cur].append(line)
    options, opt = [], None
    for line in parts.get("captions", []):
        if line.startswith("### "):
            opt = [line[4:].strip()]; options.append(opt)
        elif opt is not None:
            opt.append(line)
    try:
        with open(os.path.join(folder, "package.json"), encoding="utf-8") as f:
            pick = int(json.load(f).get("caption") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        pick = 0
    pick = pick if 0 <= pick < len(options) else 0
    body = lambda ls: "\n".join(ls).strip()
    out = [head, ""]
    if options:
        out += [f"== Caption ({options[pick][0]}) ==", body(options[pick][1:]), ""]
    for name, label in (("tiktok", "TikTok"), ("pinned comment", "Pinned comment")):
        if body(parts.get(name, [])):
            out += [f"== {label} ==", body(parts[name]), ""]
    others = [o for i, o in enumerate(options) if i != pick]
    if others:
        out.append("== Other captions ==")
        for o in others:
            out += [f"--- {o[0]} ---", body(o[1:]), ""]
    return "\n".join(out).strip() + "\n" if len(out) > 2 else ""                # a post.md with no posting text: no file


def copy_back(root, name, channel_key, channel):
    """approved/<name>'s edit, captions and covers into its week's Drive folder. Returns the copied paths ([] when there
    is nothing to do)."""
    if not channel_key or not channel or not channel.get("coversBack") or not channel.get("drive"):
        return []
    folder = os.path.join(root, "approved", name)
    m = re.search(r"-(\d{4})(?:-|$)", name)
    have = [(c, size) for c, size in COVERS if os.path.isfile(os.path.join(folder, c))]
    video = os.path.isfile(os.path.join(folder, VIDEO))
    if not m or not (have or video):
        return []
    week = week_folder(channel["drive"], m[1])
    if not week:
        return []
    title = title_of(folder)
    base = os.path.join(week, f"{m[1]}_{title}" if title else m[1])
    done = []
    if video:
        shutil.copyfile(os.path.join(folder, VIDEO), base + ".mp4")
        done.append(base + ".mp4")
    text = captions_text(folder)
    if text:
        with open(base + "_captions.txt", "w", encoding="utf-8") as f:
            f.write(text)
        done.append(base + "_captions.txt")
    for cover, size in have:
        shutil.copyfile(os.path.join(folder, cover), f"{base}_{size}.png")
        done.append(f"{base}_{size}.png")
    # the same set in the finished date folder beside the raw footage folders (PONG/x EDIT → PONG/<MMDD>/; owner
    # 2026-11-02: "Both folders"), made when it is not there yet
    finished = os.path.join(os.path.dirname(os.path.normpath(channel["drive"])), m[1])
    os.makedirs(finished, exist_ok=True)
    for src in list(done):
        dst = os.path.join(finished, os.path.basename(src))
        shutil.copyfile(src, dst)
        done.append(dst)
    with open(os.path.join(folder, "covers-back.json"), "w", encoding="utf-8") as f:
        json.dump({"copied": done, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False, indent=1)
    return done
