// Insights: nine views over one finished run.
import { $, $$, h, icon, esc, inr, pct, num, short, css, riskColor, sparkline, api, debounce, setRangeFill, DECISIONS, decisionVar, store, tierChip, onEcharts } from './ui.js';
import { decisionOrbit } from './orbit.js';

const TABS = [
  ['brief', 'Brief'], ['vendors', 'Vendors'], ['risk', 'Risk map'], ['spend', 'Spend'], ['forecast', 'Forecast'],
  ['market', 'Market intel'], ['plan', 'Mitigation'], ['whatif', 'What-if'], ['audit', 'Audit trail'],
];
export const TAB_LIST = TABS;
// Tab changes slide in the direction of travel (View Transitions; instant under reduced motion).
export function selectTab(id) {
  if (!R) { tab = id; store.set('sp-tab', id); return; }
  const from = TABS.findIndex(([t]) => t === tab), to = TABS.findIndex(([t]) => t === id);
  if (from === to) return;
  if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) { select(id); return; }
  document.documentElement.dataset.vt = 'tab';
  document.documentElement.style.setProperty('--tdir', to > from ? '1' : '-1');
  const t = document.startViewTransition(() => select(id));
  t.ready.catch(() => {});
  t.finished.catch(() => {}).finally(() => { delete document.documentElement.dataset.vt; });
}
const PILLAR_LABEL = { delivery: 'Delivery', quality: 'Quality', cost: 'Cost', responsiveness: 'Responsiveness', compliance: 'Compliance' };
const CAT_SHORT = { 'Steel & Metals': 'Steel', 'Packaging': 'Packaging', 'Electronic Components': 'Electronics', 'Logistics & Freight': 'Logistics', 'Chemicals & Plastics': 'Chemicals' };

let R = null;          // current result
let tab = store.get('sp-tab', 'brief');
let charts = [];       // [{node, build}]
let vSort = { key: 'combined_risk', dir: -1 };
let vFilter = { q: '', cat: '', dec: '' };

/* ------------------------------------------------------------- charts */
function theme() {
  const c = (n) => css(n);
  return {
    ink: c('--ink'), ink2: c('--ink-2'), ink3: c('--ink-3'), line: c('--line'), line2: c('--line-2'), surface: c('--surface'), surface3: c('--surface-3'),
    brand: c('--brand'), keep: c('--keep'), watch: c('--watch'), develop: c('--develop'), replace: c('--replace'),
    risk: [c('--risk-0'), c('--risk-1'), c('--risk-2'), c('--risk-3'), c('--risk-4')],
  };
}
const base = (t) => ({
  textStyle: { fontFamily: 'Geist, system-ui, sans-serif', color: t.ink2 },
  animationDuration: 700, animationEasing: 'cubicOut',
  tooltip: { backgroundColor: t.surface, borderColor: t.line2, borderWidth: 1, textStyle: { color: t.ink, fontSize: 12.5 }, extraCssText: 'box-shadow:0 8px 28px rgba(0,0,0,.12);border-radius:10px;' },
});
const axis = (t, extra = {}) => ({ axisLine: { lineStyle: { color: t.line2 } }, axisTick: { show: false }, axisLabel: { color: t.ink3, fontSize: 11, fontFamily: 'Geist Mono' }, splitLine: { lineStyle: { color: t.line, type: [3, 4] } }, nameTextStyle: { color: t.ink3, fontSize: 11 }, ...extra });

function chart(node, build) {
  if (!node) return;
  if (!window.echarts) { onEcharts(() => { if (document.body.contains(node)) chart(node, build); }); return; }
  const inst = echarts.getInstanceByDom(node) || echarts.init(node, null, { renderer: 'canvas' });
  inst.setOption(build(theme()), true);
  charts.push({ node, build });
  return inst;
}
export function rerenderCharts() {
  charts = charts.filter((c) => document.body.contains(c.node));
  charts.forEach((c) => echarts.getInstanceByDom(c.node)?.setOption(c.build(theme()), true));
}
window.addEventListener('resize', debounce(() => charts.forEach((c) => echarts.getInstanceByDom(c.node)?.resize()), 120));

/* ---------------------------------------------------------- utilities */
const dec = (v) => v.decision?.decision || '—';
const decChip = (d, src) => h('span', { class: `decision ${d}` }, d, src === 'rule' ? h('span', { class: 'src-tag' }, 'rule') : null);
const scope = () => R.vendors.filter((v) => v.in_scope);
function counts() {
  const c = { Keep: 0, Watch: 0, Develop: 0, Replace: 0 };
  scope().forEach((v) => { if (c[dec(v)] != null) c[dec(v)] += 1; });
  return c;
}
function panel(title, meta, ...body) {
  return h('section', { class: 'panel' }, h('div', { class: 'panel-head' }, h('h2', {}, title), meta ? h('span', { class: 'meta' }, meta) : null), ...body);
}

/* ============================================================== render */
export function renderInsights(result) {
  if (!result) return;
  const fresh = R !== result;
  R = result;
  const tabs = $('#ins-tabs');
  if (fresh || !tabs.children.length) {
    tabs.innerHTML = '';
    const c = counts();
    const badge = { vendors: scope().length, plan: (R.mitigation?.plans || []).length, market: (R.market?.signals || []).length };
    TABS.forEach(([id, label], i) => {
      const b = h('button', { role: 'tab', id: `tab-${id}`, 'aria-controls': 'ins-body', 'aria-selected': id === tab, tabindex: id === tab ? 0 : -1 }, label, badge[id] != null ? h('span', { class: 'n' }, badge[id]) : null);
      b.addEventListener('click', () => selectTab(id));
      b.addEventListener('keydown', (e) => {
        if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
        e.preventDefault();
        const n = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
        selectTab(TABS[n][0]); $(`#tab-${TABS[n][0]}`).focus();
      });
      tabs.append(b);
    });
    void c;
    $('#dl-report').href = `/api/runs/${R.run_id}/report`;
    $('#dl-csv').href = `/api/runs/${R.run_id}/csv`;
  }
  select(tab, true);
}

// Narrow screens scroll the tab strip: fade the clipped edge(s) and keep the active tab in view.
function syncTabFade() {
  const t = $('#ins-tabs');
  t.classList.toggle('more-r', t.scrollLeft + t.clientWidth < t.scrollWidth - 2);
  t.classList.toggle('more-l', t.scrollLeft > 2);
}
function revealTab(id) {
  const t = $('#ins-tabs'), a = $(`#tab-${id}`);
  if (!t.dataset.fade) { t.addEventListener('scroll', syncTabFade, { passive: true }); addEventListener('resize', syncTabFade); t.dataset.fade = '1'; }
  if (a) {
    const tr = t.getBoundingClientRect(), ar = a.getBoundingClientRect();
    if (ar.left < tr.left + 24) t.scrollLeft -= tr.left - ar.left + 32;
    else if (ar.right > tr.right - 24) t.scrollLeft += ar.right - tr.right + 32;
  }
  syncTabFade();
}

