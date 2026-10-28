# Selling Agents HQ: the client edition

Each client gets their own clean office on their own computer, signed in to **their own Claude account**. Your office,
brain, lessons, channels and accounts never leave your PC.

## What a client gets

- The 31 agents in 8 teams, the 3D office, the phone app, the board, posting with their own accounts
- The general skills: reel, yellow-serif, pixel, sfx, quill, radar, relay, pulse
- A fresh brain ("Not set up yet") with the default brand rules, no lessons, no channels, no tasks
- Their own name on the office ("Acme HQ"), set in the app's setup screen

Not included (they run on AI OFFICE or need your style guides): the sermon and thumbnail design studios,
poster-kinetic, caption-card, sermon-moments, sermon-poster, xhs-sermon-recap. In your own office they stay as they are.

## The pieces

| Piece | Where |
|---|---|
| Your office (unchanged) | this repo, public, updates your PC |
| The client edition | private repo `johnooi5593-hue/Agents-HQ-Client`, made from this repo by `release/client_edition.py` |
| Client installer | built by GitHub Actions in the private repo on every release (Releases → latest) |
| A client's updates | their office pulls the private repo hourly with their access code (a read-only key) |

## Ship a release

```
py -3 release/client_edition.py --push
```

It builds the clean copy into `..\Agents-HQ-Client`, shows what changed, and pushes only after you type `yes`.
Clients get it at their next update. The build stops if any personal detail (your name, NLRCC, D: paths…) is left in,
or if a passage it removes from an agent has changed: fix the rule in `release/client_edition.py` and build again.

## A new client

```
py -3 release/new_client.py "Acme Sdn Bhd"
```

Send them the installer (`Agents-HQ-Setup.exe` from the private repo's latest release) and the access code it prints.
They install, sign in to Claude Code with their own account, type their office name, paste the code, press Save.

- `py -3 release/new_client.py --list` every client key
- `py -3 release/new_client.py --revoke <id>` stop one client's updates (their office keeps working as it is)

## Good to know

- Claude usage is the client's own: their Claude Pro/Max plan or API key, on their computer.
- The licence is MIT and includes Bekhruz AI's copyright line: keep `LICENSE` in every copy.
- The installer is not code-signed, so Windows shows "More info → Run anyway" on first install.
