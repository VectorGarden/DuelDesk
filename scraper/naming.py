#!/usr/bin/env python3
"""The event's own name and posting times, taken from what it published.

Both were being reconstructed from the URL, which is lossy in the same way:
the slug 2026-08-quebec becomes "2026 08 Quebec", and a date-shaped stamp
becomes a round "posted 2026-08-15". The posts themselves say "YCS Montreal"
and carry the clock, so neither needs inventing.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

# Post titles are written "Event: what this post is" -- "YCS Montreal: Round 3
# Pairings (Genesys Format)". A handful break the pattern, mostly feature
# matches titled by round, so the name is the prevailing prefix rather than the
# first one seen.
_TITLE_SPLIT = re.compile(r"\s*[:–—]\s*")

# Enough of the event's posts must agree before their prefix is treated as its
# name. Set low because the majority is usually overwhelming -- 51 of 60 at YCS
# Montreal -- but not at one, which would let a single oddly-titled post name
# the whole event.
MIN_SHARE = 0.4


def event_name(titles: list[str], fallback: str) -> str:
    """The event's name, or `fallback` if its posts do not agree on one.

    Two things this counts carefully, both learned by getting them wrong.

    Support is titles that *start with* the candidate, not titles whose prefix
    equals it. "YCS Montreal Top Tables Update" is thirteen posts naming the same
    event under a longer heading, and treating them as a rival name split the
    vote.

    The denominator is titles that name anything at all, not every title. A news
    post headed "Doors open at 9am" is not a vote against the event's name, it is
    an abstention. Counting it as one is how raising the fetch budget from 60
    posts to 143 pushed a 39.9% share under a 40% threshold and renamed the event
    from "YCS Montreal" to "2026 08 Quebec" -- the same coverage, more of it, and
    a worse answer.
    """
    named, prefixes = 0, Counter()
    for title in titles:
        parts = _TITLE_SPLIT.split(title.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0]:
            named += 1
            prefixes[parts[0]] += 1
    if not prefixes:
        return fallback

    # Score every candidate by how many titles begin with it. A shorter name can
    # only have at least the support of one extending it, so this settles on the
    # event rather than on a heading that happens to be common: "YCS Montreal Top
    # Tables Update" has thirteen posts of its own and is still not what the
    # event is called.
    #
    # The length tie-break is for a stable answer rather than a better one. Two
    # names in that position are unrelated -- one cannot extend the other and
    # still tie -- so nothing here can tell them apart, and picking on length
    # beats picking on whatever order the dictionary happened to be built in.
    def support(name):
        return sum(1 for t in titles if t.strip().startswith(name))

    name = max(prefixes, key=lambda p: (support(p), -len(p)))
    return name if support(name) >= MIN_SHARE * named else fallback


def clock(stamp: str | None) -> str | None:
    """'2026-08-16T11:07:30-07:00' -> '11:07'. Anything else is passed through.

    Deliberately shown in the offset the blog published it in, not converted:
    that is the time the coverage says it went up, and it is the local time at
    a North American event. Converting to the reader's zone would need their
    zone; converting to UTC would put a Saturday afternoon round at 22:00.
    """
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).strftime("%H:%M")
    except ValueError:
        return stamp


# "Genesys Format Round 5 Feature Match: Adrien Racek vs. Oliver Martin Ernst".
# The separator is written "vs." on the blog but "vs" appears too, and a name
# can contain "vs" inside a word, so it must be surrounded by spaces.
_VERSUS = re.compile(r"\s+vs\.?\s+", re.I)


def feature_players(title: str) -> tuple[str, str] | None:
    """The two Duelists a feature match names, or None if it names anything else.

    The post body is prose and photographs -- there is no table to read -- so the
    title is the only structured thing about it. That is enough for the round
    panel to say who played and link to the write-up, which is what the panel is
    for; it is not enough for decks or records, and those stay unknown rather
    than being filled in from somewhere they do not belong.
    """
    _, _, after = title.partition(":")
    parts = _VERSUS.split(after.strip() if after.strip() else title)
    if len(parts) != 2:
        return None
    a, b = (p.strip(" .") for p in parts)
    return (a, b) if a and b else None
