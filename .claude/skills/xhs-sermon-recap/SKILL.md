---
name: xhs-sermon-recap
description: Adapt a user-selected sermon poster into two separate editable 1080 x 1440 RedNote images, an original-title main image and a matching 信息回顾 / Sermon Recap cover. Use for XHS Sermon Recap Pro, not generic sermon video summaries or other brands' social packages.
---

# XHS Sermon Recap

Own the selected poster's portrait adaptation. Default output is exactly **two independent 1080 x 1440 (3:4) images**, Main and Cover, rather than four alternatives or a collage. Respect an explicit Main Only / Cover Only request. This specifically requested pair overrides the general four-image preference for this workflow.

## Select and inspect the source

Read current shared `Brand rules` and the scoped sermon brief/reference records, without writing shared memory. Obtain the user's selected poster and its exact Chinese/English titles. Use the selected project/revision/design ID when available. If no poster was selected, get that essential selection before adapting; do not infer approval or choose one silently.

Inspect the actual source and record its palette, typography, texture, subjects and unknowns. Preserve the chosen poster's visual identity. Do not import another brand's financial-media rules, invent subjects, reimagine faces or claim to know an unidentified font. Keep original uploads and all prior revisions unchanged.

Use the installed **D:/Agents HQ → Creative → XHS Sermon Recap Pro** and the same authenticated Studio bridge. Read `D:/Agents HQ/docs/sermon-design-studio.md` and `D:/AI OFFICE/docs/SERMON-DESIGN-STUDIO.md` for current API/provider capabilities and limits. A native Studio export already creates its review delivery; do not add duplicate board tasks or bypass the bridge by editing task files. If automating, inspect current `/api/sermon-design/capabilities` and API contracts first. The existing title project's `/api/sermon-design/projects/{id}/recap` handoff accepts the selected design and current revision, creating a new linked XHS draft rather than replacing the landscape original.

## The two artwork contracts

**Main Sermon Image:** visible wording is the exact original Chinese and English sermon titles, preserving original spelling, punctuation and capitalization. Keep the title group in the upper **20–35%** of the canvas; retain at least the lower **40%** as usable space for later content, adjusting composition around the actual source. Do not insert 信息回顾 or Sermon Recap on Main. Keep meaningful subject elements, proportions and identity; avoid clipping essential objects or faces.

**Matching Recap Cover:** visible wording is only **信息回顾** and **Sermon Recap**. Never retain the old sermon title, including text baked into a background or subject crop. Match the selected poster's palette, texture and visual language while recomposing for portrait. Do not add a date, speaker, verse, logo, old title or extra labels.

Use real vector Chinese/English text where it preserves the intended typography and supplied wording. When the source uses unknown/custom title lettering, preserve complete original title pixels as a movable title group, or disclose the font substitution; do not pretend retyped text is the original lettering. Keep text, subject and background independently movable wherever actual source material supports it. Every adaptation stays editable and versioned; a raster crop remains raster, even inside an editable source project.

## Layered and flattened source limits

For a native editable poster, use the actual source-design handoff. The current app can render its textless background and preserve rendered title glyph pixels as a proportional transparent title group. Existing isolated subject assets can be carried forward unchanged. This known source conversion does not require OCR and is not a claim of automatic layer extraction from arbitrary images.

For a flat PNG/JPG/WebP, the app does **not** implement OCR, automatic subject/background separation, PSD layer parsing, editable PDF parsing or native Canva import. Do not fabricate extraction results. Supported layer inputs are transparent PNG and self-contained safe static SVG; export unsupported sources to those formats first. Request exact titles or usable source layers/crops only when needed for the chosen deliverable.

- A manual title rectangle preserves source pixels and must include the entire original title. Confirm its completeness before export; a crop may retain a rectangular background because automatic transparency removal was not performed.
- A manual text-free subject/body crop preserves source pixels and aspect ratio, but is not a background-removed layer. Inspect that it includes essential subjects and does not bring the old title onto Cover.
- A missing subject layer/crop is a real limitation: supply one, or obtain the user's explicit acceptance of a background-only fallback. Do not silently claim subjects were preserved. Keep unrelated preparation available while essential inputs are missing.
- Never reuse the entire flattened poster as Cover's background, since that leaks the old title. Use a clean textless background, a text-free body crop, or a genuinely successful verified provider edit.
- Source-sampled colors and procedural artwork are a disclosed local fallback; they are not reconstruction of original textures or generative outpainting.

## Image capability and delivery

Use a requested ChatGPT built-in image route only if the host currently exposes its verified tool/handoff. Claude has no implicit access to `image_gen`; an installed signed-in Codex CLI alone does not prove automatic image transport. Use the maintained Studio docs for an actual supported handoff and record returned provenance; do not invent a CLI command/model or call a draft generated. An actually available built-in route needs no separate API key. A separately configured API provider is optional when the user chooses it. If unavailable, report the gap and preserve the draft rather than silently substituting a different generation method. Do not start Pulse, unrelated model runs or held productions.

Export Main and Cover as separate **1080 x 1440 PNG and JPG** files, with their editable source and a source ZIP. Do not deliver them as one canvas or rely on a ZIP alone. Verify actual successful exports, dimensions, file sizes/hashes, exact visible text, top title placement and bottom usable space, proportional source sizing, subject completeness and absence of old-title pixels on Cover. Inspect both rendered rasters; automated checks do not prove full subject preservation, texture fidelity, visual quality or contrast over uploaded/generated imagery.

Pass outputs and source evidence to a separate brand checker in coordinated production; log corrections against this job and preserve prior exports. Native Claude HQ **out/** and **Creative review / Waiting for your OK** are the final handoff. Include exact source/project revision, independent download links, provider provenance, crop/font limitations and review findings. Keep the current version **awaiting_approval** (native board `review`) until the user's explicit OK for that version; a successful render or reviewer PASS cannot complete it. No posting, upload or file sending is authorized by this adaptation skill.
