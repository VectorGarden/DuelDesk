/**
 * Taking a deck away.
 *
 * A deck list on a page is for reading. A deck list somebody wants to play is
 * a file, and three of them matter: a .ydk, which every simulator opens; a
 * ydke:// URI, which is the same thing as a link; and the JSON a tournament
 * registration form takes.
 *
 * They do not speak the same language. .ydk and ydke:// carry the eight-digit
 * passcode printed on the card; registration wants Konami's own id under
 * CardDatabaseId. Getting that wrong registers somebody for a deck they are
 * not playing, so both numbers are asserted here rather than assumed.
 *
 * The parsing and the writing are lifted out of read.js rather than
 * reimplemented, and run against text: none of it needs a browser, which is
 * why it is written to not need one.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const reader = readFileSync(join(ROOT, 'read.js'), 'utf8');
const deckcode = new Function('btoa',
  reader.slice(reader.indexOf('const DECK_COUNT'), reader.indexOf('let popup = null;'))
  + '; return {decksIn, pileOf, ydkOf, ydkeOf, registrationOf, missing};')(
    (s) => Buffer.from(s, 'binary').toString('base64'));

const { decksIn, pileOf, ydkOf, ydkeOf, registrationOf, missing } = deckcode;

/* A post as Konami writes one: a heading, then sections, one card to a line
   behind its count. */
const POST = [
  'Wanna see the Decks that Duelists piloted to the Top 8 this weekend?',
  '1st Place', 'Raymond Dai', 'Exosisters',
  'Monsters: 4', '3 Ash Blossom & Joyous Spring', '1 Exosister Irene',
  'Spells: 2', '2 Pot of Prosperity',
  'Traps: 1', '1 Infinite Impermanence',
  'Extra Deck: 1', '1 Exosister Asophiel',
  'Side Deck: 2', '2 Droll & Lock Bird',
  '2nd Place', 'Somebody Else', 'Tearlaments',
  'Monsters: 1', '1 Tearlaments Merrli',
  'Extra Deck: 1', '1 Some Fusion',
];

const STORE = {
  'Ash Blossom & Joyous Spring': {id: 14558127, cid: 12950},
  'Exosister Irene': {id: 22331122, cid: 17001},
  'Pot of Prosperity': {id: 84211599, cid: 15352},
  'Infinite Impermanence': {id: 10045474, cid: 13340},
  'Exosister Asophiel': {id: 11111111, cid: 17002},
  'Droll & Lock Bird': {id: 94145021, cid: 9962},
  'Tearlaments Merrli': {id: 22331010, cid: 17500},
  /* In the store, but with no Konami id -- 2% of the database is like this,
     and a registration file cannot carry it. */
  'Some Fusion': {id: 55555555},
  /* And the other way about: known to the store, with no passcode to write
     into a .ydk. */
  'Nameless Thing': {cid: 19999},
};
const resolve = (name) => STORE[name] ?? null;

test('a post of eight decks is read as eight decks', async () => {
  const decks = decksIn(POST);
  assert.equal(decks.length, 2);
  assert.equal(decks[0].name, '1st Place — Raymond Dai — Exosisters');
  assert.equal(decks[1].name, '2nd Place — Somebody Else — Tearlaments');
});

test('each pile holds what its section said', async () => {
  const [deck] = decksIn(POST);
  assert.deepEqual(deck.Monsters, [
    {name: 'Ash Blossom & Joyous Spring', quantity: 3},
    {name: 'Exosister Irene', quantity: 1}]);
  assert.equal(deck.Spells.length, 1);
  assert.equal(deck.Traps.length, 1);
  assert.equal(deck.Extra.length, 1);
  assert.equal(deck.Side.length, 1);
});

/* The other shape: two columns.
 *
 * 21 posts write a deck list with the count alone on its line and the card's
 * name emphasised on the next. They held 38 decks and 2,596 cards and could
 * not be read at all, because a line saying "3" is not a card and a line
 * saying "Blue-Eyes White Dragon" has no quantity.
 */
const TWO_COLUMNS = [
  {text: 'Billy Brake', emph: true},
  {text: 'Monsters:', emph: true},
  {text: '24', emph: false},                    // the section's own total
  {text: '3', emph: false},
  {text: 'Blue-Eyes White Dragon', emph: true},
  {text: '1', emph: false},
  {text: 'Sage with Eyes of Blue', emph: true},
  {text: 'Extra Deck:', emph: true},
  {text: '15', emph: false},
  {text: '2', emph: false},
  {text: 'Azure-Eyes Silver Dragon', emph: true},
];

