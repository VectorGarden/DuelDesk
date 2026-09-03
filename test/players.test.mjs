/**
 * The player index, and the one contract that matters about it.
 *
 * The scraper decides which of 512 files a Duelist's record goes in; the page
 * has to work out the same number from the same name, in another language,
 * without asking. If the two ever disagree the page fetches the wrong file and
 * reports that nobody by that name exists — which looks like missing data
 * rather than a bug.
 *
 * So this does not test the page's arithmetic against a copy of itself. It
 * tests it against the shards the scraper actually wrote.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

/* The page's own function, lifted out of player.js rather than reimplemented,
   so this cannot pass against a second copy that has drifted. */
const source = readFileSync(join(ROOT, 'player.js'), 'utf8');
const body = source.slice(source.indexOf('async function shardOf('));
// The count comes out of the page too. Passed in as a constant, this test
// would go on passing with the page sharding into some other number.
const SHARDS = Number(/const SHARDS = (\d+);/.exec(source)[1]);
const shardOf = new Function('SHARDS',
  body.slice(0, body.indexOf('\n}') + 2) + '; return shardOf;')(SHARDS);

const shardFiles = readdirSync(join(ROOT, 'players')).filter((f) => f.endsWith('.json'));

test('the page and the scraper agree on where every Duelist lives', async () => {
  // Every name in every shard, not a sample: the whole point is that no name
  // resolves to the wrong file, and 66,000 names take under a second.
  let checked = 0;
  for (const file of shardFiles) {
    const expected = file.replace('.json', '');
    const shard = JSON.parse(readFileSync(join(ROOT, 'players', file), 'utf8'));
    // Aliases are in the shard the folded-away spelling hashes to, which is
    // the whole point of them, so they are checked like any other name.
    const names = Object.keys(shard);
    for (const name of names) {
      assert.equal(await shardOf(name), expected, `${name} is in ${file}`);
      checked += 1;
    }
  }
  assert.ok(checked > 1000, `expected the whole index, checked ${checked}`);
});

test('a name that differs only in punctuation lands in the same file', async () => {
  // "P. Hoban" and "P Hoban" are one page's worth of question.
  assert.equal(await shardOf('P. Hoban'), await shardOf('P Hoban'));
  assert.equal(await shardOf('Ada Lovelace'), await shardOf('ada  lovelace!'));
});

test('every shard is one of the five hundred and twelve', async () => {
  for (const name of ['Ada Lovelace', 'Bo Peep', '*** ***', 'Zed']) {
    const n = await shardOf(name);
    assert.match(n, /^\d{3}$/);
    assert.ok(Number(n) >= 0 && Number(n) < 512);
  }
});

test('a spelling that was folded away points at the one that was kept', () => {
  // The fold moves a record to the fuller name, and the shard is worked out
  // from the name asked for -- so without a pointer, a reader who typed the
  // spelling the coverage used would be told nobody by that name exists.
  const aliases = [];
  for (const file of shardFiles) {
    const shard = JSON.parse(readFileSync(join(ROOT, 'players', file), 'utf8'));
    for (const [name, value] of Object.entries(shard)) {
      if (!Array.isArray(value)) aliases.push([name, value]);
    }
  }
  assert.ok(aliases.length, 'the archive folds names, so some should point');
  for (const [name, value] of aliases) {
    assert.equal(typeof value.as, 'string', `${name} points nowhere`);
    assert.notEqual(value.as, name);
  }
});

test('and what it points at is really there', async () => {
  for (const file of shardFiles) {
    const shard = JSON.parse(readFileSync(join(ROOT, 'players', file), 'utf8'));
    for (const [name, value] of Object.entries(shard)) {
      if (Array.isArray(value)) continue;
      const target = JSON.parse(
        readFileSync(join(ROOT, 'players', `${await shardOf(value.as)}.json`), 'utf8'));
      assert.ok(Array.isArray(target[value.as]),
        `${name} points at ${value.as}, which is not in the index`);
    }
  }
});

/* ── The links that reach these pages ────────────────────────────────────── */

test('a Duelist name links to their own page, in a new tab', async () => {
  // Asked for explicitly: a reader following a name out of a bracket is
  // looking something up beside what they were reading, not leaving it.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    page.$('[data-view="pairings"]').click();
    const link = page.$('#round-body a.who');
    assert.ok(link, 'the round tables name Duelists and should link them');
    assert.match(link.getAttribute('href'), /^\/player\/\?name=/);
    assert.equal(link.getAttribute('target'), '_blank');
    // A new tab handed a reference back can navigate the one it came from.
    assert.match(link.getAttribute('rel'), /noopener/);
  } finally {
    await page.close();
  }
});

test('a name is escaped into the query rather than the path', async () => {
  // 66,000 names include full stops, apostrophes, slashes and hashes, and a
  // path would have to carry them.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    const href = page.get(`playerLink("Ann O'Neil / Smith").match(/href="([^"]+)"/)[1]`);
    assert.equal(href, "/player/?name=Ann%20O'Neil%20%2F%20Smith");
  } finally {
    await page.close();
  }
});

test('a seat that is not a Duelist does not link', async () => {
  // A bye and an unnamed seat are written "*** ***", and a name with no
  // letters in it is nobody -- the test records.is_placeholder makes.
  const { loadPage } = await import('./harness.mjs');
  const page = await loadPage();
  try {
    for (const nobody of ['*** ***', '---', '']) {
      assert.equal(page.get(`playerLink(${JSON.stringify(nobody)}).includes("<a")`), false,
        `${nobody} should not be a link`);
    }
    assert.equal(page.get(`playerLink("Ada Lovelace").includes("<a")`), true);
  } finally {
    await page.close();
  }
});
