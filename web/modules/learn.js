// 深度学习：条目深读（论文 / GitHub）+ 主题学习计划。路由：#learn、#learn/plans、#learn/plan/<id>
const CSS = `
.learn-progress { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; margin: 6px 0; }
.learn-progress > i { display: block; height: 100%; background: var(--ok); }
.learn-stars button { border: none; background: none; padding: 0 1px; font-size: 16px; color: var(--muted); }
.learn-stars button.on { color: var(--warn); }
.learn-step { margin-bottom: 8px; }
.learn-step.done { opacity: .75; } .learn-step.skipped { opacity: .45; }
.learn-step .head { display: flex; gap: 8px; align-items: center; }
.learn-step .head b { flex: 1; cursor: pointer; }
.learn-step ul { margin: 4px 0; padding-left: 20px; }
.learn-step .body { margin-top: 6px; }
.learn-summary { white-space: pre-wrap; font-size: 13px; margin: 6px 0; }
.learn-out { max-height: 70vh; overflow-y: auto; border-top: 1px solid var(--line); margin-top: 8px; padding-top: 8px; }
`;
const STATUS_TAG = { done: 'ok', active: 'ok', failed: 'err', running: 'warn', queued: 'warn', generating: 'warn', adapting: 'warn' };
const STATUS_TXT = { queued: '排队', running: '解析中', done: '完成', failed: '失败', generating: '生成中', active: '进行中', adapting: '调整中' };
const STEP_TXT = { todo: '待学', doing: '学习中', done: '已完成', skipped: '跳过' };
let onAgentDone = null;
let current = null;
const watching = new Set();
const openSteps = new Set(); // 重绘时保持展开的步骤

const page = {
  // 不用 ctx.refresh()：外壳的 route() 会把右侧对话切回板块总览，打断绑定 ref 的对话
  async render(el, ctx0) {
    current = { el, ctx0 };
    const ctx = { ...ctx0, sub: location.hash.slice(1).split('/').slice(1),
      refresh: () => { current.el.replaceChildren(); return page.render(current.el, current.ctx0); } };
    const { h } = ctx;
    if (!document.getElementById('learn-css')) document.head.append(h('style', { id: 'learn-css' }, CSS));
    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = (e) => { if (e.detail.module === 'learn' && location.hash.startsWith('#learn')) ctx.refresh(); };
    document.addEventListener('agent-done', onAgentDone);

    const [view, id] = ctx.sub;
    if (view === 'plan' && id) return renderPlan(el, ctx, +id);
    const tab = view === 'plans' ? 'plans' : 'items';
    el.append(h('div.tabs', {}, [
      h('button' + (tab === 'items' ? '.active' : ''), { onclick: () => { location.hash = '#learn'; } }, '条目深读（论文 / GitHub）'),
      h('button' + (tab === 'plans' ? '.active' : ''), { onclick: () => { location.hash = '#learn/plans'; } }, '主题学习计划'),
    ]));
    return tab === 'plans' ? renderPlans(el, ctx) : renderItems(el, ctx);
  },
};
export default page;

const tag = (h, status) => h('span.tag' + (STATUS_TAG[status] ? '.' + STATUS_TAG[status] : ''), {}, STATUS_TXT[status] || status);

function watchJob(ctx, jobId, status) {
  if (!jobId || watching.has(jobId) || !['queued', 'running', 'generating', 'adapting'].includes(status)) return;
  watching.add(jobId);
  ctx.api.waitJob(jobId, null, 4000).finally(() => { watching.delete(jobId); if (location.hash.startsWith('#learn')) ctx.refresh(); });
}

function stars(h, value, onset) {
  const box = h('span.learn-stars', { title: '理解度 / 评分' });
  for (let i = 1; i <= 5; i++) {
    box.append(h('button' + (i <= value ? '.on' : ''), { onclick: () => onset(i === value ? 0 : i) }, '★'));
  }
  return box;
}

