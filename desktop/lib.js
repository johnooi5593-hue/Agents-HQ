"use strict";
/* lib.js: the pure helpers of the Agents HQ desktop app.
 *
 * Nothing from electron is required here, so main.js can use it and `node test-lib.js` can test it on any OS:
 *   - run(): a command with a timeout (on Windows through cmd.exe, so .cmd shims like npm and claude resolve)
 *   - the prerequisite checks (git, node, python, ffmpeg, claude) with install hints
 *   - settings load/save, port probing, an HTTP poll, a log ring buffer
 *   - the PowerShell lines that install what is missing, where the real claude executable is, the office folder,
 *     and whether Claude Code is signed in
 */
const fs = require("fs");
const net = require("net");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const IS_WIN = process.platform === "win32";
const DEFAULT_PORT = 7331;
const LAST_PORT = 7340;
const REPO_URL = "https://github.com/johnooi5593-hue/Agents-HQ";
const CHECK_TIMEOUT_MS = 10000;
const MAX_OUTPUT = 64 * 1024;

// The five tools the office needs. `required` ones must be there before the engine starts; the others
// only stop part of the work (git: updates and the first download, ffmpeg: video editing).
const TOOLS = [
  { name: "git", label: "Git", hint: "winget install -e --id Git.Git", why: "downloads the office and keeps it up to date", required: false },
  { name: "node", label: "Node.js 18+", hint: "winget install -e --id OpenJS.NodeJS.LTS", why: "runs the shared brain and Claude Code", required: true },
  { name: "python", label: "Python 3.10+", hint: "winget install -e --id Python.Python.3.12", why: "runs the engine and the video tools", required: true },
  { name: "ffmpeg", label: "ffmpeg", hint: "winget install -e --id Gyan.FFmpeg", why: "cuts and captions the clips", required: false },
  // the native installer gives a real claude.exe (in %USERPROFILE%\.local\bin) that the engine can start without cmd.exe;
  // the npm package only gives a claude.cmd shim, which mangles quotes and line breaks in the owner's messages
  { name: "claude", label: "Claude Code", hint: "irm https://claude.ai/install.ps1 | iex", why: "the chief of staff itself", required: true },
];
const PYTHON_CANDIDATES = [["py", "-3"], ["python"], ["python3"]];
const PYTHON_MIN_MINOR = 10;
const NODE_MIN_MAJOR = 18;

// ---------------------------------------------------------------- running commands

/** Quote one argument for a cmd.exe command line. */
function quoteArg(a) {
  a = String(a);
  if (a === "") return '""';
  return /[\s"&|<>^()]/.test(a) ? '"' + a.replace(/"/g, '\\"') + '"' : a;
}

/** `cmd arg1 "arg with space"`: the command line cmd.exe gets. */
function cmdline(cmd, args = []) {
  return [cmd, ...args].map(quoteArg).join(" ");
}

/** Kill a process and, on Windows, everything it started. */
function killTree(pid) {
  if (!pid) return;
  try {
    if (IS_WIN) spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" }).on("error", () => {});
    else process.kill(pid, "SIGKILL");
  } catch (_) { /* already gone */ }
}

/**
 * Run a command line and collect its output. Never throws: a missing tool gives { code: null, error }.
 * On Windows the line goes through `cmd.exe /d /s /c "<line>"`, which resolves .cmd shims (npm, claude)
 * that CreateProcess alone does not find. Elsewhere it is split the simple way (no shell quoting needed).
 */
function runLine(line, opts = {}) {
  const timeoutMs = opts.timeoutMs || CHECK_TIMEOUT_MS;
  return new Promise((resolve) => {
    const out = { line, code: null, stdout: "", stderr: "", error: null, timedOut: false };
    let child, done = false;
    const finish = () => { if (done) return; done = true; clearTimeout(timer); resolve(out); };
    const base = { cwd: opts.cwd, env: opts.env || process.env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] };
    try {
      if (IS_WIN) child = spawn("cmd.exe", ["/d", "/s", "/c", '"' + line + '"'], { ...base, windowsVerbatimArguments: true });
      else child = spawn("/bin/sh", ["-c", line], base);
    } catch (e) {
      out.error = e.message;
      return resolve(out);
    }
    const timer = setTimeout(() => { out.timedOut = true; out.error = "timed out after " + timeoutMs / 1000 + " s"; killTree(child.pid); finish(); }, timeoutMs);
    child.stdout.on("data", (d) => { if (out.stdout.length < MAX_OUTPUT) out.stdout += d; });
    child.stderr.on("data", (d) => { if (out.stderr.length < MAX_OUTPUT) out.stderr += d; });
    child.on("error", (e) => { out.error = e.message; setImmediate(finish); });
    child.on("close", (code) => { out.code = code; finish(); });
  });
}

