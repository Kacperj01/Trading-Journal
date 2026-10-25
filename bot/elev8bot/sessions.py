"""Session clock: which session a bar is in and which trading day it belongs to."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import SessionConfig

SESSION_NAMES = ("asia", "london", "newyork")


def _t(text: str) -> time:
    hh, mm = text.split(":")
    return time(int(hh), int(mm))


def _in_window(now: time, start: time, end: time) -> bool:
    if start < end:
        return start <= now < end
    return now >= start or now < end  # wraps past midnight (e.g. 20:00-00:00)


class SessionClock:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.day_start = _t(cfg.day_start)
        self.windows = {name: (_t(getattr(cfg, name)[0]), _t(getattr(cfg, name)[1])) for name in SESSION_NAMES}
        self.flatten_at = _t(cfg.flatten_at) if cfg.flatten_at else None

    def local(self, when: datetime) -> datetime:
        return when.astimezone(self.tz)

    def session(self, when: datetime) -> str | None:
        now = self.local(when).time()
        for name, (start, end) in self.windows.items():
            if _in_window(now, start, end):
                return name
        return None

    def trading_day(self, when: datetime) -> date:
        """Trading day rolls at day_start (17:00 New York by default)."""
        local = self.local(when)
        if local.time() >= self.day_start:
            return (local + timedelta(days=1)).date()
        return local.date()

    def can_enter(self, when: datetime) -> bool:
        return self.session(when) in self.cfg.trade_in

    def should_flatten(self, when: datetime) -> bool:
        if not self.flatten_at:
            return False
        now = self.local(when).time()
        return self.flatten_at <= now < self.day_start
