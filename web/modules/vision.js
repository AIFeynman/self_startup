// 视野板块：AI 发展 → 吃喝玩乐 / 生活 / 学习 → 国家宏观与行业 的大数据变化和解读卡。
// 数据和统计全在后端 /api/vision/*；「变了多少」「口径提醒」由程序算，解读卡正文来自通过校验和审稿的卡片。
const FREQ = { Y: '年', H: '半年', Q: '季', M: '月', W: '周', D: '日' };
const STATUS = { running: '在写', reviewing: '审稿中', done: '已发布', rejected: '被打回', failed: '失败' };
const TIPS = ['最近 AI 哪个变化最值得注意？', '中国生育率还会继续掉吗？', 'AI 对哪些工作的招聘影响最大？'];

const isRate = (unit) => ['%', '‰', ''].includes(unit || '') || (unit || '').includes('=100');

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  const d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : 3;
  return Number(v.toFixed(d)).toLocaleString('zh-CN', { maximumFractionDigits: d });
}

function delta(cfg, d) {
  if (d === null || d === undefined) return '';
  const sign = d > 0 ? '+' : d < 0 ? '−' : '±';
  const unit = cfg.unit === '%' ? ' 个百分点' : cfg.unit === '‰' ? ' 个千分点' : isRate(cfg.unit) ? '' : ` ${cfg.unit}`;
  return `${sign}${fmt(Math.abs(d))}${unit}`;
}

function changeLine(cfg, s) {
  const parts = [];
  if (s.change !== undefined) parts.push(`比上一期（${s.prev_period}）${delta(cfg, s.change)}`);
  if (s.yoy_pct !== undefined) parts.push(`比一年前 ${s.yoy_pct > 0 ? '+' : ''}${fmt(s.yoy_pct)}%`);
  else if (s.yoy_change !== undefined) parts.push(`比一年前 ${delta(cfg, s.yoy_change)}`);
  return parts.join(' · ');
}

function scale(pts, w, h, pad) {
  const vs = pts.map((p) => p[1]);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (lo === hi) { lo -= 1; hi += 1; }
  const x = (i) => pad.left + (pts.length === 1 ? 0 : i / (pts.length - 1)) * (w - pad.left - pad.right);
  const y = (v) => pad.top + (1 - (v - lo) / (hi - lo)) * (h - pad.top - pad.bottom);
  return { x, y, lo, hi };
}

function spark(pts) {
  if (pts.length < 2) return '';
  const w = 160, h = 40, { x, y } = scale(pts, w, h, { left: 2, right: 2, top: 4, bottom: 4 });
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
  const last = pts.length - 1;
  return `<svg class="vs-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"/>
    <circle cx="${x(last)}" cy="${y(pts[last][1])}" r="2.6"/></svg>`;
}

function bigChart(h, cfg, pts) {
  const w = 720, ht = 260, pad = { left: 52, right: 14, top: 14, bottom: 26 };
  const { x, y, lo, hi } = scale(pts, w, ht, pad);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
  const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<line class="vs-gl" x1="${pad.left}" x2="${w - pad.right}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="vs-ax" x="${pad.left - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join('');
  const xs = [0, Math.floor((pts.length - 1) / 2), pts.length - 1].map((i, k) => `<text class="vs-ax" x="${x(i)}" y="${ht - 6}"
    text-anchor="${['start', 'middle', 'end'][k]}">${pts[i][0]}</text>`).join('');
  const box = h('div.vs-chart', { html: `<svg viewBox="0 0 ${w} ${ht}" role="img" aria-label="${cfg.name}历史走势">${ticks}${xs}
    <path class="vs-line" d="${d}"/><line class="vs-cross" y1="${pad.top}" y2="${ht - pad.bottom}" visibility="hidden"/>
    <circle class="vs-dot" r="3.5" visibility="hidden"/>
    <rect class="vs-hit" x="${pad.left}" y="${pad.top}" width="${w - pad.left - pad.right}" height="${ht - pad.top - pad.bottom}"/></svg><div class="vs-tip" hidden></div>` });
  const svg = box.querySelector('svg'), tip = box.querySelector('.vs-tip'), cross = box.querySelector('.vs-cross'), dot = box.querySelector('.vs-dot');
  const hit = box.querySelector('.vs-hit');
  hit.addEventListener('mousemove', (e) => {
    const r = svg.getBoundingClientRect();
    const sx = (e.clientX - r.left) / r.width * w;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round((sx - pad.left) / (w - pad.left - pad.right) * (pts.length - 1))));
    const cx = x(i), cy = y(pts[i][1]);
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); dot.setAttribute('visibility', 'visible');
    tip.hidden = false; tip.textContent = `${pts[i][0]}：${fmt(pts[i][1])} ${cfg.unit || ''}`;
    const left = cx / w * 100; tip.style.left = `${left}%`; tip.classList.toggle('flip', left > 60);
  });
  hit.addEventListener('mouseleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
  return box;
}

