/**
 * A Team YCS enters three Duelists a side.
 *
 * The standings rank teams, the pairings pair teams, and the three duels played
 * inside a team match hang off it. The page has no way to tell any of that from
 * the rows — a team match reads exactly like a match — so the data says which
 * it is, and the page follows.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, roundsFixture } from './harness.mjs';

/** The simulation, rewritten as a team event: teams paired, duels beneath. */
function teamRounds() {
  const d = roundsFixture();
  const fmt = d.formats[0];
  d.formats = [{ ...fmt, entrant: 'Team', duelists: 389 }];
  for (const r of d.formats[0].rounds) {
    r.pairings = (r.pairings ?? []).map((p, i) => ({
      table: i * 3 + 1,
      a: `Team ${p.a.split(' ')[0]}`, aRec: p.aRec, aDeck: null,
      b: `Team ${p.b.split(' ')[0]}`, bRec: p.bRec, bDeck: null,
      duels: [
        { table: i * 3 + 1, a: p.a, aDeck: p.aDeck, b: p.b, bDeck: p.bDeck },
        { table: i * 3 + 2, a: 'Second Seat A', aDeck: null, b: 'Second Seat B', bDeck: null },
        { table: i * 3 + 3, a: 'Third Seat A', aDeck: null, b: 'Third Seat B', bDeck: null },
      ],
    }));
    r.standings = (r.standings ?? []).map((s) => ({
      ...s, name: `Team ${s.name.split(' ')[0]}`,
      members: [s.name, 'Someone Else', 'A Third'],
    }));
  }
  return d;
}

const teamEvent = { routes: { 'rounds.json': () => ({ status: 200, body: JSON.stringify(teamRounds()) }) } };

const heads = (page) => page.$$('#round-body thead th').map((t) => t.textContent.trim());
const rows = (page) => page.$$('#round-body tbody tr');

async function paired(t) {
  const page = await loadPage(teamEvent);
  t.after(() => page.close());
  const id = page.json('ROUNDS.filter(r => r.pairings.length).map(r => r.id)')[0];
  page.run(`selectRound('${id}'); activeView='pairings'; renderRound();`);
  return page;
}

test('a team event counts teams, and says so', async (t) => {
  // 389 teams shown as "389 Duelists" is the same number under the wrong noun,
  // and there are 1,167 Duelists behind it.
  const page = await loadPage(teamEvent);
  t.after(() => page.close());
  assert.match(page.text('#hero-meta'), /389 Teams/);
  assert.ok(!page.text('#hero-meta').includes('Duelists'));
});

test('an ordinary event still counts Duelists', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  assert.match(page.text('#hero-meta'), /Duelists/);
});

test('the pairings pair teams', async (t) => {
  const page = await paired(t);
  assert.deepEqual(heads(page).slice(1), ['Team', 'Record', 'Team', 'Record']);
});

test('the duels are rows beneath the match that names the teams', async (t) => {
  // Flattened into nine hundred rows the round would say who duelled and never
  // say who was playing whom.
  const page = await paired(t);
  const kinds = rows(page).slice(0, 4).map((tr) => tr.className);
  assert.deepEqual(kinds, ['match', 'duel', 'duel', 'duel']);
});

test('a duel names the Duelists, not the teams again', async (t) => {
  const page = await paired(t);
  const [match, duel] = rows(page);
  const cell = (tr, i) => tr.children[i].textContent.trim();
  assert.match(cell(match, 1), /^Team /);
  assert.ok(!cell(duel, 1).startsWith('Team '), cell(duel, 1));
  assert.equal(cell(duel, 0), cell(match, 0), 'the first duel is at the match’s table');
});

test('a search for a Duelist finds the team match they played in', async (t) => {
  const page = await paired(t);
  const name = page.$$('#round-body tr.duel')[1].children[1].textContent.trim();
  page.run(`query = ${JSON.stringify(name.toLowerCase())}; renderRound();`);
  const shown = rows(page);
  assert.ok(shown.length, `nothing matched ${name}`);
  assert.equal(shown[0].className, 'match', 'found the seat but lost the match');
  assert.ok(page.text('#round-body').includes(name));
});

test('a search for a team finds it', async (t) => {
  const page = await paired(t);
  const team = rows(page)[0].children[1].textContent.trim();
  page.run(`query = ${JSON.stringify(team.toLowerCase())}; renderRound();`);
  assert.ok(rows(page).length, `nothing matched ${team}`);
});

test('the standings rank teams and name who is on them', async (t) => {
  const page = await loadPage(teamEvent);
  t.after(() => page.close());
  const id = page.json('ROUNDS.filter(r => r.standings.length).map(r => r.id)')[0];
  page.run(`selectRound('${id}'); activeView='standings'; renderRound();`);
  assert.ok(heads(page).includes('Team'), heads(page).join('/'));
  assert.ok(!heads(page).includes('Duelist'), heads(page).join('/'));
  assert.match(rows(page)[0].textContent, /Someone Else/, 'the roster is not shown');
});

test('a search for a team member finds their team', async (t) => {
  const page = await loadPage(teamEvent);
  t.after(() => page.close());
  const id = page.json('ROUNDS.filter(r => r.standings.length).map(r => r.id)')[0];
  page.run(`selectRound('${id}'); activeView='standings'; renderRound();`);
  page.run(`query = 'someone else'; renderRound();`);
  assert.ok(rows(page).length, 'a Duelist cannot find themselves in the standings');
});

test('a singles event renders exactly as it did', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  const id = page.json('ROUNDS.filter(r => r.pairings.length).map(r => r.id)')[0];
  page.run(`selectRound('${id}'); activeView='pairings'; renderRound();`);
  assert.ok(heads(page).includes('Duelist'), heads(page).join('/'));
  assert.ok(!heads(page).includes('Team'), heads(page).join('/'));
  assert.equal(page.$$('#round-body tr.match').length, 0);
  assert.equal(page.$$('#round-body tr.duel').length, 0);
});
