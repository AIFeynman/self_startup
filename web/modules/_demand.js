import { annotate, loadRatings } from './_annotate.js';
// 产品需求（原需求图谱）：知识库的子标签，由 kb.js 在 #kb/demand 路由下调用 demandTab(body, ctx, 查询)；顶部主搜索框的输入走返回的 search。
// 数据是产品雷达里的创业公司 / PH 日榜 / 增长 Case，逐产品拆成「目标用户 · 场景 · 痛点 · 产品 · 商业模式 · 增长手段」。
// 三栏下钻：领域 / 场景 → 痛点 → 公司知识卡（字号固定，不用缩放拖动）；另有「打法矩阵」：场景 × 增长手段 / 商业模式。
const CSS = `
.dm-size { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--line-2); }
.dm-size.mid { color: var(--accent); border-color: var(--accent); font-weight: 600; }
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
.dm-strip { position: sticky; top: -8px; z-index: 2; background: var(--panel); margin: -8px -8px 10px; padding: 8px; border-bottom: 1px solid var(--line); }
.dm-sort { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; font-size: 13px; }
.dm-sort button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 2px 10px; font-size: 12.5px; cursor: pointer; }
.dm-sort button.on { background: var(--dark); color: var(--bg); border-color: var(--dark); }
.dm-names { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin; }
.dm-names a { flex: none; border: 1px solid var(--line); border-radius: 8px; padding: 2px 10px; font-size: 13px; cursor: pointer; white-space: nowrap; color: var(--text); background: var(--bg); }
.dm-names a:hover { border-color: var(--accent); color: var(--accent); }
.dm-names small { color: var(--muted); margin-left: 5px; font-size: 11.5px; }
.dm-co { scroll-margin-top: 96px; border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px; margin: 0 0 10px; }
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
.dm-rate { float: right; display: inline-flex; margin: 0 0 4px 8px; }
.dm-rate button { border: none; background: none; padding: 1px; color: var(--line-2); cursor: pointer; border-radius: 4px; }
.dm-rate button svg { width: 17px; height: 17px; }
.dm-rate button.on { color: var(--accent); } .dm-rate button.on svg { fill: var(--accent); }
.dm-names .st { color: var(--accent); font-weight: 600; }
.dm-res { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; margin: 0 0 10px; }
.dm-res .dm-names { flex-wrap: wrap; overflow: visible; margin-top: 6px; }
.dm-days { display: flex; align-items: flex-end; gap: 3px; height: 62px; margin: 0 0 8px; padding: 4px 8px 0; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); overflow-x: auto; }
.dm-days > b { flex: none; font-weight: 400; font-size: 12px; color: var(--muted); align-self: center; margin-right: 6px; white-space: nowrap; }
.dm-days i { flex: 1 0 14px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; cursor: pointer; font-style: normal; }
.dm-days i span { font-size: 10px; color: var(--muted); line-height: 12px; } .dm-days i u { display: block; width: 100%; max-width: 18px; background: var(--accent); opacity: .55; border-radius: 3px 3px 0 0; text-decoration: none; }
.dm-days i:hover u, .dm-days i.on u { opacity: 1; } .dm-days i.on span { color: var(--accent); font-weight: 700; } .dm-days i small { font-size: 9px; color: var(--muted); line-height: 11px; }
.dm-flt { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 4px 0 12px; }
.dm-flt select { width: auto; font-size: 12.5px; padding: 3px 6px; border-radius: 8px; max-width: 150px; }
.dm-seg { display: inline-flex; border: 1px solid var(--line-2); border-radius: 8px; overflow: hidden; }
.dm-seg button { border: none; border-radius: 0; padding: 3px 10px; font-size: 12.5px; background: var(--panel); color: var(--muted); cursor: pointer; }
.dm-seg button.on { background: var(--accent-soft); color: var(--accent); }
.dm-watch { margin: 8px 0; font-size: 13px; border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 12px; }
.dm-watch summary { cursor: pointer; } .dm-wl { padding: 6px 0; border-top: 1px dashed var(--line); } .dm-wl a, .dm-watch a { cursor: pointer; }
.dm-watch small { margin-left: 3px; color: var(--muted); }
.dm-tier b { padding: 3px 8px; font-size: 12.5px; color: var(--muted); font-weight: 500; border-right: 1px solid var(--line-2); }
.dm-tier button.on { font-weight: 600; }
.dm-flt .ghost { border: none; background: none; color: var(--accent); font-size: 12.5px; cursor: pointer; padding: 3px 6px; }
@container (max-width: 900px) { .dm-3 { grid-template-columns: 210px minmax(0, 1fr); } .dm-3 > div:nth-child(3) { grid-column: 1 / -1; max-height: none; } }
@container (max-width: 560px) { .dm-3 { grid-template-columns: 1fr; } .dm-3 > div { max-height: none; } }
`;

