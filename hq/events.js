#!/usr/bin/env node
// Claude Code hook: appends one line to hq/events.jsonl when a sub-agent starts or stops, so the office can light
// the right character up. Registered in .claude/settings.json (SubagentStart / SubagentStop). Never fails the hook.
const fs = require("fs");
const path = require("path");
const FILE = path.join(__dirname, "events.jsonl");
const MAX_LINES = 2000;

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let input = {};
  try { input = JSON.parse(raw || "{}"); } catch (e) { input = {}; }
  const event = { ts: Date.now(), event: process.argv[2] === "stop" ? "stop" : "start", agent: input.agent_type || "unknown", id: input.agent_id || "", session: input.session_id || "" };
  try {
    fs.appendFileSync(FILE, JSON.stringify(event) + "\n");
    const lines = fs.readFileSync(FILE, "utf8").split("\n").filter(Boolean);
    if (lines.length > MAX_LINES) fs.writeFileSync(FILE, lines.slice(-MAX_LINES / 2).join("\n") + "\n");
  } catch (e) { /* the office feed is best effort */ }
  process.exit(0);
});
