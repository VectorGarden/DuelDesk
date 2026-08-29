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
import re
import sys
from pathlib import Path


def bracket_width(label):
    """How many competitors a cut round holds, from its label.

    "Top 8" is eight of them. The blog also writes the last two stages by name,
    and cut_rank in the builder treats those as the same stages, so this does
    too. None for a label that names no stage at all.
    """
    low = label.lower()
    if m := re.search(r"top\s*(\d+)", low):
        return int(m.group(1))
    if "semi" in low:
        return 4
    if "quarter" in low:
        return 8
    if re.search(r"\bfinals?\b", low):
        return 2
    return None


def matches_played(record):
    """Matches a record accounts for, or None when it is not fully known.

    Records are stored as parts rather than a formatted string, because a
    scraped one may know wins without losses.
    """
    if not isinstance(record, dict):
        return None
    w, l, d = record.get("wins"), record.get("losses"), record.get("draws") or 0
    if w is None or l is None:
        return None
    return w + l + d


def fmt_record(record):
    if not isinstance(record, dict):
        return repr(record)
    part = lambda v: "?" if v is None else str(v)
    core = [part(record.get("wins")), part(record.get("losses"))]
    if record.get("draws"):
        core.append(part(record.get("draws")))
    return "–".join(core)


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
        # A round must carry something, but not necessarily all of it. Generated
        # data always has each; real coverage does not -- the blog posts
        # standings for some rounds and pairings for others, and for older
        # events sometimes only a feature match. Five of the 2026 North America
        # WCQ's rounds reached the archive as a feature match and nothing else,
        # which is thin coverage of a real round, not an empty one.
        if not r.get("pairings") and not r.get("standings") and not r.get("feature"):
            problems.append(f"{rl}: no pairings, standings or feature match")

        pairs = r.get("pairings") or []
        names = [n for p in pairs for n in (p.get("a"), p.get("b"))]
        if any(p.get("a") == p.get("b") for p in pairs):
            problems.append(f"{rl}: a Duelist is paired against themselves")
        # One name at two tables is either two Duelists or a mistake in the
        # source, and the coverage does not always say which -- Columbus round 2
        # seats "Colton Randolph Crane" twice with no region on either row. What
        # must not happen is deriving a record from the merged appearances, so
        # that, not the duplicate itself, is what fails: a name the build has
        # already given up on is honestly reported, not a defect to fix here.
        derived = {p[side] for p in pairs for side in ("a", "b")
                   if (p.get(f"{side}Rec") or {}).get("confidence") in ("derived", "partial")}
        twice = {n for n in names if names.count(n) > 1}
        if bad := sorted(twice & derived):
            problems.append(f"{rl}: a record was derived for {bad[0]}, "
                            "who appears in two pairings")

        after = r.get("standingsAfter")
        if isinstance(after, int):
            for st in r.get("standings") or []:
                rec = st.get("record")
                # A partial record is valid, not broken: wins can be exact while
                # losses are not, and the page renders a ? for the gap. Only a
                # fully derived record can be checked against the round count.
                if isinstance(rec, dict) and rec.get("confidence") != "derived":
                    continue
                played = matches_played(rec)
                if played is None:
                    problems.append(f"{rl}: unusable record {rec!r}")
                    continue
                # Fewer matches than rounds is legitimate: a bye awards points
                # without a pairing, and entrants join late or sit one out. What
                # cannot happen is a record accounting for more matches than the
                # tournament has played by that point.
                if played > after:
                    problems.append(
                        f"{rl}: {st.get('name')} has {fmt_record(st.get('record'))} "
                        f"({played} matches) but only {after} rounds have been played")

    swiss = [r for r in rounds if r.get("phase") == "Swiss"]
    cut = [r for r in rounds if r.get("phase") == "Top cut"]
    for r in rounds:
        if r.get("phase") not in ("Swiss", "Top cut"):
            problems.append(f"{label} {r.get('label', r.get('id'))}: phase is {r.get('phase')!r}")
    if isinstance(swiss_count, int):
        # Scraped coverage can be missing a round the blog never posted, so the
        # count present may be lower. What must never happen is a round numbered
        # beyond the tournament's length, or a length below what is present.
        numbers = [int(r["id"]) for r in swiss if str(r.get("id", "")).isdigit()]
        if numbers and max(numbers) > swiss_count:
            problems.append(f"{label}: round {max(numbers)} exceeds swissRounds {swiss_count}")
        if len(swiss) > swiss_count:
            problems.append(f"{label}: {len(swiss)} Swiss rounds but swissRounds says {swiss_count}")

    played_cut = [r for r in cut if r.get("state") != "upcoming"]
    sides: dict[str, int] = {}          # round -> Duelists a side, see below
    for r in played_cut:
        if isinstance(swiss_count, int) and r.get("standingsAfter") != swiss_count:
            problems.append(f"{label} {r['label']}: standingsAfter is {r.get('standingsAfter')}, "
                            f"expected the final Swiss standings ({swiss_count})")
        # The bracket's shape, read from the round's own label rather than
        # assumed. A round called Top N holds N competitors playing N/2 matches,
        # so the rows per match fall out of it -- and that is what varies.
        #
        # A Team YCS pairs three Duelists a side and lists them individually, so
        # its Top 8 is eight teams playing four matches of three duels: twelve
        # rows. Requiring a power of two rejected TEAM YCS Las Vegas outright
        # over a bracket that was perfectly well formed.
        #
        # Skipped where there are no pairings at all: that is a round the blog
        # covered with a feature match and nothing else.
        n = len(r.get("pairings") or [])
        if not n:
            continue
        competitors = bracket_width(r["label"])
        if competitors is None:
            problems.append(f"{label} {r['label']}: not a round of a bracket")
        elif (n * 2) % competitors:
            problems.append(f"{label} {r['label']}: {n} matches does not divide "
                            f"{competitors} into equal sides")
        else:
            sides[r["label"]] = n * 2 // competitors

    if isinstance(swiss_count, int):
        for depth, r in enumerate(played_cut):
            for p in r.get("pairings") or []:
                for who, rec in (("a", p.get("aRec")), ("b", p.get("bRec"))):
                    if rec is None or (isinstance(rec, dict)
                                       and rec.get("confidence") != "derived"):
                        continue          # a scraped pairing may carry no record
                    played = matches_played(rec)
                    if played is None:
                        problems.append(f"{label} {r['label']}: unusable record {rec!r}")
                        continue
                    if played != swiss_count + depth:
                        problems.append(f"{label} {r['label']}: {p.get(who)} shows "
                                        f"{fmt_record(rec)} ({played} matches), "
                                        f"expected {swiss_count + depth}")

    # One number for the whole bracket. Derived per round above, so a round that
    # lost rows shows up as the one disagreeing with the rest rather than being
    # waved through by a rule loose enough to accept a team event.
    if len(set(sides.values())) > 1:
        problems.append(f"{label}: rounds disagree on how many Duelists a side: "
                        + ", ".join(f"{k} says {v}" for k, v in sorted(sides.items())))

    # Advancement, between consecutive cut rounds that both published pairings.
    # A round covered only by a feature match names nobody, and "nobody advanced
    # out of the Top 4" is a fact about the coverage, not about the bracket --
    # Konami covered YCS Montreal's as far as the Top 4 and stopped, and older
    # events stop earlier. Checking it anyway rejected whole events over the one
    # round nobody published.
    for earlier, later in zip(played_cut, played_cut[1:]):
        if not (earlier.get("pairings") and later.get("pairings")):
            continue
        before = {}
        for p in earlier["pairings"]:
            before[p.get("a")] = p.get("aRec")
            before[p.get("b")] = p.get("bRec")
        after_names = {n for p in later["pairings"] for n in (p.get("a"), p.get("b"))}
        stray = sorted(after_names - set(before))
        if stray:
            problems.append(f"{label} {later['label']}: {stray} did not play in {earlier['label']}")
        if len(after_names) * 2 != len(before):
            problems.append(f"{label} {later['label']}: {len(after_names)} Duelists from "
                            f"{len(before)} in {earlier['label']}, expected half")
        for p in later.get("pairings") or []:
            for who, rec in ((p.get("a"), p.get("aRec")), (p.get("b"), p.get("bRec"))):
                prev = before.get(who)
                if not isinstance(prev, dict) or not isinstance(rec, dict):
                    continue
                w0, l0 = prev.get("wins"), prev.get("losses")
                w1, l1 = rec.get("wins"), rec.get("losses")
                if None in (w0, l0, w1, l1):
                    continue
                if (w1, l1) != (w0 + 1, l0):
                    problems.append(f"{label} {later['label']}: {who} went "
                                    f"{fmt_record(prev)} -> {fmt_record(rec)}; "
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
    for field in ("event", "coverageBy", "formats", "sample"):
        if field not in data:
            problems.append(f"missing top-level field {field!r}")

    # The page hides its "Sample data" badge unless this is exactly True, so a
    # file that omits it or writes something truthy-but-not-true is served as
    # genuine coverage. Required and strictly boolean, in both directions: the
    # badge is the only claim the page makes about whether any of this is real.
    if "sample" in data and not isinstance(data["sample"], bool):
        problems.append(f"sample is {data['sample']!r}, expected true or false")
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

    # "updated" must name the newest round actually posted, across all formats.
    # This check existed and was lost when the format axis was added -- which is
    # how a timestamp an hour in the future reached production.
    stamped = [(f.get("format"), r) for f in formats for r in (f.get("rounds") or []) if r.get("posted")]
    if stamped and data.get("updated"):
        latest = max(r.get("posted") for _, r in stamped)
        stamp = str(data["updated"])
        # Generated data stamps a time; scraped data has only the date the blog
        # published. Compare on whichever precision both carry.
        if "T" in stamp and ":" in latest:
            if stamp[11:16] != latest:
                problems.append(f"updated says {stamp[11:16]} but the newest "
                                f"posted round went up at {latest}")
        elif len(latest) == 10 and stamp[:10] < latest:
            problems.append(f"updated is {stamp[:10]} but a round was posted at {latest}")

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
