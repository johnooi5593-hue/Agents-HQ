# gradecheck.py: measured colour checks for the brand check (board t204, 2026-11-08)

Why: on the 1107 Children review v3, two grades stacked (`work/creative/1107-children/scripts/grade.py` plus the caption
renderer's warm grade arc) and a mum's face came out orange. The brand-checkers each measured by hand, in different
ways. The owner then set the rule (Brand rules, 2026-11-08): bright and clean, never too orange or too warm, neutral
whites, natural skin. This tool measures that rule the same way every time.

## Usage

```
python tools/vision/gradecheck.py <video.mp4> <out.json> [--step 0.5] [--profile kids|sermon]
       [--shots shots.json] [--faces faces.json] [--ref other.mp4] [--sheet out.jpg]
```

- Exit code: **0 = PASS**, **1 = FAIL** (at least one judged shot or the overall numbers flagged), **2 = the video can't
  be read** (for example a render still in progress, because ffprobe finds no moov atom). It prints one JSON summary line.
- `--profile kids` is the default. It applies to children and event reviews and to any edit meant to look neutral.
  Use `--profile sermon` for sermon or Pong talk reels with a warm, owner-approved stage grade.
- `--shots`: pass the edit's shots.json when there is one (the grade.py format `{"dur":2,"shots":[{"d":..}]}`,
  `{"cuts":[s,..]}`, `[[start,end],..]` or `[{"start","end"}]`). Without it, cuts are found from the luma histogram
  (the same rule as grade.py). That finds hard cuts but merges zooms and soft cuts: on the 1107 v3 9:16 it found
  8 shots where shots.json has 25.
