/**
 * The winners page.
 *
 * One list of every event the coverage names a winner for, built from the
 * manifest alone -- the champions are in it precisely so this page does not
 * have to fetch a hundred and forty round files to read one name out of each.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

/* The winners page has one load and its own globals, so it says when it is
   done rather than being asked about the coverage page's two. */
const BOOTED = "document.getElementById('wcount').textContent !== 'Loading'";

const manifest = (events) => ({
  page: 'winners/index.html',
  settleOn: BOOTED,
  routes: { 'events.json': { status: 200, body: JSON.stringify({ events }) } },
});

const EVENTS = [
  { slug: 'a', event: 'YCS Montréal', updated: '2026-08-16', location: 'Montréal, Canada',
    path: 'events/a/rounds.json',
    champions: [{ format: 'Advanced', name: 'Ada Lovelace', deck: 'Elfnote' }] },
  { slug: 'b', event: 'YCS Columbus', updated: '2026-05-23', path: 'events/b/rounds.json',
    champions: [{ format: 'Advanced', name: 'Ada Lovelace', deck: 'Branded' },
                { format: 'Genesys', name: 'Bo Peep', deck: null }] },
  { slug: 'c', event: 'North America WCQ 2026', updated: '2026-07-12',
    path: 'events/c/rounds.json',
    champions: [{ format: null, name: 'Carla Gamma', deck: 'Ryzeal' }] },
  { slug: 'd', event: 'YCS Nowhere', updated: '2026-01-01', path: 'events/d/rounds.json' },
];

const rows = (page) => page.$$('.win');
const names = (page) => rows(page).map((n) => n.querySelector('.win__n').textContent.trim());

test('every winner in the archive is listed, newest first', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  assert.deepEqual(names(page), ['Ada Lovelace', 'Carla Gamma', 'Ada Lovelace', 'Bo Peep']);
  assert.match(page.text('#wcount'), /4 winners/);
});

test('an event with no winner on record is not a row', async (t) => {
  // Most of the archive: 32 winners across 143 events. A row saying nothing
  // would be worse than no row.
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  assert.ok(!page.text('#winners').includes('YCS Nowhere'));
});

test('a two-format event contributes both of its winners', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  const columbus = rows(page).filter((r) =>
    r.querySelector('.win__e').textContent.includes('Columbus'));
  assert.equal(columbus.length, 2);
  assert.deepEqual(columbus.map((r) => r.querySelector('.win__f').textContent),
    ['Advanced', 'Genesys']);
});

test('an event that names no format says nothing rather than inventing one', async (t) => {
  // The North America WCQ titles every post "North America WCQ: Round 10
  // Pairings". That is one tournament with no format name, not a missing one.
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  const wcq = rows(page).find((r) => r.querySelector('.win__e').textContent.includes('WCQ'));
  assert.equal(wcq.querySelector('.win__f'), null);
});

test('a repeat winner is marked as one', async (t) => {
  // The same names come back, and a list that did not say so would be hiding
  // the most interesting thing in it.
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  const ada = rows(page).filter((r) => r.querySelector('.win__n').textContent === 'Ada Lovelace');
  assert.equal(ada.length, 2);
  for (const r of ada) assert.match(r.querySelector('.win__x').textContent, /2/);
  const bo = rows(page).find((r) => r.querySelector('.win__n').textContent === 'Bo Peep');
  assert.equal(bo.querySelector('.win__x'), null, 'and a one-time winner is not');
});

test('a winner with no deck published is still listed', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  const bo = rows(page).find((r) => r.querySelector('.win__n').textContent === 'Bo Peep');
  assert.equal(bo.querySelector('.win__d'), null, 'and shows no empty label');
});

test('each row links to the event on the coverage page', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  assert.equal(rows(page)[0].querySelector('.win__e').getAttribute('href'), '/?event=a');
});

test('search covers the winner, the event and the deck', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  const search = (v) => {
    page.$('#q').value = v;
    page.run(`query = ${JSON.stringify(v.toLowerCase())}; render();`);
  };
  search('elfnote');
  assert.deepEqual(names(page), ['Ada Lovelace']);
  search('columbus');
  assert.equal(rows(page).length, 2);
  search('carla');
  assert.deepEqual(names(page), ['Carla Gamma']);
  assert.match(page.text('#wcount'), /1 winner of 4/, 'and says what it is a subset of');
});

test('a search matching nothing says so', async (t) => {
  const page = await loadPage(manifest(EVENTS));
  t.after(() => page.close());
  page.run(`query = 'nobody at all'; render();`);
  assert.equal(rows(page).length, 0);
  assert.match(page.text('#wcount'), /No matches/);
});

test('an archive with no winners yet says that, not nothing', async (t) => {
  const page = await loadPage(manifest([EVENTS[3]]));
  t.after(() => page.close());
  assert.match(page.text('#winners'), /No winners on record/);
});

test('a manifest that will not load is reported, not blank', async (t) => {
  const page = await loadPage({
    page: 'winners/index.html',
    settleOn: BOOTED,
    routes: { 'events.json': { status: 500 } },
  });
  t.after(() => page.close());
  assert.match(page.text('#winners'), /could not be loaded/);
  assert.match(page.text('#wcount'), /Unavailable/);
});

test('a name out of the data is escaped', async (t) => {
  const page = await loadPage(manifest([{
    slug: 'x', event: 'YCS Test', updated: '2026-01-01', path: 'events/x/rounds.json',
    champions: [{ format: null, name: '<img src=x onerror=alert(1)>', deck: null }],
  }]));
  t.after(() => page.close());
  assert.equal(page.$('#winners img'), null);
  assert.match(page.text('#winners'), /onerror/);
});
