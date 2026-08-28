import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadPage } from './harness.mjs';

const body = (page) => page.text('#round-body');
const select = (page, id) => { page.run(`selectRound('${id}')`); return body(page); };
const view = (page, v) => page.$(`[data-view="${v}"]`).click();

test('every round renders its own data', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const r1 = select(page, '1'), r5 = select(page, '5'), r12 = select(page, '12');
  assert.notEqual(r1, r12, 'R1 and R12 must not be identical');
  assert.notEqual(r5, r1);
  assert.notEqual(r5, r12);
  assert.match(r1, /0–0/, 'round 1 pairs players on 0–0 entering records');
  assert.doesNotMatch(r1, /9–2|10–1/, 'nobody has nine wins in round one');
});

test('standings records match the number of rounds actually played', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  view(page, 'standings');

  for (const id of ['3', '7', '11']) {
    page.run(`selectRound('${id}')`);
    const after = page.run(`roundOf('${id}').standingsAfter`);
    const recs = page.json(`roundOf('${id}').standings.map(s => s.record)`);
    assert.ok(recs.length > 0, `round ${id} shows standings`);
    for (const rec of recs) {
      assert.equal(rec.wins + rec.losses + (rec.draws ?? 0), after,
        `round ${id}: ${JSON.stringify(rec)} should total ${after} matches`);
    }
    assert.match(page.text('#round-body caption'), new RegExp(`after round ${after}`));
  }
});

test('the live round shows standings that already exist, never its own', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const live = page.json(`ROUNDS.find(r => r.state === 'live')`);
  const swissRounds = page.run(`formatOf(activeFormat).swissRounds`);
  assert.ok(live, 'the data marks a round live');

  if (live.phase === 'Swiss') {
    assert.equal(live.standingsAfter, Number(live.id) - 1,
      'its results do not exist yet, so standings come from the round before');
  } else {
    assert.equal(live.standingsAfter, swissRounds,
      'in the cut, Swiss is over and the standings are final');
  }
});

test('feature match differs by round and degrades when absent', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  view(page, 'feature');
  assert.notEqual(select(page, '6'), select(page, '12'));

  page.run(`ROUNDS.find(r => r.id === '6').feature = null`);
  page.run(`selectRound('6')`);
  assert.match(body(page), /No feature match/, 'a round without one says so');
});

test('rounds that have not started carry and show nothing', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const upcoming = page.json(`ROUNDS.filter(r => r.state === 'upcoming').map(r => r.id)`);
  assert.ok(upcoming.length > 0, 'the data still has at least one round ahead');

  for (const id of upcoming) {
    assert.match(select(page, id), /has not started/);
    assert.equal(page.run(`roundOf('${id}').pairings.length`), 0);
    assert.equal(page.run(`roundOf('${id}').standings.length`), 0);
    assert.ok(page.$$('[data-view]').every((b) => b.disabled),
      `${id}: the view control is disabled`);
  }
});

test('the current round comes from the data, not a hardcoded id', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.get('activeRound'), page.run(`ROUNDS.find(r => r.state === 'live').id`));

  // Mark a different round live and the page should land there instead.
  const moved = await loadPage({
    routes: {
      'rounds.json': async ({ calls }) => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        const f = d.formats[0];
        f.rounds.forEach((r) => { if (r.state === 'live') r.state = 'done'; });
        f.rounds.find((r) => r.id === '7').state = 'live';
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => moved.close());
  assert.equal(moved.get('activeRound'), '7', 'landed on whichever round the data marks live');
});

test('the hero is populated from the event data', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.text('#live-h'), page.get('eventInfo.event'));
  assert.match(page.text('#hero-meta'), /Duelists/);
  assert.match(page.text('#hero-meta'), /Swiss rounds/);
  const phase = page.run(`roundOf(activeRound).phase`);
  assert.match(page.text('#round-sub'), new RegExp(phase),
    'the subtitle names the phase the round actually belongs to');
});

test('the top cut is seeded from the final Swiss standings', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  const swiss = page.run(`formatOf(activeFormat).swissRounds`);
  const lastSwiss = page.run(`[...ROUNDS].reverse().find(r => r.phase === 'Swiss').id`);
  const finalStandings = page.json(`roundOf('${lastSwiss}').standings.map(s => s.name)`);
  const t8 = page.json(`roundOf('T8')`);
  assert.equal(t8.standingsAfter, swiss, 'the cut shows the final Swiss standings');

  const field = t8.pairings.flatMap((p) => [p.a, p.b]);
  assert.deepEqual([...field].sort(), [...finalStandings].sort(),
    'the Top 8 field is exactly the top eight of the final standings');

  // Standard single elimination: 1v8, 2v7, 3v6, 4v5.
  assert.deepEqual(t8.pairings.map((p) => [p.a, p.b]), [
    [finalStandings[0], finalStandings[7]],
    [finalStandings[1], finalStandings[6]],
    [finalStandings[2], finalStandings[5]],
    [finalStandings[3], finalStandings[4]],
  ]);
});

