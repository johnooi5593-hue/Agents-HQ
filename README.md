# Agents HQ

An AI office of 31 agents in 8 teams around one shared Brain, run by [Claude Code](https://claude.com/claude-code), with a 3D office you open in your browser to watch them work. You give the chief of staff a task in plain words; it routes the task to the right team, the team head plans, the workers run in parallel, the head reviews, and the result waits for your OK. Nothing is published, posted, sent or pushed without it.

Built from Bekhruz AI's "Build Your AI Team" videos: [I Built an AI Agent Team From Scratch](https://youtu.be/-14NKNpWr1M) (the creative team, the video tools, the permission rules; code from [bekhruztbx/ai-creative-team](https://github.com/bekhruztbx/ai-creative-team), MIT) and [I Built an AI Office With 31 Agents](https://youtu.be/t0hGE-aaAds) (the office: eight teams around the Brain, heads that plan and review, workers that do one job, and the 3D "Agents HQ" view).

![Agents HQ office](hq/screenshot-office.png)

## The office

| Team | Head | Workers |
|---|---|---|
| The Brain | the chief of staff (your Claude Code session) | the shared memory everyone reads |
| Research | research-director | market-analyst, competitor-analyst, trend-scout |
| Inbox | inbox-manager | customer-support, proposal-writer |
| Scripts | script-writer | hook-writer, seo-specialist |
| Dev | engineering-lead | frontend-dev, backend-dev, qa-tester, code-reviewer |
| Shop | shop-manager | copywriter, ads-specialist, finance-analyst, project-manager |
| Social | social-media-manager | community-manager, email-marketer, outreach-writer |
| Creative | creative-director | clip-editor, brand-checker, thumbnail-designer |
| Analytics | analytics-lead | data-analyst, strategist |

Every agent is one file in `.claude/agents/` with its job, its team, its tools and its steps. The full org chart is in `docs/office.md`. Seven skills in `.claude/skills/` (reel, yellow-serif, pixel, quill, radar, relay, pulse) hold the creative know-how and their scripts; the agents that need one preload it.

**The app** (`python hq/server.py`, opens http://localhost:7331):

| Screen | What you do there |
|---|---|
| **Office** | The 3D floor: the Brain in the middle, one room per team, one desk and character per agent, heads wear a hat. Screens light up and speech bubbles appear while an agent runs. "31 agents · N running" at the top. Drag to orbit, wheel to zoom, click a character for its card, click a room to fly to it, keys 1 to 8 jump to rooms, 0 is the overview, the minimap is bottom right |
| **Tasks** | The board (to do, doing, review, done) the chief of staff keeps, who is running now, and the live feed of agent starts and stops. Add a task and press Run |
| **Desk** | Clips waiting, work waiting for your OK, edited count, brand rules, and the lead's latest reply |
| **Inbox** | Drag raw clips, comment exports and analytics CSVs in |
| **Staff** | All 31 agents by team, with a light on whoever is working |
| **Work** | Finished edits with cover and video preview, notes and post copy. **Approve** moves a folder to `approved/` |
| **Brain** | Company, brand rules, lessons and ideas: what every agent reads. Teach a rule here |
| **Console** | Everything the lead does, as it happens |

The buttons at the bottom (Standup, Edit clips, What's next, Stats, Script…, Post copy…) and the message box talk to the chief of staff, which is Claude Code running headless in this folder with the repository's own permission rules. Each message continues the same conversation, so "OK" and "make it shorter" work.

**The office shows every Claude session on your computer.** Claude Code keeps a live log of each session in `~/.claude/projects/`, including every sub-agent with its type and whether it has finished. The engine reads those logs (`hq/activity.py`, read-only), so the characters light up whenever Claude is working, even in a session started in another folder, such as a project on your D: drive. Hooks in `.claude/settings.json` add exact sub-agent starts and stops for sessions inside this folder. Set `HQ_WATCH_CLAUDE=0` to turn the watcher off.

**It updates itself.** Every time you open the app it pulls the newest Agents HQ from GitHub before starting (set `HQ_NO_UPDATE=1` to skip that).

## How the office gets better

The agents learn from every project, and share it across teams:

- **Retro.** After you approve or correct work, `/retro` saves up to five specific lessons to the brain, tagged with the team they came from and the teams they help: `[Creative · for Scripts] Hooks under 8 words kept people watching longer`.
- **Every agent reads the lessons before it works.** The team heads end each review with their lessons, so the next project starts from what the last one taught.
- **Weekly coffee chat.** Every Monday the board gets a "Coffee chat" task. `/coffee-chat` has the eight team heads cross-review each other's lessons, adopt what helps them, and propose improvements. Changes to skills or agents still wait for your OK.
- **You can see it.** In the office, idle agents stand up, grab coffee, take calls and walk to other departments. What they talk about in their speech bubbles are those real lessons, ideas and brand rules (`/api/chatter`). When real work arrives they hurry back to their desks.

## The floor plan

```
Agents-HQ/
├── Open Agents HQ.command     double-click on a Mac to open the app (Windows: Open Agents HQ.bat)
├── CLAUDE.md                  the chief of staff's charter: teams, how work flows, the brain, the rules
├── docs/office.md             the org chart: every agent and its job
├── .claude/
│   ├── agents/                31 agents, one file each (team and role in the frontmatter)
│   ├── skills/                reel, yellow-serif, pixel, quill, radar, relay, pulse (with their scripts)
│   ├── commands/              /brief /standup /research /campaign /edit-clips /script /whats-next /post-copy /stats /teach /tasks /hire /retro /coffee-chat
│   └── settings.json          what agents may do alone, what asks you, what is never allowed; the office hooks
├── .mcp.json                  the memory MCP server (the shared brain), started through hq/brain.js
├── brain/memory.jsonl         Company, Brand rules, Lessons, Ideas
├── hq/                        the app: server.py, app.html, office3d.js (+ vendor/three.min.js), login.html,
│                              tasks.js and tasks.json (the board), events.js and events.jsonl (the live feed), status.py
├── inbox/                     raw clips; inbox/radar/ comments; inbox/stats/ analytics CSVs; inbox/messages/ emails and DMs
├── work/<team>/<task>/        research, copy, plans, code notes: one folder per task
├── out/                       finished video work waiting for your OK
├── approved/                  what you approved in the app, ready for you to publish
├── done/                      raw clips whose edit is finished
├── setup.sh / setup.py        one-time setup (setup.py for Windows)
├── deploy/ and fly.toml       the hosted version (Docker, HTTPS, login)
└── LICENSE                    MIT
```

## Setup (once)

You need [Claude Code](https://claude.com/claude-code) (signed in), Node.js 18+, and for video editing also ffmpeg and Python 3.10+.

```bash
git clone https://github.com/johnooi5593-hue/Agents-HQ
cd Agents-HQ
bash setup.sh        # Windows: python setup.py
```

The first time you run `claude` in the folder, accept the trust dialog and allow the `memory` server. The app passes the allow list itself, so it works right away.

## Open the app

```bash
python3 hq/server.py      # Windows: python hq/server.py
```

Or double-click `Open Agents HQ.command` (Mac) or `Open Agents HQ.bat` (Windows). The browser opens http://localhost:7331. The app only listens on your own machine.

## Windows app

No terminal, no setup. One download:

- **[Agents-HQ-Setup.exe](https://github.com/johnooi5593-hue/Agents-HQ/releases/latest/download/Agents-HQ-Setup.exe)**, the installer
- [Agents-HQ-Portable.exe](https://github.com/johnooi5593-hue/Agents-HQ/releases/latest/download/Agents-HQ-Portable.exe), runs from any folder, nothing to install

Windows SmartScreen will warn you the first time, because the app is not code-signed. Click **More info**, then **Run anyway**.

The first start does the setup for you. It checks for Python, Node.js, ffmpeg, Git and Claude Code, and installs the missing ones with one click. It signs you in to Claude Code. It downloads your office into `Documents\Agents HQ` (or `C:\Users\<you>\Agents HQ` when Documents is synced by OneDrive). Then it opens the office.

After that the office updates itself every time it starts. The app itself does not yet: when a new version is announced, download Agents-HQ-Setup.exe again from the link above. Editing mp4 clips still needs ffmpeg; the app installs it for you.

Every push to `main` builds a new installer (`.github/workflows/windows-app.yml`), so the links above always give you the newest one.

## Use it

| You type (or press) | What happens |
|---|---|
| `/brief write the listing for the new hoodie` | Routed to Shop: shop-manager plans, copywriter writes, brand-checker reviews |
| `/research AI video editing tools market` | market-analyst, competitor-analyst and trend-scout run in parallel; one brief with sources |
| `/campaign launch of the October drop` | Social and Shop heads plan; posts, replies, newsletter, outreach, ads, pricing and timeline run in parallel |
| `/edit-clips` | One clip-editor per clip in `inbox/`, in parallel, then brand-checker |
| `/script <topic>` · `/whats-next` · `/stats` · `/post-copy <clip>` | The Scripts head, the trend-scout, the data-analyst, the copywriter |
| `/standup` | Status of the folders, the board and the brain |
| `/tasks` · `/hire podcast-producer: turns long recordings into episode outlines` | The board · a new agent file and org-chart row |
| `/teach cover text is red, not yellow` | A rule saved to the brain that every agent follows from then on |

Or just talk. Tell it about your company once (*"We sell X to Y. Our voice is Z."*) and the chief of staff saves it to the brain.

Deliverables land in `work/<team>/<task>/` and `out/<clip>/`. Nothing is posted; you review and say OK.

## Caption style: Yellow Serif Kinetic

The default caption style (黄字重点衬线动态字幕, the `yellow-serif` skill): white heavy serif captions, key words in warm yellow `#FBC238`, and one motion per sentence (typing, pop, burst, shine, flash), with full-screen, darkened-speaker and torn-paper layouts and light-leak transitions. A long talk becomes two 45-60 s topics. Each gets a planning page (`plan.md`: original line, key words, motion, picture and notes) that you can approve before anything is rendered. Every render keeps editable captions (`edit.ass` for Aegisub, `edit.srt` for CapCut) beside the video. Speech-to-text handles Chinese and English. The fonts (Noto Serif SC and Ma Shan Zheng, both SIL OFL) download on first use. The full guide is `.claude/skills/yellow-serif/GUIDE.md`. Ask for "word-by-word captions" to get the older reel style.

## Posting: Facebook, Instagram, YouTube Shorts in one press

After Creative finishes a clip (one captioned video, one cover), the Social team writes `post.md`: the posting plan and 2-3 text options for every platform. Open the task in the app and you get the **posting overview**: the video, the thumbnail (tap another one if there are several), the video version, and the text for each platform (tap an option, edit anything). **Approve & post** posts to every ticked account at the same time; each one shows its link, or what went wrong. A long talk cut into topics shows one tab per topic, and each topic is its own post. TikTok you post by hand with the TikTok text.

**Schedule it:** under **When**, pick **Schedule** and a date and time (10 minutes to 4 weeks ahead), then **Approve & schedule**. Facebook and YouTube receive the video right away and publish it themselves at that time. Instagram has no scheduling in its API, so Agents HQ posts it then: keep the computer on with Agents HQ running (if it was off, it posts as soon as Agents HQ opens and says it was late). A scheduled post shows on the board and in the Calendar, and a waiting Instagram post can be cancelled from the same screen.

Connect the accounts once under your name (top right) → **Accounts for posting**; the screen walks you through it:
- **Facebook + Instagram:** a Meta app of your own (App ID, App secret and a token from the Graph API Explorer). Instagram must be a Professional account linked to your Facebook Page.
- **YouTube:** a Google Cloud OAuth client (Desktop app); you sign in once. Google keeps uploads from a new API project **private** until the project passes Google's free YouTube API audit.

The keys stay in `.hq-accounts.json` on this computer: never committed, and the agents are blocked from reading it or calling the posting API. Only your button posts.

## Your phone, with no "Not Secure" warning

In the app, open **Phone access**, turn it on with a password, then press **Turn on secure link**. It uses Tailscale's free HTTPS (`tailscale serve`) to give your computer a real https address like `https://my-pc.my-tailnet.ts.net/`, shown with a QR code. Safari shows no warning, and the microphone and Copy buttons work on the phone. The first time, Tailscale may ask you to turn on HTTPS certificates in its admin page; the app shows the button. Phones still log in with your password: requests that arrive through Tailscale are never treated as this computer's own window.

Without the app: turn on HTTPS at https://login.tailscale.com/admin/dns, then run `tailscale serve --bg 7331` once on the computer.

## Host it, so your phone can reach it

The hosted version is the same app behind a login, in one Docker image. See `deploy/` and `fly.toml`. You need a server (Fly.io is the simplest), an Anthropic API key (a server can't use your Claude app login, so the office bills to the key; set a spend limit) and a password.

```bash
fly launch --no-deploy --copy-config --name my-agents-hq
fly volumes create hq_data --size 10
fly secrets set HQ_PASSWORD='a long password' ANTHROPIC_API_KEY='sk-ant-...' HQ_SECRET="$(openssl rand -hex 32)"
fly deploy
```

Or on any VPS with Docker: `cp deploy/.env.example deploy/.env`, fill it in, `docker compose -f deploy/docker-compose.yml up -d --build`. Caddy gets the HTTPS certificate by itself.

## Safety

- The office runs on full auto: nothing asks for permission (`defaultMode: bypassPermissions` in `.claude/settings.json`). Only the hard blocks remain: `rm`, `curl`, `wget`, force pushes and reading `.env` are never allowed. If you'd rather be asked before the office edits its own agents or skills, change `defaultMode` to `default`.
- `rm`, `curl`, `wget`, force pushes and reading `.env` are blocked. `git push` asks.
- Every deliverable is reviewed by a checker or a team head before you see it. Agents never post: only your **Approve & post** button does, and the agents can't read your account keys (`.hq-accounts.json`).
- Installing agents or skills from other people? Read them first, or ask the chief of staff to list every file, command and network call in one.

## Credits and license

MIT. The creative skills, their scripts and the team design come from Bekhruz AI's [ai-creative-team](https://github.com/bekhruztbx/ai-creative-team) (MIT); the office layout follows his 31-agent office video. Three.js (`hq/vendor/`) is MIT; the Geist font in the skill folders is under the SIL Open Font License.
