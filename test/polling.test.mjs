import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor, fixture } from './harness.mjs';

const feedCalls = (page) => page.calls.filter((c) => c.url.includes('feed.xml')).length;

/** Serve the feed with a controllable ETag so "changed" can be simulated. */
function versionedFeed(state) {
  return () => ({ status: 200, body: state.body, headers: { ETag: state.etag } });
}

test('an unchanged poll does not repaint the list', async (t) => {
  const state = { body: fixture('feed.xml'), etag: '"v1"' };
  const page = await loadPage({ routes: { 'feed.xml': versionedFeed(state) } });
  t.after(() => page.close());

  // Mark the live DOM. If the list is rebuilt, the marker disappears.
  page.run(`document.querySelector('.event').dataset.marker = 'kept'`);
  const before = feedCalls(page);

  const result = await page.run('pollOnce()');
  assert.equal(result.changed, false, 'reported unchanged');
  assert.ok(feedCalls(page) > before, 'it really did make the request');
  assert.equal(page.$('.event').dataset.marker, 'kept',
    'the DOM survived: an unchanged poll must not re-render');
});

test('a changed ETag does repaint', async (t) => {
  const state = { body: fixture('feed.xml'), etag: '"v1"' };
  const page = await loadPage({ routes: { 'feed.xml': versionedFeed(state) } });
  t.after(() => page.close());

  page.run(`document.querySelector('.event').dataset.marker = 'kept'`);
  state.etag = '"v2"';
  const result = await page.run('pollOnce()');

  assert.equal(result.changed, true);
  assert.equal(page.$('.event').dataset.marker, undefined, 'the list was rebuilt');
});

test('change detection uses the ETag, not the status code', async (t) => {
  // A revalidated 304 reaches script as a 200 with the cached body, so a
  // status-based check would never fire. Same body, same ETag, status 200.
  const state = { body: fixture('feed.xml'), etag: '"stable"' };
  const page = await loadPage({ routes: { 'feed.xml': versionedFeed(state) } });
  t.after(() => page.close());

  for (let i = 0; i < 3; i++) {
    const r = await page.run('pollOnce()');
    assert.equal(r.changed, false, `poll ${i + 1} correctly saw no change despite a 200`);
  }
  assert.equal(page.get('feedVersion'), '"stable"');
});

test('change detection falls back when the server sends no ETag', async (t) => {
  // python -m http.server sends Last-Modified only; some servers send neither.
  // Relying on ETag alone would re-render on every poll and steal focus.
  const body = fixture('feed.xml');
  const lastMod = { body, when: 'Fri, 28 Aug 2026 04:00:00 GMT' };
  const page = await loadPage({
    routes: {
      'feed.xml': () => ({ status: 200, body: lastMod.body, headers: { 'Last-Modified': lastMod.when } }),
    },
  });
  t.after(() => page.close());

  page.run(`document.querySelector('.event').dataset.marker = 'kept'`);
  assert.equal((await page.run('pollOnce()')).changed, false, 'Last-Modified alone detects no change');
  assert.equal(page.$('.event').dataset.marker, 'kept', 'and does not re-render');

  lastMod.when = 'Fri, 28 Aug 2026 05:00:00 GMT';
  assert.equal((await page.run('pollOnce()')).changed, true, 'a newer Last-Modified is a change');
});

test('change detection still works with no caching headers at all', async (t) => {
  const body = fixture('feed.xml');
  const bare = { body };
  const page = await loadPage({
    routes: { 'feed.xml': () => ({ status: 200, body: bare.body }) },   // no headers
  });
  t.after(() => page.close());

  page.run(`document.querySelector('.event').dataset.marker = 'kept'`);
  assert.equal((await page.run('pollOnce()')).changed, false, 'falls back to comparing the body');
  assert.equal(page.$('.event').dataset.marker, 'kept');

  bare.body = body.replace('</channel>', `<item><title>E: Round 99 pairings</title>
    <link>https://x.example/</link><pubDate>Fri, 28 Aug 2026 06:00:00 +0000</pubDate></item></channel>`);
  assert.equal((await page.run('pollOnce()')).changed, true, 'a different body is a change');
});

