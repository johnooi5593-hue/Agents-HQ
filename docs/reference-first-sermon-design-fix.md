# Reference-first sermon/service artwork — engine implementation handoff (2026-10-28)

## Owner request and observed mismatch

Owner-provided screenshots of **Agent HQ · Design Department** show a Cantonese service poster with controls labelled **Photo placement**, **Photo scale**, **Information text tone**, and a message **"Exact details are frozen for this version"**. Adjacent PJ services are labelled **"Same approved artwork"**. The owner reports that this workflow does **not** closely follow the uploaded visual reference. These screenshots do not establish the exact root cause, but they establish that the current controls are too limited to enforce the requested outcome.

**Desired default:** Every time the owner uploads/selects a reference image, use that image as the primary **visual authority**. Create the poster in the reference's visual language, while blending in the **original speaker photo**, **exact Chinese and English sermon titles**, **Chinese and English speaker names**, **service name**, **date**, **time**, **venue**, and any other **actually supplied** information. The literal text must not change; the composition is free to adapt. Identity preservation and reference fidelity are distinct acceptance gates.

A live image engine is installed separately at `D:\AI OFFICE\studio\sermon-design-server.mjs` (and the Codex-side design implementation). This repository's `hq/sermon_design.py` is primarily a bridge/proxy. Updating Claude agent prompts in this repository does **not** itself update that live engine or redesign already exported images. The Codex-side engine/UI changes below must be implemented and tested at the existing installed workspace, under its normal code ownership workflow.

## Priority and defaults

1. **Explicit current-user instruction** overrides everything.
2. **Uploaded/selected primary reference image** defines layout logic, image treatment, palette, typography feeling, lighting, texture, motifs, density, hierarchy and negative space. Store the reference ID/hash and selected priority. Do not silently substitute a prior approved artwork or preset.
3. **Provided text/data and speaker source** are immutable content input for this version. Field values must be copied verbatim (including Chinese characters, English capitalization, punctuation, date and time).
4. Existing service/channel brand rules apply where they do not conflict with the selected reference.
5. Generic visual styles/presets are only fallback when no reference is attached, or when the owner explicitly requests alternative styles.

The existing `Same approved artwork` behavior becomes **explicit opt-in** rather than an auto-selected default that defeats new references. An approved style can be reused only when the user selects it or the active service truly has no reference and the user approves reuse. Do not mix reference images or speaker photos between Cantonese, PJ Mandarin, PJ Bilingual, CS, CN or other services.

## Separate content lock from composition freedom

- **Lock content** per accepted generation revision: exact title fields, names, service/date/time/venue and speaker photo provenance. Reject accidental text mutation, hallucinated dates and field omissions.
- **Do not lock the whole artwork**: photo position/scale, visual hierarchy, title lettering scale/treatment, text placements, layered depth, masks, artistic accents and background composition should remain freely recomposable to fit the selected reference.
- UI copy should say **"Text and supplied details locked; visual composition follows your reference"**, rather than suggesting the overall poster is frozen.
- A new explicit correction to any field creates a **new version**, preserving the old output. No automatic silent changes to already approved details.

## Generation pipeline and rendering requirements

