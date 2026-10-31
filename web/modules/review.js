// 复盘（首页）：问候 + 一句话状态 + 大输入框（记一条 / 写复盘 / 问 Agent）+ 今日三卡（事项 / AI 建议 / Agent 效率）
// 标签页：当日复盘 / 时间线 / 问题与经验 / Agent 效率。路由：#review/<YYYY-MM-DD>/<tab>
import { today } from '../api.js';
import { utilization } from './_utilchart.js';
import { deliveries } from './_deliveries.js';

const CSS = `
.rv-top { display: flex; justify-content: flex-end; margin-bottom: -8px; }
.rv-date { display: inline-flex; align-items: center; gap: 2px; padding: 2px 4px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); }
.rv-date button { border: none; background: none; padding: 3px 9px; color: var(--muted); }
.rv-date button:hover { color: var(--accent); background: var(--accent-soft); }
.rv-date label { position: relative; padding: 2px 8px; font-size: 13px; cursor: pointer; white-space: nowrap; }
.rv-date label input { position: absolute; inset: 0; opacity: 0; cursor: pointer; padding: 0; border: none; }
.rv-hero { padding-top: 26px; }
.rv-hero h1 { font-size: 36px; }
.rv-hero .sub b { color: var(--accent); font-weight: 600; }
.rv-wrap .composer { margin-top: 18px; }
.rv-tabs { display: flex; justify-content: center; margin: 22px 0 4px; }
.rv-tabs .tabs { margin: 0; padding: 4px; background: var(--bg-2); border-radius: 999px; gap: 2px; }
.rv-tabs .tabs button { border: none; background: transparent; padding: 5px 16px; }
.rv-tabs .tabs button.active { background: var(--panel); color: var(--text); box-shadow: var(--shadow); }
.rv-cards { display: grid; grid-template-columns: 1.35fr 1fr 1fr; gap: 14px; align-items: start; }
.rv-cards > .card { margin: 0; min-width: 0; }
@media (max-width: 1180px) { .rv-cards { grid-template-columns: 1fr 1fr; } .rv-cards > .rv-tasks { grid-column: 1 / -1; } }
@media (max-width: 760px) { .rv-cards { grid-template-columns: 1fr; } }
.rv-big { display: flex; align-items: baseline; gap: 10px; margin: 2px 0 8px; }
.rv-big .num { font-size: 34px; }
.rv-big .muted { flex: 1; }
.rv-task { position: relative; display: flex; align-items: flex-start; gap: 10px; padding: 7px 0; border-top: 1px solid var(--line); }
.rv-task:first-child { border-top: none; }
.rv-task.kid { padding-left: 22px; }
.rv-check { flex: none; width: 20px; height: 20px; padding: 0; margin-top: 2px; justify-content: center; border-radius: 50%; border: 1.5px solid var(--line-2); background: var(--panel); color: transparent; }
.rv-check svg { width: 13px; height: 13px; stroke-width: 2.6; }
.rv-check:hover { border-color: var(--accent); color: var(--accent); }
.rv-task.done .rv-check { background: var(--accent); border-color: var(--accent); color: #fff; }
.rv-task .t { flex: 1; min-width: 0; cursor: pointer; }
.rv-task .t > span { font-size: 14px; }
.rv-task.done .t > span { color: var(--muted); text-decoration: line-through; }
.rv-task.dropped .t > span { color: var(--muted); text-decoration: line-through dotted; }
.rv-pills { display: none; gap: 2px; position: absolute; right: 0; top: 6px; padding-left: 14px; background: linear-gradient(90deg, transparent, var(--panel) 14px); }
.rv-task:hover .rv-pills { display: flex; }
.rv-task:hover .rv-st { visibility: hidden; }
.rv-pills button { padding: 0 7px; font-size: 11px; line-height: 20px; border-color: var(--line); color: var(--muted); }
.rv-pills button.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.rv-detail { margin: 6px 0 2px; padding: 8px 10px; background: var(--bg-2); border-radius: var(--radius-sm); font-size: 12px; color: var(--muted); }
.rv-detail input[type=range] { width: 140px; padding: 0; vertical-align: middle; }
.rv-more { margin-top: 6px; }
.rv-sugg { padding: 10px 0; border-top: 1px solid var(--line); }
.rv-sugg:first-of-type { border-top: none; padding-top: 2px; }
.rv-sugg .ttl { font-weight: 600; font-size: 14px; }
.rv-sugg .row { margin-top: 8px; }
.rv-tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 4px 0 12px; }
.rv-tiles .stat { padding: 10px 12px; background: var(--bg); border-color: transparent; }
.rv-tiles .stat .v { font-size: 22px; }
.rv-rec { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 22px; }
.rv-rec .k { font-size: 12px; color: var(--accent); margin-bottom: 2px; }
.rv-rec .v { white-space: pre-wrap; font-size: 14px; min-height: 22px; }
.rv-rec .v.none { color: var(--muted); }
.rv-entries { display: flex; flex-direction: column; }
.rv-entry { display: grid; grid-template-columns: 64px 44px 1fr; gap: 10px; align-items: baseline; padding: 7px 0; border-top: 1px dashed var(--line); }
.rv-entry:first-child { border-top: none; padding-top: 0; }
.rv-entry .t { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.rv-entry .f { font-size: 12px; color: var(--accent); }
.rv-entry .x { white-space: pre-wrap; font-size: 14px; overflow-wrap: anywhere; }
.rv-improve .md { font-size: 14px; }
.rv-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--line-2); }
@media (max-width: 760px) { .rv-rec, .rv-form { grid-template-columns: 1fr; } }
.rv-notes { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; align-items: start; }
.rv-agent .stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 900px) { .rv-agent .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.rv-note { margin: 0; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.rv-note .head { display: flex; align-items: center; gap: 6px; }
.rv-note .head .del { margin-left: auto; opacity: 0; }
.rv-note:hover .head .del { opacity: 1; }
.rv-note .ttl { font: 700 15px/1.5 var(--serif); }
.rv-note .ct { font-size: 13px; color: var(--muted); white-space: pre-wrap; }
.rv-note .tags .tag { margin-right: 4px; }
.rv-filter { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.rv-filter input { width: 240px; border-radius: 999px; padding: 6px 14px; }
.rv-filter .chip { padding: 4px 14px; font-size: 13px; }
.rv-filter .chip.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.rv-range { display: flex; gap: 8px; align-items: center; margin-bottom: 18px; color: var(--muted); }
.rv-range input { width: auto; padding: 4px 10px; border-radius: 999px; font-size: 13px; }
.rv-tl .tl-item { cursor: pointer; margin-bottom: 22px; }
.rv-tl .tl-item .card { margin: 6px 0 0; padding: 12px 16px; transition: border-color .12s; }
.rv-tl .tl-item:hover .card { border-color: var(--accent); }
.rv-tl .day { display: flex; align-items: baseline; gap: 10px; }
.rv-tl .day b { font: 700 16px var(--serif); }
.rv-tl .notes { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.rv-msg { font-size: 12px; padding: 3px 0; border-bottom: 1px dashed var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
table.rv { border-collapse: collapse; width: 100%; font-size: 12px; } table.rv td, table.rv th { border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }
.rv-status { font-size: 12px; color: var(--muted); margin-top: 6px; overflow-wrap: anywhere; }
`;
const STATUS = { todo: '待办', doing: '进行中', done: '完成', partial: '部分', dropped: '放弃' };
const NOTE_KIND = { problem: '问题', lesson: '经验', insight: '洞察', idea: '想法' };
const NOTE_CLS = { problem: 'err', lesson: 'ok', insight: '', idea: 'warn' };
const REC_FIELD = { summary: '总结', wins: '收获', problems: '问题', next_actions: '下一步' };
const MSG_KIND = { new_task: '新任务/追加', correct: '纠正/转向', approve: '确认/继续', interrupt: '中断', answer: '回答提问', check: '询问进度' };
const MSG_CLS = { correct: 'warn', interrupt: 'err', approve: '', check: 'warn', answer: '', new_task: 'ok' };
const TABS = { day: '当日复盘', timeline: '时间线', notes: '问题与经验', agent: 'Agent 效率' };
const WEEK = '日一二三四五六';
const dayLabel = (s) => { const d = new Date(s + 'T12:00:00'); return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]}`; };
const hours = (min) => ((min || 0) / 60).toFixed(1) + 'h';
let onAgentDone;

export default {
  async render(el, ctx) {
    const { api, h, md, toast, openChat, field, ui, sub } = ctx;
    let css = document.getElementById('rv-css');
    if (!css) { css = h('style', { id: 'rv-css' }); document.head.append(css); }
    css.textContent = CSS;
    el.classList.add('rv-wrap');

    const isToday = (d) => d === today();
    const state = { date: /^\d{4}-\d{2}-\d{2}$/.test(sub[0] || '') ? sub[0] : today(), tab: TABS[sub[1]] ? sub[1] : 'day', day: null, noteKind: '' };
    const go = (date, tab) => { location.hash = `#review/${date || state.date}/${tab || state.tab}`; };
    const chatRef = () => ({ module: 'review', ref: state.date, title: `复盘 ${state.date}` });
    const askAgent = (text) => openChat({ ...chatRef(), send: text });

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && (state.tab === 'day' || state.tab === 'notes') && show();
    document.addEventListener('agent-done', onAgentDone);

    // ---------- 顶部：日期 + 问候 + 状态 ----------
    const shift = (n) => { const d = new Date(state.date + 'T12:00:00'); d.setDate(d.getDate() + n); go(d.toLocaleDateString('sv-SE')); };
    const dateIn = h('input', { type: 'date', value: state.date, onchange: (e) => e.target.value && go(e.target.value) });
    const dateBox = h('div.rv-date', {}, [
      h('button', { title: '前一天', onclick: () => shift(-1) }, '‹'),
      h('label', { title: '选择日期' }, [isToday(state.date) ? `今天 · ${dayLabel(state.date)}` : dayLabel(state.date), dateIn]),
      h('button', { title: '后一天', onclick: () => shift(1) }, '›'),
      isToday(state.date) ? null : h('button', { onclick: () => go(today()) }, '回到今天'),
    ]);
    const statusLine = h('div.sub', {}, ' ');
    const heroTitle = isToday(state.date) ? `${ui.greeting()}，今天过得怎么样？` : `回看 ${dayLabel(state.date)}`;

    // ---------- 大输入框 ----------
    const HINTS = {
      note: '前缀「问题: 经验: 洞察: 想法:」定类型 · #标签 · Enter 即存',
      record: '前缀「总结: 收获: 问题: 明天:」选栏目，默认追加到总结',
      ask: '带上这一天的事项、复盘和效率数据问复盘 Agent',
    };
    const comp = ui.composer({
      placeholder: '记一条经验，比如：问题：需求没写验收标准导致返工 #流程',
      autofocus: true, hint: HINTS.note,
      modes: [
        { id: 'note', label: '记一条', placeholder: '记一条经验，比如：问题：需求没写验收标准导致返工 #流程' },
        { id: 'record', label: '写复盘', placeholder: '一句一句写今天的复盘，比如：收获：集成测试脚本跑通了' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：今天哪件事拖得最久，为什么？' },
      ],
      onSubmit: async (text, mode) => {
        try {
          if (mode === 'ask') { askAgent(text); return; }
          if (mode === 'record') {
            const r = await api.post(`/api/review/day/${state.date}/append`, { text });
            toast(`已追加到「${REC_FIELD[r.field] || r.field}」，AI 正在分析怎么改进`);
            if (state.tab !== 'day') go(null, 'day');
          } else {
            const n = await api.post('/api/review/notes/quick', { text, date: state.date });
            toast(`已记一条「${NOTE_KIND[n.kind] || n.kind}」${n.tags ? ' · ' + n.tags.split(',').map((t) => '#' + t).join(' ') : ''}`);
          }
          show();
        } catch (e) { toast(e.message, true); return false; }
      },
    });
    comp.querySelectorAll('.modes button').forEach((b, i) => b.addEventListener('click', () => comp.setHint(HINTS[['note', 'record', 'ask'][i]])));

    const chipRow = ui.chips([
      { label: '检查今天完成情况', icon: 'check', onClick: () => startCheck() },
      { label: '复盘 Agent 效率', icon: 'robot', onClick: () => askAgent('复盘这一天我用 Claude Code / Codex 的效率：人工介入花在哪、哪些不必要、明天怎么减少？') },
      { label: '今天学到了什么', icon: 'bulb', onClick: () => askAgent('根据这一天的事项、记录和提交，总结我学到了什么，挑 1-3 条值得记成经验的。') },
      { label: '看时间线', icon: 'clock', onClick: () => go(null, 'timeline') },
    ]);
    const tabs = h('div.rv-tabs', {}, h('div.tabs', {}, Object.entries(TABS).map(([k, v]) =>
      h('button' + (k === state.tab ? '.active' : ''), { onclick: () => go(null, k) }, v))));
    const body = h('div');
    el.append(h('div.rv-top', {}, dateBox), h('div.hero.rv-hero', {}, [h('h1', {}, heroTitle), statusLine]), comp, chipRow, tabs, body);

    // ---------- 后台任务 ----------
    const watching = new Set();
    const checkState = { status: null };
    async function watch(jobId, label, statusEl) {
      if (watching.has(jobId)) return;
      watching.add(jobId);
      const j = await api.waitJob(jobId, (j) => {
        const last = (j.log || '').trim().split('\n').pop() || '';
        if (statusEl.isConnected) statusEl.textContent = `${label}：${j.status === 'running' ? '进行中' : j.status} ${last.slice(0, 100)}`;
      });
      watching.delete(jobId);
      toast(j.status === 'done' ? `${label}完成` : `${label}失败`, j.status !== 'done');
      if (el.isConnected) show();
    }
    async function startCheck() {
      if (state.tab !== 'day') { go(null, 'day'); setTimeout(() => toast('在「AI 检查建议」卡片里点「开始检查」'), 300); return; }
      try {
        const r = await api.post('/api/review/check', { date: state.date });
        toast('AI 检查已开始，完成后会更新建议');
        await show();
        if (checkState.status) watch(r.job_id, 'AI 检查', checkState.status);
      } catch (e) { toast(e.message, true); }
    }

    async function loadDay() {
      const d = await api.get(`/api/review/day?date=${state.date}`);
      state.day = d;
      const w = d.stats.work, l = d.stats.learning, e = d.efficiency?.summary;
      const parts = [];
      parts.push(w.total ? h('span', {}, [isToday(state.date) ? '今天 ' : '', h('b', {}, `${w.done}/${w.total}`), ' 件事完成']) : '还没有事项');
      if (l.total) parts.push(`学习 ${l.done}/${l.total}`);
      if (d.notes.length) parts.push(`记了 ${d.notes.length} 条`);
      if (e && e.sessions) parts.push(`介入 Agent ${e.human_turns} 次 · 活跃 ${hours(e.active_min_interactive ?? e.active_min)}`);
      statusLine.replaceChildren(...parts.flatMap((p, i) => (i ? [' · ', p] : [p])));
      return d;
    }

    // ---------- 当日复盘 ----------
    const patchTask = async (t, patch) => {
      try { await api.patch(`/api/tasks/${t.id}`, patch); show(); } catch (e) { toast(e.message, true); }
    };
    function taskRow(t, kid = false) {
      const detail = h('div');
      const toggleDetail = () => {
        if (detail.firstChild) return detail.replaceChildren();
        const prog = h('input', { type: 'range', min: 0, max: 100, step: 10, value: t.progress || 0 });
        const pv = h('span', {}, ` ${t.progress || 0}%`);
        prog.oninput = () => { pv.textContent = ` ${prog.value}%`; };
        prog.onchange = () => patchTask(t, { progress: +prog.value, ...(prog.value == 100 ? { status: 'done' } : {}) });
        detail.replaceChildren(h('div.rv-detail', {}, [
          t.goal ? h('div', {}, '目标：' + t.goal) : null,
          t.notes ? h('div', { style: { whiteSpace: 'pre-wrap' } }, t.notes.slice(0, 300)) : null,
          h('div', {}, ['进度 ', prog, pv, t.executor && t.executor !== 'human' ? h('span.tag.line', { style: { marginLeft: '8px' } }, t.executor) : null,
            t.start_time ? h('span', {}, ` · ${t.start_time}${t.end_time ? '–' + t.end_time : ''}`) : null]),
        ]));
      };
      const done = t.status === 'done';
      return h('div.rv-task' + (kid ? '.kid' : '') + (done ? '.done' : '') + (t.status === 'dropped' ? '.dropped' : ''), {}, [
        h('button.rv-check', { title: done ? '标为待办' : '标为完成', onclick: () => patchTask(t, done ? { status: 'todo', progress: 0 } : { status: 'done', progress: 100 }) }, ui.icon('check')),
        h('div.t', {}, [h('span', { onclick: toggleDetail, title: '点开看目标和进度' }, t.title), detail]),
        ['doing', 'partial', 'dropped'].includes(t.status) ? h('span.tag.rv-st.' + (t.status === 'dropped' ? 'gray' : 'warn'), {}, STATUS[t.status]) : null,
        h('div.rv-pills', {}, ['doing', 'partial', 'dropped'].map((s) => h('button' + (t.status === s ? '.on' : ''), {
          onclick: () => patchTask(t, { status: t.status === s ? 'todo' : s }) }, STATUS[s]))),
      ]);
    }
    const flat = (items) => items.flatMap((t) => [[t, false], ...(t.children || []).map((c) => [c, true])]);
    function taskList(items, limit = 7) {
      const rows = flat(items);
      const box = h('div');
      const draw = (n) => {
        box.replaceChildren(...rows.slice(0, n).map(([t, k]) => taskRow(t, k)));
        if (rows.length > n) box.append(h('button.ghost.sm.rv-more', { onclick: () => draw(rows.length) }, `展开全部 ${rows.length} 项`));
      };
      draw(limit);
      return box;
    }

    function tasksCard(d) {
      const w = d.stats.work;
      return h('div.card.rv-tasks', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, '今日事项完成'), h('a.muted', { href: '#plan' }, '去规划 →')]),
        w.total ? h('div.rv-big', {}, [h('span.num', {}, `${w.done}/${w.total}`), h('span.muted', {}, `平均进度 ${w.avg_progress}%`)]) : null,
        w.total ? ui.progress(w.total ? (w.done / w.total) * 100 : 0) : null,
        d.tasks.length ? h('div', { style: { marginTop: '10px' } }, taskList(d.tasks))
          : ui.empty('这一天没有事项', '去「规划」排一下，或让 Agent 帮你拆解'),
      ]);
    }

    function suggCard(d) {
      const rec = d.record;
      const sugg = rec.task_suggestions || [];
      const all = flat([...d.tasks, ...d.learning]).map(([t]) => t);
      const titleOf = (id) => all.find((t) => t.id === id)?.title || '';
      const pending = sugg.map((s, i) => ({ ...s, i })).filter((s) => !s.applied && !s.dismissed);
      const status = h('div.rv-status');
      checkState.status = status;
      const running = d.jobs.find((j) => j.ref.startsWith('check:') && ['queued', 'running'].includes(j.status));
      if (running) { status.textContent = 'AI 检查进行中…'; watch(running.id, 'AI 检查', status); }
      const apply = async (i) => { await api.post(`/api/review/suggestions/${state.date}/${i}/apply`); };
      const runBtn = h('button' + (sugg.length || rec.ai_analysis ? '.ghost.sm' : '.dark'), { disabled: !!running, onclick: startCheck },
        [ui.icon('spark'), running ? '检查中' : sugg.length || rec.ai_analysis ? '重新检查' : '开始检查']);
      const desc = (s) => [s.status ? STATUS[s.status] || s.status : null, s.progress != null ? s.progress + '%' : null].filter(Boolean).join(' · ');
      return h('div.card', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, 'AI 检查建议'), sugg.length || rec.ai_analysis ? runBtn : null]),
        pending.length ? h('div', {}, [
          ...pending.slice(0, 3).map((s) => h('div.rv-sugg', {}, [
            h('div.ttl', {}, [titleOf(s.task_id) || `#${s.task_id}`, desc(s) ? h('span.tag', { style: { marginLeft: '6px' } }, '→ ' + desc(s)) : null]),
            s.evidence ? h('div.muted.clamp2', { title: s.evidence }, s.evidence) : null,
            s.problem ? h('div.clamp2', { style: { fontSize: '12px', color: 'var(--warn)' } }, '问题：' + s.problem) : null,
            h('div.row', {}, [
              h('button.primary.sm', { onclick: async () => { await apply(s.i); toast('已采纳'); show(); } }, '采纳'),
              h('button.outline.sm', { onclick: async () => { await api.post(`/api/review/suggestions/${state.date}/${s.i}/dismiss`); show(); } }, '忽略'),
            ]),
          ])),
          pending.length > 1 ? h('button.ghost.sm', { onclick: async () => { for (const s of pending) await apply(s.i); toast(`已采纳 ${pending.length} 条`); show(); } },
            `全部采纳（${pending.length}）`) : null,
        ]) : sugg.length || rec.ai_analysis
          ? h('div', {}, [h('h3', {}, sugg.length ? '建议都处理完了' : '检查完成'),
            h('div.muted', {}, `采纳 ${sugg.filter((s) => s.applied).length} 条（其中有证据、自动写回 ${sugg.filter((s) => s.auto).length} 条）· 忽略 ${sugg.filter((s) => s.dismissed).length} 条`)])
          : h('div', {}, [h('h3', {}, '今天做完了吗？让 AI 对照证据看看'),
            h('div.muted', { style: { margin: '-2px 0 12px' } }, '对照目标看当天 git 提交、改动文件和文档，给出每件事的完成度建议。'), runBtn]),
        status,
      ]);
    }

    function effCard(d) {
      const e = d.efficiency?.summary;
      return h('div.card', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, 'Agent 效率'), h('a.muted', { href: `#review/${state.date}/agent` }, '详情 →')]),
        e && e.sessions ? h('div.rv-tiles', {}, [
          ['人工介入', `${e.human_turns}次`], ['Agent 活跃', hours(e.active_min_interactive ?? e.active_min)],
          ['等待中位', `${e.wait_median_min}分`], ['峰值并行', e.peak_parallel],
        ].map(([k, v]) => h('div.stat', {}, [h('span.v', {}, String(v)), h('span.k', {}, k)])))
          : h('div', {}, [h('h3', {}, e ? '这一天没有 Agent 会话' : '还没扫描 Agent 会话'),
            h('div.muted', { style: { margin: '-2px 0 12px' } }, '统计 Claude Code / Codex 的人工介入、等待与并行。')]),
        e && e.sessions ? h('div.muted', {}, `纠正 ${e.kinds?.correct || 0} · 中断 ${e.kinds?.interrupt || 0} · 工具错误 ${e.tool_errors}/${e.tool_calls}`)
          : h('button.dark', { onclick: () => go(null, 'agent') }, [ui.icon('refresh'), '扫描会话']),
      ]);
    }

    function recordCard(rec) {
      const entries = rec.entries || [];
      const view = entries.length ? h('div.rv-entries', {}, entries.map((e) => h('div.rv-entry', {}, [
        h('span.t', { title: e.at ? e.at.replace('T', ' ') : '没记时间（老记录或手动编辑）' }, e.time ? (e.next_day ? `次日 ${e.time}` : e.time) : '—'),
        h('span.f', {}, REC_FIELD[e.field] || e.field), h('span.x', {}, e.text)])))
        : h('div.muted', {}, '还没写复盘。用上方「写复盘」一句句追加，每条会记下时间，按时间线排在这里。');
      const formBox = h('div');
      const editBtn = h('button.ghost.sm', { onclick: () => {
        if (formBox.firstChild) { formBox.replaceChildren(); editBtn.lastChild.textContent = '展开详细'; return; }
        const ta = (k) => h('textarea', { rows: 3, value: rec[k] || '', placeholder: REC_FIELD[k] });
        const fs = Object.fromEntries(Object.keys(REC_FIELD).map((k) => [k, ta(k)]));
        formBox.replaceChildren(h('div.rv-form', {}, [...Object.entries(fs).map(([k, t]) => field(REC_FIELD[k], t)),
          h('div', {}, h('button.primary', { onclick: async () => {
            await api.put(`/api/review/day/${state.date}`, Object.fromEntries(Object.entries(fs).map(([k, v]) => [k, v.value])));
            toast('已保存'); show();
          } }, [ui.icon('check'), '保存复盘']))]));
        fs.summary.focus();
        editBtn.lastChild.textContent = '收起';
      } }, [ui.icon('edit'), h('span', {}, '展开详细')]);
      return h('div.card', {}, [h('div', { style: { float: 'right' } }, editBtn), view, formBox]);
    }

    function improveCard(d) {
      const rec = d.record;
      const status = h('div.rv-status');
      const running = d.jobs.find((j) => j.ref.startsWith('improve:') && ['queued', 'running'].includes(j.status));
      if (running) { status.textContent = 'AI 正在结合当天会话和学习反馈分析…'; watch(running.id, '改进分析', status); }
      const run = async () => {
        try { await api.post('/api/review/improve', { date: state.date }); toast('改进分析已开始'); show(); } catch (e) { toast(e.message, true); }
      };
      const btn = h('button' + (rec.improve_md ? '.ghost.sm' : '.dark'), { disabled: !!running, onclick: run },
        [ui.icon('spark'), running ? '分析中' : rec.improve_md ? '重新分析' : '分析怎么改进']);
      return h('div.card.rv-improve', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, 'AI 改进分析 · 结合当天会话与学习反馈'), rec.improve_md ? btn : null]),
        rec.improve_md ? h('div.md', {}, md(rec.improve_md))
          : h('div', {}, [h('div.muted', { style: { margin: '2px 0 12px' } },
            (rec.entries || []).length ? '每次写复盘后会自动分析；也可以手动开始。' : '写下复盘后，AI 会把每条放回当天时间线，对照会话和学习记录找根因、给改进。'),
          (rec.entries || []).length && !running ? btn : null]),
        status,
      ]);
    }

    function noteCard(n, after) {
      return h('div.card.rv-note', {}, [
        h('div.head', {}, [h('span.tag.' + (NOTE_CLS[n.kind] || ''), {}, NOTE_KIND[n.kind] || n.kind),
          n.date !== state.date ? h('a.muted', { href: `#review/${n.date}/day` }, dayLabel(n.date)) : null,
          h('button.icon.del', { title: '删除', onclick: async () => { if (confirm('删除这条记录？')) { await api.del(`/api/review/notes/${n.id}`); after(); } } }, ui.icon('trash'))]),
        n.title ? h('div.ttl', {}, n.title) : null,
        n.content ? h('div.ct.clamp3', { title: n.content }, n.content) : null,
        n.tags ? h('div.tags', {}, n.tags.split(',').filter(Boolean).map((t) => h('span.tag.line', {}, '#' + t.trim()))) : null,
      ]);
    }

    async function renderDay() {
      const d = await loadDay();
      const rec = d.record;
      const lx = d.learning_extra;
      const nodes = [
        ui.section('我的复盘', '按写下的时间排列 · 用上方「写复盘」一句句追加'), recordCard(rec), improveCard(d),
        ui.section(isToday(state.date) ? '今天的进展' : '这一天的进展', dayLabel(state.date)),
        h('div.rv-cards', {}, [tasksCard(d), suggCard(d), effCard(d)]),
        await deliveries({ api, h, ui }, { date: state.date }),
      ];
      if (d.learning.length || lx.steps.length || lx.items.length || lx.events?.length) {
        nodes.push(ui.section('学习'), h('div.card', {}, [
          d.learning.length ? taskList(d.learning) : null,
          lx.steps.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '深度学习步骤'),
            ...lx.steps.map((s) => h('div.item', {}, [h('span.tag' + (s.status === 'done' ? '.ok' : '.gray'), {}, s.status), s.plan_topic ? h('span.muted', {}, s.plan_topic + ' · ') : null, s.title,
              s.understanding ? h('span.muted', {}, ` 理解 ${s.understanding}/5`) : null]))]) : null,
          lx.items.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '完成的论文 / 代码解析'),
            ...lx.items.map((i) => h('div.item', {}, [h('span.tag', {}, i.kind), i.title || i.url]))]) : null,
          lx.events?.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '学习记录（测试 / 停一下 / 理解度）'),
            ...lx.events.map((x) => h('div.item', { style: { fontSize: '13px' } }, x))]) : null,
        ]));
      }
      if (rec.ai_analysis) nodes.push(h('details.card.flat', {}, [h('summary', {}, 'AI 检查完整分析'), md(rec.ai_analysis)]));
      nodes.push(ui.section('问题与经验', d.notes.length ? `${d.notes.length} 条` : ''),
        d.notes.length ? h('div.rv-notes', {}, d.notes.map((n) => noteCard(n, show)))
          : ui.empty('还没有记录', '在上方「记一条」里写一句，Enter 就存好了'));
      body.replaceChildren(...nodes);
    }

    // ---------- 时间线 ----------
    async function renderTimeline() {
      loadDay();
      const s = new Date(state.date + 'T12:00:00'); s.setDate(s.getDate() - 29);
      const startIn = h('input', { type: 'date', value: s.toLocaleDateString('sv-SE') });
      const endIn = h('input', { type: 'date', value: state.date });
      const list = h('div.timeline.rv-tl');
      const load = async () => {
        const days = await api.get(`/api/review/timeline?start=${startIn.value}&end=${endIn.value}`);
        list.replaceChildren(...(days.length ? days.map((x) => {
          const t = x.tasks, l = x.learning;
          const active = t.done || l.done || x.notes.length || x.summary;
          return h('div.tl-item' + (active ? '' : '.dim'), { onclick: () => go(x.date, 'day') }, [
            h('div.day', {}, [h('b', {}, dayLabel(x.date)), isToday(x.date) ? h('span.tag', {}, '今天') : null,
              t.total ? h('span.muted', {}, `事项 ${t.done}/${t.total} · ${t.avg_progress}%`) : null,
              l.total ? h('span.muted', {}, `学习 ${l.done}/${l.total}`) : null,
              x.has_ai ? h('span.tag.ok', {}, 'AI 已检查') : null]),
            x.summary || x.notes.length || x.efficiency ? h('div.card', {}, [
              x.summary ? h('div.clamp3', { style: { fontSize: '14px' } }, x.summary) : null,
              x.notes.length ? h('div.notes', {}, x.notes.slice(0, 6).map((n) => h('span.tag.' + (NOTE_CLS[n.kind] || ''), {}, `${NOTE_KIND[n.kind] || n.kind} · ${n.title}`))) : null,
              x.efficiency ? h('div.muted', { style: { marginTop: '6px' } }, x.efficiency) : null,
            ]) : null,
          ]);
        }) : [ui.empty('这段时间没有记录')]));
      };
      startIn.onchange = endIn.onchange = load;
      body.replaceChildren(ui.section('时间线', '点某一天进入当日复盘'), h('div.rv-range', {}, [startIn, '—', endIn]), list);
      await load();
    }

    // ---------- 问题与经验 ----------
    async function renderNotes() {
      loadDay();
      const q = h('input', { placeholder: '搜索标题 / 内容 / 标签' });
      const list = h('div.rv-notes');
      const count = h('span');
      const load = async () => {
        const ns = await api.get(`/api/review/notes?q=${encodeURIComponent(q.value)}&kind=${state.noteKind}`);
        count.textContent = `${ns.length} 条`;
        list.replaceChildren(...(ns.length ? ns.map((n) => noteCard(n, load)) : [ui.empty('没有记录', '在上方「记一条」里写一句')]));
      };
      const kindChips = [['', '全部'], ...Object.entries(NOTE_KIND)].map(([k, v]) => h('button.chip' + (state.noteKind === k ? '.on' : ''), {
        onclick: (e) => { state.noteKind = k; kindChips.forEach((b) => b.classList.toggle('on', b === e.currentTarget)); load(); } }, v));
      q.addEventListener('input', () => { clearTimeout(q._t); q._t = setTimeout(load, 250); });
      body.replaceChildren(ui.section('问题与经验', count), h('div.rv-filter', {}, [q, ...kindChips]), list);
      await load();
    }

    // ---------- Agent 效率 ----------
    async function renderAgent(refresh = false) {
      loadDay();
      body.replaceChildren(ui.empty('扫描会话日志中…', '读取当天 Claude Code / Codex 会话'));
      const e = await api.get(`/api/review/efficiency?date=${state.date}${refresh ? '&refresh=1' : ''}`);
      const a = e.summary;
      const status = h('div.rv-status');
      const reflectBtn = h('button.primary', { onclick: async () => {
        reflectBtn.disabled = true;
        const r = await api.post('/api/review/reflect', { date: state.date });
        watch(r.job_id, 'AI 反思', status);
      } }, [ui.icon('spark'), e.reflection ? '重新反思' : 'AI 反思']);
      if (e.reflect_job && ['queued', 'running'].includes(e.reflect_job.status)) { reflectBtn.disabled = true; watch(e.reflect_job.id, 'AI 反思', status); }
      const nodes = [
        h('div.row.between', { style: { margin: '28px 0 12px' } }, [
          h('div', {}, [h('h2', { style: { margin: 0, fontSize: '20px' } }, 'Claude Code / Codex 效率'),
            h('div.muted', {}, '扫描于 ' + (e.scanned_at || '').slice(11, 16) + ' · 分类为启发式规则（首条=新任务；「继续/好」=确认；含「不对/应该」=纠正）')]),
          h('div.row', {}, [h('button.ghost', { onclick: () => renderAgent(true) }, [ui.icon('refresh'), '重新扫描']), reflectBtn])]),
        ui.stats([
          { k: '交互 + 自动会话', v: `${a.interactive || 0}+${a.automated || 0}` }, { k: '人工介入', v: a.human_turns ?? 0 },
          { k: `Agent 活跃（含自动 ${hours(a.active_min)}）`, v: hours(a.active_min_interactive ?? a.active_min) },
          { k: `Agent 等你（墙钟，同看板 · 各会话累加 ${a.wait_total_min ?? 0}分）`, v: `${a.wait_wall_min ?? a.wait_total_min ?? 0}分` }, { k: '等待中位', v: `${a.wait_median_min ?? 0}分` },
          { k: '峰值并行', v: a.peak_parallel ?? 0 }, { k: `工具错误 / 调用 · 权限拒绝 ${a.denials ?? 0}`, v: `${a.tool_errors ?? 0}/${a.tool_calls ?? 0}` },
          { k: '平台任务失败 / 总', v: `${a.platform_jobs_failed || 0}/${a.platform_jobs || 0}` },
        ]),
        h('div', { style: { marginBottom: '14px' } }, Object.entries(a.kinds || {}).map(([k, v]) => h('span.tag.' + (MSG_CLS[k] || ''), {}, `${MSG_KIND[k] || k} ${v}`))),
        status,
        e.reflection ? h('div.card', {}, [h('span.card-label', {}, 'AI 反思'), md(e.reflection)])
          : h('div.card.flat', {}, [h('span.card-label', {}, 'AI 反思'), h('div.muted', {}, '还没有反思。点右上「AI 反思」，让 Agent 分析人工介入是否必要、怎么减少。')]),
      ];
      const inter = e.sessions.filter((s) => !s.automated || s.human_turns);
      const auto = e.sessions.filter((s) => s.automated && !s.human_turns);
      nodes.push(ui.section('交互会话', `${inter.length} 个`), inter.length ? h('div.card', {}, h('div.list', {}, inter.map((s) => h('details.item', {}, [
        h('summary', {}, [h('span.tag', {}, s.engine), h('b', {}, s.project), ' ', h('span.muted', {}, (s.title || '').slice(0, 40)), ' ',
          h('span.muted', {}, `${s.start.slice(11, 16)}–${s.end.slice(11, 16)} · 活跃 ${s.active_min} / 墙钟 ${s.wall_min} 分 · 介入 ${s.human_turns} · 工具 ${s.tool_calls}（错 ${s.tool_errors}，拒 ${s.denials}）`)]),
        h('div', { style: { margin: '6px 0' } }, Object.entries(s.kinds).filter(([, v]) => v).map(([k, v]) => h('span.tag.' + (MSG_CLS[k] || ''), {}, `${MSG_KIND[k]} ${v}`))),
        ...s.messages.map((m) => h('div.rv-msg', {}, [h('span.muted', {}, `${m.t}${m.wait_min != null ? ` 等${m.wait_min}分` : ''} `),
          h('span.tag.' + (MSG_CLS[m.kind] || ''), {}, MSG_KIND[m.kind] || m.kind), m.text])),
      ])))) : ui.empty('没有交互会话'));
      if (auto.length) {
        const byProj = {};
        for (const s of auto) { const p = byProj[s.project] ||= { n: 0, min: 0, tools: 0, err: 0 }; p.n++; p.min += s.active_min; p.tools += s.tool_calls; p.err += s.tool_errors; }
        nodes.push(h('details.card.flat', {}, [h('summary', {}, `自动化会话（${auto.length}，claude -p / codex exec）`),
          h('table.rv', {}, [h('tr', {}, ['项目', '会话', '活跃分钟', '工具', '错误'].map((x) => h('th', {}, x))),
            ...Object.entries(byProj).map(([p, v]) => h('tr', {}, [p, v.n, v.min.toFixed(1), v.tools, v.err].map((x) => h('td', {}, String(x)))))])]));
      }
      const pr = e.platform || {};
      if ((pr.jobs || []).length || (pr.plan_runs || []).length) {
        nodes.push(h('details.card.flat', {}, [h('summary', {}, `本平台后台任务（${(pr.jobs || []).length}）· 规划自动执行（${(pr.plan_runs || []).length}）`),
          h('table.rv', {}, [h('tr', {}, ['#', '板块', 'ref', '引擎', '状态', '分钟'].map((x) => h('th', {}, x))),
            ...(pr.jobs || []).map((j) => h('tr', {}, [j.id, j.module, j.ref, j.engine, j.status, j.minutes ?? '-'].map((x) => h('td', {}, String(x)))))]),
          ...(pr.plan_runs || []).map((r) => h('div.item', {}, `#${r.task_id} ${r.task_title || ''} · ${r.engine} · ${r.status}`))]));
      }
      // 时间利用：真实事件铺到时间轴上，看空档、专注外交互、等你的时间
      nodes.splice(2, 0, ui.section('时间利用', 'Agent 是否跑满 · 人工交互是否在专注时间'), await utilization({ api, h, ui }, { date: state.date }));
      body.replaceChildren(h('div.rv-agent', {}, nodes));
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
