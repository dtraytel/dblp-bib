'use strict';
// dblp-bib client: search (dblp-like), bibliography editing, options, dump updates.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const view = () => $('#view');

let DEFAULTS = {};
let S = { options: {}, doc: { path: '', items: [] }, nextId: 1 };   // persisted on the server (data/state.json)
let R = {};                 // rendered items by id
let BIB = '';               // the rendered .bib
let STATUS = null;
let current = 'search';

// ------------------------------------------------------------------ server

async function api(path, body) {
  const init = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch('/api/' + path, init);
  let j;
  try { j = await r.json(); } catch { j = { error: r.statusText }; }
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function toast(msg, err = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add('hidden'), err ? 6000 : 2500);
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const persist = debounce(() => api('state', S).catch(e => toast('Could not save state: ' + e.message, true)), 400);

let renderSeq = 0;
async function renderDoc() {
  const seq = ++renderSeq;
  if (!STATUS?.db) { R = {}; BIB = ''; refreshDocViews(); return; }
  try {
    const res = await api('render', { items: S.doc.items, options: S.options });
    if (seq !== renderSeq) return;
    R = Object.fromEntries(res.items.map(x => [x.id, x]));
    BIB = res.bib;
  } catch (e) { toast(e.message, true); }
  refreshDocViews();
}
const renderDocSoon = debounce(renderDoc, 150);

function changed() { persist(); renderDocSoon(); updateCount(); }

function updateCount() {
  $('#bibcount').textContent = S.doc.items.filter(i => i.kind !== 'other').length;
}

function refreshDocViews() {
  updateCount();
  if (current === 'bib') drawBib();
  const side = $('#side');
  if (side) side.innerHTML = sideHTML();
  $$('.pub').forEach(li => {
    const on = inBib(li.dataset.key);
    const b = $('.add', li);
    if (b) { b.classList.toggle('on', !!on); b.textContent = on ? '✓' : '+'; b.title = on ? 'In the bibliography (click to remove)' : 'Add to the bibliography'; }
  });
}

// ------------------------------------------------------------------ records

const TYPES = {
  journal: ['j', 'Journal article'], conference: ['c', 'Conference paper'], informal: ['i', 'Informal / preprint'],
  editorship: ['e', 'Editorship'], book: ['b', 'Book'], part: ['p', 'Part in book'], thesis: ['t', 'Thesis'], data: ['d', 'Data / artifact'],
};
function category(r) {
  if ((r.publtype || '').includes('informal') || r.venue === 'CoRR') return 'informal';
  return { article: 'journal', inproceedings: 'conference', proceedings: 'editorship', book: 'book', incollection: 'part',
           phdthesis: 'thesis', mastersthesis: 'thesis', data: 'data' }[r.type] || 'journal';
}
const stripNum = n => n.replace(/\s+\d{4}$/, '');
function nameHTML(n, me) {
  const m = n.match(/^(.*?)\s+(\d{4})$/);
  const label = m ? `${esc(m[1])}<span class="num">${m[2]}</span>` : esc(n);
  if (me && n === me) return `<span class="me">${label}</span>`;
  return `<a href="#author?name=${encodeURIComponent(n)}">${label}</a>`;
}
function peopleHTML(r, me, max = 30) {
  const people = r.authors.length ? r.authors : r.editors;
  let shown = people.slice(0, max).map(n => nameHTML(n, me)).join(', ');
  if (people.length > max) shown += `, … (${people.length} in total)`;
  return shown + (!r.authors.length && r.editors.length ? ' (eds.)' : '') + (people.length ? ':' : '');
}
function venueHTML(r) {
  const yr = r.year ? ` ${r.year}` : '';
  let v = esc(r.venue || '');
  if (r.type === 'article') {
    v += r.volume ? ` ${esc(r.volume)}` : '';
    v += r.number ? `(${esc(r.number)})` : '';
    v = `<a href="#toc?key=${encodeURIComponent(r.key)}">${v}</a>${yr}`;
  } else if (r.crossref) {
    v = `<a href="#toc?key=${encodeURIComponent(r.crossref)}">${v}${yr}</a>`;
  } else if (r.type === 'proceedings') {
    v = `<a href="#toc?key=${encodeURIComponent(r.key)}">${v || 'Contents'}</a>${yr}`;
  } else {
    v = v + yr;
  }
  if (r.extra?.series && r.type === 'proceedings') v += ` · ${esc(r.extra.series)} ${esc(r.volume || '')}`;
  return v + (r.pages ? `: ${esc(r.pages)}` : '');
}
function pubHTML(r, me) {
  const cat = category(r);
  const [letter, tname] = TYPES[cat];
  const on = inBib(r.key);
  const ee = r.extra?.ee || r.ee || [];
  const link = r.doi ? `https://doi.org/${r.doi}` : ee[0];
  const tags = (r.publtype || '').split(' ').filter(t => t && t !== 'informal').map(t => `<span class="tag">${esc(t)}</span>`).join('');
  return `<li class="pub" data-key="${esc(r.key)}">
    <div class="gutter"><span class="badge t-${letter}" title="${esc(tname)}">${letter}</span>
      <button class="add${on ? ' on' : ''}" data-act="toggle" title="${on ? 'In the bibliography (click to remove)' : 'Add to the bibliography'}">${on ? '✓' : '+'}</button></div>
    <div class="body">
      <div class="authors">${peopleHTML(r, me)}</div>
      <div class="title">${esc(r.title)}</div>
      <div class="venue">${venueHTML(r)}</div>
      <div class="meta"><a href="#" data-act="bibtex">BibTeX</a>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${r.doi ? 'DOI' : 'electronic edition'}</a>` : ''}
        <a href="https://dblp.org/rec/${esc(r.key)}.html" target="_blank" rel="noopener">dblp</a>
        <span class="muted mono">${esc(r.key)}</span>${tags}</div>
      <pre class="bibtex hidden"></pre>
    </div></li>`;
}
function listHTML(rs, me, years = false) {
  let out = '', y = null;
  for (const r of rs) {
    if (years && r.year !== y) { y = r.year; out += `<li class="year-head">${y ?? 'no year'}</li>`; }
    out += pubHTML(r, me);
  }
  return `<ul class="publist">${out}</ul>`;
}

function inBib(key) {
  return S.doc.items.find(i => (i.kind === 'dblp' && i.dblp === key) || (i.kind === 'raw' && i.match === key));
}
function newItem(o) { return { id: 'i' + (S.nextId++), ...o }; }

function toggleKey(key) {
  const it = inBib(key);
  if (it) {
    if (it.kind === 'raw') { toast('This entry comes from the loaded .bib file; remove it on the Bibliography page'); return; }
    S.doc.items = S.doc.items.filter(i => i !== it);
    toast('Removed ' + key);
  } else {
    S.doc.items.push(newItem({ kind: 'dblp', dblp: key }));
    toast('Added ' + key);
  }
  changed();
  refreshDocViews();
}

async function showBibtex(li) {
  const pre = $('pre.bibtex', li);
  if (!pre.classList.contains('hidden')) { pre.classList.add('hidden'); return; }
  try {
    const res = await api('render', { items: [{ id: 'x', kind: 'dblp', dblp: li.dataset.key }], options: S.options });
    pre.textContent = res.items[0].text;
    pre.classList.remove('hidden');
  } catch (e) { toast(e.message, true); }
}

document.addEventListener('click', e => {
  const a = e.target.closest('[data-act]');
  if (!a) return;
  const li = a.closest('.pub');
  if (li && a.dataset.act === 'toggle') { e.preventDefault(); toggleKey(li.dataset.key); }
  if (li && a.dataset.act === 'bibtex') { e.preventDefault(); showBibtex(li); }
});

// ------------------------------------------------------------------ side panel (bibliography summary)

function sideHTML() {
  const items = S.doc.items.filter(i => i.kind !== 'other');
  const lis = items.map(i => {
    const r = R[i.id];
    const key = r?.key || i.key || i.dblp || '…';
    return `<li><span class="k" title="${esc(r?.record?.title || key)}">${esc(key)}</span>
      ${i.kind === 'dblp' ? `<a href="#" data-side-rm="${i.id}" title="Remove">✕</a>` : '<span class="muted" title="from the loaded file">file</span>'}</li>`;
  }).join('');
  return `<h3><span>Bibliography</span><a href="#bib">open ›</a></h3>
    ${S.doc.path ? `<div class="muted mono" style="font-size:11.5px;margin-bottom:6px;word-break:break-all">${esc(S.doc.path)}</div>` : ''}
    ${items.length ? `<ul>${lis}</ul>` : '<p class="empty">Nothing yet. Click <b>+</b> next to a publication to add it.</p>'}
    <div class="toolbar" style="margin:0">
      <button class="btn small" data-bib="copy" ${items.length ? '' : 'disabled'}>Copy .bib</button>
      <button class="btn small" data-bib="download" ${items.length ? '' : 'disabled'}>Download</button>
      ${S.doc.path ? `<button class="btn small" data-bib="save">Save</button>` : ''}
    </div>`;
}
document.addEventListener('click', e => {
  const rm = e.target.closest('[data-side-rm]');
  if (rm) {
    e.preventDefault();
    S.doc.items = S.doc.items.filter(i => i.id !== rm.dataset.sideRm);
    changed(); refreshDocViews();
  }
  const b = e.target.closest('[data-bib]');
  if (b) { e.preventDefault(); bibAction(b.dataset.bib, b); }
});

// ------------------------------------------------------------------ routing

function route() {
  const [name, qs] = (location.hash.slice(1) || 'search').split('?');
  const p = new URLSearchParams(qs || '');
  current = name;
  $$('nav a').forEach(a => a.classList.toggle('active', a.dataset.nav === name || (a.dataset.nav === 'search' && ['author', 'toc'].includes(name))));
  window.scrollTo(0, 0);
  if (name === 'author') return showAuthor(p.get('name'));
  if (name === 'toc') return showToc(p.get('key'));
  if (name === 'bib') return drawBib();
  if (name === 'options') return drawOptions();
  if (name === 'data') return drawData();
  return showSearch(p);
}
window.addEventListener('hashchange', route);

function needDb() {
  if (STATUS?.db) return false;
  view().innerHTML = `<div class="welcome"><h1>No database yet</h1>
    <p>dblp-bib works on a local copy of the dblp dump. Download the current one from dblp.org on the
    <a href="#data">Data</a> page.</p></div>`;
  return true;
}

function withSide(html) {
  return `<div class="with-side"><div>${html}</div><aside class="side" id="side">${sideHTML()}</aside></div>`;
}

// ------------------------------------------------------------------ search

const SEARCH = { q: '', types: new Set(), from: '', to: '', sort: 'relevance', results: [], offset: 0, more: false };

$('#searchform').addEventListener('submit', e => {
  e.preventDefault();
  const q = $('#q').value.trim();
  location.hash = 'search?' + searchParams({ q });
});
document.addEventListener('keydown', e => {
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { e.preventDefault(); $('#q').focus(); $('#q').select(); }
});

function searchParams(over = {}) {
  const s = { q: SEARCH.q, types: [...SEARCH.types].join(','), from: SEARCH.from, to: SEARCH.to, sort: SEARCH.sort, ...over };
  return new URLSearchParams(Object.entries(s).filter(([, v]) => v && !(v === 'relevance'))).toString();
}

async function showSearch(p) {
  if (needDb()) return;
  SEARCH.q = p.get('q') || '';
  SEARCH.types = new Set((p.get('types') || '').split(',').filter(Boolean));
  SEARCH.from = p.get('from') || ''; SEARCH.to = p.get('to') || ''; SEARCH.sort = p.get('sort') || 'relevance';
  $('#q').value = SEARCH.q;
  if (!SEARCH.q) {
    view().innerHTML = withSide(`<div class="welcome"><h1>Search the local dblp</h1>
      <p class="sub">${Number(STATUS.db.records).toLocaleString()} records, dump from ${fmtDate(STATUS.db.source_mtime)}.</p>
      <ul>
        <li>All words must occur (as word prefixes) in the title, authors, venue or year: <code>traytel bounded natural</code></li>
        <li><code>"exact phrase"</code>, <code>author:blanchette</code>, <code>title:superposition</code>, <code>venue:CADE</code>, <code>year:2021</code>, <code>-exclude</code></li>
        <li>Click an author for all their publications, a venue for the table of contents of that volume.</li>
        <li>Click <b>+</b> to add a publication to the bibliography; see the <a href="#bib">Bibliography</a> page to edit, load and save .bib files, and <a href="#options">Options</a> for the substitutions.</li>
        <li>Press <kbd>/</kbd> to jump to the search box.</li>
      </ul></div>`);
    $('#q').focus();
    return;
  }
  view().innerHTML = withSide(`<h1>Search results</h1>
    <div class="filters">
      <div class="chips">${Object.entries(TYPES).map(([k, [l, n]]) => `<span class="chip${SEARCH.types.has(k) ? ' on' : ''}" data-type="${k}" title="${n}"><span class="badge t-${l}" style="width:14px;height:14px;line-height:14px;font-size:9px">${l}</span> ${n}</span>`).join('')}</div>
      <span>Years <input type="number" id="yfrom" value="${esc(SEARCH.from)}" placeholder="from"> – <input type="number" id="yto" value="${esc(SEARCH.to)}" placeholder="to"></span>
      <span>Sort <select id="sort"><option value="relevance">relevance</option><option value="year"${SEARCH.sort === 'year' ? ' selected' : ''}>year</option></select></span>
    </div>
    <div id="results"><p class="muted">Searching…</p></div>`);
  $$('.chip[data-type]').forEach(c => c.addEventListener('click', () => {
    SEARCH.types.has(c.dataset.type) ? SEARCH.types.delete(c.dataset.type) : SEARCH.types.add(c.dataset.type);
    location.hash = 'search?' + searchParams();
  }));
  const refilter = () => { SEARCH.from = $('#yfrom').value; SEARCH.to = $('#yto').value; SEARCH.sort = $('#sort').value; location.hash = 'search?' + searchParams(); };
  $('#yfrom').addEventListener('change', refilter); $('#yto').addEventListener('change', refilter); $('#sort').addEventListener('change', refilter);
  SEARCH.results = []; SEARCH.offset = 0;
  await loadResults();
}

async function loadResults() {
  const qs = new URLSearchParams({ q: SEARCH.q, offset: SEARCH.offset, limit: 50, types: [...SEARCH.types].join(','), from: SEARCH.from, to: SEARCH.to, sort: SEARCH.sort });
  let res;
  try { res = await api('search?' + qs); } catch (e) { $('#results').innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  if (res.error) { $('#results').innerHTML = `<p class="err">Query error: ${esc(res.error)}</p>`; return; }
  SEARCH.results.push(...res.results);
  SEARCH.offset += res.results.length;
  const el = $('#results');
  if (!el) return;
  el.innerHTML = SEARCH.results.length
    ? listHTML(SEARCH.results, null, SEARCH.sort === 'year') + (res.more ? '<div class="more"><button class="btn" id="moreBtn">More results</button></div>' : `<p class="muted">${SEARCH.results.length} result${SEARCH.results.length === 1 ? '' : 's'}.</p>`)
    : '<p class="muted">No matches.</p>';
  $('#moreBtn')?.addEventListener('click', e => { e.target.disabled = true; loadResults(); });
}

// ------------------------------------------------------------------ author & table of contents

async function showAuthor(name) {
  if (needDb()) return;
  view().innerHTML = withSide('<p class="muted">Loading…</p>');
  const res = await api('author?' + new URLSearchParams({ name }));
  const co = {};
  res.results.forEach(r => [...r.authors, ...r.editors].forEach(a => { if (a !== name) co[a] = (co[a] || 0) + 1; }));
  const top = Object.entries(co).sort((a, b) => b[1] - a[1]).slice(0, 12);
  view().innerHTML = withSide(`<h1>${esc(stripNum(name))}${name !== stripNum(name) ? ` <span class="num" style="font-size:13px">${esc(name.slice(-4))}</span>` : ''}</h1>
    <p class="sub">${res.results.length} publications · <a href="https://dblp.org/search?q=${encodeURIComponent(stripNum(name))}" target="_blank" rel="noopener">on dblp.org</a>
    · <a href="#search?q=${encodeURIComponent('author:"' + stripNum(name) + '"')}">search for name variants</a></p>
    ${top.length ? `<p class="muted" style="font-size:13px">Frequent co-authors: ${top.map(([a, n]) => `<a href="#author?name=${encodeURIComponent(a)}">${esc(stripNum(a))}</a> (${n})`).join(', ')}</p>` : ''}
    ${listHTML(res.results, name, true)}`);
}

async function showToc(key) {
  if (needDb()) return;
  view().innerHTML = withSide('<p class="muted">Loading…</p>');
  const res = await api('toc?' + new URLSearchParams({ key }));
  const h = res.head || {};
  const isProc = h.type === 'proceedings' || h.type === 'book';
  const addable = res.results.filter(r => r.key !== h.key);
  view().innerHTML = withSide(`<h1>${esc(h.title || key)}</h1>
    <p class="sub">${isProc ? `${peopleHTML({ authors: [], editors: h.editors || [] }, null, 12)} ${esc(h.series || '')} ${esc(h.volume || '')} · ${esc(h.year || '')}` : esc(h.year || '')}
      · ${addable.length} entries</p>
    ${isProc ? `<ul class="publist">${pubHTML(Object.assign({}, h, { extra: { ee: h.ee, series: h.series } }))}</ul><h2>Contents</h2>` : ''}
    <div class="toolbar"><button class="btn small" id="addAll">Add all ${addable.length} to the bibliography</button></div>
    ${listHTML(addable)}`);
  $('#addAll').addEventListener('click', () => {
    let n = 0;
    addable.forEach(r => { if (!inBib(r.key)) { S.doc.items.push(newItem({ kind: 'dblp', dblp: r.key })); n++; } });
    toast(`Added ${n} entries`); changed();
  });
}

// ------------------------------------------------------------------ bibliography

const OPEN = new Set();       // expanded items

function itemInfo(i) {
  const r = R[i.id] || {};
  const f = Object.fromEntries((r.fields || []).map(([k, v]) => [k, v]));
  if (i.kind === 'dblp' && r.record) {
    const rec = r.record;
    const ppl = (rec.authors.length ? rec.authors : rec.editors).map(stripNum);
    return `${esc(ppl.slice(0, 3).join(', '))}${ppl.length > 3 ? ' et al.' : ''}: <b>${esc(rec.title)}</b> ${esc(rec.venue || '')} ${esc(rec.year || '')}`;
  }
  const clean = latexToText;
  const who = clean(f.author || f.editor).split(/\s+and\s+/).filter(Boolean);
  return `${who.length ? esc(who.slice(0, 3).join('; ')) + (who.length > 3 ? ' et al.' : '') + ': ' : ''}<b>${esc(clean(f.title))}</b> ${esc(clean(f.booktitle || f.journal || f.publisher || f.howpublished || ''))} ${esc(f.year || '')}`;
}

const ACC = { '"': '\u0308', "'": '\u0301', '`': '\u0300', '^': '\u0302', '~': '\u0303', '=': '\u0304', '.': '\u0307', 'u': '\u0306', 'v': '\u030c', 'H': '\u030b', 'c': '\u0327', 'k': '\u0328', 'r': '\u030a' };
const SYM = { o: 'ø', O: 'Ø', ss: 'ß', l: 'ł', L: 'Ł', ae: 'æ', AE: 'Æ', oe: 'œ', aa: 'å', AA: 'Å', i: 'i', j: 'j' };
function latexToText(s) {
  return String(s || '')
    .replace(/\\([a-zA-Z]{1,2})(?![a-zA-Z])\s*/g, (m, c) => SYM[c] ?? m)
    .replace(/\\([\"'`^~=.]|[uvHckr](?=[{\s]))\s*\{?\s*(\\?[a-zA-Zıȷ])\}?/g, (m, a, ch) => (ch.replace('\\', '') + ACC[a]).normalize('NFC'))
    .replace(/\\(?:url|emph|textit|textbf|texttt|mathrm|text)\s*/g, '')
    .replace(/\\[a-zA-Z]+\s*/g, '').replace(/[{}$]/g, '').replace(/~/g, ' ').replace(/\s+/g, ' ').trim();
}

function statusOf(i) {
  const r = R[i.id] || {};
  if (r.error) return ['none', r.error];
  if (i.kind === 'other') return ['plain', 'comment / @string / @preamble'];
  if (i.kind === 'dblp') {
    const s = [['dblp', i.orig ? 'updated from dblp' : 'dblp']];
    if (r.upgrade?.length) s.push(['up', 'published version available']);
    return s;
  }
  if (r.alt?.same) return ['same', 'up to date with dblp'];
  if (r.alt) return ['diff', 'differs from dblp'];
  if (i.candidates?.length) return ['diff', 'possible matches'];
  if (i.checked) return ['none', 'not found in dblp'];
  return ['plain', 'not checked'];
}
function badges(i) {
  let s = statusOf(i);
  if (!Array.isArray(s[0])) s = [s];
  return s.map(([c, t]) => `<span class="st ${c}">${esc(t)}</span>`).join(' ');
}

function wordDiff(a, b) {
  const A = String(a ?? '').split(/(\s+)/), B = String(b ?? '').split(/(\s+)/);
  if (A.length * B.length > 250000) return [`<del>${esc(a)}</del>`, `<ins>${esc(b)}</ins>`];
  const L = Array.from({ length: A.length + 1 }, () => new Int32Array(B.length + 1));
  for (let x = A.length - 1; x >= 0; x--) for (let y = B.length - 1; y >= 0; y--)
    L[x][y] = A[x] === B[y] ? L[x + 1][y + 1] + 1 : Math.max(L[x + 1][y], L[x][y + 1]);
  let x = 0, y = 0, oa = '', ob = '';
  while (x < A.length && y < B.length) {
    if (A[x] === B[y]) { oa += esc(A[x]); ob += esc(B[y]); x++; y++; }
    else if (L[x + 1][y] >= L[x][y + 1]) { oa += `<del>${esc(A[x++])}</del>`; }
    else { ob += `<ins>${esc(B[y++])}</ins>`; }
  }
  while (x < A.length) oa += `<del>${esc(A[x++])}</del>`;
  while (y < B.length) ob += `<ins>${esc(B[y++])}</ins>`;
  return [oa, ob];
}

function diffTable(left, right, lt, rt) {
  const norm = v => String(v ?? '').replace(/\s+/g, ' ').trim();
  const a = Object.fromEntries(left.fields.map(([k, v]) => [k, norm(v)]));
  const b = Object.fromEntries(right.fields.map(([k, v]) => [k, norm(v)]));
  const names = [...new Set([...right.fields.map(f => f[0]), ...left.fields.map(f => f[0])])];
  const rows = [['@type', left.type, right.type], ['key', left.key, right.key], ...names.map(n => [n, a[n], b[n]])];
  return `<table class="diff"><tr><th style="width:90px"></th><th>${lt}</th><th>${rt}</th></tr>${rows.map(([n, x, y]) => {
    if (x === y) return `<tr><td class="f">${esc(n)}</td><td class="v">${esc(x)}</td><td class="v">${esc(y)}</td></tr>`;
    const [dx, dy] = x === undefined ? ['<span class="muted">—</span>', `<ins>${esc(y)}</ins>`] : y === undefined ? [`<del>${esc(x)}</del>`, '<span class="muted">—</span>'] : wordDiff(x, y);
    return `<tr class="changed"><td class="f">${esc(n)}</td><td class="v">${dx}</td><td class="v">${dy}</td></tr>`;
  }).join('')}</table>`;
}

function parsedOrig(i) { return i.origParsed; }

function itemHTML(i) {
  const r = R[i.id] || {};
  if (i.kind === 'other') {
    return `<li class="item" data-id="${i.id}"><div class="row"><span class="st plain">${esc(statusOf(i)[1])}</span>
      <span class="mono muted" style="font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1">${esc((i.raw || '').slice(0, 120))}</span>
      <div class="actions"><button class="btn small danger" data-it="remove">Remove</button></div></div></li>`;
  }
  const open = OPEN.has(i.id);
  let acts = '';
  if (i.kind === 'raw') {
    if (r.alt && !r.alt.same) acts += `<button class="btn small primary" data-it="use">Use dblp version</button>`;
    if (!i.checked) acts += `<button class="btn small" data-it="check">Check dblp</button>`;
  }
  if (i.kind === 'dblp' && i.orig) acts += `<button class="btn small" data-it="revert">Revert</button>`;
  if (i.kind === 'dblp' && r.upgrade?.length) acts += `<button class="btn small primary" data-it="upgrade">Use published version</button>`;
  acts += `<button class="btn small" data-it="toggle">${open ? 'Less' : 'Details'}</button><button class="btn small danger" data-it="remove" title="Remove from the bibliography">✕</button>`;
  let details = '';
  if (open) {
    if (i.kind === 'raw' && r.alt) details += diffTable(r, r.alt, 'in your file', 'from dblp (with your options)');
    else if (i.kind === 'dblp' && i.orig && i.origParsed && r.fields) details += diffTable(i.origParsed, r, 'originally in your file', 'now');
    else details += `<pre class="bibtex">${esc(r.text || i.raw || '')}</pre>`;
    if (i.kind === 'dblp' && r.upgrade?.length) details += `<div class="cands"><b>Published versions:</b>${r.upgrade.map(u => `<div>${esc(u.venue)} ${u.year}: ${esc(u.title)} <span class="how">${esc(u.key)}</span></div>`).join('')}</div>`;
    if (i.kind === 'raw' && i.candidates?.length) {
      details += `<div class="cands"><b>dblp candidates</b> (choose the record this entry corresponds to):
        <label><input type="radio" name="c-${i.id}" value="" ${!i.match ? 'checked' : ''}> none</label>
        ${i.candidates.map(c => `<label><input type="radio" name="c-${i.id}" value="${esc(c.key)}" ${i.match === c.key ? 'checked' : ''}>
          ${esc((c.authors.length ? c.authors : c.editors).slice(0, 3).map(stripNum).join(', '))}${c.authors.length > 3 ? ' et al.' : ''}: <b>${esc(c.title)}</b>
          ${esc(c.venue || '')} ${esc(c.year || '')} <span class="how">— ${esc(c.key)}, by ${esc(c.how)}</span></label>`).join('')}</div>`;
    }
  }
  const key = r.key || i.key || '';
  return `<li class="item" data-id="${i.id}">
    <div class="row"><input class="keyin" value="${esc(key)}" data-it="key" title="Citation key (editable)" spellcheck="false">
      ${badges(i)}<div class="actions">${acts}</div></div>
    <div class="desc">${itemInfo(i)}</div>${details}</li>`;
}

function drawBib() {
  if (current !== 'bib') return;
  const items = S.doc.items;
  const entries = items.filter(i => i.kind !== 'other');
  const raw = items.filter(i => i.kind === 'raw');
  const updatable = raw.filter(i => R[i.id]?.alt && !R[i.id].alt.same);
  const upgradable = items.filter(i => i.kind === 'dblp' && R[i.id]?.upgrade?.length);
  const unchecked = raw.filter(i => !i.checked);
  const scroll = window.scrollY;
  const focused = document.activeElement?.closest?.('.item')?.dataset.id;
  view().innerHTML = `<h1>Bibliography</h1>
    <div class="pathrow"><span class="muted">File</span><input class="text" id="path" placeholder="/path/to/references.bib (on this machine)" value="${esc(S.doc.path || '')}">
      <button class="btn" data-bib="load" title="Read the file at this path, or choose a file if the path is empty">Open</button>
      <button class="btn primary" data-bib="save" title="Write the bibliography to this path (keeps a .bak copy), or choose where if the path is empty">Save</button></div>
    <div class="toolbar">
      <label class="btn" title="Open a .bib file from your computer">Upload .bib…<input type="file" id="upload" accept=".bib,.txt" hidden></label>
      <button class="btn" data-bib="paste">Paste BibTeX…</button>
      <span class="sep"></span>
      <button class="btn" data-bib="copy" ${entries.length ? '' : 'disabled'}>Copy</button>
      <button class="btn" data-bib="download" ${entries.length ? '' : 'disabled'}>Download</button>
      <span class="sep"></span>
      <button class="btn" data-bib="sort-key">Sort by key</button>
      <button class="btn" data-bib="sort-year">Sort by author/year</button>
      <button class="btn danger" data-bib="clear" ${items.length ? '' : 'disabled'}>Clear</button>
    </div>
    <div id="pastebox" class="hidden"><textarea id="pastetext" rows="8" placeholder="Paste BibTeX entries here"></textarea>
      <div class="toolbar"><button class="btn primary" data-bib="paste-add">Add these entries</button><button class="btn" data-bib="paste-cancel">Cancel</button></div></div>
    ${raw.length ? `<div class="card"><b>Entries from your file:</b> ${raw.length}
      <div class="summary">${unchecked.length ? `<button class="btn small" data-bib="check-all">Check ${unchecked.length} against dblp</button>` : ''}
      ${updatable.length ? `<button class="btn small primary" data-bib="update-all">Use the dblp version for all ${updatable.length} that differ</button>` : ''}
      <span class="st same">${raw.filter(i => R[i.id]?.alt?.same).length} up to date</span>
      <span class="st diff">${updatable.length} differ from dblp</span>
      <span class="st diff">${raw.filter(i => !R[i.id]?.alt && i.candidates?.length).length} uncertain</span>
      <span class="st none">${raw.filter(i => i.checked && !i.candidates?.length).length} not in dblp</span></div>
      <span class="muted" style="font-size:12.5px">Updated entries keep their citation keys${S.options.keep_keys ? '' : ' — currently off in Options'}; “Revert” restores the original text.</span></div>` : ''}
    ${upgradable.length ? `<div class="card"><span class="st up">${upgradable.length} preprint${upgradable.length > 1 ? 's have' : ' has'} a published version</span>
      <button class="btn small primary" data-bib="upgrade-all">Use the published versions</button></div>` : ''}
    <div class="dropzone" id="drop">Drop a .bib file here to open it</div>
    <div class="bibgrid">
      <div>${entries.length || items.length ? `<ul class="items">${items.map(itemHTML).join('')}</ul>` : '<p class="muted">The bibliography is empty: add publications from the search results, or open a .bib file.</p>'}</div>
      <div class="preview"><h3 style="margin-top:0">.bib preview</h3><pre class="bibtex">${esc(BIB.trim() ? BIB : '% empty')}</pre></div>
    </div>`;
  window.scrollTo(0, scroll);
  if (focused) $(`.item[data-id="${focused}"] .keyin`)?.focus();
  $('#upload').addEventListener('change', async e => {
    const f = e.target.files[0];
    if (f) await openText(await f.text(), '');
  });
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', async e => { const f = e.dataTransfer.files[0]; if (f) await openText(await f.text(), ''); });
  $('#path').addEventListener('change', e => { S.doc.path = e.target.value.trim(); persist(); });
}

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-it]');
  if (!b || b.tagName === 'INPUT') return;
  const li = b.closest('.item');
  const i = S.doc.items.find(x => x.id === li?.dataset.id);
  if (!i) return;
  e.preventDefault();
  const act = b.dataset.it;
  if (act === 'toggle') { OPEN.has(i.id) ? OPEN.delete(i.id) : OPEN.add(i.id); drawBib(); return; }
  if (act === 'remove') { S.doc.items = S.doc.items.filter(x => x !== i); changed(); drawBib(); return; }
  if (act === 'use') useDblp(i);
  if (act === 'revert') {
    if (i.prevDblp) { Object.assign(i, { dblp: i.prevDblp, key: i.prevKey || '' }); delete i.prevDblp; delete i.prevKey; }
    else { Object.assign(i, { kind: 'raw', raw: i.orig, match: i.dblp }); delete i.dblp; delete i.key; }
    delete i.orig; delete i.origParsed;
  }
  if (act === 'upgrade') upgrade(i);
  if (act === 'check') { await checkItems([i]); OPEN.add(i.id); }
  changed();
});
document.addEventListener('change', e => {
  const t = e.target;
  const li = t.closest?.('.item');
  const i = li && S.doc.items.find(x => x.id === li.dataset.id);
  if (!i) return;
  if (t.dataset.it === 'key') setKey(i, t.value.trim());
  if (t.type === 'radio' && t.name === 'c-' + i.id) { i.match = t.value || null; changed(); }
});

function setKey(i, key) {
  if (!key) return;
  if (i.kind === 'dblp') i.key = key;
  else if (i.kind === 'raw') i.raw = i.raw.replace(/^(\s*@\s*\w+\s*[{(]\s*)[^,\s]*/, `$1${key}`);
  changed();
}

function useDblp(i) {
  const r = R[i.id];
  if (!i.match || !r) return;
  Object.assign(i, { kind: 'dblp', orig: i.raw, origParsed: { type: r.type, key: r.key, fields: r.fields }, dblp: i.match,
                     key: S.options.keep_keys ? r.key : '' });
  delete i.raw;
}
function upgrade(i) {
  const r = R[i.id];
  if (!r?.upgrade?.length) return;
  if (!i.orig) { i.orig = r.text; i.origParsed = { type: r.type, key: r.key, fields: r.fields }; i.prevDblp = i.dblp; i.prevKey = i.key || ''; }
  if (!i.key && S.options.keep_keys) i.key = r.key;   // keep the citation key the paper uses
  i.dblp = r.upgrade[0].key;
}

async function checkItems(items) {
  const raw = items.filter(i => i.kind === 'raw');
  for (let k = 0; k < raw.length; k += 25) {
    const chunk = raw.slice(k, k + 25);
    try {
      const res = await api('match', { items: chunk.map(i => ({ id: i.id, raw: i.raw })) });
      chunk.forEach(i => { const m = res.matches[i.id]; i.checked = true; i.candidates = m.candidates; i.match = m.best; });
    } catch (e) { toast(e.message, true); return; }
    if (raw.length > 25) toast(`Checked ${Math.min(k + 25, raw.length)} of ${raw.length}`);
  }
}

async function openText(text, path) {
  let res;
  try { res = await api('parse', { text }); } catch (e) { toast(e.message, true); return; }
  const items = res.items.map(p => p.kind === 'entry' ? newItem({ kind: 'raw', raw: p.raw }) : newItem({ kind: 'other', raw: p.raw }));
  let append = false;
  if (S.doc.items.length) {
    append = !confirm(`Replace the current bibliography (${S.doc.items.length} items) with this file?\n\nOK: replace · Cancel: append the entries instead`);
  }
  if (append) S.doc.items.push(...items);
  else { S.doc.items = items; S.doc.path = path; OPEN.clear(); }
  const errs = res.items.filter(p => p.error).length;
  toast(`Read ${items.filter(i => i.kind === 'raw').length} entries${errs ? `, ${errs} unparsable chunk(s) kept as text` : ''}; checking against dblp…`);
  changed();
  if (STATUS?.db) { await checkItems(items); changed(); toast('Checked the entries against dblp'); }
}

async function bibAction(act, btn) {
  const name = (S.doc.path || 'references.bib').split('/').pop();
  if (act === 'copy') {
    try { await navigator.clipboard.writeText(BIB); toast('Copied the .bib to the clipboard'); } catch { toast('Clipboard not available', true); }
  } else if (act === 'download') {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([BIB], { type: 'application/x-bibtex' }));
    a.download = name.endsWith('.bib') ? name : name + '.bib';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } else if (act === 'save') {
    let path = ($('#path')?.value || S.doc.path || '').trim();
    try {
      if (!path) {                                   // no path: the desktop's save-as dialog (via the server)
        btn.disabled = true;
        const res = await api('file/choose', { save: true, name: 'references.bib' }).finally(() => { btn.disabled = false; });
        path = res.unsupported ? prompt('Save to which .bib file on this machine?', '') : res.path;
        if (!path) return;                           // cancelled
      }
      await renderDoc();
      const res = await api('file/save', { path, text: BIB, backup: true });
      S.doc.path = res.path; persist();
      toast(`Saved ${res.path}${res.backup ? ' (previous version in .bak)' : ''}`);
      if (current === 'bib') drawBib();
    } catch (e) { toast(e.message, true); }
  } else if (act === 'load') {
    let path = $('#path').value.trim();
    try {
      if (!path) {                                   // no path: the desktop's file dialog (via the server, which learns the path)
        btn.disabled = true;
        const res = await api('file/choose', {}).finally(() => { btn.disabled = false; });
        if (res.unsupported) { $('#upload').click(); return; }   // fallback: the browser's dialog (no path, so Save asks for one)
        if (!res.path) return;                       // cancelled
        path = res.path;
      }
      const res = await api('file/load', { path });
      await openText(res.text, res.path);
    } catch (e) { toast(e.message, true); }
  } else if (act === 'paste') {
    $('#pastebox').classList.remove('hidden'); $('#pastetext').focus();
  } else if (act === 'paste-cancel') {
    $('#pastebox').classList.add('hidden');
  } else if (act === 'paste-add') {
    const text = $('#pastetext').value;
    const res = await api('parse', { text });
    const items = res.items.map(p => newItem({ kind: p.kind === 'entry' ? 'raw' : 'other', raw: p.raw }));
    S.doc.items.push(...items);
    changed();
    await checkItems(items); changed();
    toast(`Added ${items.length} item(s)`);
  } else if (act === 'clear') {
    if (confirm('Remove all entries from the bibliography? (The file on disk is not touched.)')) { S.doc.items = []; S.doc.path = ''; OPEN.clear(); changed(); }
  } else if (act === 'check-all') {
    btn.disabled = true; await checkItems(S.doc.items.filter(i => i.kind === 'raw' && !i.checked)); changed();
  } else if (act === 'update-all') {
    let n = 0;
    S.doc.items.forEach(i => { if (i.kind === 'raw' && R[i.id]?.alt && !R[i.id].alt.same) { useDblp(i); n++; } });
    toast(`Updated ${n} entries from dblp`); changed();
  } else if (act === 'upgrade-all') {
    let n = 0;
    S.doc.items.forEach(i => { if (i.kind === 'dblp' && R[i.id]?.upgrade?.length) { upgrade(i); n++; } });
    toast(`Switched ${n} preprints to their published versions`); changed();
  } else if (act === 'sort-key' || act === 'sort-year') {
    const keyOf = i => (R[i.id]?.key || '').toLowerCase();
    const ay = i => {
      const r = R[i.id] || {};
      const f = Object.fromEntries((r.fields || []).map(([k, v]) => [k, v]));
      const first = String(f.author || f.editor || '').split(/\s+and\s+/)[0].replace(/[{}\\"']/g, '');
      const last = first.includes(',') ? first.split(',')[0] : first.split(/\s+/).pop();
      return `${last.toLowerCase()} ${f.year || ''} ${keyOf(i)}`;
    };
    const k = act === 'sort-key' ? keyOf : ay;
    const others = S.doc.items.filter(i => i.kind === 'other' && /^\s*@\s*(string|preamble)/i.test(i.raw));
    const rest = S.doc.items.filter(i => !others.includes(i) && i.kind !== 'other');
    const comments = S.doc.items.filter(i => i.kind === 'other' && !others.includes(i));
    S.doc.items = [...others, ...comments, ...rest.sort((a, b) => k(a).localeCompare(k(b)))];
    changed();
  }
}

// ------------------------------------------------------------------ options

const OPTION_UI = [
  { h: 'Venues' },
  { k: 'series_abbrev', t: 'check', l: 'Abbreviate series and journal names', hint: 'Lecture Notes in Computer Science → LNCS etc., using the list below (one “Long name = Short” per line).' },
  { k: 'series_map', t: 'area', rows: 6, show: o => o.series_abbrev },
  { k: 'booktitle', t: 'radio', l: 'Conference names (booktitle)', choices: [
    ['keep', 'Keep dblp’s full title', '10th International Conference on Interactive Theorem Proving, ITP 2019, Portland, OR, USA, September 9-12, 2019'],
    ['clean', 'Name and acronym, without ordinal, the words below, location and date', 'Conference on Interactive Theorem Proving, ITP 2019'],
    ['acronym', 'Acronym and year only', 'ITP 2019']] },
  { k: 'full_years', t: 'check', l: 'Write years in full in conference names', hint: 'POPL \'20, MFCS\'91, RTA-87 → POPL 2020, MFCS 1991, RTA 1987. A number after a hyphen only counts when it matches the year of the entry, so CADE-28 stays.' },
  { k: 'strip_words', t: 'text', l: 'Words removed from conference names', hint: 'Comma-separated, e.g. “International, Annual”.', show: o => o.booktitle === 'clean' },
  { h: 'Links' },
  { k: 'url_doi', t: 'radio', l: 'url and doi', choices: [
    ['keep', 'Keep both, as dblp does'],
    ['dedupe', 'Drop the url when it is just the DOI link', 'url = {https://doi.org/10.1007/…} is removed if doi = {10.1007/…}'],
    ['prefer_doi', 'Drop the url whenever there is a DOI']] },
  { h: 'Fields' },
  { k: 'drop_dblp_meta', t: 'check', l: 'Drop dblp metadata', hint: 'timestamp, biburl, bibsource' },
  { k: 'drop_fields', t: 'text', l: 'Other fields to drop', hint: 'Comma-separated, e.g. “editor, publisher, isbn”.' },
  { h: 'Formatting' },
  { k: 'latex', t: 'check', l: 'Write accents and symbols as LaTeX commands', hint: 'Sch{\\"{a}}ffeler instead of Schäffeler (turn off for biblatex/biber with UTF-8).' },
  { k: 'protect_caps', t: 'check', l: 'Protect capitalized words with braces', hint: 'In titles and booktitles: {HOL}, {Isabelle/HOL}, {ACM} keep their case in all bibliography styles.' },
  { k: 'abbrev_names', t: 'check', l: 'Abbreviate first names', hint: 'Jasmin Christian Blanchette → J. C. Blanchette' },
  { k: 'key_style', t: 'radio', l: 'Citation keys for new entries', choices: [
    ['dblp', 'dblp keys', 'DBLP:conf/itp/BrunT19'], ['short', 'Short dblp keys', 'BrunT19'], ['authoryear', 'Author, year, title word', 'brun2019generic']] },
  { h: 'Existing .bib files' },
  { k: 'keep_keys', t: 'check', l: 'Keep citation keys when updating an entry from dblp', hint: 'So that \\cite commands in the paper keep working.' },
  { k: 'normalize_foreign', t: 'check', l: 'Apply the substitutions also to entries that are not from dblp', hint: 'Series names, conference names, url/doi, dropped fields and custom rules.' },
  { h: 'Custom rules' },
  { k: 'custom_rules', t: 'area', rows: 5, l: 'Regular-expression substitutions, applied last', hint: 'One per line: “field: regex => replacement”, field * for all. An empty result removes the field. Example: “publisher: ^Schloss Dagstuhl.*$ => Schloss Dagstuhl”.' },
];

function drawOptions() {
  const o = S.options;
  const field = d => {
    if (d.h) return `</div><div class="card"><h2>${esc(d.h)}</h2>`;
    if (d.show && !d.show(o)) return '';
    const hint = d.hint ? `<span class="hint">${esc(d.hint)}</span>` : '';
    if (d.t === 'check') return `<label class="opt"><input type="checkbox" data-opt="${d.k}" ${o[d.k] ? 'checked' : ''}> ${esc(d.l)}${hint}</label>`;
    if (d.t === 'text') return `<div class="optblock"><span class="lbl">${esc(d.l)}</span><input class="text" style="width:100%" data-opt="${d.k}" value="${esc(o[d.k])}">${hint.replace('class="hint"', 'class="muted" style="font-size:12.5px"')}</div>`;
    if (d.t === 'area') return `<div class="optblock">${d.l ? `<span class="lbl">${esc(d.l)}</span>` : ''}<textarea rows="${d.rows}" data-opt="${d.k}" spellcheck="false">${esc(o[d.k])}</textarea>${hint.replace('class="hint"', 'class="muted" style="font-size:12.5px"')}</div>`;
    if (d.t === 'radio') return `<div class="optblock"><span class="lbl">${esc(d.l)}</span>${d.choices.map(([v, l, ex]) =>
      `<label class="opt radio"><input type="radio" name="${d.k}" data-opt="${d.k}" value="${v}" ${o[d.k] === v ? 'checked' : ''}> ${esc(l)}${ex ? `<span class="hint example">${esc(ex)}</span>` : ''}</label>`).join('')}</div>`;
    return '';
  };
  view().innerHTML = `<h1>Options</h1><p class="sub">Applied to every entry generated from dblp, immediately (also to entries already in the bibliography).</p>
    <div class="optgrid"><div><div class="card" style="display:none">${OPTION_UI.map(field).join('')}</div>
      <div class="toolbar"><button class="btn" id="resetOpts">Reset to defaults</button></div></div>
      <div class="preview"><div class="card"><h2>Preview</h2><p class="muted" style="margin-top:0">dblp’s BibTeX on the left, with your options on the right${S.doc.items.some(i => i.kind === 'dblp') ? ' (entries from your bibliography)' : ''}.</p><div id="optprev" class="muted">…</div></div></div></div>`;
  $$('[data-opt]').forEach(el => el.addEventListener(el.tagName === 'TEXTAREA' || el.type === 'text' ? 'input' : 'change', () => {
    const k = el.dataset.opt;
    o[k] = el.type === 'checkbox' ? el.checked : el.value;
    changed();
    optionPreviewSoon();
    if (el.type === 'checkbox' || el.type === 'radio') { const y = window.scrollY; drawOptions(); window.scrollTo(0, y); }
  }));
  $('#resetOpts').addEventListener('click', () => { if (confirm('Reset all options to their defaults?')) { S.options = { ...DEFAULTS }; changed(); drawOptions(); } });
  optionPreview();
}

const DBLP_PLAIN = { series_abbrev: false, booktitle: 'keep', url_doi: 'keep', drop_dblp_meta: false, drop_fields: '', latex: true,
                     protect_caps: true, abbrev_names: false, key_style: 'dblp', custom_rules: '' };
async function optionPreview() {
  const el = $('#optprev');
  if (!el || !STATUS?.db) return;
  let keys = S.doc.items.filter(i => i.kind === 'dblp').slice(0, 3).map(i => i.dblp);
  if (!keys.length) keys = ['conf/itp/BrunT19', 'conf/cade/FurerLST20', 'journals/pacmpl/BruggeMPT25'];
  const items = keys.map((k, n) => ({ id: 'p' + n, kind: 'dblp', dblp: k }));
  try {
    const [a, b] = await Promise.all([api('render', { items, options: { ...S.options, ...DBLP_PLAIN } }), api('render', { items, options: S.options })]);
    el.innerHTML = a.items.filter(x => !x.error).map((x, n) => diffTable(x, b.items[n], 'dblp', 'with your options')).join('<br>') || 'No example records.';
    el.classList.remove('muted');
  } catch (e) { el.textContent = e.message; }
}
const optionPreviewSoon = debounce(optionPreview, 250);

// ------------------------------------------------------------------ data (dump)

function fmtDate(t) { return t ? new Date(Number(t) * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '?'; }
function fmtTime(t) { return t ? new Date(Number(t) * 1000).toLocaleString() : '?'; }

async function drawData() {
  STATUS = await api('status');
  const db = STATUS.db, job = STATUS.job;
  view().innerHTML = `<h1>Data</h1><p class="sub">The local copy of dblp that search and BibTeX generation use.</p>
    <div class="optgrid"><div>
    <div class="card"><h2>Database</h2>${db ? `<dl class="kv">
        <dt>Records</dt><dd>${Number(db.records).toLocaleString()}</dd>
        <dt>Dump date</dt><dd>${fmtDate(db.source_mtime)}</dd>
        <dt>Indexed</dt><dd>${fmtTime(db.built)} (${Math.round(db.build_seconds / 60)} min)</dd></dl>`
      : '<p>No database yet: download the dump below.</p>'}</div>
    <div class="card"><h2>Update</h2>
      <p style="margin-top:0">Download the current dump from dblp.org (about 1 GB) and rebuild the index (about 5 minutes;
      the database needs about 6 GB, twice that while rebuilding). Search keeps working on the old data meanwhile.</p>
      <div class="toolbar"><button class="btn" id="checkRemote">Check dblp.org for a newer dump</button>
        <button class="btn primary" id="download" ${job.running ? 'disabled' : ''}>Download and rebuild</button></div>
      <div id="remote" class="muted"></div>
      ${STATUS.dump ? `<h3>Rebuild without downloading</h3>
      <p class="muted" style="margin-top:0">From the dump downloaded earlier (${fmtDate(STATUS.dump.mtime)}, ${(STATUS.dump.size / 2 ** 20).toFixed(0)} MB).</p>
      <div class="toolbar"><button class="btn" id="rebuild" ${job.running ? 'disabled' : ''}>Rebuild</button></div>` : ''}
    </div></div>
    <div><div class="card" id="jobcard"></div></div></div>`;
  drawJob(job);
  $('#checkRemote').addEventListener('click', async () => {
    $('#remote').textContent = 'Asking dblp.org…';
    try {
      const r = await api('remote');
      const newer = !db || (r.modified && r.modified > Number(db.source_mtime) + 3600);
      $('#remote').innerHTML = `dblp.org has a dump from <b>${fmtDate(r.modified)}</b> (${(r.size / 2 ** 20).toFixed(0)} MB): ${newer ? '<b>newer than yours</b>.' : 'yours is up to date.'}`;
    } catch (e) { $('#remote').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
  $('#download').addEventListener('click', () => startJob({ mode: 'download' }));
  $('#rebuild')?.addEventListener('click', () => startJob({ mode: 'rebuild' }));
  if (job.running) pollJob();
}

function drawJob(job) {
  const el = $('#jobcard');
  if (!el) return;
  if (!job || !job.phase) { el.innerHTML = '<h2>Status</h2><p class="muted">No update has run since the server started.</p>'; return; }
  const label = { start: 'Starting', download: 'Downloading', import: 'Reading the dump', index: 'Building the search index', done: 'Finished', error: 'Failed' }[job.phase] || job.phase;
  el.innerHTML = `<h2>Status</h2><p style="margin:0"><b>${label}</b> ${job.running ? '' : job.phase === 'done' ? '✓' : ''}</p>
    ${job.running ? `<div class="progress"><div style="width:${(job.phase === 'index' ? 100 : job.frac * 100).toFixed(1)}%"></div></div>` : ''}
    <p class="${job.phase === 'error' ? 'err' : 'muted'}">${esc(job.msg || '')}${job.running && job.phase === 'index' ? ' (no progress reported for this step)' : ''}</p>
    ${job.started ? `<p class="muted" style="font-size:12.5px">Started ${fmtTime(job.started)}${job.finished ? `, finished ${fmtTime(job.finished)}` : ''}</p>` : ''}`;
}

async function startJob(body) {
  try {
    await api('update', body);
    toast('Update started');
    drawData();
  } catch (e) { toast(e.message, true); }
}

async function pollJob() {
  const st = await api('status').catch(() => null);
  if (!st) return;
  const wasRunning = STATUS?.job?.running;
  STATUS = st;
  if (current === 'data') drawJob(st.job);
  checkBanner();
  if (st.job.running) setTimeout(pollJob, 1000);
  else if (wasRunning) { if (current === 'data') drawData(); renderDoc(); toast(st.job.phase === 'done' ? 'The database has been rebuilt' : 'Update failed', st.job.phase !== 'done'); }
}

function checkBanner() {
  const b = $('#banner');
  if (STATUS?.job?.running) {
    b.innerHTML = `Updating the dblp database: ${esc(STATUS.job.msg || '')} — <a href="#data">details</a>`;
    b.classList.remove('hidden');
  } else if (!STATUS?.db) {
    b.innerHTML = 'No dblp database yet. <a href="#data">Download the dblp dump</a>.';
    b.classList.remove('hidden');
  } else b.classList.add('hidden');
}

// ------------------------------------------------------------------ start

(async function init() {
  try {
    STATUS = await api('status');
    DEFAULTS = STATUS.defaults;
    const st = await api('state');
    S = { options: { ...DEFAULTS, ...(st.options || {}) }, doc: st.doc || { path: '', items: [] }, nextId: st.nextId || 1 };
    S.doc.items = (S.doc.items || []).filter(Boolean);
  } catch (e) { view().innerHTML = `<p class="err">Cannot reach the server: ${esc(e.message)}</p>`; return; }
  checkBanner();
  updateCount();
  if (STATUS.job.running) pollJob();
  route();
  renderDoc();
})();
