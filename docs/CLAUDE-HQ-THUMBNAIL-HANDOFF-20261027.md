# Claude HQ thumbnail handoff — 2026-10-27

## Ownership and immediate request

The owner has explicitly assigned Claude HQ code maintenance to Claude. Codex handles thumbnail production and exchanges input/output through the existing interface. Codex must not continue editing `D:\Agents HQ` code. This handoff was prepared with read-only inspection of that directory; only this document in `D:\AI OFFICE` was created.

**First fix the owner's reported bug:** clicking **Back to HQ / ← Agent HQ** on the thumbnail page does not restore the actual HQ main page. The failure has been reported by the owner; this handoff does not claim a reproduced root cause or a repair.

Observed code:

- `hq/thumbnail-studio.html` contains `<a class="back" href="/">← Agent HQ</a>`.
- `hq/server.py` handles `/` and `/index.html` by serving `hq/app.html` behind the existing page authentication guard.
- Final review links use `/?task=<delivery.taskId>`; `hq/hud.js` opens that native review task after refresh.
- `desktop/main.js` has `will-navigate`/`isLocal` checks and a window-open handler. The installed desktop app runs packaged files from `resources/app.asar`; changing the source checkout alone does not necessarily update the installed shell.

Reproduce from the actual entry the user used. Inspect page errors and network loading of `app.html`, `hud.js`, styles and office initialization. Check browser/desktop navigation separately if needed. An address bar changing to `/` or an HTTP 200 alone is insufficient: the normal office, navigation and task controls must visibly return and work. Preserve the current origin and phone access; do not hard-code localhost as the phone's return destination or relax authentication. Verify the Final deep link as well.

## What Codex changed

Claude HQ checkout (`D:\Agents HQ`):

- Added `hq/thumbnail_design.py`: channel templates, frozen video approval requests, bounded Codex-job collection, verified final delivery, approval guards.
- Added `hq/thumbnail-studio.html`, `.js`, `.css`: template upload/default selection, video/title approval, progress, deliberate retry/collection and Final links.
- Modified `hq/server.py`: static/API routes, bridge initialization, consistent bridge-lock → task-lock order, approval/revision guards, final folder/task/source reconciliation and accepted-job watcher resumption.
- Modified `hq/hud.js`: Creative and channel-settings entries, video approval handoff, Final revision link, duplicate final-folder suppression, and final-task deep links.
- Added `hq/tests/test_thumbnail_design.py` and `hq/tests/thumbnail-routing.test.cjs`.
- Added `docs/channel-thumbnails.md`.

**Behavioral scope to review:** this is more than a separate page. The current UI directs ordinary `out/` video folders, except `thumbnail-final-*`, into the thumbnail approval stage and hides intermediate posting actions. Backend guards also prevent ordinary video-folder approval / task move-to-done from bypassing that stage. Review this behavior against the intended HQ workflow before changing it; do not silently break existing holds or already approved work.

Codex side (`D:\AI OFFICE`, Codex ownership):

- Added `studio/thumbnail-design.mjs` and focused thumbnail tests.
- Extended `studio/sermon-design-codex.mjs` for complete thumbnail prompts/aspect ratios while retaining the existing receipt checks and sermon path.
- Extended `studio/sermon-design-server.mjs` to expose thumbnail jobs through the existing dedicated loopback engine.
- Added `docs/HQ-CHANNEL-THUMBNAILS.md` and evidence under `.studio/intake/hq-channel-thumbnails-20261027/`.

These were local edits. Do not assume a clean Git checkout, a complete pre-change snapshot or a committed rollback point. Inspect current diffs and preserve unrelated edits before making changes.

## Intended user workflow

