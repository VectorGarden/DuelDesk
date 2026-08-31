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
/* The rows as rendered, so a roster button can name its own row by index
   rather than by a name two winners could share. */
let shown = [];
/* Which rosters the reader has opened. Keyed by the event and the team rather
   than by the row: a search re-orders the list, and an index would carry the
   open state to whichever team happened to land in that position. */
let open = new Set();
const rosterKey = (r) => `${r.slug}|${r.name}`;

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
        /* A team champion's Duelists, where the manifest carries them. A
           singles champion has none and the row is unchanged. */
        members: c.members || null,
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

/* How many events a Duelist has won, counting the ones they won as part of a
   team. A team's title belongs to its three Duelists as much as to the name
   they entered under -- Kamal Derrick El Crooks-Valdez has won alone and has
   won on two teams, and a count that only saw the team name would say once. */
function duelistWins(rows){
  const n = new Map();
  const add = (name) => name && n.set(name, (n.get(name) || 0) + 1);
  for (const r of rows){
    if (r.members?.length) r.members.forEach(m => add(m.name));
    else add(r.name);
  }
  return n;
}

/* An event that names no format was played under Advanced. Before 2025 there
   was nothing else to play -- Advanced and the Dragon Duel side event, which
   is not in here at all -- so the blog had no reason to say so, and the
   builder does not invent what the source never stated.

   Read here rather than written into the archive, because the archive should
   go on saying what Konami said. The filter can know what that means. */
const DEFAULT_FORMAT = 'Advanced';
const formatOf = (r) => r.format || DEFAULT_FORMAT;

let formatFilter = 'all';

function formatsPresent(){
  return [...new Set(WINS.map(formatOf))].sort();
}

function renderFormatFilters(){
  const box = document.getElementById('format-filters');
  if (!box) return;
  const present = formatsPresent();
  /* One format is not a choice. */
  box.hidden = present.length < 2;
  if (box.hidden){ box.innerHTML = ''; return; }
  box.innerHTML = [['all', 'Every Format'], ...present.map(f => [f, f])]
    .map(([value, label]) =>
      `<button type="button" data-win-format="${esc(value)}" aria-pressed="${
        String(value === formatFilter)}">${esc(label)}</button>`).join('');
}

document.addEventListener('click', e => {
  const b = e.target.closest('[data-win-format]');
  if (!b) return;
  formatFilter = b.dataset.winFormat;
  render();
  say(countEl.textContent);
});

function render(){
  const all = repeats(WINS);
  const each = duelistWins(WINS);
  renderFormatFilters();
  const rows = WINS.filter(r =>
    (formatFilter === 'all' || formatOf(r) === formatFilter)
    && hit(r.event, r.name, r.deck, r.format, r.location));

  countEl.textContent = rows.length
    ? `${rows.length} winner${rows.length > 1 ? 's' : ''}`
      + (rows.length === WINS.length ? '' : ` of ${WINS.length}`)
    : 'No matches';

  if (!rows.length){
    list.innerHTML = `<div class="empty"><h3>Nothing matches that</h3>
      <p>Try an event, a Duelist or a deck.</p></div>`;
    return;
  }

  shown = rows;
  list.innerHTML = `<ol class="wins">` + rows.map((r, i) => {
    const won = all.get(r.name) || 1;
    return `<li class="win">
      <div class="win__who">
        <b class="win__n">${esc(r.name)}</b>
        ${won > 1 ? `<span class="win__x" title="Events won in this archive">${esc(won)}&times;</span>` : ''}
        ${r.deck ? `<span class="win__d">${esc(r.deck)}</span>` : ''}
        ${r.members?.length ? `<button type="button" class="roster-open" data-roster="${esc(i)}"
            aria-expanded="${String(open.has(rosterKey(r)))}" aria-controls="roster-${esc(i)}"
            >Roster</button>` : ''}
      </div>
      <div class="win__at">
        <a class="win__e" href="/?event=${encodeURIComponent(r.slug)}">${esc(r.event)}</a>
        ${r.format ? `<span class="win__f">${esc(r.format)}</span>` : ''}
        <span class="win__w">${esc(when(r.date))}</span>
        ${r.location ? `<span class="win__l">${esc(r.location)}</span>` : ''}
      </div>
      ${r.members?.length ? `<ul class="win__roster" id="roster-${esc(i)}"${
        open.has(rosterKey(r)) ? '' : ' hidden'}>${r.members.map(m => {
          const mw = each.get(m.name) || 1;
          return `<li>
            <span class="roster__n">${esc(m.name)}</span>
            ${mw > 1 ? `<span class="win__x" title="Events won in this archive"
              >${esc(mw)}&times;</span>` : ''}
            ${m.deck ? `<span class="roster__d">${esc(m.deck)}</span>` : ''}
          </li>`;
        }).join('')}</ul>` : ''}
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

/* Expanded in place rather than in a dialog. A roster is three names and the
   row it belongs to is right there -- a modal would cover the list the reader
   is reading to show them less than the row already implies. */
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-roster]');
  if (!b) return;
  const i = Number(b.dataset.roster);
  const box = document.getElementById(`roster-${i}`);
  if (!box) return;
  const nowOpen = box.hidden;
  box.hidden = !nowOpen;
  b.setAttribute('aria-expanded', String(nowOpen));
  const key = rosterKey(shown[i]);
  if (nowOpen) open.add(key); else open.delete(key);
  say(nowOpen ? `${shown[i]?.name}: ${shown[i]?.members?.length} Duelists` : 'Roster hidden');
});
