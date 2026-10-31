// 深度学习：条目深读（论文 / GitHub）+ 主题学习计划。
// 路由：#learn（总览 + 智能输入框）、#learn/plans（同总览，滚到计划）、#learn/plan/<id>、#learn/item/<id>（笔记阅读）
import { annotate } from './_annotate.js';
const CSS = `
.ln-opts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: -4px 0 10px; }
.ln-opts .lbl { font-size: 12px; color: var(--muted); margin-right: 2px; }
.ln-pill { padding: 4px 12px; font-size: 13px; background: var(--panel); border-color: var(--line-2); max-width: 340px; }
.ln-pill span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ln-pill.empty { color: var(--muted); border-style: dashed; }
.ln-pill.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.ln-pill svg { width: 15px; height: 15px; color: var(--accent); }
.ln-edit { display: flex; gap: 8px; align-items: center; margin: -2px 0 12px; padding: 10px 12px; background: var(--panel);
  border: 1px solid var(--line); border-radius: var(--radius-sm); }
.ln-edit input { flex: 1; }
.ln-edit .muted { white-space: nowrap; }
.ln-back { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.ln-back svg { transform: rotate(180deg); width: 15px; height: 15px; }
.ln-card-click { cursor: pointer; transition: border-color .12s, transform .12s; }
.ln-card-click:hover { border-color: var(--accent); }
.ln-pcard h3 { font-size: 19px; margin: 2px 0 10px; }
.ln-pcard .next { font-size: 13px; margin-top: 8px; color: var(--text); }
.ln-pcard .next b { color: var(--accent); font-weight: 500; margin-right: 4px; }
.ln-icard { display: flex; flex-direction: column; }
.ln-icard h3 { font-size: 17px; line-height: 1.4; margin: 6px 0 6px; }
.ln-icard .tldr { white-space: pre-line; font-size: 13px; color: var(--muted); flex: 1; }
.ln-icard .foot { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line); }
.ln-badge { font-size: 11px; padding: 0 8px; border-radius: 6px; line-height: 20px; font-weight: 600; letter-spacing: .03em; }
.ln-badge.paper { background: var(--accent-soft); color: var(--accent); }
.ln-steps { margin-top: 10px; display: flex; flex-direction: column; gap: 3px; }
.ln-step { font: 12px/1.5 var(--mono); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ln-step:last-child { color: var(--accent); }
.ln-badge.github { background: var(--dark); color: var(--bg); }
.ln-stars { display: inline-flex; gap: 0; }
.ln-stars button { border: none; background: none; padding: 1px; color: var(--line-2); border-radius: 4px; }
.ln-stars button svg { width: 17px; height: 17px; }
.ln-stars button.on { color: var(--accent); } .ln-stars button.on svg { fill: var(--accent); }
.ln-stars button:hover { color: var(--accent); }
.ln-stars.ro svg { width: 13px; height: 13px; }
.ln-head h1 { font-size: 30px; }
.ln-meta { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-top: 10px; }
.ln-meta .pct { font: 700 22px var(--serif); color: var(--accent); }
.ln-meta .progress { flex: 1; min-width: 160px; }
.ln-stagecard h3 { font-size: 17px; margin: 0 0 18px; }
.ln-stages { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); }
.ln-stage { position: relative; text-align: center; cursor: pointer; padding: 0 4px; }
.ln-stage::before { content: ''; position: absolute; top: 9px; left: -50%; right: 50%; height: 1.5px; background: var(--line-2); }
.ln-stage:first-child::before { display: none; }
.ln-stage.reached::before { background: var(--accent); }
.ln-dot { position: relative; z-index: 1; width: 20px; height: 20px; margin: 0 auto 8px; border-radius: 50%; display: grid; place-items: center;
  background: var(--panel); border: 1.5px solid var(--line-2); }
.ln-dot svg { width: 12px; height: 12px; stroke-width: 3; color: #fff; }
.ln-stage.done .ln-dot { background: var(--accent); border-color: var(--accent); }
.ln-stage.cur .ln-dot { border-color: var(--accent); box-shadow: 0 0 0 5px var(--accent-ring); }
.ln-stage.cur .ln-dot::after { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.ln-stage .k { font-size: 12px; color: var(--muted); }
.ln-stage .n { font-size: 13px; line-height: 1.35; }
.ln-stage.cur .n, .ln-stage.cur .k { color: var(--accent); }
.ln-stage.empty { opacity: .5; cursor: default; }
.ln-stage:hover .n { color: var(--accent); }
.ln-adapt { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); }
.ln-adapt input { flex: 1; }
.ln-step { padding: 14px 18px; margin-bottom: 10px; }
.ln-step.done { background: var(--bg); box-shadow: none; }
.ln-step.done .ln-st-title { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--line-2); }
.ln-step.skipped { opacity: .55; box-shadow: none; }
.ln-step.cur { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
.ln-st-head { display: flex; gap: 10px; align-items: center; }
.ln-st-title { flex: 1; min-width: 0; font-weight: 600; font-size: 15px; cursor: pointer; }
.ln-check { width: 24px; height: 24px; padding: 0; justify-content: center; border-radius: 50%; border: 1.5px solid var(--line-2); background: var(--panel); flex: none; }
.ln-check svg { width: 14px; height: 14px; stroke-width: 2.6; color: transparent; }
.ln-check:hover svg { color: var(--accent); }
.ln-check.on { background: var(--accent); border-color: var(--accent); } .ln-check.on svg { color: #fff; }
.ln-st-head select { width: auto; font-size: 12px; padding: 2px 6px; border-radius: 8px; }
.ln-st-body { margin: 10px 0 0 34px; }
.ln-st-head .tg svg { transition: transform .15s; } .ln-step.open .ln-st-head .tg svg { transform: rotate(90deg); }
.ln-st-body .md { font-size: 14px; }
.ln-st-sub { font-size: 12px; color: var(--muted); margin: 12px 0 4px; letter-spacing: .03em; }
.ln-res { display: flex; gap: 8px; align-items: baseline; padding: 7px 10px; border-radius: var(--radius-sm); }
.ln-res:hover { background: var(--bg); }
.ln-res svg { width: 15px; height: 15px; color: var(--accent); align-self: center; }
.ln-res a { font-weight: 500; }
.ln-res .why { color: var(--muted); font-size: 13px; flex: 1; min-width: 0; }
.ln-q { display: flex; gap: 8px; padding: 4px 10px; font-size: 14px; }
.ln-q .no { color: var(--accent); font: 700 13px var(--serif); min-width: 18px; }
.ln-fb { display: flex; gap: 10px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
.ln-fb input { flex: 1; min-width: 220px; }
.ln-saved { font-size: 12px; color: var(--ok); }
.ln-st-actions { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.ln-reader { max-width: 780px; margin: 0 auto; }
.ln-reader .card { padding: 30px 40px; }
.ln-reader .md { font-size: 15.5px; line-height: 1.9; }
.ln-reader .md > :first-child { margin-top: 0; }
.ln-reader .md h1, .ln-reader .md h2, .ln-reader .md h3 { font-family: var(--serif); }
.ln-reader .md h2 { font-size: 21px; margin-top: 1.6em; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.ln-reader .md h3 { font-size: 17px; }
.ln-reader .md code { background: var(--bg-2); padding: 1px 5px; border-radius: 4px; }
.ln-reader .md pre code { background: none; padding: 0; }
.ln-tldr { background: var(--focus); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 22px; margin-bottom: 14px; }
.ln-tldr ul { margin: 6px 0 0; padding-left: 18px; } .ln-tldr li { margin: 3px 0; }
`;
const STATUS_TAG = { done: 'ok', active: 'ok', failed: 'err', running: 'warn', queued: 'warn', generating: 'warn', adapting: 'warn' };
const STATUS_TXT = { queued: '排队', running: '解析中', done: '完成', failed: '失败', generating: '生成中', active: '进行中', adapting: '调整中' };
const STEP_TXT = { todo: '待学', doing: '学习中', done: '已完成', skipped: '跳过' };
const BUSY = ['queued', 'running', 'generating', 'adapting'];
const DEF_KEY = 'ln-defaults';
let onAgentDone = null;
let current = null;
const watching = new Set();
const openSteps = new Set(); // 重绘时保持展开的步骤
const closedSteps = new Set(); // 用户手动收起的「当前步骤」

