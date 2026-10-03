// Safe Procure — app shell, Configure view, live Run view, Copilot.
import { $, $$, h, icon, esc, inr, num, short, clock, api, debounce, setRangeFill, toast, store, sparkline, tierChip, onEcharts } from './ui.js';
import { FlowGraph, NODES } from './graph.js';
import { renderInsights, rerenderCharts, selectTab, TAB_LIST, openVendor } from './insights.js';
import { initFx, setMode, retheme, warp, burst, pulseAt } from './fx.js';
import { initPalette } from './palette.js';

const RM = matchMedia('(prefers-reduced-motion: reduce)');
// Cinematic view changes: an iris opens from where the user clicked (View Transitions API; plain swap where unsupported).
let lastPoint = null, vtSeq = 0;
addEventListener('pointerdown', (e) => { lastPoint = [e.clientX, e.clientY]; }, true);
export function cinematic(fn, kind = 'iris') {
  if (!document.startViewTransition || RM.matches || !S.booted) { fn(); return; }
  const [x, y] = lastPoint || [innerWidth / 2, innerHeight / 2];
  const root = document.documentElement;
  root.style.setProperty('--vx', `${x}px`); root.style.setProperty('--vy', `${y}px`);
  root.dataset.vt = kind;
  lastPoint = null;
  const t = document.startViewTransition(fn);
  t.ready.catch(() => {}); // a newer transition skipped this one; the DOM update still ran
  const mine = ++vtSeq;
  t.finished.catch(() => {}).finally(() => { if (mine === vtSeq) delete root.dataset.vt; });
}
const decisionMix = (r) => {
  const m = { keep: 0, watch: 0, develop: 0, replace: 0 };
  (r?.vendors || []).filter((v) => v.in_scope).forEach((v) => { const d = v.decision?.decision?.toLowerCase(); if (d in m) m[d] += 1; });
  return m;
};

const PILLARS = [
  { key: 'delivery', label: 'Delivery', color: '#3E3AE0' },
  { key: 'quality', label: 'Quality', color: '#0A6B9E' },
  { key: 'cost', label: 'Cost', color: '#0B7A4E' },
  { key: 'responsiveness', label: 'Responsiveness', color: '#A85A06' },
  { key: 'compliance', label: 'Compliance', color: '#BE2A21' },
];
const PRESETS = {
  Balanced: { delivery: 30, quality: 25, cost: 20, responsiveness: 10, compliance: 15 },
  'Delivery first': { delivery: 50, quality: 20, cost: 10, responsiveness: 10, compliance: 10 },
  'Cost first': { delivery: 15, quality: 15, cost: 50, responsiveness: 5, compliance: 15 },
  'Risk averse': { delivery: 25, quality: 25, cost: 5, responsiveness: 10, compliance: 35 },
};
const PROMPTS = [
  'Which vendors put our Q4 production at risk, and what should we do about each one?',
  'Where can we cut 10% of cost without hurting on-time delivery?',
  'How exposed are we to steel and logistics disruption right now?',
  'Which vendors deserve more volume next quarter?',
];
const CAT_SHORT = { 'Steel & Metals': 'Steel', 'Packaging': 'Packaging', 'Electronic Components': 'Electronics', 'Logistics & Freight': 'Logistics', 'Chemicals & Plastics': 'Chemicals' };

export const S = {
  health: null, dataset: null, weights: { ...PRESETS.Balanced }, genCats: null, scopeCats: [],
  baselineRanks: {}, prevRanks: {}, run: null, result: null, route: 'configure',
};

/* ================================================================ routing */
function route() {
  const r = (location.hash.replace('#/', '') || 'configure').split('/')[0];
  const target = ['configure', 'run', 'insights'].includes(r) ? r : 'configure';
  if (target === 'insights' && !S.result) {
    if (S.run && !S.run.done) { location.hash = '#/run'; return; }
    if (S.health?.saved_run) { loadSaved(); return; }
    location.hash = '#/configure'; return;
  }
  if (target === 'run' && !S.run) {
    if (S.result) { S.route = 'run'; showReplayIdle(); }
    else if (S.health?.saved_run) { loadSaved(true); return; }
    else { location.hash = '#/configure'; return; }
  }
  const changed = S.route !== target || !S.shown;
  S.shown = true;
  if (changed) cinematic(() => showView(target)); else showView(target);
}
function showView(target) {
  S.route = target;
  setMode(target === 'run' ? (S.run && !S.run.done ? 'run' : 'calm') : target, target === 'insights' ? decisionMix(S.result) : null);
  $$('.view').forEach((v) => { v.hidden = v.dataset.view !== target; });
  $$('[data-nav]').forEach((a) => { if (a.dataset.nav !== target) a.removeAttribute('aria-current'); else a.setAttribute('aria-current', 'page'); });
  $('#copilot-fab').hidden = !(target === 'insights' && S.result);
  if (target !== 'insights') closeCopilot();
  if (target === 'insights') renderInsights(S.result);
  window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  // Move focus to the new view's heading so screen readers announce the page change without reading the whole view.
  const h1 = $(`.view[data-view="${target}"] h1`);
  if (h1) { h1.tabIndex = -1; h1.focus({ preventScroll: true }); } else $('#main').focus({ preventScroll: true });
  requestAnimationFrame(moveNavIndicator);
}
// Liquid indicator that slides under the active workflow step.
function moveNavIndicator() {
  const a = $('.steps a[aria-current="page"]'), ind = $('.steps-ind');
  if (!a || !ind) return;
  const n = $('.steps').getBoundingClientRect(), r = a.getBoundingClientRect();
  ind.style.transform = `translateX(${r.left - n.left}px)`; ind.style.width = `${r.width}px`;
  $('.steps').dataset.step = a.dataset.nav;
}
function lockNav() {
  $('[data-nav="run"]').classList.toggle('locked', !S.run && !S.result && !S.health?.saved_run);
  $('#btn-replay').hidden = !S.result || (S.run && !S.run.done);
  $('[data-nav="insights"]').classList.toggle('locked', !S.result && !S.health?.saved_run);
}

