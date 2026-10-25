"""Load bars from CSV (MT5, NinjaTrader and TradingView exports work) or generate test data."""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Iterator
from zoneinfo import ZoneInfo

from .indicators import Aggregator
from .models import Bar

_ALIASES = {
    "time": ("time", "datetime", "date", "timestamp", "<date>", "gmt time", "local time"),
    "clock": ("<time>",),
    "open": ("open", "<open>", "o"),
    "high": ("high", "<high>", "h"),
    "low": ("low", "<low>", "l"),
    "close": ("close", "<close>", "c", "last"),
    "volume": ("volume", "<tickvol>", "<vol>", "tick volume", "vol", "v"),
}
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
            "%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
            "%Y%m%d %H%M%S")


def _parse_time(text: str, tz) -> datetime:
    text = text.strip()
    if text.replace(".", "", 1).isdigit():
        value = float(text)
        if value > 1e11:  # milliseconds
            value /= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _FORMATS:
            try:
                dt = datetime.strptime(text.split(" GMT")[0], fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Could not read time '{text}'")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def load_csv(path: str, tz: str = "UTC") -> list[Bar]:
    """Read OHLC bars. Times without a timezone are read in `tz` (your export's timezone)."""
    zone = timezone.utc if tz.upper() == "UTC" else ZoneInfo(tz)
    with open(path, newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        rows = csv.reader(fh, dialect)
        header = [h.strip().lower() for h in next(rows)]
        col = {}
        for key, names in _ALIASES.items():
            for n in names:
                if n in header:
                    col[key] = header.index(n)
                    break
        missing = [k for k in ("time", "open", "high", "low", "close") if k not in col]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}. Found: {header}")
        bars = []
        for row in rows:
            if not row or not row[col["time"]].strip():
                continue
            stamp = row[col["time"]]
            if "clock" in col:
                stamp += " " + row[col["clock"]]
            bars.append(Bar(
                _parse_time(stamp, zone),
                float(row[col["open"]]), float(row[col["high"]]), float(row[col["low"]]), float(row[col["close"]]),
                float(row[col["volume"]]) if "volume" in col and row[col["volume"]] else 0.0,
            ))
    bars.sort(key=lambda b: b.time)
    return bars


def resample(bars: list[Bar], from_minutes: int, to_minutes: int) -> list[Bar]:
    if from_minutes == to_minutes:
        return bars
    if to_minutes % from_minutes:
        raise ValueError("Can only resample to a multiple of the data timeframe")
    agg = Aggregator(to_minutes)
    out: list[Bar] = []
    for b in bars:
        out.extend(agg.update(b, from_minutes))
    return out


def detect_minutes(bars: list[Bar]) -> int:
    gaps = sorted((b.time - a.time).total_seconds() / 60 for a, b in zip(bars, bars[1:]) if b.time > a.time)
    return int(gaps[len(gaps) // 2]) if gaps else 1


def synthetic(days: int = 60, minutes: int = 5, start_price: float = 1.0850, seed: int = 7,
              vol: float = 0.00035) -> list[Bar]:
    """Random-walk prices with session-shaped volatility and trends. For testing only:
    results on this say nothing about how the strategy does on real markets."""
    rng = random.Random(seed)
    ny = ZoneInfo("America/New_York")
    t = datetime(2026, 1, 4, 17, 0, tzinfo=ny).astimezone(timezone.utc)
    end = t + timedelta(days=days)
    price, drift, bars = start_price, 0.0, []
    while t < end:
        local = t.astimezone(ny)
        weekend = local.weekday() == 5 or (local.weekday() == 4 and local.hour >= 17) or (local.weekday() == 6 and local.hour < 17)
        if not weekend:
            h = local.hour
            mult = 1.8 if 2 <= h < 5 or 7 <= h < 11 else 0.6 if 17 <= h or h < 2 else 1.0
            if rng.random() < 0.02:
                drift = rng.gauss(0, vol * 0.25)
            sigma = vol * mult * math.sqrt(minutes / 5)
            o = price
            steps = [o]
            for _ in range(4):
                steps.append(steps[-1] + drift / 4 + rng.gauss(0, sigma / 2))
            c = steps[-1]
            hi = max(steps) + abs(rng.gauss(0, sigma * 0.3))
            lo = min(steps) - abs(rng.gauss(0, sigma * 0.3))
            bars.append(Bar(t, round(o, 5), round(hi, 5), round(lo, 5), round(c, 5), rng.randint(50, 500)))
            price = c
        t += timedelta(minutes=minutes)
    return bars
