/**
 * The archive: more than one event, and choosing between them.
 *
 * One event's rounds are about 1.3MB, so they are not all loaded at once. The
 * page reads events.json — every event, small enough to load first — and fetches
 * the rounds only for the event being read.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor, tick, fixture, roundsFixture } from './harness.mjs';

const SAMPLE = JSON.parse(fixture('events.json')).events[0];

/** A manifest of two events, newest first, both pointing at real round data. */
const OLDER = {
  ...SAMPLE,
  slug: 'older-ycs-columbus',
  event: 'YCS Columbus',
  updated: '2026-05-23',
  path: 'events/older-ycs-columbus/rounds.json',
};

/* The second event's rounds are the simulation with its rounds trimmed, so the
   two are distinguishable without inventing a tournament that never happened. */
function olderRounds() {
  const d = roundsFixture();
  d.event = 'YCS Columbus';
  d.formats = [{ ...d.formats[0], rounds: d.formats[0].rounds.slice(0, 4) }];
  return d;
}

const twoEvents = (extra = {}) => ({
  routes: {
    'events.json': { status: 200, body: JSON.stringify({ events: [SAMPLE, OLDER] }) },
    'older-ycs-columbus/rounds.json': () => ({ status: 200, body: JSON.stringify(olderRounds()) }),
    /* The event on screen contributes no coverage of its own. The simulation
       has fifty-six posts, and every one of them is noise in a test asserting
       something about the other event or about the feed. */
    'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
    ...extra,
  },
});

/** Open the event search and read what it offers.
 *
 * `year` is the group the option sits in: the list is grouped by year, so the
 * option itself carries only the month and the year is not repeated on it.
 */
function options(page, query = '') {
  page.run(`openPicker(true)`);
  if (query) page.run(`pickerQuery = ${JSON.stringify(query)}; renderEventPicker();`);
  return page.$$('#event-list [role="option"]').map((li) => ({
    slug: li.dataset.slug,
    name: li.querySelector('b')?.textContent.trim() ?? li.textContent.trim(),
    aside: li.querySelector('span')?.textContent.trim() ?? '',
    year: li.closest('[role="group"]')?.getAttribute('aria-label') ?? '',
  }));
}

test('one event is not presented as a choice', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  assert.equal(page.$('#event-pick').hidden, true,
    'the archive holds one event; there is nothing to pick');
});

test('the picker box cannot collapse to nothing', async (t) => {
  // Its width is min(22rem,60vw) and box-sizing is border-box, so where 60vw
  // resolves to nothing the box shrinks to its own padding: a 43.6px stub
  // showing the chevron with no room to type, which is what the live site
  // rendered. A text input's min-width is 0, so nothing else stops it.
  const page = await loadPage({});
  t.after(() => page.close());
  const floor = page.get(
    `getComputedStyle(document.getElementById('event-search')).minWidth`);
  // Read as a number, so "0", "0px" and "" all fail the same way.
  assert.ok(parseFloat(floor) > 0,
    `the box needs a width floor above zero, got ${JSON.stringify(floor)}`);
});

test('the picker lists every event, newest first', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  assert.equal(page.$('#event-pick').hidden, false);
  assert.deepEqual(options(page).map((o) => o.slug), [SAMPLE.slug, OLDER.slug]);
  assert.deepEqual(options(page).map((o) => o.name), [SAMPLE.event, 'YCS Columbus']);
});

test('two events of the same name are told apart by date', async (t) => {
  // An event runs most years, so its name alone does not identify it: of the 68
  // events in the blog's archive with rounds to show, 25 share a name with
  // another. Five separate North American WCQs ran between 2013 and 2017.
  const twin = { ...OLDER, slug: 'older-still', updated: '2025-05-24' };
  const page = await loadPage({
    routes: {
      'events.json': {
        status: 200, body: JSON.stringify({ events: [SAMPLE, OLDER, twin] }),
      },
      'rounds.json': () => ({ status: 200, body: JSON.stringify(olderRounds()) }),
    },
  });
  t.after(() => page.close());
  // Told apart by the group they sit in, which is where the year now lives.
  const labels = options(page).map((o) => `${o.year} ${o.name} ${o.aside}`);
  assert.equal(new Set(labels).size, labels.length, `not distinguishable: ${labels}`);
  assert.deepEqual(labels.slice(1), ['2026 YCS Columbus May', '2025 YCS Columbus May']);
});

