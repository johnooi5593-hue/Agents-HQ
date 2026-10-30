# Caption Card · 字卡动效 (guide v1, sermon edition + v2 motion)

Source: the owner-approved 16-page guide "字卡广告短片 文字动画与配色指南 v1" (2026-10-27), measured frame by frame from a
screen recording of an Instagram ad (XiXi Trading). PDF and evidence: `C:\Users\John Ooi\Documents\Style Guides\xixi-trading-reel\`.
Only the style is used, never the ad's footage, claims, amounts, disclaimer or brand.
v2 (below) is the owner-approved look of Pong+Gospel 11/14 (2026-10-30): `work/creative/pong-1114-caption-card/v2/edit-sfx.mp4`.

## Colours (measured)
| Use | Hex |
|---|---|
| Card box / card text | #63E6DA / #1D3AF5 (darker bottom #1530D8) |
| Hook rows / hook key | #E9E7E4 / #FAF536 |
| Number gradient | #8CD941 -> #689634 |
| Write-on gradient, glow | #86DD46 -> #479745, #6BBA46 |
| Punch gradient, shadow | #E7E634 -> #9BA228, #192113 |
| v2 key word: bar / word | #FFE45C / #0A1A9C -> #06127A |
Sermon additions in the renderer: gold #FFE17A -> #D99A1E, ice (breathe), cyan, rose, white.

## Layout at 1080 x 1920 (measured)
Card centre y 0.51 (the chest), box 112 px with the text taller than it. Hook rows around y 0.43-0.58. Number ink 0.45-0.47 of the
height, centred. Write-on y 0.5. Punch y 0.45, 86 % of the width. Breathe rows centred on y 0.5 (key row 205 px, others 128 px).
Everything centred; nothing below y 1420.

## The five layers (why it pops)
Heavy face; top-light gradient (35-45 % darker at the bottom); dark soft shadow (blur 16-26, down 8-14 px); outer glow in the
same colour family; the picture blurred and dimmed about 30 % while big type is up (55 % of that under a punch, whose punch-in
carries it; 80 % under breathe).

## Motion principles (measured curves)
Fast in, slow stop (ease-out); overshoot then settle (punch 35 %, hook ghost 27 %); stagger (2 frames per character or word);
motion blur only while moving; swell / brighten before the exit (number +10 %); hold at least 0.6 s after landing. 30 fps.

## v2 motion (from the approved 1114 edit; frames at 30 fps)
**Card entrances** (each line its own; without `anim` they take turns so neighbours never match):
| anim | move |
|---|---|
| rise | up from +70 px, overshoot -6, settle in 6 f; unblur 10 -> 0 in 4 f; box 0.85 -> 1.0 wide |
| slide | in from 260 px left or right, 14 px overshoot, settle in 7 f; motion blur 60 -> 0 in 4 f |
| slam | scale 1.55 -> 0.95 -> 1.02 -> 1.0 in 7 f; blur 9 -> 0 in 3 f |
| stagger | box grows 0 -> 1.04 -> 1.0 in 6 f, then the characters drop from -46 px, 0.6 -> 1.12 -> 1.0 in 5 f, 1-1.5 f apart |
| wipe | the box wipes in from the left in 5 f with a light streak on its edge; each character pops 0.7 -> 1.1 -> 1.0 as it passes |
| cut | a hard cut (the v1 card) |
A line's follow-on cards use the same entrance 1.7x faster. The line's last card swells out: 1.05x and 1.18 brightness, then
0.9x, fading and blurring (8) in 4 f. Cards never overlap; one caption set at a time.

**Key word** (`key`): when the word is spoken (never before its card has landed), a #FFE45C bar wipes in under it in 3 f, the
word turns deep blue and pops 1.0 -> 1.22 -> 1.0 in 5 f. Two keys on a card each keep their own time. A key spanning two cards
gets a bar on both parts.

**Breathe**: characters 2.5 f apart, each fading in (0.1 -> 1), rising 26 px, unblurring 12 -> 0 and settling 1.06 -> 1.0 in
8 f; the group grows 1.2 % a second; it leaves by dissolving up 30 px with blur 14.

**Camera** (zoomed around plan `camera.face`; 1.0 = the edit's framing; never under 1.0 or over 1.35):
- A new piece starts at every cut, every big-type entry except a punch (the picture is blurred there, so the restart is
  unseen) and every transition, snapped to the frame grid. The pieces take turns: push, push, drift right, push, drift left.
  Push: 1.0 -> 1 + min(0.07, 0.025 + 0.008 x the piece's seconds). Drift: at 1.04, 36 px across. Pieces under 1.2 s only push.
- Sway (`sway` lines or `camera.sway` windows): handheld, x 11 + 5 px, y 7 + 3 px, +2 % zoom, eased in and out over 0.35 s.
- Punch line: 1.0 -> 1.25 (`punch_scale`) in 3 f, starting 3 f before the line; it eases back out over 8 f after the line, or
  ends on a cut / flash inside it (the cut hides the snap).
- `punch_in` on a line: 1.0 -> x1.015 -> x in 6 f at its start, held to the next piece.
- Pull-back: from the last line to the end, whatever the zoom is eases back to 1.0 (`pull_back.to`).
- Full-resolution footage (`hr` / `--hr`) gives the zooms real pixels: at 1114's 1.30x peak the picture is enlarged 1.12x from
  1728x3072 footage, against 1.30x from the 1080x1920 edit.

**Grade arc** (`grade`): eased between the points, g -1 cool and dim ... +1 warm, with a light vignette. The message decides
it: cool through the problem, neutral at the turn, warm at the promise.

**Light**: `flash` = a 4-frame white (one frame before the cut, the peak on it, two after), then a warm leak (0.9 s, strength 0.55); `leak` on a line = a soft leak (1.5 s, 0.38);
`light` = a warm bloom that ramps to 0.16 over 3 s, plus floating light particles kept off the face, to the end.

**Accents**: `rings` two light rings open as the line lands; `orbs` two soft lights drift together; `halo` a soft gold glow
behind the line.

## Rules
Cards for every line, 2-6 characters, each line animated and its key word marked. About one big moment every 8 s in v2
(1114: 8 in 65 s; 3-4 a minute in classic), each with a why, at least 3 s apart. The words stay exactly as spoken. Never over the face. One caption set at a time (cards wait while big type is
up).
