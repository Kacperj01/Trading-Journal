"""Apply ELEV8's account email settings to Supabase through the Management API.

Sets the branded email templates and subjects (from site/email-templates), the Site URL and the
allowed redirect URLs, so confirmation and reset buttons bring people back to the journal.

Needs SUPABASE_ACCESS_TOKEN: a personal access token from supabase.com/dashboard/account/tokens,
stored as a GitHub Actions secret (never in this repository). Run by the "Account emails" workflow.
  python3 site/apply_auth_config.py           apply
  python3 site/apply_auth_config.py --dry-run show what would change, send nothing
"""
import json, os, re, sys, urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "site" / "email-templates"))
import make_templates  # noqa: E402

SITE = "https://elev8tradingjournal.com"
REDIRECTS = [f"{SITE}/**", "https://www.elev8tradingjournal.com/**"]

cfg = json.loads((root / "site" / "config.json").read_text())
ref = re.match(r"https://([a-z0-9]+)\.supabase\.co", cfg["supabaseUrl"]).group(1)

body = {"site_url": SITE, "mailer_otp_exp": 3600,  # buttons and codes last 1 hour (Supabase recommends 1 hour or less), as the emails say
        "password_min_length": 8}
for kind, (subject, html) in make_templates.build().items():
    body[f"mailer_subjects_{kind}"] = subject
    body[f"mailer_templates_{kind}_content"] = html

api = f"https://api.supabase.com/v1/projects/{ref}/config/auth"
token = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
dry = "--dry-run" in sys.argv


def call(method, data=None):
    req = urllib.request.Request(api, method=method, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "elev8-auth-config"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


if dry and not token:
    print("Dry run without a token: would set", ", ".join(sorted(k for k in body if not k.endswith("_content"))), "and", len([k for k in body if k.endswith("_content")]), "templates")
    print("Redirect URLs would include:", ", ".join(REDIRECTS))
    sys.exit(0)
if not token:
    sys.exit("SUPABASE_ACCESS_TOKEN is not set. Add it as a GitHub Actions secret, then run the Account emails workflow.")

current = call("GET")
# Keep any redirect URLs already allowed and add ours.
allowed = [u.strip() for u in (current.get("uri_allow_list") or "").split(",") if u.strip()]
body["uri_allow_list"] = ",".join(dict.fromkeys(allowed + REDIRECTS))

smtp = current.get("smtp_host")
print(f"Project {ref}: custom SMTP {'on (' + smtp + ')' if smtp else 'OFF: emails only reach your own team until it is on'}")
print(f"Site URL: {current.get('site_url')} -> {SITE}")
print(f"Redirect URLs: {body['uri_allow_list']}")
for kind in make_templates.TEMPLATES:
    old = current.get(f"mailer_subjects_{kind}")
    print(f"  {kind:16} subject: {old!r} -> {body[f'mailer_subjects_{kind}']!r}")
if dry:
    print("Dry run: nothing changed.")
    sys.exit(0)
call("PATCH", body)
after = call("GET")
bad = [k for k, v in body.items() if after.get(k) != v]
if bad:
    sys.exit("These settings didn't stick: " + ", ".join(bad))
print("Done: all account emails now use the ELEV8 templates.")
