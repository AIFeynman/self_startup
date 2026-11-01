// 调研：新调研（大输入框，回车即开跑）/ 文档库 / 产品体验。路由 #research/<tab>，详情 #research/r/<id>，文档 #research/docs/<id>。
import { annotate } from './_annotate.js';
const STATUS = {
  queued: ['排队中', 'gray'], running: ['调研中', 'warn'], waiting: ['等待 GrokBot', 'warn'], timeout: ['等待超时', 'warn'],
  awaiting_paste: ['待粘贴', ''], awaiting_login: ['等待登录', 'warn'], done: ['完成', 'ok'], failed: ['失败', 'err'],
};
const ENGINE_NAMES = { claude: 'Claude Code', codex: 'Codex', grokbot: 'GrokBot', muse: 'Muse' };
const ENGINE_PILLS = { claude: 'Claude', codex: 'Codex', grokbot: 'GrokBot·X', muse: 'Muse·手动' };
const ENGINE_DESC = { claude: '联网检索网页与文档', codex: '联网检索网页与文档', grokbot: 'X/Twitter 上的讨论', muse: '自动打开 Muse 网页版提问并取回答（首次需登录）' };
const ENGINE_ICON = { claude: 'robot', codex: 'bolt', grokbot: 'chat', muse: 'edit' };
const DEFAULT_ANGLES = ['技术原理', '关键玩家与竞品', '最新进展'];
const PREFILL_KEY = 'research-prefill';
const PREFS_KEY = 'rs-prefs';
const go = (path) => { location.hash = '#research' + (path ? '/' + path : ''); };
const tagsOf = (s) => s.split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean);
const fmt = (t) => (t || '').slice(5, 16).replace('T', ' ');
const loadPrefs = () => { try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}'); } catch { return {}; } };
const savePrefs = (p) => { try { localStorage.setItem(PREFS_KEY, JSON.stringify({ ...loadPrefs(), ...p })); } catch { /* ignore */ } };

const CSS = `
.rs-opts { display: flex; flex-direction: column; gap: 8px; margin: -2px 4px 6px; }
.rs-opts .lbl { font-size: 12px; color: var(--muted); width: 34px; flex: none; }
.rs-pill { padding: 3px 12px; font-size: 13px; border-color: var(--line-2); background: var(--panel); color: var(--text); }
.rs-pill svg { width: 14px; height: 14px; display: none; }
.rs-pill.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.rs-pill.on svg { display: inline; }
.rs-pill.off { opacity: .55; }
.rs-pill.add { border-style: dashed; color: var(--muted); background: transparent; }
.rs-pill.add svg { display: inline; }
.rs-pill-input { width: 140px; padding: 3px 10px; font-size: 13px; border-radius: 999px; }
.rs-ctx { margin: 2px 0 8px; }
.rs-note { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--accent); background: var(--accent-soft); border-radius: 999px; padding: 2px 6px 2px 12px; margin-bottom: 4px; }
.rs-note button { padding: 0 4px; border: none; background: none; color: inherit; }
.rs-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.rs-card { cursor: pointer; margin: 0; display: flex; flex-direction: column; gap: 6px; transition: border-color .12s, transform .12s; }
.rs-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.rs-card .t { font: 700 17px/1.4 var(--serif); }
.rs-dots { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }
.rs-dot { display: inline-flex; align-items: center; gap: 5px; }
.rs-dot i { width: 8px; height: 8px; border-radius: 50%; background: var(--line-2); flex: none; }
.rs-dot.done i { background: var(--ok); } .rs-dot.failed i { background: var(--err); }
.rs-dot.running i, .rs-dot.waiting i, .rs-dot.queued i { background: var(--warn); animation: rs-pulse 1.2s ease-in-out infinite; }
.rs-dot.awaiting_paste i, .rs-dot.timeout i { background: transparent; border: 1.5px solid var(--accent); }
@keyframes rs-pulse { 50% { opacity: .3; } }
.rs-search { display: flex; align-items: center; gap: 8px; background: var(--panel); border: 1px solid var(--line-2); border-radius: 999px; padding: 2px 6px 2px 14px; }
.rs-search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
.rs-search input { border: none; box-shadow: none !important; padding: 6px 2px; background: transparent; }
.rs-search svg { color: var(--muted); }
.rs-head-tabs { margin: 0; }
.rs-back { margin: -8px 0 10px -6px; }
.rs-hero h1 { font-size: 32px; margin: 2px 0 8px; line-height: 1.3; }
.rs-engines { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-bottom: 14px; }
.rs-engines .card { margin: 0; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.rs-engines .card.wide { grid-column: 1 / -1; }
.rs-engines .eh { display: flex; align-items: center; gap: 8px; }
.rs-engines .eh .ic { width: 30px; height: 30px; border-radius: 9px; background: var(--accent-soft); color: var(--accent); display: grid; place-items: center; }
.rs-engines .eh b { flex: 1; font-size: 15px; }
.rs-engines pre { margin: 0; max-height: 110px; overflow: auto; font-size: 11px; }
.rs-paste { background: var(--focus); border: 1px dashed var(--accent); border-radius: var(--radius-sm); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.rs-paste textarea { background: var(--panel); }
.rs-synth { padding: 24px 28px; }
.rs-read { max-width: 760px; margin: 0 auto; font-size: 15px; line-height: 1.85; }
.rs-read.md h1 { font-size: 24px; } .rs-read.md h2 { font-size: 20px; margin-top: 1.4em; } .rs-read.md h3 { font-size: 16px; }
.rs-read.md ul, .rs-read.md ol { padding-left: 1.4em; } .rs-read.md li { margin: .2em 0; }
.rs-read.md code { background: var(--bg-2); padding: 1px 5px; border-radius: 5px; }
.rs-read.md pre code { background: none; padding: 0; }
.rs-result summary { list-style: none; display: flex; align-items: center; gap: 8px; color: var(--text); font: 700 16px var(--serif); }
.rs-result summary::-webkit-details-marker { display: none; }
.rs-result summary::after { content: '展开'; margin-left: auto; font: 400 12px var(--font); color: var(--muted); }
.rs-result[open] summary::after { content: '收起'; }
.rs-result[open] summary { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.rs-reader { max-width: 820px; margin: 0 auto; padding: 30px 40px 40px; }
.rs-reader h1.title { font-size: 30px; margin: 4px 0 8px; line-height: 1.3; }
.rs-row { cursor: pointer; border-radius: var(--radius-sm); padding: 12px 10px !important; }
.rs-row:hover { background: var(--bg); }
.rs-stars { color: var(--accent); letter-spacing: 1px; font-size: 14px; } .rs-stars s { color: var(--line-2); text-decoration: none; }
.rs-prod { margin: 0; display: flex; flex-direction: column; gap: 8px; }
.rs-prod .name { font: 700 18px var(--serif); flex: 1; min-width: 0; }
.rs-prod .pc { display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; font-size: 13px; align-items: baseline; }
.rs-prod .acts { margin-top: auto; padding-top: 6px; }
.rs-quick { display: flex; gap: 8px; align-items: center; }
.rs-quick .rs-search { flex: 1; }
`;

