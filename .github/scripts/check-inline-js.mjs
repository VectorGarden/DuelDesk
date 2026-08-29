/**
 * Parse-check the page's JavaScript: every inline <script>, and every local
 * file one points at with src.
 *
 * None of it reaches a bundler or a linter on its own, and an HTML validator
 * treats a <script> body as opaque text. This pulls each block out and runs
 * `node --check` over it.
 *
 * The src files matter as much as the inline ones now that the behaviour lives
 * in app.js: a syntax error there is a page that renders its markup and does
 * nothing, which every other check in the build would call fine.
 */
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

const file = process.argv[2];
if (!file) {
  console.error('usage: check-inline-js.mjs <html-file>');
  process.exit(2);
}

const src = readFileSync(file, 'utf8');
const inline = [...src.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
  .map((m, i) => ({ what: `inline block ${i + 1}`, code: m[1] }));

/* Local files only. A src pointing off-site is somebody else's to parse, and
   this build has none of them. */
const linked = [...src.matchAll(/<script[^>]*\bsrc="([^"]+)"/gi)]
  .map((m) => m[1])
  .filter((href) => !/^(https?:)?\/\//.test(href))
  .map((href) => ({
    what: href,
    code: readFileSync(join(dirname(file), href), 'utf8'),
  }));

const blocks = [...inline, ...linked];
if (blocks.length === 0) {
  console.error(`${file}: no JavaScript found — expected at least one script`);
  process.exit(1);
}

const dir = mkdtempSync(join(tmpdir(), 'inline-js-'));
let failed = 0;

blocks.forEach(({ what, code }, i) => {
  const path = join(dir, `block-${i + 1}.js`);
  writeFileSync(path, code);
  const lines = code.trim().split('\n').length;
  try {
    execFileSync(process.execPath, ['--check', path], { stdio: 'pipe' });
    console.log(`  ok    ${what} (${lines} lines)`);
  } catch (err) {
    failed++;
    console.error(`  FAIL  ${what}`);
    console.error(String(err.stderr || err.message).replace(/^/gm, '        '));
  }
});

console.log(`${blocks.length} script(s) checked, ${failed} failed`);
process.exit(failed ? 1 : 0);
