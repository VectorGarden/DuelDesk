/* ============================================================
   0. HELPERS
   ============================================================ */

/* Everything rendered through innerHTML goes through this first.
   Every name, headline and deck on the page came out of somebody
   else's markup, by way of a scraper. Escape at the boundary,
   always. */
const ESCAPES = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ESCAPES[c]);

/* esc() makes a value safe *inside* an attribute. It does not make a URL safe
   *as* an href: "javascript:alert(1)" contains none of the five characters
   esc() escapes, so it passes through intact and runs on click. The two do
   different jobs and neither substitutes for the other.

   The URL constructor is doing the parsing on purpose -- it normalises the
   tricks a hand-written scheme regex misses: "java\tscript:", leading
   whitespace, control characters, odd encodings. */
/* A headline is only a link when it goes somewhere else. The feed carries a
   <link> for every item, but the sample feed points every one at this site's own
   homepage, so linking those would reload the page under the reader. For real
   coverage the link is the point: the page shows Konami's headlines, and this is
   how a reader reaches the post itself. */
/* A feed item for a round this page already shows should move the page to it,
   not send the reader to Konami to read a table sitting a few hundred pixels
   above. Only pairings and standings: a feature match or a deck list is prose
   and photographs, and the post is the only place to read it.

   Returns null when the round cannot be resolved -- an event-wide post while two
   tournaments are on offer names no format, and guessing which one is worse than
   linking out. */
function jumpTarget(post){
  if (post.kind !== 'pairings' && post.kind !== 'standings') return null;
  /* The round panel holds one event, and which rounds another event published
     is not in the manifest -- only in the file for that event, which has not
     been fetched. Rather than offer a jump that might land nowhere, the event
     group in the coverage list carries a control to open the event first; every
     headline in it becomes a jump once it is the one on screen. */
  if (post.slug && post.slug !== activeEvent) return null;
  if (post.round === null || post.round === undefined) return null;
  if (hasFormatChoice() && !post.format) return null;
  const name = post.format || activeFormat;
  const fmt = eventInfo?.formats?.find(f => f.format === name);
  const rounds = fmt?.rounds ?? [];

  /* "Final Standings" is Konami's name for the table at the end of Swiss, not
     for a bracket round. Reading it as one landed the reader on a panel headed
     "Final · Top cut" for a post about Swiss -- showing the right rows, since a
     cut round points at that very table, but saying the wrong thing about them. */
  if (post.kind === 'standings' && post.round === 'Final') {
    const swiss = rounds.filter(r => r.phase !== 'Top cut');
    const last = swiss[swiss.length - 1];
    return last ? {format: name, round: last.id, view: 'standings'} : null;
  }

  /* Cut ids drop their spaces: the feed says "Top 8", the data says "Top8". */
  const wanted = String(post.round).replace(/\s+/g, '');
  const round = rounds.find(r => String(r.id) === wanted);
  return round ? {format: name, round: round.id, view: post.kind} : null;
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
   1. THEME
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

/* ============================================================
   2. THE COVERAGE FEED
   ------------------------------------------------------------
   feed.xml is this site's own, written by the scraper. The blog
   it covers has no feed to read -- every /feed/ path 404s and
   the REST endpoint returns 403, which is why there is a scraper
   at all, reading the sitemap instead.

   The hard part is not fetching it. One event arrives as a
   hundred and forty separate posts titled "Round 11 Pairings",
   and these functions turn that flat stream back into events
   holding rounds.
   ============================================================ */
const KINDS = {
  pairings : {label:'Pairings',      color:'var(--c-pair)'},
  standings: {label:'Standings',     color:'var(--c-stand)'},
  feature  : {label:'Feature match', color:'var(--c-feature)'},
  result   : {label:'Result',        color:'var(--c-result)'},
  news     : {label:'Announcement',  color:'var(--c-news)'},
  deck     : {label:'Deck profile',  color:'var(--c-deck)'}
};
const kindOf = k => KINDS[k] ?? KINDS.news;

/* A record is stored as parts, because how much of it is known varies. Wins are
   exact from match points; losses need the rounds a Duelist actually played;
   and before ties were abolished on 2025-09-02, points alone determine neither
   -- 3 points is one win or three draws.

   A "?" is not decoration: it says we looked and could not tell, which is a
   different claim from a blank. "0–?" and "?–?" are different states, and
   collapsing both to a dash would lose that.

   The shape follows the era. Ties existed before 2025-09-02, so those events
   read W–L–T as they did at the time; later ones read W–L. */
function formatRecord(record, {drawsPossible = false} = {}){
  if (!record) return drawsPossible ? '?–?–?' : '?–?';
  const part = v => (v === null || v === undefined) ? '?' : String(v);
  const shown = drawsPossible || record.draws > 0
    ? [record.wins, record.losses, record.draws]
    : [record.wins, record.losses];
  return shown.map(part).join('–');
}

const eventDrawsPossible = () => !!eventInfo?.drawsPossible;

/* Round slot, independent of word order — real titles vary a lot
   ("Round 11 Pairings", "Pairings for Round 11", "R11 pairings"). */
function roundFrom(t){
  let m;
  if ((m = t.match(/\btop\s*(\d+)/)))                     return 'Top ' + m[1];
  if ((m = t.match(/\bround\s*(\d+)/)))                   return +m[1];
  if ((m = t.match(/\br(\d+)\b/)))                        return +m[1];
  if (/\bquarter[-\s]?finals?\b/.test(t))                 return 'Top 8';
  if (/\bsemi[-\s]?finals?\b/.test(t))                    return 'Top 4';
  if (/\bfinals?\b/.test(t))                              return 'Final';
  return null;
}

/* Coverage type. Order matters: the structural markers (pairings,
   standings) are checked before the looser "deck" catch, so that
   "Top 8 pairings" is a pairing and "Top 8 decklists" is a profile.
   "Deck check" is a policy term, not deck content, so it is excluded.
   Titles with no keyword at all fall back to 'news' rather than guess. */
function kindFrom(t){
  if (/\bpairings?\b/.test(t))                                               return 'pairings';
  if (/\bstandings\b|\bpoint totals\b/.test(t))                              return 'standings';
  if (/\bfeature match\b|\bfinal match\b|\bmatch:\s/.test(t))                return 'feature';
  if (/\bwinner\b|\bchampion\b|\bcongratulations\b|\bundefeated\b/.test(t))  return 'result';
  if (/\bdecks?\b|\bdeck ?lists?\b/.test(t) && !/\bdeck check\b/.test(t))     return 'deck';
  return 'news';
}

/** Classify one post title into a kind plus a round slot. */
function classify(title){
  const t = title.toLowerCase();
  return {kind: kindFrom(t), round: roundFrom(t)};
}

/* A leading "Feature Match:" is a coverage label, not an event name.
   Splitting on the colon regardless would invent an event called
   "Feature Match" and scatter the real tournament across it. */
const LABEL_PREFIX = /^(pairings?|standings|feature match|final match|deck profiles?|deck ?lists?|round \d+|top \d+|results?|announcements?|update)\b/i;

function eventNameFrom(title, fallback){
  const i = title.indexOf(':');
  if (i > -1){
    const head = title.slice(0, i).trim();
    if (head && !LABEL_PREFIX.test(head)) return head;
  }
  return fallback;
}

/** RSS XML -> [{event, date, posts:[{title,kind,round,time,url}]}] */
function groupFeed(xmlText){                                   // eslint-disable-line
  const doc = new DOMParser().parseFromString(xmlText, 'application/xml');
  if (doc.querySelector('parsererror')) throw new Error('Feed is not valid XML');

  const map = new Map();
  for (const item of doc.querySelectorAll('item')){
    /* The feed marks every item [Sample] so the disclaimer travels with it into
       aggregators, where nobody reads <copyright>. On the page itself the badge
       beside the headline already says so, so strip it rather than repeat it in
       every event name and post title. */
    const rawTitle = item.querySelector('title')?.textContent?.trim() ?? '';
    const title = rawTitle.replace(/^\[sample\]\s*/i, '');
    if (!title) continue;
    const url   = item.querySelector('link')?.textContent?.trim() ?? '#';
    const raw   = item.querySelector('pubDate')?.textContent;
    const date  = raw && !isNaN(Date.parse(raw)) ? new Date(raw) : new Date();
    const cat   = item.querySelector('category')?.textContent?.trim();
    /* The feed states the format on a second, namespaced category. A post that
       belongs to no format -- an announcement is about the event, not one of its
       tournaments -- carries none, and stays visible whichever is selected. */
    const fmt   = item.querySelector('category[domain="format"]')?.textContent?.trim() || null;
    /* And the archive slug on a third. Names are for reading -- they are derived
       from what the coverage calls itself and can change between scrapes -- so
       the slug is what groups an event and what links a headline to the event
       file the round panel loads. */
    const slug  = item.querySelector('category[domain="event"]')?.textContent?.trim() || null;
    const name  = eventNameFrom(title, cat || 'Unsorted coverage');

    /* Feed items are titled "Event: headline" so each one stands alone in a
       reader, where there is no surrounding context. On the page the event name
       is already the heading directly above the row, so repeating it in every
       post is noise. Split it off rather than render it twice.

       Only the exact prefix goes: "Remote Duel YCS: Feature match: X vs Y"
       keeps its inner colon, and an item whose title carries no event prefix
       (because eventNameFrom fell back to the category) is left alone. */
    const headline = title.startsWith(name + ':')
      ? title.slice(name.length + 1).trim() || title
      : title;

    /* Keyed on the slug where there is one, so two events that happen to be
       written the same way stay apart, and one renamed between scrapes does not
       split into two. */
    const key = slug || name;
    let group = map.get(key);
    if (!group) map.set(key, group = {event:name, slug, date, posts:[]});
    if (date > group.date) group.date = date;   // group carries its newest post's date

    group.posts.push({
      title: headline,
      format: fmt,
      slug,
      url: safeUrl(url),
      time: date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}),
      /* Classify the headline, not the full title: an event called
         "300th YCS" or "Top Cut Invitational" would otherwise leak its own
         digits and keywords into round and kind detection. */
      ...classify(headline)
    });
  }
  return [...map.values()].sort((a, b) => b.date - a.date);
}

