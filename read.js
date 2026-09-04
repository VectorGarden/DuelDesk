/* READ — one post of the coverage, read here instead of on Konami's blog.

   Its own page, and its own tab, on purpose. The coverage list is a dense
   index of a few hundred headlines and an article opened inside it buries the
   next twenty; a post that has a page has a link somebody can send, and a back
   button that goes back to the list rather than to the middle of it.

   Three files, all of them small or already wanted: the manifest for the
   event's name and who covered it, the event's posts.json for this post's
   headline and kind, and the event's articles.json for the words. The rounds
   -- half a megabyte of pairings -- are never fetched: nothing here is about
   a round.

   The blog's markup is not what arrives. The scraper stored runs of text and
   which of them are emphasised, and blocksHtml in common.js turns those into
   elements, escaping every character of it. */

const params = new URLSearchParams(location.search);
const slug = params.get('event') || '';
const url = params.get('post') || '';

const whereEl = document.getElementById('post-where');
const titleEl = document.getElementById('post-h');
const noteEl  = document.getElementById('post-note');
const bodyEl  = document.getElementById('post-body');
const sayEl   = document.getElementById('announce');

/* esc, safeUrl, blocksHtml and applyTheme come from common.js. */

const say = (m) => { if (sayEl) sayEl.textContent = m; };

function nothing(message, detail){
  titleEl.textContent = 'Coverage';
  noteEl.textContent = '';
  bodyEl.innerHTML = `<div class="empty"><h3>${esc(message)}</h3>${
    detail ? `<p>${detail}</p>` : ''}</div>`;
  say(message);
}

/* Where the reader is, and the way back. The event's own page rather than the
   list of every event: they came from one tournament's coverage. */
function where(event){
  if (!event) return;
  whereEl.innerHTML = `<a href="/?event=${encodeURIComponent(event.slug)}">${
    esc(event.event)}</a>`;
}

/* Whose words these are. On every article, with the link to the original:
   Konami wrote it and the photographs are still only there. */
function credit(event){
  const by = event?.coverageBy;
  const link = safeUrl(url);
  return `<p class="article__by">${by ? `Coverage by <b>${esc(by)}</b>. ` : ''}${
    link !== '#'
      ? `<a href="${esc(link)}" rel="external noreferrer">Read it on the blog</a>, with the photographs.`
      : ''}</p>`;
}

async function load(){
  if (!url || !slug){
    noteEl.textContent = '';
    return nothing('This page needs a post',
                   'Open one from an event’s coverage list.');
  }
  try {
    const [manifest, posts, articles] = await Promise.all([
      fetch('/events.json', {cache: 'no-cache'}),
      fetch(`/events/${encodeURIComponent(slug)}/posts.json`, {cache: 'no-cache'}),
      fetch(`/events/${encodeURIComponent(slug)}/articles.json`, {cache: 'no-cache'}),
    ]);
    if (!articles.ok) throw new Error(`the coverage responded ${articles.status}`);
    const blocks = (await articles.json())[url];
    if (!blocks || !blocks.length){
      noteEl.textContent = '';
      return nothing('The archive does not hold this post',
                     `<a href="${esc(safeUrl(url))}" rel="external noreferrer">Read it on the blog</a>.`);
    }

    const event = manifest.ok
      ? ((await manifest.json()).events || []).find((e) => e.slug === slug)
      : null;
    const post = posts.ok
      ? (await posts.json()).find((p) => p.url === url)
      : null;

    where(event);
    /* The headline as the coverage wrote it. Only ever from posts.json -- the
       query string carries a URL, never a title, so there is nothing a reader
       could put in the address bar that this page would print back. */
    const headline = post?.title || 'Coverage';
    titleEl.textContent = headline;
    document.title = `${headline} — Duel Desk`;
    noteEl.textContent = [post?.kind ? kindLabel(post.kind) : '', dateOf(post)]
      .filter(Boolean).join(' · ');
    bodyEl.innerHTML = blocksHtml(blocks) + credit(event);
    watchCards(bodyEl);
    offerDecks(bodyEl);
    say(`${headline}, ${blocks.length} paragraphs`);
  } catch (err) {
    noteEl.textContent = '';
    nothing('This post could not be loaded', esc(err.message));
  }
}

/* The words the coverage list uses for the same thing, so a reader arriving
   from it is not learning a second vocabulary. */
