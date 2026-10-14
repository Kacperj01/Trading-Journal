"""Build the ELEV8 account emails (Supabase Auth templates) from one shared design.

Every email has the ELEV8 header, a short message and one button. The link itself is never shown.
Run: python3 site/email-templates/make_templates.py  (writes the .html files next to this script)
Then apply them with site/apply_auth_config.py, or the "Account emails" GitHub Action.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = "https://elev8tradingjournal.com"
LOGO = f"{SITE}/email/elev8-email-logo.png"

# Supabase template name -> (file, subject, preheader, heading, body html, button label or None)
TEMPLATES = {
    "confirmation": ("confirm-signup.html", "Confirm your ELEV8 account",
        "One tap to confirm your email and open your journal.",
        "Welcome to ELEV8",
        "You're one step away from your trading journal. Confirm <b style=\"color:#e6eef8\">{{ .Email }}</b> to finish setting up your account.",
        "Confirm my email"),
    "recovery": ("reset-password.html", "Reset your ELEV8 password",
        "Choose a new password for your ELEV8 journal.",
        "Reset your password",
        "We got a request to reset the password for <b style=\"color:#e6eef8\">{{ .Email }}</b>. Tap the button to choose a new one.",
        "Choose a new password"),
    "email_change": ("change-email.html", "Confirm your new ELEV8 email",
        "Confirm the new email address for your ELEV8 account.",
        "Confirm your new email",
        "You asked to change your ELEV8 sign-in email from <b style=\"color:#e6eef8\">{{ .Email }}</b> to <b style=\"color:#e6eef8\">{{ .NewEmail }}</b>. Tap the button to confirm.",
        "Confirm new email"),
    "magic_link": ("magic-link.html", "Your ELEV8 sign-in link",
        "Tap to sign in to your ELEV8 journal.",
        "Sign in to ELEV8",
        "Tap the button below to sign in to your trading journal as <b style=\"color:#e6eef8\">{{ .Email }}</b>.",
        "Sign in to my journal"),
    "invite": ("invite.html", "You're invited to ELEV8",
        "You've been invited to the ELEV8 Trading Journal.",
        "You're invited to ELEV8",
        "You've been invited to the ELEV8 Trading Journal. Accept the invite to set up your account and start logging your trades.",
        "Accept invite"),
    "reauthentication": ("reauthentication.html", "Your ELEV8 security code",
        "Your ELEV8 security code.",
        "Your security code",
        "Enter this code in ELEV8 to confirm it's you.",
        None),
}

NOTE = {
    "confirmation": "If you didn't create an ELEV8 account, you can ignore this email.",
    "recovery": "If you didn't ask for this, ignore this email. Your password stays the same.",
    "email_change": "If you didn't ask for this, ignore this email and your sign-in email stays the same.",
    "magic_link": "If you didn't ask to sign in, you can ignore this email.",
    "invite": "If you weren't expecting this, you can ignore this email.",
    "reauthentication": "If you didn't ask for a code, you can ignore this email.",
}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def button(label):
    # Bulletproof button: the whole pill is the link; a solid colour sits behind the gradient for Outlook.
    return f"""<tr><td align="center" style="padding:8px 32px 6px">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td align="center" bgcolor="#1f9fcf" style="border-radius:12px;background:#1f9fcf;background-image:linear-gradient(120deg,#2a7fd9 0%,#1f9fcf 55%,#2fd0c8 100%)">
      <a href="{{{{ .ConfirmationURL }}}}" target="_blank" style="display:inline-block;padding:15px 34px;font-family:{FONT};font-size:16px;font-weight:700;color:#06111f;text-decoration:none;border-radius:12px">{label}</a>
    </td>
  </tr></table>
</td></tr>"""


def code_box():
    return f"""<tr><td align="center" style="padding:8px 32px 6px">
  <div style="display:inline-block;padding:16px 28px;border-radius:12px;background:#06111f;border:1px solid #1f3a5c;font-family:'SFMono-Regular',Menlo,Consolas,monospace;font-size:30px;font-weight:700;letter-spacing:8px;color:#2fd0c8">{{{{ .Token }}}}</div>
</td></tr>"""


def page(kind, pre, heading, body, label):
    action = button(label) if label else code_box()
    expiry = "The button works once and expires in 24 hours." if label else "The code works once and expires in 24 hours."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"><title>{heading}</title></head>
<body style="margin:0;padding:0;background:#06111f">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#06111f">{pre}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#06111f" style="background:#06111f;padding:28px 12px">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px">
    <tr><td align="center" style="padding:6px 0 22px"><img src="{LOGO}" width="120" alt="ELEV8 Trading" style="display:block;width:120px;height:auto;border:0"></td></tr>
    <tr><td bgcolor="#0f2038" style="background:#0f2038;border:1px solid #1d3352;border-radius:18px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="height:4px;line-height:4px;font-size:0;border-radius:18px 18px 0 0;background:#1f9fcf;background-image:linear-gradient(90deg,#2a7fd9,#2fd0c8)">&nbsp;</td></tr>
        <tr><td align="center" style="padding:30px 32px 6px;font-family:{FONT};font-size:24px;line-height:1.25;font-weight:800;color:#e6eef8">{heading}</td></tr>
        <tr><td align="center" style="padding:6px 32px 18px;font-family:{FONT};font-size:15.5px;line-height:1.6;color:#b0bfd3">{body}</td></tr>
        {action}
        <tr><td align="center" style="padding:14px 32px 0;font-family:{FONT};font-size:13px;line-height:1.5;color:#8394ad">{expiry}</td></tr>
        <tr><td style="padding:22px 32px 0"><div style="height:1px;background:#1d3352;line-height:1px;font-size:0">&nbsp;</div></td></tr>
        <tr><td align="center" style="padding:16px 32px 28px;font-family:{FONT};font-size:12.5px;line-height:1.5;color:#8394ad">{NOTE[kind]}</td></tr>
      </table>
    </td></tr>
    <tr><td align="center" style="padding:22px 12px 4px;font-family:{FONT};font-size:12px;line-height:1.6;color:#5d7190">ELEV8 Trading Journal<br>Track every trade. Elevate every decision.</td></tr>
  </table>
</td></tr>
</table>
</body></html>
"""


def build():
    out = {}
    for kind, (fname, subject, pre, heading, body, label) in TEMPLATES.items():
        html = page(kind, pre, heading, body, label)
        (HERE / fname).write_text(html, encoding="utf-8")
        out[kind] = (subject, html)
    return out


if __name__ == "__main__":
    for kind, (subject, html) in build().items():
        print(f"{kind:16} {subject}  ({len(html):,} chars)")
