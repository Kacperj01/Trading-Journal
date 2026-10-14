"""Email a preview of every ELEV8 account email to one address, through Resend.

Shows exactly how the emails look in a real inbox. The buttons in a preview open the sign-in page,
because a preview has no real confirmation code behind it.
Run by the "Account emails" workflow with preview_to set. Needs RESEND_API_KEY.
"""
import json, os, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "email-templates"))
import make_templates  # noqa: E402

to = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
key = os.environ.get("RESEND_API_KEY", "")
if "@" not in to:
    sys.exit("Give the address to send the preview to.")
if not key:
    sys.exit("RESEND_API_KEY is not set.")

SITE = make_templates.SITE
for kind, (subject, html) in make_templates.build().items():
    html = (html.replace("{{ .Email }}", to).replace("{{ .NewEmail }}", "new-" + to)
                .replace("{{ .Token }}", "482913"))
    # A preview has no real code: point the button at the sign-in page instead.
    html = html.replace(f"{SITE}/?verify={{{{ .TokenHash }}}}&amp;type=", f"{SITE}/?login&amp;preview=")
    req = urllib.request.Request("https://api.resend.com/emails", method="POST",
        data=json.dumps({"from": "ELEV8 <noreply@elev8tradingjournal.com>", "to": [to], "subject": "[Preview] " + subject, "html": html}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "elev8-email-preview"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"sent {kind:16} {subject}  ({r.status})")
    except urllib.error.HTTPError as e:
        sys.exit(f"Resend refused {kind}: {e.code} {e.read().decode()[:300]}")
    time.sleep(0.6)  # stay under Resend's rate limit
print("Preview sent to", to)