export default {
  async render(el, ctx) {
    const { h, ui } = ctx;
    if (!document.getElementById('rs-style')) document.head.append(h('style#rs-style', {}, CSS));
    const [tab = 'new', arg] = ctx.sub;
    const tabs = [['new', '新调研'], ['docs', '文档库'], ['products', '产品体验']];
    const cur = tab === 'r' ? 'new' : tab;
    const tabBar = h('div.tabs.rs-head-tabs', {}, tabs.map(([id, name]) =>
      h('button' + (cur === id ? '.active' : ''), { onclick: () => go(id) }, name)));
    const subs = { new: '输入主题回车即开跑：多个引擎并行检索，再综合成一份有来源的文档', docs: '所有调研与手写笔记，存为本地 markdown', products: '你自己用过的产品，一句话就能记' };
    if (tab !== 'r') el.append(ui.pageHead('调研', subs[cur] || '', [tabBar]));
    const body = h('div');
    el.append(body);
    if (tab === 'r') return detail(body, ctx, +arg);
    if (tab === 'docs') return docs(body, ctx, arg ? +arg : null);
    if (tab === 'products') return products(body, ctx);
    return newResearch(body, ctx);
  },
};

// 被备选引擎代跑的结果：原引擎名后标明，避免误以为两个引擎都跑通了
const subTag = (h, x) => (x.used_engine && x.used_engine !== x.engine
  ? h('span.tag.warn', { title: `${ENGINE_NAMES[x.engine] || x.engine} 没跑通，平台自动回退` }, `由 ${ENGINE_NAMES[x.used_engine] || x.used_engine} 代跑`) : null);
const statusTag = (h, s) => { const [t, c] = STATUS[s] || [s || '—', 'gray']; return h('span.tag' + (c ? '.' + c : ''), {}, t); };
const dots = (h, progress) => h('div.rs-dots', {}, progress.map((x) =>
  h('span.rs-dot.' + x.status, { title: `${ENGINE_NAMES[x.engine] || x.engine}：${(STATUS[x.status] || [x.status])[0]}` }, [h('i'), ENGINE_PILLS[x.engine] || x.engine])));
const stars = (h, n) => h('span.rs-stars', { title: n ? `${n}/5` : '未评分' }, n ? ['★'.repeat(n), h('s', {}, '★'.repeat(5 - n))] : h('s', {}, '☆☆☆☆☆'));

function searchBox(h, ui, placeholder, onInput) {
  const input = h('input', { placeholder });
  input.addEventListener('input', debounce(() => onInput(input.value)));
  const box = h('label.rs-search', {}, [ui.icon('search'), input]);
  box.input = input;
  return box;
}

// 可切换的 pill；onToggle(on)
function pill(h, ui, label, on, onToggle, extra = '') {
  const b = h('button.rs-pill' + (on ? '.on' : '') + extra, { type: 'button' }, [ui.icon('check'), label]);
  b.addEventListener('click', () => { b.classList.toggle('on'); onToggle(b.classList.contains('on')); });
  return b;
}

