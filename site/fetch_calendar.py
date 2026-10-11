"""Fetch this week's economic calendar and save it as docs/calendar.json for the app.

Source: the free weekly calendar feed published by Fair Economy, the company behind
Forex Factory (https://nfs.faireconomy.media/ff_calendar_thisweek.json). The feed asks
for light use, so this runs from a GitHub Action every few hours, never from the app.

Past weeks are kept (up to ~6 months) so the journal can later match trades to the news
around them. The file is only rewritten when the events change, so the Action doesn't
commit when nothing is new.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
OUT = Path(__file__).resolve().parent.parent / "docs" / "calendar.json"
KEEP_DAYS = 190
IMPACTS = {"High", "Medium", "Low", "Holiday", "Non-Economic"}


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "ELEV8-Trading-Journal/1.0 (+https://github.com/Kacperj01/Trading-Journal)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.load(res)
    if not isinstance(data, list):
        raise ValueError("unexpected feed format")
    events = []
    for e in data:
        if not isinstance(e, dict) or not e.get("title") or not e.get("date"):
            continue
        when = datetime.fromisoformat(str(e["date"]))  # e.g. 2026-10-12T08:30:00-04:00
        impact = str(e.get("impact") or "Low")
        events.append({
            "t": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cur": str(e.get("country") or "").upper()[:4],
            "title": str(e["title"]).strip()[:120],
            "impact": impact if impact in IMPACTS else "Low",
            "forecast": str(e.get("forecast") or "").strip()[:24],
            "previous": str(e.get("previous") or "").strip()[:24],
        })
    if not events:
        raise ValueError("feed had no events")
    return events


def main():
    fresh = fetch()
    old = []
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8")).get("events", [])
        except (ValueError, AttributeError):
            old = []
    # The feed covers one week: replace that week's span, keep older weeks as history.
    start = min(e["t"] for e in fresh)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = [e for e in old if cutoff <= e.get("t", "") < start]
    events = sorted(kept + fresh, key=lambda e: (e["t"], e["cur"], e["title"]))
    if events == old:
        print("calendar unchanged")
        return
    OUT.write_text(json.dumps({
        "source": "Forex Factory calendar feed (nfs.faireconomy.media)",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": events,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"calendar updated: {len(fresh)} this week, {len(events)} total")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # leave the last good file in place
        print("calendar fetch failed:", exc, file=sys.stderr)
        sys.exit(1)
