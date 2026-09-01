#!/usr/bin/env python3
"""Who won, read off the post that announces it.

The blog never records a winner as data. The final match's pairing names two
Duelists and does not say which of them took it, and most events do not publish
a final at all -- coverage usually stops at the semis. What there is instead is
a post:

    "Congratulations to Barrett Arthur Keys the winner of YCS Bogota!"
    "Juan Sebastian Andrade Castro is our new South America WCQ Champion."
    "Francisco Osorio ... used his Elfnote Deck to defeat the World Champion"

Reading a name out of prose like that is not something to attempt. Two rules
were tried on the real archive -- take the first name in the post, take the
longest -- and each of them confidently produced a different wrong champion for
the 2013 North America WCQ, which says "Patrick J. Hoban ... defeated David J.
Keener III". One rule picked a Duelist called Patrick Le on the strength of the
word "Patrick"; the other picked Keener, who lost.

So no name is read out of the post at all. The event already knows who could
possibly have won -- the Duelists in the deepest round of its top cut -- and the
post is asked only which of *them* it is talking about. That turns extraction
into recognition, over a handful of candidates rather than the whole field, and
the failure mode becomes "no champion claimed" rather than "the wrong one".

Three things have to hold before a name is claimed:

  * the post announces a winner, by its own title;
  * it is not about one of the side events, which every YCS runs a dozen of and
    which have winners of their own;
  * exactly one of the cut's Duelists is named in it.
"""
from __future__ import annotations

import re

# What the blog calls the tournaments running alongside the main event. Each has
# its own winner and its own congratulatory post, and taking one of those for
# the event's champion is the single easiest mistake to make here: of 266 result
# posts in the archive, 198 are these.
SIDE_EVENT = re.compile(
    r"dragon duel|public event|attack of the giant card|time wizard"
    r"|3\s*v\.?\s*s?\.?\s*3|sealed|win-a-mat|bounty|cosplay|artist|charity"
    r"|raffle|school tournament|ots tournament|speed duel|invitational"
    r"|team tournament",
    re.I)

# A post that announces a winner says so in its title. Deliberately loose --
# "And the Advanced Format Winner is...", "We have a winner!", "Central America
# WCQ Winner!", "...is our new Champion" -- because the work of being careful is
# done by the candidate list, not here. A tight pattern only lost real winners:
# an earlier one required "the winner is" as a phrase and missed YCS Montreal,
# whose post is headed "And the Advanced Format Winner is".
ANNOUNCEMENT = re.compile(r"\bwinners?\b|\bchampions?\b", re.I)

# A post about titles somebody already holds, rather than one won here. "UDS
# Champions at YCS Seattle" is Duelists holding an Ultimate Duelist Series
# invitation, photographed at a YCS; "Welcoming the National Champions of
# South America" is a greeting. Both say "Champions" and neither announces
# anybody's win.
#
# This costs a real champion when it is not caught. YCS Guatemala City 2017
# published its winner and, the same weekend, "UDS Champions at YCS Guatemala"
# -- which names a Duelist who reached the Top 4. Two posts claiming two
# different winners is a disagreement, so the event was left with none.
HELD_ELSEWHERE = re.compile(
    r"\buds champions?\b|\bin attendance\b|\bwelcoming\b|\bhonou?ring\b"
    r"|\btitle belts?\b", re.I)

# A sentence that crowns somebody, rather than looking forward to it. The
# finals feature match is prose, and most of what it says about champions is
# not a result: a preview of what is at stake, or a Duelist's history.
CROWNS = re.compile(r"\bis (?:your|the|our)\b[^.!?]*\bchampions?\b"
                    r"|\bcrown\b|\bchampions? of\b"
                    r"|\bbecomes? (?:your|the|our)\b[^.!?]*\bchampions?\b", re.I)

# What makes such a sentence a prediction, a condition or a biography instead.
# Every one of these was found in a real finals feature match:
#
#   "...is now just a short win away from becoming a YCS Champion!"
#   "One of these Duelists will soon gain the honor..."
#   "Neven is a 2-time YCS Champion, and although Garcia only has 1 YCS win..."
#
# The last is the dangerous one: it is a fact about the runner-up, in the past
# tense, in a post about the match he went on to lose.
HEDGE = re.compile(r"\b(will|would|could|about to|soon|away from|one of|if"
                   r"|going to|hopes?|chance|reigning|\d+-time|two-time)\b", re.I)

