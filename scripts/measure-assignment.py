#!/usr/bin/env python3
"""What a change to event assignment would do, measured against the real index.

    scripts/measure-assignment.py                  # versus the archive on disk
    scripts/measure-assignment.py --against REF    # versus another commit's rules

The index is the point. An earlier harness reconstructed one from
events/*/posts.json, which is only the posts the archive has adopted -- 8,546
of them against the sitemap's 12,072. The missing third is not inert: every
word-frequency rule in index.py is computed over every indexed post, so
"jose", "costa" and "toronto" looked rare enough to name an event in that
subset and are not in the real one. Three posts #275 was measured to move did
not move, and nothing in the measurement could have said so.

Worse, that harness agreed with the archive a little more each run whatever
the truth was: a post the archive drops leaves posts.json, and the next run
cannot see it at all.

So this reads the sitemap, the way run.py does. The fetches are cached, so
only the first run costs anything, and the sitemap index is re-read each time
because it is the one file that changes.
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))

from fetch import SITEMAP, Fetcher, newest_sitemap  # noqa: E402
from index import parse_post_sitemap, parse_sitemap_index  # noqa: E402
from parse import lead, parse_post  # noqa: E402
from build import Source, seated  # noqa: E402

CACHE = ".scrape-state/cache"


def sitemap_entries(cache: str, refresh: bool = True):
    """Every post the blog lists, and a way to read one, as run.py has both.

    The reader matters for about ten posts on the blog and it is not optional
    to have it. A winner announcement whose slug says only "we-have-a-winner-13"
    is placed by the sentence inside it -- "Esteban Jesus Mena Campos is our new
    Central America WCQ Champion" -- and with no reader that rule does nothing,
    so those posts read as belonging nowhere and every comparison here reports
    them as a loss the archive did not make.
    """
    f = Fetcher(cache_dir=cache)
    index = f.get(SITEMAP, refresh=refresh)
    subs = [l for l in parse_sitemap_index(index) if "posts-post" in l]
    entries = []
    for url in subs:
        entries += parse_post_sitemap(f.get(url, refresh=refresh and url == newest_sitemap(index)))
    return (entries, len(subs), lambda url: lead(f.get(url)),
            lambda url: seated(Source(url, parse_post(f.get(url), url))))


def stored() -> dict[str, str]:
    """Which event the archive currently files each post under."""
    out = {}
    for path in sorted(glob.glob("events/*/posts.json")):
        slug = path.split(os.sep)[1]
        for post in json.loads(Path(path).read_text()):
            out[post["url"]] = slug
    return out


def _placed(index, run, entries, read, names):
    """Where production puts every post: assignment, then the step run.py takes
    after it -- a post filed under one event that was played at another is
    moved before anything is ranked. A commit from before that step has no
    run.misfiled, and is measured as it was: assignment alone."""
    out = {r["url"]: r.get("event") for r in index.assign_events(entries, read=read)}
    if run is not None and hasattr(run, "misfiled") and names is not None:
        for slug, posts, _ in run.events_by_recency(entries, read, names):
            for post in posts:
                out[post["url"]] = slug
    return out


def _scraper_modules() -> list[str]:
    here = Path(__file__).resolve().parent.parent / "scraper"
    return [f.stem for f in here.glob("*.py") if not f.stem.startswith("test_")]


def assign_with(ref: str | None, entries, read=None, names=None):
    """Place every post with a given commit's rules, or the working tree's."""
    mods = _scraper_modules()
    if ref is None:
        import index, run
        return _placed(index, run, entries, read, names)
    with tempfile.TemporaryDirectory() as tmp:
        listed = subprocess.run(["git", "ls-tree", "--name-only", ref, "scraper/"],
                                capture_output=True, text=True).stdout.split()
        for path in listed:
            if path.endswith(".py") and not Path(path).name.startswith("test_"):
                src = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
                if src.returncode == 0:
                    Path(tmp, Path(path).name).write_text(src.stdout)
        saved = {m: sys.modules.pop(m) for m in list(sys.modules) if m in mods}
        sys.path.insert(0, tmp)
        try:
            import index as old_index
            try:
                import run as old_run
            except Exception:
                old_run = None
            return _placed(old_index, old_run, entries, read, names)
        finally:
            sys.path.remove(tmp)
            for m in [m for m in list(sys.modules) if m in mods]:
                del sys.modules[m]
            sys.modules.update(saved)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--against", metavar="REF",
                    help="compare with this commit's rules instead of the archive on disk")
    ap.add_argument("--cache", default=CACHE, help=f"fetch cache (default {CACHE})")
    ap.add_argument("--offline", action="store_true",
                    help="trust the cache completely, fetching nothing")
    ap.add_argument("--quiet", action="store_true", help="counts only, no list")
    args = ap.parse_args()

    entries, subs, read, names = sitemap_entries(args.cache, refresh=not args.offline)
    print(f"Indexed {len(entries):,} posts from {subs} sub-sitemaps")

    now = assign_with(None, entries, read, names)
    if args.against:
        was = assign_with(args.against, entries, read, names)
        label = f"{args.against}'s rules"
    else:
        was = stored()
        label = "the archive on disk"

    # Against the archive, only the posts it holds can be compared. posts.json
    # is a filtered view -- an event keeps its coverage and not the week's
    # product news -- so a post assign_events places that the archive does not
    # store is the filter working, not a disagreement.
    urls = set(was) if not args.against else set(was) | set(now)
    changed = [(u, was.get(u), now.get(u)) for u in urls if was.get(u) != now.get(u)]
    detach = sum(1 for _, w, n in changed if w and not n)
    attach = sum(1 for _, w, n in changed if n and not w)
    print(f"{len(changed)} of {len(entries):,} posts differ from {label}: "
          f"{detach} detached, {attach} attached, {len(changed) - detach - attach} moved")
    if not args.quiet:
        for url, w, n in sorted(changed):
            print(f"  {url[len('https://yugiohblog.konami.com/'):]}\n      {w} -> {n}")
    losses = collections.Counter(w for _, w, n in changed if w and w != n)
    for event, n in losses.most_common(10):
        print(f"  {event:46} loses {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
