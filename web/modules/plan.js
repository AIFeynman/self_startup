// 规划：每日事项录入 → AI 拆解 → 排程（专注窗 / 人车道 / Agent 车道）→ 可选让 Agent 自动执行
// 列表按状态分组（参考 Linear）：C 新建弹窗写标题 + 长描述 + 属性，点行开右侧详情直接编辑，自动保存。
import { today, nowLocal, toMs } from '../api.js';
import { approvals } from './_approvals.js';
import { submitted } from './_submitted.js';

const CSS = `
.pl-date { display: flex; align-items: center; gap: 4px; }
.pl-date input { width: auto; padding: 3px 8px; border-radius: 999px; font-size: 13px; background: transparent; }
.pl-date button { padding: 3px 10px; font-size: 13px; }
.pl-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.pl-bar .sp { flex: 1; }
.pl-bar button { display: inline-flex; align-items: center; gap: 5px; padding: 5px 12px; font-size: 13px; }
.pl-bar button svg { width: 14px; height: 14px; }
.pl-search { width: 200px; padding: 5px 12px; border-radius: 8px; font-size: 13px; }
.pl-k { font: 11px var(--mono); border: 1px solid currentColor; border-radius: 4px; padding: 0 4px; opacity: .6; }
.pl-more { margin: -4px 0 10px; font-size: 12px; color: var(--muted); }
.pl-more summary { cursor: pointer; width: max-content; }
.pl-more > div { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-top: 8px; }
.pl-more input[type=text] { width: 260px; padding: 3px 12px; border-radius: 999px; font-size: 12px; background: transparent; }
.pl-more label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.pl-job { color: var(--muted); font-size: 12px; min-height: 18px; margin-bottom: 6px; }
.pl-job:empty { display: none; }
.pl-warn { margin-top: -4px; margin-bottom: 14px; font-size: 13px; display: flex; flex-direction: column; gap: 4px; }

.pl-issues { padding: 0; overflow: hidden; }
.pl-group { display: flex; align-items: center; gap: 8px; padding: 7px 14px; background: var(--bg-2); font-size: 13px; font-weight: 600; cursor: pointer; user-select: none; }
.pl-issues > .pl-group + .pl-group, .pl-issues > div + .pl-group { border-top: 1px solid var(--line); }
.pl-group svg { width: 15px; height: 15px; }
.pl-group .n { color: var(--muted); font-weight: 400; }
.pl-group .sp { flex: 1; }
.pl-group .fold { color: var(--muted); font-size: 10px; width: 10px; }
.pl-group button { padding: 0 6px; line-height: 20px; border: 0; background: transparent; color: var(--muted); }
.pl-group button:hover { color: var(--accent); }
.pl-irow { display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 14px; border-top: 1px solid var(--line); cursor: pointer; font-size: 14px; }
.pl-group + .pl-irow { border-top: 0; }
.pl-irow:hover { background: var(--bg); }
.pl-irow.sel { background: var(--accent-soft); box-shadow: inset 2px 0 var(--accent); }
.pl-irow.kid { padding-left: 46px; font-size: 13px; min-height: 34px; }
.pl-irow.closed .ttl { color: var(--muted); }
.pl-ico { all: unset; display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; flex: none; cursor: pointer; }
.pl-ico:hover { background: var(--bg-2); }
.pl-ico:focus-visible { outline: 2px solid var(--accent); }
.pl-ico svg, .pl-menu svg, .pl-prop svg { width: 16px; height: 16px; flex: none; }
.pl-id { color: var(--muted); font-size: 12px; width: 42px; flex: none; font-variant-numeric: tabular-nums; }
.pl-irow .ttl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-irow .sub { color: var(--muted); font-size: 12px; flex: none; }
.pl-caret { all: unset; width: 14px; flex: none; text-align: center; color: var(--muted); font-size: 10px; cursor: pointer; }
.pl-lbls { display: flex; gap: 4px; flex: none; align-items: center; }
.pl-lbl { font-size: 12px; line-height: 20px; padding: 0 8px; border: 1px solid var(--line-2); border-radius: 999px; color: var(--muted); white-space: nowrap; }
.pl-lbl.agent { border-color: var(--ok); color: var(--ok); }
.pl-lbl.over { border-color: var(--warn); color: var(--warn); font-weight: 600; }
.pl-lbl.time { border-color: transparent; color: var(--text); font-variant-numeric: tabular-nums; }
.pl-irow .pl-del { visibility: hidden; }
.pl-irow:hover .pl-del, .pl-irow.sel .pl-del { visibility: visible; }
.pl-irow .pl-del:hover { color: var(--warn); }
.pl-irow button.run { padding: 1px 10px; font-size: 12px; background: var(--dark); color: var(--bg); border-color: var(--dark); }
@media (max-width: 760px) { .pl-lbl.opt, .pl-id { display: none; } .pl-search { width: 100%; } }

.pl-menu { position: fixed; z-index: 1000; min-width: 170px; background: var(--panel); border: 1px solid var(--line-2); border-radius: 10px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, .16); padding: 4px; }
.pl-menu button { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 10px; border-radius: 6px; font-size: 13px; cursor: pointer; color: var(--text); }
.pl-menu button:hover, .pl-menu button.cur { background: var(--bg-2); }
.pl-menu .k { margin-left: auto; padding-left: 16px; color: var(--muted); font-size: 11px; }
.pl-prop { all: unset; box-sizing: border-box; display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; min-height: 28px; border: 1px solid var(--line-2);
  border-radius: 8px; font-size: 13px; cursor: pointer; color: var(--text); white-space: nowrap; }
.pl-prop:hover { background: var(--bg-2); }
.pl-prop:focus-visible { outline: 2px solid var(--accent); }
.pl-prop input { all: unset; font-size: 13px; color: var(--text); }
.pl-prop input[type=number] { width: 3em; text-align: right; }
.pl-prop.muted { color: var(--muted); }
.pl-bare { display: block; width: 100%; border: 0; padding: 0; margin: 0; background: transparent; color: var(--text); resize: none; overflow: hidden; outline: 0; box-shadow: none; }
.pl-bare:focus { outline: 0; box-shadow: none; border: 0; }
.pl-bare[hidden] { display: none; }

.pl-new { width: min(720px, calc(100vw - 32px)); margin: 10vh auto auto; padding: 0; background: var(--panel); color: var(--text); border: 1px solid var(--line); border-radius: 14px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, .25); }
.pl-new::backdrop { background: rgba(0, 0, 0, .35); }
.pl-new-h { display: flex; align-items: center; gap: 8px; padding: 14px 18px 4px; font-size: 12px; color: var(--muted); }
.pl-new-h .sp { flex: 1; }
.pl-new-b { display: grid; gap: 8px; padding: 6px 18px 10px; }
.pl-new .t { font: 700 20px/1.4 var(--serif); }
.pl-new .d { font-size: 14px; line-height: 1.65; min-height: 96px; }
.pl-new .d.bulk { font: 13px/1.7 var(--mono); min-height: 140px; }
.pl-props { display: flex; gap: 6px; flex-wrap: wrap; padding: 4px 18px 14px; }
.pl-new-f { display: flex; align-items: center; gap: 14px; padding: 10px 18px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); }
.pl-new-f .sp { flex: 1; }
.pl-new-f label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }

.pl-detail { position: fixed; top: 0; right: 0; bottom: 0; width: min(880px, 100vw); z-index: 900; display: flex; flex-direction: column;
  background: var(--panel); border-left: 1px solid var(--line); box-shadow: -14px 0 36px rgba(0, 0, 0, .14); }
.pl-detail-h { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--line); font-size: 13px; color: var(--muted); }
.pl-detail-h .sp { flex: 1; }
.pl-detail-h button { padding: 3px 10px; font-size: 13px; }
.pl-detail-h a { cursor: pointer; }
.pl-detail-b { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 250px; }
.pl-main { overflow: auto; padding: 26px 30px 48px; }
.pl-main .t { font: 700 24px/1.35 var(--serif); }
.pl-main .d { margin-top: 14px; font-size: 15px; line-height: 1.75; min-height: 180px; }
.pl-main h5 { display: flex; align-items: center; gap: 8px; margin: 26px 0 6px; font: 600 13px var(--font); color: var(--muted); }
.pl-main .pl-irow { border: 0; border-radius: 8px; min-height: 34px; padding: 0 6px; }
.pl-main .pl-irow.kid { padding-left: 6px; }
.pl-addsub { display: block; width: 100%; padding: 6px 8px; border: 1px dashed var(--line-2); border-radius: 8px; background: transparent; font-size: 13px; margin-top: 4px; }
.pl-source { display: inline-block; margin-top: 10px; font-size: 13px; }
.pl-run { margin-top: 6px; font-size: 13px; }
.pl-run pre { margin: 4px 0 0; max-height: 260px; overflow: auto; white-space: pre-wrap; font: 12px/1.6 var(--mono); background: var(--bg-2); border-radius: 8px; padding: 8px 10px; }
.pl-side { display: grid; align-content: start; gap: 14px; padding: 18px 16px; overflow: auto; border-left: 1px solid var(--line); background: var(--bg); }
.pl-side > label, .pl-side > div { display: grid; gap: 5px; font-size: 12px; color: var(--muted); }
.pl-side .pl-prop { justify-self: start; }
.pl-side .val { font-size: 13px; color: var(--text); }
.pl-side textarea { font-size: 13px; resize: vertical; min-height: 64px; }
.pl-side .dates { display: flex; flex-wrap: wrap; gap: 6px; }
.pl-saved { font-size: 12px; color: var(--muted); }
@media (max-width: 760px) { .pl-detail-b { grid-template-columns: 1fr; overflow: auto; } .pl-main { overflow: visible; padding: 18px 16px; }
  .pl-side { border-left: 0; border-top: 1px solid var(--line); overflow: visible; } }
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
const SOURCE_LINES = [
  [/^deepread:item:\d+ #learn\/item\/(\d+)/, ([, id]) => ({ href: `#learn/item/${id}`, label: '打开深读' })],
  [/^learn:plan:(\d+) step:(\d+)/, ([, plan, step]) => ({ href: `#learn/plan/${plan}/step/${step}`, label: '打开学习步骤' })],
  [/^来自 (\d{4}-\d{2}-\d{2}) 的复盘/, ([, date]) => ({ href: `#review/${date}`, label: `打开 ${date} 的复盘` })],
];
const splitNotes = (notes) => {
  const [first, ...rest] = (notes || '').split('\n');
  for (const [re, link] of SOURCE_LINES) {
    const m = re.exec(first);
    if (m) return { sourceLine: first, source: link(m), text: rest.join('\n') };
  }
  return { sourceLine: '', source: null, text: notes || '' };
};
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

