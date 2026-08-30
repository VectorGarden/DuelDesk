/**
 * The upcoming-events card.
 *
 * The blog covers a tournament while it happens and says nothing before it, so
 * the schedule comes from Konami's own listing and is read every few months.
 * What the page has to get right is that "upcoming" is a fact about when you
 * are looking, not about the file.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

const rows = (page) => page.$$('#upcoming .up');
const names = (page) => rows(page).map((n) => n.querySelector('strong').textContent.trim());

test('the card lists what is still to come', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.deepEqual(names(page),
    ['YCS Houston', 'YCS Orlando', 'YCS Santiago', 'North America Remote Duel YCS']);
});

test('an event that has already happened is not upcoming', async (t) => {
  // The file is written every few months and read every day, so this cannot be
  // decided when it is written: a file written in October and read in December
  // would call a November tournament upcoming.
  const page = await loadPage();
  t.after(() => page.close());
  assert.ok(!names(page).includes('YCS Long Past'),
    'the 2020 event in the fixture is not shown');
});

test('an event is still upcoming on its last day', async (t) => {
  /* Judged on the day it ends rather than the day it starts, so a tournament
     is not dropped from the list on the morning of its final round. */
  const page = await loadPage();
  t.after(() => page.close());
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const iso = (d) => d.toISOString().slice(0, 10);
  const running = { event: 'Happening now', location: 'Here',
    starts: iso(new Date(today.getTime() - 2 * 864e5)), ends: iso(today), url: '' };
  assert.deepEqual(page.json(`stillToCome(${JSON.stringify([running])}, today()).length`), 1);
});

test('a run with no end is judged on when it started', async (t) => {
  // The promotions run until further notice. A start with no end is not a
  // one-day event that finished the day it began.
  const page = await loadPage();
  t.after(() => page.close());
  assert.ok(names(page).length && !names(page).includes('A promotion with no end'),
    'shown only if it fits the four the card has room for');
  const page2 = page;
  assert.equal(page2.json(
    `stillToCome([{event:'x', starts:'2099-12-20', ends:null}], today()).length`), 1);
  assert.equal(page2.json(
    `stillToCome([{event:'x', starts:'2020-12-20', ends:null}], today()).length`), 0);
});

test('each event links to the page Konami publishes for it', async (t) => {
  // These used to be plain rows, correctly: the site had no destination to
  // offer. The listing gives every event its own entry, so now it has one.
  const page = await loadPage();
  t.after(() => page.close());
  const links = rows(page);
  assert.ok(links.length > 0);
  assert.ok(links.every((n) => n.tagName === 'A'), 'rendered as links');
  for (const a of links) {
    assert.match(a.getAttribute('href'), /^https:\/\/www\.yugioh-card\.com\//);
    assert.equal(a.getAttribute('rel'), 'external noreferrer',
      'leaks no referrer, like every other outbound link here');
  }
});

test('an event with no usable link stays a plain row', async (t) => {
  // An anchor promises a destination. Where there is none, the row says what it
  // knows and stops -- the same rule the coverage headlines follow.
  const page = await loadPage({
    routes: {
      'upcoming.json': { status: 200, body: JSON.stringify({
        fetched: '2026-08-30',
        events: [{ event: 'YCS Nowhere', location: 'Nowhere',
                   starts: '2099-01-01', ends: '2099-01-02', url: 'javascript:alert(1)' }] }) },
    },
  });
  t.after(() => page.close());
  const [row] = rows(page);
  assert.equal(row.tagName, 'DIV');
  assert.equal(row.querySelector('a'), null, 'and nothing focusable inside it');
});

test('the dates are shown the way a reader would write them', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const span = rows(page)[0].querySelector('span').textContent;
  assert.match(span, /16–18 Oct 2099/, 'one month named once');
  assert.match(span, /Houston, TX/, 'and where it is');
});

test('a range crossing a month names both', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // Whatever the runtime's en-GB calls September -- "Sep" here, "Sept" there --
  // the shape is what matters: both months named, the year once, at the end.
  const got = page.json(`whenText({starts:'2099-08-29', ends:'2099-09-13'})`);
  assert.match(got, /^29 Aug – 13 Sept? 2099$/);
});

test('the card degrades to its own link when the file will not load', async (t) => {
  // The footer link is where this data came from in the first place, so a
  // schedule nobody can fetch is not an error worth putting in front of anyone.
  const page = await loadPage({ routes: { 'upcoming.json': { status: 500 } } });
  t.after(() => page.close());
  assert.equal(rows(page).length, 0, 'no rows');
  assert.ok(page.$('#upcoming'), 'the container is still there');
  assert.ok(page.$$('.card__foot a[href*="yugioh-card.com"]').length,
    'and the link to the listing still answers the question');
});

test('a malformed file is handled, not crashed on', async (t) => {
  const page = await loadPage({
    routes: { 'upcoming.json': { status: 200, body: '{"events": "not a list"}' } },
  });
  t.after(() => page.close());
  assert.equal(rows(page).length, 0);
  assert.equal(page.get('coverageState'), 'ready', 'and the rest of the page is unaffected');
});
