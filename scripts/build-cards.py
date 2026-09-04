#!/usr/bin/env python3
"""Build the card store from YGOPRODeck's database.

    python3 scripts/build-cards.py                 # fetch and write cards/
    python3 scripts/build-cards.py --from all.json # from a copy already here

Run when a set releases, not on every scrape. The coverage changes hourly
during an event and the cards do not, so this is not the scraper's job: one
request for the whole database, and 512 files out of it.

Only what a card is and what it does is kept -- see scraper/cards.py. The
printings, the prices, the images and the ban list are all in the response and
none of them is the question a reader hovering a name is asking.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import cards as cardstore                                        # noqa: E402

# misc=yes, because Konami's own card id is in misc_info and is not returned
# without it. A registration form asks for that number and a .ydk asks for the
# passcode, and they are different numbering systems.
API = "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes"


def fetch(url: str = API) -> list[dict]:
    """The whole database in one request.

    One, not one per card: the archive names eleven and a half thousand of
    them, and asking for each would be eleven and a half thousand requests to
    somebody else's server for data they publish in a single file.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "DuelDesk card store"})
    with urllib.request.urlopen(req, timeout=600) as response:
        return json.loads(response.read())["data"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="source", help="a saved copy of the API response")
    ap.add_argument("--out", default=".", help="where cards/ goes (default: here)")
    args = ap.parse_args(argv)

    if args.source:
        raw = json.loads(Path(args.source).read_text(encoding="utf-8"))
        data = raw["data"] if isinstance(raw, dict) else raw
    else:
        data = fetch()
    print(f"{len(data):,} cards in the database")

    shards = cardstore.build(data)
    kept = cardstore.write(args.out, shards)
    dropped = len(data) - kept
    print(f"Card store holds {kept:,} cards in {len(shards)} files")
    if dropped:
        # Never silent: a name two cards answer to is dropped on purpose, and
        # a run that dropped hundreds would mean the rule had gone wrong.
        print(f"{dropped} not stored -- their names are not theirs alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
