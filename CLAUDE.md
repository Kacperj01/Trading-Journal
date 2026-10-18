# ELEV8 project notes

## Videos, social posts and marketing
- Every promo video and social post must say ELEV8 is **for education only, not financial advice**, and that it is **not affiliated with any prop firm or broker**.
- No pricing on the homepage or in promos; use "Start now".
- Keep the ELEV8 colours and the Outfit font.

## Repo
- App source: `index.html`. Homepage: `site/home/`. Legal: `site/legal/`. `python3 site/build.py` builds into `docs/`, which Cloudflare Pages serves (output folder `docs`, no build command; `docs/_headers` sets response headers).
- Never put API keys or the Supabase service key in the app or the repo.
