"use strict";
/* test-lib.js: exercises lib.js with plain node (no electron). Run: node test-lib.js
 * Exits 1 when a check fails. Works on Linux, macOS and Windows; the tool checks need git, node and python3 on the
 * machine (they are on the CI box and on the owner's PC once the app installed them); ffmpeg is checked when present.
 */
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const net = require("net");
const http = require("http");
const path = require("path");
const lib = require("./lib");

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// ---------------------------------------------------------------- helpers

/** A fake runner: answers per command name, like { python: { code: 0, stdout: "Python 3.12.1" } }. */
function fakeRunner(table) {
  return async (cmd, args = []) => {
    const key = cmd + (args.length > 1 ? " " + args.slice(0, -1).join(" ") : "");   // "py -3", "python"
    const r = table[key] || table[cmd] || { code: null, error: "spawn " + cmd + " ENOENT" };
    return { line: cmd, code: r.code === undefined ? 0 : r.code, stdout: r.stdout || "", stderr: r.stderr || "", error: r.error || null, timedOut: !!r.timedOut };
  };
}

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "agents-hq-test-"));
}

// ---------------------------------------------------------------- command lines

test("quoteArg and cmdline quote spaces and quotes", () => {
  assert.strictEqual(lib.quoteArg("plain"), "plain");
  assert.strictEqual(lib.quoteArg("C:\\Users\\John Ooi\\x"), '"C:\\Users\\John Ooi\\x"');
  assert.strictEqual(lib.quoteArg(""), '""');
  assert.strictEqual(lib.cmdline("git", ["clone", "https://x", "C:\\Users\\John Ooi\\Documents\\Agents HQ"]),
    'git clone https://x "C:\\Users\\John Ooi\\Documents\\Agents HQ"');
});

test("run() never throws for a missing command", async () => {
  const res = await lib.run("agents-hq-no-such-command-xyz", ["--version"], { timeoutMs: 5000 });
  assert.notStrictEqual(res.code, 0);
  assert.ok(res.error || res.stderr, "a missing tool reports an error or stderr");
});

test("run() honours its timeout", async () => {
  const slow = lib.IS_WIN ? ["ping", ["-n", "6", "127.0.0.1"]] : ["sleep", ["5"]];
  const t0 = Date.now();
  const res = await lib.run(slow[0], slow[1], { timeoutMs: 400 });
  assert.strictEqual(res.timedOut, true);
  assert.ok(Date.now() - t0 < 4000, "returned soon after the timeout");
});

test("run() collects stdout", async () => {
  const res = await lib.run("node", ["-e", "process.stdout.write('hello')"]);
  assert.strictEqual(res.code, 0);
  assert.strictEqual(res.stdout.trim(), "hello");
});

// ---------------------------------------------------------------- parsing

test("parseVersion and firstLine", () => {
  assert.deepStrictEqual(lib.parseVersion("git version 2.43.0.windows.1"), { text: "2.43.0", major: 2, minor: 43, patch: 0 });
  assert.deepStrictEqual(lib.parseVersion("v22.1"), { text: "22.1", major: 22, minor: 1, patch: 0 });
  assert.strictEqual(lib.parseVersion("nothing here"), null);
  assert.strictEqual(lib.firstLine("\r\n\r\n  ffmpeg version 6.1 \r\nbuilt with gcc"), "ffmpeg version 6.1");
  assert.strictEqual(lib.firstLine(""), "");
});

// ---------------------------------------------------------------- the real tools on this machine

test("checkAll finds git, node and python on this machine (and ffmpeg when it is there)", async () => {
  const res = await lib.checkAll();
  const by = Object.fromEntries(res.tools.map((t) => [t.name, t]));
  for (const t of res.tools) console.log(`      ${t.label.padEnd(14)} ${t.ok ? "ok  " + t.version : "missing: " + t.detail}`);
  assert.strictEqual(res.tools.length, 5);
  for (const t of res.tools) {
    assert.ok(typeof t.hint === "string" && t.hint.length > 0, t.name + " has an install hint");
    assert.ok(["ok", "version", "name", "label", "required"].every((k) => k in t), t.name + " has the expected fields");
  }
  assert.strictEqual(by.git.ok, true, "git is detected: " + by.git.detail);
  assert.strictEqual(by.node.ok, true, "node is detected: " + by.node.detail);
  assert.strictEqual(by.python.ok, true, "python is detected: " + by.python.detail);
  assert.ok(/^3\.\d+/.test(by.python.version.replace("Python ", "")), "python version is 3.x");
  assert.ok(Array.isArray(res.python) && res.python.length >= 1, "the python command that worked is remembered");
  if (!by.ffmpeg.ok) console.log("      (ffmpeg not on this machine; skipping that assertion)");
  else assert.ok(by.ffmpeg.version, "ffmpeg reports a version");
  assert.strictEqual(res.requiredOk, by.node.ok && by.python.ok && by.claude.ok);
  assert.strictEqual(res.allOk, res.tools.every((t) => t.ok));
});

test("hints are the agreed install commands", () => {
  const hints = Object.fromEntries(lib.TOOLS.map((t) => [t.name, t.hint]));
  assert.strictEqual(hints.git, "winget install -e --id Git.Git");
  assert.strictEqual(hints.node, "winget install -e --id OpenJS.NodeJS.LTS");
  assert.strictEqual(hints.python, "winget install -e --id Python.Python.3.12");
  assert.strictEqual(hints.ffmpeg, "winget install -e --id Gyan.FFmpeg");
  assert.strictEqual(hints.claude, "irm https://claude.ai/install.ps1 | iex", "the native installer: a real claude.exe, not the npm .cmd shim");
});

// ---------------------------------------------------------------- python: the Windows Store alias and old versions

test("checkPython skips a command that prints nothing (the Windows Store alias) and takes the next", async () => {
  // simulated: "py -3" missing, "python" is the Store alias (no output, exit 9009), "python3" works
  const runner = fakeRunner({
    "py -3": { code: null, error: "spawn py ENOENT" },
    python: { code: 9009, stdout: "", stderr: "" },
    python3: { code: 0, stdout: "Python 3.12.4\n" },
  });
  const res = await lib.checkPython(runner);
  assert.strictEqual(res.ok, true);
  assert.deepStrictEqual(res.cmd, ["python3"]);
  assert.strictEqual(res.version, "Python 3.12.4");
});

test("checkPython with a real silent command first (prints nothing, exits non-zero)", async () => {
  // `false` behaves like the Store alias: no output, non-zero exit. node is used as a stand-in python that works.
  const silent = lib.IS_WIN ? ["cmd", "/c", "exit", "9009"] : ["false"];
  const works = ["node", "-e", "console.log('Python 3.11.9')", "--"];
  const res = await lib.checkPython(lib.run, [silent, works]);
  assert.strictEqual(res.ok, true, res.detail);
  assert.deepStrictEqual(res.cmd, works);
});

test("checkPython reports when every candidate is silent", async () => {
  const runner = fakeRunner({ "py -3": { code: 9009 }, python: { code: 9009 }, python3: { code: null, error: "ENOENT" } });
  const res = await lib.checkPython(runner);
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.cmd, null);
  assert.match(res.detail, /not installed|not on the PATH/);
});

test("checkPython rejects Python 2 and Python 3.9", async () => {
  const runner = fakeRunner({ "py -3": { code: 0, stdout: "Python 3.9.13" }, python: { code: 0, stderr: "Python 2.7.18" }, python3: { code: 0, stdout: "Python 3.9.0" } });
  const res = await lib.checkPython(runner);
  assert.strictEqual(res.ok, false);
  assert.match(res.detail, /3\.10 or newer/);
  assert.match(res.detail, /py -3 is Python 3\.9\.13/);
});

test("checkPython reads the version from stderr too (Python 2 style), and from 'py -3'", async () => {
  const runner = fakeRunner({ "py -3": { code: 0, stderr: "Python 3.10.0\r\n" } });
  const res = await lib.checkPython(runner);
  assert.strictEqual(res.ok, true);
  assert.deepStrictEqual(res.cmd, ["py", "-3"]);
});

// ---------------------------------------------------------------- the other checks, simulated

test("checkNode needs major >= 18", async () => {
  assert.strictEqual((await lib.checkNode(fakeRunner({ node: { stdout: "v16.20.2\n" } }))).ok, false);
  assert.match((await lib.checkNode(fakeRunner({ node: { stdout: "v16.20.2\n" } }))).detail, /too old/);
  assert.strictEqual((await lib.checkNode(fakeRunner({ node: { stdout: "v18.0.0\n" } }))).ok, true);
  assert.strictEqual((await lib.checkNode(fakeRunner({ node: { stdout: "v22.11.0\n" } }))).version, "22.11.0");
  const missing = await lib.checkNode(fakeRunner({}));
  assert.strictEqual(missing.ok, false);
  assert.match(missing.detail, /not installed/);
});

