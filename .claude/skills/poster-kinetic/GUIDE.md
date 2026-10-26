# Poster Kinetic · 大字海报动态 (guide v1, sermon edition)

Source: the owner-approved PDF "Semenyih 店屋短片 字体与特效指南 v1" (2026-10-26), measured frame by frame from a property
listing reel, saved at `C:\Users\John Ooi\Documents\Style Guides\semenyih-shoplot-reel\guideline.pdf`. The approval came
with one instruction: make it suitable for **sermon highlights** and able to enhance them more. Values measured from the
reel are marked (measured); sermon adaptations are marked (sermon). The reel belongs to another creator; only its style
is used, never its footage, data card or text.

> 一屏一点，大字落在说出的那个词上。 One point per screen; the big word lands on the word as it is spoken.

## 1. What the style is
A checklist of points. Each point gets **one giant hero word** and 0-2 small white lead-in words; no caption boxes;
legibility comes from very heavy type, a short dark extrusion and (when a matte exists) the speaker standing in front of
the text. Almost every shot change is a motion-blurred transition.

(sermon) A sermon is spoken teaching, often watched with the sound off, so **every line still gets a readable caption**
(the yellow-serif rule "one caption set" holds: a line is either a caption or a hero composition, never both). Heroes
go on the **few lines that carry the point**: about one every 4-8 s, at most 45% of lines.

## 2. Type (guide p.4-5; the reel's own fonts cannot be identified: closest installed matches)
| Role | Font (fallbacks) | Size at 1080 wide |
|---|---|---|
| Chinese hero, upright | Alibaba PuHuiTi Heavy (思源黑体 Heavy, Noto Sans SC 900) | 262 px (288 for 1-3 characters), down to 170 |
| Chinese hero, slanted | 优设标题黑 YouSheBiaoTiHei (PuHuiTi Heavy + 10° slant) | same |
| Latin hero | Arial Black upright / Alibaba Sans Heavy Italic slanted | x1.06 so capitals match the Chinese |
| Title (Latin only) | Arial Narrow Bold, metal fill | 200 px |
| Lead-in / tail | PuHuiTi Heavy, white | 100 px (to 72) |
| Caption (sermon) | PuHuiTi Heavy, white, key words 1.08x | 78 px (to 64), two rows max |
| Scripture card body (sermon) | PuHuiTi Bold, #1C2230 | 62 px (to 44) |

Heavy and Black weights only. Short phrases, broken by meaning. (sermon) PuHuiTi and 优设标题黑 have no 祂, 袮 or
Traditional characters; those characters are drawn with 思源黑体 Heavy automatically (never empty boxes).

## 3. Colour = meaning (guide p.6, measured hex; meanings for sermons)
| Name | Hex | Use |
|---|---|---|
| white | #FCFCFA | base, lead-ins, captions |
| gold | #F8EA98 | grace, hope, promise, blessing, God's love (default key colour) |
| cream | #FBF4CA | scripture, quotes |
| peach | #F8CCA2 | people, love, family, warmth |
| lime | #ACD744 | life, growth, action, a way forward |
| ice | #C5FFFC | the Holy Spirit, peace, new, invitation |
| red | #90132F (light #F0657A) | sin, warning, contrast, what is NOT; at most twice a clip |
| navy | #253C69 (light #8FB4FF) | numbers and facts on a bright picture |
| blue | #0A64BC (light #5FA8FF) | welcome, church, a section title |
Extrusion #1B1813 (measured). At most 3 text colours on screen. (sermon) render.py measures the picture behind each
hero; a dark colour on a dark picture switches to its light variant, a light word on a bright picture is flagged.

## 4. Motion at 30 fps (guide p.7-14, frame counts measured, curves estimated)
| Effect | Use | Numbers |
|---|---|---|
| zoom | punchline, opening word | 1.10 -> 1.00 over 8 frames, blur 18 -> 0 in 3 |
| whip | a key word, a turn | from left/right (alternating) or top, 3 frames with motion blur, then 40 px drift over 16 frames |
| drop | a contrast, a short title | letters 1 frame apart, each 3 frames from -36 px, 1.12x, blur 14, recentred while arriving |
| stack | 2-4 characters that land like a stamp | vertical, 5 frames apart, each 2 frames ghost -> solid |
| caption | every other line | each word ghosts in over 2 frames as spoken; the old line blurs into the next over 4 frames |
| exit | hero | blur out 6 frames; swap (drop 60 px, 3 frames) when the next hero lands in the same zone |
| flash | section start | zoom-blur white flash, 12 frames |
| whip transition | quick turn | horizontal blur, 5 frames |
| card (sermon) | a verse the preacher reads | flies in 12 frames: 0.55x, turned -35°, blur 10 -> rests turned -9°/4°, gentle sway |
| title (sermon) | sermon title + preacher | metal letters drop in 2 frames apart; name appears 6 frames later |
| punch-in (sermon) | while a hero is up | picture scales 1.00 -> 1.045, eases back in 0.35 s |
Sync: a hero lands 2 frames before its word (guide: 0-4 frames; measured median 0.07 s). Hold at least 1 s after landing.

## 5. Layout (guide p.18)
1080x1920. Text inside x 90-990, y 120-1400; nothing below 1400 (platform captions and buttons). Hero zones (centre
y): top 300 (above the head in a full-figure shot), middle 820, low 1060 (default: over the body / podium). Captions
end at y 1372. Never over the face: choose the zone after looking at the frames. Behind-speaker heroes (matte) go
top or middle so the head overlaps them.

## 6. Do / don't
Do: one point per screen; hero 60-87% of the width; white lead-in small and first, coloured hero big and second;
colour by meaning; move with the picture; transitions at section starts (2-4 per clip); keep 2-3 s clean at the end.
Don't: change the words, numbers, negations or conditions (a hero keeps its 不 / 没有: 不符合, not 符合); put text over
the face or below y 1400; use red as decoration; stack effects on one word; make every line a hero; invent scripture
references (a card shows only words actually spoken; a reference only if the preacher names it or the slide shows it).

## 7. Delivery checklist
- [ ] fonts found (pfonts.py), no empty boxes; heroes >= 170 px; at most 3 colours on screen
- [ ] original words kept; every hero and card text is an exact part of the speech; references checked
- [ ] nothing over the face or below 1400; heroes held >= 1 s; no warning left unexplained
- [ ] picture, captions and sound are one version; edit.srt and plan.json beside edit.mp4; phone copy under 28 MiB
- [ ] the owner sees the plan or a preview before posting; each finished video gets its own OK
