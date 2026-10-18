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
import re
import sys
import time
import urllib.error
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
# One-off: every confirmed account gets a preview of their week, even if weekly emails are off.
PREVIEW_ALL = os.environ.get("PREVIEW_ALL") in ("1", "true")
DRY = os.environ.get("DRY_RUN") == "1"


# ---------- Supabase ----------
def sb_get(path, extra=None):
    headers = {"apikey": KEY, "Accept": "application/json"}
    if KEY.startswith("eyJ"):  # legacy service_role JWT; new sb_secret_ keys go in apikey only
        headers["Authorization"] = "Bearer " + KEY
    headers.update(extra or {})
    req = urllib.request.Request(SB_URL.rstrip("/") + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.load(res)
    except urllib.error.HTTPError as exc:  # say what Supabase said, not just the status code
        detail = exc.read().decode("utf-8", "replace")[:300]
        hint = ""
        if exc.code in (401, 403):
            hint = (" -> Check SUPABASE_SERVICE_KEY is the SECRET key (service_role / sb_secret_...), not the publishable/anon key,"
                    " and that site/supabase-setup.sql's grants to service_role have been run.")
        sys.exit(f"Supabase refused {path.split('?')[0]} ({exc.code}): {detail}{hint}")


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


# Same rules as the app: a result under a tenth of the trade's risk (or the default risk; with neither,
# under 0.02% of the account) is a scratch, counted as breakeven rather than a win or a loss.
CTX = {"risk": 0.0, "sizes": {}}


def scratch_size(t):
    risk = num(t.get("risk")) if num(t.get("risk")) > 0 else CTX["risk"]
    return risk * 0.1 if risk > 0 else CTX["sizes"].get(t.get("account"), 0.0) * 0.0002


def result(t):
    p = num(t.get("pnl"))
    return "BE" if abs(p) < scratch_size(t) else "Win" if p > 0 else "Loss"


NOTE_TAGS = {
    "invalid": re.compile(r"\b(invalid(ated)?|no longer valid|setup (was )?(broke|broken|failed)|thesis (was )?wrong|structure (broke|shifted)|didn'?t (play|work) out)\b", re.I),
    "early": re.compile(r"\b(clos(ed|ing)|cut|exit(ed)?|took (it )?off|got out)\b[^.]{0,20}\b(early|before (tp|target))\b|\bmanual(ly)? clos|\bscratch(ed)?\b", re.I),
    "breakeven": re.compile(r"\b(moved|move|put)\b[^.]{0,12}\b(sl|stop|stop loss)\b[^.]{0,8}\b(to )?(be|break ?even)\b|\bstopped (out )?at (be|break ?even)\b", re.I),
    "news": re.compile(r"\b(news|nfp|cpi|fomc|rate decision|powell)\b", re.I),
    "emotional": re.compile(r"\b(revenge|fomo|tilt(ed)?|greed(y)?|scared|fear(ful)?|impatien(t|ce)|bored|overtrad(e|ed|ing)|chas(e|ed|ing))\b", re.I),
}


def note_tags(t):
    text = f"{t.get('notes') or ''} {t.get('mistakes') or ''}"
    return [k for k, rx in NOTE_TAGS.items() if rx.search(text)]


# Mistakes are typed freely; the review names them in standard trading terms rather than quoting them.
MISTAKE_TYPES = [
    ("early_exit", "exit before target", r"\b(clos(e|ed|ing)|exit(ed)?|took (profit|it off)|cut)\b[^,.]{0,15}\b(too )?early\b|\bcut (the |my )?winners?\b|\bpanic(ked)? clos"),
    ("news", "position held through high-impact news", r"\b(news|nfp|cpi|fomc|powell|rate decision)\b"),
    ("no_stop", "no stop loss in place", r"\bno (stop|sl)\b|\bwithout (a |my )?(stop|sl)\b"),
    ("moved_stop", "stop loss moved against the plan", r"\b(mov(e|ed|ing)|widen(ed)?)\b[^,.]{0,10}\b(stop|sl)\b"),
    ("size", "position size above plan", r"\bover ?(si[sz]ed?|leverag\w*|risk\w*)|\btoo (big|large|much risk)|\blot size|\brisked too much"),
    ("late", "late entry after the move", r"\b(late entry|entered late|chas(e|ed|ing) (price|the move|it))\b"),
    ("early_entry", "entry before confirmation", r"\b(enter(ed)?|entry|jump(ed)? in)\b[^,.]{0,10}\b(early|too soon)\b|\bno confirm|\bwithout confirm|\bbefore confirm|\bdidn'?t wait"),
    ("held_long", "held past the planned exit", r"\bheld (it )?too long|\bdidn'?t take (profit|tp)|\bgave (it )?back"),
    ("influence", "trade influenced by outside opinion", r"\boutside influence|\b(signal|discord|telegram|twitter|someone|friend|group|copied|copy ?trad)"),
    ("overtrading", "overtrading", r"\bover ?trad|\btoo many trades"),
    ("emotional", "emotion-driven decision", r"\b(revenge|fomo|greed(y)?|fear(ful)?|scared|tilt(ed)?|impatien\w*|bored)\b"),
    ("off_plan", "setup outside the trading plan", r"\b(not (my|in (my|the)) (setup|plan)|off[- ]?plan|wrong setup|no setup|random (trade|entry))\b"),
    ("counter_trend", "trade against the higher-timeframe bias", r"\b(against (the )?(trend|htf|bias)|counter[- ]?trend)\b"),
]
MISTAKE_RX = [(k, label, re.compile(rx, re.I)) for k, label, rx in MISTAKE_TYPES]


def mistake_type(m):
    for k, label, rx in MISTAKE_RX:
        if rx.search(m):
            return k, label
    tidy = re.sub(r"[.!]+$", "", re.sub(r"\s+", " ", m.strip()))
    tidy = re.sub(r"\b(did|do|was|is|could|should|would|can)nt\b", r"\1n't", tidy, flags=re.I)
    tidy = re.sub(r"\bcant\b", "can't", tidy, flags=re.I)
    tidy = re.sub(r"\bwont\b", "won't", tidy, flags=re.I)
    tidy = re.sub(r"\bi\b", "I", tidy)
    return "x:" + tidy.lower(), tidy[:1].lower() + tidy[1:]


def emo_word(e):
    return e if e == e.upper() else e.lower()


def cut_for_invalid(t):
    tags, v = note_tags(t), num(t.get("pnl"))
    risk = num(t.get("risk")) if num(t.get("risk")) > 0 else scratch_size(t) * 10
    return ("invalid" in tags or ("early" in tags and result(t) == "BE")) and -0.6 * risk < v < 0.5 * risk


def stats(ts):
    pn = [num(t.get("pnl")) for t in ts]
    res = [result(t) for t in ts]
    wins = [p for p, r in zip(pn, res) if r == "Win"]
    losses = [p for p, r in zip(pn, res) if r == "Loss"]
    run = longest = 0
    for r in res:
        if r == "BE": continue
        run = run + 1 if r == "Loss" else 0
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
        out.append({"name": name, "n": s["n"], "wins": s["wins"], "losses": s["losses"], "be": s["n"] - s["wins"] - s["losses"], "pnl": s["total"]})
    return sorted(out, key=lambda x: -x["pnl"])


def build_week(trades, start, cur, settings=None):
    settings = settings or {}
    CTX["risk"] = num(settings.get("defaultRisk"))
    CTX["sizes"] = {a.get("id"): num(a.get("size")) for a in settings.get("accounts") or []}
    end = start + dt.timedelta(days=6)
    iso = lambda d: d.isoformat()
    in_week = lambda s, e: sorted([t for t in trades if iso(s) <= str(t.get("date", "")) <= iso(e)], key=lambda t: (t.get("date", ""), t.get("time") or ""))
    week, prev = in_week(start, end), in_week(start - dt.timedelta(days=7), end - dt.timedelta(days=7))
    st, pv = stats(week), stats(prev)

    def money(v, signed=True):
        s = f"{cur}{abs(v):,.2f}"
        return (("+" if v > 0 else "−" if v < 0 else "") + s) if signed else s
    rec = lambda g: f"{g['wins']}W–{g['losses']}L" + (f"–{g['be']}BE" if g.get("be") else "")
    # Size results against risk and the account, so a few dollars isn't called a good or bad week.
    risks = [num(t.get("risk")) for t in week if num(t.get("risk")) > 0]
    unit = sum(risks) / len(risks) if risks else CTX["risk"]
    # Same as the app: the balance just before the week, for the accounts traded this week
    # (their sizes plus everything they closed earlier). Every % in the review is of this.
    ids = {t.get("account") for t in week}
    close_key = lambda t: (t.get("closedDate") or t.get("date") or "") + " " + ((t.get("closedTime") if t.get("closedDate") else t.get("time")) or "")
    first = min((close_key(t) for t in week), default="")
    week_ids = {id(t) for t in week}
    bal = sum(CTX["sizes"].get(a, 0.0) for a in ids) + sum(
        num(t.get("pnl")) for t in trades
        if t.get("account") in ids and id(t) not in week_ids and t.get("status") != "open"
        and close_key(t) < first)
    min_move = max(unit * 0.25, bal * 0.0005, 0.01)
    big = lambda v: abs(v) >= min_move
    def size_txt(v):
        sign = "+" if v >= 0 else "−"
        return f"{sign}{abs(v / unit):.1f}R" if unit else f"{sign}{abs(v / bal * 100):.2f}%" if bal else ""
    tagged = lambda k: [t for t in week if k in note_tags(t)]
    b = lambda x: f"<b>{html.escape(str(x))}</b>"
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"

    followed = [t for t in week if t.get("followedPlan") is not False]
    broke = [t for t in week if t.get("followedPlan") is False]
    setups, sessions, pairs = group(week, "setup"), group(week, "session"), group(week, "pair")
    emos = group([t for t in week if t.get("emotionBefore")], "emotionBefore")
    mistakes = {}
    for t in week:
        seen = set()
        for m in [x.strip() for x in str(t.get("mistakes") or "").split(",") if x.strip()]:
            key, label = mistake_type(m)
            if key in seen: continue  # one count per trade
            seen.add(key)
            mistakes.setdefault(key, {"label": label, "n": 0, "pnl": 0.0})
            mistakes[key]["n"] += 1
            mistakes[key]["pnl"] += num(t.get("pnl"))
    top_mistakes = sorted(mistakes.items(), key=lambda kv: (-kv[1]["n"], kv[1]["pnl"]))

    worked, cost, focus = [], [], []
    losing = [g for g in sorted([g for g in setups if g["pnl"] < 0], key=lambda g: (-(g["n"] >= 2), g["pnl"]))[:2] if big(g["pnl"])]
    best_setup = next((g for g in setups if g["pnl"] > 0 and big(g["pnl"])), None)
    if best_setup: worked.append(f"{b(best_setup['name'])} was your strongest setup: {rec(best_setup)}, net {b(money(best_setup['pnl']))}.")
    bs = next((g for g in sessions if g["pnl"] > 0 and big(g["pnl"])), None)
    if bs: worked.append(f"The {b(bs['name'])} session performed best, returning {b(money(bs['pnl']))} ({rec(bs)}).")
    bp = next((g for g in pairs if g["pnl"] > 0 and big(g["pnl"])), None)
    if bp: worked.append(f"{b(bp['name'])} was your most profitable instrument: {b(money(bp['pnl']))} across {plural(bp['n'], 'trade')}.")
    be = next((g for g in emos if g["pnl"] > 0 and g["n"] >= 2 and big(g["pnl"])), None)
    if be: worked.append(f"Trades entered feeling {b(emo_word(be['name']))} returned {b(money(be['pnl']))} ({rec(be)}).")
    fp = sum(num(t.get("pnl")) for t in followed)
    cut = [t for t in week if cut_for_invalid(t)]
    if cut: worked.append(f"{'One trade was' if len(cut) == 1 else f'{len(cut)} trades were'} closed early once the setup was invalidated ({', '.join(html.escape(str(t.get('pair') or '')) + ' ' + money(num(t.get('pnl'))) for t in cut)}). Exiting a broken idea at minimal cost is sound risk management.")
    to_be = tagged("breakeven")
    if to_be: worked.append(f"Risk was removed from {plural(len(to_be), 'trade')} by moving the stop to breakeven.")
    if followed and fp > 0 and big(fp): worked.append(f"Plan-compliant trades returned {b(money(fp))} across {plural(len(followed), 'trade')}.")

    for g in losing: cost.append(f"{b(g['name'])} underperformed: {rec(g)}, net {b(money(g['pnl']))}.")
    ws = ([g for g in sessions if g["pnl"] < 0 and big(g["pnl"])] or [None])[-1]
    if ws: cost.append(f"The {b(ws['name'])} session was a drag on results: {b(money(ws['pnl']))} ({rec(ws)}).")
    emo_notes = tagged("emotional")
    if emo_notes: cost.append(f"Your notes point to emotional decision-making (revenge, FOMO, fear or impatience) on {plural(len(emo_notes), 'trade')}, net {b(money(sum(num(t.get('pnl')) for t in emo_notes)))}.")
    news_notes = [t for t in tagged("news") if num(t.get("pnl")) < 0]
    if news_notes: cost.append(f"High-impact news affected {plural(len(news_notes), 'losing trade')}, net {b(money(sum(num(t.get('pnl')) for t in news_notes)))}.")
    we = ([g for g in emos if g["pnl"] < 0 and g["n"] >= 2 and big(g["pnl"])] or [None])[-1]
    if we: cost.append(f"Entries taken feeling {b(emo_word(we['name']))} returned {b(money(we['pnl']))} ({rec(we)}).")
    if broke: cost.append(f"{'One trade' if len(broke) == 1 else f'{len(broke)} trades'} deviated from your trading plan, net {b(money(sum(num(t.get('pnl')) for t in broke)))}.")
    if top_mistakes: cost.append("Execution errors logged: " + "; ".join(html.escape(v["label"]) + (f" (×{v['n']})" if v["n"] > 1 else "") for _, v in top_mistakes[:3]) + ".")
    if st["longest_loss"] >= 3: cost.append(f"Longest losing streak: {b(st['longest_loss'])} consecutive trades.")
    fees_wk = sum(abs(num(t.get("fees"))) for t in week)
    if fees_wk >= 0.01: cost.append(f"Fees and commission: {b(money(-fees_wk))} across {plural(sum(1 for t in week if num(t.get('fees'))), 'trade')} (already taken off your P&amp;L).")

    if we: focus.append(f"Stand aside when you feel {html.escape(emo_word(we['name']))}: those entries went {rec(we)} this week.")
    if mistakes.get("early_exit", {}).get("n", 0) >= 2: focus.append(f"Allow winners to reach target. {mistakes['early_exit']['n']} trades were exited early; set the take profit and let the trade play out.")
    if mistakes.get("early_entry", {}).get("n", 0) >= 2 and len(focus) < 3: focus.append(f"Wait for confirmation before entering. {mistakes['early_entry']['n']} entries were taken too soon this week.")
    if st["longest_loss"] >= 3 and len(focus) < 3: focus.append("Apply a daily stop: after two consecutive losses, end the session.")
    if broke and len(focus) < 3: focus.append(f"Prioritise plan adherence. Off-plan trades returned {money(sum(num(t.get('pnl')) for t in broke))}" + (", and outside opinion influenced some of them." if "influence" in mistakes else "."))
    if best_setup and len(focus) < 3: focus.append(f"Concentrate on {html.escape(best_setup['name'])}: it was your edge this week ({rec(best_setup)}).")
    if losing and len(focus) < 3: focus.append(f"Refine {html.escape(losing[0]['name'])} entries and wait for confirmation before committing.")

    delta = st["total"] - pv["total"]
    # The week in R, as the app and share card show it: each trade's own R added up when every
    # closed trade has its risk set, otherwise P&L over the average risk.
    def r_of(t):
        if isinstance(t.get("r"), (int, float)): return float(t["r"])
        return num(t.get("pnl")) / num(t.get("risk")) if num(t.get("risk")) > 0 else None
    rs = [r_of(t) for t in week if t.get("status") != "open"]
    week_r = sum(rs) if rs and all(r is not None for r in rs) else st["total"] / unit if unit and week else None
    size = (("+" if week_r >= 0 else "−") + f"{abs(week_r):.1f}R") if week_r is not None else size_txt(st["total"]) if week else ""
    sized = f" ({size})" if size else ""
    strong = st["total"] >= unit * 2 if unit else st["total"] >= bal * 0.01
    rough = st["total"] <= -unit * 2 if unit else st["total"] <= -bal * 0.01
    if not week: verdict = "No trades logged this week."
    elif not big(st["total"]):
        verdict = f"Breakeven week: {b(money(st['total']))} from {plural(st['n'], 'trade')}{sized}." + (
            f" {'One trade was' if len(cut) == 1 else f'{len(cut)} trades were'} closed early after the setup was invalidated, which limited the impact." if cut else " No meaningful gain or loss.")
    elif st["total"] > 0 and strong and st["pf"] >= 1.5 and st["n"] >= 2:
        verdict = f"Strong week: {b(money(st['total']))}{sized} across {plural(st['n'], 'trade')}" + (f", {'up' if delta >= 0 else 'down'} {b(money(abs(delta), False))} on last week." if prev else ".")
    elif st["total"] > 0: verdict = f"Small green week: {b(money(st['total']))}{sized} from {plural(st['n'], 'trade')}. A modest gain with room to build on."
    elif rough: verdict = f"Tough week: {b(money(st['total']))}{sized} across {plural(st['n'], 'trade')}. The breakdown below shows where the losses came from."
    else: verdict = f"Small red week: {b(money(st['total']))}{sized} from {plural(st['n'], 'trade')}. A contained drawdown, recoverable with a single good trade."

    days = []
    for i in range(7):
        d = start + dt.timedelta(days=i)
        ts = [t for t in week if t.get("date") == d.isoformat()]
        days.append((d, len(ts), sum(num(t.get("pnl")) for t in ts)))
    pf = "—" if not (st["wins"] or st["losses"]) else "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return {"start": start, "end": end, "st": st, "prev": pv, "verdict": verdict, "worked": worked, "cost": cost,
            "focus": focus[:3], "days": days, "money": money, "pf": pf, "plan_rate": (len(followed) / len(week)) if week else 0}


