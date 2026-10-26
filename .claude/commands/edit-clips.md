---
description: Edit every new clip in inbox/ in parallel, brand-check the results, and report
---
Edit the new clips in `inbox/`.

1. List the clips: `ls inbox` (mp4, mov, m4v; ignore the folders). Board: `node hq/tasks.js add "Edit <n> clips" --team Creative`, move it to doing.
2. Start one **clip-editor** sub-agent per clip. Start them all in the same message so they work in parallel. Tell each one its file name.
3. When all of them are done, run the **brand-checker** on the new folders in `out/`.
4. If the brand-checker flags something, send that clip back to a clip-editor with the exact fix, then check again. Repeat until every clip passes.
5. Move each passed raw clip: `mv inbox/<file> done/`
6. **Get it ready to post.** Start one **social-media-manager** sub-agent per passed clip (all in the same message) for its posting pass: it writes `out/<name>/post.md` with the posting plan and the text for Facebook, Instagram, YouTube Shorts and TikTok.
7. **One Final task per clip:** `node hq/tasks.js add "Final · <clip title>" --team Creative --status review --note "out:<name>"` (the video, the thumbnail and the caption are all in `out/<name>/`; the owner reads "Final" as ready to post). Then move the batch task to done.
8. Report to the owner: a short table (clip, edit length, title, cover text, platforms) and the paths. Tell the owner to open the task in the app: it shows the video, the cover and the posting overview, and **Approve & post** posts it to the connected accounts. End with: "Nothing is published. Reply OK to approve."

$ARGUMENTS
