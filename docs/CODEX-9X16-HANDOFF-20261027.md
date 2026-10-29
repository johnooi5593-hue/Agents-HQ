# Codex HQ handoff: 9:16 thumbnails fail in the image engine (2026-10-27)

From Claude HQ (`D:\Agents HQ`). The owner asked for this to go to Codex because the fix is in Codex's engine (`D:\AI OFFICE`). Please don't edit `D:\Agents HQ`. The HQ side needs no change: it already sends 1080×1920 requests in the existing schema.

## What fails

3:4 works. Two real Pong+Gospel jobs at **1080×1440** were delivered with four options each; the native images were 1086×1448.

9:16 fails every time. Two **1080×1920** jobs for the same video failed in about a minute, before any option was saved:

| Request id | Status | Error |
|---|---|---|
| `f63e1431db894e68ae3665a9d77a51a8` | failed | ChatGPT returned an undersized image or unexpected aspect ratio. No stretched replacement is claimed. |
| `2ecf3282feb3462594846e8ee60f75d9` | failed (deliberate retry) | same |

Evidence: `D:\AI OFFICE\.studio\sermon-design-runtime\.studio\thumbnail-design\jobs\<id>\job.json` (the `output\` folder is empty). Template: `Pong+Gospel golden portrait 9x16 20261027` (1080×1920, sha256 `c1ebfe1c…6404`).

The check that fires is `studio/sermon-design-codex.mjs:276`: the ratio must be within ±0.04 of the target. 9:16 is 0.5625. My guess, which I haven't verified: the built-in ChatGPT image model's tallest portrait is about 2:3 (0.667), which is outside that tolerance. The native size isn't recorded on failure, so please confirm it first.

## What to build

1. **Log first.** On a ratio or size failure, record the returned native width×height in `job.json`, so the cause can be seen.
2. **Native 9:16 extension.** For 1080×1920 requests:
   - generate at the tallest portrait size the model actually supports;
   - extend the real scene at the top and bottom with the same signed-in image route, using an image edit that continues the background and keeps the person and text untouched, until the ratio is 9:16;
   - resize to exactly 1080×1920.
   - Prompt for a vertical layout with headroom, so the presenter's face, glasses and the title sit inside a safe area and no extension crosses them.
3. **Keep every existing guard:**
   - no stretching, no blurred or solid padding bars, no collage;
   - four separate PNGs, with real image-generation receipts for every step;
   - no silent paid API or other provider.
   - If extension can't be done honestly, fail with a clear message, as it does now.
4. **Provenance:** for each option, add the native size, the extension steps and their receipts.

## Done when

- A real 9:16 job for `out/pong-gospel-1107-marriage-stay-together` (video `edit.mp4`, the 9:16 template, title 婚姻能长久，是因为愿意一起坚持, subtitle 累的时候，不要轻易放弃。) delivers four 1080×1920 PNGs. Each must have the exact Chinese title, the same real presenter, and no stretched face, bars or blur.
- 3:4 and 16:9 jobs still pass, and the existing engine tests pass with new tests for the 9:16 path.
- You report back what changed, the test results, and the request id of the successful 9:16 job. Claude HQ will then verify it and run 1108.

To retest from HQ, open `http://127.0.0.1:7331/thumbnail-studio.html?folder=out%2Fpong-gospel-1107-marriage-stay-together&taskId=t10` and use **重新提交当前设置** (resubmit the current settings) on the failed request, with the settings above.
