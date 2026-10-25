"""The trading rules.

1. Higher timeframe: find valid supply / demand zones (see zones.py).
2. Track liquidity: previous day high/low and Asia / London / New York highs and lows.
3. When price taps a valid zone (or sweeps a key level), do NOT enter yet. Arm a setup.
4. On the entry timeframe wait for confirmation: a liquidity sweep and/or a
   break of structure in the direction of the trade.
5. Enter only inside the allowed sessions. Stop goes beyond the swept extreme.
   Target is the next untaken liquidity pool, if it pays at least min_rr.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import Config
from .indicators import ATR, Aggregator, SwingTracker
from .liquidity import LiquidityBook
from .models import LONG, SHORT, Bar, Level, Signal, Zone
from .sessions import SessionClock
from .zones import ZoneFinder


@dataclass
class Setup:
    side: str
    armed_at: int  # LTF bar index
    extreme: float  # lowest low (long) / highest high (short) since armed
    extreme_index: int
    source: str  # human readable, e.g. "demand zone 1.0841-1.0852"
    zone: Optional[Zone] = None
    swept: list = field(default_factory=list)  # names of liquidity swept since armed
    swept_price: Optional[float] = None


class Strategy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        tf = cfg.timeframes
        self.clock = SessionClock(cfg.sessions)
        self.book = LiquidityBook(self.clock)
        self.swings = SwingTracker(tf.swing_length)
        self.atr = ATR(cfg.zones.atr_length)
        self.agg = Aggregator(tf.htf_minutes)
        self.zones = ZoneFinder(cfg.zones, tf.htf_swing_length)
        self.setups: list[Setup] = []
        self.i = -1
        self.log: list[str] = []

    # ------------------------------------------------------------------ helpers
    def _note(self, bar: Bar, text: str) -> None:
        self.log.append(f"{bar.time.isoformat()} {text}")

    def _ltf_sweeps(self, bar: Bar) -> tuple[list[str], dict]:
        """Entry-timeframe swing highs/lows this bar takes out (checked before updating)."""
        names, price = [], {}
        lows = [s for s in self.swings.lows[-50:] if not s.taken and bar.low < s.price]
        highs = [s for s in self.swings.highs[-50:] if not s.taken and bar.high > s.price]
        if lows:
            names.append("swing low")
            price["low"] = min(s.price for s in lows)
        if highs:
            names.append("swing high")
            price["high"] = max(s.price for s in highs)
        return names, price

    # ---------------------------------------------------------------- main loop
    def on_bar(self, bar: Bar, allow_entries: bool = True) -> Optional[Signal]:
        """Feed one closed entry-timeframe bar. Returns a Signal or None."""
        self.i += 1
        cfg = self.cfg

        for htf_bar in self.agg.update(bar, cfg.timeframes.ltf_minutes):
            for z in self.zones.update(htf_bar, list(self.book.levels.values())):
                kind = "demand" if z.side == LONG else "supply"
                self._note(bar, f"new {kind} zone {z.bottom:g}-{z.top:g}: {', '.join(z.reasons)}")

        ltf_sweep_names, ltf_sweep_price = self._ltf_sweeps(bar)
        key_swept = self.book.update(bar)
        self.swings.update(bar)
        atr = self.atr.update(bar)

        swept_lows = [lv for lv in key_swept if lv.kind == "low"]
        swept_highs = [lv for lv in key_swept if lv.kind == "high"]

        self._arm(bar, swept_lows, swept_highs)

        signal = None
        for setup in list(self.setups):
            if self.i - setup.armed_at > cfg.entry.setup_timeout_bars or (setup.zone and setup.zone.broken):
                self.setups.remove(setup)
                continue
            long = setup.side == LONG
            if (long and bar.low < setup.extreme) or (not long and bar.high > setup.extreme):
                setup.extreme = bar.low if long else bar.high
                setup.extreme_index = self.i
            # Liquidity swept since the setup armed?
            lv_list = swept_lows if long else swept_highs
            if lv_list:
                setup.swept += [lv.name for lv in lv_list]
                setup.swept_price = min(lv.price for lv in lv_list) if long else max(lv.price for lv in lv_list)
            side_key = "low" if long else "high"
            if side_key in ltf_sweep_price:
                setup.swept.append(f"entry-timeframe swing {side_key}")
                setup.swept_price = ltf_sweep_price[side_key]

            if signal or not allow_entries or atr is None:
                continue
            if self._confirmed(setup, bar):
                signal = self._make_signal(setup, bar, atr)
                if signal:
                    self.setups = [s for s in self.setups if s.side != setup.side]
                    if setup.zone and cfg.zones.one_trade_per_zone:
                        setup.zone.used = True
        return signal

    def _arm(self, bar: Bar, swept_lows: list[Level], swept_highs: list[Level]) -> None:
        armed_zones = {id(s.zone) for s in self.setups if s.zone}
        for z in self.zones.active():
            if id(z) in armed_zones or z.touched or not z.contains(bar.low, bar.high):
                continue
            z.touched = True
            kind = "demand" if z.side == LONG else "supply"
            extreme = bar.low if z.side == LONG else bar.high
            self.setups.append(Setup(z.side, self.i, extreme, self.i, f"{kind} zone {z.bottom:g}-{z.top:g}", z))
            self._note(bar, f"price tapped {kind} zone {z.bottom:g}-{z.top:g}; waiting for confirmation")
        if self.cfg.entry.trade_key_level_sweeps:
            for side, levels in ((LONG, swept_lows), (SHORT, swept_highs)):
                if not levels or any(s.side == side and s.zone is None for s in self.setups):
                    continue
                names = [lv.name for lv in levels]
                extreme = bar.low if side == LONG else bar.high
                price = min(lv.price for lv in levels) if side == LONG else max(lv.price for lv in levels)
                st = Setup(side, self.i, extreme, self.i, f"sweep of {' + '.join(names)}", None, names, price)
                self.setups.append(st)
                self._note(bar, f"{' + '.join(names)} swept; waiting for break of structure")

    def _confirmed(self, setup: Setup, bar: Bar) -> bool:
        mode = self.cfg.entry.confirmation
        long = setup.side == LONG
        # Break of structure: close beyond the last swing that formed before the extreme.
        pool = self.swings.highs if long else self.swings.lows
        ref = next((s for s in reversed(pool) if s.index < setup.extreme_index), None)
        bos = False
        if ref is not None:
            bos = bar.close > ref.price if long else bar.close < ref.price
        swept = bool(setup.swept)
        if mode == "bos":
            return bos
        if mode == "sweep_then_bos":
            return swept and bos
        # mode == "sweep": swept and closed back on the right side, with a candle in our direction
        if not swept or setup.swept_price is None:
            return False
        if long:
            return bar.close > setup.swept_price and bar.close > bar.open
        return bar.close < setup.swept_price and bar.close < bar.open

    def _make_signal(self, setup: Setup, bar: Bar, atr: float) -> Optional[Signal]:
        cfg = self.cfg
        long = setup.side == LONG
        if not self.clock.can_enter(bar.time):
            return None  # confirmation outside the allowed sessions; keep waiting
        buffer = cfg.entry.stop_buffer_ticks * cfg.instrument.tick_size
        entry = bar.close
        stop = setup.extreme - buffer if long else setup.extreme + buffer
        risk = entry - stop if long else stop - entry
        if risk <= 0:
            return None
        if risk > cfg.entry.max_stop_atr * atr:
            self._note(bar, f"skip {setup.source}: stop too wide ({risk / atr:.1f} ATR)")
            self.setups.remove(setup)
            return None
        target, target_name = self._target(long, entry, risk)
        if target is None:
            self._note(bar, f"skip {setup.source}: {target_name}")
            self.setups.remove(setup)
            return None
        why = f"{setup.source}"
        if setup.swept:
            why += f"; swept {', '.join(dict.fromkeys(setup.swept))}"
        why += f"; break of structure; target {target_name}"
        if cfg.entry.confirmation == "sweep":
            why = why.replace("; break of structure", "; reclaim")
        sig = Signal(setup.side, entry, stop, target, bar.time, why, setup.zone)
        self._note(bar, f"SIGNAL {setup.side} @ {entry:g} stop {stop:g} target {target:g} ({sig.rr:.1f}R): {why}")
        return sig

    def _target(self, long: bool, entry: float, risk: float) -> tuple[Optional[float], str]:
        e = self.cfg.entry
        if e.target_mode == "fixed":
            return (entry + e.fixed_rr * risk if long else entry - e.fixed_rr * risk), f"{e.fixed_rr:g}R"
        candidates: list[tuple[float, str]] = []
        kind = "high" if long else "low"
        for lv in self.book.untaken(kind):
            candidates.append((lv.price, lv.name))
        for s in (self.zones.swings.highs if long else self.zones.swings.lows)[-20:]:
            if not s.taken:
                candidates.append((s.price, "higher-timeframe swing " + kind))
        for z in self.zones.active(SHORT if long else LONG):
            candidates.append(((z.bottom, "supply zone") if long else (z.top, "demand zone")))
        ahead = [(p, n) for p, n in candidates if (p > entry if long else p < entry)]
        if not ahead:
            t = entry + e.fixed_rr * risk if long else entry - e.fixed_rr * risk
            return t, f"{e.fixed_rr:g}R (no liquidity ahead)"
        price, name = min(ahead, key=lambda c: abs(c[0] - entry))
        rr = abs(price - entry) / risk
        if rr < e.min_rr:
            return None, f"next liquidity ({name}) only {rr:.1f}R away"
        if rr > e.max_rr:
            price = entry + e.max_rr * risk if long else entry - e.max_rr * risk
            name += f", capped at {e.max_rr:g}R"
        return price, name
