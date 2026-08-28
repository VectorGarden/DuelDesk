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

    # --- top cut: a bracket that looks plausible but is wrong would pass every
    # check above, so verify its structure explicitly. ---
    swiss_count = data.get("swissRounds")
    cut = [r for r in rounds if r.get("phase") == "Top cut"]
    swiss = [r for r in rounds if r.get("phase") == "Swiss"]

    for r in rounds:
        if r.get("phase") not in ("Swiss", "Top cut"):
            problems.append(f"{r.get('label', r.get('id'))}: phase is {r.get('phase')!r}, "
                            "expected 'Swiss' or 'Top cut'")

    if isinstance(swiss_count, int) and len(swiss) != swiss_count:
        problems.append(f"{len(swiss)} Swiss rounds present but swissRounds says {swiss_count}")

    played_cut = [r for r in cut if r.get("state") != "upcoming"]
    for r in played_cut:
        # Swiss is over in the cut, so standings must be the final ones.
        if isinstance(swiss_count, int) and r.get("standingsAfter") != swiss_count:
            problems.append(f"{r['label']}: standingsAfter is {r.get('standingsAfter')}, "
                            f"expected the final Swiss standings ({swiss_count})")
        # A bracket halves each round: 4 matches, then 2, then 1.
        n = len(r.get("pairings") or [])
        if n == 0 or (n & (n - 1)) != 0:
            problems.append(f"{r['label']}: {n} matches is not a power of two")

    # Cut results count, so entering records grow by one match per cut round
    # already played. The Top 8 enters on the Swiss record; the Top 4 one later.
    if isinstance(swiss_count, int):
        for depth, r in enumerate(played_cut):
            for p in r.get("pairings") or []:
                for who, rec in (("a", p.get("aRec")), ("b", p.get("bRec"))):
                    parts = str(rec).replace("–", "-").split("-")
                    try:
                        played = int(parts[0]) + int(parts[1])
                    except (ValueError, IndexError):
                        problems.append(f"{r['label']}: unparseable record {rec!r}")
                        continue
                    if played != swiss_count + depth:
                        problems.append(
                            f"{r['label']}: {p.get(who)} shows {rec} "
                            f"({played} matches), expected {swiss_count + depth}")

    # Advancing must add exactly one win and no losses.
    for earlier, later in zip(played_cut, played_cut[1:]):
        before = {}
        for p in earlier.get("pairings") or []:
            before[p.get("a")] = p.get("aRec")
            before[p.get("b")] = p.get("bRec")
        for p in later.get("pairings") or []:
            for who, rec in ((p.get("a"), p.get("aRec")), (p.get("b"), p.get("bRec"))):
                prev = before.get(who)
                if prev is None:
                    continue        # reported separately by the field check below
                try:
                    w0, l0 = (int(x) for x in str(prev).replace("–", "-").split("-")[:2])
                    w1, l1 = (int(x) for x in str(rec).replace("–", "-").split("-")[:2])
                except (ValueError, IndexError):
                    continue
                if (w1, l1) != (w0 + 1, l0):
                    problems.append(
                        f"{later['label']}: {who} went {prev} -> {rec}; advancing "
                        f"should add exactly one win")

    # Each cut round's field must come from the previous round's competitors.
    for earlier, later in zip(played_cut, played_cut[1:]):
        before = {n for p in earlier["pairings"] for n in (p.get("a"), p.get("b"))}
        after = {n for p in later["pairings"] for n in (p.get("a"), p.get("b"))}
        if not after <= before:
            stray = sorted(after - before)
            problems.append(f"{later['label']}: {stray} did not play in {earlier['label']}")
        if len(after) * 2 != len(before):
            problems.append(f"{later['label']}: {len(after)} Duelists from "
                            f"{len(before)} in {earlier['label']}, expected half")

    # "updated" must name the newest round that was actually posted. It drifted
    # silently once before, when adding the top cut left it an round behind.
    stamped = [r for r in rounds if r.get("posted")]
    if stamped and data.get("updated"):
        newest = stamped[-1]
        if not str(data["updated"]).endswith("Z") and "+" not in str(data["updated"]):
            problems.append(f"updated is not an absolute timestamp: {data['updated']!r}")
        else:
            hhmm = str(data["updated"])[11:16]
            if hhmm != newest.get("posted"):
                problems.append(
                    f"updated says {hhmm} but the newest posted round "
                    f"({newest['label']}) went up at {newest.get('posted')}")

    if problems:
        for p_ in problems[:25]:
            print(f"  FAIL  {p_}")
        if len(problems) > 25:
            print(f"  ... and {len(problems) - 25} more")
        return 1

    playable = [r for r in rounds if r.get("state") != "upcoming"]
    print(f"  ok    {path}: {len(rounds)} rounds ({len(playable)} with data), "
          f"{len(swiss)} Swiss + {len(cut)} cut, records and bracket coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
