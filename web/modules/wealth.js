// 理财板块：目标（一年收益目标 + 分配 + 挂单）/ 减持（美团阶梯挂单 + 换 QQQ）/ 通知（信号变化与每日汇总）。
// 计算全在后端 /api/wealth/*（从 wealth 仓库迁来），这里只负责展示；统计估算，不构成投资建议。
const TABS = [['target', '目标'], ['sell', '减持'], ['alerts', '通知']];
const MODES = { safe: '稳妥', aggressive: '进取' };
const BOND = 'BOND.CN';
const SERIES = { QQQ: 's0', GOOGL: 's1', MSFT: 's2', '512890.SS': 's3', [BOND]: 's4', portfolio: 'sp' };
const REFS = { QQQ: '100% QQQ', '512890.SS': '100% 红利低波', [BOND]: '100% 纯债基金' };
const LADDER_NAMES = { '^NDX': '纳指100（长历史）' };
const HORIZONS = { 21: '1个月', 63: '3个月', 126: '6个月', 252: '12个月', 756: '3年', 1260: '5年' };
const SHAPES = { concentrated: '集中（≈上限）', balanced: '均衡', wide: '分散' };
const SHAPE_NOTES = {
  concentrated: '全部挂在目标价：达标概率最高，但没碰到就一股不卖，下行最大',
  balanced: '目标价上下分几档：达标概率居中，部分成交托底',
  wide: '更低起步、更高封顶：最平滑，达标概率最低',
};
const SW_REST = { hold: '其余继续持有', ladder: '其余按挂单，成交即换' };
const SW_METRIC = { median_ratio: ['中位数', 'median'], mean_ratio: ['平均', 'mean'], p10_ratio: ['悲观10%', 'p10'] };
const DISCLAIMER = '统计估算，不构成投资建议。';

// 偏好只存在本浏览器（目标、方案、买法、到账延迟、换仓假设）
const store = {
  get(k, d) { try { const v = localStorage.getItem('wealth-' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('wealth-' + k, JSON.stringify(v)); } catch { /* 无痕模式 */ } },
};
const tp = { target: store.get('target', 0.10), mode: store.get('mode', 'safe'), shape: store.get('shape', 'balanced'), delay: store.get('delay', 1), drawdown: store.get('drawdown', 0.05), data: null, seq: 0, timer: null };
const sp = { target: null, horizon: null, shape: null, now: null, compare: null, metric: 'median_ratio', data: null, seq: 0, timer: null, saveTimer: null, pending: null, ...store.get('switch', {}) };

// ---------------------------------------------------------------- 格式
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? esc(u) : '#');
const pr = (v) => (v == null ? '—' : v > 0 && v < 0.001 ? '<0.1%' : `${(v * 100).toFixed(v > 0 && v < 0.01 ? 1 : 0)}%`);
const ret = (v, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`);
const pctv = (v, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`);   // 已经是百分数
const money = (v, d = 2) => (v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }));
const int = (v) => (v == null ? '—' : Math.round(v).toLocaleString('zh-CN'));
const times = (v) => (v == null ? '—' : `${v.toFixed(2)}×`);
const tone = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');
const price = (v, cur) => (v == null ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: cur === 'CNY' ? 3 : 2, maximumFractionDigits: cur === 'CNY' ? 3 : 2 }));
const day = (iso) => (iso ? String(iso).slice(0, 10) : '今天');
const local = (v) => { if (!v) return '—'; const d = new Date(typeof v === 'number' ? v : v); return isNaN(d) ? String(v) : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); };
const after = (iso, months) => { const d = iso ? new Date(iso) : new Date(); d.setMonth(d.getMonth() + months); return d.toISOString().slice(0, 10); };
const horizonName = (d) => HORIZONS[d] || `${d}个交易日`;
const kpis = (rows, cls = '') => `<div class="wl-kpis ${cls}">${rows.map(([k, v, note, hero]) => `<div class="stat${hero ? ' wl-hero' : ''}"><span class="k">${k}</span><span class="v num">${v}</span>${note ? `<small>${esc(note)}</small>` : ''}</div>`).join('')}</div>`;
const table = (head, body, cls = '') => `<div class="wl-scroll"><table class="wl-table ${cls}"><thead><tr>${head.map((x) => `<th>${x}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
const bar = (v, scale = 1, text = pr(v)) => `<span class="wl-bar"><i style="width:${scale ? Math.min(100, (v || 0) / scale * 100).toFixed(1) : 0}%"></i><b>${text}</b></span>`;
const emptyText = (t) => `<p class="muted wl-empty">${esc(t)}</p>`;
const list = (items) => `<ul class="wl-ul">${(items || []).map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`;
const card = (title, body, extra = '', cls = '') => `<section class="card wl-card ${cls}"><div class="row between wl-card-head"><div class="card-label">${title}</div>${extra ? `<span class="muted wl-extra">${extra}</span>` : ''}</div>${body}</section>`;
const seg = (name, items, active) => `<div class="tabs wl-seg" data-seg="${name}">${items.map(([v, label]) => `<button data-v="${esc(v)}" class="${String(v) === String(active) ? 'active' : ''}">${label}</button>`).join('')}</div>`;
const actionTag = (a) => `<span class="tag ${a === 'add' ? 'ok' : a === 'reduce' ? 'err' : 'gray'}">${a === 'add' ? '▲' : a === 'reduce' ? '▼' : '■'}</span>`;

