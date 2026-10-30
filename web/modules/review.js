// 复盘：当日事项完成度 + AI 检查 / 问题与经验 / 时间线 / Agent 效率反思
// 路由：#review/<YYYY-MM-DD>/<tab>
import { today } from '../api.js';

const CSS = `
.rv-tree .kids { margin: 6px 0 0 18px; display: flex; flex-direction: column; gap: 4px; }
.rv-task { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rv-task .t { flex: 1; min-width: 180px; }
.rv-task select, .rv-task input { width: auto; padding: 1px 4px; font-size: 12px; }
.rv-task input[type=range] { width: 110px; }
.rv-task.done .t b { text-decoration: line-through; opacity: .6; }
.rv-stats { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; }
.rv-stats b { font-size: 18px; display: block; }
.rv-sugg { border-left: 3px solid var(--accent); }
.rv-sugg.applied { opacity: .55; border-left-color: var(--ok); }
.rv-two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
@media (max-width: 900px) { .rv-two { grid-template-columns: 1fr; } }
.rv-msg { font-size: 12px; padding: 3px 0; border-bottom: 1px dashed var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
.tl-item { cursor: pointer; } .tl-item:hover .item { border-color: var(--accent); }
table.rv { border-collapse: collapse; width: 100%; font-size: 12px; } table.rv td, table.rv th { border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }
`;
const STATUS = { todo: '待办', doing: '进行中', done: '完成', partial: '部分', dropped: '放弃' };
const NOTE_KIND = { problem: '问题', lesson: '经验', insight: '洞察', idea: '想法' };
const NOTE_CLS = { problem: 'err', lesson: 'ok', insight: '', idea: 'warn' };
const MSG_KIND = { new_task: '新任务/追加', correct: '纠正/转向', approve: '确认/继续', interrupt: '中断', answer: '回答提问', check: '询问进度' };
const MSG_CLS = { correct: 'warn', interrupt: 'err', approve: '', check: 'warn', answer: '', new_task: 'ok' };
const TABS = { day: '当日复盘', timeline: '时间线', notes: '问题与经验', agent: 'Agent 效率' };
let onAgentDone;

