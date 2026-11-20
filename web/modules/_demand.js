// 需求图谱：产品雷达里的创业公司 / PH 日榜 / 增长 Case，逐产品拆成「目标用户 · 场景 · 痛点 · 产品 · 增长手段」，按场景大小聚成 大场景 → 子场景 → 产品。
// 两个视图：地图（一眼看大家在打什么痛点）、打法矩阵（大场景 × 增长手段，看每类痛点主要靠什么增长）。
const CSS = `
.dm-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 10px 0; }
.dm-bar button, .dm-chip { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.dm-bar button.on, .dm-chip.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.dm-sp { flex: 1; } .dm-m { color: var(--muted); font-size: 13px; }
.dm-map { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 12px; align-items: start; }
.dm-g { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; }
.dm-g h2 { font: 700 17px/1.5 var(--serif); margin: 0; } .dm-g h2 small { font: 12px var(--font); color: var(--muted); margin-left: 6px; }
.dm-sum { font-size: 13.5px; margin: 6px 0 8px; padding: 6px 10px; background: var(--bg); border-radius: 8px; }
.dm-s { border-top: 1px solid var(--line); padding: 8px 0 4px; }
.dm-s b { font-size: 14px; } .dm-s .p { font-size: 12.5px; color: var(--muted); margin: 1px 0 5px; }
.dm-pills { display: flex; flex-wrap: wrap; gap: 4px; }
.dm-pill { font-size: 12.5px; border: 1px solid var(--line-2); border-radius: 6px; padding: 1px 8px; cursor: pointer; background: var(--bg); }
.dm-pill:hover, .dm-pill.cur { border-color: var(--accent); color: var(--accent); }
.dm-pill.dim { opacity: .25; }
.dm-pill i { font-style: normal; font-size: 10.5px; margin-right: 3px; color: var(--muted); }
.dm-tg { display: flex; gap: 3px; flex-wrap: wrap; margin-top: 4px; }
.dm-tg span { font-size: 11px; background: var(--bg-2); color: var(--accent); border-radius: 4px; padding: 0 6px; }
.dm-tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.dm-tbl th, .dm-tbl td { border: 1px solid var(--line); padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums; }
.dm-tbl th { background: var(--panel); font-size: 12px; font-weight: 600; min-width: 72px; } .dm-tbl th:first-child { min-width: 110px; } .dm-tbl th:nth-child(2) { min-width: 40px; } .dm-tbl td:first-child, .dm-tbl th:first-child { text-align: left; position: sticky; left: 0; background: var(--panel); }
.dm-tbl td.c { cursor: pointer; }
.dm-wrap { overflow-x: auto; }
.dm-card { position: fixed; right: 0; top: 0; bottom: 0; width: min(440px, 100vw); background: var(--panel); border-left: 1px solid var(--line); box-shadow: -6px 0 24px rgba(0,0,0,.12); padding: 16px 18px; overflow-y: auto; z-index: 30; }
.dm-card h3 { font: 700 18px/1.4 var(--serif); margin: 0 0 4px; }
.dm-card dt { font-size: 12px; color: var(--muted); margin-top: 10px; } .dm-card dd { margin: 2px 0 0; font-size: 14px; line-height: 1.6; }
.dm-card .x { float: right; cursor: pointer; font-size: 18px; color: var(--muted); }
.dm-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 12px 0; }
@media (max-width: 720px) { .dm-map { grid-template-columns: 1fr; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const SRC = { '创业公司': '创', 'PH 日榜': 'PH', '增长 Case': '案' };
const STAGE = { start: '正在启动', extract: '逐个产品抽取需求卡', taxonomy: '建场景分类', assign: '把产品归到子场景', summary: '写大场景总结', done: '完成' };

export async function renderDemand(el, ctx, tabs) {
  {
    const { api, h, ui } = ctx;
    let D, view = 'map', tac = '', src = '', cur = '', timer;
    const body = h('div');
    el.append(h('style', {}, CSS), ui.pageHead('产品雷达 · 需求图谱', '创业公司 / PH 日榜 / 增长 Case 拆成「谁、在什么场景、有什么痛点、靠什么增长」，按场景大小聚成图谱', []), tabs, body);

    const fit = (c) => (!tac || c.tactics.includes(tac)) && (!src || c.sources.includes(src));
    const pill = (k) => { const c = D.cards[k]; return `<span class="dm-pill ${fit(c) ? '' : 'dim'} ${cur === k ? 'cur' : ''}" data-k="${E(k)}" title="${E(c.scene)}"><i>${c.sources.map((s) => SRC[s]).join('')}</i>${E(c.name)}</span>`; };
    const subTac = (sb) => {
      const n = {};
      sb.products.forEach((k) => D.cards[k].tactics.forEach((t) => { n[t] = (n[t] || 0) + 1; }));
      return Object.entries(n).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([t, c]) => `<span>${E(t)} ×${c}</span>`).join('');
    };

    const bar = () => {
      const n = (f) => Object.values(D.cards).filter(f).length;
      return `<div class="dm-bar"><button data-v="map" class="${view === 'map' ? 'on' : ''}">场景地图</button><button data-v="mat" class="${view === 'mat' ? 'on' : ''}">打法矩阵</button><span class="dm-m">&nbsp;来源</span>
