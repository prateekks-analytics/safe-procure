// Decision Orbit: every in-scope vendor is a star on the ring of its decision (Keep innermost, Replace outermost).
// Drag to spin it, select a star for the dossier. Opening it plays a "big bang" where the stars burst out of the core.
// Pointer convenience only: the same vendors stay reachable by keyboard in "Needs attention" and the Vendors tab.
import { short, inr } from './ui.js';
import { burst } from './fx.js';

const NS = 'http://www.w3.org/2000/svg';
const RINGS = [['Keep', 74], ['Develop', 112], ['Watch', 150], ['Replace', 188]];
const RM = matchMedia('(prefers-reduced-motion: reduce)');
let played = new WeakSet();

const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
};

export function decisionOrbit(result, vendors, onPick) {
  const wrap = document.createElement('div');
  wrap.className = 'orbit';
  const c = Object.fromEntries(RINGS.map(([d]) => [d, vendors.filter((v) => v.decision?.decision === d)]));
  const svg = el('svg', { viewBox: '-215 -215 430 430', role: 'img', 'aria-label': `Decision orbit: ${RINGS.map(([d]) => `${c[d].length} ${d}`).join(', ')}. Drag to rotate; vendors are also listed under Needs attention and in the Vendors tab.` });
  wrap.append(svg);
  const tip = document.createElement('div');
  tip.className = 'orbit-tip'; tip.setAttribute('aria-hidden', 'true'); tip.hidden = true;
  wrap.append(tip);

  const defs = el('defs', {}, svg);
  const g = el('radialGradient', { id: 'orbit-core' }, defs);
  el('stop', { offset: '0%', 'stop-color': 'var(--brand)', 'stop-opacity': '.55' }, g);
  el('stop', { offset: '100%', 'stop-color': 'var(--brand)', 'stop-opacity': '0' }, g);
  el('circle', { r: 64, fill: 'url(#orbit-core)', class: 'o-glow' }, svg);

  const maxSpend = Math.max(...vendors.map((v) => v.spend_total), 1);
  const stars = [];
  const rings = RINGS.map(([d, r], ri) => {
    el('circle', { r, class: `o-ring ${d.toLowerCase()}` }, svg);
    const lbl = el('text', { class: `o-lbl ${d.toLowerCase()}`, x: 0, y: -r - 5, 'text-anchor': 'middle' }, svg);
    lbl.textContent = `${d} · ${c[d].length}`;
    const grp = el('g', { class: 'o-grp' }, svg);
    const list = c[d];
    list.forEach((v, i) => {
      const a0 = (i / Math.max(1, list.length)) * Math.PI * 2 + ri * 0.7;
      const s = el('g', { class: `o-star ${d.toLowerCase()}` }, grp);
      const size = 4.5 + Math.sqrt(v.spend_total / maxSpend) * 8;
      el('circle', { r: size + 6, class: 'o-hit' }, s);
      el('circle', { r: size, class: 'o-dot' }, s);
      s.addEventListener('pointerenter', () => { tip.hidden = false; tip.innerHTML = `<b>${short(v.vendor)}</b><span>${d} · risk ${Math.round(v.combined_risk)} · ${inr(v.spend_total)}</span>`; s.classList.add('hot'); });
      s.addEventListener('pointerleave', () => { tip.hidden = true; s.classList.remove('hot'); });
      s.addEventListener('click', () => { if (!dragMoved) onPick(v.vendor); });
      stars.push({ s, r, a0, ri, i, size, v });
    });
    return { grp, speed: [0.00011, -0.00008, 0.00006, -0.00004][ri] };
  });
  // core
  el('circle', { r: 30, class: 'o-core' }, svg);
  const n = el('text', { class: 'o-n', y: 4, 'text-anchor': 'middle' }, svg);
  n.textContent = vendors.length;
  const nl = el('text', { class: 'o-nl', y: 18, 'text-anchor': 'middle' }, svg);
  nl.textContent = 'vendors';

  // drag-to-spin with inertia
  let spin = 0, vel = 0, dragging = false, dragMoved = false, lastA = 0, lastT = 0;
  const angleOf = (e) => { const b = svg.getBoundingClientRect(); return Math.atan2(e.clientY - (b.top + b.height / 2), e.clientX - (b.left + b.width / 2)); };
  svg.addEventListener('pointerdown', (e) => { dragging = true; dragMoved = false; lastA = angleOf(e); lastT = performance.now(); svg.setPointerCapture(e.pointerId); wrap.classList.add('grab'); });
  svg.addEventListener('pointermove', (e) => {
    const rb = wrap.getBoundingClientRect();
    tip.style.transform = `translate(${e.clientX - rb.left + 14}px, ${e.clientY - rb.top + 10}px)`;
    if (!dragging) return;
    const a = angleOf(e), now = performance.now();
    let d = a - lastA; if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI;
    if (Math.abs(d) > 0.01) dragMoved = true;
    spin += d; vel = d / Math.max(8, now - lastT); lastA = a; lastT = now;
    if (RM.matches) draw(now);
  });
  const end = () => { dragging = false; wrap.classList.remove('grab'); setTimeout(() => { dragMoved = false; }, 0); };
  svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);

  // big bang intro (plays the first time the orbit is on screen) + continuous orbit
  let t0 = performance.now();
  const intro = !RM.matches && !played.has(result);
  played.add(result);
  const ease = (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p) * Math.cos(p * 6.2)); // springy overshoot
  let raf = 0, visible = true;
  function draw(now) {
    const t = now - t0;
    if (!dragging) { spin += vel * 16; vel *= 0.95; }
    for (const st of stars) {
      const delay = 120 + st.ri * 140 + st.i * 35;
      const p = intro ? Math.max(0, Math.min(1, (t - delay) / 1100)) : 1;
      const e = ease(p);
      const a = st.a0 + spin + (RM.matches ? 0 : t * rings[st.ri].speed);
      const rr = st.r * e;
      st.s.setAttribute('transform', `translate(${(Math.cos(a) * rr).toFixed(2)} ${(Math.sin(a) * rr).toFixed(2)}) scale(${(0.2 + 0.8 * Math.min(1, p * 1.6)).toFixed(3)})`);
    }
  }
  function loop(now) { draw(now); raf = wrap.isConnected && visible && !RM.matches ? requestAnimationFrame(loop) : 0; }
  let banged = !intro;
  const bang = () => {
    banged = true; t0 = performance.now();
    const b = svg.getBoundingClientRect();
    const mix = Object.fromEntries(RINGS.map(([d]) => [d.toLowerCase(), c[d].length]));
    setTimeout(() => burst(b.left + b.width / 2, b.top + b.height / 2, mix, 90), 80);
    wrap.classList.add('bang');
  };
  const io = new IntersectionObserver(([en]) => {
    visible = en.isIntersecting;
    if (visible && !banged) bang();
    if (visible && !raf && !RM.matches) raf = requestAnimationFrame(loop);
  }, { threshold: 0.35 });
  requestAnimationFrame(() => {
    if (!wrap.isConnected) return;
    io.observe(wrap);
    draw(performance.now());
  });
  return wrap;
}
