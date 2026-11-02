// 产品雷达：关注公司的产品 / 商业变化流，B 级及以上带「五层解读卡」。
// 路由：#intel（变化流）· #intel/e/<id>（事件 + 解读卡）· #intel/c/<slug>（公司时间线；创业公司带收入曲线 + 生意拆解卡）
//       #intel/startups · #intel/tracks · #intel/t/<赛道> · #intel/ph · #intel/companies · #intel/sources
const LV = { S: ['S', 'err'], A: ['A', 'warn'], B: ['B', 'ok'], C: ['C', 'gray'] };
const CARD = { queued: ['解读中', 'line'], done: ['解读卡', 'ok'], incomplete: ['解读卡不完整', 'warn'], failed: ['解读失败', 'err'] };
const DAYS = [['7', '7 天'], ['30', '30 天'], ['90', '90 天'], ['0', '全部']];
const st = { level: 'S,A,B', days: '30', company: '', q: '', type: '' };
const ss = { track: '', sort: 'rev', q: '', watch: false, all: false };  // 创业公司表的筛选
const PROFILE = { queued: ['拆解中', 'line'], done: ['拆解卡', 'ok'], incomplete: ['拆解卡不完整', 'warn'], failed: ['拆解失败', 'err'] };
const TABS = [['变化流', '#intel'], ['创业公司', '#intel/startups'], ['赛道', '#intel/tracks'], ['PH 日榜', '#intel/ph'],
  ['公司', '#intel/companies'], ['信息源', '#intel/sources']];
const tabs = (h, active) => h('div.tabs', {}, TABS.map(([t, href]) =>
  h('button' + (href === active ? '.active' : ''), { onclick: () => { location.hash = href; } }, t)));

const CSS = `
.it-row { display: grid; grid-template-columns: 34px minmax(0,1fr) auto; gap: 4px 12px; padding: 12px 14px; border-radius: 10px; cursor: pointer; }
.it-row:hover { background: var(--bg-2); }
.it-row + .it-row { border-top: 1px solid var(--line); }
.it-lv { font: 700 18px/1 var(--serif); text-align: center; padding-top: 3px; }
.it-lv.S { color: var(--err); } .it-lv.A { color: var(--warn); } .it-lv.B { color: var(--ok); } .it-lv.C { color: var(--muted); }
.it-t { font: 600 15px/1.45 var(--serif); }
.it-meta { color: var(--muted); font-size: 12.5px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 2px; }
.it-sum { font-size: 13.5px; opacity: .85; margin-top: 3px; }
.it-day { font: 600 12px var(--font); color: var(--muted); margin: 14px 0 4px 4px; }
.it-filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
.it-filters select, .it-filters input { width: auto; padding: 5px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); color: var(--text); }
.it-src { font-size: 13px; padding: 3px 0; }
.it-acts { display: flex; gap: 8px; align-items: center; flex: none; } .it-acts select { width: auto; }
.it-card h2 { font: 700 16px var(--serif); margin: 18px 0 6px; padding-top: 10px; border-top: 1px solid var(--line); }
.it-card h2:first-child { border-top: 0; margin-top: 0; padding-top: 0; }
.it-card strong { color: var(--warn); }
.it-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.it-tbl td, .it-tbl th { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.it-tbl .err { color: var(--err); }
.it-tbl td.it-n, .it-tbl th.it-n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.it-tbl th, .it-tbl td.nw { white-space: nowrap; }
.it-tbl tr.click { cursor: pointer; } .it-tbl tr.click:hover td { background: var(--bg-2); }
.it-up { color: var(--ok); } .it-down { color: var(--err); }
.it-spark { color: var(--accent); display: block; }
.it-chart { position: relative; } .it-chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.it-chart .ax { fill: var(--muted); font: 11px var(--font); } .it-chart .grid { stroke: var(--line); stroke-width: 1; }
.it-tip { position: absolute; pointer-events: none; background: var(--panel); border: 1px solid var(--line-2); box-shadow: var(--shadow);
  border-radius: 8px; padding: 6px 9px; font-size: 12px; white-space: nowrap; display: none; z-index: 2; }
.it-legend { display: flex; gap: 14px; font-size: 12px; color: var(--muted); margin-bottom: 6px; flex-wrap: wrap; }
.it-legend i { display: inline-block; width: 14px; height: 2px; background: var(--accent); vertical-align: middle; margin-right: 5px; }
.it-legend i.pt { width: 8px; height: 8px; border-radius: 50%; background: var(--panel); border: 2px solid var(--text); }
.it-kv { display: grid; grid-template-columns: 90px minmax(0,1fr); gap: 4px 12px; font-size: 13.5px; }
.it-kv > :nth-child(odd) { color: var(--muted); }
.it-tracks { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.it-track { cursor: pointer; } .it-track:hover { border-color: var(--accent); }
.it-track .n { font: 700 20px var(--serif); } .it-track .scope { color: var(--muted); font-size: 12px; margin: 2px 0 6px; }
.it-ph { display: grid; grid-template-columns: 28px minmax(0,1fr) auto; gap: 2px 10px; padding: 8px 4px; font-size: 13.5px; }
.it-ph + .it-ph { border-top: 1px solid var(--line); } .it-ph .rk { font: 700 15px var(--serif); color: var(--muted); text-align: center; }
@media (max-width: 720px) { .it-hide-sm { display: none; } }
`;