const DAY = 864e5;
const ymd = (x) => x.toLocaleDateString('sv-SE');
const addDays = (date, n) => { const x = new Date(date + 'T00:00'); x.setDate(x.getDate() + n); return ymd(x); };
const daysBetween = (a, b) => Math.round((new Date(b + 'T00:00') - new Date(a + 'T00:00')) / DAY);
const isSpan = (t) => t.end_date !== t.date;

// 范围快捷项：都从当前查看的那天算起；end '' = 不设结束
export const RANGES = {
  day: { label: '当天', end: (d) => d },
  week: { label: '到本周日', end: (d) => addDays(d, (7 - new Date(d + 'T00:00').getDay()) % 7) },
  month: { label: '到月底', end: (d) => { const x = new Date(d + 'T00:00'); return ymd(new Date(x.getFullYear(), x.getMonth() + 1, 0)); } },
  open: { label: '不设结束', end: () => '' },
};

// `11-30` / `2026-11-30` → 完整日期；没写年份的按 base 的年份，roll 时早于 base 就算明年（结束日跨年）
function fullDate(s, base, roll = false) {
  const m = s.match(/^(?:(\d{4})-)?(\d{1,2})-(\d{1,2})$/);
  if (!m) return null;
  const d = `${m[1] || base.slice(0, 4)}-${pad2(+m[2])}-${pad2(+m[3])}`;
  return roll && !m[1] && d < base ? `${+d.slice(0, 4) + 1}${d.slice(4)}` : d;
}

