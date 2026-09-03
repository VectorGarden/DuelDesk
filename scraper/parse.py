#!/usr/bin/env python3
"""Parse a Yu-Gi-Oh! TCG blog coverage post into structured data.

Kept separate from fetching so it can be tested against saved fixtures without
touching the network -- which is also the only way to test it in CI.

Table shapes are detected from their headers rather than assumed by position,
because the blog uses at least three different layouts for what is nominally
the same kind of content:

    Rank | Player Name | Points                                    standings
    Table | P1 First Name | P1 Last Name | vs. | P2 ... | P2 ...   pairings
    Table | Duelist 1 Name | Duelist 1 Deck Type | vs. | ...       pairings + decks

Assuming column positions would silently mis-read one of them.
"""
from __future__ import annotations

import html
import re
from functools import lru_cache
from dataclasses import dataclass, field, asdict
from typing import Any

# Region codes ride along inside name cells: "Philip DEU", "Brandon QC",
# "Humza PA", "Samson George ON". They mix countries (DEU, NLD) with provinces
# and states (QC, ON, PA), hence "region" rather than "country".
#
# They must be stripped per *cell*, before first and last names are joined:
# "Philip DEU" + "Weidinger" naively becomes "Philip DEU Weidinger", where the
# trailing token is a surname and the code is stranded in the middle.
_REGION_TOKEN = re.compile(r"[A-Z]{2,3}")

# Generational suffixes are all-caps two-or-three letter tokens too, so the
# region rule swallows them. That silently splits one person into two: the
# standings cell "Aldrich III, Gordon Russell" keeps the suffix (the comma
# stops it matching) while the pairings cells "Gordon Russell" + "Aldrich III"
# lose it, and the appearance count then misses every round they played.
#
# VI and IA are also real region codes; a name suffix is the likelier reading in
# a player list, and getting it wrong here costs a whole player's record.
_NAME_SUFFIXES = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "JR", "SR"}

# Some standings tables carry a player ID and a status inside the name cell:
#   "Adrien (0200512639) (PlayoffCut - Round 11) Racek"
# Left in place the name never matches the same player in a pairings table, so
# their appearances are never counted and their record cannot be derived. This
# is why an entire 169-row table came back partial.
_ANNOTATION = re.compile(r"\s*\([^)]*\)")

# The status half of that annotation names the last round the player took part
# in, and is worth keeping rather than discarding. Four spellings appear:
#
#   Drop - Round 4         left the event during round 4
#   TopX - Round 7         did not survive the day-one cut, made after round 7
#   PlayoffCut - Round 11  finished Swiss, did not make the playoff
#   Cut - Round 12         played in the top cut and lost in that bracket round
#
# For the first three the round is exactly the player's last Swiss round: it
# matched their final pairings appearance for all 161 annotated entrants at YCS
# Montreal, with no exceptions. "Cut" is the odd one -- its round counts on past
# the end of Swiss into the bracket (12, 13, 14 for an eleven-round event), so
# it cannot be read as a Swiss round and is handled separately.
#
# "TopX" is literal in the source, not a placeholder for a number.
_STATUS = re.compile(
    r"\(\s*(Drop|PlayoffCut|Cut|Top\s*X)\s*[\u2010-\u2015-]\s*Round\s*(\d+)\s*\)",
    re.I)

_TAG = re.compile(r"<[^>]+>")
_TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# WordPress wraps a post's prose in this. Only the opening is kept, and only for
# the posts that announce a winner: the sentence naming one is always the first
# thing such a post says, and holding whole articles in memory for every page of
# a 140-post event to read one line of them would be waste.
_ENTRY_OPEN = re.compile(r"class=\"[^\"]*entry-content[^\"]*\"[^>]*>", re.I)
_DIV = re.compile(r"<(/?)div\b[^>]*>", re.I)


def entry(doc: str) -> str:
    """The post's body: everything inside the entry-content div.

    Found by counting divs rather than by looking for the pair that closes it.
    A regex ending at the first "</div></div>" is right for a flat post and
    wrong for a nested one, and it fails silently -- YCS Chicago's winner post
    nests its text four divs deep, so 140 characters of a 312KB page came back
    and the rest, including

        Raphael Neven from the Netherlands used his Lunalight Deck to come out
        on top in a field of 1566 Duelists

    was never read. The event had a winner post naming a Duelist in its own Top
    4 and no champion, and the empty string looked like a post made of images.

    Rare -- four pages in a cache of 4,349 -- but silent, and what it takes is
    the end of the post.
    """
    if not (m := _ENTRY_OPEN.search(doc)):
        return ""
    start, depth = m.end(), 1
    for tag in _DIV.finditer(doc, start):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return doc[start:tag.start()]
    # No closing div for it. Everything to the footer, which is where the old
    # rule stopped too.
    rest = doc[start:]
    cut = re.search(r"<footer", rest, re.I)
    return rest[:cut.start()] if cut else rest
_SCRIPTS = re.compile(r"<(script|style).*?</\1>", re.S | re.I)
LEAD_CHARS = 400
# A finals feature match is a whole match written out, and the sentence naming
# the champion is somewhere in it -- 5,000 characters in, for the one that
# crowned the North America Remote Duel YCS. So these are kept whole, within
# reason. Only the finals, and only until the build has read them.
MATCH_CHARS = 12000
# A round of pairings written out is long: 64 tables of two named Duelists and
# their decks. Read whole, or the bottom of the room goes missing.
PROSE_CHARS = 40000


# Zero-width characters that are not whitespace to str.strip() and are not
# anything to a reader either. TEAM YCS Las Vegas 2023 carries a byte order
# mark inside the cells of its finals table, so "vs.\ufeff" was not "vs." and
# the row announcing the match's two teams was not recognised as one -- the
# final's three duels stood as three separate matches, in an event whose every
# other cut round is a team match of three.
_INVISIBLE = str.maketrans("", "", "\ufeff\u200b\u200c\u200d\u2060")

# The one tag that means "and now a space".
_BREAK = re.compile(r"<br\s*/?>", re.I)


# Cached for the reason strip_region and build._words are: a table's cells are
# the same handful of strings over and over -- a Duelist's name in every round
# they played, "Advanced" in every format column, the same deck in every seat
# that played it. Across forty events this was called 904,677 times about
# 26,956 distinct fragments, so 97% of the calls already had their answer, and
# every distinct fragment together is a megabyte.
@lru_cache(maxsize=None)
def _text(fragment: str) -> str:
    # One line, whatever the markup did. A cell holding "Destiny Adventurer<br>
    # Prank-Kids" came through with the break still in it, and the newline is
    # in the deck name the archive stores and the site prints: 35 deck names
    # and 136 cells carried one, and "Sky\n  Striker" is a different name from
    # "Sky Striker" to everything that counts them.
    # A line break is a space, not nothing: dropped with the rest of the tags,
    # "Sky<br>Striker" comes through as "SkyStriker".
    return re.sub(r"\s+", " ",
                  html.unescape(_TAG.sub("", _BREAK.sub(" ", fragment)))
                  .replace("\xa0", " ").translate(_INVISIBLE)).strip()


# A title written into the name after a dash, which 2013's Central American
# coverage does: "Campos Valverde, Jorge Luis - Costa Rican Champion". Six
# names in the archive, 47 rows.
#
# Only where the annotation says "Champion". #113 warned that reading whatever
# follows a dash cuts a real surname in half, and the archive proves it: of 68
# names holding a dash, 62 are a team -- "Nguyen - Tamez - Cebrian", "Council
# of Robina - Walmart Edition" -- or a surname, "Jesus Correa - Moreira". Six
# say Champion, and those six are the mangled ones.
_TITLE_AFTER_DASH = re.compile(r"\s*[-–—]\s*([^,()]*?\bchampions?\b[^,()]*?)\s*(?=$|[,(])", re.I)


