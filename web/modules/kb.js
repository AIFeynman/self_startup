// 知识库：两层。概念层是「我看过、想过、判断过」的内容按概念组织成的图谱（像 Obsidian）；
// 来源层是各板块同步来的 markdown 原文，可检索、可批注。
// 另有「判断台账」：我的观点 / 预测 / 评价 / 疑问，按问题线看立场变化，到期回来复查。
// 路由：#kb（判断）#kb/judge/<问题线> #kb/graph #kb/topics #kb/stream #kb/source · #kb/c/<概念> #kb/t/<主题> #kb/doc/<路径>
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
.kb-ty { font-size: 11.5px; border-radius: 5px; padding: 1px 7px; color: #fff; flex: none; }
.kb-st { font-size: 11.5px; border-radius: 999px; padding: 1px 8px; border: 1px solid var(--line-2); color: var(--muted); flex: none; white-space: nowrap; }
.kb-st.holds, .kb-st.resolved { color: var(--ok); border-color: var(--ok); background: var(--ok-soft); }
.kb-st.revised { color: var(--warn); border-color: var(--warn); background: var(--warn-soft); }
.kb-st.overturned { color: var(--err); border-color: var(--err); background: var(--err-soft); }
.kb-st.due { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.kb-jr { display: flex; gap: 8px; align-items: baseline; padding: 7px 0; cursor: pointer; }
.kb-jr .d { color: var(--muted); font-size: 12px; width: 44px; flex: none; font-variant-numeric: tabular-nums; }
.kb-jr .c { flex: 1; min-width: 0; font-size: 14px; line-height: 1.55; }
.kb-jr:hover .c { color: var(--accent); }
.kb-jd { margin: 2px 0 10px 52px; padding: 10px 14px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); font-size: 13px; }
.kb-jd blockquote { margin: 0 0 8px; padding: 2px 0 2px 10px; border-left: 3px solid var(--line-2); white-space: pre-wrap; }
.kb-ev { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; margin: 8px 0; }
.kb-ev b { font-weight: 600; color: var(--muted); font-size: 12px; white-space: nowrap; }
.kb-ag { padding: 8px 12px; border-radius: var(--radius-sm); background: var(--focus); margin: 8px 0; }
.kb-rv { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; }
.kb-rv textarea { width: 100%; min-height: 38px; resize: vertical; font: inherit; padding: 6px 8px; border: 1px solid var(--line-2); border-radius: 7px; background: var(--panel); color: var(--text); }
.kb-rv button { font-size: 12.5px; padding: 3px 10px; }
.kb-rv input[type=date] { width: auto; font: inherit; font-size: 12.5px; padding: 2px 6px; border: 1px solid var(--line-2); border-radius: 7px; background: var(--panel); color: var(--text); }
.kb-hist { margin: 6px 0 0; padding: 0; list-style: none; color: var(--muted); }
.kb-hist li { margin: 2px 0; }
.kb-th { margin-bottom: 14px; }
.kb-th h3 { margin: 0 0 4px; font: 600 17px/1.45 var(--serif); }
.kb-th .stance { font-size: 13.5px; }
.kb-shift { margin: 8px 0 4px; padding: 6px 10px; border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 7px 7px 0; font-size: 13px; }
.kb-tl { margin: 10px 0 0 4px; border-left: 2px solid var(--line-2); padding-left: 12px; }
.kb-tl > .kb-jr { position: relative; }
.kb-tl > .kb-jr::before { content: ''; position: absolute; left: -18px; top: 13px; width: 10px; height: 10px; border-radius: 50%; background: var(--panel); border: 2px solid var(--line-2); }
.kb-tl > .kb-jr.chg::before { border-color: var(--accent); background: var(--accent); }
.kb-new { display: grid; gap: 8px; padding: 14px 16px; margin-bottom: 14px; }
.kb-src { display: grid; gap: 6px; }
.kb-src .sel { display: flex; flex-wrap: wrap; gap: 6px; }
.kb-src .chip { display: inline-flex; gap: 6px; align-items: center; padding: 2px 8px; border: 1px solid var(--line-2); border-radius: 12px; font-size: 12.5px; max-width: 100%; }
.kb-src .chip > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-src .chip button { border: 0; background: none; padding: 0; color: var(--muted); cursor: pointer; }
.kb-src .hits { border: 1px solid var(--line); border-radius: 8px; max-height: 260px; overflow: auto; }
.kb-src .hit { padding: 6px 10px; cursor: pointer; font-size: 13px; }
.kb-src .hit:hover { background: var(--hover, rgba(127,127,127,.08)); }
.kb-src .hit .muted { font-size: 12px; }
.kb-srcs { display: flex; flex-wrap: wrap; gap: 4px 10px; margin: 6px 0; font-size: 13px; }
.kb-new textarea { width: 100%; min-height: 60px; font: inherit; padding: 8px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--panel); color: var(--text); resize: vertical; }
.kb-new .row select, .kb-new .row input { width: auto; font: inherit; font-size: 13px; padding: 3px 6px; border: 1px solid var(--line-2); border-radius: 7px; background: var(--panel); color: var(--text); }
@media (max-width: 640px) { .kb-jd { margin-left: 0; } }
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
const jLink = (q) => '#kb/judge/' + enc(q);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export default {
  async render(el, ctx) {
    const { h } = ctx;
    if (!document.getElementById('kb-style')) document.head.append(h('style#kb-style', {}, CSS));
    const [tab = 'judge', ...rest] = ctx.sub;
    let arg = rest.join('/');
    try { arg = decodeURIComponent(arg); } catch { /* 保持原样 */ }
    if (tab === 'c') return conceptPage(el, ctx, arg);
    if (tab === 't') return topicPage(el, ctx, arg);
    if (tab === 'doc') return docPage(el, ctx, arg);
    return home(el, ctx, tab, arg);
  },
};

