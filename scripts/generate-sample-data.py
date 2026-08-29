#!/usr/bin/env python3
"""Generate the site's sample data: rounds.json and feed.xml.

Both come from one simulated tournament, so they agree. Previously the feed
announced "Round 12 pairings are up" while the round panel showed the same
eight tables for every round; nothing referenced anything real.

The simulation is a genuine Swiss run: players are paired against others on
the same record, results decide the next pairing, and standings are sorted by
wins with opponent match-win percentage as the tiebreak. Records therefore add
up -- an 11-0 Duelist in round 12 really did win eleven matches here.

Deterministic: seeded PRNG, and every timestamp derives from --now. Re-running
with the same --now reproduces the file byte for byte.
"""
import argparse, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import archive                                              # noqa: E402
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

SEED = 20260828
# The archive keys events by slug, so the simulation needs one. Fixed rather
# than derived from the month in the event's name, so regenerating on a
# different day does not leave a second sample event behind in the archive.
SLUG = "sample-remote-duel-ycs"
FIELD = 64                 # simulated field; the page shows the top 8 of it
# Real events run parallel tournaments with different round counts: at YCS
# Montreal the Advanced main event ran 13 Swiss rounds and Genesys 11.
FORMATS = [
    {"format": "Advanced", "swiss": 12, "field": 1248, "seed_offset": 0},
    {"format": "Genesys",  "swiss": 10, "field": 384,  "seed_offset": 991},
]
SWISS = 12                 # longest format; used for the posting timeline
ANNOUNCED = 1248           # headline field size for the event
GAP = 38                   # minutes from one round posting to the next
LEAD = 12                  # minutes between the newest round posting and `now`

SURNAMES = """Okonkwo Alvarez Lindqvist Nakamura Wexler Boateng Duval Petrov Marchetti Zhao
Ferreira Haddad Rasmussen Osei Bergstrom Castellanos Ibarra Novak Takahashi Mwangi Sorensen
Delacroix Kowalski Almeida Nguyen Adeyemi Rossi Fischer Dlamini Varga Sasaki Ortega Bakker
Larsen Chibuzo Moreau Ivanov Yildiz Santoro Keller Abadi Pereira Lund Hassan Moretti Blomqvist
Aguilar Vermeulen Kimura Osborne Bianchi Traore Nowak Reinhardt Espinoza Falk Mbeki Guerrero
Halvorsen Ricci Amara Sundqvist Costa Weber""".split()
INITIALS = "RMJPDSKATLCNEVHIGBFOWZY"
DECKS = ['Maliss','Ryzeal','Fiendsmith','Mitsurugi','Voiceless Voice','Snake-Eye','Yubel','Tenpai Dragon']


def event_anchor(clock):
    """The instant the timeline hangs off: `clock`, or the last one a day fits.

    Rounds are laid out backwards from here, and each carries a bare "HH:MM"
    posting time -- the page shows one event day, with no date to tell rounds
    on either side of a midnight apart. Anchored in the small hours the event
    ran across one: `updated` named a time today while the rounds it summarised
    posted yesterday, and check-rounds.py rightly rejected the pair. Sliding
    the whole event back to the end of the previous day keeps every stamp on a
    single date, and still puts the newest one in the past.
    """
    span = timedelta(minutes=(max(spec["swiss"] for spec in FORMATS) + 1) * GAP + LEAD)
    if span >= timedelta(days=1):
        # No anchor would help: the event itself no longer fits a calendar day,
        # so its posting times cannot be read as one without a date beside them.
        sys.exit("simulated event runs {} -- longer than the day its posting "
                 "times are written for".format(span))
    newest, oldest = clock - timedelta(minutes=LEAD), clock - span
    if oldest.date() == newest.date():
        return clock
    return newest.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=1)


def build_field(rng):
    players = []
    for i, surname in enumerate(SURNAMES[:FIELD]):
        players.append({
            'name': f'{INITIALS[i % len(INITIALS)]}. {surname}',
            'deck': DECKS[i % len(DECKS)],
            'w': 0, 'l': 0, 'opps': [],
            'power': rng.uniform(0.35, 0.68),   # latent skill, drives results
        })
    return players


