"use strict";
/* main.js: the Electron main process of Agents HQ.
 *
 * What happens when the app opens:
 *   1. check the five tools (git, node, python, ffmpeg, claude)               -> setup.html shows the checklist
 *   2. make sure the office folder exists (Documents\Agents HQ, or <home>\Agents HQ when OneDrive syncs Documents):
 *      git clone into "<folder>.download" and rename it when done, or the copy bundled with the app
 *   3. the first time, run `python setup.py` there (numpy, pillow, faster-whisper, the folders)
 *   4. start the engine: `python hq/server.py --no-browser` with HQ_PORT, log to userData/engine.log
 *   5. when http://127.0.0.1:<port>/api/status answers, show the office in the same window
 * If the engine stops, the window goes back to setup.html with the last log lines and a Restart button.
 * Closing the window on Windows hides it to the tray; Quit is in the tray menu and in File.
 *
 * Phone access (phone.html, from the tray, File > Phone access... and the setup screen): when it is on, the engine
 * listens on every network (HQ_HOST=0.0.0.0) and asks for a password (HQ_PASSWORD) from every device except this
 * computer itself (HQ_LOCAL_TRUST=1). The password and the cookie secret (HQ_SECRET, so phones stay logged in across
 * restarts) are kept in settings.json, encrypted with Electron's safeStorage when the system offers it.
 *
 * Secure link (phone.html, "Secure link (https)"): `tailscale serve --bg --https=443 http://127.0.0.1:<port>` gives the
 * office an https://<computer>.<tailnet>.ts.net/ address inside the owner's tailnet, so the iPhone shows no warning and the
 * microphone works. When another app (AI OFFICE) already serves 443, the office uses https://...ts.net:8443/ (or :10000)
 * and leaves that app's link alone: only links that relay to our engine are ever turned off. Tailscale relays it from 127.0.0.1, and hq/server.py makes every relayed request log in with the
 * phone password even with HQ_LOCAL_TRUST=1. The link only stays on while our engine runs with the password: it is turned
 * off before an engine without phone access starts, when phone access is turned off and when the app quits, and turned on
 * again (on the new port, if it changed) whenever the engine comes up with phone access and settings.secureLink is true.
 *
 * Build: copy the office into desktop/bundle (the GitHub workflow .github/workflows/windows-app.yml does this with
 * robocopy: the repository without .git, desktop, out, done, approved and the inbox contents), then `npm run dist:win`.
 */
const { app, BrowserWindow, Menu, Tray, ipcMain, shell, session, nativeImage, safeStorage, clipboard } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");
const { spawn } = require("child_process");
const lib = require("./lib");

const APP_ID = "com.agentshq.desktop";
const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const ASSETS = path.join(__dirname, "assets");
const SETUP_PAGE = path.join(__dirname, "setup.html");
const PHONE_PAGE = path.join(__dirname, "phone.html");
const LOG_MAX_BYTES = 5 * 1024 * 1024;

app.setAppUserModelId(APP_ID);

// one instance: a second launch brings the window up instead
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
  app.whenReady().then(start);
}

// ---------------------------------------------------------------- state shared with setup.html

let settingsFile, logFile, settings;
let win = null, tray = null, phoneWin = null;
let child = null;             // the engine process
let externalEngine = false;   // an engine we did not start answers on the port
let expectedExit = false;     // we stopped the engine ourselves
let pythonCmd = null;         // e.g. ["py", "-3"], the python that passed the check
let claudeBin;                // resolved once: the claude executable for CLAUDE_BIN, or null
let booting = false;
let quitting = false;
let hiddenByUser = false;     // the user closed the window to the tray; it does not pop up again by itself
let logStream = null;
let phone = { password: "", secret: "" };   // decrypted phone password and cookie secret, in memory only
let enginePhone = false;                     // the running engine was started with phone access on
// the secure link (tailscale serve): applied = https port `httpsPort` relays to `port` as far as we know; maybe = it may still be on from earlier
const secure = { applied: false, maybe: false, port: 0, httpsPort: 0, url: "", busy: false, problem: null, funnel: false, checked: false };
// every log line (the setup screen, engine.log) has the phone password and the secret blanked out
const log = new lib.RingLog(500, { redact: (line) => lib.redact(line, [phone.password, phone.secret]) });

const state = {
  phase: "checking",          // checking | missing | cloning | setup | starting | ready | stopped | updating | error
  message: "",
  tools: [], allOk: false, requiredOk: false, python: "",
  officeDir: "", port: lib.DEFAULT_PORT, url: "",
  engine: "stopped",          // stopped | starting | running
  setupDone: false, canOpen: false, busy: false, signedIn: null,
  platform: process.platform, logFile: "", phoneAccess: false, phoneActive: false,
};

function publicState() {
  return { ...state, busy: booting, canOpen: state.engine === "running" && state.requiredOk, phoneAccess: !!(settings && settings.phoneAccess), phoneActive: enginePhone && state.engine === "running" };
}

function setState(patch) {
  Object.assign(state, patch);
  if (win && !win.isDestroyed()) win.webContents.send("hq:state", publicState());
  if (phoneWin && !phoneWin.isDestroyed()) phoneWin.webContents.send("phone:state", phoneState());
}

function say(line) {
  log.push("[app] " + line + "\n");
}

function saveSettings() {
  try { lib.saveSettings(settingsFile, settings); } catch (e) { say("Could not save settings: " + e.message); }
}

// ---------------------------------------------------------------- start

async function start() {
  const userData = app.getPath("userData");
  settingsFile = path.join(userData, "settings.json");
  logFile = path.join(userData, "engine.log");
  settings = lib.loadSettings(settingsFile, { officeDir: defaultOfficeDir(), port: lib.DEFAULT_PORT, setupDone: false });
  if (typeof settings.officeDir !== "string" || !settings.officeDir) settings.officeDir = defaultOfficeDir();
  if (!Number.isInteger(settings.port) || settings.port < 1 || settings.port > 65535) settings.port = lib.DEFAULT_PORT;
  Object.assign(state, { officeDir: settings.officeDir, port: settings.port, setupDone: !!settings.setupDone, logFile, office: lib.officeSummary(settings.officeDir) });

  // the log: every line to the setup screen and to engine.log
  openLogStream();
  log.onLine((line) => {
    if (win && !win.isDestroyed()) win.webContents.send("hq:log", line);
    if (logStream) logStream.write(line + "\n");
  });
  say(`Agents HQ desktop ${app.getVersion()} on ${process.platform}; settings in ${userData}; office folder ${settings.officeDir}`);
  loadPhone();
  if (settings.phoneAccess) say("Phone access is on: phones on your network can open the office with the phone password.");
  if (typeof settings.secureLink !== "boolean") settings.secureLink = false;
  secure.maybe = settings.secureLink;          // Tailscale keeps a --bg serve across restarts: it may still be on

  // the office page may use the microphone (voice command); nothing else is granted
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback) => callback(permission === "media"));
  session.defaultSession.setPermissionCheckHandler((wc, permission) => permission === "media");

  registerIpc();
  buildMenu();
  createWindow();
  createTray();
  boot();
}

