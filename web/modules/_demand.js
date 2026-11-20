// 需求图谱：产品雷达里的创业公司 / PH 日榜 / 增长 Case，逐产品拆成「目标用户 · 场景 · 痛点 · 产品 · 商业模式 · 增长手段」。
// 三栏下钻：领域 / 场景 → 痛点 → 公司知识卡（字号固定，不用缩放拖动）；另有「打法矩阵」：场景 × 增长手段 / 商业模式。
const CSS = `
.dm-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 10px 0; }
.dm-bar button, .dm-chip { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.dm-bar button.on, .dm-chip.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.dm-sp { flex: 1; } .dm-m { color: var(--muted); font-size: 13px; }
.dm-dot { display: inline-block; background: #e5484d; color: #fff; font: 700 11px/18px var(--font); min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; text-align: center; margin-left: 6px; vertical-align: 1px; }
.dm-note { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid #e5484d; border-radius: 8px; padding: 6px 12px; font-size: 13px; margin: 8px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.dm-3 { display: grid; grid-template-columns: 230px 310px minmax(0, 1fr); gap: 12px; align-items: start; }
.dm-3 > div { border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); padding: 8px; overflow-y: auto; max-height: 76vh; }
.dm-dh { font-weight: 700; font-size: 13px; margin: 10px 6px 2px; }
.dm-it { padding: 7px 10px; border-radius: 8px; cursor: pointer; font-size: 15px; border-left: 4px solid transparent; }
.dm-it:hover, .dm-it.on { background: var(--bg-2); } .dm-it.on { font-weight: 700; }
.dm-it small { color: var(--muted); font-weight: 400; margin-left: 4px; }
.dm-it .p { display: block; font-size: 12.5px; color: var(--muted); font-weight: 400; margin-top: 2px; line-height: 1.5; }
.dm-box { font-size: 13.5px; background: var(--bg); border-radius: 8px; padding: 8px 10px; margin: 2px 2px 8px; line-height: 1.6; }
.dm-co { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px; margin: 0 0 10px; }
.dm-co h4 { margin: 0 0 4px; font: 700 16px/1.4 var(--serif); }
.dm-co dl { margin: 0; font-size: 14px; line-height: 1.6; } .dm-co dt { color: var(--muted); font-size: 12px; margin-top: 6px; } .dm-co dd { margin: 0; }
.dm-tg { display: flex; gap: 3px; flex-wrap: wrap; margin-top: 3px; }
.dm-tg span, .dm-chp { font-size: 12px; background: var(--bg-2); color: var(--accent); border-radius: 5px; padding: 0 7px; margin: 2px 4px 2px 0; display: inline-block; }
.dm-chp.b, .dm-tg .b { color: var(--muted); }
.dm-bars div { display: grid; grid-template-columns: 130px 1fr 24px; gap: 6px; align-items: center; font-size: 12.5px; margin: 2px 0; }
.dm-bars i { display: block; height: 8px; border-radius: 3px; background: var(--accent); }
.dm-wrap { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
.dm-tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.dm-tbl th, .dm-tbl td { border: 1px solid var(--line); padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums; }
.dm-tbl th { background: var(--panel); font-size: 12px; font-weight: 600; min-width: 72px; } .dm-tbl th:first-child { min-width: 110px; } .dm-tbl th:nth-child(2) { min-width: 40px; }
.dm-tbl td:first-child, .dm-tbl th:first-child { text-align: left; position: sticky; left: 0; background: var(--panel); }
.dm-tbl td.c { cursor: pointer; }
.dm-run { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; margin: 12px 0; }
.dm-cq { container-type: inline-size; }
@container (max-width: 900px) { .dm-3 { grid-template-columns: 210px minmax(0, 1fr); } .dm-3 > div:nth-child(3) { grid-column: 1 / -1; max-height: none; } }
@container (max-width: 560px) { .dm-3 { grid-template-columns: 1fr; } .dm-3 > div { max-height: none; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const SRC = { '创业公司': '创', 'PH 日榜': 'PH', '增长 Case': '案' };
const STAGE = { start: '正在启动', extract: '逐个产品抽取需求卡', model: '补商业模式', arr: '补收入规模', taxonomy: '建场景和痛点分类', assign: '把产品归到痛点', summary: '写场景和痛点的增长总结', done: '完成' };

export async function renderDemand(el, ctx, tabs) {
  const { api, h, ui } = ctx;
  let D, view = 'graph', tac = '', src = '', bm = '', mat = 'tac', S = '', P = '', timer;
  const fresh = new Set();
  const SEEN = 'dm-seen';
  const seen = new Set((() => { try { return JSON.parse(localStorage.getItem(SEEN) || '[]'); } catch { return []; } })());
  const saveSeen = () => { try { localStorage.setItem(SEEN, JSON.stringify([...seen])); } catch { /* 无痕模式 */ } };
  const isNew = (k) => !!D.cards[k]?.added && !seen.has(k);
  const newN = (keys) => keys.filter(isNew).length;
  const dot = (n) => (n ? `<b class="dm-dot" title="${n} 个新项目">${n}</b>` : '');
  const body = h('div.dm-cq');
  el.append(h('style', {}, CSS), ui.pageHead('产品雷达 · 需求图谱', '领域 / 场景 → 痛点 → 公司：看大家在打什么痛点、怎么做增长、怎么赚钱', []), tabs, body);

  const fit = (c) => (!tac || c.tactics.includes(tac)) && (!src || c.sources.includes(src)) && (!bm || c.bm_type === bm);
  const filtering = () => !!(tac || src || bm);
  const hits = (sb) => (filtering() ? sb.products.filter((k) => fit(D.cards[k])) : sb.products);
  const sceneKeys = (sc) => sc.subs.flatMap(hits);
  const count = (keys, f) => {
    const n = {};
    keys.forEach((k) => [].concat(f(D.cards[k]) || []).forEach((t) => { if (t) n[t] = (n[t] || 0) + 1; }));
    return Object.entries(n).sort((a, b) => b[1] - a[1]);
  };
  const tacCount = (keys) => count(keys, (c) => c.tactics);
  const bmCount = (keys) => count(keys, (c) => c.bm_type);
  const bars = (keys, kind = 'tac') => {
    const t = kind === 'tac' ? tacCount(keys) : bmCount(keys), mx = t[0]?.[1] || 1;
    return t.length ? `<div class="dm-bars">${t.map(([n, c]) => `<div><span>${E(n)}</span><i style="width:${Math.round(c / mx * 100)}%"></i><span>${c}</span></div>`).join('')}</div>` : '<span class="dm-m">材料里没讲</span>';
  };

  const notice = () => {
    const nn = newN(Object.keys(D.cards)), run = D.status.running;
    if (!nn && !D.pending && !run) return '';
    return `<div class="dm-note">${run ? `<span>同步中：${E(STAGE[D.status.stage] || D.status.stage)} ${D.status.done || 0} / ${D.status.total || 0}</span>` : ''}${D.pending && !run ? `<span>雷达里有 <b>${D.pending}</b> 个新产品还没收录</span><button data-run="sync">同步新项目</button>` : ''}${nn ? `<span><b class="dm-dot" style="margin:0">${nn}</b> 个新收录的项目未读</span><button data-seen="all">全部标为已读</button>` : ''}</div>`;
  };
  const bar = () => {
    const n = (f) => Object.values(D.cards).filter(f).length;
    return `<div class="dm-bar"><button data-v="graph" class="${view === 'graph' ? 'on' : ''}">图谱</button><button data-v="mat" class="${view === 'mat' ? 'on' : ''}">打法矩阵</button><span class="dm-m">&nbsp;来源</span>
