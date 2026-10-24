---
description: Write the post copy (title, description, captions, pinned comment) for a finished edit in out/
---
Write the post copy for the edit: $ARGUMENTS

If no clip was named, run `ls out` and list the clip folders that have a `notes.md` but no `post.md`, then ask which one in a single line and stop. Otherwise start the **copywriter** sub-agent on `out/<name>/`. Reply with the path of `post.md` and end with: "Nothing is posted. Waiting for the owner's OK."
