---
name: reel
description: Edit ONE raw clip from inbox/ into a finished vertical reel with burned-in captions, following the brand rules. Use when asked to edit, cut or "make a reel" from a clip. For the cover image, also use the pixel skill.
---

# Reel: one raw clip in, a finished vertical edit out

Call the clip `<name>` (its file name without the extension). Run every step as its own command, one command per Bash call, no `&&` chains. The scripts live in this skill's `scripts/` folder and create their output folders themselves.

1. **Brand rules.** Read them from the shared brain: `mcp__memory__open_nodes` with names ["Brand rules"]. Use the maximum length and the caption color they give.
2. **Cut.** `python3 .claude/skills/reel/scripts/cut.py inbox/<file> out/<name>/cut.mp4 --max <max seconds>`
   **Footage mix** (sermon highlights cut from a RAW livestream, owner 2026-11-02): show the RAW in only 2-3 scenes; the rest is the same service's B-roll, mostly the speaker from other angles and about a third without the speaker (audience, worship team, raised hands, the hall and stage), more of those on the reflective lines. The speaker's audio, timing and captions run on unchanged under the B-roll; captions stay off faces.
   Removes pauses and filler-only phrases ("um", "uh", "ah", "ohh") and reframes to vertical 1080x1920. A wide clip is center-cropped; add `--frame blur` to keep the whole frame on a blurred background instead.
3. **Captions.** `python3 .claude/skills/reel/scripts/captions.py out/<name>/cut.mp4 out/<name>/edit.mp4 --srt out/<name>/captions.srt --color <caption color> --words 3 --size 56`
   Always pass `--size 56`: the default size clips long 3-word lines at the frame edges.
   **Negative key word** (only when the owner asks for it, see the negative-key skill): `--key-style negative` draws the highlighted word (the word being spoken) as a photo negative of the picture behind it (255 - background) over a soft dark shadow; the other words stay white with their dark outline, and `--color` is unused.
   It prints the transcript. Read it. If a word is clearly misheard, run it again with `--replace "wrong=right"` (repeatable).
   **Music** (every edit, owner 2026-11-01): blend the owner's track under the voice with the sfx skill's step 0 (`music.py`); its output becomes `edit.mp4`.
4. **Look at it.** `python3 .claude/skills/reel/scripts/frames.py out/<name>/edit.mp4 out/<name>/frames.jpg`, then Read `frames.jpg`: captions readable, nothing cut off. Check the widest caption line in every frame. If any text touches or crosses the left or right edge, re-run step 3 with `--size` lowered by 4 and look again. Don't report the edit until no line is cut off.
5. **Self-check.** Go through every brand rule (length, fillers, caption color, words per line). Fix anything that fails before you report.
6. **Notes.** Write `out/<name>/notes.md`: a title (max 60 characters, no clickbait), the hook (the first sentence a viewer hears), raw length, edit length, seconds removed, fillers removed and the transcript.
7. **Done.** When the edit and its cover exist and the brand-checker passed them, move the raw clip: `mv inbox/<file> done/`

Report in three short lines: the folder, the edit length, the title.

Never upload, post or delete anything.
