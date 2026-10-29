import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from elev8bot.backtest import Position, run_backtest
from elev8bot.config import Config, load_config
from elev8bot.data import load_csv, resample, synthetic
from elev8bot.indicators import Aggregator, SwingTracker
from elev8bot.liquidity import LiquidityBook
from elev8bot.models import LONG, SHORT, Bar, Signal
from elev8bot.risk import RiskManager
from elev8bot.sessions import SessionClock
from elev8bot.strategy import Strategy
from elev8bot.zones import ZoneFinder

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]


def ny(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY).astimezone(timezone.utc)


def bar(t, o, h, l, c):
    return Bar(t, o, h, l, c)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = SessionClock(Config().sessions)

    def test_sessions_follow_new_york_time_through_daylight_saving(self):
        self.assertEqual(self.clock.session(ny(2026, 1, 6, 3)), "london")  # winter
        self.assertEqual(self.clock.session(ny(2026, 7, 7, 3)), "london")  # summer
        self.assertEqual(self.clock.session(ny(2026, 1, 6, 8)), "newyork")
        self.assertEqual(self.clock.session(ny(2026, 1, 6, 21)), "asia")
        self.assertIsNone(self.clock.session(ny(2026, 1, 6, 12)))

    def test_trading_day_rolls_at_5pm(self):
        self.assertEqual(self.clock.trading_day(ny(2026, 1, 6, 16, 55)).day, 6)
        self.assertEqual(self.clock.trading_day(ny(2026, 1, 6, 17, 0)).day, 7)

    def test_entries_only_in_allowed_sessions(self):
        self.assertTrue(self.clock.can_enter(ny(2026, 1, 6, 8)))
        self.assertFalse(self.clock.can_enter(ny(2026, 1, 6, 21)))  # Asia not in trade_in


class IndicatorTests(unittest.TestCase):
    def test_aggregator_builds_hour_bars(self):
        agg = Aggregator(60)
        t0 = datetime(2026, 1, 6, 10, tzinfo=timezone.utc)
        out = []
        for k in range(24):
            out += agg.update(bar(t0 + timedelta(minutes=5 * k), 1 + k, 2 + k, k, 1.5 + k), 5)
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0].open, out[0].high, out[0].low, out[0].close), (1, 13, 0, 12.5))

    def test_swings_are_confirmed_only_after_right_side_bars(self):
        s = SwingTracker(2)
        t0 = datetime(2026, 1, 6, tzinfo=timezone.utc)
        highs = [1, 2, 5, 3, 2, 1]
        found = []
        for k, h in enumerate(highs):
            found.append(s.update(bar(t0 + timedelta(minutes=k), h - 0.5, h, h - 1, h - 0.5)))
        self.assertEqual(found[3], [])  # not known yet at bar 3
        self.assertEqual([x.price for x in found[4] if x.kind == "high"], [5])


def htf_bars(rows, start=None, minutes=60):
    start = start or datetime(2026, 1, 6, tzinfo=timezone.utc)
    return [bar(start + timedelta(minutes=minutes * k), *r) for k, r in enumerate(rows)]


# 16 quiet bars (ATR about 1), then a swing high at 104, a pullback with a down
# candle at 100-101, and an explosive rally through 104 that leaves a gap.
QUIET = [(100, 101, 99.5, 100.5)] * 16
STRONG = QUIET + [
    (100.5, 103, 100.4, 102.8),
    (102.8, 104, 102.5, 103.5),   # swing high 104
    (103.5, 103.6, 102.0, 102.2),
    (102.2, 102.3, 101.0, 101.2),
    (101.2, 101.3, 100.0, 100.2),  # last down candle = demand 100.0-101.3
    (100.2, 102.5, 100.1, 102.4),
    (102.4, 105.5, 102.6, 105.3),  # gap: 101.3 < 102.6, closes above 104
]


