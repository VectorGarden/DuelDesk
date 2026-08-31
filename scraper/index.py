#!/usr/bin/env python3
"""Build a post index from the blog's sitemap, and group posts into events.

The sitemap is the sanctioned entry point: robots.txt disallows only /wp-admin/
and publishes wp-sitemap.xml explicitly. There is no RSS feed (every /feed/ path
404s) and the WordPress REST posts endpoint returns 403, so this is the only
supported way in.

Event identity is the hard part. A post URL is either

    /{year}/{category}/{slug}/                 no event
    /{year}/{category}/{event}/{slug}/         event in the path

and the *same* event appears in both shapes -- YCS Montreal has posts under
2026-08-quebec and others directly under ycs. So the event slugs are treated as
authoritative date windows, and undated siblings are attached by date.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import date

from naming import wcq_name
from parse import detect_kind, detect_round
from winners import SIDE_EVENT

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BASE = "https://yugiohblog.konami.com/"

# Path segments that are topics, not events. dragon-duel reads like an event
# slug and is not one: its posts land in 2013, 2015 and 2018, three separate
# clusters of a dozen or more, which is a recurring side bracket covered at many
# events rather than one tournament.
TOPIC_SEGMENTS = {"ycs", "championships", "dragon-duel", "event-information",
                  "genesys", "news-updates", "product-guide", "sjc", "uds",
                  "wcq"}

# A gap this long inside one event's dates means a second occasion, not a slow
# weekend. See tight_window: measured across all 98 event slugs, 30 days is the
# point where stray re-edits separate cleanly and real coverage stays whole.
GAP_DAYS = 30

# How many of an event's own posts a word must appear in to count as naming it.
MIN_TERM_SHARE = 0.5

# The two kinds of post a round track is built from. An event that published
# neither is an announcement, not coverage.
TOURNAMENT = ("pairings", "standings")


@dataclass
class Entry:
    url: str
    year: str
    category: str
    event_slug: str | None
    slug: str
    lastmod: str | None          # the date, for grouping posts into events
    modified: str | None = None  # the same stamp as published, time and offset intact

    def to_dict(self) -> dict:
        return asdict(self)


def parse_sitemap_index(xml: str) -> list[str]:
    return [e.text for e in ET.fromstring(xml).findall(".//s:loc", NS) if e.text]


def parse_post_sitemap(xml: str) -> list[Entry]:
    out: list[Entry] = []
    for u in ET.fromstring(xml).findall(".//s:url", NS):
        loc = u.findtext("s:loc", namespaces=NS) or ""
        # Kept twice on purpose. Events are grouped by whole days, so lastmod is
        # a date and the comparisons downstream stay simple; the feed and the
        # per-round posting time need the clock, so the published stamp is kept
        # beside it rather than reconstructed later from a date.
        published = (u.findtext("s:lastmod", namespaces=NS) or "").strip() or None
        lastmod = published[:10] if published else None
        parts = [p for p in loc.replace(BASE, "").rstrip("/").split("/") if p]
        if len(parts) < 3:
            continue
        year, category, slug = parts[0], parts[1], parts[-1]
        event = parts[2] if len(parts) >= 4 and parts[2] not in TOPIC_SEGMENTS else None
        out.append(Entry(loc, year, category, event, slug, lastmod, published))
    return out


def tight_window(dates: list[str], gap_days: int = GAP_DAYS) -> tuple[str, str]:
    """The range holding the bulk of these dates, ignoring strays.

    min()..max() is wrong here, because lastmod is a *modification* date: edit
    one 2014 post today and that event's window stretches across eleven years
    and swallows every undated post in between. It is not a rare accident -- 11
    of 98 event slugs have a window spanning more than two months, and in nearly
    every case it is exactly one re-edited post doing it.

    So the dates are split wherever they leave a gap of a month, and the biggest
    piece wins. On a tie the earlier piece wins: an event happens once and the
    strays are edits made afterwards, so later is the suspicious direction.
    """
    ordinals = sorted(date.fromisoformat(d).toordinal() for d in dates)
    pieces, current = [], [ordinals[0]]
    for o in ordinals[1:]:
        if o - current[-1] > gap_days:
            pieces.append(current)
            current = []
        current.append(o)
    pieces.append(current)
    # By post count, not by span: an event publishes many posts on a few days,
    # so counting distinct dates would let a two-day stray outvote a real event
    # that ran on one.
    best = max(pieces, key=lambda p: (len(p), -p[0]))
    return (date.fromordinal(best[0]).isoformat(),
            date.fromordinal(best[-1]).isoformat())


def slug_terms(slug: str) -> set[str]:
    """The words in a slug, minus numbers and noise too short to identify anything."""
    return {t for t in re.split(r"[^a-z]+", slug.lower())
            if len(t) > 2 and not t.isdigit()}


@dataclass
class Profile:
    """What an event's own posts say about it, used to judge undated siblings."""
    window: tuple[str, str]
    categories: set[str]
    terms: set[str]

    def names(self, entry: Entry) -> bool:
        """Whether this post corroborates the event beyond merely sharing a date.

        A date window is a weak signal, and on its own it swept product news
        into YCS Montreal's coverage: three Legendary Arc-V deck announcements
        and an item about New York Comic Con, all published that week and none
        of them about the tournament.

        The event's own posts are the evidence. A post filed under a category
        the event actually uses is taken at its word; one from elsewhere has to
        say the event's name -- which is read from the coverage's own slugs
        rather than a list, so it works for an event nobody has named yet.
        """
        return entry.category in self.categories or bool(self.terms & slug_terms(entry.slug))