1. Inspect the **actual uploaded reference pixels**. Extract a concise design brief: anchor positions and hierarchy, title treatment, palette, textures, lighting direction, background motifs, apparent typography structure, negative space, and speaker placement rules. Do not infer visual attributes from filename alone.
2. Build the generation/edit request with **the selected reference as the primary image input** and high image-fidelity priority. The requested result should remain recognizably close to this reference, not a generic "premium sermon poster" from a fixed house style. Preserve its main design identity, with necessary space for additional requested details.
3. Treat the original speaker photo as a provenance-bound asset; ideally composite the **original portrait/face pixels** onto the composition. Do not ask an image model to redraw or beautify the speaker's face. Use proportional sizing, natural feather/matte integration, ambient edge light and depth matching the reference, without pasted-on cutout appearance.
4. **Type exact text after image generation** whenever possible using font-backed editable text layers, rather than relying on AI-generated exact Chinese/English glyphs or dates. The output must contain each supplied field exactly once. Do not add labels/content that the owner didn't supply.
5. Chinese title should feel intentionally art-directed and match the reference's lettering treatment; English title should be integrated below/near it according to that reference, not arbitrarily typeset. Speaker names and event information should align with the reference's visual grammar. No generic bottom-strip overlay or separated portrait rectangle unless the reference actually calls for that.
6. If title/details are baked into a flattened reference image, the engine must either perform a verified clean edit preserving the style or report the limitation. Do not place a new title on top of the old visible title or label the result as "exactly like the reference" without visual evidence.
7. Preserve truthful output/provenance reporting; raster export is not a native layered PSD. Keep existing revision tracking, genuine model receipts, reference/source hashes, approval holds, authenticated access and no-publish policy.
8. For a **service edition** explicitly requesting **one finished picture**, output one independent **3840×2160 / 16:9** design. Do not force the ordinary four-concept flow. For a normal "Sermon Title 16:9" request asking four choices, return four independent reference-faithful variations when a reference is supplied; only use four unrelated predefined looks if no reference exists or the owner expressly wants stylistic exploration.

## Studio UI defaults

- **Reference-first**: enabled automatically when a reference image exists, with the selected reference shown prominently.
- **Reference fidelity**: default `High / Closely follow reference`; lower fidelity is a deliberate user override.
- **Reuse approved artwork**: off by default when the user supplied a new reference. If selected, explicitly label which artwork/version is reused.
- **Speaker photo**: original source preserved by default. "Right", "85%" and "Light text · dark artwork" must be user overrides only, not constraints that freeze the whole composition.
- **Exact details preview**: show all supplied Chinese/English titles/names, service, date/time and venue. Correct data only through the master project/version; no auto rewriting.
- **Fidelity & production notes**: describe which reference was actually used, which speaker source was preserved, any font/flattened-layer limits, and which requested metadata is present or absent.
- Preserve mobile accessibility and downloadable PNG/JPG; do not remove advanced placement controls, but do not make them the only means of controlling reference fidelity.

## Acceptance tests before marking repaired

1. **Reference priority**: Upload reference A, generate service edition, then select reference B for another service. The B result follows B; it must not silently reuse A or any approved design.
2. **Content exactness**: Given Chinese/English titles and bilingual speaker names plus date/time/venue, delivered rendered text matches the input exactly, once per field, with no invented details or missing glyphs. Preserve the text data before and after modifications to art layout.
3. **Speaker identity**: Original image is visually faithful; face pixels/identity are not AI-repainted. The crop, lighting, composition and edges naturally match the target poster's art direction.
4. **Reference fidelity review**: Inspect side by side; palette, motifs, typography feeling, hierarchy, density, texture and lighting closely match the actual selected reference. A generic "professional poster" without those elements fails even if text is correct.
5. **Single service edition**: One finished 3840×2160 PNG/JPG, as requested; independent four-option output only where appropriate.
6. **Reuse opt-in**: `Same approved artwork` activates only after explicit selection. Selecting another reference resets it/off or surfaces a clear conflict.
7. **Version/approval**: Edits create new revisions; no overwriting past deliverables and nothing is approved or published automatically.
8. **End-to-end**: Run one actual owner-provided reference + speaker/photo + service-data job through authenticated HQ → Codex engine → exported artwork → Claude HQ Waiting for your OK. A mock provider, passing unit tests or API availability alone do not prove poster fidelity.

## Boundaries / implementation ownership

- **Claude HQ / this repository:** Creative team skill and reviewer rules now explicitly require reference-first outputs; the backend bridge, task approval and source-integrity semantics should be preserved.
- **Codex image engine / local D: workspace:** Update the real generation prompt builder, composer/layout, metadata-lock handling, reference source selection, "same approved artwork" default, persisted project preferences, UI and tests there. This is the part required for actual on-screen results to change.
- Make the smallest safe code changes. Do not migrate or overwrite previous approved files or restart held/unrelated jobs. Keep the normal owner OK/approval flow.

**Definition of done:** A real exported service poster visibly follows the specific owner-selected reference and seamlessly integrates the original speaker and every supplied exact bilingual detail. Do not close the issue based on instruction/documentation edits alone.