function select(id, initial = false) {
  tab = id; store.set('sp-tab', id);
  $$('#ins-tabs [role="tab"]').forEach((b) => { const on = b.id === `tab-${id}`; b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1; });
  revealTab(id);
  const body = $('#ins-body');
  body.setAttribute('role', 'tabpanel'); body.setAttribute('aria-labelledby', `tab-${id}`);
  charts.forEach((c) => echarts.getInstanceByDom(c.node)?.dispose());
  charts = [];
  body.innerHTML = '';
  const wrap = h('div', { class: 'tab-body' });
  body.append(wrap);
  ({ brief, vendors, risk, spend, forecast, market, plan, whatif, audit })[id](wrap);
  if (!initial) window.scrollTo({ top: 0 });
}

/* ================================================================ BRIEF */
function brief(root) {
  const b = R.brief || {}, qa = R.qa || {}, c = counts();
  const total = Object.values(c).reduce((a, x) => a + x, 0) || 1;
  const main = h('article', { class: 'panel brief-main' },
    h('p', { class: 'brief-q' }, 'Asked', h('span', {}, `“${R.question || R.plan?.objective || 'Full vendor portfolio review'}”`)),
    h('h2', { class: 'headline' }, b.headline || 'Vendor portfolio review'),
    b.answer ? h('p', { class: 'answer' }, b.answer) : null,
    (b.summary || []).map((p) => h('p', { class: 'para' }, p)),
    h('dl', { class: 'facts' }, (b.key_numbers || []).slice(0, 6).map((k) => h('div', {}, h('dt', {}, k.label), h('dd', { class: String(k.value).length > 12 ? 'long' : '' }, k.value)))));

  const cnt = (st) => (qa.checks || []).filter((x) => x.status === st).length;
  const verified = cnt('verified'), corrected = cnt('corrected'), unsupported = cnt('unsupported');
  const seal = h('div', { class: `qa-seal ${qa.verdict === 'revise' ? 'revise' : ''}` }, icon('shield'),
    h('div', {}, h('b', {}, qa.verdict === 'approve' || !qa.verdict ? 'Approved by independent QA' : 'Published after QA revision'),
      h('span', {}, `${(qa.checks || []).length} claims re-checked against the data: ${verified} verified, ${corrected} corrected, ${unsupported} unsupported · ${R.revisions ? `${R.revisions} revision round` : 'no revision needed'}`)));

  const dist = h('div', { class: 'dist', role: 'img', 'aria-label': DECISIONS.map((d) => `${d}: ${c[d]}`).join(', ') },
    DECISIONS.filter((d) => c[d]).map((d) => h('span', { class: `bg-${d.toLowerCase()}`, style: { flexGrow: c[d] }, title: `${d}: ${c[d]}` }, c[d])));
  const legend = h('div', { class: 'legend' }, DECISIONS.map((d) => h('span', {}, h('i', { class: `bg-${d.toLowerCase()}` }), `${d} ${c[d]}`)));

  const acts = h('ol', { class: 'actions-list' }, (b.top_actions || []).map((a, i) => h('li', {}, h('span', { class: 'n' }, String(i + 1).padStart(2, '0')),
    h('div', {}, h('b', {}, a.action), h('div', { class: 'sub' }, h('span', {}, a.owner), h('span', {}, a.timeline), h('span', {}, a.impact))))));

  const watchlist = scope().filter((v) => ['Replace', 'Watch'].includes(dec(v))).sort((a, b2) => b2.combined_risk - a.combined_risk).slice(0, 6);
  const wl = h('ul', { class: 'checks' }, watchlist.map((v) => h('li', { class: `${dec(v) === 'Replace' ? 'unsupported' : 'corrected'} as-btn` },
    h('button', { type: 'button', class: 'row-btn', onclick: () => openVendor(v.vendor), 'aria-label': `${v.vendor}, ${dec(v)}. Open dossier` },
      icon(dec(v) === 'Replace' ? 'alert' : 'flag'), h('div', {}, h('b', {}, short(v.vendor)), ' ', decChip(dec(v), v.decision?.source), h('span', { class: 'note' }, v.decision?.rationale || ''))))));

  root.append(h('div', { class: 'brief' },
    h('div', { class: 'stack' }, main,
      panel('Needs attention', 'Select a vendor for the full dossier', wl.children.length ? wl : h('p', { class: 'meta' }, 'No vendors flagged.'))),
    h('div', { class: 'stack' },
      seal,
      panel('Decisions', `${total} vendors · drag the orbit, select a star`, decisionOrbit(R, scope(), openVendor), dist, legend),
      panel('Priority actions', null, acts.children.length ? acts : h('p', { class: 'meta' }, 'No actions returned.')))));
}