export default {
  async render(el, ctx) {
    const { api, h, md, toast, openChat, field, sub } = ctx;
    if (!document.getElementById('rv-css')) document.head.append(h('style', { id: 'rv-css' }, CSS));
    const state = { date: /^\d{4}-\d{2}-\d{2}$/.test(sub[0] || '') ? sub[0] : today(), tab: TABS[sub[1]] ? sub[1] : 'day' };
    const go = (date, tab) => { location.hash = `#review/${date || state.date}/${tab || state.tab}`; };

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && state.tab === 'day' && show();
    document.addEventListener('agent-done', onAgentDone);

    const dateIn = h('input', { type: 'date', value: state.date, style: { width: 'auto' }, onchange: (e) => go(e.target.value) });
    const shift = (n) => { const d = new Date(state.date + 'T12:00:00'); d.setDate(d.getDate() + n); go(d.toLocaleDateString('sv-SE')); };
    const tabs = h('div.tabs', {}, Object.entries(TABS).map(([k, v]) =>
      h('button' + (k === state.tab ? '.active' : ''), { onclick: () => go(null, k) }, v)));
    el.append(h('div.row', { style: { marginBottom: '8px' } }, [
      h('button', { onclick: () => shift(-1) }, '‹'), dateIn, h('button', { onclick: () => shift(1) }, '›'),
      h('button.ghost', { onclick: () => go(today()) }, '今天'),
      h('span', { style: { flex: 1 } }),
      h('button.ghost', { onclick: () => openChat({ module: 'review', ref: state.date, title: `复盘 ${state.date}` }) }, '💬 复盘这一天'),
    ]), tabs);
    const body = h('div');
    el.append(body);

    const watching = new Set();
    async function watch(jobId, label, statusEl) {
      if (watching.has(jobId)) return;
      watching.add(jobId);
      const j = await api.waitJob(jobId, (j) => {
        const last = (j.log || '').trim().split('\n').pop() || '';
        statusEl.textContent = `${label}：${j.status} ${last.slice(0, 120)}`;
      });
      watching.delete(jobId);
      statusEl.textContent = '';
      toast(j.status === 'done' ? `${label}完成` : `${label}失败`, j.status !== 'done');
      if (el.isConnected) show();
    }

    // ---------- 当日复盘 ----------
    function taskRow(t) {
      const prog = h('input', { type: 'range', min: 0, max: 100, step: 10, value: t.progress || 0 });
      const pv = h('span.muted', {}, `${t.progress || 0}%`);
      prog.oninput = () => { pv.textContent = prog.value + '%'; };
      prog.onchange = async () => { await api.patch(`/api/tasks/${t.id}`, { progress: +prog.value, ...(prog.value == 100 ? { status: 'done' } : {}) }); show(); };
      const st = h('select', { html: Object.entries(STATUS).map(([v, l]) => `<option value="${v}"${v === t.status ? ' selected' : ''}>${l}</option>`).join('') });
      st.onchange = async () => { await api.patch(`/api/tasks/${t.id}`, { status: st.value, ...(st.value === 'done' ? { progress: 100 } : {}) }); show(); };
      const row = h('div.item', {}, [h('div.rv-task' + (t.status === 'done' ? '.done' : ''), {}, [
        h('div.t', {}, [h('b', {}, `#${t.id} ${t.title}`), ' ',
          t.executor && t.executor !== 'human' ? h('span.tag', {}, t.executor) : null,
          t.repo ? h('span.tag', { title: t.repo }, '📁') : null,
          t.goal ? h('div.muted', {}, '目标：' + t.goal) : null,
          t.notes ? h('div.muted', {}, t.notes.slice(0, 200)) : null]),
        st, prog, pv,
      ])]);
      if (t.children?.length) row.append(h('div.kids', {}, t.children.map(taskRow)));
      return row;
    }

    const stat = (label, s) => h('div', {}, [h('b', {}, s.total ? `${s.done}/${s.total}` : '-'), h('span.muted', {}, label + (s.total ? ` · 平均 ${s.avg_progress}%` : ''))]);

    function noteForm(date, after) {
      const kind = h('select', { style: { width: 'auto' }, html: Object.entries(NOTE_KIND).map(([v, l]) => `<option value="${v}">${l}</option>`).join('') });
      const title = h('input', { placeholder: '一句话（如：需求没写验收标准导致返工）' });
      const content = h('textarea', { rows: 2, placeholder: '细节 / 根因 / 下次怎么做（可选）' });
      const tags = h('input', { placeholder: '标签，逗号分隔', style: { width: '180px' } });
      const add = async () => {
        if (!title.value.trim() && !content.value.trim()) return toast('写点内容', true);
        await api.post('/api/review/notes', { date, kind: kind.value, title: title.value.trim(), content: content.value.trim(), tags: tags.value.trim() });
        title.value = content.value = tags.value = ''; toast('已记录'); after();
      };
      title.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
      return h('div', {}, [h('div.row', {}, [kind, h('div', { style: { flex: 1 } }, title), tags, h('button.primary', { onclick: add }, '记录')]),
        h('div', { style: { marginTop: '6px' } }, content)]);
    }

    function noteItem(n, after) {
      return h('div.item', {}, [
        h('div.row', {}, [h('span.tag.' + (NOTE_CLS[n.kind] || ''), {}, NOTE_KIND[n.kind] || n.kind), h('b', { style: { flex: 1 } }, n.title || ''),
          h('a.muted', { href: `#review/${n.date}/day` }, n.date),
          h('button.icon', { title: '删除', onclick: async () => { if (confirm('删除这条记录？')) { await api.del(`/api/review/notes/${n.id}`); after(); } } }, '×')]),
        n.content ? h('div', { style: { whiteSpace: 'pre-wrap', fontSize: '13px' } }, n.content) : null,
        n.tags ? h('div', {}, n.tags.split(',').filter(Boolean).map((t) => h('span.tag', {}, t.trim()))) : null,
      ]);
    }

    async function renderDay() {
      const d = await api.get(`/api/review/day?date=${state.date}`);
      const rec = d.record;
      body.innerHTML = '';
      // 事项
      body.append(h('div.card', {}, [
        h('div.row', {}, [h('h3', { style: { flex: 1 } }, '当日事项与目标'), h('a.muted', { href: '#plan' }, '去规划 →')]),
        h('div.rv-stats', {}, [stat('事项完成', d.stats.work), stat('学习完成', d.stats.learning)]),
        d.tasks.length ? h('div.list.rv-tree', {}, d.tasks.map(taskRow)) : h('div.muted', {}, '这一天没有事项。'),
      ]));
      // 学习
      const lx = d.learning_extra;
      if (d.learning.length || lx.steps.length || lx.items.length) {
        body.append(h('div.card', {}, [h('h3', {}, '学习任务'),
          d.learning.length ? h('div.list.rv-tree', {}, d.learning.map(taskRow)) : null,
          lx.steps.length ? h('div', { style: { marginTop: '8px' } }, [h('div.muted', {}, '深度学习步骤'),
            ...lx.steps.map((s) => h('div.item', {}, [h('span.tag' + (s.status === 'done' ? '.ok' : ''), {}, s.status), s.plan_topic ? h('span.muted', {}, s.plan_topic + ' · ') : null, s.title,
              s.understanding ? h('span.muted', {}, ` 理解 ${s.understanding}/5`) : null]))]) : null,
          lx.items.length ? h('div', { style: { marginTop: '8px' } }, [h('div.muted', {}, '完成的论文/代码解析'),
            ...lx.items.map((i) => h('div.item', {}, [h('span.tag', {}, i.kind), i.title || i.url]))]) : null,
        ]));
      }
      // AI 检查
      const status = h('div.muted');
      const checkBtn = h('button.primary', { onclick: async () => {
        checkBtn.disabled = true;
        const r = await api.post('/api/review/check', { date: state.date });
        watch(r.job_id, 'AI 检查', status);
      } }, 'AI 检查完成情况');
      const running = d.jobs.find((j) => j.ref.startsWith('check:') && (j.status === 'queued' || j.status === 'running'));
      if (running) { checkBtn.disabled = true; watch(running.id, 'AI 检查', status); }
      const sugg = rec.task_suggestions || [];
      const titleOf = (id) => { const all = [...d.tasks, ...d.learning].flatMap((t) => [t, ...(t.children || [])]); return all.find((t) => t.id === id)?.title || ''; };
      body.append(h('div.card', {}, [
        h('div.row', {}, [h('h3', { style: { flex: 1 } }, 'AI 检查'), checkBtn]),
        h('div.muted', {}, '对照目标，分析当天 git 提交、改动文件、文档（设置里的「复盘分析目录」+ 事项 repo）。'), status,
        sugg.length ? h('div.list', { style: { margin: '8px 0' } }, sugg.map((s, i) => h('div.item.rv-sugg' + (s.applied ? '.applied' : ''), {}, [
          h('div.row', {}, [h('b', { style: { flex: 1 } }, `#${s.task_id} ${titleOf(s.task_id)}`),
            s.status ? h('span.tag', {}, STATUS[s.status] || s.status) : null, s.progress != null ? h('span.tag', {}, s.progress + '%') : null,
            h('button', { disabled: s.applied, onclick: async () => { await api.post(`/api/review/suggestions/${state.date}/${i}/apply`); toast('已采纳'); show(); } }, s.applied ? '已采纳' : '采纳')]),
          s.evidence ? h('div.muted', {}, '证据：' + s.evidence) : null,
          s.problem ? h('div', { style: { fontSize: '12px', color: 'var(--warn)' } }, '问题：' + s.problem) : null,
        ]))) : null,
        rec.ai_analysis ? h('details', { open: !sugg.length }, [h('summary', {}, '完整分析'), md(rec.ai_analysis)]) : null,
      ]));
      // 复盘记录
      const ta = (k, ph) => h('textarea', { rows: 3, value: rec[k] || '', placeholder: ph, 'data-k': k });
      const fields = { summary: ta('summary', '今天整体怎样'), wins: ta('wins', '做成了什么'), problems: ta('problems', '遇到的问题、根因'), next_actions: ta('next_actions', '明天要做 / 要改的') };
      body.append(h('div.card', {}, [h('h3', {}, '我的复盘'),
        field('总结', fields.summary),
        h('div.rv-two', {}, [field('收获', fields.wins), field('问题', fields.problems)]),
        field('下一步', fields.next_actions),
        h('button.primary', { onclick: async () => {
          await api.put(`/api/review/day/${state.date}`, Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, v.value])));
          toast('已保存');
        } }, '保存复盘'),
      ]));
      // 问题与经验
      body.append(h('div.card', {}, [h('h3', {}, '问题与经验'), noteForm(state.date, show),
        h('div.list', { style: { marginTop: '8px' } }, d.notes.map((n) => noteItem(n, show)))]));
      // 效率
      body.append(h('div.card', {}, [h('div.row', {}, [h('h3', { style: { flex: 1 } }, 'Agent 效率'), h('button', { onclick: () => go(null, 'agent') }, '查看 →')]),
        h('div', {}, d.efficiency ? d.efficiency.headline : h('span.muted', {}, '未扫描，点「查看」扫描当日 Claude Code / Codex 会话'))]));
    }

    // ---------- 时间线 ----------
    async function renderTimeline() {
      const end = state.date;
      const s = new Date(end + 'T12:00:00'); s.setDate(s.getDate() - 29);
      const startIn = h('input', { type: 'date', value: s.toLocaleDateString('sv-SE'), style: { width: 'auto' } });
      const endIn = h('input', { type: 'date', value: end, style: { width: 'auto' } });
      const list = h('div.timeline');
      const load = async () => {
        const days = await api.get(`/api/review/timeline?start=${startIn.value}&end=${endIn.value}`);
        list.innerHTML = '';
        if (!days.length) list.append(h('div.muted', {}, '这段时间没有记录。'));
        for (const x of days) {
          const t = x.tasks, l = x.learning;
          list.append(h('div.tl-item', { onclick: () => go(x.date, 'day') }, [h('div.item', {}, [
            h('div.row', {}, [h('b', {}, x.date),
              t.total ? h('span.tag' + (t.done === t.total ? '.ok' : ''), {}, `事项 ${t.done}/${t.total} · ${t.avg_progress}%`) : null,
              l.total ? h('span.tag', {}, `学习 ${l.done}/${l.total}`) : null,
              x.has_ai ? h('span.tag', {}, 'AI 已检查') : null]),
            x.summary ? h('div', { style: { fontSize: '13px' } }, x.summary.slice(0, 200)) : null,
            x.notes.length ? h('div', {}, x.notes.slice(0, 6).map((n) => h('span.tag.' + (NOTE_CLS[n.kind] || ''), {}, `${NOTE_KIND[n.kind] || n.kind}：${n.title}`))) : null,
            x.efficiency ? h('div.muted', {}, '⚙ ' + x.efficiency) : null,
          ])]));
        }
      };
      body.innerHTML = '';
      body.append(h('div.row', { style: { marginBottom: '10px' } }, [startIn, '—', endIn, h('button', { onclick: load }, '查看')]), list);
      await load();
    }

    // ---------- 问题与经验 ----------
    async function renderNotes() {
      const q = h('input', { placeholder: '搜索标题/内容/标签', style: { width: '220px' } });
      const kind = h('select', { style: { width: 'auto' }, html: '<option value="">全部类型</option>' + Object.entries(NOTE_KIND).map(([v, l]) => `<option value="${v}">${l}</option>`).join('') });
      const list = h('div.list');
      const load = async () => {
        const ns = await api.get(`/api/review/notes?q=${encodeURIComponent(q.value)}&kind=${kind.value}`);
        list.replaceChildren(...(ns.length ? ns.map((n) => noteItem(n, load)) : [h('div.muted', {}, '没有记录。')]));
      };
      q.addEventListener('input', () => { clearTimeout(q._t); q._t = setTimeout(load, 250); });
      kind.onchange = load;
      body.innerHTML = '';
      body.append(h('div.card', {}, [h('h3', {}, `记录到 ${state.date}`), noteForm(state.date, load)]),
        h('div.row', { style: { marginBottom: '8px' } }, [q, kind]), list);
      await load();
    }

    // ---------- Agent 效率 ----------
    async function renderAgent(refresh = false) {
      body.innerHTML = '';
      body.append(h('div.muted', {}, '扫描会话日志中…'));
      const e = await api.get(`/api/review/efficiency?date=${state.date}${refresh ? '&refresh=1' : ''}`);
      const a = e.summary;
      body.innerHTML = '';
      const status = h('div.muted');
      const reflectBtn = h('button.primary', { onclick: async () => {
        reflectBtn.disabled = true;
        const r = await api.post('/api/review/reflect', { date: state.date });
        watch(r.job_id, 'AI 反思', status);
      } }, 'AI 反思');
      if (e.reflect_job && ['queued', 'running'].includes(e.reflect_job.status)) { reflectBtn.disabled = true; watch(e.reflect_job.id, 'AI 反思', status); }
      const num = (v, l) => h('div', {}, [h('b', {}, v), h('span.muted', {}, l)]);
      body.append(h('div.card', {}, [
        h('div.row', {}, [h('h3', { style: { flex: 1 } }, 'Claude Code / Codex 效率'), h('span.muted', {}, '扫描于 ' + (e.scanned_at || '').slice(11, 16)),
          h('button', { onclick: () => renderAgent(true) }, '重新扫描'), reflectBtn]),
        h('div.rv-stats', {}, [num(`${a.interactive}+${a.automated}`, '交互+自动会话'), num(a.human_turns, '人工介入'),
          num(((a.active_min_interactive ?? a.active_min) / 60).toFixed(1) + 'h', `Agent 活跃（交互；含自动 ${(a.active_min / 60).toFixed(1)}h）`), num(a.wait_total_min + '分', '人工响应(单次封顶30分)'),
          num(a.wait_median_min + '分', '等待中位'), num(a.peak_parallel, '峰值并行'),
          num(`${a.tool_errors}/${a.tool_calls}`, '工具错误/调用'), num(a.denials, '权限拒绝'),
          num(`${a.platform_jobs_failed || 0}/${a.platform_jobs || 0}`, '平台任务失败/总')]),
        h('div', {}, Object.entries(a.kinds || {}).map(([k, v]) => h('span.tag.' + (MSG_CLS[k] || ''), {}, `${MSG_KIND[k] || k} ${v}`))),
        h('div.muted', { style: { marginTop: '6px' } }, '分类为启发式规则：首条=新任务；短句「继续/好/提交」=确认；上一条 Agent 在提问=回答；含「不对/应该/打不开」等=纠正。'),
        status,
      ]));
      if (e.reflection) body.append(h('div.card', {}, [h('h3', {}, 'AI 反思'), md(e.reflection)]));
      const inter = e.sessions.filter((s) => !s.automated || s.human_turns);
      const auto = e.sessions.filter((s) => s.automated && !s.human_turns);
      body.append(h('div.card', {}, [h('h3', {}, `交互会话（${inter.length}）`),
        h('div.list', {}, inter.map((s) => h('details.item', {}, [
          h('summary', {}, [h('span.tag', {}, s.engine), h('b', {}, s.project), ' ', h('span.muted', {}, (s.title || '').slice(0, 40)), ' ',
            h('span.muted', {}, `${s.start.slice(11, 16)}–${s.end.slice(11, 16)} · 活跃 ${s.active_min} / 墙钟 ${s.wall_min} 分 · 介入 ${s.human_turns} · 工具 ${s.tool_calls}（错 ${s.tool_errors}，拒 ${s.denials}）`)]),
          h('div', {}, Object.entries(s.kinds).filter(([, v]) => v).map(([k, v]) => h('span.tag.' + (MSG_CLS[k] || ''), {}, `${MSG_KIND[k]} ${v}`))),
          ...s.messages.map((m) => h('div.rv-msg', {}, [h('span.muted', {}, `${m.t}${m.wait_min != null ? ` 等${m.wait_min}分` : ''} `),
            h('span.tag.' + (MSG_CLS[m.kind] || ''), {}, MSG_KIND[m.kind] || m.kind), m.text])),
        ])))]));
      if (auto.length) {
        const byProj = {};
        for (const s of auto) { const p = byProj[s.project] ||= { n: 0, min: 0, tools: 0, err: 0 }; p.n++; p.min += s.active_min; p.tools += s.tool_calls; p.err += s.tool_errors; }
        body.append(h('details.card', {}, [h('summary', {}, `自动化会话（${auto.length}，claude -p / codex exec）`),
          h('table.rv', {}, [h('tr', {}, ['项目', '会话', '活跃分钟', '工具', '错误'].map((x) => h('th', {}, x))),
            ...Object.entries(byProj).map(([p, v]) => h('tr', {}, [p, v.n, v.min.toFixed(1), v.tools, v.err].map((x) => h('td', {}, String(x)))))])]));
      }
      const pr = e.platform || {};
      if ((pr.jobs || []).length || (pr.plan_runs || []).length) {
        body.append(h('details.card', {}, [h('summary', {}, `本平台后台任务（${(pr.jobs || []).length}）· 规划自动执行（${(pr.plan_runs || []).length}）`),
          h('table.rv', {}, [h('tr', {}, ['#', '板块', 'ref', '引擎', '状态', '分钟'].map((x) => h('th', {}, x))),
            ...(pr.jobs || []).map((j) => h('tr', {}, [j.id, j.module, j.ref, j.engine, j.status, j.minutes ?? '-'].map((x) => h('td', {}, String(x)))))]),
          ...(pr.plan_runs || []).map((r) => h('div.item', {}, `#${r.task_id} ${r.task_title || ''} · ${r.engine} · ${r.status}`))]));
      }
    }

    async function show() {
      try {
        if (state.tab === 'day') await renderDay();
        else if (state.tab === 'timeline') await renderTimeline();
        else if (state.tab === 'notes') await renderNotes();
        else await renderAgent();
      } catch (e) {
        body.replaceChildren(h('pre.error', {}, e.message));
      }
    }
    await show();
  },
};