// 折线图悬停：十字线 + 提示框；rows(x) 返回提示内容
function hover(box, { width, pad, xOf, nearest, tipHtml, onClick }) {
  const svg = box.querySelector('svg'), tip = box.querySelector('.wl-tip'), cross = svg.querySelector('.wl-cross'), hit = svg.querySelector('.wl-hit');
  const pick = (e) => { const r = svg.getBoundingClientRect(); return nearest((e.clientX - r.left) / r.width * width); };
  hit.addEventListener('mousemove', (e) => {
    const p = pick(e), cx = xOf(p);
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
    tip.hidden = false; tip.innerHTML = tipHtml(p);
    const left = cx / width * 100; tip.style.left = `${left}%`; tip.classList.toggle('flip', left > 55);
  });
  hit.addEventListener('mouseleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); });
  if (onClick) hit.addEventListener('click', (e) => onClick(pick(e)));
  void pad;
}
const chartFrame = (width, height, pad, inner, label) => `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}">${inner}
  <line class="wl-cross" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}" visibility="hidden"/>
  <rect class="wl-hit" x="${pad.left}" y="${pad.top}" width="${width - pad.left - pad.right}" height="${height - pad.top - pad.bottom}"/></svg><div class="wl-tip" hidden></div>`;

// ================================================================ 目标
const tpPlan = (d) => (tp.mode === 'safe' && d.safe ? d.safe : d.allocation);
const tpName = (d, s) => d.assets.find((a) => a.symbol === s)?.name || s;
const tpWeights = (d, w) => Object.entries(w).filter(([, x]) => x > 0).map(([s, x]) => `${tpName(d, s)} ${Math.round(x * 100)}%`).join(' · ');

async function loadTarget(box, ctx) {
  const seq = ++tp.seq;
  box.classList.add('wl-loading');
  try {
    const d = await ctx.api.get(`/api/wealth/target-plan?target=${tp.target}&delay=${tp.delay}&drawdown=${tp.drawdown}`);
    if (seq !== tp.seq) return;
    tp.data = d; renderTarget(box, ctx);
  } catch (e) {
    if (seq === tp.seq) box.innerHTML = card('无法计算', emptyText(e.message));
  } finally { if (seq === tp.seq) box.classList.remove('wl-loading'); }
}

function renderTarget(box, ctx) {
  const d = tp.data;
  if (!d.safe) tp.mode = 'aggressive';
  const al = d.allocation, plan = tpPlan(d), s = plan.stats, funding = al.funding, hist = plan.history;
  const delay = d.delay || { months: 0, held_days: 252, options: [0, 1, 2, 3] }, waiting = delay.months > 0;
  const span = waiting ? `持有 ${delay.held_days} 个交易日` : '一年';
  const histNote = hist ? `${hist.start.slice(0, 4)} 年起 ${hist.n} 个${span}窗口（约 ${hist.n_eff.toFixed(0)} 个独立年），最差 ${ret(hist.worst)}` : '历史太短';
  const wait = waiting && plan.no_wait ? `；钱今天就能用的话是 ${pr(plan.no_wait.probability)}` : '';
  const weights = tpWeights(d, plan.weights);
  const fund = ['可分配资金', funding ? `${int(funding.net)} ${funding.currency}` : '—', funding ? `美团剩余 ${int(funding.shares)} 股 × ${funding.price}，扣费 ${int(funding.costs)}、税 ${int(funding.tax)}` : '没有读到美团持仓'];
  const top = tp.mode === 'safe' ? [
    ['稳妥组合达标概率', pr(s.probability), (plan.relaxed ? `${weights}（没有组合同时满足三条约束，显示最不容易亏的）` : weights) + wait, true],
    ['一年不亏的概率', pr(s.nonneg), `约束 ≥ ${pr(plan.constraints.nonneg)}；亏超 10% 的概率 ${pr(s.loss10)}`],
    ['80% 把握的收益', ret(s.p20), `中位 ${ret(s.p50)}；悲观 10% ${ret(s.p10)}（约束不低于 ${ret(plan.constraints.p10_floor, 0)}）；乐观 10% ${ret(s.p90)}`],
    ['压力回撤', ret(s.stress_drawdown), `约束不超过 ${pr(plan.constraints.max_drawdown)}（${plan.constraints.stress_start.slice(0, 4)} 年起，不含 2000、2008）；实际历史 ${hist ? `${ret(hist.max_drawdown)}（${hist.start.slice(0, 4)} 年起）` : '—'}`],
    ['历史回放：不亏 / 达标', hist ? `${pr(hist.nonneg_rate)} / ${pr(hist.hit_rate)}` : '—', histNote], fund,
  ] : [
    ['组合达标概率', pr(s.probability), weights + wait, true],
    ['中位一年收益', ret(s.p50), `10%–90% 区间 ${ret(s.p10)} 到 ${ret(s.p90)}`],
    ['一年亏超 10%', pr(s.loss10), `约束：悲观 10% 不低于 ${ret(al.constraints.p10_floor, 0)}`],
    ['一年不亏的概率', pr(s.nonneg), `80% 把握的收益 ${ret(s.p20)}`],
    ['历史回放：不亏 / 达标', hist ? `${pr(hist.nonneg_rate)} / ${pr(hist.hit_rate)}` : '—', histNote], fund,
  ];
  const note = `一年后（${day(d.generated_at)} 起 252 个交易日）总收益 ≥ ${ret(d.target)}，各自币种计。`
    + (waiting ? `钱约 ${delay.months} 个月后（${after(d.generated_at, delay.months)}）到账，等待期间是现金、不计利息，实际只投资 ${delay.held_days} 个交易日。` : '') + (d.tax_note || '');
  const pct = Math.round(d.target * 1000) / 10;
  const ddPct = d.safe ? Math.round(d.safe.constraints.max_drawdown * 100) : null;
  const controls = `<section class="card wl-controls">
    <div class="wl-ctl"><label class="card-label">一年收益目标</label>
      <div class="row wl-target"><input type="number" id="tp-target" min="0" max="50" step="0.5" value="${pct}"><span>%</span>
        <input type="range" id="tp-range" min="0" max="30" step="0.5" value="${pct}">
        ${seg('preset', [[5, '5%'], [8, '8%'], [10, '10%'], [15, '15%'], [20, '20%']], pct)}</div></div>
    <div class="wl-ctl-row">
      <div class="wl-ctl"><label class="card-label">方案</label>${seg('mode', Object.entries(MODES), tp.mode)}</div>
      ${tp.mode === 'safe' && d.safe ? `<div class="wl-ctl"><label class="card-label">压力回撤上限</label>
        <div class="row wl-target"><input type="number" id="tp-drawdown" min="1" max="40" step="1" value="${ddPct}"><span>%</span>${seg('dd', [3, 5, 8, 10, 15, 20].map((v) => [v, `${v}%`]), ddPct)}</div></div>` : ''}
      <div class="wl-ctl"><label class="card-label">买法</label>${seg('shape', Object.entries(d.ladder_model.labels), tp.shape)}</div>
      <div class="wl-ctl"><label class="card-label">资金到账</label>${seg('delay', (delay.options || [0, 1, 2, 3]).map((m) => [m, m ? `${m} 个月后` : '今天']), delay.months)}</div>
    </div>
    <p class="muted wl-note">${esc(note)}</p></section>`;
  box.innerHTML = controls + kpis(top) + `<h3 class="wl-h">逐个标的：加仓、持有还是减仓</h3><div class="wl-assets">${d.assets.map(assetCard).join('')}</div>`
    + card('收益目标 vs 达标概率', `<div class="wl-chart" id="tp-curve"></div><div class="wl-legend" id="tp-legend"></div>`, '点击曲线可把目标设为该值')
    + allocationCard(d) + ordersCard(d) + backtestCard(d.backtest, d)
    + `<p class="muted wl-note wl-foot">${esc(modelNote(d))}</p>`;
  curve(box.querySelector('#tp-curve'), box.querySelector('#tp-legend'), d, (t) => setTarget(box, ctx, Math.round(t * 100)));
  bindTarget(box, ctx);
}

function setTarget(box, ctx, raw) {
  const v = Number(raw);
  if (!Number.isFinite(v) || v < 0 || v > 50) { ctx.toast('请输入 0%–50% 之间的数字'); return; }
  tp.target = Math.round(v * 10) / 1000; store.set('target', tp.target);
  const input = box.querySelector('#tp-target'), range = box.querySelector('#tp-range');
  if (input && document.activeElement !== input) input.value = Math.round(v * 10) / 10;
  if (range) range.value = v;
  clearTimeout(tp.timer); tp.timer = setTimeout(() => loadTarget(box, ctx), 300);
}

function setDrawdown(box, ctx, raw) {
  const v = Number(raw);
  if (!Number.isFinite(v) || v < 1 || v > 40) { ctx.toast('请输入 1%–40% 之间的数字'); return; }
  tp.drawdown = Math.round(v) / 100; store.set('drawdown', tp.drawdown);
  clearTimeout(tp.timer); tp.timer = setTimeout(() => loadTarget(box, ctx), 300);
}

function bindTarget(box, ctx) {
  box.querySelector('#tp-drawdown')?.addEventListener('change', (e) => setDrawdown(box, ctx, e.target.value));
  box.querySelector('#tp-target').addEventListener('change', (e) => setTarget(box, ctx, e.target.value));
  box.querySelector('#tp-range').addEventListener('input', (e) => setTarget(box, ctx, e.target.value));
  box.querySelectorAll('[data-seg] button').forEach((b) => b.addEventListener('click', () => {
    const name = b.parentElement.dataset.seg, v = b.dataset.v;
    if (name === 'preset') return setTarget(box, ctx, v);
    if (name === 'dd') return setDrawdown(box, ctx, v);
    if (name === 'delay') { tp.delay = Number(v); store.set('delay', tp.delay); return loadTarget(box, ctx); }
    tp[name] = v; store.set(name, v); renderTarget(box, ctx);   // 方案和买法：返回值里两套都有，只重画
  }));
}

function assetCard(a) {
  const heads = (a.news?.headlines || []).slice(0, 3).map((x) => `<li><a href="${safeUrl(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a> <small class="muted">${esc(x.source || '')} · ${day(x.published_at)}</small></li>`).join('');
  const live = a.quote?.observed_at ? `${a.quote.source === 'live' ? '实时' : '收盘'} ${a.quote.observed_at.slice(5, 16).replace('T', ' ')}` : '历史收盘';
  const isFund = a.kind === 'fund', funds = Object.entries(a.funds || {});
  const tag = isFund ? `${funds.map(([c]) => c).join(' + ')} 等权 · ${a.currency}` : `${esc(a.symbol)} · ${a.currency}`;
  const line = isFund ? `场外基金，按净值申购 · 净值日 ${a.nav_date} · 数据自 ${a.history_start.slice(0, 4)}` : `${a.price ?? '—'} ${a.currency} · ${live} · 数据自 ${a.history_start.slice(0, 4)}`;
  const third = isFund ? ['历史最大回撤', ret(a.max_drawdown, 2), `年化波动 ${ret(a.volatility?.annual, 2).replace('+', '')}`]
    : ['亏超 10%', pr(a.loss10), `200 日线 ${ret(a.state.ma200_gap)}`];
  const fundTable = funds.length ? table(['基金', '累计净值', '近一年', '最大回撤'], funds.map(([c, f]) => `<tr><td>${esc(f.name)} <small class="muted">${esc(c)}</small></td><td>${f.nav.toFixed(4)}</td><td class="${tone(f.return_1y)}">${ret(f.return_1y, 2)}</td><td>${ret(f.max_drawdown, 2)}</td></tr>`).join('')) : '';
  return `<article class="card wl-asset">
    <header class="row between"><div><small class="muted"><i class="wl-sw ${SERIES[a.symbol] || ''}"></i>${tag}</small><h4>${esc(a.name)}</h4><div class="muted wl-small">${line}</div></div>
      <span class="wl-action ${a.action}">${actionTag(a.action)} ${esc(a.action_label)}</span></header>
    <div class="wl-mini">
      <div><span>达标概率</span><b>${pr(a.probability)}</b>${bar(a.probability, 1, '')}</div>
      <div><span>中位</span><b class="${tone(a.p50)}">${ret(a.p50)}</b><small>${ret(a.p10)} ~ ${ret(a.p90)}</small></div>
      <div><span>${third[0]}</span><b>${third[1]}</b><small>${third[2]}</small></div>
    </div>${fundTable}${timingPanel(a.val_timing)}
    <p class="wl-pacing"><b>节奏</b>${esc(a.pacing)}</p>
    <details open><summary>理由</summary>${list(a.reasons)}</details>
    ${heads ? `<details><summary>最近资讯（${a.news.count} 条，偏正面 ${a.news.positive} / 偏负面 ${a.news.negative}）</summary><ul class="wl-ul">${heads}</ul></details>` : ''}
  </article>`;
}

function timingPanel(t) {
  if (!t) return '';
  const rows = [['cheap', '便宜（< 30%）'], ['fair', '合理（30%–70%）'], ['dear', '偏贵（> 70%）']].map(([k, label]) => {
    const z = t.zones?.[k];
    const cells = z ? `<td>${z.n} 周</td><td class="${tone(z.median)}">${ret(z.median)}</td><td class="${tone(z.worst)}">${ret(z.worst)}</td><td>${pr(z.loss)}</td>` : '<td colspan="4">样本不足</td>';
    const band = t.levels?.bands?.[k];
    const level = band ? `<td><b>${esc(band.price)}</b>${band.metric ? `<br><small class="muted">${esc(band.metric)}</small>` : ''}</td>` : '<td>—</td>';
    return `<tr class="${k === t.zone ? 'sel' : ''}"><td>${label}</td>${level}${cells}</tr>`;
  }).join('');
  return `<div class="wl-timing">
    <div class="row between"><b>估值择时 · ${esc(t.index)}</b><span class="tag ${t.zone === 'cheap' ? 'ok' : t.zone === 'dear' ? 'warn' : 'gray'}">${esc(t.zone_label)} · 综合分位 ${Math.round(t.score * 100)}%</span></div>
    <div class="wl-mini">${t.cards.map((c) => `<div><span>${esc(c.label)}</span><b>${esc(c.value)}</b><small>${esc(c.note)}</small></div>`).join('')}</div>
    ${t.levels?.headline ? `<p class="wl-levels">${esc(t.levels.headline)}</p>` : ''}
    <div class="wl-scroll">${table([`${Number(t.since.slice(0, 4)) + 3} 年起每周估值`, t.levels?.header || '对应价格', '样本', '之后一年中位', '最差', '亏损占比'], rows)}</div>
    <p class="muted wl-small">估值日 ${esc(t.as_of)}${t.cgb_date ? `，国债日 ${esc(t.cgb_date)}` : ''}。分位只用当时之前的历史（自 ${esc(t.since.slice(0, 4))} 年），样本约 ${Math.round(Object.values(t.zones).reduce((sum, z) => sum + (z?.n || 0), 0) / 52)} 年。${esc(t.note || '')}${t.stale ? '<b class="wl-warn">数据源暂不可用，显示缓存</b>' : ''}</p>
  </div>`;
}

function curve(boxEl, legendEl, d, onPick) {
  const series = d.assets.map((a) => ({ key: a.symbol, label: a.name, curve: a.curve })).concat({ key: 'portfolio', label: `${MODES[tp.mode]}组合`, curve: tpPlan(d).curve });
  const targets = d.curve_targets, lo = targets[0], hi = targets.at(-1);
  const all = series.flatMap((s) => s.curve.map((r) => r.probability));
  const yLo = Math.max(0, Math.floor(Math.min(...all) * 10) / 10), yHi = Math.min(1, Math.ceil(Math.max(...all) * 10) / 10);
  const width = 900, height = 320, pad = { top: 16, right: 130, bottom: 36, left: 44 };
  const x = (v) => pad.left + (v - lo) / (hi - lo) * (width - pad.left - pad.right);
  const y = (v) => pad.top + (yHi - v) / (yHi - yLo || 1) * (height - pad.top - pad.bottom);
  const yt = []; for (let v = yLo; v <= yHi + 1e-9; v += 0.1) yt.push(v);
  const grid = yt.map((v) => `<line class="wl-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${y(v)}" y2="${y(v)}"/><text class="wl-lab" x="${pad.left - 6}" y="${y(v) + 3}" text-anchor="end">${Math.round(v * 100)}%</text>`).join('');
  const xt = targets.filter((t) => Math.round(t * 100) % 5 === 0).map((t) => `<text class="wl-lab" x="${x(t)}" y="${height - 16}" text-anchor="middle">${Math.round(t * 100)}%</text>`).join('')
    + `<text class="wl-lab" x="${(pad.left + width - pad.right) / 2}" y="${height - 2}" text-anchor="middle">一年收益目标</text>`;
  const ends = series.map((s) => ({ s, y: y(s.curve.at(-1).probability) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i += 1) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 12);
  const lines = series.map((s) => `<path class="wl-line ${SERIES[s.key]}" d="${s.curve.map((r, i) => `${i ? 'L' : 'M'}${x(r.target).toFixed(1)},${y(r.probability).toFixed(1)}`).join(' ')}"/>`).join('');
  const labels = ends.map(({ s, y: ly }) => `<text class="wl-lab wl-end" x="${x(hi) + 6}" y="${ly + 3}">${esc(s.label)} ${pr(s.curve.at(-1).probability)}</text>`).join('');
  const mark = d.target >= lo && d.target <= hi ? `<line class="wl-target-line" x1="${x(d.target)}" x2="${x(d.target)}" y1="${pad.top}" y2="${height - pad.bottom}"/><text class="wl-lab" x="${x(d.target) + 4}" y="${pad.top + 8}">当前目标 ${ret(d.target)}</text>` : '';
  boxEl.innerHTML = chartFrame(width, height, pad, grid + xt + mark + lines + labels, '一年收益目标与达标概率曲线');
  legendEl.innerHTML = series.map((s) => `<span><i class="wl-sw ${SERIES[s.key]}"></i>${esc(s.label)}</span>`).join('');
  hover(boxEl, {
    width, pad, xOf: x,
    nearest: (vx) => { const v = lo + (vx - pad.left) / (width - pad.left - pad.right) * (hi - lo); return targets.reduce((b, t) => (Math.abs(t - v) < Math.abs(b - v) ? t : b)); },
    tipHtml: (t) => `<b>目标 ${ret(t, 0)}</b><small>一年后达标的概率</small>${series.map((s) => ({ s, p: s.curve.find((r) => Math.abs(r.target - t) < 1e-9)?.probability })).sort((a, b) => b.p - a.p)
      .map(({ s, p }) => `<span class="${s.key === 'portfolio' ? 'cur' : ''}"><i class="wl-sw ${SERIES[s.key]}"></i>${esc(s.label)}<em>${pr(p)}</em></span>`).join('')}`,
    onClick: onPick,
  });
}

function allocationCard(d) {
  const al = d.allocation, plan = tpPlan(d), net = al.funding?.net, safe = tp.mode === 'safe';
  const by = Object.fromEntries(d.assets.map((a) => [a.symbol, a]));
  const local = Object.fromEntries((plan.orders || []).map((r) => [r.symbol, r]));
  const rows = Object.entries(plan.weights).map(([sym, w]) => {
    const a = by[sym], c = local[sym];
    return `<tr class="${w > 0 ? '' : 'dim'}"><td><i class="wl-sw ${SERIES[sym] || ''}"></i><b>${esc(a?.name || sym)}</b> <small class="muted">${esc(sym)}</small></td><td><b>${Math.round(w * 100)}%</b></td>
      <td>${net && w > 0 ? int(net * w) : '—'}</td><td>${c?.amount ? `${int(c.amount)} ${c.currency}` : '—'}</td><td>${pr(a?.probability)}</td><td><span class="wl-action ${a?.action}">${actionTag(a?.action)} ${esc(a?.action_label || '')}</span></td><td class="wl-wrap">${esc(a?.pacing || '')}</td></tr>`;
  }).join('');
  const cmp = [[safe ? '稳妥组合' : '进取组合', plan.stats, true]]
    .concat(safe ? [['进取组合（四只股票/ETF 都持有）', al.stats]] : d.safe ? [['稳妥组合', d.safe.stats]] : [])
    .concat(Object.entries(al.references).map(([k, r]) => [k === 'equal' ? `等权 ${Math.round(100 / d.assets.length)}% × ${d.assets.length}` : REFS[k] || k, r.stats]));
  const cmpTable = `<h4 class="wl-h4">和其他做法比</h4>` + table(['组合', '达标', '不亏', '80% 把握', '悲观 10%', '中位'], cmp.map(([n, s, cur]) => `<tr class="${cur ? 'sel' : ''}"><td>${n}</td><td><b>${pr(s.probability)}</b></td><td>${pr(s.nonneg)}</td><td class="${tone(s.p20)}">${ret(s.p20)}</td><td class="${tone(s.p10)}">${ret(s.p10)}</td><td class="${tone(s.p50)}">${ret(s.p50)}</td></tr>`).join(''));
  let side;
  if (safe) {
    const c = plan.constraints, key = (w) => Object.entries(w).map(([s, v]) => `${s}:${Math.round(v * 100)}`).join();
    side = `<h4 class="wl-h4">只买其中几只行不行：每种持有方式里最好的权重</h4>` + table(['持有', '达标', '不亏', '80% 把握', '悲观 10%', '回撤 压力 / 历史', '历史 不亏 / 达标', '稳妥约束'], plan.options.map((o) => {
      const fails = [o.nonneg < c.nonneg - 1e-9 ? '不亏' : '', o.p10 < c.p10_floor - 1e-9 ? '悲观' : '', o.stress_drawdown < -c.max_drawdown - 1e-9 ? '回撤' : ''].filter(Boolean);
      const qd = o.holdings.length === 2 && o.holdings.includes('QQQ') && o.holdings.includes('512890.SS');
      return `<tr class="${key(o.weights) === key(plan.weights) ? 'sel' : ''} ${o.ok ? '' : 'dim'}"><td class="wl-wrap">${tpWeights(d, o.weights)}${qd ? ' <span class="tag line">只买 QQQ + 红利低波</span>' : ''}</td><td><b>${pr(o.probability)}</b></td><td>${pr(o.nonneg)}</td><td class="${tone(o.p20)}">${ret(o.p20)}</td><td class="${tone(o.p10)}">${ret(o.p10)}</td>
        <td>${ret(o.stress_drawdown)} / ${o.history ? ret(o.history.max_drawdown) : '—'}</td><td>${o.history ? `${pr(o.history.nonneg_rate)} / ${pr(o.history.hit_rate)}` : '—'}</td><td class="${o.ok ? 'up' : 'down'}">${o.ok ? '✓ 满足' : `✕ ${fails.join('、')}`}</td></tr>`;
    }).join(''));
  } else {
    side = `<h4 class="wl-h4">概率最高的几种权重（未加悲观约束前）</h4>` + table(['权重', '达标', '悲观 10%', '中位'], al.frontier.slice(0, 5).map((r) => `<tr><td>${tpWeights(d, r.weights)}</td><td>${pr(r.probability)}</td><td class="${tone(r.p10)}">${ret(r.p10)}</td><td>${ret(r.p50)}</td></tr>`).join(''));
  }
  const corr = `红利低波与美股科技的相关性约 ${(al.correlations?.QQQ?.['512890.SS'] ?? 0).toFixed(2)}、纯债基金约 ${(al.correlations?.QQQ?.[BOND] ?? 0).toFixed(2)}，它们的权重主要来自分散，而不是更高的预期收益。金额按今天全部卖出美团的税后净额估算。`;
  const how = safe
    ? `选法：以 ${Math.round(plan.constraints.grid * 100)}% 为步长枚举所有持有方式（可以只买一两只，单只个股 ≤ ${Math.round(plan.constraints.max_single_stock * 100)}%），先要求一年不亏的概率 ≥ ${pr(plan.constraints.nonneg)}、悲观 10% 不低于 ${ret(plan.constraints.p10_floor, 0)}、压力回撤不超过 ${pr(plan.constraints.max_drawdown)}（各持仓 ${plan.constraints.stress_start.slice(0, 4)} 年以来最深回撤按权重相加，相当于假设它们同时跌到最深），再在满足的组合里取达标概率最高的；差距不到 ${Math.round(plan.constraints.tie * 100)} 个百分点时选更不容易亏的。「历史」是 ${plan.history?.start?.slice(0, 4) || ''} 年以来按同样权重买入持有 ${d.delay?.held_days || 252} 个交易日的实际结果，窗口互相重叠，只有约 ${plan.history?.n_eff?.toFixed(0) || '—'} 个独立年。${corr}`
    : `选法：以 10% 为步长枚举权重，单只个股 ≤ ${Math.round(al.constraints.max_single_stock * 100)}%、四只股票/ETF 每只 ≥ ${Math.round(al.constraints.min_weight * 100)}%（纯债基金可以不配）、悲观 10% 不低于 ${ret(al.constraints.p10_floor, 0)}；在达标概率与最高者相差不到 ${Math.round(al.constraints.tie * 100)} 个百分点的组合里，选悲观 10% 最好的一个。${corr}`;
  return card(`${MODES[tp.mode]}方案：美团卖出资金怎么分`,
    table(['标的', '权重', `金额（${al.funding?.currency || 'HKD'}）`, '折合当地币种', '单只达标', '信号', '建仓节奏'], rows)
    + `<div class="wl-two">${safe ? `<div class="wl-wide">${side}</div><div>${cmpTable}</div>` : `<div>${cmpTable}</div><div>${side}</div>`}</div>`
    + `<p class="muted wl-note">${esc(how)}</p>`);
}

function ordersCard(d) {
  const plan = tpPlan(d), funding = d.allocation.funding, model = d.ladder_model;
  const rows = plan.orders_by_shape?.[tp.shape] || plan.orders || [];
  const delay = d.delay || { months: 0 }, waiting = delay.months > 0;
  const arrive = after(d.generated_at, delay.months), expiry = after(d.generated_at, delay.months + 3), shapeLabel = model.labels[tp.shape];
  const fx = Object.entries(d.fx || {}).map(([c, f]) => `1 HKD = ${f.rate.toFixed(4)} ${c}`).join(' · ');
  const fxSrc = Object.values(d.fx || {}).every((f) => f.source === 'yahoo') ? 'Yahoo 实时' : '部分为默认汇率';
  const byCur = {};
  rows.forEach((r) => { if (r.hkd) { const c = byCur[r.currency] ||= { hkd: 0, amount: 0 }; c.hkd += r.hkd; c.amount += r.amount; } });
  const exchange = Object.entries(byCur).map(([c, x]) => `${int(x.hkd)} HKD → 约 ${int(x.amount)} ${c}`).join('；');
  const weightsOf = (r) => r.timing?.weights || model.shapes[tp.shape];
  const stockRows = rows.filter((r) => r.kind !== 'fund'), bondRow = rows.find((r) => r.kind === 'fund');
  const hasLimits = stockRows.some((r) => weightsOf(r).slice(1).some((w) => w > 0));
  const timed = rows.find((r) => r.timing);
  const steps = [
    funding ? `今天卖出美团剩余 ${int(funding.shares)} 股（按现价 ${funding.price} HKD），${waiting ? `约 ${delay.months} 个月后（<b>${arrive}</b> 前后）` : ''}到账约 <b>${int(funding.net)} HKD</b>。` : '没有读到美团持仓，下表金额无法计算。',
    waiting ? '等待期间不用做什么，也不必提前挂单：下表按今天价格估算，到账当天按当天价格把每一档重新算一遍（比例和 −3% / −6% / −10% 不变，数量随价格变）。' : '',
    exchange ? `${waiting ? '到账后' : ''}换汇：${exchange}${waiting ? '（按今天汇率估算）' : ''}。` : '',
    bondRow ? `纯债基金在场外申购（基金销售平台、银行或券商的基金账户）：${waiting ? '到账后' : ''}工作日 15:00 前提交按当天净值成交，T+1 确认；两只各申购一半，约 ${int(bondRow.funds[0]?.amount)} CNY。持有不满 7 天赎回有 1.5% 惩罚性费用。` : '',
    !stockRows.length ? '' : hasLimits ? `${waiting ? '到账当天' : '当天'}按现价买入表中「现价买入」行，同时挂好回调限价单，有效期约 3 个月（到 <b>${expiry}</b>，约 ${model.days} 个交易日）。` : `${waiting ? '到账当天' : '当天'}按现价一次买入表中全部数量。`,
    timed ? `${esc(tpName(d, timed.symbol))}按估值调整买法：当前${esc(timed.timing.zone_label)}，${esc(timed.timing.label.replace('按估值：', ''))}，其他标的仍按${esc(shapeLabel)}。` : '',
    stockRows.length && hasLimits ? '到期仍没成交的限价单撤掉，把剩下的钱按当时市价买入，不再等更低的价格。' : '',
    `买完后持有到 <b>${after(d.generated_at, 12)}</b>（从今天卖出算满一年），每月回来看一次信号；美团实际成交价和到账金额出来后，在这里重新算一次数量。`,
  ].filter(Boolean).map((x) => `<li>${x}</li>`).join('');
  const kind = (o) => (o.kind === 'market' ? '现价买入' : `限价 −${Math.round(o.depth * 100)}%`);
  const blocks = rows.length ? rows.map((r) => {
    if (r.kind === 'fund') {
      return `<div class="wl-order"><div class="row between"><div><i class="wl-sw ${SERIES[r.symbol] || ''}"></i><b>${esc(tpName(d, r.symbol))}</b> <small class="muted">场外基金 · 按当天净值申购</small></div><span class="num">${Math.round(r.weight * 100)}% · ${r.amount ? `${int(r.amount)} ${r.currency}` : '—'}</span></div>
        ${table(['申购', '代码', `金额（${r.currency}）`], r.funds.map((f) => `<tr><td>${esc(f.name)}</td><td>${esc(f.code)}</td><td><b>${int(f.amount)}</b></td></tr>`).join(''))}
        <p class="muted wl-small">按金额申购，不挂限价单；份额 = 金额 ÷ 当天净值，次日确认。申购费按平台折扣后约 0.02%–0.08%。</p></div>`;
    }
    const ld = d.ladders[r.symbol], orders = r.plan?.orders || [], lot = r.plan?.lot || 1, unit = r.symbol === '512890.SS' ? '份' : '股';
    const arrival = ld.arrival ? `<p class="muted wl-small">到账时（约 ${ld.arrival.days} 个交易日后）价格估计：中位 <b>${price(ld.arrival.p50, r.currency)}</b>，80% 落在 ${price(ld.arrival.p10, r.currency)}–${price(ld.arrival.p90, r.currency)}；比今天贵的概率 ${pr(ld.arrival.up)}。</p>` : '';
    const shapes = Object.entries(ld.shapes).map(([n, s]) => `<li class="${(r.timing ? n === 'timing' : n === tp.shape) ? 'cur' : ''}">${esc(model.labels[n] || ld.timing?.label || n)}：达标 ${pr(s.probability)}，平均 ${ret(s.mean)}，悲观 10% ${ret(s.p10)}${n === ld.model_pick ? '（模型最优）' : ''}</li>`).join('');
    return `<div class="wl-order"><div class="row between"><div><i class="wl-sw ${SERIES[r.symbol] || ''}"></i><b>${esc(tpName(d, r.symbol))}</b> <small class="muted">${esc(r.symbol)} · 现价 ${price(ld.price, r.currency)} ${r.currency}</small>${r.timing ? ` <span class="tag warn">按估值调整 · ${esc(r.timing.zone_label)}</span>` : ''}</div><span class="num">${Math.round(r.weight * 100)}% · ${r.amount ? `${int(r.amount)} ${r.currency}` : '—'}</span></div>${arrival}
      ${table(['下单', waiting ? '价格（按今天）' : '价格', '数量', '金额', '成交概率'], orders.filter((o) => o.units > 0).map((o) => `<tr><td>${kind(o)}</td><td><b>${price(o.price, r.currency)}</b></td><td>${o.units.toLocaleString('zh-CN')} ${unit}</td><td>${int(o.amount)}</td><td>${o.kind === 'market' ? '—' : pr(o.fill_probability)}</td></tr>`).join(''))}
      <p class="muted wl-small">合计 ${int(r.plan?.spent)} ${r.currency}，按整${lot > 1 ? `手（${lot} ${unit}一手）` : '股'}取整后剩 ${int(r.plan?.leftover)} ${r.currency} 现金。</p>
      <details><summary>${ld.timing ? '各种' : '三种'}买法的模型结果（${waiting ? `到账后持有 ${d.delay.held_days} 个交易日` : '一年后'}，含未成交按市价补买）</summary><ul class="wl-ul">${shapes}</ul></details></div>`;
  }).join('') : emptyText('这个方案没有需要买入的标的。');
  const v = d.backtest?.ladder_verdict, cny = byCur.CNY;
  const notes = [
    v ? `<b>历史怎么说</b> ${esc(v)}` : '',
    '成交概率是按各标的波动率和趋势估算的「3 个月内价格至少触及一次限价」的概率；限价已按最小报价单位向下取整。',
    cny ? `人民币部分（${[stockRows.some((r) => r.currency === 'CNY') ? '红利低波 512890 需要能买上交所 ETF 的账户' : '', bondRow ? '纯债基金需要内地基金账户' : ''].filter(Boolean).join('，')}）约 ${int(cny.hkd)} HKD，换成人民币后还有人民币兑港币的汇率波动，模型没算进去。` : '',
    DISCLAIMER,
  ].filter(Boolean).map((x) => `<p class="muted wl-small">${x}</p>`).join('');
  return card(`${MODES[tp.mode]}方案 · 具体怎么买（${esc(shapeLabel)}）`, `<ol class="wl-steps">${steps}</ol><div class="wl-orders">${blocks}</div>${notes}`, `${fx}（${fxSrc}）`);
}

function backtestCard(bt, d) {
  if (!bt) return card('回测', emptyText('回测尚未生成（每天自动运行一次）。'));
  const all = bt.all, eras = bt.eras || {};
  const top = kpis([
    ['平均预测 vs 实际', `${pr(all.predicted)} / ${pr(all.realized)}`, `${all.n} 个起点，约 ${all.n_eff.toFixed(0)} 个独立年；预测偏保守`],
    ['Brier（越低越好）', all.brier.toFixed(3), `只用历史平均命中率时为 ${all.brier_climatology.toFixed(3)}`],
    ['区分能力 AUC', all.auc == null ? '—' : all.auc.toFixed(2), '0.5 相当于随机，概率不能用来择时'],
    ['2010 年前 / 后实际命中', `${pr(eras.before_2010?.realized)} / ${pr(eras.since_2010?.realized)}`, '同一模型，不同年代差别很大'],
  ], 'compact');
  const names = { rule: '按信号调权', equal: '每月再平衡等权', hold: '买入后一直持有' };
  const ports = [['focus', '四只标的'], ['long', '长历史（纳指100、微软、谷歌）']].filter(([k]) => bt.portfolios?.[k]).map(([k, title]) => {
    const p = bt.portfolios[k];
    return `<div><h4 class="wl-h4">${title} · ${p.start.slice(0, 7)} 至 ${p.end.slice(0, 7)}</h4>${table(['做法', '年化', '最大回撤', '一年达标率'], Object.entries(names).map(([key, label]) => { const s = p.strategies[key]; return `<tr><td>${label}</td><td class="${tone(s.cagr)}">${ret(s.cagr)}</td><td class="down">${ret(s.max_drawdown)}</td><td>${pr(s.hit_rate)}</td></tr>`; }).join(''))}</div>`;
  }).join('');
  const ladders = Object.entries(bt.ladders || {}).map(([sym, r]) => {
    const s = r.shapes;
    return `<tr><td>${esc(LADDER_NAMES[sym] || tpName(d, sym))} <small class="muted">${r.n} 个起点</small></td><td class="${tone(s.lump.mean)}">${ret(s.lump.mean)}</td><td class="${tone(s.balanced.mean)}">${ret(s.balanced.mean)}</td><td>${pr(s.balanced.beats_lump)}</td><td class="${tone(s.lump.p10)}">${ret(s.lump.p10)}</td><td class="${tone(s.balanced.p10)}">${ret(s.balanced.p10)}</td><td>${r.fill_rates.slice(1).map(pr).join(' / ')}</td></tr>`;
  }).join('');
  const lt = ladders ? `<div class="wl-wide"><h4 class="wl-h4">买入方式回测：一次买入 vs 现价 40% + 回调挂单（3 个月未成交按市价补）</h4>${table(['标的', '一次买入 平均一年', '分批 平均一年', '分批胜出的起点', '一次买入 悲观 10%', '分批 悲观 10%', '−3/−6/−10% 成交率'], ladders)}</div>` : '';
  return `<details class="card wl-card wl-fold"><summary class="row between"><span class="card-label">回测：模型准不准、信号有没有用</span><span class="muted wl-extra">按 ${ret(bt.target, 0)} 目标 · 生成于 ${day(bt.generated_at)}${bt.stale ? '（已超过一周）' : ''}</span></summary>
    ${top}<div class="wl-two">${ports}${lt}</div>
    <p class="wl-verdict"><b>结论</b> ${esc(bt.verdict || '')}</p>${bt.ladder_verdict ? `<p class="wl-verdict"><b>买入方式</b> ${esc(bt.ladder_verdict)}</p>` : ''}</details>`;
}

function modelNote(d) {
  const m = d.model;
  return '收益按各自币种计算：QQQ、谷歌、微软为美元，红利低波和纯债基金为人民币；港币与美元挂钩，美元资产基本没有汇率风险，人民币资产另有 CNH 汇率波动，模型未计入。'
    + `模型：长期年化对数收益向 ${ret(m.prior, 0)} 收缩（ETF/指数先验权重 ${m.shrink_years} 年，个股 ${m.shrink_years_stock} 年以抵消“幸存者”偏差），波动率加趋势不确定性 κ=${m.kappa}。`
    + `稳妥方案：可以只持有其中一两只，要求一年不亏的概率 ≥ ${pr(d.safe?.constraints.nonneg)}、悲观 10% 不低于 ${ret(d.safe?.constraints.p10_floor, 0)}、压力回撤不超过 ${pr(d.safe?.constraints.max_drawdown)}，再在满足的组合里求达标概率最高；进取方案四只股票/ETF 都持有（纯债可选），直接求达标概率最高。纯债基金不向股票先验收缩，用近一年收益作中枢。`
    + `信号规则：低于 200 日均线或达标概率 < ${pr(m.reduce_probability)} → 减仓或暂缓；≥ ${pr(m.add_probability)} → 加仓；其余持有。${DISCLAIMER}`;
}

// ================================================================ 减持
async function loadSell(box, ctx, { quiet = false } = {}) {
  const seq = ++sp.seq;
  const q = new URLSearchParams();
  if (sp.target != null) q.set('target_avg', sp.target);
  if (sp.horizon != null) q.set('horizon_days', sp.horizon);
  if (sp.shape) q.set('shape', sp.shape);
  if (sp.now != null) q.set('now_shares', sp.now);
  if (sp.compare != null) q.set('compare_days', sp.compare);
  if (sp.qqq != null) q.set('qqq_return', sp.qqq / 100);
  if (sp.stock != null) q.set('stock_return', sp.stock / 100);
  if (!quiet) box.classList.add('wl-loading');
  try {
    const d = await ctx.api.get(`/api/wealth/sell-plan?${q}`);
    if (seq !== sp.seq) return;
    sp.data = d;
    Object.assign(sp, { target: d.plan.target_avg, horizon: d.position.horizon_days, compare: d.position.compare_days, shape: d.plan.shape });
    renderSell(box, ctx);
  } catch (e) {
    if (seq === sp.seq) { if (sp.data) ctx.toast('减持测算失败：' + e.message); else box.innerHTML = card('无法计算', emptyText(e.message)); }
  } finally { if (seq === sp.seq) box.classList.remove('wl-loading'); }
}

function saveSell(ctx, changes) {
  clearTimeout(sp.saveTimer);
  sp.pending = { ...(sp.pending || {}), ...changes };
  sp.saveTimer = setTimeout(async () => {
    const body = { symbol: sp.data?.symbol, ...sp.pending }; sp.pending = null;
    try { await ctx.api.post('/api/wealth/positions', body); } catch (e) { ctx.toast('保存设置失败：' + e.message); }
  }, 800);
}

function renderSell(box, ctx) {
  const d = sp.data, plan = d.plan, quote = d.quote, sm = d.summary;
  const hl = d.position.unlimited ? `${horizonName(plan.horizon_days)}（不设期限）` : horizonName(plan.horizon_days);
  const refresh = d.refresh || {};
  const status = refresh.last_status === 'failed' ? `上次刷新失败：${refresh.last_error}` : refresh.last_status === 'partial' ? '上次刷新部分成功' : '';
  const chips = [['1小时', sm.change_1h_pct], ['今日', sm.change_1d_pct], ['5日', sm.change_5d_pct], ['20日', sm.change_20d_pct], ['60日', sm.change_60d_pct], ['1年', sm.change_1y_pct]];
  const range = sm.range_position == null ? '' : `<div class="wl-chip wl-range"><span>52周 ${money(sm.low_52w)} – ${money(sm.high_52w)}</span><div><i style="left:${(sm.range_position * 100).toFixed(1)}%"></i></div></div>`;
  const low = Math.floor(quote.price * 0.9), high = Math.ceil(Math.max(quote.price * 1.6, sm.high_52w || 0, plan.target_avg * 1.05));
  const premium = (plan.target_avg / quote.price - 1) * 100;
  const head = `<section class="card wl-controls">
    <div class="row between wl-wrapline"><div><div class="card-label">${esc(d.market || '')} · ${esc(d.currency)}</div><h3 class="wl-title">${esc(d.symbol)} · ${esc(d.name)} · 持有 ${int(d.position.shares)} 股</h3>
      <div class="muted wl-small">价格 ${local(quote.observed_at)}（${quote.source === 'live' ? '实时' : quote.source === 'hourly' ? '小时线' : '收盘'}） · 行情资讯每 ${d.refresh_minutes} 分钟刷新，上次 ${local(refresh.last_completed_at)} ${esc(status)}</div></div></div>
    <div class="wl-chips"><div class="wl-chip wl-price"><span>现价 ${esc(d.currency)}</span><b>${money(quote.price)}</b><em class="${tone(sm.change_1d_pct)}">${pctv(sm.change_1d_pct)}</em></div>
      ${chips.map(([k, v]) => `<div class="wl-chip"><span>${k}</span><b class="${tone(v)}">${pctv(v)}</b></div>`).join('')}
      <div class="wl-chip"><span>年化波动率</span><b>${(d.volatility.annual * 100).toFixed(1)}%</b></div>${range}</div>
    <div class="wl-ctl"><label class="card-label">目标整体均价（${esc(d.currency)}）</label>
      <div class="row wl-target"><input type="number" id="sp-target" step="0.5" value="${plan.target_avg.toFixed(2)}"><input type="range" id="sp-range" min="${low}" max="${high}" step="0.5" value="${plan.target_avg}">
      <span class="muted">比现价 <b class="${tone(premium)}">${pctv(premium)}</b>${d.execution.sold_shares ? ` · 已卖 ${int(d.execution.sold_shares)} 股后，剩余 ${int(plan.remaining_shares)} 股需卖出均价 <b>${money(plan.required_avg_remaining)}</b>` : ''}</span></div></div>
    <div class="wl-ctl-row">
      <div class="wl-ctl"><label class="card-label">期限</label>${seg('horizon', Object.entries(HORIZONS), d.position.horizon_days)}<p class="muted wl-small">${d.position.unlimited ? `不设期限：限价单一直挂着（GTC）；概率按换仓比较期（${horizonName(plan.horizon_days)}）计算` : '期限决定概率口径；到期未成交部分按到期价卖出计入'}</p></div>
      <div class="wl-ctl"><label class="card-label">挂单形态</label>${seg('spshape', Object.entries(SHAPES), plan.shape)}<p class="muted wl-small">${SHAPE_NOTES[plan.shape] || ''}</p></div>
    </div></section>`;
  const top = kpis([
    ['达标概率', pr(plan.probability_target), `${hl}后整体均价 ≥ ${money(plan.target_avg)}`, true],
    ['现在按市价卖', `${int(plan.now_shares)} 股`, plan.overridden ? `你选定的 · 推荐 ${int(plan.recommended_now_shares)} 股` : '达标概率最高的一档'],
    ['全部成交均价', money(plan.all_filled_avg), `扣费后 ${money(plan.all_filled_net_avg)} · 最高挂单${hl}内被触及 ${pr(plan.all_filled_probability)}`],
    ['中位均价', money(plan.p50_avg), `悲观 10% ${money(plan.p10_avg)} · 期望 ${money(plan.expected_avg)}（扣费 ${money(plan.expected_net_avg)}）`],
    ['期末未成交（期望）', `${int(Math.round(plan.expected_unfilled_shares / 100) * 100)} 股`, `未成交部分按${hl}后的价格计入`],
    ['现在全部卖出', money(plan.sell_all_now_avg), `扣费后 ${money(plan.sell_all_now_net_avg)} · ${pctv((plan.sell_all_now_avg / plan.target_avg - 1) * 100)} vs 目标`],
  ]);
  box.innerHTML = head + top + ladderCard(plan, d, hl) + (d.timing ? `<section class="card">${timingPanel(d.timing)}</section>` : '') + reasonsCard(plan) + ceilingCard(d, hl) + switchCard(d) + sweepCard(plan)
    + costsCard(plan, d) + shapesCard(plan) + sellBacktestCard(d) + executionCard(d) + hourlyCard(d) + newsCard(d)
    + `<p class="muted wl-note wl-foot">${DISCLAIMER}</p>`;
  drawCeiling(box, d);
  drawSwitch(box, d);
  bindSell(box, ctx);
}

function ladderCard(plan, d, hl) {
  const rows = plan.ladder.filter((r) => r.shares > 0);
  if (!rows.length) return card('挂单阶梯', emptyText('没有需要挂单的股数'));
  const max = Math.max(...rows.map((r) => r.shares));
  const timing = (t) => (!t || t.median_days == null ? '—' : `${esc(t.median_date || '')} <small class="muted">第 ${t.median_days} 日（${t.q25_days}–${t.q75_days}）</small>`);
  return card('挂单阶梯', table(['挂单', '价格', '股数', '', '较现价', `${hl}内成交`, '若成交，中位时间', '费用', '扣费净价'], rows.map((r) => `
    <tr class="${r.kind === 'market' ? 'sel' : ''}"><td>${r.kind === 'market' ? '<b>现在市价</b>' : '限价卖出'}</td><td><b>${money(r.price)}</b></td><td>${int(r.shares)}</td>
      <td class="wl-barcell"><i style="width:${(r.shares / max * 100).toFixed(1)}%"></i></td><td class="${tone(r.gain_pct)}">${r.kind === 'market' ? '—' : pctv(r.gain_pct)}</td>
      <td>${r.kind === 'market' ? '确定' : bar(r.touch_probability)}</td><td>${r.kind === 'market' ? '现在' : timing(r.timing)}</td><td>${r.cost ? money(r.cost.total, 0) : '—'}</td><td>${money(r.net_price)}</td></tr>`).join(''))
    + `<p class="muted wl-note">每档按 ${d.position.lot_size || 100} 股一手取整，不足一手的零股并入第一档。挂单全部成交的均价 ${money(plan.ladder_avg)}，不低于剩余部分所需的 ${money(plan.required_avg_remaining)}。触及即视为成交（未计盘口深度）；“中位时间”只在该档最终成交的情形里统计。</p>`);
}

function reasonsCard(plan) {
  const r = plan.reasons;
  if (!r) return '';
  const rungs = (r.rungs || []).map((x) => `<div class="wl-rung"><div class="row between"><b>限价 ${money(x.price)}</b><span class="muted">${int(x.shares)} 股</span></div>
    <dl><dt>为什么是这个价</dt><dd>${esc(x.price_reason)}</dd><dt>为什么是这么多股</dt><dd>${esc(x.shares_reason)}</dd><dt>什么时候成交</dt><dd>${esc(x.timing_reason)}</dd></dl></div>`).join('');
  return card('为什么这么挂', `<div class="wl-two"><div><h4 class="wl-h4">1 · 前提与取舍</h4>${list(r.overview)}</div><div><h4 class="wl-h4">2 · 现在按市价卖 ${int(plan.now_shares)} 股的理由</h4>${list(r.now)}</div></div>
    <h4 class="wl-h4">3 · 每一档挂单的依据</h4><div class="wl-rungs">${rungs || emptyText('没有限价挂单')}</div>
    <h4 class="wl-h4">4 · 未成交怎么办、什么时候重新规划</h4>${list(r.contingency)}`);
}

function ceilingCard(d, hl) {
  const c = d.ceiling, plan = d.plan;
  if (!c || !c.curve.length) return card('达标上限', emptyText('没有可用的波动率'));
  const conc = (plan.shape_comparison || []).find((r) => r.shape === 'concentrated'), cur = (plan.shape_comparison || []).find((r) => r.shape === plan.shape);
  const gap = (c.probability - plan.probability_target) * 100;
  const tradeoff = plan.shape === 'concentrated' ? '当前就是集中挂单，已贴近上限' : `比上限低 ${gap.toFixed(1)} 个百分点，换来悲观 10% 净均价 ${money(cur?.p10_net_avg)}（集中挂单为 ${money(conc?.p10_net_avg)}）`;
  const side = kpis([
    ['达标上限', pr(c.probability), `${hl}内价格至少一次触及 ${money(c.required_level)}；任何挂法都不会超过它`, true],
    ['当前方案', pr(plan.probability_target), tradeoff],
    ['拉长期限', pr(c.unlimited), `不限时间的理论极限 · ${c.by_horizon.map((r) => `${horizonName(r.days)} ${pr(r.probability)}`).join(' · ')}`],
    ['扣费后达标', pr(c.net_probability), `毛均价需 ≥ ${money(plan.net_target?.gross_avg_needed)} 才能净均价 ≥ ${money(plan.target_avg)}`],
  ], 'compact') + table([`想要的把握（${hl}）`, '目标均价最多', '较现价'], c.targets.map((r) => `<tr data-target="${r.target_avg.toFixed(2)}" class="click ${Math.abs(r.target_avg - plan.target_avg) < 0.05 ? 'sel' : ''}"><td>${pr(r.probability)}</td><td><b>${money(r.target_avg)}</b></td><td class="${tone(r.target_avg - d.quote.price)}">${pctv((r.target_avg / d.quote.price - 1) * 100)}</td></tr>`).join(''));
  return card('目标均价定多高：达标上限', `<div class="wl-split"><div><div class="wl-chart" id="sp-ceiling"></div><div class="wl-legend">${c.horizons.map((x, i) => `<span><i class="wl-sw h${i}"></i>${horizonName(x)}</span>`).join('')}<span><i class="wl-sw tgt"></i>目标均价</span></div></div><div>${side}</div></div>
    <p class="muted wl-note">上限的依据：每笔成交价都不会高于期间最高价，所以价格没碰到剩余股数所需均价时，任何挂法都达不到目标；把全部股数挂在该价位正好取到这个概率。点击曲线或表格中的一行可把目标设为该值。</p>`);
}

function drawCeiling(box, d) {
  const el = box.querySelector('#sp-ceiling'), c = d.ceiling, plan = d.plan;
  if (!el) return;
  const width = 640, height = 300, pad = { top: 14, right: 16, bottom: 30, left: 40 };
  const cv = c.curve, lo = cv[0].target_avg, hi = cv.at(-1).target_avg;
  const x = (v) => pad.left + (v - lo) / (hi - lo) * (width - pad.left - pad.right);
  const y = (v) => pad.top + (1 - v) * (height - pad.top - pad.bottom);
  const active = String(plan.horizon_days);
  const lines = c.horizons.map((dd, i) => `<path class="wl-line h${i}${String(dd) === active ? ' cur' : ''}" d="${cv.map((r, j) => `${j ? 'L' : 'M'}${x(r.target_avg).toFixed(1)},${y(r.probability[dd]).toFixed(1)}`).join(' ')}"/>`).join('');
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line class="wl-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${y(v)}" y2="${y(v)}"/><text class="wl-lab" x="${pad.left - 6}" y="${y(v) + 3}" text-anchor="end">${v * 100}%</text>`).join('');
  const step = (hi - lo) / 5;
  const xt = Array.from({ length: 6 }, (_, i) => lo + step * i).map((v) => `<text class="wl-lab" x="${x(v)}" y="${height - 10}" text-anchor="middle">${money(v, 0)}</text>`).join('');
  const tx = Math.min(Math.max(x(plan.target_avg), pad.left), width - pad.right);
  const mark = plan.target_avg <= hi ? `<line class="wl-target-line" x1="${tx}" x2="${tx}" y1="${pad.top}" y2="${height - pad.bottom}"/>
    <circle class="wl-dot-ceil" cx="${tx}" cy="${y(c.probability)}" r="5"/><circle class="wl-dot-plan" cx="${tx}" cy="${y(plan.probability_target)}" r="5"/>
    <text class="wl-lab" x="${tx + 8}" y="${y(c.probability) - 6}">上限 ${pr(c.probability)}</text><text class="wl-lab" x="${tx - 8}" y="${y(plan.probability_target) + 4}" text-anchor="end">当前方案 ${pr(plan.probability_target)}</text>` : '';
  el.innerHTML = chartFrame(width, height, pad, grid + xt + lines + mark, '目标均价与达标上限曲线');
  hover(el, {
    width, pad, xOf: (r) => x(r.target_avg),
    nearest: (vx) => { const v = lo + (vx - pad.left) / (width - pad.left - pad.right) * (hi - lo); return cv.reduce((b, r) => (Math.abs(r.target_avg - v) < Math.abs(b.target_avg - v) ? r : b)); },
    tipHtml: (r) => `<b>目标均价 ${money(r.target_avg)}</b><small>较现价 ${pctv((r.target_avg / d.quote.price - 1) * 100)}</small>${c.horizons.map((dd, i) => `<span class="${String(dd) === active ? 'cur' : ''}"><i class="wl-sw h${i}"></i>${horizonName(dd)}<em>${pr(r.probability[dd])}</em></span>`).join('')}`,
    onClick: (r) => box.dispatchEvent(new CustomEvent('wl-target', { detail: Math.round(r.target_avg * 20) / 20 })),
  });
}

function switchCard(d) {
  const sw = d.switch;
  if (!sw) return card('换成 QQQ 值不值', emptyText('没有剩余持仓，无需比较'));
  const a = sw.assumptions, by = Object.fromEntries(sw.strategies.map((r) => [r.key, r]));
  const best = sw.optimal[SW_METRIC[sp.metric][1]], opt = (k) => `${Math.round(sw.optimal[k].fraction * 100)}%`;
  const hold = by.hold, now = by.switch_now, rate = (v, dg = 1) => ret(v, dg);
  const top = kpis([
    ['现在全卖的税后到手', money(sw.base_value, 0), `${int(sw.remaining_shares)} 股，扣卖出费用和超 ${money(sw.tax.threshold, 0)} 部分 ${Math.round(sw.tax.rate * 100)}% 的税；下表都以它为 1.00×`],
    [`最优换仓比例（${SW_METRIC[sp.metric][0]}）`, `${Math.round(best.fraction * 100)}%`, `${SW_REST[best.rest]} · 中位数最优 ${opt('median')} · 平均最优 ${opt('mean')} · 悲观10%最优 ${opt('p10')}`, true],
    [`${sw.years} 年后：持有 vs 全换`, `${times(hold.median_ratio)} / ${times(now.median_ratio)}`, `中位数；全换在 ${pr(now.beats_hold)} 的路径上胜过持有，悲观10% ${times(hold.p10_ratio)} vs ${times(now.p10_ratio)}`],
    ['美团要涨多少才值得留着', rate(sw.break_even?.mean), `年化，按平均值打平；按中位数要 ${rate(sw.break_even?.median)}。上市以来年化 ${rate(a.stock_cagr_since_listing)}`],
  ]);
  const topR = Math.max(...sw.strategies.map((r) => r.median_ratio));
  const tbl = table(['做法', '中位数', '平均', '悲观10%', '乐观10%', '年化（中位）', '胜过持有', '整体均价达标'], sw.strategies.map((r) => `<tr class="${r.key === 'plan' ? 'sel' : ''}"><td><b>${esc(r.label)}</b></td>
    <td>${bar(r.median_ratio, topR, times(r.median_ratio))}</td><td>${times(r.mean_ratio)}</td><td>${times(r.p10_ratio)}</td><td>${times(r.p90 / sw.base_value)}</td><td class="${tone(r.median_cagr)}">${rate(r.median_cagr)}</td><td>${r.key === 'hold' ? '—' : pr(r.beats_hold)}</td><td>${pr(r.target_probability)}</td></tr>`).join(''));
  const sens = table(['QQQ 年化', '持有', '全换', '当前方案', '最优比例', '美团打平需要'], sw.sensitivity.map((r) => `<tr class="${r.current ? 'sel' : ''}"><td><b>${rate(r.qqq_return, 0)}</b>${r.current ? ' <span class="tag line">当前</span>' : ''}</td>
    <td>${times(r.median_ratio.hold)}</td><td>${times(r.median_ratio.switch_now)}</td><td>${times(r.median_ratio.plan)}</td><td>${Math.round(r.best_fraction_median * 100)}%</td><td>${rate(r.break_even)}</td></tr>`).join(''));
  const bt = sw.backtest, btNames = { holdout: '美团自身（样本外）', basket: '港股一篮子（腾讯、阿里、小米、京东、中芯）' };
  const btHtml = bt ? Object.entries(bt.groups || {}).map(([n, g]) => `<h4 class="wl-h4">${esc(btNames[n] || n)}</h4>` + table(['期限', '独立样本', '股票 / QQQ 年化', '持有', '全换', '当前方案', '全换胜过持有 模型 / 实际'], g.rows.map((r) => `<tr><td>${r.days / 252} 年</td><td>${r.n_eff.toFixed(1)}</td>
      <td><span class="${tone(r.stock_cagr_median)}">${rate(r.stock_cagr_median, 0)}</span> / <span class="${tone(r.qqq_cagr_median)}">${rate(r.qqq_cagr_median, 0)}</span></td><td>${times(r.realized_median.hold)}</td><td>${times(r.realized_median.switch_now)}</td><td>${times(r.realized_median.plan)}</td><td>${pr(r.switch_beats_hold.predicted)} / <b>${pr(r.switch_beats_hold.realized)}</b></td></tr>`).join(''))).join('')
    + `<p class="muted wl-small">生成于 ${local(bt.generated_at)}${bt.stale ? '（已超过一周，等待重跑）' : ''}。每 ${bt.step} 个交易日一个起点，用真实走势回放；窗口互相重叠，独立样本很少，只能看方向，不能当作概率。</p>` : emptyText('还没有回放结果（每周自动重跑）');
  const controls = `<div class="wl-ctl-row">
    <div class="wl-ctl"><label class="card-label">比较期</label>${seg('compare', [[252, '1年'], [756, '3年'], [1260, '5年']], sw.days)}</div>
    <div class="wl-ctl"><label class="card-label">看哪个数</label>${seg('metric', Object.entries(SW_METRIC).map(([k, v]) => [k, v[0]]), sp.metric)}</div>
    <div class="wl-ctl"><label class="card-label">年化假设（%）</label><div class="row wl-inline"><label>QQQ <input type="number" id="sw-qqq" step="0.5" value="${Math.round(a.qqq_return * 1000) / 10}"></label><label>美团 <input type="number" id="sw-stock" step="0.5" value="${Math.round(a.stock_return * 1000) / 10}"></label></div></div></div>`;
  const note = `模型：美团与 QQQ 联合模拟 ${int(sw.samples)} 条路径（每 ${sw.step_days} 个交易日一步），美团年化 ${rate(a.stock_return)}、波动按近期估计并含趋势不确定性；QQQ 年化 ${rate(a.qqq_return)}、波动 ${rate(a.qqq_sigma)}、与美团相关 ${a.correlation.toFixed(2)}（近 5 年周线）。`
    + `税：每笔卖出价超过 ${money(sw.tax.threshold, 0)} 的部分按 ${Math.round(sw.tax.rate * 100)}% 计税；QQQ 期末按净收益 ${Math.round(sw.tax.switch_rate * 100)}% 计税；换仓买卖各计 ${(sw.switch_cost_rate * 100).toFixed(2)}% 成本。未计汇率、股息与 QQQ 管理费。QQQ 历史年化：近 5 年 ${rate(a.qqq_cagr?.['5'])}、10 年 ${rate(a.qqq_cagr?.['10'])}、15 年 ${rate(a.qqq_cagr?.['15'])}。${DISCLAIMER}`;
  return card(`换成 QQQ 值不值（${sw.years} 年后税后财富）`, controls + top
    + `<div class="wl-split"><div><div class="wl-chart" id="sw-chart"></div><div class="wl-legend"><span><i class="wl-sw s0"></i>${SW_REST.hold}</span><span><i class="wl-sw s1"></i>${SW_REST.ladder}</span></div></div><div><h4 class="wl-h4">理由</h4>${list(sw.reasons)}</div></div>`
    + tbl + `<details><summary>QQQ 收益假设敏感性</summary>${sens}</details><details><summary>历史回放：当年这样做，结果如何</summary>${btHtml}</details><p class="muted wl-note">${esc(note)}</p>`);
}

function drawSwitch(box, d) {
  const el = box.querySelector('#sw-chart'), sw = d.switch;
  if (!el || !sw) return;
  const metric = sp.metric, rows = sw.sweep, rests = ['hold', 'ladder'], cls = { hold: 's0', ladder: 's1' };
  const width = 440, height = 250, pad = { top: 22, right: 14, bottom: 34, left: 44 };
  const vals = rows.map((r) => r[metric]).concat(1);
  const lo = Math.floor(Math.min(...vals) * 20) / 20, hi = Math.ceil(Math.max(...vals) * 20) / 20 || 1;
  const x = (f) => pad.left + f * (width - pad.left - pad.right);
  const y = (v) => pad.top + (hi - v) / (hi - lo || 1) * (height - pad.top - pad.bottom);
  const grid = Array.from({ length: 5 }, (_, i) => lo + (hi - lo) * i / 4).map((v) => `<line class="wl-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${y(v)}" y2="${y(v)}"/><text class="wl-lab" x="${pad.left - 6}" y="${y(v) + 3}" text-anchor="end">${v.toFixed(2)}×</text>`).join('');
  const xt = [0, 0.25, 0.5, 0.75, 1].map((f) => `<text class="wl-lab" x="${x(f)}" y="${height - 14}" text-anchor="middle">${f * 100}%</text>`).join('')
    + `<text class="wl-lab" x="${(pad.left + width - pad.right) / 2}" y="${height}" text-anchor="middle">现在卖出并换 QQQ 的比例</text>`;
  const base = `<line class="wl-target-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y(1)}" y2="${y(1)}"/><text class="wl-lab" x="${width - pad.right}" y="${y(1) - 5}" text-anchor="end">今天全卖到手 1.00×</text>`;
  const lines = rests.map((rest) => { const s = rows.filter((r) => r.rest === rest); return `<path class="wl-line ${cls[rest]}" d="${s.map((r, i) => `${i ? 'L' : 'M'}${x(r.fraction).toFixed(1)},${y(r[metric]).toFixed(1)}`).join(' ')}"/>` + s.map((r) => `<circle class="wl-pt ${cls[rest]}" cx="${x(r.fraction)}" cy="${y(r[metric])}" r="3"/>`).join(''); }).join('');
  const best = sw.optimal[SW_METRIC[metric][1]];
  const mark = `<circle class="wl-best" cx="${x(best.fraction)}" cy="${y(best.value)}" r="7"/><text class="wl-lab" x="${x(best.fraction) - 10}" y="${y(best.value) - 10}" text-anchor="end">最优 ${Math.round(best.fraction * 100)}% · ${times(best.value)}</text>`;
  el.innerHTML = chartFrame(width, height, pad, grid + xt + base + lines + mark, '换仓比例与期末税后财富');
  hover(el, {
    width, pad, xOf: x,
    nearest: (vx) => Math.round(Math.min(1, Math.max(0, (vx - pad.left) / (width - pad.left - pad.right))) * 10) / 10,
    tipHtml: (f) => { const at = rows.filter((r) => Math.abs(r.fraction - f) < 1e-6); return `<b>现在换 ${Math.round(f * 100)}%（${int(at[0]?.now_shares)} 股）</b><small>${SW_METRIC[metric][0]} · 胜过全持有的路径占比</small>${at.map((r) => `<span><i class="wl-sw ${cls[r.rest]}"></i>${SW_REST[r.rest]}<em>${times(r[metric])} · ${pr(r.beats_hold)}</em></span>`).join('')}`; },
  });
}

function sweepCard(plan) {
  const best = Math.max(...plan.sweep.map((r) => r.probability_target));
  return card('现在卖多少：逐档比较', table(['现在卖', '剩余需均价', '达标概率', '悲观10%', '期望均价', '期望费用'], plan.sweep.map((r) => `
    <tr data-now="${r.now_shares}" class="click ${r.now_shares === plan.now_shares ? 'sel' : ''}"><td><b>${int(r.now_shares)}</b>${r.now_shares === plan.recommended_now_shares ? ' <span class="tag ok">推荐</span>' : ''}</td>
      <td>${r.required_avg_rest == null ? '—' : money(r.required_avg_rest)}</td><td>${bar(r.probability_target, best)}</td><td>${money(r.p10_avg)}</td><td>${money(r.expected_avg)}</td><td>${money(r.expected_costs, 0)}</td></tr>`).join('')),
  plan.overridden ? '<button class="ghost sm" data-act="reset-now">恢复推荐</button>' : '点一行改用该股数');
}

function costsCard(plan, d) {
  const labels = d.costs?.labels || {}, totals = {};
  let gross = 0;
  plan.ladder.filter((r) => r.shares > 0 && r.cost).forEach((r) => { gross += r.price * r.shares; Object.entries(r.cost).forEach(([k, v]) => { if (k !== 'total') totals[k] = (totals[k] || 0) + v; }); });
  if (!gross) return '';
  const bps = (v, b) => (b ? `${(v / b * 10000).toFixed(1)} bp` : '—');
  const nowGross = plan.sell_all_now_avg * plan.remaining_shares, net = plan.net_target;
  const rows = Object.entries(totals).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(labels[k] || k)}</td><td>${money(v)}</td><td>${bps(v, gross)}</td></tr>`).join('')
    + `<tr class="sel"><td>合计（${plan.ladder.filter((r) => r.shares > 0).length} 笔）</td><td>${money(plan.all_filled_costs)}</td><td>${bps(plan.all_filled_costs, gross)}</td></tr>
       <tr><td>按概率加权的期望费用</td><td>${money(plan.expected_costs)}</td><td>—</td></tr><tr><td>对照：现在一次全卖</td><td>${money(plan.sell_all_now_costs)}</td><td>${bps(plan.sell_all_now_costs, nowGross)}</td></tr>`;
  return `<details class="card wl-card wl-fold"><summary class="row between"><span class="card-label">税费</span><span class="muted wl-extra">全部成交 ${money(plan.all_filled_costs, 0)}</span></summary>${table(['项目', '全部按方案成交', '占成交额'], rows)}
    <p class="muted wl-note">${net ? `目标均价按税费前计。若要求扣费后整体均价也 ≥ ${money(plan.target_avg)}，税费前需要 ${money(net.gross_avg_needed)}，对应达标概率 ${pr(net.probability_target)}（推荐现价卖 ${int(net.recommended_now_shares)} 股）。` : ''}费率按香港券商常见收费（佣金 0.03%、平台费每笔 15、印花税 0.1% 进位到元、交易费、证监会与会财局征费、交收费）；限价单分多天成交时平台费会重复收取。</p></details>`;
}

function shapesCard(plan) {
  const shapes = plan.shape_comparison || [], drift = plan.drift_sensitivity || [];
  if (!shapes.length && !drift.length) return '';
  const st = shapes.length ? table(['形态', '档数', '现价卖', '达标概率', '期望净均价', '悲观10%净均价'], shapes.map((r) => `<tr data-shape="${esc(r.shape)}" class="click ${r.shape === plan.shape ? 'sel' : ''}"><td><b>${SHAPES[r.shape] || esc(r.shape)}</b>${r.shape === plan.shape ? ' <span class="tag line">当前</span>' : ''}</td>
    <td>${r.rungs}</td><td>${int(r.recommended_now_shares)}</td><td>${pr(r.probability_target)}</td><td>${money(r.expected_net_avg)}</td><td>${money(r.p10_net_avg)}</td></tr>`).join('')) + '<p class="muted wl-small">点击一行切换形态。集中：达标概率最高、最差情形最差；分散：反之。期望均价三者几乎相同，差别只在风险分布。</p>' : '';
  const dt = drift.length ? table(['若真实年化趋势为', '达标概率', '期望净均价', '悲观10%均价'], drift.map((r) => `<tr><td class="${tone(r.drift_annual)}">${r.drift_annual > 0 ? '+' : ''}${(r.drift_annual * 100).toFixed(0)}%</td><td>${pr(r.probability_target)}</td><td>${money(r.expected_net_avg)}</td><td>${money(r.p10_avg)}</td></tr>`).join('')) + '<p class="muted wl-small">模型不判断方向；这张表说明同一套挂单在不同趋势下的结果。</p>' : '';
  return `<details class="card wl-card wl-fold"><summary class="row between"><span class="card-label">挂单形态与趋势敏感性</span></summary><div class="wl-two"><div>${st}</div><div>${dt}</div></div></details>`;
}

function sellBacktestCard(d) {
  const bt = d.backtest;
  if (!bt) return card('回测', emptyText('还没有回测结果（之后每周自动重跑）'));
  const names = { holdout: `${bt.holdout} 自身（样本外，未参与调参）`, basket: '一篮子港美股（参与调参）' };
  const labels = { plan: '本方案（阶梯挂单）', now: '现在一次全卖', twap: '期限内每天等量卖', single: '全部挂在目标价' };
  const ratio = (v) => (v == null ? '—' : pctv((v - 1) * 100));
  const groups = Object.entries(bt.groups || {}).map(([n, g]) => {
    const st = g.strategy, cal = g.calibration;
    if (!st) return `<div><h4 class="wl-h4">${esc(names[n] || n)}</h4>${emptyText('该格点没有样本')}</div>`;
    const iv = st.realized_interval || [];
    const models = (cal?.models || []).map((m) => `κ=${m.kappa} Brier ${m.brier.toFixed(3)}（技能 ${(m.skill * 100).toFixed(0)}%）`).join(' · ');
    return `<div><h4 class="wl-h4">${esc(names[n] || n)} <small class="muted">${(g.symbols || []).length} 只 · ${st.n} 个起点 · 有效独立样本约 ${st.n_eff.toFixed(0)}</small></h4>
      ${kpis([['模型预测达标', pr(st.predicted), '起点时刻的模型输出（平均）'], ['实际达标', pr(st.realized), `95% 区间 ${pr(iv[0])} – ${pr(iv[1])}`], ['Brier 分', st.brier.toFixed(3), '越低越好；0.25 相当于瞎猜'], ['实际费用', `${st.plan_cost_bps.toFixed(1)} bp`, `平均 ${st.plan_orders.toFixed(1)} 笔成交`]], 'compact')}
      ${table(['策略（相对起点价）', '平均净到手', '悲观10%', '达到目标比例'], Object.entries(labels).map(([k, l]) => { const it = st.strategies?.[k]; return it ? `<tr class="${k === 'plan' ? 'sel' : ''}"><td>${l}</td><td>${ratio(it.net)}</td><td>${ratio(it.p10_net)}</td><td>${k === 'now' ? '—' : pr(it.hit)}</td></tr>` : ''; }).join(''))}
      ${models ? `<p class="muted wl-small">触及概率校准：${models}</p>` : ''}</div>`;
  }).join('');
  return `<details class="card wl-card wl-fold"><summary class="row between"><span class="card-label">回测：阶梯挂单历史上表现如何</span><span class="muted wl-extra">生成于 ${local(bt.generated_at)}${bt.stale ? '（已超过一周）' : ''} · 期限 ${bt.days} 日、目标 +${Math.round(bt.premium * 100)}%</span></summary>
    <div class="wl-two">${groups}</div><p class="muted wl-note">从每个历史交易日出发，用当时之前的数据生成挂单，再用之后真实的日线最高价判断是否成交，到期未成交按收盘价卖出，计入同样的费用。相邻起点期限重叠，有效样本远少于起点数。美团历史上本方案的平均净到手低于“现在全卖”，这是限价单在涨势里过早成交、跌势里不成交的结构性代价，方案换来的是达到目标的概率。</p></details>`;
}

function executionCard(d) {
  const ex = d.execution, lot = d.position.lot_size || 100;
  const top = kpis([
    ['已卖出', `${int(ex.sold_shares)} 股`, ex.sold_shares ? `成交额 ${money(ex.sold_proceeds, 0)}` : '还没有成交'],
    ['已实现均价', money(ex.realized_avg), ex.realized_pnl == null ? '未设成本价' : `已实现盈亏 ${money(ex.realized_pnl, 0)}`],
    ['剩余持仓', `${int(ex.remaining_shares)} 股`, `按现价 ${money(ex.remaining_value, 0)}`],
    ['剩余需卖均价', money(ex.required_avg_remaining), `才能让整体均价达到 ${money(d.plan.target_avg)}`],
  ], 'compact');
  const trades = ex.trades.length ? table(['时间', '股数', '价格', '备注', ''], ex.trades.map((t) => `<tr><td>${local(t.executed_at)}</td><td>${int(t.shares)}</td><td><b>${money(t.price)}</b></td><td>${esc(t.note || '')}</td><td><button class="ghost sm" data-trade="${t.id}">删除</button></td></tr>`).join('')) : emptyText('卖出后在这里记一笔，均价和剩余所需均价会实时重算');
  return card('成交记录', top + `<form class="wl-form" id="sp-trade"><input type="number" name="shares" min="${lot}" max="${ex.remaining_shares}" step="${lot}" placeholder="股数（${lot} 股一手）" required>
    <input type="number" name="price" step="0.01" min="0" placeholder="成交价（现价 ${money(d.quote.price)}）" required><input type="datetime-local" name="time"><input type="text" name="note" placeholder="备注"><button class="primary sm" type="submit">记一笔</button></form>` + trades);
}

function hourlyCard(d) {
  const bars = (d.hourly || []).filter((b) => Number.isFinite(b.close));
  if (bars.length < 2) return card('小时线', emptyText('小时线不足'));
  const levels = d.plan.ladder.filter((r) => r.kind === 'limit' && r.shares > 0).map((r) => r.price), target = d.plan.target_avg;
  const width = 900, height = 280, pad = { top: 14, right: 62, bottom: 22, left: 8 };
  const vals = bars.map((b) => b.close), min = Math.min(...vals) * 0.995, max = Math.max(...vals, ...levels, target) * 1.005;
  const x = (i) => pad.left + i / (bars.length - 1) * (width - pad.left - pad.right);
  const y = (v) => pad.top + (max - v) / (max - min) * (height - pad.top - pad.bottom);
  const path = bars.map((b, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(b.close).toFixed(1)}`).join(' ');
  const lv = levels.map((l) => `<line class="wl-level" x1="${pad.left}" x2="${width - pad.right}" y1="${y(l)}" y2="${y(l)}"/><text class="wl-lab" x="${width - pad.right + 6}" y="${y(l) + 4}">${money(l)}</text>`).join('');
  const idx = new Map(bars.map((b, i) => [b.ts, i]));
  const marks = (d.notable_moves || []).filter((m) => idx.has(m.ts)).map((m) => `<circle class="wl-move ${tone(m.change_pct)}" cx="${x(idx.get(m.ts))}" cy="${y(m.close)}" r="5"><title>${local(m.ts * 1000)} ${pctv(m.change_pct)}</title></circle>`).join('');
  const days = [];
  bars.forEach((b, i) => { const k = new Date(b.ts * 1000).toDateString(); if (!days.length || days.at(-1).k !== k) days.push({ k, i, ts: b.ts }); });
  const every = Math.max(1, Math.ceil(days.length / 8));
  const ticks = days.filter((_, n) => n % every === 0).map((dd) => `<text class="wl-lab" x="${x(dd.i)}" y="${height - 4}">${new Date(dd.ts * 1000).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}</text>`).join('');
  const ly = y(vals.at(-1));
  const svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="小时线与挂单价位">${lv}<line class="wl-target-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y(target)}" y2="${y(target)}"/>
    <path class="wl-area" d="${path} L${x(bars.length - 1)},${height - pad.bottom} L${x(0)},${height - pad.bottom} Z"/><path class="wl-line s0" d="${path}"/>${marks}<circle class="wl-pt s0" cx="${x(bars.length - 1)}" cy="${ly}" r="4"/><text class="wl-lab" x="${width - pad.right + 6}" y="${ly + 4}">${money(vals.at(-1))}</text>${ticks}</svg>`;
  const moves = d.notable_moves || [];
  const mv = moves.length ? `<div class="wl-moves">${moves.map((m) => `<div class="wl-move-card"><div class="row between"><b class="${tone(m.change_pct)}">${pctv(m.change_pct)}</b><span class="muted wl-small">${local(m.ts * 1000)} · ${Math.abs(m.sigma).toFixed(1)}σ${m.gap ? ' · 含隔夜跳空' : ''}</span></div>
    ${m.news.length ? m.news.map((n) => `<a href="${safeUrl(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>`).join('') : '<small class="muted">窗口内没有匹配到资讯</small>'}</div>`).join('')}</div>` : emptyText('近一个月没有超过 2σ 的小时异动');
  return card('小时线与挂单价位', `<div class="wl-chart">${svg}</div><div class="wl-legend"><span><i class="wl-sw s0"></i>小时收盘</span><span><i class="wl-sw lvl"></i>挂单价</span><span><i class="wl-sw tgt"></i>目标均价 ${money(target)}</span><span><i class="wl-sw mv"></i>异动（超 2σ）</span></div>${mv}`);
}

function newsCard(d) {
  const week = d.news_7d || {}, tones = { positive: '偏多', negative: '偏空' };
  const topics = Object.entries(d.topic_counts || {}).map(([t, it]) => `<span class="tag line">${esc(t)} <b>${it.count}</b>${it.positive ? ` <small class="up">+${it.positive}</small>` : ''}${it.negative ? ` <small class="down">−${it.negative}</small>` : ''}</span>`).join('');
  const items = (d.news || []).length ? `<div class="list">${d.news.map((n) => `<a class="item wl-news" href="${safeUrl(n.url)}" target="_blank" rel="noopener noreferrer"><span>${esc(n.title)}</span>
    <small class="muted">${esc(n.source || '')} · ${local(n.published_at)}${(n.topics || []).map((t) => ` · ${esc(t)}`).join('')}${tones[n.tone] ? ` · <em class="${n.tone === 'positive' ? 'up' : 'down'}">${tones[n.tone]}</em>` : ''}</small></a>`).join('')}</div>` : emptyText('暂无相关资讯');
  return `<details class="card wl-card wl-fold"><summary class="row between"><span class="card-label">相关资讯 · 近7天 ${week.count || 0} 条</span></summary><div class="wl-topics">${topics}</div>${items}</details>`;
}

function bindSell(box, ctx) {
  const reload = (quiet) => loadSell(box, ctx, { quiet });
  const onTarget = (v, src) => {
    const n = Number(v); if (!Number.isFinite(n) || n <= 0) return;
    sp.target = n; sp.now = null;
    if (src !== 'range') box.querySelector('#sp-range').value = n;
    if (src !== 'number') box.querySelector('#sp-target').value = n.toFixed(2);
    clearTimeout(sp.timer); sp.timer = setTimeout(() => reload(true), 250);
    saveSell(ctx, { target_avg: n });
  };
  box.querySelector('#sp-range').addEventListener('input', (e) => onTarget(e.target.value, 'range'));
  box.querySelector('#sp-target').addEventListener('change', (e) => onTarget(e.target.value, 'number'));
  box.addEventListener('wl-target', (e) => onTarget(e.detail, 'chart'), { once: true });
  box.querySelectorAll('[data-seg] button').forEach((b) => b.addEventListener('click', () => {
    const name = b.parentElement.dataset.seg, v = b.dataset.v;
    if (name === 'horizon') { sp.horizon = Number(v); sp.now = null; saveSell(ctx, { horizon_days: sp.horizon }); return reload(); }
    if (name === 'spshape') { sp.shape = v; sp.now = null; saveSell(ctx, { shape: v }); return reload(); }
    if (name === 'compare') { sp.compare = Number(v); sp.now = null; saveSell(ctx, { compare_days: sp.compare }); return reload(); }
    if (name === 'metric') { sp.metric = v; store.set('switch', { qqq: sp.qqq, stock: sp.stock, metric: sp.metric }); return renderSell(box, ctx); }
  }));
  const onReturn = (key) => (e) => {
    const v = e.target.value === '' ? null : Number(e.target.value);
    if (v != null && !(Number.isFinite(v) && Math.abs(v) <= 50)) { ctx.toast('年化收益请填 -50 到 50 之间的百分数'); return; }
    sp[key] = v; store.set('switch', { qqq: sp.qqq, stock: sp.stock, metric: sp.metric }); reload(true);
  };
  box.querySelector('#sw-qqq')?.addEventListener('change', onReturn('qqq'));
  box.querySelector('#sw-stock')?.addEventListener('change', onReturn('stock'));
  box.querySelectorAll('tr[data-target]').forEach((r) => r.addEventListener('click', () => onTarget(Number(r.dataset.target), 'table')));
  box.querySelectorAll('tr[data-now]').forEach((r) => r.addEventListener('click', () => { sp.now = Number(r.dataset.now); reload(); }));
  box.querySelectorAll('tr[data-shape]').forEach((r) => r.addEventListener('click', () => { if (r.dataset.shape === sp.shape) return; sp.shape = r.dataset.shape; sp.now = null; saveSell(ctx, { shape: sp.shape }); reload(); }));
  box.querySelector('[data-act=reset-now]')?.addEventListener('click', () => { sp.now = null; reload(); });
  box.querySelectorAll('[data-trade]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm('删除这笔成交记录？')) return;
    try { await ctx.api.del(`/api/wealth/trades/${b.dataset.trade}`); reload(true); } catch (e) { ctx.toast('删除失败：' + e.message); }
  }));
  box.querySelector('#sp-trade')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), time = f.get('time');
    const body = { symbol: sp.data.symbol, shares: Number(f.get('shares')), price: Number(f.get('price')), executed_at: time ? new Date(time).toISOString() : null, note: String(f.get('note') || '').trim() };
    try { await ctx.api.post('/api/wealth/trades', body); sp.now = null; await loadSell(box, ctx, { quiet: true }); ctx.toast(`已记录卖出 ${body.shares} 股 @ ${body.price}`); }
    catch (err) { ctx.toast('记录失败：' + err.message); }
  });
}

