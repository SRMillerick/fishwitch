#!/usr/bin/env python3
"""Link-check the built static site: every internal href/src must resolve to a
file in site/. Fails loudly — run before publish (publish-site calls it)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent / "site"
ok = True
for page in sorted(SITE.glob("*.html")):
    body = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", page.read_text())
    refs = set(re.findall(r'(?:href|src)="([^"]+)"', body))
    for r in refs:
        if r.startswith(("#", "http:", "https:", "mailto:", "data:")):
            continue
        target = (SITE / r.split("#")[0].split("?")[0]).resolve()
        if not target.exists():
            print(f"✗ {page.name}: {r}")
            ok = False
if not ok:
    sys.exit("broken internal links — aborting publish")
print(f"✓ all internal links resolve across {len(list(SITE.glob('*.html')))} pages")
