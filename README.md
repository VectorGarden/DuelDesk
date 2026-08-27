# Duel Desk

A single-page design study for live **Yu-Gi-Oh! TCG** event coverage — round-by-round pairings,
standings, and feature matches, in the shape a competitive player actually reads them.

🔗 **Live:** https://dueldesk.reizu.dev

> ⚠️ Not affiliated with or endorsed by Konami. All Duelist names, records, and pairings shown
> are invented sample data.

## What it is

The whole site is one dependency-free `index.html` — markup, styles, and behaviour in a single
file, no build step. Open it in a browser and it works.

### Features

- **Round track** — a horizontally scrollable ARIA tablist with roving tabindex; arrow keys,
  `Home`, and `End` move between rounds.
- **Round panel** — switch between Pairings, Standings, and Feature match for the selected round.
- **Coverage feed** — events grouped into collapsible sections, filterable by coverage type
  (pairings, standings, feature, results, deck profiles) and searchable by Duelist or event.
- **Keyboard shortcuts** — `/` jumps to search, `Escape` clears it.
- **Theming** — light, dark, and system, driven by CSS custom properties.
- **Accessibility** — targets WCAG 2.2 AA: visible focus rings, live-region announcements,
  colour never the sole signal, and `prefers-reduced-motion` / `prefers-contrast` respected.

### Design notes

The palette is lifted from the game's own card-frame colour system, which competitive players
already read fluently: Spell teal, Effect orange, Trap magenta, Link blue, Fusion purple, plus the
antique gold of the card border used only as a hairline. The clipped corner (`--notch`) is a nod to
the card frame.

## Running locally

Just open the file:

```bash
open index.html
```

Or serve it, which is closer to production:

```bash
python3 -m http.server 8000
```

Then visit http://localhost:8000.

## Data

The page currently renders **sample data** defined inline in `index.html`.

`classify()` and `groupFeed()` sketch how a real feed would be wired up: the source blog runs
WordPress and exposes RSS at `/feed/`, but one tournament arrives as ~47 separate posts with titles
like *"Pairings for Round 11"*. Those two functions turn that flat stream back into events
containing rounds.

Browsers cannot fetch that feed cross-origin, so a real deployment needs a small server or worker
to fetch, parse, and serve the JSON to the page.

## Deployment

Served by GitHub Pages from the default branch. `CNAME` points the site at `dueldesk.reizu.dev`;
the matching DNS record is configured separately.

## Licence

MIT — see [LICENSE](LICENSE).
