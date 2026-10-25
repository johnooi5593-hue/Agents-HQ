---
description: Edit every new clip in inbox/ in parallel, brand-check the results, and report
---
Edit the new clips in `inbox/`.

1. List the clips: `ls inbox` (mp4, mov, m4v; ignore the folders). Board: `node hq/tasks.js add "Edit <n> clips" --team Creative`, move it to doing.
2. Start one **clip-editor** sub-agent per clip. Start them all in the same message so they work in parallel. Tell each one its file name.
3. When all of them are done, run the **brand-checker** on the new folders in `out/`.
4. If the brand-checker flags something, send that clip back to a clip-editor with the exact fix, then check again. Repeat until every clip passes.
5. Move each passed raw clip: `mv inbox/<file> done/`
6. Move the task to review. Report to the owner: a short table (clip, edit length, title, cover text) and the paths. End with: "Nothing is published. Reply OK to approve."

$ARGUMENTS
