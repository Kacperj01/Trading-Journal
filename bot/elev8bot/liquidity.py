"""Liquidity pools: previous day high/low and the high/low of each session."""
from __future__ import annotations

from datetime import date
from typing import Optional

from .models import Bar, Level
from .sessions import SessionClock


class LiquidityBook:
    def __init__(self, clock: SessionClock):
        self.clock = clock
        self.day: Optional[date] = None
        self.day_high = float("-inf")
        self.day_low = float("inf")
        self.session: Optional[str] = None
        self.session_high = float("-inf")
        self.session_low = float("inf")
        self.levels: dict[str, Level] = {}  # name -> latest level with that name

    def _roll(self, bar: Bar) -> None:
        day = self.clock.trading_day(bar.time)
        session = self.clock.session(bar.time)
        if self.session is not None and session != self.session:
            title = {"asia": "Asia", "london": "London", "newyork": "New York"}[self.session]
            self.levels[f"{title} high"] = Level(f"{title} high", self.session_high, "high")
            self.levels[f"{title} low"] = Level(f"{title} low", self.session_low, "low")
        if session != self.session:
            self.session = session
            self.session_high, self.session_low = float("-inf"), float("inf")
        if self.day is not None and day != self.day:
            self.levels["PDH"] = Level("PDH", self.day_high, "high")
            self.levels["PDL"] = Level("PDL", self.day_low, "low")
        if day != self.day:
            self.day = day
            self.day_high, self.day_low = float("-inf"), float("inf")

    def update(self, bar: Bar) -> list[Level]:
        """Feed one bar. Returns the levels this bar swept (traded through)."""
        self._roll(bar)
        swept = []
        for level in self.levels.values():
            if level.taken:
                continue
            if (level.kind == "high" and bar.high > level.price) or (level.kind == "low" and bar.low < level.price):
                level.taken = True
                swept.append(level)
        self.day_high = max(self.day_high, bar.high)
        self.day_low = min(self.day_low, bar.low)
        if self.session is not None:
            self.session_high = max(self.session_high, bar.high)
            self.session_low = min(self.session_low, bar.low)
        return swept

    def untaken(self, kind: str) -> list[Level]:
        return [lv for lv in self.levels.values() if lv.kind == kind and not lv.taken]
