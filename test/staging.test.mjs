/**
 * What the site is made of reaches the site.
 *
 * scripts/stage-site.sh copies an explicit list of files into the artifact,
 * which is right -- a repository holds scrapers and tests and fixtures, and
 * none of that belongs on a static host. The cost is that a file added to the
 * pages has to be added to that list as well, and forgetting is silent here:
 * every test passes, because every test reads the repository, where the file
 * is.
 *
 * It was not silent at deploy -- the artifact's own reference check refused
 * it, which is why the check exists -- but that is ten minutes and a halted
 * rebuild later. This asks the same question of the same list, here.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PAGES = ['index.html', 'read/index.html', 'player/index.html', 'winners/index.html'];

/* The list stage-site.sh copies, read out of the script rather than repeated
   here: a copy of it would pass while the real one was wrong. */
function staged(){
  const sh = readFileSync(join(ROOT, 'scripts/stage-site.sh'), 'utf8');
  const at = sh.indexOf('FILES=(');
  const held = sh.slice(at + 'FILES=('.length, sh.indexOf(')', at));
  return new Set(held.split(/\s+/).filter(Boolean));
}

test('every script and stylesheet a page asks for is staged', () => {
  const files = staged();
  const missing = [];
  for (const page of PAGES){
    const html = readFileSync(join(ROOT, page), 'utf8');
    for (const m of html.matchAll(/(?:src|href)="\/?([\w.-]+\.(?:js|css))"/g)){
      if (!files.has(m[1])) missing.push(`${page} asks for ${m[1]}`);
    }
  }
  assert.deepEqual(missing, [],
    'add it to FILES in scripts/stage-site.sh, or the artifact ships without it');
});

test('and nothing is staged that is not there', () => {
  // The other way round: a file dropped from the repository and left in the
  // list stages nothing and fails no test, until the copy does.
  const gone = [...staged()].filter((f) => {
    try { readFileSync(join(ROOT, f)); return false; } catch { return true; }
  });
  assert.deepEqual(gone, []);
});