// ================================================================ 通知
async function loadAlerts(box, ctx) {
  box.classList.add('wl-loading');
  try { renderAlerts(box, ctx, await ctx.api.get('/api/wealth/alerts?limit=60')); }
  catch (e) { box.innerHTML = card('读取失败', emptyText(e.message)); }
  finally { box.classList.remove('wl-loading'); }
}

function renderAlerts(box, ctx, d) {
  const st = d.state || {}, assets = Object.values(st.assets || {}), ex = st.exit, cfg = d.settings || {};
  const kindTag = (k) => (k === 'summary' ? '<span class="tag line">每日汇总</span>' : k === 'test' ? '<span class="tag gray">测试</span>' : k?.startsWith('exit') ? '<span class="tag warn">美团减持</span>' : '<span class="tag ok">信号变化</span>');
  const state = assets.length || ex ? table(['标的', '当前信号', '一年达标概率', '为什么'], assets.map((a) => `<tr><td><b>${esc(a.name)}</b> <small class="muted">${esc(a.symbol || '')}</small></td><td><span class="wl-action ${a.action}">${actionTag(a.action)} ${esc(a.label)}</span></td><td>${pr(a.probability)}</td><td class="wl-wrap">${esc(a.reason || '')}</td></tr>`).join('')
    + (ex ? `<tr><td><b>${esc(ex.name)}</b> <small class="muted">${esc(ex.symbol || '')}</small></td><td><span class="wl-action reduce">${actionTag('reduce')} 减持中</span></td><td>${pr(ex.probability)}</td><td class="wl-wrap">现价 ${ex.price} ${esc(ex.currency)}，剩余 ${int(ex.remaining)} 股，建议现卖 ${int(ex.now_shares)} 股，目标均价 ${ex.target_avg}</td></tr>` : '')) : emptyText('还没有算过信号，点「立即检查」算一次。');
  const log = d.log.length ? `<div class="list">${d.log.map((n) => `<div class="item wl-log"><div class="row between"><div class="row">${kindTag(n.kind)}<b>${esc(n.title)}</b></div><span class="muted wl-small">${local(n.created_at)}</span></div>
    ${n.body ? `<div class="wl-body">${esc(n.body)}</div>` : ''}${(n.reasons || []).length ? `<details><summary>理由（${n.reasons.length}）</summary>${list(n.reasons)}</details>` : ''}</div>`).join('')}</div>` : emptyText('还没有提醒记录。信号变化或每天汇总时会出现在这里。');
  box.innerHTML = `<section class="card wl-controls"><div class="row between wl-wrapline"><div>
      <div class="card-label">提醒规则</div>
      <p class="wl-small">后台每 ${cfg.refresh_minutes || 60} 分钟刷新行情、重算信号；QQQ、谷歌、微软、红利低波、纯债的加仓 / 持有 / 减仓信号变化，或美团建议现卖股数、目标均价的达标概率明显变化时，立刻提醒（页内 + Mac 系统通知），每天 ${esc(cfg.summary_time || '16:30')} 发一条汇总。${cfg.alerts === false ? '<b class="wl-warn">提醒已关闭（设置 wealth.alerts）</b>' : ''}</p>
      <p class="muted wl-small">上次检查 ${local(d.checked_at)} · 上次汇总 ${esc(d.summary_date || '—')} · ${DISCLAIMER}</p></div>
    <div class="row wl-actions"><button class="primary sm" data-act="check">立即检查</button><button class="outline sm" data-act="summary">发送汇总</button><button class="ghost sm" data-act="test">测试通知</button></div></div></section>`
    + card('当前信号', state, d.checked_at ? `算于 ${local(d.checked_at)}` : '') + card('提醒记录', log, `${d.log.length} 条`);
  box.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    try {
      const act = b.dataset.act;
      if (act === 'test') { await ctx.api.post('/api/wealth/alerts/test', {}); ctx.toast('已发送测试通知'); }
      else { const r = await ctx.api.post('/api/wealth/alerts/check', { summary: act === 'summary' }); ctx.toast(r.events.length ? `发出 ${r.events.length} 条提醒` : '信号没有变化'); }
      await loadAlerts(box, ctx);
    } catch (e) { ctx.toast('失败：' + e.message); b.disabled = false; }
  }));
}