1. Save a default template **per channel**: NLRCC uses existing main key `""`; Pong+Gospel uses `"pong-gospel"`. Do not recreate these channels or share defaults between brands. A per-video override is allowed.
2. User inspects the finished video and exact thumbnail headline, then explicitly approves **that video version and thumbnail generation**.
3. HQ sends one frozen request to Codex with the selected template, source-frame image when available and source/channel/template provenance.
4. Codex generates **four separate PNG options**, never one combined grid.
5. HQ verifies and copies the outputs, approved video and unambiguous existing post/caption files into a new native **Final · …** review task.
6. Final remains `review` until fresh user OK. Source tasks containing multiple videos only finish after all current videos have approved latest finals. Publishing remains the separate existing user action.

## Browser → Claude HQ API (port 7331)

Use the authenticated HQ origin, prefix `/api/thumbnail-design`. The browser does not call port 4341 directly.

| Method / suffix | Input / output |
|---|---|
| `GET /config` | `{channels:[{key,name,templates,defaultTemplateId}],dimensions,schemaVersion}` |
| `POST /templates` | `{channel,name,dataUrl,width,height,instructions,makeDefault}`. Immutable image upload; returns config. |
| `POST /default` | `{channel,templateId}`. Only a template belonging to that channel. |
| `GET /templates/:id/image` | Verified template preview. |
| `GET /context?folder=out/name&taskId=tN` | Source videos with `path,name,size,sha256`, channel evidence (`channelKnown`), templates, defaults, eligibility and prior jobs. |
| `POST /approve-video` | Explicit current-version video approval; example below. Returns `{job}`. |
| `GET /jobs/:id` | `{job}`; observes an already accepted request and may collect its existing output. Never starts a new generation POST. |

Example approval body — use actual values returned by context/config:

```json
{
  "folder": "out/<existing-folder>",
  "taskId": "<existing-task-id>",
  "videoPath": "<selected-relative-video-path>",
  "videoSha256": "<context-sha256>",
  "channel": "pong-gospel",
  "templateId": "<that-channel-template-id>",
  "title": "用户确认的准确标题",
  "subtitle": "",
  "instructions": "",
  "approval": true,
  "retry": false
}
```

`retry:true` is only for a deliberate new attempt after a **confirmed failed** request. Do not retry an uncertain accepted request automatically. Use GET collection first. Missing template, changed source or wrong channel must remain explicit errors.

Public bridge jobs include `id,status,progress,folder,taskId,channel,title,subtitle,instructions,templateId,templateRevision,videoPath,videoSha256,approvedAt,deadlineAt,warnings,sourceFrameAvailable,error,delivery` where applicable. Statuses include `dispatching`, `watching`, `uncertain`, `delivery-error`, `failed`, `delivered`. On successful delivery, `job.delivery` contains `{folder:"out/thumbnail-final-<id>",taskId,...}`. Native task IDs belong to HQ; do not confuse them with request IDs.

## Claude backend → Codex engine (loopback 4341)

Fixed engine: `D:\AI OFFICE\studio\sermon-design-server.mjs`. Runtime root: `D:\AI OFFICE\.studio\sermon-design-runtime`.

- `GET /api/runtime`: verify `app: "sermon-design-engine"` and exact source/runtime paths.
- `GET /api/thumbnail-design/capabilities`: schema 1, four options and supported dimensions. Route availability is not proof of successful live model access.
- `POST /api/thumbnail-design/jobs`: creates one durable request.
- `GET /api/thumbnail-design/jobs/:requestId`: reads that exact request.

Generation body:

```json
{
  "requestId": "<stable-unique-request-id>",
  "title": "准确标题",
  "subtitle": "",
  "width": 1080,
  "height": 1920,
  "instructions": "频道模板说明与本次补充要求",
  "template": {"name":"template-name","dataUrl":"data:image/png;base64,..."},
  "sourceFrame": {"name":"approved-video-frame.jpg","dataUrl":"data:image/jpeg;base64,..."},
  "provenance": {"folder":"out/example","taskId":"tN","channel":"pong-gospel","templateId":"...","templateRevision":1,"templateSha256":"...","videoPath":"video.mp4","videoSha256":"...","approvedAt":0,"sourceFrameAvailable":true}
}
```