# Which side of a beating each name is on. Only consulted when a post names two
# of the cut's Duelists, which is what the final's write-up naturally does.
# Words that put the winner before the loser. Two kinds: beating somebody, and
# saying who came second.
#
# "against" is deliberately not here on its own. YCS San Diego's winner post
# says the champion "had an epic Match against his own brother at YCS Dallas,
# but his brother took the title that time" -- an against about a different
# tournament a year earlier, sitting exactly where this rule looks. Only
# "victory against", which is what winning the final is called, and the two
# phrases that name the loser as the loser.
DEFEAT = re.compile(
    r"\b(defeat(?:ed|s|ing)?|beat|beats|bested|topple[ds]?|overcame|overcome"
    r"|won against|victorious over|victory (?:against|over)"
    r"|in second place|runner-?up)\b", re.I)

# Which format a post is about, where it says. A two-format event publishes two
# of these posts and they must not be read against each other's brackets.
_FORMAT = re.compile(r"\b(advanced|genesys)\b", re.I)


def named_in(name: str, text: str) -> int:
    """Where a recorded name is named in prose, or -1.

    The blog writes shorter forms than the tables do: "Francisco Osorio" for
    "Francisco Andres Osorio Bobadilla", "Hani Jawhari" for "Hani Yasser
    Jawhari". So the prose is searched for the recorded name's own words and
    two of them have to be there.

    Two, not all, because the dropped word is often the last: Spanish and
    Portuguese names carry two surnames and the blog usually prints one. And
    not one, because a lone forename is not identification -- "Patrick" is the
    whole of what a rule matching on one word had to go on when it decided the
    2013 North America WCQ had been won by a Patrick who was not there.

    A name that is only one word can therefore never match, which is the right
    answer for the team events: they enter as "Legionnaire" and one word of
    ordinary prose is not a team.
    """
    words = [w for w in re.split(r"[^A-Za-z]+", name.lower()) if len(w) > 1]
    low = text.lower()
    at = [low.find(w) for w in words]
    present = [p for p in at if p >= 0]
    return min(present) if len(present) >= 2 else -1


def about_format(title: str) -> str | None:
    """The format a winner post names, or None if it names none."""
    m = _FORMAT.search(title or "")
    return m.group(1).title() if m else None


# An aside, set off by dashes or brackets, is about a person and not about the
# post. The 2026 North America WCQ's winner announcement opens:
#
#   "2077 Duelists competed in the 2026 North America World Championship
#    Qualifier, and one Duelist -- a former Dragon Duel World Champion and
#    former MASTER DUEL World Champion -- emerged on top! Ryan Yu from
#    Ontario, Canada used his Sky Striker Deck..."
#
# Read whole, that is a Dragon Duel post and the event lost its champion. Read
# without the aside it is what it plainly is: the WCQ's own result, with a line
# of biography about the man who won it. The same mistake the hedge rule was
# written for -- "Neven is a 2-time YCS Champion" is a fact about a person, in
# a post about the match he lost.
_ASIDE = re.compile(r"\s[\u2010-\u2015]\s.*?\s[\u2010-\u2015]\s|\([^)]*\)", re.S)


def announces_a_winner(title: str, opening: str = "", fmt: str | None = None) -> bool:
    """Whether this post announces the winner of the tournament being asked about.

    The opening of the body is read as well as the title, because a side event
    is not always named in the heading -- "And the Winner Is..." is used for the
    Dragon Duel playoff as readily as for the event itself, and the first line
    says which.

    What the first line says about the event, not what it says about the
    Duelist: an aside naming a title somebody used to hold is biography, and
    reading it as the subject of the post costs the event its champion.

    `fmt` is the tournament asking. A side event's winner post is not the main
    event's result and never was -- but since the builder began grouping those
    tournaments separately, the Dragon Duel is a tournament of its own with its
    own bracket, and this rule was refusing it its own championship:

        And the new North American Dragon Duel Champion is...
        Congratulations to Aiden Christopher Tiemann of Austin, Texas...

    Aiden is in that bracket's Top 8. Four events had a Dragon Duel winner post
    naming a Duelist who was right there in the cut, and no champion.
    """
    if not ANNOUNCEMENT.search(title or ""):
        return False
    if HELD_ELSEWHERE.search(title or ""):
        return False
    said = _ASIDE.sub(" ", opening[:400])[:160]
    if HELD_ELSEWHERE.search(said):
        return False
    # Named anywhere -- heading or first line -- and not the tournament asking.
    for text in (title or "", said):
        if (found := SIDE_EVENT.search(text)) and not _asked_about(found.group(0), fmt):
            return False
    return True