const tag = (h, [t, c]) => h('span.tag.' + c, {}, t);
const ago = (s) => (s ? s.slice(5, 16).replace('T', ' ') : '-');

// 卡片出处写成 [来源](链接, 日期)，marked 不认这种写法，先拆成 [来源](链接)（日期）
function cardMd(md, text) {
  const box = md(text.replace(/\]\((https?:\/\/[^)\s,]+),\s*([^)]*)\)/g, '](\$1)（\$2）'));
  box.classList.add('it-card');
  return box;
}

// $12.3k / $1.2M；空值 -
function usd(v) {
  if (v === null || v === undefined || v === '') return '-';
  const a = Math.abs(v);
  return '$' + (a >= 1e9 ? (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M'
    : a >= 1e3 ? (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k' : Math.round(v));
}
const pct = (h, g) => (g === null || g === undefined ? h('span.muted', {}, '-')
  : h('span.' + (g > 0 ? 'it-up' : g < 0 ? 'it-down' : 'muted'), {}, `${g > 0 ? '+' : ''}${Math.round(g)}%`));
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// 表格里的小走势：单色 2px 线，只看形状（具体数值在公司页曲线里悬停看）
function spark(h, vals) {
  if (!vals || vals.length < 2) return h('span.muted', {}, vals?.length ? '仅 1 天' : '-');
  const w = 84, ht = 22, lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * (w - 4) + 2).toFixed(1)},${(ht - 3 - (v - lo) / span * (ht - 6)).toFixed(1)}`).join(' ');
  return h('span', { title: `${usd(vals[0])} → ${usd(vals[vals.length - 1])}（${vals.length} 天）`,
    html: `<svg class="it-spark" width="${w}" height="${ht}" viewBox="0 0 ${w} ${ht}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>` });
}

// 收入曲线：一根纵轴 = 年化收入。verified（TrustMRR 支付接口）MRR×12 画实线；reported（公开报道的 ARR）画空心点，两种口径分开标注。
function revenueChart(h, metrics, reported) {
  const ver = metrics.map((m) => ({ d: m.date, v: (m.mrr ?? m.revenue_30d ?? null), kind: 'v' })).filter((p) => p.v)
    .map((p) => ({ ...p, y: p.v * 12 }));
  const rep = reported.filter((r) => ['arr', 'mrr'].includes(r.metric))
    .map((r) => ({ d: r.date, y: r.metric === 'mrr' ? r.value * 12 : r.value, raw: r, kind: 'r' }));
  const all = [...ver, ...rep];
  if (!all.length) return null;
  const W = 640, H = 220, L = 52, R = 12, T = 10, B = 24;
  const ts = all.map((p) => Date.parse(p.d));
  let t0 = Math.min(...ts), t1 = Math.max(...ts);
  if (t1 === t0) { t0 -= 864e5 * 7; t1 += 864e5 * 7; }
  const yMax = Math.max(...all.map((p) => p.y)) * 1.1 || 1;
  const X = (d) => L + (Date.parse(d) - t0) / (t1 - t0) * (W - L - R);
  const Y = (v) => T + (1 - v / yMax) * (H - T - B);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMax / 1.1 * f);
  let svg = ticks.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${usd(v)}</text>`).join('');
  const days = [t0, (t0 + t1) / 2, t1].map((t) => new Date(t).toISOString().slice(0, 10));
  svg += days.map((d, i) => `<text class="ax" x="${X(d)}" y="${H - 6}" text-anchor="${['start', 'middle', 'end'][i]}">${d.slice(2)}</text>`).join('');
  if (ver.length > 1) svg += `<polyline points="${ver.map((p) => `${X(p.d)},${Y(p.y)}`).join(' ')}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`;
  if (ver.length === 1) svg += `<circle cx="${X(ver[0].d)}" cy="${Y(ver[0].y)}" r="4" fill="var(--accent)"/>`;
  svg += rep.map((p) => `<circle cx="${X(p.d)}" cy="${Y(p.y)}" r="5" fill="var(--panel)" stroke="var(--text)" stroke-width="2"/>`).join('');
  svg += `<line class="hair" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="var(--muted)" stroke-dasharray="3 3" style="display:none"/>`;
  svg += `<rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/>`;
  const box = h('div.it-chart', { html: `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="年化收入走势">${svg}</svg>` });
  const tip = h('div.it-tip'); box.append(tip);
  const el = box.querySelector('svg'), hair = el.querySelector('.hair');
  el.addEventListener('mousemove', (ev) => {
    const r = el.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * W;
    const p = all.reduce((a, b) => (Math.abs(X(b.d) - x) < Math.abs(X(a.d) - x) ? b : a));
    hair.setAttribute('x1', X(p.d)); hair.setAttribute('x2', X(p.d)); hair.style.display = '';
    tip.innerHTML = p.kind === 'v'
      ? `<b>${p.d}</b> · verified<br>MRR ${usd(p.v)} · 年化 ${usd(p.y)}`
      : `<b>${p.d}</b> · reported ${esc(p.raw.metric.toUpperCase())} ${usd(p.raw.value)}<br><span style="color:var(--muted)">${esc((p.raw.note || p.raw.source || '').slice(0, 60))}</span>`;
    tip.style.display = 'block';
    const px = X(p.d) / W * r.width;
    tip.style.left = Math.min(px + 12, r.width - tip.offsetWidth - 4) + 'px'; tip.style.top = (Y(p.y) / H * r.height - 10) + 'px';
  });
  el.addEventListener('mouseleave', () => { tip.style.display = 'none'; hair.style.display = 'none'; });
  const legend = h('div.it-legend', {}, [ver.length ? h('span', {}, [h('i'), 'verified：TrustMRR 支付接口的 MRR × 12']) : null,
    rep.length ? h('span', {}, [h('i.pt'), 'reported：公开报道的 ARR（未核实）']) : null]);
  return h('div', {}, [legend, box]);
}