const KIND_LABELS = {feature: 'Feature Match', deck: 'Deck Profile',
                     result: 'Result', news: 'Announcement',
                     pairings: 'Pairings', standings: 'Standings'};
const kindLabel = (k) => KIND_LABELS[k] || 'Coverage';

function dateOf(post){
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(post?.modified ?? ''));
  return m
    ? new Date(+m[1], +m[2] - 1, +m[3])
        .toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'})
    : '';
}

/* ============================================================
   CARDS IN THE PROSE
   ------------------------------------------------------------
   A match report names cards constantly and a deck list is nothing else, and
   a reader who does not know what one does had to leave to find out.

   Two shapes, both already on the page. The coverage emphasises a card name
   in prose -- "he activated Effect Veiler" -- and writes a deck list one card
   to a line behind a count, "3 Ash Blossom & Joyous Spring". Neither is
   marked as a card by anybody, so both are offered and the store answers:
   89% of emphasised mentions are cards and the rest are headings like "Duel
   1", which simply do not open.
   ============================================================ */

const COUNTED = /^(\d+)(\s+)(\S.*)$/;

/* Wrap the names a card store could answer for. Text nodes only, so nothing
   already a link -- a Duelist's name in a deck list heading -- is touched. */
function markCards(root){
  const emphasised = new Set(['B', 'I', 'U', 'SUP']);
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const jobs = [];
  for (let node = walk.nextNode(); node; node = walk.nextNode()){
    if (node.parentElement.closest('a, .cardref')) continue;
    const inEmphasis = emphasised.has(node.parentElement.tagName);
    /* Line by line, not node by node: a deck list is one text node holding
       "Monsters: 19" and then forty counted lines, and asked as a whole it
       matches nothing. */
    const counted = node.textContent.split('\n').some((l) => COUNTED.test(l.trim()));
    if (inEmphasis || counted) jobs.push([node, inEmphasis]);
  }
  for (const [node, inEmphasis] of jobs) wrap(node, inEmphasis);
}

/* One text node, rebuilt with its card names in spans. A line at a time,
   because a deck list is lines and only the part after the count is a name. */
function wrap(node, inEmphasis){
  const out = document.createDocumentFragment();
  const lines = node.textContent.split('\n');
  lines.forEach((line, i) => {
    if (i) out.append('\n');
    const counted = COUNTED.exec(line);
    let name = null;
    if (counted){
      out.append(counted[1] + counted[2]);
      name = counted[3];
    } else if (inEmphasis && line.trim()){
      name = line;
    }
    if (name === null){ out.append(line); return; }
    /* The spaces around the name stay outside it, so the underline sits on
       the words and not on the gap before them. */
    const lead = name.length - name.trimStart().length;
    const tail = name.length - name.trimEnd().length;
    if (lead) out.append(name.slice(0, lead));
    const span = document.createElement('span');
    span.className = 'cardref';
    span.tabIndex = 0;
    span.textContent = name.trim();
    out.append(span);
    if (tail) out.append(name.slice(name.length - tail));
  });
  node.replaceWith(out);
}

/* What a card is, in the order somebody reading a match report wants it. */
function cardPanel(card){
  const line = [card.type, card.race, card.attribute].filter(Boolean).join(' · ');
  const stats = [];
  if (card.level !== undefined) stats.push(`Level ${card.level}`);
  if (card.atk !== undefined) stats.push(`ATK ${card.atk}`);
  if (card.def !== undefined) stats.push(`DEF ${card.def}`);
  return `<b class="cardpop__n">${esc(card.name)}</b>
    <span class="cardpop__t">${esc(line)}</span>
    ${stats.length ? `<span class="cardpop__s">${esc(stats.join('  '))}</span>` : ''}
    ${card.archetype ? `<span class="cardpop__a">${esc(card.archetype)}</span>` : ''}
    <span class="cardpop__d">${esc(card.desc ?? '')}</span>`;
}

