"""Supply and demand zones on the higher timeframe.

Not every base is a zone. A demand zone is only kept when the move up out of it
broke structure (closed above the last swing high), was a strong displacement
(several ATR), left a fair value gap, and the zone itself is tight. Supply is the
mirror image. Zones die when a close goes through their far edge, when a trade
has been taken from them, or when they get too old.
"""
from __future__ import annotations

from .config import ZoneConfig
from .indicators import ATR, SwingTracker
from .models import LONG, SHORT, Bar, Level, Zone


class ZoneFinder:
    def __init__(self, cfg: ZoneConfig, swing_length: int):
        self.cfg = cfg
        self.bars: list[Bar] = []
        self.atr = ATR(cfg.atr_length)
        self.swings = SwingTracker(swing_length)
        self.zones: list[Zone] = []
        self.rejected: list[tuple] = []  # (time, side, why) for debugging / reports
        self._broken_highs: set[int] = set()
        self._broken_lows: set[int] = set()

    def update(self, bar: Bar, key_levels: list[Level] | None = None) -> list[Zone]:
        """Feed one finished HTF bar. Returns new valid zones."""
        self.bars.append(bar)
        atr = self.atr.update(bar)
        self.swings.update(bar)
        j = len(self.bars) - 1
        self._age_and_break(bar, j)
        if atr is None:
            return []
        new = []
        sh = self.swings.last_high()
        if sh and sh.index not in self._broken_highs and bar.close > sh.price:
            self._broken_highs.add(sh.index)
            z = self._build(LONG, sh.index, j, atr, key_levels or [])
            if z:
                new.append(z)
        sl = self.swings.last_low()
        if sl and sl.index not in self._broken_lows and bar.close < sl.price:
            self._broken_lows.add(sl.index)
            z = self._build(SHORT, sl.index, j, atr, key_levels or [])
            if z:
                new.append(z)
        self.zones.extend(new)
        return new

    def _age_and_break(self, bar: Bar, j: int) -> None:
        for z in self.zones:
            if not z.active:
                continue
            if j - z.created_index > self.cfg.max_age_bars:
                z.broken = True
            elif z.side == LONG and bar.close < z.bottom:
                z.broken = True
            elif z.side == SHORT and bar.close > z.top:
                z.broken = True

    def _build(self, side: str, swing_index: int, j: int, atr: float, key_levels: list[Level]) -> Zone | None:
        bars, cfg = self.bars, self.cfg
        leg = range(swing_index + 1, j + 1)
        if not leg:
            return None
        if side == LONG:
            origin = min(leg, key=lambda k: bars[k].low)
            opposite = lambda b: b.close < b.open  # last down candle before the rally
        else:
            origin = max(leg, key=lambda k: bars[k].high)
            opposite = lambda b: b.close > b.open  # last up candle before the drop
        base = origin
        for k in range(origin, max(origin - 3, -1), -1):
            if opposite(bars[k]):
                base = k
                break
        if side == LONG:
            bottom = min(bars[base].low, bars[origin].low)
            top = bars[base].high
            displacement = bars[j].close - bottom
        else:
            top = max(bars[base].high, bars[origin].high)
            bottom = bars[base].low
            displacement = top - bars[j].close

        reasons = ["broke structure"]
        why_not = None
        if displacement < cfg.displacement_atr * atr:
            why_not = f"weak move ({displacement / atr:.1f} ATR)"
        elif top - bottom > cfg.max_height_atr * atr:
            why_not = f"zone too tall ({(top - bottom) / atr:.1f} ATR)"
        else:
            reasons.append(f"displacement {displacement / atr:.1f} ATR")
            fvg = self._has_fvg(side, origin, j)
            if cfg.require_fvg and not fvg:
                why_not = "no fair value gap"
            elif fvg:
                reasons.append("left a fair value gap")
        if why_not is None:
            swept = self._swept_liquidity(side, origin, key_levels)
            if swept:
                reasons.append(f"swept {swept} first")
            elif cfg.require_liquidity_origin:
                why_not = "did not sweep liquidity"
        if why_not:
            self.rejected.append((bars[j].time, side, why_not))
            return None
        for z in self.zones:  # same zone found twice
            if z.active and z.side == side and abs(z.top - top) < 1e-12 and abs(z.bottom - bottom) < 1e-12:
                return None
        return Zone(side, top, bottom, bars[j].time, j, reasons)

    def _has_fvg(self, side: str, origin: int, j: int) -> bool:
        b = self.bars
        for m in range(origin + 1, j):
            if side == LONG and b[m - 1].high < b[m + 1].low:
                return True
            if side == SHORT and b[m - 1].low > b[m + 1].high:
                return True
        return False

    def _swept_liquidity(self, side: str, origin: int, key_levels: list[Level]) -> str | None:
        b = self.bars[origin]
        if side == LONG:
            for s in self.swings.lows:
                if s.index < origin and b.low < s.price < b.high:
                    return "a swing low"
            for lv in key_levels:
                if lv.kind == "low" and b.low < lv.price < b.high:
                    return lv.name
        else:
            for s in self.swings.highs:
                if s.index < origin and b.low < s.price < b.high:
                    return "a swing high"
            for lv in key_levels:
                if lv.kind == "high" and b.low < lv.price < b.high:
                    return lv.name
        return None

    def active(self, side: str | None = None) -> list[Zone]:
        return [z for z in self.zones if z.active and (side is None or z.side == side)]
