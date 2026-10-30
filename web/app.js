// 外壳：侧边栏（图标导航 + 最近对话）+ 页面路由（#<module>/...）+ 右侧 Agent 对话。
// 板块页面约定：web/modules/<id>.js 导出 default { render(container, ctx) }
//   ctx = { api, h, md, toast, field, ui, openChat, ask, refresh, module, sub }
//   - ask(text)：直接把一句话发给本板块 Agent（打开右侧对话并发送）
//   - refresh()：只重绘页面主体；Agent 回复结束会触发 document 'agent-done' 事件
//   - 页面自己用 ui.pageHead() 渲染标题，用 ui.composer() 提供便捷输入
import { api, h, md, toast, field } from './api.js';
import { initChat, openChat, chatBusy, chatSnapshot } from './chat.js';
import * as ui from './ui.js';

const ICONS = { review: 'review', plan: 'plan', feed: 'feed', research: 'research', learn: 'learn', kb: 'kb', agents: 'robot' };
let meta;
const page = document.getElementById('page');

async function boot() {
  initChat(document.getElementById('chat'));
  meta = await api.get('/api/meta');
  const nav = document.getElementById('nav');
  nav.innerHTML = '';
  nav.append(
    h('div.brand', {}, [ui.icon('leaf'), '学习平台']),
    h('button.new-chat', { onclick: () => openChat({ module: currentId(), title: titleOf(currentId()), fresh: true }) }, [ui.icon('plus'), '新对话']),
    h('nav#nav-links', {}, meta.modules.map((m) => h('a', { href: '#' + m.id, 'data-id': m.id }, [ui.icon(ICONS[m.id] || 'spark'), h('span', {}, m.title)]))),
    h('div.nav-sec#recent'),
    h('div.nav-foot', {}, [h('a', { href: '#settings' }, [ui.icon('settings'), h('span', {}, '设置')]),
      h('span#engine-status', {}, Object.entries(meta.engines).map(([k, v]) => `${k}${v ? '✓' : '✗'}`).join(' '))]),
  );
  window.addEventListener('hashchange', route);
  document.addEventListener('agent-done', loadRecent);
  await route();
  loadRecent();
  watchJobs();
  watchApprovals();
  watchUpdates();
  restoreChat();
}

// ---------- 改动自动生效 ----------
// 前端文件变了 / 后端重启过 → 自动刷新页面（正在输入或对话进行中时改为提示条）；
// 后端改动在等任务结束才重启（supervisor）→ 显示等待提示。
function watchUpdates() {
  let base = null;
  const bar = h('div.update-bar');
  document.body.append(bar);
  const typing = () => [...document.querySelectorAll('textarea, input[type=text], input:not([type])')]
    .some((e) => e.value && e.value.trim() && !e.closest('.chat-head')) || chatBusy();
  const reload = () => {
    try { sessionStorage.setItem('chat-restore', JSON.stringify(chatSnapshot())); } catch { /* 无痕模式 */ }
    location.reload();
  };
  const show = (html, act) => { bar.replaceChildren(...html); bar.classList.toggle('on', !!html.length); if (act) bar.onclick = act; };
  setInterval(async () => {
    if (document.hidden) return;
    const s = await api.get('/api/dev/status').catch(() => null);
    if (!s) { show([h('span', {}, '服务重启中…')]); return; }
    if (!base) base = s;
    const updated = s.static_version !== base.static_version || s.started !== base.started;
    if (updated) {
      if (!typing()) return reload();
      return show([ui.icon('refresh'), h('span', {}, '平台已更新，'), h('a', { href: '#' }, '点此刷新'), h('span.muted', {}, '（正在输入 / 对话中，没有自动刷新）')], (e) => { e.preventDefault(); reload(); });
    }
    const p = s.reload_pending;
    if (p) {
      const b = p.busy || s.busy;
      const wait = [b.jobs ? `${b.jobs} 个后台任务` : '', b.chats ? `${b.chats} 个对话` : ''].filter(Boolean).join('、');
      return show([ui.icon('clock'), h('span', {}, `后端有更新（${(p.files || []).length} 个文件），${wait ? `等 ${wait} 结束后` : '即将'}自动重启`),
        h('span.muted', {}, '任务不会被打断')]);
    }
    show([]);
  }, 3000);
}