/* ============================================================
   3. THE ARCHIVE — events, their rounds, and choosing between them
   ------------------------------------------------------------
   Fifty-two events from 2011 onwards. events.json lists them all
   and is small; each event's rounds are their own file, fetched
   only when that event is the one being read.

   Everything from here to section 4 is about which event is on
   screen: loading it, naming it, and the search that finds it.
   ============================================================ */
let ROUNDS = [];
let eventInfo = null;
let activeFormat = null;       // which tournament's rounds are on screen
let roundsVersion = null;      // change detection: see versionOf()
let roundsState = 'loading';   // loading | ready | error
let roundsError = '';

/* The archive. events.json lists every event the scraper has built, small
   enough to load first; each event's rounds live in their own file and are
   fetched only when that event is being read. One event is about 1.3MB, so a
   single file holding all of them would be a several-megabyte download to look
   at one round of one tournament. */
let CATALOG = [];              // events.json, newest first
let activeEvent = null;        // slug of the event on screen
let catalogVersion = null;

const entryFor = slug => CATALOG.find(e => e.slug === slug);
/* One event is not a choice, so it is not presented as one -- the same rule the
   format buttons follow. */
const hasEventChoice = () => CATALOG.length > 1;

const roundOf = id => ROUNDS.find(r => r.id === id);
const formatOf = name => eventInfo?.formats?.find(f => f.format === name) ?? eventInfo?.formats?.[0];

/* Each format is a separate tournament, so switching one out replaces the round
   set entirely -- including the round count, which differs between them. */
function selectFormat(name){
  const f = formatOf(name);
  if (!f || name === activeFormat) return;
  activeFormat = name;
  ROUNDS = f.rounds;
  activeRound = null;                 // the old round id may not exist here
  renderFormats();
  renderEventMeta();
  buildTrack();
  landOnCurrentRound();
  renderEvents();            // the coverage list below follows the same choice
  say(`Showing the ${name} tournament`);
}

function landOnCurrentRound(){
  if (!activeRound || !ROUNDS.some(r => r.id === activeRound)){
    const current = ROUNDS.find(r => r.state === 'live')
                 ?? [...ROUNDS].reverse().find(r => r.state === 'done')
                 ?? ROUNDS[0];
    activeRound = current?.id ?? null;
  }
  syncSegs();
  if (activeRound) selectRound(activeRound); else renderRound();
}

/* One format is not a choice, so do not present it as one. The hero meta reads
   the same flag: whichever of the two states the format, exactly one of them
   does, so it is never said twice and never left unsaid. */
const hasFormatChoice = () => (eventInfo?.formats?.length ?? 0) > 1;

/* An event runs most years, so its name alone does not identify it: of the 68
   events in the blog's archive with rounds to show, 25 share a name with
   another one. Five separate North American WCQs ran between 2013 and 2017, and
   without a date the picker offers five identical entries and no way to tell
   which is which.

   The date rather than the year, because it is the same width and answers the
   other question a list of past events raises. Absent for an event whose
   coverage carried no date, which is a fact about it rather than a reason to
   print something. */
/* The archive writes a calendar date -- the day the coverage ended -- and the
   day is the whole point of showing it. Two things make that harder than it
   looks.

   new Date("2026-08-16") is midnight UTC, which renders as the 15th for every
   reader west of Greenwich. Built from the parts instead, so the day shown is
   the day the scraper wrote.

   And Date.parse is not a validator: it reads "sometime in 2019" as the 1st of
   January and hands back a date nobody wrote. The shape is checked first, so
   anything that is not a date the archive could have produced is treated as no
   date at all. */
const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})/;
function eventDate(stamp){
  const m = ISO_DAY.exec(String(stamp ?? ''));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}

function eventLabel(e){
  const on = eventDate(e.updated);
  const when = on && on.toLocaleDateString('en-GB', {month:'short', year:'numeric'});
  return [e.event, when].filter(Boolean).join(' · ') + (e.ongoing ? ' · live' : '');
}

/* ---- the event combobox -------------------------------------------------
   Fifty-two events, a dozen of them a YCS in a city you would have to scroll a
   select to find, and several sharing a name across years. So it is a search:
   type, and the list narrows.

   What a query matches is everything that identifies an event to a reader --
   its name, where it was held, its year -- plus its archive slug, which is how
   "north america" finds an event whose coverage only ever called it NAWCQ. */
let pickerOpen = false;
let pickerQuery = '';
let pickerAt = 0;                 // which option the keyboard is on

const pickerInput = () => document.getElementById('event-search');
const pickerList  = () => document.getElementById('event-list');

/* "NAWCQ" for "North America WCQ 2026". The qualifiers are known by their
   initials as much as by their names -- the blog's own coverage calls that
   event NAWCQ throughout -- and neither the name nor the slug contains the
   word. A part that is already an abbreviation stays whole, so the WCQ in the
   middle survives rather than becoming a W. */
function initials(name){
  const words = String(name || '').split(/\s+/).filter(w => /[a-z]/i.test(w));
  return words.map(w => (w.length > 1 && w === w.toUpperCase() ? w : w[0])).join('')
              .toLowerCase();
}

