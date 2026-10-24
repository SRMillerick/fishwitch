"""Run the full unittest suite with HTTP/TCP blocked and legacy test config.

Usage: ~/.astro-venv/bin/python tests/run_offline.py
Browser state checks: node tests/report_state.test.cjs
"""
import os
from pathlib import Path
import unittest
from unittest import mock


def main():
    root = Path(__file__).resolve().parent.parent
    # Some legacy attribution tests expect an enabled retailer. This supplies
    # configuration only; no outbound request or affiliate click can execute.
    config = {"FISHWITCH_AMZ_TAG": "baromoon-20", "FISHWITCH_NO_USAGE": "1"}
    with mock.patch.dict(os.environ, config), \
            mock.patch("requests.sessions.Session.request",
                       side_effect=AssertionError("HTTP forbidden in offline tests")), \
            mock.patch("socket.socket.connect",
                       side_effect=AssertionError("network forbidden in offline tests")):
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