/** run("git", ["--version"]) -> { code, stdout, stderr, error }. See runLine. */
function run(cmd, args = [], opts = {}) {
  return runLine(cmdline(cmd, args), opts);
}

// ---------------------------------------------------------------- prerequisite checks

/** First "x.y[.z]" in a text, as { text, major, minor, patch }. */
function parseVersion(text) {
  const m = /(\d+)\.(\d+)(?:\.(\d+))?/.exec(text || "");
  return m ? { text: m[0], major: +m[1], minor: +m[2], patch: m[3] ? +m[3] : 0 } : null;
}

function firstLine(s) {
  return String(s || "").replace(/\r/g, "").split("\n").map((l) => l.trim()).find(Boolean) || "";
}

/** The label of a python command, e.g. "py -3". */
function pythonLabel(cmd) {
  return Array.isArray(cmd) ? cmd.join(" ") : String(cmd || "python");
}

/** The problem in one plain sentence, for a tool that did not answer. */
function failureDetail(res, label) {
  if (res.timedOut) return label + " did not answer within 10 seconds.";
  if (res.error && /ENOENT|not found|not recognized/i.test(res.error)) return label + " is not installed, or not on the PATH yet.";
  if (res.error) return label + " could not be started: " + res.error;
  const text = firstLine(res.stderr) || firstLine(res.stdout);
  if (res.code !== 0 && !text) return label + " is not installed, or not on the PATH yet.";
  return label + " answered: " + (text || "exit code " + res.code);
}

async function checkGit(runner) {
  const res = await runner("git", ["--version"]);
  const v = parseVersion(res.stdout);
  const ok = res.code === 0 && /git version/i.test(res.stdout) && !!v;
  return { ok, version: ok ? v.text : "", detail: ok ? "" : failureDetail(res, "Git") };
}

async function checkNode(runner) {
  const res = await runner("node", ["--version"]);
  const v = parseVersion(res.stdout);
  if (res.code === 0 && v && v.major >= NODE_MIN_MAJOR) return { ok: true, version: v.text, detail: "" };
  if (res.code === 0 && v) return { ok: false, version: v.text, detail: "Node.js " + v.text + " is too old; " + NODE_MIN_MAJOR + " or newer is needed." };
  return { ok: false, version: "", detail: failureDetail(res, "Node.js") };
}

/**
 * Try "py -3", "python", "python3" and keep the first that prints "Python 3.x" with x >= 10.
 * The Windows Store alias named python.exe prints nothing and exits non-zero: no match, so it is skipped.
 */
async function checkPython(runner, candidates = PYTHON_CANDIDATES) {
  const tried = [];
  for (const cmd of candidates) {
    const res = await runner(cmd[0], [...cmd.slice(1), "--version"]);
    const text = (String(res.stdout) + "\n" + String(res.stderr)).trim();
    const m = /Python 3\.(\d+)(?:\.(\d+))?/.exec(text);
    if (m && +m[1] >= PYTHON_MIN_MINOR) return { ok: true, version: m[0], cmd, detail: "" };
    if (m) tried.push(pythonLabel(cmd) + " is " + m[0]);
    else if (text && res.code === 0) tried.push(pythonLabel(cmd) + " answered " + firstLine(text));
  }
  const detail = tried.length
    ? "Found " + tried.join(", ") + ", but Python 3." + PYTHON_MIN_MINOR + " or newer is needed."
    : "Python 3 is not installed, or not on the PATH yet.";
  return { ok: false, version: "", cmd: null, detail };
}

