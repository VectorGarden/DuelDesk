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

test('the revealed champion is a link to their page', async (t) => {
  /* Every Duelist has a page, and the one the whole tournament was about was
     the one name on the round track that did not go anywhere. */
  const page = await loadPage(withChampion());
  t.after(() => page.close());
  page.run(`selectRound(${JSON.stringify(deepest(page))})`);
  champ(page).querySelector('[data-champ]').click();
  const link = champ(page).querySelector('.champ__n a.who');
  assert.ok(link, 'the champion is a link');
  assert.equal(link.textContent, 'Ada Lovelace');
  assert.match(link.getAttribute('href'), /^\/player\/\?name=Ada%20Lovelace$/);
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

const crowns = (page) => page.$$('#round-body .place').length;

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

test('the mark says what it means, not just how it looks', async (t) => {
  // Colour and shape are never the only signal, so the mark is the word
  // itself. Nothing here needs an accessible name bolted on beside a glyph.
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  const el = page.$('#round-body .place');
  assert.match(el.textContent.trim(), /^champion$/i,
    'the badge has to read as a word, not as a picture of one');
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

test('a Duelist the builder could not place carries no badge', async (t) => {
  const page = await page4();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS[ROUNDS.length-1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  const cells = page.$$('#round-body td').filter((td) => /Bo Peep/.test(td.textContent));
  assert.ok(cells.length, 'the runner-up is in the table');
  for (const td of cells) assert.equal(td.querySelector('.place'), null);
});

/* ── How far everybody else got ──────────────────────────────────────────── */

const rec = (w) => ({ wins: w, losses: 0, draws: 0, confidence: 'derived' });

/** A cut the coverage published in full: a Top 4 and the final it led to. */
function placed({ withFinal = true } = {}) {
  const d = roundsFixture();
  const f = d.formats[0];
  const at = (label) => f.rounds.find((r) => r.label === label);
  const t4 = at('Top 4');
  t4.state = 'done';
  t4.pairings = [
    { table: 1, a: 'Ada Lovelace', aRec: rec(3), b: 'Cid Vega', bRec: rec(2) },
    { table: 2, a: 'Bo Peep', aRec: rec(3), b: 'Dee Marsh', bRec: rec(2) },
  ];
  const fin = at('Final');
  fin.state = 'done';
  fin.pairings = withFinal
    ? [{ table: 1, a: 'Ada Lovelace', aRec: rec(4), b: 'Bo Peep', bRec: rec(3) }]
    : [];
  f.champion = 'Ada Lovelace';
  return d;
}

const openAt = async (t, data, label) => {
  const page = await loadPage({ routes: {
    'rounds.json': { status: 200, body: JSON.stringify(data) },
    'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
  } });
  t.after(() => page.close());
  // The reveal lives on the deepest round the event published, so that is
  // where a reader asks; the badges then follow them back up the bracket.
  page.run(`selectRound(ROUNDS[ROUNDS.length - 1].id)`);
  page.run(`document.querySelector('#champion [data-champ]').click()`);
  page.run(`selectRound(ROUNDS.find(r => r.label === ${JSON.stringify(label)}).id)`);
  return page;
};

const badges = (page) => Object.fromEntries(page.$$('#round-body tbody td')
  .filter((td) => td.querySelector('.place'))
  .map((td) => [td.textContent.replace(/\s*(champion|runner-up|top 4)\s*$/i, '').trim(),
                td.querySelector('.place').textContent.trim()]));

test('the other finalist is the runner-up', async (t) => {
  const page = await openAt(t, placed(), 'Final');
  assert.deepEqual(badges(page),
    { 'Ada Lovelace': 'champion', 'Bo Peep': 'runner-up' });
});

test('and the Duelists they beat to get there reached the Top 4', async (t) => {
  // Not third and fourth. There is no third place match, so they did not play
  // off: there is no third and fourth, there are two thirds.
  const page = await openAt(t, placed(), 'Top 4');
  assert.deepEqual(badges(page), {
    'Ada Lovelace': 'champion', 'Bo Peep': 'runner-up',
    'Cid Vega': 'top 4', 'Dee Marsh': 'top 4',
  });
});

test('with no final published, nobody is named runner-up', async (t) => {
  // 106 of the archive's 142 tournaments announce a winner without publishing
  // the final's pairing. The runner-up is in the Top 4 somewhere and there is
  // nothing here that says which of the three they are.
  const page = await openAt(t, placed({ withFinal: false }), 'Top 4');
  const got = badges(page);
  assert.equal(got['Ada Lovelace'], 'champion');
  assert.deepEqual(
    [got['Bo Peep'], got['Cid Vega'], got['Dee Marsh']],
    ['top 4', 'top 4', 'top 4']);
});

test('a Duelist holds one place, the highest they reached', async (t) => {
  // The champion played the Top 4 too, and is not badged twice.
  const page = await openAt(t, placed(), 'Top 4');
  const cells = page.$$('#round-body tbody td')
    .filter((td) => /Ada Lovelace/.test(td.textContent));
  for (const td of cells) assert.equal(td.querySelectorAll('.place').length, 1);
  assert.equal(page.$('#round-body .place').textContent.trim(), 'champion');
});

test('no placement is shown before the champion is revealed', async (t) => {
  // A runner-up badge says who did not win, which gives the ending away as
  // plainly as the champion's own does.
  const page = await loadPage({ routes: {
    'rounds.json': { status: 200, body: JSON.stringify(placed()) },
    'sample-remote-duel-ycs/posts.json': { status: 200, body: '[]' },
  } });
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.label === 'Top 4').id)`);
  assert.equal(page.$$('#round-body .place').length, 0);
});

test('a Top 4 Duelist the builder could not tell apart is not badged', async (t) => {
  // The same guard the champion gets, and for the same reason: a name the
  // builder refused to derive a record for is one it could not separate from
  // somebody else, so a badge on it may be on the wrong Duelist.
  const d = placed();
  const t4 = d.formats[0].rounds.find((r) => r.label === 'Top 4');
  t4.pairings[1].bRec = null;          // Dee Marsh, underived
  for (const r of d.formats[0].rounds){
    for (const st of r.standings ?? []) if (st.name === 'Dee Marsh') st.record = null;
  }
  const page = await openAt(t, d, 'Top 4');
  const got = badges(page);
  assert.equal(got['Cid Vega'], 'top 4', 'the Duelist beside them is still placed');
  assert.equal(got['Dee Marsh'], undefined);
});

test('a final that does not name the champion names no runner-up', async (t) => {
  // The final's table is read like any other and can be the wrong table. If
  // the Duelist who won is not in it, it is not the match they won, and
  // whoever is in it did not come second.
  const d = placed();
  const fin = d.formats[0].rounds.find((r) => r.label === 'Final');
  fin.pairings = [{ table: 1, a: 'Cid Vega', aRec: rec(4), b: 'Dee Marsh', bRec: rec(3) }];
  const page = await openAt(t, d, 'Top 4');
  const got = badges(page);
  assert.ok(!Object.values(got).includes('runner-up'), JSON.stringify(got));
});
