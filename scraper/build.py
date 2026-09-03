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
from functools import lru_cache
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from naming import clock, feature_players
from parse import coverage_format
from winners import champion as champion_named
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


# What the builder was producing when an event file was written.
#
# The archive is built once per event and then left alone -- that is the whole
# point of `attempted` -- so a change to what the builder produces reaches only
# the events built after it. Two have landed that the archive predates: who won
# each event, and records that know whether ties were still policy when it was
# played. Without a marker there is no way to ask which files are behind, and
# "rebuild everything" is hours of fetching to correct a handful.
#
# Bump this when the builder starts producing something the older files do not
# have. Events whose `built` is behind it are what `--rebuild` picks up.
#
# 5: four changes to what the scraper can see. A tie the date rule could not
#    break is broken by the qualifier a post names; the final's own write-up is
#    read for a champion; a round written out as sentences is read as pairings;
#    and an event discovered rather than filed can be dated, which is 1,879
#    posts that had nowhere to go.
#
# 6: one Duelist, one name. The Swiss tables carry the name off the entry form
#    and the cut tables carry the name people use -- "Aaron Chase Furman" for
#    eleven rounds and "Aaron Furman" in the Top 16 -- so a record looked up by
#    name stopped at the cut, and the page showed two entrants where there was
#    one. Every event with a cut is behind this.
#
# 7: every feature match a round carried, not the best of them. 102 of the 357
#    rounds that have one have more than one -- YCS Montreal's Top 4 had three
#    -- so keeping one threw away two thirds of the Duelists the blog wrote
#    about that round. `feature` becomes `features`, a list, newest first.
#
# 8: the tables the blog actually writes. 149 round posts held a real table the
#    reader did not recognise -- "Table | Player 1 | Player 2" and eight other
#    headings -- so YCS Niagara Falls 2022 had ten rounds of standings, no
#    pairings at all, an empty cut, and therefore nobody to name champion.
# 9: a round is not always one table, and a name is not always only a name. The
#    2017 UDS Invitational Trinidad and Tobago published its Top 4 as two
#    tables of one match, and wrote the country and deck beside each Duelist --
#    so the round held one match of four Duelists whose names no other round
#    agreed with, and the event was rejected and left the archive.
# 10: a standings cell is annotated too. The 2016 South America WCQ writes
#     "Rinaldi Petroni, Joaquin (Argentina) - Dracoslayer Performapals" in its
#     standings as well as its pairings, and only the pairings were read that
#     way -- so the deck stayed inside the name, and reconcile_names, which
#     counts words, folded eight clean names into their mangled spellings
#     across every round of the event.
# 11: a caption is not a header, and a blank row ends a table. The 2013 World
#     Championship heads each table with "Main World Championship | Round 1"
#     in a row of its own and puts the Dragon Duel's rounds in the same table
#     underneath, so every round post it published read as unknown and the
#     event has never been in the archive.
# 12: a table with no header at all. Eleven round posts open straight into
#     their rows, and what the columns are is legible from the row itself.
#     Reading them found 595 pairings at YCS Hartford, 350 standings at YCS
#     Pasadena and a Top 4 for the 2013 North America WCQ -- and, on the way,
#     that a "Winner" column was being read as part of the loser's name.
# 13: the team written on every Duelist. A Team YCS that does not announce
#     the team in a row of its own writes it on each Duelist instead -- "La
#     Revolucion: Lozano, Connor Joseph" -- and the comma rule partitioned
#     around it, leaving the team in the middle of the name. 32,791 names
#     across eleven events.
# 14: a team row is data, not a caption -- and a zero-width character is not
#     part of a word. TEAM YCS Las Vegas 2023 announces its final's teams
#     above the header rather than below it, with a byte order mark inside
#     every cell, so the row was neither recognised as an announcement nor
#     kept: the match's three duels stood as three separate matches.
# 15: a title held elsewhere is not a win here. "UDS Champions at YCS
#     Guatemala" is a photograph of Duelists holding an Ultimate Duelist
#     Series invitation, and it names one who reached the Top 4 -- so it was
#     read as announcing this event's winner, disagreed with the post that
#     actually did, and left the event with no champion.
# 16: the rounds written as sentences. Thirty-six round posts carry no table
#     at all, and the prose reader asked for one shape of them: "Table N:"
#     with a colon and a bracketed deck on each side. Nineteen more read now.
# 17: a final written as a sentence. Every YCS final since 2022 is published
#     as prose about the two Duelists rather than as a pairing, so ten events
#     had no Final -- and an event with no Final has no two Duelists for a
#     winner post to be recognised among.
# 18: a sentence side must be a name, and two letters can be the wrong way
#     round. #132 read any sentence saying "against" as a pairing, which made
#     a clause into a Duelist; and YCS Toronto's Top 4 write-up spells
#     "Alexandre Dalpe" as "Alexander Dalpe", which no folding rule reached.
# 19: a team is named by its Duelists. A team enters under a name it chose --
#     "Ares", "Legionnaire" -- and one word is not a name ordinary prose can
#     be searched for, so a team event had no champion unless a winner post
#     happened to quote the name. The coverage names the people instead, and
#     the people are already here, in the duels a team match was decided by.
# 20: the team is the prefix on every Duelist. Four Team YCSs publish their
#     cut with no announcement row at all -- the team is written on each
#     Duelist and consecutive rows sharing a pair are the match. Read a row at
#     a time, a Top 4 of four teams held twenty-four Duelists and no team, so
#     those events had no roster and could name no champion.
# 21: six events the archive had refused. A round the blog published with
#     Player 2 copied from Player 1; the Dragon Duel's tables read as the main
#     event's, which also cost the 2016 World Championship its champion; a Top
#     4 holding eight Duelists; a slug that said Top 3 over a title that said
#     Round 3; a Top 8 published as four unheaded tables; a duel nobody
#     numbered; and a cut round of ten, which no bracket can produce.
# 22: the World Championship is called that. Five events, five spellings, and
#     for 2016 no name at all -- its coverage heads six posts "Pairings: ..."
#     and writes the event's own name without a colon, so the vote never saw
#     it and the archive published the event as Pairings. The name is stored
#     in rounds.json, so only a rebuild changes it.
# 23: a title that used the naming convention is not an abstention. Version 22
#     dropped "Top Table Update" and its kind from the denominator as well as
#     from the vote, which let a candidate with five titles out of fifty-three
#     clear a share it should have failed, and five events reached the site
#     named QQ.
# 24: one Remote Duel YCS is not another. Three events were called exactly
#     "Remote Duel YCS" and two exactly "North America Remote Duel YCS", so
#     the front page listed them side by side with nothing to tell them apart.
#     Named for the month as well as the year, because North America played
#     one in February 2022 and another that December.
# 25: the qualifiers that named their region in two letters, or not at all.
#     "WCQ CA", "SA WCQ", one named for the country it was held in, and the
#     three 2022 events filed under what the qualifier was called before 2023.
#     Every year from 2011 to 2026 is now named the same way, and the only
#     gaps left are 2020 and 2021, when these were not held.
# 26: the sentence that crowns somebody names them. A winner post that names
#     both finalists and no word like "defeated" between them was a
#     disagreement and no champion, which is how YCS Denver had a winner post
#     saying "Anderson Tsang is your newest YCS Champion" and no champion.
# 27: the blog says who came second. Winning the final is written "to victory
#     against", and the loser is often named as the loser rather than as
#     somebody who was beaten -- "In second place was", "Runner-up:". Four
#     more events had a winner post naming both finalists and no word the
#     archive read as putting one before the other.
# 28: the Extravaganza is named, not slugged. The last event on the site whose
#     name was its slug title-cased -- "2023 Yu Gi Oh Tcg Remote Duel
#     Extravaganza Main Event". Named for its month like the Remote Duel YCS
#     beside it, which is what the blog's own welcome post calls it.
# 29: a bracket labelled as Swiss rounds is still a bracket. Team YCS Atlanta
#     numbers all fourteen of its rounds and its winner post says what they
#     were -- ten Swiss and four of single elimination. With no cut round the
#     archive had nobody to ask about a champion and no team match to read a
#     roster from. And a team named inside another team's name is not
#     independently named: its Top 4 holds both "TCG Collectibles" and "Team
#     TCG Collectibles Fala Galera".
# 30: a tournament may claim its own championship. announces_a_winner refuses
#     a post that names a side event, which is right for the main event and
#     wrong for the side event itself -- and the Dragon Duel has been a
#     tournament of its own since version 20 grouped it separately. Five of
#     them had a winner post naming a Duelist standing in their own cut.
# 31: a post that opens with an event's name belongs to that event. A date is
#     when the blog last edited a post, not when the event was, and an edit
#     months later moved the post to whichever event ran that week: YCS
#     Chicago's winner post went to YCS Knoxville, YCS Mexico City's to YCS
#     Providence. 38 posts move and 229 that had no event at all are placed.
# 32: a semi-final is the Top 4. "Semi-Finals pairings" matched the "finals"
#     inside it and became the Final -- two matches in a round that holds one,
#     which took the 2026 World Championship out of the archive the moment
#     version 31 gave it that post.
# 33: a name never moves a round. Version 31 gave a post to the event its slug
#     names, rounds included, and the blog reprints tables under a second slug
#     -- YCS Philadelphia's Top 64 is printed twice and the copy holds 63
#     Duelists. It beat the good table on size and the event left the site;
#     YCS Guadalajara lost two rounds the same way. A name says which event a
#     post is about and nothing about whether its table is any good.
# 34: the Genesys Championship names its region. Each region runs one; Central
#     and South America name theirs in their own coverage and North America's
#     calls itself just "Genesys Championship", so it sat on the front page
#     beside two that say where they were and did not.
# 35: the roll-call, and the heading. A winner post often crowns somebody and
#     then lists the placings behind them -- "the rest of the Top 4" -- and a
#     team's own name is often only in the heading, with the body naming the
#     three Duelists and not the team.
# 36: read the whole entry. The body of a post was found by ending at the
#     first "</div></div>", which is right for a flat post and silently wrong
#     for a nested one: YCS Chicago's winner post returned 140 characters of a
#     312KB page, stopping before the winner's name, and an empty body looks
#     exactly like a post made of images.
# 37: a country is not part of a name. South American coverage writes "Lopes de
#     Aguiar, Renato from Brazil" and 2013's Central American coverage writes a
#     title after a dash; strip_region knew only two- and three-letter codes,
#     so both survived and normalise_name swapped the comma around them. 846
#     rows carried a country in the middle of a name and 47 a title, and a
#     Duelist written both ways counted as two people in their own records.
# 38: a post may crown a winner rather than a champion. The 2025 North America
#     WCQ says "Wilfredo Flores is the North America World Championship
#     Qualifier winner!" and never says champion -- "Championship" there is the
#     event's name -- so the sentence that crowned him said nothing this could
#     read.
# 39: a deck column is not a name. The 2013 World Championship heads its cut
#     "Table | Player 1 | VS. | Player 2 | | Winner | Deck" and everything
#     right of the divider was read as Player 2, so the deck landed in the
#     middle of the name -- "Shin En Dragon Rulers Huang" -- and both
#     finalists matched the winner post on "Dragon Rulers".
# 40: a preview is not an announcement. "Only two more rounds before we have a
#     new South American Champion!" reads as a winner post to every rule, and
#     the body under it is a pairings table -- so a preview naming one Duelist
#     of the cut would have crowned them two rounds before they won anything.
# 41: a surname nobody else answers to. YCS Origins' Final is Jacob David
#     Phinney against Aaron Chase Furman and its winner post says "Jake
#     Phinney" -- a shortening no folding rule reaches, and named_in wants two
#     words of a name. Asked only of a post that named nobody at all.
# 42: a name is read where it actually stands. named_in reported a name at the
#     earliest of its own words, so the 2014 Central American WCQ's two Joses
#     -- one in the first line, one in the last -- came back level, and no
#     word could sit between them to say which had won.
# 43: a name's word is a whole word. Matching by substring read a name's
#     particles into ordinary words -- "De La" found inside "Mementotlan Deck"
#     -- so YCS Mexico City's winner post named two Duelists and could crown
#     neither.
# 44: the path names the event. A lastmod is when the blog last edited a post,
#     and an edit weeks later moved it to whatever event ran that week: YCS
#     Houston's winner post went to YCS Providence, and eight of the 2013
#     North America WCQ's standings went to YCS Chicago, six years away.
# 45: a qualifier known by its initials. The blog writes "sawcq2025-winner",
#     and a word boundary after "wcq" never matches when a digit follows, so
#     the slug named nothing -- and its date, weeks after the tournament, sat
#     inside two qualifiers it was not about.
#  46 The date an event is listed under is the day its coverage ended, not
#     the day somebody edited one of its posts afterwards. Nineteen events
#     moved; YCS Seattle 2017 had been dated to 2 March by a single post
#     edited eleven days after the tournament.
#  47 One rule for what a post is, shared with the page. The stored kind
#     changes for 267 posts: 198 plural winner announcements that read as
#     news, and 69 that mention decks without covering any.
#  48 "Final Match" is not a feature match. The archive had already been
#     rebuilt at 47 when that was corrected, so nothing was behind and the
#     fix had nothing to run against: the 2019 UDS Invitational Medellin
#     stayed without its champion.
BUILD_VERSION = 48


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