/* ============================================================
   A DECK LIST YOU CAN LOAD
   ------------------------------------------------------------
   A deck list on a page is for reading. A deck list somebody wants to play is
   a file, and there are three that matter: a .ydk, which every simulator
   opens; a ydke:// URI, which is the same thing as a link; and the JSON a
   tournament registration form takes.

   They do not speak the same language. A .ydk and a ydke:// carry the
   eight-digit passcode printed on the card; registration wants Konami's own
   card id under CardDatabaseId. The card store keeps both -- see
   scraper/cards.py -- which is the whole reason this is a few lines rather
   than a project.

   Konami writes a deck list in sections, one card to a line behind its count:

       Monsters: 19
       3 Ash Blossom & Joyous Spring
       ...
       Extra Deck: 15
       ...

   77 of the archive's posts are written that way and hold 651 decks between
   them. The other 21 split the count from the name -- a column of bare
   numbers beside a column of names -- and are left alone; a deck exported
   wrong is worse than one not offered.
   ============================================================ */

const DECK_COUNT = /^(\d+)\s+(\S.*)$/;
const DECK_SECTION = /^(monsters?|monster cards?|spells?|spell cards?|traps?|trap cards?|extra\s*deck|side\s*deck)\b/i;

/* Which pile a section's cards belong in. The post says so, which is better
   than working it out from the cards: a .ydk records no types, so Deckoder has
   to ask the API what each card is, and here the coverage already wrote it. */
function pileOf(heading){
  const h = heading.toLowerCase();
  if (/^extra/.test(h)) return 'Extra';
  if (/^side/.test(h)) return 'Side';
  if (/^spell/.test(h)) return 'Spells';
  if (/^trap/.test(h)) return 'Traps';
  return 'Monsters';
}

/* The decks in a post, as names and counts. Lines in, decks out -- no DOM, so
   it can be tested against text.

   A deck ends where the next one begins, and the next one begins at the first
   main-deck section after a side or extra one. A post holds eight of them and
   nothing separates them but that. */
function decksIn(lines){
  const decks = [];
  let deck = null;
  let pile = null;
  let closed = false;          // this deck has reached its side or extra
  /* Whatever was said last before a deck began. Konami puts the placing, the
     Duelist and the deck's name there -- "1st Place / Raymond Dai /
     Exosisters" -- and it is what the file should be called. */
  let heading = [];
  for (const raw of lines){
    const line = raw.trim();
    if (!line) continue;
    if (DECK_SECTION.test(line)){
      const next = pileOf(line);
      const main = next === 'Monsters' || next === 'Spells' || next === 'Traps';
      if (!deck || (main && closed)){
        deck = {name: heading.join(' — '), Monsters: [], Spells: [],
                Traps: [], Extra: [], Side: []};
        decks.push(deck);
        closed = false;
      }
      heading = [];
      if (!main) closed = true;
      pile = next;
      continue;
    }
    const counted = DECK_COUNT.exec(line);
    if (counted && deck && pile){
      deck[pile].push({name: counted[2].trim(), quantity: Math.min(+counted[1], 99)});
    } else if (!counted){
      /* Not a card and not a section, so it is being said about the deck that
         comes next. Only the last few lines of it: a post opens with a
         paragraph of introduction that is nobody's deck name. */
      heading = [...heading, line].slice(-3);
    }
  }
  return decks.filter(d => d.Monsters.length || d.Spells.length || d.Traps.length);
}

/* ---------- the three files ---------- */

/* Every card of a pile, once per copy, as passcodes. */
function passcodes(entries, resolve){
  const out = [];
  for (const {name, quantity} of entries){
    const card = resolve(name);
    if (!card || card.id === undefined) continue;
    for (let i = 0; i < quantity; i++) out.push(card.id);
  }
  return out;
}

function ydkOf(deck, resolve, title){
  const main = [...passcodes(deck.Monsters, resolve), ...passcodes(deck.Spells, resolve),
                ...passcodes(deck.Traps, resolve)];
  const lines = [];
  if (title) lines.push(`#created by ${title}`);
  lines.push('#main', ...main.map(String),
             '#extra', ...passcodes(deck.Extra, resolve).map(String),
             '!side', ...passcodes(deck.Side, resolve).map(String));
  return lines.join('\n') + '\n';
}

/* Passcodes as little-endian 32-bit numbers, base64. What ydke:// is. */
function idsToB64(ids){
  const bytes = new Uint8Array(ids.length * 4);
  const view = new DataView(bytes.buffer);
  ids.forEach((id, i) => view.setUint32(i * 4, id >>> 0, true));
  let s = '';
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s);
}

