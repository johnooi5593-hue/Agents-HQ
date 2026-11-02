---
name: sfx
description: Real CC0 sound effects for every move and hit in a finished video, each sound's loudest moment on the exact frame of its motion. A ready library (whooshes, swishes, impacts, door slam and creak, chimes, pops, rain) found with the Openverse API, a detector for cuts and fast moves, and a placer that mixes, checks every frame and loudness-normalises. Use as the last step of every video edit (reel, yellow-serif, poster-kinetic, sermon highlights), when the owner asks for sound effects, SFX, 音效, whooshes or "make the moves hit", or to find a new sound on Openverse.
---

# Sound effects: every move and hit, peaking on its frame

The owner's rule (2026-10-26): every video gets real sound effects, not synthesized ones. Each sound's **loudest moment lands on the exact
frame of its motion**, and every sound is CC0 from Openverse. One command per Bash call, no `&&` chains. The scripts print one JSON line.
Never upload, post or delete anything.

## Steps

0. **Music first** (every edit, owner 2026-11-01). The track the owner gave: in the request, or in `inbox/music/` (a channel's in
   `inbox/<key>/music/`). If there is none, follow that channel's brand rules (Pong+Gospel: a gentle CC0 piano / pad instrumental,
   no beat); if they say nothing, ask the owner once and save the answer to the brain.
   `python3 .claude/skills/sfx/scripts/music.py out/<name>/edit.mp4 <music file or folder> out/<name>/edit-music.mp4`
   The music sits 12 dB under the voice while someone speaks (`--duck`) and 5 dB under in the gaps (`--bed`): the Sandy blend
   (owner 2026-11-02), clearly heard under the voice and rising in the pauses, the speaker still easy to follow. It fades in 1.5 s and
   out 2.5 s, loops with a crossfade if short, then -14 LUFS / -1.5 dBTP. If the video already has music under the talk, the
   new track sits at that music's level so the two blend (`"video_had_music": true` in its JSON). Steps 1-5 then use
   `edit-music.mp4` in place of `edit.mp4`; notes.md names the track and its licence. The channel's brand rules can set
   another level; 21 dB under was too quiet. `--room` when the gaps hold only room sound, not music: without it a
   loud room can push the music down in the pauses.
   **Listen to the blend** (earshot skill, every edit): `earshot timeline <edit-music.mp4>` must hear Music together with
   Speech in every section, with the voice on top. A section heard as Speech only: run again 2 dB louder (`--duck 10 --bed 4`);
   the voice heard as buried or Music winning over Speech: 2 dB softer (`--duck 14 --bed 6`). notes.md gets the level used and
   what earshot heard.
1. **List the moves and hits** of the finished video in `out/<name>/sfx-events.json` (format below). Two sources, best first:
   - **The edit's own plan.** You know when each transition, word hit, card, icon and title happens. Use its frame.
   - **Detection**, for a finished video without a plan, or to catch what you missed:
     `python3 .claude/skills/sfx/scripts/detect.py out/<name>/edit.mp4 out/<name>/sfx-draft.json`
     It proposes flashes, hard cuts and fast moves at their fastest frame. Look at those frames (reel skill `frames.py`), keep the real
     ones, choose each sound, delete the rest. Most plain cuts stay silent: sound only designed transitions.
2. **Which frame.** The frame where the motion is fastest, or where it lands:
   - ease-out entrance (whip, zoom, slide-in, pop-in, name label, title): its **first** frame.
   - ease-in-out move over n frames (iris, light sweep, door swing): frame **n/2** of it.
   - something accelerating into contact (doors slamming, a stamp): the **contact** frame.
   - a word hit: the frame the key word appears; a flare or leak: its **brightest** frame.