function eventMatches(e){
  if (!pickerQuery) return true;
  const hay = [e.event, e.location, e.slug, (e.updated || '').slice(0, 4), initials(e.event)]
    .filter(Boolean).join(' ').toLowerCase();
  /* Every word, in any order: "wcq 2018" and "2018 wcq" are the same request,
     and neither is a substring of "North America WCQ 2018". */
  return pickerQuery.split(/\s+/).filter(Boolean).every(w => hay.includes(w));
}

const pickerOptions = () => CATALOG.filter(eventMatches);

/* Runs of one year, in the order the catalog already has -- which is newest
   first, so the years come out in order without sorting anything again. The
   index travels with each event because the keyboard counts options across the
   whole list, not within a year. */
function groupByYear(events){
  const out = [];
  events.forEach((event, i) => {
    /* Through eventDate, not the first four characters of the stamp: that reads
       "sometime in 2019" as a year called "some". Same reason the option's own
       date goes through it -- a stamp the archive could not have written is no
       date rather than a confident wrong one. */
    const on = eventDate(event.updated);
    const year = on ? String(on.getFullYear()) : 'Undated';
    if (out.at(-1)?.[0] !== year) out.push([year, []]);
    out.at(-1)[1].push({event, i});
  });
  return out;
}

function renderEventPicker(){
  const wrap = document.getElementById('event-pick');
  wrap.hidden = !hasEventChoice();
  if (wrap.hidden) return;

  const input = pickerInput();
  const list = pickerList();
  /* Closed, the box says which event is on screen; open, it holds the query.
     Overwriting it while the reader is typing would undo their keystroke. */
  if (!pickerOpen) input.value = entryFor(activeEvent)?.event ?? '';

  const options = pickerOptions();
  pickerAt = Math.min(pickerAt, Math.max(options.length - 1, 0));
  list.hidden = !pickerOpen;
  input.setAttribute('aria-expanded', String(pickerOpen));
  if (!pickerOpen){ input.removeAttribute('aria-activedescendant'); return; }

  list.innerHTML = options.length ? groupByYear(options).map(([year, events]) =>
    /* A real group rather than a heading between rows, so the year is part of
       what a screen reader announces about the option and not decoration
       sitting near it. The inner list is presentational: without that the
       options would hang off a second listbox rather than off the group. */
    `<li role="group" aria-label="${esc(year)}">
      <span class="picker__year" aria-hidden="true">${esc(year)}</span>
      <ul role="presentation">${events.map(({event: e, i}) => {
        const when = eventDate(e.updated);
        const month = when ? when.toLocaleDateString('en-GB', {month: 'short'}) : '';
        return `<li role="option" id="ev-opt-${i}" data-slug="${esc(e.slug)}"
            aria-selected="${String(i === pickerAt)}"
            class="${e.slug === activeEvent ? 'here' : ''}">
          <b>${esc(e.event)}</b>
          <span>${esc(e.location ? e.location + ' · ' : '')}${esc(month)}</span>
        </li>`;
      }).join('')}</ul>
    </li>`).join('') : `<li class="picker__none" role="option" aria-selected="false"
      id="ev-opt-none">No event matches that</li>`;

  if (options.length) input.setAttribute('aria-activedescendant', `ev-opt-${pickerAt}`);
  else input.removeAttribute('aria-activedescendant');
  list.querySelector('[aria-selected="true"]')?.scrollIntoView({block: 'nearest'});
}

function openPicker(open){
  if (pickerOpen === open) return;
  pickerOpen = open;
  /* The query starts empty rather than pre-filled with the current event's
     name, which would show one result and read as though nothing else exists. */
  pickerQuery = '';
  pickerAt = Math.max(0, CATALOG.findIndex(e => e.slug === activeEvent));
  if (open) pickerInput().value = '';
  renderEventPicker();
}

function commitPicker(slug){
  const chosen = slug ?? pickerOptions()[pickerAt]?.slug;
  openPicker(false);
  if (chosen) selectEvent(chosen); else renderEventPicker();
}

/* Switching events replaces everything below it, so the panel is emptied while
   the new file is in flight rather than left showing the old event's rounds
   under the new event's name. */
async function selectEvent(slug){
  const entry = entryFor(slug);
  if (!entry || slug === activeEvent) return;
  activeEvent = slug;
  activeFormat = null;
  activeRound = null;
  eventInfo = null;
  ROUNDS = [];
  roundsState = 'loading';
  renderEventMeta();
  renderFormats();
  buildTrack();
  renderRound();
  await refreshRounds();
  /* Which headlines below are in-page jumps depends on which event is loaded,
     so the list is rebuilt rather than left offering the previous event's. */
  renderEvents();
  say(`Showing ${entry.event}`);
}

document.addEventListener('input', e => {
  if (e.target.id !== 'event-search') return;
  pickerQuery = e.target.value.trim().toLowerCase();
  pickerOpen = true;
  pickerAt = 0;
  renderEventPicker();
});

document.addEventListener('keydown', e => {
  if (e.target.id !== 'event-search' || e.metaKey || e.ctrlKey || e.altKey) return;
  const options = pickerOptions();
  const step = {ArrowDown: 1, ArrowUp: -1}[e.key];
  if (step !== undefined){
    e.preventDefault();
    if (!pickerOpen) return openPicker(true);
    if (!options.length) return;
    pickerAt = (pickerAt + step + options.length) % options.length;
    renderEventPicker();
  } else if (e.key === 'Enter'){
    e.preventDefault();
    if (pickerOpen) commitPicker();
  } else if (e.key === 'Escape'){
    /* Back to the event on screen, which is what the box said before it was
       opened. A reader who changes their mind should not have to remember it. */
    e.preventDefault();
    openPicker(false);
  } else if (e.key === 'Home' || e.key === 'End'){
    if (!pickerOpen || !options.length) return;
    e.preventDefault();
    pickerAt = e.key === 'Home' ? 0 : options.length - 1;
    renderEventPicker();
  }
});

document.addEventListener('click', e => {
  const option = e.target.closest('#event-list [data-slug]');
  if (option) return commitPicker(option.dataset.slug);
  if (e.target.id === 'event-search') return openPicker(true);
  if (pickerOpen && !e.target.closest('#event-pick')) openPicker(false);
});

function renderFormats(){
  const el = document.getElementById('formats');
  const formats = eventInfo?.formats ?? [];
  el.hidden = !hasFormatChoice();
  if (el.hidden){ el.innerHTML = ''; return; }
  el.innerHTML = formats.map(f =>
    `<button type="button" data-format="${esc(f.format)}"
             aria-pressed="${String(f.format === activeFormat)}">${
       esc(f.format ?? 'Main event')}</button>`).join('');
}

document.addEventListener('click', e => {
  const b = e.target.closest('[data-format]');
  if (b) selectFormat(b.dataset.format);
});

async function loadCatalog(){
  const res = await fetch('events.json', {cache:'no-cache'});
  if (!res.ok) throw new Error(`events responded ${res.status}`);

  const text = await res.text();
  const version = versionOf(res, text);
  if (catalogVersion !== null && version === catalogVersion) return {unchanged:true};

  const data = JSON.parse(text);
  if (!Array.isArray(data.events) || !data.events.length)
    throw new Error('events.json lists no events');
  catalogVersion = version;  // only after it parses, so a bad file is retried
  return {unchanged:false, events:data.events};
}

/* The version is tracked per event, not globally: switching away and back must
   refetch rather than see the mark left by the event in between and decide
   nothing has changed. */
