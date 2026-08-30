#!/usr/bin/env python3
"""The archive: one directory per event, plus a manifest naming them all.

One event's coverage is about 1.5MB of JSON, so the archive cannot be a single
file -- 68 events of it would be a 100MB download to look at one round. Each
event gets its own directory and the page fetches only the one being read.

    events.json                       every event, small enough to load first
    events/<slug>/rounds.json         that event's rounds, the page's payload
    events/<slug>/posts.json          its coverage posts, for rebuilding the feed

posts.json exists because the feed spans events. A run backfills a few events at
a time, so a feed built from only what that run fetched would drop every event
the previous run covered. Keeping each event's posts beside its rounds makes the
feed a function of the archive rather than of the last run.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ARCHIVE = "events"
MANIFEST = "events.json"


def lean(event: dict) -> dict:
    """The event with nulls dropped from its table rows.

    Pairings and standings rows are 99% of the file and most of each row is
    fields that do not apply: no deck type was published, no points column
    existed, nothing could be derived. Written out in full, YCS Columbus is
    10.1MB of JSON to describe 17 rounds, and the archive would reach a
    quarter of a gigabyte before it was half filled.

    Only the rows, and only nulls. Every structural field stays exactly as
    built, including the ones that are legitimately null -- a tournament with no
    format name says so rather than omitting the key, because the checker's
    "does this file describe itself" rule has to keep meaning something.

    Safe for the page because it never distinguishes the two: every place that
    tests one of these fields tests for null and undefined together.
    """
    out = copy.deepcopy(event)
    drop = lambda row: {k: v for k, v in row.items() if v is not None}
    for fmt in out.get("formats") or []:
        for rnd in fmt.get("rounds") or []:
            for key in ("pairings", "standings"):
                rnd[key] = [drop(r) for r in rnd.get(key) or []]
    return out


def dumps(obj: dict, *, pretty: bool = False) -> str:
    """One JSON writer, so every file the site reads is written the same way.

    Compact by default. Indentation is 60% of an event file and nobody reads a
    twenty-thousand-row table by eye; the manifest, which someone might, is the
    one written pretty.
    """
    sep = None if pretty else (",", ":")
    return json.dumps(obj, indent=2 if pretty else None, separators=sep,
                      ensure_ascii=False) + "\n"


def event_dir(root: str | Path, slug: str) -> Path:
    return Path(root) / slug


def rounds_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "rounds.json"


def posts_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "posts.json"


def write_event(root: str | Path, slug: str, event: dict, posts: list[dict]) -> Path:
    d = event_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    out = rounds_path(root, slug)
    out.write_text(dumps(lean(event)), encoding="utf-8")
    posts_path(root, slug).write_text(dumps(posts, pretty=True), encoding="utf-8")
    return out


def rejected_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "rejected.json"


def reject_event(root: str | Path, slug: str, reason: str) -> None:
    """Record that an event was built and would not do, and why.

    Without this the backfill cannot get past a bad event. A rejected event
    leaves nothing in the archive, so the next run does not count it as
    attempted, so it is picked again -- and because the plan takes the newest
    events missing from the archive, the same failures are retried first every
    time and the run never reaches the ones behind them. Five batches of ten
    landed 21 events and then stopped dead: every batch was spending itself on
    the same seven rejections.

    Kept in the archive rather than a state file, and readable, so what the
    archive is missing and why is a thing in the repository rather than a line
    in a log that expires. Delete the file to try again.
    """
    d = event_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    rejected_path(root, slug).write_text(
        dumps({"slug": slug, "reason": reason}, pretty=True), encoding="utf-8")


def attempted(root: str | Path) -> set[str]:
    """Slugs the archive has already built, whether or not it kept them.

    This is the backfill's memory. Read off the files rather than kept in a
    state file, so it cannot disagree with what is actually there.
    """
    root = Path(root)
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir()
            if (d / "rounds.json").is_file() or (d / "rejected.json").is_file()}


def scraped(root: str | Path) -> set[str]:
    """Slugs the archive holds coverage for. What the manifest is built from."""
    root = Path(root)
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if (d / "rounds.json").is_file()}


def count_posts(root: str | Path, slug: str) -> int:
    p = posts_path(root, slug)
    return len(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else 0


def behind(root: str | Path, version: int) -> set[str]:
    """Slugs whose coverage was written by an older builder.

    Read off the files rather than kept in a state file, exactly as `attempted`
    is, so it cannot disagree with what is actually there. A file with no
    `built` at all predates the marker and is behind by definition.
    """
    out = set()
    for slug in scraped(root):
        try:
            event = json.loads(rounds_path(root, slug).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if event.get("built", 0) != version:
            out.add(slug)
    return out


def summarise(slug: str, event: dict, posts: int = 0) -> dict:
    """The manifest's entry for one event: enough to list and choose it, and
    nothing that would make the manifest grow with the coverage."""
    return {
        "slug": slug,
        "event": event.get("event"),
        # In the manifest as well, so the event list can say where an event was
        # without fetching the whole of it.
        **({"location": event["location"]} if event.get("location") else {}),
        "updated": event.get("updated"),
        "sample": event.get("sample", False),
        "ongoing": event.get("ongoing", False),
        "coverageBy": event.get("coverageBy"),
        "path": f"{ARCHIVE}/{slug}/rounds.json",
        # How many posts the event has, not the posts themselves. The page
        # lists every event but fetches an event's coverage only when it is
        # opened, so without this it could only count what it had already
        # loaded -- and a total that climbs as you read is worse than none.
        "postCount": posts,
        "formats": [{"format": f.get("format"),
                     "swissRounds": f.get("swissRounds"),
                     "duelists": f.get("duelists"),
                     "rounds": len(f.get("rounds") or [])}
                    for f in event.get("formats") or []],
    }


def build_manifest(root: str | Path) -> dict:
    """Every built event, newest first.

    Sorted on `updated` descending with the slug breaking ties, so two events
    finishing on the same day list in a stable order rather than in whatever
    order the filesystem returned.
    """
    events = []
    for slug in sorted(scraped(root)):
        event = json.loads(rounds_path(root, slug).read_text(encoding="utf-8"))
        events.append(summarise(slug, event, count_posts(root, slug)))
    events.sort(key=lambda e: (e["updated"] or "", e["slug"]), reverse=True)
    return {"events": events}


def feed_items(root: str | Path, limit: int) -> list[dict]:
    """The newest coverage posts across the whole archive.

    Capped, because the archive runs to thousands of posts and the feed is a
    what's-new list, not a catalogue. The events.json manifest is how the rest
    is reached.
    """
    items: list[dict] = []
    for slug in scraped(root):
        p = posts_path(root, slug)
        if p.is_file():
            items += json.loads(p.read_text(encoding="utf-8"))
    items.sort(key=lambda i: i.get("modified") or "", reverse=True)
    return items[:limit]
