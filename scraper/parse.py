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
_ENTRY = re.compile(r"class=\"[^\"]*entry-content[^\"]*\"[^>]*>(.*?)"
                    r"(?:</div>\s*</div>|<footer)", re.S | re.I)
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


def _text(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).replace("\xa0", " ").strip()


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
    tokens = _ANNOTATION.sub(" ", name).strip().split()
    if not tokens:
        return "", None
    is_code = lambda t: bool(_REGION_TOKEN.fullmatch(t)) and t not in _NAME_SUFFIXES
    codes = [t for t in tokens if is_code(t)]
    kept = [t for t in tokens if not is_code(t)]
    if not kept:                      # the whole name looked like a code
        return " ".join(tokens), None
    return " ".join(kept), (codes[0] if codes else None)


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
    m = _ENTRY.search(doc)
    if not m:
        return ""
    body = _TABLE.sub(" ", _SCRIPTS.sub(" ", m.group(1)))
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


def detect_kind(text: str) -> str:
    low = _words(text)
    if re.search(r"\bdeck ?lists?\b|\bdeck profiles?\b|\btop \d+ deck", low):
        return "deck"
    # Singular too. The final is the one round the blog titles "Final Pairing",
    # having exactly one match to report, and requiring the plural classified it
    # as news -- which the fetch budget ranks last, so the round the whole
    # bracket builds towards was the one post never fetched.
    if re.search(r"\bpairings?\b", low):
        return "pairings"
    if "standings" in low:
        return "standings"
    if "feature match" in low:
        return "feature"
    # Plurals here too. A post announcing several winners is titled "Winners",
    # and requiring the singular filed it as news -- the same slip that hid the
    # final pairing, in the line directly below it.
    if re.search(r"\bwinners?\b|\bchampions?\b|\bcongratulations\b", low):
        return "result"
    return "news"


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
    return _DANGLING.sub("", head).strip(), region or None, deck or None


def parse_table(doc: str) -> Table | None:
    tables = []
    for m in _TABLE.finditer(doc):
        rows = [[_text(c) for c in _CELL.findall(r)] for r in _ROW.findall(m.group(0))]
        if rows := [r for r in rows if r]:
            tables.append(rows)
    if not tables:
        return None

    header, body = tables[0][0], list(tables[0][1:])
    # One round is not always one table. The 2017 UDS Invitational Trinidad and
    # Tobago published its Top 4 as two tables of a single match each, and
    # reading only the first gave a Top 4 with one match in it -- which is not
    # a bracket, so the event was rejected and left the archive.
    #
    # A later table continues this one when it repeats the same header, and
    # only then. Pages carry other tables -- a deck breakdown, a prize list --
    # and those have headers of their own, so they stay out rather than having
    # their rows read as pairings.
    for rows in tables[1:]:
        if rows[0] == header:
            body += rows[1:]
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
        left, _ = cut(header)
        decks = any("deck" in h.lower() for h in left)

        def side(cells: list[str]) -> dict[str, Any]:
            if decks:
                parts, deck = [cells[0]], (cells[1] if len(cells) > 1 else None)
            else:
                parts, deck = cells, None
            # Per cell: the code sits on whichever cell carried it, which for
            # a first/last split is the first, not the joined string.
            cleaned, region = [], None
            for c in parts:
                text, spelt, played = read_annotation(_text(c))
                text, code = strip_region(text)
                region = region or code or spelt
                deck = deck or played
                if text:
                    cleaned.append(text)
            return {"name": normalise_name(" ".join(cleaned)),
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
            if numbered and (not r or not r[0].strip().isdigit()):
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
                a, b = side(lcells), side(rcells)
                if a["name"] and b["name"]:
                    out.append({"table": None, "a": a, "b": b})
                continue
            duel = {"table": int(r[0]), "a": side(lcells), "b": side(rcells)}
            if match is None:
                out.append(duel)                    # a singles event
                continue
            match["duels"].append(duel)
            if match["table"] is None:              # the match is at its first table
                match["table"] = duel["table"]

    return Table(kind=kind, columns=header, rows=out)


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
_PROSE_SPLIT = re.compile(r"Table\s*(\d+)\s*:", re.I)
# "vs." with the space after it optional, for that same row.
_VS = re.compile(r"\s*\bvs(?:\.\s*|\s+)", re.I)
_PARENS = re.compile(r"^(.*?)\s*\(([^)]*)\)")


def _prose_side(text: str) -> dict[str, Any] | None:
    """One Duelist out of "Name (Country - points - Deck)", and what they played."""
    m = _PARENS.match(text.strip())
    if not m:
        # No parenthesis at all. Everything to the end of the piece would be the
        # name -- but a result sentence often trails it, and with no bracket to
        # say where the name stopped this side is not read.
        return None
    # Whatever else is in there, the deck is the last part: "(HEROES)" is a
    # deck, and so is the end of "(Japan - 9 points - Frog Monarch)".
    deck = re.split(r"\s+[-\u2013\u2014]\s+", m.group(2))[-1].strip() or None
    name = normalise_name(m.group(1))
    return {"name": name, "region": None, "deck": deck} if name else None


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
        if rows := parse_prose_pairings(lead(doc, PROSE_CHARS)):
            table = Table(kind="pairings", columns=["Table", "Duelist", "vs.", "Duelist"],
                          rows=rows)
    if (table and kind in ("pairings", "standings")
            and table.kind in ("pairings", "standings") and table.kind != kind):
        kind = table.kind
    rnd = detect_round(basis, kind)
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