/** Documents\Agents HQ, or <home>\Agents HQ when OneDrive syncs Documents: a git repository, the brain file and raw clips do not belong in a synced folder. */
function defaultOfficeDir() {
  return path.join(lib.officeBase(app.getPath("documents"), app.getPath("home")), "Agents HQ");
}

function openLogStream() {
  try {
    fs.mkdirSync(path.dirname(logFile), { recursive: true });
    if (fs.existsSync(logFile) && fs.statSync(logFile).size > LOG_MAX_BYTES) fs.renameSync(logFile, logFile + ".old");
    logStream = fs.createWriteStream(logFile, { flags: "a" });
    logStream.on("error", () => { logStream = null; });
    logStream.write(`\n==== ${new Date().toISOString()} ====\n`);
  } catch (_) {
    logStream = null;
  }
}

// ---------------------------------------------------------------- the boot sequence

async function boot() {
  if (booting) return;
  booting = true;
  setState({ busy: true });
  try {
    const checked = await checkTools();
    if (!checked.requiredOk) {
      setState({ phase: "missing", message: 'Some tools are missing. Press "Install missing tools", let the installs finish, then press "Check again".' });
      return;
    }
    if (!(await ensureOffice())) return;
    if (!settings.setupDone) await runSetup();
    await startEngine();
  } catch (e) {
    say("Unexpected problem: " + (e && e.stack || e));
    setState({ phase: "error", message: "Something went wrong: " + (e && e.message || e) + '. Press "Check again"; if it keeps happening, open the engine log.' });
  } finally {
    booting = false;
    setState({ busy: false });
  }
}

/** Run the five checks and remember the python command. */
async function checkTools() {
  setState({ phase: state.engine === "running" ? state.phase : "checking", message: "Checking the tools Agents HQ needs..." });
  if (IS_WIN) await lib.refreshPath(process.env);     // tools installed while the app is open
  const res = await lib.checkAll();
  pythonCmd = res.python;
  claudeBin = undefined;                              // resolve again with the fresh PATH
  for (const t of res.tools) say(`${t.label}: ${t.ok ? "ok, " + t.version : "missing. " + t.detail}`);
  setState({ tools: res.tools, allOk: res.allOk, requiredOk: res.requiredOk, python: lib.pythonLabel(res.python || ""), signedIn: lib.claudeSignedIn(app.getPath("home")) });
  return res;
}

/**
 * The office folder: already there, or git clone, or the copy that ships with the app. The download goes into
 * "<folder>.download" and is renamed when it is complete, so an interrupted first run never leaves a half office
 * behind under the real name; whatever is in the way is moved aside, never deleted.
 */
async function ensureOffice() {
  const dir = settings.officeDir;
  if (isOffice(dir)) return true;
  setState({ phase: "cloning", message: "First run: setting up your office folder. This takes a minute." });
  try { fs.mkdirSync(path.dirname(dir), { recursive: true }); } catch (_) { /* the clone or copy reports it */ }
  const tmp = dir + ".download";
  const stuck = `The office could not be created in ${dir}. Install Git (press "Install missing tools"), check your internet connection, then press "Check again".`;
  if (!clearWay(dir) || !clearWay(tmp)) { setState({ phase: "error", message: stuck }); return false; }
  const git = state.tools.find((t) => t.name === "git");
  let ok = false;
  if (git && git.ok && !lib.PRIVATE_EDITION) {             // a client edition's repo is private: start from the copy in the app
    say(`Downloading Agents HQ into ${dir} ...`);
    const code = await stream("git", ["clone", lib.REPO_URL, tmp], { cwd: path.dirname(dir) });
    ok = code === 0 && isOffice(tmp);
    if (!ok) { say("The download did not finish; using the copy that came with the app instead."); clearWay(tmp); }
  }
  if (!ok) ok = copyBundle(tmp);
  if (ok) {
    try { fs.renameSync(tmp, dir); } catch (e) { say(`Could not move ${tmp} to ${dir}: ${e.message}`); ok = false; }
  }
  if (!ok) { setState({ phase: "error", message: stuck }); return false; }
  say(`The office is in ${dir}.`);
  setState({ office: lib.officeSummary(dir) });
  return true;
}

/** "Your office" on the setup screen: the office's name, and for a client edition the access code its updates use. */
function setOffice(req) {
  req = req && typeof req === "object" ? req : {};
  const dir = settings.officeDir;
  if (!isOffice(dir)) return { ok: false, message: "Wait until the office folder is set up, then save again." };
  const patch = {};
  if (typeof req.name === "string") patch.name = lib.cleanOfficeName(req.name);
  if (typeof req.access === "string" && req.access.trim()) {
    if (!lib.accessCodeOk(req.access)) return { ok: false, message: "That access code is not complete. Copy the whole code (it starts with HQ1.) and paste it again." };
    patch.access = req.access.replace(/\s+/g, "");
  }
  try { lib.writeOffice(dir, patch); }
  catch (e) { return { ok: false, message: "Could not save: " + e.message }; }
  setState({ office: lib.officeSummary(dir) });
  say("Office settings saved" + (patch.name !== undefined ? `: name "${patch.name || "Agents HQ"}"` : "") + (patch.access ? ", access code saved" : "") + ".");
  return { ok: true, message: "Saved." + (patch.name !== undefined ? " The office shows its name the next time you open or reload it." : "") + (patch.access ? " Updates use the access code from the next check." : "") };
}

function isOffice(dir) {
  return fs.existsSync(path.join(dir, "hq", "server.py"));
}

/** Make sure nothing is at `dir`: an empty folder is removed, anything else is renamed "<dir> (incomplete <date>)". Never deletes. */
function clearWay(dir) {
  if (!fs.existsSync(dir)) return true;
  try {
    if (fs.statSync(dir).isDirectory() && fs.readdirSync(dir).length === 0) { fs.rmdirSync(dir); return true; }
    const stamp = new Date().toISOString().slice(0, 10);
    let aside = `${dir} (incomplete ${stamp})`;
    for (let n = 2; fs.existsSync(aside); n++) aside = `${dir} (incomplete ${stamp} ${n})`;
    fs.renameSync(dir, aside);
    say(`${dir} was not a finished office; it was moved to ${aside} (nothing is deleted).`);
    return true;
  } catch (e) {
    say(`Could not move ${dir} out of the way: ${e.message}`);
    return false;
  }
}

/** Where a copy of the office ships: resources/office in the installed app, desktop/bundle, and in a dev run the checkout itself. */
function bundleDir() {
  const candidates = [];
  if (process.resourcesPath) candidates.push(path.join(process.resourcesPath, "office"));
  candidates.push(path.join(__dirname, "bundle"));
  if (!app.isPackaged) candidates.reverse();
  if (!app.isPackaged) candidates.push(path.join(__dirname, ".."));
  return candidates.find((d) => isOffice(d)) || null;
}