- `--faces`: the output of `tools/vision/faces.py` (t202). Its raw `per_frame` boxes are used first, then its padded
  `faces` ranges. A plain `[{"t", "faces": [[x, y, w, h]]}]` list also works. Skin is then measured only inside
  the face boxes (with a loose skin mask, so hair and background inside a box don't count). Use it whenever
  faces.py runs: it is much more exact than the frame-wide mask (see Limits).
- `--ref`: also measures a second video in the same shot windows and adds `ref`, `ref_flags` and `delta`
  (this minus ref) per shot, plus `delta_overall`. The sheet then shows ref | this side by side.
- `--sheet`: one frame per shot (the sample nearest the shot's middle) with its numbers. The frame is red for a
  flagged shot, green for a pass and grey for a SHORT shot. Read it with the Read tool before writing the verdict.

## What it measures (each sample frame, decoded at 640 px on the long side)

| Measure | How |
|---|---|
| White balance | Pixels with L* > 65, HSV S < 0.28, \|a*\| < 10 and min channel < 245 (white walls, tables, paper; pink caption cards and blown-out areas left out). Mean **a\*** (+ = magenta/red) and **b\*** (+ = yellow/warm), CIELAB D65, computed in numpy. No reading if under 0.5 % of the frame. |
| Skin | With `--faces`: the face boxes. Without: a YCrCb mask (Cr 133-185, Cb 77-127, Y > 60), narrowed to HSV S 0.18-0.75 and hue 0-40 deg (or >= 350), so warm walls and pink cards don't count. Mean **hue** (deg), mean **HSV S**, **% clipped** (R >= 250 or any channel >= 254). No reading if under 0.4 % of the frame. |
| Exposure | Rec.709 luma: **median**, **% crushed** (< 8/255), **% clipped** (> 250/255). |
| Colour | Mean HSV saturation. **Warmth index** = mean b\* of the near-neutral mid-tones (L\* 25-75, C\* < 25), with skin left out. A colour cast shows up there; orange shirts, toys and wood (C\* > 25) and close-up faces do not. |

Each shot takes the mean of its samples (plus `skin_clip_max`, the worst frame). A shot shorter than 1.0 s is
measured but not judged (verdict SHORT): those are flashes, light leaks and blur wipes. A shot shorter than the
step gets its nearest sample. The overall numbers are the mean over every sample, and they are judged as well.

## Thresholds (a value above the max, or below the min, flags)

| Flag | kids (default) | sermon |
|---|---|---|
| `skin_sat` skin HSV S | > 0.45 | > 0.55 |
| `skin_hue_low` / `skin_hue_high` | < 10 deg / > 35 deg | same |
| `skin_clip` % of skin clipped | > 1 % | > 2.5 % |
| `white_warm` white b\* | > +8 | > +12 |
| `white_magenta` white a\* | > +4 | > +5 |
| `crushed` % luma < 8 | > 3 % | > 35 % |
| `too_warm` warmth index | > +8 | > +12 |

The kids numbers are the brief's numbers, with one change: `too_warm` is set at 8, not 10. The warmth index leaves
out saturated colours and skin, so it reads lower than a plain mid-tone mean (the first version of the index, a
plain mid-tone mean, flagged 11 of the 25 v4 9:16 shots for orange toys, shirts and faces alone). At 8, it fails 7 of the
25 v3 9:16 shots (8.6 to 12.4) and none of the v4 shots (the worst is 6.3).

## Calibration (2026-11-08, step 0.5 s, 1107 shots from `work/creative/1107-children/shots.json`, no faces.json)

Overall means (white a\*/b\*, warmth, skin hue/S/clip%/worst clip%, median luma, crushed %, saturation):

| Video | Profile | Verdict | white a\*/b\* | warmth | skin hue / S / clip (max) | luma / crushed | sat |
|---|---|---|---|---|---|---|---|
| out/1107-children-review-v3/edit.mp4 (9:16) | kids | **FAIL**, 23/25 shots + overall white_warm | 0.1 / **10.3** | 5.9 | 26.2 / 0.41 / 0.68 (5.0) | 124 / 0.2 | 0.38 |
| out/1107-children-review-16x9-v3/edit.mp4 | kids | **FAIL**, 22/25 + overall white_warm | -0.1 / **10.4** | 5.1 | 25.8 / 0.39 / 0.77 (3.5) | 128 / 0.4 | 0.35 |
| render-v4/edit.mp4 (9:16, v4 caption render) | kids | FAIL, 1/25 (shot #5 skin_clip 1.07 %) | 0.6 / **3.6** | 2.0 | 23.8 / 0.38 / 0.17 (1.3) | 121 / 0.1 | 0.31 |
| render16-v4/edit.mp4 (16:9, v4 caption render) | kids | FAIL, 2/25 (#5 skin_clip 1.22 %, #13 white b\* 9.5) | 0.3 / **3.1** | 0.9 | 23.2 / 0.37 / 0.16 (1.8) | 124 / 0.2 | 0.28 |
| out/can-1106-01-i-see-jesus-in-you/edit.mp4 | sermon | **PASS** | 0.6 / 5.6 | 3.9 | 25.9 / 0.40 / 0.31 (5.9) | 56 / 6.1 | 0.35 |
| approved/pj-1101-01-paris-cannot-keep-quiet/edit.mp4 | sermon | **PASS** | -1.4 / 1.8 | 1.0 | 21.5 / 0.47 / 0.12 (3.3) | 35 / 15.9 | 0.41 |
| (same CAN reel) | kids | FAIL, 6/10 + overall crushed | | | | | |
| (same PJ reel) | kids | FAIL, 7/9 + overall skin_sat, crushed | | | | | |
| out/1107-children-review-v3 (9:16) | sermon | FAIL, 11/25 (white b\* 9.5-15.8) | | | | | |

**v3 to v4 (same stage: the caption-card render before stickers, `render-cute-v3` vs `render-v4`, with `--ref`):**
white b\* 10.7 to 3.6 (**-7.0**), warmth 6.1 to 2.0 (-4.1), skin hue 26.3 to 23.8 deg (-2.6), skin S 0.40 to 0.38,
skin clip 0.62 to 0.17 %, clipped luma 1.6 to 0.8 %, saturation 0.37 to 0.31. The 16:9 pair shows the same:
white b\* 10.6 to 3.1 (-7.5), warmth 5.1 to 0.9. The v3 caption render fails 23/25 shots, v4 fails 1.

**The mum-and-baby shot, 34.2-36.2 s (shot #17).** The `out/` v3 9:16 edit **is flagged** (skin_sat 0.463, above 0.45).
That file already has the v3 brand-check fix in it (grade.py SHOT_FIX, notes.md row I), so its skin clip is 0.03 %.
The 15-17 % clip from the first v3 render can't be re-measured, because that render was replaced and not kept.
With a face box drawn by hand on her face (scratch test), the face alone reads S 0.49, hue 20 deg and 0 % clip:
still flagged. In v4 the same shot reads S 0.45 (on the line, not flagged), white b\* 3.1 and warmth -1.9. The
16:9 v3 shot reads S 0.443, so it is *not* flagged: her face is a smaller part of the wider frame, and the
frame-wide mask averages it with the rest. faces.json would separate it.

**Why a sermon profile.** The two approved sermon reels fail every kids check that a stage grade trips: designed
near-black stage and caption backgrounds (crushed 6-32 % per shot), skin S up to 0.53 under stage light, and white
b\* up to 10.9 on the PJ opening. So `--profile sermon` sets each limit just above the approved reels' worst judged
shot: white b\* 10.9 to 12, white a\* 4.7 to 5, skin S 0.534 to 0.55, skin clip 2.1 % to 2.5 %, crushed 31.9 % to 35 %,
and warmth 8.4 to 12. The 1107 v3 still fails the sermon profile on 11 shots, so the profile is looser but not blind.

## Limits (read the sheet before you fail or pass on one number)

- Without `--faces`, "skin" means every skin-coloured region: wood, beige clothes, the orange print on a craft board.
  Both v4 `skin_clip` flags (shot #5, 10.2-12.2 s) come from the bright edges of the teacher's printed board, not
  from her face (checked on a mask overlay). Confirm a skin flag on the sheet, or rerun with `--faces`.
- faces.py (t202) crashed during this calibration (2026-11-08) while writing its JSON (`Object of type float32 is not JSON
  serializable`, faces.py line 478). The 1107 numbers above were therefore measured without faces. That file belongs
  to the other worker and was not touched here.
- The v4 numbers come from the v4 caption render (`render-v4/edit.mp4`, `render16-v4/edit.mp4`, finished at 01:31).
  The sticker pass (`edit-stk.mp4`) was still being written, and there is no v4 file in `out/` yet. Run it once more
  on the final v4 `edit.mp4` with `--ref out/1107-children-review-v3/edit.mp4`.
- The white b\* +8 flag on v4 16:9 shot #13 (the boy in the orange shirt, 26.2-28.2 s) looks like a real, mild
  cream cast on the wall beside him (orange bounce light). It is worth one look, not a re-grade of the whole clip.

## In the brand check

```
python tools/vision/gradecheck.py out/<clip>/edit.mp4 out/<clip>/gradecheck.json --profile kids \
       --shots <work>/shots.json [--faces <work>/faces.json] --sheet out/<clip>/gradecheck.jpg
```
For a re-grade, add `--ref <previous edit.mp4>` and quote `delta_overall` in brandcheck.md. The JSON and the
sheet sit next to brandcheck.md so "done?" can be answered from a file.