test('the Top 4 is drawn from Top 8 competitors and is bracket-correct', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const t8 = page.json(`roundOf('T8')`);
  const t4 = page.json(`roundOf('T4')`);

  const t8Field = new Set(t8.pairings.flatMap((p) => [p.a, p.b]));
  const t4Field = t4.pairings.flatMap((p) => [p.a, p.b]);
  assert.equal(t4Field.length, 4, 'two matches, four Duelists');
  assert.equal(new Set(t4Field).size, 4, 'all distinct');
  assert.ok(t4Field.every((n) => t8Field.has(n)), 'everyone came through the Top 8');
  assert.ok(t4.pairings.every((p) => p.a !== p.b));
});

test('cut results count toward a Duelist\'s record', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const swiss = page.run(`formatOf(activeFormat).swissRounds`);
  const cut = page.json(`ROUNDS.filter(r => r.phase === 'Top cut' && r.pairings.length)`);

  // Entering records grow by one match per cut round already played: the Top 8
  // enters on the Swiss record, the Top 4 one match later.
  cut.forEach((r, depth) => {
    for (const p of r.pairings) {
      for (const rec of [p.aRec, p.bRec]) {
        assert.equal(rec.wins + rec.losses + (rec.draws ?? 0), swiss + depth,
          `${r.label}: ${JSON.stringify(rec)} should total ${swiss + depth} matches`);
      }
    }
  });
});

test('winning a cut match adds a win, losing adds a loss', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const t8 = page.json(`roundOf('T8')`);
  const t4 = page.json(`roundOf('T4')`);

  const entering = new Map();
  for (const p of t8.pairings) {
    entering.set(p.a, p.aRec);
    entering.set(p.b, p.bRec);
  }

  for (const p of t4.pairings) {
    for (const [name, rec] of [[p.a, p.aRec], [p.b, p.bRec]]) {
      const before = entering.get(name);
      assert.equal(rec.wins, before.wins + 1,
        `${name} advanced, so their wins should go ${before.wins} -> ${before.wins + 1}`);
      assert.equal(rec.losses, before.losses,
        `${name} advanced, so their losses should stay at ${before.losses}`);
    }
  }
});

test('the standings table keeps the final Swiss placings during the cut', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const swiss = page.run(`formatOf(activeFormat).swissRounds`);
  const lastSwiss = page.run(`[...ROUNDS].reverse().find(r => r.phase === 'Swiss').id`);
  const afterSwiss = page.json(`roundOf('${lastSwiss}').standings`);

  for (const id of ['T8', 'T4']) {
    const shown = page.json(`roundOf('${id}').standings`);
    assert.deepEqual(shown, afterSwiss,
      `${id}: standings must stay the final Swiss ones, not absorb cut results`);
    for (const s of shown) {
      assert.equal(s.record.wins + s.record.losses + (s.record.draws ?? 0), swiss,
        `${id}: ${JSON.stringify(s.record)} should still total ${swiss}`);
    }
  }
});

test('the Final is genuinely unknown until the Top 4 is played', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const fin = page.json(`roundOf('F')`);
  assert.equal(fin.state, 'upcoming');
  assert.equal(fin.pairings.length, 0, 'its competitors do not exist yet');
  assert.match(select(page, 'F'), /has not started/);
});

test('the cut is presented as a bracket, not as Swiss tables', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  page.run(`selectRound('T8')`);
  page.$('[data-view="pairings"]').click();
  assert.match(page.text('#round-body caption'), /bracket/i,
    'the caption says bracket, not "top tables"');
  assert.match(page.text('#round-body thead'), /Match/,
    'the column is a match number, not a table number');
  assert.match(page.text('#round-sub'), /Top cut/, 'the subtitle names the phase');
  assert.doesNotMatch(page.text('#round-sub'), /Swiss/, 'and does not call it Swiss');

  // The count only appears while a round is live, so check the live cut round.
  page.run(`selectRound('T4')`);
  assert.match(page.text('#round-sub'), /Top cut · \d+ matches?\b/,
    'a cut is counted in matches, not tables');
  assert.doesNotMatch(page.text('#round-sub'), /\btables?\b/);
  page.run(`selectRound('T8')`);

  page.$('[data-view="standings"]').click();
  assert.match(page.text('#round-body caption'), /Final Swiss standings/,
    'standings are labelled final, so they do not look like they still move');
});

