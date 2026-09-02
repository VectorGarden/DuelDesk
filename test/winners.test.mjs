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

/* ── A team champion's roster ───────────────────────────────────────────── */

const TEAMS = [
  { slug: 't1', event: 'TEAM YCS São Paulo', updated: '2023-09-04',
    path: 'events/t1/rounds.json',
    champions: [{ format: null, name: 'Better Have It', deck: null, members: [
      { name: 'Ruben Andres Penaranda', deck: 'Bystial Dragon Link' },
      { name: 'Repeat Winner', deck: 'Purrely' }] }] },
  { slug: 't2', event: 'TEAM YCS Las Vegas', updated: '2024-02-28',
    path: 'events/t2/rounds.json',
    champions: [{ format: null, name: 'Ares', deck: null, members: [
      { name: 'Repeat Winner', deck: 'Maliss' }] }] },
  { slug: 's1', event: 'YCS Montréal', updated: '2026-08-16', path: 'events/s1/rounds.json',
    champions: [{ format: null, name: 'Ada Lovelace', deck: 'Elfnote' }] },
];

test('a team row expands its roster in place', async (t) => {
  // Three names, and the row they belong to is right there. A dialog would
  // cover the list the reader is reading to show them less than the row
  // already implies.
  const page = await loadPage(manifest(TEAMS));
  t.after(() => page.close());
  assert.equal(page.$$('[data-roster]').length, 2, 'a roster button per team row');
  assert.equal(page.get('document.querySelector(".win__roster").hidden'), true,
    'the roster is showing before it was asked for');
  page.run(`document.querySelector('[data-roster]').click()`);
  assert.equal(page.get('document.querySelector(".win__roster").hidden'), false);
  assert.equal(page.get(`document.querySelector('[data-roster]').getAttribute('aria-expanded')`),
    'true');
});

test('a singles row has no roster to expand', async (t) => {
  const page = await loadPage(manifest([TEAMS[2]]));
  t.after(() => page.close());
  assert.equal(page.$$('[data-roster]').length, 0);
  assert.equal(page.$$('.win__roster').length, 0);
});

test('a Duelist counts the events they won on a team', async (t) => {
  // A team's title belongs to its Duelists as much as to the name they
  // entered under. Counted by the team name alone, a Duelist who has won
  // twice on two different teams reads as having won nothing twice.
  const page = await loadPage(manifest(TEAMS));
  t.after(() => page.close());
  page.run(`document.querySelectorAll('[data-roster]').forEach(b => b.click())`);
  const badge = (name) => page.$$('.win__roster li')
    .filter((li) => li.querySelector('.roster__n').textContent.trim() === name)
    .map((li) => li.querySelector('.win__x')?.textContent.trim() ?? null);
  assert.deepEqual(badge('Repeat Winner'), ['2\u00d7', '2\u00d7'],
    'two team titles for one Duelist are not counted');
  assert.deepEqual(badge('Ruben Andres Penaranda'), [null],
    'a single win should carry no badge');
});

test('a Duelist\'s own row counts the events they won on a team', async (t) => {
  // Jesse Dean Kotton has won four events alone and two on teams. His own rows
  // said four while his name inside a roster said six -- the same Duelist,
  // two numbers, on one page.
  const page = await loadPage(manifest([...TEAMS,
    { slug: 's2', event: 'YCS Utrecht', updated: '2026-01-10',
      path: 'events/s2/rounds.json',
      champions: [{ format: null, name: 'Repeat Winner', deck: 'Ryzeal' }] }]));
  t.after(() => page.close());
  const solo = rows(page).find((r) => r.querySelector('.win__n').textContent === 'Repeat Winner');
  // Scoped to the row's own heading: a roster's badges are inside the row too.
  assert.equal(solo.querySelector('.win__who .win__x').textContent.trim(), '3\u00d7',
    'one win alone and two on teams is three, on the row and in the roster alike');
});

