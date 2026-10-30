// 时间利用图（Agent 看板 / 复盘共用）：一天的时间轴上画
//   ① 专注时间窗（暖色底）② 每 10 分钟有几个 Agent 在真正干活（交互 / 脚本，堆叠柱，虚线 = 并发上限）
//   ③ Agent 在等你（灰柱）④ 人工交互（点：专注内绿色、专注外橙色）⑤ 空档（斜纹）
// 用法：import { utilization } from './_utilchart.js'; el.append(await utilization(ctx, { date }))
export async function utilization(ctx, { date = '', compact = false } = {}) {
  const { api, h, ui } = ctx;
  injectStyle();
  const box = h('div.uc');
  const load = async (refresh = false) => {
    box.replaceChildren(h('div.muted', {}, h('span.dots', {}, '统计真实会话事件中')));
    try {
      const d = await api.get(`/api/agents/utilization?date=${date}${refresh ? '&refresh=true' : ''}`);
      box.replaceChildren(...view(d));
    } catch (e) { box.replaceChildren(h('div.muted', {}, '统计失败：' + e.message)); }
  };

  function view(d) {
    const s = d.summary;
    const tiles = ui.stats([
      { k: `Agent 覆盖（统计 ${fmtMin(s.elapsed_min)} 里有 Agent 在跑 · 工作时间内 ${s.coverage_work_pct ?? '-'}%）`, v: s.coverage_pct + '%' },
      { k: `并发容量使用（上限 ${s.concurrency}）`, v: s.capacity_pct + '%' },
      { k: '空档（无 Agent 在跑）', v: fmtMin(s.idle_min) },
      { k: '人工交互 · 专注时间外', v: `${s.human_total} · ${s.human_out_focus}` },
      { k: `Agent 等你（墙钟 · 各会话累加 ${fmtMin(s.wait_total_min)}）`, v: fmtMin(s.wait_wall_min ?? s.wait_total_min) },
    ]);
    const parts = [tiles, chart(d)];
    if (!compact) {
      parts.push(h('div.uc-cols', {}, [
        h('div.card.flat', {}, [h('div.card-label', {}, '改进建议 · 可直接用于明天的规划'),
          h('ol.uc-advice', {}, d.advice.map((a) => h('li', {}, a)))]),
        h('div.card.flat', {}, [h('div.card-label', {}, '等你最久的几次'),
          d.top_waits.length ? h('div.list', {}, d.top_waits.map((w) => h('div.item', {}, [
            h('div.row', {}, [h('b', {}, `${w.start}–${w.end}`), h('span.tag' + (w.focus ? '.ok' : '.warn'), {}, w.focus ? '专注时间' : '专注外'),
              h('span.grow'), h('span.muted', {}, fmtMin(w.minutes))]),
            h('div.muted.clamp2', {}, `${w.project} · ${w.title || ''}`)]))) : h('div.muted', {}, '没有明显的等待')]),
      ]));
      parts.push(h('details.uc-humans', {}, [h('summary', {}, `人工交互明细（${d.humans.length}）`),
        h('div.list', {}, d.humans.slice().reverse().map((x) => h('div.item', {}, [
          h('div.row', {}, [h('b', {}, x.t), h('span.tag' + (x.focus ? '.ok' : '.warn'), {}, x.focus ? '专注' : '专注外'),
            h('span.tag.line', {}, x.label), h('span.muted', {}, x.project)]),
          h('div.muted.clamp2', {}, x.text)])))]));
    }
    parts.push(h('div.row.uc-foot', {}, [h('span.muted', {}, `${s.day} · ${s.sessions} 个会话（交互 ${s.interactive}）· 峰值并行 ${s.peak_parallel}`),
      h('span.grow'), h('button.sm.ghost', { onclick: () => load(true) }, [ui.icon('refresh'), '重新统计'])]));
    return parts;
  }

  function chart(d) {
    const slots = d.slots, n = slots.length;
    const W = 1000, H = 150, top = 8, barH = 78, waitY = 96, humanY = 122, xw = W / Math.max(1, n);
    const maxRun = Math.max(d.summary.concurrency, ...slots.map((s) => s.interactive + s.automated), 1);
    const y = (v) => top + barH - (v / maxRun) * barH;
    const ns = 'http://www.w3.org/2000/svg';
    const el = (tag, attrs, title) => { const e = document.createElementNS(ns, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (title) { const t = document.createElementNS(ns, 'title'); t.textContent = title; e.append(t); } return e; };
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'uc-svg', preserveAspectRatio: 'none' });
    const defs = el('defs', {});
    const pat = el('pattern', { id: 'uc-hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' });
    pat.append(el('rect', { width: 2, height: 6, class: 'uc-hatch' }));
    defs.append(pat); svg.append(defs);
    slots.forEach((s, i) => {
      const x = i * xw;
      if (s.focus) svg.append(el('rect', { x, y: 0, width: xw + 0.5, height: H - 18, class: 'uc-focus' }));
      if (!s.future && s.work && s.interactive + s.automated === 0) svg.append(el('rect', { x, y: top, width: xw + 0.5, height: barH, fill: 'url(#uc-hatch)' }, `${s.t} 无 Agent 在跑`));
      if (s.future) svg.append(el('rect', { x, y: top, width: xw + 0.5, height: barH, class: 'uc-future' }));
      const tip = `${s.t}  交互 Agent ${s.interactive} · 脚本 ${s.automated} · 等你 ${s.waiting} · 人工 ${s.humans}`;
      if (s.interactive) svg.append(el('rect', { x: x + 0.6, y: y(s.interactive), width: xw - 1.2, height: barH + top - y(s.interactive), class: 'uc-inter', rx: 1.5 }, tip));
      if (s.automated) svg.append(el('rect', { x: x + 0.6, y: y(s.interactive + s.automated), width: xw - 1.2, height: y(s.interactive) - y(s.interactive + s.automated), class: 'uc-auto', rx: 1.5 }, tip));
      if (s.waiting) svg.append(el('rect', { x: x + 0.6, y: waitY, width: xw - 1.2, height: Math.min(14, 4 + s.waiting * 3), class: 'uc-wait', rx: 1.5 }, tip));
      if (s.humans) svg.append(el('circle', { cx: x + xw / 2, cy: humanY + 6, r: Math.min(6, 2 + s.humans), class: s.focus ? 'uc-h-in' : 'uc-h-out' }, tip));
      if (s.t.endsWith(':00') && (+s.t.slice(0, 2)) % 2 === 0) {
        svg.append(el('line', { x1: x, x2: x, y1: top, y2: H - 18, class: 'uc-grid' }));
        const tx = el('text', { x: x + 2, y: H - 4, class: 'uc-tick' }); tx.textContent = s.t.slice(0, 2); svg.append(tx);
      }
    });
    svg.append(el('line', { x1: 0, x2: W, y1: y(d.summary.concurrency), y2: y(d.summary.concurrency), class: 'uc-cap' }, `并发上限 ${d.summary.concurrency}`));
    const legend = h('div.uc-legend', {}, [
      h('span', {}, [h('i.uc-l.inter'), '交互 Agent 在干活']), h('span', {}, [h('i.uc-l.auto'), '脚本 Agent']),
      h('span', {}, [h('i.uc-l.wait'), 'Agent 在等你']), h('span', {}, [h('i.uc-l.hin'), '人工交互（专注内）']),
      h('span', {}, [h('i.uc-l.hout'), '人工交互（专注外）']), h('span', {}, [h('i.uc-l.focus'), '专注时间']),
      h('span', {}, [h('i.uc-l.idle'), '空档']), h('span', {}, [h('i.uc-l.cap'), '并发上限']),
    ]);
    return h('div.card.flat.uc-chart', {}, [svg, legend]);
  }

  await load();
  return box;
}

