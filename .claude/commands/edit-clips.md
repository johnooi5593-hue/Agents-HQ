---
description: Edit every new clip in inbox/ in parallel, brand-check the results, and report
---
Edit the new clips in `inbox/`.

**Which clips.** If the arguments below name clips (for example `inbox/<file>` or `inbox/<channel>/<file>`, sent by the owner's Edit button), edit only those. Otherwise list them: `ls inbox` (mp4, mov, m4v; ignore the folders) for the main channel.

**Which channel.** A clip in `inbox/<key>/` belongs to that channel (the arguments then name it and its brain entities). Every sub-agent for that clip gets this line in its prompt: "Channel: <name>. Read the brain entities "<name> · Company" and "<name> · Brand rules" instead of "Company" and "Brand rules"; never use the main channel's name, logo, slogans or hashtags." Clips straight in `inbox/` are the main channel: no channel line.

1. Board: `node hq/tasks.js add "Edit <n> clips" --team Creative`, move it to doing. If the arguments name a New footage task, move that one to doing instead of adding a new task.
2. Start one **clip-editor** sub-agent per clip. Start them all in the same message so they work in parallel. Tell each one its file name (and its channel line).
3. When all of them are done, run the **brand-checker** on the new folders in `out/` (with the channel line for a channel's clips).
4. If the brand-checker flags something, send that clip back to a clip-editor with the exact fix, then check again. Repeat until every clip passes.
5. Move each passed raw clip: `mv inbox/<file> done/` (or `mv inbox/<key>/<file> done/`). For a channel's clip, write its key into the clip's work folder: `out/<name>/channel.txt` holding just the key (the posting screen uses it to pick that channel's accounts).
6. **Get it ready to post.** Start one **social-media-manager** sub-agent per passed clip (all in the same message, each with its channel line) for its posting pass: it writes `out/<name>/post.md` with the posting plan and the text for Facebook, Instagram, YouTube Shorts and TikTok.
7. **One Final task per clip:** `node hq/tasks.js add "Final · <clip title>" --team Creative --status review --note "out:<name>"` (the video, the thumbnail and the caption are all in `out/<name>/`; the owner reads "Final" as ready to post). Then move the batch task (or the New footage task) to done.
8. Report to the owner: a short table (clip, channel, edit length, title, cover text, platforms) and the paths. Tell the owner to open the task in the app: it shows the video, the cover and the posting overview, and **Approve & post** posts it to that channel's connected accounts. End with: "Nothing is published. Reply OK to approve."

$ARGUMENTS
