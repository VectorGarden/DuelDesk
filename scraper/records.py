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
    row-lists, one per round.

    A lower bound on rounds played, not the number itself -- see
    `last_appearance`, which is what records are derived from.
    """
    seen = Counter()
    for pairings in rounds:
        for row in pairings:
            for side in ("a", "b"):
                name = (row.get(side) or {}).get("name", "")
                if not is_placeholder(name):
                    seen[name] += 1
    return seen


def last_appearance(rounds: list[list[dict]],
                    round_numbers: list[int] | None = None) -> dict[str, int]:
    """The last round each player is paired in.

    Rounds played is this, not the number of pairings a player appears in. A bye
    prints no pairing row, so counting silently drops it: 35 of 765 Advanced
    entrants at YCS Montreal had at least one, ten of them two, and every such
    record came out a loss or two light.

    Byes are not an edge case at a YCS. Most are earned and fall at the start --
    31 of those 35 are absent only from rounds 1..k and paired continuously
    after -- and one more is handed out every round the field is odd.

    Taking the last round instead is right because a player is in the event from
    round one until they leave: absences before their last pairing are byes, and
    the last pairing is where they stopped. That agrees exactly with the round
    Konami states in its own drop annotations, for all 161 annotated entrants,
    which is two independent sources landing on the same number.

    `round_numbers` names the round each list belongs to. Without it the rounds
    are assumed to be 1..n, which undercounts if a pairings page is missing --
    an understated record rather than an invented one.
    """
    numbers = round_numbers if round_numbers is not None else range(1, len(rounds) + 1)
    seen: dict[str, int] = {}
    for number, pairings in zip(numbers, rounds):
        for row in pairings:
            for side in ("a", "b"):
                name = (row.get(side) or {}).get("name", "")
                if not is_placeholder(name):
                    seen[name] = max(seen.get(name, 0), number)
    return seen


def anchor_record(points: int, rounds: int) -> tuple[int, int, int] | None:
    """(wins, draws, losses) for a player on `points` after `rounds` matches.

    None where more than one record fits. Points are 3 for a win and 1 for a
    draw, so `3w + d = points` with `w + d + l = rounds`, and for small `rounds`
    that has exactly one non-negative solution:

        after 2 rounds:  6 -> 2-0-0    4 -> 1-1-0    3 -> 1-0-1
                         2 -> 0-2-0    1 -> 0-1-1    0 -> 0-0-2

    This exists because the blog does not publish standings after round one --
    a table of everyone at 3-0-0 says nothing -- so a series has to be anchored
    on the first table it does publish. Two rounds always resolve; three
    sometimes do not, because 3 points is one win and two losses or three draws.
    """
    fits = [(w, points - 3 * w, rounds - w - (points - 3 * w))
            for w in range(rounds + 1)]
    fits = [(w, d, l) for w, d, l in fits if d >= 0 and l >= 0]
    return fits[0] if len(fits) == 1 else None


def results_from_standings(series: list[list[dict]],
                           start_round: int = 0) -> dict[str, dict[str, int]]:
    """Exact W/D/L from consecutive per-round standings.

    Each round-on-round points delta is one match: +3 win, +1 draw, +0 loss.
    This is the only way to resolve draws, and it needs the standings pages for
    consecutive rounds -- a gap makes the rounds either side unusable.

    `start_round` is the round the first table reports on, and its points are
    read as a record of that many matches rather than as a baseline of zero.
    Without it the tally describes only the rounds the series happens to cover:
    a run beginning after round five would call a Duelist on 25 points 2-0-0,
    which is not a record of anything.

    A player is returned only where every round of the run is accounted for.
    Missing from a table in the middle, or a points move that is not a win, a
    draw or a loss, means a round nobody can attribute -- and a record short a
    round is not exact, it is just wrong by less.
    """
    if not series:
        return {}
    first = {r["name"]: r["points"] for r in series[0]
             if r.get("points") is not None and not is_placeholder(r.get("name", ""))}
    tally: dict[str, dict[str, int]] = {}
    for name, points in first.items():
        if (start := anchor_record(points, start_round)) is not None:
            tally[name] = {"wins": start[0], "draws": start[1], "losses": start[2]}

    previous = first
    for table in series[1:]:
        current = {r["name"]: r["points"] for r in table
                   if r.get("points") is not None and not is_placeholder(r.get("name", ""))}
        for name in list(tally):
            if name not in current or name not in previous:
                # Absent for a round: dropped, or a page that does not list
                # them. Either way this round cannot be attributed.
                del tally[name]
                continue
            delta = current[name] - previous[name]
            if delta == WIN_POINTS:
                tally[name]["wins"] += 1
            elif delta == DRAW_POINTS:
                tally[name]["draws"] += 1
            elif delta == 0:
                tally[name]["losses"] += 1
            else:
                del tally[name]      # a correction, or points from elsewhere
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
    # Whether this came from reading the standings round on round rather than
    # from counting appearances. Such a record does not depend on the pairings
    # at all, so the rule that withholds losses when pairings are missing must
    # not touch it. Not written to the archive -- see to_record.
    from_series: bool = False

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


def swiss_last_round(standings: list[dict]) -> int | None:
    """The final Swiss round, read off the standings' own status annotations.

    Every non-cut status names a round within Swiss, so the largest of them is
    the last Swiss round. "cut" is excluded: its rounds run past the end of
    Swiss into the bracket.

    Deliberately not `len(pairing_rounds)`. A record must not depend on how many
    pairings pages happened to be fetched -- with three of eleven in hand that
    would cap everyone at three rounds and delete real losses. This reads the
    event's own shape from a single page.
    """
    rounds = [r.get("statusRound") for r in standings
              if r.get("status") in ("drop", "playoffcut", "topx")
              and r.get("statusRound")]
    return max(rounds) if rounds else None


def rounds_played(row: dict, seen_through: int | None,
                  swiss_last: int | None) -> int | None:
    """How many Swiss rounds a player actually played.

    `seen_through` is the last round the player was paired in. The status
    annotation states the same thing outright, so it is preferred where present
    -- it is available for the full-Swiss table, where the two agree exactly. A "cut" player played all of Swiss and then some bracket; their
    Swiss record ends at the last Swiss round.

    With no annotation this is the last round paired -- including None, meaning
    never paired at all. Nothing is inferred from the points here: a
    player with more wins than rounds must stay partial, and quietly raising the
    round count to match would turn that into a fabricated unbeaten record.
    """
    status, stated = row.get("status"), row.get("statusRound")
    if status == "cut":
        stated = swiss_last
    elif status is None:
        stated = None
    if stated is None:
        return seen_through
    return max(stated, seen_through or 0)


def derive(standings: list[dict], pairing_rounds: list[list[dict]],
           *, event_date: str | None = None,
           standings_series: list[list[dict]] | None = None,
           series_from: int = 0,
           round_numbers: list[int] | None = None,
           ambiguous: set[str] | frozenset = frozenset()) -> list[Record]:
    """Best available record for every player in a final standings table.

    `ambiguous` names two Duelists the coverage does not distinguish -- one name
    seated at two tables in one round, with nothing to say which is which.
    Counting their appearances counts two people's, so nothing is derived for
    them: the points are reported and the record is left unknown.
    """
    draws_possible = bool(event_date) and event_date < DRAWS_ABOLISHED
    appearances = last_appearance(pairing_rounds, round_numbers)
    exact = (results_from_standings(standings_series, series_from)
             if standings_series else {})
    swiss_last = swiss_last_round(standings)

    out: list[Record] = []
    for row in standings:
        name, points = row.get("name", ""), row.get("points")
        if is_placeholder(name):
            continue
        played = appearances.get(name)

        if name in ambiguous:
            out.append(Record(name, points, None, None, None, None, "unknown"))
            continue

        if name in exact:                       # round-by-round deltas: exact
            e = exact[name]
            out.append(Record(name, points, e["wins"], e["draws"], e["losses"],
                              e["wins"] + e["draws"] + e["losses"], "derived",
                              from_series=True))
            continue

        if draws_possible or points is None:
            # 3 points is one win or three draws, and nothing here can tell them
            # apart. Report the points rather than pick one.
            out.append(Record(name, points, None, None, None, played, "unknown"))
            continue

        wins = points // WIN_POINTS
        played = rounds_played(row, played, swiss_last)
        if played is None or played < wins:
            # Never paired, or fewer appearances than wins (a bye awards points
            # without a pairing). Wins are still sound; losses are not.
            out.append(Record(name, points, wins, 0, None, played, "partial"))
            continue

        out.append(Record(name, points, wins, 0, played - wins, played, "derived"))
    return out