// ---------- A. 条目 ----------
async function renderItems(el, ctx) {
  const { api, h, toast, field } = ctx;
  const url = h('input', { placeholder: 'arXiv / PDF / DOI 链接，或 GitHub 仓库（owner/repo）' });
  const kind = h('select', {}, [h('option', { value: '' }, '自动识别'), h('option', { value: 'paper' }, '论文'), h('option', { value: 'github' }, 'GitHub 项目')]);
  const focus = h('input', { placeholder: '可选：关注点，例如「评测是否可靠」「调度怎么实现」' });
  const submit = async () => {
    if (!url.value.trim()) return toast('请填写链接', true);
    await api.post('/api/learn/items', { url: url.value.trim(), kind: kind.value, focus: focus.value.trim() });
    toast('已提交后台深读，完成后自动刷新'); ctx.refresh();
  };
  el.append(h('div.card', {}, [h('h3', {}, '新建深读'),
    h('div.row', {}, [h('div', { style: { flex: 3 } }, field('链接', url)), h('div', { style: { flex: 1 } }, field('类型', kind))]),
    field('关注点', focus), h('button.primary', { onclick: submit }, '开始深读')]));

  const items = await api.get('/api/learn/items');
  if (!items.length) el.append(h('p.muted', {}, '还没有深读条目。'));
  for (const it of items) {
    watchJob(ctx, it.job_id, it.status);
    el.append(itemCard(it, ctx));
  }
}

function itemCard(it, ctx) {
  const { api, h, md, toast, openChat } = ctx;
  const isHtml = /\.html?$/i.test(it.output_path || '');
  const outBox = h('div.learn-out', { style: { display: 'none' } });
  const fileName = (it.output_path || '').split('/').pop();
  const open = async () => {
    if (isHtml) return window.open(`/api/learn/items/${it.id}/out/${encodeURIComponent(fileName)}`, '_blank');
    if (outBox.style.display === 'none') {
      outBox.replaceChildren(md(await api.get(`/api/learn/items/${it.id}/file`)));
      outBox.style.display = '';
    } else outBox.style.display = 'none';
  };
  const notes = h('textarea', { rows: 3, value: it.my_notes || '', placeholder: '我的笔记 / 认识' });
  let rating = it.rating || 0;
  const starBox = h('span');
  const drawStars = () => starBox.replaceChildren(stars(h, rating, (v) => { rating = v; drawStars(); }));
  drawStars();
  const notesBox = h('div', { style: { display: it.my_notes ? '' : 'none', marginTop: '8px' } }, [notes,
    h('div.row', {}, [h('span.muted', {}, '评分'), starBox,
      h('button', { onclick: async () => { await api.patch(`/api/learn/items/${it.id}`, { my_notes: notes.value, rating }); toast('已保存'); } }, '保存')])]);
  const ref = `learn:item:${it.id}`;
  return h('div.card', {}, [
    h('div.row', {}, [h('span.tag', {}, it.kind === 'github' ? 'GitHub' : '论文'), tag(h, it.status),
      h('b', { style: { flex: 1 } }, it.title || it.url), it.rating ? h('span.muted', {}, '★'.repeat(it.rating)) : null]),
    h('div.muted', {}, [h('a', { href: it.url.startsWith('http') ? it.url : '#learn', target: '_blank' }, it.url), ` · ${it.created_at?.slice(0, 10) || ''}`,
      it.focus ? ` · 关注：${it.focus}` : '']),
    it.summary ? h('div.learn-summary', {}, it.summary) : null,
    h('div.row', {}, [
      it.output_path ? h('button.primary', { onclick: open }, isHtml ? '打开 HTML 教程' : '阅读笔记') : null,
      it.kind === 'github' && it.output_path ? h('button', { onclick: () => window.open(`/api/learn/items/${it.id}/out/summary.md`, '_blank') }, 'summary.md') : null,
      h('button', { onclick: () => openChat({ module: 'learn', ref, title: '追问：' + (it.title || it.url).slice(0, 20) }) }, '继续追问'),
      h('button', { onclick: () => { notesBox.style.display = notesBox.style.display === 'none' ? '' : 'none'; } }, '笔记 / 评分'),
      h('button.ghost', { onclick: async () => { if (!confirm('重新生成会覆盖产物，继续？')) return; await api.post(`/api/learn/items/${it.id}/rerun`, {}); ctx.refresh(); } }, '重新生成'),
      it.job_id ? h('a.muted', { href: `/api/jobs/${it.job_id}`, target: '_blank' }, `job ${it.job_id}`) : null,
      h('button.ghost', { onclick: async () => { if (!confirm('删除该条目？（产物文件保留）')) return; await api.del(`/api/learn/items/${it.id}`); ctx.refresh(); } }, '删除'),
    ]),
    notesBox, outBox,
  ]);
}

