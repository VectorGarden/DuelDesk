#!/usr/bin/env python3
"""Rebuild a few events from live coverage and check what comes out.

The suite runs the parser against saved fixtures, and `check-rounds.py` runs
against the archive as committed. Neither reads a post. So a change to how
coverage is read is not tested against any coverage until a rebuild runs -- and
a rebuild commits and deploys each batch before its halt conditions are
checked, which twice cost the live site an event that had to be repaired in a
follow-up.

This is that check, before the merge instead of after. It rebuilds a handful of
events exactly as the scraper would -- including asking the indexer which posts
belong to them -- and fails if one of them stops being coherent.

The indexer is run rather than the committed post lists being reused, because
half of what this is guarding is the indexer. A change there alters which posts
an event is built from, and reading the list the last build wrote would hide
exactly that: the duplicate tables that cost YCS Philadelphia and YCS
Guadalajara arrived because a rule started handing events posts they had never
had.

Only events that pass today are demanded to pass: an event the archive is
already unhappy about is not this gate's business.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

from fetch import Fetcher, SITEMAP                         # noqa: E402
from index import (assign_events, parse_post_sitemap,      # noqa: E402
                   parse_sitemap_index)
from parse import detect_kind, lead                        # noqa: E402
import run as R                                            # noqa: E402

CHECKER = ROOT / ".github/scripts/check-rounds.py"

# Chosen for shape rather than for size, because what breaks is a shape:
#
#   a team event, whose rows are matches of three duels
#   a two-format event, whose posts must not cross between tournaments
#   a World Championship, whose cut is written unlike anybody else's
#   a WCQ with a Dragon Duel beside it
#   a YCS with a plain, deep Swiss and a full cut
#   an event whose coverage is patchy, where a reader is likeliest to guess
#
# Six is a compromise. It is enough to have caught both halts this exists for
# -- the 2026 World Championship's mislabelled semi-finals and the duplicate
# tables that cost YCS Philadelphia and YCS Guadalajara -- and few enough to
# keep a pull request under a couple of minutes.
SAMPLE = [
    "2026-04-team-ycs-las-vegas",
    "2026-north-america-wcq",
    "yu-gi-oh-tcg-world-championship-2026",
    "2019-north-america-wcq",
    "2026-08-quebec",
    "2023-05-ycs-philadelphia",
]


def checker():
    spec = importlib.util.spec_from_file_location("check_rounds", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coherent(check, path: Path) -> tuple[bool, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = check.check(str(path))
    return code == 0, out.getvalue().strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".scrape-state/cache")
    ap.add_argument("--out", default=".rebuild-sample")
    ap.add_argument("slugs", nargs="*", default=None)
    args = ap.parse_args()

    slugs = args.slugs or SAMPLE
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    check = checker()
    f = Fetcher(cache_dir=args.cache)

    print("  reading the sitemap and assigning events...", flush=True)
    entries = []
    for sm in parse_sitemap_index(f.get(SITEMAP)):
        entries += parse_post_sitemap(f.get(sm))
    assigned: dict[str, list[dict]] = {}
    # With the reader, because the run under test has one: an event whose
    # winner post is placed by its text has to be gated like any other.
    for rec in assign_events(entries, read=lambda url: lead(f.get(url))):
        if rec["event"] in slugs:
            assigned.setdefault(rec["event"], []).append(
                {"title": "", "url": rec["url"], "modified": rec["lastmod"],
                 "lastmod": rec["lastmod"], "kind": detect_kind(rec["slug"]),
                 "slug": rec["event"]})

    failed = []
    for slug in slugs:
        committed = ROOT / "events" / slug / "rounds.json"
        if not committed.exists():
            print(f"  skip  {slug}: not in the archive", flush=True)
            continue
        # Only what already passes. An event the archive is unhappy about is
        # somebody else's problem, and failing a pull request for it would
        # teach people to ignore this job.
        was_ok, _ = coherent(check, committed)
        if not was_ok:
            print(f"  skip  {slug}: does not pass today either", flush=True)
            continue

        posts = assigned.get(slug, [])
        if not posts:
            print(f"  skip  {slug}: the indexer gives it no posts", flush=True)
            continue
        ended = max((p["modified"][:10] for p in posts if p.get("modified")), default="")
        with redirect_stdout(io.StringIO()):
            event, _, _ = R.build_one(f, slug, posts, ended, len(posts))
        built = out / f"{slug}.json"
        built.write_text(json.dumps(event, indent=1), encoding="utf-8")

        ok, said = coherent(check, built)
        print(f"  {'ok  ' if ok else 'FAIL'}  {slug}", flush=True)
        if not ok:
            failed.append((slug, said))

    if failed:
        print("\nThese events pass in the archive and would not after this change:\n")
        for slug, said in failed:
            print(f"  {slug}\n    {said}\n")
        print("A rebuild would refuse them, and the site would lose them until it "
              "was fixed. That is what this job is for.")
        return 1
    print("\nEvery sampled event still builds coherently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
