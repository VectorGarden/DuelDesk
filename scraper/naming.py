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
    """The event's name, or `fallback` if its posts do not agree on one."""
    prefixes = Counter()
    for title in titles:
        parts = _TITLE_SPLIT.split(title.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0]:
            prefixes[parts[0]] += 1
    if not prefixes:
        return fallback
    name, count = prefixes.most_common(1)[0]
    return name if count >= MIN_SHARE * len(titles) else fallback


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
