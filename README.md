# Duel Desk

A single-page design study for live **Yu-Gi-Oh! TCG** event coverage — round-by-round pairings,
standings, and feature matches, in the shape a competitive player actually reads them.

🔗 **Live:** https://dueldesk.reizu.dev

> ⚠️ Not affiliated with or endorsed by Konami. All Duelist names, records, and pairings shown
> are invented sample data.

## What it is

A dependency-free site in three files — `index.html`, `styles.css`, `app.js` — with no build step.
Open it in a browser and it works.

### Features

- **Honest records** — a record is stored as parts, not a formatted string, because how much is
  known varies. Wins are exact from match points; losses need the rounds a Duelist actually played.
  What is unknown renders as `?`, so `5–?` and `?–?` stay distinguishable, and both are muted.
  Ties were abolished on 2025-09-02, so events before that read `W–L–T` and later ones `W–L`.
- **Format selector** — an event runs a parallel tournament per format, each with its own field,
  round count and bracket. Switching one replaces the round set entirely and lands on whatever is
  live in that tournament. Hidden when an event has only one format, because then it is not a choice.
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

[`scraper/`](scraper/) parses coverage posts from Konami's Yu-Gi-Oh! TCG blog, and what it finds
is what the site serves.

The sitemap is the only supported way in: every `/feed/` path 404s and the WordPress REST posts
endpoint returns 403. `robots.txt` disallows only `/wp-admin/` and publishes `wp-sitemap.xml`
explicitly, so that is what `scraper/index.py` reads — 12,039 posts across seven sub-sitemaps.

`scraper/parse.py` reads a post's title and table. Table shapes are detected from their **headers**,
never by column position, because the blog uses at least three layouts:

| Layout | Columns |
| --- | --- |
| Standings | `Rank`, `Player Name`, `Points` — the points column is often absent |
| Pairings | `Table`, `P1 First Name`, `P1 Last Name`, `vs.`, `P2 …`, `P2 …` |
| Pairings with decks | `Table`, `Duelist 1 Name`, `Duelist 1 Deck Type`, `vs.`, … |

```bash
python3 -m unittest discover -s scraper -p 'test_*.py'
```

The tests run against real pages saved under `test/fixtures/blog/`, so they need no network and
run in CI. Every defect they guard against was found in actual markup, not imagined.

`scraper/build.py` assembles parsed posts into the site's schema — grouped by format, rounds
ordered, records derived. `scraper/run.py` is the entry point; the `Scrape coverage` workflow runs
it behind the sitemap gate and commits what it finds.

### The archive

The blog indexes about 12,000 posts, roughly 4,800 of which are event coverage across 97 event
slugs. A run builds the newest event every time — it may still be running — and, when asked, a few
older ones behind it:

```bash
python3 scraper/run.py --backfill 3        # the newest event, plus three more
```

Each event is written once and skipped on every run after that. The memory is the archive itself
rather than a state file, so deleting an event's directory is how a bad build is retried.

```
events.json                        every event, small enough to load first
events/<slug>/rounds.json          that event's rounds — the page's payload
events/<slug>/posts.json           its coverage posts, for rebuilding the feed
```

`posts.json` exists because the feed spans events. A run backfills a few at a time, so a feed built
only from what that run fetched would drop everything the run before it covered.

### Rebuilding what an older builder wrote

The archive is built once per event and then left alone — that is what `attempted` is for — so a
change to what the builder produces reaches only the events built after it. Each event file
records the `built` version that wrote it, and `--rebuild N` takes the N newest events whose
version is behind the current one. Separate from `--backfill`, which asks the opposite question:
one is what is missing, the other what is out of date.

Bump `BUILD_VERSION` in `scraper/build.py` when the builder starts producing something the older
files do not have, then rebuild in batches. Without the marker there is no way to ask which files
are behind, and rebuilding everything is hours of fetching to correct a handful.

### Event identity

Posts appear both under an event slug (`/2026/ycs/2026-08-quebec/…`) and without one, and only
about a fifth carry the slug. The rest are attached by date window, or by the name in their own
slug — which takes some care:

- **`lastmod` is a modification date.** Edit one 2014 post today and that event's window stretches
  across eleven years. Eleven of 97 slugs were affected, almost always by a single re-edited post,
  so the window is the largest cluster of an event's dates rather than their full range.
- **A shared date is not coverage.** Three Legendary Arc-V product announcements and an item about
  New York Comic Con were published during YCS Montréal and shown as its coverage. A post from a
  category the event does not use has to name the event, in vocabulary read from the event's own
  slugs rather than from a list.
- **Concurrent events are real** — the 2026 WCQ and the Genesys Championship both ran on
  2026-07-11 — so where a date matches two windows the format decides, and anything still
  ambiguous is reported rather than guessed.
