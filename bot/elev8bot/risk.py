"""Position sizing and the hard limits that stop the bot trading."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Optional

from .config import Config
from .models import Signal, Trade
from .sessions import SessionClock


class RiskManager:
    def __init__(self, cfg: Config, clock: SessionClock, equity: float):
        self.cfg = cfg
        self.clock = clock
        self.start_equity = equity
        self.peak = equity
        self.equity = equity
        self.day: Optional[date] = None
        self.day_start_equity = equity
        self.trades_today = 0
        self.losses_in_row = 0
        self.halted_for_good = False
        self.reason = ""

    def _roll(self, when: datetime) -> None:
        day = self.clock.trading_day(when)
        if day != self.day:
            self.day = day
            self.day_start_equity = self.equity
            self.trades_today = 0
            self.losses_in_row = 0

    def set_equity(self, equity: float, when: datetime) -> None:
        """Live trading: sync with the account balance from the broker."""
        self._roll(when)
        self.equity = equity
        self.peak = max(self.peak, equity)

    def can_trade(self, when: datetime) -> bool:
        self._roll(when)
        r = self.cfg.risk
        if self.halted_for_good:
            return False
        drawdown = (self.peak - self.equity) / self.peak * 100 if self.peak else 0
        if drawdown >= r.max_drawdown_pct:
            self.halted_for_good = True
            self.reason = f"max drawdown {drawdown:.1f}% reached; bot halted"
            return False
        day_loss = (self.day_start_equity - self.equity) / self.day_start_equity * 100 if self.day_start_equity else 0
        if day_loss >= r.max_daily_loss_pct:
            self.reason = f"daily loss limit hit ({day_loss:.1f}%)"
            return False
        if self.trades_today >= r.max_trades_per_day:
            self.reason = "max trades for the day"
            return False
        if self.losses_in_row >= r.max_consecutive_losses:
            self.reason = f"{self.losses_in_row} losses in a row today"
            return False
        self.reason = ""
        return True

    def size(self, signal: Signal) -> float:
        """Contracts / lots so a stop-out loses about risk_per_trade_pct of equity."""
        ins = self.cfg.instrument
        risk_money = self.equity * self.cfg.risk.risk_per_trade_pct / 100
        ticks = signal.risk / ins.tick_size
        per_unit = ticks * ins.tick_value + ins.commission_per_unit
        if per_unit <= 0:
            return 0.0
        qty = math.floor(risk_money / per_unit / ins.qty_step + 1e-9) * ins.qty_step
        qty = min(round(qty, 8), ins.max_qty)
        return qty if qty >= ins.min_qty else 0.0

    def on_open(self, when: datetime) -> None:
        self._roll(when)
        self.trades_today += 1

    def on_close(self, trade: Trade) -> None:
        self.equity += trade.pnl
        self.peak = max(self.peak, self.equity)
        self.losses_in_row = self.losses_in_row + 1 if trade.pnl < 0 else 0
