# Sermon Design Studio in Creative

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
