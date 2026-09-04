/**
 * Taking an event's deck lists.
 *
 * The reader offers one post's decks; this offers every deck list the event
 * published, in one download. What makes that cheap is that the scraper has
 * already read the articles: a post carries decks: true when it holds deck
 * lists, so the button is offered, or not, out of posts.json.
 *
 * 99 posts in the archive hold deck lists across 41 events. 99 events have a
 * post whose title says "deck", which is why the title is not what this asks.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadPage } from './harness.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

/* The manifest, with the event saying how many of its posts hold deck lists.

   Out of events.json rather than the event's posts, because the button has to
   be offered before anything is fetched -- asking for the posts to find out
   re-rendered the coverage list underneath somebody opening it. */
function manifest(decks){
  const held = JSON.parse(readFileSync(join(ROOT, 'test/fixtures/events.json'), 'utf8'));
  const events = (held.events ?? held).map(
    (e, i) => (i === 0 && decks ? {...e, decks} : e));
  return { 'events.json': { status: 200,
    body: JSON.stringify(held.events ? {...held, events} : events) } };
}

test('the button is offered where the event has deck lists', async (t) => {
  const page = await loadPage({ routes: manifest(2) });
  t.after(() => page.close());
  const button = page.$('#export-decks');
  assert.equal(button.hidden, false, 'it should be offered');
  assert.match(button.textContent, /Deck Lists/);
  assert.match(button.getAttribute('aria-label'), /from 2 posts/);
});

test('and not where the event has none', async (t) => {
  // A post about decks is not a post of deck lists: "Deck Breakdown" names a
  // handful of cards in prose. Offering a download of nothing is worse than
  // offering nothing, and 99 events have such a post where 41 have decks.
  const page = await loadPage({ routes: manifest(0) });
  t.after(() => page.close());
  assert.equal(page.$('#export-decks').hidden, true);
});

test('the reader and the coverage page read decks with the same code', () => {
  // Written twice for about a day. decks.js is where it lives now, and both
  // pages load it -- so a deck is the same thing on both, by construction.
  const engine = readFileSync(join(ROOT, 'decks.js'), 'utf8');
  for (const name of ['function decksIn', 'function layoutOf', 'function decksByPlace',
                      'function ydkOf', 'function handOverAll']){
    assert.ok(engine.includes(name), `${name} should live in decks.js`);
  }
  const read = readFileSync(join(ROOT, 'read.js'), 'utf8');
  for (const name of ['function decksIn', 'function layoutOf', 'function ydkOf']){
    assert.ok(!read.includes(name), `${name} should not be in read.js as well`);
  }
  for (const page of ['index.html', 'read/index.html']){
    assert.match(readFileSync(join(ROOT, page), 'utf8'), /src="\/?decks\.js/,
      `${page} should load decks.js`);
  }
});
