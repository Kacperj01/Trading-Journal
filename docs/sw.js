// Offline support for the Trading Journal app. The version changes whenever the page does.
const CACHE = "journal-6026fce0e4";
const CORE = ["./", "./index.html", "./manifest.webmanifest", "./icons/apple-touch-icon.png", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/favicon-32.png",
  "./fonts/fonts.css", "./fonts/outfit-latin.woff2", "./fonts/outfit-latin-ext.woff2", "./fonts/jetbrains-mono-latin.woff2", "./fonts/jetbrains-mono-latin-ext.woff2"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // The page: try the network for the latest version, fall back to the saved copy offline.
  if (req.mode === "navigate" && url.pathname.includes("/home/")) {
    // The homepage: always from the network, never stored as the journal's offline copy.
    e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match("./index.html")));
    return;
  }
  if (req.mode === "navigate") {
    // Bypass the HTTP cache (GitHub Pages caches pages for 10 minutes) so updates show on the next open.
    e.respondWith(fetch(req, { cache: "no-store" }).then(res => { const copy = res.clone(); caches.open(CACHE).then(c => c.put("./index.html", copy)); return res; })
      .catch(() => caches.match("./index.html")));
    return;
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => hit || fetch(req)));
  }
});

// Notifications (weekly review ready, high-impact news), sent by the weekly-review and news-alerts Actions.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "ELEV8", {
    body: d.body || "", icon: "./icons/icon-192.png", badge: "./icons/badge-96.png",
    tag: d.tag || undefined, renotify: !!d.tag, data: { url: d.url || "./?app" }
  }));
});
// Tapping one opens the journal on that page, reusing an open journal window if there is one.
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "./?app", self.registration.scope);
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const open = list.find(c => { const p = new URL(c.url); return p.origin === url.origin && !/\/(home|privacy|terms)\//.test(p.pathname); });
    if (open) { open.postMessage({ open: url.searchParams.get("open") }); return open.focus(); }
    return clients.openWindow(url.href);
  }));
});