async function loadRounds(entry){
  const res = await fetch(entry.path, {cache:'no-cache'});
  if (!res.ok) throw new Error(`rounds responded ${res.status}`);

  const text = await res.text();
  const version = versionOf(res, text);
  if (roundsVersion?.slug === entry.slug && roundsVersion.version === version)
    return {unchanged:true};

  const data = JSON.parse(text);
  if (!Array.isArray(data.formats) || !data.formats.length) throw new Error('rounds.json has no formats');
  if (!data.formats.some(f => Array.isArray(f.rounds) && f.rounds.length))
    throw new Error('rounds.json has no rounds');
  roundsVersion = {slug:entry.slug, version};
  return {unchanged:false, data};
}

async function refreshRounds({poll = false} = {}){
  try {
    const catalog = await loadCatalog();
    if (!catalog.unchanged){
      CATALOG = catalog.events;
      renderEventPicker();
    }
    /* Whatever the reader chose, unless the archive no longer offers it. The
       newest event is the default, and a poll must not move them off the one
       they are reading just because a newer one appeared. */
    if (!activeEvent || !entryFor(activeEvent)) activeEvent = CATALOG[0].slug;

    const result = await loadRounds(entryFor(activeEvent));
    if (result.unchanged){
      roundsState = 'ready';
      roundsError = '';
      return {changed: false};
    }
    eventInfo = result.data;
    roundsState = 'ready';
    roundsError = '';
    /* Keep the reader on the format they chose across a refresh, unless it has
       gone away. */
    if (!activeFormat || !eventInfo.formats.some(f => f.format === activeFormat)){
      activeFormat = eventInfo.formats[0].format;
    }
    ROUNDS = formatOf(activeFormat).rounds;
    renderFormats();
    /* Land on whatever the data says is in progress -- but only when we have
       nowhere to be. A poll must not yank a reader looking at round 5 back to
       the live round. */
    landOnCurrentRound();
  } catch (err) {
    roundsState = 'error';
    roundsError = err.message;
  }
  renderEventMeta();
  renderEventPicker();
  renderFormats();
  buildTrack();
  syncSegs();
  /* selectRound() bails when the id is not in ROUNDS, which is exactly the case
     after a failed load -- so the error state would never paint. Render it
     directly instead of routing through round selection. */
  if (roundsState === 'ready' && activeRound) selectRound(activeRound);
  else renderRound();
  /* Whether a headline in the coverage list is an in-page jump depends on the
     rounds this event published, so the list has to be repainted once they
     arrive. It used to be right by luck: rounds were one fetch and coverage
     two, so the rounds always landed first. Reading the manifest before the
     event file reversed that, and every headline rendered as a link off to
     Konami for a round sitting a few hundred pixels above.

     Only when the data actually changed -- refreshRounds returns early when it
     has not -- and through the focus-preserving path, so a poll cannot steal
     focus or reset scroll inside an expanded event. */
  if (EVENTS.length) renderEventsKeepingFocus();
}

function renderEventMeta(){
  const h1 = document.getElementById('live-h');
  const meta = document.getElementById('hero-meta');
  if (roundsState !== 'ready' || !eventInfo){
    h1.textContent = roundsState === 'error' ? 'Event unavailable' : 'Loading event…';
    meta.textContent = '';
    return;
  }
  const f = formatOf(activeFormat);
  /* Explicitly true, not merely truthy or absent: a file that forgets to say
     what it is must not pass as real coverage. check-rounds.py requires the
     field, so the page and the data cannot drift apart quietly. */
  document.getElementById('demo').hidden = eventInfo.sample !== true;
  h1.textContent = eventInfo.event;
  /* When it happened, which only becomes a question once there is more than one
     event to be looking at. Read from the entry the picker chose, so the line
     under the heading and the option that selected it cannot disagree. */
  const on = eventDate(entryFor(activeEvent)?.updated);
  const when = on && on.toLocaleDateString('en-GB',
    {day:'numeric', month:'short', year:'numeric'});
  meta.innerHTML = [
    when && hasEventChoice() ? `<span>${esc(when)}</span>` : '',
    /* Where it was held, when the coverage said. Kept out of the heading --
       "YCS Santiago" is what the event is called, and Chile is a separate fact
       about it -- so this is where it goes. */
    eventInfo.location ? `<span>${esc(eventInfo.location)}</span>` : '',
    /* A Team YCS ranks teams of three, so the count is teams and the noun has
       to follow it. Stated by the data rather than guessed from the rows: a
       team match reads exactly like a match. */
    `<span><b>${esc((f?.duelists ?? 0).toLocaleString())}</b> ${
       esc(f?.entrant === 'Team' ? 'Teams' : 'Duelists')}</span>`,
    `<span><b>${esc(f?.swissRounds ?? 0)}</b> Swiss rounds</span>`,
    /* The selector sits directly below this line and shows the format as the
       pressed button. Naming it here as well printed it twice, a few pixels
       apart, with only one of them actually being the control. */
    /* Absent, not blank: some events run a single tournament and never name a
       format -- the North America WCQ titles every post "North America WCQ:
       Round 10 Pairings" -- and "Format —" states a gap where there is none. */
    (hasFormatChoice() || !f?.format) ? '' : `<span>Format <b>${esc(f.format)}</b></span>`,
    `<span>Coverage by <b>${esc(eventInfo.coverageBy)}</b></span>`
  ].filter(Boolean).join('');
}

/* The coverage list, read from this site's own feed. The feed carries no round
   detail -- a headline and a link and nothing else -- which is why the round
   panel loads the event's own file instead of reading it from here. */
let EVENTS = [];              // filled by refreshCoverage()
let feedUpdated = null;       // <lastBuildDate>, drives the hero stamp
let feedVersion = null;       // change detection: see versionOf()
let coverageState = 'loading';// loading | ready | empty | stale | error
let coverageError = '';

/* The feed has no liveness flag. Rather than invent one, infer it: an event is
   live when its newest post lands within this window of the feed's build time. */
const LIVE_WINDOW_MS = 6 * 60 * 60 * 1000;

/* Parsed separately from groupFeed() so that function keeps its narrow
   contract (RSS text in, events out). Re-parsing 6KB is not worth widening it. */
function feedUpdatedFrom(xmlText){
  const doc = new DOMParser().parseFromString(xmlText, 'application/xml');
  const raw = doc.querySelector('channel > lastBuildDate')?.textContent;
  return raw && !isNaN(Date.parse(raw)) ? new Date(raw) : null;
}

/* groupFeed() returns Date objects and no display fields; the renderer wants
   a formatted date and a live flag. */
function toDisplayEvents(groups, built){
  /* Two conditions, not one. The feed can only say an event was live as of its
     own build time, so that build must also be recent -- otherwise a feed
     generated months ago goes on claiming "live now" indefinitely. */
  const feedIsFresh = !!built && (Date.now() - built) < LIVE_WINDOW_MS;
  return groups.map(g => ({
    event: g.event,
    slug:  g.slug,
    date:  g.date.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}),
    live:  feedIsFresh && (built - g.date) < LIVE_WINDOW_MS,
    posts: g.posts
  }));
}

/* Detecting "nothing changed" cannot use res.status. The browser revalidates
   on our behalf, and when the server answers 304 it hands the *cached body*
   back to script as a 200 -- a revalidation 304 is never visible here.

   Which header is available varies by server: GitHub Pages sends ETag,
   `python -m http.server` sends only Last-Modified, and some send neither. So
   fall back rather than silently re-rendering on every poll, which would drop
   focus and reset scroll once a minute. The last resort compares the body. */
function versionOf(res, body){
  return res.headers.get('ETag')
      ?? res.headers.get('Last-Modified')
      ?? body;
}