function copyBundle(dir) {
  const src = bundleDir();
  if (!src) { say("The app has no bundled office to copy."); return false; }
  say(`Copying the office that came with the app from ${src} to ${dir} ...`);
  const never = new Set([".git", "node_modules", "__pycache__"]);                 // not part of an office at any depth
  const notFromTop = new Set(["desktop"]);                                         // the app itself, when the source is the checkout
  const filter = (p) => !never.has(path.basename(p)) && !(path.dirname(p) === src && notFromTop.has(path.basename(p)));
  try {
    fs.cpSync(src, dir, { recursive: true, force: false, errorOnExist: false, filter });
  } catch (e) {
    say("The copy failed: " + e.message);
    return false;
  }
  return isOffice(dir);
}

/** `python setup.py` once in the office folder. */
async function runSetup() {
  setState({ phase: "setup", message: "First run: installing the Python packages the office needs (numpy, pillow, faster-whisper). This can take a few minutes." });
  const code = await stream(pythonCmd[0], [...pythonCmd.slice(1), "setup.py"], { cwd: settings.officeDir, env: await engineEnv() });
  if (code === 0) {
    settings.setupDone = true;
    saveSettings();
    setState({ setupDone: true });
    say("Setup finished.");
  } else {
    say(`setup.py ended with code ${code}. The engine starts anyway; setup runs again next time. Captions and covers may not work until it finishes.`);
  }
}

/** Spawn a command directly (git, python: real executables), stream its output to the log, resolve its exit code. */
function stream(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    say(`> ${cmd} ${args.join(" ")}`);
    let p;
    try {
      p = spawn(cmd, args, { cwd: opts.cwd, env: opts.env || process.env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    } catch (e) {
      say(`${cmd} could not start: ${e.message}`);
      return resolve(-1);
    }
    p.stdout.on("data", (d) => log.push(d));
    p.stderr.on("data", (d) => log.push(d));
    p.on("error", (e) => { say(`${cmd} could not start: ${e.message}`); resolve(-1); });
    p.on("close", (code) => { log.flush(); resolve(code == null ? -1 : code); });
  });
}

// ---------------------------------------------------------------- the engine

/** The environment for python: HQ_PORT, CLAUDE_BIN and, for the engine with `opts.phone`, the phone access settings when they are on. */
async function engineEnv(opts = {}) {
  if (claudeBin === undefined) claudeBin = await resolveClaudeBin();
  return lib.buildEngineEnv(process.env, { port: settings.port, claudeBin, phone: opts.phone && phoneOn() ? phone : null });
}

/** The claude executable the engine should start, or null to leave it to the PATH. */
async function resolveClaudeBin() {
  try {
    const r = await lib.resolveClaude(process.env);
    if (!r.bin) return null;
    if (r.kind === "exe" || !/\s/.test(r.bin)) return r.bin;
    // the npm shim claude.cmd in a folder with a space: Windows cannot start it that way; the short 8.3 path has no spaces
    const short = await lib.shortPath(r.bin);
    if (short && !/\s/.test(short)) return short;        // no 8.3 names on this volume: the long path would break in cmd.exe
    say(`Claude Code was found at ${r.bin}. The space in that path can stop the engine from starting it. If messages to the chief of staff fail, install the native version in PowerShell:  irm https://claude.ai/install.ps1 | iex`);
    return null;
  } catch (e) {
    say("Could not look up the claude executable: " + e.message);
    return null;
  }
}

