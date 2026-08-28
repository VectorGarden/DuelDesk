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
- **Live updates** — the page polls its own feed and round data, repainting only when
  something actually changed. Polling pauses while the tab is hidden, backs off exponentially
  on failure, and slows to a five-minute interval when no event is in progress.
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

## Scraping the official blog

[`scraper/`](scraper/) parses coverage posts from Konami's Yu-Gi-Oh! TCG blog. **Nothing in the
site consumes it yet** — it produces structured data, and mapping that onto the page's model is a
separate decision (see below).

The sitemap is the only supported way in: every `/feed/` path 404s and the WordPress REST posts
endpoint returns 403. `robots.txt` disallows only `/wp-admin/` and publishes `wp-sitemap.xml`
explicitly, so that is what `scraper/index.py` reads — 12,039 posts across seven sub-sitemaps.

`scraper/parse.py` reads a post's title and table. Table shapes are detected from their **headers**,
never by column position, because the blog uses at least three layouts:

| Layout | Columns |
| --- | --- |
| Standings | `Rank`, `Player Name`, `Points` |
| Pairings | `Table`, `P1 First Name`, `P1 Last Name`, `vs.`, `P2 …`, `P2 …` |
| Pairings with decks | `Table`, `Duelist 1 Name`, `Duelist 1 Deck Type`, `vs.`, … |

```bash
python3 -m unittest discover -s scraper -p 'test_*.py'
```

17 tests run against real pages saved under `test/fixtures/blog/`, so they need no network and run
in CI.

### What does not map cleanly yet

- **The blog reports points, the site models W–L–0 records.** They are different quantities.
- **Events run two parallel tournaments** (Advanced and Genesys); `rounds.json` has no format axis.
- **Event identity is genuinely ambiguous.** Posts appear both under an event slug
  (`/2026/ycs/2026-08-quebec/…`) and without one, and concurrent events are real — the 2026 WCQ and
  the Genesys Championship both ran on 2026-07-11. Posts are attached by date window and format,
  and anything still ambiguous is reported as such rather than guessed.

## Tests

The JavaScript lives inside `index.html`, so it never reaches a bundler or a linter. The suite
loads the real page into jsdom with a controllable network and exercises the actual boot sequence,
render functions and state machines — not a re-implementation that could drift from them.

```bash
nvm use     # reads .nvmrc
npm ci
npm test
```

Requires Node 20+ (`node:test` and jsdom). [`.nvmrc`](.nvmrc) pins the version and CI reads the
same file, so a local shell and the runner cannot drift apart. The **site itself stays dependency-free**; jsdom and
`vnu-jar` are dev dependencies used only for testing and validation.

Covered: escaping and URL-scheme guards, feed parsing and classification, every data state
(loading, ready, empty, stale, error) for both loaders, per-round rendering and record coherence,
accessibility invariants (tabpanel wiring, roving tabindex, no dangling ARIA references,
non-interactive post rows), theme persistence, search and filtering, and polling — change
detection, focus and scroll preservation, visibility pausing, backoff, and announcements.

The suite is mutation-tested: ten deliberate regressions — unescaped output, an unrestricted
`safeUrl`, a stale reload blanking the page, `renderRound` ignoring the active round, a detached
tabpanel label, post rows becoming links, an unconditional live badge, a fetch that stops
revalidating, a broken roving tabindex, and theme persistence removed — are each caught.

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

The coverage list is **loaded at runtime from this site's own [`feed.xml`](feed.xml)** through
`groupFeed()`. The feed is the single source — the posts are no longer duplicated inline.

The data is still **sample data**; what changed is that the *mechanism* is real. The round panel
(pairings, standings, feature match) remains hardcoded, because the feed carries no round detail.

Round detail comes from [`rounds.json`](rounds.json). Both files are produced by
[`scripts/generate-sample-data.py`](scripts/generate-sample-data.py) from **one simulated Swiss
tournament**, so the coverage posts and the round panel describe the same event. The simulation
pairs players on equal records, plays the results out, and sorts standings by wins with opponent
match-win percentage as the tiebreak — so the records add up. An 11–0 Duelist in round 12 really
did win eleven matches in there.

```bash
python3 scripts/generate-sample-data.py
```

The simulation runs past Swiss into the **top cut**: the top eight of the final standings are
seeded 1v8, 2v7, 3v6, 4v5, the Top 8 is played, and the Top 4 is paired from its winners. The
Final stays empty because its competitors genuinely are not known until the Top 4 finishes — so
the "not started" state is still shown, honestly, rather than because the data ran out.

Cut matches count: winning the Top 8 takes a Duelist from 9–3 to 10–3, and the Top 4 pairing
shows that. The standings table is snapshotted before the cut begins and keeps the final *Swiss*
placings, because Swiss standings really are final after the last Swiss round — so the two do not
contradict each other.

It is deterministic: a seeded PRNG plus a `--now` anchor means the same inputs reproduce the same
files byte for byte. CI checks the result stays coherent, including that each cut round's field
comes from the previous round's competitors and halves each time.

