"""NinjaTrader 8 through its Automated Trading Interface (ATI). Orders only.

Turn it on in NinjaTrader: Tools > Options > Automated trading interface >
"AT interface" ticked. The bot drops order files (OIF) into
Documents/NinjaTrader 8/incoming and NinjaTrader places them. NinjaTrader writes
position files to the "outgoing" folder, which the bot reads.

Bars must come from another source (broker.data_source = "tradovate" or "csv"),
because ATI does not stream prices. If your NinjaTrader is connected to a
Tradovate account, use that.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import Config
from ..models import LONG, Signal
from .base import Broker, BrokerError


class NinjaTrader(Broker):
    name = "ninjatrader"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        b = cfg.broker
        self.account = b.ninjatrader_account
        self.instrument = b.ninjatrader_instrument or cfg.instrument.symbol
        self.incoming = Path(b.ninjatrader_incoming or Path.home() / "Documents" / "NinjaTrader 8" / "incoming")
        self.outgoing = self.incoming.parent / "outgoing"
        self._n = 0
        self._balance = cfg.risk.account_size
        self._open: list[dict] = []  # bot orders whose exit has not filled yet

    def connect(self) -> None:
        if not self.incoming.is_dir():
            raise BrokerError(f"NinjaTrader incoming folder not found: {self.incoming}")

    def _send(self, line: str) -> None:
        self._n += 1
        name = self.incoming / f"oif{int(time.time() * 1000)}_{self._n}.txt"
        tmp = name.with_suffix(".tmp")
        tmp.write_text(line + "\n")
        os.replace(tmp, name)  # NinjaTrader must never read a half-written file

    def _order_state(self, order_id: str) -> tuple[str, float, float]:
        """NinjaTrader writes outgoing/<order id>.txt as STATE;FILLED QTY;AVG FILL PRICE."""
        f = self.outgoing / f"{order_id}.txt"
        if not f.exists():
            return "", 0.0, 0.0
        parts = (f.read_text().strip().split(";") + ["", "0", "0"])[:3]
        try:
            return parts[0].upper(), float(parts[1] or 0), float(parts[2] or 0)
        except ValueError:
            return parts[0].upper(), 0.0, 0.0

    def equity(self) -> float:
        """ATI does not report the balance, so add up the bot's own fills."""
        for t in list(self._open):
            state_e, qty, entry = self._order_state(t["id"] + "E")
            for leg in ("T", "S"):
                state, q, price = self._order_state(t["id"] + leg)
                if state == "FILLED" and entry:
                    ins = self.cfg.instrument
                    move = (price - entry) if t["long"] else (entry - price)
                    self._balance += move / ins.tick_size * ins.tick_value * q - ins.commission_per_unit * q
                    self._open.remove(t)
                    break
        return self._balance

    def has_position(self) -> bool:
        for f in self.outgoing.glob(f"*_{self.account}_position.txt"):
            if f.name.lower().startswith(self.instrument.lower()):
                text = f.read_text().strip()
                if text and not text.upper().startswith("FLAT"):
                    return True
        return False

    def place_bracket(self, signal: Signal, qty: float) -> str:
        long = signal.side == LONG
        entry, exit_ = ("BUY", "SELL") if long else ("SELL", "BUY")
        q = int(qty)
        oid = f"ELEV8{int(time.time())}"
        acct, ins = self.account, self.instrument
        # PLACE;ACCOUNT;INSTRUMENT;ACTION;QTY;ORDER TYPE;LIMIT;STOP;TIF;OCO;ORDER ID;STRATEGY;STRATEGY ID
        self._send(f"PLACE;{acct};{ins};{entry};{q};MARKET;0;0;DAY;;{oid}E;;")
        # Only send the stop and target once the entry has filled, so a rejected
        # entry can never leave a stray stop that opens a position the other way.
        for _ in range(40):
            state, _, _ = self._order_state(oid + "E")
            if state == "FILLED":
                break
            if state in ("REJECTED", "CANCELLED"):
                raise BrokerError(f"NinjaTrader {state.lower()} the entry order")
            time.sleep(0.25)
        else:
            self._send(f"CANCEL;;;;;;;;;;{oid}E;;")
            raise BrokerError("NinjaTrader entry did not fill within 10 seconds; cancelled")
        self._send(f"PLACE;{acct};{ins};{exit_};{q};LIMIT;{signal.target};0;GTC;{oid};{oid}T;;")
        self._send(f"PLACE;{acct};{ins};{exit_};{q};STOPMARKET;0;{signal.stop};GTC;{oid};{oid}S;;")
        self._open.append({"id": oid, "long": long})
        return oid

    def flatten(self) -> None:
        self._send(f"CLOSEPOSITION;{self.account};{self.instrument};GTC;;;;;;;;;")
