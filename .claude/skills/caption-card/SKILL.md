---
name: caption-card
description: Caption Card (字卡动效) style for sermon highlights and other vertical clips - every phrase on a cyan card with blue slanted words (hard cuts, 2-6 characters), plus 3-4 pro big-type moments built with layered type (gradient, dark soft shadow, glow, background blurred and dimmed) and measured pro motion (fast-in, overshoot, settle, stagger, motion blur, swell-before-exit) - a 3-line hook whose key row scatters and gathers, a giant gradient number, a phrase written on like a light pen with a bloom exit, and a punch line that slams in character by character with a picture punch-in. Built from the owner-approved guide measured from an Instagram ad. Use when the owner asks for caption-card, 字卡, "the IG ad style", "the XiXi style", cyan caption boxes, or very pro word animation / motion graphics on a sermon highlight. Plan first, then render; the sfx skill adds sound after.
---

# Caption Card: cards for every phrase, pro big type for the few that matter

The style in one line (guide: `C:\Users\John Ooi\Documents\Style Guides\xixi-trading-reel\guideline.pdf`, read pages 2, 5-6 and
14 once; numbers in `GUIDE.md`): **every line is a cyan caption card; 3-4 lines a minute earn big type.** The big type looks pro
because of its five layers and its motion (both built into the renderer); your job is choosing the right lines and keeping
the words exact. Never change the preacher's words, scripture, numbers, negations or conditions.

Scripts: `D:/Agents HQ/.claude/skills/caption-card/scripts/` (call it `$CC`). It reuses poster-kinetic (fonts, speech-to-text,
preview) next to it. One command per Bash call; quoted absolute paths; run from a short folder. Every script prints one JSON
line. Never upload, post or delete anything.

## Steps
1. **Source.** A clean, caption-free edit (e.g. `edit_src.mp4` / `clean.mp4`), or cut a topic from a RAW livestream as in the
   poster-kinetic skill (speaker crop `--crop 960:297:960:540 --focus ...`; the owner's rule: no slides from the RAW).
2. **Plan.** `python "$CC/plan.py" <clip> <dir>/plan.json` (CPU faster-whisper, local large-v3-turbo; `YS_LANG=zh` for Chinese),
   or reuse an existing plan's lines: `python "$CC/plan.py" --from-plan <other plan.json> <dir>/plan.json`. Read the transcript;
   fix clearly misheard words in `text` and the same word in `words` (say so in `note`).
3. **Choose the big moments** (most lines stay `"kind": "card"`). One every 12-20 s, at least 3 s apart, each with `"why"`:
   | kind | when the words... | fields (exact parts of the line) | default colour |
   |---|---|---|---|
   | `hook` | open the clip: a question or bold claim | `rows`: 2-3 short rows in word order, 2-6 characters / 1-3 words each; the last row is the key (or `key_row`) | key row `key` yellow (try `gold`) |
   | `number` | give a number, a count, a chapter or a percentage | `number`; optional `label` (short, shown above) and `unit` (beside) | `lime` |
   | `writeon` | carry the promise or a name to remember | `phrase` (up to 7 characters / 4 words); optional `sub` under it | `green` (try `gold` for grace) |
   | `punch` | call to action, the last line, the one sentence to obey | `phrase` (4-7 characters / 1-4 words) | `yellow` |
   Colours: `key, yellow, lime, green, white, gold, cyan, rose` or `#hex`. Merge two transcript lines first when a hook's rows
   or a number's label span them (edit `text` and join `words`). Optional per line: `"transition": "flash"` (section start) or
   `"blurcut"`, `"y"` (0-1) to move big type off a face. Plan level: `"card": {"box", "text", "text2"}` for a church colour pair,
   `"card_y"` (default 0.51, the chest).
4. **Check.** `python "$CC/plan.py" --check <dir>/plan.json` (fix errors; weigh warnings: long rows shrink, moments too close)
   and `python "$CC/plan.py" --md <dir>/plan.json` writes the planning page. Stop here if the owner wants to see it first.
5. **Render.** Quick look: `python "$CC/render.py" <clip> <dir>/plan.json <dir>/quick/edit.mp4 --to 15 --preset veryfast`.
   Full: `python "$CC/render.py" <clip> <dir>/plan.json <dir>/edit.mp4 --phone` (about real time). Writes `edit.mp4`, `edit.srt`,
   `edit_phone.mp4` (under 28 MiB), `edit.pk.json` and `edit.sfx-events.json`.
6. **Look.** `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/preview.py" <dir>/edit.mp4 <dir>/preview.jpg --at <t1>,<t2>,...`
   at each big moment (entry, +0.1 s, +0.3 s, landed) and two cards. Check: big type lands on its word, never on the face,
   readable on the picture, cards never doubled with big type, no clipped text, Traditional characters drawn (no boxes).
7. **Sound.** The sfx skill: start from `edit.sfx-events.json` (a draft of every big move), keep the true punchlines (a sermon
   stays reverent: 1-3 hits a minute), run its `place.py`.
8. **Deliver** as the other styles do: `notes.md` (title, punchline, the big moments and why, fonts, the transcript), Agents HQ
   `out/<name>/` with `edit.mp4`, `captions.srt`, `clean.mp4` (`render.py ... --no-text`), `followups.json`; send `edit_phone.mp4`.

## Good to know
- Fonts (closest installed; the reference's own fonts are unknown): cards 优设标题黑 (Latin: Alibaba Sans Heavy Italic), hook /
  labels Alibaba PuHuiTi Heavy + Arial Black, punch 庞门正道标题体 (whole phrase falls back to PuHuiTi Heavy if one character is
  missing), numbers and English write-on Bebas Neue at 86-90 % width. Traditional characters fall back to 思源黑体 Heavy.
- Motion numbers (30 fps): hook rows blur in 4 f; key row scatter 2.2x -> 1, 0.45 -> 1.12 -> 1.0 in 7 f, one ghost; number 0.45 ->
  1.15 -> 0.97 -> 1.0 in 6 f, exit swell 1.08 + brighten then shrink 0.7 in 5 f; write-on 4 f per character, 2 f apart (1 f for
  Latin letters); bloom exit 5 f; punch units 2 f apart, 0.4 -> 1.35 -> 0.95 -> 1.0 with +-15 deg tilt, 1.35x punch-in.
- Pairs with **sermon-moments** (text behind the head etc.) only through poster-kinetic; in caption-card, keep to these four.