def event_profiles(entries: list[Entry], gap_days: int = GAP_DAYS) -> dict[str, Profile]:
    """Per event slug, built only from the posts that carry it in their URL."""
    own: dict[str, list[Entry]] = {}
    for e in entries:
        if e.event_slug and e.lastmod:
            own.setdefault(e.event_slug, []).append(e)
    out = {}
    for slug, posts in own.items():
        counts = Counter(t for p in posts for t in slug_terms(p.slug))
        out[slug] = Profile(
            window=tight_window([p.lastmod for p in posts], gap_days),
            categories={p.category for p in posts},
            terms={t for t, n in counts.items() if n >= MIN_TERM_SHARE * len(posts)})
    return out


def event_windows(entries: list[Entry]) -> dict[str, tuple[str, str]]:
    """Date range covered by each explicit event slug."""
    return {k: p.window for k, p in event_profiles(entries).items()}


_SLUG_YEAR = re.compile(r"(?:^|-)(?:19|20)\d{2}(?=-|$)")


def same_series(entry: Entry, windows: dict, within) -> str | None:
    """The event this post's slug names, if its slug has the wrong year on it.

    Two event slugs that differ only in their year are two runnings of one
    series, so a post whose date falls outside the one its URL names, and
    inside a sibling's, belongs to the sibling. Anything else is left to the
    date rules.
    """
    family = _SLUG_YEAR.sub("", entry.event_slug)
    for slug, (lo, hi) in windows.items():
        if (slug != entry.event_slug and _SLUG_YEAR.sub("", slug) == family
                and within(entry.lastmod, lo, hi)):
            return slug
    return None


# Words that say what a post is about rather than which event it covers. A post
# slug is the event's name followed by the post's subject --
# "ycs-atlanta-round-1-pairings", "uds-invitational-lima-peru-standings-after-
# round-3" -- so the first of these words is where the name stops.
#
# Only words that are genuinely about a post. "in" and "the" were in this set
# and cost the archive an event: "250th-ycs-in-bogota-colombia-round-1-pairings"
# and "250th-ycs-in-los-angeles-round-3-pairings" both cut back to "250th-ycs",
# which merged two tournaments held the same weekend into one.
POST_SUBJECT = {"pairings", "pairing", "standings", "round", "rounds", "top",
                "after", "final", "finals", "feature", "match", "matches",
                "deck", "decks", "breakdown", "results", "result", "winner",
                "winners", "welcome", "day", "table", "tables", "update",
                "updates", "cut", "swiss", "bracket", "playoff", "playoffs",
                "quarterfinals", "semifinals", "photo", "gallery"}

# Two runnings of one event are at least this far apart, so a gap this long
# inside one name's dates is the next year's tournament rather than a slow
# weekend. Same reasoning as GAP_DAYS, and the same value.
SERIES_GAP_DAYS = GAP_DAYS

# Below this a group is strays -- a couple of posts that escaped an event the
# path names -- rather than coverage of a tournament nobody filed.
MIN_DISCOVERED_POSTS = 5


