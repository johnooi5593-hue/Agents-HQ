#!/usr/bin/env node
// The board: hq/tasks.json, shared by the chief of staff (this script) and the office (the app reads and writes the same file).
// usage: node hq/tasks.js list [--json]
//        node hq/tasks.js add "<title>" [--team <Team>] [--agent <name>] [--note "<text>"] [--status todo|doing|review|done]
//        node hq/tasks.js move <id> todo|doing|review|done
//        node hq/tasks.js note <id> "<text>"
//        node hq/tasks.js remove <id>
const fs = require("fs");
const path = require("path");
const FILE = path.join(__dirname, "tasks.json");
const STATUSES = ["todo", "doing", "review", "done"];

function load() { try { return JSON.parse(fs.readFileSync(FILE, "utf8")); } catch (e) { return { tasks: [] }; } }
function save(db) { fs.writeFileSync(FILE, JSON.stringify(db, null, 2) + "\n"); }
function opts(args) { const o = { _: [] }; for (let i = 0; i < args.length; i++) { if (args[i].startsWith("--")) { o[args[i].slice(2)] = args[i + 1]; i++; } else o._.push(args[i]); } return o; }
function out(obj) { console.log(JSON.stringify(obj)); }

const [cmd, ...rest] = process.argv.slice(2);
const db = load();
const o = opts(rest);
const now = () => new Date().toISOString();
const find = (id) => db.tasks.find((t) => t.id === id);

if (cmd === "add") {
  const title = o._[0]; if (!title) { console.error("add needs a title"); process.exit(1); }
  const id = "t" + (Math.max(0, ...db.tasks.map((t) => parseInt(t.id.slice(1), 10) || 0)) + 1);
  const task = { id, title, team: o.team || "", agent: o.agent || "", status: STATUSES.includes(o.status) ? o.status : "todo", note: o.note || "", created: now(), updated: now() };
  db.tasks.push(task); save(db); out({ added: task });
} else if (cmd === "move") {
  const t = find(o._[0]); const st = o._[1];
  if (!t || !STATUSES.includes(st)) { console.error("move <id> todo|doing|review|done"); process.exit(1); }
  t.status = st; t.updated = now(); save(db); out({ moved: t });
} else if (cmd === "note") {
  const t = find(o._[0]); if (!t) { console.error("no such task"); process.exit(1); }
  t.note = o._.slice(1).join(" "); t.updated = now(); save(db); out({ noted: t });
} else if (cmd === "remove") {
  const n = db.tasks.length; db.tasks = db.tasks.filter((t) => t.id !== o._[0]); save(db); out({ removed: n - db.tasks.length });
} else {
  if (o.json !== undefined || cmd === "json") out(db);
  else for (const st of STATUSES) { const rows = db.tasks.filter((t) => t.status === st); console.log(`${st.toUpperCase()} (${rows.length})`); for (const t of rows) console.log(`  ${t.id}  ${t.title}${t.team ? "  [" + t.team + "]" : ""}${t.agent ? "  @" + t.agent : ""}${t.note ? "  - " + t.note : ""}`); }
}
