#!/usr/bin/env python3
"""Scrape the newest event's coverage into the site's rounds.json shape.

Deliberately conservative about scope: it takes the most recent event window
from the sitemap and fetches only that event's posts, rather than crawling
12,000 archived posts on an hourly schedule.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build import Source, build_event                     # noqa: E402
from fetch import BASE, SITEMAP, Fetcher, newest_sitemap  # noqa: E402
from index import assign_events, parse_post_sitemap, parse_sitemap_index  # noqa: E402
from parse import parse_post                              # noqa: E402

# Ties were removed from tournament policy on this date.
DRAWS_ABOLISHED = date(2025, 9, 2)


def newest_event(entries):
    """The event slug with the most recent activity, and its posts."""
    assigned = assign_events(entries)
    dated = [a for a in assigned if a.get("event") and a.get("lastmod")]
    if not dated:
        return None, [], None
    latest = max(dated, key=lambda a: a["lastmod"])
    slug = latest["event"]
    posts = [a for a in assigned if a.get("event") == slug]
    return slug, posts, max(p["lastmod"] for p in posts if p["lastmod"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scraped-rounds.json")
    ap.add_argument("--cache", default=".scrape-state/cache")
    ap.add_argument("--summary", help="file to append a human-readable report to")
    ap.add_argument("--limit", type=int, default=60, help="max posts to fetch")
    args = ap.parse_args()

    f = Fetcher(cache_dir=args.cache)
    index = f.get(SITEMAP, refresh=True)

    # Every post sub-sitemap, not just the newest. An event's posts are split
    # across URL shapes -- some carry the event slug, most do not -- and the
    # undated siblings are attached by date window, so they have to be in the
    # index for that to work. Reading only the newest chunk found 35 of the
    # event's posts and none of its round pairings.
    sub = [l for l in parse_sitemap_index(index) if "posts-post" in l]
    entries = []
    for url in sub:
        entries += parse_post_sitemap(f.get(url, refresh=(url == newest_sitemap(index))))
    print(f"Indexed {len(entries):,} posts from {len(sub)} sub-sitemaps")

    slug, posts, latest = newest_event(entries)
    if not slug:
        print("No event could be identified from the sitemap.")
        return 0

    posts = sorted(posts, key=lambda p: p["lastmod"] or "", reverse=True)[: args.limit]
    print(f"Event {slug!r}: fetching {len(posts)} posts (newest {latest})")

    sources = []
    for p in posts:
        try:
            html = f.get(p["url"])
        except Exception as exc:                    # a single bad page must not stop the run
            print(f"  skipped {p['url']}: {exc}")
            continue
        sources.append(Source(url=p["url"], post=parse_post(html, p["url"]),
                              posted=(p["lastmod"] or "")[:10]))

    draws_possible = bool(latest) and date.fromisoformat(latest) < DRAWS_ABOLISHED
    event = build_event(slug.replace("-", " ").title(), sources,
                        draws_possible=draws_possible, updated=latest)

    Path(args.out).write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n")

    kinds = Counter(s.post.kind for s in sources)
    lines = [
        f"### Scrape of `{slug}`",
        "",
        f"- posts fetched: **{len(sources)}** ({', '.join(f'{v} {k}' for k, v in kinds.most_common())})",
        f"- formats found: **{', '.join(f['format'] for f in event['formats']) or 'none'}**",
        f"- posts naming no format: **{event['_unassigned']}**",
        "",
    ]
    for fmt in event["formats"]:
        conf = Counter(s["record"]["confidence"]
                       for r in fmt["rounds"] for s in r["standings"] if s.get("record"))
        lines.append(f"**{fmt['format']}** — {len(fmt['rounds'])} rounds, "
                     f"{fmt['swissRounds']} Swiss, {fmt['duelists']} Duelists"
                     + (f", records: {dict(conf)}" if conf else ", no standings found"))
    report = "\n".join(lines)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
