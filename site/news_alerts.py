"""Notify people 15 minutes before high-impact news for the currencies they trade.

Run every 30 minutes by the news-alerts GitHub Action. Each run looks at the high-impact events in
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


def people():
    """Everyone with news alerts on and at least one device: [(user_id, email, currencies, devices)]."""
    from weekly_review import all_rows, all_users, clean_trade  # same Supabase readers as the weekly email
    devs = push.devices()
    if not devs:
        return []
    settings = {r["user_id"]: (r.get("data") if isinstance(r.get("data"), dict) else {}) for r in all_rows("journal_settings")}
    pairs = {}
    for r in all_rows("trades"):
        t = clean_trade(r.get("data"))
        if t and t.get("pair"):
            pairs.setdefault(r["user_id"], set()).add(t["pair"])
    out = []
    for u in all_users():
        s, email = settings.get(u["id"], {}), (u.get("email") or "").lower()
        if u["id"] not in devs or (ONLY and email != ONLY) or (not ONLY and not s.get("pushNews")):
            continue
        listed = s.get("pairs") if isinstance(s.get("pairs"), list) else []
        curs = {c for p in [*listed, *pairs.get(u["id"], ())] for c in pair_currencies(p)}
        out.append((u["id"], email, curs, devs[u["id"]]))
    return out


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
    events = json.loads((ROOT / "docs" / "calendar.json").read_text(encoding="utf-8")).get("events", [])
    if ONLY:  # a test: the next high-impact event, sent straight away to that one account
        upcoming = slots(events, now() + dt.timedelta(days=14))[:1]
        if not upcoming:
            sys.exit("No high-impact news in the calendar to test with.")
    else:
        upcoming = slots(events, now() + AHEAD)
    if not upcoming:
        print("no high-impact news in the next", int(AHEAD.total_seconds() // 60), "minutes")
        return
    who = people()
    print(f"{len(upcoming)} news time(s) coming up; {len(who)} account(s) with news alerts on")
    for at, evs in upcoming:
        wait = (at - LEAD - now()).total_seconds()
        if wait > 0 and not ONLY:
            print(f"waiting {int(wait // 60)} min for {at:%H:%M} UTC")
            time.sleep(wait)
        if when(evs[0]) <= now():
            continue  # already out: too late to warn anyone
        minutes = max(0, round((at - now()).total_seconds() / 60))
        sent = 0
        for uid, email, curs, devs in who:
            mine = evs if ONLY else [e for e in evs if not curs or e["cur"] in curs]  # a test always sends
            if not mine:
                continue
            # One alert per person per time slot, claimed first so a second run can't repeat it.
            key = f"news:{at:%Y-%m-%dT%H:%MZ}:{uid}" + (":test" if ONLY else "")
            if not ONLY and not push.claim(key):
                continue
            title, body = message(mine, minutes)
            if ONLY:
                title = "Test: " + title
            ttl = max(60, int((at - now()).total_seconds()))  # no use arriving after the news
            for d in devs:
                sent += push.send(signer, d, title, body, "./?app&open=news", f"news-{at:%Y%m%d%H%M}", ttl)
        print(f"{at:%Y-%m-%d %H:%M} UTC ({', '.join(e['cur'] + ' ' + e['title'] for e in evs)}): sent to {sent} device(s)")
    if not ONLY:
        push.tidy_log()


if __name__ == "__main__":
    main()