def final_from_annotations(candidates: list[Source]) -> tuple[str, str] | None:
    """(runner-up, champion) for a final nobody published pairings for.

    Konami covered YCS Montreal's bracket as far as the Top 4 and stopped. The
    final was played -- the post-cut standings say so -- but it has no pairings
    post, so the round track ended a round early with the event's most
    interesting match missing.

    The annotations describe the whole bracket. For Genesys: four Duelists lost
    in round 12, two in round 13, one in round 14, and one was never eliminated.
    That is a Top 8, a Top 4, a final, and a champion.

    Read only when it is unambiguous. Exactly one Duelist may have lost in the
    last bracket round and exactly one may have gone unbeaten; anything else is a
    table this cannot read, and inventing a final is worse than ending at the
    Top 4. A format whose post-cut standings were never published -- Advanced
    here -- gets nothing, which is the honest outcome rather than a guess.
    """
    for source in candidates:
        rows = source.post.table.rows if source.post.table else []
        cuts = [r for r in rows if r.get("status") == "cut" and r.get("statusRound")]
        if not cuts:
            continue
        unbeaten = [r["name"] for r in rows if not r.get("status")]
        last = max(r["statusRound"] for r in cuts)
        losers = [r["name"] for r in cuts if r["statusRound"] == last]
        if len(losers) == 1 and len(unbeaten) == 1:
            return losers[0], unbeaten[0]
    return None


