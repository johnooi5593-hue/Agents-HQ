# Sermon Design Studio in Creative

## Speaker integration correction — 2026-10-28.2

New picture-style service editions use the v4 frozen portrait/name contract. Internal gathering labels (PJ Mandarin, Cantonese Service, CS, CN, KJ and other row names) are routing/UI metadata only: omit them from the visible poster. Place the supplied Chinese and English speaker names together directly beside/below that speaker's portrait in the frozen adjacent name region; never detach them into the date/footer group. Keep the same anchor across the selected artwork group. Exact names, dates and full 12-hour time ranges still come only from checked fields.

Prepare a larger upper-body portrait from the original photo. The pinned local HyperFrames CPU segmenter supplies transparency only; final RGB comes from the original decoded photograph, with alpha=min(original alpha, segmentation alpha). Preserve the original upload, derived cutout, owned mask, original/cutout RGB hashes, crop and immutable provenance. Both names, titles and date/time remain image lettering; deliver a complete flattened PNG/JPG, with no editable text/name cards. The selected master plus all ten registered style references remain actual generation inputs; original speaker photos never go to the image model. Cutout failure must be reported before paid generation, with no opaque-photo or regenerated-face fallback. Real faces, hair, clothing, Chinese lettering, portrait/name adjacency, overlap and integration require visual review; local alpha extraction does not guarantee perfect edges or art direction.

This supersedes earlier new-edition instructions that kept rectangular photo backgrounds, printed row labels, or placed names in a global footer. Historical frozen editions and earlier exports remain unchanged; prepare a fresh edition from the existing checked parent plan. The fingerprint includes the versioned cutout runtime/model contract, preventing reuse of an older no-cutout edition. New portraits freeze a bottom-only 16% torso alpha fade to avoid a hard crop edge; head/face pixels stay fully opaque. Historical no-fade editions remain unchanged. A strictly matched prior generated picture can be reused for an alpha-only polish when exact titles/event copy, speaker, master hash and layout match; record the source revision/background hash and never claim a fresh image call. Current evidence: `.studio/intake/sermon-portrait-blend-20261028/` (local actual-Hiew proof, hashes and software checks). Progress cards retain their accepted order and DOM identity during polling; display actual workflow checkpoints, or an indeterminate status when no numeric progress exists. Do not claim a percentage is an image-model ETA. Pulse stays paused; no publish or approval is implied.


## Latest default: complete speaker/service picture (2026-10-28)

The user clarified these ten poster images are the DEFAULT speaker/name/date/time integration references, not an optional information-card preset. New service editions use complete reference-led AI picture mode, including when reopening an old editable parent plan. The draft selects it automatically; existing finished/frozen child editions are retained. Real generation consumes the selected master plus the registered ten-image style sheet and two focused examples. No unrelated example people/logos/event wording are copied. Exact checked service copy is integrated into picture lettering, original speaker pixels are composited separately, and final PNG/JPG/SVG/HTML exports are flattened pictures rather than editable text cards. Same-group style/portrait placement is frozen. This supersedes the earlier NEW-plan classic/editorial default; those modes remain for historical compatibility only.

Default provider remains the configured signed-in ChatGPT image route, without an invented per-call model variant. Actual spelling, stylistic integration and title/portrait overlap require final visual review. Source photos keep their background unless already transparent. No image generation, task approval, upload, publication or Pulse run is triggered by configuration or page opening. Current actual references: `D:/AI OFFICE/references/sermon-service-info/20261028/profile.json`; technical evidence and original guide archives: `.studio/intake/sermon-service-picture-20261028/`.


## Stage 1 design groups and compact navigation (guide 2026-10-27.5)

Before generating artwork, choose **How many different posters?**:

| Arrangement | Stage 1 artwork drafts | Choices in each draft |
|---|---:|---:|
| All 6 the same | 1 group for all six services | 4 separate designs |
| Friday different | 1 Friday group + 1 group for the other five | 4 separate designs per group |
| All 6 different | 6 individually named service groups | 4 separate designs per group |

