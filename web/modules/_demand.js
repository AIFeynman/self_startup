// 需求图谱：产品雷达里的创业公司 / PH 日榜 / 增长 Case，逐产品拆成「目标用户 · 场景 · 痛点 · 产品 · 增长手段」。
// 图谱三层：用户场景 → 痛点 → 公司（叶子 = 公司知识卡）；点场景 / 痛点展开，侧栏看这一层的增长方式聚合，点叶子看公司卡。
// 另有「打法矩阵」：场景 × 增长手段。
const CSS = `
.dm-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 10px 0; }
.dm-bar button, .dm-chip { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.dm-bar button.on, .dm-chip.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.dm-sp { flex: 1; } .dm-m { color: var(--muted); font-size: 13px; }
.dm-wrap { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
.dm-cv { position: relative; height: 78vh; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius); background: radial-gradient(circle at 50% 50%, var(--panel), var(--bg)); cursor: grab; touch-action: none; user-select: none; }
.dm-cv.drag { cursor: grabbing; }
.dm-vp { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.dm-vp svg { position: absolute; left: 0; top: 0; overflow: visible; pointer-events: none; }
.dm-vp path { fill: none; stroke-width: 1.4; opacity: .38; }
.dm-vp path.hl { opacity: .95; stroke-width: 2.4; }
.dm-n { position: absolute; left: 0; top: 0; box-sizing: border-box; border-radius: 999px; padding: 0 12px; display: flex; align-items: center; gap: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; font-size: 13px; color: var(--text); border: 1.5px solid hsl(var(--h) 55% 50% / .55); background: hsl(var(--h) 60% 55% / .13); }
.dm-n:hover, .dm-n.cur { border-color: hsl(var(--h) 65% 45%); background: hsl(var(--h) 60% 55% / .3); }
.dm-n.dim { opacity: .16; }
.dm-n.r { border-radius: 50%; justify-content: center; font: 700 18px var(--serif); background: var(--dark); color: var(--bg); border: 0; padding: 0; white-space: normal; text-align: center; }
.dm-n.d { font: 700 16px var(--serif); background: hsl(var(--h) 55% 42%); color: #fff; border: 0; }
.dm-n.s { font-weight: 700; background: hsl(var(--h) 60% 55% / .26); }
.dm-n.p small { color: var(--muted); font-size: 11px; }
.dm-n.l { font-size: 12.5px; padding: 0 9px; background: var(--bg); }
.dm-n i { font-style: normal; font-size: 10.5px; color: var(--muted); }
.dm-n em { font-style: normal; font-size: 10.5px; color: hsl(var(--h) 55% 38%); }
.dm-zoom { position: absolute; right: 10px; bottom: 10px; display: flex; gap: 4px; }
.dm-zoom button { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); font-size: 16px; cursor: pointer; color: var(--text); }
.dm-hint { position: absolute; left: 12px; bottom: 10px; font-size: 12px; color: var(--muted); pointer-events: none; }
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
const PW = { d: 130, s: 170, p: 190, l: 150 }, PH = { d: 38, s: 34, p: 32, l: 24 };
const BM_COLOR = {};

export async function renderDemand(el, ctx, tabs) {
  const { api, h, ui } = ctx;
  let D, view = 'graph', tac = '', src = '', bm = '', mat = 'tac', side = null, timer, tf = null, moved = false;
  const open = new Set();
  const body = h('div');
  el.append(h('style', {}, CSS), ui.pageHead('产品雷达 · 需求图谱', '用户场景 → 痛点 → 公司：看大家在打什么痛点、怎么做增长；叶子是公司知识卡', []), tabs, body);

  const fit = (c) => (!tac || c.tactics.includes(tac)) && (!src || c.sources.includes(src)) && (!bm || c.bm_type === bm);
  const filtering = () => !!(tac || src || bm);
  const hits = (sb) => sb.products.filter((k) => fit(D.cards[k]));
  const tacCount = (keys) => {
    const n = {};
    keys.forEach((k) => D.cards[k].tactics.forEach((t) => { n[t] = (n[t] || 0) + 1; }));
    return Object.entries(n).sort((a, b) => b[1] - a[1]);
  };
  const bmCount = (keys) => {
    const n = {};
    keys.forEach((k) => { const t = D.cards[k].bm_type; if (t) n[t] = (n[t] || 0) + 1; });
    return Object.entries(n).sort((a, b) => b[1] - a[1]);
  };

  const bar = () => {
    const n = (f) => Object.values(D.cards).filter(f).length;
    return `<div class="dm-bar"><button data-v="graph" class="${view === 'graph' ? 'on' : ''}">图谱</button><button data-v="mat" class="${view === 'mat' ? 'on' : ''}">打法矩阵</button><span class="dm-m">&nbsp;来源</span>
