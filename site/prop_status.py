"""Prop firm limits for one account: the server's copy of the app's propStatus() (daily and max loss).

Uses the same firm rules the app has built in (index.html's propRules), the account's own adjustments,
its closed trades and its payouts, so a notification says exactly what the Accounts page shows.
"""
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rules():
    try:
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        return json.loads(re.search(r'<script type="application/json" id="propRules">(.*?)</script>', page, re.S).group(1))
    except Exception:
        return {"firms": []}


PROP = _rules()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def find_firm(name):
    n = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    return next((f for f in PROP.get("firms", []) if any(m in n for m in f.get("match", []))), None) if n else None


def rules_for(a):
    if a.get("type") != "Prop firm":
        return None
    f = find_firm(a.get("firm"))
    prog = next((p for p in f.get("programs", []) if p.get("id") == a.get("program")), None) if f else None
    if not prog or not prog.get("phases"):
        return None, None
    ph = next((x for x in prog["phases"] if x.get("name") == a.get("phase")), prog["phases"][0])
    o = a.get("rules") if isinstance(a.get("rules"), dict) else {}
    pick = lambda k, v: num(o[k]) if o.get(k) not in (None, "") else v
    daily = dict(ph["daily"], pct=pick("daily", ph["daily"].get("pct"))) if ph.get("daily") else ({"pct": num(o["daily"]), "of": "initial"} if o.get("daily") not in (None, "") else None)
    mx = dict(ph["max"], pct=pick("max", ph["max"].get("pct"))) if ph.get("max") else ({"pct": num(o["max"]), "type": "static"} if o.get("max") not in (None, "") else None)
    return {"daily": daily, "max": mx}, prog


def reset_zone(firm):
    """Same as the app's resetZone(): the time zone the firm's trading day starts in."""
    r = str((firm or {}).get("reset") or "")
    if re.search(r"Prague|CE\(S\)T", r, re.I):
        return "Europe/Prague"
    m = re.search(r"(?:UTC|GMT)\s*([+-]\d{1,2})", r, re.I)
    return int(m.group(1)) if m else None


def _in_zone(at, zone):
    if isinstance(zone, int):
        return at.astimezone(dt.timezone(dt.timedelta(hours=zone)))
    from zoneinfo import ZoneInfo
    return at.astimezone(ZoneInfo(zone))


def firm_close_day(t, zone, tz):
    """Same as the app's firmCloseDay(): the firm's day a trade closed on (trade times are the trader's local time)."""
    d = str(t.get("closedDate") or t.get("date") or "")
    tm = str((t.get("closedTime") if t.get("closedDate") else t.get("time")) or "")
    if zone is None or tz is None or not re.match(r"^\d{1,2}:\d{2}", tm):
        return d
    try:
        h, mi = tm[:5].split(":")
        at = dt.datetime.fromisoformat(d).replace(hour=int(h), minute=int(mi), tzinfo=tz)
        return _in_zone(at, zone).date().isoformat()
    except Exception:
        return d


def status(a, trades, today, tz=None, now=None):
    """Daily and max loss for a prop account, as the app works them out. `today` is an ISO date in the
    trader's own time zone; with `tz` (the trader's ZoneInfo) and `now` (aware), days follow the firm's
    reset time like the app. None when the account isn't a known prop programme."""
    got = rules_for(a)
    if not got or not got[0]:
        return None
    r, prog = got
    size = num(a.get("size"))
    if size <= 0:
        return None
    start_date = a.get("startDate") or ""
    closed = [t for t in trades if t.get("account") == a.get("id") and t.get("status") != "open" and (not start_date or str(t.get("date") or "") >= start_date)]
    closed.sort(key=lambda t: str(t.get("date") or "") + str(t.get("time") or ""))
    zone = reset_zone(find_firm(a.get("firm")))
    if zone is not None and tz is not None and now is not None:
        today = _in_zone(now, zone).date().isoformat()
    by_day = {}
    for t in closed:
        d = firm_close_day(t, zone, tz)
        by_day[d] = by_day.get(d, 0.0) + num(t.get("pnl"))
    pays = sorted([p for p in (a.get("payouts") or []) if isinstance(p, dict) and p.get("date")], key=lambda p: p["date"])
    pay_days = {p["date"] for p in pays}
    paid_on = {}
    for p in pays:
        paid_on[p["date"]] = paid_on.get(p["date"], 0.0) + num(p.get("amount"))
    deduct = (prog or {}).get("payout") == "deduct"
    mx = r["max"]
    max_allow = mx["pct"] / 100 * size if mx else None
    st = {"bal": size, "peak": size, "locked": False}

    def floor_at(pk):
        if not mx:
            return float("-inf")
        if mx.get("type") != "trailing":
            return size - max_allow
        if st["locked"]:
            return size
        f = pk - max_allow
        return min(f, size) if mx.get("lockAt") == "initial" else f

    def payout(d):
        if not deduct:
            st["bal"] = size; st["peak"] = size
            return
        st["bal"] -= paid_on.get(d, 0.0)
        if mx and mx.get("lockOnPayout"):
            st["locked"] = True

    breach = None
    for d in sorted(set(by_day) | pay_days):
        if d not in by_day:
            if d in pay_days:
                payout(d)
            continue
        start, pnl = st["bal"], by_day[d]
        st["bal"] += pnl
        if r["daily"]:
            lim = r["daily"]["pct"] / 100 * (start if r["daily"].get("of") == "startOfDay" else size)
            if -pnl >= lim - 1e-9 and not breach:
                breach = {"rule": "Daily loss limit", "date": d}
        if st["bal"] <= floor_at(st["peak"]) + 1e-9 and not breach:
            breach = {"rule": "Maximum loss", "date": d}
        st["peak"] = max(st["peak"], st["bal"])
        if d in pay_days:
            payout(d)
    today_pnl = by_day.get(today, 0.0)
    sod = st["bal"] - today_pnl
    daily_limit = r["daily"]["pct"] / 100 * (sod if r["daily"].get("of") == "startOfDay" else size) if r["daily"] else None
    floor = floor_at(st["peak"])
    return {"bal": st["bal"], "today_pnl": today_pnl, "daily_limit": daily_limit, "daily_used": max(0.0, -today_pnl),
            "floor": floor, "max_allow": max_allow, "max_room": st["bal"] - floor, "breach": breach,
            "last_day": max(by_day) if by_day else ""}
