// 右侧对话面板：每个板块一个 Agent，调本地 Claude Code（Codex 备选）。
// 板块页面也可以调用 openChat({module, ref, prefill}) 打开绑定到某个对象的对话。
import { api, h, md } from './api.js';

const state = { module: '', ref: '', sessionId: null, busy: false };
let root;

export function initChat(el) {
  root = el;
}

export async function openChat({ module, ref = '', prefill = '', title = '', expand = true } = {}) {
  const changed = module !== state.module || ref !== state.ref;
  state.module = module; state.ref = ref;
  if (changed) {
    state.sessionId = null;
    const ss = await api.get(`/api/chat/${module}/sessions?ref=${encodeURIComponent(ref)}`).catch(() => []);
    if (ref && ss.length) state.sessionId = ss[0].id; // 绑定对象的对话默认续上一次
    render(title, ss);
  }
  if (expand) root.classList.remove('collapsed');
  if (prefill) { const ta = root.querySelector('textarea'); ta.value = prefill; ta.focus(); }
}

async function render(title, sessions) {
  root.innerHTML = '';
  const sel = h('select.sess', { onchange: async (e) => { state.sessionId = e.target.value ? +e.target.value : null; await loadMessages(); } },
    [h('option', { value: '' }, '新对话'), ...sessions.map((s) => h('option', { value: s.id, selected: s.id === state.sessionId }, `${s.title || '对话'} · ${s.engine}`))]);
  const engine = h('select.engine', {}, [h('option', { value: '' }, '默认引擎'), h('option', { value: 'claude' }, 'Claude Code'), h('option', { value: 'codex' }, 'Codex')]);
  const head = h('div.chat-head', {}, [
    h('b', {}, `${title || state.module} Agent`), sel, engine,
    h('button.icon', { title: '收起', onclick: () => root.classList.add('collapsed') }, '×'),
  ]);
  const log = h('div.chat-log');
  const ta = h('textarea', { placeholder: '和本板块 Agent 对话… (⌘/Ctrl+Enter 发送)', rows: 3 });
  const send = h('button.primary', { onclick: () => submit(ta, log, engine.value) }, '发送');
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(ta, log, engine.value); });
  root.append(head, log, h('div.chat-input', {}, [ta, send]));
  await loadMessages();
}

async function loadMessages() {
  const log = root.querySelector('.chat-log');
  log.innerHTML = '';
  if (!state.sessionId) { log.append(h('div.muted', {}, '新对话。Agent 能看到本板块的当前数据，可以直接让它修改。')); return; }
  const s = await api.get(`/api/chat/session/${state.sessionId}`);
  for (const m of s.messages) log.append(bubble(m.role, m.content));
  log.scrollTop = log.scrollHeight;
}

function bubble(role, content) {
  if (role === 'tool') return h('div.msg.tool', {}, '⚙ ' + content);
  if (role === 'user') return h('div.msg.user', {}, content);
  if (role === 'error') return h('div.msg.error', {}, content);
  return h('div.msg.assistant', {}, md(content));
}

async function submit(ta, log, engine) {
  const text = ta.value.trim();
  if (!text || state.busy) return;
  state.busy = true; ta.value = '';
  if (log.querySelector('.muted')) log.innerHTML = '';
  log.append(bubble('user', text));
  const pending = h('div.msg.assistant.pending', {}, '思考中…');
  log.append(pending);
  try {
    const r = await fetch(`/api/chat/${state.module}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: state.sessionId, ref: state.ref, engine }),
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '', texts = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === 'meta') state.sessionId = ev.session_id;
        else if (ev.type === 'tool') log.insertBefore(bubble('tool', ev.text), pending);
        else if (ev.type === 'error' || ev.type === 'engine') log.insertBefore(bubble('error', ev.text), pending);
        else if (ev.type === 'text') { texts.push(ev.text); pending.classList.remove('pending'); pending.replaceChildren(md(texts.join('\n\n'))); }
        log.scrollTop = log.scrollHeight;
      }
    }
    if (!texts.length) pending.remove();
    document.dispatchEvent(new CustomEvent('agent-done', { detail: { module: state.module, ref: state.ref } }));
  } catch (e) {
    pending.replaceChildren('出错：' + e.message);
  } finally {
    state.busy = false;
  }
}
