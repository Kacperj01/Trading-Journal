"""Notifications that run on a timer (Settings › Profile › Notifications), every 30 minutes from the
news-alerts GitHub Action:

- Prop firm limits: when a prop account reaches 80% of its daily or max loss limit, and when it hits it.
- Journal reminder: weekday evenings at the person's chosen time, if they have open trades or traded
  this week but haven't logged anything today.
- High-impact news: 15 minutes before, for the currencies they trade (below).

Quiet hours (if set) hold back news and limit alerts, in the person's own time zone.

High-impact news: each run Each run looks at the high-impact events in
docs/calendar.json starting in the next ~50 minutes, waits until 15 minutes before each one, and sends
one notification per person per time slot to everyone with "High-impact news" on in
Settings › Profile › Notifications. Each slot is claimed in Supabase's push_log first, so overlapping
or late runs never send it twice. A run that starts late still sends while the news hasn't happened.

A person's currencies come from their pair list (Settings) and the pairs they've traded, the same
way the News tab's "My pairs" filter works: GBPJPY → GBP and JPY, XAUUSD → USD, US30 → USD.

Environment:
  SUPABASE_SERVICE_KEY  Supabase secret (service_role) key - GitHub secret
  ONLY_EMAIL            optional: send a test alert for the next high-impact news (any currency) to just this account, now
  NOW                   optional (tests): pretend it's this UTC time, e.g. 2026-10-20T12:10:00Z
"""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import push  # noqa: E402
import prop_status  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEAD = dt.timedelta(minutes=15)    # alert this long before the news
AHEAD = dt.timedelta(minutes=50)   # this run handles news up to this far ahead (runs are 30 min apart, often late)
ONLY = os.environ.get("ONLY_EMAIL", "").strip().lower()
FAKE_NOW = os.environ.get("NOW")
START = dt.datetime.now(dt.timezone.utc)

# Same as the app's pairCurrencies().
INDEX_CUR = {"US30": "USD", "NAS100": "USD", "US100": "USD", "SPX500": "USD", "US500": "USD", "DJI": "USD", "USOIL": "USD",
             "GER40": "EUR", "DE40": "EUR", "DAX": "EUR", "UK100": "GBP", "FTSE": "GBP", "JP225": "JPY", "AUS200": "AUD"}


def pair_currencies(pair):
    p = re.sub(r"[^A-Z0-9]", "", str(pair or "").upper())
    if p in INDEX_CUR:
        return [INDEX_CUR[p]]
    if re.fullmatch(r"[A-Z]{6}", p):
        return [c for c in (p[:3], p[3:]) if c not in ("XAU", "XAG", "BTC", "ETH")]
    return []


def now():
    if FAKE_NOW:  # tests: the fake clock moves with the real one
        return dt.datetime.fromisoformat(FAKE_NOW.replace("Z", "+00:00")) + (dt.datetime.now(dt.timezone.utc) - START)
    return dt.datetime.now(dt.timezone.utc)


def when(e):
    return dt.datetime.fromisoformat(e["t"].replace("Z", "+00:00"))


def slots(events, until):
    """High-impact events from now until `until`, grouped by start time: [(time, [events])]."""
    t0, out = now(), {}
    for e in events:
        if e.get("impact") == "High" and t0 + dt.timedelta(minutes=1) < when(e) <= until:
            out.setdefault(when(e), []).append(e)
    return sorted(out.items())


class Person:
    def __init__(self, u, s, trades, devs):
        self.id, self.email, self.s, self.trades, self.devs = u["id"], (u.get("email") or "").lower(), s, trades, devs
        try:
            self.tz = ZoneInfo(str(s.get("pushTz") or "Europe/Dublin"))
        except Exception:
            self.tz = ZoneInfo("Europe/Dublin")
        listed = s.get("pairs") if isinstance(s.get("pairs"), list) else []
        self.curs = {c for p in [*listed, *(t.get("pair") for t in trades)] for c in pair_currencies(p)}
        self.cur = re.sub(r"[<>&\"'`\\]", "", str(s.get("currency") or "$")).strip()[:4] or "$"

    def local(self, at=None):
        return (at or now()).astimezone(self.tz)

    def quiet(self, at=None):
        """True inside the person's quiet hours (e.g. 23:00 to 07:00, across midnight)."""
        if not self.s.get("pushQuiet"):
            return False
        t, a, b = self.local(at).strftime("%H:%M"), hhmm(self.s.get("pushQuietFrom"), "23:00"), hhmm(self.s.get("pushQuietTo"), "07:00")
        return (a <= t < b) if a <= b else (t >= a or t < b)

    def money(self, v):
        return ("−" if v < 0 else "") + f"{self.cur}{abs(v):,.0f}"