// ---------- B. 计划列表 ----------
async function renderPlans(el, ctx) {
  const { api, h, toast, field } = ctx;
  const topic = h('input', { placeholder: '例如：世界模型、强化学习用于 LLM 推理、产品 UI 设计' });
  const bg = h('textarea', { rows: 2, placeholder: '我的背景：已经会什么、不会什么' });
  const goal = h('textarea', { rows: 2, placeholder: '学习目标：学完要能做到什么' });
  const hours = h('input', { type: 'number', value: 5, min: 1, max: 60 });
  const create = async () => {
    if (!topic.value.trim()) return toast('请填写主题', true);
    const p = await api.post('/api/learn/plans', { topic: topic.value.trim(), background: bg.value, goal: goal.value, hours_per_week: +hours.value || 5 });
    toast('已提交，Agent 正在检索资料生成计划（几分钟）');
    location.hash = `#learn/plan/${p.id}`;
  };
  el.append(h('div.card', {}, [h('h3', {}, '新建主题学习计划'), field('主题', topic), field('背景', bg), field('目标', goal),
    h('div.row', {}, [h('div', { style: { width: '160px' } }, field('每周小时', hours)), h('button.primary', { onclick: create }, '生成学习计划')])]));
  const plans = await api.get('/api/learn/plans');
  if (!plans.length) el.append(h('p.muted', {}, '还没有学习计划。'));
  const grid = h('div.grid');
  for (const p of plans) {
    watchJob(ctx, p.job_id, p.status);
    grid.append(h('div.card', { style: { cursor: 'pointer' }, onclick: () => { location.hash = `#learn/plan/${p.id}`; } }, [
      h('div.row', {}, [h('b', { style: { flex: 1 } }, p.topic), tag(h, p.status)]),
      h('div.learn-progress', {}, h('i', { style: { width: p.progress.pct + '%' } })),
      h('div.muted', {}, `${p.progress.done}/${p.progress.total} 步 · 约 ${p.progress.hours}h · 每周 ${p.hours_per_week}h`),
      p.goal ? h('div.muted', {}, '目标：' + p.goal.slice(0, 80)) : null,
    ]));
  }
  el.append(grid);
}

// ---------- B. 计划详情 ----------
async function renderPlan(el, ctx, pid) {
  const { api, h, md, toast, openChat } = ctx;
  const p = await api.get(`/api/learn/plans/${pid}`);
  const ref = `learn:plan:${pid}`;
  watchJob(ctx, p.job_id, p.status);
  const busy = ['generating', 'adapting'].includes(p.status);
  const adaptNote = h('input', { placeholder: '可选：给调整的补充说明，例如「第 4 阶段太难」「想多做实践」' });
  el.append(h('div.card', {}, [
    h('div.row', {}, [h('a', { href: '#learn/plans' }, '← 全部计划'), h('h3', { style: { flex: 1, margin: 0 } }, p.topic), tag(h, p.status)]),
    h('div.learn-progress', {}, h('i', { style: { width: p.progress.pct + '%' } })),
    h('div.muted', {}, `${p.progress.done}/${p.progress.total} 步完成（${p.progress.pct}%）· 约 ${p.progress.hours}h · 每周 ${p.hours_per_week}h`
      + (p.background ? ` · 背景：${p.background.slice(0, 60)}` : '') + (p.goal ? ` · 目标：${p.goal.slice(0, 60)}` : '')),
    h('div.row', { style: { marginTop: '8px' } }, [
      h('button', { onclick: () => openChat({ module: 'learn', ref, title: '计划：' + p.topic.slice(0, 16) }) }, '💬 讨论 / 让 Agent 改计划'),
      h('div', { style: { flex: 1 } }, adaptNote),
      h('button.primary', { disabled: busy || !p.steps.length, onclick: async () => {
        await api.post(`/api/learn/plans/${pid}/adapt`, { note: adaptNote.value.trim() }); toast('Agent 正在根据反馈调整计划'); ctx.refresh();
      } }, '根据反馈调整'),
      h('button.ghost', { disabled: busy, onclick: async () => {
        if (!confirm('重新生成会清空现有步骤与反馈，继续？')) return; await api.post(`/api/learn/plans/${pid}/regenerate`); ctx.refresh();
      } }, '重新生成'),
      h('button.ghost', { onclick: async () => { if (!confirm('删除计划？')) return; await api.del(`/api/learn/plans/${pid}`); location.hash = '#learn/plans'; } }, '删除'),
    ]),
    busy ? h('p.muted', {}, (p.status === 'generating' ? '计划生成中' : '计划调整中') + `（job ${p.job_id}），完成后自动刷新…`) : null,
  ]));
  if (p.overview_md) {
    el.append(h('details.card', { open: !p.steps.length || p.progress.done === 0 }, [h('summary', {}, '计划总览 / 调整记录'), md(p.overview_md)]));
  }
  for (const [no, name] of Object.entries(p.stages)) {
    const ss = p.steps.filter((s) => s.stage === +no);
    if (!ss.length) continue;
    const done = ss.filter((s) => s.status === 'done').length;
    el.append(h('div.card', {}, [h('h3', {}, `阶段 ${no} · ${name}`), h('span.muted', {}, ` ${done}/${ss.length}`),
      h('div', { style: { marginTop: '8px' } }, ss.map((s) => stepView(s, p, ctx)))]));
  }
}

