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
 * Build: copy the office into desktop/bundle (the GitHub workflow .github/workflows/windows-app.yml does this with
 * robocopy: the repository without .git, desktop, out, done, approved and the inbox contents), then `npm run dist:win`.
 */
const { app, BrowserWindow, Menu, Tray, ipcMain, shell, session, nativeImage } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const lib = require("./lib");

const APP_ID = "com.agentshq.desktop";
const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const ASSETS = path.join(__dirname, "assets");
const SETUP_PAGE = path.join(__dirname, "setup.html");
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
let win = null, tray = null;
let child = null;             // the engine process
let externalEngine = false;   // an engine we did not start answers on the port
let expectedExit = false;     // we stopped the engine ourselves
let pythonCmd = null;         // e.g. ["py", "-3"], the python that passed the check
let claudeBin;                // resolved once: the claude executable for CLAUDE_BIN, or null
let booting = false;
let quitting = false;
let hiddenByUser = false;     // the user closed the window to the tray; it does not pop up again by itself
let logStream = null;
const log = new lib.RingLog(500);

const state = {
  phase: "checking",          // checking | missing | cloning | setup | starting | ready | stopped | updating | error
  message: "",
  tools: [], allOk: false, requiredOk: false, python: "",
  officeDir: "", port: lib.DEFAULT_PORT, url: "",
  engine: "stopped",          // stopped | starting | running
  setupDone: false, canOpen: false, busy: false, signedIn: null,
  platform: process.platform, logFile: "",
};

function publicState() {
  return { ...state, busy: booting, canOpen: state.engine === "running" && state.requiredOk };
}

function setState(patch) {
  Object.assign(state, patch);
  if (win && !win.isDestroyed()) win.webContents.send("hq:state", publicState());
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
  Object.assign(state, { officeDir: settings.officeDir, port: settings.port, setupDone: !!settings.setupDone, logFile });

  // the log: every line to the setup screen and to engine.log
  openLogStream();
  log.onLine((line) => {
    if (win && !win.isDestroyed()) win.webContents.send("hq:log", line);
    if (logStream) logStream.write(line + "\n");
  });
  say(`Agents HQ desktop ${app.getVersion()} on ${process.platform}; settings in ${userData}; office folder ${settings.officeDir}`);

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
  if (git && git.ok) {
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
  return true;
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

async function engineEnv() {
  const env = { ...process.env, HQ_PORT: String(settings.port), PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" };
  if (claudeBin === undefined) claudeBin = await resolveClaudeBin();
  if (claudeBin) env.CLAUDE_BIN = claudeBin;
  return env;
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
    externalEngine = true;
    engineUp(settings.port);
    return;
  }
  externalEngine = false;
  const port = await lib.findPort(settings.port);
  if (!port) {
    setState({ phase: "error", engine: "stopped", message: 'Ports 7331 to 7340 are all busy. Close the programs that use them, then press "Check again".' });
    return;
  }
  if (port !== settings.port) { settings.port = port; saveSettings(); say(`Port ${state.port} is busy, using ${port}.`); }
  setState({ port });

  const env = await engineEnv();
  const args = [...pythonCmd.slice(1), "hq/server.py", "--no-browser"];
  say(`Engine: ${pythonCmd[0]} ${args.join(" ")}   (port ${port}, folder ${settings.officeDir}${env.CLAUDE_BIN ? ", claude " + env.CLAUDE_BIN : ""})`);
  expectedExit = false;
  let me;
  try {
    me = spawn(pythonCmd[0], args, { cwd: settings.officeDir, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  } catch (e) {
    setState({ phase: "error", engine: "stopped", message: "The engine could not start: " + e.message + '. Press "Check again".' });
    return;
  }
  child = me;
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

async function restartEngine() {
  if (booting) return;
  showWindow();
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

/** Tray: git pull in the office folder, then restart the engine. */
async function checkForUpdates() {
  if (booting) return;
  showWindow();
  showSetup();
  if (!fs.existsSync(path.join(settings.officeDir, ".git"))) {
    say("This office folder was copied from the app, not downloaded with Git, so it cannot update itself. Install Git, move the folder somewhere else, and open Agents HQ again to download a fresh copy.");
    setState({ message: "This office folder cannot update itself (it was not downloaded with Git). See the log." });
    return;
  }
  booting = true;
  setState({ busy: true, phase: "updating", message: "Checking GitHub for a newer Agents HQ..." });
  try {
    if (child) await stopEngine();
    const code = await stream("git", ["pull", "--ff-only"], { cwd: settings.officeDir });
    say(code === 0 ? "Update check finished." : "The update did not finish; the lines above say why.");
    await startEngine();
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
    { type: "separator" },
    { label: "Restart engine", click: () => restartEngine() },
    { label: "Check for updates", click: () => checkForUpdates() },
    { type: "separator" },
    { label: `Engine: ${state.engine}${state.engine === "running" ? " on port " + state.port : ""}`, enabled: false },
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

/**
 * "Install missing tools": a visible PowerShell window running the winget commands and the Claude Code installer.
 * The script is written to a file and started through `cmd /c start`, which gives PowerShell its own console
 * (a detached child of a GUI app has none, so it would run invisibly).
 */
function installMissing() {
  const missing = state.tools.filter((t) => !t.ok);
  if (!missing.length) return { ok: true, message: "Everything is installed." };
  if (!IS_WIN) {
    say("Install these yourself, then press Check again: " + missing.map((t) => t.label).join(", "));
    return { ok: false, message: "On this system, install " + missing.map((t) => t.label).join(", ") + " yourself, then press Check again." };
  }
  try {
    const script = path.join(app.getPath("userData"), "install-tools.ps1");
    fs.writeFileSync(script, lib.installLines(state.tools).join("\r\n") + "\r\n", "utf8");
    say("Opening PowerShell to install: " + missing.map((t) => t.label).join(", ") + ` (${script})`);
    const p = spawn("cmd.exe", ["/c", "start", "Agents HQ: installing tools", "powershell.exe", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", script],
      { detached: true, stdio: "ignore", windowsHide: true });
    p.on("error", (e) => say("PowerShell could not be opened: " + e.message));
    p.unref();
    return { ok: true, message: "A PowerShell window is installing the tools. Approve the Windows prompts, wait until it says Done, then press Check again." };
  } catch (e) {
    return { ok: false, message: "PowerShell could not be opened: " + e.message };
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
  ipcMain.handle("hq:openFolder", async () => ({ ok: !(await openFolder()) }));
  ipcMain.handle("hq:openLog", async () => ({ ok: !(await openLog()) }));
  ipcMain.handle("hq:start", () => startOrOpen());
}

// ---------------------------------------------------------------- quit

async function quit() {
  if (quitting) return;
  quitting = true;
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
