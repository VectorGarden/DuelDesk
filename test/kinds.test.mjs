/**
 * What a post is, from its title.
 *
 * The page classifies live feed titles itself, because a feed item arrives
 * with no kind attached. The scraper classifies slugs before fetching,
 * because knowing a post is pairings is what lets a limited budget go to the
 * posts that carry results. Two implementations of one rule.
 *
 * They drifted: over 403 of the archive's 8,076 titles the two disagreed, and
 * the reader saw the page's answer. It read "Public Events winners" as news,
 * because it asked for a singular winner, and filed "QQ: What Decks were you
 * expecting to see this weekend" under deck profiles, because it asked for
 * the bare word "deck".
 *
 * So both suites read the same cases. Consolidating the implementations is
 * issue #182; this is what stops them drifting in the meantime.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadPage } from './harness.mjs';

const CASES = JSON.parse(
  readFileSync(new URL('./fixtures/kinds.json', import.meta.url), 'utf8')).cases;

test('every shared case classifies as the fixture says', async (t) => {
  const page = await loadPage({});
  t.after(() => page.close());
  for (const c of CASES){
    const got = page.get(`kindFrom(${JSON.stringify(c.title.toLowerCase())})`);
    assert.equal(got, c.kind, `${c.title} — ${c.why ?? ''}`);
  }
});

test('the fixture covers every kind the filter offers', async (t) => {
  // A shared fixture only stops a drift it looks at. The filter buttons in
  // index.html are the list this has to match.
  const page = await loadPage({});
  t.after(() => page.close());
  const offered = page.$$('.filters [data-filter]')
    .map((b) => b.dataset.filter).filter((k) => k !== 'all');
  const covered = new Set(CASES.map((c) => c.kind));
  for (const k of offered) assert.ok(covered.has(k), `no shared case for the ${k} filter`);
  assert.ok(covered.has('news'), 'nor for the posts that match nothing');
});
