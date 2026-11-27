// 实践：知识讲解 + 可运行代码交替的课程（类 Colab）。路由 #practice / #practice/<课程> / #practice/<课程>/<课>。
// 代码在运行环境里执行（阿里云 GPU 用时才开机 / 本机），输出由后端收集、这里轮询；ss 库的可视化在这里原生渲染。
// 每一步包一层批注组件：可以问本机 Claude（带上讲解 + 代码 + 最新输出 / 报错），讨论会保存、同步进知识库。
import { annotate } from './_annotate.js';

const VIZ = 'application/vnd.ssviz+json';
const RT_NAME = { cloud: '阿里云 GPU', local: '本机' };
const ST_NAME = { stopped: '未开机', starting: '开机中', ready: '已就绪', stopping: '释放中', failed: '出错' };

const CSS = `
.pr-wrap { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 18px; align-items: start; }
.pr-toc { position: sticky; top: 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); padding: 6px 0; }
.pr-toc a { display: block; padding: 6px 12px; font-size: 13.5px; color: var(--text); text-decoration: none; border-left: 3px solid transparent; }
.pr-toc a.on { background: var(--accent-soft); border-left-color: var(--accent); color: var(--accent); }
.pr-toc a.done::before { content: '✓ '; color: var(--ok); }
.pr-toc .hd { font-size: 12px; color: var(--muted); padding: 4px 12px 6px; }
.pr-rt { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel);
  padding: 8px 12px; margin: 0 0 14px; font-size: 13px; position: sticky; top: 0; z-index: 5; }
.pr-rt .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.pr-rt .dot.ready { background: var(--ok); } .pr-rt .dot.starting, .pr-rt .dot.stopping { background: var(--warn); animation: prb 1s infinite alternate; }
.pr-rt .dot.failed { background: var(--err); }
@keyframes prb { to { opacity: .3; } }
.pr-rt .log { flex-basis: 100%; font: 12px/1.5 var(--mono); color: var(--muted); white-space: pre-wrap; max-height: 9em; overflow: auto; margin: 4px 0 0; }
.pr-know { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 4px; align-items: center; }
.pr-know button { border: 1px solid var(--line-2); background: var(--panel); border-radius: 999px; padding: 1px 10px; font-size: 12.5px; color: var(--text); }
.pr-know button.on { border-color: var(--accent); color: var(--accent); }
.pr-kpop { border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); padding: 8px 12px; margin: 6px 0; font-size: 13.5px; }
.pr-kpop a { display: block; padding: 2px 0; }
.pr-step { border-top: 1px solid var(--line); padding: 14px 0 6px; }
.pr-step > h3 { margin: 0 0 6px; font-size: 17px; }
.pr-step .md { font-size: 15px; line-height: 1.75; }
.pr-cell { border: 1px solid var(--line); border-radius: 10px; margin: 10px 0; overflow: hidden; background: var(--panel); }
.pr-cell .bar { display: flex; gap: 8px; align-items: center; padding: 4px 8px; font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.pr-cell .bar button { padding: 1px 10px; font-size: 12px; }
.pr-cell .bar .st.run { color: var(--warn); } .pr-cell .bar .st.ok { color: var(--ok); } .pr-cell .bar .st.err { color: var(--err); }
.pr-code { display: block; width: 100%; box-sizing: border-box; border: 0; border-radius: 0; resize: vertical; padding: 10px 12px; margin: 0;
  font: 13px/1.55 var(--mono); background: #23211e; color: #f1ece4; tab-size: 4; white-space: pre; overflow-x: auto; }
.pr-out { padding: 6px 12px 10px; font-size: 13px; }
.pr-out:empty { display: none; }
.pr-out pre { margin: 6px 0; white-space: pre-wrap; word-break: break-word; font: 12.5px/1.5 var(--mono); max-height: 360px; overflow: auto; }
.pr-out pre.err { color: var(--err); background: var(--err-soft); padding: 6px 8px; border-radius: 6px; }
.pr-out pre.stderr { color: var(--muted); }
.pr-out img { max-width: 100%; }
.pr-ask { border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 8px 8px 0; padding: 8px 12px; margin: 10px 0; font-size: 14.5px; display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.pr-ask b { color: var(--accent); }
.pr-ask span { flex: 1; min-width: 200px; }
.vz { margin: 8px 0; } .vz > .t { font-weight: 600; font-size: 13px; margin: 0 0 4px; }
.vz-kv { display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px; font-size: 13.5px; } .vz-kv dt { color: var(--muted); } .vz-kv dd { margin: 0; font-variant-numeric: tabular-nums; }
.vz-tb { overflow-x: auto; } .vz-tb table { border-collapse: collapse; font-size: 12.5px; min-width: 100%; }
.vz-tb td, .vz-tb th { border-bottom: 1px solid var(--line); padding: 3px 8px; text-align: left; vertical-align: top; } .vz-tb th { color: var(--muted); font-weight: 600; white-space: nowrap; }
.vz-bars div.r { display: grid; grid-template-columns: minmax(70px, 30%) 1fr auto; gap: 8px; align-items: center; font-size: 12.5px; margin: 2px 0; }
.vz-bars i { display: block; height: 12px; background: var(--accent); border-radius: 3px; min-width: 2px; }
.vz-stack { display: flex; height: 22px; border-radius: 5px; overflow: hidden; } .vz-stack i { display: block; height: 100%; }
.vz-leg { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; margin-top: 4px; } .vz-leg span::before { content: ''; display: inline-block; width: 9px; height: 9px; border-radius: 2px; background: var(--c); margin-right: 4px; }
.vz-tok span { display: inline-block; border-radius: 3px; padding: 1px 3px; margin: 1px; font: 13px/1.5 var(--mono); color: #222; white-space: pre; }
.vz-cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } .vz-cmp > div { border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; }
.vz-cmp b { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; } .vz-cmp pre { margin: 0; white-space: pre-wrap; font: 12.5px/1.55 var(--mono); }
.vz-heat { display: grid; gap: 1px; font-size: 10px; overflow-x: auto; } .vz-heat i { display: block; min-width: 14px; height: 14px; }
.vz-line svg { width: 100%; height: auto; max-height: 260px; } .vz-line svg text { fill: var(--muted); font-size: 10px; }
.vz-line pre { font: 11.5px/1.45 var(--mono); color: var(--muted); max-height: 9em; overflow: auto; margin: 4px 0 0; white-space: pre-wrap; }
.vz-trace > div { border-left: 3px solid var(--line-2); padding: 3px 10px; margin: 4px 0; font-size: 13px; white-space: pre-wrap; word-break: break-word; }
.vz-trace .user { border-color: var(--muted); } .vz-trace .thought { border-color: var(--warn); } .vz-trace .tool { border-color: var(--accent); font-family: var(--mono); font-size: 12px; }
.vz-trace .assistant { border-color: var(--ok); font-weight: 600; } .vz-trace small { color: var(--muted); margin-right: 6px; font-weight: 400; }
.vz-note { border-radius: 6px; padding: 5px 10px; background: var(--bg-2); font-size: 13px; } .vz-note.warn { background: var(--warn-soft); }
.pr-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.pr-card { border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); padding: 12px 14px; cursor: pointer; }
.pr-card:hover { border-color: var(--accent); } .pr-card h3 { margin: 0 0 4px; font-size: 16px; }
.pr-card .meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 12.5px; color: var(--muted); margin-top: 8px; }
.pr-modal { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: flex; align-items: center; justify-content: center; z-index: 50; padding: 16px; }
.pr-modal > div { background: var(--panel); border-radius: 12px; padding: 18px 20px; max-width: 460px; width: 100%; box-shadow: var(--shadow); }
.pr-modal dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; font-size: 14px; } .pr-modal dt { color: var(--muted); } .pr-modal dd { margin: 0; }
.pr-nav { display: flex; justify-content: space-between; gap: 10px; margin: 20px 0 40px; }
@media (max-width: 760px) {
  .pr-wrap { grid-template-columns: 1fr; }
  .pr-toc { position: static; display: flex; overflow-x: auto; padding: 0; } .pr-toc .hd { display: none; }
  .pr-toc a { white-space: nowrap; border-left: 0; border-bottom: 3px solid transparent; } .pr-toc a.on { border-bottom-color: var(--accent); }
  .vz-cmp { grid-template-columns: 1fr; }
}
`;

