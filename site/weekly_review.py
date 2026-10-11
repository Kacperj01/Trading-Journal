"""Email each opted-in user their ELEV8 weekly review (run every Sunday by the weekly-review Action).

Reads trades and settings from Supabase with the service key, builds the same review the app's
Insights tab shows (what worked, what cost you, focus for next week), and sends it through Resend
from reviews@elev8tradingjournal.com.

Environment:
  SUPABASE_SERVICE_KEY  Supabase secret (service_role) key        - GitHub secret
  RESEND_API_KEY        Resend API key                            - GitHub secret
  ONLY_EMAIL            optional: send only to this address (a test), even if not opted in
  DRY_RUN               optional: "1" writes the emails to site/weekly-preview/ instead of sending
  RESEND_URL, SUPABASE_URL  optional overrides (tests)
"""
import datetime as dt
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SB_URL = os.environ.get("SUPABASE_URL") or json.loads((ROOT / "site" / "config.json").read_text())["supabaseUrl"]
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_URL = os.environ.get("RESEND_URL", "https://api.resend.com/emails")
FROM = os.environ.get("MAIL_FROM", "ELEV8 Weekly Review <reviews@elev8tradingjournal.com>")
SITE = "https://elev8tradingjournal.com"
ONLY = os.environ.get("ONLY_EMAIL", "").strip().lower()
DRY = os.environ.get("DRY_RUN") == "1"


# ---------- Supabase ----------
def sb_get(path, extra=None):
    headers = {"apikey": KEY, "Accept": "application/json"}
    if KEY.startswith("eyJ"):  # legacy service_role JWT; new sb_secret_ keys go in apikey only
        headers["Authorization"] = "Bearer " + KEY
    headers.update(extra or {})
    req = urllib.request.Request(SB_URL.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)


def all_users():
    out, page = [], 1
    while True:
        data = sb_get(f"/auth/v1/admin/users?page={page}&per_page=200")
        batch = data.get("users", data if isinstance(data, list) else [])
        out += batch
        if len(batch) < 200:
            return out
        page += 1


def all_rows(table):
    out, start = [], 0
    while True:
        batch = sb_get(f"/rest/v1/{table}?select=user_id,data&order=user_id", {"Range-Unit": "items", "Range": f"{start}-{start + 999}"})
        out += batch
        if len(batch) < 1000:
            return out
        start += 1000


# ---------- Review (same rules as the app's weekly review) ----------
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def stats(ts):
    pn = [num(t.get("pnl")) for t in ts]
    wins, losses = [p for p in pn if p > 0], [p for p in pn if p < 0]
    run = longest = 0
    for p in pn:
        run = run + 1 if p < 0 else 0
        longest = max(longest, run)
    gross_loss = -sum(losses)
    return {"n": len(ts), "wins": len(wins), "losses": len(losses), "total": sum(pn),
            "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else 0,
            "pf": (sum(wins) / gross_loss) if gross_loss else (float("inf") if wins else 0), "longest_loss": longest}


def group(ts, key):
    g = {}
    for t in ts:
        g.setdefault(t.get(key) or "Unspecified", []).append(t)
    out = []
    for name, items in g.items():
        s = stats(items)
        out.append({"name": name, "n": s["n"], "wins": s["wins"], "losses": s["losses"], "pnl": s["total"]})
    return sorted(out, key=lambda x: -x["pnl"])


