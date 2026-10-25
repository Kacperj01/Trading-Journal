"""Small incremental helpers: ATR, swing points, bar aggregation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .models import Bar, Swing


class ATR:
    """Wilder ATR, updated one bar at a time."""

    def __init__(self, length: int):
        self.length = length
        self.value: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._seed: list[float] = []

    def update(self, bar: Bar) -> Optional[float]:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(bar.high - bar.low, abs(bar.high - self._prev_close), abs(bar.low - self._prev_close))
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) >= self.length:
                self.value = sum(self._seed) / len(self._seed)
        else:
            self.value = (self.value * (self.length - 1) + tr) / self.length
        return self.value


class SwingTracker:
    """Finds swing highs/lows with `length` bars on each side.

    A swing at bar i is only known once bar i+length has closed, so there is no
    look-ahead: `update` returns swings as they become confirmed.
    """

    def __init__(self, length: int):
        self.length = length
        self.bars: list[Bar] = []
        self.highs: list[Swing] = []
        self.lows: list[Swing] = []

    def update(self, bar: Bar) -> list[Swing]:
        self.bars.append(bar)
        n = self.length
        i = len(self.bars) - 1 - n
        if i < n:
            return []
        window = self.bars[i - n : i + n + 1]
        pivot = self.bars[i]
        found = []
        if pivot.high == max(b.high for b in window) and all(b.high < pivot.high for b in window[n + 1 :]):
            s = Swing(i, pivot.time, pivot.high, "high")
            self.highs.append(s)
            found.append(s)
        if pivot.low == min(b.low for b in window) and all(b.low > pivot.low for b in window[n + 1 :]):
            s = Swing(i, pivot.time, pivot.low, "low")
            self.lows.append(s)
            found.append(s)
        # Mark older swings that this bar traded through.
        for s in self.highs[-50:]:
            if not s.taken and s.index < len(self.bars) - 1 and bar.high > s.price:
                s.taken = True
        for s in self.lows[-50:]:
            if not s.taken and s.index < len(self.bars) - 1 and bar.low < s.price:
                s.taken = True
        return found

    def last_high(self) -> Optional[Swing]:
        return self.highs[-1] if self.highs else None

    def last_low(self) -> Optional[Swing]:
        return self.lows[-1] if self.lows else None


class Aggregator:
    """Builds higher-timeframe bars from lower-timeframe bars."""

    def __init__(self, minutes: int):
        self.minutes = minutes
        self.current: Optional[Bar] = None
        self._bucket: Optional[datetime] = None

    def _bucket_of(self, when: datetime) -> datetime:
        epoch_min = int(when.timestamp() // 60)
        start = epoch_min - epoch_min % self.minutes
        return datetime.fromtimestamp(start * 60, tz=when.tzinfo)

    def update(self, bar: Bar, ltf_minutes: int) -> list[Bar]:
        """Feed one LTF bar. Returns any HTF bars that are now complete."""
        bucket = self._bucket_of(bar.time)
        done: list[Bar] = []
        if self.current is not None and bucket != self._bucket:
            done.append(self.current)  # data gap: previous bucket never got its last bar
            self.current = None
        if self.current is None:
            self._bucket = bucket
            self.current = Bar(bucket, bar.open, bar.high, bar.low, bar.close, bar.volume)
        else:
            c = self.current
            self.current = Bar(c.time, c.open, max(c.high, bar.high), min(c.low, bar.low), bar.close, c.volume + bar.volume)
        # Close the bucket as soon as its last LTF bar arrives, so HTF zones are not a bar late.
        if bar.time + timedelta(minutes=ltf_minutes) >= bucket + timedelta(minutes=self.minutes):
            done.append(self.current)
            self.current, self._bucket = None, None
        return done