test('a malformed rounds.json is retried rather than remembered as current', async (t) => {
  let broken = false;
  const page = await loadPage({
    routes: { 'rounds.json': () => (broken ? { status: 200, body: '{ not json', headers: { ETag: '"bad"' } } : undefined) },
  });
  t.after(() => page.close());

  broken = true;
  await page.run('refreshRounds()');
  assert.equal(page.get('roundsState'), 'error');
  assert.notEqual(page.get('roundsVersion'), '"bad"',
    'a version that failed to parse must not be recorded, or the retry would short-circuit');

  broken = false;
  await page.run('refreshRounds()');
  assert.equal(page.get('roundsState'), 'ready', 'and the retry actually re-reads');
});

test('a poll does not move the reader off the round they chose', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('5')`);
  assert.equal(page.get('activeRound'), '5');

  page.run(`roundsVersion = null`);          // force a full re-read
  await page.run('pollOnce()');
  assert.equal(page.get('activeRound'), '5', 'still on round 5 after a poll');
});

test('a poll keeps focus on the event the reader was using', async (t) => {
  const state = { body: fixture('feed.xml'), etag: '"v1"' };
  const page = await loadPage({ routes: { 'feed.xml': versionedFeed(state) } });
  t.after(() => page.close());

  const bar = page.$('.event__bar');
  const key = bar.dataset.ev;
  bar.focus();
  assert.equal(page.document.activeElement, bar);

  state.etag = '"v2"';                    // force a real re-render
  await page.run('pollOnce()');

  const focused = page.document.activeElement;
  assert.ok(focused?.classList.contains('event__bar'), 'focus is still on an event toggle');
  assert.equal(focused.dataset.ev, key, 'and on the same event');
});

test('polling stops while the tab is hidden and resumes on return', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const hide = (v) => page.run(
    `Object.defineProperty(document, 'hidden', {value: ${v}, configurable: true});
     document.dispatchEvent(new Event('visibilitychange'))`);

  hide(true);
  assert.equal(page.get('pollTimer'), null, 'no timer while hidden');
  const during = feedCalls(page);
  assert.equal((await page.run('pollOnce()')).skipped, true, 'a poll while hidden is a no-op');
  assert.equal(feedCalls(page), during, 'and makes no request');

  hide(false);
  await waitFor(page, 'pollTimer !== null');
  assert.ok(feedCalls(page) > during, 'returning to view checks immediately');
});

test('failures back off exponentially and recover', async (t) => {
  let fail = false;
  const page = await loadPage({ routes: { 'feed.xml': () => (fail ? { status: 500 } : undefined) } });
  t.after(() => page.close());

  const base = page.get('POLL_LIVE_MS');
  fail = true;
  page.run(`schedulePoll(true)`);
  const first = page.get('pollDelay');
  assert.ok(first > base, `backed off from ${base} to ${first}`);

  page.run(`schedulePoll(true)`);
  assert.ok(page.get('pollDelay') > first, 'and again');

  for (let i = 0; i < 12; i++) page.run(`schedulePoll(true)`);
  assert.equal(page.get('pollDelay'), page.get('POLL_MAX_MS'), 'capped, not unbounded');

  fail = false;
  page.run(`schedulePoll(false)`);
  assert.ok(page.get('pollDelay') <= page.get('POLL_IDLE_MS'), 'reset on success');
});

test('the interval slows down when nothing is live', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  page.run(`EVENTS.forEach(e => e.live = true)`);
  page.run(`schedulePoll(false)`);
  assert.equal(page.get('pollDelay'), page.get('POLL_LIVE_MS'));

  page.run(`EVENTS.forEach(e => e.live = false); ROUNDS.forEach(r => { if (r.state === 'live') r.state = 'done'; })`);
  page.run(`schedulePoll(false)`);
  assert.equal(page.get('pollDelay'), page.get('POLL_IDLE_MS'), 'idle polling is slower');
});

test('polls never overlap', async (t) => {
  let release;
  const gate = new Promise((r) => { release = r; });
  let concurrent = 0, peak = 0;
  const page = await loadPage({
    routes: {
      'feed.xml': async () => {
        concurrent++; peak = Math.max(peak, concurrent);
        await gate;
        concurrent--;
        return undefined;
      },
    },
    settle: false,
  });
  t.after(() => page.close());
  release();
  await waitFor(page, "coverageState !== 'loading'");

  page.run(`feedVersion = null`);
  const a = page.run('pollOnce()');
  const b = page.run('pollOnce()');
  const [ra, rb] = await Promise.all([a, b]);
  assert.ok(ra.skipped || rb.skipped, 'the second poll was refused while one was in flight');
  assert.ok(peak <= 1, `no concurrent feed requests (peak ${peak})`);
});

test('one resource failing does not stop the other being polled', async (t) => {
  let failRounds = false;
  const page = await loadPage({
    routes: { 'rounds.json': () => (failRounds ? { status: 500 } : undefined) },
  });
  t.after(() => page.close());

  failRounds = true;
  page.run(`feedVersion = null; roundsVersion = null`);
  const before = feedCalls(page);
  const result = await page.run('pollOnce()');

  assert.equal(page.get('roundsState'), 'error', 'rounds failed');
  assert.ok(feedCalls(page) > before, 'the feed was still requested');
  assert.equal(page.get('coverageState'), 'ready', 'and coverage is fine');
  assert.equal(result.failed, true, 'the poll reports failure so backoff applies');
});

test('new posts are announced, unchanged polls are not', async (t) => {
  const full = fixture('feed.xml');
  // Start from a feed with the newest item removed, then restore it.
  const trimmed = full.replace(/<item>[\s\S]*?<\/item>/, '');
  const state = { body: trimmed, etag: '"v1"' };
  const page = await loadPage({ routes: { 'feed.xml': () => ({ status: 200, body: state.body, headers: { ETag: state.etag } }) } });
  t.after(() => page.close());

  // Boot's own selectRound() queues an announcement on a 60ms timer; let it
  // land before clearing, or it repopulates the region mid-test.
  await new Promise((r) => setTimeout(r, 150));
  page.run(`announce.textContent = ''`);
  await page.run('pollOnce()');                        // unchanged
  await new Promise((r) => setTimeout(r, 120));
  assert.equal(page.text('#announce'), '', 'an unchanged poll announces nothing');

  state.body = full; state.etag = '"v2"';
  await page.run('pollOnce()');                        // one post more
  await new Promise((r) => setTimeout(r, 120));
  assert.match(page.text('#announce'), /Coverage updated, 1 new post\b/);
});

test('a change that adds no posts announces nothing', async (t) => {
  // An edit to an existing post changes the ETag but not the count. Announcing
  // "0 new posts" would be worse than silence.
  const full = fixture('feed.xml');
  const state = { body: full, etag: '"v1"' };
  const page = await loadPage({
    routes: { 'feed.xml': () => ({ status: 200, body: state.body, headers: { ETag: state.etag } }) },
  });
  t.after(() => page.close());

  await new Promise((r) => setTimeout(r, 150));
  page.run(`announce.textContent = ''`);

  // Same number of items, one title reworded, new ETag.
  state.body = full.replace(/<title>([^<]*Round 12[^<]*)<\/title>/, '<title>Round 12 pairings (updated)</title>');
  state.etag = '"v2"';
  const result = await page.run('pollOnce()');
  await new Promise((r) => setTimeout(r, 150));

  assert.equal(result.changed, true, 'the poll did see a change');
  assert.equal(page.text('#announce'), '', 'but announced nothing, because no post was added');
});

test('a poll that recovers from stale clears the notice', async (t) => {
  let fail = false;
  const page = await loadPage({ routes: { 'feed.xml': () => (fail ? { status: 500 } : undefined) } });
  t.after(() => page.close());

  fail = true;
  await page.run('refreshCoverage()');
  await waitFor(page, "coverageState === 'stale'");
  assert.ok(page.$('.notice'), 'stale notice shown');

  fail = false;
  await page.run('pollOnce()');
  assert.equal(page.get('coverageState'), 'ready');
  assert.equal(page.$('.notice'), null, 'notice cleared even though the ETag was unchanged');
});
