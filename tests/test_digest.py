"""The digest generator (plan §10): ready-to-paste community posts.

Two properties matter more than the formatting:

1. **Every fact is the engine's.** The body carries the score, the pick, its
   `technique` and its own reason strings — nothing is authored here, so a post
   cannot claim more than the pipe computed.
2. **The tag survives the attribution layer.** The src the digest puts on a
   landing link must pass `webapp._src_token` *unchanged*, because that token is
   what the page log stores and what rides into Amazon's ascsubtag. If the two
   ever disagree, the distribution test silently measures nothing.
"""
import argparse
import contextlib
import io
import json
import re
import unittest
from datetime import datetime, timedelta
from unittest import mock

import cli
import webapp


def _row(day_offset=1, overall=8.0, picks=("Drop shot", "Wacky-rigged Senko"),
         why=("solunar major — feed window",), technique="slow fall on the break",
         conf="high", prime_ev="sunset + Jupiter hour"):
    day = (datetime.now() + timedelta(days=day_offset)).date()
    start = datetime.combine(day, datetime.min.time()).replace(hour=17, minute=30)
    return dict(day=day, start=start, end=start + timedelta(hours=2), overall=overall,
                ps=10.0, prime_t=start, prime_ev=prime_ev, picks=list(picks),
                why=list(why), technique=technique, solunar="", conf=conf,
                state="heat-streak")


class PostSrcTest(unittest.TestCase):
    """The landing-link tag: a stable short slug per water."""

    def test_priority_waters_get_distinct_short_tags(self):
        tags = [cli._post_src("fb-w1", lid) for lid in cli.DIGEST_PRIORITY]
        self.assertEqual(len(tags), len(set(tags)), f"collision in {tags}")
        for t in tags:
            self.assertLessEqual(len(t), 24, t)

    def test_slug_strips_stacked_suffixes(self):
        self.assertEqual(cli._post_src("fb", "hidden-valley-lake-ca"), "fb-hidden-valley")
        self.assertEqual(cli._post_src("fb", "lake-berryessa"), "fb-berryessa")
        self.assertEqual(cli._post_src("fb", "clear-lake"), "fb-clear")
        self.assertEqual(cli._post_src("fb", "goldwater-lake-az"), "fb-goldwater")
        self.assertEqual(cli._post_src("fb", "yavapai-lakes-az"), "fb-yavapai")

    def test_long_channel_truncates_the_slug_not_the_cap(self):
        tag = cli._post_src("x" * 18, "hidden-valley-lake-ca")
        self.assertEqual(len(tag), 24)
        self.assertTrue(tag.startswith("x" * 18))

    def test_overlong_channel_is_capped(self):
        self.assertEqual(len(cli._post_src("y" * 40, "clear-lake")), 24)

    def test_tag_survives_the_attribution_layer_unchanged(self):
        """The contract with webapp: whatever the digest emits, `_src_token`
        must not rewrite it — otherwise the page log and Amazon's sub-tag would
        record a different tag than the one in the posted link."""
        for lid in cli.DIGEST_PRIORITY:
            for channel in ("fb-w1", "reddit-w2", "forum"):
                tag = cli._post_src(channel, lid)
                self.assertEqual(webapp._src_token(tag), tag,
                                 f"{lid}/{channel} -> {tag} was mangled")
                self.assertEqual(webapp._src_token(tag)[:24], tag)


class WeekendDatesTest(unittest.TestCase):
    def test_only_saturday_and_sunday(self):
        days = cli._weekend_dates(14)
        self.assertTrue(days, "a 14-day horizon should contain a weekend")
        for d in days:
            self.assertIn(d.weekday(), (5, 6))


