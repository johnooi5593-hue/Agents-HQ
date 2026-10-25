---
description: The board: list tasks, add one, move one, remove one (the office shows the same board)
---
Board request: $ARGUMENTS

Use `node hq/tasks.js`:
- `node hq/tasks.js list` shows the board (todo, doing, review, done).
- `node hq/tasks.js add "<title>" --team "<Team>" [--agent <name>] [--note "<text>"]`
- `node hq/tasks.js move <id> todo|doing|review|done`
- `node hq/tasks.js note <id> "<text>"` and `node hq/tasks.js remove <id>`

With no arguments, show the board. Reply with the board as a short table.