function startupTable(h, rows, { showTrack = true } = {}) {
  const head = ['公司', showTrack ? '赛道' : null, 'MRR', '30 天', '走势', '在售', '拆解卡'].filter((x) => x !== null);
  return h('table.it-tbl', {}, [h('tr', {}, head.map((t) => h('th' + (['MRR', '30 天'].includes(t) ? '.it-n' : ''), {}, t))),
    ...rows.map((c) => h('tr.click', { onclick: () => { location.hash = `#intel/c/${c.slug}`; } }, [
      h('td', {}, [h('b', {}, c.name), c.watch ? ' ★' : '', c.description ? h('div.muted.it-hide-sm', { style: { fontSize: '12px' } }, c.description.slice(0, 80)) : null,
        !c.mrr && c.reported ? h('div.muted', { style: { fontSize: '12px' } }, `reported ${c.reported.metric.toUpperCase()} ${usd(c.reported.value)}`) : null]),
      showTrack ? h('td.muted', {}, c.track_name || '待归类') : null,
      h('td.it-n', {}, c.mrr ? usd(c.mrr) : c.revenue_30d ? h('span', { title: '近 30 天收入' }, usd(c.revenue_30d)) : '-'),
      h('td.it-n', {}, pct(h, c.growth_30d)),
      h('td.nw', {}, spark(h, c.spark)),
      h('td', {}, c.on_sale === 1 ? tag(h, [c.asking_price ? `在售 ${usd(c.asking_price)}` : '在售', 'warn']) : ''),
      h('td', {}, PROFILE[c.profile_status] ? tag(h, PROFILE[c.profile_status]) : ''),
    ].filter((x) => x !== null)))]);
}

function eventRow(h, e, { showCompany = true } = {}) {
  const card = CARD[e.card_status];
  return h('div.it-row', { onclick: () => { location.hash = `#intel/e/${e.id}`; } }, [
    h('div.it-lv.' + e.level, {}, e.level),
    h('div', {}, [
      h('div.it-t', {}, e.title),
      h('div.it-meta', {}, [showCompany ? h('b', {}, e.company_name) : null, e.product ? h('span', {}, e.product) : null,
        h('span', {}, e.type_name || e.type), h('span', {}, `${e.sources.length} 个来源`),
        e.sources.some((s) => s.official) ? null : tag(h, ['无官方源', 'warn']), card ? tag(h, card) : null]),
      e.summary ? h('div.it-sum', {}, e.summary) : null,
    ]),
    h('div.muted', { style: { fontSize: '12px' } }, e.date),
  ]);
}

function groupByDay(h, events, opts) {
  const out = [];
  let day = '';
  let box;
  for (const e of events) {
    if (e.date !== day) { day = e.date; out.push(h('div.it-day', {}, day)); box = h('div.card', { style: { padding: '4px' } }); out.push(box); }
    box.append(eventRow(h, e, opts));
  }
  return out;
}

async function renderStream(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const qs = new URLSearchParams({ level: st.level, days: st.days, company: st.company, q: st.q, type: st.type, limit: 300 });
  const [d, status, cos] = await Promise.all([api.get('/api/intel/events?' + qs), api.get('/api/intel/status'), api.get('/api/intel/companies')]);
  d.events.forEach((e) => { e.type_name = d.types[e.type]; });
  const lr = status.last_run || {};
  const runBtn = h('button.ghost', { onclick: async () => {
    const r = await api.post('/api/intel/run', { force_fetch: true });
    toast(r.started ? '开始抓取：所有信息源 → 分类 → 解读卡，几分钟后刷新' : '上一轮还在跑');
  } }, [ui.icon('refresh'), ' 立即抓取']);
  el.append(ui.pageHead('产品雷达', `跟踪 ${status.companies} 家公司 · ${status.sources} 个官方信息源 · 上次 ${ago(lr.at)}` +
    (status.running ? ' · 正在跑' : '') + (status.deepseek ? '' : ' · 未配 DEEPSEEK_API_KEY，分类停用'), [runBtn]));
  const levels = ['S', 'A', 'B', 'C'];
  el.append(ui.stats([
    ...levels.map((l) => ({ k: `${l} 级`, v: d.counts[l] || 0, active: st.level === l, onClick: () => { st.level = st.level === l ? 'S,A,B' : l; ctx.refresh(); } })),
    { k: '今日解读卡', v: `${status.cards_today}/${status.cards_per_day}` },
    { k: '异常信息源', v: status.failing_sources.length, onClick: () => { location.hash = '#intel/sources'; } },
  ]));
  const lvSel = h('select', { onchange: (e) => { st.level = e.target.value; ctx.refresh(); } },
    [['S,A,B', 'B 级及以上'], ['S,A', 'A 级及以上'], ['S', '只看 S'], ['S,A,B,C', '全部级别']].map(([v, t]) => h('option', { value: v, selected: st.level === v }, t)));
  const daySel = h('select', { onchange: (e) => { st.days = e.target.value; ctx.refresh(); } },
    DAYS.map(([v, t]) => h('option', { value: v, selected: st.days === v }, t)));
  const coSel = h('select', { onchange: (e) => { st.company = e.target.value; ctx.refresh(); } },
    [h('option', { value: '' }, '全部公司'), ...cos.map((c) => h('option', { value: c.slug, selected: st.company === c.slug }, `${c.name}（${c.events}）`))]);
  const q = h('input', { placeholder: '搜标题 / 产品', value: st.q, onkeydown: (e) => { if (e.key === 'Enter') { st.q = e.target.value; ctx.refresh(); } } });
  const tySel = h('select', { onchange: (e) => { st.type = e.target.value; ctx.refresh(); } },
    [['', '全部类型'], ['revenue', '收入 / 挂牌'], ...Object.entries(d.types).filter(([k]) => !['revenue', 'listing'].includes(k))]
      .map(([v, t]) => h('option', { value: v, selected: st.type === v }, t)));
  el.append(tabs(h, '#intel'), h('div.it-filters', {}, [lvSel, daySel, tySel, coSel, q]));
  if (!d.events.length) {
    el.append(ui.empty('这段时间还没有事件', status.events ? '换个级别或时间范围看看' : '后台每 10 分钟跑一轮；也可以点「立即抓取」'));
    return;
  }
  el.append(...groupByDay(h, d.events));
}

