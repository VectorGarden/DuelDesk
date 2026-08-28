#!/usr/bin/env python3
"""Build the site's RSS feed from the coverage posts a scrape actually saw.

The feed the site shipped with was generated alongside the sample tournament and
says so in every field: its channel is titled SAMPLE DATA and each item is
prefixed [Sample]. That was honest while the round data was invented too. Serving
it beside real standings would not be -- the page would show real Duelists and
real records under headlines about people who do not exist.

Items link to Konami's post, never to a copy of it here. The feed says what was
published and where to read it; the coverage itself stays on their site.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

SITE = "https://dueldesk.reizu.dev/"

# What each post kind is called in the feed. The site groups on these, and they
# are the same words the page's filter buttons use.
LABELS = {
    "pairings": "Pairings",
    "standings": "Standings",
    "feature": "Feature match",
    "deck": "Deck profile",
    "result": "Results",
    "news": "News",
}

ATTRIBUTION = ("Round-by-round coverage of Yu-Gi-Oh! TCG events, indexed from "
               "Konami's official event coverage. Every item links to the "
               "original post. Not affiliated with or endorsed by Konami.")

RIGHTS = ("Coverage is Konami's. This feed indexes and links to it and claims "
          "no rights in it.")


def rfc822(stamp: str | None) -> str | None:
    """RSS wants RFC 822 dates; the sitemap publishes ISO 8601."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    # Not strftime("%a, %d %b %Y"): that renders weekday and month names in the
    # running locale, and a feed reader parsing "sam., 16 août" gets nothing.
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    utc = parsed.astimezone(timezone.utc)
    return (f"{days[utc.weekday()]}, {utc.day:02d} {months[utc.month - 1]} "
            f"{utc.year} {utc:%H:%M:%S} +0000")


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def build_feed(event: str, items: list[dict], *, updated: str | None = None,
               site: str = SITE) -> str:
    """RSS 2.0 for one event's coverage.

    Each item is {title, url, modified, kind}. Items with no title or no link
    are dropped: an entry a reader cannot open is worse than one fewer entry.
    """
    usable = [i for i in items if (i.get("title") or "").strip() and i.get("url")]
    usable.sort(key=lambda i: i.get("modified") or "", reverse=True)

    built = rfc822(updated) or rfc822(
        max((i.get("modified") or "" for i in usable), default="") or None)

    body = []
    for item in usable:
        label = LABELS.get(item.get("kind"), "Coverage")
        when = rfc822(item.get("modified"))
        body.append(
            "    <item>\n"
            f"      <title>{esc(item['title'])}</title>\n"
            f"      <link>{esc(item['url'])}</link>\n"
            f"      <guid isPermaLink=\"true\">{esc(item['url'])}</guid>\n"
            f"      <category>{esc(label)}</category>\n"
            + (f"      <pubDate>{when}</pubDate>\n" if when else "")
            + f"      <description>{esc(label)} from {esc(event)}, "
              "published by Konami. Follow the link for the original post."
              "</description>\n"
            "    </item>")

    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>Duel Desk — {esc(event)}</title>\n"
            f"    <link>{esc(site)}</link>\n"
            f'    <atom:link href="{esc(site)}feed.xml" rel="self" '
            'type="application/rss+xml"/>\n'
            f"    <description>{esc(ATTRIBUTION)}</description>\n"
            "    <language>en</language>\n"
            + (f"    <lastBuildDate>{built}</lastBuildDate>\n" if built else "")
            + "    <generator>Duel Desk</generator>\n"
            f"    <copyright>{esc(RIGHTS)}</copyright>\n"
            + "\n".join(body) + ("\n" if body else "")
            + "  </channel>\n</rss>\n")
