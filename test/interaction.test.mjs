import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor } from './harness.mjs';

test('theme is resolved before paint and persisted', async (t) => {
  const dark = await loadPage();
  t.after(() => dark.close());
  assert.equal(dark.document.documentElement.dataset.theme, 'dark', 'defaults to dark');

  const stored = await loadPage({ storedTheme: 'light' });
  t.after(() => stored.close());
  assert.equal(stored.document.documentElement.dataset.theme, 'light',
    'a stored choice is applied by the pre-paint script, so there is no flash');
  assert.equal(stored.$('[data-theme-set="light"]').getAttribute('aria-pressed'), 'true');

  const sys = await loadPage({ storedTheme: 'system', prefersLight: true });
  t.after(() => sys.close());
  assert.equal(sys.document.documentElement.dataset.theme, 'light', 'system follows the OS');
});

test('choosing a theme writes it to storage', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.$('[data-theme-set="light"]').click();
  assert.equal(page.document.documentElement.dataset.theme, 'light');
  assert.equal(page.window.localStorage.getItem('dd-theme'), 'light');
  assert.equal(page.$$('[data-theme-set][aria-pressed="true"]').length, 1);
});

test('filtering narrows the coverage list to one kind', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.$('[data-filter="pairings"]').click();
  const labels = page.$$('.post__k').map((n) => n.textContent);
  assert.ok(labels.length > 0, 'something matched');
  assert.ok(labels.every((l) => l === 'Pairings'), `unexpected kinds: ${[...new Set(labels)]}`);
  assert.equal(page.$$('[data-filter][aria-pressed="true"]').length, 1);
});

test('the format filter narrows the coverage list to one tournament', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const buttons = page.$$('[data-feed-format]').map((b) => b.dataset.feedFormat);
  assert.ok(buttons.length > 2, `no format choice to make: ${buttons}`);
  const before = page.$$('#events .post__t').length;
  const formatOfTitle = new Map(page.run(`coverageEvents().flatMap(e => e.posts)
    .map(p => [p.title, p.format ?? null])`));

  /* Every format, not one of them. Reading off the rendered list rather than
     off the predicate, because asking inChosenFormat what it thinks proves
     only that it agrees with itself -- that version passed cleanly with the
     call to it taken out of the list's own filter. */
  let narrowedByOne = false;
  for (const pick of buttons.filter((f) => f !== 'all')){
    page.$(`[data-feed-format="${pick}"]`).click();
    const titles = page.$$('#events .post__t').map((n) => n.textContent.trim());
    assert.ok(titles.length > 0, `${pick} emptied the list`);
    if (titles.length < before) narrowedByOne = true;
    /* Every post left is either that format or event-wide: an announcement or
       a winner carries no format and belongs to whichever tournament you read. */
    const leaked = titles.filter((t) => {
      const f = formatOfTitle.get(t);
      return f !== undefined && f !== null && f !== pick;
    });
    assert.deepEqual(leaked, [], `${pick} still shows other formats: ${leaked}`);
    assert.equal(page.$$('[data-feed-format][aria-pressed="true"]').length, 1);
  }
  assert.ok(narrowedByOne, `no format changed the list of ${before}`);
});

test('a post with no format survives every format filter', async (t) => {
  /* Filtering these away hid every winner announcement and table of contents
     the moment anybody chose a format. */
  const page = await loadPage();
  t.after(() => page.close());
  const kept = page.run(`formatFilter='Genesys'; coverageEvents().flatMap(e => e.posts)
    .filter(p => !p.format).every(p => inChosenFormat(p))`);
  assert.equal(kept, true);
});

test('the format row stays hidden when there is nothing to choose', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  /* Through coverageEvents, which is where the row reads them from: an event's
     posts come out of POSTS once it has been opened and out of the feed
     before that, and mutating only one of the two proves nothing. */
  const hidden = page.run(`
    coverageEvents().forEach(e => (e.posts || []).forEach(p => { p.format = 'Advanced'; }));
    formatButtons = null; renderEvents();
    document.getElementById('format-filters').hidden`);
  assert.equal(hidden, true, 'one format is not a choice');
});

