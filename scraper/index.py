#!/usr/bin/env python3
"""Build a post index from the blog's sitemap, and group posts into events.

The sitemap is the sanctioned entry point: robots.txt disallows only /wp-admin/
and publishes wp-sitemap.xml explicitly. There is no RSS feed (every /feed/ path
404s) and the WordPress REST posts endpoint returns 403, so this is the only
supported way in.

Event identity is the hard part. A post URL is either

    /{year}/{category}/{slug}/                 no event
    /{year}/{category}/{event}/{slug}/         event in the path

and the *same* event appears in both shapes -- YCS Montreal has posts under
2026-08-quebec and others directly under ycs. So the event slugs are treated as
authoritative date windows, and undated siblings are attached by date.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import date

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BASE = "https://yugiohblog.konami.com/"

# Path segments that are topics, not events.
TOPIC_SEGMENTS = {"ycs", "championships", "event-information", "genesys",
                  "news-updates", "product-guide", "sjc", "uds", "wcq"}


@dataclass
class Entry:
    url: str
    year: str
    category: str
    event_slug: str | None
    slug: str
    lastmod: str | None          # the date, for grouping posts into events
    modified: str | None = None  # the same stamp as published, time and offset intact

    def to_dict(self) -> dict:
        return asdict(self)


def parse_sitemap_index(xml: str) -> list[str]:
    return [e.text for e in ET.fromstring(xml).findall(".//s:loc", NS) if e.text]


def parse_post_sitemap(xml: str) -> list[Entry]:
    out: list[Entry] = []
    for u in ET.fromstring(xml).findall(".//s:url", NS):
        loc = u.findtext("s:loc", namespaces=NS) or ""
        # Kept twice on purpose. Events are grouped by whole days, so lastmod is
        # a date and the comparisons downstream stay simple; the feed and the
        # per-round posting time need the clock, so the published stamp is kept
        # beside it rather than reconstructed later from a date.
        published = (u.findtext("s:lastmod", namespaces=NS) or "").strip() or None
        lastmod = published[:10] if published else None
        parts = [p for p in loc.replace(BASE, "").rstrip("/").split("/") if p]
        if len(parts) < 3:
            continue
        year, category, slug = parts[0], parts[1], parts[-1]
        event = parts[2] if len(parts) >= 4 and parts[2] not in TOPIC_SEGMENTS else None
        out.append(Entry(loc, year, category, event, slug, lastmod, published))
    return out


def event_windows(entries: list[Entry]) -> dict[str, tuple[str, str]]:
    """Date range covered by each explicit event slug."""
    seen: dict[str, list[str]] = {}
    for e in entries:
        if e.event_slug and e.lastmod:
            seen.setdefault(e.event_slug, []).append(e.lastmod)
    return {k: (min(v), max(v)) for k, v in seen.items()}


def assign_events(entries: list[Entry], slack_days: int = 4) -> list[dict]:
    """Attach every post to an event.

    Posts carrying an event slug define the windows. Posts without one are
    attached to a window their date falls inside, widened by a few days because
    write-ups land after the event ends.

    Concurrent events are real -- 2026-north-america-wcq and
    2026-north-america-genesys-championship share a date -- so a date alone is
    never enough to disambiguate. When several windows match, the format in the
    slug is used to choose, and anything still ambiguous is reported rather than
    guessed.
    """
    windows = event_windows(entries)

    def within(d: str, lo: str, hi: str) -> bool:
        return (date.fromisoformat(lo).toordinal() - slack_days
                <= date.fromisoformat(d).toordinal()
                <= date.fromisoformat(hi).toordinal() + slack_days)

    out = []
    for e in entries:
        rec = e.to_dict()
        if e.event_slug:
            rec["event"], rec["event_confidence"] = e.event_slug, "path"
        elif not e.lastmod:
            rec["event"], rec["event_confidence"] = None, "none"
        else:
            hits = [k for k, (lo, hi) in windows.items() if within(e.lastmod, lo, hi)]
            if len(hits) == 1:
                rec["event"], rec["event_confidence"] = hits[0], "date"
            elif len(hits) > 1:
                fmt = "genesys" if "genesys" in e.slug else ("advanced" if "advanced" in e.slug else None)
                narrowed = [h for h in hits if fmt and fmt in h] if fmt else []
                if len(narrowed) == 1:
                    rec["event"], rec["event_confidence"] = narrowed[0], "date+format"
                else:
                    rec["event"], rec["event_confidence"] = None, f"ambiguous:{len(hits)}"
            else:
                rec["event"], rec["event_confidence"] = None, "unmatched"
        out.append(rec)
    return out