// ---------- 新调研 ----------
async function newResearch(el, ctx) {
  const { api, h, toast, ui, ask } = ctx;
  const presets = await api.get('/api/research/presets');
  let pre = {};
  try { pre = JSON.parse(sessionStorage.getItem(PREFILL_KEY) || '{}'); sessionStorage.removeItem(PREFILL_KEY); } catch { /* ignore */ }
  const prefs = loadPrefs();
  const avail = Object.fromEntries(presets.engines.map((e) => [e.id, e.available]));
  const customs = [...new Set([...(prefs.customAngles || []), ...(pre.angles || []).filter((a) => !presets.angles.includes(a))])];
  const angles = new Set(pre.angles || prefs.angles || DEFAULT_ANGLES);
  const engines = new Set((prefs.engines || ['claude']).filter((e) => e in ENGINE_PILLS));
  if (!engines.size) engines.add('claude');
  let productId = pre.product_id || null;

  // 角度
  const angleRow = h('div.row');
  const addAngle = (a, on) => {
    angleRow.insertBefore(pill(h, ui, a, on, (v) => (v ? angles.add(a) : angles.delete(a))), addBtn);
  };
  const addBtn = h('button.rs-pill.add', { type: 'button', onclick: () => {
    const inp = h('input.rs-pill-input', { placeholder: '新角度，回车' });
    let closed = false;
    const done = () => {
      if (closed) return;
      closed = true;
      for (const a of tagsOf(inp.value)) {
        if (![...presets.angles, ...customs].includes(a)) { customs.push(a); addAngle(a, true); savePrefs({ customAngles: customs }); }
        angles.add(a);
        angleRow.querySelectorAll('.rs-pill:not(.add)').forEach((b) => { if (b.textContent === a) b.classList.add('on'); });
      }
      inp.remove(); addBtn.style.display = '';
    };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); done(); } if (e.key === 'Escape') { inp.value = ''; done(); } });
    inp.addEventListener('blur', done);
    addBtn.style.display = 'none';
    angleRow.insertBefore(inp, addBtn);
    inp.focus();
  } }, [ui.icon('plus'), '自定义']);
  angleRow.append(addBtn);
  [...presets.angles, ...customs].forEach((a) => addAngle(a, angles.has(a)));

  // 引擎
  const engineRow = h('div.row', {}, presets.engines.map((e) => {
    const b = pill(h, ui, ENGINE_PILLS[e.id] || e.name, engines.has(e.id), (v) => (v ? engines.add(e.id) : engines.delete(e.id)), e.available ? '' : '.off');
    b.title = (ENGINE_DESC[e.id] || '') + (e.available ? '' : '（本机未检测到）');
    return b;
  }));

  // 补充背景
  const context = h('textarea.rs-ctx', { rows: 3, placeholder: '背景 / 已有认知 / 想重点弄清的问题' }, [pre.context || '']);
  const ctxBox = h('div', { style: { display: pre.context ? '' : 'none' } }, context);
  const ctxBtn = h('button.ghost.sm', { type: 'button', onclick: () => { const show = ctxBox.style.display === 'none'; ctxBox.style.display = show ? '' : 'none'; ctxBtn.lastChild.textContent = show ? '收起背景' : '补充背景'; if (show) context.focus(); } },
    [ui.icon('plus'), h('span', {}, pre.context ? '收起背景' : '补充背景')]);
  const note = productId ? h('div.rs-note', {}, [ui.icon('box'), `来自产品体验：${pre.topic}`, h('button', { title: '取消关联', onclick: () => { productId = null; note.remove(); } }, ui.icon('x'))]) : null;

  const opts = h('div.rs-opts', {}, [
    h('div.row', {}, [h('span.lbl', {}, '角度'), h('div.grow', {}, angleRow)]),
    h('div.row', {}, [h('span.lbl', {}, '引擎'), h('div.grow', {}, h('div.row', {}, [engineRow, h('span.grow'), ctxBtn]))]),
    ctxBox,
  ]);
  const productHelp = h('div.rs-opts', { style: { display: 'none' } }, [
    h('div.muted', {}, '格式：产品名 评分 体验 #标签 —— 也认 ★★★★、4/5、链接、「优：… 缺：…」。回车立即保存。'),
    ui.chips([
      { label: 'Cursor 4星 补全快但贵 #AI编程', onClick: () => comp.setValue('Cursor 4星 补全快但贵 #AI编程') },
      { label: 'Raycast ★★★★★ 启动器 优：快 缺：插件少 #效率', onClick: () => comp.setValue('Raycast ★★★★★ 启动器 优：快 缺：插件少 #效率') },
    ], { left: true }),
  ]);

  const start = async (topic) => {
    if (!engines.size) { toast('至少选一个引擎', true); return false; }
    const angleList = [...angles];
    savePrefs({ angles: angleList, engines: [...engines] });
    try {
      const r = await api.post('/api/research', { topic, angles: angleList, engines: [...engines], context: context.value, product_id: productId });
      go('r/' + r.id);
    } catch (e) { toast(e.message, true); return false; }
  };
  const quickProduct = async (text) => {
    try {
      const p = await api.post('/api/research/products/quick', { text });
      toast(`已记录：${p.name}${p.rating ? ' ' + '★'.repeat(p.rating) : ''}${p.tags.length ? ' · #' + p.tags.join(' #') : ''}`);
    } catch (e) { toast(e.message, true); return false; }
  };
  const hints = { research: 'Enter 开始 · Shift+Enter 换行', product: 'Enter 保存产品体验', ask: 'Enter 发给调研 Agent' };
  const comp = ui.composer({
    placeholder: '想调研什么？如：AI 编程助手的商业模式', autofocus: true, value: pre.topic || '',
    modes: [{ id: 'research', label: '调研', placeholder: '想调研什么？如：AI 编程助手的商业模式' },
      { id: 'product', label: '记产品体验', placeholder: 'Cursor 4星 补全快但贵 #AI编程' },
      { id: 'ask', label: '问 Agent', placeholder: '比如：把我最近几次调研的结论对比一下' }],
    hint: hints.research,
    onSubmit: (t, mode) => (mode === 'product' ? quickProduct(t) : mode === 'ask' ? ask(t) : start(t)),
  });
  comp.querySelector('.modes').addEventListener('click', () => {
    opts.style.display = comp.mode === 'research' ? '' : 'none';
    productHelp.style.display = comp.mode === 'product' ? '' : 'none';
    comp.setHint(hints[comp.mode]);
  });

  // 最近调研
  const cards = h('div.rs-cards');
  let q = '';
  const card = (r) => h('div.card.rs-card', { onclick: () => go('r/' + r.id) }, [
    h('div.row', {}, [h('span.card-label', { style: { margin: 0 } }, `#${r.id} · ${fmt(r.created_at)}`), h('span.grow'),
      r.synth_status === 'done' ? h('span.tag.line', {}, '已综合') : null, statusTag(h, r.status)]),
    h('div.t.clamp2', {}, r.topic),
    h('div.muted.clamp2', {}, r.angles.join(' · ') || '整体概况'),
    dots(h, r.progress?.length ? r.progress : r.engines.map((e) => ({ engine: e, status: r.status }))),
  ]);
  let timer;
  const load = async () => {
    const rs = await api.get('/api/research?limit=30&q=' + encodeURIComponent(q));
    cards.replaceChildren(...(rs.length ? rs.map(card) : [h('div', { style: { gridColumn: '1/-1' } }, ui.empty(q ? '没找到' : '还没有调研', q ? '换个关键词' : '在上面输入一个主题，回车就开始'))]));
    clearTimeout(timer);
    if (rs.some((r) => ['running', 'queued'].includes(r.status) || r.synth_status === 'running')) timer = setTimeout(() => { if (cards.isConnected) load(); }, 6000);
  };
  const search = searchBox(h, ui, '搜索历史调研…', (v) => { q = v; load(); });
  search.style.width = '240px';

  el.append(...[note, comp, opts, productHelp].filter(Boolean),
    h('div.row', { style: { margin: '28px 0 12px' } }, [h('div.section-title.grow', { style: { margin: 0 } }, '最近调研'), search]),
    cards);
  await load();
}