async function startEngine() {
  if (child) return;
  if (!pythonCmd) { setState({ phase: "missing", message: 'Python 3.10 or newer was not found. Press "Install missing tools", then "Check again".' }); return; }
  setState({ phase: "starting", engine: "starting", message: "Starting the office engine..." });

  // an engine from an earlier launch (or from "Open Agents HQ.bat") may already answer on the remembered port
  if (await lib.isAgentsHq(settings.port)) {
    say(`An Agents HQ engine already answers on port ${settings.port}; using it.`);
    if (phoneOn()) say("That engine was not started by this app, so phone access is not active. Close the window where it runs, then press Restart.");
    externalEngine = true;
    enginePhone = false;
    // that engine may have no phone password: the secure link must not relay to it
    if (secureMaybeOn()) await secureTask(() => removeSecure("the engine running now was not started by this app"));
    engineUp(settings.port);
    return;
  }
  externalEngine = false;
  // with phone access the engine listens on every network, so the port must be free there too
  const port = await lib.findPort(settings.port, phoneOn() ? "0.0.0.0" : "127.0.0.1");
  if (!port) {
    setState({ phase: "error", engine: "stopped", message: 'Ports 7331 to 7340 are all busy. Close the programs that use them, then press "Check again".' });
    return;
  }
  if (port !== settings.port) { settings.port = port; saveSettings(); say(`Port ${state.port} is busy, using ${port}.`); }
  setState({ port });

  const env = await engineEnv({ phone: true });
  const withPhone = env.HQ_HOST === "0.0.0.0";
  // the secure link relays to 127.0.0.1:<port>: off before an engine without the password starts, or on another port
  if (secureMaybeOn() && !(withPhone && secure.applied && secure.port === port)) {
    await secureTask(() => removeSecure(withPhone ? `the engine moves to port ${port}; it is turned on again when the engine is up` : "the engine starts without phone access"));
  }
  const args = [...pythonCmd.slice(1), "hq/server.py", "--no-browser"];
  say(`Engine: ${pythonCmd[0]} ${args.join(" ")}   (port ${port}, folder ${settings.officeDir}${env.CLAUDE_BIN ? ", claude " + env.CLAUDE_BIN : ""}` +
    (withPhone ? ", phone access on: every network, password required except on this computer" : "") + ")");
  expectedExit = false;
  let me;
  try {
    me = spawn(pythonCmd[0], args, { cwd: settings.officeDir, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  } catch (e) {
    setState({ phase: "error", engine: "stopped", message: "The engine could not start: " + e.message + '. Press "Check again".' });
    return;
  }
  child = me;
  enginePhone = withPhone;
  me.stdout.on("data", (d) => log.push(d));
  me.stderr.on("data", (d) => log.push(d));
  me.on("error", (e) => say("The engine could not start: " + e.message));
  me.on("close", (code, signal) => onEngineExit(me, code, signal));

  const url = `http://127.0.0.1:${port}`;
  const gone = () => child !== me;
  let up = await lib.waitForHttp(url + "/api/status", { timeoutMs: 60000, intervalMs: 500, shouldStop: gone });
  if (gone()) return;                      // it exited meanwhile; onEngineExit showed why
  if (!up) {
    say("The engine has not answered after 60 seconds; still waiting (the first start can be slow while it checks for updates).");
    up = await lib.waitForHttp(url + "/api/status", { timeoutMs: 120000, intervalMs: 2000, shouldStop: gone });
    if (gone()) return;
  }
  if (!up) {
    setState({ phase: "error", message: `The engine is running but does not answer on port ${port}. Open the engine log to see why, then press Restart.` });
    return;
  }
  engineUp(port);
}

const SIGN_IN_HINT = 'Press "Sign in to Claude Code", finish in the terminal, then press "Open Agents HQ".';

function engineUp(port) {
  setState({ engine: "running", phase: "ready", port, url: `http://127.0.0.1:${port}`, message: "Agents HQ is running.", signedIn: lib.claudeSignedIn(app.getPath("home")) });
  updateTray();
  syncSecure("the engine is up on port " + port);
  // straight to the office when every tool is there, the first-run setup finished and Claude Code is signed in; otherwise the setup screen stays
  if (state.allOk && settings.setupDone && state.signedIn) { showOffice(); return; }
  if (state.allOk && settings.setupDone) {
    setState({ message: "Agents HQ is running, but Claude Code is not signed in yet. " + SIGN_IN_HINT });
    say("The office is up, but Claude Code is not signed in yet. " + SIGN_IN_HINT);
  } else {
    say('The office is up. Press "Open Agents HQ" to use it' + (state.allOk ? "." : "; the tools marked red are still worth installing."));
  }
}

function onEngineExit(me, code, signal) {
  if (child !== me) return;
  child = null;
  enginePhone = false;
  log.flush();
  if (expectedExit || quitting) { setState({ engine: "stopped" }); updateTray(); return; }
  const why = code != null ? `code ${code}` : `signal ${signal}`;
  say(`The engine stopped (${why}).`);
  setState({ phase: "stopped", engine: "stopped", message: `The engine stopped (${why}). The last lines of its log are below. Press Restart to start it again.` });
  showSetup();
  updateTray();
}

/** Stop the engine we started; resolves when it is gone (or after 5 s). */
function stopEngine() {
  return new Promise((resolve) => {
    const me = child;
    if (!me) return resolve();
    expectedExit = true;
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    me.once("close", finish);
    setTimeout(finish, 5000);
    if (IS_WIN) spawn("taskkill", ["/pid", String(me.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" }).on("error", () => { try { me.kill(); } catch (_) { /* gone */ } });
    else { try { me.kill(); } catch (_) { /* gone */ } }
  });
}

/** Stop and start the engine again. `opts.focus: false` leaves the window where it is (the phone access window stays in front). */
async function restartEngine(opts = {}) {
  if (booting) return;
  if (opts.focus !== false) showWindow();
  showSetup();
  if (externalEngine && !child) {
    say("The running engine was not started by this app, so it cannot be restarted from here. Close the window where it runs, then press Restart.");
    setState({ message: "The running engine was not started by this app. Close the window where it runs, then press Restart." });
    return;
  }
  booting = true;
  setState({ busy: true });
  try {
    await stopEngine();
    await startEngine();
  } finally {
    booting = false;
    setState({ busy: false });
  }
}

/** Tray: restart the engine; on start it updates the office folder from GitHub (and links a copied folder to GitHub). */
async function checkForUpdates() {
  if (booting) return;
  showWindow();
  showSetup();
  booting = true;
  setState({ busy: true, phase: "updating", message: "Checking GitHub for a newer Agents HQ..." });
  try {
    if (child) await stopEngine();
    await startEngine();
    say("Update check finished: the version and the result are in the app under your name (top right).");
  } finally {
    booting = false;
    setState({ busy: false });
  }
}

// ---------------------------------------------------------------- the window

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1024, minHeight: 680,
    title: "Agents HQ",
    backgroundColor: "#0b0f1a",
    icon: path.join(ASSETS, "icon.png"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.once("ready-to-show", () => win.show());
  win.on("page-title-updated", (e) => e.preventDefault());
  win.webContents.on("did-finish-load", () => { if (win) win.webContents.send("hq:state", publicState()); });
  // links out of the office open in the system browser
  win.webContents.setWindowOpenHandler(({ url }) => { openOutside(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => { if (!isLocal(url)) { e.preventDefault(); openOutside(url); } });
  win.webContents.on("did-fail-load", (e, code, desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3 || !/^http:/.test(url || "")) return;     // -3: the navigation was replaced, not an error
    say(`The office page did not load (${desc}).`);
    if (externalEngine && !child) {                                           // the engine we found running is gone
      externalEngine = false;
      setState({ phase: "stopped", engine: "stopped", message: "The engine is not answering any more. Press Restart to start it again." });
    } else {
      setState({ message: `The office page did not load (${desc}). Press Restart.` });
    }
    showSetup();
    updateTray();
  });
  win.on("close", (e) => {
    if (IS_WIN && !quitting) { e.preventDefault(); win.hide(); hiddenByUser = true; trayHint(); }   // to the tray; Quit is in the tray menu
  });
  win.on("closed", () => { win = null; });
  win.loadFile(SETUP_PAGE);
}

function isLocal(url) {
  try {
    const u = new URL(url);
    return u.protocol === "file:" || (u.protocol === "http:" && (u.hostname === "127.0.0.1" || u.hostname === "localhost"));
  } catch (_) {
    return false;
  }
}

function openOutside(url) {
  if (/^https?:\/\//i.test(url)) shell.openExternal(url);
}

function showWindow() {
  hiddenByUser = false;
  if (!win) { createWindow(); if (state.engine === "running" && state.requiredOk) showOffice(); return; }
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function showSetup() {
  if (!win) return;
  const current = win.webContents.getURL();
  if (!current.startsWith("file:")) win.loadFile(SETUP_PAGE);
}

function showOffice() {
  if (!win || !state.url || state.engine !== "running") return;
  const target = state.url + "/";
  if (win.webContents.getURL() !== target) win.loadURL(target);
  if (!win.isVisible() && !hiddenByUser) win.show();
}

// ---------------------------------------------------------------- the tray and the menu

function createTray() {
  try {
    // Windows draws .ico best in the tray; elsewhere a small PNG
    tray = IS_WIN ? new Tray(path.join(ASSETS, "icon.ico")) : new Tray(nativeImage.createFromPath(path.join(ASSETS, "icon.png")).resize({ width: 18, height: 18 }));
    tray.setToolTip("Agents HQ");
    tray.on("click", () => showWindow());
    updateTray();
  } catch (e) {
    say("No tray icon: " + e.message);
  }
}

/** Windows, the first time the window goes to the tray: say so (Windows 11 hides new tray icons in the overflow). */
function trayHint() {
  if (!tray || settings.trayHintShown) return;
  settings.trayHintShown = true;
  saveSettings();
  try {
    tray.displayBalloon({ title: "Agents HQ keeps running", content: "The office is still open in the tray. Right-click the icon and choose Quit to stop it.", iconType: "info" });
  } catch (e) {
    say("No tray notice: " + e.message);
  }
}

function updateTray() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open Agents HQ", click: () => { showWindow(); if (state.engine === "running" && state.requiredOk) showOffice(); } },
    { label: "Setup screen", click: () => { showWindow(); showSetup(); } },
    { label: "Open office folder", click: openFolder },
    { label: "Open engine log", click: openLog },
    { label: "Phone access…", click: openPhoneWindow },
    { type: "separator" },
    { label: "Restart engine", click: () => restartEngine() },
    { label: "Check for updates", click: () => checkForUpdates() },
    { type: "separator" },
    { label: `Engine: ${state.engine}${state.engine === "running" ? " on port " + state.port : ""}`, enabled: false },
    { label: `Phone access: ${enginePhone && state.engine === "running" ? "on" : settings && settings.phoneAccess ? "on, starts with the engine" : "off"}`, enabled: false },
    { label: "Quit", click: () => quit() },
  ]));
}

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(IS_MAC ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        { label: "Setup screen", click: () => { showWindow(); showSetup(); } },
        { label: "Open office folder", click: openFolder },
        { label: "Open engine log", click: openLog },
        { label: "Phone access…", click: openPhoneWindow },
        { type: "separator" },
        { label: "Quit", accelerator: IS_MAC ? "Cmd+Q" : "Ctrl+Q", click: () => quit() },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "zoomIn" }, { role: "zoomOut" }, { role: "resetZoom" },
      ],
    },
    {
      label: "Help",
      submenu: [{ label: "Open README on GitHub", click: () => shell.openExternal(lib.REPO_URL) }],
    },
  ]));
}

