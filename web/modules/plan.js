// 规划：每日事项录入 → AI 拆解 → 排程（专注窗 / 人车道 / Agent 车道）→ 可选让 Agent 自动执行
// 输入：一个大 composer，每行一个顶层事项，支持轻量行内语法（见 parseLine）。
import { today } from '../api.js';
import { approvals } from './_approvals.js';

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

.pl-draft { padding: 16px 18px; margin-bottom: 14px; border: 1.5px dashed var(--accent); }
.pl-draft-h { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.pl-draft-h b { font: 700 17px var(--serif); }
.pl-draft-h .muted { font-size: 12px; }
.pl-draft h5 { margin: 12px 0 4px; font: 600 12px var(--font); color: var(--muted); }
.pl-draft ul, .pl-draft ol { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.6; }
.pl-draft .dft { color: var(--muted); font-size: 12px; }
.pl-draft-q li { margin-bottom: 2px; }
.pl-draft-item { margin-top: 12px; }
.pl-draft-item > .t { font: 600 14px var(--serif); }
.pl-draft-item > .note { font-size: 12px; color: var(--muted); margin: 2px 0 4px; }
.pl-draft-sub { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; padding: 6px 4px 6px 8px; border-left: 1.5px solid var(--line-2); }
.pl-draft-sub.auto { background: var(--auto); }
.pl-draft-sub .n { font: 13px var(--serif); color: var(--muted); }
.pl-draft-sub .st { font-size: 13px; font-weight: 600; }
.pl-draft-sub .st .tag { margin-left: 6px; font-weight: 400; }
.pl-draft-sub .g { font-size: 12px; color: var(--muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; cursor: pointer; }
.pl-draft-sub .g.open { display: block; }
.pl-draft-sub button { padding: 0 6px; font-size: 12px; align-self: start; }
.pl-draft-acts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 14px; }
.pl-draft-acts .muted { font-size: 12px; }

.pl-live { padding: 14px 18px; margin-bottom: 14px; }
.pl-live-h { display: flex; align-items: baseline; gap: 10px; }
.pl-live-h b { font: 700 16px var(--serif); }
.pl-live-h .muted { font-size: 12px; }
.pl-live-row { border-top: 1px dashed var(--line); padding: 8px 0; }
.pl-live-row:first-of-type { border-top: 0; }
.pl-live-row > summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 8px; align-items: baseline; }
.pl-live-row > summary::-webkit-details-marker { display: none; }
.pl-live-row .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); animation: pl-pulse 1.4s infinite; }
.pl-live-row.done .dot { animation: none; } .pl-live-row.failed .dot { background: var(--warn); animation: none; }
.pl-live-row.paused .dot { background: var(--muted); animation: none; }
.pl-live-row .acts { display: inline-flex; gap: 4px; margin-left: 6px; }
.pl-live-h .sp { flex: 1; } .pl-live-h button { white-space: nowrap; }
@keyframes pl-pulse { 50% { opacity: .3; } }
.pl-live-row .t { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-live-row .now { grid-column: 2 / 4; font: 12px var(--mono); color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-live-row .meta { font-size: 12px; color: var(--muted); white-space: nowrap; }
.pl-ready { margin: 8px 0 10px; padding: 10px 12px; border-radius: 10px; background: var(--auto); }
.pl-ready-h { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pl-ready-h b { font-size: 14px; color: var(--ok); }
.pl-ready-h .muted { font-size: 12px; }
.pl-ready-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 6px 0; border-top: 1px dashed var(--line); font-size: 13px; }
.pl-ready-row:first-of-type { border-top: 0; }
.pl-ready-row .t { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-ready-row .meta { font-size: 12px; color: var(--muted); white-space: nowrap; }
.pl-blocked { font-size: 12px; margin-top: 6px; }
.pl-live-log { margin: 6px 0 0 20px; font: 11px/1.6 var(--mono); color: var(--muted); max-height: 220px; overflow: auto; white-space: pre-wrap; word-break: break-all;
  background: var(--bg-2); border-radius: 8px; padding: 6px 10px; }

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

// 与 app/jobs.py needs_you 同口径：`NEEDS_YOU:` 行、「需要你做」小节下的条目、「- 需要你做：…」
const NEED_HEAD = /需要你|待你|要你(?:决定|确认|拍板)|人工(?:确认|决策|审批)|NEEDS_YOU/;
export function needsYou(text) {
  const tagged = [...(text || '').matchAll(/NEEDS_YOU[:：]\s*(.+)/g)].map((m) => m[1].trim());
  if (tagged.length) return [...new Set(tagged)].slice(0, 8);
  const out = []; let inSec = false;
  for (const raw of (text || '').split('\n')) {
    const ln = raw.trim();
    if (!ln) continue;
    const b = ln.match(/^(?:[-*•]|\d+[.、)])\s+/);
    const body = (b ? ln.slice(b[0].length) : ln).replaceAll('**', '').replace(/^#+\s*/, '').trim();
    let m;
    if ((m = body.match(/^NEEDS_YOU[:：]\s*(.+)/))) out.push(m[1].trim());
    else if (!b && NEED_HEAD.test(body) && !/需要你(?:知道|了解|注意)|供你参考/.test(body)) {
      const rest = body.split(/[:：]/).slice(1).join('：').trim();
      if (rest) out.push(rest);
      inSec = true; continue;
    } else if (b && inSec) { out.push(body); continue; }
    else if (b && /^(?:需要你|待你)[^:：]{0,8}[:：]/.test(body)) out.push(body.split(/[:：]/).slice(1).join('：').trim());
    inSec = false;
  }
  return [...new Set(out.filter(Boolean))].slice(0, 8);
}

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
let liveTimer; // 「正在执行」面板的轮询
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
        watch(r.job_id, taskIds ? 'AI 重新拆解（出草稿）' : 'AI 拆解（出草稿）');
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
      body.replaceChildren(...(d.draft ? [draftCard(d.draft)] : []), approvals(ctx, { fallback: () => parsedNeeds(d), onChange: load }),
        ...liveCard(d), ...summary(d), ui.section('事项', d.tree.length ? `${d.tree.length} 项 · ${d.tasks.length - d.tree.length} 个子任务` : ''),
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

    // 审批接口还没上线（平台还没重启）时，从今天结束的执行结果里解析出来只读展示
    async function parsedNeeds(d) {
      const done = d.runs.filter((r) => r.status !== 'running');
      const out = [];
      for (const r of done) {
        const j = await api.get(`/api/jobs/${r.job_id}`).catch(() => null);
        needsYou(j?.output).forEach((x) => out.push([r.title, x]));
      }
      return out;
    }

    // ---------- 正在执行：派给 Agent 的子任务，每 10 秒读一次 job 日志看到哪一步 ----------
    function liveCard(d) {
      clearInterval(liveTimer);
      const today0 = state.date === today();
      // 每个任务只看最近一次执行（审批续接、暂停后继续都算同一次，看最新一轮）；今天的显示进行中 + 暂停的 + 今天结束的
      const live = (r) => ['queued', 'running'].includes(r.tip_status);
      const paused = (r) => r.tip_status === 'paused';
      const seen = new Set();
      const latest = d.runs.filter((r) => !seen.has(r.task_id) && seen.add(r.task_id));
      const list = latest.filter((r) => live(r) || paused(r) || (today0 && (r.finished_at || '').startsWith(state.date)));
      // 可以开跑：自动任务、依赖都完成了、还没在跑
      const st = Object.fromEntries(d.tasks.map((t) => [t.id, t.status]));
      const parents = new Set(d.tasks.map((t) => t.parent_id).filter(Boolean));
      const busy = new Set(latest.filter((r) => live(r) || paused(r)).map((r) => r.task_id)); // 暂停的用「继续」，不重新开跑
      const auto = d.tasks.filter((t) => !parents.has(t.id) && t.human_level === 'auto' && ['todo', 'partial'].includes(t.status) && !busy.has(t.id));
      const ready = auto.filter((t) => (t.depends_on || []).every((x) => st[x] === 'done'));
      const blocked = auto.filter((t) => !ready.includes(t));
      if (!list.length && !ready.length) return [];
      const rows = list.map((r) => {
        const now = h('div.now', {}, '读取中…');
        const meta = h('span.meta');
        const acts = h('span.acts');
        const log = h('div.pl-live-log');
        const row = h(`details.pl-live-row.${live(r) ? 'running' : r.tip_status || r.status}`, {}, [
          h('summary', {}, [h('span.dot'), h('span.t', { title: r.title }, r.title), h('span', {}, [meta, acts]), now]), log]);
        return { r, row, now, meta, acts, log };
      });
      const elapsed = (a, b) => { const m = Math.max(0, Math.round(((b ? new Date(b) : new Date()) - new Date(a)) / 60000)); return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m}m`; };
      const tick = async () => {
        if (!box.isConnected) return clearInterval(liveTimer);
        let finished = false;
        const m = await api.get('/api/jobs/machine').catch(() => null);
        busyTag.replaceChildren(m?.queued ? (m.ok ? `排队 ${m.queued} 个（车道 ${m.running}/${m.cap}）` : `机器忙，排队中 ${m.queued} 个：${m.reason}`) : '');
        busyTag.hidden = !m?.queued;
        busyTag.classList.toggle('warn', !!m && !m.ok);
        await Promise.all(rows.map(async (x) => {
          try {
            const j = await api.get(`/api/jobs/${x.r.tip_job_id || x.r.job_id}`);
            const steps = (j.log || '').split('\n').filter((l) => l.startsWith('[tool]'));
            const last = (steps.at(-1) || '').replace('[tool] ', '');
            const queued = m && !m.ok ? `机器忙，排队中（${m.reason}）` : `排队中（车道 ${m?.running ?? '?'}/${m?.cap ?? '?'} 已满）`;
            const status = { queued: m && !m.ok ? '机器忙' : '排队中', running: '执行中', done: '完成', failed: '失败', paused: '已暂停' }[j.status] || j.status;
            const rnd = x.r.round > 1 ? ` · 第 ${x.r.round} 轮` : '';
            x.meta.textContent = `${status}${rnd} · ${elapsed(j.started_at || j.created_at, j.finished_at)} · ${steps.length} 步`;
            x.row.className = `pl-live-row ${j.status === 'queued' ? 'running' : j.status}`;
            x.acts.replaceChildren(
              ['queued', 'running'].includes(j.status) ? h('button.sm.outline', { onclick: (e) => act(e, `/api/jobs/${j.id}/pause`, '已暂停，会话已保存') }, '暂停') : '',
              j.status === 'paused' ? h('button.sm.primary', { onclick: (e) => act(e, `/api/jobs/${j.id}/resume`, '已续接原会话继续执行') }, '继续') : '');
            x.now.textContent = j.status === 'queued' ? queued : j.status === 'running' ? (last ? '正在：' + last : '启动中…')
              : (j.output || '').trim().split('\n').filter(Boolean).slice(-1)[0] || status;
            x.log.textContent = j.status === 'done' ? j.output : (j.log || '').split('\n').slice(-40).join('\n');
            if (live(x.r) && j.status !== 'running' && j.status !== 'queued') finished = true;
          } catch (e) { x.now.textContent = '读取失败：' + e.message; }
        }));
        if (finished) load();
      };
      const act = async (e, url, msg) => {
        e.preventDefault(); e.stopPropagation(); // 按钮在 summary 里，别顺手展开日志
        try { await api.post(url, {}); toast(msg); load(); } catch (err) { toast(err.message, true); }
      };
      const busyTag = h('span.tag', { hidden: true });
      const running = list.filter(live).length;
      const nPaused = list.filter(paused).length;
      const autoOn = d.config.plan_auto_dispatch !== false;
      const pauseAll = async () => {
        if (!confirm(`暂停全部 ${running} 个执行中的 Agent，并关掉到点自动派发？会话都会保存，之后可逐个「继续」。`)) return;
        try { const r = await api.post('/api/jobs/pause_all', {}); toast(`已暂停 ${r.paused.length} 个，自动派发已关`); load(); } catch (e) { toast(e.message, true); }
      };
      const setAuto = async (on) => {
        try { await api.put('/api/settings', { plan_auto_dispatch: on }); toast(on ? '到点自动派发已打开' : '到点自动派发已关闭'); load(); } catch (e) { toast(e.message, true); }
      };
      const cap = +d.config.max_agent_concurrency || 3;
      const launch = async (ts) => {
        for (const t of ts) {
          try { await api.post(`/api/plan/tasks/${t.id}/launch`, {}); } catch (e) { toast(`「${t.title}」派发失败：${e.message}`, true); }
        }
        toast(`已派发 ${ts.length} 个任务给 Agent`); load();
      };
      const free = Math.max(0, cap - running);
      const readyBox = ready.length ? h('div.pl-ready', {}, [
        h('div.pl-ready-h', {}, [h('b', {}, `可以开跑（${ready.length}）`),
          h('span.muted', {}, `依赖都已完成 · 空闲车道 ${free}/${cap}`),
          free ? h('button.sm.primary', { onclick: () => launch(ready.slice(0, free)) }, ready.length > free ? `开跑前 ${free} 个` : '全部开跑') : null]),
        ...ready.map((t) => h('div.pl-ready-row', {}, [
          h('span.t', { title: t.goal || '' }, t.title),
          h('span.meta', {}, `${EXEC[t.executor] || t.executor} · ${t.est_minutes}m${t.start_time ? ' · 原定 ' + t.start_time : ''}`),
          h('button.sm.outline', { onclick: () => launch([t]) }, '开跑'),
        ])),
        blocked.length ? h('div.muted.pl-blocked', {}, `还在等依赖：${blocked.map((t) => t.title.slice(0, 18)).join('、')}`) : null,
      ]) : null;
      const box = h('div.card.pl-live', {}, [
        h('div.pl-live-h', {}, [h('b', {}, '正在执行'),
          h('span.muted', {}, `${list.filter((r) => r.tip_status === 'running').length} 个 Agent 在跑${nPaused ? ` · 已暂停 ${nPaused} 个` : ''}${list.length > running + nPaused ? ` · 今天已结束 ${list.length - running - nPaused} 个` : ''} · 每 10 秒刷新 · 点开看日志`),
          busyTag, h('span.sp'),
          h('button.sm.ghost', { onclick: () => setAuto(!autoOn), title: '到排程时间且依赖完成的自动任务，是否自动派给 Agent' }, autoOn ? '自动派发：开' : '自动派发：已关'),
          running ? h('button.sm.outline', { onclick: pauseAll }, '全部暂停') : null]),
        readyBox, ...rows.map((x) => x.row)]);
      setTimeout(tick); // 等面板挂到页面上再读，否则 tick 以为面板已移除
      if (running) liveTimer = setInterval(tick, 10000);
      return [box];
    }

    // ---------- 拆解草稿：先讨论，确认后才写成子任务 ----------
    function draftCard(dr) {
      const data = dr.data;
      const subs = data.items.flatMap((it) => it.subtasks);
      const human = subs.filter((s) => s.human_level !== 'auto').reduce((a, s) => a + (+s.est_minutes || 0), 0);
      const agent = subs.filter((s) => s.human_level === 'auto').reduce((a, s) => a + (+s.est_minutes || 0), 0);
      const save = async (next) => {
        try { await api.put(`/api/plan/drafts/${dr.id}`, { data: next }); load(); } catch (e) { toast(e.message, true); }
      };
      const drop = (ii, si) => {
        const next = structuredClone(data);
        const list = next.items[ii].subtasks;
        list.splice(si, 1);
        // 依赖是下标：删掉一项后修正后面的下标
        for (const s of list) s.depends_on = (s.depends_on || []).filter((x) => x !== si).map((x) => (x > si ? x - 1 : x));
        save(next);
      };
      const discuss = () => openChat({ module: 'plan', ref: `plan:${state.date}`, title: '讨论拆解草稿',
        send: '我们来讨论这份拆解草稿：先逐条回答你列的待确认问题（说明默认选择和理由），再指出哪里还能更精简或者有遗漏。' });
      const apply = async () => {
        try {
          const r = await api.post(`/api/plan/drafts/${dr.id}/apply`, {});
          toast(`已采用：写入 ${r.created.length} 个子任务并重新排程`); load();
        } catch (e) { toast(e.message, true); }
      };
      const discard = async () => {
        if (!confirm('丢弃这份草稿？已有的子任务不受影响。')) return;
        await api.post(`/api/plan/drafts/${dr.id}/discard`, {}); load();
      };
      return h('div.card.pl-draft', {}, [
        h('div.pl-draft-h', {}, [h('b', {}, '拆解草稿'), h('span.tag.warn', {}, '未生效'),
          h('span.muted', {}, `${subs.length} 个子任务 · 人 ${human} 分 · Agent ${agent} 分 · ${(dr.updated_at || dr.created_at).slice(11, 16)} 更新`)]),
        data.basis.length ? h('h5', {}, '依据的已有进展') : null,
        data.basis.length ? h('ul', {}, data.basis.map((b) => h('li', {}, b))) : null,
        data.questions.length ? h('h5', {}, '需要你拍板') : null,
        data.questions.length ? h('ol.pl-draft-q', {}, data.questions.map((q) => h('li', {}, [q.q, q.default ? h('div.dft', {}, '默认：' + q.default) : null]))) : null,
        ...data.items.map((it, ii) => h('div.pl-draft-item', {}, [
          h('div.t', {}, it.title),
          it.note ? h('div.note', {}, it.note) : null,
          ...it.subtasks.map((s, si) => {
            const g = h('div.g', { onclick: () => g.classList.toggle('open') }, s.goal || '');
            return h('div.pl-draft-sub' + (s.human_level === 'auto' ? '.auto' : ''), {}, [
              h('span.n', {}, String(si + 1)),
              h('div', {}, [h('div.st', {}, [s.title,
                h('span.tag' + (s.human_level === 'auto' ? '.ok' : s.human_level === 'heavy' ? '' : '.line'), {}, LEVEL[s.human_level] || s.human_level),
                h('span.tag.line', {}, `${EXEC[s.executor] || s.executor || '人'} · ${s.est_minutes || 30}m`)]), g]),
              h('button.ghost', { title: '从草稿里去掉这一步', onclick: () => drop(ii, si) }, '×'),
            ]);
          }),
        ])),
        h('div.pl-draft-acts', {}, [
          h('button.primary', { onclick: discuss }, [ui.icon('chat'), '在对话里讨论']),
          h('button.outline', { onclick: apply }, '采用此方案'),
          h('button.ghost', { onclick: discard }, '丢弃'),
          h('span.muted', {}, '采用后替换这些事项下还没开始的子任务，并重新排程'),
        ]),
      ]);
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