# Cached because reconcile_names asks the same few thousand names about each
# other: one 646-Duelist event called this 4.7 million times, and splitting the
# same string over and over was 74% of the whole build. A name's words never
# change, so the second answer is the first one.
@lru_cache(maxsize=None)
def _words(name: str) -> tuple[str, ...]:
    return tuple(w for w in re.split(r"[^A-Za-z]+", name.lower()) if w)


def reconcile_names(sources: list[Source]) -> dict[str, str]:
    """Give one Duelist one name for the whole event. Rewrites in place.

    Konami's Swiss tables carry the name off the entry form and its cut tables
    carry the name people use. YCS Chicago seated "Aaron Chase Furman" through
    eleven rounds of Swiss and "Aaron Furman" in the Top 16, "Kobe Louis Short"
    and then "Kobe Short", "Calvin Habib Tahan" and then "Calvin Tahan" -- the
    same sixteen people, spelled two ways, in one event.

    Nothing downstream survives that. A record is looked up by name, so the cut
    pairings asked for a Duelist the standings had filed under a longer one and
    got nothing; the page showed two entrants where there was one; and the
    advancement check read a Top 16 whose Duelists had, as far as any name could
    tell, not played in the Top 32.

    A short name is folded into a longer one only where the longer one is the
    only candidate. Every word of the short name has to be a word of the longer
    one, or the start of one: the cut tables shorten "Jeffrey Michael Alexander
    Jones" to "Jeff Jones", and they drop given names from the front as readily
    as from the back -- "Mohammed Faisal Khan" is printed "Faisal Khan", so a
    rule keyed on the forename alone would refuse him.

    But the two have to agree about a forename or a surname, and not merely
    share words. Without that, "Alexander Michael" folded into "Jeffrey Michael
    Alexander Jones" at YCS Cancun -- two people, one of them erased, because
    the shorter name's two words happen to sit inside the longer one. Matching
    either end is enough for every real shortening: "Aaron Furman" keeps the
    forename, "Faisal Khan" keeps the surname, and "Edgar Tinoco" for "Edgar
    Gustavo Tinoco Serrano" keeps the forename where the second surname is the
    one dropped.

    Being the only candidate is what makes the rest safe rather than reckless.
    YCS Knoxville seated a Mohammed Imran Khan as well, and he is not a
    candidate for "Faisal Khan"; had he been, neither Duelist would be folded.
    The same uniqueness covers the initial nobody can expand -- "J Jones" is
    left alone among five, which costs a record and does not invent one.

    Two spellings seated in the same round are two people, whatever their names
    look like: one Duelist does not play themselves. That case is left alone
    too, and so is a target two names both reach for -- folding those would
    seat one Duelist twice in a round that holds two.
    """
    names: set[str] = set()
    together: list[set[str]] = []      # names seated in one round
    at: dict[int, set[str]] = defaultdict(set)     # who appears, by round order
    for s in sources:
        if not s.post.table:
            continue
        here: set[str] = set()
        for row in s.post.table.rows:
            cells = ([row.get(side) or {} for side in ("a", "b")]
                     if s.post.kind == "pairings" else [row])
            here.update(c["name"] for c in cells if c.get("name"))
        names |= here
        together.append(here)
        rd = s.post.round
        if isinstance(rd, int):
            at[rd] |= here
        elif isinstance(rd, str):
            at[CUT_ORDER_BASE + cut_rank(rd)] |= here

    def apart(a: str, b: str) -> bool:
        return not any({a, b} <= group for group in together)

    def ends_agree(sw: tuple[str, ...], lw: tuple[str, ...]) -> bool:
        """Whether the two names agree about a forename or about a surname."""
        return any(a == b or b.startswith(a)
                   for a, b in ((sw[0], lw[0]), (sw[-1], lw[-1])))

    def misspelt(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
        """Whether these are one name with a letter typed wrong in it.

        YCS Atlanta's Swiss seated "Mohammed Imran Khan" for eleven rounds and
        its Top 4 post printed "Mohammed Imram Khan". Nothing about that is a
        shortening -- same words, same length, one letter -- so the folding
        rules did not reach it, and the event was rejected because a Duelist in
        the Top 4 had not played in the Top 8.

        Exactly one letter, in exactly one word, with every other word
        identical. Two Duelists whose names are one letter apart both played
        the Swiss and are therefore seated in the same rounds, which `apart`
        already refuses.
        """
        if len(a) != len(b):
            return False
        odd = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(odd) != 1:
            return False
        x, y = a[odd[0]], b[odd[0]]
        if len(x) != len(y):
            return False
        off = [i for i, (p, q) in enumerate(zip(x, y)) if p != q]
        if len(off) == 1:
            return True
        # Or two neighbours the wrong way round, which is the same slip of the
        # hand. YCS Toronto's Top 8 seats "Alexandre Dalpe" and its Top 4 is
        # written up as "Alexander Dalpe" -- one Duelist, and a Top 4 holding
        # somebody who had not played in the Top 8 took the event out of the
        # archive.
        return (len(off) == 2 and off[1] == off[0] + 1
                and x[off[0]] == y[off[1]] and x[off[1]] == y[off[0]])

    def shortens(sw: tuple[str, ...], lw: tuple[str, ...]) -> bool:
        """Whether every word of sw is a distinct word of lw, or starts one."""
        spare = list(lw)
        for w in sw:
            fit = ([x for x in spare if x == w]
                   or [x for x in spare if len(w) > 2 and x.startswith(w)])
            if not fit:
                return False
            spare.remove(fit[0])
        return True

    # How many rounds each spelling was seated in. A typo appears once, in the
    # post that carried it; the name itself appears everywhere the Duelist
    # played, so the majority spelling is the one to keep.
    rounds_seen = Counter(n for group in together for n in group)

    # Where the candidates could possibly be, so the rules are asked about
    # those rather than about everybody. Both rules are narrow -- a shortening
    # keeps one end of the name, a typo leaves every other word alone -- and
    # scanning every pair spent almost all of its time proving so. One
    # 646-Duelist event compared 2,064,969 pairs to find 162 worth testing for
    # a typo and 10,190 worth testing for a shortening.
    #
    # Both indexes are supersets of what the rules accept, and the rules still
    # decide, so the folding is the same folding. The keys are chosen to keep
    # it that way: ends_agree accepts a prefix -- "Ben" agrees with "Benjamin"
    # -- so the end index is keyed on a first letter and not a whole word,
    # which a shorter forename would fall straight out of.
    ends_index: dict[tuple, set[str]] = defaultdict(set)
    gap_index: dict[tuple, set[str]] = defaultdict(set)
    for n in names:
        w = _words(n)
        if not w:
            continue
        # Keyed on how many words the name has as well as which letter it
        # starts with. A shortening has strictly more words than the name it
        # shortens, so every bucket at or below that length holds nobody this
        # rule can accept -- and a first letter alone puts thousands of names
        # in a bucket, every one of which was tested to prove that.
        ends_index["first", w[0][0], len(w)].add(n)
        ends_index["last", w[-1][0], len(w)].add(n)
        # Two names differing in exactly one word agree on the others, so they
        # meet under the key that leaves that word out.
        for i in range(len(w)):
            gap_index[len(w), i, w[:i] + w[i + 1:]].add(n)

    longest = max((len(_words(n)) for n in names), default=0)

    canon: dict[str, str] = {}
    for short in names:
        sw = _words(short)
        if len(sw) < 2:
            continue                    # a lone word identifies nobody
        keeps_an_end = set().union(*(
            ends_index[end, letter, size]
            for end, letter in (("first", sw[0][0]), ("last", sw[-1][0]))
            for size in range(len(sw) + 1, longest + 1)))
        longer = [n for n in keeps_an_end
                  if shortens(sw, _words(n))
                  and ends_agree(sw, _words(n)) and apart(short, n)]
        # Or the same name with a letter typed wrong, folded the way round the
        # coverage votes: the spelling seen in more rounds keeps the Duelist.
        one_word_off = set().union(*(gap_index[len(sw), i, sw[:i] + sw[i + 1:]]
                                     for i in range(len(sw))))
        longer += [n for n in one_word_off
                   if misspelt(sw, _words(n)) and apart(short, n)
                   and rounds_seen[n] > rounds_seen[short]]
        if len(longer) > 1:
            # Several people could be meant, so the bracket is asked instead.
            # A Duelist in a cut round played in the round before it, and YCS
            # Memphis printed a Top 16 "Thanh Nguyen" over a Swiss holding both
            # a Nhan Thanh Nguyen and a Thanh Cong Nguyen. Only one of them is
            # in the Top 32, and that is the one who reached the Top 16.
            first = min((r for r, who in at.items() if short in who), default=None)
            before = [r for r in at if r < first] if first is not None else []
            if before:
                seeded = at[max(before)]
                longer = [n for n in longer if n in seeded] or longer
        if len(longer) == 1:
            canon[short] = longer[0]

    # Only the ends of a chain. "A Furman" -> "A C Furman" -> "A C D Furman"
    # would otherwise leave the first two disagreeing about the third.
    for short in list(canon):
        seen = {short}
        while canon.get(canon[short]) and canon[short] not in seen:
            seen.add(canon[short])
            canon[short] = canon[canon[short]]

    # Several names reaching for one target are usually one Duelist written
    # several ways -- YCS Memphis has "Kamal Crooks", "Kamal Crooks-Valdez" and
    # "Kamal Derrick El Crooks-Valdez", and refusing all three because there
    # were three left the event with a Top 16 seeded from nobody.
    #
    # What cannot stand is two of them in one round, because that is one
    # Duelist playing themselves. Those are left alone, and only those.
    reached = defaultdict(set)
    for short, long in canon.items():
        reached[long].add(short)
    for long, shorts in reached.items():
        if len(shorts) > 1 and any(len(shorts & group) > 1 for group in together):
            for short in shorts:
                canon.pop(short, None)

    if canon:
        for s in sources:
            for row in (s.post.table.rows if s.post.table else []):
                cells = ([row.get(side) for side in ("a", "b")]
                         if s.post.kind == "pairings" else [row])
                for cell in cells:
                    if cell and cell.get("name") in canon:
                        cell["name"] = canon[cell["name"]]
    return canon


def disambiguate(sources: list[Source]) -> tuple[set[str], set[str]]:
    """Give two Duelists who share a name their regions back. Rewrites in place.

    Returns (separated, ambiguous): the names it could tell apart, and the ones
    it could not.

    At YCS Columbus, "Johnny KS Nguyen" and "Johnny PA Nguyen" are two people
    from Kansas and Pennsylvania. The region code is the only thing separating
    them and strip_region takes it off the name, so they merged into one Duelist
    playing two matches a round -- and a merged Duelist's appearances are two
    people's, which makes the losses derived from them wrong for both.

    Only names that actually collide are touched, and only where a region says
    which is which. Appending a region everywhere would be the safer-looking
    change and the wrong one: the same person is written with a region in the
    pairings and without one in the standings, so a name built from the region
    unconditionally would stop matching itself between the two tables.

    Sometimes there is no region to go on. Round 2 at Columbus seats "Colton
    Randolph Crane" at two tables with nothing to separate them, and the page is
    not the place to decide whether that is two Duelists or one printed twice.
    Those names come back as ambiguous, and nothing is derived from them.
    """
    shared: set[str] = set()
    ambiguous: set[str] = set()
    for s in sources:
        if s.post.kind != "pairings" or not s.post.table:
            continue
        seen: dict[str, str | None] = {}
        for row in s.post.table.rows:
            for side in ("a", "b"):
                cell = row.get(side) or {}
                nm, region = cell.get("name"), cell.get("region")
                if not nm:
                    continue
                if nm in seen:
                    (shared if seen[nm] != region else ambiguous).add(nm)
                seen.setdefault(nm, region)
    if not shared:
        return shared, ambiguous

    def relabel(cell: dict) -> None:
        nm, region = cell.get("name"), cell.get("region")
        if nm in shared and region:
            cell["name"] = f"{nm} ({region})"

    for s in sources:
        for row in (s.post.table.rows if s.post.table else []):
            if s.post.kind == "pairings":
                for side in ("a", "b"):
                    if row.get(side):
                        relabel(row[side])
            elif s.post.kind == "standings":
                relabel(row)
    return shared, ambiguous


def relabel_the_swiss_tail(by_round: dict) -> None:
    """A bracket the blog numbered like Swiss rounds.

    Team YCS Atlanta publishes fourteen rounds and calls every one of them a
    round. Its own winner post says what they were:

        After 10 rounds of Swiss and 4 rounds of Single Elimination, Team TCG
        Collectibles Fala Galera ... bested all other teams

    Swiss does not halve. These do -- 4 matches then 2 -- and a run that halves
    down to a bracket at the end of an event with no cut at all is that
    event's cut, whatever its rounds were called. Left as Swiss, the archive
    had no cut round, so it had nobody to ask about a champion and no team
    match to read a roster from.

    Only where the format has no cut of its own, only a trailing run, and only
    down to a size a bracket could be. Two events in the archive look like
    this; every other event with a bracket says so.
    """
    if any(k[0] == "cut" for k in by_round):
        return
    swiss = sorted((k for k in by_round if k[0] == "swiss"), key=lambda k: k[1])
    played = [k for k in swiss if (by_round[k].get("pairings") is not None)]
    if not played:
        return
    run = [played[-1]]
    while True:
        here = _matches(by_round[run[0]])
        before = played[played.index(run[0]) - 1] if played.index(run[0]) else None
        if before is None or _matches(by_round[before]) != here * 2:
            break
        run.insert(0, before)
    held = _matches(by_round[run[-1]]) * 2
    if held < 4 or held & (held - 1) or len(run) < 2:
        return
    for i, key in enumerate(reversed(run)):
        size = held << i
        by_round[("cut", f"Top {size}")] = by_round.pop(key)


def _matches(entry: dict) -> int:
    """How many matches a round published, or 0."""
    post = entry.get("pairings")
    return len(post.post.table.rows) if post else 0


def relabel_by_size(by_round: dict) -> None:
    """A cut round is named for how many Duelists are still in it.

    So a Top N holds N/2 matches, and that holds for all 455 cut rounds in the
    archive without a single exception. The 2019 North America WCQ publishes a
    post titled "North America WCQ: Top 4 Pairings" holding four:

        1  Nguyen, Thanh Cong    vs.  Dawar, Manav
        2  Dominguez, Abdur Rahim vs. Dai, Raymond Young
        3  Rayos, Brian          vs.  Li, Wei
        4  Angeloff, Dakota Clint vs. Gueye, Maguette Laye

    Eight Duelists, which is a Top 8. The same event titles its Top 64 post
    with 32 matches and its Top 16 post with 8, so this one is a slip rather
    than a convention -- and read as written it made the Top 4 a team round of
    two a side, which took 115 posts out of the archive.

    The count of matches is data and the title is something someone typed, so
    the count wins. Only the pairings move: a standings table filed under the
    same name is a different post making its own claim, and is left where it
    is. Nothing moves onto a name already taken, or off a team round, whose
    rows are matches rather than duels and do not count this way.
    """
    for key in [k for k in by_round if k[0] == "cut"]:
        want = re.fullmatch(r"Top (\d+)", key[1])
        post = by_round[key].get("pairings")
        if not want or post is None:
            continue
        rows = post.post.table.rows
        if not rows or any(r.get("duels") for r in rows):
            continue
        held = len(rows) * 2
        fixed = (key[0], f"Top {held}")
        # And only onto a bracket that could exist. Every one of the archive's
        # 527 cut rounds is a power of two, 4 through 64, so a count that is
        # not one says the table is partial rather than the title wrong -- and
        # "Top 6" would be a worse answer than the one already there.
        if held & (held - 1) or held < 4:
            continue
        if held == int(want.group(1)) or fixed in by_round:
            continue
        by_round[fixed] = {"pairings": by_round[key].pop("pairings")}
        if not by_round[key]:
            del by_round[key]


def build_format(name: str | None, sources: list[Source], *,
                 ongoing: bool = False, announcements: list[Source] = (),
                 event_date: str | None = None) -> dict | None:
    """Assemble one format's tournament.

    `name` is None for an event that runs a single tournament and never names a
    format -- the North America WCQ titles every post "North America WCQ: Round
    N Pairings". Left as None rather than invented, so the page shows the event
    without claiming it was played under a format nobody stated.

    `ongoing` says whether coverage is still arriving. It defaults to False so a
    caller that does not know cannot accidentally claim a round is live: an event
    wrongly shown as finished is merely stale, while one wrongly shown as live is
    telling the reader to refresh for results that will never come.
    """
    # Before anything reads a name: one Duelist spelled two ways is as bad as
    # two Duelists spelled one way, and both have to be settled once, up front,
    # so the pairings, the standings and the derivation all see the same people.
    # Folding comes first -- a collision between names nobody has reconciled yet
    # is a collision between spellings, not between Duelists.
    folded = reconcile_names(sources)
    if folded:
        print(f"  {name or 'main event'}: {len(folded)} "
              f"{'name' if len(folded) == 1 else 'names'} folded into their "
              f"longer form ({', '.join(f'{k} -> {v}' for k, v in sorted(folded.items())[:3])}"
              f"{', ...' if len(folded) > 3 else ''})")
    shared, ambiguous = disambiguate(sources)
    for label, names in (("separated by region", shared),
                         ("left underived, nothing tells them apart", ambiguous)):
        if names:
            print(f"  {name or 'main event'}: {len(names)} shared "
                  f"{'name' if len(names) == 1 else 'names'} {label} "
                  f"({', '.join(sorted(names))})")

    by_round: dict[tuple, dict[str, Source]] = defaultdict(dict)
    features: dict[tuple, list[Source]] = defaultdict(list)
    floating_standings: list[Source] = []
    for s in sources:
        if s.post.kind not in ("pairings", "standings", "feature"):
            continue
        # A pairings post *is* its pairings table, and a standings post its
        # standings table. One carrying neither -- no table at all, or a table
        # that read as something else -- is not a round source. Dropping it here
        # rather than guarding each read keeps the invariant in one place: five
        # of the reads downstream assume the columns of their own kind, and a
        # standings row has no "table" key to give them.
        #
        # Checking only for a missing table was not enough. A backfill of seven
        # events fetched 629 pages and one of them, live, came back with a
        # different first table than the same URL serves from cache -- so the
        # pairings loop read a standings row, and a KeyError took down the run
        # and the six events it had already built.
        #
        # Said out loud rather than skipped quietly: a round dropped here makes
        # every record in its format partial, which is worth being able to trace
        # back to the page that caused it.
        if s.post.kind in ("pairings", "standings") and (
                s.post.table is None or s.post.table.kind != s.post.kind):
            found = s.post.table.kind if s.post.table else "no"
            print(f"  ignored {s.url}: a {s.post.kind} post carrying "
                  f"{'an' if found[0] in 'aeiou' else 'a'} {found} table")
            continue
        key = round_key(s.post)
        if key is None:
            # "Final Standings After Swiss" names no round, correctly -- it is
            # the table at the end of Swiss, not a round of its own. Held aside
            # and attached below, once the last Swiss round is known.
            if s.post.kind == "standings":
                floating_standings.append(s)
            continue
        # A round can carry more than one feature match, and 102 of the 357
        # rounds that have one have more than one -- YCS Montreal's Top 4 had
        # three. Keeping the best of them threw away two thirds of the Duelists
        # the blog wrote about that round, so all of them are kept and the
        # panel shows all of them.
        #
        # Sorted rather than appended, so the same scrape twice running gives
        # the same answer and the readable ones lead.
        if s.post.kind == "feature":
            features[key].append(s)
            continue
        existing = by_round[key].get(s.post.kind)
        if existing is not None and not better_table(s, existing):
            continue
        by_round[key][s.post.kind] = s
    # A round the blog covered with a feature match and nothing else is still a
    # round -- five of the 2026 North America WCQ's arrived that way -- so its
    # key has to exist even though no table put it there.
    for key in features:
        by_round[key]
    relabel_the_swiss_tail(by_round)
    relabel_by_size(by_round)
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

    def standings_run(limit: int) -> tuple[list[list[dict]], int]:
        """The unbroken run of standings tables ending at `limit`, and where it
        starts.

        Consecutive is the whole requirement: each round-on-round move in a
        player's points is one match, and a missing round leaves a gap nobody
        can attribute. The run is taken backwards from the round being reported
        so it always reaches it, and it stops at the first round the blog did
        not publish -- which is usually round one, whose table would say only
        that everybody has either three points or none.
        """
        published = {k[1]: by_round[k]["standings"].post.table.rows
                     for k in swiss_keys if "standings" in by_round[k]}
        if limit not in published:
            return [], 0
        first = limit
        while (first - 1) in published:
            first -= 1
        return [published[n] for n in range(first, limit + 1)], first

    # Filled by the last Swiss round as it is built, then read by the cut rounds
    # that follow it. swiss_keys sorts before cut_keys, so it is always populated
    # before anything needs it -- but default to empty rather than rely on that,
    # since an event whose Swiss standings never arrived should show nothing in
    # the cut rather than fail to build at all.
    final_standings: list[dict] = []
    by_player: dict[str, dict] = {}
    # Records as they stood after each round that published a standings table.
    # A pairing for round N wants the table from N-1: that is the record each
    # Duelist carried into the match.
    records_after: dict[int, dict[str, dict]] = {}

    def cut_records(key) -> dict[str, dict]:
        """Each Duelist's record going into this bracket round.

        Their Swiss record plus the bracket matches they have already won, and
        winning is the only way to still be here: a Duelist paired in the Top 4
        beat someone in the Top 8, so every earlier cut round they appear in is
        one more win. The same reasoning as counting Swiss appearances, and the
        same reason it is sound -- it reads what happened rather than assuming a
        result. Losses do not move; a bracket loss is the last thing a Duelist
        appears in.
        """
        earlier = [k for k in cut_keys if cut_rank(k[1]) < cut_rank(key[1])]
        wins_before: Counter = Counter()
        for k in earlier:
            post = by_round[k].get("pairings")
            if not post:
                continue
            for row in post.post.table.rows:
                for side in ("a", "b"):
                    name = (row.get(side) or {}).get("name")
                    if name:
                        wins_before[name] += 1

        out = {}
        for name, rec in by_player.items():
            extra = wins_before.get(name, 0)
            if not extra or rec.get("wins") is None:
                out[name] = rec
                continue
            out[name] = {**rec, "wins": rec["wins"] + extra}
        return out

    def feature_of(source):
        """One feature match, as much of it as the post actually says.

        Deck and record stay None: a feature post is prose and photographs with
        no table in it, so the title is the only structured thing about it. Their
        Swiss records are known, but not as of that round -- printing a final
        record beside a round-two match would be a plausible-looking lie.
        """
        if source is None:
            return None
        players = feature_players(source.post.title)
        if not players:
            return None
        a, b = players
        return {
            "a": {"name": a, "deck": None, "record": None},
            "b": {"name": b, "deck": None, "record": None},
            "note": "Feature match coverage published by Konami.",
            "source": source.url,
        }

    def features_of(key):
        """Every feature match the round carries, newest first.

        A title whose Duelists cannot be read names nobody, and a panel of
        nobodies is worse than a shorter panel, so those are dropped rather
        than shown empty -- which is also what kept YCS Philadelphia's Top 64
        from being a round holding nothing at all.
        """
        newest = sorted(features.get(key, ()),
                        key=lambda s: s.posted or "", reverse=True)
        return [f for f in (feature_of(s) for s in newest) if f]

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
            # Before the ties were abolished, points alone cannot separate one
            # win from three draws -- so the date is stated, and where it says
            # draws were possible the only sound reading is the round-on-round
            # one. Without the date every event was derived as if ties had never
            # existed, which left 34,030 records claiming a whole number of wins
            # their own points contradict.
            series, series_from = standings_run(through)
            recs = derive(table, window, round_numbers=window_rounds,
                          ambiguous=ambiguous, event_date=event_date,
                          standings_series=series, series_from=series_from)

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
                    # Only the records that counted appearances to get their
                    # losses. One read round on round from the standings does
                    # not depend on the pairings at all, and one that already
                    # knows nothing must not be promoted to knowing half.
                    if (r.confidence == "derived" and not r.from_series
                            and r.name not in stated):
                        r.losses, r.confidence = None, "partial"
            by_name = {r.name: r for r in recs}
            for row in standings_post.post.table.rows:
                r = by_name.get(row["name"])
                standings.append({
                    "pos": row["rank"],
                    "name": row["name"],
                    # Who is on the team. Absent for an ordinary entrant, who
                    # is one person and needs no roster.
                    **({"members": row["members"]} if row.get("members") else {}),
                    "record": r.to_record() if r else None,
                    "points": row.get("points"),
                    "deck": None,
                    "pct": None,
                })

        # A cut round has no standings table of its own: the bracket is seeded
        # from the end of Swiss and nothing is published after it. It names that
        # table in standingsAfter and the page follows the reference, rather than
        # each cut round carrying its own copy -- three copies of 766 rows took
        # rounds.json from 1.4MB to 2.3MB, downloaded on every visit, to say the
        # same thing three times.

        pairings_post = entry.get("pairings")
        pairings = []
        if pairings_post is not None:
            # The record each Duelist brought to the table. For a bracket round
            # that is their Swiss record plus the bracket matches they have won;
            # for a Swiss round it is whatever the previous round's standings
            # said, which exists for the later rounds and not the early ones --
            # rounds 1-8 publish standings with no points column at all, so a
            # record going into round 4 is not something this can know.
            records = cut_records(key) if is_cut else records_after.get(key[1] - 1, {})
            def seat(duel: dict) -> dict:
                return {"table": duel["table"],
                        "a": duel["a"]["name"], "aDeck": duel["a"].get("deck"),
                        "b": duel["b"]["name"], "bDeck": duel["b"].get("deck")}

            for row in pairings_post.post.table.rows:
                pairings.append({
                    "table": row["table"],
                    "a": row["a"]["name"], "aRec": records.get(row["a"]["name"]),
                    "aDeck": row["a"].get("deck"),
                    "b": row["b"]["name"], "bRec": records.get(row["b"]["name"]),
                    "bDeck": row["b"].get("deck"),
                    # A team match is one row holding the three duels played
                    # inside it. The row itself is the match -- team against
                    # team -- which is what the standings rank and what a record
                    # is derived for; the duels are who sat where.
                    **({"duels": [seat(d) for d in row["duels"]]}
                       if row.get("duels") else {}),
                })

        if not is_cut and standings:
            here = {r["name"]: r["record"] for r in standings if r.get("record")}
            records_after[key[1]] = here
            # The last Swiss round's table is also what the cut is seeded from.
            if key == swiss_keys[-1]:
                final_standings = standings
                by_player = here

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
            "features": features_of(key),
            "source": source.url if source else None,
        })

    # A final the coverage played but never paired. Appended rather than built in
    # the loop above, because it comes from the standings annotations and not
    # from a post of its own, and only when no cut round already covers it.
    finalists = final_from_annotations(floating_standings)
    if finalists and not any(cut_rank(k[1]) >= cut_rank("Final") for k in cut_keys):
        runner_up, champion = finalists
        records = cut_records(("cut", "Final"))
        seed = by_round[cut_keys[-1]].get("pairings") if cut_keys else None
        rounds.append({
            "id": "Final",
            "label": "Final",
            "phase": "Top cut",
            "state": "done",
            "order": CUT_ORDER_BASE + cut_rank("Final"),
            "tables": 1,
            "posted": clock(seed.posted) if seed else None,
            "standingsAfter": swiss_count,
            "pairings": [{
                "table": 1,
                "a": champion, "aRec": records.get(champion), "aDeck": None,
                "b": runner_up, "bRec": records.get(runner_up), "bDeck": None,
            }],
            "standings": [],
            "features": [],
            # The standings that say the final happened, since it has no post.
            "source": next((c.url for c in floating_standings
                            if any(r.get("status") == "cut"
                                   for r in (c.post.table.rows if c.post.table else []))),
                           None),
        })

    # The newest round with pairings but no results yet is the one in progress --
    # but only while the event still is. A finished event's last round is its
    # final, and calling it "in progress" is a claim about right now that the
    # data cannot support: YCS Montreal went to production reading "Top 4 · IN
    # PROGRESS" twelve days after it ended.
    if rounds and ongoing:
        rounds[-1]["state"] = "live"

    # A round nothing was published for is not a round. One is created whenever
    # a post names it and carries nothing -- a feature match whose title will
    # not parse into two Duelists, or a side event's write-up naming a Final
    # the main event has not reached. Left in, it is an empty row on the track,
    # and the deploy refuses the whole event over it.
    #
    # Dropped rather than reported, because a round the blog never posted is
    # already something this archive lives with: the count present may be lower
    # than the count played, and that is stated rather than treated as damage.
    rounds = [r for r in rounds
              if r["pairings"] or r["standings"] or r.get("features")]

    field = max((len(r["standings"]) for r in rounds), default=0)
    # Result posts naming no format are considered too. A two-format event
    # usually titles them "And the Advanced Format Winner is", but not always,
    # and one that does not would otherwise be dropped with the rest of the
    # unassigned posts and take its event's champion with it. Safe to offer to
    # both tournaments, because each asks only about its own cut: a post naming
    # nobody in this bracket claims nobody here.
    # A team is named by its Duelists, not by the name it entered under.
    won_by = champion_named(cut_finalists(rounds),
                            [{"title": s.post.title, "text": s.post.lead,
                              "kind": s.post.kind}
                             for s in list(sources) + list(announcements)
                             if s.post.lead],
                            name, rosters=cut_rosters(rounds))
    # What one entrant is. A Team YCS ranks teams of three, so "389 Duelists"
    # would be 389 teams under the wrong noun -- and the page has no way to know
    # from the rows themselves, because a team match reads exactly like a match.
    return {"format": name, "entrant": "Team" if entered_as_teams(sources) else "Duelist",
            "swissRounds": swiss_count, "duelists": field,
            # Who won, where the coverage says so plainly enough to be sure.
            # Null is the common answer and a real one: most events never
            # publish a final, and the post announcing a winner is not always
            # there. See winners.py for why nothing is guessed at.
            "champion": won_by,
            "rounds": rounds}


