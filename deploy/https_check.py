#!/usr/bin/env python3
"""Small external post-release gate; no personal data or provider calculations."""
import re
import sys
import time
from urllib.request import Request, urlopen


def check(revision, mode):
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or mode not in ("window", "any"):
        raise ValueError("Expected public revision and window/any contract")
    request = Request("https://baromoon.com/?warm=1&release=" + revision,
                      headers={"Cache-Control": "no-cache", "User-Agent": "baromoon-release-check/1"})
    marker = 'id="window-form"' if mode == "window" else "baromoon"
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                if response.geturl().startswith("https://baromoon.com/") and response.status == 200:
                    if marker in response.read(2_000_000).decode("utf-8"):
                        print("HTTPS 200; expected homepage present")
                        return True
        except Exception:
            pass
        time.sleep(2)
    return False


if __name__ == "__main__":
    sys.exit(0 if check(*sys.argv[1:]) else 1)