- **Most tournaments have no event slug at all.** Not one of the 2023 North America WCQ's posts
  says which tournament in its path, and it is not alone: 2,560 rounds of pairings and standings,
  and something over a hundred tournaments, were invisible to every rule above. What the path
  leaves out the post slug says — `ycs-atlanta-round-1-pairings` — so the name is read off the
  front of the slug, up to the first word that describes the post rather than the event. Grouping
  on that name and cutting each group where the dates say one tournament ended and the next began
  finds them, and the two signals check each other: a name used every year is split by the dates,
  and two tournaments held the same weekend are kept apart by the name. Discovery runs last, on
  what is left, so an event the path or the dates already settled can gain posts this way but
  never lose or exchange one.
- **A discovered event can be dated too.** Until it could, an event nobody filed under a path only
  ever received posts that carried its name — so everything written about one in a sentence fell
  through: the post announcing its winner, its feature matches, its table of contents. The 2023
  North America Remote Duel YCS has a finals write-up naming its champion in so many words, under
  the slug `finals-feature-match-steven-santoli-vs-liam-mac-oscair`, which has no name in it to
  match and no window to fall inside either. Discovered events now attract undated siblings on the
  same corroborated terms path events always have, which is 1,879 posts. A category held by a
  single post out of thirty-four is not one of the event's, though — one WCQ post filed under
  `/2023/ycs/` put "ycs" on the 2023 South America WCQ and made every YCS post that weekend a
  candidate for it.
- **The oldest coverage cannot be identified at all.** Before about 2017 a post is slugged, and
  titled, only for what it contains — `standings-after-round-3`, and the page says the same. Some
  thirty tournaments are in the index this way with nothing anywhere to say which they are, so
  they stay unassigned rather than being guessed at.

### What is coming

