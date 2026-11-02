// 产品雷达：关注公司的产品 / 商业变化流，B 级及以上带「五层解读卡」。
// 路由：#intel（变化流）· #intel/e/<id>（事件 + 解读卡）· #intel/c/<slug>（公司时间线）· #intel/companies · #intel/sources
const LV = { S: ['S', 'err'], A: ['A', 'warn'], B: ['B', 'ok'], C: ['C', 'gray'] };
const CARD = { queued: ['解读中', 'line'], done: ['解读卡', 'ok'], incomplete: ['解读卡不完整', 'warn'], failed: ['解读失败', 'err'] };
const DAYS = [['7', '7 天'], ['30', '30 天'], ['90', '90 天'], ['0', '全部']];
const st = { level: 'S,A,B', days: '30', company: '', q: '' };

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
.it-filters select, .it-filters input { padding: 5px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); color: var(--text); }
.it-src { font-size: 13px; padding: 3px 0; }
.it-acts { display: flex; gap: 8px; align-items: center; flex: none; } .it-acts select { width: auto; }
.it-card h2 { font: 700 16px var(--serif); margin: 18px 0 6px; padding-top: 10px; border-top: 1px solid var(--line); }
.it-card h2:first-child { border-top: 0; margin-top: 0; padding-top: 0; }
.it-card strong { color: var(--warn); }
.it-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.it-tbl td, .it-tbl th { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.it-tbl .err { color: var(--err); }
`;

const tag = (h, [t, c]) => h('span.tag.' + c, {}, t);
const ago = (s) => (s ? s.slice(5, 16).replace('T', ' ') : '-');

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
  const qs = new URLSearchParams({ level: st.level, days: st.days, company: st.company, q: st.q, limit: 300 });
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
  const tabs = h('div.tabs', {}, [['变化流', '#intel'], ['公司', '#intel/companies'], ['信息源', '#intel/sources']].map(([t, href], i) =>
    h('button' + (i === 0 ? '.active' : ''), { onclick: () => { location.hash = href; } }, t)));
  const lvSel = h('select', { onchange: (e) => { st.level = e.target.value; ctx.refresh(); } },
    [['S,A,B', 'B 级及以上'], ['S,A', 'A 级及以上'], ['S', '只看 S'], ['S,A,B,C', '全部级别']].map(([v, t]) => h('option', { value: v, selected: st.level === v }, t)));
  const daySel = h('select', { onchange: (e) => { st.days = e.target.value; ctx.refresh(); } },
    DAYS.map(([v, t]) => h('option', { value: v, selected: st.days === v }, t)));
  const coSel = h('select', { onchange: (e) => { st.company = e.target.value; ctx.refresh(); } },
    [h('option', { value: '' }, '全部公司'), ...cos.map((c) => h('option', { value: c.slug, selected: st.company === c.slug }, `${c.name}（${c.events}）`))]);
  const q = h('input', { placeholder: '搜标题 / 产品', value: st.q, onkeydown: (e) => { if (e.key === 'Enter') { st.q = e.target.value; ctx.refresh(); } } });
  el.append(tabs, h('div.it-filters', {}, [lvSel, daySel, coSel, q]));
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
  const cs = CARD[e.card_status];
  el.append(ui.section('五层解读卡', cs ? cs[0] : (e.level === 'C' ? 'C 级默认不出卡，改成 B 级以上会自动生成' : '未生成')));
  if (e.card?.content) {
    if (e.card.missing.length) el.append(h('div.card', { style: { borderColor: 'var(--warn)' } }, `缺少：${e.card.missing.join('、')}（或缺带链接 / 日期的出处）`));
    // 卡片出处写成 [来源](链接, 日期)，marked 不认这种写法，先拆成 [来源](链接)（日期）
    const box = md(e.card.content.replace(/\]\((https?:\/\/[^)\s,]+),\s*([^)]*)\)/g, '](\$1)（\$2）')); box.classList.add('it-card');
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
  el.append(h('div.muted', { style: { marginBottom: '8px' } }, h('a', { href: '#intel/companies' }, '← 公司')));
  el.append(ui.pageHead(c.name, `T${c.tier} · ${c.category || '-'} · ${c.events.length} 个事件 · ${c.sources.length} 个官方源`));
  if (c.experiences.length) {
    el.append(ui.section('我的一手体验', '来自调研板块'), h('div.card', {}, c.experiences.map((p) =>
      h('div.it-src', {}, [h('a', { href: '#research' }, p.name), h('span.muted', {}, ` · ${p.rating ?? '-'} 分 · ${p.used_at || ''}`)]))));
  }
  el.append(ui.section('时间线'));
  el.append(...(c.events.length ? groupByDay(h, c.events, { showCompany: false }) : [ui.empty('还没有事件')]));
}

async function renderCompanies(el, ctx) {
  const { api, h, ui, toast } = ctx;
  const cos = await api.get('/api/intel/companies');
  el.append(ui.pageHead('产品雷达 · 公司', `${cos.filter((c) => c.enabled).length} 家在跟`));
  el.append(h('div.tabs', {}, [['变化流', '#intel'], ['公司', '#intel/companies'], ['信息源', '#intel/sources']].map(([t, href], i) =>
    h('button' + (i === 1 ? '.active' : ''), { onclick: () => { location.hash = href; } }, t))));
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
  el.append(h('div.tabs', {}, [['变化流', '#intel'], ['公司', '#intel/companies'], ['信息源', '#intel/sources']].map(([t, href], i) =>
    h('button' + (i === 2 ? '.active' : ''), { onclick: () => { location.hash = href; } }, t))));
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
    return renderStream(el, ctx);
  },
};
