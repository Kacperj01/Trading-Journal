"""Replay history bar by bar through the same Strategy and RiskManager the live bot uses."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .config import Config
from .models import LONG, Bar, Signal, Trade
from .risk import RiskManager
from .strategy import Strategy


def trade_pnl(cfg: Config, trade: Trade, exit_price: float) -> float:
    ins = cfg.instrument
    move = (exit_price - trade.entry) if trade.side == LONG else (trade.entry - exit_price)
    return move / ins.tick_size * ins.tick_value * trade.qty - ins.commission_per_unit * trade.qty


class Position:
    """An open trade with a stop and a target, filled against bars."""

    def __init__(self, cfg: Config, signal: Signal, qty: float, slippage: float):
        entry = signal.entry + slippage if signal.side == LONG else signal.entry - slippage
        self.cfg = cfg
        self.trade = Trade(signal.side, signal.time, entry, signal.stop, signal.target, qty, signal.reason)
        self.slippage = slippage

    def check(self, bar: Bar) -> bool:
        """Returns True when the trade closed on this bar. If stop and target are
        both inside one bar we assume the stop was hit first (pessimistic)."""
        t = self.trade
        if t.side == LONG:
            if bar.low <= t.stop:
                return self.close(bar, min(t.stop, bar.open) - self.slippage, "stop")
            if bar.high >= t.target:
                return self.close(bar, max(t.target, bar.open), "target")
        else:
            if bar.high >= t.stop:
                return self.close(bar, max(t.stop, bar.open) + self.slippage, "stop")
            if bar.low <= t.target:
                return self.close(bar, min(t.target, bar.open), "target")
        return False

    def close(self, bar: Bar, price: float, why: str) -> bool:
        t = self.trade
        t.exit_time, t.exit, t.exit_reason = bar.time, price, why
        t.pnl = trade_pnl(self.cfg, t, price)
        return True


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    start_equity: float = 0.0
    end_equity: float = 0.0
    max_drawdown_pct: float = 0.0

    def summary(self) -> str:
        n = len(self.trades)
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in losses)
        pf = gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0
        avg_r = sum(t.r_multiple for t in self.trades) / n if n else 0.0
        lines = [
            f"Trades:         {n}",
            f"Win rate:       {len(wins) / n * 100:.1f}%" if n else "Win rate:       -",
            f"Average R:      {avg_r:+.2f}",
            f"Profit factor:  {pf:.2f}",
            f"Net P&L:        {self.end_equity - self.start_equity:+,.2f}",
            f"Return:         {(self.end_equity / self.start_equity - 1) * 100:+.2f}%",
            f"Max drawdown:   {self.max_drawdown_pct:.2f}%",
        ]
        return "\n".join(lines)


def run_backtest(cfg: Config, bars: Iterable[Bar]) -> Result:
    strat = Strategy(cfg)
    risk = RiskManager(cfg, strat.clock, cfg.risk.account_size)
    slip = cfg.instrument.slippage_ticks * cfg.instrument.tick_size
    pos: Optional[Position] = None
    result = Result(start_equity=risk.equity)
    peak = risk.equity
    for bar in bars:
        if pos is not None:
            closed = pos.check(bar)
            if not closed and strat.clock.should_flatten(bar.time):
                closed = pos.close(bar, bar.close, "end of day")
            if closed:
                risk.on_close(pos.trade)
                result.trades.append(pos.trade)
                pos = None
                peak = max(peak, risk.equity)
                result.max_drawdown_pct = max(result.max_drawdown_pct, (peak - risk.equity) / peak * 100)
        allow = pos is None and risk.can_trade(bar.time) and not strat.clock.should_flatten(bar.time)
        signal = strat.on_bar(bar, allow_entries=allow)
        if signal:
            qty = risk.size(signal)
            if qty <= 0:
                strat.log.append(f"{bar.time.isoformat()} skip signal: position size rounds to 0")
                continue
            pos = Position(cfg, signal, qty, slip)
            risk.on_open(bar.time)
    if pos is not None:  # close anything still open at the last price
        pos.close(bar, bar.close, "end of data")
        risk.on_close(pos.trade)
        result.trades.append(pos.trade)
    result.end_equity = risk.equity
    result.log = strat.log
    return result


def write_trades_csv(path: str, cfg: Config, trades: list[Trade]) -> None:
    """Columns line up with the ELEV8 journal import (date, symbol, side, entry, exit, ...)."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Exit date", "Symbol", "Side", "Entry", "Exit", "Stop", "Target",
                    "Size", "P&L", "R", "Setup", "Exit reason"])
        for t in trades:
            w.writerow([t.entry_time.isoformat(), t.exit_time.isoformat() if t.exit_time else "",
                        cfg.instrument.symbol, "Long" if t.side == LONG else "Short",
                        f"{t.entry:.6g}", f"{t.exit:.6g}" if t.exit is not None else "",
                        f"{t.stop:.6g}", f"{t.target:.6g}", f"{t.qty:g}", f"{t.pnl:.2f}",
                        f"{t.r_multiple:.2f}", t.reason, t.exit_reason])