test("checkGit, checkFfmpeg, checkClaude parse their outputs", async () => {
  assert.deepStrictEqual(await lib.checkGit(fakeRunner({ git: { stdout: "git version 2.47.1.windows.1\n" } })), { ok: true, version: "2.47.1", detail: "" });
  const ff = await lib.checkFfmpeg(fakeRunner({ ffmpeg: { stdout: "ffmpeg version 7.1-full_build-www.gyan.dev Copyright (c) 2000-2024\nbuilt with gcc" } }));
  assert.strictEqual(ff.ok, true);
  assert.strictEqual(ff.version, "7.1-full_build-www.gyan.dev");
  const cl = await lib.checkClaude(fakeRunner({ claude: { stdout: "2.0.31 (Claude Code)\n" } }));
  assert.strictEqual(cl.ok, true);
  assert.strictEqual(cl.version, "2.0.31 (Claude Code)");
  const cl2 = await lib.checkClaude(fakeRunner({ claude: { code: 1, stderr: "'claude' is not recognized as an internal or external command" } }));
  assert.strictEqual(cl2.ok, false);
  assert.match(cl2.detail, /not installed|not on the PATH|answered/);
  const to = await lib.checkClaude(fakeRunner({ claude: { code: null, timedOut: true } }));
  assert.strictEqual(to.ok, false);
  assert.match(to.detail, /10 seconds/);
});

test("checkAll with a runner that throws still answers for every tool", async () => {
  const res = await lib.checkAll({ run: async () => { throw new Error("boom"); } });
  assert.strictEqual(res.tools.length, 5);
  assert.ok(res.tools.every((t) => t.ok === false));
  assert.strictEqual(res.allOk, false);
  assert.strictEqual(res.python, null);
});

// ---------------------------------------------------------------- the install script

test("installLines: the winget commands, then the native Claude Code installer with npm as the fallback", () => {
  const tools = lib.TOOLS.map((t) => ({ ...t, ok: t.name === "node" || t.name === "git" }));
  const lines = lib.installLines(tools);
  const s = lib.installScript(tools);
  assert.ok(Array.isArray(lines) && lines.every((l) => typeof l === "string" && !/[\r\n]/.test(l)), "one statement per line");
  assert.strictEqual(s, lines.join("; "), "installScript is the lines joined with '; '");
  assert.ok(lines.includes("winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements"), "python");
  assert.ok(s.includes("winget install -e --id Gyan.FFmpeg"), "ffmpeg");
  assert.ok(lines.includes("irm https://claude.ai/install.ps1 | iex"), "the native claude installer");
  assert.ok(lines.some((l) => /^if \(-not \(Test-Path "\$env:USERPROFILE\\\.local\\bin\\claude\.exe"\)\) \{ npm install -g @anthropic-ai\/claude-code \}$/.test(l)), "npm only as the fallback");
  assert.ok(!s.includes("Git.Git") && !s.includes("OpenJS"), "installed tools are not reinstalled");
  assert.ok(lines.length >= 6);
  assert.ok(s.indexOf("Gyan.FFmpeg") < s.indexOf("install.ps1") && s.indexOf("install.ps1") < s.indexOf("npm install"), "winget, then the native installer, then the fallback");
  const none = lib.installScript(lib.TOOLS.map((t) => ({ ...t, ok: true })));
  assert.ok(!none.includes("winget") && !none.includes("install.ps1") && !none.includes("npm install"));
});

// ---------------------------------------------------------------- the office folder and the sign-in guess

test("officeBase keeps the office out of OneDrive", () => {
  assert.strictEqual(lib.officeBase("C:\\Users\\John Ooi\\Documents", "C:\\Users\\John Ooi"), "C:\\Users\\John Ooi\\Documents");
  assert.strictEqual(lib.officeBase("C:\\Users\\John Ooi\\OneDrive\\Documents", "C:\\Users\\John Ooi"), "C:\\Users\\John Ooi");
  assert.strictEqual(lib.officeBase("C:\\Users\\John Ooi\\OneDrive - Contoso\\Documents", "C:\\Users\\John Ooi"), "C:\\Users\\John Ooi");
  assert.strictEqual(lib.officeBase("/home/john/Documents", "/home/john"), "/home/john/Documents");
  assert.strictEqual(lib.officeBase("", "/home/john"), "/home/john");
});

test("claudeSignedIn looks at the credentials file, ~/.claude.json and the environment", () => {
  const home = tmpdir();
  const env = {};
  assert.strictEqual(lib.claudeSignedIn(home, env), false, "an empty home is not signed in");
  assert.strictEqual(lib.claudeSignedIn(home, { ANTHROPIC_API_KEY: "sk-ant-x" }), true, "an API key counts");
  assert.strictEqual(lib.claudeSignedIn(home, { CLAUDE_CODE_OAUTH_TOKEN: "t" }), true, "an OAuth token counts");
  fs.writeFileSync(path.join(home, ".claude.json"), '{"numStartups": 3}');
  assert.strictEqual(lib.claudeSignedIn(home, env), false, "a .claude.json without an account");
  fs.writeFileSync(path.join(home, ".claude.json"), '{"oauthAccount": {"emailAddress": "x@y"}}');
  assert.strictEqual(lib.claudeSignedIn(home, env), true, "oauthAccount in .claude.json");
  fs.writeFileSync(path.join(home, ".claude.json"), "{ broken");
  assert.strictEqual(lib.claudeSignedIn(home, env), false, "a broken .claude.json is not a sign-in");
  fs.mkdirSync(path.join(home, ".claude"));
  fs.writeFileSync(path.join(home, ".claude", ".credentials.json"), "{}");
  assert.strictEqual(lib.claudeSignedIn(home, env), true, "the credentials file counts");
  const other = tmpdir();
  assert.strictEqual(lib.claudeSignedIn(other, { CLAUDE_CONFIG_DIR: path.join(home, ".claude") }), true, "CLAUDE_CONFIG_DIR is honoured");
  fs.rmSync(home, { recursive: true, force: true });
  fs.rmSync(other, { recursive: true, force: true });
});

// ---------------------------------------------------------------- settings

test("settings round-trip, defaults and a broken file", () => {
  const dir = tmpdir();
  const file = path.join(dir, "deep", "settings.json");          // the folder does not exist yet
  const defaults = { officeDir: "C:\\Users\\John Ooi\\Documents\\Agents HQ", port: 7331, setupDone: false };
  assert.deepStrictEqual(lib.loadSettings(file, defaults), defaults, "missing file -> defaults");
  const saved = lib.saveSettings(file, { ...defaults, port: 7333, setupDone: true });
  assert.deepStrictEqual(lib.loadSettings(file, defaults), saved, "round-trip");
  assert.strictEqual(lib.loadSettings(file, defaults).officeDir, "C:\\Users\\John Ooi\\Documents\\Agents HQ", "spaces and backslashes survive");
  assert.ok(!fs.existsSync(file + ".tmp"), "no temp file left behind");
  fs.writeFileSync(file, "{ not json");
  assert.deepStrictEqual(lib.loadSettings(file, defaults), defaults, "broken file -> defaults");
  fs.writeFileSync(file, '{"port": 7340}');
  assert.deepStrictEqual(lib.loadSettings(file, defaults), { ...defaults, port: 7340 }, "partial file merges over defaults");
  fs.writeFileSync(file, "[1,2]");
  assert.deepStrictEqual(lib.loadSettings(file, defaults), defaults, "an array is not settings");
  fs.rmSync(dir, { recursive: true, force: true });
});

// ---------------------------------------------------------------- ports

test("isPortFree and findPort", async () => {
  const srv = net.createServer();
  const busy = await listen(srv);
  try {
    assert.strictEqual(await lib.isPortFree(busy), false, "a listening port is not free");
    const found = await lib.findPort(busy);
    assert.ok(Number.isInteger(found), "a port was found");
    assert.notStrictEqual(found, busy, "not the busy one");
    assert.ok(found >= lib.DEFAULT_PORT && found <= lib.LAST_PORT, "falls back into 7331..7340");
    assert.strictEqual(await lib.isPortFree(found), true);
  } finally {
    await close(srv);
  }
  const srv2 = net.createServer();
  const freeNow = await listen(srv2);
  await close(srv2);
  assert.strictEqual(await lib.findPort(freeNow), freeNow, "the preferred port is kept when free");
});