async function checkFfmpeg(runner) {
  const res = await runner("ffmpeg", ["-version"]);
  const line = firstLine(res.stdout);
  const m = /ffmpeg version (\S+)/i.exec(line);
  const ok = res.code === 0 && !!m;
  return { ok, version: ok ? m[1] : "", detail: ok ? "" : failureDetail(res, "ffmpeg") };
}

async function checkClaude(runner) {
  const res = await runner("claude", ["--version"]);
  const line = firstLine(res.stdout) || firstLine(res.stderr);
  const v = parseVersion(line);
  const ok = res.code === 0 && !!v;
  return { ok, version: ok ? line : "", detail: ok ? "" : failureDetail(res, "Claude Code") };
}

const CHECKERS = { git: checkGit, node: checkNode, python: checkPython, ffmpeg: checkFfmpeg, claude: checkClaude };

/**
 * Check every tool. Returns { tools: [{ name, label, ok, version, hint, why, required, detail }], python: ["py","-3"] | null,
 * allOk, requiredOk }. `opts.run` replaces the runner (tests), `opts.pythonCandidates` the python commands to try.
 */
async function checkAll(opts = {}) {
  const runner = opts.run || run;
  const results = await Promise.all(TOOLS.map(async (t) => {
    let r;
    try {
      r = t.name === "python" ? await checkPython(runner, opts.pythonCandidates) : await CHECKERS[t.name](runner);
    } catch (e) {
      r = { ok: false, version: "", detail: t.label + " check failed: " + e.message };
    }
    return { ...t, ok: !!r.ok, version: r.version || "", detail: r.detail || "", cmd: r.cmd || null };
  }));
  const py = results.find((t) => t.name === "python");
  const tools = results.map(({ cmd, ...t }) => t);
  return {
    tools,
    python: py && py.ok ? py.cmd : null,
    allOk: tools.every((t) => t.ok),
    requiredOk: tools.filter((t) => t.required).every((t) => t.ok),
  };
}

// ---------------------------------------------------------------- Windows PATH and the claude executable

/** Expand %VAR% in a registry PATH value. */
function expandWin(s, env) {
  return String(s).replace(/%([^%]+)%/g, (m, k) => (env[k] != null ? env[k] : env[k.toUpperCase()] != null ? env[k.toUpperCase()] : m));
}

/**
 * Windows only: read the current PATH from the registry (machine + user), so tools installed while the app is
 * open (winget, npm -g) are found without restarting it. Returns the merged PATH and sets it on `env`.
 */
async function refreshPath(env = process.env, runner = runLine) {
  if (!IS_WIN) return null;
  const keys = ['"HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"', "HKCU\\Environment"];
  const parts = [];
  for (const key of keys) {
    const res = await runner("reg query " + key + " /v Path", { timeoutMs: 5000 });
    const m = /\bPath\s+REG_(?:EXPAND_)?SZ\s+(.*)/i.exec(res.stdout || "");
    if (m) parts.push(expandWin(m[1].trim(), env));
  }
  const home = env.USERPROFILE || "";
  const known = [env.APPDATA && path.join(env.APPDATA, "npm"), home && path.join(home, ".local", "bin")].filter(Boolean);
  const seen = new Set();
  const merged = [];
  for (const p of [...(env.Path || env.PATH || "").split(";"), ...parts.join(";").split(";"), ...known]) {
    const q = p.trim();
    const k = q.toLowerCase();
    if (q && !seen.has(k)) { seen.add(k); merged.push(q); }
  }
  env.Path = merged.join(";");
  env.PATH = env.Path;
  return env.Path;
}

/**
 * Where the claude executable is: { bin, kind } with kind "exe" (a real executable), "cmd" (the npm shim) or null.
 * The engine (hq/server.py) starts claude itself; on Windows it needs an .exe, or a .cmd whose path has no spaces.
 */
