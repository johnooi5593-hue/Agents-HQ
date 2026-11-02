---
name: gold-stack
description: Gold Stack (金色叠字), the owner's default style for talk and sermon highlights (approved 2026-11-01). Caption words build as a stepped staircase of heavy white Noto Sans SC Black, landing as they are spoken, with one brand-gold #FBC238 key word or number per block. Designed moves, each with its own sound effect: title rise, giant slam on the main point, number grow, write-on number, 3D spin, gold marker swipe on a question, flash frame, gold light-leak burn into a chapter vignette, and a closing push. A slight camera move runs on every shot. Use for every talk / sermon edit unless the owner names another style; also when the owner says Gold Stack, 金色叠字 or "my new style". Plan first, then render; music, sound effects and an earshot listening check follow.
---

# Gold Stack: words that build, one gold, a camera that breathes

The brand sheet is the law: `C:\Users\John Ooi\Documents\Style Guides\gold-stack\guideline.pdf` (read pages 3-10 once).
The renderer reproduces its moves frame for frame, so your job is choosing **which word is gold** and **which line earns a
move**, and keeping the words exact. Never change the speaker's words, scripture, numbers, negations or conditions.

Scripts: `D:/Agents HQ/.claude/skills/gold-stack/scripts/` (call it `$GS`). It reuses caption-card and poster-kinetic next to
it (speech-to-text, compositing, preview). One command per Bash call, quoted absolute paths. Every script prints one JSON
line. Never upload, post or delete anything.

## Steps
1. **Source.** A clean, caption-free cut. Sermons: the speaker crop only, never the slides (brand rule); interpreted
   sermons: only the speaker's own voice, every interpreter phrase cut (Lessons). Cut crew slates and crew lines.
   **Footage mix** (sermon highlights cut from a RAW livestream, owner 2026-11-02): show the RAW in only 2-3 scenes; the rest is the same service's B-roll, mostly the speaker from other angles and about a third without the speaker (audience, worship team, raised hands, the hall and stage), more of those on the reflective lines. The speaker's audio, timing and captions run on unchanged under the B-roll; captions stay off faces.
   **30 fps first**: `ffmpeg -i <clip> -vf fps=30 -c:v libx264 -crf 14 -c:a aac <dir>/src30.mp4` (a 25 fps source puts
   each framing switch one frame off its cut).
   **Fillers and pauses out** (every edit): `python "D:/Agents HQ/.claude/skills/yellow-serif/scripts/tighten.py" <clip> <dir>/tight.mp4 [--map <dir>/cutmap.json]`
   (env `YS_LANG=zh`); use `tight.mp4` and `tight.cutmap.json` from here on. 45 s maximum.
2. **Plan.** `python "$GS/plan.py" <dir>/tight.mp4 <dir>/plan.json` (env `YS_LANG=zh`), or reuse another plan's lines with
   `--from-plan`. Fix clearly misheard words in `text` and `words` and say so in `note`. Write numbers as digits (三次 → 3次)
   and percentages with % (never 巴仙).
3. **Measure the face.** Look at 3 frames per shot (start, middle, end). Set plan `camera.face` = [x, y] of the face
   (0..1) and `camera.chin` = the chin's y in px on the 1080×1920 frame (the lowest chin you see). Captions stay 40 px
   below the chin, even with the camera's tight framing (the renderer allows for it).
4. **Choose** (each line starts as a plain staircase, words landing as spoken):
   - **Negative key word** (only when the owner asks for it, see the negative-key skill): plan `key_style: "negative"` draws every gold item (the `key`,
     the title key, slam `b`, the number and write-on digits, a gold spin word, the word behind) as a photo negative of
     the picture behind it over a soft dark shadow (45 %, blur 10 px), with no gold glow; every other word stays white.
     The gold accents (title bar, question swipe, pen trail, flash frame, light leak) stay gold. Leave `key_style` out
     (or `"gold"`) for the gold look.
   - `key`: the line's one gold word or phrase, an exact part of the line, with its negation (没有定他的罪, never 定他的罪
     alone). Most lines get one.
   - `move` on the lines that earn it:
     - `title` (line 1 only): the opening line rises over the chest; its `key` is gold.
     - `slam` (once; the main point, at least 3 s in): `a` = the lead phrase, `b` = the gold phrase; add `flash: true` for one gold frame after it.
     - `number` (a number that matters, never money): `number` = the digits, optional `unit` = the word after (次, 天).
     - `writeon` (a Bible reference, date or count): `number` = the digits.
     - `spin` (at most once; a 2-3 character verb that turns the story): `word`.
     - `question` (a question the speaker asks): the whole line on one row with a gold marker swipe.
     - `behind` (at most 2; owner 2026-11-01): `word` = 2-4 characters, shown huge **behind the speaker's head**, cut out
       with the person matte; the rest of the line builds under the chin. Gold by default (`behind_colour: "white"`), and
       it is the line's gold item. Two characters spread apart so the head sits between them, big (owner 2026-11-02 "more bigger": at least 300 px each, sitting high so the head covers only their lower inner part; a character shrinks only while less than 35 % of it would show), inside the 86/994 margins. Needs `--matte` (step 6).
       Use it for the word the line turns on (悔改, 恩典, 爱); the face must be in the shot for the whole line.
   - `transition: "leak"` on the first line of a new section (1-2 per video): a gold light-leak burn, then the chapter
     vignette and a tracking close on that line's first word (its spread is capped to stay inside the margins). `track: true` = a tracking close at a hard section cut.
   - `exit: "pulse"` on the last block before a cut to a new idea.
   - Plan `close: true` (the default): the closing push holds the last line to the end.
   Pacing: a designed move every 3-5 s, never two within 2 s (M4+flash, leak+track and close+flash count as one), at
   least one every 10 s (brand rule).