// ---------------------------------------------------------------- HTTP helpers

test("waitForHttp and isAgentsHq against a local server", async () => {
  let ready = false;
  const srv = http.createServer((req, res) => {
    if (!ready) { res.writeHead(503); return res.end("starting"); }
    if (req.url === "/api/status") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ counts: { agents: 31 }, desk: { state: "idle" } })); }
    res.writeHead(200); res.end("<html>office</html>");
  });
  const port = await listen(srv);
  try {
    assert.strictEqual(await lib.isAgentsHq(port), false, "503 is not an engine");
    setTimeout(() => { ready = true; }, 300);
    const t0 = Date.now();
    assert.strictEqual(await lib.waitForHttp(`http://127.0.0.1:${port}/api/status`, { timeoutMs: 5000, intervalMs: 100 }), true);
    assert.ok(Date.now() - t0 >= 250, "waited for the server to become ready");
    assert.strictEqual(await lib.isAgentsHq(port), true, "the status JSON marks an Agents HQ engine");
    assert.strictEqual(await lib.waitForHttp(`http://127.0.0.1:${port}/x`, { timeoutMs: 1000, intervalMs: 50, shouldStop: () => true }), false, "shouldStop ends the wait");
  } finally {
    await close(srv);
  }
  const srv2 = net.createServer(); const dead = await listen(srv2); await close(srv2);
  assert.strictEqual(await lib.waitForHttp(`http://127.0.0.1:${dead}/api/status`, { timeoutMs: 600, intervalMs: 100 }), false, "nothing listening -> false after the timeout");
  assert.strictEqual(await lib.isAgentsHq(dead), false);
});

test("isAgentsHq rejects a 200 that is not the engine's status JSON", async () => {
  const srv = http.createServer((req, res) => { res.writeHead(200, { "Content-Type": "text/html" }); res.end("<html>some other app</html>"); });
  const port = await listen(srv);
  try { assert.strictEqual(await lib.isAgentsHq(port), false); } finally { await close(srv); }
});

// ---------------------------------------------------------------- the log ring buffer

test("RingLog splits chunks into lines, keeps partial lines, caps and notifies", () => {
  const log = new lib.RingLog(5);
  const seen = [];
  const off = log.onLine((l) => seen.push(l));
  log.push("one\r\ntwo\nthr");
  assert.deepStrictEqual(log.lines(), ["one", "two"], "the partial line waits");
  log.push("ee\n\n\nfour\n");
  assert.deepStrictEqual(log.lines(), ["one", "two", "three", "four"], "joined, blank lines dropped");
  log.push("five\nsix\nseven\n");
  assert.deepStrictEqual(log.lines(), ["three", "four", "five", "six", "seven"], "capped at 5");
  assert.deepStrictEqual(log.tail(2), ["six", "seven"]);
  assert.strictEqual(seen.length, 7);
  log.push("tail without newline");
  assert.strictEqual(log.lines().length, 5);
  log.flush();
  assert.strictEqual(log.lines()[4], "tail without newline", "flush pushes the partial line");
  off();
  log.push("after off\n");
  assert.strictEqual(seen.length, 8, "removed listeners stop getting lines");
  const bad = new lib.RingLog(3);
  bad.onLine(() => { throw new Error("listener broke"); });
  assert.doesNotThrow(() => bad.push("x\n"), "a broken listener does not break the log");
});

// ---------------------------------------------------------------- phone access

test("isTailscaleIp covers exactly 100.64.0.0/10", () => {
  for (const ip of ["100.64.0.1", "100.101.102.103", "100.127.255.254"]) assert.strictEqual(lib.isTailscaleIp(ip), true, ip);
  for (const ip of ["100.63.255.255", "100.128.0.1", "10.0.0.5", "192.168.1.20", "100.64.0", "", null, "100.64.0.256"]) assert.strictEqual(lib.isTailscaleIp(ip), false, String(ip));
});

test("phoneAddresses lists the LAN and Tailscale IPv4s, skips internal, IPv6 and link-local", () => {
  const ifaces = {
    lo: [{ address: "127.0.0.1", family: "IPv4", internal: true }, { address: "::1", family: "IPv6", internal: true }],
    "Wi-Fi": [
      { address: "fe80::1c2b:3a4d", family: "IPv6", internal: false },
      { address: "192.168.1.23", family: "IPv4", internal: false },
    ],
    Ethernet: [{ address: "169.254.10.20", family: "IPv4", internal: false }],                 // no network: skipped
    "vEthernet (WSL)": [{ address: "172.27.80.1", family: 4, internal: false }],               // Node 18.0-18.3 style family
    Tailscale: [{ address: "100.101.5.6", family: "IPv4", internal: false }, { address: "fd7a:115c:a1e0::1", family: "IPv6", internal: false }],
    utun4: [{ address: "100.88.1.2", family: "IPv4", internal: false }],                       // macOS: no Tailscale name, the range tells
    "Tailscale-named": [{ address: "10.9.8.7", family: "IPv4", internal: false }],             // Tailscale by its name
    dup: [{ address: "192.168.1.23", family: "IPv4", internal: false }],
  };
  const list = lib.phoneAddresses(ifaces, 7331);
  assert.deepStrictEqual(list.map((a) => a.ip), ["100.101.5.6", "100.88.1.2", "10.9.8.7", "192.168.1.23", "172.27.80.1"], "Tailscale first, each address once");
  const ts = list[0];
  assert.deepStrictEqual(ts, { ip: "100.101.5.6", url: "http://100.101.5.6:7331", iface: "Tailscale", tailscale: true, label: "works anywhere (Tailscale)" });
  const wifi = list.find((a) => a.ip === "192.168.1.23");
  assert.strictEqual(wifi.tailscale, false);
  assert.strictEqual(wifi.label, "same Wi-Fi only");
  assert.strictEqual(wifi.url, "http://192.168.1.23:7331");
  assert.ok(list.every((a) => !/^169\.254\./.test(a.ip) && !a.ip.includes(":") && a.ip !== "127.0.0.1"));
  assert.deepStrictEqual(lib.phoneAddresses({}, 7331), []);
  assert.deepStrictEqual(lib.phoneAddresses(null, 7331), []);
  assert.deepStrictEqual(lib.phoneAddresses({ x: [null, { family: "IPv4" }] }, 1), [], "broken entries are skipped");
  const real = lib.phoneAddresses(os.networkInterfaces(), 7663);
  assert.ok(Array.isArray(real));
  console.log("      this machine: " + (real.map((a) => a.url + " (" + a.label + ")").join(", ") || "no network addresses"));
});

test("generatePassword: three words and two digits, readable, random", () => {
  assert.strictEqual(new Set(lib.PASSWORD_WORDS).size, lib.PASSWORD_WORDS.length, "no duplicate words");
  assert.ok(lib.PASSWORD_WORDS.length >= 200, "at least 200 words");
  assert.ok(lib.PASSWORD_WORDS.every((w) => /^[a-z]{3,8}$/.test(w)), "lowercase a-z words only");
  const seen = new Set();
  for (let i = 0; i < 200; i++) {
    const pw = lib.generatePassword();
    assert.ok(/^[a-z]{3,8}-[a-z]{3,8}-[a-z]{3,8}-\d{2}$/.test(pw), "shape word-word-word-NN: " + pw);
    assert.ok(pw.length >= lib.PHONE_MIN_PASSWORD && pw.length <= 30, "length " + pw.length);
    assert.strictEqual(lib.passwordProblem(pw), "", "a generated password is always accepted");
    const words = pw.split("-").slice(0, 3);
    assert.strictEqual(new Set(words).size, 3, "three different words");
    assert.ok(words.every((w) => lib.PASSWORD_WORDS.includes(w)));
    seen.add(pw);
  }
  assert.ok(seen.size >= 195, "200 passwords are (nearly) all different");
  // with a fixed random source the output is predictable: words 0, 1, 2 (0 repeats, so it is skipped) and 7 padded
  const seq = [0, 0, 1, 2, 7];
  assert.strictEqual(lib.generatePassword(() => seq.shift()), `${lib.PASSWORD_WORDS[0]}-${lib.PASSWORD_WORDS[1]}-${lib.PASSWORD_WORDS[2]}-07`);
});

