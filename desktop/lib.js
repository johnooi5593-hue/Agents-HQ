"use strict";
/* lib.js: the pure helpers of the Agents HQ desktop app.
 *
 * Nothing from electron is required here, so main.js can use it and `node test-lib.js` can test it on any OS:
 *   - run(): a command with a timeout (on Windows through cmd.exe, so .cmd shims like npm and claude resolve)
 *   - the prerequisite checks (git, node, python, ffmpeg, claude) with install hints
 *   - settings load/save, port probing, an HTTP poll, a log ring buffer
 *   - the PowerShell lines that install what is missing, where the real claude executable is, the office folder,
 *     and whether Claude Code is signed in
 *   - phone access: the addresses, the password, the engine environment, Tailscale detection and the secure https link
 *     (tailscale serve): the commands, and reading what they print
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

// ---------------------------------------------------------------- phone access

// the engine settings phone access controls; anything the user's own environment has for them is dropped first,
// so a stray HQ_HOST or HQ_TRUST_PROXY on the PC can never open the office by accident
const PHONE_ENV_KEYS = ["HQ_HOST", "HQ_PASSWORD", "HQ_SECRET", "HQ_LOCAL_TRUST", "HQ_TRUST_PROXY"];
const PHONE_MIN_PASSWORD = 8;
const REDACTED = "********";

/** True for an address in Tailscale's range, 100.64.0.0/10 (100.64.0.0 to 100.127.255.255). */
function isTailscaleIp(ip) {
  const m = /^100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(String(ip || ""));
  return !!m && +m[1] >= 64 && +m[1] <= 127 && +m[2] <= 255 && +m[3] <= 255;
}

/**
 * The addresses a phone can type, from an os.networkInterfaces() object: every IPv4 that is not internal and not
 * link-local (169.254.x.x, what Windows gives an adapter with no network), as http://<ip>:<port>.
 * Returns [{ ip, url, iface, tailscale, label }] with the Tailscale ones first, each address once.
 */
function phoneAddresses(ifaces, port) {
  const out = [];
  const seen = new Set();
  for (const [iface, list] of Object.entries(ifaces || {})) {
    for (const a of Array.isArray(list) ? list : []) {
      if (!a || a.internal) continue;
      const v4 = a.family === "IPv4" || a.family === 4;       // Node 18.0-18.3 reported the family as a number
      if (!v4 || !/^\d{1,3}(\.\d{1,3}){3}$/.test(a.address || "")) continue;
      if (/^169\.254\./.test(a.address) || /^127\./.test(a.address) || seen.has(a.address)) continue;
      seen.add(a.address);
      const tailscale = isTailscaleIp(a.address) || /tailscale/i.test(iface);
      out.push({ ip: a.address, url: `http://${a.address}:${port}`, iface, tailscale, label: tailscale ? "works anywhere (Tailscale)" : "same Wi-Fi only" });
    }
  }
  return out.sort((x, y) => (y.tailscale - x.tailscale));
}

// short, common words that are easy to type on a phone keyboard (no look-alikes, no capitals)
const PASSWORD_WORDS = (
  "acorn amber anchor apple arrow aspen autumn badge bagel bamboo banjo basil beacon berry bison blossom breeze brick " +
  "bridge bronze bubble cabin cactus camel candle canoe canyon carbon carrot castle cedar cherry chess cider cinema " +
  "circus citrus clover cobalt comet copper coral cotton crane crayon cricket crystal cupcake daisy delta denim desert " +
  "dolphin dragon drum eagle easel ember falcon fern fiddle flame forest fossil fox galaxy garden garlic gecko ginger " +
  "glacier globe goose granite grape gravel guitar hammer harbor hazel helmet heron honey hornet iceberg igloo indigo " +
  "island ivory jacket jaguar jasmine jelly jungle kettle kiwi koala ladder lagoon lantern lemon lily lizard lobster " +
  "lotus magnet mango maple marble meadow melon meteor mint mirror mitten monkey moose mosaic muffin nectar needle " +
  "nickel noodle nutmeg oasis ocean olive onion orbit orchid otter owl paddle panda papaya parrot peach pebble pepper " +
  "piano pickle pigeon pillow pine planet plum pocket polar pony poppy potato prism pumpkin puzzle quartz quill rabbit " +
  "radar radish raven ribbon river robin rocket rose ruby saddle salmon sapphire satin scarf scooter shadow shell " +
  "silver sketch sled snail sparrow spider spruce squash stamp star stone sugar summit sunset swan tango teapot " +
  "thistle thunder tiger timber toast tomato topaz tractor tulip tundra turtle tuxedo umbrella valley velvet violet " +
  "walnut walrus whale willow window winter wizard yogurt zebra zephyr"
).split(" ");

