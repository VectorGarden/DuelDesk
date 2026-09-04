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
