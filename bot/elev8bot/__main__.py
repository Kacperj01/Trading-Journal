"""Command line: python -m elev8bot backtest|run|check"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config

DISCLAIMER = ("ELEV8 bot is for education only, not financial advice. Not affiliated with any prop firm "
              "or broker. Automated trading can lose money fast; test on paper first.")


def cmd_backtest(args) -> int:
    from .backtest import run_backtest, write_trades_csv
    from .data import detect_minutes, load_csv, resample, synthetic

    cfg = load_config(args.config)
    ltf = cfg.timeframes.ltf_minutes
    if args.synthetic:
        bars = synthetic(days=args.days, minutes=ltf)
        print("Using random synthetic data: this only checks the bot runs, it says nothing about the strategy.\n")
    elif args.csv:
        bars = load_csv(args.csv, args.tz)
        bars = resample(bars, detect_minutes(bars), ltf)
    else:
        print("Give --csv FILE or --synthetic", file=sys.stderr)
        return 2
    if not bars:
        print("No bars loaded", file=sys.stderr)
        return 1
    print(f"{cfg.instrument.symbol}: {len(bars)} bars of {ltf}m, {bars[0].time:%Y-%m-%d} to {bars[-1].time:%Y-%m-%d}")
    result = run_backtest(cfg, bars)
    print(result.summary())
    if args.trades:
        write_trades_csv(args.trades, cfg, result.trades)
        print(f"\nTrades written to {args.trades} (import into the ELEV8 journal)")
    if args.log:
        with open(args.log, "w") as fh:
            fh.write("\n".join(result.log) + "\n")
        print(f"Decision log written to {args.log}")
    return 0


def cmd_run(args) -> int:
    from .live import run

    cfg = load_config(args.config)
    handlers = [logging.StreamHandler(), logging.FileHandler(args.logfile)]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    run(cfg, confirmed_live=args.confirm_live)
    return 0


def cmd_check(args) -> int:
    from .live import make_broker, make_feed

    cfg = load_config(args.config)
    feed = make_feed(cfg)
    feed.connect()
    bars = feed.closed_bars(5)
    print(f"Data OK: last bars for {cfg.instrument.symbol}:")
    for b in bars:
        print(f"  {b.time:%Y-%m-%d %H:%M} UTC  O {b.open:g} H {b.high:g} L {b.low:g} C {b.close:g}")
    broker = make_broker(cfg, feed)
    if broker is not feed:
        broker.connect()
    print(f"Orders: {broker.name} ({cfg.broker.mode}); equity {broker.equity():,.2f}; open position: {broker.has_position()}")
    ins = cfg.instrument
    print(f"Contract: tick size {ins.tick_size:g}, tick value {ins.tick_value:g}, size step {ins.qty_step:g}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="elev8bot", description=DISCLAIMER)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backtest", help="test the strategy on historical bars")
    b.add_argument("--config", help="settings file (TOML)")
    b.add_argument("--csv", help="bars exported from MT5 / NinjaTrader / TradingView")
    b.add_argument("--tz", default="UTC", help="timezone of the CSV times, e.g. Europe/Athens for many MT5 servers")
    b.add_argument("--synthetic", action="store_true", help="use random data to check the bot runs")
    b.add_argument("--days", type=int, default=90)
    b.add_argument("--trades", help="write trades to this CSV")
    b.add_argument("--log", help="write every decision the bot made to this file")
    b.set_defaults(func=cmd_backtest)

    r = sub.add_parser("run", help="run on live prices (paper or live, from the config)")
    r.add_argument("--config", required=True)
    r.add_argument("--confirm-live", action="store_true", help="needed when broker.mode = live")
    r.add_argument("--logfile", default="elev8bot.log")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("check", help="test the broker connection without trading")
    c.add_argument("--config", required=True)
    c.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    print(DISCLAIMER + "\n")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