async function renderEvent(el, ctx, id) {
  const { api, h, md, ui, toast } = ctx;
  const e = await api.get(`/api/intel/events/${id}`);
  el.append(h('div.muted', { style: { marginBottom: '8px' } }, [h('a', { href: '#intel' }, '← 变化流'), ' · ',
    h('a', { href: `#intel/c/${e.company_slug}` }, `${e.company_name} 时间线`)]));
  const lvSel = h('select', { onchange: async (ev) => {
    const reason = prompt(`把级别从 ${e.level} 改成 ${ev.target.value}，理由（可空）：`, '');
    if (reason === null) { ev.target.value = e.level; return; }
    await api.post(`/api/intel/events/${id}/level`, { level: ev.target.value, reason });
    toast('已改级别'); ctx.refresh();
  } }, ['S', 'A', 'B', 'C'].map((l) => h('option', { value: l, selected: e.level === l }, `${l} 级`)));
  const regen = h('button.ghost', { onclick: async () => {
    const r = await api.post(`/api/intel/events/${id}/card`);
    toast('已提交解读任务'); regen.disabled = true;
    await api.waitJob(r.job_id); ctx.refresh();
  } }, [ui.icon('refresh'), e.card ? ' 重新解读' : ' 生成解读卡']);
  el.append(ui.pageHead(e.title, `${e.company_name} · ${e.product || '-'} · ${e.date} · 自动定级 ${e.level_auto}`, [h('div.it-acts', {}, [lvSel, regen])]));
  if (e.summary) el.append(h('div.card', {}, e.summary));
  el.append(ui.section('来源', `${e.sources.length} 个`), h('div.card', {}, e.sources.map((s) =>
    h('div.it-src', {}, [tag(h, s.official ? ['官方', 'ok'] : ['第三方', 'gray']), ' ', h('a', { href: s.url, target: '_blank' }, s.label || s.url),
      h('span.muted', {}, ` · ${s.date || ''} · ${s.title || ''}`)]))));
  if (e.card_status === 'profile') {  // 收入 / 挂牌事件不出五层卡，去公司页看生意拆解卡
    el.append(ui.section('生意拆解卡'), h('div.card', {}, ['收入异动和挂牌不单独写解读卡，整家公司的生意拆解在 ',
      h('a', { href: `#intel/c/${e.company_slug}` }, `${e.company_name} 公司页`), '。']));
    return;
  }
  const cs = CARD[e.card_status];
  el.append(ui.section('五层解读卡', cs ? cs[0] : (e.level === 'C' ? 'C 级默认不出卡，改成 B 级以上会自动生成' : '未生成')));
  if (e.card?.content) {
    if (e.card.missing.length) el.append(h('div.card', { style: { borderColor: 'var(--warn)' } }, `缺少：${e.card.missing.join('、')}（或缺带链接 / 日期的出处）`));
    // 卡片出处写成 [来源](链接, 日期)，marked 不认这种写法，先拆成 [来源](链接)（日期）
    const box = cardMd(md, e.card.content);
    el.append(h('div.card', {}, box));
    if (e.versions.length > 1) el.append(h('div.muted', { style: { fontSize: '12px', marginTop: '6px' } }, `共 ${e.versions.length} 个版本，显示最新（${e.card.created_at.slice(0, 16)}）`));
  } else {
    el.append(ui.empty(e.card_status === 'queued' ? '后台正在写解读卡' : '还没有解读卡'));
  }
  if (e.level_log.length) {
    el.append(ui.section('级别调整'), h('div.card', {}, e.level_log.map((l) => h('div.it-src', {}, `${l.at.slice(0, 16)} ${l.old} → ${l.new} ${l.reason || ''}`))));
  }
}