function ydkeOf(deck, resolve){
  const main = [...passcodes(deck.Monsters, resolve), ...passcodes(deck.Spells, resolve),
                ...passcodes(deck.Traps, resolve)];
  return `ydke://${idsToB64(main)}!${idsToB64(passcodes(deck.Extra, resolve))}`
       + `!${idsToB64(passcodes(deck.Side, resolve))}!`;
}

/* The registration form's shape, which counts copies rather than repeating
   them, and asks for Konami's id rather than the passcode. */
function registrationOf(deck, resolve, title){
  const pile = (entries) => {
    const out = [];
    for (const {name, quantity} of entries){
      const card = resolve(name);
      if (!card || card.cid === undefined) continue;
      out.push({CardDatabaseId: card.cid, Quantity: quantity});
    }
    return out;
  };
  return {Name: title || 'Untitled deck', Monsters: pile(deck.Monsters),
          Spells: pile(deck.Spells), Traps: pile(deck.Traps),
          Side: pile(deck.Side), Extra: pile(deck.Extra)};
}

/* What the export could not name. Said out loud rather than quietly dropped:
   a deck that exports 38 of its 40 cards is a deck that loses two games. */
function missing(deck, resolve, needs){
  const out = [];
  for (const pile of ['Monsters', 'Spells', 'Traps', 'Extra', 'Side']){
    for (const {name} of deck[pile]){
      const card = resolve(name);
      if (!card || card[needs] === undefined) out.push(name);
    }
  }
  return [...new Set(out)];
}

let popup = null;
let showing = null;       // the name the open card belongs to
let opening = null;       // the timer waiting to see if the reader meant it
let closing = null;       // and the one giving them time to reach the card
let muted = false;        // sent away by hand, until the pointer moves again

/* Long enough that passing over a name on the way somewhere else opens
   nothing, short enough that resting on one does not feel like waiting. A
   deck list is forty names in a column and the pointer crosses most of them
   to leave, which is what made the card hard to be rid of: every escape route
   opened another one. */
const REST = 300;
/* And the gap between the name and the card, which the pointer travels
   through. Closing on the instant it left the name made the card
   unreachable. */
const REACH = 160;

/* Sent away deliberately, as against merely moved away from. */
function dismiss(){
  muted = true;
  closeCard();
}

function closeCard(){
  clearTimeout(opening); opening = null;
  showing = null;
  if (popup){ popup.hidden = true; popup.removeAttribute('data-for'); }
}

/* Asked for whenever the pointer is not on the name or the card. Deferred, so
   crossing the gap between them is not leaving. */
function letGo(){
  clearTimeout(closing);
  closing = setTimeout(closeCard, REACH);
}
const hold = () => { clearTimeout(closing); closing = null; };

function wantCard(span){
  hold();
  if (muted || showing === span) return;
  clearTimeout(opening);
  opening = setTimeout(() => openCard(span), REST);
}

/* What a card is, in the order somebody reading a match report wants it. */
function cardPanel(card){
  const line = [card.type, card.race, card.attribute].filter(Boolean).join(' \u00b7 ');
  const stats = [];
  if (card.level !== undefined) stats.push(`Level ${card.level}`);
  if (card.atk !== undefined) stats.push(`ATK ${card.atk}`);
  if (card.def !== undefined) stats.push(`DEF ${card.def}`);
  return `<b class="cardpop__n">${esc(card.name)}</b>
    <span class="cardpop__t">${esc(line)}</span>
    ${stats.length ? `<span class="cardpop__s">${esc(stats.join('  '))}</span>` : ''}
    ${card.archetype ? `<span class="cardpop__a">${esc(card.archetype)}</span>` : ''}
    <span class="cardpop__d">${esc(card.desc ?? '')}</span>`;
}

async function openCard(span){
  const name = span.textContent;
  showing = span;
  const card = await lookupCard(name);
  /* The reader may have moved on while the shard was fetched, and a card
     opening under a pointer that has gone is worse than none. Sent away by
     hand in the meantime counts as moving on: a click both dismisses the card
     and focuses the name under it, and this is the half that arrives second. */
  if (showing !== span || muted || !card) return;
  if (!popup){
    popup = document.createElement('div');
    popup.className = 'cardpop';
    popup.id = 'cardpop';
    popup.setAttribute('role', 'tooltip');
    /* The card is part of what the pointer is on. Reaching it to read the
       small print, or to select a line of it, must not count as leaving. */
    popup.addEventListener('mouseover', hold);
    popup.addEventListener('mouseout', letGo);
    document.body.append(popup);
  }
  popup.innerHTML = cardPanel(card);
  popup.hidden = false;
  popup.dataset.for = name;
  span.setAttribute('aria-describedby', 'cardpop');
  place(span);
}

