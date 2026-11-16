// 分级：按天分级，默认看今天；可切近 7 / 14 / 30 天，按天倒序看每天的 Tier1 / Tier2。Tier3 回到信息推荐和产品雷达的原列表。
const CSS = `
.tr-sec { margin: 22px 0 8px; display: flex; align-items: baseline; gap: 10px; }
.tr-sec h3 { margin: 0; font: 700 20px var(--serif); }
.tr-sec span { color: var(--muted); font-size: 12.5px; }
.tr-cat { margin: 14px 0 4px; color: var(--muted); font: 600 12.5px var(--font); }
.tr-list { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 4px 6px; }
.tr-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 14px; padding: 11px 12px; position: relative; }
.tr-row + .tr-row::before { content: ''; position: absolute; left: 12px; right: 12px; top: 0; height: 1px; background: var(--line); }
.tr-t { font: 700 15.5px/1.45 var(--serif); color: var(--text); }
.tr-t:hover { color: var(--accent); text-decoration: none; }
.tr-sum { grid-column: 1; color: var(--text); opacity: .8; font-size: 13px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.tr-meta { grid-column: 1; color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.tr-chip { padding: 0 7px; border-radius: 6px; background: var(--bg-2); font: 600 11.5px/18px var(--font); }
.tr-chip.boost { background: var(--accent-soft); color: var(--accent); }
.tr-side { grid-column: 2; grid-row: 1 / span 3; align-self: center; font-size: 12.5px; white-space: nowrap; }
.tr-side a { color: var(--muted); }
.tr-t3 { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; padding: 14px 16px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.tr-t3 a { padding: 4px 12px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.tr-int { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.tr-readtag { display: none; padding: 0 6px; border-radius: 6px; background: var(--bg-2); color: var(--muted); }
.tr-isread .tr-readtag { display: inline-block; }
.tr-isread .tr-t { color: var(--muted); font-weight: 500; }
.tr-deep { padding: 3px 12px; font-size: 12.5px; border: 1px solid var(--accent); color: var(--accent); background: transparent; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.tr-deep:hover { background: var(--accent-soft); }
.tr-deep.busy { border-color: var(--line-2); color: var(--muted); cursor: default; }
.tr-deep.busy:hover { background: transparent; }
.tr-deep.done { border-color: var(--ok); color: var(--ok); }
.tr-deep.failed { border-color: var(--err); color: var(--err); }
.tr-side { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
.tr-range { margin: 4px 0 0; }
.tr-day { margin-top: 26px; padding-top: 14px; border-top: 1px solid var(--line-2); }
.tr-day:first-of-type { border-top: none; padding-top: 0; }
.tr-day > h2 { margin: 0; font: 700 22px var(--serif); display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.tr-day > h2 span { color: var(--muted); font: 500 12.5px var(--font); }
.tr-day details > summary { cursor: pointer; list-style: none; }
.tr-day details > summary::-webkit-details-marker { display: none; }
.tr-day details > summary h3::before { content: '▸ '; color: var(--muted); }
.tr-day details[open] > summary h3::before { content: '▾ '; }
.tr-pending { color: var(--muted); padding: 10px 0; font-size: 13px; }
@media (max-width: 720px) { .tr-row { grid-template-columns: 1fr; } .tr-side { grid-column: 1; grid-row: auto; } .tr-day > h2 { font-size: 19px; } }
`;

