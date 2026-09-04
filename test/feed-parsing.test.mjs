import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage, fixture } from './harness.mjs';

const classify = (page, title) => page.run(`classify(${JSON.stringify(title)})`);

test('round slot is found regardless of word order', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const [title, round] of [
    ['Pairings for Round 11', 11],
    ['Round 11 Pairings', 11],
    ['R11 pairings', 11],
    ['Pairings for Top 8', 'Top 8'],
    ['Quarterfinal pairings', 'Top 8'],
    ['Semi-final feature match', 'Top 4'],
    ['The final match', 'Final'],
  ]) {
    assert.deepEqual(classify(page, title).round, round, title);
  }
});

test('coverage type checks structural markers before the looser deck match', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const [title, kind] of [
    ['Pairings for Top 8', 'pairings'],
    ['Top 8 Decklists', 'deck'],
    ['The eight decks still in contention', 'deck'],
    ['Deck profile: Snake-Eye', 'deck'],
    ['Standings after round 10', 'standings'],
    ['Point totals after the circuit', 'standings'],
    ['Feature match: Maliss against Ryzeal', 'feature'],
    ['Your champion, undefeated in the top cut', 'result'],
    ['Deck check penalty issued', 'news'],       // policy term, not deck content
    ['What the top tables were playing', 'news'], // no keyword: fall back, do not guess
  ]) {
    assert.equal(classify(page, title).kind, kind, title);
  }
});

test('the sample marker is stripped wherever it appears', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.json(`groupFeed(\`<?xml version="1.0"?><rss version="2.0"><channel>
    <title>t</title><link>l</link><description>d</description>
    <item><title>[Sample] YCS Montreal: Round 3 pairings</title><link>https://x.example/</link>
      <pubDate>Fri, 28 Aug 2026 05:00:00 +0000</pubDate></item>
    <item><title>[SAMPLE] YCS Montreal: Standings after round 3</title><link>https://x.example/</link>
      <pubDate>Fri, 28 Aug 2026 05:10:00 +0000</pubDate></item>
  </channel></rss>\`)`);

  assert.equal(groups.length, 1, 'both items group under one event despite the marker');
  assert.equal(groups[0].event, 'YCS Montreal');
  assert.deepEqual(groups[0].posts.map((p) => p.kind).sort(), ['pairings', 'standings']);
});

test('a leading coverage label is not mistaken for an event name', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.run(`eventNameFrom('Feature Match: A vs B', 'FALLBACK')`), 'FALLBACK');
  assert.equal(page.run(`eventNameFrom('Round 3: pairings', 'FALLBACK')`), 'FALLBACK');
  assert.equal(page.run(`eventNameFrom('YCS Montreal: Round 3 pairings', 'FALLBACK')`), 'YCS Montreal');
  assert.equal(page.run(`eventNameFrom('No colon here', 'FALLBACK')`), 'FALLBACK');
});

test('the shipped feed round-trips through the parser', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.run(`groupFeed(${JSON.stringify(fixture('feed.xml'))})`);

  assert.equal(groups.length, 4, 'four events reassembled from a flat post stream');
  // The gap that let a [Sample] prefix leak into every event name unnoticed.
  for (const g of groups) {
    assert.doesNotMatch(g.event, /^\[sample\]/i, `marker leaked into event name: ${g.event}`);
    for (const p of g.posts) {
      assert.doesNotMatch(p.title, /^\[sample\]/i, `marker leaked into post title: ${p.title}`);
    }
  }
  assert.ok(groups.some((g) => /^Remote Duel YCS/.test(g.event)),
    'and the real event name survives intact');
  assert.ok(!groups.some((g) => /^(feature|final) match$/i.test(g.event)), 'no bogus label-event');
  assert.ok(!groups.some((g) => g.event === 'Unsorted coverage'));
  assert.ok(groups[0].date >= groups[1].date, 'newest event first');
  assert.ok(groups.flatMap((g) => g.posts).every((p) => p.time), 'every post has a time');
});

test('malformed and partial feeds are handled, not crashed on', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.throws(() => page.run(`groupFeed('not xml <<<')`), /valid XML/);
  const sparse = page.run(
    `groupFeed('<rss><channel><item><title>only a title</title></item></channel></rss>')`);
  assert.equal(sparse.length, 1, 'an item missing every optional field still groups');
  const titleless = page.run(
    `groupFeed('<rss><channel><item><link>x</link></item></channel></rss>')`);
  assert.equal(titleless.length, 0, 'an item with no title is skipped');
});

/** Build a minimal feed from [title, category] pairs. */
const feedOf = (items) => `<?xml version="1.0"?><rss version="2.0"><channel>
  <title>t</title><link>l</link><description>d</description>
  ${items.map(([title, cat], i) => `<item><title>${title}</title>
    <link>https://x.example/${i}</link>
    ${cat ? `<category>${cat}</category>` : ''}
    <pubDate>Fri, 28 Aug 2026 0${i}:00:00 +0000</pubDate></item>`).join('')}
</channel></rss>`;

