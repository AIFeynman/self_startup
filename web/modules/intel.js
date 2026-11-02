// 产品雷达：目前只有「开源雷达」标签——stars ≥ 1000 的 GitHub 项目按功能检索（设计稿 docs/designs/2026-11-01-oss-radar-design.md）。
// 有输入：改写 + 多路召回 + 精排，可切「相关性 | star」；没输入：按领域浏览（star 倒序）。
// 路由：#intel/oss/<查询>（信息推荐卡片的「同类项目」跳这里）。
const TASKS = { collect: '全量采集', label: '标注', daily: '每日新增', weekly: '每周刷新' };
const ACTIVE = [['0', '不限活跃'], ['30', '30 天内有更新'], ['180', '半年内有更新'], ['365', '一年内有更新']];
const AI_NAME = { core: 'AI 本身', for_ai: '给 AI 用', ai_powered: 'AI 应用', none: '' };
const st = { q: '', by: 'rel', kind: '', domain: '', lang: '', active: '0', offset: 0 };
const fmtStars = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n));

const CSS = `
.os-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 4px 0 14px; }
.os-bar select { font: inherit; font-size: 13px; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text); max-width: 180px; }
.os-seg { display: inline-flex; border: 1px solid var(--line-2); border-radius: 8px; overflow: hidden; }
.os-seg button { border: none; border-radius: 0; padding: 4px 14px; font-size: 12.5px; background: var(--panel); color: var(--muted); }
.os-seg button.on { background: var(--accent-soft); color: var(--accent); }
.os-item .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
.os-item .why { color: var(--accent); font-size: 13px; margin-top: 4px; }
.os-item .acts { display: flex; gap: 4px; margin-left: auto; }
.os-item .acts button { padding: 2px 10px; font-size: 12px; }
.os-intent { font-size: 12.5px; color: var(--muted); margin: -6px 0 10px; }
.os-run { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.os-run .progress { flex: 1; min-width: 120px; }
`;

