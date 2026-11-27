// 知识库的「GitHub 项目」标签：stars ≥ 1000 的 GitHub 项目按功能检索（设计稿 docs/designs/2026-11-01-oss-radar-design.md，后端 app/modules/_oss_radar.py）。
// 由 kb.js 在 #kb/repo 路由下调用 repoTab(body, ctx, 查询)；顶部主搜索框的输入走返回的 search。
// 有输入：改写 + 多路召回 + 精排，可切「相关性 | star」；没输入：按领域浏览（star 倒序）。
// 路由：#kb/repo/<查询>（信息推荐卡片的「同类项目」跳这里）。
const ADDED = [['1', '今天入库'], ['3', '近 3 天入库'], ['7', '近 7 天入库'], ['30', '近 30 天入库'], ['0', '全部时间']];
const ACTIVE = [['0', '不限活跃'], ['30', '30 天内有更新'], ['180', '半年内有更新'], ['365', '一年内有更新']];
const AI_NAME = { core: 'AI 本身', for_ai: '给 AI 用', ai_powered: 'AI 应用', none: '' };
const LEARN = [['survey', '综述 / 论文'], ['course', '教程 / 课程'], ['scratch', '代码学习 / 从零实现'], ['book', '书籍 / 讲义'], ['road', '学习路线 / 面试'], ['list', '资源清单']];
const LNAME = Object.fromEntries(LEARN);
const st = { q: '', by: 'rel', kind: '', domain: '', lang: '', active: '0', offset: 0, added: '30', order: 'time', learn: '' };
const saved = { added: '30', order: 'time' };
let lc = null;
const fmtStars = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n));

const CSS = `
.os-bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 4px 0 14px; }
.os-bar select { width: auto; font-size: 12.5px; padding: 3px 6px; border-radius: 8px; max-width: 130px; }
.os-seg { display: inline-flex; border: 1px solid var(--line-2); border-radius: 8px; overflow: hidden; }
.os-seg button { border: none; border-radius: 0; padding: 3px 10px; font-size: 12.5px; background: var(--panel); color: var(--muted); }
.os-seg button.on { background: var(--accent-soft); color: var(--accent); }
.os-item .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
.os-item .why { color: var(--accent); font-size: 13px; margin-top: 4px; }
.os-item .acts { display: flex; gap: 4px; margin-left: auto; }
.os-item .acts button { padding: 2px 10px; font-size: 12px; }
.os-intent { font-size: 12.5px; color: var(--muted); margin: -6px 0 10px; }
.os-mode { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 0 0 10px; }
.os-mode .os-seg button { font-size: 13.5px; padding: 4px 14px; }
.os-lt { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 10px; }
.os-lt button { border: 1px solid var(--line-2); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 12px; font-size: 13px; }
.os-lt button.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.os-lt small { color: var(--muted); margin-left: 4px; font-variant-numeric: tabular-nums; }
.os-item .lt { background: var(--accent-soft); color: var(--accent); }
`;

