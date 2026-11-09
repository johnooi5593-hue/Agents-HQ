# tools/vision: face boxes for stickers, bubbles and caption cards (board t202, 2026-11-08)

Why: every brand check of the 1107 Children review (v2, v3, both sizes) came back FIX for a sticker or card on a face,
because the face avoid boxes (FACES9 / FACES16 in `work/creative/1107-children/scripts/build_stickers.py`) were typed
by eye. `faces.py` finds the faces itself, every 0.1 s, and writes them in the avoid-box format stickers.py uses.
Other tools in this folder (gradecheck.py, textscan.py, blur_hits.py) belong to other workers; see their own README.

| file | what |
|---|---|
| `faces.py` | the detector: video -> faces.json (+ a contact sheet). `python faces.py` with no args prints the usage |
| `faces_check.py` | compares faces.json with hand-typed FACES tables (recall, misses, oversized boxes, sweep) |
| `onnx_strip_inputs.py` | one-time model fix (below); already applied |
| `models/ultraface-rfb-640/` | the face model, its MIT LICENSE and manifest |
| `validation/` | the 1107 runs, sheets, check results and the v2 replay spec (`make_v2_spec.py`) |
| `../../hq/tests/test_faces.py` | unit tests (`python -m unittest hq.tests.test_faces`) |

## Usage
```
python "D:/Agents HQ/tools/vision/faces.py" <video.mp4> <out.json> [--step 0.1] [--shots shots.json] [--min 0.04]
       [--pad 0.35] [--conf 0.4] [--grow 1.5] [--detector auto|yunet|ultraface|haar] [--sheet out.jpg] [--sheet-every 0.5]
python "D:/Agents HQ/.claude/skills/kids-review/scripts/stickers.py" plan <stickers.json> --faces faces916.json --faces faces16.json
python "D:/Agents HQ/tools/vision/faces_check.py" <faces.json> <build_stickers.py> --table FACES9 [--sweep]
```
Output: `{"size": [W, H], "aspect", "duration", "step", "detector", "params", "faces": [{"start", "end", "box", "face",
"conf", "hits", "track"}], "per_frame": {"0.000": [[x0, y0, x1, y1, conf], ...]}}`. `box` = padded avoid box (fractions of
the frame), `face` = the mean raw detection. Works on 1080x1920 and 1920x1080 (and a 90-degree rotation tag).

In kids-review, faces*.json files beside shots.json are loaded by the build_stickers.py template automatically
(typed FACES9 / FACES16 rows stay as extras), and `stickers.py plan|render --faces` adds them by hand.

## Decisions (made without asking, per the owner's "do it, no questions" rule)
1. **Detector: UltraFace RFB-640, not Haar.** The brief said Haar cascades ship in `cv2.data.haarcascades`. On this
   computer they don't: opencv-python-headless 5.0.0.93 has an empty `cv2/data` (only `__init__.py`). There's no
   YuNet .onnx in `tools/` or `.claude/skills/` either (searched, and searched all of D:). Nothing was downloaded.
   An MIT-licensed UltraFace RFB-640 (ONNX Model Zoo, Linzaer; sha256 8f4c6592...a6430, matching its manifest) was
   already on the computer inside JianyingPro (`AppData/Local/JianyingPro/Apps/11.7.0.14614/Resources/canvas_agent/
   models/ultraface-rfb-640/`). It was copied here with its LICENSE and manifest and runs on onnxruntime 1.30, which
   was already installed. Adobe's RetinaFace files (Premiere / Lightroom) are licensed only with those apps and are
   not used. `--detector auto` = UltraFace, then Haar if a future OpenCV ships cascades. YuNet only on request (below).
2. **`version-RFB-640.ort-ready.onnx`**: the export lists all 244 weights as graph inputs too, so onnxruntime
   couldn't pre-pack them (155 ms a run). `onnx_strip_inputs.py` drops only those input entries (the onnx package
   isn't installed, so it edits the protobuf wire format directly). Weights and outputs are unchanged (max diff 2e-7
   on a random input), and a run takes ~60 ms on one thread. The original file is kept next to it.
