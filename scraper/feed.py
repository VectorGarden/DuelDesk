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
import unicodedata
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


def headline_from_url(url: str, title: str) -> str | None:
    """The part of a post's slug its title does not already say.

    Konami titles some posts with nothing but the event and where and when it
    was: two of YCS Montreal's are both headed "YCS Montreal, Quebec 2026", and
    which is the main event information and which the public event information
    is only in the slug. Split on the event name that leaves ", Quebec 2026" as
    the headline -- a comma, a place and a year, describing no post in
    particular and the same for both of them.

    So the slug is read instead, minus the words the title already used:

        ycs-montreal-quebec-2026-main-event-information
        YCS Montreal, Quebec 2026            -> Main Event Information

    Accents are folded for the comparison only. The blog writes Montreal both
    ways, and a slug cannot carry one.
    """
    said = {_fold(w) for w in re.findall(r"[\w']+", title)}
    words = [w for w in url.rstrip("/").rsplit("/", 1)[-1].split("-") if w]
    while words and _fold(words[0]) in said:
        words.pop(0)
    return " ".join(w.capitalize() for w in words) if words else None


def _fold(word: str) -> str:
    """Lowercased and stripped of accents, for comparing a title to a slug."""
    return "".join(c for c in unicodedata.normalize("NFKD", word.lower())
                   if not unicodedata.combining(c))


def titled(event: str, title: str, url: str = "") -> str:
    """'Event: headline', which is how every item in this feed is written.

    A feed item stands alone in a reader, with no page around it to say which
    tournament it belongs to, so the event has to be in the title. The site reads
    the same convention to group items, and where the convention was missing it
    grouped by category instead: a deck list post titled "YCS Montreal Advanced
    Format Top 32 Deck Lists" has no colon, so it became an event called "Deck
    profile", and a feature match split at its own colon into an event called
    "Genesys Format Round 4 Feature Match". One tournament showed up as eight.
    """
    title = title.strip()
    if title.startswith(f"{event}:"):
        return title
    if title.startswith(event):
        # Names it already, just without the separator the convention needs.
        rest = title[len(event):].lstrip(" -–—:")
        # A headline that opens with a comma is not a headline: the title is
        # still naming the event -- "YCS Montreal" then ", Quebec 2026" -- and
        # what the post is about is in the slug instead. Two of Montreal's read
        # "YCS Montréal: , Quebec 2026", identically, for different posts.
        if rest.startswith(",") and (from_slug := headline_from_url(url, title)):
            return f"{event}: {from_slug}"
        return f"{event}: {rest}".rstrip(": ")
    return f"{event}: {title}"


def build_feed(event: str, items: list[dict], *, updated: str | None = None,
               site: str = SITE) -> str:
    """RSS 2.0 for the archive's newest coverage.

    Each item is {title, url, modified, kind, format} and may carry {event, slug}
    naming the tournament it belongs to; `event` is the fallback for items that
    do not, and titles the channel. Items with no title or no link are dropped:
    an entry a reader cannot open is worse than one fewer.
    """
    usable = [i for i in items if (i.get("title") or "").strip() and i.get("url")]
    usable.sort(key=lambda i: i.get("modified") or "", reverse=True)

    built = rfc822(updated) or rfc822(
        max((i.get("modified") or "" for i in usable), default="") or None)

    body = []
    for item in usable:
        label = LABELS.get(item.get("kind"), "Coverage")
        when = rfc822(item.get("modified"))
        # Per item, because the feed spans events now. Falling back to the
        # channel's name keeps a single-event feed reading exactly as before.
        name = item.get("event") or event
        body.append(
            "    <item>\n"
            f"      <title>{esc(titled(name, item['title'], item['url']))}</title>\n"
            f"      <link>{esc(item['url'])}</link>\n"
            f"      <guid isPermaLink=\"true\">{esc(item['url'])}</guid>\n"
            f"      <category>{esc(label)}</category>\n"
            # The same answer again, as an identifier rather than a label.
            # The label above is prose for a feed reader; this is the kind the
            # scraper actually read -- from the title, the slug and the table
            # on the page, in that order of correction -- so the site does not
            # have to guess it back out of a headline. It guessed wrong on 309
            # posts, because the archive's older titles are "WCQ" and "Public
            # Events" while the slug says round-1-feature-match.
            + (f'      <category domain="kind">{esc(item["kind"])}</category>\n'
               if item.get("kind") else "")
            # A third category, namespaced with domain= as RSS intends, so the
            # site can filter coverage by format without parsing the headline.
            # Absent for posts that belong to no format -- an announcement is
            # about the event, not about one of its tournaments -- and the site
            # keeps those visible whichever format is selected.
            + (f'      <category domain="format">{esc(item["format"])}</category>\n'
               if item.get("format") else "")
            # The event's archive slug, so the site can take a feed item to the
            # event it belongs to without matching on the display name. Names
            # are for reading; this is the identifier.
            + (f'      <category domain="event">{esc(item["slug"])}</category>\n'
               if item.get("slug") else "")
            + (f"      <pubDate>{when}</pubDate>\n" if when else "")
            + f"      <description>{esc(label)} from {esc(name)}, "
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
