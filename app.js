/* ============================================================
   0. HELPERS
   ============================================================ */

/* esc(), safeUrl() and offsite() live in common.js, which every page loads:
   they are the same job on the winners list as they are here. */

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


/* Section 1, the theme, is in common.js -- the winners page needs it too. */


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
  feature  : {label:'Feature Match', color:'var(--c-feature)'},
  result   : {label:'Result',        color:'var(--c-result)'},
  news     : {label:'Announcement',  color:'var(--c-news)'},
  deck     : {label:'Deck Profile',  color:'var(--c-deck)'}
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

/* Coverage type. The same questions the scraper asks in parse.detect_kind,
   in the same order, giving the same answers -- test/fixtures/kinds.json is
   read by both suites so the two cannot drift again. They had drifted over
   403 of the archive's 8,076 titles: this rule read "Public Events winners"
   as news, because it asked for a singular winner, and filed "QQ: What Decks
   were you expecting to see this weekend" under deck profiles, because it
   asked for the bare word "deck".

   Order is the rule, not a detail. "Top 32 Pairings and Deck Lists" is a
   bracket that also prints decks, and the bracket is the part worth having;
   "Winner Deck Lists" is a decklist post about a winner. So pairings is asked
   before deck, and deck before result.

   Singular and plural throughout: the blog titles a final "Final Pairing" and
   a multi-winner post "Winners". Titles with no keyword at all fall back to
   'news' rather than guess. */
