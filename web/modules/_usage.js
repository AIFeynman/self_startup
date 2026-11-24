// 大模型用量（复盘 · 用量）：每天的等价费用 / token，按类型（后台任务 / 讨论 / Claude 批量与单次调用 / DeepSeek / 其他 API）堆叠，下面按板块拆开
// 数据：/api/usage?start=&end=（llm_usage 表；Claude 订阅下费用是 CLI 报的等价美元）
// 用法：import { usagePanel } from './_usage.js'; el.append(await usagePanel(ctx, { end: date }))
const KINDS = [
  { id: 'job', name: '后台 Agent 任务', light: '#2a78d6', dark: '#3987e5' },
  { id: 'chat', name: '讨论', light: '#eb6834', dark: '#d95926' },
  { id: 'light', name: 'Claude 批量与单次调用', light: '#1baf7a', dark: '#199e70' },
  { id: 'deepseek', name: 'DeepSeek', light: '#eda100', dark: '#c98500' },
  { id: 'api', name: 'Jev / 百炼语音', light: '#6250d6', dark: '#9085e9' },
];
const EXTRA_NAMES = { xart: 'X 长文', paper: '论文库', oss: '开源项目', verify: '验证', annotate: '文档批注', voice: '语音', people: '名人动态', eval: '评测脚本', nomod: '其他' };
const METRICS = { cost: '等价费用', tokens: 'token' };

