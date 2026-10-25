---
description: The weekly coffee chat: team heads cross-review each other's lessons and propose how the whole office improves
---
Hold the coffee chat. $ARGUMENTS

1. Read the brain: `mcp__memory__open_nodes` with names ["Company", "Brand rules", "Lessons", "Ideas"]. Add a board task: `node hq/tasks.js add "Coffee chat" --team "The Brain"` and move it to doing.
2. Pair the teams so every head reads the lessons of two other teams (for example Creative ↔ Scripts, Research ↔ Social, Analytics ↔ Shop, Dev ↔ Inbox, then rotate). Start all eight heads in one message, each with the lessons of its two partner teams and this brief: "Which of these lessons should your team adopt, and how exactly? Which one do you disagree with, and why? One improvement you suggest for the partner team." Each head answers in at most ten lines.
3. Merge the answers into `work/office/coffee-chat-<date>.md`: lessons adopted by which team (save each adoption as a new lesson `[<Adopting team> · for <Source team>] adopted: <lesson>` with `mcp__memory__add_observations` on "Lessons"), disagreements to settle, and proposed changes to skills or agent files written as diffs.
4. Retire stale lessons: if two lessons contradict, or one was replaced by a brand rule, list them in the file with a suggestion; delete observations only after the owner says OK.
5. Move the task to review. Reply with: what each team adopted (one line each), the open disagreements, and the proposed skill or agent changes waiting for the owner's OK.