def cut_finalists(rounds: list[dict]) -> list[str]:
    """The Duelists in the deepest round of the cut that was published.

    Whoever won was one of them. Only the cut, never Swiss: a Swiss round holds
    most of the field, and asking a winner post which of two hundred names it
    mentions is the loose question that produced wrong champions.
    """
    played = [r for r in rounds if r.get("phase") == "Top cut" and r.get("pairings")]
    if not played:
        return []
    return [row[side] for row in played[-1]["pairings"]
            for side in ("a", "b") if row.get(side)]


def cut_rosters(rounds: list[dict]) -> dict[str, list[str]]:
    """Each team in the deepest cut round, and the Duelists who played for it.

    A team enters under a name it chose and the coverage announces its win by
    naming the people:

        "Pierre Burgals, Matthieu Bricard, and Kevin Rodrigues Goncalves are
         the TEAM YCS Las Vegas Champions!!"
        "Stephen Silverman, Dominic Couch, and Alexander Cancell"

    So the team name is not what identifies the team. Its Duelists are, and
    they are already here: a team match carries the three duels it was decided
    by, and each duel names both sides.

    Empty for a singles event, where a pairing has no duels inside it.
    """
    played = [r for r in rounds if r.get("phase") == "Top cut" and r.get("pairings")]
    if not played:
        return {}
    out: dict[str, list[str]] = {}
    for row in played[-1]["pairings"]:
        for side in ("a", "b"):
            if not (team := row.get(side)):
                continue
            who = [duel[side]["name"] if isinstance(duel.get(side), dict) else duel.get(side)
                   for duel in row.get("duels") or []]
            if named := [w for w in who if w]:
                out[team] = named
    return out