test('Swiss rounds keep their own presentation', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('7')`);
  page.$('[data-view="pairings"]').click();
  assert.match(page.text('#round-body caption'), /Top tables/);
  assert.match(page.text('#round-body thead'), /Table/);
  assert.match(page.text('#round-sub'), /Swiss/);
  assert.doesNotMatch(page.text('#round-sub'), /Top cut/);

});

test('every round declares which phase it belongs to', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const r of page.json('ROUNDS')) {
    assert.ok(['Swiss', 'Top cut'].includes(r.phase), `${r.label} has no valid phase`);
  }
  const cut = page.json(`ROUNDS.filter(r => r.phase === 'Top cut').map(r => r.label)`);
  assert.deepEqual(cut, ['Top 8', 'Top 4', 'Final']);
});

test('the page opens on the live cut round', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  assert.equal(page.get('activeRound'), 'T4', 'lands on whatever is in progress');
  assert.ok(page.$('#round-body tbody'), 'and renders its bracket immediately');
});

test('a live Swiss round is counted in tables, not matches', async (t) => {
  // The shipped data has no live Swiss round any more -- the event has reached
  // the cut -- so construct one rather than leave that branch untested.
  const page = await loadPage({
    routes: {
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        const f = d.formats[0];
        f.rounds.forEach((r) => { if (r.state === 'live') r.state = 'upcoming'; });
        f.rounds.find((r) => r.id === '9').state = 'live';
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());

  assert.equal(page.get('activeRound'), '9', 'landed on the live Swiss round');
  assert.match(page.text('#round-sub'), /Swiss · \d+ tables\b/,
    'Swiss is counted in tables');
  assert.doesNotMatch(page.text('#round-sub'), /\bmatches\b/);
});

test('a format selector appears, one button per tournament', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const names = page.json('eventInfo.formats.map(f => f.format)');
  assert.ok(names.length >= 2, 'the sample event runs more than one tournament');

  const buttons = page.$$('#formats [data-format]');
  assert.deepEqual(buttons.map((b) => b.dataset.format), names);
  assert.equal(page.$$('#formats [aria-pressed="true"]').length, 1);
  assert.equal(page.$('#formats').hidden, false);
});

test('a single-format event shows no selector, because there is no choice', async (t) => {
  const page = await loadPage({
    routes: {
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        d.formats = [d.formats[0]];
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());
  assert.equal(page.$('#formats').hidden, true);
});

test('switching format replaces the whole round set', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const [a, b] = page.json('eventInfo.formats.map(f => f.format)');

  const before = {
    rounds: page.get('ROUNDS.length'),
    swiss: page.run(`formatOf(activeFormat).swissRounds`),
    duelists: page.run(`formatOf(activeFormat).duelists`),
    table: page.text('#round-body tbody'),
  };
  page.$(`#formats [data-format="${b}"]`).click();

  assert.equal(page.get('activeFormat'), b);
  assert.notEqual(page.get('ROUNDS.length'), before.rounds, 'round counts differ per format');
  assert.notEqual(page.run(`formatOf(activeFormat).swissRounds`), before.swiss);
  assert.notEqual(page.text('#round-body tbody'), before.table, 'a different tournament');
  assert.equal(page.$$('#formats [aria-pressed="true"]').length, 1);
  assert.equal(page.$(`#formats [data-format="${b}"]`).getAttribute('aria-pressed'), 'true');

  page.$(`#formats [data-format="${a}"]`).click();
  assert.equal(page.get('ROUNDS.length'), before.rounds, 'switching back restores it');
});

test('the rail marks which edges have more track behind them', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());

  // (scrollLeft, scrollWidth, clientWidth) -> which edges are cut.
  const at = (l, sw, cw) => page.run(`overflowState(${l}, ${sw}, ${cw})`);

  assert.equal(at(0, 300, 300), 'none', 'everything fits, so nothing is cut');
  assert.equal(at(0, 900, 300), 'end', 'at the start there is only more to the right');
  assert.equal(at(600, 900, 300), 'start', 'at the end there is only more to the left');
  assert.equal(at(300, 900, 300), 'both', 'in the middle both edges are cut');
});

test('a fade is not drawn for a fractional scroll offset', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // Zoom and hidpi leave sub-pixel scroll positions on a rail that has not
  // moved; fading there would put a permanent smudge on a full track.
  assert.equal(page.run('overflowState(0.4, 300.3, 300)'), 'none');
  assert.equal(page.run('overflowState(0, 300.3, 300)'), 'none',
    'a rail a third of a pixel wider than its box has not overflowed');
  assert.equal(page.run('overflowState(0, 0, 0)'), 'none',
    'and a rail with no layout yet is not scrolled either');
});

test('the rail states its overflow so the fade can follow it', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const rail = page.$('#rail');
  assert.ok(rail.dataset.overflow, 'set on build, not left undefined until first scroll');

  // Nothing has layout under jsdom, so the honest answer is "nothing is cut".
  assert.equal(rail.dataset.overflow, 'none');
  page.run("selectRound(ROUNDS[0].id)");
  assert.equal(rail.dataset.overflow, 'none', 'and it is kept in step when a round is picked');
});

