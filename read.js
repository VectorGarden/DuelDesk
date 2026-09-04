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
    /* Shaped before the cards are marked, so a deck's heading is a heading by
       the time anything asks whether it is a card. */
    shapeDecks(bodyEl);
    watchCards(bodyEl);
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
    /* Not a link, not already marked, and not a deck's heading: a heading is
       bold, and read as emphasis its placing -- "– 13" -- was offered as a
       card and underlined for one. */
    if (node.parentElement.closest('a, .cardref, .deck__n')) continue;
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

/* A card and how many of it, which is how 77 of the posts write one: "3 Ash
   Blossom & Joyous Spring".

   The full stop is YCS Indianapolis 2011, which punctuates some of its
   counts -- "2. T.G. Striker" -- and had those cards read as nothing at all.
   It is optional and the space after it is not, which is what keeps the
   blog's own numbered prose out: a tech update lists its subjects as "1.)
   Kashtira Fenrir" and "2.) The Bystial Monsters", and a bracket is not
   whitespace. There are 219 lines written that way in the archive and none
   of them is a card. */
const DECK_COUNT = /^(\d+)[.)]?\s+(\S.*)$/;
/* A count with nothing on the line but itself, which is how 21 posts write
   one: the number plain, the card's name emphasised on the line after. */
const BARE_COUNT = /^(\d{1,2})$/;
/* An Extra Deck, including the two times the coverage spelt it wrong. YCS
   Portland 2019 writes "Etra Deck: 15" and the Top 16 decklists from
   Indianapolis 2011 write "Exra Deck: 15", and a section that is not read as
   one ends the deck it is in the middle of: the Side Deck under it opened a
   deck that was never there, and the Portland deck was left with no name at
   all.

   Spelt out rather than made tolerant. These are the only two near misses in
   the archive -- every line of every post with a section in it, matched
   against anything of the shape "<word> Deck: <number>" -- so there is
   nothing here for a looser rule to earn, and a looser rule would be reading
   sections into words nobody has written yet. */
const EXTRA = "extra|etra|exra";
const DECK_SECTION = new RegExp(`^(main\\s*decks?|monsters?|monster cards?|spells?`
  + `|spell cards?|traps?|trap cards?|(${EXTRA})\\s*decks?|side\\s*decks?)\\b`, 'i');
/* A card whose name was too long for the line it was written on. "Light
   Dragon @Ignister Mereologic Aggregator" is wrapped in the coverage, and
   the wrap is a real break in the post, so the tail of the name arrives as a
   line of its own that counts nothing and names no section.

   It is the tail of the card above it when it is written in the same
   paragraph as that card -- a wrap cannot cross a paragraph -- and when it
   does not open with a number. That last is what keeps "2. T.G. Striker",
   which is a count written with a full stop, from being read as more of the
   T.G. Warwolf above it. Those are the only three lines in the archive this
   is asked about at all. */
const WRAPPED = /^\D/;
/* How many the section says it holds, where it says so: "Monster Cards: 31". */
const SECTION_COUNT = /:\s*(\d+)\s*$/;

/* Which pile a section's cards belong in. The post says so, which is better
   than working it out from the cards: a .ydk records no types, so Deckoder has
   to ask the API what each card is, and here the coverage already wrote it. */
function pileOf(heading){
  const h = heading.toLowerCase();
  if (new RegExp(`^(${EXTRA})`).test(h)) return 'Extra';
  if (/^side/.test(h)) return 'Side';
  if (/^spell/.test(h)) return 'Spells';
  if (/^trap/.test(h)) return 'Traps';
  /* "Main Deck: 41" opens a deck and names no pile of its own. 59 of the 64
     posts that use it name the piles underneath; 2 list the cards straight
     after it, and those land in Monsters -- the .ydk and the ydke:// are
     right either way, because a main deck is a main deck, and only the
     registration file's grouping suffers. */
  return 'Monsters';
}

