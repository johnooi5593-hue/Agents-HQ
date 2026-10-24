---
description: Save a brand rule to the shared brain so every agent follows it from now on
---
Save this as a brand rule: $ARGUMENTS

1. If no rule was given, read the current rules with `mcp__memory__open_nodes` (names ["Brand rules"]), list them numbered, and stop.
2. Rewrite the rule as one short, checkable sentence (what, the exact value, for example a color code or a word count).
3. If it contradicts an existing rule, say which one and ask whether to replace it (`mcp__memory__delete_observations` for the old one) before saving.
4. Save it with `mcp__memory__add_observations` on "Brand rules" and confirm in one line: the rule as saved, and which skills it affects.
