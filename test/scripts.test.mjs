/**
 * Every page's scripts, together.
 *
 * common.js is loaded beside app.js, read.js, winners.js and player.js, and
 * they are plain scripts rather than modules — so they share one scope. A name
 * declared twice is not a shadowing, it is a SyntaxError, and it takes the
 * whole file with it: `const where` in common.js met `function where` in
 * read.js and the reader page stopped rendering entirely.
 *
 * Nothing caught it. The harness loads index.html, so it exercises common.js
 * against app.js and against nothing else — three of the four pages had no
 * test that would so much as parse them.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (f) => readFileSync(join(ROOT, f), 'utf8');

/* Which script each page loads beside common.js, taken from the page itself
   rather than listed here: a page that starts loading another one is a page
   this test should already know about. */
const PAGES = ['index.html', 'read/index.html', 'winners/index.html', 'player/index.html'];

function scriptsOf(page){
  const html = read(page);
  return [...html.matchAll(/<script src="([^"]+)"/g)]
    .map((m) => m[1].replace(/^\//, '').replace(/\?.*$/, ''));
}

test('every page names common.js and one of its own', async () => {
  for (const page of PAGES){
    const scripts = scriptsOf(page);
    assert.ok(scripts.includes('common.js'), `${page} should load common.js`);
    assert.ok(scripts.length >= 2, `${page} loads ${scripts.length} scripts`);
  }
});

test('a page\'s scripts share a scope and must not collide in it', async () => {
  for (const page of PAGES){
    const source = scriptsOf(page).map(read).join('\n');
    assert.doesNotThrow(() => new Function(source),
      `${page}: its scripts do not parse together`);
  }
});

test('nothing common.js declares is declared again by a page', async () => {
  // The same fault said plainly, so a failure names the identifier rather
  // than only the file.
  const declared = (source) => new Set([
    ...[...source.matchAll(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]),
    ...[...source.matchAll(/^function\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]),
  ]);
  const shared = declared(read('common.js'));
  for (const page of PAGES){
    for (const script of scriptsOf(page)){
      if (script === 'common.js') continue;
      const clash = [...declared(read(script))].filter((name) => shared.has(name));
      assert.deepEqual(clash, [], `${script} redeclares what common.js already has`);
    }
  }
});
