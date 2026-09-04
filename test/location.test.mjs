/**
 * Where an event was held.
 *
 * The winners list and a Duelist's page printed it beside every row — "YCS
 * Guatemala City · Guatemala City, Guatemala" — which says the same thing
 * twice, and only 44 of the archive's 190 events have a location at all, so it
 * was a column absent three quarters of the time and redundant the rest.
 *
 * It hangs off the event's name now. In the markup rather than in a title
 * attribute, because a title is not reliably reachable by a keyboard and is
 * unreadable on a phone: hidden the way this page hides anything from sight
 * and not from a screen reader, and shown to everyone else on hover and focus.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadPage } from './harness.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

test('a place is markup, and nothing is markup where there is no place', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.match(page.run(`where('Guatemala City, Guatemala')`),
    /^<span class="win__where">Guatemala City, Guatemala<\/span>$/);
  assert.equal(page.run(`where(null)`), '');
  assert.equal(page.run(`where('')`), '');
  assert.equal(page.run(`where(undefined)`), '');
});

test('a place out of the coverage cannot inject markup', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const html = page.run(`where('<img src=x onerror=alert(1)>')`);
  assert.equal(html.includes('<img'), false);
  assert.match(html, /&lt;img/);
});

test('the row no longer prints it, and the name carries it instead', async () => {
  // Both halves matter: out of the row, so it stops repeating the event's own
  // name, and still in the document, so a reader who cannot hover is not the
  // one reader it is kept from.
  //
  // Asked of the source. The harness waits on state the main page defines, so
  // it cannot load the winners page, and what is being asserted here is what
  // those two files render rather than how they behave.
  for (const file of ['winners.js', 'player.js']){
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.equal(source.includes('win__l"'), false, `${file} still prints the old column`);
    assert.match(source, /where\((r|e\?)\.location\)/,
      `${file} should hang the place off the name`);
  }
});

test('it is out of sight until the name is pointed at or focused', async (t) => {
  // Read off the stylesheet's own rules: jsdom parses them but resolves no
  // custom properties, so a computed value here says nothing about a colour
  // or a size.
  const page = await loadPage();
  t.after(() => page.close());
  const ruleFor = (sel) => page.run(`(() => {
    for (const sheet of document.styleSheets)
      for (const r of sheet.cssRules ?? [])
        if ((r.selectorText ?? '').split(',').map((s) => s.trim()).includes(${JSON.stringify(sel)}))
          return r.style.cssText;
    return null;
  })()`);
  const hidden = ruleFor('.win__where');
  assert.ok(hidden, '.win__where is styled');
  assert.match(hidden, /clip-path:\s*inset\(50%\)/, 'hidden from sight');
  assert.match(hidden, /position:\s*absolute/);

  assert.ok(ruleFor('.win__e:hover .win__where'), 'and shown on hover');
  assert.ok(ruleFor('.win__e:focus-visible .win__where'),
    'and on focus, which a keyboard is the only way to reach');
});

test('the winners search still knows where an event was', async (t) => {
  // The text left the row; it never left the data, and somebody looking for
  // "Bolivia" should still find the event held there.
  const source = readFileSync(join(ROOT, 'winners.js'), 'utf8');
  assert.match(source, /r\.location/, 'the search still reads it');
});
