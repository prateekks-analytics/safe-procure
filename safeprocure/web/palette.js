// Command palette (Ctrl/⌘ K or "/"): jump to any view, insight tab or vendor, or run an action, from the keyboard.
// ARIA combobox + listbox pattern; focus returns to where it was on close.
import { h, icon } from './ui.js';

let getCommands = () => [];
let items = [], active = 0, lastFocus = null;

const $ = (s) => document.querySelector(s);

function score(label, q) {
  if (!q) return 1;
  const L = label.toLowerCase();
  const idx = L.indexOf(q);
  if (idx >= 0) return 100 - idx;
  let i = 0, s = 0;
  for (const ch of q) { const j = L.indexOf(ch, i); if (j < 0) return 0; s += j === i ? 3 : 1; i = j + 1; }
  return s;
}

function render() {
  const q = $('#pal-input').value.trim().toLowerCase();
  const all = getCommands().filter((c) => !c.hidden);
  items = all.map((c) => ({ ...c, s: score(`${c.group} ${c.label} ${c.keys || ''}`, q) })).filter((c) => c.s > 0);
  if (q) items.sort((a, b) => b.s - a.s);
  items = items.slice(0, 40);
  active = Math.min(active, Math.max(0, items.length - 1));
  const ul = $('#pal-list');
  ul.innerHTML = '';
  let group = '';
  items.forEach((c, i) => {
    if (c.group !== group && !q) { group = c.group; ul.append(h('li', { role: 'presentation', class: 'pal-group' }, group)); }
    const li = h('li', { role: 'option', id: `pal-opt-${i}`, 'aria-selected': i === active, class: 'pal-opt' },
      h('span', { class: 'pal-ic', 'aria-hidden': 'true' }, icon(c.icon || 'arrow-right')),
      h('span', { class: 'pal-lb' }, c.label, c.sub ? h('small', {}, c.sub) : null),
      c.keys ? h('kbd', {}, c.keys) : null);
    li.addEventListener('pointermove', () => { if (active !== i) { active = i; mark(); } });
    li.addEventListener('click', () => exec(i));
    ul.append(li);
  });
  if (!items.length) ul.append(h('li', { role: 'presentation', class: 'pal-empty' }, 'No match. Try a view, a tab or a vendor name.'));
  $('#pal-count').textContent = `${items.length} result${items.length === 1 ? '' : 's'}`;
  mark();
}
function mark() {
  document.querySelectorAll('#pal-list [role=option]').forEach((li, i) => li.setAttribute('aria-selected', i === active));
  const inp = $('#pal-input');
  if (items.length) inp.setAttribute('aria-activedescendant', `pal-opt-${active}`); else inp.removeAttribute('aria-activedescendant');
  document.getElementById(`pal-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
}
function exec(i) {
  const c = items[i];
  if (!c) return;
  close(false);
  setTimeout(() => c.run(), 0);
}

export function openPalette() {
  const d = $('#palette');
  if (!d.hidden) return;
  lastFocus = document.activeElement;
  d.hidden = false; $('#pal-scrim').hidden = false;
  $('#pal-input').value = ''; active = 0;
  render();
  $('#pal-input').focus();
  $('#palette-btn')?.setAttribute('aria-expanded', 'true');
}
function close(restore = true) {
  const d = $('#palette');
  if (d.hidden) return;
  d.hidden = true; $('#pal-scrim').hidden = true;
  $('#palette-btn')?.setAttribute('aria-expanded', 'false');
  if (restore) lastFocus?.focus?.();
}

export function initPalette(commands) {
  getCommands = commands;
  const inp = $('#pal-input');
  inp.addEventListener('input', () => { active = 0; render(); });
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % Math.max(1, items.length); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + items.length) % Math.max(1, items.length); mark(); }
    else if (e.key === 'Home' && e.ctrlKey) { active = 0; mark(); }
    else if (e.key === 'Enter') { e.preventDefault(); exec(active); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Tab') { e.preventDefault(); } // single-field dialog: keep focus inside
  });
  $('#pal-scrim').addEventListener('click', () => close());
  $('#palette-btn')?.addEventListener('click', openPalette);
  document.addEventListener('keydown', (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#palette').hidden ? openPalette() : close(); }
    else if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === '/' || e.key === '?') && $('#palette').hidden && $('#drawer').hidden) { e.preventDefault(); openPalette(); }
  });
}
