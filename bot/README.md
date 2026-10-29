# ELEV8 trading bot

> **For education only, not financial advice.** ELEV8 is not affiliated with any prop firm or broker.
> Automated trading can lose money quickly. Backtest, then paper trade, then use a demo or eval account before real money.
> Check your prop firm's rules: some ban bots, copy trading or trading during news.

A supply and demand bot built for **gold**: spot gold (XAUUSD) on MetaTrader 5 and gold futures (MGC / GC) on Tradovate and NinjaTrader 8. The rules work on other markets too, but the ready-made settings are for gold.

## Gold presets

Copy the one for your platform to `config.toml`:

| File | Market | Platform |
|---|---|---|
| `presets/xauusd_mt5.toml` | Spot gold, XAUUSD | MetaTrader 5 |
| `presets/mgc_tradovate.toml` | Micro gold futures, MGC | Tradovate |
| `presets/mgc_ninjatrader.toml` | Micro gold futures, MGC | NinjaTrader 8 (bars from Tradovate) |

What's tuned for gold:
- **Sessions:** London 02:00–05:00 and New York 07:00–11:00 (New York time), which covers the 08:20 COMEX open and 08:30 US data.
- **Stop buffer:** $0.60 beyond the swept high or low (60 ticks on XAUUSD, 6 ticks on MGC).
- **Flat by 16:50** New York time, before the 17:00 close or roll.
- **Futures trading day** starts at the 18:00 reopen, so the previous day high and low match the CME session.
- **Sizing:** MGC is $1 per $0.10 tick per contract. For full-size GC, set `tick_value = 10.0`, `max_qty = 2` and the GC contract name. On MT5 the bot reads gold's contract size from your broker.
- **Contract roll:** the futures presets use the December 2026 contract (`MGCZ6` / `MGC 12-26`). Switch to February 2027 (`MGCG7` / `MGC 02-27`) in late November, when volume moves over.

Don't run XAUUSD and MGC at the same time on the same money. They're the same market, so it would double your risk.

## The strategy

1. **Valid zones only.** On the higher timeframe (1 hour by default), a demand or supply zone counts only if the move out of it:
   - broke structure (closed beyond the last swing high or low),
   - moved at least 1.5 ATR,
   - left a fair value gap,
   - and the zone itself is no taller than 1 ATR.

   Optionally the zone must also have swept liquidity before the move (`require_liquidity_origin`). A zone dies after one trade, when a candle closes through it, or when it gets too old.
2. **Liquidity pools.** The bot tracks the previous day high and low (day rolls at 17:00 New York) and the Asia, London and New York session highs and lows. It also tracks which ones have already been taken.
3. **Don't enter on the tap.** When price reaches a valid zone, or sweeps the PDH/PDL or a session high or low, the bot arms a setup and waits.
4. **Confirmation on the entry timeframe (5 minutes):**
   - `sweep_then_bos` (default): liquidity gets swept, then a candle closes through the last swing (break of structure).
   - `bos`: break of structure only.
   - `sweep`: sweep, then a close back inside with a candle in the trade's direction.
5. **Sessions.** Entries happen only in the sessions in `trade_in` (London and New York by default).
6. **Stop and target.** The stop goes beyond the swept extreme plus a buffer. The target is the **nearest** untaken liquidity in the trade's direction: PDH/PDL, a session high or low, a higher-timeframe swing, or an opposing zone. If that liquidity is closer than `min_rr` (2R), the bot skips the trade.
7. **Risk.** Each trade risks 0.5% of equity. The bot allows at most 2 trades a day and stops for the day at -2% or after 3 losses in a row. It stops for good at a 6% drawdown. Every number is in `config.toml`.

Every decision is logged in plain words, for example "new demand zone 1.0841-1.0852: broke structure, displacement 2.3 ATR, left a fair value gap" or "skip: next liquidity (PDH) only 1.4R away". Use `--log` to see why it did or didn't trade.

