import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

test('esc() neutralises markup in every field the renderer interpolates', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  assert.equal(page.run(`esc('<img src=x onerror=alert(1)>')`),
    '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(page.run(`esc('a"b\\'c&d')`), 'a&quot;b&#39;c&amp;d');
  assert.equal(page.run(`esc(null)`), '', 'null renders as empty, not "null"');
});

test('a hostile feed cannot inject nodes into the coverage list', async (t) => {
  const hostile = `<?xml version="1.0"?><rss version="2.0"><channel>
    <title>t</title><link>l</link><description>d</description>
    <item><title>YCS Evil: &lt;img src=x onerror="window.PWNED=1"&gt; pairings</title>
      <link>https://ok.example/1</link><pubDate>Sat, 01 Aug 2026 10:00:00 +0000</pubDate></item>
    </channel></rss>`;
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: hostile } } });
  t.after(() => page.close());

  assert.equal(page.$$('#events img').length, 0, 'no injected element');
  assert.equal(page.$$('#events script').length, 0);
  assert.equal(page.get('window.PWNED'), undefined, 'nothing executed');
  assert.match(page.text('#events'), /img src=x/, 'the payload renders as visible text');
});

test('safeUrl blocks dangerous schemes and keeps real ones', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  for (const bad of [
    'javascript:alert(1)', 'JavaScript:alert(1)', '  javascript:alert(1)',
    'java\tscript:alert(1)', 'java\nscript:alert(1)', 'jAvAsCrIpT:alert(1)',
    'data:text/html,<script>alert(1)</script>', 'vbscript:msgbox(1)', 'file:///etc/passwd',
  ]) {
    assert.equal(page.run(`safeUrl(${JSON.stringify(bad)})`), '#', `should block ${bad}`);
  }
  for (const good of ['https://konami.example/p/1', 'http://example.com/a', '/feed.xml', 'post/123']) {
    assert.match(page.run(`safeUrl(${JSON.stringify(good)})`), /^https?:/, `should allow ${good}`);
  }
  for (const inert of ['', '   ', '#', '#top']) {
    assert.equal(page.run(`safeUrl(${JSON.stringify(inert)})`), '#');
  }
  assert.equal(page.run(`safeUrl(null)`), '#');
  assert.equal(page.run(`safeUrl(undefined)`), '#');
});

test('groupFeed sanitises URLs at the boundary', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const urls = page.run(`
    groupFeed(\`<?xml version="1.0"?><rss version="2.0"><channel>
      <title>t</title><link>l</link><description>d</description>
      <item><title>E: Round 1 pairings</title><link>javascript:window.PWNED=1</link>
        <pubDate>Sat, 01 Aug 2026 10:00:00 +0000</pubDate></item>
      <item><title>E: Round 2 pairings</title><link>https://good.example/ok</link>
        <pubDate>Sat, 01 Aug 2026 11:00:00 +0000</pubDate></item>
    </channel></rss>\`).flatMap(g => g.posts).map(p => p.url)`);

  assert.ok(urls.includes('#'), 'hostile link neutralised');
  assert.ok(urls.includes('https://good.example/ok'), 'good link preserved');
});
