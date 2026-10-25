#!/usr/bin/env node
// Starts the shared brain (the memory MCP server) on brain/memory.jsonl in this repository,
// whatever folder Claude Code was started from, on macOS, Linux and Windows. Used by .mcp.json.
const path = require("path");
const { spawn } = require("child_process");

const root = path.resolve(__dirname, "..");
const env = { ...process.env, MEMORY_FILE_PATH: path.join(root, "brain", "memory.jsonl") };
const win = process.platform === "win32";
const child = spawn(win ? "npx.cmd" : "npx", ["-y", "@modelcontextprotocol/server-memory"], { stdio: "inherit", env, cwd: root, shell: win });
child.on("exit", (code) => process.exit(code === null ? 1 : code));
child.on("error", (err) => { console.error("could not start the memory server:", err.message); process.exit(1); });