function restoreChat() {
  let c;
  try { c = JSON.parse(sessionStorage.getItem('chat-restore') || 'null'); sessionStorage.removeItem('chat-restore'); } catch { return; }
  if (!c?.module || !(c.open || c.sessionId)) return;
  openChat({ module: c.module, ref: c.ref, title: c.title, sessionId: c.sessionId, expand: c.open, prefill: c.draft });
}

// 后台任务结束 → 弹通知（点击打开结果）、刷新最近对话；chat.js 收到 job-done 会刷新正在看的那个对话
function watchJobs() {
  let since = new Date(Date.now() - 5000).toLocaleString('sv-SE').replace(' ', 'T');
  setInterval(async () => {
    if (document.hidden) return;
    const js = await api.get(`/api/jobs/finished?since=${encodeURIComponent(since)}`).catch(() => null);
    if (!js?.length) return;
    since = js[js.length - 1].finished_at;
    for (const j of js) {
      document.dispatchEvent(new CustomEvent('job-done', { detail: j }));
      notice(j);
    }
    loadRecent();
  }, 6000);
}

// 侧栏「规划」「Agent 看板」上的待审批数
function watchApprovals() {
  const paint = async () => {
    if (document.hidden) return;
    const list = await api.get('/api/jobs/approvals').catch(() => null);
    if (!list) return;
    for (const id of ['plan', 'agents']) {
      const a = document.querySelector(`#nav-links a[data-id="${id}"]`);
      if (!a) continue;
      a.querySelector('.nav-badge')?.remove();
      if (list.length) a.append(h('span.nav-badge', { title: `${list.length} 项待你审批` }, String(list.length)));
    }
  };
  paint();
  setInterval(paint, 15000);
  document.addEventListener('job-done', paint);
}

function notice(j) {
  const ok = j.status === 'done';
  const t = h('div.toast.notice' + (ok ? '' : '.err'), {}, [
    h('b', {}, `${j.kind}${ok ? '完成' : '失败'}`), h('span', {}, j.title),
    h('a', { href: j.link, onclick: () => t.remove() }, '查看 →'),
    j.chat_session_id ? h('a', { href: '#', onclick: (e) => { e.preventDefault(); t.remove(); openChat({ module: j.module, sessionId: j.chat_session_id, title: titleOf(j.module) }); } }, '看对话') : null,
    h('button.icon', { onclick: () => t.remove(), title: '关闭' }, ui.icon('x')),
  ]);
  document.body.append(t);
  setTimeout(() => t.remove(), 15000);
}

const currentId = () => location.hash.slice(1).split('/')[0] || meta.modules[0]?.id || 'settings';
const titleOf = (id) => meta.modules.find((m) => m.id === id)?.title || id;

async function loadRecent() {
  const box = document.getElementById('recent');
  const rs = await api.get('/api/chat/recent?limit=8').catch(() => []);
  box.replaceChildren(...(rs.length ? [h('h4', {}, '最近对话'), ...rs.map((s) => h('a', {
    href: '#' + s.module, title: `${titleOf(s.module)} · ${s.title}`,
    onclick: () => setTimeout(() => openChat({ module: s.module, ref: s.ref, title: titleOf(s.module), sessionId: s.id }), 50),
  }, [ui.icon('chat'), (s.title || '对话')]))] : []));
}