/* ============================================================== VENDORS */
function vendors(root) {
  const cats = [...new Set(R.vendors.map((v) => v.category))].sort();
  const search = h('input', { type: 'search', placeholder: 'Search vendors', value: vFilter.q, 'aria-label': 'Search vendors' });
  const catSel = h('select', { 'aria-label': 'Filter by category' }, h('option', { value: '' }, 'All categories'), cats.map((c) => h('option', { value: c, selected: vFilter.cat === c }, c)));
  const decSel = h('select', { 'aria-label': 'Filter by decision' }, h('option', { value: '' }, 'All decisions'), DECISIONS.map((d) => h('option', { value: d, selected: vFilter.dec === d }, d)));
  const count = h('span', { class: 'meta' });
  const tbody = h('tbody');
  const cols = [
    ['rank', 'Rank'], ['vendor', 'Vendor'], ['composite', 'Score'], ['combined_risk', 'Risk'], ['otd', 'On-time 12m'],
    ['defect', 'Defect %'], ['pv', 'Price var.'], ['spend_total', 'Spend'], ['decision', 'Decision'],
  ];
  const thead = h('thead', {}, h('tr', {}, cols.map(([k, l]) => {
    const th = h('th', { scope: 'col', class: `c-${k}`, 'aria-sort': vSort.key === k ? (vSort.dir > 0 ? 'ascending' : 'descending') : null }, h('button', { type: 'button' }, l, vSort.key === k ? icon(vSort.dir > 0 ? 'arrow-up' : 'arrow-down', 'sm') : null));
    th.querySelector('button').addEventListener('click', () => { vSort = { key: k, dir: vSort.key === k ? -vSort.dir : (k === 'vendor' || k === 'rank' ? 1 : -1) }; root.innerHTML = ''; vendors(root); });
    return th;
  })));
  const val = (v, k) => ({ rank: v.rank, vendor: v.vendor, composite: v.composite, combined_risk: v.combined_risk, otd: v.kpis.on_time_pct, defect: v.kpis.defect_rate_pct, pv: v.kpis.price_variance_pct, spend_total: v.spend_total, decision: DECISIONS.indexOf(dec(v)) }[k]);
  const draw = () => {
    const q = vFilter.q.toLowerCase();
    const rows = R.vendors.filter((v) => (!q || v.vendor.toLowerCase().includes(q) || v.category.toLowerCase().includes(q)) && (!vFilter.cat || v.category === vFilter.cat) && (!vFilter.dec || dec(v) === vFilter.dec))
      .sort((a, b) => { const x = val(a, vSort.key), y = val(b, vSort.key); return (x > y ? 1 : x < y ? -1 : 0) * vSort.dir; });
    tbody.innerHTML = '';
    count.textContent = `${rows.length} of ${R.vendors.length} vendors`;
    if (!rows.length) { tbody.append(h('tr', {}, h('td', { colspan: cols.length }, h('div', { class: 'empty' }, h('b', {}, 'No vendors match'), 'Clear a filter to see more.')))); return; }
    rows.forEach((v) => {
      const tr = h('tr', { tabindex: 0, 'aria-label': `${v.vendor}, ${dec(v)}` },
        h('td', { class: 'n c-rank' }, v.rank),
        h('td', { class: 'vn c-vendor' }, h('b', {}, short(v.vendor)), h('span', {}, `${v.category} · ${v.region.split(',')[0]}`)),
        h('td', { class: 'c-composite', 'data-label': 'Score' }, h('div', { class: 'scorebar' }, h('span', { class: 'num' }, v.composite.toFixed(1)), h('span', { class: 'b' }, h('i', { style: { width: `${v.composite}%` } })), tierChip(v.tier))),
        h('td', { class: 'n c-combined_risk', 'data-label': 'Risk' }, h('span', { class: 'riskdot', style: { '--rc': riskColor(v.combined_risk) } }, v.combined_risk.toFixed(0))),
        h('td', { class: 'c-otd', 'data-label': 'On-time', html: `<span class="otd">${sparkline(v.otd_series)}<span class="num">${v.kpis.on_time_pct.toFixed(1)}</span></span>` }),
        h('td', { class: 'n c-defect' }, v.kpis.defect_rate_pct.toFixed(2)),
        h('td', { class: `n c-pv ${v.kpis.price_variance_pct > 2 ? 'delta-down' : v.kpis.price_variance_pct < 0 ? 'delta-up' : ''}` }, `${v.kpis.price_variance_pct > 0 ? '+' : ''}${v.kpis.price_variance_pct.toFixed(1)}%`),
        h('td', { class: 'n c-spend_total' }, inr(v.spend_total)),
        h('td', { class: 'c-decision' }, v.decision ? decChip(dec(v), v.decision.source) : h('span', { class: 'meta' }, 'out of scope')));
      tr.addEventListener('click', () => openVendor(v.vendor));
      // preventDefault: otherwise the same Enter activates the dossier's Close button once focus moves there.
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openVendor(v.vendor); } });
      tbody.append(tr);
    });
  };
  search.addEventListener('input', debounce(() => { vFilter.q = search.value; draw(); }, 120));
  catSel.addEventListener('change', () => { vFilter.cat = catSel.value; draw(); });
  decSel.addEventListener('change', () => { vFilter.dec = decSel.value; draw(); });
  root.append(h('section', { class: 'panel' },
    h('div', { class: 'toolbar' }, h('label', { class: 'search' }, icon('search'), search), catSel, decSel, count),
    h('div', { class: 'vt-wrap vlist-wrap' }, h('table', { class: 'vt vlist' }, thead, tbody))));
  draw();
}