// ---------- 调研详情 ----------
async function detail(el, ctx, id) {
  const { api, h, md, toast, openChat, ui } = ctx;
  let r;
  try { r = await api.get(`/api/research/${id}`); } catch (e) { el.append(h('pre.error', {}, e.message)); return; }
  const rerender = () => { if (el.isConnected) { el.innerHTML = ''; detail(el, ctx, id); } };

  const doneCount = r.results.filter((x) => x.status === 'done').length;
  const synthRunning = r.synth_status === 'running';
  const synthesize = async () => { try { await api.post(`/api/research/${id}/synthesize`); toast('综合任务已提交'); rerender(); } catch (e) { toast(e.message, true); } };
  const synthBtn = (cls = 'primary') => h('button.' + cls, { disabled: !doneCount || synthRunning, onclick: synthesize },
    [ui.icon('spark'), synthRunning ? '综合中…' : (r.synthesis ? '重新综合' : '综合')]);

  el.append(
    h('button.ghost.rs-back', { onclick: () => go('new') }, [ui.icon('arrow', ''), '调研']),
    h('div.rs-hero', {}, [
      h('div.row', {}, [h('span.card-label', { style: { margin: 0 } }, `调研 #${r.id} · ${r.created_at.slice(0, 16).replace('T', ' ')}`), statusTag(h, r.status)]),
      h('h1', {}, r.topic),
      h('div.row', { style: { marginBottom: '12px' } }, r.angles.length ? r.angles.map((a) => h('span.tag', {}, a)) : h('span.tag.gray', {}, '整体概况')),
      r.context ? h('details.card.flat', { style: { padding: '10px 16px' } }, [h('summary', {}, '背景'), h('div', { style: { whiteSpace: 'pre-wrap', marginTop: '6px' } }, r.context)]) : null,
      h('div.row', { style: { marginBottom: '18px' } }, [
        synthBtn(),
        h('button', { onclick: () => openChat({ module: 'research', ref: `research:${id}`, title: '调研：' + r.topic }) }, [ui.icon('chat'), '和 Agent 讨论']),
        r.doc_id ? h('button', { onclick: () => go('docs/' + r.doc_id) }, [ui.icon('doc'), '阅读文档']) : null,
        h('span.grow'),
        h('span.muted', { title: r.doc_path, style: { maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, r.doc_path),
        h('button.ghost', { onclick: async () => { if (confirm('删除这条调研及其文档？')) { await api.del(`/api/research/${id}`); go('new'); } } }, [ui.icon('trash'), '删除']),
      ]),
    ]),
  );
  // 返回按钮的箭头朝左
  el.querySelector('.rs-back svg').style.transform = 'rotate(180deg)';

  const engineGrid = h('div.rs-engines');
  el.append(engineGrid);
  for (const x of r.results) engineGrid.append(engineCard(x, ctx, rerender, el));

  // 综合
  if (r.synth_status || doneCount) {
    const synth = h('div.card.hl.rs-synth', {}, [
      h('div.row', { style: { marginBottom: '6px' } }, [h('span.card-label', { style: { margin: 0 } }, [ui.icon('spark'), ' 综合结论']), h('span.grow'),
        r.synth_status ? statusTag(h, r.synth_status) : null]),
      r.synthesis ? annotate(ctx, md(r.synthesis), { doc: `research:${r.id}:synth`, title: `${r.topic} · 综合结论`, link: `#research/r/${r.id}`, source: r.synthesis }) : h('div.empty', { style: { padding: '18px 0' } }, [
        h('div.serif', {}, synthRunning ? '正在合并各引擎结果' : r.synth_status === 'failed' ? '综合失败，可重试' : `${doneCount} 个引擎已完成`),
        synthRunning ? h('div.dots', {}, '稍等') : h('div', { style: { marginTop: '10px' } }, synthBtn()),
      ]),
    ]);
    synth.querySelector('.md')?.classList.add('rs-read');
    el.append(synth);
    if (synthRunning && r.synth_job_id) watchJob(api, r.synth_job_id, el, rerender);
  }

  // 各引擎原文
  const done = r.results.filter((x) => x.status === 'done' && x.content);
  if (done.length) {
    el.append(ui.section('各引擎原文', `${done.length} 份`));
    for (const x of done) {
      const body = md(x.content); body.classList.add('rs-read');
      const read = annotate(ctx, body, { doc: `research:${r.id}:r${x.id}`, title: `${r.topic} · ${ENGINE_NAMES[x.engine] || x.engine}`, link: `#research/r/${r.id}`, source: x.content });
      el.append(h('details.card.rs-result', { id: 'rs-res-' + x.id, open: !r.synthesis && done.length === 1 },
        [h('summary', {}, [ui.icon(ENGINE_ICON[x.engine] || 'robot'), ENGINE_NAMES[x.engine] || x.engine, subTag(h, x), h('span.muted', { style: { fontFamily: 'var(--font)', fontWeight: 400 } }, fmt(x.finished_at))]), read]));
    }
  }
}

function engineCard(x, ctx, rerender, root) {
  const { api, h, toast, ui } = ctx;
  const act = async (path, body) => { try { await api.post(`/api/research/results/${x.id}/${path}`, body); rerender(); } catch (e) { toast(e.message, true); } };
  const card = h('div.card' + (x.status === 'awaiting_paste' ? '.wide' : ''));
  card.append(h('div.eh', {}, [h('span.ic', {}, ui.icon(ENGINE_ICON[x.engine] || 'robot')), h('b', {}, ENGINE_NAMES[x.engine] || x.engine), subTag(h, x), statusTag(h, x.status)]));
  const logEl = h('pre.muted', { style: { display: 'none' } });

  if (x.status === 'done') {
    card.append(h('div.row', {}, [h('span.muted.grow', {}, `${fmt(x.finished_at)} 完成 · ${(x.content || '').length} 字`),
      h('button.sm', { onclick: () => { const d = document.getElementById('rs-res-' + x.id); if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'start' }); } } }, '看原文')]));
  } else if (x.status === 'awaiting_paste') {
    const ta = h('textarea', { rows: 7, placeholder: '把 Muse 的回答粘贴到这里，然后点「保存回答」' });
    card.append(h('div.rs-paste', {}, [
      h('div.muted', {}, x.error),
      h('div.row', {}, [
        h('button.sm', { onclick: async () => { await navigator.clipboard.writeText(x.brief); toast('已复制提问'); } }, [ui.icon('doc'), '复制提问']),
        h('button.sm', { onclick: () => act('muse_auto') }, [ui.icon('bolt'), '自动提问']),
        h('button.sm', { onclick: () => act('muse') }, [ui.icon('refresh'), '重新复制并打开 Muse']),
        h('details', { style: { flex: '1 1 100%' } }, [h('summary', {}, '查看提问 brief'), h('pre', { style: { maxHeight: '200px' } }, x.brief)]),
      ]),
      ta,
      h('div', {}, h('button.primary', { onclick: () => (ta.value.trim() ? act('paste', { content: ta.value }) : toast('内容为空', true)) }, [ui.icon('check'), '保存回答'])),
    ]));
  } else if (x.status === 'failed') {
    card.append(h('pre.error', {}, x.error || '失败'),
      h('div', {}, h('button.sm', { onclick: () => { if (x.engine !== 'grokbot' || confirm('将向 GrokBot 发送一个新请求，确定？')) act('retry'); } }, [ui.icon('refresh'), '重试'])));
  } else if (x.status === 'timeout') {
    card.append(h('div.muted', {}, x.error), h('div', {}, h('button.sm', { onclick: () => act('resume') }, [ui.icon('clock'), '继续等待（不重发）'])));
    if (x.engine === 'grokbot') card.append(grokPaste(h, toast, ui, act));
  } else {
    card.append(h('div.muted.dots', {}, x.engine === 'grokbot' ? (x.request_id ? '已发送，等待 GrokBot 回复' : '检查配置并发送') : x.engine === 'muse' ? (x.error || 'Muse 自动提问中') : ENGINE_DESC[x.engine] || '后台 Agent 调研中'), logEl);
    if (x.engine === 'grokbot' && x.request_id) card.append(grokPaste(h, toast, ui, act));
    if (x.job_id) watchJob(api, x.job_id, root, rerender, logEl);
    else if (x.engine === 'grokbot' || x.engine === 'muse') pollResult(api, x, root, rerender);
  }
  return card;
}

