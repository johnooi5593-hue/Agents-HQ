# Claude Agent HQ → Codex channel thumbnails

This workflow is for the installed Claude HQ at `D:\Agents HQ`. It uses the existing channel keys: main (`""`) is **NLRCC**, and `pong-gospel` is **Pong+Gospel**. Templates are saved per channel, with an optional per-video override. Uploading a template does not generate images.

## Everyday use

1. In **Creative**, open **Channel thumbnails / 频道封面**. The same entry appears in each channel's settings.
2. Choose the channel and upload its PNG, JPG or WebP template (up to 15 MB). Name it, choose 9:16, 16:9 or 3:4 output, and add layout instructions. Save it as that channel's default. Uploading another template with the same name creates a new version and retains the original.
3. Open a finished video's review and choose **批准视频 → Codex 封面**. Inspect the selected video, confirm the exact cover title/subtitle and the channel's template, then press **批准这个视频，并用 Codex 生成 4 张封面**. If the source has no recorded channel, explicitly select its brand first.
4. The signed-in office Codex image connection generates four independent PNGs. You can close the page after the request is accepted; the bounded watcher collects the result. A failure is shown rather than replaced with a different provider or claimed as successful.
5. Open the returned **Final · …** task in **Waiting for your OK**. It contains the approved video, four thumbnails, provenance, and existing unambiguously associated captions/post copy where available. Select and inspect the intended cover; approve the final version in HQ.
6. Use **修改 Codex 封面 / New version** to revise the thumbnail title, template or direction. Previous deliveries remain. A confirmed failed request can be deliberately retried. Duplicate clicks on the same accepted request do not launch another generation.

The video approval starts the thumbnail stage; it does not approve the whole project or publish. A source task with several videos stays in review until all current videos have approved final packages. The existing posting interface remains a separate final action.

## Templates and fidelity

- A channel never silently inherits another channel's template. A video's temporary template choice does not change the channel default.
- Supported output sizes: **1080 × 1920**, **1920 × 1080**, **1080 × 1440**. Four separate files, never one grid.
- The template guides composition, text hierarchy, palette and overall style. A frame from the approved video is supplied when extraction succeeds. Missing extraction is recorded and shown; it is not proof of identity matching.
- These are generated raster thumbnails. Exact lettering, face identity and template fidelity still require visual review. This workflow does not promise editable PSD/Canva layers or verified OCR. The existing Sermon Studio remains separate.

## Runtime and saved evidence

The HQ Python service on 7331 owns `hq/thumbnail-design/index.json`, immutable template uploads and frozen requests. The separate existing Node image engine on 4341 owns `.studio/sermon-design-runtime/.studio/thumbnail-design/jobs/`. Each accepted request binds the channel, template version/checksum and approved video checksum. Deliveries are copied to unique `out/thumbnail-final-<requestId>/` folders and registered as native review tasks.

The bridge checks returned identity, provenance and every file checksum. Final approval checks that source and delivered bytes still match, and that no newer thumbnail request superseded the reviewed version. It does not copy old thumbnails, follow-up instructions or publication state into the new package. Ambiguous post copy is omitted with a warning.

The image engine uses the existing signed-in Codex app-server integration. It starts a bounded separate image job, not a message in this conversation. It requires actual image-generation receipts and does not silently use a paid API or another model. Output resizing/padding and native image dimensions are recorded.

## Activation and verification

Python and Node modules are loaded at service startup. An already-running old HQ or image engine needs its normal restart before these new routes exist; refreshing a page alone does not reload either backend. Preserve the installed launcher's login/phone settings. Do not interrupt active production work.

Implementation evidence: `.studio/intake/hq-channel-thumbnails-20261027/`. Automated tests and cross-runtime integration use synthetic images and a fake image provider; they do not establish real thumbnail quality or claim a production image job. Real channel templates and a real user-approved video are still needed for the first production run. This implementation remains awaiting the user's OK.

Live check on 2026-10-27: the normal installed HQ Quit/reopen loaded the new Python routes; the real template page and both channel names are visible, with no templates uploaded. A separate automated image-engine stop/start command was rejected before execution by automatic approval (`blocked by policy`). No bypass was attempted. After the normal HQ lifecycle the image engine is not listening; the existing bridge is configured to launch the missing fixed engine on an explicit generation request, but that first actual startup/generation has not been verified.
