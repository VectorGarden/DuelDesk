"""What the archive looks like right now, and whether it looks damaged.

Printed as one JSON object so drive-scrape.sh can diff two of them: what an
hour of batches did to the archive is the difference between the one it took
before and the one it takes after.

Run from the root of the repository.
"""
import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scraper"))
import archive, build

root = pathlib.Path('events')
events, bad_records, empty_rounds = {}, [], []

for f in sorted(root.glob('*/rounds.json')):
    slug = f.parent.name
    ev = json.loads(f.read_text())
    events[slug] = ev.get('built', 0)
    for fmt in ev.get('formats') or []:
        for r in fmt.get('rounds') or []:
            # Every round must carry something. A round with no pairings, no
            # standings and no feature match is a round the builder invented.
            if not (r.get('pairings') or r.get('standings') or r.get('features')):
                empty_rounds.append(f"{slug} :: {fmt.get('format')} :: {r.get('label')}")
            # Only files the current builder wrote: an older one's arithmetic
            # is not what this run is testing.
            if ev.get('built', 0) != build.BUILD_VERSION:
                continue
            for row in r.get('standings') or []:
                w, d, p = (row.get('wins'), row.get('draws'), row.get('points'))
                if None in (w, d, p):
                    continue
                if 3 * w + d != p:
                    bad_records.append(f"{slug} :: {r.get('label')} :: "
                                       f"{row.get('name')} {w}-{d} for {p}")

print(json.dumps({
    "version": build.BUILD_VERSION,
    "events": len(events),
    "slugs": sorted(events),
    "behind": len(archive.behind(root, build.BUILD_VERSION)),
    "champions": sum(len(e.get('champions', []))
                     for e in json.load(open('events.json'))['events']),
    "rejected": sorted(p.parent.name for p in root.glob('*/rejected.json')),
    "badRecords": bad_records[:20],
    "emptyRounds": empty_rounds[:20],
}))
