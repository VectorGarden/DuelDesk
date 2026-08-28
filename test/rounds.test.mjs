import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

const body = (page) => page.text('#round-body');
const select = (page, id) => { page.run(`selectRound('${id}')`); return body(page); };
const view = (page, v) => page.$(`[data-view="${v}"]`).click();

test('every round renders its own data', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const r1 = select(page, '1'), r5 = select(page, '5'), r12 = select(page, '12');
  assert.notEqual(r1, r12, 'R1 and R12 must not be identical');
  assert.notEqual(r5, r1);
  assert.notEqual(r5, r12);
  assert.match(r1, /0–0–0/, 'round 1 pairs players on 0–0–0 entering records');
  assert.doesNotMatch(r1, /9–2–0|10–1–0/, 'nobody has nine wins in round one');
});

test('standings records match the number of rounds actually played', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  view(page, 'standings');

  for (const id of ['3', '7', '11']) {
    page.run(`selectRound('${id}')`);
    const after = page.run(`roundOf('${id}').standingsAfter`);
    const recs = page.$$('#round-body .rec').map((n) => n.textContent).filter((s) => s.includes('–'));
    assert.ok(recs.length > 0, `round ${id} shows standings`);
    for (const rec of recs) {
      const [w, l] = rec.split('–').map(Number);
      assert.equal(w + l, after, `round ${id}: ${rec} should total ${after} matches`);
    }
    assert.match(page.text('#round-body caption'), new RegExp(`after round ${after}`));
  }
});

test('the live round shows standings that already exist, never its own', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const live = page.json(`ROUNDS.find(r => r.state === 'live')`);
  const swissRounds = page.get('eventInfo.swissRounds');
  assert.ok(live, 'the data marks a round live');

  if (live.phase === 'Swiss') {
    assert.equal(live.standingsAfter, Number(live.id) - 1,
      'its results do not exist yet, so standings come from the round before');
  } else {
    assert.equal(live.standingsAfter, swissRounds,
      'in the cut, Swiss is over and the standings are final');
  }
});

test('feature match differs by round and degrades when absent', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  view(page, 'feature');
  assert.notEqual(select(page, '6'), select(page, '12'));

  page.run(`ROUNDS.find(r => r.id === '6').feature = null`);
  page.run(`selectRound('6')`);
  assert.match(body(page), /No feature match/, 'a round without one says so');
});

test('rounds that have not started carry and show nothing', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const upcoming = page.json(`ROUNDS.filter(r => r.state === 'upcoming').map(r => r.id)`);
  assert.ok(upcoming.length > 0, 'the data still has at least one round ahead');

  for (const id of upcoming) {
    assert.match(select(page, id), /has not started/);
    assert.equal(page.run(`roundOf('${id}').pairings.length`), 0);
    assert.equal(page.run(`roundOf('${id}').standings.length`), 0);
    assert.ok(page.$$('[data-view]').every((b) => b.disabled),
      `${id}: the view control is disabled`);
  }
});

test('the current round comes from the data, not a hardcoded id', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.get('activeRound'), page.run(`ROUNDS.find(r => r.state === 'live').id`));

  // Mark a different round live and the page should land there instead.
  const moved = await loadPage({
    routes: {
      'rounds.json': async ({ calls }) => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../rounds.json', import.meta.url), 'utf8'));
        d.rounds.forEach((r) => { if (r.state === 'live') r.state = 'done'; });
        const r7 = d.rounds.find((r) => r.id === '7');
        r7.state = 'live';
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => moved.close());
  assert.equal(moved.get('activeRound'), '7', 'landed on whichever round the data marks live');
});

test('the hero is populated from the event data', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.text('#live-h'), page.get('eventInfo.event'));
  assert.match(page.text('#hero-meta'), /Duelists/);
  assert.match(page.text('#hero-meta'), /Swiss rounds/);
  const phase = page.run(`roundOf(activeRound).phase`);
  assert.match(page.text('#round-sub'), new RegExp(phase),
    'the subtitle names the phase the round actually belongs to');
});

test('the top cut is seeded from the final Swiss standings', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const swiss = page.get('eventInfo.swissRounds');
  const finalStandings = page.json(`roundOf('${'' + 12}').standings.map(s => s.name)`);
  const t8 = page.json(`roundOf('T8')`);
  assert.equal(t8.standingsAfter, swiss, 'the cut shows the final Swiss standings');

  const field = t8.pairings.flatMap((p) => [p.a, p.b]);
  assert.deepEqual([...field].sort(), [...finalStandings].sort(),
    'the Top 8 field is exactly the top eight of the final standings');

  // Standard single elimination: 1v8, 2v7, 3v6, 4v5.
  assert.deepEqual(t8.pairings.map((p) => [p.a, p.b]), [
    [finalStandings[0], finalStandings[7]],
    [finalStandings[1], finalStandings[6]],
    [finalStandings[2], finalStandings[5]],
    [finalStandings[3], finalStandings[4]],
  ]);
});