test("passwordProblem asks for 8+ characters in plain words", () => {
  assert.strictEqual(lib.passwordProblem("12345678"), "");
  assert.match(lib.passwordProblem("1234567"), /at least 8 characters/);
  assert.match(lib.passwordProblem(""), /Type a password/);
  assert.match(lib.passwordProblem(undefined), /Type a password/);
  assert.match(lib.passwordProblem("abcdefgh\nij"), /line breaks/);
  assert.match(lib.passwordProblem("x".repeat(201)), /too long/);
});

test("buildEngineEnv: phone on sets host, password, secret and local trust; off sets none of them", () => {
  const base = { PATH: "/usr/bin", HQ_HOST: "0.0.0.0", HQ_TRUST_PROXY: "1", HQ_PASSWORD: "stray", HQ_SECRET: "stray", HQ_LOCAL_TRUST: "1", KEEP: "yes" };
  const secret = "ab".repeat(32);
  const on = lib.buildEngineEnv(base, { port: 7333, claudeBin: "C:\\bin\\claude.exe", phone: { password: "maple-otter-lantern-42", secret } });
  assert.strictEqual(on.HQ_HOST, "0.0.0.0");
  assert.strictEqual(on.HQ_PASSWORD, "maple-otter-lantern-42");
  assert.strictEqual(on.HQ_SECRET, secret);
  assert.strictEqual(on.HQ_LOCAL_TRUST, "1");
  assert.ok(!("HQ_TRUST_PROXY" in on), "HQ_TRUST_PROXY is never set, even when the PC's own environment has it");
  assert.strictEqual(on.HQ_PORT, "7333");
  assert.strictEqual(on.CLAUDE_BIN, "C:\\bin\\claude.exe");
  assert.strictEqual(on.PYTHONIOENCODING, "utf-8");
  assert.strictEqual(on.PYTHONUNBUFFERED, "1");
  assert.strictEqual(on.KEEP, "yes");
  assert.strictEqual(on.PATH, "/usr/bin");

  const off = lib.buildEngineEnv(base, { port: 7331 });
  for (const k of ["HQ_HOST", "HQ_PASSWORD", "HQ_SECRET", "HQ_LOCAL_TRUST", "HQ_TRUST_PROXY"]) assert.ok(!(k in off), k + " is not set with phone access off");
  assert.strictEqual(off.HQ_PORT, "7331");
  assert.ok(!("CLAUDE_BIN" in off));
  assert.strictEqual(base.HQ_HOST, "0.0.0.0", "the base environment is not changed");

  const weak = lib.buildEngineEnv({}, { port: 7331, phone: { password: "short", secret } });
  assert.ok(!("HQ_HOST" in weak) && !("HQ_PASSWORD" in weak), "a password under 8 characters never opens the network");
  const noSecret = lib.buildEngineEnv({}, { port: 7331, phone: { password: "long enough", secret: "" } });
  assert.ok(!("HQ_HOST" in noSecret), "no secret, no phone access");
  assert.strictEqual(lib.buildEngineEnv({}, {}).HQ_PORT, "7331", "the default port");
});

test("redact hides the password and the secret in log lines", () => {
  const pw = "maple-otter-lantern-42", secret = "cd".repeat(32);
  assert.strictEqual(lib.redact(`login with ${pw} ok`, [pw, secret]), "login with ******** ok");
  assert.strictEqual(lib.redact(`${pw}${pw} and ${secret}`, [pw, secret]), "**************** and ********");
  assert.strictEqual(lib.redact("HQ_PASSWORD=hunter2hunter2 HQ_SECRET: abc", []), "HQ_PASSWORD=******** HQ_SECRET: ********");
  assert.strictEqual(lib.redact('set HQ_PASSWORD="two words"', []), "set HQ_PASSWORD=********");
  assert.strictEqual(lib.redact("nothing secret here", [pw, "", null, "ab"]), "nothing secret here", "empty and very short secrets are ignored");
  assert.strictEqual(lib.redact("a+b(c)?", ["+b(c)?"]), "a********", "regex characters in the password are literal");

  let current = { password: pw };
  const log = new lib.RingLog(10, { redact: (l) => lib.redact(l, [current.password]) });
  const seen = [];
  log.onLine((l) => seen.push(l));
  log.push("first half maple-otter-");
  log.push("lantern-42 second half\n");                 // split across chunks: the whole line is redacted
  assert.deepStrictEqual(log.lines(), ["first half ******** second half"]);
  assert.deepStrictEqual(seen, ["first half ******** second half"], "listeners (engine.log, the log panel) get the redacted line");
  current = { password: "brand-new-password-11" };
  log.push("now brand-new-password-11\n");
  assert.strictEqual(log.tail(1)[0], "now ********", "a changed password is redacted from then on");
  const broken = new lib.RingLog(3, { redact: () => { throw new Error("x"); } });
  broken.push("secret line\n");
  assert.deepStrictEqual(broken.lines(), ["********"], "a failing redactor hides the line instead of leaking it");
});

test("tailscaleState and checkTailscale read `tailscale ip -4`", async () => {
  assert.deepStrictEqual(lib.tailscaleState({ code: 0, stdout: "100.101.5.6\n" }), { state: "connected", ip: "100.101.5.6" });
  assert.deepStrictEqual(lib.tailscaleState({ code: 0, stdout: "\r\n100.70.1.2\r\n" }), { state: "connected", ip: "100.70.1.2" });
  assert.strictEqual(lib.tailscaleState({ code: 1, stdout: "", stderr: "Tailscale is stopped.\n" }).state, "signed-out");
  assert.strictEqual(lib.tailscaleState({ code: 1, stderr: "failed to connect to local tailscaled; dial unix /var/run/tailscale/tailscaled.sock: connect: no such file or directory" }).state, "signed-out", "installed, service not running");
  assert.strictEqual(lib.tailscaleState({ code: 0, stdout: "" }).state, "signed-out", "no address yet: not signed in");
  assert.strictEqual(lib.tailscaleState({ code: 1, stderr: "'tailscale' is not recognized as an internal or external command,\r\noperable program or batch file." }).state, "missing", "Windows cmd.exe");
  assert.strictEqual(lib.tailscaleState({ code: 127, stderr: "sh: 1: tailscale: not found" }).state, "missing", "POSIX sh");
  assert.strictEqual(lib.tailscaleState({ code: null, error: "spawn tailscale ENOENT" }).state, "missing");
  assert.strictEqual(lib.tailscaleState({ code: null, error: "timed out after 10 s", timedOut: true }).state, "signed-out", "a timeout means it is there but not answering");
  assert.strictEqual(lib.tailscaleState(null).state, "missing");

  const calls = [];
  const runner = (table) => async (cmd, args, opts) => { calls.push({ cmd, args, opts }); return table[cmd] || { code: 127, stderr: "sh: 1: " + cmd + ": not found" }; };
  assert.deepStrictEqual(await lib.checkTailscale({ run: runner({ tailscale: { code: 0, stdout: "100.64.1.1\n" } }) }), { state: "connected", ip: "100.64.1.1" });
  assert.deepStrictEqual(calls[0].args, ["ip", "-4"]);
  assert.strictEqual(calls[0].opts.timeoutMs, 10000, "the 10 s timeout of the tool checks");
  assert.strictEqual((await lib.checkTailscale({ run: runner({}), isWin: false })).state, "missing");
  // Windows, installed while the app was open: not on the PATH yet, found in Program Files
  const winTable = {}; winTable[lib.TAILSCALE_WIN_EXE] = { code: 0, stdout: "100.90.0.9\n" };
  assert.deepStrictEqual(await lib.checkTailscale({ run: runner(winTable), isWin: true, exists: (p) => p === lib.TAILSCALE_WIN_EXE }), { state: "connected", ip: "100.90.0.9" });
  assert.strictEqual((await lib.checkTailscale({ run: runner({}), isWin: true, exists: () => false })).state, "missing");
  const real = await lib.checkTailscale();
  console.log("      tailscale here: " + real.state + (real.ip ? " " + real.ip : ""));
});

test("tailscaleInstallLines run winget for tailscale.tailscale", () => {
  const lines = lib.tailscaleInstallLines();
  assert.ok(lines.some((l) => /^winget install -e --id tailscale\.tailscale\b/.test(l)));
  assert.ok(lines.every((l) => !/rm |Remove-Item|del /i.test(l)));
});

// ---------------------------------------------------------------- the secure link (tailscale serve)