class ZoneTests(unittest.TestCase):
    def run_zone(self, rows, **overrides):
        cfg = Config().zones
        for k, v in overrides.items():
            setattr(cfg, k, v)
        zf = ZoneFinder(cfg, 2)
        for b in htf_bars(rows):
            zf.update(b)
        return zf

    def test_strong_break_with_gap_makes_demand_zone(self):
        zf = self.run_zone(STRONG)
        demand = zf.active(LONG)
        self.assertEqual(len(demand), 1)
        self.assertEqual((demand[0].bottom, demand[0].top), (100.0, 101.3))
        self.assertIn("left a fair value gap", demand[0].reasons)

    def test_weak_break_is_not_a_zone(self):
        # Barely closes above the swing high: 2.5 ATR move vs the strong 3.1 ATR one.
        weak = STRONG[:-2] + [(100.2, 102.5, 100.1, 102.4), (102.4, 104.3, 102.6, 104.1)]
        zf = self.run_zone(weak, displacement_atr=3.0)
        self.assertEqual(zf.active(LONG), [])
        self.assertEqual(len(self.run_zone(STRONG, displacement_atr=3.0).active(LONG)), 1)
        self.assertTrue(any(side == LONG for _, side, _ in zf.rejected))

    def test_no_gap_rejected_when_gap_required(self):
        no_gap = STRONG[:-1] + [(102.4, 105.5, 101.2, 105.3)]  # low overlaps the 101.3 high
        self.assertEqual(self.run_zone(no_gap).active(LONG), [])
        self.assertEqual(len(self.run_zone(no_gap, require_fvg=False).active(LONG)), 1)

    def test_close_through_zone_kills_it(self):
        zf = self.run_zone(STRONG + [(105, 105.2, 99, 99.5)], displacement_atr=1.5)
        self.assertEqual(zf.active(LONG), [])


class LiquidityTests(unittest.TestCase):
    def test_previous_day_and_session_levels(self):
        book = LiquidityBook(SessionClock(Config().sessions))
        book.update(bar(ny(2026, 1, 6, 3), 10, 12, 9, 11))  # london, day 6
        book.update(bar(ny(2026, 1, 6, 6), 11, 11.5, 10.5, 11))  # london over
        self.assertEqual(book.levels["London high"].price, 12)
        book.update(bar(ny(2026, 1, 6, 18), 11, 11.2, 10.8, 11))  # new trading day
        self.assertEqual((book.levels["PDH"].price, book.levels["PDL"].price), (12, 9))
        swept = book.update(bar(ny(2026, 1, 7, 3), 11, 11.5, 8.5, 10))
        self.assertIn("PDL", [lv.name for lv in swept])


class RiskTests(unittest.TestCase):
    def test_size_risks_the_set_percent(self):
        cfg = Config()
        cfg.instrument.tick_size, cfg.instrument.tick_value, cfg.instrument.qty_step = 0.25, 1.25, 1
        cfg.instrument.min_qty, cfg.instrument.max_qty = 1, 50
        rm = RiskManager(cfg, SessionClock(cfg.sessions), 50_000)
        sig = Signal(LONG, 5000, 4990, 5030, ny(2026, 1, 6, 8), "")
        # 0.5% of 50k = 250; 10 points = 40 ticks * 1.25 = 50 per contract -> 5 contracts
        self.assertEqual(rm.size(sig), 5)

    def test_daily_loss_limit_halts(self):
        cfg = Config()
        rm = RiskManager(cfg, SessionClock(cfg.sessions), 50_000)
        t = ny(2026, 1, 6, 8)
        self.assertTrue(rm.can_trade(t))
        rm.set_equity(48_900, t)  # -2.2%
        self.assertFalse(rm.can_trade(t))
        self.assertTrue(rm.can_trade(ny(2026, 1, 7, 8)))  # next day OK


class FillTests(unittest.TestCase):
    def test_stop_and_target_in_same_bar_counts_as_loss(self):
        cfg = Config()
        p = Position(cfg, Signal(LONG, 100, 99, 102, ny(2026, 1, 6, 8), ""), 1, 0)
        p.check(bar(ny(2026, 1, 6, 8, 5), 100, 103, 98, 101))
        self.assertEqual(p.trade.exit_reason, "stop")

    def test_short_target(self):
        cfg = Config()
        p = Position(cfg, Signal(SHORT, 100, 101, 97, ny(2026, 1, 6, 8), ""), 1, 0)
        p.check(bar(ny(2026, 1, 6, 8, 5), 99, 99.5, 96.5, 97))
        self.assertEqual((p.trade.exit_reason, p.trade.exit), ("target", 97))


