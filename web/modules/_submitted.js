// 我提交的任务（规划页）：调研、深读、学习计划、读书提交过哪些、各到哪一步，点一行进到各自的页面。不分日期。
// 用法：import { submitted } from './_submitted.js'; el.append(submitted(ctx))
const TABS = [['needs', '等你处理'], ['running', '进行中'], ['ready', '可以看了'], ['done', '已看完'], ['all', '全部'], ['closed', '已关闭']];
const TAG = { needs: 'warn', running: 'ok', ready: 'line', done: 'gray' };
const STATE = { needs: '等你处理', running: '进行中', ready: '可以看了', done: '已看完' };
const PAGE = 8;
const POLL = 10000;

// 页面主体重绘时（改事项、切日期）不闪空白、不丢选中的页签
let last = null;
let tab = '';

export function submitted(ctx) {
  const { api, h, toast } = ctx;
  injectStyle();
  const box = h('div.card.flat.sb-card');
  let shown = PAGE;
  let polled = false;

  const row = (x) => h('a.sb-row.' + x.state, { href: x.link }, [
    h('span.sb-dot'),
    h('span.sb-main', {}, [
      h('span.sb-title', { title: x.title }, x.title),
      h('span.sb-detail', { title: x.detail }, x.detail),
    ]),
    x.pct != null ? h('span.sb-pct', { title: `${x.pct}%` }, h('i', { style: { width: `${x.pct}%` } })) : null,
    h('span.tag.line.sb-type', {}, x.label),
    tab === 'all' || tab === 'closed' ? h('span.tag.sb-state.' + TAG[x.state], {}, STATE[x.state]) : null,
    h('span.sb-at', { title: `提交于 ${x.created_at.replace('T', ' ')}` }, x.created_at.slice(5, 10)),
    x.state === 'running' ? null : h('button.ghost.sm.sb-close', {
      title: x.closed ? '放回列表' : '关闭：不再显示，可在「已关闭」里恢复',
      onclick: (e) => { e.preventDefault(); e.stopPropagation(); setClosed(x); },
    }, x.closed ? '恢复' : '关闭'),
  ]);

  const setClosed = async (x) => {
    try {
      await api.post(`/api/plan/submitted/${encodeURIComponent(x.key)}/${x.closed ? 'reopen' : 'close'}`, {});
      await refresh();
    } catch (e) { toast(e.message, true); }
  };

  const render = (d) => {
    const n = (k) => (k === 'all' ? d.items.length - d.counts.closed : d.counts[k]);
    if (!tab || !n(tab)) tab = TABS.find(([k]) => n(k))?.[0] || 'all';
    const list = d.items.filter((x) => (tab === 'closed' ? x.closed : !x.closed && (tab === 'all' || x.state === tab)));
    box.replaceChildren(
      h('div.sb-top', {}, [h('b.sb-h', {}, '我提交的任务'), h('span.muted', {}, '调研、深读、学习计划、读书，点一行进入')]),
      h('div.tabs.sb-tabs', {}, TABS.filter(([k]) => k === 'all' || n(k)).map(([k, name]) => h('button' + (tab === k ? '.active' : ''),
        { onclick: () => { tab = k; shown = PAGE; render(d); } }, [name, h('span.sb-n' + (k === 'needs' ? '.warn' : ''), {}, String(n(k)))]))),
      list.length ? h('div.sb-list', {}, list.slice(0, shown).map(row))
        : h('div.muted.sb-none', {}, '还没有提交过。去「调研」或「深度学习」提交后，进展会显示在这里。'),
      ...(list.length > shown ? [h('button.ghost.sm.sb-more', { onclick: () => { shown = list.length; render(d); } }, `显示其余 ${list.length - shown} 条`)] : []),
    );
  };

  const refresh = async () => {
    last = await api.get('/api/plan/submitted');
    render(last);
  };

  const load = async () => {
    if (polled && !box.isConnected) return; // 已离开页面或主体已重绘，别再轮询
    try {
      await refresh();
    } catch (e) {
      if (!last) box.replaceChildren(h('div.muted', {}, '读取失败：' + e.message));
    }
    polled = true;
    if (last?.counts.running) setTimeout(load, POLL); // 进行中才轮询
  };

  if (last) render(last); else box.append(h('div.muted', {}, '读取中…'));
  load();
  return box;
}

function injectStyle() {
  if (document.getElementById('sb-style')) return;
  const s = document.createElement('style');
  s.id = 'sb-style';
  s.textContent = `
  .sb-card { padding: 12px 16px; margin-bottom: 14px; }
  .sb-top { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .sb-h { font: 700 16px var(--serif); }
  .sb-top .muted { font-size: 12px; }
  .sb-tabs { margin-bottom: 6px; }
  .sb-tabs button { padding: 2px 11px; font-size: 13px; }
  .sb-n { margin-left: 5px; font-size: 12px; opacity: .7; } .sb-n.warn { color: var(--warn); opacity: 1; font-weight: 700; }
  .sb-tabs button.active .sb-n { color: inherit; }
  .sb-row { display: flex; align-items: center; gap: 9px; padding: 7px 4px; border-top: 1px dashed var(--line); color: var(--text); text-decoration: none; border-radius: 4px; }
  .sb-row:first-child { border-top: 0; }
  .sb-row:hover { background: var(--bg-2); text-decoration: none; }
  .sb-dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--line-2); }
  .sb-row.running .sb-dot { background: var(--ok); animation: pl-pulse 1.4s infinite; }
  .sb-row.needs .sb-dot { background: var(--warn); }
  .sb-row.ready .sb-dot { background: var(--accent); }
  .sb-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .sb-title { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sb-detail { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sb-row.needs .sb-detail { color: var(--warn); }
  .sb-pct { flex: none; width: 56px; height: 5px; border-radius: 3px; background: var(--bg-2); overflow: hidden; }
  .sb-pct i { display: block; height: 100%; background: var(--ok); }
  .sb-type, .sb-state { flex: none; }
  .sb-at { flex: none; font: 12px var(--mono); color: var(--muted); }
  .sb-close { flex: none; padding: 1px 8px; font-size: 12px; opacity: 0; }
  .sb-row:hover .sb-close, .sb-close:focus-visible { opacity: 1; }
  @media (hover: none) { .sb-close { opacity: 1; } }
  .sb-more { margin-top: 4px; }
  .sb-none { font-size: 13px; padding: 6px 0; }
  @media (max-width: 720px) { .sb-pct, .sb-type { display: none; } }
  `;
  document.head.append(s);
}
