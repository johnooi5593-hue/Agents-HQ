# Sermon Design Studio in Creative

Open **Creative → Overview → Sermon Title 16:9** or **XHS Sermon Recap Pro**.
The exact first line `Sermon Title 16:9` also opens the editor from the typed or
microphone command box. Follow it with `Chinese:` and `English:` lines. Ordinary
requests continue through the existing lead workflow.

The editor uses this Agent HQ's existing login and phone connection. Its fixed
local image engine is `D:\AI OFFICE\studio\sermon-design-server.mjs` on loopback
port **4341**. It saves editable projects under
`D:\AI OFFICE\.studio\sermon-design-runtime`; it does not open the older office's
task store. The first design API request can start this exact installed engine
when its port is closed. A different or outdated service on that port is left
untouched and reported. Node.js must be installed on the office computer.

Optional GPT Image access is configured on the server with
`D:\AI OFFICE\.studio\sermon-design\provider-config.json` (ignored private
configuration), or the documented server environment variable. Details are in
`D:\AI OFFICE\docs\SERMON-DESIGN-STUDIO.md`. Keys are never entered into the
browser. When no provider is configured, the UI shows that limitation and uses
the available deterministic composition tools. A rendered local background is
not described as AI-generated imagery.

After a successful export, each file's size and SHA-256 are checked. The delivery
is copied into this office's own `out/sermon-studio-<project>-r<revision>-a<attempt>`
folder, and a **Creative → Waiting for your OK** task is added exactly once for
that export version. This is a native renderer operation, not a Claude model
run. Open the review task to inspect the independent artwork and download its
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