Click **Prepare design groups**, then open one group, enter/check its exact Chinese and English titles, add its references and choose **Generate 4 designs**. A group is an ordinary sermon-title project with its own references, settings, version history and four independent image choices. Preparing groups works before any source design exists, with incomplete titles allowed as drafts. It creates no model job, image, export or approval task. Generating is a separate deliberate action for each group; preparation never silently launches 4, 8 or 24 paid/image jobs.

Select the required complete-picture generation provider in that draft. References are initial owned copies of the parent's supplied reference assets; each draft can subsequently use its own references and titles. Speaker photos are copied as original owned subject assets only for that group's member services. Other rows do not receive invented or foreign photo IDs. Reopening the same grouping reuses active drafts and preserves their edits; switching grouping retains the previously prepared groups rather than resetting them. Trashed drafts are not reused.

Choose the preferred concept, then open **Stage 2 / After your master design**. Only that group's member services are displayed/prepared. Matching member services retain the exact selected master pixels and consistent event typography, with their individual original speaker photos and checked service details. The other-five group uses its first member (PJ Mandarin), not the unrelated Friday row, as its artwork/layout anchor; unrelated rows cannot change that group's shared font sizing. Existing direct same-master and saved service editions remain supported.

**Location is optional.** An empty location is omitted from the exported picture; a supplied location retains its exact wording. Review exact dates, full 12-hour AM/PM time ranges, both supplied Chinese/English speaker names and each member's original photo before Stage 2 preparation. Names are never translated or inferred. Selecting a design or confirming metadata is not final approval; every delivered version still needs the user's final OK in its native HQ review task. No Pulse update, recurring generation, publishing or upload is started by this workflow.

The compact Studio keeps the active artwork/project and primary actions visible, offers group cards for opening each draft, and folds advanced service details into Stage 2. Use one group at a time: prepare → open → add titles/references → generate → choose → check member details → inspect final files. Progress must come from actual accepted jobs; draft cards are not evidence of workers running.

The checked group API is POST `/api/sermon-design/projects/:id` with `{serviceAction:'prepare-groups', mode:'all-same'|'friday-different'|'all-different', expectedRevision}`. Its response contains the updated parent, child `serviceProjects` and group memberships. `prepare-independent` remains the six-independent-group alias. Parent group mapping and child identity are server-owned; a stale revision must be reopened rather than overwritten. This documents the implemented route, not proof that an older running server has reloaded it; check current capabilities and perform a live smoke check before announcing availability.

### Standalone post covers

In Claude HQ's Thumbnail Studio, select a channel and template, enter the exact post headline and optional subtitle, choose the output size and optionally upload this post's person/subject reference. **Generate 4 separate covers** starts a standalone cover job without requiring a finished video. Saving a channel template does not start generation. Inspect/download each separate result and select the preferred cover; selection does not publish or replace the native final-review decision. The template library is secondary to the create-and-choose flow. Never treat unrelated people or old wording in a template as the requested subject/copy.

### Pending integration

Manual speaker-photo and Google Sheet sync is now available through preview and checked apply. Follow the manual weekly duty sync section; no recurring sync or automatic artwork generation is enabled.



## Six service editions after the master design

### Weekly schedule, 12-hour time and individual speaker uploads

New untouched service plans use the server's Malaysia-time weekly preset. Starting from the nearest Friday whose 10:00 AM start has not passed, the six rows are:

| Row | Exact default gathering name | Day | Display time |
|---|---|---|---|
| 1 | Cantonese Service | Friday | 10:00 AM–11:45 AM |
| 2 | PJ Mandarin | Saturday | 5:00 PM–6:45 PM |
| 3 | PJ Billgual | Sunday | 10:00 AM–11:45 AM |
| 4 | CS | Sunday | 10:00 AM–11:45 AM |
| 5 | CN | Sunday | 10:00 AM–11:45 AM |
| 6 | KJ | Sunday | 10:00 AM–11:45 AM |

These are supplied gathering names, not inferred venue addresses. `PJ Billgual` preserves the user's supplied label. Venue and both speaker names remain explicit user inputs. The helper uses `Asia/Kuala_Lumpur`, including same-Friday start cutoff, month/year boundaries and leap dates. The whole Friday–Sunday set advances together; it never selects each weekday independently into different weeks. Stored times stay canonical HH:MM; UI and final pictures display 12-hour AM/PM ranges. An end time must be later than the start on the same date. No overnight service is inferred.

