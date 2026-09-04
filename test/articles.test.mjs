import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

/* The blocks the scraper stores, turned into elements. The whole reason they
   are stored as runs rather than as HTML is that the words are Konami's and
   the markup must be this site's, so the escaping is the point of the file. */

test('a run becomes text and its emphasis becomes a tag', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.equal(
    page.run(`blocksHtml([{t:'p', r:['He played ', {b:'Cyber Dragon'}, '.']}])`),
    '<p>He played <b>Cyber Dragon</b>.</p>');
  assert.equal(page.run(`blocksHtml([{t:'h', r:['Duel One']}])`), '<h2>Duel One</h2>');
  assert.equal(page.run(`blocksHtml([{t:'hr'}])`), '<hr>');
  assert.equal(page.run(`blocksHtml([{t:'q', r:['Quoted.']}])`),
    '<blockquote>Quoted.</blockquote>');
});

test('list items that came in a row become one list', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.equal(
    page.run(`blocksHtml([{t:'li',r:['A']},{t:'li',r:['B']},{t:'p',r:['After.']}])`),
    '<ul><li>A</li><li>B</li></ul><p>After.</p>');
  assert.equal(page.run(`blocksHtml([{t:'li',r:['Last']}])`), '<ul><li>Last</li></ul>',
    'a list that runs to the end is still closed');
});

test('an article cannot inject markup, whatever the archive holds', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([
    {t:'p', r:['<img src=x onerror="window.PWNED=1">']},
    {t:'p', r:[{b:'</b><script>window.PWNED=1</script>'}]},
    {t:'table', rows:[['<script>window.PWNED=1</script>']]}])`);
  assert.equal(html.includes('<img'), false, 'no injected element');
  assert.equal(html.includes('<script'), false, 'no injected script');
  assert.match(html, /&lt;img src=x/, 'the payload renders as visible text');
  assert.match(html, /&lt;\/b&gt;/, 'a tag inside an emphasised run is text too');
});

test('an emphasis the page does not know is text, not a tag', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.equal(page.run(`blocksHtml([{t:'p', r:[{script:'alert(1)'}]}])`),
    '<p>alert(1)</p>', 'an unknown key renders its text and no element');
});

test('a malformed block does not throw or render', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.equal(page.run(`blocksHtml(null)`), '');
  assert.equal(page.run(`blocksHtml([null, {t:'p'}, {t:'p', r:'not an array'}])`), '');
  assert.equal(page.run(`blocksHtml([{t:'table', rows:'nope'}])`),
    '<div class="article__scroll"><table></table></div>');
});

test('a Duelist named in the prose is a link to their page', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([{t:'p', r:[
    {who:'Julien Leo Kehon', t:'Kehon'}, ' opened with ', {b:'Kewl Tune Reco'}, '.']}])`);
  assert.match(html, /<a class="who" href="\/player\/\?name=Julien%20Leo%20Kehon"/);
  assert.match(html, />Kehon<\/a>/, 'the page says what the coverage wrote');
  assert.equal(html.includes('Julien Leo Kehon<'), false,
    'and not the name the archive files them under');
});

test('a linked name is escaped like everything else', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([{t:'p', r:[
    {who:'<img src=x onerror=alert(1)>', t:'<script>alert(1)</script>'}]}])`);
  assert.equal(html.includes('<img'), false);
  assert.equal(html.includes('<script'), false);
  assert.match(html, /&lt;script&gt;/);
});

test('a line the coverage wrote is a line on the page', async (t) => {
  // Konami writes a deck list one card to a line inside a single paragraph.
  // The archive keeps those breaks and the stylesheet renders them; nothing
  // else in the text does, so the source's own indentation stays collapsed.
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([{t:'p', r:['Monsters: 19\\n3 Ash Blossom']}])`);
  assert.match(html, /Monsters: 19\n3 Ash Blossom/);

  /* Read off the rule's own text: jsdom parses the stylesheet but does not
     surface every property through its typed accessors. */
  const rule = page.run(`(() => {
    for (const sheet of document.styleSheets)
      for (const r of sheet.cssRules ?? [])
        if ((r.selectorText ?? '') === '.article p') return r.style.cssText;
    return null;
  })()`);
  assert.match(rule ?? '', /white-space:\s*pre-line/,
    'the breaks are rendered rather than collapsed');
});

test('a name written in a heading is a link inside the heading', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([{t:'p', r:[
    {who:'Raymond Dai', t:'Raymond Dai', e:'b'}]}])`);
  assert.match(html, /^<p><b><a class="who"/, 'the emphasis wraps the link');
  assert.match(html, />Raymond Dai<\/a><\/b>/);
});

test('an emphasis the page does not know does not wrap a link', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const html = page.run(`blocksHtml([{t:'p', r:[
    {who:'Raymond Dai', t:'Raymond Dai', e:'script'}]}])`);
  assert.equal(html.includes('<script'), false);
  assert.match(html, /<a class="who"/);
});
