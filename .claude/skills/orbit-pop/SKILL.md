---
name: orbit-pop
description: Orbit Pop (环绕弹字), a caption style for talk and sermon highlights (brand sheet approved 2026-11-02). Heavy bevelled Noto Sans SC Black words orbit the speaker - in the top band behind the head, a tilted pair beside it, rows over the chest, a glow column down the left side. One key per block (a lime-gradient word that pops in with overshoot, or a green Oswald number that drops in digit by digit), mixed-size rows, an English sub-word only for English the speaker says or a verse reference, and a Kick Exit (with one slice glitch) at section ends. Real CC0 sound on every designed moment. Use only when the owner asks for Orbit Pop, 环绕弹字 or "the ad style", on any channel; each channel keeps its default style otherwise. Plan first, then render; music, sound effects and an earshot listening check follow.
---

# Orbit Pop: words that orbit the speaker, one key that pops

The brand sheet is the law: `C:\Users\John Ooi\Documents\Style Guides\orbit-pop\guideline.pdf` (pages 3-11; source
`source/guide.html`), **with the owner's 5 answers below, which win where they differ**. The renderer reproduces the moves
frame for frame, so your job is choosing **which word is the key**, **which line earns a move** and **where a section ends**,
and keeping the words exact. Never change the speaker's words, scripture, numbers, negations or conditions.

Scripts: `D:/Agents HQ/.claude/skills/orbit-pop/scripts/` (call it `$OP`): `op.py` (type, colours, zones, checks, planning
page), `plan.py`, `render.py`. It reuses caption-card and poster-kinetic next to it (speech-to-text, compositing, matte,
preview), as Gold Stack does. One command per Bash call, quoted absolute paths. Every script prints one JSON line. Never
upload, post or delete anything.