/* The next two encode a measurement taken in a real browser, because the thing
   they protect only exists once there is layout: with the rail 375px wide, the
   selected chip came to rest 36px clear of the trailing edge -- exactly the fade
   -- and 4px clear once scroll snapping was reintroduced, i.e. inside it. */
test('the scroll padding is tied to the fade, not a copy of its value', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const declared = page.window.getComputedStyle(page.$('#rail')).scrollPaddingInline;
  assert.match(declared, /var\(--fade\)/,
    'a hardcoded length here goes stale the moment --fade changes, and the ' +
    'selected round quietly starts resting under the fade again');
});

test('the rail does not scroll-snap', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const snap = page.window.getComputedStyle(page.$('#rail')).scrollSnapType;
  assert.ok(!snap || snap === 'none',
    'snapping overrides the scroll padding: scroll-snap-align:start pulls a ' +
    'chip to the padded start edge, pushing the selected one into the far fade');
});

/* The badge is the page's only claim about whether any of what it shows is
   real, so both directions are failures worth naming: hiding it over invented
   records passes them off as coverage, and showing it over real ones tells a
   reader to ignore results that actually happened. */
function withRounds(transform) {
  return {
    routes: {
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        transform(d);
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  };
}

/* Real coverage is indexed and linked, never rehosted. The page shows Konami's
   headlines, so each one has to be a way to reach the post it names -- that is
   the whole basis on which this publishes anything at all. */
function withFeed(xml) {
  return { routes: { 'feed.xml': { status: 200, body: xml } } };
}

const REAL_FEED = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk — YCS Montréal</title>
  <link>https://dueldesk.reizu.dev/</link>
  <description>Indexed from Konami's official event coverage.</description>
  <item>
    <title>YCS Montréal: Round 3 Pairings (Genesys Format)</title>
    <link>https://yugiohblog.konami.com/2026/ycs/round-3/</link>
    <category>Pairings</category>
    <pubDate>Sun, 16 Aug 2026 18:07:30 +0000</pubDate>
    <description>Pairings from YCS Montréal, published by Konami.</description>
  </item>
</channel></rss>`;

test('a real headline links to the post it names', async (t) => {
  const page = await loadPage(withFeed(REAL_FEED));
  t.after(() => page.close());
  const link = page.$('#events a.post__t');
  assert.ok(link, 'the headline is not a link');
  assert.equal(link.getAttribute('href'), 'https://yugiohblog.konami.com/2026/ycs/round-3/');
  assert.match(link.getAttribute('rel'), /noreferrer/);
});

test('a headline pointing at this site is not made a link', async (t) => {
  // The sample feed points every item at our own homepage. A link there
  // reloads the page under the reader and leads nowhere.
  const page = await loadPage(withFeed(
    REAL_FEED.replace('https://yugiohblog.konami.com/2026/ycs/round-3/',
                      'https://dueldesk.reizu.dev/')));
  t.after(() => page.close());
  assert.equal(page.$('#events a.post__t'), null);
  assert.ok(page.$('#events span.post__t'), 'still rendered, just not as a link');
});

test('an unusable link is not made a link', async (t) => {
  const page = await loadPage(withFeed(
    REAL_FEED.replace('https://yugiohblog.konami.com/2026/ycs/round-3/',
                      'http://[unparseable')));
  t.after(() => page.close());
  assert.equal(page.$('#events a.post__t'), null);
  assert.ok(page.$('#events span.post__t'), 'the headline still shows');
});

/* Every element hidden by attribute needs its class checked: an author rule
   setting display beats the UA sheet's [hidden]{display:none}, and the element
   stays on screen while every test that asks `.hidden` says it is gone. This
   has been wrong three times in this file, most recently on the badge that
   claims an event is live. */
function withStaleFeed() {
  return {
    routes: {
      'feed.xml': async () => {
        const { readFileSync } = await import('node:fs');
        const xml = readFileSync(new URL('../test/fixtures/feed.xml', import.meta.url), 'utf8');
        // Twelve days old, which is what a finished event looks like.
        return { status: 200, body: xml.replace(
          /<lastBuildDate>.*?<\/lastBuildDate>/,
          '<lastBuildDate>Sun, 16 Aug 2026 18:07:30 +0000</lastBuildDate>') };
      },
    },
  };
}

test('a finished event does not claim to be live', async (t) => {
  const page = await loadPage(withStaleFeed());
  t.after(() => page.close());
  const tag = page.$('#livetag');
  assert.equal(tag.hidden, true, 'nothing in the feed is recent');
  assert.equal(page.window.getComputedStyle(tag).display, 'none',
    'the attribute alone does not hide it: .livetag sets display:inline-flex, ' +
    'which is how LIVE NOW came to sit over an event twelve days finished');
});

test('nothing hidden by attribute is still displayed', async (t) => {
  const page = await loadPage(withStaleFeed());
  t.after(() => page.close());
  const offenders = ['livetag', 'demo', 'formats']
    .map((id) => page.$('#' + id))
    .filter((el) => el && el.hidden &&
                    page.window.getComputedStyle(el).display !== 'none')
    .map((el) => el.id);
  assert.deepEqual(offenders, [], 'hidden in the DOM but still painted');
});

/* A scraped feature post is prose and photographs: it names two Duelists and
   nothing else structured. The panel has to show that without inventing the
   rest, and without printing the punctuation that would have joined them. */
function withFeature(feature) {
  return withRounds((d) => {
    const f = d.formats[0];
    const r = f.rounds.find((x) => x.pairings.length) || f.rounds[0];
    r.feature = feature;
    d.__roundId = r.id;
  });
}

const SCRAPED_FEATURE = {
  a: { name: 'Adrien Racek', deck: null, record: null },
  b: { name: 'Oliver Martin Ernst Denk', deck: null, record: null },
  note: 'Feature match coverage published by Konami.',
  source: 'https://yugiohblog.konami.com/2026/ycs/feature/',
};

test('a feature match with no deck or record prints neither', async (t) => {
  const page = await loadPage(withFeature(SCRAPED_FEATURE));
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.feature).id); activeView='feature'; renderRound();`);
  const text = page.text('#round-body');
  assert.match(text, /Adrien Racek/);
  assert.doesNotMatch(text, /·/, 'the separator has nothing to separate');
  assert.doesNotMatch(text, /\?–\?/, 'an unknown record is omitted, not printed');
  assert.equal(page.$$('#round-body .feature__side p').length, 0,
    'no empty paragraph either: a blank line under the name is still a line');
});

