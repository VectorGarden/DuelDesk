/* DECKS — reading a post's deck lists, and handing them over as files.
 *
 * Shared by the reader, which shows one post's decks and offers them, and by
 * the coverage page, which offers an event's -- every deck list post it has,
 * in one download. Neither page owns this: a deck is the same thing on both,
 * and it was written twice for about a day before that stopped being true.
 *
 * Nothing here touches the page it is on. It reads paragraphs, gives back
 * decks, and writes .ydk, ydke:// and registration JSON out of them; what to
 * do with a deck once read is each page's own business.
 */

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
      /* A second Extra Deck is the Side Deck. The Top 8 lists from YCS
         Anaheim 2025 head both of Steven Trifunoski's last two piles "Extra
         Deck: 15", and the second holds Raigeki, Dark Hole, Lightning Storm
         and Dark Ruler No More -- Spells and Traps, which no Extra Deck may
         hold, fifteen of them, and he was the only Duelist in the post
         without a Side Deck. An Extra Deck of thirty is not a deck anybody
         could register.

         The one deck in the archive written this way, and it is only read as
         the Side Deck where there is no Side Deck to disagree with. */
      let next = pileOf(text);
      if (next === 'Extra' && deck && deck.Extra.length && !deck.Side.length){
        next = 'Side';
      }
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
      /* A second Extra Deck is the Side Deck -- see decksIn, which reads the
         same post the same way, or the two would disagree about the piles. */
      let next = pileOf(text);
      if (next === 'Extra' && deck && deck.piles.has('Extra') && !deck.piles.has('Side')){
        next = 'Side';
      }
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