// ================================================================ 页面
const CSS = `
.wl-page { --s0: #2a78d6; --s1: #eb6834; --s2: #1baf7a; --s3: #eda100; --s4: #e87ba4; --sp: var(--text); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .wl-page { --s0: #3987e5; --s1: #d95926; --s2: #199e70; --s3: #c98500; --s4: #d55181; } }
:root[data-theme="dark"] .wl-page { --s0: #3987e5; --s1: #d95926; --s2: #199e70; --s3: #c98500; --s4: #d55181; }
.wl-page .wl-body-box { display: flex; flex-direction: column; gap: 14px; transition: opacity .15s; }
.wl-loading { opacity: .55; pointer-events: none; }
.wl-card { min-width: 0; }
.wl-card-head { margin-bottom: 10px; gap: 10px; flex-wrap: wrap; }
.wl-extra { font-size: 12px; }
.wl-fold > summary { list-style: none; cursor: pointer; }
.wl-fold > summary::-webkit-details-marker { display: none; }
.wl-fold > summary .card-label::before { content: '▸ '; } .wl-fold[open] > summary .card-label::before { content: '▾ '; }
.wl-fold[open] > summary { margin-bottom: 10px; }
.wl-controls { display: flex; flex-direction: column; gap: 12px; }
.wl-ctl-row { display: flex; gap: 18px; flex-wrap: wrap; }
.wl-ctl { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wl-ctl .tabs { margin: 0; }
.wl-seg button { padding: 4px 12px; font-size: 13px; }
.wl-target { gap: 10px; flex-wrap: wrap; align-items: center; }
.wl-target input[type=number] { width: 96px; }
.wl-target input[type=range] { flex: 1; min-width: 160px; accent-color: var(--accent); }
.wl-inline { gap: 12px; flex-wrap: wrap; } .wl-inline input { width: 80px; margin-left: 4px; }
.wl-title { font: 600 19px/1.35 var(--serif); margin: 2px 0 4px; }
.wl-note { font-size: 12.5px; line-height: 1.6; margin: 8px 0 0; }
.wl-small { font-size: 12.5px; line-height: 1.55; margin: 4px 0 0; }
.wl-foot { margin: 4px 2px 0; }
.wl-warn { color: var(--warn); }
.wl-h { font: 600 16px var(--serif); margin: 6px 0 -4px; }
.wl-h4 { font: 600 13.5px var(--font, inherit); margin: 14px 0 6px; }
.wl-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.wl-kpis .stat small { font-size: 12px; color: var(--muted); line-height: 1.45; }
.wl-kpis.compact .stat { padding: 10px 12px; } .wl-kpis.compact .v { font-size: 20px; }
.wl-kpis .wl-hero { border-color: var(--accent); background: var(--accent-soft); } .wl-kpis .wl-hero .k { color: var(--accent); }
.wl-scroll { overflow-x: auto; max-width: 100%; }
.wl-table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
.wl-table th { text-align: right; font-weight: 500; color: var(--muted); font-size: 12px; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.wl-table td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.wl-table th:first-child, .wl-table td:first-child { text-align: left; }
.wl-table td.wl-wrap { white-space: normal; text-align: left; min-width: 200px; }
.wl-table tr.sel td { background: var(--accent-soft); }
.wl-table tr.dim td { opacity: .5; }
.wl-table tr.click { cursor: pointer; } .wl-table tr.click:hover td { background: var(--bg-2); }
.up { color: var(--ok); } .down { color: var(--err); }
.wl-bar { display: inline-flex; align-items: center; gap: 6px; min-width: 90px; justify-content: flex-end; }
.wl-bar i { display: inline-block; height: 6px; border-radius: 3px; background: var(--accent); max-width: 60px; flex: none; }
.wl-bar:has(b:empty) { min-width: 0; width: 100%; justify-content: flex-start; } .wl-bar:has(b:empty) i { max-width: 100%; }
.wl-barcell { width: 80px; } .wl-barcell i { display: block; height: 6px; border-radius: 3px; background: var(--line-2); }
.wl-sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; background: var(--muted); }
.wl-sw.s0 { background: var(--s0); } .wl-sw.s1 { background: var(--s1); } .wl-sw.s2 { background: var(--s2); } .wl-sw.s3 { background: var(--s3); } .wl-sw.s4 { background: var(--s4); } .wl-sw.sp { background: var(--sp); }
.wl-sw.h0 { background: var(--s0); } .wl-sw.h1 { background: var(--s1); } .wl-sw.h2 { background: var(--s2); } .wl-sw.h3 { background: var(--s3); } .wl-sw.h4 { background: var(--s4); } .wl-sw.h5 { background: var(--muted); }
.wl-sw.tgt { background: var(--accent); height: 2px; vertical-align: 3px; } .wl-sw.lvl { background: var(--line-2); height: 2px; vertical-align: 3px; } .wl-sw.mv { border-radius: 50%; background: var(--warn); }
.wl-action { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.wl-action .tag { padding: 0 6px; }
.wl-assets { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.wl-asset { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.wl-asset h4 { font: 600 17px var(--serif); margin: 2px 0; }
.wl-asset header { align-items: flex-start; gap: 10px; }
.wl-mini { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
.wl-mini > div { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; background: var(--bg-2); border-radius: 10px; min-width: 0; }
.wl-mini span { font-size: 12px; color: var(--muted); } .wl-mini b { font: 700 18px var(--serif); } .wl-mini small { font-size: 11.5px; color: var(--muted); line-height: 1.4; }
.wl-levels { margin: 0; font-weight: 600; font-size: 13.5px; line-height: 1.5; } .wl-scroll { overflow-x: auto; }
.wl-timing { border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.wl-pacing { font-size: 13px; margin: 0; } .wl-pacing b { margin-right: 8px; color: var(--accent); }
.wl-ul { margin: 6px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.6; } .wl-ul li + li { margin-top: 3px; } .wl-ul li.cur { font-weight: 600; }
.wl-page details > summary { cursor: pointer; font-size: 13px; color: var(--muted); }
.wl-chart { position: relative; } .wl-chart svg { width: 100%; height: auto; display: block; overflow: visible; }
.wl-grid { stroke: var(--line); stroke-width: 1; }
.wl-lab { fill: var(--muted); font-size: 11px; }
.wl-end { font-size: 11.5px; fill: var(--text); }
.wl-line { fill: none; stroke-width: 2; stroke: var(--muted); stroke-linejoin: round; stroke-linecap: round; }
.wl-line.s0, .wl-line.h0 { stroke: var(--s0); } .wl-line.s1, .wl-line.h1 { stroke: var(--s1); } .wl-line.s2, .wl-line.h2 { stroke: var(--s2); } .wl-line.s3, .wl-line.h3 { stroke: var(--s3); } .wl-line.s4, .wl-line.h4 { stroke: var(--s4); }
.wl-line.sp { stroke: var(--sp); stroke-width: 3; } .wl-line.cur { stroke-width: 3.5; }
.wl-pt { stroke: var(--panel); stroke-width: 2; } .wl-pt.s0 { fill: var(--s0); } .wl-pt.s1 { fill: var(--s1); }
.wl-best { fill: none; stroke: var(--accent); stroke-width: 2; }
.wl-target-line { stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 4 3; }
.wl-level { stroke: var(--line-2); stroke-width: 1; stroke-dasharray: 2 3; }
.wl-area { fill: var(--s0); opacity: .08; }
.wl-move { stroke: var(--panel); stroke-width: 2; fill: var(--warn); } .wl-move.up { fill: var(--ok); } .wl-move.down { fill: var(--err); }
.wl-dot-ceil { fill: var(--accent); stroke: var(--panel); stroke-width: 2; } .wl-dot-plan { fill: var(--text); stroke: var(--panel); stroke-width: 2; }
.wl-cross { stroke: var(--muted); stroke-width: 1; }
.wl-hit { fill: transparent; cursor: crosshair; }
.wl-tip { position: absolute; top: 8px; transform: translateX(12px); background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); border-radius: 10px; padding: 8px 10px; font-size: 12px; display: flex; flex-direction: column; gap: 3px; min-width: 170px; pointer-events: none; z-index: 2; }
.wl-tip.flip { transform: translateX(calc(-100% - 12px)); }
.wl-tip small { color: var(--muted); } .wl-tip span { display: flex; align-items: center; gap: 4px; } .wl-tip span.cur { font-weight: 600; } .wl-tip em { margin-left: auto; font-style: normal; padding-left: 12px; font-variant-numeric: tabular-nums; }
.wl-legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: 6px; }
.wl-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0 18px; } .wl-two .wl-wide { grid-column: 1 / -1; }
.wl-split { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 18px; align-items: start; margin: 10px 0; }
.wl-steps { margin: 0 0 10px; padding-left: 20px; font-size: 13.5px; line-height: 1.65; }
.wl-orders { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 12px; }
.wl-order { border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.wl-order > .row { gap: 8px; flex-wrap: wrap; }
.wl-verdict { font-size: 13px; line-height: 1.6; margin: 10px 0 0; } .wl-verdict b { color: var(--accent); }
.wl-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.wl-chip { display: flex; flex-direction: column; gap: 2px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 10px; font-variant-numeric: tabular-nums; }
.wl-chip span { font-size: 11.5px; color: var(--muted); } .wl-chip b { font-size: 15px; } .wl-chip em { font-style: normal; font-size: 12px; }
.wl-chip.wl-price b { font: 700 22px var(--serif); }
.wl-range { min-width: 180px; } .wl-range div { position: relative; height: 6px; border-radius: 3px; background: var(--bg-2); margin-top: 6px; } .wl-range i { position: absolute; top: -3px; width: 4px; height: 12px; border-radius: 2px; background: var(--accent); transform: translateX(-2px); }
.wl-rungs { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.wl-rung { border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font-size: 13px; }
.wl-rung dl { margin: 6px 0 0; } .wl-rung dt { color: var(--muted); font-size: 12px; margin-top: 6px; } .wl-rung dd { margin: 2px 0 0; line-height: 1.55; }
.wl-form { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; } .wl-form input { flex: 1 1 120px; min-width: 0; }
.wl-moves { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-top: 12px; }
.wl-move-card { border: 1px solid var(--line); border-radius: 12px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; font-size: 13px; } .wl-move-card a { color: var(--text); }
.wl-topics { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.wl-news { display: flex; flex-direction: column; gap: 2px; color: var(--text); text-decoration: none; } .wl-news em { font-style: normal; }
.wl-wrapline { gap: 12px; flex-wrap: wrap; align-items: flex-start; }
.wl-actions { gap: 8px; flex-wrap: wrap; }
.wl-log .row { gap: 8px; flex-wrap: wrap; } .wl-log .wl-body { font-size: 13.5px; margin-top: 4px; line-height: 1.55; }
.wl-empty { margin: 4px 0; font-size: 13px; }
@media (max-width: 720px) {
  .wl-assets, .wl-orders { grid-template-columns: minmax(0, 1fr); }
  .wl-split { grid-template-columns: minmax(0, 1fr); }
  .wl-two { grid-template-columns: minmax(0, 1fr); }
  .wl-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .wl-kpis .stat .v { font-size: 20px; }
  .wl-tip { display: none; }
}`;

