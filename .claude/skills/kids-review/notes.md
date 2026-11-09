# kids-review: decisions (2026-11-08, board task t201)

The owner asked: "Save this as new skill for editing this kind of review", as the slash command /kids-review. Built from
the 1107 Children review (work/creative/1107-children/, owner "Niceee!" on v3; v4 = the neutral grade, task t200). No
questions were asked; these are the decisions.

## What was generalised, and how
- **No 1107 paths in the scripts.** Every script takes the source folder, the work folder, the output and the size as
  arguments, and reads the video's own data (shots.json, lines.json, plan.json, cute.json, layout16.json, blur*.json,
  grade-fix.json, stickers.json) from its work folder. The 1107 values live only in templates/ as the worked example.
- **build.py** merges the 9:16 build.py and the 16:9 build16.py (`--size`). A shot's `src` matches the exact file name,
  the DJI short id (`_0636_D`), the end of the stem, or any unique part of the name. `--to` builds a quick part. The
  1107 pre-grade (eq gamma 1.12, contrast 1.05, saturation 1.18) stays the default so the look matches; `--eq null` turns
  it off if a new venue's footage looks too saturated after grade.py.
- **vo.py** reads the voice script (templates/lines.json) instead of a table in the code, and speaks a line again only when
  its text or the voice changed (NN.txt), so a one-line fix doesn't re-speak 25 lines. `--reuse` keeps every NN.wav.
- **One voice script for everything per line** (templates/lines.json): the host's text, the shot it plays over, its words
  (`seg`, for regroup_words.py) and its caption-plan fields (key, big moments). makeplan.py and regroup_words.py read it,
  so nothing per-video is left in code.
- **regroup_words.py**: `seg` from the script first, then jieba (installed on this PC) with a particle / 的 / 们 clean-up,
  else it stops and lists the lines. On 1107 without `seg`, jieba gave usable words on most lines but split a few badly
  (做好 可爱哦, 手也): `seg` stays the way to do it, jieba is the fallback.
- **blur.py** = blur16.py for any size and frame rate; the 9:16 badge (an ffmpeg boxblur in v1) is now a blur916.json box.
- **sheet.py** = sheet16.py for any size, plus `--every`.
- **make_renderers.py** replaces the frozen renderer copies (cc916/, cc16/) and cute_patch.py / patch16.py: it builds both
  cute renderers from the caption-card skill's CURRENT render.py at run time. Every replacement must match exactly once
  or it stops loudly and writes nothing, so a caption-card change that touches a patched line can't slip through, and a
  change that doesn't flows in. Tested 2026-11-08: the two renderers it makes are code-identical to the 1107 v3/v4 copies
  (only the docstring line naming the patcher differs). The v2 un-patch path of cute_patch.py was dropped (always fresh copies).
- **cute.py** (the 1107 v3 file) now reads cute.json from the PLAN's folder first, so each video keeps its own settings;
  `--cute <file>` still wins. Nothing else in it changed.
- **stickers.py** is the 1107 v3 file (already one file after patch_v3.py); the splice note is gone, the header names the
  skill. Its HQ board path still resolves (the skill's scripts/ sits as deep as the 1107 scripts/).
- **build_stickers.py** is now templates/build_stickers.py, copied into each work folder: sections 0-5 (setup, cuts,
  bursts, motion graphics, avoid boxes, fit + write), the cut times read from shots.json, a `card_lines_from_plan()` first
  guess for the card boxes. Tested: with the 1107 tables it writes the same 112 stickers, 81 avoid boxes and sfx_adjust as
  1107's stickers.json (only some "what" labels are shorter).
- **grade.py** is the t200 v4 file (neutral look by default, `--look warm` = v3), copied after grade.before-v4.py existed
  and grade.py had changed (01:09). Its per-shot fixes moved out of the code into `--fix grade-fix.json`; the defaults
  hold none. If t200 changes grade.py again, the coordinator syncs the P / LOOKS dicts into this copy.
- **makeplan.py defaults = the 1107 v4 plan**: grade arc [[0, 0.03], [0.383 x dur, 0.05], [0.728 x dur, 0.08], [dur, 0.1]]
  and light bloom 0 (t200 set these in plan.json at 01:12). Tested: makeplan + regroup from the template give the
  1107 v4 plan.json line for line (only the "edition" label differs).
- **Music:** Blue Sky (CC0) copied into assets/ with its LICENCE.txt, so the skill doesn't depend on the children-combined folder.
- The scripts print UTF-8 (sys.stdout.reconfigure): the Windows console is cp1252 and the JSON lines carry Chinese.
- No slash-command file in .claude/commands/: the skill itself is /kids-review.

## Open
- Covers: pixel makes 9:16 and 16:9; the 3:4 cover is pixel on a 1080x1440 crop clip of the same frame (as 1101 / 1107 did).
- `sticker` positions for 16:9 still need a look on frames every time (the 1107 16:9 first guesses needed 6 fixes).