test('the event name is split off the post headline, not repeated in it', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([
    ['YCS Montreal: Round 3 pairings are up'],
    ['YCS Montreal: Feature match: Maliss against Ryzeal'],
  ]))})`);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].event, 'YCS Montreal');
  // Posts keep feed document order; only groups are sorted.
  assert.deepEqual(groups[0].posts.map((p) => p.title), [
    'Round 3 pairings are up',
    'Feature match: Maliss against Ryzeal',   // inner colon survives
  ]);
});

test('a headline with no event prefix is left alone', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // eventNameFrom falls back to the category here, so there is nothing to strip.
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([
    ['Feature match: A against B', 'YCS Montreal'],
  ]))})`);

  assert.equal(groups[0].event, 'YCS Montreal');
  assert.equal(groups[0].posts[0].title, 'Feature match: A against B',
    'the whole headline is kept when it carries no event prefix');
});

test('an event name is not mistaken for a partial prefix', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([
    ['YCS Montreal Regional: Round 1 pairings'],
  ]))})`);
  assert.equal(groups[0].event, 'YCS Montreal Regional');
  assert.equal(groups[0].posts[0].title, 'Round 1 pairings',
    'the full event name is removed, not a shorter lookalike');
});

test('a title that is only the event name keeps something to show', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([['YCS Montreal:']]))})`);
  assert.ok(groups[0].posts[0].title.length > 0, 'never renders an empty row');
});

test('classification reads the headline, so event names cannot leak into it', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // These names collide with roundFrom's patterns while still being valid event
  // names -- they do not *start* with a coverage label, so eventNameFrom accepts
  // them. Classifying the full title would read the round out of the event name:
  // "Championship Round 5" -> 5, "Invitational Top 8" -> "Top 8".
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([
    ['Championship Round 5: Standings after round 2'],
    ['Invitational Top 8: Standings after round 3'],
  ]))})`);

  const byEvent = Object.fromEntries(groups.map((g) => [g.event, g.posts[0]]));
  assert.equal(byEvent['Championship Round 5'].round, 2,
    'round comes from the headline, not the "Round 5" in the event name');
  assert.equal(byEvent['Invitational Top 8'].round, 3,
    'not "Top 8" picked up from the event name');
  for (const g of groups) assert.equal(g.posts[0].kind, 'standings');
});

test('a name that is a prefix but not followed by a colon is not stripped', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // No colon in the title, so the name comes from the category. Matching on the
  // name alone would eat the first character of the headline.
  const groups = page.json(`groupFeed(${JSON.stringify(feedOf([
    ['YCS Montreal Round 1 pairings', 'YCS Montreal'],
  ]))})`);

  assert.equal(groups[0].event, 'YCS Montreal');
  assert.equal(groups[0].posts[0].title, 'YCS Montreal Round 1 pairings',
    'the headline is untouched when there is no "name:" prefix to remove');
});

test('the shipped feed renders headlines without the event prefix', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const ev of page.json('EVENTS')) {
    for (const p of ev.posts) {
      assert.ok(!p.title.startsWith(ev.event),
        `"${p.title}" repeats its own event name`);
    }
  }
  // And the rendered rows agree.
  const rows = page.$$('.post__t').map((n) => n.textContent);
  assert.ok(rows.length > 0);
  assert.ok(rows.every((r) => !/^Remote Duel YCS/.test(r)), 'no row leads with the event name');
});

test('search still finds a post by its event name', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // The event name is gone from the title, so search must still match on it.
  page.run(`query = 'montreal'; renderEvents()`);
  const shown = page.$$('.event__title').map((n) => n.textContent);
  assert.ok(shown.some((s) => /Montreal/i.test(s)), 'matched on the event name');
  assert.ok(page.$$('.post').length > 0, 'and its posts are listed');
});

/* Who decides what a post is.
 *
 * classify() asks the same questions as the scraper, in the same order --
 * fixtures/kinds.json is read by both suites so they cannot drift. But it asks
 * them of a headline, and the scraper asked them of the title, the slug and
 * the table on the page. On 309 of the archive's posts that is the difference
 * between a kind and a shrug: Central America WCQ 2014 titles forty-eight
 * posts "WCQ" and puts everything in the slug, and read off the title alone
 * forty-five of them are news.
 */

const FEED_WITH = (extra) => `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk</title><link>https://dueldesk.reizu.dev/</link><description>d</description>
  <item><title>WCQ CA: WCQ</title>
    <link>https://yugiohblog.konami.com/wcq-ca-top-16-pairings/</link>
    <category>Pairings</category>${extra}
    <category domain="event">2014-wcq-ca</category>
    <pubDate>Sun, 06 Jul 2014 09:48:54 +0000</pubDate></item>
</channel></rss>`;

test('a feed item carries the kind the scraper read', async (t) => {
  const page = await loadPage({
    routes: { 'feed.xml': { status: 200,
      body: FEED_WITH('<category domain="kind">pairings</category>') } },
  });
  t.after(() => page.close());
  const post = page.json('EVENTS.flatMap(e => e.posts).find(p => /WCQ/.test(p.title)) ?? null');
  assert.equal(post.kind, 'pairings', 'the title alone says news');
});

test('a feed item without one is still classified from its headline', async (t) => {
  // An older feed, or one this scraper did not write.
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: FEED_WITH('') } } });
  t.after(() => page.close());
  const post = page.json('EVENTS.flatMap(e => e.posts).find(p => /WCQ/.test(p.title)) ?? null');
  assert.equal(post.kind, 'news', 'nothing else to go on');
});
