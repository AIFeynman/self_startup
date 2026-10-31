// 知识库：检索 / 浏览 data/kb 下自动同步的 markdown 知识树。也是新视觉风格的参考实现。
import { annotate } from './_annotate.js';
export default {
  async render(el, ctx) {
    const { api, h, md, toast, ui, ask } = ctx;
    const st = await api.get('/api/kb/stats');
    const results = h('div');
    const reader = h('div');
    const statsBox = h('div');
    const listBox = h('div');
    let type = '';

    const show = async (path) => {
      const text = await api.get(`/api/kb/doc?path=${encodeURIComponent(path)}`);
      const body = String(text).replace(/^---[\s\S]*?---\s*/, '');
      reader.replaceChildren(h('div.card', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, path),
          h('button.icon', { title: '关闭', onclick: () => reader.replaceChildren() }, ui.icon('x'))]),
        annotate(ctx, md(body), { doc: `kb:${path}`, title: path, link: '#kb', source: body })]));
      reader.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    const row = (d) => h('div.item', { style: { cursor: 'pointer' }, onclick: () => show(d.path) }, [
      h('div.row', {}, [h('span.tag', {}, st.names[d.type] || d.type), h('span.item-title.grow', {}, d.title), h('span.muted', {}, d.date || '')]),
      d.snippet ? h('div.muted.clamp2', { html: esc(d.snippet).replace(/«/g, '<mark>').replace(/»/g, '</mark>') }) : h('div.muted.clamp2', {}, d.summary || ''),
    ]);
    const search = async (q) => {
      const rs = await api.get(`/api/kb/search?q=${encodeURIComponent(q)}&type=${type}&limit=30`);
      results.replaceChildren(ui.section(`「${q}」${type ? ' · ' + (st.names[type] || type) : ''}`, `${rs.length} 条`),
        rs.length ? h('div.card', {}, h('div.list', {}, rs.map(row))) : ui.empty('没找到', '换个说法，或直接问 Agent'));
    };

    el.append(
      ui.pageHead('知识库', `${st.total} 份知识 · 自动从各板块同步为 markdown，大模型可直接检索阅读`, [
        h('button.outline', { onclick: async () => { const r = await api.post('/api/kb/sync'); toast(`已同步 ${r.docs} 份`); } }, [ui.icon('refresh'), '同步']),
      ]),
      ui.composer({
        placeholder: '搜关键词，或切到「问 Agent」用一句话问你的积累…', autofocus: true,
        modes: [{ id: 'search', label: '搜索', placeholder: '搜关键词（中文 3 个字以上更准）…' },
          { id: 'ask', label: '问 Agent', placeholder: '比如：我之前关于 Agent 评测记过哪些结论？' }],
        hint: '目录 ' + st.dir,
        onSubmit: (t, mode) => (mode === 'ask' ? ask(t) : search(t)),
      }),
      statsBox, results, reader, listBox,
    );
    drawStats();
    drawList();

    // 点统计卡片按类型筛选，再点一次取消；筛选时列出该类型全部条目
    function drawStats() {
      statsBox.replaceChildren(ui.stats(Object.entries(st.by_type).map(([k, v]) => ({
        k: st.names[k] || k, v, active: type === k,
        onClick: () => { type = type === k ? '' : k; drawStats(); drawList(); },
      }))));
    }
    async function drawList() {
      if (!type) {
        listBox.replaceChildren(ui.section('最近更新'),
          st.recent.length ? h('div.card', {}, h('div.list', {}, st.recent.map(row))) : ui.empty('还没有知识', '在各板块记录、调研、学习后会自动出现在这里'));
        return;
      }
      const ds = await api.get(`/api/kb/list?type=${encodeURIComponent(type)}`);
      listBox.replaceChildren(ui.section(st.names[type] || type, [`${ds.length} 份 · `, h('a', { href: '#', onclick: (e) => { e.preventDefault(); type = ''; drawStats(); drawList(); } }, '显示全部')]),
        ds.length ? h('div.card', {}, h('div.list', {}, ds.map(row))) : ui.empty('这一类还没有内容'));
    }
  },
};

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