3. **Tiling**: the model takes 640x480 only. Each sample runs the whole frame once plus 2 overlapping 4:3 tiles, sized
   so a face of `--min` x short side is at least 16 model px. That's 3 inferences per sample on both shapes, frames
   decoded at 720 px short side, and 4 onnxruntime sessions x 2 threads (`HQ_VISION_WORKERS`, `HQ_VISION_INTRA`).
4. **Tracking**: boxes in neighbouring samples are linked by IoU, or by centre distance for fast moves. A gap of up to
   0.3 s is filled by interpolation, so flicker never drops a face. A track never crosses a `--shots` cut. A one-sample
   detection is kept only at conf >= 0.8. Median-of-3 smoothing. A range is split when its union box would pass
   `--grow` x the mean padded face (a face walking across the frame gets several snug boxes, not one huge one). Each
   range covers half a step either side, clamped to its shot.
5. **Padding**: `--pad` on every side, x1.4 on the top for hair and paper hats.
6. **Tuned defaults** (sweep below): pad 0.35, conf 0.4, grow 1.5, min 0.04. The brief's example of 0.25 is lower
   recall. A missed face costs a brand-check FIX, while an extra box (the detector also fires on a printed face on a
   water bottle, or a craft) only narrows where stickers can go, so the defaults lean toward recall.
7. **Recall measure** (`faces_check.py`): a hand box counts as "covered" when, on at least 50% of its 0.1 s samples,
   a detected box overlaps it by at least 25% of the smaller of the two. Many typed boxes sit beside the face (they
   were typed by eye), so the stricter 50% overlap is printed too. "Wildly oversized" = a box over 2x its own padded
   face AND over 5% of the frame. Close-ups are big by nature, and the frame-relative count is printed for
   information only.

## Validation on the 1107 Children review (52.2 s, 24 cuts; defaults above)
| | 9:16 vo-video-blur.mp4 vs FACES9 | 16:9 vo-video16-blur.mp4 vs FACES16 |
|---|---|---|
| recall (25% overlap) | **87.0%** (20 of 23) | **97.0%** (32 of 33) |
| recall (strict 50%) | 78.3% | 93.9% |
| time recall | 84.0% | 90.8% |
| wildly oversized boxes | 0 | 0 |
| face ranges / tracks | 252 / 192 | 587 / 313 |
| run time (522 samples) | 24.3 s (71 s with every core busy with other renders) | 26.2 s (69.6 s busy) |

The 3 9:16 "misses" are errors in the typed boxes, not missed faces. Checked on the frames
(`validation/1107-faces916.jpg` and frame crops):
- *woman at the top left (24.2-26.2 s)*: detected at 24.6 s. She leaves the frame about 25 s, but the typed box stays.
- *girl in a mask (28.2-30.2 s)*: the camera only brings her in at about 29.3 s. Detected from then on (45% of the shot).
- *woman at the left (30.2-32.2 s)*: the typed box [0, 0, 0.38, 0.24] is over the ceiling and air conditioner. Her
  face is at y 0.25-0.4, and it is detected.

So all 20 typed 9:16 boxes that really hold a face are found (100%), and 97% on 16:9. The 16:9 "helper" miss is the
same kind (she pans out of frame after 28.6 s). The one real weak spot is a face cut by the top edge of the frame: the
16:9 grandma at 24-26 s is found on only 50% of samples. Keep typing a FACES row for faces cut by an edge, masks
and backs of heads (SKILL.md step 8 says so).

Sweep (9:16, `faces_check.py --sweep`): pad 0.15/0.25 -> 82.6%, pad 0.35/0.5 -> 87.0% at conf 0.4. conf 0.7/0.8 lose
one or two boxes, and min 0.06 loses one. At grow 2.5, or pad 0.5, boxes start to come out wildly oversized.
16:9 at conf 0.5: 93.9%; at 0.4: 97.0%.

