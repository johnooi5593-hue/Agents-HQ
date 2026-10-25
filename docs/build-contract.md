# Agents HQ app: build contract

The app is rebuilt to match Bekhruz AI's "Agent HQ" video exactly (see `docs/video-spec.md`). Several engineers build it in parallel, each owning files listed here. Everything crosses file boundaries only through the interfaces below. Do not edit a file you do not own; if you need something from another module, build against this contract and leave a `TODO(contract)` note in your own file.

## Files and owners

| File | Owner | Purpose |
|---|---|---|
| `hq/office3d.js` | scene | The Three.js scene: Brain, 8 rooms, walkways, wires, furniture, characters, sub-agent bay, camera, bloom, picking. Exposes `window.HQ_OFFICE`. |
| `hq/hud.js` + `hq/hud.css` | hud | Every HTML overlay: top bar, floating team cards, notifications, room label card, status chips, minimap, team panel, task board, calendar tab, brain tab, voice orb, Ask any agent, drop zones, approve/review actions. Owns `window.HQ` (data + stream) and the page's data refresh loop. |
| `hq/app.html` | hud | The page skeleton: `<div id="office3d">` for the scene, `<div id="hud">` for the overlay, script tags in the order listed below. Keep CSS in `hud.css`. |
| `hq/server.py` | backend | HTTP API (below), static files, login, running `claude -p`, uploads, approvals, the board, notifications, calendar, team metadata. |
| `hq/teams.json` | backend | Static team metadata (icons, colors, taglines, leads, tools, skills). The scene and the HUD read it through `/api/teams`. |
| `hq/tasks.js`, `hq/events.js`, `hq/status.py`, `hq/brain.js` | backend | Board CLI, hook feed, folder status, brain launcher (already exist; extend, don't rename). |

Script order in `app.html`: `vendor/three.min.js`, `vendor/three-examples/{CopyShader,LuminosityHighPassShader,EffectComposer,RenderPass,ShaderPass,UnrealBloomPass,RoundedBoxGeometry,CSS2DRenderer,OrbitControls}.js`, `hud.js`, `office3d.js`. `hud.js` must not assume the scene exists at load (call `window.HQ_OFFICE` only when defined); `office3d.js` reads `window.HQ` lazily each frame.

Static routes served by the backend: `/` (app.html, login-guarded), `/hud.js`, `/hud.css`, `/office3d.js`, `/vendor/<path>` (anything under `hq/vendor/`), `/login`, `/files/out/...`, `/files/approved/...`.

## Teams (fixed order, clockwise from the top)

| # | key | name | color (floor) | icon | tagline | lead agent |
|---|---|---|---|---|---|---|
| 1 | research | Research | `#3b82f6` blue | 🔍 (magnifier) | github radar · markets · trends | research-director |
| 2 | scripts | Scripts | `#d4a017` gold | ✏️ (pencil) | hooks · scripts · fact-check | script-writer |
| 3 | social | Social | `#d946ef` magenta | 💬 (speech bubble) | posts · calendar · replies | social-media-manager |
| 4 | creative | Creative | `#7c5cff` purple | ▶️ (play) | rough cuts · captions · thumbnails | creative-director |
| 5 | analytics | Analytics | `#14b8a6` teal | 📊 (bar chart) | retention · reports · lessons | analytics-lead |
| 6 | shop | Shop | `#ef4444` red | 🛍 (bag) | listings · orders · support | shop-manager |
| 7 | dev | Dev | `#22c55e` green | <> (code) | ships the code | engineering-lead |
| 8 | inbox | Inbox | `#f97316` orange | ✉️ (tray) | email · brand deals · quotes | inbox-manager |

The Brain sits in the middle: "THE BRAIN · <n> notes · shared memory" where n = total observations in `brain/memory.jsonl`.
Exact hex values come from `docs/video-spec.md` (floor, accent, carpet `color_light`, wall `color_wall`); the backend keeps them in `hq/teams.json` and everyone reads them from `/api/teams`.

Agents come from `.claude/agents/*.md` (frontmatter `team:` matches the team name, `role: head|worker`). The scene puts the head at the back desk and the workers at the front desks. Agent display names: the frontmatter `name` (e.g. `clip-editor`); the HUD may show a prettier label (`Clip Editor`).

## Backend API (JSON unless noted)

- `GET /api/status` → `{ inbox: {clips:[], radar:[], stats:[], messages:[]}, out: {...}, approved: {...}, done: n, brain: {"Brand rules": n, ...}, brain_notes: n, waiting_for_approval: [names], desk: {busy, current, runs:[...]}, auth: bool, running: {agentName: count}, tasks: [Task], counts: {agents, running, tasks_running, tasks_waiting, tasks_done_today} }`
- `GET /api/teams` → `{ teams: [ {key, name, color, color_light, color_wall, icon, tagline, lead, tools: [{name, status: "connected"|"not connected", via: "MCP"|"skill"}], skills: [{name, note}] } ] }` in the fixed order above.
- `GET /api/agents` → `{ agents: [ {name, label, team, teamKey, role, model, description, tools:[], skills:[], color} ], teams: [names] }`
- `GET /api/events?after=N` → `{ events: [ {ts, event: "start"|"stop", agent, id, session} ], offset, total, running: {agentName: count} }`
- `GET /api/tasks` → `{ tasks: [Task] }`. `POST /api/tasks` with `{action: "add", title, team, agent?, note?, kind?, date?}` | `{action: "move", id, status}` | `{action: "remove", id}` | `{action: "approve", id}` | `{action: "progress", id, progress, subtitle}`.
  `Task = { id, title, team, agent, status: "todo"|"doing"|"review"|"done", kind: "task"|"approval"|"post"|"meeting", note, subtitle, progress: 0..100|null, date: "YYYY-MM-DD"|null, time: "HH:MM"|null, created, updated, done_at|null }`.
  The HUD maps statuses to the video's sections: RUNNING = doing, WAITING FOR YOU = review (Approve/Review buttons), DONE TODAY = done with done_at today, and the filter tabs All / Running / Waiting / Done.
- `GET /api/notifications?after=N` → `{ items: [ {id, ts, team, teamKey, title, body, kind: "done"|"started"|"scheduled"|"waiting"} ], total }` derived by the backend from the hook feed and board changes (e.g. "Creative · 3 sub-agents started", "Scripts · 5 hooks drafted for Thursday" when a task moves to review/done, "Social · One Brain reel scheduled · 9:00" for dated posts).
- `GET /api/calendar?month=YYYY-MM` → `{ days: { "YYYY-MM-DD": [Task] } }` (tasks with a date: posts, meetings, deadlines).
- `GET /api/brain` → `{ "Company": [..], "Brand rules": [..], "Lessons": [..], "Ideas": [..] }` plus `GET /api/brain/notes` → `{ notes: n }`.
- `POST /api/run` `{prompt}` → `{id, ...}` (202) or 409 when busy; `GET /api/runs/<id>?after=N` → streamed events (`text`, `tool` with `staff` for sub-agents, `tool_done`, `result`, `error`, `system`). Unchanged from today.
- `PUT /api/inbox/<clips|radar|stats|messages>/<name>` raw body upload. `POST /api/approve` `{name}` moves `out/<name>` to `approved/`.
- `POST /login` `{password}`, `POST /logout`, `GET /login` page. Unchanged.

## Scene API (`window.HQ_OFFICE`, set by `office3d.js` once the scene is built)

- `flyTo(teamKey)`, `overview()`, `select(agentName|null)`, `focusAgent(agentName)`
- `project(kind, key)` → `{x, y, visible}` screen pixels (relative to `#office3d`) for `kind` in `"team"` (the room's anchor above the back wall), `"agent"` (above the character's head), `"brain"`; the HUD uses this every animation frame to position floating cards and name pills (or the scene can host them as CSS2DObjects; either way the HUD owns their HTML content through `HQ_OFFICE.setLabel(kind, key, htmlString)`).
- `setRunning({agentName: taskText|true})` is NOT needed: the scene reads `window.HQ.running()` each frame.
- `spawnSubagents(teamKey, [ {id, label, subtitle, progress} ])` and `clearSubagents(teamKey)`: ghost figures with glow rings in that room's sub-agent bay, used when the stream shows parallel sub-agents of one team (e.g. three `clip-editor`s).
- `zoom(delta)`, `setZoomPercent(p)`, `getZoomPercent()`, `fullscreen()`, `resize()`, `minimapState()` → `{ rooms: [{key, x, y, w, h, color, lit}], brain: {x, y}, camera: {x, y}, target: {x, y} }` in 0..1 map coordinates.
- Callbacks the HUD sets: `HQ_OFFICE.onRoomClick = (teamKey) => {}`, `HQ_OFFICE.onAgentClick = (agentName) => {}`, `HQ_OFFICE.onBrainClick = () => {}`.

## HUD data API (`window.HQ`, set by `hud.js` at load)

- `HQ.status()` → last `/api/status` payload (or null), `HQ.teams()` → `/api/teams` teams array, `HQ.agents()` → `/api/agents` agents array
- `HQ.running()` → `{ agentName: true | "task text" }` merged from the hook feed and the app's own stream, plus `"chief of staff": "working"` while a run is active
- `HQ.subagents()` → `{ teamKey: [ {id, label, subtitle, progress} ] }` currently shown
- `HQ.send(prompt)` → starts a run (used by voice, Ask any agent, Run buttons)
- `HQ.toast(team, title, body)` → shows a notification

## DOM ids (for tests and judges)

`#topbar`, `#brand`, `#user-menu`, `#tab-office`, `#tab-tasks`, `#tab-calendar`, `#tab-brain`, `#ask-any`, `#agents-pill`, `#bell`, `#avatar`, `#toasts`, `#team-cards` (children `.team-card[data-team]`), `#room-label`, `#status-chips`, `#minimap` (with `#minimap-zoom`, `#minimap-out`, `#minimap-in`, `#minimap-full`), `#team-panel`, `#task-board`, `#calendar`, `#brain-view`, `#voice-orb`, `#voice-bar`, `#agent-card`, `#office3d`.

## Visual rules everyone follows

- Dark space background `#0b0f1a` to `#111827` gradient with faint stars; UI surfaces `rgba(17,20,30,0.85)` with 1px `rgba(255,255,255,0.08)` borders, radius 12 to 16px, soft shadow; text `#e6e8ef`, muted `#8b93a7`; green running dot `#34d399`; waiting yellow `#f5b400`; blue progress ring `#3b82f6`.
- Fonts: UI `Inter, -apple-system, "Segoe UI", Roboto, sans-serif`; small technical labels (`3 agents · 2 running`, `THE BRAIN`, `MAP 111%`, `RUNS ON`) in `ui-monospace, "JetBrains Mono", Menlo, monospace`, uppercase with letter-spacing where the video does.
- Nothing posts, sends or publishes. "Approve" only moves work to `approved/` or a task to done; the owner publishes.
