// 信息推荐：按热度/新鲜度/兴趣/反馈排序的 AI 信息流；只展示标题 + 简介 + 链接 + 推荐理由。
// 页面：今日精选（前 5 条，编号行）+ 分类 pill + 紧凑列表（无限加载）+ 一个多模式输入框（筛选 / 加兴趣 / 问 Agent）。
// 键盘：j/k 移动选中，l 赞，s 收藏，o 打开，d 深读，x 隐藏。
import { toMs } from '../api.js';

const TABS = [['', '全部'], ['paper', '论文'], ['blog', '博客'], ['podcast', '播客'], ['product', '产品'], ['repo', '项目'], ['discussion', '讨论'], ['hn', 'HN 精读'], ['video', '视频'], ['x_article', 'X 长文'], ['saved', '已收藏']];
const REFRESHABLE = ['paper', 'blog', 'podcast', 'product', 'repo', 'discussion', 'hn', 'video', 'x_article'];
const TYPE_NAME = { paper: '论文', blog: '博客', podcast: '播客', product: '产品', repo: '项目', discussion: '讨论', video: '视频' };
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const fmtDur = (s) => s ? (s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}` : `${Math.round(s / 60)} 分钟`) : '';
const PAGE = 40;
const TOP_N = 5;
const DAYS = [['0', '不限时间'], ['1', '24 小时内'], ['3', '3 天内'], ['7', '7 天内'], ['30', '30 天内']];
const SORTS = [['score', '综合排序'], ['new', '最新发布'], ['hot', '最热（同源比）']];
const st = { tab: '', q: '', mode: 'filter', days: '0', sort: 'score', hnView: 'posts' };
const HN_ITEM = (id) => `https://news.ycombinator.com/item?id=${id}`;
const SENT = { pos: ['好评', 'ok'], neg: ['差评', 'err'], mixed: ['褒贬不一', 'warn'], neutral: ['提及', 'gray'] };

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
.fd-pa { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; font-size: 13px; line-height: 1.5; margin-top: 6px; padding: 6px 10px; border-left: 2px solid var(--accent, #6b8afd); background: color-mix(in srgb, var(--text) 4%, transparent); border-radius: 4px; }
.fd-pa b { font-weight: 600; opacity: .6; white-space: nowrap; }
.fd-pa .rev { font-variant-numeric: tabular-nums; }
details.fd-pa-d { margin-top: 5px; font-size: 13px; }
details.fd-pa-d > summary { cursor: pointer; list-style: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
details.fd-pa-d > summary b { font-weight: 600; opacity: .55; margin-right: 4px; }
details.fd-pa-d > summary .sep { opacity: .35; margin: 0 8px; }
details.fd-pa-d > summary:hover { color: var(--accent); }
details.fd-pa-d[open] > summary { opacity: .6; }
details.fd-pa-d > summary::-webkit-details-marker { display: none; }
details.fd-pa-d > summary::before { content: '▸ '; }
details.fd-pa-d[open] > summary::before { content: '▾ '; }
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
.fd-tabref { white-space: nowrap; }
/* HN 精读：评论区提炼（帖子内折叠块 + 经验库） */
details.fd-hn { margin-top: 6px; font-size: 13px; border-left: 2px solid var(--warn); padding: 2px 0 2px 10px; }
details.fd-hn > summary { cursor: pointer; list-style: none; line-height: 1.5; }
details.fd-hn > summary::-webkit-details-marker { display: none; }
details.fd-hn > summary b { color: var(--warn); font-weight: 600; margin-right: 6px; white-space: nowrap; }
details.fd-hn > summary .n { color: var(--muted); font-size: 12px; margin-left: 6px; white-space: nowrap; }
details.fd-hn > summary:hover { color: var(--accent); }
.fd-hn-sec { margin-top: 8px; }
.fd-hn-sec > h6 { margin: 0 0 3px; font: 600 12px var(--font); color: var(--muted); }
.fd-hn-sec ul { margin: 0; padding-left: 0; list-style: none; }
.fd-hn-sec li { padding: 2px 0; line-height: 1.5; }
.fd-hn-sec li .k { display: inline-block; min-width: 34px; margin-right: 6px; padding: 0 5px; border-radius: 5px; background: var(--bg-2); color: var(--muted); font-size: 11.5px; text-align: center; }
.fd-hn-sec li .k.ok { background: var(--ok-soft); color: var(--ok); } .fd-hn-sec li .k.err { background: var(--err-soft); color: var(--err); }
.fd-hn-sec li .k.warn { background: var(--warn-soft); color: var(--warn); }
.fd-hn-sec .d { color: var(--muted); }
.fd-cid { font-size: 11px; color: var(--muted); margin-left: 3px; vertical-align: 1px; }
a.fd-cid:hover { color: var(--accent); }
.fd-ents { display: flex; flex-wrap: wrap; gap: 5px; }
.fd-ent { padding: 0 8px; border-radius: 6px; font-size: 12px; line-height: 21px; background: var(--bg-2); color: var(--text); cursor: default; }
.fd-ent.ok { background: var(--ok-soft); color: var(--ok); } .fd-ent.err { background: var(--err-soft); color: var(--err); } .fd-ent.warn { background: var(--warn-soft); color: var(--warn); }
.fd-hn-none { margin-top: 4px; font-size: 12px; color: var(--muted); display: flex; gap: 8px; align-items: center; }
.fd-hnbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: -2px 0 10px; font-size: 12.5px; color: var(--muted); }
.fd-seg { display: inline-flex; border: 1px solid var(--line-2); border-radius: 8px; overflow: hidden; }
.fd-seg button { border: none; border-radius: 0; padding: 4px 14px; white-space: nowrap; font-size: 12.5px; background: var(--panel); color: var(--muted); }
.fd-seg button.on { background: var(--accent-soft); color: var(--accent); }
.fd-lib { display: grid; gap: 14px; }
.fd-lib section { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; }
.fd-lib section > h4 { margin: 0 0 8px; font: 600 14px var(--font); } .fd-lib section > h4 span { font-weight: 400; color: var(--muted); font-size: 12px; margin-left: 6px; }
.fd-lib details { border-top: 1px solid var(--line); padding: 6px 0; font-size: 13px; }
.fd-lib details:first-of-type { border-top: none; }
.fd-lib details > summary { cursor: pointer; list-style: none; display: flex; gap: 8px; align-items: baseline; min-width: 0; }
.fd-lib details > summary::-webkit-details-marker { display: none; }
.fd-lib details > summary .nm { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fd-lib details > summary .ct { margin-left: auto; white-space: nowrap; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.fd-lib details > summary .ct .ok { color: var(--ok); } .fd-lib details > summary .ct .err { color: var(--err); } .fd-lib details > summary .ct .warn { color: var(--warn); }
.fd-lib details ul { margin: 6px 0 2px; padding-left: 14px; } .fd-lib details li { padding: 2px 0; line-height: 1.5; }
.fd-lib .src { color: var(--muted); font-size: 12px; }
.fd-exps { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.fd-exp { border: 1px solid var(--line); border-radius: 9px; padding: 9px 11px; font-size: 13px; line-height: 1.5; }
.fd-exp .who { font-size: 12px; color: var(--muted); } .fd-exp .res { margin-top: 3px; color: var(--ok); }
.fd-exp .src { display: block; margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fd-lib .more { color: var(--muted); font-size: 12px; margin-top: 6px; }
.fd-tabref svg { width: 13px; height: 13px; }
.fd-fresh { font-size: 13px; color: var(--muted); white-space: nowrap; }
.fd-fresh.ok { color: var(--ok); }
.fd-follow { margin: 0 0 16px; padding: 16px 20px; }
.fd-follow .fg { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 8px 14px; padding: 12px 0; border-top: 1px solid var(--line); }
.fd-follow .fg:first-of-type { border-top: none; padding-top: 4px; }
.fd-follow .fg > b { font-size: 13px; padding-top: 4px; }
.fd-follow .fg > b small { display: block; font-weight: 400; color: var(--muted); font-size: 11px; margin-top: 2px; }
.fd-follow .chips { display: flex; flex-wrap: wrap; gap: 5px; }
.fd-follow .fd-int { background: var(--bg-2); color: var(--ink); }
.fd-follow .fd-int.custom { background: var(--accent-soft); color: var(--accent); }
.fd-follow .fd-int a { color: inherit; text-decoration: none; }
.fd-follow .more { border: none; background: none; color: var(--accent); font-size: 12px; padding: 1px 6px; }
.fd-follow form { display: flex; gap: 6px; margin-top: 8px; grid-column: 2; }
.fd-follow form input { flex: 1; min-width: 0; font-size: 13px; }
.fd-follow .head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 4px; }
.fd-follow .head .muted { font-size: 12px; }
@media (max-width: 640px) { .fd-follow .fg { grid-template-columns: 1fr; } .fd-follow form { grid-column: 1; } }
.fd-kw .chips { justify-content: flex-start; }
.fd-kw .fd-int small { margin-left: 5px; opacity: .7; font-size: 11px; }
.fd-kw .fd-int.good { background: var(--ok-soft); color: var(--ok); }
.fd-kw .fd-int.bad { background: var(--err-soft); color: var(--err); }
.fd-kw .fd-int.off { opacity: .5; }
.fd-kw .fd-int i { font-style: normal; font-size: 10.5px; opacity: .65; margin-left: 4px; }
.fd-kw .fg > b button { display: block; border: none; background: none; padding: 2px 0 0; font-size: 11.5px; color: var(--muted); cursor: pointer; }
.fd-kw .fg > b button:hover { color: var(--accent); }
.fd-kw .srcs { font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 2px 0 6px; }
.fd-kw .srcs span { cursor: help; border-bottom: 1px dotted var(--line-2); }
.fd-kw .sug { padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); margin-top: 6px; font-size: 13px; }
.fd-kw .sug .why { color: var(--muted); font-size: 12px; margin-top: 2px; }
.fd-kw .sug .acts { display: flex; gap: 6px; margin-top: 6px; }
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
    const followBtn = h('button.ghost', { onclick: () => toggleFollow() }, [ui.icon('user'), h('span', {}, '关注源')]);
    const kwBtn = h('button.ghost', { onclick: () => toggleKw() }, [ui.icon('search'), h('span', {}, '关键词')]);
    const head = ui.pageHead('今天值得看', '', [kwBtn, followBtn, h('div.fd-refresh', {}, [refreshBtn, pop])]);
    const followBox = h('div');
    const kwBox = h('div');
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
    const hnBar = h('div.fd-hnbar');
    const libBox = h('div.fd-lib');
    const sentinel = h('div.fd-sentinel');
    const kbd = h('span.fd-kbd', { title: 'j/k 移动 · l 赞 · s 收藏 · o 打开 · d 深读 · / 输入' }, [h('kbd', {}, 'j'), h('kbd', {}, 'k'), ' 移动 · ', h('kbd', {}, 'l'), ' 赞 · ',
      h('kbd', {}, 's'), ' 收藏 · ', h('kbd', {}, 'o'), ' 打开 · ', h('kbd', {}, 'd'), ' 深读 · ', h('kbd', {}, '/'), ' 输入']);

    // 时间筛选 + 排序：只作用于下面的列表（今日精选固定按综合分）
    const optSel = (opts, key, title) => {
      const s = h('select', { title, onchange: (e) => { st[key] = e.target.value; clearFresh(); s.classList.toggle('on', st[key] !== opts[0][0]); loadList(); } },
        opts.map(([v, name]) => h('option', { value: v, selected: st[key] === v }, name)));
      return s;
    };
    const opts = h('div.fd-opts', {}, [optSel(DAYS, 'days', '按发布时间筛选'), optSel(SORTS, 'sort', '列表排序方式')]);

    const tabRefresh = h('button.ghost.sm.fd-tabref', { onclick: () => doRefresh(st.tab) });
    // 刚刷完的结果常驻在按钮旁；有新增时本次新收的排到列表最前（否则按综合分常落到几十名开外，看着像没刷）
    const freshNote = h('span.fd-fresh');
    let fresh = null;   // { since, added, label }
    el.append(h('style', {}, CSS), head, kwBox, followBox, comp, intsEl, quick,
      ui.section('今日精选', '按热度 · 新鲜度 · 兴趣词 · 你的反馈 · 每个来源最多 1 条'), topBox,
      h('div.fd-bar', {}, [tabs, tabRefresh, freshNote, opts, kbd]), hnBar, listBox, libBox, sentinel);

    // ---------- 状态 / 刷新 ----------
    function renderStatus() {
      const s = status;
      const last = s.running ? `刷新中（${fmtTime(s.started_at).slice(6)} 开始）…` : `上次刷新 ${ago(s.finished_at || s.last_fetched) || '—'}`;
      subEl.textContent = `从 ${s.total} 条里按你的兴趣挑出 · ${last}`;
      refreshBtn.disabled = !!s.running;
      refreshBtn.lastChild.textContent = s.running && !s.scope ? '刷新中…' : '刷新';
      renderTabRefresh();
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
    // 分类页的「刷新本类」：只跑这个分类的来源（论文 → HF / AlphaXiv …）；已入库的同一条只更新不重复
    function renderTabRefresh() {
      const name = TABS.find(([id]) => id === st.tab)?.[1];
      tabRefresh.hidden = !REFRESHABLE.includes(st.tab);
      const busy = status.running && status.scope === st.tab;
      tabRefresh.disabled = !!status.running;
      tabRefresh.title = status.running ? '正在刷新，稍等' : `只抓「${name}」的来源，抓新的、合并重复的`;
      tabRefresh.replaceChildren(ui.icon('refresh'), busy ? `刷新${name}中…` : `刷新${name || ''}`);
    }
    async function doRefresh(type = '') {
      status = await api.post('/api/feed/refresh', type ? { type } : {});
      renderStatus();
      await watchRefresh(type ? TABS.find(([id]) => id === type)?.[1] : '');
    }
    function renderFresh() {
      freshNote.classList.toggle('ok', !!fresh?.added);
      freshNote.textContent = !fresh ? '' : fresh.added ? `${fresh.label}刚刷新 · 新增 ${fresh.added} 条，已排在最前` : `${fresh.label}刚刷新 · 没有新内容`;
    }
    function clearFresh() { if (fresh) { fresh = null; renderFresh(); } }
    async function watchRefresh(label) {
      const since = status.started_utc;
      while (status.running) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!el.isConnected) return;
        status = await api.get('/api/feed/status');
        renderStatus();
      }
      const res = Object.entries(status.results || {}).filter(([k]) => !['judge', 'gist', 'product_analysis'].includes(k));
      const added = res.reduce((n, [, r]) => n + (r.new || 0), 0);
      const errs = res.filter(([, r]) => r.errors?.length).map(([k]) => k);
      toast(`${label ? label + '：' : ''}刷新完成，新增 ${added} 条${errs.length ? `（${errs.join('、')} 有报错，悬停「刷新」看详情）` : ''}`);
      fresh = { since, added, label: label ? label + ' · ' : '' };
      renderFresh();
      reloadAll();
    }

    // ---------- 关注源 ----------
    let followOpen = false;
    const followMore = {};
    async function toggleFollow(force) {
      followOpen = force ?? !followOpen;
      followBtn.classList.toggle('on', followOpen);
      if (!followOpen) { followBox.replaceChildren(); return; }
      const r = await api.get('/api/feed/sources').catch(() => null);
      if (r) renderFollow(r.groups);
    }
    function renderFollow(groups) {
      if (!followOpen) return;
      const total = groups.reduce((n, g) => n + g.items.length, 0);
      followBox.replaceChildren(h('div.card.fd-follow', {}, [
        h('div.head', {}, [h('b', {}, `关注源 · ${total}`), h('span.muted', {}, '加进来的会马上抓一次；高亮的是你加的，删掉默认的也能再加回来')]),
        ...groups.map((g) => {
          const LIMIT = 24;
          const all = followMore[g.id] ? g.items : g.items.slice(0, LIMIT);
          const input = h('input', { placeholder: g.hint });
          const add = h('button.sm', { type: 'submit' }, [ui.icon('plus'), '关注']);
          return h('div.fg', {}, [
            h('b', {}, [g.label, h('small', {}, `${g.items.length} 个`)]),
            h('div', {}, [
              h('div.chips', {}, [
                ...all.map((x) => h('span.fd-int' + (x.custom ? '.custom' : ''), { title: x.url || x.key }, [
                  x.url ? h('a', { href: x.url, target: '_blank', rel: 'noopener' }, x.label) : x.label,
                  h('button', { title: '取消关注', onclick: async () => {
                    const r = await api.post('/api/feed/sources/remove', { list: x.list, key: x.key }).catch((e) => { toast(String(e.message).replace(/^"|"$/g, '')); return null; });
                    if (r) { toast(`已取消关注 ${x.label}`); renderFollow(r.groups); }
                  } }, ui.icon('x'))])),
                g.items.length > LIMIT ? h('button.more', { onclick: () => { followMore[g.id] = !followMore[g.id]; renderFollow(groups); } },
                  followMore[g.id] ? '收起' : `展开全部 ${g.items.length} 个`) : null]),
              h('form', { onsubmit: async (e) => {
                e.preventDefault();
                const value = input.value.trim();
                if (!value) return;
                add.disabled = true; add.lastChild.textContent = '识别中…';
                const r = await api.post('/api/feed/sources', { group: g.id, value }).catch((err) => { toast(String(err.message || '加不上').replace(/^"|"$/g, '')); return null; });
                add.disabled = false; add.lastChild.textContent = '关注';
                if (!r) return;
                toast(r.exists ? `${r.label} 已在关注里` : `已关注 ${r.label}${r.refreshing ? '，正在抓取…' : ''}`);
                renderFollow(r.groups);
                if (r.refreshing) { status = await api.get('/api/feed/status'); renderStatus(); watchRefresh(r.label); }
              } }, [input, add])])]);
        })]));
    }

    // ---------- 关键词（主题表） ----------
    let kwOpen = false, kw = null, kwBusy = false;
    const KW_LISTS = ['en', 'zh', 'hn', 'github', 'reddit', 'youtube', 'zhihu', 'x'];
    async function toggleKw(force) {
      kwOpen = force ?? !kwOpen;
      kwBtn.classList.toggle('on', kwOpen);
      if (!kwOpen) { kwBox.replaceChildren(); return; }
      kw = await api.get('/api/feed/topics').catch(() => null);
      renderKw();
    }
    const errMsg = (e) => String(e.message || e).replace(/^"|"$/g, '').replace(/^\{"detail":"|"\}$/g, '');
    async function saveTopics(topics, msg) {
      const r = await api.put('/api/feed/topics', { topics }).catch((e) => { toast(errMsg(e)); return null; });
      if (r) { kw = r; renderKw(); if (msg) toast(msg); }
    }
    // 一个词可能被几个来源用：合计各来源的数字；有一个来源有效就算有效
    function termInfo(tp, term) {
      const t = term.toLowerCase(), rows = [];
      for (const s of Object.keys(kw.langs)) {
        const used = s in tp ? tp[s] : tp[kw.langs[s]];
        if (!(used || []).some((x) => x.toLowerCase() === t) || kw.explicit.includes(s)) continue;
        const r = kw.stats[`${s}|${t}`];
        const inUse = (kw.queries[s] || []).some((x) => x.toLowerCase() === t);
        rows.push({ s, r, inUse });
      }
      const sum = (k) => rows.reduce((n, x) => n + (x.r?.[k] || 0), 0);
      const vs = rows.map((x) => x.r?.verdict).filter(Boolean);
      const verdict = vs.includes('有效') ? '有效' : vs.find((v) => v === '低效' || v === '没搜到') || '';
      const good = sum('liked') + sum('saved') + sum('deep');
      const title = rows.map(({ s, r, inUse }) => `${kw.labels[s]}：` + (r ? `搜到 ${r.found} · 留下 ${r.kept} · 赞 ${r.liked} 藏 ${r.saved} 深读 ${r.deep} · 搜过 ${r.runs} 次 · ${r.verdict}` : '还没数据')
        + (inUse ? '' : '（超出上限，这次不搜）')).join('\n') || '没有来源用这个词（对应来源用自己的列表）';
      return { found: sum('found'), kept: sum('kept'), good, verdict, title, srcs: rows.map((x) => kw.labels[x.s]) };
    }
    function renderKw() {
      if (!kwOpen) return;
      if (!kw) { kwBox.replaceChildren(h('div.card.fd-follow', {}, '关键词加载失败')); return; }
      const topics = kw.topics;
      const bad = [];
      const termChip = (tp, ti, term, key) => {
        const x = termInfo(tp, term);
        if ((x.verdict === '低效' || x.verdict === '没搜到') && !bad.some((b) => b.term.toLowerCase() === term.toLowerCase())) bad.push({ ti, term, x });
        const cls = x.verdict === '有效' ? '.good' : x.verdict ? '.bad' : '';
        return h('span.fd-int' + cls + (tp.off ? '.off' : ''), { title: x.title }, [
          term, key !== 'en' && key !== 'zh' ? h('i', {}, `仅${kw.labels[key]}`) : null,
          x.found ? h('small', {}, `${x.found}→${x.kept}${x.good ? ` ♥${x.good}` : ''}`) : null,
          h('button', { title: '删掉这个词', onclick: () => removeTerm(ti, term) }, ui.icon('x'))]);
      };
      const rows = topics.map((tp, ti) => {
        const input = h('input', { placeholder: '加词：中文进知乎，英文进 HN / Reddit / YouTube / GitHub' });
        const chips = [];
        for (const k of KW_LISTS) for (const t of tp[k] || []) chips.push(termChip(tp, ti, t, k));
        return h('div.fg', {}, [
          h('b', {}, [tp.name, h('small', {}, tp.off ? '已停用' : `${chips.length} 个词`),
            h('button', { onclick: () => saveTopics(topics.map((x, i) => i === ti ? { ...x, off: !x.off } : x), tp.off ? `已启用「${tp.name}」` : `已停用「${tp.name}」`) }, tp.off ? '启用' : '停用'),
            h('button', { onclick: () => saveTopics(topics.filter((_, i) => i !== ti), `已删除主题「${tp.name}」`) }, '删除主题')]),
          h('div', {}, [h('div.chips', {}, chips),
            h('form', { onsubmit: (e) => {
              e.preventDefault();
              const add = input.value.split(/[,，、\n]/).map((x) => x.trim()).filter(Boolean);
              if (!add.length) return;
              const next = { ...tp };
              for (const t of add) {
                const k = /[一-鿿]/.test(t) ? 'zh' : 'en';
                if (!(next[k] || []).some((x) => x.toLowerCase() === t.toLowerCase())) next[k] = [...(next[k] || []), t];
              }
              saveTopics(topics.map((x, i) => i === ti ? next : x), `已加入：${add.join('、')}`);
            } }, [input, h('button.sm', { type: 'submit' }, [ui.icon('plus'), '加词'])])])]);
      });
      const nameIn = h('input', { placeholder: '新主题名，比如「推理加速」' });
      const addTopic = h('div.fg', {}, [h('b', {}, '新主题'), h('form', { style: 'margin-top:0; grid-column:auto', onsubmit: (e) => {
        e.preventDefault();
        const name = nameIn.value.trim();
        if (!name) return;
        if (topics.some((x) => x.name.toLowerCase() === name.toLowerCase())) { toast('已有这个主题'); return; }
        saveTopics([...topics, { name }], `已加主题「${name}」，再给它加几个词`);
      } }, [nameIn, h('button.sm', { type: 'submit' }, [ui.icon('plus'), '加主题'])])]);

      const srcs = h('div.srcs', {}, ['这次各来源搜：', ...Object.keys(kw.langs).map((s) => kw.explicit.includes(s)
        ? h('span', { title: (kw.queries[s] || []).join('\n') }, `${kw.labels[s]} 用自己的列表`)
        : h('span', { title: (kw.queries[s] || []).join('\n') || '不搜' }, `${kw.labels[s]} ${(kw.queries[s] || []).length}/${kw.caps[s]}`))]);
      const badBox = bad.length ? h('div.fg', {}, [h('b', {}, ['建议换掉', h('small', {}, `近 ${kw.days} 天`)]), h('div.chips', {},
        bad.map(({ ti, term, x }) => h('span.fd-int.bad', { title: x.title }, [term, h('small', {}, x.verdict === '没搜到' ? '没搜到' : `${x.found}→${x.kept}`),
          h('button', { title: '从所有主题里删掉这个词', onclick: () => removeTerm(null, term) }, ui.icon('x'))])))]) : null;

      const sugBtn = h('button.sm.outline', { disabled: kwBusy, onclick: async () => {
        kwBusy = true; renderKw();
        const r = await api.post('/api/feed/topics/suggest', {}).catch((e) => { toast(errMsg(e)); return null; });
        kwBusy = false;
        if (r) { kw = r; toast(r.added ? `推荐了 ${r.added} 个候选主题` : '没有新的候选'); }
        renderKw();
      } }, [ui.icon('spark'), kwBusy ? '分析中…' : '根据我的反馈推荐']);
      const sugBox = h('div.fg', {}, [h('b', {}, ['候选', h('small', {}, '赞 / 收藏 / 深读过的')]), h('div', {}, [sugBtn,
        ...(kw.suggestions || []).map((x) => h('div.sug', {}, [h('b', {}, x.name), ' ',
          h('span.muted', {}, [...(x.en || []), ...(x.zh || [])].join(' · ')), x.reason ? h('div.why', {}, x.reason) : null,
          h('div.acts', {}, [
            h('button.sm', { onclick: () => answerSug(x.name, 'accept', `已加入「${x.name}」`) }, [ui.icon('plus'), '加入']),
            h('button.sm.ghost', { onclick: () => answerSug(x.name, 'dismiss', '已忽略，以后不再推荐这些词') }, '忽略')])]))])]);

      kwBox.replaceChildren(h('div.card.fd-follow.fd-kw', {}, [
        h('div.head', {}, [h('b', {}, `关键词 · ${topics.length} 个主题`),
          h('span.muted', {}, `一份主题表派生各来源的搜索词；词后数字是近 ${kw.days} 天「搜到→留下 ♥赞藏深读」，悬停看各来源`)]),
        srcs, ...rows, addTopic, badBox, sugBox]));
    }
    function removeTerm(ti, term) {
      const t = term.toLowerCase();
      const topics = kw.topics.map((x, i) => ti !== null && i !== ti ? x : Object.fromEntries(Object.entries(x).map(([k, v]) =>
        [k, Array.isArray(v) ? v.filter((y) => y.toLowerCase() !== t) : v])));
      saveTopics(topics, `已删掉「${term}」`);
    }
    async function answerSug(name, action, msg) {
      const r = await api.post('/api/feed/topics/suggestion', { name, action }).catch((e) => { toast(errMsg(e)); return null; });
      if (r) { kw = r; renderKw(); toast(msg); }
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
      (x.extra?.feed || x.extra?.subreddit || x.extra?.channel) && h('span.fd-chip', {}, x.extra.channel || x.extra.feed || `r/${x.extra.subreddit}`),
      x.extra?.flair && h('span.fd-chip', {}, x.extra.flair),
      x.extra?.duration && h('span.fd-chip', {}, fmtDur(x.extra.duration)),
      x.source === 'reddit' && x.extra?.comments ? h('span.fd-chip', {}, [ui.icon('chat'), `评论 ${x.extra.comments}`]) : null,
      x.extra?.link && h('a.fd-chip', { href: x.extra.link, target: '_blank', rel: 'noopener', title: '帖子指向的外部链接' }, [ui.icon('arrow'), host(x.extra.link) || '外链']),
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
      : x.seen_days >= 3 ? h('span.fd-old', { title: '第一次收录到现在的天数（10-31 之前收的从 10-31 算起）' }, `在榜 ${x.seen_days} 天`) : null;
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
    // 产品分析（产品分类）：收入 / 商业模式 / 定位 / 价值 / 痛点；TrustMRR 收入是支付渠道验证的数字，没分析时也先显示
    const PA = [['revenue', '收入'], ['model', '商业模式'], ['position', '产品定位'], ['value', '用户价值'], ['pain', '解决痛点']];
    // 折叠时的一行：收入取前三项（MRR / 近 30 天 / 环比），没公开就用定位；商业模式取第一个分句
    const clause = (t, n) => { const c = String(t || '').replace(/^推测：/, '推测 ').split(/[，；。,;]/)[0]; return c.length > n ? c.slice(0, n) + '…' : c; };
    const paBox = (entry) => {
      const { x } = entry;
      const pa = { revenue: x.extra?.revenue || '', ...(x.extra?.pa || {}) };
      const rows = PA.filter(([k]) => pa[k]);
      if (!rows.length) return null;
      const grid = h('div.fd-pa', { title: x.extra?.pa ? '收入来自数据源（TrustMRR 为支付渠道验证）；其余由模型根据标题、简介和数据生成' : '' },
        rows.flatMap(([k, n]) => [h('b', {}, n), h('span' + (k === 'revenue' ? '.rev' : ''), {}, pa[k])]));
      const rev = pa.revenue && pa.revenue !== '未公开';
      const line = [rev ? ['收入', pa.revenue.split('，').slice(0, 3).join(' · ')] : pa.position && ['定位', clause(pa.position, 40)],
        pa.model && ['模式', clause(pa.model, 30)]].filter(Boolean);
      const d = h('details.fd-pa-d', { title: '点击展开 / 收起产品分析' }, [
        h('summary', {}, line.flatMap(([k, v], j) => [j ? h('span.sep', {}, '|') : null, h('b', {}, k), v])), grid]);
      d.open = !!entry.paOpen;
      d.addEventListener('toggle', () => { entry.paOpen = d.open; });
      return d;
    };
    // HN 评论区提炼：一句话总结常显，展开看链接 / 技术产品 / 观点 / 经验；每条后面的小编号点开是 HN 上的原评论
    const cids = (ids) => (ids || []).slice(0, 3).map((id, j) => h('a.fd-cid', { href: HN_ITEM(id), target: '_blank', rel: 'noopener', title: '打开这条 HN 评论' }, `#${j + 1}`));
    const hnSec = (title, rows) => rows.length ? h('div.fd-hn-sec', {}, [h('h6', {}, title), h('ul', {}, rows)]) : null;
    async function redigest(entry) {
      entry.digesting = true; mount(entry);
      try {
        const r = await api.post('/api/feed/hn/digest', { id: entry.x.id });
        for (const e of entries) if (e.x.id === entry.x.id) { e.x.extra = { ...(e.x.extra || {}), hn: r.hn }; e.hnOpen = true; }
        toast('评论区已提炼');
      } catch (e) { toast('提炼失败：' + e.message, true); }
      for (const e of entries) if (e.x.id === entry.x.id) { e.digesting = false; mount(e); }
    }
    const hnBox = (entry) => {
      const { x } = entry;
      if (x.source !== 'hn') return null;
      const d = x.extra?.hn;
      const btn = (label) => h('button.ghost.sm', { disabled: !!entry.digesting, title: '读评论区（前若干条高赞楼）并提炼', onclick: (e) => { e.stopPropagation(); redigest(entry); } }, entry.digesting ? '提炼中…' : label);
      if (!d) {
        if (st.tab !== 'hn') return null;
        const n = x.extra?.comments || 0;
        return h('div.fd-hn-none', {}, [h('span', {}, n < 30 ? `评论 ${n} 条，不到 30 条不自动提炼` : `评论 ${n} 条 · 还没提炼（刷新时按热度挑前 30 帖）`), btn('现在提炼')]);
      }
      const links = (d.links || []).map((l) => h('li', {}, [h('span.k', {}, l.kind),
        h('a', { href: l.url, target: '_blank', rel: 'noopener' }, l.title || host(l.url) || l.url), ' ', h('span.d', {}, [host(l.url), l.mentions > 1 ? ` · 提到 ${l.mentions} 次` : '', l.why ? ' · ' + l.why : '']), ...cids(l.cids)]));
      const ents = (d.entities || []).length ? h('div.fd-hn-sec', {}, [h('h6', {}, '提到的技术 / 产品（悬停看评价）'),
        h('div.fd-ents', {}, d.entities.map((e) => h('span.fd-ent.' + SENT[e.sentiment][1], { title: `${e.kind} · ${SENT[e.sentiment][0]}${e.note ? '：' + e.note : ''}` }, e.name)))]) : null;
      const ops = (d.opinions || []).map((o) => h('li', {}, [h('span.k' + (o.stance === '主流' ? '.ok' : o.stance === '反对' ? '.err' : o.stance === '少数' ? '.warn' : ''), {}, o.stance),
        o.claim, o.n ? h('span.d', {}, ` · 约 ${o.n} 条`) : null, ...cids(o.cids)]));
      const exps = (d.experiences || []).map((e) => h('li', {}, [h('b', {}, e.who), '：', e.did, e.result ? h('span.d', {}, ' → ' + e.result) : null, ...cids(e.cids)]));
      const box = h('details.fd-hn', {}, [
        h('summary', { title: '点击展开 / 收起评论区提炼' }, [h('b', {}, '评论区'), d.tldr || '（无总结）',
          h('span.n', {}, `读了 ${d.read}/${d.total} 条 · 链接 ${(d.links || []).length} · 经验 ${(d.experiences || []).length}`)]),
        hnSec('观点与判断', ops), hnSec('实战经验', exps), hnSec('评论里推荐的链接', links), ents,
        h('div.fd-hn-none', {}, [h('span', {}, `提炼于 ${fmtTime(x.extra?.hn_at) || '—'}，模型根据评论原文生成；链接都在评论里出现过`), btn('重新提炼')]),
      ]);
      box.open = !!entry.hnOpen;
      box.addEventListener('toggle', () => { entry.hnOpen = box.open; });
      return box;
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
            paBox(entry),
            hnBox(entry),
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
            paBox(entry),
            hnBox(entry),
            h('div.fd-line', {}, [TYPE_NAME[x.type] && h('span.fd-chip.type', {}, TYPE_NAME[x.type]),
              x.extra?.x_article && h('span.fd-chip.art', {}, x.extra.x_article === 'own' ? 'X 长文' : '引用 X 长文'),
              h('span', { style: { whiteSpace: 'nowrap' } }, x.source_label + (fmtDate(x.date) ? ' · ' + fmtDate(x.date) : '')),
              x.extra?.hn_url && h('a.muted', { href: x.extra.hn_url, target: '_blank', rel: 'noopener', style: { whiteSpace: 'nowrap' } }, 'HN 讨论'),
              (x.extra?.channel || x.extra?.subreddit) && h('span', { style: { whiteSpace: 'nowrap' } }, x.extra.channel || `r/${x.extra.subreddit}`),
              x.extra?.link && h('a.muted', { href: x.extra.link, target: '_blank', rel: 'noopener', style: { whiteSpace: 'nowrap' } }, host(x.extra.link) || '外链'),
              x.why ? h('span.fd-why', { title: x.why }, '· ' + x.why) : null]),
            verdictBox(entry),
          ]),
          actions(entry),
        ]);
      }
      node.addEventListener('mousedown', (e) => { if (!e.target.closest('button, a')) select(entries.indexOf(entry), false); });
      node._hay = norm([x.title, x.gist, x.summary, x.source_label, x.why, x.extra?.feed, x.extra?.channel, x.extra?.subreddit, x.extra?.flair, TYPE_NAME[x.type],
        x.extra?.revenue, ...Object.values(x.extra?.pa || {}), x.extra?.hn?.tldr, ...(x.extra?.hn?.entities || []).map((e) => e.name)].join(' '));
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
        onclick: () => { if (st.tab === id) return; st.tab = id; clearFresh(); renderTabs(); renderTabRefresh(); loadList(); },
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
    const baseOffset = () => (!st.tab && !st.q && st.days === '0' && st.sort === 'score' && !fresh?.added ? TOP_N : 0);
    function params(offset) {
      const p = new URLSearchParams({ limit: PAGE, offset, q: st.q, days: st.days, sort: st.sort });
      if (st.tab === 'saved') p.set('saved', 'true'); else if (st.tab) p.set('type', st.tab);
      if (fresh?.added && fresh.since) p.set('since', fresh.since);
      return p;
    }
    // HN 精读：按帖子（普通列表 + 评论区提炼）/ 经验库（跨帖累计）
    const libView = () => st.tab === 'hn' && st.hnView === 'lib';
    function renderHnBar() {
      if (st.tab !== 'hn') { hnBar.replaceChildren(); hnBar.style.display = 'none'; return; }
      hnBar.style.display = '';
      const seg = (id, name) => h('button' + (st.hnView === id ? '.on' : ''), { onclick: () => { if (st.hnView === id) return; st.hnView = id; renderHnBar(); loadList(); } }, name);
      hnBar.replaceChildren(h('div.fd-seg', {}, [seg('posts', '按帖子'), seg('lib', '经验库')]),
        h('span', {}, st.hnView === 'lib' ? '已提炼帖子的跨帖累计：技术与产品口碑、被反复推荐的链接、经验卡片；上面的筛选框和时间筛选也作用于这里'
          : '评论 ≥30 的帖子每次刷新按热度提炼前 30 帖；点「评论区」展开'));
    }
    const postLink = (p) => h('a.src', { href: p.hn_url || '#', target: '_blank', rel: 'noopener', title: p.title }, `${p.date ? p.date.slice(5) + ' · ' : ''}${p.title}`);
    const capNote = (n, cap) => (n > cap ? h('div.more', {}, `还有 ${n - cap} 个，用筛选框缩小范围`) : null);
    async function loadLib(seq) {
      const r = await api.get('/api/feed/hn/library?' + new URLSearchParams({ q: st.q, days: st.days }));
      if (seq !== loadSeq) return;
      listOffset = listTotal = 0; renderSentinel();
      if (!r.posts) {
        libBox.replaceChildren(ui.empty(st.q ? `经验库里没有匹配「${st.q}」的内容` : '还没有提炼过的帖子', '切到「按帖子」点「现在提炼」，或刷新 HN 精读'));
        return;
      }
      const sentCt = (g) => h('span.ct', {}, [`${g.posts} 帖 · `, g.pos ? h('span.ok', {}, `好 ${g.pos} `) : null, g.neg ? h('span.err', {}, `差 ${g.neg} `) : null,
        g.mixed ? h('span.warn', {}, `褒贬 ${g.mixed} `) : null, g.neutral ? `提及 ${g.neutral}` : null]);
      const E = 40, L = 30, X = 60;
      const ents = r.entities.slice(0, E).map((g) => h('details', {}, [h('summary', {}, [h('span.nm', {}, g.name), h('span.fd-chip.type', {}, g.kind), sentCt(g)]),
        h('ul', {}, g.notes.map((n) => h('li', {}, [h('span.fd-ent.' + SENT[n.sentiment][1], {}, SENT[n.sentiment][0]), ' ', n.note || '—', ...cids(n.cids), ' ', postLink(n)])))]));
      const links = r.links.slice(0, L).map((g) => h('details', {}, [h('summary', {}, [h('span.fd-chip.type', {}, g.kind),
        h('a.nm', { href: g.url, target: '_blank', rel: 'noopener', onclick: (e) => e.stopPropagation() }, g.title || host(g.url) || g.url),
        h('span.src', {}, host(g.url)), h('span.ct', {}, `${g.posts} 帖 · 提到 ${g.mentions} 次`)]),
        h('ul', {}, g.whys.map((w) => h('li', {}, [w.why || '—', ...cids(w.cids), ' ', postLink(w)])))]));
      const exps = r.experiences.slice(0, X).map((x) => h('div.fd-exp', {}, [h('div.who', {}, x.who), h('div', {}, x.did),
        x.result ? h('div.res', {}, '→ ' + x.result) : null, h('span.src', {}, [postLink(x.post), ...cids(x.cids)])]));
      libBox.replaceChildren(
        h('div.muted', { style: { fontSize: '12.5px' } }, `已提炼 ${r.posts} / ${r.total} 帖${st.q ? ` · 匹配「${st.q}」` : ''}`),
        h('section', {}, [h('h4', {}, ['技术与产品', h('span', {}, `${r.entities.length} 个 · 按被几帖讨论排序，展开看每帖的评价`)]), ...(ents.length ? ents : [h('div.muted', {}, '无')]), capNote(r.entities.length, E)]),
        h('section', {}, [h('h4', {}, ['被推荐的链接', h('span', {}, `${r.links.length} 个 · 博客 / 视频 / 仓库 / 产品…`)]), ...(links.length ? links : [h('div.muted', {}, '无')]), capNote(r.links.length, L)]),
        h('section', {}, [h('h4', {}, ['经验卡片', h('span', {}, `${r.experiences.length} 条 · 评论者亲身做过的事和结果`)]), exps.length ? h('div.fd-exps', {}, exps) : h('div.muted', {}, '无'), capNote(r.experiences.length, X)]));
    }
    async function loadList() {
      const seq = ++loadSeq;
      renderHnBar();
      listBox.style.display = libView() ? 'none' : '';
      libBox.style.display = libView() ? '' : 'none';
      if (libView()) {
        entries = entries.filter((e) => e.kind !== 'list');
        if (sel >= entries.length) sel = -1;
        listBox.replaceChildren();
        return loadLib(seq);
      }
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
      if (loading || listOffset >= listTotal || libView()) return;
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
