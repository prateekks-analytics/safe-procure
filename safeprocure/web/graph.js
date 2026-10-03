// Live workflow graph: draws the CrewAI Flow and animates it from telemetry events.

const NS = 'http://www.w3.org/2000/svg';
const W = 214, H = 54;

export const NODES = {
  intake:      { x: 430, y: 44,  name: 'Intake Router',        role: 'Turns the question into a plan', n: 1 },
  audit:       { x: 430, y: 136, name: 'Data Quality Auditor', role: 'Checks the data is decision-grade', n: 2 },
  performance: { x: 150, y: 244, name: 'Performance Analyst',  role: 'Delivery, quality, trends', n: 3 },
  cost:        { x: 430, y: 244, name: 'Cost & Spend Analyst', role: 'Concentration and savings', n: 4 },
  market:      { x: 710, y: 244, name: 'Market Risk Researcher', role: 'Live news by category and region', n: 5 },
  forecast:    { x: 430, y: 352, name: 'Forecast Agent',       role: 'Next-quarter projections', n: 6 },
  strategy:    { x: 430, y: 448, name: 'Procurement Strategist', role: 'Keep, Watch, Develop, Replace', n: 7 },
  mitigation:  { x: 700, y: 532, name: 'Mitigation Planner',   role: 'Dual sourcing and 30/60/90 plan', n: 8 },
  qa:          { x: 430, y: 616, name: 'QA Reviewer',          role: 'Verifies claims, can send back', n: 9 },
  brief:       { x: 430, y: 712, name: 'Executive Writer',     role: 'Board-ready answer', n: 10 },
};
const GATE = { x: 430, y: 532 };

const EDGES = [
  ['intake', 'audit'], ['audit', 'performance'], ['audit', 'cost'], ['audit', 'market'],
  ['performance', 'forecast'], ['cost', 'forecast'], ['market', 'forecast'], ['forecast', 'strategy'],
  ['strategy', 'gate'], ['gate', 'mitigation', 'high risk'], ['gate', 'qa', 'low risk'], ['mitigation', 'qa'],
  ['qa', 'brief', 'approve'], ['qa', 'strategy', 'revise', true],
];

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

function anchor(id, side) {
  if (id === 'gate') {
    return { top: [GATE.x, GATE.y - 22], bottom: [GATE.x, GATE.y + 22], right: [GATE.x + 22, GATE.y], left: [GATE.x - 22, GATE.y] }[side];
  }
  const n = NODES[id];
  return { top: [n.x, n.y - H / 2], bottom: [n.x, n.y + H / 2], left: [n.x - W / 2, n.y], right: [n.x + W / 2, n.y] }[side];
}