def strip_title(name: str) -> tuple[str, str | None]:
    """'Jorge Luis - Costa Rican Champion' -> ('Jorge Luis', 'Costa Rican Champion')."""
    if not (m := _TITLE_AFTER_DASH.search(name)):
        return name, None
    return (name[:m.start()] + name[m.end():]).strip(), m.group(1).strip()


# Cached for the same reason build._words is: the archive seats the same
# Duelist in every round they played, so this is asked the same question over
# and over. Across forty events it was called 447,354 times about 18,974
# distinct strings -- 96% of the calls already had their answer.
#
# Safe to cache because it is a pure function of the string: the country and
# title it strips, the codes it recognises and the suffixes it spares are all
# fixed patterns, and the tuple it returns is immutable.
@lru_cache(maxsize=None)
def strip_region(name: str) -> tuple[str, str | None]:
    """'Philip DEU' -> ('Philip', 'DEU'). Leaves ordinary names alone.

    The code is not always trailing. Where a whole name arrives in one cell it
    can sit mid-string -- "Joshua Aaron TX Jones", "Christian Jorel Sevil CA
    Agustin" -- so every all-caps 2-3 letter token is removed, not just the last.

    This matters beyond tidiness: records are derived by counting a player's
    appearances across pairings pages, so the same person must normalise
    identically everywhere or they count as two people.

    The blog writes ordinary names in title case and reserves all-caps for these
    codes. At least one token is always kept, so a name that is nothing but such
    a token survives intact.
    """
    # Written out in words before it is looked for in capitals. A country or a
    # title spelled out survives every rule below, which reads only two- and
    # three-letter codes, and normalise_name then swaps the comma and leaves it
    # in the middle of the name.
    name, spelt = strip_country(name)
    if spelt is None:
        name, spelt = strip_title(name)
    tokens = _ANNOTATION.sub(" ", name).strip().split()
    if not tokens:
        return "", spelt
    # One pass, because the question is asked of every token of every name in
    # the archive and asking it twice is the same regex run twice: two list
    # comprehensions over the same tokens meant three million fullmatch calls
    # where a million and a half would do.
    codes: list[str] = []
    kept: list[str] = []
    for t in tokens:
        target = (codes if _REGION_TOKEN.fullmatch(t) and t not in _NAME_SUFFIXES
                  else kept)
        target.append(t)
    if not kept:                      # the whole name looked like a code
        return " ".join(tokens), spelt
    return " ".join(kept), (codes[0] if codes else spelt)


def split_status(cell: str) -> tuple[str | None, int | None]:
    """('... (Drop - Round 4) ...') -> ('Drop', 4). (None, None) if absent.

    The status is returned separately from the name; the name itself still has
    every parenthetical stripped by `strip_region`, because a status left inline
    stops the player matching their own pairings rows.
    """
    m = _STATUS.search(cell)
    if not m:
        return None, None
    label = re.sub(r"\s+", "", m.group(1)).lower()
    canonical = {"drop": "drop", "playoffcut": "playoffcut",
                 "cut": "cut", "topx": "topx"}[label]
    return canonical, int(m.group(2))


def split_team(cell: str) -> dict[str, Any]:
    """'Road of the King: Yacine S., Francisco O., Patrick H.' -> name + members.

    A Team YCS enters three Duelists a side and publishes one standings row per
    team, written this way. Read as one Duelist it is a name the comma rule
    turns inside out -- normalise_name exists to make "Gouge, Justin" into
    "Justin Gouge", and it does the same to everything after the colon.

    The team's own name is left exactly as printed. It is a name someone chose,
    not a person's, so neither the comma rule nor the region rule applies to it:
    a team called "TCG Masters" would otherwise lose half of itself to a rule
    for stripping province codes.
    """
    name, _, rest = cell.partition(":")
    members = [m.strip() for m in rest.split(",") if m.strip()]
    return {"name": name.strip() or cell.strip(), "members": members}


def normalise_name(raw: str) -> str:
    """The blog writes names three ways; settle on 'First Last'."""
    raw, _ = strip_region(_text(raw))
    if "," in raw:                       # "Gouge, Justin Matthew"
        last, _, first = raw.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    return raw


@dataclass
class Table:
    kind: str                    # standings | pairings | unknown
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Post:
    title: str
    kind: str                    # pairings | standings | feature | result | deck | news
    fmt: str | None              # Advanced | Genesys | None
    round: Any                   # int, "Top 8", "Final", or None
    table: Table | None = None
    # The opening of the prose, kept only where something might be read out of
    # it. Never written to the archive -- see to_dict.
    lead: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.table is None:
            d.pop("table")
        # Working data for the build, not a fact about the post. The archive
        # carries what the coverage said, not the paragraph it said it in.
        d.pop("lead", None)
        return d


def lead(doc: str, limit: int = LEAD_CHARS) -> str:
    """The opening of a post's prose, flattened to one line.

    Enough to read a winner out of and no more. Tables are cut first: a post
    announcing a champion sometimes carries the final standings underneath, and
    a thousand names of table would drown the one sentence that matters.
    """
    if not (found := entry(doc)):
        return ""
    body = _TABLE.sub(" ", _SCRIPTS.sub(" ", found))
    return re.sub(r"\s+", " ", _text(body))[:limit].strip()


def page_title(doc: str) -> str:
    m = _TITLE.search(doc)
    if not m:
        return ""
    t = _text(m.group(1))
    # WordPress appends the site name after an en dash or pipe.
    return re.split(r"\s+[–|]\s+", t)[0].strip()


def detect_format(text: str) -> str | None:
    low = _words(text)
    if "genesys" in low:
        return "Genesys"
    if "advanced" in low:
        return "Advanced"
    return None


# The tournaments that run beside the main event and get written up like it,
# each under its own name. Counted from what the archive holds: Dragon Duel 228
# posts, ATTACK OF THE GIANT CARD 128, public events 84, Time Wizard 34.
#
# Named rather than lumped together, because they are four different
# tournaments and a reader asking for one of them means that one. Longest
# first, so "attack of the giant card" is not read as its own last two words.
#
# Deliberately not winners.SIDE_EVENT, which is a wider net cast for a
# different purpose. That one matches "invitational", and a UDS Invitational is
# a main event in this archive with a hundred posts of its own -- filing those
# under anything but their own format would be a plain lie.
_SIDE_COVERAGE = [
    (re.compile(r"attack of the giant card"), "Attack of the Giant Card"),
    (re.compile(r"dragon duel"),              "Dragon Duel"),
    (re.compile(r"public event"),             "Public Events"),
    (re.compile(r"time wizard"),              "Time Wizard"),
]


def coverage_format(text: str, fmt: str | None) -> str | None:
    """What a post is coverage *of*, which is not always a format of the event.

    Dragon Duel, ATTACK OF THE GIANT CARD, the public events and Time Wizard
    all run alongside the main event and the blog writes them up like any other
    tournament -- 474 posts between them. A reader filtering the feed wants
    them in the list of things to filter by.

    Each under its own name. They are four different tournaments, and a reader
    asking for one of them means that one -- calling the button Dragon Duel
    said that three quarters of what it held was something it is not, and
    calling it Other says only that nobody looked.

    It is deliberately not a value detect_format returns. That answer groups an
    event's rounds into tournaments, and a Dragon Duel table read as one of the
    main event's has cost this archive real damage:
    "dd-wcq-ca-standings-after-round-1" became the WCQ's own standings once.
    The feed can name the thing without the builder having to believe in it.
    """
    low = _words(text)
    for pattern, name in _SIDE_COVERAGE:
        if pattern.search(low):
            return name
    return fmt


