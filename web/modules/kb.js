// 知识库：两层。概念层是「我看过、想过、判断过」的内容按概念组织成的图谱（像 Obsidian）；
// 来源层是各板块同步来的 markdown 原文，可检索、可批注。
// 路由：#kb（图谱）#kb/topics #kb/stream #kb/source · #kb/c/<概念> #kb/t/<主题> #kb/doc/<路径>
import { annotate } from './_annotate.js';

const CSS = `
.kb-graph { position: relative; padding: 0; overflow: hidden; }
.kb-graph canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.kb-graph canvas.drag { cursor: grabbing; }
.kb-graph .kb-tip { position: absolute; pointer-events: none; background: var(--panel); border: 1px solid var(--line-2);
  border-radius: 8px; padding: 6px 10px; font-size: 12px; box-shadow: var(--shadow); max-width: 260px; display: none; }
.kb-graph .kb-tip b { font-size: 13px; }
.kb-graph .kb-hint { position: absolute; left: 12px; bottom: 8px; font-size: 12px; color: var(--muted); pointer-events: none; }
.kb-legend { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; align-items: center; }
.kb-legend button { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--panel);
  border-radius: 999px; padding: 3px 11px; font-size: 12px; color: var(--text); }
.kb-legend button.off { opacity: .45; }
.kb-legend button.on { border-color: var(--text); }
.kb-legend .sp { flex: 1; }
.kb-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex: none; }
.kb-topics { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.kb-topics .card h3 { margin: 0 0 4px; font-size: 18px; display: flex; align-items: center; gap: 8px; }
.kb-cl { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.kb-cl a { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; color: var(--text); font-size: 12.5px; background: var(--bg); }
.kb-cl a:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
.kb-cl a small { color: var(--muted); margin-left: 4px; }
.kb-j { padding: 14px 16px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); margin-bottom: 10px; transition: box-shadow .3s; }
.kb-j.flash { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
.kb-j .claim { font: 600 15.5px/1.55 var(--serif); margin: 4px 0; }
.kb-j .claim .n { color: var(--accent); font-family: var(--font); font-size: 12px; margin-right: 6px; }
.kb-j blockquote { margin: 6px 0; padding: 2px 0 2px 12px; border-left: 3px solid var(--line-2); font-size: 13.5px; white-space: pre-wrap; }
.kb-j .ctx { color: var(--muted); font-size: 12.5px; }
.kb-j .foot { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin-top: 8px; font-size: 12.5px; color: var(--muted); }
.kb-j .foot .kb-cl { margin-top: 0; }
.kb-sum { padding: 16px 18px; background: var(--focus); border-radius: var(--radius); border: 1px solid var(--line); }
.kb-sum ul { margin: 6px 0 0; padding-left: 20px; } .kb-sum li { margin: 4px 0; }
.kb-sum sup a { font-size: 11px; padding: 0 1px; }
.kb-sum .lbl { font-size: 12px; color: var(--muted); }
.kb-back { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-size: 13px; margin-bottom: 6px; }
.kb-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-size: 13px; margin: -6px 0 4px; align-items: center; }
.kb-day { font: 600 13px var(--font); color: var(--muted); margin: 18px 0 8px; }
.kb-status { font-size: 12.5px; color: var(--muted); }
`;

// 主题配色：深浅两种主题下都看得清；「未归类」用灰
const PALETTE = ['#c4552f', '#3f7cac', '#4c8a5a', '#b7791f', '#8a5cb8', '#2a9d8f', '#c0567e', '#6b7a8f', '#9c6b3f', '#5d8f2f', '#b04a4a', '#4a6fb0'];
const colorOf = (topics) => {
  const m = {};
  topics.filter((t) => t.name !== '未归类').forEach((t, i) => { m[t.name] = PALETTE[i % PALETTE.length]; });
  return (name) => m[name] || '#a39a8f';
};
const enc = encodeURIComponent;
const cLink = (name) => '#kb/c/' + enc(name);
const tLink = (name) => '#kb/t/' + enc(name);
const dLink = (path) => '#kb/doc/' + enc(path);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export default {
  async render(el, ctx) {
    const { h } = ctx;
    if (!document.getElementById('kb-style')) document.head.append(h('style#kb-style', {}, CSS));
    const [tab = 'graph', ...rest] = ctx.sub;
    let arg = rest.join('/');
    try { arg = decodeURIComponent(arg); } catch { /* 保持原样 */ }
    if (tab === 'c') return conceptPage(el, ctx, arg);
    if (tab === 't') return topicPage(el, ctx, arg);
    if (tab === 'doc') return docPage(el, ctx, arg);
    return home(el, ctx, tab);
  },
};

