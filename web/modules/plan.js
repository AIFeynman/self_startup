// 规划：每日事项录入 → AI 拆解 → 排程（专注窗 / 人车道 / Agent 车道）→ 可选让 Agent 自动执行
import { today } from '../api.js';

const CSS = `
.plan-tl { display: flex; gap: 6px; position: relative; overflow-x: auto; }
.plan-axis { width: 44px; flex: none; position: relative; font-size: 11px; color: var(--muted); }
.plan-axis span { position: absolute; right: 4px; transform: translateY(-50%); }
.plan-lane { flex: 1; min-width: 130px; position: relative; border-left: 1px dashed var(--line); }
.plan-lane > h4 { position: sticky; top: 0; margin: 0; font-size: 12px; text-align: center; color: var(--muted); }
.plan-band { position: absolute; left: 0; right: 0; background: var(--focus); opacity: .55; pointer-events: none; }
.plan-hr { position: absolute; left: 0; right: 0; border-top: 1px solid var(--line); opacity: .5; }
.plan-blk { position: absolute; left: 3px; right: 3px; padding: 0 5px !important; font-size: 11px; line-height: 1.25; overflow: hidden; cursor: default; }
.plan-blk.kick, .plan-blk.review { border-style: dashed; background: var(--auto); opacity: .85; font-size: 10px; line-height: 1; }
.plan-blk.done { opacity: .45; text-decoration: line-through; }
.plan-blk.flag { border-color: var(--warn); }
.plan-now { position: absolute; left: 0; right: 0; border-top: 2px solid var(--err); z-index: 2; }
.plan-tree .item { margin-bottom: 6px; }
.plan-tree .kids { margin: 6px 0 0 18px; display: flex; flex-direction: column; gap: 4px; }
.plan-ed { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; margin-top: 4px; }
.plan-ed select, .plan-ed input { width: auto; padding: 1px 4px; font-size: 12px; }
.plan-ed input[type=number] { width: 64px; }
.plan-stats { display: flex; gap: 18px; flex-wrap: wrap; }
.plan-stats b { font-size: 18px; display: block; }
`;
const LEVEL = { heavy: '重度', medium: '中度', light: '轻度', auto: '自动' };
const EXEC = { human: '人', claude: 'Claude', codex: 'Codex', mixed: '混合' };
const STATUS = { todo: '待办', doing: '进行中', done: '完成', partial: '部分', dropped: '放弃' };
const KIND = { work: '工作', learning: '学习', life: '生活' };
const PX = 1.8; // 每分钟像素

const mins = (s) => { const [a, b] = (s || '0:0').split(':').map(Number); return a * 60 + b; };
const opts = (map, cur) => Object.entries(map).map(([v, t]) => `<option value="${v}"${v == cur ? ' selected' : ''}>${t}</option>`).join('');
let onAgentDone;