def detect_round(text: str, kind: str | None = None):
    """The round a post is about, or None.

    "Final Standings After Swiss" is not the Final -- it is the standings at the
    end of Swiss. Matching a bare "final" there would file the whole standings
    table under the last cut round.
    """
    low = _words(text)
    if m := re.search(r"\btop\s*(\d+)", low):
        return f"Top {m.group(1)}"
    if m := re.search(r"\bround\s*(\d+)", low):
        return int(m.group(1))
    if kind == "standings" and re.search(r"after swiss|final standings", low):
        return None
    # A semi-final is the Top 4 and a quarter-final the Top 8, which is what
    # the rest of the archive calls them. Before this, "Semi-Finals pairings"
    # matched the "finals" inside it and became the Final -- two matches in a
    # round that holds one, so the World Championship 2026 reported two
    # Duelists a side and was refused. "Semifinals", written closed, matched
    # nothing at all and was no round.
    if re.search(r"\bsemi[\s-]?finals?\b", low):
        return "Top 4"
    if re.search(r"\bquarter[\s-]?finals?\b", low):
        return "Top 8"
    if re.search(r"\bfinals?\b", low):
        return "Final"
    return None


def _words(text: str) -> str:
    """Lower-case, with separators flattened to spaces.

    Classification runs on slugs as well as titles -- knowing a post is
    pairings before fetching it is what lets a limited budget go to the posts
    that carry results. A slug writes "deck-lists" and "feature-match", so a
    pattern expecting spaces silently files both under news.
    """
    return re.sub(r"[-_/]+", " ", text.lower())


# What a post is, in the order the questions have to be asked. The page asks
# the same questions of live feed titles in app.js kindFrom, and the two must
# give the same answer: see test/fixtures/kinds.json, which both test suites
# read. They had drifted apart over 403 of the archive's 8,076 titles before
# this list existed.
#
# Order is the rule, not a detail:
#
#   "YCS Hartford Top 32 Pairings and Deck Lists" is a bracket that also
#   prints decks, and the bracket is the part worth having, so pairings is
#   asked first. "TEAM YCS Las Vegas Winner Deck Lists" is a decklist post
#   about a winner, so deck is asked before result.
#
# Singular and plural, throughout. The final is the one round the blog titles
# "Final Pairing", having exactly one match to report; a post announcing
# several winners is titled "Winners". Requiring one or the other filed both
# as news -- which the fetch budget ranks last, so the round the whole bracket
# builds towards was the one post never fetched.
KINDS = (
    ("pairings",  r"\bpairings?\b"),
    ("standings", r"\bstandings\b|\bpoint totals\b"),
    # Not "Final Match", though the blog titles sixty-six posts that way and
    # the page used to read them as feature matches. Those posts carry the
    # final's pairing table and often only a line of preview text -- "Good
    # luck to both Duelists!" -- and a feature match is a write-up, so its
    # table is not read as a round. Calling them feature cost the 2019 UDS
    # Invitational Medellin its champion: the Final had no pairing left to
    # derive one from.
    ("feature",   r"\bfeature match\b|\bmatch:\s"),
    # Any post about the decks played, which is looser than it looks: the blog
    # writes "Top 8 Decklists", "Deck Breakdown", "Deck Type Breakdown",
    # "Duelists and Decks in Day 2" and "Top 16 Players and Decks", and a rule
    # naming the forms it knew about lost the ones it did not.
    #
    # What has to come out is not a phrasing but three series that are about
    # decks without being coverage of any: QQ, the blog's reader-question
    # column, which asks "Which Deck Are You Using This Weekend?" fifty-nine
    # times; the Structure Deck and game mat products; and Deck Update, which
    # is a set announcement. Deck check is a floor penalty.
    # "Decklists" is one word as often as two, and \bdecks?\b does not see it.
    ("deck",      r"\bdecks?\b|\bdeck ?lists?\b|\bdeck ?profiles?\b"),
    ("result",    r"\bwinners?\b|\bchampions?\b|\bcongratulations\b|\bundefeated\b"),
)

# About decks, but not coverage of any. See the "deck" line above.
_NOT_DECK_COVERAGE = re.compile(
    r"\bqq\b|\bstructure deck\b|\bdeck check\b|\bdeck update\b"
    r"|\bgame mat\b|\btech update\b")


def detect_kind(text: str) -> str:
    low = _words(text)
    for kind, pattern in KINDS:
        if kind == "deck" and _NOT_DECK_COVERAGE.search(low):
            continue
        if re.search(pattern, low):
            return kind
    return "news"


# A column heading that names a result rather than a Duelist.
# A column heading that says the cell under it is not part of anybody's name.
#
# "deck" is here for the same table that put "winner" here. The 2013 World
# Championship heads its cut
#
#   Table | Player 1 | VS. | Player 2 | | Winner | Deck
#
# and everything right of the divider was read as Player 2, so the deck was
# appended to their name: "Shin En Dragon Rulers Huang" for a Duelist called
# Shin En Huang. That is not a label a reader would forgive, and it cost the
# event its champion -- both finalists matched the winner post on "Dragon
# Rulers", which was never part of anybody's name.
#
# Where a deck column belongs to the Duelist beside it, it is read before this
# and kept: that is the `decks` split above, which pairs each name with the
# deck in its own half of the table. This one belongs to the winner of the
# match rather than to either player, so there is nobody to give it to.
_NOT_A_NAME = re.compile(r"(winner|result|score|record|outcome|deck)\b", re.I)


# The column that holds the deck, wherever it sits. A side is not always
# "name then deck": the 300th YCS heads its Genesys rounds
#
#   Table | Duelist 1 Name | Duelist 1 Points | Duelist 1 Deck Type | vs. | ...
#
# and taking the cell after the name took the points, so 186 rows of that
# event were published with a Duelist's score as their deck -- "6", "9", "12".
_DECK_COL = re.compile(r"\bdecks?\b", re.I)

# And the columns beside it that are about the Duelist without being their
# name. Searched rather than matched from the start, because these headings
# are written "Duelist 1 Points" as often as "Points".
_ABOUT_NOT_NAMED = re.compile(r"\b(points?|record|score|result|standing)\b", re.I)


_VS_CELL = ("vs.", "vs")


def _announces_a_team(row: list[str]) -> bool:
    """Whether this row announces a team match rather than naming columns.

    The same test the pairings reader uses further down: a row carrying two
    names and nothing else but the words that frame them.
    """
    named = [c for c in row if c.strip().lower() not in ("team", "vs.", "vs", "")]
    return len(named) == 2 and any(c.strip().lower() == "team" for c in row)


def _infer_header(row: list[str]) -> list[str] | None:
    """A header for a table that has none, read off a row of its own data.

    Eleven round posts open straight into their rows -- no header at all, or
    a caption where one should be:

        ['1', 'Toby C. CA Lin', 'vs.', 'Nazree Asri']
        ['1', 'Nicholas James NH King', 'Raphael Pelaja Neven']
        ['1', 'Paul Stephen', 'Aronson', 'vs.', 'Brian John', 'Kalina']
        ['Rodrigues de Souza, Rafael Jose from Brazil (Zoodiac)', 'vs', ...]
        ['1', 'Lopez Ramirez, Walter Eligio', '30']

    What the columns are is legible from the row itself: a leading number is
    a table number or a rank, a "vs." is the divider, and a trailing number
    where there is no divider is points. Naming them is enough -- everything
    downstream reads columns by their names, so an inferred header is read
    exactly like a written one.

    None where the row says nothing, which leaves the table unknown and the
    post dropped, as before. This only ever runs on a table no header could
    be read from, so a table that reads today cannot be changed by it.
    """
    if not row or not any(c.strip() for c in row):
        return None
    ranked = row[0].strip().isdigit()
    vs_at = next((i for i, c in enumerate(row) if c.strip().lower() in _VS_CELL), None)

    if vs_at is not None:
        if vs_at == 0 or vs_at == len(row) - 1:
            return None                 # a divider with nothing on one side
        head = ["Table"] if ranked else []
        left = vs_at - len(head)
        return (head + ["Player 1"] * left + ["vs."]
                + ["Player 2"] * (len(row) - vs_at - 1))

    if not ranked:
        return None                     # nothing to say where the row starts

    # No divider. Three cells is a rank, a name and a number -- which is
    # standings -- or a table number and two Duelists, which is a pairing.
    if len(row) == 3:
        return (["Rank", "Player", "Points"] if row[2].strip().isdigit()
                else ["Table", "Player 1", "Player 2"])
    if len(row) == 2:
        return ["Rank", "Player"]
    return None