/* ============================================================ VENDOR DRAWER */
export function openVendor(name) {
  const v = R.vendors.find((x) => x.vendor === name);
  if (!v) return;
  const drawer = $('#drawer'), scrim = $('#scrim'), inner = $('#drawer-inner');
  const last = document.activeElement;
  inner.innerHTML = '';
  const close = () => { drawer.hidden = true; scrim.hidden = true; document.removeEventListener('keydown', onKey); last?.focus?.(); };
  const onKey = (e) => {
    if (e.key === 'Escape') close();
    if (e.key === 'Tab') {
      const f = $$('button, a[href], input, select, [tabindex="0"]', drawer).filter((x) => !x.disabled && x.offsetParent);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  const closeBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close vendor details', onclick: close }, icon('x'));
  const d = v.decision;
  const plan = (R.mitigation?.plans || []).find((p) => p.vendor === v.vendor);
  const sig = (R.market?.signals || []).find((s) => s.category === v.category);
  inner.append(
    h('div', { class: 'dw-head' }, h('div', {}, h('h2', { id: 'drawer-title' }, short(v.vendor)), h('p', {}, `${v.category} · ${v.region} · rank ${v.rank} of ${R.vendors.length} · ${inr(v.spend_total)} spend`)), closeBtn),
    h('div', { class: 'kv', role: 'list', 'aria-label': 'Vendor summary' }, d ? decChip(d.decision, d.source) : null, tierChip(v.tier), h('span', { class: 'tag' }, `Score ${v.composite.toFixed(1)}`),
      h('span', { class: 'tag' }, `Internal risk ${v.internal_risk.toFixed(0)}`), h('span', { class: 'tag' }, `Market risk ${v.market_risk.toFixed(0)}`), h('span', { class: 'tag brand' }, `Combined ${v.combined_risk.toFixed(0)}`)),
    d ? h('div', { class: 'dw-sec' }, h('h3', {}, `Strategist's call · confidence ${Math.round(d.confidence * 100)}%`), h('p', { class: 'rationale' }, d.rationale), d.actions?.length ? h('ul', {}, d.actions.map((a) => h('li', {}, a))) : null) : null,
    h('div', { class: 'dw-sec' }, h('h3', {}, 'On-time delivery: 12 months and 3-month forecast'), h('div', { class: 'chart short', id: 'dw-chart', role: 'img', 'aria-label': `On-time delivery history and forecast for ${v.vendor}` })),
    h('div', { class: 'dw-sec' }, h('h3', {}, 'Pillar scores'), h('div', { class: 'pillars' }, Object.entries(v.pillars).map(([k, s]) => h('div', { class: 'pillar' }, h('span', {}, PILLAR_LABEL[k]), h('span', { class: 'b' }, h('i', { style: { width: `${s}%`, background: s >= 75 ? 'var(--keep)' : s >= 55 ? 'var(--develop)' : s >= 40 ? 'var(--watch)' : 'var(--replace)' } })), h('span', { class: 'v' }, s.toFixed(0)))))),
    h('div', { class: 'dw-sec' }, h('h3', {}, 'Key performance indicators (last 6 months, spend-weighted)'), h('dl', { class: 'kpis' },
      [['On-time', pct(v.kpis.on_time_pct)], ['Fill rate', pct(v.kpis.fill_rate_pct)], ['Defects', pct(v.kpis.defect_rate_pct, 2)], ['Lead time', `${v.kpis.lead_time_days.toFixed(1)} d`],
        ['Price variance', `${v.kpis.price_variance_pct > 0 ? '+' : ''}${v.kpis.price_variance_pct.toFixed(1)}%`], ['Response', `${v.kpis.response_time_hrs.toFixed(0)} h`],
        ['Capacity used', pct(v.kpis.capacity_utilization_pct, 0)], ['OTD trend', `${v.kpis.otd_trend > 0 ? '+' : ''}${v.kpis.otd_trend.toFixed(2)}/mo`], ['Compliance', `${v.compliance_incidents} incidents`]]
        .map(([k, x]) => h('div', {}, h('dt', {}, k), h('dd', {}, x))))),
    plan ? h('div', { class: 'dw-sec' }, h('h3', {}, 'Mitigation plan'), planCard(plan, true)) : null,
    sig ? h('div', { class: 'dw-sec' }, h('h3', {}, `Market signal: ${v.category}`), signalCard(sig)) : null,
  );
  drawer.hidden = false; scrim.hidden = false;
  scrim.onclick = close;
  document.addEventListener('keydown', onKey);
  $$('.kv[role=list] > *', inner).forEach((c) => c.setAttribute('role', 'listitem'));
  closeBtn.focus();
  const f = v.forecast;
  if (f) {
    chart($('#dw-chart'), (t) => forecastOption(t, f, 'otd', 'On-time %', R.config?.otd_floor));
  }
}

function forecastOption(t, f, key, label, threshold) {
  const months = [...f.history_months, ...f.future_months];
  const hist = [...f[key].history, ...f.future_months.map(() => null)];
  const fc = [...f.history_months.map((_, i) => (i === f.history_months.length - 1 ? f[key].history[i] : null)), ...f[key].forecast];
  const lo = [...f.history_months.map(() => null), ...f[key].lower];
  const band = [...f.history_months.map(() => null), ...f[key].upper.map((u, i) => u - f[key].lower[i])];
  return {
    ...base(t), grid: { left: 40, right: 64, top: 18, bottom: 28 },
    tooltip: { ...base(t).tooltip, trigger: 'axis', valueFormatter: (x) => (x == null ? '—' : Number(x).toFixed(1)) },
    xAxis: { type: 'category', data: months, ...axis(t), axisLabel: { ...axis(t).axisLabel, interval: 2 } },
    yAxis: { type: 'value', scale: true, ...axis(t) },
    series: [
      { name: 'band', type: 'line', data: lo, stack: 'b', lineStyle: { opacity: 0 }, symbol: 'none', tooltip: { show: false } },
      { name: '80% band', type: 'line', data: band, stack: 'b', lineStyle: { opacity: 0 }, symbol: 'none', areaStyle: { color: t.brand, opacity: 0.12 }, tooltip: { show: false } },
      { name: label, type: 'line', data: hist, symbol: 'circle', symbolSize: 5, lineStyle: { color: t.ink, width: 2 }, itemStyle: { color: t.ink } },
      { name: 'Forecast', type: 'line', data: fc, symbol: 'circle', symbolSize: 5, lineStyle: { color: t.brand, width: 2, type: [6, 4] }, itemStyle: { color: t.brand },
        markLine: threshold ? { symbol: 'none', label: { formatter: key === 'otd' ? `floor ${threshold}%` : `ceiling ${threshold}%`, color: t.replace, fontSize: 10 }, lineStyle: { color: t.replace, type: [4, 4] }, data: [{ yAxis: threshold }] } : undefined },
    ],
  };
}

/* ================================================================= RISK */
function risk(root) {
  const th = R.config?.risk_threshold ?? 55;
  const sc = h('div', { class: 'chart tall', role: 'img', 'aria-label': 'Risk matrix: internal risk versus market risk, bubble size is spend' });
  const hm = h('div', { class: 'chart tall', role: 'img', 'aria-label': 'Heatmap of pillar scores by vendor' });
  root.append(h('div', { class: 'grid-2' },
    panel('Risk matrix', `Bubble = spend · dashed line = tolerance ${th}`, sc),
    panel('Pillar heatmap', 'Score 0–100 by pillar, sorted by risk', hm)));
  const vs = scope();
  chart(sc, (t) => ({
    ...base(t), grid: { left: 48, right: 24, top: 24, bottom: 44 },
    tooltip: { ...base(t).tooltip, formatter: (p) => `<b>${esc(short(p.data.v.vendor))}</b><br>${esc(p.data.v.category)}<br>Internal ${p.data.value[0].toFixed(0)} · Market ${p.data.value[1].toFixed(0)}<br>Combined ${p.data.v.combined_risk.toFixed(0)} · ${dec(p.data.v)}<br>${inr(p.data.v.spend_total)}` },
    xAxis: { name: 'Internal risk (performance)', nameLocation: 'middle', nameGap: 28, min: 0, max: 100, ...axis(t) },
    yAxis: { name: 'Market risk (live news)', nameLocation: 'middle', nameGap: 34, min: 0, max: 100, ...axis(t) },
    series: [{
      type: 'scatter', data: vs.map((v) => ({ value: [v.internal_risk, v.market_risk], v, symbolSize: 10 + Math.sqrt(v.spend_total / 1e5) * 2.4, itemStyle: { color: decisionVarColor(t, dec(v)), opacity: 0.82, borderColor: t.surface, borderWidth: 1.5 } })),
      label: { show: true, formatter: (p) => (p.data.v.combined_risk >= th - 5 ? short(p.data.v.vendor).split(' ')[0] : ''), position: 'right', color: t.ink2, fontSize: 11 },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: t.replace, type: [5, 5] }, label: { color: t.replace, fontSize: 10, formatter: 'tolerance' },
        data: [[{ coord: [Math.min(100, th / 0.65), 0] }, { coord: [Math.max(0, (th - 35) / 0.65), 100] }]] },
    }],
  }));
  const sorted = [...vs].sort((a, b) => b.combined_risk - a.combined_risk);
  const pillars = Object.keys(PILLAR_LABEL);
  chart(hm, (t) => ({
    ...base(t), grid: { left: 150, right: 16, top: 8, bottom: 60 },
    tooltip: { ...base(t).tooltip, formatter: (p) => `${esc(short(sorted[p.value[1]].vendor))}<br>${PILLAR_LABEL[pillars[p.value[0]]]}: <b>${p.value[2].toFixed(0)}</b>` },
    xAxis: { type: 'category', data: pillars.map((p) => PILLAR_LABEL[p]), ...axis(t), axisLabel: { color: t.ink3, fontSize: 11, rotate: 0 }, splitLine: { show: false } },
    yAxis: { type: 'category', data: sorted.map((v) => short(v.vendor)), inverse: true, ...axis(t), axisLabel: { color: t.ink2, fontSize: 11, fontFamily: 'Geist' }, splitLine: { show: false } },
    visualMap: { min: 0, max: 100, show: true, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 140, itemWidth: 10, text: ['100', '0'], textStyle: { color: t.ink3, fontSize: 10 }, inRange: { color: [t.risk[4], t.risk[2], t.risk[0]] } },
    series: [{ type: 'heatmap', data: sorted.flatMap((v, y) => pillars.map((p, x) => [x, y, v.pillars[p]])), itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 }, label: { show: true, color: '#fff', fontSize: 10, fontFamily: 'Geist Mono', formatter: (p) => p.value[2].toFixed(0) } }],
  }));
}
function decisionVarColor(t, d) { return { Keep: t.keep, Watch: t.watch, Develop: t.develop, Replace: t.replace }[d] || t.ink3; }

