/* PLAYER — one Duelist's events, read out of the shard that holds their name.

   The archive knows 66,572 Duelists across 154,000-odd appearances, which is
   six and a half megabytes: far too much to load to answer one question. It is
   sharded into 512 files hashed on the name, so this page fetches exactly one
   of them, 13 to 21KB, whatever the name is.

   The rows in a shard carry only what this page cannot work out for itself --
   the event's slug, its format, the cut reached, the deck, whether they won.
   Everything a reader actually reads about the event, its name and date and
   place, comes from the manifest, which is one file for all of them. */

const SHARDS = 512;

const who = new URLSearchParams(location.search).get('name') || '';

const nameEl  = document.getElementById('who-h');
const noteEl  = document.getElementById('who-note');
const countEl = document.getElementById('pcount');
const listEl  = document.getElementById('played');
const sayEl   = document.getElementById('announce');

/* esc, safeUrl and applyTheme come from common.js, which both other pages
   load for the same reason. */

const say = (m) => { if (sayEl) sayEl.textContent = m; };

/* The same key archive.shard_of uses: the letters of the name and nothing
   else, so "P. Hoban" and "P Hoban" are one file's worth of question. Kept in
   step by test/players.test.mjs, which reads the shard the scraper wrote. */
async function shardOf(name){
  const flat = name.toLowerCase().replace(/[^a-z]+/g, '');
  const bytes = new TextEncoder().encode(flat);
  const hash = await crypto.subtle.digest('SHA-1', bytes);
  const hex = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('');
  return String(parseInt(hex.slice(0, 8), 16) % SHARDS).padStart(3, '0');
}

const day = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ''));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
};
const when = (iso) => {
  const d = day(iso);
  return d ? d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'}) : '';
};

/* How far they got, as a badge. The same words the round tables use, so a
   reader moving between them is not learning a second vocabulary. */
function place(row){
  if (row.won) return '<span class="place place--champion">champion</span>';
  /* Reaching the final is not reaching the Top 32, and both wore the same
     grey. Every other cut is the quiet one, which is what .place is by
     default. */
  if (row.cut === 'Final') return '<span class="place place--final">final</span>';
  if (row.cut) return `<span class="place place--top4">${esc(row.cut)}</span>`;
  return '';
}

function render(rows, events){
  const byslug = new Map(events.map((e) => [e.slug, e]));
  /* Newest first: a Duelist's most recent event is the one somebody looking
     them up is most likely to be asking about. */
  rows = rows.slice().sort((a, b) =>
    String(byslug.get(b.e)?.updated ?? '').localeCompare(String(byslug.get(a.e)?.updated ?? '')));

  const won = rows.filter((r) => r.won).length;
  countEl.textContent = `${rows.length} event${rows.length === 1 ? '' : 's'}`
    + (won ? `, ${won} won` : '');

  listEl.innerHTML = `<ol class="wins">` + rows.map((r) => {
    const e = byslug.get(r.e);
    return `<li class="win">
      <div class="win__who">
        <a class="win__n win__e" href="/?event=${encodeURIComponent(r.e)}">${
          esc(e?.event ?? r.e)}${heldAt(e?.location)}</a>
        ${place(r)}
        ${r.deck ? `<span class="win__d">${esc(r.deck)}</span>` : ''}
      </div>
      <div class="win__at">
        ${r.f ? `<span class="win__f">${esc(r.f)}</span>` : ''}
        <span class="win__w">${esc(when(e?.updated))}</span>
      </div>
    </li>`;
  }).join('') + `</ol>`;
}

function nobody(message){
  countEl.textContent = '';
  listEl.innerHTML = `<div class="empty"><h3>${esc(message)}</h3>
    <p>Search the <a href="/">coverage</a> or the <a href="/winners/">winners</a>.</p></div>`;
}

async function load(){
  if (!who.trim()){
    nameEl.textContent = 'Duelist';
    noteEl.textContent = 'No Duelist named.';
    return nobody('This page needs a name');
  }
  /* The name as asked for, shown before anything is fetched: the reader
     already typed it, and a heading that waits is a heading that flickers. */
  nameEl.textContent = who;
  noteEl.textContent = 'Every event the archive has them in.';
  document.title = `${who} — Duel Desk`;

  try {
    const [shard, manifest] = await Promise.all([
      shardOf(who).then((n) => fetch(`/players/${n}.json`, {cache: 'no-cache'})),
      fetch('/events.json', {cache: 'no-cache'}),
    ]);
    if (!shard.ok) throw new Error(`the player index responded ${shard.status}`);
    if (!manifest.ok) throw new Error(`events.json responded ${manifest.status}`);
    let rows = (await shard.json())[who];
    /* A spelling the archive folded away: the record is under the fuller name,
       in a different shard, and the index leaves a pointer where the old one
       hashes to. Followed once -- the fold only ever has one step, and a
       second hop would mean a chain nothing here should be repairing. */
    if (rows && !Array.isArray(rows) && rows.as){
        const to = rows.as;
        const next = await fetch(`/players/${await shardOf(to)}.json`, {cache: 'no-cache'});
        if (!next.ok) throw new Error(`the player index responded ${next.status}`);
        rows = (await next.json())[to];
        nameEl.textContent = to;
        document.title = `${to} — Duel Desk`;
        noteEl.textContent = `Every event the archive has them in. The coverage also spells them ${who}.`;
    }
    if (!rows || !rows.length){
      noteEl.textContent = 'The archive has nobody by that name.';
      return nobody('No Duelist by that name');
    }
    render(rows, (await manifest.json()).events || []);
    say(countEl.textContent);
  } catch (err) {
    noteEl.textContent = '';
    nobody(`Could not be loaded: ${err.message}`);
  }
}

applyTheme();
load();