const loadDefaults = () => { try { return { hours: 5, background: '', ...JSON.parse(localStorage.getItem(DEF_KEY) || '{}') }; } catch { return { hours: 5, background: '' }; } };
const saveDefaults = (d) => { try { localStorage.setItem(DEF_KEY, JSON.stringify(d)); } catch { /* ignore */ } };

const page = {
  // 不用 ctx.refresh()：外壳的 route() 会把右侧对话切回板块总览，打断绑定 ref 的对话。
  // 自己的 refresh 先在离屏容器渲染再整体替换，保持滚动位置、无闪烁。
  async render(el, ctx0) {
    current = { el, ctx0 };
    const ctx = { ...ctx0, sub: location.hash.slice(1).split('/').slice(1), refresh: softRefresh };
    const { h } = ctx;
    document.getElementById('learn-css')?.remove();
    let style = document.getElementById('ln-css');
    if (!style) { style = h('style', { id: 'ln-css' }); document.head.append(style); }
    style.textContent = CSS;
    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = (e) => { if (e.detail?.module === 'learn' && location.hash.startsWith('#learn')) softRefresh(); };
    document.addEventListener('agent-done', onAgentDone);

    const [view, id] = ctx.sub;
    if (view === 'plan' && id) return renderPlan(el, ctx, +id);
    if (view === 'item' && id) return renderItem(el, ctx, +id);
    return renderHome(el, ctx, view === 'plans');
  },
};
export default page;

async function softRefresh() {
  if (!current || !location.hash.startsWith('#learn')) return;
  const { el, ctx0 } = current;
  const tmp = document.createElement('div');
  await page.render(tmp, ctx0);
  current.el = el;
  el.replaceChildren(...tmp.childNodes);
}

const tag = (h, status) => h('span.tag' + (STATUS_TAG[status] ? '.' + STATUS_TAG[status] : ''), {}, STATUS_TXT[status] || status);
const badge = (h, kind) => h('span.ln-badge.' + (kind === 'github' ? 'github' : 'paper'), {}, kind === 'github' ? 'REPO' : 'PAPER');

function watchJob(ctx, jobId, status) {
  if (!jobId || watching.has(jobId) || !BUSY.includes(status)) return;
  watching.add(jobId);
  ctx.api.waitJob(jobId, null, 4000).catch(() => {}).finally(() => { watching.delete(jobId); softRefresh(); });
}

