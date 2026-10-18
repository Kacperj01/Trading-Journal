"""Fetch the European Central Bank's daily reference exchange rates and save them as
docs/rates.json (units of each currency per 1 US dollar), for the position size calculator.

Source: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml (updated once a
working day around 16:00 CET). Runs alongside the calendar job; the file is only
rewritten when the rates change.
"""
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
OUT = Path(__file__).resolve().parent.parent / "docs" / "rates.json"


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "ELEV8-Trading-Journal/1.0 (+https://elev8tradingjournal.com)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        root = ET.fromstring(res.read())
    day, eur = None, {"EUR": 1.0}
    for el in root.iter():
        if el.tag.endswith("Cube") and el.get("time"):
            day = el.get("time")
        if el.tag.endswith("Cube") and el.get("currency") and el.get("rate"):
            eur[el.get("currency").upper()] = float(el.get("rate"))
    if not day or "USD" not in eur:
        raise ValueError("unexpected ECB feed format")
    usd = eur["USD"]
    rates = {c: round(v / usd, 6) for c, v in sorted(eur.items())}
    rates["USD"] = 1.0
    return {"date": day, "source": "European Central Bank", "base": "USD", "rates": rates}


def main():
    try:
        data = fetch()
    except Exception as e:  # keep the last good file
        print("rates: fetch failed:", e, file=sys.stderr)
        return
    old = None
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if old == data:
        print("rates: unchanged", data["date"])
        return
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print("rates: saved", data["date"], len(data["rates"]), "currencies")


if __name__ == "__main__":
    main()
