/* ============================================================
   WINNERS — every event the coverage names a winner for
   ------------------------------------------------------------
   One fetch, of the manifest the coverage page already loads
   first. The champions are in it because the alternative is
   fetching a hundred and forty round files, several of them over
   ten megabytes, to read one name out of each.

   esc(), safeUrl() and the theme come from common.js.
   ============================================================ */
const list    = document.getElementById('winners');
const countEl = document.getElementById('wcount');
const qEl     = document.getElementById('q');
const liveRegion = document.getElementById('announce');

let WINS = [];
let query = '';

const say = (msg) => { if (liveRegion) liveRegion.textContent = msg; };

/* Newest first: an event's winner is news for about a week and history
   afterwards. The manifest is already in that order, and this does not rely on
   it -- a list that promises an order should hold to it whatever it is handed. */
function flatten(events){
  const out = [];
  for (const e of events || []){
    for (const c of e.champions || []){
      out.push({
        event: e.event,
        slug: e.slug,
        location: e.location || null,
        date: e.updated || null,
        /* Null for the events that run a single tournament and never name a
           format -- the North America WCQ titles every post "North America
           WCQ: Round 10 Pairings". Shown as nothing rather than invented. */
        format: c.format || null,
        name: c.name,
        deck: c.deck || null,
      });
    }
  }
  return out.sort((a, b) => String(b.date ?? '').localeCompare(String(a.date ?? '')));
}

const day = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ''));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
};

const when = (iso) => {
  const d = day(iso);
  return d ? d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'}) : '';
};

const hit = (...fields) =>
  !query || fields.filter(Boolean).join(' ').toLowerCase().includes(query);

/* How many events this person has won, across the whole archive. Worth saying:
   the same names come back, and a list that did not say so would be hiding the
   most interesting thing in it. */
function repeats(rows){
  const n = new Map();
  for (const r of rows) n.set(r.name, (n.get(r.name) || 0) + 1);
  return n;
}

function render(){
  const all = repeats(WINS);
  const rows = WINS.filter(r => hit(r.event, r.name, r.deck, r.format, r.location));

  countEl.textContent = rows.length
    ? `${rows.length} winner${rows.length > 1 ? 's' : ''}`
      + (rows.length === WINS.length ? '' : ` of ${WINS.length}`)
    : 'No matches';

  if (!rows.length){
    list.innerHTML = `<div class="empty"><h3>Nothing matches that</h3>
      <p>Try an event, a Duelist or a deck.</p></div>`;
    return;
  }

  list.innerHTML = `<ol class="wins">` + rows.map(r => {
    const won = all.get(r.name) || 1;
    return `<li class="win">
      <div class="win__who">
        <b class="win__n">${esc(r.name)}</b>
        ${won > 1 ? `<span class="win__x" title="Events won in this archive">${esc(won)}&times;</span>` : ''}
        ${r.deck ? `<span class="win__d">${esc(r.deck)}</span>` : ''}
      </div>
      <div class="win__at">
        <a class="win__e" href="/?event=${encodeURIComponent(r.slug)}">${esc(r.event)}</a>
        ${r.format ? `<span class="win__f">${esc(r.format)}</span>` : ''}
        <span class="win__w">${esc(when(r.date))}</span>
        ${r.location ? `<span class="win__l">${esc(r.location)}</span>` : ''}
      </div>
    </li>`;
  }).join('') + `</ol>`;
}

let searchTimer;
qEl?.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const next = qEl.value.trim().toLowerCase();
    if (next === query) return;
    query = next;
    render();
    say(countEl.textContent);
  }, 250);
});

/* "/" jumps to search, Escape clears it -- the same two keys the coverage page
   answers to, because a reader moving between them should not have to learn a
   second set. */
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement !== qEl){
    e.preventDefault();
    qEl?.focus();
  } else if (e.key === 'Escape' && document.activeElement === qEl){
    qEl.value = '';
    query = '';
    render();
  }
});

async function load(){
  try {
    /* Rooted. This page is served at /winners/, so "events.json" asks for
       /winners/events.json and gets a 404 -- which is what it did, and the
       page showed "Winners could not be loaded" over an empty list. app.js
       can say it relatively because index.html is served from the root; this
       one cannot. */
    const res = await fetch('/events.json', {cache: 'no-cache'});
    if (!res.ok) throw new Error(`events.json responded ${res.status}`);
    WINS = flatten((await res.json()).events);
    if (!WINS.length){
      countEl.textContent = 'No winners yet';
      list.innerHTML = `<div class="empty"><h3>No winners on record</h3>
        <p>The coverage names one where it can. So far it has not.</p></div>`;
      return;
    }
    render();
  } catch (err) {
    countEl.textContent = 'Unavailable';
    list.innerHTML = `<div class="empty"><h3>Winners could not be loaded</h3>
      <p>${esc(err.message)}</p></div>`;
  }
}

applyTheme();
load();