function stars(h, ui, value, onset, { readonly = false } = {}) {
  const box = h('span.ln-stars' + (readonly ? '.ro' : ''), { title: readonly ? `评分 ${value}/5` : '理解度（再点一次取消）' });
  const draw = (v) => box.replaceChildren(...[1, 2, 3, 4, 5].map((i) => {
    if (readonly) { const ic = ui.icon('star'); ic.style.color = i <= v ? 'var(--accent)' : 'var(--line-2)'; if (i <= v) ic.style.fill = 'var(--accent)'; return ic; }
    return h('button' + (i <= v ? '.on' : ''), { onclick: (e) => { e.stopPropagation(); const nv = i === v ? 0 : i; draw(nv); onset(nv); } }, ui.icon('star'));
  }));
  draw(value);
  return box;
}

// ---------- 意图识别 ----------
function detectIntent(text) {
  const t = text.trim();
  if (!t) return null;
  let m;
  if ((m = t.match(/arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5})/i)) || (m = t.match(/^(?:arxiv:)?(\d{4}\.\d{4,5})(v\d+)?$/i))) {
    return { kind: 'paper', label: `论文 arXiv ${m[1]}`, url: `https://arxiv.org/abs/${m[1]}` };
  }
  if ((m = t.match(/(10\.\d{4,9}\/\S+)/)) && !/\s/.test(t)) return { kind: 'paper', label: `论文 DOI ${m[1]}`, url: t };
  if ((m = t.match(/github\.com\/([\w.-]+)\/([\w.-]+)/i))) {
    const repo = `${m[1]}/${m[2].replace(/\.git$/, '')}`;
    return { kind: 'github', label: `仓库 ${repo}`, url: `https://github.com/${repo}` };
  }
  if ((m = t.match(/https?:\/\/[^\s，。、）)]+/i))) {
    const link = m[0];
    const u = new URL(link);
    const pdf = /\.pdf($|\?)/i.test(link);
    const name = pdf ? u.pathname.split('/').pop() : u.hostname.replace(/^www\./, '') + (u.pathname.length > 1 ? u.pathname.slice(0, 30) : '');
    return { kind: u.hostname.includes('openreview') || pdf ? 'paper' : '', label: (pdf ? '论文 PDF ' : '链接 ') + name, url: link };
  }
  if (/^[\w.-]+\/[\w.-]+$/.test(t) && !/^\d/.test(t)) return { kind: 'github', label: `仓库 ${t}`, url: t };
  if (/^[~/]\S*$/.test(t)) return { kind: 'github', label: `本地目录 ${t}`, url: t };
  return null;
}

