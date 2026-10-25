"""MetaTrader 5 (forex and CFDs). Data and orders.

Needs Windows, the MT5 terminal installed and logged in, "Algo Trading" switched
on, and `pip install MetaTrader5`. The bot never sees your MT5 password: it
attaches to the terminal that is already logged in.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..config import Config
from ..models import LONG, Bar, Signal
from .base import Broker, BrokerError, DataFeed

try:  # only available on Windows
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

_TIMEFRAMES = {1: "TIMEFRAME_M1", 2: "TIMEFRAME_M2", 3: "TIMEFRAME_M3", 5: "TIMEFRAME_M5",
               10: "TIMEFRAME_M10", 15: "TIMEFRAME_M15", 30: "TIMEFRAME_M30", 60: "TIMEFRAME_H1"}


class MT5(Broker, DataFeed):
    name = "mt5"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.symbol = cfg.instrument.symbol
        self.offset = 0  # broker server time minus UTC, in seconds
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return
        if mt5 is None:
            raise BrokerError("MetaTrader5 package not installed. Run: pip install MetaTrader5 (Windows only)")
        ok = mt5.initialize(path=self.cfg.broker.mt5_path) if self.cfg.broker.mt5_path else mt5.initialize()
        if not ok:
            raise BrokerError(f"Could not attach to MT5: {mt5.last_error()}")
        if not mt5.symbol_select(self.symbol, True):
            raise BrokerError(f"Symbol {self.symbol} not found in MT5 Market Watch")
        info = mt5.symbol_info(self.symbol)
        ins = self.cfg.instrument  # use the broker's real contract specs for sizing
        ins.tick_size = info.trade_tick_size
        ins.tick_value = info.trade_tick_value
        ins.qty_step = info.volume_step
        ins.min_qty = info.volume_min
        ins.max_qty = min(ins.max_qty, info.volume_max)
        self.offset = self._server_offset()
        self._connected = True

    def _server_offset(self) -> int:
        """MT5 bar times are broker server time, not UTC. Work out the gap."""
        setting = str(self.cfg.broker.mt5_server_utc_offset).strip().lower()
        if setting != "auto":
            return int(float(setting) * 3600)
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise BrokerError("No price from MT5 to work out server time; set broker.mt5_server_utc_offset")
        diff = tick.time - time.time()
        hours = round(diff / 1800) / 2  # nearest half hour
        if abs(diff - hours * 3600) > 300:
            raise BrokerError("Market looks closed, can't work out MT5 server time. Set broker.mt5_server_utc_offset")
        return int(hours * 3600)

    def closed_bars(self, count: int) -> list[Bar]:
        tf = getattr(mt5, _TIMEFRAMES[self.cfg.timeframes.ltf_minutes])
        rates = mt5.copy_rates_from_pos(self.symbol, tf, 1, count)  # position 0 is the bar still forming
        if rates is None:
            raise BrokerError(f"MT5 returned no bars: {mt5.last_error()}")
        return [Bar(datetime.fromtimestamp(int(r["time"]) - self.offset, tz=timezone.utc),
                    float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["tick_volume"]))
                for r in rates]

    def equity(self) -> float:
        return float(mt5.account_info().equity)

    def _positions(self):
        return [p for p in (mt5.positions_get(symbol=self.symbol) or []) if p.magic == self.cfg.broker.mt5_magic]

    def has_position(self) -> bool:
        return bool(self._positions())

    def _filling(self):
        mode = mt5.symbol_info(self.symbol).filling_mode
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def place_bracket(self, signal: Signal, qty: float) -> str:
        tick = mt5.symbol_info_tick(self.symbol)
        long = signal.side == LONG
        price = tick.ask if long else tick.bid
        if (long and not signal.stop < price < signal.target) or (not long and not signal.target < price < signal.stop):
            raise BrokerError(f"Price {price} moved outside stop/target; signal skipped")
        digits = mt5.symbol_info(self.symbol).digits
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(qty),
            "type": mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL, "price": price,
            "sl": round(signal.stop, digits), "tp": round(signal.target, digits), "deviation": 20,
            "magic": self.cfg.broker.mt5_magic, "comment": "ELEV8 bot",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise BrokerError(f"MT5 rejected the order: {getattr(res, 'comment', mt5.last_error())}")
        return str(res.order)

    def flatten(self) -> None:
        for p in self._positions():
            tick = mt5.symbol_info_tick(self.symbol)
            buy = p.type == mt5.POSITION_TYPE_SELL
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": p.volume, "position": p.ticket,
                "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": tick.ask if buy else tick.bid,
                "deviation": 50, "magic": self.cfg.broker.mt5_magic, "comment": "ELEV8 flatten",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
            })
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                raise BrokerError(f"MT5 could not close position {p.ticket}: {getattr(res, 'comment', '')}")

    def disconnect(self) -> None:
        if mt5 is not None:
            mt5.shutdown()
