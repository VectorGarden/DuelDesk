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

let popup = null;
let showing = null;

function hideCard(){
  showing = null;
  if (popup) popup.hidden = true;
}

async function showCard(span){
  const name = span.textContent;
  showing = span;
  const card = await lookupCard(name);
  /* The reader may have moved on while the shard was fetched, and a card
     opening under a cursor that has gone is worse than none. */
  if (showing !== span || !card) return;
  if (!popup){
    popup = document.createElement('div');
    popup.className = 'cardpop';
    popup.id = 'cardpop';
    popup.setAttribute('role', 'tooltip');
    document.body.append(popup);
  }
  popup.innerHTML = cardPanel(card);
  popup.hidden = false;
  span.setAttribute('aria-describedby', 'cardpop');
  /* Beside the name, and flipped when there is no room below or to the
     right. Measured after it is filled, because its height is its text. */
  const at = span.getBoundingClientRect();
  const box = popup.getBoundingClientRect();
  /* Clamped to the left edge last, so a card wider than the window lands on
     screen rather than off it. */
  const left = Math.max(8, Math.min(at.left, window.innerWidth - box.width - 8));
  const below = at.bottom + 8;
  const top = below + box.height < window.innerHeight ? below : at.top - box.height - 8;
  popup.style.left = `${left + window.scrollX}px`;
  popup.style.top = `${Math.max(8, top) + window.scrollY}px`;
}

function watchCards(root){
  markCards(root);
  const enter = (e) => {
    const span = e.target.closest?.('.cardref');
    if (span) showCard(span); else if (e.type === 'focusin') hideCard();
  };
  root.addEventListener('mouseover', enter);
  root.addEventListener('focusin', enter);
  root.addEventListener('mouseout', (e) => {
    if (e.target.closest?.('.cardref')) hideCard();
  });
  root.addEventListener('focusout', hideCard);
  /* Escape closes it, which is what a tooltip owes a keyboard. */
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideCard(); });
  window.addEventListener('scroll', hideCard, {passive: true});
}

applyTheme();
load();