def _classify_table(header: list[str]) -> str:
    """What a table is, from its column headings.

    A points column used to be required to call something standings, and that
    is not what the blog publishes. Points appear once a tournament is far
    enough along to have them; before that, and at some events throughout, the
    table is Rank and Player Name and nothing else. YCS Columbus publishes all
    23 of its standings that way, so requiring points threw away the entire
    event -- 17 rounds, both formats, no field size and no standings at all.
    """
    low = [h.lower() for h in header]
    if "table" in low and any(h.strip() in ("vs.", "vs") for h in low):
        return "pairings"
    # Two sides is what makes a table a pairing, and the blog heads them a
    # dozen ways: Team 1 and Team 2 at a Team YCS, Player 1 and Player 2 for
    # most of 2016 and 2017 and every round of the 2022 Remote Duel YCS, plain
    # Name and Name before that. Requiring a "vs." column, or the word Table,
    # or the word Team, left 149 round posts unread -- tables all of them, and
    # none of them a shape anybody had told this function about.
    # Standings first, because a ranking is never a pairing and some of them
    # name two columns that read like sides. TEAM YCS La Paz heads its
    # standings "Rank | Team Name | Duelist Names | Points", and asking about
    # sides before asking about rank read every one of them as a bracket --
    # which left that event with no standings, no format, and nothing at all.
    #
    # The name column is not always headed -- "Rank |  | Points" is how nine of
    # them arrive -- so the points say what the table is where no heading can.
    if "rank" in low and (any("player" in h or "name" in h for h in low)
                          or any("point" in h for h in low)):
        return "standings"
    sides = sum(bool(re.match(r"(player|duelist|team|name)\b", h)) for h in low)
    if sides == 2:
        return "pairings"
    return "unknown"


# A country written out, after the dash the blog separates it with. The codes
# strip_region knows are three letters in capitals; this is "- Trinidad and
# Tobago", which stayed inside the name and made one Duelist two people.
# Spaces are required around the dash, so hyphenated surnames are left alone.
# The separator an annotation opens with, and what one leaves behind.
_LEADING = re.compile(r"^[\s,\u2010-\u2015-]+")
# What is left on the end of a name when the annotation is taken off it.
_DANGLING = re.compile(r"[\s,\u2010-\u2015-]+$")


_SPELT_REGION = re.compile(r"\s+[-\u2010-\u2015]\s+([^-\u2010-\u2015]+)$")


def read_annotation(cell: str) -> tuple[str, str | None, str | None]:
    """A Duelist cell's name, the region written beside it, and the deck.

    Prose pairings have always read "Name (Country - points - Deck)" this way.
    A table cell carries the same thing, and the blog writes it either way
    round:

        Quispe Llanco, Ariel (Bolivia) - Burning Abyss Phantom Knights
        Lopez Rangel, Carlos Eduardo - (Colombia) Fire Kings Kozmos
        Deonarine, Brandon Luke - Trinidad and Tobago (SPYRAL)

    The bracket is the country in the first two and the deck in the third, so
    which one it is cannot be read off the bracket. What does not vary is the
    order: where a cell carries both, the region comes first and the deck
    second. That is the rule here.

    Reading none of this is what put a deck inside a name. The 2016 South
    America WCQ wrote its standings the first way, and the name kept the deck
    -- which reconcile_names then preferred, because it counts words, folding
    eight clean names into their mangled spellings across all eleven rounds
    and sending its champion to the winners page as "Joaquin - Dracoslayer
    Performapals Rinaldi Petroni".

    Both parts are optional and neither is invented: a cell with no bracket
    comes back unchanged, with no region and no deck.
    """
    text = cell.strip()
    if not (m := _PARENS.match(text)) or not m.group(1).strip():
        # No bracket, or a bracket with nothing in front of it. The 2016 World
        # Championship writes "(Japan) Yada, Makoto" -- the country leads and
        # the name follows -- and reading that as an annotation left the name
        # as the empty string in front of the bracket. A leading bracket is
        # strip_region's business, as it was before this function existed.
        #
        # A dash with no bracket is left alone too. "Correa - Moreira, Jesus"
        # is a compound surname, and 137 names in the archive carry a country
        # after a dash with nothing to say which it is.
        return text, None, None

    head, bracket, tail = m.group(1), m.group(2).strip(), text[m.end():]
    # An annotation written before the bracket rather than after it.
    spelt = None
    if s := _SPELT_REGION.search(head):
        spelt, head = s.group(1).strip(), head[:s.start()]

    # In the order the coverage wrote them, so the first is the region.
    said = [x for x in (spelt, bracket, _DANGLING.sub("", _LEADING.sub("", tail)).strip()) if x]
    if len(said) > 1:
        region, deck = said[0], said[-1]
    else:
        # One annotation, which may still hold both: "(Japan - 9 points -
        # Frog Monarch)" is a country, a total and a deck in one bracket. The
        # deck is the last of them, because that is the part every one has.
        bits = [b.strip() for b in re.split(r"\s+[-\u2010-\u2015]\s+", said[0])] if said else []
        region = bits[0] if len(bits) > 1 else None
        deck = bits[-1] if bits else None
    return _DANGLING.sub("", head).strip(), region or None, _deck_or_none(deck)


