---
description: After a project, the team writes down what worked and what to avoid, tagged for the teams it helps, so the next project is better
---
Run a retro on: $ARGUMENTS   (a task id, a folder in out/ or work/, or "today")

1. Read the brain: `mcp__memory__open_nodes` with names ["Brand rules", "Lessons"]. Read the board (`node hq/tasks.js list`) and the files of the work in question (notes.md, plan.md, post.md, the review results).
2. Find what really happened: what the owner approved straight away, what they corrected (and how), what the brand-checker or code-reviewer flagged, and any numbers from inbox/stats/.
3. Ask the head of every team that worked on it for its "Lessons for the office" (one sub-agent call per head, all in one message). Merge their lines with yours.
4. Keep at most five lessons in total. Each must be specific, checkable and backed by what happened. Drop anything vague, anything already in "Lessons" or "Brand rules", and anything that would change the meaning of the owner's words. Use the exact form `[<Team> · for <Team>, <Team>] <lesson>`; "for" names the other teams that should use it.
5. Save each one with `mcp__memory__add_observations` on "Lessons" (create the entity with `mcp__memory__create_entities` if it is missing).
6. If a lesson means a skill or an agent file should change, write the proposed diff to `work/office/retro-<date>.md` and ask the owner for OK before editing; do not edit skills or agents on your own.
7. Reply with the saved lessons, one line each, and which teams they will reach. The office shows them as tips the agents share over coffee.