${Object.keys(SRC).map((s) => `<span class="dm-chip ${src === s ? 'on' : ''}" data-s="${s}">${s} ${n((c) => c.sources.includes(s))}</span>`).join('')}<span class="dm-m">&nbsp;增长手段</span>
${D.graph.tactics.map((t) => `<span class="dm-chip ${tac === t ? 'on' : ''}" data-t="${E(t)}">${E(t)} ${n((c) => c.tactics.includes(t))}</span>`).join('')}
<span class="dm-m">&nbsp;商业模式</span>
${(D.graph.models || []).map((t) => `<span class="dm-chip ${bm === t ? 'on' : ''}" data-b="${E(t)}">${E(t)} ${n((c) => c.bm_type === t)}</span>`).join('')}
<span class="dm-sp"></span><span class="dm-m">${D.graph.n} 个公司 · ${new Date(D.graph.updated * 1000).toLocaleDateString()}</span><button data-run="graph">重新聚类</button></div>`;
  };

  const hue = (i, n) => Math.round((i * 360) / Math.max(n, 1) + 205) % 360;
  const domains = () => (D.graph.domains?.length ? D.graph.domains : [{ id: 'D0', name: '全部', desc: '', scenes: D.graph.scenes.map((x) => x.id) }]);
  const sceneById = (id) => D.graph.scenes.find((x) => x.id === id);
  const visibleScenes = () => D.graph.scenes.filter((sc) => sceneKeys(sc).length);
  const fixSel = () => {
    const vs = visibleScenes();
    if (!vs.find((x) => x.id === S)) S = vs[0]?.id || '';
    const sc = sceneById(S), ps = sc ? sc.subs.filter((sb) => hits(sb).length) : [];
    if (!ps.find((x) => x.id === P)) P = ps[0]?.id || '';
  };

  const company = (k) => {
    const c = D.cards[k], nw = fresh.has(k) || isNew(k);
    return `<div class="dm-co"><h4>${E(c.name)}${nw ? '<b class="dm-dot">新</b>' : ''}</h4><div class="dm-m">${c.sources.map(E).join(' · ')}${c.track ? ' · ' + E(c.track) : ''}</div>
