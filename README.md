# Trading Journal

A self-contained trading journal and performance dashboard. Open `index.html` in a browser; there's no build step and no dependencies.

**Tabs:** Overview · Analytics · Psychology · Calendar · Insights · Trade log · Log trade · Settings

- Log trades by date and time, with pair, session (filled in automatically from the time), direction, setup, prices, risk, P&L, R multiple, emotions before and after, confidence, plan adherence, mistakes, notes and a chart link.
- Every analytics tab respects the shared Period, Session and Setup filters.
- Settings lets you edit the account balance, currency, default risk and the dropdown lists (pairs, setups, sessions, emotions, mistakes).
- Import `.xlsx`, `.csv` or `.json` files (columns are matched by name). Export to JSON or CSV.
- When published as a claude.ai artifact, trades sync privately to your account across devices; opened as a local file, they are saved in the browser. Export a backup regularly.

`data/notion-q4-2026.json` holds the 22 trades from the Notion database "Trading Journal Q4 2026" (1–9 Oct 2026), converted to the journal's format. Import it from Settings when using the page locally. Setups, mistakes and plan adherence were inferred from each trade's notes, because the Notion database has no columns for them.