def _asked_about(found: str, fmt: str | None) -> bool:
    """Whether the side event a post names is the tournament asking about it.

    Loose on purpose: SIDE_EVENT matches "public event" where the builder calls
    the tournament "Public Events", so the shorter is checked against the
    longer rather than the two being required to be equal.
    """
    if not fmt:
        return False
    a, b = found.strip().lower(), fmt.strip().lower()
    return a in b or b in a


def crowning(text: str) -> str:
    """The sentence in which a post crowns somebody, or "".

    Read from the end, because that is where a result is and the previews are
    at the front. A sentence that hedges, or that is about one of the side
    events, is not a result whatever else it says.
    """
    for sentence in reversed(re.split(r"(?<=[.!?])\s+", text or "")):
        if not CROWNS.search(sentence):
            continue
        if HEDGE.search(sentence) or SIDE_EVENT.search(sentence):
            continue
        return sentence
    return ""


def _bare(name: str) -> str:
    """A name reduced to its words, for asking whether one contains another."""
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def champion(candidates: list[str], posts: list[dict], fmt: str | None = None,
             rosters: dict[str, list[str]] | None = None) -> str | None:
    """Which of these Duelists the coverage says won, or None.

    `candidates` are the Duelists in the deepest round of the cut that was
    published. `posts` are the event's result posts, each a dict with a title
    and the opening of its text.

    None is a real answer and the common one. An event whose winner post was
    never published, or whose cut is not in the archive, has no champion here
    rather than a guess at one.
    """
    claimed = set()
    for post in posts:
        title, text = post.get("title") or "", post.get("text") or ""
        if post.get("kind") == "feature":
            # A feature match is prose about two Duelists, and it names both of
            # them throughout -- so unlike a winner post, the whole of it says
            # nothing about which one took it. One sentence does, and only that
            # sentence is read.
            text = crowning(text)
            if not text:
                continue
        elif not announces_a_winner(title, text, fmt):
            continue
        # A post that names a format is about that format's bracket and no
        # other. One that names none is read against whichever is asking.
        said = about_format(title)
        if fmt and said and said != fmt:
            continue
        # A team is recognised by whoever played for it. It enters under a
        # name it chose -- "Ares", "Legionnaire" -- and one word is not a
        # name that ordinary prose can be searched for, which is why a team
        # event has had no champion unless the post happened to quote it.
        # The Duelists are what the coverage names:
        #
        #   "Pierre Burgals, Matthieu Bricard, and Kevin Rodrigues Goncalves
        #    are the TEAM YCS Las Vegas Champions!!"
        #
        # Whichever of the two names is found first stands for the team, so a
        # post that says "defeated" still reads the right way round.
        def where(name: str, hay: str) -> int:
            found = [at for who in [name] + list((rosters or {}).get(name, []))
                     if (at := named_in(who, hay)) >= 0]
            return min(found) if found else -1

        named = sorted((at, name) for name in candidates
                       if (at := where(name, text)) >= 0)
        # A team whose name is inside another team's name is not independently
        # named. Team YCS Atlanta's Top 4 holds both "TCG Collectibles", who
        # came fourth, and "Team TCG Collectibles Fala Galera", who won, and
        # every word of the first is in the second -- so the sentence naming
        # the champion looked like a sentence naming two teams, and the event
        # had no champion.
        inside = {_bare(n) for _, n in named}
        named = [(at, n) for at, n in named
                 if not any(_bare(n) != other and _bare(n) in other for other in inside)]
        if len(named) == 1:
            claimed.add(named[0][1])
        elif len(named) > 1:
            # The final's write-up names both Duelists. Whoever is on the near
            # side of "defeated" won it.
            beat = DEFEAT.search(text)
            if beat and named[0][0] < beat.start() <= named[1][0]:
                claimed.add(named[0][1])
            else:
                # No such word, which is the commoner case: the blog crowns the
                # winner in one sentence and mentions who they beat in the
                # next.
                #
                #   Overcoming 716 other Duelists, Anderson Tsang is your
                #   newest YCS Champion! He piloted his Infernoid Deck to
                #   victory against Leonard Anaya's Zoodiac Deck in the Finals.
                #
                # Read whole, that names two finalists and nothing says which
                # way round -- YCS Denver had no champion on the strength of
                # it. The sentence that does the crowning names one of them,
                # and that is the one being crowned.
                #
                # Only where exactly one is in it. "X defeated Y to become
                # Champion" puts both in that sentence, and is answered above
                # or not at all -- a guess is worse than no champion.
                said = crowning(text)
                inside = [name for _, name in named if where(name, said) >= 0]
                if len(inside) == 1:
                    claimed.add(inside[0])
    # Two posts naming two different winners is a disagreement, not a result.
    return claimed.pop() if len(claimed) == 1 else None