def event_prefix(slug: str) -> str:
    """The part of a post's slug that names its event, or "".

    Konami files most coverage with no event in the URL, but the post slug
    still opens with the event's name. Cutting at the first word about the post
    leaves it: "ycs-atlanta-round-1-pairings" is YCS Atlanta's.

    Empty for the older coverage, which is titled and slugged only for what the
    post contains -- "standings-after-round-3" says nothing about which
    tournament, and neither does the page it points at.
    """
    words = []
    for w in slug.split("-"):
        if w in POST_SUBJECT:
            break
        words.append(w)
    return "-".join(words)


def _slug_words(slug: str) -> set[str]:
    return {w for w in slug.split("-") if w and not w.isdigit()}


def _names_the_same(prefix: str, slug: str) -> bool:
    """Whether a post's name is the event's, or part of it.

    A subset test, and the empty set is a subset of everything -- so a slug
    with no word in it at all matched every event whose dates covered it.
    Thirty posts are numbers and nothing else, the ids WordPress falls back to
    when a post is published untitled, and each of them attached to whichever
    event was asked about first.
    """
    words = _slug_words(prefix)
    return bool(words) and words <= _slug_words(slug)


def _overlaps(a: tuple[str, str], b: tuple[str, str], slack_days: int = 0) -> bool:
    """Whether two date ranges meet, the second widened by a few days.

    The same slack the date rules allow, and for the same reason: write-ups
    land after the event ends, so a group and the event it belongs to often sit
    next to each other rather than on top of each other. The 2026 North America
    WCQ's own posts are dated the 11th and the rounds that escaped it the 12th,
    which strict overlap called two different tournaments.
    """
    lo = date.fromisoformat(b[0]).toordinal() - slack_days
    hi = date.fromisoformat(b[1]).toordinal() + slack_days
    return not (date.fromisoformat(a[1]).toordinal() < lo
                or hi < date.fromisoformat(a[0]).toordinal())


def _split_runnings(rows: list, gap_days: int) -> list[list]:
    """One name's posts, cut into the separate tournaments that used it."""
    rows = sorted(rows, key=lambda r: r["lastmod"])
    out, current = [], [rows[0]]
    for r in rows[1:]:
        if (date.fromisoformat(r["lastmod"]).toordinal()
                - date.fromisoformat(current[-1]["lastmod"]).toordinal()) > gap_days:
            out.append(current)
            current = []
        current.append(r)
    out.append(current)
    return out


def _minted_slug(prefix: str, lo: str, taken: set[str]) -> str:
    """A stable id for an event the blog never gave one.

    The name the posts use, with the year in front where they left it out, in
    the same shape as the slugs Konami does write: "2017-ycs-atlanta". The
    month is added only if that is already somebody else's.
    """
    year, month = lo[:4], lo[5:7]
    base = prefix if _SLUG_YEAR.search(f"-{prefix}") else f"{year}-{prefix}"
    if base not in taken:
        return base
    return f"{year}-{month}-{prefix}"


def discover_events(records: list[dict], windows: dict, is_tournament,
                    gap_days: int = SERIES_GAP_DAYS,
                    minimum: int = MIN_DISCOVERED_POSTS,
                    slack_days: int = 4) -> dict[str, str]:
    """Post URL -> event, for coverage the blog filed under no event at all.

    Two thirds of this blog's tournament coverage carries no event in its URL.
    The 2023 North America WCQ has thirty-odd posts under /2023/championships/
    and not one of them says which tournament in the path, so nothing above
    this could see the event -- 2,560 rounds of pairings and standings, and
    something over a hundred tournaments, were simply not there.

    What the path leaves out the slug says: posts open with the event's name.
    Grouping on that name and cutting each group where its dates say one
    tournament ended and the next began is enough to find them, and the two
    signals check each other -- a name recurring every year is split by the
    dates, and two tournaments held the same weekend are kept apart by the
    name.

    A group whose name is already an event's, over dates that event covers, is
    that event: those posts escaped it rather than being a tournament of their
    own, and 2026 North America WCQ gets back twenty-two rounds this way.
    """
    groups: dict[str, list[dict]] = {}
    for rec in records:
        if rec["event"] or not rec["lastmod"] or not is_tournament(rec):
            continue
        if prefix := event_prefix(rec["slug"]):
            groups.setdefault(prefix, []).append(rec)

    found = []
    for prefix, rows in sorted(groups.items()):
        for running in _split_runnings(rows, gap_days):
            found.append((prefix, running,
                          (running[0]["lastmod"], running[-1]["lastmod"]), {prefix}))
    found = _merge_same_qualifier(found, slack_days)

    out: dict[str, str] = {}
    minted: set[str] = set()
    # Every name an event answers to, and the dates it ran, for the second pass
    # below. A merged qualifier answers to two.
    known: dict[str, tuple[set[str], tuple[str, str]]] = {}
    for prefix, running, span, names in found:
        host = [slug for slug, w in windows.items()
                if _names_the_same(prefix, slug)
                and _overlaps(span, w, slack_days)]
        if len(host) == 1:
            event = host[0]
        elif host or len(running) < minimum:
            # Two events could host it, or it is too small to be one: the
            # posts stay unassigned rather than being guessed at.
            continue
        else:
            event = _minted_slug(prefix, span[0], set(windows) | minted)
            minted.add(event)
        for r in running:
            out[r["url"]] = event
        seen, dates = known.get(event, (set(), span))
        known[event] = (seen | names,
                        (min(span[0], dates[0]), max(span[1], dates[1])))

    # The rest of each event's coverage: its feature matches, its deck
    # breakdowns, the post welcoming everyone to it. Found the same way and
    # held to the same two signals, so a post joins on its own name and its own
    # date rather than on being adjacent to something that did.
    for rec in records:
        if rec["event"] or rec["url"] in out or not rec["lastmod"]:
            continue
        if not (prefix := event_prefix(rec["slug"])):
            continue
        for event, (names, dates) in known.items():
            if ((prefix in names or _names_the_same(prefix, event))
                    and _overlaps((rec["lastmod"], rec["lastmod"]), dates, slack_days)):
                out[rec["url"]] = event
                break
    return out