function edgePath(a, b, loop) {
  if (loop) {
    const [x1, y1] = anchor(a, 'left');
    const [x2, y2] = anchor(b, 'left');
    return `M${x1} ${y1} C ${x1 - 150} ${y1}, ${x2 - 150} ${y2}, ${x2} ${y2}`;
  }
  if (a === 'gate' && b === 'mitigation') {
    const [x1, y1] = anchor('gate', 'right');
    const [x2, y2] = anchor('mitigation', 'left');
    return `M${x1} ${y1} L ${x2} ${y2}`;
  }
  if (a === 'mitigation' && b === 'qa') {
    const [x1, y1] = anchor('mitigation', 'bottom');
    const [x2, y2] = anchor('qa', 'right');
    return `M${x1} ${y1} C ${x1} ${y2}, ${x1} ${y2}, ${x2} ${y2}`;
  }
  const [x1, y1] = anchor(a, 'bottom');
  const [x2, y2] = anchor(b, 'top');
  const my = (y1 + y2) / 2;
  return `M${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
}

const BADGE_IDLE = 'M-3 0h6'; // small dash
const fit = (s, n = 27) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const MODEL_SHORT = (s) => s.replace('Gemini 3.1 Flash-Lite', 'Flash-Lite').replace('GPT-OSS ', 'GPT-OSS·').replace('Qwen 3.8 27B', 'Qwen 3.8');
const BADGE_DONE = 'M-4.5 0.5 -1.3 3.6 4.6 -3.2';
const BADGE_WARN = 'M0 -4v4.2M0 4v.1';

export class FlowGraph {
  constructor(svg, onSelect) {
    this.svg = svg;
    this.onSelect = onSelect;
    this.state = {};
    this.selected = null;
    this.build();
  }

  build() {
    const s = this.svg;
    s.innerHTML = '';
    s.setAttribute('viewBox', '0 0 860 750');
    s.setAttribute('role', 'group');
    const edges = el('g', {}, s);
    this.packetLayer = null;
    this.edges = {};
    for (const [a, b, label, loop] of EDGES) {
      const p = el('path', { class: `g-edge${loop ? ' loop' : ''}`, d: edgePath(a, b, loop), 'marker-end': 'url(#arrow)' }, edges);
      this.edges[`${a}>${b}`] = p;
      if (label) {
        let tx, ty;
        if (loop) { tx = 214; ty = 534; }
        else if (b === 'mitigation') { tx = 486; ty = 522; }
        else if (b === 'qa' && a === 'gate') { tx = 442; ty = 576; }
        else { tx = 442; ty = 668; }
        const t = el('text', { class: 'g-route', x: tx, y: ty }, edges);
        t.textContent = label;
        this.edges[`${a}>${b}`].label = t;
      }
    }
    const defs = el('defs', {}, s);
    const m = el('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: '8.5', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0 1.5 8.5 5 0 8.5', fill: 'none', stroke: 'var(--ink-3)', 'stroke-width': '1.4', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, m);

    this.packetLayer = el('g', { class: 'g-packets', 'aria-hidden': 'true' }, s);
    const gate = el('g', { class: 'g-gate', transform: `translate(${GATE.x} ${GATE.y})` }, s);
    el('polygon', { points: '0,-22 22,0 0,22 -22,0' }, gate);
    const gt = el('text', { x: -30, y: 4, 'text-anchor': 'end' }, gate);
    gt.textContent = 'Risk gate';
    this.gate = gate;

    this.nodes = {};
    for (const [id, n] of Object.entries(NODES)) {
      const g = el('g', { class: 'g-node', transform: `translate(${n.x - W / 2} ${n.y - H / 2})`, tabindex: '0', role: 'button', 'aria-label': `${n.name}: idle` }, s);
      el('rect', { class: 'halo', x: -3, y: -3, width: W + 6, height: H + 6, rx: 15 }, g);
      el('rect', { class: 'card', width: W, height: H, rx: 12 }, g);
      el('circle', { class: 'badge', cx: 24, cy: H / 2, r: 12 }, g);
      const bi = el('path', { class: 'badge-ic', d: BADGE_IDLE, transform: `translate(24 ${H / 2})` }, g);
      const num = el('text', { class: 's', x: 24, y: H / 2 + 3.6, 'text-anchor': 'middle' }, g);
      num.textContent = n.n;
      const t = el('text', { class: 't', x: 44, y: 23 }, g);
      t.textContent = n.name;
      const sub = el('text', { class: 's', x: 44, y: 40 }, g);
      sub.textContent = fit(n.role, 27);
      g.addEventListener('click', () => this.select(id));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.select(id); } });
      this.nodes[id] = { g, bi, num, sub, t };
    }
  }

  buildList(ol) {
    this.list = {};
    if (!ol) return;
    ol.innerHTML = '';
    const order = [['intake'], ['audit'], ['performance', 'cost', 'market'], ['forecast'], ['strategy'], ['mitigation'], ['qa'], ['brief']];
    for (const group of order) {
      const li = document.createElement('li');
      li.className = group.length > 1 ? 'fl-group' : '';
      if (group.length > 1) { const t = document.createElement('span'); t.className = 'fl-par'; t.textContent = 'In parallel'; li.append(t); }
      for (const id of group) {
        const n = NODES[id];
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'fl-item idle';
        b.innerHTML = `<span class="fl-dot" aria-hidden="true">${n.n}</span><span class="fl-txt"><b>${n.name}</b><small>${n.role}</small></span>`;
        b.addEventListener('click', () => this.select(id));
        li.append(b);
        this.list[id] = b;
      }
      ol.append(li);
    }
  }

  reset() {
    this.state = {};
    for (const id of Object.keys(NODES)) this.set(id, 'idle');
    Object.values(this.edges).forEach((p) => { p.classList.remove('live', 'done', 'skipped'); p.label?.classList.remove('on'); });
    this.gate.setAttribute('class', 'g-gate');
  }

  set(id, status, model) {
    const n = this.nodes[id];
    if (!n) return;
    this.state[id] = status;
    n.g.setAttribute('class', `g-node ${status}${this.selected === id ? ' selected' : ''}`);
    n.g.setAttribute('aria-label', `${NODES[id].name}: ${status}`);
    const showNum = status === 'idle' || status === 'skipped';
    n.num.style.display = showNum ? '' : 'none';
    n.bi.style.display = showNum ? 'none' : '';
    n.bi.setAttribute('d', status === 'done' ? BADGE_DONE : status === 'degraded' || status === 'failed' ? BADGE_WARN : 'M0 0');
    if (status === 'active') {
      n.bi.setAttribute('d', 'M-4 0a4 4 0 1 0 8 0');
      // SMIL ignores the CSS reduced-motion rule, so only spin when motion is allowed.
      n.bi.innerHTML = matchMedia('(prefers-reduced-motion: reduce)').matches ? '' : '<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="0.9s" repeatCount="indefinite" additive="sum"/>';
    } else {
      n.bi.innerHTML = '';
    }
    if (model) n.sub.textContent = fit(MODEL_SHORT(model));
    const li = this.list?.[id];
    if (li) {
      li.className = `fl-item ${status}`;
      li.querySelector('.fl-dot').textContent = status === 'done' ? '✓' : status === 'degraded' || status === 'failed' ? '!' : NODES[id].n;
      if (model) li.querySelector('small').textContent = model;
    }
    // a finished agent hands its output on: data packets fly along every outgoing edge
    if (status === 'done' || status === 'degraded') {
      for (const key of Object.keys(this.edges)) if (key.startsWith(id + '>') && key !== 'qa>strategy') this.packet(key);
    }
    // edges into an active node animate; edges into done node settle
    for (const [key, p] of Object.entries(this.edges)) {
      const [, b] = key.split('>');
      if (b === id || (id === 'strategy' && key === 'forecast>strategy')) {
        if (status === 'active') { p.classList.add('live'); p.classList.remove('done'); }
        if (status === 'done' || status === 'degraded') { p.classList.remove('live'); p.classList.add('done'); }
        if (status === 'failed') p.classList.remove('live');
      }
    }
  }

  model(id, label) {
    const n = this.nodes[id];
    if (n) n.sub.textContent = fit(MODEL_SHORT(label));
    const li = this.list?.[id];
    if (li) li.querySelector('small').textContent = label;
  }

  // Comet-like packet travelling along an edge (skipped under reduced motion).
  packet(key, color) {
    const path = this.edges[key];
    if (!path || !this.packetLayer || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const len = path.getTotalLength();
    const dots = [0, 1, 2, 3].map((i) => el('circle', { class: 'g-packet', r: 4.2 - i * 0.9, style: `opacity:${1 - i * 0.22}${color ? `;fill:${color}` : ''}` }, this.packetLayer));
    const t0 = performance.now(), dur = 520 + len * 1.1;
    const step = (now) => {
      const p = (now - t0) / dur;
      dots.forEach((d, i) => {
        const q = Math.min(1, Math.max(0, p - i * 0.045)), e = q < 0.5 ? 2 * q * q : 1 - Math.pow(-2 * q + 2, 2) / 2;
        const pt = path.getPointAtLength(e * len);
        d.setAttribute('cx', pt.x.toFixed(1)); d.setAttribute('cy', pt.y.toFixed(1));
      });
      if (p < 1 + dots.length * 0.045 && this.svg.isConnected) requestAnimationFrame(step); else dots.forEach((d) => d.remove());
    };
    requestAnimationFrame(step);
  }

  route(stage, route) {
    if (stage === 'risk_gate') {
      this.packet(route === 'mitigate' ? 'gate>mitigation' : 'gate>qa', route === 'mitigate' ? 'var(--replace)' : null);
      this.gate.setAttribute('class', 'g-gate done');
      const hi = route === 'mitigate';
      this.edges['strategy>gate'].classList.add('done');
      this.edges['gate>mitigation'].classList.toggle('done', hi);
      this.edges['gate>mitigation'].label?.classList.toggle('on', hi);
      this.edges['gate>qa'].classList.toggle('done', !hi);
      this.edges['gate>qa'].label?.classList.toggle('on', !hi);
      if (!hi && this.state.mitigation !== 'done') this.set('mitigation', 'skipped');
    }
    if (stage === 'qa') {
      const rev = route === 'revise';
      this.packet(rev ? 'qa>strategy' : 'qa>brief', rev ? 'var(--watch)' : 'var(--keep)');
      this.edges['qa>strategy'].classList.toggle('live', rev);
      this.edges['qa>strategy'].label?.classList.toggle('on', rev);
      if (!rev) { this.edges['qa>brief'].classList.add('done'); this.edges['qa>brief'].label?.classList.add('on'); this.edges['qa>strategy'].classList.remove('live'); }
    }
  }

  select(id) {
    if (this.selected && this.nodes[this.selected]) this.nodes[this.selected].g.classList.remove('selected');
    this.selected = id;
    this.nodes[id]?.g.classList.add('selected');
    this.onSelect?.(id);
  }
}
