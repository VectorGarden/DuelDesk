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
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date

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
                if len(narrowed) == 1:
                    rec["event"], rec["event_confidence"] = narrowed[0], "date+format"
                else:
                    rec["event"], rec["event_confidence"] = None, f"ambiguous:{len(hits)}"
            else:
                rec["event"], rec["event_confidence"] = None, "unmatched"
        out.append(rec)
    return out
