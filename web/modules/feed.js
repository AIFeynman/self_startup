// 信息推荐：按热度/新鲜度/兴趣/反馈排序的 AI 信息流；只展示标题 + 简介 + 链接 + 推荐理由。
const TABS = [['', '全部'], ['paper', '论文'], ['blog', '博客'], ['product', '产品'], ['repo', '项目'], ['discussion', '讨论'], ['saved', '已收藏']];
const st = { tab: '', q: '', limit: 60 };

export default {
  async render(el, ctx) {
    const { api, h, toast, openChat } = ctx;
    const settings = await api.get('/api/settings');
    const interests = h('input', { value: (settings.feed?.interests || []).join(', '), placeholder: '兴趣词，逗号分隔' });
    const statusEl = h('span.muted');
    const refreshBtn = h('button.primary', { onclick: doRefresh }, '刷新信息源');
    const search = h('input', { placeholder: '筛选标题/简介…', value: st.q, style: { maxWidth: '220px' },
      oninput: (e) => { st.q = e.target.value; clearTimeout(search._t); search._t = setTimeout(load, 300); } });
    const tabs = h('div.tabs');
    const list = h('div.list');
    const more = h('div');

    el.append(
      h('div.card', {}, [
        h('div.row', {}, [refreshBtn, statusEl]),
        h('div.row', { style: { marginTop: '8px' } }, [
          h('span.muted', { style: { whiteSpace: 'nowrap' } }, '兴趣词'), h('div', { style: { flex: 1 } }, interests),
          h('button', { onclick: saveInterests }, '保存'),
        ]),
      ]),
      h('div.row', {}, [tabs, search]), list, more,
    );
    Object.assign(tabs.style, { flex: '1 1 360px', flexWrap: 'wrap' });

    function renderTabs() {
      tabs.innerHTML = '';
      for (const [id, name] of TABS) {
        tabs.append(h('button' + (st.tab === id ? '.active' : ''), { style: { whiteSpace: 'nowrap' }, onclick: () => { st.tab = id; st.limit = 60; renderTabs(); load(); } }, name));
      }
    }

    async function saveInterests() {
      const arr = interests.value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean);
      await api.put('/api/settings', { feed: { interests: arr } });
      toast('兴趣词已保存'); load();
    }

    function fmtStatus(s) {
      const parts = [`库内 ${s.total} 条`];
      if (s.running) parts.unshift(`刷新中（${s.started_at.slice(11)} 开始）…`);
      else if (s.finished_at) parts.unshift(`上次刷新 ${s.finished_at.replace('T', ' ').slice(5, 16)}`);
      const res = Object.entries(s.results || {}).map(([k, v]) => `${k} ${v.count}${v.errors?.length ? '⚠' : ''}`);
      if (res.length) parts.push(res.join(' · '));
      return parts.join(' ｜ ');
    }

    async function showStatus() {
      const s = await api.get('/api/feed/status');
      statusEl.textContent = fmtStatus(s);
      const errs = Object.entries(s.results || {}).flatMap(([k, v]) => (v.errors || []).map((e) => `${k}: ${e}`));
      statusEl.title = errs.join('\n');
      refreshBtn.disabled = s.running;
      return s;
    }

    async function doRefresh() {
      await api.post('/api/feed/refresh', {});
      for (;;) {
        const s = await showStatus();
        if (!s.running) break;
        await new Promise((r) => setTimeout(r, 2000));
      }
      toast('刷新完成'); load();
    }

    async function fb(item, patch, row) {
      const r = await api.post('/api/feed/feedback', { id: item.id, ...patch });
      item.feedback = r;
      if (r.hidden && st.tab !== 'saved') { row.remove(); return; }
      row.replaceWith(renderRow(item));
    }

    function renderRow(x) {
      const f = x.feedback || {};
      const row = h('div.item');
      const date = (x.date || '').slice(0, 10);
      row.append(
        h('div', {}, [h('a', { href: x.url, target: '_blank', rel: 'noopener', style: { fontWeight: 600 } }, x.title)]),
        h('div.row', { style: { gap: '4px', margin: '2px 0' } }, [
          h('span.tag', {}, x.source_label),
          (x.extra?.feed || x.extra?.subreddit) && h('span.tag', {}, x.extra.feed || `r/${x.extra.subreddit}`),
          x.extra?.origin === 'learn_evolve' && h('span.tag', {}, 'learn_evolve'),
          date && h('span.muted', {}, date),
          x.extra?.hn_url && h('a.muted', { href: x.extra.hn_url, target: '_blank', rel: 'noopener' }, 'HN 讨论'),
        ]),
        x.summary && h('div', { style: { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, x.summary),
        x.why && h('div.muted', {}, '推荐理由：' + x.why),
        h('div.row', { style: { gap: '4px', marginTop: '4px' } }, [
          h('button' + (f.vote > 0 ? '.primary' : ''), { title: '赞', onclick: () => fb(x, { vote: f.vote > 0 ? 0 : 1 }, row) }, '👍'),
          h('button' + (f.vote < 0 ? '.primary' : ''), { title: '踩', onclick: () => fb(x, { vote: f.vote < 0 ? 0 : -1 }, row) }, '👎'),
          h('button' + (f.saved ? '.primary' : ''), { title: '收藏', onclick: () => fb(x, { saved: !f.saved }, row) }, f.saved ? '★' : '☆'),
          h('button.ghost', { onclick: () => fb(x, { hidden: !f.hidden }, row) }, f.hidden ? '取消隐藏' : '隐藏'),
          h('button.ghost', { onclick: () => openChat({ module: 'learn', title: '深度学习', prefill: `深度解析：${x.url}` }) }, '深度学习'),
        ]),
      );
      return row;
    }

    async function load() {
      const p = new URLSearchParams({ limit: st.limit, q: st.q });
      if (st.tab === 'saved') p.set('saved', 'true'); else if (st.tab) p.set('type', st.tab);
      const r = await api.get('/api/feed/items?' + p);
      list.innerHTML = ''; more.innerHTML = '';
      if (!r.items.length) list.append(h('div.muted', {}, st.tab === 'saved' ? '还没有收藏。' : '暂无内容，点「刷新信息源」抓取。'));
      for (const x of r.items) list.append(renderRow(x));
      if (r.total > r.items.length) more.append(h('button.ghost', { onclick: () => { st.limit += 60; load(); } }, `加载更多（共 ${r.total} 条）`));
    }

    const onAgent = () => { if (!el.isConnected) return document.removeEventListener('agent-done', onAgent); load(); };
    document.addEventListener('agent-done', onAgent);
    renderTabs();
    const s = await showStatus();
    await load();
    if (s.running) doRefresh();
  },
};
