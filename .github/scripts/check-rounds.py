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


def check_rounds(label, rounds, swiss_count):
    """Every check that applies within one format's tournament."""
    problems = []
    ids = [r.get("id") for r in rounds]
    if len(set(ids)) != len(ids):
        problems.append(f"{label}: duplicate round ids")

    live = [r for r in rounds if r.get("state") == "live"]
    if len(live) > 1:
        problems.append(f"{label}: {len(live)} rounds marked live, expected at most 1")

    # order must be present and strictly increasing: it is what lets Swiss and
    # cut rounds share one array without the track guessing at sequence.
    orders = [r.get("order") for r in rounds]
    if any(o is None for o in orders):
        problems.append(f"{label}: a round has no order")
    elif orders != sorted(orders) or len(set(orders)) != len(orders):
        problems.append(f"{label}: order is not strictly increasing: {orders}")

    for r in rounds:
        rl = f"{label} {r.get('label', r.get('id', '?'))}"
        state = r.get("state")
        if state not in ("done", "live", "upcoming"):
            problems.append(f"{rl}: unknown state {state!r}")
            continue
        if state == "upcoming":
            if r.get("pairings") or r.get("standings"):
                problems.append(f"{rl}: an upcoming round must carry no data")
            continue
        if not r.get("pairings"):
            problems.append(f"{rl}: no pairings")
        if not r.get("standings"):
            problems.append(f"{rl}: no standings")

        names = [n for p in r.get("pairings") or [] for n in (p.get("a"), p.get("b"))]
        if any(p.get("a") == p.get("b") for p in r.get("pairings") or []):
            problems.append(f"{rl}: a Duelist is paired against themselves")
        if len(set(names)) != len(names):
            problems.append(f"{rl}: a Duelist appears in two pairings")

        after = r.get("standingsAfter")
        if isinstance(after, int):
            for st in r.get("standings") or []:
                parts = str(st.get("record", "")).replace("–", "-").split("-")
                try:
                    played = int(parts[0]) + int(parts[1])
                except (ValueError, IndexError):
                    problems.append(f"{rl}: unparseable record {st.get('record')!r}")
                    continue
                if played != after:
                    problems.append(
                        f"{rl}: {st.get('name')} has {st.get('record')} but {after} rounds were played")

    swiss = [r for r in rounds if r.get("phase") == "Swiss"]
    cut = [r for r in rounds if r.get("phase") == "Top cut"]
    for r in rounds:
        if r.get("phase") not in ("Swiss", "Top cut"):
            problems.append(f"{label} {r.get('label', r.get('id'))}: phase is {r.get('phase')!r}")
    if isinstance(swiss_count, int) and len(swiss) != swiss_count:
        problems.append(f"{label}: {len(swiss)} Swiss rounds but swissRounds says {swiss_count}")

    played_cut = [r for r in cut if r.get("state") != "upcoming"]
    for r in played_cut:
        if isinstance(swiss_count, int) and r.get("standingsAfter") != swiss_count:
            problems.append(f"{label} {r['label']}: standingsAfter is {r.get('standingsAfter')}, "
                            f"expected the final Swiss standings ({swiss_count})")
        n = len(r.get("pairings") or [])
        if n == 0 or (n & (n - 1)) != 0:
            problems.append(f"{label} {r['label']}: {n} matches is not a power of two")

    if isinstance(swiss_count, int):
        for depth, r in enumerate(played_cut):
            for p in r.get("pairings") or []:
                for who, rec in (("a", p.get("aRec")), ("b", p.get("bRec"))):
                    parts = str(rec).replace("–", "-").split("-")
                    try:
                        played = int(parts[0]) + int(parts[1])
                    except (ValueError, IndexError):
                        problems.append(f"{label} {r['label']}: unparseable record {rec!r}")
                        continue
                    if played != swiss_count + depth:
                        problems.append(f"{label} {r['label']}: {p.get(who)} shows {rec} "
                                        f"({played} matches), expected {swiss_count + depth}")

    for earlier, later in zip(played_cut, played_cut[1:]):
        before = {}
        for p in earlier.get("pairings") or []:
            before[p.get("a")] = p.get("aRec")
            before[p.get("b")] = p.get("bRec")
        after_names = {n for p in later.get("pairings") or [] for n in (p.get("a"), p.get("b"))}
        stray = sorted(after_names - set(before))
        if stray:
            problems.append(f"{label} {later['label']}: {stray} did not play in {earlier['label']}")
        if len(after_names) * 2 != len(before):
            problems.append(f"{label} {later['label']}: {len(after_names)} Duelists from "
                            f"{len(before)} in {earlier['label']}, expected half")
        for p in later.get("pairings") or []:
            for who, rec in ((p.get("a"), p.get("aRec")), (p.get("b"), p.get("bRec"))):
                prev = before.get(who)
                if prev is None:
                    continue
                try:
                    w0, l0 = (int(x) for x in str(prev).replace("–", "-").split("-")[:2])
                    w1, l1 = (int(x) for x in str(rec).replace("–", "-").split("-")[:2])
                except (ValueError, IndexError):
                    continue
                if (w1, l1) != (w0 + 1, l0):
                    problems.append(f"{label} {later['label']}: {who} went {prev} -> {rec}; "
                                    "advancing should add exactly one win")
    return problems


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
    for field in ("event", "coverageBy", "formats"):
        if field not in data:
            problems.append(f"missing top-level field {field!r}")
    for i, fmt in enumerate(data.get("formats") or []):
        for field in ("format", "swissRounds", "duelists", "rounds"):
            if field not in fmt:
                problems.append(f"formats[{i}] missing field {field!r}")

    formats = data.get("formats") or []
    if not isinstance(formats, list) or not formats:
        problems.append("formats is empty or not a list")

    names = [f.get("format") for f in formats]
    if len(set(names)) != len(names):
        problems.append(f"duplicate format names: {names}")

    for fmt in formats:
        label = fmt.get("format", "?")
        rounds = fmt.get("rounds") or []
        swiss_count = fmt.get("swissRounds")
        if not rounds:
            problems.append(f"{label}: no rounds")
            continue
        problems += check_rounds(label, rounds, swiss_count)

    if problems:
        for p_ in problems[:25]:
            print(f"  FAIL  {p_}")
        if len(problems) > 25:
            print(f"  ... and {len(problems) - 25} more")
        return 1

    total = sum(len(f.get("rounds") or []) for f in formats)
    print(f"  ok    {path}: {len(formats)} formats ("
          + ", ".join(f"{f.get('format')} {len(f.get('rounds') or [])}" for f in formats)
          + f"), {total} rounds, records and bracket coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
