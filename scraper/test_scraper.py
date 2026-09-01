#!/usr/bin/env python3
"""Tests for the blog scraper, against saved fixtures -- no network.

The fixtures are real pages, trimmed to their <title> and <table>. Real ones
matter here: every defect these tests guard against was found in actual markup,
not imagined.
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse import (parse_post, normalise_name, strip_region,  # noqa: E402
                   detect_kind, detect_round, detect_format)
from index import parse_post_sitemap, assign_events, event_windows  # noqa: E402

FIX = Path(__file__).parent.parent / "test" / "fixtures" / "blog"
load = lambda n: parse_post((FIX / f"{n}.html").read_text(), n)



_CHECKER_PATH = Path(__file__).resolve().parent.parent / ".github/scripts/check-rounds.py"
_checker_loaded = None


def run_checker(path):
    """check-rounds.py over one file: its exit code and what it printed.

    Loaded once rather than started as a command each time. Seventy-seven
    tests ask this, and at 58ms to start Python that was four and a half
    seconds of an eight second suite spent on an interpreter already running.

    One test still runs it as a command, because that is how CI runs it and
    an argv or exit-code mistake would not show here.
    """
    global _checker_loaded
    if _checker_loaded is None:
        spec = importlib.util.spec_from_file_location("check_rounds_under_test", _CHECKER_PATH)
        _checker_loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_checker_loaded)
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        code = _checker_loaded.main(str(path))
    return code, said.getvalue()



class TestNames(unittest.TestCase):
    def test_region_codes_are_split_out(self):
        # Countries and provinces/states both appear, hence "region".
        for raw, name, code in [("Philip DEU", "Philip", "DEU"),
                                ("Brandon QC", "Brandon", "QC"),
                                ("Humza PA", "Humza", "PA"),
                                ("Samson George ON", "Samson George", "ON")]:
            self.assertEqual(strip_region(raw), (name, code))

    def test_ordinary_names_are_untouched(self):
        for raw in ["George Lucas", "Justin Matthew", "Osorio Bobadilla"]:
            self.assertEqual(strip_region(raw), (raw, None))

    def test_last_comma_first_is_reordered(self):
        self.assertEqual(normalise_name("Gouge, Justin Matthew"), "Justin Matthew Gouge")
        self.assertEqual(normalise_name("Bourgault Morin, Brandon QC"), "Brandon Bourgault Morin")

    def test_first_last_is_left_alone(self):
        self.assertEqual(normalise_name("Aviel Getter"), "Aviel Getter")


class TestFinalPairingKind(unittest.TestCase):
    """The one round the blog titles in the singular."""

    def test_a_final_pairing_is_pairings_not_news(self):
        from parse import detect_kind
        # "Final Pairing" -- one match, so the blog drops the plural. Requiring
        # "pairings" classified it as news, which the fetch budget ranks last, so
        # the round the whole bracket builds towards was the post never fetched.
        for slug in ("ycs-montreal-advanced-format-final-pairing-with-deck-types",
                     "ycs-montreal-genesys-format-final-pairing-with-deck-types",
                     "ycs-orlando-final-pairings"):
            self.assertEqual(detect_kind(slug), "pairings", slug)

    def test_the_plural_still_works(self):
        from parse import detect_kind
        self.assertEqual(detect_kind("ycs-montreal-round-1-pairings-advanced-format"),
                         "pairings")

    def test_it_does_not_swallow_neighbouring_kinds(self):
        from parse import detect_kind
        self.assertEqual(detect_kind("ycs-montreal-top-32-deck-lists"), "deck")
        self.assertEqual(detect_kind("advanced-format-round-4-feature-match-a-vs-b"),
                         "feature")
        self.assertEqual(detect_kind("sunday-advanced-attack-of-the-giant-card-winners"),
                         "result")

    def test_a_final_pairing_names_its_round(self):
        from parse import detect_round
        self.assertEqual(
            detect_round("ycs-montreal-advanced-format-final-pairing-with-deck-types"),
            "Final")


class TestClassification(unittest.TestCase):
    def test_kind(self):
        for text, kind in [("Round 13 Pairings (Advanced Format)", "pairings"),
                           ("Final Standings After Swiss", "standings"),
                           ("Top 32 Deck Lists", "deck"),
                           ("Finals Feature Match: A vs B", "feature"),
                           ("And the Advanced Format Winner Is...", "result")]:
            self.assertEqual(detect_kind(text), kind, text)

    def test_format_is_detected(self):
        self.assertEqual(detect_format("Round 13 Pairings (Advanced Format)"), "Advanced")
        self.assertEqual(detect_format("Genesys Format Top 8 Pairings"), "Genesys")
        self.assertIsNone(detect_format("Deck Lists"))

    def test_final_standings_is_not_the_Final_round(self):
        # "Final Standings After Swiss" is the end of Swiss, not the last cut
        # round; matching a bare "final" filed the whole table under it.
        self.assertIsNone(detect_round("Final Standings After Swiss", "standings"))
        self.assertEqual(detect_round("Finals Feature Match", "feature"), "Final")
        self.assertEqual(detect_round("Round 13 Pairings", "pairings"), 13)
        self.assertEqual(detect_round("Top 8 Pairings", "pairings"), "Top 8")


class TestRealPages(unittest.TestCase):
    def test_standings_page(self):
        p = load("standings-advanced")
        self.assertEqual((p.kind, p.fmt, p.round), ("standings", "Advanced", None))
        self.assertEqual(p.table.kind, "standings")
        self.assertEqual(len(p.table.rows), 766, "a real 767-player event")
        first = p.table.rows[0]
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["name"], "Francisco Andres Osorio Bobadilla")
        self.assertEqual(first["points"], 36)
        # Ranks must be contiguous from 1 -- a parser that drops rows would
        # still look plausible in a spot check.
        self.assertEqual([r["rank"] for r in p.table.rows], list(range(1, 767)))

    def test_pairings_page_with_split_name_columns(self):
        p = load("pairings-round13")
        self.assertEqual((p.kind, p.fmt, p.round), ("pairings", "Advanced", 13))
        self.assertEqual(p.table.kind, "pairings")
        row = p.table.rows[0]
        self.assertEqual(row["table"], 1)
        self.assertEqual(row["a"]["name"], "George Lucas Sacco")
        self.assertEqual(row["b"]["name"], "Francisco Andres Osorio Bobadilla")
        # The region rides on the first-name cell, so it must be stripped per
        # cell rather than from the joined string.
        row2 = p.table.rows[1]
        self.assertEqual(row2["a"], {"name": "Philip Weidinger", "region": "DEU", "deck": None})
        self.assertEqual(row2["b"], {"name": "Dave Vecht", "region": "NLD", "deck": None})

    def test_pairings_page_with_deck_columns(self):
        p = load("pairings-top8-decks")
        self.assertEqual((p.kind, p.fmt, p.round), ("pairings", "Genesys", "Top 8"))
        row = p.table.rows[0]
        self.assertEqual(row["table"], 101, "cut tables are numbered from 101")
        self.assertEqual(row["a"], {"name": "Aviel Getter", "region": None, "deck": "Blitzclique"})
        self.assertEqual(row["b"]["deck"], "Magistus Fairy Tail Invoked")

    def test_the_two_formats_are_distinguished(self):
        adv, gen = load("standings-advanced"), load("standings-genesys")
        self.assertEqual((adv.fmt, gen.fmt), ("Advanced", "Genesys"))
        self.assertNotEqual(len(adv.table.rows), len(gen.table.rows))

    def test_column_layout_is_read_from_headers_not_positions(self):
        # The three layouts have different column counts and orders.
        layouts = {n: load(n).table.columns for n in
                   ("standings-advanced", "pairings-round13", "pairings-top8-decks")}
        self.assertEqual(len(layouts["standings-advanced"]), 3)
        self.assertEqual(len(layouts["pairings-round13"]), 6)
        self.assertEqual(len(layouts["pairings-top8-decks"]), 6)
        self.assertNotEqual(layouts["pairings-round13"], layouts["pairings-top8-decks"])


SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://yugiohblog.konami.com/2026/ycs/2026-08-quebec/a-standings/</loc>
     <lastmod>2026-08-15T10:00:00-07:00</lastmod></url>
<url><loc>https://yugiohblog.konami.com/2026/ycs/2026-08-quebec/b-pairings/</loc>
     <lastmod>2026-08-16T10:00:00-07:00</lastmod></url>
<url><loc>https://yugiohblog.konami.com/2026/ycs/ycs-montreal-round-13-pairings-advanced-format/</loc>
     <lastmod>2026-08-16T12:00:00-07:00</lastmod></url>
<url><loc>https://yugiohblog.konami.com/2026/genesys/unrelated-points-update/</loc>
     <lastmod>2026-01-24T12:00:00-07:00</lastmod></url>
</urlset>"""


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.entries = parse_post_sitemap(SITEMAP)

    def test_event_slug_is_read_only_when_present(self):
        by_slug = {e.slug: e for e in self.entries}
        self.assertEqual(by_slug["a-standings"].event_slug, "2026-08-quebec")
        # A topic segment is not an event.
        self.assertIsNone(by_slug["ycs-montreal-round-13-pairings-advanced-format"].event_slug)
        self.assertIsNone(by_slug["unrelated-points-update"].event_slug)

    def test_windows_come_from_explicit_event_slugs(self):
        self.assertEqual(event_windows(self.entries),
                         {"2026-08-quebec": ("2026-08-15", "2026-08-16")})

    def test_a_post_without_an_event_slug_is_attached_by_date(self):
        got = {r["slug"]: (r["event"], r["event_confidence"]) for r in assign_events(self.entries)}
        self.assertEqual(got["a-standings"], ("2026-08-quebec", "path"))
        self.assertEqual(got["ycs-montreal-round-13-pairings-advanced-format"],
                         ("2026-08-quebec", "date"))
        # Months away from any event, so it stays unattached rather than being
        # forced into the nearest one.
        self.assertEqual(got["unrelated-points-update"], (None, "unmatched"))

    def test_a_date_may_not_duplicate_a_round_the_event_has(self):
        # The January 2022 Remote Duel YCS ran alongside the Latin America
        # Remote Duel YCS. Both published a Top 32, both are filed under
        # "ycs", and only one of them has the event in its URL. A shared
        # weekend and a shared category were enough to take the other one --
        # and Latin America's cut overwrote North America's, leaving one
        # tournament's Top 32 feeding another's Top 16.
        xml = SITEMAP.replace("</urlset>", """
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-08-quebec/top-32-pairings/</loc>
             <lastmod>2026-08-16T10:00:00-07:00</lastmod></url>
        <url><loc>https://yugiohblog.konami.com/2026/ycs/other-event-top-32-pairings/</loc>
             <lastmod>2026-08-16T11:00:00-07:00</lastmod></url>
        </urlset>""")
        got = {r["slug"]: r["event"] for r in assign_events(parse_post_sitemap(xml))}
        self.assertEqual(got["top-32-pairings"], "2026-08-quebec", "its own, by path")
        self.assertIsNone(got["other-event-top-32-pairings"],
                          "a second Top 32 is a second tournament, not this one's")

    def test_the_other_format_is_not_the_same_round(self):
        # The guard above keys a round by its format as well. YCS Montreal
        # runs Advanced and Genesys side by side and both publish a round 13,
        # so a format-blind key made one tournament's coverage refuse the
        # other's -- which split the event in two and lost the posts that
        # nothing else claimed.
        xml = SITEMAP.replace("</urlset>", """
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-08-quebec/round-13-pairings-genesys-format/</loc>
             <lastmod>2026-08-16T10:00:00-07:00</lastmod></url>
        </urlset>""")
        got = {r["slug"]: (r["event"], r["event_confidence"])
               for r in assign_events(parse_post_sitemap(xml))}
        self.assertEqual(got["ycs-montreal-round-13-pairings-advanced-format"],
                         ("2026-08-quebec", "date"),
                         "Advanced round 13 is not the Genesys one")

    def test_concurrent_events_are_refused_not_guessed(self):
        # Two events on the same weekend is real: the 2026 WCQ and the Genesys
        # Championship both ran on 2026-07-11.
        xml = SITEMAP.replace("</urlset>", """
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-07-wcq/x/</loc>
             <lastmod>2026-07-11T10:00:00-07:00</lastmod></url>
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-07-genesys/y/</loc>
             <lastmod>2026-07-11T10:00:00-07:00</lastmod></url>
        <url><loc>https://yugiohblog.konami.com/2026/ycs/some-coverage-post/</loc>
             <lastmod>2026-07-11T11:00:00-07:00</lastmod></url>
        </urlset>""")
        got = {r["slug"]: (r["event"], r["event_confidence"])
               for r in assign_events(parse_post_sitemap(xml))}
        event, confidence = got["some-coverage-post"]
        self.assertIsNone(event, "an ambiguous post must not be assigned an event")
        self.assertTrue(confidence.startswith("ambiguous"), confidence)

    def test_the_format_in_a_slug_breaks_a_tie(self):
        xml = SITEMAP.replace("</urlset>", """
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-07-wcq/x/</loc>
             <lastmod>2026-07-11T10:00:00-07:00</lastmod></url>
        <url><loc>https://yugiohblog.konami.com/2026/ycs/2026-07-genesys-championship/y/</loc>
             <lastmod>2026-07-11T10:00:00-07:00</lastmod></url>
        <url><loc>https://yugiohblog.konami.com/2026/ycs/genesys-format-top-8-pairings/</loc>
             <lastmod>2026-07-11T11:00:00-07:00</lastmod></url>
        </urlset>""")
        got = {r["slug"]: (r["event"], r["event_confidence"])
               for r in assign_events(parse_post_sitemap(xml))}
        self.assertEqual(got["genesys-format-top-8-pairings"],
                         ("2026-07-genesys-championship", "date+format"))



class TestFetcher(unittest.TestCase):
    """The cache, the politeness delay and the update gate, without a network."""

    def setUp(self):
        import tempfile
        from fetch import Fetcher
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []

        def transport(url, ua):
            self.calls.append(url)
            return f"<html>{url}</html>"

        self.f = Fetcher(cache_dir=self.tmp / "cache", delay=0, transport=transport)

    def test_a_page_is_fetched_once_then_served_from_cache(self):
        a = self.f.get("https://example.test/post/")
        b = self.f.get("https://example.test/post/")
        self.assertEqual(a, b)
        self.assertEqual(len(self.calls), 1, "the second read must not hit the network")
        self.assertEqual(self.f.cache_size(), 1)

    def test_refresh_bypasses_the_cache(self):
        self.f.get("https://example.test/a/")
        self.f.get("https://example.test/a/", refresh=True)
        self.assertEqual(len(self.calls), 2)

    def test_the_user_agent_identifies_the_project(self):
        from fetch import USER_AGENT
        self.assertIn("DuelDesk", USER_AGENT)
        self.assertIn("dueldesk.reizu.dev", USER_AGENT)


SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://yugiohblog.konami.com/wp-sitemap-posts-post-1.xml</loc></sitemap>
<sitemap><loc>https://yugiohblog.konami.com/wp-sitemap-posts-post-7.xml</loc></sitemap>
<sitemap><loc>https://yugiohblog.konami.com/wp-sitemap-posts-post-2.xml</loc></sitemap>
<sitemap><loc>https://yugiohblog.konami.com/wp-sitemap-taxonomies-category-1.xml</loc></sitemap>
</sitemapindex>"""


class TestUpdateGate(unittest.TestCase):
    def test_the_newest_sub_sitemap_is_chosen_numerically(self):
        from fetch import newest_sitemap
        # Not by document order, and not by string sort -- "post-10" must beat
        # "post-9" once the blog gets that far.
        self.assertTrue(newest_sitemap(SITEMAP_INDEX).endswith("posts-post-7.xml"))
        many = SITEMAP_INDEX.replace("post-2.xml", "post-10.xml")
        self.assertTrue(newest_sitemap(many).endswith("posts-post-10.xml"))

    def test_taxonomy_sitemaps_are_ignored(self):
        from fetch import newest_sitemap
        self.assertIn("posts-post", newest_sitemap(SITEMAP_INDEX))

    def test_gate_opens_only_when_the_high_water_mark_moves(self):
        import tempfile
        from fetch import Fetcher, check_for_updates, save_state
        tmp = Path(tempfile.mkdtemp())
        sm = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://x/a/</loc><lastmod>2026-08-25T00:00:00-07:00</lastmod></url>
        <url><loc>https://x/b/</loc><lastmod>2026-08-24T00:00:00-07:00</lastmod></url></urlset>"""

        def transport(url, ua):
            return SITEMAP_INDEX if url.endswith("wp-sitemap.xml") else sm

        f = Fetcher(cache_dir=tmp / "c", delay=0, transport=transport)
        state = tmp / "state.json"

        changed, high = check_for_updates(f, state)
        self.assertTrue(changed, "no prior state means everything is new")
        self.assertEqual(high, "2026-08-25T07:00:00+00:00")

        save_state(state, {"high_water": high})
        changed, _ = check_for_updates(f, state)
        self.assertFalse(changed, "unchanged sitemap must close the gate")

        save_state(state, {"high_water": "2020-01-01"})
        changed, _ = check_for_updates(f, state)
        self.assertTrue(changed, "a moved high-water mark must reopen it")


class TestLastmodResolution(unittest.TestCase):
    """The gate watches this value, so its resolution is the gate's resolution."""

    def sitemap(self, *stamps):
        urls = "".join(f"<url><loc>https://x/{i}/</loc>"
                       f"<lastmod>{s}</lastmod></url>" for i, s in enumerate(stamps))
        return ('<?xml version="1.0"?><urlset '
                'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>")

    def test_two_posts_on_one_day_are_two_different_marks(self):
        from fetch import max_lastmod
        # The bug this replaces. A single event day put 34 posts under one date,
        # so the first moved the mark and the other 33 each read as "nothing new".
        morning = max_lastmod(self.sitemap("2026-08-16T09:00:00-07:00"))
        evening = max_lastmod(self.sitemap("2026-08-16T09:00:00-07:00",
                                           "2026-08-16T17:30:00-07:00"))
        self.assertNotEqual(morning, evening,
                            "same day, later post -- the gate must see this")

    def test_the_newest_is_the_latest_instant_not_the_highest_string(self):
        from fetch import max_lastmod
        # 01:00-07:00 is 08:00 UTC and later than 07:00+00:00, but sorts before
        # it. Comparing the published text picks the wrong one.
        got = max_lastmod(self.sitemap("2026-08-16T01:00:00-07:00",
                                       "2026-08-16T07:00:00+00:00"))
        self.assertEqual(got, "2026-08-16T08:00:00+00:00")

    def test_the_mark_is_normalised_so_an_offset_change_is_not_a_change(self):
        from fetch import max_lastmod
        # The blog's offset shifts across daylight saving. The same instant
        # written either way must produce the same stored mark.
        self.assertEqual(max_lastmod(self.sitemap("2026-08-16T08:00:00+00:00")),
                         max_lastmod(self.sitemap("2026-08-16T01:00:00-07:00")))

    def test_a_date_only_stamp_is_still_valid_sitemap_syntax(self):
        from fetch import max_lastmod
        self.assertEqual(max_lastmod(self.sitemap("2026-08-16")),
                         "2026-08-16T00:00:00+00:00")

    def test_a_z_suffix_is_accepted(self):
        from fetch import max_lastmod
        self.assertEqual(max_lastmod(self.sitemap("2026-08-16T08:00:00Z")),
                         "2026-08-16T08:00:00+00:00")

    def test_one_unreadable_stamp_does_not_lose_the_rest(self):
        from fetch import max_lastmod
        got = max_lastmod(self.sitemap("not a date", "2026-08-16T08:00:00+00:00"))
        self.assertEqual(got, "2026-08-16T08:00:00+00:00")

    def test_a_sitemap_with_no_stamps_has_no_mark(self):
        from fetch import max_lastmod
        self.assertIsNone(max_lastmod(self.sitemap()))
        self.assertIsNone(max_lastmod(self.sitemap("", "   ")))

    def test_the_gate_reopens_for_a_post_later_the_same_day(self):
        import tempfile
        from fetch import Fetcher, check_for_updates, save_state
        tmp = Path(tempfile.mkdtemp())
        pages = {"sm": self.sitemap("2026-08-16T09:00:00-07:00")}

        def transport(url, ua):
            return SITEMAP_INDEX if url.endswith("wp-sitemap.xml") else pages["sm"]

        f = Fetcher(cache_dir=tmp / "c", delay=0, transport=transport)
        state = tmp / "state.json"
        _, high = check_for_updates(f, state)
        save_state(state, {"high_water": high})

        # A second post lands two hours later, on the same date.
        pages["sm"] = self.sitemap("2026-08-16T09:00:00-07:00",
                                   "2026-08-16T11:00:00-07:00")
        changed, moved = check_for_updates(f, state)
        self.assertTrue(changed, "this is every round of an event after the first")
        self.assertNotEqual(moved, high)


def _pairing(a, b):
    return {"table": 1, "a": {"name": a, "region": None, "deck": None},
            "b": {"name": b, "region": None, "deck": None}}


class TestRecords(unittest.TestCase):
    def test_losses_come_from_rounds_played_not_the_round_count(self):
        from records import derive
        # Dana dropped after two rounds. rounds-minus-wins would call that 0-4.
        rounds = [[_pairing("Ada", "Dana")], [_pairing("Ada", "Dana")],
                  [_pairing("Ada", "Bo")], [_pairing("Ada", "Bo")]]
        standings = [{"name": "Ada", "points": 12}, {"name": "Dana", "points": 0}]
        got = {r.name: r for r in derive(standings, rounds, event_date="2026-08-16")}
        self.assertEqual((got["Ada"].wins, got["Ada"].losses), (4, 0))
        self.assertEqual((got["Dana"].wins, got["Dana"].losses), (0, 2))
        self.assertEqual(got["Dana"].label(), "0–2")

    def test_placeholders_are_not_players(self):
        from records import derive, count_appearances, is_placeholder
        self.assertTrue(is_placeholder("*** ***"))
        self.assertFalse(is_placeholder("Ada Lovelace"))
        rounds = [[_pairing("Ada", "*** ***")]]
        self.assertEqual(dict(count_appearances(rounds)), {"Ada": 1})
        self.assertEqual(derive([{"name": "*** ***", "points": 0}], rounds), [])

    def test_a_player_never_paired_reports_wins_only(self):
        from records import derive
        got = derive([{"name": "Ghost", "points": 3}], [[_pairing("Ada", "Bo")]],
                     event_date="2026-08-16")[0]
        self.assertEqual(got.confidence, "partial")
        self.assertEqual(got.wins, 3 // 3)
        self.assertIsNone(got.losses)
        self.assertEqual(got.label(), "1–?", "wins known, losses not")

    def test_a_bye_does_not_produce_negative_losses(self):
        from records import derive
        # Two wins on paper, one appearance -- the other was a bye.
        got = derive([{"name": "Ada", "points": 6}], [[_pairing("Ada", "Bo")]],
                     event_date="2026-08-16")[0]
        self.assertEqual(got.confidence, "partial")
        self.assertIsNone(got.losses, "better no answer than a negative one")

    def test_before_2025_09_points_alone_are_ambiguous(self):
        from records import derive
        # 3 points is one win or three draws, and nothing here separates them.
        rounds = [[_pairing("Ada", "Bo")] for _ in range(3)]
        got = derive([{"name": "Ada", "points": 3}], rounds, event_date="2019-05-01")[0]
        self.assertEqual(got.confidence, "unknown")
        self.assertIsNone(got.wins)
        self.assertEqual(got.label(True), "?–?–?", "a draws-era record with nothing known")

    def test_consecutive_standings_resolve_draws_exactly(self):
        from records import derive
        series = [
            [{"name": "Ada", "points": 0}],
            [{"name": "Ada", "points": 3}],    # +3 win
            [{"name": "Ada", "points": 4}],    # +1 draw
            [{"name": "Ada", "points": 4}],    # +0 loss
        ]
        got = derive([{"name": "Ada", "points": 4}], [], event_date="2019-05-01",
                     standings_series=series)[0]
        self.assertEqual(got.confidence, "derived")
        self.assertEqual((got.wins, got.draws, got.losses), (1, 1, 1))
        self.assertEqual(got.label(True), "1–1–1")
        self.assertEqual(got.to_record(),
                         {"wins": 1, "losses": 1, "draws": 1, "confidence": "derived"})

    def test_two_rounds_of_points_resolve_to_one_record(self):
        # The blog does not publish standings after round one -- a table of
        # everyone at three points or none says nothing -- so a series has to be
        # anchored on the first table it does publish, which is round two.
        from records import anchor_record
        self.assertEqual(anchor_record(6, 2), (2, 0, 0))
        self.assertEqual(anchor_record(4, 2), (1, 1, 0))
        self.assertEqual(anchor_record(3, 2), (1, 0, 1))
        self.assertEqual(anchor_record(2, 2), (0, 2, 0))
        self.assertEqual(anchor_record(1, 2), (0, 1, 1))
        self.assertEqual(anchor_record(0, 2), (0, 0, 2))

    def test_three_rounds_do_not_always_resolve(self):
        # 3 points after three rounds is one win and two losses, or three draws.
        from records import anchor_record
        self.assertIsNone(anchor_record(3, 3))
        self.assertEqual(anchor_record(9, 3), (3, 0, 0), "but some still do")

    def test_a_series_is_read_from_where_it_starts_not_from_zero(self):
        # Without the anchor the tally describes only the rounds the series
        # happens to cover: a run beginning after round five called a Duelist on
        # 25 points 2-0-0, which is not a record of anything.
        from records import results_from_standings
        series = [[{"name": "Ada", "points": 4}],     # after R2: 1-1-0
                  [{"name": "Ada", "points": 7}],     # +3 win
                  [{"name": "Ada", "points": 7}]]     # +0 loss
        self.assertEqual(results_from_standings(series, 2),
                         {"Ada": {"wins": 2, "draws": 1, "losses": 1}})

    def test_a_round_nobody_can_attribute_disqualifies_the_record(self):
        # Missing from a table in the middle, or a points move that is not a
        # win, a draw or a loss. A record short a round is not exact; it is
        # wrong by less.
        from records import results_from_standings
        gap = [[{"name": "Ada", "points": 6}], [{"name": "Bo", "points": 6}],
               [{"name": "Ada", "points": 9}]]
        self.assertNotIn("Ada", results_from_standings(gap, 2))
        odd = [[{"name": "Ada", "points": 6}], [{"name": "Ada", "points": 11}]]
        self.assertNotIn("Ada", results_from_standings(odd, 2))

    def test_an_unresolvable_anchor_claims_nobody(self):
        from records import results_from_standings
        self.assertEqual(results_from_standings([[{"name": "Ada", "points": 3}]], 3), {})

    def test_the_real_event_reconciles(self):
        import glob, re
        from records import derive
        from parse import parse_post
        rd = Path(__file__).parent.parent / "test" / "fixtures" / "blog" / "rounds"
        if not rd.exists():
            self.skipTest("round fixtures not committed")
        rounds = [parse_post(Path(f).read_text()).table.rows
                  for f in sorted(glob.glob(str(rd / "r*.html")),
                                  key=lambda p: int(re.search(r"r(\d+)", p).group(1)))]
        st = parse_post((FIX / "standings-advanced.html").read_text()).table.rows
        recs = derive(st, rounds, event_date="2026-08-16")
        self.assertTrue(all(r.losses is None or r.losses >= 0 for r in recs),
                        "no derived record may imply negative losses")


def _sources():
    """Every Montreal fixture, as the builder would receive them."""
    import glob, re as _re
    from build import Source
    out = []
    rd = FIX / "rounds"
    for f in sorted(glob.glob(str(rd / "r*.html")),
                    key=lambda p: int(_re.search(r"r(\d+)", p).group(1))):
        n = int(_re.search(r"r(\d+)", f).group(1))
        out.append(Source(f"https://x/round-{n}/", parse_post(Path(f).read_text()), "12:00"))
    for name in ("standings-advanced", "standings-genesys", "pairings-top8-decks"):
        out.append(Source(f"https://x/{name}/", parse_post((FIX / f"{name}.html").read_text()), "18:40"))
    return out


class TestStatusAnnotations(unittest.TestCase):
    """Reading the round a player left, rather than counting their appearances."""

    def test_each_status_spelling_is_read(self):
        from parse import split_status
        for cell, want in [
            ("Zhou, Alex (0200539277) (Drop - Round 4)", ("drop", 4)),
            ("Racek, Adrien (0200512639) (PlayoffCut - Round 11)", ("playoffcut", 11)),
            ("Pfeiffer, Felix DEU (0303059880) (Cut \u2013 Round 13)", ("cut", 13)),
            ("Lemperg, Kyle (0100000000) (TopX \u2013 Round 7)", ("topx", 7)),
        ]:
            self.assertEqual(split_status(cell), want, cell)

    def test_an_unannotated_cell_has_no_status(self):
        from parse import split_status
        self.assertEqual(split_status("Gangapersaud, Anil ON (0200262499)"),
                         (None, None))

    def test_the_status_never_reaches_the_name(self):
        from parse import normalise_name
        self.assertEqual(
            normalise_name("Racek, Adrien (0200512639) (PlayoffCut - Round 11)"),
            "Adrien Racek", "an inline status stops the player matching pairings")

    def test_standings_rows_carry_the_status(self):
        from parse import parse_table
        t = parse_table(
            "<table><tr><th>Rank</th><th>Player Name</th><th>Points</th></tr>"
            "<tr><td>1</td><td>Zhou, Alex (0200539277) (Drop \u2013 Round 4)</td>"
            "<td>9</td></tr></table>")
        self.assertEqual(t.rows[0]["name"], "Alex Zhou")
        self.assertEqual((t.rows[0]["status"], t.rows[0]["statusRound"]), ("drop", 4))

    def test_a_bye_round_is_counted_from_the_stated_round(self):
        from records import derive
        # 21 points is 7 wins; the player is in ten pairings but played eleven
        # rounds -- one was a bye. Counting appearances gives 7-3, which is ten
        # rounds for an eleven-round player.
        row = {"name": "Isaac", "points": 21,
               "status": "playoffcut", "statusRound": 11}
        rounds = [[_pairing("Isaac", f"Foe{i}")] for i in range(10)]
        got = derive([row], rounds, event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses), (7, 4))
        self.assertEqual(got.rounds_played, 11)
        self.assertEqual(got.confidence, "derived")

    def test_a_cut_player_stops_at_the_last_swiss_round(self):
        from records import derive
        # "Cut - Round 13" is a bracket round, not a Swiss one. Read literally
        # it would charge two extra losses to a finalist.
        standings = [
            {"name": "Felix", "points": 27, "status": "cut", "statusRound": 13},
            {"name": "Other", "points": 9, "status": "playoffcut", "statusRound": 11},
        ]
        rounds = [[_pairing("Felix", "Other")] for _ in range(11)]
        got = derive(standings, rounds, event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses), (9, 2))
        self.assertEqual(got.rounds_played, 11)

    def test_swiss_length_ignores_cut_rounds(self):
        from records import swiss_last_round
        self.assertEqual(swiss_last_round([
            {"status": "drop", "statusRound": 4},
            {"status": "playoffcut", "statusRound": 11},
            {"status": "cut", "statusRound": 14},
        ]), 11)

    def test_swiss_length_is_unknown_without_annotations(self):
        from records import swiss_last_round
        self.assertIsNone(swiss_last_round([{"name": "Ada", "points": 3}]))

    def test_an_unannotated_player_still_counts_appearances(self):
        from records import derive
        row = {"name": "Anil", "points": 24}
        rounds = [[_pairing("Anil", f"Foe{i}")] for i in range(11)]
        got = derive([row], rounds, event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses, got.confidence), (8, 3, "derived"))

    def test_wins_beyond_the_stated_round_stay_partial(self):
        from records import derive
        # Eight wins inside a stated seven rounds is a contradiction. Raising
        # the round count to fit would invent an unbeaten 8-0.
        row = {"name": "Ada", "points": 24, "status": "drop", "statusRound": 7}
        got = derive([row], [[_pairing("Ada", "Bo")]], event_date="2026-08-16")[0]
        self.assertEqual(got.confidence, "partial")
        self.assertIsNone(got.losses)

    def test_stated_rounds_survive_missing_pairings(self):
        from records import derive
        # No pairings at all: appearance counting can say nothing, the stated
        # round still can.
        row = {"name": "Ada", "points": 9, "status": "drop", "statusRound": 5}
        got = derive([row], [], event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses, got.confidence), (3, 2, "derived"))


class TestByes(unittest.TestCase):
    """Rounds played is the last round paired, not the number of pairings."""

    def test_last_appearance_is_not_a_count(self):
        from records import last_appearance, count_appearances
        # Byed rounds 1 and 2, paired in 3 and 4.
        rounds = [[], [], [_pairing("Ada", "Bo")], [_pairing("Ada", "Cy")]]
        self.assertEqual(count_appearances(rounds)["Ada"], 2)
        self.assertEqual(last_appearance(rounds)["Ada"], 4)

    def test_round_numbers_travel_with_the_rows(self):
        from records import last_appearance
        # Rounds 1 and 2 were not fetched; the rows that were are 3 and 4.
        rounds = [[_pairing("Ada", "Bo")], [_pairing("Ada", "Cy")]]
        self.assertEqual(last_appearance(rounds, [3, 4])["Ada"], 4,
                         "without the real numbers this reads as round 2")

    def test_an_earned_bye_no_longer_reads_as_unbeaten(self):
        from records import derive
        # Yacine Sahli: 27 points after eleven rounds, byed rounds 1 and 2.
        # Counting his nine pairings made him 9-0 -- a published unbeaten run.
        rounds = [[], []] + [[_pairing("Yacine", f"Foe{i}")] for i in range(9)]
        got = derive([{"name": "Yacine", "points": 27}], rounds,
                     event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses), (9, 2))
        self.assertEqual(got.rounds_played, 11)

    def test_a_dropped_player_is_not_charged_for_rounds_after_they_left(self):
        from records import derive
        # Played three, dropped. The event ran eleven more. Reading the last
        # round paired must not become "the event length".
        rounds = ([[_pairing("Ada", f"Foe{i}")] for i in range(3)]
                  + [[_pairing("Bo", f"Foe{i}")] for i in range(11)])
        got = derive([{"name": "Ada", "points": 0}], rounds,
                     event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses), (0, 3), "0-3, not 0-14")

    def test_a_mid_event_bye_is_counted(self):
        from records import derive
        # Odd field: one player sits out each round. Paired in 1 and 3, byed 2.
        rounds = [[_pairing("Ada", "Bo")], [_pairing("Bo", "Cy")],
                  [_pairing("Ada", "Cy")]]
        got = derive([{"name": "Ada", "points": 6}], rounds,
                     event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses, got.rounds_played), (2, 1, 3))

    def test_rounds_are_taken_at_their_highest_not_their_last(self):
        from records import last_appearance
        # Pages are normally handed over in order; nothing in this function
        # should depend on that.
        rounds = [[_pairing("Ada", "Bo")], [_pairing("Ada", "Cy")]]
        self.assertEqual(last_appearance(rounds, [7, 3])["Ada"], 7)

    def test_a_round_seen_after_the_stated_one_wins(self):
        from records import derive
        # The annotation says she left in round 4, but she is paired in round 7.
        # A misread annotation must not delete rounds we watched her play.
        row = {"name": "Ada", "points": 9, "status": "drop", "statusRound": 4}
        rounds = [[_pairing("Ada", f"Foe{i}")] for i in range(7)]
        got = derive([row], rounds, event_date="2026-08-16")[0]
        self.assertEqual((got.wins, got.losses, got.rounds_played), (3, 4, 7))

    def test_a_player_never_paired_is_still_unknown(self):
        from records import derive
        got = derive([{"name": "Ghost", "points": 0}], [[_pairing("Ada", "Bo")]],
                     event_date="2026-08-16")[0]
        self.assertEqual(got.confidence, "partial")
        self.assertIsNone(got.losses)


class TestFinalStandingsSelection(unittest.TestCase):
    """Which no-round standings table becomes the end-of-Swiss one, and how the
    post-cut table's annotations reach it."""

    def _src(self, title, rows):
        from build import Source
        from parse import Post, Table
        return Source(url="https://x/", post=Post(title=title, kind="standings",
                                                  fmt="Genesys", round=None,
                                                  table=Table("standings", [], rows)))

    def test_after_swiss_wins_over_day_one_and_post_cut(self):
        from build import pick_final_standings
        day1 = self._src("Final Standings After Day 1 (Genesys Format)", [])
        post = self._src("Final Standings (Genesys Format)", [])
        swiss = self._src("Final Standings After Swiss (Genesys Format)", [])
        for order in ([day1, post, swiss], [swiss, post, day1], [post, swiss, day1]):
            self.assertIs(pick_final_standings(order).post.title,
                          swiss.post.title, "must not depend on publication order")

    def test_day_one_is_the_last_resort(self):
        from build import pick_final_standings
        day1 = self._src("Final Standings After Day 1 (Genesys Format)", [])
        post = self._src("Final Standings (Genesys Format)", [])
        self.assertIs(pick_final_standings([post, day1]), post)

    def test_a_status_does_not_leak_into_an_earlier_round(self):
        from build import build_format, Source
        from parse import Post, Table

        def std(title, rnd, rows):
            return Source(url="https://x/", post=Post(title=title, kind="standings",
                                                      fmt="Genesys", round=rnd,
                                                      table=Table("standings", [], rows)))

        def pairs(rnd, *names):
            def cell(n):
                return {"name": n, "region": None, "deck": None}
            rows = [{"table": 1, "a": cell(names[0]), "b": cell(names[1])}]
            return Source(url="https://x/", post=Post(title=f"Round {rnd} Pairings",
                                                      kind="pairings", fmt="Genesys",
                                                      round=rnd,
                                                      table=Table("pairings", [], rows)))

        # Ada is paired in round 1 and byed in round 2, so pairings can only ever
        # account for one of the two rounds she played. Her status names round 2.
        fmt = build_format("Genesys", [
            pairs(1, "Ada", "Bo"), pairs(2, "Bo", "Cy"),
            std("Standings After Round 1 (Genesys Format)", 1,
                [{"name": "Ada", "rank": 1, "points": 3}]),
            std("Final Standings After Swiss (Genesys Format)", None,
                [{"name": "Ada", "rank": 1, "points": 3}]),
            std("Final Standings (Genesys Format)", None,
                [{"name": "Ada", "rank": 1, "points": 3,
                  "status": "drop", "statusRound": 2}]),
        ])
        r1 = next(r for r in fmt["rounds"] if r["label"] == "R1")
        rec = r1["standings"][0]["record"]
        self.assertEqual((rec["wins"], rec["losses"]), (1, 0),
                         "one round played by round 1, not the two her status names")
        r2 = next(r for r in fmt["rounds"] if r["label"] == "R2")
        rec2 = r2["standings"][0]["record"]
        self.assertEqual((rec2["wins"], rec2["losses"]), (1, 1),
                         "the bye round is only visible through the status")

    def test_annotations_are_collected_across_tables(self):
        from build import status_by_player
        got = status_by_player([
            self._src("Final Standings After Swiss", [{"name": "Ada", "points": 9}]),
            self._src("Final Standings", [
                {"name": "Ada", "points": 9, "status": "drop", "statusRound": 4},
                {"name": "Bo", "points": 3, "status": None, "statusRound": None}]),
        ])
        self.assertEqual(got, {"Ada": {"status": "drop", "statusRound": 4}})


class TestEventNaming(unittest.TestCase):
    """The event's name comes from its posts, not from its URL."""

    def test_the_prevailing_title_prefix_names_the_event(self):
        from naming import event_name
        titles = ["YCS Montréal: Round 3 Pairings (Genesys Format)",
                  "YCS Montréal: Standings After Round 9 (Advanced Format)",
                  "YCS Montréal: Final Standings (Genesys Format)",
                  "Genesys Format Round 4 Feature Match: Someone vs Someone"]
        self.assertEqual(event_name(titles, "2026 08 Quebec"), "YCS Montréal")

    def test_an_en_dash_separator_is_read_too(self):
        from naming import event_name
        self.assertEqual(event_name(["YCS Rio – Round 1 Pairings",
                                     "YCS Rio – Round 2 Pairings"], "slug"), "YCS Rio")

    def test_a_longer_heading_still_names_the_same_event(self):
        from naming import event_name
        # "YCS Montreal Top Tables Update" is thirteen posts naming the same
        # event under a longer heading. Counting them as a rival split the vote.
        titles = (["YCS Montréal: Round 1 Pairings"] * 3
                  + ["YCS Montréal Top Tables Update: Round 4"] * 4
                  + ["Something Else: x"])
        self.assertEqual(event_name(titles, "slug"), "YCS Montréal")

    def test_a_post_that_names_nothing_is_an_abstention(self):
        from naming import event_name
        # Raising the fetch budget from 60 posts to 143 brought in news posts
        # with no event in their heading. Counting those as votes against pushed
        # a 39.9% share under a 40% threshold and renamed the event to its slug:
        # the same coverage, more of it, and a worse answer.
        titles = ["YCS Montréal: Round 1 Pairings"] * 3 + ["Doors open at 9am"] * 40
        self.assertEqual(event_name(titles, "slug"), "YCS Montréal")

    def test_two_equally_supported_names_resolve_the_same_way_twice(self):
        from naming import event_name
        # Nothing here can tell these apart. What it must not do is depend on the
        # order the titles arrived in, so the same event does not get two names
        # across two scrapes.
        a = ["Long Event Name: one", "Long Event Name: two", "Short: one", "Short: two"]
        self.assertEqual(event_name(a, "slug"), event_name(list(reversed(a)), "slug"))

    def test_the_slug_wins_when_the_posts_do_not_agree(self):
        from naming import event_name
        # One oddly-titled post must not get to name the whole event.
        self.assertEqual(event_name(["A: one", "B: two", "C: three", "D: four"],
                                    "2026 08 Quebec"), "2026 08 Quebec")

    def test_titles_without_a_separator_fall_back(self):
        from naming import event_name
        self.assertEqual(event_name(["No separator here"], "fallback"), "fallback")

    def test_an_event_that_never_uses_a_colon_is_still_named(self):
        from naming import event_name
        # The 2026 North America WCQ heads its coverage "North America WCQ Round
        # 13 Pairings", with a colon only on its feature matches -- so the
        # convention saw a handful of unrelated headings, agreed on none of
        # them, and the event reached the archive called "2026 North America Wcq".
        titles = ["North America WCQ Round 13 Pairings",
                  "North America WCQ Round 14 Pairings",
                  "North America WCQ Standings After Round 12",
                  "NAWCQ Round 11 Feature Match: Israel Santos vs. DaVinci Sukienik"]
        self.assertEqual(event_name(titles, "2026 North America Wcq"),
                         "North America WCQ")

    def test_the_longer_of_two_equally_supported_openings_wins(self):
        from naming import event_name
        # Every one of those titles also begins with "North", which is not what
        # the event is called. Same support, so the longer one is free.
        titles = ["North America WCQ Round 13 Pairings",
                  "North America WCQ Round 14 Pairings",
                  "North America WCQ Standings After Round 12"]
        self.assertEqual(event_name(titles, "fallback"), "North America WCQ")

    def test_one_post_cannot_name_an_event_after_itself(self):
        from naming import event_name
        # Every prefix of a lone title has 100% support, so the share alone is
        # not a threshold at all. It nearly named the 2026 North America WCQ
        # "NAWCQ Round 11 Feature Match", after the single post there that used
        # a colon.
        self.assertEqual(event_name(["Doors open at 9am"], "fallback"), "fallback")
        self.assertEqual(
            event_name(["North America WCQ Round 13 Pairings",
                        "North America WCQ Round 14 Pairings",
                        "NAWCQ Round 11 Feature Match: Israel Santos vs. DaVinci Sukienik"],
                       "fallback"),
            "North America WCQ", "one colon title must not outvote the coverage")

    def test_a_minority_opening_is_not_the_events_name(self):
        from naming import event_name
        # No convention and no consensus either: three pairs of posts that
        # happen to open alike. The most common of them is still only a third of
        # the coverage, which is not an event naming itself -- the slug is the
        # honest answer.
        titles = ["Doors open at 9am", "Doors open at 10am",
                  "Welcome to the venue", "Welcome to day two",
                  "Prize wall restocked", "Prize wall sold out"]
        self.assertEqual(event_name(titles, "2026 08 Quebec"), "2026 08 Quebec")

    def test_a_stated_name_is_not_overridden_by_a_common_opening(self):
        from naming import event_name
        # The fallback is only reached when the convention gives no answer. Here
        # it does, and "YCS" opens more titles than "YCS Montréal:" does.
        titles = ["YCS Montréal: Round 3 Pairings"] * 4 + ["YCS Championship Series news"]
        self.assertEqual(event_name(titles, "fallback"), "YCS Montréal")
        self.assertEqual(event_name([], "fallback"), "fallback")

    def test_the_posting_time_is_shown_as_published(self):
        from naming import clock
        # Not converted to UTC: 11:07 Pacific is 18:07 UTC, and a Saturday
        # afternoon round would read as evening.
        self.assertEqual(clock("2026-08-16T11:07:30-07:00"), "11:07")

    def test_a_value_that_is_not_a_timestamp_passes_through(self):
        from naming import clock
        self.assertEqual(clock("08:24"), "08:24")
        self.assertIsNone(clock(None))


class TestFeed(unittest.TestCase):
    """The feed built from real coverage, rather than from the simulation."""

    ITEMS = [
        {"title": "YCS Montréal: Round 3 Pairings (Genesys Format)",
         "url": "https://yugiohblog.konami.com/a/",
         "modified": "2026-08-16T11:07:30-07:00", "kind": "pairings"},
        {"title": "YCS Montréal: Final Standings",
         "url": "https://yugiohblog.konami.com/b/",
         "modified": "2026-08-16T17:00:00-07:00", "kind": "standings"},
    ]

    def feed(self, items=None, **kw):
        from feed import build_feed
        return build_feed("YCS Montréal", self.ITEMS if items is None else items, **kw)

    def test_it_is_well_formed_and_has_the_items(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(self.feed())
        self.assertEqual(len(root.findall("channel/item")), 2)

    def test_items_link_to_the_source_not_to_us(self):
        import xml.etree.ElementTree as ET
        # The whole basis for the feed: it says what was published and where to
        # read it. A link back here would be claiming the coverage.
        for item in ET.fromstring(self.feed()).findall("channel/item"):
            self.assertTrue(item.findtext("link").startswith("https://yugiohblog.konami.com/"))

    def test_it_never_claims_to_be_sample_data(self):
        self.assertNotIn("sample", self.feed().lower())

    def test_it_says_whose_coverage_it_is(self):
        import xml.etree.ElementTree as ET
        ch = ET.fromstring(self.feed()).find("channel")
        self.assertIn("konami", (ch.findtext("description") or "").lower())
        self.assertIn("konami", (ch.findtext("copyright") or "").lower())

    def test_newest_first(self):
        import xml.etree.ElementTree as ET
        titles = [i.findtext("title")
                  for i in ET.fromstring(self.feed()).findall("channel/item")]
        self.assertEqual(titles[0], "YCS Montréal: Final Standings")

    def test_an_item_a_reader_cannot_open_is_dropped(self):
        import xml.etree.ElementTree as ET
        items = self.ITEMS + [{"title": "", "url": "https://x/", "kind": "news"},
                              {"title": "No link", "url": None, "kind": "news"}]
        self.assertEqual(len(ET.fromstring(self.feed(items)).findall("channel/item")), 2)

    def test_dates_are_rfc822_and_locale_independent(self):
        from feed import rfc822
        # strftime("%a, %d %b") renders month names in the running locale, and a
        # reader parsing "sam., 16 août" gets nothing.
        self.assertEqual(rfc822("2026-08-16T11:07:30-07:00"),
                         "Sun, 16 Aug 2026 18:07:30 +0000")
        self.assertEqual(rfc822("2026-08-16"), "Sun, 16 Aug 2026 00:00:00 +0000")
        self.assertIsNone(rfc822("not a date"))
        self.assertIsNone(rfc822(None))

    def test_dates_stay_english_under_another_locale(self):
        import locale
        from feed import rfc822
        # RFC 822 day and month names are English by specification. strftime
        # renders them in LC_TIME, so a process that has set a locale -- or a
        # future caller of setlocale anywhere in the scraper -- would emit
        # "dim., 16 août 2026" and every reader would fail to parse the date.
        for candidate in ("fr_FR.UTF-8", "de_DE.UTF-8", "es_ES.UTF-8"):
            try:
                locale.setlocale(locale.LC_TIME, candidate)
            except locale.Error:
                continue
            try:
                self.assertEqual(rfc822("2026-08-16T11:07:30-07:00"),
                                 "Sun, 16 Aug 2026 18:07:30 +0000")
            finally:
                locale.setlocale(locale.LC_TIME, "C")
            return
        self.skipTest("no non-English locale installed to test against")

    def test_markup_in_a_title_cannot_break_the_feed(self):
        import xml.etree.ElementTree as ET
        items = [{"title": 'Round 1 <b>"pairings"</b> & more',
                  "url": "https://yugiohblog.konami.com/c/",
                  "modified": "2026-08-16T11:00:00-07:00", "kind": "pairings"}]
        root = ET.fromstring(self.feed(items))
        # The event prefix is added by titled(); what matters here is that the
        # markup survives the round trip as text rather than breaking the XML.
        self.assertEqual(root.findtext("channel/item/title"),
                         'YCS Montréal: Round 1 <b>"pairings"</b> & more')

    def test_an_event_with_no_usable_posts_still_parses(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(self.feed([]))
        self.assertEqual(len(root.findall("channel/item")), 0)


class TestRoundDetail(unittest.TestCase):
    """What a round panel can say beyond its own pairings table.

    Built from synthetic posts rather than the saved pages: the fixture set has
    no feature match and only one cut round, and the behaviour under test is the
    shape of an event -- Swiss, then a bracket that narrows -- not the parsing of
    any particular page, which is covered elsewhere.
    """

    def event(self):
        from build import Source, build_event
        from parse import Post, Table

        def pairs(rnd, table_rows, url, posted="12:00"):
            rows = [{"table": i + 1,
                     "a": {"name": a, "region": None, "deck": None},
                     "b": {"name": b, "region": None, "deck": None}}
                    for i, (a, b) in enumerate(table_rows)]
            return Source(url, Post(f"Round {rnd} Pairings", "pairings", "Advanced",
                                    rnd, Table("pairings", [], rows)), posted)

        # Four Duelists, three Swiss rounds, then a bracket that halves.
        names = ["Ada", "Bo", "Cy", "Di"]
        sources = [
            pairs(1, [("Ada", "Bo"), ("Cy", "Di")], "https://x/r1/"),
            pairs(2, [("Ada", "Cy"), ("Bo", "Di")], "https://x/r2/"),
            pairs(3, [("Ada", "Di"), ("Bo", "Cy")], "https://x/r3/"),
        ]
        def table(rows):
            return [{"rank": i + 1, "name": n, "region": None, "points": pts,
                     "status": None, "statusRound": None}
                    for i, (n, pts) in enumerate(rows)]

        # Standings after round 2, so round 3's pairings have something to carry.
        sources.append(Source("https://x/after-2/",
                              Post("Standings After Round 2", "standings", "Advanced",
                                   2, Table("standings", [], table(
                                       [("Ada", 6), ("Bo", 3), ("Cy", 3), ("Di", 0)]))),
                              "15:00"))
        standings = table([("Ada", 9), ("Bo", 6), ("Cy", 3), ("Di", 0)])
        sources.append(Source("https://x/final/",
                              Post("Final Standings After Swiss", "standings", "Advanced",
                                   None, Table("standings", [], standings)), "18:00"))
        sources.append(pairs("Top 4", [("Ada", "Di"), ("Bo", "Cy")], "https://x/t4/", "19:00"))
        sources.append(pairs("Final", [("Ada", "Bo")], "https://x/final-match/", "20:00"))

        # Two feature matches in round 2, newest first in source order on
        # purpose: taking whichever arrives last would pick the older one, so
        # the tie-break has to actually run for these to pass.
        for when, who, url in (("13:30", "Bo vs. Di", "https://x/f-new/"),
                               ("13:00", "Ada vs. Cy", "https://x/f-old/")):
            sources.append(Source(url, Post(f"Round 2 Feature Match: {who}", "feature",
                                            "Advanced", 2, None), when))
        return build_event("Synthetic", sources, updated="2026-08-16T20:00:00Z")

    def setUp(self):
        self.fmt = next(f for f in self.event()["formats"] if f["format"] == "Advanced")
        self.cut = [r for r in self.fmt["rounds"] if r["phase"] == "Top cut"]

    def test_a_cut_round_names_the_standings_it_was_seeded_from(self):
        # It has no table of its own -- nothing is published after Swiss -- so it
        # names the Swiss round it came from and the page follows that. Carrying
        # a copy in each cut round said the same thing three times and took
        # rounds.json from 1.4MB to 2.3MB, downloaded on every visit.
        self.assertTrue(self.cut, "the bracket did not build")
        rounds = {str(r["id"]): r for r in self.fmt["rounds"]}
        for r in self.cut:
            self.assertEqual(r["standings"], [], f"{r['label']} carries a copy")
            self.assertEqual(r["standingsAfter"], self.fmt["swissRounds"])
            named = rounds.get(str(r["standingsAfter"]))
            self.assertIsNotNone(named, f"{r['label']} names a round that is not here")
            self.assertTrue(named["standings"], "the table it names is empty")

    def test_cut_pairings_carry_records(self):
        for row in self.cut[0]["pairings"]:
            self.assertIsNotNone(row["aRec"], f"{row['a']} has no record")
            self.assertIsNotNone(row["bRec"], f"{row['b']} has no record")

    def test_advancing_through_the_bracket_adds_a_win(self):
        # Being paired in a later cut round is proof of winning the earlier one,
        # which is the only reason a record may move with no results table.
        early, late = self.cut[0], self.cut[1]
        seen = {}
        for row in early["pairings"]:
            seen[row["a"]] = row["aRec"]["wins"]
            seen[row["b"]] = row["bRec"]["wins"]
        checked = 0
        for row in late["pairings"]:
            for name, rec in ((row["a"], row["aRec"]), (row["b"], row["bRec"])):
                self.assertEqual(rec["wins"], seen[name] + 1,
                                 f"{name} advanced without gaining a win")
                checked += 1
        self.assertGreater(checked, 0, "no Duelist appears in both rounds")

    def test_a_swiss_round_carries_the_previous_round_s_records(self):
        # The standings after round 2 exist in this event, so round 3's pairings
        # know what each Duelist brought to the table. Only rounds with no
        # published points before them stay blank -- which at YCS Montreal was
        # rounds 1-8, not every Swiss round, as this first assumed.
        r3 = next(r for r in self.fmt["rounds"] if r["label"] == "R3")
        self.assertTrue(all(row["aRec"] and row["bRec"] for row in r3["pairings"]),
                        "records were available and not used")

    def test_a_round_with_nothing_published_before_it_stays_blank(self):
        r1 = next(r for r in self.fmt["rounds"] if r["label"] == "R1")
        self.assertTrue(all(row["aRec"] is None for row in r1["pairings"]),
                        "nothing is known yet, and blank is the honest answer")

    def test_every_feature_match_reaches_its_round(self):
        r2 = next(r for r in self.fmt["rounds"] if r["label"] == "R2")
        self.assertEqual([f["source"] for f in r2["features"]],
                         ["https://x/f-new/", "https://x/f-old/"],
                         "both of them, newest first")

    def test_a_feature_match_states_only_what_the_post_says(self):
        r2 = next(r for r in self.fmt["rounds"] if r["label"] == "R2")
        f = r2["features"][0]
        self.assertEqual((f["a"]["name"], f["b"]["name"]), ("Bo", "Di"))
        # A feature post has no table. Printing a final Swiss record beside a
        # round-two match would be a plausible-looking lie.
        self.assertIsNone(f["a"]["deck"])
        self.assertIsNone(f["a"]["record"])

    def test_a_round_with_no_feature_says_so(self):
        r1 = next(r for r in self.fmt["rounds"] if r["label"] == "R1")
        self.assertEqual(r1["features"], [])


class TestDerivedFinal(unittest.TestCase):
    """A final that was played but never paired."""

    def standings(self, rows):
        from build import Source
        from parse import Post, Table
        return Source("https://x/final-standings/",
                      Post("Final Standings", "standings", "Advanced", None,
                           Table("standings", [], rows)), "21:00")

    def row(self, rank, name, status=None, when=None):
        return {"rank": rank, "name": name, "region": None, "points": 30 - rank,
                "status": status, "statusRound": when}

    def test_one_loser_and_one_unbeaten_name_the_final(self):
        from build import final_from_annotations
        got = final_from_annotations([self.standings([
            self.row(1, "Champ"),
            self.row(2, "Runner", "cut", 14),
            self.row(3, "Semi", "cut", 13),
            self.row(9, "Dropped", "drop", 4),
        ])])
        self.assertEqual(got, ("Runner", "Champ"))

    def test_two_unbeaten_is_not_a_final(self):
        from build import final_from_annotations
        # A table this cannot read. Inventing a final is worse than stopping at
        # the Top 4, which is what the coverage actually published.
        self.assertIsNone(final_from_annotations([self.standings([
            self.row(1, "Champ"), self.row(2, "Also"),
            self.row(3, "Runner", "cut", 14),
        ])]))

    def test_two_losing_the_last_bracket_round_is_not_a_final(self):
        from build import final_from_annotations
        self.assertIsNone(final_from_annotations([self.standings([
            self.row(1, "Champ"),
            self.row(2, "Runner", "cut", 14),
            self.row(3, "Other", "cut", 14),
        ])]))

    def test_a_published_final_is_not_duplicated_by_a_derived_one(self):
        from build import Source, build_event
        from parse import Post, Table

        def pairs(label, rows, url):
            return Source(url, Post(f"{label} Pairings", "pairings", "Advanced", label,
                                    Table("pairings", [], [
                                        {"table": i + 1,
                                         "a": {"name": a, "region": None, "deck": None},
                                         "b": {"name": b, "region": None, "deck": None}}
                                        for i, (a, b) in enumerate(rows)])), "20:00")

        ev = build_event("X", [
            pairs(1, [("Champ", "Runner")], "https://x/r1/"),
            pairs("Top 4", [("Champ", "Semi"), ("Runner", "Other")], "https://x/t4/"),
            pairs("Final", [("Champ", "Runner")], "https://x/final-match/"),
            self.standings([
                self.row(1, "Champ"), self.row(2, "Runner", "cut", 14),
                self.row(3, "Semi", "cut", 13), self.row(4, "Other", "cut", 13),
            ]),
        ], updated="2026-08-16T21:00:00Z")
        fmt = ev["formats"][0]
        finals = [r for r in fmt["rounds"] if r["label"] == "Final"]
        self.assertEqual(len(finals), 1, "the published final was doubled")
        self.assertEqual(finals[0]["source"], "https://x/final-match/",
                         "the published round wins; the derived one fills a gap")

    def test_a_cut_round_is_named_for_how_many_are_left_in_it(self):
        # The 2019 North America WCQ titles a post "Top 4 Pairings" and puts
        # four matches in it -- eight Duelists, which is a Top 8. The same
        # event titles its Top 64 post with 32 matches and its Top 16 with 8,
        # so the one post is a slip. Read as written the Top 4 became a team
        # round of two a side and 115 posts left the archive.
        from build import Source, build_event
        from parse import Post, Table

        def pairs(label, rows, url):
            return Source(url, Post(f"{label} Pairings", "pairings", None, label,
                                    Table("pairings", [], [
                                        {"table": i + 1,
                                         "a": {"name": a, "region": None, "deck": None},
                                         "b": {"name": b, "region": None, "deck": None}}
                                        for i, (a, b) in enumerate(rows)])), "20:00")

        ev = build_event("WCQ", [
            pairs("Top 16", [("A", "B"), ("C", "D"), ("E", "F"), ("G", "H"),
                             ("I", "J"), ("K", "L"), ("M", "N"), ("O", "P")],
                  "https://x/top-16/"),
            pairs("Top 4", [("A", "C"), ("E", "G"), ("I", "K"), ("M", "O")],
                  "https://x/mislabelled/"),
            Source("https://x/standings/",
                   Post("Final Standings", "standings", None, None,
                        Table("standings", [],
                              [self.row(i + 1, n) for i, n in enumerate("ABCDEFGH")])),
                   "21:00"),
        ], updated="2026-08-16T21:00:00Z")

        labels = [r["label"] for r in ev["formats"][0]["rounds"]]
        self.assertIn("Top 8", labels, "four matches is a Top 8, whatever it was called")
        self.assertNotIn("Top 4", labels)
        eight = next(r for r in ev["formats"][0]["rounds"] if r["label"] == "Top 8")
        self.assertEqual(eight["source"], "https://x/mislabelled/")

    def test_a_cut_round_that_agrees_with_its_name_is_left_alone(self):
        from build import relabel_by_size
        from parse import Post, Table
        from build import Source

        def post(label, n):
            return {"pairings": Source(
                f"https://x/{label}/",
                Post(f"{label} Pairings", "pairings", None, label,
                     Table("pairings", [], [
                         {"table": i + 1,
                          "a": {"name": f"a{i}", "region": None, "deck": None},
                          "b": {"name": f"b{i}", "region": None, "deck": None}}
                         for i in range(n)])), "20:00")}

        by_round = {("cut", "Top 8"): post("Top 8", 4),
                    ("cut", "Top 4"): post("Top 4", 2)}
        relabel_by_size(by_round)
        self.assertEqual(sorted(by_round), [("cut", "Top 4"), ("cut", "Top 8")])

    def test_a_relabelled_round_never_lands_on_a_name_already_taken(self):
        from build import relabel_by_size, Source
        from parse import Post, Table

        def post(label, n):
            return {"pairings": Source(
                f"https://x/{label}/",
                Post(f"{label} Pairings", "pairings", None, label,
                     Table("pairings", [], [
                         {"table": i + 1,
                          "a": {"name": f"a{i}", "region": None, "deck": None},
                          "b": {"name": f"b{i}", "region": None, "deck": None}}
                         for i in range(n)])), "20:00")}

        # A "Top 4" holding four matches wants to become Top 8, but this event
        # published a real Top 8 as well. Neither moves; the checker can say so
        # far better than a guess can.
        by_round = {("cut", "Top 8"): post("Top 8", 4),
                    ("cut", "Top 4"): post("Top 4", 4)}
        relabel_by_size(by_round)
        self.assertEqual(sorted(by_round), [("cut", "Top 4"), ("cut", "Top 8")])
        self.assertEqual(by_round[("cut", "Top 4")]["pairings"].url,
                         "https://x/Top 4/")

    def test_only_the_pairings_move_off_a_wrong_name(self):
        # A standings table filed under the same name is a different post
        # making its own claim about a different thing, and it stays.
        from build import relabel_by_size, Source
        from parse import Post, Table

        def pairings(n):
            return Source("https://x/p/", Post("Top 4 Pairings", "pairings", None, "Top 4",
                                               Table("pairings", [], [
                                                   {"table": i + 1,
                                                    "a": {"name": f"a{i}", "region": None, "deck": None},
                                                    "b": {"name": f"b{i}", "region": None, "deck": None}}
                                                   for i in range(n)])), "20:00")

        standings = Source("https://x/s/",
                           Post("Top 4 Standings", "standings", None, "Top 4",
                                Table("standings", [], [])), "21:00")
        by_round = {("cut", "Top 4"): {"pairings": pairings(4), "standings": standings}}
        relabel_by_size(by_round)
        self.assertEqual(sorted(by_round), [("cut", "Top 4"), ("cut", "Top 8")])
        self.assertEqual(by_round[("cut", "Top 8")]["pairings"].url, "https://x/p/")
        self.assertEqual(by_round[("cut", "Top 4")], {"standings": standings},
                         "the standings post never claimed to be a Top 8")

    def test_a_team_round_is_not_counted_this_way(self):
        # A team round's rows are matches, not duels, and a partly published
        # one counts to a number that looks like a bracket without being one:
        # two of a Top 8's four team matches would read as a Top 4.
        from build import relabel_by_size, Source
        from parse import Post, Table

        rows = [{"table": i + 1,
                 "a": {"name": f"Team {i}A", "region": None, "deck": None},
                 "b": {"name": f"Team {i}B", "region": None, "deck": None},
                 "duels": [{"table": i + 1, "a": "x", "b": "y"}]} for i in range(2)]
        by_round = {("cut", "Top 8"): {"pairings": Source(
            "https://x/p/", Post("Top 8 Pairings", "pairings", None, "Top 8",
                                 Table("pairings", [], rows)), "20:00")}}
        relabel_by_size(by_round)
        self.assertEqual(sorted(by_round), [("cut", "Top 8")])

    def test_a_count_that_is_not_a_bracket_is_not_an_answer(self):
        # Three matches is six Duelists, which is no bracket at all. The table
        # is partial, not misnamed, and "Top 6" would be worse than "Top 8".
        from build import relabel_by_size, Source
        from parse import Post, Table

        rows = [{"table": i + 1,
                 "a": {"name": f"a{i}", "region": None, "deck": None},
                 "b": {"name": f"b{i}", "region": None, "deck": None}} for i in range(3)]
        by_round = {("cut", "Top 8"): {"pairings": Source(
            "https://x/p/", Post("Top 8 Pairings", "pairings", None, "Top 8",
                                 Table("pairings", [], rows)), "20:00")}}
        relabel_by_size(by_round)
        self.assertEqual(sorted(by_round), [("cut", "Top 8")])

    def test_a_tournament_alongside_is_not_a_round_of_the_one_beside_it(self):
        # The 2018 South America WCQ has no Top 8 pairings post of its own, so
        # the Dragon Duel's stood in as one: eight children who never played in
        # the Top 16, and forty-five posts refused over it. Every post of a WCQ
        # names no format, so grouping by the post's format put both
        # tournaments in one bracket.
        from build import Source, build_event
        from parse import Post, Table

        def pairs(title, label, rows, url):
            return Source(url, Post(title, "pairings", None, label,
                                    Table("pairings", [], [
                                        {"table": i + 1,
                                         "a": {"name": a, "region": None, "deck": None},
                                         "b": {"name": b, "region": None, "deck": None}}
                                        for i, (a, b) in enumerate(rows)])), "20:00")

        def table(title, rows, url):
            return Source(url, Post(title, "standings", None, None,
                                    Table("standings", [], rows)), "21:00")

        ev = build_event("South America WCQ", [
            pairs("South America WCQ: Pairings for Top 4", "Top 4",
                  [("Ann Alpha", "Bo Beta"), ("Cy Gamma", "Di Delta")],
                  "https://x/wcq-top-4/"),
            table("South America WCQ: Final Standings",
                  [self.row(1, "Ann Alpha"), self.row(2, "Bo Beta"),
                   self.row(3, "Cy Gamma"), self.row(4, "Di Delta")],
                  "https://x/wcq-standings/"),
            pairs("South America Dragon Duel WCQ: Pairings for Top 4", "Top 4",
                  [("Kid One", "Kid Two"), ("Kid Three", "Kid Four")],
                  "https://x/dd-top-4/"),
        ], updated="2026-08-16T21:00:00Z")

        named = {f["format"]: f for f in ev["formats"]}
        self.assertEqual(set(named), {None, "Dragon Duel"})
        main = named[None]["rounds"][0]["pairings"]
        self.assertEqual([p["a"] for p in main], ["Ann Alpha", "Cy Gamma"],
                         "the main event kept only its own Top 4")
        kids = named["Dragon Duel"]["rounds"][0]["pairings"]
        self.assertEqual([p["a"] for p in kids], ["Kid One", "Kid Three"])

    def test_a_derived_final_carries_no_copy_of_the_standings_either(self):
        from build import Source, build_event
        from parse import Post, Table

        def pairs(label, rows, url):
            return Source(url, Post(f"{label} Pairings", "pairings", "Advanced", label,
                                    Table("pairings", [], [
                                        {"table": i + 1,
                                         "a": {"name": a, "region": None, "deck": None},
                                         "b": {"name": b, "region": None, "deck": None}}
                                        for i, (a, b) in enumerate(rows)])), "20:00")

        ev = build_event("X", [
            pairs(1, [("Champ", "Runner")], "https://x/r1/"),
            pairs("Top 4", [("Champ", "Semi"), ("Runner", "Other")], "https://x/t4/"),
            self.standings([
                self.row(1, "Champ"), self.row(2, "Runner", "cut", 14),
                self.row(3, "Semi", "cut", 13), self.row(4, "Other", "cut", 13),
            ]),
        ], updated="2026-08-16T21:00:00Z")
        final = next(r for r in ev["formats"][0]["rounds"] if r["label"] == "Final")
        self.assertEqual(final["pairings"][0]["a"], "Champ")
        self.assertEqual(final["standings"], [],
                         "it names the Swiss table like every other cut round")
        self.assertTrue(final["standingsAfter"])

    def test_standings_with_no_cut_annotations_say_nothing(self):
        from build import final_from_annotations
        # Advanced published only its after-Swiss table, so its final is unknown
        # and stays unknown rather than being guessed at.
        self.assertIsNone(final_from_annotations([self.standings([
            self.row(1, "Champ"), self.row(2, "Runner"),
        ])]))
        self.assertIsNone(final_from_annotations([]))


class TestOngoing(unittest.TestCase):
    """Whether the site may say a round is in progress."""

    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

    def ago(self, **kw):
        from datetime import timedelta
        return self.now - timedelta(**kw)

    def test_recent_coverage_means_the_event_is_running(self):
        from cadence import is_ongoing
        self.assertTrue(is_ongoing(self.ago(minutes=40), self.now))

    def test_coverage_that_stopped_means_it_is_over(self):
        from cadence import is_ongoing
        self.assertFalse(is_ongoing(self.ago(days=12), self.now),
                         "this is the state the site published on its first day")
        self.assertFalse(is_ongoing(self.ago(hours=7), self.now))

    def test_nothing_known_is_not_a_reason_to_claim_live(self):
        from cadence import is_ongoing
        self.assertFalse(is_ongoing(None, self.now))

    def test_build_format_will_not_claim_live_unasked(self):
        from build import build_format, Source
        from parse import Post, Table
        rows = [{"table": 1, "a": {"name": "Ada", "region": None, "deck": None},
                 "b": {"name": "Bo", "region": None, "deck": None}}]
        src = Source(url="https://x/", posted="2026-08-16T11:07:30-07:00",
                     post=Post(title="Round 1 Pairings", kind="pairings",
                               fmt="Advanced", round=1,
                               table=Table("pairings", [], rows)))
        # A caller that does not say must not get a live round by default.
        self.assertEqual(
            [r for r in build_format("Advanced", [src])["rounds"] if r["state"] == "live"],
            [])
        self.assertEqual(
            len([r for r in build_format("Advanced", [src], ongoing=True)["rounds"]
                 if r["state"] == "live"]), 1)

    def test_a_post_from_the_future_does_not_count(self):
        from datetime import timedelta
        from cadence import is_ongoing
        self.assertFalse(is_ongoing(self.now + timedelta(hours=2), self.now))


class TestProvenanceCheck(unittest.TestCase):
    """check-rounds.py is what stops a file that misdescribes itself reaching
    the site. It runs in CI against real data, but its own rules had no test,
    and this is the rule that decides whether invented records get served as
    coverage."""

    CHECKER = Path(__file__).resolve().parent.parent / ".github/scripts/check-rounds.py"

    def subject(self, needs=None):
        """The newest published event with a top cut these rules can be read on.

        Through the manifest rather than by path, exactly as the page finds it,
        so this cannot end up checking a file nothing serves -- but the newest
        event is whichever tournament happened last, and its shape is not this
        suite's to choose. The 2026 World Championship arrived in the archive
        with a single cut round, and every test here that reaches for a second
        one broke on data that was perfectly valid.

        So the newest is not assumed to be suitable, only preferred: the first
        one down the list carrying two rounds of cut pairings is used.

        `needs` asks for more than that. A test that mutates a derived record
        has to be given an event that has one -- the 2026 World Championship
        has none, and when it arrived at the head of the manifest the two tests
        that mutate records stopped testing anything: one asserted a rejection
        for a file it had not changed, the other subtracted from a record whose
        wins were None.
        """
        import json
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "events.json").read_text())
        for entry in manifest["events"]:
            event = json.loads((root / entry["path"]).read_text())
            fmt = (event.get("formats") or [{}])[0]
            cut = [r for r in fmt.get("rounds") or [] if r.get("phase") == "Top cut"]
            if len([r for r in cut if r.get("pairings")]) >= 2 and (needs is None
                                                                    or needs(event)):
                return event
        raise self.skipTest("no published event has the shape this test needs")

    @staticmethod
    def derived_rows(event):
        """The standings rows carrying a derived record and the points for it."""
        return [st for fmt in event["formats"] for r in fmt["rounds"]
                for st in (r.get("standings") or [])
                if (st.get("record") or {}).get("confidence") == "derived"
                and st.get("points") is not None
                and (st["record"].get("wins") is not None)]

    def check(self, mutate, needs=None):
        """Run the checker over a published event, mutated."""
        import json, subprocess, tempfile
        good = self.subject(needs)
        mutate(good)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(good, fh)
            path = fh.name
        return run_checker(path)

    def test_the_checker_still_works_as_a_command(self):
        # Every other test loads check-rounds.py and calls it. CI runs it as a
        # command, so one test does too: an argv mistake, a bad exit code or an
        # import that only fails at start-up would not show any other way.
        import subprocess
        good = self.subject(None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(good, fh)
            path = fh.name
        done = subprocess.run([sys.executable, str(self.CHECKER), path],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("ok", done.stdout)
        # And a file it should reject exits 1, so the gate is a real gate.
        bad = self.subject(None)
        bad["formats"][0]["rounds"] = []
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(bad, fh)
            badpath = fh.name
        done = subprocess.run([sys.executable, str(self.CHECKER), badpath],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stdout)

    def test_the_committed_data_passes(self):
        code, out = self.check(lambda d: None)
        self.assertEqual(code, 0, out)

    def test_a_file_that_does_not_say_what_it_is_is_rejected(self):
        code, out = self.check(lambda d: d.pop("sample"))
        self.assertEqual(code, 1)
        self.assertIn("sample", out)

    def test_a_truthy_value_that_is_not_boolean_is_rejected(self):
        # "yes" and 1 are both truthy, and the page requires exactly true, so a
        # file saying either would be served with no badge over invented data.
        for value in ("yes", 1, None):
            code, out = self.check(lambda d, v=value: d.__setitem__("sample", v))
            self.assertEqual(code, 1, f"{value!r} should be rejected: {out}")

    def test_both_booleans_are_accepted(self):
        for value in (True, False):
            code, out = self.check(lambda d, v=value: d.__setitem__("sample", v))
            self.assertEqual(code, 0, f"{value!r} should be accepted: {out}")

    def first_round(self, d):
        return d["formats"][0]["rounds"][0]

    def test_a_round_covered_only_by_a_feature_match_is_accepted(self):
        # Five of the 2026 North America WCQ's rounds reached the archive as a
        # feature match and nothing else. That is thin coverage of a real round,
        # not an empty one.
        def only_feature(d):
            r = self.first_round(d)
            r["pairings"], r["standings"] = [], []
            r["feature"] = {"a": "Ann Alpha", "b": "Bo Beta", "url": "https://x/f/"}
        self.assertEqual(self.check(only_feature)[0], 0)

    def test_a_round_carrying_nothing_at_all_is_still_rejected(self):
        def empty(d):
            r = self.first_round(d)
            r["pairings"], r["standings"], r["feature"] = [], [], None
        code, out = self.check(empty)
        self.assertEqual(code, 1)
        self.assertIn("feature match", out)

    def cut(self, d):
        """The event's cut rounds that published pairings."""
        return [r for r in d["formats"][0]["rounds"]
                if r.get("phase") == "Top cut" and r.get("pairings")]

    def test_a_gap_in_the_published_cut_is_accepted(self):
        # The South America WCQ 2015 published a Top 64, a Top 32 and a Top 8,
        # and never a Top 16. Reading the two rounds either side of that gap as
        # consecutive -- "8 Duelists from 32, expected half" -- rejected the
        # whole event over a round Konami did not post.
        def drop_the_middle(d):
            rounds, cut = d["formats"][0]["rounds"], self.cut(d)
            if len(cut) < 3:
                self.skipTest("the subject has no cut round to drop")
            gone = cut[1]
            rounds.remove(gone)
            # And the records lose the win that round was the evidence for. A
            # derived cut record counts the rounds the blog posted, so this is
            # what the builder itself produces when a round is not published --
            # not a doctored file, but the shape of gapped coverage.
            for r in cut[2:]:
                for p in r["pairings"]:
                    for k in ("aRec", "bRec"):
                        if isinstance(p.get(k), dict) and p[k].get("wins"):
                            p[k]["wins"] -= 1
        code, out = self.check(drop_the_middle)
        self.assertEqual(code, 0, out)

    def test_a_cut_round_holding_the_wrong_number_of_duelists_is_rejected(self):
        # What the gap rule used to catch, kept: a table read into the wrong
        # round. Measured against the round's own name rather than against the
        # round before it, so it holds across a gap too.
        def merge_two(d):
            first = self.cut(d)[0]
            if len(first["pairings"]) < 2:
                self.skipTest("the subject's first cut round has one match")
            # One Duelist seated where another belongs: the matches still
            # divide evenly and everyone here did play the round before, so
            # only the count gives it away.
            first["pairings"][1]["a"] = first["pairings"][0]["a"]
        code, out = self.check(merge_two)
        self.assertEqual(code, 1)
        self.assertIn("its name calls for", out)

    def test_a_derived_record_for_a_duelist_seated_twice_is_rejected(self):
        # The defect this guards: two people sharing a name merge, and the
        # merged appearances make both their records wrong.
        def twice(d):
            r = self.first_round(d)
            rec = {"wins": 1, "losses": 0, "draws": 0, "confidence": "derived"}
            r["pairings"] = [{"table": 1, "a": "Ann Alpha", "aRec": rec, "aDeck": None,
                              "b": "Bo Beta", "bRec": rec, "bDeck": None},
                             {"table": 2, "a": "Ann Alpha", "aRec": rec, "aDeck": None,
                              "b": "Cy Gamma", "bRec": rec, "bDeck": None}]
        code, out = self.check(twice)
        self.assertEqual(code, 1)
        self.assertIn("Ann Alpha", out)

    def test_a_duelist_seated_twice_with_nothing_derived_is_accepted(self):
        # Columbus round 2 seats "Colton Randolph Crane" at two tables with no
        # region on either row. The build gives up on the name rather than
        # guessing, and reporting that honestly is not a defect to fail on.
        def twice_unknown(d):
            r = self.first_round(d)
            rec = {"wins": None, "losses": None, "draws": None, "confidence": "unknown"}
            r["pairings"] = [{"table": 1, "a": "Colton Randolph Crane", "aRec": rec,
                              "aDeck": None, "b": "Bo Beta", "bRec": rec, "bDeck": None},
                             {"table": 2, "a": "Colton Randolph Crane", "aRec": rec,
                              "aDeck": None, "b": "Cy Gamma", "bRec": rec, "bDeck": None}]
        code, out = self.check(twice_unknown)
        self.assertEqual(code, 0, out)

    def test_a_cut_round_with_only_a_feature_match_is_accepted(self):
        # A bracket halves, so a Top 8 of three matches is a parse that lost a
        # row. No matches at all is different: the blog published a feature
        # match from that round and nothing else. This rule had not been given
        # the same reading as the one above it, and rejected a backfill batch of
        # eleven events over one Top 8 nobody published pairings for.
        def feature_only(d):
            fmt = d["formats"][0]
            cut = [r for r in fmt["rounds"] if r["phase"] == "Top cut"]
            # The last one, which nothing advances out of. Konami covered YCS
            # Montreal's bracket as far as the Top 4 and stopped, so this is the
            # round most often reached by a feature match and nothing else.
            cut[-1]["pairings"] = []
            cut[-1]["feature"] = {"a": {"name": "Ann Alpha"}, "b": {"name": "Bo Beta"},
                                  "source": "https://x/f/"}
        code, out = self.check(feature_only)
        self.assertEqual(code, 0, out)

    def test_a_record_is_measured_against_the_cut_rounds_published(self):
        # A bracket win is counted by seeing the Duelist paired in the round
        # after it, so a cut round nobody posted pairings for adds nothing to
        # anyone's record. Expecting it back rejected YCS Philadelphia over 35
        # Duelists whose Top 64 match was never published.
        def unpublished_first_cut(d):
            fmt = d["formats"][0]
            cut = [r for r in fmt["rounds"] if r["phase"] == "Top cut"]
            first = dict(cut[0])
            first.update(id="T64", label="Top 64", pairings=[], standings=[],
                         order=cut[0]["order"] - 1,
                         feature={"a": {"name": "Ann Alpha"}, "b": {"name": "Bo Beta"},
                                  "source": "https://x/f/"})
            fmt["rounds"].insert(fmt["rounds"].index(cut[0]), first)
        code, out = self.check(unpublished_first_cut)
        self.assertEqual(code, 0, out)

    def test_a_record_that_does_not_add_up_to_its_points_is_rejected(self):
        # The rule two rebuilds were stopped by, and which nothing else here
        # would catch: a record can account for the right number of matches and
        # still describe a different tournament than the row it sits in.
        def wrong_by_a_win(d):
            self.derived_rows(d)[0]["record"]["wins"] += 1
        code, out = self.check(wrong_by_a_win, needs=self.derived_rows)
        self.assertEqual(code, 1)
        self.assertIn("which is not what that adds up to", out)

    def test_a_row_claiming_no_record_is_not_asked_to_add_up(self):
        # Most rows are this: the points are published and the record is not.
        def claim_nothing(d):
            for fmt in d["formats"]:
                for r in fmt["rounds"]:
                    for st in r.get("standings") or []:
                        st["record"] = {"wins": None, "losses": None,
                                        "draws": None, "confidence": "unknown"}
        code, out = self.check(claim_nothing)
        self.assertEqual(code, 0, out)

    def test_a_draw_counts_towards_the_points(self):
        # 3*wins + draws, not 3*wins: a record with draws in it must not be
        # rejected for the points those draws account for.
        def one_draw(d):
            # A win becomes a draw: two points fewer, and the same number of
            # matches, so this tests the arithmetic and not the round count.
            st = self.derived_rows(d)[0]
            st["record"]["wins"] -= 1
            st["record"]["draws"] = (st["record"].get("draws") or 0) + 1
            st["points"] -= 2
        code, out = self.check(one_draw, needs=self.derived_rows)
        self.assertEqual(code, 0, out)

    def test_a_record_short_of_the_rounds_that_were_published_is_rejected(self):
        # The rule keeps its whole force where the coverage is complete.
        def deep_cut_record(event):
            """A cut round, after the first, whose seats carry a record."""
            cut = [r for r in event["formats"][0]["rounds"] if r["phase"] == "Top cut"]
            return [r for r in cut[1:] if r.get("pairings")
                    and isinstance(r["pairings"][0].get("aRec"), dict)
                    and r["pairings"][0]["aRec"].get("wins") is not None]

        def one_short(d):
            deep_cut_record(d)[0]["pairings"][0]["aRec"]["wins"] -= 1
        code, out = self.check(one_short, needs=deep_cut_record)
        self.assertEqual(code, 1)
        self.assertIn("matches), expected", out)

    def test_a_cut_round_missing_a_match_is_still_rejected(self):
        def three(d):
            fmt = d["formats"][0]
            cut = [r for r in fmt["rounds"] if r["phase"] == "Top cut"]
            cut[0]["pairings"] = (cut[0]["pairings"] or [])[:3]
        code, out = self.check(three)
        self.assertEqual(code, 1)
        self.assertIn("does not divide 8 into equal sides", out)

    def test_a_duelist_paired_against_themselves_is_always_rejected(self):
        def mirror(d):
            self.first_round(d)["pairings"] = [
                {"table": 1, "a": "Ann Alpha", "aRec": None, "aDeck": None,
                 "b": "Ann Alpha", "bRec": None, "bDeck": None}]
        self.assertEqual(self.check(mirror)[0], 1)


class TestFeedIdentity(unittest.TestCase):
    """Each item has to say which tournament it belongs to, and which format."""

    def test_a_title_already_in_the_convention_is_left_alone(self):
        from feed import titled
        self.assertEqual(titled("YCS Montréal", "YCS Montréal: Round 3 Pairings"),
                         "YCS Montréal: Round 3 Pairings")

    def test_a_title_naming_the_event_without_a_colon_gains_one(self):
        from feed import titled
        # "YCS Montreal Advanced Format Top 32 Deck Lists" has no separator, so
        # the site grouped it under its category and invented a "Deck profile"
        # event. Repeating the name instead would read worse than fixing it.
        self.assertEqual(
            titled("YCS Montréal", "YCS Montréal Advanced Format Top 32 Deck Lists"),
            "YCS Montréal: Advanced Format Top 32 Deck Lists")

    def test_a_title_that_does_not_name_the_event_is_prefixed(self):
        from feed import titled
        got = titled("YCS Montréal", "Genesys Format Round 4 Feature Match: A vs. B")
        self.assertEqual(got, "YCS Montréal: Genesys Format Round 4 Feature Match: A vs. B")
        # The site splits on the first colon, so the inner one survives.
        self.assertEqual(got.split(":", 1)[0], "YCS Montréal")

    def test_a_title_that_is_only_the_event_name_gains_nothing(self):
        from feed import titled
        self.assertEqual(titled("YCS Montréal", "YCS Montréal"), "YCS Montréal")

    def test_the_format_rides_on_its_own_category(self):
        import xml.etree.ElementTree as ET
        from feed import build_feed
        xml = build_feed("YCS Montréal", [
            {"title": "Round 1 Pairings", "url": "https://yugiohblog.konami.com/a/",
             "modified": "2026-08-16T11:00:00-07:00", "kind": "pairings",
             "format": "Advanced"}])
        item = ET.fromstring(xml).find("channel/item")
        self.assertEqual(item.find('category[@domain="format"]').text, "Advanced")
        # The kind stays the plain category the site already reads.
        self.assertEqual(item.find("category").text, "Pairings")

    def test_a_post_belonging_to_no_format_says_nothing(self):
        import xml.etree.ElementTree as ET
        from feed import build_feed
        xml = build_feed("YCS Montréal", [
            {"title": "Doors open at 9am", "url": "https://yugiohblog.konami.com/c/",
             "modified": "2026-08-16T09:00:00-07:00", "kind": "news", "format": None}])
        item = ET.fromstring(xml).find("channel/item")
        self.assertIsNone(item.find('category[@domain="format"]'),
                          "an announcement is about the event, not a tournament")


class TestFetchBudget(unittest.TestCase):
    """Which of an event's posts get fetched when not all of them can."""

    def posts(self, **counts):
        out = []
        for kind, n in counts.items():
            out += [{"kind": kind, "slug": f"{kind}-{i}",
                     "lastmod": f"2026-08-16T{i:02d}:00:00+00:00"} for i in range(n)]
        return out

    def taken(self, posts, limit):
        from collections import Counter
        from run import select_posts
        return Counter(p["kind"] for p in select_posts(list(posts), limit))

    def test_pairings_and_standings_are_never_rationed(self):
        # A record is wrong without every round's pairings, so these come whole
        # even when the budget is tight.
        got = self.taken(self.posts(pairings=30, standings=23, feature=37, news=39), 60)
        self.assertEqual(got["pairings"], 30)
        self.assertEqual(got["standings"], 23)

    def test_no_kind_is_starved_to_nothing(self):
        # The failure this replaces: 30 pairings and 23 standings filled 53 of 60
        # slots, so 5 of 37 features were fetched and all five were one format.
        got = self.taken(self.posts(pairings=30, standings=23, feature=37,
                                    news=39, result=12, deck=2), 60)
        for kind in ("feature", "news", "result", "deck"):
            self.assertGreater(got[kind], 0, f"{kind} was starved: {dict(got)}")

    def test_a_whole_event_fits_in_the_default_budget(self):
        # An event runs to about 140 posts and its table of contents caps under
        # 200, so nothing is rationed in practice.
        posts = self.posts(pairings=30, standings=23, feature=37, news=39,
                           result=12, deck=2)
        got = self.taken(posts, 200)
        self.assertEqual(sum(got.values()), len(posts))

    def test_the_limit_is_honoured(self):
        posts = self.posts(pairings=5, standings=5, feature=50, news=50)
        self.assertEqual(sum(self.taken(posts, 20).values()), 20)

    def test_a_tight_budget_still_takes_every_pairing(self):
        # Even past the limit: a partial pairings set produces wrong records,
        # which is worse than one more request.
        got = self.taken(self.posts(pairings=40, standings=10), 20)
        self.assertEqual(got["pairings"], 20, "truncation must not drop a round silently")

    def test_the_default_budget_covers_a_whole_event(self):
        import re, run
        # The default is what starved feature matches: at 60, pairings and
        # standings alone took 53 of the slots. An event runs to about 140 posts
        # and its own table of contents caps under 200. Read from the source
        # because the parser is built inside main() and never handed out.
        src = Path(run.__file__).read_text()
        m = re.search(r'--limit", type=int, default=(\d+)', src)
        self.assertIsNotNone(m, "the --limit argument moved or was renamed")
        self.assertGreaterEqual(int(m.group(1)), 150,
                                "too low to hold one event, which is how this broke")

    def test_a_feature_match_outranks_a_news_post_for_the_last_slot(self):
        # Both are rationed, but a feature attaches to a round on the page while
        # a news post only ever appears in the feed.
        got = self.taken(self.posts(pairings=3, standings=2, feature=5, news=5), 6)
        self.assertEqual(got["feature"], 1)
        self.assertEqual(got["news"], 0)

    def test_newest_first_within_a_kind(self):
        from run import select_posts
        posts = self.posts(feature=5)
        order = [p["slug"] for p in select_posts(posts, 3)]
        self.assertEqual(order, ["feature-4", "feature-3", "feature-2"],
                         "the newest coverage is the coverage worth having")


class TestCadence(unittest.TestCase):
    """Which scheduled ticks reach the blog and which are dropped."""

    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

    def ago(self, **kw):
        from datetime import timedelta
        return self.now - timedelta(**kw)

    def test_a_live_event_checks_on_every_tick(self):
        from cadence import should_check
        self.assertEqual(should_check(self.now, self.ago(minutes=20), self.ago(minutes=10)),
                         (True, "live"))

    def test_a_quiet_stretch_checks_about_hourly(self):
        from cadence import should_check
        old = self.ago(days=30)
        self.assertEqual(should_check(self.now, old, self.ago(minutes=10))[0], False)
        self.assertEqual(should_check(self.now, old, self.ago(minutes=54))[0], False)
        self.assertEqual(should_check(self.now, old, self.ago(minutes=55))[0], True)

    def test_a_late_tick_still_counts_as_the_hourly_one(self):
        from cadence import should_check
        # GitHub runs scheduled jobs late under load. Keying off the wall-clock
        # minute would drop a tick that arrived at :12 instead of :03 and skip
        # the whole hour; elapsed time does not care when it arrived.
        self.assertEqual(should_check(self.now, self.ago(days=30), self.ago(minutes=70))[0],
                         True)

    def test_the_window_lapses_overnight_and_comes_back(self):
        from cadence import should_check
        # Last post at midnight, first check of the morning.
        self.assertEqual(should_check(self.now, self.ago(hours=5, minutes=59),
                                      self.ago(minutes=1))[0], True, "still live")
        self.assertEqual(should_check(self.now, self.ago(hours=6, minutes=1),
                                      self.ago(minutes=1))[0], False, "back to quiet")

    def test_missing_state_checks_rather_than_stalls(self):
        from cadence import should_check
        self.assertEqual(should_check(self.now, None, None), (True, "quiet"))
        self.assertEqual(should_check(self.now, None, self.ago(minutes=1))[0], False,
                         "no known change, so the quiet rate still applies")

    def test_a_timestamp_from_the_future_does_not_pin_it_live(self):
        from datetime import timedelta
        from cadence import should_check
        # A clock skew or a hand-edited cache must not leave the scraper polling
        # at the fast rate indefinitely.
        ahead = self.now + timedelta(hours=2)
        self.assertEqual(should_check(self.now, ahead, self.ago(minutes=1))[0], False)
        self.assertEqual(should_check(self.now, self.ago(days=30), ahead)[0], True,
                         "and an impossible last check is re-checked, not trusted")

    def test_an_unreadable_timestamp_is_treated_as_absent(self):
        from cadence import parse_time
        self.assertIsNone(parse_time("not a date"))
        self.assertIsNone(parse_time(""))
        self.assertIsNone(parse_time(None))

    def test_a_naive_timestamp_is_read_as_utc(self):
        from cadence import parse_time
        self.assertIsNotNone(parse_time("2026-08-29T14:00:00").tzinfo,
                             "comparing naive to aware raises, stopping the scraper")

    def test_a_first_sighting_is_not_a_change(self):
        from cadence import record, decide
        # An empty cache means we have never looked, not that something was just
        # posted. Treating it as a change would run the fast cadence for the
        # whole live window every time the cache is rebuilt.
        first = record({}, self.now, "2026-08-29")
        self.assertNotIn("last_change", first)
        self.assertEqual(first["high_water"], "2026-08-29")
        self.assertEqual(decide(first, self.now), (False, "quiet"),
                         "and the next tick is quiet, not live")

    def test_the_change_time_only_moves_when_the_mark_does(self):
        from cadence import record
        from datetime import timedelta
        seen = record({}, self.now - timedelta(hours=2), "2026-08-29")
        first = record(seen, self.now, "2026-08-30")
        self.assertEqual(first["last_change"], self.now.isoformat())

        later = self.now + timedelta(minutes=10)
        same = record(first, later, "2026-08-30")
        self.assertEqual(same["last_change"], first["last_change"],
                         "checking is not evidence the event is still running")
        self.assertEqual(same["last_check"], later.isoformat())

        moved = record(same, later, "2026-08-31")
        self.assertEqual(moved["last_change"], later.isoformat())

    def test_a_weekend_of_coverage_polls_fast_then_stands_down(self):
        from datetime import datetime, timedelta, timezone
        from cadence import decide, record

        # A ten-minute cron across two days. Coverage lands every 47 minutes for
        # eight hours of the Saturday, then nothing at all.
        #
        # The posts are deliberately off the tick grid -- 15:07, 15:54, 16:41 --
        # so the measured lag is real. Landing them on the ten-minute boundaries
        # reports a lag of zero however badly the gate behaves.
        TICKS = 6 * 24 * 2
        start = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        posts = [start + timedelta(hours=3, minutes=7 + 47 * i) for i in range(10)]

        # The blog is not new: it carries coverage of earlier events, so the
        # first check records a real high-water mark rather than nothing. That
        # matters -- a first sighting is deliberately not treated as a change.
        state, checks, live_checks, mark = {}, 0, 0, "2026-08-01"
        seen, lag, entry = set(), {}, None
        for tick in range(TICKS):
            now = start + timedelta(minutes=10 * tick)
            go, cadence = decide(state, now)
            if not go:
                continue
            checks += 1
            live_checks += cadence == "live"
            due = [p for p in posts if p <= now]
            # A check covers everything published since the last one, not just
            # the newest -- the high-water mark moves and the scrape refetches
            # the event -- so every post now due counts as found.
            for post in due:
                if post not in seen:
                    seen.add(post)
                    lag[post] = (now - post).total_seconds() / 60
                    entry = entry if entry is not None else now
            mark = due[-1].isoformat() if due else mark
            state = record(state, now, mark)

        self.assertEqual(len(seen), len(posts), "every post is eventually found")
        self.assertLess(checks, TICKS // 2, "most ticks are dropped")

        # The event starts while the cadence is still quiet, so whatever has been
        # posted by the first hourly check arrives in one batch and waits up to
        # an hour. That is the cost of not keeping a calendar; it is paid once.
        opening = [p for p in posts if p <= entry]
        self.assertLessEqual(max(lag[p] for p in opening), 60)

        # Every post after that is found within a single tick, which is the point.
        rest = [p for p in posts if p > entry]
        self.assertGreaterEqual(len(rest), 7, "otherwise this proves little")
        self.assertLessEqual(max(lag[p] for p in rest), 10,
                             "once live, no post waits longer than one tick")
        self.assertGreater(live_checks, 40, "the event window is polled fast")
        self.assertLess(checks - live_checks, 40, "and the quiet day is hourly-ish")


class TestPostedTime(unittest.TestCase):
    def test_a_round_reports_the_clock_not_the_stamp(self):
        from build import build_format, Source
        from parse import Post, Table
        rows = [{"table": 1, "a": {"name": "Ada", "region": None, "deck": None},
                 "b": {"name": "Bo", "region": None, "deck": None}}]
        src = Source(url="https://x/", posted="2026-08-16T11:07:30-07:00",
                     post=Post(title="Round 1 Pairings", kind="pairings",
                               fmt="Advanced", round=1,
                               table=Table("pairings", [], rows)))
        fmt = build_format("Advanced", [src])
        self.assertEqual(fmt["rounds"][0]["posted"], "11:07",
                         "the page renders this straight into 'pairings posted ...'")


class TestCutOrdering(unittest.TestCase):
    def test_stages_sort_into_bracket_order(self):
        from build import cut_rank
        labels = ["Final", "Top 4", "Top 8", "Top 16", "Top 32", "Top 64"]
        self.assertEqual(sorted(labels, key=cut_rank),
                         ["Top 64", "Top 32", "Top 16", "Top 8", "Top 4", "Final"])

    def test_the_Final_sorts_last_despite_having_no_number(self):
        from build import cut_rank
        self.assertGreater(cut_rank("Final"), cut_rank("Top 4"))
        self.assertGreater(cut_rank("Finals"), cut_rank("Top 64"))

    def test_stage_aliases_rank_identically(self):
        from build import cut_rank
        # One stage under two names must not sort into two places depending on
        # what the blog called it that day.
        self.assertEqual(cut_rank("Semifinals"), cut_rank("Top 4"))
        self.assertEqual(cut_rank("Quarterfinals"), cut_rank("Top 8"))


class TestBuild(unittest.TestCase):
    def setUp(self):
        from build import build_event
        self.ev = build_event("YCS Montréal", _sources(), updated="2026-08-16T19:10:00Z")
        self.adv = next(f for f in self.ev["formats"] if f["format"] == "Advanced")

    def test_posts_are_grouped_by_format(self):
        self.assertEqual(sorted(f["format"] for f in self.ev["formats"]), ["Advanced", "Genesys"])

    def test_a_post_naming_no_format_is_not_guessed_into_one(self):
        from build import build_event
        from parse import parse_post
        ev = build_event("x", _sources() + [
            __import__("build").Source("https://x/none/",
                                       parse_post("<title>Top 64 Pairings</title><table></table>"))])
        self.assertGreaterEqual(ev["_unassigned"], 1, "reported, not assigned")

    def test_swiss_rounds_are_ordered_and_counted(self):
        rounds = [r for r in self.adv["rounds"] if r["phase"] == "Swiss"]
        self.assertEqual([r["label"] for r in rounds][:3], ["R1", "R2", "R3"])
        self.assertEqual(self.adv["swissRounds"], 13)
        self.assertEqual([r["order"] for r in rounds], sorted(r["order"] for r in rounds))

    def test_final_swiss_standings_attach_to_the_last_round(self):
        # "Final Standings After Swiss" names no round, correctly. It must still
        # land somewhere rather than being dropped.
        last = [r for r in self.adv["rounds"] if r["phase"] == "Swiss"][-1]
        self.assertEqual(last["label"], "R13")
        self.assertEqual(len(last["standings"]), 766)
        self.assertEqual(last["standingsAfter"], 13)

    def test_records_are_derived_from_appearances(self):
        last = [r for r in self.adv["rounds"] if r["standings"]][-1]
        top = last["standings"][0]
        self.assertEqual(top["record"], {"wins": 12, "losses": 1, "draws": 0,
                                         "confidence": "derived"})
        self.assertEqual(top["points"], 36)
        confidences = {s["record"]["confidence"] for s in last["standings"]}
        self.assertTrue(confidences <= {"derived", "partial", "unknown"})
        # No derived record may imply negative losses.
        self.assertTrue(all(s["record"]["losses"] is None or s["record"]["losses"] >= 0
                            for s in last["standings"]))

    def test_a_finished_event_has_no_round_in_progress(self):
        # The default, and the important direction: "in progress" is a claim
        # about right now. YCS Montreal reached production reading
        # "Top 4 - IN PROGRESS" twelve days after it ended.
        self.assertEqual([r for r in self.adv["rounds"] if r["state"] == "live"], [])

    def test_the_newest_round_is_live_while_the_event_is(self):
        from build import build_event
        ev = build_event("YCS Montréal", _sources(), updated="2026-08-16T19:10:00Z",
                         ongoing=True)
        adv = next(f for f in ev["formats"] if f["format"] == "Advanced")
        live = [r for r in adv["rounds"] if r["state"] == "live"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["order"], max(r["order"] for r in adv["rounds"]))

    def test_every_round_carries_its_source_url(self):
        for r in self.adv["rounds"]:
            self.assertTrue(r["source"], f"{r['label']} has no source URL")

    def test_the_output_matches_the_shape_the_site_reads(self):
        for key in ("event", "coverageBy", "drawsPossible", "updated", "formats"):
            self.assertIn(key, self.ev)
        for key in ("format", "swissRounds", "duelists", "rounds"):
            self.assertIn(key, self.adv)
        for key in ("id", "label", "phase", "state", "order", "pairings", "standings"):
            self.assertIn(key, self.adv["rounds"][0])


class TestTLS(unittest.TestCase):
    def test_the_bundled_intermediate_is_present_and_not_expiring(self):
        import re as _re
        import datetime as _dt
        certs = list((Path(__file__).parent / "certs").glob("*.pem"))
        self.assertTrue(certs, "the server omits its intermediate; one must be bundled")
        for c in certs:
            text = c.read_text()
            self.assertIn("BEGIN CERTIFICATE", text, f"{c.name} holds no certificate")
            m = _re.search(r"# Expires: (\d{4}-\d{2}-\d{2})", text)
            self.assertTrue(m, f"{c.name} does not record its expiry")
            expires = _dt.date.fromisoformat(m.group(1))
            left = (expires - _dt.date.today()).days
            self.assertGreater(left, 90,
                f"{c.name} expires in {left} days; fetch the current intermediate "
                "from the leaf's AIA URL and replace it")

    def test_the_intermediate_is_the_certificate_we_expect(self):
        """Pin it by fingerprint.

        The file is loaded as a trust anchor, so substituting another
        certificate would change what the scraper accepts. Comparing the hash
        makes that fail here rather than depend on someone reading base64 in a
        diff. Computed from the DER, which is what a fingerprint is over.
        """
        import base64
        import hashlib
        import re as _re

        expected = {
            "geotrust-tls-rsa-ca-g1.pem":
                "c06e307f7cfc1d32fa72a4c033c87b90019af216f0775d64978a2eca6c8a230e",
        }
        certs = {c.name: c for c in (Path(__file__).parent / "certs").glob("*.pem")}
        self.assertEqual(set(certs), set(expected),
                         "an unpinned certificate was added to the trust bundle")

        for name, path in certs.items():
            body = _re.search(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
                              path.read_text(), _re.S)
            self.assertTrue(body, f"{name} holds no certificate")
            der = base64.b64decode("".join(body.group(1).split()))
            got = hashlib.sha256(der).hexdigest()
            self.assertEqual(got, expected[name],
                             f"{name} is not the pinned certificate")
            # The header must state the same hash, so the file documents itself.
            self.assertIn(got, path.read_text().lower(),
                          f"{name} header does not record its own fingerprint")

    def test_verification_is_never_disabled(self):
        # A fallback that skips verification would be worse than the failure it
        # works around, so make that impossible to add quietly.
        src = (Path(__file__).parent / "fetch.py").read_text()
        for bad in ("_create_unverified_context", "CERT_NONE", "check_hostname = False",
                    "verify=False"):
            self.assertNotIn(bad, src, f"fetch.py must never {bad}")


class TestAnnotatedNames(unittest.TestCase):
    """Some standings tables put a player ID and status inside the name cell."""

    def test_ids_and_status_are_stripped(self):
        self.assertEqual(normalise_name("Adrien (0200512639) (PlayoffCut – Round 11) Racek"),
                         "Adrien Racek")
        self.assertEqual(normalise_name("Alex (0200539277) (Drop – Round 4) Zhou"),
                         "Alex Zhou")

    def test_an_annotated_name_matches_its_plain_form(self):
        # This is the whole point: a name that normalises two ways counts as two
        # people, and their appearances are never found.
        self.assertEqual(normalise_name("Adrien (0200512639) (Drop – Round 4) Racek"),
                         normalise_name("Adrien Racek"))
        self.assertEqual(normalise_name("Racek, Adrien (0200512639)"),
                         normalise_name("Adrien Racek"))

    def test_stripping_does_not_disturb_ordinary_names(self):
        for raw, want in [("George Lucas Sacco", "George Lucas Sacco"),
                          ("Aldrich III, Gordon Russell", "Gordon Russell Aldrich III"),
                          ("Joshua Aaron TX Jones", "Joshua Aaron Jones")]:
            self.assertEqual(normalise_name(raw), want)


class TestRunFetchesWhatItSelected(unittest.TestCase):
    """main() end to end against a fake blog, watching which URLs it requests.

    select_posts had every one of the tests above and none of them noticed that
    main() never called it: main kept its own sort-by-kind-and-truncate, so the
    budget rules were live in the test suite and dead in the scraper. A unit test
    of a function nothing calls proves nothing, so this one drives main() and
    reads the requests off the wire.
    """

    KINDS = {"pairings": "round-{i}-pairings-advanced-format",
             "standings": "round-{i}-standings-advanced-format",
             "deck": "deck-profile-{i}-advanced-format",
             "feature": "feature-match-round-{i}-advanced-format"}

    def blog(self, counts):
        """(transport, fetched-urls). One sub-sitemap of one event's posts."""
        urls = []
        for kind, n in counts.items():
            urls += [f"https://yugiohblog.konami.com/2026/ycs/fake-event/"
                     f"{self.KINDS[kind].format(i=i)}/" for i in range(n)]
        sitemap = ('<?xml version="1.0"?><urlset xmlns='
                   '"http://www.sitemaps.org/schemas/sitemap/0.9">'
                   + "".join(f"<url><loc>{u}</loc>"
                             f"<lastmod>2026-08-{14 + i % 3:02d}T{i % 24:02d}:00:00+00:00"
                             f"</lastmod></url>" for i, u in enumerate(urls))
                   + "</urlset>")
        sub = "https://yugiohblog.konami.com/wp-sitemap-posts-post-1.xml"
        index = ('<?xml version="1.0"?><sitemapindex xmlns='
                 '"http://www.sitemaps.org/schemas/sitemap/0.9">'
                 f"<sitemap><loc>{sub}</loc></sitemap></sitemapindex>")

        fetched = []

        def transport(url, ua):
            if url.endswith("wp-sitemap.xml"):
                return index
            if url == sub:
                return sitemap
            fetched.append(url)
            return f"<html><head><title>Fake Event {url.rstrip('/').rsplit('/', 1)[-1]}"
        return transport, fetched

    def run_main(self, counts, limit):
        import io, tempfile
        from collections import Counter
        from contextlib import redirect_stdout
        from unittest import mock
        import run
        transport, fetched = self.blog(counts)
        real = run.Fetcher
        with tempfile.TemporaryDirectory() as tmp:
            # Every output path inside the temp dir. Left to their defaults,
            # the archive and its manifest land in the repo.
            argv = ["run.py", "--cache", f"{tmp}/cache",
                    "--archive", f"{tmp}/events", "--manifest", f"{tmp}/events.json",
                    "--limit", str(limit)]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(run, "Fetcher",
                                   lambda **kw: real(**kw, delay=0, transport=transport)), \
                 redirect_stdout(io.StringIO()):
                run.main()
        marks = {"pairings": "-pairings-", "standings": "-standings-",
                 "deck": "deck-profile-", "feature": "feature-match-"}
        return Counter(k for u in fetched for k, mark in marks.items() if mark in u)

    def test_the_budget_rules_are_the_ones_the_scraper_uses(self):
        # Chosen so the two algorithms disagree. Under the old strict ranking a
        # deck profile outranked a feature match, so the last slot went to the
        # deck; select_posts rotates with features first because a feature
        # attaches to a round on the page and a deck profile does not.
        got = self.run_main({"pairings": 3, "standings": 2, "deck": 2, "feature": 2}, 6)
        self.assertEqual(got["pairings"], 3)
        self.assertEqual(got["standings"], 2)
        self.assertEqual((got["feature"], got["deck"]), (1, 0),
                         f"main() is not using select_posts: {dict(got)}")

    def test_a_whole_event_is_fetched_at_the_default_limit(self):
        counts = {"pairings": 13, "standings": 13, "deck": 2, "feature": 12}
        got = self.run_main(counts, 200)
        self.assertEqual(dict(got), counts)


def urlset(*urls):
    """A sitemap of (path, lastmod) pairs, rooted at the blog."""
    return ('<?xml version="1.0"?><urlset xmlns='
            '"http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>https://yugiohblog.konami.com/{path}/</loc>"
                      f"<lastmod>{when}T10:00:00+00:00</lastmod></url>"
                      for path, when in urls)
            + "</urlset>")


class TestEventWindows(unittest.TestCase):
    """Windows built from lastmod, which is a modification date and lies."""

    def test_one_re_edited_post_does_not_stretch_the_window(self):
        from index import tight_window
        # The real shape: 2014-north-american-wcq ran over two weeks in July
        # 2014 and one of its posts was edited in 2025, so min()..max() gave it
        # an eleven-year window that swallowed every undated post in between.
        self.assertEqual(
            tight_window(["2014-07-11", "2014-07-12", "2014-07-13", "2025-07-08"]),
            ("2014-07-11", "2014-07-13"))

    def test_a_genuinely_long_event_stays_whole(self):
        from index import tight_window
        # 2025-ycs-vancouver really does publish over four weeks. The threshold
        # has to clear real coverage as well as catch strays.
        self.assertEqual(
            tight_window(["2025-08-14", "2025-08-25", "2025-09-04", "2025-09-11"]),
            ("2025-08-14", "2025-09-11"))

    def test_the_bigger_cluster_wins_on_post_count_not_span(self):
        from index import tight_window
        # Two posts spread over two days must not outvote five published on one.
        self.assertEqual(
            tight_window(["2020-01-01"] * 5 + ["2021-06-01", "2021-06-02"]),
            ("2020-01-01", "2020-01-01"))

    def test_a_tie_goes_to_the_earlier_cluster(self):
        from index import tight_window
        # An event happens once and strays are edits made afterwards, so later
        # is the suspicious direction.
        self.assertEqual(
            tight_window(["2020-01-01", "2020-01-02", "2022-03-01", "2022-03-02"]),
            ("2020-01-01", "2020-01-02"))

    def test_dragon_duel_is_a_topic_not_an_event(self):
        # Its posts cluster in 2013, 2015 and 2018 -- a side bracket run at many
        # events, not one tournament.
        entry = parse_post_sitemap(
            urlset(("2015/ycs/dragon-duel/some-write-up", "2015-06-20")))[0]
        self.assertIsNone(entry.event_slug)


def listing(*items):
    """The events page's markup for a few entries."""
    return "<ul>" + "".join(
        f'<li><h6><a href="{href}">'
        + "".join(f'<p class="small">{p}</p>' for p in paras)
        + "</a></h6></li>" for href, paras in items) + "</ul>"


class TestChampion(unittest.TestCase):
    """Who won, recognised among the Duelists who could have.

    No name is read out of the prose. The event knows who was in the deepest
    round of its cut, and the post is asked only which of them it means.
    """

    def post(self, title, text):
        return {"title": title, "text": text}

    def test_a_title_held_elsewhere_is_not_a_win_here(self):
        # YCS Guatemala City 2017 published its winner and, the same weekend,
        # "UDS Champions at YCS Guatemala" -- a photograph of Duelists holding
        # an Ultimate Duelist Series invitation, one of whom reached the Top
        # 4. Both posts say "Champions", so both were read as announcing this
        # event's winner; two posts claiming two different Duelists is a
        # disagreement, and the event was left with no champion at all.
        from winners import champion
        got = champion(
            ["Gerald Yagans South Chaves", "Alejandro Garcia Moreno"],
            [self.post("YCS Guatemala City: And the winner is…",
                       "Congratulations to Gerald South Chaves from Costa Rica "
                       "for becoming our newest YCS Champion!"),
             self.post("YCS Guatemala City: UDS Champions at YCS Guatemala",
                       "We have got two UDS Champions in attendance! Here are "
                       "Osmin Arteaga from El Salvador and Alejandro Garcia "
                       "from Mexico with their UDS title belts.")])
        self.assertEqual(got, "Gerald Yagans South Chaves")

    def test_a_greeting_is_not_an_announcement(self):
        # "Welcoming the National Champions of South America" greets Duelists
        # who won somewhere else. It is not this event's result.
        from winners import announces_a_winner
        self.assertFalse(announces_a_winner(
            "Welcoming the National Champions of South America", ""))
        self.assertFalse(announces_a_winner("Honoring Our Champions In Attendance!", ""))
        # And the real thing still reads as one.
        self.assertTrue(announces_a_winner(
            "Congratulations to the Winner of the 2023 North America "
            "World Championship Qualifier!", ""))
        self.assertTrue(announces_a_winner("..And the 2013 Yu-Gi-Oh! World Champions are…", ""))

    def test_a_team_is_named_by_its_duelists(self):
        # A team enters under a name it chose -- "Ares", "Legionnaire" -- and
        # one word is not a name ordinary prose can be searched for. The
        # coverage announces the win by naming the people instead:
        #
        #   "Pierre Burgals, Matthieu Bricard, and Kevin Rodrigues Goncalves
        #    are the TEAM YCS Las Vegas Champions!!"
        from winners import champion
        got = champion(
            ["Ares", "Neal 4 Papa"],
            [self.post("And the Winners Are…",
                       "We have three new YCS Champions! Pierre Burgals, "
                       "Matthieu Bricard, and Kevin Rodrigues Goncalves are "
                       "the TEAM YCS Las Vegas Champions!!")],
            rosters={"Ares": ["Kevin Rodrigues Goncalves", "Matthieu Nicolas Bricard",
                              "Pierre Burgals"],
                     "Neal 4 Papa": ["Cameron Taylor Neal", "Cristian Rafael Urena",
                                     "Antonio Papa"]})
        self.assertEqual(got, "Ares")

    def test_a_post_naming_both_teams_is_settled_by_the_crowning_sentence(self):
        # TEAM YCS Las Vegas 2024 names the winning team and, further down,
        # the runner-up. This used to be a disagreement and no champion, on
        # the grounds that guessing at the first name is what cost YCS
        # Guatemala City its champion.
        #
        # It is not a guess. The sentence doing the crowning names one team,
        # and the other is in a different sentence saying it finished second.
        from winners import champion
        got = champion(
            ["Supreme Pro", "The Jawhari Brothers"],
            [self.post("And the Winner is…",
                       "The Champions of TEAM YCS Las Vegas are Team The Jawhari "
                       "Brothers! That is Hisam Jawhari, Hani Jawhari, and "
                       "Christopher LeBlanc! Supreme Pro finished second.")],
            rosters={"The Jawhari Brothers": ["Hani Yasser Jawhari", "Hisam Yasser Jawhari"],
                     "Supreme Pro": ["Hansel Erik Aguero", "Pakawat Thomas Pamornsut"]})
        self.assertEqual(got, "The Jawhari Brothers")

    def test_winning_the_final_is_called_victory_against(self):
        # YCS Seattle crowns nobody in the form CROWNS reads -- "we finally
        # have a Champion!" is not "is your Champion" -- so the crowning
        # sentence is empty and both finalists are named. What separates them
        # is the sentence describing the final.
        from winners import champion
        got = champion(
            ["Alexis Roberto Rodriguez Jimenez", "Noah Reid Greene"],
            [self.post("YCS Seattle: Champion",
                       "Coming out ahead of 851 other Duelists, we finally have a "
                       "Champion! Alexis Rodriguez is taking home the title, the "
                       "trophy, and an Ultra Rare Number 93: Utopia Kaiser! He "
                       "piloted his Kaiju Zoodiac Deck to victory against Noah "
                       "Greene's Artifact Zoodiac Deck.")])
        self.assertEqual(got, "Alexis Roberto Rodriguez Jimenez")

    def test_the_loser_is_named_as_the_loser(self):
        # Two ways the blog says it, both of which put the winner first.
        from winners import champion
        for tail in ("In second place was Bo Beta.", "Runner-up: Bo Beta."):
            got = champion(
                ["Ann Alpha", "Bo Beta"],
                [self.post("And the winner is…",
                           f"Our new Champion is Ann Alpha of Chile! {tail}")])
            self.assertEqual(got, "Ann Alpha", tail)

    def test_a_match_at_another_event_is_not_this_final(self):
        # YCS San Diego's winner post says the champion "had an epic Match
        # against his own brother at YCS Dallas, but his brother took the
        # title that time". A bare "against" sits exactly where this rule
        # looks and is about a different tournament a year earlier, so it is
        # not a marker. Here it would hand the title to the wrong Duelist.
        from winners import champion
        got = champion(
            ["Ann Alpha", "Bo Beta"],
            [self.post("And the winner is…",
                       "Bo Beta had an epic Match against Ann Alpha at YCS Dallas "
                       "last year. This year the trophy went elsewhere.")])
        self.assertIsNone(got)

    def test_the_crowning_sentence_is_read_not_the_first_name(self):
        # The guard the test above used to provide, kept: a post that names
        # the runner-up first must not hand it the title. Here "Bo Beta" is
        # named before "Ann Alpha" and the crowning sentence names Ann.
        from winners import champion
        got = champion(
            ["Ann Alpha", "Bo Beta"],
            [self.post("And the winner is…",
                       "Bo Beta came into the Finals unbeaten. It was not to be: "
                       "Ann Alpha is your newest YCS Champion!")])
        self.assertEqual(got, "Ann Alpha")

    def test_both_in_the_crowning_sentence_is_still_no_champion(self):
        # "X over Y to become Champion" puts both in that one sentence and
        # says nothing this rule can read. A guess is worse than no champion.
        from winners import champion
        got = champion(
            ["Ann Alpha", "Bo Beta"],
            [self.post("And the winner is…",
                       "What a Match. Ann Alpha and Bo Beta are your YCS "
                       "Champions and runner-up.")])
        self.assertIsNone(got)

    def test_a_singles_event_is_unchanged_by_rosters(self):
        # No rosters, so the question asked is exactly the one asked before.
        from winners import champion
        got = champion(["Barrett Arthur Keys", "Someone Else Entirely"],
                       [self.post("And the Winner Is…",
                                  "Congratulations to Barrett Arthur Keys!")],
                       rosters={})
        self.assertEqual(got, "Barrett Arthur Keys")

    def test_the_one_duelist_the_post_names_is_the_champion(self):
        from winners import champion
        got = champion(["Barrett Arthur Keys", "Someone Else Entirely"],
                       [self.post("And the Winner Is…",
                                  "Congratulations to Barrett Arthur Keys the "
                                  "winner of YCS Bogota, Colombia!")])
        self.assertEqual(got, "Barrett Arthur Keys")

    def test_a_shorter_name_in_the_prose_still_matches_the_record(self):
        # The tables carry two surnames and the blog usually prints one.
        from winners import champion
        got = champion(["Francisco Andres Osorio Bobadilla", "Julien Leo Kehon"],
                       [self.post("And the Advanced Format Winner is…",
                                  "Francisco Osorio from Santiago, Chile used his "
                                  "Elfnote Deck to win the whole thing!")])
        self.assertEqual(got, "Francisco Andres Osorio Bobadilla")

    def test_the_one_who_did_the_defeating_won(self):
        # The 2013 North America WCQ, which broke two earlier rules. Both
        # Duelists are named and only the sentence says which way round it went.
        from winners import champion
        got = champion(["Patrick Hoban", "David Keener"],
                       [self.post("Congratulations to our North American Champion",
                                  "Patrick J. Hoban of Atlanta, GA playing his Dragon "
                                  "Ruler Deck, defeated David J. Keener III to become "
                                  "the 2013 North American Champion.")])
        self.assertEqual(got, "Patrick Hoban")

    def test_a_lone_forename_does_not_identify_anybody(self):
        # A rule matching on one word decided this event was won by a Duelist
        # called Patrick Le, on the strength of the word "Patrick".
        from winners import named_in
        self.assertEqual(named_in("Patrick Le", "Patrick J. Hoban defeated David Keener"), -1)
        self.assertGreaterEqual(named_in("Patrick Hoban", "Patrick J. Hoban defeated"), 0)

    def test_a_side_events_winner_is_not_the_events_champion(self):
        # Every YCS runs a dozen of these and each has a congratulatory post of
        # its own: 198 of the archive's 266 result posts are side events.
        from winners import champion
        got = champion(["Jose Lopez", "Someone Else Entirely"],
                       [self.post("YCS Anaheim: Saturday ATTACK OF THE GIANT CARD Winner!",
                                  "Congrats to our Saturday ATTACK OF THE GIANT CARD "
                                  "winner, Jose Lopez!")])
        self.assertIsNone(got)

    def test_a_side_event_named_only_in_the_body_is_still_a_side_event(self):
        # "And the Winner Is..." is used for the Dragon Duel playoff as readily
        # as for the event itself, and only the first line says which.
        from winners import champion
        got = champion(["Emmett Parker Smith", "Someone Else Entirely"],
                       [self.post("And the Winner Is…",
                                  "We have our winner of the Dragon Duel Championship "
                                  "playoff! Emmett Parker Smith used his Ryzeal deck…")])
        self.assertIsNone(got)

    def test_a_post_that_announces_nothing_is_not_read(self):
        from winners import champion
        got = champion(["Barrett Arthur Keys"],
                       [self.post("Top 4 Feature Match",
                                  "Barrett Arthur Keys sits down against…")])
        self.assertIsNone(got)

    def test_a_format_post_is_read_against_its_own_bracket(self):
        # A two-format event publishes two winner posts, and reading one against
        # the other's cut would hand a format the wrong champion.
        from winners import champion
        posts = [self.post("And the Advanced Format Winner Is…",
                           "Jesse Dean Kotton takes it with Ryzeal!"),
                 self.post("And the Genesys Format Winner Is…",
                           "Xiaoyi Stanley Huang wins the Genesys side.")]
        self.assertEqual(champion(["Jesse Dean Kotton"], posts, "Advanced"),
                         "Jesse Dean Kotton")
        self.assertEqual(champion(["Xiaoyi Stanley Huang"], posts, "Genesys"),
                         "Xiaoyi Stanley Huang")

    def test_a_post_naming_no_format_is_read_by_whoever_asks(self):
        # Most events have one tournament and title their post accordingly.
        from winners import champion
        posts = [self.post("We have a winner!", "Rafael Mariano Reich took it.")]
        self.assertEqual(champion(["Rafael Mariano Reich"], posts, "Advanced"),
                         "Rafael Mariano Reich")

    def test_two_posts_naming_two_winners_claim_neither(self):
        # A disagreement is not a result.
        from winners import champion
        got = champion(["Ann Alpha Smith", "Bo Beta Jones"],
                       [self.post("And the Winner Is…", "Ann Alpha Smith won!"),
                        self.post("We have a winner!", "Bo Beta Jones won!")])
        self.assertIsNone(got)

    def test_an_event_whose_winner_was_never_posted_claims_nobody(self):
        # The common answer, and a real one: no champion rather than a guess.
        from winners import champion
        self.assertIsNone(champion(["Ann Alpha Smith", "Bo Beta Jones"], []))

    def test_nobody_on_record_means_nobody_claimed(self):
        from winners import champion
        self.assertIsNone(champion([], [self.post("And the Winner Is…", "Ann Alpha Smith!")]))

    def test_a_one_word_name_is_not_enough_to_recognise(self):
        # Team events enter under names like "Legionnaire", and one word is not
        # identification: it may be an ordinary word of the prose. A team event
        # has no champion here rather than possibly the wrong one.
        from winners import named_in
        self.assertEqual(named_in("Legionnaire", "Legionnaire won the whole thing"), -1)

    def test_two_named_and_nothing_saying_which_claims_neither(self):
        # A post that names both finalists without saying who beat whom has not
        # answered the question. Taking whichever is mentioned first would have
        # given the 2013 North America WCQ to the runner-up.
        from winners import champion
        got = champion(["Ann Alpha Smith", "Bo Beta Jones"],
                       [self.post("And the Winner Is…",
                                  "What a final between Ann Alpha Smith and "
                                  "Bo Beta Jones! What a weekend!")])
        self.assertIsNone(got)

    def test_one_formats_post_cannot_crown_the_others_champion(self):
        # Both tournaments of a two-format event have their own cut and their
        # own winner post. Read against each other they produce two claims for
        # one bracket, and two claims are no claim.
        from winners import champion
        posts = [self.post("And the Advanced Format Winner Is…", "Jesse Dean Kotton takes it!"),
                 self.post("And the Genesys Format Winner Is…", "Sam Epsilon Doe takes it!")]
        self.assertEqual(champion(["Jesse Dean Kotton", "Sam Epsilon Doe"], posts, "Advanced"),
                         "Jesse Dean Kotton")
        self.assertEqual(champion(["Jesse Dean Kotton", "Sam Epsilon Doe"], posts, "Genesys"),
                         "Sam Epsilon Doe")

    def test_a_name_nobody_recorded_is_not_promoted_to_champion(self):
        # The post names a Duelist the cut does not have -- a side event's
        # winner, or another event's post filed here. Recognition, not
        # extraction: if it is not one of the candidates it is not an answer.
        from winners import champion
        got = champion(["Ann Alpha Smith", "Bo Beta Jones"],
                       [self.post("And the Winner Is…",
                                  "Congratulations to Carla Gamma Brown!")])
        self.assertIsNone(got)


class TestRecordsKnowWhenTiesWereStillPolicy(unittest.TestCase):
    """The date reaches the derivation, and the standings series with it.

    Neither did before. `derive` took an event_date and a standings_series and
    build.py passed neither, so every event was derived as though ties had never
    existed -- which left 34,030 records claiming a whole number of wins their
    own published points contradict, and left the one function that can resolve
    a draw uncalled.
    """

    def event(self, *, on, standings):
        """One format, `standings` being {round: [(name, points), ...]}."""
        from build import build_format, Source
        from parse import Post, Table
        srcs = []
        names = sorted({n for rows in standings.values() for n, _ in rows})
        # Two distinct Duelists a table, always: one name on both sides is a
        # collision, and the disambiguator rightly refuses to derive for it.
        names = names if len(names) > 1 else names + ["Padding Opponent"]
        for rnd, rows in sorted(standings.items()):
            srcs.append(Source(f"https://x/r{rnd}-pairings/", Post(
                title=f"Round {rnd} Pairings", kind="pairings", fmt=None, round=rnd,
                table=Table(kind="pairings", columns=["table", "a", "b"],
                            rows=[{"table": 1, "a": {"name": names[0]},
                                   "b": {"name": names[1]}}])), "10:00"))
            srcs.append(Source(f"https://x/r{rnd}-standings/", Post(
                title=f"Standings After Round {rnd}", kind="standings", fmt=None, round=rnd,
                table=Table(kind="standings", columns=["rank", "name", "points"],
                            rows=[{"rank": i + 1, "name": n, "points": p}
                                  for i, (n, p) in enumerate(rows)])), "11:00"))
        return build_format(None, srcs, event_date=on)

    def last_standings(self, fmt):
        return [r for r in fmt["rounds"] if r["standings"]][-1]["standings"]

    def test_a_draw_is_counted_where_the_series_shows_one(self):
        # 4 points after two rounds is one win and one draw, and nothing but the
        # round-on-round reading can say so.
        fmt = self.event(on="2023-05-28", standings={
            2: [("Ada Lovelace", 4), ("Bo Peep", 3)],
            3: [("Ada Lovelace", 7), ("Bo Peep", 3)],
        })
        ada = next(r for r in self.last_standings(fmt) if r["name"] == "Ada Lovelace")
        self.assertEqual(ada["record"],
                         {"wins": 2, "losses": 0, "draws": 1, "confidence": "derived"})

    def test_two_duelists_of_one_name_get_no_record_either_way(self):
        # YCS Hartford ranked two Jimmy Nguyens in every table -- 3 points and
        # 0 after round one -- and nothing can say which row is which person.
        # Records are read back by name, so one of them answered for both and
        # the other's row came out saying "3 points, 0 wins".
        from records import derive
        got = derive([{"name": "Jimmy Nguyen", "points": 3},
                      {"name": "Jimmy Nguyen", "points": 0},
                      {"name": "Someone Else", "points": 3}],
                     [[_pairing("Jimmy Nguyen", "Someone Else")]],
                     event_date="2026-05-01")
        by = {(r.name, r.points): r for r in got}
        self.assertEqual(by[("Jimmy Nguyen", 3)].confidence, "unknown")
        self.assertEqual(by[("Jimmy Nguyen", 0)].confidence, "unknown")
        self.assertIsNone(by[("Jimmy Nguyen", 3)].wins)
        self.assertEqual(by[("Someone Else", 3)].confidence, "derived",
                         "and everybody else is unaffected")

    def test_a_record_that_does_not_add_up_to_its_row_is_not_claimed(self):
        # The series and the table are two different documents. A cut round is
        # handed the final standings rather than the table the series ends on,
        # and at the 250th YCS those disagree by a win: the series read a
        # Duelist 10-2-0 off a table saying 30 points, and the row it landed in
        # said 27. Forty-one rows came out reading "27 points, 10 wins".
        from records import derive
        series = [[{"name": "Ada Lovelace", "points": 6}],
                  [{"name": "Ada Lovelace", "points": 9}]]
        # The series says 3-0-0. The row says 6 points, which is two wins.
        got = derive([{"name": "Ada Lovelace", "points": 6}], [],
                     event_date="2023-05-28", standings_series=series, series_from=2)[0]
        self.assertEqual(got.confidence, "unknown")
        self.assertIsNone(got.wins)

    def test_a_record_that_does_add_up_is_kept(self):
        from records import derive
        series = [[{"name": "Ada Lovelace", "points": 6}],
                  [{"name": "Ada Lovelace", "points": 9}]]
        got = derive([{"name": "Ada Lovelace", "points": 9}], [],
                     event_date="2023-05-28", standings_series=series, series_from=2)[0]
        self.assertEqual((got.wins, got.draws, got.losses), (3, 0, 0))
        self.assertEqual(got.confidence, "derived")

    def test_no_record_contradicts_its_own_points(self):
        # The whole complaint: 3*wins + draws has to come to the points.
        fmt = self.event(on="2023-05-28", standings={
            2: [("Ada Lovelace", 4), ("Bo Peep", 1)],
            3: [("Ada Lovelace", 5), ("Bo Peep", 4)],
        })
        for row in self.last_standings(fmt):
            rec = row["record"] or {}
            if rec.get("wins") is None:
                continue
            self.assertEqual(3 * rec["wins"] + (rec["draws"] or 0), row["points"], row)

    def test_without_a_series_a_draws_era_record_is_not_claimed(self):
        # Points alone cannot separate one win from three draws, so the points
        # are reported and the record is not.
        fmt = self.event(on="2023-05-28", standings={5: [("Ada Lovelace", 9)]})
        row = self.last_standings(fmt)[0]
        self.assertEqual((row["record"] or {}).get("confidence"), "unknown")
        self.assertEqual(row["points"], 9, "the points are still published")

    def test_points_that_are_not_a_whole_number_of_wins_claim_nothing(self):
        # After the ties were abolished every score should be a multiple of
        # three. One that is not means the points or the date is wrong, and no
        # record can add up to it -- which the deploy checks, so claiming one
        # would stop the scrape rather than publish the event without it.
        from records import derive
        got = derive([{"name": "Ada Lovelace", "points": 4}],
                     [[_pairing("Ada Lovelace", "Bo Peep")]],
                     event_date="2026-05-01")[0]
        self.assertEqual(got.confidence, "unknown")
        self.assertIsNone(got.wins)
        self.assertEqual(got.points, 4, "the points are still published")

    def test_after_ties_were_abolished_points_alone_are_enough(self):
        # Nothing is lost for the modern events: 3 points is one win, full stop.
        fmt = self.event(on="2026-05-28", standings={
            2: [("Ada Lovelace", 6)], 3: [("Ada Lovelace", 9)]})
        self.assertEqual((self.last_standings(fmt)[0]["record"] or {})["wins"], 3)


class TestTheEventDateComesFromTheEvent(unittest.TestCase):

    def test_a_draws_era_event_is_built_knowing_it(self):
        # build_format takes the date, but it is build_event that knows it --
        # off the day the coverage ends. Passing nothing meant every event was
        # built as though ties had never been policy.
        from build import build_event, Source
        from parse import Post, Table
        srcs = [
            Source("https://x/p1/", Post(title="Round 1 Pairings", kind="pairings",
                fmt=None, round=1, table=Table(kind="pairings", columns=["table", "a", "b"],
                    rows=[{"table": 1, "a": {"name": "Ada Lovelace"},
                           "b": {"name": "Bo Peep"}}])), "10:00"),
            Source("https://x/s5/", Post(title="Standings After Round 5", kind="standings",
                fmt=None, round=5, table=Table(kind="standings",
                    columns=["rank", "name", "points"],
                    rows=[{"rank": 1, "name": "Ada Lovelace", "points": 9},
                          {"rank": 2, "name": "Bo Peep", "points": 3}])), "11:00"),
        ]
        ev = build_event("Some Event", srcs, updated="2023-05-28T19:10:00Z")
        rows = [r for f in ev["formats"] for r in f["rounds"] if r["standings"]]
        row = rows[-1]["standings"][0]
        # Nine points over five rounds is three wins and two losses, or two
        # wins and three draws. The date is what says so.
        self.assertEqual((row["record"] or {}).get("confidence"), "unknown")
        self.assertEqual(row["points"], 9)


class TestStandingsRun(unittest.TestCase):
    """Which tables can be read as a series: consecutive ones, ending at the
    round being reported."""

    def fmt_with(self, points_by_round):
        """One Duelist, on the given points after each listed round."""
        from build import build_format, Source
        from parse import Post, Table
        srcs = []
        for rnd, pts in sorted(points_by_round.items()):
            srcs.append(Source(f"https://x/r{rnd}-pairings/", Post(
                title=f"Round {rnd} Pairings", kind="pairings", fmt=None, round=rnd,
                table=Table(kind="pairings", columns=["table", "a", "b"],
                            rows=[{"table": 1, "a": {"name": "Ada Lovelace"},
                                   "b": {"name": "Bo Peep"}}])), "10:00"))
            srcs.append(Source(f"https://x/r{rnd}-standings/", Post(
                title=f"Standings After Round {rnd}", kind="standings", fmt=None, round=rnd,
                table=Table(kind="standings", columns=["rank", "name", "points"],
                            rows=[{"rank": 1, "name": "Ada Lovelace", "points": pts},
                                  {"rank": 2, "name": "Bo Peep", "points": 0}])), "11:00"))
        return build_format(None, srcs, event_date="2023-05-28")

    def last(self, fmt):
        return [r for r in fmt["rounds"] if r["standings"]][-1]["standings"][0]

    def test_a_gap_stops_the_run_short(self):
        # Each round-on-round move is one match, so a missing round leaves a gap
        # nobody can attribute: the run can only reach back to round five, and
        # nine points over five rounds is three wins and two losses or three
        # draws and two wins. Unreadable, and said so.
        fmt = self.fmt_with({2: 3, 3: 6, 5: 9, 6: 12})
        self.assertEqual((self.last(fmt)["record"] or {}).get("confidence"), "unknown")

    def test_a_cut_table_with_no_swiss_standings_behind_it_does_not_crash(self):
        # A cut round reads against the whole of Swiss, and the blog does not
        # always publish standings after the last Swiss round. Reaching for a
        # table that is not there took the build down with a KeyError.
        from build import build_format, Source
        from parse import Post, Table
        rows = [{"rank": 1, "name": "Ada Lovelace", "points": 6},
                {"rank": 2, "name": "Bo Peep", "points": 0}]
        def pairings(rnd, title=None):
            return Source(f"https://x/p{rnd}/", Post(
                title=title or f"Round {rnd} Pairings", kind="pairings", fmt=None, round=rnd,
                table=Table(kind="pairings", columns=["table", "a", "b"],
                            rows=[{"table": 1, "a": {"name": "Ada Lovelace"},
                                   "b": {"name": "Bo Peep"}}])), "10:00")
        def standings(rnd, title=None):
            return Source(f"https://x/s{rnd}/", Post(
                title=title or f"Standings After Round {rnd}", kind="standings",
                fmt=None, round=rnd,
                table=Table(kind="standings", columns=["rank", "name", "points"],
                            rows=rows)), "11:00")
        fmt = build_format(None, [
            pairings(1), pairings(2), standings(2), pairings(3),
            pairings("Top 4", title="Top 4 Pairings"),
            standings("Top 4", title="Top 4 Standings"),
        ], event_date="2023-05-28")
        self.assertTrue(any(r["standings"] for r in fmt["rounds"]))

    def test_an_unbroken_run_reaches_the_round_it_reports(self):
        # The same points, with round four published: now the run reaches back
        # to round two, where three points is one win and one loss and nothing
        # else, and every round after it is a delta.
        fmt = self.fmt_with({2: 3, 3: 6, 4: 6, 5: 9, 6: 12})
        self.assertEqual(self.last(fmt)["record"],
                         {"wins": 4, "losses": 2, "draws": 0, "confidence": "derived"})


class TestPairingsWrittenAsProse(unittest.TestCase):
    """Konami writes a round as sentences often enough to matter.

    The 2023 North America Remote Duel YCS published its Top 8 and Top 4 that
    way, and the archive had no cut for that event at all.
    """

    def rows(self, text):
        from parse import parse_prose_pairings
        return parse_prose_pairings(text)

    def test_a_round_is_read_out_of_sentences(self):
        got = self.rows("Table 1: Jordan Farris (Floowandereeze) vs. "
                        "Liam Mac Oscair (Mathmech @Ignister)")
        self.assertEqual(got, [{"table": 1,
                                "a": {"name": "Jordan Farris", "region": None,
                                      "deck": "Floowandereeze"},
                                "b": {"name": "Liam Mac Oscair", "region": None,
                                      "deck": "Mathmech @Ignister"}}])

    def test_the_deck_is_the_last_thing_in_the_bracket(self):
        # The writer puts in whatever they had: a deck, or a country and a
        # points total and a deck. The deck is the part all of them end with.
        got = self.rows("Table 1: Hideki Kawai (Japan – 9 points – Frog Monarch) vs. "
                        "Kei Kuwano (Japan – 9 points – Herald of Perfection)")
        self.assertEqual(got[0]["a"]["deck"], "Frog Monarch")
        self.assertEqual(got[0]["b"]["deck"], "Herald of Perfection")

    def test_a_surname_first_name_is_turned_around(self):
        got = self.rows("Table 1: Medina Hernandez, Omar (HEROES) vs. "
                        "Franco Flores, Braulio Omar (Gravekeepers)")
        self.assertEqual([got[0]["a"]["name"], got[0]["b"]["name"]],
                         ["Omar Medina Hernandez", "Braulio Omar Franco Flores"])

    def test_a_result_trailing_the_row_is_not_part_of_the_name(self):
        # "...(Gravekeepers) Braulio wins 2-0" -- the bracket says where the
        # name stopped.
        got = self.rows("Table 1: Medina Hernandez, Omar (HEROES) vs. "
                        "Franco Flores, Braulio Omar (Gravekeepers) Braulio wins 2-0")
        self.assertEqual(got[0]["b"]["name"], "Braulio Omar Franco Flores")

    def test_a_missing_space_after_vs_does_not_swallow_the_next_table(self):
        # One row of the 2013 Central America Top 16 reads "(Constellars)
        # vs.Gallegos Lomeli, Luis Edgar" with no space, and a separator that
        # insisted on one ran the row on into the table after it. The Top 16
        # came out with seven matches.
        got = self.rows("Table 1: Garcia Reyes, Eduardo (Constellars) vs.Gallegos Lomeli, "
                        "Luis Edgar (Dragon Ruler) "
                        "Table 2: Vazquez Herrera, Jonhathan (Dragon Ruler) vs. "
                        "Rodriguez Pinto, Victor (Dragon Ruler)")
        self.assertEqual([r["table"] for r in got], [1, 2])
        self.assertEqual(got[0]["b"]["name"], "Luis Edgar Gallegos Lomeli")

    def test_a_bye_is_not_a_pairing_and_does_not_spoil_the_round(self):
        # "Table 16: Jonathon Castillo Gomez (Blue-Eyes) – BYE" is a real thing
        # to publish and nothing to pair.
        got = self.rows("Table 1: A One (Deck) vs. B Two (Deck) "
                        "Table 2: Jonathon Castillo Gomez (Blue-Eyes) – BYE")
        self.assertEqual([r["table"] for r in got], [1])

    def test_a_round_that_will_not_parse_whole_is_not_used_at_all(self):
        # A bracket short a match is not a smaller bracket, it is a wrong one,
        # and the round it lands in would be measured against a field that
        # never played it.
        self.assertEqual(self.rows("Table 1: A One (Deck) vs. B Two (Deck) "
                                   "Table 2: no bracket here vs nor here"), [])

    def test_a_whole_round_is_read_not_just_the_top_tables(self):
        # Sixty-four tables of two named Duelists and their decks is a long
        # post, and reading only the opening of it loses the bottom of the room.
        from parse import parse_post
        tables = " ".join(
            f"Table {i}: Duelist Number{i} (Deck{i}) vs. Opponent Number{i} (Other{i})"
            for i in range(1, 65))
        page = ('<title>Round 1 Pairings</title><div class="entry-content"><p>'
                + tables + '</p></div></div>')
        got = parse_post(page, "https://x/round-1-pairings/")
        self.assertEqual(len(got.table.rows), 64)
        self.assertEqual(got.table.rows[-1]["a"]["name"], "Duelist Number64")

    def test_prose_reaches_the_post_when_there_is_no_table(self):
        from parse import parse_post
        page = ('<title>Top 8 Pairings (with Deck Types!)</title>'
                '<div class="entry-content"><p>Take a look at the Top 8!</p>'
                '<p>Table 1: A One (Floowandereeze) vs. B Two (Mathmech)</p>'
                '</div></div>')
        got = parse_post(page, "https://x/top-8-pairings-with-deck-types/")
        self.assertEqual(got.kind, "pairings")
        self.assertEqual(got.table.kind, "pairings")
        self.assertEqual(len(got.table.rows), 1)

    def test_a_page_with_a_table_is_read_from_the_table(self):
        # The prose reading is a fallback, not a second opinion.
        from parse import parse_post
        page = ('<title>Round 3 Pairings</title><div class="entry-content">'
                '<table><tr><th>Table</th><th>Duelist</th><th>vs.</th><th>Duelist</th></tr>'
                '<tr><td>1</td><td>Ada Lovelace</td><td>vs.</td><td>Bo Peep</td></tr></table>'
                '<p>Table 9: Somebody Else (Deck) vs. Another One (Deck)</p>'
                '</div></div>')
        got = parse_post(page, "https://x/round-3-pairings/")
        self.assertEqual([r["table"] for r in got.table.rows], [1])


class TestProseRounds(unittest.TestCase):
    """Rounds the blog wrote as sentences rather than as a table."""

    def rows(self, text):
        from parse import parse_prose_pairings
        return parse_prose_pairings(text)

    def test_a_table_number_without_a_colon(self):
        # Eight posts write "Table 1 De Obaldia Soza, ..." with nothing
        # between the number and the first name.
        got = self.rows("Here are the pairings for Top 4: "
                        "Table 1 Andrade Castro, Juan Sebastian (True Draco) vs "
                        "Stephenson, Darren James (Pendulum Magicians) "
                        "Table 2 Perez Herrera, Hector (ABC) vs Mena Campos, Esteban (Zoodiac)")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["a"]["name"], "Juan Sebastian Andrade Castro")
        self.assertEqual(got[0]["b"]["deck"], "Pendulum Magicians")

    def test_a_deck_after_a_dash_instead_of_a_bracket(self):
        # The 2014 Central America WCQ writes the deck after a dash.
        got = self.rows("Here are the pairings for the Top 8: "
                        "Table 1: Elizondo Ochoa, Saul Hiram \u2013 Madolche Hand vs. "
                        "Gonzalez Orea, Alvaro \u2013 Geargia")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["a"]["name"], "Saul Hiram Elizondo Ochoa")
        self.assertEqual(got[0]["a"]["deck"], "Madolche Hand")

    def test_a_country_written_out_beside_the_name(self):
        got = self.rows("Table 1 De Obaldia Soza, Galileo Mauricio from Panama (ABC) "
                        "vs Perez Herrera, Hector Lorenzo from Chile (ABC)")
        self.assertEqual(got[0]["a"]["name"], "Galileo Mauricio De Obaldia Soza")

    def test_a_chain_with_no_table_numbers(self):
        # Nothing separates one pairing from the next but the bracket ending
        # the side before it.
        got = self.rows("Here are the Top 4 Pairings! "
                        "Aaron Furman (Metalfoes) vs. Chandler Sanford (Majespecter) "
                        "Kamal Crooks (Blue-Eyes) vs. Jose Uriel Diaz (Kozmo)")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["a"]["name"], "Aaron Furman")
        self.assertEqual(got[1]["b"]["name"], "Jose Uriel Diaz")

    def test_a_preamble_ending_in_a_full_stop(self):
        got = self.rows("Only four Duelists remain! Here are the semifinal matchups. "
                        "Rolando Alberto Gordon Bustamante (Gouki) vs. "
                        "Andres David Torres Reyes (Burning Abyss)")
        self.assertEqual(got[0]["a"]["name"], "Rolando Alberto Gordon Bustamante")

    def test_an_initial_is_not_the_end_of_a_preamble(self):
        # Cutting at every full stop would take "Antonio Nogueira Jr." down to
        # nothing and lose the post rather than its preamble.
        got = self.rows("We are close to crowning a champion! "
                        "Antonio Nogueira Jr. (Tengu Synchro) vs Julian Beltran (Six Samurai)")
        self.assertEqual(got[0]["a"]["name"], "Antonio Nogueira Jr.")

    def test_a_sentence_trailing_a_pairing_is_not_a_deck(self):
        # "Parra, Filiberto Octavio - Geargia advances to Top 8. Orea had
        # represented Central America in 2012" is a sentence, not an
        # archetype. The name is worth keeping without it.
        got = self.rows("Table 1: Gonzalez Orea, Alvaro \u2013 Madolche Hand vs. "
                        "Parra, Filiberto Octavio \u2013 Geargia Parra, Filiberto Octavio "
                        "\u2013 Geargia advances to Top 8. Orea had represented Central America.")
        self.assertEqual(got[0]["b"]["name"], "Filiberto Octavio Parra")
        self.assertIsNone(got[0]["b"]["deck"])


class TestProseDuels(unittest.TestCase):
    """A round written as a sentence about the Duelists in it.

    Every YCS final since 2022 is published this way, and a Final is what an
    event needs before a winner post has two Duelists to be recognised among.
    """

    def rows(self, text):
        from parse import parse_prose_duels
        return parse_prose_duels(text)

    def test_a_final_written_as_a_sentence(self):
        got = self.rows("It all comes down to this! Michael Tamez and his "
                        "Floowandereeze Deck is facing off against Christopher "
                        "LeBlanc and his Spright Tearlaments Deck in a Match.")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["a"], {"name": "Michael Tamez", "region": None,
                                       "deck": "Floowandereeze"})
        self.assertEqual(got[0]["b"]["name"], "Christopher LeBlanc")

    def test_the_other_way_of_saying_it(self):
        got = self.rows("Ryan Yu will be using his Sky Striker Deck to Duel "
                        "against Landon Oliver and his Fire King Snake-Eye "
                        "Azamina Deck in the Finals!")
        self.assertEqual(got[0]["a"], {"name": "Ryan Yu", "region": None,
                                       "deck": "Sky Striker"})
        self.assertEqual(got[0]["b"]["deck"], "Fire King Snake-Eye Azamina")

    def test_a_deck_that_has_the_word_deck_in_it(self):
        # YCS Toronto writes "his Extra Deck Monarch Deck". Stopping at the
        # first "Deck" leaves the archetype as "Extra".
        got = self.rows("At Table 1, Ryan Arthur Levine is using his Extra Deck "
                        "Monarch Deck to Duel against Bohdan Temnyk and his "
                        "Burning Abyss Phantom Knight Deck.")
        self.assertEqual(got[0]["a"]["name"], "Ryan Arthur Levine")
        self.assertEqual(got[0]["a"]["deck"], "Extra Deck Monarch")

    def test_two_duelists_and_no_decks(self):
        got = self.rows("Here are the Final Pairing at the North American "
                        "World Championship Qualifier. Chase Robert Cunningham "
                        "versus Noah Reid Greene")
        self.assertEqual((got[0]["a"]["name"], got[0]["b"]["name"]),
                         ("Chase Robert Cunningham", "Noah Reid Greene"))

    def test_a_post_with_no_table_falls_through_to_the_sentence(self):
        # The list is tried first and the sentence is what is left. Without
        # that second try the post carries no table and is dropped whole.
        html = ("<html><head><title>YCS Houston Final Pairing</title></head><body>"
                "<div><div class=\"entry-content\"><p>The final round of YCS Houston "
                "is about to begin! Pascal Manigat and his Goblin Memento Deck will be "
                "facing off against Manuel Kalin and his Ryzeal Deck in a Match that "
                "will determine the winner of YCS Houston!</p></div></div>"
                "<footer>x</footer></body></html>")
        t = parse_post(html).table
        self.assertIsNotNone(t, "a final written as a sentence is still a round")
        self.assertEqual(t.kind, "pairings")
        self.assertEqual(len(t.rows), 1)
        self.assertEqual(t.rows[0]["a"]["name"], "Pascal Manigat")

    def test_a_round_short_a_match_is_not_taken(self):
        # Two sentences say "against" and only one of them names two
        # Duelists. Half a round is a wrong round, so neither is kept.
        got = self.rows("Ann Alpha and her Ryzeal Deck is up against Bo Beta and "
                        "his Maliss Deck. They are up against each other now!")
        self.assertEqual(got, [])

    def test_a_clause_is_not_a_duelist(self):
        # The 2016 South America WCQ writes its Top 16 as a dash-delimited
        # chain with "Versus" between the halves. Read as sentences, that gave
        # a Duelist called "With just sixteen Duelists now remaining in the
        # WCQ let's find out who's left" playing one called "in the Top 16" --
        # a Top 16 of two matches, which took the event out of the archive.
        got = self.rows("With just sixteen Duelists now remaining in the WCQ "
                        "let\u2019s find out who\u2019s left; where they\u2019re from; "
                        "and who they\u2019re up against in the Top 16!")
        self.assertEqual(got, [])

    def test_a_doubled_word_does_not_cost_the_post(self):
        # YCS Toronto writes "Michael Kyle Walters and and his Burning Abyss
        # Phantom Knight Deck", and the doubled word leaves a conjunction on
        # the end of the name -- which the name test then refuses, losing the
        # round rather than the typo.
        got = self.rows("At Table 2, Alexander Dalpe is using his Domain Monarch "
                        "Deck to Duel against Michael Kyle Walters and and his "
                        "Burning Abyss Phantom Knight Deck.")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["b"]["name"], "Michael Kyle Walters")

    def test_a_sentence_naming_nobody_is_not_a_round(self):
        # The same all-or-nothing the pairings reader applies: a round short a
        # match is a wrong round, not a small one.
        self.assertEqual(self.rows("They are about to face off against each other!"), [])
        self.assertEqual(self.rows("A weekend of Duelling is over."), [])


class TestWinnerProse(unittest.TestCase):
    """The one line a champion can be read out of, and only for the posts that
    might carry one."""

    PAGE = ('<title>And the Winner Is&#8230;</title>'
            '<div class="entry-content"><p>Congratulations to Ann Alpha Smith, '
            'who defeated Bo Beta Jones!</p>{extra}</div></div>')

    def test_a_result_posts_opening_is_kept(self):
        from parse import parse_post
        got = parse_post(self.PAGE.format(extra=""), "https://x/and-the-winner-is/")
        self.assertEqual(got.kind, "result")
        self.assertIn("Ann Alpha Smith", got.lead)

    def test_every_other_kind_carries_no_prose(self):
        # Read from their tables, so holding their paragraphs would be weight
        # carried through the build of a 140-post event for nothing.
        from parse import parse_post
        page = ('<title>Round 3 Pairings</title><div class="entry-content">'
                '<p>Here are the pairings.</p></div></div>')
        got = parse_post(page, "https://x/round-3-pairings/")
        self.assertEqual(got.kind, "pairings")
        self.assertEqual(got.lead, "")

    def test_a_table_underneath_does_not_drown_the_sentence(self):
        # A post announcing a champion sometimes carries the final standings
        # below it, and a thousand names of table would push the one sentence
        # that matters past the end of what is kept.
        from parse import parse_post
        table = "<table>" + "".join(
            f"<tr><td>{i}</td><td>Someone Else Number {i}</td></tr>"
            for i in range(200)) + "</table>"
        got = parse_post(self.PAGE.format(extra=table), "https://x/and-the-winner-is/")
        self.assertIn("Ann Alpha Smith", got.lead)
        self.assertNotIn("Someone Else Number", got.lead)

    def test_the_opening_is_bounded(self):
        from parse import parse_post, LEAD_CHARS
        page = self.PAGE.format(extra="<p>" + ("padding " * 400) + "</p>")
        self.assertLessEqual(len(parse_post(page, "https://x/w/").lead), LEAD_CHARS)


class TestChampionInAFeatureMatch(unittest.TestCase):
    """The final's own write-up says who took it, in one sentence.

    Everything else it says about champions is a preview or a biography, and
    both read like results.
    """

    def feature(self, text, title="Finals Feature Match: Ada Lovelace vs Bo Peep"):
        return {"title": title, "text": text, "kind": "feature"}

    def test_the_sentence_that_crowns_somebody_is_read(self):
        from winners import champion
        got = champion(["Ada Lovelace", "Bo Peep"],
                       [self.feature("A long match, described at length. "
                                     "Ada Lovelace is your YCS Champion!")])
        self.assertEqual(got, "Ada Lovelace")

    def test_a_prediction_is_not_a_result(self):
        # "...is now just a short win away from becoming a YCS Champion!" was
        # written about a Duelist mid-match.
        from winners import champion
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Ada Lovelace is now just a short win away from becoming a YCS Champion!")]))
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "One of these Duelists will soon be known as a YCS champion.")]))

    def test_a_duelists_history_is_not_this_events_result(self):
        # The dangerous one: a fact about the runner-up, in the past tense, in
        # a post about the match he went on to lose.
        from winners import champion
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Bo Peep is a 2-time YCS Champion, and although Lovelace has only "
            "one win, it came a week ago.")]))

    def test_a_side_events_crowning_is_not_the_events(self):
        from winners import champion
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Ada Lovelace is the 2018 Central America Dragon Duel WCQ Champion!")]))

    def test_the_last_crowning_wins_not_the_first(self):
        # Two sentences that both crown somebody, and only the order says which
        # is this event's. A finals write-up opens by recalling who won the last
        # one -- and that Duelist is often sitting at the table.
        from winners import champion
        got = champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Ada Lovelace is the champion of the last YCS she entered. "
            "Tonight is another matter. "
            "Bo Peep is your YCS Champion!")])
        self.assertEqual(got, "Bo Peep")

    def test_a_crowning_naming_nobody_on_record_claims_nobody(self):
        # A post filed under the wrong event: "Shunping Xu is the champion of
        # YCS Pasadena" sits in YCS Sao Paulo's coverage.
        from winners import champion
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Shunping Xu is the champion of YCS Pasadena with his Sky Striker Deck!")]))

    def test_a_feature_match_that_crowns_nobody_is_ignored(self):
        # Most of them: the match is described and it ends with boilerplate.
        from winners import champion
        self.assertIsNone(champion(["Ada Lovelace", "Bo Peep"], [self.feature(
            "Ada Lovelace attacks for game. Click here for the next Feature Match.")]))

    def test_the_finals_write_up_is_kept_whole_enough_to_find_it(self):
        # The sentence naming the champion sat 5,000 characters into the post
        # that crowned the North America Remote Duel YCS.
        from parse import parse_post, MATCH_CHARS
        page = ('<title>Finals Feature Match: Ada Lovelace vs Bo Peep</title>'
                '<div class="entry-content"><p>' + ('turn after turn. ' * 300)
                + 'Ada Lovelace is your YCS Champion!</p></div></div>')
        got = parse_post(page, "https://x/finals-feature-match-a-vs-b/")
        self.assertEqual(got.kind, "feature")
        self.assertEqual(got.round, "Final")
        self.assertIn("Ada Lovelace is your YCS Champion", got.lead)
        self.assertLessEqual(len(got.lead), MATCH_CHARS)

    def test_an_ordinary_feature_match_carries_no_prose(self):
        # Only the final's. An event publishes thirty of these.
        from parse import parse_post
        page = ('<title>Round 4 Feature Match: Ada Lovelace vs Bo Peep</title>'
                '<div class="entry-content"><p>A match.</p></div></div>')
        self.assertEqual(parse_post(page, "https://x/round-4-feature-match/").lead, "")


class TestChampionInTheBuild(unittest.TestCase):
    """Who the candidates are, and that the answer reaches the file."""

    def rounds(self, *specs):
        return [{"label": lbl, "phase": phase,
                 "pairings": [{"a": a, "b": b} for a, b in pairs]}
                for lbl, phase, pairs in specs]

    def test_the_candidates_are_the_deepest_cut_round(self):
        from build import cut_finalists
        got = cut_finalists(self.rounds(
            ("Top 8", "Top cut", [("A One", "B Two"), ("C Three", "D Four")]),
            ("Top 4", "Top cut", [("A One", "C Three")])))
        self.assertEqual(got, ["A One", "C Three"])

    def test_swiss_players_are_not_candidates(self):
        # A Swiss round holds most of the field, and asking a winner post which
        # of two hundred names it mentions is the loose question that produced
        # wrong champions. An event with no cut published has no candidates.
        from build import cut_finalists
        self.assertEqual(cut_finalists(self.rounds(
            ("R11", "Swiss", [("A One", "B Two"), ("C Three", "D Four")]),
            ("R12", "Swiss", [("A One", "C Three")]))), [])

    def test_a_cut_round_with_no_pairings_is_not_the_deepest(self):
        # The bracket is often published a round further than the pairings are.
        from build import cut_finalists
        rounds = self.rounds(("Top 4", "Top cut", [("A One", "C Three")]))
        rounds.append({"label": "Final", "phase": "Top cut", "pairings": []})
        self.assertEqual(cut_finalists(rounds), ["A One", "C Three"])

    def announcement(self, lead):
        """A result post carrying one line of prose, as the fetcher would."""
        from build import Source
        from parse import Post
        return Source("https://x/and-the-winner-is/",
                      Post(title="And the Winner Is…", kind="result", fmt=None,
                           round=None, table=None, lead=lead),
                      "20:00")

    def test_the_champion_reaches_the_built_format(self):
        # The whole point: the answer has to be in the file the page reads.
        from build import build_event
        ev = build_event("YCS Montréal",
                         _sources() + [self.announcement(
                             "Congratulations to Samuel Deng, who defeated "
                             "Aviel Getter to take the whole thing!")],
                         updated="2026-08-16T19:10:00Z")
        gen = next(f for f in ev["formats"] if f["format"] == "Genesys")
        self.assertEqual(gen["champion"], "Samuel Deng")

    def test_a_finals_feature_match_reaches_the_built_format(self):
        # The extractor can read one, and the builder has to hand it over: for
        # nine events in the archive the finals write-up is the only thing that
        # names a champion at all.
        from build import build_event, Source
        from parse import Post
        write_up = Source(
            "https://x/finals-feature-match/",
            Post(title="Finals Feature Match: Samuel Deng vs Aviel Getter",
                 kind="feature", fmt=None, round="Final", table=None,
                 lead="A long match. Samuel Deng is your YCS Champion!"),
            "20:00")
        ev = build_event("YCS Montréal", _sources() + [write_up],
                         updated="2026-08-16T19:10:00Z")
        gen = next(f for f in ev["formats"] if f["format"] == "Genesys")
        self.assertEqual(gen["champion"], "Samuel Deng")

    def test_a_round_nothing_was_published_for_is_not_a_round(self):
        # One is created whenever a post names a round and carries nothing: a
        # feature match whose title will not parse into two Duelists, or a side
        # event's write-up naming a Final the main event has not reached. Left
        # in, it is an empty row on the track and the deploy refuses the event.
        from build import build_event, Source
        from parse import Post
        # The title says "Finals Feature Match" and nothing more, so no two
        # Duelists come out of it and the round it names carries nothing. It
        # must be in a format's own sources to create one at all.
        names_a_final = Source(
            "https://x/finals-feature/",
            Post(title="Finals Feature Match", kind="feature", fmt="Genesys",
                 round="Final", table=None, lead=""), "20:00")
        ev = build_event("YCS Montréal", _sources() + [names_a_final],
                         updated="2026-08-16T19:10:00Z")
        gen = next(f for f in ev["formats"] if f["format"] == "Genesys")
        self.assertNotIn("Final", [r["label"] for r in gen["rounds"]])
        for fmt in ev["formats"]:
            for r in fmt["rounds"]:
                self.assertTrue(r["pairings"] or r["standings"] or r.get("feature"),
                                f"{r['label']} is empty")

    def test_a_round_with_only_a_feature_match_is_still_a_round(self):
        # The blog covers some rounds with a feature match and nothing else.
        from build import build_event, Source
        from parse import Post
        ev = build_event("YCS Montréal", _sources() + [Source(
            "https://x/f/", Post(title="Final Feature Match: Ada Lovelace vs Bo Peep",
                                 kind="feature", fmt="Genesys", round="Final",
                                 table=None, lead=""), "20:00")],
            updated="2026-08-16T19:10:00Z")
        gen = next(f for f in ev["formats"] if f["format"] == "Genesys")
        final = next((r for r in gen["rounds"] if r["label"] == "Final"), None)
        self.assertIsNotNone(final, "the round is kept")
        self.assertTrue(final["features"])

    def test_an_event_nobody_announced_a_winner_for_says_so(self):
        # Null is the common answer across the archive, and a real one.
        from build import build_event
        ev = build_event("YCS Montréal", _sources(), updated="2026-08-16T19:10:00Z")
        self.assertTrue(all(f["champion"] is None for f in ev["formats"]))

    def test_a_side_events_post_does_not_crown_anybody(self):
        from build import build_event
        ev = build_event("YCS Montréal",
                         _sources() + [self.announcement(
                             "We have our winner of the Dragon Duel Championship "
                             "playoff! Samuel Deng used his Ryzeal deck…")],
                         updated="2026-08-16T19:10:00Z")
        self.assertTrue(all(f["champion"] is None for f in ev["formats"]))


class TestUpcomingEvents(unittest.TestCase):
    """The schedule, which the blog does not carry.

    The blog covers a tournament while it happens and says nothing before it,
    so what is next comes from Konami's own listing at yugioh-card.com.
    """

    HOUSTON = ("/en/events-item/2026-ycs-houston/",
               ["Yu-Gi-Oh! Championship Series Houston, Texas 2026",
                "Houston, TX", "10/16/2026 - 10/18/2026"])

    def parse(self, *items):
        from upcoming import parse_events
        return parse_events(listing(*items))

    def test_an_event_is_read_whole(self):
        got = self.parse(self.HOUSTON)[0]
        self.assertEqual(got["event"], "YCS Houston")
        self.assertEqual(got["location"], "Houston, TX")
        self.assertEqual((got["starts"], got["ends"]), ("2026-10-16", "2026-10-18"))
        self.assertEqual(got["url"],
                         "https://www.yugioh-card.com/en/events-item/2026-ycs-houston/")

    def test_the_series_and_the_state_and_the_year_come_out_of_the_name(self):
        # The year is in the date beside it and the state is in the location
        # beside that, so what is left is what anyone calls the tournament.
        got = self.parse(
            ("/e/1", ["Yu-Gi-Oh! Championship Series Guayaquil, Ecuador 2026",
                      "Guayaquil, Ecuador", "10/02/2026 - 10/04/2026"]),
            ("/e/2", ["Yu-Gi-Oh! Championship Series Santiago, Chile 2026",
                      "Santiago, Chile", "11/27/2026 - 11/29/2026"]))
        self.assertEqual([e["event"] for e in got], ["YCS Guayaquil", "YCS Santiago"])

    def test_what_was_listed_is_kept_beside_the_name(self):
        # The name shown is derived, so the source's own wording stays on record
        # rather than being thrown away where nobody can check the derivation.
        self.assertEqual(self.parse(self.HOUSTON)[0]["listed"],
                         "Yu-Gi-Oh! Championship Series Houston, Texas 2026")

    def test_an_event_with_no_city_keeps_its_whole_name(self):
        # The Remote Duel events are named for a region and hosted on Discord.
        # There is no city to find and cutting to one would leave "YCS".
        got = self.parse(("/e/1", ["Latin America Remote Duel Yu-Gi-Oh! Championship Series",
                                   "Latin America (hosted on Discord)",
                                   "09/18/2026 - 09/20/2026"]))
        self.assertEqual(got[0]["event"], "Latin America Remote Duel YCS")

    def test_an_event_that_is_not_a_series_event_is_left_alone(self):
        # New York Comic Con is not a YCS and guessing at its shape would only
        # damage it.
        got = self.parse(("/e/1", ["New York Comic Con 2026", "New York, NY",
                                   "10/08/2026 - 10/11/2026"]))
        self.assertEqual(got[0]["event"], "New York Comic Con 2026")

    def test_an_open_ended_run_has_a_start_and_no_end(self):
        # The promotions run until further notice. A start with no end is not a
        # one-day event, and saying so is the difference between a promotion
        # still on and one the page would call long finished.
        got = self.parse(("/en/events/ygo_x_efootball/",
                          ["Yu-Gi-Oh! x eFootball Collaboration",
                           "North America & Latin America", "starts on 09/27/2025"]))
        self.assertEqual((got[0]["starts"], got[0]["ends"]), ("2025-09-27", None))

    def test_an_entry_with_no_date_is_not_an_event(self):
        # The listing carries standing links -- policies, store locators -- in
        # the same markup, and something that cannot say when it is does not go
        # in front of a reader.
        self.assertEqual(self.parse(("/en/events/organizedplay/", ["Organized Play Forms"])), [])

    def test_they_come_out_soonest_first(self):
        got = self.parse(
            ("/e/1", ["Yu-Gi-Oh! Championship Series Santiago, Chile 2026",
                      "Santiago, Chile", "11/27/2026 - 11/29/2026"]),
            self.HOUSTON)
        self.assertEqual([e["event"] for e in got], ["YCS Houston", "YCS Santiago"])

    def test_the_file_records_when_it_was_read(self):
        # Read every few months, so without this a reader cannot tell a quiet
        # schedule from a stale one.
        from upcoming import build
        import datetime
        got = build(listing(self.HOUSTON), datetime.date(2026, 8, 30))
        self.assertEqual(got["fetched"], "2026-08-30")
        self.assertEqual(len(got["events"]), 1)

    def test_whether_it_has_happened_is_not_decided_here(self):
        # A file written in October and read in December would otherwise call a
        # November tournament upcoming. The date is a fact about the event;
        # "upcoming" is a fact about when you are looking, so the page decides.
        from upcoming import build
        import datetime
        got = build(listing(("/e/1", ["Yu-Gi-Oh! Championship Series Houston, Texas 2020",
                                      "Houston, TX", "10/16/2020 - 10/18/2020"])),
                    datetime.date(2026, 8, 30))
        self.assertEqual(len(got["events"]), 1, "long past, and still written out")


class TestUpcomingAgainstTheRealListing(unittest.TestCase):
    """The saved page, so the parser is held to markup nobody here wrote."""

    def setUp(self):
        from pathlib import Path
        self.page = (Path(__file__).parent.parent / "test" / "fixtures"
                     / "yugioh-card-events.html").read_text(encoding="utf-8", errors="replace")

    def test_the_shipped_listing_parses(self):
        from upcoming import parse_events
        got = parse_events(self.page)
        self.assertEqual(len(got), 10)
        names = [e["event"] for e in got]
        for expected in ("YCS Houston", "YCS Orlando", "YCS Santiago", "YCS Guayaquil"):
            self.assertIn(expected, names)

    def test_every_event_read_has_the_four_things_the_page_shows(self):
        from upcoming import parse_events
        for e in parse_events(self.page):
            self.assertTrue(e["event"], e)
            self.assertRegex(e["starts"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(e["url"].startswith("https://www.yugioh-card.com/"), e)


class TestTheNameBreaksTheTie(unittest.TestCase):
    """Where a date matches two events, the qualifier the post names."""

    def assigned(self, *urls):
        rows = assign_events(parse_post_sitemap(urlset(*urls)))
        return {r["slug"]: (r["event"], r["event_confidence"]) for r in rows}

    CONCURRENT = [
        ("2026/championships/2026-north-america-wcq/nawcq-round-1-pairings", "2026-07-11"),
        ("2026/championships/2026-north-america-wcq/nawcq-standings-after-round-1", "2026-07-11"),
        ("2026/championships/2026-north-america-genesys-championship/"
         "genesys-round-1-pairings", "2026-07-11"),
        ("2026/championships/2026-north-america-genesys-championship/"
         "genesys-standings-after-round-1", "2026-07-11"),
    ]

    def test_a_post_naming_its_qualifier_goes_to_it(self):
        # The 2026 North America WCQ finished with no champion because the post
        # announcing its winner is headed "and-the-winner-of-the-2026-nawcq-is"
        # and the Genesys Championship ran the same weekend. It names its event
        # as plainly as a post can; what it does not name is a format, which is
        # all the rule before this one could read.
        got = self.assigned(*self.CONCURRENT,
                            ("2026/championships/and-the-winner-of-the-2026-nawcq-is", "2026-07-12"))
        self.assertEqual(got["and-the-winner-of-the-2026-nawcq-is"],
                         ("2026-north-america-wcq", "date+name"))

    def test_a_post_naming_no_qualifier_is_still_ambiguous(self):
        # This narrows an ambiguity. It does not resolve one by picking.
        got = self.assigned(*self.CONCURRENT,
                            ("2026/championships/what-a-weekend-that-was", "2026-07-12"))
        self.assertIsNone(got["what-a-weekend-that-was"][0])
        self.assertTrue(got["what-a-weekend-that-was"][1].startswith("ambiguous"))

    def test_a_format_in_the_slug_still_decides_first(self):
        # The older rule is the more specific one: a post naming the Genesys
        # tournament belongs to it whatever else it says.
        got = self.assigned(*self.CONCURRENT,
                            ("2026/championships/genesys-top-8-pairings-north-america-wcq-weekend",
                             "2026-07-12"))
        self.assertEqual(got["genesys-top-8-pairings-north-america-wcq-weekend"][0],
                         "2026-north-america-genesys-championship")

    def test_two_qualifiers_of_one_name_are_left_alone(self):
        # If both candidates answer to the name, the name has not told them
        # apart and neither gets the post.
        got = self.assigned(
            ("2019/championships/2019-north-america-wcq/nawcq-round-1-pairings", "2019-07-10"),
            ("2019/championships/2019-north-america-wcq/nawcq-standings-after-round-1", "2019-07-10"),
            ("2019/championships/2019-north-america-wcq-dragon-duel/"
             "nawcq-dragon-duel-round-1-pairings", "2019-07-10"),
            ("2019/championships/2019-north-america-wcq-dragon-duel/"
             "nawcq-dragon-duel-standings-after-round-1", "2019-07-10"),
            ("2019/championships/and-the-winner-of-the-2019-nawcq-is", "2019-07-11"))
        slug = "and-the-winner-of-the-2019-nawcq-is"
        self.assertTrue(got[slug][0] is None or got[slug][1] != "date+name")


class TestQualifierAbbreviation(unittest.TestCase):

    def test_nawcq_is_the_north_america_qualifier(self):
        # The region patterns already read it; the gate in front of them did
        # not, so a name the module knew how to write came back as nothing.
        from naming import wcq_name
        self.assertEqual(wcq_name("2024-nawcq", "", "2024-07-22"),
                         "North America WCQ 2024")

    def test_a_qualifier_that_abbreviates_its_region(self):
        # Three qualifiers name their region only in the short form, or by the
        # country instead, and so had no region at all: they went to the site
        # as "WCQ CA", "SA WCQ" and "WCQ Mexico".
        #
        # Two letters are enough here because a qualifier is the only thing
        # that reaches this function, and the blog runs these for Central,
        # South and North America and nothing else -- so "ca" is Central
        # America and not California.
        from naming import wcq_name
        self.assertEqual(wcq_name("2014-wcq-ca", "WCQ CA", "2014-07-06"),
                         "Central America WCQ 2014")
        self.assertEqual(wcq_name("2016-sa-wcq", "SA WCQ", "2016-06-19"),
                         "South America WCQ 2016")
        # Mexico's qualifier is the Central American one. The archive holds
        # every year from 2012 to 2026 except 2014 and 2016, and these two
        # events are exactly those years.
        self.assertEqual(wcq_name("wcq-2016-mexico", "WCQ Mexico", "2016-06-11"),
                         "Central America WCQ 2016")

    def test_the_qualifier_under_its_older_name(self):
        # Before 2023 the same event was the region's Yu-Gi-Oh! TCG
        # Championship, and its North American leg is filed under the initials
        # of that older name. All three regions ran one in 2022 and the
        # archive had no 2022 qualifier for any of them.
        from naming import wcq_name
        self.assertEqual(wcq_name("na-ygoc-2022", "Na Ygoc 2022", "2022-07-22"),
                         "North America WCQ 2022")
        self.assertEqual(
            wcq_name("central-america-yu-gi-oh-tcg-championship-2022",
                     "Central America Yu-Gi-Oh! TCG Championship 2022", "2022-06-19"),
            "Central America WCQ 2022")
        self.assertEqual(
            wcq_name("south-america-yu-gi-oh-tcg-championship-2022",
                     "South America Yu-Gi-Oh! TCG Championship 2022", "2022-06-26"),
            "South America WCQ 2022")

    def test_the_world_championship_is_not_a_qualifier(self):
        # It is the same words with "World" in the middle of them, and
        # wcq_name is asked first. Claiming it here would take the event away
        # from worlds_name.
        from naming import wcq_name, canonical_name
        self.assertIsNone(wcq_name("yu-gi-oh-tcg-world-championship-2024",
                                   "Yu-Gi-Oh! TCG World Championship 2024", "2024-08-25"))
        self.assertEqual(
            canonical_name("Yu-Gi-Oh! TCG World Championship 2024",
                           "yu-gi-oh-tcg-world-championship-2024", "2024-08-25")[0],
            "World Championship 2024")

    def test_another_championship_beside_it_is_not_a_qualifier(self):
        # The Genesys and Dragon Duel championships run alongside and are not
        # the qualifier.
        from naming import wcq_name
        for slug, name in (
                ("2026-central-america-genesys-championship",
                 "Central America Genesys Championship"),
                ("2026-south-america-dragon-duel-championship",
                 "South America Dragon Duel Championship")):
            self.assertIsNone(wcq_name(slug, name, "2026-06-08"), slug)

    def test_the_renamed_qualifier_is_still_found_by_its_initials(self):
        # The site's event search matches on initials, so "NAWCQ" has to keep
        # finding an event whose coverage never used the word. This is the
        # rule app.js implements; if it changes there, this says so.
        name = "North America WCQ 2022"
        words = [w for w in name.split() if any(c.isalpha() for c in w)]
        initials = "".join(w if len(w) > 1 and w == w.upper() else w[0]
                           for w in words).lower()
        self.assertEqual(initials, "nawcq")

    def test_the_region_written_out_beats_two_letters_elsewhere(self):
        # Order matters: a slug that says the region in full must never be
        # read off two letters somewhere else in it.
        from naming import wcq_name
        self.assertEqual(
            wcq_name("2026-south-america-wcq-ca-final", "South America WCQ", "2026-06-28"),
            "South America WCQ 2026")

    def test_a_word_merely_ending_in_wcq_is_not_a_qualifier(self):
        from naming import wcq_name
        self.assertIsNone(wcq_name("2024-showcq", "", "2024-07-22"))


class TestTheWorldChampionship(unittest.TestCase):
    """One event a year, spelled five ways across five years."""

    def test_every_spelling_settles_on_one_name(self):
        from naming import worlds_name
        for slug, name, ended, want in (
                ("wcs-2010", "Wcs 2010", "2010-08-16", "World Championship 2010"),
                ("yu-gi-oh-world-championship-2013", "Yu Gi Oh World Championship 2013",
                 "2013-08-13", "World Championship 2013"),
                # The one with no name at all: its coverage heads six posts
                # "Pairings: ..." and writes the event's own name without a
                # colon, so the vote never saw it.
                ("yu-gi-oh-world-championship-2016", "Pairings",
                 "2016-08-21", "World Championship 2016"),
                ("yu-gi-oh-tcg-world-championship-2024",
                 "Yu-Gi-Oh! TCG World Championship 2024", "2024-08-25",
                 "World Championship 2024"),
                ("yu-gi-oh-tcg-world-championship-2026",
                 "Yu-Gi-Oh! TCG WORLD CHAMPIONSHIP 2026", "2026-08-30",
                 "World Championship 2026")):
            self.assertEqual(worlds_name(slug, name, ended), want, slug)

    def test_the_name_the_archive_actually_gets(self):
        # Through canonical_name, which is what run.py calls. Reaching the
        # right answer in a helper nothing consults would fix nothing.
        from naming import canonical_name
        self.assertEqual(
            canonical_name("Pairings", "yu-gi-oh-world-championship-2016",
                           "2016-08-21", named=True)[0],
            "World Championship 2016")
        self.assertEqual(
            canonical_name("Yu-Gi-Oh! TCG WORLD CHAMPIONSHIP 2026",
                           "yu-gi-oh-tcg-world-championship-2026",
                           "2026-08-30", named=True)[0],
            "World Championship 2026")

    def test_a_qualifier_is_not_the_championship_it_qualifies_for(self):
        # WCQ stands for World Championship Qualifier, so the words are right
        # there in the name and a rule reading for them would rename every
        # qualifier in the archive after the event it is not.
        from naming import worlds_name, canonical_name
        self.assertIsNone(worlds_name("2026-north-america-wcq",
                                      "North America WCQ 2026", "2026-06-28"))
        self.assertIsNone(worlds_name("2019-north-america-wcq",
                                      "World Championship Qualifier", "2019-06-30"))
        self.assertEqual(canonical_name("North America WCQ 2026",
                                        "2026-north-america-wcq", "2026-06-28")[0],
                         "North America WCQ 2026")

    def test_a_championship_with_no_year_is_not_named_for_one(self):
        from naming import worlds_name
        self.assertIsNone(worlds_name("world-championship", "World Championship", None))

    def test_an_ordinary_event_is_left_alone(self):
        from naming import worlds_name
        self.assertIsNone(worlds_name("2026-08-quebec", "YCS Montréal", "2026-08-16"))
        self.assertIsNone(worlds_name("2022-central-america-championship",
                                      "Central America Yu-Gi-Oh! TCG Championship 2022",
                                      "2022-11-06"))


class TestTheRemoteDuelYCS(unittest.TestCase):
    """More than one a year, and the blog spelled it five ways."""

    def test_every_spelling_settles_on_one_name(self):
        from naming import remote_duel_name
        for slug, name, ended, want in (
                # Three called exactly this, so the front page listed them
                # side by side with nothing to tell them apart.
                ("2022-02-north-america-remote-duel-ycs", "Remote Duel YCS", "2022-02-27",
                 "North America Remote Duel YCS February 2022"),
                ("2022-remote-duel-ycs-north-america", "Remote Duel YCS", "2022-12-11",
                 "North America Remote Duel YCS December 2022"),
                ("2022-january-remote-duel-ycs", "Remote Duel YCS", "2022-01-16",
                 "Remote Duel YCS January 2022"),
                ("2022-latin-america-remote-duel-ycs", "Latin America Remote Duel",
                 "2022-02-01", "Latin America Remote Duel YCS February 2022"),
                ("2025-12-rdycs-na", "Remote Duel YCS-North America", "2025-12-16",
                 "North America Remote Duel YCS December 2025"),
                # And two called exactly this.
                ("2023-north-america-remote-duel-ycs", "North America Remote Duel YCS",
                 "2023-06-25", "North America Remote Duel YCS June 2023"),
                ("2024-11-north-america-remote-duel-ycs", "North America Remote Duel YCS",
                 "2024-11-10", "North America Remote Duel YCS November 2024")):
            self.assertEqual(remote_duel_name(slug, name, ended), want, slug)

    def test_the_month_comes_from_the_slug_not_the_last_post(self):
        # The date is the end of the coverage, and the coverage can run past
        # the month it covers: this event's last post is on 1 February and it
        # is January's event. Reading the month off the date renames it.
        from naming import remote_duel_name
        self.assertEqual(
            remote_duel_name("remote-duel-ycs-january-2026",
                             "Remote Duel YCS January 2026", "2026-02-01"),
            "Remote Duel YCS January 2026")

    def test_an_event_the_blog_gives_no_region_keeps_none(self):
        # Three of these never name a region anywhere in their coverage. The
        # blog calls them "Remote Duel YCS January 2024" and nothing more, and
        # inventing a region would be a guess dressed as a fact.
        from naming import remote_duel_name
        for slug, name, ended in (
                ("remote-duel-ycs-january-2024", "Remote Duel YCS January 2024", "2024-01-28"),
                ("remote-duel-ycs-february-2025", "Remote Duel YCS February 2025", "2025-02-09")):
            got = remote_duel_name(slug, name, ended)
            self.assertEqual(got, name, slug)
            self.assertNotIn("America", got)

    def test_the_extravaganza_is_not_a_ycs(self):
        # A different thing that also happens to be played remotely. It keeps
        # its own name rather than being renamed after a series it is not in.
        from naming import remote_duel_name
        self.assertIsNone(remote_duel_name(
            "2023-yu-gi-oh-tcg-remote-duel-extravaganza-main-event",
            "2023 Yu Gi Oh Tcg Remote Duel Extravaganza Main Event", "2023-07-30"))

    def test_an_ordinary_ycs_is_left_alone(self):
        from naming import remote_duel_name, canonical_name
        self.assertIsNone(remote_duel_name("2026-08-quebec", "YCS Montréal", "2026-08-16"))
        self.assertEqual(canonical_name("YCS Montréal", "2026-08-quebec", "2026-08-16")[0],
                         "YCS Montréal")

    def test_the_name_the_archive_actually_gets(self):
        # Through canonical_name, which is what run.py calls.
        from naming import canonical_name
        self.assertEqual(
            canonical_name("Remote Duel YCS", "2025-12-rdycs-na", "2025-12-16",
                           named=True)[0],
            "North America Remote Duel YCS December 2025")


class TestANameThatFitsEveryEvent(unittest.TestCase):
    """A candidate made of nothing but words for a kind of coverage."""

    def test_pairings_is_not_an_event(self):
        from naming import says_only_what_it_is
        for no in ("Pairings", "Final Standings", "Top 8 Pairings", "Day 1 Wrap-Up"):
            self.assertTrue(says_only_what_it_is(no), no)

    def test_a_name_with_anything_of_its_own_is_kept(self):
        # Checked against all 140 names in the archive: this rejects exactly
        # one of them, and it is the one that is not a name.
        from naming import says_only_what_it_is
        for yes in ("YCS Montréal", "250th YCS", "Wcs 2010", "2016 World Championship",
                    "North America WCQ 2026", "TEAM YCS Las Vegas", "UDS Invitational Lima"):
            self.assertFalse(says_only_what_it_is(yes), yes)

    def test_a_weak_candidate_does_not_win_by_the_others_leaving(self):
        # YCS Charlotte has seven posts headed "Top Table Update" and five
        # headed "QQ". Dropping the first from the vote is right; dropping it
        # from the denominator too is not, and it let QQ clear a share it
        # should have failed. Five events reached the site named QQ.
        from naming import event_name
        # The real vote, counted off the event's 53 posts: sixteen titles use
        # the convention, and QQ holds five of them. Five is under the 40%
        # share; it only passed when the other eleven stopped counting.
        titles = (["Top Table Update: Round %d" % n for n in range(1, 8)]
                  + ["Day 1: Morning", "Day 1: Evening", "Day 2: Morning", "Day 2: Evening"]
                  + ["QQ: Something", "QQ: Else", "QQ: Again", "QQ: More", "QQ: Still"]
                  + ["Welcome to YCS Charlotte!"]
                  + ["YCS Charlotte Round %d Pairings" % n for n in range(1, 11)])
        # Not QQ, which is the whole of it. On the real event the fallback
        # path then reads "YCS Charlotte" off the other thirty-seven titles;
        # this fixture carries the vote, not the whole post list.
        self.assertNotEqual(event_name(titles, "Fallback"), "QQ")

    def test_a_prefix_that_says_only_its_kind_still_counts_as_a_vote_cast(self):
        # The denominator is titles that used the convention, which these did.
        from naming import event_name
        # Nine "Pairings:" titles and two "Real Event:" ones. Two out of eleven
        # is not a share, and the answer is not "Real Event" on that evidence.
        titles = ["Pairings: Round %d" % n for n in range(1, 10)] + \
                 ["Real Event: One", "Real Event: Two"]
        self.assertNotEqual(event_name(titles, "Fallback"), "Real Event")

    def test_such_a_prefix_never_wins_the_vote(self):
        from naming import event_name
        # Six posts headed "Pairings: ..." and the event's own name written
        # bare, which the convention cannot see. Pairings won, and the event
        # reached the front page, the feed and the winners table called that.
        titles = ["Pairings: Round 2", "Pairings: Round 3", "Pairings: Top 4",
                  "Pairings: Quarterfinals!", "Pairings: World Championship Finals!",
                  "2016 World Championship", "2016 World Championship"]
        self.assertNotEqual(event_name(titles, "Fallback"), "Pairings")


class TestEventPrefix(unittest.TestCase):
    """The event's name is the front of a post's slug, up to the post's subject."""

    def test_the_name_stops_at_the_first_word_about_the_post(self):
        from index import event_prefix
        self.assertEqual(event_prefix("ycs-atlanta-round-1-pairings"), "ycs-atlanta")
        self.assertEqual(event_prefix("uds-invitational-lima-peru-standings-after-round-3"),
                         "uds-invitational-lima-peru")
        self.assertEqual(event_prefix("team-ycs-san-jose-costa-rica-standings-after-round-8"),
                         "team-ycs-san-jose-costa-rica")

    def test_coverage_that_names_only_its_subject_yields_nothing(self):
        # The older posts are slugged, and titled, for what they contain and
        # never for which tournament: "standings-after-round-3" is thirty of
        # them. Fetching the page does not help -- its <title> says the same.
        from index import event_prefix
        self.assertEqual(event_prefix("standings-after-round-3"), "")
        self.assertEqual(event_prefix("top-cut-will-be-top-32-and-standings-after-round-5"), "")

    def test_a_joining_word_is_part_of_the_name(self):
        # "in" and "the" were cut on once, and it cost an event: the two 250th
        # YCS held the same weekend both came back as "250th-ycs" and merged.
        from index import event_prefix
        self.assertEqual(event_prefix("250th-ycs-in-bogota-colombia-round-1-pairings"),
                         "250th-ycs-in-bogota-colombia")
        self.assertEqual(event_prefix("250th-ycs-in-los-angeles-round-3-pairings"),
                         "250th-ycs-in-los-angeles")


class TestEventDiscovery(unittest.TestCase):
    """Tournaments the blog filed under no event path at all.

    Two thirds of this blog's tournament coverage carries no event in its URL:
    2,560 rounds of pairings and standings, and something over a hundred
    tournaments, that nothing above this could see.
    """

    def assigned(self, *urls):
        rows = assign_events(parse_post_sitemap(urlset(*urls)))
        return {r["slug"]: (r["event"], r["event_confidence"]) for r in rows}

    @staticmethod
    def coverage(prefix, when, n=6):
        """One tournament's worth: enough rounds to clear the minimum."""
        return [(f"2017/ycs/{prefix}-round-{i}-pairings", when) for i in range(1, n + 1)] + \
               [(f"2017/ycs/{prefix}-standings-after-round-{i}", when) for i in range(1, n + 1)]

    def test_an_event_with_no_path_of_its_own_is_found(self):
        got = self.assigned(*self.coverage("ycs-atlanta", "2017-03-04"))
        self.assertEqual(got["ycs-atlanta-round-1-pairings"],
                         ("2017-ycs-atlanta", "discovered"))

    def test_two_tournaments_on_one_weekend_stay_apart(self):
        # YCS Atlanta and the UDS Invitational in Lima ran the same weekend in
        # March 2017. Dates alone put all forty-nine posts in one event.
        got = self.assigned(*self.coverage("ycs-atlanta", "2017-03-04"),
                            *self.coverage("uds-invitational-lima-peru", "2017-03-04"))
        self.assertEqual(got["ycs-atlanta-round-1-pairings"][0], "2017-ycs-atlanta")
        self.assertEqual(got["uds-invitational-lima-peru-round-1-pairings"][0],
                         "2017-uds-invitational-lima-peru")

    def test_one_name_used_every_year_is_split_by_the_dates(self):
        # "south-america-wcq" is five tournaments. Grouping on the name alone
        # would file 2018's rounds and 2024's as one event. WordPress keeps the
        # later slugs unique by suffixing the whole thing, which leaves the name
        # at the front identical -- so only the dates can tell these apart.
        got = self.assigned(
            *self.coverage("south-america-wcq", "2018-06-30"),
            *[(f"2017/ycs/south-america-wcq-round-{i}-pairings-2", "2024-06-29")
              for i in range(1, 7)],
            *[(f"2017/ycs/south-america-wcq-standings-after-round-{i}-2", "2024-06-29")
              for i in range(1, 7)])
        self.assertEqual(got["south-america-wcq-round-1-pairings"][0],
                         "2018-south-america-wcq")
        self.assertEqual(got["south-america-wcq-round-1-pairings-2"][0],
                         "2024-south-america-wcq")

    def test_posts_that_escaped_a_known_event_go_back_to_it(self):
        # Twenty-two rounds of the 2026 North America WCQ were slugged without
        # the event path the rest of it uses. They are that event's, not a
        # second tournament held in the same room on the same day.
        #
        # The two 200th YCS ran the same weekend in 2018, so the date rule
        # cannot place these -- two events fit and it says so rather than
        # guessing. Neither is a qualifier, so nothing but the name in the
        # slug separates them.
        got = self.assigned(
            ("2018/ycs/2018-09-200th-ycs-columbus-oh/200th-ycs-columbus-round-1-pairings", "2018-09-22"),
            ("2018/ycs/2018-09-200th-ycs-columbus-oh/200th-ycs-columbus-standings-after-round-1", "2018-09-22"),
            ("2018/ycs/2018-09-200th-ycs-mexico-city-mexico/200th-ycs-mexico-round-1-pairings", "2018-09-22"),
            ("2018/ycs/2018-09-200th-ycs-mexico-city-mexico/200th-ycs-mexico-standings-after-round-1", "2018-09-22"),
            *[(f"2018/ycs/200th-ycs-columbus-round-{i}-pairings", "2018-09-23")
              for i in range(2, 8)],
            *[(f"2018/ycs/200th-ycs-columbus-standings-after-round-{i}", "2018-09-23")
              for i in range(2, 8)])
        self.assertEqual(got["200th-ycs-columbus-round-2-pairings"],
                         ("2018-09-200th-ycs-columbus-oh", "prefix"))

    def test_a_name_that_two_events_could_answer_to_is_left_alone(self):
        # "wcq" is in the index on its own, and in 2018 the North and South
        # America qualifiers ran the same week. Either could host it, so
        # neither does: this is the ambiguity rule the date matching already
        # applies, and the answer is still to report rather than guess.
        got = self.assigned(
            ("2018/championships/2018-north-america-wcq/nawcq-round-1-pairings", "2018-06-30"),
            ("2018/championships/2018-north-america-wcq/nawcq-standings-after-round-1", "2018-06-30"),
            ("2018/championships/2018-south-america-wcq/sawcq-round-1-pairings", "2018-06-30"),
            ("2018/championships/2018-south-america-wcq/sawcq-standings-after-round-1", "2018-06-30"),
            *[(f"2018/championships/wcq-round-{i}-pairings", "2018-07-01") for i in range(2, 6)],
            *[(f"2018/championships/wcq-standings-after-round-{i}", "2018-07-01")
              for i in range(2, 6)])
        self.assertIsNone(got["wcq-round-2-pairings"][0])

    def test_a_post_that_is_only_a_number_names_nobody(self):
        # WordPress falls back to the post id when a post is published
        # untitled, and thirty of those are in the index. Matching on the words
        # in a name is a subset test, and the empty set is a subset of
        # everything -- so each of them matched every event there was.
        #
        # It may still be attached by its date, which is a different rule with
        # corroboration behind it. What it must never do is match on a name it
        # does not have.
        from index import _names_the_same
        self.assertFalse(_names_the_same("55642", "2017-ycs-atlanta"))
        self.assertFalse(_names_the_same("", "2017-ycs-atlanta"))
        self.assertTrue(_names_the_same("ycs-atlanta", "2017-ycs-atlanta"))

    def test_a_handful_of_posts_is_not_a_tournament(self):
        # Two strays are an event's posts that got away, not coverage of a
        # tournament nobody filed. Below the minimum they stay unassigned
        # rather than becoming an event of two rounds in the reader's list.
        got = self.assigned(("2017/ycs/ycs-portland-round-1-pairings", "2019-08-24"),
                            ("2017/ycs/ycs-portland-standings-after-round-1", "2019-08-24"))
        self.assertIsNone(got["ycs-portland-round-1-pairings"][0])

    def test_an_announcement_with_no_rounds_is_not_an_event(self):
        # A name is looked for in rounds, never in the talk around them. Eight
        # posts welcoming everyone to a tournament are not coverage of one, and
        # taking them for it would put an event with no rounds in the archive
        # and in the reader's list.
        got = self.assigned(*[(f"2017/ycs/ycs-atlanta-welcome-{i}", "2017-03-04")
                              for i in range(8)])
        self.assertIsNone(got["ycs-atlanta-welcome-0"][0])

    def test_the_rest_of_a_discovered_events_coverage_joins_it(self):
        # Its feature matches and deck breakdowns, found the same way: on their
        # own name and their own date, not on being adjacent to a round.
        got = self.assigned(*self.coverage("ycs-atlanta", "2017-03-04"),
                            ("2017/ycs/ycs-atlanta-feature-match-a-versus-b", "2017-03-05"),
                            ("2017/ycs/ycs-atlanta-top-8-deck-breakdown", "2017-03-05"))
        self.assertEqual(got["ycs-atlanta-feature-match-a-versus-b"][0], "2017-ycs-atlanta")
        self.assertEqual(got["ycs-atlanta-top-8-deck-breakdown"][0], "2017-ycs-atlanta")

    def test_a_post_from_another_year_does_not_join_on_the_name(self):
        # The name matching is not enough on its own: "ycs-atlanta" is three
        # tournaments, so the dates have to agree as well.
        got = self.assigned(*self.coverage("ycs-atlanta", "2017-03-04"),
                            ("2014/ycs/ycs-atlanta-feature-match-a-versus-b", "2014-02-01"))
        self.assertIsNone(got["ycs-atlanta-feature-match-a-versus-b"][0])

    def test_an_unrelated_post_published_that_weekend_is_left_alone(self):
        # The name has to match as well as the date. This is the rule that
        # keeps product news out of an event's coverage, applied here too.
        got = self.assigned(*self.coverage("ycs-atlanta", "2017-03-04"),
                            ("2017/news-updates/introducing-the-new-structure-deck", "2017-03-05"))
        self.assertIsNone(got["introducing-the-new-structure-deck"][0])

    def test_nothing_already_identified_is_revisited(self):
        # Discovery runs last and only on what is left, so an event the path or
        # the dates settled can gain posts here but never lose or exchange one.
        got = self.assigned(
            ("2026/ycs/2026-08-quebec/ycs-montreal-round-1-pairings", "2026-08-15"),
            ("2026/ycs/2026-08-quebec/ycs-montreal-standings-after-round-1", "2026-08-15"))
        self.assertEqual(got["ycs-montreal-round-1-pairings"], ("2026-08-quebec", "path"))


class TestOneQualifierWrittenTwoWays(unittest.TestCase):
    """The 2024 North America WCQ published its Swiss rounds as
    "north-america-wcq-round-10-pairings" and its top cut as
    "nawcq-top-16-pairings-and-deck-types"."""

    def assigned(self, *urls):
        rows = assign_events(parse_post_sitemap(urlset(*urls)))
        return {r["slug"]: r["event"] for r in rows}

    @staticmethod
    def swiss(when):
        return [(f"2024/championships/north-america-wcq-round-{i}-pairings", when)
                for i in range(1, 7)] + \
               [(f"2024/championships/north-america-wcq-standings-after-round-{i}", when)
                for i in range(1, 7)]

    @staticmethod
    def cut(when):
        return [(f"2024/championships/nawcq-top-{i}-pairings-and-deck-types", when)
                for i in (64, 32, 16, 8, 4, 2)] + \
               [(f"2024/championships/nawcq-standings-after-round-{i}", when)
                for i in range(7, 13)]

    def test_the_two_halves_are_one_tournament(self):
        got = self.assigned(*self.swiss("2024-07-20"), *self.cut("2024-07-22"))
        self.assertEqual(got["nawcq-top-16-pairings-and-deck-types"],
                         got["north-america-wcq-round-1-pairings"])

    def test_the_fuller_name_is_the_one_kept(self):
        # The abbreviation turns up on the cut, and the cut is the short half.
        got = self.assigned(*self.swiss("2024-07-20"), *self.cut("2024-07-22"))
        self.assertEqual(got["nawcq-top-16-pairings-and-deck-types"],
                         "2024-north-america-wcq")

    def test_two_years_of_it_are_still_two_tournaments(self):
        # Reading both names as one qualifier must not reach across the dates:
        # there is a North America WCQ every year.
        got = self.assigned(*self.swiss("2024-07-20"), *self.cut("2025-07-12"))
        self.assertNotEqual(got["nawcq-top-16-pairings-and-deck-types"],
                            got["north-america-wcq-round-1-pairings"])

    def test_two_clusters_months_apart_are_not_merged_on_the_name(self):
        # The year is in the name, so it separates most of these on its own --
        # but not two clusters within one year. A post re-edited months later
        # reads as a second cluster of the same qualifier, and merging them
        # would give the event a window running from March to July.
        got = self.assigned(*self.swiss("2024-03-16"), *self.cut("2024-07-22"))
        self.assertNotEqual(got["nawcq-top-16-pairings-and-deck-types"],
                            got["north-america-wcq-round-1-pairings"])

    def test_the_rest_of_the_cuts_coverage_joins_by_the_name_it_used(self):
        # A deck breakdown slugged "nawcq-..." belongs to an event now called
        # "2024-north-america-wcq", which does not contain the word. The merge
        # keeps both names so that this can still be found.
        got = self.assigned(*self.swiss("2024-07-20"), *self.cut("2024-07-22"),
                            ("2024/championships/nawcq-top-64-deck-breakdown", "2024-07-22"))
        self.assertEqual(got["nawcq-top-64-deck-breakdown"], "2024-north-america-wcq")

    def test_the_genesys_championship_alongside_is_not_swept_in(self):
        # A date is not the test -- this ran the same weekend and is a separate
        # tournament, which is why merging is only ever on the qualifier's name.
        got = self.assigned(
            *self.swiss("2024-07-20"),
            *[(f"2024/championships/north-america-genesys-championship-round-{i}-pairings",
               "2024-07-20") for i in range(1, 7)],
            *[(f"2024/championships/north-america-genesys-championship-standings-after-round-{i}",
               "2024-07-20") for i in range(1, 7)])
        self.assertNotEqual(got["north-america-genesys-championship-round-1-pairings"],
                            got["north-america-wcq-round-1-pairings"])


class TestADiscoveredEventCanBeDated(unittest.TestCase):
    """An event nobody filed under a path could only ever be given a post that
    carried its name.

    Everything written about one in a sentence fell through -- the post
    announcing its winner, its feature matches, its table of contents. The
    2023 North America Remote Duel YCS has a finals write-up naming its
    champion in so many words, under the slug
    "finals-feature-match-steven-santoli-vs-liam-mac-oscair": no name in it to
    match, and no window to fall inside either.
    """

    def assigned(self, *urls):
        rows = assign_events(parse_post_sitemap(urlset(*urls)))
        return {r["slug"]: (r["event"], r["event_confidence"]) for r in rows}

    @staticmethod
    def coverage(prefix, when, category="ycs", n=6):
        return [(f"2023/{category}/{prefix}-round-{i}-pairings", when) for i in range(1, n + 1)] + \
               [(f"2023/{category}/{prefix}-standings-after-round-{i}", when) for i in range(1, n + 1)]

    def test_a_sibling_in_the_events_own_category_joins_it(self):
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/finals-feature-match-steven-santoli-vs-liam-mac-oscair", "2023-06-25"))
        self.assertEqual(got["finals-feature-match-steven-santoli-vs-liam-mac-oscair"],
                         ("2023-north-america-remote-duel-ycs", "discovered+date"))

    def test_a_round_the_event_already_holds_is_not_dated_in(self):
        # A date says a piece of writing belongs to the weekend. It does not say
        # whose bracket a table is, and a discovered event's vocabulary is its
        # own slugs -- which is to say "pairings", "top", "round". A slug built
        # from nothing else matches every event that ran that weekend.
        #
        # YCS Chicago published its Top 32 under its own name, and something
        # else that weekend published "top-32-pairings-6", naming nobody. Dated
        # in, it was the fuller of the two tables and won -- and then fourteen
        # of the sixteen Duelists in Chicago's own Top 16 had, on the record,
        # never played in its Top 32.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/north-america-remote-duel-ycs-top-32-pairings", "2023-06-24"),
            ("2023/ycs/top-32-pairings-6", "2023-06-25"))
        self.assertEqual(got["north-america-remote-duel-ycs-top-32-pairings"][1],
                         "discovered")
        self.assertIsNone(got["top-32-pairings-6"][0])

    def test_a_word_many_events_use_names_none_of_them(self):
        # The rule reads a word in proportion to how few events use it. Four
        # events calling themselves a Cup means "cup" identifies no event at
        # all, and a round whose slug happens to carry it must not be refused
        # on that -- which is what keeps YCS Minneapolis's "standings-after-
        # round-4-4" attached to the event that actually played it.
        got = self.assigned(
            *self.coverage("alpha-open", "2023-06-24"),
            *self.coverage("beta-cup", "2023-02-04"),
            *self.coverage("gamma-cup", "2023-03-04"),
            *self.coverage("delta-cup", "2023-04-08"),
            *self.coverage("epsilon-cup", "2023-05-06"),
            ("2023/ycs/cup-standings-after-round-9", "2023-06-25"))
        self.assertEqual(got["cup-standings-after-round-9"],
                         ("2023-alpha-open", "discovered+date"))

    def test_a_round_naming_another_event_is_that_events(self):
        # A category is enough for the prose this rule is mostly for, and every
        # YCS post is filed under "ycs". It is nowhere near enough for a table:
        # "ycs-philadelphia-top-64-pairings-and-deck-types" was vouched for by
        # its category and became YCS Cancun's Top 64 -- an event that never
        # played one, arriving with sixty-three Duelists in a round of
        # sixty-four because the blog had printed one of Philadelphia's twice.
        # Philadelphia ran months earlier, so its own window does not hold this
        # post and only the other event's does. Nothing but the name says whose
        # table it is.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            *self.coverage("ycs-philadelphia", "2023-01-14"),
            ("2023/ycs/ycs-philadelphia-top-64-pairings", "2023-06-25"))
        self.assertIsNone(got["ycs-philadelphia-top-64-pairings"][0])

    def test_a_round_the_event_has_no_other_way_to_get_is_kept(self):
        # Refusing every dated round was the first fix and it was too blunt.
        # YCS Minneapolis 2016 is named by none of its own standings --
        # "standings-after-round-4-4", "standings-after-the-swiss-rounds" --
        # and refusing them took all six, which left the event with no
        # standings at all and dropped it below the coverage worth building.
        # A generic slug is how the blog wrote a round, not evidence that the
        # round belongs to somebody else.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/top-32-pairings-6", "2023-06-25"))
        self.assertEqual(got["top-32-pairings-6"],
                         ("2023-north-america-remote-duel-ycs", "discovered+date"))

    def test_the_writing_around_an_event_still_joins_it(self):
        # The rule is narrow on purpose: it holds back rounds, not writing.
        # Everything this class exists for -- the winner announcement, the
        # feature matches, the table of contents -- still arrives by date.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/and-the-winner-is-4", "2023-06-25"))
        self.assertEqual(got["and-the-winner-is-4"][0],
                         "2023-north-america-remote-duel-ycs")

    def test_a_post_from_another_week_is_not_swept_in(self):
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/finals-feature-match-a-vs-b", "2023-09-01"))
        self.assertIsNone(got["finals-feature-match-a-vs-b"][0])

    def test_a_post_from_a_category_the_event_does_not_use_must_name_it(self):
        # The rule that keeps product news out of an event's coverage, applied
        # here too: three Legendary Arc-V announcements were published during
        # YCS Montreal and shown as its coverage.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/news-updates/introducing-the-new-structure-deck", "2023-06-25"),
            ("2023/news-updates/north-america-remote-duel-ycs-what-to-expect", "2023-06-25"))
        self.assertIsNone(got["introducing-the-new-structure-deck"][0])
        self.assertEqual(got["north-america-remote-duel-ycs-what-to-expect"][0],
                         "2023-north-america-remote-duel-ycs")

    def test_two_discovered_events_that_weekend_claim_neither(self):
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            *self.coverage("south-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/finals-feature-match-a-vs-b", "2023-06-25"))
        self.assertIsNone(got["finals-feature-match-a-vs-b"][0])

    def test_one_misfiled_post_does_not_widen_the_net(self):
        # A category one post out of thirty-four sits in is not a category the
        # event uses. One WCQ post filed under /2023/ycs/ put "ycs" on the 2023
        # South America WCQ and made every YCS post that weekend a candidate.
        # The misfiled post has to be one the event actually takes, or it never
        # reaches the category set and the fixture proves nothing: this one
        # carries the event's name, so it joins on that and brings "ycs" with
        # it.
        got = self.assigned(
            *self.coverage("south-america-wcq", "2023-06-24", category="championships"),
            ("2023/ycs/south-america-wcq-round-7-pairings", "2023-06-24"),
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/finals-feature-match-steven-santoli-vs-liam-mac-oscair", "2023-06-25"))
        self.assertEqual(got["south-america-wcq-round-7-pairings"][0], "2023-south-america-wcq",
                         "the misfiled post is the event's, whatever section it sits in")
        self.assertEqual(got["finals-feature-match-steven-santoli-vs-liam-mac-oscair"][0],
                         "2023-north-america-remote-duel-ycs")

    def test_a_side_event_is_not_attached_by_its_date(self):
        # Every YCS runs a dozen tournaments beside the main one, and a date
        # cannot tell them apart. "dd-wcq-ca-standings-after-round-1" is the
        # Dragon Duel's table and would be read as the main event's.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/dragon-duel-standings-after-round-1", "2023-06-25"),
            ("2023/ycs/sunday-speed-duel-attack-of-the-giant-card-finals-feature-match",
             "2023-06-25"))
        self.assertIsNone(got["dragon-duel-standings-after-round-1"][0])
        self.assertIsNone(
            got["sunday-speed-duel-attack-of-the-giant-card-finals-feature-match"][0])

    def test_the_main_events_own_posts_are_unaffected(self):
        # The rule is scoped to the date path, so a post of the event's that
        # happens to sit next to the side events still arrives.
        got = self.assigned(
            *self.coverage("north-america-remote-duel-ycs", "2023-06-24"),
            ("2023/ycs/dragon-duel-standings-after-round-1", "2023-06-25"),
            ("2023/ycs/what-a-weekend-it-has-been", "2023-06-25"))
        self.assertIsNone(got["dragon-duel-standings-after-round-1"][0])
        self.assertEqual(got["what-a-weekend-it-has-been"][0],
                         "2023-north-america-remote-duel-ycs")

    def test_a_small_event_keeps_the_categories_it_has(self):
        # Every category of a short event is held by one post, and stripping
        # them all would make it unreachable.
        from index import _discovered_profiles
        recs = [{"event": "e", "event_confidence": "discovered", "lastmod": "2023-06-24",
                 "category": "ycs", "slug": "e-round-1-pairings"}]
        self.assertEqual(_discovered_profiles(recs)["e"].categories, {"ycs"})


class TestDiscoveredEventsAreBuildable(unittest.TestCase):

    def test_a_discovered_event_gets_its_end_date_from_its_own_posts(self):
        # events_by_recency reads that date off the event's profile, and a
        # discovered event has none: a profile is built from posts carrying the
        # slug in the path, and these carry no path at all.
        from run import events_by_recency
        entries = parse_post_sitemap(urlset(
            *[(f"2017/ycs/ycs-atlanta-round-{i}-pairings", "2017-03-04") for i in range(1, 7)],
            *[(f"2017/ycs/ycs-atlanta-standings-after-round-{i}", "2017-03-05")
              for i in range(1, 7)]))
        ranked = dict((slug, ended) for slug, _, ended in events_by_recency(entries))
        self.assertEqual(ranked["2017-ycs-atlanta"], "2017-03-05")


class TestDateAttachmentIsCorroborated(unittest.TestCase):
    """A shared date makes a post a candidate, not coverage.

    Product news published during YCS Montreal's week was attached to it and
    shown as coverage: three Legendary Arc-V deck announcements and an item
    about New York Comic Con.
    """

    OWN = [(f"2026/ycs/2026-08-quebec/ycs-montreal-round-{i}-pairings-advanced-format",
            f"2026-08-1{i}") for i in (4, 5, 6)]

    def assigned(self, *paths):
        rows = assign_events(parse_post_sitemap(urlset(
            *self.OWN, *((p, "2026-08-15") for p in paths))))
        return {r["slug"]: r["event"] for r in rows}

    def test_a_sibling_in_the_events_own_category_is_taken_at_its_word(self):
        # A real Montreal post, and one that names nothing: no "ycs", no
        # "montreal", no round. The category is the only thing vouching for it,
        # so a rule that asked every post to say the event's name would throw
        # this away along with the product news.
        got = self.assigned("2026/ycs/qq-which-tech-cards-are-you-using-this-weekend-3")
        self.assertEqual(got["qq-which-tech-cards-are-you-using-this-weekend-3"],
                         "2026-08-quebec")

    def test_a_word_one_post_happens_to_use_does_not_name_the_event(self):
        # Vocabulary has to be shared across the coverage, not scraped from any
        # single post. Montreal ran a Genesys tournament, so "genesys" appears
        # in some of its slugs -- but the blog's standing Genesys points updates
        # are not YCS coverage, and a threshold of zero would let every one of
        # them in.
        rows = assign_events(parse_post_sitemap(urlset(
            ("2026/ycs/2026-08-quebec/ycs-montreal-round-4-pairings-advanced-format", "2026-08-14"),
            ("2026/ycs/2026-08-quebec/ycs-montreal-round-5-pairings-advanced-format", "2026-08-15"),
            ("2026/ycs/2026-08-quebec/ycs-montreal-round-4-pairings-genesys-format", "2026-08-16"),
            ("2026/news-updates/genesys-points-update-august", "2026-08-15"))))
        got = {r["slug"]: r["event"] for r in rows}
        self.assertIsNone(got["genesys-points-update-august"])

    def test_product_news_from_another_category_is_not_coverage(self):
        got = self.assigned("2026/news-updates/legendary-arc-v-decks-lunalight")
        self.assertIsNone(got["legendary-arc-v-decks-lunalight"])

    def test_another_events_announcement_is_not_this_events_coverage(self):
        got = self.assigned("2026/event-information/new-york-comic-con-2026-information")
        self.assertIsNone(got["new-york-comic-con-2026-information"])

    def test_a_foreign_category_post_that_names_the_event_is_kept(self):
        # The rule must not throw out the real thing to catch the fakes. This
        # sits in the same category and the same week as the Comic Con post.
        got = self.assigned("2026/event-information/ycs-montreal-quebec-2026-main-event-information")
        self.assertEqual(got["ycs-montreal-quebec-2026-main-event-information"],
                         "2026-08-quebec")

    def test_the_event_names_itself_from_its_own_coverage(self):
        # No hardcoded vocabulary: the terms come from the event's own slugs, so
        # an event nobody has ever named still works.
        from index import event_profiles
        entries = parse_post_sitemap(urlset(
            *[(f"2031/ycs/2031-06-atlantis/ycs-atlantis-round-{i}-pairings", f"2031-06-0{i}")
              for i in (1, 2, 3)]))
        self.assertIn("atlantis", event_profiles(entries)["2031-06-atlantis"].terms)


def _page(title, header, rows):
    """A coverage post as the blog writes one: a <title> and one table."""
    cells = lambda r: "".join(f"<td>{c}</td>" for c in r)
    return (f"<html><head><title>{title}</title></head><body><table><tbody>"
            f"<tr>{cells(header)}</tr>"
            + "".join(f"<tr>{cells(r)}</tr>" for r in rows)
            + "</tbody></table></body></html>")


def _src(url, title, header, rows, posted="12:00"):
    from build import Source
    return Source(url, parse_post(_page(title, header, rows), url), posted)


PAIR_HEAD = ["Table", "P1 First Name", "P1 Last Name", "vs.",
             "P2 First Name", "P2 Last Name"]


class TestABiographyIsNotASideEvent(unittest.TestCase):
    """A side event named in an aside is about the Duelist, not the post.

    The 2026 North America WCQ's winner announcement opens by saying its
    winner is a former Dragon Duel World Champion, and the event lost its
    champion to that sentence.
    """

    NAWCQ = ("2077 Duelists competed in the 2026 North America World Championship "
             "Qualifier, and one Duelist \u2013 a former Dragon Duel World Champion "
             "and former MASTER DUEL World Champion \u2013 emerged on top! Ryan Yu "
             "from Ontario, Canada used his Sky Striker Deck to go undefeated.")

    def test_a_title_held_in_an_aside_does_not_veto_the_post(self):
        from winners import announces_a_winner
        self.assertTrue(announces_a_winner("And the Winner of the 2026 NAWCQ Is\u2026",
                                           self.NAWCQ))

    def test_a_bracketed_aside_counts_too(self):
        from winners import announces_a_winner
        self.assertTrue(announces_a_winner(
            "And the Winner Is\u2026",
            "One Duelist (a former Dragon Duel champion) came out on top!"))

    def test_a_post_actually_about_the_side_event_is_still_refused(self):
        # The rule must not throw out what it was written to catch.
        from winners import announces_a_winner
        self.assertFalse(announces_a_winner(
            "And the Winner Is\u2026", "The Dragon Duel Championship has a winner!"))

    def test_a_side_event_in_the_title_is_still_refused(self):
        from winners import announces_a_winner
        self.assertFalse(announces_a_winner("And the Dragon Duel Winner Is\u2026",
                                            "Somebody won."))

    def test_the_champion_is_read_out_of_the_post(self):
        from winners import champion
        got = champion(["Charley Ray Futch III", "Ryan Linus Yu"],
                       [{"title": "And the Winner of the 2026 NAWCQ Is\u2026",
                         "text": self.NAWCQ, "kind": "result"}])
        self.assertEqual(got, "Ryan Linus Yu")


class TestTheHeadersTheBlogActuallyWrites(unittest.TestCase):
    """A table the reader did not recognise is a round nobody has.

    149 round posts were unread and every one of them held a real table. YCS
    Niagara Falls 2022 heads its pairings "Table | Player 1 | Player 2", so
    every pairings post on it parsed to nothing -- the standings came through,
    the whole bracket did not, and with no cut there were no candidates to ask
    who had won it. The event sat in the archive looking present and hollow.
    """

    def table(self, header, *rows):
        cells = lambda r: "".join(f"<td>{c}</td>" for c in r)
        return parse_post("<html><head><title>Round 4 Pairings</title></head><body>"
                          f"<table><tbody><tr>{cells(header)}</tr>"
                          + "".join(f"<tr>{cells(r)}</tr>" for r in rows)
                          + "</tbody></table></body></html>")

    def test_player_1_and_player_2(self):
        t = self.table(["Table", "Player 1", "Player 2"],
                       ["1", "Ann Alpha", "Bo Beta"]).table
        self.assertEqual(t.kind, "pairings")
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["name"]),
                         ("Ann Alpha", "Bo Beta"))
        self.assertEqual(t.rows[0]["table"], 1)

    def test_a_blank_column_divides_the_sides(self):
        # "Table | Player 1 |  | Player 2" -- the same separator drawn rather
        # than written. Splitting the rest evenly put the blank on the right.
        t = self.table(["Table", "Player 1", "", "Player 2"],
                       ["1", "Ann Alpha", "", "Bo Beta"]).table
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["name"]),
                         ("Ann Alpha", "Bo Beta"))

    def test_a_deck_on_each_side(self):
        t = self.table(["Table", "Player 1", "Deck Type", "Player 2", "Deck Type"],
                       ["1", "Ann Alpha", "Ryzeal", "Bo Beta", "Maliss"]).table
        self.assertEqual((t.rows[0]["a"]["deck"], t.rows[0]["b"]["deck"]),
                         ("Ryzeal", "Maliss"))

    def test_a_table_with_no_table_number(self):
        # The first column is the first Duelist, and reading it as a table
        # number dropped that side of every match.
        t = self.table(["Player 1", "vs.", "Player 2"],
                       ["Ann Alpha", "vs.", "Bo Beta"]).table
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["name"]),
                         ("Ann Alpha", "Bo Beta"))
        self.assertIsNone(t.rows[0]["table"])

    def test_names_with_no_heading_of_their_own(self):
        t = self.table(["Name", "Deck", "", "Name", "Deck"],
                       ["Ann Alpha", "Ryzeal", "", "Bo Beta", "Maliss"]).table
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["deck"]),
                         ("Ann Alpha", "Maliss"))

    def test_standings_whose_name_column_is_unheaded(self):
        # "Rank |  | Points" is how nine of them arrive. The points say what
        # the table is where the missing heading cannot.
        html = ("<html><head><title>Standings After Round 4</title></head><body>"
                "<table><tbody><tr><td>Rank</td><td></td><td>Points</td></tr>"
                "<tr><td>1</td><td>Ann Alpha</td><td>12</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(t.kind, "standings")
        self.assertEqual((t.rows[0]["name"], t.rows[0]["points"]), ("Ann Alpha", 12))

    def test_a_team_row_narrower_than_its_table(self):
        # TEAM YCS Las Vegas heads its Top 8 with five columns and announces
        # each team match with four. The length check dropped those rows, so
        # every duel became a match of its own and the round reported three
        # Duelists a side where the Top 16 reported one -- and the event was
        # rejected for disagreeing with itself.
        html = ("<html><head><title>Top 8 Pairings</title></head><body><table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Deck Type</td>"
                "<td>Player 2</td><td>Deck Type</td></tr>"
                "<tr><td>Team</td><td>Alpha Squad</td><td>vs.</td><td>Beta Crew</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>Ryzeal</td><td>Bo B.</td><td>Maliss</td></tr>"
                "<tr><td>2</td><td>Cy C.</td><td>Ryzeal</td><td>Di D.</td><td>Maliss</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(len(t.rows), 1, "one team match, not two singles")
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["name"]),
                         ("Alpha Squad", "Beta Crew"))
        self.assertEqual(len(t.rows[0]["duels"]), 2)

    def test_a_team_keeps_a_name_that_looks_like_a_region_code(self):
        # normalise_name strips a two- or three-letter all-caps token as a
        # region code, which is right for a Duelist -- "Philip DEU" -- and
        # wrong for a team. TEAM YCS Las Vegas round 6 pairs "Team PWP" with
        # "Team VCG"; both came back as a team called "Team", so the match was
        # a team playing itself and the event left the archive.
        html = ("<html><head><title>Round 6 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Team 1</td><td>Team 2</td></tr>"
                "<tr><td>Team</td><td>Team PWP</td><td>Team VCG</td></tr>"
                "<tr><td>1</td><td>Ann Alpha</td><td>Bo Beta</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertEqual((row["a"]["name"], row["b"]["name"]), ("Team PWP", "Team VCG"))
        self.assertNotEqual(row["a"]["name"], row["b"]["name"],
                            "a team does not play itself")

    def test_the_other_team_row_shape_too(self):
        # The same announcement written "Team | A | Team | B" rather than with
        # a "vs." in the middle.
        html = ("<html><head><title>Top 16 Pairings</title></head><body><table><tbody>"
                "<tr><td>Table</td><td>Duelist 1</td><td>vs.</td><td>Duelist 2</td></tr>"
                "<tr><td>Team</td><td>Alpha Squad</td><td>Team</td><td>Beta Crew</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs.</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual((t.rows[0]["a"]["name"], t.rows[0]["b"]["name"]),
                         ("Alpha Squad", "Beta Crew"))
        self.assertEqual(len(t.rows[0]["duels"]), 1)

    def test_one_round_published_as_several_tables(self):
        # The 2017 UDS Invitational Trinidad and Tobago wrote its Top 4 as two
        # tables of one match each. Reading only the first gave a Top 4 with
        # one match in it, which does not divide four Duelists into equal
        # sides -- so the event failed the coherence check and left the
        # archive after having been in it for eight builds.
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann Alpha</td><td>Bo Beta</td></tr>"
                "</tbody></table>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Player 2</td></tr>"
                "<tr><td>2</td><td>Cy Gamma</td><td>Di Delta</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(len(t.rows), 2, "both tables are the one round")
        self.assertEqual([r["a"]["name"] for r in t.rows], ["Ann Alpha", "Cy Gamma"])

    def test_a_second_table_with_its_own_header_stays_out(self):
        # Pages carry other tables -- a deck breakdown under the pairings is
        # the common one. Only a table repeating the pairings header is the
        # pairings continued; anything else has a header of its own and its
        # rows are not matches.
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann Alpha</td><td>Bo Beta</td></tr>"
                "</tbody></table>"
                "<table><tbody>"
                "<tr><td>Deck</td><td>Count</td></tr>"
                "<tr><td>Ryzeal</td><td>13</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(len(t.rows), 1, "the deck breakdown is not a match")

    def test_a_country_and_deck_written_beside_the_name(self):
        # The same event's Top 4 writes "Deonarine, Brandon Luke - Trinidad
        # and Tobago (SPYRAL)" where its Top 8 wrote "Deonarine, Brandon
        # Luke". Discarding the bracket threw the deck away and left the
        # country inside the name, so the two rounds disagreed about who had
        # played and the cut did not chain.
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Deonarine, Brandon Luke \u2013 Trinidad and Tobago (SPYRAL)</td>"
                "<td>Alpha, Ann \u2013 Mexico (Maliss)</td></tr>"
                "</tbody></table></body></html>")
        side = parse_post(html).table.rows[0]["a"]
        self.assertEqual(side["name"], "Brandon Luke Deonarine")
        self.assertEqual(side["region"], "Trinidad and Tobago")
        self.assertEqual(side["deck"], "SPYRAL")

    def test_a_bracket_in_front_of_the_name_is_not_an_annotation(self):
        # The 2016 World Championship writes the country first: "(Japan) Yada,
        # Makoto". Read as a trailing annotation, the name is whatever sits in
        # front of the bracket -- nothing -- so every Duelist in the event came
        # back nameless, every pairing was one nameless Duelist against
        # another, and the event was refused for seating a Duelist against
        # themselves. A leading bracket belongs to strip_region, which has
        # always removed it.
        html = ("<html><head><title>Round 3 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>(Japan) Yada, Makoto</td><td>vs.</td>"
                "<td>(Korea) Choi, Byung-Hyug</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertEqual(row["a"]["name"], "Makoto Yada")
        self.assertEqual(row["b"]["name"], "Byung-Hyug Choi")
        self.assertNotEqual(row["a"]["name"], row["b"]["name"])

    def test_a_standings_cell_is_annotated_too(self):
        # The 2016 South America WCQ writes its standings the same way as its
        # pairings, and only the pairings were read that way -- so the deck
        # stayed inside the name. reconcile_names counts words, so the
        # spelling carrying a deck was the longer one and won: eight clean
        # names were folded into their mangled spellings across all eleven
        # rounds, and the champion reached the winners page as "Joaquin -
        # Dracoslayer Performapals Rinaldi Petroni".
        html = ("<html><head><title>Standings After Round 4</title></head><body>"
                "<table><tbody>"
                "<tr><td>Rank</td><td>Player</td><td>Points</td></tr>"
                "<tr><td>1</td>"
                "<td>Rinaldi Petroni, Joaquin (Argentina) \u2013 Dracoslayer Performapals</td>"
                "<td>12</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertEqual(row["name"], "Joaquin Rinaldi Petroni")
        self.assertEqual(row["region"], "Argentina")

    def test_the_region_is_written_before_the_deck(self):
        # Which of the two the bracket holds cannot be read off the bracket:
        # it is the country in one of these and the deck in the other. What
        # does not vary is the order.
        from parse import read_annotation
        self.assertEqual(
            read_annotation("Quispe Llanco, Ariel (Bolivia) \u2013 Burning Abyss"),
            ("Quispe Llanco, Ariel", "Bolivia", "Burning Abyss"))
        self.assertEqual(
            read_annotation("Deonarine, Brandon Luke \u2013 Trinidad and Tobago (SPYRAL)"),
            ("Deonarine, Brandon Luke", "Trinidad and Tobago", "SPYRAL"))

    def test_a_dash_with_no_bracket_is_left_alone(self):
        # "Correa - Moreira, Jesus" is a compound surname, and 137 names in
        # the archive carry a country after a dash with no bracket at all.
        # Nothing here can tell those apart, so the dash is only read as an
        # annotation when a bracket says the cell is annotated.
        html = ("<html><head><title>Round 3 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Correa \u2013 Moreira, Jesus</td><td>Beta, Bo</td></tr>"
                "</tbody></table></body></html>")
        side = parse_post(html).table.rows[0]["a"]
        self.assertEqual(side["name"], "Jesus Correa \u2013 Moreira")
        self.assertIsNone(side["region"])

    def test_a_caption_above_the_header_is_read_past(self):
        # The 2013 World Championship heads each table with a row of its own,
        # and the header is underneath it. Read as the header, the caption
        # says nothing the classifier knows, so every round of that event was
        # dropped -- which is why it has never been in the archive.
        html = ("<html><head><title>Round 1 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td></td><td>Main World Championship</td><td></td><td>Round 1</td></tr>"
                "<tr><td>Table</td><td>Player 1</td><td>VS.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Alpha, Ann</td><td>VS.</td><td>Beta, Bo</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(t.kind, "pairings")
        self.assertEqual(len(t.rows), 1)
        self.assertEqual(t.rows[0]["a"]["name"], "Ann Alpha")

    def test_a_blank_row_ends_the_table(self):
        # The same event puts two tournaments in one table, separated by an
        # empty row: the Main World Championship, then the Dragon Duel World
        # Championship with a caption and header of its own. That caption has
        # two cells that are not noise, so it was read as the announcement of
        # a team match -- a fifth match in a Top 8, and the reason a singles
        # championship came back holding 38 Teams instead of 26 Duelists.
        html = ("<html><head><title>Top 8 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>VS.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Alpha, Ann</td><td>VS.</td><td>Beta, Bo</td></tr>"
                "<tr><td></td><td></td><td></td><td></td></tr>"
                "<tr><td></td><td>Dragon Duel World Championship</td><td></td><td>Top 8</td></tr>"
                "<tr><td>Table</td><td>Player 1</td><td>VS.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Gamma, Cy</td><td>VS.</td><td>Delta, Di</td></tr>"
                "</tbody></table></body></html>")
        rows = parse_post(html).table.rows
        self.assertEqual(len(rows), 1, "the Dragon Duel is not this tournament's round")
        self.assertNotIn("duels", rows[0], "a caption is not a team match")

    def test_a_table_with_no_header_at_all(self):
        # Eleven round posts open straight into their rows. What the columns
        # are is legible from the row itself -- a leading number, a "vs.", a
        # trailing number -- and naming them is enough, because everything
        # downstream reads columns by their names.
        html = ("<html><head><title>Round 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>1</td><td>Ann Alpha</td><td>vs.</td><td>Bo Beta</td></tr>"
                "<tr><td>2</td><td>Cy Gamma</td><td>vs.</td><td>Di Delta</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(t.kind, "pairings")
        self.assertEqual(len(t.rows), 2, "the first row is data, not a header")
        self.assertEqual(t.rows[0]["a"]["name"], "Ann Alpha")

    def test_a_headerless_ranking_is_standings(self):
        # Three cells ending in a number is a rank, a name and points.
        html = ("<html><head><title>Standings After Round 10</title></head><body>"
                "<table><tbody>"
                "<tr><td>1</td><td>Lopez Ramirez, Walter Eligio</td><td>30</td></tr>"
                "<tr><td>2</td><td>Santacruz Guzman, Alan Daniel</td><td>27</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(t.kind, "standings")
        self.assertEqual((t.rows[0]["rank"], t.rows[0]["points"]), (1, 30))
        self.assertEqual(t.rows[0]["name"], "Walter Eligio Lopez Ramirez")

    def test_a_winner_column_is_not_part_of_a_name(self):
        # The 2013 World Championship writes its rounds "Table | Player 1 |
        # VS. | Player 2 | | Winner", and everything after the divider was
        # read as Player 2 -- so the winner's name was appended to their
        # opponent's, and a Duelist called Weerapun Suebyoubol was filed as
        # "Weerapun Sergio Soldani Suebyoubol".
        html = ("<html><head><title>Round 1 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>VS.</td><td>Player 2</td>"
                "<td></td><td>Winner</td></tr>"
                "<tr><td>1</td><td>Soldani, Sergio</td><td>VS.</td>"
                "<td>Suebyoubol, Weerapun</td><td></td><td>Sergio Soldani (Italy)</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertEqual(row["b"]["name"], "Weerapun Suebyoubol")

    def test_the_team_written_on_every_duelist(self):
        # A Team YCS that does not announce the team in a row of its own
        # writes it on every Duelist: "La Revolucion: Lozano, Connor Joseph".
        # The colon is the team's and the comma is the Duelist's, and
        # normalise_name partitions on the comma -- so the team landed in the
        # middle of the name. 32,791 names across eleven events read that way.
        html = ("<html><head><title>Round 1 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>La Revolucion: Lozano, Connor Joseph</td><td>vs.</td>"
                "<td>The Mulchummies: Suangco, Adriane Earl Sun</td></tr>"
                "</tbody></table></body></html>")
        # The prefix names the team, so the row is the team's match and the
        # Duelist is the duel inside it.
        row = parse_post(html).table.rows[0]
        self.assertEqual((row["a"]["name"], row["b"]["name"]),
                         ("La Revolucion", "The Mulchummies"))
        duel = row["duels"][0]
        self.assertEqual(duel["a"]["name"], "Connor Joseph Lozano")
        self.assertEqual(duel["b"]["name"], "Adriane Earl Sun Suangco")

    def test_three_rows_of_one_team_pair_are_one_match(self):
        # TEAM YCS Las Vegas 2020 writes its cut with the team on every
        # Duelist and no announcement row at all. Read a row at a time, its
        # Top 4 of four teams held twenty-four Duelists and no team -- so the
        # event had no roster and could name no champion.
        rows = []
        for i, (t1, d1, t2, d2) in enumerate([
                ("Gonna Finish That", "Couch, Dominic", "Dino DNA", "Gamrat, Griffin"),
                ("Gonna Finish That", "Silverman, Stephen", "Dino DNA", "Cornell, Brendan"),
                ("Gonna Finish That", "Page, Scott", "Dino DNA", "Nappi, Ross"),
                ("Team Leon", "Gibbs, James", "Hi Kasey", "Jaffer, Michael")], 1):
            rows.append(f"<tr><td>{i}</td><td>{t1}: {d1}</td><td>vs.</td>"
                        f"<td>{t2}: {d2}</td></tr>")
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                + "".join(rows) + "</tbody></table></body></html>")
        got = parse_post(html).table.rows
        self.assertEqual(len(got), 2, "two team matches, not four singles")
        self.assertEqual((got[0]["a"]["name"], got[0]["b"]["name"]),
                         ("Gonna Finish That", "Dino DNA"))
        self.assertEqual(len(got[0]["duels"]), 3)
        self.assertEqual(got[0]["duels"][0]["a"]["name"], "Dominic Couch")
        self.assertEqual(len(got[1]["duels"]), 1, "the next pair of teams starts the next match")

    def test_a_team_does_not_play_itself(self):
        # TEAM YCS Las Vegas 2020 has two teams registered as "Brick Squad"
        # and pairs them against each other. Grouped on the prefix that is a
        # team playing itself, which is not a match -- so the prefix is not
        # evidence here and the rows stand as the duels they are.
        html = ("<html><head><title>Round 1 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                "<tr><td>235</td><td>Brick Squad: Fuentes Jr., Saul</td><td>vs.</td>"
                "<td>Brick Squad: Johnson, Jermaine</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertNotIn("duels", row, "a team cannot play itself")
        self.assertEqual(row["a"]["name"], "Saul Fuentes Jr.")

    def test_a_colon_with_no_name_after_it_is_left_alone(self):
        # The team prefix is only stripped where a comma follows, because the
        # comma is what says a Duelist's name comes next. "Lift Yourself
        # 1:58" is a team, and 58 is not a Duelist -- without the comma rule
        # this cell would come back named "58".
        html = ("<html><head><title>Round 1 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Lift Yourself 1:58</td><td>vs.</td><td>Beta, Bo</td></tr>"
                "</tbody></table></body></html>")
        row = parse_post(html).table.rows[0]
        self.assertEqual(row["a"]["name"], "Lift Yourself 1:58")

    def test_a_team_row_carrying_a_byte_order_mark(self):
        # TEAM YCS Las Vegas 2023 has a byte order mark inside the cells of
        # its finals table, and str.strip() does not remove one -- so "vs."
        # was not "vs." and the row announcing the two teams was not read as
        # announcing anything. Its three duels stood as three separate
        # matches, in an event whose every other cut round is a team match of
        # three, and the event was rejected for disagreeing with itself.
        html = ("<html><head><title>Pairings for the Finals</title></head><body>"
                "<table><tbody>"
                "<tr><td>Team</td><td>Back For Seconds\ufeff</td><td>vs.\ufeff</td>"
                "<td>2 World Champs and John\ufeff</td><td></td></tr>"
                "<tr><td>Table\ufeff</td><td>Player 1\ufeff</td><td>Deck Type\ufeff</td>"
                "<td>Player 2\ufeff</td><td>Deck Type</td></tr>"
                "<tr><td>1</td><td>Stephen S.</td><td>Kashtira</td>"
                "<td>John W.</td><td>Despia Branded</td></tr>"
                "<tr><td>2</td><td>Dominic C.</td><td>Kashtira</td>"
                "<td>Ryan Y.</td><td>Labrynth</td></tr>"
                "</tbody></table></body></html>")
        rows = parse_post(html).table.rows
        self.assertEqual(len(rows), 1, "one team match, not two singles")
        self.assertEqual((rows[0]["a"]["name"], rows[0]["b"]["name"]),
                         ("Back For Seconds", "2 World Champs and John"))
        self.assertEqual(len(rows[0]["duels"]), 2)

    def test_a_cut_round_of_ten_is_not_a_cut_round(self):
        # The 2016 North America WCQ heads a post "Pairings: Top 10" over 128
        # matches -- 256 Duelists, the field that came back for day two. Its
        # own first sentence says what it is, and round 10's pairings were
        # missing from the event entirely.
        from parse import parse_post
        html = ("<html><head><title>Pairings: Top 10</title></head><body>"
                "<div class=\"entry-content\">"
                "<p>Here are the Pairings for Round 10.</p></div></div>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        self.assertEqual(parse_post(html, "https://x/pairings-top-10/").round, 10)

    def test_a_bracket_that_could_exist_is_never_second_guessed(self):
        # Only an impossible label sends this to the prose. A Top 8 is a Top 8
        # even in a post that mentions another round in passing.
        from parse import parse_post
        html = ("<html><head><title>Pairings: Top 8</title></head><body>"
                "<div class=\"entry-content\">"
                "<p>These eight came through Round 12.</p></div></div>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        self.assertEqual(parse_post(html, "https://x/pairings-top-8/").round, "Top 8")

    def test_an_impossible_label_with_nothing_to_correct_it_stands(self):
        # The prose is asked, not obeyed. A post that says nothing useful keeps
        # what its heading said, and the checker refuses the event -- which is
        # a better answer than an invented one.
        from parse import parse_post
        html = ("<html><head><title>Pairings: Top 10</title></head><body>"
                "<div class=\"entry-content\">"
                "<p>The hall was packed today.</p></div></div>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        self.assertEqual(parse_post(html, "https://x/p/").round, "Top 10")

    def test_which_numbers_are_brackets(self):
        from parse import impossible_bracket
        for good in ("Top 4", "Top 8", "Top 16", "Top 32", "Top 64", "Top 256"):
            self.assertFalse(impossible_bracket(good), good)
        for bad in ("Top 3", "Top 10", "Top 1", "Top 0", "Top 100"):
            self.assertTrue(impossible_bracket(bad), bad)
        # Swiss rounds are numbers, and "Final" is neither.
        self.assertFalse(impossible_bracket(10))
        self.assertFalse(impossible_bracket("Final"))
        self.assertFalse(impossible_bracket(None))

    def test_the_title_names_the_round_and_the_slug_only_fills_in(self):
        # Konami types slugs by hand and sometimes types them wrong. The 2017
        # South America WCQ published "Pairings for Round 3" under the slug
        # south-america-wcq-pairings-for-top-3, and read together the slug won:
        # 137 matches of Swiss became a Top 3, which is not a bracket, and the
        # whole event was refused.
        from parse import parse_post
        html = ("<html><head><title>South America WCQ: Pairings for Round 3"
                "</title></head><body><table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        url = "https://x/2017/south-america-wcq-pairings-for-top-3/"
        self.assertEqual(parse_post(html, url).round, 3)

    def test_a_slug_still_names_the_round_when_the_title_does_not(self):
        # Most of the archive is read this way and has to stay that way.
        from parse import parse_post
        html = ("<html><head><title>South America WCQ Pairings</title></head>"
                "<body><table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        url = "https://x/2017/south-america-wcq-pairings-for-round-9/"
        self.assertEqual(parse_post(html, url).round, 9)

    def test_a_headerless_table_continues_the_one_above_it(self):
        # The 2017 South America WCQ publishes its Top 8 as four tables of one
        # match each, none of them headed. Reading only the first gave a Top 8
        # holding one match, which is not a bracket.
        from parse import parse_post
        one = ("<table><tbody><tr><td>{a}</td><td>vs</td><td>{b}</td></tr>"
               "</tbody></table>")
        html = ("<html><head><title>Top 8 Pairings</title></head><body>"
                + "".join(one.format(a=a, b=b) for a, b in
                          (("Ann A.", "Bo B."), ("Cy C.", "Di D."),
                           ("Ed E.", "Fi F."), ("Gus G.", "Hal H.")))
                + "</body></html>")
        rows = parse_post(html).table.rows
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["a"]["name"] for r in rows],
                         ["Ann A.", "Cy C.", "Ed E.", "Gus G."])

    def test_a_headerless_table_that_says_nothing_is_left_out(self):
        # A deck breakdown under a pairings table is not more pairings. Only a
        # row carrying a "vs." of its own is read as a continuation.
        from parse import parse_post
        html = ("<html><head><title>Top 8 Pairings</title></head><body>"
                "<table><tbody><tr><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "</tbody></table>"
                "<table><tbody><tr><td>1</td><td>Zoodiac</td><td>13</td></tr>"
                "<tr><td>2</td><td>True Draco</td><td>9</td></tr></tbody></table>"
                "</body></html>")
        # That second table infers a header of its own -- Rank | Player |
        # Points -- so "has a header this reader can guess" is not enough to
        # take its rows. It has to guess the same header.
        self.assertEqual(len(parse_post(html).table.rows), 1)

    def test_a_duel_the_blog_forgot_to_number_is_still_a_duel(self):
        # The 2017 South America WCQ leaves the table cell of its second Top 4
        # match empty. Read as the announcement of a team match, both Duelists
        # became teams and the Top 4 held two players who never played in the
        # Top 8.
        from parse import parse_post
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Table</td><td>Player 1</td><td>vs</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs</td><td>Bo B.</td></tr>"
                "<tr><td></td><td>Cy C.</td><td>vs</td><td>Di D.</td></tr>"
                "</tbody></table></body></html>")
        rows = parse_post(html).table.rows
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["a"]["name"], rows[1]["b"]["name"]), ("Cy C.", "Di D."))
        self.assertIsNone(rows[1]["table"], "it has no number because none was written")
        self.assertNotIn("duels", rows[1], "it is a duel, not a team match")

    def test_a_team_announcement_is_not_a_caption(self):
        # The caption rule reads past a row that names no columns. A team
        # announcement names no columns either, and it is data.
        html = ("<html><head><title>Top 4 Pairings</title></head><body>"
                "<table><tbody>"
                "<tr><td>Team</td><td>Alpha Squad</td><td>vs.</td><td>Beta Crew</td></tr>"
                "<tr><td>Table</td><td>Player 1</td><td>vs.</td><td>Player 2</td></tr>"
                "<tr><td>1</td><td>Ann A.</td><td>vs.</td><td>Bo B.</td></tr>"
                "</tbody></table></body></html>")
        rows = parse_post(html).table.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["a"]["name"], "Alpha Squad")
        self.assertEqual(len(rows[0]["duels"]), 1)

    def test_a_ranking_is_never_a_pairing(self):
        # TEAM YCS La Paz heads its standings "Rank | Team Name | Duelist
        # Names | Points". Two of those read like sides, so asking about sides
        # before asking about rank turned every standings table on the event
        # into a bracket -- and left it with no standings, no format, and
        # nothing at all in the archive.
        html = ("<html><head><title>Standings After Round 4</title></head><body>"
                "<table><tbody>"
                "<tr><td>Rank</td><td>Team Name</td><td>Duelist Names</td><td>Points</td></tr>"
                "<tr><td>1</td><td>Road of the King</td><td>Ann A., Bo B., Cy C.</td><td>12</td></tr>"
                "</tbody></table></body></html>")
        t = parse_post(html).table
        self.assertEqual(t.kind, "standings")
        self.assertEqual(t.rows[0]["rank"], 1)

    def test_one_side_is_not_a_pairing(self):
        # A deck list names one Duelist per row. Reading it as a pairing would
        # give every one of them an opponent made of their own deck.
        t = self.table(["Player", "Deck"], ["Ann Alpha", "Ryzeal"]).table
        self.assertEqual(t.kind, "unknown")

    def test_a_column_the_blog_copied_is_not_a_round(self):
        # YCS Denver published round 6 with Player 2 holding Player 1's name
        # in all 247 rows. Read as written it is 247 Duelists each playing
        # themselves, which is not a round -- and it took the whole 42-post
        # event out of the archive.
        head = ["Table", "Player 1", "vs.", "Player 2"]
        copied = self.table(head,
                            ["1", "Brown, Quinton", "vs.", "Brown, Quinton"],
                            ["2", "Flynn, Andrey", "vs.", "Flynn, Andrey"]).table
        self.assertEqual(copied.kind, "pairings")   # still a pairings post
        self.assertEqual(copied.rows, [])           # with nothing to read

    def test_one_copied_row_still_stops_the_event(self):
        # Every row, not some. A single self-paired row is a typo in a round
        # that was really played, and the archive should keep refusing it
        # rather than quietly drop the round it belongs to.
        head = ["Table", "Player 1", "vs.", "Player 2"]
        mixed = self.table(head,
                           ["1", "Brown, Quinton", "vs.", "Brown, Quinton"],
                           ["2", "Flynn, Andrey", "vs.", "Le, An Thanh"]).table
        self.assertEqual(len(mixed.rows), 2)
        self.assertEqual(mixed.rows[0]["a"]["name"], mixed.rows[0]["b"]["name"])

    def test_a_table_that_is_neither_is_still_neither(self):
        t = self.table(["Deck", "Count"], ["Ryzeal", "13"]).table
        self.assertEqual(t.kind, "unknown")


class TestCoverageFormat(unittest.TestCase):
    """What a post is coverage of, which is not always a format of the event."""

    def test_each_side_tournament_is_named(self):
        # Four tournaments, not one. Calling them all Dragon Duel said that
        # three quarters of what that button held was something it is not.
        from parse import coverage_format
        for title, want in (
                ("Dragon Duel Top 8 Pairings", "Dragon Duel"),
                ("Sunday ATTACK OF THE GIANT CARD!! Winners", "Attack of the Giant Card"),
                ("Public Events Points Playoff Winner", "Public Events"),
                ("Time Wizard Format Winner", "Time Wizard")):
            self.assertEqual(coverage_format(title, None), want, title)

    def test_it_wins_over_the_events_own_format(self):
        # "Advanced Format Dragon Duel Feature Match" is Dragon Duel coverage
        # that happens to name the format the main event was played under.
        from parse import coverage_format
        self.assertEqual(
            coverage_format("Advanced Format Dragon Duel Feature Match", "Advanced"),
            "Dragon Duel")

    def test_a_main_event_that_reads_like_a_side_one_keeps_its_format(self):
        # winners.SIDE_EVENT matches "invitational" for a different purpose.
        # A UDS Invitational is a main event here with a hundred posts of its
        # own, and filing those anywhere but their own format is a plain lie.
        from parse import coverage_format
        self.assertIsNone(coverage_format("UDS Invitational Round 4 Pairings", None))
        self.assertEqual(
            coverage_format("UDS Invitational Round 4 Pairings", "Advanced"), "Advanced")

    def test_an_ordinary_post_keeps_its_format(self):
        from parse import coverage_format
        self.assertEqual(coverage_format("Round 4 Pairings", "Genesys"), "Genesys")
        self.assertIsNone(coverage_format("Round 4 Pairings", None))

    def test_the_builder_does_not_see_them(self):
        # detect_format is what groups an event's rounds into tournaments. A
        # Dragon Duel table read as one of the main event's has cost this
        # archive real damage, so the feed names them and the builder does not.
        from parse import detect_format
        for title in ("Dragon Duel Top 8 Pairings",
                      "Sunday ATTACK OF THE GIANT CARD!! Winners",
                      "Public Events Points Playoff Winner"):
            self.assertIsNone(detect_format(title), title)


class TestFoldedNames(unittest.TestCase):
    """One Duelist with two names.

    YCS Chicago seated "Aaron Chase Furman" through eleven rounds of Swiss and
    "Aaron Furman" in the Top 16. Nothing downstream survives that: a record is
    looked up by name, so the cut asked for a Duelist the standings had filed
    under a longer one and got nothing, and the advancement check read a Top 16
    whose Duelists had never played in the Top 32.
    """

    def fold(self, swiss, cut, cut_round="Top 16"):
        from build import reconcile_names
        sources = [_src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD, swiss),
                   _src("https://x/t/", f"{cut_round} Pairings", PAIR_HEAD, cut)]
        return reconcile_names(sources), sources

    def test_a_name_is_split_once_not_once_per_comparison(self):
        # reconcile_names asks every name about every other name, and asked
        # each of them for its words up to three times a comparison. One
        # 646-Duelist event split the same strings 4.7 million times, which
        # was 74% of the whole build -- 5.4 seconds of the 5.5 it took.
        #
        # Asserted through the cache's own counters rather than a clock, so it
        # fails when the caching is removed and not when CI is busy.
        from build import _words
        _words.cache_clear()
        self.fold([["1", "Aaron Chase", "Furman", "vs.", "Kobe Louis", "Short"]],
                  [["1", "Aaron", "Furman", "vs.", "Kobe", "Short"]])
        info = _words.cache_info()
        self.assertGreater(info.hits, info.misses,
                           f"most calls should be answered from the cache, got {info}")

    def test_folding_is_the_same_answer_the_second_time(self):
        # The cache lives for the process, so a second event builds against a
        # cache the first one filled. A name's words do not depend on which
        # event asked, and this says so out loud: the same input must give the
        # same folding warm as it did cold.
        from build import _words
        _words.cache_clear()
        rows = ([["1", "Aaron Chase", "Furman", "vs.", "Kobe Louis", "Short"]],
                [["1", "Aaron", "Furman", "vs.", "Kobe", "Short"]])
        cold, _ = self.fold(*rows)
        self.assertGreater(_words.cache_info().currsize, 0, "the cache is warm now")
        warm, _ = self.fold(*rows)
        self.assertEqual(cold, warm)

    def test_a_shortening_of_both_ends_is_still_found(self):
        # The candidate index is keyed on a first letter, not a whole word,
        # because ends_agree accepts a prefix: "Ben" agrees with "Benjamin".
        # Keyed on whole words this Duelist has no key in common with their
        # own longer name -- neither "ben"/"benjamin" nor "smith"/"smithson"
        # -- so the fold would quietly stop happening, which is how a narrowed
        # folding rule cost the archive four events in #89 and #93.
        canon, _ = self.fold(
            [["1", "Benjamin Carl", "Smithson", "vs.", "Zoe", "Adams"]],
            [["1", "Ben", "Smith", "vs.", "Zoe", "Adams"]], cut_round="Top 4")
        self.assertEqual(canon.get("Ben Smith"), "Benjamin Carl Smithson")

    def test_two_letters_the_wrong_way_round(self):
        # YCS Toronto's Top 8 seats "Alexandre Dalpe" and its Top 4 is written
        # up as "Alexander Dalpe" -- one Duelist, and a Top 4 holding somebody
        # who had not played in the Top 8 took the event out of the archive. A
        # transposition is the same slip of the hand as a typed letter.
        # The spelling seen in more rounds keeps the Duelist, so the typo has
        # to be the rarer one -- as it is: it appears in the write-up of one
        # round and the name itself appears everywhere they played.
        from build import reconcile_names
        swiss = [["1", "Alexandre", "Dalpe", "vs.", "Kobe Louis", "Short"]]
        sources = [_src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD, swiss),
                   _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD, swiss),
                   _src("https://x/t/", "Top 4 Pairings", PAIR_HEAD,
                        [["1", "Alexander", "Dalpe", "vs.", "Kobe", "Short"]])]
        canon = reconcile_names(sources)
        self.assertEqual(canon.get("Alexander Dalpe"), "Alexandre Dalpe")

    def test_a_dropped_middle_name_is_folded(self):
        canon, sources = self.fold(
            [["1", "Aaron Chase", "Furman", "vs.", "Kobe Louis", "Short"]],
            [["1", "Aaron", "Furman", "vs.", "Kobe", "Short"]])
        self.assertEqual(canon, {"Aaron Furman": "Aaron Chase Furman",
                                 "Kobe Short": "Kobe Louis Short"})
        got = [(r["a"]["name"], r["b"]["name"]) for r in sources[1].post.table.rows]
        self.assertEqual(got, [("Aaron Chase Furman", "Kobe Louis Short")])

    def test_a_dropped_forename_is_folded(self):
        # Konami drops given names from the front as readily as from the back:
        # YCS Knoxville printed "Mohammed Faisal Khan" as "Faisal Khan". A rule
        # keyed on the forename refuses him.
        canon, _ = self.fold(
            [["1", "Mohammed Faisal", "Khan", "vs.", "Kyle Conner", "Jones"]],
            [["1", "Faisal", "Khan", "vs.", "Kyle", "Jones"]])
        self.assertEqual(canon["Faisal Khan"], "Mohammed Faisal Khan")

    def test_a_nickname_is_folded(self):
        canon, _ = self.fold(
            [["1", "Jeffrey Michael Alexander", "Jones", "vs.", "Rashad Franklin", "Jones"]],
            [["1", "Jeff", "Jones", "vs.", "Rashad", "Jones"]])
        self.assertEqual(canon["Jeff Jones"], "Jeffrey Michael Alexander Jones")

    def test_a_fold_needs_a_forename_or_a_surname_in_common(self):
        # YCS Cancun seated an Alexander Michael and a Jeffrey Michael Alexander
        # Jones. Every word of the first sits inside the second, and folding
        # them erased a Duelist -- they agree about neither end of the name.
        canon, _ = self.fold(
            [["1", "Jeffrey Michael Alexander", "Jones", "vs.", "Kobe Louis", "Short"]],
            [["1", "Alexander", "Michael", "vs.", "Kobe", "Short"]])
        self.assertNotIn("Alexander Michael", canon)
        self.assertEqual(canon["Kobe Short"], "Kobe Louis Short")

    def test_the_surname_alone_is_enough(self):
        # "Edgar Tinoco" for "Edgar Gustavo Tinoco Serrano": the blog prints one
        # of two surnames, so the last words differ and the first agree.
        canon, _ = self.fold(
            [["1", "Edgar Gustavo", "Tinoco Serrano", "vs.", "Ann", "Alpha"]],
            [["1", "Edgar", "Tinoco", "vs.", "Ann", "Alpha"]])
        self.assertEqual(canon["Edgar Tinoco"], "Edgar Gustavo Tinoco Serrano")

    def test_two_names_reaching_for_one_target_in_one_round_are_left_alone(self):
        # Two seats folding to one name is one Duelist playing themselves.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Matthew Joseph", "Alvarado Ruiz", "vs.", "Ann", "Alpha"]]),
            _src("https://x/t/", "Top 64 Pairings", PAIR_HEAD,
                 [["1", "Matthew", "Alvarado", "vs.", "Matthew Joseph", "Alvarado"]])]
        canon = reconcile_names(sources)
        self.assertNotIn("Matthew Alvarado", canon)
        self.assertNotIn("Matthew Joseph Alvarado", canon)

    def test_one_duelist_written_three_ways_is_still_folded(self):
        # YCS Memphis has "Kamal Crooks", "Kamal Crooks-Valdez" and "Kamal
        # Derrick El Crooks-Valdez", never two of them in a round. Refusing all
        # three because there were three left its Top 16 seeded from nobody.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Kamal Derrick El", "Crooks-Valdez", "vs.", "Ann", "Alpha"]]),
            _src("https://x/t32/", "Top 32 Pairings", PAIR_HEAD,
                 [["1", "Kamal", "Crooks-Valdez", "vs.", "Ann", "Alpha"]]),
            _src("https://x/t16/", "Top 16 Pairings", PAIR_HEAD,
                 [["1", "Kamal", "Crooks", "vs.", "Ann", "Alpha"]])]
        canon = reconcile_names(sources)
        self.assertEqual(canon["Kamal Crooks"], "Kamal Derrick El Crooks-Valdez")
        self.assertEqual(canon["Kamal Crooks-Valdez"], "Kamal Derrick El Crooks-Valdez")

    def test_a_letter_typed_wrong_is_folded_back(self):
        # YCS Atlanta's Swiss seated "Mohammed Imran Khan" for eleven rounds
        # and its Top 4 post printed "Mohammed Imram Khan". Nothing about that
        # is a shortening, so the event was rejected for a Top 4 Duelist who
        # had not played in the Top 8.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Ann", "Alpha"]]),
            _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Bo", "Beta"]]),
            _src("https://x/t/", "Top 4 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imram", "Khan", "vs.", "Ann", "Alpha"]])]
        canon = reconcile_names(sources)
        self.assertEqual(canon["Mohammed Imram Khan"], "Mohammed Imran Khan")

    def test_the_spelling_the_coverage_uses_more_is_the_one_kept(self):
        # A typo appears once, in the post that carried it. The name itself
        # appears everywhere the Duelist played, so the rounds vote.
        from build import reconcile_names
        sources = [
            _src("https://x/t/", "Top 4 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imram", "Khan", "vs.", "Ann", "Alpha"]]),
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Bo", "Beta"]]),
            _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Cy", "Gamma"]])]
        self.assertEqual(reconcile_names(sources)["Mohammed Imram Khan"],
                         "Mohammed Imran Khan")

    def test_two_letters_apart_is_two_people(self):
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Ann", "Alpha"]]),
            _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Bo", "Beta"]]),
            _src("https://x/t/", "Top 4 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Usman", "Khan", "vs.", "Ann", "Alpha"]])]
        self.assertNotIn("Mohammed Usman Khan", reconcile_names(sources))

    def test_a_letter_wrong_in_two_words_is_not_a_typo(self):
        # One slip in one word is a typo. Two is two names, and folding them
        # would merge a Mohammad into a Mohammed on no evidence at all.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Ann", "Alpha"]]),
            _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Bo", "Beta"]]),
            _src("https://x/t/", "Top 4 Pairings", PAIR_HEAD,
                 [["1", "Mohammad Imram", "Khan", "vs.", "Ann", "Alpha"]])]
        self.assertNotIn("Mohammad Imram Khan", reconcile_names(sources))

    def test_two_duelists_one_letter_apart_are_left_alone(self):
        # They both entered, so they are seated in the same rounds -- which is
        # what tells them apart from a name typed wrong in one post.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Mohammed Imram", "Khan"]]),
            _src("https://x/r2/", "Round 2 Pairings", PAIR_HEAD,
                 [["1", "Mohammed Imran", "Khan", "vs.", "Ann", "Alpha"],
                  ["2", "Mohammed Imram", "Khan", "vs.", "Bo", "Beta"]])]
        self.assertEqual(reconcile_names(sources), {})

    def test_two_candidates_are_left_alone(self):
        # YCS Memphis ran a Nhan Thanh Nguyen and a Thanh Cong Nguyen, and a
        # Top 16 "Thanh Nguyen" could be either. Guessing costs a Duelist their
        # record and gives it to someone who did not earn it.
        canon, _ = self.fold(
            [["1", "Nhan Thanh", "Nguyen", "vs.", "Thanh Cong", "Nguyen"]],
            [["1", "Thanh", "Nguyen", "vs.", "Chuong", "Nguyen"]])
        self.assertNotIn("Thanh Nguyen", canon)

    def test_the_previous_round_settles_two_candidates(self):
        # Both Nguyens played the Swiss; only one reached the Top 32, and that
        # is the one the Top 16 means.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Nhan Thanh", "Nguyen", "vs.", "Thanh Cong", "Nguyen"]]),
            _src("https://x/t32/", "Top 32 Pairings", PAIR_HEAD,
                 [["1", "Thanh Cong", "Nguyen", "vs.", "Chuong", "Nguyen"]]),
            _src("https://x/t16/", "Top 16 Pairings", PAIR_HEAD,
                 [["1", "Thanh", "Nguyen", "vs.", "Chuong", "Nguyen"]])]
        canon = reconcile_names(sources)
        self.assertEqual(canon["Thanh Nguyen"], "Thanh Cong Nguyen")

    def test_two_seated_in_one_round_are_two_people(self):
        # One Duelist does not play themselves, so whatever the names look
        # like, a round holding both spellings holds two entrants.
        canon, _ = self.fold(
            [["1", "Aaron", "Furman", "vs.", "Aaron Chase", "Furman"]],
            [["1", "Aaron", "Furman", "vs.", "Kobe", "Short"]])
        self.assertNotIn("Aaron Furman", canon)

    def test_an_initial_is_not_expanded(self):
        # "J Jones" among several is not identification, and a two-letter word
        # would start half the forenames in the room.
        canon, _ = self.fold(
            [["1", "Jeffrey Michael Alexander", "Jones", "vs.", "Johnny Nathaniel", "Jones"]],
            [["1", "J", "Jones", "vs.", "Johnny", "Jones"]])
        self.assertNotIn("J Jones", canon)

    def test_a_lone_word_is_never_folded(self):
        # Team events enter as one word -- "Legionnaire" is not a forename.
        canon, _ = self.fold(
            [["1", "Team", "Legionnaire", "vs.", "Team", "Sharks"]],
            [["1", "", "Legionnaire", "vs.", "", "Sharks"]])
        self.assertNotIn("Legionnaire", canon)

    def test_the_standings_are_folded_too(self):
        # Otherwise the cut's names stop matching the table the records are
        # derived onto, which is the whole reason for folding them.
        from build import reconcile_names
        sources = [
            _src("https://x/r1/", "Round 1 Pairings", PAIR_HEAD,
                 [["1", "Aaron Chase", "Furman", "vs.", "Kobe Louis", "Short"]]),
            _src("https://x/s/", "Standings After Round 1",
                 ["Rank", "Player Name", "Points"], [["1", "Aaron Furman", "3"]])]
        reconcile_names(sources)
        self.assertEqual(sources[1].post.table.rows[0]["name"], "Aaron Chase Furman")


class TestSharedNames(unittest.TestCase):
    """Two Duelists with one name.

    At YCS Columbus "Johnny KS Nguyen" and "Johnny PA Nguyen" are two people.
    strip_region takes the code off the name, so they merged into one Duelist
    playing two matches a round -- and a merged Duelist's appearances are two
    people's, which makes the losses derived from them wrong for both.
    """

    def build(self, rows, standings=None):
        from build import disambiguate
        sources = [_src("https://x/r1/", "Round 1 Pairings (Advanced Format)",
                        PAIR_HEAD, rows)]
        if standings is not None:
            sources.append(_src("https://x/s1/", "Standings After Round 1 (Advanced Format)",
                                ["Rank", "Player Name", "Points"], standings))
        return disambiguate(sources), sources

    def test_a_region_tells_two_duelists_apart(self):
        (shared, ambiguous), sources = self.build([
            ["1", "Johnny KS", "Nguyen", "vs.", "Steven Sean", "Bowers"],
            ["2", "Johnny PA", "Nguyen", "vs.", "Wyatt Hank", "Ticheli"]])
        self.assertEqual(shared, {"Johnny Nguyen"})
        self.assertEqual(ambiguous, set())
        got = [r["a"]["name"] for r in sources[0].post.table.rows]
        self.assertEqual(got, ["Johnny Nguyen (KS)", "Johnny Nguyen (PA)"])

    def test_the_standings_are_relabelled_too(self):
        # Otherwise the split names stop matching the table the records are
        # derived onto, and the fix for one Duelist breaks both.
        (shared, _), sources = self.build(
            [["1", "Johnny KS", "Nguyen", "vs.", "Steven Sean", "Bowers"],
             ["2", "Johnny PA", "Nguyen", "vs.", "Wyatt Hank", "Ticheli"]],
            standings=[["1", "Johnny KS Nguyen", "3"], ["2", "Johnny PA Nguyen", "0"]])
        self.assertEqual([r["name"] for r in sources[1].post.table.rows],
                         ["Johnny Nguyen (KS)", "Johnny Nguyen (PA)"])

    def test_a_name_that_does_not_collide_is_left_alone(self):
        (shared, ambiguous), sources = self.build([
            ["1", "Philip DEU", "Weidinger", "vs.", "Dave NLD", "Vecht"]])
        self.assertEqual((shared, ambiguous), (set(), set()))
        self.assertEqual(sources[0].post.table.rows[0]["a"]["name"], "Philip Weidinger")

    def test_a_bystander_is_untouched_while_a_collision_is_fixed(self):
        # The region is on plenty of rows, and the same Duelist is written with
        # one in the pairings and without one in the standings. Appending it
        # wherever it appears would be the safer-looking change and the wrong
        # one: Philip would stop matching himself between the two tables and
        # lose the record the collision fix was supposed to protect.
        (shared, _), sources = self.build(
            [["1", "Johnny KS", "Nguyen", "vs.", "Steven Sean", "Bowers"],
             ["2", "Johnny PA", "Nguyen", "vs.", "Wyatt Hank", "Ticheli"],
             ["3", "Philip DEU", "Weidinger", "vs.", "Dave NLD", "Vecht"]],
            standings=[["1", "Philip Weidinger", "9"]])
        self.assertEqual(shared, {"Johnny Nguyen"}, "the collision is still fixed")
        pairs = {r["a"]["name"] for r in sources[0].post.table.rows}
        self.assertIn("Philip Weidinger", pairs, "no region on a name nobody shares")
        self.assertEqual(sources[1].post.table.rows[0]["name"], "Philip Weidinger")

    def test_with_no_region_to_go_on_the_name_is_left_ambiguous(self):
        # Columbus round 2 seats "Colton Randolph Crane" at two tables and says
        # nothing more. Whether that is two Duelists or one printed twice is not
        # something the page gets to decide.
        (shared, ambiguous), sources = self.build([
            ["1", "DArmond Rushaun", "Dixon", "vs.", "Colton Randolph", "Crane"],
            ["2", "Eric Casey Ho", "Kovalak", "vs.", "Colton Randolph", "Crane"]])
        self.assertEqual(shared, set())
        self.assertEqual(ambiguous, {"Colton Randolph Crane"})
        self.assertEqual([r["b"]["name"] for r in sources[0].post.table.rows],
                         ["Colton Randolph Crane"] * 2, "left exactly as found")

    def test_nothing_is_derived_for_an_ambiguous_name(self):
        from records import derive
        standings = [{"name": "Colton Randolph Crane", "points": 3}]
        pairings = [[{"a": {"name": "Colton Randolph Crane"}, "b": {"name": "A B"}},
                     {"a": {"name": "Colton Randolph Crane"}, "b": {"name": "C D"}}]]
        rec = derive(standings, pairings, ambiguous={"Colton Randolph Crane"})[0]
        self.assertEqual(rec.confidence, "unknown")
        self.assertIsNone(rec.wins)
        self.assertIsNone(rec.rounds_played,
                          "two people's appearances are nobody's round count")
        self.assertEqual(rec.points, 3, "the points are still what the table said")


class TestStandingsWithoutPoints(unittest.TestCase):
    """The blog publishes Rank and Player Name and nothing else for whole events."""

    TABLE = _page("YCS Columbus: Standings After Round 10 (Advanced Format)",
                  ["Rank", "Player Name"],
                  [["1", "Andrew Robert Hadfield"], ["2", "Chase Alexander DeDomenic"]])

    def test_a_two_column_table_is_still_standings(self):
        # Requiring a points column threw away all 23 of YCS Columbus's
        # standings, and with them both formats' field sizes: 17 rounds, 1,618
        # Duelists, and a built event that reported nothing at all.
        p = parse_post(self.TABLE)
        self.assertEqual(p.table.kind, "standings")
        self.assertEqual(len(p.table.rows), 2)
        self.assertEqual(p.table.rows[0]["name"], "Andrew Robert Hadfield")

    def test_the_missing_points_are_absent_not_zero(self):
        # Zero would be a claim about how the Duelist is doing. There is no
        # points column; the table says nothing either way.
        self.assertIsNone(parse_post(self.TABLE).table.rows[0]["points"])

    def test_the_three_column_layout_still_reads_its_points(self):
        row = load("standings-advanced").table.rows[0]
        self.assertEqual(row["points"], 36)


class TestSingleTournamentEvent(unittest.TestCase):
    """Events that run one tournament and never name a format.

    The North America WCQ titles every post "North America WCQ: Round 10
    Pairings". Building only named formats threw the whole event away: 62 posts,
    nine rounds of pairings, no tournament.
    """

    def wcq(self, *extra):
        from build import build_event
        return build_event("NAWCQ", [
            _src("https://x/p10/", "North America WCQ: Round 10 Pairings",
                 PAIR_HEAD, [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
            _src("https://x/s10/", "North America WCQ: Standings After Round 10",
                 ["Rank", "Player Name", "Points"], [["1", "Ann Alpha", "27"]]),
            *extra])

    def test_the_tournament_is_built_under_no_format_name(self):
        formats = self.wcq()["formats"]
        self.assertEqual(len(formats), 1)
        self.assertIsNone(formats[0]["format"],
                          "no format was stated, so none may be invented")
        self.assertTrue(formats[0]["rounds"])

    def test_announcements_alone_are_not_a_tournament(self):
        # YCS Montreal's 19 format-less posts are announcements about the event,
        # not a third tournament running alongside Advanced and Genesys.
        from build import build_event
        ev = build_event("YCS Montréal", [
            _src("https://x/n1/", "Welcome to YCS Montreal", ["a"], []),
            _src("https://x/n2/", "The Giant Cards of YCS Montreal", ["a"], [])])
        self.assertEqual(ev["formats"], [])
        self.assertEqual(ev["_unassigned"], 2)

    def test_named_formats_do_not_absorb_the_announcements(self):
        ev = _build_montreal_with_announcement()
        self.assertEqual({f["format"] for f in ev["formats"]}, {"Advanced", "Genesys"})
        self.assertEqual(ev["_unassigned"], 1)


def _build_montreal_with_announcement():
    from build import build_event
    return build_event("YCS Montréal",
                       _sources() + [_src("https://x/n/", "Welcome to YCS Montreal",
                                          ["a"], [])])


class TestArchive(unittest.TestCase):
    """One directory per event, and a manifest naming them all."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def event(self, name, updated, fmt="Advanced", rounds=2):
        return {"event": name, "updated": updated, "sample": False, "ongoing": False,
                "coverageBy": "Konami",
                "formats": [{"format": fmt, "swissRounds": 13, "duelists": 766,
                             "rounds": [{"id": str(i)} for i in range(rounds)]}]}

    def write(self, slug, name, updated, posts=()):
        import archive
        archive.write_event(self.tmp, slug, self.event(name, updated), list(posts))

    def test_an_event_that_was_built_is_remembered(self):
        import archive
        self.assertEqual(archive.scraped(self.tmp), set())
        self.write("2026-08-quebec", "YCS Montréal", "2026-08-16")
        self.assertEqual(archive.scraped(self.tmp), {"2026-08-quebec"})

    def test_a_missing_archive_is_empty_not_an_error(self):
        import archive
        self.assertEqual(archive.scraped(self.tmp / "nothing-here"), set())

    def test_the_manifest_lists_events_newest_first(self):
        import archive
        self.write("a-old", "Old", "2025-01-01")
        self.write("c-new", "New", "2026-08-16")
        self.write("b-mid", "Mid", "2026-05-23")
        got = [e["slug"] for e in archive.build_manifest(self.tmp)["events"]]
        self.assertEqual(got, ["c-new", "b-mid", "a-old"])

    def test_the_manifest_carries_a_summary_not_the_rounds(self):
        import archive, json
        self.write("2026-08-quebec", "YCS Montréal", "2026-08-16")
        entry = archive.build_manifest(self.tmp)["events"][0]
        self.assertEqual(entry["event"], "YCS Montréal")
        self.assertEqual(entry["path"], "events/2026-08-quebec/rounds.json")
        self.assertEqual(entry["formats"], [{"format": "Advanced", "swissRounds": 13,
                                             "duelists": 766, "rounds": 2}])
        # The point of a manifest is that it stays small as the archive grows.
        self.assertNotIn("pairings", json.dumps(entry))

    def test_the_manifest_carries_who_won_and_with_what(self):
        # The winners page lists every event at once, and the alternative is
        # fetching a hundred and forty round files -- several over ten
        # megabytes -- to read one name out of each.
        import archive
        got = archive.champions({"formats": [{
            "format": "Advanced", "champion": "Ada Lovelace",
            "rounds": [{"label": "Final", "pairings": [
                {"a": "Ada Lovelace", "aDeck": "Elfnote",
                 "b": "Bo Peep", "bDeck": "Kewl Tune"}]}]}]})
        self.assertEqual(got, [{"format": "Advanced", "name": "Ada Lovelace",
                                "deck": "Elfnote"}])

    def test_the_deck_is_the_winners_side_of_the_pairing(self):
        # Reading the other side prints the runner-up's deck under the
        # winner's name, which is the sort of thing that looks right.
        import archive
        got = archive.champions({"formats": [{
            "format": None, "champion": "Bo Peep",
            "rounds": [{"label": "Final", "pairings": [
                {"a": "Ada Lovelace", "aDeck": "Elfnote",
                 "b": "Bo Peep", "bDeck": "Kewl Tune"}]}]}]})
        self.assertEqual(got[0]["deck"], "Kewl Tune")

    def test_an_event_with_no_champion_contributes_nothing(self):
        import archive
        self.assertEqual(archive.champions({"formats": [{"format": "Advanced"}]}), [])

    def test_a_champion_with_no_deck_published_still_counts(self):
        import archive
        got = archive.champions({"formats": [{
            "format": None, "champion": "Ada Lovelace",
            "rounds": [{"label": "Top 4", "pairings": [{"a": "Ada Lovelace", "b": "Bo Peep"}]}]}]})
        self.assertEqual(got, [{"format": None, "name": "Ada Lovelace", "deck": None}])

    def test_a_team_champion_names_its_duelists(self):
        # A team has no deck of its own -- three Duelists do -- and the page
        # has nowhere else to read them from. Fetching the round file to find
        # three names is what this function exists to avoid.
        import archive
        got = archive.champions({"formats": [{
            "format": None, "champion": "Better Have It", "entrant": "Team",
            "rounds": [{"label": "Top 4", "pairings": [
                {"a": "Better Have It", "aDeck": None, "b": "Los Pistoleros", "bDeck": None,
                 "duels": [
                     {"table": 1, "a": "Ruben Andres Penaranda", "aDeck": "Bystial Dragon Link",
                      "b": "Someone Else", "bDeck": "Purrely"},
                     {"table": 2, "a": "Pakawat Thomas Pamornsut", "aDeck": "Unchained",
                      "b": "A Third", "bDeck": "Maliss"}]}]}]}]})
        self.assertEqual(got[0]["name"], "Better Have It")
        self.assertEqual(got[0]["members"], [
            {"name": "Ruben Andres Penaranda", "deck": "Bystial Dragon Link"},
            {"name": "Pakawat Thomas Pamornsut", "deck": "Unchained"}])

    def test_the_members_are_the_winning_side_of_the_match(self):
        # Reading the other side lists the runner-up's Duelists under the
        # winner's name, which is the sort of thing that looks right.
        import archive
        got = archive.champions({"formats": [{
            "format": None, "champion": "Los Pistoleros", "entrant": "Team",
            "rounds": [{"label": "Final", "pairings": [
                {"a": "Better Have It", "b": "Los Pistoleros",
                 "duels": [{"table": 1, "a": "Ruben Andres Penaranda", "aDeck": "Purrely",
                            "b": "Cameron Taylor Neal", "bDeck": "Ryzeal"}]}]}]}]})
        self.assertEqual(got[0]["members"], [{"name": "Cameron Taylor Neal", "deck": "Ryzeal"}])

    def test_a_singles_champion_carries_no_members(self):
        # Every singles event would otherwise carry an empty list in a file
        # the page fetches before anything is on screen.
        import archive
        got = archive.champions({"formats": [{
            "format": None, "champion": "Ada Lovelace",
            "rounds": [{"label": "Final", "pairings": [{"a": "Ada Lovelace", "b": "Bo Peep"}]}]}]})
        self.assertNotIn("members", got[0])

    def test_the_manifest_counts_each_events_posts(self):
        # The page lists every event but fetches an event's coverage only when
        # it is opened, so the count has to come from here. Without it the page
        # can only total what it has already loaded, and the figure climbs as
        # you read.
        import archive
        self.write("2026-08-quebec", "YCS Montréal", "2026-08-16",
                   [{"title": f"post {i}"} for i in range(7)])
        self.assertEqual(archive.build_manifest(self.tmp)["events"][0]["postCount"], 7)

    def test_an_event_with_no_posts_counts_none_rather_than_omitting_it(self):
        # A missing key and a zero read the same to the page only if it happens
        # to test for both; a number that is always there is one less thing.
        import archive
        self.write("2026-08-quebec", "YCS Montréal", "2026-08-16")
        self.assertEqual(archive.build_manifest(self.tmp)["events"][0]["postCount"], 0)

    def test_the_feed_is_the_whole_archive_newest_first_and_capped(self):
        import archive
        # A run backfills a few events at a time, so a feed built from only what
        # that run fetched would drop every event the run before it covered.
        self.write("old", "Old", "2025-01-01",
                   [{"title": "old post", "modified": "2025-01-01T10:00:00+00:00"}])
        self.write("new", "New", "2026-08-16",
                   [{"title": f"new post {i}",
                     "modified": f"2026-08-1{i}T10:00:00+00:00"} for i in range(3)])
        titles = [i["title"] for i in archive.feed_items(self.tmp, 3)]
        self.assertEqual(titles, ["new post 2", "new post 1", "new post 0"])
        self.assertEqual(len(archive.feed_items(self.tmp, 99)), 4,
                         "every event's posts are there, not just the last run's")


class TestBackfillPlan(unittest.TestCase):
    """Which events a run builds."""

    def entries(self):
        rows = []
        for slug, month, kinds in (
                ("2026-08-quebec", "08", ("pairings", "standings", "news")),
                ("2026-05-columbus", "05", ("pairings", "standings")),
                ("2026-02-orlando", "02", ("pairings", "standings")),
                ("2026-01-nothing", "01", ("news",))):
            rows += [(f"2026/ycs/{slug}/ycs-round-1-{k}", f"2026-{month}-14")
                     for k in kinds]
        return parse_post_sitemap(urlset(*rows))

    def plan(self, done, backfill):
        from run import plan
        return [slug for slug, _, _ in plan(self.entries(), set(done), backfill)]

    def test_by_default_only_the_newest_event_is_built(self):
        self.assertEqual(self.plan([], 0), ["2026-08-quebec"])

    def test_a_backfill_takes_the_next_newest_events(self):
        self.assertEqual(self.plan([], 2),
                         ["2026-08-quebec", "2026-05-columbus", "2026-02-orlando"])

    def test_an_event_already_in_the_archive_is_not_fetched_again(self):
        self.assertEqual(self.plan(["2026-05-columbus"], 1),
                         ["2026-08-quebec", "2026-02-orlando"])

    def test_the_newest_event_is_rebuilt_even_though_it_is_in_the_archive(self):
        # It is the one that may still be running.
        self.assertEqual(self.plan(["2026-08-quebec"], 0), ["2026-08-quebec"])

    def test_an_event_with_no_rounds_is_never_built(self):
        # Of 97 event slugs only 68 published both pairings and standings. The
        # rest are an announcement or two, and building them would put empty
        # events in the archive and in the reader's event list.
        self.assertNotIn("2026-01-nothing", self.plan([], 9))


class TestEventDatesIgnoreLaterEdits(unittest.TestCase):
    """An event is dated by its coverage, not by when someone last edited it."""

    def entries(self):
        return parse_post_sitemap(urlset(
            # A 2025 event, with one post edited a year later.
            ("2025/ycs/2025-na-wcq/wcq-round-1-pairings", "2025-07-08"),
            ("2025/ycs/2025-na-wcq/wcq-round-1-standings", "2025-07-09"),
            ("2025/ycs/2025-na-wcq/wcq-about-the-venue", "2026-07-12"),
            ("2026/ycs/2026-na-wcq/wcq-round-1-pairings", "2026-07-11"),
            ("2026/ycs/2026-na-wcq/wcq-round-1-standings", "2026-07-11")))

    def dated(self):
        from run import events_by_recency
        return {slug: ended for slug, _, ended in events_by_recency(self.entries())}

    def test_a_re_edited_post_does_not_redate_the_event(self):
        self.assertEqual(self.dated()["2025-na-wcq"], "2025-07-09")

    def test_the_newer_event_sorts_first(self):
        from run import events_by_recency
        # Dated by the raw newest lastmod, the 2025 WCQ sorted ahead of the 2026
        # one purely because someone edited one of its posts.
        self.assertEqual([slug for slug, _, _ in events_by_recency(self.entries())],
                         ["2026-na-wcq", "2025-na-wcq"])

    def test_draws_follow_the_day_the_event_was_played(self):
        from datetime import date
        from run import DRAWS_ABOLISHED
        # Ties were abolished on 2 September 2025. A July 2025 tournament was
        # played with them; dated to 2026 by an edit, its records were built
        # without them.
        self.assertLess(date.fromisoformat(self.dated()["2025-na-wcq"]), DRAWS_ABOLISHED)
        self.assertGreater(date.fromisoformat(self.dated()["2026-na-wcq"]), DRAWS_ABOLISHED)


class TestFeedSpansEvents(unittest.TestCase):
    """The feed carries the whole archive, so an item's event is its own."""

    ITEMS = [{"title": "Round 13 Pairings", "url": "https://x/a/", "kind": "pairings",
              "modified": "2026-08-16T10:00:00+00:00", "format": "Advanced",
              "event": "YCS Montréal", "slug": "2026-08-quebec"},
             {"title": "Round 1 Pairings", "url": "https://x/b/", "kind": "pairings",
              "modified": "2026-05-23T10:00:00+00:00", "format": "Advanced",
              "event": "YCS Columbus", "slug": "2026-05-ycs-columbus"}]

    def feed(self, items=None):
        from feed import build_feed
        return build_feed("Duel Desk", items if items is not None else self.ITEMS)

    def test_each_item_is_titled_with_its_own_event(self):
        # Titling every item with one event name is how a reader is told that
        # Columbus's round 1 belongs to Montreal.
        xml = self.feed()
        self.assertIn("<title>YCS Montréal: Round 13 Pairings</title>", xml)
        self.assertIn("<title>YCS Columbus: Round 1 Pairings</title>", xml)

    def test_each_item_names_the_event_it_belongs_to(self):
        xml = self.feed()
        self.assertIn('<category domain="event">2026-08-quebec</category>', xml)
        self.assertIn('<category domain="event">2026-05-ycs-columbus</category>', xml)

    def test_the_slug_is_carried_because_display_names_are_not_identifiers(self):
        # Two events can be written the same way and an event can be renamed
        # between runs; the slug is what the archive is keyed on.
        from feed import build_feed
        xml = build_feed("Duel Desk", [{**self.ITEMS[0], "event": "YCS Montreal"}])
        self.assertIn('<category domain="event">2026-08-quebec</category>', xml)

    def test_an_item_with_no_event_falls_back_to_the_channel(self):
        # Which is exactly a single-event feed, unchanged.
        xml = self.feed([{k: v for k, v in self.ITEMS[0].items()
                          if k not in ("event", "slug")}])
        self.assertIn("<title>Duel Desk: Round 13 Pairings</title>", xml)
        self.assertNotIn('domain="event"', xml)

    def test_the_description_names_the_items_own_event(self):
        xml = self.feed()
        self.assertIn("Pairings from YCS Columbus, published by Konami.", xml)


class TestSampleDataTimeline(unittest.TestCase):
    """The sample generator lays its rounds out backwards from --now, and each
    round carries a bare "HH:MM" posting time. Anchored in the small hours the
    event ran across midnight, so `updated` named a time today while the rounds
    it summarised posted yesterday -- which check-rounds.py rejects. The deploy
    workflow regenerates sample data and checks it in the next step, so every
    deploy between midnight and about 06:00 UTC would have failed."""

    ROOT = Path(__file__).resolve().parent.parent
    GENERATOR = ROOT / "scripts/generate-sample-data.py"
    CHECKER = ROOT / ".github/scripts/check-rounds.py"

    def generate(self, now):
        """Run the generator at `now` and return the rounds.json it wrote."""
        import json, subprocess, tempfile
        out = Path(tempfile.mkdtemp())
        done = subprocess.run(["python3", str(self.GENERATOR), "--now", now,
                               "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        # Through the manifest, as the page finds it: the generator writes the
        # archive the site actually serves, not a file at a fixed path.
        manifest = json.loads((out / "events.json").read_text())
        path = out / manifest["events"][0]["path"]
        return path, json.loads(path.read_text())

    def check(self, path):
        return run_checker(path)

    def test_the_check_passes_whatever_hour_it_is_generated_at(self):
        for hour in range(24):
            now = f"2026-08-29T{hour:02d}:20:00Z"
            code, out = self.check(self.generate(now)[0])
            self.assertEqual(code, 0, f"--now {now}: {out}")

    def test_every_round_posts_on_the_day_updated_names(self):
        # What the checker is really asserting, stated directly: a posting time
        # with no date beside it can only be read against one day.
        for now in ("2026-08-29T04:20:00Z", "2026-08-29T14:20:00Z"):
            _, data = self.generate(now)
            posted = [r["posted"] for f in data["formats"]
                      for r in f["rounds"] if r.get("posted")]
            self.assertEqual(data["updated"][11:16], max(posted), now)
            for fmt in data["formats"]:
                # Rounds are stored in playing order, so their times must read
                # in order too. A round stamped 00:28 after one stamped 23:50
                # is a round from the next day, and nothing in the file says so.
                times = [r["posted"] for r in fmt["rounds"] if r.get("posted")]
                self.assertEqual(times, sorted(times), f"{now} {fmt['format']}")

    def test_an_event_that_already_fits_the_day_is_left_where_it_is(self):
        # The slide is a fallback, not a reschedule: a generator run at a normal
        # hour must still describe the event as having just been updated.
        _, data = self.generate("2026-08-29T14:20:00Z")
        self.assertEqual(data["updated"], "2026-08-29T14:08:00Z")
        self.assertIn("August 2026", data["event"])

    def test_the_small_hours_event_is_dated_the_day_it_ran(self):
        # Slid back rather than forwards: coverage of a tournament that has not
        # happened yet would be a worse answer than one that finished late.
        _, data = self.generate("2026-08-29T04:20:00Z")
        self.assertEqual(data["updated"], "2026-08-28T23:47:00Z")
        # The event's name follows it, so a run just after midnight on the 1st
        # does not headline a month none of its timestamps fall in.
        _, turn = self.generate("2026-09-01T04:20:00Z")
        self.assertEqual(turn["updated"][:10], "2026-08-31")
        self.assertIn("August 2026", turn["event"])


class TestABadPageCannotStopTheRun(unittest.TestCase):
    """A backfill spends minutes an event and fetches hundreds of pages.

    A seven-event run fetched 629 of them and one, live, came back with a
    different first table than the same URL serves from cache. The pairings loop
    read a standings row, and the KeyError took down the run and the six events
    it had already built -- an hour of fetching, nothing committed.
    """

    def sources(self, table_html):
        from build import Source
        pairings = ("<html><head><title>Round 1 Pairings (Advanced Format)"
                    "</title></head><body>" + table_html + "</body></html>")
        return [Source("https://x/r1/", parse_post(pairings, "https://x/r1/"), "12:00"),
                _src("https://x/s1/", "Standings After Round 1 (Advanced Format)",
                     ["Rank", "Player Name", "Points"], [["1", "Ann Alpha", "3"]])]

    def build(self, table_html):
        import io
        from contextlib import redirect_stdout
        from build import build_event
        log = io.StringIO()
        with redirect_stdout(log):
            ev = build_event("Somewhere", self.sources(table_html))
        return ev, log.getvalue()

    def test_a_pairings_post_with_no_table_at_all_is_not_a_round(self):
        ev, log = self.build("<p>The pairings are on the wall by the stage.</p>")
        self.assertIn("ignored https://x/r1/", log)
        self.assertIn("no table", log)
        self.assertTrue(ev["formats"], "one bad page took the whole format down")

    def test_a_pairings_post_whose_table_reads_as_neither_is_not_a_round(self):
        # What is left for the guard to catch once the table is trusted: a table
        # the parser cannot place at all. Its rows are nobody's columns.
        odd = ("<table><tbody><tr><td>Prize</td><td>Quantity</td></tr>"
               "<tr><td>Game mat</td><td>200</td></tr></tbody></table>")
        ev, log = self.build(odd)
        self.assertIn("ignored https://x/r1/", log)
        self.assertIn("unknown table", log)
        self.assertTrue(ev["formats"])

    def test_a_pairings_post_with_pairings_in_it_is_kept(self):
        good = ("<table><tbody>"
                "<tr><td>Table</td><td>P1 First Name</td><td>P1 Last Name</td>"
                "<td>vs.</td><td>P2 First Name</td><td>P2 Last Name</td></tr>"
                "<tr><td>1</td><td>Ann</td><td>Alpha</td><td>vs.</td>"
                "<td>Bo</td><td>Beta</td></tr></tbody></table>")
        ev, log = self.build(good)
        self.assertNotIn("ignored", log)
        rounds = ev["formats"][0]["rounds"]
        self.assertEqual(len(rounds[0]["pairings"]), 1)


class TestOneEventFailingDoesNotLoseTheRest(unittest.TestCase):
    """Each event is written as it finishes, so a later failure must not
    discard the ones already built."""

    def run_backfill(self, breaks_on, breaks_coherence=None):
        """Build three events, one of which raises or comes out incoherent."""
        import io, tempfile, types
        from contextlib import redirect_stdout
        from unittest import mock
        import run
        built = []
        # No network and no sitemap: plan() is stubbed, so nothing reads either.
        fetcher = types.SimpleNamespace(get=lambda url, **kw: "<urlset/>")

        # A real published event, renamed. Events are validated as they are
        # written now, so a stub shaped like one would be rejected before the
        # thing under test -- whether a later failure loses the earlier ones --
        # ever came up.
        import json
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "events.json").read_text())
        good = json.loads((root / manifest["events"][0]["path"]).read_text())

        def fake_build_one(f, slug, posts, ended, limit):
            if slug == breaks_on:
                raise KeyError("table")
            built.append(slug)
            event = {**json.loads(json.dumps(good)), "event": slug, "updated": ended}
            if slug == breaks_coherence:
                # A Top 8 of three matches: a bracket halves, so this is a parse
                # that lost a row rather than coverage that stopped early.
                cut = [r for r in event["formats"][0]["rounds"]
                       if r["phase"] == "Top cut"]
                cut[0]["pairings"] = cut[0]["pairings"][:3]
            return (event, [], [f"### {slug}", ""])

        events = [(f"e{i}", [{"kind": "pairings"}], f"2026-0{i}-01") for i in (1, 2, 3)]
        log = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run.py", "--cache", f"{tmp}/cache", "--archive", f"{tmp}/events",
                    "--manifest", f"{tmp}/events.json"]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(run, "Fetcher", lambda **kw: fetcher), \
                 mock.patch.object(run, "plan", lambda *a, **k: events), \
                 mock.patch.object(run, "parse_sitemap_index", lambda x: []), \
                 mock.patch.object(run, "build_one", fake_build_one), \
                 redirect_stdout(log):
                try:
                    code = run.main()
                except Exception as exc:
                    return None, built, log.getvalue(), exc
            import json
            manifest = json.loads(Path(f"{tmp}/events.json").read_text()) \
                if Path(f"{tmp}/events.json").exists() else {"events": []}
        return code, built, log.getvalue(), manifest

    def test_a_later_event_failing_keeps_the_earlier_ones(self):
        code, built, log, manifest = self.run_backfill("e3")
        self.assertEqual(code, 0)
        self.assertEqual(built, ["e1", "e2"])
        self.assertEqual({e["slug"] for e in manifest["events"]}, {"e1", "e2"},
                         "the events already built were thrown away")

    def test_the_failure_is_reported_rather_than_buried(self):
        _, _, log, _ = self.run_backfill("e2")
        self.assertIn("FAILED to build e2", log)
        self.assertIn("1 of 3 events could not be built", log)

    def test_an_incoherent_event_is_rejected_rather_than_published(self):
        # The archive is a directory of files a reader is sent to, so it must
        # not hold one the site would refuse to serve. Validating the whole
        # archive afterwards instead meant one incoherent event failed the run
        # and threw away the ten beside it that were fine.
        code, built, log, manifest = self.run_backfill(None, breaks_coherence="e3")
        self.assertEqual(code, 0)
        self.assertEqual({e["slug"] for e in manifest["events"]}, {"e1", "e2"})
        self.assertIn("REJECTED e3", log)
        self.assertIn("does not divide 8 into equal sides", log)

    def test_the_newest_event_failing_fails_the_run(self):
        # It is what the feed is titled after and what a scheduled run exists to
        # publish. Skipping it would report success over an unchanged site.
        code, built, log, exc = self.run_backfill("e1")
        self.assertIsNone(code)
        self.assertIsInstance(exc, KeyError)


class TestTheTableSettlesWhatAPostIs(unittest.TestCase):
    """Where the text and the table disagree, the table is the content.

    Konami published YCS Anaheim's standings under the slug
    ycs-anaheim-round-12-pairings. The page is headed "YCS Anaheim: Standings
    After Round 11" and holds a standings table; only the slug says pairings,
    and the slug is what won. Read as pairings, every row was missing the
    columns pairings have -- which is how a seven-event backfill came down on
    its last event with KeyError: 'table'.
    """

    URL = "https://yugiohblog.konami.com/2025/ycs/ycs-anaheim-round-12-pairings/"

    def test_the_real_page_reads_as_the_standings_it_is(self):
        doc = _page("YCS Anaheim: Standings After Round 11",
                    ["Rank", "Player Name"],
                    [["1", "Alex Anthony Bergeron"], ["2", "Cameron Taylor Neal"]])
        post = parse_post(doc, self.URL)
        self.assertEqual(post.kind, "standings")
        self.assertEqual(len(post.table.rows), 2)

    def test_the_round_follows_the_corrected_kind(self):
        doc = _page("YCS Anaheim: Standings After Round 11",
                    ["Rank", "Player Name"], [["1", "Alex Anthony Bergeron"]])
        self.assertEqual(parse_post(doc, self.URL).round, 11)

    def test_final_standings_under_a_pairings_slug_are_not_the_final(self):
        # The round has to be read after the kind is settled, not before.
        # "Final Standings" is the table at the end of Swiss, not the last round
        # of the bracket -- but only a post already known to be standings gets
        # read that way, and a slug saying "pairing" was enough to stop it. The
        # whole Swiss field would have been filed under the Final.
        doc = _page("YCS Anaheim: Final Standings", ["Rank", "Player Name", "Points"],
                    [["1", "Alex Anthony Bergeron", "36"]])
        post = parse_post(doc, "https://yugiohblog.konami.com/2025/ycs/"
                               "ycs-anaheim-final-pairing/")
        self.assertEqual(post.kind, "standings")
        self.assertIsNone(post.round, "the end of Swiss is not the Final")

    def test_a_pairings_post_with_pairings_in_it_is_left_alone(self):
        doc = _page("YCS Anaheim: Round 12 Pairings", PAIR_HEAD,
                    [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]])
        post = parse_post(doc, self.URL)
        self.assertEqual((post.kind, post.round), ("pairings", 12))

    def test_a_news_post_quoting_a_table_is_still_news(self):
        # Narrow on purpose: only between pairings and standings, and only when
        # both are confident. An announcement that happens to carry a table is
        # not a round of anything.
        doc = _page("Prize Wall Restocked", ["Rank", "Player Name"],
                    [["1", "Ann Alpha"]])
        self.assertEqual(parse_post(doc, "https://x/prize-wall/").kind, "news")


class TestASideEventIsNotATournament(unittest.TestCase):
    """A format has to have rounds someone played.

    YCS Anaheim's eight Genesys posts are two feature matches, some news and a
    winner, covering a Genesys Invitational held alongside the main event. They
    name a Top 8, so a Top 8 round was built -- with no matches in it, in a
    format with no Duelists and no Swiss rounds. check-rounds.py rejected the
    published file: "Genesys Top 8: 0 matches is not a power of two".
    """

    def event(self, *extra):
        from build import build_event
        return build_event("YCS Anaheim", [
            _src("https://x/p1/", "YCS Anaheim: Round 1 Pairings (Advanced Format)",
                 PAIR_HEAD, [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
            _src("https://x/s1/", "YCS Anaheim: Standings After Round 1 (Advanced Format)",
                 ["Rank", "Player Name", "Points"], [["1", "Ann Alpha", "3"]]),
            *extra])

    def genesys_features(self):
        return [_src("https://x/f1/",
                     "Genesys Invitational Top 8 Feature Match: Hanko Chow vs. Steven Lee",
                     ["a"], []),
                _src("https://x/f2/",
                     "Genesys Invitational Top 8 Feature Match: Siming Yang vs. Jordan Ng",
                     ["a"], [])]

    def test_a_format_covered_only_by_feature_matches_is_not_built(self):
        formats = self.event(*self.genesys_features())["formats"]
        self.assertEqual([f["format"] for f in formats], ["Advanced"])

    def test_the_tournament_beside_it_is_unaffected(self):
        formats = self.event(*self.genesys_features())["formats"]
        self.assertEqual(len(formats[0]["rounds"]), 1)
        self.assertEqual(len(formats[0]["rounds"][0]["pairings"]), 1)

    def test_a_format_with_rounds_of_its_own_is_built(self):
        # The guard must not throw out a real second tournament: Montreal runs
        # Advanced and Genesys side by side and both have pairings.
        formats = self.event(
            _src("https://x/g1/", "YCS Anaheim: Round 1 Pairings (Genesys Format)",
                 PAIR_HEAD, [["1", "Cy", "Gamma", "vs.", "Di", "Delta"]]),
            *self.genesys_features())["formats"]
        self.assertEqual({f["format"] for f in formats}, {"Advanced", "Genesys"})


class TestATeamBracketIsStillABracket(unittest.TestCase):
    """A Team YCS enters three Duelists a side.

    Its Top 8 is eight teams playing four matches of three duels, listed
    individually: twelve rows. Requiring a power of two rejected TEAM YCS Las
    Vegas outright -- three events, over brackets that were perfectly well
    formed.
    """

    CHECKER = Path(__file__).resolve().parent.parent / ".github/scripts/check-rounds.py"

    def check(self, cut):
        """cut: [(label, matches)]. Returns (exit code, output)."""
        import json, subprocess, tempfile
        pair = lambda i: {"table": i, "a": f"A{i}", "aRec": None, "aDeck": None,
                          "b": f"B{i}", "bRec": None, "bDeck": None}
        rounds, n = [], 0
        for label, matches in cut:
            n += 1
            rounds.append({"id": label.replace(" ", ""), "label": label,
                           "phase": "Top cut", "state": "done", "order": 100 + n,
                           "standingsAfter": 1, "pairings": [pair(i) for i in range(matches)],
                           "standings": [], "source": "https://x/"})
        data = {"event": "TEAM YCS Las Vegas", "sample": False, "coverageBy": "Konami",
                "drawsPossible": False, "updated": "2026-04-19", "ongoing": False,
                "formats": [{"format": None, "swissRounds": 1, "duelists": 389,
                             "rounds": [{"id": "1", "label": "R1", "phase": "Swiss",
                                         "state": "done", "order": 1, "pairings": [pair(0)],
                                         "standings": [], "source": "https://x/"}] + rounds}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(data, fh)
            path = fh.name
        return run_checker(path)

    def test_three_duelists_a_side_is_a_valid_bracket(self):
        code, out = self.check([("Top 8", 12), ("Top 4", 6), ("Final", 3)])
        self.assertEqual(code, 0, out)

    def test_one_duelist_a_side_still_is_too(self):
        code, out = self.check([("Top 8", 4), ("Top 4", 2), ("Final", 1)])
        self.assertEqual(code, 0, out)

    def test_a_bracket_that_changes_its_mind_is_rejected(self):
        # Twelve in the Top 8 and two in the Top 4 is not a team event playing
        # fewer duels; it is a round that lost rows.
        code, out = self.check([("Top 8", 12), ("Top 4", 2), ("Final", 3)])
        self.assertEqual(code, 1)
        self.assertIn("disagree on how many Duelists a side", out)

    def test_a_round_that_does_not_divide_evenly_is_rejected(self):
        code, out = self.check([("Top 8", 5)])
        self.assertEqual(code, 1)
        self.assertIn("does not divide 8 into equal sides", out)

    def test_the_width_is_read_from_the_label(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("checker", self.CHECKER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.bracket_width("Top 64"), 64)
        self.assertEqual(mod.bracket_width("Final"), 2)
        # The blog writes the last two stages by name as well, and the builder
        # already treats those as the same stages.
        self.assertEqual(mod.bracket_width("Semifinals"), 4)
        self.assertEqual(mod.bracket_width("Quarterfinals"), 8)
        self.assertIsNone(mod.bracket_width("R7"))


class TestTeamEvents(unittest.TestCase):
    """A Team YCS enters three Duelists a side.

    Three layouts the parser had never seen, and everything downstream works on
    entrants, so the whole of the difference is what an entrant is.

        standings   Rank | Player Name
                    1    | Road of the King: Yacine S., Francisco O., Patrick H.

        Swiss       Table | Team 1 | Team 2          -- no vs. column at all
                    Team  | Cuspy Way | We are just here
                    1     | Billy de la Cruz Gadier | Piersen Matthew Sukienik

        top cut     Table | Duelist 1 Name | Duelist 1 Deck Type | vs. | ...
                          | Ares |  | vs. | 3 Lil Pigs |
                    1     | Kevin QC Rodrigues Goncalves | Artmage K9 | vs. | ...
    """

    SWISS = _page("TEAM YCS Las Vegas: Round 3 Pairings",
                  ["Table", "Team 1", "Team 2"],
                  [["Team", "Cuspy Way", "We are just here"],
                   ["1", "Billy de la Cruz Gadier", "Piersen Matthew Sukienik"],
                   ["2", "Timothy William Roma", "Zachary Paul Hutson"],
                   ["3", "Jordan Eric NC Smith", "Joseph Albert Crask"],
                   ["Team", "Lazy Dog", "Strait of Hermos"],
                   ["4", "Nicolas Hieu CA Phan", "Yaozhong NY Liu"],
                   ["5", "Anthony NY Xu", "Michael CA Park"],
                   ["6", "Wenbo NY Gao", "Nathan Shigeo Shimada"]])

    CUT = _page("TEAM YCS Las Vegas: Top 8 Pairings with Deck Types",
                ["Table", "Duelist 1 Name", "Duelist 1 Deck Type", "vs.",
                 "Duelist 2 Name", "Duelist 2 Deck Type"],
                [["", "Ares", "", "vs.", "3 Lil Pigs", ""],
                 ["1", "Kevin QC Rodrigues Goncalves", "Artmage K9", "vs.",
                  "William Russell Candia", "Azamina Mitsurugi Yummy"],
                 ["2", "Matthieu Nicolas Bricard", "Mitsurugi", "vs.",
                  "Edwin Martin Strom IV", "Fiendsmith Yummy"],
                 ["3", "Pierre FRA Burgals", "Bystial @Ignister Maliss", "vs.",
                  "Michael Joseph Ehresman", "Branded Mitsurugi Sky Striker"]])

    STANDINGS = _page("TEAM YCS Las Vegas: Standings After Round 11",
                      ["Rank", "Player Name"],
                      [["1", "Road of the King: Yacine S., Francisco O., Patrick H."],
                       ["2", "Ares: Kevin R., Matthieu B., Pierre B."],
                       ["3", "Neal 4 Papa: Cameron N., Cristian U., Antonio P."]])

    # ---- the Swiss layout, which has no vs. column ----

    def test_a_table_with_no_versus_column_is_still_pairings(self):
        # Eleven of TEAM YCS Las Vegas's twelve Swiss rounds are written this
        # way, and every one of them was dropped as an unreadable table.
        self.assertEqual(parse_post(self.SWISS).table.kind, "pairings")

    def test_a_team_match_is_one_row_holding_its_duels(self):
        rows = parse_post(self.SWISS).table.rows
        self.assertEqual(len(rows), 2, "two team matches, not six duels")
        self.assertEqual((rows[0]["a"]["name"], rows[0]["b"]["name"]),
                         ("Cuspy Way", "We are just here"))
        self.assertEqual([d["a"]["name"] for d in rows[0]["duels"]],
                         ["Billy de la Cruz Gadier", "Timothy William Roma",
                          "Jordan Eric Smith"])

    def test_the_match_is_at_the_first_table_its_duels_are_played_on(self):
        rows = parse_post(self.SWISS).table.rows
        self.assertEqual([r["table"] for r in rows], [1, 4])
        self.assertEqual([d["table"] for d in rows[1]["duels"]], [4, 5, 6])

    def test_neither_side_is_swallowed_by_a_separator_that_is_not_there(self):
        # The reader split the columns on the vs. column and skipped it. With no
        # vs. column the fallback skipped a real one instead, and every match
        # came back a name short.
        rows = parse_post(self.SWISS).table.rows
        for r in rows:
            self.assertTrue(r["a"]["name"] and r["b"]["name"], r)

    # ---- the top cut layout, which has one ----

    def test_the_cut_layout_names_the_teams_too(self):
        rows = parse_post(self.CUT).table.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["a"]["name"], rows[0]["b"]["name"]),
                         ("Ares", "3 Lil Pigs"))

    def test_a_deck_belongs_to_the_Duelist_not_the_team(self):
        row = parse_post(self.CUT).table.rows[0]
        self.assertIsNone(row["a"]["deck"], "a team does not play a deck")
        self.assertEqual([d["a"]["deck"] for d in row["duels"]],
                         ["Artmage K9", "Mitsurugi", "Bystial @Ignister Maliss"])

    def test_a_singles_event_is_untouched(self):
        # Every row is a match of its own, exactly as before, and carries no
        # duels for the page to render.
        rows = load("pairings-round13").table.rows
        self.assertEqual(rows[0]["a"]["name"], "George Lucas Sacco")
        self.assertNotIn("duels", rows[0])

    # ---- standings ----

    def test_a_standings_row_is_a_team_and_its_members(self):
        rows = parse_post(self.STANDINGS).table.rows
        self.assertEqual(rows[0]["name"], "Road of the King")
        self.assertEqual(rows[0]["members"], ["Yacine S.", "Francisco O.", "Patrick H."])

    def test_the_team_name_is_left_exactly_as_printed(self):
        from parse import split_team
        # Neither the comma rule nor the region rule applies to a name someone
        # chose: normalise_name exists to turn "Gouge, Justin" into "Justin
        # Gouge", and strip_region to take province codes off people.
        self.assertEqual(split_team("TCG QC Masters: A B., C D.")["name"],
                         "TCG QC Masters")

    def test_the_table_decides_together_not_row_by_row(self):
        # One oddly punctuated Duelist's name would otherwise be read as a team
        # of one in a table of individuals.
        doc = _page("Standings After Round 11", ["Rank", "Player Name", "Points"],
                    [["1", "Francisco Andres Osorio Bobadilla", "36"],
                     ["2", "Nickname: The Wall", "33"],
                     ["3", "Julien Leo Kehon", "33"]])
        rows = parse_post(doc).table.rows
        self.assertEqual(rows[1]["name"], "Nickname: The Wall")
        self.assertNotIn("members", rows[1])

    # ---- what the event comes out as ----

    def sources(self):
        from build import Source
        return [Source("https://x/r3/", parse_post(self.SWISS, "https://x/r3/"), "12:00"),
                Source("https://x/s3/", parse_post(self.STANDINGS, "https://x/s3/"), "13:00")]

    def event(self):
        import io
        from contextlib import redirect_stdout
        from build import build_event
        with redirect_stdout(io.StringIO()):
            return build_event("TEAM YCS Las Vegas", self.sources(), updated="2026-04-19")

    def test_the_entrants_are_teams_and_the_data_says_so(self):
        # The page has no way to tell from the rows: a team match reads exactly
        # like a match. Left unsaid, 389 teams are shown as 389 Duelists.
        fmt = self.event()["formats"][0]
        self.assertEqual(fmt["entrant"], "Team")
        self.assertEqual(fmt["duelists"], 3)

    def test_an_ordinary_event_says_so_too(self):
        from build import build_event
        ev = build_event("YCS Montréal", _sources())
        self.assertTrue(all(f["entrant"] == "Duelist" for f in ev["formats"]))

    def test_the_duels_reach_the_page(self):
        fmt = self.event()["formats"][0]
        match = fmt["rounds"][0]["pairings"][0]
        self.assertEqual((match["a"], match["b"]), ("Cuspy Way", "We are just here"))
        self.assertEqual([d["a"] for d in match["duels"]][:1], ["Billy de la Cruz Gadier"])

    def test_the_roster_reaches_the_page(self):
        fmt = self.event()["formats"][0]
        row = next(r for r in fmt["rounds"] if r["standings"])["standings"][0]
        self.assertEqual(row["members"], ["Yacine S.", "Francisco O.", "Patrick H."])

class TestAFeatureMatchThatNamesNobody(unittest.TestCase):
    """A round can carry more than one feature match, and the newest wins.

    Only among the ones that can be read, though. YCS Philadelphia's Top 64 had
    two, and the newer was "Top 64 Feature Match: Hani Jawhari Versus Nicholas
    Scarangella" -- spelled out. The players could not be parsed out of it, so
    the round was left holding a feature naming nobody, beside no pairings and
    no standings, and the whole event was rejected for the empty round.
    """

    def test_the_separator_is_read_spelled_out(self):
        from naming import feature_players
        self.assertEqual(
            feature_players("Top 64 Feature Match: Hani Jawhari Versus Nicholas Scarangella"),
            ("Hani Jawhari", "Nicholas Scarangella"))

    def test_the_abbreviations_still_work(self):
        from naming import feature_players
        for sep in ("vs.", "vs", "VS.", "Versus"):
            self.assertEqual(feature_players(f"Round 5 Feature Match: A One {sep} B Two"),
                             ("A One", "B Two"), sep)

    def test_versus_inside_a_word_is_not_a_separator(self):
        from naming import feature_players
        # It has to be surrounded by spaces, or a name carrying the letters
        # splits itself in half and the round reports two Duelists who are one.
        self.assertIsNone(feature_players("Round 5 Feature Match: Alvsson Bergman"))

    def feature(self, title, posted):
        return _src(f"https://x/{posted}/", title, ["a"], [], posted=posted)

    def round_features(self, *feature_sources):
        import io
        from contextlib import redirect_stdout
        from build import build_event
        sources = [
            _src("https://x/p/", "Round 4 Pairings (Advanced Format)", PAIR_HEAD,
                 [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
            *feature_sources,
        ]
        with redirect_stdout(io.StringIO()):
            ev = build_event("YCS Philadelphia", sources)
        return ev["formats"][0]["rounds"][0]["features"]

    def test_every_feature_match_the_round_carried_is_kept(self):
        # 102 of the 357 rounds that have a feature match have more than one,
        # and YCS Montreal's Top 4 had three. Showing the best of them threw
        # away two thirds of the Duelists the blog wrote about that round.
        got = self.round_features(
            self.feature("Advanced Format Round 4 Feature Match: Ryan Yu vs. Dominic Couch", "10:00"),
            self.feature("Advanced Format Round 4 Feature Match: C Three vs. D Four", "18:00"))
        self.assertEqual([f["a"]["name"] for f in got], ["C Three", "Ryan Yu"],
                         "both, newest first")

    def test_a_feature_naming_nobody_is_dropped_rather_than_shown_empty(self):
        # The title is the only structured thing about a feature post. YCS
        # Philadelphia's newer Top 64 post was "Hani Jawhari and friends", and
        # a panel of nobodies is worse than a shorter panel.
        got = self.round_features(
            self.feature("Advanced Format Round 4 Feature Match: Ryan Yu vs. Dominic Couch", "10:00"),
            self.feature("Advanced Format Round 4 Feature Match: Hani Jawhari and friends", "18:00"))
        self.assertEqual([f["a"]["name"] for f in got], ["Ryan Yu"])

    def test_a_round_covered_only_by_feature_matches_is_still_a_round(self):
        # Five of the 2026 North America WCQ's rounds arrived that way. The
        # features are collected apart from the tables now, so a round whose
        # only source is a feature match has to keep its place among the ones
        # that have tables.
        import io
        from contextlib import redirect_stdout
        from build import build_event
        with redirect_stdout(io.StringIO()):
            ev = build_event("YCS Philadelphia", [
                _src("https://x/p/", "Round 4 Pairings (Advanced Format)", PAIR_HEAD,
                     [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
                self.feature("Advanced Format Round 5 Feature Match: Ryan Yu vs. Dominic Couch", "10:00")])
        rounds = ev["formats"][0]["rounds"]
        self.assertEqual([r["label"] for r in rounds], ["R4", "R5"])
        self.assertEqual(rounds[1]["features"][0]["a"]["name"], "Ryan Yu")
        self.assertEqual(rounds[1]["pairings"], [])


class TestRebuildingWhatAnOlderBuilderWrote(unittest.TestCase):
    """The archive is built once per event and then left alone, so a change to
    what the builder produces reaches only the events built after it."""

    def setUp(self):
        import tempfile
        from pathlib import Path as P
        self.tmp = P(tempfile.mkdtemp())

    def write(self, slug, built=None):
        import archive
        event = {"event": slug, "sample": False, "coverageBy": "Konami",
                 "updated": "2026-01-01", "formats": []}
        if built is not None:
            event["built"] = built
        archive.write_event(self.tmp, slug, event, [])

    def test_a_file_from_an_older_builder_is_behind(self):
        import archive
        self.write("old", built=1)
        self.write("current", built=2)
        self.assertEqual(archive.behind(self.tmp, 2), {"old"})

    def test_a_file_with_no_marker_at_all_is_behind(self):
        # Everything in the archive today predates the marker.
        import archive
        self.write("ancient")
        self.assertEqual(archive.behind(self.tmp, 2), {"ancient"})

    def test_what_a_builder_writes_says_which_builder_wrote_it(self):
        from build import build_event, BUILD_VERSION
        self.assertEqual(build_event("x", [])["built"], BUILD_VERSION)

    def ranked(self, *slugs):
        return [(s, [{"kind": "pairings"}, {"kind": "standings"}], f"2026-01-0{i+1}")
                for i, s in enumerate(slugs)]

    def plan(self, *, done, backfill=0, rebuild=0, behind=frozenset(), slugs=None):
        from unittest import mock
        import run
        ranked = self.ranked(*(slugs or ("a", "b", "c", "d")))
        with mock.patch.object(run, "events_by_recency", lambda e: ranked):
            return [s for s, _, _ in run.plan([], done, backfill, rebuild, behind)]

    def test_a_rebuild_takes_events_the_backfill_never_would(self):
        # The backfill asks what is missing; this asks what is out of date, and
        # every one of these is already in the archive.
        got = self.plan(done={"a", "b", "c", "d"}, rebuild=2, behind={"b", "c", "d"})
        self.assertEqual(got, ["a", "b", "c"], "the newest, then two behind it")

    def test_a_rebuild_stops_at_the_number_asked_for(self):
        got = self.plan(done={"a", "b", "c", "d"}, rebuild=1, behind={"b", "c", "d"})
        self.assertEqual(got, ["a", "b"])

    def test_events_that_are_current_are_left_alone(self):
        got = self.plan(done={"a", "b", "c", "d"}, rebuild=5, behind={"d"})
        self.assertEqual(got, ["a", "d"])

    def test_nothing_is_built_twice_in_one_run(self):
        # The newest event is always rebuilt, and it is usually also behind.
        got = self.plan(done={"a", "b", "c", "d"}, rebuild=2, behind={"a", "b", "c", "d"})
        self.assertEqual(got, ["a", "b", "c"])
        self.assertEqual(len(got), len(set(got)))

    def test_an_event_the_backfill_took_is_not_rebuilt_after_it(self):
        # An event can be both missing and out of date -- it is missing, so
        # whatever version it lacks it lacks. Building it twice in one run
        # spends the budget twice and writes the same file twice.
        got = self.plan(done={"a", "b"}, backfill=2, rebuild=1, behind={"c"})
        self.assertEqual(got, ["a", "c", "d"])
        self.assertEqual(len(got), len(set(got)), "and no event appears twice")

    def test_a_backfill_and_a_rebuild_do_not_eat_each_others_budget(self):
        # Opposite questions, separate counts: two missing and one stale is
        # three events, not whichever two came first.
        got = self.plan(done={"a", "b"}, backfill=2, rebuild=1, behind={"b"})
        self.assertEqual(got, ["a", "c", "d", "b"])

    def test_without_being_asked_a_run_rebuilds_nothing(self):
        # An event already in the archive costs the same minutes to fetch again
        # as it did the first time, so this never happens by accident.
        got = self.plan(done={"a", "b", "c", "d"}, behind={"b", "c", "d"})
        self.assertEqual(got, ["a"])


class TestTheRebuildIsWiredUp(unittest.TestCase):
    """main() reads the archive and hands the plan what it found."""

    def setUp(self):
        import tempfile
        from pathlib import Path as P
        self.tmp = P(tempfile.mkdtemp())

    def run_main(self, extra_argv):
        """One run of main() against a fake blog and a two-event archive."""
        import io, sys, types, archive, run
        from contextlib import redirect_stdout
        from unittest import mock
        root = self.tmp / "events"
        for slug, built in (("newest", 2), ("stale", 1)):
            archive.write_event(root, slug, {"event": slug, "sample": False,
                                             "coverageBy": "Konami", "built": built,
                                             "updated": "2026-01-01", "formats": []}, [])
        ranked = [(s, [{"kind": "pairings"}, {"kind": "standings"}], "2026-01-01")
                  for s in ("newest", "stale")]
        built = []
        def fake_build_one(f, slug, posts, ended, limit):
            built.append(slug)
            return ({"event": slug, "sample": False, "coverageBy": "Konami",
                     "built": 2, "updated": ended, "formats": []}, [], [])
        argv = ["run.py", "--cache", f"{self.tmp}/cache", "--archive", str(root),
                "--manifest", f"{self.tmp}/events.json", *extra_argv]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(run, "Fetcher",
                               lambda **kw: types.SimpleNamespace(get=lambda u, **k: "<urlset/>")), \
             mock.patch.object(run, "parse_sitemap_index", lambda x: []), \
             mock.patch.object(run, "events_by_recency", lambda e: ranked), \
             mock.patch.object(run, "coherence_problem", lambda *a: None), \
             mock.patch.object(run, "build_one", fake_build_one), \
             redirect_stdout(io.StringIO()):
            run.main()
        return built

    def test_asking_for_a_rebuild_reaches_the_stale_event(self):
        self.assertEqual(self.run_main(["--rebuild", "5"]), ["newest", "stale"])

    def test_not_asking_leaves_it_alone(self):
        # The newest event is always rebuilt because it may still be running.
        # Nothing else is, without being asked.
        self.assertEqual(self.run_main([]), ["newest"])

    def test_the_archive_is_not_read_unless_a_rebuild_was_asked_for(self):
        # Not a behaviour, a cost: this reads every event file, and the
        # scheduled run fires every ten minutes against an archive of 145 of
        # them, some over ten megabytes.
        import archive, run
        from unittest import mock
        with mock.patch.object(archive, "behind",
                               mock.Mock(side_effect=AssertionError("read the archive"))):
            self.assertEqual(self.run_main([]), ["newest"])


class TestARejectedEventIsRemembered(unittest.TestCase):
    """Otherwise the backfill cannot get past one.

    A rejected event leaves nothing in the archive, so the next run does not
    count it as attempted, so it is picked again -- and because the plan takes
    the newest events missing from the archive, the same failures are retried
    first every time and the run never reaches the ones behind them. Five
    batches of ten landed 21 events and then stopped dead, every batch spending
    itself on the same seven rejections.
    """

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_a_rejection_counts_as_attempted(self):
        import archive
        archive.reject_event(self.tmp, "2018-11-sao-paulo-brazil", "Top 8: nobody advanced")
        self.assertEqual(archive.attempted(self.tmp), {"2018-11-sao-paulo-brazil"})

    def test_a_rejection_is_not_coverage(self):
        import archive
        archive.reject_event(self.tmp, "2018-11-sao-paulo-brazil", "Top 8: nobody advanced")
        self.assertEqual(archive.scraped(self.tmp), set())
        self.assertEqual(archive.build_manifest(self.tmp)["events"], [])

    def test_the_reason_is_kept_where_it_can_be_read(self):
        # A line in a log expires; what the archive is missing and why should be
        # a thing in the repository.
        import archive, json
        archive.reject_event(self.tmp, "sp", "Top 8: nobody advanced from Top 16")
        got = json.loads(archive.rejected_path(self.tmp, "sp").read_text())
        self.assertEqual(got["reason"], "Top 8: nobody advanced from Top 16")

    def test_deleting_the_record_tries_the_event_again(self):
        import archive
        archive.reject_event(self.tmp, "sp", "why")
        archive.rejected_path(self.tmp, "sp").unlink()
        self.assertEqual(archive.attempted(self.tmp), set())

    def run_backfill(self, archive_root, breaks_coherence):
        """One run of main(), building three events, one of them incoherent."""
        import io, json, types
        from contextlib import redirect_stdout
        from unittest import mock
        import run
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "events.json").read_text())
        good = json.loads((root / manifest["events"][0]["path"]).read_text())
        planned = []

        def fake_build_one(f, slug, posts, ended, limit):
            planned.append(slug)
            event = {**json.loads(json.dumps(good)), "event": slug, "updated": ended}
            if slug == breaks_coherence:
                cut = [r for r in event["formats"][0]["rounds"] if r["phase"] == "Top cut"]
                cut[0]["pairings"] = cut[0]["pairings"][:3]
            return (event, [], [])

        def plan(entries, done, backfill, rebuild=0, behind=frozenset()):
            return [(s, [{"kind": "pairings"}], f"2026-0{i}-01")
                    for i, s in enumerate(("e1", "e2", "e3"), start=1) if s not in done]

        log = io.StringIO()
        argv = ["run.py", "--cache", f"{self.tmp}/cache", "--archive", str(archive_root),
                "--manifest", f"{self.tmp}/events.json"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(run, "Fetcher",
                               lambda **kw: types.SimpleNamespace(get=lambda u, **k: "<urlset/>")), \
             mock.patch.object(run, "plan", plan), \
             mock.patch.object(run, "parse_sitemap_index", lambda x: []), \
             mock.patch.object(run, "build_one", fake_build_one), \
             redirect_stdout(log):
            run.main()
        return planned, log.getvalue()

    def test_the_scraper_records_what_it_rejected(self):
        # Tested through main(), not through the archive functions alone: the
        # memory only works if the run actually writes to it, and a helper
        # nothing calls is how this whole sequence of failures started.
        import archive
        root = self.tmp / "events"
        self.run_backfill(root, breaks_coherence="e2")
        self.assertEqual(archive.scraped(root), {"e1", "e3"})
        self.assertIn("e2", archive.attempted(root))

    def test_the_next_run_does_not_spend_itself_on_the_same_failure(self):
        # Five batches of ten landed 21 events and then stopped dead, every one
        # of them retrying the same seven rejections before anything else.
        root = self.tmp / "events"
        self.run_backfill(root, breaks_coherence="e2")
        planned, _ = self.run_backfill(root, breaks_coherence="e2")
        self.assertEqual(planned, [], "the rejected event was picked again")


class TestTwoPostsClaimingOneRound(unittest.TestCase):
    """Whichever arrived last used to win, which is not a rule at all.

    Two posts can claim one round: the same table published twice, or two
    events sharing a weekend. The January 2022 Remote Duel YCS did the latter
    with the Latin America one -- both published a Top 32, both landed on the
    same event, and one of the two had a table that read as empty.

    The same coverage then built differently from one run to the next. That is
    how an event passed a local check and was rejected in CI on identical data.
    """

    def pairings(self, title, rows, posted):
        return _src(f"https://x/{posted}/", title, PAIR_HEAD, rows, posted=posted)

    def rows(self, n, prefix):
        return [[str(i + 1), f"{prefix}{i}", "One", "vs.", f"{prefix}{i}", "Two"]
                for i in range(n)]

    def build(self, sources):
        import io
        from contextlib import redirect_stdout
        from build import build_event
        with redirect_stdout(io.StringIO()):
            return build_event("Remote Duel YCS", sources)

    def test_the_fuller_table_wins(self):
        full = self.pairings("Top 32 Pairings (Advanced Format)", self.rows(16, "A"), "10:00")
        empty = self.pairings("Top 32 Pairings (Advanced Format)", [], "18:00")
        for order in ([full, empty], [empty, full]):
            rounds = self.build(list(order))["formats"][0]["rounds"]
            self.assertEqual(len(rounds[0]["pairings"]), 16,
                             "an empty table beat a full one")

    def test_the_answer_does_not_depend_on_the_order_they_arrive_in(self):
        one = self.pairings("Top 32 Pairings (Advanced Format)", self.rows(16, "A"), "10:00")
        two = self.pairings("Top 32 Pairings (Advanced Format)", self.rows(16, "B"), "18:00")
        seen = {tuple(p["a"] for p in self.build(list(o))["formats"][0]["rounds"][0]["pairings"])
                for o in ([one, two], [two, one])}
        self.assertEqual(len(seen), 1, "the same coverage built two different ways")

    def test_between_two_equal_tables_the_newer_wins(self):
        older = self.pairings("Top 32 Pairings (Advanced Format)", self.rows(16, "Old"), "10:00")
        newer = self.pairings("Top 32 Pairings (Advanced Format)", self.rows(16, "New"), "18:00")
        pairs = self.build([older, newer])["formats"][0]["rounds"][0]["pairings"]
        self.assertTrue(pairs[0]["a"].startswith("New"), pairs[0]["a"])

    def test_standings_follow_the_same_rule(self):
        head = ["Rank", "Player Name", "Points"]
        full = _src("https://x/a/", "Standings After Round 5 (Advanced Format)", head,
                    [[str(i + 1), f"Duelist {i}", "9"] for i in range(20)], posted="10:00")
        empty = _src("https://x/b/", "Standings After Round 5 (Advanced Format)", head,
                     [], posted="18:00")
        rounds = self.build([full, empty])["formats"][0]["rounds"]
        self.assertEqual(len(rounds[0]["standings"]), 20)


class TestTheEventListReadsAsNames(unittest.TestCase):
    """What the picker shows has to identify the event.

    Eighteen of the archive's fifty-one were listed under something that did
    not: five North American WCQs spelled five ways, no two of them saying
    which year's, and labels like "11 10 Columbus" and "201504 Bogota D C
    Colombia" that are the slug with its hyphens taken out.
    """

    def name(self, derived, slug, ended="2026-01-01", named=True):
        from naming import canonical_name
        return canonical_name(derived, slug, ended, named=named)[0]

    def location(self, derived, slug, ended="2026-01-01", named=True):
        from naming import canonical_name
        return canonical_name(derived, slug, ended, named=named)[1]

    # ---- the qualifiers ----

    def test_every_spelling_of_the_north_american_qualifier_agrees(self):
        for derived, slug in (("NAWCQ", "2026-north-america-wcq"),
                              ("North America WCQ", "2018-north-america-wcq"),
                              ("2013 North American Wcq", "2013-north-american-wcq")):
            year = slug[:4]
            self.assertEqual(self.name(derived, slug, f"{year}-07-01"),
                             f"North America WCQ {year}", slug)

    def test_the_other_regions_read_the_same_way(self):
        self.assertEqual(self.name("Central America WCQ", "2024-central-america-wcq",
                                   "2024-06-01"), "Central America WCQ 2024")
        self.assertEqual(self.name("South America WCQ", "2019-south-america-wcq",
                                   "2019-06-01"), "South America WCQ 2019")

    def test_a_qualifier_is_renamed_even_when_the_coverage_named_it(self):
        # "NAWCQ" is a name -- fifteen of that event's posts use it -- and it is
        # not one that says which year's, and there is one every year.
        self.assertEqual(self.name("NAWCQ", "2025-north-america-wcq", "2025-07-13"),
                         "North America WCQ 2025")

    def test_the_year_comes_from_the_event_not_from_its_last_edit(self):
        # The 2013 South American WCQ has coverage edited into 2014, and it is
        # not the 2014 one -- there was a 2014 one.
        self.assertEqual(self.name("WCQ", "2013-south-american-wcq-championships",
                                   "2014-01-31"), "South America WCQ 2013")

    def test_a_qualifier_with_no_year_anywhere_is_still_named(self):
        self.assertEqual(self.name("NAWCQ", "north-america-wcq", None),
                         "North America WCQ")

    def test_a_ycs_is_not_a_qualifier(self):
        self.assertEqual(self.name("YCS Montréal", "2026-08-quebec", "2026-08-16"),
                         "YCS Montréal")

    # ---- places ----

    def test_a_slug_that_names_only_a_place_is_a_ycs(self):
        for slug, want in (("11-10-columbus", "YCS Columbus"),
                           ("201503-guatemala", "YCS Guatemala"),
                           ("201509-monterrey", "YCS Monterrey"),
                           ("201603-santiago-chile", "YCS Santiago")):
            self.assertEqual(self.name(slug.replace("-", " ").title(), slug,
                                       named=False), want)

    def test_the_administrative_letters_are_not_part_of_the_city(self):
        # The D and C of bogota-d-c-colombia are Distrito Capital.
        self.assertEqual(self.name("201504 Bogota D C Colombia",
                                   "201504-bogota-d-c-colombia", named=False),
                         "YCS Bogota")

    def test_a_token_holding_a_digit_is_not_a_place(self):
        # 300th, 75thsjc, 201504 -- the date and the count.
        self.assertEqual(self.name("12 03 100Th", "12-03-100th", named=False),
                         "12 03 100Th")

    # ---- where it was held ----

    def test_the_country_is_kept_beside_the_name_not_inside_it(self):
        self.assertEqual(self.location("201603 Santiago Chile", "201603-santiago-chile",
                                       named=False), "Santiago, Chile")

    def test_a_city_of_several_words_comes_through_whole(self):
        # Split at a guess, "buenos-aires-argentina" is a city called Aires.
        self.assertEqual(
            self.name("201712 Buenos Aires Argentina", "201712-buenos-aires-argentina",
                      named=False), "YCS Buenos Aires")
        self.assertEqual(
            self.location("201712 Buenos Aires Argentina", "201712-buenos-aires-argentina",
                          named=False), "Buenos Aires, Argentina")

    def test_a_two_word_city_is_not_split_into_a_country(self):
        # san-diego-ca and atlantic-city are cities of two words. Taking the
        # last word as the country makes them "YCS San" in "San, Diego".
        for slug, want in (("201711-san-diego-ca", "YCS San Diego"),
                           ("atlantic-city-2013", "YCS Atlantic City")):
            self.assertEqual(self.name(slug.replace("-", " ").title(), slug,
                                       named=False), want, slug)
            self.assertIsNone(self.location(slug.replace("-", " ").title(), slug,
                                            named=False), slug)

    def test_no_country_in_the_slug_means_none_is_known(self):
        # "Columbus" alone would be the title with a word taken off rather than
        # anything the archive did not already say.
        self.assertIsNone(self.location("11 10 Columbus", "11-10-columbus", named=False))

    def test_a_country_the_coverage_wrote_into_the_name_is_taken_back_out(self):
        self.assertEqual(self.name("YCS Cancun, Mexico", "2024-10-cancun-mexico"),
                         "YCS Cancun")
        self.assertEqual(self.location("YCS Cancun, Mexico", "2024-10-cancun-mexico"),
                         "Cancun, Mexico")

    def test_the_city_is_what_is_left_after_the_kind_of_event(self):
        # Taking the last word instead made "YCS Guatemala City" a city called
        # "City".
        self.assertEqual(self.location("YCS Guatemala City, Guatemala", "201703-uds"),
                         "Guatemala City, Guatemala")

    def test_a_name_with_no_comma_says_nothing_about_where(self):
        self.assertIsNone(self.location("YCS Montréal", "2026-08-quebec"))

    def test_a_name_that_says_what_a_post_is_about_is_not_an_event_name(self):
        # YCS Charlotte's coverage agreed most often on "Top Table Update",
        # which is what a post contains. No event is called Standings.
        self.assertEqual(self.name("Top Table Update", "2022-ycs-charlotte"),
                         "YCS Charlotte")

    def test_a_bare_event_type_is_not_an_event_name(self):
        # YCS Hartford's settled on "YCS", which is thirty events.
        self.assertEqual(self.name("YCS", "202205-ycs-hartford-ct"), "YCS Hartford")

    def test_a_name_of_common_words_can_still_be_a_name(self):
        # "Genesys Championship" is a format and an event type and nothing else,
        # and is nonetheless what that tournament is called.
        self.assertEqual(
            self.name("Genesys Championship", "2026-north-america-genesys-championship"),
            "Genesys Championship")

    def test_the_slug_keeps_the_kind_of_event_it_says(self):
        # "2022-ycs-charlotte" is the YCS at Charlotte, not a YCS by default.
        from naming import place_name
        self.assertEqual(place_name("uds-2016-elsalvador")[0], "UDS Elsalvador")

    def test_a_place_is_only_guessed_at_when_there_was_nothing_to_go_on(self):
        # The coverage agreed on a name, so it is not overruled by a guess.
        self.assertEqual(self.name("YCS Anaheim", "201611-anaheim-ca", named=True),
                         "YCS Anaheim")

    def test_a_slug_saying_more_than_a_place_is_left_alone(self):
        # An event type written as initials is kept and the rest read as the
        # place. Any other word about the event is more than the guess should
        # overrule, so those slugs keep the fallback: "winter invitational" is
        # not a city, and neither is "undisputed".
        #
        # This used to be checked with "na-ygoc-2022", which is no longer an
        # example of anything: YGOC is what the North America qualifier was
        # called before 2023, so that slug is now answered by wcq_name long
        # before a place is guessed at.
        for slug in ("2024-undisputed-uds-championship",
                     "201703-uds-winter-invitational-las-vegas"):
            fallback = slug.replace("-", " ").title()
            self.assertEqual(self.name(fallback, slug, named=False), fallback, slug)

    def test_a_slug_of_nothing_but_a_date_is_left_alone(self):
        self.assertEqual(self.name("2018 09", "2018-09", named=False), "2018 09")

    def built(self, slug, ended, title):
        """One event through the scraper's own path, off a stubbed blog."""
        import io, types
        from contextlib import redirect_stdout
        import run
        head = f"{title}: " if title else ""      # "" for coverage naming nothing
        pages = {
            "https://x/p/": _page(f"{head}Round 1 Pairings", PAIR_HEAD,
                                  [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
            "https://x/s/": _page(f"{head}Standings After Round 1",
                                  ["Rank", "Player Name", "Points"], [["1", "Ann Alpha", "3"]]),
        }
        posts = [{"url": u, "kind": k, "lastmod": ended, "slug": k}
                 for u, k in (("https://x/p/", "pairings"), ("https://x/s/", "standings"))]
        fetcher = types.SimpleNamespace(get=lambda url, **kw: pages[url])
        with redirect_stdout(io.StringIO()):
            event, _, _ = run.build_one(fetcher, slug, posts, ended, 200)
        return event["event"]

    def test_the_scraper_settles_the_name_it_publishes(self):
        # Through build_one, not canonical_name alone: a rule the scraper does
        # not call renames nothing, and the archive went out under "NAWCQ".
        self.assertEqual(self.built("2026-north-america-wcq", "2026-07-12", "NAWCQ"),
                         "North America WCQ 2026")

    def test_the_scraper_guesses_a_place_only_when_it_has_to(self):
        # Its posts are headed "Round 1 Pairings" and nothing else, so there is
        # no name in the coverage and the label was "11 10 Columbus".
        self.assertEqual(self.built("11-10-columbus", "2011-10-23", ""),
                         "YCS Columbus")
        self.assertEqual(self.built("2026-08-quebec", "2026-08-16", "YCS Montréal"),
                         "YCS Montréal")


class TestATitleThatOnlyNamesTheEvent(unittest.TestCase):
    """Some posts are headed with the event and nothing else.

    Two of YCS Montreal's are both "YCS Montréal, Quebec 2026" -- one the main
    event information, one the public event information, and which is which is
    only in the slug. Split on the event's name, both came out as
    "YCS Montréal: , Quebec 2026": a comma, a place and a year, describing no
    post in particular and describing both of them identically.
    """

    MAIN = ("https://yugiohblog.konami.com/2026/event-information/"
            "ycs-montreal-quebec-2026-main-event-information/")
    PUBLIC = ("https://yugiohblog.konami.com/2026/event-information/"
              "ycs-montreal-quebec-2026-public-event-information/")

    def test_the_slug_says_what_the_title_does_not(self):
        from feed import titled
        self.assertEqual(titled("YCS Montréal", "YCS Montréal, Quebec 2026", self.MAIN),
                         "YCS Montréal: Main Event Information")

    def test_two_posts_with_one_title_are_told_apart(self):
        from feed import titled
        both = {titled("YCS Montréal", "YCS Montréal, Quebec 2026", u)
                for u in (self.MAIN, self.PUBLIC)}
        self.assertEqual(len(both), 2, both)

    def test_accents_do_not_stop_the_slug_matching_the_title(self):
        # The blog writes Montreal both ways and a slug cannot carry the accent,
        # so "Montréal" has to be recognised in "ycs-montreal-...".
        from feed import headline_from_url
        self.assertEqual(headline_from_url(self.MAIN, "YCS Montréal, Quebec 2026"),
                         "Main Event Information")

    def test_a_real_headline_is_left_alone(self):
        from feed import titled
        self.assertEqual(
            titled("YCS Montréal", "YCS Montréal: Round 13 Pairings",
                   "https://x/ycs-montreal-round-13-pairings/"),
            "YCS Montréal: Round 13 Pairings")

    def test_a_headline_that_merely_continues_the_name_is_the_trigger(self):
        # Not every title that starts with the event is one of these. "YCS
        # Columbus Top Tables Update" carries a headline; ", OH 2026" does not.
        from feed import titled
        self.assertEqual(
            titled("YCS Columbus", "YCS Columbus Top Tables Update",
                   "https://x/ycs-columbus-top-tables-update/"),
            "YCS Columbus: Top Tables Update")

    def test_a_title_with_a_headline_of_its_own_is_not_second_guessed(self):
        # No colon, so this reaches the same branch the broken ones do. The slug
        # says more than the title -- "round 5 advanced format" -- and none of
        # that is an improvement on a headline the post already has.
        from feed import titled
        self.assertEqual(
            titled("YCS Montréal", "YCS Montréal Top Tables Update",
                   "https://x/ycs-montreal-top-tables-update-round-5-advanced-format/"),
            "YCS Montréal: Top Tables Update")

    def test_a_slug_saying_nothing_more_leaves_the_title_as_it_was(self):
        # Nothing is invented when the slug repeats the title: better the
        # awkward comma than a headline made up out of nowhere.
        from feed import titled
        got = titled("YCS Columbus", "YCS Columbus, OH 2026",
                     "https://x/ycs-columbus-oh-2026/")
        self.assertEqual(got, "YCS Columbus: , OH 2026")


class TestAMistypedYearInASlug(unittest.TestCase):
    """The URL is the strongest signal there is, and it is typed by hand.

    Konami filed a July 2026 post -- round 13 of the 2026 North America WCQ --
    under the 2025 event's slug:

        /2026/championships/2025-north-america-wcq/nawcq-top-tables-update-round-13/

    Read at its word that is 2026 coverage sitting in the 2025 event.
    """

    def index(self, *extra):
        own = [(f"{y}/championships/{y}-north-america-wcq/nawcq-round-{i}-pairings",
                f"{y}-07-{10 + i:02d}")
               for y in (2025, 2026) for i in (1, 2, 3)]
        return parse_post_sitemap(urlset(*own, *extra))

    def assigned(self, *extra):
        return {r["slug"]: (r["event"], r["event_confidence"])
                for r in assign_events(self.index(*extra))}

    def test_a_post_dated_outside_its_event_goes_to_the_right_running(self):
        got = self.assigned(("2026/championships/2025-north-america-wcq/"
                             "nawcq-top-tables-update-round-13", "2026-07-12"))
        self.assertEqual(got["nawcq-top-tables-update-round-13"],
                         ("2026-north-america-wcq", "path+year"))

    def test_a_post_inside_its_event_is_left_where_the_url_puts_it(self):
        got = self.assigned()
        self.assertEqual(got["nawcq-round-1-pairings"][1], "path")

    def test_only_the_year_may_differ(self):
        # A slug that differs in more than its year is a different event, not
        # the same one mistyped. The Genesys Championship runs the same week as
        # the WCQ and its dates would hold this post perfectly well.
        rows = assign_events(parse_post_sitemap(urlset(
            # The 2025 running, so the stray is outside its window rather than
            # being the whole of it.
            *[(f"2025/championships/2025-north-america-wcq/nawcq-round-{i}-pairings",
               f"2025-07-1{i}") for i in (1, 2, 3)],
            *[(f"2026/championships/2026-north-america-genesys-championship/"
               f"genesys-round-{i}-pairings", f"2026-07-1{i}") for i in (1, 2, 3)],
            ("2026/championships/2025-north-america-wcq/"
             "nawcq-top-tables-update-round-13", "2026-07-12"))))
        got = {r["slug"]: (r["event"], r["event_confidence"]) for r in rows}
        # It may still land there by date -- nothing else is on those dates --
        # but not by the URL, which names a WCQ and not a Genesys Championship.
        self.assertNotEqual(got["nawcq-top-tables-update-round-13"][1], "path+year")

    def test_a_post_with_no_sibling_at_all_is_not_forced_into_one(self):
        got = self.assigned(("2026/championships/2025-north-america-wcq/"
                             "nawcq-top-tables-update-round-13", "2031-07-12"))
        self.assertNotEqual(got["nawcq-top-tables-update-round-13"][1], "path+year")

    def test_an_event_running_past_new_year_keeps_its_posts(self):
        # 2021-december-remote-duel-ycs publishes eight posts in January 2022,
        # under /2022/. The window follows the coverage rather than the slug, so
        # they fall inside it and nothing is moved.
        rows = assign_events(parse_post_sitemap(urlset(
            *[(f"2022/ycs/2021-december-remote-duel-ycs/rdycs-round-{i}-pairings",
               f"2022-01-2{i}") for i in (1, 2, 3)])))
        got = {r["slug"]: (r["event"], r["event_confidence"]) for r in rows}
        self.assertEqual(got["rdycs-round-1-pairings"],
                         ("2021-december-remote-duel-ycs", "path"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
