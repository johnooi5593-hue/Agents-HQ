---
name: kids-review
description: Kids Review (儿童回顾), the owner-approved recipe for a cute children / kids' event review video, built on the 1107 Children review ("Niceee!", v4 with the neutral grade). It ALWAYS makes both 9:16 (1080x1920) and 16:9 (1920x1080). Event footage becomes a 2-second-shot montage (group photos whole over a blurred fill), host voice 3B talks the viewer through it in a chatty Malaysian-style thread, readable names are blurred, a neutral bright grade, Caption Card cute-edition captions (puffy pink sticker cards, hopping characters, candy key words, rainbow big type, speech bubbles), QQ emoji stickers and kids' motion graphics on every cut with bursts on the key moments (bubbles, twinkles, trails, candy wipes, arrows, crayon frames, balloons, confetti), Blue Sky ukulele music, real CC0 pops, a clean ending. Use when the owner asks for a children review, kids review, 儿童回顾, 儿童主日学回顾, an event review with kids, "edit the review like 1107", or /kids-review.
argument-hint: "<event footage folder> [title or date]"
---

# Kids Review: a happy host, pink sticker cards, something cute on every cut

The look in one line (numbers in `GUIDE.md`): **one chatty host line per 2-second shot, every phrase a puffy pink card whose
characters hop in, a small sticker on every cut and a bigger burst on each moment that matters, a bright neutral picture,
ukulele under it all, and never a face covered or a child's name readable.** The look is built into the scripts; your job is
choosing the shots, writing the host's lines, finding every name, and placing the stickers off the faces in BOTH sizes.

Scripts: `D:/Agents HQ/.claude/skills/kids-review/scripts/` (call it `$KR`). Templates: `$KR/../templates/`. It uses the
caption-card skill's renderer (patched at run time), the sfx skill (music.py, place.py), pixel (covers) and relay (post.md).
One command per Bash call, quoted absolute paths, no `&&`. Every script prints its usage when run without arguments and one
JSON line when done. Never upload, post or delete anything; the source footage on D: is read-only.

Reference (read once): `D:/Agents HQ/work/creative/1107-children/` (every input below for a real video) and the delivered
`out/1107-children-review-v4/` + `out/1107-children-review-16x9-v4/` (v3 until v4 exists: `out/1107-children-review-v3/`,
`out/1107-children-review-16x9-v3/`); their notes.md list every decision and brand-check fix. Every template is the 1107
worked example: replace its rows, keep its shape.

## Before you start
- Brain: "Company", "Brand rules" (children reviews: both sizes, stickers never on a face, never a readable child's name;
  host voice 3B; colour grade 2026-11-08: neutral, never orange; clean ending; music blend; sound effects), "Lessons".
  For another channel, its "<name> · Company" and "<name> · Brand rules" (CLAUDE.md, Channels).
- Names: `W` = the work folder `D:/Agents HQ/work/creative/<MMDD>-<event>/`, `SRC` = the footage folder,
  `<name>` = `<MMDD>-<event>-review`. Deliver to `out/<name>/` (9:16) and `out/<name>-16x9/` (16:9).