def pair_round(players, rng):
    """Swiss: sort by record, pair down the list, avoid rematches where possible."""
    pool = sorted(players, key=lambda p: (-p['w'], p['l'], p['name']))
    pairs, used = [], set()
    for i, p in enumerate(pool):
        if p['name'] in used:
            continue
        # Look for a fresh opponent, but only nearby. Searching the whole field
        # would avoid rematches at the cost of pairing a 9-2 against a 7-4,
        # which is not Swiss. Close records matter more than a repeat.
        WINDOW = 6
        candidates = [q for q in pool[i + 1:] if q['name'] not in used]
        opponent = next((q for q in candidates[:WINDOW] if q['name'] not in p['opps']), None)
        if opponent is None:                         # accept a rematch to stay in bracket
            opponent = candidates[0] if candidates else None
        if opponent is None:
            break                                    # odd player out -- bye
        used.add(p['name']); used.add(opponent['name'])
        pairs.append((p, opponent))
    return pairs


def play(pairs, rng):
    for a, b in pairs:
        edge = a['power'] / (a['power'] + b['power'])
        winner, loser = (a, b) if rng.random() < edge else (b, a)
        winner['w'] += 1
        loser['l'] += 1
        a['opps'].append(b['name']); b['opps'].append(a['name'])


def duel(a, b, rng):
    """One elimination match. Returns (winner, loser), and updates both records.

    A cut match is still a match: winning the Top 8 takes a Duelist from 9-3 to
    10-3, and that is what the Top 4 pairing should show. The standings table is
    unaffected because it is snapshotted before the cut begins -- Swiss
    standings really are final after the last Swiss round.
    """
    edge = a["power"] / (a["power"] + b["power"])
    winner, loser = (a, b) if rng.random() < edge else (b, a)
    winner["w"] += 1
    loser["l"] += 1
    return winner, loser


def bracket_rows(pairs):
    """Cut pairings reuse the Swiss pairing shape, so the table renders as-is.

    Called before the round is played, so these are entering records: a Top 4
    row shows what each Duelist carried out of the Top 8.
    """
    return [{
        "table": i + 1,
        "a": a["name"], "aRec": rec(a["w"], a["l"]),
        "b": b["name"], "bRec": rec(b["w"], b["l"]),
    } for i, (a, b) in enumerate(pairs)]


def omw(player, by_name):
    """Opponent match-win percentage, the real Swiss tiebreak."""
    if not player['opps']:
        return 0.0
    total = 0.0
    for name in player['opps']:
        o = by_name[name]
        played = o['w'] + o['l']
        total += (o['w'] / played) if played else 0.0
    return 100.0 * total / len(player['opps'])


def rec(w, l, draws=0, confidence="derived"):
    """A record as parts, not a formatted string.

    How much is known varies once records come from scraped coverage: wins are
    exact from points, losses need a player's appearances, and before ties were
    abolished neither is determined by points alone. A baked "6-0-0" cannot
    express that, so the page formats these and shows a ? for what is unknown.
    """
    return {"wins": w, "losses": l, "draws": draws, "confidence": confidence}


def standings_table(players):
    by_name = {p['name']: p for p in players}
    ranked = sorted(players, key=lambda p: (-p['w'], p['l'], -omw(p, by_name), p['name']))
    return [{
        'pos': i + 1,
        'name': p['name'],
        'record': rec(p['w'], p['l']),
        'points': p['w'] * 3,
        'deck': p['deck'],
        'pct': f"{omw(p, by_name):.1f}",
    } for i, p in enumerate(ranked[:8])]


