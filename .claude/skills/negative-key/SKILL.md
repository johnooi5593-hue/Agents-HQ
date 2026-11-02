---
name: negative-key
description: Negative Key (负片字) - the key word drawn as a photo negative of the picture behind it, over a soft dark shadow (sample C, owner-approved 2026-11-02). Use only when the owner asks for "negative", "负片字", "negative key word" or "invert the key word", on any channel; every style keeps its own key-word colour otherwise. It works on top of the caption styles (Gold Stack, Caption Card, Yellow Serif, Poster Kinetic, Neon Glow, reel) and the covers (pixel, Codex). Not for Orbit Pop, whose key stays lime.
---

# Negative Key (负片字)

An add-on, not a style: the edit is planned and rendered in its own style as usual, and only the key word changes.

## The look

The key word's letters show the picture behind them inverted; every other word keeps its style. A soft dark shadow
(the blurred letters) sits under the word so it separates from the picture:

```
out = rgb * (1 - shadow)              # shadow = blurred letter shape x 0.45, blur 10 px
out = out * (1 - a) + (255 - rgb) * a # a = the letter shape; rgb = the picture before the text went on
```

## Turn it on

| Style | Switch | What turns negative |
|---|---|---|
| Gold Stack | plan `"key_style": "negative"` (normal: `"gold"` or left out) | every gold item: the `key`, title key, slam `b`, numbers and write-on digits, a gold spin word, the word behind; no gold glow |
| Caption Card | plan `"key_style": "negative"` (normal: `"yellow"`) | the card's key word (no yellow bar) and the hook / breathe key row (its `color` is unused) |
| Yellow Serif | plan `"key_style": "negative"` (normal: `"yellow"`) | inline key words, the burst phrase, the darken column, a fullscreen `head` big letter; `edit.ass` still marks them `#FBC238` |
| Poster Kinetic | plan `"key_style": "negative"` (normal: `"colour"`) | the hero word's face, on a neutral dark extrusion (#101010) with a thin light outline (`NEG_EDGE`) |
| Neon Glow | plan `"key_style": "negative"` (normal: `"neon"`) | the neon word and the gold key word of the kinetic lines; the dark rim, flicker and switch-on stay, no glow, shine, streak or flare |
| reel | `captions.py --key-style negative` (normal: `color`) | the word being spoken; `--color` is unused |
| Cover (pixel) | `thumbnail.py --key negative` (normal: `color`) | the `--accent` word |

Leave the switch out and every style renders exactly as before.

## Trade-offs (tell the owner when they show)

- The colour of a negative is the opposite colour: tan on a blue shirt, near-white over dark areas, dark red on a cyan card.
  A busy or mid-grey patch reads worst; move the word or its zone.
- Gold Stack's non-text gold accents (title bar, question swipe, pen trail, flash frame, light leak) stay gold.
- Poster Kinetic adds a thin light outline round the hero face, so a dark negative still separates from the extrusion.

## Covers

Covers are made with pixel `--key negative`. For Codex thumbnails the codex-graphic-designer asks Codex for the title's
key word in a photo-negative look only when the owner requested the negative key word; otherwise the template's colours stay.