/* The decks in a post, as names and counts. Lines in, decks out -- no DOM, so
   it can be tested against text.

   A line is either a string or, where the caller knows, {text, emph}: whether
   the coverage emphasised it. Some posts need that to be read at all -- see
   below.

   A deck ends where the next one begins, and the next one begins at the first
   main-deck section after a side or extra one. A post holds eight of them and
   nothing separates them but that. */
/* Which lines are the rest of the card above them, written into the paragraph
   below it.

   "Maliss <P> March Hare" is published with the brackets unescaped, and the
   blog's own editor read "<P>" as a paragraph: what it saved, and so what the
   archive holds, is "3 Maliss" ending one paragraph and "March Hare" starting
   the next. A wrap cannot cross a paragraph -- #244 -- and this is not a
   wrap, it is a paragraph break invented by a CMS.

   Told apart by what is under it. The line after a deck's last card is
   ordinarily the next Duelist, and a Duelist's name is not followed by more
   cards in the same paragraph: it is alone, or above "Main Deck: 43". The
   tail of a card name is followed by the rest of the list it was in.

   Measured over the archive: without that last condition the rule takes 572
   lines across 42 posts, nearly all of them Duelists. With it, 11, and every
   one is this. */
function tailsIn(rows){
  const out = new Set();
  let pile = false;
  let card = -1;
  rows.forEach((row, at) => {
    const text = (row.text ?? '').trim();
    if (!text) return;
    if (DECK_SECTION.test(text)){ pile = true; card = -1; return; }
    if (DECK_COUNT.test(text)){ card = pile ? at : -1; return; }
    if (BARE_COUNT.test(text)){ card = -1; return; }
    const under = rows.slice(at + 1).find((next) => (next.text ?? '').trim());
    if (card >= 0 && row.p && WRAPPED.test(text)
        && under && under.p === row.p && DECK_COUNT.test(under.text.trim())){
      out.add(at);
    }
    card = -1;
  });
  return out;
}