def build_week(trades, start, cur):
    end = start + dt.timedelta(days=6)
    iso = lambda d: d.isoformat()
    in_week = lambda s, e: sorted([t for t in trades if iso(s) <= str(t.get("date", "")) <= iso(e)], key=lambda t: (t.get("date", ""), t.get("time") or ""))
    week, prev = in_week(start, end), in_week(start - dt.timedelta(days=7), end - dt.timedelta(days=7))
    st, pv = stats(week), stats(prev)

    def money(v, signed=True):
        s = f"{cur}{abs(v):,.2f}"
        return (("+" if v > 0 else "−" if v < 0 else "") + s) if signed else s
    rec = lambda g: f"{g['wins']}W–{g['losses']}L"
    b = lambda x: f"<b>{html.escape(str(x))}</b>"
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"

    followed = [t for t in week if t.get("followedPlan") is not False]
    broke = [t for t in week if t.get("followedPlan") is False]
    setups, sessions, pairs = group(week, "setup"), group(week, "session"), group(week, "pair")
    emos = group([t for t in week if t.get("emotionBefore")], "emotionBefore")
    mistakes = {}
    for t in week:
        for m in [x.strip() for x in str(t.get("mistakes") or "").split(",") if x.strip()]:
            mistakes.setdefault(m, [0, 0.0])
            mistakes[m][0] += 1
            mistakes[m][1] += num(t.get("pnl"))
    top_mistakes = sorted(mistakes.items(), key=lambda kv: (-kv[1][0], kv[1][1]))

    worked, cost, focus = [], [], []
    losing = sorted([g for g in setups if g["pnl"] < 0], key=lambda g: (-(g["n"] >= 2), g["pnl"]))[:2]
    best_setup = next((g for g in setups if g["pnl"] > 0), None)
    if best_setup: worked.append(f"{b(best_setup['name'])} went {rec(best_setup)} for {b(money(best_setup['pnl']))}.")
    bs = next((g for g in sessions if g["pnl"] > 0), None)
    if bs: worked.append(f"{b(bs['name'])} was your best session: {b(money(bs['pnl']))} ({rec(bs)}).")
    bp = next((g for g in pairs if g["pnl"] > 0), None)
    if bp: worked.append(f"{b(bp['name'])} made {b(money(bp['pnl']))} from {plural(bp['n'], 'trade')}.")
    be = next((g for g in emos if g["pnl"] > 0 and g["n"] >= 2), None)
    if be: worked.append(f"Trades taken feeling {b(be['name'].lower())} returned {b(money(be['pnl']))} ({rec(be)}).")
    fp = sum(num(t.get("pnl")) for t in followed)
    if followed and fp > 0: worked.append(f"Following your plan made {b(money(fp))} over {plural(len(followed), 'trade')}.")

    for g in losing: cost.append(f"{b(g['name'])} went {rec(g)} for {b(money(g['pnl']))}.")
    ws = ([g for g in sessions if g["pnl"] < 0] or [None])[-1]
    if ws: cost.append(f"{b(ws['name'])} lost {b(money(ws['pnl']))} ({rec(ws)}).")
    we = ([g for g in emos if g["pnl"] < 0 and g["n"] >= 2] or [None])[-1]
    if we: cost.append(f"Trades taken feeling {b(we['name'].lower())}: {rec(we)}, {b(money(we['pnl']))}.")
    if broke: cost.append(f"{plural(len(broke), 'trade')} broke your plan, for {b(money(sum(num(t.get('pnl')) for t in broke)))}.")
    if top_mistakes: cost.append("Mistakes logged: " + ", ".join(f"{html.escape(m)} ×{v[0]}" for m, v in top_mistakes[:3]) + ".")
    if st["longest_loss"] >= 3: cost.append(f"A losing run of {b(st['longest_loss'])} trades in a row.")

    if we: focus.append(f"If you feel {html.escape(we['name'].lower())}, skip the trade. Those entries went {rec(we)} this week.")
    if mistakes.get("Closed too early", [0])[0] >= 2: focus.append(f"Let winners reach take profit. You closed early {mistakes['Closed too early'][0]} times; set the TP and step away.")
    if st["longest_loss"] >= 3 and len(focus) < 3: focus.append("Use a daily stop: after 2 losses in a row, finish for the day.")
    if broke and len(focus) < 3: focus.append(f"Stick to the plan. Plan-breaking trades returned {money(sum(num(t.get('pnl')) for t in broke))}.")
    if best_setup and len(focus) < 3: focus.append(f"Prioritise {html.escape(best_setup['name'])} setups. They were your edge this week ({rec(best_setup)}).")
    if losing and len(focus) < 3: focus.append(f"Tighten {html.escape(losing[0]['name'])} entries: wait for confirmation before committing.")

    delta = st["total"] - pv["total"]
    if not week: verdict = "No trades logged this week."
    elif st["total"] > 0 and st["pf"] >= 1.5:
        verdict = f"Strong week. You finished {b(money(st['total']))} across {plural(st['n'], 'trade')}" + (f", {'up' if delta >= 0 else 'down'} {b(money(abs(delta), False))} on last week." if prev else ".")
    elif st["total"] > 0: verdict = f"Positive week: {b(money(st['total']))} from {plural(st['n'], 'trade')}. Solid, with room to tighten up."
    elif st["total"] == 0: verdict = f"Flat week across {plural(st['n'], 'trade')}."
    else: verdict = f"Tough week: {b(money(st['total']))} across {plural(st['n'], 'trade')}. The notes below show where it went."

    days = []
    for i in range(7):
        d = start + dt.timedelta(days=i)
        ts = [t for t in week if t.get("date") == d.isoformat()]
        days.append((d, len(ts), sum(num(t.get("pnl")) for t in ts)))
    pf = "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return {"start": start, "end": end, "st": st, "prev": pv, "verdict": verdict, "worked": worked, "cost": cost,
            "focus": focus[:3], "days": days, "money": money, "pf": pf, "plan_rate": (len(followed) / len(week)) if week else 0}