const mins = (s) => { const [a, b] = (s || '0:0').split(':').map(Number); return a * 60 + b; };
const pad2 = (n) => String(n).padStart(2, '0');

/**
 * 解析一行：`写周报 P1 60m #学习 @重 @claude >交给老板前定稿`
 * P1..P4 优先级；60m / 1.5h / 90分钟 预计时长；#学习/#生活/#工作 类别；@auto/@重/@中/@轻 人干预度；@claude/@codex/@人 执行者；> 之后是目标。
 * 日期范围：`~11-30` 从 base 到 11-30，`11-10~11-30` 指定起止，单独一个 `~` 不设结束。
 */
export function parseLine(line, base = today()) {
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
    else if ((m = tok.match(/^([\d-]*)[~～]([\d-]*)$/)) && (!m[1] || fullDate(m[1], base)) && (!m[2] || fullDate(m[2], base))) {
      out.date = m[1] ? fullDate(m[1], base) : base;
      out.end_date = m[2] ? fullDate(m[2], out.date, true) : '';
    }
    else rest.push(tok);
  }
  out.title = rest.join(' ').trim();
  if (out.est_minutes !== undefined && out.est_minutes < 5) out.est_minutes = 5;
  return out;
}

let onAgentDone;
let onKey;
let liveTimer; // 「正在执行」面板的轮询
let closeMenu = () => {};
let closeDetail = () => {};
const collapsed = new Set(); // 折叠的父事项 id（跨重绘保留）
const foldedGroups = new Set(['done', 'dropped']);
const watching = new Set(); // 已在轮询的 job id

const svg = (body, color) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 16 16');
  s.style.color = color;
  s.innerHTML = body;
  return s;
};
const RING = '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.6"/>';
export function statusIcon(s) {
  return {
    todo: () => svg(RING, 'var(--muted)'),
    doing: () => svg(`${RING}<path d="M8 4a4 4 0 0 1 0 8z" fill="currentColor"/>`, 'var(--warn)'),
    partial: () => svg(`${RING}<path d="M8 4a4 4 0 1 1-4 4h4z" fill="currentColor"/>`, 'var(--warn)'),
    done: () => svg('<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M5 8.3l2 2 4-4.3" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>', 'var(--ok)'),
    dropped: () => svg('<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>', 'var(--muted)'),
  }[s]?.() || svg(RING, 'var(--muted)');
}
export function prioIcon(p) {
  if (+p === 1) return svg('<rect x="1.5" y="1.5" width="13" height="13" rx="3" fill="currentColor"/><path d="M8 4.5v4.5" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.4" r="1" fill="#fff"/>', 'var(--accent)');
  const on = 5 - +p;
  return svg([[2, 8], [6.5, 5], [11, 2]].map(([x, y], i) => `<rect x="${x}" y="${y}" width="3" height="${13 - y}" rx="1" fill="currentColor" opacity="${i < on ? 1 : 0.25}"/>`).join(''), 'var(--text)');
}
const PRIO_LABEL = { 1: '紧急', 2: '高', 3: '中', 4: '低' };
const statusOpts = () => Object.entries(STATUS).map(([v, label]) => ({ v, label, icon: statusIcon(v) }));
const prioOpts = () => [1, 2, 3, 4].map((v) => ({ v, label: `${PRIO_LABEL[v]} P${v}`, icon: prioIcon(v) }));
const opts = (map) => Object.entries(map).map(([v, label]) => ({ v, label }));

// 下拉菜单：数字键直接选，Esc 关；在弹窗里打开时挂进弹窗，否则会被弹窗的顶层盖住
function menu(anchor, items, cur, onPick) {
  closeMenu();
  const r = anchor.getBoundingClientRect();
  const pick = (v) => { closeMenu(); onPick(v); };
  const box = document.createElement('div');
  box.className = 'pl-menu';
  for (const [i, o] of items.entries()) {
    const b = document.createElement('button');
    if (String(o.v) === String(cur)) b.className = 'cur';
    if (o.icon) b.append(o.icon.cloneNode(true));
    const k = document.createElement('span');
    k.className = 'k';
    k.textContent = i < 9 ? String(i + 1) : '';
    b.append(o.label, k);
    b.onclick = (e) => { e.stopPropagation(); pick(o.v); };
    box.append(b);
  }
  const key = (e) => {
    const n = +e.key;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); } else if (n >= 1 && n <= items.length) { e.preventDefault(); e.stopPropagation(); pick(items[n - 1].v); }
  };
  const away = (e) => { if (!box.contains(e.target)) closeMenu(); };
  document.addEventListener('keydown', key, true);
  setTimeout(() => document.addEventListener('mousedown', away));
  (anchor.closest('dialog') || document.body).append(box);
  box.style.left = `${Math.max(8, Math.min(r.left, innerWidth - box.offsetWidth - 8))}px`;
  box.style.top = `${r.bottom + box.offsetHeight + 8 > innerHeight ? r.top - box.offsetHeight - 4 : r.bottom + 4}px`;
  closeMenu = () => { box.remove(); document.removeEventListener('keydown', key, true); document.removeEventListener('mousedown', away); closeMenu = () => {}; };
}