// ---------- 总览：智能输入框 + 计划 + 条目 ----------
async function renderHome(el, ctx, scrollToPlans) {
  const { api, h, toast, ui, ask } = ctx;
  const [items, plans] = await Promise.all([api.get('/api/learn/items'), api.get('/api/learn/plans')]);
  items.forEach((it) => watchJob(ctx, it.job_id, it.status));
  plans.forEach((p) => watchJob(ctx, p.job_id, p.status));
  const latestPlan = [...plans].filter((p) => p.status !== 'failed').sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))[0];

  const defs = loadDefaults();
  const opt = { background: defs.background, goal: '', hours: defs.hours, focus: '', kind: '', depth: 'quick' };
  let intent = 'plan';
  let target = null; // 识别出的链接
  const optsRow = h('div.ln-opts');
  const editRow = h('div');
  let editing = null;

  const box = ui.composer({
    placeholder: '粘贴 arXiv / PDF / DOI / GitHub 链接深读，或输入想系统学习的主题…', autofocus: true,
    modes: [{ id: 'auto', label: '自动' }, { id: 'item', label: '深读', placeholder: 'arXiv / PDF / DOI 链接，或 GitHub owner/repo' },
      { id: 'plan', label: '学习计划', placeholder: '想系统学习的主题，例如：世界模型、RL 用于 LLM 推理' },
      { id: 'ask', label: '问 Agent', placeholder: '问学习 Agent，例如：ReAct 和 Reflexion 的区别？' }],
    onSubmit: async (text) => {
      try {
        if (intent === 'ask') { ask(text); return; }
        if (intent === 'open') { location.hash = `#learn/item/${target.existing.id}`; return; }
        if (intent === 'item') {
          const url = target?.url || text;
          const it = await api.post('/api/learn/items', { url, kind: opt.kind || target?.kind || '', focus: opt.focus.trim(), depth: (opt.kind || target?.kind) === 'github' ? opt.depth : '' });
          toast('已开始后台深读，完成后自动刷新');
          opt.focus = ''; location.hash = `#learn/item/${it.id}`;
          return;
        }
        saveDefaults({ background: opt.background, hours: opt.hours });
        const p = await api.post('/api/learn/plans', { topic: text, background: opt.background, goal: opt.goal, hours_per_week: +opt.hours || 5 });
        toast('Agent 正在检索资料生成计划（几分钟）');
        location.hash = `#learn/plan/${p.id}`;
      } catch (e) { toast('提交失败：' + e.message, true); return false; }
    },
  });
  const ta = box.querySelector('textarea');

  const pill = (key, ic, label, value, placeholder) => h('button.ln-pill' + (value ? '' : '.empty') + (editing === key ? '.on' : ''), {
    title: placeholder, onclick: () => { editing = editing === key ? null : key; update(); if (editing) editRow.querySelector('input')?.focus(); },
  }, [ui.icon(ic), h('span', {}, value ? `${label}：${value}` : `+ ${label}`)]);

  const editor = () => {
    if (!editing) return null;
    const cfg = { background: ['我的背景', '已经会什么、不会什么（记住，下次默认）'], goal: ['学习目标', '学完要能做到什么'],
      focus: ['关注点', '例如：评测是否可靠 / 调度怎么实现'] }[editing];
    if (editing === 'hours') {
      return h('div.ln-edit', {}, [h('span.muted', {}, '每周投入'), ...[2, 3, 5, 8, 12].map((n) => h('button.sm' + (+opt.hours === n ? '.primary' : ''), {
        onclick: () => { opt.hours = n; saveDefaults({ background: opt.background, hours: n }); editing = null; update(); ta.focus(); } }, `${n}h`)),
      h('input', { type: 'number', min: 1, max: 60, value: opt.hours, style: { width: '80px', flex: 'none' },
        onkeydown: (e) => { if (e.key === 'Enter') { opt.hours = +e.target.value || 5; saveDefaults({ background: opt.background, hours: opt.hours }); editing = null; update(); ta.focus(); } } })]);
    }
    if (editing === 'kind') return null;
    const inp = h('input', { value: opt[editing], placeholder: cfg[1],
      onkeydown: (e) => {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { editing = null; update(); ta.focus(); }
      } });
    const commit = () => { opt[editing] = inp.value.trim(); if (editing === 'background') saveDefaults({ background: opt.background, hours: opt.hours }); editing = null; update(); ta.focus(); };
    return h('div.ln-edit', {}, [h('span.muted', {}, cfg[0]), inp, h('button.sm.primary', { onclick: commit }, '好'), h('span.muted', {}, 'Enter 确认 · Esc 取消')]);
  };

  const update = () => {
    const text = ta.value.trim();
    const mode = box.mode;
    const det = detectIntent(text);
    target = det;
    if (mode === 'ask') intent = 'ask';
    else if (mode === 'item') intent = 'item';
    else if (mode === 'plan') intent = 'plan';
    else intent = det ? 'item' : /[?？]$/.test(text) ? 'ask' : 'plan';
    const existing = intent === 'item' && det && items.find((it) => it.url.trim() === det.url.trim());
    if (existing) { intent = 'open'; target = { ...det, existing }; }
    let hint;
    if (!text) hint = mode === 'ask' ? 'Enter 发给学习 Agent' : mode === 'item' ? '粘贴链接，Enter 开始深读' : mode === 'plan' ? '输入主题，Enter 生成学习计划'
      : '链接 → 深读 · 主题 → 学习计划 · 问句 → 问 Agent';
    else if (intent === 'ask') hint = 'Enter → 问学习 Agent';
    else if (intent === 'open') hint = `已深读过「${(existing.title || existing.url).slice(0, 30)}」，Enter 打开笔记`;
    else if (intent === 'item') hint = `Enter → 将${(opt.kind || det?.kind) === 'github' && opt.depth !== 'full' ? '速读' : '深读'}${det ? det.label : '：' + text.slice(0, 40)}`;
    else hint = `Enter → 将生成「${text.slice(0, 24)}${text.length > 24 ? '…' : ''}」学习计划 · 每周 ${opt.hours}h`;
    box.setHint(hint);
    if (editing === 'focus' && intent !== 'item') editing = null;
    if (['background', 'goal', 'hours'].includes(editing) && intent !== 'plan') editing = null;
    const kindTxt = { '': '自动识别', paper: '论文', github: 'GitHub 项目' };
    optsRow.replaceChildren(...(intent === 'plan' ? [h('span.lbl', {}, '计划选项'),
      pill('background', 'user', '背景', opt.background, '我的背景'), pill('goal', 'bulb', '目标', opt.goal, '学习目标'),
      h('button.ln-pill' + (editing === 'hours' ? '.on' : ''), { onclick: () => { editing = editing === 'hours' ? null : 'hours'; update(); } }, [ui.icon('clock'), h('span', {}, `每周 ${opt.hours}h`)])]
      : intent === 'item' ? [h('span.lbl', {}, '深读选项'), pill('focus', 'search', '关注点', opt.focus, '关注点'),
        h('button.ln-pill', { title: '点击切换类型', onclick: () => { opt.kind = { '': 'paper', paper: 'github', github: '' }[opt.kind]; update(); } },
          [ui.icon('box'), h('span', {}, '类型：' + (opt.kind ? kindTxt[opt.kind] : det?.kind ? kindTxt[det.kind] + '（自动）' : '自动识别'))]),
        (opt.kind || det?.kind) === 'github' ? h('button.ln-pill' + (opt.depth === 'full' ? '.on' : ''), {
          title: '速读：几分钟出一份 markdown 笔记；完整教程：离线 HTML + 流程图 + 函数级讲解，通常 10–20 分钟',
          onclick: () => { opt.depth = opt.depth === 'full' ? 'quick' : 'full'; update(); } },
        [ui.icon('clock'), h('span', {}, opt.depth === 'full' ? '完整 HTML 教程（较慢）' : '速读笔记（几分钟）')]) : null]
        : []));
    editRow.replaceChildren(...[editor()].filter(Boolean));
  };
  ta.addEventListener('input', update);
  box.querySelector('.modes')?.addEventListener('click', () => setTimeout(update, 0));
  const setMode = (id) => { const i = ['auto', 'item', 'plan', 'ask'].indexOf(id); box.querySelectorAll('.modes button')[i]?.click(); };

  const plansSec = h('div', { id: 'ln-plans' });
  const totalSteps = plans.reduce((a, p) => a + p.progress.total, 0);
  const doneSteps = plans.reduce((a, p) => a + p.progress.done, 0);
  el.append(
    ui.pageHead('深度学习', `${items.length} 篇深读 · ${plans.length} 个学习计划 · 已完成 ${doneSteps}/${totalSteps} 步`),
    box, optsRow, editRow,
    ui.chips([
      { label: '继续上次的计划', icon: 'arrow', onClick: () => (latestPlan ? (location.hash = `#learn/plan/${latestPlan.id}`) : toast('还没有学习计划', true)) },
      { label: '深读一篇论文', icon: 'doc', onClick: () => { setMode('item'); box.focus(); } },
      { label: '给我一个学习计划', icon: 'plan', onClick: () => { setMode('plan'); box.focus(); } },
      { label: '根据反馈调整', icon: 'refresh', onClick: () => (latestPlan ? (location.hash = `#learn/plan/${latestPlan.id}/adapt`) : toast('还没有学习计划', true)) },
    ]),
  );
  update();

  plansSec.append(ui.section('学习计划', plans.length ? `${plans.length} 个` : ''),
    plans.length ? h('div.grid', {}, plans.map((p) => planCard(p, ctx))) : ui.empty('还没有学习计划', '在上面输入一个主题，Enter 即可生成'));
  el.append(plansSec,
    ui.section('论文与项目深读', items.length ? `${items.length} 篇` : ''),
    items.length ? h('div.grid', {}, items.map((it) => itemCard(it, ctx))) : ui.empty('还没有深读条目', '粘贴一个 arXiv / GitHub 链接试试'));
  if (scrollToPlans) setTimeout(() => plansSec.scrollIntoView({ block: 'start' }), 0);
}