/**
 * A readable password: three words and two digits, like "maple-otter-lantern-42" (about 31 bits; the engine also
 * slows down every address after 5 wrong tries). `randomInt(n)` returns 0..n-1; crypto.randomInt by default.
 */
function generatePassword(randomInt) {
  const rnd = randomInt || require("crypto").randomInt;
  const words = [];
  while (words.length < 3) {
    const w = PASSWORD_WORDS[rnd(PASSWORD_WORDS.length)];
    if (!words.includes(w)) words.push(w);
  }
  return words.join("-") + "-" + String(rnd(100)).padStart(2, "0");
}

/** "" when the phone password is fine, else the problem in one plain sentence. */
function passwordProblem(pw) {
  if (typeof pw !== "string" || !pw) return "Type a password first, or press Generate.";
  if (pw.length < PHONE_MIN_PASSWORD) return `The password needs at least ${PHONE_MIN_PASSWORD} characters. Type a longer one or press Generate.`;
  if (pw.length > 200) return "The password is too long. Use at most 200 characters.";
  if (/[\r\n\0]/.test(pw)) return "The password cannot contain line breaks.";
  return "";
}

/**
 * The environment of the engine: the app's own environment plus HQ_PORT and, with `phone` = { password, secret },
 * phone access: listen on every network (HQ_HOST=0.0.0.0), ask for the password (HQ_PASSWORD), keep phones logged in
 * across restarts (HQ_SECRET) and let this computer's own window in without a login (HQ_LOCAL_TRUST=1).
 * HQ_TRUST_PROXY is never set: with it, anyone could claim to be this computer through X-Forwarded-For.
 * Without `phone` the engine listens on 127.0.0.1 only, as it always did.
 */
function buildEngineEnv(base, opts = {}) {
  const env = { ...(base || {}) };
  for (const k of PHONE_ENV_KEYS) delete env[k];
  env.HQ_PORT = String(opts.port || DEFAULT_PORT);
  env.PYTHONIOENCODING = "utf-8";
  env.PYTHONUNBUFFERED = "1";
  if (opts.claudeBin) env.CLAUDE_BIN = opts.claudeBin;
  const phone = opts.phone;
  if (phone && !passwordProblem(phone.password) && phone.secret) {
    env.HQ_HOST = "0.0.0.0";
    env.HQ_PASSWORD = phone.password;
    env.HQ_SECRET = phone.secret;
    env.HQ_LOCAL_TRUST = "1";
  }
  return env;
}