class StrategyScenarioTests(unittest.TestCase):
    def build_day_then_sweep(self):
        """Day 1 ranges 100-107. Next London open sweeps the low (PDL), then breaks structure up."""
        bars = []
        t = ny(2026, 1, 5, 17)
        price_path = []
        for k in range(12 * 24):  # one trading day of 5m bars, ranging 101-103
            mid = 102 + (1 if (k // 12) % 2 else -1) * 0.5
            price_path.append((mid, mid + 0.3, mid - 0.3, mid))
        price_path[30] = (101.5, 101.6, 100.0, 101.0)  # day low 100 (PDL)
        price_path[200] = (102.5, 107.0, 102.4, 102.6)  # day high 107 (PDH)
        for o, h, l, c in price_path:
            bars.append(bar(t, o, h, l, c))
            t += timedelta(minutes=5)
        # Next day, London (02:00 NY): drift down, small swing high, sweep below 100, then rally.
        t = ny(2026, 1, 7, 2)
        seq = [
            (101.5, 101.6, 101.0, 101.1), (101.1, 101.2, 100.6, 100.7), (100.7, 101.4, 100.6, 101.3),
            (101.3, 101.5, 101.0, 101.1),  # swing high 101.5
            (101.1, 101.2, 100.6, 100.7), (100.7, 100.8, 100.3, 100.4),
            (100.4, 100.5, 99.6, 100.2),  # sweeps PDL 100 (low 99.6)
            (100.2, 100.9, 100.1, 100.8), (100.8, 101.3, 100.7, 101.2),
            (101.2, 101.9, 101.1, 101.8),  # closes above 101.5 = break of structure
        ]
        for o, h, l, c in seq:
            bars.append(bar(t, o, h, l, c))
            t += timedelta(minutes=5)
        return bars

    def test_pdl_sweep_then_bos_gives_long_targeting_liquidity(self):
        cfg = Config()
        cfg.instrument.tick_size = 0.01
        cfg.entry.stop_buffer_ticks = 5
        cfg.entry.max_stop_atr = 10
        strat = Strategy(cfg)
        signals = [s for s in (strat.on_bar(b) for b in self.build_day_then_sweep()) if s]
        self.assertEqual(len(signals), 1, "\n".join(strat.log))
        s = signals[0]
        self.assertEqual(s.side, LONG)
        self.assertAlmostEqual(s.entry, 101.8)
        self.assertAlmostEqual(s.stop, 99.55)  # below the sweep low plus buffer
        self.assertIn("PDL", s.reason)
        self.assertGreaterEqual(s.rr, cfg.entry.min_rr)

    def test_skips_when_next_liquidity_is_too_close(self):
        cfg = Config()
        cfg.instrument.tick_size = 0.01
        cfg.entry.stop_buffer_ticks = 5
        cfg.entry.max_stop_atr = 10
        cfg.entry.min_rr = 3.0  # PDH is only about 2.3R away
        strat = Strategy(cfg)
        self.assertFalse(any(strat.on_bar(b) for b in self.build_day_then_sweep()))
        self.assertTrue(any("only 2.3R away" in line for line in strat.log), "\n".join(strat.log))

    def test_no_trade_without_break_of_structure(self):
        cfg = Config()
        cfg.instrument.tick_size = 0.01
        cfg.entry.max_stop_atr = 10
        bars = self.build_day_then_sweep()[:-1]  # stop before the BOS bar
        strat = Strategy(cfg)
        self.assertFalse(any(strat.on_bar(b) for b in bars))

    def test_no_entry_outside_sessions(self):
        cfg = Config()
        cfg.instrument.tick_size = 0.01
        cfg.entry.max_stop_atr = 10
        cfg.sessions.trade_in = ("newyork",)  # scenario happens in London
        strat = Strategy(cfg)
        self.assertFalse(any(strat.on_bar(b) for b in self.build_day_then_sweep()))


class EndToEndTests(unittest.TestCase):
    def test_backtest_runs_and_respects_daily_trade_cap(self):
        cfg = Config()
        cfg.entry.confirmation = "bos"
        result = run_backtest(cfg, synthetic(days=40))
        self.assertGreater(len(result.trades), 0)
        per_day = {}
        clock = SessionClock(cfg.sessions)
        for t in result.trades:
            d = clock.trading_day(t.entry_time)
            per_day[d] = per_day.get(d, 0) + 1
        self.assertLessEqual(max(per_day.values()), cfg.risk.max_trades_per_day)
        for t in result.trades:  # entries only in allowed sessions
            self.assertIn(clock.session(t.entry_time), cfg.sessions.trade_in)

    def test_example_config_loads(self):
        cfg = load_config(str(ROOT / "config.example.toml"))
        self.assertEqual(cfg.sessions.trade_in, ("london", "newyork"))

    def test_csv_round_trip_mt5_format(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "eurusd.csv"
            lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>"]
            for k in range(6):
                lines.append(f"2026.01.06\t10:{k:02d}:00\t1.1\t1.2\t1.0\t1.15\t10")
            p.write_text("\n".join(lines))
            bars = load_csv(str(p), "Europe/Athens")
            self.assertEqual(bars[0].time, datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc))
            self.assertEqual(len(resample(bars, 1, 5)), 1)


class GoldPresetTests(unittest.TestCase):
    def test_all_gold_presets_load(self):
        for name in ("xauusd_mt5", "mgc_tradovate", "mgc_ninjatrader"):
            cfg = load_config(str(ROOT / "presets" / f"{name}.toml"))
            self.assertEqual(cfg.broker.mode, "paper", name)  # never ship a preset that trades live
            self.assertEqual(cfg.sessions.flatten_at, "16:50", name)

    def test_mgc_sizing(self):
        cfg = load_config(str(ROOT / "presets" / "mgc_tradovate.toml"))
        rm = RiskManager(cfg, SessionClock(cfg.sessions), 50_000)
        # $3.00 stop = 30 ticks x $1 + $1.50 commission = $31.50 per contract; $250 risk -> 7 contracts
        sig = Signal(LONG, 4000.0, 3997.0, 4006.0, ny(2026, 11, 3, 8), "")
        self.assertEqual(rm.size(sig), 7)

    def test_xauusd_sizing(self):
        cfg = load_config(str(ROOT / "presets" / "xauusd_mt5.toml"))
        rm = RiskManager(cfg, SessionClock(cfg.sessions), 50_000)
        # $3.00 stop = 300 ticks x $1 + $7 commission = $307 per lot; $250 risk -> 0.81 lots
        sig = Signal(SHORT, 4000.0, 4003.0, 3994.0, ny(2026, 11, 3, 8), "")
        self.assertAlmostEqual(rm.size(sig), 0.81)

    def test_futures_flatten_window(self):
        cfg = load_config(str(ROOT / "presets" / "mgc_tradovate.toml"))
        clock = SessionClock(cfg.sessions)
        self.assertTrue(clock.should_flatten(ny(2026, 11, 3, 16, 55)))
        self.assertFalse(clock.should_flatten(ny(2026, 11, 3, 18, 5)))  # reopened
        self.assertEqual(clock.trading_day(ny(2026, 11, 3, 18, 5)).day, 4)


class NinjaTraderTests(unittest.TestCase):
    def test_brackets_sent_only_after_entry_fills(self):
        from elev8bot.brokers.base import BrokerError
        from elev8bot.brokers.ninjatrader import NinjaTrader

        with tempfile.TemporaryDirectory() as d:
            inc, out = Path(d) / "incoming", Path(d) / "outgoing"
            inc.mkdir()
            out.mkdir()
            cfg = Config()
            cfg.broker.ninjatrader_incoming = str(inc)
            cfg.broker.ninjatrader_instrument = "MES 12-26"
            nt = NinjaTrader(cfg)
            nt.connect()
            import elev8bot.brokers.ninjatrader as mod
            orig = mod.time.sleep
            mod.time.sleep = lambda s: None
            try:
                with self.assertRaises(BrokerError):  # never filled -> cancelled, no brackets
                    nt.place_bracket(Signal(LONG, 5000, 4990, 5030, ny(2026, 1, 6, 8), ""), 2)
                texts = [f.read_text() for f in sorted(inc.glob("oif*.txt"))]
                self.assertEqual(len(texts), 2)
                self.assertTrue(texts[0].startswith("PLACE;Sim101;MES 12-26;BUY;2;MARKET"))
                self.assertTrue(texts[1].startswith("CANCEL"))
            finally:
                mod.time.sleep = orig


if __name__ == "__main__":
    unittest.main()
