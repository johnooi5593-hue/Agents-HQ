"""Fonts for Poster Kinetic: heavy Chinese sans, a slanted title black, heavy Latin italics and upright blacks.

usage: python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/pfonts.py"     print which fonts are in use and test sermon words

The reel's exact fonts cannot be identified from video (guide p.4-5); these are the closest installed matches. Each
role tries its candidates in order. Every character is checked: a character the chosen font cannot draw (祂, 袮,
Traditional characters in Alibaba PuHuiTi / 优设标题黑) is drawn with the next font that can, so there are never empty boxes.
Fonts are looked up in the Windows user font folder and C:\\Windows\\Fonts; nothing is downloaded or copied.
"""
import functools, json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

UF = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")), "Microsoft", "Windows", "Fonts")
WF = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
EXTRA = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")]   # optional, owner-supplied

# (file, display name, licence note, variable-font weight or None)
CANDIDATES = {
    "cjk": [("Alibaba-PuHuiTi-Heavy.ttf", "Alibaba PuHuiTi Heavy", "Alibaba free commercial licence", None),
            ("_思源黑体SourceHanSansCN-Heavy.otf", "Source Han Sans CN Heavy", "SIL OFL", None),
            ("SourceHanSansCN-Heavy.otf", "Source Han Sans CN Heavy", "SIL OFL", None),
            ("NotoSansSC-VF.ttf", "Noto Sans SC Black", "SIL OFL", 900),
            ("msyhbd.ttc", "Microsoft YaHei Bold", "Windows system font", None)],
    "cjk_slant": [("优设标题黑.ttf", "YouSheBiaoTiHei 优设标题黑", "free commercial use (YouShe)", None)],
    "cjk_text": [("Alibaba-PuHuiTi-Bold.ttf", "Alibaba PuHuiTi Bold", "Alibaba free commercial licence", None),
                 ("NotoSansSC-VF.ttf", "Noto Sans SC Bold", "SIL OFL", 700),
                 ("msyhbd.ttc", "Microsoft YaHei Bold", "Windows system font", None)],
    "latin": [("ariblk.ttf", "Arial Black", "Windows system font", None),
              ("Montserrat-Black.otf", "Montserrat Black", "SIL OFL", None),
              ("AlibabaSans-Heavy.otf", "Alibaba Sans Heavy", "Alibaba licence: check before commercial use", None)],
    "latin_italic": [("AlibabaSans-HeavyItalic.otf", "Alibaba Sans Heavy Italic", "Alibaba licence: check before commercial use", None),
                     ("Montserrat-BlackItalic.otf", "Montserrat Black Italic", "SIL OFL", None)],
    "latin_narrow": [("ARIALNB.TTF", "Arial Narrow Bold", "Windows system font", None),
                     ("Oswald-Bold.ttf", "Oswald Bold", "SIL OFL", None)],
}
# Characters missing from a role's font are drawn by these, in order (Source Han / Noto cover GB18030 and Traditional).
CJK_BACKUP = ["_思源黑体SourceHanSansCN-Heavy.otf", "SourceHanSansCN-Heavy.otf", "NotoSansSC-VF.ttf", "msyhbd.ttc"]
SAMPLE = "祂袮恩典圣灵耶稣這說會為們 ROI 7% Grace"
SLANT = 0.18          # synthetic slant (about 10 degrees) when the slanted font cannot be used


def _find(fname):
    for d in [UF, WF] + EXTRA:
        p = os.path.join(d, fname)
        if os.path.isfile(p):
            return p
    return None


@functools.lru_cache(maxsize=None)
def _load(path, size, weight):
    ft = ImageFont.truetype(path, size)
    if weight:
        try:
            ft.set_variation_by_axes([weight])
        except Exception:
            pass
    return ft


@functools.lru_cache(maxsize=None)
def resolve_role(role):
    """(path, name, licence, weight) of the first installed candidate for a role, or None."""
    for fname, name, lic, wt in CANDIDATES[role]:
        p = _find(fname)
        if p:
            return (p, name, lic, wt)
    return None


def font(role, size):
    r = resolve_role(role) or resolve_role("cjk")
    return _load(r[0], max(6, int(round(size))), r[3])


@functools.lru_cache(maxsize=None)
def _notdef(path, weight):
    return _ink(path, weight, "\ue000")


@functools.lru_cache(maxsize=200000)
def _ink(path, weight, ch):
    ft = _load(path, 48, weight)
    im = Image.new("L", (72, 72))
    ImageDraw.Draw(im).text((8, 8), ch, font=ft, fill=255)
    return np.asarray(im).tobytes()


def has_glyph(path, weight, ch):
    if ch.isspace():
        return True
    ink = _ink(path, weight, ch)
    return ink != _notdef(path, weight) and any(ink)


USED = {}


@functools.lru_cache(maxsize=200000)
def pick(ch, role):
    """(path, weight, synthetic_slant, name) to draw one character in a role, with fallbacks."""
    order = []
    if role == "cjk_slant":
        r = resolve_role("cjk_slant")
        if r:
            order.append((r, 0.0))
        r2 = resolve_role("cjk")
        if r2:
            order.append((r2, SLANT))
        order += [((p, os.path.basename(p), "", 900 if "VF" in p else None), SLANT) for p in filter(None, map(_find, CJK_BACKUP))]
    else:
        r = resolve_role(role)
        if r:
            order.append((r, 0.0))
        if role in ("cjk", "cjk_text"):
            order += [((p, os.path.basename(p), "", (900 if role == "cjk" else 700) if "VF" in p else None), 0.0)
                      for p in filter(None, map(_find, CJK_BACKUP))]
    for (path, name, lic, wt), sl in order:
        if has_glyph(path, wt, ch):
            USED[name] = lic
            return (path, wt, sl, name)
    path, name, lic, wt = order[0][0] if order else (resolve_role("cjk") or (None, "?", "", None))
    return (path, wt, 0.0, name)


def glyph_font(ch, role, size):
    path, wt, sl, name = pick(ch, role)
    return _load(path, max(6, int(round(size))), wt), sl, name


def used():
    return [f"{k} ({v})" for k, v in USED.items()]


def resolve():
    out = {}
    for role in CANDIDATES:
        r = resolve_role(role)
        out[role] = {"name": r[1], "file": r[0], "licence": r[2]} if r else None
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    res = resolve()
    fallback = {}
    for role in ("cjk", "cjk_slant"):
        for ch in SAMPLE:
            if ch.strip() and ord(ch) > 0x2E80:
                p = pick(ch, role)
                if p[3] != (res[role] or {}).get("name"):
                    fallback.setdefault(role, []).append(f"{ch}->{p[3]}" + (" (slanted)" if p[2] else ""))
    missing = [r for r, v in res.items() if v is None]
    print(json.dumps({"tool": "fonts", "ok": not {"cjk", "latin"} & set(missing), "fonts": res, "missing_roles": missing,
                      "per_character_fallbacks": fallback,
                      "note": "closest installed matches to the reference reel; the reel's own fonts are unknown"}, ensure_ascii=False))
