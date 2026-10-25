"""Paper broker: fills against live bars, no real orders. Use this before going live."""
from __future__ import annotations

from typing import Optional

from ..backtest import Position
from ..config import Config
from ..models import Bar, Signal, Trade
from .base import Broker


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.balance = cfg.risk.account_size
        self.pos: Optional[Position] = None
        self.closed: list[Trade] = []
        self.last_bar: Optional[Bar] = None
        self._n = 0

    def connect(self) -> None:
        pass

    def equity(self) -> float:
        return self.balance

    def has_position(self) -> bool:
        return self.pos is not None

    def place_bracket(self, signal: Signal, qty: float) -> str:
        slip = self.cfg.instrument.slippage_ticks * self.cfg.instrument.tick_size
        self.pos = Position(self.cfg, signal, qty, slip)
        self._n += 1
        return f"paper-{self._n}"

    def on_bar(self, bar: Bar) -> None:
        self.last_bar = bar
        if self.pos and self.pos.trade.entry_time < bar.time and self.pos.check(bar):
            self._book()

    def flatten(self) -> None:
        if self.pos and self.last_bar:
            self.pos.close(self.last_bar, self.last_bar.close, "flatten")
            self._book()

    def _book(self) -> None:
        self.balance += self.pos.trade.pnl
        self.closed.append(self.pos.trade)
        self.pos = None