const enc = encodeURIComponent;
const ansi = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, '');
const PALETTE = ['#b8432f', '#2f7a4a', '#c9a96e', '#4a6fa5', '#8a5aa8', '#3a9a9a', '#a5664a', '#777'];

export default {
  async render(el, ctx) {
    const { h } = ctx;
    el.append(h('style', {}, CSS));
    const [cid, lid] = ctx.sub || [];
    if (cid && lid) return lessonPage(el, ctx, cid, lid);
    if (cid) return coursePage(el, ctx, cid);
    return homePage(el, ctx);
  },
};

// ---------- 可视化 ----------

function viz(ctx, d) {
  const { h } = ctx;
  const title = d.title ? h('div.t', {}, d.title) : null;
  const box = (cls, kids) => h('div.vz.' + cls, {}, [title, ...kids]);
  switch (d.kind) {
    case 'kv':
      return box('vz-kvb', [h('dl.vz-kv', {}, d.items.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))]);
    case 'table':
      return box('vz-tb', [h('table', {}, [h('tr', {}, d.cols.map((c) => h('th', {}, c))), ...d.rows.map((r) => h('tr', {}, r.map((x) => h('td', {}, x))))])]);
    case 'bars': {
      const mx = Math.max(1e-9, ...d.items.map((x) => Math.abs(x[1])));
      if (d.stacked) {
        const sum = d.items.reduce((a, x) => a + x[1], 0) || 1;
        return box('vz-bars', [h('div.vz-stack', {}, d.items.map((x, i) => h('i', { title: `${x[0]} ${x[1]}${d.unit}`, style: { width: `${(x[1] / sum) * 100}%`, background: PALETTE[i % 8] } }))),
          h('div.vz-leg', {}, d.items.map((x, i) => h('span', { style: { '--c': PALETTE[i % 8] } }, `${x[0]} ${x[1]}${d.unit}（${Math.round((x[1] / sum) * 100)}%）`)))]);
      }
      return box('vz-bars', d.items.map((x) => h('div.r', {}, [h('span', {}, x[0]), h('i', { style: { width: `${(Math.abs(x[1]) / mx) * 100}%` } }), h('span', {}, `${x[1]}${d.unit}`)])));
    }
    case 'tokens':
      return box('vz-tok', [h('div', {}, d.items.map(([t, id], i) => h('span', { title: `#${i} · id ${id}`, style: { background: `hsl(${(i * 67) % 360} 70% 84%)` } }, t.replace(/\n/g, '↵'))))]);
    case 'compare':
      return box('vz-cmp-b', [h('div.vz-cmp', {}, [d.a, d.b].map(([t, x]) => h('div', {}, [h('b', {}, t), h('pre', {}, x)])))]);
    case 'heat': {
      const flat = d.values.flat(), mx = Math.max(...flat), mn = Math.min(...flat);
      return box('vz-heatb', [h('div.vz-heat', { style: { gridTemplateColumns: `max-content repeat(${d.cols.length}, minmax(14px, 1fr))` } }, [
        h('span'), ...d.cols.map((c) => h('span', { style: { writingMode: 'vertical-rl' } }, c)),
        ...d.values.flatMap((r, i) => [h('span', {}, d.rows[i]), ...r.map((v) => h('i', { title: v, style: { background: `rgba(184,67,47,${mx > mn ? (v - mn) / (mx - mn) : 0})` } }))])])]);
    }
    case 'line':
      return box('vz-line', [lineSvg(ctx, d), d.samples?.length ? h('div.vz-trace', {}, d.samples.map(([s, t]) => h('div.assistant', {}, [h('small', {}, `step ${s}`), t]))) : null,
        d.tail?.length ? h('pre', {}, d.tail.map(ansi).join('\n')) : null]);
    case 'trace':
      return box('vz-trace', d.steps.map((s) => h('div.' + (s.role || 'user'), {}, [h('small', {}, { user: '任务', thought: '决定调用', tool: '工具返回', assistant: '最终答案' }[s.role] || s.role),
        s.name ? h('small', {}, s.name) : null, s.text])));
    case 'note':
      return h('div.vz.vz-note' + (d.level === 'warn' ? '.warn' : ''), {}, d.text);
    default:
      return h('pre', {}, JSON.stringify(d).slice(0, 2000));
  }
}

