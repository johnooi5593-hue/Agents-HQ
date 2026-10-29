# Org chart

35 agents in 9 teams around the Brain, led by the chief of staff (your Claude Code session, with its instructions in `CLAUDE.md`). Each agent is one file in `.claude/agents/`. Everyone runs on Opus 5.5; Fable only when the owner asks for it. Team heads plan, merge and review; workers do one job each.

| # | Agent | Team | Role | Job |
|---|---|---|---|---|
| lead | chief of staff | The Brain | lead | Routes work, starts agents in parallel, reviews, reports (`CLAUDE.md`) |
| 1 | `research-director` | Research | head | Head of Research |
| 2 | `market-analyst` | Research | worker | Sizes a market: customers, segments, pricing benchmarks and demand signals, with sources |
| 3 | `competitor-analyst` | Research | worker | Profiles competitors and finds the gap we can own: offers, prices, positioning, strengths, weaknesses |
| 4 | `trend-scout` | Research | worker | Finds what changed in the last 30 to 90 days in a niche, and turns comments and notes in inbox/radar/ into ranked video ideas (radar skill) |
| 5 | `inbox-manager` | Inbox | head | Head of Inbox |
| 6 | `customer-support` | Inbox | worker | Writes replies to customer messages in the company's voice: answers, apologies, next steps |
| 7 | `proposal-writer` | Inbox | worker | Writes proposals and quotes: scope, deliverables, price, timeline, next step |
| 8 | `script-writer` | Scripts | head | Head of Scripts |
| 9 | `hook-writer` | Scripts | worker | Writes ten ranked opening lines (hooks) for a script, post or video, each 12 words or fewer |
| 10 | `seo-specialist` | Scripts | worker | Finds the keywords people search for and writes titles, descriptions and outlines around them |
| 11 | `engineering-lead` | Dev | head | Head of Dev |
| 12 | `frontend-dev` | Dev | worker | Implements UI changes following the project's existing patterns: HTML, CSS, JavaScript, components |
| 13 | `backend-dev` | Dev | worker | Implements server, API, data and tooling changes following the project's patterns |
| 14 | `qa-tester` | Dev | worker | Tests a change against its acceptance criteria, reproduces bugs with exact steps, and reports pass/fail per criterion |
| 15 | `code-reviewer` | Dev | worker | Reviews a diff for bugs, risks and simplifications and returns ranked findings with PASS or FIX |
| 16 | `shop-manager` | Shop | head | Head of Shop |
| 17 | `copywriter` | Shop | worker | Writes product listings, landing-page and bio copy, and the post copy for a finished edit (relay skill: title, description, captions, pinned comment) |
| 18 | `ads-specialist` | Shop | worker | Writes paid ad variants, picks audiences and lays out a small test plan with a budget |
| 19 | `finance-analyst` | Shop | worker | Works out pricing, margins and budgets with every assumption written down |
| 20 | `project-manager` | Shop | worker | Turns a launch into a timeline: milestones, tasks, owners, dates, dependencies and risks |
| 21 | `social-media-manager` | Social | head | Head of Social |
| 22 | `community-manager` | Social | worker | Drafts replies to comments and DMs, spots what needs the owner, and lists the questions people keep asking |
| 23 | `email-marketer` | Social | worker | Writes newsletters and email sequences with subject lines and preview text |
| 24 | `outreach-writer` | Social | worker | Writes personalised outreach to partners, sponsors and collaborators |
| 25 | `creative-director` | Creative | head | Head of Creative |
| 26 | `clip-editor` | Creative | worker | Edits ONE raw clip from inbox/ into a short vertical video with burned-in captions, a cover image and notes (yellow-serif by default, or reel; pixel for the cover) |
| 27 | `brand-checker` | Creative | worker | Reviews every creative deliverable (edits, covers, copy, scripts) against the brand rules in the shared brain and lists exactly what must be fixed |
| 28 | `thumbnail-designer` | Creative | worker | Picks the frame, the words and the placement for a cover image and makes it with the pixel skill |
| 29 | `analytics-lead` | Analytics | head | Head of Analytics |
| 30 | `data-analyst` | Analytics | worker | Cleans exported data, computes the metrics and trends, shows the work, and turns analytics CSVs into lessons (pulse skill) |
| 31 | `strategist` | Analytics | worker | Turns a goal into options, a recommendation and the first three steps |
| 32 | `design-director` | Design | head | Head of Design: routes every Codex picture job (thumbnails, sermon artwork, posters) and reviews it with brand-checker |
| 33 | `codex-graphic-designer` | Design | worker | Prepares Codex video thumbnails and post covers (9:16 YouTube + Facebook, 3:4 Instagram): style, title rows, feeling, reference |
| 34 | `sermon-designer` | Design | worker | Sermon title artwork in Sermon Design Studio: Sermon Title 16:9, XHS Sermon Recap, service editions |
| 35 | `poster-designer` | Design | worker | Event, announcement, service-time, seasonal and social posters in every size, on the Codex engine |

## How a request moves

```
owner  ->  chief of staff (the Brain)  ->  team head: plan  ->  workers, in parallel
                 ^                                                     |
                 |                                                     v
              report  <----------  team head: merge and review  <----  files in work/<team>/<task>/
```

A Claude Code sub-agent cannot start other sub-agents, so the head plans and the chief of staff starts the workers. The head then merges and reviews what they made.

## The shared brain

`.mcp.json` starts the memory MCP server (through `hq/brain.js`) with its file at `brain/memory.jsonl`. Three entities: **Company** (what we do, who we serve, offers, voice), **Brand rules** (visual and copy rules) and **Lessons** (what the numbers taught us). Every agent reads what it needs before working. When the owner says "from now on…", the chief of staff writes it there.

## The office

`hq/app.html` draws this chart as a 3D floor: the Brain in the middle, one room per team around it, one desk and character per agent; heads wear a hat. Characters light up while their agent runs. The hooks in `.claude/settings.json` append every agent start and stop to `hq/events.jsonl` (`hq/events.js`), the app reads it. `hq/build.js` turns the agent files into `hq/agents.json`, the list the office is built from; run it after `/hire`.

## Learning

Every agent reads "Lessons" before it works. Team heads end their reviews with lessons tagged `[<Team> · for <Teams>]`; `/retro` saves them after the owner approves or corrects work, and `/coffee-chat` (a board task every Monday) has the heads cross-review each other's lessons. The office shows those lessons as the tips agents share when they visit each other.

## Adding an agent

`/hire <name>: <job>` writes the file and rebuilds the office. Keep one job per agent, say when to use it in the description (that is how the chief of staff picks it), put `team:` and `role:` in the frontmatter so the office knows where it sits, and give it only the tools it needs.
