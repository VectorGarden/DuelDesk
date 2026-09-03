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
from functools import lru_cache
from datetime import date

from naming import wcq_name
from parse import coverage_format, detect_format, detect_kind, detect_round
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

# How many events may share a word before it stops identifying any of them.
FEW = 3


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


# A date as a day number, worked out once per date rather than once per
# question. assign_events asks whether a post's date falls inside an event's
# window, and asks it for every post against every window: 1,365,509 calls
# over one run of the archive, each parsing three ISO strings, for 3,369,664
# parses of 776 distinct dates.
@lru_cache(maxsize=None)
def _day(iso: str) -> int:
    return date.fromisoformat(iso).toordinal()


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


def settled_end(ended: str, days: dict[str, int], today: str | None = None,
                gap_days: int = 2, stray_posts: int = 2) -> str:
    """The day an event's coverage really ended, ignoring a later edit.

    lastmod is a modification date, so a post edited weeks afterwards dates the
    event to the day it was edited. tight_window already refuses the extreme
    version of this -- an edit years later -- by splitting on a month's gap.
    What it cannot see is the stray inside that month: YCS Seattle published
    thirty-seven posts on 18 and 19 February 2017 and one more on 2 March, and
    the site dated the tournament to March.

    So the end date walks backwards off a stray and stops at the first real
    day of coverage. A stray is both rare and remote -- no more than a couple
    of posts, and separated from the rest by more than a weekend -- because
    either alone is ordinary. A quiet last day is what a Sunday looks like when
    only the winner is left to announce, and a gap is what a Remote Duel event
    looks like when it runs over two weekends.

    Nineteen of the archive's events move; the other hundred and fifty-four do
    not, and none moves by less than three days. An event still being covered
    is left alone: its quiet newest day is the coverage catching up, not a
    stray, and there is no telling the two apart until it stops.
    """
    # Still being written about, so today's silence means nothing yet.
    if today is not None and (date.fromisoformat(today).toordinal()
                              - date.fromisoformat(ended).toordinal()) <= gap_days:
        return ended
    while earlier := [d for d in days if d < ended]:
        if days.get(ended, 0) > stray_posts:
            break
        previous = max(earlier)
        if (date.fromisoformat(ended).toordinal()
                - date.fromisoformat(previous).toordinal()) <= gap_days:
            break
        ended = previous
    return ended


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


def qualifier_named(entry: Entry, windows: dict) -> str | None:
    """The qualifier a post's slug names, when exactly one event answers to it.

    The dates cannot always place these. "sawcq2025-winner" is the 2025 South
    American qualifier's winner post and carries 8 July, weeks after that
    tournament and inside two others -- so it was ambiguous between the Central
    and North American ones, neither of which it is about.

    What it does say, plainly, is which qualifier. wcq_name reads that: the
    blog's own initials for the three regions, with the year running straight
    on to them. Asked only once the dates have failed, and only where exactly
    one event answers to the name, so this narrows an ambiguity rather than
    overruling an answer.
    """
    if not (want := wcq_name(entry.slug, "", entry.lastmod)):
        return None
    answering = [slug for slug, (lo, hi) in windows.items()
                 if wcq_name(slug, "", hi) == want]
    return answering[0] if len(answering) == 1 else None


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


# How the blog opens a weekend it is about to cover. The oldest coverage names
# its tournament nowhere else -- not in the path, not in the slug of a single
# table, not even in their titles, which read "Standings: Round 2" -- so this
# post is the only thing that says which tournament the weekend was.
_OPENS = re.compile(r"^welcome-to-|^welcome-|^introduction-to-"
                    r"|-is-underway$|-is-about-to-begin$|-has-begun$|-kicks-off$")

# What that leaves once the announcement is taken off: the event's own name.
_OPENING_TRIM = re.compile(r"^(?:welcome-to-the-|welcome-to-|welcome-|introduction-to-)"
                           r"|(?:-is-underway|-is-about-to-begin|-has-begun|-kicks-off)$")

# Coverage, as opposed to the product news and reader questions the blog runs
# through the same weekend. A window of dates is not evidence that a post is
# about the tournament -- that mistake swept a week of card announcements into
# YCS Montreal -- so only the kinds that carry a tournament's own record come.
_COVERAGE = ("pairings", "standings", "feature", "result", "deck")


