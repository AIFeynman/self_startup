// 规划：每日事项录入 → AI 拆解 → 排程（专注窗 / 人车道 / Agent 车道）→ 可选让 Agent 自动执行
// 输入：一个大 composer，每行一个顶层事项，支持轻量行内语法（见 parseLine）。
import { today } from '../api.js';

const CSS = `
.pl-head { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.pl-steps { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); white-space: nowrap; }
.pl-steps .st { display: inline-flex; align-items: center; gap: 6px; }
.pl-steps .n { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--line-2); display: grid; place-items: center;
  font: 600 12px var(--serif); color: var(--muted); background: var(--panel); }
.pl-steps .st.done .n { border-color: var(--accent); color: var(--accent); }
.pl-steps .st.done { color: var(--text); }
.pl-steps .st.cur .n { background: var(--accent); border-color: var(--accent); color: #fff; }
.pl-steps .st.cur { color: var(--accent); font-weight: 600; }
.pl-steps .sep { width: 18px; border-top: 1px dashed var(--line-2); }
.pl-date { display: flex; align-items: center; gap: 4px; }
.pl-date input { width: auto; padding: 3px 8px; border-radius: 999px; font-size: 13px; background: transparent; }
.pl-date button { padding: 3px 10px; font-size: 13px; }
.pl-preview { display: flex; flex-direction: column; gap: 4px; margin: -6px 4px 10px; font-size: 12px; }
.pl-preview .ln { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.pl-preview .ln b { font-weight: 600; font-size: 13px; }
.pl-preview .ln .goal { color: var(--muted); }
.pl-preview .tag { margin-right: 0; }
.pl-syntax { color: var(--muted); font-size: 12px; margin: -8px 4px 10px; }
.pl-syntax code { background: var(--bg-2); padding: 0 4px; border-radius: 4px; font-size: 11px; }
.pl-opts { display: flex; justify-content: center; align-items: center; gap: 10px; flex-wrap: wrap; margin: 2px 0 6px; font-size: 13px; color: var(--muted); }
.pl-opts input[type=text] { width: 240px; padding: 3px 12px; border-radius: 999px; font-size: 12px; background: transparent; }
.pl-opts label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.pl-job { text-align: center; color: var(--muted); font-size: 12px; min-height: 18px; }
.pl-job:empty { display: none; }
.pl-warn { margin-top: -4px; margin-bottom: 14px; font-size: 13px; display: flex; flex-direction: column; gap: 4px; }
.pl-list { padding: 6px 8px; }
.pl-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) auto; gap: 14px; padding: 14px 12px; border-radius: 12px; position: relative; }
.pl-list > .pl-row + .pl-row { border-top: 1px solid var(--line); }
.pl-row.p1 { background: linear-gradient(90deg, var(--accent-soft), transparent 70%); }
.pl-row.p1::before { content: ''; position: absolute; left: 0; top: 14px; height: 48px; width: 3px; border-radius: 3px; background: var(--accent); }
.pl-row.done .pl-title { text-decoration: line-through; color: var(--muted); }
.pl-num { font: 400 30px/1.1 var(--serif); color: var(--muted); padding-top: 2px; }
.pl-row.p1 .pl-num { color: var(--accent); }
.pl-title { font: 700 17px/1.4 var(--serif); }
.pl-title .meta { font: 400 12px var(--font); color: var(--muted); margin-left: 8px; }
.pl-goal { color: var(--muted); font-size: 13px; margin-top: 2px; }
.pl-goal b { font-weight: 500; color: var(--text); opacity: .7; }
.pl-pills { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
.pl-pill { appearance: none; -webkit-appearance: none; width: auto; border: 1px solid var(--line-2); border-radius: 999px; background: var(--panel);
  padding: 1px 10px; font-size: 12px; line-height: 20px; color: var(--muted); cursor: pointer; }
.pl-pill:hover { border-color: var(--accent); }
select.pl-pill.hot { background: var(--accent); border-color: var(--accent); color: #fff; }
select.pl-pill.heavy { background: var(--accent-soft); border-color: transparent; color: var(--accent); }
select.pl-pill.auto { background: var(--ok-soft); border-color: transparent; color: var(--ok); }
select.pl-pill.agent { border-color: var(--ok); color: var(--ok); }
select.pl-pill.ok { background: var(--ok-soft); border-color: transparent; color: var(--ok); }
input.pl-pill { width: 64px; cursor: text; text-align: center; }
.pl-side { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.pl-time { font: 600 13px var(--serif); color: var(--text); white-space: nowrap; }
.pl-time.none { color: var(--muted); font: 400 12px var(--font); }
.pl-acts { display: flex; gap: 4px; align-items: center; }
.pl-acts button.launch { background: var(--dark); color: var(--bg); border-color: var(--dark); padding: 4px 14px; font-size: 13px; }
.pl-kids-t { margin-top: 8px; padding: 2px 8px; font-size: 12px; }
.pl-kids { margin-top: 8px; display: flex; flex-direction: column; border-left: 1.5px solid var(--line-2); margin-left: 4px; }
.pl-kid { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; gap: 10px; padding: 8px 6px 8px 12px; border-radius: 10px; }
.pl-kid + .pl-kid { border-top: 1px dashed var(--line); }
.pl-kid.auto { background: var(--auto); }
.pl-kid .pl-num { font-size: 15px; padding-top: 1px; }
.pl-kid .pl-title { font: 600 14px var(--font); }
.pl-kid .pl-pills { margin-top: 4px; }
.pl-notes { margin-top: 6px; font-size: 12px; }
.pl-notes pre { margin: 4px 0 0; }

.pl-tl-card { padding: 16px 16px 18px; }
.pl-legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.pl-legend i { display: inline-block; width: 14px; height: 10px; border-radius: 3px; vertical-align: -1px; margin-right: 4px; }
.pl-tl { display: flex; gap: 8px; position: relative; overflow-x: auto; }
.pl-axis { width: 44px; flex: none; position: relative; font: 11px var(--serif); color: var(--muted); }
.pl-axis span { position: absolute; right: 4px; transform: translateY(-50%); }
.pl-lane { flex: 1; min-width: 150px; position: relative; border-radius: 12px; background: var(--bg); }
.pl-lane > h4 { position: sticky; top: 0; margin: 0; padding-top: 2px; font: 600 12px var(--font); text-align: center; color: var(--muted);
  display: flex; align-items: center; justify-content: center; gap: 4px; }
.pl-lane > h4 svg { width: 14px; height: 14px; }
.pl-band { position: absolute; left: 0; right: 0; background: var(--focus); border-top: 1px solid var(--accent-soft); border-bottom: 1px solid var(--accent-soft); pointer-events: none; }
.pl-hr { position: absolute; left: 6px; right: 6px; border-top: 1px dashed var(--line); }
.pl-blk { position: absolute; left: 5px; right: 5px; padding: 2px 7px; font-size: 11px; line-height: 1.3; overflow: hidden; cursor: default;
  background: var(--panel); border: 1px solid var(--line-2); border-radius: 8px; box-shadow: 0 1px 2px rgba(60, 40, 20, .05); }
.pl-blk b { font-weight: 600; }
.pl-blk .muted { font-size: 10px; }
.pl-blk.heavy { border-left: 3px solid var(--accent); }
.pl-blk.agent { background: var(--auto); border-color: transparent; border-left: 3px solid var(--ok); }
.pl-blk.kick, .pl-blk.review { background: var(--auto); border: 1px dashed var(--ok); font-size: 10px; line-height: 1.1; padding: 0 6px; opacity: .9; }
.pl-blk.done { opacity: .45; text-decoration: line-through; }
.pl-blk.flag { border-color: var(--warn); border-left-color: var(--warn); }
.pl-now { position: absolute; left: 0; right: 0; border-top: 2px solid var(--accent); z-index: 2; }
.pl-now::before { content: ''; position: absolute; left: -3px; top: -5px; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
`;
const LEVEL = { heavy: '重度', medium: '中度', light: '轻度', auto: '自动' };
const EXEC = { human: '人', claude: 'Claude', codex: 'Codex', mixed: '混合' };
const STATUS = { todo: '待办', doing: '进行中', done: '完成', partial: '部分', dropped: '放弃' };
const KIND = { work: '工作', learning: '学习', life: '生活' };
const PRIO = { 1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4' };
const PX = 1.8; // 每分钟像素
const KIND_ALIAS = { 学习: 'learning', learn: 'learning', learning: 'learning', 生活: 'life', life: 'life', 工作: 'work', work: 'work' };
const AT_ALIAS = { auto: ['human_level', 'auto'], 自动: ['human_level', 'auto'], 重: ['human_level', 'heavy'], heavy: ['human_level', 'heavy'],
  中: ['human_level', 'medium'], medium: ['human_level', 'medium'], 轻: ['human_level', 'light'], light: ['human_level', 'light'],
  claude: ['executor', 'claude'], codex: ['executor', 'codex'], 人: ['executor', 'human'], human: ['executor', 'human'], mixed: ['executor', 'mixed'] };

const mins = (s) => { const [a, b] = (s || '0:0').split(':').map(Number); return a * 60 + b; };
const pad2 = (n) => String(n).padStart(2, '0');

/**
 * 解析一行：`写周报 P1 60m #学习 @重 @claude >交给老板前定稿`
 * P1..P4 优先级；60m / 1.5h / 90分钟 预计时长；#学习/#生活/#工作 类别；@auto/@重/@中/@轻 人干预度；@claude/@codex/@人 执行者；> 之后是目标。
 */
export function parseLine(line) {
  let s = line.replace(/^\s*(?:[-*•]|\d+[.、)])\s+/, '').trim();
  const out = {};
  const gi = s.search(/[>＞]/);
  if (gi >= 0) { out.goal = s.slice(gi + 1).trim(); s = s.slice(0, gi); }
  const rest = [];
  for (const tok of s.split(/\s+/).filter(Boolean)) {
    let m;
    if ((m = tok.match(/^[Pp]([1-4])$/))) out.priority = +m[1];
    else if ((m = tok.match(/^(\d+(?:\.\d+)?)(m|min|分钟|分)$/i))) out.est_minutes = Math.round(+m[1]);
    else if ((m = tok.match(/^(\d+(?:\.\d+)?)(h|hr|小时)$/i))) out.est_minutes = Math.round(+m[1] * 60);
    else if ((m = tok.match(/^[#＃](.+)$/)) && KIND_ALIAS[m[1].toLowerCase()]) out.kind = KIND_ALIAS[m[1].toLowerCase()];
    else if ((m = tok.match(/^[@＠](.+)$/)) && AT_ALIAS[m[1].toLowerCase()]) { const [k, v] = AT_ALIAS[m[1].toLowerCase()]; out[k] = v; }
    else rest.push(tok);
  }
  out.title = rest.join(' ').trim();
  if (out.est_minutes !== undefined && out.est_minutes < 5) out.est_minutes = 5;
  return out;
}

let onAgentDone;
const collapsed = new Set(); // 折叠的父事项 id（跨重绘保留）
const watching = new Set(); // 已在轮询的 job id

export default {
  async render(el, ctx) {
    const { api, h, toast, openChat, ui } = ctx;
    if (!document.getElementById('pl-css')) document.head.append(h('style', { id: 'pl-css' }, CSS));
    document.getElementById('plan-css')?.remove();
    const state = { date: today(), runs: [], data: null };

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && load();
    document.addEventListener('agent-done', onAgentDone);

    const askDay = (text) => (state.date === today() ? ctx.ask(text)
      : openChat({ module: 'plan', ref: `plan:${state.date}`, title: ctx.title || '规划', send: text }));
    const patch = async (id, body) => { await api.patch(`/api/tasks/${id}`, body); load(); };
    const pill = (map, cur, onchange, cls = '') => {
      const s = h('select.pl-pill' + (cls ? '.' + cls : ''), {}, Object.entries(map).map(([v, t]) => h('option', { value: v, selected: String(v) === String(cur) }, t)));
      s.onchange = () => onchange(s.value);
      return s;
    };

    // ---------- 静态骨架：页头 / 输入 / 快捷操作只建一次，load() 只换动态区，草稿不丢 ----------
    const head = h('div');
    const jobEl = h('div.pl-job');
    const body = h('div');
    const preview = h('div.pl-preview');
    const hint = h('input', { type: 'text', placeholder: 'AI 拆解补充要求（可选）' });
    const fromNow = h('input', { type: 'checkbox' });

    async function watch(jobId, label) {
      if (watching.has(jobId)) return;
      watching.add(jobId);
      jobEl.textContent = `${label}：排队中…`;
      try {
        const j = await api.waitJob(jobId, (j) => {
          const last = (j.log || '').trim().split('\n').pop() || '';
          jobEl.textContent = `${label}：${j.status} ${last.slice(0, 120)}`;
        });
        toast(j.status === 'done' ? `${label}完成` : `${label}失败`, j.status !== 'done');
      } finally { watching.delete(jobId); jobEl.textContent = ''; }
      if (el.isConnected) load();
    }

    const addLines = async (text) => {
      const items = text.split('\n').map(parseLine).filter((x) => x.title);
      if (!items.length) { toast('没有可添加的事项（标题为空）', true); return false; }
      for (const it of items) {
        await api.post('/api/tasks', { date: state.date, priority: 2, kind: 'work', est_minutes: 60, ...it });
      }
      toast(`已添加 ${items.length} 项`);
      preview.replaceChildren();
      load();
    };
    const decompose = async (taskIds) => {
      try {
        const r = await api.post('/api/plan/decompose', { date: state.date, hint: hint.value, ...(taskIds ? { task_ids: taskIds } : {}) });
        watch(r.job_id, taskIds ? 'AI 重新拆解' : 'AI 拆解');
      } catch (e) { toast(e.message, true); }
    };
    const schedule = async () => {
      const now = new Date();
      const from = fromNow.checked ? `${pad2(now.getHours())}:${pad2(now.getMinutes())}` : '';
      try { await api.post('/api/plan/schedule', { date: state.date, from_time: from }); toast('已排程'); load(); } catch (e) { toast(e.message, true); }
    };
    const carry = async () => {
      const r = await api.post('/api/plan/carry', { date: state.date });
      toast(r.from ? `从 ${r.from} 顺延 ${r.created.length} 项` : '没有可顺延的事项'); load();
    };

    const comp = ui.composer({
      placeholder: '每行一件事，例如：写周报 P1 60m #工作 @重 >下班前发出', autofocus: true, rows: 2,
      modes: [{ id: 'add', label: '加事项', placeholder: '每行一件事，例如：写周报 P1 60m #工作 @重 >下班前发出' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：把第一件事拆细一点 / 下午还能塞进什么？' }],
      hint: 'Enter 添加 · Shift+Enter 换行',
      onSubmit: (t, mode) => (mode === 'ask' ? askDay(t) : addLines(t)),
    });
    const ta = comp.querySelector('textarea');
    const renderPreview = () => {
      if (comp.mode === 'ask') return preview.replaceChildren();
      const lines = ta.value.split('\n').filter((l) => l.trim()).slice(0, 8).map(parseLine);
      preview.replaceChildren(...lines.map((p) => h('div.ln', {}, [
        h('b', {}, p.title || '（缺标题）'),
        h('span.tag' + (p.priority === 1 ? '' : '.line'), {}, `P${p.priority || 2}`),
        h('span.tag.line', {}, `${p.est_minutes || 60}m${p.est_minutes ? '' : '·默认'}`),
        p.kind ? h('span.tag.gray', {}, KIND[p.kind]) : null,
        p.human_level ? h('span.tag' + (p.human_level === 'auto' ? '.ok' : ''), {}, LEVEL[p.human_level]) : null,
        p.executor ? h('span.tag.ok', {}, EXEC[p.executor]) : null,
        p.goal ? h('span.goal', {}, '→ ' + p.goal) : null,
      ])));
    };
    ta.addEventListener('input', renderPreview);
    comp.querySelectorAll('.modes button').forEach((b) => b.addEventListener('click', () => setTimeout(renderPreview)));

    el.append(head, comp, preview,
      h('div.pl-syntax', {}, ['行内语法：', h('code', {}, 'P1'), ' ', h('code', {}, '60m'), ' ', h('code', {}, '1.5h'), ' ', h('code', {}, '#学习'), ' ',
        h('code', {}, '#生活'), ' ', h('code', {}, '@auto'), ' ', h('code', {}, '@重'), ' ', h('code', {}, '@轻'), ' ', h('code', {}, '@claude'), ' ',
        h('code', {}, '@codex'), ' ', h('code', {}, '>目标'), '　按 ', h('kbd', {}, '/'), ' 聚焦']),
      ui.chips([
        { label: '顺延昨天未完成', icon: 'refresh', onClick: carry },
        { label: 'AI 拆解全部', icon: 'spark', onClick: () => decompose() },
        { label: '一键排程', icon: 'clock', onClick: schedule },
        { label: '哪些能交给 Agent?', icon: 'robot', onClick: () => askDay('哪些事可以交给 Agent 自动跑？请按并行/依赖给出建议，并直接帮我改执行者和干预度。') },
      ]),
      h('div.pl-opts', {}, [hint, h('label', { title: '中途重排：只排当前时间之后' }, [fromNow, '排程从现在起']),
        h('button.ghost.sm', { onclick: () => openChat({ module: 'plan', ref: `plan:${state.date}`, title: ctx.title || '规划',
          prefill: '帮我看看今天的安排：优先级是否合理？哪些可以交给 Agent 并行？' }) }, [ui.icon('chat'), '讨论这一天'])]),
      jobEl, body);

    // ---------- 动态区 ----------
    async function load() {
      const d = await api.get(`/api/plan/day?date=${state.date}`);
      state.runs = d.runs; state.data = d;
      head.replaceChildren(pageHead(d));
      body.replaceChildren(...summary(d), ui.section('事项', d.tree.length ? `${d.tree.length} 项 · ${d.tasks.length - d.tree.length} 个子任务` : ''),
        items(d), ui.section('时间线', d.schedule ? `排程于 ${d.schedule.created_at.slice(11, 16) || d.schedule.created_at}（从 ${d.schedule.summary.from_time} 起）· 改了事项请重新排程` : ''),
        timeline(d));
      for (const j of d.jobs) watch(j.id, 'AI 拆解');
    }

    function pageHead(d) {
      const isToday = state.date === today();
      const date = h('input', { type: 'date', value: state.date });
      const setDate = (v) => { state.date = v; load(); };
      const shift = (n) => { const x = new Date(state.date + 'T00:00'); x.setDate(x.getDate() + n); setDate(x.toLocaleDateString('sv-SE')); };
      date.onchange = () => date.value && setDate(date.value);
      const done = [d.tasks.length > 0, d.tasks.some((t) => t.parent_id), !!d.schedule];
      const cur = done.indexOf(false);
      const step = (i, label) => h('span.st' + (done[i] ? '.done' : '') + (i === cur ? '.cur' : ''), {},
        [h('span.n', {}, done[i] && i !== cur ? '✓' : String(i + 1)), label]);
      const fw = d.config.focus_windows.map((w) => `${w.start}-${w.end}`).join('、');
      const wd = '日一二三四五六'[new Date(state.date + 'T00:00').getDay()];
      return ui.pageHead(isToday ? '今天做什么' : `${state.date.slice(5).replace('-', '月')}日做什么`,
        `周${wd} · 专注时间 ${fw} · 一天 ${d.config.day_start}-${d.config.day_end} · Agent 并发 ${d.config.max_agent_concurrency}（在「设置」修改）`,
        h('div.pl-head', {}, [
          h('div.pl-steps', {}, [step(0, '列事项'), h('span.sep'), step(1, 'AI 拆解'), h('span.sep'), step(2, '排程')]),
          h('div.pl-date', {}, [h('button.ghost', { onclick: () => shift(-1), title: '前一天' }, '‹'), date,
            h('button.ghost', { onclick: () => shift(1), title: '后一天' }, '›'),
            isToday ? null : h('button.outline', { onclick: () => setDate(today()) }, '回到今天')]),
        ]));
    }

    function summary(d) {
      const s = d.schedule?.summary;
      if (!s) return [];
      const pct = s.focus_capacity_minutes ? Math.round((100 * s.human_focus_minutes) / s.focus_capacity_minutes) : 0;
      return [
        ui.stats([
          { k: `人专注时间占用 · ${s.human_focus_minutes}/${s.focus_capacity_minutes} 分`, v: s.focus_capacity_minutes ? `${pct}%` : '—' },
          { k: '专注外人时间', v: `${s.human_outside_minutes} 分` },
          { k: 'Agent 时长', v: `${s.agent_minutes} 分` },
          { k: '并行度', v: s.parallel_ratio },
          { k: '峰值并发', v: `${s.agent_peak_concurrency} / ${s.lanes}` },
          { k: '已排', v: `${s.scheduled} 项` },
        ]),
        s.warnings.length ? h('div.pl-warn', {}, s.warnings.map((w) => h('div', {}, [h('span.tag.warn', {}, '注意'), w]))) : null,
      ].filter(Boolean);
    }

    function controls(t, isLeaf) {
      const est = h('input.pl-pill', { type: 'number', value: t.est_minutes, min: 5, step: 5, title: '预计分钟' });
      est.onchange = () => patch(t.id, { est_minutes: +est.value });
      const runs = state.runs.filter((r) => r.task_id === t.id);
      return h('div.pl-pills', {}, [
        pill(PRIO, t.priority, (v) => patch(t.id, { priority: +v }), t.priority === 1 ? 'hot' : ''),
        pill(LEVEL, t.human_level, (v) => patch(t.id, { human_level: v }), t.human_level === 'heavy' ? 'heavy' : t.human_level === 'auto' ? 'auto' : ''),
        pill(EXEC, t.executor, (v) => patch(t.id, { executor: v }), ['claude', 'codex'].includes(t.executor) ? 'agent' : ''),
        est, h('span.muted', {}, '分'),
        pill(STATUS, t.status, (v) => patch(t.id, { status: v, progress: v === 'done' ? 100 : t.progress }), t.status === 'done' ? 'ok' : ''),
        t.parallel_group ? h('span.tag.gray', {}, `并行组 ${t.parallel_group}`) : null,
        t.depends_on?.length ? h('span.tag.line', {}, `依赖 #${t.depends_on.join(',#')}`) : null,
        ...runs.slice(0, 1).map((r) => h(`span.tag.${r.status === 'done' ? 'ok' : r.status === 'running' ? 'gray' : 'warn'}`, { title: r.result || '' }, `Agent ${r.status}`)),
      ]);
    }

    function side(t, isLeaf) {
      const launch = async () => {
        try {
          const r = await api.post(`/api/plan/tasks/${t.id}/launch`, {});
          toast(`已派发给 Agent（job ${r.job_id}）`);
          load();
          watch(r.job_id, `执行「${t.title}」`);
        } catch (e) { toast(e.message, true); }
      };
      const canRun = isLeaf && (t.human_level === 'auto' || ['claude', 'codex'].includes(t.executor)) && t.status !== 'done';
      return h('div.pl-side', {}, [
        t.start_time ? h('span.pl-time', {}, `${t.start_time} – ${t.end_time}`) : h('span.pl-time.none', {}, '未排'),
        h('div.pl-acts', {}, [
          canRun ? h('button.launch', { onclick: launch, title: '让 Agent 自动执行（cwd = 代码库目录）' }, '🚀 执行') : null,
          h('button.icon', { title: '删除', onclick: async () => { if (confirm(`删除「${t.title}」${isLeaf ? '' : '及其子任务'}？`)) { await api.del(`/api/tasks/${t.id}`); load(); } } }, ui.icon('trash')),
        ]),
      ]);
    }

    const notes = (t) => (t.notes ? h('details.pl-notes', {}, [h('summary', {}, '备注 / Agent 结果'), h('pre', {}, t.notes)]) : null);
    const goal = (t) => (t.goal ? h('div.pl-goal', {}, [h('b', {}, '目标 '), t.goal]) : null);

    function items(d) {
      if (!d.tree.length) return h('div.card', {}, ui.empty(state.date === today() ? '今天还没有事项' : '这一天还没有事项', '在上面的输入框里每行写一件事，或点「顺延昨天未完成」'));
      const rows = d.tree.map((p, i) => {
        const kids = p.children || [];
        const leaf = !kids.length;
        const isCol = collapsed.has(p.id);
        const kidBox = leaf ? null : h('div.pl-kids', { style: { display: isCol ? 'none' : '' } }, kids.map((c, j) => h(`div.pl-kid${c.human_level === 'auto' ? '.auto' : ''}${c.status === 'done' ? '.done' : ''}`, {}, [
          h('div.pl-num', {}, `${i + 1}.${j + 1}`),
          h('div', {}, [h('div.pl-title', {}, [c.title, h('span.meta', {}, `#${c.id}`)]), goal(c), controls(c, true), notes(c)]),
          side(c, true),
        ])));
        const toggle = leaf ? null : h('button.ghost.pl-kids-t', { onclick: () => {
          const now = !collapsed.has(p.id);
          now ? collapsed.add(p.id) : collapsed.delete(p.id);
          kidBox.style.display = now ? 'none' : '';
          toggle.firstChild.textContent = `${now ? '▸' : '▾'} ${kids.length} 个子任务`;
        } }, [h('span', {}, `${isCol ? '▸' : '▾'} ${kids.length} 个子任务`)]);
        return h(`div.pl-row${p.priority === 1 ? '.p1' : ''}${p.status === 'done' ? '.done' : ''}`, {}, [
          h('div.pl-num', {}, pad2(i + 1)),
          h('div', {}, [
            h('div.pl-title', {}, [p.title, h('span.meta', {}, [`#${p.id}`, ' · ', KIND[p.kind] || p.kind, p.repo ? ` · ${p.repo}` : ''].join(''))]),
            goal(p), controls(p, leaf), notes(p),
            leaf ? null : h('div.row', {}, [toggle, h('button.ghost.sm', { onclick: () => decompose([p.id]) }, [ui.icon('spark'), '重新拆解'])]),
            kidBox,
          ]),
          side(p, leaf),
        ]);
      });
      return h('div.card.pl-list', {}, rows);
    }

    function timeline(d) {
      const cfg = d.config;
      const blocks = d.schedule?.blocks || [];
      if (!blocks.length) return h('div.card', {}, ui.empty('还没有排程', '列好事项 →（可选）AI 拆解 → 点「一键排程」'));
      // 只画有内容的时段：从最早的块（向下取整到整点）到最晚的块（向上取整），落在一天范围内
      const lo = Math.min(...blocks.map((b) => mins(b.start))), hi = Math.max(...blocks.map((b) => mins(b.end)));
      const t0 = Math.max(mins(cfg.day_start), Math.floor(lo / 60) * 60), t1 = Math.min(Math.max(mins(cfg.day_end), hi), Math.ceil(hi / 60) * 60);
      const y = (t) => (mins(t) - t0) * PX + 24;
      const H = (t1 - t0) * PX + 34;
      const byId = Object.fromEntries(d.tasks.map((t) => [t.id, t]));
      const nLanes = Math.max(cfg.max_agent_concurrency, ...blocks.filter((b) => b.lane.startsWith('agent')).map((b) => +b.lane.slice(5)));
      const lanes = ['human', ...Array.from({ length: nLanes }, (_, i) => `agent${i + 1}`)];
      const flags = d.schedule?.summary?.flags || {};

      const axis = h('div.pl-axis', { style: { height: H + 'px' } });
      for (let m = Math.ceil(t0 / 60) * 60; m <= t1; m += 60) axis.append(h('span', { style: { top: (m - t0) * PX + 24 + 'px' } }, `${m / 60}:00`));
      const wrap = h('div.pl-tl', {}, [axis]);
      const isToday = state.date === today();
      const nowM = new Date().getHours() * 60 + new Date().getMinutes();
      for (const ln of lanes) {
        const lane = h('div.pl-lane', { style: { height: H + 'px' } }, [h('h4', {}, ln === 'human' ? [ui.icon('user'), '人'] : [ui.icon('robot'), `Agent ${ln.slice(5)}`])]);
        for (const w of cfg.focus_windows) {
          const a = Math.max(t0, mins(w.start)), b = Math.min(t1, mins(w.end));
          if (b > a) lane.append(h('div.pl-band', { style: { top: (a - t0) * PX + 24 + 'px', height: (b - a) * PX + 'px' } }));
        }
        for (let m = Math.ceil(t0 / 60) * 60; m <= t1; m += 60) lane.append(h('div.pl-hr', { style: { top: (m - t0) * PX + 24 + 'px' } }));
        if (isToday && nowM > t0 && nowM < t1) lane.append(h('div.pl-now', { style: { top: (nowM - t0) * PX + 24 + 'px' } }));
        for (const b of blocks.filter((x) => x.lane === ln)) {
          const t = byId[b.task_id];
          if (!t) continue;
          const cls = [b.type === 'agent' ? 'agent' : '', b.type === 'kickoff' ? 'kick' : '', b.type === 'review' ? 'review' : '',
            b.type === 'work' && (t.human_level === 'heavy' || t.human_level === 'medium') ? 'heavy' : '',
            t.status === 'done' ? 'done' : '', flags[t.id] ? 'flag' : ''].filter(Boolean).map((c) => '.' + c).join('');
          const pre = { kickoff: '▶ 启动 ', review: '✓ 验收 ', agent: '', work: '' }[b.type];
          lane.append(h(`div.pl-blk${cls}`, {
            style: { top: y(b.start) + 'px', height: Math.max(9, (mins(b.end) - mins(b.start)) * PX - 2) + 'px' },
            title: `${b.start}-${b.end} ${t.title}\nP${t.priority} · ${LEVEL[t.human_level]} · ${EXEC[t.executor]}${flags[t.id] ? '\n⚠ ' + flags[t.id] : ''}\n${t.goal || ''}`,
          }, [h('b', {}, `${pre}${t.title}`), ' ', h('span.muted', {}, `${b.start} · P${t.priority} · ${LEVEL[t.human_level]}`)]));
        }
        wrap.append(lane);
      }
      const lg = (css, label) => h('span', {}, [h('i', { style: css }), label]);
      return h('div.card.pl-tl-card', {}, [
        h('div.pl-legend', {}, [lg('background: var(--focus); border: 1px solid var(--accent-soft)', '专注时间窗'),
          lg('background: var(--panel); border: 1px solid var(--line-2); border-left: 3px solid var(--accent)', '人 · 重/中度'),
          lg('background: var(--auto); border-left: 3px solid var(--ok)', 'Agent 执行'), lg('background: var(--auto); border: 1px dashed var(--ok)', '人启动 / 验收'),
          isToday ? lg('background: var(--accent); height: 2px', '现在') : null]),
        wrap]);
    }

    await load();
  },
};
