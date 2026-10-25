# Agent HQ — definitive build spec from the video

Source: Bekhruz AI's Agent HQ tour video (232 s; eight teams, 31 agents, one shared brain). Six per-slice frame analyses (f001–f233 at 1280×720) plus a 230-swatch pixel palette were merged into this document. Audience: engineers rebuilding the app exactly as a **Three.js scene + HTML overlay**.

How to read this file:

- Every measurement is given in **1280×720 frame pixels** (the capture size) and, where it matters, as a **percentage of the viewport**. For an 854×480 canvas multiply pixel values by **0.667**. Design in relative terms; the app itself is responsive (the same chrome appears at 0.46× scale inside the video's "how it's built" embeds).
- Confidence tags: **[certain]** read clearly at native scale, **[best read]** small text read after zooming, **[guess]** below the video's resolution; builders may substitute sensible placeholders for guesses only.
- Conflicts between slices were resolved by preferring the most specific observation (closest zoom, native scale, explicit crop); the losing reading is kept in a note so nothing is lost.
- Section 6 lists everything in the video that is **not** app UI (captions, chapter pills, title cards). Do not copy those.

Contents

1. Screen layout and the HTML overlay
2. The 3D scene
3. Data model implied by the UI
4. Interactions
5. Palette and typography
6. Things in the video that are NOT app UI
7. Timeline of what is on screen, open questions

---

## 1. Screen layout and the HTML overlay

### 1.1 Viewport and layering

- The app is a single full-bleed page: a **3D canvas fills the whole viewport**; a **fixed top bar** sits over its top edge; every other UI element is an **HTML overlay floating on top of the canvas** (team cards, toasts, panels, minimap, chips, pills). The canvas camera moves under a static chrome.
- Overlay classes:
  - **Screen-fixed**: top bar, toast stack (top-right), minimap (bottom-right), model chips (bottom-left), side panels (left), sub-agent progress cards (right).
  - **3D-anchored billboards** (HTML projected from a world point every frame, constant pixel size at a given zoom, scaled slightly with distance, clipped at viewport edges, blurred/dimmed together with the scene during transitions): floating team cards, the Brain label, agent name pills, the Social scheduled-post sub-card, flying file chips.
- Z-order, bottom to top: canvas → 3D-anchored billboards → side panels → toasts → top bar.
- Shared chrome tokens: surfaces are near-black blue-grey glass (#12151c–#1b1f2b, 85–92 % opacity, backdrop blur), radius 8–16 px, 1 px border rgba(255,255,255,0.06–0.08), soft drop shadow; text white (#ecf0fc) / muted grey (#8b93a7–#9aa3b2); status green #3ddc84 (dot) / #4cceac (fill).
- Background seen through the chrome: dark charcoal-navy (#2a2d36 centre → #181a26 corners) with faint star dots — see 2.2.

### 1.2 Top bar

Height ≈ 36–48 px (≈ 6 % of viewport height; use 44 px at 1280 wide). Background #161922 at ~85–90 % with backdrop blur, 1 px bottom hairline #2a2f3a. Three clusters, left / centre / right.

| Element | Position (x at 1280) | Geometry | Text (exact) | Colours |
|---|---|---|---|---|
| Logo tile | 8–30 | 22–24 px rounded square, radius 7, diagonal gradient, white hollow rounded-square/ring glyph with dark centre | — | gradient #7583fb (top-left) → teal → #14343d (bottom-right); slices also read it as #4f8cff→#7b6cf6 or blue→teal→purple |
| Wordmark | 36–110 | bold sans ~14–15 px | `Agent HQ` | #c9ccd5 (reads white) |
| Workspace switcher | 120–310 | dark pill radius full (~90×24, bg #2e323b), 16–18 px round photo avatar, label 12–13 px, tiny chevron | `Bekhruz AI ▾` | label #565962–#b8bcc6 (muted) |
| Nav tabs | 495–790 (centred) | four text tabs ~12–14 px medium in a faint darker pill container, ~18–28 px gaps; active tab gets its own lighter rounded rect (radius 6–8, bg #24252a / #2a3140) with white text | `Office` (active throughout) · `Tasks` + badge `22` · `Calendar` · `Brain` | active text #c4c3c9, inactive #898c91; badge ~18×14, radius 4, bg #595474 (reads indigo #5558d6–#6b63c9), text #bfbada/white |
| Search box | 835–1010 | rounded rect ~120–170×26, radius 8, bg #172224/#1a1f2a, magnifier icon left, dim placeholder (wraps to 2 lines at the narrow width), keyboard chip at right (~18×14 rounded, bg #3a3e48) | placeholder `Ask any agent…` · chip `⌘K` | placeholder #6e737d |
| Agents status pill | 965–1215 | pill radius full ~130–150×22, dark green translucent fill #1b292a (rgba(61,220,132,0.12)), thin green border, 6 px green dot left | `● 31 agents · 12 running` (default) / `● 34 agents · 15 running` (while 3 sub-agents run) | dot #5fdeb5, text #aec2c1 |
| Bell | 1230–1250 | 14–18 px outline bell, red round badge at top-right with one digit | badge digit **[guess]** (1 char, likely `3`) | bell #9aa0aa, badge #ff4d5e |
| Avatar | 1255–1280 | 24–32 px round photo | — | — |

Behaviour: the bar never scrolls or changes layout. Only the agents pill is live (31·12 ↔ 34·15, see 2.12). `Tasks 22` never changes. Clicking `Tasks` opens the Task status side panel **as an overlay** (the `Office` tab still looks active afterwards; it is not a route change). `Calendar` and `Brain` tabs are never opened in the video.

### 1.3 Floating team cards (one per room, 8 total)

3D-anchored billboard, anchored above the room's back corner (the corner facing away from camera), with a hairline vertical leader/stem down to the corner post (visible when zoomed).

Geometry: ≈ 150×34 px in the overview, ≈ 230×44 px when a room is centred, ≈ 265×52 px close up; radius 8–10, bg #12151c–#16181e at ~90 %, 1 px border rgba(255,255,255,0.08), soft shadow.

Anatomy, left to right:

1. **Icon tile** 22–30 px rounded square (radius 6) filled with the team accent, white glyph: Research magnifier · Inbox tray/envelope · Scripts pen/quill · Social speech bubble · Dev `</>` · TBX Shop shopping bag · Creative camera/clapper (play-in-rectangle) · Analytics bar chart.
2. **Line 1**: team name, sans bold ~11–14 px, white (#dcdbe3).
3. **Line 2**: monospace ~8–11 px grey (#616469–#8b90a0), small green dot (#82ada6 / #3ddc84) then the status string.
4. **Avatar stack** at right: 2–3 overlapping round character-head portraits (14–22 px, −6 px overlap), count = agents in the room. Stacks seen: Research 3, Inbox 2, Scripts 3, Social 2, Dev 3, TBX Shop 3, Creative 3, Analytics 2.

Exact text pattern: `<Team>` / `● <n> agents · <m> running`.

Default values (native-scale reads; the 0.46× embed reads in the last slice were unreliable and are ignored):

| Team | Line 2 default | Alternate reads |
|---|---|---|
| Research | `● 3 agents · 2 running` | 3·3 in the first overview; most of the video shows the live line instead (below) |
| Inbox | `● 2 agents · 1 running` | — |
| Scripts | `● 3 agents · 1 running` | `2 agents · 1 running` in two office-wide reads |
| Social | `● 2 agents · 2 running` | 3·2 in first overview |
| Dev | `● 3 agents · 1 running` | 3·2 in first overview |
| TBX Shop | `● 3 agents · 1 running` | — |
| Creative | `● 3 agents · 3 running` | 3·1 in first overview |
| Analytics | `● 2 agents · 1 running` | — |

Note: the per-card agents sum to 21, the header says 31. Reproduce both as shown; the header total is its own field (narration: "31 agents", plus 128 crawlers that are not counted as agents).

**Live/status variants of line 2** (the card swaps counts for a status string when the team has a headline activity):

- Research: `● GitHub Radar · scanning 29 repos` **[best read]** (also read as 28 once — treat the number as a live ticking value). Card is wider (~320 px) and **highlighted**: 1–1.5 px border #4a7bf0/#5b8bff with outer glow `0 0 12px rgba(74,123,240,0.6)`. Shown when hovered/focused and also on its own in the final office-wide shots.
- Social: `● 2 posts scheduled`, magenta glow border (#e24bd1), plus the scheduled-post sub-card (1.14) attached below-right.
- Creative (after the spawn): `● 3 agents · 3 sub-agents`.

**Focused-room header variant**: when the camera lands on a room, that room's card docks to top-centre under the top bar (x≈480–810, y≈72–115), enlarged to ~330×42, with a glowing 1.5 px blue border (#5b8bff) and a small downward triangle pointer at bottom-centre aimed at the room. Seen for Research with `● GitHub Radar · scanning 29 repos`.

Behaviour: cards slide with their rooms during the camera orbit, keep constant pixel size at a given zoom, shrink slightly with distance, are drawn on top of the scene, clip at the viewport edge, and are hidden for the selected room once its team panel is open and the camera is close.

### 1.4 Brain label card

3D-anchored above the Brain sphere, centred on the beam. ≈ 150×34 px overview, ≈ 200×36 mid, ≈ 280×46–50 close. Radius 8, bg #191c24 at ~85–90 %. Two centred lines, both monospace:

- Line 1: `THE BRAIN` — uppercase, letter-spaced ~0.2–0.25 em, ~10–13 px, pale blue #afcad5 (reads white-cyan #dff4ff).
- Line 2: `1,842 notes · shared memory` — ~8–11 px, grey #50555b–#c7cdd6.

Live counter: 1,842 at 72 s → 1,845 at 74 s → 1,847 at 75 s → 1,848 from 77 s to the end (1,842 + 6 = 1,848, matching the toast `The Brain — 6 new notes saved` that appears at 74 s). Reading seen in the overview throughout: `1,842` → later `1,848`.

### 1.5 Notification toasts (top-right stack)

Screen-fixed stack under the top bar, right-aligned with ~10 px margin: first toast x≈945–1170, y≈80–125; second directly beneath at y≈130–175; gap 6–8 px; up to two visible.

Geometry: ≈ 220–270×40–50 px, radius 10–12, bg #151820 at ~90 %, subtle border. Left: 26–28 px rounded-square team icon (same glyph as the team card); then bold white title (team name, ~11–13 px, #b5b8c1–white) over a grey subtitle (~9–11 px, #5f646a–#8b90a0); a faint right-aligned timestamp at top-right reading `now` **[best read]**.

Toasts seen (title — body):

| Title | Body | Icon colour | When |
|---|---|---|---|
| `Research` | `Found 3 new trending repos` **[best read]** (one slice read "topics") | blue #3b82f6 | 9–13 s, 26 s, 42 s, 52–54 s, 102–107 s, 215–216 s |
| `Scripts` | `3 hooks drafted for Thursday` **[best read]** ("…drafted for Thursday" certain; one slice guessed 2, another 5) | amber #f5b11a | 14–16 s, 26 s, 44 s, 54–57 s, 106–109 s, 216 s |
| `Analytics` | `Weekly report is ready` | teal #2fb7a1 | 17–20 s |
| `Social` | `One Brain reel scheduled · 9:00` **[best read]** | magenta #c43cc0 | 7 s, 37–40 s, 130–134 s, 144–149 s |
| `Dev` | `tbx-site deployed ✓` **[certain]** | green #2fbf71 | 130 s, 140–146 s |
| `Dev` | `Hotfix deployed ✓` (earlier Dev toast, 7 s and 35 s; a third read guessed "Preview deployed ✓") | green | 7 s, 35 s, 47 s |
| `The Brain` | `6 new notes saved` | light cyan #38bdf8 | 74–77 s (~3 s lifetime) |
| `Creative` | `3 sub-agents started` | violet #6c5ce7 | 123–128 s |

Behaviour: a new toast slides in from the right at the top of the stack and pushes the older one down; toasts stay fully opaque then fade out after ~3–5 s; newest on top.

### 1.6 Room label card (bottom-left)

Dark rounded rect ~410×80 (radius 10, bg #121318, subtle border) with a 4 px vertical accent bar in the team colour at its left edge; title in bold condensed caps ~26 px white; subtitle monospace ~13 px #c9ccd3. Seen texts: `RESEARCH` / `128 crawlers · top 3 repos daily`; `SCRIPTS` / `hooks · scripts · fact-check`; `SOCIAL` / `every post, scheduled`; `ANALYTICS` / `what worked, what didn't`; `TBX SHOP` / `listings · orders · support`; `DEV` / `ships the code`; `INBOX` / `email · brand deals`; `CREATIVE` / `the favorite · coming up`.

**Verdict: this is almost certainly a video lower-third, not app UI** (same typeface as the chapter marker, and `CREATIVE` shows while the camera is on the Brain). Build it only as an optional in-app room label with the same visual spec; do not expect it in the default UI.

### 1.7 Status chips — "RUNS ON" model legend (bottom-left)

Screen-fixed row at x≈105–370, y≈668–686 (bottom-left, ~16 px inset). A very faint grey monospace label (~6 chars, #6b7080) reading `RUNS ON` **[guess; label unreadable]**, then four pill chips ~22 px tall, radius 6, 8 px horizontal padding, 6 px gap, bg #1a242c with 1 px border #2a2f3a, text ~9–11 px #b0b9c0: `Opus` · `Sonnet` · `Haiku` · `headless · cloud`.

Behaviour: static legend. In the focused/zoomed room views the `Opus` chip is highlighted (brighter fill #2b2e38 with 1 px light border, or green-tinted #2f6b4f in the first slice) — the model tier of the focused room's lead. Inferred meaning: agents are tagged by model tier (Opus leads, Sonnet workers, Haiku, headless cloud runners).

### 1.8 Minimap (bottom-right)

Screen-fixed panel at x≈1035–1170, y≈560–690 (≈ 135×130 px; 180×105 in one wider layout), radius 10, bg #191d28 at ~90 %, 1 px border.

- Header row: `MAP` tiny monospace grey at left; zoom readout at right `100%` **[best read]** (one frame looked like `115%`; one slice guessed `LIVE`).
- Map area: near-black inner rect (#0f0f17, ~95–110×55–75, 1 px grey border) holding eight small rounded rectangles (~14–16×8–9 px) in the team colours laid out like the office around a white centre dot (#dde8ec, the Brain): blue top, orange upper-left, amber upper-right, green left, magenta right, red lower-left, violet lower-right, teal bottom. Minimap swatches: Research #4887e6, Inbox #dd6b12, Scripts #cfa61a, Dev #18a654, Social #b348bc, TBX Shop #dd3569, Creative #5f50b5, Analytics #1d9e7f.
- A thin white rectangle outline (rgba(255,255,255,0.7)) = the current camera viewport; it is large in the wide shot and small/shifted onto the focused room during the tour. The focused room's swatch also gets a thin lighter outline box. The swatch ring rotates slightly with the camera yaw.
- Footer: three equal square buttons (~30–40×22–24, bg #30343f, grey glyphs): `−`, `+`, `⤢` (diagonal expand / fit).

### 1.9 Team panel (left side panel) — seen for Creative

Opens when a room is clicked. Slides in from the left with motion blur while the camera dollies in on the room. Left side, x≈20–430 native (~32 % of width; appears 25–535 in a 1.25× zoomed shot), from just below the top bar to the bottom, ~16 px margins, radius 16, bg #1b252f–#1f2a3a (rgba(16,22,32,0.88)) with backdrop blur, 1 px border rgba(255,255,255,0.08), ~20 px inner padding. **Vertically scrollable** (the header scrolls out of view).

Sections top to bottom:

1. **Header**: 48 px rounded-square team icon (radius 12, #8272f3 violet, white camera/play-in-rectangle glyph); title `Creative` ~18–20 px bold #f9ffff; subtitle with green dot `● 3 agents · lead: Video Editor` ~12 px #868e9b; `×` close button (24–32 px round/rounded, #232a3a) at top-right.
2. **Tabs**: `Overview` (active: white #ecf6ff with a 2 px violet underline #7879ba ~65 px wide) · `Tasks` · `Calendar` · `Settings` (inactive #57606f), ~13 px, ~28 px spacing. Never clicked.
3. **Stat tiles**: row of three, each ~150×100, radius 10, bg #2f3744, 1 px border; small grey label ~11 px #646c79, big value ~22 px semibold #f8ffff, thin sparkline (~120×20) along the bottom.
   - `Tasks today` — `18` — violet sparkline #7d7dbd, rising.
   - `Running` — `5` — teal sparkline #349282, flat/wavy.
   - `Avg. turnaround` — `14m` — blue sparkline #889bc6, gently falling.
4. **CONNECTED TOOLS**: section label in letter-spaced monospace ~10 px #414753, right-aligned green mono badge `4 live` (#6f9b9c on dark teal pill). 2×2 grid of tool tiles ~235×60, radius 10, bg #2a323d, 1 px border; hover/selected tile bg #323858 with border #40486d. Each tile: 34 px rounded-square brand icon, name bold ~13 px #f2f7fd, green dot + `Connected · MCP` ~11 px #787e8a.
   - `Google Drive` (green square #1ca16b with white folder) · `CapCut` (black #222933 with white "C") · `Canva` (blue→indigo gradient #46a5be/#3b6cf6→#6d5df5 with white "C") · `Slack` (plum/magenta #612656/#7c1e5a with "#").
5. **SKILLS**: label `SKILLS`, right-aligned green badge `5 running in parallel` (#5ca59a on #1a2e3b). Seven rows ~34 px: status dot (running #40bc9f, idle #4f5665) + skill name in monospace ~12 px #eff3fe + progress bar ~130×5 (fill #54d7b5 on track #313d4d, rounded) + right-aligned mono percentage ~11 px #9096ac, or `idle` (#757a90) with an empty track.
   - `rough-cut` · `captions-burn-in` · `resize-for-reels` · `thumbnail-maker` · `hook-writer` (running) · `brand-check` (idle) · `music-bed` (idle) — 7 skills, matching the narration ("seven skills: rough cuts, captions, resizing, thumbnails, hooks, brand checks and music").
   - Percentages animate live, climbing ~2–4 points per second and wrapping back to ~30 % after ~90 %. Snapshots (rough-cut / captions / resize / thumbnail / hook): 91 s 72/40/60/57/38 · 93 s 75/46/–/–/45 · 97 s ~68/60/83/83/– · 98 s 31/63/86/86/69 · 99 s 33/65/89/89/73 · 100 s 35/68/32/33/77 · 101 s 37/70/35/35/80.
6. **AGENTS**: label `AGENTS`. Three rows ~62 px (8 px gap), bg #151b26; the lead row is highlighted (bg #232d48, border rgba(139,124,246,0.5)). Each row: 36 px round cartoon avatar, name bold ~13 px, tiny `LEAD` tag (grey caps #babdde) on the lead, subtitle grey ~11 px, right-aligned mono status chip `working` (#6facad on #223245).
   - `Video Editor` `LEAD` — `Cutting the Tashkent vlog · 15s next` — `working`
   - `Graphic Design` — `Thumbnail A/B · 3 variants` — `working`
   - `Copy & Captions` — `Burning captions · 2 files` — `working`

### 1.10 Agent chat panel (Video Editor) with voice orb

The same left-panel chrome, opened on a single agent (the Creative lead). Width ≈ 40 % in the zoomed shot (x≈18–535), narrower (~x 30–375) in the overview. Dark glass rgba(14,16,22,0.9), radius 16, backdrop blur.

Header: 28 px round avatar + bold title `Video Editor`; status line in small mono with green dot `● Lead agent · Creative · working`; a wrapping row of skill chips (bg #2a2d3f, radius 6, mono 11 px lowercase): `rough-cut` · `captions-burn-in` · `resize-for-reels` · `thumbnail-maker` · `sub-agents`.

Messages (each bubble has a mono uppercase header `SENDER · TIME`, 10 px letter-spaced, above 14 px body; user bubbles right-aligned, indigo→violet gradient #5b5bf6→#6f6af0, radius 14, with the user's photo avatar bottom-right outside the bubble; agent bubbles left-aligned, #23252d, radius 14, cartoon avatar (dark hair, purple shirt) bottom-left):

1. `YOU · 8:55` — `Cut the Tashkent vlog to 30s. Keep the market scene and the hook.`
2. `VIDEO EDITOR · 9:03` — `Got it. Rough cut is 41s, trimming the intro and the drone shot.`
3. `VIDEO EDITOR · 9:12` — `The 30s is cut. The 15s and 9s are next. Want to watch v2?` + attachment card: darker rounded rect, 32 px dark square with white `▶`, mono filename `tashkent-30s-v2.mp4`, grey `0:30 · 1080×1920`.
4. `YOU · VOICE` — `Hey, grab the three new clips from Drive, and edit them in parallel.`
5. `VIDEO EDITOR · NOW` — streams token by token: `On it.` → `On it. Pulling the 3 new clips` → `On it. Pulling the 3 new clips from Drive and splitting them across 3 sub-agents.` Then three sub-agent rows inside the bubble: 40 px square thumbnail (red-orange / blue / yellow), mono `Sub-agent 1 · clip_01.mp4`, three tiny chips `Cut` (filled indigo) `Captions` `Thumbnail` (outline), right-aligned percentage. Also seen as a file/progress row `clip_01.mp4` / sub-label `thumbnail` / `0%` in the earliest shot. Percentages: 0 % at spawn → 13 % / 9 % / 5 % at 122 s → 48 % / 33 % / 27 % at 136 s.

Input bar (bottom): rounded dark input ~44 px tall, placeholder `Message the agent…`; 44 px square **mic** button (dark #23252d, mic glyph); 44 px square **send** button (indigo #5b6cf0, paper-plane glyph). Panel auto-scrolls so the newest message stays at the bottom.

**Voice orb / listening state** (triggered by clicking the mic):

- The chat dims/blurs to ghost rectangles. A large glossy sphere (~160–175 px diameter) is centred in the panel (centre ≈ (270–275, 415–420)): radial gradient highlight #eaeeff at upper-left → #a4b3ff top → #af96f7 mid → #a363db bottom, edge #8872fb, soft outer halo #40518a; it pulses/breathes.
- Caption `LISTENING` under it: monospace uppercase, tracked ~0.3 em, ~11 px, #b4b3d5.
- The input turns into a transcript box ~345×56 (bg #0d1215/#0a1f16, 1 px red/dark-red border #7a2b2f–#e5484d, radius 12) with a red animated **waveform** icon (~8 vertical bars, #fcbec9, ~60×18) at left and white ~13 px transcript text (#d7dce0, max 2 lines). Placeholder `Listening…`, then the live transcript grows word by word: `Hey, grab the three` → `Hey, grab the three new clips from Drive,` → `… and edit them` → `Hey, grab the three new clips from Drive, and edit them in parallel.`
- Mic button becomes filled red #d44355/#d9484f (52×52, radius 12, white mic glyph); send button stays blue #4c6fe0/#5759a9 (52×52, white paper plane).
- On completion the orb closes, the transcript is posted as the `YOU · VOICE` bubble, and the agent's `VIDEO EDITOR · NOW` reply starts streaming. The Video Editor's 3D name pill reads `· listening` during this state and `· delegating` right after.

### 1.11 Task board panel ("Task status")

Opened by clicking the `Tasks 22` tab. Slides in from the left while the camera pans the office to the right so the rooms stay visible beside it. ≈ 505 px wide (x 20–525), radius 16, bg #1b1f2b (rgba(22,27,38,0.96)), 1 px border rgba(255,255,255,0.06), shadow, 24 px padding. Scrollable list.

- **Header**: 44 px blue rounded-square icon (#3d7cff→#5b9cff gradient, white three-lines list glyph); title `Task status` bold 20 px white; subtitle `Whole office · today` 13 px grey; `×` close 32×32 rounded (#232a3a) top-right.
- **Filter tabs** (pill row): `All 239` (active: bg #2a3142, text #fbffff) · `Running 22` · `Waiting 3` · `Done 214` (inactive: hairline border, grey #9198a8 text, count bolder). (A 0.46× embed read "339/314"; the native read 239/214 matches the narration "214 done today".)
- **Section headers**: letter-spaced monospace uppercase ~10–11 px grey (#555867) with a coloured dot: `● RUNNING · 22` (blue dot #4f8cff), `● WAITING FOR YOU · 3` (yellow dot #e4c830), `● DONE TODAY · 214` (teal dot #4cceac).
- **Rows**: cards 470×64, radius 12, bg #282c38 (border #212531), 10 px gap. Row anatomy: left status glyph · title bold ~14 px #ecf0fc · beneath it a **team tag pill** (mono ~9–10 px, radius 4/999, accent-tinted fill with darker accent text) followed by a grey mono subtitle #7f8291 · right-aligned control.

| Section | Title | Team tag | Subtitle | Right control |
|---|---|---|---|---|
| RUNNING | `Edit clip_01 → 30s reel` | `Creative` (#a89ff4, text #5951a6) | `Sub-agent 1` | progress ring `100` |
| RUNNING | `Scan GitHub Trending` | `Research` (#8fb3ef) | `128 crawlers` | progress ring 43 → 59 (ticks ~1 %/s) |
| RUNNING | `Draft 5 hooks for Thursday` | `Scripts` (#ebc16f) | `Hook Writer` | progress ring 43 → 64 |
| WAITING FOR YOU | `Post the One Brain reel · tomorrow 9:00` | `Social` (#d078e0) | `needs your approval` | button `Approve` |
| WAITING FOR YOU | `Reply to a brand deal email` | `Inbox` (#e1a569) | `draft ready` | button `Review` |
| DONE TODAY | `Thumbnail A/B test` | `Creative` | `2h ago` | faint `›` chevron |
| DONE TODAY | `Weekly retention report` | `Analytics` (#64c6c1) | `4h ago` | `›` |
| DONE TODAY | `Deploy tbx-site fix` | `Dev` | `PR #42 merged` | `›` |

- Running glyph: 20 px thin blue spinner arc (rotating), outline #2a3040. Progress ring: 30 px, track #364c54, arc #577dbc (bright #90b6e7), number 9 px #becdd2 inside. Ring values seen: 100/43/43 (150 s) → 100/51/54 → 100/53/57 → 100/57/61 → 100/59/64 (163 s).
- Waiting glyph: 22 px circle outlined yellow with `!`. `Approve` button 34 px tall, radius 8, yellow gradient #fec745→#f6a71c, dark bold text #472600. `Review` button same size, bg #323440, border #3a3e4a, white text #dbdfe8. The `Post the One Brain reel` row carries a faint 1 px yellow border (highlighted).
- Done glyph: 22 px circle (bg #2b3c43) with teal check #70b2a8.
- Section "WAITING" has a faint yellow left highlight.

### 1.12 Agent name pills (above characters)

3D-anchored above each character's head inside the **selected/zoomed** room only (hidden at office-wide zoom). Small dark pill rgba(15,15,25,0.85–0.9), radius full, ~18–22 px tall (~100–165 px wide), 1 px dark border, 5–6 px green dot (#3ddc84) at left, white 9–12 px sans text.

Texts seen: `● Copy & Captions` · `● Graphic Design` · `● Video Editor` · `● Video Editor · listening` · `● Video Editor · delegating` · `● Sub 1 · clip_01` · `● Sub 2 · clip_02` · `● Sub 3 · clip_03`. Under each `Sub N` pill a smaller semi-transparent lavender label shows `<stage> · NN%` (e.g. `cutting · 7%`, `captions · 62%`) **[pattern certain, digits best read]**. In one early frame an obscured third sub-agent pill carried an attached white file chip `clip_01.mp4`.

Behaviour: suffix changes with agent state (plain → `· listening` → `· delegating` → plain); Sub pills appear with the spawn and their stage/percent ticks up.

### 1.13 Sub-agent progress cards (right side)

Screen-fixed at the right edge, x≈895–1240, three cards stacked at y≈170–230 / 250–310 / 330–390, each ≈ 345×72, bg rgba(18,18,26,0.92), radius 12, 1 px border, 8 px gap. Title 15 px semibold white: `Sub-agent 1 · clip_01.mp4`, `Sub-agent 2 · clip_02.mp4`, `Sub-agent 3 · clip_03.mp4`. Below: three step chips in mono uppercase 11 px, radius 6, ~70×20: `CUT` · `CAPTIONS` · `THUMBNAIL`. States: active = filled indigo #5b5fd6 with white text; done = green tint (bg #1f5a46, text #5ee0a8); pending = dark outline, grey text #6b6e7a. A 2 px indigo progress line along the card's bottom edge grows left→right.

Observed sequence: 124–125 s all `CUT` active (line ~35 %) → 127 s Sub 1 & 2 CUT done + CAPTIONS active, Sub 3 CUT done → 130 s Sub 1 CUT+CAPTIONS done, THUMBNAIL active; Sub 2/3 CAPTIONS active → 133 s Sub 1 all done (line full), Sub 2/3 THUMBNAIL active.

### 1.14 Social scheduled-post sub-card

Attached under the Social team card, offset right (x≈830–1050, y≈245–300 office view; floats inside the room above its wall screen when the camera is on Social). ≈ 220×56, radius 10, bg #231b30/#14161e. Left: 34–36 px rounded (radius 8) pink date tile #e0457b/#ea6eab with two white lines `TUE` (tiny) / `9:00` (bold). Title `One Brain reel` bold 13 px white; subtitle mono 10 px grey `tomorrow · scheduled ✓`. Pops in when the post is scheduled (≈141 s) and stays.

In-room variant (47 s, camera on Social): a smaller ~160×48 card (bg #1a1420 at ~90 %) floating inside the room above its wall screen, whose left tile is a red/pink (#e0485e) ~30 px **video thumbnail** with two lines of tiny white text instead of the `TUE / 9:00` date tile; title `One Brain reel`, subtitle `tomorrow · scheduled` **[best read]**. Same data, two presentations: date tile when attached to the team card, thumbnail when anchored in the room.

### 1.15 Flying file chips (spawn animation)

Small white rounded chips ≈ 110×22 with a 16 px square thumbnail and mono dark text: `clip_01.mp4` (red thumbnail), `clip_02.mp4` (blue), `clip_03.mp4` (yellow/olive). They fly from the Video Editor's desk to each new sub-agent desk during the spawn and fade out within ~1 s.

### 1.16 Calendar tab and Brain tab

Never opened in the video. The only calendar-like UI is the `TUE 9:00 · One Brain reel · tomorrow · scheduled ✓` sub-card and the `Calendar` tab inside the team panel. The only Brain UI is the Brain label card and the `The Brain — 6 new notes saved` toast. Build these tabs as placeholders consistent with the panel chrome.

### 1.17 Cursor

The standard OS arrow is visible (white with black outline). It is not an app element; hover states exist on tool tiles (brighter border/bg) and team cards (glow border).

---

## 2. The 3D scene

### 2.1 Camera

- **Perspective camera, narrow FOV (~25–30°)** — not orthographic: far rooms are slightly smaller, the Brain disc reads as a foreshortened ellipse, verticals converge slightly in close-ups. The overview nevertheless looks near-isometric.
- Pitch ≈ 35–45° down (steeper, ~45–50°, when pushed in on the Brain); yaw ≈ 45° so square rooms read as diamonds with their two back walls standing and the two front sides open.
- Overview framing: the Brain at screen centre with the 8 rooms in a ring (Research top, Scripts upper-right, Social right, Creative lower-right, Analytics bottom (partly cut by the frame), TBX Shop lower-left, Dev left, Inbox upper-left).
- Idle: slow continuous orbit/drift counter-clockwise with a slight zoom.
- Focus: fast eased dolly-in (~0.6 s, reads as motion blur) landing with one room filling ~55–60 % of the frame; the minimap viewport rectangle tracks it. When a left panel opens the camera pans so the office shifts right (~300 px) to stay visible beside the panel.
- Room tour order used in the video: Research → Scripts → Social → Analytics → TBX Shop → Dev → Inbox → wide Brain view → push-in on the Brain.

### 2.2 Background

- Flat matte ground/void in dark slate-navy, radial gradient: ~#454f6a lit near the Brain → #30343a / #303749 mid → #181a26 at the corners (vignette). No horizon, no skybox, no grid.
- Sparse tiny white/grey star or dust dots (1–2 px, #cfd4dd at ~25–35 % alpha), some softly glowing, drifting very slowly.
- Post-processing: **bloom** on every emissive (lamps, Brain rings and core, ring light, screens, neon trims, particles); no hard shadows; subtle ambient occlusion in room corners.

### 2.3 The Brain (centre hub)

Every part, bottom to top:

1. **Platform**: a large two-tier circular platform ≈ 1.5–3 room-widths across — a wide outer disc in dark glossy charcoal (#313f4c outer ring, #415b70 disc between rings, rim highlight #3a4150/#c8d6e5 thin pale rim line) with a bevelled rim and a cylindrical side (~15 px tall on screen, darker), and a slightly raised inner disc. Seen from the side it shows concentric glossy steps.
2. **Rings on the surface**: two bright neon cyan-white emissive rings (#7fe9ff / #c6e2ec, ~4 px wide, strong bloom) at ~45–55 % and ~72–75 % radius, plus 2–3 thinner faint white rings between/inside; the innermost disc glows pale cyan (#bed8e4); a soft blue light pool around the centre.
3. **Base glow**: a bright soft radial glow (#98c8dc) under the centre, and a fainter volumetric cone/beam (#56859c) dropping below the platform into the void.
4. **Core sphere**: a pale ice-blue matte sphere (#b0d5e1 core, shaded edge #7a9aaa, highlight #cfe6f5, ~35–80 px on screen, ~0.6–0.8 desk widths) hovering ~1 room-height above the centre on the beam.
5. **Beam**: a vertical light column (~10–30 px wide, cream/pale-yellow core #efe3c2/#e9dfc8 with white-cyan bloom #bfe9ff, sampled #7e8a96 above the core) rising from the sphere straight up out of the top of the frame.
6. **Orbit rings**: 3–7 thin white/ice wireframe ellipses (rgba(255,255,255,0.4–0.8)) at different tilts around the sphere (atom/gyroscope look), radius 1.5–2.5× the sphere, carrying a few small bright particles; a faint wireframe lattice/globe behind.
7. **Particles**: small white sparkles floating around the rings, rising along the beam, and sliding along the wires that converge here.
8. **Label**: the `THE BRAIN` HTML card floats above the sphere (1.4).
9. A tiny glowing amber cone/marker (#f0b24a) with a white glow at its base stands on the floor directly below the Brain disc in the overview (possibly a spawn/"you are here" marker) **[unclear]**.

Animation: orbit rings rotate slowly; particles orbit and rise; the core and surface rings pulse gently in brightness.

### 2.4 Room construction (common to all 8)

- Square raised slab ≈ 200×200 world units (≈ 190 px wide in the overview), rotated 45° to the camera, ~0.3–0.35 units thick with darker side faces; a subtle lighter rim/skirting line along the slab's top edges (bevelled bright edge). Creative's front-left edge has a glowing trim.
- **Two walls** on the two back sides (back-left and back-right, the corner facing away from camera), ~1.1 room-heights (~70–90 px on screen) tall, in a darker, more saturated shade of the floor; thin lighter top trim/bevel; outer faces darker. **No front walls, no ceiling.**
- Floor in the team colour; a lighter rectangular **carpet/rug** (≈ 45–55 % of the floor side, pastel of the floor ≈ floor mixed 65 % toward white) sits front-centre / slightly off-centre under the main desk.
- Each room: a dark **wall dashboard** on the back-left wall (black landscape panel ~1.2×0.7 units, thin bezel, tiny title in the team colour top-left, 2–3 small white stat numbers, a white/light line chart rising left→right; TBX Shop's chart line is red-tinted); a **floor lamp** near a back corner (and/or a wall/ceiling spot above the dashboard); a floating **bookshelf** on the back-right wall; 1–2 **desks** with monitors and black chairs; 1–3 **plants**; a wall corner post where the team card's leader line lands.
- Creative is roughly 1.5× the size of the others (it includes the sub-agent bay).
- Social uniquely has bright neon-magenta light strips (#c883d4 / #ff5fff) along every wall-top edge and the floor perimeter.

### 2.5 The eight rooms, clockwise from top

Colours: palette close-up samples first (most specific), overview reads ~15 % darker.

| # (clock) | Team | Floor | Carpet | Wall (lit / shadow) | Accent (icon tile) |
|---|---|---|---|---|---|
| 12 | Research | #5d88cf | #bfcdea | #2a468f / #273e72 | #3858bd |
| 1–2 | Scripts | #d8b055 | #ecd9ba | #8b632f / #6d502e | #e3b031 |
| 3 | Social | #ca54cf | #e8b8e8 | #802a8e / #703973 (+ neon edge #c883d4) | #cd51d5 |
| 4–5 | Creative | #7a69d1 | #c9c1ea | #4b4490 / #3b357f (bay dashes #7d6cd4) | #7269d4 |
| 6 | Analytics | #40aa9c | #badad7 | #136056 / #375850 | #07b594 |
| 7–8 | TBX Shop | #d74961 | #efb7c0 | #802433 / #5e1624 | #f6275b |
| 9 | Dev | #48b467 | #bcdcc4 | #186a39 / #094b25 | #28ad5e |
| 10–11 | Inbox | #d69155 | #eed0bb | #8e4e32 / #7f4f35 | #f69a4f |

Derivation rule that reproduces these: floor = accent slightly desaturated; carpet = floor mixed ~65 % toward white; wall = floor darkened ~45 %; task tag pill = accent mixed ~35 % toward white with text = accent darkened.

Furniture inventory and occupants per room:

**Research (top, blue)** — Back-left wall: a large dark wall dashboard (~2 desks wide) with a blue line chart and small UI blocks, plus a second smaller screen; a tall thin black floor lamp with a very bright white bulb in the back corner. Side desk at the back-left wall (white desk, one dark monitor) with a red-haired agent in a green shirt. Centre: a double desk (light wood top #c9a46a on black frame) with a 3-monitor array (dark screens with code/terminal lines) where a dark-haired agent in an orange shirt sits with back to camera and an agent with green headphones sits opposite; a white glowing desk lamp between the monitors. Right wall: floating wooden shelf with white/green/blue/red/purple books and a small plant. Green plants at the front-right corner and outside the front edge. **Crawler markers**: ~10–15 small glowing light-cyan rings (#7fe9ff/#e2f8ff, ~12 px outer, 2 px stroke, dark 4 px dot inside) lying on the floor, on the walls and one on a monitor, a thin cyan line linking a few, and one bright white orb (~0.25 units) hovering mid-room near the lamp — the "128 crawlers" visualisation. They pulse / fade in and out at different phases and drift slightly. Characters: 3 (plus crawlers).

**Scripts (upper-right, amber)** — Back-left wall: two dark dashboards with white/orange line charts; tall floor lamp (round warm-white head) at the back corner. Two white desks with monitors on the left side; the back-left side desk is occupied by a **glowing white sub-agent ghost** while the team's running count is up. Central white-top desk with dual black monitors and a character with a red cap/red hair and dark jacket; a second desk at the right with a woman in a purple shirt and brown hair facing the right wall; a small pink/magenta-topped item and red/blue/white books on the right-wall shelf; a bushy plant in a white pot at the front-right corner and another outside. Desk legs are black U-frames. Characters: 3.

**Social (right, magenta)** — Back-left wall dashboard; white two-seat sofa + round white side table + glowing floor lamp along the left; centre desk with monitor and a red-haired agent (another read: green hair/headphones); a red-shirted standing character near the back-right; shelf with colourful items on the right wall; a ring light on a stand near the front-right corner; plants; neon-magenta strips on all wall tops and the floor perimeter. The scheduled-post sub-card floats above the wall screen when focused. Characters: 2 (+1 standing).

**Creative (lower-right, violet)** — Back-left wall: two black wall screens (a wide dashboard with white/green line charts and a smaller one with text rows) and a tall black floor lamp with a bright white sphere. Along the left wall: a **ring light** (white glowing torus ~0.7 units / 60–70 px on a thin black stand with round base) and a **black three-leg tripod** with a small black camera/phone head in the front-left corner; a small black desk lamp on a thin arm; a second white point light at the back-right corner. Left/side desk (cream, L-shaped, two black monitors showing dark UI with green/teal caption text lines): `Copy & Captions` (red/auburn bob, dark grey/charcoal jacket), with a bright white glow spot on the floor beside the chair. Centre desk on the lavender carpet: long cream desk with 2–3 black monitors showing a **video-editing timeline** (dark screen with 4–6 horizontal coloured clip bars cyan/orange/magenta/green/yellow and a small preview rectangle); `Video Editor` (dark or silver-grey short hair, white over-ear headphones, purple/violet shirt #7c6cf0) seated on the near side with back to camera; `Graphic Design` (dark skin, dark/brown hair, red over-ear headphones #e0432f, glasses, white long-sleeve shirt) at a desk at a right angle / the far side facing camera. Right-back wall: white shelf with pink/blue/green/purple/red books and a small plant. Two round green plants along the right/front edges. **Sub-agent bay** (2.9) on the empty front-left quarter/half of the floor. Characters: 3, +3 sub-agents after the spawn.

**Analytics (bottom, teal)** — Dark wall dashboard on the back-left wall; white sofa + glowing floor lamp at the left; round side table; centre desk with monitor and an agent in an orange/yellow shirt with a blonde-haired agent opposite; shelf with red/yellow/white books on the right wall; floor lamp; plants. Characters: 2.

**TBX Shop (lower-left, red)** — Dark wall screen (red-tinted chart) back-left; floor lamp; left desk with monitor and an agent with long orange/red hair; centre desk with a large dark monitor array whose wide screen shows a **4×2 grid of coloured product tiles** (red, blue, orange, purple, green, pink — store listings) and a seated agent in orange / dark top with headphones; right-wall shelf with colourful small boxes (products); a green plant at right and one at the front edge. Characters: 3.

**Dev (left, green)** — Two dark code/dashboard screens on the back-left wall with a glowing wall/ceiling spot above them; white desk at left with a monitor and a red-shirted agent; centre desk with two monitors and a purple/blue-shirted agent; glowing floor lamp back-right; a small red item (toolbox/book) on the right-wall shelf; plants. A **white ghost sub-agent** stands behind the main desk while Dev's running count is up. Characters: 3.

**Inbox (upper-left, orange)** — Dark wall screen with text lines on the back-left wall; white two-seat sofa against the left wall with a glowing floor lamp beside it and a round white side table; centre desk with monitor and a seated agent (green shirt, brown hair; a second agent in blue/teal further back); small shelf with red/blue books on the right wall; two green plants (front corner and right). Characters: 2.

### 2.6 Walkways and wires

**Walkways**: eight straight flat strips radiating from the Brain platform to each room's near edge/corner (meeting the room at the middle of a side), plus short diagonal links between neighbouring rooms (e.g. behind Creative toward Social). Dark charcoal slab #343844 (reads #22252f–#3e4863 depending on light), ~18–40 px wide on screen (~0.2 room-widths, one character wide), slightly raised; a faint lighter centre line #575a5f, which reads as short dashes (pale yellow #e6d7a0 or the room's colour when zoomed, e.g. yellow dashes in front of Scripts); small bright white point lights (LED-style glowing dots, 2–4 per strip, bloom) along the edges every ~1 unit, travelling toward/from the Brain. Up close one wide strip reads sand/tan #6b6552 under warm light.

**Wires / data links**: thin (1–2 px) gently curved bezier arcs from each room's back corner/screens to the Brain sphere/platform, above the walkways, in the originating team's colour (red #ff4d5e from TBX, pink/magenta #ff5fff from Social, orange #e08a3c from Inbox, cyan/blue #7fe9ff/#5886d3 from Research, green #3ddc84 from Dev, gold #e0a62e/#f5c542 from Scripts, violet #8f7cff from Creative) at ~25–40 % opacity, with small glowing white (or team-coloured) particles (3–8 px with bloom, several per line) sliding along them toward the Brain; where they converge at the Brain they form a web, and a few faint white "network" lines fan out from the sphere into space. Some straight thin red "laser" lines also cross the floor near TBX Shop.

### 2.7 Furniture and prop library (shared)

- **Desk**: thin rectangular top in cream #e2d8c6 (or light wood #c9a46a) on black U-shaped / rectangular-tube legs (#180000); ~2.2×0.9 units for the main desk, smaller for side desks; some carry a small white glowing desk lamp.
- **Chair**: black (#313638 / #1c1e24) office chair, square back and seat, central column, 5-spoke star base with casters.
- **Monitor**: thin dark flat panel (#181619) on a short stand, often a dual pair or a wide + angled one; screens #1b2338/#0b0d12 glow faintly and show terminal-like code lines (#a9c8ff text), line charts, a grid, or the Creative timeline.
- **Wall dashboard**: black panel #121116 with a tiny team-colour title, 2–3 white stat numbers, a white line chart (red in TBX Shop).
- **Floor lamp**: thin black pole (~1.4 units) on a round black base with a glowing white dome/sphere (#f9f6ef, ~14 px on screen with a ~40 px warm halo #fff2d0) casting a warm light pool.
- **Bookshelf**: thin light-wood plank #e8dcc4 (~1 unit) on the back-right wall with 4–6 upright books (red #e0485e, blue #3b63d6, purple #6a5bd6, pink #ff7ab8, cream #f2efe8, yellow #e0c040) and a tiny plant at the right end.
- **Sofa**: white/light-grey blocky two-seater #d9cdd7 (#c3d1d1 in Analytics) with a small round white side table #f8f0f1 — Inbox, Social, Analytics (and Scripts per one read).
- **Plant**: 2–3 stacked low-poly green spheres (#52a775 / #3fae5a) in a short white/cream cylindrical pot #d3d7ce; one inside the right corner, one outside the front corner on the ground, sometimes a third by the sofa.
- **Creative extras**: ring light (white torus #e1d8ff on a thin black stand), black tripod, spotlight stand, desk lamp.
- **TBX extra**: product-grid monitor and product boxes on the shelf.

### 2.8 Characters (agents)

- Style: low-poly blocky "toy"/chibi figures ~1.5–1.7 desk-heights tall (~25 px in the overview, ~45 px mid, ~70 px close): oversized slightly rounded cube head (~1/3 of height) with a cap-shaped hair mesh or hat, short box torso, stubby block arms and legs, white shoes, no facial detail beyond a dark eye band / simple eyes or glasses on a few.
- Skin: light #e8d4c1, medium #d1b9a8, tan #c3b38f, dark #645348 (also peach #f1c9a5, brown #7a4b2e).
- Hair: brown #926546 / #ab754b, auburn/red #b33a2a, blonde #eed787, dark #795e55 / #2a2a2e, plus hats (green cap, red beanie/cap, white cap).
- Clothes: single flat colours — red #ef3155, purple #8569db (#574e7e in shadow), teal #54c9a6, orange #ea8a38 / #e89549, light blue #75bdd8, green #3fbf6a, white, grey-blue hoodie #465364, dark jacket; dark navy trousers #2b3350.
- Headphones: over-ear band with cups in white (Video Editor), green (a Research agent, Sub 1), pink/red (Graphic Design), white (Sub 3).
- Poses: seated upright on office chairs square to the desk, forearms forward on the keyboard, subtle idle bob/typing; walkers stride with legs apart and slight arm swing, most carrying a dark grey tablet/laptop held in front with both hands, with a small soft white glow under their feet. Occupied chairs / active agents have a soft white light pool on the floor.
- Walkers seen: green-sweater dark-haired figure with tablet; blonde in dark jacket; green-haired figure in orange shirt with tablet; blue/purple top; teal-shirt with dark cap and tablet; orange-shirt with green cap; grey-hoodie with auburn hair; orange-haired figure on the TBX spoke; a dark figure walking from the Brain toward Creative.
- Per-room counts: 2–3 seated per room (3,2,3,2,3,3,3,2 for Research, Inbox, Scripts, Social, Dev, TBX, Creative, Analytics); 4–6 walkers on the walkways at any time.

### 2.9 Sub-agent bay and ghost sub-agents

- **Bay decal**: a thin dashed outline rectangle (white/lavender #7d6cd4–#d6d0ff at ~70 %, 2 px stroke, dash ~10 px, gap ~6 px, rounded corners) painted flat on the Creative floor over the empty front-left quarter-to-half of the room, with monospace text laid flat and perspective-skewed inside along its edge: `SUB-AGENT BAY · ready` (#e6e2ff). The label stays while empty and is hidden under the desks once sub-agents spawn; the dashed outline remains.
- **Spawn sequence** (~2 s, triggered when the lead delegates): three new white-topped desks each with one glowing white monitor and a black chair pop in, in a diagonal row (back-left → front-right) inside the bay; each gets a bright white light pool. Figures first appear as semi-transparent (~50 % alpha) white/lilac/light-blue **ghost silhouettes** with strong bloom; a large soft white radial glow circle (~400 px) and two expanding concentric white rings (~1.5 desk widths, fading) appear on the floor around them; file chips `clip_01/02/03.mp4` fly from the Video Editor to each desk; name pills `Sub 1 · clip_01` etc. appear. By ~2 s the ghosts resolve into solid characters: Sub 1 light blonde hair, teal/green headphones, purple shirt; Sub 2 red/auburn hair, purple shirt; Sub 3 sandy-blonde hair, white headphones, purple shirt — all in normal idle-typing poses at bright white screens.
- **Ghost sub-agents elsewhere**: while a team's running count is raised, the same character mesh is rendered as a solid glowing pure-white emissive figure (bloom, hexagonal head outline in one close-up) seated at a side desk (Scripts back-left desk) or standing (Dev behind the main desk); the monitor in front of it glows white; a bright white glow circle lies under it; they flicker/fade slightly.

### 2.10 Lamps and lighting

- Mood: dark cool ambient; each room lit by its own warm point light near the floor lamp (plus a wall/ceiling spot above the dashboard in Dev/Research); cool cyan glow from the Brain; strong bloom on emissive whites and cyans; monitors emit a faint glow onto the desks; no hard shadows; walls have a lit side and a shadow side (both hex values in 2.5).
- Emissives: floor-lamp bulbs (#f9f6ef), desk lamps, ring light, Brain rings/core/beam, Social neon strips, Creative front trim, walkway LED dots, wire particles, crawler rings, screens.
- Constant glow (no flicker observed).

### 2.11 Animations (idle)

- Camera slow orbit/drift; eased dolly on focus; pan when a panel opens.
- Brain: orbit rings rotate slowly, particles orbit and rise along the beam, core and surface rings pulse.
- Walkway LED dots and wire particles travel continuously toward/from the Brain.
- Walkers move along walkway centre lines between rooms and the Brain (a few px per second in the overview).
- Seated agents idle-type/bob; screens' timeline bars shift subtly.
- Research crawler rings pulse / appear-disappear out of phase and drift slightly.
- Stars drift very slowly.
- Toasts slide in/push down/fade; progress rings tick ~1 %/s; skill bars climb 2–4 %/s and wrap; chat replies stream token by token.

### 2.12 What changes when agents run

- Header pill: `31 agents · 12 running` → `34 agents · 15 running` while the 3 sub-agents exist (count = 31 base + 3 subs, running + 3); it returns to 31·12 when they finish.
- Team card line 2 switches from counts to a live task string (Research `GitHub Radar · scanning 29 repos`), to `2 posts scheduled` (Social) or `3 agents · 3 sub-agents` (Creative), and the card gets a team-coloured glow border.
- A toast announces the event (`Creative — 3 sub-agents started`, `The Brain — 6 new notes saved`, …) and the Brain note counter ticks up.
- Ghost/white sub-agent figures appear at spare desks (Scripts, Dev) or in the Creative bay with expanding floor rings and file chips; name pills gain `· listening` / `· delegating`; Sub pills show `<stage> · NN%`.
- Sub-agent progress cards appear at the right edge and step CUT → CAPTIONS → THUMBNAIL; chat rows show live percentages.
- Task board rows' progress rings tick; the `Tasks 22` badge and `Running 22` remain constant in the video.
- The `Opus` model chip highlights in focused room views.

---

## 3. Data model implied by the UI

```ts
type ModelTier = "Opus" | "Sonnet" | "Haiku" | "headless · cloud";

interface Team {
  id: "research" | "scripts" | "social" | "creative" | "analytics" | "tbx-shop" | "dev" | "inbox";
  name: string;            // "Research", "Scripts", "Social", "Creative", "Analytics", "TBX Shop", "Dev", "Inbox"
  icon: "magnifier" | "pen" | "speech-bubble" | "camera" | "bar-chart" | "shopping-bag" | "code" | "tray";
  accent: string;          // #3858bd #e3b031 #cd51d5 #7269d4 #07b594 #f6275b #28ad5e #f69a4f
  floor: string; carpet: string; wallLit: string; wallShadow: string;
  clockPosition: 12 | 1.5 | 3 | 4.5 | 6 | 7.5 | 9 | 10.5;   // clockwise from top
  agentCount: number;      // 3,3,2,3,2,3,3,2
  runningCount: number;    // 2,1,2,3,1,1,1,1
  leadAgentId: string;     // Creative → "Video Editor"
  statusLine?: string;     // overrides "N agents · M running" (e.g. "GitHub Radar · scanning 29 repos", "2 posts scheduled", "3 agents · 3 sub-agents")
  focused: boolean;        // glow border
  stats: { tasksToday: number; running: number; avgTurnaround: string; sparklines: number[][] }; // 18, 5, "14m"
  tools: Tool[];           // Creative: Google Drive, CapCut, Canva, Slack
  skills: Skill[];         // Creative: 7
  hasSofa: boolean; hasRingLight: boolean; hasNeonTrim: boolean; hasSubAgentBay: boolean;
}

interface Agent {
  id: string; name: string;          // "Video Editor", "Graphic Design", "Copy & Captions", "Hook Writer", "GitHub Radar", "Sub 1"...
  teamId: Team["id"];
  role: "lead" | "worker" | "sub-agent" | "crawler";
  model: ModelTier;
  state: "idle" | "working" | "listening" | "delegating";
  currentTask?: string;              // "Cutting the Tashkent vlog · 15s next", "Thumbnail A/B · 3 variants", "Burning captions · 2 files"
  appearance: { skin: string; hair: string; shirt: string; headphones?: string; glasses?: boolean };
  seat: { roomId: string; deskIndex: number } | { walking: true; path: string[] };
  subAgent?: { file: string; stage: "cutting" | "captions" | "thumbnail"; percent: number; steps: Record<"CUT"|"CAPTIONS"|"THUMBNAIL", "pending"|"active"|"done"> };
}

interface Task {
  id: string;
  title: string;                     // "Edit clip_01 → 30s reel", "Scan GitHub Trending", "Draft 5 hooks for Thursday", ...
  teamId: Team["id"];
  subtitle: string;                  // "Sub-agent 1", "128 crawlers", "Hook Writer", "needs your approval", "draft ready", "PR #42 merged"
  status: "running" | "waiting" | "done";
  progress?: number;                 // 0–100 for running
  action?: "Approve" | "Review";     // for waiting
  completedAgo?: string;             // "2h ago", "4h ago"
  scheduledFor?: string;             // "tomorrow 9:00"
}
// Board totals shown: all 239, running 22, waiting 3, done 214 (214 + 22 + 3 = 239).

interface Notification { teamId: Team["id"] | "brain"; title: string; body: string; at: string /* "now" */; ttlMs: number /* ~3000–5000 */ }

interface Brain { notes: number /* 1,842 → 1,848 */; label: "shared memory" }

interface Tool { name: "Google Drive" | "CapCut" | "Canva" | "Slack" | string; icon: string; status: "Connected"; via: "MCP" }

interface Skill { name: string; /* rough-cut, captions-burn-in, resize-for-reels, thumbnail-maker, hook-writer, brand-check, music-bed */ state: "running" | "idle"; percent?: number }

interface ChatMessage { sender: "YOU" | string; time: string /* "8:55", "9:03", "9:12", "VOICE", "NOW" */; text: string; attachment?: { file: string; duration: string; size: string }; subAgentRows?: Agent["subAgent"][] }

interface ScheduledPost { teamId: "social"; day: "TUE"; time: "9:00"; title: "One Brain reel"; note: "tomorrow · scheduled ✓" }

interface Office { agentsTotal: 31; agentsRunning: 12; tasksBadge: 22; workspace: "Bekhruz AI"; subAgentsLive: number /* 0 or 3 */ }
```

Name pills seen (agents): Video Editor (lead, Creative), Graphic Design, Copy & Captions, Sub 1 · clip_01, Sub 2 · clip_02, Sub 3 · clip_03. Named in board/cards: Hook Writer (Scripts), GitHub Radar (Research), Sub-agent 1. Narration adds: Research runs 128 crawlers; TBX Shop's three agents handle listings, orders and support.

---

## 4. Interactions

Every click / voice / keyboard behaviour seen or directly implied:

1. **Click a room (floor)** → camera dollies in (eased, ~0.6 s, motion blur) until the room fills ~55–60 % of the frame; the team panel slides in from the left with motion blur; agent name pills appear above the room's characters; the room's team card docks to top-centre with a glow border and its live status line; the minimap viewport rectangle jumps to that room's swatch and outlines it; the `Opus` chip highlights. The bottom-left `RESEARCH / 128 crawlers …` card appears in the video (likely an overlay; optional).
2. **Hover a team card** → glow border in the team colour and the live status line (Research blue, Social magenta).
3. **Hover a tool tile** in the team panel → brighter border/background (Canva, CapCut, Google Drive seen).
4. **Scroll the team panel** → header and stat tiles scroll out; SKILLS and AGENTS reach the top.
5. **Click `×`** on a panel → panel closes (implied).
6. **Click the mic button** in the agent chat → voice mode: chat dims/blurs, orb + `LISTENING`, input turns red-outlined with waveform and `Listening…`, mic turns red, the agent's 3D pill reads `· listening`. **Speak** → transcript streams word by word into the input. **Click send** (or auto on silence) → orb closes, transcript becomes a `YOU · VOICE` bubble, the agent reply streams, pill reads `· delegating`, then the sub-agent spawn runs (2.9), the `Creative — 3 sub-agents started` toast fires, the header pill goes 31·12 → 34·15, the right-side sub-agent cards appear, and the chat shows live sub-agent rows.
7. **Type in `Message the agent…`** and send → same bubble flow (implied by the earlier `YOU · 8:55` text message).
8. **Click the `Tasks 22` tab** → the Task status panel slides in from the left; the camera pans the office right so rooms stay visible; the `Office` tab stays visually active.
9. **Scroll the task board** (~185 px) → WAITING FOR YOU and DONE TODAY sections come into view; running rings keep ticking.
10. **Hover `Approve` / `Review`** → cursor only; never clicked in the video. Approve is meant to release the gated item (post/email/brand deal); Review opens the draft (implied).
11. **Hover an attachment card** (`tashkent-30s-v2.mp4`) → cursor only; `▶` implies play/preview.
12. **Minimap `−` / `+` / `⤢`** → zoom out / zoom in / fit the whole office (implied by the icons and the `100%` readout); clicking a swatch would focus that room (implied, not seen).
13. **`⌘K`** → focuses the `Ask any agent…` command box (implied by the keycap; never pressed).
14. **Workspace switcher `Bekhruz AI ▾`**, bell, avatar, `Calendar`, `Brain`, panel tabs `Tasks / Calendar / Settings` → never opened.
15. **Camera idle** → continuous slow orbit; the video also shows a scripted room-by-room tour (Research → Scripts → Social → Analytics → TBX Shop → Dev → Inbox → Brain), i.e. a programmatic `focusRoom(id)` / `focusBrain()` API with eased transitions.
16. **Live data events** (from the agents, no user input): toasts, Brain note counter, team-card status swaps, Social sub-card pop-in, ghost sub-agents appearing in Scripts/Dev, walkers.

---

## 5. Palette and typography

### 5.1 Palette (sampled hex values; frames 1280×720)

Team system:

| Team | Accent (icon tile) | Minimap swatch | Task tag pill / text | Toast icon | Card icon (alt reads) |
|---|---|---|---|---|---|
| Research | #3858bd | #4887e6 | #8fb3ef / dark blue | #3b82f6 | #6e9ef7, #3b63d6, #4a7bf0 |
| Scripts | #e3b031 | #cfa61a | #ebc16f | #f5b11a / #e0a92e | #e3ac3f, #e0a62e, #e9b63b |
| Social | #cd51d5 | #b348bc | #d078e0 | #c43cc0 | #e372f1, #c43cc9, #e24bd1 |
| Creative | #7269d4 | #5f50b5 | #a89ff4 / #5951a6 | #6c5ce7 | #9890f2, #6a5bd6, #7b6cf6 |
| Analytics | #07b594 | #1d9e7f | #64c6c1 | #2fb7a1 / #14b8a6 | #2fa88f, #2fbfa0 |
| TBX Shop | #f6275b | #dd3569 | (pink) | #e0485e | #ee6878, #d9394f, #e8445a |
| Dev | #28ad5e | #18a654 | (green) | #2fbf71 | #40b969, #3aa64a, #2fb961 |
| Inbox | #f69a4f | #dd6b12 | #e1a569 | #f29a3c | #e49c61, #e08a3c, #f0862b |
| The Brain (toast) | #38bdf8 | — | — | #38bdf8 | — |

Rooms (floor / carpet / wall lit / wall shadow): see table in 2.5. Overview reads: Research floor #5675b1, Social #c050c5, Creative #7b71b9 (carpet #cac1ec, wall #36344c), Dev shadow #237242.

Scene:

| What | Hex |
|---|---|
| Space background, lit near Brain | #454f6a |
| Space background top / mid | #30343a, #343641, #303749 |
| Space background corner (vignette) | #181a26 |
| Walkway strip / centre line | #343844 / #575a5f |
| Brain glow core / shaded edge / highlight | #b0d5e1 / #7a9aaa / #cfe6f5 |
| Brain light column | #7e8a96 (cream core #efe3c2) |
| Brain bright ring / inner disc glow | #c6e2ec / #bed8e4 |
| Brain dark disc / outer ring | #415b70 / #313f4c |
| Brain base glow / beam below base | #98c8dc / #56859c |
| Cyan neon rings (bloomed) | #7fe9ff, #9fe8ff |
| Desk top / leg | #e2d8c6 (#e1d7cb) / #180000 |
| Monitor frame / screen | #181619 / #1b2338 |
| Wall dashboard bg | #121116 |
| Plant green / pot | #52a775 (#4d9a66) / #d3d7ce |
| Sofa / side table | #d9cdd7 (#c3d1d1) / #f8f0f1 |
| Office chair | #313638 |
| Floor lamp glow / ring light | #f9f6ef / #e1d8ff |
| Social neon edge | #c883d4 |
| Creative bay dashes | #7d6cd4 |
| Skin light / medium / tan / dark | #e8d4c1 / #d1b9a8 / #c3b38f / #645348 |
| Hair brown / brown 2 / blond / dark | #926546 / #ab754b / #eed787 / #795e55 |
| Shirts red / purple / purple shadow / teal / orange / orange 2 / light blue / hoodie | #ef3155 / #8569db / #574e7e / #54c9a6 / #ea8a38 / #e89549 / #75bdd8 / #465364 |

UI chrome:

| What | Hex |
|---|---|
| Top bar bg | #161922 (#14191f) |
| Active tab pill / active text / inactive text | #24252a / #c4c3c9 / #898c91 |
| Tasks badge bg / text | #595474 / #bfbada |
| Agents pill bg / dot / text | #1b292a (#1c272b) / #5fdeb5 / #aec2c1 |
| Search box bg | #172224 |
| Logo gradient | #7583fb → #14343d |
| Brand text / user name text | #c9ccd5 / #565962 |
| Model chip bg / text | #1a242c / #b0b9c0 |
| Team card bg / title / sub (mono) / green dot / highlighted border | #12151c / #dcdbe3 / #616469 / #82ada6 / #264450 (glow #4a7bf0) |
| THE BRAIN label bg / title / sub | #191c24 / #afcad5 / #50555b |
| Toast bg / title / sub | #151820 (#14111c) / #b5b8c1 / #5f646a |
| Scheduled sub-card bg / TUE tile / title / sub | #231b30 / #ea6eab / #e9d6f2 / #6e5678 |
| Task board bg / card bg / card border | #1b1f2b / #282c38 / #212531 |
| Task title / sub | #ecf0fc / #7f8291 |
| Approve gradient / text | #fec745 → #f6a71c / #472600 |
| Review bg / border / text | #323440 / #3a3e4a / #dbdfe8 |
| Progress ring blue / bright / track / number | #577dbc / #90b6e7 / #364c54 / #becdd2 |
| Waiting dot / label text | #e4c830 / #555867 |
| Done dot / label / check bg / check | #4cceac / #5d6570 / #2b3c43 / #70b2a8 |
| Pending circle outline | #2a3040 |
| Board tab active / inactive text | #fbffff / #9198a8 |
| Minimap panel / map area / centre dot / button | #191d28 / #0f0f17 / #dde8ec / #30343f |
| Voice orb highlight / top / mid / bottom / edge / halo | #eaeeff / #a4b3ff / #af96f7 / #a363db / #8872fb / #40518a |
| LISTENING text / voice panel bg | #b4b3d5 / #141823 |
| Mic box bg / waveform / mic button / send button / transcript text | #0a1f16 / #fcbec9 / #d44355 / #5759a9 / #d7dce0 |
| Team panel bg / lower | #1b252f / #1f2a3a |
| Stat tile bg / value / label | #2f3744 / #f8ffff / #646c79 |
| Sparklines purple / teal / blue | #7d7dbd / #349282 / #889bc6 |
| Section label / "4 live" | #414753 / #6f9b9c |
| Tool tile bg / selected bg / selected border / name / sub / dot | #2a323d / #323858 / #40486d / #f2f7fd / #787e8a / #689a96 |
| Tool icons Drive / CapCut / Canva / Slack | #1ca16b / #222933 / #46a5be / #612656 |
| Panel header icon / title / sub | #8272f3 / #f9ffff / #868e9b |
| Panel tab active / inactive / underline | #ecf6ff / #57606f / #7879ba |
| Skill name / running dot / bar fill / track / percent | #eff3fe / #40bc9f / #54d7b5 / #313d4d / #9096ac |
| "5 running in parallel" text / pill | #5ca59a / #1a2e3b |
| Agent row selected bg / working text / working pill / LEAD text | #232d48 / #6facad / #223245 / #babdde |
| idle text / idle dot / idle track | #757a90 / #4f5665 / #2e3a4a |
| Status green (dot / fill) | #3ddc84 / #4cceac |
| Bell badge red | #ff4d5e |

Treat any sampled text value ≥ #e0e4ec as pure white (JPEG blur darkens thin glyphs).

### 5.2 Typography

Two families:

1. **UI sans-serif** — clean geometric grotesque, Inter / SF Pro style. Used for: `Agent HQ` (bold ~15 px), nav tabs (medium ~14 px), team-card titles (semibold ~11–14 px), toast titles (~12 px semibold), board filter tabs (~13 px, number bolder), task titles (~14 px semibold), task subtitles (~11 px), Approve/Review labels (~13 px bold), panel title (~18–20 px semibold), panel tabs (~13 px), stat values (~22 px semibold), tool names (~13 px semibold), agent names (~13 px semibold), chat body (~14 px), name pills (~11 px), sub-agent card titles (15 px semibold).
2. **Monospace** — light, slightly wide, JetBrains Mono / IBM Plex Mono look. Used for every small system label: team-card line 2 (~8–11 px), `THE BRAIN` (uppercase, tracked ~0.2–0.25 em) and its note line, board section headers (uppercase, tracked ~0.15 em), task tag pills (~9 px), panel section headers `CONNECTED TOOLS` / `SKILLS` / `AGENTS` (uppercase, tracked), status words `4 live`, `5 running in parallel`, `working`, `idle`, `Connected · MCP`, skill names and percentages, chat bubble headers `YOU · 8:55` (uppercase, tracked, 10 px), filenames, sub-agent step chips `CUT / CAPTIONS / THUMBNAIL` (uppercase 11 px), skill chips in the chat header (lowercase 11 px), `LISTENING` (uppercase, tracked ~0.3 em), `SUB-AGENT BAY · ready` floor decal, minimap labels, model chips (~9–11 px).

Hierarchy rule: sans for titles and actions; mono for counts, statuses, section headers and filenames; headers uppercase and letter-spaced, body mono lowercase. Sizes are for 1280×720; multiply by 0.667 for 854×480.

---

## 6. Things in the video that are NOT app UI (do not copy)

- **Burned-in word-by-word captions** at the bottom centre: white bold sans on a dark rounded strip, current word in a white box with black text, keywords in cyan/pink pills, plus pink number badges (`22`, `214`, `3`, `5`).
- **Speaker tag** `BEKHRUZ · VOICE` / `BEKHRUZ` (yellow pill #f8d762, text #290d00) and the big left-aligned caption block `HEY, / GRAB THE 3 NEW CLIPS / FROM DRIVE, / AND EDIT THEM / IN PARALLEL.`
- **Chapter marker pill** top-left (dark pill #101417, coloured dot, mono caps): `● 01 · THE OFFICE`, `● 02 · THE BRAIN`, `● 03 · CREATIVE`, `● 04 · NOBODY STOPS`, `● 05 · THE TASK BOARD`, `● 06 · HOW IT'S BUILT` — it overlaps the app's own logo.
- **Chapter title cards** over a dimmed/blurred app: outlined numeral + title + `CHAPTER n OF 6` (`01 THE OFFICE`, `02 THE BRAIN`, `03 CREATIVE`, `04 NOBODY STOPS`, `05 THE TASK BOARD`, `06 HOW IT'S BUILT`).
- **Big title cards**: `MY AI OFFICE` with pill `● 8 TEAMS · 31 AGENTS · 1 BRAIN`; `3 SUB-AGENTS / IN PARALLEL`; `128 CRAWLERS`; `8 TEAMS / 31 AGENTS`; `1 SHARED BRAIN`; `7 SKILLS`; `3 SUB-AGENTS`; `ALL AT ONCE`; `NOTHING SHIPS / WITHOUT HIS OK`; `5 STEPS` with chips `● 1 ONE AGENT, ONE JOB`, `● 2 GIVE IT TOOLS`, `● 3 THE SHARED BRAIN`, `● 4 LEADS + SUB-AGENTS`, `● 5 HUMAN IN THE LOOP`.
- **Stat callout pills** over the 3D view: `● 22 RUNNING`, `● 214 DONE TODAY`, `● 3 WAITING FOR HIM` (third-person wording = editing graphic).
- **Lower-third cards** bottom-left with a team-colour bar: the room labels listed in 1.6, and `VIDEO EDITOR / team lead`, `GRAPHIC DESIGN / thumbnails`, `COPY & CAPTIONS / exactly what it sounds like`.
- **"How it's built" step slides** (left 55 % of the frame): outlined gold numerals `01`–`05`, `STEP n OF 5`, titles `ONE AGENT, ONE JOB` / `GIVE IT TOOLS` / `THE SHARED BRAIN` / `LEADS + SUB-AGENTS` / `HUMAN IN THE LOOP`, sublines `Claude + a short brief` / `only what it needs · MCP` / `one memory server` / `split the work, run in parallel` / `public or money → your OK`, the rows `● WHO Hook Writer, Scripts team`, `● DOES 5 hooks for every new video`, `● NEVER posts anything by itself`, the `AI / Agent` circle with `MCP` and nodes `Google Drive`, `GitHub`, `Calendar`, the `Shared brain` hub diagram, the `AI / Lead` → `sub 1/2/3` → `OK` diagram, chips `● Post the reel · 9:00 → Approve` and `● Brand deal reply → Review`.
- **YouTube cards**: the `ONE BRAIN` end-screen card (`ChatGPT`, `Codex`, `Claude` chips, `One Brain: shared memory for AI`, `Bekhruz AI · watch next`) and the final end card (`NEXT VIDEO`, `Build one team / from scratch`, channel avatar, `SUBSCRIBE` → `Subscribed`).
- **Framing**: the rounded-corner device frame, blurred dark-blue backdrop/vignette around the app, the 0.46× embedded screenshots, letterboxing, dim/blur under title cards, whip-pan and zoom motion-blur transitions, and the crop/zoom into the panel in the first seven seconds.
- The OS mouse cursor.

---

## 7. Timeline of what is on screen, and open questions

| Time | App state |
|---|---|
| 0–5 s | Creative room zoomed; Video Editor chat in voice mode: orb `LISTENING`, transcript streaming, pill `Video Editor · listening`. |
| 5–7 s | Command sent; chat shows reply and `clip_01.mp4 · thumbnail · 0%`; pill `· delegating`; 3 ghost sub-agents in the bay with glow circle, pills `Copy & Captions`, `Graphic Design`, `Sub-agent…`, file chip `clip_01.mp4`; header 34·15. |
| 7–8 s | Research zoom with crawler rings; toasts Social `One Brain reel scheduled · 9:00`, Dev `Hotfix deployed ✓`. |
| 8–31 s | Full office overview, slow orbit; toasts Research → Scripts → Analytics; header 31·12; Brain `1,842 notes`. |
| 32–36 s | Focus Research: docked card `GitHub Radar · scanning 29 repos`, minimap outline, `Opus` chip highlighted, header 34·15; Dev toast. |
| 36–60 s | Room tour Research → Scripts (ghost at side desk) → Social (`2 posts scheduled`, neon, in-room `One Brain reel` card) → Analytics → TBX Shop (product grid) → Dev (standing ghost) → Inbox; header flips 34·15 at 39 s and 46 s. |
| 62–87 s | Wide Brain view, push-in; Brain counter 1,842 → 1,845 → 1,847 → 1,848 with `The Brain — 6 new notes saved` (74 s). |
| 87–107 s | Creative clicked: team panel (Overview, tiles 18/5/14m, 4 tools, 7 skills animating, 3 agents), name pills; toasts Research, Scripts. |
| 108–134 s | Video Editor chat open; mic → voice → send; reply streams; spawn at 121–124 s (`Creative — 3 sub-agents started`, header 34·15, right-side cards CUT→CAPTIONS→THUMBNAIL); toasts Social, Dev `tbx-site deployed ✓`. |
| 136–147 s | Office view; chat shows 48/33/27 %; Research card glow `scanning 28 repos`; Social `2 posts scheduled` + `TUE 9:00 One Brain reel` sub-card; Creative `3 agents · 3 sub-agents`; Dev toast `now`. |
| 148–163 s | `Tasks 22` clicked → Task status panel; scroll; rings tick 43→59 / 43→64. |
| 164–212 s | App embedded at 0.46× in explainer slides: office, Scripts close-up, Creative panel, Brain push-in, Creative spawn again, Tasks board. |
| 214–216 s | Full-screen office; Scripts toast stacks above Research; header 31·12. |

Open questions / unresolved reads for the builder to decide:

- Bell badge digit (1 char; use `3`).
- Minimap right-header label: `100%` zoom readout vs `LIVE` (use the zoom %).
- Faint label before the model chips (`RUNS ON` assumed).
- Scripts card default: `3 agents · 1 running` (close-up) vs `2 agents · 1 running` (office-wide).
- Research toast body: `repos` (preferred) vs `topics`; Scripts toast count 3 (preferred) vs 2/5; Dev toast `Hotfix deployed ✓` early vs `tbx-site deployed ✓` later (two different events, keep both).
- Research live count 28 vs 29 repos (treat as ticking).
- Whether the bottom-left `RESEARCH / 128 crawlers · top 3 repos daily` card is in-app (treat as optional overlay).
- The amber cone marker under the Brain (decorative; optional).
