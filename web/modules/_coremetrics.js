// Agent 核心指标（Agent 看板 / 复盘共用）：结果分、吞吐、杠杆、可避免交互占比，口径同 session-report 技能。
// 杠杆直接由日志算；其余三项要点「AI 评分」跑一次后台评分任务。
// 用法：import { coreMetrics } from './_coremetrics.js'; el.append(await coreMetrics(ctx, { date }))
import { today } from '../api.js';

const fmt = (key, v) => v == null ? '—' : key === 'avoidable_pct' ? `${v}%` : key === 'leverage' ? `${v} 分` : String(v);

export async function coreMetrics(ctx, { date = '' } = {}) {
  const { api, h, toast } = ctx;
  injectStyle();
  const box = h('div');
  let day = date || today(), polling = false;

  const load = async () => {
    try {
      const d = await api.get(`/api/agents/core?date=${day}`);
      box.replaceChildren(view(d));
      if (d.job && ['queued', 'running'].includes(d.job.status)) poll(d.job.id);
    } catch (e) { box.replaceChildren(h('div.card.flat.cm-card.muted', {}, '读取核心指标失败：' + e.message)); }
  };

  async function poll(id) {
    if (polling) return;
    polling = true;
    const j = await api.waitJob(id, () => {}, 4000).catch(() => ({ status: 'failed' }));
    polling = false;
    toast(j.status === 'done' ? 'AI 评分完成' : 'AI 评分失败', j.status !== 'done');
    if (box.isConnected) load();
  }

  async function score() {
    try { const r = await api.post('/api/agents/core/score', { date: day }); toast('已开始 AI 评分，约 1–3 分钟'); await load(); poll(r.job_id); }
    catch (e) { toast('评分启动失败：' + e.message, true); }
  }

  function tile({ key, label, higher_better: higher, def }, d) {
    const v = d.core[key], p = d.prev?.core?.[key];
    let delta = null;
    if (v != null && p != null && v !== p) {
      const better = higher ? v > p : v < p;
      delta = h('span.cm-delta.' + (better ? 'up' : 'down'), {}, `${v > p ? '↑' : '↓'} 上次 ${fmt(key, p)}`);
    }
    const need = v == null && key !== 'leverage';
    return h('div.cm-tile', { title: def }, [
      h('div.cm-k', {}, label),
      h('div.cm-v' + (need ? '.muted' : ''), {}, need ? '未评分' : fmt(key, v)),
      delta || (p != null ? h('span.cm-delta', {}, `上次 ${fmt(key, p)}`) : null),
      h('div.cm-def', {}, def),
    ]);
  }

  function sessionRow(s) {
    const tasks = s.tasks.map((t) => h('div.cm-task', {}, [
      h('span.cm-score', {}, t.score), h('span.muted', {}, `难度 ${t.difficulty} · ${t.std_h}h`), h('b', {}, t.title),
      t.why ? h('span.muted', {}, '— ' + t.why) : null,
    ]));
    const av = Object.entries(s.avoidable).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join('、');
    return h('details.cm-row', {}, [
      h('summary', {}, h('div.cm-rh', {}, [
        h('span.cm-st', {}, s.status), h('span.cm-at', {}, s.start.slice(11, 16)), h('span.cm-proj', {}, s.project),
        h('span.cm-title', {}, s.title || s.session_id.slice(0, 8)),
        h('span.cm-num', { title: '结果分' }, s.result ?? '—'),
        h('span.cm-num', { title: '吞吐' }, s.throughput ?? '—'),
        h('span.cm-num', { title: '杠杆（分钟/次）' }, s.leverage_min ?? '—'),
        h('span.cm-num', { title: '可避免交互占比' }, s.avoidable_pct == null ? '—' : s.avoidable_pct + '%'),
      ])),
      h('div.cm-more', {}, [
        h('div.muted', {}, `活跃 ${s.active_min} 分 · 人工交互 ${s.human_turns} 次${s.wait_p90_min != null ? ` · 等待 P90 ${s.wait_p90_min} 分` : ''} · 难度 ${s.difficulty ?? '—'} · 产出 ${s.output_h}h`),
        s.note ? h('div', {}, s.note) : null,
        av ? h('div.muted', {}, '可避免：' + av) : null,
        ...tasks,
      ]),
    ]);
  }

  function view(d) {
    const running = d.job && ['queued', 'running'].includes(d.job.status);
    const status = d.error ? `上次评分失败：${d.error}`
      : running ? 'AI 评分进行中…'
      : d.scored_at ? `已评分 ${d.scored}/${d.scorable} 个会话 · ${d.scored_at.slice(5, 16)}${d.new_turns ? ` · 之后新增 ${d.new_turns} 次交互` : ''}${d.unscored?.length ? ` · ${d.unscored.length} 个会话未评` : ''}`
      : `${d.scorable} 个交互会话，尚未评分（杠杆已按日志算出）`;
    const dateIn = h('input', { type: 'date', value: day, style: { width: 'auto' }, onchange: (e) => { day = e.target.value || today(); load(); } });
    const top = h('div.cm-top', {}, [
      h('b.cm-h', {}, '核心指标'), dateIn, h('span.muted.cm-status', {}, status), h('span.grow'),
      h('button.sm' + (d.scored_at && !d.new_turns && !d.unscored?.length ? '.outline' : '.dark'),
        { onclick: score, disabled: running || !d.scorable, title: '后台让 Agent 读当天交互会话，按任务难度、结果、可避免交互打分' },
        running ? '评分中…' : d.scored_at ? '重新评分' : 'AI 评分'),
    ]);
    const tiles = h('div.cm-tiles', {}, d.defs.map((c) => tile(c, d)));
    const extra = [];
    const by = Object.entries(d.avoidable_by_type || {}).filter(([, n]) => n).sort((a, b) => b[1] - a[1]);
    const facts = [
      d.output_h ? `产出 ${d.output_h} 标准工时 / 活跃 ${d.active_h}h` : null,
      d.counts && d.scored ? `✅ ${d.counts['✅']} · 🟡 ${d.counts['🟡']} · ❌ ${d.counts['❌']} · ⏸ ${d.counts['⏸']}` : null,
      d.nudges ? `催促 ${d.nudges} 次` : null,
      d.waits_over_30m ? `等待超 30 分 ${d.waits_over_30m} 次` : null,
      d.wait_p90_min != null ? `等待 P90 ${d.wait_p90_min} 分` : null,
      by.length ? '可避免：' + by.map(([k, n]) => `${k} ${n}`).join('、') : null,
    ].filter(Boolean);
    if (facts.length) extra.push(h('div.muted.cm-facts', {}, facts.join(' · ')));
    const trace = Object.entries(d.trace_min || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
    if (trace.length) extra.push(h('div.muted.cm-facts', {}, 'Agent 时间去向：' + trace.map(([k, m]) => `${k} ${m} 分`).join(' · ')));
    if (d.sessions?.length) {
      extra.push(h('details.cm-sub', {}, [
        h('summary', {}, `逐会话（${d.sessions.length}）· 列：结果分 / 吞吐 / 杠杆 / 可避免`),
        h('div.cm-list', {}, d.sessions.slice().sort((a, b) => a.start.localeCompare(b.start)).map(sessionRow)),
      ]));
    }
    return h('div.card.flat.cm-card', {}, [top, tiles, ...extra]);
  }

  await load();
  return box;
}

function injectStyle() {
  if (document.getElementById('cm-style')) return;
  const s = document.createElement('style');
  s.id = 'cm-style';
  s.textContent = `
  .cm-card { padding: 12px 16px; margin-bottom: 12px; }
  .cm-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
  .cm-h { font: 700 16px var(--serif); }
  .cm-status { font-size: 12px; }
  .cm-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
  .cm-tile { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; min-width: 0; }
  .cm-k { font-size: 12px; color: var(--muted); }
  .cm-v { font: 700 24px var(--font); margin: 2px 0; }
  .cm-v.muted { font-size: 16px; font-weight: 500; }
  .cm-delta { font-size: 11px; color: var(--muted); }
  .cm-delta.up { color: var(--ok); } .cm-delta.down { color: var(--danger, #c0392b); }
  .cm-def { font-size: 11px; color: var(--muted); margin-top: 4px; line-height: 1.4; }
  .cm-facts { font-size: 12px; margin-top: 8px; }
  .cm-sub { margin-top: 8px; font-size: 13px; } .cm-sub > summary { cursor: pointer; color: var(--muted); font-size: 12px; }
  .cm-row { border-top: 1px dashed var(--line); padding: 6px 0; }
  .cm-row > summary { list-style: none; cursor: pointer; } .cm-row > summary::-webkit-details-marker { display: none; }
  .cm-rh { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 13px; }
  .cm-st { flex: none; } .cm-at { font-family: var(--mono); font-size: 12px; color: var(--muted); flex: none; }
  .cm-proj { font-weight: 600; flex: none; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cm-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cm-num { flex: none; width: 44px; text-align: right; font-family: var(--mono); font-size: 12px; }
  .cm-more { padding: 6px 0 2px 24px; font-size: 12px; display: flex; flex-direction: column; gap: 4px; }
  .cm-task { display: flex; gap: 6px; flex-wrap: wrap; align-items: baseline; }
  .cm-score { font: 700 12px var(--mono); color: var(--accent); }
  @media (max-width: 640px) { .cm-num:nth-of-type(n+2) { display: none; } .cm-proj { max-width: 90px; } }
  `;
  document.head.append(s);
}