5. **Check.** `python "$GS/plan.py" --check <dir>/plan.json` (fix every error, think about every warning), then
   `python "$GS/plan.py" --md <dir>/plan.json` for the planning page. Stop here if the owner wants to see the plan first.
6. **Render.** With a `behind` move, make the speaker cutout first:
   `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/matte.py" <dir>/tight.mp4 <dir>/matte.mp4` (same framing options as render).
   `python "$GS/render.py" <dir>/tight.mp4 <dir>/plan.json <dir>/edit.mp4 --map <dir>/tight.cutmap.json [--matte <dir>/matte.mp4] --phone`
   (`--to 15 --preset veryfast` for a quick look; `--no-text` for clean.mp4). About 4× real time on this PC.
   Writes `edit.mp4`, `edit.srt`, `edit.pk.json`, `edit.sfx-events.json`, `edit_phone.mp4`. Read its `warnings`.
7. **Look.** `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/preview.py" <dir>/edit.mp4 <dir>/preview.jpg --at ...`
   at each move (its start, +0.1 s, +0.4 s) and a few plain lines. Check: no text on the face, nothing in the right-hand
   button area (x > 950, y 1000-1700) or the bottom 300 px, one gold item per block, every character drawn, the camera
   never showing a black edge.
8. **Music, sound, listen** (every edit):
   - Music: sfx skill step 0, `music.py <dir>/edit.mp4 <owner's track> <dir>/edit-music.mp4`, at the level the channel's
     brand rules set. Pong+Gospel: the approved CC0 piano (e.g. Piano_Echo by TreyVZ) with `--room` at the default level
     (12 dB under the voice, 5 in the gaps: the Sandy blend, owner 2026-11-02; 21 and 15 were too quiet on a phone). earshot must hear it as music in every section.
   - Sound effects: `place.py <dir>/edit-music.mp4 <dir>/edit.sfx-events.json <dir>/edit-sfx.mp4`. The events come from
     the plan: one sound per designed move, loudest on its frame (sheet page 10). A sound the library lacks: find it on
     Openverse with the sfx skill's `search.py` and listen to the candidates with earshot `describe` before adding one.
   - **Listen with earshot** before anyone sees it:
     `cd "D:/Agents HQ/tools/ext/earshot"` then `.venv/Scripts/python -m earshot timeline "<dir>/edit-sfx.mp4" --cues "<dir>/edit.sfx-events.json"`.
     Every cue needs a hit within 100 ms (a "NO HIT" cue is masked or cut off: move or raise it), loudness -14 LUFS and
     true peak at or under -1 dBTP, no filler left between words. Quote its numbers in notes.md.
9. **Brand check, then deliver** as the other styles: brand-checker review, `notes.md`, `out/<name>/` with `edit.mp4`
   (= edit-sfx.mp4), `captions.srt`, `clean.mp4`; then Social's posting pass. Nothing is published.

## The camera move (owner, 2026-11-01: "more camera movement")
On by default (`camera.on`, `camera.strength` 1.0): the picture sits at 107 % and keeps moving: a drift of ±18 px over
7.3 s and ±14 px over 9.1 s, a sway of ±0.6° over 11.7 s, a breathing zoom of 1.5 % over 8 s, and a 4 % push within each
framing. With `--map`, it switches between a wide and a 1.15× tight framing (around `camera.face`) at pause cuts, on the
exact frame the picture cuts, each framing on screen for at least 1.2 s. Punches: 6 % on the slam, 3 % on a number or a
word behind, 2.5 % on each gold key word, each settling in 0.2 s; the closing push adds 7 % over the last 1.5 s. It never
shows a black edge (checked on every frame of the test). `camera.strength: 0.4` gives the earlier slight move;
`camera.alternate: false` keeps one framing.

## Glow (owner, 2026-11-01: "more glow on the words")
Gold words (a negative key word has only its soft dark shadow): a wide gold bloom (40 %, blur 0.40 × size) and a strong close glow (75 %, blur 0.15 × size), then a burst as
they land (up to full at frame 6, settling by frame 16) and a gentle pulse while held (0.9 Hz). White words: a soft warm
halo #FFF0CD (22 % wide, 30 % close). The dark stroke and shadow stay, so the text still reads on bright pictures.

## Good to know
- Type: Noto Sans SC Black (SIL OFL, `C:\Windows\Fonts\NotoSansSC-VF.ttf`) for everything; it has 祂 and every church
  character. Sizes S 72 / M 120 / L 180 / N 300 px; white #FFFFFF → #E2E5EA with a 3 px #08090B stroke at 60 % and a 70 %
  shadow; gold #FBC238 with a 45 % gold glow.
- Sound names used (sfx library): title `impact` (-6 dB), slam `impact`, number unit `pop`, write-on `swish_soft`, spin
  `whoosh_fast`, question `pop`, flash `impact`, leak `whoosh_zoom`, pulse `swish_soft`, tracking close `pop`, closing push
  `chime_soft` (loudest when the takeaway lands, 1 s before the end, so it rings out; on the last frame earshot heard no hit).
  An Openverse riser was tried for the close: earshot read it as "dark and tense", so the soft chime stays.
- Test edit and every move checked frame by frame: `D:\Agents HQ\work\creative\gold-stack-test\` (`v1/` the rule-following
  test, `moves/` every other move).
