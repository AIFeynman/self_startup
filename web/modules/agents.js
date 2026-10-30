// Agent 看板：本地 Claude Code / Codex 会话 + 平台后台任务，按 运行中 → 等你处理 → 待验收 → 已验收 流转。
// 每 10 秒自动刷新；卡片可拖到「已验收」，或用按钮 验收 / 归档 / 续接 / 关联事项 / 备注。
import { utilization } from './_utilchart.js';
import { deliveries } from './_deliveries.js';
import { approvals } from './_approvals.js';

const ENGINE = { claude: 'Claude', codex: 'Codex', platform: '平台' };
const prefs = load();

export default {
  async render(el, ctx) {
    const { api, h, md, toast, ui, ask } = ctx;
    injectStyle();
    el.classList.add('ag-wide'); // 看板需要更宽的画布
    let data = null, filter = '', timer = null;
    const todays = await api.get('/api/tasks').catch(() => []);
    const tops = todays.filter((t) => !t.parent_id);

    const statsBox = h('div');
    const deliveryBox = h('div');
    deliveries(ctx).then((n) => deliveryBox.replaceChildren(n));
    const boardBox = h('div.ag-board');
    const overviewBox = h('div');
    const meta = h('span.muted');

    const pills = (items, cur, on) => h('div.row', {}, items.map(([v, label]) =>
      h('button.sm' + (String(cur) === String(v) ? '.dark' : ''), { onclick: () => on(v) }, label)));
    const filters = h('div.ag-filters');
    const drawFilters = () => filters.replaceChildren(
      pills([[6, '6 小时'], [24, '24 小时'], [72, '3 天'], [168, '7 天']], prefs.hours, (v) => { prefs.hours = v; save(); refresh(); }),
      h('span.ag-sep'),
      pills([['all', '全部'], ['claude', 'Claude'], ['codex', 'Codex'], ['platform', '平台']], prefs.engine, (v) => { prefs.engine = v; save(); draw(); }),
      h('span.ag-sep'),
      h('label.row.muted', {}, [h('input', { type: 'checkbox', checked: prefs.automated, onchange: (e) => { prefs.automated = e.target.checked; save(); refresh(); } }),
        `显示脚本会话${data ? `（${data.hidden_automated}）` : ''}`]),
      h('span.grow'), meta,
    );

    const box = ui.composer({
      placeholder: '输入即筛选卡片；回车把这句话发给 Agent…',
      modes: [{ id: 'filter', label: '筛选', placeholder: '输入即筛选卡片（项目名、标题…）；回车发给 Agent' },
        { id: 'ask', label: '问 Agent', placeholder: '比如：哪些会话在等我？卡住的怎么处理？' }],
      hint: '每 10 秒自动刷新 · 拖动卡片到「已验收」',
      // 回车总是发给 Agent；「筛选」模式下边打字边筛卡片，但像问句的输入不筛（免得看板被筛空）
      onSubmit: (t) => { filter = ''; draw(); return ask(t); },
    });
    const isQuestion = (t) => /[?？吗呢]$|哪|怎么|几件|什么|多少|为什么|总结|帮我/.test(t);
    box.querySelector('textarea').addEventListener('input', (e) => {
      const t = e.target.value.trim();
      filter = box.mode === 'filter' && !isQuestion(t) ? t : ''; draw();
    });

    const tab = ctx.sub[0] === 'util' ? 'util' : 'board';
    const tabs = h('div.tabs', {}, [['board', '看板'], ['util', '时间利用']].map(([id, label]) =>
      h('button' + (tab === id ? '.active' : ''), { onclick: () => { location.hash = id === 'board' ? '#agents' : '#agents/util'; } }, label)));
    if (tab === 'util') return renderUtil();
    el.append(
      ui.pageHead('Agent 看板', '本地 Claude Code / Codex 会话与平台任务的实时进度，便于盯控和验收', [
        h('button.outline', { onclick: () => refresh() }, [ui.icon('refresh'), '刷新']),
      ]),
      tabs,
      box,
      ui.chips([
        { label: '哪些在等我？', icon: 'bulb', onClick: () => ask('看一下 Agent 看板：哪些会话在等我处理？按紧急程度列出，每条一句话说明在等什么、建议怎么做。') },
        { label: '总结各 Agent 进展', icon: 'review', onClick: () => ask('总结一下最近 24 小时各个 Agent 会话的进展：运行中的到哪一步了，待验收的做成了什么。') },
        { label: '卡住的怎么处理', icon: 'bolt', onClick: () => ask('看板里「可能卡住」「等待批准」「已中断」的会话，分别可能是什么原因，怎么处理最快？') },
        { label: '今天交付了什么', icon: 'check', onClick: () => ask('今天已经交付了哪几件事（有推送/部署/PR/发布或文档材料，之后没再改的）？每件一句话说清交付物；再列出交付后仍在改、或只提交没推送的。') },
      ], { left: true }),
      approvals(ctx), deliveryBox, statsBox, overviewBox, filters, boardBox,
    );

    async function renderUtil() {
      const day = h('input', { type: 'date', value: ctx.sub[1] || new Date().toLocaleDateString('sv-SE'), style: { width: 'auto' },
        onchange: (e) => { location.hash = '#agents/util/' + e.target.value; } });
      el.append(
        ui.pageHead('时间利用', '从 Claude Code / Codex 会话的真实事件统计：Agent 有没有跑满、人工交互是否落在专注时间、Agent 等你多久', [day]),
        tabs,
        ui.chips([
          { label: '据此优化明天的规划', icon: 'plan', onClick: () => ctx.openChat({ module: 'plan', title: '规划', send: '结合「时间利用」统计和近 7 天规律，帮我调整明天的拆解与排程：需要人来回交互的放进专注时间，能自动跑的填满空档和专注时间外。' }) },
          { label: '分析今天哪里没利用好', icon: 'bulb', onClick: () => ask('结合时间利用统计，分析今天哪些时间没利用好、哪些人工交互不在高效时间，给出 3 条最有用的改进。') },
        ], { left: true }),
        await utilization(ctx, { date: day.value }),
      );
      const pat = await api.get('/api/agents/patterns?days=7');
      el.append(ui.section('近 7 天规律', pat.days ? `${pat.days} 天有数据${pat.filling ? ' · 正在补算更早的日子' : ''}` : (pat.filling ? '正在后台补算，稍后刷新' : '暂无')),
        pat.days ? patternView(pat) : ui.empty('还没有历史数据', '后台正在补算过去 7 天，稍后刷新本页'));
    }

    function patternView(p) {
      const max = Math.max(1, ...p.hourly.map((x) => x.agents));
      const maxH = Math.max(1, ...p.hourly.map((x) => x.humans));
      return h('div.card.flat', {}, [
        ui.stats([{ k: `平均覆盖 · 工作时间内 ${p.avg.coverage_work_pct}%`, v: p.avg.coverage_pct + '%' }, { k: '平均容量使用', v: p.avg.capacity_pct + '%' },
          { k: 'Agent 等你/天（墙钟）', v: p.avg.wait_wall_min + 'm' },
          { k: '平均空档/天', v: p.avg.idle_min + 'm' }, { k: '人工交互/天 · 专注外', v: `${p.avg.human_total} · ${p.avg.human_out_focus}` }]),
        h('div.ag-hours', {}, p.hourly.map((x) => h('div.ag-hour', { title: `${x.hour}点：平均 ${x.agents} 个 Agent·小时，人工交互 ${x.humans} 次，等你 ${x.waiting}` }, [
          h('i.a', { style: { height: (x.agents / max) * 60 + 'px' } }), h('i.h', { style: { height: (x.humans / maxH) * 24 + 'px' } }),
          h('span', {}, x.hour % 3 === 0 ? x.hour : '')]))),
        h('div.muted', {}, ['每小时：', h('b', { style: { color: 'var(--accent)' } }, '■'), ' 平均 Agent 工作量　', h('b', { style: { color: 'var(--warn)' } }, '■'), ' 人工交互次数',
          p.recurring_idle_hours.length ? `　·　经常空着：${p.recurring_idle_hours.map((x) => x + '点').join('、')}` : '']),
      ]);
    }

    function match(c) {
      if (prefs.engine !== 'all' && c.engine !== prefs.engine) return false;
      if (!filter) return true;
      const q = filter.toLowerCase();
      return [c.project, c.title, c.last_human, c.last_agent, c.note, c.branch].some((x) => (x || '').toLowerCase().includes(q));
    }

    function draw() {
      if (!data) return;
      drawFilters();
      const cols = data.columns.map((col) => ({ ...col, cards: col.cards.filter(match) }));
      const n = (id) => cols.find((c) => c.id === id).cards.length;
      statsBox.replaceChildren(ui.stats([
        { k: '运行中', v: n('running') }, { k: '等你处理', v: n('attention') },
        { k: '待验收', v: n('review') }, { k: '已验收', v: n('done') },
      ]));
      const shown = cols.reduce((a, c) => a + c.cards.length, 0);
      meta.textContent = `${filter ? `筛选「${filter}」${shown ? ` · ${shown} 张` : ' · 无匹配，回车问 Agent'} · ` : ''}更新于 ${data.generated_at.slice(11, 19)}${data.archived ? ` · 已归档 ${data.archived}` : ''}`;
      overviewBox.replaceChildren(overview(cols));
      boardBox.replaceChildren(...cols.map((col) => column(col)));
    }

    // 进展一览：运行中 / 等你处理 / 待验收各一行，看计划进度和产出，不用进会话问「进度怎样」
    function overview(cols) {
      const rows = ['running', 'attention', 'review'].flatMap((id) => cols.find((c) => c.id === id).cards.map((c) => ({ ...c, column: id })));
      if (!rows.length) return h('span');
      const withOut = rows.filter((c) => c.output).length;
      return h('div.ag-ov', {}, [
        h('div.ag-ov-head', {}, [h('b', {}, '进展一览'), h('span.muted', {}, `${rows.length} 个会话 · ${withOut} 个有产出 · ${rows.length - withOut} 个暂无产出`)]),
        ...rows.map((c) => h('div.ag-ov-row', { title: c.last_agent || '' }, [
          h('span.ag-dot.ag-' + c.column),
          h('span.ag-proj', {}, c.project),
          h('span.ag-ov-title', {}, c.title),
          h('span.muted', {}, c.plan.length ? `计划 ${c.plan_done}/${c.plan.length}${c.plan_current ? ' · ' + c.plan_current : ''}` : c.reason),
          output(c, true) || h('span.ag-out.none', {}, '暂无产出'),
          h('span.muted', {}, ago(c.idle_min)),
        ])),
      ]);
    }

    function column(col) {
      const body = h('div.ag-col-body', {}, col.cards.length ? col.cards.map(card) : h('div.ag-empty', {}, col.id === 'attention' ? '没有需要你处理的 🎉' : '—'));
      const c = h('div.ag-col.ag-' + col.id, {}, [h('div.ag-col-head', {}, [h('span.ag-dot'), col.title, h('span.ag-count', {}, col.cards.length)]), body]);
      if (col.id === 'done' || col.id === 'review') {
        c.addEventListener('dragover', (e) => { e.preventDefault(); c.classList.add('drop'); });
        c.addEventListener('dragleave', () => c.classList.remove('drop'));
        c.addEventListener('drop', (e) => { e.preventDefault(); c.classList.remove('drop'); mark(e.dataTransfer.getData('text/plain'), col.id === 'done' ? 'done' : ''); });
      }
      return c;
    }

    function card(c) {
      const isSession = c.engine === 'claude' || c.engine === 'codex';
      const reasonCls = { running: '', attention: '.err', review: '.ok', done: '.gray' }[c.column] || '';
      const pct = c.plan.length ? Math.round((c.plan_done / c.plan.length) * 100) : 0;
      const more = h('div.ag-more', { hidden: true }, [
        c.plan.length ? h('ol.ag-plan', {}, c.plan.map((p) => h('li.' + p.status, {}, p.text))) : null,
        c.last_agent ? h('div.ag-reply', {}, md(c.last_agent)) : null,
        c.cwd ? h('div.muted', {}, [c.cwd, c.branch ? ` · ${c.branch}` : '']) : null,
        isSession ? h('div.muted.ag-mono', {}, c.key) : null,
      ]);
      const note = h('input.ag-note', { value: c.note || '', placeholder: '备注…（Enter 保存）',
        onkeydown: (e) => { if (e.key === 'Enter') { api.post('/api/agents/state', { key: c.key, note: e.target.value }).then(() => toast('备注已保存')); } } });
      const taskSel = tops.length ? h('select.ag-task', { title: '关联规划事项（验收时一并完成）',
        onchange: (e) => api.post('/api/agents/state', { key: c.key, task_id: +e.target.value || 0 }).then(() => toast('已关联')) },
        [h('option', { value: '' }, '关联事项…'), ...tops.map((t) => h('option', { value: t.id, selected: t.id === c.task_id }, t.title.slice(0, 24)))]) : null;

      const el = h('div.ag-card' + (c.column === 'attention' ? '.hot' : ''), { draggable: true }, [
        h('div.ag-top', {}, [h('span.ag-eng.' + c.engine, {}, ENGINE[c.engine] || c.engine), h('span.ag-proj', {}, c.project),
          h('span.grow'), h('span.muted', { title: c.last }, ago(c.idle_min))]),
        h('div.ag-title', { title: c.title }, c.title),
        c.plan.length ? h('div.ag-prog', {}, [ui.progress(pct), h('span.muted', {}, `${c.plan_done}/${c.plan.length}`)]) : null,
        c.plan_current ? h('div.ag-cur', {}, ['▸ ', c.plan_current]) : null,
        output(c),
        c.last_human ? h('div.ag-ask.clamp2', { title: c.last_human }, ['你：', c.last_human]) : null,
        !c.plan_current && c.last_agent ? h('div.ag-last.clamp2', {}, c.last_agent.replace(/[#*`>]/g, '')) : null,
        c.error ? h('div.ag-err.clamp2', {}, c.error) : null,
        h('div.ag-foot', {}, [
          h('span.tag' + reasonCls, {}, c.reason),
          c.humans ? h('span.muted', { title: '人工消息数' }, `👤${c.humans}`) : null,
          c.tools ? h('span.muted', { title: '工具调用数' }, `⚙${c.tools}`) : null,
          h('span.grow'),
          h('button.icon', { title: '展开详情', onclick: () => { more.hidden = !more.hidden; } }, ui.icon('doc')),
          isSession ? h('button.icon', { title: '复制续接命令', onclick: () => copyResume(c) }, ui.icon('link')) : null,
          isSession && c.column !== 'running' ? h('button.icon', { title: '在终端续接', onclick: () => openTerm(c) }, ui.icon('arrow')) : null,
          c.column === 'done'
            ? h('button.icon', { title: '恢复自动判断', onclick: () => mark(c.key, '') }, ui.icon('refresh'))
            : h('button.icon.ag-ok', { title: '验收（标记完成）', onclick: () => mark(c.key, 'done') }, ui.icon('check')),
          h('button.icon', { title: '归档（隐藏）', onclick: () => mark(c.key, 'archived') }, ui.icon('box')),
        ]),
        h('div.ag-extra', {}, [taskSel, note]),
        more,
      ]);
      el.addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', c.key));
      return el;
    }

    async function mark(key, col) {
      await api.post('/api/agents/state', { key, col });
      toast(col === 'done' ? '已验收' : col === 'archived' ? '已归档' : '已恢复');
      refresh();
    }
    async function copyResume(c) {
      const { command } = await api.post('/api/agents/resume-command', { key: c.key, cwd: c.cwd });
      try { await navigator.clipboard.writeText(command); toast('已复制：' + command.slice(0, 60)); } catch { prompt('复制续接命令', command); }
    }
    async function openTerm(c) {
      try { await api.post('/api/agents/open', { key: c.key, cwd: c.cwd }); toast('已在终端打开'); } catch (e) { toast(e.message, true); }
    }

    async function refresh() {
      if (!el.isConnected && data) return stop();
      try {
        data = await api.get(`/api/agents/board?hours=${prefs.hours}&automated=${prefs.automated}`);
        draw();
      } catch (e) { meta.textContent = '刷新失败：' + e.message; }
    }
    function stop() { clearInterval(timer); }
    await refresh();
    timer = setInterval(() => { if (!el.isConnected) return stop(); if (!document.hidden) refresh(); }, 10000);
  },
};

const OUT = { delivered: '已交付', changed_after: '交付后仍在改', committed: '已提交未推送' };
function output(c, compact = false) {
  const o = c.output;
  if (!o) return null;
  const docs = o.docs_total ? ` · 文档 ${o.docs_total}` : '';
  const dirty = o.dirty ? ` · 未提交 ${o.dirty}` : '';
  const text = compact ? `${o.labels.join('/')}${docs}` : `📦 ${OUT[o.status] || o.status} · ${o.labels.join('/')}${docs}${dirty} · ${o.at}`;
  return h('span.ag-out.' + o.status, { title: `${OUT[o.status] || o.status} ${o.day} ${o.at}` }, text);
}

function ago(min) {
  if (min < 1) return '刚刚';
  if (min < 60) return `${Math.round(min)} 分钟前`;
  if (min < 1440) return `${Math.round(min / 60)} 小时前`;
  return `${Math.round(min / 1440)} 天前`;
}
function load() {
  try { return { hours: 24, engine: 'all', automated: false, ...JSON.parse(localStorage.getItem('ag-prefs') || '{}') }; } catch { return { hours: 24, engine: 'all', automated: false }; }
}
function save() { try { localStorage.setItem('ag-prefs', JSON.stringify(prefs)); } catch { /* 无痕模式 */ } }

function injectStyle() {
  if (document.getElementById('ag-style')) return;
  const s = document.createElement('style');
  s.id = 'ag-style';
  s.textContent = `
  .ag-hours { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; align-items: end; height: 110px; margin: 10px 0 6px; }
  .ag-hour { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 2px; height: 100%; }
  .ag-hour i { display: block; width: 70%; border-radius: 2px; } .ag-hour i.a { background: var(--accent); } .ag-hour i.h { background: var(--warn); opacity: .8; }
  .ag-hour span { font-size: 10px; color: var(--muted); height: 12px; }
  .ag-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 4px 0 12px; }
  .ag-sep { width: 1px; height: 18px; background: var(--line-2); }
  .ag-board { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: start; }
  .ag-col { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; min-height: 160px; transition: box-shadow .12s; }
  .ag-col.drop { box-shadow: 0 0 0 3px var(--accent-ring); border-color: var(--accent); }
  .ag-col-head { display: flex; align-items: center; gap: 8px; font: 700 15px var(--serif); padding: 2px 4px 10px; }
  .ag-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
  .ag-running .ag-dot { background: var(--accent); box-shadow: 0 0 0 0 var(--accent-ring); animation: ag-pulse 1.6s infinite; }
  .ag-attention .ag-dot { background: var(--err); } .ag-review .ag-dot { background: var(--ok); }
  @keyframes ag-pulse { 0% { box-shadow: 0 0 0 0 var(--accent-ring); } 70% { box-shadow: 0 0 0 7px transparent; } }
  .ag-count { margin-left: auto; font: 500 12px var(--font); color: var(--muted); background: var(--panel); border-radius: 99px; padding: 0 8px; }
  .ag-col-body { display: flex; flex-direction: column; gap: 8px; }
  .ag-empty { text-align: center; color: var(--muted); font-size: 13px; padding: 18px 0; }
  .ag-card { background: var(--panel); border: 1px solid var(--line); border-radius: 11px; padding: 10px 12px; cursor: grab; box-shadow: 0 1px 2px rgba(60,40,20,.04); }
  .ag-card:hover { border-color: var(--line-2); box-shadow: var(--shadow); }
  .ag-card.hot { border-left: 3px solid var(--err); }
  .ag-running .ag-card { border-left: 3px solid var(--accent); }
  .ag-top { display: flex; align-items: center; gap: 6px; font-size: 12px; }
  .page-wrap.ag-wide { max-width: 1560px; }
  .ag-eng { white-space: nowrap; flex: none; font-size: 11px; padding: 0 7px; border-radius: 99px; background: var(--accent-soft); color: var(--accent); }
  .ag-eng.codex { background: var(--ok-soft); color: var(--ok); } .ag-eng.platform { background: var(--bg-2); color: var(--muted); }
  .ag-proj { font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .ag-top .muted { white-space: nowrap; flex: none; }
  .ag-title { font: 700 14px/1.45 var(--serif); margin: 6px 0 4px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .ag-prog { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; margin: 4px 0; }
  .ag-cur { font-size: 12px; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ag-ask { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .ag-last { font-size: 12px; color: var(--text); margin-top: 4px; opacity: .85; }
  .ag-err { font-size: 12px; color: var(--err); margin-top: 4px; }
  .ag-out { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 99px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
  .ag-out.delivered { background: var(--ok-soft); color: var(--ok); }
  .ag-out.changed_after, .ag-out.committed { background: var(--accent-soft); color: var(--accent); }
  .ag-out.none { background: var(--bg-2); color: var(--muted); }
  .ag-ov { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 12px; }
  .ag-ov-head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 6px; font-size: 13px; }
  .ag-ov-row { display: grid; grid-template-columns: 10px minmax(80px, 140px) minmax(0, 2fr) minmax(0, 1.4fr) auto 70px; gap: 10px; align-items: center; font-size: 12px; padding: 4px 0; border-top: 1px dashed var(--line); }
  .ag-ov-row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .ag-ov-row .ag-out { margin-top: 0; }
  .ag-ov-row .ag-dot.ag-running { background: var(--accent); } .ag-ov-row .ag-dot.ag-attention { background: var(--err); } .ag-ov-row .ag-dot.ag-review { background: var(--ok); }
  @media (max-width: 720px) { .ag-ov-row { grid-template-columns: 10px minmax(0, 1fr) auto; } .ag-ov-row > span:nth-child(3), .ag-ov-row > span:nth-child(4), .ag-ov-row > span:nth-child(6) { display: none; } }
  .ag-foot { display: flex; align-items: center; gap: 4px; margin-top: 8px; font-size: 11px; white-space: nowrap; flex-wrap: wrap; }
  .ag-foot .tag { flex: none; }
  .ag-foot button.icon { padding: 3px; } .ag-foot svg.i { width: 16px; height: 16px; }
  .ag-ok:hover { color: var(--ok); }
  .ag-extra { display: none; gap: 6px; margin-top: 8px; }
  .ag-card:hover .ag-extra, .ag-extra:focus-within { display: flex; }
  .ag-extra select, .ag-extra input { font-size: 12px; padding: 3px 6px; }
  .ag-extra select { max-width: 45%; }
  .ag-more { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); font-size: 12px; }
  .ag-plan { margin: 0 0 8px; padding-left: 18px; } .ag-plan li { margin: 2px 0; color: var(--muted); }
  .ag-plan li.done { text-decoration: line-through; } .ag-plan li.doing { color: var(--accent); font-weight: 600; }
  .ag-reply { max-height: 260px; overflow: auto; background: var(--bg); border-radius: 8px; padding: 6px 10px; margin-bottom: 6px; }
  .ag-mono { font-family: var(--mono); font-size: 11px; word-break: break-all; }
  @media (max-width: 1200px) { .ag-board { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 720px) { .ag-board { grid-template-columns: 1fr; } }
  `;
  document.head.append(s);
}