/** The line with every secret (4+ characters) replaced by ********, plus anything written as HQ_PASSWORD=... or HQ_SECRET=... */
function redact(line, secrets = []) {
  let s = String(line);
  const list = secrets.filter((x) => typeof x === "string" && x.length >= 4).sort((a, b) => b.length - a.length);
  for (const x of list) s = s.split(x).join(REDACTED);
  return s.replace(/\b(HQ_PASSWORD|HQ_SECRET)(\s*[=:]\s*)("[^"]*"|'[^']*'|\S+)/g, (m, k, sep) => k + sep + REDACTED);
}

/** The first Tailscale address in the output of `tailscale ip -4`, or "". */
function parseTailscaleIp(text) {
  for (const l of String(text || "").replace(/\r/g, "").split("\n")) if (isTailscaleIp(l.trim())) return l.trim();
  return "";
}

/**
 * What `tailscale ip -4` said: { state: "connected", ip } | { state: "signed-out" } (installed, but not signed in or
 * not running) | { state: "missing" } (no tailscale command). `res` is a run() result.
 */
function tailscaleState(res) {
  const ip = res && res.code === 0 ? parseTailscaleIp(res.stdout) : "";
  if (ip) return { state: "connected", ip };
  if (commandMissing(res)) return { state: "missing", ip: "" };
  return { state: "signed-out", ip: "" };
}

/** All the text a run() result has: error, stderr and stdout. */
function resultText(res) {
  return String((res && res.error) || "") + "\n" + String((res && res.stderr) || "") + "\n" + String((res && res.stdout) || "");
}

/** True when a run() result says the tailscale command does not exist (cmd.exe 9009, sh 127, ENOENT). */
function commandMissing(res) {
  return !res || res.code === 127 || res.code === 9009 || (!!res.error && !res.timedOut && /ENOENT|not found/i.test(res.error)) ||
    /is not recognized as an internal or external command|tailscale(\.exe)?: (command )?not found/i.test(resultText(res));
}

/** Where Tailscale installs its command on Windows (on the PATH too, but only for programs started after the install). */
const TAILSCALE_WIN_EXE = "C:\\Program Files\\Tailscale\\tailscale.exe";

/** Detect Tailscale with `tailscale ip -4` (10 s timeout). `opts.run` and `opts.exists` replace the runner and fs.existsSync (tests). */
async function checkTailscale(opts = {}) {
  const runner = opts.run || run;
  const exists = opts.exists || fs.existsSync;
  let res = await runner("tailscale", ["ip", "-4"], { timeoutMs: CHECK_TIMEOUT_MS });
  let st = tailscaleState(res);
  if (st.state === "missing" && (opts.isWin != null ? opts.isWin : IS_WIN) && exists(TAILSCALE_WIN_EXE)) {
    res = await runner(TAILSCALE_WIN_EXE, ["ip", "-4"], { timeoutMs: CHECK_TIMEOUT_MS });
    st = tailscaleState(res);
    if (st.state === "missing") st = { state: "signed-out", ip: "" };      // the program is there, it just did not answer
  }
  return st;
}

/** The PowerShell lines that install Tailscale with winget (run in a visible window, like the tool installs). */
function tailscaleInstallLines() {
  return [
    "Write-Host 'Agents HQ: installing Tailscale. Approve the Windows prompt when it appears.' -ForegroundColor Yellow",
    "winget install -e --id tailscale.tailscale --accept-package-agreements --accept-source-agreements",
    "Write-Host 'Done. Open Tailscale from the Start menu and sign in, then go back to Agents HQ and press Check Tailscale.' -ForegroundColor Green",
  ];
}

// ---------------------------------------------------------------- the secure link: tailscale serve (https)
//
// `tailscale serve` gives this computer an https address inside the owner's tailnet, https://<computer>.<tailnet>.ts.net/,
// with a real certificate, and relays it to the engine on 127.0.0.1. The iPhone then shows no "not secure" page and the
// office page is a secure context (microphone, clipboard). It is tailnet only: Funnel (the public internet) is never used.
// The relayed requests reach the engine from 127.0.0.1 but carry X-Forwarded-* and Tailscale-User-* headers, and
// hq/server.py makes every relayed request log in with the phone password, even with HQ_LOCAL_TRUST=1.

const TAILSCALE_TIMEOUT_MS = 20000;
const TAILSCALE_ADMIN_DNS = "https://login.tailscale.com/admin/dns";

/** `tailscale serve --bg --https=443 http://127.0.0.1:<port>`: the secure link on, kept by Tailscale in the background. */
function serveOnArgs(port) {
  return ["serve", "--bg", "--https=443", `http://127.0.0.1:${Number(port) || DEFAULT_PORT}`];
}

/** `tailscale serve --https=443 off`: only the https link this app made goes away. */
function serveOffArgs() {
  return ["serve", "--https=443", "off"];
}

/** `tailscale serve reset`: every serve setting goes away (the fallback when the off command fails). */
function serveResetArgs() {
  return ["serve", "reset"];
}

/** `tailscale serve status --json`, or with `json` false the plain text form (older versions without --json). */
function serveStatusArgs(json = true) {
  return json ? ["serve", "status", "--json"] : ["serve", "status"];
}

/** `tailscale status --json`: this computer's name in the tailnet (Self.DNSName). */
function statusJsonArgs() {
  return ["status", "--json"];
}

/** The JSON object in a command's output (text before the first "{" or after the last "}" is ignored), or null. */
function parseJsonOutput(text) {
  const s = String(text || "");
  const a = s.indexOf("{"), b = s.lastIndexOf("}");
  if (a < 0 || b < a) return null;
  try {
    const obj = JSON.parse(s.slice(a, b + 1));
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : null;
  } catch (_) {
    return null;
  }
}

/** A DNS name without its trailing dot, lower case, or "" when it is not a plain host name. */
function cleanDnsName(name) {
  const s = String(name || "").trim().replace(/\.+$/, "").toLowerCase();
  return /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(s) ? s : "";
}

/**
 * What `tailscale status --json` says about this computer: { dnsName (no trailing dot), magicDns (true, false or null when
 * not reported), certDomains, backend ("Running", "NeedsLogin", "Stopped"...) }. Never throws; dnsName "" when unknown.
 */
function parseStatusJson(text) {
  const obj = parseJsonOutput(text);
  if (!obj) return { dnsName: "", magicDns: null, certDomains: [], backend: "" };
  const self = obj.Self && typeof obj.Self === "object" ? obj.Self : {};
  const tailnet = obj.CurrentTailnet && typeof obj.CurrentTailnet === "object" ? obj.CurrentTailnet : null;
  return {
    dnsName: cleanDnsName(self.DNSName),
    magicDns: tailnet && typeof tailnet.MagicDNSEnabled === "boolean" ? tailnet.MagicDNSEnabled : null,
    certDomains: Array.isArray(obj.CertDomains) ? obj.CertDomains.map(cleanDnsName).filter(Boolean) : [],
    backend: typeof obj.BackendState === "string" ? obj.BackendState : "",
  };
}

/** https://<dnsname>/ for a tailnet name, or "". */
function secureUrl(dnsName) {
  const d = cleanDnsName(dnsName);
  return d ? `https://${d}/` : "";
}

/** True for a secure link address: https://<name>.ts.net/ (what phone:qr may turn into a QR code). */
function isSecureUrl(url) {
  return /^https:\/\/[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.ts\.net\/?$/.test(String(url || ""));
}

/** True for a link the app may open in the system browser from the secure link card: https://login.tailscale.com/... only. */
function isTailscaleAdminLink(url) {
  return typeof url === "string" && url.length <= 2000 && /^https:\/\/login\.tailscale\.com\/[^\s"'<>\\]*$/.test(url);
}

/** The local port a serve proxy target points at ("http://127.0.0.1:7331", "localhost:7331", "7331"), or 0 for anything else. */
function proxyPort(target) {
  const m = /^(?:https?:\/\/)?(?:(?:127\.0\.0\.1|localhost|\[::1\]):)?(\d{1,5})\/?$/i.exec(String(target || "").trim());
  return m ? +m[1] : 0;
}

/**
 * Does port 443 of the secure link relay to our engine? Reads `tailscale serve status --json` (the ServeConfig:
 * Web["<host>:443"].Handlers["/"].Proxy, also inside Foreground sessions) or, for older versions, the plain text form
 * ("https://<host> (tailnet only)" then "|-- / proxy http://127.0.0.1:7331").
 * Returns { on (443 relays to `port`), proxy (what 443 relays to, or ""), host, funnel (443 is open to the internet) }.
 */
function parseServeStatus(text, port) {
  const found = { proxy: "", host: "", funnel: false };
  const obj = parseJsonOutput(text);
  if (obj) {
    const configs = [obj];
    if (obj.Foreground && typeof obj.Foreground === "object") for (const c of Object.values(obj.Foreground)) if (c && typeof c === "object") configs.push(c);
    for (const sc of configs) {
      const web = sc.Web && typeof sc.Web === "object" ? sc.Web : {};
      for (const [hostPort, cfg] of Object.entries(web)) {
        const m = /^(.+):443$/.exec(hostPort);
        if (!m || !cfg || typeof cfg.Handlers !== "object" || !cfg.Handlers) continue;
        const root = cfg.Handlers["/"];
        const proxy = root && typeof root.Proxy === "string" ? root.Proxy : "";
        if (!proxy || found.proxy) continue;
        found.proxy = proxy;
        found.host = cleanDnsName(m[1]);
        found.funnel = !!(sc.AllowFunnel && sc.AllowFunnel[hostPort]);
      }
    }
  } else {
    let host = "", funnel = false;
    for (const raw of String(text || "").replace(/\r/g, "").split("\n")) {
      const line = raw.trim();
      const h = /^https:\/\/([^\s/:]+)(:\d+)?\/?(\s|$)/.exec(line);
      if (h) { host = h[2] && h[2] !== ":443" ? "" : h[1]; funnel = /funnel on/i.test(line); continue; }
      const p = /^\|--\s+\/\s+proxy\s+(\S+)/.exec(line);
      if (p && host && !found.proxy) { found.proxy = p[1]; found.host = cleanDnsName(host); found.funnel = funnel; }
    }
  }
  return { on: !!found.proxy && proxyPort(found.proxy) === Number(port), ...found };
}

/**
 * What went wrong with a tailscale command, in a form the phone window can show: null when nothing did, else
 * { kind, message, link }. kind is one of
 *   https-off      HTTPS certificates (or Serve) are not enabled on the tailnet; `link` is the admin page that enables them
 *   magicdns-off   MagicDNS is disabled on the tailnet; `link` is the DNS page of the admin
 *   access-denied  tailscaled refused the change
 *   old-version    this Tailscale does not know `serve --bg`
 *   not-running    Tailscale is installed but not running or not signed in
 *   missing        no tailscale command
 *   timeout        no answer within the time limit
 *   failed         anything else (message: the CLI's first line)
 * The CLI prints the admin link while it waits for HTTPS to be enabled ("Serve is not enabled on your tailnet. To enable,
 * visit: https://login.tailscale.com/f/serve?node=..."), so that output counts even when the command timed out.
 */
function serveProblem(res) {
  const text = resultText(res);
  if (res && res.code === 0 && !res.timedOut && !res.error) return null;
  const link = (/https:\/\/login\.tailscale\.com\/[^\s"'<>\\)]+/.exec(text) || [""])[0].replace(/[.,;]+$/, "");
  if (/MagicDNS (is )?(disabled|not enabled|off)|enable MagicDNS/i.test(text)) {
    return { kind: "magicdns-off", link: link || TAILSCALE_ADMIN_DNS, message: "Turn on MagicDNS in your Tailscale admin (the DNS page), then press Turn on again." };
  }
  if (/(serve|https|https certificates|certificates|tls certificates?) (is |are )?not (enabled|available|supported)|not enabled on your tailnet|enable https|https is disabled|does not support getting tls certs|login\.tailscale\.com\/f\/(serve|https)/i.test(text)) {
    return { kind: "https-off", link: link || TAILSCALE_ADMIN_DNS, message: "Turn on HTTPS certificates in your Tailscale admin, then press Turn on again." };
  }
  if (commandMissing(res)) return { kind: "missing", link: "", message: "Tailscale is not installed on this computer. Install it below, sign in, then press Turn on again." };
  if (/access denied|permission denied|requires (root|administrator)/i.test(text)) {
    return { kind: "access-denied", link: "", message: "Tailscale refused the change (access denied). Make sure Tailscale on this computer is signed in with your own account, then press Turn on again." };
  }
  if (/flag provided but not defined|unknown flag|invalid argument|unknown subcommand/i.test(text)) {
    return { kind: "old-version", link: "", message: "This Tailscale is too old for the secure link. Update it from tailscale.com/download, then press Turn on again." };
  }
  if (/failed to connect to local tailscaled|is tailscaled running|tailscale is stopped|NeedsLogin|not logged in|logged out/i.test(text)) {
    return { kind: "not-running", link: "", message: "Tailscale is not running or not signed in on this computer. Open Tailscale, sign in, then press Turn on again." };
  }
  if (res && res.timedOut) return { kind: "timeout", link: "", message: "Tailscale did not answer within 20 seconds. Check that it is running, then press Turn on again." };
  const first = firstLine(res && (res.stderr || res.stdout || res.error)) || "exit code " + (res ? res.code : "none");
  return { kind: "failed", link: "", message: "Tailscale answered: " + first.slice(0, 300) };
}

/**
 * Run tailscale with these arguments (20 s timeout): the `tailscale` on the PATH, or on Windows the one in Program Files
 * when the PATH does not have it yet. `opts.run`, `opts.exists` and `opts.isWin` replace the runner, fs.existsSync and
 * the platform (tests); `opts.timeoutMs` the time limit. Never throws.
 */
async function runTailscale(args, opts = {}) {
  const runner = opts.run || run;
  const exists = opts.exists || fs.existsSync;
  const timeoutMs = opts.timeoutMs || TAILSCALE_TIMEOUT_MS;
  let res;
  try {
    res = await runner("tailscale", args, { timeoutMs });
    if (commandMissing(res) && (opts.isWin != null ? opts.isWin : IS_WIN) && exists(TAILSCALE_WIN_EXE)) res = await runner(TAILSCALE_WIN_EXE, args, { timeoutMs });
  } catch (e) {
    res = { line: "tailscale " + args.join(" "), code: null, stdout: "", stderr: "", error: e.message, timedOut: false };
  }
  return { ...res, line: res.line || "tailscale " + args.join(" ") };
}

/**
 * One step for main.js's log: { line, code, timedOut, output (the first lines of what it printed) }. With `summary`, a
 * command that worked logs that one line instead of its output (`tailscale status --json` lists every device).
 */
function stepOf(res, summary) {
  const ok = res.code === 0 && !res.timedOut && !res.error;
  const output = ok && summary ? [summary]
    : [res.stdout, res.stderr, res.error].filter(Boolean).join("\n").replace(/\r/g, "").split("\n").map((l) => l.trimEnd()).filter((l) => l.trim()).slice(0, 12);
  return { line: res.line, code: res.code, timedOut: !!res.timedOut, output };
}

/** This computer's tailnet name and its https address: { ok, dnsName, url, magicDns, certDomains, problem, steps }. */
async function readSecureName(opts = {}) {
  const res = await runTailscale(statusJsonArgs(), opts);
  const st = parseStatusJson(res.stdout);
  const steps = [stepOf(res, "this computer is " + (st.dnsName || "(no name)") + (st.magicDns === false ? ", MagicDNS off" : "") + (st.backend ? ", " + st.backend : ""))];
  if (!st.dnsName) {
    const problem = serveProblem(res) || (st.backend && st.backend !== "Running"
      ? { kind: "not-running", link: "", message: "Tailscale is not running or not signed in on this computer. Open Tailscale, sign in, then press Turn on again." }
      : { kind: "failed", link: "", message: "Tailscale did not say this computer's name. Check that Tailscale is signed in, then try again." });
    return { ok: false, dnsName: "", url: "", magicDns: st.magicDns, certDomains: st.certDomains, problem, steps };
  }
  if (st.magicDns === false) {
    return { ok: false, dnsName: st.dnsName, url: secureUrl(st.dnsName), magicDns: false, certDomains: st.certDomains, steps,
      problem: { kind: "magicdns-off", link: TAILSCALE_ADMIN_DNS, message: "Turn on MagicDNS in your Tailscale admin (the DNS page), then press Turn on again." } };
  }
  return { ok: true, dnsName: st.dnsName, url: secureUrl(st.dnsName), magicDns: st.magicDns, certDomains: st.certDomains, problem: null, steps };
}

/** Does the secure link relay to `port` right now? `tailscale serve status --json`, then the plain form. { on, proxy, host, funnel, steps }. */
async function readServeStatus(port, opts = {}) {
  const say = (s) => "443 relays to " + (s.proxy || "nothing") + (s.funnel ? " (Funnel on: open to the internet)" : "");
  let res = await runTailscale(serveStatusArgs(true), opts);
  let s = res.code === 0 ? parseServeStatus(res.stdout, port) : { on: false, proxy: "", host: "", funnel: false };
  const steps = [stepOf(res, say(s))];
  if (res.code !== 0 && /flag provided but not defined|unknown flag/i.test(resultText(res))) {
    res = await runTailscale(serveStatusArgs(false), opts);
    s = res.code === 0 ? parseServeStatus(res.stdout, port) : s;
    steps.push(stepOf(res, say(s)));
  }
  return { ...s, steps };
}

/**
 * The secure link as it is: { ok, on (443 relays to `port`), url, dnsName, proxy, funnel, problem, steps }.
 * `url` is https://<dnsname>/ whenever Tailscale says the name, also while the link is off.
 */
async function secureLinkInfo(port, opts = {}) {
  const name = await readSecureName(opts);
  if (!name.dnsName) return { ok: false, on: false, url: "", dnsName: "", proxy: "", funnel: false, problem: name.problem, steps: name.steps };
  const s = await readServeStatus(port, opts);
  return { ok: true, on: s.on, url: name.url, dnsName: name.dnsName, proxy: s.proxy, funnel: s.funnel, problem: s.on ? null : name.problem, steps: [...name.steps, ...s.steps] };
}

/**
 * Turn the secure link on for the engine on `port`: tailscale serve --bg --https=443 http://127.0.0.1:<port>, then read
 * the https address and what 443 relays to. { ok, url, dnsName, verified (443 relays to `port`), funnel, problem, steps }. When HTTPS is not enabled on the tailnet, problem.kind is
 * "https-off" with the admin link that enables it.
 */
async function enableSecureLink(port, opts = {}) {
  const res = await runTailscale(serveOnArgs(port), opts);
  const steps = [stepOf(res)];
  const problem = serveProblem(res);
  if (problem) return { ok: false, url: "", dnsName: "", problem, steps };
  const name = await readSecureName(opts);
  steps.push(...name.steps);
  // serve is on, but without MagicDNS the phone cannot find the name: the owner has to turn it on first
  if (name.problem && name.problem.kind === "magicdns-off") return { ok: false, url: name.url, dnsName: name.dnsName, problem: name.problem, steps };
  const fromOutput = (/https:\/\/([a-z0-9.-]+\.ts\.net)\/?/i.exec(res.stdout || "") || [])[1] || "";
  const dnsName = name.dnsName || cleanDnsName(fromOutput);
  if (!dnsName) return { ok: false, url: "", dnsName: "", problem: name.problem, steps };
  // check what 443 relays to now (informational: a format this version cannot read does not fail the call)
  const s = await readServeStatus(port, opts);
  steps.push(...s.steps);
  return { ok: true, url: secureUrl(dnsName), dnsName, verified: s.on, funnel: s.funnel, problem: null, steps };
}

/** Turn the secure link off: tailscale serve --https=443 off, and `tailscale serve reset` when that fails. { ok, problem, steps }. */
async function disableSecureLink(opts = {}) {
  const res = await runTailscale(serveOffArgs(), opts);
  const steps = [stepOf(res)];
  // "off" for a port that serves nothing is an error in some versions: nothing to turn off is fine
  if (res.code === 0 || /not (being )?served|nothing to (remove|turn off)|no serve config|does not exist/i.test(resultText(res))) return { ok: true, problem: null, steps };
  if (commandMissing(res)) return { ok: true, problem: null, steps };              // no Tailscale, no secure link
  const reset = await runTailscale(serveResetArgs(), opts);
  steps.push(stepOf(reset));
  if (reset.code === 0) return { ok: true, problem: null, steps };
  return { ok: false, problem: serveProblem(reset) || serveProblem(res), steps };
}

// ---------------------------------------------------------------- the log ring buffer

/**
 * The last `max` log lines, with listeners for new ones. push() splits chunks into lines.
 * `opts.redact(line)` rewrites every line before it is kept or passed on (main.js hides the phone password with it).
 */
class RingLog {
  constructor(max = 400, opts = {}) {
    this.max = max;
    this.items = [];
    this.listeners = [];
    this.partial = "";
    this.redact = opts.redact || null;
  }

  push(chunk) {
    const text = this.partial + String(chunk).replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    this.partial = text.endsWith("\n") ? "" : lines.pop();
    for (const raw of lines) {
      let line = raw.trimEnd();
      if (!line) continue;
      if (this.redact) { try { line = this.redact(line); } catch (_) { line = REDACTED; } }
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
  PHONE_ENV_KEYS, PHONE_MIN_PASSWORD, PASSWORD_WORDS, TAILSCALE_WIN_EXE,
  isTailscaleIp, phoneAddresses, generatePassword, passwordProblem, buildEngineEnv, redact,
  parseTailscaleIp, tailscaleState, checkTailscale, tailscaleInstallLines, commandMissing,
  TAILSCALE_TIMEOUT_MS, TAILSCALE_ADMIN_DNS, serveOnArgs, serveOffArgs, serveResetArgs, serveStatusArgs, statusJsonArgs,
  parseJsonOutput, cleanDnsName, parseStatusJson, secureUrl, isSecureUrl, isTailscaleAdminLink, proxyPort, parseServeStatus,
  serveProblem, runTailscale, readSecureName, readServeStatus, secureLinkInfo, enableSecureLink, disableSecureLink,
  RingLog,
};