async function resolveClaude(env = process.env, runner = runLine) {
  if (!IS_WIN) {
    const res = await runner("command -v claude", { env });
    const bin = firstLine(res.stdout);
    return bin ? { bin, kind: "exe" } : { bin: null, kind: null };
  }
  const res = await runner("where claude", { env, timeoutMs: 5000 });
  const found = String(res.stdout || "").replace(/\r/g, "").split("\n").map((l) => l.trim()).filter(Boolean);
  const exe = found.find((p) => /\.exe$/i.test(p));
  if (exe) return { bin: exe, kind: "exe" };
  const native = path.join(env.USERPROFILE || "", ".local", "bin", "claude.exe");
  if (env.USERPROFILE && fs.existsSync(native)) return { bin: native, kind: "exe" };
  const shim = found.find((p) => /\.(cmd|bat)$/i.test(p));
  return shim ? { bin: shim, kind: "cmd" } : { bin: null, kind: null };
}

/** Windows only: the 8.3 short form of a path (no spaces), or null when Windows has none for it. */
async function shortPath(p, runner = runLine) {
  if (!IS_WIN) return null;
  const res = await runner('for %I in ("' + p + '") do @echo %~sI', { timeoutMs: 5000 });
  const s = firstLine(res.stdout);
  return s && fs.existsSync(s) ? s : null;
}

/**
 * True when Claude Code looks signed in on this machine: an API key or OAuth token in the environment, the credentials
 * file (Windows and Linux keep it in ~/.claude/.credentials.json; macOS uses the keychain) or an account in ~/.claude.json.
 * A guess, not a login check: when it is wrong, the office page shows claude's own answer.
 */
function claudeSignedIn(home, env = process.env) {
  if (env.ANTHROPIC_API_KEY || env.CLAUDE_CODE_OAUTH_TOKEN) return true;
  const cfgDir = env.CLAUDE_CONFIG_DIR || path.join(home || "", ".claude");
  if (fs.existsSync(path.join(cfgDir, ".credentials.json"))) return true;
  for (const file of [path.join(home || "", ".claude.json"), path.join(cfgDir, ".claude.json")]) {
    try {
      const cfg = JSON.parse(fs.readFileSync(file, "utf8"));
      if (cfg && typeof cfg === "object" && (cfg.oauthAccount || cfg.primaryApiKey)) return true;
    } catch (_) { /* missing or broken: not a sign-in */ }
  }
  return false;
}

// ---------------------------------------------------------------- the office folder

/**
 * The folder the office goes in: Documents, unless OneDrive syncs it (then the home folder). A git repository,
 * the brain file the memory server rewrites and multi-GB raw clips do not belong in a synced folder.
 */
function officeBase(documents, home) {
  return documents && !/[\\/]OneDrive/i.test(documents) ? documents : home;
}

// ---------------------------------------------------------------- the install script

/**
 * The PowerShell lines that install every missing tool: the winget commands, then the native Claude Code installer
 * (a real claude.exe in %USERPROFILE%\.local\bin), with a PATH refresh and the npm package as the fallback.
 * main.js writes them to a .ps1 and runs it in a visible window so the user can watch and approve the UAC prompts.
 */
function installLines(tools) {
  const missing = tools.filter((t) => !t.ok);
  const lines = ["Write-Host 'Agents HQ: installing the missing tools. Approve the Windows prompts when they appear.' -ForegroundColor Yellow"];
  for (const t of missing) {
    if (t.name === "claude") continue;
    lines.push(t.hint.startsWith("winget ") ? t.hint + " --accept-package-agreements --accept-source-agreements" : t.hint);
  }
  const claude = missing.find((t) => t.name === "claude");
  if (claude) {
    lines.push(claude.hint);
    lines.push("$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')");
    lines.push('if (-not (Test-Path "$env:USERPROFILE\\.local\\bin\\claude.exe")) { npm install -g @anthropic-ai/claude-code }');
  }
  lines.push("Write-Host 'Done. Go back to Agents HQ and press Check again.' -ForegroundColor Green");
  return lines;
}

/** The same as one PowerShell command line (the lines joined with "; "). */
function installScript(tools) {
  return installLines(tools).join("; ");
}

// ---------------------------------------------------------------- settings