function kindFrom(t){
  if (/\bpairings?\b/.test(t))                                                 return 'pairings';
  if (/\bstandings\b|\bpoint totals\b/.test(t))                                return 'standings';
  // Not "Final Match": those posts carry the final's pairing table, and the
  // builder reads a feature match as a write-up rather than a round. See
  // parse.KINDS -- calling them feature cost an event its champion.
  if (/\bfeature match\b|\bmatch:\s/.test(t))                                    return 'feature';
  // Any post about the decks played. What comes out is not a phrasing but
  // three series that are about decks without covering any: QQ, the reader
  // question column; the Structure Deck and game mat products; and Deck
  // Update, a set announcement. Deck check is a floor penalty.
  if (/\bdecks?\b|\bdeck ?lists?\b|\bdeck ?profiles?\b/.test(t)
      && !/\bqq\b|\bstructure deck\b|\bdeck check\b|\bdeck update\b|\bgame mat\b|\btech update\b/.test(t))
                                                                              return 'deck';
  if (/\bwinners?\b|\bchampions?\b|\bcongratulations\b|\bundefeated\b/.test(t)) return 'result';
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

/* ?event=<slug>, where the winners list sends a reader and where a link to one
   event rather than to the site comes from.

   Only consulted when there is no event on screen, which is the first load and
   nothing else: a poll leaves a reader's choice alone because the choice is
   still valid, not because this refuses to answer twice.

   Ignored unless the archive actually holds it. A slug that is not there would
   otherwise show an empty page for a URL that looks deliberate. */
function wantedEvent(){
  try {
    const want = new URLSearchParams(location.search).get('event');
    return want && CATALOG.some(e => e.slug === want) ? want : null;
  } catch { return null; }
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
    if (!activeEvent || !entryFor(activeEvent)) activeEvent = wantedEvent() ?? CATALOG[0].slug;

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
/* How many events the list shows before asking. Fifty-two is a long way to
   scroll past to reach anything else on the page. */
const COVERAGE_SHOWN = 5;
let coverageAll = false;
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
  if (!coverageEvents().length){ coverageState = 'loading'; renderEvents(); }
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
    /* An empty feed is no longer an empty page: the list is the archive, and
       the feed only says what is new. "No coverage" means no events at all. */
    coverageState = coverageEvents().length ? 'ready' : 'empty';
    coverageError = '';
    /* Open the newest event on first load instead of hardcoding its name. */
    if (!open.size && coverageEvents().length) open.add(coverageEvents()[0].event);
  } catch (err) {
    /* A failed reload must never blank data the reader already has. */
    coverageState = coverageEvents().length ? 'stale' : 'error';
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

/* ---- an event's own coverage ---------------------------------------------
   The feed is one river of the newest three hundred posts across the whole
   archive, which is the right shape for a reader subscribing to it and the
   wrong one for a page listing fifty-two events: only the five most recent had
   any items in it at all, so forty-seven events showed no coverage whatever.

   Every event publishes its own posts beside its rounds, so the list is built
   from the archive and each event's posts are fetched when its group is opened.
   The feed still says when the site last updated and which events are running;
   it is no longer where the list comes from. */
const POSTS = new Map();          // slug -> the event's posts, once fetched
const loadingPosts = new Set();

/* Beside the rounds, which is the archive's layout: events/<slug>/rounds.json
   and events/<slug>/posts.json. */
const postsPath = (entry) => entry.path.replace(/rounds\.json$/, 'posts.json');

async function loadEventPosts(slug){
  const entry = entryFor(slug);
  if (!entry || POSTS.has(slug) || loadingPosts.has(slug)) return;
  loadingPosts.add(slug);
  try {
    const res = await fetch(postsPath(entry), {cache: 'no-cache'});
    if (!res.ok) throw new Error(`posts responded ${res.status}`);
    POSTS.set(slug, asCoveragePosts(await res.json()));
  } catch {
    /* An event whose posts will not load shows none rather than an error in
       the middle of a list: the rounds above it are the page's actual subject
       and they are already on screen. */
    POSTS.set(slug, []);
  } finally {
    loadingPosts.delete(slug);
    renderEventsKeepingFocus();
  }
}

/* The same shape groupFeed produces, so the renderer does not care which of
   them a post came from. */
function asCoveragePosts(raw){
  return (Array.isArray(raw) ? raw : []).map(p => {
    const when = p.modified && !isNaN(Date.parse(p.modified)) ? new Date(p.modified) : null;
    const headline = eventHeadline(p.event ?? '', p.title ?? '');
    return {
      title: headline,
      format: p.format ?? null,
      slug: p.slug ?? null,
      url: safeUrl(p.url ?? '#'),
      time: when ? when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '',
      date: when,
      ...classify(headline),
    };
  }).sort((a, b) => (b.date ?? 0) - (a.date ?? 0));
}

/* "YCS Montréal: Round 9 Pairings" -> "Round 9 Pairings". The event is the
   heading directly above the row, so repeating it in every post is noise --
   the same reasoning groupFeed applies to the feed's own titles. */
function eventHeadline(event, title){
  return event && title.startsWith(`${event}:`)
    ? title.slice(event.length + 1).trim() || title
    : title;
}

/* Every event in the archive, newest first, each with whatever of its posts are
   to hand.

   The feed has already been fetched and holds the newest few events' posts, so
   those are shown straight away and stand in until the event's own file
   arrives -- the feed's set is only the part of it that fitted in three hundred
   items, so it is a head start rather than an answer.

   An event the feed names but the archive does not is kept as well. It should
   not happen, since the feed is built from the archive, and if it ever does the
   coverage is real and hiding it would be the wrong way round. */
function coverageEvents(){
  const fromFeed = new Map();
  for (const g of EVENTS) fromFeed.set(g.slug ?? g.event, g);

  const out = CATALOG.map(e => {
    const feed = fromFeed.get(e.slug);
    fromFeed.delete(e.slug);
    return {
      event: e.event,
      slug: e.slug,
      date: eventDate(e.updated)?.toLocaleDateString('en-GB',
        {day: 'numeric', month: 'short', year: 'numeric'}) ?? '',
      live: !!feed?.live,
      loaded: POSTS.has(e.slug) || !!feed,
      complete: POSTS.has(e.slug),
      posts: POSTS.get(e.slug) ?? feed?.posts ?? [],
      /* What the manifest says the event has, which is not the same as what is
         to hand: an unopened event has a count and no posts. */
      total: e.postCount,
    };
  });
  for (const g of fromFeed.values())
    out.push({...g, loaded: true, complete: true, total: g.posts.length});
  return out;
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
/* Which tournament the coverage list is showing, across every event. Separate
   from activeFormat, which is the round track's and belongs to one event: this
   one survives changing events, because "show me the Genesys coverage" is a
   question about the archive and not about YCS Montreal. */
let formatFilter = 'all';
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
  renderChampion();

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

/* ---- archetype export ------------------------------------------------------
   One round at a time, on purpose. Four of YCS Montreal's eight Top 8 Duelists
   also played its Top 4 and its Final, so a count over "the top cut" would
   report the finalists three times each and nobody would be able to tell.

   Within a round the arithmetic is exact: each Duelist holds one seat and each
   seat names one deck, so counting seats counts Duelists. A team event carries
   its decks on the duels rather than on the match, because a team does not have
   a deck -- three Duelists do -- and those are the seats there. */
function archetypeCounts(r){
  const counts = new Map();
  for (const p of r.pairings ?? []){
    const seats = p.duels?.length
      ? p.duels.flatMap(d => [d.aDeck, d.bDeck])
      : [p.aDeck, p.bDeck];
    for (const deck of seats){
      if (!deck) continue;              // a seat whose deck was never published
      counts.set(deck, (counts.get(deck) ?? 0) + 1);
    }
  }
  /* Commonest first, then alphabetically, so the same round exports the same
     file twice running and two exports can be diffed. */
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                    .map(([archetype, count]) => ({archetype, count}));
}

/* The whole published cut, as one object. A Duelist who reached the Final is
   seated in the Top 8, the Top 4 and the Final, so counting the rounds together
   would report the finalists three times each -- 4 of YCS Montreal's 8 Top 8
   Duelists are in more than one of its rounds.
   
   So each Duelist is counted once, with the deck they were first published
   holding. The widest round comes first, which is the one everybody is in, and
   that makes this the breakdown of the cut as it was entered. */
function topCutArchetypes(){
  const rounds = (formatOf(activeFormat)?.rounds ?? [])
    .filter(r => r.phase === 'Top cut' && (r.pairings ?? []).length);
  const deckOf = new Map();
  for (const r of rounds){
    for (const p of r.pairings){
      const seats = p.duels?.length
        ? p.duels.flatMap(d => [[d.a, d.aDeck], [d.b, d.bDeck]])
        : [[p.a, p.aDeck], [p.b, p.bDeck]];
      for (const [who, deck] of seats){
        if (who && deck && !deckOf.has(who)) deckOf.set(who, deck);
      }
    }
  }
  const counts = new Map();
  for (const deck of deckOf.values()) counts.set(deck, (counts.get(deck) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                    .map(([archetype, count]) => ({archetype, count}));
}

function exportName(label){
  const event = (eventInfo?.event?.name ?? 'event').toLowerCase();
  return `${event} ${activeFormat ?? ''} ${label} archetypes`
    .replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase() + '.json';
}

function renderExport(r){
  const one = document.getElementById('export-archetypes');
  const all = document.getElementById('export-top-cut');
  if (one){
    const rows = r ? archetypeCounts(r) : [];
    one.hidden = rows.length === 0;
    if (!one.hidden){
      const seats = rows.reduce((n, x) => n + x.count, 0);
      one.textContent = 'Export Round Archetypes';
      one.setAttribute('aria-label',
        `Export the ${rows.length} archetypes across ${seats} Duelists in ${r.label} as JSON`);
    }
  }
  if (all){
    const rows = topCutArchetypes();
    /* Hidden where it would only repeat the button beside it: an event whose
       cut is one published round has nothing to compile. */
    const cut = (formatOf(activeFormat)?.rounds ?? [])
      .filter(x => x.phase === 'Top cut' && (x.pairings ?? []).length);
    all.hidden = rows.length === 0 || cut.length < 2;
    if (!all.hidden){
      const duelists = rows.reduce((n, x) => n + x.count, 0);
      all.textContent = 'Export Top Cut Archetypes';
      all.setAttribute('aria-label',
        `Export the ${rows.length} archetypes across ${duelists} Duelists in the top cut as JSON`);
    }
  }
}

function download(rows, name){
  /* A blob and an object URL: the file is made here and never leaves the
     browser, which is the whole of what was asked for -- an export, not a
     link between two sites. */
  const blob = new Blob([JSON.stringify(rows, null, 2) + '\n'],
                        {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

document.addEventListener('click', e => {
  if (e.target.closest('#export-archetypes')){
    const r = roundOf(activeRound);
    if (r) download(archetypeCounts(r), exportName(r.label));
  } else if (e.target.closest('#export-top-cut')){
    download(topCutArchetypes(), exportName('top cut'));
  }
});

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
  /* A duel has no record of its own -- the record belongs to the team -- but
     it still has to occupy the column, or every cell after it shifts left. A
     round with deck types has seven columns and this row was emitting five,
     so the second Duelist landed under Record and their deck under Team. */
  const duels = (p) => (p.duels ?? []).map(d => `<tr class="duel">
      <td class="num">${esc(d.table)}</td>
      <td>${withPlace(d.a)}</td>${deckCell(d.aDeck)}<td></td>
      <td>${withPlace(d.b)}</td>${deckCell(d.bDeck)}<td></td></tr>`).join('');

  return wrapTable(`Pairings for ${r.label}`, `<table>
    <caption>${caption} Search by ${teams ? 'Duelist or team' : 'Duelist'} to filter this list.</caption>
    <thead><tr>
      <th scope="col" class="num">${r.phase === 'Top cut' ? 'Match' : 'Table'}</th>
      <th scope="col">${who}</th>${deckHead}<th scope="col">Record</th>
      <th scope="col">${who}</th>${deckHead}<th scope="col">Record</th>
    </tr></thead><tbody>
    ${rows.map(p => `<tr${p.duels?.length ? ' class="match"' : ''}>
      <td class="num">${esc(p.table)}</td>
      <td>${withPlace(p.a)}</td>${deckCell(p.aDeck)}${rec(p.aRec)}
      <td>${withPlace(p.b)}</td>${deckCell(p.bDeck)}${rec(p.bRec)}</tr>${duels(p)}`).join('')}
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
      <td>${withPlace(s.name)}${s.members?.length
        ? `<span class="roster">${esc(s.members.join(', '))}</span>` : ''}</td>
      ${hasRecord ? `<td class="rec${s.record?.confidence !== 'derived' ? ' rec--partial' : ''}">${esc(formatRecord(s.record, {drawsPossible: eventDrawsPossible()}))}</td>` : ''}
      ${hasPoints ? `<td class="rec num">${esc(s.points ?? '—')}</td>` : ''}
      ${hasDeck ? `<td>${esc(s.deck ?? '')}</td>` : ''}
      ${hasPct ? `<td class="rec">${esc(s.pct)}%</td>` : ''}</tr>`).join('')}
    </tbody></table>`);
}

/* A round can carry several. 102 of the 357 rounds with a feature match have
   more than one and YCS Montreal's Top 4 had three, so all of them are shown.

   `r.feature` is what the builder wrote before it kept them all. Reading it
   here keeps the panel working for the events still holding the old shape,
   between this deploying and the archive being rebuilt; it can go once nothing
   in events/ has a `feature` key. */
function roundFeatures(r){
  return r.features || (r.feature ? [r.feature] : []);
}

function renderFeature(r){
  const features = roundFeatures(r);
  if (!features.length) return `<div class="empty"><h3>No feature match for this round</h3>
    <p>Feature coverage is chosen once the round's top tables are known.</p></div>`;
  /* A scraped feature post is prose and photographs: it names the two Duelists
     and nothing else structured. Joining deck and record unconditionally printed
     a bare " · ?–?" under every name, so each side shows only what is known. */
  const side = (p) => {
    const bits = [];
    if (p.deck) bits.push(esc(p.deck));
    if (p.record) bits.push(esc(formatRecord(p.record, {drawsPossible: eventDrawsPossible()})));
    return `<div class="feature__side"><h3>${withPlace(p.name)}</h3>`
         + (bits.length ? `<p>${bits.join(' · ')}</p>` : '') + `</div>`;
  };
  const one = ({a, b, note, source}) => `<div class="feature">
    ${side(a)}
    <div class="feature__vs" aria-hidden="true">VS</div>
    ${side(b)}
  </div>
  <p class="feature__note">${esc(note)}${offsite(source) ? ` <a href="${esc(source)}" rel="external noreferrer">Read the coverage</a>.` : ''}</p>`;
  /* Counted only where there is more than one, so the ordinary round reads the
     way it always did rather than gaining a heading saying "1 of 1". */
  if (features.length === 1) return one(features[0]);
  return `<p class="feature__count">${features.length} feature matches published for this round.</p>`
       + features.map(f => `<div class="feature__one">${one(f)}</div>`).join('');
}

/* ---- who won -------------------------------------------------------------
   Shown on the last round the event published, and nowhere else. Usually the
   final; where coverage stopped at the semis there is no final to hang it on,
   and the deepest round is where the bracket ends for whoever is reading.

   Hidden until asked for. The rounds above it are worth reading first, and a
   result printed beside them takes that away from anyone who wanted to follow
   the bracket down. */
const champEl = document.getElementById('champion');

/* Which tournament the reader asked to be told about, rather than whether they
   asked. A plain flag stayed true when the event changed, so revealing one
   champion gave away the next event's before its bracket had been read -- on
   the one page whose whole point is that the ending is not printed beside the
   rounds. Resetting the flag wherever the tournament changes is two lines in
   two functions today and one missed line the next time a third way of
   changing it is added; a reveal that names its own tournament cannot leak
   into another however the reader got there. Formats count separately: each is
   its own tournament with its own champion. */
let championFor = null;
const tournamentKey = () => `${activeEvent}\u0000${activeFormat}`;
const championShown = () => championFor !== null && championFor === tournamentKey();

const deepestRound = () => ROUNDS[ROUNDS.length - 1];

/* How far each Duelist got, beside their name wherever the round tables print
   it: champion, runner-up, or the top cut they reached.

   Only once the champion has been revealed. The whole point of hiding them is
   that the rounds above are worth reading first, and a badge in the Top 4
   pairings gives the ending away as plainly as printing the name would --
   which is the leak #179 closed between events and would reopen inside one.
   A runner-up badge says who did not win, which gives away as much.

   And only where the archive can point to the Duelist without doubt. Two
   Duelists share a name more often than a bracket is wrong: YCS Hartford's
   Top 32 seats a Pascal Manigat in two different matches, and badging by name
   alone would badge whichever one went out first. The builder already knows
   -- it refuses to derive a record for a name it cannot tell apart -- so a
   name it never derived a record for is one this cannot safely point at. */
const places = new Map();

/* Who finished where, as far as the coverage actually says.

   The runner-up is the other Duelist in the final, and is only knowable when
   the final's own pairing was published: 36 of the archive's 142 tournaments.
   The rest announce a winner without it.

   Everyone else in the Top 4 is badged as having reached it, and not as third
   or fourth. They did not play off -- there is no third place match -- so
   there is no third and fourth, there are two thirds, and where the final is
   missing the runner-up is among them too. A badge saying "Top 4" is true;
   one saying "3rd" is a guess. */
function placementsIn(fmt){
  const key = `${activeEvent}\u0000${fmt.format}`;
  if (places.has(key)) return places.get(key);

  const derived = new Set();
  const round = (label) => (fmt.rounds ?? []).find(r => r.label === label);
  const seats = (r) => (r?.pairings ?? []).flatMap(p => [p.a, p.b]).filter(Boolean);
  for (const r of fmt.rounds ?? []){
    for (const p of r.pairings ?? []){
      if (p.a && p.aRec) derived.add(p.a);
      if (p.b && p.bRec) derived.add(p.b);
    }
    for (const st of r.standings ?? []){
      if (st.name && st.record && st.record.wins !== null
          && st.record.wins !== undefined) derived.add(st.name);
    }
  }

  const out = new Map();
  const won = fmt.champion;
  if (won && derived.has(won)) out.set(won, 'champion');

  const final = seats(round('Final'));
  const top4 = seats(round('Top 4'));
  if (won && final.length === 2 && final.includes(won)){
    const second = final.find(n => n !== won);
    if (second && derived.has(second)) out.set(second, 'runner-up');
  }
  for (const n of top4){
    if (!out.has(n) && derived.has(n)) out.set(n, 'top 4');
  }
  places.set(key, out);
  return out;
}

/* The badge's markup, or nothing. A word rather than a glyph: an emoji is the
   one mark whose appearance the page does not control, and it reads as
   clutter in a column of names. The word is also its own accessible name, so
   nothing here depends on colour or shape.

   Highest only, which the map gives for free: a Duelist holds one place. */
function placeBadge(name){
  if (!name || !championShown()) return '';
  const fmt = formatOf(activeFormat);
  if (!fmt) return '';
  const place = placementsIn(fmt).get(name);
  if (!place) return '';
  return ` <span class="place place--${place.replace(/\W+/g, '')}">${esc(place)}</span>`;
}

/* A name as the tables print it, with its placement where it belongs. */
const withPlace = (v) => `${esc(v)}${placeBadge(v)}`;

/* What they won with, from the round they won it in. Only where the coverage
   published deck types, which it does for the cut and not for Swiss. */
function championDeck(name){
  for (const p of deepestRound()?.pairings ?? []){
    if (p.a === name) return p.aDeck;
    if (p.b === name) return p.bDeck;
  }
  return null;
}

/* Who played for the winning team, from the round they won it in. A team has
   no deck of its own -- three Duelists do -- and the duels are where they are. */
function championRoster(name){
  for (const p of deepestRound()?.pairings ?? []){
    const side = p.a === name ? 'a' : (p.b === name ? 'b' : null);
    if (!side) continue;
    return (p.duels ?? []).filter(d => d[side])
      .map(d => ({ name: d[side], deck: d[side + 'Deck'] ?? null }));
  }
  return [];
}

function renderChampion(){
  const won = formatOf(activeFormat)?.champion;
  const here = won && deepestRound() && activeRound === deepestRound().id;
  if (!champEl) return;
  champEl.hidden = !here;
  if (!here){ champEl.innerHTML = ''; return; }

  const deck = championDeck(won);
  /* A team champion is a name the reader cannot do anything with -- the three
     Duelists are who won it. Only once the champion is revealed: the roster
     names them, and showing it beside a hidden champion would give the
     ending away to a reader who asked not to be told. */
  const roster = championRoster(won);
  champEl.innerHTML = championShown()
    ? `<span class="champ__k">Champion</span>
       <b class="champ__n">${esc(won)}</b>
       ${deck ? `<span class="champ__d">${esc(deck)}</span>` : ''}
       ${roster.length ? `<button type="button" class="roster-open" data-roster
           aria-haspopup="dialog">Roster</button>` : ''}
       <button type="button" class="btn btn--sm" data-champ aria-expanded="true">Hide</button>`
    : `<span class="champ__k">Champion</span>
       <button type="button" class="btn btn--sm" data-champ aria-expanded="false">Reveal</button>
       <span class="champ__h">hidden until you ask</span>`;
}

champEl?.addEventListener('click', e => {
  if (e.target.closest('[data-roster]')){
    const won = formatOf(activeFormat)?.champion;
    openRoster({ name: won, members: championRoster(won),
                 note: `Decks as published for ${deepestRound()?.label ?? 'the cut'}.` });
    return;
  }
  if (!e.target.closest('[data-champ]')) return;
  championFor = championShown() ? null : tournamentKey();
  renderChampion();
  /* And the tables, which mark the champion wherever they name them. Only
     this strip was redrawn before, so a reveal put the name in the heading
     and left the round below it uncrowned until something else happened to
     redraw it. */
  renderRound();
  /* Focus survives the rewrite: the button is the thing that was just used,
     and a reader on the keyboard would otherwise be returned to the top. */
  champEl.querySelector('[data-champ]')?.focus();
  say(championShown()
    ? `Champion: ${formatOf(activeFormat)?.champion}`
    : 'Champion hidden');
});

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
  renderExport(r);
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

  renderFormatFilters();

  /* An event stays in the list when its own name matches, even before its
     posts are fetched -- otherwise searching would hide every event that
     happens not to be open yet. */
  const matching = coverageEvents().map(ev => ({
    ...ev,
    posts: ev.posts.filter(p =>
      (filter === 'all' || p.kind === filter) && inChosenFormat(p)
      && inSelectedFormat(p) && hit(p.title, ev.event)),
  })).filter(ev => ev.posts.length || (!ev.loaded && hit(ev.event)));

  /* A handful to begin with, and the rest on request. Fifty-two events is a
     long way to scroll past to reach anything else on the page. */
  const groups = coverageAll ? matching : matching.slice(0, COVERAGE_SHOWN);
  const hidden = matching.length - groups.length;

  /* The total is the archive's, taken from the manifest, rather than a tally of
     whatever has been opened -- a figure that climbed as you read would be
     worse than none. A search or a kind filter works on post titles, and only
     an event whose posts have been fetched has any, so those report what they
     actually matched instead of a total they cannot yet know. */
  const narrowed = !!query || filter !== 'all';
  const posts = matching.reduce(
    (n, g) => n + (narrowed ? g.posts.length : (g.total ?? g.posts.length)), 0);
  countEl.textContent = matching.length
    ? `${matching.length} event${matching.length > 1 ? 's' : ''} · ${posts.toLocaleString()} `
      + (narrowed ? 'matching' : `update${posts === 1 ? '' : 's'}`)
    : 'No matches';

  if (!groups.length){
    list.innerHTML = staleNote + `<div class="empty"><h3>Nothing matches that</h3>
      <p>Try a Duelist name, an event, or clear the filter to see everything.</p></div>`;
    return;
  }

  const more = hidden
    ? `<p class="more"><button type="button" class="btn" data-show-all>Show all ${
         esc(matching.length)} events</button></p>`
    : '';

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
        ${!ev.loaded ? `<p class="post loading"><i aria-hidden="true"></i>Loading coverage…</p>` : ''}
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
  }).join('') + more;

  /* Whatever is open needs its posts. Asked for after rendering rather than
     before, so an event that is merely listed costs nothing. */
  for (const ev of groups) if (!ev.complete && open.has(ev.event)) loadEventPosts(ev.slug);
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
  if (e.target.closest('[data-show-all]')){ coverageAll = true; renderEvents(); return; }
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
  /* Opened in place without re-rendering, so the posts are asked for here as
     well as after a render -- this is the path a reader actually takes. */
  if (willOpen){
    const ev = coverageEvents().find(x => x.event === name);
    if (ev && !ev.complete) loadEventPosts(ev.slug);
  }
});

/* Footer jumps. The href is a real fragment, so without JS these still land on
   the coverage section -- just unfiltered. With JS they also apply the filter,
   which is the only reason the label is honest. */
/* A post with no format is event-wide -- an announcement, a table of contents,
   the winner -- and belongs to whichever tournament you are reading about, so
   it is never filtered out. Filtering it away hid every winner announcement
   the moment anybody chose a format. */
function inChosenFormat(post){
  return formatFilter === 'all' || !post.format || post.format === formatFilter;
}

/* The formats the loaded coverage actually has, in the order the buttons show
   them. Read from the posts, so a format the archive has never seen cannot get
   a button and one it gains does not need a code change. */
function formatsPresent(){
  const seen = new Set();
  for (const ev of coverageEvents()) for (const p of ev.posts || []) if (p.format) seen.add(p.format);
  return [...seen].sort();
}

/* An event's posts are fetched when it is opened, so the formats on offer grow
   as the reader reads. The row is rewritten only when the set of them actually
   changes -- rebuilding it on every render would take the focus off the button
   somebody just pressed, every minute, when the poll comes back. */
let formatButtons = '';
function renderFormatFilters(){
  const box = document.getElementById('format-filters');
  if (!box) return;
  const present = formatsPresent();
  const key = present.join('\u0000');
  if (key === formatButtons) return;
  formatButtons = key;
  /* One format is not a choice, and a row of buttons that cannot change the
     list is a control that lies about what it does. */
  box.hidden = present.length < 2;
  if (box.hidden){ box.innerHTML = ''; return; }
  box.innerHTML = [['all', 'Every Format'], ...present.map(f => [f, f])]
    .map(([value, label]) =>
      `<button type="button" data-feed-format="${esc(value)}" aria-pressed="${
        String(value === formatFilter)}">${esc(label)}</button>`).join('');
}

/* data-feed-format, not data-format: the round track's buttons already own
   that attribute, and a handler on it would have made choosing a tournament to
   read also filter the coverage list -- and choosing a coverage filter also
   change the round track. Two controls, two names. */
function applyFormatFilter(name){
  formatFilter = name;
  document.querySelectorAll('[data-feed-format]').forEach(x =>
    x.setAttribute('aria-pressed', String(x.dataset.feedFormat === formatFilter)));
  renderEvents();
  say(countEl.textContent);
}

document.addEventListener('click', e => {
  const b = e.target.closest('[data-feed-format]');
  if (b) applyFormatFilter(b.dataset.feedFormat);
});

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

/* ============================================================
   9. UPCOMING EVENTS — the schedule, which the blog does not carry
   ------------------------------------------------------------
   The blog covers a tournament while it happens and says nothing
   before it, so what is next comes from Konami's own listing and
   is read every few months rather than every few minutes.

   Which of them are still to come is decided here rather than in
   the file. A file written in October and read in December would
   otherwise call a November tournament upcoming: the dates are a
   fact about the event, "upcoming" is a fact about when you look.
   ============================================================ */
const upcomingEl = document.getElementById('upcoming');

/* Local midnight. An event is upcoming all through its last day rather than
   until the moment the clock passes its start. */
const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };

const asDay = iso => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso ?? ''));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
};

