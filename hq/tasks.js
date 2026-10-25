#!/usr/bin/env node
// The board: hq/tasks.json, shared by the chief of staff (this script) and the office (the app reads and writes the same file).
// usage: node hq/tasks.js list [--json]
//        node hq/tasks.js add "<title>" [--team <Team>] [--agent <name>] [--note "<text>"] [--status todo|doing|review|done]
//                                       [--kind task|approval|post|meeting] [--date YYYY-MM-DD] [--time HH:MM] [--subtitle "<text>"]
//        node hq/tasks.js move <id> todo|doing|review|done          (done stamps done_at, anything else clears it)
//        node hq/tasks.js progress <id> <0..100> ["<subtitle>"]     (what the task is doing right now)
//        node hq/tasks.js note <id> "<text>"                        (note "out:<name>" ties the task to out/<name>: Approve in the app moves it)
//        node hq/tasks.js remove <id>
// Task = { id, title, team, agent, status, kind, note, subtitle, progress, date, time, created, updated, done_at }
const fs = require("fs");
const path = require("path");
const FILE = path.join(__dirname, "tasks.json");
const STATUSES = ["todo", "doing", "review", "done"];
const KINDS = ["task", "approval", "post", "meeting"];
const DEFAULTS = { team: "", agent: "", note: "", kind: "task", subtitle: "", progress: null, date: null, time: null, done_at: null };

function normalize(t) {
  for (const [k, v] of Object.entries(DEFAULTS)) if (t[k] === undefined) t[k] = v;
  if (!STATUSES.includes(t.status)) t.status = "todo";
  if (!KINDS.includes(t.kind)) t.kind = "task";
  return t;
}
function load() { let db; try { db = JSON.parse(fs.readFileSync(FILE, "utf8")); } catch (e) { db = { tasks: [] }; } db.tasks = (db.tasks || []).map(normalize); return db; }
function save(db) { fs.writeFileSync(FILE, JSON.stringify(db, null, 2) + "\n"); }
function opts(args) {
  const o = { _: [] };
  for (let i = 0; i < args.length; i++) {
    if (!args[i].startsWith("--")) { o._.push(args[i]); continue; }
    const next = args[i + 1];
    if (next === undefined || next.startsWith("--")) o[args[i].slice(2)] = true; else { o[args[i].slice(2)] = next; i++; }
  }
  return o;
}
function out(obj) { console.log(JSON.stringify(obj)); }
const now = () => new Date().toISOString();
const cleanDate = (s) => (typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(Date.parse(s)) ? s : null);
const cleanTime = (s) => (typeof s === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(s) ? s : null);
const cleanProgress = (p) => { if (p === undefined || p === null || p === "" || p === true) return null; const n = parseInt(p, 10); return isNaN(n) ? null : Math.max(0, Math.min(100, n)); };
function setStatus(t, st) {
  t.status = st; t.updated = now();
  if (st === "done") { t.done_at = t.done_at || now(); if (t.progress !== null) t.progress = 100; } else t.done_at = null;
}

const [cmd, ...rest] = process.argv.slice(2);
const db = load();
const o = opts(rest);
const find = (id) => db.tasks.find((t) => t.id === id);

if (cmd === "add") {
  const title = o._[0]; if (!title) { console.error("add needs a title"); process.exit(1); }
  const id = "t" + (Math.max(0, ...db.tasks.map((t) => parseInt(String(t.id).slice(1), 10) || 0)) + 1);
  const status = STATUSES.includes(o.status) ? o.status : "todo";
  const task = normalize({ id, title, team: o.team === true ? "" : o.team || "", agent: o.agent === true ? "" : o.agent || "", status,
    kind: KINDS.includes(o.kind) ? o.kind : "task", note: o.note === true ? "" : o.note || "", subtitle: o.subtitle === true ? "" : o.subtitle || "",
    progress: cleanProgress(o.progress), date: cleanDate(o.date), time: cleanTime(o.time), created: now(), updated: now(), done_at: status === "done" ? now() : null });
  db.tasks.push(task); save(db); out({ added: task });
} else if (cmd === "move") {
  const t = find(o._[0]); const st = o._[1];
  if (!t || !STATUSES.includes(st)) { console.error("move <id> todo|doing|review|done"); process.exit(1); }
  setStatus(t, st); save(db); out({ moved: t });
} else if (cmd === "progress") {
  const t = find(o._[0]); const p = cleanProgress(o._[1]);
  if (!t || p === null) { console.error("progress <id> <0..100> [\"<subtitle>\"]"); process.exit(1); }
  t.progress = p; if (o._.length > 2) t.subtitle = o._.slice(2).join(" "); t.updated = now(); save(db); out({ progress: t });
} else if (cmd === "note") {
  const t = find(o._[0]); if (!t) { console.error("no such task"); process.exit(1); }
  t.note = o._.slice(1).join(" "); t.updated = now(); save(db); out({ noted: t });
} else if (cmd === "remove") {
  const n = db.tasks.length; db.tasks = db.tasks.filter((t) => t.id !== o._[0]); save(db); out({ removed: n - db.tasks.length });
} else {
  if ("json" in o || cmd === "json") out(db);
  else for (const st of STATUSES) {
    const rows = db.tasks.filter((t) => t.status === st); console.log(`${st.toUpperCase()} (${rows.length})`);
    for (const t of rows) console.log(`  ${t.id}  ${t.title}${t.team ? "  [" + t.team + "]" : ""}${t.agent ? "  @" + t.agent : ""}${t.kind !== "task" ? "  <" + t.kind + ">" : ""}${t.date ? "  " + t.date + (t.time ? " " + t.time : "") : ""}${t.progress !== null ? "  " + t.progress + "%" : ""}${t.subtitle ? "  · " + t.subtitle : ""}${t.note ? "  - " + t.note : ""}`);
  }
}
