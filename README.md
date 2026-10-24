# Agents HQ

The headquarters of a small AI creative team that runs inside [Claude Code](https://claude.com/claude-code). Drop raw clips, comments and analytics into `inbox/`, and a lead agent puts the staff to work: clips get cut, captioned and covered in parallel, a checker reviews them against your brand rules, a scout turns comments into ideas, a scriptwriter writes in your voice, an analyst turns stats into lessons. A shared brain remembers your rules. Nothing is published without your OK.

Built from Bekhruz AI's video [**I Built an AI Agent Team From Scratch (Claude Code)**](https://youtu.be/-14NKNpWr1M) and the [ai-creative-team](https://github.com/bekhruztbx/ai-creative-team) repo behind it. The video (episode 4 of the "Build Your AI Team" series) builds a lead plus parallel sub-agents with a shared memory brain. Episode 6 later turned every agent into a skill. Agents HQ keeps both ideas:

- **Skills hold the know-how.** Six playbooks in `.claude/skills/`, each with its own scripts.
- **Agents are the staff.** Six thin sub-agents in `.claude/agents/` that load a skill, work in their own context with only the tools they need, and run in parallel.
- **The desk is slash commands.** `/standup`, `/edit-clips`, `/script`, `/whats-next`, `/post-copy`, `/stats`, `/teach`.

## The floor plan

```
Agents-HQ/
├── CLAUDE.md                  the HQ charter: staff, brain, folders, rules
├── .claude/
│   ├── agents/                the staff (sub-agents)
│   │   ├── clip-editor.md     one raw clip in, a captioned vertical edit + cover out
│   │   ├── brand-checker.md   reviews every edit against the brand rules (read-only)
│   │   ├── scriptwriter.md    scripts and hooks in your voice
│   │   ├── scout.md           comments in, a ranked shortlist of ideas out
│   │   ├── copywriter.md      titles, descriptions, captions, pinned comment
│   │   └── analyst.md         analytics CSVs in, lessons for the team out
│   ├── skills/                the playbooks (reel, pixel, quill, radar, relay, pulse)
│   │   ├── reel/scripts/      cut.py, captions.py, frames.py (+ media.py helpers)
│   │   └── pixel/scripts/     thumbnail.py
│   ├── commands/              the desk (/standup, /edit-clips, /script, /whats-next, /post-copy, /stats, /teach)
│   └── settings.json          what the team may do alone, what it must ask, what it may never do
├── .mcp.json                  the memory MCP server (the shared brain)
├── brain/memory.jsonl         brand rules, lessons, ideas
├── hq/status.py               one JSON line with the state of inbox, out, done and the brain
├── inbox/                     raw clips; inbox/radar/ comments and notes; inbox/stats/ analytics CSVs
├── out/                       finished work waiting for your OK
├── done/                      raw clips whose edit is finished
└── setup.sh                   one-time setup
```

## Who does what

| Staff | Skill | In | Out |
|---|---|---|---|
| clip-editor | reel + pixel | `inbox/<clip>.mp4` | `out/<clip>/edit.mp4`, `cover.jpg`, `captions.srt`, `notes.md` |
| brand-checker | (the brand rules) | `out/<clip>/` | `PASS` or `FIX: what, which file, which option` |
| scriptwriter | quill | a topic | `out/scripts/<slug>.md` |
| scout | radar | `inbox/radar/*` | `out/radar/shortlist.md` + "Ideas" in the brain |
| copywriter | relay | `out/<clip>/notes.md` | `out/<clip>/post.md` |
| analyst | pulse | `inbox/stats/*.csv` | `out/pulse/report.md` + "Lessons" in the brain |

The lead (your Claude Code session) reads `CLAUDE.md`, delegates, runs the clip-editors in parallel, sends everything through the brand-checker, and reports. For a small single task it can use a skill directly instead of delegating.

## Setup (once)

You need [Claude Code](https://claude.com/claude-code), ffmpeg, Python 3.10+ and Node.js 18+.

```bash
git clone https://github.com/johnooi5593-hue/Agents-HQ
cd Agents-HQ
bash setup.sh
```

`setup.sh` installs numpy, pillow and a local speech-to-text engine (faster-whisper, or sherpa-onnx Whisper as a fallback), creates the folders and prints the HQ status. Speech-to-text runs on your machine; nothing is uploaded.

## Use it

Start Claude Code in this folder (`claude`) and use the desk:

| Command | What happens |
|---|---|
| `/standup` | Inbox, work waiting for approval, what the brain knows, suggested next move |
| `/edit-clips` | One clip-editor per clip in `inbox/`, in parallel, then the brand-checker, then a table for your OK |
| `/script <topic>` | The scriptwriter writes a reel script (or a YouTube script if you give a length) |
| `/whats-next` | The scout reads `inbox/radar/` and shortlists 3 ideas |
| `/post-copy <clip>` | The copywriter writes title, description, captions and a pinned comment for `out/<clip>/` |
| `/stats` | The analyst reads `inbox/stats/` and saves 3 lessons every script follows from then on |
| `/teach <rule>` | Saves a brand rule to the brain (`/teach` alone lists the current rules) |

Or just talk: *"There's a new clip in inbox, make it a reel."*, *"What should I make next?"*, *"Here are this month's stats, what worked?"*

Finished work lands in `out/`. Raw clips move to `done/` after their edit passed the check. Tip: make `inbox/` a cloud-synced folder and clips you drop on your phone land at HQ.

## Teach it your style

Tell the lead a preference (*"From now on, cover text is red, not yellow."*) or use `/teach`. The rule goes into the shared brain (`brain/memory.jsonl`), and every agent and skill follows it from the next run on. The starting rules are in that file; edit them to match your channel.

Skills improve too. When a step keeps going wrong, the lead proposes a change to that skill's `SKILL.md`, shows the diff, and saves it only after you say OK (`.claude/settings.json` asks before any edit under `.claude/`).

## Safety

- The team may only run the skill scripts and `hq/status.py`, move clips from `inbox/` to `done/`, and write into `out/` (`.claude/settings.json`).
- Deleting files and network tools like `curl` and `wget` are blocked. Pushing to git and editing the charter, the agents, the skills or the brain file asks you first.
- Nothing is uploaded or posted. You review `out/` and publish yourself.
- Installing skills or agents from other people? Read them first, or ask the lead to list every file, command and network call in one before you use it.

## Credits and license

MIT. The playbooks, scripts and team design come from Bekhruz AI's [ai-creative-team](https://github.com/bekhruztbx/ai-creative-team) (MIT), rearranged into an HQ with staff agents, a desk of commands and a status script. The Geist font in the skill folders is under the SIL Open Font License.
