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