export async function repoTab(body, ctx, q0 = '') {
  const { api, h, toast, ui } = ctx;
  const [tax, status0] = await Promise.all([api.get('/api/intel/oss/taxonomy'), api.get('/api/intel/oss/status')]);
  const dname = {};
  tax.domains.forEach((d) => d.children.forEach((c) => { dname[c.code] = c.name; }));
  const kname = Object.fromEntries(tax.kinds.map((k) => [k.code, k.name]));
  st.q = q0;
  const setHash = (q) => history.replaceState(null, '', q ? '#kb/repo/' + encodeURIComponent(q) : '#kb/repo');   // 改 hash 会整页重绘，这里只记地址

  const bar = h('div.os-bar');
  const modeBox = h('div');
  const intentBox = h('div');
  const listBox = h('div');

  const sub = (s) => `${s.repos} 个仓库 · 已标注 ${s.labeled} · 待标注 ${s.todo} · 分类体系 ${s.tax_ver}`;

  // ---------- 检索 / 浏览 ----------
  const sel = (key, opts, onchange) => h('select', { onchange: (e) => { st[key] = e.target.value; st.offset = 0; onchange(); } },
    opts.map(([v, n]) => h('option', { value: v, selected: st[key] === v }, n)));
  const setMode = (learn) => {
    if (!!learn === !!st.learn) { st.learn = learn; return; }
    const keep = { added: st.added, order: st.order };
    Object.assign(st, saved, { learn, domain: '', kind: '' });
    Object.assign(saved, keep);
  };
  const drawMode = () => {
    const cnt = lc ? Object.values(lc.counts).reduce((a, b) => a + b, 0) : 0;
    const pick = (v) => { setMode(v); drawMode(); drawBar(); load(); };
    modeBox.replaceChildren(
      h('div.os-mode', {}, [h('div.os-seg', {}, [['', '全部项目'], ['all', '学习类']].map(([v, n]) => h('button' + (!!st.learn === !!v ? '.on' : ''), { onclick: () => pick(v) }, n))),
        st.learn ? h('span.muted', {}, '综述、教程、从零实现、书籍、学习路线等，适合拿来学的项目') : null]),
      st.learn ? h('div.os-lt', {}, [['all', '全部'], ...LEARN].map(([v, n]) => h('button' + (st.learn === v ? '.on' : ''), { onclick: () => pick(v) },
        [n, lc ? h('small', {}, String(v === 'all' ? cnt : lc.counts[v] || 0)) : null]))) : '');
  };
  const drawBar = () => {
    const seg = (id, name) => h('button' + (st.by === id ? '.on' : ''), { onclick: () => { st.by = id; drawBar(); load(); } }, name);
    const dc = st.learn ? lc?.doms || {} : status0.by_domain;
    const domOpts = [['', '全部领域'], ...tax.domains.flatMap((d) => d.children.filter((c) => !st.learn || dc[c.code] || st.domain === c.code).map((c) => [c.code, `${d.name} · ${c.name}${dc[c.code] ? ` (${dc[c.code]})` : ''}`]))];
    bar.replaceChildren(...[
      st.q ? h('div.os-seg', {}, [seg('rel', '相关性'), seg('stars', 'star')])
        : h('div.os-seg', {}, [['time', '按入库时间'], ['stars', '按 star']].map(([id, name]) => h('button' + (st.order === id ? '.on' : ''), { onclick: () => { st.order = id; drawBar(); load(); } }, name))),
      st.q ? null : sel('added', ADDED, load),
      sel('domain', domOpts, load), st.learn ? null : sel('kind', [['', '全部类型'], ...tax.kinds.map((k) => [k.code, k.name])], load),
      sel('lang', [['', '全部语言'], ...['Python', 'TypeScript', 'JavaScript', 'Go', 'Rust', 'Java', 'C++', 'C', 'Swift', 'Kotlin', 'C#', 'Shell', 'Jupyter Notebook'].map((l) => [l, l])], load),
      sel('active', ACTIVE, load),
      st.q ? h('button.ghost', { onclick: () => { st.q = ''; setHash(''); drawBar(); load(); } }, ['清除「', st.q, '」']) : null].filter(Boolean));
  };
  const card = (x) => h('div.item.os-item', {}, [
    h('div.row', {}, [
      h('a.item-title', { href: `https://github.com/${x.name}`, target: '_blank', rel: 'noopener' }, x.name),
      h('span.tag.line', {}, ['★ ', fmtStars(x.stars)]), x.lang ? h('span.muted', {}, x.lang) : null,
      x.lt ? h('span.tag.lt', { title: '学习类细分' }, LNAME[x.lt]) : h('span.tag.gray', {}, kname[x.k] || x.k), h('span.tag', { title: '点击只看这个领域', style: { cursor: 'pointer' }, onclick: () => { st.domain = x.d; st.offset = 0; drawBar(); load(); } }, dname[x.d] || x.d),
      AI_NAME[x.ai] ? h('span.tag.ok', {}, AI_NAME[x.ai]) : null,
      x.archived ? h('span.tag.warn', {}, '已归档') : x.pushed ? h('span.muted', {}, '更新于 ' + x.pushed.slice(0, 10)) : null,
      x.added ? h('span.muted', {}, '入库 ' + x.added) : null,
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
  const go = (q) => { st.q = q; setHash(q); st.offset = 0; drawBar(); load(); };

  let loadSeq = 0;
  async function load(more = false) {
    const seq = ++loadSeq;
    if (!more) st.offset = 0;
    const p = new URLSearchParams({ q: st.q, by: st.by, kind: st.kind, domain: st.domain, lang: st.lang, active: st.active, added: st.added, order: st.order, offset: st.offset, k: st.q || st.learn ? 30 : 40, learn: st.learn });
    if (!more) {
      if (st.q || !listBox.querySelector('.list')) listBox.replaceChildren(h('div.muted', {}, st.q ? '检索中（改写需求 → 召回 → 精排，首次约几秒）…' : '加载中…'));
      else listBox.style.opacity = 0.5;
    }
    let r;
    try { r = await api.get('/api/intel/oss/search?' + p); } catch (e) { if (seq !== loadSeq) return; listBox.replaceChildren(ui.empty('检索失败', e.message)); return; } finally { if (seq === loadSeq) listBox.style.opacity = ''; }
    if (seq !== loadSeq) return;
    intentBox.replaceChildren(r.mode !== 'search' ? '' : r.ref ? h('div.os-intent', {}, ['直接定位：', r.ref, ...(r.errors || []).map((e) => h('div', { style: { color: 'var(--warn)' } }, e))]) : h('div.os-intent', {}, [
      r.names?.length ? `按项目名找到：${r.names.join('、')} · 其余按：` : '理解为：', (r.intent.must || []).join(' / '),
      r.intent.domains?.length ? ` · 领域 ${r.intent.domains.map((d) => dname[d] || d).join('、')}` : '',
      r.intent.not?.length ? ` · 排除 ${r.intent.not.join('、')}` : '',
      r.reranked ? '' : ' · 未精排', ...(r.errors || []).map((e) => h('div', { style: { color: 'var(--warn)' } }, e))]));
    if (r.learn_counts) {
      lc = { counts: r.learn_counts, doms: r.learn_domains };
      if (!more) { drawMode(); drawBar(); }
    }
    const items = r.results.map(card);
    if (more) { listBox.querySelector('.list')?.append(...items); } else {
      const title = (st.learn ? `学习类 · ${st.learn === 'all' ? '全部' : LNAME[st.learn]} · ` : '') + (r.mode === 'search' ? `「${st.q}」` : (st.domain ? dname[st.domain] : '全部领域') + (st.order === 'time' ? ' · 按入库时间' : ' · 按 star'));
      listBox.replaceChildren(ui.section(title, r.mode === 'search' ? `${r.results.length} 个` : `共 ${r.total} 个`),
        items.length ? h('div.card', {}, h('div.list', {}, items))
          : ui.empty(status0.labeled ? '没找到' : '库还是空的', status0.labeled ? (st.added !== '0' ? '这段时间没有新入库的项目，可以放宽入库时间' : '换个说法，或去掉筛选') : '后台还没采集和标注'));
    }
    listBox.querySelector('.os-more')?.remove();
    if (r.mode === 'browse' && st.offset + r.results.length < r.total) {
      listBox.append(h('button.ghost.os-more', { onclick: () => { st.offset += r.results.length; load(true); } }, '加载更多'));
    }
  }

  const head = h('div.muted', { style: { margin: '0 0 10px' } }, sub(status0));
  body.append(h('style', {}, CSS), head, modeBox, bar, intentBox, listBox);
  drawMode();
  drawBar();
  load();
  return { search: go };
}