// Grok Bot 回答了但没在本机执行 reply 回传时，手动把聊天里的回答粘贴回来
function grokPaste(h, toast, ui, act) {
  const ta = h('textarea', { rows: 6, placeholder: '把 Grok Bot 聊天里的回答粘贴到这里' });
  return h('details.rs-paste', {}, [
    h('summary', {}, 'Grok Bot 已经回答了但这里没收到？'),
    h('div.muted', {}, '回答要靠 Grok Bot 在本机执行 reply 命令才能回传；它没执行（或在等你批准本机执行）时，可以直接粘贴。'),
    ta,
    h('div', {}, h('button.primary', { onclick: () => (ta.value.trim() ? act('paste', { content: ta.value }) : toast('内容为空', true)) }, [ui.icon('check'), '保存回答'])),
  ]);
}

// 轮询 job（Claude/Codex/综合），结束后重绘；离开页面即停止
function watchJob(api, jobId, root, rerender, logEl) {
  api.waitJob(jobId, (j) => {
    if (!root.isConnected) throw new Error('detached');
    if (logEl && j.log) { logEl.style.display = ''; logEl.textContent = j.log.split('\n').slice(-6).join('\n'); }
  }, 3000).then(() => setTimeout(rerender, 800)).catch(() => {});
}

// 轮询 GrokBot 结果
function pollResult(api, x, root, rerender) {
  const t = setInterval(async () => {
    if (!root.isConnected) return clearInterval(t);
    const y = await api.get(`/api/research/results/${x.id}`).catch(() => null);
    if (y && (y.status !== x.status || y.request_id !== x.request_id)) { clearInterval(t); rerender(); }
  }, 5000);
}