function tile(h, s) {
  const sm = s.summary || {};
  const reasons = s.signals?.reasons || [];
  return h('a.card.vs-tile', { href: `#vision/${s.id}` }, [
    h('div.vs-tile-name', {}, s.name),
    h('div.vs-tile-val', {}, [h('b', {}, fmt(sm.value)), h('span.muted', {}, ` ${s.unit || ''} · ${sm.period || '还没取到'}`)]),
    h('div.vs-tile-chg.muted', {}, changeLine(s, sm)),
    h('div', { html: spark(s.spark || []) }),
    reasons.length ? h('div.vs-reason', {}, reasons[0]) : null,
  ]);
}

function pendingList(h, list) {
  if (!list.length) return null;
  return h('div.vs-pending.muted', {}, [h('b', {}, '待接入：'), list.map((s) => s.name).join('、')]);
}

function existingLinks(h, list) {
  if (!list.length) return null;
  return h('div.vs-pending.muted', {}, ['平台里已有：', ...list.flatMap((s, i) => [i ? '、' : '', h('a', { href: s.link || '#intel' }, s.name)])]);
}

function themeBlock(h, ui, t) {
  const ok = t.series.filter((s) => s.status === 'ok');
  const todo = t.series.filter((s) => s.status === 'todo' || s.status === 'extract');
  const existing = t.series.filter((s) => s.status === 'existing');
  const out = [ui.section(t.title, `已接入 ${ok.length} 个 · 待接入 ${todo.length} 个`)];
  if (t.id === 'macro') {
    out.push(h('div.card.vs-table-wrap', {}, h('table.vs-table', {}, [
      h('tr', {}, ['指标', '最新', '期', '变化', '值得注意'].map((x) => h('th', {}, x))),
      ...ok.map((s) => h('tr.go', { onclick: () => { location.hash = `#vision/${s.id}`; } }, [
        h('td', {}, s.name), h('td', {}, `${fmt(s.summary?.value)} ${s.unit || ''}`), h('td.muted', {}, s.summary?.period || '—'),
        h('td.muted', {}, s.summary?.change !== undefined ? delta(s, s.summary.change) : ''), h('td.vs-reason-cell', {}, (s.signals?.reasons || []).join('；')),
      ])),
    ])));
  } else if (ok.length) {
    const groups = [...new Set(ok.map((s) => s.grp))];
    for (const g of groups) {
      if (groups.length > 1) out.push(h('div.vs-grp', {}, g));
      out.push(h('div.vs-grid', {}, ok.filter((s) => s.grp === g).map((s) => tile(h, s))));
    }
  } else {
    out.push(ui.empty('这一组还没有能直接取到的数据', '下面列的指标要从报告里抽取或待验证来源，P2 再接入。'));
  }
  out.push(pendingList(h, todo), existingLinks(h, existing));
  return out;
}

