// 待你审批 / 决策（规划、Agent 看板共用）：每条可 批准 / 不批准 / 忽略，或写一句指令再发。
// 一个任务的事项都决定完后，平台续接那个 Agent 会话把决定发过去（后端 /api/jobs/approvals）。
// 用法：import { approvals } from './_approvals.js'; el.append(approvals(ctx, { fallback }))
//   fallback(): 后端还没提供审批接口（平台待重启）时，返回 [[来源标题, 事项]] 只读展示。
export function approvals(ctx, { fallback, onChange } = {}) {
  const { api, h, toast } = ctx;
  injectStyle();
  const box = h('div.ap', { hidden: true });
  let timer;

  const load = async () => {
    if (!box.isConnected && timer) return clearInterval(timer);
    let list;
    try { list = await api.get('/api/jobs/approvals'); } catch {
      const fb = (await fallback?.()) || [];
      box.hidden = !fb.length;
      return box.replaceChildren(h('b.ap-h', {}, `⚠ 待你审批 / 决策（${fb.length}）`),
        h('div.ap-warn', {}, '审批按钮在平台下次自动重启后可用（正在等后台任务跑完，不会打断它们）。'),
        h('ul.ap-ro', {}, fb.map(([t, x]) => h('li', {}, [x, h('span.ap-from', {}, '— ' + t)]))));
    }
    box.hidden = !list.length;
    // 按最初的执行任务分组（审批续接的几轮算同一个任务）：一组决定完才一起发给 Agent
    const groups = new Map();
    for (const a of list) { const k = a.root_job_id || a.job_id; (groups.get(k) || groups.set(k, []).get(k)).push(a); }
    box.replaceChildren(h('b.ap-h', {}, `⚠ 待你审批 / 决策（${list.length}）`),
      h('div.ap-warn', {}, 'Agent 只在不可逆的事（合并 main、发布、删数据、对外发送、花钱）上问你，问过的不会重复问；其余按它的建议默认继续。'),
      ...[...groups.values()].map((items) => h('div.ap-group', {}, [
        h('div.ap-src', {}, [h('span.tag.warn', {}, items[0].round > 1 ? `第 ${items[0].round} 轮` : (items[0].kind || '任务')),
          items[0].link ? h('a', { href: items[0].link }, items[0].title) : h('span', {}, items[0].title),
          h('span.ap-from', {}, items.length > 1 ? `${items.length} 项都决定后一起发给 Agent` : '决定后发给 Agent 继续')]),
        ...items.map(row),
      ])));
  };

  function row(a) {
    const note = h('input', { type: 'text', placeholder: '给 Agent 的指令（可选），如：先别合并，把 RSS 换成新列表再跑一遍测试' });
    const send = async (decision) => {
      if (decision === 'replied' && !note.value.trim()) { note.focus(); return toast('先写一句指令', true); }
      try {
        const r = await api.post(`/api/jobs/approvals/${a.id}/decide`, { decision, note: note.value });
        toast(r.followup_job_id ? '已发给 Agent，续接原会话执行中' : r.left ? `已记录，这个任务还差 ${r.left} 项` : '已记录');
        await load(); onChange?.();
      } catch (e) { toast(e.message, true); }
    };
    note.onkeydown = (e) => { if (e.key === 'Enter' && !e.isComposing) send(note.value.trim() ? 'replied' : 'approved'); };
    return h('div.ap-row', {}, [
      h('div.ap-item', {}, a.item),
      h('div.ap-acts', {}, [
        note,
        h('button.sm.primary', { onclick: () => send('approved'), title: '批准（附上输入框里的指令）' }, '批准'),
        h('button.sm.outline', { onclick: () => send('rejected'), title: '不批准（附上输入框里的原因）' }, '不批准'),
        h('button.sm.outline', { onclick: () => send('replied'), title: '不表态，只把输入框里的指令发给 Agent' }, '发指令'),
        h('button.sm.ghost', { onclick: () => send('dismissed'), title: '不是要审批的事，忽略' }, '忽略'),
      ]),
    ]);
  }

  load();
  timer = setInterval(() => !document.hidden && !box.contains(document.activeElement) && load(), 15000);
  return box;
}

function injectStyle() {
  if (document.getElementById('ap-style')) return;
  const s = document.createElement('style');
  s.id = 'ap-style';
  s.textContent = `
  .ap { margin: 4px 0 12px; padding: 12px 14px; border-radius: 12px; background: var(--warn-soft); border: 1px solid var(--warn); }
  .ap-h { color: var(--warn); font-size: 14px; }
  .ap-warn { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .ap-ro { margin: 6px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.6; }
  .ap-from { color: var(--muted); font-size: 12px; margin-left: 6px; }
  .ap-group { margin-top: 10px; }
  .ap-src { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; flex-wrap: wrap; }
  .ap-src a { color: var(--text); }
  .ap-row { padding: 8px 0 8px 10px; border-left: 2px solid var(--warn); margin: 6px 0 0 4px; }
  .ap-item { font-size: 13px; line-height: 1.6; }
  .ap-acts { display: flex; gap: 6px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
  .ap-acts input { flex: 1; min-width: 220px; padding: 4px 12px; border-radius: 999px; font-size: 12px; background: var(--panel); }
  .ap-acts button { white-space: nowrap; }
  `;
  document.head.append(s);
}