def parse_table(doc: str) -> Table | None:
    tables = []
    for m in _TABLE.finditer(doc):
        rows = [[_text(c) for c in _CELL.findall(r)] for r in _ROW.findall(m.group(0))]
        if rows := [r for r in rows if r]:
            tables.append(rows)
    if not tables:
        return None

    header, body = tables[0][0], list(tables[0][1:])
    # A caption where the header should be. The 2013 World Championship heads
    # each table with a row of its own -- "Main World Championship | Round 1"
    # -- and the header the reader needs is underneath it:
    #
    #   ['', 'Main World Championship', '', 'Round 1', '', '']
    #   ['Table', 'Player 1', 'VS.', 'Player 2', '', 'Winner']
    #
    # Read as the header, the caption says nothing the classifier knows, so
    # the table came back unknown and the post was dropped -- every round of
    # that event, which is why it has never been in the archive.
    #
    # Only ever one row, and only when the row below it is a header this
    # reader recognises. A table whose first row is data is left alone: that
    # is a different shape and guessing at it here would eat a pairing.
    if _classify_table(header) == "unknown":
        if body and _announces_a_team(header) and _classify_table(body[0]) != "unknown":
            # Not a caption: TEAM YCS Las Vegas announces the final's teams
            # above the header rather than below it, and dropping that row as
            # a caption left the match's three duels standing as three
            # separate matches -- a Final of three singles in an event whose
            # every other cut round is a team match of three.
            header, body = body[0], [header] + body[1:]
        elif body and _classify_table(body[0]) != "unknown":
            header, body = body[0], body[1:]
        elif made := _infer_header(header):
            # The first row is data, so it stays in the body and gets a
            # header of its own.
            header, body = made, [header] + body
        elif body and (made := _infer_header(body[0])):
            # A caption over a table with no header under it. The 2013 North
            # America WCQ writes "Top   16" in a row by itself and then its
            # pairings, with nothing naming the columns.
            header = made
    # And a blank row ends it. The same event puts two tournaments in one
    # table -- the Main World Championship, an empty row, then the Dragon Duel
    # World Championship with a caption and header of its own:
    #
    #   ['4', 'Murakoshi, Kei', 'VS.', 'Huang, Shin En', ...]
    #   ['', '', '', '', '', '', '']
    #   ['', 'Dragon Duel World Championship', '', 'Top 8', '', '', '']
    #
    # Read straight through, that caption has two cells that are not noise, so
    # it was taken for the announcement of a team match -- which is both a
    # fifth match in a Top 8 and the reason a singles championship came back
    # holding 38 Teams.
    #
    # The Dragon Duel is its own tournament and is not this one's rounds.
    for i, r in enumerate(body):
        if not any(c.strip() for c in r):
            body = body[:i]
            break
    # One round is not always one table. The 2017 UDS Invitational Trinidad and
    # Tobago published its Top 4 as two tables of a single match each, and
    # reading only the first gave a Top 4 with one match in it -- which is not
    # a bracket, so the event was rejected and left the archive.
    #
    # A later table continues this one when it repeats the same header, and
    # only then. Pages carry other tables -- a deck breakdown, a prize list --
    # and those have headers of their own, so they stay out rather than having
    # their rows read as pairings.
    #
    # And a table with no header of its own continues it when its own rows say
    # what they are. The 2017 South America WCQ publishes its Top 8 as four
    # tables of one match each, none of them headed:
    #
    #   Rodrigues de Souza, Rafael Jose (Zoodiac) vs Rego Bastos, Daniel Aires
    #   Magalhaes Lima, Andre Felipe (True Draco) vs Lopes de Aguiar, Renato
    #
    # Reading only the first gave a Top 8 with one match in it, which is not a
    # bracket, and the event was refused.
    #
    # Only where the row carries a "vs." of its own. That is the one shape a
    # headerless row states outright; a ranked one could be standings, a prize
    # list or a deck breakdown, and merging those on a guess would put rows
    # into a table that never claimed them.
    for rows in tables[1:]:
        if rows[0] == header:
            body += rows[1:]
        elif (made := _infer_header(rows[0])) == header and "vs." in header:
            body += rows
    kind = _classify_table(header)
    out: list[dict[str, Any]] = []

    if kind == "standings":
        # Decided for the table, not row by row. A Team YCS publishes one row
        # per team with the members inside it -- "Road of the King: Yacine S.,
        # Francisco O., Patrick H." -- and no ordinary entrant's name has a
        # colon in it. Taken row by row, one oddly punctuated name would be read
        # as a team of one.
        entered = [r[1] for r in body if len(r) >= 2 and r[0].isdigit()]
        teams = bool(entered) and sum(":" in n for n in entered) > len(entered) / 2

        for r in body:
            if len(r) < 2 or not r[0].isdigit():
                continue
            if teams:
                out.append({"rank": int(r[0]), **split_team(r[1]),
                            "region": None,
                            "points": int(r[2]) if len(r) > 2 and r[2].isdigit() else None,
                            "status": None, "statusRound": None})
                continue
            # The same reading the pairings get. A standings cell carries
            # the same annotations -- "Quispe Llanco, Ariel (Bolivia) -
            # Burning Abyss Phantom Knights" -- and reading it without them
            # left the deck inside the name.
            #
            # That is not only a bad label. reconcile_names counts the words
            # of a name, so the spelling carrying a deck is the longer one and
            # wins: the 2016 South America WCQ folded eight clean names into
            # their mangled spellings and rewrote them across all eleven
            # rounds, which is how its champion reached the winners page as
            # "Joaquin - Dracoslayer Performapals Rinaldi Petroni".
            cell, spelt, _ = read_annotation(r[1])
            name, region = strip_region(cell)
            region = region or spelt
            status, status_round = split_status(r[1])
            out.append({
                "rank": int(r[0]),
                "name": normalise_name(name),
                "region": region,
                # Absent, not zero. A table with no points column says nothing
                # about anyone's points, and the record is derived from the
                # pairings regardless.
                "points": int(r[2]) if len(r) > 2 and r[2].isdigit() else None,
                "status": status,
                "statusRound": status_round,
            })

    elif kind == "pairings":
        # Each side is read by position within its own half, because the halves
        # differ between layouts. Where there is a 'vs.' column it separates
        # them and belongs to neither; the team Swiss layout has none --
        # Table | Team 1 | Team 2 -- so the columns after the table number
        # divide evenly instead. Treating the missing separator as a column
        # swallowed the left side entirely and left every match a name short.
        # Whether the first column is the table number. Most layouts head it
        # "Table" or leave it blank; some have no such column at all and open
        # straight on the first Duelist, and reading their opening name as a
        # table number dropped it from the match.
        numbered = bool(header) and ("table" in header[0].lower()
                                     or not header[0].strip())
        start = 1 if numbered else 0

        # What divides the two sides. A "vs." column where there is one, and
        # otherwise a column headed nothing at all, which is the same thing
        # drawn rather than written -- "Table | Player 1 |  | Player 2".
        # Splitting the remaining columns evenly instead put the blank on the
        # right and cost that side its deck.
        vs_at = next((i for i, h in enumerate(header)
                      if h.strip().lower() in ("vs.", "vs")), None)
        if vs_at is None:
            vs_at = next((i for i, h in enumerate(header)
                          if i > start and not h.strip()), None)
        if vs_at is None:
            split, skip = start + (len(header) - start) // 2, 0
        else:
            split, skip = vs_at, 1
        cut = lambda row: (row[start:split], row[split + skip:])
        left, right = cut(header)
        deck_at = next((i for i, h in enumerate(left) if _DECK_COL.search(h)), None)

        def side(cells: list[str], heads: list[str] = ()) -> dict[str, Any]:
            if deck_at is not None:
                deck = cells[deck_at] if deck_at < len(cells) else None
                # Everything else on this side is the name, minus the columns
                # that are about the Duelist without being part of it.
                keepable = [i for i in range(len(cells))
                            if i != deck_at
                            and not (i < len(heads) and _ABOUT_NOT_NAMED.search(heads[i]))]
                parts = [cells[i] for i in keepable] or [cells[0]]
                heads = [heads[i] for i in keepable if i < len(heads)]
            else:
                parts, deck = cells, None
            # A column that names a result is not part of a Duelist's name.
            # The 2013 World Championship writes its rounds
            # "Table | Player 1 | VS. | Player 2 | | Winner", and everything
            # after the divider was read as Player 2 -- so the winner's name
            # was appended to their opponent's, giving "Weerapun Sergio
            # Soldani Suebyoubol" for a Duelist called Weerapun Suebyoubol.
            keep = [c for i, c in enumerate(parts)
                    if not (i < len(heads) and _NOT_A_NAME.match(heads[i].strip()))]
            parts = keep if keep else parts
            # Per cell: the code sits on whichever cell carried it, which for
            # a first/last split is the first, not the joined string.
            cleaned, region, team = [], None, None
            for c in parts:
                text = _text(c)
                # A Team YCS that does not announce the team in a row of its
                # own writes it on every Duelist instead:
                #
                #   La Revolucion: Lozano, Connor Joseph
                #
                # The colon is the team's and the comma is the Duelist's, and
                # normalise_name partitions on the comma -- so the team ended
                # up in the middle of the name: "Connor Joseph La Revolucion:
                # Lozano". 32,791 names across eleven events read that way.
                #
                # Only where a comma follows, which is the shape the blog
                # writes. A team's own name can hold a colon -- "Beetron 2:
                # Electric Boogaloo", "Lift Yourself 1:58" -- and those come
                # through team_row rather than here, but the comma keeps this
                # off them whatever route they take.
                if ":" in text:
                    before, _, after = text.partition(":")
                    if before.strip() and "," in after:
                        team, text = before.strip(), after.strip()
                text, spelt, played = read_annotation(text)
                text, code = strip_region(text)
                region = region or code or spelt
                deck = deck or played
                if text:
                    cleaned.append(text)
            return {**({"team": team} if team else {}),
                    "name": normalise_name(" ".join(cleaned)),
                    "region": region, "deck": deck or None}

        # A team match is one row of this table, holding the duels played
        # inside it. Both team layouts announce one the same way -- a row whose
        # table cell is not a number, carrying two names and nothing else:
        #
        #   ['Team', 'Cuspy Way', 'We are just here']              Swiss
        #   ['', 'Ares', '', 'vs.', '3 Lil Pigs', '']              top cut
        #
        # Those rows were skipped for not starting with a number, which left
        # three duels a match with nothing saying whose they were. A singles
        # event has none of them and every row is a match of its own, exactly
        # as before.
        # The row that announces a team match, in either of the two shapes the
        # blog writes it:
        #
        #   ['Team', 'Joel White's Insurance Agents', 'Team', 'Slifer Slackers']
        #   ['Team', 'Joel White's Insurance Agents', 'vs.', 'Robert McNett']
        #
        # Neither is as wide as the table it sits in -- TEAM YCS Las Vegas
        # heads its Top 8 with five columns and announces its matches with
        # four -- so the length check dropped them, every duel became a match
        # of its own, and the round reported three Duelists a side where the
        # Top 16 reported one. The event was rejected for disagreeing with
        # itself.
        def unnumbered_duel(cells) -> bool:
            """A duel the blog forgot to number.

            The 2017 South America WCQ leaves the table cell of its second Top
            4 match empty:

                1 | Lopes de Aguiar, Renato   | vs | Rodrigues de Souza, Rafael
                  | Delgado Chavarry, Santino | vs | Asfour Al Jaubri, Kanaan

            Read as the announcement of a team match, both Duelists became
            teams, the Top 4 held two players who never played in the Top 8,
            and the event was refused.

            A row as wide as the header, with the separator in the header's own
            column and nothing else in it blank, is the shape of a duel
            whatever its first cell says. The team layouts fail that last part:
            TEAM YCS heads a match ['', 'Ares', '', 'vs.', '3 Lil Pigs', ''],
            which is full width and separated in the right place but empty in
            three cells that a duel would fill.
            """
            if vs_at is None or len(cells) != len(header):
                return False
            # Forgotten, not filled in with something else. A team match
            # announces itself in that very cell -- ['Team', 'Alpha Squad',
            # 'vs.', 'Beta Crew'] -- and is a match rather than a duel.
            if start and cells[0].strip():
                return False
            if cells[vs_at].strip().lower() not in _VS_CELL:
                return False
            return all(c.strip() for i, c in enumerate(cells)
                       if i >= start and i != vs_at)

        def team_row(cells):
            named = [c for c in cells
                     if c.strip().lower() not in ("team", "vs.", "vs", "")]
            return named if len(named) == 2 else None

        match = None
        for r in body:
            # A row that does not open with a table number is either the
            # announcement of a team match or nothing this can read. It is
            # never a duel, and reading its first cell as a number is how a
            # blank one crashed the whole event.
            if numbered and (not r or not r[0].strip().isdigit()) and not unnumbered_duel(r):
                pair = team_row(r)
                if pair:
                    # A team's name is not a Duelist's, and must not be read
                    # like one. normalise_name strips a two- or three-letter
                    # all-caps token as a region code -- right for "Philip
                    # DEU", wrong for "Team PWP", which came back as a team
                    # called "Team" from a region called "PWP". TEAM YCS Las
                    # Vegas round 6 pairs "Team PWP" with "Team VCG", so both
                    # sides became "Team" and the match was a team playing
                    # itself, which is not a pairing and took the event out of
                    # the archive.
                    a, b = ({"name": _text(pair[0]).strip(), "region": None, "deck": None},
                            {"name": _text(pair[1]).strip(), "region": None, "deck": None})
                    match = {"table": None, "a": a, "b": b, "duels": []}
                    out.append(match)
                continue
            if len(r) != len(header):
                continue
            lcells, rcells = cut(r)
            # A table with no number column has no team rows to find either:
            # every row is a match, and there is nothing to read a number from.
            if not numbered:
                a, b = side(lcells, left), side(rcells, right)
                if a["name"] and b["name"]:
                    out.append({"table": None, "a": a, "b": b})
                continue
            duel = {"table": int(r[0]) if r[0].strip().isdigit() else None,
                    "a": side(lcells, left), "b": side(rcells, right)}
            if match is None:
                # No row announced a match, but the sides may still say which
                # teams they played for. TEAM YCS Las Vegas 2020 writes its
                # cut with the team on every Duelist and no announcement at
                # all:
                #
                #   1 | Gonna Finish That: Couch, Dominic  | vs. | Dino DNA: Gamrat, Griffin
                #   2 | Gonna Finish That: Silverman, ...  | vs. | Dino DNA: Cornell, Brendan
                #   3 | Gonna Finish That: Page, Scott     | vs. | Dino DNA: Nappi, Ross
                #
                # Those three rows are one match. Read as three, the Top 4 of
                # four teams held twenty-four Duelists and no team, so the
                # event had no roster and could name no champion.
                #
                # Consecutive rows only, and only while both teams hold: the
                # next pair of teams starts the next match.
                # Not where both sides carry the same name. TEAM YCS Las
                # Vegas 2020 has two teams registered as "Brick Squad" and
                # pairs them against each other, and a team does not play
                # itself -- so the prefix is not evidence of a match here and
                # the rows stand as the duels they are.
                teams = (duel["a"].get("team"), duel["b"].get("team"))
                if all(teams) and teams[0] != teams[1]:
                    if not out or out[-1].get("teams") != teams:
                        out.append({"table": duel["table"], "teams": teams,
                                    "a": {"name": teams[0], "region": None, "deck": None},
                                    "b": {"name": teams[1], "region": None, "deck": None},
                                    "duels": []})
                    out[-1]["duels"].append(duel)
                    continue
                out.append(duel)                    # a singles event
                continue
            match["duels"].append(duel)
            if match["table"] is None:              # the match is at its first table
                match["table"] = duel["table"]

        # A round where every table pairs a Duelist against themselves is a
        # column the blog copied, not a round that was played. YCS Denver's
        # round 6 is published with Player 2 holding Player 1's name in all
        # 247 rows:
        #
        #   1 | Brown, Quinton DeVante Marvin | vs. | Brown, Quinton DeVante Marvin
        #   2 | Flynn, Andrey Asiev           | vs. | Flynn, Andrey Asiev
        #
        # There is no opponent in that post to read, so the pairings are
        # dropped and the round keeps whatever else it has -- 244 rounds in
        # the archive already stand with no pairings. Reading them as written
        # took the whole 42-post event out of the archive.
        #
        # Every row, not some: one self-paired row is a typo in a round that
        # was really played, and that still stops the event, as it should.
        if out and all(_itself(d) for d in out):
            out = []

    return Table(kind=kind, columns=header, rows=out)