function openFolder() {
  try { fs.mkdirSync(settings.officeDir, { recursive: true }); } catch (_) { /* openPath reports it */ }
  return shell.openPath(settings.officeDir);
}

function openLog() {
  try { if (!fs.existsSync(logFile)) fs.writeFileSync(logFile, ""); } catch (_) { /* openPath reports it */ }
  return shell.openPath(logFile);
}

// ---------------------------------------------------------------- the buttons of setup.html

/** "Install missing tools": a visible PowerShell window running the winget commands and the Claude Code installer. */
function installMissing() {
  const missing = state.tools.filter((t) => !t.ok);
  if (!missing.length) return { ok: true, message: "Everything is installed." };
  if (!IS_WIN) {
    say("Install these yourself, then press Check again: " + missing.map((t) => t.label).join(", "));
    return { ok: false, message: "On this system, install " + missing.map((t) => t.label).join(", ") + " yourself, then press Check again." };
  }
  say("Opening PowerShell to install: " + missing.map((t) => t.label).join(", "));
  const err = openPowerShell("Agents HQ: installing tools", "install-tools.ps1", lib.installLines(state.tools));
  if (err) return { ok: false, message: "PowerShell could not be opened: " + err };
  return { ok: true, message: "A PowerShell window is installing the tools. Approve the Windows prompts, wait until it says Done, then press Check again." };
}

/**
 * Windows: write the lines to userData/<file> and run them in a visible PowerShell window titled `title`.
 * The script is started through `cmd /c start`, which gives PowerShell its own console (a detached child of a GUI
 * app has none, so it would run invisibly). Returns null, or the error message.
 */
