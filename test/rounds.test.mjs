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

test('the live round shows standings from the previous round', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const live = page.run(`ROUNDS.find(r => r.state === 'live')`);
  assert.ok(live, 'the data marks a round live');
  assert.equal(live.standingsAfter, Number(live.id) - 1,
    'its results do not exist yet, so standings come from the round before');
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
  for (const id of ['T8', 'T4', 'F']) {
    assert.match(select(page, id), /has not started/);
    assert.equal(page.run(`roundOf('${id}').pairings.length`), 0);
  }
  assert.ok(page.$$('[data-view]').every((b) => b.disabled), 'the view control is disabled');
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
  assert.match(page.text('#round-sub'), /Swiss|Complete/);
});
