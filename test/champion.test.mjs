/**
 * The champion reveal.
 *
 * Who won is a fact about the end of a tournament, so it is shown on the last
 * round the event published and nowhere else -- and hidden until asked for,
 * because the rounds above it are worth reading first and a result printed
 * beside them takes that away from anyone following the bracket down.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, roundsFixture } from './harness.mjs';

/** The simulation, with a champion and a deck on the final. */
function withChampion(mutate = () => {}) {
  return {
    routes: {
      'rounds.json': async () => {
        const d = roundsFixture();
        const f = d.formats[0];
        const last = f.rounds[f.rounds.length - 1];
        last.pairings = [{ table: 1, a: 'Ada Lovelace', aDeck: 'Elfnote',
                           b: 'Bo Peep', bDeck: 'Kewl Tune' }];
        f.champion = 'Ada Lovelace';
        mutate(d);
        return { status: 200, body: JSON.stringify(d) };
      },
      'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
    },
  };
}

const champ = (page) => page.$('#champion');
const deepest = (page) => page.json('ROUNDS[ROUNDS.length-1].id');

test('the reveal sits on the last round the event published', async (t) => {
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  assert.equal(champ(page).hidden, false);
  assert.match(champ(page).textContent, /Champion/);
});

test('and on no other round', async (t) => {
  // A reader arrives at the last round having already seen the bracket. On
  // round three they have not, and this would be telling them how it ends.
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  const earlier = page.json('ROUNDS[0].id');
  page.run(`selectRound(${JSON.stringify(earlier)})`);
  assert.equal(champ(page).hidden, true);
  assert.equal(champ(page).textContent, '');
});

test('the name is not there until it is asked for', async (t) => {
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  assert.doesNotMatch(champ(page).textContent, /Ada Lovelace/,
    'not merely hidden with CSS: not in the document');
  assert.equal(champ(page).querySelector('[data-champ]').getAttribute('aria-expanded'), 'false');
});

test('revealing shows who won and what they won with', async (t) => {
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  champ(page).querySelector('[data-champ]').click();
  assert.match(champ(page).textContent, /Ada Lovelace/);
  assert.match(champ(page).textContent, /Elfnote/, "the winner's deck, not the loser's");
  assert.doesNotMatch(champ(page).textContent, /Kewl Tune/);
  assert.equal(champ(page).querySelector('[data-champ]').getAttribute('aria-expanded'), 'true');
});

test('and it can be put back', async (t) => {
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  const button = () => champ(page).querySelector('[data-champ]');
  button().click();
  button().click();
  assert.doesNotMatch(champ(page).textContent, /Ada Lovelace/);
});

test('the keyboard does not lose its place on the toggle', async (t) => {
  // The row is rewritten to reveal, so the button the reader just pressed is a
  // different element afterwards. Without this they are returned to the top.
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  champ(page).querySelector('[data-champ]').click();
  assert.equal(page.window.document.activeElement,
               champ(page).querySelector('[data-champ]'));
});

test('an event nobody has a champion for shows nothing', async (t) => {
  // Most of them: 32 of 143 events have one. The row is absent rather than
  // present and empty.
  const page = await loadPage(withChampion((d) => { d.formats[0].champion = null; }));
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  assert.equal(champ(page).hidden, true);
});

test('a champion with no deck published is still shown', async (t) => {
  // Deck types are published for the cut and not always even then.
  const page = await loadPage(withChampion((d) => {
    const f = d.formats[0];
    delete f.rounds[f.rounds.length - 1].pairings[0].aDeck;
  }));
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  champ(page).querySelector('[data-champ]').click();
  assert.match(champ(page).textContent, /Ada Lovelace/);
  assert.equal(champ(page).querySelector('.champ__d'), null, 'and no empty label');
});

test('a champion is escaped like anything else from the data', async (t) => {
  const page = await loadPage(withChampion((d) => {
    const f = d.formats[0];
    f.champion = '<img src=x onerror=alert(1)>';
    f.rounds[f.rounds.length - 1].pairings[0].a = '<img src=x onerror=alert(1)>';
  }));
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  champ(page).querySelector('[data-champ]').click();
  assert.equal(champ(page).querySelector('img'), null);
  assert.match(champ(page).textContent, /onerror/, 'shown as the text it is');
});