/* ================================================================== theme */
function syncThemeButton() {
  const cur = document.documentElement.dataset.theme;
  const dark = cur === 'dark' || (cur !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  const b = $('#theme-toggle');
  b.setAttribute('aria-label', 'Dark theme'); b.setAttribute('aria-pressed', String(dark));
}
function initTheme() {
  syncThemeButton();
  $('#theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme;
    const sysDark = matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = cur === 'dark' || (cur === 'auto' && sysDark);
    const next = isDark ? 'light' : 'dark';
    cinematic(() => {
      document.documentElement.dataset.theme = next;
      store.set('sp-theme', next); try { localStorage.setItem('sp-theme', next); } catch (e) { /* */ }
      retheme();
      rerenderCharts();
      renderMiniChart();
      syncThemeButton();
    }, 'theme');
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { retheme(); rerenderCharts(); renderMiniChart(); });
}

/* ================================================================= health */
async function loadHealth() {
  const pill = $('#status-pill');
  try {
    S.health = await api('/api/health');
    const ready = S.health.endpoints.filter((e) => e.available);
    const provs = new Set(ready.map((e) => e.provider));
    pill.className = `status-pill ${ready.length ? 'ok' : 'bad'}`;
    pill.querySelector('.label').innerHTML = ready.length ? `${ready.length} models<span class="lx"> · ${provs.size} providers</span> ready` : 'No API keys configured';
    pill.title = ready.map((e) => e.label).join(', ');
    $('#btn-saved').hidden = !S.health.saved_run;
  } catch (e) {
    pill.className = 'status-pill bad';
    pill.querySelector('.label').textContent = 'Server unreachable';
    toast('Cannot reach the Safe Procure server. Is it still running?', 'err');
  }
  lockNav();
}

/* ============================================================== configure */
function initConfigure() {
  // data source tabs
  $$('#panel-data [role="tab"]').forEach((b) => b.addEventListener('click', () => {
    $$('#panel-data [role="tab"]').forEach((x) => x.setAttribute('aria-selected', x === b));
    $('#src-sample').hidden = b.dataset.src !== 'sample';
    $('#src-upload').hidden = b.dataset.src !== 'upload';
  }));
  $$('#panel-data [role="tab"]').forEach((b, i, all) => b.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const n = all[(i + (e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length]; n.focus(); n.click(); }
  }));

  // ranges with outputs
  const bindRange = (id, out, fmt = (v) => v, cb) => {
    const r = $(id);
    $(out).setAttribute('aria-hidden', 'true'); // the slider itself announces the value via aria-valuetext
    const upd = () => { setRangeFill(r); $(out).textContent = fmt(r.value); r.setAttribute('aria-valuetext', String(fmt(r.value))); cb?.(); };
    r.addEventListener('input', upd); upd();
  };
  bindRange('#in-nv', '#o-nv');
  bindRange('#in-mo', '#o-mo');
  bindRange('#in-th', '#o-th', (v) => v, () => updateLaunchInfo());
  bindRange('#in-otd', '#o-otd', (v) => `${v}%`);
  bindRange('#in-def', '#o-def', (v) => `${Number(v).toFixed(1)}%`);

  $('#btn-dice').addEventListener('click', () => { $('#in-seed').value = Math.floor(Math.random() * 99999) + 1; });
  $('#btn-generate').addEventListener('click', generate);

  // upload
  const drop = $('#drop');
  const file = $('#in-file');
  file.addEventListener('change', () => file.files[0] && upload(file.files[0]));
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  $('#dl-template').addEventListener('click', (e) => { e.preventDefault(); if (S.dataset) location.href = `/api/dataset/${S.dataset.dataset_id}/csv`; });

  // question
  const pc = $('#prompt-chips');
  // Chips ship in the HTML (no layout shift when the script arrives); build them only if missing.
  if (!pc.children.length) PROMPTS.forEach((p) => pc.append(h('button', { type: 'button' }, p)));
  $$('button', pc).forEach((b) => b.addEventListener('click', () => { $('#in-question').value = b.textContent; $('#in-question').focus(); updateLaunchInfo(); }));
  $('#in-question').addEventListener('input', debounce(updateLaunchInfo, 200));

  // weights
  const presets = $('#presets');
  Object.keys(PRESETS).forEach((name) => presets.append(h('button', { type: 'button', 'aria-pressed': name === 'Balanced', onclick: () => applyPreset(name) }, name)));
  const wbox = $('#weights');
  PILLARS.forEach((p) => {
    const id = `w-${p.key}`;
    const input = h('input', { type: 'range', id, min: 0, max: 60, value: S.weights[p.key] });
    const out = h('output', { id: `${id}-o`, for: id, 'aria-hidden': 'true' }, '');
    input.addEventListener('input', () => { S.weights[p.key] = Number(input.value); markPreset(); renderWeights(); rescoreSoon(); });
    wbox.append(h('div', { class: 'weight' }, h('label', { for: id }, h('span', { class: 'sw', style: { background: p.color } }), p.label), input, out));
  });
  renderWeights();

  $('#btn-run').addEventListener('click', startRun);
  $('#btn-saved').addEventListener('click', () => loadSaved());
  $('#btn-replay').addEventListener('click', replay);
}

function applyPreset(name) {
  S.weights = { ...PRESETS[name] };
  PILLARS.forEach((p) => { $(`#w-${p.key}`).value = S.weights[p.key]; });
  markPreset(); renderWeights(); rescoreSoon();
}
function markPreset() {
  const match = Object.entries(PRESETS).find(([, w]) => PILLARS.every((p) => w[p.key] === S.weights[p.key]))?.[0];
  $$('#presets button').forEach((b) => b.setAttribute('aria-pressed', b.textContent === match));
}
function renderWeights() {
  const total = PILLARS.reduce((a, p) => a + S.weights[p.key], 0) || 1;
  PILLARS.forEach((p) => {
    const r = $(`#w-${p.key}`); setRangeFill(r);
    const share = `${Math.round((S.weights[p.key] / total) * 100)}%`;
    $(`#w-${p.key}-o`).textContent = share;
    r.setAttribute('aria-valuetext', `${share} of total weight`);
  });
  const bar = $('#weight-bar');
  bar.innerHTML = '';
  PILLARS.forEach((p) => bar.append(h('span', { style: { flexGrow: S.weights[p.key] || 0.001, background: p.color } })));
}

function renderGenCats() {
  const cats = S.health?.categories || Object.keys(CAT_SHORT);
  if (!S.genCats) S.genCats = [...cats];
  const box = $('#gen-cats'); box.innerHTML = '';
  cats.forEach((c) => {
    const b = h('button', { type: 'button', class: 'chip', 'aria-pressed': S.genCats.includes(c) }, icon('check', 'tick'), CAT_SHORT[c] || c);
    b.addEventListener('click', () => {
      const on = S.genCats.includes(c);
      if (on && S.genCats.length <= 2) { toast('Keep at least two categories.'); return; }
      S.genCats = on ? S.genCats.filter((x) => x !== c) : [...S.genCats, c];
      b.setAttribute('aria-pressed', !on);
    });
    box.append(b);
  });
}

