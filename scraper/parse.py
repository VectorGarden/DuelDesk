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

_TAG = re.compile(r"<[^>]+>")
_TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


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

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.table is None:
            d.pop("table")
        return d


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
    if "pairings" in low:
        return "pairings"
    if "standings" in low:
        return "standings"
    if "feature match" in low:
        return "feature"
    if re.search(r"\bwinner\b|\bchampion\b|\bcongratulations\b", low):
        return "result"
    return "news"


def _classify_table(header: list[str]) -> str:
    low = [h.lower() for h in header]
    if "rank" in low and any("point" in h for h in low):
        return "standings"
    if "table" in low and any(h.strip() == "vs." or h.strip() == "vs" for h in low):
        return "pairings"
    return "unknown"


def parse_table(doc: str) -> Table | None:
    m = _TABLE.search(doc)
    if not m:
        return None
    rows = [[_text(c) for c in _CELL.findall(r)] for r in _ROW.findall(m.group(0))]
    rows = [r for r in rows if r]
    if not rows:
        return None

    header, body = rows[0], rows[1:]
    kind = _classify_table(header)
    out: list[dict[str, Any]] = []

    if kind == "standings":
        for r in body:
            if len(r) < 3 or not r[0].isdigit():
                continue
            name, region = strip_region(r[1])
            out.append({
                "rank": int(r[0]),
                "name": normalise_name(name),
                "region": region,
                "points": int(r[2]) if r[2].isdigit() else None,
            })

    elif kind == "pairings":
        # Split the header on the 'vs.' column so each side is read by position
        # within its own half -- the halves differ between layouts.
        try:
            pivot = next(i for i, h in enumerate(header) if h.strip().lower() in ("vs.", "vs"))
        except StopIteration:
            pivot = len(header) // 2
        left, right = header[1:pivot], header[pivot + 1:]
        decks = any("deck" in h.lower() for h in left)

        for r in body:
            if len(r) != len(header) or not r[0].isdigit():
                continue
            lcells, rcells = r[1:pivot], r[pivot + 1:]

            def side(cells: list[str], cols: list[str]) -> dict[str, Any]:
                if decks:
                    parts, deck = [cells[0]], (cells[1] if len(cells) > 1 else None)
                else:
                    parts, deck = cells, None
                # Per cell: the code sits on whichever cell carried it, which for
                # a first/last split is the first, not the joined string.
                cleaned, region = [], None
                for c in parts:
                    text, code = strip_region(_text(c))
                    region = region or code
                    if text:
                        cleaned.append(text)
                return {"name": normalise_name(" ".join(cleaned)),
                        "region": region, "deck": deck or None}

            out.append({"table": int(r[0]), "a": side(lcells, left), "b": side(rcells, right)})

    return Table(kind=kind, columns=header, rows=out)


def parse_post(doc: str, url: str = "") -> Post:
    title = page_title(doc)
    basis = f"{title} {url}"
    kind = detect_kind(basis)
    return Post(
        title=title,
        kind=kind,
        fmt=detect_format(basis),
        round=detect_round(basis, kind),
        table=parse_table(doc),
    )