export default {
  async render(el, ctx) {
    const { h, ui } = ctx;
    const view = TABS.some(([id]) => id === ctx.sub[0]) ? ctx.sub[0] : 'target';
    const body = h('div.wl-body-box');
    const status = await ctx.api.get('/api/wealth/status').catch(() => null);
    const live = status?.live;
    const refreshBtn = h('button.outline.sm', {
      onclick: async () => {
        refreshBtn.disabled = true; refreshBtn.textContent = '刷新中…';
        try { await ctx.api.post('/api/wealth/refresh', {}); ctx.toast('行情与资讯已刷新'); go(); }
        catch (e) { ctx.toast('刷新失败：' + e.message); }
        finally { refreshBtn.disabled = false; refreshBtn.replaceChildren(ui.icon('refresh'), ' 刷新行情'); }
      },
    }, [ui.icon('refresh'), ' 刷新行情']);
    const sub = `统计估算，不构成投资建议${live ? ` · 实时行情${live.connected ? '已连接' : '未连接'}` : ''}${status?.refresh?.last_completed_at ? ` · 上次刷新 ${local(status.refresh.last_completed_at)}` : ''}`;
    const tabs = h('div.tabs', {}, TABS.map(([id, label]) => h('button' + (id === view ? '.active' : ''), { onclick: () => { location.hash = `#wealth/${id}`; } }, label)));
    const go = () => (view === 'sell' ? loadSell(body, ctx) : view === 'alerts' ? loadAlerts(body, ctx) : loadTarget(body, ctx));
    el.replaceChildren(h('div.wl-page', {}, [h('style', {}, CSS), ui.pageHead('理财', sub, [refreshBtn]), tabs, body]));
    if (view === 'target' && tp.data) renderTarget(body, ctx);
    if (view === 'sell' && sp.data) renderSell(body, ctx);
    go();
    // 收到本板块的提醒时，通知页直接刷新
    const onNotify = (e) => { if (e.detail?.module === 'wealth' && location.hash.startsWith('#wealth/alerts') && document.body.contains(body)) loadAlerts(body, ctx); };
    window.addEventListener('notify', onNotify);
    const cleanup = () => { if (!document.body.contains(body)) { window.removeEventListener('notify', onNotify); window.removeEventListener('hashchange', cleanup); } };
    window.addEventListener('hashchange', cleanup);
  },
};