async function loadCoverage(){
  /* no-cache forces revalidation, it does not bypass the cache. GitHub Pages
     serves this with max-age=600, so a plain fetch would read a stale copy
     from disk and any future poll would silently do nothing. */
  const res = await fetch('feed.xml', {cache:'no-cache'});
  if (!res.ok) throw new Error(`feed responded ${res.status}`);

  const xml = await res.text();
  const version = versionOf(res, xml);
  if (feedVersion !== null && version === feedVersion) return {unchanged:true};
  feedVersion = version;

  return {unchanged:false, groups: groupFeed(xml), built: feedUpdatedFrom(xml)};
}

/* Rebuilding the list drops focus, so put it back on the same event. Keyed by
   name rather than position: a refresh can reorder or insert events. */
function renderEventsKeepingFocus(){
  const key = document.activeElement?.closest?.('.event__bar')?.dataset.ev ?? null;
  renderEvents();
  if (key == null) return;
  /* Matched by comparing dataset values rather than building an attribute
     selector. Event names contain spaces, commas and ampersands, and
     CSS.escape is defined for identifiers, not for quoted attribute values. */
  for (const bar of list.querySelectorAll('.event__bar')){
    if (bar.dataset.ev === key){ bar.focus(); return; }
  }
}

async function refreshCoverage({poll = false} = {}){
  if (!EVENTS.length){ coverageState = 'loading'; renderEvents(); }
  const wasStale = coverageState === 'stale';
  const postsBefore = EVENTS.reduce((n, e) => n + e.posts.length, 0);
  try {
    const result = await loadCoverage();

    if (result.unchanged){
      /* Nothing to repaint. This is the common case once polling starts, and
         skipping the render is what stops a poll stealing focus or resetting
         scroll inside an expanded event every minute. */
      coverageState = 'ready';
      coverageError = '';
      if (wasStale) renderEvents();      // only to drop the stale notice
      renderStamp();
      return {changed: false};
    }

    EVENTS = toDisplayEvents(result.groups, result.built);
    feedUpdated = result.built;
    coverageState = EVENTS.length ? 'ready' : 'empty';
    coverageError = '';
    /* Open the newest event on first load instead of hardcoding its name. */
    if (!open.size && EVENTS.length) open.add(EVENTS[0].event);
  } catch (err) {
    /* A failed reload must never blank data the reader already has. */
    coverageState = EVENTS.length ? 'stale' : 'error';
    coverageError = err.message;
    renderEvents();
    renderStamp();
    renderLiveTag();
    return {changed: false, failed: true};
  }

  renderEventsKeepingFocus();
  renderStamp();
  renderLiveTag();

  const added = EVENTS.reduce((n, e) => n + e.posts.length, 0) - postsBefore;
  if (poll && added > 0) say(`Coverage updated, ${added} new ${added === 1 ? 'post' : 'posts'}`);
  return {changed: true};
}

/* The hero badge used to be unconditional markup. It now reflects the data:
   no live event, or a feed too old to vouch for one, means no badge. */
function renderLiveTag(){
  document.getElementById('livetag').hidden = !EVENTS.some(ev => ev.live);
}

/* ============================================================
   4. STATE
   ============================================================ */
const rail      = document.getElementById('rail');
const roundBody = document.getElementById('round-body');
const roundH    = document.getElementById('round-h');
const roundSub  = document.getElementById('round-sub');
const list      = document.getElementById('events');
const countEl   = document.getElementById('count');
const qEl       = document.getElementById('q');
const liveRegion= document.getElementById('announce');
const viewButtons = document.querySelectorAll('[data-view]');

let activeRound = null;   // seeded from the active format on load
let activeView  = 'pairings';
let filter = 'all';
let query  = '';
const open = new Set();   // seeded from the feed on first load

const stateLabel = s => s === 'live' ? 'In progress' : s === 'done' ? 'Complete' : 'Not started';
const hit = (...fields) => !query || fields.join(' ').toLowerCase().includes(query);

/* ============================================================
   5. ROUND TRACK — an ARIA tablist with roving tabindex
   ------------------------------------------------------------
   Chips are built once and then updated in place. Rebuilding the
   rail on every keypress destroyed the focused element and reset
   the horizontal scroll to zero, which made arrow-keying jump.
   ============================================================ */
function buildTrack(){
  rail.replaceChildren(...ROUNDS.map(r => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-controls', 'round-body');
    b.dataset.state = r.state;
    b.dataset.id = r.id;
    b.id = 'tab-' + r.id;

    const n = document.createElement('span');
    n.className = 'chip__n';
    n.textContent = r.label;
    const s = document.createElement('span');
    s.className = 'chip__s';
    s.textContent = stateLabel(r.state);
    b.append(n, s);
    return b;
  }));
  syncTrack();
}

/* Which edges still have track behind them. Pure so it can be tested without a
   layout engine: jsdom reports every scroll dimension as 0, which is exactly
   the "nothing to scroll" case and must not draw a fade. */
function overflowState(scrollLeft, scrollWidth, clientWidth){
  const EPS = 1;                      // fractional scroll offsets are normal
  const start = scrollLeft > EPS;
  const end   = scrollLeft + clientWidth < scrollWidth - EPS;
  return start && end ? 'both' : start ? 'start' : end ? 'end' : 'none';
}

function syncRailEdges(){
  rail.dataset.overflow = overflowState(rail.scrollLeft, rail.scrollWidth, rail.clientWidth);
}

/* Scrolling is the usual cause, but not the only one: switching format rebuilds
   the rail with a different number of rounds, and a resize changes what fits. */
rail.addEventListener('scroll', syncRailEdges, {passive:true});
addEventListener('resize', syncRailEdges);

function syncTrack(){
  for (const b of rail.children){
    const selected = b.dataset.id === activeRound;
    b.setAttribute('aria-selected', String(selected));
    b.tabIndex = selected ? 0 : -1;
  }
  /* The tabs are built by JS, so the panel cannot name one in the static
     document without pointing at an id that does not exist yet. */
  roundBody.setAttribute('aria-labelledby', 'tab-' + activeRound);
}

function syncSegs(){
  const upcoming = roundOf(activeRound)?.state === 'upcoming';
  viewButtons.forEach(b => {
    b.disabled = upcoming;
    b.setAttribute('aria-pressed', String(!upcoming && b.dataset.view === activeView));
  });
}

function selectRound(id, focus){
  const r = roundOf(id);
  if (!r) return;
  activeRound = id;
  syncTrack();
  syncSegs();

  roundH.textContent   = /^\d+$/.test(id) ? 'Round ' + id : r.label;
  /* The cut is not Swiss and is measured in matches, not tables, so the phase
     comes from the data rather than being assumed. */
  const unit = r.tables === 1 ? 'match' : r.phase === 'Top cut' ? 'matches' : 'tables';
  roundSub.textContent =
      r.state === 'live' ? `${r.phase} · ${r.tables} ${unit} · pairings posted ${r.posted}`
    : r.state === 'done' ? `${r.phase} · complete · results final · posted ${r.posted}`
    :                      'Not started · pairings appear here once the previous round finishes';
  renderRound();

  const tab = document.getElementById('tab-' + id);
  if (focus) tab?.focus();
  tab?.scrollIntoView({block:'nearest', inline:'nearest'});
  /* This is where the rail's scroll position and its contents both settle:
     picking a round scrolls it, and rebuilding the track for another format
     ends here too. The scroll event alone would miss both, because neither
     necessarily moves the rail. */
  syncRailEdges();
  say(`${r.label}, ${stateLabel(r.state).toLowerCase()}`);
}