function renderScopeCats() {
  const cats = S.dataset?.quality.categories || [];
  const box = $('#scope-cats'); box.innerHTML = '';
  S.scopeCats = S.scopeCats.filter((c) => cats.includes(c));
  const all = h('button', { type: 'button', class: 'chip', 'aria-pressed': S.scopeCats.length === 0 }, icon('check', 'tick'), 'All categories');
  all.addEventListener('click', () => { S.scopeCats = []; renderScopeCats(); updateLaunchInfo(); renderRanks(S.dataset.scorecard); });
  box.append(all);
  cats.forEach((c) => {
    const b = h('button', { type: 'button', class: 'chip', 'aria-pressed': S.scopeCats.includes(c) }, icon('check', 'tick'), CAT_SHORT[c] || c);
    b.addEventListener('click', () => {
      S.scopeCats = S.scopeCats.includes(c) ? S.scopeCats.filter((x) => x !== c) : [...S.scopeCats, c];
      if (S.scopeCats.length === cats.length) S.scopeCats = [];
      renderScopeCats(); updateLaunchInfo(); renderRanks(S.dataset.scorecard);
    });
    box.append(b);
  });
}

async function generate() {
  const btn = $('#btn-generate');
  btn.classList.add('loading'); btn.disabled = true;
  try {
    const ds = await api('/api/dataset/sample', { method: 'POST', body: {
      n_vendors: Number($('#in-nv').value), months: Number($('#in-mo').value), seed: Number($('#in-seed').value) || 42,
      categories: S.genCats, inject_quality_issues: $('#in-issues').checked } });
    setDataset(ds);
  } catch (e) { toast(`Could not generate data: ${e.message}`, 'err'); }
  finally { btn.classList.remove('loading'); btn.disabled = false; }
}

async function upload(f) {
  const fd = new FormData(); fd.append('file', f);
  const box = $('#dataset');
  box.innerHTML = '<div class="skeleton-block" aria-hidden="true"></div>';
  try {
    const ds = await api('/api/dataset/upload', { method: 'POST', body: fd });
    setDataset(ds);
    toast(`Loaded ${f.name}: ${ds.quality.vendors} vendors.`);
  } catch (e) {
    box.innerHTML = '';
    box.append(h('div', { class: 'empty' }, h('b', {}, 'That file could not be used'), e.message));
    toast(e.message, 'err');
  }
}

function setDataset(ds) {
  S.dataset = ds;
  S.baselineRanks = Object.fromEntries(ds.scorecard.map((r) => [r.vendor, r.rank]));
  S.prevRanks = {};
  renderDataset();
  renderScopeCats();
  rescore();
  $('#btn-run').disabled = false;
  updateLaunchInfo();
}

function renderDataset() {
  const ds = S.dataset, q = ds.quality;
  const box = $('#dataset'); box.innerHTML = '';
  box.append(h('dl', { class: 'ds-facts' },
    h('div', {}, h('dt', {}, 'Vendors'), h('dd', {}, q.vendors)),
    h('div', {}, h('dt', {}, 'Period'), h('dd', {}, `${q.n_months} mo`)),
    h('div', {}, h('dt', {}, 'Spend'), h('dd', {}, inr(q.total_spend))),
    h('div', {}, h('dt', {}, 'Rows'), h('dd', {}, num(q.rows_in))),
    h('div', {}, h('dt', {}, 'Quality'), h('dd', {}, `${q.quality_score}`)),
  ));
  if (q.issues.length) {
    const ul = h('ul', { class: 'issues', 'aria-label': 'Data issues found and auto-cleaned' });
    q.issues.forEach((i) => ul.append(h('li', {}, icon('alert'), h('span', { html: `<b>${i.count} ${esc(i.type.replace('_', ' '))}</b> in <code class="mono">${esc(i.column)}</code>. ${esc(i.action)}.` }))));
    box.append(ul);
  }
  if (ds.notes?.length) box.append(h('ul', { class: 'notes' }, ds.notes.map((n) => h('li', {}, n))));
  box.append(h('div', { class: 'mini-chart', id: 'mini-chart', role: 'img', 'aria-label': 'Monthly spend across all vendors' }));
  renderMiniChart();
  const cols = ds.columns;
  const table = h('table', { class: 'data' },
    h('thead', {}, h('tr', {}, cols.map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, ds.preview.map((r) => h('tr', {}, cols.map((c) => h('td', { class: typeof r[c] === 'string' ? 'txt' : '' }, r[c]))))));
  box.append(h('details', { class: 'preview' }, h('summary', {}, `Preview first ${ds.preview.length} of ${num(ds.row_count)} rows`), h('div', { class: 'table-scroll', tabindex: '0' }, table)));
}

function renderMiniChart() {
  const node = $('#mini-chart');
  if (!node || !window.echarts || !S.dataset) return;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const ch = echarts.getInstanceByDom(node) || echarts.init(node, null, { renderer: 'svg' });
  const m = S.dataset.monthly_spend;
  ch.setOption({
    animationDuration: 600, grid: { left: 6, right: 6, top: 10, bottom: 20 },
    xAxis: { type: 'category', data: m.months, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: css('--ink-3'), fontSize: 10, interval: Math.ceil(m.months.length / 6) - 1, fontFamily: 'Geist Mono' } },
    yAxis: { type: 'value', show: false },
    tooltip: { trigger: 'axis', valueFormatter: (v) => inr(v), backgroundColor: css('--surface'), borderColor: css('--line'), textStyle: { color: css('--ink'), fontFamily: 'Geist' } },
    series: [{ type: 'bar', data: m.spend, barWidth: '62%', itemStyle: { color: css('--brand'), borderRadius: [3, 3, 0, 0], opacity: 0.85 } }],
  }, true);
}

const rescoreSoon = debounce(() => rescore(), 140);
async function rescore() {
  if (!S.dataset) return;
  try {
    const r = await api(`/api/dataset/${S.dataset.dataset_id}/score`, { method: 'POST', body: { weights: S.weights } });
    S.dataset.scorecard = r.scorecard;
    renderRanks(r.scorecard);
  } catch (e) { toast(e.message, 'err'); }
}