test('search filters the round table as the caption promises', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('12')`);
  const all = page.$$('#round-body tbody tr').length;
  assert.ok(all > 1);

  const name = page.run(`ROUNDS.find(r => r.id === '12').pairings[0].a`);
  page.run(`query = ${JSON.stringify(name.toLowerCase())}; renderRound()`);
  const rows = page.$$('#round-body tbody tr');
  assert.equal(rows.length, 1, 'exactly the matching table');
  assert.match(rows[0].textContent, new RegExp(name.split(' ').pop()));

  page.run(`query = 'zzzznotathing'; renderRound()`);
  assert.ok(page.$('#round-body .empty'), 'an empty state, not a blank table');

  page.run(`query = ''; renderRound()`);
  assert.equal(page.$$('#round-body tbody tr').length, all, 'restored');
});

test('expanding an event does not rebuild the list or lose the button', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const bar = page.$('.event__bar');
  const wasOpen = bar.getAttribute('aria-expanded') === 'true';

  bar.click();
  assert.equal(bar.getAttribute('aria-expanded'), String(!wasOpen));
  assert.equal(page.document.getElementById(bar.getAttribute('aria-controls')).hidden, wasOpen);
  assert.equal(page.$('.event__bar'), bar, 'same node: the list was not re-rendered');
});

test('the coverage list handler survives repeated re-renders', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (let i = 0; i < 6; i++) page.run('renderEvents()');
  const bar = page.$('.event__bar');
  const before = bar.getAttribute('aria-expanded');
  bar.click();
  assert.notEqual(page.$('.event__bar').getAttribute('aria-expanded'), before,
    'one delegated handler still fires after six re-renders');
});

test('the stamp reports the feed time, machine-readable', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const time = page.$('#stamp time');
  assert.ok(time, 'a <time> element is rendered');
  assert.ok(!Number.isNaN(Date.parse(time.getAttribute('datetime'))), 'with a parseable datetime');
  assert.equal(time.getAttribute('datetime'), page.run('feedUpdated.toISOString()'));
  assert.match(page.text('#stamp'), /^Updated .+ · refreshes automatically$/);
});

test('theme-color follows the chosen theme, not just the OS', async (t) => {
  const meta = (p) => p.document.getElementById('theme-color');

  // Explicit light on a dark-preferring OS: the browser chrome must follow the
  // choice, which the media-query pair alone could never do.
  const light = await loadPage({ storedTheme: 'light', prefersLight: false });
  t.after(() => light.close());
  assert.equal(meta(light).content, '#EDF0F6');

  const dark = await loadPage({ storedTheme: 'dark', prefersLight: true });
  t.after(() => dark.close());
  assert.equal(meta(dark).content, '#0E1119');

  // It must come before the media-query fallbacks, or it never applies.
  const all = dark.$$('meta[name="theme-color"]');
  assert.ok(all.length >= 2, 'the no-JS fallback pair is still present');
  assert.equal(all[0].id, 'theme-color', 'the JS-managed tag is first');
  assert.equal(all[0].getAttribute('media'), null, 'and unconditional, so it wins');
});

test('toggling the theme updates the browser chrome', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const meta = page.document.getElementById('theme-color');
  assert.equal(meta.content, '#0E1119');

  page.$('[data-theme-set="light"]').click();
  assert.equal(meta.content, '#EDF0F6', 'chrome follows the toggle');
  page.$('[data-theme-set="dark"]').click();
  assert.equal(meta.content, '#0E1119');
});

test('the tabpanel does not add a second tab stop in front of the table', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const panel = page.$('#round-body');

  // Views that render a focusable scroll container.
  for (const view of ['pairings', 'standings']) {
    page.$(`[data-view="${view}"]`).click();
    assert.ok(page.$('#round-body .tblwrap'), `${view} renders a focusable region`);
    assert.equal(panel.getAttribute('tabindex'), null,
      `${view}: the panel must not also be a tab stop`);
  }

  // The feature view renders no scroll container, but its Duelists are links
  // to their own pages, so it is reachable through them and the panel must
  // not be a second stop in front of them.
  page.$('[data-view="feature"]').click();
  assert.equal(page.$('#round-body .tblwrap'), null);
  assert.ok(page.$('#round-body a[href^="/player/"]'), 'feature view names are links');
  assert.equal(panel.getAttribute('tabindex'), null,
    'feature view: the links are the tab stops, not the panel');

  // And a state with nothing focusable at all, which is the other half of the
  // rule: the panel itself has to be reachable or its text is unreachable by
  // keyboard. Every round of this simulation now links out of its Duelists,
  // so the empty state is the one that still proves it.
  page.run(`roundsState = 'loading'; renderRound();`);
  assert.equal(page.$$('#round-body a[href], #round-body button').length, 0,
    'the loading state has nothing of its own to focus');
  assert.equal(panel.getAttribute('tabindex'), '0', 'loading: the panel is reachable');
});

test('the panel tab stop is correct in the loading and error states', async (t) => {
  const err = await loadPage({ routes: { 'rounds.json': { status: 500 } } });
  t.after(() => err.close());
  // The error state offers a retry button, which is itself focusable.
  assert.ok(err.$('#round-body [data-retry-rounds]'));
  assert.equal(err.$('#round-body').getAttribute('tabindex'), null,
    'the retry button is the tab stop, not the panel');
});
