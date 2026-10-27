// Agents HQ on a phone's home screen: the "can't reach your PC" page, and notifications.
// Nothing else is cached: every screen and file comes from the PC each time, so the app is always the newest version.
const CACHE = "hq-shell-v1";
const OFFLINE = "/offline.html";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, "/icons/icon-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;                  // files and API calls: straight from the PC
  e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
});

self.addEventListener("push", (e) => {
  let msg = {};
  try { msg = e.data ? e.data.json() : {}; } catch (_) { msg = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(msg.title || "Agents HQ", {
    body: msg.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: msg.tag || undefined,                                // a newer message about the same task replaces the older one
    renotify: !!msg.tag,
    data: { url: msg.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "/", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    const open = wins.find((w) => new URL(w.url).origin === self.location.origin);
    if (open) return open.focus().then((w) => (w && w.navigate ? w.navigate(url) : null));
    return self.clients.openWindow(url);
  }));
});
