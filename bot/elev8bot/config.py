"""Settings, loaded from a TOML file. Every value has a default (see config.example.toml)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class InstrumentConfig:
    symbol: str = "EURUSD"
    tick_size: float = 0.00001  # smallest price step
    tick_value: float = 1.0  # money per tick for 1 contract / 1 lot
    qty_step: float = 0.01  # lots step (forex) or 1 for futures contracts
    min_qty: float = 0.01
    max_qty: float = 10.0
    commission_per_unit: float = 0.0  # round-turn cost per contract / lot
    slippage_ticks: float = 0.0  # backtest only


@dataclass
class TimeframeConfig:
    ltf_minutes: int = 5  # entry timeframe the bot runs on
    htf_minutes: int = 60  # timeframe zones are drawn on
    swing_length: int = 2  # bars each side for a swing high / low (LTF)
    htf_swing_length: int = 2


@dataclass
class ZoneConfig:
    # A zone only counts when ALL of these hold. This is what stops random zones.
    require_bos: bool = True  # the move away from the zone broke structure
    displacement_atr: float = 1.5  # move away from the zone must be at least this many ATR
    require_fvg: bool = True  # the move away left a fair value gap (imbalance)
    max_height_atr: float = 1.0  # zones taller than this are too vague to trade
    require_liquidity_origin: bool = False  # zone formed by sweeping a swing / PDH / PDL first
    max_age_bars: int = 120  # HTF bars before a zone expires
    atr_length: int = 14
    one_trade_per_zone: bool = True


@dataclass
class SessionConfig:
    # Times are New York local time (handles daylight saving). "HH:MM".
    timezone: str = "America/New_York"
    day_start: str = "17:00"  # futures / forex trading day roll
    asia: tuple = ("20:00", "00:00")
    london: tuple = ("02:00", "05:00")
    newyork: tuple = ("07:00", "10:00")
    trade_in: tuple = ("london", "newyork")  # sessions entries are allowed in
    flatten_at: str = ""  # e.g. "15:55" to close everything before the futures close


@dataclass
class EntryConfig:
    # "sweep_then_bos": tap zone -> sweep liquidity -> break of structure -> enter
    # "bos": tap zone -> break of structure -> enter
    # "sweep": tap zone -> sweep liquidity and close back -> enter
    confirmation: str = "sweep_then_bos"
    trade_key_level_sweeps: bool = True  # PDH/PDL/session sweep + BOS is a setup even outside a zone
    setup_timeout_bars: int = 24  # LTF bars to wait for confirmation after the zone tap
    stop_buffer_ticks: float = 2.0
    max_stop_atr: float = 3.0  # LTF ATR; skip setups whose stop is too wide
    target_mode: str = "liquidity"  # "liquidity" (next untaken pool) or "fixed"
    min_rr: float = 2.0
    fixed_rr: float = 3.0
    max_rr: float = 8.0


@dataclass
class RiskConfig:
    account_size: float = 50_000.0  # used by the backtester and paper broker
    risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 2
    max_daily_loss_pct: float = 2.0  # halt for the day after this
    max_drawdown_pct: float = 6.0  # halt the bot for good after this (from peak)
    max_consecutive_losses: int = 3  # halt for the day after this many losses in a row


@dataclass
class BrokerConfig:
    mode: str = "paper"  # "paper" or "live"
    broker: str = "paper"  # "paper", "mt5", "tradovate", "ninjatrader"
    data_source: str = ""  # where live bars come from: "mt5" or "tradovate"; defaults to the broker
    mt5_path: str = ""  # optional path to terminal64.exe
    mt5_magic: int = 880088  # tags the bot's MT5 orders so it never touches your manual trades
    mt5_server_utc_offset: str = "auto"  # hours, e.g. "2"; "auto" works it out while the market is open
    tradovate_env: str = "demo"  # "demo" or "live"
    tradovate_symbol: str = ""  # e.g. "MESZ6"; defaults to instrument.symbol
    tradovate_account: str = ""  # account name; defaults to the first account
    ninjatrader_account: str = "Sim101"
    ninjatrader_instrument: str = ""  # e.g. "MES 12-26"
    ninjatrader_incoming: str = ""  # defaults to ~/Documents/NinjaTrader 8/incoming
    poll_seconds: int = 5


@dataclass
class Config:
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    timeframes: TimeframeConfig = field(default_factory=TimeframeConfig)
    zones: ZoneConfig = field(default_factory=ZoneConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)


def _fill(obj: Any, data: dict, path: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown setting '{path}{key}'")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"'{path}{key}' must be a table")
            _fill(current, value, f"{path}{key}.")
        else:
            if isinstance(current, tuple):
                value = tuple(value)
            elif isinstance(current, float) and isinstance(value, int):
                value = float(value)
            setattr(obj, key, value)


def load_config(path: str | None) -> Config:
    cfg = Config()
    if path:
        with open(path, "rb") as fh:
            _fill(cfg, tomllib.load(fh), "")
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.timeframes.htf_minutes % cfg.timeframes.ltf_minutes:
        raise ValueError("htf_minutes must be a multiple of ltf_minutes")
    if cfg.entry.confirmation not in ("sweep_then_bos", "bos", "sweep"):
        raise ValueError("entry.confirmation must be sweep_then_bos, bos or sweep")
    if cfg.entry.target_mode not in ("liquidity", "fixed"):
        raise ValueError("entry.target_mode must be liquidity or fixed")
    if cfg.broker.mode not in ("paper", "live"):
        raise ValueError("broker.mode must be paper or live")
    if cfg.broker.broker not in ("paper", "mt5", "tradovate", "ninjatrader"):
        raise ValueError("broker.broker must be paper, mt5, tradovate or ninjatrader")
    if cfg.broker.data_source not in ("", "mt5", "tradovate"):
        raise ValueError("broker.data_source must be mt5 or tradovate")
    for name in cfg.sessions.trade_in:
        if name not in ("asia", "london", "newyork"):
            raise ValueError(f"Unknown session '{name}' in sessions.trade_in")
    if cfg.risk.risk_per_trade_pct <= 0 or cfg.risk.risk_per_trade_pct > 5:
        raise ValueError("risk.risk_per_trade_pct must be between 0 and 5")
