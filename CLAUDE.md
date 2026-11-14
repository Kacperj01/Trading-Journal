# ELEV8 project notes

## Videos, social posts and marketing
- Every promo video and social post must say ELEV8 is **for education only, not financial advice**, and that it is **not affiliated with any prop firm or broker**.
- No pricing in promos; use "Start now".
- Journal plans: Free (EUR 0), Pro (EUR 14.99/mo or 149/yr), Elite (EUR 29.99/mo or 299/yr), with a 7-day Elite trial and no card. Shown in the homepage pricing section and on elev8trading.app. Paid plans aren't built yet ("Launching soon"); until they are, every feature stays free.
- Keep the ELEV8 colours and the Outfit font.

## Repo
- App source: `index.html`. Homepage: `site/home/`. Legal: `site/legal/`. `python3 site/build.py` builds into `docs/`, which GitHub Pages serves. (Ready for Cloudflare Pages if hosting ever moves: output folder `docs`, no build command; `docs/_headers` sets response headers there.)
- Never put API keys or the Supabase service key in the app or the repo.
