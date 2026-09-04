/* ============================================================
   COMMON — what every page of this site needs
   ------------------------------------------------------------
   Two pages read the same archive: the coverage page and the
   winners list. Escaping and the theme are the same job on both,
   and a second copy of either is a second thing to get wrong.

   Loaded before the page's own script, which is a plain <script>
   too, so everything declared here is in scope there.
   ============================================================ */

/* Everything rendered through innerHTML goes through this first.
   Every name, headline and deck on the page came out of somebody
   else's markup, by way of a scraper. Escape at the boundary,
   always. */
const ESCAPES = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ESCAPES[c]);

/* A Duelist's name, as a link to their own page.

   Opened in a new tab, deliberately: a reader following a name out of a
   bracket is looking something up beside what they were reading, not leaving
   it, and coming back to a round they had scrolled to is worse than a tab
   they can close. rel="noopener" because a new tab given a handle back to
   this one can navigate it.

   Not everything in a name column is a Duelist. A bye and an unnamed seat are
   written "*** ***", and a name with no letters in it is nobody -- the same
   test records.is_placeholder makes on the other side. Teams do not link
   either: a team has no page, and its Duelists are linked individually.

   The name goes in the query string rather than the path so that no name
   needs escaping into a URL shape it does not fit: 66,000 of them include
   full stops, apostrophes, slashes and hashes. */
const playerLink = (name, written) => {
  /* `written` is what the words on the page should say, where that differs
     from the name the archive files them under: an article says "Kehon" and
     the page it links to is Julien Leo Kehon's. */
  const text = esc(written ?? name);
  if (!name || !/[A-Za-z]/.test(name)) return text;
  return `<a class="who" href="/player/?name=${encodeURIComponent(name)}"`
       + ` target="_blank" rel="noopener">${text}</a>`;
};

/* A post's prose, as blocks the scraper stored and this page turns into
   elements. Shared because the reader page renders them and the site may want
   them elsewhere; kept here rather than in either page's own script.

   The blog's own markup never gets this far. What the archive stores is runs
   of text and which of them are emphasised, so every character below goes
   through esc and every tag is one this file chose. */
const EMPHASIS = {b: 'b', i: 'i', u: 'u', s: 'sup'};

function runHtml(run){
  if (typeof run === 'string') return esc(run);
  if (!run || typeof run !== 'object') return '';
  /* A Duelist the coverage named, and the words it named them in -- inside
     whatever emphasis it wrote them in, where it wrote them in one. A deck
     list's heading is bold and holds the Duelist's name. */
  if (run.who){
    const link = playerLink(run.who, run.t);
    const tag = EMPHASIS[run.e];
    return tag ? `<${tag}>${link}</${tag}>` : link;
  }
  const [key, text] = Object.entries(run)[0] ?? [];
  const tag = EMPHASIS[key];
  return tag ? `<${tag}>${esc(text)}</${tag}>` : esc(text);
}

function blocksHtml(blocks){
  if (!Array.isArray(blocks)) return '';
  let html = '', list = false;
  for (const b of blocks){
    const runs = Array.isArray(b?.r) ? b.r.map(runHtml).join('') : '';
    /* List items arrive one at a time and a <ul> holds all of the ones that
       came in a row. */
    if (b?.t === 'li'){
      html += (list ? '' : '<ul>') + `<li>${runs}</li>`;
      list = true;
      continue;
    }
    if (list){ html += '</ul>'; list = false; }
    if (b?.t === 'hr') html += '<hr>';
    else if (b?.t === 'h') html += `<h2>${runs}</h2>`;
    else if (b?.t === 'q') html += `<blockquote>${runs}</blockquote>`;
    else if (b?.t === 'table'){
      const rows = Array.isArray(b.rows) ? b.rows : [];
      html += `<div class="article__scroll"><table>` + rows.map(
        row => `<tr>` + (Array.isArray(row) ? row : []).map(
          c => `<td>${esc(c)}</td>`).join('') + `</tr>`).join('') + `</table></div>`;
    }
    else if (runs) html += `<p>${runs}</p>`;
  }
  return html + (list ? '</ul>' : '');
}

/* ============================================================
   CARDS
   ------------------------------------------------------------
   What a card does, for a reader who does not already know.

   The store is 14,517 cards and 6.4MB of text, sharded into 512 files the
   same way the Duelists are: the page works out which file a name is in and
   fetches that one, about 13KB, rather than the whole of it.

   Keyed on the name with its punctuation and case taken out, because the
   coverage writes Maxx "C" with typographic quotes and prose that has been
   through a CMS is not where anybody should have to match an official
   spelling exactly. Kept in step with scraper/cards.py by
   test/cards.test.mjs, which reads the shards the scraper wrote.
   ============================================================ */
const CARD_SHARDS = 512;
const CARDS = new Map();          // shard name -> its cards, once fetched

/* The same key scraper/cards.normalise makes: letters and digits only. The
   curly quotes a CMS invents and the straight ones a keyboard has both go,
   and so do both kinds of dash, so neither has to be folded onto the other
   first. */