def _merge_same_qualifier(found: list, slack_days: int) -> list:
    """One qualifier written two ways is one tournament.

    The 2024 North America WCQ published its Swiss rounds as
    "north-america-wcq-round-10-pairings" and its top cut as
    "nawcq-top-16-pairings-and-deck-types", which are two names and would
    otherwise be two events three days apart in the reader's list.

    Only qualifiers, and only where the naming module reads both names as the
    same one -- "North America WCQ 2024" -- over dates that meet. That is a
    narrower thing than merging on a shared date, which would take the Genesys
    Championship running alongside as well.

    The fuller name wins, because the group that carries it is the bigger one:
    the abbreviation turns up on the cut, and the cut is the short half. Both
    are kept, so the event's feature matches and deck breakdowns can be found
    under whichever of the two they were slugged with.
    """
    keyed: dict[str, list] = {}
    rest = []
    for item in found:
        prefix, _, span, _names = item
        if name := wcq_name(prefix, "", span[1]):
            keyed.setdefault(name, []).append(item)
        else:
            rest.append(item)

    for items in keyed.values():
        items.sort(key=lambda i: i[2][0])
        merged = [items[0]]
        for prefix, rows, span, names in items[1:]:
            was_prefix, was_rows, was_span, was_names = merged[-1]
            if _overlaps(span, was_span, slack_days):
                merged[-1] = (was_prefix if len(was_rows) >= len(rows) else prefix,
                              was_rows + rows,
                              (min(span[0], was_span[0]), max(span[1], was_span[1])),
                              was_names | names)
            else:
                merged.append((prefix, rows, span, names))
        rest += merged
    return rest