async function renderCompany(el, ctx, slug) {
  const { api, h, ui } = ctx;
  const c = await api.get(`/api/intel/companies/${slug}`);
  c.events.forEach((e) => { e.company_name = c.name; });
  if (c.kind === 'startup') return renderStartup(el, ctx, c);
  el.append(h('div.muted', { style: { marginBottom: '8px' } }, h('a', { href: '#intel/companies' }, '← 公司')));
  el.append(ui.pageHead(c.name, `T${c.tier} · ${c.category || '-'} · ${c.events.length} 个事件 · ${c.sources.length} 个官方源`));
  if (c.experiences.length) {
    el.append(ui.section('我的一手体验', '来自调研板块'), h('div.card', {}, c.experiences.map((p) =>
      h('div.it-src', {}, [h('a', { href: '#research' }, p.name), h('span.muted', {}, ` · ${p.rating ?? '-'} 分 · ${p.used_at || ''}`)]))));
  }
  el.append(ui.section('时间线'));
  el.append(...(c.events.length ? groupByDay(h, c.events, { showCompany: false }) : [ui.empty('还没有事件')]));
}

async function renderStartup(el, ctx, c) {
  const { api, h, md, ui, toast } = ctx;
  const x = c.ext || {};
  const last = c.metrics[c.metrics.length - 1] || {};
  el.append(h('div.muted', { style: { marginBottom: '8px' } }, [h('a', { href: '#intel/startups' }, '← 创业公司'),
    ...(c.track ? [' · ', h('a', { href: `#intel/t/${c.track}` }, c.track_name)] : [])]));
  const trackSel = h('select', { title: '改赛道（人工改过的不会再被模型覆盖）', onchange: async (ev) => {
    await api.patch(`/api/intel/companies/${c.id}`, { track: ev.target.value }); toast('已改赛道');
  } }, [h('option', { value: '' }, '待归类'), ...c.track_options.map((t) => h('option', { value: t.slug, selected: c.track === t.slug }, t.name))]);
  const watchBtn = h('button.ghost', { onclick: async () => {
    await api.patch(`/api/intel/companies/${c.id}`, { watch: c.watch ? 0 : 1 }); toast(c.watch ? '已取消关注' : '已关注：拆解卡优先写、收入变化优先提醒'); ctx.refresh();
  } }, c.watch ? '★ 已关注' : '☆ 关注');
  const aiSel = h('select', { title: '是不是 AI 产品；选「不是」后从创业公司列表里隐藏', onchange: async (ev) => {
    await api.patch(`/api/intel/companies/${c.id}`, { ai: +ev.target.value }); toast('已更新');
  } }, [[1, 'AI 产品'], [0, '不是 AI'], [-1, '待定']].map(([v, t]) => h('option', { value: v, selected: c.ai === v }, t)));
  const sub = [c.track_name || '待归类', last.date ? `MRR ${usd(last.mrr ?? last.revenue_30d)}（${last.date}）` : null,
    x.country, x.founded ? `成立 ${x.founded}` : null].filter(Boolean).join(' · ');
  el.append(ui.pageHead(c.name, sub, [h('div.it-acts', {}, [aiSel, trackSel, watchBtn])]));
  el.append(ui.stats([
    { k: 'MRR', v: usd(last.mrr) }, { k: '30 天增长', v: last.growth_30d == null ? '-' : `${Math.round(last.growth_30d)}%` },
    { k: '近 30 天收入', v: usd(last.revenue_30d) }, { k: '累计收入', v: usd(last.total_revenue) },
    { k: '订阅数', v: last.subscriptions ?? '-' }, ...(last.on_sale === 1 ? [{ k: '挂牌价', v: usd(last.asking_price) }] : []),
  ]));
  el.append(ui.section('收入走势', `近一年 · verified ${c.metrics.length} 天 · reported ${c.reported.length} 条`));
  el.append(h('div.card', {}, revenueChart(h, c.metrics, c.reported) || ui.empty('还没有收入数据', '每天跑一次 TrustMRR 快照')));
  if (c.reported.length) {
    el.append(h('div.card', { style: { marginTop: '8px' } }, c.reported.slice().reverse().map((r) => h('div.it-src', {}, [tag(h, ['reported', 'gray']), ' ',
      `${r.date} · ${r.metric.toUpperCase()} ${usd(r.value)} · `, r.source?.startsWith('http') ? h('a', { href: r.source, target: '_blank' }, '出处') : r.source || '',
      r.note ? h('div.muted', {}, `“${r.note}”`) : null]))));
  }
  const kv = [['网站', x.website && h('a', { href: x.website, target: '_blank' }, x.website)], ['一句话', x.description], ['卖给谁', x.audience || x.persona],
    ['价值主张', x.value_prop], ['解决的问题', x.problem], ['定价', x.pricing], ['渠道', (x.channels || []).join('、')],
    ['创始人', [x.founder, x.x ? h('a', { href: `https://x.com/${x.x.replace(/^@/, '')}`, target: '_blank' }, ` @${x.x.replace(/^@/, '')}`) : null,
      x.x_followers ? `（${x.x_followers} 粉丝）` : null].filter(Boolean)], ['TrustMRR', x.trustmrr && h('a', { href: `https://trustmrr.com/startup/${x.trustmrr}`, target: '_blank' }, x.trustmrr)],
    ['挂牌说明', x.seller_note]].filter(([, v]) => v && (!Array.isArray(v) || v.length));
  if (kv.length) el.append(ui.section('基本信息', '来自 TrustMRR 详情页'), h('div.card', {}, h('div.it-kv', {}, kv.flatMap(([k, v]) => [h('div', {}, k), h('div', {}, v)]))));

  const ps = PROFILE[c.profile_status];
  const regen = h('button.ghost', { onclick: async () => {
    regen.disabled = true; const r = await api.post(`/api/intel/companies/${c.id}/profile`);
    toast('已提交：Claude 联网查渠道和打法，几分钟后刷新'); await api.waitJob(r.job_id); ctx.refresh();
  } }, [ui.icon('refresh'), c.profile ? ' 重写拆解卡' : ' 写拆解卡']);
  el.append(h('div.section-title', {}, ['生意拆解卡', h('span.extra', {}, [ps ? ps[0] : '未生成', ' ', regen])]));
  if (c.profile?.content) {
    if (c.profile.missing.length) el.append(h('div.card', { style: { borderColor: 'var(--warn)' } }, `缺少：${c.profile.missing.join('、')}`));
    el.append(h('div.card', {}, cardMd(md, c.profile.content)));
    el.append(h('div.muted', { style: { fontSize: '12px', marginTop: '6px' } }, `${c.profile.created_at.slice(0, 16)} 生成${c.profile_versions > 1 ? ` · 共 ${c.profile_versions} 版` : ''}`));
  } else {
    el.append(ui.empty(c.profile_status === 'queued' ? '后台正在写拆解卡' : '还没有拆解卡',
      '每天自动写 10 张：关注的 > 收入异动 > 高增长 > 新挂牌 > 赛道前 10；也可以点「写拆解卡」'));
  }

  // BizPeel 只放链接 + 手动粘贴：粘进来的内容会作为写拆解卡的材料
  const biz = h('input', { placeholder: 'https://bizpeel.com/…', value: x.bizpeel_url || '', style: { flex: '1', minWidth: '240px' } });
  const notes = h('textarea', { rows: 5, placeholder: '粘贴 BizPeel / 访谈 / 自己的观察，写拆解卡时会一并参考', style: { width: '100%' } });
  notes.value = x.notes || '';
  el.append(ui.section('资料与笔记', 'BizPeel 不自动抓取'), h('div.card', {}, [
    h('div.it-filters', {}, [biz, x.bizpeel_url ? h('a', { href: x.bizpeel_url, target: '_blank' }, '打开') : null]), notes,
    h('div', { style: { marginTop: '8px' } }, h('button.primary', { onclick: async () => {
      await api.patch(`/api/intel/companies/${c.id}`, { ext: { bizpeel_url: biz.value.trim(), notes: notes.value } }); toast('已保存；重写拆解卡时会用上');
    } }, '保存'))]));
  el.append(ui.section('收入事件'));
  el.append(...(c.events.length ? groupByDay(h, c.events, { showCompany: false }) : [ui.empty('还没有收入异动', '第一天只记基线，之后过里程碑 / 暴涨 / 下滑 / 挂牌才会记')]));
}