# ---------- Email ----------
def render(w, name):
    st, money = w["st"], w["money"]
    rng = f"{w['start'].strftime('%-d %b')} – {w['end'].strftime('%-d %b %Y')}"
    col = lambda v: "#13955a" if v > 0 else "#d8344f" if v < 0 else "#5d6d84"
    kpi = lambda label, value, color="#0d1b2e": f'<td style="padding:12px 10px;background:#f3f6fb;border-radius:10px;text-align:center" width="25%"><div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#5d6d84">{label}</div><div style="font:600 18px Menlo,Consolas,monospace;color:{color};margin-top:4px">{value}</div></td>'
    lst = lambda items, empty: "".join(f'<li style="margin:0 0 8px">{x}</li>' for x in items) or f'<li style="color:#5d6d84">{empty}</li>'
    biggest = max([abs(p) for _, _, p in w["days"]] + [1])
    bars = "".join(
        f'<td style="vertical-align:bottom;text-align:center;padding:0 3px" width="14%">'
        f'<div style="height:{max(4, int(56 * abs(p) / biggest)) if n else 4}px;background:{col(p) if n else "#e3ebf5"};border-radius:4px"></div>'
        f'<div style="font-size:11px;color:#5d6d84;margin-top:6px">{d.strftime("%a")}</div>'
        f'<div style="font:600 11px Menlo,Consolas,monospace;color:{col(p)}">{money(p) if n else "–"}</div></td>' for d, n, p in w["days"])
    section = lambda title, color, body: f'<tr><td style="padding:18px 24px 0"><div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{color};margin-bottom:8px">{title}</div><ul style="margin:0;padding-left:18px;color:#33445c;font-size:14px;line-height:1.5">{body}</ul></td></tr>'
    hello = html.escape(name.split()[0]) if name else "there"
    return f"""<!doctype html><html><body style="margin:0;background:#eef3f9;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef3f9;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden">
<tr><td style="background:#06111f;padding:22px 24px">
  <table role="presentation" cellpadding="0" cellspacing="0"><tr>
    <td><img src="{SITE}/icons/icon-192.png" width="40" height="40" alt="ELEV8" style="display:block;border-radius:10px"></td>
    <td style="padding-left:12px"><div style="font-weight:800;font-size:20px;letter-spacing:2px;color:#4a9af0">ELEV8</div><div style="font-size:10px;letter-spacing:3px;color:#25c0c0">WEEKLY REVIEW</div></td>
  </tr></table>
</td></tr>
<tr><td style="padding:22px 24px 4px"><div style="font-size:13px;color:#5d6d84">{rng}</div><div style="font-size:20px;font-weight:700;color:#0d1b2e;margin-top:4px">Hi {hello}, here's your week</div>
<p style="font-size:15px;color:#33445c;line-height:1.5;margin:10px 0 0">{w['verdict']}</p></td></tr>
<tr><td style="padding:16px 18px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="6"><tr>
{kpi("P&amp;L", money(st['total']), col(st['total']))}{kpi("Trades", st['n'])}{kpi("Win rate", f"{st['win_rate']:.0%}")}{kpi("Profit factor", w['pf'])}
</tr></table></td></tr>
<tr><td style="padding:16px 24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="height:100px"><tr>{bars}</tr></table></td></tr>
{section("What worked", "#13955a", lst(w['worked'], "Nothing stood out this week."))}
{section("What cost you", "#d8344f", lst(w['cost'], "No costly patterns. Nice."))}
{section("Focus for next week", "#1f6fc4", lst(w['focus'], "Keep doing what you're doing."))}
<tr><td style="padding:22px 24px 26px" align="center"><a href="{SITE}/#insights" style="display:inline-block;background:#1f6fc4;background-image:linear-gradient(120deg,#2a7fd9,#25c0c0);color:#ffffff;text-decoration:none;font-weight:600;padding:12px 22px;border-radius:10px">Open your journal</a></td></tr>
</table>
<p style="font-size:12px;color:#5d6d84;margin:14px 0 0;max-width:600px">You're getting this because weekly reviews are on in ELEV8 › Settings › Profile. Turn them off there any time.</p>
</td></tr></table></body></html>"""


