#!/usr/bin/env python3
"""How often to ask the blog whether anything new has been posted.

Coverage arrives in bursts. During a YCS a round lands every fifty minutes or
so and each one brings pairings, standings and features; between events nothing
is posted for weeks. An hourly check is far too slow for the first case and far
more often than needed for the second.

GitHub cannot compute a cron at runtime, so the schedule is fixed at the fast
rate and most ticks are dropped here. The decision costs nothing: it reads the
clock and the previous run's state, and makes no network request. Only once it
says yes does anything reach out to the blog.

Liveness is judged by what the blog has actually been doing, not by a calendar.
A calendar rule was the obvious alternative -- YCS events run at weekends -- but
"the weekend" is not a fact about an event, it is a fact about a timezone: a
Saturday event in Japan begins on Friday afternoon UTC, and coverage of a North
American event runs well past midnight UTC into Monday. Recent posting is the
thing actually being tracked, and it needs no maintenance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# How long after the last new post the event still counts as running. Rounds are
# roughly fifty minutes and a day's coverage is continuous, so this only lapses
# overnight and at the end of an event -- which is the intent. It must comfortably
# exceed the longest gap within a day of coverage; if it does not, the cadence
# drops to quiet mid-event and takes up to QUIET_INTERVAL to recover.
LIVE_WINDOW = timedelta(hours=6)

# The quiet-day rate. Slightly under an hour so an hourly cadence cannot drift
# into a two-hour one: GitHub runs scheduled jobs late under load, and comparing
# elapsed time rather than the wall-clock minute means a tick that arrives at
# :12 instead of :03 still counts, rather than being dropped for the whole hour.
QUIET_INTERVAL = timedelta(minutes=55)

ZERO = timedelta(0)


def parse_time(value: str | None) -> datetime | None:
    """An ISO timestamp from a previous run, or None if absent or unreadable.

    State that cannot be read is state we do not have. Treating a malformed
    timestamp as missing makes the caller fall back to checking, which is the
    safe direction: a wasted request rather than a scraper that stops for good.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def should_check(now: datetime, last_change: datetime | None,
                 last_check: datetime | None) -> tuple[bool, str]:
    """(ask the blog now, which cadence said so).

    The cadence name is returned rather than logged here so the caller can put
    it in the run summary: knowing a tick was skipped is useless without knowing
    which rate it was skipped at.
    """
    since_change = None if last_change is None else now - last_change
    live = since_change is not None and ZERO <= since_change < LIVE_WINDOW
    if live:
        return True, "live"                 # every tick, for as long as it lasts

    if last_check is None:
        return True, "quiet"                # nothing to go on, so go and look

    since_check = now - last_check
    if since_check < ZERO:
        # The stored time is ahead of the clock, so one of them is wrong and the
        # elapsed comparison cannot be trusted. Check, and let this run replace it.
        return True, "quiet"
    return since_check >= QUIET_INTERVAL, "quiet"


def decide(state: dict, now: datetime) -> tuple[bool, str]:
    """should_check() against a state dict as it is stored on disk."""
    return should_check(now,
                        parse_time(state.get("last_change")),
                        parse_time(state.get("last_check")))


def record(state: dict, now: datetime, high: str | None) -> dict:
    """The state to store after a check that reached the blog.

    `last_change` only moves when the high-water mark does, because it is what
    "the event is still running" is measured from. Refreshing it on every check
    would make the scraper look permanently live once it had ever been live.

    A first sighting does not count as a change. With no previous mark to compare
    against we know only that we have never looked, not that anything was posted
    recently -- and calling that a change would put the scraper into the fast
    cadence for the whole live window every time the cache is rebuilt.
    """
    updated = dict(state)
    updated["last_check"] = now.isoformat()
    previous = state.get("high_water")
    if high is not None and previous is not None and high != previous:
        updated["last_change"] = now.isoformat()
    updated["high_water"] = high
    return updated