function renderRanks(rows) {
  const list = $('#rank-list');
  const scoped = S.scopeCats.length ? rows.filter((r) => S.scopeCats.includes(r.category)) : rows;
  const prev = S.prevRanks;
  // FLIP: remember where each vendor row was, re-render, then glide rows from old to new positions.
  const before = Object.fromEntries($$('li[data-v]', list).map((li) => [li.dataset.v, li.getBoundingClientRect()]));
  list.innerHTML = '';
  scoped.forEach((r, i) => {
    const base = S.baselineRanks[r.vendor];
    const mv = base ? base - r.rank : 0;
    const li = h('li', { class: prev[r.vendor] && prev[r.vendor] !== r.rank ? 'flash' : '', 'data-v': r.vendor, style: { '--tc': `var(--${{ A: 'keep', B: 'develop', C: 'watch', D: 'replace' }[r.tier] || 'brand'})`, '--sc': `${Math.max(4, r.composite)}%` } },
      h('span', { class: 'rk' }, i + 1),
      h('span', { class: 'nm' }, h('b', { title: r.vendor }, short(r.vendor)), h('span', {}, `${CAT_SHORT[r.category] || r.category} · risk ${Math.round(r.internal_risk)}`)),
      h('span', { class: 'sc' },
        h('span', { class: `mv ${mv > 0 ? 'up' : mv < 0 ? 'down' : ''}`, title: mv ? 'Rank change vs balanced weights' : null, 'aria-hidden': 'true' },
          mv ? icon(mv > 0 ? 'arrow-up' : 'arrow-down') : '', mv ? h('span', {}, Math.abs(mv)) : ''),
        mv ? h('span', { class: 'sr-only' }, `${mv > 0 ? 'up' : 'down'} ${Math.abs(mv)} places versus balanced weights, `) : '',
        h('span', {}, h('span', { class: 'sr-only' }, 'score '), r.composite.toFixed(1)), tierChip(r.tier)));
    list.append(li);
  });
  if (!RM.matches && Object.keys(before).length) {
    $$('li[data-v]', list).forEach((li) => {
      const o = before[li.dataset.v];
      if (!o) return;
      const n = li.getBoundingClientRect(), dx = o.left - n.left, dy = o.top - n.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      li.animate([{ transform: `translate(${dx}px, ${dy}px)`, zIndex: 2 }, { transform: 'none', zIndex: 2 }], { duration: 650, easing: 'cubic-bezier(.2,1.35,.4,1)' });
    });
  }
  // One short announcement per rescore instead of re-reading the whole list.
  const moved = Object.keys(prev).length ? rows.filter((r) => prev[r.vendor] && prev[r.vendor] !== r.rank).length : 0;
  if (Object.keys(prev).length && scoped.length) $('#rank-sr').textContent = `Ranking updated. ${moved ? `${moved} vendors changed rank. ` : 'No rank changes. '}Top vendor: ${short(scoped[0].vendor)}.`;
  S.prevRanks = Object.fromEntries(rows.map((r) => [r.vendor, r.rank]));
}

function updateLaunchInfo() {
  const info = $('#launch-info');
  const noKeys = S.health && !S.health.endpoints.some((e) => e.available);
  $('#btn-run').disabled = !S.dataset || noKeys;
  if (noKeys) { info.innerHTML = '<b>No model keys on the server.</b> Set GROQ_API_KEY and/or GEMINI_API_KEY, restart, and the agents will be ready. The instant scorecard still works.'; return; }
  if (!S.dataset) { info.textContent = 'Load or generate a dataset to begin.'; return; }
  const n = S.scopeCats.length ? S.dataset.scorecard.filter((r) => S.scopeCats.includes(r.category)).length : S.dataset.scorecard.length;
  const q = $('#in-question').value.trim();
  info.innerHTML = `<b>${n} vendors</b> in scope · risk tolerance <b>${$('#in-th').value}</b> · ${q ? 'custom question' : 'full portfolio review'}. Typical run: about 1.5 minutes on free-tier models.`;
}

/* ==================================================================== run */
const RUN = { graph: null, es: null, timer: null, t0: 0, stats: {}, lanes: {}, events: [], stageOut: {}, stageModel: {}, pollSeq: 0 };

async function startRun() {
  if (!S.dataset) return;
  const btn = $('#btn-run');
  btn.classList.add('loading'); btn.disabled = true;
  try {
    const body = {
      dataset_id: S.dataset.dataset_id, question: $('#in-question').value.trim(), weights: S.weights,
      risk_threshold: Number($('#in-th').value), otd_floor: Number($('#in-otd').value), defect_ceiling: Number($('#in-def').value),
      focus_categories: S.scopeCats,
    };
    const r = await api('/api/runs', { method: 'POST', body });
    RUN.replayTimers?.forEach(clearTimeout); RUN.replaying = false;
    S.run = { id: r.run_id, done: false, question: body.question || 'Full vendor portfolio risk review' };
    S.result = null;
    store.set('sp-last-run', r.run_id);
    warp();
    beginRunView();
    location.hash = '#/run';
  } catch (e) {
    toast(`Could not start: ${e.message}`, 'err');
  } finally { btn.classList.remove('loading'); btn.disabled = false; lockNav(); }
}

function beginRunView(live = true) {
  Object.assign(RUN, { t0: Date.now(), stats: { stages: 0, calls: 0, tokens: 0, fail: 0 }, events: [], stageOut: {}, stageModel: {}, pollSeq: 0, lanes: {} });
  $('#run-question').textContent = `“${S.run.question}”`;
  $('#trace').innerHTML = '';
  $('#trace').append(h('li', { class: 'trace-empty' }, 'Connecting to the agent crew…'));
  $('#run-done-bar').hidden = true;
  $('#inspector').innerHTML = '';
  RUN.graph.reset();
  renderLanes();
  clearInterval(RUN.timer);
  RUN.timer = setInterval(tickRun, 500);
  setMode('run');
  const pill = $('#status-pill');
  if (live) {
    RUN.timeScale = 1; RUN.replaying = false;
    pill.className = 'status-pill live'; pill.querySelector('.label').textContent = 'Agents running';
    connect();
  }
  $('#btn-replay').hidden = true;
}

function connect() {
  RUN.es?.close();
  let gotAny = false;
  const es = new EventSource(`/api/runs/${S.run.id}/events`);
  RUN.es = es;
  es.onmessage = (m) => { gotAny = true; const ev = JSON.parse(m.data); if (ev.seq >= RUN.pollSeq) { RUN.pollSeq = ev.seq + 1; onEvent(ev); } };
  es.addEventListener('done', () => { es.close(); finishRun(); });
  es.onerror = () => { es.close(); if (!S.run.done) poll(); };
  setTimeout(() => { if (!gotAny && !S.run.done) { es.close(); poll(); } }, 6000);
}

async function poll() {
  if (S.run.done) return;
  try {
    const r = await api(`/api/runs/${S.run.id}/poll?since=${RUN.pollSeq}`);
    r.events.forEach((ev) => { if (ev.seq >= RUN.pollSeq) { RUN.pollSeq = ev.seq + 1; onEvent(ev); } });
    if (r.done) { finishRun(); return; }
  } catch (e) { /* transient */ }
  setTimeout(poll, 1200);
}

