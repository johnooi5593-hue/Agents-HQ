---
name: pixel
description: Make the cover image (thumbnail) for a cut clip, following the brand cover rules. Use whenever an edit needs a cover, or when the owner asks for a cover or thumbnail.
---

# Pixel: the cover

1. **Rules.** Read the brand rules from the shared brain: `mcp__memory__open_nodes` with names ["Brand rules"]. Note the word limit and the cover color.
2. **Words.** From the transcript or `notes.md`, pick the strongest idea in at most 3 words, all caps. Concrete beats clever. The cover should make the same promise as the title.
3. **Make it** from the cut without captions:
   `python3 .claude/skills/pixel/scripts/thumbnail.py out/<name>/cut.mp4 out/<name>/cover.jpg --text "<COVER TEXT>" --color <cover color>`
   The script picks the sharpest, best-lit frame on its own. `--accent N` colors the Nth word instead of the last one.
4. **Look at it.** Read `cover.jpg`. If the text sits on something busy or is hard to read, run it again with `--at <seconds>` (another frame) or `--pos middle|bottom` (move the text).
5. **Record it.** Add a line `Cover text: <COVER TEXT>` to `out/<name>/notes.md`.

One command per Bash call. Never delete files.