const md = (d) => `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const day = (s) => (/T\d/.test(s || '') && !isNaN(new Date(s)) ? md(new Date(s)) : (s || '').slice(5, 10));
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const dayName = (d, today) => `${day(d)} ${WEEK[new Date(d + 'T12:00:00').getDay()]}${d === today ? ' · 今天' : ''}`;
const RANGE_LABEL = { 1: '当天', 7: '近 7 天', 14: '近 14 天', 30: '近 30 天' };

export default {
  async render(el, ctx) {
    const { api, h, ui, toast } = ctx;
    const rows = new Map();
    const body = h('div');
    const rangeBar = h('div.tabs.tr-range');
    let range = 1, seq = 0, retry = null;
    const url = (refresh) => `/api/tiers/items?days=${range}` + (refresh ? '&refresh=true' : '');
    const load = async (refresh) => {
      const my = ++seq;
      clearTimeout(retry);
      body.replaceChildren(ui.empty(range === 1 ? '正在分级…' : `正在读取${RANGE_LABEL[range]}的分级…`));
      const d = await api.get(url(refresh));
      if (my !== seq) return;
      rows.clear();
      body.replaceChildren(...(range === 1 ? today(d) : history(d)));
      if (d.days.some((x) => x.pending)) retry = setTimeout(() => el.isConnected && my === seq && load(false), 8000);
    };
    const drawRange = (opts) => rangeBar.replaceChildren(...opts.map((n) => h('button' + (n === range ? '.active' : ''), {
      onclick: () => { if (n === range) return; range = n; drawRange(opts); load(false); },
    }, RANGE_LABEL[n])));
    const markRead = (c, node) => {
      if (c.read) return;
      c.read = true;
      node.classList.add('tr-isread');
      const call = c.kind === 'event' ? api.post(`/api/intel/events/${c.read_ref}/read`, {})
        : c.kind === 'case' ? api.post('/api/intel/growth/read', { item_id: c.read_ref })
          : api.post('/api/feed/click', { id: c.read_ref });
      call.catch(() => { c.read = false; node.classList.remove('tr-isread'); });
    };
    // 深读与信息推荐同一套：POST /api/learn/items 后台解析，完成后再点打开 #learn/item/<id>，状态存在学习模块里
    const setDeep = (c, st, node) => { c.deep_read = st; node.querySelector('.tr-deep')?.replaceWith(deepBtn(c, node)); };
    const deepGo = async (c, node) => {
      const old = c.deep_read;
      if (old?.status === 'done') { location.hash = `#learn/item/${old.id}`; return; }
      if (old && old.status !== 'failed') { toast('正在解析，完成后会提醒'); return; }
      setDeep(c, { status: 'queued' }, node);
      try {
        const it = await api.post('/api/learn/items', { url: c.url, reuse: true });
        setDeep(c, { id: it.id, status: it.status }, node);
        if (it.status !== 'done') toast('已开始深度解析，完成后会提醒');
      } catch (e) { setDeep(c, old, node); toast('开始深读失败：' + e.message, true); }
    };
    const deepBtn = (c, node) => {
      const d = c.deep_read, s = d?.status;
      if (s === 'done' && d.reading) return h('button.tr-deep.done', { title: '回到上次读到的位置', onclick: () => deepGo(c, node) }, `接着读 ${Math.round(d.pos * 100)}%`);
      if (s === 'done') return h('button.tr-deep.done', { title: '打开解析结果', onclick: () => deepGo(c, node) }, '深度完成');
      if (s === 'failed') return h('button.tr-deep.failed', { title: '上次解析失败，点击重试', onclick: () => deepGo(c, node) }, '解析失败，重试');
      if (s) return h('button.tr-deep.busy', { disabled: true, title: '后台解析中，完成后会提醒，可以继续看别的' }, '解析中');
      return h('button.tr-deep', { title: '后台开始深度解析，不离开当前页', onclick: () => deepGo(c, node) }, '深读');
    };
    const onDeepDone = async ({ detail: j }) => {
      if (!el.isConnected) return document.removeEventListener('job-done', onDeepDone);
      const iid = +/^learn:item:(\d+)$/.exec(j.ref || '')?.[1];
      if (!iid) return;
      await new Promise((r) => setTimeout(r, 1500));
      const d = await api.get(url(false));
      for (const n of d.days.flatMap((x) => [...(x.t1 || []), ...(x.t2 || [])])) { const hit = rows.get(n.id); if (hit && n.deep_read) setDeep(hit.c, n.deep_read, hit.node); }
    };
    document.addEventListener('job-done', onDeepDone);
    const row = (c) => {
      const node = h('div.tr-row' + (c.read ? '.tr-isread' : ''), {}, [
        h('a.tr-t', { href: c.href || c.url, onclick: () => markRead(c, node), ...(c.href ? {} : { target: '_blank', rel: 'noopener' }) }, c.title),
        c.gist || c.summary ? h('div.tr-sum', {}, c.gist || c.summary) : null,
        h('div.tr-meta', {}, [
          c.deep != null ? h('span.tr-chip.boost', {}, `深读分 ${c.deep.toFixed(2)}`) : null,
          c.pick != null ? h('span.tr-chip.boost', {}, `扫读分 ${c.pick.toFixed(2)}`) : null,
          c.boosted ? h('span.tr-chip.boost', {}, '兴趣提权') : null,
          h('span.tr-readtag', {}, '已读'),
          h('span', {}, c.source), h('span', {}, day(c.date)), h('span', {}, c.why.join(' · ')),
        ]),
        h('div.tr-side', {}, [
          c.url ? h('span.tr-deep-slot') : null,
          c.href && c.url ? h('a', { href: c.url, target: '_blank', rel: 'noopener', onclick: () => markRead(c, node) }, '原文 ↗') : null,
        ]),
      ]);
      node.querySelector('.tr-deep-slot')?.replaceWith(deepBtn(c, node));
      rows.set(c.id, { c, node });
      return node;
    };
    const group = (cards) => {
      const by = new Map();
      cards.forEach((c) => by.set(c.cat_label, [...(by.get(c.cat_label) || []), c]));
      return [...by].flatMap(([label, list]) => [h('div.tr-cat', {}, `${label} · ${list.length}`), h('div.tr-list', {}, list.map(row))]);
    };
    const tier3 = (count, scanned, links) => [
      h('div.tr-sec', {}, [h('h3', {}, 'Tier 3'), h('span', {}, `其余 ${count} 条（共扫描 ${scanned} 条），在原列表里快速浏览和筛选，排序不变`)]),
      h('div.tr-t3', {}, [h('span', {}, '去看：'), ...links.map((l) => h('a', { href: l.href }, l.label))]),
    ];
    const interests = (d) => [
      h('div.tr-sec', {}, [h('h3', {}, '兴趣线'), h('span', {}, '命中的 Tier2 内容进入榜单；长文类可提到 Tier1')]),
      h('div.tr-int', {}, d.interests.map((i) => h('span.tr-chip', {}, i))),
    ];
    const t2head = (x) => h('div.tr-sec', {}, [h('h3', {}, 'Tier 2'), h('span', {}, `${x.t2.length} 条` + (x.t2_more ? ` · 另有 ${x.t2_more} 条超出上限` : ''))]);
    const today = (d) => {
      const x = d.days[0];
      return [
        h('div.tr-sec', {}, [h('h3', {}, 'Tier 1'), h('span', {}, `${x.t1.length} 条 · ${dayName(x.day, d.today)} · 达标全收，不限条数`)]),
        ...(x.t1.length ? group(x.t1) : [ui.empty('今天还没有达到 Tier1 门槛的内容，可以切到近 7 天看历史')]),
        t2head(x),
        ...(x.t2.length ? group(x.t2) : [ui.empty('今天还没有 Tier2 内容')]),
        ...tier3(x.t3.count, x.t3.scanned, x.t3.links),
        ...interests(d),
      ];
    };
    const history = (d) => {
      const done = d.days.filter((x) => !x.pending);
      const n1 = done.reduce((a, x) => a + x.t1.length, 0), n2 = done.reduce((a, x) => a + x.t2.length, 0);
      const pend = d.days.length - done.length;
      const head = h('div.tr-sec', {}, [h('h3', {}, RANGE_LABEL[d.range]), h('span', {},
        `Tier1 共 ${n1} 条 · Tier2 共 ${n2} 条 · 每天一组，新的在前` + (pend ? ` · ${pend} 天还在后台生成，稍后自动刷新` : ''))]);
      const dayBlock = (x) => {
        if (x.pending) return h('section.tr-day', {}, [h('h2', {}, dayName(x.day, d.today)), h('div.tr-pending', {}, '这一天的分级还在后台生成…')]);
        return h('section.tr-day', {}, [
          h('h2', {}, [dayName(x.day, d.today), h('span', {}, `Tier1 ${x.t1.length} 条 · Tier2 ${x.t2.length} 条 · Tier3 ${x.t3.count} 条`)]),
          h('div.tr-sec', {}, [h('h3', {}, 'Tier 1'), h('span', {}, `${x.t1.length} 条`)]),
          ...(x.t1.length ? group(x.t1) : [ui.empty('这一天没有达到 Tier1 门槛的内容')]),
          x.t2.length ? h('details', {}, [h('summary', {}, t2head(x)), ...group(x.t2)]) : t2head(x),
        ]);
      };
      const links = done[0]?.t3.links || [];
      return [head, ...d.days.map(dayBlock),
        ...tier3(done.reduce((a, x) => a + x.t3.count, 0), done.reduce((a, x) => a + x.t3.scanned, 0), links), ...interests(d)];
    };
    const refreshBtn = h('button.btn', { onclick: () => load(true) }, [ui.icon('refresh'), '重新分级']);
    el.append(h('style', {}, CSS), ui.pageHead('分级', '把信息推荐和产品雷达按天、按重要程度重排：Tier1 重点、Tier2 次重点、Tier3 快速浏览；默认看今天，可切近 7 / 14 / 30 天看历史', [refreshBtn]), rangeBar, body);
    drawRange([1, 7, 14, 30]);
    await load(false);
  },
};
