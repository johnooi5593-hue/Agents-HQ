---
description: Route any task through the office: the right team, its head's plan, workers in parallel, review, report
---
Task from the owner: $ARGUMENTS

1. Read the brain (`mcp__memory__open_nodes` with names ["Company", "Brand rules"]). If no task was given, ask for one in a single line and stop.
2. Decide the team. Put it on the board: `node hq/tasks.js add "<short title>" --team "<Team>"`, then `node hq/tasks.js move <id> doing`.
3. Small and single-skill: start that worker directly. Otherwise ask the team head for its plan pass, then start every worker it named in one message, in parallel, each with its brief and the folder `work/<team>/<task-slug>/`.
4. Hand the results to the head for its merge and review pass (creative work also to `brand-checker`, code to `code-reviewer`). Fix what is flagged, check again.
5. `node hq/tasks.js move <id> review`. Report: what was done, the file paths, what needs a decision. End with "Nothing is published. Reply OK to approve."