def hhmm(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else default


def people():
    """Everyone with at least one device: [Person]."""
    from weekly_review import all_rows, all_users, clean_trade  # same Supabase readers as the weekly email
    devs = push.devices()
    if not devs:
        return []
    settings = {r["user_id"]: (r.get("data") if isinstance(r.get("data"), dict) else {}) for r in all_rows("journal_settings")}
    trades = {}
    for r in all_rows("trades"):
        if r["user_id"] in devs:
            t = clean_trade(r.get("data"))
            if t:
                trades.setdefault(r["user_id"], []).append(t)
    return [Person(u, settings.get(u["id"], {}), trades.get(u["id"], []), devs[u["id"]]) for u in all_users() if u["id"] in devs]


def notify(signer, p, title, body, url, tag, ttl):
    return sum(push.send(signer, d, title, body, url, tag, ttl) for d in p.devs)


# ---------- Prop firm limits ----------
def prop_alerts(signer, who):
    sent = 0
    for p in who:
        if not p.s.get("pushProp") or p.quiet():
            continue
        today = p.local().date().isoformat()
        for a in p.s.get("accounts") or []:
            if not isinstance(a, dict) or a.get("archived") or a.get("type") != "Prop firm":
                continue
            st = prop_status.status(a, p.trades, today, p.tz, now())
            if not st:
                continue
            name = str(a.get("name") or a.get("firm") or "Prop account")[:40]
            if st["breach"] and st["breach"]["date"] < today:
                continue  # already lost before today: nothing new to warn about
            msgs = []
            if st["daily_limit"]:
                used = st["daily_used"] / st["daily_limit"]
                left = st["daily_limit"] - st["daily_used"]
                if used >= 1:
                    msgs.append(("daily100", f"{name}: daily loss limit reached",
                                 f"Today's loss is {p.money(st['daily_used'])}, at or past the {p.money(st['daily_limit'])} limit (closed trades). Check your firm's dashboard."))
                elif used >= 0.8:
                    msgs.append(("daily80", f"{name}: {used:.0%} of today's loss limit used",
                                 f"{p.money(st['daily_used'])} of your {p.money(st['daily_limit'])} daily limit is used. {p.money(left)} left today."))
            if st["max_allow"] and st["last_day"]:
                used = 1 - st["max_room"] / st["max_allow"]
                if used >= 1:
                    msgs.append(("max100", f"{name}: max loss reached",
                                 f"The balance is at or below the {p.money(st['floor'])} max-loss floor (closed trades). Check your firm's dashboard."))
                elif used >= 0.8:
                    msgs.append(("max80", f"{name}: {used:.0%} of max loss used",
                                 f"{p.money(st['max_room'])} left above the {p.money(st['floor'])} max-loss floor."))
            for level, title, body in msgs:
                # Daily ones once a day; max ones once per new trading day, so a recovered account can warn again.
                day = today if level.startswith("daily") else st["last_day"]
                base = f"prop:{p.id}:{a.get('id')}:{level.rstrip('018')}"  # e.g. prop:<user>:<account>:daily
                if level.endswith("80") and push.claimed(f"{base}100:{day}"):
                    continue  # already told them the limit was hit
                if push.claim(f"{base}{level[-3:] if level.endswith('100') else level[-2:]}:{day}"):
                    sent += notify(signer, p, title, body, "./?app&open=accounts", f"prop-{a.get('id')}-{level.rstrip('018')}", 6 * 3600)
    return sent


# ---------- Journal reminder ----------
def reminders(signer, who):
    sent = 0
    for p in who:
        if not p.s.get("pushRemind"):
            continue
        loc = p.local()
        if loc.weekday() >= 5:
            continue  # weekdays only
        at = hhmm(p.s.get("pushRemindAt"), "21:00")
        due = loc.replace(hour=int(at[:2]), minute=int(at[3:]), second=0, microsecond=0)
        if not (due <= loc < due + dt.timedelta(hours=3)):
            continue  # runs are 30 minutes apart and sometimes late: anywhere in the 3 hours after counts
        today = loc.date().isoformat()
        week_ago = (loc.date() - dt.timedelta(days=7)).isoformat()
        open_n = sum(1 for t in p.trades if t.get("status") == "open")
        logged_today = any(str(t.get("date") or "") == today for t in p.trades)
        recent = any(week_ago <= str(t.get("date") or "") < today for t in p.trades)
        if open_n:
            title = f"You have {open_n} open trade{'s' if open_n != 1 else ''}"
            body = f"Close {'them' if open_n != 1 else 'it'} in your journal once {'they are' if open_n != 1 else 'it is'} done, while the details are fresh."
            url = "./?app&open=overview"
        elif recent and not logged_today:
            title, body, url = "Did you trade today?", "Log it in ELEV8 while it's fresh. Your Sunday review is only as good as your journal.", "./?app&open=log"
        else:
            continue
        if push.claim(f"remind:{p.id}:{today}"):
            sent += notify(signer, p, title, body, url, "journal-reminder", 3 * 3600)
    return sent


def message(evs, minutes):
    """Title and body for the events at one time, e.g. 'USD CPI m/m in 15 minutes'."""
    first, rest = evs[0], evs[1:]
    lead = ("now" if minutes <= 0 else f"in {minutes} minute{'s' if minutes != 1 else ''}" if minutes < 60
            else f"in {minutes // 60}h {minutes % 60}m")
    title = f"{first['cur']} {first['title']} {lead}"
    also = ", ".join(f"{e['cur']} {e['title']}" for e in rest[:3]) + (f" and {len(rest) - 3} more" if len(rest) > 3 else "")
    body = ("Also at the same time: " + also + ". " if rest else "High-impact news. ") + "Check your open trades and your prop firm's news rules."
    return title, body


def main():
    if not push.KEY:
        sys.exit("Missing GitHub secret: SUPABASE_SERVICE_KEY. Add it in Settings > Secrets and variables > Actions.")
    _, signer = push.keys()  # also makes the key pair on the very first run
    who = people()
    if ONLY:
        who = [p for p in who if p.email == ONLY]
    elif who:
        print(f"prop limit alerts: sent to {prop_alerts(signer, who)} device(s); reminders: sent to {reminders(signer, who)} device(s)")
    events = json.loads((ROOT / "docs" / "calendar.json").read_text(encoding="utf-8")).get("events", [])
    if ONLY:  # a test: the next high-impact event, sent straight away to that one account
        upcoming = slots(events, now() + dt.timedelta(days=14))[:1]
        if not upcoming:
            sys.exit("No high-impact news in the calendar to test with.")
    else:
        upcoming = slots(events, now() + AHEAD)
    if not upcoming:
        print("no high-impact news in the next", int(AHEAD.total_seconds() // 60), "minutes")
    newsy = [p for p in who if ONLY or p.s.get("pushNews")]
    if upcoming:
        print(f"{len(upcoming)} news time(s) coming up; {len(newsy)} account(s) with news alerts on")
    for at, evs in upcoming:
        wait = (at - LEAD - now()).total_seconds()
        if wait > 0 and not ONLY:
            print(f"waiting {int(wait // 60)} min for {at:%H:%M} UTC")
            time.sleep(wait)
        if when(evs[0]) <= now():
            continue  # already out: too late to warn anyone
        minutes = max(0, round((at - now()).total_seconds() / 60))
        sent = 0
        for p in newsy:
            mine = evs if ONLY else [e for e in evs if not p.curs or e["cur"] in p.curs]  # a test always sends
            if not mine or (not ONLY and p.quiet()):
                continue
            # One alert per person per time slot, claimed first so a second run can't repeat it.
            if not ONLY and not push.claim(f"news:{at:%Y-%m-%dT%H:%MZ}:{p.id}"):
                continue
            title, body = message(mine, minutes)
            if ONLY:
                title = "Test: " + title
            ttl = max(60, int((at - now()).total_seconds()))  # no use arriving after the news
            sent += notify(signer, p, title, body, "./?app&open=news", f"news-{at:%Y%m%d%H%M}", ttl)
        print(f"{at:%Y-%m-%d %H:%M} UTC ({', '.join(e['cur'] + ' ' + e['title'] for e in evs)}): sent to {sent} device(s)")
    if not ONLY:
        push.tidy_log()


if __name__ == "__main__":
    main()
