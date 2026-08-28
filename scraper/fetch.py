#!/usr/bin/env python3
"""Fetch blog pages politely, with a disk cache and a cheap "is there anything
new?" gate.

The gate exists because the scraper is meant to run hourly. Coverage lands in
batches during an event and not at all between them, so almost every run has
nothing to do and should cost one request, not thousands.

    high-water mark:  the newest lastmod seen in the sitemap on the last run,
                      stored in state.json

A run fetches only the newest sub-sitemap, takes the maximum lastmod, and stops
if it has not moved. Note lastmod is a *modification* date -- editing an old
post bumps it -- so this answers "has anything changed?", not "is an event on".
That is the right question for a scraper.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

BASE = "https://yugiohblog.konami.com/"
SITEMAP = BASE + "wp-sitemap.xml"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Identifies the project and points at it, so an operator seeing this in their
# logs can tell what it is and who to contact.
USER_AGENT = ("DuelDesk/1.0 (+https://dueldesk.reizu.dev; "
              "coverage aggregator; contact via github.com/VectorGarden/DuelDesk)")
DELAY_SECONDS = 1.0          # between live requests
TIMEOUT = 30


# yugiohblog.konami.com sends only its leaf certificate, omitting the GeoTrust
# intermediate, so the chain to a trusted root cannot be built. Browsers and
# macOS curl hide this by fetching the intermediate from the leaf's AIA
# extension; Python does not, and fails verification outright -- on a clean
# GitHub runner as readily as anywhere else.
#
# The intermediate is checked in and supplied here. Verification stays fully on:
# this adds the missing link rather than skipping the check.
_INTERMEDIATES = Path(__file__).parent / "certs"


def _context_with_intermediates() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for pem in sorted(_INTERMEDIATES.glob("*.pem")):
        ctx.load_verify_locations(cafile=str(pem))
    return ctx


def _urlopen(url: str, user_agent: str) -> str:
    """Default transport.

    Tries ordinary verification first, so a correctly configured server -- or
    this one, if Konami ever fixes its chain -- needs nothing special. Only a
    verification failure falls back to the checked-in intermediate, and that
    path still verifies.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        if not isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise
        with urllib.request.urlopen(req, timeout=TIMEOUT,
                                    context=_context_with_intermediates()) as r:
            return r.read().decode("utf-8", errors="replace")


@dataclass
class Fetcher:
    """Transport is injectable so the cache, gate and politeness delay can be
    tested without a network -- which is also what lets them run in CI."""
    cache_dir: Path
    delay: float = DELAY_SECONDS
    user_agent: str = USER_AGENT
    transport: Callable[[str, str], str] = _urlopen
    _last_request: float = 0.0

    def __post_init__(self):
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")

    def get(self, url: str, *, refresh: bool = False) -> str:
        """Cached GET. Post content does not change once published, so a cache
        hit is the normal case and costs nothing."""
        cached = self._path(url)
        if cached.exists() and not refresh:
            return cached.read_text(encoding="utf-8")

        gap = self.delay - (time.monotonic() - self._last_request)
        if gap > 0:
            time.sleep(gap)
        body = self.transport(url, self.user_agent)
        self._last_request = time.monotonic()
        cached.write_text(body, encoding="utf-8")
        return body

    def cache_size(self) -> int:
        return len(list(self.cache_dir.glob("*.html")))


def newest_sitemap(index_xml: str) -> str:
    """The sub-sitemap WordPress is currently filling, which is the last one."""
    locs = [e.text for e in ET.fromstring(index_xml).findall(".//s:loc", NS) if e.text]
    posts = [l for l in locs if "posts-post" in l]
    if not posts:
        raise ValueError("sitemap index lists no post sub-sitemaps")
    return max(posts, key=lambda l: int(l.rsplit("-", 1)[-1].split(".")[0]))


def parse_lastmod(text: str | None) -> datetime | None:
    """One sitemap <lastmod> as an instant, or None if it cannot be read.

    The blog writes them with an offset -- 2026-08-16T11:07:30-07:00 -- but a
    date alone is valid sitemap syntax too, so both are accepted, as is a "Z"
    suffix -- fromisoformat has taken that since 3.11, and a test pins it so a
    Python that cannot says so out loud rather than dropping every stamp.

    A stamp that parses as none of those is dropped rather than raised on: one
    malformed entry among thousands must not stop the scraper seeing the rest.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def max_lastmod(sitemap_xml: str) -> str | None:
    """The newest <lastmod> in a sitemap, to the second, normalised to UTC.

    This is the whole update gate: the scraper decides there is new coverage by
    watching this value change. It used to be truncated to ten characters -- the
    date -- which made it blind to everything an event actually does. One
    sub-sitemap holds 39 posts with 39 distinct timestamps and 5 distinct dates,
    and its busiest day collapsed 34 posts into a single value. On that day the
    first post would have moved the mark and the other 33 would each have been
    reported as "nothing new", so the scraper would have fetched once and gone
    quiet until midnight.

    Comparison is by instant, not by text. The stamps carry real offsets, and
    sorting them as strings gets it backwards whenever two offsets differ:
    01:00-07:00 is 08:00 UTC and later than 07:00+00:00, but sorts before it.

    Normalising to UTC also keeps the stored mark stable, so a mark that has not
    moved cannot look like it has because the blog's offset shifted over a
    daylight-saving boundary.
    """
    stamps = [parse_lastmod(e.text)
              for e in ET.fromstring(sitemap_xml).findall(".//s:lastmod", NS)]
    stamps = [s for s in stamps if s]
    if not stamps:
        return None
    return max(stamps).astimezone(timezone.utc).isoformat()


def load_state(path: Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(path: Path, state: dict) -> None:
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def check_for_updates(fetcher: Fetcher, state_path: Path) -> tuple[bool, str | None]:
    """(is there anything new, newest lastmod). Costs two small requests."""
    index = fetcher.get(SITEMAP, refresh=True)
    newest = fetcher.get(newest_sitemap(index), refresh=True)
    high = max_lastmod(newest)
    previous = load_state(state_path).get("high_water")
    return (high is not None and high != previous), high
