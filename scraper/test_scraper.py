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

    def test_a_feature_match_reaches_its_round(self):
        r2 = next(r for r in self.fmt["rounds"] if r["label"] == "R2")
        self.assertIsNotNone(r2["feature"], "no feature match on the round")
        self.assertEqual(r2["feature"]["source"], "https://x/f-new/",
                         "the newest of the two, not whichever arrived last")

    def test_a_feature_match_states_only_what_the_post_says(self):
        r2 = next(r for r in self.fmt["rounds"] if r["label"] == "R2")
        f = r2["feature"]
        self.assertEqual((f["a"]["name"], f["b"]["name"]), ("Bo", "Di"))
        # A feature post has no table. Printing a final Swiss record beside a
        # round-two match would be a plausible-looking lie.
        self.assertIsNone(f["a"]["deck"])
        self.assertIsNone(f["a"]["record"])

    def test_a_round_with_no_feature_says_so(self):
        r1 = next(r for r in self.fmt["rounds"] if r["label"] == "R1")
        self.assertIsNone(r1["feature"])


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

    def check(self, mutate):
        """Run the checker over the newest published event, mutated.

        Found through the manifest rather than by path, exactly as the page
        finds it, so this cannot end up checking a file nothing serves.
        """
        import json, subprocess, tempfile
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "events.json").read_text())
        good = json.loads((root / manifest["events"][0]["path"]).read_text())
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

    def test_a_record_short_of_the_rounds_that_were_published_is_rejected(self):
        # The rule keeps its whole force where the coverage is complete.
        def one_short(d):
            cut = [r for r in d["formats"][0]["rounds"] if r["phase"] == "Top cut"]
            rec = cut[1]["pairings"][0]["aRec"]
            rec["wins"] -= 1
        code, out = self.check(one_short)
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
        import subprocess
        done = subprocess.run(["python3", str(self.CHECKER), str(path)],
                              capture_output=True, text=True)
        return done.returncode, done.stdout

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
        done = subprocess.run(["python3", str(self.CHECKER), path],
                              capture_output=True, text=True)
        return done.returncode, done.stdout

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

    def test_a_readable_feature_beats_a_newer_unreadable_one(self):
        from build import better_feature
        readable = self.feature("Top 64 Feature Match: Ryan Yu vs. Dominic Couch", "10:00")
        unreadable = self.feature("Top 64 Feature Match involving several people", "18:00")
        self.assertTrue(better_feature(readable, unreadable))
        self.assertFalse(better_feature(unreadable, readable))

    def test_between_two_readable_ones_the_newest_wins(self):
        from build import better_feature
        older = self.feature("Round 4 Feature Match: A One vs. B Two", "10:00")
        newer = self.feature("Round 4 Feature Match: C Three vs. D Four", "18:00")
        self.assertTrue(better_feature(newer, older))
        self.assertFalse(better_feature(older, newer))

    def test_a_round_shows_the_feature_it_can_read(self):
        import io
        from contextlib import redirect_stdout
        from build import build_event
        sources = [
            _src("https://x/p/", "Round 4 Pairings (Advanced Format)", PAIR_HEAD,
                 [["1", "Ann", "Alpha", "vs.", "Bo", "Beta"]]),
            self.feature("Advanced Format Round 4 Feature Match: Ryan Yu vs. Dominic Couch", "10:00"),
            self.feature("Advanced Format Round 4 Feature Match: Hani Jawhari and friends", "18:00"),
        ]
        with redirect_stdout(io.StringIO()):
            ev = build_event("YCS Philadelphia", sources)
        feature = ev["formats"][0]["rounds"][0]["feature"]
        self.assertIsNotNone(feature, "the round was left holding a feature naming nobody")
        self.assertEqual(feature["a"]["name"], "Ryan Yu")


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

        def plan(entries, done, backfill):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
