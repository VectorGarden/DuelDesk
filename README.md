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
  `Home`, and `End` move between rounds. Chips are updated in place, so the rail keeps its
  scroll position and never loses focus.
- **Round panel** — switch between Pairings, Standings, and Feature match for the selected
  round. The view control is disabled for rounds that have not started.
- **Coverage feed** — events grouped into collapsible sections, filterable by coverage type
  (pairings, standings, feature, results, deck profiles) and searchable by Duelist or event.
- **Search** — filters the coverage feed *and* the pairings and standings tables.
- **Keyboard shortcuts** — `/` jumps to search, `Escape` clears it. Modifier combos
  (`Cmd+/`, `Ctrl+/`) are left to the browser.
- **Theming** — light, dark, and system, driven by CSS custom properties, persisted to
  `localStorage`, and resolved before first paint so the page never flashes the wrong theme.
- **Accessibility** — targets WCAG 2.2 AA: a properly wired `tabpanel`, visible focus rings that
  are never clipped, keyboard-scrollable table regions, live-region announcements, colour never
  the sole signal, and `prefers-reduced-motion` / `prefers-contrast` respected.

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

The page currently renders **sample data** defined inline in `index.html`, and publishes the same
data as a valid RSS 2.0 feed at [`feed.xml`](feed.xml).

`groupFeed()` shows how a real feed would be wired up. One tournament arrives as ~47 separate
posts with titles like *"Pairings for Round 11"*; it turns that flat stream back into events
containing rounds, using three helpers:

| Helper | Job |
| --- | --- |
| `roundFrom()` | Pulls the round slot out of a title regardless of word order — `Round 11 Pairings`, `Pairings for Round 11`, and `R11 pairings` all resolve to round 11. |
| `kindFrom()` | Classifies coverage type. Structural markers (pairings, standings) are checked before the looser deck match, so `Top 8 pairings` and `Top 8 decklists` land correctly. A title with no keyword falls back to `news` rather than guessing. |
| `eventNameFrom()` | Derives the event name, ignoring leading coverage labels — without this, `Feature Match: A vs B` would invent an event called *Feature Match* and scatter the real tournament across it. |

`feed.xml` round-trips through this parser: 13 flat posts reassemble into the same 4 events with
the correct kinds and round slots.

> **Escaping.** Everything rendered through `innerHTML` goes through `esc()` first. The sample data
> is trusted, but `groupFeed()` is built to replace it with third-party RSS where titles and
> Duelist names are attacker-controlled. Escape at the boundary, always.

Browsers cannot fetch a cross-origin feed, so a real deployment needs a small server or worker
to fetch, parse, and serve the JSON to the page.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The entire site — markup, styles, and behaviour. |
| `feed.xml` | RSS 2.0 coverage feed. |
| `og.png` | 1200×630 social preview image. |
| `CNAME` | Custom domain for GitHub Pages. |

## Deployment

Served by GitHub Pages from the default branch. `CNAME` points the site at `dueldesk.reizu.dev`;
the matching DNS record is configured separately.

Round data is sourced from Konami's official
[Yu-Gi-Oh! TCG blog](https://yugiohblog.konami.com/), which is credited in the footer. The
site's own feed is `feed.xml` — Konami's feed is not presented as this site's.

## Licence

MIT — see [LICENSE](LICENSE).