test('a feature match links to the coverage it summarises', async (t) => {
  const page = await loadPage(withFeature(SCRAPED_FEATURE));
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.feature).id); activeView='feature'; renderRound();`);
  const link = page.$('#round-body .feature__note a');
  assert.ok(link, 'no link to the source post');
  assert.equal(link.getAttribute('href'), SCRAPED_FEATURE.source);
});

test('a feature match that does know the deck still shows it', async (t) => {
  const page = await loadPage(withFeature({
    ...SCRAPED_FEATURE,
    a: { name: 'Ada', deck: 'Snake-Eye', record: {wins: 5, losses: 1, draws: 0, confidence: 'derived'} },
  }));
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.feature).id); activeView='feature'; renderRound();`);
  const text = page.text('#round-body');
  assert.match(text, /Snake-Eye/);
  assert.match(text, /5–1/);
});

/* One tournament's coverage at a time, matching the round track. A post with no
   format is about the event rather than one of its tournaments, and stays. */
const MIXED_FEED = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Duel Desk — YCS Montréal</title>
  <link>https://dueldesk.reizu.dev/</link>
  <description>Indexed from Konami's official event coverage.</description>
  <item><title>YCS Montréal: Round 3 Pairings (Advanced Format)</title>
    <link>https://yugiohblog.konami.com/a/</link><category>Pairings</category>
    <category domain="format">Advanced</category>
    <pubDate>Sun, 16 Aug 2026 18:00:00 +0000</pubDate></item>
  <item><title>YCS Montréal: Genesys Format Round 4 Feature Match: A vs. B</title>
    <link>https://yugiohblog.konami.com/b/</link><category>Feature match</category>
    <category domain="format">Genesys</category>
    <pubDate>Sun, 16 Aug 2026 17:00:00 +0000</pubDate></item>
  <item><title>YCS Montréal: Doors open at 9am</title>
    <link>https://yugiohblog.konami.com/c/</link><category>News</category>
    <pubDate>Sun, 16 Aug 2026 16:00:00 +0000</pubDate></item>