Opening a new untouched plan fills this preset from current server capabilities. Reopening a saved plan or editing dates manually does not move it to another week. **Use upcoming Friday–Sunday dates** explicitly refreshes the schedule and clears the information confirmation; it does not generate images. This is editor prefill, not a scheduler or a weekly production run. Existing folder/Pulse automations remain unchanged.

Each gathering has its own single-photo **Upload photo** control. The returned owned asset is bound only to that named row. Before final service preparation, new plans require a speaker photo and the corresponding supplied Chinese/English names for each selected service; an artwork group checks only its owned members. Copy-previous venue/name controls do not copy photos, dates or times. Shared artwork mode keeps original speaker pictures separate while using the same placement/scale rules.

For the same-master batch, event typography is derived across the six checked rows, then frozen with the child editions: date/time/venue/name font sizes, positions and formatting stay consistent. Long supplied fields can reduce a shared font size and still require legibility review. The child reuse fingerprint includes this typography contract, time formatting, date range and photo requirements, so an old differently formatted child cannot be silently reused.


### Same approved design, with bilingual service information

New service plans default to **Keep the same approved design for all 6**. The exact chosen master artwork is copied for every service: background, sermon title lettering, colours and layout do not regenerate. All rows share the selected master and photo/layout settings. Only the supplied event details and original speaker photo differ. This protected mode disables AI regeneration of the service children. Turning it off explicitly re-enables the earlier different-sermon modes; image-generated title revisions can then vary and need fresh review.

Fill **Date**, **Time**, **Venue / 地点**, **Speaker name · 中文姓名** and **Speaker name · English name**. Venue accepts the exact supplied Chinese/English wording in one field; names have two independent fields. Nothing is automatically translated or inferred. Location is optional and omitted when blank; a service using a speaker name or photo needs both supplied names. Leaving all speaker fields/photo empty omits the speaker. Old saved single-name service editions remain intact. The summary and export checks include both names and the venue. Copy-previous controls never copy dates or times.


In either HQ, open the same Sermon Studio project. Generate the first four concepts as before. On the chosen concept, click **Use as service master** to open **Service Editions**. This is a creative-direction selection, not final approval of any exported image.

Choose one of three modes:

- **All same:** six services share the Chinese/English sermon titles and selected master direction.
- **5 same + 1 different:** select the exceptional service by its name; its titles/design can differ.
- **All different:** each service has its own exact titles and selected master direction.

Name all six services. Each has its own calendar date, displayed 12-hour time range, speaker name and original speaker photo assignment, regardless of grouping. Grouping only shares sermon titles/master selection. The original individual title drafts are retained when changing modes. Dates are explicit YYYY-MM-DD and times HH:MM; the app never infers a missing date, speaker or schedule. Check the six-service summary and deliberately confirm the master direction and supplied information before creating images.

Upload speakers using **Original speaker photos**. Select one photo for each service; the same supplied person can be reused. Source bytes are copied and checksum-verified, never passed to the image provider. Proportional placement preserves the original image and face, without beautifying, warping or face regeneration. Transparent cutouts integrate most cleanly. Ordinary rectangular photos retain their background; this release does not automatically remove backgrounds or claim seamless photographic extraction. Choose left/right, photo scale and information tone. A sample needs visual review because existing flattened artwork may be covered by the added photo/information.

Use **Create first service sample** to inspect one service, then **Create all 6 service images** when ready. Each service gets one child project and one independent 3840×2160 PNG/JPG, plus its own ZIP/source. Identical titles reuse the actual selected master pixels without a new image call. Different titles require one real image revision using the selected master as reference; old embedded lettering is not covered with replacement title text. New artistic lettering still requires visual spelling review. Exact event labels, dates, times and speaker names are composed from the supplied fields and checked against the frozen service record.