class PostBodyTest(unittest.TestCase):
    """Every claim in the body must trace to an engine field."""

    def test_body_carries_score_pick_why_technique_and_link(self):
        r = _row()
        url = "https://baromoon.com/report?lake=clear-lake&src=fb-w1-clear"
        body = cli._post_body({"name": "Clear Lake"}, r, url, 3)
        self.assertIn(f"{r['overall']}/10", body)
        self.assertIn(r["conf"], body)
        self.assertIn(f"{r['day']:%a %b %-d}", body)
        self.assertIn("Top pick: Drop shot", body)
        self.assertIn(r["technique"], body)
        for w in r["why"]:
            self.assertIn(w, body)
        self.assertIn(r["prime_ev"], body)
        self.assertIn("Wacky-rigged Senko", body)     # the second pick
        self.assertIn(url, body)

    def test_body_survives_a_bare_window(self):
        """A thin window (no picks, no why) must still produce a usable post."""
        r = _row(picks=(), why=(), technique="", prime_ev="")
        body = cli._post_body({"name": "X"}, r, "https://x/y", 2)
        self.assertIn("best window", body)
        self.assertNotIn("Top pick", body)

    def test_url_appears_once_in_the_body(self):
        """The body is what gets pasted; the header prints the link separately."""
        r = _row()
        url = "https://baromoon.com/report?lake=clear-lake&src=fb-w1-clear"
        self.assertEqual(cli._post_body({"name": "C"}, r, url, 3).count(url), 1)


class DigestCommandTest(unittest.TestCase):
    def _ns(self, **kw):
        base = dict(lakes=None, priority=False, tag="fb-w1", days=3,
                    weekend=False, json=True)
        base.update(kw)
        return argparse.Namespace(**base)

    def _run(self, ns, results=None):
        err = io.StringIO()
        out = io.StringIO()
        rows = results if results is not None else [_row()]
        with mock.patch.object(cli, "_scan_horizon", lambda *a, **k: (list(rows), {})), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.cmd_digest(ns)
        return out.getvalue(), err.getvalue()

    def test_json_block_shape(self):
        out, _ = self._run(self._ns(lakes="clear-lake"))
        blocks = json.loads(out)
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b["lake_id"], "clear-lake")
        self.assertEqual(b["src"], "fb-w1-clear")
        self.assertIn(b["src"], b["body"])

    def test_link_points_at_the_report_page(self):
        """`report.html` is the only template that includes `_tackle.html`, so
        the affiliate links (and therefore the click half of the test) only
        exist on /report. A /lake link would carry no offers at all."""
        out, _ = self._run(self._ns(lakes="clear-lake"))
        url = json.loads(out)[0]["url"]
        self.assertEqual(url, "https://baromoon.com/report?lake=clear-lake&src=fb-w1-clear")

    def test_priority_expands_to_the_plan_list(self):
        out, _ = self._run(self._ns(priority=True))
        ids = [b["lake_id"] for b in json.loads(out)]
        self.assertEqual(len(ids), len(cli.DIGEST_PRIORITY))

    def test_unknown_lake_is_skipped_rather_than_geocoded(self):
        """A typo must not be geocoded into some other water body and then
        advertised with a /lake/<id> page that does not exist."""
        out, err = self._run(self._ns(lakes="clear-lake,not-a-lake"))
        self.assertEqual([b["lake_id"] for b in json.loads(out)], ["clear-lake"])
        self.assertIn("not-a-lake", err)

    def test_duplicate_tag_is_refused_rather_than_double_counted(self):
        """Two posts sharing one tag would merge in the page log and in Amazon's
        Sub-Tag report, silently corrupting the measurement."""
        out, err = self._run(self._ns(lakes="clear-lake,clear-lake"))
        self.assertEqual(len(json.loads(out)), 1)
        self.assertIn("already used", err)

    def test_no_lakes_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.cmd_digest(self._ns())

    def test_no_scorable_window_is_skipped(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self._run(self._ns(lakes="clear-lake"), results=[])

    def test_weekend_filter_drops_weekday_windows(self):
        monday = (datetime.now() + timedelta(days=(7 - datetime.now().weekday()) % 7)).date()
        off_day = next(d for d in (monday + timedelta(days=i) for i in range(1, 8))
                       if d.weekday() not in (5, 6))
        row = _row()
        row["day"] = off_day
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self._run(self._ns(lakes="clear-lake", weekend=True), results=[row])

    def test_human_output_separates_the_body_from_the_header(self):
        out, _ = self._run(self._ns(lakes="clear-lake", json=False))
        self.assertIn("Clear Lake", out)
        self.assertIn("src:  fb-w1-clear", out)
        self.assertIn("Tag every link", out)


if __name__ == "__main__":
    unittest.main()
