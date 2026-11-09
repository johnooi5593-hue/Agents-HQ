# textscan: readable-text check for every shot (board t203)

Brand rule: never a readable child's name. Until now that was an eye check on zooms. On the 1107 Children review
the 16:9 editor found 5 spots by eye (teacher badge "VICKY ONG 王美婷", the door charts, a helper's badge, name stickers
on two water bottles), and the 9:16 brand check caught the badge late. `textscan.py` makes it a machine check: it lists
every piece of text it can read, marks the name-like ones, and draws them on a sheet a human checks in a minute.
`blur_hits.py` turns chosen hits into blurs in one step.

| File | What |
|---|---|
| `textscan.py` | the scan: video -> `hits` json (+ `--sheet` contact sheet) |
| `blur_hits.py` | hits -> box json for `.claude/skills/kids-review/scripts/blur.py`, and/or an ffmpeg filtergraph |
| `../../hq/tests/test_textscan.py` | 24 tests: frames with text drawn by PIL and a 3 s synthetic video through the real OCR, merge, classifier, labels, blur json and cut timing |

## Use

```
python tools/vision/textscan.py <video.mp4> <scan.json> --sheet <scan.jpg>
python tools/vision/blur_hits.py <scan.json> <boxes.json> --video <video.mp4>                 # every name-like hit
python tools/vision/blur_hits.py <scan.json> <boxes.json> --video <video.mp4> --ids 3,7,12    # the ones you picked on the sheet
python .claude/skills/kids-review/scripts/blur.py <video.mp4> <boxes.json> <video-blur.mp4>
python tools/vision/textscan.py <video-blur.mp4> <scan-after.json> --sheet <scan-after.jpg>   # proof: the names are gone
```

Options: `--step 0.5` (seconds between samples), `--min-height 0.012` (smallest character, as a fraction of the frame's
short side: 13 px at 1080), `--min-conf 0.5`, `--tiles 2 --zoom 2` (the 2x2 enlarged-tile pass), `--ignore words.txt`
(extra allow-list words, one per line; a `captions.srt` works too, so a finished edit's own captions are never flagged:
any 2+ character piece of an ignore line counts as known), `--no-labels`. `blur_hits.py`: `--kinds name-like,label`, `--all`, `--pad 0.3`
(of the box width, each side), `--pad-y 1.2` (of the text height, above and below, so the next badge line is covered),
`--size WxH`, `--ffmpeg graph.txt` (then `ffmpeg -i in.mp4 -/filter_complex graph.txt -map "[vout]" -map 0:a? ...`;
ffmpeg 9 here has no `-filter_complex_script`).

Output: `{"size":[W,H], "step", "duration", "samples", "hits":[{"id","start","end","box":[x0,y0,x1,y1 fractions],"text",
"conf","kind","keys":[[t,x0,y0,x1,y1],...]}]}`. `id` is the number on the sheet; `keys` are the per-sample boxes, so a
blur can follow the camera.

## What got installed

- `rapidocr-onnxruntime 1.4.4` (pip, `--no-deps`), PP-OCRv4 Chinese + English detection/recognition ONNX models bundled
  (about 15 MB), CPU only. Its other needs were already there or came in with it: `onnxruntime 1.30.0` (already),
  `pyclipper 1.4.0`, `shapely 2.2.0`, `six 1.17.0`, `PyYAML`, `Pillow`, `numpy` (already).
- OpenCV: the plain `pip install rapidocr-onnxruntime` failed with "Access is denied ... cv2.pyd": the faces.py worker
  had just installed `opencv-python-headless 5.0.0.93` and its cv2.pyd was in use. So I installed rapidocr with
  `--no-deps`; it imports and runs on the headless OpenCV. `pip check` will say rapidocr wants `opencv-python`; that is
  expected and harmless (same `cv2` module, without GUI windows, which nothing here uses). Don't install `opencv-python`
  on top: two OpenCV wheels in one environment clash.
- No pip block, so the MSER/stroke-width fallback was not needed as the engine; a small heuristic of that kind is used
  for unreadable labels (below).

## How it works (decisions)

1. **Sampling.** One ffmpeg pipe, `fps=1/step`, decoded at the displayed size (the rotation tag is applied, see the
   1101 DJI lesson). Default step 0.5 s: shots on the reviews are about 2 s, so every shot gets 3-4 samples.
2. **OCR passes.** Whole frame + a 2x2 grid of tiles (15 % overlap) enlarged 2x. On 1107 the teacher badge is 14-25 px
   text: the whole frame alone reads `VICXYONG` but never the Chinese name; the tiles add `王美婷`-like readings. 3x3
   tiles at 3x read a little more (e.g. `PJ` on the door chart) but cost 2-3x the time; not the default.
3. **Keep.** confidence >= 0.5, at least 2 letters/characters, character size >= `--min-height`. Readings of the same
   spot from the whole frame and the tiles are de-duplicated (best confidence wins).
