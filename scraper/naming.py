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

# How far into a title the opening-words fallback will read. Long enough for
# "Ultimate Duelist Series Season 6", short enough that it cannot swallow what
# the post is actually about.
MAX_NAME_WORDS = 6

# And a floor, not just a share. A share is measured against the titles that
# name anything, so one post naming something is a unanimous vote: every prefix
# of a lone title has 100% support. That is how a single feature match, the only
# post at the 2026 North America WCQ to use a colon at all, came within reach of
# naming the event "NAWCQ Round 11 Feature Match". Two posts agreeing is thin
# but is evidence; one is not evidence at all.
MIN_NAMING_TITLES = 2

# Words that say what a post is, not which event it belongs to. The opening-words
# fallback prefers the longest prefix among equally-supported ones, which with
# only a handful of titles reaches straight past the name into the subject:
# three WCQ posts, two of them round pairings, named the event "North America
# WCQ Round". A name never ends with one of these.
_SUBJECT_WORDS = {"round", "rounds", "day", "top", "final", "finals",
                  "standings", "pairing", "pairings", "feature", "match",
                  "deck", "decks", "profile", "lists", "update", "updates",
                  "results", "winner", "winners", "champion", "champions"}


def _trim_subject(name: str) -> str:
    """Cut a candidate name before the first word that names a post's subject."""
    words = name.split()
    for i, word in enumerate(words):
        if word.strip(":,.").lower() in _SUBJECT_WORDS:
            return " ".join(words[:i])
    return name


def _from_opening_words(titles: list[str], fallback: str) -> str:
    """The name when the posts do not use the colon convention at all.

    The 2026 North America WCQ heads every post "North America WCQ Round 13
    Pairings". No colon anywhere, so there was no prefix to count and the event
    reached the archive named after its slug: "2026 North America Wcq".

    Only reached when the convention produces no answer, so it cannot override a
    name the coverage does state. The threshold is the same, against every title
    rather than the ones that name something -- without the convention there is
    nothing to tell a heading from an abstention, and it is better to keep the
    slug than to name an event after whatever its posts happen to open with.
    """
    counts: Counter = Counter()
    for title in titles:
        words = title.strip().split()
        for i in range(1, min(len(words), MAX_NAME_WORDS) + 1):
            counts[" ".join(words[:i])] += 1
    if not counts:
        return fallback
    # Most support first. Among prefixes with exactly the same support the longer
    # one is strictly more informative and costs nothing -- "North America WCQ"
    # over "North", which every one of those titles also begins with.
    best = _trim_subject(max(counts, key=lambda p: (counts[p], len(p))))
    # Support is read after trimming: a shorter prefix is shared by at least as
    # many titles, never fewer, so this can only help.
    support = counts.get(best, 0)
    enough = (best and support >= MIN_SHARE * len(titles)
              and support >= MIN_NAMING_TITLES)
    return best.rstrip(":–—- ") if enough else fallback


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

    if prefixes:
        name = max(prefixes, key=lambda p: (support(p), -len(p)))
        if support(name) >= max(MIN_SHARE * named, MIN_NAMING_TITLES):
            return name
    # The convention gave no answer: either no title used it, or the titles that
    # did could not agree. The 2026 North America WCQ is the second case -- it
    # heads its coverage "North America WCQ Round 13 Pairings" with no colon at
    # all, and only its feature matches carry one, so the convention sees a
    # handful of unrelated headings and none of them is the event.
    return _from_opening_words(titles, fallback)


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
# The separator is written "vs." on the blog, and also "vs", and also the whole
# word: "Top 64 Feature Match: Hani Jawhari Versus Nicholas Scarangella". A name
# can contain any of those inside a word, so it must be surrounded by spaces.
#
# The spelled-out one is why YCS Philadelphia's Top 64 reached the archive as a
# round with nothing in it. Two feature matches were published for it, the newer
# of the two used "Versus", the players could not be read out of it, and the
# round was left holding a feature match that named nobody.
_VERSUS = re.compile(r"\s+(?:vs\.?|versus)\s+", re.I)


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
