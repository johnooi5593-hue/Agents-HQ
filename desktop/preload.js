"use strict";
/* preload.js: the bridge between setup.html and main.js.
 * The page gets window.desktop with a fixed list of calls; nothing else from node or electron reaches it.
 */
const { contextBridge, ipcRenderer } = require("electron");

// calls the page may make (each answers with a promise)
const INVOKE = ["getState", "check", "installMissing", "signIn", "openFolder", "openLog", "start"];
// events main.js pushes to the page
const EVENTS = { onLog: "hq:log", onState: "hq:state" };

const desktop = {};
for (const name of INVOKE) desktop[name] = (...args) => ipcRenderer.invoke("hq:" + name, ...args);
for (const [name, channel] of Object.entries(EVENTS)) {
  desktop[name] = (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  };
}

contextBridge.exposeInMainWorld("desktop", desktop);