test('the Top 4 is drawn from Top 8 competitors and is bracket-correct', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const t8 = page.json(`roundOf('T8')`);
  const t4 = page.json(`roundOf('T4')`);

  const t8Field = new Set(t8.pairings.flatMap((p) => [p.a, p.b]));
  const t4Field = t4.pairings.flatMap((p) => [p.a, p.b]);
  assert.equal(t4Field.length, 4, 'two matches, four Duelists');
  assert.equal(new Set(t4Field).size, 4, 'all distinct');
  assert.ok(t4Field.every((n) => t8Field.has(n)), 'everyone came through the Top 8');
  assert.ok(t4.pairings.every((p) => p.a !== p.b));
});

test('cut records are Swiss records, not invented cut ones', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const swiss = page.get('eventInfo.swissRounds');

  for (const id of ['T8', 'T4']) {
    for (const p of page.json(`roundOf('${id}').pairings`)) {
      for (const rec of [p.aRec, p.bRec]) {
        const [w, l] = rec.split('–').map(Number);
        assert.equal(w + l, swiss,
          `${id}: ${rec} should be the ${swiss}-round Swiss record`);
      }
    }
  }
});

test('the Final is genuinely unknown until the Top 4 is played', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const fin = page.json(`roundOf('F')`);
  assert.equal(fin.state, 'upcoming');
  assert.equal(fin.pairings.length, 0, 'its competitors do not exist yet');
  assert.match(select(page, 'F'), /has not started/);
});

test('the cut is presented as a bracket, not as Swiss tables', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  page.run(`selectRound('T8')`);
  page.$('[data-view="pairings"]').click();
  assert.match(page.text('#round-body caption'), /bracket/i,
    'the caption says bracket, not "top tables"');
  assert.match(page.text('#round-body thead'), /Match/,
    'the column is a match number, not a table number');
  assert.match(page.text('#round-sub'), /Top cut/, 'the subtitle names the phase');
  assert.doesNotMatch(page.text('#round-sub'), /Swiss/, 'and does not call it Swiss');

  // The count only appears while a round is live, so check the live cut round.
  page.run(`selectRound('T4')`);
  assert.match(page.text('#round-sub'), /Top cut · \d+ matches?\b/,
    'a cut is counted in matches, not tables');
  assert.doesNotMatch(page.text('#round-sub'), /\btables?\b/);
  page.run(`selectRound('T8')`);

  page.$('[data-view="standings"]').click();
  assert.match(page.text('#round-body caption'), /Final Swiss standings/,
    'standings are labelled final, so they do not look like they still move');
});

test('Swiss rounds keep their own presentation', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('7')`);
  page.$('[data-view="pairings"]').click();
  assert.match(page.text('#round-body caption'), /Top tables/);
  assert.match(page.text('#round-body thead'), /Table/);
  assert.match(page.text('#round-sub'), /Swiss/);
  assert.doesNotMatch(page.text('#round-sub'), /Top cut/);

});

test('every round declares which phase it belongs to', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const r of page.json('ROUNDS')) {
    assert.ok(['Swiss', 'Top cut'].includes(r.phase), `${r.label} has no valid phase`);
  }
  const cut = page.json(`ROUNDS.filter(r => r.phase === 'Top cut').map(r => r.label)`);
  assert.deepEqual(cut, ['Top 8', 'Top 4', 'Final']);
});

test('the page opens on the live cut round', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.get('activeRound'), 'T4', 'lands on whatever is in progress');
  assert.ok(page.$('#round-body tbody'), 'and renders its bracket immediately');
});

test('a live Swiss round is counted in tables, not matches', async (t) => {
  // The shipped data has no live Swiss round any more -- the event has reached
  // the cut -- so construct one rather than leave that branch untested.
  const page = await loadPage({
    routes: {
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../rounds.json', import.meta.url), 'utf8'));
        d.rounds.forEach((r) => { if (r.state === 'live') r.state = 'upcoming'; });
        const r9 = d.rounds.find((r) => r.id === '9');
        r9.state = 'live';
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());

  assert.equal(page.get('activeRound'), '9', 'landed on the live Swiss round');
  assert.match(page.text('#round-sub'), /Swiss · \d+ tables\b/,
    'Swiss is counted in tables');
  assert.doesNotMatch(page.text('#round-sub'), /\bmatches\b/);
});