test('an event with no usable date is listed by name rather than by nothing', async (t) => {
  // Missing and unreadable are different inputs and the same answer: the date
  // is absent, which is a fact about the event rather than a reason to print
  // "Invalid Date" beside its name.
  for (const updated of [null, '', 'sometime in 2019']) {
    const page = await loadPage({
      routes: {
        'events.json': {
          status: 200,
          body: JSON.stringify({ events: [SAMPLE, { ...OLDER, updated }] }),
        },
        'older-ycs-columbus/rounds.json': () => ({
          status: 200, body: JSON.stringify(olderRounds()),
        }),
      },
    });
    t.after(() => page.close());
    const shown = options(page)[1];
    assert.equal(shown.name, 'YCS Columbus', `updated: ${JSON.stringify(updated)}`);
    assert.equal(shown.aside, '', `updated: ${JSON.stringify(updated)}`);
    assert.equal(shown.year, 'Undated', `updated: ${JSON.stringify(updated)}`);
    page.close();
  }
});

/* Built from the parts, like the page: new Date("2026-08-16") is midnight UTC
   and renders as the 15th anywhere west of Greenwich, so a test that used it
   would agree with the page only on machines set to UTC or east of it. */
const longDate = (iso) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d)
    .toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
};

test('the day shown is the day the coverage names, west of Greenwich too', async (t) => {
  // new Date("2026-08-16") is midnight UTC. Rendered in a zone behind it that
  // is the 15th, so every archived event would be listed a day early for most
  // of the Americas -- and the archive's dates are exactly the calendar days
  // the tournaments were played on.
  const tz = process.env.TZ;
  process.env.TZ = 'America/Los_Angeles';
  t.after(() => { if (tz === undefined) delete process.env.TZ; else process.env.TZ = tz; });

  const page = await loadPage({
    routes: {
      'events.json': {
        status: 200,
        body: JSON.stringify({ events: [{ ...OLDER, updated: '2026-05-23' }, SAMPLE] }),
      },
      'older-ycs-columbus/rounds.json': () => ({
        status: 200, body: JSON.stringify(olderRounds()),
      }),
    },
  });
  t.after(() => page.close());
  assert.deepEqual(options(page)[0],
    {slug: OLDER.slug, name: 'YCS Columbus', aside: 'May', year: '2026'});
  assert.ok(page.text('#hero-meta').includes('23 May 2026'), page.text('#hero-meta'));
});

test('the date under the heading is the one the picker chose', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  assert.ok(page.text('#hero-meta').includes(longDate(SAMPLE.updated)),
    page.text('#hero-meta'));
  page.run(`selectEvent('${OLDER.slug}')`);
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.ok(page.text('#hero-meta').includes(longDate(OLDER.updated)),
    page.text('#hero-meta'));
});

test('a lone event needs no date beside its name', async (t) => {
  // Nothing to tell it apart from, so the line is one fact shorter.
  const page = await loadPage({});
  t.after(() => page.close());
  assert.ok(!/\d{4}/.test(page.text('#hero-meta')), page.text('#hero-meta'));
});

test('the newest event is the one on screen', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  assert.equal(page.get('activeEvent'), SAMPLE.slug);
  assert.equal(page.text('#live-h'), SAMPLE.event);
});

test('only the event being read is fetched', async (t) => {
  // The whole point of the manifest: an archive of dozens of events must not be
  // a dozens-of-megabytes download to look at one round of one of them.
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  const fetched = page.calls.map((c) => String(c.url));
  assert.ok(fetched.some((u) => u.includes(SAMPLE.slug)), 'the newest event was loaded');
  assert.ok(!fetched.some((u) => u.includes(OLDER.slug)),
    'the event nobody is reading was fetched anyway');
});

test('choosing another event loads it and renames the page', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  page.run(`selectEvent('${OLDER.slug}')`);
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.text('#live-h'), 'YCS Columbus');
  assert.equal(page.get('ROUNDS.length'), 4, 'the other event’s rounds are on screen');
  assert.ok(page.calls.some((c) => String(c.url).includes(OLDER.slug)));
});

test('switching away and back fetches again rather than trusting a stale mark', async (t) => {
  // Change detection is per event. Tracked globally, coming back would see the
  // mark left by the event in between and decide nothing had changed -- so the
  // page would keep the other event's rounds under this event's name.
  //
  // Both files answer with the same ETag, which is what makes this bite: a
  // global mark cannot tell "this file has not changed" from "this is a
  // different file that happens to share a validator".
  const page = await loadPage(twoEvents({
    'sample-remote-duel-ycs/rounds.json': () => ({
      status: 200, body: fixture(SAMPLE.path), headers: { ETag: '"same"' },
    }),
    'older-ycs-columbus/rounds.json': () => ({
      status: 200, body: JSON.stringify(olderRounds()), headers: { ETag: '"same"' },
    }),
  }));
  t.after(() => page.close());
  page.run(`selectEvent('${OLDER.slug}')`);
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.get('ROUNDS.length'), 4, 'the other event loaded at all');
  page.run(`selectEvent('${SAMPLE.slug}')`);
  await waitFor(page, `activeEvent === '${SAMPLE.slug}' && roundsState === 'ready'`);
  assert.equal(page.get('ROUNDS.length'), roundsFixture().formats[0].rounds.length,
    'came back to the first event and kept the second one’s rounds');
  assert.equal(page.text('#live-h'), SAMPLE.event);
});

