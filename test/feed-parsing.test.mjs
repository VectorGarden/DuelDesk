import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, fixture } from './harness.mjs';

const classify = (page, title) => page.run(`classify(${JSON.stringify(title)})`);

test('round slot is found regardless of word order', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const [title, round] of [
    ['Pairings for Round 11', 11],
    ['Round 11 Pairings', 11],
    ['R11 pairings', 11],
    ['Pairings for Top 8', 'Top 8'],
    ['Quarterfinal pairings', 'Top 8'],
    ['Semi-final feature match', 'Top 4'],
    ['The final match', 'Final'],
  ]) {
    assert.deepEqual(classify(page, title).round, round, title);
  }
});

test('coverage type checks structural markers before the looser deck match', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const [title, kind] of [
    ['Pairings for Top 8', 'pairings'],
    ['Top 8 Decklists', 'deck'],
    ['The eight decks still in contention', 'deck'],
    ['Deck profile: Snake-Eye', 'deck'],
    ['Standings after round 10', 'standings'],
    ['Point totals after the circuit', 'standings'],
    ['Feature match: Maliss against Ryzeal', 'feature'],
    ['Your champion, undefeated in the top cut', 'result'],
    ['Deck check penalty issued', 'news'],       // policy term, not deck content
    ['What the top tables were playing', 'news'], // no keyword: fall back, do not guess
  ]) {
    assert.equal(classify(page, title).kind, kind, title);
  }
});

test('a leading coverage label is not mistaken for an event name', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.run(`eventNameFrom('Feature Match: A vs B', 'FALLBACK')`), 'FALLBACK');
  assert.equal(page.run(`eventNameFrom('Round 3: pairings', 'FALLBACK')`), 'FALLBACK');
  assert.equal(page.run(`eventNameFrom('YCS Montreal: Round 3 pairings', 'FALLBACK')`), 'YCS Montreal');
  assert.equal(page.run(`eventNameFrom('No colon here', 'FALLBACK')`), 'FALLBACK');
});

test('the shipped feed round-trips through the parser', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.run(`groupFeed(${JSON.stringify(fixture('feed.xml'))})`);

  assert.equal(groups.length, 4, 'four events reassembled from a flat post stream');
  assert.ok(!groups.some((g) => /^(feature|final) match$/i.test(g.event)), 'no bogus label-event');
  assert.ok(!groups.some((g) => g.event === 'Unsorted coverage'));
  assert.ok(groups[0].date >= groups[1].date, 'newest event first');
  assert.ok(groups.flatMap((g) => g.posts).every((p) => p.time), 'every post has a time');
});

test('malformed and partial feeds are handled, not crashed on', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.throws(() => page.run(`groupFeed('not xml <<<')`), /valid XML/);
  const sparse = page.run(
    `groupFeed('<rss><channel><item><title>only a title</title></item></channel></rss>')`);
  assert.equal(sparse.length, 1, 'an item missing every optional field still groups');
  const titleless = page.run(
    `groupFeed('<rss><channel><item><link>x</link></item></channel></rss>')`);
  assert.equal(titleless.length, 0, 'an item with no title is skipped');
});
