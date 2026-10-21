"""Check, from outside, that the live Supabase project keeps everyone's data private.

Acts like a stranger who isn't signed in: using only the public (publishable) key that every visitor's
browser already has, it tries to read each table, write rows, call the account functions and list the
private storage bucket. Every one of those must be refused or come back empty. Run by the "Security
check" Action (weekly and by hand). Needs no secrets.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CFG = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
URL, KEY = CFG["supabaseUrl"].rstrip("/"), CFG["supabaseAnonKey"]
TABLES = ["trades", "journal_settings", "bug_reports", "push_subscriptions", "push_keys", "push_log", "app_config"]
results = []


def call(method, path, body=None):
    headers = {"apikey": KEY, "Content-Type": "application/json", "Accept": "application/json"}
    if KEY.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + KEY
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def check(name, status, text, safe):
    ok = safe(status, text)
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {status} {text[:120].strip()}")


refused = lambda s, t: s in (400, 401, 403, 404)
empty_or_refused = lambda s, t: refused(s, t) or (s == 200 and t.strip() in ("[]", ""))

for t in TABLES:
    s, txt = call("GET", f"/rest/v1/{t}?select=*&limit=5")
    check(f"read {t}", s, txt, empty_or_refused)
for t, row in [("trades", {"id": "probe", "data": {}}), ("journal_settings", {"data": {}}),
               ("bug_reports", {"title": "probe", "body": "probe"}), ("app_config", {"key": "probe", "value": "x"})]:
    s, txt = call("POST", f"/rest/v1/{t}", row)
    check(f"write {t}", s, txt, refused)
for fn, args in [("delete_my_account", {"really": False}), ("push_public_key", {}),
                 ("push_subscribe", {"p_endpoint": "https://example.com/x", "p_p256dh": "x" * 30, "p_auth": "x" * 10}),
                 ("push_unsubscribe", {"p_endpoint": "https://example.com/x"})]:
    s, txt = call("POST", f"/rest/v1/rpc/{fn}", args)
    check(f"call {fn}", s, txt, refused)
s, txt = call("POST", "/storage/v1/object/list/payout-certificates", {"prefix": "", "limit": 5})
check("list payout-certificates bucket", s, txt, empty_or_refused)
s, txt = call("GET", "/storage/v1/object/public/payout-certificates/probe.png")
check("public link into payout-certificates", s, txt, refused)

# Sign-up settings (information only).
s, txt = call("GET", "/auth/v1/settings")
if s == 200:
    st = json.loads(txt)
    print("info  sign-ups open:", not st.get("disable_signup"), "| email confirmation required:",
          not st.get("mailer_autoconfirm"), "| sign-in methods:",
          ", ".join(k for k, v in (st.get("external") or {}).items() if v) or "none")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