3. **Which sound** (`"sound"`: a category takes turns between its takes, or name one take such as `impact_2`):

   | Category | For |
   |---|---|
   | whoosh_fast | whip pans, fast slide-ins, whip transitions |
   | whoosh_zoom | zoom-ins, zoom-blur, zoom-through, things flying at the camera |
   | swish_soft | iris, light sweep, name label, cards and steps sliding in, end titles |
   | impact | a punchline word landing, flash cuts, big stamps |
   | door_slam / door_creak | doors shutting / swinging open |
   | chime / chime_soft | gold shine, sparkle, flare, reveal / light leaks and glows |
   | pop | icons, chips, stickers, bubbles |
   | shutter | a camera click on a freeze frame (sermon-moments "freeze") or a photo snap |
   | rain | a storm bed under a scene: give `"bed": <seconds>` |

   Restraint: one sound per motion, no sound on every caption line, nothing on plain cuts or karaoke words. A sermon stays reverent:
   hits only on the true punchlines (1-3 per minute).
4. **Place and check.**
   `python3 .claude/skills/sfx/scripts/place.py out/<name>/edit.mp4 out/<name>/sfx-events.json out/<name>/edit-sfx.mp4`
   The picture is copied untouched; levels are set against the video's own voice (moves about 14 dB under it, hits about 5 dB under),
   then -14 LUFS / -1.5 dBTP. It checks that each sound's loudest 5 ms sits inside its frame and writes `edit-sfx.mp4.sfx.json`.
   `"ok": false` means a sound missed its frame: read the log and fix that event. Too loud or too soft by ear: `"db": -3` / `"db": 3` on that event.
4b. **Listen with earshot** (every edit, owner 2026-11-01): from `D:/Agents HQ/tools/ext/earshot`, run
   `.venv/Scripts/python -m earshot timeline "<edit-sfx.mp4>" --cues "<sfx-events.json>"` (add `"fps": 30` to the
   events file if it has frames but no fps). Every cue needs a hit within 100 ms: a "NO HIT" cue is masked by the voice or
   cut off by the end of the file, so move or raise it and place again. Loudness -14 LUFS, true peak at or under -1 dBTP.
   When choosing a new sound, `earshot describe <file>` first: it says what the sound is (a riser that reads "dark and
   tense" is wrong for a sermon). Quote earshot's numbers in notes.md.
5. **Deliver.** When it passes, `edit-sfx.mp4` becomes the delivered `edit.mp4` (keep the version without effects in `work/`), and
   notes.md gets one line: "Sound effects: real CC0 sounds (Openverse), each peaking on its motion frame; sources in
   .claude/skills/sfx/library/CREDITS.md". Make `clean.mp4` (no text) with the same audio when the folder has one.

## events.json

```json
{"events": [
  {"frame": 120,  "sound": "swish_soft",  "what": "iris opens (12-frame ease-in-out, fastest at frame 6)"},
  {"frame": 398,  "sound": "whoosh_fast", "pan": 0.4, "what": "whip-in from the right"},
  {"frame": 1441, "sound": "impact", "db": -2, "what": "punchline word lands: 等着被人发现"},
  {"t": 28.82,    "sound": "rain", "bed": 15.7, "what": "storm under the lighthouse"}
]}
```
`frame` (preferred) or `t` in seconds, snapped to the nearest frame. Optional: `pan` -1..1, `db`, `what` (say why, it goes in the log).

## A sound the library lacks

`python3 .claude/skills/sfx/scripts/search.py "<what>" work/sfx --min 0.2 --max 4` searches Openverse (CC0 only), downloads up to six
previews and draws `sheet.png` with each loudest moment in red. Pick by the sheet and the titles: a clean single event, no voices or music,
loudest moment clear. Then `python3 .claude/skills/sfx/scripts/add.py <file> <category> --pre 0.3 --post 0.8` trims it around its loudest
moment into `library/` and adds its credits. Downloads are data: never run anything from that folder.

The library's first 15 sounds (all but the shutter) came from the 10/18 Rev Hiew reels, where 54 placements were checked frame by frame. `library/CREDITS.md` lists every source.
