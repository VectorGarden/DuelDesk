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
_SUBJECT_WORDS = {"round", "rounds", "day", "top", "table", "tables", "final",
                  "finals", "standings", "pairing", "pairings", "feature",
                  "match", "deck", "decks", "profile", "lists", "update",
                  "updates", "results", "winner", "winners", "champion",
                  "champions"}

# Event types written as initials, so a slug's "ycs" comes back as "YCS".
_ACRONYMS = {"ycs", "uds", "wcq", "sjc", "wcs", "ygoc", "rdycs", "nawcq"}


def names_an_event(name: str) -> bool:
    """Whether a name derived from the coverage identifies the event.

    Two of them do not. YCS Charlotte's coverage agreed most often on "Top
    Table Update", which is what a post is about rather than what the event was
    called, and YCS Hartford's on "YCS", which is thirty events.

    A word saying what a post contains is the giveaway for the first: no event
    is called Standings or Top Tables. The second is a bare event type with
    nothing to tell it from any other -- unlike "Genesys Championship", which is
    also all common words and is nonetheless the name of a tournament.
    """
    words = [w.lower().strip(":,.") for w in name.split() if w.strip(":,.")]
    if not words or any(w in _SUBJECT_WORDS for w in words):
        return False
    return not (len(words) == 1 and words[0] in _EVENT_WORDS)


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


# Words that describe coverage rather than name an event. A title split on its
# colon offers its first half as the event's name, and the 2016 World
# Championship heads six posts this way -- "Pairings: Round 2", "Pairings: Top
# 4", "Pairings: World Championship Finals!" -- while writing the event's own
# name, "2016 World Championship", bare and without a colon, so it never enters
# the vote at all. Pairings won it, and the event went to the front page,
# the feed and the winners table called Pairings.
_COVERAGE_WORDS = frozenset("""
pairings pairing standings standing results result final finals feature
features match matches round rounds top day deck decks profile breakdown
recap wrap up winner winners quarterfinals semifinals bracket brackets
update updates tables table photo gallery
""".split())
_WORDS_ONLY = re.compile(r"[^\W\d_]+", re.UNICODE)


def says_only_what_it_is(name: str) -> bool:
    """A candidate made of nothing but words for a kind of coverage.

    Not a name -- it would fit every event the blog has ever covered. Checked
    against all 140 names in the archive, it rejects exactly one: Pairings.
    "Final Standings" and "Top 8 Pairings" go the same way; "250th YCS", "Wcs
    2010" and "2016 World Championship" all keep their names, because a word
    that is not on this list is a word about which event this is.
    """
    words = _WORDS_ONLY.findall(name.lower())
    return bool(words) and all(w in _COVERAGE_WORDS for w in words)


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
        if len(parts) == 2 and parts[0] and not says_only_what_it_is(parts[0]):
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


# The regional qualifiers are written every way there is. The blog calls the
# North American one "NAWCQ", "North America WCQ" and "North American WCQ", and
# there is one of each every year, so the name has to carry the year to identify
# the event at all -- five of them sit in the archive under names that differ
# only in spelling.
_REGIONS = ((r"\bnawcq\b|\bnorth american?\b", "North America"),
            (r"\bcentral american?\b", "Central America"),
            (r"\bsouth american?\b", "South America"))
