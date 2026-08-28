#!/usr/bin/env python3
"""Validate feed.xml: well-formed, and structurally a usable RSS 2.0 feed.

Well-formedness alone would pass a feed with no items, or items missing the
fields the site's own groupFeed() reads. This checks the shape too.
"""
import sys
import xml.etree.ElementTree as ET

REQUIRED_ITEM_FIELDS = ("title", "link", "pubDate")

# The feed reaches subscribers with no page around it, and aggregators strip
# <copyright>, so whatever it claims about itself has to ride on the parts a
# reader displays: the channel title and description, and each item's own title.
#
# There are two honest feeds and this checks whichever it is handed.
#
#   sample -- invented results, and every item says so, or it reads as coverage
#   real   -- Konami's coverage, indexed and linked, and it must credit them
#
# What it must never be is half of each. A feed with some items marked [sample]
# among real ones is worse than either: a reader who checks one unmarked item
# and finds it genuine has no reason to doubt the next.
SAMPLE_MARKER = "[sample]"

# A real feed must name whose coverage it is indexing.
ATTRIBUTION_TERMS = ("konami",)

# A real item must send the reader to the source, not in a circle back to us.
SITE_PREFIX = "https://dueldesk.reizu.dev"


def main(path="feed.xml"):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print(f"  FAIL  {path} is not well-formed XML: {exc}")
        return 1

    problems = []
    if root.tag != "rss":
        problems.append(f"root element is <{root.tag}>, expected <rss>")

    channel = root.find("channel")
    if channel is None:
        problems.append("no <channel> element")
        items = []
    else:
        for field in ("title", "link", "description"):
            node = channel.find(field)
            if node is None or not (node.text or "").strip():
                problems.append(f"<channel> missing non-empty <{field}>")
        items = channel.findall("item")
        if not items:
            problems.append("<channel> contains no <item> elements")

    marked = [(item.findtext("title") or "").lower().lstrip().startswith(SAMPLE_MARKER)
              for item in items]
    sample_feed = any(marked)

    if items and sample_feed and not all(marked):
        problems.append(f"{marked.count(False)} of {len(items)} items are not marked "
                        f"{SAMPLE_MARKER} while the rest are -- a feed must be all "
                        "sample or all real, never a mix")

    if channel is not None:
        ch_title = (channel.findtext("title") or "")
        ch_desc = (channel.findtext("description") or "")
        blurb = f"{ch_title} {ch_desc}".lower()
        if sample_feed:
            if "sample" not in ch_title.lower():
                problems.append("<channel><title> does not identify the feed as sample data")
            if "sample" not in ch_desc.lower():
                problems.append("<channel><description> does not identify the feed as sample data")
        else:
            if "sample" in blurb:
                problems.append("<channel> calls the feed sample data, but no item is "
                                f"marked {SAMPLE_MARKER}")
            if not any(term in blurb for term in ATTRIBUTION_TERMS):
                problems.append("<channel> does not say whose coverage this indexes")

    for n, item in enumerate(items, 1):
        title = item.find("title")
        label = (title.text or "").strip()[:48] if title is not None else f"item {n}"
        for field in REQUIRED_ITEM_FIELDS:
            node = item.find(field)
            if node is None or not (node.text or "").strip():
                problems.append(f"item {n} ({label!r}) missing non-empty <{field}>")

        desc = (item.findtext("description") or "").lower()
        if sample_feed and "sample data" not in desc:
            problems.append(f"item {n} ({label!r}) description does not say it is sample data")
        if not sample_feed:
            link = (item.findtext("link") or "")
            if link.startswith(SITE_PREFIX):
                problems.append(f"item {n} ({label!r}) links back to this site; a real "
                                "item must link to the coverage it is indexing")

    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1

    kind = "all marked as sample data" if sample_feed else "indexing external coverage"
    print(f"  ok    {path}: well-formed RSS 2.0, {len(items)} items, {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
