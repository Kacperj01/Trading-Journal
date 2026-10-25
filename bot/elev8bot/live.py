"""Run the strategy on live bars, in paper mode or with real orders."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .brokers.base import Broker, BrokerError, DataFeed
from .config import Config
from .risk import RiskManager
from .strategy import Strategy

log = logging.getLogger("elev8bot")

STOP_FILE = Path("STOP")  # create a file called STOP next to the bot to halt it


def make_feed(cfg: Config) -> DataFeed:
    source = cfg.broker.data_source or cfg.broker.broker
    if source == "mt5":
        from .brokers.mt5 import MT5
        return MT5(cfg)
    if source == "tradovate":
        from .brokers.tradovate import Tradovate
        return Tradovate(cfg)
    raise BrokerError(f"No live data from '{source}'. Set broker.data_source to mt5 or tradovate")


def make_broker(cfg: Config, feed: DataFeed) -> Broker:
    if cfg.broker.mode == "paper" or cfg.broker.broker == "paper":
        from .brokers.paper import PaperBroker
        return PaperBroker(cfg)
    if isinstance(feed, Broker) and feed.name == cfg.broker.broker:
        return feed  # same connection for data and orders
    if cfg.broker.broker == "mt5":
        from .brokers.mt5 import MT5
        return MT5(cfg)
    if cfg.broker.broker == "tradovate":
        from .brokers.tradovate import Tradovate
        return Tradovate(cfg)
    from .brokers.ninjatrader import NinjaTrader
    return NinjaTrader(cfg)


def run(cfg: Config, confirmed_live: bool, warmup: int = 1500) -> None:
    live = cfg.broker.mode == "live" and cfg.broker.broker != "paper"
    if live and not confirmed_live:
        raise SystemExit("Live mode places real orders. Re-run with --confirm-live once you have tested on paper.")
    feed = make_feed(cfg)
    feed.connect()
    broker = make_broker(cfg, feed)
    if broker is not feed:
        broker.connect()
    log.info("Connected. Data: %s, orders: %s (%s)", type(feed).__name__, broker.name, "LIVE" if live else "paper")

    strat = Strategy(cfg)
    history = feed.closed_bars(warmup)
    if not history:
        raise BrokerError("No bars received")
    for bar in history:  # rebuild zones and liquidity, no trading
        strat.on_bar(bar, allow_entries=False)
    last = history[-1].time
    log.info("Warmed up on %d bars up to %s. %d active zones.", len(history), last, len(strat.zones.active()))
    for line in strat.log[-10:]:
        log.info("history: %s", line)
    strat.log.clear()

    risk = RiskManager(cfg, strat.clock, broker.equity())
    in_pos = broker.has_position()
    equity_at_open = risk.equity
    try:
        while True:
            if STOP_FILE.exists():
                log.warning("STOP file found. Stopping (open positions keep their stop and target).")
                return
            try:
                bars = [b for b in feed.closed_bars(10) if b.time > last]
            except BrokerError as e:
                log.error("Data error: %s", e)
                time.sleep(cfg.broker.poll_seconds)
                continue
            for k, bar in enumerate(bars):
                last = bar.time
                broker.on_bar(bar)
                risk.set_equity(broker.equity(), bar.time)
                now_in_pos = broker.has_position()
                if in_pos and not now_in_pos:
                    pnl = risk.equity - equity_at_open
                    risk.losses_in_row = risk.losses_in_row + 1 if pnl < 0 else 0
                    log.info("Position closed, P&L %+.2f. Equity %.2f", pnl, risk.equity)
                in_pos = now_in_pos
                if in_pos and strat.clock.should_flatten(bar.time):
                    log.info("Flatten time: closing position")
                    broker.flatten()
                fresh = k == len(bars) - 1  # never act on a bar we only caught up on
                allow = fresh and not in_pos and not strat.clock.should_flatten(bar.time) and risk.can_trade(bar.time)
                if fresh and not in_pos and risk.reason:
                    log.debug("No new trades: %s", risk.reason)
                signal = strat.on_bar(bar, allow_entries=allow)
                for line in strat.log:
                    log.info(line)
                strat.log.clear()
                if not signal:
                    continue
                qty = risk.size(signal)
                if qty <= 0:
                    log.warning("Signal skipped: size rounds to 0 at this risk")
                    continue
                try:
                    oid = broker.place_bracket(signal, qty)
                except BrokerError as e:
                    log.error("Order failed: %s", e)
                    continue
                risk.on_open(bar.time)
                equity_at_open = risk.equity
                in_pos = True
                log.info("ORDER %s %s x%g stop %g target %g (id %s)", signal.side, cfg.instrument.symbol,
                         qty, signal.stop, signal.target, oid)
            time.sleep(cfg.broker.poll_seconds)
    except KeyboardInterrupt:
        log.info("Stopped by user (open positions keep their stop and target).")
    finally:
        broker.disconnect()
        if feed is not broker:
            getattr(feed, "disconnect", lambda: None)()
