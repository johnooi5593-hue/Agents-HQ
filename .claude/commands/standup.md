---
description: HQ status: what is waiting in inbox, what is in out/ waiting for approval, what the brain knows
---
Give the owner a standup for Agents HQ.

1. Run `python3 hq/status.py` and read its JSON line.
2. Read the brain: `mcp__memory__open_nodes` with names ["Brand rules", "Lessons", "Ideas"] (missing entities are fine).
3. Report, short:
   - **Inbox**: clips waiting, radar files, stats files.
   - **Waiting for approval**: every folder in `out/` with what it contains (edit, cover, post copy, script, shortlist, report).
   - **Done**: how many clips have been edited.
   - **Brain**: the number of brand rules, the latest 3 lessons, the latest 3 ideas.
   - **Suggested next move**: one line (for example "3 clips in inbox: run /edit-clips").

$ARGUMENTS