def send(to, subject, body):
    if DRY:
        out = ROOT / "site" / "weekly-preview"
        out.mkdir(exist_ok=True)
        (out / f"{to.replace('@', '_at_')}.html").write_text(body, encoding="utf-8")
        print("  wrote preview for", to)
        return
    data = json.dumps({"from": FROM, "to": [to], "subject": subject, "html": body, "reply_to": "noreply@elev8tradingjournal.com"}).encode()
    req = urllib.request.Request(RESEND_URL, data=data, method="POST", headers={"Authorization": "Bearer " + RESEND_KEY, "Content-Type": "application/json", "User-Agent": "elev8-weekly-review"})
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()
    time.sleep(0.6)  # stay under Resend's 2 requests/second


def main():
    missing = [n for n, v in (("SUPABASE_SERVICE_KEY", KEY), ("RESEND_API_KEY", RESEND_KEY or DRY)) if not v]
    if missing:
        sys.exit("Missing GitHub secrets: " + ", ".join(missing) + ". Add them in Settings > Secrets and variables > Actions.")
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=today.weekday())  # Monday of this week (the job runs on Sunday)
    settings = {r["user_id"]: r.get("data") or {} for r in all_rows("journal_settings")}
    trades = {}
    for r in all_rows("trades"):
        trades.setdefault(r["user_id"], []).append(r.get("data") or {})
    sent = skipped = 0
    for u in all_users():
        email = (u.get("email") or "").lower()
        s = settings.get(u["id"], {})
        if ONLY:
            if email != ONLY: continue
        elif not s.get("weeklyEmail") or not u.get("email_confirmed_at"):
            continue
        w = build_week(trades.get(u["id"], []), start, s.get("currency") or "$")
        if not w["st"]["n"] and not ONLY:
            skipped += 1  # nothing logged this week: no email
            continue
        name = (u.get("user_metadata") or {}).get("full_name", "")
        subject = f"Your ELEV8 week: {w['money'](w['st']['total'])} · {w['st']['n']} trades · {w['st']['win_rate']:.0%} win rate"
        try:
            send(u["email"], subject, render(w, name))
            sent += 1
        except Exception as exc:  # one bad address shouldn't stop the rest
            print("  could not send to", email, "-", exc, file=sys.stderr)
    print(f"week of {start}: sent {sent}, skipped {skipped} (no trades)")
    if ONLY and not sent:
        sys.exit(f"No account found for {ONLY}")


if __name__ == "__main__":
    main()