export default {
  async render(el, ctx) {
    const { api, h, toast, openChat } = ctx;
    if (!document.getElementById('plan-css')) document.head.append(h('style', { id: 'plan-css' }, CSS));
    const state = { date: today(), runs: [] };

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && load();
    document.addEventListener('agent-done', onAgentDone);

    const sel = (map, cur, onchange) => { const s = h('select', { html: opts(map, cur) }); s.onchange = () => onchange(s.value); return s; };
    const patch = async (id, body) => { await api.patch(`/api/tasks/${id}`, body); load(); };

    async function watch(jobId, label, statusEl) {
      statusEl.textContent = `${label}：排队中…`;
      const j = await api.waitJob(jobId, (j) => {
        const last = (j.log || '').trim().split('\n').pop() || '';
        statusEl.textContent = `${label}：${j.status} ${last.slice(0, 120)}`;
      });
      statusEl.textContent = '';
      toast(j.status === 'done' ? `${label}完成` : `${label}失败`, j.status !== 'done');
      load();
    }

    async function load() {
      const d = await api.get(`/api/plan/day?date=${state.date}`);
      state.runs = d.runs;
      el.innerHTML = '';
      el.append(toolbar(d), addForm(), summary(d), timeline(d), tree(d));
      for (const j of d.jobs) watch(j.id, 'AI 拆解', el.querySelector('.plan-job'));
    }

    function toolbar(d) {
      const date = h('input', { type: 'date', value: state.date, style: { width: 'auto' } });
      const shift = (n) => { const x = new Date(state.date + 'T00:00'); x.setDate(x.getDate() + n); setDate(x.toLocaleDateString('sv-SE')); };
      const setDate = (v) => { state.date = v; load(); };
      date.onchange = () => setDate(date.value);
      const fromNow = h('input', { type: 'checkbox', title: '中途重排：只排当前时间之后' });
      const jobEl = h('span.muted.plan-job');
      const hint = h('input', { placeholder: '拆解补充要求（可选）', style: { width: '220px' } });
      const decompose = async () => {
        try {
          const r = await api.post('/api/plan/decompose', { date: state.date, hint: hint.value });
          watch(r.job_id, 'AI 拆解', jobEl);
        } catch (e) { toast(e.message, true); }
      };
      const schedule = async () => {
        const now = new Date();
        const from = fromNow.checked ? `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}` : '';
        await api.post('/api/plan/schedule', { date: state.date, from_time: from });
        toast('已排程'); load();
      };
      const carry = async () => {
        const r = await api.post('/api/plan/carry', { date: state.date });
        toast(r.from ? `从 ${r.from} 顺延 ${r.created.length} 项` : '没有可顺延的事项'); load();
      };
      const fw = d.config.focus_windows.map((w) => `${w.start}-${w.end}`).join('、');
      return h('div.card', {}, [
        h('div.row', {}, [
          h('button', { onclick: () => shift(-1) }, '◀'), date, h('button', { onclick: () => shift(1) }, '▶'),
          h('button', { onclick: () => setDate(today()) }, '今天'),
          h('button', { onclick: carry }, '顺延未完成'),
          hint, h('button', { onclick: decompose }, '🤖 AI 拆解'),
          h('label.row', { style: { gap: '4px' } }, [fromNow, h('span.muted', {}, '从现在起')]),
          h('button.primary', { onclick: schedule }, '排程'),
          h('button.ghost', { onclick: () => openChat({ module: 'plan', ref: `plan:${state.date}`, title: '规划',
            prefill: '帮我看看今天的安排：优先级是否合理？哪些可以交给 Agent 并行？' }) }, '💬 讨论今天'),
        ]),
        h('div.muted', {}, `专注时间 ${fw} · 一天 ${d.config.day_start}-${d.config.day_end} · Agent 并发 ${d.config.max_agent_concurrency}（在「设置」修改）`),
        jobEl,
      ]);
    }

    function addForm() {
      const title = h('input', { placeholder: '事项标题' });
      const goal = h('input', { placeholder: '目标 / 完成标准' });
      const prio = h('select', { html: opts({ 1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4' }, 2), style: { width: 'auto' } });
      const kind = h('select', { html: opts(KIND, 'work'), style: { width: 'auto' } });
      const est = h('input', { type: 'number', value: 60, min: 5, step: 5, style: { width: '80px' }, title: '预计分钟' });
      const repo = h('input', { placeholder: '代码库/文档目录（可选）', style: { width: '200px' } });
      const add = async () => {
        if (!title.value.trim()) return toast('请填写标题', true);
        await api.post('/api/tasks', { date: state.date, title: title.value.trim(), goal: goal.value.trim(), priority: +prio.value,
          kind: kind.value, est_minutes: +est.value || 30, repo: repo.value.trim() });
        load();
      };
      title.addEventListener('keydown', (e) => e.key === 'Enter' && add());
      return h('div.card', {}, [h('h3', {}, '添加事项'),
        h('div.row', {}, [h('div', { style: { flex: '2', minWidth: '160px' } }, title), h('div', { style: { flex: '3', minWidth: '200px' } }, goal),
          prio, kind, est, h('span.muted', {}, '分钟'), repo, h('button.primary', { onclick: add }, '添加')])]);
    }

    function summary(d) {
      const s = d.schedule?.summary;
      if (!s) return h('div.card.muted', {}, '还没有排程。录入事项 →（可选）AI 拆解 → 排程。');
      const stat = (label, v) => h('div', {}, [h('b', {}, v), h('span.muted', {}, label)]);
      return h('div.card', {}, [
        h('div.plan-stats', {}, [
          stat('专注内人时间', `${s.human_focus_minutes} / ${s.focus_capacity_minutes} 分`),
          stat('专注外人时间', `${s.human_outside_minutes} 分`),
          stat('Agent 时间', `${s.agent_minutes} 分`),
          stat('并行度', s.parallel_ratio),
          stat('峰值并发', `${s.agent_peak_concurrency} / ${s.lanes}`),
          stat('已排', `${s.scheduled} 项`),
        ]),
        s.warnings.length ? h('div', { style: { marginTop: '8px' } }, s.warnings.map((w) => h('div', {}, [h('span.tag.warn', {}, '⚠'), w]))) : null,
        h('div.muted', {}, `排程于 ${d.schedule.created_at}（从 ${s.from_time} 起）；修改任务后请重新排程`),
      ]);
    }

    function timeline(d) {
      const cfg = d.config;
      const t0 = mins(cfg.day_start), t1 = mins(cfg.day_end);
      const y = (t) => (mins(t) - t0) * PX + 20;
      const H = (t1 - t0) * PX + 30;
      const byId = Object.fromEntries(d.tasks.map((t) => [t.id, t]));
      const blocks = d.schedule?.blocks || [];
      const nLanes = Math.max(cfg.max_agent_concurrency, ...blocks.filter((b) => b.lane.startsWith('agent')).map((b) => +b.lane.slice(5)));
      const lanes = ['human', ...Array.from({ length: nLanes }, (_, i) => `agent${i + 1}`)];
      const flags = d.schedule?.summary?.flags || {};

      const axis = h('div.plan-axis', { style: { height: H + 'px' } });
      for (let m = Math.ceil(t0 / 60) * 60; m <= t1; m += 60) axis.append(h('span', { style: { top: (m - t0) * PX + 20 + 'px' } }, `${m / 60}:00`));
      const wrap = h('div.plan-tl', {}, [axis]);
      const isToday = state.date === today();
      const nowM = new Date().getHours() * 60 + new Date().getMinutes();
      for (const ln of lanes) {
        const lane = h('div.plan-lane', { style: { height: H + 'px' } }, [h('h4', {}, ln === 'human' ? '👤 人' : `🤖 Agent ${ln.slice(5)}`)]);
        for (let m = Math.ceil(t0 / 60) * 60; m <= t1; m += 60) lane.append(h('div.plan-hr', { style: { top: (m - t0) * PX + 20 + 'px' } }));
        for (const w of cfg.focus_windows) lane.append(h('div.plan-band', { style: { top: y(w.start) + 'px', height: (mins(w.end) - mins(w.start)) * PX + 'px' } }));
        if (isToday && nowM > t0 && nowM < t1) lane.append(h('div.plan-now', { style: { top: (nowM - t0) * PX + 20 + 'px' } }));
        for (const b of blocks.filter((x) => x.lane === ln)) {
          const t = byId[b.task_id];
          if (!t) continue;
          const cls = ['item', b.type === 'agent' ? 'auto' : '', b.type === 'kickoff' ? 'kick' : '', b.type === 'review' ? 'review' : '',
            b.type === 'work' && (t.human_level === 'heavy' || t.human_level === 'medium') ? 'focus' : '',
            t.status === 'done' ? 'done' : '', flags[t.id] ? 'flag' : ''].filter(Boolean).join('.');
          const pre = { kickoff: '▶ 启动 ', review: '✓ 验收 ', agent: '🤖 ', work: '' }[b.type];
          lane.append(h(`div.plan-blk.${cls}`, {
            style: { top: y(b.start) + 'px', height: Math.max(8, (mins(b.end) - mins(b.start)) * PX - 1) + 'px' },
            title: `${b.start}-${b.end} ${t.title}\nP${t.priority} · ${LEVEL[t.human_level]} · ${EXEC[t.executor]}${flags[t.id] ? '\n⚠ ' + flags[t.id] : ''}\n${t.goal || ''}`,
          }, [h('b', {}, `${pre}${t.title}`), ' ', h('span.muted', {}, `${b.start} P${t.priority} ${LEVEL[t.human_level]}`)]));
        }
        wrap.append(lane);
      }
      return h('div.card', {}, [h('h3', {}, '时间线'), h('div.muted', {}, '黄色底 = 专注时间窗；虚线块 = Agent 任务的人启动 / 验收'), wrap]);
    }

    function editor(t, isLeaf) {
      const runs = state.runs.filter((r) => r.task_id === t.id);
      const est = h('input', { type: 'number', value: t.est_minutes, min: 5, step: 5 });
      est.onchange = () => patch(t.id, { est_minutes: +est.value });
      const launch = async () => {
        try {
          const r = await api.post(`/api/plan/tasks/${t.id}/launch`, {});
          toast(`已派发给 Agent（job ${r.job_id}）`);
          load();
          watch(r.job_id, `执行「${t.title}」`, el.querySelector('.plan-job'));
        } catch (e) { toast(e.message, true); }
      };
      const canRun = isLeaf && (t.human_level === 'auto' || ['claude', 'codex'].includes(t.executor)) && t.status !== 'done';
      return h('div.plan-ed', {}, [
        sel({ 1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4' }, t.priority, (v) => patch(t.id, { priority: +v })),
        sel(LEVEL, t.human_level, (v) => patch(t.id, { human_level: v })),
        sel(EXEC, t.executor, (v) => patch(t.id, { executor: v })),
        est, h('span.muted', {}, '分'),
        sel(STATUS, t.status, (v) => patch(t.id, { status: v, progress: v === 'done' ? 100 : t.progress })),
        t.start_time ? h('span.tag', {}, `${t.start_time}-${t.end_time}`) : h('span.muted', {}, '未排'),
        t.parallel_group ? h('span.tag', {}, `并行组 ${t.parallel_group}`) : null,
        t.depends_on?.length ? h('span.muted', {}, `依赖 #${t.depends_on.join(',#')}`) : null,
        canRun ? h('button', { onclick: launch, title: '让 Agent 自动执行（cwd = 代码库目录）' }, '🚀 执行') : null,
        ...runs.slice(0, 1).map((r) => h(`span.tag.${r.status === 'done' ? 'ok' : r.status === 'running' ? '' : 'warn'}`, { title: r.result || '' }, `Agent ${r.status}`)),
        h('button.icon', { title: '删除', onclick: async () => { if (confirm(`删除「${t.title}」${isLeaf ? '' : '及其子任务'}？`)) { await api.del(`/api/tasks/${t.id}`); load(); } } }, '🗑'),
      ]);
    }

    function tree(d) {
      if (!d.tree.length) return h('div.card.muted', {}, '今天还没有事项。');
      const node = (t, leaf) => h(`div.item${t.human_level === 'auto' ? '.auto' : ''}`, {}, [
        h('div', {}, [h('b', {}, `#${t.id} ${t.title}`), ' ', h('span.muted', {}, [KIND[t.kind] || t.kind, t.repo ? ` · ${t.repo}` : ''].join(''))]),
        t.goal ? h('div.muted', {}, '目标：' + t.goal) : null,
        editor(t, leaf),
        t.notes ? h('details', {}, [h('summary.muted', {}, '备注 / Agent 结果'), h('pre', {}, t.notes)]) : null,
      ]);
      return h('div.card.plan-tree', {}, [h('h3', {}, '事项树'), ...d.tree.map((p) => {
        const n = node(p, !p.children.length);
        if (p.children.length) {
          n.append(h('div.kids', {}, p.children.map((c) => node(c, true))));
          n.append(h('button.ghost', { onclick: async () => { const r = await api.post('/api/plan/decompose', { date: state.date, task_ids: [p.id] }); watch(r.job_id, 'AI 重新拆解', el.querySelector('.plan-job')); } }, '🤖 重新拆解'));
        }
        return n;
      })]);
    }

    await load();
  },
};