def assign_events(entries: list[Entry], slack_days: int = 4) -> list[dict]:
    """Attach every post to an event.

    Posts carrying an event slug define the windows. Posts without one are
    attached to a window their date falls inside, widened by a few days because
    write-ups land after the event ends.

    Concurrent events are real -- 2026-north-america-wcq and
    2026-north-america-genesys-championship share a date -- so a date alone is
    never enough to disambiguate. When several windows match, the format in the
    slug is used to choose, and anything still ambiguous is reported rather than
    guessed.

    A window match also has to be corroborated: falling inside the dates makes a
    post a candidate, and Profile.names decides whether it is really about the
    event. Without that, a week of unrelated product news became coverage.
    """
    profiles = event_profiles(entries)
    windows = {k: p.window for k, p in profiles.items()}

    def within(d: str, lo: str, hi: str) -> bool:
        return (date.fromisoformat(lo).toordinal() - slack_days
                <= date.fromisoformat(d).toordinal()
                <= date.fromisoformat(hi).toordinal() + slack_days)

    out = []
    for e in entries:
        rec = e.to_dict()
        misfiled = (e.event_slug and e.lastmod and e.event_slug in windows
                    and not within(e.lastmod, *windows[e.event_slug]))
        if e.event_slug and not misfiled:
            rec["event"], rec["event_confidence"] = e.event_slug, "path"
        elif misfiled and (sibling := same_series(e, windows, within)):
            # The URL is the strongest signal there is, and it is typed by hand.
            # Konami filed a July 2026 post -- round 13 of the 2026 North
            # America WCQ -- under the 2025 event's slug:
            #
            #   /2026/championships/2025-north-america-wcq/
            #       nawcq-top-tables-update-round-13/
            #
            # The slug still names the series correctly; only the year is
            # wrong. So the year is the part not believed, and the instalment
            # whose dates actually hold the post is used instead. Nothing else
            # separated the two candidates: both are 2026 championships posts,
            # and neither the category nor the vocabulary told them apart.
            rec["event"], rec["event_confidence"] = sibling, "path+year"
        elif not e.lastmod:
            rec["event"], rec["event_confidence"] = None, "none"
        else:
            hits = [k for k, (lo, hi) in windows.items()
                    if within(e.lastmod, lo, hi) and profiles[k].names(e)]
            if len(hits) == 1:
                rec["event"], rec["event_confidence"] = hits[0], "date"
            elif len(hits) > 1:
                fmt = "genesys" if "genesys" in e.slug else ("advanced" if "advanced" in e.slug else None)
                narrowed = [h for h in hits if fmt and fmt in h] if fmt else []
                # Failing the format, the qualifier the post names. Two events
                # ran on 2026-07-11 -- the North America WCQ and the Genesys
                # Championship -- and the post announcing the WCQ's winner is
                # headed "and-the-winner-of-the-2026-nawcq-is". It names its
                # event as plainly as a post can; what it does not do is name a
                # format, so the rule above had nothing to work with and the
                # event finished with no champion.
                #
                # Read through the naming module, so "nawcq" and
                # "north-america-wcq" are the one qualifier they already are
                # everywhere else. Only qualifiers, and only where exactly one
                # candidate answers to the name: this narrows an ambiguity, it
                # does not resolve one by picking.
                if len(narrowed) != 1 and (want := wcq_name(e.slug, "", e.lastmod)):
                    named = [h for h in hits
                             if wcq_name(h, "", windows[h][1]) == want]
                    if len(named) == 1:
                        narrowed = named
                        rec["event"], rec["event_confidence"] = named[0], "date+name"
                        out.append(rec)
                        continue
                if len(narrowed) == 1:
                    rec["event"], rec["event_confidence"] = narrowed[0], "date+format"
                else:
                    rec["event"], rec["event_confidence"] = None, f"ambiguous:{len(hits)}"
            else:
                rec["event"], rec["event_confidence"] = None, "unmatched"
        out.append(rec)

    # Last, because it works on what is left: everything the path or the dates
    # could identify has been, and these are the tournaments that were not
    # there at all. Nothing above is revisited, so an event the earlier rules
    # settled can only gain posts here, never lose or exchange them.
    found = discover_events(out, windows, lambda r: detect_kind(r["slug"]) in TOURNAMENT,
                            slack_days=slack_days)
    for rec in out:
        if slug := found.get(rec["url"]):
            rec["event"], rec["event_confidence"] = slug, (
                "prefix" if slug in windows else "discovered")

    # A discovered event can now be dated, so the rule the path events have had
    # all along applies to it too.
    #
    # Until this, an event nobody filed under a path could only ever be given a
    # post that carried its name. Everything written about it in a sentence
    # fell through: the post announcing its winner, its feature matches, the
    # table of contents. The 2023 North America Remote Duel YCS has a finals
    # write-up naming its champion in so many words, and the slug is
    # "finals-feature-match-steven-santoli-vs-liam-mac-oscair" -- which begins
    # with a word about the post, so there is no name in it to match, and no
    # window to fall inside either.
    #
    # Same corroboration as everywhere else, because a date on its own swept
    # product news into YCS Montreal's coverage: a post from a category the
    # event uses is taken at its word, and one from elsewhere has to say the
    # event's name. Same ambiguity rule too -- where two of them fit, neither
    # gets it.
    for rec, ev in _by_date(out, _discovered_profiles(out), within):
        rec["event"], rec["event_confidence"] = ev, "discovered+date"
    return out


