#!/usr/bin/env python3
"""Turn published points into win-loss records.

Points are match points: 3 for a win, 1 for a draw, 0 for a loss. Modern events
have no draws -- verified against 935 players across two formats, every score
divisible by 3 -- so wins are exact:

    wins = points // 3

Losses are not in any published table. Pairings pages carry no results column,
but they do say who played, and a player's appearances across a format's rounds
is exactly the rounds they played:

    losses = rounds_played - wins

That distinction matters: 45% of expected matches at YCS Montreal were never
played because entrants dropped, so `swiss_rounds - wins` would invent losses
for hundreds of them.

Before 2025-09-02 draws existed, and 3 points is either one win or three draws.
Pairings cannot separate those. Consecutive standings can -- a round-on-round
gain of 3, 1 or 0 is a win, draw or loss -- so that path is used when the pages
exist and the record is reported as unknown when they do not.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# The blog redacts some entrants. These are not players and must not be counted
# as an appearance for anyone.
PLACEHOLDER = re.compile(r"^[\W_]*$")

# Ties were removed from tournament policy on this date.
DRAWS_ABOLISHED = "2025-09-02"

WIN_POINTS, DRAW_POINTS = 3, 1


def is_placeholder(name: str) -> bool:
    return not name or bool(PLACEHOLDER.match(name))


def count_appearances(rounds: list[list[dict]]) -> Counter:
    """How many rounds each player was paired in. `rounds` is a list of pairing
    row-lists, one per round."""
    seen = Counter()
    for pairings in rounds:
        for row in pairings:
            for side in ("a", "b"):
                name = (row.get(side) or {}).get("name", "")
                if not is_placeholder(name):
                    seen[name] += 1
    return seen


def results_from_standings(series: list[list[dict]]) -> dict[str, dict[str, int]]:
    """Exact W/D/L from consecutive per-round standings.

    Each round-on-round points delta is one match: +3 win, +1 draw, +0 loss.
    This is the only way to resolve draws, and it needs the standings pages for
    consecutive rounds -- a gap makes the rounds either side unusable.
    """
    tally: dict[str, dict[str, int]] = {}
    previous: dict[str, int] = {}
    for i, table in enumerate(series):
        current = {r["name"]: r["points"] for r in table
                   if r.get("points") is not None and not is_placeholder(r.get("name", ""))}
        if i:
            for name, points in current.items():
                if name not in previous:
                    continue
                delta = points - previous[name]
                t = tally.setdefault(name, {"wins": 0, "draws": 0, "losses": 0})
                if delta == WIN_POINTS:
                    t["wins"] += 1
                elif delta == DRAW_POINTS:
                    t["draws"] += 1
                elif delta == 0:
                    t["losses"] += 1
                # anything else is a correction or a bye; leave it uncounted
        previous = current
    return tally


@dataclass
class Record:
    name: str
    points: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    rounds_played: int | None
    confidence: str          # derived | partial | unknown

    def label(self, draws_possible: bool = False) -> str:
        """Record-shaped always, with ? for what is not known.

        Matches how the page renders it, so the scraper and the site describe
        the same record the same way. "10-?" and "?-?" are different claims:
        one knows the wins, the other knows neither.
        """
        part = lambda v: "?" if v is None else str(v)
        core = [part(self.wins), part(self.losses)]
        if draws_possible or self.draws:
            core.append(part(self.draws))
        return "–".join(core)

    def to_record(self) -> dict:
        """The shape rounds.json stores, so the page can format it."""
        return {"wins": self.wins, "losses": self.losses,
                "draws": self.draws, "confidence": self.confidence}


def derive(standings: list[dict], pairing_rounds: list[list[dict]],
           *, event_date: str | None = None,
           standings_series: list[list[dict]] | None = None) -> list[Record]:
    """Best available record for every player in a final standings table."""
    draws_possible = bool(event_date) and event_date < DRAWS_ABOLISHED
    appearances = count_appearances(pairing_rounds)
    exact = results_from_standings(standings_series) if standings_series else {}

    out: list[Record] = []
    for row in standings:
        name, points = row.get("name", ""), row.get("points")
        if is_placeholder(name):
            continue
        played = appearances.get(name)

        if name in exact:                       # round-by-round deltas: exact
            e = exact[name]
            out.append(Record(name, points, e["wins"], e["draws"], e["losses"],
                              e["wins"] + e["draws"] + e["losses"], "derived"))
            continue

        if draws_possible or points is None:
            # 3 points is one win or three draws, and nothing here can tell them
            # apart. Report the points rather than pick one.
            out.append(Record(name, points, None, None, None, played, "unknown"))
            continue

        wins = points // WIN_POINTS
        if played is None or played < wins:
            # Never paired, or fewer appearances than wins (a bye awards points
            # without a pairing). Wins are still sound; losses are not.
            out.append(Record(name, points, wins, 0, None, played, "partial"))
            continue

        out.append(Record(name, points, wins, 0, played - wins, played, "derived"))
    return out
