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
.dm-n.p, .dm-n.l { border-radius: 8px; }
.dm-n.r { border-radius: 14px; justify-content: center; font: 700 18px var(--serif); background: var(--dark); color: var(--bg); border: 0; padding: 0; justify-content: center; }
.dm-n.d { font: 700 16px var(--serif); background: hsl(var(--h) 55% 42%); color: #fff; border: 0; }
.dm-n.s { font-weight: 700; font-size: 14px; background: hsl(var(--h) 60% 55% / .26); }
.dm-n.p small { color: var(--muted); font-size: 11px; }
.dm-n.l { font-size: 12.5px; padding: 0 9px; background: var(--bg); }
.dm-n i { font-style: normal; font-size: 10.5px; color: var(--muted); }
.dm-n em { font-style: normal; font-size: 10.5px; color: hsl(var(--h) 55% 38%); }
.dm-dot { flex: none; margin-left: auto; background: #e5484d; color: #fff; font: 700 10.5px/16px var(--font); min-width: 16px; height: 16px; padding: 0 4px; border-radius: 999px; text-align: center; font-style: normal; }
.dm-n.r .dm-dot { margin: 0; }
.dm-note { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid #e5484d; border-radius: 8px; padding: 6px 12px; font-size: 13px; margin: 8px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.dm-zoom { position: absolute; right: 10px; bottom: 10px; display: flex; gap: 4px; }
.dm-zoom button { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); font-size: 16px; cursor: pointer; color: var(--text); }
.dm-hint { position: absolute; left: 12px; bottom: 10px; font-size: 12px; color: var(--muted); pointer-events: none; }
.dm-side { position: fixed; right: 0; top: 0; bottom: 0; width: min(440px, 100vw); background: var(--panel); border-left: 1px solid var(--line); box-shadow: -6px 0 24px rgba(0,0,0,.12); padding: 16px 18px; overflow-y: auto; z-index: 30; }
@media (max-width: 900px) { .dm-side { top: auto; left: 0; width: 100vw; height: 46vh; border-left: 0; border-top: 1px solid var(--line); box-shadow: 0 -6px 24px rgba(0,0,0,.12); } }
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
  let D, view = 'graph', tac = '', src = '', bm = '', mat = 'tac', side = null, timer, tf = null, moved = false, LAY = null, anim = 0;
  const SEEN = 'dm-seen';
  const seen = new Set((() => { try { return JSON.parse(localStorage.getItem(SEEN) || '[]'); } catch { return []; } })());
  const saveSeen = () => { try { localStorage.setItem(SEEN, JSON.stringify([...seen])); } catch { /* 无痕模式 */ } };
  const isNew = (k) => !!D.cards[k]?.added && !seen.has(k);
  const newN = (keys) => keys.filter(isNew).length;
  const dot = (n) => (n ? `<b class="dm-dot" title="${n} 个新项目">${n}</b>` : '');
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
<span class="dm-sp"></span><button data-open="all">展开全部公司</button><button data-open="none">收起公司</button><span class="dm-m">${D.graph.n} 个公司 · ${new Date(D.graph.updated * 1000).toLocaleDateString()}</span><button data-run="graph">重新聚类</button></div>`;
  };

  const hue = (i, n) => Math.round((i * 360) / Math.max(n, 1) + 205) % 360;
  const CW = 250, GAP = 20, YD = 120, YS = 220, YP = 282;
  const layout = () => {
    const doms = D.graph.domains?.length ? D.graph.domains : [{ id: 'D0', name: '全部', desc: '', scenes: D.graph.scenes.map((x) => x.id) }];
    const nodes = [], links = [];
    const put = (cls, x, y, w, h, hue, html, attrs, dim, cur, key) => nodes.push({ cls, x, y, w, h, hue, html, attrs, dim, cur, key });
    const down = (a, b, h, hl) => links.push({ d: `M${a.x},${a.y} C${a.x},${(a.y + b.y) / 2} ${b.x},${(a.y + b.y) / 2} ${b.x},${b.y}`, h, hl });
    const trunk = (px, py, kids, h, hl) => kids.forEach((c) => links.push({ d: `M${px},${py} V${c.y + c.h / 2} H${c.x}`, h, hl }));
    let x = 0, H = 0;
    const dRows = [];
    doms.forEach((dm, di) => {
      const h = hue(di, doms.length), x0 = x;
      let any = false;
      for (const id of dm.scenes) {
        const sc = D.graph.scenes.find((v) => v.id === id);
        if (!sc) continue;
        const pains = sc.subs.filter((sb) => !filtering() || hits(sb).length);
        if (!pains.length) continue;
        any = true;
        put('s', x, YS, CW, 40, h, `${E(sc.name)}${dot(newN(sc.subs.flatMap((sb) => sb.products)))}`, `data-sc="${sc.id}" title="${E(sc.desc)}"`, false, side?.sc === sc.id, sc.id);
        let y = YP;
        const pk = [];
        for (const sb of pains) {
          const ks = filtering() ? hits(sb) : sb.products, isOpen = open.has(sb.id) || filtering(), tg = tacCount(sb.products)[0];
          const pnode = { x: x + 16, y, w: CW - 16, h: 32 };
          put('p', pnode.x, y, pnode.w, 32, h, `${isOpen ? '▾' : '▸'} ${E(sb.name)} <small>${ks.length}</small>${dot(newN(sb.products))}`, `data-sb="${sb.id}" title="${E(sb.pain)}${tg ? '｜主要增长：' + E(tg[0]) : ''}"`, false, side?.sb === sb.id, sb.id);
          pk.push(pnode);
          y += 38;
          if (isOpen) {
            const lk = [];
            for (const k of ks) {
              const c = D.cards[k], lnode = { x: x + 40, y, w: CW - 40, h: 26 };
              put('l', lnode.x, y, lnode.w, 26, h, `<i>${c.sources.map((v) => SRC[v]).join('')}</i>${E(c.name)}${isNew(k) ? '<b class="dm-dot">新</b>' : ''}`, `data-k="${E(k)}" title="${E(c.scene)}｜${E(c.bm_type || '')}"`, !fit(c), side?.k === k, k);
              lk.push(lnode);
              y += 30;
            }
            trunk(x + 28, pnode.y + 32, lk, h, false);
            y += 6;
          }
        }
        trunk(x + 8, YS + 40, pk, h, side?.sc === sc.id);
        
        
        
        H = Math.max(H, y);
        x += CW + GAP;
      }
      if (any) dRows.push({ dm, h, x0, x1: x - GAP });
      x += 14;
    });
    const W = Math.max(x - GAP - 14, CW);
    const root = { x: W / 2, y: 70 };
    for (const r of dRows) {
      const w = Math.max(r.x1 - r.x0, 140), cx = (r.x0 + r.x1) / 2;
      put('d', cx - w / 2, YD, w, 46, r.h, E(r.dm.name) + dot(newN(r.dm.scenes.flatMap((id) => (D.graph.scenes.find((v) => v.id === id)?.subs || []).flatMap((sb) => sb.products)))), `data-dom="${r.dm.id}"`, false, side?.dom === r.dm.id, r.dm.id);
      down({ x: root.x, y: root.y }, { x: cx, y: YD }, r.h, side?.dom === r.dm.id);
      for (const n of nodes.filter((v) => v.cls === 's' && v.x >= r.x0 && v.x <= r.x1)) down({ x: cx, y: YD + 46 }, { x: n.x + CW / 2, y: YS }, r.h, side?.sc === n.key);
    }
    return { nodes, links: links.filter((l) => l.d), W, H: H + 20 };
  };

  const nodeCss = (n) => `left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px`;
  const view0 = (cv) => { const k = Math.min(0.9, Math.max(0.16, (cv.clientWidth - 24) / (LAY.W + 40))); return { k, x: (cv.clientWidth - LAY.W * k) / 2, y: 12 }; };
  const applyTf = () => { const vp = body.querySelector('.dm-vp'); if (vp && tf) vp.style.transform = `translate(${tf.x}px,${tf.y}px) scale(${tf.k})`; };
  const graph = () => {
    const L = layout();
    LAY = L;
    const order = L.nodes.map((n, i) => i).sort((x, y) => (L.nodes[x].cur ? 1 : 0) - (L.nodes[y].cur ? 1 : 0));
    const pn = (i) => { const n = L.nodes[i]; return `<div class="dm-n ${n.cls} ${n.dim ? 'dim' : ''} ${n.cur ? 'cur' : ''}" ${n.attrs} style="--h:${n.hue};${nodeCss(n)}">${n.html}</div>`; };
    return `<div class="dm-cv"><div class="dm-vp"><svg width="1" height="1">${L.links.map((l) => `<path class="${l.hl ? 'hl' : ''}" stroke="hsl(${l.h} 60% 45%)" d="${l.d}"/>`).join('')}</svg>
<div class="dm-n r" style="left:${L.W / 2 - 80}px;top:20px;width:160px;height:50px">用户需求图谱</div>${order.map(pn).join('')}</div>
<div class="dm-hint">拖动平移 · 滚轮缩放 · 点节点聚焦并看详情</div><div class="dm-zoom"><button data-z="in">＋</button><button data-z="out">－</button><button data-z="fit" title="适应窗口">⤢</button></div></div>`;
  };

  const ease = (t) => 1 - (1 - t) ** 3;
  const animateTo = (t1, ms = 400) => {
    cancelAnimationFrame(anim);
    const t0 = { ...tf }, t = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t) / ms), e = ease(p);
      tf = { k: t0.k + (t1.k - t0.k) * e, x: t0.x + (t1.x - t0.x) * e, y: t0.y + (t1.y - t0.y) * e };
      applyTf();
      if (p < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  };
  const KMIN = { d: 0.5, s: 0.6, p: 0.85, l: 0.95 };
  const focus = (key) => {
    const cv = body.querySelector('.dm-cv'), n = LAY?.nodes.find((v) => v.key === key);
    if (!cv || !n) return;
    const rc = cv.getBoundingClientRect(), wide = innerWidth > 900, k = Math.min(2.5, Math.max(tf.k, KMIN[n.cls]));
    const visW = wide && side ? Math.max(280, Math.min(rc.right, innerWidth - 440) - rc.left) : cv.clientWidth;
    animateTo({ k, x: visW / 2 - (n.x + n.w / 2) * k, y: (!wide && side ? cv.clientHeight * 0.18 : cv.clientHeight * 0.22) - n.y * k });
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
${c.arr ? `<dt>收入规模</dt><dd>${E(c.arr)}<div class="dm-tg"><span>${c.arr_grade === 'verified' ? '支付渠道验证' : '自述 / 报道，未验证'}</span></div></dd>` : ''}<dt>商业模式</dt><dd>${c.bm ? E(c.bm) : '<span class="dm-m">暂无</span>'}${c.bm_type ? `<div class="dm-tg"><span>${E(c.bm_type)}</span></div>` : ''}</dd>
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
    body.innerHTML = notice() + bar() + (view === 'graph' ? graph() : matrix()) + sidebar();
    const cv = body.querySelector('.dm-cv');
    if (cv) { if (!tf) tf = view0(cv); applyTf(); }
    window.scrollTo(0, wy);
  };
  const load = async () => {
    if (!el.isConnected) return;
    D = await api.get('/api/demand/graph');
    paint();
    if (D.graph && D.status.running) timer = setTimeout(load, 4000);
  };

  body.onclick = async (e) => {
    if (moved) { moved = false; return; }
    const d = e.target.closest('[data-seen],[data-v],[data-s],[data-t],[data-b],[data-mat],[data-dom],[data-z],[data-k],[data-x],[data-cell],[data-run],[data-sc],[data-sb],[data-open]');
    if (!d) return;
    const ds = d.dataset;
    if (ds.v) view = ds.v;
    else if (ds.s !== undefined) src = src === ds.s ? '' : ds.s;
    else if (ds.t !== undefined) tac = tac === ds.t ? '' : ds.t;
    else if (ds.b !== undefined) bm = bm === ds.b ? '' : ds.b;
    else if (ds.mat) mat = ds.mat;
    else if (ds.dom) side = { dom: ds.dom };
    else if (ds.run === 'sync') { await api.post('/api/demand/run', {}); return load(); }
    else if (ds.z) {
      const cv = body.querySelector('.dm-cv'), k0 = tf.k;
      if (ds.z === 'fit') return animateTo(view0(cv));
      { const k = Math.min(2.5, Math.max(0.12, k0 * (ds.z === 'in' ? 1.3 : 1 / 1.3))), cx = cv.clientWidth / 2, cy = cv.clientHeight / 2; tf = { ...tf, k, x: cx - (cx - tf.x) * (k / k0), y: cy - (cy - tf.y) * (k / k0) }; }
      return applyTf();
    }
    else if (ds.seen) { Object.keys(D.cards).forEach((k) => seen.add(k)); saveSeen(); }
    else if (ds.k) { side = { k: ds.k }; seen.add(ds.k); saveSeen(); }
    else if (ds.x !== undefined) side = null;
    else if (ds.cell) { if (mat === 'tac') tac = ds.cell; else bm = ds.cell; view = 'graph'; }
    else if (ds.open) { open.clear(); if (ds.open === 'all') D.graph.scenes.forEach((sc) => sc.subs.forEach((sb) => open.add(sb.id))); }
    else if (ds.sb) { open.has(ds.sb) ? open.delete(ds.sb) : open.add(ds.sb); side = { sb: ds.sb }; }
    else if (ds.sc) side = { sc: ds.sc };
    else if (ds.run) { await api.post('/api/demand/run' + (ds.run === 'graph' ? '?graph_only=true' : ''), {}); return load(); }
    paint();
    const key = ds.k || ds.sb || ds.sc || ds.dom;
    if (key && view === 'graph') focus(key);
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
