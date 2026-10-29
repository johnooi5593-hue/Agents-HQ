---
description: All-hands meeting - everyone walks to the 6F Meeting Hall and the heads discuss how to improve (optionally a topic first)
---
Call an all-hands meeting.

1. Run `python3 hq/meeting.py "$ARGUMENTS"` (the topic, if any, is everything after /meeting). It starts one lead job: the team heads read the latest videos, posts, designs, the board and the brain for NLRCC (the hall covers the main channel only) and write `work/meetings/<date>-<time>.md`. The office walks to the hall to watch.
2. Tell the owner in one line that the meeting started, the board task number, and where the notes will be.
3. Don't wait for it or start other jobs. When the notes are in, the board task moves to review; the owner reads them there or on the hall's projector.

$ARGUMENTS