def _itself(duel: dict) -> bool:
    """Both sides of one row naming the same Duelist."""
    def named(side):
        return side["name"] if isinstance(side, dict) else side
    return bool(named(duel.get("a")) and named(duel["a"]) == named(duel.get("b")))


# Pairings written as sentences rather than as a table. Konami does this often
# enough to matter -- the 2023 North America Remote Duel YCS published its Top 8
# and Top 4 this way, and the archive simply had no cut for that event.
#
#   Table 1: Jordan Andrew Farris (Floowandereeze) vs. Liam Mac Oscair (Mathmech)
#   Table 1: Hideki Kawai (Japan - 9 points - Frog Monarch) vs. Kei Kuwano (...)
#   Table 1: Medina Hernandez, Omar (HEROES) vs. Franco Flores, Braulio (...) Braulio wins 2-0
#
# The parenthesis carries whatever the writer had: a deck, or a country and a
# points total and a deck. The deck is the last of them, because that is the
# part every one of these has.
# The text is cut at each "Table N:" and each piece read on its own, rather than
# matched in one pass. A row where the separator is missing would otherwise run
# on into the next table and swallow it: one row of the 2013 Central America Top
# 16 reads "...(Constellars) vs.Gallegos Lomeli..." with no space, and the Top 16
# came out with seven matches instead of eight.
# The colon is optional. Eight posts write "Table 1 De Obaldia Soza, ..."
# with nothing between the number and the first name.
_PROSE_SPLIT = re.compile(r"Table\s*(\d+)\s*:?\s", re.I)
# "vs." with the space after it optional, for that same row.
_VS = re.compile(r"\s*\bvs(?:\.\s*|\s+)", re.I)
_PARENS = re.compile(r"^(.*?)\s*\(([^)]*)\)")

