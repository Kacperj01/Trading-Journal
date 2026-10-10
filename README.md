# Trading Journal

A self-contained trading journal and performance dashboard. Open `index.html` in a browser; there's no build step and no dependencies.

**Tabs:** Overview · Analytics · Psychology · Calendar · Insights · Trade log · Log trade · Settings

- Log trades by date and time, with pair, session (filled in automatically from the time), direction, setup, prices, risk, P&L, R multiple, emotions before and after, confidence, plan adherence, mistakes, notes and a chart link.
- Every analytics tab respects the shared Period, Session and Setup filters.
- Settings lets you edit the account balance, currency, default risk and the dropdown lists (pairs, setups, sessions, emotions, mistakes).
- Import `.xlsx`, `.csv` or `.json` files (columns are matched by name). Export to JSON or CSV.
- When published as a claude.ai artifact, trades sync privately to your account across devices; opened as a local file, they are saved in the browser. Export a backup regularly.

## Install on iPhone

The installable app lives in `docs/` and is built from `index.html`:

```
python3 site/build.py
```

Host it with GitHub Pages (Settings → Pages → Deploy from a branch → this branch, folder `/docs`), then open the Pages address in Safari, tap Share → Add to Home Screen. The app opens full screen, works offline, and saves trades on the device. Move trades in from Settings → Import file, using a file saved with Export journal, or an Excel/CSV/JSON export.
