"use strict";
/* preload.js: the bridge between the app's pages (setup.html, phone.html) and main.js.
 * The page gets window.desktop with a fixed list of calls; nothing else from node or electron reaches it.
 * main.js answers the phone:* calls only for the app's own file:// pages, never for the office page.
 */
const { contextBridge, ipcRenderer } = require("electron");

// calls the page may make (each answers with a promise): window.desktop.<name>(...) -> ipc channel
const INVOKE = {
  getState: "hq:getState", check: "hq:check", installMissing: "hq:installMissing", signIn: "hq:signIn",
  openFolder: "hq:openFolder", openLog: "hq:openLog", start: "hq:start", openPhone: "hq:openPhone",
  phoneGet: "phone:get", phoneSet: "phone:set", phoneQr: "phone:qr", phoneTailscale: "phone:tailscale",
  phoneInstallTailscale: "phone:install-tailscale", phoneGenerate: "phone:generate", phoneCopy: "phone:copy",
};
// events main.js pushes to the page
const EVENTS = { onLog: "hq:log", onState: "hq:state", onPhoneState: "phone:state" };

const desktop = {};
for (const [name, channel] of Object.entries(INVOKE)) desktop[name] = (...args) => ipcRenderer.invoke(channel, ...args);
for (const [name, channel] of Object.entries(EVENTS)) {
  desktop[name] = (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  };
}

contextBridge.exposeInMainWorld("desktop", desktop);