def _discovered_profiles(records: list[dict]) -> dict[str, Profile]:
    """A profile for each event discovery found, built the same way as the rest.

    event_profiles reads the posts that carry a slug in their path, which these
    events have none of. Theirs are the posts discovery gave them.
    """
    own: dict[str, list[dict]] = {}
    for rec in records:
        if rec["event"] and rec["event_confidence"] in ("discovered", "prefix") and rec["lastmod"]:
            own.setdefault(rec["event"], []).append(rec)
    out = {}
    for slug, posts in own.items():
        counts = Counter(t for p in posts for t in slug_terms(p["slug"]))
        # A category one post out of thirty-four sits in is not a category the
        # event uses, it is a post Konami filed in the wrong section. One such
        # post -- south-america-wcq-...-playoff-round-1, under /2023/ycs/ --
        # put "ycs" on the 2023 South America WCQ and made every YCS post that
        # weekend a candidate for it. Six events have one of these.
        #
        # Unless that leaves nothing: a small event's every category is held by
        # a single post, and no category at all would make it unreachable.
        cats = Counter(p["category"] for p in posts)
        common = {c for c, n in cats.items() if n > 1}
        out[slug] = Profile(
            window=tight_window([p["lastmod"] for p in posts]),
            categories=common or set(cats),
            terms={t for t, n in counts.items() if n >= MIN_TERM_SHARE * len(posts)})
    return out


def _by_date(records: list[dict], profiles: dict[str, Profile], within):
    """Still-unassigned posts, and the one discovered event each belongs to."""
    # The rounds each event already holds from a post that named it, which is
    # what a dated round is not allowed to duplicate.
    covered: dict[str, set] = defaultdict(set)
    for rec in records:
        if not rec["event"]:
            continue
        kind = detect_kind(rec["slug"])
        if kind in TOURNAMENT:
            covered[rec["event"]].add(
                (kind, detect_round(f"{rec['slug']} {rec['url']}", kind)))

    for rec in records:
        if rec["event"] or not rec["lastmod"]:
            continue
        # Every YCS runs a dozen tournaments beside the main one, and a date
        # cannot tell them apart -- they are on at the same time, in the same
        # room, written up by the same people. Attaching one to the event is
        # not a harmless extra post: "dd-wcq-ca-standings-after-round-1" is the
        # Dragon Duel's table, and it would be read as the main event's, while
        # "sunday-speed-duel-...-finals-feature-match" names a Final the main
        # event has not reached and leaves an empty round where it should be.
        #
        # Scoped to this rule, which is the one with nothing to go on but the
        # day a post was published. It happens that a side event's own posts
        # rarely match by name either -- "ycs-origins-dragon-duel-champion"
        # reads as an event called "ycs-origins-dragon-duel", which no window
        # belongs to -- so in practice they are left alone entirely.
        if SIDE_EVENT.search(rec["slug"].replace("-", " ")):
            continue
        entry = Entry(rec["url"], rec["year"], rec["category"], rec["event_slug"],
                      rec["slug"], rec["lastmod"])
        hits = [slug for slug, p in profiles.items()
                if within(rec["lastmod"], *p.window) and p.names(entry)]
        if len(hits) != 1:
            continue
        # A round the event already has, on the strength of a date, is the one
        # thing this rule must not do. YCS Chicago published
        # "ycs-chicago-top-32-pairings-and-deck-breakdown", and something else
        # that weekend published "top-32-pairings-6", which names nobody. Dated
        # in, it was the fuller of the two tables and won -- and then fourteen
        # of the sixteen Duelists in Chicago's own Top 16 had not played in its
        # Top 32, which is how the deploy found it.
        #
        # Refusing every dated round was the first fix and it was too blunt.
        # YCS Minneapolis 2016 is named by none of its own standings --
        # "standings-after-round-4-4", "standings-after-the-swiss-rounds" --
        # and the rule took all six, which left the event with no standings at
        # all and dropped it below the coverage worth building. A generic slug
        # is how the blog wrote a round, not evidence the round is somebody
        # else's.
        #
        # What separates the two is whether the event already holds that round
        # from a post that named it. Where it does, the date adds a second
        # table for a round that has one, and there is nothing to choose
        # between them but size. Where it does not, the date is the only thing
        # standing between the round and nobody having it.
        kind = detect_kind(rec["slug"])
        if kind in TOURNAMENT:
            rnd = detect_round(f"{rec['slug']} {rec['url']}", kind)
            if (kind, rnd) in covered.get(hits[0], ()):
                continue
        yield rec, hits[0]