/* ================================================================ SPEND */
function spend(root) {
  const sp = R.spend;
  const par = h('div', { class: 'chart', role: 'img', 'aria-label': 'Pareto chart of spend by vendor' });
  const conc = h('div', { class: 'chart', role: 'img', 'aria-label': 'Category concentration (HHI)' });
  const trend = h('div', { class: 'chart short', role: 'img', 'aria-label': 'Monthly spend trend' });
  const levers = (R.cost?.savings_levers || []);
  const risks = (R.cost?.concentration_risks || []);
  root.append(
    h('dl', { class: 'facts panel', style: { marginTop: 0, borderTop: '1px solid var(--line)', padding: '6px 20px 14px' } },
      [['Total spend', inr(sp.total_spend)], ['Vendors holding 80% of spend', `${sp.pareto_vendors_80pct} of ${sp.vendor_count}`], ['Overpaid vs contract (6 mo)', inr(sp.overpay_recent_total)],
        ['Annual savings opportunity', inr(sp.savings_opportunity_total)], ['Concentrated categories', String(sp.categories.filter((c) => c.concentration_flag).length)]].map(([k, x]) => h('div', {}, h('dt', {}, k), h('dd', {}, x)))),
    h('div', { class: 'grid-2', style: { marginTop: '16px' } },
      panel('Spend Pareto', 'Bars: spend · line: cumulative share', par),
      panel('Concentration by category', 'HHI above 2,500 = highly concentrated', conc),
      panel('Savings levers', 'Quantified by the Cost & Spend Analyst', levers.length ? h('ol', { class: 'actions-list' }, levers.map((l, i) => h('li', {}, h('span', { class: 'n' }, String(i + 1).padStart(2, '0')),
        h('div', {}, h('b', {}, l.lever), h('div', { class: 'sub' }, h('span', { class: 'num' }, `${inr(l.estimated_annual_value_inr)} / yr`), h('span', {}, (l.categories || []).map((c) => CAT_SHORT[c] || c).join(', '))), h('p', { class: 'meta', style: { marginTop: '4px' } }, l.rationale))))) : h('p', { class: 'meta' }, 'No levers returned.')),
      panel('Concentration risks', null, risks.length ? h('ul', { class: 'checks' }, risks.map((r) => h('li', { class: 'corrected' }, icon('alert'), h('div', {}, h('b', {}, r.headline), h('span', { class: 'note' }, `${short(r.vendor)} · ${r.evidence}`))))) : h('p', { class: 'meta' }, 'None flagged.')),
      h('div', { class: 'span-2' }, panel('Monthly spend', null, trend))));
  const vs = sp.vendors.slice(0, 20);
  chart(par, (t) => ({
    ...base(t), grid: { left: 54, right: 44, top: 20, bottom: 86 },
    tooltip: { ...base(t).tooltip, trigger: 'axis' },
    xAxis: { type: 'category', data: vs.map((v) => short(v.vendor_name)), ...axis(t), axisLabel: { color: t.ink3, fontSize: 10, rotate: 45, fontFamily: 'Geist' } },
    yAxis: [{ type: 'value', ...axis(t), axisLabel: { ...axis(t).axisLabel, formatter: (x) => inr(x).replace('₹', '') } }, { type: 'value', max: 100, ...axis(t), splitLine: { show: false }, axisLabel: { ...axis(t).axisLabel, formatter: '{value}%' } }],
    series: [
      { type: 'bar', name: 'Spend', data: vs.map((v) => v.spend_total), itemStyle: { color: t.brand, borderRadius: [4, 4, 0, 0] }, tooltip: { valueFormatter: inr } },
      { type: 'line', name: 'Cumulative', yAxisIndex: 1, data: vs.map((v) => +(v.cum_share * 100).toFixed(1)), symbol: 'circle', symbolSize: 5, lineStyle: { color: t.watch, width: 2 }, itemStyle: { color: t.watch }, tooltip: { valueFormatter: (x) => `${x}%` },
        markLine: { symbol: 'none', silent: true, lineStyle: { color: t.ink3, type: [4, 4] }, label: { formatter: '80%', color: t.ink3, fontSize: 10 }, data: [{ yAxis: 80 }] } },
    ],
  }));
  chart(conc, (t) => ({
    ...base(t), grid: { left: 110, right: 30, top: 10, bottom: 30 },
    tooltip: { ...base(t).tooltip, formatter: (p) => { const c = sp.categories[p.dataIndex]; return `<b>${esc(c.category)}</b><br>HHI ${c.hhi}<br>Top: ${esc(short(c.top_vendor))} (${Math.round(c.top_share * 100)}%)`; } },
    xAxis: { type: 'value', ...axis(t), max: 10000 },
    yAxis: { type: 'category', data: sp.categories.map((c) => CAT_SHORT[c.category] || c.category), inverse: true, ...axis(t), axisLabel: { color: t.ink2, fontSize: 12, fontFamily: 'Geist' } },
    series: [{ type: 'bar', data: sp.categories.map((c) => ({ value: c.hhi, itemStyle: { color: c.hhi > 2500 ? t.replace : t.develop, borderRadius: [0, 4, 4, 0] } })), barWidth: 18,
      label: { show: true, position: 'right', color: t.ink2, fontFamily: 'Geist Mono', fontSize: 11 },
      markLine: { symbol: 'none', silent: true, lineStyle: { color: t.ink3, type: [4, 4] }, label: { formatter: '2,500', color: t.ink3, fontSize: 10 }, data: [{ xAxis: 2500 }] } }],
  }));
  chart(trend, (t) => ({
    ...base(t), grid: { left: 54, right: 16, top: 16, bottom: 28 },
    tooltip: { ...base(t).tooltip, trigger: 'axis', valueFormatter: inr },
    xAxis: { type: 'category', data: sp.monthly.months, ...axis(t) },
    yAxis: { type: 'value', ...axis(t), axisLabel: { ...axis(t).axisLabel, formatter: (x) => inr(x).replace('₹', '') } },
    series: [{ type: 'line', data: sp.monthly.spend, smooth: 0.3, symbol: 'none', lineStyle: { color: t.brand, width: 2 }, areaStyle: { color: t.brand, opacity: 0.08 } }],
  }));
}

