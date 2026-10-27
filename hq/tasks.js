#!/usr/bin/env node
// The board: hq/tasks.json, shared by the chief of staff (this script) and the office (the app reads and writes the same file).
// usage: node hq/tasks.js list [--json]
//        node hq/tasks.js add "<title>" [--team <Team>] [--agent <name>] [--note "<text>"] [--status todo|doing|review|done]
//                                       [--kind task|approval|post|meeting] [--date YYYY-MM-DD] [--time HH:MM] [--subtitle "<text>"]
//                                       [--channel <key>|main|@office]   (a channel's key from .hq-channels.json, main, or the whole office)
//        node hq/tasks.js move <id> todo|doing|review|done|cancelled (done stamps done_at, anything else clears it)
//        node hq/tasks.js channel <id> <key>|main|@office|auto     (file the task under a channel; auto: from its note/folder)
//        node hq/tasks.js progress <id> <0..100> ["<subtitle>"]     (what the task is doing right now)
//        node hq/tasks.js note <id> "<text>"                        (note "out:<name>" ties the task to out/<name>: Approve in the app moves it)
//        node hq/tasks.js remove <id>                               (moves it to the Deleted tab in the app; Restore brings it back)
// Task = { id, title, team, agent, status, kind, note, subtitle, progress, date, time, created, updated, done_at, channel }
const fs = require("fs");
const path = require("path");
const FILE = path.join(__dirname, "tasks.json");
const STATUSES = ["todo", "doing", "review", "done", "cancelled"];
const KINDS = ["task", "approval", "post", "meeting"];
const DEFAULTS = { team: "", agent: "", note: "", kind: "task", subtitle: "", progress: null, date: null, time: null, done_at: null, channel: null };
const cleanChannel = (c) => (c === "main" ? "" : c === "@office" || (typeof c === "string" && /^[a-z0-9-]+$/.test(c)) ? c : null);   // "main": the main channel; the app checks it is real

function normalize(t) {
  for (const [k, v] of Object.entries(DEFAULTS)) if (t[k] === undefined) t[k] = v;
  if (!STATUSES.includes(t.status)) t.status = "todo";
  if (!KINDS.includes(t.kind)) t.kind = "task";
  return t;
}
function load() { let db; try { db = JSON.parse(fs.readFileSync(FILE, "utf8")); } catch (e) { db = { tasks: [] }; } db.tasks = (db.tasks || []).map(normalize); return db; }
const nap = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
// Several lead jobs can change the board at the same moment, and so can the app: hq/tasks.lock lets one in at a time
// (the app's server takes the same lock), and the board is written whole and swapped in, so nobody reads half a file.
const LOCK = path.join(__dirname, "tasks.lock");
function lock() {
  for (const end = Date.now() + 10000; Date.now() < end; nap(20)) {
    try { fs.closeSync(fs.openSync(LOCK, "wx")); return true; } catch (e) {
      if (e.code !== "EEXIST") return false;
      try { if (Date.now() - fs.statSync(LOCK).mtimeMs > 15000) fs.unlinkSync(LOCK); } catch (e2) { /* someone else took it */ }
    }
  }
  return false;
}
function unlock(held) { if (held) try { fs.unlinkSync(LOCK); } catch (e) { /* already gone */ } }
function save(db) {
  const tmp = `${FILE}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(db, null, 2) + "\n");
  for (let i = 0; ; i++) { try { fs.renameSync(tmp, FILE); return; } catch (e) { if (i >= 20 || !["EPERM", "EBUSY", "EACCES"].includes(e.code)) throw e; nap(50); } }
}
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
const held = ["add", "move", "progress", "note", "channel", "remove"].includes(cmd) && lock();   // reading needs no lock
process.on("exit", () => unlock(held));
const db = load();
const o = opts(rest);
const find = (id) => db.tasks.find((t) => t.id === id);

if (cmd === "add") {
  const title = o._[0]; if (!title) { console.error("add needs a title"); process.exit(1); }
  const id = "t" + (Math.max(0, ...db.tasks.concat(db.deleted || []).map((t) => parseInt(String(t.id).slice(1), 10) || 0)) + 1);   // deleted tasks keep their ids for Restore
  const status = STATUSES.includes(o.status) ? o.status : "todo";
  const task = normalize({ id, title, team: o.team === true ? "" : o.team || "", agent: o.agent === true ? "" : o.agent || "", status,
    kind: KINDS.includes(o.kind) ? o.kind : "task", note: o.note === true ? "" : o.note || "", subtitle: o.subtitle === true ? "" : o.subtitle || "",
    progress: cleanProgress(o.progress), date: cleanDate(o.date), time: cleanTime(o.time), created: now(), updated: now(), done_at: status === "done" ? now() : null, channel: cleanChannel(o.channel) });
  db.tasks.push(task); save(db); out({ added: task });
} else if (cmd === "move") {
  const t = find(o._[0]); const st = o._[1];
  if (!t || !STATUSES.includes(st)) { console.error("move <id> todo|doing|review|done|cancelled"); process.exit(1); }
  setStatus(t, st); save(db); out({ moved: t });
} else if (cmd === "progress") {
  const t = find(o._[0]); const p = cleanProgress(o._[1]);
  if (!t || p === null) { console.error("progress <id> <0..100> [\"<subtitle>\"]"); process.exit(1); }
  t.progress = p; if (o._.length > 2) t.subtitle = o._.slice(2).join(" "); t.updated = now(); save(db); out({ progress: t });
} else if (cmd === "note") {
  const t = find(o._[0]); if (!t) { console.error("no such task"); process.exit(1); }
  t.note = o._.slice(1).join(" "); t.updated = now(); save(db); out({ noted: t });
} else if (cmd === "channel") {
  const t = find(o._[0]); const c = o._[1] === "auto" ? null : cleanChannel(o._[1]);
  if (!t || (o._[1] !== "auto" && c === null)) { console.error("channel <id> <key>|main|@office|auto"); process.exit(1); }
  t.channel = c; t.updated = now(); save(db); out({ channel: t });
} else if (cmd === "remove") {                             // into the app's Deleted tab, where the owner can Restore it
  const t = find(o._[0]); if (!t) { console.error("no such task"); process.exit(1); }
  db.tasks = db.tasks.filter((x) => x !== t); (db.deleted = db.deleted || []).push({ ...t, deleted_at: now() }); save(db); out({ removed: 1 });
} else {
  if ("json" in o || cmd === "json") out(db);
  else for (const st of STATUSES) {
    const rows = db.tasks.filter((t) => t.status === st); console.log(`${st.toUpperCase()} (${rows.length})`);
    for (const t of rows) console.log(`  ${t.id}  ${t.title}${t.team ? "  [" + t.team + "]" : ""}${t.agent ? "  @" + t.agent : ""}${t.kind !== "task" ? "  <" + t.kind + ">" : ""}${t.date ? "  " + t.date + (t.time ? " " + t.time : "") : ""}${t.progress !== null ? "  " + t.progress + "%" : ""}${t.subtitle ? "  · " + t.subtitle : ""}${t.note ? "  - " + t.note : ""}`);
  }
}
