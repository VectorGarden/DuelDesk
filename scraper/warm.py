"""Fetch the posts a rebuild will need, before it needs them.

A rebuild asks the builder to read the same posts again, not to find new ones.
Every post it wants is one the scraper has already fetched at some point, and a
cache hit costs nothing -- so the whole cost of a rebuild is the posts that
happen not to be in the cache, at one second each. A batch of twenty-one events
spent five minutes and twenty-two seconds of its seven minutes exactly there.

So this fills the cache and stops. It fetches nothing the scraper would not
fetch itself: the same events, ranked the same way, and the same posts chosen
out of each by the same budget. What it leaves behind is what the next rebuild
would otherwise have spent its time collecting.

Bounded and resumable, because the whole corpus does not fit in a job. It works
newest-first, stops when its minutes are up, and the cache it leaves is picked
up by the next run -- of this or of the scraper, which restores the same
directory. Run it until it reports nothing left to fetch.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch import SITEMAP, Fetcher, newest_sitemap
from index import parse_post_sitemap, parse_sitemap_index
from run import events_by_recency, select_posts, worth_building


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=".scrape-state/cache")
    ap.add_argument("--minutes", type=float, default=240.0,
                    help="stop fetching after this long; the cache is kept")
    ap.add_argument("--limit", type=int, default=200,
                    help="posts per event, matching the scraper's own budget")
    args = ap.parse_args()

    deadline = time.monotonic() + args.minutes * 60
    f = Fetcher(cache_dir=args.cache)

    index = f.get(SITEMAP, refresh=True)
    sub = [l for l in parse_sitemap_index(index) if "posts-post" in l]
    entries = []
    for url in sub:
        entries += parse_post_sitemap(f.get(url, refresh=(url == newest_sitemap(index))))
    print(f"Indexed {len(entries):,} posts from {len(sub)} sub-sitemaps", flush=True)

    # The same posts the scraper would choose, for the same events, in the same
    # order. Anything else would warm a cache the rebuild does not read.
    wanted: list[str] = []
    seen: set[str] = set()
    events = 0
    for _slug, posts, _ended in events_by_recency(entries):
        if not worth_building(posts):
            continue
        events += 1
        for p in select_posts(posts, args.limit):
            if p["url"] not in seen:
                seen.add(p["url"])
                wanted.append(p["url"])

    have = sum(1 for u in wanted if f._path(u).exists())
    todo = [u for u in wanted if not f._path(u).exists()]
    print(f"{events} events want {len(wanted):,} posts; "
          f"{have:,} are cached and {len(todo):,} are not", flush=True)

    fetched = failed = 0
    for url in todo:
        if time.monotonic() >= deadline:
            print(f"Out of time with {len(todo) - fetched - failed:,} still to fetch",
                  flush=True)
            break
        try:
            f.get(url)
            fetched += 1
        except Exception as e:                      # noqa: BLE001
            # One post that will not load is not a reason to abandon the rest,
            # and the next run will try it again.
            failed += 1
            print(f"  could not fetch {url}: {e}", flush=True)
        if fetched % 100 == 0 and fetched:
            print(f"  {fetched:,} fetched, {len(todo) - fetched - failed:,} to go",
                  flush=True)

    left = len(todo) - fetched - failed
    print(f"Fetched {fetched:,}, failed {failed:,}, {left:,} left; "
          f"cache holds {f.cache_size():,} posts")
    if not left and not failed:
        print("WARM: the cache holds every post a rebuild will read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
