---
name: poster-kinetic
description: Poster Kinetic (大字海报动态) style for sermon highlights and other vertical clips - one giant hero word per point in heavy Chinese sans with a short 3D extrusion, colour by meaning, whip / drop / zoom / vertical-stack entrances, readable word-by-word captions for every other line, scripture cards that fly in, an opening title, flash and whip transitions, a slow punch-in, and optional text behind the speaker. Built from the owner-approved Semenyih shoplot reel guide. Use when the owner asks for this style, "大字海报", "poster style", "the Semenyih / shoplot style", or wants a sermon highlight to feel bolder than Yellow Serif. Plan first (企划页), then render. For the cover, also use the pixel skill.
---

# Poster Kinetic: plan first, then render

Read `GUIDE.md` in this folder once (the style in numbers, the sermon palette, do/don't). In short: one point per screen,
a giant hero word that lands on the word as it is spoken, every other line a clean caption, colour by meaning, nothing
over the face or below y 1400. Never change the meaning: original words, numbers, negations and conditions stay.

Scripts live in `D:/Agents HQ/.claude/skills/poster-kinetic/scripts/` (call it `$PK`); they reuse the yellow-serif and
reel skills next to it for speech-to-text and cutting. Run each command on its own (no `&&`), with quoted absolute paths,
from a short working folder (Windows cannot launch ffmpeg from very long paths). Every script prints one JSON line.
Never upload, post or delete anything.

## Steps

1. **Fonts.** `python "$PK/pfonts.py"`. It lists the font for each role and the per-character fallbacks (祂, 袮 and
   Traditional characters come from 思源黑体 Heavy). If a role is missing, say so in the report.
2. **Source.**
   - An edit that already exists (a clean, caption-free sermon reel, e.g. `out/<name>/clean.mp4`): use it as is.
   - A long RAW livestream: pick the topic(s) as in the yellow-serif skill (transcribe the whole talk, choose 45-60 s of
     complete thought, the strongest lines), then cut with
     `python "D:/Agents HQ/.claude/skills/yellow-serif/scripts/cut_topics.py" <raw> <dir>/topics.json <dir>`.
     The livestream frame has the stage camera in the right half of the strip y 297-837; render with
     `--crop 960:297:960:540` (and `--focus` to follow the speaker). The owner's rule: no slides from the RAW.
3. **Plan.** `python "$PK/plan.py" <clip> <dir>/plan.json [--map <dir>/cutmap.json]` (env `YS_LANG=zh`; Cantonese
   sermons too). It runs on the CPU with the local large-v3-turbo model. Read the transcript it prints; fix clearly
   misheard words (names, 甘迪 -> 甘地) in that line's `text` and the same word in `words`, and say so in `note`.
4. **Look at the picture** before choosing zones: `python "$PK/preview.py" <clip> <dir>/source.jpg --at 3,9,15,...`
   (the times you are thinking of). Note where the face is, where slides or graphics sit, and dark or bright areas.
5. **Edit `<dir>/plan.json`.** Every line starts as `"mode": "caption"`. Choose:
   - **Heroes** (`mode` `poster`, or `stack` for 2-4 Chinese characters): the line that carries the point, about one
     every 4-8 s, at most 45% of lines, at least 2 s apart. `keyword` = the hero, an exact part of the line, 2-5
     characters; the rest of the line becomes the white lead-in / tail (keep lead + tail under 16 characters; use
     `plan.py --split <plan> <id> <first part>` or `--merge <plan> <id> <id2>` to reshape lines). Keep negations inside
     the hero (`不符合`, never `符合`).
   - **motion** for posters: `zoom` (the punchline, an opening word), `whip` (most key words; `from` left/right
     alternates by itself, `top` for a drop from above), `drop` (a contrast or short title, letter by letter).
   - **color** by meaning (GUIDE §3): gold grace/hope (default), cream scripture, peach people/love, lime life/action,
     ice Holy Spirit/peace/invitation, red sin/warning/contrast (max 2), navy numbers on bright pictures, blue welcome.
     Optional `slant: true` (优设标题黑 / italic Latin), `fill` `gradient` + `color2`, or `metal`.
   - **zone** `top` / `middle` / `low` (default low, over the body) so the hero never covers the face or a graphic.
   - Captions: `keywords` (0-2, exact parts) are tinted with the line's `color` at 1.08x.
   - `transition`: `flash` or `whip` on the first line of a new section (2-4 per clip, 6 s apart).
   - **overlays** (list at the top level):
     `{"kind": "title", "start": 0.3, "end": 2.8, "main": "<sermon title>", "sub": "<preacher>", "zone": "top"}` - only
     with the real title and name (check spelling);
     `{"kind": "card", "start": s, "end": e, "text": "<words actually read>", "ref": "<book ch:v>", "zone": "low"}` - a
     verse the preacher reads; the text must be exactly what was said (the check rejects anything else), the reference
     only if the preacher names it or the slide shows it. Captions under the card are hidden.
   - `behind: true` puts a hero behind the speaker, only with a matte (step 8).
6. **Check and show.** `python "$PK/plan.py" --check <dir>/plan.json` (fix every error, weigh every warning), then
   `python "$PK/plan.py" --md <dir>/plan.json` writes the planning page `plan.md`. If the owner asked to see the plan
   first, stop here and send it.
7. **Render.** Quick look first: `python "$PK/render.py" <clip> <dir>/plan.json <dir>/quick/edit.mp4 --to 15 --preset veryfast`.
   Then the full clip: `python "$PK/render.py" <clip> <dir>/plan.json <dir>/edit.mp4 --phone` (add `--crop`, `--focus`,
   `--frame blur` for RAW sources; `--no-punch` if the source already moves a lot). About 1.5x real time. It writes
   `edit.mp4`, `edit.srt`, `edit.pk.json`, `plan.json` and `edit_phone.mp4` (under 28 MiB, for SendUserFile). Read its
   `warnings`: contrast swaps, short holds, lines that did not fit, hidden heroes.
8. **Optional: text behind the speaker.** `python "$PK/matte.py" <clip> <dir>/matte.mp4` (same `--crop/--focus/--frame`),
   then render with `--matte <dir>/matte.mp4` and `"behind": true` on the poster / stack lines (zone `top` or
   `middle`, where the head is). It uses the local Robust Video Matting model (D:/AI OFFICE/tools/models/rvm, CPU,
   about 9 frames per second). Use it on speaker shots only; crowd B-roll mattes are messy.
9. **Look at it.** `python "$PK/preview.py" <dir>/edit.mp4 <dir>/preview.jpg` and Read it (16 frames at hero entries
   and landings, stacks, cards, titles, transitions). Check: hero readable and never on the face, colours by meaning
   and readable on the picture, captions clear of graphics, nothing below y 1400, text clear after every effect. Zoom in
   on a moment with `--at 12.3,14.6`. Fix the plan and render again until it is right.
10. **Cover.** `python "$PK/render.py" <clip> <dir>/plan.json <dir>/clean.mp4 --no-text`, then the pixel skill on
    `clean.mp4`; cover text in this style: one hero word in its meaning colour, PuHuiTi Heavy with the dark extrusion.
11. **Deliver.** Write `<dir>/notes.md`: title (60 characters max), punchline, source range, length, fonts used, heroes
    and why, colours, overlays, the transcript and the warnings you accepted. In Agents HQ register the folder as
    `out/<name>/` with `edit.mp4`, `captions.srt` (copy of `edit.srt`), `clean.mp4`, `notes.md` and a `followups.json`
    like the existing `out/revhiew-*` folders (cover brief: this style, not Yellow Serif). Send `edit_phone.mp4` with
    SendUserFile when the owner follows from the phone. Report in three short lines: the folder, the length, the title.

## Optional moments
For a sermon highlight, read the **sermon-moments** skill after step 6: it adds text behind the head, active-word captions, a name label, a question bar, a grade wipe, a prayer grade, a wall of moments, a freeze, zoom-through and jump-cut framing to this plan.json, only on the lines whose words earn them (`moments`, overlays `name` / `question`, `caption_style`, transitions `whip` / `zoom_through`).

## Good to know
- Fonts are found in the Windows user font folder and C:\Windows\Fonts; nothing is downloaded. Alibaba Sans (Latin
  italic) has its own licence: check before paid commercial use; Montserrat Black Italic (OFL) is the fallback.
- Speech-to-text runs on the CPU (this PC has no CUDA runtime); `PK_CUDA=1` tries the GPU, `YS_WHISPER_MODEL` picks a model.
- The renderer lays out at 1080x1920, 30 fps; audio is copied from the source.
- Captions are machine transcribed: check names and scripture words by ear before posting.