`sourceFrame` is optional; unavailable extraction must remain disclosed. The bridge obtains provenance from the real selected source, not hard-coded example values. Accepted dimensions: 1920×1080, 1080×1920, 1080×1440. Templates: PNG/JPEG/WebP, ≤15 MB. The existing bridge supplies JSON content type and the engine's loopback Host/Origin; retain existing authentication/origin boundaries.

Response is **`{job}`**. Successful engine jobs use `status:"succeeded"`; **`job.files`** contains four PNGs plus `thumbnail-manifest.json`, with absolute owned `path`, `name`, `size`, `sha256`, `format` and PNG dimensions. `job.request.provenance` retains the original bindings; individual model receipts are in `job.provenance`. Backend success is distinct from final user approval.

The Python bridge verifies frozen request SHA, returned brief/provenance, owned file paths, sizes and hashes, then creates the native final package. This is polling plus managed local file copy on the same machine, **not an outbound callback/webhook to this chat**. Do not point HQ at this Codex conversation or substitute another image provider.

## State, review and limitations

- HQ ledger/templates/frozen requests: `D:\Agents HQ\hq\thumbnail-design\`.
- Engine outputs: `<runtimeRoot>\.studio\thumbnail-design\jobs\<requestId>\output\`.
- HQ final package: `D:\Agents HQ\out\thumbnail-final-<requestId>\`, with `thumbnail-final.json` and `channel.txt`.
- Do not overwrite older exports, copy `followups.json`/publication state, bypass final checks, or replay model requests on restart.
- Current locking order is bridge RLock → task lock. Keep this order to avoid deadlocks and approval/revision races.
- AI rasters still require visual review for exact text, identity and template fidelity. No editable PSD/Canva-layer promise.

Last observed activation: updated HQ Python routes and the real upload UI loaded successfully after normal app restart. Both channels had no uploaded templates. The image engine was not listening after that normal HQ lifecycle; the bridge is configured to start the fixed missing engine on explicit generation, but first real generation was not verified. An attempted automated engine stop/start was rejected before execution with `blocked by policy`; no bypass was attempted. Do not represent a fixture test as production generation or bypass that rejection through a substitute command. Report any required user action explicitly.

Validation already performed: 20 thumbnail Python tests; 22 existing sermon tests passed, 1 skipped; 10 HQ JS routing tests; 34 engine/adapter checks passed, 1 skipped; a real Python→HTTP→Node→file-delivery integration with a **fake image provider** passed. Supplemental independent review covered seven request-integrity cases. There has been no real thumbnail generation, no automatic posting, and no final user artifact approval.

Evidence: `D:\AI OFFICE\.studio\intake\hq-channel-thumbnails-20261027\`, especially `independent-review.md`, `review-supplement.md`, `cross-runtime-validation.json`, `verification-final.json`, and `live-activation.json`. Last reviewed `thumbnail_design.py` SHA-256: `B3540F44F6ADA4F575E23EF1A3934472379318A5263CAEF81102C9E703930BF3`; compare before assuming these historical results cover newer edits.

Useful verification commands (use the existing Python environment):

```powershell
& 'D:\AI OFFICE\.venv\Scripts\python.exe' -m unittest discover -s 'D:\Agents HQ\hq\tests' -p 'test_*.py'
node --test 'D:\Agents HQ\hq\tests\thumbnail-routing.test.cjs' 'D:\Agents HQ\hq\tests\sermon-design-routing.test.cjs'
```

Priority: fix and visually verify Back to HQ first; retain a rollback point for the changes you make. Then verify template → user-approved video → real image generation → native Final review using actual owner-supplied inputs, with no unsolicited publishing. Any required Codex-side contract change should be returned as a concrete handoff rather than concurrent edits to both codebases.