const tokensOf = (r) => r.input_tokens + r.output_tokens + r.cache_read + r.cache_write;
const valueOf = (r, metric) => (metric === 'cost' ? r.cost_usd : tokensOf(r));
const usd = (v) => (v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`);
const tok = (v) => (v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(v));
const fmt = (v, metric) => (metric === 'cost' ? usd(v) : tok(v));
const shift = (day, n) => { const d = new Date(day + 'T12:00:00'); d.setDate(d.getDate() + n); return d.toLocaleDateString('sv-SE'); };

export async function usagePanel(ctx, { end }) {
  const { api, h, ui } = ctx;
  injectStyle();
  const names = Object.fromEntries((await api.get('/api/meta').catch(() => ({ modules: [] }))).modules.map((m) => [m.id, m.title]));
  const moduleName = (m) => (m.startsWith('chat:') ? `讨论 · ${moduleName(m.slice(5))}` : names[m] || EXTRA_NAMES[m] || m);
  const state = { start: shift(end, -29), end, metric: 'cost' };
  const box = h('div.us');

  const startIn = h('input', { type: 'date', value: state.start, onchange: (e) => { state.start = e.target.value; load(); } });
  const endIn = h('input', { type: 'date', value: state.end, onchange: (e) => { state.end = e.target.value; load(); } });
  const preset = (n) => h('button.chip', { onclick: () => { state.start = shift(state.end, -(n - 1)); startIn.value = state.start; load(); } }, `近 ${n} 天`);
  const metricBtns = Object.entries(METRICS).map(([k, v]) => h('button.chip' + (k === state.metric ? '.on' : ''), {
    onclick: (e) => { state.metric = k; metricBtns.forEach((b) => b.classList.toggle('on', b === e.currentTarget)); paint(); } }, v));
  const filters = h('div.us-filters', {}, [h('div.rv-range', {}, [startIn, '—', endIn]), preset(7), preset(30)]);
  const content = h('div');
  box.append(filters, content);
  let data = null;

  async function load() {
    content.replaceChildren(h('div.muted', {}, h('span.dots', {}, '汇总用量')));
    try {
      data = await api.get(`/api/usage?start=${state.start}&end=${state.end}`);
      paint();
    } catch (e) { content.replaceChildren(h('div.muted', {}, '读取失败：' + e.message)); }
  }

  function paint() {
    const rows = data.rows;
    const days = [];
    for (let d = data.start; d <= data.end; d = shift(d, 1)) days.push(d);
    const total = rows.reduce((a, r) => ({ cost: a.cost + r.cost_usd, tokens: a.tokens + tokensOf(r), calls: a.calls + r.calls }), { cost: 0, tokens: 0, calls: 0 });
    const active = new Set(rows.map((r) => r.day)).size;
    const note = data.since ? `从 ${data.since} 开始记录；之前的调用没有用量数据` : '还没有用量记录';
    const tiles = ui.stats([
      { k: '等价费用（美元）', v: usd(total.cost) },
      { k: 'token（含缓存读写）', v: tok(total.tokens) },
      { k: '调用次数', v: String(total.calls) },
      { k: `日均费用（${active || 0} 天有记录）`, v: usd(active ? total.cost / active : 0) },
    ]);
    if (!rows.length) {
      content.replaceChildren(tiles, h('div.card.flat.muted', {}, `这段时间没有用量。${note}`));
      return;
    }
    content.replaceChildren(tiles, chart(days, rows), h('div.muted.us-note', {}, note + '。Claude 走订阅，费用是 CLI 报的等价价，不是实际扣费；DeepSeek 搜索、Jev 没有单价，只算调用次数；百炼按人民币折美元。'),
      byKind(rows, total), byDay(days, rows));
  }

  function chart(days, rows) {
    const m = state.metric;
    const per = Object.fromEntries(days.map((d) => [d, Object.fromEntries(KINDS.map((k) => [k.id, 0]))]));
    rows.forEach((r) => { if (per[r.day]) per[r.day][r.kind] += valueOf(r, m); });
    const sums = days.map((d) => KINDS.reduce((a, k) => a + per[d][k.id], 0));
    const max = Math.max(...sums, 1e-9);
    const tip = h('div.us-tip', { hidden: true });
    const showTip = (e, d) => {
      tip.replaceChildren(h('b', {}, d), ...KINDS.filter((k) => per[d][k.id]).map((k) =>
        h('div.us-tip-row', {}, [h('i', { style: { background: `var(--us-${k.id})` } }), h('span', {}, k.name), h('span.grow'), h('span', {}, fmt(per[d][k.id], m))])),
      h('div.us-tip-row.total', {}, [h('span', {}, '合计'), h('span.grow'), h('span', {}, fmt(KINDS.reduce((a, k) => a + per[d][k.id], 0), m))]));
      tip.hidden = false;
      const r = e.currentTarget.getBoundingClientRect(), p = plot.getBoundingClientRect();
      tip.style.left = `${Math.min(Math.max(r.left - p.left + r.width / 2, 80), p.width - 80)}px`;
    };
    const cols = days.map((d, i) => h('div.us-col', { onmouseenter: (e) => showTip(e, d), onmouseleave: () => { tip.hidden = true; } },
      h('div.us-stack', { style: { height: `${sums[i] / max * 100}%` } }, KINDS.filter((k) => per[d][k.id] > 0).map((k) =>
        h('div.us-seg', { style: { flexGrow: per[d][k.id] / sums[i], background: `var(--us-${k.id})` } })).reverse())));
    const plot = h('div.us-plot', {}, [h('div.us-max', {}, fmt(max, m)), ...cols, tip]);
    const step = Math.ceil(days.length / 8);
    const axis = h('div.us-axis', {}, days.map((d, i) => h('span', {}, (days.length - 1 - i) % step === 0 ? d.slice(5) : '')));
    const legend = h('div.us-legend', {}, KINDS.map((k) => h('span', {}, [h('i', { style: { background: `var(--us-${k.id})` } }), k.name])));
    return h('div.card.flat.us-chart', {}, [h('div.row', {}, [h('span.card-label', {}, `每天${METRICS[m]}`), h('span.grow'), ...metricBtns]), plot, axis, legend]);
  }

  function byKind(rows, total) {
    const groups = KINDS.map((k) => {
      const mods = {};
      rows.filter((r) => r.kind === k.id).forEach((r) => {
        const x = mods[r.module] ||= { module: r.module, calls: 0, input_tokens: 0, output_tokens: 0, cache_read: 0, cache_write: 0, cost_usd: 0 };
        ['calls', 'input_tokens', 'output_tokens', 'cache_read', 'cache_write', 'cost_usd'].forEach((f) => { x[f] += r[f]; });
      });
      const list = Object.values(mods).sort((a, b) => b.cost_usd - a.cost_usd || tokensOf(b) - tokensOf(a));
      const sum = list.reduce((a, x) => Object.fromEntries(Object.keys(a).map((f) => [f, a[f] + x[f]])),
        { calls: 0, input_tokens: 0, cache_read: 0, cache_write: 0, output_tokens: 0, cost_usd: 0 });
      return { k, list, sum };
    }).filter((g) => g.list.length);
    const head = h('tr', {}, ['类型 / 板块', '调用', '输入', '缓存读', '缓存写', '输出', '费用', '占比'].map((t, i) => h(i ? 'th.n' : 'th', {}, t)));
    const body = groups.flatMap(({ k, list, sum }) => [
      h('tr.us-group', {}, [h('td', {}, [h('i.us-dot', { style: { background: `var(--us-${k.id})` } }), k.name]), h('td.n', {}, String(sum.calls)),
        ...['input_tokens', 'cache_read', 'cache_write', 'output_tokens'].map((f) => h('td.n', {}, tok(sum[f]))), h('td.n', {}, usd(sum.cost_usd)),
        h('td.n', {}, total.cost ? `${Math.round(sum.cost_usd / total.cost * 100)}%` : '—')]),
      ...list.map((x) => h('tr', {}, [h('td.us-mod', {}, moduleName(x.module)), h('td.n', {}, String(x.calls)), h('td.n', {}, tok(x.input_tokens)),
        h('td.n', {}, tok(x.cache_read)), h('td.n', {}, tok(x.cache_write)), h('td.n', {}, tok(x.output_tokens)), h('td.n', {}, usd(x.cost_usd)),
        h('td.n', {}, total.cost ? `${Math.round(x.cost_usd / total.cost * 100)}%` : '—')])),
    ]);
    return h('div.card.flat', {}, [h('div.card-label', {}, '按类型和板块'), h('div.us-scroll', {}, h('table.us-table', {}, [h('thead', {}, head), h('tbody', {}, body)]))]);
  }

  function byDay(days, rows) {
    const list = days.slice().reverse().map((d) => {
      const rs = rows.filter((r) => r.day === d);
      const by = Object.fromEntries(KINDS.map((k) => [k.id, rs.filter((r) => r.kind === k.id).reduce((a, r) => a + r.cost_usd, 0)]));
      return { d, rs, by, cost: rs.reduce((a, r) => a + r.cost_usd, 0), tokens: rs.reduce((a, r) => a + tokensOf(r), 0), calls: rs.reduce((a, r) => a + r.calls, 0) };
    }).filter((x) => x.rs.length);
    const head = h('tr', {}, ['日期', '调用', 'token', ...KINDS.map((k) => k.name), '合计费用'].map((t, i) => h(i ? 'th.n' : 'th', {}, t)));
    const body = list.map((x) => h('tr', {}, [h('td', {}, x.d), h('td.n', {}, String(x.calls)), h('td.n', {}, tok(x.tokens)),
      ...KINDS.map((k) => h('td.n', {}, x.by[k.id] ? usd(x.by[k.id]) : '—')), h('td.n', {}, h('b', {}, usd(x.cost)))]));
    return h('details.card.flat.us-days', { open: true }, [h('summary', {}, h('span.card-label', {}, `每天明细（${list.length} 天）`)),
      h('div.us-scroll', {}, h('table.us-table', {}, [h('thead', {}, head), h('tbody', {}, body)]))]);
  }

  await load();
  return box;
}

function injectStyle() {
  if (document.getElementById('us-css')) return;
  const s = document.createElement('style');
  s.id = 'us-css';
  s.textContent = `
.us { ${KINDS.map((k) => `--us-${k.id}: ${k.light};`).join(' ')} }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .us { ${KINDS.map((k) => `--us-${k.id}: ${k.dark};`).join(' ')} } }
:root[data-theme="dark"] .us { ${KINDS.map((k) => `--us-${k.id}: ${k.dark};`).join(' ')} }
.us-filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }
.us-filters .rv-range { margin: 0; }
.us-chart { margin-top: 14px; }
.us-chart > .row { flex-wrap: wrap; gap: 8px; }
.us-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12.5px; color: var(--muted); margin-top: 10px; }
.us-legend i, .us-tip i, .us-dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
.us-plot { position: relative; display: flex; align-items: flex-end; gap: 2px; height: 180px; margin-top: 12px; padding-top: 16px; border-bottom: 1px solid var(--line-2); }
.us-max { position: absolute; top: 0; left: 0; font-size: 11.5px; color: var(--muted); border-top: 1px dashed var(--line-2); width: 100%; padding-top: 2px; }
.us-col { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 0; cursor: default; }
.us-col:hover { background: var(--bg-2); }
.us-stack { width: 100%; max-width: 28px; margin: 0 auto; display: flex; flex-direction: column; gap: 2px; min-height: 0; }
.us-stack:not(:empty) { min-height: 2px; }
.us-seg { min-height: 1px; flex-basis: 0; }
.us-seg:first-child { border-radius: 4px 4px 0 0; }
.us-tip { position: absolute; top: 8px; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--line-2); border-radius: 8px; padding: 8px 10px;
  font-size: 12.5px; box-shadow: var(--shadow); min-width: 190px; pointer-events: none; z-index: 2; }
.us-tip-row { display: flex; align-items: center; gap: 4px; margin-top: 3px; white-space: nowrap; }
.us-tip-row .grow { min-width: 12px; }
.us-tip-row.total { border-top: 1px solid var(--line); padding-top: 4px; font-weight: 600; }
.us-axis { display: flex; gap: 2px; font-size: 11px; color: var(--muted); margin-top: 4px; }
.us-axis span { flex: 1; text-align: center; white-space: nowrap; overflow: visible; min-width: 0; }
.us-note { font-size: 12.5px; margin: 8px 2px 14px; }
.us-scroll { overflow-x: auto; }
.us-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.us-table th, .us-table td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
.us-table th { color: var(--muted); font-weight: 500; font-size: 12px; }
.us-table .n { text-align: right; font-variant-numeric: tabular-nums; }
.us-group td { font-weight: 600; background: var(--bg-2); }
.us-mod { padding-left: 26px !important; color: var(--muted); }
.us-days { margin-top: 14px; }
.us-days summary { cursor: pointer; }
`;
  document.head.append(s);
}