# What a Duelist is registered as, which the coverage puts in the same bracket
# a deck goes in: YCS Pasadena writes "Wong, Vincent Man Kith CA (0101299430)"
# and the reading that finds "(Metalfoes)" found the COSSY number instead. It
# is on the page as a Duelist's identifier and it is not what they played --
# 1,344 cells across six events had one of these as their deck, and the site
# showed it as one.
#
# Any run of digits, not only the ten-digit ones: no archetype in this game is
# a number, so a bracket holding nothing else says nothing about the deck.
_REGISTRATION = re.compile(r"^\d+$")


def _deck_or_none(text: str | None) -> str | None:
    """A deck, unless what was found is a number."""
    text = (text or "").strip()
    return None if not text or _REGISTRATION.match(text) else text


# "De Obaldia Soza, Galileo Mauricio from Panama (ABC)" -- the country written
# out, in the middle of the side rather than in the bracket.
# A country written out after the name, which South American coverage does:
# "Lopes de Aguiar, Renato from Brazil". Read out of prose since #112 and never
# out of a table cell, where strip_region -- which knows only two- and
# three-letter codes -- let it through. normalise_name then swapped the comma
# and left the country in the middle of the name: "Renato from Brazil Lopes de
# Aguiar", 846 times across a dozen events.
#
# A Duelist written both ways counts as two people in their own event's
# records, and the mangled spelling is the longer one, so it wins the fold.
#
# The word "from" is what makes this safe. #113 warned that a rule taking
# whatever follows a dash cuts a real surname in half -- "Jesus Correa -
# Moreira" is one name -- and nothing here reads a dash.
_FROM_COUNTRY = re.compile(r"\s+from\s+([A-Z][^,()]*?)\s*(?=$|[,(])")


def strip_country(name: str) -> tuple[str, str | None]:
    """'Renato from Brazil' -> ('Renato', 'Brazil'). Leaves the rest alone."""
    if not (m := _FROM_COUNTRY.search(name)):
        return name, None
    return (name[:m.start()] + name[m.end():]).strip(), m.group(1).strip()

# A round written as a chain with no "Table N" to cut it at:
#
#   Here are the Top 4 Pairings! Aaron Furman (Metalfoes) vs. Chandler
#   Sanford (Majespecter) Kamal Crooks (Blue-Eyes) vs. Jose Uriel Diaz (Kozmo)
#
# Nothing separates one pairing from the next except the bracket ending the
# side before it, so the bracket is what the pairs are found by. Each side is
# bounded: it cannot run past a bracket, and it cannot be longer than a name
# and a deck.
_PROSE_PAIR = re.compile(
    r"([^()]{2,90}\([^)]*\))\s*(?:vs\.?|versus)\s+([^()]{2,90}\([^)]*\))", re.I)

# What a post says before it starts naming anybody. Cut at the last of these,
# so "Here are the Top 4 Pairings!" does not become part of the first name.
#
# A full stop counts too -- "Here are the semifinal matchups. Rolando ..." --
# but only after a whole word. An initial and a suffix both end in a stop, and
# cutting at those would take "Antonio Nogueira Jr." down to nothing and lose
# the post rather than the preamble.
_PREAMBLE = re.compile(r"^.*(?:[:!?]|(?<![A-Z])(?<!\bJr)(?<!\bSr)(?<!\bDr)\w{4,}\.)\s+", re.S)

# A deck is a deck's length. Where a piece trails a result sentence -- "Parra,
# Filiberto Octavio - Geargia advances to Top 8. Orea had represented Central
# America in 2012" -- what follows the dash is a sentence, not an archetype,
# and the name is worth keeping without it.
def _plausible_deck(said: str) -> str | None:
    said = said.strip()
    return said if said and "," not in said and len(said.split()) <= 5 else None


def _prose_side(text: str) -> dict[str, Any] | None:
    """One Duelist out of "Name (Country - points - Deck)", and what they played."""
    text = text.strip()
    if m := _PARENS.match(text):
        # Whatever else is in there, the deck is the last part: "(HEROES)" is a
        # deck, and so is the end of "(Japan - 9 points - Frog Monarch)".
        deck = _deck_or_none(re.split(r"\s+[-\u2013\u2014]\s+", m.group(2))[-1])
        said = m.group(1)
    else:
        # No bracket. The deck can be written after a dash instead -- the 2014
        # Central America WCQ writes "Gonzalez Orea, Alvaro - Madolche Hand" --
        # and a piece of prose here is bounded by "Table N" on one side and
        # "vs." on the other, so what follows the dash is the deck rather than
        # the second half of a surname.
        #
        # Without one of the two, this side is not read: everything to the end
        # of the piece would be the name, and a result sentence often trails
        # it with nothing to say where the name stopped.
        said, _, tail = text.partition(" \u2013 ")
        if not tail:
            said, _, tail = text.partition(" - ")
        if not tail:
            return None
        deck = _plausible_deck(tail)
    said = _FROM_COUNTRY.sub("", said)
    # "Farfan Soto, Sergio Mauricio - Bolivia (Pendulum Magician)" -- the
    # country after a dash, with the bracket holding the deck. The same shape
    # a table cell carries, and the same reading: where a bracket says the
    # side is annotated, what follows the dash is not part of the name.
    if deck and (m := _SPELT_REGION.search(said)):
        said = said[:m.start()]
    name = normalise_name(said)
    return {"name": name, "region": None, "deck": deck} if name else None


# A round written as a sentence about the Duelists rather than as a list of
# them. Every YCS final since 2022 is published this way:
#
#   Michael Tamez and his Floowandereeze Deck is facing off against
#   Christopher LeBlanc and his Spright Tearlaments Deck
#   Ryan Yu will be using his Sky Striker Deck to Duel against Landon Oliver
#   and his Fire King Snake-Eye Azamina Deck
#   Chase Robert Cunningham versus Noah Reid Greene
#
# Worth reading rather than dropping: these are Finals, and an event whose
# Final is missing has no two Duelists for a winner post to be recognised
# among -- which is exactly how YCS Niagara Falls 2022 had no champion.
_DUEL_AGAINST = re.compile(r"\s+(?:up\s+)?(?:against|versus)\s+", re.I)
# "and his Floowandereeze Deck", "using her Sky Striker Deck". The deck is
# what sits between the pronoun and the word Deck.
_THEIR_DECK = re.compile(
    r"\s+(?:and|with|using|is using|are using|will be using)\s+"
    r"(?:his|her|their)\s+(.+)\s+Decks?\b", re.I)
# "At Table 1, Ryan Arthur Levine is using..." -- YCS Toronto writes its Top 4
# as one sentence a table.
_AT_TABLE = re.compile(r"^\s*at\s+table\s+(\d+)\s*,\s*", re.I)


# Particles that sit inside a name without a capital of their own.
_PARTICLES = {"de", "del", "la", "las", "los", "van", "von", "der", "den",
              "da", "das", "dos", "du", "di", "el", "al", "bin", "ibn", "y"}


def _looks_like_a_name(said: str) -> bool:
    """Whether this is a Duelist's name rather than a piece of a sentence.

    The sentence reader hands back whatever sits in front of a verb, and on a
    post that is not about two Duelists that is a clause. The 2016 South
    America WCQ writes its Top 16 as a dash-delimited chain with "Versus"
    between the halves, and reading it as a sentence gave a Duelist called
    "With just sixteen Duelists now remaining in the WCQ let's find out who's
    left" playing one called "in the Top 16" -- a Top 16 of two matches, which
    took the event out of the archive.

    A name is a few words, each of them capitalised or a particle, and none of
    them punctuation the blog uses to separate things.
    """
    words = said.split()
    if not 2 <= len(words) <= 6:
        return False
    if any(c in said for c in ";:\u2013\u2014|") or any(ch.isdigit() for ch in said):
        return False
    return all(w[:1].isupper() or w.lower().strip(".,") in _PARTICLES for w in words)


