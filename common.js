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
      <span class="roster__n">${esc(m.name)}</span>
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