/* ============================================================= FORECAST */
function forecast(root) {
  const fcs = R.vendors.filter((v) => v.forecast && v.in_scope);
  const warn = R.forecast?.early_warnings || [];
  const ranked = [...fcs].sort((a, b) => (b.forecast.otd_breach - a.forecast.otd_breach) || (a.forecast.otd.slope_per_month - b.forecast.otd.slope_per_month));
  let current = ranked[0]?.vendor;
  let metric = 'otd';
  const sel = h('select', { 'aria-label': 'Vendor to forecast' }, ranked.map((v) => h('option', { value: v.vendor }, `${short(v.vendor)}${v.forecast.otd_breach || v.forecast.defect_breach ? ' · breach' : ''}`)));
  const seg = h('div', { class: 'seg', role: 'tablist', 'aria-label': 'Metric' },
    h('button', { role: 'tab', 'aria-selected': true, 'data-m': 'otd' }, 'On-time %'), h('button', { role: 'tab', 'aria-selected': false, 'data-m': 'defect' }, 'Defect %'));
  const node = h('div', { class: 'chart tall', role: 'img', 'aria-label': 'Forecast chart' });
  const draw = () => {
    const v = R.vendors.find((x) => x.vendor === current);
    if (!v) return;
    const inst = window.echarts?.getInstanceByDom(node);
    const build = (t) => forecastOption(t, v.forecast, metric, metric === 'otd' ? 'On-time %' : 'Defect %', metric === 'otd' ? R.config?.otd_floor : R.config?.defect_ceiling);
    if (inst) { inst.setOption(build(theme()), true); charts = charts.filter((c) => c.node !== node); charts.push({ node, build }); }
    else chart(node, build);
  };
  sel.addEventListener('change', () => { current = sel.value; draw(); });
  $$('button', seg).forEach((b) => b.addEventListener('click', () => { metric = b.dataset.m; $$('button', seg).forEach((x) => x.setAttribute('aria-selected', x === b)); draw(); }));
  const outlook = { deteriorating: [], improving: [], stable: [] };
  fcs.forEach((v) => outlook[v.forecast.outlook]?.push(v));
  root.append(h('div', { class: 'whatif' },
    h('div', { class: 'stack' },
      panel('Early warnings', null, warn.length ? h('ul', { class: 'checks' }, warn.map((w) => h('li', { class: `${w.confidence === 'high' ? 'unsupported' : 'corrected'} as-btn` },
        h('button', { type: 'button', class: 'row-btn', onclick: () => { current = R.vendors.find((x) => x.vendor.startsWith(short(w.vendor)))?.vendor || current; sel.value = current; draw(); } },
          icon('alert'), h('div', {}, h('b', {}, short(w.vendor)), h('span', { class: 'note' }, `${w.projection} · ${w.confidence} confidence`), h('span', { class: 'note' }, `Trigger: ${w.recommended_trigger}`)))))) : h('p', { class: 'meta' }, 'No projected breaches.')),
      panel('Outlook', null, h('div', { class: 'legend', style: { display: 'grid', gap: '8px' } },
        h('span', {}, h('i', { class: 'bg-replace' }), `Deteriorating: ${outlook.deteriorating.map((v) => short(v.vendor)).join(', ') || 'none'}`),
        h('span', {}, h('i', { class: 'bg-keep' }), `Improving: ${outlook.improving.map((v) => short(v.vendor)).join(', ') || 'none'}`),
        h('span', {}, h('i', { style: { background: 'var(--ink-3)' } }), `Stable: ${outlook.stable.length} vendors`)))),
    h('section', { class: 'panel' }, h('div', { class: 'panel-head' }, h('h2', {}, 'Projection with 80% band'), h('div', { class: 'toolbar', style: { margin: 0 } }, sel, seg)), node,
      R.forecast?.summary ? h('p', { class: 'meta', style: { marginTop: '8px' } }, R.forecast.summary) : null)));
  draw();
}

