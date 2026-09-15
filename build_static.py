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
    k: {kk: vv for kk, vv in v.items() if kk != "lore"} for k, v in _reg.items()
}

STAMP = datetime.now().strftime("%A %b %-d, %-I:%M %p")
BANNER = (f'<p class="fine snap">📸 static snapshot — built {STAMP}. '
          'The live pipe re-renders these in real time.</p>')

c = webapp.app.test_client()
OUT = ROOT / "site"
(OUT / "static").mkdir(parents=True, exist_ok=True)
import shutil  # noqa: E402
shutil.copytree(ROOT / "web" / "static", OUT / "static", dirs_exist_ok=True)


def save(path: str, body: str):
    body = body.replace('href="/static/', 'href="static/')
    body = body.replace('src="/static/', 'src="static/')
    body = body.replace('href="/report?lake=hidden-valley-lake-ca&amp;at=', 'href="report-')
    body = re.sub(r'href="/report\?[^"]*"', 'href="report-tonight.html"', body)
    body = body.replace('href="/report"', 'href="report-tonight.html"')  # nav + hero btn
    body = re.sub(r'href="/outlook\?[^"]*"', 'href="outlook.html"', body)
    body = body.replace('href="/outlook"', 'href="outlook.html"')
    body = re.sub(r'href="/kb\?species=(\w+)"', r'href="kb-\1.html"', body)
    body = body.replace('href="/kb"', 'href="kb-bass.html"')
    body = body.replace('href="/interview"', 'href="interview.html"')
    body = body.replace('href="/review"', 'href="#"')
    body = body.replace('href="/"', 'href="index.html"')
    # forms can't submit anywhere on a static host
    body = body.replace('method="get" action="/outlook"', 'onsubmit="return false"')
    body = body.replace('method="get" action="/kb"', 'onsubmit="return false"')
    body = re.sub(r'<form id="report-form" class="grid" method="get" action="/report">',
                  '<form id="report-form" class="grid" onsubmit="return false">', body)
    # snapshot banner right under <main>
    body = body.replace("<main>", "<main>" + BANNER, 1)
    (OUT / path).write_text(body)
    print(f"  ✓ {path}")


print(f"building snapshot → site/  ({STAMP})")

# landing + kb + outlook
save("index.html", c.get("/").get_data(as_text=True))
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
iv = iv.replace("Save profile to this browser", "🔒 profile creation runs on the live app")
iv = iv.replace('<div class="cta">',
                '<p class="fine"><strong>Read-only snapshot:</strong> the save button is locked. '
                'Profile creation and personal reports need the live app — '
                'where your birth data stays in your browser and never touches a disk.</p>\n  <div class="cta">', 1)
iv = iv.replace('<button type="submit">', '<button type="submit" disabled>')
# no live APIs on a static host: birth-place field goes readonly (its id is dropped so
# the geocode listener safely no-ops; the vault menu itself still works — import/switch
# are pure client-side, and stashed profiles carry over to the live app in this browser)
iv = iv.replace('<input name="bplace" id="bplace" placeholder="City, State, Country" required>',
                '<input name="bplace" placeholder="City, State, Country — geocoding runs on the live app" readonly>')
save("interview.html", iv)

(OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n")
(OUT / ".nojekyll").write_text("")
print("done — publish with: ./publish-site")
