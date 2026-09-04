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
      const res = await fetch(`/cards/${shard}.json`, {cache: 'force-cache'});
      CARDS.set(shard, res.ok ? await res.json() : {});
    } catch {
      /* A card that will not load is a card the reader does not get told
         about, which is where they were before. */
      CARDS.set(shard, {});
    }
  }
  return CARDS.get(shard)[key] ?? null;
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
