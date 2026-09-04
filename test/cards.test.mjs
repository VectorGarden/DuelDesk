/**
 * The card store, and the one contract that matters about it.
 *
 * The scraper decides which of 512 files a card's text goes in, and keys it on
 * the name with its punctuation and case taken out. The page has to work out
 * the same key and the same number from the same name, in another language,
 * without asking — because what it has is whatever the coverage typed and what
 * it wants is what Konami calls the card.
 *
 * So this does not test the page's arithmetic against a copy of itself. It
 * tests it against the shards the scraper actually wrote.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CARDS = join(ROOT, 'cards');

/* The numbered files, and not ids.json beside them: that one is every card's
   numbers with none of its text, and it is not a shard. */
const shardFiles = () =>
  readdirSync(CARDS).filter((f) => /^\d{3}\.json$/.test(f));

/* The page's own functions, lifted out of common.js rather than
   reimplemented, so this cannot pass against a second copy that has drifted.
   Run here rather than in the page: the lookup hashes with crypto.subtle,
   which node has and the harness's jsdom does not. */
const source = readFileSync(join(ROOT, 'common.js'), 'utf8');
const section = source.slice(source.indexOf('const CARD_SHARDS'),
                             source.indexOf('function offsite('));
const load = (fetcher) => new Function('fetch',
  section + '; return {cardKey, cardShardOf, lookupCard, CARDS};')(fetcher);

const { cardKey, cardShardOf } = load(async () => ({ok: false}));
const SHARD_COUNT = Number(/const CARD_SHARDS = (\d+);/.exec(source)[1]);

test('the page and the scraper agree on every card in the store', async (t) => {
  if (!existsSync(CARDS)) return t.skip('no card store built');
  // Every card in every shard, not a sample: a name that resolves to the wrong
  // file is a hover that quietly finds nothing, which looks like missing data
  // rather than a bug.
  let checked = 0;
  for (const file of shardFiles()) {
    const expected = file.replace('.json', '');
    const shard = JSON.parse(readFileSync(join(CARDS, file), 'utf8'));
    for (const [key, card] of Object.entries(shard)) {
      /* Its own name, or -- for the ten cards named with a token in angle
         brackets -- the name without it. The coverage cannot hold those
         brackets: published unescaped, the blog's editor read "<P>" as a
         paragraph and broke the name across one, so the store answers to the
         halves rejoined as well. */
      const own = cardKey(card.name);
      const without = cardKey(card.name.replace(/<[^>]{1,3}>/g, ' '));
      assert.ok(key === own || key === without,
        `${card.name} keys differently here`);
      assert.equal(await cardShardOf(key), expected,
        `${card.name} would be looked for elsewhere`);
      checked += 1;
    }
  }
  assert.ok(checked > 1000, `only ${checked} cards checked`);
});

test('the count comes out of the page, not out of this file', async () => {
  assert.equal(SHARD_COUNT, 512);
  if (!existsSync(CARDS)) return;
  assert.ok(shardFiles().length <= SHARD_COUNT);
});

test('the key survives what a CMS does to a name', async () => {
  assert.equal(cardKey('Maxx “C”'), cardKey('Maxx "C"'), 'curly quotes');
  assert.equal(cardKey('Rai–Mei'), cardKey('Rai-Mei'), 'an en dash');
  assert.equal(cardKey('ASH BLOSSOM & JOYOUS SPRING'), 'ashblossomjoyousspring');
  assert.equal(cardKey(''), '');
  assert.equal(cardKey(null), '');
});

test('a name that is not a card answers nothing', async () => {
  // Most of what gets offered is not a card. "Duel 1" and "Extra Deck: 15" are
  // emphasised exactly the way a card name is, and 11% of the archive's
  // emphasised mentions are headings like them.
  const store = load(async () => ({
    ok: true, json: async () => ({ashblossomjoyousspring: {name: 'Ash Blossom & Joyous Spring'}}),
  }));
  assert.equal(await store.lookupCard('Duel 1'), null);
  assert.equal(await store.lookupCard(''), null, 'and a name with nothing in it');
  const found = await store.lookupCard('Ash Blossom & Joyous Spring');
  assert.equal(found.name, 'Ash Blossom & Joyous Spring');
});

test('a shard that will not load leaves the reader where they were', async () => {
  const store = load(async () => { throw new Error('offline'); });
  assert.equal(await store.lookupCard('Ash Blossom & Joyous Spring'), null);
});

test('a shard is fetched once, however many of its cards are asked for', async () => {
  let fetches = 0;
  const store = load(async () => {
    fetches += 1;
    return {ok: true, json: async () => ({})};
  });
  await store.lookupCard('Ash Blossom & Joyous Spring');
  await store.lookupCard('Ash Blossom & Joyous Spring');
  assert.equal(fetches, 1, 'a shard is kept once it is here');
});

/* Where the card goes.
 *
 * A deck list is a column of card names. A panel dropped below one covers the
 * next eight, so every way of moving the pointer off it landed on another name
 * and opened another card -- which is what made it hard to be rid of. Beside
 * the name it covers the margin instead.
 *
 * The arithmetic is lifted out of read.js rather than reimplemented, and run
 * against rectangles: the harness's jsdom measures every element as zero, so a
 * browser is no use for asking where a thing would go.
 */