async function renderStartups(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const qs = new URLSearchParams({ track: ss.track, sort: ss.sort, q: ss.q, watch: ss.watch ? 1 : 0, all: ss.all ? 1 : 0 });
  const d = await api.get('/api/intel/startups?' + qs);
  const last = d.last || {};
  const runBtn = h('button.ghost', { onclick: async () => {
    const r = await api.post('/api/intel/startups/run', { force_fetch: true });
    toast(r.started ? '开始：TrustMRR 快照 → 赛道归类 → PH 日榜 → 公开 ARR → 拆解卡排队，几分钟后刷新' : '上一轮还在跑');
  } }, [ui.icon('refresh'), ' 立即抓取']);
  el.append(ui.pageHead('产品雷达 · 创业公司', `${d.total} 家有收入的 AI 创业公司 · 数据来自 TrustMRR（verified）+ 公开报道（reported）` +
    (last.at ? ` · 上次快照 ${ago(last.at)}` : ''), [runBtn]));
  el.append(ui.stats([
    { k: '在看', v: d.total },
    { k: '关注', v: ss.watch ? '只看关注' : '全部', active: ss.watch, onClick: () => { ss.watch = !ss.watch; ctx.refresh(); } },
    { k: '待归赛道', v: d.pending_tracks },
    { k: '今日拆解卡', v: `${d.profiles_today}/${d.profiles_per_day}` },
    ...(last.errors?.length ? [{ k: '上次错误', v: last.errors.length, title: last.errors.join('\n') }] : []),
  ]));
  const trSel = h('select', { onchange: (e) => { ss.track = e.target.value; ctx.refresh(); } },
    [h('option', { value: '' }, '全部赛道'), ...d.tracks.map((t) => h('option', { value: t.slug, selected: ss.track === t.slug }, t.name))]);
  const sortSel = h('select', { onchange: (e) => { ss.sort = e.target.value; ctx.refresh(); } },
    [['rev', '按 MRR'], ['growth', '按 30 天增长'], ['reported', '按公开 ARR']].map(([v, t]) => h('option', { value: v, selected: ss.sort === v }, t)));
  const q = h('input', { placeholder: '搜名称 / 描述', value: ss.q, onkeydown: (e) => { if (e.key === 'Enter') { ss.q = e.target.value; ctx.refresh(); } } });
  const allBox = h('label.muted', { style: { fontSize: '13px' } }, [h('input', { type: 'checkbox', checked: ss.all, onchange: (e) => { ss.all = e.target.checked; ctx.refresh(); } }), ' 含非 AI / 待定']);
  el.append(tabs(h, '#intel/startups'), h('div.it-filters', {}, [trSel, sortSel, q, allBox]));
  if (!d.startups.length) {
    el.append(ui.empty('还没有创业公司数据', '后台每天跑一次 TrustMRR 快照；也可以点「立即抓取」'));
    return;
  }
  el.append(h('div.card', { style: { overflowX: 'auto' } }, startupTable(h, d.startups)));
}