def entered_as_teams(sources: list[Source]) -> bool:
    """Whether this event's entrants are teams rather than individual Duelists.

    A Team YCS enters three a side. Its standings hold one row per team with
    the members inside it, and its pairings hold one row per team match with
    the three duels inside that. The parser reads both, so this is a question
    about the shape it produced rather than about punctuation in a name.

    What it decides is what the page calls them, and that is the whole of it:
    everything downstream already works on entrants without caring whether an
    entrant is one person or three.
    """
    for s in sources:
        for row in (s.post.table.rows if s.post.table else []):
            if row.get("members") or row.get("duels"):
                return True
    return False


def better_table(candidate: Source, existing: Source) -> bool:
    """Whether `candidate` is the pairings or standings to use for a round.

    Two posts can claim one round. Sometimes it is the same table published
    twice; sometimes it is two events sharing a weekend, which the January 2022
    Remote Duel YCS did with the Latin America one -- both published a Top 32,
    and both landed on the same event.

    Whichever arrived last used to win, which is not a rule at all: the same
    coverage built differently from one run to the next, and an empty table beat
    a full one whenever the empty one happened to be read second. That is how an
    event passed here and was rejected in CI on identical data.

    So the fuller table wins, and the newer breaks a tie. It does not settle
    which event a post belonged to -- nothing here can -- but it does make the
    answer the same every time, and prefers the reading with something in it.
    """
    rows = lambda s: len(s.post.table.rows) if s.post.table else 0
    if rows(candidate) != rows(existing):
        return rows(candidate) > rows(existing)
    return (candidate.posted or "") >= (existing.posted or "")