const reader = readFileSync(join(ROOT, 'read.js'), 'utf8');
const geometry = new Function(
  reader.slice(reader.indexOf('const CARD_WIDE'), reader.indexOf('function place(span)'))
  + '; return {placement, cardWidth, CARD_WIDE, CARD_NARROW};')();

const rect = (left, top, width, height) =>
  ({left, top, width, height, right: left + width, bottom: top + height});
const VIEW = {width: 1280, height: 800};

test('a card sits beside the name, not over the list', async () => {
  const at = rect(20, 300, 180, 20);
  const where = geometry.placement(at, rect(0, 0, 480, 240), VIEW);
  assert.equal(where.beside, true);
  assert.ok(where.left >= at.right, 'to the right of the name');
  assert.ok(where.top <= at.top, 'and level with it');
});

test('and on the other side when that is where the room is', async () => {
  const at = rect(1000, 300, 180, 20);
  const where = geometry.placement(at, rect(0, 0, 480, 240), VIEW);
  assert.equal(where.beside, true);
  assert.ok(where.left + 480 <= at.left, 'to the left of the name');
});

test('it goes under the name only when there is no margin at all', async () => {
  const narrow = {width: 380, height: 800};
  const at = rect(20, 300, 180, 20);
  const where = geometry.placement(at, rect(0, 0, 360, 240), narrow);
  assert.equal(where.beside, false);
  assert.ok(where.top >= at.bottom, 'below it');
  assert.ok(where.left >= 8 && where.left + 360 <= narrow.width, 'and on the screen');
});

test('a card too tall for the space below goes above instead', async () => {
  const narrow = {width: 380, height: 400};
  const at = rect(20, 300, 180, 20);
  const where = geometry.placement(at, rect(0, 0, 360, 240), narrow);
  assert.ok(where.top + 240 <= 400, 'it fits on the screen');
  assert.ok(where.top < at.top, 'which means above the name');
});

test('a card level with a name near the bottom is pulled back on screen', async () => {
  const at = rect(20, 760, 180, 20);
  const where = geometry.placement(at, rect(0, 0, 480, 240), VIEW);
  assert.ok(where.top + 240 <= VIEW.height, 'not hanging off the bottom');
  assert.ok(where.top >= 8);
});

test('it narrows to keep out of the list rather than giving up the margin', async () => {
  // A card's text at 15rem is a taller panel. A taller panel in the margin is
  // still better than a wider one over the deck list.
  const at = rect(20, 300, 180, 20);
  assert.equal(geometry.cardWidth(at, VIEW), geometry.CARD_WIDE, 'wide where there is room');
  const tight = geometry.cardWidth(at, {width: 560, height: 800});
  assert.ok(tight < geometry.CARD_WIDE && tight >= geometry.CARD_NARROW,
    `narrowed to ${tight}`);
  assert.equal(geometry.cardWidth(at, {width: 300, height: 800}), geometry.CARD_NARROW,
    'and never below the width its text needs');
});


/* The numbers, apart from the text.
 *
 * A hover wants one card and fetches one shard. An export wants a whole deck
 * list, and the worst post names 642 cards across 367 of the 512 shards --
 * 4.7MB in 367 requests to answer one button.
 */
test('every card in the shards is in the numbers file, and nothing else is', async (t) => {
  if (!existsSync(CARDS)) return t.skip('no card store built');
  const ids = JSON.parse(readFileSync(join(CARDS, 'ids.json'), 'utf8'));
  let expected = 0;
  for (const file of shardFiles()){
    for (const [key, card] of Object.entries(JSON.parse(readFileSync(join(CARDS, file), 'utf8')))){
      if (card.id === undefined) continue;
      expected += 1;
      assert.ok(ids[key], `${card.name} is in a shard and not in the numbers`);
      assert.equal(ids[key][0], card.id, `${card.name} has a different passcode`);
      assert.equal(ids[key][1], card.cid, `${card.name} has a different Konami id`);
    }
  }
  assert.equal(Object.keys(ids).length, expected, 'and nothing that is not a card');
});

test('a card Konami never numbered carries one number, not two', async (t) => {
  if (!existsSync(CARDS)) return t.skip('no card store built');
  const ids = JSON.parse(readFileSync(join(CARDS, 'ids.json'), 'utf8'));
  const lengths = new Set(Object.values(ids).map((v) => v.length));
  assert.deepEqual([...lengths].sort(), [1, 2],
    'a passcode always, and Konami\'s id where there is one');
});

test('the page reads the numbers the same way', async () => {
  const store = load(async () => ({ok: false}));
  const numbers = new Function('cardKey',
    source.slice(source.indexOf('function numbersFor'),
                 source.indexOf('function offsite(')) + '; return numbersFor;')(store.cardKey);
  assert.deepEqual(numbers({ashblossomjoyousspring: [14558127, 12950]},
                           'Ash Blossom & Joyous Spring'),
                   {id: 14558127, cid: 12950});
  assert.deepEqual(numbers({somefusion: [55555555]}, 'Some Fusion'), {id: 55555555});
  assert.equal(numbers({}, 'Not A Card'), null);
});
