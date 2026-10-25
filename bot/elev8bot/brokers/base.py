"""What every broker connection must provide."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Bar, Signal


class BrokerError(RuntimeError):
    pass


class DataFeed(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def closed_bars(self, count: int) -> list[Bar]:
        """The last `count` CLOSED entry-timeframe bars, oldest first, times in UTC."""


class Broker(ABC):
    name = "broker"

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def has_position(self) -> bool: ...

    @abstractmethod
    def place_bracket(self, signal: Signal, qty: float) -> str:
        """Market entry with an attached stop loss and take profit. Returns an order id."""

    @abstractmethod
    def flatten(self) -> None:
        """Close any open position and cancel working orders for the bot's symbol."""

    def on_bar(self, bar: Bar) -> None:
        """Called with every new bar (the paper broker uses it to fill orders)."""

    def disconnect(self) -> None:
        pass