/* Beside the name, and under it only where there is no beside to be had.

   Because of what is underneath: a deck list is a column of cards, and a
   panel dropped below one covers the next eight -- so every way of moving the
   pointer off it landed on another name and opened another card. To the side
   it covers the margin.

   It will narrow to fit rather than give up on the side: a card's text at
   15rem is a taller panel, and a taller panel in the margin is still better
   than a wider one over the list.

   The arithmetic is kept apart from the element so it can be tested against
   rectangles rather than against a browser. */
const CARD_WIDE = 480;
const CARD_NARROW = 240;

/* How wide the card may be, given how much margin there is beside the name. */
function cardWidth(at, view){
  const room = Math.max(view.width - at.right - 20, at.left - 20);
  return Math.min(CARD_WIDE, Math.max(room, CARD_NARROW));
}

/* Where it goes, in the coordinates the name was measured in. */
function placement(at, box, view){
  const gap = 12;
  if (view.width - at.right - gap - 8 >= box.width){
    return {left: at.right + gap, top: level(at, box, view), beside: true};
  }
  if (at.left - gap - 8 >= box.width){
    return {left: at.left - gap - box.width, top: level(at, box, view), beside: true};
  }
  /* No margin either side, so under it -- or over it, where under would fall
     off the bottom. */
  const under = at.bottom + gap;
  return {
    left: Math.max(8, Math.min(at.left, view.width - box.width - 8)),
    top: under + box.height < view.height ? under
         : Math.max(8, at.top - box.height - gap),
    beside: false,
  };
}

/* Level with the name, pulled back on screen if that hangs it off the bottom. */
function level(at, box, view){
  return Math.min(Math.max(8, at.top - 4), Math.max(8, view.height - box.height - 8));
}

function place(span){
  const at = span.getBoundingClientRect();
  const view = {width: window.innerWidth, height: window.innerHeight};
  popup.style.maxWidth = `${cardWidth(at, view)}px`;
  // Measured at the width it will actually be.
  const where = placement(at, popup.getBoundingClientRect(), view);
  popup.style.left = `${where.left + window.scrollX}px`;
  popup.style.top = `${where.top + window.scrollY}px`;
}

/* ---------- offering them ---------- */

/* One deck's controls, put where its list begins.

   Per deck, not per post: a Top 8 post holds eight of them and a reader wants
   one. Which one is not a thing a single button at the top could be told. */
function offerDecks(root){
  const paragraphs = [...root.querySelectorAll('p')];
  const lines = [];
  for (const p of paragraphs){
    for (const line of p.textContent.split('\n')) lines.push({line, p});
  }
  const decks = decksIn(lines.map((l) => l.line));
  if (!decks.length) return;

  /* Where each deck starts on the page: the first section heading after the
     one before it. Found by walking the same lines the parse walked. */
  const starts = [];
  let seen = 0;
  let closed = false;
  let open = false;
  for (const {line, p} of lines){
    const text = line.trim();
    if (!DECK_SECTION.test(text)) continue;
    const pile = pileOf(text);
    const main = pile === 'Monsters' || pile === 'Spells' || pile === 'Traps';
    if (!open || (main && closed)){ starts.push(p); seen += 1; closed = false; open = true; }
    if (!main) closed = true;
  }

  decks.forEach((deck, i) => {
    const at = starts[i];
    if (!at) return;
    const bar = document.createElement('p');
    bar.className = 'deckout';
    bar.innerHTML = `<span class="deckout__k">Take this deck</span>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="ydk">.ydk</button>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="ydke">ydke://</button>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="json">Registration JSON</button>
      <span class="deckout__note" data-note="${i}"></span>`;
    at.before(bar);
  });

  root.addEventListener('click', (e) => {
    const button = e.target.closest?.('[data-deck]');
    if (button) handOver(decks[+button.dataset.deck], button.dataset.as,
                         root.querySelector(`[data-note="${button.dataset.deck}"]`));
  });
}