function tickRun() {
  const s = ((Date.now() - RUN.t0) / 1000) * (RUN.timeScale || 1);
  $('#st-time').textContent = clock(s);
  $('#st-stages').textContent = `${RUN.stats.stages}/10`;
  $('#st-calls').textContent = num(RUN.stats.calls);
  $('#st-tokens').textContent = num(RUN.stats.tokens);
  $('#st-fail').textContent = num(RUN.stats.fail);
  renderLanes();
}

const STAGE_OF = Object.fromEntries(Object.entries(NODES).map(([k, n]) => [n.name, k]));

function onEvent(ev) {
  RUN.events.push(ev);
  const stage = ev.stage || STAGE_OF[ev.agent];
  switch (ev.type) {
    case 'stage_start': RUN.graph.set(ev.stage, 'active'); break;
    case 'stage_end':
      RUN.stats.stages = new Set(RUN.events.filter((e) => e.type === 'stage_end').map((e) => e.stage)).size;
      RUN.stageOut[ev.stage] = ev.output;
      RUN.graph.set(ev.stage, ev.status === 'ok' ? 'done' : 'degraded', RUN.stageModel[ev.stage] ? `${RUN.stageModel[ev.stage]} · ${ev.seconds}s` : `${ev.seconds}s`);
      if (RUN.graph.selected === ev.stage || !RUN.graph.selected) inspect(ev.stage);
      pulseAt(RUN.graph.nodes[ev.stage]?.g.querySelector('.card'), ev.status === 'ok' ? 'keep' : 'watch');
      $('#run-sr').textContent = `${NODES[ev.stage]?.name || ev.agent} ${ev.status === 'ok' ? 'finished' : 'fell back to rules'}. ${RUN.stats.stages} of 10 stages done.`;
      break;
    case 'llm_end':
      RUN.stats.calls += 1; RUN.stats.tokens += (ev.prompt_tokens || 0) + (ev.completion_tokens || 0);
      (RUN.lanes[ev.model] ||= []).push({ t: ev.t, tok: (ev.prompt_tokens || 0) + (ev.completion_tokens || 0) });
      if (stage) { RUN.stageModel[stage] = ev.model; if (RUN.graph.state[stage] === 'active') RUN.graph.model(stage, `on ${ev.model}`); }
      break;
    case 'llm_start':
      if (stage && RUN.graph.state[stage] === 'active') RUN.graph.model(stage, `thinking · ${ev.model}`);
      break;
    case 'tool_start':
      if (stage && RUN.graph.state[stage] === 'active') RUN.graph.model(stage, `using ${ev.tool}`);
      break;
    case 'failover': RUN.stats.fail += 1; break;
    case 'route': RUN.graph.route(ev.stage, ev.route); pulseAt(ev.stage === 'risk_gate' ? RUN.graph.gate : RUN.graph.nodes.qa?.g, ev.route === 'mitigate' || ev.route === 'revise' ? 'replace' : 'brand'); break;
    default: break;
  }
  appendTrace(ev);
}

function argsText(a) {
  if (!a || !Object.keys(a).length) return '';
  return Object.entries(a).map(([k, v]) => `${k}=${Array.isArray(v) ? `[${v.length}]` : JSON.stringify(v).slice(0, 60)}`).join(', ');
}

function stageSummary(o) {
  if (!o) return '';
  return o.headline || o.summary || o.portfolio_summary || o.objective || (o.verdict ? `Verdict: ${o.verdict}` : '') || '';
}

function appendTrace(ev) {
  const list = $('#trace');
  list.querySelector('.trace-empty')?.remove();
  let cls = '', ic = 'network', html = '', verbose = false;
  const A = `<b>${esc(ev.agent || '')}</b>`;
  switch (ev.type) {
    case 'run_start': cls = 'k-stage'; ic = 'play'; html = `Run started with <b>${ev.vendors}</b> vendors in scope`; break;
    case 'stage_start': cls = 'k-stage'; ic = 'network'; html = `${A} started`; break;
    case 'stage_end': cls = ev.status === 'ok' ? 'k-done' : 'k-warn'; ic = ev.status === 'ok' ? 'check' : 'alert';
      html = `${A} finished in ${ev.seconds}s<span class="q">${esc(String(stageSummary(ev.output)).slice(0, 180))}</span>`; break;
    case 'stage_error': cls = 'k-bad'; ic = 'alert'; html = `${A} hit an error, so deterministic rules took over for this stage<span class="q">${esc(ev.message)}</span>`; break;
    case 'tool_start': ic = 'tool'; html = `${A} called <code>${esc(ev.tool)}(${esc(argsText(ev.args))})</code>`; break;
    case 'tool_end': ic = 'tool'; verbose = true; html = `<code>${esc(ev.tool)}</code> returned ${num(ev.chars)} chars in ${ev.seconds}s`; break;
    case 'llm_end': ic = 'spark'; verbose = true; html = `${A} ← ${esc(ev.model)} · ${num(ev.prompt_tokens)} in / ${num(ev.completion_tokens)} out · ${ev.seconds}s`; break;
    case 'llm_error': cls = 'k-warn'; ic = 'alert'; html = `${esc(ev.model)} refused a call from ${A} (${esc(ev.kind.replace('_', ' '))})`; break;
    case 'failover': cls = 'k-warn'; ic = 'shuffle'; html = `Router moved ${A} to <b>${esc(ev.to_model)}</b> (${esc(ev.reason)})`; break;
    case 'throttle': ic = 'gauge'; verbose = true; html = `Pacing ${A}: waiting ${ev.wait}s for ${esc(ev.model)} budget`; break;
    case 'risk_blend': cls = 'k-route'; ic = 'globe'; html = `Market risk blended into the scorecard: <b>${ev.flagged}</b> vendors above tolerance`; break;
    case 'route': cls = 'k-route'; ic = 'flag';
      html = ev.stage === 'risk_gate' ? `Risk gate → <b>${ev.route === 'mitigate' ? 'Mitigation Planner' : ev.reason === 'already_planned' ? 'QA (mitigation plan already covers these vendors)' : 'QA (no high-risk vendors)'}</b>${ev.targets?.length ? `<span class="q">${esc(ev.targets.map(short).join(', '))}</span>` : ''}`
        : `QA verdict → <b>${ev.route === 'revise' ? 'send back to Strategist' : 'publish'}</b>`; break;
    case 'guardrails': cls = ev.flags?.length ? 'k-warn' : 'k-done'; ic = 'shield'; html = `Guardrails ran: <b>${ev.flags?.length || 0}</b> automated flags`; break;
    case 'run_end': cls = 'k-done'; ic = 'check'; html = `Run complete · ${num(ev.usage?.llm_calls)} LLM calls · ${num(ev.usage?.total_tokens)} tokens`; break;
    case 'run_error': cls = 'k-bad'; ic = 'alert'; html = `Run error: ${esc(ev.message)}`; break;
    default: return;
  }
  const li = h('li', { class: `${cls}${verbose ? ' v' : ''}` }, h('span', { class: 'tt' }, clock(ev.t)), h('span', { class: 'ic' }, icon(ic)), h('span', { class: 'tx', html }));
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.append(li);
  if (nearBottom) list.scrollTop = list.scrollHeight;
}

