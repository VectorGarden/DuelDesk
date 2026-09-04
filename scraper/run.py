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
import shutil
import contextlib
import importlib.util
import io
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import archive                                            # noqa: E402
from article import (holds_decks, link_names,             # noqa: E402
                     read as read_article, readable)
from build import BUILD_VERSION, Source, build_event      # noqa: E402
from cadence import is_ongoing                            # noqa: E402
from fetch import (BASE, SITEMAP, Fetcher, newest_sitemap,  # noqa: E402
                   parse_lastmod)
from winners import named_in                              # noqa: E402
from index import (assign_events, event_profiles, parse_post_sitemap,  # noqa: E402
                   parse_sitemap_index, settled_end, tight_window)
from feed import build_feed                              # noqa: E402
from naming import canonical_name, event_name            # noqa: E402
from parse import (coverage_format, detect_kind, entry, lead,  # noqa: E402
                   parse_post)

# The kinds that are writing. A pairings or standings post is a table the
# archive already stores and the page already draws, and they are 44% of every
# post in it -- extracting their prose would store the tables a second time to
# say nothing around them.
ARTICLE_KINDS = ("feature", "deck", "news", "result")


def duelists_in(event: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Everyone who played, and the two Duelists of each feature match.

    Two lists because they answer different questions. A feature match is
    about two people the archive already knows, from the title it parses to
    build the round, so a surname in it can only mean one of them. Every other
    post is about the field, where 40.8% of Duelists share a surname with
    somebody else in their own event.

    A team's own name is not a Duelist and has no page. Its members are, and a
    team match carries the duels it was decided by, each naming both seats.
    """
    field, features = set(), {}
    for fmt in event.get("formats", []):
        for rnd in fmt.get("rounds", []):
            for row in rnd.get("pairings") or []:
                for duel in row.get("duels") or [row]:
                    for side in ("a", "b"):
                        if duel.get(side):
                            field.add(duel[side])
            for feature in rnd.get("features") or []:
                if feature.get("source"):
                    features[feature["source"]] = [
                        name for side in ("a", "b")
                        if (name := (feature.get(side) or {}).get("name"))]
    # A feature match's Duelists come out of the post's title, which is where
    # the blog shortens: "Julien Kehon" for the Julien Leo Kehon in the
    # standings. A link has to go to the page the archive actually keeps, so
    # each is answered against the field.
    field = sorted(field)
    features = {url: [filed for name in pair
                      if (filed := _as_filed(name, field))]
                for url, pair in features.items()}
    return field, features


def _as_filed(name: str, field: list[str]) -> str | None:
    """The name the archive keeps this Duelist under, or None.

    Exactly one, or nobody: a short name that answers to two entrants
    identifies neither, and linking it to whichever came first would send a
    reader to somebody else's page.

    None where the field does not have them at all. A title carries typos --
    "Feilx Pfeiffer" for Felix -- and names Duelists whose pairings were never
    published, and a link to a page that says nobody by that name is worse
    than the words left plain. Its match then has one Duelist rather than two,
    which is answered by asking the whole field without surnames.
    """
    if name in field:
        return name
    fuller = [f for f in field if named_in(f, name) >= 0]
    return fuller[0] if len(fuller) == 1 else None


def article_people(kind: str, url: str, field: list[str],
                   features: dict[str, list[str]]) -> tuple[list[str], bool]:
    """Who a post may be about, and whether a surname alone identifies them.

    A feature match is about the two Duelists its title names, and in a write-up
    about two people a surname can only be one of them. Anything else is about
    the field, where 40.8% of Duelists share a surname with another entrant --
    79% at the worst event -- so there only a name written in full is read.
    """
    pair = features.get(url) or []
    about_two = kind == "feature" and len(pair) == 2
    return (pair if about_two else field), about_two

# Ties were removed from tournament policy on this date.
DRAWS_ABOLISHED = date(2025, 9, 2)


def events_by_recency(entries, read=None) -> list[tuple[str, list[dict], str]]:
    """Every identified event, its posts, and the day its coverage ended.

    That last date is taken from the event's window rather than from the newest
    lastmod among its posts, because lastmod is a modification date. One post of
    the 2025 North America WCQ was edited in July 2026, which dated the whole
    event to 2026: it sorted ahead of the 2026 WCQ in the archive, and it fell
    the wrong side of the day ties were abolished, so a tournament played while
    draws were still policy had its records built without them.

    An event the blog filed under no path of its own has no profile to read
    that window off, because a profile is built from the posts carrying the
    slug and these carry none. Their dates are all the event has, so the same
    rule is applied to them directly: the bulk of them, strays ignored.

    The kind is read from the slug here rather than after a page is fetched, so
    both of the decisions that follow -- which events are worth building, and
    which of an event's posts to spend the budget on -- cost nothing.
    """
    profiles = event_profiles(entries)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in assign_events(entries, read=read):
        if a.get("event") and a.get("lastmod"):
            a["kind"] = detect_kind(a["slug"])
            grouped[a["event"]].append(a)

    def ended(slug: str, posts: list[dict]) -> str:
        end = (profiles[slug].window[1] if slug in profiles
               else tight_window([p["lastmod"] for p in posts])[1])
        # And not the day somebody edited one post afterwards. This is the
        # date the event is listed and sorted under, and for events either
        # side of the day ties were abolished it decides whether their records
        # may hold a draw -- YCS Vancouver ran in August 2025 and one edited
        # post dated it to September, past the change.
        seen = Counter(p["lastmod"] for p in posts if p.get("lastmod"))
        return settled_end(end, seen, date.today().isoformat())

    return sorted(((slug, posts, ended(slug, posts))
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


def plan(entries, done: set[str], backfill: int,
         rebuild: int = 0, behind: set[str] | frozenset = frozenset(),
         read=None) -> list[tuple[str, list[dict], str]]:
    """Which events this run builds: the newest, plus older ones.

    The newest event is rebuilt every time because it may still be running. The
    backfill takes the next-newest events not already in the archive, so a run
    walks backwards through history a few events at a time and a finished event
    is fetched exactly once.

    `rebuild` takes events that *are* in the archive but were written by an
    older builder. Separate from the backfill because they are opposite
    questions -- one asks what is missing, the other what is out of date -- and
    a run doing both at once would be hard to read afterwards. Newest first
    either way: if a rebuild is interrupted, the events most likely to be
    looked at are the ones already corrected.
    """
    ranked = [e for e in events_by_recency(entries, read) if worth_building(e[1])]
    if not ranked:
        return []
    chosen = [ranked[0]]
    taken = {ranked[0][0]}
    for event in ranked[1:]:
        if len(chosen) > backfill:
            break
        if event[0] not in done:
            chosen.append(event)
            taken.add(event[0])
    for event in ranked[1:]:
        if len(chosen) >= backfill + rebuild + 1:
            break
        if event[0] in behind and event[0] not in taken:
            chosen.append(event)
            taken.add(event[0])
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
              limit: int) -> tuple[dict, list[dict], dict[str, list], list[str]]:
    """Fetch and build one event.

    Returns (event, feed posts, articles, report lines).
    """
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

    sources, articles, kinds_of = [], {}, {}
    for p in chosen:
        try:
            html = f.get(p["url"])
        except Exception as exc:                # a single bad page must not stop the run
            print(f"  skipped {p['url']}: {exc}")
            continue
        post = parse_post(html, p["url"])
        sources.append(Source(url=p["url"], post=post,
                              posted=p.get("modified") or p["lastmod"]))
        # The prose, for the reader. Only the kinds that are writing: a
        # pairings or standings post is a table this archive already stores
        # and already draws, and 94% of them carry under 200 characters
        # around it. And only where there is enough of it -- see article.THIN.
        if post.kind in ARTICLE_KINDS:
            blocks, linked = read_article(entry(html))
            if readable(blocks, linked):
                articles[p["url"]] = blocks
                kinds_of[p["url"]] = post.kind
    if not sources:
        return {}, [], {}, [f"### `{slug}` — nothing could be fetched", ""]

    draws_possible = date.fromisoformat(ended) < DRAWS_ABOLISHED
    # The slug is the last resort, not the first: it renders 2026-08-quebec as
    # "2026 08 Quebec" while every post it covers is titled "YCS Montreal".
    fallback = slug.replace("-", " ").title()
    name = event_name([s.post.title for s in sources], fallback)
    # Then settled: a regional qualifier is named for its region and year
    # whatever its coverage called it, and a slug that names only a place is a
    # YCS. Eighteen of the archive's fifty-one events were listed under a name
    # that did not identify them -- five WCQs spelled five ways, and labels like
    # "11 10 Columbus".
    name, location = canonical_name(name, slug, ended, named=name != fallback)
    # Whether a round may be shown as in progress. Read from the coverage rather
    # than assumed: the newest post of a finished event is days old.
    newest = max((parse_lastmod(s.posted) for s in sources if s.posted),
                 default=None, key=lambda d: d or datetime.min.replace(tzinfo=timezone.utc))
    ongoing = is_ongoing(newest, datetime.now(timezone.utc))
    print(f"  {name}: newest post {newest.isoformat() if newest else 'unknown'}, "
          f"{'ongoing' if ongoing else 'finished'}")
    event = build_event(name, sources, draws_possible=draws_possible, updated=ended,
                        ongoing=ongoing, location=location)

    # Whether this post can be read here. The page needs to know before it
    # fetches any prose -- a "Read it here" offered on a post that has none is
    # worse than the link it replaced -- and posts.json is already on its way.
    # The Duelists in the prose, now that the event is built and the archive
    # knows who played and who each feature match was between.
    field, features = duelists_in(event)
    for url, blocks in articles.items():
        people, by_surname = article_people(kinds_of.get(url, ""), url, field, features)
        articles[url] = link_names(blocks, people, by_surname=by_surname)

    feed_posts = [{"title": s.post.title, "url": s.url, "modified": s.posted,
                   "kind": s.post.kind, "event": name,
                   **({"article": True} if s.url in articles else {}),
                   # And whether it has deck lists in it, so the event page can
                   # offer them without fetching half a megabyte of prose to
                   # find out. 99 posts in the archive do; a post whose title
                   # says "deck" is wrong about it more often than not.
                   **({"decks": True}
                      if holds_decks(articles.get(s.url) or []) else {}),
                   # What the post is coverage of, which for Dragon Duel is not
                   # a format the builder groups rounds by. See coverage_format.
                   "format": coverage_format(s.post.title, s.post.fmt),
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
        entrants = f"{fmt['duelists']} {fmt.get('entrant', 'Duelist')}s"
        lines.append(f"- **{fmt['format'] or 'Main event'}** — {len(fmt['rounds'])} rounds, "
                     f"{fmt['swissRounds']} Swiss, {entrants}"
                     + (f", records: {dict(conf)}" if conf else ", no standings found")
                     + gap)
    lines.append("")
    return event, feed_posts, articles, lines


CHECKER = Path(__file__).resolve().parent.parent / ".github/scripts/check-rounds.py"
_checker_module = None


def _checker():
    """check-rounds.py as a module, loaded once.

    Its name has a hyphen in it, so it cannot be imported by name -- and it is
    a script CI calls as a command, which is the point of it. Nothing here
    copies its rules; this is the file itself.
    """
    global _checker_module
    if _checker_module is None:
        spec = importlib.util.spec_from_file_location("check_rounds", CHECKER)
        _checker_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_checker_module)
    return _checker_module


def coherence_problem(root: str, slug: str) -> str | None:
    """What check-rounds.py objects to in a built event, or None if nothing.

    The same script CI runs, and the same rules -- it is that file, loaded.
    Two sets of rules for what counts as coherent data would drift, and the
    one that matters is the one that gates the deploy.

    Loaded rather than run as a command. A build asks this about every event
    it writes, and a batch writes forty: at 66ms to start Python that was two
    and a half seconds of a run, and five seconds of the test suite, spent
    starting an interpreter that is already running.
    """
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        code = _checker().main(str(archive.rounds_path(root, slug)))
    if code == 0:
        return None
    lines = [l.strip() for l in said.getvalue().splitlines() if l.strip()]
    return "; ".join(l.removeprefix("FAIL").strip() for l in lines) or "failed the coherence check"


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
    # Also off by default, and for the same reason: an event already in the
    # archive costs the same minutes to fetch again as it did the first time.
    ap.add_argument("--rebuild", type=int, default=0, metavar="N",
                    help="also rebuild the N newest events an older builder wrote")
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

    done = archive.attempted(args.archive)
    stale = archive.behind(args.archive, BUILD_VERSION) if args.rebuild else set()
    if stale:
        print(f"{len(stale)} events were built by an older builder; "
              f"rebuilding up to {args.rebuild} of them")
    # The indexer reads a post only where a slug could not place it and an
    # event's window holds its date -- ten posts on the blog, and cached like
    # every other fetch after the first run.
    chosen = plan(entries, done, args.backfill, args.rebuild, stale,
                  read=lambda url: lead(f.get(url)))
    if not chosen:
        print("No event with both pairings and standings could be identified.")
        return 0
    kept = archive.scraped(args.archive)
    print(f"Archive holds {len(kept)} events"
          + (f" and has rejected {len(done) - len(kept)}" if len(done) > len(kept) else "")
          + "; building "
          + ", ".join(f"{slug} ({ended})" for slug, _, ended in chosen))

    report: list[str] = []
    newest_event = None
    failed: list[str] = []
    for i, (slug, posts, ended) in enumerate(chosen):
        try:
            event, feed_posts, articles, lines = build_one(f, slug, posts, ended,
                                                           args.limit)
        except Exception as exc:
            # One event must not take the others down with it. A backfill spends
            # minutes per event and writes each one as it finishes, so a failure
            # on the seventh used to throw away the six already built and commit
            # nothing -- an hour of fetching for no archive at all.
            #
            # The newest event is the exception: it is what the feed is titled
            # after and what a scheduled run exists to publish, so failing to
            # build it is a failed run, not a skipped event.
            if i == 0:
                raise
            failed.append(slug)
            print(f"  FAILED to build {slug}: {type(exc).__name__}: {exc}")
            report += [f"### `{slug}` — **build failed**", "",
                       f"- `{type(exc).__name__}: {exc}`", ""]
            continue
        report += lines
        if not event:
            continue
        archive.write_event(args.archive, slug, event, feed_posts, articles)

        # Checked with the same script the site's own data must pass, one event
        # at a time, and backed out if it does not. The archive is a directory
        # of files a reader can be sent to, so it must not hold one the site
        # would refuse to serve -- and validating the whole archive afterwards
        # instead meant a single incoherent event failed the run and threw away
        # the ten beside it that were fine.
        if problem := coherence_problem(args.archive, slug):
            shutil.rmtree(archive.event_dir(args.archive, slug))
            archive.reject_event(args.archive, slug, problem)
            failed.append(slug)
            print(f"  REJECTED {slug}: {problem}")
            report += [f"### `{slug}` — **rejected, not published**", "",
                       f"- {problem}", ""]
            continue

        if i == 0:
            newest_event = event   # names the feed's channel
    if failed:
        # Never let a failure be visible only in a stack trace halfway up a log
        # that ends in success. It will be retried on the next backfill, because
        # the archive is the memory and nothing was written for it.
        print(f"{len(failed)} of {len(chosen)} events could not be built: "
              + ", ".join(failed))

    manifest = archive.build_manifest(args.archive)
    Path(args.manifest).write_text(archive.dumps(manifest, depth=2), encoding="utf-8")
    print(f"Manifest lists {len(manifest['events'])} events")

    # Who played what, sharded so a page can fetch one Duelist without the
    # other sixty-six thousand. Rebuilt whole every run, like the manifest:
    # it is derived from the archive and there is nothing in it to go stale
    # independently.
    shards = archive.build_players(args.archive)
    named = archive.write_players(args.archive, shards)
    print(f"Player index holds {named:,} Duelists in {len(shards)} files")

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