/* Resolve every card in a deck, then write the file. The store is sharded, so
   this is one fetch per shard the deck touches -- about forty cards across
   forty files the first time and none of them the second. */
async function handOver(deck, as, note){
  note.textContent = 'Looking the cards up…';
  const names = ['Monsters', 'Spells', 'Traps', 'Extra', 'Side']
    .flatMap((pile) => deck[pile].map((c) => c.name));
  const found = new Map();
  await Promise.all([...new Set(names)].map(async (name) => {
    found.set(name, await lookupCard(name));
  }));
  const resolve = (name) => found.get(name) ?? null;

  const needs = as === 'json' ? 'cid' : 'id';
  const lost = missing(deck, resolve, needs);
  /* A filename out of the heading: "1st Place — Raymond Dai — Exosisters"
     becomes "1st Place - Raymond Dai - Exosisters".

     Only what a file system actually objects to is taken out. Much of this
     archive is named in Spanish and Portuguese, and a rule built on \w --
     which is ASCII and nothing else -- turned an accented name into
     "Jos Ram rez". */
  const stem = (deck.name || 'decklist')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim().slice(0, 60) || 'decklist';
  if (as === 'ydk') save(ydkOf(deck, resolve, deck.name), `${stem}.ydk`, 'text/plain');
  else if (as === 'ydke') save(ydkeOf(deck, resolve), `${stem}.ydke.txt`, 'text/plain');
  else save(JSON.stringify(registrationOf(deck, resolve, deck.name), null, 2),
            `${stem}.json`, 'application/json');

  /* What it could not name, out loud. A deck exported two cards short is a
     deck that loses games, and quietly is the wrong way to find that out. */
  note.textContent = lost.length
    ? `${lost.length} card${lost.length > 1 ? 's' : ''} not in the card store: ${lost.join(', ')}`
    : '';
}

function save(text, filename, type){
  const url = URL.createObjectURL(new Blob([text], {type}));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  /* Revoked on the next turn of the loop, not now: the click has to have been
     handed the URL before it stops meaning anything. */
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function watchCards(root){
  markCards(root);
  const point = (e) => {
    const span = e.target.closest?.('.cardref');
    if (span) wantCard(span); else letGo();
  };
  root.addEventListener('mouseover', point);
  root.addEventListener('mouseout', (e) => {
    if (e.target.closest?.('.cardref')) letGo();
  });
  /* A keyboard reader gets it on focus and keeps it until they move on. No
     resting: tabbing to a name is already the deliberate act the delay is
     waiting for.

     Only when the focus came from a keyboard, which is what :focus-visible
     means. Clicking a name focuses it too, and opening on that made a click
     on the prose -- which in a match report is mostly card names -- open a
     card rather than dismiss the one already up. That is the whole of why
     clicking the page appeared to do nothing. */
  root.addEventListener('focusin', (e) => {
    const span = e.target.closest?.('.cardref');
    if (!span) { closeCard(); return; }
    let byKeyboard = true;
    try { byKeyboard = span.matches(':focus-visible'); } catch { /* older engines */ }
    if (byKeyboard && !muted) openCard(span);
  });
  root.addEventListener('focusout', closeCard);
  /* Every ordinary way of saying "enough". Escape is what a tooltip owes a
     keyboard, and a click is what everybody tries first -- including a click
     on the card itself, which is the thing under the pointer when a reader
     decides they have had enough of it. That was exempted at first so its
     text stayed selectable, which made the one obvious way of dismissing it
     the one way that did nothing.

     Selecting still works: a drag ends in a click too, so a click that
     leaves a selection behind is not a dismissal. */
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') dismiss(); });
  document.addEventListener('click', () => {
    if ((window.getSelection?.()?.toString() ?? '').trim()) return;
    dismiss();
  });
  /* A card left hanging over the page while it scrolls is pointing at
     nothing. */
  window.addEventListener('scroll', closeCard, {passive: true});
  /* Sent away by hand, it stays away until the reader moves. Hiding it
     changes what is under the pointer, and what is under the pointer is
     often another card name -- so dismissing it opened the next one, and
     the dismissal looked like it had done nothing. */
  document.addEventListener('mousemove', () => { muted = false; }, {passive: true});
}

applyTheme();
load();