function cardKey(name){
  return String(name ?? '').normalize('NFKD')
    .toLowerCase().replace(/[^a-z0-9]+/g, '');
}

async function cardShardOf(key){
  const hash = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(key));
  const hex = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('');
  return String(parseInt(hex.slice(0, 8), 16) % CARD_SHARDS).padStart(3, '0');
}

/* The card, or null. Null is the ordinary answer: a bold run may be a heading
   -- "Duel 1", "Extra Deck: 15" -- and 11% of the emphasised mentions in the
   archive are not cards at all. Nothing is shown for those. */
async function lookupCard(name){
  const key = cardKey(name);
  if (!key) return null;
  const shard = await cardShardOf(key);
  if (!CARDS.has(shard)){
    try {
      /* Revalidated, not taken on trust. force-cache served whatever the
         browser had whatever the store said, so a rebuilt card file never
         reached anybody who had already read one -- which is how a deck
         export came back missing twelve cards that were sitting in the shard
         it had just asked for. */
      const res = await fetch(`/cards/${shard}.json`, {cache: 'no-cache'});
      CARDS.set(shard, res.ok ? await res.json() : {});
    } catch {
      /* A card that will not load is a card the reader does not get told
         about, which is where they were before. */
      CARDS.set(shard, {});
    }
  }
  return CARDS.get(shard)[key] ?? null;
}

/* Where an event was held, hung off its name rather than printed beside it.

   "YCS Guatemala City · Guatemala City, Guatemala" says the same thing twice,
   and only 44 of the archive's 190 events have a location at all -- so it was
   a column that was absent three quarters of the time and redundant the rest.

   In the markup rather than in a title attribute, because a title is not
   reliably reachable by a keyboard and is unreadable on a phone. Hidden the
   way the page hides anything from sight and not from a screen reader, and
   shown to everyone else on hover and on focus -- which the name already
   takes, being a link. */
const heldAt = (place) => place
  ? `<span class="win__where">${esc(place)}</span>`
  : '';

/* Every card's numbers, in one file and without a word of its text.

   A hover wants one card and fetches one shard of 13KB. An export wants a
   whole deck list, and the worst post in the archive names 642 cards across
   367 of the 512 shards -- 4.7MB in 367 requests to answer one button. Names
   and numbers alone are 517KB in one request, and 240KB of it over the wire.

   So the shards answer "what does this card do" and this answers "which card
   is this", and an export of any size asks only the second. */
let NUMBERS = null;

async function cardNumbers(){
  if (!NUMBERS){
    try {
      const res = await fetch('/cards/ids.json', {cache: 'no-cache'});
      NUMBERS = res.ok ? await res.json() : {};
    } catch {
      NUMBERS = {};
    }
  }
  return NUMBERS;
}

/* What a name resolves to, for the files that are made of numbers.
   [passcode] or [passcode, Konami id] -- 2% of the database has no second. */
function numbersFor(ids, name){
  const found = ids[cardKey(name)];
  if (!found) return null;
  return found[1] === undefined ? {id: found[0]} : {id: found[0], cid: found[1]};
}

/* ============================================================
   A ZIP, BY HAND
   ------------------------------------------------------------
   Sixty-three deck lists want to arrive as sixty-three files, and a .ydk has
   no way of holding more than one -- the format has no separator.

   Written here rather than fetched, because a zip of stored entries is a
   documented layout and about sixty lines: a header before each file, a
   directory of them at the end, and a CRC of each. Nothing is compressed --
   a deck list is a kilobyte and the saving would not pay for the code.

   The names carry accents and em dashes, so the UTF-8 flag is set. macOS's
   bundled unzip is an old Info-ZIP build that mishandles those whatever the
   flag says; Finder's own extractor, Python and every modern tool read them
   correctly.
   ============================================================ */
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++){
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(bytes){
  let c = 0xFFFFFFFF;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

/* [{name, text}] -> the bytes of a zip holding them. */
function zipOf(files){
  const encoder = new TextEncoder();
  const parts = [];
  const directory = [];
  let at = 0;
  for (const {name, text} of files){
    const named = encoder.encode(name);
    const data = encoder.encode(text);
    const crc = crc32(data);

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);              // the version that can read it
    local.setUint16(6, 0x0800, true);          // the name is UTF-8
    local.setUint16(8, 0, true);               // stored, not deflated
    local.setUint16(12, 0x21, true);           // a date, because there must be one
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, named.length, true);
    parts.push(new Uint8Array(local.buffer), named, data);

    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014b50, true);
    entry.setUint16(4, 20, true);
    entry.setUint16(6, 20, true);
    entry.setUint16(8, 0x0800, true);
    entry.setUint16(10, 0, true);
    entry.setUint16(14, 0x21, true);
    entry.setUint32(16, crc, true);
    entry.setUint32(20, data.length, true);
    entry.setUint32(24, data.length, true);
    entry.setUint16(28, named.length, true);
    entry.setUint32(42, at, true);
    directory.push(new Uint8Array(entry.buffer), named);
    at += 30 + named.length + data.length;
  }
  const listed = directory.reduce((n, chunk) => n + chunk.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, listed, true);
  end.setUint32(16, at, true);

  const all = [...parts, ...directory, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((n, chunk) => n + chunk.length, 0));
  let put = 0;
  for (const chunk of all){ out.set(chunk, put); put += chunk.length; }
  return out;
}