4. **Merge.** A reading joins a range from the last 1-2 samples (one missed sample is bridged) when the text is similar
   (>= 0.6, normalised, so `VICXYONG`/`VCXYONG`/`VICKYONG` merge) near the same place, or the boxes overlap (IoU >= 0.3)
   with loosely similar text. `start` = first sample, `end` = last sample + step (clamped to the video).
5. **kind.**
   - `name-like`: 2-3 Latin words in Title Case or ALL CAPS that are not all everyday English words; or one 6-16 letter
     cased word when the text is small (<= 3.5 % of the short side), because OCR drops the space in `VICKY ONG`; or 2-4
     Chinese characters starting with a common surname (王 李 陈 林 ...; Malaysian Chinese surnames included). The
     surname rule is my tightening of the brief's "2-4 CJK not in the allow-list": shirt prints and misreads (`累代`,
     `共田`) were the biggest false-positive source and none of them start with a surname.
   - `label` (added, not in the brief): text `[label]` for a small light sticker / card / chart with dark marks in it
     that OCR can't read. The water-bottle name sticker (8 px handwriting) and the door chart rows are below what any
     OCR reads at 1080p; this pass points at them anyway. Two masks (white paper; paper lighter than its surroundings),
     rectangular, 0.04-2 % of the frame, ink 2-35 %, edges, lighter than the ring around it, and not already a text hit.
   - `brand`: a known brand (Vitagen, adidas, Emirates ... ~45), fuzzy (`Witagen`, `Emintes`).
   - `other`: everything else, including the allow-list (from the 1107 notes: Prayer Room / 祷告室, 出口, KELUAR,
     SHARK SIGHTED, NO SWIMMING, Mongolia / 蒙古包, PJ, SPORT, WARNING, ALWAYS, Fly Better, Cool Buddy, plus church and
     sign words). A known Latin sign phrase inside a line (`PrayerRoom请含室`) makes the whole line a sign; a fragment
     of a known word (`LUAR`, `SIGHTED`) is known too. `--ignore` adds words.
   Every hit stays in the json and on the sheet; `kind` only orders them (name-like, label, brand, other).
6. **Sheet.** One cell per hit: the frame with the box (red name-like, pink label, orange brand, yellow other), a
   zoomed crop, `#id start-end kind`, the text and confidence. Chinese text drawn with Microsoft YaHei.
7. **blur_hits timing.** With `--video`, ffmpeg's `scdet` finds the cuts; the blur starts at the cut up to two steps
   before the first sample and stops at the first cut up to two steps after the last one (else one step), so it covers
   the whole time the text is on screen without spilling onto the next shot.

## 1107 Children: results

Defaults (step 0.5, 104 samples per 52 s video). A known spot counts as found when a hit's box is within 40 px of the
human box at a time inside the spot's range. Human lists: `work/creative/1107-children/blur16.json` (5 spots, 16:9)
and `.claude/skills/kids-review/templates/blur916.json` (badge only, 9:16).

**16:9 `vo-video16.mp4` (unblurred): 4 of 5 found, the badge as name-like.**

| Spot (human) | Found by |
|---|---|
| teacher badge 10.15-12.2 s | `VICKYONG` 0.99, **name-like**, 10.0-12.0 s |
| door charts 12.2-14.2 s | 2 x `label` 12.5-14.0 s on the charts, and the `Prayer Room` sign above them (other) |
| helper's badge 28.2-29.1 s | **missed**: a blue card seen edge-on with a white blur; no text and no light label to find |
| white bottle sticker 32.2-34.2 s | the bottle's `SPORT` print (other) 32.0-34.0 s, right on the sticker box; the sticker itself is unreadable |
| blue bottle sticker 39.8-41.8 s | `label` 40.0-40.5 s on the sticker |

Hits that are not one of the 5 spots: **6 name-like** (`IAMMTO`, `万开`, `QaVie`, `MADLING`, `JSU KUOTUR`, `STRO`: shirt
prints and misreads; none is a real name on review), **10 label**, 4 brand, 75 other (101 hits in all). The first
untuned run had 17 name-like extras and 49 labels; the tuning (allow-list from these notes, everyday-word list,
surname rule, single-word size cap, label conf >= 0.5 and not cut off by the frame edge) took them to 6 and 10 with
no loss of recall.

**9:16 `vo-video.mp4` (unblurred): 1 of 1 found.** The badge is read fully: `VICKYONG` 0.99 and `王美婷` 1.00, both
name-like, 10.0-12.0 s. Extras: 2 name-like (`万月`, `LYORTTE`), 6 label, 2 brand, 51 other (66 hits).
**New finding:** the 9:16 scan also reads the door charts (`PJR小#`, `PJXI`, 12.0-12.5 s, x 0.73-0.78, y 0.17-0.27),
and the delivered `out/1107-children-review/edit.mp4` shows both PJ charts unblurred at about 12.0-13.5 s (frame
checked at 12.3 s). The rows are not legible at 1080x1920, but the 16:9 blurred the same charts. Brand-checker's call;
I didn't change any delivered file.