// ---------- 首页：页头 + 搜索 + 四个视图 ----------
async function home(el, ctx, tab) {
  const { api, h, ui, ask, toast } = ctx;
  const [g, st] = await Promise.all([api.get('/api/kb/graph'), api.get('/api/kb/stats')]);
  const tabs = [['graph', '图谱'], ['topics', '主题'], ['stream', '最近思考'], ['source', '来源库']];
  const cur = tabs.some(([id]) => id === tab) ? tab : 'graph';
  const tabBar = h('div.tabs', { style: { marginBottom: 0 } }, tabs.map(([id, name]) =>
    h('button' + (cur === id ? '.active' : ''), { onclick: () => { location.hash = id === 'graph' ? '#kb' : '#kb/' + id; } }, name)));
  const status = h('span.kb-status');
  const refreshBtn = h('button.outline', { title: '用大模型把新的判断和材料整理进概念图谱', onclick: () => runRefresh() }, [ui.icon('refresh'), '整理']);
  const results = h('div');

  el.append(
    ui.pageHead('知识库', `${g.nodes.length} 个概念 · ${g.signals.judgment || 0} 条我的判断 · ${g.signals.material || 0} 份看过的材料 · 来源文件 ${st.total} 份`, [refreshBtn]),
    ui.composer({
      placeholder: '搜概念或关键词，或切到「问 Agent」用一句话问你的积累…',
      modes: [{ id: 'search', label: '搜索', placeholder: '搜概念或关键词（中文 3 个字以上更准）…' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：我之前关于 Agent 评测有哪些判断？' }],
      hint: 'Obsidian 可直接打开 ' + st.dir,
      onSubmit: (t, mode) => (mode === 'ask' ? ask(t) : search(t)),
    }),
    results,
    h('div.row', { style: { margin: '14px 0 12px', alignItems: 'center' } }, [tabBar, h('span.grow'), status]),
  );
  const body = h('div');
  el.append(body);
  showStatus(g.status, g.stale);
  if (g.status.running) poll();

  if (cur === 'graph') graphTab(body, ctx, g);
  else if (cur === 'topics') topicsTab(body, ctx, g);
  else if (cur === 'stream') streamTab(body, ctx);
  else sourceTab(body, ctx, st);

  function showStatus(s, stale) {
    refreshBtn.disabled = !!s.running;
    status.textContent = s.running ? `整理中… ${s.msg || ''}` : stale ? `有 ${stale} 条新内容还没整理进图谱` : s.at ? `上次整理 ${s.at.slice(5, 16).replace('T', ' ')}` : '';
  }
  async function runRefresh() {
    await api.post('/api/kb/graph/refresh');
    toast('开始整理：抽概念、归主题、写归纳，约 1 分钟');
    poll();
  }
  async function poll() {
    for (;;) {
      if (!el.isConnected) return;
      const s = await api.get('/api/kb/graph/status');
      showStatus(s, 0);
      if (!s.running) { if (s.state === 'error') toast('整理失败：' + (s.msg || ''), true); else ctx.refresh(); return; }
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  async function search(q) {
    const rs = await api.get(`/api/kb/search?q=${enc(q)}&limit=30`);
    const cs = rs.filter((d) => d.type === 'concept');
    const ds = rs.filter((d) => d.type !== 'concept');
    results.replaceChildren(
      ui.section(`「${q}」`, [`${rs.length} 条 · `, h('a', { href: '#', onclick: (e) => { e.preventDefault(); results.replaceChildren(); } }, '收起')]),
      cs.length ? h('div.kb-cl', { style: { marginBottom: '10px' } }, cs.map((d) => h('a', { href: cLink(d.title) }, [d.title, h('small', {}, d.summary || '')]))) : null,
      ds.length ? h('div.card', {}, h('div.list', {}, ds.map((d) => docRow(ctx, d, st.names)))) : cs.length ? null : ui.empty('没找到', '换个说法，或直接问 Agent'),
    );
  }
}

function docRow(ctx, d, names = {}) {
  const { h } = ctx;
  return h('div.item', { style: { cursor: 'pointer' }, onclick: () => { location.hash = dLink(d.path); } }, [
    h('div.row', {}, [h('span.tag', {}, names[d.type] || d.type), h('span.item-title.grow', {}, d.title), h('span.muted', {}, d.date || '')]),
    d.snippet ? h('div.muted.clamp2', { html: esc(d.snippet).replace(/«/g, '<mark>').replace(/»/g, '</mark>') }) : h('div.muted.clamp2', {}, d.summary || ''),
  ]);
}

// ---------- 图谱 ----------
function graphTab(body, ctx, g) {
  const { h, ui } = ctx;
  if (!g.nodes.length) {
    body.append(ui.empty('图谱还是空的', g.stale ? '点右上角「整理」，把你的判断和看过的材料整理成概念' : '在各板块写复盘、批注、作答后，这里会长出你的概念图谱'));
    return;
  }
  const color = colorOf(g.topics);
  let all = false;
  let focus = '';
  const legend = h('div.kb-legend');
  const box = h('div');
  body.append(legend, box);
  const draw = () => {
    const nodes = g.nodes.filter((n) => all || n.core);
    const ids = new Set(nodes.map((n) => n.id));
    legend.replaceChildren(
      ...g.topics.map((t) => h('button' + (focus === t.name ? '.on' : focus ? '.off' : ''), {
        title: t.desc, onclick: () => { focus = focus === t.name ? '' : t.name; draw(); },
      }, [h('span.kb-dot', { style: { background: color(t.name) } }), t.name, h('span.muted', {}, String(t.n))])),
      h('span.sp'),
      h('button', { onclick: () => { all = !all; draw(); }, title: '核心概念 = 至少两次出现在我的判断或材料里' },
        all ? `全部 ${g.nodes.length} 个 · 只看核心` : `核心 ${nodes.length} 个 · 显示全部`),
    );
    box.replaceChildren(graphView(ctx, nodes, g.edges.filter((e) => ids.has(e.a) && ids.has(e.b)), color, { focus, height: 600 }));
  };
  draw();
}

/** 力导向图（canvas）。nodes: [{id, topic, category, w, j, m, last}]，edges: [{a, b, w}]。点节点进概念页。 */
function graphView(ctx, nodes, edges, color, { focus = '', height = 600 } = {}) {
  const { h } = ctx;
  const cv = h('canvas');
  const tip = h('div.kb-tip');
  const wrap = h('div.card.kb-graph', { style: { height: height + 'px' } }, [cv, tip, h('div.kb-hint', {}, '滚轮缩放 · 拖动平移 · 点概念打开 · 实心描边 = 有我的判断')]);
  const N = nodes.map((n) => ({ ...n, r: 3.5 + Math.sqrt(n.w) * 2.1, x: 0, y: 0, vx: 0, vy: 0 }));
  const byId = Object.fromEntries(N.map((n) => [n.id, n]));
  const E = edges.map((e) => ({ s: byId[e.a], t: byId[e.b], w: e.w })).filter((e) => e.s && e.t);
  const nbr = {};
  for (const e of E) { (nbr[e.s.id] ||= new Set()).add(e.t.id); (nbr[e.t.id] ||= new Set()).add(e.s.id); }
  // 同主题聚在一起：主题锚点排在一个圆上，节点初始放在锚点附近
  const topics = [...new Set(N.map((n) => n.topic))];
  const anchor = {};
  const R = 40 + 14 * Math.sqrt(N.length);
  topics.forEach((t, i) => { const a = (i / topics.length) * Math.PI * 2; anchor[t] = topics.length > 1 ? [Math.cos(a) * R, Math.sin(a) * R] : [0, 0]; });
  N.forEach((n) => { const [ax, ay] = anchor[n.topic]; n.x = ax + (Math.random() - 0.5) * 80; n.y = ay + (Math.random() - 0.5) * 80; });
  const byW = [...N].sort((a, b) => b.w - a.w);

  let view = { k: 1, x: 0, y: 0 };
  let W = 0, H = 0, dpr = 1;
  let alpha = 1, hover = null, drag = null, touched = false, dirty = true, started = false;

  const resize = () => {
    dpr = window.devicePixelRatio || 1;
    W = wrap.clientWidth; H = wrap.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    dirty = true;
  };
  const toWorld = (px, py) => [(px - W / 2 - view.x) / view.k, (py - H / 2 - view.y) / view.k];
  const pick = (px, py) => {
    const [x, y] = toWorld(px, py);
    let best = null, bd = Infinity;
    for (const n of N) { const d = Math.hypot(n.x - x, n.y - y); if (d < n.r + 4 / view.k && d < bd) { best = n; bd = d; } }
    return best;
  };
  const fit = () => {
    // 取全部节点的范围；只有个别孤点甩得特别远（比 2% 分位范围宽出一倍）时才把它排除，免得整张图被缩小
    if (!N.length || !W) return;
    const q = (arr) => {
      arr.sort((a, b) => a - b);
      const i = Math.floor(arr.length * 0.02), lo = arr[i], hi = arr[arr.length - 1 - i], pad = (hi - lo) * 0.5;
      return [Math.max(arr[0], lo - pad) - 20, Math.min(arr[arr.length - 1], hi + pad) + 20];
    };
    const [x0, x1] = q(N.map((n) => n.x)); const [y0, y1] = q(N.map((n) => n.y));
    const k = Math.min(2, (W - 100) / (x1 - x0 || 1), (H - 90) / (y1 - y0 || 1));
    view = { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k };
  };

  const tick = () => {
    const rep = 3000 * alpha;
    for (let i = 0; i < N.length; i++) {
      const a = N[i];
      for (let j = i + 1; j < N.length; j++) {
        const b = N[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        if (d2 > 160000) continue;
        const d = Math.sqrt(d2);
        // 斥力 + 碰撞：圆之间至少留 10px
        const f = rep / Math.max(d2, 100) + Math.max(0, a.r + b.r + 10 - d) * 0.3;
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
    }
    for (const e of E) {
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
      const d = Math.hypot(dx, dy) || 1;
      const L = 40 + e.s.r + e.t.r;
      const f = ((d - L) / d) * 0.03 * Math.min(e.w, 4) * alpha;
      e.s.vx += dx * f; e.s.vy += dy * f; e.t.vx -= dx * f; e.t.vy -= dy * f;
    }
    for (const n of N) {
      const [ax, ay] = anchor[n.topic];
      n.vx += (ax - n.x) * 0.008 * alpha - n.x * 0.002; n.vy += (ay - n.y) * 0.008 * alpha - n.y * 0.002;
      if (n === drag?.node) { n.vx = n.vy = 0; continue; }
      n.vx = Math.max(-15, Math.min(15, n.vx * 0.55)); n.vy = Math.max(-15, Math.min(15, n.vy * 0.55));
      n.x += n.vx; n.y += n.vy;
    }
    alpha = Math.max(0, alpha * 0.985);
  };

  const draw = () => {
    const css = getComputedStyle(document.documentElement);
    const v = (k) => css.getPropertyValue(k).trim();
    const c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);
    c.translate(W / 2 + view.x, H / 2 + view.y);
    c.scale(view.k, view.k);
    const hi = hover ? nbr[hover.id] || new Set() : null;
    const dim = (n) => (hover ? n !== hover && !hi.has(n.id) : focus ? n.topic !== focus : false);
    c.lineCap = 'round';
    for (const e of E) {
      const on = hover && (e.s === hover || e.t === hover);
      c.strokeStyle = on ? v('--accent') : v('--line-2');
      c.globalAlpha = on ? 0.9 : dim(e.s) || dim(e.t) ? 0.08 : e.s.topic === e.t.topic ? 0.65 : 0.25;
      c.lineWidth = (on ? 1.6 : 0.6 + Math.min(e.w, 6) * 0.25) / Math.sqrt(view.k);
      c.beginPath(); c.moveTo(e.s.x, e.s.y); c.lineTo(e.t.x, e.t.y); c.stroke();
    }
    for (const n of N) {
      c.globalAlpha = dim(n) ? 0.15 : 1;
      c.fillStyle = color(n.topic);
      c.beginPath(); c.arc(n.x, n.y, n.r, 0, Math.PI * 2); c.fill();
      if (n.j) { c.strokeStyle = v('--text'); c.lineWidth = 1.2 / view.k; c.stroke(); }
    }
    c.font = `${12 / view.k}px ${v('--font')}`;
    c.textAlign = 'center'; c.textBaseline = 'top'; c.lineJoin = 'round';
    // 标签按分量从大到小放，和已放的标签重叠就不画；悬停时只标它和邻居
    const boxes = [];
    const lh = 14 / view.k;
    for (const n of byW) {
      const must = n === hover || hi?.has(n.id);
      if (hover ? !must : focus && n.topic !== focus) continue;
      const w = c.measureText(n.id).width;
      const b = [n.x - w / 2, n.y + n.r + 2 / view.k, n.x + w / 2, n.y + n.r + 2 / view.k + lh];
      if (!must && boxes.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1])) continue;
      boxes.push(b);
      c.globalAlpha = 1;
      c.strokeStyle = v('--panel'); c.lineWidth = 3 / view.k; c.strokeText(n.id, n.x, b[1]);
      c.fillStyle = v('--text'); c.fillText(n.id, n.x, b[1]);
    }
    c.globalAlpha = 1;
  };

  // 模拟跑完、没交互时不重绘；离开页面（元素脱离文档）就停
  const loop = () => {
    if (!wrap.isConnected) { if (!started) requestAnimationFrame(loop); return; }
    if (!started) { started = true; resize(); }
    if (alpha > 0.005) { tick(); tick(); if (!touched) fit(); dirty = true; }
    if (dirty) { draw(); dirty = false; }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  new ResizeObserver(() => { resize(); if (!touched) fit(); }).observe(wrap);

  const pos = (e) => { const b = cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
  cv.addEventListener('pointerdown', (e) => {
    const [px, py] = pos(e);
    drag = { node: pick(px, py), px, py, vx: view.x, vy: view.y, moved: false };
    cv.setPointerCapture(e.pointerId);
    cv.classList.add('drag');
  });
  cv.addEventListener('pointermove', (e) => {
    const [px, py] = pos(e);
    dirty = true;
    if (drag) {
      if (Math.hypot(px - drag.px, py - drag.py) > 3) { drag.moved = true; touched = true; }
      if (!drag.moved) return;
      if (drag.node) { const [x, y] = toWorld(px, py); drag.node.x = x; drag.node.y = y; alpha = Math.max(alpha, 0.12); }
      else { view.x = drag.vx + px - drag.px; view.y = drag.vy + py - drag.py; }
      return;
    }
    hover = pick(px, py);
    cv.style.cursor = hover ? 'pointer' : '';
    if (hover) {
      tip.style.display = 'block';
      tip.replaceChildren(h('b', {}, hover.id), h('div.muted', {}, `${hover.topic} · ${hover.category}`),
        h('div', {}, `${hover.j} 条判断 · ${hover.m} 份材料${hover.last ? ' · 最近 ' + hover.last : ''}`));
      tip.style.left = Math.min(px + 14, W - 220) + 'px'; tip.style.top = Math.min(py + 14, H - 70) + 'px';
    } else tip.style.display = 'none';
  });
  const up = () => {
    if (drag && !drag.moved && drag.node) location.hash = cLink(drag.node.id);
    drag = null; cv.classList.remove('drag');
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  cv.addEventListener('pointerleave', () => { if (!drag) { hover = null; tip.style.display = 'none'; dirty = true; } });
  cv.addEventListener('wheel', (e) => {
    e.preventDefault();
    touched = true; dirty = true;
    const [px, py] = pos(e);
    const k = Math.max(0.2, Math.min(5, view.k * Math.exp(-e.deltaY * 0.0015)));
    const cx = px - W / 2, cy = py - H / 2;
    view.x = cx - ((cx - view.x) * k) / view.k; view.y = cy - ((cy - view.y) * k) / view.k; view.k = k;
  }, { passive: false });
  return wrap;
}

// ---------- 主题 ----------
function topicsTab(body, ctx, g) {
  const { h, ui } = ctx;
  if (!g.topics.length) { body.append(ui.empty('还没有主题', '点右上角「整理」生成')); return; }
  const color = colorOf(g.topics);
  body.append(h('div.kb-topics', {}, g.topics.map((t) => {
    const cs = g.nodes.filter((n) => n.topic === t.name).sort((a, b) => b.w - a.w);
    const shown = cs.filter((n) => n.core).slice(0, 14);
    return h('div.card', {}, [
      h('h3', {}, [h('span.kb-dot', { style: { background: color(t.name) } }), h('a', { href: tLink(t.name), style: { color: 'inherit' } }, t.name)]),
      h('div.muted', {}, t.desc || ''),
      h('div.kb-cl', {}, [...shown.map((n) => h('a', { href: cLink(n.id), title: `${n.j} 条判断 · ${n.m} 份材料` }, [n.id, n.j ? h('small', {}, String(n.j)) : null])),
        cs.length > shown.length ? h('a', { href: tLink(t.name) }, `全部 ${cs.length} 个 →`) : null]),
    ]);
  })));
}

async function topicPage(el, ctx, name) {
  const { api, h, ui } = ctx;
  const g = await api.get('/api/kb/graph');
  const t = g.topics.find((x) => x.name === name);
  el.append(h('a.kb-back', { href: '#kb/topics' }, '← 知识库 · 主题'));
  if (!t) { el.append(ui.empty('没有这个主题', '可能整理后改了名字')); return; }
  const color = colorOf(g.topics);
  const cs = g.nodes.filter((n) => n.topic === name).sort((a, b) => b.w - a.w);
  const ids = new Set(cs.map((n) => n.id));
  el.append(ui.pageHead(name, `${t.desc || ''} · ${cs.length} 个概念`,
    [h('button.ghost', { onclick: () => { location.hash = dLink('topics/' + name.replace(/[\\/:*?"<>|#^[\]]+/g, '-') + '.md'); } }, [ui.icon('doc'), 'markdown'])]));
  el.append(graphView(ctx, cs, g.edges.filter((e) => ids.has(e.a) && ids.has(e.b)), color, { height: 420 }));
  el.append(ui.section('概念', '按分量排序（一条判断算 3，一份材料算 1）'),
    h('div.card', {}, h('div.list', {}, cs.map((n) => h('div.item', { style: { cursor: 'pointer' }, onclick: () => { location.hash = cLink(n.id); } },
      h('div.row', {}, [h('span.tag', {}, n.category), h('span.item-title.grow', {}, n.id),
        h('span.muted', {}, `${n.j} 判断 · ${n.m} 材料${n.last ? ' · ' + n.last : ''}`)]))))));
}

// ---------- 概念页 ----------
async function conceptPage(el, ctx, name) {
  const { api, h, ui, ask, toast } = ctx;
  el.append(h('a.kb-back', { href: '#kb' }, '← 知识库'));
  let c;
  try { c = await api.get(`/api/kb/concept?name=${enc(name)}`); } catch { c = null; }
  if (!c) { el.append(ui.empty(`没有「${name}」这个概念`, '可能被合并、隐藏，或还没整理进来')); return; }
  if (c.name !== name) history.replaceState(null, '', cLink(c.name));

  const rename = async () => {
    const dst = prompt('改名为（填一个已有概念名，就把它合并进去）', c.name)?.trim();
    if (!dst || dst === c.name) return;
    await api.post('/api/kb/concept/edit', { op: 'rename', src: c.name, dst });
    toast('已改名，Obsidian 里的文件也同步了');
    location.hash = cLink(dst);
  };
  const hide = async () => {
    if (!confirm(`从图谱里隐藏「${c.name}」？不删任何原始记录，以后重新整理也不会再出现。`)) return;
    await api.post('/api/kb/concept/edit', { op: 'hide', src: c.name });
    toast('已隐藏');
    location.hash = '#kb';
  };
  el.append(ui.pageHead(c.name, '', [
    h('button.outline', { onclick: () => ask(`读知识库里概念「${c.name}」的页面（${c.path}），总结我对它的判断、还没想清楚的地方，以及接下来值得看什么。`) }, [ui.icon('chat'), '问 Agent']),
    h('button.ghost', { onclick: rename, title: '改名，或合并到另一个概念' }, [ui.icon('edit'), '改名 / 合并']),
    h('button.ghost', { onclick: hide, title: '不是我关心的概念' }, [ui.icon('x'), '隐藏']),
  ]));
  el.append(h('div.kb-meta', {}, [
    h('span.tag', {}, c.category),
    h('span', {}, ['主题 ', h('a', { href: tLink(c.topic) }, c.topic)]),
    c.aliases.length ? h('span', {}, '又称 ' + c.aliases.join('、')) : null,
    h('span', {}, c.first === c.last ? c.first : `${c.first} → ${c.last}`),
    h('a', { href: dLink(c.path) }, c.path),
  ]));

  // 我的理解：AI 据我的判断归纳，[n] 指向下面第 n 条判断
  const cite = (s) => esc(s).replace(/\[(\d+)\]/g, (_, n) => `<sup><a href="#" data-n="${n}">[${n}]</a></sup>`);
  const sm = c.summary || {};
  const sumBox = h('div.kb-sum', {}, sm.points?.length ? [
    h('div.lbl', {}, '我的理解 · AI 根据下面我的判断归纳，[n] 是出处'),
    h('ul', {}, sm.points.map((p) => h('li', { html: cite(p) }))),
    sm.open?.length ? h('div.lbl', { style: { marginTop: '10px' } }, '还没想清楚') : null,
    sm.open?.length ? h('ul', {}, sm.open.map((p) => h('li', { html: cite(p) }))) : null,
  ] : h('div.muted', {}, c.judgments.length ? '归纳还没生成，下次「整理」时会补上。' : '这个概念目前只出现在看过的材料里，还没有我自己的判断。'));
  sumBox.addEventListener('click', (e) => {
    const n = e.target.dataset?.n;
    if (!n) return;
    e.preventDefault();
    const card = el.querySelector(`[data-j="${n}"]`);
    if (card) { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); card.classList.add('flash'); setTimeout(() => card.classList.remove('flash'), 1600); }
  });
  el.append(h('div', { style: { marginTop: '16px' } }, sumBox));

  if (c.judgments.length) {
    el.append(ui.section('我的判断', `${c.judgments.length} 条 · 按时间`));
    el.append(h('div', {}, c.judgments.map((s, i) => judgmentCard(ctx, s, i + 1, c.name))));
  }
  if (c.materials.length) {
    el.append(ui.section('看过的材料', `${c.materials.length} 份`));
    el.append(h('div.card', {}, h('div.list', {}, c.materials.map((s) => h('div.item', {}, [
      h('div.row', {}, [h('span.tag', {}, s.sub_name), h('span.item-title.grow', {}, srcLink(h, s)), h('span.muted', {}, s.date)]),
      s.context ? h('div.muted.clamp2', {}, s.context) : null,
    ])))));
  }
  if (c.related.length) {
    el.append(ui.section('相关概念', '在同一条判断或材料里一起出现，数字是关联强度'));
    el.append(h('div.kb-cl', {}, c.related.map((r) => h('a', { href: cLink(r.name) }, [r.name, h('small', {}, String(r.w))]))));
  }
}

// 来源：优先跳平台原页面（能接着作答、批注），没有就打开知识库里的 markdown
function srcLink(h, s) {
  const href = s.link || (s.path ? dLink(s.path) : s.url || '#');
  const a = h('a', { href, title: s.path || '' }, s.title);
  if (!s.link && !s.path && s.url) { a.target = '_blank'; a.rel = 'noopener'; }
  return a;
}

function judgmentCard(ctx, s, n, self = '') {
  const { h } = ctx;
  const norm = (x) => (x || '').replace(/\s/g, '');
  const dup = !s.claim || norm(s.mine).startsWith(norm(s.claim).slice(0, 20));
  return h('div.kb-j', n ? { 'data-j': String(n) } : {}, [
    h('div.row', {}, [h('span.tag', {}, s.sub_name), h('span.muted.grow', {}, s.date)]),
    h('div.claim', {}, [n ? h('span.n', {}, `[${n}]`) : null, s.claim || s.mine]),
    s.mine && !dup ? h('blockquote', {}, s.mine) : null,
    s.context ? h('div.ctx.clamp2', {}, '针对：' + s.context) : null,
    h('div.foot', {}, [
      h('span', {}, ['来自 ', srcLink(h, s)]),
      s.path && s.link ? h('a', { href: dLink(s.path), title: '知识库里的 markdown' }, '原文') : null,
      h('span.grow'),
      h('span.kb-cl', {}, s.concepts.filter((x) => x !== self).map((x) => h('a', { href: cLink(x) }, x))),
    ]),
  ]);
}

// ---------- 最近思考 ----------
async function streamTab(body, ctx) {
  const { api, h, ui } = ctx;
  const js = await api.get('/api/kb/stream?limit=80');
  if (!js.length) { body.append(ui.empty('还没有判断', '复盘、批注、作答、感想都会出现在这里')); return; }
  let day = null;
  for (const s of js) {
    if (s.date !== day) { day = s.date; body.append(h('div.kb-day', {}, day || '未注明日期')); }
    body.append(judgmentCard(ctx, s, 0));
  }
}

// ---------- 来源库：各板块同步来的原始 markdown ----------
function sourceTab(body, ctx, st) {
  const { api, h, ui } = ctx;
  let type = '';
  const statsBox = h('div');
  const listBox = h('div');
  body.append(h('div.muted', { style: { marginBottom: '10px' } }, '各板块原样同步的记录。产品雷达等没互动过的自动内容只在这里，不进概念图谱。'), statsBox, listBox);
  const drawStats = () => statsBox.replaceChildren(ui.stats(Object.entries(st.by_type).map(([k, v]) => ({
    k: st.names[k] || k, v, active: type === k,
    onClick: () => { type = type === k ? '' : k; drawStats(); drawList(); },
  }))));
  const drawList = async () => {
    if (!type) {
      listBox.replaceChildren(ui.section('最近更新'),
        st.recent.length ? h('div.card', {}, h('div.list', {}, st.recent.map((d) => docRow(ctx, d, st.names)))) : ui.empty('还没有知识', '在各板块记录、调研、学习后会自动出现在这里'));
      return;
    }
    const ds = await api.get(`/api/kb/list?type=${enc(type)}`);
    listBox.replaceChildren(ui.section(st.names[type] || type, [`${ds.length} 份 · `, h('a', { href: '#', onclick: (e) => { e.preventDefault(); type = ''; drawStats(); drawList(); } }, '显示全部')]),
      ds.length ? h('div.card', {}, h('div.list', {}, ds.map((d) => docRow(ctx, d, st.names)))) : ui.empty('这一类还没有内容'));
  };
  drawStats();
  drawList();
}

// ---------- 阅读 markdown：[[双链]] 可点 ----------
async function docPage(el, ctx, path) {
  const { api, h, md, ui } = ctx;
  el.append(h('a.kb-back', { href: '#', onclick: (e) => { e.preventDefault(); if (history.length > 1) history.back(); else location.hash = '#kb/source'; } }, '← 返回'));
  let text;
  try { text = await api.get(`/api/kb/doc?path=${enc(path)}`); } catch { el.append(ui.empty('找不到这个文件', path)); return; }
  const body = String(text).replace(/^---[\s\S]*?---\s*/, '');
  // [[concepts/x|名]] [[topics/x|名]] [[目录/文件|标题]] [[概念]] → 站内链接
  const linked = body.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, target, label) => {
    const t = target.trim();
    let href;
    if (t.startsWith('topics/')) href = tLink(label || t.slice(7));
    else if (t.startsWith('concepts/')) href = cLink(label || t.slice(9));
    else if (t.includes('/')) href = dLink(t.endsWith('.md') ? t : t + '.md');
    else href = cLink(label || t);
    return `[${(label || t.split('/').pop()).replace(/[[\]]/g, '')}](<${href}>)`;
  });
  el.append(h('div.card', {}, [
    h('div.row.between', {}, [h('span.card-label', {}, path)]),
    annotate(ctx, md(linked), { doc: `kb:${path}`, title: path, link: dLink(path), source: body }),
  ]));
}
