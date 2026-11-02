---
name: xhs-sermon-recap
description: Adapt a user-selected sermon poster into two separate complete-picture 1080 x 1440 RedNote images, an original-title main image and a matching 信息回顾 / Sermon Recap cover. Use for XHS Sermon Recap Pro, not generic sermon video summaries or other brands' social packages.
---

# XHS Sermon Recap

Revision 2026-10-29.2 — explicit user-confirmed XHS picture and speaker workflow. This overrides the previous editable-text/no-speaker default for new picture projects; preserve old saved and frozen versions.

Own the selected poster's portrait adaptation. Default output is exactly **two independent 1080 x 1440 (3:4) images**, Main and Cover, rather than four alternatives or a collage. Respect an explicit Main Only / Cover Only request. This specifically requested pair overrides the general four-image preference for this workflow.

## Select and inspect the source

Read current shared `Brand rules` and the scoped sermon brief/reference records, without writing shared memory. Obtain the user's selected poster and its exact Chinese/English titles. Use the selected project/revision/design ID when available. If no poster was selected, get that essential selection before adapting; do not infer approval or choose one silently.

Inspect the actual source and record its palette, typography, texture, subjects and unknowns. Preserve the chosen poster's visual identity. Do not import another brand's financial-media rules, invent subjects, reimagine faces or claim to know an unidentified font. Keep original uploads and all prior revisions unchanged.

Use the installed **D:/Agents HQ → Creative → XHS Sermon Recap Pro** and the same authenticated Studio bridge. Read `D:/Agents HQ/docs/sermon-design-studio.md` and `D:/AI OFFICE/docs/SERMON-DESIGN-STUDIO.md` for current API/provider capabilities and limits. A native Studio export already creates its review delivery; do not add duplicate board tasks or bypass the bridge by editing task files. If automating, inspect current `/api/sermon-design/capabilities` and API contracts first. The existing title project's `/api/sermon-design/projects/{id}/recap` handoff accepts the selected design and current revision, creating a new linked XHS draft rather than replacing the landscape original.

## Shared Claude and Codex HQ entry points

When Codex HQ reports `sharedHq.mode: claude-shared` in capabilities, its artwork routes forward to the same Claude HQ bridge and canonical image engine. Either entry can open/edit the same saved project; use **Shared projects** to inspect the original accepted job and native review status. Do not create a second project or run another generation merely because the user changes HQ. Reopen the current revision after a conflict; do not overwrite another window's changes. An unavailable shared office is an error, not permission to fall back to a second local writer.

Final version-specific OK remains in Claude HQ. Use the shared hub's verified desktop/private-phone Claude review link; never send Claude `tN` task IDs to the unrelated Codex task board or use a phone-local `127.0.0.1` link. The hub is read-only and does not approve, publish, retry, or generate. A saved watch record only identifies which job to query; show progress from its actual job response, and report missing/interrupted jobs honestly. Unrelated task boards, brands, Brain records and paused productions are not merged by this connection. See `docs/SERMON-DESIGN-STUDIO.md` (Codex workspace) or `docs/sermon-design-studio.md` (Claude workspace) for the current host setup.

## The two complete-picture contracts

Use `settings.xhsPicture.version: 1` for the new workflow, with independently assigned speakers, `mainSpeakerId` and explicit `coverSpeakerIds`. The actual backend capability `xhsPicture.version: 1` must be present before claiming the runtime supports it. Input fields remain editable facts; they are not editable typography layers over the final artwork.

**Main Sermon Image:** include only the exact supplied Chinese/English sermon titles, one round language badge selected for the service, and that service's original speaker portrait with supplied exact Chinese/English name(s). Carry both when provided; require at least one supplied name and never invent a missing translation. Titles lead in the upper region; portraits may fill the lower region. Place each name close to its own portrait and blend the person naturally into the chosen poster's palette, texture and atmosphere. Preserve original face/skin/hair/body identity and proportions. Do not impose the former 40% empty-bottom requirement on this speaker layout.

**Matching Recap Cover:** title wording is exactly **信息回顾** and **Sermon Recap**, plus the explicitly selected speakers' own portraits and exact names. Do not carry the original sermon title onto Cover. One or more selected speakers are allowed within supported limits; the two-person example is not an automatic selection or fixed count. Do not invent people or use the example speakers as current service data.