const grown = (cls, props) => {
  const ta = document.createElement('textarea');
  ta.className = cls;
  Object.assign(ta, props);
  const fit = () => { ta.style.height = 'auto'; ta.style.height = `${ta.scrollHeight}px`; };
  new ResizeObserver(fit).observe(ta);
  ta.addEventListener('input', fit);
  return ta;
};

export default {
  async render(el, ctx) {
    const { api, h, toast, openChat, ui } = ctx;
    if (!document.getElementById('pl-css')) document.head.append(h('style', { id: 'pl-css' }, CSS));
    document.getElementById('plan-css')?.remove();
    const state = { date: today(), runs: [], data: null, sel: null, q: '' };
    closeDetail();

    if (onAgentDone) document.removeEventListener('agent-done', onAgentDone);
    onAgentDone = () => el.isConnected && load();
    document.addEventListener('agent-done', onAgentDone);

    const patch = async (id, body) => { const t = await api.patch(`/api/tasks/${id}`, body); await load(); return t; };
    const setStatus = (t, v) => patch(t.id, { status: v, ...(v === 'done' ? { progress: 100 } : {}) });
    const remove = async (t) => {
      const hasKids = state.data.tasks.some((x) => x.parent_id === t.id);
      if (!confirm(`删除「${t.title}」${hasKids ? '及其子任务' : ''}？`)) return false;
      await api.del(`/api/tasks/${t.id}`);
      if (state.sel === t.id) state.sel = null;
      await load();
      return true;
    };

    // ---------- 静态骨架：页头 / 工具条只建一次，load() 只换动态区 ----------
    const head = h('div');
    const jobEl = h('div.pl-job');
    const listBox = h('div');
    const body = h('div');
    const hint = h('input', { type: 'text', placeholder: 'AI 拆解补充要求（可选）' });
    const fromNow = h('input', { type: 'checkbox' });
    const search = h('input.pl-search', { type: 'search', placeholder: '筛选任务  /' });
    search.oninput = () => { state.q = search.value; paintList(); };
    search.onkeydown = (e) => { if (e.key === 'Escape') { search.value = ''; state.q = ''; paintList(); search.blur(); } };

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

    const decompose = async (taskIds) => {
      try {
        const r = await api.post('/api/plan/decompose', { date: state.date, hint: hint.value, ...(taskIds ? { task_ids: taskIds } : {}) });
        watch(r.job_id, taskIds ? 'AI 重新拆解（出草稿）' : 'AI 拆解（出草稿）');
      } catch (e) { toast(e.message, true); }
    };
    const schedule = async () => {
      const from = fromNow.checked ? nowLocal().slice(11, 16) : '';
      try { await api.post('/api/plan/schedule', { date: state.date, from_time: from }); toast('已排程'); load(); } catch (e) { toast(e.message, true); }
    };
    const carry = async () => {
      const r = await api.post('/api/plan/carry', { date: state.date });
      toast(r.from ? `从 ${r.from} 顺延 ${r.created.length} 项` : '没有可顺延的事项'); load();
    };
    const launch = async (t) => {
      try {
        const r = await api.post(`/api/plan/tasks/${t.id}/launch`, {});
        toast(`已派发给 Agent（job ${r.job_id}）`);
        load();
        watch(r.job_id, `执行「${t.title}」`);
      } catch (e) { toast(e.message, true); }
    };
    const canRun = (t, leaf) => leaf && (t.human_level === 'auto' || ['claude', 'codex'].includes(t.executor)) && t.status !== 'done';
    const discuss = () => openChat({ module: 'plan', ref: `plan:${state.date}`, title: ctx.title || '规划',
      prefill: '帮我看看这一天的安排：优先级是否合理？哪些可以交给 Agent 并行？' });

    el.append(head,
      h('div.pl-bar', {}, [
        h('button.primary', { onclick: () => openNew(), title: '新建任务（C）' }, [ui.icon('plus'), '新建任务', h('span.pl-k', {}, 'C')]),
        search, h('span.sp'),
        h('button.ghost', { onclick: carry, title: '把上一天没做完的事项顺延到这一天' }, [ui.icon('refresh'), '顺延未完成']),
        h('button.ghost', { onclick: () => decompose() }, [ui.icon('spark'), 'AI 拆解']),
        h('button.ghost', { onclick: schedule }, [ui.icon('clock'), '排程']),
        h('button.ghost', { onclick: discuss }, [ui.icon('chat'), '问 Agent']),
      ]),
      h('details.pl-more', {}, [h('summary', {}, 'AI 拆解 / 排程选项 · 快捷键'), h('div', {}, [hint,
        h('label', { title: '中途重排：只排当前时间之后' }, [fromNow, '排程从现在起']),
        h('span', {}, 'C 新建 · J/K 上下 · Enter 打开 · 1-4 优先级 · S 状态 · / 筛选 · Esc 关闭')])]),
      jobEl, listBox, body);

    // ---------- 动态区 ----------
    async function load() {
      const d = await api.get(`/api/plan/day?date=${state.date}`);
      state.runs = d.runs; state.data = d;
      head.replaceChildren(pageHead(d));
      paintList();
      body.replaceChildren(...(d.draft ? [draftCard(d.draft)] : []), approvals(ctx, { fallback: () => parsedNeeds(d), onChange: load }),
        ...liveCard(d), submitted(ctx), ...summary(d),
        ui.section('时间线', d.schedule ? `排程于 ${d.schedule.created_at.slice(11, 16) || d.schedule.created_at}（从 ${d.schedule.summary.from_time} 起）· 改了事项请重新排程` : ''),
        timeline(d));
      for (const j of d.jobs) watch(j.id, 'AI 拆解');
    }

    function pageHead(d) {
      const isToday = state.date === today();
      const date = h('input', { type: 'date', value: state.date });
      const setDate = (v) => { state.date = v; state.sel = null; closeDetail(); load(); };
      const shift = (n) => setDate(addDays(state.date, n));
      date.onchange = () => date.value && setDate(date.value);
      const fw = d.config.focus_windows.map((w) => `${w.start}-${w.end}`).join('、');
      const wd = '日一二三四五六'[new Date(state.date + 'T00:00').getDay()];
      return ui.pageHead(isToday ? '今天做什么' : `${state.date.slice(5).replace('-', '月')}日做什么`,
        `周${wd} · 专注时间 ${fw} · 一天 ${d.config.day_start}-${d.config.day_end} · Agent 并发 ${d.config.max_agent_concurrency}（在「设置」修改）`,
        h('div.pl-date', {}, [h('button.ghost', { onclick: () => shift(-1), title: '前一天' }, '‹'), date,
          h('button.ghost', { onclick: () => shift(1), title: '后一天' }, '›'),
          isToday ? null : h('button.outline', { onclick: () => setDate(today()) }, '回到今天')]));
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
      const elapsed = (a, b) => { const m = Math.max(0, Math.round(((b ? toMs(b) : Date.now()) - toMs(a)) / 60000)); return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m}m`; };
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

    // ---------- 属性控件：新建弹窗和详情面板共用 ----------
    const pickProp = (items, cur, onPick, title) => {
      const b = h('button.pl-prop', { type: 'button', title });
      const paint = (v) => {
        const o = items.find((x) => String(x.v) === String(v)) || items[0];
        b.replaceChildren(...(o.icon ? [o.icon.cloneNode(true)] : []), o.label);
      };
      b.onclick = (e) => { e.stopPropagation(); menu(b, items, cur, (v) => { cur = v; paint(v); onPick(v); }); };
      paint(cur);
      return b;
    };
    const estProp = (cur, onChange) => {
      const i = h('input', { type: 'number', value: cur, min: 5, step: 5 });
      i.onchange = () => i.value && onChange(Math.max(5, +i.value));
      return h('label.pl-prop', { title: '预计分钟' }, [ui.icon('clock'), i, '分钟']);
    };
    const dateProps = (f, onChange) => {
      const s = h('input', { type: 'date', value: f.date });
      const e = h('input', { type: 'date', value: f.end_date || '' });
      s.onchange = () => {
        if (!s.value) return;
        const single = f.end_date === f.date;
        f.date = s.value;
        if (single) e.value = f.end_date = s.value;
        onChange({ date: f.date, ...(single ? { end_date: f.end_date } : {}) });
      };
      e.onchange = () => { f.end_date = e.value; onChange({ end_date: e.value }); };
      const quick = h('button.pl-prop.muted', { type: 'button', title: '快捷设置结束日' }, '范围');
      quick.onclick = (ev) => {
        ev.stopPropagation();
        menu(quick, Object.entries(RANGES).map(([v, r]) => ({ v, label: r.label })), '', (k) => {
          e.value = f.end_date = RANGES[k].end(f.date);
          onChange({ end_date: f.end_date });
        });
      };
      return [h('label.pl-prop', {}, ['开始', s]), h('label.pl-prop', { title: '留空 = 不设结束，做完前每天都在' }, ['结束', e]), quick];
    };

    // ---------- 新建任务：Linear 式弹窗，标题 + 长描述 + 属性；可切换成每行一件的批量模式 ----------
    function openNew(preset = {}) {
      const f = { status: 'todo', priority: 2, kind: 'work', executor: 'human', human_level: 'medium', est_minutes: 30,
        date: state.date, end_date: state.date, ...preset };
      const title = grown('pl-bare t', { rows: 1, placeholder: '任务标题' });
      const desc = grown('pl-bare d', { rows: 4, placeholder: '添加描述…具体要做的事、背景、链接、验收标准，写多少都行' });
      const bulk = grown('pl-bare d bulk', { rows: 6, hidden: true,
        placeholder: '每行一件事，下面的属性是默认值，行内写了就以行内为准：\n写周报 P1 60m #工作 @重 >下班前发出\n读论文 1.5h #学习 ~11-30\n\n行内语法：P1-P4 · 60m / 1.5h · #学习 #生活 · ~11-30 / 11-10~11-30 / ~ · @auto @重 @轻 @claude @codex · >目标' });
      const more = h('input', { type: 'checkbox' });
      const bulkOn = h('input', { type: 'checkbox' });
      bulkOn.onchange = () => {
        title.hidden = desc.hidden = bulkOn.checked;
        bulk.hidden = !bulkOn.checked;
        (bulkOn.checked ? bulk : title).focus();
      };
      const box = h('dialog.pl-new');
      const close = () => { closeMenu(); box.close(); box.remove(); };
      const create = async () => {
        const items = bulkOn.checked
          ? bulk.value.split('\n').map((l) => parseLine(l, f.date)).filter((x) => x.title)
          : [{ title: title.value.trim(), notes: desc.value.trim() }].filter((x) => x.title);
        if (!items.length) return toast('标题不能为空', true);
        try {
          for (const it of items) await api.post('/api/tasks', { ...f, ...it });
        } catch (e) { return toast(e.message, true); }
        toast(items.length > 1 ? `已创建 ${items.length} 个任务` : `已创建「${items[0].title}」`);
        load();
        if (!more.checked) return close();
        title.value = desc.value = bulk.value = '';
        (bulkOn.checked ? bulk : title).focus();
      };
      title.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); desc.focus(); } });
      box.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); create(); } });
      box.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
      box.append(
        h('div.pl-new-h', {}, [h('span', {}, `新建任务 · ${f.date.slice(5)}${f.parent_id ? ` · 子任务 of #${f.parent_id}` : ''}`), h('span.sp'),
          h('button.icon', { type: 'button', title: '关闭（Esc）', onclick: close }, ui.icon('x'))]),
        h('div.pl-new-b', {}, [title, desc, bulk]),
        h('div.pl-props', {}, [
          pickProp(statusOpts(), f.status, (v) => { f.status = v; }, '状态'),
          pickProp(prioOpts(), f.priority, (v) => { f.priority = +v; }, '优先级'),
          f.parent_id ? null : pickProp(opts(KIND), f.kind, (v) => { f.kind = v; }, '类别'),
          pickProp(opts(EXEC), f.executor, (v) => { f.executor = v; }, '执行者'),
          pickProp(opts(LEVEL), f.human_level, (v) => { f.human_level = v; }, '人干预度'),
          estProp(f.est_minutes, (v) => { f.est_minutes = v; }),
          ...(f.parent_id ? [] : dateProps(f, () => {})),
        ]),
        h('div.pl-new-f', {}, [h('label', {}, [bulkOn, '批量（每行一件）']), h('span.sp'), h('label', {}, [more, '创建更多']),
          h('button.primary', { onclick: create }, ['创建任务 ', h('span.pl-k', {}, '⌘↵')])]),
      );
      document.body.append(box);
      box.showModal();
      title.focus();
    }

    // ---------- 详情面板：右侧滑出，标题 / 描述直接改，失焦自动保存；右栏改属性 ----------
    async function openDetail(id) {
      closeDetail();
      let t = state.data.tasks.find((x) => x.id === id) || await api.get(`/api/tasks/${id}`).catch(() => null);
      if (!t) return;
      state.sel = id; markSel();
      const saved = h('span.pl-saved');
      const save = async (b) => {
        try { t = { ...t, ...await patch(t.id, b) }; saved.textContent = '已保存'; setTimeout(() => { saved.textContent = ''; }, 1500); } catch (e) { toast(e.message, true); }
      };
      const { sourceLine, source, text } = splitNotes(t.notes);
      const title = grown('pl-bare t', { rows: 1, value: t.title, placeholder: '任务标题' });
      title.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); title.blur(); } });
      title.onblur = () => { const v = title.value.trim(); if (!v) title.value = t.title; else if (v !== t.title) save({ title: v }); };
      const desc = grown('pl-bare d', { rows: 6, value: text, placeholder: '添加描述…具体要做的事、进展、卡点、下一步' });
      desc.onblur = () => { const v = [sourceLine, desc.value.trim()].filter(Boolean).join('\n'); if (v !== (t.notes || '')) save({ notes: v }); };
      const goalBox = grown('', { rows: 2, value: t.goal || '', placeholder: '怎样算完成' });
      goalBox.onblur = () => { if (goalBox.value.trim() !== (t.goal || '')) save({ goal: goalBox.value.trim() }); };

      const kids = state.data.tasks.filter((x) => x.parent_id === t.id).sort(byPrio);
      const parent = t.parent_id && state.data.tasks.find((x) => x.id === t.parent_id);
      const addSub = h('input.pl-addsub', { type: 'text', placeholder: '+ 添加子任务，回车创建' });
      addSub.onkeydown = async (e) => {
        if (e.key !== 'Enter' || e.isComposing || !addSub.value.trim()) return;
        try {
          await api.post('/api/tasks', { title: addSub.value.trim(), parent_id: t.id, date: state.date, kind: t.kind, priority: t.priority, est_minutes: 30 });
          await load(); openDetail(t.id);
        } catch (err) { toast(err.message, true); }
      };
      const runs = state.runs.filter((r) => r.task_id === t.id);
      const leaf = !kids.length;
      const del = async () => { if (await remove(t)) closeDetail(); };
      const panel = h('aside.pl-detail', { role: 'dialog', 'aria-label': '任务详情' }, [
        h('div.pl-detail-h', {}, [
          parent ? h('a', { onclick: () => openDetail(parent.id) }, `#${parent.id} ${parent.title.slice(0, 16)} ›`) : null,
          h('span', {}, `#${t.id} · ${KIND[t.kind] || t.kind}`), saved, h('span.sp'),
          canRun(t, leaf) ? h('button.primary', { onclick: () => launch(t), title: '让 Agent 自动执行（cwd = 代码库目录）' }, '🚀 执行') : null,
          !t.parent_id && !leaf ? h('button.ghost', { onclick: () => decompose([t.id]) }, [ui.icon('spark'), '重新拆解']) : null,
          h('button.icon', { title: '删除', onclick: del }, ui.icon('trash')),
          h('button.icon', { title: '关闭（Esc）', onclick: () => closeDetail() }, ui.icon('x')),
        ]),
        h('div.pl-detail-b', {}, [
          h('div.pl-main', {}, [title, desc,
            source ? h('a.pl-source', { href: source.href, onclick: () => closeDetail() }, `${source.label} →`) : null,
            t.parent_id ? null : h('h5', {}, [`子任务 ${kids.filter((k) => k.status === 'done').length}/${kids.length}`]),
            ...(t.parent_id ? [] : [...kids.map((k) => row(k, { kid: true, inPanel: true })), addSub]),
            runs.length ? h('h5', {}, 'Agent 执行') : null,
            ...runs.slice(0, 3).map((r) => h('details.pl-run', {}, [h('summary', {}, `${r.status} · ${(r.started_at || r.created_at || '').slice(5, 16)}`), h('pre', {}, r.result || '（无结果）')])),
          ]),
          h('div.pl-side', {}, [
            h('div', {}, ['状态', pickProp(statusOpts(), t.status, (v) => save({ status: v, ...(v === 'done' ? { progress: 100 } : {}) }), '状态')]),
            h('div', {}, ['优先级', pickProp(prioOpts(), t.priority, (v) => save({ priority: +v }), '优先级')]),
            t.parent_id ? null : h('div', {}, ['类别', pickProp(opts(KIND), t.kind, (v) => save({ kind: v }), '类别')]),
            h('div', {}, ['执行者', pickProp(opts(EXEC), t.executor, (v) => save({ executor: v }), '执行者')]),
            h('div', {}, ['人干预度', pickProp(opts(LEVEL), t.human_level, (v) => save({ human_level: v }), '人干预度')]),
            h('div', {}, ['预计时长', estProp(t.est_minutes, (v) => save({ est_minutes: v }))]),
            t.parent_id ? null : h('div', {}, ['日期', h('div.dates', {}, dateProps({ date: t.date, end_date: t.end_date || '' }, (b) => save(b))),
              isSpan(t) ? h('span.val', {}, spanText(t, state.date)) : null]),
            h('div', {}, ['排程', h('span.val', {}, t.start_time ? `${t.start_time} – ${t.end_time}` : '未排')]),
            h('label', {}, ['完成标准', goalBox]),
            t.depends_on?.length ? h('div', {}, ['依赖', h('span.val', {}, t.depends_on.map((x) => `#${x}`).join('、'))]) : null,
            t.parallel_group ? h('div', {}, ['并行组', h('span.val', {}, t.parallel_group)]) : null,
          ]),
        ]),
      ]);
      const esc = (e) => {
        if (e.key !== 'Escape' || document.querySelector('dialog[open], .pl-menu')) return;
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return document.activeElement.blur();
        closeDetail();
      };
      document.addEventListener('keydown', esc);
      window.addEventListener('hashchange', closeDetail);
      document.body.append(panel);
      closeDetail = () => {
        document.activeElement?.blur?.();
        panel.remove(); document.removeEventListener('keydown', esc); window.removeEventListener('hashchange', closeDetail);
        closeDetail = () => {};
      };
    }

    // ---------- 任务列表：按状态分组，一行一个任务 ----------
    const byPrio = (a, b) => a.priority - b.priority || (a.start_time || '99').localeCompare(b.start_time || '99') || a.id - b.id;
    const GROUPS = [['doing', '进行中', ['doing', 'partial']], ['todo', '待办', ['todo']], ['done', '已完成', ['done']], ['dropped', '已放弃', ['dropped']]];
    const overdue = (t) => t.end_date && t.end_date < state.date && !['done', 'dropped'].includes(t.status);
    const spanShort = (t) => {
      if (overdue(t)) return `逾期 ${daysBetween(t.end_date, state.date)} 天`;
      if (!t.end_date) return `第 ${daysBetween(t.date, state.date) + 1} 天`;
      const left = daysBetween(state.date, t.end_date);
      return left ? `${t.end_date.slice(5)} 截止` : '今天截止';
    };

    function row(t, { kid = false, kids = [], inPanel = false } = {}) {
      const st = h('button.pl-ico', { title: `状态：${STATUS[t.status]}（S）` }, statusIcon(t.status));
      st.onclick = (e) => { e.stopPropagation(); menu(st, statusOpts(), t.status, (v) => setStatus(t, v).then(() => inPanel && openDetail(t.parent_id))); };
      const pr = h('button.pl-ico', { title: `优先级：${PRIO_LABEL[t.priority]}（1-4）` }, prioIcon(t.priority));
      pr.onclick = (e) => { e.stopPropagation(); menu(pr, prioOpts(), t.priority, (v) => patch(t.id, { priority: +v })); };
      const lbl = (cls, text, title) => h('span.pl-lbl' + cls, title ? { title } : {}, text);
      const run = state.runs.find((r) => r.task_id === t.id);
      const done = kids.filter((k) => k.status === 'done').length;
      const caret = kids.length ? h('button.pl-caret', { title: '展开 / 收起子任务', onclick: (e) => {
        e.stopPropagation(); collapsed.has(t.id) ? collapsed.delete(t.id) : collapsed.add(t.id); paintList();
      } }, collapsed.has(t.id) ? '▸' : '▾') : null;
      return h(`div.pl-irow${kid ? '.kid' : ''}${['done', 'dropped'].includes(t.status) ? '.closed' : ''}${state.sel === t.id && !inPanel ? '.sel' : ''}`,
        { 'data-id': t.id, onclick: () => openDetail(t.id) }, [
          inPanel ? null : caret, pr, h('span.pl-id', {}, `#${t.id}`), st,
          h('span.ttl', { title: t.title }, t.title),
          kids.length ? h('span.sub', {}, `${done}/${kids.length}`) : null,
          h('span.pl-lbls', {}, [
            isSpan(t) ? lbl(overdue(t) ? '.over' : '', spanShort(t), spanText(t, state.date)) : null,
            run && ['queued', 'running'].includes(run.tip_status) ? lbl('.agent', 'Agent 执行中') : null,
            t.executor !== 'human' ? lbl('.agent.opt', EXEC[t.executor] || t.executor) : null,
            t.human_level === 'auto' ? lbl('.agent.opt', '自动') : null,
            !kid && !inPanel ? lbl('.opt', KIND[t.kind] || t.kind) : null,
            lbl('.opt', `${t.est_minutes}m`),
            t.start_time ? lbl('.time', `${t.start_time}–${t.end_time}`) : null,
            !inPanel && canRun(t, !kids.length) ? h('button.run', { title: '让 Agent 自动执行', onclick: (e) => { e.stopPropagation(); launch(t); } }, '执行') : null,
          ]),
          h('button.pl-ico.pl-del', { title: '删除（Delete）', onclick: (e) => { e.stopPropagation(); remove(t).then((ok) => ok && inPanel && openDetail(t.parent_id)); } }, ui.icon('trash')),
        ]);
    }

    function paintList() {
      const d = state.data;
      if (!d) return;
      const q = state.q.trim().toLowerCase();
      const hit = (t) => !q || `#${t.id} ${t.title} ${t.notes || ''} ${t.goal || ''}`.toLowerCase().includes(q);
      const tops = d.tree.filter((t) => hit(t) || t.children.some(hit));
      const nSpan = d.tree.filter(isSpan).length;
      const kidsN = d.tasks.filter((t) => t.parent_id).length;
      const head = ui.section(state.date === today() ? '今天的任务' : '这一天的任务',
        d.tree.length ? `${d.tree.length} 项${nSpan ? `（跨日 ${nSpan}）` : ''}${kidsN ? ` · ${kidsN} 个子任务` : ''}` : '');
      if (!tops.length) {
        return listBox.replaceChildren(head, h('div.card', {}, q ? ui.empty('没有匹配的任务', `筛选「${state.q}」`)
          : ui.empty(state.date === today() ? '今天还没有任务' : '这一天还没有任务', '按 C 新建，或点「顺延未完成」把上一天没做完的带过来')));
      }
      const parts = [];
      for (const [key, label, sts] of GROUPS) {
        const list = tops.filter((t) => sts.includes(t.status)).sort(byPrio);
        if (!list.length && key !== 'todo') continue;
        const folded = foldedGroups.has(key) && !q;
        parts.push(h('div.pl-group', { onclick: () => { foldedGroups.has(key) ? foldedGroups.delete(key) : foldedGroups.add(key); paintList(); } }, [
          h('span.fold', {}, folded ? '▸' : '▾'), statusIcon(sts[0]), label, h('span.n', {}, String(list.length)), h('span.sp'),
          h('button', { title: `新建${label}任务`, onclick: (e) => { e.stopPropagation(); openNew({ status: sts[0] }); } }, ui.icon('plus')),
        ]));
        if (folded) continue;
        for (const t of list) {
          const kids = [...t.children].sort(byPrio);
          parts.push(row(t, { kids }));
          if (!collapsed.has(t.id)) kids.forEach((k) => parts.push(row(k, { kid: true })));
        }
      }
      listBox.replaceChildren(head, h('div.card.pl-issues', {}, parts));
    }

    const markSel = () => listBox.querySelectorAll('.pl-irow').forEach((r) => r.classList.toggle('sel', +r.dataset.id === state.sel));
    const move = (n) => {
      const ids = [...listBox.querySelectorAll('.pl-irow')].map((r) => +r.dataset.id);
      if (!ids.length) return;
      const i = ids.indexOf(state.sel);
      state.sel = ids[i < 0 ? (n > 0 ? 0 : ids.length - 1) : Math.max(0, Math.min(ids.length - 1, i + n))];
      markSel();
      listBox.querySelector('.pl-irow.sel')?.scrollIntoView({ block: 'nearest' });
      if (document.querySelector('.pl-detail')) openDetail(state.sel);
    };

    if (onKey) document.removeEventListener('keydown', onKey);
    onKey = (e) => {
      if (!el.isConnected) return document.removeEventListener('keydown', onKey);
      if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || document.querySelector('dialog[open], .pl-menu')) return;
      const k = e.key.toLowerCase();
      const cur = state.sel && state.data?.tasks.find((t) => t.id === state.sel);
      if (k === 'c') openNew();
      else if (k === '/') search.focus();
      else if (k === 'j') move(1);
      else if (k === 'k') move(-1);
      else if ((k === 'enter' || k === 'o') && cur) openDetail(cur.id);
      else if ('1234'.includes(k) && k && cur) patch(cur.id, { priority: +k });
      else if ((k === 'delete' || k === 'backspace') && cur) remove(cur).then((ok) => ok && closeDetail());
      else if (k === 's' && cur) {
        const anchor = listBox.querySelector(`.pl-irow[data-id="${cur.id}"] .pl-ico:nth-of-type(2)`) || listBox;
        menu(anchor, statusOpts(), cur.status, (v) => setStatus(cur, v));
      } else return;
      e.preventDefault();
    };
    document.addEventListener('keydown', onKey);

    // 「第 3/24 天 · 剩 21 天」「逾期 2 天」「第 5 天」（不设结束）
    function spanText(t, on) {
      const range = `${t.date.slice(5)} → ${t.end_date ? t.end_date.slice(5) : '不设结束'}`;
      if (!on) return range;
      const n = daysBetween(t.date, on) + 1;
      if (!t.end_date) return `${range} · 第 ${n} 天`;
      const left = daysBetween(on, t.end_date);
      return `${range} · ${left < 0 ? `逾期 ${-left} 天` : `第 ${n}/${daysBetween(t.date, t.end_date) + 1} 天 · ${left ? `剩 ${left} 天` : '今天截止'}`}`;
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
      const nowM = +nowLocal().slice(11, 13) * 60 + +nowLocal().slice(14, 16);
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
