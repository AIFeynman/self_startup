// 信息推荐：按热度/新鲜度/兴趣/反馈排序的 AI 信息流；只展示标题 + 简介 + 链接 + 推荐理由。
// 页面：今日精选（前 5 条，编号行）+ 分类 pill + 紧凑列表（无限加载）+ 一个多模式输入框（筛选 / 加兴趣 / 问 Agent）。
// 键盘：j/k 移动选中，l 赞，s 收藏，o 打开，d 深读，x 隐藏。
import { toMs } from '../api.js';

const TABS = [['', '全部'], ['paper', '论文'], ['blog', '博客'], ['podcast', '播客'], ['product', '产品'], ['repo', '项目'], ['discussion', '讨论'], ['x_article', 'X 长文'], ['saved', '已收藏']];
const TYPE_NAME = { paper: '论文', blog: '博客', podcast: '播客', product: '产品', repo: '项目', discussion: '讨论' };
const PAGE = 40;
const TOP_N = 5;
const DAYS = [['0', '不限时间'], ['1', '24 小时内'], ['3', '3 天内'], ['7', '7 天内'], ['30', '30 天内']];
const SORTS = [['score', '综合排序'], ['new', '最新发布'], ['hot', '最热（同源比）']];
const st = { tab: '', q: '', mode: 'filter', days: '0', sort: 'score' };