For both outputs omit date, time, location, church logo, service heading/internal service name, Bible verse and other copy by default. A language badge on Main is intentional. A user can explicitly ask for additional content; otherwise source service metadata must not leak into the picture.

These user references define layout/content, not a mandatory copied design: `D:/AI OFFICE/brain/references/xhs-speaker-layout-20261029/references.json` records the three actual source files and inspection. The current selected sermon poster governs colors, materials, artistic lettering and visual identity. Do not automatically reuse the example's blue checks, fruit, gold landscape, decorative crown, example text or faces.

Deliver each artwork as a complete flattened PNG/JPG. Do not add editable text overlays or a default layer-editing workflow. Exact lettering still needs visual spelling review. When image generation is used, keep its real receipt; original speaker RGB/face pixels are composited locally from the assigned source photos rather than regenerated. An image-backed SVG/HTML container is not editable recovered typography; keep such optional/internal assets distinct from the requested final raster downloads.

Support revision instructions and additional reference uploads. Revisions preserve selected identity and existing approved composition except for requested changes, save a new version, and require a fresh user OK. Do not automatically regenerate upon upload or selection.

## Source material and legacy compatibility

For legacy editable projects or supplied layered artwork, use the actual source-design handoff. The current app can render its textless background and preserve rendered title glyph pixels as a proportional transparent title group. Existing isolated subject assets can be carried forward unchanged. This known source conversion does not require OCR and is not a claim of automatic layer extraction from arbitrary images.

For a flat PNG/JPG/WebP, do not claim the app implements OCR, automatic subject/background separation, PSD layer parsing, editable PDF parsing or native Canva import. Do not fabricate extraction results. Supported layer inputs are transparent PNG and self-contained safe static SVG; export unsupported sources to those formats first. Request exact titles or usable source layers/crops only when needed for the chosen deliverable.

- A manual title rectangle preserves source pixels and must include the entire original title. Confirm its completeness before export; a crop may retain a rectangular background because automatic transparency removal was not performed.
- A manual text-free subject/body crop preserves source pixels and aspect ratio, but is not a background-removed layer. Inspect that it includes essential subjects and does not bring the old title onto Cover.
- A missing subject layer/crop is a real limitation: supply one, or obtain the user's explicit acceptance of a background-only fallback. Do not silently claim subjects were preserved. Keep unrelated preparation available while essential inputs are missing.
- Never reuse the entire flattened poster as Cover's background, since that leaks the old title. Use a clean textless background, a text-free body crop, or a genuinely successful verified provider edit.
- Source-sampled colors and procedural artwork are a disclosed local fallback; they are not reconstruction of original textures or generative outpainting.

## Image capability and delivery

Use a requested ChatGPT built-in image route only if the host currently exposes its verified tool/handoff. Claude has no implicit access to `image_gen`; an installed signed-in Codex CLI alone does not prove automatic image transport. Use the maintained Studio docs for an actual supported handoff and record returned provenance; do not invent a CLI command/model or call a draft generated. An actually available built-in route needs no separate API key. A separately configured API provider is optional when the user chooses it. If unavailable, report the gap and preserve the draft rather than silently substituting a different generation method. Do not start Pulse, unrelated model runs or held productions.

Export Main and Cover as separate complete **1080 x 1440 PNG and JPG** files. A ZIP may contain these independent pictures and a manifest; editable text sources are not required or the default. Do not deliver them as one canvas or rely on a ZIP alone. Verify actual successful exports, dimensions, file sizes/hashes, exact visible text, top title placement and selected portrait/name arrangement, proportional source sizing, subject completeness and absence of old-title pixels on Cover. Inspect both rendered rasters; automated checks do not prove full subject preservation, texture fidelity, visual quality or contrast over uploaded/generated imagery.

Pass outputs and source evidence to a separate brand checker in coordinated production; log corrections against this job and preserve prior exports. Native Claude HQ **out/** and **Creative review / Waiting for your OK** are the final handoff. Include exact source/project revision, independent download links, provider provenance, crop/font limitations and review findings. Keep the current version **awaiting_approval** (native board `review`) until the user's explicit OK for that version; a successful render or reviewer PASS cannot complete it. No posting, upload or file sending is authorized by this adaptation skill.
