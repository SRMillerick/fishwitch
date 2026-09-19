#!/usr/bin/env python3
"""Static site builder — renders the fishwitch showcase to `site/` for GitHub Pages.

The pipe is deterministic, so snapshots ARE the product: this renders the real
webapp (via its own test client — no server) into static HTML, then rewrites
links to relative paths. Publish with ./publish-site (gh-pages branch).

Public-safety scrubbing (this is the showcase, not the private app):
  - lake `lore` stripped (club-lake intel stays local)
  - logbook neutered (no catch counts / best producers leak — patch lb.summary_for
    and lb.load during the build)
  - anonymous renders only — no profiles, no natal data, nothing personal

Reports freeze at build time; each page carries a snapshot stamp.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

import logbook as lb  # noqa: E402

# ── scrub the private layers before anything renders ────────────────────────
lb.summary_for = lambda *a, **k: None      # no "your logbook" rows publicly
lb.load = lambda *a, **k: []               # no angler-verified species leaks

import webapp  # noqa: E402  (after scrub: generate() reads patched lb)

_reg = webapp.registry()
webapp.registry = lambda: {
    k: {kk: vv for kk, vv in v.items() if kk not in ("lore", "access", "structure")}
    for k, v in _reg.items()
}

STAMP = datetime.now().strftime("%A %b %-d, %-I:%M %p")
BANNER = (f'<p class="fine snap">Static snapshot — built {STAMP}. '
          'The live pipe re-renders these in real time.</p>')

c = webapp.app.test_client()
OUT = ROOT / "site"
(OUT / "static").mkdir(parents=True, exist_ok=True)
import shutil  # noqa: E402
shutil.copytree(ROOT / "web" / "static", OUT / "static", dirs_exist_ok=True)


def _resolve_out(path: str):
    """Resolve a /out/<entry>/<retailer> link back to its destination so the
    static snapshot (no server) still links correctly."""
    m = re.match(r"/out/([^/?#]+)/([^/?#]+)", path)
    if not m:
        return None
    entry, retailer = m.group(1), m.group(2)
    if retailer == "manufacturer":
        cat = webapp.tx.find_entry(entry)
        return (cat or {}).get("manufacturer_specs", {}).get("product_url")
    for o in webapp.offers.resolve(entry):
        if o.get("retailer") == retailer and o.get("url"):
            return o["url"]
    return None


def _rewrite_out(m):
    url = _resolve_out(m.group(1))
    return f'href="{url}"' if url else m.group(0)


def save(path: str, body: str):
    body = body.replace('href="/static/', 'href="static/')
    body = body.replace('src="/static/', 'src="static/')
    body = body.replace('href="/report?lake=hidden-valley-lake-ca&amp;at=', 'href="report-')
    body = re.sub(r'href="/report\?[^"]*"', 'href="report-tonight.html"', body)
    body = body.replace('href="/report"', 'href="report-tonight.html"')  # nav + hero btn
    body = re.sub(r'href="/outlook\?[^"]*"', 'href="outlook.html"', body)
    body = body.replace('href="/outlook"', 'href="outlook.html"')
    # /ledger.ics + /outlook.rss are dynamic-only (no server on gh-pages); drop
    # the subscribe line so the static snapshot has no broken links.
    body = re.sub(r'<p class="fine">Subscribe to the A/S windows:.*?</p>\s*',
                  '', body, flags=re.S)
    body = re.sub(r'href="/kb\?species=(\w+)"', r'href="kb-\1.html"', body)
    body = body.replace('href="/kb"', 'href="kb-bass.html"')
    body = body.replace('href="/interview"', 'href="interview.html"')
    body = body.replace('href="/lakes"', 'href="lakes.html"')
    body = re.sub(r'href="/lake/([\w-]+)"', r'href="lake-\1.html"', body)
    body = body.replace('href="/about"', 'href="about.html"')
    body = body.replace('href="/privacy"', 'href="privacy.html"')
    body = body.replace('href="/disclosure"', 'href="disclosure.html"')
    body = body.replace('href="/contact"', 'href="contact.html"')
    body = body.replace('href="/review"', 'href="#"')
    body = body.replace('href="/"', 'href="index.html"')
    # forms can't submit anywhere on a static host
    body = body.replace('method="get" action="/outlook"', 'onsubmit="return false"')
    body = body.replace('method="get" action="/kb"', 'onsubmit="return false"')
    body = re.sub(r'<form id="report-form" class="grid" method="get" action="/report">',
                  '<form id="report-form" class="grid" onsubmit="return false">', body)
    # /out/ click links need a server — resolve them for the static snapshot
    body = re.sub(r'href="(/out/[^"]+)"', _rewrite_out, body)
    # snapshot banner right under <main>
    body = body.replace("<main>", "<main>" + BANNER, 1)
    (OUT / path).write_text(body)
    print(f"  ✓ {path}")


print(f"building snapshot → site/  ({STAMP})")

# landing + kb + outlook
save("index.html", c.get("/").get_data(as_text=True))
for pg in ("about", "privacy", "disclosure", "contact"):
    save(f"{pg}.html", c.get(f"/{pg}").get_data(as_text=True))
save("lakes.html", c.get("/lakes").get_data(as_text=True))
for _lk in _reg:
    save(f"lake-{_lk}.html", c.get(f"/lake/{_lk}").get_data(as_text=True))
for sp in ("bass", "trout", "catfish", "panfish"):
    save(f"kb-{sp}.html", c.get(f"/kb?species={sp}").get_data(as_text=True))
save("outlook.html", c.get("/outlook?lake=hidden-valley-lake-ca&days=10")
     .get_data(as_text=True))

# anonymous report snapshots: tonight + next two evenings (almanac voice)
for i, at in enumerate([datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
                        + timedelta(days=d) for d in (0, 1, 2)], start=1):
    day = at.strftime("%Y-%m-%d")
    q = f"/report?lake=hidden-valley-lake-ca&at={day}%2018%3A00&hours=2.5&voice=almanac"
    name = "report-tonight.html" if i == 1 else f"report-d{i}.html"
    save(name, c.get(q).get_data(as_text=True))

# interview placeholder (the real one needs the live app + custody API)
iv = c.get("/interview").get_data(as_text=True)
iv = iv.replace("Save profile to this browser", "profile creation runs on the live app")
iv = iv.replace('<div class="cta">',
                '<p class="fine"><strong>Read-only snapshot:</strong> the save button is locked. '
                'Profile creation and personal reports need the live app — '
                'where your birth data stays in your browser and never touches a disk.</p>\n  <div class="cta">', 1)
iv = iv.replace('<button type="submit">', '<button type="submit" disabled>')
# no live APIs on a static host: the wizard is inert — banner up top, readonly place,
# locked save button with its reason (bplace's id is dropped so the geocode listener no-ops;
# the vault menu still works — import/switch are pure client-side)
iv = iv.replace('<h1>Three steps to your reports</h1>',
                '<h1>Three steps to your reports</h1>'
                '<p class="fine"><strong>Read-only snapshot</strong> — this page can’t geocode or save '
                '(GitHub Pages runs no code). The live app does both.</p>')
iv = iv.replace('<input name="bplace" id="bplace" placeholder="City, State — e.g. Santa Rosa, CA" required>',
                '<input name="bplace" placeholder="City, State — geocoding runs on the live app" readonly>')
iv = iv.replace('<button type="submit">Save profile to this browser</button>',
                '<button type="submit" disabled>saving runs on the live app</button>')
save("interview.html", iv)

(OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n")
(OUT / ".nojekyll").write_text("")
(OUT / "CNAME").write_text("baromoon.com\n")   # custom domain — survives every rebuild
print("done — publish with: ./publish-site")