</channel></rss>`;

test('one tournament is one event, however its posts are titled', async (t) => {
  // A deck list post has no colon and a feature match has its own, so grouping
  // on the title alone turned one tournament into eight events.
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: MIXED_FEED } } });
  t.after(() => page.close());
  assert.deepEqual(page.json('EVENTS.map(e => e.event)'), ['YCS Montréal']);
});

test('the format selector filters the coverage list', async (t) => {
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: MIXED_FEED } } });
  t.after(() => page.close());
  const shown = () => page.$$('#events .post__t').map((n) => n.textContent);

  page.run(`selectFormat('Advanced')`);
  const adv = shown();
  assert.ok(adv.some((t) => /Round 3 Pairings/.test(t)), 'its own pairings');
  assert.ok(!adv.some((t) => /Feature Match/.test(t)), 'not the other tournament');

  page.run(`selectFormat('Genesys')`);
  const gen = shown();
  assert.ok(gen.some((t) => /Feature Match/.test(t)));
  assert.ok(!gen.some((t) => /Round 3 Pairings/.test(t)));
});

test('a post belonging to no format is always shown', async (t) => {
  const page = await loadPage({ routes: { 'feed.xml': { status: 200, body: MIXED_FEED } } });
  t.after(() => page.close());
  for (const f of ['Advanced', 'Genesys']) {
    page.run(`selectFormat('${f}')`);
    assert.ok(page.$$('#events .post__t').some((n) => /Doors open/.test(n.textContent)),
      `the announcement disappeared under ${f}`);
  }
});

test('a single-format event filters nothing away', async (t) => {
  // Nothing to choose between, and if the feed and the round data disagreed on
  // the name, filtering on it would empty the list for no reason.
  const page = await loadPage({
    routes: {
      'feed.xml': { status: 200, body: MIXED_FEED },
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        d.formats = [d.formats[0]];
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());
  assert.equal(page.$('#formats').hidden, true, 'no selector');
  assert.equal(page.$$('#events .post__t').length, 3, 'all three posts remain');
});

/* Deck types are published for the cut and never for Swiss, so the columns have
   to come and go with the data rather than sit empty on every Swiss round. */
function withPairings(roundId, pairings) {
  return withRounds((d) => {
    const r = d.formats[0].rounds.find((x) => x.id === roundId) || d.formats[0].rounds[0];
    r.pairings = pairings;
  });
}

test('a cut pairing shows the deck each Duelist brought', async (t) => {
  const page = await loadPage(withPairings('T8', [{
    table: 1, a: 'Ada', aDeck: 'Mitsurugi', aRec: {wins: 12, losses: 1, draws: 0, confidence: 'derived'},
    b: 'Bo', bDeck: 'Elfnote', bRec: {wins: 11, losses: 2, draws: 0, confidence: 'derived'},
  }]));
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.pairings.some(p => p.aDeck)).id); activeView='pairings'; renderRound();`);
  const head = page.$$('#round-body thead th').map((n) => n.textContent);
  assert.deepEqual(head, ['Match', 'Duelist', 'Deck', 'Record', 'Duelist', 'Deck', 'Record']);
  const text = page.text('#round-body tbody tr');
  assert.match(text, /Mitsurugi/);
  assert.match(text, /Elfnote/);
});

test('a Swiss round with no decks grows no deck columns', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound(ROUNDS.find(r => r.phase !== 'Top cut' && r.pairings.length).id); activeView='pairings'; renderRound();`);
  const head = page.$$('#round-body thead th').map((n) => n.textContent);
  assert.ok(!head.includes('Deck'), `empty columns on every Swiss round: ${head}`);
});

test('a cut round renders the standings it points at', async (t) => {
  // The data carries no copy, so if the page did not follow standingsAfter the
  // Standings tab of every bracket round would be empty.
  const page = await loadPage(withRounds((d) => {
    const f = d.formats[0];
    for (const r of f.rounds) if (r.phase === 'Top cut') r.standings = [];
  }));
  t.after(() => page.close());
  const cut = page.json(`ROUNDS.filter(r => r.phase === 'Top cut').map(r => r.id)`);
  assert.ok(cut.length, 'no cut rounds in the fixture');
  page.run(`selectRound('${cut[0]}'); activeView='standings'; renderRound();`);
  assert.ok(page.$$('#round-body tbody tr').length > 0,
    'the reference was not followed');
});

test('the page asks not to be indexed', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // The site is public because Pages is, not because it is meant to be found.
  // Duelists should not turn up here searching for their own records.
  const meta = page.$('meta[name="robots"]');
  assert.ok(meta, 'no robots meta tag');
  assert.match(meta.getAttribute('content'), /noindex/);
});

test('sample data is badged as sample data', async (t) => {
  const page = await loadPage(withRounds((d) => { d.sample = true; }));
  t.after(() => page.close());
  assert.equal(page.$('#demo').hidden, false);
  assert.equal(page.window.getComputedStyle(page.$('#demo')).display, 'inline-block');
});

test('real coverage is not badged as sample data', async (t) => {
  const page = await loadPage(withRounds((d) => { d.sample = false; }));
  t.after(() => page.close());
  assert.equal(page.$('#demo').hidden, true);
  assert.equal(page.window.getComputedStyle(page.$('#demo')).display, 'none',
    'the attribute alone does not hide it: .demo sets display:inline-block');
});

test('a file that does not say what it is is not treated as sample', async (t) => {
  // It is also rejected by check-rounds.py before it can be deployed. This
  // pins the page's own behaviour if one ever reaches it: the badge is a
  // positive claim, so absence of the claim is not the claim.
  const page = await loadPage(withRounds((d) => { delete d.sample; }));
  t.after(() => page.close());
  assert.equal(page.$('#demo').hidden, true);
});

test('a truthy value that is not true does not count', async (t) => {
  const page = await loadPage(withRounds((d) => { d.sample = 'yes'; }));
  t.after(() => page.close());
  assert.equal(page.$('#demo').hidden, true, 'exactly true, not merely truthy');
});

test('the format selector leads the track header', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const head = page.$('.track__head');
  const kids = [...head.children].map(e => e.id || e.className);

  assert.deepEqual(kids, ['formats', 'track-h', 'track__hint'],
    'first in the row, so it lines up with the rail edge below it');
  assert.equal(page.$('#formats').parentElement, head,
    'and in the header row, not on one of its own, which cost a band of ' +
    'empty space for one small control');
});

test('the hero meta follows the selected format', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const [, b] = page.json('eventInfo.formats.map(f => f.format)');
  const before = page.text('#hero-meta');
  page.$(`#formats [data-format="${b}"]`).click();
  const after = page.text('#hero-meta');

  assert.notEqual(after, before, 'field size and round count are per format');
  assert.doesNotMatch(after, new RegExp(b),
    'the selector below already names it; saying it here too printed it twice');
  assert.ok(after.includes(String(page.run('formatOf(activeFormat).swissRounds'))),
    'the Swiss round count shown is this format\'s');
  assert.ok(after.includes(page.run('formatOf(activeFormat).duelists.toLocaleString()')),
    'and so is the field size');
});

