// Offline support for the Trading Journal app. The version changes whenever the page does.
const CACHE = "journal-37773b9ca3";
const FONTS = "journal-fonts";
const CORE = ["./", "./index.html", "./manifest.webmanifest", "./icons/apple-touch-icon.png", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/favicon-32.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== FONTS).map(k => caches.delete(k)))).then(() => self.clients.claim()));
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
  // Google Fonts: serve the saved copy, refresh it in the background.
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    e.respondWith(caches.open(FONTS).then(async c => {
      const hit = await c.match(req);
      const net = fetch(req).then(res => { c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => hit || fetch(req)));
  }
});
