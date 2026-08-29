/**
 * Searching the event archive.
 *
 * Fifty-two events, a dozen of them a YCS in a city you would have to scroll a
 * select to find, and several sharing a name across years. So the picker is a
 * combobox: type, and the list narrows.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, waitFor, tick, fixture, roundsFixture } from './harness.mjs';

const SAMPLE = JSON.parse(fixture('events.json')).events[0];

/* A slice of the real archive: two events sharing a name across years, a
   qualifier whose coverage called it something else, and one with a location. */
const CATALOG = [
  { ...SAMPLE, slug: '2026-north-america-wcq', event: 'North America WCQ 2026',
    updated: '2026-07-12' },
  { ...SAMPLE, slug: '2025-10-ycs-anaheim', event: 'YCS Anaheim', updated: '2025-10-06' },
  { ...SAMPLE, slug: '2024-12-ycs-anaheim', event: 'YCS Anaheim', updated: '2024-12-07' },
  { ...SAMPLE, slug: '2018-north-america-wcq', event: 'North America WCQ 2018',
    updated: '2018-06-23' },
  { ...SAMPLE, slug: '201603-santiago-chile', event: 'YCS Santiago',
    location: 'Santiago, Chile', updated: '2016-05-02' },
];

const archive = (extra = {}) => ({
  routes: {
    'events.json': { status: 200, body: JSON.stringify({ events: CATALOG }) },
    'rounds.json': () => ({ status: 200, body: JSON.stringify(roundsFixture()) }),
    ...extra,
  },
});

const open = (page) => page.run('openPicker(true)');
const type = (page, q) => {
  const input = page.$('#event-search');
  input.value = q;
  input.dispatchEvent(new page.window.Event('input', { bubbles: true }));
};
const shown = (page) =>
  page.$$('#event-list [role="option"]').map((li) => li.dataset.slug ?? null);
const names = (page) =>
  page.$$('#event-list [role="option"] b').map((b) => b.textContent.trim());
const key = (page, k) => {
  const input = page.$('#event-search');
  input.dispatchEvent(new page.window.KeyboardEvent('keydown',
    { key: k, bubbles: true, cancelable: true }));
};

test('the list is closed until asked for', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  assert.equal(page.$('#event-list').hidden, true);
  assert.equal(page.$('#event-search').getAttribute('aria-expanded'), 'false');
});

test('closed, the box says which event is on screen', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  assert.equal(page.$('#event-search').value, 'North America WCQ 2026');
});

test('opening it offers every event, not just the one on screen', async (t) => {
  // Pre-filling the query with the current event's name would show one result
  // and read as though nothing else existed.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  assert.equal(page.$('#event-search').value, '');
  assert.equal(shown(page).length, CATALOG.length);
  assert.equal(page.$('#event-search').getAttribute('aria-expanded'), 'true');
});

test('typing narrows the list', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'anaheim');
  assert.deepEqual(shown(page), ['2025-10-ycs-anaheim', '2024-12-ycs-anaheim']);
});

test('a year finds the event held in it', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, '2018');
  assert.deepEqual(shown(page), ['2018-north-america-wcq']);
});

test('the words may be given in any order', async (t) => {
  // "wcq 2018" and "2018 wcq" are the same request, and neither is a substring
  // of "North America WCQ 2018".
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  for (const q of ['wcq 2018', '2018 wcq', 'america 2018 wcq']) {
    type(page, q);
    assert.deepEqual(shown(page), ['2018-north-america-wcq'], q);
  }
});

test('where an event was held is searchable', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'chile');
  assert.deepEqual(names(page), ['YCS Santiago']);
});

test('the archive slug is searchable, so old names still find their event', async (t) => {
  // The 2026 qualifier's coverage only ever called it NAWCQ; someone looking
  // for it may well type what the blog used to say.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'north-america-wcq');
  assert.deepEqual(shown(page),
    ['2026-north-america-wcq', '2018-north-america-wcq']);
});

test('a query matching nothing says so rather than showing an empty box', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'atlantis');
  assert.equal(page.$('#event-list').hidden, false);
  assert.match(page.text('#event-list'), /no event matches/i);
});

/* ---- keyboard ---------------------------------------------------------- */

test('arrow keys move through the list', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const at = () => page.$$('#event-list [aria-selected="true"]')[0]?.dataset.slug;
  key(page, 'ArrowDown');
  assert.equal(at(), CATALOG[1].slug);
  key(page, 'ArrowUp');
  assert.equal(at(), CATALOG[0].slug);
});