def opened_events(records: list[dict], windows: dict, within,
                  gap_days: int = 3, minimum: int = 9) -> dict[str, str]:
    """Post URL -> event, for tournaments the blog covered but never named.

    discover_events reads the event's name off the front of a slug. The oldest
    coverage has none to read: 2011 to 2016 published its tables at the blog
    root as "standings-after-round-3" and "top-32-pairings", so three hundred
    of them belong to tournaments this archive does not have at all.

    What names them is the post that opens the weekend -- "welcome-to-ycs-
    dallas", "ycs-kansas-city-is-underway" -- and that is what this reads.

    Four things have to hold, because attaching tables by date is what cost
    YCS Philadelphia and YCS Guadalajara their brackets:

      * The weekend has to hold a bracket's worth of tables. A stray pairings
        post is not a tournament.
      * Nothing in the weekend already belongs to an event. Asked of the
        posts rather than of the known windows, because by this point events
        have been discovered that no window describes: 2016 YCS Minneapolis
        was found by discover_events, and a rule reading windows alone
        re-claimed its weekend and relabelled thirty-one of its posts.
      * Exactly one post opens the weekend. Three tournaments ran on
        2015-02-14 -- Tacoma, Charlotte and Charleston -- and a rule that
        picked one of them would be guessing.
      * Only coverage is adopted, never the news and reader questions that run
        the same weekend.
    """
    unplaced = [r for r in records if not r["event"] and r["lastmod"]]
    tables = sorted((r for r in unplaced if detect_kind(r["slug"]) in TOURNAMENT),
                    key=lambda r: r["lastmod"])
    if not tables:
        return {}

    runs, current = [], [tables[0]]
    for rec in tables[1:]:
        if _day(rec["lastmod"]) - _day(current[-1]["lastmod"]) > gap_days:
            runs.append(current)
            current = []
        current.append(rec)
    runs.append(current)

    out: dict[str, str] = {}
    for run in runs:
        if len(run) < minimum:
            continue
        lo, hi = run[0]["lastmod"], run[-1]["lastmod"]
        if any(r["event"] and r["lastmod"] and lo <= r["lastmod"] <= hi
               for r in records):
            continue
        here = [r for r in unplaced if lo <= r["lastmod"] <= hi]
        opening = [r for r in here if _OPENS.search(r["slug"])]
        if len(opening) != 1:
            continue
        bare = _OPENING_TRIM.sub("", opening[0]["slug"]).strip("-")
        if len(bare) < 4:
            continue
        slug = f"{lo[:4]}-{bare}"
        for rec in here:
            if rec is opening[0] or detect_kind(rec["slug"]) in _COVERAGE:
                out[rec["url"]] = slug
    return out


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


