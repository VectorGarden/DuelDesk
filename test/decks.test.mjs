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

test('taking the name out of a shared paragraph leaves the section behind', async () => {
  // The heading is moved rather than copied, so the Duelist keeps the link
  // the article gave them. Where it shares a paragraph with "Main Deck: 42",
  // moving the paragraph would take the total away from the pile that counts
  // it -- and put it in the name. Only the heading's own lines come away.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    const got = page.json(`(() => {
      ${reader.slice(reader.indexOf('function endOfLine(p, n)'), reader.indexOf('function shapeDecks'))}
      const p = document.createElement('p');
      p.innerHTML = '<b><a class="who" href="/player/?name=Jesse%20Dean%20Kotton">Jesse Kotton</a></b>'
        + '<b> \u2013 1st Place\\nMain Deck: 42</b>';
      const name = document.createElement('span');
      takeHeading(name, p, 1);
      return {name: name.textContent, link: name.querySelector('a.who')?.getAttribute('href'),
              left: p.textContent, still: !!p.parentNode || p.isConnected === false};
    })()`);
    assert.equal(got.name, 'Jesse Kotton – 1st Place', 'the Duelist and the placing');
    assert.equal(got.link, '/player/?name=Jesse%20Dean%20Kotton', 'still their profile');
    assert.equal(got.left, 'Main Deck: 42', 'and the total stays in the article');
  } finally {
    await page.close();
  }
});

test('a heading in a paragraph of its own is taken whole', async () => {
  // Nothing is left of it, and the paragraph goes with it: the heading is not
  // wanted twice, once in the name and once above the cards.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    const got = page.json(`(() => {
      ${reader.slice(reader.indexOf('function endOfLine(p, n)'), reader.indexOf('function shapeDecks'))}
      const box = document.createElement('div');
      box.innerHTML = '<p><b>1st Place</b>\\nRaymond Dai</p><p>Monsters: 2</p>';
      const p = box.firstChild;
      const name = document.createElement('span');
      takeHeading(name, p, 0);
      return {name: name.textContent, gone: box.children.length};
    })()`);
    assert.equal(got.name, '1st Place\nRaymond Dai');
    assert.equal(got.gone, 1, 'the paragraph it came from is gone');
  } finally {
    await page.close();
  }
});

test('a card name that wrapped is one card, not a card and a stray', async () => {
  // "Light Dragon @Ignister Mereologic Aggregator" is too long for the line
  // the coverage wrote it on, and the wrap is a real break in the post. The
  // tail counted nothing and named no section, so it was read as a heading:
  // it ended the deck it was in the middle of, the Side Deck under it opened
  // a deck that was never there, and neither half of the name resolved to a
  // passcode.
  const head = {}, main = {}, extra = {};
  const [deck] = decksIn([
    {text: 'Monsters: 1', p: head},
    {text: '1 Ash Blossom & Joyous Spring', p: main},
    {text: 'Extra Deck: 1', p: head},
    {text: '1 Light Dragon @Ignister', p: extra},
    {text: 'Mereologic Aggregator', p: extra},
  ]);
  assert.deepEqual(deck.Extra.map((c) => c.name),
                   ['Light Dragon @Ignister Mereologic Aggregator']);
  assert.equal(deck.Extra[0].quantity, 1, 'and one copy of it, not two');
});

test('a count written with a full stop is still a count', async () => {
  // YCS Indianapolis 2011 punctuates some of its counts -- "3 T.G. Warwolf"
  // and then "2. T.G. Striker". The full stop where the space should be meant
  // the line counted nothing: the card was left out of the deck, out of the
  // .ydk and out of the ydke://, and the line was very nearly read as more of
  // the T.G. Warwolf above it instead.
  const head = {}, main = {};
  const [deck] = decksIn([
    {text: 'Monsters: 5', p: head},
    {text: '3 T.G. Warwolf', p: main},
    {text: '2. T.G. Striker', p: main},
  ]);
  assert.deepEqual(deck.Monsters.map((c) => c.name),
                   ['T.G. Warwolf', 'T.G. Striker'], 'two cards, not one');
  assert.deepEqual(deck.Monsters.map((c) => c.quantity), [3, 2]);
});

test("the blog's numbered prose is not a card", async () => {
  // A tech update lists what it is about as "1.) Kashtira Fenrir", "2.) The
  // Bystial Monsters". A bracket is not the whitespace a count needs, so none
  // of the 219 lines written that way in the archive is read as a card -- and
  // a line opening with a number is never glued to the card above it either.
  const head = {}, main = {};
  const [deck] = decksIn([
    {text: 'Monsters: 3', p: head},
    {text: '3 Ash Blossom & Joyous Spring', p: main},
    {text: '2.) Gemini Imps', p: main},
  ]);
  assert.deepEqual(deck.Monsters.map((c) => c.name), ['Ash Blossom & Joyous Spring']);
});

test('a wrap cannot cross a paragraph', async () => {
  // A name broken over two paragraphs is not a wrap -- it is the next thing
  // the post had to say, and in a deck list that is whoever came next.
  const head = {}, main = {}, after = {};
  const [deck] = decksIn([
    {text: 'Monsters: 1', p: head},
    {text: '1 Ash Blossom & Joyous Spring', p: main},
    {text: 'Somebody Else', p: after},
  ]);
  assert.deepEqual(deck.Monsters.map((c) => c.name), ['Ash Blossom & Joyous Spring']);
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
  /* A leading "*" marks the paragraph as bold, which is how Konami sets a
     heading that runs to more than one paragraph. */
  const nodes = texts.map((text) => ({text: text.replace(/^\*/, ''),
                                      emph: text.startsWith('*'),
                                      nextElementSibling: null}));
  nodes.forEach((n, i) => { n.nextElementSibling = nodes[i + 1] ?? null; });
  const lines = [];
  for (const node of nodes){
    for (const line of node.text.split('\n')){
      lines.push({text: line, p: node, emph: node.emph});
    }
  }
  return {nodes, lines};
}

test('a deck begins at its heading, not at its first section', async () => {
  const {nodes, lines} = paragraphs(
    'Wanna see the Decks?', '1st Place\nRaymond Dai',
    'Monsters: 2\n2 Ash Blossom & Joyous Spring', 'Extra Deck: 1\n1 Some Fusion');
  const [deck] = layout.layoutOf(lines);
  assert.equal(deck.at, nodes[1], 'the paragraph naming the Duelist');
  assert.deepEqual(deck.title, [nodes[1]]);
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
  assert.deepEqual(deck.title, [nodes[1]]);
  assert.equal(deck.at === nodes[0], false, 'and never the introduction');
});

test('a heading with a card between it and the section is not the deck\'s', async () => {
  // Adjacency is the whole of the rule. A counted line does not make a new
  // heading, so without it the last thing said any distance back would be
  // taken for the deck's name.
  const {nodes, lines} = paragraphs(
    'Somebody Else', '3 Maliss', 'Monsters: 1\n1 Bystial Baldrake');
  const [deck] = layout.layoutOf(lines);
  assert.deepEqual(deck.title, [], 'nothing adjacent, so no heading');
  assert.equal(deck.at, nodes[2], 'the section itself');
});

test('a heading written across paragraphs keeps the Duelist in it', async () => {
  // Speed Duel names a deck in bold -- "Sam Chen - 1st Place" -- and then
  // says in plain text which character and skill it played. Keeping only the
  // paragraph nearest the cards named the deck "Character: Yami Yugi Skill
  // Name: Ever Faithful Companions", which is not a Duelist and, worse, is
  // what a second Duelist on the same character was called too: two decks
  // under one name, and one of them overwritten on the way out as a file.
  const {nodes, lines} = paragraphs(
    'Here are the Top 4 Decks from Saturday\u2019s event!',
    '*Sam Chen \u2013 1st Place',
    'Character: Yami Yugi\nSkill Name: Ever Faithful Companions',
    'Main Deck Total: 21', 'Monster Cards: 14', '3 Dark Magician');
  const [deck] = layout.layoutOf(lines);
  assert.deepEqual(deck.title, [nodes[1], nodes[2]], 'the name and what it played');
  assert.equal(deck.at, nodes[1], 'and the deck starts at the name');
  assert.equal(deck.at === nodes[0], false, 'never the introduction');
});

test('a heading set wholly in bold is kept whole', async () => {
  // Where every paragraph of it is bold, the heading is all of them: the
  // bold begins at the name and there is nothing plain in between.
  const {nodes, lines} = paragraphs(
    'Wanna see the Decks?', '*Steven Le \u2013 2nd Place', '*Character: Tea',
    'Monster Cards: 10', '3 Alpha The Magnet Warrior');
  const [deck] = layout.layoutOf(lines);
  assert.deepEqual(deck.title, [nodes[1], nodes[2]]);
  assert.equal(deck.at, nodes[1], 'never the introduction');
});

test('a line under "Main Deck: 20" is not a second Duelist', async () => {
  // Speed Duel opens a deck with its total and only then says which character
  // and skill it played, plain, under the bold. That line was read as a new
  // heading and ended the deck it belonged to, so every Duelist came out
  // twice: once holding nothing but the total, and once named after the
  // character -- and two Duelists on one character then shared a name.
  const {nodes, lines} = paragraphs(
    'Here are the Top 4 Speed Duel Deck Lists!',
    '*Leif Andersen \u2013 1st', '*Main Deck: 20',
    'Character: Duke Devlin\nSkill Name: See Me Rolling',
    '*Monster Cards: 9', '3 Volcanic Shell\n2 Snipe Hunter',
    '*Side Deck: 2', '2 Kunai with Chain');
  const found = layout.layoutOf(lines);
  assert.equal(found.length, 1, 'one Duelist, one deck');
  assert.deepEqual(found[0].title, [nodes[1]], 'named for the Duelist');
  assert.deepEqual([...found[0].piles.keys()], ['Monsters', 'Side'],
                   'and holding the piles that followed the line');
  assert.equal(found[0].piles.get('Monsters').held.includes(nodes[5]), true,
               'the cards among them');
});

test('a new name ends the deck before it, cut or no cut', async () => {
  // Not every post closes a deck with a Side or an Extra. Where one ends at
  // its traps and the next Duelist is named straight after, the name is all
  // there is to go on -- without it the second deck's cards are added to the
  // first and the post reads as one enormous deck.
  const {nodes, lines} = paragraphs(
    'Somebody', 'Monsters: 1\n1 Ash Blossom & Joyous Spring',
    'Somebody Else', 'Monsters: 1\n1 Tearlaments Merrli');
  const found = layout.layoutOf(lines);
  assert.equal(found.length, 2, 'two Duelists, two decks');
  assert.equal(found[1].at, nodes[2], 'the second at the second name');
});

test('a Duelist written into the section\'s own paragraph still names the deck', async () => {
  // Team YCS writes the name and the total in one paragraph, broken by a line
  // break rather than a paragraph break. The heading was only ever looked for
  // in the paragraph before, so these decks had no name at all and were
  // exported as "Deck 1" and "Deck 2" -- 54 of the 654 decks in the archive.
  const {nodes, lines} = paragraphs(
    'Here are the Deck Lists of the 1st Place team!',
    '*Jesse Kotton \u2013 1st Place\nMain Deck: 42',
    '*Monster Cards: 25', '3 Ash Blossom & Joyous Spring');
  const found = layout.layoutOf(lines);
  assert.equal(found.length, 1, 'one deck, not one per section');
  assert.deepEqual(found[0].title, [nodes[1]], 'named from its own paragraph');
  assert.equal(found[0].upto, 1, 'and only the line above the total is the name');
});

test('a heading in its own paragraph is not read as part of the section', async () => {
  // The other way about: where the heading really is the paragraph before,
  // nothing of the section's paragraph belongs to it.
  const {nodes, lines} = paragraphs(
    'Wanna see the Decks?', '1st Place\nRaymond Dai',
    'Monsters: 2\n2 Ash Blossom & Joyous Spring');
  const [deck] = layout.layoutOf(lines);
  assert.deepEqual(deck.title, [nodes[1]]);
  assert.equal(deck.upto, 0, 'no lines of the section paragraph');
});

test('the tail of a wrapped name does not open a deck that is not there', async () => {
  // The layout has to agree with the parsing about how many decks a post
  // holds -- they are paired by position -- so a tail read as a heading here
  // put every name after it on the wrong deck.
  const {nodes, lines} = paragraphs(
    '*Jesse Kotton \u2013 1st Place', 'Monsters: 1\n1 Ash Blossom & Joyous Spring',
    'Extra Deck: 1\n1 Light Dragon @Ignister\nMereologic Aggregator',
    'Side Deck: 1\n1 Droll & Lock Bird');
  const found = layout.layoutOf(lines);
  assert.equal(found.length, 1, 'one deck, and no phantom under the Side Deck');
  assert.deepEqual(found[0].title, [nodes[0]]);
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

/* A zip, written by hand.
 *
 * Sixty-three deck lists want to arrive as sixty-three files, and a .ydk has
 * no way of holding more than one — the format has no separator. A zip of
 * stored entries is a documented layout and about sixty lines, which is less
 * than a dependency costs on a page that has none.
 *
 * Asserted against the bytes rather than against a reader: node has no unzip,
 * and the point is that the bytes are what the format says they are.
 */
const zipping = new Function('TextEncoder',
  readFileSync(join(ROOT, 'common.js'), 'utf8')
    .slice(readFileSync(join(ROOT, 'common.js'), 'utf8').indexOf('const CRC_TABLE'),
           readFileSync(join(ROOT, 'common.js'), 'utf8').indexOf('function offsite('))
  + '; return {zipOf, crc32, eachNamedOnce};')(TextEncoder);

const u32 = (bytes, at) => new DataView(bytes.buffer, bytes.byteOffset).getUint32(at, true);
const u16 = (bytes, at) => new DataView(bytes.buffer, bytes.byteOffset).getUint16(at, true);

test('a CRC-32 is the one everybody else computes', async () => {
  // The number every reader checks the file against. Wrong, and the zip opens
  // and then refuses its own contents.
  const of = (s) => zipping.crc32(new TextEncoder().encode(s));
  assert.equal(of('123456789'), 0xCBF43926, 'the check value the standard gives');
  assert.equal(of(''), 0);
});

test('the bytes say what a zip says', async () => {
  const zip = zipping.zipOf([{name: 'a.ydk', text: '#main\n1\n'}]);
  assert.equal(u32(zip, 0), 0x04034b50, 'a local header first');
  assert.equal(u16(zip, 8), 0, 'stored, not deflated');
  assert.equal(u16(zip, 6) & 0x0800, 0x0800, 'and the name is UTF-8');
  assert.equal(u32(zip, 22), 8, 'the size it says it is');
  /* And it ends with the directory record every reader looks for first. */
  const end = zip.length - 22;
  assert.equal(u32(zip, end), 0x06054b50);
  assert.equal(u16(zip, end + 10), 1, 'one file in it');
});

test('sixty-three decks are sixty-three files', async () => {
  const files = Array.from({length: 63}, (_, i) => ({name: `deck ${i}.ydk`, text: '#main\n1\n'}));
  const zip = zipping.zipOf(files);
  assert.equal(u16(zip, zip.length - 22 + 10), 63);
});

test('two decks called the same thing are two files', async () => {
  // A name is not an identifier — a post can hold two "Top 8" decks — and two
  // files in a zip cannot share one.
  const files = zipping.eachNamedOnce([
    {name: 'Top 8.ydk', text: 'a'}, {name: 'Top 8.ydk', text: 'b'}, {name: 'Top 8.ydk', text: 'c'}]);
  assert.deepEqual(files.map((f) => f.name),
    ['Top 8.ydk', 'Top 8 (2).ydk', 'Top 8 (3).ydk']);
  assert.deepEqual(files.map((f) => f.text), ['a', 'b', 'c'], 'and each keeps its own');
});

test('a name with an accent survives into the archive', async () => {
  // The names carry accents and em dashes, which is why the UTF-8 flag is set.
  const zip = zipping.zipOf([{name: 'José Ramírez — 1.ydk', text: 'x'}]);
  const nameLength = u16(zip, 26);
  const name = new TextDecoder().decode(zip.slice(30, 30 + nameLength));
  assert.equal(name, 'José Ramírez — 1.ydk');
  assert.ok(nameLength > 'José Ramírez — 1.ydk'.length, 'encoded as UTF-8, not as characters');
});