export default {
  async render(el, ctx) {
    const { api, h, toast, ui } = ctx;
    const [tax, status0] = await Promise.all([api.get('/api/intel/oss/taxonomy'), api.get('/api/intel/oss/status')]);
    const dname = {};
    tax.domains.forEach((d) => d.children.forEach((c) => { dname[c.code] = c.name; }));
    const kname = Object.fromEntries(tax.kinds.map((k) => [k.code, k.name]));
    st.q = ctx.sub[0] === 'oss' && ctx.sub[1] ? decodeURIComponent(ctx.sub[1]) : '';
    const setHash = (q) => history.replaceState(null, '', q ? '#intel/oss/' + encodeURIComponent(q) : '#intel');   // 改 hash 会整页重绘，这里只记地址

    const runBox = h('div.card.flat');
    const bar = h('div.os-bar');
    const intentBox = h('div');
    const listBox = h('div');
    let timer = null;

    // ---------- 后台任务 ----------
    const drawRun = (s) => {
      const r = s.running;
      const p = r ? JSON.parse(r.progress || '{}') : {};
      const la = p.label_at;   // [已处理, 总数, {labeled, cost}]
      const line = r ? [h('span.tag', {}, `${TASKS[r.task] || r.task}进行中`),
        la ? ui.progress((la[0] / Math.max(la[1], 1)) * 100) : h('span.muted', {}, p.page ? `已拉 ${p.page[0]}（${p.page[1]} 个）` : p.refresh_at ? `刷新 ${p.refresh_at[0]}/${p.refresh_at[1]}` : '准备中…'),
        la ? h('span.muted', {}, `${la[0]}/${la[1]} · 已标 ${la[2].labeled} · ≈$${la[2].cost}`) : null,
        h('button.ghost', { onclick: async () => { await api.post(`/api/intel/oss/runs/${r.id}/stop`); toast('当前批次做完后停'); } }, '停止')]
        : [h('span.muted', {}, s.runs[0] ? `上次：${TASKS[s.runs[0].task]} ${s.runs[0].status === 'done' ? '完成' : s.runs[0].status === 'failed' ? '失败' : '已停'} · ${(s.runs[0].finished || s.runs[0].started || '').slice(5, 16).replace('T', ' ')}` : '还没跑过'),
          ...Object.entries(TASKS).map(([t, n]) => h('button.outline', { onclick: () => start(t, n, s) }, n))];
      runBox.replaceChildren(...[h('div.os-run', {}, line),
        s.runs[0]?.status === 'failed' ? h('div.muted', { style: { color: 'var(--err)' } }, (s.runs[0].log || '').split('\n')[0]) : null].filter(Boolean));
      clearTimeout(timer);
      if (r) timer = setTimeout(async () => { if (runBox.isConnected) drawAll(await api.get('/api/intel/oss/status')); }, 5000);
    };
    const start = async (task, name, s) => {
      let limit = 0;
      if (task === 'label') {
        const v = prompt(`待标注 ${s.todo} 个（订阅 Haiku，每 50 个一次调用，4 路并行）。这次标多少个？0 = 全部`, String(Math.min(s.todo, 500)));
        if (v === null) return;
        limit = parseInt(v, 10) || 0;
      } else if (task === 'collect' && !confirm('全量采集 stars ≥ 1000 的仓库（约 6.6 万个，受 GitHub 搜索限流约 20-40 分钟，只调 GitHub 不调模型）。开始？')) return;
      try { await api.post('/api/intel/oss/runs', { task, limit }); toast(`${name}已开始`); drawAll(await api.get('/api/intel/oss/status')); } catch (e) { toast(e.message, true); }
    };
    const drawAll = (s) => {
      head.querySelector('.sub').textContent = sub(s);
      drawRun(s);
    };
    const sub = (s) => `${s.repos} 个仓库 · 已标注 ${s.labeled} · 待标注 ${s.todo} · 分类体系 ${s.tax_ver}`;

    // ---------- 检索 / 浏览 ----------
    const sel = (key, opts, onchange) => h('select', { onchange: (e) => { st[key] = e.target.value; st.offset = 0; onchange(); } },
      opts.map(([v, n]) => h('option', { value: v, selected: st[key] === v }, n)));
    const drawBar = () => {
      const seg = (id, name) => h('button' + (st.by === id ? '.on' : ''), { onclick: () => { st.by = id; drawBar(); load(); } }, name);
      const domOpts = [['', '全部领域'], ...tax.domains.flatMap((d) => d.children.map((c) => [c.code, `${d.name} · ${c.name}${status0.by_domain[c.code] ? ` (${status0.by_domain[c.code]})` : ''}`]))];
      bar.replaceChildren(...[
        st.q ? h('div.os-seg', {}, [seg('rel', '相关性'), seg('stars', 'star')]) : null,
        sel('domain', domOpts, load), sel('kind', [['', '全部类型'], ...tax.kinds.map((k) => [k.code, k.name])], load),
        sel('lang', [['', '全部语言'], ...['Python', 'TypeScript', 'JavaScript', 'Go', 'Rust', 'Java', 'C++', 'C', 'Swift', 'Kotlin', 'C#', 'Shell', 'Jupyter Notebook'].map((l) => [l, l])], load),
        sel('active', ACTIVE, load),
        st.q ? h('button.ghost', { onclick: () => { st.q = ''; comp.setValue(''); setHash(''); drawBar(); load(); } }, ['清除「', st.q, '」']) : null].filter(Boolean));
    };
    const card = (x) => h('div.item.os-item', {}, [
      h('div.row', {}, [
        h('a.item-title', { href: `https://github.com/${x.name}`, target: '_blank', rel: 'noopener' }, x.name),
        h('span.tag.line', {}, ['★ ', fmtStars(x.stars)]), x.lang ? h('span.muted', {}, x.lang) : null,
        h('span.tag.gray', {}, kname[x.k] || x.k), h('span.tag', { title: '点击只看这个领域', style: { cursor: 'pointer' }, onclick: () => { st.domain = x.d; st.offset = 0; drawBar(); load(); } }, dname[x.d] || x.d),
        AI_NAME[x.ai] ? h('span.tag.ok', {}, AI_NAME[x.ai]) : null,
        x.archived ? h('span.tag.warn', {}, '已归档') : x.pushed ? h('span.muted', {}, '更新于 ' + x.pushed.slice(0, 10)) : null,
        h('span.acts', {}, [
          h('button.ghost', { title: '用学习板块的项目深读', onclick: () => deep(x) }, '深读'),
          h('button.ghost', { title: '这个作者以后的新仓库进信息推荐', onclick: () => follow(x) }, '关注作者')]),
      ]),
      h('div', {}, x.s),
      x.why ? h('div.why', {}, '✓ ' + x.why) : null,
      h('div.tags', {}, (x.t || []).map((t) => h('span.tag.line', { style: { cursor: 'pointer' }, title: '按这个功能搜', onclick: () => go(t) }, t))),
    ]);
    const deep = async (x) => {
      try { const it = await api.post('/api/learn/items', { url: `https://github.com/${x.name}`, reuse: true }); location.hash = `#learn/item/${it.id}`; } catch (e) { toast('开始深读失败：' + e.message, true); }
    };
    const follow = async (x) => {
      try { await api.post('/api/feed/sources', { group: 'github', value: x.name.split('/')[0] }); toast(`已关注 ${x.name.split('/')[0]}`); } catch (e) { toast('关注失败：' + e.message, true); }
    };
    const go = (q) => { st.q = q; setHash(q); st.offset = 0; comp.setValue(q); drawBar(); load(); };

    async function load(more = false) {
      if (!more) st.offset = 0;
      const p = new URLSearchParams({ q: st.q, by: st.by, kind: st.kind, domain: st.domain, lang: st.lang, active: st.active, offset: st.offset, k: st.q ? 30 : 40 });
      if (!more) listBox.replaceChildren(h('div.muted', {}, st.q ? '检索中（改写需求 → 召回 → 精排，首次约几秒）…' : '加载中…'));
      let r;
      try { r = await api.get('/api/intel/oss/search?' + p); } catch (e) { listBox.replaceChildren(ui.empty('检索失败', e.message)); return; }
      intentBox.replaceChildren(r.mode === 'search' ? h('div.os-intent', {}, [
        '理解为：', (r.intent.must || []).join(' / '),
        r.intent.domains?.length ? ` · 领域 ${r.intent.domains.map((d) => dname[d] || d).join('、')}` : '',
        r.intent.not?.length ? ` · 排除 ${r.intent.not.join('、')}` : '',
        r.reranked ? '' : ' · 未精排', ...(r.errors || []).map((e) => h('div', { style: { color: 'var(--warn)' } }, e))]) : '');
      const items = r.results.map(card);
      if (more) { listBox.querySelector('.list')?.append(...items); } else {
        const title = r.mode === 'search' ? `「${st.q}」` : (st.domain ? dname[st.domain] : '全部领域') + ' · 按 star';
        listBox.replaceChildren(ui.section(title, r.mode === 'search' ? `${r.results.length} 个` : `共 ${r.total} 个`),
          items.length ? h('div.card', {}, h('div.list', {}, items))
            : ui.empty(status0.labeled ? '没找到' : '库还是空的', status0.labeled ? '换个说法，或去掉筛选' : '先点上面的「全量采集」，再点「标注」'));
      }
      listBox.querySelector('.os-more')?.remove();
      if (r.mode === 'browse' && st.offset + r.results.length < r.total) {
        listBox.append(h('button.ghost.os-more', { onclick: () => { st.offset += r.results.length; load(true); } }, '加载更多'));
      }
    }

    const comp = ui.composer({
      placeholder: '用一句话说你想做什么，比如：我想做 PDF 解析 / 给网站加全文搜索 / 本地跑大模型', autofocus: !st.q, value: st.q,
      hint: '按功能找 stars ≥ 1000 的开源项目',
      onSubmit: (t) => { st.q = t; setHash(t); drawBar(); load(); return false; },
    });
    const head = ui.pageHead('产品雷达', sub(status0));
    el.append(h('style', {}, CSS), head, h('div.tabs', {}, [h('button.active', {}, '开源雷达')]), runBox, comp, bar, intentBox, listBox);
    if (!head.querySelector('.sub')) head.append(h('span.sub'));
    setTimeout(() => comp.querySelector('textarea').dispatchEvent(new Event('input')), 60);   // 挂载后按实际宽度重算高度
    drawRun(status0);
    drawBar();
    load();
  },
};