/* Both events crowned somebody, so a reveal carried across from one would be
   the other's ending printed without being asked for. */
const withChampions = (extra = {}) => {
  const crown = (d, who) => {
    const f = d.formats[0];
    const last = f.rounds[f.rounds.length - 1];
    last.pairings = [{ table: 1, a: who, aDeck: 'Elfnote', b: 'Bo Peep', bDeck: 'Kewl Tune' }];
    f.champion = who;
    return d;
  };
  return twoEvents({
    'sample-remote-duel-ycs/rounds.json': () => ({
      status: 200, body: JSON.stringify(crown(roundsFixture(), 'Ada Lovelace')) }),
    'older-ycs-columbus/rounds.json': () => ({
      status: 200, body: JSON.stringify(crown(olderRounds(), 'Grace Hopper')) }),
    ...extra,
  });
};

const landOnChampion = (page) =>
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);

test('a champion revealed on one event is not revealed on the next', async (t) => {
  // The page hides who won until it is asked, because the rounds above are
  // worth reading first. Asked once, it stayed asked: switching events
  // printed the next event's ending beside a bracket nobody had read yet.
  const page = await loadPage(withChampions());
  t.after(() => page.close());
  landOnChampion(page);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  assert.match(page.text('#champion'), /Ada Lovelace/, 'revealed on the first event');

  page.run(`selectEvent('${'older-ycs-columbus'}')`);
  await waitFor(page, `activeEvent === 'older-ycs-columbus' && roundsState === 'ready'`);
  landOnChampion(page);
  assert.doesNotMatch(page.text('#champion'), /Grace Hopper/,
    "the next event's champion was given away without being asked for");
  assert.match(page.text('#champion'), /Reveal/);
});

test('and asking again on the second event still works', async (t) => {
  const page = await loadPage(withChampions());
  t.after(() => page.close());
  landOnChampion(page);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  page.run(`selectEvent('older-ycs-columbus')`);
  await waitFor(page, `activeEvent === 'older-ycs-columbus' && roundsState === 'ready'`);
  landOnChampion(page);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  assert.match(page.text('#champion'), /Grace Hopper/);
});

test('coming back to an event keeps the reveal the reader asked for', async (t) => {
  // The reveal belongs to a tournament, not to a moment. This reader has
  // already been told how this event ends and cannot be untold it, so asking
  // again on the way back would be ceremony rather than protection.
  const page = await loadPage(withChampions());
  t.after(() => page.close());
  landOnChampion(page);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  page.run(`selectEvent('older-ycs-columbus')`);
  await waitFor(page, `activeEvent === 'older-ycs-columbus' && roundsState === 'ready'`);
  page.run(`selectEvent('${'sample-remote-duel-ycs'}')`);
  await waitFor(page, `activeEvent === 'sample-remote-duel-ycs' && roundsState === 'ready'`);
  landOnChampion(page);
  assert.match(page.text('#champion'), /Ada Lovelace/,
    'the reader asked for this one and has not left it since');
});

test('the round the reader was on does not survive into another event', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  page.run(`selectRound('9')`);
  assert.equal(page.get('activeRound'), '9');
  page.run(`selectEvent('${OLDER.slug}')`);
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  // The other event has four rounds; round 9 is not one of them.
  assert.ok(page.json('ROUNDS.map(r => r.id)').includes(page.get('activeRound')),
    'landed on a round the event does not have');
});

test('a manifest that cannot be loaded is an error, not a blank page', async (t) => {
  const page = await loadPage({ routes: { 'events.json': { status: 500 } } });
  t.after(() => page.close());
  assert.equal(page.get('roundsState'), 'error');
  assert.match(page.text('#round-body'), /again|unavailable/i);
});

test('a manifest listing no events is rejected', async (t) => {
  const page = await loadPage({
    routes: { 'events.json': { status: 200, body: '{"events":[]}' } },
  });
  t.after(() => page.close());
  assert.equal(page.get('roundsState'), 'error');
});

test('coverage still loads when the archive does not', async (t) => {
  const page = await loadPage({ routes: { 'events.json': { status: 500 } } });
  t.after(() => page.close());
  assert.equal(page.get('roundsState'), 'error');
  assert.equal(page.get('coverageState'), 'ready', 'one failing must not block the other');
});

/* ---- coverage list ---------------------------------------------------- */