Only two service renders/generations execute at once; remaining accepted jobs queue in the office. Accepted jobs are tracked on leaving the page, and each completed export follows the existing Claude HQ review delivery. Repeating preparation reuses the exact unchanged child. A partial failure leaves successful/accepted versions intact and shows the affected service; it does not automatically repeat a paid generation. Download independent files from each service project. This release supplies a ZIP per service, not a combined six-service ZIP.

Change service information in the parent plan and prepare a new child version; old images remain available. Artwork changes, regeneration or restoring different master artwork invalidate prior confirmations. Metadata-only categorisation and child bookkeeping preserve the reviewed master. Adding a speaker photo requires a fresh information check. No checkmark approves the final HQ task: each concrete delivered version still awaits the user's final OK.

API capability: `serviceEditions.enabled`. Existing POST `/api/sermon-design/projects/:id` supports `{serviceAction:'save-plan',plan,expectedRevision}` and `{serviceAction:'prepare',rowId,expectedRevision}`. Preparation returns `{project:master,edition:child,reused}` and starts no model job. Use the child's existing `/generate` and `/jobs/:id` flow for delivery; no new Python bridge routes or phone pairing are needed. A service edition's titles, source identity and checked schedule/photo inputs are immutable. Studio uses the same canonical store for Claude and Codex HQ.



## Project organisation and reliable Back to HQ



Studio **Projects** now supports search, custom categories, category filters and separate **Projects / Trash** lists. Use the category field and Save to organise a project. A category-only change preserves the exact artwork export and review record; Download reuses its existing files when the immutable artwork snapshot is unchanged. Artwork edits still require a new version and final OK.



**Delete project** asks for the named project and moves it to reversible Trash. Original references, rendered files, historical versions and native review records are retained. Restore returns it to the project list. Trash is read-only; restore it before editing, generating or exporting. An actively generating project cannot be moved or categorised mid-run. No permanent purge or automatic deletion of existing tasks is provided.



Both header home links now run **save draft → return to the current HQ**. Codex-origin Studio returns to `/#office`, Claude-origin Studio returns to `/`. A failed save keeps the draft on screen; a clean accepted background job does not block departure or restart generation. Modern Studio takes ownership of navigation before the legacy Claude suffix is appended, and coordinates with its existing unload wrapper. Back is separate from the final-review link.



New API: GET `/api/sermon-design/projects?includeDeleted=1`; POST `/projects/:id/trash` and `/untrash` with `expectedRevision`. Existing authenticated bridges also support the bounded compatibility POST `/projects/:id` body `{management:{action:'categorize',category:'PJ'},expectedRevision:3}`, or actions `trash` / `untrash`. This uses the same single writer, per-project locks and revision checks. Capability `projectManagement` exposes categories/trash/restore; old engines leave these controls unavailable rather than pretending a write succeeded.



The prepared Codex desktop quit fix defers stopping local services until Electron accepts closing every window. Canceling unsaved-page closure keeps the service online; it no longer shuts down the server first and leaves a blocked window behind. This desktop-process change loads only on a normal full App restart. A Studio browser refresh loads the UI changes but cannot recover a stopped Codex4317 service.





## Work on design and video at the same time



Use **Codex HQ → Design → Open design workspace** for sermon poster/XHS work. It opens a separate studio window; keep **Claude HQ** available for video commands, edits and review. Both artwork entries still use the one canonical project engine and return version-specific final OK to Claude HQ. Image generation is a separate Codex image job and does not occupy the Claude lead conversation. Office computer/services must remain running.



After an accepted generation, Studio tracks the original job in its background jobs panel. You can leave the page, return to HQ, open a different project or prepare another draft. The generating project stays protected against duplicate generation and conflicting edits. Background polling must never replace another draft or overwrite unsaved changes. Reopening reads the same job; it does not generate another set. Offline/missing-job states are reported honestly. This does not allow multiple simultaneous messages in Claude's single active lead turn or guarantee unlimited hardware/model concurrency.





## Complete-picture default (2026-10-27)



New Sermon Title projects default to **Complete picture · designed lettering** (`typographyMode: image`). ChatGPT/image generation creates each entire finished poster, including artistic Chinese and English lettering. Four separate directions are cinematic, contemporary minimal, energetic and experimental editorial. No local title text or template panels are overlaid on the provider picture. The English title is a substantial part of the composition. Only supplied titles appear; sample wording, people and logos are not copied.