/* Two decks in a post can be called the same thing -- a name is not an
   identifier -- and two files in a zip cannot.

   Not "named": app.js has one of those, and these files share a scope. */
function eachNamedOnce(files){
  const seen = new Map();
  return files.map(({name, text}) => {
    const n = (seen.get(name) ?? 0) + 1;
    seen.set(name, n);
    return {name: n === 1 ? name : name.replace(/(\.[^.]+)$/, ` (${n})$1`), text};
  });
}

function offsite(url){
  /* Every url here has been through safeUrl(), so it is either an http(s) URL or
     the inert '#'. That is why this needs no guard of its own: '#' resolves
     against this page and compares equal, and nothing reaching here can throw. */
  return new URL(url, location.href).host !== location.host;
}

function safeUrl(raw){
  const value = String(raw ?? '').trim();
  /* Empty and fragment-only inputs resolve to the site's own homepage once the
     URL constructor gets hold of them, which would turn a feed item with no
     <link> into a working link somewhere unrelated. Keep those inert. */
  if (!value || value.startsWith('#')) return '#';
  try {
    const u = new URL(value, location.origin);
    return (u.protocol === 'https:' || u.protocol === 'http:') ? u.href : '#';
  } catch {
    return '#';                     // unparseable -> inert
  }
}

/* ============================================================
   THEME
   ------------------------------------------------------------
   The resolved theme is already on <html> from the inline script
   in <head>, so there is no flash. This only handles changes.
   ============================================================ */
const mq = window.matchMedia('(prefers-color-scheme: light)');
const themeButtons = document.querySelectorAll('[data-theme-set]');
let themeMode = document.documentElement.dataset.themeMode || 'dark';

function applyTheme(){
  const t = themeMode === 'system' ? (mq.matches ? 'light' : 'dark') : themeMode;
  document.documentElement.dataset.theme = t;
  document.documentElement.dataset.themeMode = themeMode;
  /* Keep the browser chrome with the chosen theme, not the OS one. */
  const themeMeta = document.getElementById('theme-color');
  if (themeMeta) themeMeta.content = t === 'light' ? '#EDF0F6' : '#0E1119';
  themeButtons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.themeSet === themeMode)));
}
themeButtons.forEach(b => b.addEventListener('click', () => {
  themeMode = b.dataset.themeSet;
  try { localStorage.setItem('dd-theme', themeMode); } catch (e) { /* private mode — session only */ }
  applyTheme();
}));
mq.addEventListener('change', () => { if (themeMode === 'system') applyTheme(); });

/* ── A team champion's roster ────────────────────────────────────────────
   Both pages name a team champion by the name it entered under, which says
   nothing about who won it. The Duelists are in the manifest, on the champion
   entry, and this is what puts them on screen.

   Native <dialog>: showModal() gives the focus trap, Escape and the inert
   background, and returns focus where it came from when it closes. Writing
   those again would be three bugs waiting rather than one function.

   Shared because the two pages differ only in the line underneath. */
function openRoster({ name, members, note }){
  const box  = document.getElementById('roster');
  const list = document.getElementById('roster-list');
  if (!box || !list || !(members || []).length) return;
  document.getElementById('roster-name').textContent = name;
  list.innerHTML = (members || []).map(m => `<li>
      <span class="roster__n">${playerLink(m.name)}</span>
      ${m.deck ? `<span class="roster__d">${esc(m.deck)}</span>` : ''}
    </li>`).join('');
  const at = document.getElementById('roster-at');
  at.textContent = note || '';
  at.hidden = !note;
  /* showModal() where there is one. A browser without <dialog> still gets the
     content -- the open attribute shows it inline -- rather than a click that
     does nothing and an exception in the console. */
  if (typeof box.showModal === 'function') box.showModal();
  else box.setAttribute('open', '');
}

function closeRoster(box){
  if (typeof box.close === 'function') box.close();
  else box.removeAttribute('open');
}

document.addEventListener('click', (e) => {
  const box = document.getElementById('roster');
  if (box && e.target.closest('[data-roster-close]')) closeRoster(box);
});
/* A click on the backdrop is a click on the dialog itself: the box is the
   element, and anything outside its own rectangle is the backdrop. */
document.getElementById('roster')?.addEventListener('click', (e) => {
  const box = e.currentTarget.getBoundingClientRect();
  const outside = e.clientX < box.left || e.clientX > box.right
               || e.clientY < box.top  || e.clientY > box.bottom;
  if (outside) closeRoster(e.currentTarget);
});