const FEED = (slug) => `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk</title><link>https://dueldesk.reizu.dev/</link>
  <description>Indexed from Konami's official event coverage.</description>
  <item><title>YCS Columbus: Round 3 Pairings (Advanced Format)</title>
    <link>https://yugiohblog.konami.com/a/</link><category>Pairings</category>
    <category domain="format">Advanced</category>
    <category domain="event">${slug}</category>
    <pubDate>Sat, 23 May 2026 18:00:00 +0000</pubDate></item>
</channel></rss>`;

test('a headline from another event opens that round here', async (t) => {
  // Which rounds that event published is in its own file, which has not been
  // fetched -- so the link carries what the post says and the page it opens
  // works it out on arrival. A table this archive holds is not worth sending
  // a reader to the blog for.
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(OLDER.slug) },
  }));
  t.after(() => page.close());
  const link = page.$('#events a.post__t--jump');
  assert.ok(link, 'the headline stays on the site');
  const url = new URL(link.getAttribute('href'), 'https://x/');
  assert.equal(url.pathname, '/');
  assert.equal(url.searchParams.get('event'), OLDER.slug);
  assert.equal(url.searchParams.get('round'), '3');
  assert.equal(url.searchParams.get('view'), 'pairings');
  assert.equal(page.$$('#events a.post__t[rel~="external"]').length, 0,
    'and does not also send them to Konami for it');
});

test('arriving on a round link lands on that round', async (t) => {
  const page = await loadPage({
    ...twoEvents(),
    search: `?event=${OLDER.slug}&round=3&view=pairings&format=Advanced`,
  });
  t.after(() => page.close());
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.json('activeRound'), '3');
  assert.equal(page.json('activeView'), 'pairings');
});

test('the round in the URL is read once, not on every event after it', async (t) => {
  // Arriving somewhere is not a standing instruction. Left unconsumed, the
  // round asked for once follows the reader into the next event they open.
  const page = await loadPage({
    ...twoEvents(),
    search: `?event=${OLDER.slug}&round=3&view=pairings&format=Advanced`,
  });
  t.after(() => page.close());
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.json('activeRound'), '3');

  page.$('#events [data-open-event]')?.click();
  page.run(`selectEvent('${SAMPLE.slug}')`);
  await waitFor(page, `activeEvent === '${SAMPLE.slug}' && roundsState === 'ready'`);
  assert.notEqual(page.json('activeRound'), '3',
    'the next event lands where its own data says, not where the URL did');
});

test('a view the page does not have is not obeyed', async (t) => {
  const page = await loadPage({
    ...twoEvents(),
    search: `?event=${OLDER.slug}&round=3&view=whatever`,
  });
  t.after(() => page.close());
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.match(page.json('activeView'), /^(pairings|standings|features)$/);
});

test('a round that event never published still opens the event', async (t) => {
  // The link is built from what a post says, not from that event's data, so
  // the round may not be there. Landing on the event is the answer; an error
  // for a URL that looks deliberate is not.
  const page = await loadPage({
    ...twoEvents(),
    search: `?event=${OLDER.slug}&round=Top8&view=pairings`,
  });
  t.after(() => page.close());
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.text('#live-h'), 'YCS Columbus');
  assert.ok(page.json('activeRound'), 'on some round of it');
});

test('an archived event offers to bring its rounds on screen', async (t) => {
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(OLDER.slug) },
  }));
  t.after(() => page.close());
  const button = page.$('#events [data-open-event]');
  assert.ok(button, 'no way to reach an event the archive holds');
  button.click();
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  assert.equal(page.text('#live-h'), 'YCS Columbus');
});

test('once an event is on screen its headlines become jumps', async (t) => {
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(OLDER.slug) },
  }));
  t.after(() => page.close());
  page.$('#events [data-open-event]').click();
  await waitFor(page, `activeEvent === '${OLDER.slug}' && roundsState === 'ready'`);
  const jump = page.$$('#events a.post__t--jump').find((a) => a.dataset.jumpRound === '3');
  assert.ok(jump, 'the round it names is on screen and still links away');
  assert.equal(page.$('#events [data-open-event]'), null,
    'nothing to open: it is already the event being read');
});

test('the event on screen is not offered as somewhere to go', async (t) => {
  // Every event in the archive is listed now, so the other one is there with
  // its own control. The one being read is the one that must not have it.
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(SAMPLE.slug) },
  }));
  t.after(() => page.close());
  const offered = page.$$('#events [data-open-event]').map((b) => b.dataset.openEvent);
  assert.ok(!offered.includes(SAMPLE.slug), offered.join(','));
  assert.deepEqual(offered, [OLDER.slug]);
});

