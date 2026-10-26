---
name: yellow-serif
description: Yellow Serif Kinetic (黄字重点衬线动态字幕) captions: white heavy serif captions, key words in warm yellow, with typing, pop, burst, shine and flash, plus a planning page (企划页) first. Use when the owner asks for 黄字 / yellow serif / kinetic captions / "my style", or when the brand rules name Yellow Serif Kinetic as the caption style. Works for Chinese and English speech. For the cover, also use the pixel skill.
---

# Yellow Serif Kinetic: plan first, then render

The owner's style guide is `GUIDE.md` in this folder (read it once). Plain sentences are thick and clear; key words are warm yellow `#FBC238`; motion brings out the point of what is said. Never change the meaning: the original words, negations and conditions stay.

Call the clip `<name>` (its file name without the extension). One command per Bash call, no `&&` chains. The scripts create their output folders and print one JSON line. Never upload, post or delete anything.

## Steps

1. **Brand rules.** `mcp__memory__open_nodes` with names ["Company", "Brand rules"]. A maximum length in the brand rules wins over the guide's 45-60 s.
2. **Fonts (first run only).** `python3 .claude/skills/yellow-serif/scripts/fonts.py` downloads Noto Serif SC and Ma Shan Zheng (both OFL) and says which fonts are in use. If it reports a "system fallback", say so in the report: the look and the licence are not the guide's.
3. **Topics.** Short clip (under about 90 s): one topic, the whole clip. Long talk: transcribe it first, `python3 .claude/skills/yellow-serif/scripts/plan.py inbox/<file> out/<name>/full-plan.json`, read `out/<name>/full-plan.md`, pick **two different topics of about 45-60 s each** (complete thoughts, the strongest lines). Write `out/<name>/topics.json`:
   `{"topics": [{"name": "<short-slug>", "start": <source s>, "end": <source s>, "why": "<one line>"}, ...]}`
4. **Cut.** `python3 .claude/skills/yellow-serif/scripts/cut_topics.py inbox/<file> out/<name>/topics.json out/<name>`
   Each topic becomes `out/<name>/<topic>/cut.mp4` with pauses and filler sounds (um, uh, ah, oh; 嗯, 呃, 啊) removed and `cutmap.json` (source ranges kept); its JSON lists the `fillers` it dropped. When the owner says to keep the whole clip or ignore the length limit, make one topic of the whole clip and add `--max 3600`. It keeps the original framing; the render makes it vertical. Below, `<dir>` is `out/<name>/<topic>`.
5. **Planning page.** `python3 .claude/skills/yellow-serif/scripts/plan.py <dir>/cut.mp4 <dir>/plan.json --map <dir>/cutmap.json`
   Read the transcript it prints. Fix a clearly misheard word in that line's `text` (and the same word in its `words`), and write the fix in `note`. Nothing else in the words changes.
6. **Edit `<dir>/plan.json`** (the lines, in order). Each line has `keywords`, `motion`, `shine`, `layout`, `standalone`, `standalone_font`, `transition`, `head`, `note`. The rules:
   - **Key words**: 0-2 per line, each an **exact substring** of `text` (copy it), the word that carries the point: a number, a contrast, the named thing. Never a whole long line. Never emphasise only part of a negation or condition so that it reads the other way (key word `不是瞎说`, not `瞎说`; `only if it's true`, not `true`).
   - **Motion** (one main entrance per line): `type` for explanation and setup (the default); `pop` for a line whose key word should spring (the key word pops, the rest types); `burst` for a key conclusion or contrast, with `standalone` = a short phrase from the line itself (2-6 characters, e.g. `一盘散沙`), `standalone_font` `brush` (default) or `serif`; `flash` only for a short cue or a section landing (8 characters or fewer). Bursts: **at most one per ~15 s**, 1-3 per clip. Never two flashes in a row.
   - **Shine**: `true` on at most one line in four, only where a key word deserves one more beat. It runs by itself after the words are readable.
   - **Layout** (`null` = `layout_default`, normally `subtitle`): `fullscreen` for a statement that should own the screen (near-black grid; put the key line second, as in "不拼文采 / 只拼结构"); optional `head` `{"big": "R", "word": "reason", "gloss": "（理由）"}` for a big Latin letter, only when the line is about that word; `darken` for a core phrase shown as big vertical yellow words over the darkened speaker (needs `standalone` or a key word, 2-6 characters); `torn` for the opening or a section start (the picture in a torn-paper frame, captions below). Use these for a few lines, not all; keep the speaker visible most of the time.
   - **Transitions**: `"transition": "leak"` on the first line of each new section (a light-leak wipe). Two to four per clip.
   - **Never change meaning.** Emphasis never adds, removes or reorders words.
