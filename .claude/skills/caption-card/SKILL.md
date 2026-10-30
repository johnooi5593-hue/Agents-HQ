---
name: caption-card
description: Caption Card (字卡动效) style for sermon highlights and other vertical clips - every phrase on a cyan card with blue slanted words (2-6 characters), now v2 (owner-approved on Pong+Gospel 11/14) - each line's cards animate in with their own entrance (rise, slide, slam, stagger, wipe), the stressed word pops with a yellow key-word bar, the quiet heavy line breathes in, and the picture moves (push-in / drift per shot, handheld sway, 1.25x punch-in, final pull-back) under a cool-to-warm grade arc with light leaks, warm light and accents (rings, orbs, halo); plus pro big-type moments (about one every 8 s) built with layered type (gradient, dark soft shadow, glow, background blurred and dimmed) - a 3-line hook whose key row scatters and gathers, a giant gradient number, a phrase written on like a light pen, a punch line that slams in. Built from the owner-approved guide measured from an Instagram ad. Use when the owner asks for caption-card, 字卡, "the IG ad style", "the XiXi style", "the 1114 look", cyan caption boxes, or very pro word animation / motion graphics on a sermon highlight. Plan first, then render; the sfx skill adds sound after. `--classic` renders the v1 look.
---

# Caption Card: cards for every phrase, pro big type for the few that matter

The style in one line (guide: `C:\Users\John Ooi\Documents\Style Guides\xixi-trading-reel\guideline.pdf`, read pages 2, 5-6 and
14 once; numbers in `GUIDE.md`): **every line is a caption card that animates in, its key word pops; about one line every 8 s earns
big type; the camera and the light carry the mood.** The look is built into the renderer; your job is choosing the right lines,
their key words and moments, and keeping the words exact. Never change the preacher's words, scripture, numbers, negations or
conditions.

Scripts: `D:/Agents HQ/.claude/skills/caption-card/scripts/` (call it `$CC`). It reuses poster-kinetic (fonts, speech-to-text,
preview) next to it. One command per Bash call; quoted absolute paths; run from a short folder. Every script prints one JSON
line. Never upload, post or delete anything. `render.py` is v2 (the default); `--classic` (or plan `"motion": "classic"`) gives the
v1 look (hard-cut cards, no camera, grade or light, a 1.35x picture punch). `render_v1.py` is the original v1 renderer, kept as is.

Reference: the owner-approved v2 is Pong+Gospel 11/14 (`work/creative/pong-1114-caption-card/v2/edit-sfx.mp4`, plan
`v2/skilltest_plan.json`, full-resolution footage `v2/cut_hr.mp4` + `cutmap.json`). Read that plan once: it is a worked example of
most fields below (it was rendered with the `--hr` / `--hr-map` flags instead of plan `hr`).