test('with one format the meta names it, since no selector does', async (t) => {
  const page = await loadPage({
    routes: {
      'rounds.json': async () => {
        const { readFileSync } = await import('node:fs');
        const d = JSON.parse(readFileSync(new URL('../test/fixtures/rounds.json', import.meta.url), 'utf8'));
        d.formats = [d.formats[0]];
        return { status: 200, body: JSON.stringify(d) };
      },
    },
  });
  t.after(() => page.close());

  const el = page.$('#formats');
  assert.equal(el.hidden, true, 'no selector for a single format');
  /* The hidden attribute alone does not hide it: .formats sets display:flex,
     and an author rule beats the UA sheet's [hidden]{display:none}. Without a
     matching author rule the empty bordered box stays on the page. */
  assert.equal(page.window.getComputedStyle(el).display, 'none',
    'and it is actually not displayed, not merely marked hidden');
  assert.match(page.text('#hero-meta'), /Format/,
    'so the meta is the only thing that can state it');
  assert.match(page.text('#hero-meta'),
    new RegExp(page.json('eventInfo.formats[0].format')));
});

test('the format is stated exactly once', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const name = page.json('eventInfo.formats[0].format');
  const inMeta = page.text('#hero-meta').includes(name);
  const inSelector = page.$$('#formats [data-format]').some(b => b.textContent === name);
  assert.ok(inMeta !== inSelector,
    'exactly one of the meta line and the selector names the format');
});

test('switching format lands on that tournament, not a stale round id', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const [, b] = page.json('eventInfo.formats.map(f => f.format)');

  // Sit on a round the other format may not have.
  page.run(`selectRound('12')`);
  const was = page.get('activeRound');
  page.$(`#formats [data-format="${b}"]`).click();

  const now = page.get('activeRound');
  assert.ok(page.run(`ROUNDS.some(r => r.id === activeRound)`),
    `landed on ${now}, which must exist in ${b}`);
  assert.ok(page.$('#round-body'), 'and the panel rendered');
  assert.notEqual(page.$('#round-body').innerHTML, '', 'with content');
});

test('the round track rebuilds for the new format', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const [, b] = page.json('eventInfo.formats.map(f => f.format)');
  const before = page.$$('.chip').length;
  page.$(`#formats [data-format="${b}"]`).click();
  const after = page.$$('.chip').length;

  assert.equal(after, page.get('ROUNDS.length'), 'one chip per round of the active format');
  assert.notEqual(after, before, 'the two tournaments have different lengths');
  assert.equal(page.$$('.chip[aria-selected="true"]').length, 1);
  assert.equal(page.$$('.chip').filter((c) => c.tabIndex === 0).length, 1);
});

test('rounds carry an explicit order, so one array holds Swiss and cut', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const f of page.json('eventInfo.formats')) {
    const orders = f.rounds.map((r) => r.order);
    assert.ok(orders.every((o) => Number.isInteger(o)), `${f.format}: every round has an order`);
    assert.deepEqual(orders, [...orders].sort((x, y) => x - y), `${f.format}: already in order`);
    // The Final has no number to parse, which is why order is stored.
    const fin = f.rounds.find((r) => r.label === 'Final');
    const t4 = f.rounds.find((r) => r.label === 'Top 4');
    assert.ok(fin.order > t4.order, `${f.format}: Final sorts after Top 4`);
  }
});

