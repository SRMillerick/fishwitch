#!/bin/sh
# indexnow.sh — tell IndexNow engines (Bing & friends) that the site changed.
# The public key lives in deploy/indexnow.key and is served at /<key>.txt.
# Best-effort: a network failure must never fail a deploy.
set -e
DIR="$(dirname "$(readlink -f "$0")")/.."
KEY="$(cat "$DIR/deploy/indexnow.key" 2>/dev/null | tr -d '[:space:]')"
if [ -z "$KEY" ]; then
  echo "indexnow: no key — skipped"
  exit 0
fi
python3 - "$KEY" <<'PY'
import json, re, sys, time, urllib.request
key = sys.argv[1]
host = "baromoon.com"

def fetch(url):
    return urllib.request.urlopen(url, timeout=30).read().decode()

for attempt in range(3):
    try:
        xml = fetch(f"https://{host}/sitemap.xml")
        break
    except Exception as e:
        if attempt == 2:
            raise
        print(f"indexnow: sitemap not up yet ({e}); retrying")
        time.sleep(5)
locs = re.findall(r"<loc>([^<]+)</loc>", xml)
if "<sitemapindex" in xml:
    # follow the chunk files so the ping list stays page URLs
    urls = []
    for child in locs:
        if child.endswith(".xml"):
            urls += re.findall(r"<loc>([^<]+)</loc>", fetch(child))
    if not urls:
        urls = locs
else:
    urls = locs
payload = {"host": host, "key": key, "keyLocation": f"https://{host}/{key}.txt", "urlList": urls}
req = urllib.request.Request("https://api.indexnow.org/indexnow",
                             data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json; charset=utf-8"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"indexnow: {r.status} ({len(urls)} urls)")
except Exception as e:
    print(f"indexnow: failed ({e})")
PY