def assign_events(entries: list[Entry], slack_days: int = 4,
                  read=None) -> list[dict]:
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
        return (_day(lo) - slack_days <= _day(d) <= _day(hi) + slack_days)

    filed: dict[str, set] = defaultdict(set)
    for e in entries:
        if not (e.event_slug and e.lastmod):
            continue
        kind = detect_kind(e.slug)
        if kind in TOURNAMENT:
            filed[e.event_slug].add((kind, detect_round(f"{e.slug} {e.url}", kind),
                                     detect_format(f"{e.slug} {e.url}")))

    out = []
    for e in entries:
        rec = e.to_dict()
        misfiled = (e.event_slug and e.lastmod and e.event_slug in windows
                    and not within(e.lastmod, *windows[e.event_slug]))
        if e.event_slug and not misfiled:
            rec["event"], rec["event_confidence"] = e.event_slug, "path"
        elif misfiled and not same_series(e, windows, within):
            # The date disagrees with the path and no other running of the
            # series explains it, which means the date is what is wrong. A
            # lastmod is when the blog last edited a post, and an edit weeks
            # later moves it to whatever event was on that week: YCS Houston's
            # winner post was touched on 30 May and went to YCS Providence,
            # and eight of the 2013 North America WCQ's standings went to YCS
            # Chicago, six years away.
            #
            # The path is typed by hand and names the event outright. Where
            # nothing can explain it away, it is believed.
            #
            # Not always rightly, and two of the thirty show it. They sit
            # under /11-02-dallas/ and are called
            # "ycs-atlanta-decks-by-the-numbers" and "-card-tech-by-the-
            # numbers", so the path is simply wrong.
            #
            # The date cannot save them either. They are dated 2011-03-19 and
            # the Atlanta tournaments either side are 10-11-atlanta, which ran
            # 20-29 November 2010, and 12-02-atlanta in February 2012. No
            # window holds them, so no rule here has a true answer to give:
            # today the date puts them in YCS Charlotte, which is 20 March and
            # also not Atlanta.
            #
            # They move from one wrong event to another. Worth knowing, and not
            # worth contorting this rule for -- a guard reading the post's own
            # slug would have to know which events exist, and discovery has not
            # run yet when this decides.
            rec["event"], rec["event_confidence"] = e.event_slug, "path+late"
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
            kind = detect_kind(e.slug)
            if len(hits) == 1 and kind in TOURNAMENT and (
                    kind, detect_round(f"{e.slug} {e.url}", kind),
                    detect_format(f"{e.slug} {e.url}")) in filed.get(hits[0], ()):
                hits = []
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

    # And the tournaments nobody named at all, which only the post opening
    # their weekend identifies. After discovery, because it works on what
    # discovery could not reach, and it mints events rather than moving posts:
    # a weekend any existing event covers is left alone.
    # Worked out once over the whole set, then applied. Recomputing it per
    # record would let each assignment shrink the very cluster the next one is
    # measured against, until the weekend falls under the minimum and the rest
    # of its tables are left behind.
    opened = opened_events(out, windows, within)
    for rec in out:
        if not rec["event"] and (slug := opened.get(rec["url"])):
            rec["event"], rec["event_confidence"] = slug, "opened"

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
    # Who each word of a slug belongs to. "philadelphia" is in one event's
    # vocabulary out of two hundred and six, which is what makes it evidence;
    # "round" is in a hundred and forty-three, which is what makes it none.
    disc = _discovered_profiles(out)
    owners: dict[str, set[str]] = defaultdict(set)
    for slug, prof in list(profiles.items()) + list(disc.items()):
        for term in prof.terms:
            owners[term].add(slug)

    for rec, ev in _by_date(out, disc, within, owners):
        rec["event"], rec["event_confidence"] = ev, "discovered+date"

    # Last of all, and the only rule here that overrules another: a post whose
    # slug opens with an event's own name, in that event's own year, belongs to
    # that event whatever a date said about it.
    #
    # A date is what the blog last edited a post, not when the event was, and
    # an edit months later moves the post to whichever event was running that
    # week. YCS Chicago's winner post is dated four months after the event and
    # went to YCS Knoxville; YCS Mexico City's went to YCS Providence. Neither
    # crowned the wrong Duelist, but only because the names in them happened
    # not to be in the receiving event's cut.
    for rec, ev in _named_outright(out, {**profiles, **disc}):
        rec["event"], rec["event_confidence"] = ev, "name"

    # And the qualifiers, which the blog names by their initials. Last, with
    # the discovered events in hand: the 2025 South American qualifier is not
    # a path event, so nothing earlier than this knows it exists.
    everything = {**profiles, **disc}
    for rec in out:
        if rec["event"]:
            continue
        # Nothing that carries a round, for the reason the rule above it says:
        # a name tells you which event a post is about and nothing about
        # whether its table belongs in that event's bracket. The 2019 North
        # America WCQ's World Qualifying Points Playoff is named for the
        # qualifier it runs beside -- "north-america-wcq-world-qualifying-
        # points-playoff-round-1" -- and its tables put five Duelists in a Top
        # 8 who had not played in the Top 16, which took the event out of the
        # archive.
        if detect_kind(rec["slug"]) in (*TOURNAMENT, "feature"):
            continue
        entry = Entry(rec["url"], rec["year"], rec["category"], rec["event_slug"],
                      rec["slug"], rec["lastmod"])
        if claimed := qualifier_named(entry, {k: p.window for k, p in everything.items()}):
            rec["event"], rec["event_confidence"] = claimed, "initials"

    # And, for the handful left, what the post says in its first line.
    #
    # Everything above reads a slug. Some winner announcements have no name in
    # theirs to read -- the Central America WCQ 2026's is "we-have-a-winner-13"
    # -- and three championships ran that weekend, so the date cannot choose
    # between them either. The event is named in the post, in a sentence:
    # "Esteban Jesus Mena Campos is our new Central America WCQ Champion."
    #
    # Reading costs a fetch, so this asks for one only where the answer is
    # worth having and nothing cheaper will do: the post is still unassigned,
    # its slug announces a winner, and some event's window holds its date.
    # Ten posts on the whole blog meet that, and the caller decides whether to
    # pay for them -- with no reader this pass does nothing at all.
    if read is not None:
        for rec, ev in _announced_in(out, everything, within, read):
            rec["event"], rec["event_confidence"] = ev, "announced"
    return out


# Slugs that say a winner is about to be named and nothing else. Deliberately
# short: this decides which posts are worth a fetch, and the fetch is the cost.
ANNOUNCEMENT = re.compile(r"we-have-a-winner|and-the-winner|winner-is|champion-is")


