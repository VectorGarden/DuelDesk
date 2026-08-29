/**
 * The archive: more than one event, and choosing between them.
 *
 * One event's rounds are about 1.3MB, so they are not all loaded at once. The
 * page reads events.json — every event, small enough to load first — and fetches
 * the rounds only for the event being read.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor, fixture, roundsFixture } from './harness.mjs';

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
    ...extra,
  },
});

test('one event is not presented as a choice', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  assert.equal(page.$('#event-pick').hidden, true,
    'the archive holds one event; there is nothing to pick');
});

test('the picker lists every event, newest first', async (t) => {
  const page = await loadPage(twoEvents());
  t.after(() => page.close());
  assert.equal(page.$('#event-pick').hidden, false);
  assert.deepEqual(page.$$('#event-select option').map((o) => o.value),
    [SAMPLE.slug, OLDER.slug]);
  assert.deepEqual(page.$$('#event-select option').map((o) => o.textContent),
    [`${SAMPLE.event} · Aug 2026`, 'YCS Columbus · May 2026']);
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
  const labels = page.$$('#event-select option').map((o) => o.textContent);
  assert.equal(new Set(labels).size, labels.length, `not distinguishable: ${labels}`);
  assert.deepEqual(labels.slice(1), ['YCS Columbus · May 2026', 'YCS Columbus · May 2025']);
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
    assert.equal(page.$$('#event-select option')[1].textContent, 'YCS Columbus',
      `updated: ${JSON.stringify(updated)}`);
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
  assert.equal(page.$$('#event-select option')[0].textContent, 'YCS Columbus · May 2026');
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

test('a headline from another event does not offer a jump that cannot land', async (t) => {
  // Which rounds that event published is in its own file, which has not been
  // fetched. Offering the jump anyway would be guessing.
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(OLDER.slug) },
  }));
  t.after(() => page.close());
  assert.equal(page.$$('#events a.post__t--jump').length, 0);
  assert.ok(page.$('#events a.post__t[rel~="external"]'), 'it still links to the post');
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
  const page = await loadPage(twoEvents({
    'feed.xml': { status: 200, body: FEED(SAMPLE.slug) },
  }));
  t.after(() => page.close());
  assert.equal(page.$('#events [data-open-event]'), null);
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
  assert.equal(page.$$('#events article.event').length, 0,
    'a Genesys post from the event on screen is not part of its Advanced tournament');
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