function lineSvg(ctx, d) {
  const W = 600, H = 220, L = 44, B = 22;
  const pts = d.series.flatMap((s) => s[1]);
  if (!pts.length) return ctx.h('div.muted', {}, '等第一批日志…');
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1), y0 = Math.min(...ys), y1 = Math.max(...ys, y0 + 1e-6);
  const X = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - 8), Y = (y) => 8 + (1 - (y - y0) / (y1 - y0)) * (H - B - 8);
  const ticks = [y0, (y0 + y1) / 2, y1];
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${d.y} 曲线">
${ticks.map((t) => `<line x1="${L}" x2="${W}" y1="${Y(t)}" y2="${Y(t)}" stroke="currentColor" opacity=".12"/><text x="${L - 4}" y="${Y(t) + 3}" text-anchor="end">${t.toFixed(2)}</text>`).join('')}
<text x="${L}" y="${H - 4}">${d.x} ${x0}</text><text x="${W - 8}" y="${H - 4}" text-anchor="end">${x1}</text>
${d.series.map((s, i) => `<polyline fill="none" stroke="${PALETTE[i % 8]}" stroke-width="2" points="${s[1].map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ')}"/>`).join('')}
<text x="${W - 8}" y="14" text-anchor="end">${d.y} ${ys[ys.length - 1].toFixed(3)}</text></svg>`;
  return ctx.h('div', { html: svg });
}

function renderOutputs(ctx, box, outputs) {
  const { h } = ctx;
  box.replaceChildren(...outputs.map((o) => {
    if (o.type === 'stream') return h('pre' + (o.name === 'stderr' ? '.stderr' : ''), {}, ansi(o.text));
    if (o.type === 'error') return h('pre.err', {}, [`${o.ename}: ${o.evalue}\n`, ansi((o.traceback || []).slice(-6).join('\n'))]);
    const d = o.data || {};
    if (d[VIZ]) return viz(ctx, d[VIZ]);
    if (d['image/png']) return h('img', { src: 'data:image/png;base64,' + d['image/png'], alt: '输出图' });
    if (d['image/svg+xml']) return h('div', { html: d['image/svg+xml'] });
    if (d['text/html']) return h('iframe', { sandbox: '', srcdoc: d['text/html'], style: { width: '100%', border: 0, minHeight: '120px' } });
    return h('pre', {}, d['text/plain'] || '');
  }));
}

const outText = (outputs) => outputs.map((o) => (o.type === 'stream' ? o.text : o.type === 'error' ? `${o.ename}: ${o.evalue}\n${ansi((o.traceback || []).slice(-4).join('\n'))}`
  : o.data?.[VIZ] ? JSON.stringify(o.data[VIZ]).slice(0, 1500) : o.data?.['text/plain'] || '')).join('\n').slice(-6000);

// ---------- 运行环境条 ----------

function runtimeBar(ctx, kind, cid) {
  const { h, api, toast } = ctx;
  const bar = h('div.pr-rt');
  let v = null, timer = null, showLog = false, waiters = [];
  const fmtMin = (s) => `${Math.max(0, Math.round((Date.now() / 1000 - s) / 60))} 分钟`;
  const paint = () => {
    const st = v?.status || 'stopped';
    const parts = [h('span.dot.' + st), h('b', {}, RT_NAME[kind]), h('span', {}, ST_NAME[st] || st)];
    if (kind === 'cloud' && v?.started_at && ['starting', 'ready'].includes(st)) parts.push(h('span.muted', {}, `已开 ${fmtMin(v.started_at)} · 约 ${v.cost} 元 · ${v.price} 元/小时`));
    if (kind === 'cloud' && st === 'ready') parts.push(h('span.muted', {}, `空闲 ${v.idle_min} 分钟或满 ${v.cap} 元自动释放`));
    if (st === 'starting' || st === 'failed') parts.push(h('span.muted', {}, (v?.error || (v?.log || '').trim().split('\n').pop() || '').slice(0, 120)));
    parts.push(h('span.grow'));
    if (v?.log) parts.push(h('button.sm.ghost', { onclick: () => { showLog = !showLog; paint(); } }, showLog ? '收起日志' : '日志'));
    if (st === 'ready' && cid) parts.push(h('button.sm.ghost', { title: '清空这门课的变量，从头再跑', onclick: async () => { await api.post('/api/practice/restart', { course: cid, kind }); toast('内核已重启，变量已清空'); } }, '重启内核'));
    if (['stopped', 'failed'].includes(st)) parts.push(h('button.sm.primary', { onclick: () => start() }, kind === 'cloud' ? '开机' : '启动'));
    if (['ready', 'starting'].includes(st)) parts.push(h('button.sm.ghost', { onclick: async () => { if (kind === 'cloud' && !confirm('释放云端机器？权重会先拉回本机。')) return; v = await api.post('/api/practice/runtime/stop', { kind }); paint(); poll(); } }, kind === 'cloud' ? '释放' : '停止'));
    if (showLog && v?.log) parts.push(h('pre.log', {}, v.log));
    bar.replaceChildren(...parts);
  };
  const poll = async () => {
    clearTimeout(timer);
    if (!bar.isConnected && v) return;
    try { v = (await api.get('/api/practice/runtime'))[kind]; } catch { /* 下次再试 */ }
    paint();
    if (v?.status === 'ready') { const w = waiters; waiters = []; w.forEach((f) => f()); }
    if (v?.status === 'failed') { const w = waiters; waiters = []; w.forEach((f) => f(new Error(v.error || '运行环境启动失败'))); }
    timer = setTimeout(poll, ['starting', 'stopping'].includes(v?.status) ? 2500 : 20000);
  };
  const quoteBox = (q) => new Promise((resolve) => {
    const close = (ok) => { m.remove(); resolve(ok); };
    const m = h('div.pr-modal', { onclick: (e) => { if (e.target === m) close(false); } }, h('div', {}, [
      h('h3', { style: { marginTop: 0 } }, '开一台阿里云 GPU？'),
      h('dl', {}, [['机器', `${q.instance_type}（NVIDIA A10 24GB）抢占式`], ['可用区', q.zone], ['价格', `约 ${q.price} 元/小时（含云盘）`],
        ['准备时间', '首次约 5–8 分钟（开机 + 装 PyTorch）'], ['自动释放', `空闲 ${q.idle_min} 分钟，或满 ${q.cap} 元（约 ${q.hours} 小时）`],
        ['释放前', '训练出的权重自动拉回本机']].flatMap(([k, x]) => [h('dt', {}, k), h('dd', {}, x)])),
      h('p.muted', { style: { fontSize: '12.5px' } }, '抢占式价格随供需浮动，极少数情况会被回收；按实际使用时长计费。'),
      h('div.row', { style: { justifyContent: 'flex-end', gap: '8px' } }, [h('button.ghost', { onclick: () => close(false) }, '取消'), h('button.primary', { onclick: () => close(true) }, '开机')]),
    ]));
    document.body.append(m);
  });
  async function start() {
    try {
      if (kind === 'cloud') {
        const r = await api.post('/api/practice/runtime/start', { kind });
        if (r.quote && !(await quoteBox(r.quote))) return false;
        v = await api.post('/api/practice/runtime/start', { kind, confirm: true });
      } else v = await api.post('/api/practice/runtime/start', { kind });
      paint();
      poll();
      return true;
    } catch (e) { toast(e.message, true); return false; }
  }
  const ready = async () => {
    if (v?.status === 'ready') return;
    if (!['starting'].includes(v?.status) && !(await start())) throw new Error('没开运行环境');
    await new Promise((res, rej) => waiters.push((err) => (err ? rej(err) : res())));
  };
  poll();
  return { el: bar, ready, state: () => v };
}

// ---------- 课程首页 ----------

async function homePage(el, ctx) {
  const { h, api, ui, toast } = ctx;
  const d = await api.get('/api/practice/courses');
  const card = (c) => h('div.pr-card', { onclick: () => { location.hash = `#practice/${c.id}`; } }, [
    h('h3', {}, c.title), h('div.muted', {}, c.summary),
    h('div.meta', {}, [h('span.tag', {}, c.topic || '实践'), h('span.tag.line', {}, RT_NAME[c.runtime] || c.runtime), h('span', {}, `${c.done}/${c.lessons} 课`),
      c.minutes ? h('span', {}, `约 ${c.minutes} 分钟`) : null, c.mine ? h('span.tag.gray', {}, '生成的') : null]),
    c.done ? ui.progress((c.done / c.lessons) * 100) : null,
  ]);
  const topic = h('input', { placeholder: '想实践的主题，比如：RAG 检索增强、LoRA 微调、多 Agent 协作' });
  const repo = h('input', { placeholder: '围绕的 GitHub 仓库（可选）' });
  const rt = h('select', {}, [h('option', { value: 'local' }, '本机运行（不需要 GPU）'), h('option', { value: 'cloud' }, '阿里云 GPU（训练类）')]);
  el.append(
    ui.pageHead('实践', '讲解和代码交替，在页面里逐格运行、当场看到结果；每一步都能问 Claude。'),
    h('div.pr-cards', {}, d.courses.map(card)),
    ui.section('生成一门新实践课', 'Claude 按主题读资料、写讲解和可运行代码，写完出现在上面'),
    h('div.card', {}, [h('div.row', { style: { gap: '8px', flexWrap: 'wrap' } }, [topic, repo, rt,
      h('button.primary', { onclick: async () => {
        if (!topic.value.trim()) return toast('先写主题', true);
        try { await api.post('/api/practice/generate', { topic: topic.value.trim(), repo: repo.value.trim(), runtime: rt.value }); toast('已开始生成，约 10–20 分钟，完成后刷新这里'); topic.value = ''; repo.value = ''; } catch (e) { toast(e.message, true); }
      } }, '生成')])]),
  );
}

