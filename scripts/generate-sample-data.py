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
import argparse, json, random
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

SEED = 20260828
FIELD = 64                 # simulated field; the page shows the top 8 of it
SWISS = 12                 # R1..R11 resolved, R12 paired but unplayed
ANNOUNCED = 1248           # headline field size for the event

SURNAMES = """Okonkwo Alvarez Lindqvist Nakamura Wexler Boateng Duval Petrov Marchetti Zhao
Ferreira Haddad Rasmussen Osei Bergstrom Castellanos Ibarra Novak Takahashi Mwangi Sorensen
Delacroix Kowalski Almeida Nguyen Adeyemi Rossi Fischer Dlamini Varga Sasaki Ortega Bakker
Larsen Chibuzo Moreau Ivanov Yildiz Santoro Keller Abadi Pereira Lund Hassan Moretti Blomqvist
Aguilar Vermeulen Kimura Osborne Bianchi Traore Nowak Reinhardt Espinoza Falk Mbeki Guerrero
Halvorsen Ricci Amara Sundqvist Costa Weber""".split()
INITIALS = "RMJPDSKATLCNEVHIGBFOWZY"
DECKS = ['Maliss','Ryzeal','Fiendsmith','Mitsurugi','Voiceless Voice','Snake-Eye','Yubel','Tenpai Dragon']


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
        "a": a["name"], "aRec": f"{a['w']}–{a['l']}–0",
        "b": b["name"], "bRec": f"{b['w']}–{b['l']}–0",
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


def standings_table(players):
    by_name = {p['name']: p for p in players}
    ranked = sorted(players, key=lambda p: (-p['w'], p['l'], -omw(p, by_name), p['name']))
    return [{
        'pos': i + 1,
        'name': p['name'],
        'record': f"{p['w']}–{p['l']}–0",
        'deck': p['deck'],
        'pct': f"{omw(p, by_name):.1f}",
    } for i, p in enumerate(ranked[:8])]


