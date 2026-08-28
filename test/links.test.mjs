import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

test('no anchor in the page points nowhere', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const dead = page.$$('a[href="#"]').map((a) => a.textContent.trim());
  assert.deepEqual([...dead], [], 'every link must have a real destination');
});

test('every in-page fragment link resolves to an element that exists', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const fragments = page.$$('a[href^="#"]')
    .map((a) => a.getAttribute('href').slice(1))
    .filter(Boolean);
  assert.ok(fragments.length > 0, 'there are fragment links to check');
  for (const id of fragments) {
    assert.ok(page.document.getElementById(id), `#${id} has no target element`);
  }
});

test('external links are marked and use https', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const external = page.$$('a[href^="http"]');
  assert.ok(external.length > 0);
  for (const a of external) {
    const href = a.getAttribute('href');
    assert.match(href, /^https:\/\//, `${href} should be https`);
    assert.match(a.getAttribute('rel') ?? '', /noreferrer/,
      `${href} should not leak a referrer`);
  }
});

test('upcoming events are not links, since no page exists for them', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const items = page.$$('.up');
  assert.equal(items.length, 3);
  assert.ok(items.every((n) => n.tagName === 'DIV'), 'rendered as plain rows');
  assert.ok(items.every((n) => !n.querySelector('a,button,[tabindex]')),
    'and contain nothing focusable');
});

test('footer coverage links jump to the coverage section', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const links = page.$$('.foot a[href="#coverage"]');
  assert.ok(links.length >= 4, 'the coverage group points at the section');
  assert.ok(page.$('#coverage'), 'and the section exists');
});

test('a footer jump applies the filter it advertises', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  for (const kind of ['feature', 'deck', 'result']) {
    const link = page.$(`.foot a[data-jump="${kind}"]`);
    assert.ok(link, `a footer link exists for ${kind}`);
    link.click();

    assert.equal(page.get('filter'), kind, `${kind}: filter applied`);
    assert.equal(page.$(`[data-filter="${kind}"]`).getAttribute('aria-pressed'), 'true',
      `${kind}: the matching filter button reflects it`);
    assert.equal(page.$$('[data-filter][aria-pressed="true"]').length, 1,
      `${kind}: exactly one filter is active`);

    // Whatever is listed must genuinely be of that kind.
    const shown = page.$$('.post__k').map((n) => n.textContent);
    if (shown.length) {
      const expected = page.run(`kindOf('${kind}').label`);
      assert.ok(shown.every((l) => l === expected), `${kind}: only ${expected} rows shown`);
    }
  }
});

test('every advertised filter has posts behind it, so no jump lands on nothing', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  for (const kind of page.$$('.foot a[data-jump]').map((a) => a.dataset.jump)) {
    const count = page.run(
      `EVENTS.reduce((n,e) => n + e.posts.filter(p => p.kind === '${kind}').length, 0)`);
    assert.ok(count > 0, `the footer offers "${kind}" but the feed has none`);
  }
});

test('the jump does not preventDefault, so the fragment still navigates', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const link = page.$('.foot a[data-jump="deck"]');
  const ev = new page.window.MouseEvent('click', { bubbles: true, cancelable: true });
  link.dispatchEvent(ev);
  assert.equal(ev.defaultPrevented, false,
    'the browser must still handle the #coverage hop, so it works without JS too');
});