// ---------- 课程页 ----------

async function coursePage(el, ctx, cid) {
  const { h, api, ui, md } = ctx;
  const c = await api.get('/api/practice/courses/' + enc(cid));
  const first = c.lessons.find((x) => !c.done[x.id]) || c.lessons[0];
  el.append(
    ui.pageHead(c.title, c.summary, [h('button.primary', { onclick: () => { location.hash = `#practice/${cid}/${first.id}`; } }, c.done[first.id] ? '从头复习' : Object.keys(c.done).length ? '继续' : '开始')]),
    h('div.row', { style: { gap: '6px', flexWrap: 'wrap', margin: '0 0 12px' } }, [h('span.tag', {}, c.topic), h('span.tag.line', {}, RT_NAME[c.runtime]),
      c.repo ? h('a', { href: c.repo, target: '_blank', rel: 'noopener' }, c.repo.replace('https://github.com/', '')) : null,
      ...(c.know || []).map((k) => h('span.tag.gray', {}, k))]),
    c.runtime === 'cloud' ? h('div.card.flat', { style: { marginBottom: '12px' } }, md('这门课要用 GPU：第一次运行代码时会提示开一台**阿里云 A10**（抢占式约 3–4 元/小时），用完空闲 30 分钟自动释放。讲解部分不用开机也能看。')) : null,
    h('div.card', {}, h('div.list', {}, c.lessons.map((x) => h('a.item', { href: `#practice/${cid}/${x.id}`, style: { display: 'block', textDecoration: 'none', color: 'inherit' } }, [
      h('div.row', {}, [h('span.item-title.grow', {}, (c.done[x.id] ? '✓ ' : '') + x.title), x.gpu ? h('span.tag.line', {}, 'GPU') : null,
        h('span.muted', {}, `${x.cells} 格 · ${x.minutes} 分钟`)]),
      x.know.length ? h('div.muted', {}, x.know.join(' · ')) : null])))),
  );
}

