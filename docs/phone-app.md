# Agents HQ on your phone

Agents HQ installs on your phone's home screen like an app. It opens full screen, always shows the newest version
(it loads from your PC each time, so there is nothing to update or reinstall on the phone), and it can send you
notifications when the Lead asks you something or work is ready for your OK.

Your PC still does all the work: it has to be on, with Agents HQ running.

## One-time setup on the PC: the secure link

Notifications and the full app need the secure (https) address that Tailscale gives your PC.

1. Agents HQ tray icon → **Phone access**.
2. Phone access must be on (with its password).
3. Turn on **Secure link (https)**. It shows an address like `https://your-pc.your-tailnet.ts.net`.
   If Tailscale says HTTPS certificates are off: open the Tailscale admin page → **DNS** → turn on **HTTPS Certificates**, then try again.
   If another app on the PC (AI OFFICE) already uses that address, the office leaves it alone and gets its own port:
   `https://your-pc.your-tailnet.ts.net:8443`. Keep the `:8443` when you type it on the phone.

## On the phone

Tailscale must be on, on the phone.

**iPhone (Safari, iOS 16.4 or newer)**
1. Open the `https://…ts.net` address and log in.
2. Share button → **Add to Home Screen** → Add.
3. Open **Agents HQ** from the new icon (not from Safari).
4. Menu (your name, top left) → **Phone notifications** → Allow. A test notification arrives.

**Android (Chrome)**
1. Open the `https://…ts.net` address and log in.
2. ⋮ menu → **Install app** (or Add to Home screen).
3. Open it from the icon → menu → **Phone notifications** → Allow. A test notification arrives.

## What you get notified about

- **Lead asks you · <task>**: the Lead needs an answer. Tapping it opens that task's chat.
- **Ready for your OK**: a task moved to Waiting for you. Tapping it opens its review.

Nothing else (no "agent started" noise). A new message about the same task replaces the older one.

## Updates

Agents HQ looks for a newer version on GitHub every hour. When there is one, it waits until the office is quiet
(no Lead job running or waiting, nothing being posted, and you haven't clicked anything for 2 minutes), then
restarts into it. The phone shows "Can't reach your PC" for a few seconds and comes back by itself; you stay logged in.

Settings (environment variables, rarely needed): `HQ_UPDATE_EVERY_MIN` (default 60), `HQ_QUIET_SEC` (default 120),
`HQ_NO_UPDATE=1` turns updates off.

## Privacy

Notifications are end-to-end encrypted from your PC to your phone (Web Push, RFC 8291); Apple's or Google's push
service only passes them on. The PC's notification key and your phones' subscriptions are kept in `.hq-push.json`
in the office folder, which is never uploaded to GitHub. To stop notifications on a phone, turn them off for
Agents HQ in the phone's settings.