const CSS = `
.fd-refresh { position: relative; }
.fd-pop { display: none; position: absolute; right: 0; top: calc(100% + 8px); z-index: 20; width: 300px; padding: 12px 14px;
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); font-size: 12px; }
.fd-refresh:hover .fd-pop, .fd-refresh:focus-within .fd-pop { display: block; }
.fd-pop h5 { margin: 0 0 6px; font: 600 12px var(--font); color: var(--muted); }
.fd-pop .fd-src { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
.fd-pop .fd-src .err { color: var(--err); }
.fd-pop .fd-src .ok { color: var(--ok); }
.fd-top { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 6px; }
.fd-row { display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; gap: 6px 14px; align-items: center; padding: 14px 16px 14px 10px;
  border-radius: 11px; position: relative; border: 1px solid transparent; }
.fd-top .fd-row + .fd-row::before { content: ''; position: absolute; left: 16px; right: 16px; top: -1px; height: 1px; background: var(--line); }
.fd-row.first { background: var(--focus); border-color: var(--accent-soft); }
.fd-row.first::after { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 3px; background: var(--accent); }
.fd-row.first + .fd-row::before { display: none; }
.fd-n { font: 400 34px/1 var(--serif); color: var(--muted); text-align: center; align-self: start; padding-top: 4px; font-variant-numeric: lining-nums; }
.fd-row.first .fd-n { color: var(--accent); }
.fd-t { font: 700 17px/1.4 var(--serif); color: var(--text); }
.fd-t:hover { color: var(--accent); text-decoration: none; }
.fd-best { display: inline-block; margin-left: 8px; padding: 0 8px; border-radius: 6px; background: var(--accent-soft); color: var(--accent);
  font: 600 12px/20px var(--font); vertical-align: 2px; }
.fd-new { display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 6px; background: var(--ok-soft); color: var(--ok);
  font: 600 11.5px/18px var(--font); vertical-align: 2px; }
.fd-old { display: inline-block; margin-left: 6px; color: var(--muted); font: 400 11.5px/18px var(--font); vertical-align: 2px; white-space: nowrap; }
.fd-sum { color: var(--text); opacity: .82; font-size: 13.5px; margin-top: 3px; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.fd-gist { color: var(--text); font-size: 14.5px; font-weight: 500; line-height: 1.5; margin-top: 4px; }
.fd-gist + .fd-sum { opacity: .6; font-size: 12.5px; }
.fd-why { color: var(--muted); font-size: 12.5px; margin-top: 2px; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.fd-why b { font-weight: 500; color: var(--muted); margin-right: 4px; }
.fd-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.fd-chip { display: inline-flex; align-items: center; gap: 4px; padding: 0 9px; border: 1px solid var(--line-2); border-radius: 7px;
  font-size: 12px; line-height: 21px; color: var(--muted); background: var(--panel); white-space: nowrap; }
.fd-chip svg { width: 13px; height: 13px; }
.fd-chip.type { background: var(--bg-2); border-color: transparent; }
a.fd-chip:hover { color: var(--accent); border-color: var(--accent); text-decoration: none; }
.fd-acts { display: flex; gap: 6px; align-items: center; }
.fd-acts button { padding: 5px 12px; font-size: 13px; }
.fd-acts button.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.fd-acts .fd-deep { border-color: var(--accent); color: var(--accent); background: transparent; padding: 5px 16px; }
.fd-acts .fd-deep:hover { background: var(--accent-soft); }
.fd-acts .fd-more { opacity: 0; transition: opacity .12s; }
.fd-row:hover .fd-more, .fd-item:hover .fd-more, .fd-sel .fd-more { opacity: 1; }
.fd-sel { box-shadow: 0 0 0 2px var(--accent-ring); border-color: var(--accent) !important; }
.fd-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 26px 0 10px; }
.fd-bar .tabs { margin: 0; flex: 1; }
.fd-kbd { font-size: 12px; color: var(--muted); white-space: nowrap; }
.fd-opts { display: flex; gap: 6px; margin-left: auto; }
@media (max-width: 1500px) { .fd-bar .fd-kbd { display: none; } }   /* 窄屏下快捷键提示让位给分类和筛选，避免分类折行 */
.fd-chip.art { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.fd-opts select { width: auto; font-size: 12px; padding: 4px 8px; border-radius: 8px; }
.fd-opts select.on { border-color: var(--accent); color: var(--accent); }
.fd-kbd kbd { margin: 0 1px; }
.fd-list { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 4px 6px; }
.fd-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 10px 10px; border-radius: 9px; border: 1px solid transparent; }
.fd-list .fd-item + .fd-item { border-top-color: var(--line); border-radius: 0; }
.fd-list .fd-item.fd-sel { border-radius: 9px; }
.fd-item .fd-t { font: 600 14.5px/1.45 var(--font); }
.fd-item .fd-line { display: flex; gap: 8px; align-items: center; min-width: 0; margin-top: 2px; font-size: 12px; color: var(--muted); }
.fd-verdict { font-size: 13px; margin-top: 4px; display: flex; gap: 6px; align-items: baseline; }
.fd-verdict b { color: var(--accent); font-weight: 600; white-space: nowrap; }
.fd-verdict.edit { align-items: center; }
.fd-verdict.edit input { flex: 1; min-width: 0; }
.fd-item .fd-line .fd-why { margin: 0; flex: 1; min-width: 0; font-size: 12px; }
.fd-item .fd-acts button { padding: 3px 9px; font-size: 12px; }
.fd-item .fd-acts .fd-deep { padding: 3px 12px; }
.fd-ints { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: -4px 0 10px; font-size: 12px; color: var(--muted); }
.fd-int { display: inline-flex; align-items: center; gap: 2px; padding: 1px 4px 1px 10px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 12px; }
.fd-int button { border: none; background: none; padding: 1px 3px; color: inherit; border-radius: 50%; }
.fd-int button:hover { background: rgba(0,0,0,.06); }
.fd-int button svg { width: 12px; height: 12px; }
.fd-sentinel { text-align: center; padding: 14px 0 4px; }
.fd-hidden { display: none !important; }
@media (max-width: 900px) {
  .fd-row { grid-template-columns: 44px minmax(0, 1fr); } .fd-row .fd-acts { grid-column: 2; }
  .fd-n { font-size: 26px; } .fd-item { grid-template-columns: 1fr; } .fd-acts .fd-more { opacity: 1; }
}
`;

