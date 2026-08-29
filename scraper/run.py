#!/usr/bin/env python3
"""Scrape event coverage from the blog into the site's archive.

The newest event every run, and optionally a few older ones behind it. Scope is
deliberately narrow per run: the blog indexes 12,000 posts and about 4,800 of
them are event coverage, which is not something to crawl on an hourly schedule.
The backfill is how the rest arrives -- a handful of events at a time, each one
written once and then skipped on every run after it.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import archive                                            # noqa: E402
from build import Source, build_event                     # noqa: E402
from cadence import is_ongoing                            # noqa: E402
from fetch import (BASE, SITEMAP, Fetcher, newest_sitemap,  # noqa: E402
                   parse_lastmod)
from index import (assign_events, event_profiles, parse_post_sitemap,  # noqa: E402
                   parse_sitemap_index)
from feed import build_feed                              # noqa: E402
from naming import event_name                            # noqa: E402
from parse import detect_kind, parse_post                 # noqa: E402

# Ties were removed from tournament policy on this date.
DRAWS_ABOLISHED = date(2025, 9, 2)


def events_by_recency(entries) -> list[tuple[str, list[dict], str]]:
    """Every identified event, its posts, and the day its coverage ended.

    That last date is taken from the event's window rather than from the newest
    lastmod among its posts, because lastmod is a modification date. One post of
    the 2025 North America WCQ was edited in July 2026, which dated the whole
    event to 2026: it sorted ahead of the 2026 WCQ in the archive, and it fell
    the wrong side of the day ties were abolished, so a tournament played while
    draws were still policy had its records built without them.

    The kind is read from the slug here rather than after a page is fetched, so
    both of the decisions that follow -- which events are worth building, and
    which of an event's posts to spend the budget on -- cost nothing.
    """
    profiles = event_profiles(entries)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in assign_events(entries):
        if a.get("event") and a.get("lastmod"):
            a["kind"] = detect_kind(a["slug"])
            grouped[a["event"]].append(a)
    return sorted(((slug, posts, profiles[slug].window[1])
                   for slug, posts in grouped.items()),
                  key=lambda e: e[2], reverse=True)


def worth_building(posts: list[dict]) -> bool:
    """Whether an event has enough coverage to make a round track.

    Read from the slugs, before spending a single request. Of 97 event slugs
    only 68 published both pairings and standings; the rest are an announcement
    or two, and building them would put empty events in the archive and in the
    reader's event list.
    """
    kinds = {p["kind"] for p in posts}
    return "pairings" in kinds and "standings" in kinds


def plan(entries, done: set[str], backfill: int) -> list[tuple[str, list[dict], str]]:
    """Which events this run builds: the newest, plus `backfill` older ones.

    The newest event is rebuilt every time because it may still be running. The
    backfill takes the next-newest events not already in the archive, so a run
    walks backwards through history a few events at a time and a finished event
    is fetched exactly once.
    """
    ranked = [e for e in events_by_recency(entries) if worth_building(e[1])]
    if not ranked:
        return []
    chosen = [ranked[0]]
    for event in ranked[1:]:
        if len(chosen) > backfill:
            break
        if event[0] not in done:
            chosen.append(event)
    return chosen


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


def build_one(f, slug: str, posts: list[dict], ended: str,
              limit: int) -> tuple[dict, list[dict], list[str]]:
    """Fetch and build one event. Returns (event, feed posts, report lines)."""
    available = Counter(p["kind"] for p in posts)
    chosen = select_posts(posts, limit)
    taken = Counter(p["kind"] for p in chosen)
    dropped = {k: n - taken.get(k, 0) for k, n in available.items() if n > taken.get(k, 0)}

    print(f"Event {slug!r}: {sum(available.values())} posts, fetching {len(chosen)} "
          f"({', '.join(f'{v} {k}' for k, v in taken.most_common())})")
    if dropped:
        # Never let a budget silently cap coverage: a missing pairings page is
        # the difference between a derived record and a partial one.
        print(f"  not fetched (limit {limit}): "
              + ", ".join(f"{v} {k}" for k, v in sorted(dropped.items())))

    sources = []
    for p in chosen:
        try:
            html = f.get(p["url"])
        except Exception as exc:                # a single bad page must not stop the run
            print(f"  skipped {p['url']}: {exc}")
            continue
        sources.append(Source(url=p["url"], post=parse_post(html, p["url"]),
                              posted=p.get("modified") or p["lastmod"]))
    if not sources:
        return {}, [], [f"### `{slug}` — nothing could be fetched", ""]

    draws_possible = date.fromisoformat(ended) < DRAWS_ABOLISHED
    # The slug is the last resort, not the first: it renders 2026-08-quebec as
    # "2026 08 Quebec" while every post it covers is titled "YCS Montreal".
    name = event_name([s.post.title for s in sources], slug.replace("-", " ").title())
    # Whether a round may be shown as in progress. Read from the coverage rather
    # than assumed: the newest post of a finished event is days old.
    newest = max((parse_lastmod(s.posted) for s in sources if s.posted),
                 default=None, key=lambda d: d or datetime.min.replace(tzinfo=timezone.utc))
    ongoing = is_ongoing(newest, datetime.now(timezone.utc))
    print(f"  {name}: newest post {newest.isoformat() if newest else 'unknown'}, "
          f"{'ongoing' if ongoing else 'finished'}")
    event = build_event(name, sources, draws_possible=draws_possible, updated=ended,
                        ongoing=ongoing)

    feed_posts = [{"title": s.post.title, "url": s.url, "modified": s.posted,
                   "kind": s.post.kind, "format": s.post.fmt, "event": name,
                   "slug": slug} for s in sources]

    kinds = Counter(s.post.kind for s in sources)
    lines = [
        f"### {name} — `{slug}`",
        "",
        f"- posts fetched: **{len(sources)}** ({', '.join(f'{v} {k}' for k, v in kinds.most_common())})",
        *([f"- **not fetched** (limit {limit}): "
           + ", ".join(f"{v} {k}" for k, v in sorted(dropped.items()))] if dropped else []),
        # An event that runs one tournament and never names a format has one
        # with no name, which is a fact about the coverage, not a gap in it.
        f"- tournaments: **{', '.join(f['format'] or 'unnamed' for f in event['formats']) or 'none'}**",
        f"- posts naming no format: **{event['_unassigned']}**",
    ]
    for fmt in event["formats"]:
        conf = Counter(s["record"]["confidence"]
                       for r in fmt["rounds"] for s in r["standings"] if s.get("record"))
        # How much of the Swiss the blog actually published. Older events are
        # covered in patches -- the 2026 North America WCQ ran fifteen Swiss
        # rounds and has pairings for nine -- and a run that only reported the
        # rounds it found would read as complete coverage of a shorter event.
        swiss = [r for r in fmt["rounds"] if r["phase"] == "Swiss"]
        gap = ("" if len(swiss) >= (fmt["swissRounds"] or 0)
               else f", **{fmt['swissRounds'] - len(swiss)} Swiss rounds not published**")
        lines.append(f"- **{fmt['format'] or 'Main event'}** — {len(fmt['rounds'])} rounds, "
                     f"{fmt['swissRounds']} Swiss, {fmt['duelists']} Duelists"
                     + (f", records: {dict(conf)}" if conf else ", no standings found")
                     + gap)
    lines.append("")
    return event, feed_posts, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=archive.ARCHIVE,
                    help="directory of per-event coverage")
    ap.add_argument("--manifest", default=archive.MANIFEST,
                    help="index of every event in the archive")
    ap.add_argument("--cache", default=".scrape-state/cache")
    ap.add_argument("--summary", help="file to append a human-readable report to")
    # An event runs to about 140 posts and its own table of contents caps out
    # under 200. Cache hits cost nothing, so fetching a whole event is a one-off
    # of a few minutes and every run after it fetches only what is new.
    ap.add_argument("--limit", type=int, default=200, help="max posts to fetch per event")
    # Off by default. A scheduled run covers the event that is on; catching up on
    # history is something asked for, and asked for in small amounts, because at
    # a request a second an event is minutes and the archive is hours.
    ap.add_argument("--backfill", type=int, default=0, metavar="N",
                    help="also build the N newest events missing from the archive")
    ap.add_argument("--feed", help="also write an RSS feed of the archive's newest posts")
    ap.add_argument("--feed-items", type=int, default=300,
                    help="how many posts the feed carries")
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

    done = archive.scraped(args.archive)
    chosen = plan(entries, done, args.backfill)
    if not chosen:
        print("No event with both pairings and standings could be identified.")
        return 0
    print(f"Archive holds {len(done)} events; building "
          + ", ".join(f"{slug} ({ended})" for slug, _, ended in chosen))

    report: list[str] = []
    newest_event = None
    for i, (slug, posts, ended) in enumerate(chosen):
        event, feed_posts, lines = build_one(f, slug, posts, ended, args.limit)
        report += lines
        if not event:
            continue
        archive.write_event(args.archive, slug, event, feed_posts)
        if i == 0:
            newest_event = event   # names the feed's channel

    manifest = archive.build_manifest(args.archive)
    Path(args.manifest).write_text(archive.dumps(manifest, pretty=True), encoding="utf-8")
    print(f"Manifest lists {len(manifest['events'])} events")

    if args.feed:
        items = archive.feed_items(args.archive, args.feed_items)
        Path(args.feed).write_text(build_feed(
            (newest_event or {}).get("event") or "Duel Desk", items))
        print(f"Feed carries {len(items)} posts")

    text = "\n".join(report)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