test('a team is still counted by the name it entered under', async (t) => {
  // The Duelists' totals must not be handed to the team: Ares won once.
  const page = await loadPage(manifest(TEAMS));
  t.after(() => page.close());
  const ares = rows(page).find((r) => r.querySelector('.win__n').textContent === 'Ares');
  assert.equal(ares.querySelector('.win__who .win__x'), null);
});

test('an expanded roster does not push the event and date out of place', async (t) => {
  // The winners row is a flex line with space-between. A roster that does not
  // claim a row of its own becomes a third column, and the event and its date
  // land in the middle of the row instead of against the right margin.
  const page = await loadPage(manifest(TEAMS));
  t.after(() => page.close());
  const basis = page.get(`(() => {
    const ul = document.querySelector('.win__roster');
    const cs = getComputedStyle(ul);
    return cs.flexBasis || cs.getPropertyValue('flex-basis');
  })()`);
  assert.equal(basis, '100%', 'the roster takes a full row under its team');
});

test('an open roster survives a search that keeps its row', async (t) => {
  const page = await loadPage(manifest(TEAMS));
  t.after(() => page.close());
  // The row that will survive the search, not whichever is first: the list is
  // newest first, so the first roster belongs to a different team.
  page.run(`[...document.querySelectorAll('.win')]
              .find(w => w.querySelector('.win__n').textContent.includes('Better Have It'))
              .querySelector('[data-roster]').click()`);
  // Through the search box, as a reader would: the page owns `query`, and
  // setting it from outside does not reach the binding the script closed over.
  page.run(`const q = document.getElementById('q');
            q.value = 'better'; q.dispatchEvent(new Event('input'));`);
  await new Promise((r) => setTimeout(r, 400));
  assert.equal(page.$$('.win').length, 1, 'the search should leave the team row on screen');
  assert.equal(page.get('document.querySelector("[data-roster]").getAttribute("aria-expanded")'),
    'true', 'the button says it is collapsed');
  assert.equal(page.get('document.querySelector(".win__roster").hidden'), false,
    'the roster folded itself up on a re-render');
});

/* ── One Duelist, two spellings ──────────────────────────────────────────── */

/* The blog is not consistent about a middle initial across events, so the
   manifest says which rows are the same Duelist. The row still shows the name
   the event that crowned them published. */
const SPELLINGS = [
  { slug: 'v', event: 'YCS Vancouver', updated: '2025-09-11', path: 'events/v/rounds.json',
    champions: [{ format: null, name: 'Steven J. Trifunoski', deck: 'Ryzeal' }] },
  { slug: 'an', event: 'YCS Anaheim', updated: '2024-12-07', path: 'events/an/rounds.json',
    champions: [{ format: null, name: 'Steven Trifunoski', deck: 'Snake-Eye',
                  person: 'Steven J. Trifunoski' }] },
];

test('a Duelist written two ways is counted once', async (t) => {
  const page = await loadPage(manifest(SPELLINGS));
  t.after(() => page.close());
  const badges = rows(page).map((r) => r.querySelector('.win__who .win__x')?.textContent.trim());
  assert.deepEqual(badges, ['2\u00d7', '2\u00d7'],
    'two titles for one Duelist read as one title each');
});

test('and still listed under the name its event published', async (t) => {
  // What each event printed is what it printed; the manifest says who is who
  // without rewriting either row.
  const page = await loadPage(manifest(SPELLINGS));
  t.after(() => page.close());
  assert.deepEqual(names(page), ['Steven J. Trifunoski', 'Steven Trifunoski']);
});

test('and found under either spelling', async (t) => {
  const page = await loadPage(manifest(SPELLINGS));
  t.after(() => page.close());
  for (const q of ['Steven J. Trifunoski', 'steven trifunoski']){
    page.run(`query = ${JSON.stringify(q.toLowerCase())}; render();`);
    assert.equal(rows(page).length, 2, `searching ${JSON.stringify(q)} found one row, not both`);
  }
});