function renderLanes() {
  const box = $('#lanes');
  if (!S.health) return;
  const now = RUN.events.length ? RUN.events[RUN.events.length - 1].t + (S.run && !S.run.done ? 0 : 0) : 0;
  const tNow = S.run && !S.run.done ? ((Date.now() - RUN.t0) / 1000) * (RUN.timeScale || 1) : now;
  const rows = S.health.endpoints.filter((e) => e.available);
  if (box.children.length !== rows.length) {
    box.innerHTML = '';
    rows.forEach((e) => box.append(h('div', { class: 'lane idle', 'data-lane': e.label },
      h('div', { class: 'nm' }, h('b', {}, e.label), h('span', {}, `${e.provider === 'groq' ? 'Groq' : 'Google'} · ${e.tpm >= 1000 ? `${Math.round(e.tpm / 1000)}k` : e.tpm} tokens/min`)),
      h('div', { class: 'bar', role: 'meter', 'aria-label': `${e.label} budget used`, 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': 0 }, h('i', { style: { width: '0%' } })),
      h('div', { class: 'vl' }, '0'))));
  }
  const cooling = new Set(RUN.events.filter((e) => e.type === 'llm_error' && tNow - e.t < 30).map((e) => e.model));
  rows.forEach((e) => {
    const lane = box.querySelector(`[data-lane="${CSS.escape(e.label)}"]`);
    const used = (RUN.lanes[e.label] || []).filter((x) => tNow - x.t <= 60).reduce((a, x) => a + x.tok, 0);
    const calls = (RUN.lanes[e.label] || []).length;
    const p = Math.min(100, (used / e.tpm) * 100);
    const bar = lane.querySelector('.bar i');
    bar.style.width = `${p}%`;
    bar.className = cooling.has(e.label) ? 'cool' : p > 75 ? 'hot' : '';
    lane.querySelector('.bar').setAttribute('aria-valuenow', Math.round(p));
    lane.querySelector('.vl').textContent = calls ? `${used >= 1000 ? `${(used / 1000).toFixed(1)}k` : used} · ${calls}×` : '—';
    lane.classList.toggle('idle', !calls);
  });
}

function inspect(id) {
  const n = NODES[id];
  const box = $('#inspector');
  const evs = RUN.events.filter((e) => e.stage === id || STAGE_OF[e.agent] === id);
  const tools = [...new Set(evs.filter((e) => e.type === 'tool_start').map((e) => e.tool))];
  const models = [...new Set(evs.filter((e) => e.type === 'llm_end').map((e) => e.model))];
  const end = evs.find((e) => e.type === 'stage_end');
  const out = RUN.stageOut[id];
  box.innerHTML = '';
  box.append(h('div', { class: 'insp-head' },
    h('div', {}, h('h3', {}, n.name), h('p', {}, n.role)),
    end ? h('span', { class: `decision ${end.status === 'ok' ? 'Keep' : 'Watch'}` }, end.status === 'ok' ? `Done in ${end.seconds}s` : 'Rule fallback') : RUN.graph.state[id] === 'failed' ? h('span', { class: 'decision Replace' }, 'Stopped here')
      : h('span', { class: 'tag' }, RUN.graph.state[id] === 'active' ? 'Working…' : RUN.graph.state[id] === 'skipped' ? 'Skipped by router' : 'Waiting')));
  box.append(h('div', { class: 'kv' },
    models.map((m) => h('span', { class: 'tag brand' }, icon('spark'), m)),
    tools.map((t) => h('span', { class: 'tag' }, icon('tool'), t)),
    h('span', { class: 'tag' }, `${evs.filter((e) => e.type === 'llm_end').length} LLM calls`)));
  if (out) {
    const sum = stageSummary(out);
    if (sum) box.append(h('p', { class: 'insp-out' }, sum));
    box.append(h('details', {}, h('summary', { class: 'meta' }, 'Structured output (JSON)'), h('pre', { class: 'json' }, JSON.stringify(out, null, 2))));
  } else {
    const err = RUN.graph.state[id] === 'failed' && [...RUN.events].reverse().find((e) => e.type === 'run_error' || e.type === 'stage_error');
    box.append(h('p', { class: 'meta' }, err ? `The run ended before this agent produced output: ${err.message}` : 'Output appears here when the agent finishes. Select any node to inspect it.'));
  }
}

async function finishRun() {
  if (S.run.done) return;
  S.run.done = true;
  clearInterval(RUN.timer); tickRun();
  // A fatal run_error or HTTP 410 means no result is coming; otherwise retry briefly while the result is written.
  const fatal = RUN.events.some((e) => e.type === 'run_error');
  for (let i = 0; i < (fatal ? 1 : 20); i++) {
    try {
      const r = await api(`/api/runs/${S.run.id}`);
      if (!r._pending) { S.result = r; break; }
    } catch (e) { if (e.status === 410) break; }
    await new Promise((res) => setTimeout(res, 800));
  }
  const pill = $('#status-pill');
  if (S.result) {
    pill.className = 'status-pill ok'; pill.querySelector('.label').textContent = 'Analysis ready';
    const u = S.result.usage;
    $('#run-done-info').innerHTML = `<b>Done in ${clock(u.elapsed)}</b> · ${num(u.llm_calls)} model calls across ${Object.keys(u.per_model).length} models · ${num(u.failovers)} automatic failovers${S.result.degraded.length ? ` · ${S.result.degraded.length} stage(s) on rule fallback` : ''}`;
    $('#run-done-actions').innerHTML = '<a class="btn primary lg" href="#/insights"><svg class="i"><use href="#i-chart"/></svg>Open insights</a>';
    $('#run-done-bar').hidden = false;
    toast('Analysis complete. Insights are ready.');
    setMode('calm'); burst(innerWidth / 2, innerHeight * 0.45, decisionMix(S.result), 160);
    if (S.health) S.health.saved_run = true;
  } else {
    pill.className = 'status-pill bad'; pill.querySelector('.label').textContent = 'Run failed';
    setMode('calm');
    showRunFailure();
  }
  lockNav();
}

// Failed run: say where and why it stopped, mark that node on the graph, and offer a one-click retry.
function showRunFailure() {
  const order = Object.keys(NODES);
  const err = [...RUN.events].reverse().find((e) => e.type === 'run_error' || e.type === 'stage_error');
  const active = order.filter((id) => RUN.graph.state[id] === 'active');
  const lastDone = [...RUN.events].reverse().find((e) => e.type === 'stage_end')?.stage;
  active.forEach((id) => RUN.graph.set(id, 'failed'));
  const focusNode = active[0] || lastDone;
  if (focusNode) RUN.graph.select(focusNode);
  const last = RUN.events[RUN.events.length - 1];
  if (last?.t) $('#st-time').textContent = clock(last.t);
  const names = (ids) => new Intl.ListFormat('en', { type: 'conjunction' }).format(ids.map((id) => NODES[id].name));
  const where = active.length ? `at ${names(active)}` : lastDone ? `after ${NODES[lastDone].name}` : 'before any agent finished';
  const why = err?.message ? ` ${esc(String(err.message).split('\n')[0].slice(0, 140).replace(/\.$/, ''))}.` : '';
  $('#run-done-info').innerHTML = `<b>Run stopped ${esc(where)}.</b>${why} ${RUN.stats.stages} of 10 stages finished. Your data and settings are kept.`;
  const actions = $('#run-done-actions');
  actions.innerHTML = '';
  actions.append(
    h('a', { class: 'btn lg', href: '#/configure' }, icon('sliders'), 'Adjust settings'),
    h('button', { class: 'btn primary lg', type: 'button', id: 'btn-retry', 'aria-describedby': 'run-done-info', onclick: () => startRun() }, icon('refresh'), 'Retry run'));
  $('#run-done-bar').hidden = false;
  toast(`Run stopped ${active.length > 1 ? `with ${active.length} agents mid-task` : where}. Retry, or adjust settings first.`, 'err');
  $('#btn-retry').focus({ preventScroll: true });
}

async function loadSaved(toRun = false) {
  try {
    S.result = await api('/api/runs/saved/latest');
    lockNav();
    const want = toRun ? '#/run' : '#/insights';
    if (location.hash !== want) location.hash = want; else route();
  } catch (e) { toast('No saved run yet.', 'err'); location.hash = '#/configure'; }
}

/* ================================================================ replay */
function showReplayIdle() {
  if (RUN.replaying) return;
  $('#run-question').innerHTML = `“${esc(S.result.question || S.result.plan?.objective || 'Full vendor portfolio review')}”<span class="replay-tag">Saved run · ${esc(S.result.created || '')}</span>`;
  $('#trace').innerHTML = '';
  $('#trace').append(h('li', { class: 'trace-empty' }, 'This run finished earlier. Press “Replay this run” to watch the agents work through it again at 6× speed.'));
  RUN.graph.reset();
  $('#btn-replay').hidden = false;
}

function replay() {
  const r = S.result;
  if (!r?.events?.length) { toast('This run has no recorded trace.', 'err'); return; }
  RUN.replayTimers?.forEach(clearTimeout);
  S.run = { id: r.run_id, done: false, question: r.question || r.plan?.objective || 'Full vendor portfolio review', replay: true };
  RUN.replaying = true;
  beginRunView(false);
  $('#run-question').innerHTML = `“${esc(S.run.question)}”<span class="replay-tag">Replay · 6×</span>`;
  const speed = 6;
  RUN.t0 = Date.now();
  RUN.timeScale = speed;
  RUN.replayTimers = r.events.map((ev) => setTimeout(() => onEvent(ev), (ev.t * 1000) / speed));
  const end = r.events[r.events.length - 1].t;
  RUN.replayTimers.push(setTimeout(() => { RUN.replaying = false; S.run.done = true; clearInterval(RUN.timer); RUN.timeScale = 1; finishReplay(); }, (end * 1000) / speed + 300));
}

function finishReplay() {
  const u = S.result.usage;
  setMode('calm'); burst(innerWidth / 2, innerHeight * 0.45, decisionMix(S.result), 120);
  $('#st-time').textContent = clock(u.elapsed);
  $('#run-done-info').innerHTML = `<b>Recorded run: ${clock(u.elapsed)}</b> · ${num(u.llm_calls)} model calls across ${Object.keys(u.per_model).length} models · ${num(u.failovers)} automatic failovers`;
  $('#run-done-bar').hidden = false;
  lockNav();
}

/* =============================================================== copilot */
// Minimal, safe markdown: escape first, then bold / italics / bullet lists / line breaks.
function miniMd(text) {
  const lines = esc(String(text || '')).split('\n');
  let out = '', inList = false;
  for (let line of lines) {
    line = line.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|\s)\*(\S.*?)\*(?=\s|$)/g, '$1<i>$2</i>');
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) { if (!inList) { out += '<ul>'; inList = true; } out += `<li>${m[1]}</li>`; continue; }
    if (inList) { out += '</ul>'; inList = false; }
    if (/^\s*\|/.test(line)) { out += `<code class="tbl">${line}</code><br>`; continue; }
    out += line.trim() ? `${line}<br>` : '<br>';
  }
  if (inList) out += '</ul>';
  return out.replace(/(<br>){3,}/g, '<br><br>');
}
const CP = { history: [] };
function initCopilot() {
  const fab = $('#copilot-fab'), panel = $('#copilot');
  fab.addEventListener('click', () => (panel.hidden ? openCopilot() : closeCopilot()));
  $('#copilot-close').addEventListener('click', closeCopilot);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) closeCopilot(); });
  $('#cp-form').addEventListener('submit', (e) => { e.preventDefault(); const v = $('#cp-input').value.trim(); if (v) ask(v); });
}
function openCopilot() {
  const panel = $('#copilot');
  panel.hidden = false; $('#copilot-fab').setAttribute('aria-expanded', 'true');
  if (!$('#cp-log').children.length) {
    const brief = S.result?.brief || {};
    $('#cp-log').append(h('li', { class: 'a' }, `I have this run's full scorecard, decisions and plans. ${brief.headline ? `Headline: ${brief.headline}` : ''}`));
    const reps = (S.result?.vendors || []).filter((v) => v.decision?.decision === 'Replace').map((v) => short(v.vendor));
    const sugg = [reps[0] ? `Why replace ${reps[0]}?` : 'Which vendor is riskiest?', 'What if delivery weight is 50%?', 'Who can absorb Steel volume?', 'Summarise savings in one line'];
    const box = $('#cp-suggest'); box.innerHTML = '';
    sugg.forEach((s) => box.append(h('button', { type: 'button', onclick: () => ask(s) }, s)));
  }
  $('#cp-input').focus();
  $('#copilot-fab').hidden = true; // hide only after focus has moved, so focus never lands on a hidden control
}
function closeCopilot() {
  const panel = $('#copilot');
  if (panel.hidden) return;
  panel.hidden = true; $('#copilot-fab').setAttribute('aria-expanded', 'false');
  $('#copilot-fab').hidden = !(S.route === 'insights' && S.result);
  $('#copilot-fab').focus();
}
async function ask(text) {
  const log = $('#cp-log');
  log.append(h('li', { class: 'u' }, text));
  $('#cp-input').value = '';
  const typing = h('li', { class: 'a typing', 'aria-label': 'Copilot is thinking' }, h('i'), h('i'), h('i'));
  log.append(typing); log.scrollTop = log.scrollHeight;
  try {
    const r = await api(`/api/runs/${S.result.run_id}/chat`, { method: 'POST', body: { message: text, history: CP.history } });
    typing.remove();
    const via = [r.models?.length ? `via ${r.models.join(', ')}` : '', r.tools?.length ? `tools: ${[...new Set(r.tools)].join(', ')}` : '',
      r.corrections?.length ? `data check corrected ${r.corrections.length} claim${r.corrections.length > 1 ? 's' : ''}` : '', `${r.seconds}s`].filter(Boolean).join(' · ');
    const li = h('li', { class: 'a md', html: miniMd(r.answer) });
    li.append(h('span', { class: 'via' }, via));
    log.append(li);
    CP.history.push({ role: 'user', content: text }, { role: 'assistant', content: r.answer });
  } catch (e) {
    typing.remove();
    log.append(h('li', { class: 'a' }, `I could not answer that: ${e.message}`));
  }
  log.scrollTop = log.scrollHeight;
}