// what the Tailscale CLI prints (shapes from 1.7x/1.8x on Windows and Linux)
const TS = {
  serveOk: "Available within your tailnet:\n\nhttps://desk-pc.tail1234.ts.net/\n|-- proxy http://127.0.0.1:7331\n\nServe started and running in the background.\nTo disable the proxy, run: tailscale serve --https=443 off\n",
  serveNotEnabled: "\nServe is not enabled on your tailnet.\nTo enable, visit:\n\n         https://login.tailscale.com/f/serve?node=nAbCdEf123CNTRL\n\n",
  httpsNotEnabled: "error: HTTPS is not enabled for your tailnet. To enable, visit: https://login.tailscale.com/f/https?node=n9xYz.\n",
  certsOld: "your Tailscale account does not support getting TLS certs; enable HTTPS in the admin console",
  magicDnsOff: "MagicDNS is disabled; enable it at https://login.tailscale.com/admin/dns to use serve\n",
  status: (dns, extra = {}) => JSON.stringify({ Version: "1.88.1", BackendState: "Running", Self: { DNSName: dns, HostName: "DESK-PC", TailscaleIPs: ["100.101.5.6"] }, CurrentTailnet: { Name: "john@example.com", MagicDNSSuffix: "tail1234.ts.net", MagicDNSEnabled: true }, CertDomains: ["desk-pc.tail1234.ts.net"], ...extra }, null, 2),
  serveJson: (proxy, extra = {}) => JSON.stringify({ TCP: { 443: { HTTPS: true } }, Web: { "desk-pc.tail1234.ts.net:443": { Handlers: { "/": { Proxy: proxy } } } }, ...extra }, null, 2),
};

test("secure link commands: serve on, off, status", () => {
  assert.deepStrictEqual(lib.serveOnArgs(7331), ["serve", "--bg", "--https=443", "http://127.0.0.1:7331"]);
  assert.deepStrictEqual(lib.serveOnArgs(7335), ["serve", "--bg", "--https=443", "http://127.0.0.1:7335"]);
  assert.deepStrictEqual(lib.serveOnArgs(7331, 8443), ["serve", "--bg", "--https=8443", "http://127.0.0.1:7331"]);
  assert.deepStrictEqual(lib.serveOnArgs(7331, 22), ["serve", "--bg", "--https=443", "http://127.0.0.1:7331"], "only 443, 8443 or 10000");
  assert.deepStrictEqual(lib.serveOnArgs("x"), ["serve", "--bg", "--https=443", "http://127.0.0.1:7331"], "a broken port falls back to 7331");
  assert.deepStrictEqual(lib.serveOffArgs(), ["serve", "--https=443", "off"]);
  assert.deepStrictEqual(lib.serveOffArgs(8443), ["serve", "--https=8443", "off"]);
  assert.strictEqual(lib.serveResetArgs, undefined, "no reset: it would remove other apps' links too");
  assert.deepStrictEqual(lib.serveStatusArgs(), ["serve", "status", "--json"]);
  assert.deepStrictEqual(lib.serveStatusArgs(false), ["serve", "status"]);
  assert.deepStrictEqual(lib.statusJsonArgs(), ["status", "--json"]);
  assert.ok(!lib.serveOnArgs(7331).some((a) => /funnel/i.test(a)), "never Funnel (the public internet)");
  assert.strictEqual(lib.cmdline("tailscale", lib.serveOnArgs(7331)), "tailscale serve --bg --https=443 http://127.0.0.1:7331", "nothing cmd.exe needs to quote");
  assert.strictEqual(lib.TAILSCALE_TIMEOUT_MS, 20000);
});

test("parseStatusJson: Self.DNSName with and without the trailing dot, MagicDNS, garbage", () => {
  assert.strictEqual(lib.parseStatusJson(TS.status("desk-pc.tail1234.ts.net.")).dnsName, "desk-pc.tail1234.ts.net", "trailing dot stripped");
  assert.strictEqual(lib.parseStatusJson(TS.status("desk-pc.tail1234.ts.net")).dnsName, "desk-pc.tail1234.ts.net", "no trailing dot");
  assert.strictEqual(lib.parseStatusJson(TS.status("DESK-PC.Tail1234.ts.net.")).dnsName, "desk-pc.tail1234.ts.net", "lower case");
  const full = lib.parseStatusJson("Warning: client version \"1.86.0\" != tailscaled server version \"1.88.1\"\n" + TS.status("desk-pc.tail1234.ts.net."));
  assert.deepStrictEqual(full, { dnsName: "desk-pc.tail1234.ts.net", magicDns: true, certDomains: ["desk-pc.tail1234.ts.net"], backend: "Running" }, "a warning line before the JSON is skipped");
  assert.strictEqual(lib.parseStatusJson(TS.status("desk-pc.tail1234.ts.net.", { CurrentTailnet: { MagicDNSEnabled: false } })).magicDns, false);
  assert.strictEqual(lib.parseStatusJson(TS.status("")).dnsName, "", "signed out: no name");
  assert.strictEqual(lib.parseStatusJson(TS.status("evil.ts.net/<script>")).dnsName, "", "only plain host names");
  for (const bad of ["", "not json", "[1,2]", "{ broken", null, undefined]) assert.deepStrictEqual(lib.parseStatusJson(bad), { dnsName: "", magicDns: null, certDomains: [], backend: "" }, String(bad));
  assert.strictEqual(lib.secureUrl("desk-pc.tail1234.ts.net."), "https://desk-pc.tail1234.ts.net/");
  assert.strictEqual(lib.secureUrl("desk-pc.tail1234.ts.net.", 443), "https://desk-pc.tail1234.ts.net/");
  assert.strictEqual(lib.secureUrl("desk-pc.tail1234.ts.net.", 8443), "https://desk-pc.tail1234.ts.net:8443/");
  assert.strictEqual(lib.secureUrl(""), "");
});

test("isSecureUrl (the QR whitelist) and isTailscaleAdminLink (the browser button)", () => {
  for (const u of ["https://desk-pc.tail1234.ts.net/", "https://desk-pc.tail1234.ts.net", "https://a.b.ts.net/", "https://x.ts.net:8443/", "https://x.ts.net:10000"]) assert.strictEqual(lib.isSecureUrl(u), true, u);
  for (const u of ["http://desk-pc.tail1234.ts.net/", "https://desk-pc.tail1234.ts.net/x", "https://evil.com/.ts.net/", "https://ts.net/", "https://x.ts.net.evil.com/", "javascript:alert(1)", "", null, "https://x.ts.net:8444/", "https://x.ts.net:8443.evil.com/"]) assert.strictEqual(lib.isSecureUrl(u), false, String(u));
  assert.strictEqual(lib.isTailscaleAdminLink("https://login.tailscale.com/f/serve?node=nAbC123"), true);
  assert.strictEqual(lib.isTailscaleAdminLink("https://login.tailscale.com/admin/dns"), true);
  for (const u of ["http://login.tailscale.com/admin", "https://login.tailscale.com.evil.com/", "https://evil.com/login.tailscale.com/", "https://login.tailscale.com", "file:///c:/x", "https://login.tailscale.com/a b", 7, null]) assert.strictEqual(lib.isTailscaleAdminLink(u), false, String(u));
});