// ---------- 首页：页头 + 搜索 + 四个视图 ----------
async function home(el, ctx, tab, arg = '') {
  const { api, h, ui, ask, toast } = ctx;
  const [g, st] = await Promise.all([api.get('/api/kb/graph'), api.get('/api/kb/stats')]);
  const tabs = [['judge', '判断'], ['graph', '图谱'], ['topics', '主题'], ['stream', '最近思考'], ['source', '来源库']];
  const cur = tabs.some(([id]) => id === tab) ? tab : 'judge';
  const tabBar = h('div.tabs', { style: { marginBottom: 0 } }, tabs.map(([id, name]) =>
    h('button' + (cur === id ? '.active' : ''), { onclick: () => { location.hash = id === 'judge' ? '#kb' : '#kb/' + id; } }, name)));
  const status = h('span.kb-status');
  const refreshBtn = h('button.outline', { title: '用大模型把新的判断和材料整理进概念图谱', onclick: () => runRefresh() }, [ui.icon('refresh'), '整理']);
  const results = h('div');

  el.append(
    ui.pageHead('知识库', `${g.nodes.length} 个概念 · ${g.signals.judgment || 0} 条我写下的想法 · ${g.signals.material || 0} 份看过的材料 · 来源文件 ${st.total} 份`, [refreshBtn]),
    ui.composer({
      placeholder: '搜概念或关键词，或切到「问 Agent」用一句话问你的积累…',
      modes: [{ id: 'search', label: '搜索', placeholder: '搜概念或关键词（中文 3 个字以上更准）…' },
        { id: 'judge', label: '记判断', placeholder: '写下一个判断或预测，比如：开源 Agent 框架年底会收敛到两三家' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：我之前关于 Agent 评测有哪些判断？' }],
      hint: 'Obsidian 可直接打开 ' + st.dir,
      onSubmit: (t, mode) => (mode === 'ask' ? ask(t) : mode === 'judge' ? addJudgment(ctx, { text: t }) : search(t)),
    }),
    results,
    h('div.row', { style: { margin: '14px 0 12px', alignItems: 'center' } }, [tabBar, h('span.grow'), status]),
  );
  const body = h('div');
  el.append(body);
  showStatus(g.status, g.stale);
  if (g.status.running) poll();

  if (cur === 'judge') judgeTab(body, ctx, arg);
  else if (cur === 'graph') graphTab(body, ctx, g);
  else if (cur === 'topics') topicsTab(body, ctx, g);
  else if (cur === 'stream') streamTab(body, ctx);
  else sourceTab(body, ctx, st);

  function showStatus(s, stale) {
    refreshBtn.disabled = !!s.running;
    status.textContent = s.running ? `整理中… ${s.msg || ''}` : stale ? `有 ${stale} 条新内容还没整理进图谱` : s.at ? `上次整理 ${s.at.slice(5, 16).replace('T', ' ')}` : '';
  }
  async function runRefresh() {
    await api.post('/api/kb/graph/refresh');
    toast('开始整理：抽概念、归主题、写归纳、给判断归类和评价，约 1–2 分钟');
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
    h('div.row', {}, [h('span.tag', {}, s.sub_name), s.type ? typeTag(h, s.type) : null, h('span.muted.grow', {}, s.date),
      s.thread ? h('a', { href: jLink(s.thread), title: '这条判断所在的问题线' }, '问题线：' + s.thread) : null,
      s.type ? statusTag(h, s) : null]),
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

// ---------- 判断台账 ----------
const TYPE_COLOR = { 观点: '#3f7cac', 预测: '#8a5cb8', 评价: '#2a9d8f', 疑问: '#b7791f' };
const STATUS_NAME = { open: '未复查', holds: '仍成立', revised: '修正过', overturned: '已推翻', pending: '还看不出', resolved: '已解决' };
const typeTag = (h, t) => h('span.kb-ty', { style: { background: TYPE_COLOR[t] || '#8b8178' } }, t);
function statusTag(h, c, today = new Date().toISOString().slice(0, 10)) {
  if (c.due && c.due <= today) return h('span.kb-st.due', { title: '到了该回来检查的时候' }, '待复查');
  const t = h('span.kb-st.' + c.status, {}, STATUS_NAME[c.status] || c.status);
  if (c.due) t.title = '下次复查 ' + c.due;
  return t;
}

async function addJudgment(ctx, body) {
  await ctx.api.post('/api/kb/judgments', body);
  ctx.toast('记下了。后台会归类并写 Agent 评价，稍后在「判断」里看到');
  if (location.hash === '#kb' || location.hash.startsWith('#kb/judge')) setTimeout(() => ctx.refresh(), 400);
}

async function judgeTab(body, ctx, focus = '') {
  const { api, h, ui } = ctx;
  const j = await api.get('/api/kb/judgments');
  const S = j.stats;
  if (!S.total) {
    body.append(ui.empty('还没有整理出判断', S.pending ? `有 ${S.pending} 条记录待归类，点右上角「整理」` : '复盘、批注、学习作答里写下的看法会自动汇总到这里，也可以用上面的「记判断」直接写'));
    return;
  }
  let fType = '', fStatus = '';
  body.append(ui.stats([
    { k: `我的判断 · 观点 ${S.by_type.观点} · 预测 ${S.by_type.预测} · 评价 ${S.by_type.评价} · 疑问 ${S.by_type.疑问}`, v: S.total },
    { k: '待复查', v: S.due },
    { k: `问题线 · 立场变过 ${S.changed}`, v: S.threads },
    { k: `已复查 · 仍成立 ${S.verdicts.holds} · 修正 ${S.verdicts.revised} · 推翻 ${S.verdicts.overturned}`, v: S.reviewed },
  ]));
  if (S.pending) body.append(h('div.kb-status', { style: { margin: '8px 0 0' } }, `还有 ${S.pending} 条新记录没归类，点右上角「整理」`));

  // 记一条（带类型 / 信心 / 复查日；只想快速记就用上面输入框的「记判断」）
  const newBox = h('div');
  body.append(h('div.row', { style: { margin: '14px 0 4px' } }, [h('span.grow'),
    h('button.ghost', { onclick: () => { newBox.replaceChildren(...(newBox.childElementCount ? [] : [newForm()])); } }, [ui.icon('plus'), '记一条判断 / 预测'])]), newBox);
  function newForm() {
    const ta = h('textarea', { placeholder: '一句话写清楚你的判断，越具体越好检查。例如：Claude Code 的插件生态半年内会超过 Cursor' });
    const ty = h('select', {}, [['', '类型：让 AI 判断'], ['观点', '观点'], ['预测', '预测'], ['评价', '评价']].map(([v, l]) => h('option', { value: v }, l)));
    const cf = h('select', {}, [['', '信心：让 AI 判断'], ['高', '信心高'], ['中', '信心中'], ['低', '信心低']].map(([v, l]) => h('option', { value: v }, l)));
    const due = h('input', { type: 'date', title: '什么时候回来检查（预测填兑现日期；留空按默认节奏）' });
    const note = h('input', { placeholder: '依据 / 背景（可选）', style: { flex: 1, minWidth: '160px' } });
    const src = sourcePicker(ctx);
    return h('div.card.kb-new', {}, [ta, src.el, h('div.row', { style: { flexWrap: 'wrap', gap: '8px' } }, [ty, cf, h('span.muted', {}, '复查日'), due, note,
      h('button', { onclick: async () => { if (!ta.value.trim()) return; await addJudgment(ctx, { text: ta.value, type: ty.value, confidence: cf.value, due: due.value, note: note.value, sources: src.value() }); newBox.replaceChildren(); } }, '保存')])]);
  }

  // 待复查（展开），没有就显示接下来的复查日程
  if (j.due.length) {
    body.append(ui.section('待复查', `${j.due.length} 条 · 当时的判断现在还成立吗？`));
    body.append(h('div.card', {}, j.due.map((c) => jRow(ctx, c, { open: true, today: j.today }))));
  } else if (j.upcoming.length) {
    body.append(ui.section('接下来复查', `现在没有到期的 · 最近一次 ${j.upcoming[0].due}`));
    body.append(h('div.card', {}, j.upcoming.map((c) => jRow(ctx, c, { today: j.today, lead: c.due.slice(5) }))));
  }

  // 问题线：同一问题上的判断按时间排开，看立场怎么变
  if (j.threads.length) {
    body.append(ui.section('问题线', `${j.threads.length} 条 · 同一个问题上我的判断按时间排开`));
    const wrap = h('div');
    for (const t of j.threads) {
      const card = h('div.card.kb-th', { id: 'th-' + t.question }, [
        h('div.row', { style: { alignItems: 'baseline' } }, [h('h3.grow', {}, t.question), h('span.muted', {}, `${t.items.length} 条 · ${t.items[0].date.slice(5)} → ${t.last.slice(5)}`)]),
        h('div.stance', {}, [h('span.muted', {}, '现在：'), t.stance]),
        t.shift ? h('div.kb-shift', {}, [t.changed ? h('b', {}, '立场变了 · ') : null, t.shift]) : null,
        h('div.kb-tl', {}, t.items.map((c, i) => jRow(ctx, c, { today: j.today, chg: t.changed && i === t.items.length - 1 }))),
      ]);
      wrap.append(card);
    }
    body.append(wrap);
    if (focus) {
      const el = document.getElementById('th-' + focus);
      if (el) setTimeout(() => { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); el.classList.add('kb-j', 'flash'); setTimeout(() => el.classList.remove('flash'), 1800); }, 80);
    }
  }

  if (j.open.length) {
    body.append(ui.section('开放问题', `${j.open.length} 个还没想清楚的`));
    body.append(h('div.card', {}, j.open.map((c) => jRow(ctx, c, { today: j.today }))));
  }

  // 其余判断：按类型 / 状态筛
  if (j.singles.length) {
    const list = h('div.card');
    const legend = h('div.kb-legend');
    const draw = () => {
      const cs = j.singles.filter((c) => (!fType || c.type === fType) && (!fStatus || (fStatus === 'reviewed' ? c.status !== 'open' : c.status === 'open')));
      list.replaceChildren(...(cs.length ? cs.map((c) => jRow(ctx, c, { today: j.today })) : [h('div.muted', {}, '没有符合的')]));
      legend.replaceChildren(
        ...[['', '全部'], ['观点', '观点'], ['预测', '预测'], ['评价', '评价']].map(([v, l]) => h('button' + (fType === v ? '.on' : ''), { onclick: () => { fType = v; draw(); } }, [v ? h('span.kb-dot', { style: { background: TYPE_COLOR[v] } }) : null, l])),
        h('span.sp'),
        ...[['', '不限'], ['open', '未复查'], ['reviewed', '复查过']].map(([v, l]) => h('button' + (fStatus === v ? '.on' : ''), { onclick: () => { fStatus = v; draw(); } }, l)));
    };
    body.append(ui.section('其他判断', `${j.singles.length} 条 · 还没串进问题线的`), legend, list);
    draw();
  }
}

// 依据材料：从看过的材料里搜着引用，或自己贴链接 / 写一句来源；都不填 = 没有源
function sourcePicker(ctx) {
  const { api, h } = ctx;
  const picked = [];
  const chips = h('div.sel');
  const hits = h('div.hits', { style: { display: 'none' } });
  const q = h('input', { placeholder: '引用看过的材料：搜标题 / 关键词（深读、调研、读书、学习计划、收藏的信息）', style: { width: '100%' } });
  const own = h('input', { placeholder: '或自己指定源：贴链接 / 写一句出处，回车加入', style: { width: '100%' } });
  const draw = () => chips.replaceChildren(...(picked.length ? picked.map((x, i) => h('span.chip', { title: x.url || x.title }, [
    h('span', {}, (x.sub_name ? x.sub_name + ' · ' : x.sid ? '' : '自定 · ') + (x.title || x.url)),
    h('button', { title: '移除', onclick: () => { picked.splice(i, 1); draw(); } }, '×')])) : [h('span.muted', { style: { fontSize: '12.5px' } }, '依据材料：暂无（可不填）')]));
  const add = (x) => { if (!picked.some((p) => (p.sid && p.sid === x.sid) || (!p.sid && (p.url || p.title) === (x.url || x.title)))) picked.push(x); draw(); };
  let timer = 0, seq = 0;
  const search = async () => {
    const my = ++seq;
    const rs = await api.get('/api/kb/materials?limit=12&q=' + encodeURIComponent(q.value.trim()));
    if (my !== seq) return;
    hits.style.display = '';
    hits.replaceChildren(...(rs.length ? rs.map((r) => h('div.hit', { onclick: () => { add({ sid: r.sid, title: r.title, url: r.url, link: r.link, sub: r.sub, sub_name: r.sub_name }); hits.style.display = 'none'; q.value = ''; } }, [
      h('div', {}, r.title), h('div.muted', {}, `${r.sub_name} · ${r.date}${r.context ? ' · ' + r.context : ''}`)])) : [h('div.hit.muted', {}, '没找到，换个词，或在下面直接贴链接')]));
  };
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 200); });
  q.addEventListener('focus', () => { if (!hits.childElementCount) search(); else hits.style.display = ''; });
  own.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || !own.value.trim()) return;
    ev.preventDefault();
    const v = own.value.trim();
    add(/^https?:\/\/\S+$/.test(v) ? { url: v, title: v } : { title: v });
    own.value = '';
  });
  draw();
  return {
    el: h('div.kb-src', {}, [chips, q, hits, own]),
    value: () => {   // 没按回车的自定源也算上
      if (own.value.trim()) { const v = own.value.trim(); add(/^https?:\/\/\S+$/.test(v) ? { url: v, title: v } : { title: v }); own.value = ''; }
      return picked.map(({ sub_name, ...x }) => x);
    },
  };
}