rail.addEventListener('click', e => {
  const chip = e.target.closest('.chip');
  if (chip) selectRound(chip.dataset.id);
});

rail.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const step = {ArrowRight:1, ArrowLeft:-1}[e.key];
  const i = ROUNDS.findIndex(r => r.id === activeRound);
  if (step){
    e.preventDefault();
    selectRound(ROUNDS[(i + step + ROUNDS.length) % ROUNDS.length].id, true);
  } else if (e.key === 'Home'){
    e.preventDefault(); selectRound(ROUNDS[0].id, true);
  } else if (e.key === 'End'){
    e.preventDefault(); selectRound(ROUNDS.at(-1).id, true);
  }
});

/* ============================================================
   6. ROUND PANEL
   ------------------------------------------------------------
   The search box filters these tables too — the pairings caption
   promises it, so it has to be true.
   ============================================================ */
const noMatch = what => `<div class="empty"><h3>No ${esc(what)} match “${esc(query)}”</h3>
  <p>Try another Duelist, or clear the search to see the whole table.</p></div>`;

/* A scrollable region needs to be focusable to be keyboard-scrollable
   (Chrome and Firefox now do this for you; Safari does not). */
const wrapTable = (label, inner) =>
  `<div class="tblwrap" tabindex="0" role="region" aria-label="${esc(label)}">${inner}</div>`;

/* Everyone a pairing names, so searching a Duelist's name finds the team match
   they played in as well as the seat they played it at. */
const named = (p) => [p.a, p.b, ...(p.duels ?? []).flatMap(d => [d.a, d.b])];

function renderPairings(r){
  const rows = (r.pairings ?? []).filter(p => hit(...named(p)));
  if (!rows.length) return noMatch('tables');
  const teams = rows.some(p => p.duels?.length);
  const who = teams ? 'Team' : 'Duelist';
  const caption = r.phase === 'Top cut'
    ? `${esc(r.label)} bracket, seeded from the final Swiss standings.`
    : `Top tables for ${esc(r.label)}.`;
  /* Deck types are published for the cut, where the blog titles the post "with
     Deck Types", and never for Swiss. The columns appear only when the round has
     them: two empty ones on every Swiss round would be worse than none.

     A team event carries them on the duels rather than on the match, because a
     team does not have a Deck -- three Duelists do. */
  const decks = rows.some(p => p.aDeck || p.bDeck
    || (p.duels ?? []).some(d => d.aDeck || d.bDeck));
  const deckHead = decks ? '<th scope="col">Deck</th>' : '';
  const deckCell = (v) => decks ? `<td>${esc(v ?? '')}</td>` : '';
  const rec = (v) => `<td class="rec${v?.confidence !== 'derived' ? ' rec--partial' : ''}">`
    + `${esc(formatRecord(v, {drawsPossible: eventDrawsPossible()}))}</td>`;

  /* A team match is one row, and the three duels played inside it are rows
     beneath, indented and numbered by the table each was played at. Flattened
     into nine hundred rows the round would say who duelled and never say who
     was playing whom. */
  const duels = (p) => (p.duels ?? []).map(d => `<tr class="duel">
      <td class="num">${esc(d.table)}</td>
      <td>${esc(d.a)}</td>${deckCell(d.aDeck)}${decks ? '' : '<td></td>'}
      <td>${esc(d.b)}</td>${deckCell(d.bDeck)}${decks ? '' : '<td></td>'}</tr>`).join('');

  return wrapTable(`Pairings for ${r.label}`, `<table>
    <caption>${caption} Search by ${teams ? 'Duelist or team' : 'Duelist'} to filter this list.</caption>
    <thead><tr>
      <th scope="col" class="num">${r.phase === 'Top cut' ? 'Match' : 'Table'}</th>
      <th scope="col">${who}</th>${deckHead}<th scope="col">Record</th>
      <th scope="col">${who}</th>${deckHead}<th scope="col">Record</th>
    </tr></thead><tbody>
    ${rows.map(p => `<tr${p.duels?.length ? ' class="match"' : ''}>
      <td class="num">${esc(p.table)}</td>
      <td>${esc(p.a)}</td>${deckCell(p.aDeck)}${rec(p.aRec)}
      <td>${esc(p.b)}</td>${deckCell(p.bDeck)}${rec(p.bRec)}</tr>${duels(p)}`).join('')}
    </tbody></table>`);
}

function renderStandings(r){
  /* A cut round has no standings of its own and names the Swiss table it was
     seeded from. Following the reference here rather than copying that table
     into every cut round keeps three copies of the whole field out of the file
     the page downloads on each visit. */
  const source = (r.standings?.length ? r
    : ROUNDS.find(x => String(x.id) === String(r.standingsAfter))) ?? r;
  const rows = (source.standings ?? []).filter(s => hit(s.name, s.deck, ...(s.members ?? [])));
  const teams = rows.some(s => s.members?.length);
  if (!rows.length) return noMatch(teams ? 'teams' : 'Duelists');
  /* Deck and opponent win percentage come from the simulation, which invents
     both. Konami's standings publish rank, name and points, so against real
     coverage these were two permanently empty columns -- and the percentage
     rendered as a bare "%". Each appears only where the data has it. */
  const hasDeck = rows.some(s => s.deck);
  const hasPct = rows.some(s => s.pct !== null && s.pct !== undefined);
  /* And the same rule for the two columns that used to be unconditional. The
     blog does not always publish a points column -- YCS Columbus has none for
     any of its 17 rounds -- and without points there is nothing to derive a
     record from either. Printed anyway, that is 1,618 rows of "?–?" beside
     1,618 rows of "—", two columns wide, saying nothing twice. */
  const hasPoints = rows.some(s => s.points !== null && s.points !== undefined);
  const hasRecord = rows.some(s => s.record && (s.record.wins !== null
                                             && s.record.wins !== undefined));

  return wrapTable(`Standings after round ${r.standingsAfter}`, `<table>
    <caption>${r.phase === 'Top cut'
      ? `Final Swiss standings after round ${esc(r.standingsAfter)}, top eight shown.`
      : `Standings after round ${esc(r.standingsAfter)}, top eight shown.`}</caption>
    <thead><tr>
      <th scope="col" class="num">Place</th><th scope="col">${teams ? 'Team' : 'Duelist'}</th>
      ${hasRecord ? '<th scope="col">Record</th>' : ''}
      ${hasPoints ? '<th scope="col" class="num">Pts</th>' : ''}
      ${hasDeck ? '<th scope="col">Deck</th>' : ''}
      ${hasPct ? '<th scope="col">Opp. win %</th>' : ''}
    </tr></thead><tbody>
    ${rows.map(s => `<tr>
      <th scope="row" class="num">${esc(s.pos)}</th>
      <td>${esc(s.name)}${s.members?.length
        ? `<span class="roster">${esc(s.members.join(', '))}</span>` : ''}</td>
      ${hasRecord ? `<td class="rec${s.record?.confidence !== 'derived' ? ' rec--partial' : ''}">${esc(formatRecord(s.record, {drawsPossible: eventDrawsPossible()}))}</td>` : ''}
      ${hasPoints ? `<td class="rec num">${esc(s.points ?? '—')}</td>` : ''}
      ${hasDeck ? `<td>${esc(s.deck ?? '')}</td>` : ''}
      ${hasPct ? `<td class="rec">${esc(s.pct)}%</td>` : ''}</tr>`).join('')}
    </tbody></table>`);
}

