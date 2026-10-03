// Observatory layer: a generative star field behind the app that reacts to the cursor, the run and the decisions.
// Purely visual. Every effect is a no-op under prefers-reduced-motion, and the loop sleeps when the tab is hidden.

const RM = matchMedia('(prefers-reduced-motion: reduce)');
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const F = {
  cv: null, cx: null, w: 0, h: 0, dpr: 1, stars: [], fx: [], mx: -1e4, my: -1e4, tx: 0, ty: 0, px: 0, py: 0,
  mode: 'calm', speed: 0, warp: 0, mix: null, raf: 0, last: 0, ink: '20,22,30', dark: false, egg: 0,
};

const DEC = ['keep', 'watch', 'develop', 'replace'];
function rgb(v) {
  const c = document.createElement('canvas').getContext('2d');
  c.fillStyle = v || '#888'; const s = c.fillStyle;
  if (s.startsWith('#')) { const n = parseInt(s.slice(1), 16); return `${n >> 16 & 255},${n >> 8 & 255},${n & 255}`; }
  return s.replace(/rgba?\(|\)|\s/g, '').split(',').slice(0, 3).join(',');
}
function palette() {
  const dark = document.documentElement.dataset.theme === 'dark' || (document.documentElement.dataset.theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  F.dark = dark;
  F.ink = dark ? '226,230,255' : '40,42,70';
  F.brand = rgb(css('--brand'));
  F.dec = Object.fromEntries(DEC.map((d) => [d, rgb(css(`--${d}`))]));
}

function seed() {
  const n = Math.min(240, Math.round((F.w * F.h) / 7000));
  F.stars = Array.from({ length: n }, () => ({
    x: Math.random() * F.w, y: Math.random() * F.h, z: Math.random() * 0.85 + 0.15,
    tw: Math.random() * Math.PI * 2, c: null, vx: (Math.random() - 0.5) * 0.06, vy: (Math.random() - 0.5) * 0.06,
  }));
  tint();
}

function resize() {
  F.dpr = Math.min(2, devicePixelRatio || 1);
  F.w = innerWidth; F.h = innerHeight;
  F.cv.width = F.w * F.dpr; F.cv.height = F.h * F.dpr;
  F.cx.setTransform(F.dpr, 0, 0, F.dpr, 0, 0);
  seed();
  if (RM.matches) frame(performance.now(), true);
}

// Star colours follow the decision mix on Insights; elsewhere they are ink/brand.
function tint() {
  const m = F.mode === 'insights' && F.mix;
  const total = m ? DEC.reduce((a, d) => a + (m[d] || 0), 0) : 0;
  F.stars.forEach((s, i) => {
    if (total && i % 3 === 0) {
      let r = Math.random() * total, k = 'keep';
      for (const d of DEC) { r -= m[d] || 0; if (r <= 0) { k = d; break; } }
      s.c = F.dec[k];
    } else s.c = i % 7 === 0 ? F.brand : null;
  });
}

function frame(t, once = false) {
  const dt = Math.min(50, t - (F.last || t)); F.last = t;
  const { cx, w, h } = F;
  cx.clearRect(0, 0, w, h);
  // eased parallax toward the cursor
  F.px += (F.tx - F.px) * 0.05; F.py += (F.ty - F.py) * 0.05;
  const target = F.mode === 'run' ? 1 : 0;
  F.speed += (target - F.speed) * 0.02;
  F.warp = Math.max(0, F.warp - dt / 900);
  const cxm = w / 2, cym = h / 2;
  const near = [];
  for (const s of F.stars) {
    // drift; during a run the field streams outward from the centre like a slow jump
    const dx = s.x - cxm, dy = s.y - cym, d = Math.hypot(dx, dy) || 1;
    const out = (F.speed * 0.35 + F.warp * 14) * s.z;
    s.x += s.vx * dt * 0.6 + (dx / d) * out * dt * 0.06;
    s.y += s.vy * dt * 0.6 + (dy / d) * out * dt * 0.06;
    if (s.x < -20 || s.x > w + 20 || s.y < -20 || s.y > h + 20) {
      if (F.speed > 0.2 || F.warp > 0) { const a = Math.random() * 6.283, r = Math.random() * 60; s.x = cxm + Math.cos(a) * r; s.y = cym + Math.sin(a) * r; }
      else { s.x = (s.x + w) % w; s.y = (s.y + h) % h; }
    }
    // cursor gravity: stars lean toward the pointer
    const ox = s.x + F.px * s.z * 18, oy = s.y + F.py * s.z * 18;
    const mdx = F.mx - ox, mdy = F.my - oy, md = Math.hypot(mdx, mdy);
    let gx = 0, gy = 0;
    if (md < 170) { const f = (1 - md / 170) * 10 * s.z; gx = (mdx / md) * f; gy = (mdy / md) * f; near.push([ox + gx, oy + gy, s]); }
    s.tw += dt * 0.002;
    const a = (0.25 + 0.55 * s.z) * (0.75 + 0.25 * Math.sin(s.tw)) * (F.dark ? 1 : 0.55);
    const col = s.c || F.ink;
    const X = ox + gx, Y = oy + gy;
    if (F.warp > 0.02 || F.speed > 0.3) {
      const len = (F.warp * 60 + F.speed * 6) * s.z;
      cx.strokeStyle = `rgba(${col},${a})`; cx.lineWidth = s.z * 1.4;
      cx.beginPath(); cx.moveTo(X, Y); cx.lineTo(X - (dx / d) * len, Y - (dy / d) * len); cx.stroke();
    } else {
      cx.fillStyle = `rgba(${col},${a})`;
      cx.beginPath(); cx.arc(X, Y, s.z * (s.c ? 1.7 : 1.2), 0, 6.283); cx.fill();
    }
  }
  // constellation lines around the cursor
  if (near.length > 1) {
    cx.lineWidth = 0.7;
    for (let i = 0; i < near.length; i++) for (let j = i + 1; j < near.length; j++) {
      const [x1, y1] = near[i], [x2, y2] = near[j], dd = Math.hypot(x1 - x2, y1 - y2);
      if (dd < 90) { cx.strokeStyle = `rgba(${F.brand},${(1 - dd / 90) * (F.dark ? 0.45 : 0.3)})`; cx.beginPath(); cx.moveTo(x1, y1); cx.lineTo(x2, y2); cx.stroke(); }
    }
  }
  // transient effects: pulses and bursts
  F.fx = F.fx.filter((e) => {
    e.t += dt;
    const p = e.t / e.life;
    if (p >= 1) return false;
    if (e.kind === 'ring') {
      cx.strokeStyle = `rgba(${e.c},${(1 - p) * 0.7})`; cx.lineWidth = 2 * (1 - p) + 0.4;
      cx.beginPath(); cx.arc(e.x, e.y, e.r0 + p * e.r, 0, 6.283); cx.stroke();
    } else {
      e.x += e.vx * dt; e.y += e.vy * dt; e.vy += 0.00045 * dt; e.vx *= 0.985; e.vy *= 0.985;
      cx.fillStyle = `rgba(${e.c},${1 - p})`;
      cx.beginPath(); cx.arc(e.x, e.y, e.s * (1 - p * 0.5), 0, 6.283); cx.fill();
    }
    return true;
  });
  if (!once) F.raf = requestAnimationFrame(frame);
}

function start() { if (!F.raf && !RM.matches && !document.hidden) { F.last = 0; F.raf = requestAnimationFrame(frame); } }
function stop() { cancelAnimationFrame(F.raf); F.raf = 0; }

export function initFx() {
  const cv = document.createElement('canvas');
  cv.className = 'sky'; cv.setAttribute('aria-hidden', 'true');
  document.body.prepend(cv);
  F.cv = cv; F.cx = cv.getContext('2d');
  palette(); resize();
  addEventListener('resize', () => { resize(); });
  addEventListener('pointermove', (e) => {
    F.mx = e.clientX; F.my = e.clientY;
    F.tx = (e.clientX / F.w - 0.5) * 2; F.ty = (e.clientY / F.h - 0.5) * 2;
    spotlight(e);
  }, { passive: true });
  document.addEventListener('pointerleave', () => { F.mx = F.my = -1e4; });
  document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
  RM.addEventListener('change', () => { if (RM.matches) { stop(); frame(performance.now(), true); } else start(); });
  initPress(); initMagnet(); initEgg();
  start();
}

export function setMode(mode, mix) {
  F.mode = mode; if (mix) F.mix = mix;
  tint();
  document.documentElement.dataset.sky = mode;
}
export function retheme() { palette(); tint(); if (RM.matches) frame(performance.now(), true); }

export function warp() { if (RM.matches) return; F.warp = 1; start(); }

export function pulse(x, y, color = 'brand') {
  if (RM.matches) return;
  const c = color === 'brand' ? F.brand : F.dec[color] || color;
  F.fx.push({ kind: 'ring', x, y, r0: 6, r: 90, t: 0, life: 900, c });
}
export function pulseAt(el, color) {
  if (!el) return;
  const r = el.getBoundingClientRect();
  if (r.width) pulse(r.left + r.width / 2, r.top + r.height / 2, color);
}

// Particle burst in the decision colours (e.g. run complete).
export function burst(x = F.w / 2, y = F.h / 2, mix = { keep: 1, watch: 1, develop: 1, replace: 1 }, n = 110) {
  if (RM.matches) return;
  const keys = DEC.flatMap((d) => Array(Math.max(0, Math.round((mix[d] || 0) * 4))).fill(d));
  for (let i = 0; i < n; i++) {
    const a = Math.random() * 6.283, v = 0.15 + Math.random() * 0.55;
    F.fx.push({ kind: 'p', x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 0.18, s: 1.5 + Math.random() * 2.2, t: 0, life: 1100 + Math.random() * 900, c: F.dec[keys[i % keys.length] || 'keep'] });
  }
  F.fx.push({ kind: 'ring', x, y, r0: 10, r: 260, t: 0, life: 1200, c: F.brand });
  start();
}

/* ------------------------------------------------------------ delight */
// Cursor spotlight on the panel under the pointer.
let litPanel = null;
function spotlight(e) {
  const p = e.target.closest?.('.panel, .launch-bar, .run-stats div');
  if (litPanel && litPanel !== p) litPanel.classList.remove('lit');
  litPanel = p;
  if (!p) return;
  const r = p.getBoundingClientRect();
  p.style.setProperty('--mx', `${e.clientX - r.left}px`); p.style.setProperty('--my', `${e.clientY - r.top}px`);
  p.classList.add('lit');
}

// Spring press: buttons squash on press and spring back on release.
function initPress() {
  document.addEventListener('pointerdown', (e) => {
    const b = e.target.closest?.('.btn, .chip, .icon-btn, .steps a, [role="tab"], .prompt-chips button, .presets button, .copilot-fab');
    if (!b || RM.matches) return;
    b.classList.remove('sprung'); b.classList.add('pressed');
    const up = () => { b.classList.remove('pressed'); void b.offsetWidth; b.classList.add('sprung'); setTimeout(() => b.classList.remove('sprung'), 600); removeEventListener('pointerup', up); removeEventListener('pointercancel', up); };
    addEventListener('pointerup', up); addEventListener('pointercancel', up);
  });
}

// Magnetic primary buttons lean toward the cursor.
function initMagnet() {
  document.addEventListener('pointermove', (e) => {
    if (RM.matches || e.pointerType !== 'mouse') return;
    for (const b of document.querySelectorAll('.btn.primary.lg, .copilot-fab')) {
      const r = b.getBoundingClientRect();
      if (!r.width) continue;
      const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
      const near = Math.abs(dx) < r.width / 2 + 40 && Math.abs(dy) < r.height / 2 + 40;
      b.style.setProperty('--mgx', near ? `${dx * 0.14}px` : '0px');
      b.style.setProperty('--mgy', near ? `${dy * 0.22}px` : '0px');
    }
  }, { passive: true });
}

// Easter egg: the Konami code (or five clicks on the logo) recolours the sky with every decision colour.
function initEgg() {
  const code = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
  let i = 0;
  document.addEventListener('keydown', (e) => { i = e.key === code[i] ? i + 1 : e.key === code[0] ? 1 : 0; if (i === code.length) { i = 0; egg(); } });
  let clicks = 0, t = 0;
  document.querySelector('.brand')?.addEventListener('click', () => { const n = Date.now(); clicks = n - t < 600 ? clicks + 1 : 1; t = n; if (clicks >= 5) { clicks = 0; egg(); } });
}
function egg() {
  F.stars.forEach((s, i) => { s.c = F.dec[DEC[i % 4]]; });
  burst(F.w / 2, F.h / 2, { keep: 1, watch: 1, develop: 1, replace: 1 }, 200);
  warp();
  document.dispatchEvent(new CustomEvent('sp-egg'));
}