test('switching format lands on that tournament\'s current round, not the same number', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const [, b] = page.json('eventInfo.formats.map(f => f.format)');

  // Round 5 exists in both tournaments, so nothing forces a reseed. The two
  // are at different stages, so the reader should land on what is live in the
  // format they switched to rather than an arbitrary same-numbered round.
  page.run(`selectRound('5')`);
  assert.equal(page.get('activeRound'), '5');

  page.$(`#formats [data-format="${b}"]`).click();
  assert.ok(page.run(`ROUNDS.some(r => r.id === '5')`), 'round 5 exists here too');
  assert.notEqual(page.get('activeRound'), '5',
    'a format switch is a tournament switch: land on what is current');
  const landed = page.run(`roundOf(activeRound)`);
  assert.equal(landed.state, 'live', 'which is the live round');
});

test('a fully known record reads W–L', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const f = (r, o) => page.run(`formatRecord(${JSON.stringify(r)}, ${JSON.stringify(o ?? {})})`);
  assert.equal(f({ wins: 12, losses: 1, draws: 0, confidence: 'derived' }), '12–1');
  assert.equal(f({ wins: 0, losses: 3, draws: 0, confidence: 'derived' }), '0–3');
});

test('an unknown half shows ?, which is a different claim from a blank', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const f = (r, o) => page.run(`formatRecord(${JSON.stringify(r)}, ${JSON.stringify(o ?? {})})`);
  // Wins are exact from points; losses need the rounds actually played.
  assert.equal(f({ wins: 11, losses: null, draws: 0, confidence: 'partial' }), '11–?');
  // Before ties were abolished, points alone determine neither.
  assert.equal(f({ wins: null, losses: null, draws: null, confidence: 'unknown' }), '?–?');
  assert.equal(f(null), '?–?', 'no record at all is still record-shaped');
  // The two uncertain states must stay distinguishable.
  assert.notEqual(f({ wins: 11, losses: null, draws: 0, confidence: 'partial' }),
                  f({ wins: null, losses: null, draws: null, confidence: 'unknown' }));
});

test('records follow the era: W–L–T before ties were abolished', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  const f = (r, o) => page.run(`formatRecord(${JSON.stringify(r)}, ${JSON.stringify(o ?? {})})`);
  const old = { drawsPossible: true };
  assert.equal(f({ wins: 10, losses: 2, draws: 1, confidence: 'derived' }, old), '10–2–1');
  assert.equal(f({ wins: 10, losses: 2, draws: 0, confidence: 'derived' }, old), '10–2–0',
    'a draws-era event keeps three parts even at zero draws');
  assert.equal(f(null, old), '?–?–?', 'and an unknown one has three unknowns');
  // A modern event never grows a third part.
  assert.equal(f({ wins: 12, losses: 1, draws: 0, confidence: 'derived' }), '12–1');
  // But a stray draw is never hidden, whatever the flag says.
  assert.equal(f({ wins: 10, losses: 2, draws: 1, confidence: 'derived' }), '10–2–1');
});

test('the standings table shows points alongside the record', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  page.run(`selectRound('7')`);
  page.$('[data-view="standings"]').click();
  assert.match(page.text('#round-body thead'), /Pts/, 'points are shown, being what the source publishes');
  const first = page.$$('#round-body tbody tr')[0];
  const cells = [...first.children].map((c) => c.textContent.trim());
  assert.match(cells[2], /^\d+–\d+$/, 'a derived record');
  assert.match(cells[3], /^\d+$/, 'and its points');
});

test('a less certain record is visibly muted', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  // Nothing in the sample data is uncertain, so make one so.
  page.run(`roundOf('7').standings[0].record = {wins: 4, losses: null, draws: 0, confidence: 'partial'}`);
  page.run(`selectRound('7')`);
  page.$('[data-view="standings"]').click();
  const cell = page.$('#round-body tbody .rec');
  assert.equal(cell.textContent.trim(), '4–?');
  assert.ok(cell.classList.contains('rec--partial'),
    'so a page of them does not read as confident data');
});

test('sample data is fully derived, so no ? appears today', async (t) => {
  const page = await loadPage();
  t.after(() => page.close());
  for (const f of page.json('eventInfo.formats')) {
    for (const r of f.rounds) {
      for (const s of r.standings ?? []) {
        assert.equal(s.record.confidence, 'derived', `${f.format} ${r.label} ${s.name}`);
      }
    }
  }
  page.run(`selectRound('7')`);
  page.$('[data-view="standings"]').click();
  assert.doesNotMatch(page.text('#round-body'), /\?/, 'invented data should never be uncertain');
});