async function renderTracks(el, ctx) {
  const { api, h, ui } = ctx;
  const ts = await api.get('/api/intel/tracks');
  el.append(ui.pageHead('产品雷达 · 赛道', '16 个固定赛道 · 模型归类，可在公司页手动改'), tabs(h, '#intel/tracks'));
  el.append(h('div.it-tracks', {}, ts.map((t) => h('div.card.it-track', { onclick: () => { location.hash = `#intel/t/${t.slug}`; } }, [
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' } }, [h('b', {}, t.name), h('span.n', {}, t.companies)]),
    h('div.scope', {}, t.scope),
    h('div.muted', { style: { fontSize: '12.5px' } }, [`合计 MRR ${usd(t.total_rev)} · 增长中位数 `, pct(h, t.median_growth),
      ` · ${t.growing} 家在涨${t.on_sale ? ` · ${t.on_sale} 家在售` : ''}${t.events_30d ? ` · 30 天 ${t.events_30d} 个事件` : ''}`]),
    t.top.length ? h('div', { style: { fontSize: '12.5px', marginTop: '4px' } }, t.top.map((x) => `${x.name} ${usd(x.rev)}`).join(' · ')) : null,
  ]))));
}

async function renderTrack(el, ctx, slug) {
  const { api, h, ui } = ctx;
  const t = await api.get(`/api/intel/tracks/${slug}`);
  t.events.forEach((e) => { e.type_name = { revenue: '收入异动', listing: '挂牌出售' }[e.type] || e.type; });
  el.append(h('div.muted', { style: { marginBottom: '8px' } }, h('a', { href: '#intel/tracks' }, '← 赛道')));
  el.append(ui.pageHead(t.name, t.scope));
  el.append(ui.stats([{ k: '公司', v: t.companies }, { k: '合计 MRR', v: usd(t.total_rev) },
    { k: '增长中位数', v: t.median_growth == null ? '-' : `${Math.round(t.median_growth)}%` }, { k: '在涨', v: t.growing }, { k: '在售', v: t.on_sale }]));
  el.append(ui.section('公司', '按 MRR'), t.startups.length ? h('div.card', { style: { overflowX: 'auto' } }, startupTable(h, t.startups, { showTrack: false })) : ui.empty('这个赛道还没有公司'));
  el.append(ui.section('收入事件', '近 60 天'), ...(t.events.length ? groupByDay(h, t.events) : [ui.empty('近 60 天没有收入异动')]));
  if (t.ph.length) {
    el.append(ui.section('Product Hunt 上的同赛道产品', '近 14 天日榜'), h('div.card', {}, t.ph.map((p) => phRow(h, p, p.date))));
  }
}

function phRow(h, p, day = '') {
  return h('div.it-ph', {}, [h('div.rk', {}, p.rank), h('div', {}, [
    h('a', { href: p.url, target: '_blank' }, h('b', {}, p.title)),
    p.why ? h('div', { style: { opacity: '.85' } }, p.why) : null,
    h('div.it-meta', {}, [day ? h('span', {}, day) : null, p.track ? h('a', { href: `#intel/t/${p.track}` }, p.track_name || p.track) : h('span', {}, '未归赛道'),
      ...(p.topics || []).slice(0, 3).map((x) => h('span', {}, x)), p.website ? h('a', { href: p.website, target: '_blank' }, '官网') : null]),
  ]), h('div.muted', { style: { fontSize: '12.5px', textAlign: 'right' } }, [`▲ ${p.votes}`, p.comments ? h('div', {}, `💬 ${p.comments}`) : null])]);
}

async function renderPh(el, ctx) {
  const { api, h, ui } = ctx;
  const days = await api.get('/api/intel/ph?days=7');
  el.append(ui.pageHead('产品雷达 · PH 日榜', '信息推荐收到的 Product Hunt 条目 · 每天取票数前 20 · DeepSeek 归赛道 + 一句话解读'), tabs(h, '#intel/ph'));
  if (!days.length) {
    el.append(ui.empty('还没有日榜解读', '信息推荐板块里有 Product Hunt 条目后，过完的那天会自动出解读'));
    return;
  }
  for (const d of days) {
    el.append(ui.section(d.date, `${d.items.length} 个产品`));
    if (d.summary) el.append(h('div.card', { style: { marginBottom: '8px' } }, d.summary));
    el.append(h('div.card', {}, d.items.map((p) => phRow(h, p))));
  }
}