## Steps
1. **Source.** A clean, caption-free edit (e.g. `clean.mp4` / `cut.mp4`), or cut a topic from a RAW livestream as in the
   poster-kinetic skill (speaker crop `--crop 960:297:960:540 --focus ...`; the owner's rule: no slides from the RAW).
   **Also keep the full-resolution footage of the same cut** when the camera's own file is bigger than 1080x1920 (4K / 1728x3072):
   the same ranges, the whole camera frame (as `pong-1114-caption-card/v2/cut_hr.py` does), with a `cutmap.json` that gives each
   shot's box (`"wide"` / `"tight"` re-framings). The camera's pushes and the 1.25x punch-in then crop real pixels instead of
   blowing up the 1080x1920 edit.
2. **Plan.** `python "$CC/plan.py" <clip> <dir>/plan.json` (CPU faster-whisper, local large-v3-turbo; `YS_LANG=zh` for Chinese),
   or reuse an existing plan's lines: `python "$CC/plan.py" --from-plan <other plan.json> <dir>/plan.json`. Read the transcript;
   fix clearly misheard words in `text` (the cards show `text`; the word times stay for timing) and say so in `note`.
3. **Every card line:** `"key"`: the stressed word(s) of the line, exact parts of `text` (a yellow bar wipes in under it as it is
   spoken, the word turns deep blue and pops). One key on most lines, two on a list (`["麻烦", "担心"]`), none on a bridge line
   (`[]`). Optional `"anim"`: `rise`, `slide`, `slam`, `stagger`, `wipe` or `cut`; leave it out and the lines take turns, so
   neighbours never match.
4. **Choose the big moments** (most lines stay `"kind": "card"`). About one every 8 s (1114: 8 in 65 s; in `--classic`, one every 12-20 s),
   at least 3 s apart, each with `"why"`:
   | kind | when the words... | fields (exact parts of the line) | default colour |
   |---|---|---|---|
   | `hook` | open the clip, or a turn: a question or bold claim | `rows`: 2-3 short rows in word order, 2-6 characters / 1-3 words each; the last row is the key (or `key_row`) | key row `key` yellow (try `gold`) |
   | `breathe` | the quiet, heavy line (tired, alone, lament) | `rows`: 2-3 rows; the last (or `key_row`) is the big one; they fade, rise and unblur slowly, then drift and dissolve up | key row `ice`, the others white |
   | `number` | give a number, a count, a chapter or a percentage | `number`; optional `label` (short, shown above) and `unit` (beside) | `lime` |
   | `writeon` | carry the promise or a name to remember | `phrase` (up to 7 characters / 4 words); optional `sub` under it | `green` (try `gold` for grace) |
   | `punch` | call to action, the one sentence to obey | `phrase` (4-7 characters / 1-4 words); the picture punches in 1.25x | `yellow` |
   Colours: `key, yellow, lime, green, white, gold, ice, cyan, rose` or `#hex`. Merge two transcript lines first when a hook's rows
   or a number's label span them (edit `text` and join `words`).
5. **Line extras** (each optional, use sparingly):
   - `"transition": "flash"` (a 4-frame white flash on the cut, then a warm light leak; a section start) or `"blurcut"`.
   - `"accent"`: `rings` (two light rings open as it lands, a punch), `orbs` (two soft lights drift together, "two"), `halo` (a
     soft gold glow behind it, the promise).
   - `"leak": true`: a soft warm light leak at the line's start. `"sway": true`: handheld sway while it is spoken.
   - `"punch_in": 1.15` (1.0-1.25): a quick camera punch-in at the line's start (a key sentence that is not a big moment).
   - `"y"` (0-1): move big type off a face.
6. **Plan level** (v2; 1114 values in brackets):
   - `"camera"`: `{"face": [x, y]` (0-1 in the frame; the zoom centre) `[0.444, 0.266]`, `"cuts": "auto"` (found from frame
     differences: re-framings and jump cuts too) or `[times]`, `"sway": [[t0, t1], ...]`, `"punch_scale": 1.25` (1.0-1.35),
     `"pull_back": "auto"` (from the last line to the end; or `{"start": t, "end": t, "to": 1.0}`, `false` for none),
     `"on": false` (no camera)`}`.
   - `"grade"`: `[[t, g], ...]` with g -1 (cool, dim) .. 0 (neutral) .. +1 (warm), eased between points, with a vignette. Follow
     the message: cool through the problem, neutral at the turn, warm at the promise
     `[[0,-1],[26.54,-1],[30,0],[46,0.3],[49,1],[65.6,1]]`.
   - `"light"`: warm bloom and floating light particles (kept off the face) to the end: `true` (from where the grade turns
     warm), a time, or `{"from": 46, "bloom": 0.16, "particles": true}`.
   - `"hr"`, `"hr_map"`: the full-resolution footage and its framing map (paths relative to the plan's folder;
     for a plan in 1114's `v2/`: `"hr": "cut_hr.mp4", "hr_map": "../cutmap.json"`). When the files are there, every render and preview uses them.
   - `"card": {"box", "text", "text2"}` for a church colour pair, `"card_y"` (default 0.51, the chest).
7. **Check.** `python "$CC/plan.py" --check <dir>/plan.json` (fix errors; weigh warnings: long rows shrink, moments too close,
   a key that never shows, neighbours with the same entrance) and `python "$CC/plan.py" --md <dir>/plan.json` writes the
   planning page. Stop here if the owner wants to see it first.
8. **Render.** Preview any part: `python "$CC/render.py" <clip> <dir>/plan.json <dir>/quick/edit.mp4 --from 40 --to 52
   --preset veryfast` (everything is planned on the whole clip, so a preview's frames are the full render's frames).
   Full: `python "$CC/render.py" <clip> <dir>/plan.json <dir>/edit.mp4 --phone` (slow: about 17 s of render per second of
   video with full-resolution footage, so a 65 s clip takes about 20 minutes; run it in the background). Without plan `hr`: `--hr <footage.mp4> [--hr-map cutmap.json]`. Writes `edit.mp4`, `edit.srt`, `edit_phone.mp4`
   (under 28 MiB), `edit.pk.json` and `edit.sfx-events.json`. Read the JSON: `max_upscale` above about 1.15 means the camera's zoom is
   enlarging the picture (give it the full-resolution footage; it doesn't count a `--crop` of a RAW, which ffmpeg enlarges
   before); `warnings` should be empty.
9. **Look.** `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/preview.py" <dir>/edit.mp4 <dir>/preview.jpg --at <t1>,<t2>,...`
   at each big moment (entry, +0.1 s, +0.3 s, landed), two cards with their key bars, a cut, the flash and the pull-back.
   Check: big type lands on its word, never on the face, readable on the picture, cards never doubled with big type, every key
   bar shows on its word, no zoom jump at a cut or a punch, no black borders, no clipped text, Traditional characters drawn.
10. **Sound.** The sfx skill: start from `edit.sfx-events.json` (a draft of every big move, camera punch-in and pull-back), keep
    the true punchlines (a sermon stays reverent: 1-3 hits a minute), run its `place.py`.
11. **Deliver** as the other styles do: `notes.md` (title, punchline, the big moments and why, fonts, the transcript), Agents HQ
    `out/<name>/` with `edit.mp4`, `captions.srt`, `clean.mp4` (`render.py ... --no-text`), `followups.json`; send `edit_phone.mp4`.

## Good to know
- Fonts (closest installed; the reference's own fonts are unknown): cards 优设标题黑 (Latin: Alibaba Sans Heavy Italic), hook /
  labels Alibaba PuHuiTi Heavy + Arial Black, punch 庞门正道标题体 (whole phrase falls back to PuHuiTi Heavy if one character is
  missing), numbers and English write-on Bebas Neue at 86-90 % width. Traditional characters fall back to 思源黑体 Heavy.
- Motion numbers are in `GUIDE.md` (v1 measured from the reference, v2 from the approved 1114 edit).
- Pairs with **sermon-moments** (text behind the head etc.) only through poster-kinetic; in caption-card, keep to these kinds.