**After the blurs** (`vo-video16-blur.mp4`, `vo-video-blur.mp4`; blur.py with the human boxes):
- 16:9: the badge hit, both door-chart labels and the blue-bottle label are gone. What still touches the 5 spots is
  the `Prayer Room` sign just above the charts and the bottle's big `SPORT` print (both `other`; the human boxes cover
  the charts and the sticker, not the sign or the print). 0 name-like and 0 label hits left on any known spot. Totals: 6 name-like, 11 label,
  3 brand, 70 other, all elsewhere.
- 9:16: the badge hits (`VICKYONG`, `王美婷`) are gone; 0 hits left on the badge. The door-chart readings are still
  there (not blurred in 9:16), plus 2 name-like misreads around them (`PIAOBL`, `Holiam` on the Mongolia print).

Note on how the numbers were made: 4 full scans ran side by side (~1 h). The label filter was tightened after them, so
the label pass was re-run alone on the same frames (OCR hits unchanged, same overlap rule) to get the numbers above;
a final full run of the shipped code on `vo-video16.mp4` confirmed them (see Confirm run).

**Confirm run** (final code, `vo-video16.mp4`, PC shared with one other job, ~25 min): 101 hits (7 name-like,
13 label, 4 brand, 77 other), the same as above, and the same 4 of 5 spots. On the sheet the badge crop reads
"VICKY ONG / 王美婷" plainly; the 6 extra name-like cells are "La Vie en Rose", "Minuman Susu Kultur" (Vitagen),
"Made in China", a mat print, a shirt print and a toy-mat word: a glance each.

**Recall summary:** badge 2/2 (both sizes, as name-like); other 16:9 spots 3/4 (door charts, white bottle, blue
bottle; helper badge missed). Name-like false positives per video: 6 (16:9), 2 (9:16), all visibly prints/misreads on
the sheet.

## Limits

- OCR reads text a viewer can read on a phone; it can't read what is only a blur at 1080p. Such spots come back as
  `label` (or not at all when the patch is not a light rectangle, like the helper's blue badge card, seen edge-on).
  The eye check on native zooms stays for those; the scan makes it a check of a short list instead of every frame.
- Time: about 5-6 s per sample on this PC (whole frame + 4 tiles, CPU), so about 10 minutes for a 52 s video when the
  PC is free; 4 scans side by side took about an hour. `--tiles 0` is ~5x faster but misses badge-size text.
- The `name-like` rules are heuristics: names written in lower case, or a single Chinese given name without surname,
  come back as `other` (still on the sheet).
- `blur_hits.py` blurs what OCR boxed: one text line plus `--pad-y` lines around it. For a whole badge or chart, widen
  `--pad`/`--pad-y` or draw the box by hand from the sheet; then re-scan the blurred video (step 3 of Use).

## Checklist lines (proposed; agents and skills are not edited here)

kids-review `SKILL.md`, step 4 (Name blurs), before the eye check:
```
   - Machine check first, per size: `python "D:/Agents HQ/tools/vision/textscan.py" "<W>/vo-video.mp4" "<W>/text916.json" --sheet "<W>/check/text916.jpg"`
     (and `vo-video16.mp4` → `text16.json` / `text16.jpg`; ~10 min each, both can run at once). Look at every red
     (name-like) and pink (label) cell on the sheet; blur the real ones with
     `python "D:/Agents HQ/tools/vision/blur_hits.py" "<W>/text916.json" "<W>/blur916.json" --video "<W>/vo-video.mp4" --ids <ids>`
     (merge with any hand-drawn boxes), then the eye check on native zooms for what OCR can't see (blurry badges seen edge-on).
   - After blur.py, re-scan the blurred file: no name-like or label hit may remain on a blurred spot; list what is left
     and why it's fine (signs, prints, brands) in notes.md. The same thing must be blurred in both sizes (1107: the door
     charts were blurred in 16:9 but not in 9:16).
```
kids-review `SKILL.md`, step 10 checklist:
```
    - [ ] textscan on both delivered sizes: 0 name-like / label hits on a person's name; text916.jpg and text16.jpg in check/
```
brand-checker (agent), new numbered step after 5:
```
6. **Readable names** on any video with children, badges or name lists (kids reviews, events): run
   `python "D:/Agents HQ/tools/vision/textscan.py" out/<name>/edit.mp4 out/<name>/textscan.json --sheet out/<name>/textscan.jpg --ignore out/<name>/captions.srt`
   (16:9 folder too; `--ignore` keeps the edit's own captions out) and look at the sheet. A name in the captions
   themselves is checked from captions.srt as before. Any `name-like` hit that is a real name, or a `label` on a name sticker,
   badge or chart, is a `FIX` with its time and box. Signs, prints and brands are fine. Name the hits you cleared in
   brandcheck.md.
```
