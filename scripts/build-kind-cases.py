#!/usr/bin/env python3
"""Freeze what every title shape in the archive classifies as.

Two implementations read this: parse.detect_kind, which wrote it, and the
page's kindFrom, which has to agree with it. The hand-written cases in
kinds.json say what the rule is *for*; this says what it currently answers,
over every shape of title the coverage has actually published.

One title per shape, where a shape is the title with its numbers flattened --
"Round 3 Pairings" and "Round 4 Pairings" are one question asked twice. That
takes 6,965 distinct titles to 4,262, and no title in the archive classifies
differently from its shape.

Run it when the archive has grown a kind of title it did not have before, and
read the diff: a line that changes is the rule changing its mind about a title
somebody published.

    python3 scripts/build-kind-cases.py
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

from archive import dumps          # noqa: E402
from parse import detect_kind      # noqa: E402

OUT = ROOT / "test/fixtures/kinds-archive.json"


def shape(title: str) -> str:
    return re.sub(r"\d+", "#", title.lower())


def main() -> None:
    titles: set[str] = set()
    for f in glob.glob(str(ROOT / "events/*/posts.json")):
        for post in json.loads(Path(f).read_text(encoding="utf-8")):
            if post.get("title"):
                titles.add(post["title"])

    held: dict[str, str] = {}
    for title in sorted(titles):
        held.setdefault(shape(title), title)

    cases = {title: detect_kind(title) for title in sorted(held.values())}
    OUT.write_text(dumps({"cases": cases}, depth=2), encoding="utf-8")
    print(f"{len(titles)} titles, {len(cases)} shapes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
