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
  for (const file of readdirSync(CARDS).filter((f) => f.endsWith('.json'))) {
    const expected = file.replace('.json', '');
    const shard = JSON.parse(readFileSync(join(CARDS, file), 'utf8'));
    for (const [key, card] of Object.entries(shard)) {
      assert.equal(cardKey(card.name), key, `${card.name} keys differently here`);
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
  assert.ok(readdirSync(CARDS).filter((f) => f.endsWith('.json')).length <= SHARD_COUNT);
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