function cardView(h, c, cfg, { full = false } = {}) {
  const b = c.body || {}, s = c.summary || {};
  const why = (b.why || []).map((w) => h('li', {}, [
    h(`span.tag.${w.kind === '推测' ? 'gray' : 'ok'}`, {}, w.kind || '来源'), ' ', w.text || '',
    w.url ? [' ', h('a', { href: w.url, target: '_blank', rel: 'noopener' }, w.date ? `（${w.date}）` : '（来源）')] : null,
  ]));
  const preds = (b.predictions || []).map((p) => h('li', {}, [p.text || '', h('span.muted', {}, ` —— 到 ${p.due} 对账 · 可信度${p.confidence}`)]));
  const row = (k, v) => (v ? h('div.vs-row', {}, [h('span.card-label', {}, k), h('div', {}, v)]) : null);
  return h('div.card.vs-card', {}, [
    h('div.row.between', {}, [h('a.vs-card-series', { href: `#vision/${c.series_id}` }, cfg ? cfg.name : c.series_id),
      h('span.muted', {}, `${c.period} · ${c.created_at?.slice(0, 10) || ''}${full ? ` · ${STATUS[c.status] || c.status}` : ''}`)]),
    h('h3.vs-card-title', {}, b.title || '（还没写完）'),
    b.plain ? h('p.vs-plain', {}, b.plain) : null,
    cfg ? row('变了多少', [`${fmt(s.value)} ${cfg.unit || ''}（${s.period || c.period}）`, changeLine(cfg, s) ? `，${changeLine(cfg, s)}` : '',
      (c.signals?.reasons || []).length ? `。${c.signals.reasons.join('；')}` : '']) : null,
    row('打个比方', b.analogy),
    why.length ? row('为什么', h('ul.vs-list', {}, why)) : null,
    b.deeper?.text ? row('更深一层', [h('span.tag', {}, b.deeper.type), ' ', b.deeper.text]) : null,
    preds.length ? row('我们的判断', h('ul.vs-list', {}, preds)) : null,
    row('对你意味着', b.meaning),
    row('接下来看', b.next),
    cfg?.note ? row('口径提醒', h('span.muted', {}, cfg.note)) : null,
    full && (c.checks?.problems || []).length ? row('校验没过', h('ul.vs-list.err', {}, c.checks.problems.map((p) => h('li', {}, p)))) : null,
    full && c.review?.reason && !c.review.pass ? row('审稿意见', c.review.reason) : null,
  ]);
}

function predTable(h, preds, byId) {
  const verdict = (p) => (p.hit === 1 ? h('span.tag.ok', {}, `中了（实际 ${fmt(p.actual)}）`) : p.hit === 0 ? h('span.tag.err', {}, `没中（实际 ${fmt(p.actual)}）`)
    : p.actual === undefined || p.actual === null ? h('span.tag.gray', {}, p.due_date < new Date().toISOString().slice(0, 10) ? '过期' : '等到期') : null);
  return h('div.card.vs-table-wrap', {}, h('table.vs-table', {}, [
    h('tr', {}, ['判断', '指标', '到期', '可信度', '结果'].map((x) => h('th', {}, x))),
    ...preds.map((p) => h('tr', {}, [h('td', {}, p.text || `${p.op} ${p.target}`), h('td', {}, h('a', { href: `#vision/${p.series_id}` }, byId[p.series_id]?.name || p.series_id)),
      h('td.muted', {}, p.due_date), h('td', {}, p.confidence), h('td', {}, verdict(p))])),
  ]));
}

function hitStats(ui, hits, themes) {
  const pct = (o) => (o && o.n ? `${Math.round(o.hits / o.n * 100)}%（${o.hits}/${o.n}）` : '还没有');
  return ui.stats([{ k: '全部判断命中率', v: pct(hits.all) },
    ...['高', '中', '低'].map((c) => ({ k: `可信度${c}`, v: pct(hits[`conf:${c}`]) })),
    ...themes.filter((t) => hits[t.id]).map((t) => ({ k: t.title, v: pct(hits[t.id]) }))]);
}

function askBar(ctx, ref, title) {
  const send = (text) => ctx.openChat({ module: 'vision', ref, title, send: text });
  const box = ctx.ui.composer({ placeholder: '问问这些数据：为什么会这样、接下来会怎样、对我意味着什么…', hint: '', onSubmit: send });
  return ctx.h('div.vs-ask', {}, [box, ctx.ui.chips(TIPS.map((t) => ({ label: t, onClick: () => send(t) })), { left: true })]);
}

function statusLine(st) {
  const r = st.run;
  const errs = r ? Object.entries(r.results || {}).filter(([, v]) => v.error) : [];
  return [r ? `上次更新 ${r.finished_at || r.started_at}${r.status === 'running' ? '（正在跑）' : ''}` : '还没跑过',
    `已接入 ${st.series.ok} 个指标`, errs.length ? `${errs.length} 个取数失败：${errs.map(([k]) => k).join('、')}` : ''].filter(Boolean).join(' · ');
}

