// 需求图谱：产品雷达里的创业公司 / PH 日榜 / 增长 Case，逐产品拆成「目标用户 · 场景 · 痛点 · 产品 · 增长手段」。
// 图谱三层：用户场景 → 痛点 → 公司（叶子 = 公司知识卡）；点场景 / 痛点展开，侧栏看这一层的增长方式聚合，点叶子看公司卡。
// 另有「打法矩阵」：场景 × 增长手段。
const CSS = `
.dm-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 10px 0; }
.dm-bar button, .dm-chip { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.dm-bar button.on, .dm-chip.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.dm-sp { flex: 1; } .dm-m { color: var(--muted); font-size: 13px; }
.dm-wrap { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
.dm-gr { position: relative; }
.dm-gr svg { position: absolute; left: 0; top: 0; pointer-events: none; }
.dm-gr path { fill: none; stroke: var(--line-2); stroke-width: 1.3; }
.dm-gr path.hl { stroke: var(--accent); stroke-width: 1.8; }
.dm-n { position: absolute; box-sizing: border-box; border-radius: 8px; padding: 3px 9px; cursor: pointer; font-size: 13px; line-height: 1.35; overflow: hidden; border: 1px solid var(--line-2); background: var(--bg); }
.dm-n:hover, .dm-n.cur { border-color: var(--accent); }
.dm-n.dim { opacity: .22; }
.dm-n.s { background: var(--dark); color: var(--bg); font-weight: 700; font-size: 14px; border-color: var(--dark); display: flex; align-items: center; }
.dm-n.s small { font-weight: 400; opacity: .75; margin-left: 6px; font-size: 12px; }
.dm-n.p b { font-weight: 600; } .dm-n.p small { color: var(--muted); font-size: 11.5px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dm-n.l { display: flex; align-items: center; white-space: nowrap; text-overflow: ellipsis; padding: 0 9px; }
.dm-n.l i { font-style: normal; font-size: 10.5px; color: var(--muted); margin-right: 5px; }
.dm-side { position: fixed; right: 0; top: 0; bottom: 0; width: min(440px, 100vw); background: var(--panel); border-left: 1px solid var(--line); box-shadow: -6px 0 24px rgba(0,0,0,.12); padding: 16px 18px; overflow-y: auto; z-index: 30; }
.dm-side h3 { font: 700 18px/1.4 var(--serif); margin: 0 0 4px; }
.dm-side dt { font-size: 12px; color: var(--muted); margin-top: 10px; } .dm-side dd { margin: 2px 0 0; font-size: 14px; line-height: 1.6; }
.dm-side .x { float: right; cursor: pointer; font-size: 18px; color: var(--muted); }
.dm-tg { display: flex; gap: 3px; flex-wrap: wrap; margin-top: 4px; }
.dm-tg span { font-size: 11px; background: var(--bg-2); color: var(--accent); border-radius: 4px; padding: 0 6px; }
.dm-bars div { display: grid; grid-template-columns: 130px 1fr 24px; gap: 6px; align-items: center; font-size: 12.5px; margin: 2px 0; }
.dm-bars i { display: block; height: 8px; border-radius: 3px; background: var(--accent); }
.dm-li { font-size: 13.5px; padding: 3px 0; cursor: pointer; } .dm-li:hover { color: var(--accent); }
.dm-tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.dm-tbl th, .dm-tbl td { border: 1px solid var(--line); padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums; }
.dm-tbl th { background: var(--panel); font-size: 12px; font-weight: 600; min-width: 72px; } .dm-tbl th:first-child { min-width: 110px; } .dm-tbl th:nth-child(2) { min-width: 40px; }
.dm-tbl td:first-child, .dm-tbl th:first-child { text-align: left; position: sticky; left: 0; background: var(--panel); }
.dm-tbl td.c { cursor: pointer; }
.dm-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 12px 0; }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const SRC = { '创业公司': '创', 'PH 日榜': 'PH', '增长 Case': '案' };
const STAGE = { start: '正在启动', extract: '逐个产品抽取需求卡', taxonomy: '建场景和痛点分类', assign: '把产品归到痛点', summary: '写场景和痛点的增长总结', done: '完成' };
const W = { s: 210, p: 270, l: 190 }, GAP = 44, HL = 28, HP = 46, HS = 40;

export async function renderDemand(el, ctx, tabs) {
  const { api, h, ui } = ctx;
  let D, view = 'graph', tac = '', src = '', side = null, timer;
  const open = new Set();
  const body = h('div');
  el.append(h('style', {}, CSS), ui.pageHead('产品雷达 · 需求图谱', '用户场景 → 痛点 → 公司：看大家在打什么痛点、怎么做增长；叶子是公司知识卡', []), tabs, body);

  const fit = (c) => (!tac || c.tactics.includes(tac)) && (!src || c.sources.includes(src));
  const filtering = () => !!(tac || src);
  const hits = (sb) => sb.products.filter((k) => fit(D.cards[k]));
  const tacCount = (keys) => {
    const n = {};
    keys.forEach((k) => D.cards[k].tactics.forEach((t) => { n[t] = (n[t] || 0) + 1; }));
    return Object.entries(n).sort((a, b) => b[1] - a[1]);
  };

  const bar = () => {
    const n = (f) => Object.values(D.cards).filter(f).length;
    return `<div class="dm-bar"><button data-v="graph" class="${view === 'graph' ? 'on' : ''}">图谱</button><button data-v="mat" class="${view === 'mat' ? 'on' : ''}">打法矩阵</button><span class="dm-m">&nbsp;来源</span>
