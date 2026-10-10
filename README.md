# Trading Journal

A self-contained trading journal and performance dashboard. Open `index.html` in a browser; there's no build step and no dependencies.

**Tabs:** Overview · Analytics · Psychology · Calendar · Insights · Trade log · Log trade · Settings

- Log trades by date and time, with pair, session (filled in automatically from the time), direction, setup, prices, risk, P&L, R multiple, emotions before and after, confidence, plan adherence, mistakes, notes and a chart link.
- Every analytics tab respects the shared Period, Session and Setup filters.
- Settings lets you edit the account balance, currency, default risk and the dropdown lists (pairs, setups, sessions, emotions, mistakes).
- Import `.xlsx`, `.csv` or `.json` files (columns are matched by name). Export to JSON or CSV.
- Data is stored in your browser's localStorage. Export a backup regularly.
