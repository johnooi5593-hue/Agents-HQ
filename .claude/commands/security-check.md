---
description: Route a security review of a change, file, setting, message or link through the Security team: plan, workers in parallel, ranked report, verdict
---
Security check: $ARGUMENTS   (a diff or "the current diff", a file or folder, a message in inbox/messages/, a link, a setting, a new tool or MCP server, or "the HQ app")

1. Read the brain (`mcp__memory__open_nodes` with names ["Company", "Brand rules", "Lessons"]). If nothing was given, check the current diff (`git diff`) and anything new in `inbox/messages/` and `inbox/radar/`.
2. Put it on the board: `node hq/tasks.js add "Security check: <short title>" --team "Security"`, then `node hq/tasks.js move <id> doing`.
3. Ask `security-lead` for its plan pass (folder `work/security/<task-slug>/`). Start every worker it named in one message, in parallel, each with its brief:
   - `security-auditor` for code and config (a diff, `hq/server.py`, a skill script, `.claude/settings.json`);
   - `access-guardian` for permissions, secrets, accounts, ports and phone access;
   - `threat-scout` for messages, comments, links, forms and footage names before any other team acts on them.
   A single message or link with nothing else: start `threat-scout` alone, no plan pass.
4. Hand the workers' files back to `security-lead` for its judge pass: one ranked report with the verdict `SAFE`, `FIX FIRST: <what, who>` or `STOP: <why>`.
5. `FIX FIRST`: route the fix to the Dev team (`engineering-lead` → `backend-dev` / `frontend-dev`), then `security-auditor` reads the new diff once more before it is reported as done. `STOP`: nothing else runs on that item until the owner answers. Never read `.hq-accounts.json`, `.env` or `.hq-push.json`; never change `.claude/settings.json` or an agent file without the owner's OK (show the diff first).
6. `node hq/tasks.js move <id> review`. Report in plain words: the verdict first, then the top findings (where, what an attacker could do, the fix), the file paths, and what needs the owner's decision. End with "Nothing is changed, published or sent without your OK."