test('a feed group is keyed on the event slug, not its display name', async (t) => {
  // Names are derived from what the coverage calls itself and can change
  // between scrapes; the slug is what the archive is keyed on.
  const feed = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk</title><link>https://dueldesk.reizu.dev/</link><description>x</description>
  <item><title>YCS Columbus: Round 3 Pairings</title>
    <link>https://yugiohblog.konami.com/a/</link><category>Pairings</category>
    <category domain="event">${OLDER.slug}</category>
    <pubDate>Sat, 23 May 2026 18:00:00 +0000</pubDate></item>
  <item><title>Columbus: Round 4 Pairings</title>
    <link>https://yugiohblog.konami.com/b/</link><category>Pairings</category>
    <category domain="event">${OLDER.slug}</category>
    <pubDate>Sat, 23 May 2026 19:00:00 +0000</pubDate></item>
</channel></rss>`;
  const page = await loadPage(twoEvents({ 'feed.xml': { status: 200, body: feed } }));
  t.after(() => page.close());
  assert.equal(page.get('EVENTS.length'), 1, 'two spellings, one event');
  assert.equal(page.get('EVENTS[0].posts.length'), 2);
});

test('the format choice does not hide other events entirely', async (t) => {
  // The selector chooses between the tournaments of the event on screen. With
  // four events in the archive, reading YCS Montréal's Advanced tournament made
  // the Genesys Championship vanish from the coverage list: every post it has is
  // Genesys, and none of them was ever part of the choice being made.
  const feed = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk</title><link>https://dueldesk.reizu.dev/</link><description>x</description>
  <item><title>YCS Columbus: Round 3 Pairings (Genesys Format)</title>
    <link>https://yugiohblog.konami.com/a/</link><category>Pairings</category>
    <category domain="format">Genesys</category>
    <category domain="event">${OLDER.slug}</category>
    <pubDate>Sat, 23 May 2026 18:00:00 +0000</pubDate></item>
</channel></rss>`;
  const page = await loadPage(twoEvents({ 'feed.xml': { status: 200, body: feed } }));
  t.after(() => page.close());
  assert.equal(page.get('activeFormat'), 'Advanced', 'reading the Advanced tournament');
  assert.equal(page.get('hasFormatChoice()'), true, 'and there is a choice to make');
  assert.equal(page.$$('#events article.event').length, 1,
    'the other event was filtered out by a choice that was not about it');
});

