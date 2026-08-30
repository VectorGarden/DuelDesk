#!/usr/bin/env python3
"""What is coming, from Konami's own events listing.

The blog covers a tournament while it happens and says nothing before it. The
schedule lives somewhere else entirely -- yugioh-card.com/en/events/ -- so the
site could say what it had covered and never what was next.

That page is server-rendered WordPress and lists each event as a name, a place
and a date range, which is all this needs. It is read every few months rather
than every few minutes: a schedule of tournaments months away does not change
between one hour and the next, and the whole point of the archive's cadence
rules is not to ask more often than the answer changes.

Whether an event has already happened is decided by the page that renders this,
not here. A file written in October and read in December would otherwise call a
November tournament upcoming, and a date is a fact about the event while
"upcoming" is a fact about when you are looking.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date

BASE = "https://www.yugioh-card.com"
EVENTS_URL = BASE + "/en/events/"

# One event, as the listing writes it:
#
#     <li><h6><a href="/en/events-item/2026-ycs-houston/">
#         <p>Yu-Gi-Oh! Championship Series Houston, Texas 2026</p>
#         <p class="small">Houston, TX</p>
#         <p class="small">10/16/2026 - 10/18/2026</p>
#     </a></h6></li>
_ITEM = re.compile(r"<li>\s*<h6>\s*<a\s+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TAGS = re.compile(r"<[^>]+>")

_RANGE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
_STARTS = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

# The listing writes the series out in full and the site does not. "YCS Houston"
# is what this tournament is called here, which is the reader's own name for it
# and the one the archive will file its coverage under.
_SERIES = "Yu-Gi-Oh! Championship Series"


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", fragment))).strip()


def _dates(text: str) -> tuple[str | None, str | None]:
    """(start, end) as ISO dates. An open-ended run has no end.

    Two forms appear: a range, and "starts on 09/27/2025" for the promotions
    that run until further notice. The second is a start with no end rather
    than a one-day event, and saying so is the difference between a promotion
    that is still on and one the page would call long finished.
    """
    if m := _RANGE.search(text):
        a, b, c, d, e, f = m.groups()
        return f"{c}-{a}-{b}", f"{f}-{d}-{e}"
    if m := _STARTS.search(text):
        a, b, c = m.groups()
        return f"{c}-{a}-{b}", None
    return None, None


def event_name(listed: str, where: str) -> str:
    """"YCS Houston" for "Yu-Gi-Oh! Championship Series Houston, Texas 2026".

    The listing's name carries the series written out, the state and the year,
    and the site shows none of those: the year is in the date beside it and the
    state is in the location beside that. What is left is the city, which is
    what anyone calls the tournament.

    The city is read from the location rather than cut out of the name, because
    the location says where the comma goes -- "Houston, TX" -- and the name does
    not always agree with itself about that.
    """
    name = " ".join(listed.split())
    if _SERIES not in name:
        # Anything else is left as it was written. New York Comic Con is not a
        # YCS and guessing at its shape would only damage it.
        return name.replace(_SERIES, "YCS")
    rest = name.replace(_SERIES, "").strip()
    if where and (city := where.split(",")[0].strip()) and city.lower() in rest.lower():
        return f"YCS {city}"
    # A series event with no city to find -- the Remote Duel ones are named for
    # a region and hosted on Discord -- keeps its whole name, abbreviated.
    return re.sub(r"\s+", " ", name.replace(_SERIES, "YCS")).strip()


def parse_events(page: str) -> list[dict]:
    """Every event the listing names, soonest first.

    Entries with no date at all are dropped: the listing carries a few standing
    links -- policies, store locators -- in the same markup, and an event that
    cannot say when it is is not something to put in front of a reader.
    """
    out = []
    for m in _ITEM.finditer(page):
        href, inner = m.group(1), m.group(2)
        parts = [_text(p) for p in _PARA.findall(inner)]
        parts = [p for p in parts if p]
        if not parts:
            continue
        listed, where = parts[0], (parts[1] if len(parts) > 2 else "")
        starts, ends = _dates(parts[-1]) if len(parts) > 1 else (None, None)
        if not starts:
            continue
        out.append({
            "event": event_name(listed, where),
            "listed": listed,
            "location": where or None,
            "starts": starts,
            "ends": ends,
            "url": href if href.startswith("http") else BASE + href,
        })
    out.sort(key=lambda e: (e["starts"], e["event"]))
    return out


def build(page: str, fetched: date) -> dict:
    """The file the site reads.

    The fetch date is written into it because this is read every few months:
    without it a reader cannot tell a quiet schedule from a stale one, and
    neither can anyone debugging it.
    """
    return {"fetched": fetched.isoformat(), "events": parse_events(page)}


def main() -> int:
    import argparse
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from fetch import Fetcher                             # noqa: E402

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="upcoming.json")
    ap.add_argument("--cache", default=".scrape-state/cache")
    args = ap.parse_args()

    f = Fetcher(cache_dir=args.cache)
    data = build(f.get(EVENTS_URL, refresh=True), date.today())
    Path(args.out).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['events'])} upcoming events -> {args.out}")
    for e in data["events"]:
        end = f" – {e['ends']}" if e["ends"] else ""
        print(f"   {e['starts']}{end}  {e['event']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