/* ================================================================== boot */
function initHero() {
  const hr = new Date().getHours();
  const shift = hr < 5 ? 'Night watch' : hr < 12 ? 'Morning shift' : hr < 17 ? 'Afternoon shift' : hr < 21 ? 'Evening shift' : 'Night watch';
  $('#kicker').innerHTML = `${shift}<span class="kx"> · procurement observatory</span> · ${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`;
  // Decorative crew ring: the ten agents waiting around the shield.
  const ring = $('#crew-ring');
  const ids = Object.keys(NODES);
  const pts = ids.map((id, i) => { const a = (i / ids.length) * Math.PI * 2 - Math.PI / 2; return [Math.cos(a) * 92, Math.sin(a) * 92]; });
  ring.innerHTML = `<defs><radialGradient id="cr-g"><stop offset="0" stop-color="var(--brand)" stop-opacity=".35"/><stop offset="1" stop-color="var(--brand)" stop-opacity="0"/></radialGradient></defs>
    <circle r="116" fill="url(#cr-g)"/><circle r="92" class="cr-orbit"/><circle r="60" class="cr-orbit in"/>
    <g class="cr-spin">${pts.map(([x, y], i) => `<line x1="0" y1="0" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" class="cr-link" style="--i:${i}"/>`).join('')}
    ${pts.map(([x, y], i) => `<g class="cr-node" style="--i:${i}" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})"><circle r="13"/><text y="4" text-anchor="middle">${i + 1}</text></g>`).join('')}</g>
    <path class="cr-shield" d="M0 -30 22 -22v17c0 14-9 24-22 28-13-4-22-14-22-28v-17Z"/><path class="cr-tick" d="m-9 0 6 6 12-13"/>`;
}

function commands() {
  const haveRun = !!(S.result || S.health?.saved_run);
  const tabs = TAB_LIST.map(([id, label]) => ({ group: 'Insights', label, icon: 'chart', hidden: !haveRun, run: () => { selectTab(id); if (S.route !== 'insights') location.hash = '#/insights'; } }));
  const vend = (S.result?.vendors || []).map((v) => ({ group: 'Vendors', label: short(v.vendor), sub: `${v.decision?.decision || 'out of scope'} · ${v.category} · risk ${Math.round(v.combined_risk)}`, icon: 'flag',
    run: () => { if (S.route !== 'insights') { location.hash = '#/insights'; setTimeout(() => openVendor(v.vendor), 500); } else openVendor(v.vendor); } }));
  return [
    { group: 'Go to', label: 'Configure', sub: 'Data, question, weights', icon: 'sliders', run: () => { location.hash = '#/configure'; } },
    { group: 'Go to', label: 'Agents', sub: 'Live workflow graph', icon: 'network', hidden: $('[data-nav="run"]').classList.contains('locked'), run: () => { location.hash = '#/run'; } },
    { group: 'Go to', label: 'Insights', sub: 'Brief and nine views', icon: 'chart', hidden: $('[data-nav="insights"]').classList.contains('locked'), run: () => { location.hash = '#/insights'; } },
    { group: 'Actions', label: 'Run the 10-agent analysis', icon: 'play', hidden: $('#btn-run').disabled, run: () => startRun() },
    { group: 'Actions', label: 'Replay the saved run at 6×', icon: 'history', hidden: !haveRun, run: async () => { if (!S.result) await loadSaved(true); else location.hash = '#/run'; setTimeout(replay, 500); } },
    { group: 'Actions', label: 'Ask the copilot', icon: 'spark', hidden: !S.result, run: () => { if (S.route !== 'insights') { location.hash = '#/insights'; setTimeout(openCopilot, 500); } else openCopilot(); } },
    { group: 'Actions', label: 'Generate a new sample dataset', icon: 'refresh', run: () => { location.hash = '#/configure'; generate(); } },
    { group: 'Actions', label: 'Switch colour theme', icon: 'moon', run: () => $('#theme-toggle').click() },
    { group: 'Actions', label: 'Download executive report', icon: 'download', hidden: !S.result, run: () => { location.href = `/api/runs/${S.result.run_id}/report`; } },
    ...tabs, ...vend,
  ];
}

async function boot() {
  initFx();
  initHero();
  initPalette(commands);
  addEventListener('resize', debounce(moveNavIndicator, 100));
  document.fonts?.ready.then(moveNavIndicator);
  document.addEventListener('sp-egg', () => toast('Observatory mode: every decision colour at once.'));
  initTheme();
  RUN.graph = new FlowGraph($('#flow-graph'), (id) => inspect(id));
  RUN.graph.buildList($('#flow-list'));
  initConfigure();
  initCopilot();
  window.addEventListener('hashchange', route);
  renderGenCats(); // default categories first, so the panel does not grow when health arrives
  $('.cfg-grid').classList.add('ready');
  await loadHealth();
  renderGenCats();
  await generate();
  route();
  S.booted = true;
  renderLanes();
}

boot();
onEcharts(() => renderMiniChart());
export { RUN };