/* =============================================================== MARKET */
function signalCard(s) {
  return h('article', { class: 'signal' },
    h('div', { class: 'score' }, h('span', { class: 'sdot', style: { background: riskColor(s.risk_score) } }), Math.round(s.risk_score), h('small', {}, 'risk')),
    h('div', {},
      h('h3', {}, s.category === 'All' ? s.region : s.category, s.region && s.category !== 'All' && s.region !== 'All India' ? h('span', { class: 'meta' }, s.region) : null, h('span', { class: `dir ${s.direction}` }, s.direction)),
      h('p', { class: 'hl' }, s.headline),
      h('p', { class: 'im' }, s.implication),
      h('p', { class: 'src' }, s.source ? h('span', {}, s.source) : null, s.date ? h('span', { class: 'num' }, s.date) : null,
        s.url ? h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, 'Open source', icon('external')) : null)));
}
function sourceList(all) {
  const ul = h('ul', { class: 'sources' });
  const item = (s) => h('li', {}, h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title), h('span', {}, [s.source, s.date, `query “${s.query}”`].filter(Boolean).join(' · ')));
  all.slice(0, 8).forEach((s) => ul.append(item(s)));
  if (all.length <= 8) return ul;
  const btn = h('button', { class: 'btn ghost sm more', type: 'button', 'aria-expanded': 'false' }, `Show all ${all.length} sources`);
  btn.addEventListener('click', () => { all.slice(8).forEach((s) => ul.append(item(s))); btn.remove(); });
  return h('div', {}, ul, btn);
}
function market(root) {
  const m = R.market || {};
  const sigs = [...(m.signals || [])].sort((a, b) => b.risk_score - a.risk_score);
  const node = h('div', { class: 'chart short', role: 'img', 'aria-label': 'External risk score by category and region' });
  root.append(h('div', { class: 'whatif' },
    h('div', { class: 'stack' },
      panel('External risk', 'Scored by the Market Risk Researcher from live news', node, m.summary ? h('p', { class: 'meta', style: { marginTop: '8px' } }, m.summary) : null),
      panel('Sources', `${(m.sources || []).length} articles retrieved this run`, (m.sources || []).length ? sourceList(m.sources) : h('p', { class: 'meta' }, 'No live sources (search unavailable during this run).'))),
    panel('Signals', null, sigs.length ? h('div', { class: 'signals' }, sigs.map(signalCard)) : h('p', { class: 'meta' }, 'No signals returned.'))));
  chart(node, (t) => ({
    ...base(t), grid: { left: 120, right: 30, top: 6, bottom: 24 },
    xAxis: { type: 'value', min: 0, max: 100, ...axis(t) },
    yAxis: { type: 'category', inverse: true, data: sigs.map((s) => (s.category === 'All' ? s.region.split(',')[0] : CAT_SHORT[s.category] || s.category)), ...axis(t), axisLabel: { color: t.ink2, fontFamily: 'Geist', fontSize: 12 } },
    series: [{ type: 'bar', barWidth: 14, data: sigs.map((s) => ({ value: s.risk_score, itemStyle: { color: t.risk[Math.min(4, Math.floor(s.risk_score / 20))], borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: 'right', color: t.ink2, fontFamily: 'Geist Mono', fontSize: 11 },
      markLine: { symbol: 'none', silent: true, lineStyle: { color: t.ink3, type: [4, 4] }, label: { formatter: 'baseline', color: t.ink3, fontSize: 10 }, data: [{ xAxis: 35 }] } }],
  }));
}

/* ================================================================= PLAN */
function planCard(p, compact = false) {
  return h('article', { class: compact ? '' : 'panel plan' },
    compact ? null : h('div', { class: 'plan-head' }, h('div', {}, h('h2', {}, short(p.vendor)), h('p', {}, /^[\d.\s]+$/.test(String(p.risk)) ? `Combined risk ${p.risk}` : p.risk)), h('button', { class: 'btn ghost sm', type: 'button', onclick: () => openVendor(p.vendor) }, 'Vendor dossier', icon('arrow-right'))),
    h('div', { class: 'shift' }, h('span', { class: 'from' }, h('b', {}, short(p.vendor))), icon('arrow-right'),
      (p.alternatives || []).length ? p.alternatives.map((a) => h('span', { class: 'to' }, h('b', {}, short(a.to_vendor)), h('span', { class: 'pct' }, `${Math.round(a.share_of_volume_pct)}%`))) : h('span', { class: 'meta' }, 'No qualified alternative in this category')),
    h('div', { class: 'phases' }, [['30 days', p.days_30], ['60 days', p.days_60], ['90 days', p.days_90]].map(([l, items]) => h('div', { class: 'phase' }, h(compact ? 'h4' : 'h3', {}, l), h('ul', {}, (items || []).map((x) => h('li', {}, x)))))),
    p.expected_impact ? h('p', { class: 'impact' }, h('b', {}, 'Expected impact: '), p.expected_impact) : null);
}
function plan(root) {
  const plans = R.mitigation?.plans || [];
  if (!plans.length) {
    root.append(h('section', { class: 'panel' }, h('div', { class: 'empty' }, h('b', {}, 'No mitigation needed'), 'The risk gate found no vendor above tolerance, so the Mitigation Planner was skipped for this run.')));
    return;
  }
  if (R.mitigation.summary) root.append(h('p', { class: 'lede', style: { margin: '0 0 16px' } }, R.mitigation.summary));
  plans.forEach((p) => root.append(planCard(p)));
}

/* ============================================================== WHAT-IF */
function whatif(root) {
  const weights = { ...(R.config?.weights || {}) };
  const tbody = h('tbody');
  const note = h('p', { class: 'meta', style: { marginTop: '10px' } });
  const baseRank = Object.fromEntries(R.vendors.map((v) => [v.vendor, v.rank]));
  const baseDec = Object.fromEntries(R.vendors.map((v) => [v.vendor, dec(v)]));
  const th = R.config?.risk_threshold ?? 55;
  const kpiById = Object.fromEntries(R.vendors.map((v) => [v.vendor, v]));
  const ws = h('div', { class: 'weights' });
  const compute = () => {
    // Same formula as the server's scorer: pillar scores are weight-independent, so re-weight locally (instant).
    const tot = Object.values(weights).reduce((a, x) => a + Math.max(0, x), 0) || 1;
    const rows = R.vendors.map((v) => ({ v, s: Object.entries(v.pillars).reduce((a, [k, x]) => a + x * (Math.max(0, weights[k] || 0) / tot), 0) }))
      .sort((a, b) => b.s - a.s).map((r, i) => ({ ...r, rank: i + 1 }));
    tbody.innerHTML = '';
    let flips = 0;
    rows.forEach((r) => {
      const mv = baseRank[r.v.vendor] - r.rank;
      const momentum = r.v.internal_risk - (100 - r.v.composite);
      const newInternal = Math.max(0, Math.min(100, 100 - r.s + momentum));
      const newComb = 0.65 * newInternal + 0.35 * r.v.market_risk;
      const crosses = (r.v.combined_risk >= th) !== (newComb >= th);
      if (crosses && r.v.in_scope) flips += 1;
      tbody.append(h('tr', {},
        h('td', { class: 'n' }, r.rank), h('td', { class: 'vn' }, h('b', {}, short(r.v.vendor)), h('span', {}, CAT_SHORT[r.v.category] || r.v.category)),
        h('td', { class: 'n' }, r.s.toFixed(1)),
        h('td', { class: `mv ${mv > 0 ? 'delta-up' : mv < 0 ? 'delta-down' : ''}` }, mv ? `${mv > 0 ? '▲' : '▼'} ${Math.abs(mv)}` : '—'),
        h('td', { class: 'n' }, h('span', { class: 'riskdot', style: { '--rc': riskColor(newComb) } }, newComb.toFixed(0))),
        h('td', {}, baseDec[r.v.vendor] !== '—' ? decChip(baseDec[r.v.vendor]) : null, crosses ? h('span', { class: 'flip' }, ' crosses tolerance') : null)));
    });
    note.textContent = flips ? `${flips} vendor(s) would cross the risk tolerance under these priorities. Re-run the agents to get updated decisions.` : 'No vendor crosses the risk tolerance under these priorities: the agents\' decisions are robust to this change.';
  };
  Object.keys(PILLAR_LABEL).forEach((k) => {
    const id = `wf-${k}`;
    const input = h('input', { type: 'range', id, min: 0, max: 60, value: weights[k] ?? 20 });
    const out = h('output', { for: id }, '');
    const upd = () => { weights[k] = Number(input.value); setRangeFill(input); const tot = Object.values(weights).reduce((a, x) => a + x, 0) || 1; $$('output', ws).forEach((o) => { const kk = o.getAttribute('for').replace('wf-', ''); o.textContent = `${Math.round(weights[kk] / tot * 100)}%`; }); compute(); };
    input.addEventListener('input', upd);
    ws.append(h('div', { class: 'weight' }, h('label', { for: id }, PILLAR_LABEL[k]), input, out));
  });
  const reset = h('button', { class: 'btn ghost sm', type: 'button' }, icon('refresh'), 'Reset to run weights');
  reset.addEventListener('click', () => { root.innerHTML = ''; whatif(root); });
  root.append(h('div', { class: 'whatif' },
    panel('Change priorities', 'Instant: no AI call needed', ws, h('div', { style: { marginTop: '16px' } }, reset), note),
    h('section', { class: 'panel' }, h('div', { class: 'panel-head' }, h('h2', {}, 'Re-ranked portfolio'), h('span', { class: 'meta' }, 'Movement vs the run\'s ranking')),
      h('div', { class: 'vt-wrap' }, h('table', { class: 'vt wf-table', style: { minWidth: '560px' } },
        h('thead', {}, h('tr', {}, ['Rank', 'Vendor', 'Score', 'Move', 'Risk', 'Agent decision'].map((x) => h('th', { scope: 'col' }, x)))), tbody)))));
  $$('input[type=range]', ws).forEach((i) => i.dispatchEvent(new Event('input')));
  void kpiById;
}

/* ================================================================ AUDIT */
function audit(root) {
  const qa = R.qa || {}, q = R.quality, u = R.usage;
  const stageNames = { intake: 'Intake Router', audit: 'Data Quality Auditor', performance: 'Performance Analyst', cost: 'Cost & Spend Analyst', market: 'Market Risk Researcher', forecast: 'Forecast Agent', strategy: 'Procurement Strategist', mitigation: 'Mitigation Planner', qa: 'QA Reviewer', brief: 'Executive Writer' };
  const gantt = h('div', { class: 'chart short', role: 'img', 'aria-label': 'Timeline of agent stages' });
  const st = R.events.filter((e) => e.type === 'stage_start' || e.type === 'stage_end');
  const spans = [];
  st.filter((e) => e.type === 'stage_start').forEach((s) => { const e = st.find((x) => x.type === 'stage_end' && x.stage === s.stage && x.seq > s.seq); if (e) spans.push({ stage: s.stage, a: s.t, b: e.t, status: e.status }); });
  root.append(h('div', { class: 'grid-2' },
    panel('QA review', `Verdict: ${qa.verdict || 'n/a'} · confidence ${Math.round((qa.confidence || 0) * 100)}%`,
      (qa.checks || []).length ? h('ul', { class: 'checks' }, qa.checks.map((c) => h('li', { class: c.status }, icon(c.status === 'verified' ? 'check' : 'alert'), h('div', {}, h('b', {}, c.claim), h('span', { class: 'note' }, `${c.status}: ${c.note}`))))) : h('p', { class: 'meta' }, 'No checks recorded.'),
      (qa.guardrail_flags || []).length ? h('div', { style: { marginTop: '14px' } }, h('h3', { class: 'meta', style: { marginBottom: '8px' } }, 'Automated guardrail flags'), h('ul', { class: 'checks' }, qa.guardrail_flags.map((f) => h('li', { class: 'corrected' }, icon('flag'), h('span', {}, f))))) : null),
    panel('Data quality', `Score ${q.quality_score}/100 · auditor verdict: ${(R.audit?.verdict || '').replaceAll('_', ' ')}`,
      h('ul', { class: 'checks' }, (q.issues || []).map((i) => h('li', { class: 'corrected' }, icon('alert'), h('div', {}, h('b', {}, `${i.count} ${i.type.replace('_', ' ')} in ${i.column}`), h('span', { class: 'note' }, `${i.action}. ${(i.examples || []).slice(0, 2).join('; ')}`))))),
      (R.audit?.caveats || []).length ? h('ul', { class: 'notes', style: { marginTop: '12px' } }, R.audit.caveats.map((c) => h('li', {}, c))) : null),
    panel('Grounding guard', 'Facts checked in code after every agent', (R.grounding || []).length
      ? h('ul', { class: 'checks' }, R.grounding.map((g) => h('li', { class: 'corrected' }, icon('shield'), h('span', {}, g))))
      : h('ul', { class: 'checks' }, h('li', { class: 'verified' }, icon('check'), h('span', {}, 'Every vendor named by the agents exists in the dataset and every savings figure is within the data-supported maximum.')))),
    panel('Routing', `${(R.path || []).length} stage executions · ${R.revisions || 0} QA revision round(s)`,
      h('p', { class: 'rationale' }, (R.path || []).map((p) => stageNames[p] || p).join(' → '))),
    h('div', { class: 'span-2' }, panel('Stage timeline', `Path: ${R.path.map((p) => stageNames[p] || p).join(' → ')}`, gantt)),
    panel('Model usage', `${num(u.llm_calls)} calls · ${num(u.total_tokens)} tokens · ${num(u.failovers)} failovers · ${u.elapsed}s`,
      h('div', { class: 'vt-wrap' }, h('table', { class: 'usage' }, h('thead', {}, h('tr', {}, ['Model', 'Calls', 'Tokens in', 'Tokens out', 'Avg s', 'Failovers in'].map((x) => h('th', { scope: 'col' }, x)))),
        h('tbody', {}, Object.entries(u.per_model).sort((a, b) => b[1].calls - a[1].calls).map(([k, m]) => h('tr', {}, h('td', {}, k.split(':').slice(1).join(':')), h('td', {}, m.calls), h('td', {}, num(m.prompt_tokens)), h('td', {}, num(m.completion_tokens)), h('td', {}, (m.seconds / Math.max(1, m.calls)).toFixed(1)), h('td', {}, m.failovers))))))),
    panel('Intake plan', R.plan?.question_type?.replaceAll('_', ' '),
      h('p', { class: 'rationale' }, R.plan?.objective || ''),
      h('ul', { class: 'notes', style: { marginTop: '10px', color: 'var(--ink-2)' } }, (R.plan?.success_criteria || []).map((c) => h('li', {}, c))),
      R.plan?.instructions_for_team ? h('p', { class: 'meta' }, R.plan.instructions_for_team) : null)));
  chart(gantt, (t) => ({
    ...base(t), grid: { left: 170, right: 20, top: 8, bottom: 28 },
    tooltip: { ...base(t).tooltip, formatter: (p) => `${esc(stageNames[p.data.stage])}<br>${p.data.a.toFixed(1)}s → ${p.data.b.toFixed(1)}s (${(p.data.b - p.data.a).toFixed(1)}s)` },
    xAxis: { type: 'value', name: 'seconds', ...axis(t) },
    yAxis: { type: 'category', inverse: true, data: Object.keys(stageNames).map((k) => stageNames[k]), ...axis(t), axisLabel: { color: t.ink2, fontFamily: 'Geist', fontSize: 11 } },
    series: [{ type: 'custom', renderItem: (params, api2) => {
      const y = api2.value(2), s = api2.coord([api2.value(0), y]), e = api2.coord([api2.value(1), y]);
      const hgt = api2.size([0, 1])[1] * 0.55;
      return { type: 'rect', shape: { x: s[0], y: s[1] - hgt / 2, width: Math.max(3, e[0] - s[0]), height: hgt, r: 4 }, style: { fill: api2.value(3) ? t.brand : t.watch } };
    }, encode: { x: [0, 1], y: 2 }, data: spans.map((sp) => ({ value: [sp.a, sp.b, stageNames[sp.stage], sp.status === 'ok' ? 1 : 0], stage: sp.stage, a: sp.a, b: sp.b })) }],
  }));
}
