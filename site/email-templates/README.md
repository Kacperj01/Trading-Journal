# ELEV8 account emails

Every account email (confirm sign-up, reset password, change email, sign-in link, invite and
security code) uses one ELEV8 design: the logo, a short message and a single button. The link
itself is never shown in the email.

- `make_templates.py` builds the six `.html` files from that design. Edit the wording there.
- `site/apply_auth_config.py` sends them to Supabase with their subjects, and also sets the Site URL
  (https://elev8tradingjournal.com), the allowed redirect URLs and a 1-hour link expiry, so the
  buttons always bring people back to the journal.
- The **Account emails** GitHub Action runs that script. It needs one secret,
  `SUPABASE_ACCESS_TOKEN`: a personal access token from supabase.com/dashboard/account/tokens,
  added under GitHub > Settings > Secrets and variables > Actions. It runs by hand from the
  Actions tab and again whenever the templates change.

The logo loads from https://elev8tradingjournal.com/email/elev8-email-logo.png (copied there by
`site/build.py`). Emails are sent from noreply@elev8tradingjournal.com through Custom SMTP (Resend).