function renderFeature(r){
  if (!r.feature) return `<div class="empty"><h3>No feature match for this round</h3>
    <p>Feature coverage is chosen once the round's top tables are known.</p></div>`;
  const {a, b, note, source} = r.feature;
  /* A scraped feature post is prose and photographs: it names the two Duelists
     and nothing else structured. Joining deck and record unconditionally printed
     a bare " · ?–?" under every name, so each side shows only what is known. */
  const side = (p) => {
    const bits = [];
    if (p.deck) bits.push(esc(p.deck));
    if (p.record) bits.push(esc(formatRecord(p.record, {drawsPossible: eventDrawsPossible()})));
    return `<div class="feature__side"><h3>${esc(p.name)}</h3>`
         + (bits.length ? `<p>${bits.join(' · ')}</p>` : '') + `</div>`;
  };
  return `<div class="feature">
    ${side(a)}
    <div class="feature__vs" aria-hidden="true">VS</div>
    ${side(b)}
  </div>
  <p class="feature__note">${esc(note)}${offsite(source) ? ` <a href="${esc(source)}" rel="external noreferrer">Read the coverage</a>.` : ''}</p>`;
}

function renderRound(){
  if (roundsState === 'loading'){
    roundBody.innerHTML = `<div class="empty"><p class="loading"><i aria-hidden="true"></i>Loading round data…</p></div>`;
    syncPanelTabStop();
    return;
  }
  if (roundsState === 'error'){
    roundBody.innerHTML = `<div class="empty"><h3>Round data could not be loaded</h3>
      <p>${esc(roundsError)}</p>
      <p style="margin-top:1rem"><button type="button" class="btn" data-retry-rounds>Try again</button></p></div>`;
    syncPanelTabStop();
    return;
  }
  const r = roundOf(activeRound);
  if (!r) return;
  if (r.state === 'upcoming'){
    roundBody.innerHTML = `<div class="empty"><h3>This round has not started</h3>
      <p>Pairings appear here once they are posted.</p></div>`;
    syncPanelTabStop();
    return;
  }
  roundBody.innerHTML =
      activeView === 'pairings'  ? renderPairings(r)
    : activeView === 'standings' ? renderStandings(r)
    :                              renderFeature(r);
  syncPanelTabStop();
}

/* APG: a tabpanel gets tabindex="0" only when it contains nothing focusable,
   so keyboard users can still reach its content. The pairings and standings
   views contain a focusable .tblwrap, so keeping it there would create a
   second, redundant tab stop on the way into the table. */