def _announced_in(records: list[dict], profiles: dict[str, Profile], within, read):
    """Winner posts that name their event in the text, and that event.

    The event's own name, whole and contiguous, the way _named_outright wants
    it in a slug -- a word of it is not enough. Where two events fit, the
    longer name wins: a post reading "YCS Lima Dragon Duel Champion" names
    both, and means the Dragon Duel.
    """
    for rec in records:
        if rec["event"] or not rec["lastmod"] or not ANNOUNCEMENT.search(rec["slug"]):
            continue
        # Same guard as the rule above, for the same reason: a name says which
        # event a post is about, never that the table in it belongs in that
        # event's bracket.
        if detect_kind(rec["slug"]) in (*TOURNAMENT, "feature"):
            continue
        near = {s: bare for s, p in profiles.items()
                if within(rec["lastmod"], *p.window)
                and len(bare := _DATE_PREFIX.sub("", s).replace("-", " ")) > 6}
        if not near:
            continue
        try:
            text = (read(rec["url"]) or "").lower()
        except Exception:
            continue
        hits = [s for s, bare in near.items() if bare in text]
        # The longest name, where one contains another. Anything else that
        # matched two events is left alone, as everywhere else here.
        hits = [s for s in hits
                if not any(o != s and near[s] in near[o] for o in hits)]
        if len(hits) == 1:
            yield rec, hits[0]


# An event's slug with any leading date taken off -- "2019-ycs-chicago" is
# written "ycs-chicago" by the posts that name it.
_DATE_PREFIX = re.compile(r"^(?:(?:19|20)?\d{2})(?:-?\d{2})?-")


def _named_outright(records: list[dict], profiles: dict[str, Profile]):
    """Posts whose slug opens with one event's name, and that event.

    The whole name, contiguous, at the front, and in the event's own year --
    not a word of it somewhere in the middle. A rule reading single words
    matched "round-4-feature-match-austin-ruggeri-versus..." to the Austin
    event on the Duelist's forename, and moved fourteen hundred posts.
    """
    year_of = {s: p.window[0][:4] for s, p in profiles.items()}
    names: dict[str, set[str]] = defaultdict(set)
    for slug in profiles:
        # Long enough to be a name. "12-04" is a date, not an event.
        if len(bare := _DATE_PREFIX.sub("", slug)) > 6:
            names[bare].add(slug)

    for rec in records:
        year = str(rec.get("year") or "")
        opens = [(bare, slug) for bare, owners in names.items()
                 if rec["slug"].startswith(bare + "-")
                 for slug in owners if year_of.get(slug) == year]
        if len(opens) != 1 or rec["event"] == opens[0][1]:
            continue
        bare, slug = opens[0]
        # What the post says about itself after its event's name. A side event
        # the builder keeps as its own tournament is welcome -- the Dragon
        # Duel's champion belongs to the Dragon Duel. One it does not separate
        # would land in the main event's bracket, and
        # "ycs-houston-speed-duel-main-event-series-top-8" is a Top 8 that
        # event never played.
        #
        # Read past the name, not across it: SIDE_EVENT matches "invitational",
        # which is half of what a UDS Invitational is called, and reading the
        # whole slug threw away that event's own rounds.
        rest = rec["slug"][len(bare) + 1:].replace("-", " ")
        if SIDE_EVENT.search(rest) and coverage_format(rest, None) is None:
            continue
        # And only what cannot change the shape of a bracket. A name says
        # which event a post belongs to; it says nothing about whether the
        # table in it is any good, and this rule cannot look. The blog
        # reprints tables under a second slug and the copy is often the worse
        # of the two -- YCS Philadelphia's Top 64 was printed twice and the
        # copy holds 63 Duelists, so handing the event its own name back cost
        # it the event. Guadalajara lost two rounds the same way.
        #
        # A result or a deck list has no round to be wrong about, and the
        # winner posts this rule exists for are results.
        if detect_kind(rec["slug"]) in (*TOURNAMENT, "feature"):
            continue
        yield rec, slug


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


def _by_date(records: list[dict], profiles: dict[str, Profile], within,
             owners: dict[str, set[str]] | None = None):
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
            # And a round that names another event is that event's. Every YCS
            # post is filed under "ycs", and a category is enough for the prose
            # this rule is mostly for and nowhere near enough for a table:
            # "ycs-philadelphia-top-64-pairings-and-deck-types" was vouched for
            # by its category and became YCS Cancun's Top 64, an event that
            # never played one -- sixty-three Duelists in a round of
            # sixty-four, because the blog had printed one of Philadelphia's
            # twice.
            #
            # A word is evidence in proportion to how few events use it.
            # "philadelphia" belongs to one vocabulary of two hundred and six;
            # "round" belongs to a hundred and forty-three and says nothing.
            # Only the rare ones are read, which is why YCS Minneapolis keeps
            # standings called nothing but "standings-after-round-4-4".
            named = [who for term in slug_terms(rec["slug"])
                     if 0 < len(who := (owners or {}).get(term, set())) <= FEW]
            if any(hits[0] not in who for who in named):
                continue
        yield rec, hits[0]