async function route() {
  const id = currentId();
  document.querySelectorAll('#nav-links a, .nav-foot a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
  page.innerHTML = '';
  const wrap = h('div.page-wrap');
  page.append(wrap);
  page.scrollTop = 0;
  if (id === 'settings') return renderSettings(wrap);
  const m = meta.modules.find((x) => x.id === id);
  if (!m) { wrap.append(ui.empty('未知页面')); return; }
  let mod;
  const ask = (text) => openChat({ module: id, title: m.title, send: text });
  // 只重绘页面主体，不重置右侧（可能绑定了某个对象的）对话
  const refresh = async () => { wrap.innerHTML = ''; await mod.default.render(wrap, ctx); };
  const ctx = { api, h, md, toast, field, ui, openChat, ask, refresh, module: id, title: m.title, sub: location.hash.slice(1).split('/').slice(1) };
  try {
    mod = await import(`./modules/${id}.js?v=${Date.now()}`);
    openChat({ module: id, title: m.title, expand: false });
    await mod.default.render(wrap, ctx);
  } catch (e) {
    console.error(e);
    wrap.append(h('pre.error', {}, `加载板块 ${id} 失败：${e.message}`));
  }
}

async function renderSettings(wrap) {
  const s = await api.get('/api/settings');
  const focus = h('input', { value: s.focus_windows.map((w) => `${w.start}-${w.end}`).join(', ') });
  const conc = h('input', { type: 'number', value: s.max_agent_concurrency, min: 1, max: 10 });
  const autoRun = h('input', { type: 'checkbox', checked: s.plan_auto_dispatch !== false });
  const tz = h('input', { value: s.timezone || '', placeholder: `留空 = 按作息自动推断（当前 ${s.timezone_effective || '系统'}）` });
  const eng = h('select', {}, ['claude', 'codex'].map((e) => h('option', { value: e, selected: s.engines.default === e }, e)));
  const codexModel = h('input', { value: s.engines.codex.model || '', placeholder: '留空 = codex 默认模型' });
  const claudeModel = h('input', { value: s.engines.claude.model || '', placeholder: '留空 = claude 默认模型' });
  const claudeBin = h('input', { value: s.engines.claude.bin || 'claude', placeholder: 'reclaude / claude' });
  const repos = h('textarea', { rows: 3, value: (s.repos || []).join('\n'), placeholder: '每行一个目录：复盘时分析的代码库 / 文档' });
  const { timezone_effective: _tzEff, ...stored } = s;
  const raw = h('textarea.mono', { rows: 16, value: JSON.stringify(stored, null, 2) });
  const save = async (body) => { await api.put('/api/settings', body); toast('已保存'); route(); };
  wrap.append(ui.pageHead('设置', '全局时间窗、引擎和目录；数据都在本地 data/ 下'),
    h('div.card', {}, [
      h('div.grid', {}, [field('人重度干预时间窗（专注时间）', focus), field('Agent 并发度', conc), field('默认引擎', eng), field('你所在的时区（如 Asia/Shanghai）', tz), field('自动任务到点自动派发', autoRun)]),
      h('div.grid', {}, [field('Claude 启动命令', claudeBin), field('Claude 模型', claudeModel), field('Codex 模型', codexModel)]),
      field('复盘分析目录', repos),
      h('button.primary', { onclick: () => save({
        focus_windows: focus.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => { const [start, end] = x.split('-'); return { start: start.trim(), end: end.trim() }; }),
        max_agent_concurrency: +conc.value,
        timezone: tz.value.trim(),
        plan_auto_dispatch: autoRun.checked,
        engines: { default: eng.value, codex: { model: codexModel.value.trim() }, claude: { bin: claudeBin.value.trim() || 'claude', model: claudeModel.value.trim() } },
        repos: repos.value.split('\n').map((x) => x.trim()).filter(Boolean),
      }) }, [ui.icon('check'), '保存']),
    ]),
    h('details.card.flat', {}, [h('summary', {}, '全部设置（JSON）'), raw,
      h('div', { style: { marginTop: '10px' } }, h('button', { onclick: () => { try { save(JSON.parse(raw.value)); } catch (e) { toast('JSON 错误：' + e.message, true); } } }, '保存 JSON'))]));
}

boot();
