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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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


def _urlopen(url: str, user_agent: str) -> str:
    """Default transport. TLS verification is left at the default on purpose --
    never disable it to work around a local trust-store problem."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
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


def max_lastmod(sitemap_xml: str) -> str | None:
    stamps = [(e.text or "")[:10] for e in ET.fromstring(sitemap_xml).findall(".//s:lastmod", NS)]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


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