## Setup

Requires Python 3.11 or newer.

```
cd bot
cp config.example.toml config.toml      # then edit it
pip install -r requirements.txt         # only for MT5 / Tradovate connections
```

## 1. Backtest

Export bars from MT5 (History Center, or right-click the chart > Export), NinjaTrader (Tools > Historical Data > Export) or TradingView. 1-minute or 5-minute bars work; the bot resamples them.

```
python -m elev8bot backtest --config config.toml --csv data/XAUUSD_M5.csv --tz Europe/Athens --trades trades.csv --log decisions.txt
```

- `--tz` is the timezone your export uses. Many MT5 brokers use server time `Europe/Athens` (GMT+2/+3). Most futures exports use `America/New_York` or UTC. Getting this wrong puts the sessions in the wrong place.
- `trades.csv` can be imported into the ELEV8 journal.
- `--synthetic` runs on random data. It only checks that the bot runs.

The backtest fills at the close of the confirmation candle and counts a bar that hits both stop and target as a loss. It includes your commission and slippage settings.

## 2. Check the connection

```
python -m elev8bot check --config config.toml
```

This prints the latest bars, your balance and the contract specs. It places no orders.

## 3. Paper trade on live prices

Set `mode = "paper"` (the default). The bot reads live bars from MT5 or Tradovate and simulates fills:

```
python -m elev8bot run --config config.toml
```

## 4. Live

Set `mode = "live"`, then:

```
python -m elev8bot run --config config.toml --confirm-live
```

- To stop: Ctrl+C, or create a file named `STOP` in the folder. Open trades keep their stop and target at the broker.
- On MT5 and Tradovate, the stop and target go out with the entry order, so they sit at the broker even if the bot crashes. On NinjaTrader they are sent right after the entry fills.

### MetaTrader 5 (forex)
- Windows only. Install the MT5 terminal, log in, and switch on **Algo Trading**.
- `pip install MetaTrader5`
- Set `broker = "mt5"` and `symbol` exactly as it appears in Market Watch (for example `EURUSD` or `EURUSD.r`).
- The bot reads tick size, tick value and lot step from your broker. It works out the server time offset itself, or you can set `mt5_server_utc_offset`.
- It tags its orders with `mt5_magic` and never touches your manual trades.

### Tradovate (futures)
- You need API access from Tradovate (an API key: CID and secret) and a market data subscription that covers API use.
- Put your login in **environment variables**, never in the config or this repo:
  ```
  set TRADOVATE_USERNAME=...
  set TRADOVATE_PASSWORD=...
  set TRADOVATE_CID=...
  set TRADOVATE_SECRET=...
  ```
- Set `broker = "tradovate"`, `tradovate_symbol = "MESZ6"` (the full contract), `tradovate_env = "demo"` first, and futures contract specs, e.g. MES: `tick_size = 0.25`, `tick_value = 1.25`, `qty_step = 1`, `min_qty = 1`.
- `pip install websocket-client`

### NinjaTrader 8 (futures)
- Turn on Tools > Options > Automated trading interface > **AT interface**.
- Set `broker = "ninjatrader"`, `ninjatrader_account` (for example `Sim101` first) and `ninjatrader_instrument = "MES 12-26"`.
- NinjaTrader's interface doesn't stream prices, so set `data_source = "tradovate"` (or `"mt5"`) for bars.
- The bot sends the stop and target only after the entry fills. It works out P&L from NinjaTrader's fill files for the daily loss limit.

## Known limits
- The broker connections are written against the MT5, Tradovate and NinjaTrader ATI documentation but **have not been run against real accounts yet**. Run `check`, then paper, then a demo or sim account before anything else.
- On futures, the default sessions are the forex killzones in New York time. For index futures you may want `newyork = ["09:30", "11:00"]`.
- News events aren't filtered yet.

## Tests

```
python -m unittest discover -s tests
```