// ---------- 文档库 ----------
async function docs(el, ctx, openId) {
  const { api, h, md, toast, field, ui } = ctx;
  let q = '', tag = '';
  const since = h('input', { type: 'date', style: { width: '140px', borderRadius: '999px', padding: '5px 10px' } });
  const until = h('input', { type: 'date', style: { width: '140px', borderRadius: '999px', padding: '5px 10px' } });
  const list = h('div.list');
  const listBox = h('div');
  const view = h('div');
  const tags = await api.get('/api/research/docs/tags');

  const load = async () => {
    const p = new URLSearchParams({ q, tag, since: since.value, until: until.value });
    const ds = await api.get('/api/research/docs?' + p);
    count.textContent = `${ds.length} 篇`;
    list.replaceChildren(...(ds.length ? ds.map((d) => h('div.item.rs-row', { onclick: () => go('docs/' + d.id) }, [
      h('div.row', {}, [h('span', { style: { color: 'var(--accent)' } }, ui.icon(d.research_id ? 'research' : 'edit')), h('span.item-title.grow', {}, d.title),
        h('span.muted', {}, fmt(d.updated_at))]),
      h('div.row', { style: { paddingLeft: '26px', marginTop: '2px' } }, [h('span.muted', {}, d.research_id ? `调研 #${d.research_id}` : '手写'), ...d.tags.slice(0, 6).map((t) => h('span.tag', {}, t))]),
    ])) : [ui.empty('没有文档', q || tag ? '换个条件试试' : '完成一次调研或新建一篇笔记')]));
  };

  const back = () => { view.replaceChildren(); listBox.style.display = ''; if (openId) { openId = null; history.replaceState(null, '', '#research/docs'); } };
  const show = async (id) => {
    let d;
    try { d = await api.get(`/api/research/docs/${id}`); } catch (e) { toast(e.message, true); return back(); }
    const body = md(d.content); body.classList.add('rs-read');
    listBox.style.display = 'none';
    view.replaceChildren(
      h('button.ghost.rs-back', { onclick: back }, [ui.icon('arrow'), '文档库']),
      h('div.card.rs-reader', {}, [
        h('div.rs-read', {}, [
          h('div.row', {}, [h('span.card-label', { style: { margin: 0 } }, d.research_id ? `调研 #${d.research_id}` : '手写笔记'), h('span.muted', {}, fmt(d.updated_at)), h('span.grow'),
            d.research_id ? h('button.sm', { onclick: () => go('r/' + d.research_id) }, '打开调研') : h('button.sm', { onclick: () => editor(d) }, [ui.icon('edit'), '编辑']),
            h('button.sm', { onclick: async () => { await navigator.clipboard.writeText(d.content); toast('已复制 markdown'); } }, '复制'),
            h('button.icon', { title: '删除', onclick: async () => {
              if (!confirm(d.research_id ? '删除文档会同时删除这条调研记录，确定？' : '删除这篇文档？')) return;
              await api.del(`/api/research/docs/${id}`); back(); load();
            } }, ui.icon('trash'))]),
          h('h1.title', {}, d.title),
          h('div.row', { style: { marginBottom: '6px' } }, [...d.tags.map((t) => h('span.tag', {}, t)), h('span.muted', { style: { fontSize: '12px' } }, d.path)]),
          h('hr', { style: { border: 'none', borderTop: '1px solid var(--line)', margin: '14px 0' } }),
        ]),
        annotate(ctx, body, { doc: `research_doc:${d.id}`, title: d.title, link: `#research/docs/${d.id}`, source: d.content }),
      ]));
    view.querySelector('.rs-back svg').style.transform = 'rotate(180deg)';
    document.getElementById('page')?.scrollTo({ top: 0 });
  };

  const editor = (d = null) => {
    const title = h('input', { value: d?.title || '', placeholder: '标题' });
    const tg = h('input', { value: (d?.tags || []).join('，'), placeholder: '标签，逗号分隔' });
    const content = h('textarea.mono', { rows: 18, placeholder: '粘贴或撰写 markdown' }, [d?.content || '']);
    listBox.style.display = 'none';
    view.replaceChildren(h('div.card.rs-reader', {}, h('div.rs-read', {}, [h('h1.title', {}, d ? '编辑文档' : '新建文档'),
      field('标题', title), field('标签', tg), field('正文（markdown）', content),
      h('div.row', {}, [
        h('button.primary', { onclick: async () => {
          const b = { title: title.value, content: content.value, tags: tagsOf(tg.value) };
          try { const r = d ? await api.put(`/api/research/docs/${d.id}`, b) : await api.post('/api/research/docs', b); await load(); show(r.id); } catch (e) { toast(e.message, true); }
        } }, [ui.icon('check'), '保存']),
        h('button.ghost', { onclick: () => (d ? show(d.id) : back()) }, '取消')])])));
    title.focus();
  };

  const count = h('span.muted');
  const tagPills = h('div.row', { style: { margin: '10px 0 2px' } }, tags.slice(0, 16).map((t) => {
    const b = h('button.rs-pill', { type: 'button' }, [ui.icon('check'), t]);
    b.addEventListener('click', () => { const on = !b.classList.contains('on'); tagPills.querySelectorAll('.rs-pill').forEach((x) => x.classList.remove('on')); b.classList.toggle('on', on); tag = on ? t : ''; load(); });
    return b;
  }));
  const reload = debounce(load);
  [since, until].forEach((x) => x.addEventListener('input', reload));
  const sb = searchBox(h, ui, '搜索标题和正文…', (v) => { q = v; load(); });
  sb.style.flex = '1';
  listBox.append(
    h('div.row', {}, [sb, since, h('span.muted', {}, '至'), until, h('button.primary', { onclick: () => editor() }, [ui.icon('plus'), '新建文档'])]),
    tags.length ? tagPills : null,
    h('div.row', { style: { margin: '18px 0 8px' } }, [h('div.section-title.grow', { style: { margin: 0 } }, '全部文档'), count]),
    h('div.card', {}, list));
  el.append(listBox, view);
  await load();
  if (openId) show(openId);
}