const E = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const SRC = { '创业公司': '创', 'PH 日榜': 'PH', '增长 Case': '案', '大公司 / AI native': '大', '中型 AI 创业公司': '中' };
const TIER = { small: '小', mid: '中', large: '大' };
const TIER_NOTE = { small: '年收入 < $1M 或未融资', mid: 'A–C 轮或年收入 $1M–$100M', large: 'D 轮以后、年收入 ≥ $100M 或大厂' };
const STAGE = { start: '正在启动', discover: '联网找中型 AI 创业公司', profile: '联网补中型公司画像', extract: '逐个产品抽取需求卡', model: '补商业模式', arr: '补收入规模', taxonomy: '建场景和痛点分类', assign: '把产品归到痛点', summary: '写场景和痛点的增长总结', done: '完成' };

const STARS = [[0, '全部'], [1, '★ 已评分'], [4, '★4 以上'], [5, '★5']];

export async function demandTab(host, ctx, q0 = '') {
  const { api, h, ui, toast } = ctx;
  const R = new Map();
  const star = (k) => R.get('demand:' + k) || 0;
  const starSvg = ui.icon('star').outerHTML;
  let minStar = (window.__starPick ||= {}).demand || 0;
  let D, view = 'graph', tac = '', src = '', bm = '', size = '', mat = 'tac', S = '', P = '', sortBy = 'def', timer;
  let q = q0, day = '', added = '', qs = null, idx = new Map();
  const low = (s) => String(s || '').toLowerCase();
  const bigrams = (s) => { const a = low(s).replace(/[\s\-_.·/]/g, ''), r = new Set(); for (let i = 0; i < a.length - 1; i++) r.add(a.slice(i, i + 2)); return r; };
  const subseq = (t, s) => { let i = 0; for (const ch of s) if (ch === t[i] && ++i === t.length) return true; return false; };
  const dist = (a, b) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
    return d[a.length][b.length];
  };
  const buildIdx = () => {
    idx = new Map(Object.entries(D.cards).map(([k, c]) => {
      const name = low(c.name);
      return [k, { name, words: name.split(/[^a-z0-9\u4e00-\u9fff]+/).filter((w) => w.length > 1), big: bigrams(name), all: low([c.name, c.user, c.scene, c.pain, c.product, c.bm, c.bm_type, c.growth, c.arr, c.funding, (c.tactics || []).join(' '), (c.sources || []).join(' '), c.track].join(' | ')) }];
    }));
  };
  const tokScore = (t, x) => {
    if (x.name.startsWith(t)) return 5;
    if (x.name.includes(t)) return 4;
    if (x.all.includes(t)) return 2;
    if (t.length < 3) return 0;
    const k = t.length >= 7 ? 2 : 1;
    if (x.words.some((w) => Math.abs(w.length - t.length) <= k && dist(t, w) <= k || w.length > t.length && dist(t, w.slice(0, t.length)) <= k)) return 1.5;
    const bt = [...bigrams(t)];
    if (t.length >= 4 && bt.length && bt.filter((b) => x.big.has(b)).length / bt.length >= 0.8) return 1.2;
    return /^[a-z0-9]+$/.test(t) && t.length >= 3 && subseq(t, x.name) ? 1 : 0;
  };
  const computeQ = () => {
    const toks = low(q).split(/\s+/).filter(Boolean);
    if (!toks.length) { qs = null; return; }
    qs = new Map();
    idx.forEach((x, k) => {
      let s = 0;
      for (const t of toks) { const v = tokScore(t, x); if (!v) { s = 0; break; } s += v; }
      if (s) qs.set(k, s);
    });
  };
  const fresh = new Set();
  const SEEN = 'dm-seen';
  const seen = new Set((() => { try { return JSON.parse(localStorage.getItem(SEEN) || '[]'); } catch { return []; } })());
  const saveSeen = () => { try { localStorage.setItem(SEEN, JSON.stringify([...seen])); } catch { /* 无痕模式 */ } };
  const isNew = (k) => !!D.cards[k]?.added && !seen.has(k);
  const newN = (keys) => keys.filter(isNew).length;
  const dot = (n) => (n ? `<b class="dm-dot" title="${n} 个新项目">${n}</b>` : '');
  const body = h('div.dm-cq');
  host.append(h('style', {}, CSS), body);
  const el = host;

  const ADDED = [['', '全部时间'], ['1', '今天新增'], ['3', '近 3 天新增'], ['7', '近 7 天新增'], ['30', '近 30 天新增']];
  const cutoff = () => { const d = new Date(); d.setDate(d.getDate() - (+added - 1)); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const dateOk = (c) => { const d = (c.date || '').slice(0, 10); return (!day || d === day) && (!added || d >= cutoff()); };
  const fit = (k) => { const c = D.cards[k]; return (!qs || qs.has(k)) && dateOk(c) && (!tac || c.tactics.includes(tac)) && (!src || c.sources.includes(src)) && (!bm || c.bm_type === bm) && (!size || c.tier === size) && star(k) >= minStar; };
  const filtering = () => !!(q.trim() || day || added || tac || src || bm || size || minStar);
  const nAct = () => [src, tac, bm, size, day, added].filter(Boolean).length + (minStar ? 1 : 0);
  const hits = (sb) => (filtering() ? sb.products.filter(fit) : sb.products);
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

  const money = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`);
  const ordered = (keys) => {
    const a = [...keys];
    if (minStar) a.sort((x, y) => star(y) - star(x));
    if (qs && sortBy === 'def') a.sort((x, y) => (qs.get(y) || 0) - (qs.get(x) || 0));
    if (sortBy === 'arr') a.sort((x, y) => (D.cards[y].arr_v || 0) - (D.cards[x].arr_v || 0));
    else if (sortBy === 'new') a.sort((x, y) => (D.cards[y].date || '').localeCompare(D.cards[x].date || ''));
    return a;
  };
  const strip = (keys) => `<div class="dm-strip"><div class="dm-sort"><span class="dm-m">${keys.length} 家 · 排序</span>${[['def', '默认'], ['arr', 'ARR 高→低'], ['new', '出现时间 新→旧']].map(([k, t]) => `<button data-sort="${k}" class="${sortBy === k ? 'on' : ''}">${t}</button>`).join('')}</div>
<div class="dm-names">${keys.map((k) => { const c = D.cards[k]; return `<a data-jump="${E(k)}" title="${E(c.scene)}">${E(c.name)}${star(k) ? `<small class="st">★${star(k)}</small>` : ''}<small>${sortBy === 'new' ? E((c.date || '').slice(5)) : c.arr_v ? money(c.arr_v) : ''}</small></a>`; }).join('')}</div></div>`;

  const days = () => {
    const n = {}, f = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    Object.values(D.cards).forEach((c) => { const k = (c.date || '').slice(0, 10); if (k) n[k] = (n[k] || 0) + 1; });
    const ds = Array.from({ length: 30 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - 29 + i); return f(d); });
    const mx = Math.max(1, ...ds.map((k) => Math.sqrt(n[k] || 0))), w7 = ds.slice(-7).reduce((a, k) => a + (n[k] || 0), 0);
    return `<div class="dm-days" title="按「出现日期」统计；点某一天只看这天新增的公司"><b>每日新增<br>今日 ${n[ds[29]] || 0} · 近 7 天 ${w7}</b>${ds.map((k) => `<i data-day="${k}" class="${day === k ? 'on' : ''}" title="${k}：${n[k] || 0} 家"><span>${n[k] || ''}</span><u style="height:${n[k] ? Math.max(3, Math.round(Math.sqrt(n[k]) / mx * 34)) : 0}px"></u><small>${k.slice(8)}</small></i>`).join('')}</div>`;
  };
  const notice = () => {
    const nn = newN(Object.keys(D.cards)), run = D.status.running;
    if (!nn && !D.pending && !run) return '';
    return `<div class="dm-note">${run ? `<span>同步中：${E(STAGE[D.status.stage] || D.status.stage)} ${D.status.done || 0} / ${D.status.total || 0}</span>` : ''}${D.pending && !run ? `<span>雷达里有 <b>${D.pending}</b> 个新产品还没收录</span><button data-run="sync">同步新项目</button>` : ''}${nn ? `<span><b class="dm-dot" style="margin:0">${nn}</b> 个新收录的项目未读</span><button data-seen="all">全部标为已读</button>` : ''}</div>`;
  };
  const bar = () => {
    const n = (f) => Object.values(D.cards).filter(f).length;
    const nStar = (m) => Object.keys(D.cards).filter((k) => (m ? star(k) >= m : true)).length;
    const total = filtering() ? Object.keys(D.cards).filter(fit).length : 0;
    const sel = (f, opts, cur) => `<select data-f="${f}">${opts.map(([v, t]) => `<option value="${E(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${E(t)}</option>`).join('')}</select>`;
    return `<div class="dm-flt"><span class="dm-seg"><button data-v="graph" class="${view === 'graph' ? 'on' : ''}">图谱</button><button data-v="mat" class="${view === 'mat' ? 'on' : ''}">打法矩阵</button></span>
<span class="dm-seg dm-tier" title="按公司规模看：同样的痛点，小团队、中型创业公司、大厂各怎么打"><b>规模</b>${[['', '全部'], ...Object.entries(TIER)].map(([x, t]) => `<button data-size="${x}" class="${size === x ? 'on' : ''}" title="${x ? E(TIER_NOTE[x]) : '不限规模'}">${t}${x ? ` ${n((c) => c.tier === x)}` : ''}</button>`).join('')}</span>
${sel('added', ADDED, added)}
${sel('src', [['', '全部来源'], ...Object.keys(SRC).map((x) => [x, `${x} (${n((c) => c.sources.includes(x))})`])], src)}
${sel('tac', [['', '全部增长手段'], ...D.graph.tactics.map((t) => [t, `${t} (${n((c) => c.tactics.includes(t))})`])], tac)}
${sel('bm', [['', '全部商业模式'], ...(D.graph.models || []).map((t) => [t, `${t} (${n((c) => c.bm_type === t)})`])], bm)}
${sel('star', STARS.map(([m, t]) => [m, `${t} (${nStar(m)})`]), minStar)}
${q.trim() ? `<button class="ghost" data-clearq="1">清除「${E(q)}」</button>` : ''}${day || nAct() ? '<button class="ghost" data-clear="1">清除筛选</button>' : ''}
<span class="dm-sp"></span><span class="dm-m">${filtering() ? `匹配 ${total} 家 · ` : ''}${D.graph.n} 个公司 · ${new Date(D.graph.updated * 1000).toLocaleDateString()}</span><button data-run="graph">重新聚类</button></div>`;
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
    const v = star(k);
    const rate = `<span class="dm-rate" title="给这家打分（再点一次取消），之后可按星级筛选">${[1, 2, 3, 4, 5].map((i) => `<button data-rate="${i}" data-k="${E(k)}" aria-label="${i} 星" class="${i <= v ? 'on' : ''}">${starSvg}</button>`).join('')}</span>`;
    return `<div class="dm-co" id="dm-c-${E(k)}" data-k="${E(k)}">${rate}<h4>${E(c.name)}${nw ? '<b class="dm-dot">新</b>' : ''}</h4><div class="dm-m">${c.tier ? `<span class="dm-size ${c.tier}" title="${E(TIER_NOTE[c.tier])}">${TIER[c.tier]}</span> ` : ''}${c.sources.map(E).join(' · ')}${c.track ? ' · ' + E(c.track) : ''}${c.date ? ' · 出现于 ' + E(c.date) : ''}</div>
<dl><dt>目标用户</dt><dd>${E(c.user)}</dd><dt>场景</dt><dd>「${E(c.scene)}」</dd><dt>痛点</dt><dd>${E(c.pain)}</dd><dt>产品</dt><dd>${E(c.product)}</dd>
${c.arr ? `<dt>收入规模</dt><dd>${E(c.arr)}<div class="dm-tg"><span class="b">${c.arr_grade === 'verified' ? '支付渠道验证' : '自述 / 报道，未验证'}</span></div></dd>` : ''}${c.funding ? `<dt>融资</dt><dd>${E(c.funding)}</dd>` : ''}<dt>商业模式</dt><dd>${c.bm ? E(c.bm) : '<span class="dm-m">暂无</span>'}${c.bm_type ? `<div class="dm-tg"><span class="b">${E(c.bm_type)}</span></div>` : ''}</dd>
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
        ? `${strip(ordered(hits(sb)))}<div class="dm-box"><b>大家怎么增长：</b>${sb.growth ? E(sb.growth) : '<span class="dm-m">增长材料较少</span>'}<div class="dm-m" style="margin-top:4px">${tacCount(hits(sb)).map((t) => `<span class="dm-chp">${E(t[0])} ×${t[1]}</span>`).join('')}${bmCount(hits(sb)).map((t) => `<span class="dm-chp b">${E(t[0])} ×${t[1]}</span>`).join('')}</div></div>${ordered(hits(sb)).map(company).join('')}`
        : `<div class="dm-box">${E(sc.summary)}</div><div class="dm-m">增长手段分布（${ks.length} 家）</div>${bars(ks)}<div class="dm-m" style="margin-top:8px">商业模式分布</div>${bars(ks, 'bm')}`;
    }
    const rk = qs ? [...qs.keys()].filter(fit).sort((a, b) => qs.get(b) - qs.get(a)) : [];
    const res = qs ? `<div class="dm-res"><span class="dm-m">搜到 ${rk.length} 家，点名称直达${rk.length > 60 ? '（只列前 60 家）' : ''}</span><div class="dm-names">${rk.slice(0, 60).map((k) => `<a data-go="${E(k)}" title="${E(D.cards[k].scene)}">${E(D.cards[k].name)}<small>${D.cards[k].arr_v ? money(D.cards[k].arr_v) : ''}</small></a>`).join('') || '<span class="dm-m">没有匹配的公司</span>'}</div></div>` : '';
    return `${res}<div class="dm-3"><div>${c1}</div><div>${c2}</div><div>${c3}</div></div>`;
  };

  const matrix = () => {
    const T = mat === 'tac' ? D.graph.tactics : D.graph.models || [], key = (c, t) => (mat === 'tac' ? c.tactics.includes(t) : c.bm_type === t);
    const rows = D.graph.scenes.map((sc) => {
      const ks = sc.subs.flatMap((sb) => sb.products).filter((k) => (!qs || qs.has(k)) && dateOk(D.cards[k]) && (!src || D.cards[k].sources.includes(src)) && (!size || D.cards[k].tier === size) && star(k) >= minStar);
      return { sc, ks, cnt: T.map((t) => ks.filter((k) => key(D.cards[k], t))) };
    });
    const mx = Math.max(1, ...rows.flatMap((r) => r.cnt.map((x) => x.length)));
    return `<div class="dm-bar"><button data-mat="tac" class="${mat === 'tac' ? 'on' : ''}">场景 × 增长手段</button><button data-mat="bm" class="${mat === 'bm' ? 'on' : ''}">场景 × 商业模式</button></div>
<div class="dm-m">格子是「这个场景里属于该${mat === 'tac' ? '增长手段' : '商业模式'}的公司数」，越深越集中；点格子回到图谱，只看这一类公司。${mat === 'tac' ? '只统计材料里讲了增长手段的公司（PH 简介通常没讲，空白不代表没做）。' : ''}</div>
<div class="dm-wrap"><table class="dm-tbl"><tr><th>用户场景</th><th>公司</th>${T.map((t) => `<th>${E(t)}</th>`).join('')}</tr>
${rows.map((r) => `<tr><td>${E(r.sc.name)}</td><td>${r.ks.length}</td>${r.cnt.map((x, i) => `<td class="c" data-cell="${E(T[i])}" style="background:rgba(120,90,200,${(x.length / mx * 0.7).toFixed(2)})">${x.length || ''}</td>`).join('')}</tr>`).join('')}</table></div>`;
  };

  const notes = (co) => {
    const c = D.cards[co.dataset.k];
    const at = document.createComment('');
    co.replaceWith(at);
    at.replaceWith(annotate(ctx, co, { doc: 'demand:' + co.dataset.k, title: `${c.name} · 产品需求`,
      link: `#kb/demand/${encodeURIComponent(c.name)}`, source: co.innerText, compact: true }));
  };
  const watchBox = () => {
    const w = D.watch || { logs: [], sources: [] }, last = w.logs.at(-1);
    const head = last ? `上次 ${E(last.date)}：新增 <b>${last.new.length}</b> 家中型公司 · 新来源 ${last.new_sources.length} 个 · 查漏 ${last.gaps.length} 个场景 · 融资新闻线索 ${last.leads} 条 · 花费 $${last.cost ?? 0}${last.stopped === 'budget' ? '（到预算停）' : ''}`
      : '还没跑过：每周自动跑一次，找新来源、按融资新闻和薄弱场景查漏、重跑过期检索';
    const row = (l) => `<div class="dm-wl"><b>${E(l.date)}</b> 新增 ${l.new.length} 家${l.new.length ? '：' + l.new.slice(0, 30).map((x) => `<a data-findname="${E(x)}">${E(x)}</a>`).join('、') + (l.new.length > 30 ? ' 等' : '') : ''}
${l.gaps.length ? `<div class="dm-m">查漏场景：${l.gaps.map(E).join('、')}</div>` : ''}${l.queries.length ? `<div class="dm-m">重跑检索 ${l.queries.length} 个</div>` : ''}</div>`;
    const src = w.sources.length ? `<div class="dm-m" style="margin-top:6px">自动找到的新来源（${w.sources.length}）：${w.sources.map((x) => `<a href="${E(x.url)}" target="_blank" rel="noopener">${E(x.name)}</a>${x.kind ? `<small>${E(x.kind)}</small>` : ''}`).join(' · ')}</div>` : '';
    return `<details class="dm-watch"><summary><b>持续更新</b> · ${head}</summary>${[...w.logs].reverse().map(row).join('')}${src}</details>`;
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
    body.innerHTML = notice() + bar() + days() + watchBox() + (view === 'graph' ? graph() : matrix());
    body.querySelectorAll('.dm-co').forEach(notes);
    window.scrollTo(0, wy);
  };
  const load = async () => {
    if (!el.isConnected) return;
    const [d, rt] = await Promise.all([api.get('/api/demand/graph'), loadRatings(api, 'demand:')]);
    D = d;
    buildIdx();
    computeQ();
    R.clear();
    rt.forEach((v, k) => R.set(k, v));
    paint();
    if (D.graph && D.status.running) timer = setTimeout(load, 4000);
  };
  const pick = (sb) => {
    P = sb.id;
    fresh.clear();
    hits(sb).forEach((k) => { if (isNew(k)) { fresh.add(k); seen.add(k); } });
    saveSeen();
  };

  body.addEventListener('change', (e) => {
    const f = e.target.dataset?.f;
    if (!f) return;
    const v = e.target.value;
    if (f === 'star') { minStar = +v; window.__starPick.demand = minStar; } else if (f === 'src') src = v; else if (f === 'tac') tac = v; else if (f === 'bm') bm = v; else if (f === 'size') size = v; else if (f === 'added') added = v;
    paint();
  });
  body.onclick = async (e) => {
    const d = e.target.closest('[data-findname],[data-size],[data-clearq],[data-day],[data-go],[data-clear],[data-rate],[data-star],[data-jump],[data-sort],[data-seen],[data-v],[data-s],[data-t],[data-b],[data-mat],[data-cell],[data-run],[data-sc],[data-sb]');
    if (!d) return;
    const ds = d.dataset;
    if (ds.rate) {
      const k = ds.k, doc = 'demand:' + k, prev = star(k), v = +ds.rate === prev ? 0 : +ds.rate;
      const set = (x) => (x ? R.set(doc, x) : R.delete(doc));
      set(v);
      paint();
      try { await api.put('/api/annotations/rating', { doc, title: D.cards[k].name, link: '#kb/demand', stars: v }); } catch (err) { set(prev); paint(); toast('评分没存上：' + err.message, true); }
      return;
    }
    if (ds.go) {
      for (const sc of D.graph.scenes) for (const sb of sc.subs) if (sb.products.includes(ds.go)) { S = sc.id; pick(sb); }
      paint();
      document.getElementById('dm-c-' + ds.go)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
      return;
    }
    if (ds.clearq) { q = ''; qs = null; paint(); return; }
    if (ds.size !== undefined) { size = ds.size; paint(); return; }
    if (ds.findname) { q = ds.findname; computeQ(); paint(); return; }
    if (ds.clear) { tac = src = bm = size = day = added = ''; minStar = 0; window.__starPick.demand = 0; paint(); return; }
    if (ds.star !== undefined) { minStar = +ds.star; window.__starPick.demand = minStar; paint(); return; }
    if (ds.jump) { document.getElementById('dm-c-' + ds.jump)?.scrollIntoView({ block: 'start', behavior: 'smooth' }); return; }
    if (ds.day !== undefined) day = day === ds.day ? '' : ds.day;
    else if (ds.sort) sortBy = ds.sort;
    else if (ds.v) view = ds.v;
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
  return { search: (t) => { q = t; computeQ(); S = ''; P = ''; if (D?.graph) paint(); } };
}