def pairings_table(pairs):
    return [{
        'table': i + 1,
        'a': a['name'], 'aRec': rec(a['w'], a['l']),
        'b': b['name'], 'bRec': rec(b['w'], b['l']),
    } for i, (a, b) in enumerate(pairs[:8])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--now', help='ISO timestamp anchoring the event (default: current UTC)')
    # The simulation used to be written to the repository root, because the root
    # files were what the site served. They now hold real coverage, so writing
    # there would overwrite what is published -- and the test suite, which reads
    # these, would be testing whichever event was scraped last.
    ap.add_argument('--out', default='test/fixtures',
                    help='directory to write the archive and feed.xml into')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clock = datetime.fromisoformat(args.now).astimezone(timezone.utc) if args.now \
        else datetime.now(timezone.utc)
    # Every timestamp below -- the event's month, its round postings, the feed's
    # older entries -- hangs off this one moment, so that they describe a single
    # coherent event rather than the wall clock the generator happened to run on.
    now = event_anchor(clock)

    event = f"Remote Duel YCS {now.strftime('%B %Y')}"
    posts = []
    formats_out = []

    # Each format is an independent tournament: its own field, its own PRNG
    # stream, its own round count.
    for spec in FORMATS:
        rng = random.Random(SEED + spec["seed_offset"])
        players = build_field(rng)
        swiss = spec["swiss"]
        posted_rounds = swiss + 2

        def posted_at(i, _swiss=swiss, _n=posted_rounds):
            return now - timedelta(minutes=(_n - 1 - i) * GAP + LEAD)

        by_name = {p["name"]: p for p in players}

        def feature_of(rows, note):
            top = rows[0]
            return {
                "a": {"name": top["a"], "deck": by_name[top["a"]]["deck"], "record": top["aRec"]},
                "b": {"name": top["b"], "deck": by_name[top["b"]]["deck"], "record": top["bRec"]},
                "note": note,
            }

        rounds = []
        for n in range(1, swiss + 1):
            pairs = pair_round(players, rng)
            entering = pairings_table(pairs)
            stamp = posted_at(n - 1)
            play(pairs, rng)
            rounds.append({
                "id": str(n), "label": f"R{n}", "phase": "Swiss", "state": "done",
                "order": n,
                "tables": spec["field"] // 2,
                "posted": stamp.strftime("%H:%M"), "_stamp": stamp,
                "standingsAfter": n,
                "pairings": entering,
                "standings": standings_table(players),
                "feature": feature_of(entering, f"Table one for round {n}."),
            })
            posts.append((stamp, event, f"{spec['format']} Round {n} pairings are up", "pairings"))
            posts.append((stamp + timedelta(minutes=22), event,
                          f"{spec['format']} standings after round {n}", "standings"))
            top = entering[0]
            if n in (6, swiss):
                posts.append((stamp + timedelta(minutes=9), event,
                              f"Feature match: {by_name[top['a']]['deck']} against "
                              f"{by_name[top['b']]['deck']} ({spec['format']})", "feature"))
            if n == swiss - 2:
                posts.append((stamp + timedelta(minutes=30), event,
                              f"The {spec['format']} decks still in contention", "deck"))

        final_table = standings_table(players)
        seeds = [by_name[r["name"]] for r in final_table]

        t8_pairs = [(seeds[0], seeds[7]), (seeds[1], seeds[6]),
                    (seeds[2], seeds[5]), (seeds[3], seeds[4])]
        t8_rows = bracket_rows(t8_pairs)
        t8_stamp = posted_at(swiss)
        t8_winners = [duel(a, b, rng)[0] for a, b in t8_pairs]
        rounds.append({
            "id": "T8", "label": "Top 8", "phase": "Top cut", "state": "done",
            "order": 100,
            "tables": len(t8_pairs), "posted": t8_stamp.strftime("%H:%M"), "_stamp": t8_stamp,
            "standingsAfter": swiss, "pairings": t8_rows, "standings": final_table,
            "feature": feature_of(t8_rows, "The top seed opens the cut."),
        })
        posts.append((t8_stamp, event, f"{spec['format']} Top 8 pairings are up", "pairings"))

        t4_pairs = [(t8_winners[0], t8_winners[3]), (t8_winners[1], t8_winners[2])]
        t4_rows = bracket_rows(t4_pairs)
        t4_stamp = posted_at(swiss + 1)
        rounds.append({
            "id": "T4", "label": "Top 4", "phase": "Top cut", "state": "live",
            "order": 101,
            "tables": len(t4_pairs), "posted": t4_stamp.strftime("%H:%M"), "_stamp": t4_stamp,
            "standingsAfter": swiss, "pairings": t4_rows, "standings": final_table,
            "feature": feature_of(t4_rows, "Two matches away from the title."),
        })
        posts.append((t4_stamp, event, f"{spec['format']} Top 4 pairings are up", "pairings"))
        posts.append((t8_stamp + timedelta(minutes=20), event,
                      f"The {spec['format']} Top 8 deck lists", "deck"))

        rounds.append({"id": "F", "label": "Final", "phase": "Top cut", "state": "upcoming",
                       "order": 102, "tables": None, "posted": None, "standingsAfter": None,
                       "pairings": [], "standings": [], "feature": None})

        formats_out.append({
            "format": spec["format"],
            "swissRounds": swiss,
            "duelists": spec["field"],
            "rounds": rounds,
        })

    # Derived from what was actually emitted. posted_at() closes over the last
    # format's round count, so calling it out here extrapolated past `now` and
    # stamped the file with a time in the future.
    newest = max(r["_stamp"] for f in formats_out for r in f["rounds"] if r.get("_stamp"))
    for f in formats_out:
        for r in f["rounds"]:
            r.pop("_stamp", None)
    # Written through the scraper's own archive, so the fixture the page is
    # tested against has the shape the page is actually served: a manifest, and
    # one directory per event holding the rounds. A fixture in a shape nothing
    # publishes tests a page nobody visits.
    #
    # One event, because that is what this simulates. A page with a second one
    # to switch to is tested by stubbing the manifest, rather than by inventing
    # a tournament here that never happened.
    sample = {
        "event": event,
        # Says so in the file rather than only in the markup, so the page can
        # show its badge from the data it is actually displaying.
        "sample": True,
        "coverageBy": "the Duel Desk team",
        # Ties were removed from tournament policy on 2025-09-02. Before that a
        # record reads W-L-T; after it, W-L. The shape follows the era.
        "drawsPossible": False,
        "updated": newest.isoformat().replace("+00:00", "Z"),
        "formats": formats_out,
    }
    # The event's own coverage posts, in the shape the scraper writes them.
    # The page builds each event's coverage list from this rather than from the
    # feed, so a fixture with an empty one is an event that renders its rounds
    # and claims to have had nothing written about it.
    #
    # The format is read back out of the headline, which is where the simulation
    # puts it, rather than threaded through the tuples: the same thing the
    # parser does to a real post.
    def spoken_format(headline):
        for name in (f["format"] for f in FORMATS):
            if name.lower() in headline.lower():
                return name
        return None

    archive.write_event(out / archive.ARCHIVE, SLUG, sample, [
        {"title": f"{event}: {headline}",
         "url": f"https://yugiohblog.konami.com/{SLUG}/{i}/",
         "modified": when.isoformat().replace("+00:00", "Z"),
         "kind": kind, "format": spoken_format(headline),
         "event": event, "slug": SLUG}
        for i, (when, _, headline, kind) in enumerate(
            sorted(posts, key=lambda p: p[0], reverse=True))])
    (out / archive.MANIFEST).write_text(
        archive.dumps(archive.build_manifest(out / archive.ARCHIVE), pretty=True),
        encoding="utf-8")
    print(f"rounds.json: {len(formats_out)} formats, "
          + ", ".join(f"{f['format']} {len(f['rounds'])} rounds" for f in formats_out))

    older = [
        (now - timedelta(days=14, minutes=30), 'YCS Montreal, Quebec', 'Your champion, undefeated in the top cut'),
        (now - timedelta(days=14, minutes=78), 'YCS Montreal, Quebec', 'Final match: a mirror decided on time'),
        (now - timedelta(days=14, minutes=215), 'YCS Montreal, Quebec', 'Top 8 pairings'),
        (now - timedelta(days=21, minutes=60), 'Ultimate Duelist Series — Season 6', 'Season 6 invite structure explained'),
        (now - timedelta(days=28, minutes=120), 'Forbidden & Limited list update', 'What changed and when it takes effect'),
    ]
    live_posts = sorted(((d, ev, t) for d, ev, t, _ in posts), key=lambda e: e[0], reverse=True)[:20]
    entries = sorted(live_posts + older, key=lambda e: e[0], reverse=True)

    items = []
    for d, ev, title in entries:
        items.append(f"""    <item>
      <title>{escape(f'[Sample] {ev}: {title}')}</title>
      <link>https://dueldesk.reizu.dev/</link>
      <guid isPermaLink="false">dueldesk-{d.strftime('%Y%m%d-%H%M%S')}</guid>
      <category>{escape(ev)}</category>
      <pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
      <description>{escape(f'SAMPLE DATA - invented for a design study, not real tournament coverage. {title}')}</description>
    </item>""")

    open(out / 'feed.xml', 'w', encoding='utf-8').write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Duel Desk — Yu-Gi-Oh! TCG event coverage (SAMPLE DATA)</title>
    <link>https://dueldesk.reizu.dev/</link>
    <atom:link href="https://dueldesk.reizu.dev/feed.xml" rel="self" type="application/rss+xml"/>
    <description>SAMPLE DATA — this is a design study. Every Duelist name, record and pairing in this feed is invented. Not affiliated with or endorsed by Konami. Live round-by-round pairings, standings and feature match coverage for Yu-Gi-Oh! TCG events.</description>
    <language>en</language>
    <lastBuildDate>{entries[0][0].strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
    <generator>Duel Desk</generator>
    <copyright>A design study. Not affiliated with or endorsed by Konami. All names and records shown are invented sample data.</copyright>
{chr(10).join(items)}
  </channel>
</rss>
""")
    print(f'feed.xml: {len(items)} items, newest {entries[0][0]:%Y-%m-%d %H:%M}')


if __name__ == '__main__':
    main()