The blog covers a tournament while it happens and says nothing before it, so the schedule comes
from somewhere else: Konami's own listing at
[yugioh-card.com/en/events/](https://www.yugioh-card.com/en/events/), which is server-rendered and
gives each event a name, a place, a date range and a page of its own to link to.

Read once a month rather than every ten minutes. That page changes when a season is announced —
a few times a year — and asking it at the coverage scraper's cadence would be thousands of
requests to watch a number that moves four times. It serves no robots.txt: `/robots.txt`
redirects to an image host that 404s, so there is no stated restriction to honour and none
claimed either. One request a month, with the same identifying user agent the blog scraper uses.

Whether an event has already happened is decided by the page, not by the file. A schedule written
in October and read in December would otherwise call a November tournament upcoming — the dates
are a fact about the event, "upcoming" is a fact about when you are looking. An event stays in the
list through its final day rather than disappearing on the morning of its last round.

### Pairings that are not in a table

Konami sometimes writes a round out as sentences rather than publishing a table:

```
Table 1: Jordan Farris (Floowandereeze) vs. Liam Mac Oscair (Mathmech @Ignister)
Table 1: Hideki Kawai (Japan – 9 points – Frog Monarch) vs. Kei Kuwano (…)
Table 1: Medina Hernandez, Omar (HEROES) vs. Franco Flores, Braulio (…) Braulio wins 2-0
```

Those posts carry no `<table>` at all, so the builder dropped them — the 2023 North America Remote
Duel YCS published its Top 8 and Top 4 that way and the archive had no cut for it. They are read as
prose where there is no table to read, never as a second opinion where there is one.

The bracket says where a name stops: whatever else is inside it, the deck is the last part, and the
result sentences that trail some rows are not part of anybody's name. Every table in a round parses
or none of it is used — a bracket short a match is not a smaller bracket, it is a wrong one. A piece
with no "vs" in it is not a failure but a bye, which is a real thing to publish and nothing to pair.

### Who won

The blog never records a winner as data. A final's pairing names two Duelists and does not say
which of them took it, and most events publish no final at all — coverage usually stops at the
semis. What there is instead is a post: *"Congratulations to Barrett Arthur Keys the winner of YCS
Bogota!"*

Reading a name out of prose like that is not attempted. Two rules were tried on the real archive —
take the first name in the post, take the longest — and each confidently produced a *different*
wrong champion for the 2013 North America WCQ, whose post reads *"Patrick J. Hoban … defeated
David J. Keener III"*. One picked a Duelist called Patrick Le, on the strength of the word
"Patrick". The other picked Keener, who lost.

So no name is read out of a post. The event already knows who could have won — the Duelists in the
deepest round of its cut — and the post is asked only which of *them* it means. That makes it
recognition over a handful of candidates rather than extraction from open prose, and the failure
mode becomes "no champion claimed" instead of "the wrong one". Three things must hold: the post
announces a winner by its own title, it is not about one of the side events every YCS runs a dozen
of (198 of the archive's 266 result posts are those), and exactly one of the cut's Duelists is
named in it. Where a post names two, as a final's write-up does, whoever is on the near side of
"defeated" won it.

A round shows every feature match it carried, newest first. 102 of the 357 rounds that have one
have more than one — YCS Montréal's Top 4 had three — so showing the best of them threw away two
thirds of the Duelists the blog wrote about that round. A post whose title names no two Duelists is
dropped rather than shown empty: the title is the only structured thing about a feature post, and a
panel of nobodies is worse than a shorter panel.

The final's own write-up counts too, where no post announces a winner outright. A feature match is
prose about two Duelists and names both of them throughout, so only one sentence of it is read: the
last one that crowns somebody. Everything else it says about champions is a preview or a
biography, and both read like results — *"is now just a short win away from becoming a YCS
Champion"*, *"is a 2-time YCS Champion, and although…"*. That second one is a true statement about
the runner-up, in the past tense, in the post about the match he went on to lose.

`champion` is null for most events, and that is a real answer rather than a gap to be filled.

The round panel shows who won on the last round the event published, and nowhere else — usually
the final, and where coverage stopped at the semis, the deepest round that exists, because that is
where the bracket ends for whoever is reading. Hidden until asked for: the rounds above it are
worth reading first, and a result printed beside them takes that away from anyone following the
bracket down. Not in the document until revealed, either — a spoiler that view-source or a screen
reader can find is not hidden.

### What the coverage does not always say

- **The blog reports points, the site models W–L–D records.** They are different quantities, and
  where the points column is missing entirely no record can be derived at all — the page shows `?`
  rather than a number nothing supports.
- **Ties were policy until 2025-09-02**, and 121 of the archive's 144 events predate that. Points
  are 3 for a win and 1 for a draw, so 3 points is one win *or* three draws and nothing in a single
  table separates them. What does separate them is the move from one round's standings to the
  next: +3 is a win, +1 a draw, +0 a loss. That reading needs the tables for consecutive rounds,
  anchored on the first one published — which is round two, never round one, because a table of
  everyone at three points or none says nothing. Two rounds always resolve to one record; three
  sometimes do not, and where the anchor is ambiguous or a round is missing, the points are
  published and the record is not.
- **Some events name no format.** The North America WCQ titles every post "North America WCQ:
  Round 10 Pairings". That is one tournament with no format name, not a missing one.
- **Two Duelists can share a name.** At YCS Columbus "Johnny KS Nguyen" and "Johnny PA Nguyen" are
  two people; the region tells them apart. Where nothing does, nothing is derived for that name.

## Tests

The JavaScript never reaches a bundler or a linter, so `check-inline-js.mjs` parse-checks it —
every inline block and every local file a `<script src>` points at. The suite
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

The coverage list is **the archive**. [`events.json`](events.json) names every event, and an
event's own `posts.json` is fetched when its section is opened — so a section costs nothing until
someone reads it, and every event has coverage rather than only the newest few.

[`feed.xml`](feed.xml) is still loaded, and still parsed by `groupFeed()`, but it is a
what's-new river of the newest 300 posts across the whole archive: at 52 events it reached only
five of them. It now says when the site last updated and which event is running, and its posts
give the newest few sections a head start while their own files are still on the way.

The data is still **sample data**; what changed is that the *mechanism* is real. The round panel
(pairings, standings, feature match) remains hardcoded, because the feed carries no round detail.

Round detail comes from the **archive**. The page reads
[`events.json`](events.json) first — every event, small enough to load before
anything is on screen — and then fetches the rounds for the one event being read.
One event is about 1.3MB, so a single file holding all of them would be a
several-megabyte download to look at one round of one tournament.

An event with more than one in the archive gets a picker above the heading.
Choosing one replaces everything below it: the round track, the panel, and which
headlines in the coverage list are in-page jumps rather than links to Konami —
because which rounds an event published is in that event's own file, and the page
does not offer a jump it cannot land. An event the archive holds but is not
showing carries a control in the coverage list to bring it on screen.

Both files are produced by
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

The event is laid out backwards from `--now`, and a round's posting time is a bare `HH:MM` — the
page shows one event day, with no date to tell rounds either side of a midnight apart. So when
`--now` falls too early in the day for the whole event to fit behind it, the event slides back to
the end of the previous day rather than running across the midnight: `updated` and the round times
it summarises then still describe one day. Slid backwards, never forwards — coverage of a
tournament that has not happened yet would be worse than one that finished late.

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
| `index.html` | The site's markup. |
| `styles.css` | Its styles. |
| `app.js` | Its behaviour. Loaded with `defer`; the only inline script is the theme resolver, which has to run before first paint. |
| `feed.xml` | RSS 2.0 feed of the newest posts across the whole archive. What is new, not the catalogue. |
| `winners/index.html` | Every event the coverage names a winner for, built from the manifest alone. Served at `/winners`. |
| `common.js` | Escaping, URL safety and the theme — the same job on both pages. |
| `winners.js` | The winners list's own behaviour. |
| `events.json` | Every event in the archive: name, date, formats, how many posts it has, who won it, and where to find it. |
| `upcoming.json` | The schedule ahead, read off Konami's event listing once a month. |
| `events/` | One directory per event; fetched on demand, not all at once. |
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

The same script runs twice. Before `configure-pages`, against a local server holding the staged
artifact — a rehearsal that catches a file the staging forgot, or a fault in the check itself,
before either is relied on. A broken check used to surface as a red deploy of a site that was
perfectly fine.

Then after `deploy-pages` publishes, [`scripts/smoke-test.sh`](scripts/smoke-test.sh) asks production
directly: the served `index.html`, `styles.css` and `app.js` must each hash-match the uploaded
artifact, `events.json` and the
event it names newest must match it too, that event must carry
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