async function home(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const d = await api.get('/api/vision/overview');
  const byId = Object.fromEntries(d.themes.flatMap((t) => t.series).map((s) => [s.id, s]));
  const btn = h('button.ghost', { onclick: async () => { await api.post('/api/vision/refresh', {}); toast('开始更新：取数 → 找显著变化 → 写解读卡，几分钟后刷新'); } },
    [ui.icon('refresh'), ' 立即更新']);
  el.append(h('div.vs-page', {}, [
    ui.pageHead('视野', statusLine(d.status), [btn]),
    askBar(ctx, 'vision:home', '视野'),
    ui.section('最近 30 天的解读', d.cards.length > 6 ? `共 ${d.cards.length} 张，显示最显著的 6 张` : ''),
    d.cards.length ? h('div.vs-cards', {}, d.cards.slice(0, 6).map((c) => cardView(h, c, byId[c.series_id])))
      : ui.empty('还没有解读卡', '每天更新数据后，程序挑出变化最显著的指标写卡；卡要先通过数字对账和审稿才会出现在这里。'),
    ...d.themes.flatMap((t) => themeBlock(h, ui, t)),
    ui.section('判断与对账', '每张卡至少一条到期能对账的判断'),
    hitStats(ui, d.hits, d.themes),
    d.predictions.length ? predTable(h, d.predictions, byId) : ui.empty('还没有判断'),
  ]));
}

async function detail(el, ctx, sid) {
  const { api, h, ui, toast } = ctx;
  const s = await api.get(`/api/vision/series/${sid}`);
  const sm = s.summary || {};
  const pts = s.spark || [];
  const btn = s.status === 'ok' ? h('button.ghost', { onclick: async () => {
    try { await api.post(`/api/vision/series/${sid}/card`, {}); toast('开始写这张卡：查原因 → 对账 → 审稿，几分钟后刷新'); } catch (e) { toast(e.message, true); }
  } }, [ui.icon('spark'), ' 现在写一张解读卡']) : null;
  el.append(h('div.vs-page', {}, [
    h('a.muted', { href: '#vision' }, '← 视野'),
    ui.pageHead(s.name, `${s.unit || '无单位'} · 每${FREQ[s.freq] || s.freq}更新 · ${s.region || '全球'} · 来源 ${s.source}`, [btn]),
    sm.value !== undefined ? ui.stats([
      { k: `最新（${sm.period}）`, v: `${fmt(sm.value)} ${s.unit || ''}` },
      sm.change !== undefined ? { k: '比上一期', v: delta(s, sm.change) } : null,
      sm.yoy_pct !== undefined ? { k: '比一年前', v: `${sm.yoy_pct > 0 ? '+' : ''}${fmt(sm.yoy_pct)}%` }
        : sm.yoy_change !== undefined ? { k: '比一年前', v: delta(s, sm.yoy_change) } : null,
      { k: `高于历史上多少时期（${sm.first} 起）`, v: `${fmt(sm.rank_pct)}%` },
      { k: `最高（${sm.max?.[0]}）`, v: fmt(sm.max?.[1]) },
      { k: `最低（${sm.min?.[0]}）`, v: fmt(sm.min?.[1]) },
    ].filter(Boolean)) : ui.empty('这个指标还没接入', s.note || ''),
    (s.signals?.reasons || []).length ? h('div.card.vs-why-now', {}, [h('span.card-label', {}, '程序发现的显著变化'), h('div', {}, s.signals.reasons.join('；'))]) : null,
    pts.length > 1 ? h('div.card', {}, [h('span.card-label', {}, s.freq === 'D' ? '历史走势（日数据按月取最后一个值）' : '历史走势'), bigChart(h, s, pts)]) : null,
    s.note ? h('div.card', {}, [h('span.card-label', {}, '口径'), h('div', {}, s.note)]) : null,
    ui.section('解读卡', `${s.cards.length} 张（含被打回的）`),
    ...(s.cards.length ? s.cards.map((c) => cardView(h, c, s, { full: true })) : [ui.empty('这个指标还没有解读卡')]),
    ui.section('判断与对账'),
    s.predictions.length ? predTable(h, s.predictions, { [s.id]: s }) : ui.empty('还没有判断'),
    s.revisions.length ? [ui.section('数据修订', '官方改过的旧数据，旧值保留'),
      h('div.card.vs-table-wrap', {}, h('table.vs-table', {}, [h('tr', {}, ['期', '修订后', '第几次修订', '发现时间'].map((x) => h('th', {}, x))),
        ...s.revisions.map((r) => h('tr', {}, [h('td', {}, r.period), h('td', {}, fmt(r.value)), h('td', {}, r.revision), h('td.muted', {}, r.fetched_at)]))]))] : null,
    h('details.card.vs-raw', {}, [h('summary', {}, h('span.card-label', {}, `原始数据（${s.points.length} 期）`)),
      h('div.vs-table-wrap', {}, h('table.vs-table', {}, [h('tr', {}, [h('th', {}, '期'), h('th', {}, `值（${s.unit || '无单位'}）`)]),
        ...s.points.slice().reverse().map(([p, v]) => h('tr', {}, [h('td', {}, p), h('td', {}, fmt(v))]))]))]),
  ].flat()));
}