def is_tournament(fmt: dict) -> bool:
    """Whether a built format is a tournament, or only coverage of one.

    YCS Anaheim's eight Genesys posts are two feature matches, some news and a
    winner, covering a Genesys Invitational held alongside the main event. They
    name a Top 8, so a Top 8 round was built -- with no matches in it, in a
    format with no Duelists and no Swiss rounds. check-rounds.py rejected the
    file, correctly: a cut round of nought matches is not a bracket.

    Coverage of a side event is still coverage and stays in the feed. What it
    is not is a tournament the round track can show.
    """
    return any(r["pairings"] or r["standings"] for r in fmt["rounds"])


def build_event(event: str, sources: list[Source], *,
                coverage_by: str = "Konami",
                draws_possible: bool = False, updated: str | None = None,
                ongoing: bool = False, location: str | None = None) -> dict:
    by_format: dict[str | None, list[Source]] = defaultdict(list)
    for s in sources:
        # A tournament that ran alongside the main event is its own tournament,
        # not a round of the one it ran beside. coverage_format has named these
        # all along and warned in its own docstring what happens when nobody
        # acts on the answer -- and nobody did: the builder grouped by the
        # post's format, which for a WCQ is None for every post, so the Dragon
        # Duel's tables were merged into the main event's bracket.
        #
        # The 2018 South America WCQ was refused over exactly that. It has no
        # Top 8 pairings post of its own, so the Dragon Duel's stood in as one:
        #
        #   Top 8   south-america-dragon-duel-wcq-pairings-for-top-8
        #   Top 4   south-america-wcq-pairings-for-top-4
        #
        # Eight children who never played in the Top 16, and a Top 4 that never
        # played in that Top 8. Forty-five posts left the archive over it.
        by_format[coverage_format(s.post.title, s.post.fmt)].append(s)

    # Posts naming no format are usually announcements -- 19 of YCS Montreal's
    # belong to the event rather than to either of its tournaments -- so they
    # are not merged into one, which would misfile them.
    #
    # But some events run a single tournament and never name a format at all.
    # The North America WCQ publishes "North America WCQ: Round 10 Pairings",
    # twelve rounds of them, and a rule that only builds named formats threw
    # away the entire event: 62 posts, nine rounds of pairings, no tournament.
    #
    # A tournament is a thing with rounds and standings, so that is the test.
    # The announcements fail it and stay out; the WCQ passes it and is built,
    # under no format name because it has none to state.
    loose = by_format.pop(None, [])
    kinds = {s.post.kind for s in loose}
    unassigned = 0 if {"pairings", "standings"} <= kinds else len(loose)
    # Kept even when the rest of the unassigned posts are dropped: which
    # tournament a winner belongs to is answered by the brackets, not by the
    # post's own title, so these are worth offering to both. The final's own
    # write-up counts, and rarely names a format -- "Finals Feature Match: Ada
    # Lovelace vs Bo Peep" says which two Duelists and nothing else.
    announcements = [s for s in loose
                     if s.post.kind == "result"
                     or (s.post.kind == "feature" and s.post.lead)]
    if unassigned:
        loose = []

    # The day the event ran, which is what says whether ties were still policy.
    # `updated` is the end of its coverage, which is the same day or the one
    # after -- close enough for a rule that changed once, in 2025.
    on = (updated or "")[:10] or None
    formats = [f for f in (build_format(name, group, ongoing=ongoing,
                                        announcements=announcements, event_date=on)
                           for name, group in sorted(by_format.items()))
               if f and is_tournament(f)]
    if loose and (only := build_format(None, loose, ongoing=ongoing,
                                       event_date=on)) and is_tournament(only):
        formats.append(only)
    return {
        "event": event,
        # Which builder wrote this, so a later one can find what it has to redo.
        "built": BUILD_VERSION,
        # Where it was held, when that is known. Kept beside the name rather
        # than inside it: "YCS Santiago" is what the event is called, and that
        # it was in Chile is a separate thing worth knowing.
        **({"location": location} if location else {}),
        # Real coverage. The page reads this to decide whether to show its
        # "Sample data" badge, so it is stated rather than left to be inferred.
        "sample": False,
        "coverageBy": coverage_by,
        "drawsPossible": draws_possible,
        # Stated per event, not inferred by the reader. With an archive of many
        # events the page lists them together, and "is this one still running"
        # is a fact about the event that only the scrape knows -- it is read
        # from how recent the coverage is at fetch time, which nothing looking
        # at the file later can reconstruct.
        "ongoing": ongoing,
        "updated": updated,
        "formats": formats,
        "_unassigned": unassigned,     # posts naming no format; reported, not guessed
    }