<dl><dt>目标用户</dt><dd>${E(c.user)}</dd><dt>场景</dt><dd>「${E(c.scene)}」</dd><dt>痛点</dt><dd>${E(c.pain)}</dd><dt>产品</dt><dd>${E(c.product)}</dd>
${c.arr ? `<dt>收入规模</dt><dd>${E(c.arr)}<div class="dm-tg"><span class="b">${c.arr_grade === 'verified' ? '支付渠道验证' : '自述 / 报道，未验证'}</span></div></dd>` : ''}<dt>商业模式</dt><dd>${c.bm ? E(c.bm) : '<span class="dm-m">暂无</span>'}${c.bm_type ? `<div class="dm-tg"><span class="b">${E(c.bm_type)}</span></div>` : ''}</dd>
<dt>增长核心手段</dt><dd>${c.growth ? E(c.growth) : '<span class="dm-m">材料里没讲增长</span>'}${c.tactics.length ? `<div class="dm-tg">${c.tactics.map((t) => `<span>${E(t)}</span>`).join('')}</div>` : ''}</dd>
${c.links.length ? `<dt>来源</dt><dd>${c.links.map((l) => `<a href="${E(l[1])}" target="_blank" rel="noopener">${E(l[0])}</a>`).join(' · ')}</dd>` : ''}</dl></div>`;
  };

  const graph = () => {
    fixSel();
    const doms = domains(), sc = sceneById(S);
    const c1 = doms.map((d, i) => {
      const ss = d.scenes.map(sceneById).filter((x) => x && sceneKeys(x).length);
      if (!ss.length) return '';
      return `<div class="dm-dh" style="color:hsl(${hue(i, doms.length)} 50% 42%)">${E(d.name)}${dot(newN(ss.flatMap((x) => x.subs.flatMap((sb) => sb.products))))}</div>`
        + ss.map((x) => `<div class="dm-it ${x.id === S ? 'on' : ''}" data-sc="${x.id}" style="border-left-color:hsl(${hue(i, doms.length)} 55% 50%)">${E(x.name)}<small>${sceneKeys(x).length}</small>${dot(newN(x.subs.flatMap((sb) => sb.products)))}</div>`).join('');
    }).join('') || '<div class="dm-m" style="padding:10px">没有符合筛选的公司</div>';
    let c2 = '', c3 = '';
    if (sc) {
      const ks = sceneKeys(sc);
      c2 = `${sc.summary ? `<div class="dm-box">${E(sc.summary)}</div>` : ''}`
        + sc.subs.filter((sb) => hits(sb).length).map((sb) => `<div class="dm-it ${sb.id === P ? 'on' : ''}" data-sb="${sb.id}">${E(sb.name)}<small>${hits(sb).length}</small>${dot(newN(sb.products))}<span class="p">${E(sb.pain)}</span>${tacCount(sb.products).slice(0, 2).map((t) => `<span class="dm-chp">${E(t[0])}</span>`).join('')}</div>`).join('');
      const sb = sc.subs.find((x) => x.id === P);
      c3 = sb
        ? `<div class="dm-box"><b>大家怎么增长：</b>${sb.growth ? E(sb.growth) : '<span class="dm-m">增长材料较少</span>'}<div class="dm-m" style="margin-top:4px">${tacCount(hits(sb)).map((t) => `<span class="dm-chp">${E(t[0])} ×${t[1]}</span>`).join('')}${bmCount(hits(sb)).map((t) => `<span class="dm-chp b">${E(t[0])} ×${t[1]}</span>`).join('')}</div></div>${hits(sb).map(company).join('')}`
        : `<div class="dm-box">${E(sc.summary)}</div><div class="dm-m">增长手段分布（${ks.length} 家）</div>${bars(ks)}<div class="dm-m" style="margin-top:8px">商业模式分布</div>${bars(ks, 'bm')}`;
    }
    return `<div class="dm-3"><div>${c1}</div><div>${c2}</div><div>${c3}</div></div>`;
  };

  const matrix = () => {
    const T = mat === 'tac' ? D.graph.tactics : D.graph.models || [], key = (c, t) => (mat === 'tac' ? c.tactics.includes(t) : c.bm_type === t);
    const rows = D.graph.scenes.map((sc) => {
      const ks = sc.subs.flatMap((sb) => sb.products).filter((k) => !src || D.cards[k].sources.includes(src));
      return { sc, ks, cnt: T.map((t) => ks.filter((k) => key(D.cards[k], t))) };
    });
    const mx = Math.max(1, ...rows.flatMap((r) => r.cnt.map((x) => x.length)));
    return `<div class="dm-bar"><button data-mat="tac" class="${mat === 'tac' ? 'on' : ''}">场景 × 增长手段</button><button data-mat="bm" class="${mat === 'bm' ? 'on' : ''}">场景 × 商业模式</button></div>
