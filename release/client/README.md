# Your AI office

An office of 31 AI agents in 8 teams (Research, Inbox, Scripts, Dev, Shop, Social, Creative, Analytics) around one
shared Brain. You give it work in plain words; the agents research, write, edit videos, plan posts and report back.
Nothing is published without your OK.

It runs on your own computer with **your own Claude account**: the agents are Claude Code, signed in as you. Your
work, your brain and your accounts stay on your computer.

## What you need

- Windows 10 or 11
- A Claude account that includes Claude Code (Claude Pro or Max), or an Anthropic API key
- The app installer and the **access code** you received with it

## Install

1. Run **Agents-HQ-Setup.exe**. Windows may warn that the app is not signed: click **More info**, then **Run anyway**.
2. The app checks for Git, Node.js, Python, ffmpeg and Claude Code. Press **Install missing tools** if any are missing,
   wait for the installs to finish, then press **Check again**.
3. Press **Sign in to Claude Code**. A terminal opens: sign in with your Claude account, accept the folder question,
   allow the memory server, then close it.
4. Under **Office name**, type your company's name (for example "Acme HQ"). Paste your **access code** and press **Save**.
5. Press **Open Agents HQ**.

The first time, tell the office about your company: what it does, who it serves, what it sells and how it should
sound. It saves that in the Brain, and every agent follows it from then on.

## Every day

- Type a task into **Ask any agent**, or press the orb and talk.
- Drop raw clips into the **inbox** folder (Tasks → Clips) and press **Edit**.
- Finished work waits under **Tasks → Waiting for you**. Nothing is posted until you press **Approve & post**.
- On your phone: tray icon → **Phone access** (see `docs/phone-app.md`).

## Updates

The office updates itself about once an hour when it is quiet, using your access code. Your brain, tasks and files
are kept. A new version of the desktop app itself comes as a new installer from your supplier.

## Credits

Built on Agents HQ, modelled on Bekhruz AI's "Build Your AI Team" series. MIT licence: see `LICENSE`.