### The two brand-check catches, replayed (`validation/make_v2_spec.py` -> `1107-v2-placements.json`)
The original v2 positions (from `build_stickers.before16.py`, read only): hook sparkle 9:16 [0.91, 0.47] at
0.70-2.25 s, and rainbow 16:9 [0.88, 0.15] at 38.62-39.77 s. The avoid list is the v2 typed FACES9 (v2 had no FACES16).
- `stickers.py plan 1107-v2-placements.json`: **no warnings** (the typed boxes missed both faces, which is why the
  brand-checker had to catch them).
- `... --faces 1107-faces916.json --faces 1107-faces16.json`: **9:16 sparkle touches the face from 0.97 s to 2.2 s**.
  The detected face [0.876, 0.356, 1.0, 0.630] is the girl at the right edge, matching the later typed fix
  [0.86, 0.35, 1.0, 0.65]. **16:9 rainbow touches a face at 38.63 s and 39.47 s**: track 186, face
  [0.87-0.93, 0.16-0.28], the woman in green, matching the typed fix [0.875, 0.09, 1.0, 0.28]. She is detected from
  38.45 s, so the rainbow sat on her from its first frame, earlier than the 39.3 s the brand-checker noted. The v2 16:9
  sparkle guess [0.80, 0.55] is flagged too (on the right boy, 0.70-2.1 s); the 16:9 editor later moved it.

## Code review fixes (2026-11-09; the whole folder is now this worker's)
- **B1** textscan.py and gradecheck.py: a side-data entry without `rotation` (after the display matrix) no longer
  resets the 90-degree turn of a DJI clip. faces.py already did this.
- **B2** faces.py, textscan.py, gradecheck.py: ffmpeg's exit code is checked, and decoding under 90% of the expected
  samples (gradecheck: frames, against the stream's average frame rate so variable-rate phone clips don't trip it) is
  an error. A cut-short file never reads as "no faces", "no names" or a grade verdict on part of the video.
- **B3** faces.py: YuNet and Haar run on one worker (their OpenCV objects aren't thread-safe). UltraFace keeps one
  onnxruntime session per thread.
- **B4** faces.py and textscan.py: no video stream, no duration, or an unreadable file gives one JSON line
  (`{"ok": false, "error": ...}`) and exit code 1. gradecheck keeps its `{"error": ...}` and exit code 2.
- **B5** faces_check.py `--sweep` prints `-` when the hand table is empty.
- **C4** stickers.py `faces_avoid()` runs `faces.validate()`. The build_stickers template skips any `faces*.json`
  that fails it (e.g. a faces_check report) with a warning, and `stickers.py --faces` refuses it with a clear message.
- **Security:** both UltraFace files are pinned (size + sha256) in faces.py as well as in `model-manifest.json`
  (`ortReady`). Both are verified at load, so a swapped model plus an edited manifest still fails. Sessions load the
  verified bytes, never the path again. YuNet is never picked by `auto`: it runs only with `--detector yunet`, from `tools/vision/models`, listed in a `model-manifest.json` beside it AND pinned in faces.py `PINNED`, loaded from the verified bytes. No YuNet is pinned today, so a dropped-in file is refused with a JSON error.
- Regression on real footage: the 1107 9:16 run gives byte-identical faces and per_frame (19.3 s). gradecheck on
  the approved v4 gives the same numbers as before.

## Left open
- The delivered 1107 v4 plan (`work/creative/1107-children/stickers.json`) gets 30 (9:16) / 75 (16:9) "face (auto" warnings
  with the padded boxes, and 18 / 38 with pad 0. Two were checked on the v4 frames: the 真棒 bubble at 25.0 s and the
  耶 star at 27.3 s. Both sit beside the face, not on it. stickers.py compares a square around each sticker with the
  face box, so these are near contacts. With `--faces` the check is stricter than what the v4 brand check passed:
  read each warning on the sheet. Lower `--pad` (0.25 or 0.15) if a busy close-up leaves no room.
- An edge-cut face (half a head at the top of the frame) is the detector's weak spot. A typed FACES row still covers it.
- Speed depends on the load: about 25 s on a quiet machine, about 70 s when the other office renders use every core.
