// 复盘（首页）：问候 + 一句话状态 + 大输入框（记一条 / 问 Agent）+ 今日三卡（事项 / AI 建议 / Agent 效率）
// 标签页：当日复盘（复盘 / Agent 效率 / 人工效率）/ 时间线 / 问题与经验 / 已读历史。路由：#review/<YYYY-MM-DD>/<tab>/<view>
import { today } from '../api.js';
import { utilization } from './_utilchart.js';
import { deliveries } from './_deliveries.js';
import { coreMetrics } from './_coremetrics.js';
import { approvals } from './_approvals.js';
import { agentBoard, agentPatterns } from './_agentboard.js';
import { annotate } from './_annotate.js';

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
.rv-away { display: flex; flex-direction: column; align-items: center; margin: 10px 0 18px; text-align: center; }
.rv-away-go { flex: none; justify-content: center; width: 148px; height: 148px; padding: 0; border-radius: 50%; border: none; font-size: 22px; font-weight: 700; box-shadow: var(--shadow); }
.rv-away-go.back { background: var(--ok); color: #fff; }
.rv-away-go.back:hover { background: var(--ok); opacity: .92; }
.rv-away-go.send { width: 96px; height: 96px; font-size: 18px; }
.rv-away-hint { margin-top: 10px; font-size: 13px; color: var(--muted); }
.rv-away-timer { font-size: 36px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--accent); margin: 2px 0 12px; }
.rv-away-head { font-size: 15px; color: var(--muted); }
.rv-away-sum { font-size: 22px; font-weight: 700; margin: 2px 0 12px; }
.rv-away-kinds { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 12px; }
.rv-away-gain { width: 100%; max-width: 420px; font-size: 16px; padding: 12px 14px; margin-bottom: 14px; box-sizing: border-box; }
.rv-away-cancel { margin-top: 10px; }
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
@media (max-width: 760px) { .rv-rec { grid-template-columns: 1fr; } }
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
.rv-areas { display: flex; flex-direction: column; gap: 18px; }
.rv-area-name { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.rv-aspects { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px; }
@media (max-width: 760px) { .rv-aspects { grid-template-columns: 1fr; } }
.rv-aspect { min-width: 0; }
.rv-aspect label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
.rv-area input { width: 100%; box-sizing: border-box; }
.rv-area-past { margin-top: 8px; max-height: 200px; overflow-y: auto; border-left: 2px solid var(--note-teal); padding-left: 10px; }
.rv-area-past > div { display: grid; grid-template-columns: 44px 1fr; gap: 8px; align-items: baseline; padding: 3px 0; font-size: 13px; }
.rv-area-past .t { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.rv-area-past .x { white-space: pre-wrap; overflow-wrap: anywhere; }
.rv-area-save { display: flex; justify-content: flex-end; margin-top: 14px; }
.rv-tl .notes { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.rv-msg { font-size: 12px; padding: 3px 0; border-bottom: 1px dashed var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
table.rv { border-collapse: collapse; width: 100%; font-size: 12px; } table.rv td, table.rv th { border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }
.rv-status { font-size: 12px; color: var(--muted); margin-top: 6px; overflow-wrap: anywhere; }
.rv-views { justify-content: center; margin: 12px 0 0; }
.rv-fold > summary { display: flex; align-items: baseline; gap: 10px; list-style: none; }
.rv-fold > summary::-webkit-details-marker { display: none; }
.rv-fold > summary::before { content: '▸'; color: var(--muted); font-size: 12px; }
.rv-fold[open] > summary::before { content: '▾'; }
.rv-fold > summary .card-label { margin: 0; flex: none; }
.rv-fold > summary .muted { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rv-fold[open] > summary { margin-bottom: 12px; }
.rv-fold[open] > summary .muted { white-space: normal; }
.rv-fold-actions { display: flex; justify-content: flex-end; margin-top: 10px; }
.rv-human { --t-开发: #2a78d6; --t-学习: #eb6834; --t-思考复盘: #1baf7a; --t-运动: #eda100; --t-吃饭: #e87ba4; --t-睡觉: #008300; --t-其他: #6250d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .rv-human { --t-开发: #3987e5; --t-学习: #d95926; --t-思考复盘: #199e70; --t-运动: #c98500; --t-吃饭: #d55181; --t-其他: #9085e9; } }
:root[data-theme="dark"] .rv-human { --t-开发: #3987e5; --t-学习: #d95926; --t-思考复盘: #199e70; --t-运动: #c98500; --t-吃饭: #d55181; --t-其他: #9085e9; }
.rv-tl-row { display: grid; grid-template-columns: 22px 1fr; gap: 8px; align-items: end; margin-bottom: 10px; }
.rv-tl-hour { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; line-height: 26px; }
.rv-tl-track { position: relative; height: 26px; background: var(--bg-2); border-radius: 4px; overflow: hidden; }
.rv-tl-seg { position: absolute; top: 0; bottom: 0; min-width: 3px; padding: 0; border: 0; border-radius: 0; cursor: pointer; box-shadow: inset -1px 0 0 var(--panel); }
.rv-tl-seg:hover, .rv-tl-seg.on { top: -1px; bottom: -1px; outline: 2px solid var(--text); outline-offset: -2px; z-index: 1; }
.rv-tl-seg.blank { background: repeating-linear-gradient(135deg, var(--line-2) 0 3px, transparent 3px 7px); }
.rv-tl-ticks { position: relative; height: 15px; font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.rv-tl-ticks span { position: absolute; transform: translateX(-50%); }
.rv-tl-ticks span:first-child { transform: none; }
.rv-tl-detail { min-height: 20px; margin-bottom: 12px; font-size: 13px; overflow-wrap: anywhere; }
.rv-tl-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 4px; font-size: 13px; }
.rv-tl-legend span { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); font-variant-numeric: tabular-nums; }
.rv-tl-legend b { font-weight: 500; color: var(--text); }
.rv-tl-dot { flex: none; display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.rv-tl-dot.blank { background: repeating-linear-gradient(135deg, var(--muted) 0 2px, transparent 2px 4px); }
.rv-time-row .tag.seg { display: inline-flex; gap: 5px; align-items: center; background: none; color: var(--text); padding: 0; white-space: nowrap; }
.rv-human .stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 900px) { .rv-human .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.rv-trend { display: flex; flex-direction: column; gap: 6px; }
.rv-trend-row { display: grid; grid-template-columns: 96px 1fr 104px; gap: 10px; align-items: center; font-size: 13px; cursor: pointer; }
.rv-trend-row.on { font-weight: 600; }
.rv-trend-bar { height: 10px; background: var(--bg-2); border-radius: 999px; overflow: hidden; }
.rv-trend-fill { height: 100%; background: var(--line-2); border-radius: 999px; overflow: hidden; }
.rv-trend-whole { height: 100%; background: var(--accent); }
.rv-trend-row .n { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
.rv-time-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.rv-time-form select, .rv-time-form input[type=time] { width: auto; }
.rv-time-form .out { flex: 1; min-width: 200px; }
.rv-time-row { display: grid; grid-template-columns: 124px 72px 1fr auto; gap: 10px; align-items: baseline; padding: 7px 0; border-top: 1px dashed var(--line); font-size: 14px; }
.rv-time-row .t { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.rv-time-row .x { overflow-wrap: anywhere; }
.rv-time-row .ops { display: flex; gap: 4px; }
@media (max-width: 760px) { .rv-time-row { grid-template-columns: 1fr auto; } .rv-time-row .x { grid-column: 1 / -1; } }
`;
const STATUS = { todo: '待办', doing: '进行中', done: '完成', partial: '部分', dropped: '放弃' };
const NOTE_KIND = { problem: '问题', lesson: '经验', insight: '洞察', idea: '想法', spark: '灵感', feeling: '感想', review: '复盘' };
const SYS_KINDS = ['problem', 'lesson', 'insight', 'idea']; // 系统记录用的类型；灵感、感想只在便签里
const NOTE_CLS = { problem: 'err', lesson: 'ok', insight: '', idea: 'warn' };
const REC_FIELD = { summary: '总结', wins: '收获', problems: '问题', next_actions: '下一步' };
const MSG_KIND = { new_task: '新任务/追加', correct: '纠正/转向', approve: '确认/继续', interrupt: '中断', answer: '回答提问', check: '询问进度' };
const MSG_CLS = { correct: 'warn', interrupt: 'err', approve: '', check: 'warn', answer: '', new_task: 'ok' };
const REVIEW_AREAS = ['产品迭代', '个人效率', 'AI协作', '学习提升'];
const REVIEW_ASPECTS = { 做得好的: '做成了什么、有什么收获，写在这一行', 有问题的: '哪里有问题、下一步怎么办，写在这一行' };
const reviewDraft = {};
const TABS = { day: '当日复盘', timeline: '时间线', notes: '问题与经验', reads: '已读历史' };
const DAY_VIEWS = { review: '复盘', agent: 'Agent 效率', human: '人工效率' };
const FRAGMENT_TARGET = 70;
const foldOverride = {};
const firstLine = (text) => (text || '').replace(/[#*`>_-]/g, '').trim().split('\n')[0].slice(0, 80);
const WEEK = '日一二三四五六';
const dayLabel = (s) => { const d = new Date(s + 'T12:00:00'); return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]}`; };
const hours = (min) => ((min || 0) / 60).toFixed(1) + 'h';
let onAgentDone;
let onQuickNote;

export default {
  async render(el, ctx) {
    const { api, h, md, toast, openChat, ui, sub } = ctx;
    let css = document.getElementById('rv-css');
    if (!css) { css = h('style', { id: 'rv-css' }); document.head.append(css); }
    css.textContent = CSS;
    el.classList.add('rv-wrap');

    const isToday = (d) => d === today();
    const state = { date: /^\d{4}-\d{2}-\d{2}$/.test(sub[0] || '') ? sub[0] : today(), tab: TABS[sub[1]] ? sub[1] : 'day', view: sub[1] === 'day' && DAY_VIEWS[sub[2]] ? sub[2] : 'review', day: null, noteKind: '' };
    const go = (date, tab, view) => {
      const t = tab || state.tab, v = t === 'day' ? view || (tab ? 'review' : state.view) : 'review';
      location.hash = `#review/${date || state.date}/${t}${v === 'review' ? '' : `/${v}`}`;
    };
    const foldCard = (key, label, note, defaultOpen, content, cls = '') => {
      const id = `${state.date}:${key}`;
      return h('details.card.rv-fold' + cls, { open: foldOverride[id] ?? defaultOpen, ontoggle: (e) => {
        if (e.currentTarget.open === defaultOpen) delete foldOverride[id];
        else foldOverride[id] = e.currentTarget.open;
      } }, [h('summary', {}, [h('span.card-label', {}, label), note ? h('span.muted', {}, note) : null]), ...content]);
    };
    const chatRef = () => ({ module: 'review', ref: state.date, title: `复盘 ${state.date}` });
    const askAgent = (text) => openChat({ ...chatRef(), send: text });

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && (state.tab === 'notes' || (state.tab === 'day' && state.view === 'review')) && show();
    document.addEventListener('agent-done', onAgentDone);
    if (onQuickNote) document.removeEventListener('quick-note', onQuickNote);
    onQuickNote = () => el.isConnected && state.view !== 'human' && !el.querySelector('.composer textarea')?.value.trim() && show();
    document.addEventListener('quick-note', onQuickNote);

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
      note: '贴到「便签」页 · 前缀「问题: 经验: 灵感: 感想:」定类型 · #标签 · Enter 即存 · 任何页面 ⌘K 随手记',
      ask: '带上这一天的事项、复盘和效率数据问复盘 Agent',
    };
    const comp = ui.composer({
      placeholder: '记一条，会贴到便签，比如：问题：需求没写验收标准导致返工 #流程',
      autofocus: true, hint: HINTS.note,
      modes: [
        { id: 'note', label: '记一条', placeholder: '记一条，会贴到便签，比如：问题：需求没写验收标准导致返工 #流程' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：今天哪件事拖得最久，为什么？' },
      ],
      onSubmit: async (text, mode) => {
        try {
          if (mode === 'ask') { askAgent(text); return; }
          const n = await api.post('/api/review/notes/quick', { text, date: state.date });
          toast(`已贴到便签「${NOTE_KIND[n.kind] || n.kind}」${n.tags ? ' · ' + n.tags.split(',').map((t) => '#' + t).join(' ') : ''}`);
          show();
        } catch (e) { toast(e.message, true); return false; }
      },
    });
    comp.querySelectorAll('.modes button').forEach((b, i) => b.addEventListener('click', () => comp.setHint(HINTS[['note', 'ask'][i]])));

    const askBoard = (text) => openChat({ module: 'agents', title: 'Agent 看板', send: text });
    const chipRow = ui.chips(state.tab === 'day' && state.view === 'agent' ? [
      { label: '哪些在等我？', icon: 'bulb', onClick: () => askBoard('看一下 Agent 看板：哪些会话在等我处理？按紧急程度列出，每条一句话说明在等什么、建议怎么做。') },
      { label: '总结各 Agent 进展', icon: 'review', onClick: () => askBoard('总结一下最近 24 小时各个 Agent 会话的进展：运行中的到哪一步了，待验收的做成了什么。') },
      { label: '卡住的怎么处理', icon: 'bolt', onClick: () => askBoard('看板里「可能卡住」「等待批准」「已中断」的会话，分别可能是什么原因，怎么处理最快？') },
      { label: '这天交付了什么', icon: 'check', onClick: () => askBoard(`${state.date} 已经交付了哪几件事（有推送/部署/PR/发布或文档材料，之后没再改的）？每件一句话说清交付物；再列出交付后仍在改、或只提交没推送的。`) },
      { label: '这天哪里没利用好', icon: 'clock', onClick: () => askBoard(`结合时间利用统计，分析 ${state.date} 哪些时间没利用好、哪些人工交互不在高效时间，给出 3 条最有用的改进。`) },
      { label: '据此优化明天的规划', icon: 'plan', onClick: () => openChat({ module: 'plan', title: '规划', send: '结合「时间利用」统计和近 7 天规律，帮我调整明天的拆解与排程：需要人来回交互的放进专注时间，能自动跑的填满空档和专注时间外。' }) },
    ] : [
      { label: '检查今天完成情况', icon: 'check', onClick: () => startCheck() },
      { label: '复盘 Agent 效率', icon: 'robot', onClick: () => askAgent('复盘这一天我用 Claude Code / Codex 的效率：人工介入花在哪、哪些不必要、明天怎么减少？') },
      { label: '今天学到了什么', icon: 'bulb', onClick: () => askAgent('根据这一天的事项、记录和提交，总结我学到了什么，挑 1-3 条值得记成经验的。') },
      { label: '看时间线', icon: 'clock', onClick: () => go(null, 'timeline') },
    ]);
    const tabs = h('div.rv-tabs', {}, h('div.tabs', {}, Object.entries(TABS).map(([k, v]) =>
      h('button' + (k === state.tab ? '.active' : ''), { onclick: () => go(null, k) }, v))));
    const views = state.tab === 'day' ? [h('div.tabs.rv-views', {}, Object.entries(DAY_VIEWS).map(([k, v]) =>
      h('button' + (k === state.view ? '.active' : ''), { onclick: () => go(null, 'day', k) }, v)))] : [];
    if (state.tab === 'day' && state.view === 'agent') el.classList.add('ag-wide');
    const body = h('div');
    el.append(h('div.rv-top', {}, dateBox), h('div.hero.rv-hero', {}, [h('h1', {}, heroTitle), statusLine]), comp, chipRow, tabs, ...views, body);

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
      if (state.tab !== 'day' || state.view !== 'review') { go(null, 'day', 'review'); setTimeout(() => toast('在「AI 检查建议」卡片里点「开始检查」'), 300); return; }
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
      const checked = sugg.length || rec.ai_analysis;
      const note = pending.length ? `${pending.length} 条待处理` : running ? '检查中' : checked ? '已处理完' : '';
      return foldCard('sugg', 'AI 检查建议', note, !checked || !!running || pending.length > 0, [
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
        checked ? h('div.rv-fold-actions', {}, runBtn) : null,
        status,
      ]);
    }

    function effCard(d) {
      const e = d.efficiency?.summary;
      return h('div.card', {}, [
        h('div.row.between', {}, [h('span.card-label', {}, 'Agent 效率'), h('a.muted', { href: `#review/${state.date}/day/agent` }, '详情 →')]),
        e && e.sessions ? h('div.rv-tiles', {}, [
          ['人工介入', `${e.human_turns}次`], ['Agent 活跃', hours(e.active_min_interactive ?? e.active_min)],
          ['等待中位', `${e.wait_median_min}分`], ['峰值并行', e.peak_parallel],
        ].map(([k, v]) => h('div.stat', {}, [h('span.v', {}, String(v)), h('span.k', {}, k)])))
          : h('div', {}, [h('h3', {}, e ? '这一天没有 Agent 会话' : '还没扫描 Agent 会话'),
            h('div.muted', { style: { margin: '-2px 0 12px' } }, '统计 Claude Code / Codex 的人工介入、等待与并行。')]),
        e && e.sessions ? h('div.muted', {}, `纠正 ${e.kinds?.correct || 0} · 中断 ${e.kinds?.interrupt || 0} · 工具错误 ${e.tool_errors}/${e.tool_calls}`)
          : h('button.dark', { onclick: () => go(null, 'day', 'agent') }, [ui.icon('refresh'), '扫描会话']),
      ]);
    }

    function recordCard(entries) {
      return h('div.rv-entries', {}, entries.map((e) => h('div.rv-entry', {}, [
        h('span.t', { title: e.at ? e.at.replace('T', ' ') : '没记时间（老记录或手动编辑）' }, e.time ? (e.next_day ? `次日 ${e.time}` : e.time) : '—'),
        h('span.f', {}, REC_FIELD[e.field] || e.field), h('span.x', {}, e.text)])));
    }

    function templateCard(history) {
      const aspect = (name, label, placeholder) => {
        const key = `${name}·${label}`;
        const prefix = `${key}：`;
        const past = history.flatMap((n) => [n.title, ...n.content.split('\n')].filter((line) => line.startsWith(prefix))
          .map((line) => ({ date: n.date, text: line.slice(prefix.length) })));
        return h('div.rv-aspect', { 'data-key': key }, [
          h('label', {}, [label, h('input', { value: reviewDraft[key] || '', placeholder,
            oninput: (e) => { reviewDraft[key] = e.target.value; } })]),
          past.length ? h('div.rv-area-past', {}, past.map((n) => h('div', {}, [h('span.t', {}, n.date.slice(5)),
            h('span.x', {}, n.text)])))
            : h('div.muted', { style: { marginTop: '6px', fontSize: '13px' } }, '这一栏还没写过'),
        ]);
      };
      const area = (name) => h('div.rv-area', {}, [h('div.rv-area-name', {}, name),
        h('div.rv-aspects', {}, Object.entries(REVIEW_ASPECTS).map(([label, placeholder]) => aspect(name, label, placeholder)))]);
      const save = async () => {
        try {
          const entries = Object.fromEntries(REVIEW_AREAS.flatMap((name) => Object.keys(REVIEW_ASPECTS)
            .map((label) => `${name}·${label}`).map((key) => [key, reviewDraft[key] || ''])));
          const made = await api.post('/api/notes/review', { date: state.date, entries });
          Object.keys(reviewDraft).forEach((key) => delete reviewDraft[key]);
          delete foldOverride[`${state.date}:template`];
          toast(`已贴一张「复盘」便签${made.issues.length ? `，${made.issues.length} 个问题进了规划事项` : ''}`);
          show();
        } catch (e) { toast(e.message, true); }
      };
      const filled = history.filter((n) => n.date === state.date).length;
      const note = filled ? `这天已填 ${filled} 张便签 · 点开可以再写一张或看过去写的` : '填几栏算几栏，保存成一张「复盘」便签，有问题的进规划事项 · 每栏下面是过去写的，方便对比';
      const drafting = Object.values(reviewDraft).some((v) => v.trim());
      return foldCard('template', '复盘模板', note, !filled || drafting, [h('div.rv-areas', {}, REVIEW_AREAS.map(area)),
        h('div.rv-area-save', {}, h('button.primary', { onclick: save }, [ui.icon('check'), '保存到便签']))]);
    }

    function improveCard(d) {
      const rec = d.record;
      const status = h('div.rv-status');
      const running = d.jobs.find((j) => j.ref.startsWith('improve:') && ['queued', 'running'].includes(j.status));
      if (running) { status.textContent = 'Agent 正在结合复盘、当天会话和学习反馈给建议…'; watch(running.id, 'Agent 改善', status); }
      const run = async () => {
        try { await api.post('/api/review/improve', { date: state.date }); toast('Agent 改善已开始'); show(); } catch (e) { toast(e.message, true); }
      };
      const btn = h('button' + (rec.improve_md ? '.ghost.sm' : '.dark'), { disabled: !!running, onclick: run },
        [ui.icon('spark'), running ? '分析中' : rec.improve_md ? '重新给建议' : 'Agent 改善']);
      const note = running ? '分析中' : rec.improve_md ? firstLine(rec.improve_md) : '';
      return foldCard('improve', 'Agent 改善 · 结合复盘、当天会话与学习反馈', note, !rec.improve_md || !!running, [
        rec.improve_md ? annotate(ctx, h('div.md', {}, md(rec.improve_md)), { doc: `review:${state.date}:improve`, title: `${state.date} · Agent 改善`, link: `#review/${state.date}`, source: rec.improve_md })
          : h('div', {}, [h('div.muted', { style: { margin: '2px 0 12px' } }, '点击后才把这天的复盘便签和未解决的问题发给 Agent，对照会话和学习记录找根因、给建议。'),
          running ? null : btn]),
        rec.improve_md ? h('div.rv-fold-actions', {}, btn) : null,
        status,
      ], '.rv-improve');
    }

    function noteCard(n, after) {
      return h('div.card.rv-note', {}, [
        h('div.head', {}, [h('span.tag.' + (NOTE_CLS[n.kind] || ''), {}, NOTE_KIND[n.kind] || n.kind),
          n.date !== state.date ? h('a.muted', { href: `#review/${n.date}/day` }, dayLabel(n.date)) : null,
          h('button.sm.ghost', { title: '这条是你自己写的：移到便签', style: { marginLeft: 'auto' }, onclick: async () => { await api.patch(`/api/review/notes/${n.id}`, { author: 'me' }); toast('已移到便签'); after(); } }, '这是我写的'),
          h('button.icon.del', { title: '删除', onclick: async () => { if (confirm('删除这条记录？')) { await api.del(`/api/review/notes/${n.id}`); after(); } } }, ui.icon('trash'))]),
        n.title ? h('div.ttl', {}, n.title) : null,
        n.content ? h('div.ct.clamp3', { title: n.content }, n.content) : null,
        n.tags ? h('div.tags', {}, n.tags.split(',').filter(Boolean).map((t) => h('span.tag.line', {}, '#' + t.trim()))) : null,
      ]);
    }

    const readRow = (x) => h('div.item', { style: { fontSize: '13.5px' } }, [
      h('span.tag.gray', {}, x.source || x.kind), ' ',
      h('a', x.url.startsWith('#') ? { href: x.url } : { href: x.url, target: '_blank', rel: 'noopener' }, x.title || x.url),
      h('span.muted', {}, ` · ${x.at.slice(11, 16)}${x.times > 1 ? ` · 打开 ${x.times} 次` : ''}`)]);

    async function renderDay() {
      const d = await loadDay();
      const rec = d.record;
      const lx = d.learning_extra;
      const reviewHistory = await api.get(`/api/review/notes?author=me&kind=review&end=${state.date}`);
      const hasLearning = d.learning.length || lx.steps.length || lx.items.length || lx.events?.length || lx.habits?.length;
      const learningNote = [d.stats.learning.total ? `事项 ${d.stats.learning.done}/${d.stats.learning.total}` : '', lx.steps.length ? `步骤 ${lx.steps.length}` : '',
        lx.items.length ? `深读 ${lx.items.length}` : '', lx.events?.length ? `记录 ${lx.events.length}` : ''].filter(Boolean).join(' · ');
      const records = [
        hasLearning ? foldCard('learning', '学习', learningNote, false, [
          lx.habits?.length ? h('div', { style: { marginBottom: '8px' } }, [h('span.card-label', {}, '学习习惯（停一下 / 学完当天用到项目 / 每日论文）'),
            ...lx.habits.map((x) => h('div.item', { style: { fontSize: '13px' } }, x))]) : null,
          d.learning.length ? taskList(d.learning) : null,
          lx.steps.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '深度学习步骤'),
            ...lx.steps.map((s) => h('div.item', {}, [h('span.tag' + (s.status === 'done' ? '.ok' : '.gray'), {}, s.status), s.plan_topic ? h('span.muted', {}, s.plan_topic + ' · ') : null, s.title,
              s.understanding ? h('span.muted', {}, ` 理解 ${s.understanding}/5`) : null]))]) : null,
          lx.items.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '深读（论文 / 项目 / 文章）'),
            ...lx.items.map((i) => h('div.item', {}, [h('span.tag' + (i.status === 'done' ? '.ok' : '.gray'), {}, i.kind),
              h('a', { href: `#learn/item/${i.id}` }, i.title || i.url),
              i.asks ? h('span.muted', {}, ` · 追问 ${i.asks}`) : null,
              ...(i.thoughts || []).map((t) => h('div.muted', { style: { fontSize: '13px', marginLeft: '8px' } }, '感想：' + t))]))]) : null,
          lx.events?.length ? h('div', { style: { marginTop: '8px' } }, [h('span.card-label', {}, '学习记录（测试 / 停一下 / 理解度）'),
            ...lx.events.map((x) => h('div.item', { style: { fontSize: '13px' } }, x))]) : null,
        ]) : null,
        d.reads.length ? foldCard('reads', '已读', `${d.reads.length} 篇 · 信息推荐 / 产品雷达里打开过的`, false, [h('div.list', {}, d.reads.map(readRow))]) : null,
        d.notes.length ? foldCard('notes', '问题与经验', `${d.notes.length} 条`, false, [h('div.rv-notes', {}, d.notes.map((n) => noteCard(n, show)))]) : null,
      ].filter(Boolean);
      const nodes = [
        ui.section(isToday(state.date) ? '今天的进展' : '这一天的进展', dayLabel(state.date)),
        h('div.rv-cards', {}, [tasksCard(d), suggCard(d), effCard(d)]),
        rec.ai_analysis ? foldCard('analysis', 'AI 检查完整分析', firstLine(rec.ai_analysis), false, [annotate(ctx, md(rec.ai_analysis), { doc: `review:${state.date}:check`, title: `${state.date} · AI 检查分析`, link: `#review/${state.date}`, source: rec.ai_analysis })]) : null,
        ui.section('我的复盘', '先写，再让 Agent 找根因'),
        templateCard(reviewHistory),
        improveCard(d),
        rec.entries?.length ? foldCard('entries', '这一天之前写下的记录', `${rec.entries.length} 条`, false, [recordCard(rec.entries)]) : null,
        ...(records.length ? [ui.section('当天记录'), ...records] : []),
      ].filter(Boolean);
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

    // ---------- 已读历史 ----------
    async function renderReads() {
      loadDay();
      const s = new Date(state.date + 'T12:00:00'); s.setDate(s.getDate() - 29);
      const startIn = h('input', { type: 'date', value: s.toLocaleDateString('sv-SE') });
      const endIn = h('input', { type: 'date', value: state.date });
      const list = h('div');
      const load = async () => {
        const days = await api.get(`/api/review/reads?start=${startIn.value}&end=${endIn.value}`);
        list.replaceChildren(...(days.length ? days.flatMap((x) => [
          ui.section(dayLabel(x.date), `${x.items.length} 篇`), h('div.card', {}, h('div.list', {}, x.items.map(readRow)))])
          : [ui.empty('这段时间没有已读记录', '在信息推荐或产品雷达里打开文章后会记到这里')]));
      };
      startIn.onchange = endIn.onchange = load;
      body.replaceChildren(ui.section('已读历史', '信息推荐 / 产品雷达里打开过的，按天排列'), h('div.rv-range', {}, [startIn, '—', endIn]), list);
      await load();
    }

    // ---------- 问题与经验 ----------
    async function renderNotes() {
      loadDay();
      const q = h('input', { placeholder: '搜索标题 / 内容 / 标签' });
      const list = h('div.rv-notes');
      const count = h('span');
      const load = async () => {
        const ns = await api.get(`/api/review/notes?author=system&q=${encodeURIComponent(q.value)}&kind=${state.noteKind}`);
        count.textContent = `${ns.length} 条`;
        list.replaceChildren(...(ns.length ? ns.map((n) => noteCard(n, load)) : [ui.empty('没有记录', 'Agent 和系统复盘记下的会出现在这里；你自己写的在「便签」')]));
      };
      const kindChips = [['', '全部'], ...SYS_KINDS.map((k) => [k, NOTE_KIND[k]])].map(([k, v]) => h('button.chip' + (state.noteKind === k ? '.on' : ''), {
        onclick: (e) => { state.noteKind = k; kindChips.forEach((b) => b.classList.toggle('on', b === e.currentTarget)); load(); } }, v));
      q.addEventListener('input', () => { clearTimeout(q._t); q._t = setTimeout(load, 250); });
      body.replaceChildren(ui.section('问题与经验', count), h('div.rv-filter', {}, [q, ...kindChips]), list);
      await load();
    }

    // ---------- Agent 效率 ----------
    async function renderAgent() {
      loadDay();
      const processBox = h('div', {}, ui.empty('扫描会话日志中…', '读取当天 Claude Code / Codex 会话'));
      const coreBox = h('div');
      const deliveryBox = h('div');
      const utilBox = h('div');
      const patternBox = h('div');
      body.replaceChildren(h('div.rv-agent', {}, [
        approvals(ctx),
        foldCard('board', '实时看板', isToday(state.date) ? '每 10 秒刷新 · 卡片拖到「已验收」' : '正在跑的会话，和所选日期无关', isToday(state.date), [agentBoard(ctx)]),
        ui.section('结果', dayLabel(state.date)),
        coreBox, deliveryBox,
        ui.section('时间利用', 'Agent 是否跑满 · 人工交互是否在专注时间'),
        utilBox, patternBox,
        processBox,
      ]));
      const fill = (box, promise) => promise.then((n) => box.replaceChildren(n));
      await Promise.all([
        fill(coreBox, coreMetrics(ctx, { date: state.date })),
        fill(deliveryBox, deliveries(ctx, { date: state.date })),
        fill(utilBox, utilization(ctx, { date: state.date })),
        fill(patternBox, agentPatterns(ctx).then(({ note, node }) => foldCard('patterns', '近 7 天规律', note, false, [node]))),
        renderProcess(processBox),
      ]);
    }

    async function renderProcess(box, refresh = false) {
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
        ui.section('人工介入', '扫描于 ' + (e.scanned_at || '').slice(11, 16) + ' · 分类为启发式规则（首条=新任务；「继续/好」=确认；含「不对/应该」=纠正）'),
        h('div.row', { style: { justifyContent: 'flex-end', marginBottom: '10px' } }, [h('button.ghost', { onclick: () => renderProcess(box, true) }, [ui.icon('refresh'), '重新扫描']), reflectBtn]),
        ui.stats([
          { k: '交互 + 自动会话', v: `${a.interactive || 0}+${a.automated || 0}` }, { k: '人工介入', v: a.human_turns ?? 0 },
          { k: `Agent 活跃（含自动 ${hours(a.active_min)}）`, v: hours(a.active_min_interactive ?? a.active_min) },
          { k: '等待中位', v: `${a.wait_median_min ?? 0}分` },
          { k: '峰值并行', v: a.peak_parallel ?? 0 }, { k: `工具错误 / 调用 · 权限拒绝 ${a.denials ?? 0}`, v: `${a.tool_errors ?? 0}/${a.tool_calls ?? 0}` },
          { k: '平台任务失败 / 总', v: `${a.platform_jobs_failed || 0}/${a.platform_jobs || 0}` },
        ]),
        h('div', { style: { marginBottom: '14px' } }, Object.entries(a.kinds || {}).map(([k, v]) => h('span.tag.' + (MSG_CLS[k] || ''), {}, `${MSG_KIND[k] || k} ${v}`))),
        status,
        e.reflection ? foldCard('reflection', 'AI 反思', firstLine(e.reflection), false, [annotate(ctx, md(e.reflection), { doc: `review:${state.date}:reflection`, title: `${state.date} · Agent 效率 AI 反思`, link: `#review/${state.date}`, source: e.reflection })])
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
      box.replaceChildren(...nodes);
    }

    // ---------- 人工效率 ----------
    function trendCard(trend) {
      const longest = Math.max(1, ...trend.map((t) => t.minutes || 0));
      return h('div.card', {}, h('div.rv-trend', {}, trend.map((t) => h('div.rv-trend-row' + (t.date === state.date ? '.on' : ''), { title: '看这一天', onclick: () => go(t.date) }, [
        h('span', {}, dayLabel(t.date)),
        h('div.rv-trend-bar', {}, t.minutes ? h('div.rv-trend-fill', { style: { width: `${(t.minutes / longest) * 100}%` } },
          h('div.rv-trend-whole', { style: { width: `${100 - (t.fragment_pct ?? 100)}%` } })) : null),
        h('span.n', {}, t.minutes == null ? '没有数据' : t.minutes ? `${hours(t.minutes)} · 碎片 ${t.fragment_pct}%` : '0h'),
      ]))));
    }

    function timelineCard(x) {
      const clockMin = (t) => +t.slice(0, 2) * 60 + +t.slice(3, 5);
      const describe = (p) => p.blank ? `${p.start}–${p.end} · 没有记录 · ${p.minutes} 分钟 · 可在下面的时间记录里补填`
        : `${p.start}–${p.end} · ${p.type}${p.label === p.type ? '' : ` · ${p.label}`} · ${p.minutes} 分钟${p.whole ? ' · 整块' : ''}`;
      const detail = h('div.rv-tl-detail.muted', {}, '指向或点一段看它在做什么');
      const periods = [...x.segments, ...x.blanks.map((b) => ({ ...b, blank: true }))];
      let picked = null;
      const bar = (p, from, span) => {
        const start = Math.max(clockMin(p.start), from), end = Math.min(clockMin(p.end), from + span);
        const node = h('button.rv-tl-seg' + (p.blank ? '.blank' : ''), { type: 'button', title: describe(p), 'aria-label': describe(p), style: {
          left: `${(start - from) / span * 100}%`, width: `${(end - start) / span * 100}%`, background: p.blank ? null : `var(--t-${p.type})` } });
        const show = () => { detail.textContent = describe(p); detail.classList.remove('muted'); };
        node.onmouseenter = show;
        node.onclick = () => { picked?.classList.remove('on'); picked = node; node.classList.add('on'); show(); };
        return node;
      };
      const SPAN = 360;
      const rows = [0, 6, 12, 18].map((hour) => {
        const from = hour * 60;
        return h('div.rv-tl-row', {}, [h('span.rv-tl-hour', {}, String(hour).padStart(2, '0')), h('div', {}, [
          h('div.rv-tl-track', {}, periods.filter((p) => clockMin(p.start) < from + SPAN && clockMin(p.end) > from).map((p) => bar(p, from, SPAN))),
          h('div.rv-tl-ticks', {}, [0, 2, 4].map((n) => h('span', { style: { left: `${n / 6 * 100}%` } }, `${hour + n}:00`))),
        ])]);
      });
      const blankMin = x.blanks.reduce((sum, b) => sum + b.minutes, 0);
      return h('div.card', {}, [
        detail,
        ...rows,
        h('div.rv-tl-legend', {}, [
          ...x.categories.map((c) => h('span', {}, [h('i.rv-tl-dot', { style: { background: `var(--t-${c})` } }), c, h('b', {}, hours(x.by_type[c]))])),
          h('span', {}, [h('i.rv-tl-dot.blank'), '待填', h('b', {}, hours(blankMin))]),
        ]),
      ]);
    }

    function timeRecordCard(x) {
      const category = h('select', {}, x.categories.map((c) => h('option', { value: c }, c)));
      const start = h('input', { type: 'time' });
      const end = h('input', { type: 'time' });
      const output = h('input.out', { placeholder: '一句产出（可不填）' });
      let editing = null;
      const submit = h('button.primary', { onclick: async () => {
        const data = { date: state.date, category: category.value, start: start.value, end: end.value, output: output.value };
        try {
          if (editing) await api.put(`/api/review/time-entries/${editing}`, data);
          else await api.post('/api/review/time-entries', data);
          await renderHuman();
        } catch (e) { toast(e.message, true); }
      } }, '记下');
      const fill = (e) => {
        category.value = e.category || x.categories[0];
        start.value = e.start; end.value = e.end; output.value = e.output || '';
        editing = e.id || null;
        submit.textContent = editing ? '保存修改' : '记下';
        output.focus();
      };
      const span = (e) => `${e.start}–${e.end <= e.start ? '次日 ' : ''}${e.end}`;
      const rows = [
        ...x.entries.map((e) => ({ at: e.start, node: h('div.rv-time-row', {}, [h('span.t', {}, span(e)), h('span.tag', {}, e.category), h('span.x', {}, e.output),
          h('div.ops', {}, [h('button.ghost.sm', { onclick: () => fill(e) }, '改'),
            h('button.ghost.sm', { onclick: async () => { if (confirm('删除这条记录？')) { await api.del(`/api/review/time-entries/${e.id}`); await renderHuman(); } } }, '删')])]) })),
        ...x.blanks.map((b) => ({ at: b.start, node: h('div.rv-time-row', {}, [h('span.t', {}, span(b)), h('span.tag.line', {}, '待填'), h('span.x.muted', {}, `${b.minutes} 分钟没有记录`),
          h('div.ops', {}, h('button.ghost.sm', { onclick: () => fill(b) }, '填'))]) })),
      ].sort((a, b) => a.at.localeCompare(b.at));
      return h('div.card', {}, [
        h('div.rv-time-form', {}, [category, start, '—', end, output, submit]),
        rows.length ? h('div', {}, rows.map((r) => r.node)) : h('div.muted', {}, '这一天还没有手填记录，也没有 20 分钟以上的空白。'),
      ]);
    }

    function awayCard(initial) {
      const box = h('div');
      const clock = (at) => at.slice(11, 16);
      const elapsed = (s) => {
        const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, '0');
        return hh ? `${hh} 小时 ${mm} 分 ${ss} 秒` : `${mm} 分 ${ss} 秒`;
      };
      const step = async (call) => {
        try {
          const a = await call();
          if (a?.discarded) toast(a.discarded);
          draw(a?.discarded ? null : a);
        } catch (e) {
          toast(e.message, true);
          draw(await api.get('/api/review/away'));
        }
      };
      const cancel = (label) => h('button.ghost.sm.rv-away-cancel', { onclick: () => {
        if (confirm('这段离开不记了？')) step(async () => { await api.del('/api/review/away'); return null; });
      } }, label);
      const drawAway = (a) => {
        const openedAt = Date.now();
        const timer = h('div.rv-away-timer', {}, elapsed(a.seconds));
        const tick = setInterval(() => {
          if (!timer.isConnected) return clearInterval(tick);
          timer.textContent = elapsed(a.seconds + Math.floor((Date.now() - openedAt) / 1000));
        }, 1000);
        box.replaceChildren(h('div.rv-away', {}, [
          h('div.rv-away-head', {}, `离开中 · ${clock(a.started_at)} 开始`),
          timer,
          h('button.rv-away-go.back', { onclick: () => step(() => api.post('/api/review/away/back')) }, '我回来了'),
          cancel('点错了，不记'),
        ]));
      };
      const drawBack = (a) => {
        let category = '';
        const gain = h('input.rv-away-gain', { placeholder: '这段时间的收获（可不填）' });
        const submit = h('button.primary.rv-away-go.send', { disabled: true, onclick: async () => {
          try {
            const r = await api.post('/api/review/away/submit', { category, output: gain.value });
            toast(`记下了 ${r.date} ${clock(a.started_at)}–${clock(a.ended_at)} ${category}`);
            await renderHuman();
          } catch (e) { toast(e.message, true); }
        } }, '提交');
        const kinds = a.categories.map((c) => h('button.kind-chip', { onclick: (e) => {
          category = c;
          kinds.forEach((k) => k.classList.toggle('on', k === e.currentTarget));
          submit.disabled = false;
        } }, c));
        box.replaceChildren(h('div.rv-away', {}, [
          h('div.rv-away-head', {}, '刚才离开了'),
          h('div.rv-away-sum', {}, `${clock(a.started_at)}–${clock(a.ended_at)} · ${elapsed(a.seconds)}`),
          h('div.rv-away-kinds', {}, kinds),
          gain,
          submit,
          cancel('不记了'),
        ]));
      };
      const draw = (a) => {
        if (a?.ended_at) drawBack(a);
        else if (a) drawAway(a);
        else box.replaceChildren(h('div.rv-away', {}, [
          h('button.primary.rv-away-go', { onclick: () => step(() => api.post('/api/review/away/start')) }, '我要离开了'),
          h('div.rv-away-hint', {}, '离开电脑时点一下，回来再点一下'),
        ]));
      };
      draw(initial);
      return box;
    }

    async function renderHuman() {
      loadDay();
      const away = awayCard(await api.get('/api/review/away'));
      if (!body.firstChild) body.replaceChildren(away, ui.empty('统计中…', '读取当天的会话和学习记录'));
      const x = await api.get(`/api/review/human?date=${state.date}`);
      const whole = x.segments.filter((s) => s.whole);
      const pieces = x.segments.filter((s) => !s.whole);
      const segmentRow = (s) => h('div.rv-time-row', {}, [h('span.t', {}, `${s.start}–${s.end}`),
        h('span.tag.seg', {}, [h('i.rv-tl-dot', { style: { background: `var(--t-${s.type})` } }), s.type]), h('span.x', {}, `${s.label === s.type ? '' : `${s.label} · `}${s.minutes} 分`)]);
      body.replaceChildren(away, h('div.rv-human', {}, [
        ui.section('人工效率'),
        ui.stats([
          { k: '人工耗时', v: hours(x.minutes) },
          { k: `碎片时间（碎片率 ${x.fragment_pct ?? '—'}%，建议 ${FRAGMENT_TARGET}% 以下）`, v: hours(x.fragment_min) },
          { k: '整块时间', v: hours(x.whole_min) },
          { k: '学习时间', v: hours(x.by_type['学习']) },
        ]),
        h('div.muted', { style: { marginBottom: '10px' } }, `人工耗时 = 有活动记录的分钟（含 10 分钟内的空隙）+ 手填的${x.work_categories.join(' / ')}，手填的吃饭、运动等不算；碎片时间 = 人工耗时 − 连续 25 分钟以上做同一项目的整块时间。看 Agent 输出超过 10 分钟不发消息会被算成中断，碎片率会偏高；这种时段可以手填成工作。`),
        ui.section('时间轴'),
        h('div.muted', { style: { marginBottom: '10px' } }, '每行 6 小时，颜色是类型；对话算开发，学习和阅读算学习，语音通话算思考复盘；手填优先。'),
        timelineCard(x),
        ui.section('时间段', whole.length ? `整块 ${whole.length} 段 · 共 ${x.whole_min} 分钟` : ''),
        h('div.card', {}, [
          whole.length ? h('div', {}, whole.map(segmentRow)) : h('div.muted', {}, '这一天没有连续 25 分钟以上做同一项目的时段。'),
          pieces.length ? h('details', { style: { marginTop: '10px' } }, [h('summary', {}, `其余 ${pieces.length} 段`), ...pieces.map(segmentRow)]) : null,
        ]),
        ui.section('时间记录', '吃饭、运动、睡觉和没被采到的工作都在这里手填；没填不影响别的，修改留历史'),
        timeRecordCard(x),
        ui.section('近 7 天', '蓝色是整块时间，灰色是碎片时间 · 点一行看那一天'),
        trendCard(x.trend),
      ]));
    }

    async function show() {
      try {
        if (state.tab === 'day') await (state.view === 'agent' ? renderAgent() : state.view === 'human' ? renderHuman() : renderDay());
        else if (state.tab === 'timeline') await renderTimeline();
        else if (state.tab === 'notes') await renderNotes();
        else await renderReads();
      } catch (e) {
        body.replaceChildren(h('pre.error', {}, e.message));
      }
    }
    await show();
  },
};
