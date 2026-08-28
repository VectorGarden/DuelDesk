#!/usr/bin/env python3
"""Tests for the blog scraper, against saved fixtures -- no network.

The fixtures are real pages, trimmed to their <title> and <table>. Real ones
matter here: every defect these tests guard against was found in actual markup,
not imagined.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse import (parse_post, normalise_name, strip_region,  # noqa: E402
                   detect_kind, detect_round, detect_format)
from index import parse_post_sitemap, assign_events, event_windows  # noqa: E402

FIX = Path(__file__).parent.parent / "test" / "fixtures" / "blog"
load = lambda n: parse_post((FIX / f"{n}.html").read_text(), n)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)


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

    def test_the_slug_wins_when_the_posts_do_not_agree(self):
        from naming import event_name
        # One oddly-titled post must not get to name the whole event.
        self.assertEqual(event_name(["A: one", "B: two", "C: three", "D: four"],
                                    "2026 08 Quebec"), "2026 08 Quebec")

    def test_titles_without_a_separator_fall_back(self):
        from naming import event_name
        self.assertEqual(event_name(["No separator here"], "fallback"), "fallback")
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
        self.assertEqual(root.findtext("channel/item/title"),
                         'Round 1 <b>"pairings"</b> & more')

    def test_an_event_with_no_usable_posts_still_parses(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(self.feed([]))
        self.assertEqual(len(root.findall("channel/item")), 0)


class TestProvenanceCheck(unittest.TestCase):
    """check-rounds.py is what stops a file that misdescribes itself reaching
    the site. It runs in CI against real data, but its own rules had no test,
    and this is the rule that decides whether invented records get served as
    coverage."""

    CHECKER = Path(__file__).resolve().parent.parent / ".github/scripts/check-rounds.py"

    def check(self, mutate):
        import json, subprocess, tempfile
        good = json.loads((Path(__file__).resolve().parent.parent / "rounds.json").read_text())
        mutate(good)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(good, fh)
            path = fh.name
        done = subprocess.run(["python3", str(self.CHECKER), path],
                              capture_output=True, text=True)
        return done.returncode, done.stdout

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

    def test_the_newest_round_is_the_live_one(self):
        live = [r for r in self.adv["rounds"] if r["state"] == "live"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["order"], max(r["order"] for r in self.adv["rounds"]))

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