PNG/JPG are the primary outputs, individually downloadable at 3840×2160; native generated dimensions remain recorded separately. Check Chinese characters, English spelling, safe margins, identity and reference fidelity visually before final OK. No OCR accuracy or artistic-quality guarantee is implied by the automated checks. A picture cannot be edited character by character. Actual separate supplied layers may be retained, while SVG/HTML wrappers of a flattened result remain picture containers. A title-field change blocks stale-picture export; update the affected pictures before delivery. Local fallback and empty layout-only requests cannot silently replace full-picture generation.



Choose **Editable text · optional** only when that is wanted. Historical saved editable projects retain their layout and assets. XHS from a complete picture keeps the original source and exact title fields as a new draft; it does not pretend to extract transparent lettering or subject layers. Use the flat-source title/subject controls or supply actual isolated layers before the existing XHS workflow.



The new UI checks the engine's `titleArtwork.completePicture` capability before starting. If the running backend predates this update, it refuses generation and asks for the original App's engine restart. Code tests do not mean the installed running process has reloaded. Do not restart while the user has deferred it.





## Shared with Codex HQ



Both HQ entries can use the same sermon-poster/XHS projects. In Codex HQ, the saved shared-artwork connection forwards only the bounded artwork routes to this Claude HQ bridge; the existing image engine remains the only project writer. In either Studio, **Shared projects** opens the common list and actual accepted-job progress. Open the same project to continue editing; changing HQ is not a reason to generate again. Version conflicts require reopening the latest revision.



Final OK stays here in Claude HQ. The shared hub links to this native review task and has no approval or generation action. Its phone review link uses a separately verified private HTTPS address, never phone-local127.0.0.1. Existing tasks, login, pairing, other brands, frozen attempts and paused productions remain separate and unchanged. An unavailable connection reports an error rather than silently creating an independent local project.



The connection setup and local read-only status API are documented in `D:/AI OFFICE/docs/SERMON-DESIGN-STUDIO.md`. These are user-requested workflow changes; they do not resume paused Pulse learning.



1. Open **Creative → Overview → Create sermon poster / 讲道海报**.

2. Enter the exact Chinese and English titles, then upload reference images.

3. Choose **Generate 4 Designs**. Review the four separate options, adjust text

   or layout, and download the selected files or ZIP.

4. Finished versions also appear in this Claude HQ's **Creative → Waiting for

   your OK**. Review and approve the concrete version there.



For typed or microphone commands, start with an exact first line:

`Sermon Poster`, `Create sermon poster`, `制作讲道海报`, or `Sermon Title 16:9`.

Follow it with `Chinese:` / `中文：` and `English:` / `英文：` title lines. This

opens the editor so references and the final brief can be checked before starting.

Ordinary requests and quoted examples continue through the existing lead.



For RedNote, choose **Make XHS recap** on a selected sermon design, or open

**XHS Sermon Recap Pro** and upload a finished poster. Review its two separate

1080 × 1440 main/recap outputs, correct flattened-artwork limitations when shown,

then export the independent images.



The editor uses this Agent HQ's existing login and phone connection. Its fixed

local image engine is `D:\AI OFFICE\studio\sermon-design-server.mjs` on loopback

port **4341**. It saves editable projects under

`D:\AI OFFICE\.studio\sermon-design-runtime`; it does not open the older office's

task store. The first design API request can start this exact installed engine

when its port is closed. A different or outdated service on that port is left

untouched and reported. Node.js must be installed on the office computer.



The default image provider is **ChatGPT through the signed-in office Codex

account**. It runs a separate bounded Codex job on the office computer, with

progress and receipts recorded for this assignment. It does not inject a message

into the current conversation. No separate API key is required for this default

route. The built-in image model variant is unknown unless its actual execution

receipt identifies it; the app must not label it as a particular GPT Image

version without that evidence. If access cannot be verified, the app reports the

failure rather than claiming an image was generated.



