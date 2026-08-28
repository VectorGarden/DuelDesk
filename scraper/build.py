#!/usr/bin/env python3
"""Turn scraped coverage posts into the rounds.json the site reads.

Everything upstream produces facts about individual posts. This assembles them
into one event: posts grouped by format, rounds ordered, records derived, and
each round given a state.

Two things it deliberately will not do:

  * Guess a format. A post that names neither Advanced nor Genesys is left out
    of both rather than assigned to one.
  * Invent a record. Losses need the rounds a Duelist actually played, so where
    the pairings for a round are missing the affected records come back partial
    and the page renders a ?.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from naming import clock
from records import derive

CUT_ORDER_BASE = 100          # cut rounds sort after every Swiss round


def cut_rank(label: str) -> int:
    """Sort key for a cut stage.

    Not parsed from the number, because the sequence runs Top 64 -> 32 -> 16 ->
    8 -> 4 -> Final: the numbers descend and the last has none at all. Ordering
    on the digit would put the Final first and reverse the bracket.
    """
    low = label.lower()
    # Semifinals and Top 4 are one stage under two names, as are quarterfinals
    # and Top 8. They must rank identically or the same round sorts into two
    # places depending on what the blog happened to call it that day.
    if "semi" in low:
        return cut_rank("top 4")
    if "quarter" in low:
        return cut_rank("top 8")
    if m := re.search(r"top\s*(\d+)", low):
        return 64 - int(m.group(1)).bit_length()
    if re.search(r"\bfinals?\b", low):
        return 64
    return 63


def round_key(post) -> tuple[str, Any]:
    """('swiss', n) or ('cut', label) -- or None when the post is not a round."""
    if isinstance(post.round, int):
        return ("swiss", post.round)
    if isinstance(post.round, str):
        return ("cut", post.round)
    return None


@dataclass
class Source:
    """One fetched post, with the URL it came from."""
    url: str
    post: Any                 # parse.Post
    posted: str | None = None # HH:MM


def pick_final_standings(candidates: list[Source]) -> Source:
    """Choose the end-of-Swiss table from the ones that name no round.

    An event publishes up to three, and they are different tables:

      "Final Standings After Day 1"   stops well short of the last round
      "Final Standings After Swiss"   the one we want
      "Final Standings"               published after the top cut

    The last is ordered by final placing, not by Swiss result -- at YCS Montreal
    its first seed holds 24 points and its third holds 27. Used as the round-11
    table it would show the Swiss standings in the wrong order.

    Previously this took whichever arrived last, making the choice depend on
    publication order.
    """
    def score(s: Source) -> tuple:
        low = s.post.title.lower()
        rows = s.post.table.rows if s.post.table else []
        return ("after swiss" in low, "day 1" not in low, len(rows))
    return max(candidates, key=score)


def status_by_player(candidates: list[Source]) -> dict[str, dict]:
    """Player -> status annotation, gathered from every standings table.

    Only the post-cut "Final Standings" carries these, and that is not the table
    we display, so the annotations have to be carried across to the one we do.
    They are facts about a player's event, not about a particular table, so this
    is a merge rather than a swap.
    """
    out: dict[str, dict] = {}
    for s in candidates:
        for row in (s.post.table.rows if s.post.table else []):
            if row.get("status"):
                out[row["name"]] = {"status": row["status"],
                                    "statusRound": row["statusRound"]}
    return out


def build_format(name: str, sources: list[Source]) -> dict | None:
    """Assemble one format's tournament."""
    by_round: dict[tuple, dict[str, Source]] = defaultdict(dict)
    floating_standings: list[Source] = []
    for s in sources:
        if s.post.kind not in ("pairings", "standings"):
            continue
        key = round_key(s.post)
        if key is None:
            # "Final Standings After Swiss" names no round, correctly -- it is
            # the table at the end of Swiss, not a round of its own. Held aside
            # and attached below, once the last Swiss round is known.
            if s.post.kind == "standings":
                floating_standings.append(s)
            continue
        by_round[key][s.post.kind] = s
    if not by_round:
        return None

    swiss_keys = sorted((k for k in by_round if k[0] == "swiss"), key=lambda k: k[1])
    statuses = status_by_player(floating_standings)
    if floating_standings and swiss_keys:
        last = swiss_keys[-1]
        by_round[last].setdefault("standings", pick_final_standings(floating_standings))
    cut_keys = sorted((k for k in by_round if k[0] == "cut"), key=lambda k: cut_rank(k[1]))
    swiss_count = swiss_keys[-1][1] if swiss_keys else 0

    # Records come from pairings, so the window has to match the table being
    # derived. A "standings after round 9" table must be read against rounds
    # 1-9 only: using every round would give a player who played 11 a 9-2
    # record in a nine-round table.
    #
    # The round numbers travel with the rows, because rounds played is read off
    # the last round a player appears in and positions are not rounds: drop the
    # page for round 2 and round 3 becomes "2", shortening every record after
    # it. Today the completeness guard below already rules that out -- if any
    # round up to the limit is missing, the window is short and the records go
    # partial anyway -- so passing them changes nothing on its own. It is here
    # so that the guard is the only thing holding the invariant, rather than the
    # guard plus an unstated assumption about list positions two files away.
    def pairings_through(limit: int | None) -> tuple[list[list[dict]], list[int]]:
        keys = [k for k in swiss_keys
                if "pairings" in by_round[k] and (limit is None or k[1] <= limit)]
        return ([by_round[k]["pairings"].post.table.rows for k in keys],
                [k[1] for k in keys])

    rounds = []
    for i, key in enumerate(swiss_keys + cut_keys):
        entry = by_round[key]
        is_cut = key[0] == "cut"
        label = key[1] if is_cut else f"R{key[1]}"
        rid = key[1].replace(" ", "") if is_cut else str(key[1])

        standings_post = entry.get("standings")
        standings: list[dict] = []
        if standings_post is not None:
            # Cut standings are the final Swiss ones, so they use every round.
            through = swiss_count if is_cut else key[1]
            window, window_rounds = pairings_through(through)
            table = standings_post.post.table.rows
            if through >= swiss_count:
                # A status names a round in the whole event, so it only reads
                # straight against a table covering all of Swiss. Against a
                # "standings after round 9" table it would credit a player who
                # went on to round 11 with two rounds they had not yet played.
                table = [{**r, **statuses.get(r["name"], {})} for r in table]
            recs = derive(table, window, round_numbers=window_rounds)

            # Losses are only sound when we hold the pairings for every round
            # the table covers. Reading the last round paired shrugs off a gap
            # in the middle -- a later page still fixes the round -- but not a
            # gap at the end, which makes every player look like they stopped
            # early and shortens their record. Those stay partial rather than
            # confidently wrong.
            complete = len(window) >= through
            if not complete:
                # A stated round does not depend on the pairings we hold, so
                # those records survive a gap that would sink counted ones.
                stated = {r["name"] for r in table if r.get("status")}
                for r in recs:
                    if r.name not in stated:
                        r.losses, r.confidence = None, "partial"
            by_name = {r.name: r for r in recs}
            for row in standings_post.post.table.rows:
                r = by_name.get(row["name"])
                standings.append({
                    "pos": row["rank"],
                    "name": row["name"],
                    "record": r.to_record() if r else None,
                    "points": row.get("points"),
                    "deck": None,
                    "pct": None,
                })

        pairings_post = entry.get("pairings")
        pairings = []
        if pairings_post is not None:
            for row in pairings_post.post.table.rows:
                pairings.append({
                    "table": row["table"],
                    "a": row["a"]["name"], "aRec": None, "aDeck": row["a"].get("deck"),
                    "b": row["b"]["name"], "bRec": None, "bDeck": row["b"].get("deck"),
                })

        source = (pairings_post or standings_post)
        rounds.append({
            "id": rid,
            "label": label,
            "phase": "Top cut" if is_cut else "Swiss",
            # A round we have data for has happened. Liveness is decided by the
            # caller, which knows which round is newest.
            "state": "done",
            "order": CUT_ORDER_BASE + cut_rank(key[1]) if is_cut else key[1],
            "tables": len(pairings) or None,
            # The clock, not the date: "pairings posted 16:38" is what a round
            # panel wants, and the sitemap carries the time.
            "posted": clock(source.posted) if source else None,
            "standingsAfter": swiss_count if is_cut else (key[1] if standings else None),
            "pairings": pairings,
            "standings": standings,
            "feature": None,
            "source": source.url if source else None,
        })

    # The newest round with pairings but no results yet is the one in progress.
    if rounds:
        rounds[-1]["state"] = "live"

    field = max((len(r["standings"]) for r in rounds), default=0)
    return {"format": name, "swissRounds": swiss_count, "duelists": field, "rounds": rounds}


def build_event(event: str, sources: list[Source], *,
                coverage_by: str = "Konami's official coverage",
                draws_possible: bool = False, updated: str | None = None) -> dict:
    by_format: dict[str, list[Source]] = defaultdict(list)
    unassigned = 0
    for s in sources:
        if s.post.fmt:
            by_format[s.post.fmt].append(s)
        else:
            unassigned += 1

    formats = [f for f in (build_format(name, group)
                           for name, group in sorted(by_format.items())) if f]
    return {
        "event": event,
        "coverageBy": coverage_by,
        "drawsPossible": draws_possible,
        "updated": updated,
        "formats": formats,
        "_unassigned": unassigned,     # posts naming no format; reported, not guessed
    }
