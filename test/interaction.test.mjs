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
  assert.match(page.text('#stamp'), /^Updated .+ · refresh to check for new coverage$/);
});
