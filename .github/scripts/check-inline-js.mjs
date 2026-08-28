/**
 * Parse-check every inline <script> in an HTML file.
 *
 * The whole site is one file, so its JavaScript never reaches a bundler or a
 * linter on its own. An HTML validator will not catch a syntax error inside a
 * <script> block either — it treats the contents as opaque text. This pulls
 * each block out and runs `node --check` over it.
 */
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const file = process.argv[2];
if (!file) {
  console.error('usage: check-inline-js.mjs <html-file>');
  process.exit(2);
}

const src = readFileSync(file, 'utf8');
// Inline scripts only — anything with src= is a external reference, not ours.
const blocks = [...src.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];

if (blocks.length === 0) {
  console.error(`${file}: no inline <script> blocks found — expected at least one`);
  process.exit(1);
}

const dir = mkdtempSync(join(tmpdir(), 'inline-js-'));
let failed = 0;

blocks.forEach((m, i) => {
  const code = m[1];
  // Line number of the block's opening tag, so errors map back to the HTML.
  const startLine = src.slice(0, m.index).split('\n').length;
  const path = join(dir, `block-${i + 1}.js`);
  writeFileSync(path, code);
  try {
    execFileSync(process.execPath, ['--check', path], { stdio: 'pipe' });
    console.log(`  ok    block ${i + 1} (${file}:${startLine}, ${code.trim().split('\n').length} lines)`);
  } catch (err) {
    failed++;
    console.error(`  FAIL  block ${i + 1} (${file}:${startLine})`);
    console.error(String(err.stderr || err.message).replace(/^/gm, '        '));
  }
});

console.log(`${blocks.length} inline script block(s) checked, ${failed} failed`);
process.exit(failed ? 1 : 0);
