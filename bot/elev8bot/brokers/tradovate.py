"""Tradovate (futures). Orders over the REST API, bars over the market data websocket.

Credentials come from environment variables only, never from the config file:
  TRADOVATE_USERNAME, TRADOVATE_PASSWORD, TRADOVATE_CID, TRADOVATE_SECRET
  optional: TRADOVATE_APP_ID (default "ELEV8 Bot"), TRADOVATE_DEVICE_ID
API access needs an API key from Tradovate (Settings > API Access). Bars need
`pip install websocket-client` and a market data subscription for API use.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from ..config import Config
from ..models import LONG, Bar, Signal
from .base import Broker, BrokerError, DataFeed

REST = {"demo": "https://demo.tradovateapi.com/v1", "live": "https://live.tradovateapi.com/v1"}
MD = {"demo": "wss://md-demo.tradovateapi.com/v1/websocket", "live": "wss://md.tradovateapi.com/v1/websocket"}


class Tradovate(Broker, DataFeed):
    name = "tradovate"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        env = cfg.broker.tradovate_env
        if env not in REST:
            raise BrokerError("broker.tradovate_env must be demo or live")
        self.base = REST[env]
        self.md_url = MD[env]
        self.symbol = cfg.broker.tradovate_symbol or cfg.instrument.symbol
        self.token = ""
        self.md_token = ""
        self.expires = datetime.now(timezone.utc)
        self.account_id = 0
        self.account_name = ""
        self.contract_id = 0
        self._bars: dict[datetime, Bar] = {}
        self._lock = threading.Lock()
        self._ws = None

    # ------------------------------------------------------------------- REST
    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True):
        if auth:
            self._renew_if_needed()
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            raise BrokerError(f"Tradovate {path} failed: {e.code} {e.read()[:300]!r}") from e

    def _env(self, key: str) -> str:
        value = os.environ.get(key, "")
        if not value:
            raise BrokerError(f"Set the {key} environment variable")
        return value

    def connect(self) -> None:
        body = {
            "name": self._env("TRADOVATE_USERNAME"), "password": self._env("TRADOVATE_PASSWORD"),
            "appId": os.environ.get("TRADOVATE_APP_ID", "ELEV8 Bot"), "appVersion": "1.0",
            "cid": self._env("TRADOVATE_CID"), "sec": self._env("TRADOVATE_SECRET"),
            "deviceId": os.environ.get("TRADOVATE_DEVICE_ID", str(uuid.uuid5(uuid.NAMESPACE_DNS, "elev8-bot"))),
        }
        res = self._request("POST", "/auth/accesstokenrequest", body, auth=False)
        if not res or "accessToken" not in res:
            raise BrokerError(f"Tradovate login failed: {res.get('errorText') if res else 'no response'}")
        self._store_token(res)
        accounts = self._request("GET", "/account/list") or []
        want = self.cfg.broker.tradovate_account
        acct = next((a for a in accounts if not want or a["name"] == want), None)
        if not acct:
            raise BrokerError(f"Tradovate account '{want}' not found")
        self.account_id, self.account_name = acct["id"], acct["name"]
        contract = self._request("GET", f"/contract/find?name={self.symbol}")
        if not contract or "id" not in contract:
            raise BrokerError(f"Tradovate contract {self.symbol} not found (use the full name, e.g. MESZ6)")
        self.contract_id = contract["id"]

    def _store_token(self, res: dict) -> None:
        self.token = res["accessToken"]
        self.md_token = res.get("mdAccessToken", self.md_token)
        exp = res.get("expirationTime")
        self.expires = (datetime.fromisoformat(exp.replace("Z", "+00:00")) if exp
                        else datetime.now(timezone.utc) + timedelta(minutes=80))

    def _renew_if_needed(self) -> None:
        if self.token and self.expires - datetime.now(timezone.utc) < timedelta(minutes=10):
            self.token, token = "", self.token
            req = urllib.request.Request(self.base + "/auth/renewaccesstoken")
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                self._store_token(json.loads(resp.read()))

    def equity(self) -> float:
        snap = self._request("POST", "/cashBalance/getcashbalancesnapshot", {"accountId": self.account_id}) or {}
        for key in ("netLiq", "totalCashValue", "amount"):
            if key in snap:
                return float(snap[key])
        raise BrokerError(f"Could not read Tradovate balance: {snap}")

    def has_position(self) -> bool:
        positions = self._request("GET", "/position/list") or []
        return any(p.get("accountId") == self.account_id and p.get("contractId") == self.contract_id
                   and p.get("netPos", 0) != 0 for p in positions)

    def place_bracket(self, signal: Signal, qty: float) -> str:
        long = signal.side == LONG
        entry, exit_ = ("Buy", "Sell") if long else ("Sell", "Buy")
        body = {
            "accountSpec": self.account_name, "accountId": self.account_id, "action": entry,
            "symbol": self.symbol, "orderQty": int(qty), "orderType": "Market", "isAutomated": True,
            "bracket1": {"action": exit_, "orderType": "Limit", "price": signal.target},
            "bracket2": {"action": exit_, "orderType": "Stop", "stopPrice": signal.stop},
        }
        res = self._request("POST", "/order/placeOSO", body) or {}
        if res.get("failureReason") or "orderId" not in res:
            raise BrokerError(f"Tradovate rejected the order: {res.get('failureText') or res}")
        return str(res["orderId"])

    def flatten(self) -> None:
        self._request("POST", "/order/liquidateposition",
                      {"accountId": self.account_id, "contractId": self.contract_id, "admin": False})

    # -------------------------------------------------------------- bar stream
    def _start_stream(self) -> None:
        try:
            import websocket  # websocket-client
        except ImportError as e:
            raise BrokerError("pip install websocket-client to stream Tradovate bars") from e
        minutes = self.cfg.timeframes.ltf_minutes

        def on_message(ws, msg: str) -> None:
            if msg == "o":
                ws.send(f"authorize\n0\n\n{self.md_token}")
                chart = {"symbol": self.symbol,
                         "chartDescription": {"underlyingType": "MinuteBar", "elementSize": minutes,
                                              "elementSizeUnit": "UnderlyingUnits", "withHistogram": False},
                         "timeRange": {"asMuchAsElements": 1500}}
                ws.send(f"md/getChart\n1\n\n{json.dumps(chart)}")
                return
            if not msg.startswith("a"):
                return
            for item in json.loads(msg[1:]):
                if item.get("e") != "chart":
                    continue
                for ch in item.get("d", {}).get("charts", []):
                    with self._lock:
                        for b in ch.get("bars", []):
                            t = datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
                            self._bars[t] = Bar(t, b["open"], b["high"], b["low"], b["close"],
                                                b.get("upVolume", 0) + b.get("downVolume", 0))

        def heartbeat(ws) -> None:
            while ws.keep_running:
                time.sleep(2.5)
                try:
                    ws.send("[]")
                except Exception:
                    return

        def run() -> None:
            while True:  # reconnect forever
                ws = websocket.WebSocketApp(self.md_url, on_message=on_message,
                                            on_open=lambda w: threading.Thread(target=heartbeat, args=(w,), daemon=True).start())
                self._ws = ws
                ws.run_forever()
                time.sleep(5)

        threading.Thread(target=run, daemon=True).start()

    def closed_bars(self, count: int) -> list[Bar]:
        if self._ws is None:
            self._start_stream()
            for _ in range(60):
                if self._bars:
                    break
                time.sleep(0.5)
        now = datetime.now(timezone.utc)
        step = timedelta(minutes=self.cfg.timeframes.ltf_minutes)
        with self._lock:
            done = sorted(b for b in self._bars if b + step <= now)
            return [self._bars[t] for t in done[-count:]]