function decksIn(lines){
  const rows = lines.map((l) => (typeof l === 'string'
    ? {text: l.trim(), emph: null, p: null}
    : {text: (l.text ?? '').trim(), emph: !!l.emph, p: l.p ?? null}));
  const decks = [];
  let deck = null;
  let pile = null;
  let closed = false;
  let heading = [];
  /* A count waiting for the card it counts. Konami writes 77 of its posts
     with the two on one line -- "3 Ash Blossom & Joyous Spring" -- and 21
     with the count on its own line and the name emphasised on the next. */
  let waiting = null;
  /* The card the line before held, where it was written, so a name that
     wrapped can be put back together. */
  let wrote = null;
  /* The paragraph the pile was opened in, and the number it said it held. */
  let opened = null;
  let counting = null;

  const start = () => {
    deck = {name: heading.join(' — '), Monsters: [], Spells: [],
            Traps: [], Extra: [], Side: []};
    decks.push(deck);
    closed = false;
  };

  const tails = tailsIn(rows);
  rows.forEach(({text, emph, p}, at) => {
    if (!text) return;
    const said = wrote;
    wrote = null;
    if (DECK_SECTION.test(text)){
      const next = pileOf(text);
      const main = next === 'Monsters' || next === 'Spells' || next === 'Traps';
      if (!deck || (main && closed)) start();
      heading = [];
      if (!main) closed = true;
      pile = next;
      waiting = null;
      opened = p;
      counting = /^main\s*decks?/i.test(text)
        ? null : Number(SECTION_COUNT.exec(text)?.[1]) || null;
      return;
    }
    const counted = DECK_COUNT.exec(text);
    if (counted && deck && pile){
      const card = {name: counted[2].trim(), quantity: Math.min(+counted[1], 99)};
      deck[pile].push(card);
      wrote = p ? {card, p} : null;
      waiting = null;
      return;
    }
    if (BARE_COUNT.test(text)){
      /* A number on its own, waiting for the card under it. A section opens
         with its own total -- "Monsters:" then 24 then 3 then the card -- and
         that total is simply overwritten by the count that follows it, which
         is why it needs no rule of its own. */
      waiting = deck && pile ? Math.min(+text, 99) : null;
      return;
    }
    if (waiting !== null && emph && deck && pile){
      deck[pile].push({name: text, quantity: waiting});
      waiting = null;
      return;
    }
    /* The rest of a card's name, wrapped onto the line under it -- or into
       the paragraph under it, where a bracket in the name broke one. */
    if (said && (tails.has(at) || (said.p === p && WRAPPED.test(text)))){
      said.card.name = `${said.card.name} ${text}`;
      wrote = said;
      return;
    }
    /* A card written with no count of its own, under a section that gave
       one: "Trap Cards: 3" and then "Infinite Impermanence" is three of it.
       Only in the section's own paragraph, and only while the pile is still
       empty, so it is the section's count being spent and not a sentence
       after a list. */
    const pot = deck && pile ? deck[pile] : null;
    if (pot && !pot.length && opened === p && counting){
      pot.push({name: text, quantity: Math.min(counting, 99)});
      return;
    }
    waiting = null;
    if (!counted){
      /* Not a card and not a section, so it is being said about the deck that
         comes next. Only the last few lines of it: a post opens with a
         paragraph of introduction that is nobody's deck name. */
      heading = [...heading, text].slice(-3);
    }
  });
  return decks.filter((d) => d.Monsters.length || d.Spells.length || d.Traps.length);
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

/* ---------- laying them out ---------- */

/* A post of deck lists is a post of many. The Top 64 lists run to 63 decks,
   2,826 cards and 3,331 lines, and the only way to the fortieth was to scroll
   past thirty-nine.

   So each deck becomes a section of its own: a heading that opens and closes
   it, one pile shown at a time, and a list at the top to get to any of them.
   A post holding one deck is left as it was -- none of that is worth its
   chrome for a single list. */

const PILES = ['Monsters', 'Spells', 'Traps', 'Extra', 'Side'];

/* A paragraph's lines, each with whether the coverage emphasised it and which
   paragraph it came from.

   Emphasis is not decoration here. 21 posts write a deck list as two columns
   -- the count plain on its own line, the card's name in bold on the next --
   and without knowing which is which they cannot be read at all.

   A line counts as emphasised only when everything in it was: "He activated
   Effect Veiler" is a sentence with a card in it, not a card. */
function linesOf(p){
  const out = [];
  let text = '';
  let emph = true;
  let any = false;
  const flush = () => { out.push({text: text.trim(), emph: emph && any, p}); text = ''; emph = true; any = false; };
  const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
  for (let node = walk.nextNode(); node; node = walk.nextNode()){
    const marked = !!node.parentElement.closest('b, i, u, sup');
    const parts = node.data.split('\n');
    parts.forEach((part, i) => {
      if (i) flush();
      if (part.trim()){ emph = emph && marked; any = true; }
      text += part;
    });
  }
  flush();
  return out.filter((line) => line.text);
}

/* Which paragraph each deck begins at, and which paragraphs hold each of its
   piles.

   A pile is not always one paragraph. Konami writes some posts with the
   heading and its cards together -- "Monsters: 19" and then the nineteen --
   and others with the heading alone and the cards in the paragraph after it.
   So a pile owns everything from its heading until the next heading.

   Walks the same lines the parse walked, so the two cannot disagree about
   where one deck ends and the next starts. */
function layoutOf(lines){
  const found = [];
  let deck = null;
  let pile = null;
  let closed = false;
  /* A heading may run to several paragraphs. Konami writes a Speed Duel deck
     as "Sam Chen - 1st Place", then "Character: Yami Yugi", then "Skill Name:
     Ever Faithful Companions", and taking only the last of them dropped the
     Duelist -- so two people who both played Yami Yugi with the same skill
     came out as one deck, listed twice under the same name. */
  let heading = [];
  let seenP = null;
  /* Whether the deck being read has held any cards yet. A heading ends a
     deck, but only a deck that got as far as its cards: Speed Duel writes
     "Main Deck: 20" and then, plain, the character and the skill, and that
     line is not a second Duelist. */
  let cards = false;
  /* Which line of its own paragraph this is. Some posts write the Duelist
     and the section under them in one paragraph, broken by a line break
     rather than a paragraph break, and then the heading is the lines above
     the section rather than the paragraph before it. */
  let atP = null;
  let said = 0;
  /* Where the last card was written, so the tail of a name that wrapped is
     read as more of it rather than as the next Duelist. */
  let wrote = null;
  const tails = tailsIn(lines);
  for (let at = 0; at < lines.length; at++){
    const {text: raw, p, emph} = lines[at];
    const text = raw.trim();
    if (!text) continue;
    if (p !== atP){ atP = p; said = 0; }
    const nth = said++;
    if (DECK_SECTION.test(text)){
      const next = pileOf(text);
      const main = next === 'Monsters' || next === 'Spells' || next === 'Traps';
      if (!deck || (main && closed)){
        /* The heading counts as the deck's own only when it runs up to the
           section without a break. A post opens with a line of introduction
           -- "Wanna see the Decks that Duelists piloted to the Top 8?" --
           and that belongs to the post, not to whoever came first.
           Where the heading really is several paragraphs, the bold is what
           says so: Konami sets the Duelist's name and placing in bold and
           leaves the introduction above it plain, so the heading begins
           where the bold begins and runs from there down to the section.
           What follows the name -- "Character: Yami Yugi", "Skill Name: Ever
           Faithful Companions" -- is plain, and belongs to the name. */
        const near = heading[heading.length - 1];
        const run = near && (near.p === p || near.p.nextElementSibling === p)
          ? heading : [];
        let from = run.findLastIndex((held) => held.emph);
        while (from > 0 && run[from - 1].emph) from -= 1;
        const own = (from < 0 ? run.slice(-1) : run.slice(from)).map((held) => held.p);
        /* How many of its lines, where the heading is in this paragraph:
           the ones above the section, which is this line. */
        const upto = own[own.length - 1] === p ? nth : 0;
        deck = {at: own[0] ?? p, title: own, upto, piles: new Map()};
        found.push(deck);
        closed = false;
        cards = false;
      }
      if (!main) closed = true;
      pile = next;
      if (!deck.piles.has(pile)) deck.piles.set(pile, {held: [], said: null});
      const held = deck.piles.get(pile);
      /* "Main Deck: 41" is the whole main deck, not the monsters in it. Its
         number belongs to no pile, and the "Monster Cards: 31" underneath is
         the one the Monsters tab should carry. */
      if (!/^main\s*decks?/i.test(text)){
        held.said = Number(SECTION_COUNT.exec(text)?.[1]) || held.said;
      }
      /* The heading's own paragraph, which may or may not hold the cards. */
      if (!held.held.includes(p)) held.held.push(p);
      heading = [];
      seenP = p;
      wrote = null;
      continue;
    }
    if (DECK_COUNT.test(text) || BARE_COUNT.test(text)){
      /* A card, in whatever paragraph it landed in -- or the count of one,
         which in the two-column posts is all a line holds. */
      if (deck && pile && p !== seenP && !deck.piles.get(pile).held.includes(p)){
        deck.piles.get(pile).held.push(p);
      }
      if (deck) cards = true;
      wrote = deck && pile && DECK_COUNT.test(text) ? p : null;
      continue;
    }
    /* The rest of a card's name, wrapped onto the line under it, or into the
       paragraph under it where a bracket in the name broke one. Neither is
       any kind of heading, and neither ends the deck it is in the middle
       of. */
    if (wrote === p && WRAPPED.test(text)) continue;
    if (tails.has(at)) continue;
    /* Nor is anything written under a section in that section's own
       paragraph. Team YCS Las Vegas 2024 writes "Trap Cards: 3" and then,
       with no count of its own, "Infinite Impermanence": a heading belongs
       at the top of a paragraph, not beneath the pile it would be ending. */
    if (seenP === p) continue;
    /* The last thing said before a deck begins is its heading, and it is
       where the section should start rather than at "Monsters:". The last,
       not the first: a post opens with a line of introduction and then names
       whoever came first, and it is the name the deck belongs to. */
    /* Consecutive paragraphs of it, in the order they were written. Which of
       them belong to the deck is settled at the section, where the bold ones
       are known to have run all the way up to it. */
    const last = heading[heading.length - 1];
    const line = {p, emph};
    heading = !last ? [line]
      : last.p === p ? [...heading.slice(0, -1), {p, emph: last.emph && emph}]
      : last.p.nextElementSibling === p ? [...heading, line].slice(-4)
      : [line];
    /* And it ends the deck before it -- but only one that reached its cards.
       A deck that has just opened at "Main Deck: 20" has not, and the line
       under it says which character was played, not who played next. */
    if (deck && deck.piles.size && cards){ deck = null; pile = null; closed = false; }
  }
  return found;
}

/* How big a deck is: its main deck, counted in copies rather than in lines.
   Three of a card is three cards, and a list of 41 that says 18 is wrong
   about the only number anybody checks. */
function copiesIn(deck){
  return ['Monsters', 'Spells', 'Traps']
    .flatMap((pile) => deck[pile])
    .reduce((n, card) => n + card.quantity, 0);
}

/* Where a paragraph's nth line ends, as a text node and an offset into it.
   Line breaks in an article are newlines inside the text rather than <br>
   elements -- the stylesheet sets pre-line -- so a heading that shares its
   paragraph with the section under it cannot be moved by moving the
   paragraph. This is what a range needs to take the heading and leave the
   rest where it is. */
function endOfLine(p, n){
  const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
  let said = 0;
  let text = '';
  for (let node = walk.nextNode(); node; node = walk.nextNode()){
    for (let i = 0; i < node.data.length; i++){
      if (node.data[i] !== '\n'){ text += node.data[i]; continue; }
      if (text.trim() && ++said === n) return {node, at: i};
      text = '';
    }
  }
  return null;
}

/* One deck per place, read inside the boundaries that place drew.

   Not the post read twice over and the two readings lined up by position.
   They did not always agree on how many decks a post held -- a card name the
   coverage broke in half, a card written without its count -- and wherever
   they disagreed, every deck after it wore the next Duelist's name and the
   next Duelist's count.

   A span with no main deck in it is not a deck. Those were always thrown
   away; they are thrown away here too, and now by the reading that decides
   the names rather than by the other one. */
function decksByPlace(lines, layout){
  const found = [];
  layout.forEach((place, i) => {
    const stop = layout[i + 1]?.at ?? null;
    const span = [];
    for (let node = place.at; node && node !== stop; node = node.nextElementSibling){
      span.push(node);
    }
    const own = new Set(span);
    const [deck] = decksIn(lines.filter((line) => own.has(line.p)));
    if (deck) found.push({deck, place, span});
  });
  return found;
}

/* The heading into the name, and out of the article: it is moved rather than
   copied, so the Duelist's name is still the link the article made it.

   Where the heading shares its paragraph with the section under it, only its
   own lines come away and the rest stays where the pile below expects it. */
function takeHeading(name, held, upto){
  const cut = upto ? endOfLine(held, upto) : null;
  if (!cut){
    while (held.firstChild) name.append(held.firstChild);
    held.remove();
    return;
  }
  const range = document.createRange();
  range.setStart(held, 0);
  range.setEnd(cut.node, cut.at);
  name.append(range.extractContents());
  /* The break the heading ended on, now at the front of what is left, which
     pre-line would otherwise render as a blank first line. */
  const first = document.createTreeWalker(held, NodeFilter.SHOW_TEXT).nextNode();
  if (first && first.data.startsWith('\n')) first.deleteData(0, 1);
}

function shapeDecks(root){
  const lines = [];
  for (const p of root.querySelectorAll('p')) lines.push(...linesOf(p));
  const layout = layoutOf(lines);
  if (!layout.length) return;

  const found = decksByPlace(lines, layout);
  if (!found.length) return;
  /* In the order they are shown, which is the order the buttons name. */
  const decks = found.map((f) => f.deck);
  const many = found.length > 1;

  found.forEach(({deck, place, span}, i) => {
    const section = document.createElement('section');
    section.className = 'deck';
    section.id = `deck-${i}`;

    place.at.before(section);
    const body = document.createElement('div');
    body.className = 'deck__body';
    body.id = `deckbody-${i}`;
    span.forEach((node) => body.append(node));

    const piles = PILES.filter((pile) => place.piles.has(pile));
    for (const pile of piles) trim(place.piles.get(pile));

    /* The heading, moved rather than copied, so the Duelist's name is still
       the link the article made it. Beside the button and not inside it: a
       link within a button is not markup. */
    const head = document.createElement('h2');
    head.className = 'deck__h';
    const name = document.createElement('span');
    name.className = 'deck__n';
    if (place.title.length){
      place.title.forEach((held, n) => {
        if (n) name.append(' — ');
        /* Only the last of them can be the section's own paragraph, which is
           where the heading is written into the line above the cards. */
        takeHeading(name, held, n === place.title.length - 1 ? place.upto : 0);
      });
    } else {
      name.textContent = deck.name || `Deck ${i + 1}`;
    }
    head.append(name);
    /* What to call it, taken now: the heading's own nodes have just been
       moved here and the paragraph they came from is gone. The export uses it
       too, or the first deck of a post is named after the post's opening
       sentence -- "Here are the Deck Lists for the Top Cut of the North
       America World Championship Qualifier!" is not a deck. */
    place.called = name.textContent.replace(/\s*\n\s*/g, ' — ').trim();
    if (place.called) deck.name = place.called;
    const size = document.createElement('span');
    size.className = 'deck__c';
    size.textContent = `${copiesIn(deck)} cards`;
    head.append(size);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'deck__toggle';
    toggle.dataset.open = String(i);
    toggle.setAttribute('aria-expanded', String(!many));
    toggle.setAttribute('aria-controls', body.id);
    toggle.innerHTML = `<span class="visually-hidden">Show this deck</span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;
    head.append(toggle);
    section.append(head);

    body.hidden = many;

    /* Where this deck can be taken away. Above the pills rather than under
       the cards: under them it moved every time a pile was chosen. */
    const bar = document.createElement('p');
    bar.className = 'deckout';
    bar.innerHTML = `<span class="deckout__k">Take this deck</span>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="ydk">.ydk</button>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="ydke">ydke://</button>
      <button type="button" class="btn btn--sm" data-deck="${i}" data-as="json">Registration JSON</button>
      <span class="deckout__note" data-note="${i}"></span>`;
    body.prepend(bar);

    if (piles.length > 1){
      const tabs = document.createElement('div');
      tabs.className = 'deck__tabs';
      tabs.setAttribute('role', 'tablist');
      /* The count goes on the tab. Saying "Monsters: 19" again above the
         nineteen is the tab's own label a second time. */
      tabs.innerHTML = piles.map((pile, n) => {
        const said = place.piles.get(pile).said;
        return `<button type="button" role="tab" data-pile="${i}:${pile}"
                 aria-selected="${n === 0}">${esc(pile)}${
                 said ? ` <span class="deck__q">${said}</span>` : ''}</button>`;
      }).join('');
      bar.after(tabs);
      /* One pile at a time. Five stacked is most of why a list of decks is
         long. */
      piles.forEach((pile, n) => {
        for (const p of place.piles.get(pile).held){
          p.dataset.holds = pile;
          p.hidden = n !== 0;
        }
      });
    }

    section.append(body);
  });

  if (many){
    root.prepend(indexOf(found.map((f) => f.deck), found.map((f) => f.place)));
    /* Two abreast, and the page as wide as it has: a deck list is a column of
       short lines and does not want the measure prose is held to. */
    root.classList.add('article--decks');
  }

  root.addEventListener('click', (e) => {
    /* The whole heading opens and closes the deck. Except a link in it: the
       Duelist's name is the way to their page and always was. */
    const head = e.target.closest?.('.deck__h');
    if (head && !e.target.closest('a')){
      const button = head.querySelector('[data-open]');
      if (button && !e.target.closest('[data-open]')) { toggleDeck(root, button); return; }
    }
    const open = e.target.closest?.('[data-open]');
    if (open){ toggleDeck(root, open); return; }
    /* A name in the index opens the deck it points at, as well as going to
       it: a jump to something still closed lands on a heading and no deck. */
    const jump = e.target.closest?.('.deckindex__list a');
    if (jump){
      const at = root.querySelector(jump.getAttribute('href'));
      const button = at?.querySelector('[data-open]');
      if (button && button.getAttribute('aria-expanded') !== 'true') toggleDeck(root, button);
    }
    const every = e.target.closest?.('[data-all]');
    if (every){
      handOverAll(decks, every.dataset.all, root.querySelector('[data-note="all"]'),
                  document.title.replace(/ — Duel Desk$/, ''));
      return;
    }
    const tab = e.target.closest?.('[data-pile]');
    if (tab) showPile(root, tab);
    const button = e.target.closest?.('[data-deck]');
    if (button) handOver(decks[+button.dataset.deck], button.dataset.as,
                         root.querySelector(`[data-note="${button.dataset.deck}"]`));
  });

  root.addEventListener('input', (e) => {
    if (e.target.id === 'deckfind') narrowDecks(root, e.target.value);
  });
}

/* Take the heading off the front of a pile's first paragraph. The tab above it
   already says which pile this is and how many are in it, and a paragraph that
   opens by repeating its own label reads as though the page forgot. */
function trim(pile){
  /* Every paragraph of the pile that opens with a heading, not only the
     first: a deck may be introduced twice over, by "Main Deck: 41" and then
     by "Monster Cards: 31", and both are the tab's own label written again.

     The heading is often bold, so it is the paragraph's text that is asked
     and not its first text node -- checking the node meant a heading inside a
     <b> was never seen. */
  for (const p of [...pile.held]){
    const [first, ...rest] = p.textContent.split('\n');
    if (!DECK_SECTION.test(first.trim())) continue;
    if (!rest.join('').trim() && pile.held.length > 1){
      /* The whole paragraph was the heading. */
      p.remove();
      pile.held.splice(pile.held.indexOf(p), 1);
      continue;
    }
    /* Otherwise take the line off the front of wherever it starts. */
    const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    const node = walk.nextNode();
    if (node) node.data = node.data.replace(/^[^\n]*\n?/, '');
  }
}

function toggleDeck(root, button){
  const body = root.querySelector(`#deckbody-${button.dataset.open}`);
  const shown = button.getAttribute('aria-expanded') === 'true';
  button.setAttribute('aria-expanded', String(!shown));
  body.hidden = shown;
}

function showPile(root, tab){
  const [i, pile] = tab.dataset.pile.split(':');
  const section = root.querySelector(`#deck-${i}`);
  for (const other of section.querySelectorAll('[data-pile]')){
    other.setAttribute('aria-selected', String(other === tab));
  }
  /* The paragraphs were marked with their pile when the section was built. */
  section.querySelectorAll('[data-holds]').forEach((p) => {
    p.hidden = p.dataset.holds !== pile;
  });
}

/* The decks in a post, as a list to get to any of them, with a box to narrow
   it. Sixty-three names is a list; sixty-three names is not a scroll. */
function indexOf(decks, layout){
  const nav = document.createElement('nav');
  nav.className = 'deckindex';
  nav.setAttribute('aria-label', 'The decks in this post');
  nav.innerHTML = `
    <label class="deckindex__find">
      <span class="visually-hidden">Find a Duelist</span>
      <input id="deckfind" type="search" placeholder="Find a Duelist or a deck"
             autocomplete="off">
    </label>
    <p class="deckindex__all">
      <span class="deckout__k">Take all ${decks.length}</span>
      <button type="button" class="btn btn--sm" data-all="ydk">.ydk zip</button>
      <button type="button" class="btn btn--sm" data-all="ydke">ydke:// list</button>
      <button type="button" class="btn btn--sm" data-all="json">JSON zip</button>
      <span class="deckout__note" data-note="all"></span>
    </p>
    <ol class="deckindex__list">${decks.map((deck, i) => `
      <li><a href="#deck-${i}">${esc(nameOf(deck, layout[i], i))}</a></li>`).join('')}
    </ol>`;
  return nav;
}

/* What to call a deck in the index: what its heading actually says on the
   page, which is where the Duelist's name is. */
function nameOf(deck, place, i){
  return place?.called || (deck.name || `Deck ${i + 1}`).replace(/\s*\n\s*/g, ' — ');
}

/* Narrowing hides the decks as well as the index entries, so the page below
   the box is the answer to what was typed. */
function narrowDecks(root, query){
  const want = query.trim().toLowerCase();
  root.querySelectorAll('.deckindex__list li').forEach((row, i) => {
    const name = row.textContent.toLowerCase();
    const hit = !want || name.includes(want);
    row.hidden = !hit;
    const section = root.querySelector(`#deck-${i}`);
    if (section) section.hidden = !hit;
  });
}

/* Resolve every card in a deck, then write the file. The store is sharded, so
   this is one fetch per shard the deck touches -- about forty cards across
   forty files the first time and none of them the second. */
async function handOver(deck, as, note){
  note.textContent = 'Looking the cards up…';
  const ids = await cardNumbers();
  const resolve = (name) => numbersFor(ids, name);

  const needs = as === 'json' ? 'cid' : 'id';
  const lost = missing(deck, resolve, needs);
  const stem = fileStem(deck.name);
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

/* Every deck in the post at once.

   All three formats. A .ydk holds one deck -- the format has no separator --
   and a registration file is one deck's form, so those arrive as a zip of
   sixty-three files, written by hand in common.js because a zip of stored
   entries is sixty lines rather than a dependency. A ydke:// is one line, so
   a list of them is a list. */
async function handOverAll(decks, as, note, title){
  note.textContent = 'Looking the cards up…';
  const ids = await cardNumbers();
  const resolve = (name) => numbersFor(ids, name);
  const stem = fileStem(title || 'deck lists');
  const nameOfDeck = (deck, i) =>
    fileStem(deck.name.replace(/\s*\n\s*/g, ' — ')) || `Deck ${i + 1}`;

  if (as === 'ydke'){
    const lines = decks.map((deck, i) =>
      `# ${nameOfDeck(deck, i)}\n${ydkeOf(deck, resolve)}`);
    save(lines.join('\n\n') + '\n', `${stem}.ydke.txt`, 'text/plain');
  } else if (as === 'ydk'){
    saveZip(eachNamedOnce(decks.map((deck, i) => ({
      name: `${nameOfDeck(deck, i)}.ydk`,
      text: ydkOf(deck, resolve, nameOfDeck(deck, i)),
    }))), `${stem}.ydk.zip`);
  } else {
    saveZip(eachNamedOnce(decks.map((deck, i) => ({
      name: `${nameOfDeck(deck, i)}.json`,
      text: JSON.stringify(registrationOf(deck, resolve, nameOfDeck(deck, i)), null, 2),
    }))), `${stem}.json.zip`);
  }

  const lost = new Set();
  for (const deck of decks){
    for (const name of missing(deck, resolve, as === 'json' ? 'cid' : 'id')) lost.add(name);
  }
  note.textContent = lost.size
    ? `${lost.size} card${lost.size > 1 ? 's' : ''} not in the card store: ${[...lost].join(', ')}`
    : `${decks.length} decks.`;
}

/* A filename out of a heading: "1st Place — Raymond Dai — Exosisters" becomes
   "1st Place - Raymond Dai - Exosisters".

   Only what a file system actually objects to is taken out. Much of this
   archive is named in Spanish and Portuguese, and a rule built on \w -- which
   is ASCII and nothing else -- turned an accented name into "Jos Ram rez". */
function fileStem(name){
  return (name || 'decklist')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim().slice(0, 60) || 'decklist';
}

/* The same handing-over, for bytes rather than text. */
function saveZip(files, filename){
  handTo(new Blob([zipOf(files)], {type: 'application/zip'}), filename);
}

function save(text, filename, type){
  handTo(new Blob([text], {type}), filename);
}

function handTo(blob, filename){
  const url = URL.createObjectURL(blob);
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