function syncPanelTabStop(){
  const focusable = roundBody.querySelector(
    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (focusable) roundBody.removeAttribute('tabindex');
  else roundBody.tabIndex = 0;
}

roundBody.addEventListener('click', e => {
  if (e.target.closest('[data-retry-rounds]')) refreshRounds();
});

viewButtons.forEach(b => b.addEventListener('click', () => {
  activeView = b.dataset.view;
  syncSegs();
  renderRound();
  say(`Showing ${b.textContent.toLowerCase()}`);
}));

/* ============================================================
   7. COVERAGE LIST — grouped by event, filtered, searchable
   ============================================================ */
/* The page previously had no notion of data that might be absent, failing, or
   already-loaded-but-now-stale. These four states come first; filtering only
   makes sense once there is something to filter. */
/* One tournament's coverage at a time, matching the round track above it: the
   selector says which tournament the page is showing, and a Genesys feature
   match is not part of the Advanced one.

   Only where there is a choice to make. A single-format event hides the
   selector, and filtering on the one format it has would say nothing while
   risking hiding everything if the feed and the round data disagreed on the
   name. Posts with no format are event-wide and always shown.

   And only for the event on screen. The selector chooses between that event's
   tournaments and says nothing about anyone else's: with the archive holding
   four events, reading YCS Montreal's Advanced tournament made the Genesys
   Championship disappear from the coverage list entirely -- every post it has
   is Genesys, and none of them was ever part of the choice being made. */
function inSelectedFormat(post){
  if (post.slug && post.slug !== activeEvent) return true;
  if (!post.format || !hasFormatChoice()) return true;
  return post.format === activeFormat;
}

function renderEvents(){
  if (coverageState === 'loading'){
    countEl.textContent = 'Loading';
    list.innerHTML = `<div class="empty"><p class="loading"><i aria-hidden="true"></i>Loading coverage…</p></div>`;
    return;
  }
  if (coverageState === 'error'){
    countEl.textContent = 'Unavailable';
    list.innerHTML = `<div class="empty"><h3>Coverage could not be loaded</h3>
      <p>${esc(coverageError)}</p>
      <p style="margin-top:1rem"><button type="button" class="btn" data-retry>Try again</button></p></div>`;
    return;
  }
  if (coverageState === 'empty'){
    countEl.textContent = 'No coverage';
    list.innerHTML = `<div class="empty"><h3>No coverage yet</h3>
      <p>The feed is reachable but has no items in it.</p></div>`;
    return;
  }

  /* 'stale' still renders the data we have -- a failed reload must not blank
     the page -- but says so, and offers a way to try again. */
  const staleNote = coverageState === 'stale'
    ? `<div class="notice" role="status"><b>Showing the last coverage that loaded.</b>
         <span>${esc(coverageError)}</span>
         <button type="button" class="btn" data-retry>Try again</button></div>`
    : '';

  const groups = EVENTS.map(ev => ({
    ...ev,
    posts: ev.posts.filter(p =>
      (filter === 'all' || p.kind === filter)
      && inSelectedFormat(p)
      && hit(p.title, ev.event))
  })).filter(ev => ev.posts.length);

  countEl.textContent = groups.length
    ? `${groups.length} event${groups.length > 1 ? 's' : ''} · ${groups.reduce((n,g) => n + g.posts.length, 0)} updates`
    : 'No matches';

  if (!groups.length){
    list.innerHTML = staleNote + `<div class="empty"><h3>Nothing matches that</h3>
      <p>Try a Duelist name, an event, or clear the filter to see everything.</p></div>`;
    return;
  }

  list.innerHTML = staleNote + groups.map((ev, i) => {
    const isOpen = query ? true : open.has(ev.event);
    return `<article class="event">
      <h3 class="event__h">
        <button type="button" class="event__bar" aria-expanded="${isOpen}"
                aria-controls="ev-${i}" data-ev="${esc(ev.event)}">
          <span class="event__date">${esc(ev.date)}</span>
          <span class="event__title">${esc(ev.event)}${ev.live ? ' <span class="livetag livetag--sm"><i aria-hidden="true"></i>Live</span>' : ''}</span>
          <span class="event__n">${esc(ev.posts.length)}</span>
          <svg class="event__caret" width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
        </button>
      </h3>
      <div class="event__body" id="ev-${i}" ${isOpen ? '' : 'hidden'}>
        ${/* The archive holds this event's rounds, and they are not the ones on
              screen. Offered rather than assumed: switching replaces the whole
              panel above, which is not something a reader should get by
              expanding a list. Outside the disclosure button, because a button
              inside a button is not markup. */
          entryFor(ev.slug) && ev.slug !== activeEvent
            ? `<div class="post post--open"><button type="button" class="btn btn--sm"
                 data-open-event="${esc(ev.slug)}">Show this event's rounds</button></div>`
            : ''}
        ${ev.posts.map(p => `<div class="post" style="--k:${kindOf(p.kind).color}">
          <span class="post__k">${esc(kindOf(p.kind).label)}</span>
          ${(() => {
            const to = jumpTarget(p);
            if (to) return `<a class="post__t post__t--jump" href="#round-h"
              data-jump-format="${esc(to.format)}" data-jump-round="${esc(to.round)}"
              data-jump-view="${esc(to.view)}">${esc(p.title)}</a>`;
            return offsite(p.url)
              ? `<a class="post__t" href="${esc(p.url)}" rel="external noreferrer">${esc(p.title)}</a>`
              : `<span class="post__t">${esc(p.title)}</span>`;
          })()}
          <span class="post__time">${esc(p.time)}</span>
        </div>`).join('')}
      </div>
    </article>`;
  }).join('');
}

/* An in-page headline moves the page to the round it names. href="#round-h" is
   real, so the link works with middle-click, keyboard and JavaScript off; the
   handler upgrades it to selecting the right format, round and tab. */
list.addEventListener('click', e => {
  const jump = e.target.closest('[data-jump-round]');
  if (!jump) return;
  e.preventDefault();
  const {jumpFormat, jumpRound, jumpView} = jump.dataset;
  selectFormat(jumpFormat);           // no-op when it is already the one shown
  activeView = jumpView;              // set before selectRound, which renders
  selectRound(jumpRound, true);
  document.getElementById('round-h').scrollIntoView({block: 'start'});
});

/* Delegated once, and it toggles the panel in place rather than
   re-rendering the list — so focus is never destroyed and never
   has to be restored. */
list.addEventListener('click', e => {
  if (e.target.closest('[data-retry]')){ refreshCoverage(); return; }
  const opener = e.target.closest('[data-open-event]');
  if (opener){
    selectEvent(opener.dataset.openEvent)
      .then(() => document.getElementById('live-h').scrollIntoView({block: 'start'}));
    return;
  }
  const bar = e.target.closest('.event__bar');
  if (!bar) return;
  const name = bar.dataset.ev;
  const panel = document.getElementById(bar.getAttribute('aria-controls'));
  const willOpen = !(bar.getAttribute('aria-expanded') === 'true');
  willOpen ? open.add(name) : open.delete(name);
  bar.setAttribute('aria-expanded', String(willOpen));
  if (panel) panel.hidden = !willOpen;
});

/* Footer jumps. The href is a real fragment, so without JS these still land on
   the coverage section -- just unfiltered. With JS they also apply the filter,
   which is the only reason the label is honest. */
function applyFilter(kind){
  filter = kind;
  document.querySelectorAll('[data-filter]').forEach(x =>
    x.setAttribute('aria-pressed', String(x.dataset.filter === filter)));
  renderEvents();
  say(countEl.textContent);
}

document.addEventListener('click', e => {
  const jump = e.target.closest('[data-jump]');
  if (!jump) return;
  applyFilter(jump.dataset.jump);   // the browser still handles the #coverage hop
});

document.querySelectorAll('[data-filter]').forEach(b =>
  b.addEventListener('click', () => applyFilter(b.dataset.filter)));

let searchTimer;
function runSearch(){
  const next = qEl.value.trim().toLowerCase();
  if (next === query) return;
  query = next;
  renderEvents();
  renderRound();
  say(countEl.textContent);
}
qEl.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 250);
});

/* "/" jumps to search, Escape clears it */
document.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
  const ae = document.activeElement;
  const typing = ae && (/^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName) || ae.isContentEditable);

  if (e.key === '/' && !typing){
    e.preventDefault();
    qEl.focus();
    qEl.select();
  } else if (e.key === 'Escape' && ae === qEl && qEl.value){
    e.preventDefault();
    clearTimeout(searchTimer);        // do not let a queued render undo this
    qEl.value = '';
    runSearch();
  }
});

/* ============================================================
   8. POLITE ANNOUNCEMENTS
   ------------------------------------------------------------
   One shared timer, so rapid arrow-keying collapses to a single
   announcement instead of a pile-up that clobbers itself.
   ============================================================ */
let sayTimer;
function say(msg){
  clearTimeout(sayTimer);
  liveRegion.textContent = '';
  sayTimer = setTimeout(() => { liveRegion.textContent = msg; }, 60);
}

/* ============================================================
   9. THE HERO STAMP
   ------------------------------------------------------------
   The time comes from the feed's own <lastBuildDate>. The label
   re-renders on a slow tick so it ages correctly while the page
   sits open; that ticks the label only, and the polling in
   section 10 is what actually refetches.
   ============================================================ */
const stampEl = document.getElementById('stamp');
const RTF = new Intl.RelativeTimeFormat(undefined, {numeric:'auto'});

function relativeTime(then, now = new Date()){
  const secs = Math.round((then - now) / 1000);
  const abs  = Math.abs(secs);
  if (abs < 60)    return RTF.format(secs, 'second');
  if (abs < 3600)  return RTF.format(Math.round(secs / 60), 'minute');
  if (abs < 86400) return RTF.format(Math.round(secs / 3600), 'hour');
  return RTF.format(Math.round(secs / 86400), 'day');
}

function renderStamp(){
  if (!feedUpdated){
    stampEl.textContent = coverageState === 'loading'
      ? 'Loading coverage…'
      : 'Coverage unavailable';
    return;
  }
  /* <time> wraps only the timestamp. Wrapping the whole sentence would leave a
     <time> whose text is not a valid time, which is a validation error. */
  stampEl.innerHTML = `Updated <time datetime="${esc(feedUpdated.toISOString())}">`
    + `${esc(relativeTime(feedUpdated))}</time> · refreshes automatically`;
}
setInterval(renderStamp, 60000);

/* ============================================================
   10. POLLING
   ------------------------------------------------------------
   A recursive timeout rather than setInterval, so a slow response
   can never let a second request overlap the first, plus an
   in-flight guard because visibility changes and the retry button
   can both fire mid-poll.

   Nothing repaints unless an ETag actually changed -- see
   loadCoverage() for why the status code cannot tell us that.
   ============================================================ */
const POLL_LIVE_MS = 60000;    // something is in progress
const POLL_IDLE_MS = 300000;   // nothing live: still check, far less often
const POLL_MAX_MS  = 600000;   // failure backoff ceiling

let pollTimer = null;
let pollDelay = POLL_LIVE_MS;
let pollInFlight = false;

const somethingLive = () =>
  EVENTS.some(e => e.live) || ROUNDS.some(r => r.state === 'live');

async function pollOnce(){
  if (pollInFlight || document.hidden) return {skipped: true};
  pollInFlight = true;
  try {
    /* Settled, not all: one resource failing must not cancel the other. */
    const [cov, rnd] = await Promise.allSettled([
      refreshCoverage({poll: true}),
      refreshRounds({poll: true}),
    ]);
    const failed = [cov, rnd].some(r =>
      r.status === 'rejected' || r.value?.failed || roundsState === 'error');
    return {failed, changed: !!(cov.value?.changed || rnd.value?.changed)};
  } finally {
    pollInFlight = false;
  }
}

function schedulePoll(failed){
  clearTimeout(pollTimer);
  if (document.hidden){ pollTimer = null; return; }
  pollDelay = failed
    ? Math.min(Math.max(pollDelay, POLL_LIVE_MS) * 2, POLL_MAX_MS)   // back off
    : (somethingLive() ? POLL_LIVE_MS : POLL_IDLE_MS);               // reset
  pollTimer = setTimeout(runPoll, pollDelay);
}

async function runPoll(){
  const result = await pollOnce();
  schedulePoll(!!result.failed);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden){
    clearTimeout(pollTimer);
    pollTimer = null;
    return;
  }
  /* Back in view: a tab left open overnight should not sit on yesterday's
     data for another minute. Check now, and reset any accumulated backoff. */
  pollDelay = POLL_LIVE_MS;
  runPoll();
});

/* boot */
applyTheme();
renderEventMeta();
renderRound();      // paints the loading state before either fetch lands
renderStamp();
Promise.allSettled([
  refreshRounds(),  // independent of the feed: one failing must not block the other
  refreshCoverage(),
]).then(() => schedulePoll(false));
