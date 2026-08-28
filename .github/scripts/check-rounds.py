#!/usr/bin/env python3
"""Validate rounds.json: present, well-formed, and internally coherent.

rounds.json is fetched from JavaScript, so check-references.py cannot see it --
it deliberately ignores script bodies. Without this, the file could go missing
or be regenerated wrong and CI would stay green.

The coherence checks matter as much as the shape ones: the whole point of the
round data is that records add up. A generator bug that produced an 11-0
Duelist in round 3 would look plausible in a screenshot and be nonsense.
"""
import json
import sys
from pathlib import Path


def main(path="rounds.json"):
    p = Path(path)
    if not p.exists():
        print(f"  FAIL  {path} is missing")
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  FAIL  {path} is not valid JSON: {exc}")
        return 1

    problems = []
    for field in ("event", "format", "duelists", "swissRounds", "rounds"):
        if field not in data:
            problems.append(f"missing top-level field {field!r}")

    rounds = data.get("rounds") or []
    if not isinstance(rounds, list) or not rounds:
        problems.append("rounds is empty or not a list")
        rounds = []

    ids = [r.get("id") for r in rounds]
    if len(set(ids)) != len(ids):
        problems.append("duplicate round ids")

    live = [r for r in rounds if r.get("state") == "live"]
    if len(live) > 1:
        problems.append(f"{len(live)} rounds marked live, expected at most 1")

    for r in rounds:
        label = r.get("label", r.get("id", "?"))
        state = r.get("state")
        if state not in ("done", "live", "upcoming"):
            problems.append(f"{label}: unknown state {state!r}")
            continue

        if state == "upcoming":
            if r.get("pairings") or r.get("standings"):
                problems.append(f"{label}: an upcoming round must carry no data")
            continue

        pairings = r.get("pairings") or []
        standings = r.get("standings") or []
        if not pairings:
            problems.append(f"{label}: no pairings")
        if not standings:
            problems.append(f"{label}: no standings")

        # Nobody plays themselves, and nobody appears twice in one round.
        names = [n for p in pairings for n in (p.get("a"), p.get("b"))]
        if any(p.get("a") == p.get("b") for p in pairings):
            problems.append(f"{label}: a Duelist is paired against themselves")
        if len(set(names)) != len(names):
            problems.append(f"{label}: a Duelist appears in two pairings")

        # Records must add up to matches actually played.
        after = r.get("standingsAfter")
        if isinstance(after, int):
            for s in standings:
                rec = s.get("record", "")
                parts = rec.replace("–", "-").split("-")
                try:
                    played = int(parts[0]) + int(parts[1])
                except (ValueError, IndexError):
                    problems.append(f"{label}: unparseable record {rec!r}")
                    continue
                if played != after:
                    problems.append(
                        f"{label}: {s.get('name')} has {rec} but {after} rounds were played"
                    )

    if problems:
        for p_ in problems[:25]:
            print(f"  FAIL  {p_}")
        if len(problems) > 25:
            print(f"  ... and {len(problems) - 25} more")
        return 1

    playable = [r for r in rounds if r.get("state") != "upcoming"]
    print(f"  ok    {path}: {len(rounds)} rounds ({len(playable)} with data), records coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