# ---------- Email ----------
def render(w, name, preview=False):
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
{('<tr><td style="padding:16px 24px 0"><div style="background:#e6f6f5;border:1px solid #bfe8e5;border-radius:10px;padding:12px 14px;font-size:13.5px;color:#0d4f4c;line-height:1.5"><b>New: weekly reviews by email.</b> This is a preview of your week. To get one every Sunday at 10am, turn on <b>Email me my weekly review</b> in ELEV8 › Settings › Profile.</div></td></tr>') if preview else ""}
<tr><td style="padding:22px 24px 4px"><div style="font-size:13px;color:#5d6d84">{rng}</div><div style="font-size:20px;font-weight:700;color:#0d1b2e;margin-top:4px">Hi {hello}, here's your week</div>
<p style="font-size:15px;color:#33445c;line-height:1.5;margin:10px 0 0">{w['verdict']}</p></td></tr>
<tr><td style="padding:16px 18px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="6"><tr>
{kpi("P&amp;L", money(st['total']), col(st['total']))}{kpi("Trades", st['n'])}{kpi("Win rate", f"{st['win_rate']:.0%}" if st['wins'] or st['losses'] else "—")}{kpi("Profit factor", w['pf'])}
</tr></table></td></tr>
<tr><td style="padding:16px 24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="height:100px"><tr>{bars}</tr></table></td></tr>
{section("What worked", "#13955a", lst(w['worked'], "Nothing stood out this week."))}
{section("What cost you", "#d8344f", lst(w['cost'], "No costly patterns. Nice."))}
{section("Focus for next week", "#1f6fc4", lst(w['focus'], "Keep doing what you're doing."))}
<tr><td style="padding:22px 24px 26px" align="center"><a href="{SITE}/?app#insights" style="display:inline-block;background:#1f6fc4;background-image:linear-gradient(120deg,#2a7fd9,#25c0c0);color:#ffffff;text-decoration:none;font-weight:600;padding:12px 22px;border-radius:10px">Open your journal</a></td></tr>
</table>
<p style="font-size:12px;color:#5d6d84;margin:14px 0 0;max-width:600px">{"This is a one-off preview. You won't get these again unless you turn on weekly reviews in ELEV8 › Settings › Profile." if preview else "You're getting this because weekly reviews are on in ELEV8 › Settings › Profile. Turn them off there any time."} This review is worked out from your own journal and is for education only, not financial advice. ELEV8 isn't affiliated with any prop firm or broker.</p>
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
        t = r.get("data") or {}
        if t.get("status") == "open":
            continue  # still open: no result yet, so it isn't part of the week's review
        trades.setdefault(r["user_id"], []).append(t)
    sent = skipped = 0
    for u in all_users():
        email = (u.get("email") or "").lower()
        s = settings.get(u["id"], {})
        if ONLY:
            if email != ONLY: continue
        elif PREVIEW_ALL:
            if not u.get("email_confirmed_at"): continue
        elif not s.get("weeklyEmail") or not u.get("email_confirmed_at"):
            continue
        # Same rule as the app: the symbol goes into HTML, so only up to 4 plain characters.
        cur = re.sub(r"[<>&\"'`\\]", "", str(s.get("currency") or "$")).strip()[:4] or "$"
        w = build_week(trades.get(u["id"], []), start, cur, s)
        if not w["st"]["n"] and not ONLY and not PREVIEW_ALL:
            skipped += 1  # nothing logged this week: no email
            continue
        name = (u.get("user_metadata") or {}).get("full_name", "")
        # A test to one address with preview on always shows the preview version.
        preview = PREVIEW_ALL and (bool(ONLY) or not s.get("weeklyEmail"))
        subject = ("Preview: " if preview else "") + f"Your ELEV8 week: {w['money'](w['st']['total'])} · {w['st']['n']} trades · {w['st']['win_rate']:.0%} win rate"
        try:
            send(u["email"], subject, render(w, name, preview))
            sent += 1
        except Exception as exc:  # one bad address shouldn't stop the rest
            print("  could not send to", email, "-", exc, file=sys.stderr)
    print(f"week of {start}: sent {sent}, skipped {skipped} (no trades)")
    if ONLY and not sent:
        sys.exit(f"No account found for {ONLY}")


if __name__ == "__main__":
    main()