const fmtMin = (m) => (m >= 60 ? `${(m / 60).toFixed(1)}h` : `${Math.round(m)}m`);

function injectStyle() {
  if (document.getElementById('uc-style')) return;
  const s = document.createElement('style');
  s.id = 'uc-style';
  s.textContent = `
  .uc .stats { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .uc-chart { padding: 12px 14px 10px; }
  .uc-svg { width: 100%; height: 170px; display: block; }
  .uc-focus { fill: var(--focus); } .uc-future { fill: var(--bg-2); opacity: .5; }
  .uc-hatch { fill: var(--err); opacity: .18; }
  .uc-inter { fill: var(--accent); } .uc-auto { fill: var(--accent); opacity: .35; }
  .uc-wait { fill: var(--muted); opacity: .55; }
  .uc-h-in { fill: var(--ok); } .uc-h-out { fill: var(--warn); }
  .uc-grid { stroke: var(--line); stroke-width: 1; } .uc-tick { font: 10px var(--font); fill: var(--muted); }
  .uc-cap { stroke: var(--text); stroke-dasharray: 4 4; stroke-width: 1; opacity: .45; }
  .uc-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--muted); margin-top: 6px; }
  .uc-legend span { display: inline-flex; align-items: center; gap: 5px; }
  .uc-l { display: inline-block; width: 12px; height: 9px; border-radius: 2px; }
  .uc-l.inter { background: var(--accent); } .uc-l.auto { background: var(--accent); opacity: .35; } .uc-l.wait { background: var(--muted); opacity: .55; }
  .uc-l.hin { background: var(--ok); border-radius: 50%; width: 9px; } .uc-l.hout { background: var(--warn); border-radius: 50%; width: 9px; }
  .uc-l.focus { background: var(--focus); border: 1px solid var(--line-2); }
  .uc-l.idle { background: repeating-linear-gradient(45deg, var(--err-soft), var(--err-soft) 2px, transparent 2px, transparent 5px); border: 1px solid var(--err-soft); }
  .uc-l.cap { height: 0; border-top: 1px dashed var(--text); opacity: .5; }
  .uc-cols { display: grid; grid-template-columns: 1.4fr 1fr; gap: 12px; }
  .uc-advice { margin: 4px 0 0; padding-left: 20px; } .uc-advice li { margin: 6px 0; line-height: 1.6; }
  .uc-humans { margin: 4px 0 10px; } .uc-humans .list { max-height: 360px; overflow: auto; margin-top: 8px; }
  .uc-foot { margin-top: 4px; }
  @media (max-width: 1000px) { .uc .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .uc-cols { grid-template-columns: 1fr; } }
  `;
  document.head.append(s);
}