function openPowerShell(title, file, lines) {
  try {
    const script = path.join(app.getPath("userData"), file);
    fs.writeFileSync(script, lines.join("\r\n") + "\r\n", "utf8");
    say(`PowerShell: ${script}`);
    const p = spawn("cmd.exe", ["/c", "start", title, "powershell.exe", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", script],
      { detached: true, stdio: "ignore", windowsHide: true });
    p.on("error", (e) => say("PowerShell could not be opened: " + e.message));
    p.unref();
    return null;
  } catch (e) {
    return e.message;
  }
}

/** "Sign in to Claude Code": a terminal running `claude` in the office folder. */
function signIn() {
  const dir = settings.officeDir;
  try { fs.mkdirSync(dir, { recursive: true }); } catch (_) { /* the terminal reports it */ }
  try {
    if (IS_WIN) {
      const p = spawn("cmd.exe", ["/c", "start", "", "cmd", "/k", "claude"], { cwd: dir, detached: true, stdio: "ignore" });
      p.on("error", (e) => say("The terminal could not be opened: " + e.message));
      p.unref();
    } else if (IS_MAC) {
      const scpt = `tell application "Terminal"\n activate\n do script "cd " & quoted form of "${dir.replace(/"/g, '\\"')}" & " && claude"\nend tell`;
      spawn("osascript", ["-e", scpt], { detached: true, stdio: "ignore" }).unref();
    } else {
      const inner = `cd "${dir.replace(/"/g, '\\"')}" && claude; exec bash`;
      const term = ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm"].find((t) => fs.existsSync("/usr/bin/" + t));
      if (!term) return { ok: false, message: `Open a terminal in ${dir} and run: claude` };
      const args = term === "gnome-terminal" ? ["--", "bash", "-lc", inner] : ["-e", "bash -lc '" + inner.replace(/'/g, "'\\''") + "'"];
      spawn(term, args, { cwd: dir, detached: true, stdio: "ignore" }).unref();
    }
    say("Opened a terminal running claude in " + dir);
    return { ok: true, message: "A terminal opened. Sign in there if it asks (type /login), accept the folder trust question, allow the memory server, then close it." };
  } catch (e) {
    return { ok: false, message: "The terminal could not be opened: " + e.message + `. Open one yourself in ${dir} and run: claude` };
  }
}

/** "Open Agents HQ" / "Restart": show the office when the engine is up, else start it. */
function startOrOpen() {
  if (state.engine === "running" && state.requiredOk) { showOffice(); return publicState(); }
  if (booting) return publicState();
  // an engine that is alive but not answering gets killed and started again; otherwise the whole boot runs
  if (child || (state.requiredOk && pythonCmd)) restartEngine(); else boot();
  return publicState();
}

function registerIpc() {
  ipcMain.handle("hq:getState", () => ({ ...publicState(), log: log.tail(300) }));
  ipcMain.handle("hq:check", async () => {
    if (booting) return publicState();
    if (state.engine === "running") {
      const res = await checkTools();
      const message = !res.allOk ? "Agents HQ is running; the tools marked red are still missing."
        : state.signedIn ? "Agents HQ is running." : "Agents HQ is running, but Claude Code is not signed in yet. " + SIGN_IN_HINT;
      setState({ phase: "ready", message });
      if (res.allOk && state.signedIn) showOffice();
    } else {
      boot();
    }
    return publicState();
  });
  ipcMain.handle("hq:installMissing", () => installMissing());
  ipcMain.handle("hq:signIn", () => signIn());
  ipcMain.handle("hq:officeSet", (_e, req) => setOffice(req));
  ipcMain.handle("hq:openFolder", async () => ({ ok: !(await openFolder()) }));
  ipcMain.handle("hq:openLog", async () => ({ ok: !(await openLog()) }));
  ipcMain.handle("hq:start", () => startOrOpen());
  ipcMain.handle("hq:openPhone", () => { openPhoneWindow(); return { ok: true, message: "" }; });

  // phone access: only the app's own pages (file://) may call these; the office page in the window is http://
  const fromApp = (fn) => async (e, ...args) => {
    if (!fromAppPage(e)) return { ok: false, message: "Only the Agents HQ app window can change phone access." };
    return fn(...args);
  };
  ipcMain.handle("phone:get", fromApp(() => phoneState()));
  ipcMain.handle("phone:set", fromApp((req) => setPhone(req)));
  ipcMain.handle("phone:qr", fromApp((url) => phoneQr(url)));
  ipcMain.handle("phone:tailscale", fromApp(() => tailscaleInfo()));
  ipcMain.handle("phone:install-tailscale", fromApp(() => installTailscale()));
  ipcMain.handle("phone:generate", fromApp(() => ({ ok: true, password: lib.generatePassword() })));
  ipcMain.handle("phone:secure-get", fromApp(() => secureGet()));
  ipcMain.handle("phone:secure-on", fromApp(() => secureOn()));
  ipcMain.handle("phone:secure-off", fromApp(() => secureOff()));
  ipcMain.handle("phone:open-link", fromApp((url) => openAdminLink(url)));
  ipcMain.handle("phone:copy", fromApp((text) => {
    if (typeof text !== "string" || !text || text.length > 500) return { ok: false, message: "Nothing to copy." };
    clipboard.writeText(text);
    return { ok: true, message: "Copied." };
  }));
}

function fromAppPage(e) {
  try { return new URL(e.senderFrame.url).protocol === "file:"; } catch (_) { return false; }
}

// ---------------------------------------------------------------- phone access

/** safeStorage that really encrypts: on Linux without a keyring Electron falls back to a fixed key ("basic_text"), which is not encryption. */
function canEncrypt() {
  try {
    if (!safeStorage.isEncryptionAvailable()) return false;
    if (process.platform === "linux" && typeof safeStorage.getSelectedStorageBackend === "function" && safeStorage.getSelectedStorageBackend() === "basic_text") return false;
    return true;
  } catch (_) {
    return false;
  }
}

function readSecret(encKey, plainKey) {
  const enc = settings[encKey];
  if (typeof enc === "string" && enc) {
    try {
      if (safeStorage.isEncryptionAvailable()) return safeStorage.decryptString(Buffer.from(enc, "base64"));
    } catch (e) {
      say(`The saved ${plainKey === "phonePassword" ? "phone password" : "phone login key"} could not be decrypted (${e.message}).`);
    }
    return "";
  }
  return typeof settings[plainKey] === "string" ? settings[plainKey] : "";
}

function writeSecret(encKey, plainKey, value, encrypt) {
  delete settings[encKey];
  delete settings[plainKey];
  if (!value) return;
  if (encrypt) settings[encKey] = safeStorage.encryptString(value).toString("base64");
  else settings[plainKey] = value;
}

/** Save the phone password and the cookie secret: encrypted when the system can, else as plain text with a note saying so. */
function savePhone() {
  let encrypt = canEncrypt();
  try {
    writeSecret("phonePasswordEncrypted", "phonePassword", phone.password, encrypt);
    writeSecret("phoneSecretEncrypted", "phoneSecret", phone.secret, encrypt);
  } catch (e) {
    say("Could not encrypt the phone password (" + e.message + "); it is saved as plain text in settings.json.");
    encrypt = false;
    writeSecret("phonePasswordEncrypted", "phonePassword", phone.password, false);
    writeSecret("phoneSecretEncrypted", "phoneSecret", phone.secret, false);
  }
  if (encrypt) delete settings.phoneStorageNote;
  else settings.phoneStorageNote = "phonePassword and phoneSecret are stored as plain text: this system offers no encryption to Electron's safeStorage. Anyone who can read this file can log in to your office from a phone.";
  saveSettings();
}

/** At start: read the phone settings, make the cookie secret once, and keep phone access off without a usable password. */
function loadPhone() {
  if (typeof settings.phoneAccess !== "boolean") settings.phoneAccess = false;
  phone.password = readSecret("phonePasswordEncrypted", "phonePassword");
  phone.secret = readSecret("phoneSecretEncrypted", "phoneSecret");
  let changed = false;
  if (!/^[0-9a-f]{64}$/.test(phone.secret)) { phone.secret = crypto.randomBytes(32).toString("hex"); changed = true; }
  if (settings.phoneAccess && lib.passwordProblem(phone.password)) {
    settings.phoneAccess = false;
    changed = true;
    say("Phone access was turned off because no usable phone password is saved. Open File > Phone access to set one and turn it on again.");
  }
  // a secret or password saved as plain text earlier is encrypted as soon as the system can
  if (changed || (canEncrypt() && (settings.phonePassword || settings.phoneSecret))) savePhone();
}

function phoneOn() {
  return !!settings.phoneAccess && !lib.passwordProblem(phone.password) && !!phone.secret;
}

/** What phone.html shows. The password goes only to the app's own pages (see fromAppPage). */
function phoneState() {
  const on = !!(settings && settings.phoneAccess);
  const active = enginePhone && state.engine === "running";
  return {
    on, active,
    engine: state.engine, busy: booting, external: externalEngine && !child,
    port: state.port,
    password: phone.password, minLength: lib.PHONE_MIN_PASSWORD,
    addresses: on ? lib.phoneAddresses(os.networkInterfaces(), state.port) : [],
    encrypted: !settings.phonePassword && !settings.phoneSecret,
    platform: process.platform,
    secure: secureState(),
  };
}

function openPhoneWindow() {
  if (phoneWin && !phoneWin.isDestroyed()) {
    if (phoneWin.isMinimized()) phoneWin.restore();
    phoneWin.show();
    phoneWin.focus();
    return;
  }
  phoneWin = new BrowserWindow({
    width: 900, height: 900, minWidth: 560, minHeight: 600,
    title: "Agents HQ: Phone access",
    backgroundColor: "#0b0f1a",
    icon: path.join(ASSETS, "icon.png"),
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  phoneWin.removeMenu();
  phoneWin.once("ready-to-show", () => phoneWin && phoneWin.show());
  phoneWin.on("page-title-updated", (e) => e.preventDefault());
  phoneWin.webContents.setWindowOpenHandler(({ url }) => { openOutside(url); return { action: "deny" }; });
  phoneWin.webContents.on("will-navigate", (e, url) => { e.preventDefault(); openOutside(url); });
  phoneWin.on("closed", () => { phoneWin = null; });
  phoneWin.loadFile(PHONE_PAGE);
}

/**
 * phone.html's switch and password: { on, password }. Turning on needs a password of 8+ characters; turning off always
 * works. A new password also makes a new cookie secret, so every phone logged in with the old one has to log in again.
 * When the engine runs, it is restarted with the new settings and the window reloads the office.
 */
let phoneChanging = false;

async function setPhone(req) {
  if (phoneChanging) return { ok: false, message: "Phone access is already changing. Wait a moment, then try again.", ...phoneState() };
  phoneChanging = true;
  try {
    return await applyPhone(req);
  } finally {
    phoneChanging = false;
  }
}

async function applyPhone(req) {
  req = req && typeof req === "object" ? req : {};
  const wantOn = req.on === true;
  const typed = typeof req.password === "string" ? req.password : null;
  if (wantOn) {
    const problem = lib.passwordProblem(typed != null ? typed : phone.password);
    if (problem) return { ok: false, message: problem, ...phoneState() };
  }
  const pwChanged = typed != null && !lib.passwordProblem(typed) && typed !== phone.password;
  const hadPassword = !!phone.password;
  if (pwChanged) {
    phone.password = typed;
    if (hadPassword) phone.secret = crypto.randomBytes(32).toString("hex");
  }
  const flipped = wantOn !== !!settings.phoneAccess;
  settings.phoneAccess = wantOn;
  savePhone();
  // without phone access the engine has no password: the secure link goes first (settings.secureLink stays, so it comes back with phone access)
  if (!wantOn && secureMaybeOn()) await secureTask(() => removeSecure("phone access turned off"));
  if (flipped) say(wantOn ? "Phone access turned on." : "Phone access turned off: only this computer can open the office.");
  else if (pwChanged) say("The phone password was changed; every phone has to log in again.");
  updateTray();

  const needRestart = wantOn !== enginePhone || (wantOn && pwChanged);
  if (!needRestart) return { ok: true, message: pwChanged ? "The new password is saved." : wantOn ? "Phone access is on." : "Phone access is off.", ...phoneState() };

  // the engine is starting right now: wait for that to finish, then restart it with the new settings
  for (let i = 0; booting && i < 1200; i++) await new Promise((r) => setTimeout(r, 500));
  if (externalEngine && !child) {
    return { ok: false, message: "The engine running now was not started by this app, so it cannot pick up phone access. Close the window where it runs, then press Restart on the setup screen.", ...phoneState() };
  }
  if (!child) {
    return { ok: true, message: (wantOn ? "Phone access is saved and starts with the engine." : "Phone access is off.") + " The engine is not running; press Restart on the setup screen to start it.", ...phoneState() };
  }
  await restartEngine({ focus: false });
  if (phoneWin && !phoneWin.isDestroyed()) phoneWin.focus();
  if (state.engine !== "running") {
    return { ok: false, message: "The engine did not start again. Open the setup screen to see why in the log, then press Restart.", ...phoneState() };
  }
  if (enginePhone !== wantOn) {
    return { ok: false, message: "The engine restarted, but phone access did not change. Press Restart engine in the tray menu and try again.", ...phoneState() };
  }
  const message = !wantOn ? "Phone access is off. Only this computer can open the office now."
    : pwChanged && hadPassword ? "The new password is active. Every phone has to log in again with it."
    : "Phone access is on. On your phone, open one of the addresses below and type the password.";
  return { ok: true, message, ...phoneState() };
}

/** A QR code (PNG data URL) for one of the phone addresses. */
async function phoneQr(url) {
  if (typeof url !== "string" || !(/^http:\/\/\d{1,3}(\.\d{1,3}){3}:\d{1,5}\/?$/.test(url) || lib.isSecureUrl(url))) return { ok: false, message: "That is not a phone address." };
  try {
    const QRCode = require("qrcode");
    const dataUrl = await QRCode.toDataURL(url, { errorCorrectionLevel: "M", margin: 2, width: 240, color: { dark: "#000000", light: "#ffffff" } });
    return { ok: true, url, dataUrl };
  } catch (e) {
    say("The QR code could not be made: " + e.message);
    return { ok: false, message: "The QR code could not be made. Type the address on the phone instead." };
  }
}

/** Tailscale: { state: connected | signed-out | missing, ip, canInstall }. */
async function tailscaleInfo() {
  try {
    if (IS_WIN) await lib.refreshPath(process.env);     // installed while the app is open
    const st = await lib.checkTailscale();
    return { ok: true, ...st, canInstall: IS_WIN };
  } catch (e) {
    return { ok: false, state: "missing", ip: "", canInstall: IS_WIN, message: "Tailscale could not be checked: " + e.message };
  }
}

function installTailscale() {
  if (!IS_WIN) return { ok: false, message: "On this system, install Tailscale from tailscale.com/download, sign in, then press Check Tailscale." };
  say("Opening PowerShell to install Tailscale.");
  const err = openPowerShell("Agents HQ: installing Tailscale", "install-tailscale.ps1", lib.tailscaleInstallLines());
  if (err) return { ok: false, message: "PowerShell could not be opened: " + err };
  return { ok: true, message: "A PowerShell window is installing Tailscale. Approve the Windows prompt, wait until it says Done, sign in to Tailscale, then press Check Tailscale." };
}

// ---------------------------------------------------------------- the secure link (tailscale serve)

let secureQueue = Promise.resolve();
let secureRetries = 0, secureRetryTimer = null;
const SECURE_RETRIES = 6, SECURE_RETRY_MS = 30000;

/** Run the secure link changes one after the other (the phone window, the engine starting and quitting all make them). */
function secureTask(fn) {
  const p = secureQueue.then(fn, fn);
  secureQueue = p.catch((e) => say("Secure link: unexpected problem: " + (e && e.message || e)));
  return p;
}

function secureMaybeOn() {
  return secure.applied || secure.maybe;
}

/** The link should be on: the owner wants it, and our own engine runs with the phone password. */
function secureWanted() {
  return !!settings.secureLink && phoneOn() && enginePhone && !!child && state.engine === "running";
}

/** What phone.html shows in the secure link card. */
function secureState() {
  const active = enginePhone && state.engine === "running";
  return {
    want: !!(settings && settings.secureLink),
    on: secure.applied && secure.port === state.port && active,
    url: secure.url, httpsPort: secure.httpsPort, busy: secure.busy, problem: secure.problem, funnel: secure.funnel, checked: secure.checked,
  };
}

function pushPhone() {
  if (phoneWin && !phoneWin.isDestroyed()) phoneWin.webContents.send("phone:state", phoneState());
}

/** Every tailscale command and its answer go to the log (the phone password is never part of them). */
function logSteps(steps) {
  for (const st of steps || []) {
    const how = st.timedOut ? "no answer after " + lib.TAILSCALE_TIMEOUT_MS / 1000 + " s" : st.code === 0 ? "ok" : "exit code " + (st.code == null ? "none" : st.code);
    say(`> ${st.line}   (${how})`);
    for (const l of st.output) say("    " + l);
  }
}

async function applySecure(port, why) {
  say(`Secure link: turning it on for port ${port} (${why}).`);
  if (IS_WIN) await lib.refreshPath(process.env);
  const r = await lib.enableSecureLink(port);
  logSteps(r.steps);
  if (r.ok) {
    Object.assign(secure, { applied: true, maybe: true, port, httpsPort: r.httpsPort, url: r.url, problem: null, funnel: !!r.funnel });
    say(`Secure link on: ${r.url} relays to http://127.0.0.1:${port}; phones log in with the phone password.` + (r.httpsPort !== 443 ? ` (Port 443 is used by another app, so the office uses ${r.httpsPort} and leaves it alone.)` : "") + (r.verified ? "" : " (Tailscale's serve status did not confirm it; the address may take a few seconds.)"));
    if (r.funnel) say("Warning: Tailscale Funnel is on for this address, so it is open to the whole internet, not only your devices. Turn Funnel off in Tailscale unless you meant that.");
  } else {
    Object.assign(secure, { applied: false, maybe: true, problem: r.problem });     // maybe: serve may have half changed
    say("Secure link not on: " + (r.problem ? r.problem.message + (r.problem.link ? " " + r.problem.link : "") : "Tailscale did not say why."));
  }
  return r;
}

async function removeSecure(why) {
  say(`Secure link: turning it off (${why}).`);
  if (IS_WIN) await lib.refreshPath(process.env);
  // only links that relay to our engine (the port the link was made for, and the engine's port now) are turned off
  const r = await lib.disableSecureLink([...new Set([secure.port, state.port].filter(Boolean))], { httpsPort: secure.httpsPort });
  logSteps(r.steps);
  if (r.ok) Object.assign(secure, { applied: false, maybe: false, httpsPort: 0, funnel: false });
  else say("The secure link could not be turned off: " + (r.problem ? r.problem.message : "Tailscale did not answer.") + ` Run this in a terminal: tailscale serve --https=${secure.httpsPort || 443} off`);
  return r;
}

/** After the engine came up (or changed): on when it is wanted and not yet on this port, off when it is not wanted. */
function syncSecure(why) {
  return secureTask(async () => {
    if (secureWanted()) {
      if (secure.applied && secure.port === state.port) return;
      clearTimeout(secureRetryTimer);
      const r = await applySecure(state.port, why);
      if (r.ok) secureRetries = 0;
      else if (r.problem && ["not-running", "timeout", "failed"].includes(r.problem.kind) && secureRetries < SECURE_RETRIES) {
        secureRetries++;                // e.g. Tailscale is still connecting right after Windows starts
        say(`Secure link: trying again in ${SECURE_RETRY_MS / 1000} seconds (${secureRetries} of ${SECURE_RETRIES}).`);
        secureRetryTimer = setTimeout(() => syncSecure("trying again"), SECURE_RETRY_MS);
      }
    } else if (secureMaybeOn()) {
      await removeSecure(why);
    }
    pushPhone();
  });
}

/** phone:secure-get: what Tailscale says now (the https address, whether a link relays to our port, and on which https port). */
function secureGet() {
  return secureTask(async () => {
    if (IS_WIN) await lib.refreshPath(process.env);
    const info = await lib.secureLinkInfo(state.port);
    logSteps(info.steps);
    secure.checked = true;
    if (info.url) secure.url = info.url;
    secure.funnel = !!info.funnel;
    if (info.on && !(enginePhone && state.engine === "running")) {
      // relaying to an engine without the phone password: never leave that on
      await removeSecure("the engine on this port has no phone password right now");
    } else if (info.on) {
      Object.assign(secure, { applied: true, maybe: true, port: state.port, httpsPort: info.httpsPort, problem: null });
      if (!settings.secureLink) { settings.secureLink = true; saveSettings(); }      // keep it on this port when the port changes
    } else if (info.ok) {
      secure.applied = false;
      if (info.problem) secure.problem = info.problem;
    } else {
      secure.applied = false;
      secure.problem = info.problem;
    }
    pushPhone();
    return { ok: info.ok, proxy: info.on ? "" : info.proxy, ...secureState() };
  });
}

/** phone:secure-on: needs phone access on with its password and our engine running with it. */
async function secureOn() {
  const notYet = () => {
    if (!settings.phoneAccess || lib.passwordProblem(phone.password)) return "Turn phone access on above first (it needs the password), then turn on the secure link.";
    if (externalEngine && !child) return "The engine running now was not started by this app, so the secure link cannot use it. Close the window where it runs, then press Restart on the setup screen.";
    if (!(enginePhone && child && state.engine === "running")) return "Phone access is not active yet. Wait until the engine runs with phone access, then press Turn on again.";
    return "";
  };
  const before = notYet();
  if (before) return { ok: false, message: before, ...secureState() };
  return secureTask(async () => {
    const now = notYet();                                  // the engine may have changed while we waited for the queue
    if (now) return { ok: false, message: now, ...secureState() };
    secure.busy = true;
    pushPhone();
    let r;
    try {
      clearTimeout(secureRetryTimer);
      secureRetries = 0;
      r = await applySecure(state.port, "turned on in the phone window");
      if (r.ok) { settings.secureLink = true; saveSettings(); }
    } finally {
      secure.busy = false;
    }
    pushPhone();
    const message = r.ok ? `The secure link is on. On your phone, switch Tailscale on and open ${r.url}, then type the password.` : (r.problem && r.problem.message) || "The secure link did not turn on. Open the engine log to see why.";
    return { ok: r.ok, message, ...secureState() };
  });
}

/** phone:secure-off: always allowed. */
function secureOff() {
  return secureTask(async () => {
    secure.busy = true;
    pushPhone();
    let r;
    try {
      clearTimeout(secureRetryTimer);
      settings.secureLink = false;
      saveSettings();
      r = await removeSecure("turned off in the phone window");
      if (r.ok) secure.problem = null;
    } finally {
      secure.busy = false;
    }
    pushPhone();
    const message = r.ok ? "The secure link is off. The https address no longer opens the office." : "The secure link could not be turned off: " + ((r.problem && r.problem.message) || "Tailscale did not answer.");
    return { ok: r.ok, message, ...secureState() };
  });
}

/** The "Open Tailscale admin" button: https://login.tailscale.com/ links only, in the system browser. */
function openAdminLink(url) {
  if (!lib.isTailscaleAdminLink(url)) return { ok: false, message: "That is not a Tailscale admin link." };
  say("Opening the Tailscale admin in the browser: " + url);
  shell.openExternal(url);
  return { ok: true, message: "The Tailscale admin opened in your browser. Turn on HTTPS certificates there, then press Turn on again." };
}

// ---------------------------------------------------------------- quit

async function quit() {
  if (quitting) return;
  quitting = true;
  clearTimeout(secureRetryTimer);
  // the link goes with the app; it comes back on the next start when the engine is up with phone access
  if (secureMaybeOn()) {
    try { await Promise.race([secureTask(() => removeSecure("Agents HQ is quitting")), new Promise((r) => setTimeout(r, 8000))]); } catch (_) { /* quit anyway */ }
  }
  try { await stopEngine(); } catch (_) { /* nothing more to do */ }
  if (tray) { tray.destroy(); tray = null; }
  app.quit();
}

app.on("before-quit", (e) => {
  if (!quitting) { e.preventDefault(); quit(); }
});

app.on("window-all-closed", () => {
  if (!IS_MAC && !IS_WIN) quit();        // Windows hides to the tray instead; macOS keeps running as usual
});

app.on("activate", () => showWindow());