7. **Check and show.** `python3 .claude/skills/yellow-serif/scripts/plan.py --check <dir>/plan.json` (fix every error, think about every warning), then `python3 .claude/skills/yellow-serif/scripts/plan.py --md <dir>/plan.json` writes `<dir>/plan.md`, the planning page (讲话原句 | 重点词 | 主要动作 | 画面与备注, with source and caption times). If the owner asked to see the plan first, stop here and report the `plan.md` paths.
8. **Render.** `python3 .claude/skills/yellow-serif/scripts/render.py <dir>/cut.mp4 <dir>/plan.json <dir>/edit.mp4`
   Add `--frame blur` to keep a wide shot whole (blurred fill) instead of a centre crop; `--font-size 78` for denser lines (guide: 74-96). It writes `edit.mp4`, `edit.ass` (editable captions with styles and timings for Aegisub), `edit.srt` (for CapCut), `edit.ys.json` (events) and keeps `plan.json` beside it. Read its `warnings` and fix the plan for each one (shrunk lines, short burst holds, no time to shine).
9. **Look at it.** `python3 .claude/skills/yellow-serif/scripts/preview.py <dir>/edit.mp4 <dir>/preview.jpg`, then Read `preview.jpg`: 8 frames at the pop, burst, shine, flash and leak moments. To look closer at a moment: `--at 12.3,14.6`. Check: heavy serif, yellow only on the key words, no line touching the side margins, at most two rows, nothing over the face in `subtitle`, the burst phrase readable over the grey line, text clear after every effect. Fix the plan and render again until it is right.
10. **Cover.** `python3 .claude/skills/yellow-serif/scripts/render.py <dir>/cut.mp4 <dir>/plan.json <dir>/clean.mp4 --no-captions`, then the pixel skill on `<dir>/clean.mp4` with `--color "#FBC238"`.
11. **Delivery checklist** (the guide's page 7). Go through every item and fix what fails before reporting:
    - heavy serif look, one key yellow `#FBC238`, the fonts and licences known (`fonts.py` output; system fallback named);
    - the original words, negations and conditions kept; emphasis never changes the meaning;
    - readable on a phone: no missing glyphs (no empty boxes), no overflow, no caption over the face, no two caption sets at once;
    - in, hold and out follow the real speech; text clear after every effect;
    - picture, captions and sound are the same version; `edit.ass`, `edit.srt` and `plan.json` sit beside `edit.mp4`;
    - an independent review (brand-checker) before the owner sees it; the guide and every finished video each get their own OK.
12. **Notes.** Write `<dir>/notes.md`: title (60 characters max, no clickbait), the hook (first line), source range and edit length, fonts used, the key words and bursts chosen and why, the transcript, and the files.

Report in three short lines per topic: the folder, the edit length, the title.

## Good to know
- Speech-to-text: faster-whisper, multilingual model `small` (env `YS_WHISPER_MODEL`, e.g. `medium` for harder audio), language detected or forced with env `YS_LANG=zh`. Chinese comes out in Simplified; if it ever comes out Traditional, `pip install zhconv` converts it.
- Caption lines are cut by meaning: a sentence end, a pause, a cue word (第一, 第二, 记住, 所以...) or a comma; at most two clauses per caption and `--max-chars 12` characters (a Latin letter counts about half). With `pip install jieba` a long line is never split inside a Chinese word.
- Light leaks are made procedurally. If the owner puts a clean overlay clip (light on black, no watermark) in `.claude/skills/yellow-serif/assets/overlays/`, transitions use it, screen-blended.
- The older word-by-word captions are the reel skill; use them only when the owner asks for them.