function stepView(s, p, ctx) {
  const { api, h, md, toast } = ctx;
  const save = async (patch, msg) => { await api.patch(`/api/learn/steps/${s.id}`, patch); if (msg) toast(msg); ctx.refresh(); };
  const fb = h('textarea', { rows: 2, value: s.feedback || '', placeholder: '反馈：哪里没懂、太难/太简单、资源好不好' });
  const notes = h('textarea', { rows: 2, value: s.notes || '', placeholder: '学习笔记 / 检查题的回答' });
  const status = h('select', { style: { width: 'auto' }, onchange: () => save({ status: status.value }) },
    Object.entries(STEP_TXT).map(([k, v]) => h('option', { value: k, selected: s.status === k }, v)));
  const body = h('div.body', { style: { display: openSteps.has(s.id) || s.status === 'doing' ? '' : 'none' } }, [
    s.description ? md(s.description) : null,
    s.resources.length ? h('ul', {}, s.resources.map((r) => h('li', {}, [
      r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.title || r.url) : (r.title || ''),
      r.type ? h('span.tag', { style: { marginLeft: '6px' } }, r.type) : null,
      r.verified === false ? h('span.tag.warn', {}, '未核验') : null,
      r.why ? h('span.muted', {}, ' — ' + r.why) : null]))) : null,
    s.questions.length ? h('div', {}, [h('b', {}, '检查题'), h('ul', {}, s.questions.map((q) => h('li', {}, q)))]) : null,
    h('div.row', {}, [h('span.muted', {}, '理解度'), stars(h, s.understanding, (v) => save({ understanding: v }))]),
    fb, notes,
    h('div.row', { style: { marginTop: '6px' } }, [
      h('button.primary', { onclick: () => save({ feedback: fb.value, notes: notes.value }, '已保存') }, '保存反馈'),
      h('button', { onclick: async () => { await api.post(`/api/learn/steps/${s.id}/today`, {}); toast('已加入今日计划'); ctx.refresh(); } }, '加入今日计划'),
      h('button', { onclick: () => ctx.openChat({ module: 'learn', ref: `learn:plan:${p.id}`, title: '计划：' + p.topic.slice(0, 16),
        prefill: `关于步骤「${s.title}」（step_id=${s.id}）：` }) }, '就这步提问'),
      h('button.ghost', { onclick: async () => { if (!confirm('删除这一步？')) return; await api.del(`/api/learn/steps/${s.id}`); ctx.refresh(); } }, '删除'),
    ]),
  ]);
  const check = h('input', { type: 'checkbox', checked: s.status === 'done', onchange: () => save({ status: check.checked ? 'done' : 'doing' }) });
  return h('div.item.learn-step.' + s.status, {}, [
    h('div.head', {}, [check, h('b', { onclick: () => {
      const show = body.style.display === 'none'; body.style.display = show ? '' : 'none';
      if (show) openSteps.add(s.id); else openSteps.delete(s.id);
    } }, s.title),
      s.understanding ? h('span.muted', {}, '★'.repeat(s.understanding)) : null,
      h('span.muted', {}, `${s.est_hours}h`), status]),
    body,
  ]);
}