function srcList(h, srcs) {
  if (!srcs?.length) return null;
  return h('div.kb-srcs', {}, [h('b', { style: { color: 'var(--muted)', fontSize: '12px' } }, '依据材料'),
    ...srcs.map((x) => (x.link || x.url) ? h('a', { href: x.link || x.url, ...(x.link ? {} : { target: '_blank', rel: 'noopener' }) }, x.title || x.url) : h('span', {}, x.title))]);
}

// 一行判断，点开看原话、Agent 评价、复查记录，并能复查
function jRow(ctx, c, { open = false, today, chg = false, lead = '' } = {}) {
  const { h } = ctx;
  const detail = h('div');
  const row = h('div.kb-jr' + (chg ? '.chg' : ''), { onclick: () => toggle() }, [
    h('span.d', { title: c.date }, lead || c.date.slice(5)), typeTag(h, c.type),
    h('span.c', {}, [c.claim, c.confidence ? h('span.muted', { style: { fontSize: '12px', marginLeft: '6px' } }, '信心' + c.confidence) : null]),
    statusTag(h, c, today),
  ]);
  const toggle = () => detail.replaceChildren(...(detail.childElementCount ? [] : [jDetail(ctx, c, today)]));
  if (open) toggle();
  return h('div', {}, [row, detail]);
}