${Object.keys(SRC).map((s) => `<span class="dm-chip ${src === s ? 'on' : ''}" data-s="${s}">${s} ${n((c) => c.sources.includes(s))}</span>`).join('')}<span class="dm-m">&nbsp;增长手段</span>
${D.graph.tactics.map((t) => `<span class="dm-chip ${tac === t ? 'on' : ''}" data-t="${E(t)}">${E(t)} ${n((c) => c.tactics.includes(t))}</span>`).join('')}
<span class="dm-sp"></span><span class="dm-m">${D.graph.n} 个产品 · ${new Date(D.graph.updated * 1000).toLocaleDateString()} 更新</span><button data-run="graph">重新聚类</button></div>`;
    };

    const map = () => `<div class="dm-map">${D.graph.scenes.map((sc) => {
      const all = sc.subs.flatMap((sb) => sb.products);
      const hit = all.filter((k) => fit(D.cards[k])).length;
      if ((tac || src) && !hit) return '';
      return `<div class="dm-g"><h2>${E(sc.name)}<small>${all.length} 个产品${tac || src ? `，命中 ${hit}` : ''}</small></h2><div class="dm-m">${E(sc.desc)}</div>
${sc.summary ? `<div class="dm-sum">${E(sc.summary)}</div>` : ''}
${sc.subs.map((sb) => `<div class="dm-s"><b>${E(sb.name)}</b> <span class="dm-m">${sb.products.length}</span><div class="p">${E(sb.pain)}</div><div class="dm-pills">${sb.products.map(pill).join('')}</div><div class="dm-tg">${subTac(sb)}</div></div>`).join('')}</div>`;
    }).join('')}</div>`;

    const matrix = () => {
      const T = D.graph.tactics;
      const rows = D.graph.scenes.map((sc) => {
        const ks = sc.subs.flatMap((sb) => sb.products).filter((k) => !src || D.cards[k].sources.includes(src));
        return { sc, ks, cnt: T.map((t) => ks.filter((k) => D.cards[k].tactics.includes(t))) };
      });
      const mx = Math.max(1, ...rows.flatMap((r) => r.cnt.map((x) => x.length)));
      return `<div class="dm-m">格子里是「这个大场景里用了这种增长手段的产品数」，越深越集中；点格子在地图里看是哪些产品。只统计材料里讲了增长手段的产品（PH 简介通常没讲，空白不代表没做）。</div>
<div class="dm-wrap"><table class="dm-tbl"><tr><th>大场景</th><th>产品</th>${T.map((t) => `<th>${E(t)}</th>`).join('')}</tr>
${rows.map((r) => `<tr><td>${E(r.sc.name)}</td><td>${r.ks.length}</td>${r.cnt.map((x, i) => `<td class="c" data-cell="${E(T[i])}" style="background:rgba(120,90,200,${(x.length / mx * 0.7).toFixed(2)})">${x.length || ''}</td>`).join('')}</tr>`).join('')}</table></div>`;
    };

    const card = (k) => {
      const c = D.cards[k];
      return `<div class="dm-card"><span class="x" data-x>×</span><h3>${E(c.name)}</h3><div class="dm-m">${c.sources.map(E).join(' · ')}${c.track ? ' · ' + E(c.track) : ''}</div>
<dl><dt>目标用户</dt><dd>${E(c.user)}</dd><dt>场景</dt><dd>「${E(c.scene)}」</dd><dt>痛点</dt><dd>${E(c.pain)}</dd><dt>产品</dt><dd>${E(c.product)}</dd>
<dt>增长核心手段</dt><dd>${c.growth ? E(c.growth) : '<span class="dm-m">材料里没讲增长</span>'}${c.tactics.length ? `<div class="dm-tg">${c.tactics.map((t) => `<span>${E(t)}</span>`).join('')}</div>` : ''}</dd>
${c.links.length ? `<dt>来源</dt><dd>${c.links.map((l) => `<a href="${E(l[1])}" target="_blank" rel="noopener">${E(l[0])}</a>`).join(' · ')}</dd>` : ''}</dl></div>`;
    };

    const paint = () => {
      if (!D.graph) {
        const s = D.status;
        body.innerHTML = `<div class="dm-run"><b>${s.running ? '正在生成' : '还没有图谱'}</b>
<div class="dm-m">${s.running ? `${E(STAGE[s.stage] || s.stage)} ${s.done || 0} / ${s.total || 0} · 已花费 $${s.cost || 0}` : s.error ? E(s.error) : `已抽取 ${D.n_cards} 张需求卡。`}</div>
${s.running ? '' : '<p><button data-run="all" class="primary">生成（读产品雷达全部产品，约几分钟）</button></p>'}</div>`;
        if (s.running) timer = setTimeout(load, 4000);
        return;
      }
      const keep = window.scrollY;
      body.innerHTML = bar() + (view === 'map' ? map() : matrix()) + (cur ? card(cur) : '');
      window.scrollTo(0, keep);
    };
    const load = async () => { if (!el.isConnected) return; D = await api.get('/api/demand/graph'); paint(); };

    body.onclick = async (e) => {
      const t = e.target, d = t.closest('[data-v],[data-s],[data-t],[data-k],[data-x],[data-cell],[data-run]');
      if (!d) return;
      const ds = d.dataset;
      if (ds.v) view = ds.v;
      else if (ds.s !== undefined) src = src === ds.s ? '' : ds.s;
      else if (ds.t !== undefined) tac = tac === ds.t ? '' : ds.t;
      else if (ds.k) cur = ds.k;
      else if (ds.x !== undefined) cur = '';
      else if (ds.cell) { tac = ds.cell; view = 'map'; }
      else if (ds.run) { await api.post('/api/demand/run' + (ds.run === 'graph' ? '?graph_only=true' : ''), {}); return load(); }
      paint();
    };
    await load();
  }
}