function planCard(p, ctx) {
  const { h, ui } = ctx;
  return h('div.card.ln-pcard.ln-card-click', { onclick: () => { location.hash = `#learn/plan/${p.id}`; } }, [
    h('div.row.between', {}, [h('span.card-label', {}, `每周 ${p.hours_per_week}h · 约 ${p.progress.hours}h`), tag(h, p.status)]),
    h('h3', {}, p.topic),
    h('div.row', {}, [h('div.grow', {}, ui.progress(p.progress.pct)), h('span.muted', {}, `${p.progress.done}/${p.progress.total} · ${p.progress.pct}%`)]),
    p.goal ? h('div.muted.clamp2', { style: { marginTop: '8px' } }, '目标：' + p.goal) : null,
    BUSY.includes(p.status) ? h('div.muted.dots', { style: { marginTop: '6px' } }, p.status === 'generating' ? 'Agent 正在生成计划' : 'Agent 正在调整计划') : null,
  ]);
}

function itemCard(it, ctx) {
  const { h, ui, openChat } = ctx;
  const busy = BUSY.includes(it.status);
  const go = () => { location.hash = `#learn/item/${it.id}`; };
  return h('div.card.ln-icard.ln-card-click', { onclick: go }, [
    h('div.row', {}, [badge(h, it.kind), it.status !== 'done' ? tag(h, it.status) : null, h('span.grow'),
      it.rating ? stars(h, ui, it.rating, null, { readonly: true }) : null, h('span.muted', {}, (it.created_at || '').slice(5, 10))]),
    h('h3.serif.clamp2', {}, it.title || it.url),
    busy ? h('div.tldr.dots', {}, '后台解析中，完成后自动刷新')
      : it.status === 'failed' ? h('div.tldr', { style: { color: 'var(--err)' } }, '深读失败，可打开后重新生成')
        : h('div.tldr.clamp3', {}, (it.summary || '').replace(/^TL;DR[:：]?\s*/i, '') || '（无 TL;DR）'),
    h('div.foot', {}, [
      it.output_path ? h('button.sm.outline', { onclick: (e) => { e.stopPropagation(); go(); } }, [ui.icon('doc'), '打开笔记']) : null,
      h('button.sm.ghost', { onclick: (e) => { e.stopPropagation(); openChat({ module: 'learn', ref: `learn:item:${it.id}`, title: '追问：' + (it.title || it.url).slice(0, 20) }); } }, [ui.icon('chat'), '追问']),
      h('span.grow'),
      it.focus ? h('span.muted.clamp2', { style: { maxWidth: '45%', fontSize: '12px' } }, '关注：' + it.focus) : null,
    ]),
  ]);
}

