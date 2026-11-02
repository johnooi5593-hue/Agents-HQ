---
description: Save a rule to the shared brain AND write it into every skill it affects, so every agent and edit style follows it from now on
---
Save this as a brand rule: $ARGUMENTS

1. If no rule was given, read the current rules with `mcp__memory__open_nodes` (names ["Brand rules"]), list them numbered, and stop.
2. Rewrite the rule as one short, checkable sentence (what, the exact value, for example a color code or a word count).
3. If it contradicts an existing rule, say which one and ask whether to replace it (`mcp__memory__delete_observations` for the old one) before saving.
4. Save it with `mcp__memory__add_observations` on "Brand rules" (a channel's rule on "<name> · Brand rules").
5. **Into the skills.** Find every skill, script default and agent file the rule touches: `Grep` `.claude/skills/` and
   `.claude/agents/` for the setting (a number like `--duck 21`, a word like `B-roll`, the step it belongs to). For an edit
   rule that means every edit style: caption-card, gold-stack, yellow-serif, poster-kinetic, neon-glow, reel, sermon-moments
   and the shared scripts (sfx `music.py`, `place.py`, yellow-serif `tighten.py`). Change the default where one script
   serves them all, otherwise add the rule as one line, dated, in the step it belongs to, and remove any old value it replaces.
6. **Show, then save.** Make the edits in a copy first and show the owner the diff (file, old line, new line). Write them to
   `.claude/` only after the owner's OK. If the owner says no, the rule stays in the brain only.
7. Confirm in a few lines: the rule as saved, and each skill or script changed.