test("parseServeStatus: JSON and plain text, our port or another, nothing configured, Funnel", () => {
  const on = lib.parseServeStatus(TS.serveJson("http://127.0.0.1:7331"), 7331);
  assert.deepStrictEqual(on, { on: true, httpsPort: 443, proxy: "http://127.0.0.1:7331", host: "desk-pc.tail1234.ts.net", funnel: false,
    links: [{ httpsPort: 443, host: "desk-pc.tail1234.ts.net", proxy: "http://127.0.0.1:7331", funnel: false }] });
  assert.strictEqual(lib.parseServeStatus(TS.serveJson("http://127.0.0.1:7331"), 7332).on, false, "443 relays to another port");
  assert.strictEqual(lib.parseServeStatus(TS.serveJson("http://localhost:7333"), 7333).on, true, "localhost counts");
  assert.strictEqual(lib.parseServeStatus(TS.serveJson("7334"), 7334).on, true, "a bare port counts");
  assert.strictEqual(lib.parseServeStatus(TS.serveJson("http://192.168.1.5:7331"), 7331).on, false, "another machine does not count");
  assert.strictEqual(lib.parseServeStatus(TS.serveJson("http://127.0.0.1:7331", { AllowFunnel: { "desk-pc.tail1234.ts.net:443": true } }), 7331).funnel, true);
  const other = JSON.stringify({ Web: { "desk-pc.tail1234.ts.net:8443": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } });
  assert.deepStrictEqual([lib.parseServeStatus(other, 7331).on, lib.parseServeStatus(other, 7331).httpsPort], [true, 8443], "a link on 8443 counts");
  const fg = JSON.stringify({ Foreground: { abc: { Web: { "desk-pc.tail1234.ts.net:443": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } } } });
  assert.strictEqual(lib.parseServeStatus(fg, 7331).on, true, "a foreground serve counts too");
  for (const none of ["{}", "", "No serve config\n", "not json at all"]) assert.deepStrictEqual(lib.parseServeStatus(none, 7331), { on: false, httpsPort: 0, proxy: "", host: "", funnel: false, links: [] }, JSON.stringify(none));
  const plain = "\nhttps://desk-pc.tail1234.ts.net (tailnet only)\n|-- / proxy http://127.0.0.1:7331\n\n";
  assert.deepStrictEqual(lib.parseServeStatus(plain, 7331), { on: true, httpsPort: 443, proxy: "http://127.0.0.1:7331", host: "desk-pc.tail1234.ts.net", funnel: false,
    links: [{ httpsPort: 443, host: "desk-pc.tail1234.ts.net", proxy: "http://127.0.0.1:7331", funnel: false }] }, "plain text");
  assert.strictEqual(lib.parseServeStatus("https://desk-pc.tail1234.ts.net (Funnel on)\n|-- / proxy http://127.0.0.1:7331\n", 7331).funnel, true);
  assert.strictEqual(lib.parseServeStatus("https://desk-pc.tail1234.ts.net:8443 (tailnet only)\n|-- / proxy http://127.0.0.1:7331\n", 7331).httpsPort, 8443, "plain text: 8443");
  assert.strictEqual(lib.parseServeStatus("http://desk-pc.tail1234.ts.net:80 (tailnet only)\n|-- / proxy http://127.0.0.1:7331\n", 7331).on, false, "plain text: an http serve is not the secure link");
  const httpOnly = JSON.stringify({ TCP: { 80: { HTTP: true } }, Web: { "desk-pc.tail1234.ts.net:80": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } });
  assert.strictEqual(lib.parseServeStatus(httpOnly, 7331).on, false, "JSON: an http serve is not the secure link");
  // this computer: AI OFFICE on 443, the office on 8443
  const shared = JSON.stringify({ TCP: { 443: { HTTPS: true }, 8443: { HTTPS: true } }, Web: {
    "desk-pc.tail1234.ts.net:443": { Handlers: { "/": { Proxy: "http://127.0.0.1:4320" } } },
    "desk-pc.tail1234.ts.net:8443": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } });
  const s = lib.parseServeStatus(shared, 7331);
  assert.deepStrictEqual([s.on, s.httpsPort, s.proxy, s.links.length], [true, 8443, "http://127.0.0.1:7331", 2]);
  const notOurs = lib.parseServeStatus(shared, 7332);
  assert.deepStrictEqual([notOurs.on, notOurs.httpsPort, notOurs.proxy], [false, 0, "http://127.0.0.1:4320"], "not ours: what 443 relays to");
  assert.strictEqual(lib.secureHttpsPort(s.links, 7331), 8443, "the link we have");
  assert.strictEqual(lib.secureHttpsPort(lib.parseServeStatus(TS.serveJson("http://127.0.0.1:4320"), 7331).links, 7331), 8443, "443 taken: the next free port");
  assert.strictEqual(lib.secureHttpsPort(notOurs.links, 7332), 10000, "443 and 8443 taken");
  assert.strictEqual(lib.secureHttpsPort([], 7331), 443);
  assert.strictEqual(lib.secureHttpsPort([443, 8443, 10000].map((p) => ({ httpsPort: p, proxy: "http://127.0.0.1:1" })), 7331), 0, "all taken");
  assert.strictEqual(lib.proxyPort("http://127.0.0.1:7331/"), 7331);
  assert.strictEqual(lib.proxyPort("https+insecure://127.0.0.1:7331"), 0);
});

test("serveProblem: HTTPS / Serve not enabled gives the admin link, MagicDNS off, and the other failures", () => {
  assert.strictEqual(lib.serveProblem({ code: 0, stdout: TS.serveOk }), null, "success");
  const waited = lib.serveProblem({ code: null, timedOut: true, error: "timed out after 20 s", stdout: TS.serveNotEnabled });
  assert.deepStrictEqual(waited, { kind: "https-off", link: "https://login.tailscale.com/f/serve?node=nAbCdEf123CNTRL", message: "Turn on HTTPS certificates in your Tailscale admin, then press Turn on again." }, "the CLI waits for the owner: the timeout still gives the link");
  const exited = lib.serveProblem({ code: 1, stdout: "", stderr: TS.serveNotEnabled });
  assert.strictEqual(exited.kind, "https-off");
  assert.strictEqual(exited.link, "https://login.tailscale.com/f/serve?node=nAbCdEf123CNTRL");
  const https = lib.serveProblem({ code: 1, stderr: TS.httpsNotEnabled });
  assert.strictEqual(https.kind, "https-off");
  assert.strictEqual(https.link, "https://login.tailscale.com/f/https?node=n9xYz", "a trailing full stop is not part of the link");
  const old = lib.serveProblem({ code: 1, stderr: TS.certsOld });
  assert.deepStrictEqual([old.kind, old.link], ["https-off", "https://login.tailscale.com/admin/dns"], "no link printed: the DNS page of the admin");
  const mdns = lib.serveProblem({ code: 1, stderr: TS.magicDnsOff });
  assert.deepStrictEqual([mdns.kind, mdns.link], ["magicdns-off", "https://login.tailscale.com/admin/dns"]);
  assert.match(mdns.message, /MagicDNS/);
  assert.strictEqual(lib.serveProblem({ code: 1, stderr: "Access denied: serve config denied\n\nUse 'sudo tailscale serve ...'" }).kind, "access-denied");
  assert.strictEqual(lib.serveProblem({ code: 2, stderr: "flag provided but not defined: -bg\nUSAGE\n  serve <target>" }).kind, "old-version");
  assert.strictEqual(lib.serveProblem({ code: 1, stderr: "failed to connect to local tailscaled; it doesn't appear to be running" }).kind, "not-running");
  assert.strictEqual(lib.serveProblem({ code: 1, stderr: "Tailscale is stopped." }).kind, "not-running");
  assert.strictEqual(lib.serveProblem({ code: 9009, stderr: "'tailscale' is not recognized as an internal or external command,\r\noperable program or batch file." }).kind, "missing");
  assert.strictEqual(lib.serveProblem({ code: null, error: "spawn tailscale ENOENT" }).kind, "missing");
  assert.strictEqual(lib.serveProblem({ code: null, timedOut: true, error: "timed out after 20 s" }).kind, "timeout");
  const other = lib.serveProblem({ code: 1, stderr: "something new went wrong\nsecond line" });
  assert.deepStrictEqual([other.kind, other.message], ["failed", "Tailscale answered: something new went wrong"]);
  assert.strictEqual(lib.serveProblem(null).kind, "missing");
});

/** A fake tailscale runner: answers by the arguments (a list: one answer per call, the last one repeats), records every call. */
function fakeTailscale(answers) {
  const calls = [];
  const runner = async (cmd, args, opts) => {
    calls.push({ cmd, args: args.join(" "), timeoutMs: opts && opts.timeoutMs });
    let a = answers[args.join(" ")];
    if (Array.isArray(a)) a = a.length > 1 ? a.shift() : a[0];
    const r = typeof a === "function" ? a(cmd) : a || { code: 1, stderr: "unexpected: " + args.join(" ") };
    return { line: lib.cmdline(cmd, args), code: r.code === undefined ? 0 : r.code, stdout: r.stdout || "", stderr: r.stderr || "", error: r.error || null, timedOut: !!r.timedOut };
  };
  return { runner, calls };
}

test("enableSecureLink: on, then the https address from tailscale status", async () => {
  const { runner, calls } = fakeTailscale({
    "serve --bg --https=443 http://127.0.0.1:7332": { stdout: TS.serveOk.replace("7331", "7332") },
    "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") },
    "serve status --json": [{ stdout: "{}" }, { stdout: TS.serveJson("http://127.0.0.1:7332") }],
  });
  const r = await lib.enableSecureLink(7332, { run: runner, isWin: false });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.url, "https://desk-pc.tail1234.ts.net/");
  assert.strictEqual(r.httpsPort, 443);
  assert.strictEqual(r.verified, true);
  assert.strictEqual(r.funnel, false);
  assert.deepStrictEqual(calls.map((c) => c.args), ["serve status --json", "serve --bg --https=443 http://127.0.0.1:7332", "status --json", "serve status --json"], "first what is served already");
  assert.ok(calls.every((c) => c.timeoutMs === 20000), "20 s for every tailscale command");
  assert.strictEqual(r.steps.length, 4);
  assert.strictEqual(r.steps[1].line, "tailscale serve --bg --https=443 http://127.0.0.1:7332");
  assert.ok(r.steps[1].output.includes("https://desk-pc.tail1234.ts.net/"), "the log gets what tailscale printed");
});

