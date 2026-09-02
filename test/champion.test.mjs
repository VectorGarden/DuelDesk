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

/* One event, two tournaments. Each crowns its own Duelist, so a reveal that
   did not name its format would hand over the other one's ending. */
function twoFormats() {
  const d = roundsFixture();
  const base = d.formats[0];
  const crown = (name, who) => {
    const rounds = base.rounds.map((r) => ({ ...r }));
    rounds[rounds.length - 1] = { ...rounds[rounds.length - 1],
      pairings: [{ table: 1, a: who, aDeck: 'Elfnote', b: 'Bo Peep', bDeck: 'Kewl Tune' }] };
    return { ...base, format: name, champion: who, rounds };
  };
  d.formats = [crown('Advanced', 'Ada Lovelace'), crown('Genesys', 'Grace Hopper')];
  return d;
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

test('a champion revealed in one format is not revealed in the other', async (t) => {
  // Each format is its own tournament with its own champion, so switching
  // between them is switching tournaments -- the same spoiler as switching
  // events, inside one event.
  const page = await loadPage({ routes: {
    'rounds.json': { status: 200, body: JSON.stringify(twoFormats()) },
    'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
  } });
  t.after(() => page.close());
  page.run(`selectFormat('Advanced'); selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  assert.match(champ(page).textContent, /Ada Lovelace/);

  page.run(`selectFormat('Genesys'); selectRound(ROUNDS[ROUNDS.length-1].id)`);
  assert.doesNotMatch(champ(page).textContent, /Grace Hopper/,
    "the other tournament's champion was given away without being asked for");
  assert.match(champ(page).textContent, /Reveal/);
});

/* ── The crown, where the tables name the champion ───────────────────────── */

/** The simulation with a champion who is traceable: a record somewhere says
 *  the builder knew which Duelist of that name it meant. */
function crowned({ derived = true } = {}) {
  const d = roundsFixture();
  const f = d.formats[0];
  const last = f.rounds[f.rounds.length - 1];
  last.pairings = [{ table: 1, a: 'Ada Lovelace', aDeck: 'Elfnote',
                     aRec: derived ? { wins: 3, losses: 0, draws: 0, confidence: 'derived' } : null,
                     b: 'Bo Peep', bDeck: 'Kewl Tune', bRec: null }];
  // Played, or the panel says the round has not started and renders no table
  // for the crown to sit in.
  last.state = 'done';
  f.champion = 'Ada Lovelace';
  return d;
}

const page4 = (mutate) => loadPage({ routes: {
  'rounds.json': { status: 200, body: JSON.stringify(mutate ?? crowned()) },
  'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
} });

const crowns = (page) => page.$$('#round-body .crown').length;

test('no crown until the champion has been revealed', async (t) => {
  // The rounds above are worth reading first, and a crown in the pairings
  // gives the ending away as plainly as printing the name would.
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  assert.equal(crowns(page), 0);
});

test('and one on the champion once it has', async (t) => {
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  assert.ok(crowns(page) > 0, 'the champion is named in the round and not marked');
});

test('the crown says what it means, not just how it looks', async (t) => {
  // Colour and shape are never the only signal: the glyph is hidden from
  // assistive technology and the word it stands for is read instead.
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  const el = page.$('#round-body .crown');
  assert.match(el.textContent, /champion/);
  assert.equal(el.querySelector('[aria-hidden="true"]').getAttribute('aria-hidden'), 'true');
});

test('nobody is crowned when the builder could not tell the name apart', async (t) => {
  // Two Duelists share a name more often than a bracket is wrong. The builder
  // refuses to derive a record for a name it cannot separate, so a champion
  // with no record anywhere is one this cannot safely point at -- crowning by
  // name alone would crown whichever of them lost.
  const page = await page4(crowned({ derived: false }));
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  assert.equal(crowns(page), 0);
});

test('the runner-up is not crowned', async (t) => {
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  const cells = page.$$('#round-body td').filter((td) => /Bo Peep/.test(td.textContent));
  assert.ok(cells.length, 'the runner-up is in the table');
  for (const td of cells) assert.equal(td.querySelector('.crown'), null);
});
