#!/usr/bin/env python3
"""The archive: one directory per event, plus a manifest naming them all.

One event's coverage is about 1.5MB of JSON, so the archive cannot be a single
file -- 68 events of it would be a 100MB download to look at one round. Each
event gets its own directory and the page fetches only the one being read.

    events.json                       every event, small enough to load first
    events/<slug>/rounds.json         that event's rounds, the page's payload
    events/<slug>/posts.json          its coverage posts, for rebuilding the feed
    events/<slug>/articles.json       their prose, so a post can be read here

posts.json exists because the feed spans events. A run backfills a few events at
a time, so a feed built from only what that run fetched would drop every event
the previous run covered. Keeping each event's posts beside its rounds makes the
feed a function of the archive rather than of the last run.

articles.json is separate from posts.json because posts.json is fetched with the
event and articles are not read until somebody asks for one. Folded in, it would
take the median event's post list from 12KB to 129KB and charge every reader for
prose nobody has opened.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ARCHIVE = "events"
MANIFEST = "events.json"


def lean(event: dict) -> dict:
    """The event with nulls dropped from its table rows.

    Pairings and standings rows are 99% of the file and most of each row is
    fields that do not apply: no deck type was published, no points column
    existed, nothing could be derived. Written out in full, YCS Columbus is
    10.1MB of JSON to describe 17 rounds, and the archive would reach a
    quarter of a gigabyte before it was half filled.

    Only the rows, and only nulls. Every structural field stays exactly as
    built, including the ones that are legitimately null -- a tournament with no
    format name says so rather than omitting the key, because the checker's
    "does this file describe itself" rule has to keep meaning something.

    Safe for the page because it never distinguishes the two: every place that
    tests one of these fields tests for null and undefined together.
    """
    out = copy.deepcopy(event)
    drop = lambda row: {k: v for k, v in row.items() if v is not None}
    for fmt in out.get("formats") or []:
        for rnd in fmt.get("rounds") or []:
            for key in ("pairings", "standings"):
                rnd[key] = [drop(r) for r in rnd.get(key) or []]
    return out


def dumps(obj: dict, *, pretty: bool = False) -> str:
    """One JSON writer, so every file the site reads is written the same way.

    Compact by default. Indentation is 60% of an event file and nobody reads a
    twenty-thousand-row table by eye; the manifest, which someone might, is the
    one written pretty.
    """
    sep = None if pretty else (",", ":")
    return json.dumps(obj, indent=2 if pretty else None, separators=sep,
                      ensure_ascii=False) + "\n"


def event_dir(root: str | Path, slug: str) -> Path:
    return Path(root) / slug


def rounds_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "rounds.json"


def posts_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "posts.json"


def articles_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "articles.json"


def write_event(root: str | Path, slug: str, event: dict, posts: list[dict],
                articles: dict[str, list] | None = None) -> Path:
    d = event_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    out = rounds_path(root, slug)
    out.write_text(dumps(lean(event)), encoding="utf-8")
    posts_path(root, slug).write_text(dumps(posts, pretty=True), encoding="utf-8")
    # Written even when empty, so a reader can tell an event whose prose has
    # not been extracted yet from one whose posts are all tables. Not pretty:
    # this is the largest file in the directory after the rounds.
    at = articles_path(root, slug)
    if articles is None:
        at.unlink(missing_ok=True)
    else:
        at.write_text(dumps(articles), encoding="utf-8")
    return out


def rejected_path(root: str | Path, slug: str) -> Path:
    return event_dir(root, slug) / "rejected.json"


def reject_event(root: str | Path, slug: str, reason: str) -> None:
    """Record that an event was built and would not do, and why.

    Without this the backfill cannot get past a bad event. A rejected event
    leaves nothing in the archive, so the next run does not count it as
    attempted, so it is picked again -- and because the plan takes the newest
    events missing from the archive, the same failures are retried first every
    time and the run never reaches the ones behind them. Five batches of ten
    landed 21 events and then stopped dead: every batch was spending itself on
    the same seven rejections.

    Kept in the archive rather than a state file, and readable, so what the
    archive is missing and why is a thing in the repository rather than a line
    in a log that expires. Delete the file to try again.
    """
    d = event_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    rejected_path(root, slug).write_text(
        dumps({"slug": slug, "reason": reason}, pretty=True), encoding="utf-8")


def attempted(root: str | Path) -> set[str]:
    """Slugs the archive has already built, whether or not it kept them.

    This is the backfill's memory. Read off the files rather than kept in a
    state file, so it cannot disagree with what is actually there.
    """
    root = Path(root)
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir()
            if (d / "rounds.json").is_file() or (d / "rejected.json").is_file()}


def scraped(root: str | Path) -> set[str]:
    """Slugs the archive holds coverage for. What the manifest is built from."""
    root = Path(root)
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if (d / "rounds.json").is_file()}


def count_posts(root: str | Path, slug: str) -> tuple[int, dict[str, int]]:
    """How many posts this event has, and how many of each kind.

    Both, because the page needs both and neither can be worked out from the
    other. The total is what an event says it holds; the breakdown is what a
    filtered list needs in order to leave out an event with nothing of the
    kind being asked for -- without it the list can only find that out by
    fetching, which meant a group vanishing the moment it was opened.

    Six numbers per event. It does not grow with the coverage, which is the
    rule this manifest is kept to.
    """
    p = posts_path(root, slug)
    if not p.is_file():
        return 0, {}
    posts = json.loads(p.read_text(encoding="utf-8"))
    kinds: dict[str, int] = {}
    for post in posts:
        if kind := post.get("kind"):
            kinds[kind] = kinds.get(kind, 0) + 1
    return len(posts), dict(sorted(kinds.items()))


def behind(root: str | Path, version: int) -> set[str]:
    """Slugs whose coverage was written by an older builder.

    Read off the files rather than kept in a state file, exactly as `attempted`
    is, so it cannot disagree with what is actually there. A file with no
    `built` at all predates the marker and is behind by definition.
    """
    out = set()
    for slug in scraped(root):
        try:
            event = json.loads(rounds_path(root, slug).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if event.get("built", 0) != version:
            out.add(slug)
    return out


def champions(event: dict) -> list[dict]:
    """Who won each of an event's tournaments, and with what.

    Lifted into the manifest because the winners page lists every event at
    once, and the alternative is fetching a hundred and forty round files --
    several of them over ten megabytes -- to read one name out of each.

    The deck comes from the champion's own side of the last pairing published,
    which is where the coverage puts deck types when it publishes them at all.

    A team champion carries its Duelists too. A team has no deck of its own --
    three Duelists do -- and the page has nowhere else to read them from: they
    are in the duels the winning match was decided by, and fetching the round
    file to find three names is what this function exists to avoid.
    """
    out = []
    for fmt in event.get("formats") or []:
        if not (won := fmt.get("champion")):
            continue
        played = [r for r in fmt.get("rounds") or [] if r.get("pairings")]
        deck, members = None, []
        for row in (played[-1]["pairings"] if played else []):
            side = "a" if row.get("a") == won else ("b" if row.get("b") == won else None)
            if side is None:
                continue
            deck = row.get(side + "Deck")
            members = [{"name": duel[side], "deck": duel.get(side + "Deck")}
                       for duel in row.get("duels") or [] if duel.get(side)]
        out.append({"format": fmt.get("format"), "name": won, "deck": deck,
                    # Only where there are any. Every singles event would
                    # otherwise carry an empty list in a file the page fetches
                    # before anything is on screen.
                    **({"members": members} if members else {})})
    return out


def summarise(slug: str, event: dict, posts: int = 0,
              kinds: dict[str, int] | None = None) -> dict:
    """The manifest's entry for one event: enough to list and choose it, and
    nothing that would make the manifest grow with the coverage."""
    return {
        "slug": slug,
        "event": event.get("event"),
        # In the manifest as well, so the event list can say where an event was
        # without fetching the whole of it.
        **({"location": event["location"]} if event.get("location") else {}),
        "updated": event.get("updated"),
        "sample": event.get("sample", False),
        "ongoing": event.get("ongoing", False),
        "coverageBy": event.get("coverageBy"),
        "path": f"{ARCHIVE}/{slug}/rounds.json",
        # How many posts the event has, not the posts themselves. The page
        # lists every event but fetches an event's coverage only when it is
        # opened, so without this it could only count what it had already
        # loaded -- and a total that climbs as you read is worse than none.
        "postCount": posts,
        # And how many of each. What lets a filtered list know an event has no
        # deck profiles without fetching its coverage to find out.
        **({"kinds": kinds} if kinds else {}),
        # Only where there is one. Most events have no champion on record, and
        # an empty list on every one of them is weight in a file the page
        # fetches before anything is on screen.
        **({"champions": won} if (won := champions(event)) else {}),
        "formats": [{"format": f.get("format"),
                     "swissRounds": f.get("swissRounds"),
                     "duelists": f.get("duelists"),
                     "rounds": len(f.get("rounds") or [])}
                    for f in event.get("formats") or []],
    }


_INITIAL = re.compile(r"^[A-Za-z]\.?$")


def names_in(event: dict) -> set[str]:
    """Every Duelist the event seated, from its pairings and its standings."""
    out: set[str] = set()
    for fmt in event.get("formats") or []:
        for rnd in fmt.get("rounds") or []:
            for row in rnd.get("pairings") or []:
                out.update(row[k] for k in ("a", "b") if row.get(k))
            for row in rnd.get("standings") or []:
                if row.get("name"):
                    out.add(row["name"])
    return out


# A name cut down to a forename and an initial: "Dominic C.".
_CUT_DOWN = re.compile(r"^(\S+)(?:\s+\S+)*\s+([A-Za-z])\.?$")


def _sides(event: dict) -> tuple[set[str], set[str]]:
    """Who the pairings name, and who the standings name."""
    paired: set[str] = set()
    listed: set[str] = set()
    for fmt in event.get("formats") or []:
        for rnd in fmt.get("rounds") or []:
            for row in rnd.get("pairings") or []:
                paired.update(row[k] for k in ("a", "b") if row.get(k))
                for duel in row.get("duels") or []:
                    paired.update(duel[k] for k in ("a", "b") if duel.get(k))
            for row in rnd.get("standings") or []:
                listed.update(row.get("members")
                              or ([row["name"]] if row.get("name") else []))
    return paired, listed


def cut_down(event: dict) -> dict[str, str]:
    """Names the standings cut to an initial, and who the pairings say they are.

    A team event's standings carry the roster rather than the entry form:
    Team YCS Las Vegas 2024 lists 1,319 Duelists as "Forbes K." and "Bastian
    N." while its pairings name all 2,395 of them in full. The two are the
    same people written twice, so without this a Duelist has a page for their
    duels and a second page, holding one event, for the table they were listed
    in -- and a title can land on the second. Dominic Eduardo Couch's page had
    fifty-five events and two titles, and a "Dominic C." held his third.

    Only where the pairings answer it. The initial has to be the initial of a
    surname, the forename has to match, and exactly one Duelist in the event
    can fit: "Robert J." is Robert Thor Juhlin at one event and Robert
    Sylvestre Loa Jr. at another, which is why this is asked of an event and
    not of the archive.

    And only for a name the pairings never use themselves. A Duelist actually
    entered as "Forbes K." plays under that name, and a name that plays is a
    name, not a shortening of somebody else's.
    """
    paired, listed = _sides(event)

    def ends(name: str) -> tuple[str, str]:
        words = name.split()
        return words[0].lower(), (words[-1][:1] if len(words) > 1 else "").upper()

    full: dict[tuple[str, str], set[str]] = defaultdict(set)
    for name in paired:
        if len(name.split()) > 1 and not _CUT_DOWN.match(name):
            full[ends(name)].add(name)

    out: dict[str, str] = {}
    for name in listed - paired:
        if not _CUT_DOWN.match(name) or len(name.split()) > 3:
            continue
        fits = full.get(ends(name), set())
        if len(fits) == 1:
            out[name] = next(iter(fits))
    return out


def one_person(seated: dict[str, set[str]]) -> dict[str, str]:
    """Names the archive writes two ways for one Duelist, and the fuller one.

    The blog is not consistent about a middle initial across events. Steven
    Trifunoski won YCS Anaheim; Steven J. Trifunoski won YCS Vancouver. They
    are one Duelist with two titles, and the winners page counted them as two
    Duelists with one each.

    Within an event this is already handled, and by a stricter rule than this
    one -- see build.fold_short_names, which has a round's seating to argue
    from. Across events there is no round to look at, so this asks for more
    before it folds anything:

      * The shorter name's words all sit in the longer one, in order, and the
        two share both a forename and a surname.
      * What the longer one adds is initials and nothing else. A full inserted
        word is a name, and names are how two people differ: 73 pairs in this
        archive that differ by a word are provably two people, because they
        are seated in the same event.
      * Nothing else answers to that forename and surname. Ankit Shah is
        written Ankit H. Shah and Ankit L. Shah, which is two Duelists and an
        ambiguous third spelling; folding it either way invents a record.
      * The two are never seated in the same event. One Duelist does not enter
        twice, so an overlap settles it -- this is what rules out Alejandro
        Cruz and Alejandro Castillo Cruz, who played the same tournament.

    Sixty pairs in the archive meet all four. Only the names are folded, and
    only for counting a Duelist across events: what each event published is
    what it published, and this does not touch it.
    """
    ends: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in seated:
        if len(words := name.split()) >= 2:
            ends[(words[0].lower(), words[-1].lower())].append(name)

    folded: dict[str, str] = {}
    for group in ends.values():
        # Exactly two spellings, or there is no unambiguous fuller form.
        if len(group) != 2:
            continue
        short, long_ = sorted(group, key=lambda n: len(n.split()))
        sw, lw = short.split(), long_.split()
        if len(sw) >= len(lw):
            continue
        at, extra = 0, []
        for word in lw:
            if at < len(sw) and word.lower() == sw[at].lower():
                at += 1
            else:
                extra.append(word)
        if at != len(sw) or not extra:
            continue
        if not all(_INITIAL.match(x) for x in extra):
            continue
        if seated[short] & seated[long_]:
            continue
        folded[short] = long_
    return folded


PLAYERS = "players"
PLAYER_SHARDS = 512

# What a Duelist's name is, for the purpose of deciding which file they are
# in. Only the letters, so a shard cannot move because a name gained a full
# stop -- "P. Hoban" and "P Hoban" are one page's worth of question, not two
# files apart.
_SHARD_KEY = re.compile(r"[^a-z]+")


def shard_of(name: str) -> str:
    """Which of the player files holds this name.

    Hashed rather than keyed on the first letters, because names are not
    spread evenly across the alphabet: two-letter prefixes put 537KB under
    "jo" and half a kilobyte under most of the rest, and a reader looking up
    a Johnson would pay for every other one. Hashed, every file is 13 to 21KB
    and the page fetches one of them whatever the name.

    Five hundred and twelve of them: enough to keep each small, few enough
    that the archive gains hundreds of files rather than tens of thousands.
    """
    flat = _SHARD_KEY.sub("", name.lower())
    n = int(hashlib.sha1(flat.encode("utf-8")).hexdigest()[:8], 16) % PLAYER_SHARDS
    return f"{n:03d}"


def build_players(root: str | Path) -> dict[str, dict]:
    """Shard name -> {Duelist: what they played and how far they got}.

    One row per Duelist per tournament, holding only what the page cannot
    work out for itself: the event's slug, which of its tournaments, the
    deepest cut round they reached, the deck they were recorded with, and
    whether they won it. The event's own name, date and place stay in the
    manifest the page already loads, so they are not repeated 154,214 times.

    A team event is read through its duels. Its pairings name the teams --
    "Ares" against "Halal Staple Chasers" -- and a team is not a Duelist and
    does not get a page; the three people who played the match are in the
    duels underneath it, and they are who this is about. The same for a team's
    standings row, which carries its members beside its name.

    A team's title belongs to those three as much as to the name they entered
    under, so the champion of a team event is credited to them. Read off the
    winning side of the last published pairing, which is where champions()
    finds a team's Duelists for the same reason.

    And a Duelist the archive spells two ways is one Duelist with one page.
    The fold is one_person's, which is careful about it: an inserted initial
    only, no competing variant, and never two spellings seated in one event.
    """
    events = {}
    # What each event's standings cut to an initial, per event: the same
    # shortening is two different Duelists at two different events.
    shortened: dict[str, dict[str, str]] = {}
    seated: dict[str, set] = defaultdict(set)
    for slug in sorted(scraped(root)):
        try:
            events[slug] = json.loads(rounds_path(root, slug).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        shortened[slug] = cut_down(events[slug])
        for name in names_in(events[slug]):
            seated[shortened[slug].get(name, name)].add(slug)
    same = one_person(seated)

    rows: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)

    def record(who: str, slug: str, fmt: str, *, cut=None, deck=None, won=False):
        who = shortened.get(slug, {}).get(who, who)
        at = rows[same.get(who, who)].setdefault((slug, fmt), {})
        if cut:
            at["cut"] = cut
        if deck:
            at.setdefault("deck", deck)
        if won:
            at["won"] = True

    for slug, event in events.items():
        for fmt in event.get("formats") or []:
            name = fmt.get("format") or ""
            champion = fmt.get("champion")
            # Who won, as people. For a singles event that is the champion; for
            # a team one it is the Duelists on the winning side of the final.
            winners = {champion} if champion else set()
            played = [r for r in fmt.get("rounds") or [] if r.get("pairings")]
            for row in (played[-1]["pairings"] if played else []):
                side = ("a" if row.get("a") == champion
                        else "b" if row.get("b") == champion else None)
                if side and row.get("duels"):
                    winners = {d[side] for d in row["duels"] if d.get(side)}

            for rnd in fmt.get("rounds") or []:
                cut = rnd.get("label") if rnd.get("phase") == "Top cut" else None
                for pair in rnd.get("pairings") or []:
                    if pair.get("duels"):
                        for duel in pair["duels"]:
                            for side in ("a", "b"):
                                if duel.get(side):
                                    record(duel[side], slug, name, cut=cut,
                                           deck=duel.get(side + "Deck"),
                                           won=duel[side] in winners)
                        continue
                    for side in ("a", "b"):
                        if pair.get(side):
                            record(pair[side], slug, name, cut=cut,
                                   deck=pair.get(side + "Deck"),
                                   won=pair[side] in winners)
                for row in rnd.get("standings") or []:
                    for who in (row.get("members") or ([row["name"]] if row.get("name") else [])):
                        record(who, slug, name, deck=row.get("deck"),
                               won=who in winners)

    shards: dict[str, dict] = defaultdict(dict)
    for who, played in rows.items():
        shards[shard_of(who)][who] = [
            {"e": slug, **({"f": fmt} if fmt else {}), **rest}
            for (slug, fmt), rest in sorted(played.items())
        ]

    # A spelling that was folded away still has to be findable. The fold moves
    # a Duelist's record to the fuller name, and the shard is worked out from
    # the name asked for -- "Darryl Kotton" hashes to 002 and "Darryl K.
    # Kotton" to 216 -- so without this a reader who typed the spelling the
    # coverage used would be told nobody by that name exists, which is exactly
    # what the fold was supposed to stop.
    #
    # Left in the shard the old spelling hashes to, pointing at the new one.
    for old, new in same.items():
        if new in rows and old not in shards[shard_of(old)]:
            shards[shard_of(old)][old] = {"as": new}

    # And the same for a name the standings cut to an initial, where it means
    # one Duelist. Eighty of them do not: "Robert J." is one Robert at one
    # event and another at the next, and a page cannot point two ways.
    pointing: dict[str, set[str]] = defaultdict(set)
    for held in shortened.values():
        for short, whole in held.items():
            pointing[short].add(whole)
    for short, whole in pointing.items():
        if len(whole) != 1:
            continue
        one = next(iter(whole))
        if one in rows and short not in shards[shard_of(short)]:
            shards[shard_of(short)][short] = {"as": one}
    return dict(shards)


def write_players(root: str | Path, shards: dict[str, dict]) -> int:
    """Write the player files, and remove any shard that no longer has names."""
    out = Path(root).parent / PLAYERS if Path(root).name else Path(PLAYERS)
    out.mkdir(parents=True, exist_ok=True)
    for name in sorted(shards):
        (out / f"{name}.json").write_text(dumps(shards[name]), encoding="utf-8")
    for stale in out.glob("*.json"):
        if stale.stem not in shards:
            stale.unlink()
    return sum(len(v) for v in shards.values())


def build_manifest(root: str | Path) -> dict:
    """Every built event, newest first.

    Sorted on `updated` descending with the slug breaking ties, so two events
    finishing on the same day list in a stable order rather than in whatever
    order the filesystem returned.
    """
    events, seated = [], defaultdict(set)
    for slug in sorted(scraped(root)):
        event = json.loads(rounds_path(root, slug).read_text(encoding="utf-8"))
        for name in names_in(event):
            seated[name].add(slug)
        events.append(summarise(slug, event, *count_posts(root, slug)))
    events.sort(key=lambda e: (e["updated"] or "", e["slug"]), reverse=True)

    # Who is who, once every event has been read: a Duelist written two ways
    # across the archive is one Duelist, and the winners page counts by this
    # rather than by the spelling each event happened to print.
    same = one_person(seated)
    for event in events:
        for won in event.get("champions") or []:
            for who in (won, *(won.get("members") or [])):
                if (person := same.get(who["name"])):
                    who["person"] = person
    return {"events": events}


def feed_items(root: str | Path, limit: int) -> list[dict]:
    """The newest coverage posts across the whole archive.

    Capped, because the archive runs to thousands of posts and the feed is a
    what's-new list, not a catalogue. The events.json manifest is how the rest
    is reached.
    """
    items: list[dict] = []
    for slug in scraped(root):
        p = posts_path(root, slug)
        if p.is_file():
            items += json.loads(p.read_text(encoding="utf-8"))
    items.sort(key=lambda i: i.get("modified") or "", reverse=True)
    return items[:limit]