def pairings_table(pairs):
    return [{
        'table': i + 1,
        'a': a['name'], 'aRec': f"{a['w']}–{a['l']}–0",
        'b': b['name'], 'bRec': f"{b['w']}–{b['l']}–0",
    } for i, (a, b) in enumerate(pairs[:8])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--now', help='ISO timestamp anchoring the event (default: current UTC)')
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now).astimezone(timezone.utc) if args.now \
        else datetime.now(timezone.utc)

    rng = random.Random(SEED)
    players = build_field(rng)
    event = f"Remote Duel YCS {now.strftime('%B %Y')}"

    # 14 rounds get posted: R1..R12, then Top 8 and Top 4. Indexed in posting
    # order so the most recent (Top 4 pairings) is the freshest thing in the feed.
    POSTED_ROUNDS = SWISS + 2
    def posted_at(i):
        return now - timedelta(minutes=(POSTED_ROUNDS - 1 - i) * 38 + 12)

    rounds, posts = [], []
    by_name = {p["name"]: p for p in players}

    def feature_of(rows, phase_note):
        top = rows[0]
        return {
            "a": {"name": top["a"], "deck": by_name[top["a"]]["deck"], "record": top["aRec"]},
            "b": {"name": top["b"], "deck": by_name[top["b"]]["deck"], "record": top["bRec"]},
            "note": phase_note,
        }

    # --- Swiss, played out in full ---
    for n in range(1, SWISS + 1):
        pairs = pair_round(players, rng)
        entering = pairings_table(pairs)
        stamp = posted_at(n - 1)
        play(pairs, rng)

        rounds.append({
            "id": str(n), "label": f"R{n}", "phase": "Swiss", "state": "done",
            "tables": ANNOUNCED // 2,
            "posted": stamp.strftime("%H:%M"),
            "standingsAfter": n,
            "pairings": entering,
            "standings": standings_table(players),
            "feature": feature_of(entering, f"Table one for round {n}. Written coverage of each turn follows as the match plays out."),
        })

        posts.append((stamp, event, f"Round {n} pairings are up", "pairings"))
        posts.append((stamp + timedelta(minutes=22), event, f"Standings after round {n}", "standings"))
        top = entering[0]
        if n in (6, 9, SWISS):
            posts.append((stamp + timedelta(minutes=9), event,
                          f"Feature match: {by_name[top['a']]['deck']} against {by_name[top['b']]['deck']}", "feature"))
        if n == SWISS - 2:
            posts.append((stamp + timedelta(minutes=30), event, "The decks still in contention", "deck"))

    # --- Top cut. Swiss is over, so standings are final from here on. ---
    # Snapshotted before any cut match is played: duel() updates records, and
    # the standings table must keep showing the final *Swiss* placings.
    final_table = standings_table(players)
    seeds = [by_name[row["name"]] for row in final_table]      # seed 1..8

    # Standard single-elimination seeding: 1v8, 2v7, 3v6, 4v5.
    t8_pairs = [(seeds[0], seeds[7]), (seeds[1], seeds[6]),
                (seeds[2], seeds[5]), (seeds[3], seeds[4])]
    t8_rows = bracket_rows(t8_pairs)
    t8_stamp = posted_at(SWISS)
    t8_winners = [duel(a, b, rng)[0] for a, b in t8_pairs]

    rounds.append({
        "id": "T8", "label": "Top 8", "phase": "Top cut", "state": "done",
        "tables": len(t8_pairs), "posted": t8_stamp.strftime("%H:%M"),
        "standingsAfter": SWISS,
        "pairings": t8_rows, "standings": final_table,
        "feature": feature_of(t8_rows, "The top seed opens the cut. Single elimination from here."),
    })
    posts.append((t8_stamp, event, "Top 8 pairings are up", "pairings"))
    posts.append((t8_stamp + timedelta(minutes=14), event, "The Top 8 decks", "deck"))

    # Winners meet: (1v8) plays (4v5), (2v7) plays (3v6).
    t4_pairs = [(t8_winners[0], t8_winners[3]), (t8_winners[1], t8_winners[2])]
    t4_rows = bracket_rows(t4_pairs)
    t4_stamp = posted_at(SWISS + 1)

    rounds.append({
        "id": "T4", "label": "Top 4", "phase": "Top cut", "state": "live",
        "tables": len(t4_pairs), "posted": t4_stamp.strftime("%H:%M"),
        "standingsAfter": SWISS,
        "pairings": t4_rows, "standings": final_table,
        "feature": feature_of(t4_rows, "Two matches away from the title. Both are being covered turn by turn."),
    })
    posts.append((t4_stamp, event, "Top 4 pairings are up", "pairings"))

    # The Final genuinely is not known yet -- the Top 4 has not been played.
    rounds.append({"id": "F", "label": "Final", "phase": "Top cut", "state": "upcoming",
                   "tables": None, "posted": None, "standingsAfter": None,
                   "pairings": [], "standings": [], "feature": None})

    json.dump({
        'event': event,
        'format': 'Advanced',
        'duelists': ANNOUNCED,
        'swissRounds': SWISS,
        'coverageBy': 'the Duel Desk team',
        # The newest posted round, which is the last cut round that has pairings.
        # This was posted_at(SWISS) back when the Swiss rounds were the last
        # thing posted; adding the cut left it pointing an round behind.
        'updated': posted_at(POSTED_ROUNDS - 1).isoformat().replace('+00:00', 'Z'),
        'rounds': rounds,
    }, open('rounds.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f'rounds.json: {len(rounds)} rounds ({SWISS} swiss + 3 cut)')

    # --- feed.xml, from the same simulation ---
    older = [
        (now - timedelta(days=14, minutes=30), 'YCS Montreal, Quebec', 'Your champion, undefeated in the top cut'),
        (now - timedelta(days=14, minutes=78), 'YCS Montreal, Quebec', 'Final match: a mirror decided on time'),
        (now - timedelta(days=14, minutes=215), 'YCS Montreal, Quebec', 'Top 8 pairings'),
        (now - timedelta(days=21, minutes=60), 'Ultimate Duelist Series — Season 6', 'Season 6 invite structure explained'),
        (now - timedelta(days=28, minutes=120), 'Forbidden & Limited list update', 'What changed and when it takes effect'),
    ]
    # Cap the live event's posts, then always append the older events. A flat
    # cap across everything let the live event crowd them out entirely, leaving
    # the coverage list showing one event instead of four.
    live_posts = sorted(((d, ev, t) for d, ev, t, _ in posts), key=lambda e: e[0], reverse=True)[:14]
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

    open('feed.xml', 'w', encoding='utf-8').write(f"""<?xml version="1.0" encoding="UTF-8"?>
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
