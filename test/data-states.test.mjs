import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor } from './harness.mjs';

const EMPTY_FEED = `<?xml version="1.0"?><rss version="2.0"><channel>
  <title>t</title><link>l</link><description>d</description></channel></rss>`;

test('coverage reaches ready against the shipped feed', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.get('coverageState'), 'ready');
  assert.ok(page.get('EVENTS.length') >= 1);
  assert.match(page.text('#count'), /event/);
});

test('a failed first load shows an error with a retry, not a blank page', async (t) => {
  const page = await loadPage({ routes: { 'feed.xml': { status: 503 } } });
  t.after(() => page.close());

  assert.equal(page.get('coverageState'), 'error');
  assert.match(page.text('#events'), /503/, 'the reason is surfaced');
  assert.ok(page.$('[data-retry]'), 'retry offered');
  assert.equal(page.text('#count'), 'Unavailable');
  assert.equal(page.text('#stamp'), 'Coverage unavailable');
});

test('retry recovers after a transient failure', async (t) => {
  let fail = true;
  const page = await loadPage({
    routes: { 'feed.xml': () => (fail ? { status: 503 } : undefined) },
  });
  t.after(() => page.close());
  assert.equal(page.get('coverageState'), 'error');

  fail = false;
  page.$('[data-retry]').click();
  await waitFor(page, "coverageState === 'ready'");
  assert.ok(page.get('EVENTS.length') >= 1);
  assert.ok(page.$$('.event').length >= 1);
});

test('a failed RELOAD goes stale and keeps the data on screen', async (t) => {
  let fail = false;
  const page = await loadPage({
    routes: { 'feed.xml': () => (fail ? { status: 500 } : undefined) },
  });
  t.after(() => page.close());
  const before = page.get('EVENTS.length');
  assert.ok(before >= 1);

  fail = true;
  await page.run('refreshCoverage()');
  await waitFor(page, "coverageState === 'stale'");

  assert.equal(page.get('EVENTS.length'), before, 'data survives the failed reload');
  assert.equal(page.$$('.event').length, before, 'and is still rendered');
  assert.ok(page.$('.notice'), 'a notice explains why');
  assert.equal(page.$('.notice').getAttribute('role'), 'status');
  assert.ok(page.$('#stamp time'), 'the last good timestamp is kept');
});

test('a reachable but empty feed is distinguished from an error', async (t) => {
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: EMPTY_FEED } } });
  t.after(() => page.close());
  assert.equal(page.get('coverageState'), 'empty');
  assert.match(page.text('#events'), /no items/i);
});

test('malformed feed XML becomes an error rather than throwing', async (t) => {
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: 'not xml <<<' } } });
  t.after(() => page.close());
  assert.equal(page.get('coverageState'), 'error');
  assert.equal(page.errors.length, 0, 'no uncaught jsdom error');
});

test('rounds and coverage fail independently', async (t) => {
  const roundsDown = await loadPage({ routes: { 'rounds.json': { status: 500 } } });
  t.after(() => roundsDown.close());
  assert.equal(roundsDown.get('roundsState'), 'error');
  assert.equal(roundsDown.get('coverageState'), 'ready', 'coverage still loads');
  assert.ok(roundsDown.$$('.event').length >= 1, 'and still renders');
  assert.match(roundsDown.text('#round-body'), /could not be loaded/, 'round error painted');
  assert.equal(roundsDown.text('#live-h'), 'Event unavailable');

  const feedDown = await loadPage({ routes: { 'feed.xml': { status: 500 } } });
  t.after(() => feedDown.close());
  assert.equal(feedDown.get('coverageState'), 'error');
  assert.equal(feedDown.get('roundsState'), 'ready', 'round panel unaffected');
  assert.ok(feedDown.$('#round-body tbody'), 'and still renders a table');
});

test('rounds.json is rejected when malformed or empty', async (t) => {
  const bad = await loadPage({ routes: { 'rounds.json': { status: 200, body: '{ not json' } } });
  t.after(() => bad.close());
  assert.equal(bad.get('roundsState'), 'error');
  assert.equal(bad.errors.length, 0);

  const empty = await loadPage({ routes: { 'rounds.json': { status: 200, body: '{"rounds":[]}' } } });
  t.after(() => empty.close());
  assert.equal(empty.get('roundsState'), 'error');
  assert.match(empty.get('roundsError'), /no rounds/);
});

test('both loads revalidate rather than reading a stale cache', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const relevant = page.calls.filter((c) => /feed\.xml|rounds\.json/.test(c.url));
  assert.ok(relevant.length >= 2, 'both resources were fetched');
  for (const c of relevant) {
    assert.equal(c.options?.cache, 'no-cache',
      `${c.url} must revalidate: GitHub Pages serves these with max-age=600`);
  }
});