async function renderCompanies(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const cos = await api.get('/api/intel/companies');
  el.append(ui.pageHead('产品雷达 · 公司', `${cos.filter((c) => c.enabled).length} 家在跟`));
  el.append(tabs(h, '#intel/companies'));
  const rows = cos.map((c) => h('tr', {}, [
    h('td', {}, h('a', { href: `#intel/c/${c.slug}` }, c.name)), h('td', {}, `T${c.tier}`), h('td.muted', {}, c.category),
    h('td', {}, String(c.events)), h('td.muted', {}, c.latest || '-'),
    h('td', {}, `${c.sources.filter((s) => s.enabled && !s.last_err).length}/${c.sources.length}`),
    h('td', {}, h('input', { type: 'checkbox', checked: !!c.enabled, onchange: async (ev) => {
      await api.patch(`/api/intel/companies/${c.id}`, { enabled: ev.target.checked ? 1 : 0 }); toast(ev.target.checked ? '已开启' : '已暂停');
    } })),
  ]));
  el.append(h('div.card', {}, h('table.it-tbl', {}, [h('tr', {}, ['公司', '层级', '方向', '事件', '最近', '源正常', '跟踪'].map((t) => h('th', {}, t))), ...rows])));
  const name = h('input', { placeholder: '公司名，如 Windsurf' });
  const tier = h('select', {}, [1, 2, 3].map((t) => h('option', { value: t, selected: t === 3 }, `T${t}`)));
  el.append(ui.section('加一家'), h('div.it-filters', {}, [name, tier, h('button.primary', { onclick: async () => {
    if (!name.value.trim()) return;
    const r = await api.post('/api/intel/companies', { name: name.value.trim(), tier: +tier.value });
    toast('已加入；到「信息源」给它加 changelog / 定价页'); location.hash = `#intel/c/${r.slug}`;
  } }, '加入')]));
}

async function renderSources(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const [srcs, cos] = await Promise.all([api.get('/api/intel/sources'), api.get('/api/intel/companies')]);
  el.append(ui.pageHead('产品雷达 · 信息源', `${srcs.length} 个官方源 · 异常 ${srcs.filter((s) => s.enabled && s.last_err).length} 个`));
  el.append(tabs(h, '#intel/sources'));
  const rows = srcs.map((s) => h('tr', {}, [
    h('td', {}, s.company_name), h('td', {}, s.kind), h('td', {}, [h('a', { href: s.url, target: '_blank' }, s.label || s.url),
      s.note ? h('div.muted', {}, s.note) : null]),
    h('td.muted', {}, `${s.snapshots} 版 · ${s.candidates} 条`), h('td.muted', {}, ago(s.last_ok)),
    h('td' + (s.last_err ? '.err' : ''), {}, s.last_err || (s.last_ok ? '正常' : '未抓')),
    h('td', {}, [h('button.ghost', { onclick: async (ev) => {
      ev.target.disabled = true; const r = await api.post(`/api/intel/sources/${s.id}/fetch`);
      toast(r.ok ? `抓到 ${r.candidates || 0} 条候选${r.unchanged ? '（没变化）' : ''}` : `失败：${r.error}`, !r.ok); ctx.refresh();
    } }, '抓'), ' ', h('input', { type: 'checkbox', checked: !!s.enabled, title: '启用', onchange: async (ev) => {
      await api.patch(`/api/intel/sources/${s.id}`, { enabled: ev.target.checked ? 1 : 0 });
    } })]),
  ]));
  el.append(h('div.card', {}, h('table.it-tbl', {}, [h('tr', {}, ['公司', '类型', '链接', '快照 / 候选', '上次成功', '状态', ''].map((t) => h('th', {}, t))), ...rows])));
  const co = h('select', {}, cos.map((c) => h('option', { value: c.id }, c.name)));
  const kind = h('select', {}, ['changelog', 'pricing', 'rss', 'docs'].map((k) => h('option', { value: k }, k)));
  const url = h('input', { placeholder: 'https://…', style: { minWidth: '320px' } });
  const label = h('input', { placeholder: '名称，如 Cursor Changelog' });
  el.append(ui.section('加一个源', 'changelog / docs：快照 diff；pricing：结构化后对比；rss：直接收条目'), h('div.it-filters', {}, [co, kind, url, label,
    h('button.primary', { onclick: async () => {
      if (!url.value.trim()) return;
      await api.post('/api/intel/sources', { company_id: +co.value, kind: kind.value, url: url.value.trim(), label: label.value.trim() });
      toast('已加入，下一轮会抓'); ctx.refresh();
    } }, '加入')]));
}

export default {
  async render(el, ctx) {
    if (!document.getElementById('it-css')) document.head.append(ctx.h('style#it-css', {}, CSS));
    const [view, arg] = ctx.sub;
    if (view === 'e' && arg) return renderEvent(el, ctx, arg);
    if (view === 'c' && arg) return renderCompany(el, ctx, decodeURIComponent(arg));
    if (view === 'companies') return renderCompanies(el, ctx);
    if (view === 'sources') return renderSources(el, ctx);
    if (view === 'startups') return renderStartups(el, ctx);
    if (view === 'tracks') return renderTracks(el, ctx);
    if (view === 't' && arg) return renderTrack(el, ctx, arg);
    if (view === 'ph') return renderPh(el, ctx);
    return renderStream(el, ctx);
  },
};
