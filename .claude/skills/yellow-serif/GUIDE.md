# Yellow Serif Kinetic · 黄字重点衬线动态字幕 (guide v1)

The owner's style guide (7-page PDF, "v1 草案 · 基于你提供的参考 · 等待本版本 OK"), summarised faithfully in English and Chinese. The reference photos belong to other creators and are not copied into this repository; they are described in words below. The `yellow-serif` skill implements this guide.

> 普通句子厚重清楚，关键字暖黄醒目；用打字、弹出、爆点、扫光与闪现，把讲话的重点带出来。
> Ordinary sentences thick and clear, key words warm yellow and eye-catching; typing, pop, burst, shine and flash bring out the point of what is said.

How to use it (这份指南怎样使用): an optional style template. First fix the topic, the original lines and the effect of every sentence on the planning page, then make the full video. Once this guide is approved it can be reused; every finished video still goes to the owner for its own check.

## 1. Type (核心字感)

- **Main captions**: a heavy / bold Song face (偏粗宋体／标宋感): full glyphs, stroke contrast, clear serifs.
- **Inline emphasis** (行内重点): the same font, turned yellow and slightly larger, **1.0-1.15x**, keeping the reading rhythm of the sentence.
- **Standalone key phrases** (独立重点短语): only a few key phrases become big hand-written / brush words (书写感大字), **1.5-2.1x**.
- The reference fonts were not identified; trial-set before production and **record the final font files and their licences** (登记最终字体文件与使用权限).
  This skill uses Noto Serif SC at its heaviest weight (Black) and Ma Shan Zheng (马善政) for brush phrases, both SIL Open Font License; see `scripts/fonts/FONTS.md`.

## 2. Colour (配色)

| Use | Colour |
|---|---|
| Normal captions 普通字幕 | `#FFFFFF` |
| Key yellow 拟定重点黄 | `#FBC238` (sampled #F7BE35 to #FCC030 from the screenshots; unified to warm gold #FBC238) |
| Near-black background 近黑背景 | `#08090B` |
| Background sentence behind a big brush phrase | dimmed white / grey |

Phone status bars, recording dots, like counts and app menus in the photos are not part of the design.

## 3. Three compositions (三种构图), optional, not all at once

1. **Full-screen text** (全屏文字): text on near-black with a subtle perspective grid floor. Photo 5: two centred lines, "不拼文采" in white over "只拼结构" in yellow. Photo 7: a big yellow serif Latin letter "R", "reason" in white under it, "（理由）" smaller, then two lines "你要给理由" white and "不是瞎说" yellow.
2. **Person darkened, big words** (人物压暗加重点). Photo 6: the speaker darkened, "两种结构" stacked vertically in very large yellow serif characters down the middle, a small grey caption line low on the frame.
3. **Torn-paper frame** (撕纸边框). Photo 1: the video sits in a torn white-paper frame in the upper part of a black frame with a faint grid; below it two caption lines in heavy white serif, "很多人拍短视频 / 像是在念PPT" with "念PPT" in yellow.

Photo 2 (两种字体层次): a big grey serif sentence ("逻辑是对的 / 内容也没有问题") sits behind a rough yellow brush phrase "一盘散沙" laid over it: the grey sentence steps back, the brush phrase lands on top.

## 4. Five motions at 30 fps (starting points, to preview with real speech)

| # | Motion | For | Timing and shape |
|---|---|---|---|
| 01 | **打字 typing** | explanation, setup | reveal by Chinese character or semantic word group; try 2-3 frames per character; a group is fully read in 0.25-0.60 s; long sentences appear by word group; **always follows the speech** |
| 02 | **轻弹 pop** | ordinary key words, numbers | 0.18-0.28 s with a fade in: scale 85% -> 108% -> 100%, then hold steady. Never make every character of a passage jump |
| 03 | **爆点放大 burst** | key conclusion or contrast | 0.22-0.35 s, big first then settle (冲击 impact -> 收住 settle -> 落稳 steady); optional very short shake or directional blur. Only a few main bursts; leave reading time after it lands |
| 04 | **shine 扫光** | a key word that needs one more beat | after the text is readable, a narrow bright band sweeps once inside the glyphs only, 0.25-0.45 s, then back to the unified yellow; no leftover highlight over the text. Can follow a pop |
| 05 | **闪现 flash** | short cues, section landings | appears and settles in 0.10-0.18 s, may have a brief light edge; never flicker repeatedly |

Per sentence choose **one main entrance motion**, and add one shine only when needed. Example (一句话的效果安排示例): explanation = white bold serif typing; core word = turns yellow and pops; key conclusion = one standalone big burst; shine = after it is readable.

## 5. Layout at 1080 x 1920 (字幕起始设置)

- Normal captions **74-96 px**, adjusted to the glyphs and picture; split by meaning; usually **at most two lines**.
- Inline key words **1.0-1.15x**; standalone big words **1.5-2.1x** to start.
- Keep captions clear of the face and gestures; side margins about **8%**, bottom margin about **15%**; then preview for the actual platform.

## 6. Planning page (企划页逐句记录)

Watch the whole long video, choose **two different topics** and the original lines worth keeping (about **45-60 s** each, the current long-talk mode), then on the planning page choose fonts, colours, layout and each sentence's motion. One row per sentence:

| 讲话原句 original line | 重点词 key words | 主要动作 main motion | 画面与备注 picture and notes |
|---|---|---|---|
| a real explanation line | content key word | typing or pop | keep the person, captions clear of the face |
| a real core conclusion | conclusion phrase | burst | full screen or darkened person, by content |
| a real landing line | the needed phrase | steady or shine | keep the tone, settle the picture |

Real projects record the source timestamps, the caption timing after the cut, and the reason for each grouping. Video and Relay share one timeline with **one caption set**, and the editable caption and effect source files are kept.

## 7. Reference boundaries and delivery checklist (参考边界与交付检查)

The photos support judgements of glyphs, colour, hierarchy and composition, not exact animation timing. The attached 26 s 1280x720 30 fps MP4 is mainly defocus, light-leak, colour-block and bright-flash transitions, with another creator's watermark and a platform end card; it shows no caption animation. It is **not copied**: this skill makes its light leaks procedurally (soft red/orange/yellow/white gradients and bokeh, screen-blended), or uses a clean overlay clip the owner provides in `assets/overlays/`. The audio was not reviewed and is not an approved sound library.

Before delivery (交付前逐项检查):

- [ ] Heavy serif look, one unified key yellow, font files and licences clear. 字形有厚重衬线感，重点黄统一，字体文件与使用权限明确。
- [ ] Original words, negations and conditions kept; emphasis never changes the meaning. 保留原话、否定词和条件；强调词不改变讲话的意思。
- [ ] Readable on a phone: no missing glyphs, overflow, face cover or two caption sets at once. 手机上清楚可读，无缺字、溢出、遮脸或两套字幕叠加。
- [ ] Entry, hold and exit aligned with the real speech; text still clear after every effect. 进入、停留、退出跟真实讲话对齐；动效结束后字仍清楚。
- [ ] Picture, captions and sound are the same version; editable files complete. 画面、字幕、声音属于同一版本；可编辑文件齐全。
- [ ] Independent review before it goes to the owner; this guide and every finished video each get their own OK. 独立 Review 后交你检查；本指南和每支成片分别记录 OK。

Source: the owner's photos 1-7 and the 26 s MP4, used only as style evidence; finished videos use the owner's own footage. The guide does not apply automatically to every brand.