${Object.keys(SRC).map((s) => `<span class="dm-chip ${src === s ? 'on' : ''}" data-s="${s}">${s} ${n((c) => c.sources.includes(s))}</span>`).join('')}<span class="dm-m">&nbsp;增长手段</span>
${D.graph.tactics.map((t) => `<span class="dm-chip ${tac === t ? 'on' : ''}" data-t="${E(t)}">${E(t)} ${n((c) => c.tactics.includes(t))}</span>`).join('')}
<span class="dm-sp"></span><button data-open="all">全部展开到痛点</button><button data-open="none">收起</button><span class="dm-m">${D.graph.n} 个公司 · ${new Date(D.graph.updated * 1000).toLocaleDateString()}</span><button data-run="graph">重新聚类</button></div>`;
  };

  const graph = () => {
    const nodes = [], links = [];
    let y = 0;
    const leafBox = (k, x, py) => { nodes.push({ cls: 'l', x, y: py, w: W.l, h: HL, k, dim: !fit(D.cards[k]) }); return py + HL / 2; };
    for (const sc of D.graph.scenes) {
      const pains = sc.subs.filter((sb) => !filtering() || hits(sb).length);
      if (!pains.length) continue;
      const y0 = y, pc = [];
      for (const sb of pains) {
        const isOpen = open.has(sb.id) || filtering();
        const ks = filtering() ? hits(sb) : sb.products;
        const yp = y;
        let center;
        if (isOpen) {
          const cs = ks.map((k) => { const c = leafBox(k, W.s + W.p + GAP * 2, y); y += HL + 4; return { k, c }; });
          center = (cs[0].c + cs[cs.length - 1].c) / 2;
          y = Math.max(y, yp + HP + 4);
          cs.forEach(({ k, c }) => links.push({ x1: W.s + GAP + W.p, y1: center, x2: W.s + W.p + GAP * 2, y2: c, hl: side?.k === k }));
        } else { center = yp + HP / 2; y = yp + HP + 4; }
        nodes.push({ cls: 'p', x: W.s + GAP, y: center - HP / 2, w: W.p, h: HP, sb, n: ks.length, isOpen });
        pc.push(center);
      }
      const sy = (pc[0] + pc[pc.length - 1]) / 2;
      nodes.push({ cls: 's', x: 0, y: sy - HS / 2, w: W.s, h: HS, sc, n: pains.reduce((a, sb) => a + (filtering() ? hits(sb).length : sb.products.length), 0) });
      pc.forEach((c) => links.push({ x1: W.s, y1: sy, x2: W.s + GAP, y2: c, hl: side?.sc === sc.id }));
      y = Math.max(y, y0 + HS) + 14;
    }
    const wd = W.s + W.p + W.l + GAP * 2 + 20;
    const path = (l) => `<path class="${l.hl ? 'hl' : ''}" d="M${l.x1},${l.y1} C${l.x1 + GAP / 2},${l.y1} ${l.x2 - GAP / 2},${l.y2} ${l.x2},${l.y2}"/>`;
    const node = (n) => {
      const st = `left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px`;
      if (n.cls === 's') return `<div class="dm-n s ${side?.sc === n.sc.id ? 'cur' : ''}" style="${st}" data-sc="${n.sc.id}" title="${E(n.sc.desc)}">${E(n.sc.name)}<small>${n.n}</small></div>`;
      if (n.cls === 'p') {
        const tg = tacCount(n.sb.products).slice(0, 2).map(([t, c]) => `${E(t)}×${c}`).join(' · ');
        return `<div class="dm-n p ${side?.sb === n.sb.id ? 'cur' : ''}" style="${st}" data-sb="${n.sb.id}" title="${E(n.sb.pain)}"><b>${n.isOpen ? '▾' : '▸'} ${E(n.sb.name)}</b> <span class="dm-m">${n.n}</span><small>${tg || '增长材料较少'}</small></div>`;
      }
      const c = D.cards[n.k];
      return `<div class="dm-n l ${n.dim ? 'dim' : ''} ${side?.k === n.k ? 'cur' : ''}" style="${st}" data-k="${E(n.k)}" title="${E(c.scene)}"><i>${c.sources.map((s) => SRC[s]).join('')}</i>${E(c.name)}</div>`;
    };
    return `<div class="dm-wrap" style="max-height:78vh"><div class="dm-gr" style="width:${wd}px;height:${y}px"><svg width="${wd}" height="${y}">${links.map(path).join('')}</svg>${nodes.map(node).join('')}</div></div>`;
  };

  const matrix = () => {
    const T = D.graph.tactics;
    const rows = D.graph.scenes.map((sc) => {
      const ks = sc.subs.flatMap((sb) => sb.products).filter((k) => !src || D.cards[k].sources.includes(src));
      return { sc, ks, cnt: T.map((t) => ks.filter((k) => D.cards[k].tactics.includes(t))) };
    });
    const mx = Math.max(1, ...rows.flatMap((r) => r.cnt.map((x) => x.length)));
    return `<div class="dm-m">格子是「这个场景里用了这种增长手段的公司数」，越深越集中；点格子回到图谱，只看用了这种手段的公司。只统计材料里讲了增长手段的公司（PH 简介通常没讲，空白不代表没做）。</div>