test('the format choice still filters the event on screen', async (t) => {
  const feed = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk</title><link>https://dueldesk.reizu.dev/</link><description>x</description>
  <item><title>Sample: Round 3 Pairings (Genesys Format)</title>
    <link>https://yugiohblog.konami.com/a/</link><category>Pairings</category>
    <category domain="format">Genesys</category>
    <category domain="event">${SAMPLE.slug}</category>
    <pubDate>Sat, 29 Aug 2026 18:00:00 +0000</pubDate></item>
</channel></rss>`;
  const page = await loadPage(twoEvents({ 'feed.xml': { status: 200, body: feed } }));
  t.after(() => page.close());
  assert.equal(page.get('activeFormat'), 'Advanced');
  // The event on screen keeps no posts under an Advanced filter, so it drops
  // out of the list. The other event is still listed -- unopened, it has no
  // posts to filter, and the row is how a reader reaches it.
  const listed = page.$$('#events .event__bar').map((b) => b.dataset.ev);
  assert.ok(!listed.includes(SAMPLE.event), listed.join(','));
});

/* ---- a tournament with no format name --------------------------------- */

test('an event that names no format does not claim one', async (t) => {
  // The North America WCQ titles every post "North America WCQ: Round 10
  // Pairings". That is one tournament with no format name, not a missing one,
  // and "Format —" states a gap where there is none.
  const page = await loadPage({
    routes: {
      'rounds.json': () => {
        const d = roundsFixture();
        d.formats = [{ ...d.formats[0], format: null }];
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());
  assert.equal(page.get('roundsState'), 'ready');
  assert.ok(!page.text('#hero-meta').includes('Format'),
    `named a format nobody stated: ${page.text('#hero-meta')}`);
  assert.ok(page.get('ROUNDS.length') > 0, 'the rounds are still shown');
});

test('standings with no points drop the columns nothing fills', async (t) => {
  // The blog does not always publish a points column -- YCS Columbus has none
  // for any of its 17 rounds -- and without points there is nothing to derive a
  // record from either. Printed anyway that is 1,618 rows of "?–?" beside 1,618
  // rows of "—": two columns wide, saying nothing twice.
  const page = await loadPage({
    routes: {
      'rounds.json': () => {
        const d = roundsFixture();
        for (const f of d.formats)
          for (const r of f.rounds)
            r.standings = (r.standings ?? []).map((s) => ({
              ...s, points: null,
              record: { wins: null, losses: null, draws: null, confidence: 'unknown' },
            }));
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());
  const round = page.json('ROUNDS.filter(r => r.standings.length).map(r => r.id)')[0];
  page.run(`selectRound('${round}'); activeView='standings'; renderRound();`);
  const heads = page.$$('#round-body thead th').map((th) => th.textContent.trim());
  assert.ok(!heads.includes('Record'), heads.join('/'));
  assert.ok(!heads.includes('Pts'), heads.join('/'));
  assert.ok(!page.text('#round-body').includes('?–?'), 'a column of nothing was printed');
  assert.ok(page.$$('#round-body tbody tr').length > 0, 'the standings are still shown');
});

test('standings keep the columns the coverage does fill', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  const round = page.json('ROUNDS.filter(r => r.standings.length).map(r => r.id)')[0];
  page.run(`selectRound('${round}'); activeView='standings'; renderRound();`);
  const heads = page.$$('#round-body thead th').map((th) => th.textContent.trim());
  assert.ok(heads.includes('Record'), heads.join('/'));
  assert.ok(heads.includes('Pts'), heads.join('/'));
});

test('where an event was held is shown, and is not in its name', async (t) => {
  // "YCS Santiago" is what the event is called; that it was in Chile is a
  // separate fact about it, and the blog writes it into the title for some
  // events and not others.
  const page = await loadPage({
    routes: {
      'rounds.json': () => {
        const d = roundsFixture();
        d.event = 'YCS Santiago';
        d.location = 'Santiago, Chile';
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());
  assert.equal(page.text('#live-h'), 'YCS Santiago');
  assert.match(page.text('#hero-meta'), /Santiago, Chile/);
});

test('an event with no known location says nothing about one', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  // "1,248 Duelists" has a comma; a location is a comma followed by a word.
  assert.ok(!/,\s*[A-Za-z]/.test(page.text('#hero-meta')), page.text('#hero-meta'));
});

/* ---- coverage comes from the archive, not the feed ---------------------- */

const POSTS = [
  { title: 'YCS Columbus: Round 3 Pairings', url: 'https://yugiohblog.konami.com/a/',
    modified: '2026-05-23T18:00:00Z', kind: 'pairings', format: 'Advanced',
    event: 'YCS Columbus', slug: OLDER.slug },
  { title: 'YCS Columbus: Standings After Round 3', url: 'https://yugiohblog.konami.com/b/',
    modified: '2026-05-23T17:00:00Z', kind: 'standings', format: 'Advanced',
    event: 'YCS Columbus', slug: OLDER.slug },
];

/* A feed with nothing in it, so these tests see the archive and only the
   archive. The shipped fixture feed carries events of its own, which the list
   correctly includes and which would drown out what is being asserted here. */
const BARE_FEED = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Duel Desk</title>
  <link>https://dueldesk.reizu.dev/</link><description>x</description></channel></rss>`;

const SAMPLE_POSTS = [
  { title: `${SAMPLE.event}: Round 1 Pairings`, url: 'https://yugiohblog.konami.com/s/',
    modified: '2026-08-29T18:00:00Z', kind: 'pairings', format: 'Advanced',
    event: SAMPLE.event, slug: SAMPLE.slug },
];

const withPosts = (extra = {}) => twoEvents({
  'feed.xml': { status: 200, body: BARE_FEED },
  'sample-remote-duel-ycs/posts.json': { status: 200, body: JSON.stringify(SAMPLE_POSTS) },
  'older-ycs-columbus/posts.json': { status: 200, body: JSON.stringify(POSTS) },
  ...extra,
});

const bars = (page) => page.$$('#events .event__bar').map((b) => b.dataset.ev);

/* Posts whose titles say nothing, which is most of the older archive. Central
   America WCQ 2014 titles forty-eight posts "WCQ" and puts what they are in
   the slug; the scraper read the title, the slug and the table on the page,
   and stored the answer. */
const MUTE_POSTS = [
  { title: 'WCQ', url: 'https://yugiohblog.konami.com/wcq-ca-top-16-pairings/',
    modified: '2026-05-23T18:00:00Z', kind: 'pairings',
    event: 'YCS Columbus', slug: OLDER.slug },
  { title: 'WCQ', url: 'https://yugiohblog.konami.com/wcq-ca-round-1-feature-match/',
    modified: '2026-05-23T17:00:00Z', kind: 'feature',
    event: 'YCS Columbus', slug: OLDER.slug },
];

test('every event in the archive is listed, not only those in the feed', async (t) => {
  // The feed is one river of the newest three hundred posts across the whole
  // archive: of fifty-two events, five had any item in it and forty-seven
  // showed no coverage at all.
  const page = await loadPage(withPosts());
  t.after(() => page.close());
  assert.deepEqual(bars(page), [SAMPLE.event, 'YCS Columbus']);
});

test("an event's posts are fetched when its group is opened", async (t) => {
  const page = await loadPage(withPosts());
  t.after(() => page.close());
  const asked = () => page.calls.filter((c) => String(c.url).includes(`${OLDER.slug}/posts.json`)).length;
  assert.equal(asked(), 0, 'a listed event costs nothing until it is opened');

  page.$$('#events .event__bar').find((b) => b.dataset.ev === 'YCS Columbus').click();
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  await tick(page, 2);
  assert.equal(asked(), 1);
  assert.match(page.text('#events'), /Round 3 Pairings/);
});

test('the event name is not repeated on every one of its posts', async (t) => {
  const page = await loadPage(withPosts());
  t.after(() => page.close());
  page.run(`loadEventPosts('${OLDER.slug}')`);
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  assert.deepEqual(page.json(`POSTS.get('${OLDER.slug}').map(p => p.title)`),
    ['Round 3 Pairings', 'Standings After Round 3']);
});

test('an event asked for twice before its posts arrive is fetched once', async (t) => {
  /* Both the render and the click ask, and on a slow connection the second ask
     lands while the first is still in flight. */
  const page = await loadPage(withPosts());
  t.after(() => page.close());
  page.run(`loadEventPosts('${OLDER.slug}'); loadEventPosts('${OLDER.slug}');`);
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  await tick(page, 2);
  page.run(`loadEventPosts('${OLDER.slug}')`);
  await tick(page, 2);
  assert.equal(
    page.calls.filter((c) => String(c.url).includes(`${OLDER.slug}/posts.json`)).length, 1,
    'once in flight and once already held, neither is fetched again');
});

test('an event whose posts will not load shows none rather than an error', async (t) => {
  // The rounds above it are the page's actual subject and they are on screen.
  const page = await loadPage(withPosts({
    'older-ycs-columbus/posts.json': { status: 500 },
  }));
  t.after(() => page.close());
  page.run(`loadEventPosts('${OLDER.slug}')`);
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  assert.deepEqual(page.json(`POSTS.get('${OLDER.slug}')`), []);
  assert.equal(page.get('coverageState'), 'ready');
});

test('an event whose posts will not load is not asked for again', async (t) => {
  /* The failed fetch records an empty list, and that record is what stops it
     being asked for again: without it every render finds the event still
     incomplete and fetches once more, which is a loop rather than an
     empty list. */
  const page = await loadPage(withPosts({
    'older-ycs-columbus/posts.json': { status: 500 },
  }));
  t.after(() => page.close());
  const asked = () => page.calls.filter((c) => String(c.url).includes(`${OLDER.slug}/posts.json`)).length;
  page.$$('#events .event__bar').find((b) => b.dataset.ev === 'YCS Columbus').click();
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  await tick(page, 3);
  page.run('renderEvents(); renderEvents();');
  await tick(page, 2);
  assert.equal(asked(), 1, 'asked once, and not again on every render');
});

test('the count is the archive\'s, not a tally of what has been opened', async (t) => {
  // The page fetches an event's posts only when it is opened, so a total added
  // up from what is loaded would climb as the reader worked down the list.
  // Here one post of the hundred and seventy-eight has actually been fetched.
  const page = await loadPage(withPosts({
    'events.json': { status: 200, body: JSON.stringify({
      events: [{ ...SAMPLE, postCount: 56 }, { ...OLDER, postCount: 122 }] }) },
  }));
  t.after(() => page.close());
  assert.match(page.text('#count'), /2 events · 178 updates/);
});

test('a four-figure total is grouped, as the duelist counts are', async (t) => {
  const page = await loadPage(withPosts({
    'events.json': { status: 200, body: JSON.stringify({
      events: [{ ...SAMPLE, postCount: 2000 }, { ...OLDER, postCount: 1060 }] }) },
  }));
  t.after(() => page.close());
  assert.match(page.text('#count'), /3,060 updates/);
});

test('a search counts what it matched rather than the archive', async (t) => {
  // Only a fetched event has post titles to search, so the archive's total
  // would be a promise the result cannot keep.
  const page = await loadPage(withPosts());
  t.after(() => page.close());
  page.run(`loadEventPosts('${OLDER.slug}')`);
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  await tick(page, 2);
  page.run(`qEl.value = 'Round 3 Pairings'; runSearch();`);
  assert.match(page.text('#count'), /1 matching/);
});

test('the list shows a handful of events and offers the rest', async (t) => {
  // Fifty-two events is a long way to scroll past to reach anything else.
  const many = Array.from({ length: 9 }, (_, i) => ({
    ...SAMPLE, slug: `e${i}`, event: `Event ${i}`, updated: `2026-0${i + 1}-01`,
    path: `events/e${i}/rounds.json`,
  }));
  const page = await loadPage({
    routes: {
      'events.json': { status: 200, body: JSON.stringify({ events: many }) },
      'rounds.json': () => ({ status: 200, body: JSON.stringify(roundsFixture()) }),
      // One post each, so none of them drops out for having no coverage and the
      // count is about how many the list shows rather than how many it has.
      'posts.json': { status: 200, body: JSON.stringify(SAMPLE_POSTS) },
      'feed.xml': { status: 200, body: BARE_FEED },
    },
  });
  t.after(() => page.close());
  assert.equal(bars(page).length, 5);
  assert.match(page.text('#events'), /Show all 9 events/);

  page.$('#events [data-show-all]').click();
  assert.equal(bars(page).length, 9);
  assert.equal(page.$('#events [data-show-all]'), null, 'nothing left to show');
});

test('a link naming an event opens that event, not the newest', async (t) => {
  // Where the winners list sends a reader: /?event=<slug>. A link that landed
  // on the newest event instead would be promising a destination it does not
  // reach, which is the rule the coverage rows already follow.
  const page = await loadPage({ ...withPosts(), search: `?event=${OLDER.slug}` });
  t.after(() => page.close());
  assert.equal(page.get('activeEvent'), OLDER.slug);
  assert.equal(page.json('eventInfo.event'), 'YCS Columbus');
});

test('a link naming an event the archive lacks falls back to the newest', async (t) => {
  // Rather than an empty page for a URL that looks deliberate.
  const page = await loadPage({ ...withPosts(), search: '?event=no-such-event' });
  t.after(() => page.close());
  assert.equal(page.get('activeEvent'), SAMPLE.slug);
});

test('a poll does not drag the reader back to the link they arrived by', async (t) => {
  const page = await loadPage({ ...withPosts(), search: `?event=${OLDER.slug}` });
  t.after(() => page.close());
  page.run(`selectEvent(${JSON.stringify(SAMPLE.slug)})`);
  await tick(page, 3);
  page.run('refreshRounds({poll: true})');
  await tick(page, 3);
  assert.equal(page.get('activeEvent'), SAMPLE.slug);
});

test('an event the feed names but the archive does not is still listed', async (t) => {
  // It should not happen -- the feed is built from the archive -- and if it
  // does the coverage is real, so hiding it would be the wrong way round.
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED('an-event-nobody-archived') },
  }));
  t.after(() => page.close());
  assert.ok(bars(page).includes('YCS Columbus'), bars(page).join(','));
});


