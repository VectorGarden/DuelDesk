#!/usr/bin/env python3
"""Validate feed.xml: well-formed, and structurally a usable RSS 2.0 feed.

Well-formedness alone would pass a feed with no items, or items missing the
fields the site's own groupFeed() reads. This checks the shape too.
"""
import sys
import xml.etree.ElementTree as ET

REQUIRED_ITEM_FIELDS = ("title", "link", "pubDate")


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

    for n, item in enumerate(items, 1):
        title = item.find("title")
        label = (title.text or "").strip()[:48] if title is not None else f"item {n}"
        for field in REQUIRED_ITEM_FIELDS:
            node = item.find(field)
            if node is None or not (node.text or "").strip():
                problems.append(f"item {n} ({label!r}) missing non-empty <{field}>")

    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1

    print(f"  ok    {path}: well-formed RSS 2.0, {len(items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
