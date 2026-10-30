// 今日已交付（Agent 看板 / 复盘共用）：有交付物（推送、部署、PR、发布、文档材料）且之后没再改代码的事。
// 另列「交付后仍有改动」「已提交未推送」，默认折叠。
// 用法：import { deliveries } from './_deliveries.js'; el.append(await deliveries(ctx, { date }))
const TAG = { 推送: 'ok', 部署: 'ok', PR: 'ok', 发布: 'ok', 发布页面: 'ok', 提交: 'line', 文档材料: 'line' };

export async function deliveries(ctx, { date = '', title = '' } = {}) {
  const { api, h, ui } = ctx;
  injectStyle();
  const box = h('div.dl');
  const load = async () => {
    try { box.replaceChildren(...view(await api.get(`/api/agents/deliveries?date=${date}`))); }
    catch (e) { box.replaceChildren(h('div.muted', {}, '读取交付失败：' + e.message)); }
  };

  function row(x) {
    const running = x.state === 'running';
    const warn = running ? '会话还在跑，结束后才算交付完' : x.status === 'changed_after' ? `交付后又改了代码（最后改动 ${x.last_code}）`
      : x.dirty ? `仓库现在还有 ${x.dirty} 个未提交改动` : '';
    const more = [
      x.summary ? h('div.dl-sum', {}, x.summary) : null,
      x.commands?.length ? h('div.dl-cmds', {}, x.commands.map((c) => h('code', {}, c))) : null,
      x.docs?.length ? h('div.dl-docs', {}, [h('span.muted', {}, `文档材料 ${x.docs_total} 份：`),
        ...x.docs.map((p) => h('code', { title: p }, p.replace(x.cwd ? x.cwd + '/' : '', '')))]) : null,
      x.cwd ? h('div.muted.dl-path', {}, `${x.cwd}${x.branch ? ' · ' + x.branch : ''}`) : null,
    ].filter(Boolean);
    const head = h('div.dl-head', {}, [
      h('span.dl-at', {}, x.at),
      ...x.labels.map((l) => h('span.tag.' + (TAG[l] || 'line'), {}, l)),
      h('span.dl-proj', {}, x.project),
      x.link ? h('a.dl-title', { href: x.link }, x.title) : h('span.dl-title', {}, x.title),
      x.docs_total && !x.docs?.length ? h('span.muted', {}, `${x.docs_total} 份文档`) : null,
      warn ? h('span.tag.warn', { title: warn }, running ? '还在跑' : x.status === 'changed_after' ? '仍在改' : '有未提交') : null,
    ]);
    return more.length ? h('details.dl-row', {}, [h('summary', {}, head), h('div.dl-more', {}, more)]) : h('div.dl-row', {}, head);
  }

  function view(d) {
    const n = d.counts;
    const parts = [h('div.dl-top', {}, [
      h('b.dl-h', {}, title || (d.date === new Date().toLocaleDateString('sv-SE') ? '今日已交付' : `${d.date} 已交付`)),
      h('span.dl-n', {}, n.delivered),
      h('span.muted', {}, '有推送 / 部署 / PR / 发布 / 文档材料，且之后没再改代码'),
      h('span.grow'),
      h('button.sm.ghost', { onclick: load, title: '重新统计' }, ui.icon('refresh')),
    ])];
    parts.push(d.delivered.length ? h('div.dl-list', {}, d.delivered.map(row))
      : h('div.muted.dl-none', {}, '还没有检测到交付。推送、部署、开 PR、发布页面，或产出文档材料后会出现在这里。'));
    for (const [k, t] of [['changed_after', '交付后仍有改动 / 还在跑'], ['committed', '已提交未推送']]) {
      if (d[k].length) parts.push(h('details.dl-sub', {}, [h('summary', {}, `${t}（${d[k].length}）`), h('div.dl-list', {}, d[k].map(row))]));
    }
    return [h('div.card.flat.dl-card', {}, parts)];
  }

  await load();
  return box;
}

function injectStyle() {
  if (document.getElementById('dl-style')) return;
  const s = document.createElement('style');
  s.id = 'dl-style';
  s.textContent = `
  .dl-card { padding: 12px 16px; margin-bottom: 12px; }
  .dl-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
  .dl-h { font: 700 16px var(--serif); }
  .dl-n { font: 700 13px var(--font); color: var(--ok); background: var(--ok-soft); border-radius: 99px; padding: 0 9px; }
  .dl-top .muted { font-size: 12px; }
  .dl-list { display: flex; flex-direction: column; }
  .dl-row { border-top: 1px dashed var(--line); padding: 7px 0; }
  .dl-row:first-child { border-top: 0; }
  .dl-row > summary { list-style: none; cursor: pointer; } .dl-row > summary::-webkit-details-marker { display: none; }
  .dl-head { display: flex; align-items: center; gap: 7px; min-width: 0; font-size: 13px; }
  .dl-head .tag { flex: none; }
  .dl-at { font-family: var(--mono); font-size: 12px; color: var(--muted); flex: none; width: 40px; }
  .dl-proj { font-weight: 600; flex: none; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dl-title { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
  a.dl-title { color: var(--accent); }
  .dl-more { padding: 6px 0 2px 47px; font-size: 12px; display: flex; flex-direction: column; gap: 5px; }
  .dl-sum { color: var(--text); opacity: .85; line-height: 1.6; }
  .dl-cmds, .dl-docs { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: center; }
  .dl-cmds code, .dl-docs code { font: 11px var(--mono); background: var(--bg-2); border-radius: 5px; padding: 1px 6px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dl-path { font: 11px var(--mono); }
  .dl-none { font-size: 13px; padding: 6px 0; }
  .dl-sub { margin-top: 6px; font-size: 13px; } .dl-sub > summary { cursor: pointer; color: var(--muted); padding: 4px 0; }
  @media (max-width: 720px) { .dl-proj { max-width: 90px; } .dl-more { padding-left: 0; } }
  `;
  document.head.append(s);
}
