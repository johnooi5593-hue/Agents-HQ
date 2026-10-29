---
name: neon-glow
description: Neon Glow (霓虹发光字) style for sermon highlights and other vertical clips - every line typed on in cool chrome (#E8EFF6 -> #B5C5D3) one character as it is spoken, and on the lines that matter one neon-yellow keyword (English or Chinese) under it that switches on like a neon tube (dim -> bright, no movement, 0.27 s) with the measured four-layer glow (near-white yellow core, tight dark rim, olive halo, faint bloom). Also a giant left-aligned neon number, white text laid over a neon word, blur-into-darkness transitions, B-roll inside a dark rounded window and a chat bubble with typing dots. Built from the owner-approved guide measured from two Instagram ads. Use when the owner asks for neon-glow, 霓虹, 发光字, glow words, "the glow style", "the second XiXi style", or the exact glow and shine. Plan first, then render; the sfx skill adds sound after.
---

# Neon Glow: chrome words, one neon word that switches on

Guide: `C:\Users\John Ooi\Documents\Style Guides\neon-glow-reel\guideline.pdf` (read pages 2-6 once; numbers in `GUIDE.md`). The
renderer reproduces the measured glow and switch-on, so your job is choosing **which word glows** and keeping the words exact.
Never change the preacher's words, scripture, numbers, negations or conditions.

Scripts: `D:/Agents HQ/.claude/skills/neon-glow/scripts/` (call it `$NG`). It reuses caption-card and poster-kinetic next to it
(fonts, layout, speech-to-text, preview). One command per Bash call, quoted absolute paths, a short working folder. Every
script prints one JSON line. Never upload, post or delete anything.

## Steps
1. **Source.** A clean, caption-free edit, or a topic cut from a RAW livestream as in the poster-kinetic skill (speaker crop;
   the owner's rule: no slides from the RAW).
2. **Plan.** `python "$NG/plan.py" <clip> <dir>/plan.json` (CPU faster-whisper, local large-v3-turbo; `YS_LANG=zh`), or reuse
   another plan's lines: `python "$NG/plan.py" --from-plan <other plan.json> <dir>/plan.json`. Fix clearly misheard words in
   `text` and `words` (note them).
3. **Choose the neon words** (every other line just types on in chrome). About one every 3-6 s, the word this sentence is
   about. On a chosen line set:
   - `keyword`: the glowing word, an exact part of the line, 1-3 English words or 2-5 Chinese characters (keep a 不 / 没有
     with it, or in the lead). English glows in the condensed face; Chinese in the heavy sans.
   - `lead` (optional): the chrome row above it, an exact part of the line; by default the rest of the line.
   - `over` (optional): a short exact part shown in white over the lower half of the neon word (TRUST + in the Lord).
   - `layout: "number"` for a number, chapter or percentage: the neon number huge and left-aligned, the lead under it.
   - `transition: "blurdark"` on the first line of a new section (blur into darkness, 0.35 s), 2-4 per clip.
   Plan level (optional): `"moments": [{"kind": "window", "start", "end"}]` puts **dark** B-roll inside a dark rounded frame
   (it looks wrong on a bright speaker shot); `"overlays": [{"kind": "bubble", "start", "end", "text"}]` a chat bubble with
   typing dots, then exact spoken words (a question, a quote); the line it repeats is hidden.
4. **Check.** `python "$NG/plan.py" --check <dir>/plan.json` (errors must go; warnings: long neon words shrink, too many or
   too close), `python "$NG/plan.py" --md <dir>/plan.json` writes the planning page; stop here if the owner wants to see it.
5. **Render.** Quick: `python "$NG/render.py" <clip> <dir>/plan.json <dir>/quick/edit.mp4 --to 15 --preset veryfast`.
   Full: `python "$NG/render.py" <clip> <dir>/plan.json <dir>/edit.mp4 --phone` (about real time). Writes `edit.mp4`, `edit.srt`,
   `edit_phone.mp4`, `edit.pk.json`, `edit.sfx-events.json`.
6. **Look.** `python "D:/Agents HQ/.claude/skills/poster-kinetic/scripts/preview.py" <dir>/edit.mp4 <dir>/preview.jpg --at ...`
   at each neon word (its spoken time, +0.1 s, +0.4 s) and a few chrome lines. Check: the glow reads on the picture, no text
   on the face, the chrome readable, no boxes for missing characters.
7. **Sound** with the sfx skill from `edit.sfx-events.json` (soft chimes on the neon words: keep the true punchlines).
8. **Deliver** as the other styles: `notes.md`, Agents HQ `out/<name>/` with `edit.mp4`, `captions.srt`, `clean.mp4`
   (`--no-text`), `followups.json`; send `edit_phone.mp4`.

## Enhanced glow and motion (the default)
The owner asked for more shine and motion than the reference (2026-10-29), so every neon word now gets, on top of the
measured look:
- **Striking flicker**: two quick flickers as the tube strikes (frames 0-3), then the switch-on.
- **Glow burst**: the halo overshoots to 1.75x at frame 8, settles by frame 17, then **pulses** gently (+-14 %, 1.1 Hz).
- **Wider, warmer glow** (1.65x halo, brighter bloom, a hot inner glow) and a slight **scale settle** 1.07 -> 1.0.
- **Light streak**: an anamorphic flare through the word at the burst, with a star glint sliding across.
- **Shine sweep**: a diagonal white light band runs through the letters once (frames 14-30), lighting the glow with it.
- **Sparkles**: star glints pop along the top edges of the letters after the sweep.
- **Stage**: the picture dims about 18 % with a vignette and a soft dark backplate sits behind the text group, so the glow
  reads even on a bright stage; the group slowly pushes in (2.5 %).
- **Chrome rise**: each chrome character rises 16 px and unblurs as it is spoken; the white over-text rises in too.
- **Exit flare**: the word swells, brightens and blurs away over 6 frames.
- **Kinetic ordinary lines** (the owner asked for varied placement and much more word animation): every line without a
  neon word gets its own **placement** (center, left, right, stagger = a poster stack of rows with alternating offset and
  size; never tilted) and **word animation** (rise, pop, slide, drop with bounce, wave, zoom, flash; words are never rotated), varied line
  by line so two neighbours never match. Each word lands at the moment it is spoken; one **key word** per English line (the
  longest content word, or `"emph"`) is 1.4x in warm gold glow with a glint; words float gently while held; a soft dark
  plate sits behind them; they lift and blur away at the end. Override per line with `"place"`, `"anim"`, `"emph"`; plan
  `"auto_motion": false` keeps every ordinary line centred with the plain rise.
Plan `"fx": "reference"` turns all of this off (the measured original look). Per line: `"shine": false` skips the sweep and
sparkles; `"fx": false` gives that line the reference look.

## Good to know
- Glow numbers scale with the letter height h: rim about 0.05 h, halo about 0.11 h blur (fades within 0.15 h), bloom 0.3 h at 18 %.
- Switch-on (30 fps, 8 frames, ease-out): opacity 0.25 -> 1, saturation 0.3 -> 1, brightness 0.55 -> 1, glow 0 -> 1, rim 0.4 -> 1.
  The neon word never moves or scales. Chrome characters each appear in 2 frames from blur 6 at their spoken time.
- Fonts: chrome = Alibaba PuHuiTi Heavy (Latin Arial Black; Traditional characters fall back to 思源黑体 Heavy); neon English =
  Bebas Neue at 86 % width. The reference's own fonts are unknown.