const CSS = `
.vs-page { --vs-line: #2a78d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .vs-page { --vs-line: #3987e5; } }
:root[data-theme="dark"] .vs-page { --vs-line: #3987e5; }
.vs-ask { margin: 0 0 16px; }
.vs-ask .composer { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; padding: 5px 6px 5px 14px; box-shadow: none; }
.vs-ask .composer textarea { flex: 1; min-width: 0; min-height: 24px; font-size: 14px; }
.vs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-bottom: 14px; }
.vs-grid .card { margin: 0; }
.vs-grp { font-size: 13px; color: var(--muted); margin: 4px 0 8px; }
.vs-tile { display: flex; flex-direction: column; gap: 4px; color: inherit; padding: 14px 16px; min-width: 0; }
.vs-tile:hover { text-decoration: none; border-color: var(--line-2); }
.vs-tile-name { font-size: 13px; color: var(--muted); }
.vs-tile-val b { font-size: 22px; font-variant-numeric: tabular-nums; }
.vs-tile-val span, .vs-tile-chg { font-size: 12px; }
.vs-spark { width: 100%; height: 40px; display: block; }
.vs-spark path { fill: none; stroke: var(--vs-line); stroke-width: 1.6; vector-effect: non-scaling-stroke; }
.vs-spark circle { fill: var(--vs-line); }
.vs-reason { font-size: 12px; color: var(--accent); }
.vs-pending { font-size: 13px; margin: 0 0 18px; line-height: 1.7; }
.vs-table-wrap { overflow-x: auto; padding: 6px 10px; }
.vs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.vs-table th { text-align: left; font-weight: 500; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.vs-table td { padding: 6px 8px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; vertical-align: top; }
.vs-table tr:last-child td { border-bottom: 0; }
.vs-table tr.go { cursor: pointer; } .vs-table tr.go:hover td { background: var(--bg-2); }
.vs-reason-cell { color: var(--accent); }
.vs-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; margin-bottom: 14px; }
.vs-cards .card { margin: 0; }
.vs-card { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.vs-card-series { font-size: 13px; }
.vs-card-title { margin: 0; font-size: 18px; line-height: 1.4; }
.vs-plain { margin: 0; font-size: 15px; }
.vs-row { display: flex; flex-direction: column; font-size: 14px; line-height: 1.65; overflow-wrap: anywhere; }
.vs-row .card-label { margin-bottom: 0; }
.vs-list { margin: 0; padding-left: 18px; }
.vs-list.err { color: var(--err); }
.vs-chart { position: relative; }
.vs-chart svg { width: 100%; height: auto; display: block; }
.vs-line { fill: none; stroke: var(--vs-line); stroke-width: 1.8; }
.vs-gl { stroke: var(--line); stroke-width: 1; }
.vs-ax { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.vs-cross { stroke: var(--line-2); stroke-width: 1; }
.vs-dot { fill: var(--vs-line); }
.vs-hit { fill: transparent; cursor: crosshair; }
.vs-tip { position: absolute; top: 4px; transform: translateX(8px); background: var(--panel); border: 1px solid var(--line-2); border-radius: 8px;
  padding: 4px 8px; font-size: 12px; white-space: nowrap; pointer-events: none; font-variant-numeric: tabular-nums; }
.vs-tip.flip { transform: translateX(calc(-100% - 8px)); }
.vs-why-now div { color: var(--accent); }
.vs-raw > summary { list-style: none; cursor: pointer; }
.vs-raw > summary::-webkit-details-marker { display: none; }
.vs-raw .vs-table-wrap { max-height: 420px; overflow-y: auto; padding: 0; margin-top: 8px; }
@media (max-width: 720px) { .vs-cards { grid-template-columns: 1fr; } .vs-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .vs-tile-val b { font-size: 18px; } }
`;

function injectStyle() {
  if (document.getElementById('vs-style')) return;
  const s = document.createElement('style');
  s.id = 'vs-style';
  s.textContent = CSS;
  document.head.append(s);
}

export default {
  async render(el, ctx) {
    injectStyle();
    if (ctx.sub[0]) return detail(el, ctx, decodeURIComponent(ctx.sub[0]));
    return home(el, ctx);
  },
};
