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
        self.assertEqual(high, "2026-08-25")

        save_state(state, {"high_water": high})
        changed, _ = check_for_updates(f, state)
        self.assertFalse(changed, "unchanged sitemap must close the gate")

        save_state(state, {"high_water": "2020-01-01"})
        changed, _ = check_for_updates(f, state)
        self.assertTrue(changed, "a moved high-water mark must reopen it")


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