function stillToCome(events, now){
  return (Array.isArray(events) ? events : []).filter(e => {
    /* Judged on the last day it runs, so a tournament is not dropped from the
       list on the morning of its final round. An open-ended run -- the
       promotions with a start and no end -- is judged on its start. */
    const last = asDay(e?.ends) ?? asDay(e?.starts);
    return last && last >= now;
  });
}

/* "16–18 Oct 2026", or a single day where that is all there is. */
function whenText(e){
  const from = asDay(e.starts), to = asDay(e.ends);
  if (!from) return '';
  const opts = {day: 'numeric', month: 'short', year: 'numeric'};
  if (!to || +to === +from) return from.toLocaleDateString('en-GB', opts);
  const sameMonth = from.getMonth() === to.getMonth() && from.getFullYear() === to.getFullYear();
  return sameMonth
    ? `${from.getDate()}–${to.toLocaleDateString('en-GB', opts)}`
    : `${from.toLocaleDateString('en-GB', {day: 'numeric', month: 'short'})} – `
      + to.toLocaleDateString('en-GB', opts);
}

const UPCOMING_SHOWN = 4;

function renderUpcoming(events){
  if (!upcomingEl) return;
  const soon = stillToCome(events, today()).slice(0, UPCOMING_SHOWN);
  /* Nothing rendered rather than an empty heading: the card's own link to
     Konami's listing is still below it and still answers the question. */
  upcomingEl.innerHTML = soon.map(e => {
    /* safeUrl answers "#" for anything it will not vouch for -- a missing URL,
       a javascript: scheme -- and "#" is not a destination. */
    const href = safeUrl(e.url ?? '');
    const usable = href !== '#';
    const body = `<strong>${esc(e.event)}</strong><span>${
      [whenText(e), e.location].filter(Boolean).map(esc).join(' · ')}</span>`;
    /* A link now that these events have a page to point at -- Konami's own
       entry for each one. Where a URL will not do, the row stays plain text
       rather than becoming an anchor that promises a destination it lacks. */
    return usable
      ? `<a class="up" href="${esc(href)}" rel="external noreferrer">${body}</a>`
      : `<div class="up">${body}</div>`;
  }).join('');
}

async function refreshUpcoming(){
  try {
    const res = await fetch('upcoming.json', {cache: 'no-cache'});
    if (!res.ok) throw new Error(`upcoming responded ${res.status}`);
    renderUpcoming((await res.json()).events);
  } catch {
    /* The card degrades to its own footer link, which is where this data came
       from in the first place. A schedule nobody can fetch is not an error
       worth putting in front of a reader. */
  }
}

/* boot */
applyTheme();
renderEventMeta();
renderRound();      // paints the loading state before either fetch lands
renderStamp();
Promise.allSettled([
  refreshRounds(),  // independent of the feed: one failing must not block the other
  refreshCoverage(),
  refreshUpcoming(),
]).then(() => schedulePoll(false));
