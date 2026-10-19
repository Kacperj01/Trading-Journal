"""Email new bug reports (sidebar › Report a bug) to the owner. Run by the news-alerts Action every 30 minutes.

Who gets them is set in Supabase, not in this public repo: the app_config table's bug_report_email row
(see the Bug report emails part of site/supabase-setup.sql). Each report is emailed once (claimed in
push_log), reports older than 14 days are skipped, and the email's reply-to is the reporter's address.

Environment:
  SUPABASE_SERVICE_KEY  Supabase secret (service_role) key - GitHub secret
  RESEND_API_KEY        Resend API key                    - GitHub secret
  DRY_RUN               optional: "1" prints the emails instead of sending
"""
import datetime as dt
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import push  # noqa: E402  (Supabase helper and the push_log claims)

RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_URL = os.environ.get("RESEND_URL", "https://api.resend.com/emails")
FROM = "ELEV8 Bug Reports <bugs@elev8tradingjournal.com>"
DRY = os.environ.get("DRY_RUN") == "1"
PROJECT = urllib.parse.urlparse(push.SB_URL).hostname.split(".")[0]


def send(to, subject, body_html, reply_to=None):
    if DRY:
        print("--- to", to, "|", subject, "| reply-to", reply_to)
        return
    msg = {"from": FROM, "to": [to], "subject": subject, "html": body_html}
    if reply_to:
        msg["reply_to"] = reply_to
    req = urllib.request.Request(RESEND_URL, data=json.dumps(msg).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + RESEND_KEY, "Content-Type": "application/json", "User-Agent": "elev8-bug-alerts"})
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()


def main():
    if not push.KEY or not (RESEND_KEY or DRY):
        sys.exit("Missing GitHub secrets: SUPABASE_SERVICE_KEY and RESEND_API_KEY.")
    try:
        cfg = push.sb("GET", "/rest/v1/app_config?select=value&key=eq.bug_report_email")
    except RuntimeError as exc:
        print("bug report emails not set up yet:", str(exc)[:160])
        return
    to = cfg[0]["value"].strip() if cfg else ""
    if "@" not in to:
        print("no bug_report_email set in app_config")
        return
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reports = push.sb("GET", f"/rest/v1/bug_reports?select=id,created_at,user_id,title,body&created_at=gte.{since}&order=id")
    sent = 0
    for r in reports:
        if not push.claim(f"bug:{r['id']}"):
            continue
        who = ""
        if r.get("user_id"):
            try:
                who = (push.sb("GET", f"/auth/v1/admin/users/{r['user_id']}") or {}).get("email") or ""
            except RuntimeError:
                who = ""
        when = dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).strftime("%a %-d %b %Y, %H:%M UTC")
        body = f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#0d1b2e;max-width:640px">
<p style="font-size:13px;color:#5d6d84;margin:0 0 6px">New bug report #{r['id']} · {html.escape(when)}</p>
<h2 style="font-size:19px;margin:0 0 14px">{html.escape(r['title'])}</h2>
<p style="margin:0 0 14px;font-size:14px">From: <b>{html.escape(who) if who else "an account that has since been deleted"}</b>{" (reply to this email to answer them)" if who else ""}</p>
<pre style="white-space:pre-wrap;font:13px/1.5 Menlo,Consolas,monospace;background:#f3f6fb;border-radius:10px;padding:14px">{html.escape(r['body'])}</pre>
<p style="font-size:13px;margin:16px 0 0"><a href="https://supabase.com/dashboard/project/{PROJECT}/editor">Open bug_reports in Supabase</a> to mark it fixed.</p>
</div>"""
        short = r["title"][5:] if r["title"].startswith("Bug: ") else r["title"]
        send(to, f"ELEV8 bug report: {short[:120]}", body, who or None)
        sent += 1
    print(f"bug reports: {len(reports)} in the last 14 days, emailed {sent} new")


if __name__ == "__main__":
    main()
