"""Plain data types shared by the strategy, backtester and brokers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class Bar:
    time: datetime  # bar open time, timezone-aware (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Swing:
    index: int  # index of the swing bar in its own timeframe
    time: datetime
    price: float
    kind: str  # "high" or "low"
    taken: bool = False  # price has traded through it since


@dataclass
class Zone:
    """A supply (short) or demand (long) zone found on the higher timeframe."""

    side: str  # LONG for demand, SHORT for supply
    top: float
    bottom: float
    created: datetime
    created_index: int  # HTF bar index when the zone was confirmed
    reasons: list = field(default_factory=list)
    touched: bool = False  # price has traded into it
    used: bool = False  # a trade was taken from it
    broken: bool = False  # a close went through the far edge

    @property
    def active(self) -> bool:
        return not (self.used or self.broken)

    def contains(self, low: float, high: float) -> bool:
        return low <= self.top and high >= self.bottom


@dataclass
class Level:
    """A liquidity pool: previous day high/low, a session high/low, or a swing."""

    name: str  # e.g. "PDH", "PDL", "Asia high", "London low"
    price: float
    kind: str  # "high" or "low"
    taken: bool = False


@dataclass
class Signal:
    side: str
    entry: float
    stop: float
    target: float
    time: datetime
    reason: str
    zone: Optional[Zone] = None

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr(self) -> float:
        return abs(self.target - self.entry) / self.risk if self.risk else 0.0


@dataclass
class Trade:
    side: str
    entry_time: datetime
    entry: float
    stop: float
    target: float
    qty: float
    reason: str
    exit_time: Optional[datetime] = None
    exit: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0  # in account currency, after costs

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry - self.stop)
        if not risk or self.exit is None:
            return 0.0
        move = (self.exit - self.entry) if self.side == LONG else (self.entry - self.exit)
        return move / risk
