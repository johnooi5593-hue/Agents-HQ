---
name: sermon-moments
description: Sermon Moments (讲道特别时刻) - a toolbox of 14 editing techniques for sermon highlights, used ONLY at the moment that earns them, never as a default look. Text behind the preacher's head, active-word captions, name label, scripture/info card, question bar, cold-to-warm grade wipe, reflective prayer grade, 3x3 wall of church moments, freeze-shrink-explain, whip pan, zoom-through, alternating jump-cut framing, storyboard first, and a cover with the title behind the head. Use when editing a sermon highlight (with poster-kinetic or on its own plan), when the owner asks to "enhance", "make it wow", "add effects at the right moments", or names one of these techniques. Owner-approved 2026-10-26 from the guide in Documents/Style Guides/sermon-edit-techniques.
---

# Sermon Moments: the right effect at the right moment

The owner's words: *"not always use, use it when it's the appropriate moment."* These techniques are a toolbox, not a
style. A sermon highlight stays readable, faithful and calm by default; a moment gets an effect only when the words
themselves call for it. The guide with pictures of every technique on our own footage is
`C:\Users\John Ooi\Documents\Style Guides\sermon-edit-techniques\guideline.pdf` (read pages 2 and 14 once).

The effects are drawn by the **poster-kinetic** renderer (`.claude/skills/poster-kinetic/scripts/render.py`, its module
`moments.py`), so first build the clip and its `plan.json` with the poster-kinetic skill (steps 1-6), then add moments here,
then render there. Never change the preacher's words, scripture, numbers, negations or conditions.

## 1. Find the moments (storyboard first)
Read the transcript in `plan.md`. For each technique below, look for its **trigger** in the words. Write a short list in
`<dir>/moments.md`: line id, words, technique, why it fits. **Most lines get nothing.** A 45-60 s highlight usually has
2-4 moments; 0 is fine when the talk is plain. If the owner wants to see the storyboard first, stop and send `moments.md`
with `plan.md`.

## 2. The catalogue: trigger, how, limit

| Technique | Use it when the words... | Don't use when | Max | plan.json |
|---|---|---|---|---|
| **Text behind the head** | name the sermon's key phrase on a **speaker shot** (神的声音) | crowd B-roll, the face would be covered, wide shots | 2 | line: `"behind": true`, zone top/middle; render `--matte` (run `matte.py`) |
| **Active-word captions** | run fast (a list, a quick explanation) and need following word by word | a hero is on that line; slow, weighty lines | lines that need it | line: `"caption_style": "active"` |
| **Name label** | the preacher first appears on a calm caption-only line | a hero is up (check warns) | 1 | overlay `{"kind": "name", "start", "end", "name", "sub", "face_box": [x, y, size]}` |
| **Scripture / info card** | he reads a verse, or announces a service / series | he only alludes to a verse | 2 | overlay `{"kind": "card", ...}` (poster-kinetic) |
| **Question bar** | he asks the audience a direct question | rhetorical asides, lines that are not questions | 2 | overlay `{"kind": "question", "start", "end", "text": "<his exact words>"}`; let the answer land as a hero |
| **Grade wipe (cold → warm)** | speak of change: renew, transform, from darkness to light, old → new | anything else | 1 | moment `{"kind": "grade_wipe", "start", "end", "why"}` |
| **Reflective grade** | prayer, silence, a tender story, an invitation to respond | upbeat or teaching moments | 2 | moment `{"kind": "moody", "start", "end", "why"}` |
| **Wall of moments** | speak of "us", the church family, community, everyone | any other line; footage not our own | 1 | moment `{"kind": "wall", "start", "end", "why", "clips": [8 x {"file", "in"}]}` from the same service's B-roll |
| **Freeze, shrink, explain** | right after a question, before the answer; or to give a verse room | longer than 3 s; mid-sentence | 2 | moment `{"kind": "freeze", "start", "end", "why"}`; put the answer as a hero in the free space |
| **Whip pan** | the cut goes speaker ↔ B-roll | every cut; jump cuts | - | transition `"whip"` (6 + 6 frames) |
| **White flash** | a new section starts ("但是…", a turn) | more than 4 per clip | 4 | transition `"flash"` |
| **Zoom-through** | the one "come into the story / into the Word" beat | anything else | 1 | transition `"zoom_through"` (needs 1.2 s before the cut) |
| **Jump-cut framing** | the same speaker shot is cut several times in a row | B-roll | - | moment `{"kind": "tight", "start", "end"}` on every other piece (1.15x) |
| **Cover: title behind the head** | making the cover from a speaker frame (thumbnail-designer) | busy frames | - | see GUIDE page 9; needs the matte |

Do not do: animated editing-software panels, timeline screenshots, other creators' reels (yt-dlp), or two effects on the
same words.

## 3. Write them into plan.json, check, render, look
1. Add the moments / overlays / line fields above. Every `moments` entry except `tight` needs `"why"` (the check refuses it otherwise).
2. `python3 .claude/skills/poster-kinetic/scripts/plan.py --check <dir>/plan.json`: fix every error; take every
   "used N times" warning seriously (cut the weakest one).
3. Text behind the head only: `python3 .claude/skills/poster-kinetic/scripts/matte.py <clip> <dir>/matte.mp4` (same framing options as the render).
4. Render with poster-kinetic (`render.py ... [--matte <dir>/matte.mp4] --phone`), then
   `python3 .claude/skills/poster-kinetic/scripts/preview.py <dir>/edit.mp4 <dir>/moments.jpg --at <each moment's middle>`
   and Read it. Check: the effect lands on its words, the face is clear, nothing below y 1400, captions never doubled,
   text readable after the effect.
5. In `notes.md`, list each moment with its line and why. The brand-checker checks them against this table.

## Good to know
- Prototypes of every technique, with the exact numbers, are in the guide folder `source/fxlab.py`.
- The matte (RVM, D:/AI OFFICE/tools/models/rvm) runs about 9 frames per second on the CPU: 3 min for a 60 s clip.
- Whip pans are heavier to render; a 60 s clip with ~20 cuts takes about 4 min.
- Owner rules still hold: speaker angle only from the RAW (no slides), our own B-roll, phone copy under 28 MiB.
