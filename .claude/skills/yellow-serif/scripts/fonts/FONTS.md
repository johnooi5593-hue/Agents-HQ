# Fonts for Yellow Serif Kinetic

The font files are not committed (about 31 MB). `scripts/fonts.py` downloads them here on first use (`setup.py` and `setup.sh` run it once), checks their size, and falls back to a system font when offline.

| Role | Font | File | Source | Licence |
|---|---|---|---|---|
| Main captions, inline key words, Latin, full-screen and vertical words | Noto Serif SC, variable, used at its heaviest weight (wght 900, Black) | `NotoSerifSC[wght].ttf` (25.1 MB) | https://github.com/google/fonts/tree/main/ofl/notoserifsc (raw: `raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf`) | SIL Open Font License 1.1, saved as `NotoSerifSC-OFL.txt` |
| Standalone brush phrases (bursts) | Ma Shan Zheng (马善政毛笔楷书) | `MaShanZheng-Regular.ttf` (5.9 MB) | https://github.com/google/fonts/tree/main/ofl/mashanzheng (raw: `raw.githubusercontent.com/google/fonts/main/ofl/mashanzheng/MaShanZheng-Regular.ttf`) | SIL Open Font License 1.1, saved as `MaShanZheng-OFL.txt` |

The OFL allows using, embedding (burning into video) and redistributing these fonts, including commercially; it does not allow selling the fonts by themselves.

Offline fallbacks (`fonts.py` prints which one it used; check its licence before publishing):
- serif: Windows `C:\Windows\Fonts\simsunb.ttf`, `STZHONGS.TTF`, `simsun.ttc`; macOS `Songti.ttc`; Linux the first `fc-list :lang=zh` font with "Serif CJK", "Song" or "Ming" in its name.
- brush: Windows `C:\Windows\Fonts\simkai.ttf`, `STKAITI.TTF`; macOS `Kaiti.ttc`; else a Kai font from `fc-list`, else the serif face.
