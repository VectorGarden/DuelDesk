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
