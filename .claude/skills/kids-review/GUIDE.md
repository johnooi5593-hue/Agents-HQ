# Kids Review: what makes it cute (the numbers)

Measured on the owner-approved 1107 Children review (v3 "Niceee!", v4 = the same with the neutral grade). Positions are
fractions of the frame; sticker sizes are fractions of the frame's SHORT side (1080 px on both sizes).

## 1. The feeling in one line
A happy host talks the viewer through the day, one chatty line per 2 s shot; every phrase is a puffy pink sticker card
whose characters hop in; something small and cute pops at every cut; a bigger burst lands on each of the 5-7 moments
that matter; the picture is bright, clean and neutral; ukulele music and soft pops carry it. Cute, never cluttered,
never on a face.

## 2. Picture
| | 9:16 (1080x1920) | 16:9 (1920x1080) |
|---|---|---|
| Shot length | 2.0 s (1.8-3.2 s; the hook 2.2 s, group photos 2.6-3.2 s) | the same shots, same order and lengths |
| Framing | crop around the subject from a 3413x1920 decode (real pixels); group photos whole over a blurred fill (blur 40, brightness 0.62, photo 40 px above centre) | the camera's whole picture, no fill; a gentle crop only where needed (shots16.json) |
| Pre-grade (build.py) | eq gamma 1.12, contrast 1.05, saturation 1.18, brightness 0.01 | the same |
| Grade (grade.py) | neutral and bright: white walls white, skin natural; soft contrast, gentle highlight roll-off, a light glow (owner 2026-11-08: never orange / warm) | the same |
| Caption grade arc | near-neutral (1107 v4): [[0, 0.03], [0.38 x dur, 0.05], [0.73 x dur, 0.08], [dur, 0.1]], light bloom 0 (v3's 0.15 -> 0.33 and its 0.12 warm bloom stacked into orange skin) | the same plan |
| Camera | push / drift per shot, 1.12 punch-in on one line, 1.22 punch on the big punches, a pull-back over the goodbye | the same (up to 1.27x enlargement on 1080p sources) |
| Skin check | R >= 250 on 0 % of a face; face saturation about 0.36-0.40 | the same |

## 3. Captions (Caption Card, cute edition)
| | 9:16 | 16:9 |
|---|---|---|
| Card | pill #FFD3EA, thick white outline, soft dark-pink shadow, top gloss | the same |
| Card text | #F0347F, second colour #C8166A, 150 px, max width 900 | 110 px, max width 1500 |
| Card height | card_y 0.66 (under the faces; per-line moves in cute.json, 1107: 0.74 and 0.56) | 0.82 (layout16.json card_y) |
| Key word | candy gradient #FF2E88 -> #FF8A2B, rim #C8166A, 1.3x squash pop, 3 sparkles #FFE45C | the same |
| Characters | hop / side / pop / drop (ball, lands in about 10 frames) / wave, one per line entrance; every character lands >= 4 frames before its card ends | the same |
| Card chunks | never shorter than 0.4 s (they join their neighbour); never split inside a word (regroup_words.py) | the same |
| Exits | 6-frame shrink-pop with a 5-dot poof (silent) | the same |
| Speech-bubble cards | about 3 lines (a "let's go" line, the group-photo count 一二三耶, the goodbye) | the same |
| Big type | hook rows 150/210 px, write-on 340, punch 260; rainbow outline #FF4F9A #FF9F1C #FFC93C #2FCB78 #3FA0F5 #9B6BFF; yellow punch #FFEB5C -> #FFB21F | hook 104/150, write-on 230, punch 190; x / y per moment in layout16.json (1107: hook x 0.21 y 0.79, 比个V y 0.80) |
| Big moments | 5 in 52 s: hook (question), the craft's name (write-on), a V sign (punch), the wow (write-on), the payoff (punch) | the same |

## 4. Stickers and motion graphics
- **Palette:** pink #FF7AC8, rose #F0347F, light #FFD3EA, yellow #FFE45C, mint #7BF7C8, sky #7CC8FF, purple #B68CFF,
  orange #FFA24C. Every sticker has a thick white outline and a soft drop shadow. Bubble text: solid ink #D81B60
  (#1565C0 on sky bubbles) over a thick white outline, no shine (open counters: 酷 and 害 must read).
- **Kinds:** QQ faces (smile, laugh, star eyes, heart eyes, wink, wow, wave), star, heart, sparkle, rainbow, cloud, sun,
  note, thumbs-up, V hand, camera, "?", crayon squiggle, confetti; motion graphics: bubbles, twinkles, trails, wipes,
  underlines, arrows, crayon corner frames, balloons. All drawn in code (no emoji font, no downloads).
- **Motion:** pop-in 0.34 s (scale 0.25 -> 1.2 -> 0.95 -> 1), a wobble / bounce / float while held, pop-out 0.22 s.
  Hearts and notes float up (rise 0.06-0.10), balloons rise to the end, crayon lines "boil" every 4 frames.
- **Sizes:** cut stickers 0.15; burst leaders 0.22-0.25; burst helpers 0.10-0.17; bubbles 0.18-0.27 (drawn 1.35x / 1.45x
  bigger, then shrunk to fit off every face and card, never below 0.85x); twinkles 0.08; trail pieces 0.065; balloons
  0.12-0.13; confetti 0.04 (40-44 pieces, clipped to bands with no faces).
- **Density (1107: 52 s, 25 cuts):** one small sticker on each plain cut (17), at cut + 0.05 s, at most 1.6 s, a new kind
  each time; 7 bursts of 3-7 pieces; 14 bubbles, 26 twinkles, 7 trails, 6 wipes (about every 4th cut, 10 frames centred
  on the cut, never on a burst cut), 3 underlines, 1 arrow, 1 frame, 6 balloons. Outside the bursts at most 4 on
  screen (1107 averaged 1-2). About one moving thing every second; the picture is never empty of cute for more than 2 s.
- **Where:** the outer 15-18 % band of the frame, the corners and empty walls / ceiling / floor. Never on a face (boxes
  take the whole head and hair, widened where the camera pans), never on a caption card or the big type.
- **Burst list per key moment (1107):**

| Moment | Burst |
|---|---|
| Hook (question on the first shot) | big star-eyes face, sparkle, "?" doodle, 好酷! shout bubble, 2 twinkles |
| The craft's name (write-on) | sparkle + star above the word, a sparkle and a pink star as it writes, 2 twinkles, a dashed underline |
| A V sign (punch) | laughing face, V-hand sticker, star, sparkle, 耶! shout, star trail, underline |
| The wow (write-on) | heart-eyes face, 3 floating hearts, crayon squiggle under the word, 2 twinkles |
| The payoff (punch, 完成啦) | thumbs-up, confetti from both bottom corners, rainbow, 看! arrow at the craft, underline, twinkle |
| The group photos | bouncing camera doodle, star, sparkle, white flash sparkle + shutter on 耶, confetti in the blur bands, heart trail, 耶! shout |
| The goodbye | waving face, floating hearts, 6 balloons rising to the end |

## 5. Voice
- Host voice 3B: edge-tts zh-CN-XiaoyiNeural, +22 % rate, +25 Hz, +10 % volume (brand rule 2026-11-03).
- One line per shot, starting 0.15 s after its cut (0.1-0.25 s), 0.6-2.3 s long, ending at least 0.1 s before the next
  line; 25 lines in 52 s. Talk TO the viewer, one connected chatty thread with particles (啦 咯 哦 咧 耶 啊); say only
  what is on screen; never a name; never a claim the picture doesn't show.
- Label it as AI / synthetic content when it is uploaded (post.md Plan).

## 6. Sound
- **Music:** Blue Sky (Sergmusic, CC0, assets/blue-sky.mp3): 12 dB under the voice while it speaks, 5 dB under in the gaps
  (music.py --room), 1.5 s fade-in, 2.5 s fade-out, -14 LUFS, -1.5 dBTP.
- **Sticker sounds:** real CC0 pops / chimes / swishes / a shutter from the sfx library, each peaking on its sticker's
  first frame. Pop category -13 dB; cut stickers db -3, helpers -2..-4 (about 10-12 dB under the impact hits at -5),
  burst leaders +1 (about 7 dB under); twinkle chimes -8 (raise to -4 where the voice masks them); wipe swishes 0.
  One sound per group; trail pieces, second twinkles and confetti are silent. One quiet card pop per line (-15 dB),
  dropped where a sticker sound is within 0.35 s. Never a sound on a plain cut.
- **Clean ending:** the last word ends at least 0.4 s before the end; voice, music and effects fade over the last 0.8 s;
  the picture keeps its pull-back.
- **earshot:** about 90 % of the cues with an onset within 100 ms; music heard under the voice in every section.

## 7. Length
1107 ran 52 s. A review may run past the 45 s rule, as every children review has; say so in notes.md.
