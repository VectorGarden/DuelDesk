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
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build import Source, build_event                     # noqa: E402
from cadence import is_ongoing                            # noqa: E402
from fetch import (BASE, SITEMAP, Fetcher, newest_sitemap,  # noqa: E402
                   parse_lastmod)
from index import assign_events, parse_post_sitemap, parse_sitemap_index  # noqa: E402
from feed import build_feed                              # noqa: E402
from naming import event_name                            # noqa: E402
from parse import detect_kind, parse_post                 # noqa: E402

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


# Only pairings and standings feed a record, and losses need *every* round's
# pairings, so those two are not rationed. The rest is ordering for the case
# where the budget still binds.
# Order within a rotation, not a cut-off: a feature match attaches to a round on
# the page, so it goes before coverage that only ever appears in the feed.
RANK = {"feature": 0, "deck": 1, "result": 2, "news": 3}


def select_posts(posts: list[dict], limit: int) -> list[dict]:
    """Which of an event's posts to fetch, and in what order.

    Sorting everything by kind and taking the first N starves whichever kinds
    sort last. At YCS Montreal that was feature matches: 30 pairings and 23
    standings filled 53 of 60 slots, so 5 of 37 features were fetched -- and all
    five happened to be Genesys, so Advanced showed none at all, including its
    Top 8 and Top 4 feature matches.

    Pairings and standings come first and whole, because a record is wrong
    without every round of them. What remains is shared round-robin, so a thin
    budget thins every kind rather than deleting one: half the feature matches is
    a smaller loss than none of them.

    Newest first within a kind. For a finished event that is the top cut, which
    is the coverage most worth having when not all of it fits.

    Worth being plain about the trade: under a budget tight enough to bind, this
    gives feature matches fewer than the old strict ordering did -- two of 37 at
    a limit of 60 where the old rule managed five. It is the limit that was
    wrong. At 200, which is above what an event publishes, every kind arrives
    whole and the rotation never runs.
    """
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        by_kind[post["kind"]].append(post)
    for group in by_kind.values():
        group.sort(key=lambda p: p["lastmod"] or "", reverse=True)

    chosen = [p for kind in ("pairings", "standings") for p in by_kind.pop(kind, [])]
    rationed = [by_kind[k] for k in sorted(by_kind, key=lambda k: RANK.get(k, 9))]
    while len(chosen) < limit and any(rationed):
        for group in rationed:
            if group and len(chosen) < limit:
                chosen.append(group.pop(0))
    return chosen[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scraped-rounds.json")
    ap.add_argument("--cache", default=".scrape-state/cache")
    ap.add_argument("--summary", help="file to append a human-readable report to")
    # An event runs to about 140 posts and its own table of contents caps out
    # under 200. Cache hits cost nothing, so fetching a whole event is a one-off
    # of a few minutes and every run after it fetches only what is new.
    ap.add_argument("--limit", type=int, default=200, help="max posts to fetch")
    ap.add_argument("--feed", help="also write an RSS feed of the posts seen")
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

    # Spend the budget on posts that carry results. Only pairings and standings
    # feed a record, and losses need *every* round's pairings -- so a newest-first
    # cut spent a third of its fetches on news posts and then left the records
    # partial for want of the rounds it never reached.
    #
    # The kind is readable from the slug, so this costs nothing.
    RANK = {"pairings": 0, "standings": 1, "deck": 2, "feature": 3, "result": 4, "news": 5}
    for p in posts:
        p["kind"] = detect_kind(p["slug"])
    posts.sort(key=lambda p: (RANK.get(p["kind"], 9), p["lastmod"] or ""))

    available = Counter(p["kind"] for p in posts)
    posts = posts[: args.limit]
    taken = Counter(p["kind"] for p in posts)
    dropped = {k: n - taken.get(k, 0) for k, n in available.items() if n > taken.get(k, 0)}

    print(f"Event {slug!r}: {sum(available.values())} posts, fetching {len(posts)} "
          f"({', '.join(f'{v} {k}' for k, v in taken.most_common())})")
    if dropped:
        # Never let a budget silently cap coverage: a missing pairings page is
        # the difference between a derived record and a partial one.
        print(f"  not fetched (limit {args.limit}): "
              + ", ".join(f"{v} {k}" for k, v in sorted(dropped.items())))

    sources = []
    for p in posts:
        try:
            html = f.get(p["url"])
        except Exception as exc:                    # a single bad page must not stop the run
            print(f"  skipped {p['url']}: {exc}")
            continue
        sources.append(Source(url=p["url"], post=parse_post(html, p["url"]),
                              posted=p.get("modified") or p["lastmod"]))

    draws_possible = bool(latest) and date.fromisoformat(latest) < DRAWS_ABOLISHED
    # The slug is the last resort, not the first: it renders 2026-08-quebec as
    # "2026 08 Quebec" while every post it covers is titled "YCS Montreal".
    name = event_name([s.post.title for s in sources],
                      slug.replace("-", " ").title())
    # Whether a round may be shown as in progress. Read from the coverage rather
    # than assumed: the newest post of a finished event is days old.
    newest = max((parse_lastmod(s.posted) for s in sources if s.posted),
                 default=None, key=lambda d: d or datetime.min.replace(tzinfo=timezone.utc))
    ongoing = is_ongoing(newest, datetime.now(timezone.utc))
    print(f"Newest post {newest.isoformat() if newest else 'unknown'}; "
          f"event {'ongoing' if ongoing else 'finished'}")
    event = build_event(name, sources, draws_possible=draws_possible, updated=latest,
                        ongoing=ongoing)

    Path(args.out).write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n")

    if args.feed:
        Path(args.feed).write_text(build_feed(name, [
            {"title": s.post.title, "url": s.url, "modified": s.posted,
             "kind": s.post.kind, "format": s.post.fmt} for s in sources]))

    kinds = Counter(s.post.kind for s in sources)
    lines = [
        f"### Scrape of `{slug}`",
        "",
        f"- posts fetched: **{len(sources)}** ({', '.join(f'{v} {k}' for k, v in kinds.most_common())})",
        *([f"- **not fetched** (limit {args.limit}): "
           + ", ".join(f"{v} {k}" for k, v in sorted(dropped.items()))] if dropped else []),
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