<div class="dm-wrap"><table class="dm-tbl"><tr><th>用户场景</th><th>公司</th>${T.map((t) => `<th>${E(t)}</th>`).join('')}</tr>
${rows.map((r) => `<tr><td>${E(r.sc.name)}</td><td>${r.ks.length}</td>${r.cnt.map((x, i) => `<td class="c" data-cell="${E(T[i])}" style="background:rgba(120,90,200,${(x.length / mx * 0.7).toFixed(2)})">${x.length || ''}</td>`).join('')}</tr>`).join('')}</table></div>`;
  };

  const tacBars = (keys) => {
    const t = tacCount(keys), mx = t[0]?.[1] || 1;
    return t.length ? `<div class="dm-bars">${t.map(([n, c]) => `<div><span>${E(n)}</span><i style="width:${Math.round(c / mx * 100)}%"></i><span>${c}</span></div>`).join('')}</div>` : '<span class="dm-m">材料里没讲增长手段</span>';
  };
  const list = (keys) => keys.map((k) => `<div class="dm-li" data-k="${E(k)}">${D.cards[k].sources.map((s) => `<span class="dm-m">${SRC[s]}</span>`).join('')} ${E(D.cards[k].name)} <span class="dm-m">· ${E(D.cards[k].scene)}</span></div>`).join('');

  const sidebar = () => {
    if (!side) return '';
    let inner;
    if (side.k) {
      const c = D.cards[side.k];
      inner = `<h3>${E(c.name)}</h3><div class="dm-m">${c.sources.map(E).join(' · ')}${c.track ? ' · ' + E(c.track) : ''}</div>
