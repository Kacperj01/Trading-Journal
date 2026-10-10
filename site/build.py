"""Build the installable web app into docs/ (served by GitHub Pages).

index.html is written as page content for claude.ai, which supplies the document wrapper.
This wraps the same content in a full document with the web-app metadata, and adds the
manifest, icons and an offline service worker. Run: python3 site/build.py
"""
import hashlib, json, re, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
docs = root / "docs"
src = (root / "index.html").read_text(encoding="utf-8")

# Everything up to the end of the page's <style> belongs in <head>; the rest is the body.
cut = src.index("</style>") + len("</style>")
head_part, body_part = src[:cut], src[cut:]
head_part = re.sub(r'<meta charset="utf-8">\s*', "", head_part)
head_part = re.sub(r"<title>.*?</title>\s*", "", head_part)

version = hashlib.sha256(src.encode()).hexdigest()[:10]
page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>ELEV8 Trading Journal</title>
<meta name="theme-color" content="#06111f">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="ELEV8">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<style>
  /* Keep content clear of the iPhone status bar and home indicator when opened from the home screen. */
  html {{ background: #06111f; padding: env(safe-area-inset-top, 0px) env(safe-area-inset-right, 0px) env(safe-area-inset-bottom, 0px) env(safe-area-inset-left, 0px); }}
  body {{ margin: 0; }}
  [hidden] {{ display: none !important; }}
</style>
{head_part}
</head>
<body>{body_part}
</body>
</html>
"""

manifest = {
    "name": "ELEV8 Trading Journal",
    "short_name": "ELEV8",
    "description": "Log trades with sessions, setups and emotions, and see your P&L, win rate and insights.",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#06111f",
    "theme_color": "#06111f",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

sw = f"""// Offline support for the Trading Journal app. The version changes whenever the page does.
const CACHE = "journal-{version}";
const FONTS = "journal-fonts";
const CORE = ["./", "./index.html", "./manifest.webmanifest", "./icons/apple-touch-icon.png", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/favicon-32.png"];

self.addEventListener("install", e => {{
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
}});
self.addEventListener("activate", e => {{
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== FONTS).map(k => caches.delete(k)))).then(() => self.clients.claim()));
}});
self.addEventListener("fetch", e => {{
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // The page: try the network for the latest version, fall back to the saved copy offline.
  if (req.mode === "navigate") {{
    e.respondWith(fetch(req).then(res => {{ const copy = res.clone(); caches.open(CACHE).then(c => c.put("./index.html", copy)); return res; }})
      .catch(() => caches.match("./index.html")));
    return;
  }}
  // Google Fonts: serve the saved copy, refresh it in the background.
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {{
    e.respondWith(caches.open(FONTS).then(async c => {{
      const hit = await c.match(req);
      const net = fetch(req).then(res => {{ c.put(req, res.clone()); return res; }}).catch(() => hit);
      return hit || net;
    }}));
    return;
  }}
  if (url.origin === location.origin) {{
    e.respondWith(caches.match(req, {{ ignoreSearch: true }}).then(hit => hit || fetch(req)));
  }}
}});
"""

docs.mkdir(exist_ok=True)
(docs / "index.html").write_text(page, encoding="utf-8")
(docs / "manifest.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(docs / "sw.js").write_text(sw, encoding="utf-8")
(docs / ".nojekyll").write_text("", encoding="utf-8")
subprocess.run([sys.executable, str(root / "site" / "make_icons.py"), str(docs / "icons")], check=True)
print("built docs/ (version", version + ")")
