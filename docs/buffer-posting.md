# Instagram + TikTok through Buffer

Owner's decision, 2026-11-09: Instagram and TikTok are posted through **Buffer** (buffer.com), with **one caption** for both
and **the same thumbnail** on both. Facebook and YouTube Shorts keep going out straight from Agents HQ's Post button, as
before. Instagram's own upload host kept refusing Reels from Agents HQ, and TikTok's API only fills the drafts folder;
Buffer posts to both from one place.

## The same thumbnail on both: the cover is frame 1

Buffer, Instagram and TikTok cannot take a separate cover picture for a video: they use a frame of the video (frame 0
unless you pick another). So the video that goes to Buffer starts with your cover for **3 frames (0.1 s at 30 fps)**, a
blink nobody notices, and then the edit plays exactly as it was. Frame 0 is your cover, so Instagram and TikTok both
show it. `HQ_COVER_FLASH_FRAMES=2` makes it even shorter. Agents HQ reads frame 0 back after making the file and checks
it really is the cover.

A 9:16 cover fills the frame. A 3:4 cover (the Instagram Codex pick) sits whole in the middle over a blurred copy of
itself, which is what the Instagram grid shows anyway.

## What Agents HQ makes: the Buffer package

Right after you approve a video, Agents HQ makes `approved/<name>/buffer/` in the background (about half a minute):

| file | what |
|---|---|
| `final.mp4` | the edit with your thumbnail as frame 1, Instagram-ready (H.264, AAC, faststart) |
| `cover.jpg` | the same cover exactly as it appears in frame 1 |
| `caption.txt` | the one caption for Instagram and TikTok (the option you picked, hashtags included) |
| `title.txt` | the TikTok title (the option's `Title:` line, at most 90 characters) |
| `package.json` | which video and cover it was made from, the frame check |

On the posting screen the **Buffer · Instagram + TikTok** row shows the package: Download final.mp4, Download cover.jpg,
Copy caption, Copy TikTok title, Open Buffer. If you change the thumbnail or the video on that screen, the package is
made again for that pick.

## Two ways to post

**By hand (works from day one).** In Buffer: New post → tick Instagram and TikTok → drop `final.mp4` → paste the caption
(the same on both) → TikTok title → schedule. Buffer's thumbnail picker already sits on frame 1. Then press **Posted in
Buffer** on the posting screen so the board shows the video as out.

**From Agents HQ (once connected).** Under user menu → Accounts → Buffer:

1. **API key.** In Buffer connect Instagram (professional account) and TikTok as usual. Open
   publish.buffer.com/settings/api, create an API key (the free plan allows one), paste it, Connect Buffer. Agents HQ reads
   your channels and picks the Instagram and TikTok ones; check the two pickers.
2. **Media host.** Buffer has no upload: it fetches the video from a public https address when it publishes (which can be
   days later for a scheduled post), so the file must sit somewhere public until then. Any S3-compatible bucket with public
   reads works; Cloudflare R2 is free: R2 → Create bucket `agents-hq-media` → Settings → Public access → allow the r2.dev
   subdomain (that address is the *Public address*) → Manage R2 API Tokens → Object Read & Write on that bucket (Access
   Key ID, Secret Access Key, and the S3 endpoint `https://<account id>.r2.cloudflarestorage.com`). Paste the four values,
   **Save & test**: Agents HQ uploads a small file, reads it back from the public address with no password (what Buffer
   will see), and removes it.

With both set up, the Buffer row is ticked by default (and the direct Instagram and TikTok rows are not). **Post** then
makes the package if it isn't made yet, uploads `final.mp4` to the bucket under an unguessable address, and creates the
Instagram Reel and the TikTok post in Buffer with the same caption, now or at the scheduled time (Buffer publishes by
itself; the computer may be off). Agents HQ asks Buffer every 10 minutes how the posts went and shows the Instagram and
TikTok links when they are out. Buffer sees the whole caption; you can still open Buffer to change anything before it goes.

**A scheduled post stays in step, both ways.** On the posting screen a scheduled Buffer row has **Change** and **Cancel**:

- **Change** opens the time, the TikTok title and the caption. **Save, in Buffer too** edits both Buffer posts first and
  only then the record here, `buffer/caption.txt`, `buffer/title.txt` and the dated task on the board. Only the fields you
  changed are sent. The time must be 10 minutes to 4 weeks ahead.
- **Cancel** asks once, then deletes both posts in Buffer, so they never go out. Cancelling here used to leave them in Buffer.
- A post Buffer already sent is left alone, and the row says so. If only one of the two could be changed or deleted, the row
  shows which one, and the other is yours to fix in Buffer.
- The other way round: move the time or delete the posts in Buffer, and Agents HQ shows it at its next check (every 30
  minutes while the post is more than an hour away, every 10 minutes after that). A caption edited in Buffer is not read back.
- A post you made by hand in Buffer (**Posted in Buffer**) is not linked: change it in Buffer.

Files in the bucket are yours: delete old ones whenever you like, once their posts are out (not before: Buffer fetches
the video at publish time).

## What the agents do differently

- Social's posting pass (`post.md`, skill **relay**) writes **one caption per option** that works on Facebook, Instagram,
  YouTube and TikTok alike: within Instagram's 2,200 characters and 30 hashtags, hashtags inside the caption, and a `Title:`
  line under 60 characters that is the YouTube title, the thumbnail title **and** TikTok's title. There is no separate
  `## TikTok` section any more; an old one is ignored.
- Creative delivers one `cover.jpg` at 1080×1920 with the words well inside the middle 3:4 (the Instagram grid), because
  that picture becomes frame 1 of the video.
- Agents never write into `buffer/`, never call Buffer, and never read `.hq-accounts.json` (where the key and the bucket
  secret live, on this computer only). Posting stays the owner's button.

## Limits worth knowing

- Buffer API: 150 calls per 15 minutes on the free plan; Agents HQ uses two per post, one per status check, and two to four for a Change or Cancel.
- Buffer stores `firstComment` for Instagram unreliably through the API, so hashtags stay in the caption.
- TikTok content settings (privacy, duet, stitch, AI label) are not in Buffer's API: Buffer uses the channel's defaults.
- The video and the cover of a scheduled post can't be swapped from here: cancel it and post again.
