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

# Sync settings: the Supabase project address and its public (anon/publishable) key.
# The key is designed to be public; row-level security keeps each person's trades private.
cfg_path = root / "site" / "config.json"
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
sync_script = ""
if cfg.get("supabaseUrl") and cfg.get("supabaseAnonKey"):
    sync_script = "<script>window.ELEV8_SUPABASE = " + json.dumps({"url": cfg["supabaseUrl"].rstrip("/"), "key": cfg["supabaseAnonKey"]}) + ";</script>"

version = hashlib.sha256((src + sync_script).encode()).hexdigest()[:10]
page = f"""<!doctype html>
<html lang="en" class="hosted">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<script>window.ELEV8_BUILD = "{version}";</script>
<script>
  // First-time visitors see the homepage. Anyone who has signed in here before, the installed app,
  // email buttons (?verify) and confirmation links, and ?login / ?signup / ?demo / ?app all open the journal directly.
  (function () {{ try {{
    if (/[?&](app|login|signup|demo|verify)(=|&|$)/.test(location.search) || /access_token|error_code|type=/.test(location.hash)) return;
    if ((window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone) return;
    if (localStorage.getItem("tj.sb.session.v1") || localStorage.getItem("tj.sb.email.v1") || localStorage.getItem("tj.trades.v1")) return;
    location.replace("home/");
  }} catch (e) {{}} }})();
</script>
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
{sync_script}
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
  if (req.mode === "navigate" && url.pathname.includes("/home/")) {{
    // The homepage: always from the network, never stored as the journal's offline copy.
    e.respondWith(fetch(req).catch(() => caches.match("./index.html")));
    return;
  }}
  if (req.mode === "navigate") {{
    // Bypass the HTTP cache (GitHub Pages caches pages for 10 minutes) so updates show on the next open.
    e.respondWith(fetch(req, {{ cache: "no-store" }}).then(res => {{ const copy = res.clone(); caches.open(CACHE).then(c => c.put("./index.html", copy)); return res; }})
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
# Custom domain for GitHub Pages (DNS is set up at Cloudflare).
(docs / "CNAME").write_text("elev8tradingjournal.com\n", encoding="utf-8")
# Homepage at /home/: site/home/index.html is page content (like index.html), wrapped here.
import shutil
home_src = (root / "site" / "home" / "index.html").read_text(encoding="utf-8")
home_title = re.search(r"<title>(.*?)</title>", home_src).group(1)
home_body = re.sub(r"<title>.*?</title>\s*", "", home_src, count=1)
home_page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{home_title}</title>
<meta name="description" content="The trading journal for prop and retail traders: log trades in seconds, track prop firm rules live and get a written review of your week.">
<meta name="theme-color" content="#06111f">
<meta property="og:title" content="ELEV8 Trading Journal">
<meta property="og:description" content="Know exactly why you win and lose. Log trades, track prop firm rules and review every week.">
<meta property="og:image" content="https://elev8tradingjournal.com/home/img/overview-desk.jpg">
<link rel="icon" type="image/png" sizes="32x32" href="../icons/favicon-32.png">
<link rel="apple-touch-icon" href="../icons/apple-touch-icon.png">
<link rel="canonical" href="https://elev8tradingjournal.com/home/">
</head>
<body>
{home_body}
</body>
</html>
"""
(docs / "home").mkdir(exist_ok=True)
(docs / "home" / "index.html").write_text(home_page, encoding="utf-8")
shutil.copytree(root / "site" / "home" / "img", docs / "home" / "img", dirs_exist_ok=True)
# Privacy Policy and Terms at /privacy/ and /terms/: site/legal/*.html are content, wrapped here.
LEGAL_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #06111f; color: #b0bfd3; font: 400 16.5px/1.7 Outfit, system-ui, -apple-system, "Segoe UI", sans-serif; -webkit-font-smoothing: antialiased; }
.top { border-bottom: 1px solid rgba(150,195,245,.14); }
.top div, main { max-width: 760px; margin: 0 auto; padding-left: max(20px, env(safe-area-inset-left, 0px)); padding-right: max(20px, env(safe-area-inset-right, 0px)); }
.top div { display: flex; align-items: center; justify-content: space-between; height: 64px; }
.top a.logo { display: flex; align-items: center; gap: 10px; text-decoration: none; font-weight: 800; letter-spacing: .12em; color: #2fd0c8; }
.top a.logo img { width: 34px; }
.top a.back { color: #b0bfd3; font-size: 14.5px; text-decoration: none; }
main { padding-block: 44px 80px; }
h1 { color: #e6eef8; font-size: 40px; line-height: 1.1; letter-spacing: -.02em; margin: 0 0 6px; }
h2 { color: #e6eef8; font-size: 21px; margin: 34px 0 8px; }
.meta { color: #8394ad; font-size: 14px; margin: 0 0 26px; }
p, ul { margin: 0 0 14px; } ul { padding-left: 22px; } li { margin-bottom: 6px; }
b { color: #e6eef8; font-weight: 600; }
a { color: #2fd0c8; }
footer { border-top: 1px solid rgba(150,195,245,.14); color: #5d7190; font-size: 13px; }
footer div { max-width: 760px; margin: 0 auto; padding: 22px max(20px, env(safe-area-inset-left, 0px)) 40px; display: flex; gap: 18px; flex-wrap: wrap; }
footer a { color: #8394ad; }
"""
for slug in ("privacy", "terms"):
    src_l = (root / "site" / "legal" / f"{slug}.html").read_text(encoding="utf-8")
    title_l = re.search(r"<title>(.*?)</title>", src_l).group(1)
    body_l = re.sub(r"<title>.*?</title>\s*", "", src_l, count=1)
    page_l = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title_l}</title>
<meta name="theme-color" content="#06111f">
<link rel="icon" type="image/png" sizes="32x32" href="../icons/favicon-32.png">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap">
<style>{LEGAL_CSS}</style>
</head>
<body>
<header class="top"><div><a class="logo" href="../home/"><img src="../home/img/mark.svg" alt="">ELEV8</a><a class="back" href="../home/">Back to home</a></div></header>
<main>
{body_l}
</main>
<footer><div><span>ELEV8 Trading Journal</span><a href="../privacy/">Privacy Policy</a><a href="../terms/">Terms of Use</a><a href="../home/">Home</a></div></footer>
</body>
</html>
"""
    (docs / slug).mkdir(exist_ok=True)
    (docs / slug / "index.html").write_text(page_l, encoding="utf-8")

# Logo the account and weekly-review emails load from the website.
(docs / "email").mkdir(exist_ok=True)
shutil.copy(root / "site" / "email-templates" / "img" / "elev8-email-logo.png", docs / "email" / "elev8-email-logo.png")
subprocess.run([sys.executable, str(root / "site" / "make_icons.py"), str(docs / "icons")], check=True)
print("built docs/ (version", version + ")")