const fmtDate = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || '');
  return m ? `${+m[2]}月${+m[3]}日` : '';
};
const fmtTime = (s) => (s ? s.replace('T', ' ').slice(5, 16) : '');
const ago = (s) => {
  if (!s) return '';
  const t = toMs(s);   // 发布时间带时区；平台自己的时间（刷新完成等）不带，按平台时区
  if (Number.isNaN(t)) return fmtTime(s);
  const m = Math.round((Date.now() - t) / 60000);
  return m < 1 ? '刚刚' : m < 60 ? `${m} 分钟前` : m < 1440 ? `${Math.round(m / 60)} 小时前` : fmtTime(s);
};
const norm = (s) => String(s || '').toLowerCase();

export default {
  async render(el, ctx) {
    const { api, h, toast, ui, ask } = ctx;
    const [settings, status0] = await Promise.all([api.get('/api/settings'), api.get('/api/feed/status')]);
    let interests = [...(settings.feed?.interests || [])];
    let status = status0;
    let entries = []; // [{x, el, kind:'top'|'list', i}]
    let sel = -1;
    let listOffset = 0, listTotal = 0, loading = false, loadSeq = 0;

    // ---------- 页头 ----------
    const subEl = h('div.sub');
    const pop = h('div.fd-pop');
    const refreshBtn = h('button.outline', { onclick: doRefresh }, [ui.icon('refresh'), h('span', {}, '刷新')]);
    const head = ui.pageHead('今天值得看', '', [h('div.fd-refresh', {}, [refreshBtn, pop])]);
    head.querySelector('.titles').append(subEl);

    // ---------- 输入框 ----------
    const MODES = [
      { id: 'filter', label: '筛选', placeholder: '输入即筛选标题 / 简介 / 来源…', hint: '边输边筛 · Esc 清空' },
      { id: 'interest', label: '加兴趣', placeholder: '输入兴趣词，回车加入（逗号分隔可一次加多个）', hint: '兴趣词影响排序' },
      { id: 'ask', label: '问 Agent', placeholder: '比如：最近有什么 agent 评测相关的新论文？', hint: '发给信息推荐 Agent' },
    ];
    const comp = ui.composer({
      modes: MODES, mode: st.mode, placeholder: MODES.find((m) => m.id === st.mode).placeholder,
      hint: MODES.find((m) => m.id === st.mode).hint, value: st.mode === 'filter' ? st.q : '',
      onSubmit: async (t, mode) => {
        if (mode === 'ask') { ask(t); return; }
        if (mode === 'interest') { await addInterests(t); return; }
        setFilter(t, true); return false; // 筛选：保留文字
      },
    });
    const ta = comp.querySelector('textarea');
    comp.querySelector('.modes').addEventListener('click', () => setTimeout(() => {
      if (comp.mode === st.mode) return;
      const prev = st.mode; st.mode = comp.mode;
      const m = MODES.find((x) => x.id === st.mode);
      comp.setHint(m.hint);
      if (prev === 'filter' && st.q) { ta.value = ''; setFilter(''); }
      if (st.mode === 'filter' && ta.value.trim()) setFilter(ta.value);
    }));
    ta.addEventListener('input', () => { if (st.mode === 'filter') setFilter(ta.value); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { ta.value = ''; ta.dispatchEvent(new Event('input')); ta.blur(); }
      if (e.key === 'ArrowDown' && st.mode === 'filter') { e.preventDefault(); ta.blur(); move(1); }
    });

    const intsEl = h('div.fd-ints');
    const quick = ui.chips([
      { label: '今天最值得看的 5 条', icon: 'spark', onClick: () => ask('今天最值得看的 5 条') },
      { label: '有什么新论文？', icon: 'doc', onClick: () => ask('最近有什么值得看的新论文？') },
      { label: '只看 Agent 相关', icon: 'search', onClick: () => { switchMode('filter'); comp.setValue('agent'); setFilter('agent'); } },
    ], { left: true });

    // ---------- 精选 + 列表 ----------
    const topBox = h('div');
    const tabs = h('div.tabs');
    const listBox = h('div.fd-list');
    const sentinel = h('div.fd-sentinel');
    const kbd = h('span.fd-kbd', { title: 'j/k 移动 · l 赞 · s 收藏 · o 打开 · d 深读 · / 输入' }, [h('kbd', {}, 'j'), h('kbd', {}, 'k'), ' 移动 · ', h('kbd', {}, 'l'), ' 赞 · ',
      h('kbd', {}, 's'), ' 收藏 · ', h('kbd', {}, 'o'), ' 打开 · ', h('kbd', {}, 'd'), ' 深读 · ', h('kbd', {}, '/'), ' 输入']);

    // 时间筛选 + 排序：只作用于下面的列表（今日精选固定按综合分）
    const optSel = (opts, key, title) => {
      const s = h('select', { title, onchange: (e) => { st[key] = e.target.value; s.classList.toggle('on', st[key] !== opts[0][0]); loadList(); } },
        opts.map(([v, name]) => h('option', { value: v, selected: st[key] === v }, name)));
      return s;
    };
    const opts = h('div.fd-opts', {}, [optSel(DAYS, 'days', '按发布时间筛选'), optSel(SORTS, 'sort', '列表排序方式')]);

    el.append(h('style', {}, CSS), head, comp, intsEl, quick,
      ui.section('今日精选', '按热度 · 新鲜度 · 兴趣词 · 你的反馈 · 每个来源最多 1 条'), topBox,
      h('div.fd-bar', {}, [tabs, opts, kbd]), listBox, sentinel);

    // ---------- 状态 / 刷新 ----------
    function renderStatus() {
      const s = status;
      const last = s.running ? `刷新中（${fmtTime(s.started_at).slice(6)} 开始）…` : `上次刷新 ${ago(s.finished_at || s.last_fetched) || '—'}`;
      subEl.textContent = `从 ${s.total} 条里按你的兴趣挑出 · ${last}`;
      refreshBtn.disabled = !!s.running;
      refreshBtn.lastChild.textContent = s.running ? '刷新中…' : '刷新';
      const res = s.results || {};
      const srcs = Object.keys({ ...s.by_source, ...res }).sort((a, b) => (s.by_source?.[b] || 0) - (s.by_source?.[a] || 0));
      pop.replaceChildren(
        h('h5', {}, Object.keys(res).length ? `本次刷新 · ${fmtTime(s.finished_at) || '进行中'}` : '各来源库存（本次启动后未刷新）'),
        ...srcs.map((k) => {
          const r = res[k];
          const errs = r?.errors || [];
          return h('div.fd-src', { title: errs.join('\n') }, [h('span', {}, k),
            h('span', {}, [r ? h('span.' + (errs.length ? 'err' : 'ok'), {}, `+${r.count}${errs.length ? ` ⚠ ${errs.length}` : ''}  `) : null,
              h('span.muted', {}, `库内 ${s.by_source?.[k] || 0}`),
              s.sources?.[k]?.stale ? h('span.err', { title: `最新条目 ${s.sources[k].latest || '无日期'}` }, ' 停更') : null])]);
        }),
        h('div.muted', { style: { marginTop: '6px' } }, `反馈：👍 ${s.feedback?.likes || 0} · ★ ${s.feedback?.saved || 0} · 隐藏 ${s.feedback?.hidden || 0} · 打开 ${s.feedback?.clicks || 0} · 进深读 ${s.feedback?.deep_reads || 0}`));
    }
    async function doRefresh() {
      status = await api.post('/api/feed/refresh', {});
      renderStatus();
      while (status.running) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!el.isConnected) return;
        status = await api.get('/api/feed/status');
        renderStatus();
      }
      toast('刷新完成'); reloadAll();
    }

    // ---------- 兴趣词 ----------
    function renderInterests() {
      intsEl.replaceChildren(h('span', {}, '兴趣词'),
        ...interests.map((w) => h('span.fd-int', {}, [w, h('button', { title: '移除', onclick: () => saveInterests(interests.filter((x) => x !== w), `已移除「${w}」`) }, ui.icon('x'))])),
        h('button.ghost.sm', { onclick: () => { switchMode('interest'); comp.focus(); } }, [ui.icon('plus'), '加']));
    }
    async function saveInterests(arr, msg) {
      interests = arr;
      renderInterests();
      await api.put('/api/settings', { feed: { interests: arr } });
      toast(msg); reloadAll();
    }
    async function addInterests(text) {
      const add = text.split(/[,，、\n]/).map((x) => x.trim()).filter((x) => x && !interests.some((y) => norm(y) === norm(x)));
      if (!add.length) { toast('已在兴趣词里'); return; }
      await saveInterests([...interests, ...add], `已加入：${add.join('、')}`);
    }
    function switchMode(id) {
      const b = [...comp.querySelectorAll('.modes button')][MODES.findIndex((m) => m.id === id)];
      if (b && comp.mode !== id) b.click();
    }

    // ---------- 行渲染 ----------
    const metaChips = (x) => [
      TYPE_NAME[x.type] && h('span.fd-chip.type', {}, TYPE_NAME[x.type]),
      h('span.fd-chip', {}, [ui.icon('doc'), x.source_label + (fmtDate(x.date) ? ' · ' + fmtDate(x.date) : '')]),
      (x.extra?.feed || x.extra?.subreddit) && h('span.fd-chip', {}, x.extra.feed || `r/${x.extra.subreddit}`),
      x.extra?.x_article && h('span.fd-chip.art', { title: '长文正文未抓取，点标题去 X 上看' }, x.extra.x_article === 'own' ? 'X 长文' : '引用 X 长文'),
      x.extra?.origin === 'learn_evolve' && h('span.fd-chip', {}, 'learn_evolve'),
      x.extra?.hn_url && h('a.fd-chip', { href: x.extra.hn_url, target: '_blank', rel: 'noopener' }, [ui.icon('chat'), `HN 讨论${x.extra.comments ? ' ' + x.extra.comments : ''}`]),
      ...Object.entries((x.also || []).reduce((m, a) => { const k = a.source_label || a.source || a; m[k] = (m[k] || 0) + 1; return m; }, {}))
        .slice(0, 2).map(([k, n]) => h('span.fd-chip', {}, `也见 ${k}${n > 1 ? '×' + n : ''}`)),
    ];
    const actions = (entry) => {
      const { x } = entry;
      const f = x.feedback || {};
      return h('div.fd-acts', {}, [
        h('button.icon.fd-more', { title: '踩（不想看到类似的）', onclick: () => fb(entry, { vote: f.vote < 0 ? 0 : -1 }) }, f.vote < 0 ? '👎' : h('span', { style: { opacity: 0.55 } }, '👎')),
        h('button.icon.fd-more', { title: f.hidden ? '取消隐藏 (x)' : '隐藏 (x)', onclick: () => fb(entry, { hidden: !f.hidden }) }, ui.icon(f.hidden ? 'refresh' : 'x')),
        h('button' + (f.vote > 0 ? '.on' : ''), { title: '赞 (l)', onclick: () => fb(entry, { vote: f.vote > 0 ? 0 : 1 }) }, '👍'),
        h('button' + (f.saved ? '.on' : ''), { title: '收藏 (s)', onclick: () => fb(entry, { saved: !f.saved }) }, f.saved ? '★' : '☆'),
        h('button' + (f.verdict ? '.on' : ''), { title: '读完写一句话判断（进知识库的论文笔记）', onclick: () => { entry.judging = !entry.judging; mount(entry); entry.el.querySelector('.fd-verdict input')?.focus(); } }, ui.icon('edit')),
        h('button.fd-deep', { title: '深读 (d)', onclick: () => deep(x) }, ['深读', ui.icon('arrow')]),
      ]);
    };
    // 打开原文只做统计（推荐 → 点击 → 深读的转化），失败不打扰
    const logClick = (x) => { api.post('/api/feed/click', { id: x.id }).catch(() => {}); };
    // 新增 / 在榜天数：第一次收进来不到 24 小时标「新」，在榜 3 天以上标天数，长期霸榜的一眼能看出来
    const ageTag = (x) => x.new ? h('span.fd-new', { title: '24 小时内新收录' }, '新')
      : x.seen_days >= 3 ? h('span.fd-old', { title: '第一次收录到现在的天数' }, `在榜 ${x.seen_days} 天`) : null;
    const titleLink = (x) => h('a.fd-t', { href: x.url, target: '_blank', rel: 'noopener', onclick: () => logClick(x), onauxclick: () => logClick(x) }, x.title);
    // 一句话判断：已写的直接显示，点「编辑」展开输入框；论文每天写 1–2 篇是学习习惯之一
    const verdictBox = (entry) => {
      const { x } = entry;
      const v = x.feedback?.verdict || '';
      if (!entry.judging) return v ? h('div.fd-verdict', {}, [h('b', {}, '我的判断'), v]) : null;
      const inp = h('input', { value: v, placeholder: '一句话判断：增量在哪、证据可不可信、值不值得跟（Enter 保存，清空 = 删除）',
        onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); save(); } if (e.key === 'Escape') { entry.judging = false; mount(entry); } } });
      const save = async () => {
        try {
          const r = await api.post('/api/feed/verdict', { id: x.id, text: inp.value });
          for (const e of entries) if (e.x.id === x.id) { e.x.feedback = { ...(e.x.feedback || {}), verdict: r.verdict, verdict_at: r.verdict_at }; e.judging = false; mount(e); }
          toast(r.verdict ? '已存进今天的论文笔记' : '已删除判断');
        } catch (e) { toast('保存失败：' + e.message, true); }
      };
      return h('div.fd-verdict.edit', {}, [inp, h('button.sm.primary', { onclick: save }, '保存')]);
    };
    const why = (x) => (x.why ? h('div.fd-why', { title: x.why }, [h('b', {}, '推荐理由'), x.why]) : null);

    function build(entry) {
      const { x, kind, i } = entry;
      let node;
      if (kind === 'top') {
        node = h('div.fd-row' + (i === 0 ? '.first' : ''), {}, [
          h('div.fd-n', {}, String(i + 1).padStart(2, '0')),
          h('div', { style: { minWidth: 0 } }, [
            h('div', {}, [titleLink(x), ageTag(x), i === 0 ? h('span.fd-best', {}, '最推荐') : null]),
            x.gist ? h('div.fd-gist', { title: '模型根据标题和简介生成的一句话概括' }, x.gist) : null,
            x.summary ? h('div.fd-sum', { title: x.summary }, x.summary) : null,
            why(x),
            verdictBox(entry),
            h('div.fd-meta', {}, metaChips(x)),
          ]),
          actions(entry),
        ]);
      } else {
        node = h('div.fd-item', {}, [
          h('div', { style: { minWidth: 0 } }, [
            titleLink(x), ageTag(x),
            x.gist ? h('div.fd-gist', { title: '模型根据标题和简介生成的一句话概括' }, x.gist) : null,
            x.summary ? h('div.fd-sum', { title: x.summary, style: { fontSize: '13px' } }, x.summary) : null,
            h('div.fd-line', {}, [TYPE_NAME[x.type] && h('span.fd-chip.type', {}, TYPE_NAME[x.type]),
              x.extra?.x_article && h('span.fd-chip.art', {}, x.extra.x_article === 'own' ? 'X 长文' : '引用 X 长文'),
              h('span', { style: { whiteSpace: 'nowrap' } }, x.source_label + (fmtDate(x.date) ? ' · ' + fmtDate(x.date) : '')),
              x.extra?.hn_url && h('a.muted', { href: x.extra.hn_url, target: '_blank', rel: 'noopener', style: { whiteSpace: 'nowrap' } }, 'HN 讨论'),
              x.why ? h('span.fd-why', { title: x.why }, '· ' + x.why) : null]),
            verdictBox(entry),
          ]),
          actions(entry),
        ]);
      }
      node.addEventListener('mousedown', (e) => { if (!e.target.closest('button, a')) select(entries.indexOf(entry), false); });
      node._hay = norm([x.title, x.gist, x.summary, x.source_label, x.why, x.extra?.feed, TYPE_NAME[x.type]].join(' '));
      if (st.q && !matches(node)) node.classList.add('fd-hidden');
      return node;
    }
    function mount(entry) {
      const old = entry.el;
      entry.el = build(entry);
      if (old) old.replaceWith(entry.el);
      if (entries[sel] === entry) entry.el.classList.add('fd-sel');
      return entry.el;
    }

    async function fb(entry, patch) {
      try {
        const r = await api.post('/api/feed/feedback', { id: entry.x.id, ...patch });
        entry.x.feedback = { ...(entry.x.feedback || {}), ...r };
        // 同一条可能同时出现在精选和列表里
        for (const e of entries) if (e !== entry && e.x.id === entry.x.id) { e.x.feedback = { ...(e.x.feedback || {}), ...r }; mount(e); }
        if (r.hidden && st.tab !== 'saved') {
          const idx = entries.indexOf(entry);
          entry.el.remove(); entries.splice(idx, 1);
          if (sel >= entries.length) sel = entries.length - 1;
          if (entries[sel]) entries[sel].el.classList.add('fd-sel');
          toast('已隐藏，可在「已收藏」或 Agent 里恢复');
          return;
        }
        mount(entry);
      } catch (e) { toast('操作失败：' + e.message, true); }
    }
    // 深读 = 深度学习里的一个条目：Agent 写成本地文档（可划线评论、追问），追问对话绑在条目上，关掉再开能续上；同一链接已读过就直接打开
    const deep = async (x) => {
      try {
        const it = await api.post('/api/learn/items', { url: x.url, reuse: true });
        location.hash = `#learn/item/${it.id}`;
      } catch (e) { toast('开始深读失败：' + e.message, true); }
    };

    // ---------- 选择与键盘 ----------
    const visible = () => entries.map((e, i) => [e, i]).filter(([e]) => e.el.isConnected && !e.el.classList.contains('fd-hidden')).map(([, i]) => i);
    function select(i, scroll = true) {
      entries[sel]?.el.classList.remove('fd-sel');
      sel = i;
      const e = entries[sel];
      if (!e) return;
      e.el.classList.add('fd-sel');
      if (scroll) e.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    function move(d) {
      const vis = visible();
      if (!vis.length) return;
      const pos = vis.indexOf(sel);
      const next = pos < 0 ? (d > 0 ? vis[0] : vis[vis.length - 1]) : vis[Math.max(0, Math.min(vis.length - 1, pos + d))];
      select(next);
      if (vis.indexOf(next) >= vis.length - 3) loadMore();
    }
    const onKey = (e) => {
      if (!el.isConnected) return document.removeEventListener('keydown', onKey);
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = document.activeElement?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement?.isContentEditable) return;
      const cur = entries[sel];
      const f = cur?.x.feedback || {};
      const act = {
        j: () => move(1), k: () => move(-1),
        l: () => cur && fb(cur, { vote: f.vote > 0 ? 0 : 1 }),
        s: () => cur && fb(cur, { saved: !f.saved }),
        o: () => { if (cur) { logClick(cur.x); window.open(cur.x.url, '_blank', 'noopener'); } },
        d: () => cur && deep(cur.x),
        x: () => cur && fb(cur, { hidden: !f.hidden }),
      }[e.key];
      if (act) { e.preventDefault(); act(); }
    };
    document.addEventListener('keydown', onKey);

    // ---------- 筛选 ----------
    const matches = (node) => {
      const words = norm(st.q).split(/\s+/).filter(Boolean);
      return words.every((w) => node._hay.includes(w));
    };
    let qTimer;
    function setFilter(q, now = false) {
      st.q = q.trim();
      // 即时：只在已加载的行上隐藏/显示
      for (const e of entries) e.el.classList.toggle('fd-hidden', !!st.q && !matches(e.el));
      if (entries[sel]?.el.classList.contains('fd-hidden')) select(-1);
      // 稍后：去服务端拿全量匹配
      clearTimeout(qTimer);
      qTimer = setTimeout(loadList, now ? 0 : 280);
    }

    // ---------- 数据 ----------
    function renderTabs() {
      tabs.replaceChildren(...TABS.map(([id, name]) => h('button' + (st.tab === id ? '.active' : ''), {
        onclick: () => { if (st.tab === id) return; st.tab = id; renderTabs(); loadList(); },
      }, name)));
    }
    async function loadTop() {
      const r = await api.get(`/api/feed/items?limit=${TOP_N}`);
      for (const e of entries.filter((e) => e.kind === 'top')) e.el.remove();
      entries = entries.filter((e) => e.kind !== 'top');
      const tops = r.items.map((x, i) => ({ x, kind: 'top', i }));
      entries = [...tops, ...entries];
      topBox.replaceChildren(tops.length ? h('div.fd-top', {}, tops.map(mount)) : ui.empty('还没有内容', '点右上角「刷新」抓取信息源'));
      if (st.q) for (const e of tops) e.el.classList.toggle('fd-hidden', !matches(e.el));
    }
    // 「全部」、综合排序、不限时间且无筛选时，列表从第 6 条开始，避免与精选重复
    const baseOffset = () => (!st.tab && !st.q && st.days === '0' && st.sort === 'score' ? TOP_N : 0);
    function params(offset) {
      const p = new URLSearchParams({ limit: PAGE, offset, q: st.q, days: st.days, sort: st.sort });
      if (st.tab === 'saved') p.set('saved', 'true'); else if (st.tab) p.set('type', st.tab);
      return p;
    }
    async function loadList() {
      const seq = ++loadSeq;
      const off = baseOffset();
      const r = await api.get('/api/feed/items?' + params(off));
      if (seq !== loadSeq) return;
      const selId = entries[sel]?.kind === 'list' ? entries[sel].x.id : null;
      entries = entries.filter((e) => e.kind !== 'list');
      if (sel >= entries.length) sel = -1;
      listOffset = off + r.items.length; listTotal = r.total;
      const rows = r.items.map((x) => ({ x, kind: 'list' }));
      entries.push(...rows);
      listBox.replaceChildren(...(rows.length ? rows.map(mount)
        : [ui.empty(st.q ? `没有匹配「${st.q}」的内容` : st.tab === 'saved' ? '还没有收藏' : st.days !== '0' ? '这段时间内没有内容' : '暂无内容', st.q ? '换个词，或切到「问 Agent」' : st.tab === 'saved' ? '按 ☆ 或 s 收藏' : '点右上角「刷新」抓取')]));
      if (selId) { const i = entries.findIndex((e) => e.kind === 'list' && e.x.id === selId); if (i >= 0) select(i, false); }
      renderSentinel();
    }
    async function loadMore() {
      if (loading || listOffset >= listTotal) return;
      loading = true; renderSentinel();
      const seq = loadSeq;
      try {
        const r = await api.get('/api/feed/items?' + params(listOffset));
        if (seq !== loadSeq) return;
        listOffset += r.items.length; listTotal = r.total;
        const rows = r.items.map((x) => ({ x, kind: 'list' }));
        entries.push(...rows);
        listBox.append(...rows.map(mount));
      } finally { loading = false; renderSentinel(); }
    }
    function renderSentinel() {
      const left = listTotal - listOffset;
      sentinel.replaceChildren(left > 0
        ? h('button.ghost', { onclick: loadMore, disabled: loading }, loading ? '加载中…' : `加载更多 · 还有 ${left} 条`)
        : (listTotal > PAGE ? h('span.muted', {}, `已全部加载（${listTotal} 条）`) : ''));
    }
    const io = new IntersectionObserver((es) => {
      if (!el.isConnected) return io.disconnect();
      if (es.some((e) => e.isIntersecting)) loadMore();
    }, { root: document.getElementById('page'), rootMargin: '300px' });
    io.observe(sentinel);

    async function reloadAll() { await Promise.all([loadTop(), loadList()]); }

    const onAgent = () => {
      if (!el.isConnected) return document.removeEventListener('agent-done', onAgent);
      api.get('/api/settings').then((s) => { interests = [...(s.feed?.interests || [])]; renderInterests(); });
      api.get('/api/feed/status').then((s) => { status = s; renderStatus(); });
      reloadAll();
    };
    document.addEventListener('agent-done', onAgent);

    renderStatus();
    renderInterests();
    renderTabs();
    await reloadAll();
    if (status.running) doRefresh();
  },
};
