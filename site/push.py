"""Send notifications to the devices that turned them on (Settings › Profile › Notifications).

Used by weekly_review.py (Sunday's "your review is ready") and news_alerts.py (high-impact news).
Needs the pywebpush package (the GitHub Actions install it) and SUPABASE_SERVICE_KEY.

The key pair notifications are signed with lives in Supabase's push_keys table, which only the
service key can read. The first run makes it, so there's no extra secret to set up; the app reads the
public half through the push_public_key() function.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SB_URL = os.environ.get("SUPABASE_URL") or json.loads((ROOT / "site" / "config.json").read_text())["supabaseUrl"]
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
CONTACT = "mailto:noreply@elev8tradingjournal.com"  # push services contact this if something goes wrong


def sb(method, path, body=None, prefer=None):
    headers = {"apikey": KEY, "Accept": "application/json", "Content-Type": "application/json"}
    if KEY.startswith("eyJ"):  # legacy service_role JWT; new sb_secret_ keys go in apikey only
        headers["Authorization"] = "Bearer " + KEY
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SB_URL.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            raw = res.read()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        hint = " -> Run the Notifications part of site/supabase-setup.sql in Supabase's SQL Editor." if exc.code in (401, 403, 404) else ""
        raise RuntimeError(f"Supabase refused {method} {path.split('?')[0]} ({exc.code}): {detail}{hint}") from None


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def keys():
    """The signing key pair, made on first use. Returns (public key for the app, Vapid signer)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from py_vapid import Vapid02
    rows = sb("GET", "/rest/v1/push_keys?select=public_key,private_key&id=eq.1")
    if not rows:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        pub = b64url(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        # If two jobs race to make it, the first one wins and both use that.
        sb("POST", "/rest/v1/push_keys", {"id": 1, "public_key": pub, "private_key": pem}, "resolution=ignore-duplicates,return=minimal")
        rows = sb("GET", "/rest/v1/push_keys?select=public_key,private_key&id=eq.1")
        print("made the notification key pair")
    return rows[0]["public_key"], Vapid02.from_pem(rows[0]["private_key"].encode())


def devices():
    """Every device with notifications on, grouped by account: {user_id: [subscription rows]}."""
    out, start = {}, 0
    while True:
        batch = sb("GET", f"/rest/v1/push_subscriptions?select=id,user_id,endpoint,p256dh,auth&order=id&offset={start}&limit=1000")
        for r in batch:
            out.setdefault(r["user_id"], []).append(r)
        if len(batch) < 1000:
            return out
        start += 1000


def claim(key):
    """True the first time a key is claimed (so a news alert is sent once, even if two jobs overlap)."""
    rows = sb("POST", "/rest/v1/push_log", {"key": key}, "resolution=ignore-duplicates,return=representation")
    return bool(rows)


def tidy_log(days=30):
    import datetime as dt
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sb("DELETE", f"/rest/v1/push_log?sent_at=lt.{cutoff}")


def send(signer, device, title, body, url, tag, ttl=3600):
    """Send one notification to one device. A device that's gone (app removed, permission revoked)
    is deleted. Returns True when the push service accepted it."""
    from pywebpush import WebPushException, webpush
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    try:
        webpush({"endpoint": device["endpoint"], "keys": {"p256dh": device["p256dh"], "auth": device["auth"]}},
                data=payload, vapid_private_key=signer, vapid_claims={"sub": CONTACT}, ttl=ttl,
                headers={"Urgency": "high"}, timeout=15)
        return True
    except WebPushException as exc:
        code = exc.response.status_code if exc.response is not None else None
        if code in (404, 410):
            sb("DELETE", f"/rest/v1/push_subscriptions?id=eq.{int(device['id'])}")
        else:
            print("  push failed:", code, str(exc)[:200], file=sys.stderr)
    except Exception as exc:  # one bad device never stops the rest
        print("  push failed:", type(exc).__name__, str(exc)[:200], file=sys.stderr)
    return False
