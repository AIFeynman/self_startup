// 分级：Tier1（不限条数的重点）+ Tier2（限量）按类别展示；Tier3 回到信息推荐和产品雷达的原列表。独立于信息推荐，验证通过后再切换。
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
.tr-t3 { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; padding: 14px 16px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.tr-t3 a { padding: 4px 12px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.tr-int { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.tr-readtag { display: none; padding: 0 6px; border-radius: 6px; background: var(--bg-2); color: var(--muted); }
.tr-isread .tr-readtag { display: inline-block; }
.tr-isread .tr-t { color: var(--muted); font-weight: 500; }
@media (max-width: 720px) { .tr-row { grid-template-columns: 1fr; } .tr-side { grid-column: 1; grid-row: auto; } }
`;

const day = (s) => (s || '').slice(5, 10);

export default {
  async render(el, ctx) {
    const { api, h, ui } = ctx;
    const body = h('div');
    const load = async (refresh) => {
      body.replaceChildren(ui.empty('正在分级…'));
      const d = await api.get('/api/tiers/items' + (refresh ? '?refresh=true' : ''));
      body.replaceChildren(...view(d));
    };
    const markRead = (c, node) => {
      if (c.read) return;
      c.read = true;
      node.classList.add('tr-isread');
      const call = c.kind === 'event' ? api.post(`/api/intel/events/${c.read_ref}/read`, {})
        : c.kind === 'case' ? api.post('/api/intel/growth/read', { item_id: c.read_ref })
          : api.post('/api/feed/click', { id: c.read_ref });
      call.catch(() => { c.read = false; node.classList.remove('tr-isread'); });
    };
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
        c.href && c.url ? h('a.tr-side', { href: c.url, target: '_blank', rel: 'noopener', onclick: () => markRead(c, node) }, '原文 ↗') : null,
      ]);
      return node;
    };
    const group = (cards) => {
      const by = new Map();
      cards.forEach((c) => by.set(c.cat_label, [...(by.get(c.cat_label) || []), c]));
      return [...by].flatMap(([label, list]) => [h('div.tr-cat', {}, `${label} · ${list.length}`), h('div.tr-list', {}, list.map(row))]);
    };
    const view = (d) => [
      h('div.tr-sec', {}, [h('h3', {}, 'Tier 1'), h('span', {}, `${d.t1.length} 条 · 近 ${d.windows.t1_days} 天 · 达标全收，不限条数`)]),
      ...(d.t1.length ? group(d.t1) : [ui.empty('近几天没有达到 Tier1 门槛的内容')]),
      h('div.tr-sec', {}, [h('h3', {}, 'Tier 2'), h('span', {}, `${d.t2.length} 条 · 近 ${d.windows.t2_days} 天` + (d.t2_more ? ` · 另有 ${d.t2_more} 条超出上限` : ''))]),
      ...(d.t2.length ? group(d.t2) : [ui.empty('没有 Tier2 内容')]),
      h('div.tr-sec', {}, [h('h3', {}, 'Tier 3'), h('span', {}, `其余 ${d.t3.count} 条（共扫描 ${d.t3.scanned} 条），在原列表里快速浏览和筛选，排序不变`)]),
      h('div.tr-t3', {}, [h('span', {}, '去看：'), ...d.t3.links.map((l) => h('a', { href: l.href }, l.label))]),
      h('div.tr-sec', {}, [h('h3', {}, '兴趣线'), h('span', {}, '命中的 Tier2 内容进入榜单；长文类可提到 Tier1')]),
      h('div.tr-int', {}, d.interests.map((i) => h('span.tr-chip', {}, i))),
    ];
    const refreshBtn = h('button.btn', { onclick: () => load(true) }, [ui.icon('refresh'), '重新分级']);
    el.append(h('style', {}, CSS), ui.pageHead('分级', '把信息推荐和产品雷达按重要程度重排：Tier1 重点、Tier2 次重点、Tier3 快速浏览', [refreshBtn]), body);
    await load(false);
  },
};