test('the arrows wrap rather than stopping dead', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const at = () => page.$$('#event-list [aria-selected="true"]')[0]?.dataset.slug;
  key(page, 'ArrowUp');
  assert.equal(at(), CATALOG.at(-1).slug, 'up from the first goes to the last');
});

test('Home and End reach the ends of what is shown', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const at = () => page.$$('#event-list [aria-selected="true"]')[0]?.dataset.slug;
  key(page, 'End');
  assert.equal(at(), CATALOG.at(-1).slug);
  key(page, 'Home');
  assert.equal(at(), CATALOG[0].slug);
});

test('Enter opens the event the keyboard is on', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'anaheim');
  key(page, 'ArrowDown');
  key(page, 'Enter');
  // Settled, not merely started: selectEvent awaits the event's rounds, and a
  // test that ends first leaves it reaching into a closed document.
  await waitFor(page, `activeEvent === '2024-12-ycs-anaheim' && roundsState === 'ready'`);
  await tick(page, 2);
  assert.equal(page.$('#event-list').hidden, true, 'the list stayed open');
});

test('Escape leaves the event on screen alone', async (t) => {
  // A reader who changes their mind should not have to remember which event
  // they were reading.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'anaheim');
  key(page, 'Escape');
  assert.equal(page.get('activeEvent'), CATALOG[0].slug);
  assert.equal(page.$('#event-list').hidden, true);
  assert.equal(page.$('#event-search').value, 'North America WCQ 2026');
});

test('an arrow key opens a closed list rather than doing nothing', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  key(page, 'ArrowDown');
  assert.equal(page.$('#event-list').hidden, false);
});

/* ---- pointer and ARIA -------------------------------------------------- */

test('clicking an event opens it', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  page.$$('#event-list [data-slug]')[2].click();
  await waitFor(page, `activeEvent === '${CATALOG[2].slug}' && roundsState === 'ready'`);
  await tick(page, 2);
  assert.equal(page.$('#event-list').hidden, true);
});

test('clicking the box opens the list', async (t) => {
  // The other tests open it by calling openPicker directly, which is not how a
  // reader reaches it.
  const page = await loadPage(archive());
  t.after(() => page.close());
  assert.equal(page.$('#event-list').hidden, true);
  page.$('#event-search').click();
  assert.equal(page.$('#event-list').hidden, false);
  assert.equal(page.$('#event-search').value, '', 'the query is not pre-filled');
});

test('clicking away closes the list without changing the event', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  page.$('#live-h').click();
  assert.equal(page.$('#event-list').hidden, true);
  assert.equal(page.get('activeEvent'), CATALOG[0].slug);
});

test('the option the keyboard is on is the one announced', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  key(page, 'ArrowDown');
  const active = page.$('#event-search').getAttribute('aria-activedescendant');
  assert.ok(active, 'no option is announced');
  assert.equal(page.document.getElementById(active).getAttribute('aria-selected'), 'true');
});

test('nothing is announced when nothing matches', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'atlantis');
  assert.equal(page.$('#event-search').getAttribute('aria-activedescendant'), null);
});

test('the event on screen is marked in the list', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const here = page.$$('#event-list li.here').map((li) => li.dataset.slug);
  assert.deepEqual(here, [CATALOG[0].slug]);
});

/* ---- grouped by year --------------------------------------------------- */

test('the list is grouped by year', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  assert.deepEqual(
    page.$$('#event-list [role="group"]').map((g) => g.getAttribute('aria-label')),
    ['2026', '2025', '2024', '2018', '2016']);
});

test('a year holds the events held in it', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const groups = page.$$('#event-list [role="group"]').map((g) =>
    [...g.querySelectorAll('[role="option"]')].map((o) => o.dataset.slug));
  assert.deepEqual(groups[0], ['2026-north-america-wcq']);
  assert.deepEqual(groups[1], ['2025-10-ycs-anaheim']);
  assert.deepEqual(groups[2], ['2024-12-ycs-anaheim']);
});