<dl><dt>目标用户</dt><dd>${E(c.user)}</dd><dt>场景</dt><dd>「${E(c.scene)}」</dd><dt>痛点</dt><dd>${E(c.pain)}</dd><dt>产品</dt><dd>${E(c.product)}</dd>
<dt>增长核心手段</dt><dd>${c.growth ? E(c.growth) : '<span class="dm-m">材料里没讲增长</span>'}${c.tactics.length ? `<div class="dm-tg">${c.tactics.map((t) => `<span>${E(t)}</span>`).join('')}</div>` : ''}</dd>
${c.links.length ? `<dt>来源</dt><dd>${c.links.map((l) => `<a href="${E(l[1])}" target="_blank" rel="noopener">${E(l[0])}</a>`).join(' · ')}</dd>` : ''}</dl>`;
    } else if (side.sb) {
      const sb = D.graph.scenes.flatMap((s) => s.subs).find((x) => x.id === side.sb);
      inner = `<h3>${E(sb.name)}</h3><div class="dm-m">${E(sb.pain)}</div><dl><dt>大家怎么增长</dt><dd>${sb.growth ? E(sb.growth) : '<span class="dm-m">增长材料较少</span>'}</dd><dt>增长手段分布（${sb.products.length} 家）</dt><dd>${tacBars(sb.products)}</dd><dt>公司</dt><dd>${list(sb.products)}</dd></dl>`;
    } else {
      const sc = D.graph.scenes.find((x) => x.id === side.sc);
      const all = sc.subs.flatMap((sb) => sb.products);
      inner = `<h3>${E(sc.name)}</h3><div class="dm-m">${E(sc.desc)}</div><dl><dt>痛点与增长总结</dt><dd>${E(sc.summary)}</dd><dt>增长手段分布（${all.length} 家）</dt><dd>${tacBars(all)}</dd><dt>痛点</dt><dd>${sc.subs.map((sb) => `<div class="dm-li" data-sb="${sb.id}">${E(sb.name)} <span class="dm-m">${sb.products.length}</span></div>`).join('')}</dd></dl>`;
    }
    return `<div class="dm-side"><span class="x" data-x>×</span>${inner}</div>`;
  };

  const paint = () => {
    if (!D.graph) {
      const s = D.status;
      body.innerHTML = `<div class="dm-run"><b>${s.running ? '正在生成' : '还没有图谱'}</b>
<div class="dm-m">${s.running ? `${E(STAGE[s.stage] || s.stage)} ${s.done || 0} / ${s.total || 0} · 已花费 $${s.cost || 0}` : s.error ? E(s.error) : `已抽取 ${D.n_cards} 张需求卡。`}</div>
${s.running ? '' : '<p><button data-run="all" class="primary">生成（读产品雷达全部公司，约几分钟）</button></p>'}</div>`;
      if (s.running) timer = setTimeout(load, 4000);
      return;
    }
    const wrap = body.querySelector('.dm-wrap'), sl = wrap?.scrollLeft || 0, st = wrap?.scrollTop || 0, wy = window.scrollY;
    body.innerHTML = bar() + (view === 'graph' ? graph() : matrix()) + sidebar();
    const w2 = body.querySelector('.dm-wrap');
    if (w2) { w2.scrollLeft = sl; w2.scrollTop = st; }
    window.scrollTo(0, wy);
  };
  const load = async () => {
    if (!el.isConnected) return;
    D = await api.get('/api/demand/graph');
    paint();
  };

  body.onclick = async (e) => {
    const d = e.target.closest('[data-v],[data-s],[data-t],[data-k],[data-x],[data-cell],[data-run],[data-sc],[data-sb],[data-open]');
    if (!d) return;
    const ds = d.dataset;
    if (ds.v) view = ds.v;
    else if (ds.s !== undefined) src = src === ds.s ? '' : ds.s;
    else if (ds.t !== undefined) tac = tac === ds.t ? '' : ds.t;
    else if (ds.k) side = { k: ds.k };
    else if (ds.x !== undefined) side = null;
    else if (ds.cell) { tac = ds.cell; view = 'graph'; }
    else if (ds.open) { open.clear(); if (ds.open === 'all') D.graph.scenes.forEach((sc) => sc.subs.forEach((sb) => open.add(sb.id))); }
    else if (ds.sb) { open.has(ds.sb) ? open.delete(ds.sb) : open.add(ds.sb); side = { sb: ds.sb }; }
    else if (ds.sc) side = { sc: ds.sc };
    else if (ds.run) { await api.post('/api/demand/run' + (ds.run === 'graph' ? '?graph_only=true' : ''), {}); return load(); }
    paint();
  };
  await load();
}
