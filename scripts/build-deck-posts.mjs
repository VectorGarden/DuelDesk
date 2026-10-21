/**
 * Freeze which posts hold deck lists, as read.js reads them.
 *
 * The page owns what a deck is. article.holds_decks only answers whether there
 * is anything to take, so the button can be offered before an article is
 * fetched -- and the two have to agree, or the page offers a download of
 * nothing, or hides one somebody wanted.
 *
 * This writes what the page finds. scraper/test_scraper.py asserts the
 * scraper's answer matches it over every article in the archive.
 *
 *     node scripts/build-deck-posts.mjs
 */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const dom = new JSDOM('<!doctype html><body></body>');
const { document } = dom.window;

// decks.js whole: it was written to read paragraphs and give back decks
// without touching the page it is on, so it needs no carving up. Slicing it out
// of read.js by marker strings is what broke when #262 moved it there -- a
// marker that is gone is index -1, the slice is nonsense, and the first anyone
// heard of it was "linesOf is not defined" weeks later, from a test that had
// been comparing against a file this could no longer write.
const engine = readFileSync(join(ROOT, 'decks.js'), 'utf8');
const common = readFileSync(join(ROOT, 'common.js'), 'utf8');
const slice = (s, a, b) => {
  const from = s.indexOf(a), to = s.indexOf(b);
  if (from < 0 || to < 0) throw new Error(`common.js no longer has ${from < 0 ? a : b}`);
  return s.slice(from, to);
};

const api = new Function(
  'document', 'NodeFilter', 'btoa', 'esc', 'playerLink', 'safeUrl',
  slice(common, 'const EMPHASIS', 'function cardKey')
  + engine
  + '; return {linesOf, layoutOf, decksByPlace, blocksHtml};')(
  document, dom.window.NodeFilter,
  (s) => Buffer.from(s, 'binary').toString('base64'),
  (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])),
  (who, written) => String(written ?? who ?? ''), (u) => u);

const held = {};
for (const slug of readdirSync(join(ROOT, 'events'))) {
  let articles;
  try {
    articles = JSON.parse(readFileSync(join(ROOT, 'events', slug, 'articles.json'), 'utf8'));
  } catch { continue; }
  for (const [url, blocks] of Object.entries(articles)) {
    const box = document.createElement('div');
    box.innerHTML = api.blocksHtml(blocks);
    const lines = [];
    for (const el of box.children) lines.push(...api.linesOf(el));
    let found;
    try { found = api.decksByPlace(lines, api.layoutOf(lines)); } catch { continue; }
    if (found.length) held[url] = found.length;
  }
}

const out = join(ROOT, 'test/fixtures/deck-posts.json');
const lines = Object.keys(held).sort().map(
  (url) => `  ${JSON.stringify(url)}: ${held[url]}`);
writeFileSync(out, '{\n  "decks": {\n' + lines.map((l) => '  ' + l).join(',\n')
  + '\n  }\n}\n');
console.log(`${lines.length} posts hold deck lists, ${
  Object.values(held).reduce((n, x) => n + x, 0)} decks -> test/fixtures/deck-posts.json`);