test('two events in one year share a group', async (t) => {
  const twins = [
    { ...SAMPLE, slug: 'a', event: 'YCS One', updated: '2026-08-16' },
    { ...SAMPLE, slug: 'b', event: 'YCS Two', updated: '2026-02-15' },
  ];
  const page = await loadPage({
    routes: {
      'events.json': { status: 200, body: JSON.stringify({ events: twins }) },
      'rounds.json': () => ({ status: 200, body: JSON.stringify(roundsFixture()) }),
    },
  });
  t.after(() => page.close());
  open(page);
  const groups = page.$$('#event-list [role="group"]');
  assert.equal(groups.length, 1);
  assert.equal(groups[0].querySelectorAll('[role="option"]').length, 2);
});

test('the year is announced as the group, not read out beside each event', async (t) => {
  // The visible label is decoration; the group carries the name.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const label = page.$('#event-list .picker__year');
  assert.equal(label.getAttribute('aria-hidden'), 'true');
  assert.equal(label.closest('[role="group"]').getAttribute('aria-label'), '2026');
});

test('the options belong to the group, not to a second listbox', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  for (const inner of page.$$('#event-list ul')) {
    assert.equal(inner.getAttribute('role'), 'presentation', inner.outerHTML.slice(0, 60));
  }
  assert.equal(page.$$('[role="listbox"]').length, 1);
});

test('grouping does not disturb the keyboard order', async (t) => {
  // The keyboard counts options across the whole list; the years are only how
  // it is laid out.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const at = () => page.$$('#event-list [aria-selected="true"]')[0]?.dataset.slug;
  for (const expected of CATALOG.slice(1).map((e) => e.slug)) {
    key(page, 'ArrowDown');
    assert.equal(at(), expected);
  }
});

test('an undated event still has somewhere to sit', async (t) => {
  const page = await loadPage({
    routes: {
      'events.json': {
        status: 200,
        body: JSON.stringify({ events: [CATALOG[0], { ...CATALOG[1], updated: null }] }),
      },
      'rounds.json': () => ({ status: 200, body: JSON.stringify(roundsFixture()) }),
    },
  });
  t.after(() => page.close());
  open(page);
  assert.deepEqual(
    page.$$('#event-list [role="group"]').map((g) => g.getAttribute('aria-label')),
    ['2026', 'Undated']);
});

test('the panel styles do not reach the lists inside it', async (t) => {
  // ".picker ul" matched every list, not just the dropdown, so all thirteen
  // year groups were absolutely positioned at the same spot and stacked on each
  // other. The list showed a column of years with one event under the last.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  const position = (el) => page.window.getComputedStyle(el).position;
  assert.equal(position(page.$('#event-list')), 'absolute',
    'the panel is the thing that floats over the page');
  for (const inner of page.$$('#event-list ul')) {
    assert.notEqual(position(inner), 'absolute',
      'a year group floated out of the list it belongs to');
  }
});

test('a year group is as tall as the events in it', async (t) => {
  // The symptom of the same fault, from the other side: torn out of the flow,
  // a group collapsed to the height of its own label.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  for (const group of page.$$('#event-list [role="group"]')) {
    assert.equal(page.window.getComputedStyle(group.querySelector('ul')).overflowY, '',
      'a year group scrolls independently of the list');
  }
});

/* ---- searching by initials --------------------------------------------- */

test('a qualifier is found by the initials its coverage uses', async (t) => {
  // The blog's own posts call the 2026 event NAWCQ throughout, and neither its
  // name nor its slug contains that word.
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'nawcq');
  assert.deepEqual(shown(page), ['2026-north-america-wcq', '2018-north-america-wcq']);
});

test('the initials keep an abbreviation whole', async (t) => {
  // N + A + WCQ, not N + A + W. The first letter of every word gives "naw",
  // and then the thing people actually type finds nothing.
  const page = await loadPage(archive());
  t.after(() => page.close());
  assert.equal(page.run(`initials('North America WCQ 2026')`), 'nawcq');
  assert.equal(page.run(`initials('TEAM YCS Las Vegas')`), 'teamycslv');
});

test('a year in the name is not an initial', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  assert.equal(page.run(`initials('South America WCQ 2015')`), 'sawcq');
});

test('initials narrow with the year like anything else', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'nawcq 2018');
  assert.deepEqual(shown(page), ['2018-north-america-wcq']);
});

test('an event with no initials worth typing is still found by name', async (t) => {
  const page = await loadPage(archive());
  t.after(() => page.close());
  open(page);
  type(page, 'santiago');
  assert.deepEqual(shown(page), ['201603-santiago-chile']);
});