## The owner's answers (2026-11-02, they override the sheet)
1. **Colour: the original ad's gradients, not Sunrise and not amber.** Key word lime diagonal #F2F538 (top right) to
   #AAEF40 (bottom left), glow #C8F23C at 40 %, blur 14 % of the size. Numbers (Oswald Bold) green vertical #86D53F to
   #416122. Text white #F9F9F9 to grey #D7D2D2. English sub-word grey #EEECED to #C1C0C0. `key_colour: "flat_yellow"`
   (#FAF535) and `"mint"` (#7BF7F6 to #B3F4E5) at most once each per video (the check warns). Stroke / shadow #0E1014.
   Glow column: a white / lime bloom (streak #F7FFE0 with a lime halo #C8F23C, bloom #EAFFB0), not amber.
2. **Channel:** any channel (main, Pong+Gospel, others) when the owner asks for it.
3. **Above the head:** a top-band word behind the head (zone A) and the glow column may come more than twice per video.
   The tilted pair beside the head (O5) stays at most 2 per video. (The sheet's "Pong: at most 2 above the chin" is dropped.)
4. **Keep the slice glitch** (O10): only f0 of a Kick Exit, at most once every 10 s.
5. **English sub-word: only English the speaker actually says, plus verse references** he names. Never a translation; the
   planner must not invent English (the check refuses a sub that is neither).
6. **Behind the head: as big as possible, as Gold Stack** (owner 2026-11-02, following the "more bigger" choice for Gold
   Stack's word behind the head). The top band starts at L 210 px, the tilted pair at 240 px, the glow column at 136 px. Each
   sits as close to the head as lets at most 40 % of a character go behind it, and shrinks only while less than 35 % of a
   character would show on some settled frame (after its pop, before its exit). The person matte keeps the head and face in front (the column too: it may go behind
   the hair). This replaces the sheet's 80 %-visible floor and the column's 30 px clearance. The negative-key-word rule does
   not apply to Orbit Pop (its key is lime, owner answer 1).

## Steps
1. **Source.** As Gold Stack step 1: a clean, caption-free cut at **30 fps**, fillers and pauses out with yellow-serif
   `tighten.py` (use `tight.mp4` and its cut map), the speaker's own voice only (interpreter phrases and crew lines cut),
   the sermon speaker crop and the footage-mix rule for RAW livestreams. Main channel 45 s max; Pong+Gospel the whole talk.
2. **Plan.** `python "$OP/plan.py" <dir>/tight.mp4 <dir>/plan.json` (env `YS_LANG=zh`), or reuse another style's approved
   lines with `--from-plan <other plan.json>` (words and timings unchanged; it keeps the measured camera face / chin /
   head top). Fix misheard words and say so in `note`. Digits for numbers, % for percentages, God is always 祂, scripture in
   和合本 wording.
3. **Measure the face.** 3 frames per shot: `camera.face` = [x, y] (0..1), `camera.chin` = the lowest chin y on the
   1080x1920 source frame, `camera.head_top` = the top of the head. The renderer works out the chin on the output for
   every framing (wide, 1.15x tight, the opening push) and keeps zone C 40 px below the lowest chin the block meets.
4. **Choose** (each line starts as a zone C block whose words settle as spoken; a line is one block):
   - `key`: the block's one key, an exact part of the line, negation included (没有定他的罪, never 定他的罪). It pops (O2)
     in lime; `key_colour` flat_yellow / mint at most once each. A block with a number has no key word.
   - `zone: "A"`: the key goes to the top band (top at y 210) **behind the head** (person matte), split either side of
     it, at L 210 px, shrinking only while less than 35 % of a character shows on a settled frame. At most 4 characters;
     never a Latin word or digits, never a negation or condition split around the head (不要, 真的不).
   - `move` on the lines that earn it:
     - `slide` (O4, at most 3): the XL first word (1-2 characters, never a 不 or a condition) slides in from the left.
     - `mixed` (O6): the XL first word pops in and the next words sit small beside it (at most 4 M or 6 S), then the rest.
     - `number` (O7, a real spoken count, day, verse or %; never money): `number` = digits, optional `unit` (次, 天) and
       `lead` (第); the digits drop in one per 2 frames and breathe; the words after it stay small on its baseline.
     - `tilt` (O5, at most 2): `word` = a two-character turn word (其实, 但是, 可是, 原来, 而是) on a pause; one character
       each side of the head at -8.5 / +18 deg, behind it, 240 px, shrinking only while less than 35 % of one shows
       on a settled frame.
     - `column` (O9, once, the last line): `word` = the closing takeaway (at most 6 characters) down the left (zone D),
       136 px, behind the head and hair (matte), with a light streak along the chest and a lime-white bloom, held to the
       last frame; the rest of the line sits in zone C.
   - `sub` (O8): an English sub-word under the block, typed on. Only English he says (`"PONG"` if he says Pong) or a verse
     reference he names: the full book name with the chapter right after it (约翰福音21章 gives `"JOHN 21"`; 罗马 alone or
     雅各 alone is not a reference). The check refuses anything else. A verse reference types on as its chapter number
     lands (JOHN 21 starts with the 21, done in 6 frames, so it is read for most of the block); `sub_at` (s) sets the
     start by hand.
   - `exit: "kick"` (X1) on the last block of a section (a change of idea with a pause of at least 0.25 s), at most 1 per
     6 s; `glitch: true` on one of them (O10, at most 1 per 10 s); `push: true` (C2, at most 1 per 10 s) pushes in under it
     where the framing is wide. Every other block takes the plain exit.
   - Plan `broll`: `[{"from": s, "to": s, "face": [x0, y0, x1, y1] or null}]` for cutaways without the speaker (output
     pixels). There the check refuses zone A, tilt and column, and zone C starts at y 870 and 40 px under that face.
   Pacing (errors in `--check`): every designed move is a moment, sounded or silent (key pops, the O6 XL pop, the top
   band, the tilt, the number, the column, kicks); moments of different blocks at least 1.5 s apart. One block is one
   moment: a kick belongs to the next block (kick + its pop, C2 + X1), the opening push to block 1 only when block 1's
   first move peaks within 0.67 s (f14 + 6); otherwise each is its own moment with its own sound. At least one moment every 10 s (warning). **One sounded moment per block**: an incoming kick or the opening push
   is the block's sound and its pop stays silent; otherwise its first sounded move sounds (slide > number > tilt > column >
   key pop). Long talks are dense: not every line gets a key (on 11/28 line 1 has none: the push is its moment).
5. **Check.** `python "$OP/plan.py" --check <dir>/plan.json --map <dir>/<cut map> --matte <dir>/matte.mp4` (the same
   cut map and matte as the render: the framing switches move exits and kicks, and the matte decides any zone C fallback;
   fix every error, think about every warning; its `sounds` list
   shows which move sounds in each block and which stay silent), then `python "$OP/plan.py" --md <dir>/plan.json` for the
   planning page. Stop here if the owner wants to see the plan first.
6. **Render.** Zone A, tilt and column need the person matte first:
   `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/matte.py" <dir>/tight.mp4 <dir>/matte.mp4`
   `python "$OP/render.py" <dir>/tight.mp4 <dir>/plan.json <dir>/edit.mp4 --map <dir>/<cut map> --matte <dir>/matte.mp4 --phone`
   (`--to 15 --preset veryfast` for a quick look; `--no-text` for clean.mp4, same frame count). About 3x real time.
   It refuses a matte shorter than the clip, and writes the plan it used as `<out>.plan.json` (never over plan.json).
   Use the cut map with every pause cut (Gold Stack used `joins.cutmap.json`). Writes `edit.mp4`, `edit.srt`,
   `edit.pk.json`, `edit.sfx-events.json`, `edit.zoom.json`, `edit_phone.mp4`. Read its `warnings`, `behind_visible_min`
   (every behind-the-head character on every settled frame, must be >= 0.35; `behind_visible_min_all_frames` adds the
   pop and exit frames, for information), `behind_pop_peak` (122 % top band, 106 % tilt), `column` and `blocks`.
   Behind the head falls back to zone C (warning) when there is no head in the shot, the head does not reach the middle of
   the band, or a character would sit less than 15 % behind the head on every frame; each character's ink stays on its
   own side of the head's centre. After a fallback the render checks the pacing again and lists any break in `warnings`.
   `--no-text` (clean.mp4) leaves out every text effect, the column's light streak and bloom included.
7. **Look.** `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/preview.py" <dir>/edit.mp4 <dir>/preview.jpg --at ...`
   at each move (pop f3, the number, the tilt, both kick frames f0 / f2 with the glitch, the column f0 / f10 / hold). Ask
   for exact frames as n/30 rounded down to 3 decimals (ffmpeg shows the next frame otherwise). Then measure the letters on
   every frame as edit minus clean (as the Gold Stack brand checks did): x 86-994, x <= 950 in y 1000-1700, y 200-1620,
   zone C at least 40 px under the chin; only a kick burst frame (f2) may cross the side, button and bottom lines.
   **The face box (eyes, nose, mouth) gets 0 letter px on every frame, bursts included.** Letters seen through flyaway
   hair at the matte's edge are allowed (the brand-checker judged them invisible on a phone); count them separately.
8. **Music, sound, listen** (every edit), exactly as Gold Stack step 8: `music.py <dir>/edit.mp4 <track> <dir>/edit-music.mp4`
   (Pong+Gospel: Piano_Echo by TreyVZ with `--room`, the default level: 12 dB under the voice, 5 in the gaps), then
   `place.py <dir>/edit-music.mp4 <dir>/edit.sfx-events.json <dir>/edit-sfx.mp4`, then from `D:/Agents HQ/tools/ext/earshot`:
   `.venv/Scripts/python -m earshot timeline "<dir>/edit-sfx.mp4" --cues "<dir>/edit.sfx-events.json"`: -14 LUFS, true
   peak at or under -1 dBTP, every cue hit within 100 ms, music heard with speech in every section. Mux the same audio onto
   the phone and clean copies (`-map 0:v -map 1:a -c copy`).
9. **Brand check, then deliver** as the other styles: brand-checker review, `notes.md`, `out/<name>/` with `edit.mp4`
   (= edit-sfx.mp4), `captions.srt`, `clean.mp4`; then Social's posting pass. Nothing is published.

## The moves (30 fps, sheet pages 7-10)
| Move | Frames | Sound (sfx library, loudest on) |
|---|---|---|
| O1 Settle (supporting words) | f0 106 % full opacity, f2 100 % | none |
| O2 Pop (the key) | 12 45 85 **122** 108 102 100 %, peak f3 on the syllable | `pop` f3 (silent after a kick / the opening push) |
| O3 Rise (middle rows of 3+) | f0 1.1x its height lower, 0 %, blur 8 px; f5 in place | none |
| O4 Side Slide (XL first word) | f0 30 % of its width outside x 86, f6 in place (ease-out quint) | `swish_soft` f1 |
| O5 Tilt Pop (pair behind the head, 240 px) | 15 49 88 **106** 102 100 %, the second 7 frames later | `pop` each f3 |
| O6 Mixed Row | XL first word pops, small words settle after it | only its O4 / key sound |
| O7 Digit Drop | each digit at 116 % -> 100 % in 2 frames, 2 frames apart, then +-6 % breath for 12 frames | `impact` f0 |
| O8 Sub-word Type-On | 1 letter a frame (2 when longer than 6), each 115 % -> 100 % | none |
| O9 Glow Column + Light Streak | streak f0-f10 (fades by f18), ghost f4-f7 to 30 %, flare f8-f10, bloom decays f11-f18, held | `whoosh_zoom` f10 |
| O10 Slice Glitch | f0 of a kick: 3 bands -24 / +18 / -12 px (room kept inside the margins) | none |
| X1 Kick Exit | 88 108 **155** (6 px motion blur) 88 % from the block's top-centre, gone f4; characters behind the head take a plain exit on f0 (never a burst toward the face) | `whoosh_fast` f2 |
| plain exit | 2 frames to 90 % and 0 % | none |
| C1 Opening Push | 100 -> 112 % in 14 frames (ease-out cubic), then holds at 112 % | `whoosh_zoom` f2 |
| C2 Push Cut | 100 -> 115 % in 6 frames under a kick (replaces the next hard switch to tight) | shares the kick's |

## The camera
C1 opens every video and the shot then holds at 112 % with a slight drift (`camera.drift` 0.4: about +-7 px). With
`--map` it switches between the wide and a 1.15x tight framing (around `camera.face`) at the pause cuts, on the exact frame
the picture cuts, each framing at least 1.2 s, exactly as Gold Stack. A block's exit finishes a frame before a framing
switch it would otherwise straddle, so its text never sits on the new framing's chin. The closing glow column holds the
framing it starts in (`camera.hold_column`, default on): the room beside the head is gone in the tight framing. Text is
pinned to the screen, never moved by the camera.

## Good to know
- Type: Noto Sans SC Black (variable font, Black instance) for every Chinese word, tracking -2 % on advances so glyphs
  never overlap; Oswald Bold for numbers (tracking -4 %, digits never overlap) and the sub-word (cap height 92 px, only the
  tracking stretches it to the row above, up to +15 %; short = right-aligned; long = right-aligned, no extra tracking).
  Sizes XL 270 / L 210 / M 150 / S 100, tilt 240 (sheet 220-260), column 136, number 400. Layers as the sheet: bevel (3 % inner edge,
  +45 % light top-left, -30 % dark bottom-right), gradient fill, 3 px #0E1014 stroke at 70 %, key glow, shadow black 65 %
  blur 9 % 4 % down.
- Every move starts on a whole frame, so the 122 % pop and the 155 % burst really show (between frames they were averaged
  away). Overshoots are clamped: never past the margins (x 86..994, 950 in the button band, y 200..1620) and never above
  the block's chin + 40 line; the first row starts lower by its own overshoot so it can still pop.
- Behind-the-head characters (zone A, tilt, column) are placed on the person matte sampled every 2nd frame they are on
  screen and measured again on every rendered frame (`behind_visible_min`); the person goes back on top 2 px wider so the
  soft hair edge covers the letters. Each stays on its own side of the head (never 改悔 / 是而), and is placed with room
  for its pop's overshoot (122 % / 106 %) inside the margins and under y 200. The 35 % rule is for settled frames; while a
  character is still tiny in its pop (12-45 %) it can sit wholly behind the hair (`behind_visible_min_all_frames`).
- Every block shrinks to fit only so far: below S (100 px) it warns (split the line); no room for one S row under the
  chin is an error. The opening push takes block 1's sound only when block 1's first move peaks within 0.67 s.
- On Pong's 11/28 footage all three stayed at their targets (210 / 240 / 136 px); the least visible settled frames showed
  57 % of 悔, 58.8 % of 改, 46 % of 而, 36.2 % of 是 and 82 % of 你. With the earlier 80 % floor they had to shrink to 150 / 140 / 88 px (kept as `*-r1`).
  The renderer warns whenever it shrinks.
- Test edit with every move checked frame by frame: `D:\Agents HQ\work\creative\pong-1128-orbit-pop\`.