// ---------- 产品体验 ----------
async function products(el, ctx) {
  const { api, h, md, toast, field, ui } = ctx;
  const formBox = h('div');
  let q = '';
  const list = h('div.grid');

  const form = (p = null) => {
    const f = {
      name: h('input', { value: p?.name || '', placeholder: '产品名' }),
      url: h('input', { value: p?.url || '', placeholder: 'https://' }),
      category: h('input', { value: p?.category || '', placeholder: '如：AI 编程 / 笔记 / 硬件' }),
      rating: h('select', {}, [0, 1, 2, 3, 4, 5].map((n) => h('option', { value: n, selected: (p?.rating || 0) === n }, n ? '★'.repeat(n) : '未评分'))),
      used_at: h('input', { type: 'date', value: p?.used_at || '' }),
      tags: h('input', { value: (p?.tags || []).join('，'), placeholder: '逗号分隔' }),
      experience: h('textarea', { rows: 4, placeholder: '怎么用的、场景、感受' }, [p?.experience || '']),
      pros: h('textarea', { rows: 2 }, [p?.pros || '']),
      cons: h('textarea', { rows: 2 }, [p?.cons || '']),
    };
    const save = async () => {
      const body = { name: f.name.value, url: f.url.value, category: f.category.value, rating: +f.rating.value, used_at: f.used_at.value,
        tags: tagsOf(f.tags.value), experience: f.experience.value, pros: f.pros.value, cons: f.cons.value };
      try { p ? await api.put(`/api/research/products/${p.id}`, body) : await api.post('/api/research/products', body); toast('已保存'); formBox.innerHTML = ''; load(); } catch (e) { toast(e.message, true); }
    };
    formBox.replaceChildren(h('div.card.hl', {}, [h('div.row.between', {}, [h('h3', {}, p ? `编辑「${p.name}」` : '详细记录产品体验'),
      h('button.icon', { title: '关闭', onclick: () => { formBox.innerHTML = ''; } }, ui.icon('x'))]),
      h('div.grid', {}, [field('产品名', f.name), field('链接', f.url), field('类别', f.category), field('评分', f.rating), field('使用时间', f.used_at), field('标签', f.tags)]),
      field('我的体验', f.experience), h('div.grid', {}, [field('优点', f.pros), field('缺点', f.cons)]),
      h('div.row', {}, [h('button.primary', { onclick: save }, [ui.icon('check'), '保存']), h('button.ghost', { onclick: () => { formBox.innerHTML = ''; } }, '取消')])]));
    formBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    f.name.focus();
  };

  const researchIt = async (p) => {
    const d = await api.get(`/api/research/products/${p.id}/draft`);
    sessionStorage.setItem(PREFILL_KEY, JSON.stringify(d));
    go('new');
  };

  const prodCard = (p) => h('div.card.rs-prod', {}, [
    h('div.row', {}, [h('span.name', {}, p.url ? h('a', { href: p.url, target: '_blank', rel: 'noopener', style: { color: 'inherit' } }, p.name) : p.name), stars(h, p.rating)]),
    h('div.row', {}, [[p.category, p.used_at].filter(Boolean).length ? h('span.muted', {}, [p.category, p.used_at].filter(Boolean).join(' · ')) : null, ...p.tags.map((t) => h('span.tag', {}, '#' + t))]),
    p.experience ? h('div.clamp3', { title: p.experience }, p.experience) : null,
    p.pros || p.cons ? h('div.pc', {}, [p.pros ? h('span.tag.ok', {}, '优') : null, p.pros ? h('span', {}, p.pros) : null,
      p.cons ? h('span.tag.err', {}, '缺') : null, p.cons ? h('span', {}, p.cons) : null]) : null,
    h('div.row.acts', {}, [
      h('button.outline.sm', { onclick: () => researchIt(p) }, [ui.icon('research'), '调研这个产品']),
      h('span.grow'),
      h('button.icon', { title: '编辑', onclick: () => form(p) }, ui.icon('edit')),
      h('button.icon', { title: '删除', onclick: async () => { if (confirm(`删除「${p.name}」？`)) { await api.del(`/api/research/products/${p.id}`); load(); } } }, ui.icon('trash')),
    ]),
  ]);
  const count = h('span.muted');
  const load = async () => {
    const ps = await api.get('/api/research/products?q=' + encodeURIComponent(q));
    count.textContent = `${ps.length} 个`;
    list.replaceChildren(...(ps.length ? ps.map(prodCard) : [h('div', { style: { gridColumn: '1/-1' } }, ui.empty(q ? '没找到' : '还没有记录', '在上面一句话记下你用过的产品'))]));
  };

  const quick = ui.composer({
    placeholder: '一句话记录：Cursor 4星 补全快但贵 #AI编程',
    hint: '产品名 评分 体验 #标签 · 也认 ★★★★、4/5、链接、「优：… 缺：…」· Enter 保存',
    onSubmit: async (text) => {
      try { const p = await api.post('/api/research/products/quick', { text }); toast(`已记录：${p.name}`); load(); } catch (e) { toast(e.message, true); return false; }
    },
  });
  const sb = searchBox(h, ui, '搜索产品、体验、标签…', (v) => { q = v; load(); });
  sb.style.width = '260px';
  el.append(quick,
    h('div.row', { style: { margin: '-4px 0 0' } }, [h('span.grow'), h('button.ghost.sm', { onclick: () => form() }, [ui.icon('plus'), '详细记录'])]),
    formBox,
    h('div.row', { style: { margin: '18px 0 12px' } }, [h('div.section-title.grow', { style: { margin: 0 } }, ['我用过的产品 ', count]), sb]),
    list);
  await load();
}

function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