- Board: `node "D:/Agents HQ/hq/tasks.js" progress <id> <pct> "<STAGE> · <what>"` at every step, real numbers only:
  **CUT** 5-20 (footage, shots, montage) · **EDIT** 20-45 (voice, names, grade, plan, renderers, sticker plan) ·
  **RENDER** 45-85 (captions, stickers) · **SOUND** 85-92 (music, effects, earshot) · **CHECK** 92-98 (brand check, fixes) ·
  **DONE** 99 (delivered, waiting for the owner's OK).
- Owner says "do it" / "OK": no questions; decide, write the decision in notes.md (CLAUDE.md rule).

## Who runs what (in parallel)
1. **Shared (one clip-editor, or the coordinator):** steps 1-3 and 6 (shots, both montages, the voice, the plan), plus
   `make_renderers.py` and the first sticker plan. These are the same for both sizes.
2. **Then two clip-editors in the same message:** one for **9:16**, one for **16:9**, each with its own steps 4, 5, 7, 8
   (its own blurs, grade, caption render, sticker check and render), 9 and its covers. Both read the same plan.json,
   cute.json and build_stickers.py. In build_stickers.py the 9:16 editor changes only the 9:16 values (p9, FACES9,
   CARD9...), the 16:9 editor only the 16:9 values (p16, FACES16, CARD16), each re-reading the file right before an edit.
   Give each brief the earshot line from MEMORY (`python -c "import sys,runpy; ..."`).
3. **If background runs keep stopping**, say so once and render both sizes yourself (start the two long renders as two
   background Bash runs at the same time).
4. **brand-checker** on both videos and covers (checklist below), fixes, check again; then **social-media-manager** (relay)
   for post.md; then the report.

## Steps
1. **Footage (CUT).**
   - `python "$KR/probe.py" "<SRC>" "<W>"` → `clips.json` + `sheet-N.jpg` (5 frames per clip). Look at every sheet.
   - Copy `templates/shots.json` to `<W>/shots.json` and choose ~25 shots that tell the day in order: arrival / the room,
     the story or lesson, snacks, the craft step by step, close-ups of small hands, a proud child with the result, adults
     helping, the finished craft, 2-3 posed group photos (`"fit": true`), and a wave goodbye. 2 s each (`d` 1.8-3.2 for the
     hook and group photos), `t` = where the action is, `cx`/`cy` = the subject for the 9:16 crop. Open on the most
     surprising picture (1107: paper yurts on two boys' heads), not on the room.
   - After the montage: `python "$KR/shotsheet.py" "<W>/framed.mp4" "<W>/shots.json" "<W>/shotsheet.jpg"` and check every
     crop (no face cut through, the subject in frame, group photos whole). Fix shots.json and build again.
2. **Montage (CUT).** Both sizes from the same shots (the two can run at the same time):
   - `python "$KR/build.py" "<SRC>" "<W>/shots.json" "<W>/framed.mp4" --size 9x16`
   - `python "$KR/build.py" "<SRC>" "<W>/shots.json" "<W>/framed16.mp4" --size 16x9` (`--over <W>/shots16.json` only
     where a subject sits too far off the landscape frame)
3. **Host voice 3B (EDIT).** Copy `templates/lines.json` to `<W>/lines.json` and write ONE line per shot: start 0.15 s after
   its cut, said TO the viewer, chatty Malaysian-style with particles (啦 咯 哦 咧 耶), only what is on screen, never a
   name, never a claim the picture doesn't show (1107 brand check: 听故事 only over a story, 零件 only over the pieces).
   Fill `seg` (the words, space-separated) and the plan fields (`key`, the 5 big moments with `kind`, see step 6).
   - `python "$KR/vo.py" "<W>/framed.mp4" "<W>/lines.json" "<W>/vo" "<W>/vo-video.mp4"` (edge-tts needs the internet; a
     re-run speaks only the lines that changed). Fix every warning (a line running into the next, or into the last 0.4 s).
   - ElevenLabs voice (only when the owner asks for it or the brain names an ElevenLabs voice): add `--eleven <voice id>`
     (ids: `python tools/voice/eleven.py voices`; the owner's key is on the Accounts screen, never read `.hq-elevenlabs.json`).
     It uses the owner's credits: speak once, then re-run only changed lines. Its real character times go into lines.json
     and makeplan.py uses them for the cards. No key connected = the whole video falls back to 3B (say so in notes.md).
     Tell the owner the credits it used and the credits left, from vo.py's "credits" output (owner, 2026-11-11).
   - 16:9: `ffmpeg -y -i "<W>/framed16.mp4" -i "<W>/vo/vo.wav" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k "<W>/vo-video16.mp4"`
4. **Name blurs (EDIT), per size.** Look at EVERY shot at native resolution for readable names: lanyard badges, name
   stickers on water bottles and bags, door charts and lists, whiteboards, table name cards (1107 had 1 in 9:16 and 5 in
   16:9). Machine check first, per size (about 10 min each, both at once):
   `python "D:/Agents HQ/tools/vision/textscan.py" "<W>/vo-video.mp4" "<W>/text916.json" --sheet "<W>/check/text916.jpg"`
   (and `vo-video16.mp4` → `text16.json` / `text16.jpg`). Look at every red (name-like) and pink (label) cell on the sheet;
   turn the real ones into blur boxes with
   `python "D:/Agents HQ/tools/vision/blur_hits.py" "<W>/text916.json" "<W>/blur916.json" --video "<W>/vo-video.mp4" --ids <ids>`
   (merge with any hand-drawn boxes). Then the eye check: `python "$KR/sheet.py" "<W>/vo-video16.mp4" "<W>/check/names16" --shots "<W>/shots.json"`, then
   `--crop x,y,w,h` zooms on anything that might be text. Write the boxes (output pixels, moving keys if the camera moves,
   stopped at the next cut) into `<W>/blur916.json` / `<W>/blur16.json` (templates), then
   - `python "$KR/blur.py" "<W>/vo-video.mp4" "<W>/blur916.json" "<W>/vo-video-blur.mp4"`
   - `python "$KR/blur.py" "<W>/vo-video16.mp4" "<W>/blur16.json" "<W>/vo-video16-blur.mp4"`
   Crop each box on the result: nothing in it may be readable. Re-scan the blurred file with textscan.py: no name-like or
   label hit may remain on a blurred spot; the same thing is blurred in BOTH sizes (1107: the door charts were blurred in 16:9
   only, found later by the scan).
5. **Grade (EDIT), per size.** Neutral and bright (owner 2026-11-08: white walls white, skin natural, never orange):
   - `python "$KR/grade.py" "<W>/vo-video-blur.mp4" "<W>/vo-video-graded.mp4" --shots "<W>/shots.json"`
   - `python "$KR/grade.py" "<W>/vo-video16-blur.mp4" "<W>/vo-video16-graded.mp4" --shots "<W>/shots.json"`
   - Check: `python "$KR/grade.py" "<W>/vo-video-blur.mp4" "<W>/check/grade-916.jpg" --sheet --shots "<W>/shots.json"`.
     A shot that still looks hot or orange gets a row in `<W>/grade-fix.json` (template) and `--fix "<W>/grade-fix.json"`.
6. **Captions plan (EDIT), shared.**
   - `python "$KR/makeplan.py" "<W>/lines.json" "<W>/vo/lines.json" "<W>/vo-video.mp4" "<W>/plan.json"`
   - `python "$KR/regroup_words.py" "<W>/plan.json" --script "<W>/lines.json"` (whole words; jieba fills a missing `seg`;
     read its words list).
   - The big moments (5 in ~50 s, at least 6 s apart): `hook` on line 1 (a question, 3 rows, `color` #FF7AC8), `writeon`
     on the craft's name (`phrase`, `transition: flash`, `accent: halo`), `punch` on a V sign or cheer (`accent: rings`),
     `writeon` on the wow (好漂亮), `punch` on the payoff (完成啦, `color: yellow`); `transition: flash` on the group photo
     line; `leak: true` on 2 lines; `punch_in: 1.12` on one. Every other line is a card with one `key`.
   - Copy `templates/cute.json` (speech bubbles on ~3 lines, per-size card heights) and `templates/layout16.json` (where the
     16:9 big type sits: off the faces) into `<W>/`.
   - Check: `python "D:/Agents HQ/.claude/skills/caption-card/scripts/plan.py" --check "<W>/plan.json"` (fix every error;
     the render prints its own warnings too).
7. **Cute caption render (RENDER), per size.**
   - Once per video (and again whenever the caption-card skill changes): `python "$KR/make_renderers.py" "<W>"` → `<W>/cc916/`
     and `<W>/cc16/`, built from the caption-card skill's current render.py. If it stops with "the patch no longer fits",
     the caption-card skill changed: update the patch lists in make_renderers.py (never hand-edit the copies).
   - `python "<W>/cc916/render.py" "<W>/vo-video-graded.mp4" "<W>/plan.json" "<W>/render916/edit.mp4" --phone`
   - `python "<W>/cc16/render.py" "<W>/vo-video16-graded.mp4" "<W>/plan.json" "<W>/render16/edit.mp4" --phone`
     (reads layout16.json beside the plan). About 12-15 s of render per second of video; `--from 0 --to 4` for a quick look.
   - Each writes `edit.srt`, `edit.pk.json` and `edit.sfx-events.json` beside the video. Look at frames of every big moment
     and of every card that sits near a face (`sheet.py --every 0.5`).
8. **Stickers and motion graphics (RENDER).**
   - <!-- t202 faces --> Faces first, per size, on the clean blurred source (both can run at the same time; 25-70 s each):
     `python "D:/Agents HQ/tools/vision/faces.py" "<W>/vo-video-blur.mp4" "<W>/faces916.json" --shots "<W>/shots.json" --sheet "<W>/check/faces916.jpg"`
     `python "D:/Agents HQ/tools/vision/faces.py" "<W>/vo-video16-blur.mp4" "<W>/faces16.json" --shots "<W>/shots.json" --sheet "<W>/check/faces16.jpg"`
     Read both sheets (red = avoid box). build_stickers.py loads every `faces*.json` beside shots.json; type a FACES9 /
     FACES16 row only for a face the sheet shows without a red box (masks, backs of heads, faces cut by the edge). <!-- /t202 -->
   - Copy `templates/build_stickers.py` to `<W>/build_stickers.py` and rewrite its tables for this video (sections 1-4:
     cuts, bursts per key moment, bubbles, twinkles, trails, wipes, underlines, arrows, frames, balloons, the caption /
     big-type and face avoid boxes for BOTH aspects). Then `python "<W>/build_stickers.py"`.
   - `python "$KR/stickers.py" plan "<W>/stickers.json" --faces "<W>/faces916.json" --faces "<W>/faces16.json"`: fix every
     error; look at every "touches" warning on frames (a "face (auto ...)" warning is a sticker on a detected face). <!-- t202 -->
     Pass the same `--faces` to `stickers.py render` below.
   - `python "$KR/stickers.py" sheet "<W>/render916/edit.mp4" "<W>/check/boxes916.jpg" --every 0.5 --boxes "<W>/stickers.json"`
     (and on render16) to place faces and stickers on the clean render.
   - `python "$KR/stickers.py" render "<W>/render916/edit.mp4" "<W>/stickers.json" "<W>/render916/edit-stk.mp4" --sfx-events "<W>/render916/edit.sfx-events.json" "<W>/render916/edit-stk.sfx-events.json" --task <id> --pct 70:85`
     (the same with render16). `--from/--to` for a quick part; `stickers.py sfx ...` when only sounds changed.
   - Check: `python "$KR/stickers.py" sheet "<W>/render916/edit-stk.mp4" "<W>/check/stk916.jpg" --every 0.5` and read every
     sheet: no sticker, bubble or confetti on a face, a card or the big type; every bubble word readable.
9. **Sound (SOUND), per size.**
   - `python "D:/Agents HQ/.claude/skills/sfx/scripts/music.py" "<W>/render916/edit-stk.mp4" "D:/Agents HQ/.claude/skills/kids-review/assets/blue-sky.mp3" "<W>/render916/edit-stk-music.mp4" --room`
   - `python "D:/Agents HQ/.claude/skills/sfx/scripts/place.py" "<W>/render916/edit-stk-music.mp4" "<W>/render916/edit-stk.sfx-events.json" "<W>/render916/edit-stk-sfx.mp4"` (0 misaligned)
   - earshot timeline with the cues (the MEMORY `python -c "import sys,runpy; ..."` form): -14 LUFS, -1.5 dBTP, music heard
     under the voice, the cues hit; a soft cue the voice masks gets a louder `db` in build_stickers.py (LOUDER, WIPE_DB).
   - Clean ending: the last word ends at least 0.4 s before the end; everything fades over the last 0.8 s.
10. **Brand check (CHECK).** brand-checker on both edits and the covers, with this checklist (the 1107 findings):
    - [ ] no sticker, bubble, trail, confetti or card on a face in ANY frame (check every 0.1 s around each burst)
    - [ ] bubble text reads (no blobbed 酷 / 害; solid ink over a white outline)
    - [ ] no short word that never lands (every card chunk >= 0.4 s, every character landed before its card goes)
    - [ ] the hook is whole in 16:9 (not cut off at the bottom through its bounce and exit); nothing clipped at an edge
    - [ ] skin natural, not orange or hot from stacked grades (build eq + grade.py + the caption grade arc); white walls white
    - [ ] no readable badge, lanyard, bottle name sticker, door chart or whiteboard name, in both sizes
    - [ ] every line matches its picture; no child's name said or shown
    - [ ] music audible under the voice, sticker pops soft, clean ending, -14 LUFS
    - [ ] both sizes delivered, the same words in both (captions.srt identical)
    - [ ] textscan on both delivered edits: 0 name-like / label hits on a person's name (text916.jpg, text16.jpg in check/)
    - [ ] `tools/vision/gradecheck.py --profile kids --faces` PASS on both delivered edits (gradecheck.json/.jpg beside notes.md)
11. **Deliver (DONE).** For each size: `cp` the `edit-stk-sfx.mp4` to `out/<name>/edit.mp4` (16:9: `out/<name>-16x9/edit.mp4`),
    `render916/edit.srt` to `captions.srt`, write `channel.txt` (the channel key, `main` for the main channel) and `notes.md`
    (request, title, hook, length and why, voice + AI label, music + licence, sticker list, blurs, decisions, the rebuild
    commands). Covers (pixel), from the clean graded source, text off every face:
    - 9:16: `python "D:/Agents HQ/.claude/skills/pixel/scripts/thumbnail.py" "<W>/vo-video-graded.mp4" "out/<name>/cover.jpg" --text "<title>" --at <s> --pos bottom`
    - 3:4: a 1080x1440 crop of the same frame (`ffmpeg -y -ss <s> -i "<W>/vo-video-graded.mp4" -t 1 -vf crop=1080:1440:0:<y> "<W>/cover-src-34.mp4"`),
      then thumbnail.py on it → `cover-ig.jpg`
    - 16:9: thumbnail.py on `<W>/vo-video16-graded.mp4` → `out/<name>-16x9/cover16x9.jpg` (one row of text)
    Then social-media-manager (relay) writes post.md in both folders (3 title + caption + hashtag sets, the AI-voice label,
    YouTube uses cover16x9.jpg for the 16:9 upload). Report, ending "Nothing is published. Reply OK to approve."

## Notes
- Decisions for this skill (2026-11-08) are in `notes.md` next to this file.
- Music other than Blue Sky only when the owner asks; any new track must be CC0 or the owner's, with its licence beside it.
- The 45 s rule: a review may run longer (1107: 52 s); say so in notes.md.