/** settings.json merged over the defaults; the defaults alone when the file is missing or broken. */
function loadSettings(file, defaults = {}) {
  try {
    const obj = JSON.parse(fs.readFileSync(file, "utf8"));
    return obj && typeof obj === "object" && !Array.isArray(obj) ? { ...defaults, ...obj } : { ...defaults };
  } catch (_) {
    return { ...defaults };
  }
}

/** Write settings.json atomically (temp file, then rename). Returns what was saved. */
function saveSettings(file, settings) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(settings, null, 2) + "\n");
  fs.renameSync(tmp, file);
  return settings;
}

// ---------------------------------------------------------------- ports and HTTP

/** True when nothing listens on host:port. */
function isPortFree(port, host = "127.0.0.1") {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.once("error", () => resolve(false));
    srv.listen({ port, host, exclusive: true }, () => srv.close(() => resolve(true)));
  });
}

/** The preferred port when free, else the first free one of 7331..7340, else null. */
async function findPort(preferred = DEFAULT_PORT, host = "127.0.0.1") {
  const ports = [preferred];
  for (let p = DEFAULT_PORT; p <= LAST_PORT; p++) if (!ports.includes(p)) ports.push(p);
  for (const p of ports) if (await isPortFree(p, host)) return p;
  return null;
}

/** GET a URL: { status, body }. Rejects on a network error or after timeoutMs. */
function httpGet(url, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (d) => { if (body.length < MAX_OUTPUT) body += d; });
      res.on("end", () => resolve({ status: res.statusCode, body }));
    });
    req.on("timeout", () => req.destroy(new Error("timed out")));
    req.on("error", reject);
  });
}

/** True when an Agents HQ engine answers on the port (its /api/status is JSON with the office counts). */
async function isAgentsHq(port, host = "127.0.0.1") {
  try {
    const res = await httpGet(`http://${host}:${port}/api/status`, 2000);
    if (res.status !== 200) return false;
    const obj = JSON.parse(res.body);
    return !!(obj && typeof obj === "object" && obj.counts && obj.desk);
  } catch (_) {
    return false;
  }
}

/** Poll a URL until it answers 200 (true), or until timeoutMs passes or shouldStop() says so (false). */
async function waitForHttp(url, opts = {}) {
  const timeoutMs = opts.timeoutMs || 60000;
  const intervalMs = opts.intervalMs || 500;
  const stop = opts.shouldStop || (() => false);
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (stop()) return false;
    try {
      const res = await httpGet(url, Math.min(3000, intervalMs * 4));
      if (res.status === 200) return true;
    } catch (_) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

// ---------------------------------------------------------------- the log ring buffer

/** The last `max` log lines, with listeners for new ones. push() splits chunks into lines. */
class RingLog {
  constructor(max = 400) {
    this.max = max;
    this.items = [];
    this.listeners = [];
    this.partial = "";
  }

  push(chunk) {
    const text = this.partial + String(chunk).replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    this.partial = text.endsWith("\n") ? "" : lines.pop();
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (!line) continue;
      this.items.push(line);
      if (this.items.length > this.max) this.items.splice(0, this.items.length - this.max);
      for (const fn of this.listeners) { try { fn(line); } catch (_) { /* a listener must not break the log */ } }
    }
  }

  flush() {
    if (this.partial) { const p = this.partial; this.partial = ""; this.push(p + "\n"); }
  }

  lines() { return this.items.slice(); }
  tail(n = 50) { return this.items.slice(-n); }
  onLine(fn) { this.listeners.push(fn); return () => { this.listeners = this.listeners.filter((f) => f !== fn); }; }
}

module.exports = {
  IS_WIN, DEFAULT_PORT, LAST_PORT, REPO_URL, TOOLS, PYTHON_CANDIDATES,
  quoteArg, cmdline, run, runLine, killTree,
  parseVersion, firstLine, pythonLabel, checkGit, checkNode, checkPython, checkFfmpeg, checkClaude, checkAll,
  refreshPath, resolveClaude, shortPath, claudeSignedIn, officeBase, installLines, installScript,
  loadSettings, saveSettings,
  isPortFree, findPort, httpGet, isAgentsHq, waitForHttp,
  RingLog,
};
