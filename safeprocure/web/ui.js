// Small DOM + formatting helpers shared by every view.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null) continue;
    if (k.startsWith('aria-')) { el.setAttribute(k, String(v)); continue; }
    if (v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') {
      for (const [sk, sv] of Object.entries(v)) { if (sk.startsWith('--')) el.style.setProperty(sk, sv); else el.style[sk] = sv; }
    }
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const icon = (name, cls = '') => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', `i ${cls}`.trim());
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function inr(v) {
  v = Number(v) || 0;
  const a = Math.abs(v);
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
  return `₹${Math.round(v).toLocaleString('en-IN')}`;
}
export const pct = (v, d = 1) => `${Number(v).toFixed(d)}%`;
export const num = (v, d = 0) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
export const short = (name) => String(name || '').replace(/ Pvt Ltd$/i, '');
export const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function riskColor(r) {
  const stops = ['--risk-0', '--risk-1', '--risk-2', '--risk-3', '--risk-4'];
  const i = r < 25 ? 0 : r < 40 ? 1 : r < 55 ? 2 : r < 70 ? 3 : 4;
  return `var(${stops[i]})`;
}

export function sparkline(values, w = 84, hgt = 24) {
  if (!values || values.length < 2) return '';
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => [i * (w - 4) / (values.length - 1) + 2, hgt - 3 - (v - min) / span * (hgt - 6)]);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${hgt}" aria-hidden="true"><path d="${d}"/><circle class="end" cx="${lx}" cy="${ly}" r="2.2"/></svg>`;
}

// ECharts loads async from the CDN so the UI can render first; run cb now or once the library arrives.
export function onEcharts(cb) {
  if (window.echarts) { cb(); return; }
  document.getElementById('echarts-js')?.addEventListener('load', () => cb(), { once: true });
}

// Score tier letter; screen readers hear "tier A" instead of a bare letter glued to the score.
export const tierChip = (t) => h('span', { class: `tier ${t}` }, h('span', { class: 'sr-only' }, ` tier ${t} `), h('span', { 'aria-hidden': 'true' }, t));

// Bottom space taken by visible docked controls (launch bar, run-done bar, copilot button) that sit under the toast column.
function dockOffset(zone) {
  const z = zone.getBoundingClientRect();
  let off = 0;
  for (const el of document.querySelectorAll('.launch-bar, .copilot-fab')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.top >= innerHeight || r.right < z.left || r.left > z.right) continue;
    off = Math.max(off, innerHeight - r.top);
  }
  return off;
}

export function toast(msg, kind = '') {
  const t = h('div', { class: `toast ${kind}` }, msg);
  const zone = document.getElementById('toasts');
  zone.append(t);
  requestAnimationFrame(() => { zone.style.bottom = `${Math.max(24, dockOffset(zone) + 12)}px`; });
  setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, kind === 'err' ? 6500 : 3800);
}

export async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) } };
  if (init.body && typeof init.body === 'object' && !(init.body instanceof FormData)) init.body = JSON.stringify(init.body);
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch (e) { /* ignore */ }
    throw Object.assign(new Error(detail), { status: r.status });
  }
  return r.status === 202 ? { _pending: true, ...(await r.json()) } : r.json();
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function setRangeFill(input) {
  const p = ((input.value - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty('--p', `${p}%`);
}

export const DECISIONS = ['Keep', 'Watch', 'Develop', 'Replace'];
export const decisionVar = (d) => `var(--${String(d || 'keep').toLowerCase()})`;

export const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};