${Object.keys(SRC).map((s) => `<span class="dm-chip ${src === s ? 'on' : ''}" data-s="${s}">${s} ${n((c) => c.sources.includes(s))}</span>`).join('')}<span class="dm-m">&nbsp;增长手段</span>
${D.graph.tactics.map((t) => `<span class="dm-chip ${tac === t ? 'on' : ''}" data-t="${E(t)}">${E(t)} ${n((c) => c.tactics.includes(t))}</span>`).join('')}
<span class="dm-m">&nbsp;商业模式</span>
${(D.graph.models || []).map((t) => `<span class="dm-chip ${bm === t ? 'on' : ''}" data-b="${E(t)}">${E(t)} ${n((c) => c.bm_type === t)}</span>`).join('')}
<span class="dm-sp"></span><button data-open="all">全部展开到痛点</button><button data-open="none">收起</button><span class="dm-m">${D.graph.n} 个公司 · ${new Date(D.graph.updated * 1000).toLocaleDateString()}</span><button data-run="graph">重新聚类</button></div>`;
  };

  const hue = (i, n) => Math.round((i * 360) / Math.max(n, 1) + 205) % 360;
  const layout = () => {
    const doms = D.graph.domains?.length ? D.graph.domains : [{ id: 'D0', name: '全部', desc: '', scenes: D.graph.scenes.map((x) => x.id) }];
    const T = [];
    let wt = 0;
    const wPain = (n) => Math.max(1, n * 0.62);
    doms.forEach((dm, di) => {
      const d = { dm, h: hue(di, doms.length), scenes: [], w: 0 };
      for (const id of dm.scenes) {
        const sc = D.graph.scenes.find((x) => x.id === id);
        if (!sc) continue;
        const sn = { sc, pains: [], w: 0 };
        for (const sb of sc.subs) {
          const ks = filtering() ? hits(sb) : sb.products;
          if (filtering() && !ks.length) continue;
          const isOpen = open.has(sb.id) || filtering();
          const pn = { sb, ks: isOpen ? ks : [], n: ks.length, isOpen, w: isOpen ? wPain(ks.length) : 1 };
          sn.pains.push(pn);
          sn.w += pn.w;
        }
        if (!sn.pains.length) continue;
        sn.w += 0.5;
        d.scenes.push(sn);
        d.w += sn.w;
      }
      if (!d.scenes.length) return;
      d.w += 1.4;
      wt += d.w;
      T.push(d);
    });
    const pS = Math.max(560, wt * 6.8), sS = pS - 230, dS = sS - 200, lS = pS + 190 + 60;
    const per = (Math.PI * 2) / wt;
    const pol = (a, r) => [Math.cos(a) * r, Math.sin(a) * r];
    const nodes = [], links = [];
    const link = (a1, r1, a2, r2, h, hl) => {
      const rm = (r1 + r2) / 2, [x1, y1] = pol(a1, r1), [x2, y2] = pol(a2, r2), [c1x, c1y] = pol(a1, rm), [c2x, c2y] = pol(a2, rm);
      links.push({ d: `M${x1.toFixed(1)},${y1.toFixed(1)} C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`, h, hl });
    };
    const put = (cls, a, r, h, html, attrs, w, hh, dim, cur) => nodes.push({ cls, a, r, h, html, attrs, w, hh, dim, cur });
    let a0 = -Math.PI / 2;
    for (const d of T) {
      const da = d.w * per, dMid = a0 + da / 2;
      put('d', dMid, dS, d.h, E(d.dm.name), `data-dom="${d.dm.id}"`, PW.d, PH.d, false, side?.dom === d.dm.id);
      link(0, 62, dMid, dS, d.h, side?.dom === d.dm.id);
      let a1 = a0 + 0.7 * per;
      for (const sn of d.scenes) {
        const sa = sn.w * per, sMid = a1 + sa / 2;
        put('s', sMid, sS, d.h, `${E(sn.sc.name)}`, `data-sc="${sn.sc.id}" title="${E(sn.sc.desc)}"`, PW.s, PH.s, false, side?.sc === sn.sc.id);
        link(dMid, dS + PW.d, sMid, sS, d.h, side?.sc === sn.sc.id);
        let a2 = a1 + 0.25 * per;
        for (const pn of sn.pains) {
          const pa = pn.w * per, pMid = a2 + pa / 2;
          const tg = tacCount(pn.sb.products)[0];
          put('p', pMid, pS, d.h, `${pn.isOpen ? '▾' : '▸'} ${E(pn.sb.name)} <small>${pn.n}</small>`, `data-sb="${pn.sb.id}" title="${E(pn.sb.pain)}${tg ? '｜主要增长：' + E(tg[0]) : ''}"`, PW.p, PH.p, false, side?.sb === pn.sb.id);
          link(sMid, sS + PW.s, pMid, pS, d.h, side?.sb === pn.sb.id);
          pn.ks.forEach((k, i) => {
            const la = a2 + ((i + 0.5) / pn.ks.length) * pa, c = D.cards[k];
            put('l', la, lS, d.h, `<i>${c.sources.map((x) => SRC[x]).join('')}</i>${E(c.name)}${c.bm_type ? ` <em>${E(c.bm_type)}</em>` : ''}`, `data-k="${E(k)}" title="${E(c.scene)}"`, PW.l + 40, PH.l, !fit(c), side?.k === k);
            link(pMid, pS + PW.p, la, lS, d.h, side?.k === k);
          });
          a2 += pa;
        }
        a1 += sa;
      }
      a0 += da;
    }
    return { nodes, links, R: lS + PW.l + 80 };
  };

  const view0 = (R, cv) => { const k = Math.min(cv.clientWidth, cv.clientHeight) / (2 * R + 40); return { k, x: cv.clientWidth / 2, y: cv.clientHeight / 2 }; };
  const applyTf = () => { const vp = body.querySelector('.dm-vp'); if (vp && tf) vp.style.transform = `translate(${tf.x}px,${tf.y}px) scale(${tf.k})`; };
  const graph = () => {
    const L = layout();
    L.nodes.sort((a, b) => (a.cur ? 1 : 0) - (b.cur ? 1 : 0));
    const pn = (n) => {
      const [x, y] = [Math.cos(n.a) * n.r, Math.sin(n.a) * n.r], flip = Math.cos(n.a) < 0, deg = (n.a * 180) / Math.PI + (flip ? 180 : 0);
      return `<div class="dm-n ${n.cls} ${n.dim ? 'dim' : ''} ${n.cur ? 'cur' : ''}" ${n.attrs} style="--h:${n.h};width:${n.w}px;height:${n.hh}px;margin:${-n.hh / 2}px 0 0 ${flip ? -n.w : 0}px;transform-origin:${flip ? '100%' : '0'} 50%;transform:translate(${x.toFixed(1)}px,${y.toFixed(1)}px) rotate(${deg.toFixed(2)}deg)">${n.html}</div>`;
    };
    const R = L.R;
    return `<div class="dm-cv" data-rad="${R}"><div class="dm-vp"><svg width="1" height="1">${L.links.map((l) => `<path class="${l.hl ? 'hl' : ''}" stroke="hsl(${l.h} 60% 45%)" d="${l.d}"/>`).join('')}</svg>