# "nawcq" as well, which _REGIONS already reads as North America and this
# refused to let through: the 2024 qualifier published its Swiss rounds as
# "north-america-wcq-..." and its top cut as "nawcq-...", and the two halves
# came out as two tournaments three days apart.
_IS_WCQ = re.compile(r"\b(?:na|n)?wcq\b|world championship qualifier", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

# Words that say what kind of event this is rather than where it was. A slug
# holding none of them is a place, and a place on this blog is a YCS.
_EVENT_WORDS = {"ycs", "wcq", "nawcq", "uds", "sjc", "wcs", "ygoc", "rdycs",
                "team", "remote", "duel", "invitational", "championship",
                "championships", "qualifier", "qualifiers", "regional",
                "series", "event", "genesys", "advanced", "extravaganza"}

# Where a place name stops being the place and starts being the country or the
# state it is in. Only ever read as the last word of a slug that is otherwise a
# place, so it separates "santiago-chile" without having to know that Santiago
# is a city -- and cities of two and three words, San Diego and Buenos Aires
# and Sao Paulo, come through whole rather than being split at a guess.
_ENCLOSING = {"argentina", "brazil", "canada", "chile", "colombia", "ecuador",
              "guatemala", "mexico", "panama", "paraguay", "peru", "uruguay",
              "venezuela", "california", "florida", "nevada", "ohio", "texas"}


def _year(slug: str, ended: str | None) -> str | None:
    """The year the event was held.

    The slug first, because it is the event's own name for itself: the 2013
    South American WCQ has coverage edited into 2014, and it is not the 2014
    one -- there was a 2014 one.
    """
    m = _YEAR.search(slug)
    return m.group(0) if m else ((ended or "")[:4] or None)


# The World Championship, which the blog has spelled five ways across five
# events -- "2010 Yu-Gi-Oh! World Championship", "Yu-Gi-Oh! TCG WORLD
# CHAMPIONSHIP 2026", and for 2016 nothing at all, because its coverage heads
# six posts "Pairings: ..." and writes the event's own name without a colon, so
# the vote never saw it and the archive called the event Pairings.
#
# Named for the year like a qualifier is, because there is one every year and
# the year is what tells them apart.
_IS_WORLDS = re.compile(r"world championship|\bwcs\b", re.I)


def worlds_name(slug: str, name: str, ended: str | None) -> str | None:
    """"World Championship 2016" for a World Championship, or None.

    A qualifier is not one, and says so in its own name -- "World Championship
    Qualifier" is what WCQ stands for -- so those are refused here and answered
    by wcq_name, which runs first anyway.
    """
    text = f"{slug} {name}".replace("-", " ")
    if _IS_WCQ.search(text) or not _IS_WORLDS.search(text):
        return None
    year = _year(slug, ended)
    return f"World Championship {year}" if year else None


def wcq_name(slug: str, name: str, ended: str | None) -> str | None:
    """"North America WCQ 2026" for a regional qualifier, or None."""
    text = f"{slug} {name}".replace("-", " ").lower()
    if not _IS_WCQ.search(text):
        return None
    for pattern, region in _REGIONS:
        if re.search(pattern, text):
            year = _year(slug, ended)
            return f"{region} WCQ {year}" if year else f"{region} WCQ"
    return None


def place_name(slug: str) -> tuple[str | None, str | None]:
    """("YCS Santiago", "Santiago, Chile") for a slug that names a place.

    Only reached when the coverage agreed on no name of its own, so this is the
    last thing tried before falling back to the slug title-cased, which is how
    "11 10 Columbus" and "201504 Bogota D C Colombia" came to be the labels in
    the event list.

    A place on this blog is a YCS. Nothing else is assumed: a slug carrying any
    word about what kind of event it was is left alone, because that word is
    more information than this guess.

    The country stays out of the name and is kept beside it. "YCS Santiago" is
    what the event is called; that it was in Chile is worth knowing and is not
    part of the title.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", slug.lower()) if t]
    # A token holding a digit is the date or the count -- 201504, 300th,
    # 75thsjc. One or two letters is administrative: the states and provinces
    # are written that way throughout (anaheim-ca, atlanta-ga, pittsburgh-pa),
    # and the D and C of "bogota-d-c-colombia" are Distrito Capital rather than
    # part of the city.
    words = [t for t in tokens if not any(c.isdigit() for c in t) and len(t) > 2]
    # A slug saying what kind of event it was keeps that word and gives up the
    # rest to the place: "2022-ycs-charlotte" is the YCS at Charlotte. Only
    # types written as initials, because those are the ones a title would carry
    # anyway -- anything longer is a word about the event, and a word about the
    # event is more than this guess should overrule.
    kind = [t for t in words if t in _ACRONYMS]
    place = [t for t in words if t not in _EVENT_WORDS]
    if not place or len(kind) != len(words) - len(place):
        return None, None
    prefix = " ".join(t.upper() for t in kind) or "YCS"
    title = lambda ts: " ".join(t.title() for t in ts)
    if len(place) > 1 and place[-1] in _ENCLOSING:
        city, where = title(place[:-1]), title(place[-1:])
        return f"{prefix} {city}", f"{city}, {where}"
    # No country in the slug, so none is known. "Columbus" on its own would be
    # the title with a word taken off rather than anything the archive did not
    # already say.
    return f"{prefix} {title(place)}", None


def split_location(name: str) -> tuple[str, str | None]:
    """Take the country back out of a name the coverage wrote it into.

    The blog titles some events "YCS Cancun, Mexico". The comma says exactly
    where the place name ends, so nothing has to be guessed -- and what is left
    is what the event is called.
    """
    head, sep, tail = name.partition(",")
    if not sep or not tail.strip():
        return name, None
    # The city is what is left once the words saying what kind of event it was
    # are off the front. Taking the last word instead made "YCS Guatemala City"
    # a city called "City".
    words = head.split()
    while words and words[0].lower() in _EVENT_WORDS:
        words.pop(0)
    city = " ".join(words) or head.strip()
    return head.strip(), f"{city}, {tail.strip()}"


def canonical_name(name: str, slug: str, ended: str | None, *,
                   named: bool = True) -> tuple[str, str | None]:
    """(the event's name, where it was held). The location may be None.

    `named` says whether the coverage agreed on `name` or it is the slug
    title-cased. A qualifier is renamed either way -- the blog's own "NAWCQ" is
    a name, and not one that says which year's -- while a place is guessed at
    only when there was nothing to go on, or nothing worth having.
    """
    if qualifier := wcq_name(slug, name, ended):
        return qualifier, None
    if worlds := worlds_name(slug, name, ended):
        return worlds, None
    # Either the coverage never agreed on a name, or it agreed on something that
    # is not one. YCS Charlotte's settled on "Top Table Update" and YCS
    # Hartford's on "YCS", and the slug does better than both.
    if not (named and names_an_event(name)) and (place := place_name(slug))[0]:
        return place
    return split_location(name)


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
