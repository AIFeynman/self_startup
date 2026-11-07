// 时间利用图（复盘 · Agent 效率）：一天里每个会话一条泳道
//   颜色 = 项目，实色 = 在干活，灰斜纹 = 在等你，圆点 = 人工交互（实心专注内、空心专注外）
//   顶部两行是总览：每 10 分钟几个 Agent 在跑（虚线 = 并发上限，红斜纹 = 空档）、几个在等你；底部按项目累加
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
      { k: `Agent 活跃（各会话累加 ${fmtMin(s.agent_active_min)}）`, v: fmtMin(s.agent_active_wall_min) },
      { k: `覆盖率（工作时间内 ${s.coverage_work_pct}%）`, v: s.coverage_pct + '%' },
      { k: `并发容量使用（上限 ${s.concurrency}）`, v: s.capacity_pct + '%' },
      { k: `Agent 等你（各会话累加 ${fmtMin(s.wait_total_min)}）`, v: fmtMin(s.wait_wall_min) },
      { k: '空档（无 Agent 在跑）', v: fmtMin(s.idle_min) },
      { k: `人工交互（专注外 ${s.human_out_focus} 次）`, v: `${s.human_total} 次` },
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
    const marks = [
      ...d.lanes.flatMap((l) => [...l.active, ...l.waits]).flatMap((x) => [toMin(x.start), endOf(x)]),
      ...d.lanes.flatMap((l) => l.humans.map((x) => toMin(x.t))),
      ...d.gaps.flatMap((x) => [toMin(x.start), endOf(x)]),
    ];
    if (!marks.length) return h('div.card.flat.muted', {}, '这一天没有 Agent 活动');
    const from = Math.floor(Math.min(...marks) / 60) * 60;
    const to = Math.max(Math.ceil(Math.max(...marks) / 60) * 60, from + 60);
    const span = to - from;
    const place = (start, end) => ({ left: `${(start - from) / span * 100}%`, width: `${(end - start) / span * 100}%` });
    const colorOf = projectColors(d.by_project);

    const detail = h('div.uc-detail.muted', {}, '指向或点一段看它在做什么');
    let picked = null;
    const hot = (node, text) => {
      const show = () => { detail.textContent = text; detail.classList.remove('muted'); };
      node.onmouseenter = show;
      node.onclick = () => { picked?.classList.remove('on'); picked = node; node.classList.add('on'); show(); };
      return node;
    };
    const mark = (cls, x, text, style) => hot(h(`button.${cls}`, { type: 'button', title: text, 'aria-label': text, style: { ...place(toMin(x.start), endOf(x)), ...style } }), text);

    const slots = d.slots.filter((x) => toMin(x.t) >= from && toMin(x.t) < to);
    const peak = Math.max(d.summary.concurrency, ...slots.map((x) => x.interactive + x.automated), 1);
    const peakWait = Math.max(1, ...slots.map((x) => x.waiting));
    const slotAt = (x) => place(toMin(x.t), toMin(x.t) + 10);
    const slotText = (x) => `${x.t} 起 10 分钟 · 交互 Agent ${x.interactive} · 脚本 ${x.automated} · 等你 ${x.waiting} · 人工 ${x.humans}`;
    const gapText = (x) => `${x.start}–${x.end} · 空档 ${x.minutes} 分钟 · 没有 Agent 在跑${x.in_focus ? `（专注时间内 ${x.in_focus} 分钟）` : ''}`;
    const runRow = row(h('div.uc-lab', {}, [h('b', {}, '同时在跑'), h('span', {}, `峰值 ${d.summary.peak_parallel} 个`)]), h('div.uc-track.run', {}, [
      ...d.gaps.map((x) => mark('uc-gap', x, gapText(x))),
      ...slots.map((x) => hot(h('div.uc-slot', { title: slotText(x), style: slotAt(x) }, [
        h('i.inter', { style: { height: `${x.interactive / peak * 100}%` } }),
        h('i.auto', { style: { height: `${x.automated / peak * 100}%` } }),
      ]), slotText(x))),
      h('div.uc-cap', { title: `并发上限 ${d.summary.concurrency}`, style: { bottom: `${d.summary.concurrency / peak * 100}%` } }),
    ]));
    const waitRow = row(h('div.uc-lab', {}, [h('b', {}, '在等你'), h('span', {}, `墙钟 ${fmtMin(d.summary.wait_wall_min)}`)]), h('div.uc-track.wait', {},
      slots.filter((x) => x.waiting).map((x) => hot(h('div.uc-slot', { title: slotText(x), style: slotAt(x) }, [
        h('i.waiting', { style: { height: `${x.waiting / peakWait * 100}%` } }),
      ]), slotText(x)))));

    const laneRow = (l) => {
      const name = l.title || l.project;
      const say = (x, what) => `${x.start === x.end ? x.start : `${x.start}–${x.end}`} · ${l.project}${l.title && l.title !== l.project ? ` · ${l.title}` : ''} · ${what} ${x.minutes} 分钟`;
      return row(h('div.uc-lab', { title: name }, [h('b', {}, name),
        h('span', {}, [l.automated ? `${l.sessions} 个会话` : l.project, ` · 干活 ${fmtMin(l.active_min)}`, l.wait_min ? ` · 等 ${fmtMin(l.wait_min)}` : '']) ]),
      h('div.uc-track', {}, [
        ...l.waits.map((x) => mark('uc-w', x, say(x, '等你'))),
        ...l.active.map((x) => mark('uc-a', x, say(x, '干活'), { background: colorOf(l.project) })),
        ...l.humans.map((x) => {
          const text = `${x.t} · 人工${x.label} · ${x.focus ? '专注内' : '专注外'} · ${l.project} · ${x.text}`;
          return hot(h('button.uc-h' + (x.focus ? '' : '.out'), { type: 'button', title: text, 'aria-label': text, style: { left: `${(toMin(x.t) + 0.5 - from) / span * 100}%` } }), text);
        }),
      ]));
    };
    const weight = (l) => l.active_min + l.wait_min;
    const people = d.lanes.filter((l) => !l.automated);
    const main = new Set([...people].sort((a, b) => weight(b) - weight(a)).slice(0, MAIN_LANES));
    const rest = people.filter((l) => !main.has(l));
    const scripts = d.lanes.filter((l) => l.automated);

    const step = span <= 480 ? 60 : span <= 960 ? 120 : 180;
    const ticks = [];
    for (let m = from; m <= to; m += step) ticks.push(m);
    const hoursAt = [];
    for (let m = from; m <= to; m += 60) hoursAt.push(m);
    const over = h('div.uc-over', {}, [
      ...d.focus.filter((x) => toMin(x.start) < to && endOf(x) > from).map((x) => h('i.uc-band', { style: place(Math.max(toMin(x.start), from), Math.min(endOf(x), to)) })),
      ...hoursAt.map((m) => h('i.uc-hour', { style: { left: `${(m - from) / span * 100}%` } })),
    ]);
    const axis = row(h('div.uc-lab'), h('div.uc-axis', {}, ticks.map((m) => h('span', { style: { left: `${(m - from) / span * 100}%` } }, `${m / 60}:00`))));

    const legend = h('div.uc-legend', {}, [
      h('span', {}, [h('i.uc-l.inter'), '交互 Agent']), h('span', {}, [h('i.uc-l.auto'), '脚本 Agent']),
      h('span', {}, [h('i.uc-l.active'), '会话在干活（颜色 = 项目）']), h('span', {}, [h('i.uc-l.waitl'), '在等你']),
      h('span', {}, [h('i.uc-l.hin'), '人工交互 · 专注内']), h('span', {}, [h('i.uc-l.hout'), '人工交互 · 专注外']),
      h('span', {}, [h('i.uc-l.focus'), '专注时间']), h('span', {}, [h('i.uc-l.idle'), '空档']), h('span', {}, [h('i.uc-l.cap'), '并发上限']),
    ]);
    return h('div.card.flat.uc-chart', {}, [
      detail,
      h('div.uc-grid', {}, [
        over, axis, runRow, waitRow, h('div.uc-sep'),
        ...people.filter((l) => main.has(l)).map(laneRow),
        rest.length ? h('details.uc-rest', {}, [h('summary', {}, `其余 ${rest.length} 个短会话（干活 ${fmtMin(rest.reduce((n, l) => n + l.active_min, 0))} · 等 ${fmtMin(rest.reduce((n, l) => n + l.wait_min, 0))}）`), ...rest.map(laneRow)]) : null,
        ...scripts.map(laneRow),
      ]),
      legend,
      projectBars(d.by_project, colorOf),
    ]);
  }

  function row(label, track) { return h('div.uc-row', {}, [label, track]); }

  function projectBars(projects, colorOf) {
    const shown = projects.slice(0, MAIN_PROJECTS);
    const others = projects.slice(MAIN_PROJECTS);
    const rows = others.length ? [...shown, { project: `其他 ${others.length} 个项目`, active_min: others.reduce((n, p) => n + p.active_min, 0), wait_min: others.reduce((n, p) => n + p.wait_min, 0) }] : shown;
    const longest = Math.max(1, ...rows.map((p) => p.active_min + p.wait_min));
    return h('div.uc-projects', {}, [
      h('div.card-label', {}, '按项目 · 各会话累加'),
      ...rows.map((p) => h('div.uc-project', {}, [
        h('span.uc-pname', { title: p.project }, p.project),
        h('div.uc-pbar', {}, [
          h('i.a', { style: { width: `${p.active_min / longest * 100}%`, background: colorOf(p.project) } }),
          h('i.w', { style: { width: `${p.wait_min / longest * 100}%` } }),
        ]),
        h('span.uc-pval', {}, `干活 ${fmtMin(p.active_min)} · 等 ${fmtMin(p.wait_min)}`),
      ])),
    ]);
  }

  await load();
  return box;
}

