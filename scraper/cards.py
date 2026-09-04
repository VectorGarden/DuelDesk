"""What the cards the coverage names actually do.

A feature match names cards constantly -- the archive emphasises 179,484 of
them -- and a deck list is nothing but cards. A reader who does not know what
Bystial Magnamhut does has to leave the page to find out.

Text only, deliberately. Card art was the obvious thing to want and is the
thing to leave out: the page forbids remote images, a rule this project set
itself rather than a header somebody else enforces, and art would have been the
first deliberate exception to it -- paid for either by the reader's browser
talking to a third party on every hover, or by this archive carrying thousands
of pictures. What a card does is the question being asked, and it is words.

Sharded the way the Duelists are, and for the same reason: the whole of it is
6.4MB and no reader wants 6.4MB to look at one card. Hashed into 512 files of
about 12KB, so a hover fetches one of them.

Keyed on the name with its punctuation and case taken out. The coverage writes
Maxx "C" with typographic quotes, and prose that has been through a CMS is not
where anybody should have to match an official spelling exactly. The card's
real name is stored beside its text, so what the page shows is what Konami
calls it rather than what the post happened to type.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

CARDS = "cards"
CARD_SHARDS = 512
# Every card's numbers in one file, without a word of its text.
#
# A hover wants one card and gets one shard of 13KB. An export wants a whole
# deck list, and the worst post in the archive names 642 cards across 367 of
# the 512 shards -- 4.7MB in 367 requests to answer one button. The same
# question asked of names and numbers alone is 517KB in one, and 240KB of it
# over the wire, so that is what an export asks.
NUMBERS = "ids.json"

# What is worth keeping of a card. Not the printings, the prices, the images or
# the ban list: what a card is and what it does, which is the question a reader
# hovering a name in a match report is asking.
FIELDS = ("type", "race", "attribute", "atk", "def", "level", "archetype", "desc")

# And the two numbers a deck list is made of. They are different numbering
# systems and a deck list needs both: "id" is the eight-digit passcode printed
# on the card, which is what a .ydk file and a ydke:// URI carry, and "cid" is
# Konami's own card id, which is what a tournament registration form wants
# under CardDatabaseId. 98% of the database has a cid; the rest export as a
# .ydk and not as registration JSON.
IDS = ("id", "cid")

def normalise(name: str) -> str:
    """A card's name as something two spellings of it can both be looked up by.

    Letters and digits only, which is what makes the coverage's spelling and
    the database's the same question. Maxx "C" is written with the curly
    quotes a CMS invents and with the ones a keyboard has, and an en dash and
    a hyphen are both dashes: none of it survives, so none of it has to be
    folded first.

    It costs the distinctions punctuation was carrying -- "Rai-Mei" and
    "Raimei" are two cards and one key -- which is why a key that names two
    cards names neither. See build.
    """
    return re.sub(r"[^a-z0-9]+", "",
                  unicodedata.normalize("NFKD", name).lower())


def shard_of(key: str) -> str:
    """Which of the 512 files a card's key lives in.

    The same arithmetic archive.shard_of uses for a Duelist, on the same
    reasoning: the page has to work out the file from the name without asking,
    so the rule has to be one both sides can compute.
    """
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"{int(digest[:8], 16) % CARD_SHARDS:03d}"


def build(cards: list[dict]) -> dict[str, dict]:
    """Shard name -> {key: what the card is}.

    A key that names more than one card names neither. Three of the database's
    14,520 keys do -- "Ectoplasmic Fortification" and "Ectoplasmic
    Fortification!", "H.E.R.O. Flash!" and "Hero Flash!!", "Rai-Mei" and
    "Raimei" -- and showing a reader the wrong card's text is worse than
    showing them nothing, which is the same rule the Duelist names are folded
    under.
    """
    by_key: dict[str, list[dict]] = {}
    for card in cards:
        if name := (card.get("name") or "").strip():
            by_key.setdefault(normalise(name), []).append(card)

    shards: dict[str, dict] = {}
    for key, found in by_key.items():
        if len(found) != 1:
            continue
        card = found[0]
        entry = {"name": card["name"].strip()}
        entry.update({f: card[f] for f in FIELDS
                      if card.get(f) not in (None, "")})
        if card.get("id") is not None:
            entry["id"] = card["id"]
        # Konami's own id, which the API buries under misc_info and only
        # returns when it is asked for it.
        cid = next((m.get("konami_id") for m in card.get("misc_info") or []
                    if m.get("konami_id") is not None), None)
        if cid is not None:
            entry["cid"] = cid
        shards.setdefault(shard_of(key), {})[key] = entry
    return shards


def numbers(shards: dict[str, dict]) -> dict[str, list[int]]:
    """Every card's key to its numbers: the passcode, and Konami's id where
    there is one.

    A list rather than an object because there are 14,517 of them and the
    field names would be a third of the file.
    """
    out = {}
    for held in shards.values():
        for key, card in held.items():
            if card.get("id") is None:
                continue
            out[key] = ([card["id"]] if card.get("cid") is None
                        else [card["id"], card["cid"]])
    return dict(sorted(out.items()))


def write(root: str | Path, shards: dict[str, dict]) -> int:
    """Write the card files, and remove any shard that no longer has cards."""
    out = Path(root) / CARDS
    out.mkdir(parents=True, exist_ok=True)
    kept = 0
    for name in range(CARD_SHARDS):
        path = out / f"{name:03d}.json"
        held = shards.get(f"{name:03d}")
        if not held:
            path.unlink(missing_ok=True)
            continue
        # Sorted, so a rebuild of an unchanged database writes identical bytes
        # and the repository records nothing.
        path.write_text(json.dumps(dict(sorted(held.items())),
                                   separators=(",", ":"), ensure_ascii=False) + "\n",
                        encoding="utf-8")
        kept += len(held)
    ids = numbers(shards)
    (out / NUMBERS).write_text(json.dumps(ids, separators=(",", ":"),
                                      ensure_ascii=False) + "\n", encoding="utf-8")
    return kept