// ---------- 一课 ----------

async function lessonPage(el, ctx, cid, lid) {
  const { h, api, md, toast } = ctx;
  const [c, L] = await Promise.all([api.get('/api/practice/courses/' + enc(cid)), api.get(`/api/practice/courses/${enc(cid)}/lessons/${enc(lid)}`)]);
  const kind = c.runtime || 'local';
  const rt = runtimeBar(ctx, kind, cid);
  const idx = c.lessons.findIndex((x) => x.id === lid);
  const toc = h('nav.pr-toc', {}, [h('div.hd', {}, c.title), ...c.lessons.map((x) => h('a' + (x.id === lid ? '.on' : '') + (c.done[x.id] ? '.done' : ''), { href: `#practice/${cid}/${x.id}` }, x.title))]);
  const main = h('div');
  el.append(h('div.pr-wrap', {}, [toc, main]));
  const cells = [];   // {n, ta, out, st, outputs}

  // 相关概念：查知识库 / 让 Claude 讲
  const know = (L.meta.know || '').split(',').map((x) => x.trim()).filter(Boolean);
  const kpop = h('div');
  let introWrap = null;
  const openKnow = async (k, btn) => {
    main.querySelectorAll('.pr-know button').forEach((b) => b.classList.toggle('on', b === btn && !b.classList.contains('on')));
    if (!btn.classList.contains('on')) { kpop.replaceChildren(); return; }
    kpop.replaceChildren(h('div.pr-kpop', {}, '查知识库…'));
    let rs = [];
    try { rs = await api.get(`/api/kb/search?q=${enc(k)}&limit=5`); } catch { /* 知识库没建好也能用 */ }
    kpop.replaceChildren(h('div.pr-kpop', {}, [
      h('div.row', { style: { gap: '8px', alignItems: 'center' } }, [h('b', {}, k), h('span.grow'),
        h('button.sm.primary', { onclick: () => introWrap?._ask(`用通俗的方式讲透「${k}」：它解决什么问题、怎么工作、常见误区，并结合这门课的代码举例。`) }, '让 Claude 讲透')]),
      rs.length ? h('div', {}, [h('div.muted', { style: { margin: '4px 0' } }, '知识库里相关的：'), ...rs.map((d) => h('a', { href: d.type === 'concept' ? '#kb/c/' + enc(d.title) : '#kb/doc/' + enc(d.path) }, `${d.title}${d.summary ? ' · ' + d.summary.slice(0, 60) : ''}`))])
        : h('div.muted', {}, '知识库里还没有这个概念，可以先让 Claude 讲，讨论会自动存进知识库。')]));
  };
  const introBody = h('div', {}, [h('h1', { style: { margin: '0 0 4px', fontSize: '24px' } }, L.title), L.intro ? md(L.intro) : null,
    know.length ? h('div.pr-know', {}, [h('span.muted', {}, '相关知识：'), ...know.map((k) => { const b = h('button', { onclick: () => openKnow(k, b) }, k); return b; })]) : null, kpop]);
  introWrap = annotate(ctx, introBody, { doc: `practice:${cid}:${lid}:intro`, title: `${c.title} · ${L.title}`, link: `#practice/${cid}/${lid}`,
    source: () => `课程：${c.title}\n本课：${L.title}\n${L.intro}`, compact: true });
  main.append(rt.el, introWrap);

  const stepText = (i) => {
    const s = L.steps[i];
    return [`课程：${c.title}`, `本课：${L.title}`, `这一步：${s.title}`, ...s.parts.map((p) => {
      if (p.type === 'md') return p.text;
      if (p.type === 'ask') return `思考题：${p.text}`;
      const cl = cells[p.n];
      return `代码格 [${p.n + 1}]：\n\`\`\`python\n${cl?.ta.value || p.code}\n\`\`\`\n${cl?.outputs.length ? '运行输出：\n' + outText(cl.outputs) : '（还没运行）'}`;
    })].join('\n\n');
  };

  const setSt = (cl, st, secs) => {
    const map = { queued: ['准备中…', 'run'], running: ['运行中', 'run'], done: ['✓ 完成', 'ok'], error: ['✗ 出错', 'err'], failed: ['✗ 失败', 'err'] };
    const [t, k] = map[st] || ['', ''];
    cl.st.className = 'st ' + k;
    cl.st.textContent = t + (secs ? ` · ${secs}s` : '');
    cl.stop.style.display = ['queued', 'running'].includes(st) ? '' : 'none';
    cl.fix.style.display = ['error', 'failed'].includes(st) ? '' : 'none';
  };
  const follow = async (cl, eid) => {
    let ver = -1;
    for (;;) {
      if (!cl.ta.isConnected) return;
      let r;
      try { r = await api.get(`/api/practice/exec/${eid}?ver=${ver}`); } catch (e) { setSt(cl, 'failed'); return toast(e.message, true); }
      if (!r.same) { cl.outputs = r.outputs; renderOutputs(ctx, cl.out, r.outputs); ver = r.ver; }
      setSt(cl, r.status, r.secs);
      if (!['queued', 'running'].includes(r.status)) {
        cl.ok = r.status === 'done';
        if (cl.ok && !c.done[lid] && cells.every((x) => x.ok)) refreshDone();
        return;
      }
      await new Promise((res) => setTimeout(res, r.status === 'running' ? 500 : 1200));
    }
  };
  const runCell = async (cl) => {
    setSt(cl, 'queued');
    try { await rt.ready(); } catch (e) { setSt(cl, 'failed'); cl.out.replaceChildren(h('pre.err', {}, e.message)); return; }
    try {
      const r = await api.post('/api/practice/run', { course: cid, lesson: lid, cell: cl.n, code: cl.ta.value, kind });
      follow(cl, r.id);
    } catch (e) { setSt(cl, 'failed'); toast(e.message, true); }
  };
  const refreshDone = async () => {
    const cc = await api.get('/api/practice/courses/' + enc(cid));
    if (cc.done[lid]) { c.done[lid] = cc.done[lid]; toc.querySelectorAll('a').forEach((a) => { if (a.getAttribute('href').endsWith('/' + lid)) a.classList.add('done'); }); toast('这一课完成了，已记进学习进度和复盘'); }
  };

  L.steps.forEach((s, i) => {
    const body = h('div.pr-step', {}, [h('h3', {}, s.title)]);
    let wrap = null;
    for (const p of s.parts) {
      if (p.type === 'md') body.append(md(p.text));
      else if (p.type === 'ask') body.append(h('div.pr-ask', {}, [h('b', {}, '思考'), h('span', {}, p.text),
        h('button.sm.ghost', { onclick: () => wrap._ask(`思考题：${p.text}\n我的想法：`) }, '和 Claude 对答案')]));
      else {
        const saved = L.cells[String(p.n)];
        const ta = h('textarea.pr-code', { spellcheck: 'false', rows: Math.min(28, (saved?.code || p.code).split('\n').length + 1) });
        ta.value = saved?.code || p.code;
        const out = h('div.pr-out');
        const st = h('span.st');
        const cl = { n: p.n, ta, out, st, outputs: saved?.outputs || [], ok: saved?.status === 'done' };
        cl.stop = h('button.sm.ghost', { style: { display: 'none' }, onclick: () => api.post('/api/practice/interrupt', { course: cid, kind }) }, '■ 中断');
        cl.fix = h('button.sm.ghost', { style: { display: 'none' }, onclick: () => wrap._ask('这一格运行出错了，帮我看看原因，并给出改好的代码。') }, '让 Claude 看报错');
        ta.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); runCell(cl); }
          if (e.key === 'Tab') { e.preventDefault(); const a = ta.selectionStart; ta.setRangeText('    ', a, ta.selectionEnd, 'end'); }
        });
        body.append(h('div.pr-cell', {}, [
          h('div.bar', {}, [h('button.sm.primary', { title: 'Shift+Enter', onclick: () => runCell(cl) }, '▶ 运行'), cl.stop, h('span', {}, `[${p.n + 1}]`),
            p.gpu ? h('span.tag.line', {}, 'GPU') : null, p.long ? h('span.tag.line', {}, '要跑几分钟') : null, st, h('span.grow'), cl.fix,
            h('button.sm.ghost', { title: '恢复成课程里的原始代码', onclick: () => { ta.value = p.code; } }, '还原')]),
          ta, out]));
        if (saved) { renderOutputs(ctx, out, saved.outputs); setSt(cl, saved.status, saved.secs); }
        if (L.live[String(p.n)]) follow(cl, L.live[String(p.n)]);
        cells[p.n] = cl;
      }
    }
    body.append(h('div.row', { style: { justifyContent: 'flex-end' } }, h('button.sm.ghost', { onclick: () => wrap._ask('') }, [ctx.ui.icon('spark'), '问 Claude 这一步'])));
    wrap = annotate(ctx, body, { doc: `practice:${cid}:${lid}:${i}`, title: `${c.title} · ${L.title} · ${s.title}`, link: `#practice/${cid}/${lid}`,
      source: () => stepText(i), compact: true });
    main.append(wrap);
  });

  const prev = c.lessons[idx - 1], next = c.lessons[idx + 1];
  const go = (hash) => () => { location.hash = hash; };
  main.append(h('div.pr-nav', {}, [prev ? h('button.ghost', { onclick: go(`#practice/${cid}/${prev.id}`) }, '← ' + prev.title) : h('span'),
    next ? h('button.primary', { onclick: go(`#practice/${cid}/${next.id}`) }, next.title + ' →') : h('button.ghost', { onclick: go(`#practice/${cid}`) }, '回到课程')]));
}