The **optional OpenAI API provider** can be configured on the server with

`D:\AI OFFICE\.studio\sermon-design\provider-config.json` (ignored private

configuration), or the documented server environment variable. Details are in

`D:\AI OFFICE\docs\SERMON-DESIGN-STUDIO.md`. Keys are never entered into the

browser. The optional API is used only when deliberately selected. Editable

typography and final composition use the native font/image renderer. A manually

selected procedural background is identified as local composition.



After a successful export, each file's size and SHA-256 are checked. The delivery

is copied into this office's own `out/sermon-studio-<project>-r<revision>-a<attempt>`

folder, and a **Creative → Waiting for your OK** task is added exactly once for

that export version. Provider receipts and native rendering provenance remain

with the delivery. Open the review task to inspect the independent artwork and download its

files. **Edit artwork in Design Studio** reopens the editable project; edits

create a new version and retain the prior delivery. The normal Approve action

moves the reviewed folder to `approved/`. Nothing is posted automatically.



The delivery index is `hq/sermon-project-links.json`. Keep it with the office's

task board and out/approved folders. Missing or changed deliveries are reported

instead of silently overwritten, and a removed review task is not recreated

automatically.



Accepted generation/layout jobs are also recorded in the ignored

`hq/sermon-pending-deliveries.json` ledger. A bounded background watcher collects

successful exports even if the phone closes before its next progress poll. It

only reads the already accepted job, checks its exact saved revision, and imports

the verified files once. It never repeats a generation request or launches an

image/model job. Watches resume on the next office startup or Studio visit and

end after at most 30 minutes; failures and delivery errors are recorded honestly.

Reopen a saved project to manually collect a result after a delivery error.



Validation commands (isolated temporary fixtures, no real tasks changed):



```powershell

python -m unittest discover -s hq/tests -p test_sermon_design.py -v

node --test hq/tests/sermon-design-routing.test.cjs

python -m py_compile hq/server.py hq/sermon_design.py

node --check hq/hud.js

```


## Manual weekly duty sync — 2026-10-27.6

Use **同步本周资料** to read the configured 证道总览 Google Sheet and match original photos in `X:/My Drive/NLRCC/Preacher Photos`. This is manual preview, then explicit **Apply checked details**, never a schedule or image-generation trigger. The source currently provides a public CSV export; no API key is needed for that read. If access changes, report it instead of substituting data or asking the user to make a private Sheet public. The configured source's C/D columns are Chinese/English **speaker names**, never sermon titles.

Friday through Sunday use the ongoing Malaysian service weekend; Monday through Thursday use the upcoming Friday. Never choose the last/farthest row. Display the source service mapping, week, exact bilingual names and original photo candidates. Multiple candidates require a choice; a previously confirmed name-to-file match can be suggested for checking. Names marked TBC are skipped with a warning. No match allows names/date only and later manual upload; changing a speaker without a replacement clears the previous speaker photo. Never infer a face identity from a filename or claim automated facial verification.

Only Apply changes the current project's date/names and checked original photo assignments; title artwork, sermon titles, references, venue and edited time ranges stay unchanged. A group child syncs only its owned services. Existing other group drafts do not silently inherit later parent changes: open and sync each existing group if needed. Clear information confirmation and require another summary check before image creation. Preview is bound to the project revision, expires in 15 minutes, and changed original bytes require another preview. Frozen source URL/hash/read time accompany the apply summary. Preserve prior revisions, original facial pixels, final HQ review and user OK.

Suggested flow: sync and check the six-service roster; prepare 1/2/6 artwork groups; open each group, supply titles/references and generate four separate choices; select one design; check the group's service information/photos; create service pictures; review/download in Claude HQ. Existing approved artwork can still use the direct-master service workflow without creating new art concepts.

- **2026-10-27.6:** User selected manual weekly roster sync. Added exact speaker-column mapping, current-week preview, candidate photo confirmation, original-byte checks, scoped explicit apply and source provenance. Retains prior useful rules and final user OK; Pulse remains paused. Prior bytes and checks: `.studio/intake/post-covers-and-independent-sermons-20261027/duty-guide-change.json`.
