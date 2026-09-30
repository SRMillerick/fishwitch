#!/usr/bin/env python3
"""Search Console performance reader — turns the manual GSC check into a command.

Uses a Google service account (no OAuth dance, no browser). The private key is
used to sign a JWT with `openssl` (already on the box), so there are **no new
Python dependencies**.

    ~/.astro-venv/bin/python tools/gsc_read.py --days 28
    ~/.astro-venv/bin/python tools/gsc_read.py --dimension page --top 25
    ~/.astro-venv/bin/python tools/gsc_read.py --inspect https://baromoon.com/lake/hidden-valley-lake-ca
    ~/.astro-venv/bin/python tools/gsc_read.py --json   # raw rows

Credentials: `$GSC_SERVICE_ACCOUNT` or `~/.config/baromoon/gsc-service-account.json`
(never in the repo). One-time human setup (Sean's Google account):

  1. console.cloud.google.com → create/select a project → APIs & Services →
     enable **Google Search Console API**.
  2. IAM & Admin → Service Accounts → create one → Keys → add key → JSON →
     save it to `~/.config/baromoon/gsc-service-account.json` (chmod 600).
  3. Search Console → baromoon.com property → Settings → Users and permissions
     → Add user → paste the service account email (`...@....iam.gserviceaccount.com`)
     → Full (or Restricted is enough for read).

The Performance API lags ~2–3 days; the default window ends yesterday-1.
Index coverage (the Pages report) has no public API — only per-URL inspection,
which this tool supports via `--inspect`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

CREDS_ENV = "GSC_SERVICE_ACCOUNT"
CREDS_DEFAULT = Path.home() / ".config" / "baromoon" / "gsc-service-account.json"
SITE = "sc-domain:baromoon.com"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

SETUP = """\
No service-account key found. One-time setup:
  1. console.cloud.google.com -> enable the Google Search Console API
  2. create a service account + JSON key, save it to {creds}
  3. in Search Console -> (baromoon.com) -> Settings -> Users and permissions,
     add the service-account email as a Full (or Restricted) user
Then run this again (or set ${env}=<path-to-json>)."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64json(obj: dict) -> str:
    return _b64(json.dumps(obj, separators=(",", ":")).encode())


def _fail(r: requests.Response) -> None:
    """Raise a compact RuntimeError from a Google API error response."""
    try:
        err = r.json().get("error", {})
        msg = err.get("message") or json.dumps(err)
    except Exception:
        msg = (r.text or "")[:200]
    raise RuntimeError(f"Google API {r.status_code}: {msg}")


def access_token(sa: dict) -> str:
    """Service-account JWT -> OAuth access token, signed by openssl."""
    now = int(time.time())
    claims = {"iss": sa["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
              "iat": now, "exp": now + 3600}
    signing = _b64json({"alg": "RS256", "typ": "JWT"}) + "." + _b64json(claims)
    pem = sa["private_key"].replace("\\n", "\n").encode()
    fd, key_path = tempfile.mkstemp(prefix="gsc_key_", suffix=".pem")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path],
                             input=signing.encode(), capture_output=True, check=True).stdout
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass
    assertion = signing + "." + _b64(sig)
    r = requests.post(TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion}, timeout=30)
    if not r.ok:
        _fail(r)
    return r.json()["access_token"]


def query(token: str, site: str, start: str, end: str,
          dimension: str | None, row_limit: int) -> dict:
    body: dict = {"startDate": start, "endDate": end, "rowLimit": row_limit}
    if dimension:
        body["dimensions"] = [dimension]
    r = requests.post(f"{API}/{quote(site, safe='')}/searchAnalytics/query",
                      headers={"Authorization": f"Bearer {token}"}, json=body, timeout=45)
    if not r.ok:
        _fail(r)
    return r.json()


def inspect(token: str, site: str, url: str) -> dict:
    r = requests.post(INSPECT, headers={"Authorization": f"Bearer {token}"},
                      json={"inspectionUrl": url, "siteUrl": site}, timeout=45)
    if not r.ok:
        _fail(r)
    return r.json()


def _row(keys, clicks, impressions, ctr, position) -> str:
    label = " / ".join(str(k) for k in keys) if keys else "(total)"
    return (f"  {clicks:6.0f}  {impressions:7.0f}  {ctr * 100:5.1f}%  {position:5.1f}  "
            + label[:110])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--end", default=None, help="end date YYYY-MM-DD (default: yesterday-1)")
    ap.add_argument("--dimension", default="query",
                    choices=["query", "page", "country", "device", "date"])
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--inspect", metavar="URL", help="URL Inspection for one page")
    ap.add_argument("--json", action="store_true", help="print raw API JSON")
    args = ap.parse_args()

    creds = Path(os.environ.get(CREDS_ENV) or CREDS_DEFAULT)
    if not creds.exists():
        print(SETUP.format(creds=CREDS_DEFAULT, env=CREDS_ENV), file=sys.stderr)
        return 2
    sa = json.loads(creds.read_text())
    token = access_token(sa)

    if args.inspect:
        out = inspect(token, args.site, args.inspect)
        print(json.dumps(out, indent=1) if args.json else
              json.dumps(out.get("inspectionResult", out), indent=1))
        return 0

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=2)
    start = end - timedelta(days=args.days)
    data = query(token, args.site, start.isoformat(), end.isoformat(),
                 args.dimension, args.top)
    if args.json:
        print(json.dumps(data, indent=1))
        return 0
    rows = data.get("rows", [])
    print(f"  Search Console — {args.site} · {start} → {end} · dimension={args.dimension}")
    print(f"  {'clicks':>6}  {'impr.':>7}  {'ctr':>6}  {'pos':>5}  key")
    for r in rows:
        print(_row(r.get("keys", []), r["clicks"], r["impressions"],
                   r["ctr"], r["position"]))
    totals = query(token, args.site, start.isoformat(), end.isoformat(), None, 1)
    t = (totals.get("rows") or [{}])[0]
    print(f"\n  total: {t.get('clicks', 0):.0f} clicks · {t.get('impressions', 0):.0f} "
          f"impressions · {t.get('ctr', 0) * 100:.1f}% ctr · avg pos {t.get('position', 0):.1f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"gsc_read: {e}", file=sys.stderr)
        raise SystemExit(1)
