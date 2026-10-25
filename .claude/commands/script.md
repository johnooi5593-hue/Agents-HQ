---
description: Write a script in the owner's voice (reel by default, YouTube if a length is given)
---
Write a script about: $ARGUMENTS

Start the **script-writer** sub-agent with that topic. For a bigger piece, also start `hook-writer` and `seo-specialist` in the same message and hand their files to `script-writer`. If no topic was given, ask for one in a single line and stop. When it is done, reply with the hook and the file path in `out/scripts/`.
