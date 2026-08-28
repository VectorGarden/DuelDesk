#!/usr/bin/env python3
"""Validate feed.xml: well-formed, and structurally a usable RSS 2.0 feed.

Well-formedness alone would pass a feed with no items, or items missing the
fields the site's own groupFeed() reads. This checks the shape too.
"""
import sys
import xml.etree.ElementTree as ET

REQUIRED_ITEM_FIELDS = ("title", "link", "pubDate")

# The feed publishes invented tournament results to anyone who subscribes, and
# aggregators strip <copyright>. The disclaimer has to ride along on the parts a
# reader actually displays, or the data reads as genuine coverage.
SAMPLE_MARKER = "[sample]"


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

    if channel is not None:
        ch_title = (channel.findtext("title") or "")
        ch_desc = (channel.findtext("description") or "")
        if "sample" not in ch_title.lower():
            problems.append("<channel><title> does not identify the feed as sample data")
        if "sample" not in ch_desc.lower():
            problems.append("<channel><description> does not identify the feed as sample data")

    for n, item in enumerate(items, 1):
        title = item.find("title")
        label = (title.text or "").strip()[:48] if title is not None else f"item {n}"
        for field in REQUIRED_ITEM_FIELDS:
            node = item.find(field)
            if node is None or not (node.text or "").strip():
                problems.append(f"item {n} ({label!r}) missing non-empty <{field}>")

        title_text = (item.findtext("title") or "")
        if not title_text.lower().lstrip().startswith(SAMPLE_MARKER):
            problems.append(f"item {n} ({label!r}) title is not marked {SAMPLE_MARKER}")
        if "sample data" not in (item.findtext("description") or "").lower():
            problems.append(f"item {n} ({label!r}) description does not say it is sample data")

    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1

    print(f"  ok    {path}: well-formed RSS 2.0, {len(items)} items, all marked as sample data")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