const MAIN_LANES = 12;
const MAIN_PROJECTS = 8;
const PROJECT_HUES = 6;
const fmtMin = (m) => (m >= 60 ? `${(m / 60).toFixed(1)}h` : `${Math.round(m)}m`);
const toMin = (t) => +t.slice(0, 2) * 60 + +t.slice(3, 5);
const endOf = (x) => { const e = toMin(x.end); return e < toMin(x.start) ? 1440 : e; };

function projectColors(projects) {
  const slots = new Map();
  const taken = new Set();
  projects.filter((p) => p.project !== '脚本任务').slice(0, PROJECT_HUES).forEach((p) => {
    let i = [...p.project].reduce((n, c) => (n * 31 + c.codePointAt(0)) % 9973, 7) % PROJECT_HUES;
    while (taken.has(i)) i = (i + 1) % PROJECT_HUES;
    taken.add(i);
    slots.set(p.project, i);
  });
  return (name) => (slots.has(name) ? `var(--uc-p${slots.get(name)})` : 'var(--muted)');
}

function injectStyle() {
  if (document.getElementById('uc-style')) return;
  const s = document.createElement('style');
  s.id = 'uc-style';
  s.textContent = `
  .uc { --uc-p0: #2a78d6; --uc-p1: #eb6834; --uc-p2: #1baf7a; --uc-p3: #eda100; --uc-p4: #e87ba4; --uc-p5: #6250d6; --uc-lab: 200px; --uc-gap: 12px; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .uc { --uc-p0: #3987e5; --uc-p1: #d95926; --uc-p2: #199e70; --uc-p3: #c98500; --uc-p4: #d55181; --uc-p5: #9085e9; } }
  :root[data-theme="dark"] .uc { --uc-p0: #3987e5; --uc-p1: #d95926; --uc-p2: #199e70; --uc-p3: #c98500; --uc-p4: #d55181; --uc-p5: #9085e9; }
  .uc .stats { grid-template-columns: repeat(6, minmax(0, 1fr)); }
  .uc-chart { padding: 14px 16px 12px; }
  .uc-detail { min-height: 20px; margin-bottom: 10px; font-size: 13px; overflow-wrap: anywhere; }
  .uc-grid { position: relative; }
  .uc-over { position: absolute; top: 0; bottom: 0; left: calc(var(--uc-lab) + var(--uc-gap)); right: 0; pointer-events: none; }
  .uc-band { position: absolute; top: 0; bottom: 0; background: var(--focus); }
  .uc-hour { position: absolute; top: 18px; bottom: 0; width: 1px; background: var(--line); }
  .uc-row { position: relative; display: grid; grid-template-columns: var(--uc-lab) minmax(0, 1fr); gap: var(--uc-gap); align-items: center; min-height: 36px; }
  .uc-lab { min-width: 0; line-height: 1.3; }
  .uc-lab b, .uc-lab span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .uc-lab b { font-weight: 500; font-size: 13px; }
  .uc-lab span { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .uc-axis { container-type: inline-size; position: relative; height: 18px; font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .uc-axis span { position: absolute; transform: translateX(-50%); }
  .uc-axis span:first-child { transform: none; } .uc-axis span:last-child { transform: translateX(-100%); }
  @container (max-width: 420px) { .uc-axis span:nth-last-child(even) { visibility: hidden; } }
  .uc-sep { height: 1px; margin: 6px 0; background: var(--line-2); position: relative; }
  .uc-track { position: relative; height: 20px; }
  .uc-track.run { height: 48px; border-bottom: 1px solid var(--line-2); }
  .uc-track.wait { height: 24px; border-bottom: 1px solid var(--line-2); }
  .uc-slot { position: absolute; top: 0; bottom: 0; display: flex; flex-direction: column; justify-content: flex-end; cursor: pointer; }
  .uc-slot i { display: block; margin: 0 .5px; }
  .uc-slot i.auto { order: 0; background: var(--text); opacity: .28; border-radius: 2px 2px 0 0; }
  .uc-slot i.inter { order: 1; background: var(--text); opacity: .72; }
  .uc-slot i.waiting { background: repeating-linear-gradient(135deg, var(--muted) 0 1.5px, transparent 1.5px 4px); }
  .uc-slot:hover i, .uc-slot.on i { opacity: 1; }
  .uc-gap { position: absolute; top: 0; bottom: 0; padding: 0; border: 0; border-radius: 0; cursor: pointer; background: repeating-linear-gradient(45deg, var(--err-soft) 0 3px, transparent 3px 8px); }
  .uc-cap { position: absolute; left: 0; right: 0; height: 0; border-top: 1px dashed var(--text); opacity: .45; pointer-events: none; }
  .uc-a, .uc-w { position: absolute; top: 2px; bottom: 2px; min-width: 2px; padding: 0; border: 0; border-radius: 3px; cursor: pointer; box-shadow: 0 0 0 1px var(--panel); }
  .uc-w { background: var(--bg-2) repeating-linear-gradient(135deg, var(--muted) 0 1.5px, transparent 1.5px 5px); box-shadow: none; }
  .uc-a:hover, .uc-w:hover, .uc-a.on, .uc-w.on { outline: 2px solid var(--text); outline-offset: 0; z-index: 2; }
  .uc-h { position: absolute; top: 50%; width: 7px; height: 7px; padding: 0; border-radius: 50%; border: 1px solid var(--panel); background: var(--text); box-sizing: content-box; transform: translate(-50%, -50%); cursor: pointer; z-index: 1; }
  .uc-h.out { background: var(--panel); box-shadow: inset 0 0 0 1.5px var(--text); }
  .uc-h:hover, .uc-h.on { outline: 2px solid var(--text); z-index: 3; }
  .uc-rest > summary { position: relative; cursor: pointer; font-size: 12.5px; color: var(--muted); margin: 6px 0; }
  .uc-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: var(--muted); margin-top: 12px; }
  .uc-legend span { display: inline-flex; align-items: center; gap: 5px; }
  .uc-l { display: inline-block; width: 12px; height: 9px; border-radius: 2px; }
  .uc-l.inter { background: var(--text); opacity: .72; } .uc-l.auto { background: var(--text); opacity: .28; }
  .uc-l.active { background: linear-gradient(90deg, var(--uc-p0) 50%, var(--uc-p1) 50%); }
  .uc-l.waitl { background: repeating-linear-gradient(135deg, var(--muted) 0 1.5px, transparent 1.5px 4px); }
  .uc-l.hin { width: 9px; border-radius: 50%; background: var(--text); } .uc-l.hout { width: 9px; border-radius: 50%; box-shadow: inset 0 0 0 2px var(--text); }
  .uc-l.focus { background: var(--focus); border: 1px solid var(--line-2); }
  .uc-l.idle { background: repeating-linear-gradient(45deg, var(--err-soft) 0 2px, transparent 2px 5px); border: 1px solid var(--err-soft); }
  .uc-l.cap { height: 0; border-top: 1px dashed var(--text); opacity: .5; }
  .uc-projects { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
  .uc-project { display: grid; grid-template-columns: var(--uc-lab) minmax(0, 1fr) 150px; gap: var(--uc-gap); align-items: center; font-size: 13px; margin-top: 7px; }
  .uc-pname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .uc-pbar { display: flex; gap: 2px; height: 12px; }
  .uc-pbar i { display: block; height: 100%; border-radius: 2px; }
  .uc-pbar i.w { background: repeating-linear-gradient(135deg, var(--muted) 0 1.5px, transparent 1.5px 4px); }
  .uc-pval { color: var(--muted); font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .uc-cols { display: grid; grid-template-columns: 1.4fr 1fr; gap: 12px; }
  .uc-advice { margin: 4px 0 0; padding-left: 20px; } .uc-advice li { margin: 6px 0; line-height: 1.6; }
  .uc-humans { margin: 4px 0 10px; } .uc-humans .list { max-height: 360px; overflow: auto; margin-top: 8px; }
  .uc-foot { margin-top: 4px; }
  @media (max-width: 1000px) { .uc .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); } .uc-cols { grid-template-columns: 1fr; } }
  @media (max-width: 700px) {
    .uc { --uc-lab: 0px; --uc-gap: 0px; }
    .uc .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .uc-row { grid-template-columns: minmax(0, 1fr); padding-bottom: 4px; }
    .uc-hour { opacity: .5; }
    .uc-project { grid-template-columns: minmax(0, 1fr) auto; }
    .uc-pbar { grid-column: 1 / -1; grid-row: 2; }
  }
  `;
  document.head.append(s);
}