// ---------- 条目阅读 ----------
async function renderItem(el, ctx, iid) {
  const { api, h, md, toast, ui, openChat } = ctx;
  let it;
  try { it = await api.get(`/api/learn/items/${iid}`); } catch { el.append(back(h, ui), ui.empty('条目不存在')); return; }
  watchJob(ctx, it.job_id, it.status);
  const busy = BUSY.includes(it.status);
  const isHtml = /\.html?$/i.test(it.output_path || '');
  const fileName = (it.output_path || '').split('/').pop();
  const ref = `learn:item:${it.id}`;
  const chat = () => openChat({ module: 'learn', ref, title: '追问：' + (it.title || it.url).slice(0, 20) });

  el.append(back(h, ui), h('div.ln-head', {}, ui.pageHead(it.title || it.url, h('span', {}, [
    badge(h, it.kind), ' ', h('a', { href: it.url.startsWith('http') ? it.url : '#learn', target: '_blank', rel: 'noopener' }, it.url),
    ` · ${(it.created_at || '').slice(0, 10)}`, it.focus ? ` · 关注：${it.focus}` : '']), [
    it.status !== 'done' ? tag(h, it.status) : null,
    h('button.primary', { onclick: chat }, [ui.icon('chat'), '继续追问']),
  ])));
  el.append(h('div.row', { style: { marginBottom: '16px' } }, [
    isHtml ? h('button.outline', { onclick: () => window.open(`/api/learn/items/${it.id}/out/${encodeURIComponent(fileName)}`, '_blank') }, [ui.icon('doc'), '打开 HTML 教程']) : null,
    it.kind === 'github' && it.output_path ? h('button', { onclick: () => window.open(`/api/learn/items/${it.id}/out/summary.md`, '_blank') }, 'summary.md') : null,
    it.kind === 'github' && !busy && it.output_path && !isHtml ? h('button.outline', { title: '离线 HTML + 流程图 + 函数级讲解，通常 10–20 分钟',
      onclick: async () => { await api.post(`/api/learn/items/${it.id}/rerun`, { depth: 'full' }); toast('已开始生成完整教程'); softRefresh(); } }, [ui.icon('doc'), '生成完整 HTML 教程']) : null,
    h('span.grow'),
    it.job_id ? h('a.muted', { href: `/api/jobs/${it.job_id}`, target: '_blank' }, `job ${it.job_id}`) : null,
    h('button.ghost', { disabled: busy, onclick: async () => { if (!confirm('重新生成会覆盖产物，继续？')) return; await api.post(`/api/learn/items/${it.id}/rerun`, {}); toast('已重新开始深读'); softRefresh(); } }, [ui.icon('refresh'), '重新生成']),
    h('button.ghost', { onclick: async () => { if (!confirm('删除该条目？（产物文件保留）')) return; await api.del(`/api/learn/items/${it.id}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除']),
  ]));

  const reader = h('div.ln-reader');
  el.append(reader);
  const lines = (it.summary || '').split('\n').map((s) => s.replace(/^[-*•]\s*/, '').trim()).filter(Boolean);
  const tldrBox = lines.length ? h('div.ln-tldr', {}, [h('span.card-label', {}, 'TL;DR'), h('ul', {}, lines.map((l) => h('li', {}, l)))]) : null;

  if (busy || it.status === 'failed' || !it.output_path) { if (tldrBox) reader.append(tldrBox); }
  if (busy) {
    // 实时进度：已用时 + Agent 最近几步（读了哪些文件、跑了什么命令）
    const steps = h('div.ln-steps');
    const head = h('div.serif', {}, '后台深读中');
    reader.append(h('div.card', {}, [h('div.row', {}, [head, h('span.grow'), h('span.muted', {}, (it.depth || 'quick') === 'quick' && it.kind === 'github' ? '速读 · 通常几分钟' : it.kind === 'github' ? '完整教程 · 通常 10–20 分钟' : '论文深读 · 通常 2–5 分钟')]), steps]));
    const tick = async () => {
      if (!steps.isConnected) return;
      const j = await api.get(`/api/jobs/${it.job_id}`).catch(() => null);
      if (!j) return;
      const mins = ((Date.now() - new Date(j.started_at || j.created_at).getTime()) / 60000).toFixed(1);
      head.textContent = `后台深读中 · 已用 ${mins} 分钟`;
      const lines = (j.log || '').split('\n').filter(Boolean).slice(-6).map((l) => l.replace(/^\[tool\]\s*/, '').replace(/\/Users\/[^ ]*\/data\/learn\/[^/]+\//g, ''));
      steps.replaceChildren(...(lines.length ? lines.map((l) => h('div.ln-step', { title: l }, l)) : [h('div.muted', {}, h('span.dots', {}, '准备中'))]));
      if (['queued', 'running'].includes(j.status)) setTimeout(tick, 4000);
    };
    tick();
  }
  else if (it.status === 'failed') reader.append(h('div.card', {}, ui.empty('深读失败', '点「重新生成」再试一次，或看 job 日志')));
  else if (it.output_path) {
    let text = null;
    if (!isHtml) text = await api.get(`/api/learn/items/${it.id}/file`).catch(() => null);
    else if (it.kind === 'github') text = await api.get(`/api/learn/items/${it.id}/out/summary.md`).catch(() => null);
    const hasNote = typeof text === 'string' && text.trim();
    if (tldrBox && !(hasNote && /TL;?DR/i.test(text.slice(0, 3000)))) reader.append(tldrBox);
    if (hasNote) {
      const note = text.replace(/^---[\s\S]*?---\s*/, '');
      reader.append(h('div.card', {}, annotate(ctx, md(note), { doc: `learn:item:${it.id}`, title: it.title || it.url, link: `#learn/item/${it.id}`, source: note })));
    }
    else if (isHtml) reader.append(h('div.card', {}, ui.empty('这是一份 HTML 教程', '点上方「打开 HTML 教程」在新标签页阅读')));
  }

  // 我的笔记 / 评分
  let rating = it.rating || 0;
  const notes = h('textarea', { rows: 4, value: it.my_notes || '', placeholder: '我的笔记 / 认识（⌘+Enter 保存）' });
  const saved = h('span.ln-saved');
  const saveNotes = async () => { await api.patch(`/api/learn/items/${it.id}`, { my_notes: notes.value, rating }); saved.textContent = '已保存 ✓'; setTimeout(() => { saved.textContent = ''; }, 2000); };
  notes.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveNotes(); } });
  reader.append(ui.section('我的笔记'), h('div.card', {}, [notes,
    h('div.row', { style: { marginTop: '10px' } }, [h('span.muted', {}, '评分'), stars(h, ui, rating, (v) => { rating = v; saveNotes(); }), h('span.grow'), saved,
      h('button.primary', { onclick: saveNotes }, [ui.icon('check'), '保存'])])]));
}

const back = (h, ui, href = '#learn', label = '深度学习') => h('a.ln-back', { href }, [ui.icon('arrow'), label]);

// ---------- 计划详情 ----------
async function renderPlan(el, ctx, pid) {
  const { api, h, md, toast, ui, openChat } = ctx;
  let p;
  try { p = await api.get(`/api/learn/plans/${pid}`); } catch { el.append(back(h, ui), ui.empty('计划不存在')); return; }
  const ref = `learn:plan:${pid}`;
  const chatTitle = '计划：' + p.topic.slice(0, 16);
  watchJob(ctx, p.job_id, p.status);
  const busy = ['generating', 'adapting'].includes(p.status);

  // 阶段状态
  const stageInfo = Object.entries(p.stages).map(([no, name]) => {
    const ss = p.steps.filter((s) => s.stage === +no);
    const done = ss.filter((s) => s.status === 'done').length;
    const closed = ss.filter((s) => s.status === 'done' || s.status === 'skipped').length;
    return { no: +no, name, ss, done, isDone: ss.length > 0 && closed === ss.length, hours: ss.reduce((a, s) => a + (+s.est_hours || 0), 0) };
  });
  const cur = stageInfo.find((s) => s.ss.length && !s.isDone);
  const curStep = p.steps.find((s) => s.status === 'doing') || p.steps.find((s) => s.status === 'todo');

  el.append(back(h, ui), h('div.ln-head', {}, ui.pageHead(p.topic,
    [p.background ? `背景：${p.background}` : '', p.goal ? `目标：${p.goal}` : ''].filter(Boolean).join(' · '), [
      tag(h, p.status),
      h('button.primary', { onclick: () => openChat({ module: 'learn', ref, title: chatTitle }) }, [ui.icon('chat'), '讨论 / 改计划']),
    ])));
  el.append(h('div.ln-meta', { style: { marginTop: '-4px', marginBottom: '16px' } }, [
    h('span.pct', {}, `${p.progress.pct}%`), ui.progress(p.progress.pct),
    h('span', {}, `${p.progress.done}/${p.progress.total} 步`), h('span', {}, [ui.icon('clock'), ` 约 ${p.progress.hours}h`]),
    h('span', {}, `每周 ${p.hours_per_week}h`),
    p.progress.hours && p.hours_per_week ? h('span', {}, `≈ ${Math.ceil(p.progress.hours / p.hours_per_week)} 周`) : null,
  ]));

  // 阶段时间线 + 调整
  const adaptNote = h('input', { placeholder: '怎么调整？如「第 4 阶段太难」「想多做实践」· Enter 提交', title: '会结合每步的反馈与理解度一起调整',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); doAdapt(); } } });
  const doAdapt = async () => {
    if (busy || !p.steps.length) return;
    await api.post(`/api/learn/plans/${pid}/adapt`, { note: adaptNote.value.trim() });
    toast('Agent 正在根据反馈调整计划'); softRefresh();
  };
  el.append(h('div.card.ln-stagecard', {}, [
    h('h3', {}, busy ? (p.status === 'generating' ? '计划生成中…' : '计划调整中…') : cur ? `当前阶段 · ${cur.name}` : p.steps.length ? '全部阶段已完成' : '暂无步骤'),
    h('div.ln-stages', {}, stageInfo.map((s, i) => {
      const prevDone = i > 0 && stageInfo[i - 1].isDone;
      const cls = [s.isDone ? 'done' : '', cur && s.no === cur.no ? 'cur' : '', (s.isDone || (cur && s.no === cur.no)) && (i === 0 || prevDone) ? 'reached' : '', s.ss.length ? '' : 'empty'].filter(Boolean).join('.');
      return h('div.ln-stage' + (cls ? '.' + cls : ''), { onclick: () => s.ss.length && document.getElementById(`ln-stage-${s.no}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [
        h('div.ln-dot', {}, s.isDone ? ui.icon('check') : null),
        h('div.k', {}, `阶段 ${s.no}${s.ss.length ? ` · ${s.done}/${s.ss.length}` : ''}`),
        h('div.n', {}, s.name),
      ]);
    })),
    h('div.ln-adapt', {}, [adaptNote,
      h('button.primary', { disabled: busy || !p.steps.length, onclick: doAdapt }, [ui.icon('refresh'), '根据反馈调整']),
      h('button.ghost', { disabled: busy, onclick: async () => {
        if (!confirm('重新生成会清空现有步骤与反馈，继续？')) return; await api.post(`/api/learn/plans/${pid}/regenerate`); softRefresh();
      } }, '重新生成'),
      h('button.ghost', { onclick: async () => { if (!confirm('删除计划？')) return; await api.del(`/api/learn/plans/${pid}`); location.hash = '#learn'; } }, [ui.icon('trash'), '删除']),
    ]),
    busy ? h('div.muted.dots', { style: { marginTop: '8px' } }, `job ${p.job_id} 运行中，完成后自动刷新`) : null,
  ]));
  if (ctx.sub[2] === 'adapt') setTimeout(() => { adaptNote.focus(); history.replaceState(null, '', `#learn/plan/${pid}`); }, 30);

  if (p.overview_md) {
    el.append(h('details.card.flat', { open: !p.steps.length }, [h('summary', {}, '计划总览 / 调整记录'),
      annotate(ctx, md(p.overview_md), { doc: `learn:plan:${pid}`, title: `${p.topic} · 计划总览`, link: `#learn/plan/${pid}`, source: p.overview_md })]));
  }
  for (const s of stageInfo) {
    if (!s.ss.length) continue;
    el.append(h('div', { id: `ln-stage-${s.no}`, style: { scrollMarginTop: '16px' } }, ui.section(`阶段 ${s.no} · ${s.name}`, `${s.done}/${s.ss.length} · ${s.hours}h`)));
    s.ss.forEach((st) => el.append(stepView(st, p, ctx, curStep && st.id === curStep.id)));
  }
}

function stepView(s, p, ctx, isCur) {
  const { api, h, md, toast, ui } = ctx;
  const save = async (patch, msg) => { await api.patch(`/api/learn/steps/${s.id}`, patch); if (msg) toast(msg); softRefresh(); };
  const saved = h('span.ln-saved');
  const flash = (t = '已保存 ✓') => { saved.textContent = t; setTimeout(() => { saved.textContent = ''; }, 2000); };
  const quiet = async (patch) => { await api.patch(`/api/learn/steps/${s.id}`, patch); flash(); };

  const fb = h('input', { value: s.feedback || '', placeholder: '一句话反馈：哪里没懂、太难/太简单、资源好不好…  Enter 保存',
    onkeydown: (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); quiet({ feedback: fb.value }); } } });
  const notes = h('textarea', { rows: 2, value: s.notes || '', placeholder: '学习笔记 / 检查题的回答（离开输入框自动保存）',
    onchange: () => quiet({ notes: notes.value }) });
  const status = h('select', { title: '状态', onclick: (e) => e.stopPropagation(), onchange: () => save({ status: status.value }) },
    Object.entries(STEP_TXT).map(([k, v]) => h('option', { value: k, selected: s.status === k }, v)));
  const expanded = openSteps.has(s.id) || ((isCur || s.status === 'doing') && !closedSteps.has(s.id));
  const body = h('div.ln-st-body', { style: { display: expanded ? '' : 'none' } }, [
    s.description ? annotate(ctx, md(s.description), { doc: `learn:step:${s.id}`, title: `${p.topic} · ${s.title}`, link: `#learn/plan/${p.id}`, source: s.description, compact: true }) : null,
    s.resources.length ? h('div.ln-st-sub', {}, '资源') : null,
    ...s.resources.map((r) => h('div.ln-res', {}, [ui.icon(r.type === 'code' || /github/.test(r.url || '') ? 'box' : r.type === 'video' ? 'bolt' : 'link'),
      h('div.why', {}, [r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.title || r.url) : h('b', {}, r.title || ''),
        r.why ? h('span', {}, ' — ' + r.why) : null]),
      r.type ? h('span.tag.gray', {}, r.type) : null,
      r.verified === false ? h('span.tag.warn', {}, '未核验') : null])),
    s.questions.length ? h('div.ln-st-sub', {}, '检查题 · 能答上来再打勾') : null,
    ...s.questions.map((q, i) => h('div.ln-q', {}, [h('span.no', {}, i + 1), h('span', {}, q)])),
    h('div.ln-fb', {}, [h('span.muted', {}, '理解度'), stars(h, ui, s.understanding, (v) => quiet({ understanding: v })), fb, saved]),
    h('div', { style: { marginTop: '8px' } }, notes),
    h('div.ln-st-actions', {}, [
      h('button.outline', { onclick: async () => { await api.post(`/api/learn/steps/${s.id}/today`, {}); toast('已加入今日计划'); softRefresh(); } }, [ui.icon('plan'), '加入今日计划']),
      h('button', { onclick: () => ctx.openChat({ module: 'learn', ref: `learn:plan:${p.id}`, title: '计划：' + p.topic.slice(0, 16),
        prefill: `关于步骤「${s.title}」（step_id=${s.id}）：` }) }, [ui.icon('chat'), '继续追问']),
      h('span.grow'),
      h('button.ghost.sm', { onclick: async () => { if (!confirm('删除这一步？')) return; await api.del(`/api/learn/steps/${s.id}`); softRefresh(); } }, [ui.icon('trash'), '删除']),
    ]),
  ]);
  const toggle = () => {
    const show = body.style.display === 'none'; body.style.display = show ? '' : 'none';
    if (show) { openSteps.add(s.id); closedSteps.delete(s.id); } else { openSteps.delete(s.id); closedSteps.add(s.id); }
    card.classList.toggle('open', show);
  };
  const done = s.status === 'done';
  const card = h('div.card.ln-step.' + s.status + (isCur ? '.cur' : '') + (expanded ? '.open' : ''), {}, [
    h('div.ln-st-head', {}, [
      h('button.ln-check' + (done ? '.on' : ''), { title: done ? '标记为未完成' : '标记完成', onclick: () => save({ status: done ? 'doing' : 'done' }, done ? '' : '完成一步 ✓') }, ui.icon('check')),
      h('span.ln-st-title', { onclick: toggle }, s.title),
      isCur ? h('span.tag', {}, '当前') : null,
      s.understanding && !expanded ? stars(h, ui, s.understanding, null, { readonly: true }) : null,
      h('span.muted', {}, `${s.est_hours}h`), status,
      h('button.icon.tg', { title: '展开 / 收起', onclick: toggle }, ui.icon('arrow')),
    ]),
    body,
  ]);
  return card;
}