function jDetail(ctx, c, today) {
  const { api, h, toast } = ctx;
  const norm = (x) => (x || '').replace(/\s/g, '');
  const e = c.eval;
  const a = c.agent;
  const due = c.due && c.due <= today;
  const ctxText = c.sources?.length ? (c.context || '').split('\n').filter((l) => !l.startsWith('依据材料：')).join('\n') : c.context;
  const agentBox = h('div');
  const showAgent = (x) => agentBox.replaceChildren(x ? h('div.kb-ag', {}, [
    h('div', {}, [h('b', {}, `Agent 参考结论：${x.suggest}`), h('span.muted', {}, ` · 对照了 ${x.n_evidence ?? 0} 条之后的材料和判断${x.stale ? ' · 有新材料，可重新对照' : ''}`)]),
    x.why ? h('div', {}, x.why) : null,
    x.ask ? h('div.muted', {}, '问问自己：' + x.ask) : null,
  ]) : '');
  showAgent(a);
  const note = h('textarea', { placeholder: c.type === '疑问' ? '现在怎么想？想清楚了就写结论' : '复查笔记：为什么还成立 / 哪里要改 / 新的看法是什么（修正、推翻时必填，会作为新判断进问题线）' });
  const date = h('input', { type: 'date', title: '改到哪天再看' });
  const send = async (verdict) => {
    if ((verdict === 'revised' || verdict === 'overturned') && !note.value.trim()) { toast('修正 / 推翻时写一句新的看法', true); note.focus(); return; }
    if (verdict === 'snooze' && !date.value) { toast('先选一个日期', true); date.focus(); return; }
    await api.post('/api/kb/judgments/review', { sid: c.sid, verdict, note: note.value, due: verdict === 'snooze' ? date.value : '' });
    toast('已记录复查');
    ctx.refresh();
  };
  const recheck = async (btn) => {
    btn.disabled = true; btn.textContent = 'Agent 对照中…';
    try { showAgent(await api.post('/api/kb/judgments/recheck', { sid: c.sid })); } catch (err) { toast('没对照成：' + (err.message || err), true); }
    btn.disabled = false; btn.textContent = '让 Agent 对照新材料';
  };
  const verdicts = c.type === '疑问' ? [['resolved', '想清楚了'], ['pending', '还没想清楚']]
    : [['holds', '仍成立'], ['revised', '要修正'], ['overturned', '推翻了'], ['pending', '还看不出']];
  return h('div.kb-jd', { onclick: (ev) => ev.stopPropagation() }, [
    c.mine && !norm(c.mine).startsWith(norm(c.claim).slice(0, 16)) ? h('blockquote', {}, c.mine) : null,
    ctxText ? h('div.muted.clamp2', {}, '针对：' + ctxText) : null,
    srcList(h, c.sources),
    e ? h('div.kb-ev', {}, [h('b', {}, `依据 ${e.strength}`), h('span', {}, e.basis), h('b', {}, '反方'), h('span', {}, e.counter), h('b', {}, '怎么验证'), h('span', {}, e.verify)]) : null,
    agentBox,
    c.reviews.length ? h('ul.kb-hist', {}, c.reviews.map((r) => h('li', {}, `${r.at.slice(0, 10)} · ${r.verdict_name}${r.due ? ' → ' + r.due : ''}${r.note ? '：' + r.note : ''}`))) : null,
    h('div.row', { style: { flexWrap: 'wrap', gap: '4px 12px', marginTop: '6px', fontSize: '12.5px', color: 'var(--muted)' } }, [
      h('span', {}, [c.sub_name, ' · ', srcLink(h, c)]),
      c.due ? h('span', {}, (due ? '该复查了（' : '下次复查 ') + c.due + (due ? '）' : '')) : null,
      c.horizon_days ? h('span', {}, `预计 ${c.horizon_days} 天见分晓`) : null,
      c.thread ? h('a', { href: jLink(c.thread) }, '问题线：' + c.thread) : null,
      h('span.grow'),
      h('span.kb-cl', { style: { marginTop: 0 } }, c.concepts.map((x) => h('a', { href: cLink(x) }, x))),
    ]),
    c.status === 'overturned' || c.status === 'resolved' ? null : h('div.kb-rv', {}, [
      note,
      ...verdicts.map(([v, l]) => h('button' + (v === 'holds' || v === 'resolved' ? '' : '.outline'), { onclick: () => send(v) }, l)),
      h('span.grow'),
      date, h('button.ghost', { onclick: () => send('snooze') }, '改期'),
      h('button.ghost', { onclick: (ev) => recheck(ev.currentTarget) }, '让 Agent 对照新材料'),
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
