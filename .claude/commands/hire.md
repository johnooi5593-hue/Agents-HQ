---
description: Add a new agent to the office: write its file, put it in a team, update the org chart
---
Hire: $ARGUMENTS   (format: `<name>: <job>`, optionally `in <Team>`)

1. If the name or job is missing, ask in one line and stop. Pick the team (or create a new one if the owner names one). Decide head or worker (new agents are workers unless the owner says otherwise).
2. Write `.claude/agents/<name>.md` with frontmatter `name`, `description` (say when to use it, that is how you pick it), `team`, `role`, `tools` (only what it needs), `model` (sonnet for a worker, opus for a head), `color`, and a body with numbered steps that end in a file under `work/<team>/<task>/` and a short reply. Editing `.claude/` asks the owner first; that is intended.
3. Add the row to the table in `docs/office.md`.
4. Reply with the file path and one line on when you'll use it. The office picks the new agent up on its own.