<div class="dm-n r" style="width:124px;height:124px;margin:-62px 0 0 -62px">用户需求<br>图谱</div>${L.nodes.map(pn).join('')}</div>
<div class="dm-hint">拖动平移 · 滚轮缩放 · 点痛点展开公司</div><div class="dm-zoom"><button data-z="in">＋</button><button data-z="out">－</button><button data-z="fit" title="适应窗口">⤢</button></div></div>`;
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

  const tacBars = (keys, kind = 'tac') => {
    const t = kind === 'tac' ? tacCount(keys) : bmCount(keys), mx = t[0]?.[1] || 1;
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
<dt>商业模式</dt><dd>${c.bm ? E(c.bm) : '<span class="dm-m">暂无</span>'}${c.bm_type ? `<div class="dm-tg"><span>${E(c.bm_type)}</span></div>` : ''}</dd>
<dt>增长核心手段</dt><dd>${c.growth ? E(c.growth) : '<span class="dm-m">材料里没讲增长</span>'}${c.tactics.length ? `<div class="dm-tg">${c.tactics.map((t) => `<span>${E(t)}</span>`).join('')}</div>` : ''}</dd>
${c.links.length ? `<dt>来源</dt><dd>${c.links.map((l) => `<a href="${E(l[1])}" target="_blank" rel="noopener">${E(l[0])}</a>`).join(' · ')}</dd>` : ''}</dl>`;
    } else if (side.sb) {
      const sb = D.graph.scenes.flatMap((s) => s.subs).find((x) => x.id === side.sb);
      inner = `<h3>${E(sb.name)}</h3><div class="dm-m">${E(sb.pain)}</div><dl><dt>大家怎么增长</dt><dd>${sb.growth ? E(sb.growth) : '<span class="dm-m">增长材料较少</span>'}</dd><dt>增长手段分布（${sb.products.length} 家）</dt><dd>${tacBars(sb.products)}</dd><dt>商业模式分布</dt><dd>${tacBars(sb.products, 'bm')}</dd><dt>公司</dt><dd>${list(sb.products)}</dd></dl>`;
    } else if (side.dom) {
      const dm = D.graph.domains.find((x) => x.id === side.dom), scs = dm.scenes.map((i) => D.graph.scenes.find((x) => x.id === i)).filter(Boolean), all = scs.flatMap((sc) => sc.subs.flatMap((sb) => sb.products));
      inner = `<h3>${E(dm.name)}</h3><div class="dm-m">${E(dm.desc)}</div><dl><dt>增长手段分布（${all.length} 家）</dt><dd>${tacBars(all)}</dd><dt>商业模式分布</dt><dd>${tacBars(all, 'bm')}</dd><dt>场景</dt><dd>${scs.map((sc) => `<div class="dm-li" data-sc="${sc.id}">${E(sc.name)} <span class="dm-m">${sc.subs.reduce((a, sb) => a + sb.products.length, 0)}</span></div>`).join('')}</dd></dl>`;
    } else {
      const sc = D.graph.scenes.find((x) => x.id === side.sc);
      const all = sc.subs.flatMap((sb) => sb.products);
      inner = `<h3>${E(sc.name)}</h3><div class="dm-m">${E(sc.desc)}</div><dl><dt>痛点与增长总结</dt><dd>${E(sc.summary)}</dd><dt>增长手段分布（${all.length} 家）</dt><dd>${tacBars(all)}</dd><dt>商业模式分布</dt><dd>${tacBars(all, 'bm')}</dd><dt>痛点</dt><dd>${sc.subs.map((sb) => `<div class="dm-li" data-sb="${sb.id}">${E(sb.name)} <span class="dm-m">${sb.products.length}</span></div>`).join('')}</dd></dl>`;
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
    const wy = window.scrollY;
    body.innerHTML = bar() + (view === 'graph' ? graph() : matrix()) + sidebar();
    const cv = body.querySelector('.dm-cv');
    if (cv) { if (!tf) tf = view0(+cv.dataset.rad, cv); applyTf(); }
    window.scrollTo(0, wy);
  };
  const load = async () => {
    if (!el.isConnected) return;
    D = await api.get('/api/demand/graph');
    paint();
  };

  body.onclick = async (e) => {
    if (moved) { moved = false; return; }
    const d = e.target.closest('[data-v],[data-s],[data-t],[data-b],[data-mat],[data-dom],[data-z],[data-k],[data-x],[data-cell],[data-run],[data-sc],[data-sb],[data-open]');
    if (!d) return;
    const ds = d.dataset;
    if (ds.v) view = ds.v;
    else if (ds.s !== undefined) src = src === ds.s ? '' : ds.s;
    else if (ds.t !== undefined) tac = tac === ds.t ? '' : ds.t;
    else if (ds.b !== undefined) bm = bm === ds.b ? '' : ds.b;
    else if (ds.mat) mat = ds.mat;
    else if (ds.dom) side = { dom: ds.dom };
    else if (ds.z) {
      const cv = body.querySelector('.dm-cv'), k0 = tf.k;
      if (ds.z === 'fit') tf = view0(+cv.dataset.rad, cv);
      else { const k = Math.min(2.5, Math.max(0.12, k0 * (ds.z === 'in' ? 1.3 : 1 / 1.3))), cx = cv.clientWidth / 2, cy = cv.clientHeight / 2; tf = { ...tf, k, x: cx - (cx - tf.x) * (k / k0), y: cy - (cy - tf.y) * (k / k0) }; }
      return applyTf();
    }
    else if (ds.k) side = { k: ds.k };
    else if (ds.x !== undefined) side = null;
    else if (ds.cell) { if (mat === 'tac') tac = ds.cell; else bm = ds.cell; view = 'graph'; }
    else if (ds.open) { open.clear(); if (ds.open === 'all') D.graph.scenes.forEach((sc) => sc.subs.forEach((sb) => open.add(sb.id))); }
    else if (ds.sb) { open.has(ds.sb) ? open.delete(ds.sb) : open.add(ds.sb); side = { sb: ds.sb }; }
    else if (ds.sc) side = { sc: ds.sc };
    else if (ds.run) { await api.post('/api/demand/run' + (ds.run === 'graph' ? '?graph_only=true' : ''), {}); return load(); }
    paint();
  };
  let drag = null;
  body.addEventListener('pointerdown', (e) => {
    const cv = e.target.closest('.dm-cv');
    if (!cv || e.target.closest('.dm-zoom')) return;
    drag = { x: e.clientX, y: e.clientY, tx: tf.x, ty: tf.y, cv };
  });
  window.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!moved && Math.hypot(dx, dy) < 5) return;
    moved = true;
    drag.cv.classList.add('drag');
    tf.x = drag.tx + dx; tf.y = drag.ty + dy;
    applyTf();
  });
  window.addEventListener('pointerup', () => { drag?.cv.classList.remove('drag'); drag = null; setTimeout(() => { moved = false; }, 0); });
  body.addEventListener('wheel', (e) => {
    const cv = e.target.closest('.dm-cv');
    if (!cv || !tf) return;
    e.preventDefault();
    const r = cv.getBoundingClientRect(), k0 = tf.k, k = Math.min(2.5, Math.max(0.12, k0 * Math.exp(-e.deltaY * 0.0015))), px = e.clientX - r.left, py = e.clientY - r.top;
    tf.x = px - (px - tf.x) * (k / k0); tf.y = py - (py - tf.y) * (k / k0); tf.k = k;
    applyTf();
  }, { passive: false });
  await load();
}
