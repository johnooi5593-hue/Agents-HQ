"""Fonts for Yellow Serif Kinetic: a heavy Song/serif face for every caption and a brush face for a few big phrases.

usage: python3 .claude/skills/yellow-serif/scripts/fonts.py            download once (if missing) and print which fonts are used
       python3 .claude/skills/yellow-serif/scripts/fonts.py --offline  only report, never download

Both fonts are SIL Open Font License fonts from the google/fonts repository, downloaded on first use into
scripts/fonts/ (not committed; sources and licences are in scripts/fonts/FONTS.md):
  serif  Noto Serif SC, variable NotoSerifSC[wght].ttf, used at its heaviest weight (Black, wght 900)
  brush  Ma Shan Zheng (马善政), MaShanZheng-Regular.ttf
Offline fallbacks (each checked to really draw Chinese and Latin): Windows STZhongsong/SimSun (serif) and SimKai (brush),
macOS Songti/Kaiti, Linux the best fc-list CJK font (Serif CJK first).
"""
import functools, glob, json, os, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "fonts")
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
SOURCES = {
    "serif": {"name": "Noto Serif SC", "file": "NotoSerifSC[wght].ttf", "url": RAW + "notoserifsc/NotoSerifSC%5Bwght%5D.ttf",
              "licence_url": RAW + "notoserifsc/OFL.txt", "licence": "NotoSerifSC-OFL.txt", "min_bytes": 20_000_000, "weight": 900},
    "brush": {"name": "Ma Shan Zheng", "file": "MaShanZheng-Regular.ttf", "url": RAW + "mashanzheng/MaShanZheng-Regular.ttf",
              "licence_url": RAW + "mashanzheng/OFL.txt", "licence": "MaShanZheng-OFL.txt", "min_bytes": 4_000_000, "weight": None},
}
FALLBACKS = {
    "serif": [r"C:\Windows\Fonts\STZHONGS.TTF", r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\simsunb.ttf",
              "/System/Library/Fonts/Supplemental/Songti.ttc", "/Library/Fonts/Songti.ttc", "/System/Library/Fonts/Songti.ttc"],
    "brush": [r"C:\Windows\Fonts\simkai.ttf", r"C:\Windows\Fonts\STKAITI.TTF", "/System/Library/Fonts/Supplemental/Kaiti.ttc",
              "/Library/Fonts/Kaiti.ttc"],
}
SAMPLE = "很多人拍短视频念PPT一盘散沙R"


def _fetch(url, dest, min_bytes=0):
    """Download url to dest through a .part file; keep it only when the size matches."""
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        want = int(r.headers.get("Content-Length") or 0)
        shutil.copyfileobj(r, f, 1 << 20)
    got = os.path.getsize(tmp)
    if (want and got != want) or got < min_bytes:
        raise RuntimeError(f"{os.path.basename(dest)}: got {got} bytes, expected {want or min_bytes}")
    os.replace(tmp, dest)


def download(quiet=False):
    """Fetch the two OFL fonts and their licences into scripts/fonts/ if they are not there yet. Returns {role: error or None}."""
    os.makedirs(DIR, exist_ok=True)
    res = {}
    for role, s in SOURCES.items():
        path = os.path.join(DIR, s["file"])
        try:
            if not (os.path.isfile(path) and os.path.getsize(path) >= s["min_bytes"]):
                if not quiet:
                    print(f"downloading {s['name']} ...", file=sys.stderr)
                _fetch(s["url"], path, s["min_bytes"])
            lic = os.path.join(DIR, s["licence"])
            if not os.path.isfile(lic):
                _fetch(s["licence_url"], lic, 1000)
            res[role] = None
        except Exception as e:  # offline, blocked, ...: the fallbacks take over
            res[role] = str(e)[:200]
    return res


def _covers(path):
    """True when the font really draws the sample (SimSun-ExtB, for one, has no common characters)."""
    try:
        from PIL import ImageFont
        ft = ImageFont.truetype(path, 32)
        nd = bytes(ft.getmask("\ue000"))
        return all(bytes(ft.getmask(c)) != nd and ft.getmask(c).getbbox() for c in SAMPLE)
    except Exception:
        return False


def _fc_list(kind):
    """Linux: CJK fonts from fontconfig, best first (serif first for the main face; no bitmap Unifont)."""
    if not shutil.which("fc-list"):
        return []
    out = [ln for ln in subprocess.run(["fc-list", ":lang=zh", "file", "family", "style"], capture_output=True, text=True).stdout.splitlines()
           if "unifont" not in ln.lower()]
    pref = ["Serif CJK", "Song", "Ming", "Serif"] if kind == "serif" else ["Kai", "Brush", "Serif CJK", "Song"]
    ranked = [ln for p in pref for ln in out if p.lower() in ln.lower()] + out
    return list(dict.fromkeys(ln.split(":")[0].strip() for ln in ranked))


OFFLINE = os.environ.get("YS_FONTS_OFFLINE") == "1"


@functools.lru_cache(None)
def resolve():
    """{"serif": {...}, "brush": {...}}: path, name, source (download | system) and licence note of each face.
    Downloads the OFL fonts on first use unless OFFLINE (env YS_FONTS_OFFLINE=1)."""
    errs = {} if OFFLINE else download(quiet=False)
    out = {}
    for role, s in SOURCES.items():
        path = os.path.join(DIR, s["file"])
        if os.path.isfile(path) and os.path.getsize(path) >= s["min_bytes"]:
            out[role] = {"path": path, "name": s["name"], "source": "google/fonts (OFL)", "weight": s["weight"], "licence": "SIL OFL 1.1"}
            continue
        cand = next((p for p in FALLBACKS[role] + _fc_list(role) if os.path.isfile(p) and _covers(p)), None)
        if role == "brush" and not cand:          # no brush face at all: use the serif one
            cand = out.get("serif", {}).get("path")
        out[role] = {"path": cand, "name": os.path.basename(cand) if cand else None, "source": "system fallback", "weight": None,
                     "licence": "system font: check its licence before publishing", "error": errs.get(role)}
    return out


@functools.lru_cache(None)
def font(role, size):
    """A PIL font of the given role ("serif" or "brush") and pixel size, at the heaviest weight for a variable font."""
    from PIL import ImageFont
    f = resolve()[role]
    if not f["path"]:
        raise RuntimeError(f"no {role} font found: run fonts.py with network access, or install a CJK serif font")
    ft = ImageFont.truetype(f["path"], max(4, int(round(size))))
    try:
        axes = ft.get_variation_axes()
        if axes:
            names = [(a.get("name") or b"").decode() if isinstance(a.get("name"), bytes) else str(a.get("name") or "") for a in axes]
            ft.set_variation_by_axes([a["maximum"] if n.lower() in ("weight", "wght") or len(axes) == 1 else a["default"] for a, n in zip(axes, names)])
    except Exception:
        pass
    return ft


def used():
    """Short description for the JSON results: which file each role uses."""
    return {r: f"{v['name']} ({v['source']})" for r, v in resolve().items()}


if __name__ == "__main__":
    OFFLINE = OFFLINE or "--offline" in sys.argv
    info = resolve()
    ok = {}
    for role in info:
        try:
            ft = font(role, 64)
            ok[role] = all(ft.getmask(c).getbbox() for c in SAMPLE)
        except Exception as e:
            ok[role] = f"error: {e}"
    print(json.dumps({"tool": "fonts", "fonts": info, "renders_cjk_and_latin": ok}, ensure_ascii=False))