test("enableSecureLink: another app on 443 keeps it, the office gets 8443; a link we have stays; all ports taken", async () => {
  const theirs = TS.serveJson("http://127.0.0.1:4320");
  const both = JSON.stringify({ TCP: { 443: { HTTPS: true }, 8443: { HTTPS: true } }, Web: {
    "desk-pc.tail1234.ts.net:443": { Handlers: { "/": { Proxy: "http://127.0.0.1:4320" } } },
    "desk-pc.tail1234.ts.net:8443": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } });
  const t = fakeTailscale({
    "serve status --json": [{ stdout: theirs }, { stdout: both }],
    "serve --bg --https=8443 http://127.0.0.1:7331": { stdout: "Available within your tailnet:\n\nhttps://desk-pc.tail1234.ts.net:8443/\n|-- proxy http://127.0.0.1:7331\n" },
    "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") },
  });
  const r = await lib.enableSecureLink(7331, { run: t.runner, isWin: false });
  assert.deepStrictEqual([r.ok, r.url, r.httpsPort, r.verified], [true, "https://desk-pc.tail1234.ts.net:8443/", 8443, true]);
  assert.ok(!t.calls.some((c) => /--https=443/.test(c.args)), "443 (the other app's link) is never touched");

  const have = fakeTailscale({ "serve status --json": { stdout: both }, "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") } });
  const kept = await lib.enableSecureLink(7331, { run: have.runner, isWin: false });
  assert.deepStrictEqual([kept.ok, kept.url, kept.verified], [true, "https://desk-pc.tail1234.ts.net:8443/", true]);
  assert.deepStrictEqual(have.calls.map((c) => c.args), ["serve status --json", "status --json"], "already on: nothing changes");

  const info = await lib.secureLinkInfo(7331, { run: fakeTailscale({ "serve status --json": { stdout: both }, "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") } }).runner, isWin: false });
  assert.deepStrictEqual([info.on, info.httpsPort, info.url], [true, 8443, "https://desk-pc.tail1234.ts.net:8443/"], "Phone access shows the 8443 link");
  const would = await lib.secureLinkInfo(7331, { run: fakeTailscale({ "serve status --json": { stdout: theirs }, "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") } }).runner, isWin: false });
  assert.deepStrictEqual([would.on, would.url, would.proxy], [false, "https://desk-pc.tail1234.ts.net:8443/", "http://127.0.0.1:4320"], "off: the address it would get");

  const full = JSON.stringify({ Web: Object.fromEntries([443, 8443, 10000].map((p) => [`desk-pc.tail1234.ts.net:${p}`, { Handlers: { "/": { Proxy: "http://127.0.0.1:4320" } } }])) });
  const none = fakeTailscale({ "serve status --json": { stdout: full } });
  const no = await lib.enableSecureLink(7331, { run: none.runner, isWin: false });
  assert.deepStrictEqual([no.ok, no.problem.kind], [false, "ports-taken"]);
  assert.deepStrictEqual(none.calls.map((c) => c.args), ["serve status --json"], "nothing is changed");
});

test("enableSecureLink: HTTPS not enabled gives the admin link and does not read further", async () => {
  const { runner, calls } = fakeTailscale({ "serve status --json": { stdout: "{}" }, "serve --bg --https=443 http://127.0.0.1:7331": { code: null, timedOut: true, error: "timed out after 20 s", stdout: TS.serveNotEnabled } });
  const r = await lib.enableSecureLink(7331, { run: runner, isWin: false });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.problem.kind, "https-off");
  assert.strictEqual(r.problem.link, "https://login.tailscale.com/f/serve?node=nAbCdEf123CNTRL");
  assert.strictEqual(calls.length, 2);
  assert.strictEqual(r.steps[1].timedOut, true);
});

test("enableSecureLink and secureLinkInfo: MagicDNS off, signed out, Windows Program Files fallback, a runner that throws", async () => {
  const mdns = fakeTailscale({
    "serve status --json": { stdout: "{}" },
    "serve --bg --https=443 http://127.0.0.1:7331": { stdout: TS.serveOk },
    "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.", { CurrentTailnet: { MagicDNSEnabled: false } }) },
  });
  const r1 = await lib.enableSecureLink(7331, { run: mdns.runner, isWin: false });
  assert.strictEqual(r1.ok, false);
  assert.strictEqual(r1.problem.kind, "magicdns-off");

  const out = fakeTailscale({ "status --json": { stdout: JSON.stringify({ BackendState: "NeedsLogin", Self: { DNSName: "" } }) } });
  const info = await lib.secureLinkInfo(7331, { run: out.runner, isWin: false });
  assert.strictEqual(info.ok, false);
  assert.strictEqual(info.problem.kind, "not-running");

  // Windows: tailscale is not on the PATH of the app yet; the one in Program Files answers
  const calls = [];
  const winRun = async (cmd, args) => {
    calls.push(cmd);
    if (cmd === "tailscale") return { line: "tailscale", code: 1, stdout: "", stderr: "'tailscale' is not recognized as an internal or external command,\r\noperable program or batch file.", error: null };
    const key = args.join(" ");
    const out = key === "status --json" ? TS.status("desk-pc.tail1234.ts.net.") : key === "serve status --json" ? TS.serveJson("http://127.0.0.1:7331") : "";
    return { line: lib.cmdline(cmd, args), code: 0, stdout: out, stderr: "", error: null };
  };
  const w = await lib.secureLinkInfo(7331, { run: winRun, isWin: true, exists: (p) => p === lib.TAILSCALE_WIN_EXE });
  assert.deepStrictEqual([w.ok, w.on, w.url], [true, true, "https://desk-pc.tail1234.ts.net/"]);
  assert.deepStrictEqual(calls, ["tailscale", lib.TAILSCALE_WIN_EXE, "tailscale", lib.TAILSCALE_WIN_EXE]);
  assert.ok(w.steps[0].line.startsWith('"C:\\Program Files\\Tailscale\\tailscale.exe" status'), "the log shows the quoted Program Files path");

  const off = await lib.secureLinkInfo(7331, { run: fakeTailscale({ "status --json": { stdout: TS.status("desk-pc.tail1234.ts.net.") }, "serve status --json": { stdout: "{}" } }).runner, isWin: false });
  assert.deepStrictEqual([off.ok, off.on, off.url, off.problem], [true, false, "https://desk-pc.tail1234.ts.net/", null], "off, with the address it would have");

  const thrown = await lib.enableSecureLink(7331, { run: async () => { throw new Error("boom"); }, isWin: false });
  assert.strictEqual(thrown.ok, false, "never throws");
  assert.ok(thrown.problem);
});

test("readServeStatus falls back to plain `tailscale serve status` on versions without --json", async () => {
  const { runner, calls } = fakeTailscale({
    "serve status --json": { code: 2, stderr: "flag provided but not defined: -json" },
    "serve status": { stdout: "https://desk-pc.tail1234.ts.net (tailnet only)\n|-- / proxy http://127.0.0.1:7331\n" },
  });
  const s = await lib.readServeStatus(7331, { run: runner, isWin: false });
  assert.strictEqual(s.on, true);
  assert.deepStrictEqual(calls.map((c) => c.args), ["serve status --json", "serve status"]);
});