test('a count on its own line belongs to the name under it', async () => {
  const [deck] = decksIn(TWO_COLUMNS);
  assert.deepEqual(deck.Monsters, [
    {name: 'Blue-Eyes White Dragon', quantity: 3},
    {name: 'Sage with Eyes of Blue', quantity: 1}]);
  assert.deepEqual(deck.Extra, [{name: 'Azure-Eyes Silver Dragon', quantity: 2}]);
});

test("a section's own total is not a quantity of anything", async () => {
  // "Monsters:" then 24 then 3 then the card. The total is overwritten by the
  // count that follows it; read as a quantity it made 24 Blue-Eyes.
  const [deck] = decksIn(TWO_COLUMNS);
  assert.equal(deck.Monsters[0].quantity, 3, 'not 24');
  assert.equal(deck.Extra[0].quantity, 2, 'not 15');
});

test('a line is emphasised only when the whole of it is', async (t) => {
  // What separates the two columns is that the card's name is bold and the
  // count is not. "He activated Effect Veiler" is a sentence with a card in
  // it, and read as emphasis -- because it ends in some -- it would be a card
  // called after the whole sentence.
  //
  // linesOf needs a document, so it is run in one rather than reimplemented.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    const got = page.json(`(() => {
      ${reader.slice(reader.indexOf('function linesOf(p)'), reader.indexOf('/* Which paragraph each deck begins at'))}
      const p = document.createElement('p');
      p.innerHTML = '<b>Blue-Eyes White Dragon</b>\\nHe activated <b>Effect Veiler</b>\\n3';
      return linesOf(p).map(({text, emph}) => [text, emph]);
    })()`);
    assert.deepEqual(got, [
      ['Blue-Eyes White Dragon', true],
      ['He activated Effect Veiler', false],
      ['3', false]]);
  } finally {
    await page.close();
  }
});

test('a plain line after a count is not a card name', async () => {
  // Emphasis is what separates the two columns. Without it the sentence after
  // a stray number would be read as a card.
  const [deck] = decksIn([
    {text: 'Monsters:', emph: true},
    {text: '10', emph: false},
    {text: '3', emph: false},
    {text: 'and then he drew', emph: false},
    {text: 'Blue-Eyes White Dragon', emph: true}]);
  assert.deepEqual(deck?.Monsters ?? [], [], 'nothing was claimed');
});

test('lines given as plain strings still read the one-line shape', async () => {
  // The caller does not always know about emphasis, and the 77 posts that
  // write "3 Ash Blossom & Joyous Spring" never needed it.
  const [deck] = decksIn(POST);
  assert.equal(deck.Monsters[0].quantity, 3);
});

test('the section says which pile, because the post already knows', async () => {
  assert.equal(pileOf('Monster Cards: 19'), 'Monsters');
  assert.equal(pileOf('Spells: 15'), 'Spells');
  assert.equal(pileOf('Trap Cards'), 'Traps');
  assert.equal(pileOf('Extra Deck: 15'), 'Extra');
  assert.equal(pileOf('Side Deck: 15'), 'Side');
});

test('a post with no deck list in it yields no decks', async () => {
  // A deck breakdown counts players, not cards: "12 Maliss" is twelve
  // Duelists, and it is written exactly like a card line. What tells them
  // apart is that a deck list says "Monsters" first.
  assert.deepEqual(decksIn(['Deck Breakdown', '12 Maliss', '9 Snake-Eye']), []);
});

test('a .ydk is passcodes, one line per copy', async () => {
  const [deck] = decksIn(POST);
  const lines = ydkOf(deck, resolve, deck.name).split('\n');
  assert.equal(lines[0], '#created by 1st Place — Raymond Dai — Exosisters');
  const main = lines.slice(lines.indexOf('#main') + 1, lines.indexOf('#extra'));
  assert.deepEqual(main, ['14558127', '14558127', '14558127', '22331122',
                          '84211599', '84211599', '10045474'],
    'monsters, then spells, then traps -- three copies written three times');
  assert.deepEqual(lines.slice(lines.indexOf('#extra') + 1, lines.indexOf('!side')),
                   ['11111111']);
  assert.deepEqual(lines.slice(lines.indexOf('!side') + 1).filter(Boolean),
                   ['94145021', '94145021']);
});

test('a ydke:// is those same passcodes, little-endian and base64', async () => {
  const [deck] = decksIn(POST);
  const uri = ydkeOf(deck, resolve);
  assert.match(uri, /^ydke:\/\/[^!]*![^!]*![^!]*!$/, 'three sections and a trailing !');

  /* Decoded the way every reader of the format decodes it. */
  const ids = (b64) => {
    const bytes = Buffer.from(b64, 'base64');
    const out = [];
    for (let i = 0; i < bytes.length; i += 4) out.push(bytes.readUInt32LE(i));
    return out;
  };
  const [main, extra, side] = uri.replace('ydke://', '').split('!');
  assert.deepEqual(ids(main), [14558127, 14558127, 14558127, 22331122,
                               84211599, 84211599, 10045474]);
  assert.deepEqual(ids(extra), [11111111]);
  assert.deepEqual(ids(side), [94145021, 94145021]);
});

test('registration JSON counts copies and uses Konami ids, not passcodes', async () => {
  const [deck] = decksIn(POST);
  const json = registrationOf(deck, resolve, deck.name);
  assert.deepEqual(Object.keys(json),
    ['Name', 'Monsters', 'Spells', 'Traps', 'Side', 'Extra']);
  assert.deepEqual(json.Monsters, [
    {CardDatabaseId: 12950, Quantity: 3},
    {CardDatabaseId: 17001, Quantity: 1}],
    'the Konami id, and the copies counted rather than repeated');
  assert.equal(json.Monsters.some((c) => c.CardDatabaseId === 14558127), false,
    'a passcode here would register somebody for the wrong card');
});

test('what cannot be named is named', async () => {
  // A deck exported two cards short is a deck that loses games, so the
  // shortfall is said out loud rather than quietly dropped.
  const [, second] = decksIn(POST);
  assert.deepEqual(missing(second, resolve, 'id'), [],
    'every card of it has a passcode');
  assert.deepEqual(missing(second, resolve, 'cid'), ['Some Fusion'],
    'and one of them has no Konami id, so registration cannot carry it');
  assert.deepEqual(missing(second, () => null, 'id'),
    ['Tearlaments Merrli', 'Some Fusion']);
});

test('a card with no passcode is left out of the files made of passcodes', async () => {
  const deck = decksIn(['Monsters: 2', '2 Nameless Thing', '1 Exosister Irene'])[0];
  const ydk = ydkOf(deck, resolve, '').split('\n');
  assert.deepEqual(ydk.slice(ydk.indexOf('#main') + 1, ydk.indexOf('#extra')),
                   ['22331122'], 'only the one that has a passcode');
  const [main] = ydkeOf(deck, resolve).replace('ydke://', '').split('!');
  assert.equal(Buffer.from(main, 'base64').length, 4, 'one card, four bytes');
  assert.deepEqual(missing(deck, resolve, 'id'), ['Nameless Thing'], 'and said so');
});

test('a card the store does not have is left out rather than guessed', async () => {
  const [, second] = decksIn(POST);
  const json = registrationOf(second, resolve, second.name);
  assert.deepEqual(json.Extra, [], 'no Konami id, so not in the registration file');
  const ydk = ydkOf(second, resolve, '').split('\n');
  assert.deepEqual(ydk.slice(ydk.indexOf('#extra') + 1, ydk.indexOf('!side')),
                   ['55555555'], 'but it has a passcode, so the .ydk keeps it');
});

/* Laying a post of many decks out.
 *
 * The Top 64 lists run to 63 decks and 3,331 lines, and the only way to the
 * fortieth was to scroll past thirty-nine. So each deck becomes a section: a
 * heading that opens it, one pile shown at a time, and an index to reach any
 * of them.
 *
 * Where a deck starts and which paragraphs hold which pile is the part with
 * the logic in it, and it needs no browser: the layout is asked of lines and
 * of whatever the lines came from, so it can be asked of stand-ins.
 */
/* Two stretches of the file: the parsing, and the laying out that uses it.
   Neither needs a browser at the point of being defined. */
const layout = new Function('btoa',
  reader.slice(reader.indexOf('const DECK_COUNT'), reader.indexOf('let popup = null;'))
  + reader.slice(reader.indexOf('const PILES'), reader.indexOf('function showPile'))
  + '; return {layoutOf, copiesIn};')(() => '');

/* Paragraph stand-ins: the layout only ever asks a paragraph what comes after
   it, which is the whole of what it needs to know. */
function paragraphs(...texts){
  const nodes = texts.map((text) => ({text, nextElementSibling: null}));
  nodes.forEach((n, i) => { n.nextElementSibling = nodes[i + 1] ?? null; });
  const lines = [];
  for (const node of nodes){
    for (const line of node.text.split('\n')) lines.push({text: line, p: node});
  }
  return {nodes, lines};
}

test('a deck begins at its heading, not at its first section', async () => {
  const {nodes, lines} = paragraphs(
    'Wanna see the Decks?', '1st Place\nRaymond Dai',
    'Monsters: 2\n2 Ash Blossom & Joyous Spring', 'Extra Deck: 1\n1 Some Fusion');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.at, nodes[1], 'the paragraph naming the Duelist');
  assert.equal(deck.title, nodes[1]);
});

test("a post's opening line belongs to the post, not to the first deck", async () => {
  // "Wanna see the Decks that Duelists piloted to the Top 8?" is not whoever
  // came first, and the Duelist's name sits between them. The heading counts
  // only when it is the paragraph immediately before the section, which is
  // what keeps the introduction out of the first deck -- and out of the index,
  // where it read as a Duelist called "Here are the Deck Lists for the Top
  // Cut of the North America World Championship Qualifier!".
  const {nodes, lines} = paragraphs(
    'Wanna see the Decks?', 'Wilfredo Michael Flores', 'Main Deck: 41',
    'Monster Cards: 1', '1 Bystial Baldrake');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.at, nodes[1], "the Duelist's name");
  assert.equal(deck.title, nodes[1]);
  assert.equal(deck.at === nodes[0], false, 'and never the introduction');
});

test('a heading with a card between it and the section is not the deck\'s', async () => {
  // Adjacency is the whole of the rule. A counted line does not make a new
  // heading, so without it the last thing said any distance back would be
  // taken for the deck's name.
  const {nodes, lines} = paragraphs(
    'Somebody Else', '3 Maliss', 'Monsters: 1\n1 Bystial Baldrake');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.title, null, 'nothing adjacent, so no heading');
  assert.equal(deck.at, nodes[2], 'the section itself');
});

test('a heading with no number leaves the count it found', async () => {
  const {lines} = paragraphs('Somebody', 'Monsters: 19', '1 Bystial Baldrake',
                             'Monsters', '1 Ash Blossom & Joyous Spring');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.piles.get('Monsters').said, 19);
});

test('a pile owns its heading and whatever paragraphs follow it', async () => {
  // Konami writes some posts with the heading and its cards together, and
  // others with the heading alone and the cards in the paragraph after.
  const {nodes, lines} = paragraphs(
    'Wilfredo Michael Flores', 'Main Deck: 41', 'Monster Cards: 31',
    '1 Bystial Baldrake\n3 Mulcharmy Fuwalos', 'Spell Cards: 8', '3 Forbidden Droplet');
  const [deck] = layout.layoutOf(lines);
  assert.deepEqual(deck.piles.get('Monsters').held, [nodes[1], nodes[2], nodes[3]]);
  assert.deepEqual(deck.piles.get('Spells').held, [nodes[4], nodes[5]]);
});

test('a main deck total is not the number of monsters in it', async () => {
  // "Main Deck: 41" and "Monster Cards: 31" are both headings and only one of
  // them counts monsters. The tab carried 41 until it stopped listening to
  // the first.
  const {lines} = paragraphs('Somebody', 'Main Deck: 41', 'Monster Cards: 31',
                             '1 Bystial Baldrake');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.piles.get('Monsters').said, 31);
});

test('the next deck starts where the last one stops', async () => {
  const {nodes, lines} = paragraphs(
    '1st Place\nRaymond Dai', 'Monsters: 1\n1 Ash Blossom & Joyous Spring',
    'Side Deck: 1\n1 Droll & Lock Bird',
    '2nd Place\nSomebody Else', 'Monsters: 1\n1 Tearlaments Merrli');
  const decks = layout.layoutOf(lines);
  assert.equal(decks.length, 2);
  assert.equal(decks[1].at, nodes[3], 'at the second name, not at its Monsters');
});

test('a deck is measured in copies, not in lines', async () => {
  // Three of a card is three cards. A list of 41 that says 18 is wrong about
  // the only number anybody checks.
  const [deck] = decksIn(POST);
  assert.equal(layout.copiesIn(deck), 7, '3 + 1 + 2 + 1, and no extra or side');
});
