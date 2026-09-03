import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

test('the tabpanel is wired to the selected tab at all times', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const panel = page.$('#round-body');

  assert.equal(panel.getAttribute('role'), 'tabpanel');
  for (const id of ['12', '3', 'T8', '1']) {
    page.run(`selectRound('${id}')`);
    const labelled = panel.getAttribute('aria-labelledby');
    assert.equal(labelled, `tab-${id}`);
    const target = page.$(`#${CSS_ESCAPE(labelled)}`);
    assert.ok(target, `aria-labelledby points at a real element for ${id}`);
    assert.equal(target.getAttribute('role'), 'tab');
    assert.equal(target.getAttribute('aria-selected'), 'true');
  }
});

const CSS_ESCAPE = (s) => s.replace(/([^\w-])/g, '\\$1');

test('no element ever points aria-labelledby at a missing id', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const el of page.$$('[aria-labelledby]')) {
    for (const id of el.getAttribute('aria-labelledby').split(/\s+/)) {
      assert.ok(page.document.getElementById(id), `dangling aria-labelledby: ${id}`);
    }
  }
  for (const el of page.$$('[aria-controls]')) {
    for (const id of el.getAttribute('aria-controls').split(/\s+/)) {
      assert.ok(page.document.getElementById(id), `dangling aria-controls: ${id}`);
    }
  }
});

test('the round track keeps a single roving tab stop', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const id of ['1', '6', '12', 'F']) {
    page.run(`selectRound('${id}')`);
    const chips = page.$$('.chip');
    assert.equal(chips.filter((c) => c.tabIndex === 0).length, 1, 'exactly one tabbable chip');
    assert.equal(chips.filter((c) => c.getAttribute('aria-selected') === 'true').length, 1);
    assert.equal(chips.find((c) => c.tabIndex === 0).dataset.id, id);
  }
});

test('arrow keys, Home and End move between rounds', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const key = (k) => page.run(
    `rail.dispatchEvent(new KeyboardEvent('keydown',{key:'${k}',bubbles:true,cancelable:true}))`);

  page.run(`selectRound('5')`);
  key('ArrowRight'); assert.equal(page.get('activeRound'), '6');
  key('ArrowLeft');  assert.equal(page.get('activeRound'), '5');
  key('Home');       assert.equal(page.get('activeRound'), page.run('ROUNDS[0].id'));
  key('End');        assert.equal(page.get('activeRound'), page.run('ROUNDS.at(-1).id'));
});

test('post rows offer no affordance the site cannot honour', async (t) => {
  // The rule was "no links at all", written when every sample item pointed at
  // this site's own homepage and a link would have gone nowhere. The site can
  // honour two things now -- a post it shows in place, and one it can only link
  // out to -- so the rule is that every link is one of those and not a third.
  const page = await loadPage();
  t.after(() => page.close());
  assert.ok(page.$$('.post').length > 0, 'posts are rendered');
  assert.ok(page.$$('.post').every((n) => n.tagName === 'DIV'));

  const rounds = new Set(page.json('ROUNDS.map(r => String(r.id))'));
  for (const a of page.$$('#events a')) {
    if (a.dataset.jumpRound !== undefined) {
      assert.ok(rounds.has(String(a.dataset.jumpRound)),
        `offers a jump to a round that is not here: ${a.dataset.jumpRound}`);
      assert.equal(a.getAttribute('href'), '#round-h',
        'a real href, so middle-click and no-JS still do something');
    } else if (a.getAttribute('href').startsWith('/')) {
      /* The third kind: a table this archive holds, in an event that is not
         the one on screen. It stays on the site. */
      const url = new URL(a.getAttribute('href'), 'https://x/');
      assert.ok(url.searchParams.get('event'), 'a link here names the event');
      assert.match(url.searchParams.get('view') ?? '', /^(pairings|standings)$/);
    } else {
      assert.match(a.getAttribute('href'), /^https?:/, 'links out, or not at all');
      assert.match(a.getAttribute('rel') ?? '', /noreferrer/);
    }
  }
});

test('scrollable tables are reachable by keyboard', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('12')`);
  const wrap = page.$('#round-body .tblwrap');
  assert.ok(wrap, 'a table is rendered');
  assert.equal(wrap.getAttribute('tabindex'), '0');
  assert.equal(wrap.getAttribute('role'), 'region');
  assert.ok(wrap.getAttribute('aria-label'), 'and is named');
});

test('the refresh claim is backed by an actual poll loop', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const copy = page.text('body');

  // This claim is only allowed because B2 made it true.
  assert.match(copy, /refreshes automatically/i);
  assert.equal(typeof page.get('pollOnce'), 'function', 'and there is a poll to back it');
  assert.ok(page.get('pollTimer') !== null, 'scheduled after boot');

  // These two were never made true and must stay gone.
  assert.doesNotMatch(copy, /updates on its own/i);
  assert.doesNotMatch(copy, /the moment it is posted/i);
});

test('liveness is derived from the data, not asserted in markup', async (t) => {
  const fresh = await loadPage();
  t.after(() => fresh.close());
  const anyLive = fresh.run(`EVENTS.some(e => e.live)`);
  assert.equal(fresh.$('#livetag').hidden, !anyLive, 'badge matches the data');

  // An old feed must not go on claiming "live now" forever.
  const stale = await loadPage({
    routes: {
      'feed.xml': async () => {
        const { readFileSync } = await import('node:fs');
        const xml = readFileSync(new URL('../test/fixtures/feed.xml', import.meta.url), 'utf8')
          .replace(/<lastBuildDate>[^<]*<\/lastBuildDate>/, '<lastBuildDate>Sun, 01 Feb 2026 14:02:00 +0000</lastBuildDate>')
          .replace(/<pubDate>[^<]*<\/pubDate>/g, '<pubDate>Sun, 01 Feb 2026 14:02:00 +0000</pubDate>');
        return { status: 200, body: xml };
      },
    },
  });
  t.after(() => stale.close());
  assert.ok(stale.run(`EVENTS.every(e => !e.live)`), 'nothing is live from an old feed');
  assert.equal(stale.$('#livetag').hidden, true, 'and the badge hides');
  assert.equal(stale.$$('#events .livetag').length, 0);
});