test("disableSecureLink: only links to our engine go, never another app's, never a reset", async () => {
  const ok = fakeTailscale({ "serve status --json": { stdout: TS.serveJson("http://127.0.0.1:7331") }, "serve --https=443 off": { stdout: "" } });
  assert.strictEqual((await lib.disableSecureLink(7331, { run: ok.runner, isWin: false })).ok, true);
  assert.deepStrictEqual(ok.calls.map((c) => c.args), ["serve status --json", "serve --https=443 off"]);

  const shared = JSON.stringify({ Web: {
    "desk-pc.tail1234.ts.net:443": { Handlers: { "/": { Proxy: "http://127.0.0.1:4320" } } },
    "desk-pc.tail1234.ts.net:8443": { Handlers: { "/": { Proxy: "http://127.0.0.1:7331" } } } } });
  const mine = fakeTailscale({ "serve status --json": { stdout: shared }, "serve --https=8443 off": { stdout: "" } });
  assert.strictEqual((await lib.disableSecureLink(7331, { run: mine.runner, isWin: false })).ok, true);
  assert.deepStrictEqual(mine.calls.map((c) => c.args), ["serve status --json", "serve --https=8443 off"], "AI OFFICE's 443 stays");

  const theirs = fakeTailscale({ "serve status --json": { stdout: TS.serveJson("http://127.0.0.1:4320") } });
  assert.strictEqual((await lib.disableSecureLink(7331, { run: theirs.runner, isWin: false })).ok, true, "nothing of ours: fine");
  assert.deepStrictEqual(theirs.calls.map((c) => c.args), ["serve status --json"], "the other app's link is not turned off");

  const moved = fakeTailscale({ "serve status --json": { stdout: TS.serveJson("http://127.0.0.1:7335") }, "serve --https=443 off": { stdout: "" } });
  await lib.disableSecureLink([7331, 7335], { run: moved.runner, isWin: false });
  assert.deepStrictEqual(moved.calls.map((c) => c.args), ["serve status --json", "serve --https=443 off"], "the engine's old port counts too");

  const gone = fakeTailscale({ "serve status --json": { stdout: TS.serveJson("http://127.0.0.1:7331") }, "serve --https=443 off": { code: 1, stderr: "error: port 443 is not being served" } });
  assert.strictEqual((await lib.disableSecureLink(7331, { run: gone.runner, isWin: false })).ok, true, "nothing to turn off is fine");

  const down = { "serve status --json": { code: 1, stderr: "failed to connect to local tailscaled" }, "serve --https=8443 off": { code: 1, stderr: "failed to connect to local tailscaled" } };
  const known = fakeTailscale(down);
  const r2 = await lib.disableSecureLink(7331, { run: known.runner, isWin: false, httpsPort: 8443 });
  assert.deepStrictEqual([r2.ok, r2.problem.kind], [false, "not-running"]);
  assert.deepStrictEqual(known.calls.map((c) => c.args), ["serve status --json", "serve --https=8443 off"], "status unreadable: only the port this app turned on");
  const blind = fakeTailscale(down);
  const r3 = await lib.disableSecureLink(7331, { run: blind.runner, isWin: false });
  assert.strictEqual(r3.ok, false);
  assert.deepStrictEqual(blind.calls.map((c) => c.args), ["serve status --json"], "status unreadable and no known port: nothing is guessed");

  const missing = fakeTailscale({ "serve status --json": { code: 127, stderr: "sh: 1: tailscale: not found" } });
  assert.strictEqual((await lib.disableSecureLink(7331, { run: missing.runner, isWin: false })).ok, true, "no Tailscale: nothing is relayed");
});

test("the secure link helpers against a real process (a fake tailscale on the PATH)", async () => {
  if (lib.IS_WIN) { console.log("      (skipped on Windows: the fake is a shell script)"); return; }
  const dir = tmpdir();
  const state = path.join(dir, "serve.json");
  const script = path.join(dir, "tailscale");
  fs.writeFileSync(script, [
    "#!/bin/sh",
    'echo "$*" >> "$TS_FAKE_DIR/calls.log"',
    'case "$TS_FAKE_MODE:$*" in',
    `  ok:"serve --bg --https=443 "*) printf '{"TCP":{"443":{"HTTPS":true}},"Web":{"desk-pc.tail1234.ts.net:443":{"Handlers":{"/":{"Proxy":"%s"}}}}}' "$4" > "$TS_FAKE_DIR/serve.json"; printf 'Available within your tailnet:\\n\\nhttps://desk-pc.tail1234.ts.net/\\n|-- proxy %s\\n\\nServe started and running in the background.\\n' "$4" ;;`,
    `  off:"serve --bg"*) printf '\\nServe is not enabled on your tailnet.\\nTo enable, visit:\\n\\n         https://login.tailscale.com/f/serve?node=nFAKE42\\n\\n'; sleep 8 ;;`,
    '  *:"serve status --json") cat "$TS_FAKE_DIR/serve.json" 2>/dev/null || echo "{}" ;;',
    '  *:"serve --https=443 off") mv "$TS_FAKE_DIR/serve.json" "$TS_FAKE_DIR/serve.json.was" 2>/dev/null; true ;;',
    `  *:"status --json") printf '{"BackendState":"Running","Self":{"DNSName":"desk-pc.tail1234.ts.net."},"CurrentTailnet":{"MagicDNSEnabled":true}}' ;;`,
    '  *) echo "unexpected $*" >&2; exit 1 ;;',
    "esac",
  ].join("\n") + "\n");
  fs.chmodSync(script, 0o755);
  const saved = { PATH: process.env.PATH, mode: process.env.TS_FAKE_MODE, dir: process.env.TS_FAKE_DIR };
  process.env.PATH = dir + path.delimiter + process.env.PATH;
  process.env.TS_FAKE_DIR = dir;
  try {
    process.env.TS_FAKE_MODE = "ok";
    const on = await lib.enableSecureLink(7339);
    assert.deepStrictEqual([on.ok, on.url, on.verified], [true, "https://desk-pc.tail1234.ts.net/", true]);
    assert.ok(fs.existsSync(state));
    const info = await lib.secureLinkInfo(7339);
    assert.deepStrictEqual([info.on, info.proxy], [true, "http://127.0.0.1:7339"]);
    assert.strictEqual((await lib.secureLinkInfo(7331)).on, false, "relays to 7339, not 7331");
    const off = await lib.disableSecureLink(7339);
    assert.strictEqual(off.ok, true);
    assert.ok(!fs.existsSync(state));
    assert.strictEqual((await lib.secureLinkInfo(7339)).on, false);

    process.env.TS_FAKE_MODE = "off";                  // HTTPS not enabled: the CLI prints the link and waits
    const t0 = Date.now();
    const blocked = await lib.enableSecureLink(7339, { timeoutMs: 1500 });
    assert.ok(Date.now() - t0 < 6000, "the time limit ends the wait");
    assert.deepStrictEqual([blocked.ok, blocked.problem.kind, blocked.problem.link], [false, "https-off", "https://login.tailscale.com/f/serve?node=nFAKE42"]);
    const log = fs.readFileSync(path.join(dir, "calls.log"), "utf8").trim().split("\n");
    assert.deepStrictEqual(log, ["serve status --json", "serve --bg --https=443 http://127.0.0.1:7339", "status --json", "serve status --json", "status --json", "serve status --json",
      "status --json", "serve status --json", "serve status --json", "serve --https=443 off", "status --json", "serve status --json",
      "serve status --json", "serve --bg --https=443 http://127.0.0.1:7339"]);
  } finally {
    process.env.PATH = saved.PATH;
    if (saved.mode === undefined) delete process.env.TS_FAKE_MODE; else process.env.TS_FAKE_MODE = saved.mode;
    if (saved.dir === undefined) delete process.env.TS_FAKE_DIR; else process.env.TS_FAKE_DIR = saved.dir;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------- misc

test("constants", () => {
  assert.strictEqual(lib.DEFAULT_PORT, 7331);
  assert.strictEqual(lib.LAST_PORT, 7340);
  assert.strictEqual(lib.REPO_URL, "https://github.com/johnooi5593-hue/Agents-HQ");
  assert.deepStrictEqual(lib.PYTHON_CANDIDATES, [["py", "-3"], ["python"], ["python3"]]);
  assert.strictEqual(lib.pythonLabel(["py", "-3"]), "py -3");
});

test("refreshPath is a no-op off Windows, resolveClaude never throws", async () => {
  if (!lib.IS_WIN) assert.strictEqual(await lib.refreshPath({}), null);
  const r = await lib.resolveClaude(process.env);
  assert.ok(r && ("bin" in r) && ("kind" in r));
  console.log("      claude executable: " + (r.bin || "not found") + (r.kind ? " (" + r.kind + ")" : ""));
  assert.strictEqual(await lib.shortPath("/x") , lib.IS_WIN ? await lib.shortPath("/x") : null);
});

// ---------------------------------------------------------------- run them

(async () => {
  let failed = 0;
  for (const t of tests) {
    try {
      await t.fn();
      console.log("  ok    " + t.name);
    } catch (e) {
      failed++;
      console.log("  FAIL  " + t.name + "\n        " + String(e && e.stack || e).split("\n").join("\n        "));
    }
  }
  console.log(`\n${tests.length - failed}/${tests.length} passed` + (failed ? `, ${failed} failed` : ""));
  process.exit(failed ? 1 : 0);
})();