The published feed marks itself as sample data at every level a reader actually sees — channel
title, channel description, each item title (`[Sample] …`) and each item description — because
aggregators strip `<copyright>`. The page strips the `[Sample]` prefix on parse, since the badge
beside the headline already says so. CI enforces the marking.

> **The sample data is regenerated at deploy time**, so the published site is always fresh enough
> to show its live state. The PRNG is seeded, so this reproduces the same tournament — same
> bracket, same records — and only the clock moves. The regenerated files are re-validated before
> upload, since they are not the ones the test job checked.
>
> The workflow also runs on a **four-hourly schedule**, so the site republishes with fresh
> timestamps even when nobody pushes — the live window is six hours, leaving two hours of slack
> for a scheduler that runs late under load. `workflow_dispatch` is a manual refresh.
>
> GitHub disables scheduled workflows after 60 days without repository activity; a push or a
> manual run re-enables them.
>
> The committed copies keep whatever timestamps they were generated with, so a local checkout more
> than six hours old will correctly stop showing the Live badge. Run the generator to refresh it.

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
| `favicon.ico` | Multi-resolution legacy favicon (16/32/48). |
| `site.webmanifest` | PWA manifest — name, colours, install icons. |
| `icons/` | Shipped icons only — everything here is published and must be referenced. |
| `design/` | Icon design sources (`icon.svg`, `icon-small.svg`, `icon-maskable.svg`). Not deployed. |
| `CNAME` | Custom domain for GitHub Pages. |

## The icon

A **two-tier set**, because the full mark does not survive favicon sizes:

- **16–48px** — a single lit chip (`icon-small.svg`). Below about 48px the three-chip
  track turns to mush, so the small tier shows one chip lifted straight out of it.
- **64px and up** — the full round track (`icon.svg`): a gold rule over three chips with the
  live round lit in accent, abstracting the site's signature UI element.
- **Android** — `icon-maskable.svg` scales the artwork into the centre 80% so an aggressive
  circle crop cannot clip a chip.

Both tiers are the same object at different zoom levels rather than two different logos.
The notch is kept *inside* the artwork: iOS masks app icons into a squircle, so a notch on
the icon's own silhouette would be cropped away exactly where the brand cue was meant to be.

There is deliberately **no SVG favicon** — browsers prefer an SVG at every size, which would
collapse the two tiers back into one.

`rel="icon"` offers nothing above 48px. A browser that picks the largest candidate would render
the three-chip track at tab size, which is the mush the two tiers exist to avoid; install-size
icons live in `site.webmanifest` instead.

`favicon.ico` uses **BMP-encoded** entries, built by
[`scripts/build-favicon.py`](scripts/build-favicon.py). PNG-in-ICO is smaller and fine on
Windows browsers, but Safari does not reliably decode it and falls back to a generic globe.
`icons/mask-icon.svg` is the monochrome Safari pinned-tab icon.

`icons/` is the *published* directory: CI fails if anything in it is referenced by nothing, is
not square, has pixels that disagree with its filename, or duplicates another file byte for byte.
Design sources live in `design/` and are never deployed. Install sizes are declared in
`site.webmanifest`, which is what makes them referenced rather than orphaned.

To regenerate every icon after editing a source SVG:

```bash
./scripts/build-icons.sh
```

It renders each source at every shipped size with headless Chrome — the same engine that displays
them, so what ships is what a browser draws — then rebuilds `favicon.ico` and runs the icon
checks. Set `CHROME=/path/to/chrome` if it cannot find one.

Against an unmodified tree it reproduces the committed files **byte for byte**, so a dirty
`git status` after running it means a source really did change. That reproduction depends on the
Chrome version, which is why CI validates the committed PNGs rather than rebuilding them.

## Deployment

Deployed to GitHub Pages by the `Validate` workflow, from an artifact rather than the branch.

The deploy job `needs: validate`, so a build that fails its checks is never published.
[`scripts/stage-site.sh`](scripts/stage-site.sh) copies an explicit **include list** into `_site/`
— the branch build published the whole repository, which meant `package.json`, the test harness
and the data generator were all reachable over HTTP. `check-references.py` then runs against the
staged tree, so a file the page needs but the script forgot fails the build instead of 404ing in
production.

After `deploy-pages` publishes, [`scripts/smoke-test.sh`](scripts/smoke-test.sh) asks production
directly: the served `index.html` must hash-match the uploaded artifact, `rounds.json` must carry
a timestamp only this deploy could have written, every referenced file must return 200, and no
source file may be reachable. It retries while Pages propagates, and reports every fault it finds
rather than stopping at the first.

That check exists because deploys were once silently broken for two merges — CI stayed green
throughout, because nothing ever asked production a question.

`CNAME` ships in the artifact; the matching DNS record is configured separately.

Round data is sourced from Konami's official
[Yu-Gi-Oh! TCG blog](https://yugiohblog.konami.com/), which is credited in the footer. The
site's own feed is `feed.xml` — Konami's feed is not presented as this site's.

## Licence

MIT — see [LICENSE](LICENSE).