def _sentence_side(text: str, lead: bool) -> dict[str, Any] | None:
    """One Duelist out of a sentence about them, and the deck it names."""
    deck = None
    if m := _THEIR_DECK.search(text):
        deck, text = m.group(1).strip(), text[:m.start()]
    else:
        # No deck named on this side. Everything up to the first verb is the
        # name -- "Noah Reid Greene" stands alone, but "Bohdan Temnyk and his
        # ... Deck" would have been caught above.
        text = re.split(r"\s+(?:is|are|will|and)\b", text, maxsplit=1)[0]
    if lead:
        text = _AT_TABLE.sub("", _PREAMBLE.sub("", text))
    # A conjunction the sentence left behind. YCS Toronto writes "Michael
    # Kyle Walters and and his Burning Abyss Phantom Knight Deck", and the
    # doubled word puts an "and" on the end of the name.
    text = re.sub(r"\s+(?:and|with|&)$", "", text.strip(" ,.!?"))
    name = normalise_name(text)
    return ({"name": name, "region": None, "deck": deck}
            if name and _looks_like_a_name(name) else None)


def parse_prose_duels(text: str) -> list[dict[str, Any]]:
    """Rounds written as sentences: one match a sentence, or [].

    Same all-or-nothing as the pairings reader, and for the same reason: a
    round short a match is a wrong round, not a small one.
    """
    out, said = [], 0
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if not (sep := _DUEL_AGAINST.search(sentence)):
            continue
        said += 1
        a = _sentence_side(sentence[:sep.start()], lead=True)
        b = _sentence_side(sentence[sep.end():], lead=False)
        if a and b:
            out.append({"table": None, "a": a, "b": b})
    return out if said and len(out) == said else []


def parse_prose_pairings(text: str) -> list[dict[str, Any]]:
    """Pairings read out of prose, or [] where the shape is not there.

    Konami writes a round this way often enough to matter -- the 2023 North
    America Remote Duel YCS published its Top 8 and Top 4 as sentences, and the
    archive simply had no cut for that event.

        Table 1: Jordan Farris (Floowandereeze) vs. Liam Mac Oscair (Mathmech)
        Table 1: Hideki Kawai (Japan - 9 points - Frog Monarch) vs. Kei Kuwano (...)
        Table 1: Medina Hernandez, Omar (HEROES) vs. Franco Flores, Braulio (...) Braulio wins 2-0

    Every table that names two Duelists, or none of them. A bracket short a
    match is not a smaller bracket, it is a wrong one, and the round it lands in
    would be measured against a field that never played it. Where a piece will
    not parse, the post is left to be dropped exactly as it was before.

    A piece with no "vs" in it is not one of those. It is a bye -- "Table 16:
    Jonathon Castillo Gomez (Blue-Eyes) - BYE" -- which is a real thing to
    publish and nothing to pair.
    """
    if not _PROSE_SPLIT.search(text):
        # No "Table N" anywhere. Read it as a chain instead, and take it only
        # if every pairing in it reads -- the same all-or-nothing this has
        # always applied, for the same reason.
        found = _PROSE_PAIR.findall(text)
        chain = [{"table": None, "a": a, "b": b}
                 for left, right in found
                 if (a := _prose_side(_PREAMBLE.sub("", left))) and (b := _prose_side(right))]
        return chain if found and len(chain) == len(found) else []

    pieces = _PROSE_SPLIT.split(text)
    out: list[dict[str, Any]] = []
    pairings = 0
    for number, piece in zip(pieces[1::2], pieces[2::2]):
        sep = _VS.search(piece)
        if not sep:
            continue
        pairings += 1
        a = _prose_side(piece[:sep.start()])
        b = _prose_side(piece[sep.end():])
        if a and b:
            out.append({"table": int(number), "a": a, "b": b})
    return out if len(out) == pairings else []


def impossible_bracket(rnd) -> bool:
    """A "Top N" that no bracket could produce.

    A cut halves the field, so N is a power of two -- 4, 8, 16, 32, 64 and 256
    are every value the archive holds, across 527 cut rounds. Ten is not one,
    and a round labelled with it was never a round of ten.
    """
    if not isinstance(rnd, str) or not (m := re.fullmatch(r"Top (\d+)", rnd)):
        return False
    n = int(m.group(1))
    return n < 2 or bool(n & (n - 1))


def parse_post(doc: str, url: str = "") -> Post:
    """Read one post.

    The kind is taken from the title and the URL, and where those disagree with
    the table on the page, the table wins. Konami published YCS Anaheim's
    standings under the slug ycs-anaheim-round-12-pairings -- the page is headed
    "YCS Anaheim: Standings After Round 11" and holds a standings table, and
    only the slug says otherwise. Read as pairings it was a post whose every
    row was missing the columns pairings have, which is how a whole backfill
    came down.

    Narrow on purpose. Only between pairings and standings, only when both the
    text and the table are confident, and only when they contradict each other:
    a news post quoting a table is still news. The round is read afterwards,
    because "Final Standings" means something different once the post is known
    to be standings.
    """
    title = page_title(doc)
    basis = f"{title} {url}"
    table = parse_table(doc)
    kind = detect_kind(basis)
    if table is None and kind == "pairings":
        # No table on the page at all. Before giving up on the post, read it as
        # prose: the build drops a pairings post carrying no table, and for
        # some events that is the whole of the cut.
        said = lead(doc, PROSE_CHARS)
        # The list first, then the sentence. A post that lists its pairings is
        # the commoner thing and the surer read; a sentence is what is left.
        if rows := (parse_prose_pairings(said) or parse_prose_duels(said)):
            table = Table(kind="pairings", columns=["Table", "Duelist", "vs.", "Duelist"],
                          rows=rows)
    if (table and kind in ("pairings", "standings")
            and table.kind in ("pairings", "standings") and table.kind != kind):
        kind = table.kind
    # The title names the round, and the slug only fills in when it does not.
    # Konami types slugs by hand and sometimes types them wrong: the 2017 South
    # America WCQ published
    #
    #   "South America WCQ: Pairings for Round 3"
    #   south-america-wcq-pairings-for-top-3
    #
    # and read together the slug won, so 137 matches of Swiss became a Top 3.
    # Nothing about a bracket of three is possible, and the event was refused.
    #
    # The same reasoning parse_post already applies to the kind, where the slug
    # said pairings and the page said standings: what the page calls itself
    # beats what its address does.
    rnd = detect_round(title, kind) or detect_round(basis, kind)
    # And a cut round of ten is not a cut round. Brackets halve, so every one
    # of the archive's 527 is a power of two, and the 2016 North America WCQ
    # heads a post "Pairings: Top 10" over 128 matches -- 256 Duelists, the
    # field that came back for day two. Its own first sentence says what it is:
    #
    #   Here are the Pairings for Round 10.
    #
    # So the post is asked. A heading is one line someone typed and can carry a
    # typo; the sentence under it is another chance to be right, and it is only
    # consulted when the heading has said something impossible.
    if impossible_bracket(rnd):
        rnd = detect_round(lead(doc, PROSE_CHARS), kind) or rnd
    return Post(
        title=title,
        kind=kind,
        fmt=detect_format(basis),
        round=rnd,
        table=table,
        # Only for the posts that might name a champion: the ones that announce
        # a winner, and the final's own feature match, which says who took it
        # in a sentence somewhere in the middle of the match it describes.
        # Every other kind is read from its table, and keeping their prose
        # would be so much weight carried through the build for nothing.
        lead=(lead(doc) if kind == "result"
              else lead(doc, MATCH_CHARS) if kind == "feature" and rnd == "Final"
              else ""),
    )