<div class="dm-m">格子是「这个场景里属于该${mat === 'tac' ? '增长手段' : '商业模式'}的公司数」，越深越集中；点格子回到图谱，只看这一类公司。${mat === 'tac' ? '只统计材料里讲了增长手段的公司（PH 简介通常没讲，空白不代表没做）。' : ''}</div>
<div class="dm-wrap"><table class="dm-tbl"><tr><th>用户场景</th><th>公司</th>${T.map((t) => `<th>${E(t)}</th>`).join('')}</tr>
${rows.map((r) => `<tr><td>${E(r.sc.name)}</td><td>${r.ks.length}</td>${r.cnt.map((x, i) => `<td class="c" data-cell="${E(T[i])}" style="background:rgba(120,90,200,${(x.length / mx * 0.7).toFixed(2)})">${x.length || ''}</td>`).join('')}</tr>`).join('')}</table></div>`;
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
    const wy = window.scrollY;
    body.innerHTML = notice() + bar() + (view === 'graph' ? graph() : matrix());
    window.scrollTo(0, wy);
  };
  const load = async () => {
    if (!el.isConnected) return;
    D = await api.get('/api/demand/graph');
    paint();
    if (D.graph && D.status.running) timer = setTimeout(load, 4000);
  };
  const pick = (sb) => {
    P = sb.id;
    fresh.clear();
    hits(sb).forEach((k) => { if (isNew(k)) { fresh.add(k); seen.add(k); } });
    saveSeen();
  };

  body.onclick = async (e) => {
    const d = e.target.closest('[data-seen],[data-v],[data-s],[data-t],[data-b],[data-mat],[data-cell],[data-run],[data-sc],[data-sb]');
    if (!d) return;
    const ds = d.dataset;
    if (ds.v) view = ds.v;
    else if (ds.s !== undefined) src = src === ds.s ? '' : ds.s;
    else if (ds.t !== undefined) tac = tac === ds.t ? '' : ds.t;
    else if (ds.b !== undefined) bm = bm === ds.b ? '' : ds.b;
    else if (ds.mat) mat = ds.mat;
    else if (ds.run === 'sync') { await api.post('/api/demand/run', {}); return load(); }
    else if (ds.seen) { Object.keys(D.cards).forEach((k) => seen.add(k)); saveSeen(); fresh.clear(); }
    else if (ds.cell) { if (mat === 'tac') tac = ds.cell; else bm = ds.cell; view = 'graph'; }
    else if (ds.sc) { S = ds.sc; P = ''; fixSel(); const sb = sceneById(S).subs.find((x) => x.id === P); if (sb) pick(sb); }
    else if (ds.sb) pick(sceneById(S).subs.find((x) => x.id === ds.sb));
    else if (ds.run) { await api.post('/api/demand/run' + (ds.run === 'graph' ? '?graph_only=true' : ''), {}); return load(); }
    paint();
  };
  await load();
}