test('a post is the kind the scraper read, not the one a headline suggests', async (t) => {
  // Read off "WCQ" alone both of these are news, and the reader's filter said
  // so for 309 posts the archive had already classified correctly.
  const page = await loadPage(withPosts({
    'older-ycs-columbus/posts.json': { status: 200, body: JSON.stringify(MUTE_POSTS) },
  }));
  t.after(() => page.close());
  page.$$('#events .event__bar').find((b) => b.dataset.ev === 'YCS Columbus').click();
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  const kinds = page.json(`POSTS.get('${OLDER.slug}').map(p => p.kind)`);
  assert.deepEqual(kinds, ['pairings', 'feature']);
});

test('a post with no stored kind is classified from its headline', async (t) => {
  // posts.json written before the scraper recorded one, and the feed's own
  // items, which arrive with nothing attached.
  const page = await loadPage(withPosts({
    'older-ycs-columbus/posts.json': { status: 200, body: JSON.stringify(
      MUTE_POSTS.map(({kind, ...rest}) => ({...rest, title: 'Round 3 Pairings'}))) },
  }));
  t.after(() => page.close());
  page.$$('#events .event__bar').find((b) => b.dataset.ev === 'YCS Columbus').click();
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  assert.deepEqual(page.json(`POSTS.get('${OLDER.slug}').map(p => p.kind)`),
    ['pairings', 'pairings']);
});

test('the round still comes from the headline, which posts.json does not store', async (t) => {
  const page = await loadPage(withPosts({
    'older-ycs-columbus/posts.json': { status: 200, body: JSON.stringify([
      { ...MUTE_POSTS[0], title: 'Top 8 Pairings' }]) },
  }));
  t.after(() => page.close());
  page.$$('#events .event__bar').find((b) => b.dataset.ev === 'YCS Columbus').click();
  await waitFor(page, `POSTS.has('${OLDER.slug}')`);
  assert.equal(page.json(`POSTS.get('${OLDER.slug}')[0].round`), 'Top 8');
});
