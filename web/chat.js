// 右侧对话面板：每个板块一个 Agent，调本地 Claude Code（Codex 备选）。
// openChat({module, ref, title, prefill, send, sessionId, fresh, expand})
//   send: 直接发送这条消息；prefill: 只填入输入框；fresh: 开新对话；sessionId: 打开指定会话。
import { api, h, md } from './api.js';
import { icon, composer, chips } from './ui.js';

const TIPS = {
  review: ['今天的事项完成得怎么样？', '我今天盯 Agent 花了多少时间？哪里可以省？', '记一条经验：'],
  plan: ['帮我把今天的事按优先级排一下', '哪些事可以交给 Agent 自动跑？', '把第一件事拆细一点'],
  feed: ['今天最值得看的 5 条', '最近有什么 agent 相关的新论文？', '把「世界模型」加进兴趣词'],
  research: ['调研一下：', '对比一下最近的 AI 编程工具', '把最近的调研结论汇总一下'],
  learn: ['给我做一个学习计划：', '深读这篇论文：', '根据我的反馈调整学习计划'],
  agents: ['哪些会话在等我？', '总结各 Agent 进展', '卡住的怎么处理？'],
  kb: ['我之前关于 Agent 评测记过什么？', '汇总我这周的问题与经验', '我调研过哪些产品？'],
};

const state = { module: '', ref: '', title: '', sessionId: null, busy: false };
let root, box, log, sessSel, engineSel;

export function initChat(el) {
  root = el;
  // 对话里提交的后台任务结束时，平台已把结果回帖到那个对话；正在看它就刷新
  document.addEventListener('job-done', (e) => {
    if (e.detail.chat_session_id && e.detail.chat_session_id === state.sessionId && !state.busy) loadMessages();
  });
}

export async function openChat({ module, ref = '', prefill = '', send = '', title = '', expand = true, fresh = false, sessionId = null } = {}) {
  const changed = module !== state.module || ref !== state.ref || fresh || sessionId;
  state.module = module; state.ref = ref; state.title = title || state.title || module;
  if (changed || !box) {
    state.sessionId = sessionId || null;
    const ss = await api.get(`/api/chat/${module}/sessions?ref=${encodeURIComponent(ref)}`).catch(() => []);
    if (!fresh && !sessionId && ref && ss.length) state.sessionId = ss[0].id; // 绑定对象的对话默认续上一次
    render(ss);
    await loadMessages();
  }
  if (expand) root.classList.remove('collapsed');
  if (send) submit(send);
  else if (prefill) box.setValue(prefill);
}

export const closeChat = () => root.classList.add('collapsed');

function render(sessions) {
  root.innerHTML = '';
  sessSel = h('select', { title: '历史对话', onchange: async (e) => { state.sessionId = e.target.value ? +e.target.value : null; await loadMessages(); } },
    [h('option', { value: '' }, '＋ 新对话'), ...sessions.map((s) => h('option', { value: s.id, selected: s.id === state.sessionId }, (s.title || '对话').slice(0, 18)))]);
  engineSel = h('select', { title: '引擎' }, [h('option', { value: '' }, '默认引擎'), h('option', { value: 'claude' }, 'Claude Code'), h('option', { value: 'codex' }, 'Codex')]);
  log = h('div.chat-log');
  box = composer({ placeholder: '问点什么，或让它直接帮你改…', hint: 'Enter 发送 · Shift+Enter 换行', onSubmit: (t) => submit(t) });
  root.append(
    h('div.chat-head', {}, [h('b', {}, `${state.title} · Agent`), sessSel, engineSel,
      h('button.icon', { title: '收起', onclick: closeChat }, icon('x'))]),
    log, box);
}

function tips() {
  return h('div.chat-tips', {}, [
    h('div', {}, '我能看到这个板块的当前数据和你的本地知识库，可以直接帮你查、改、记。'),
    chips((TIPS[state.module] || []).map((t) => ({ label: t, onClick: () => (t.endsWith('：') ? box.setValue(t) : submit(t)) })), { left: true }),
  ]);
}

async function loadMessages() {
  log.innerHTML = '';
  if (!state.sessionId) { log.append(tips()); return; }
  const s = await api.get(`/api/chat/session/${state.sessionId}`);
  for (const m of s.messages) log.append(bubble(m.role, m.content));
  log.scrollTop = log.scrollHeight;
}

function bubble(role, content) {
  if (role === 'tool') return h('div.msg.tool', { title: content }, '⚙ ' + content);
  if (role === 'user') return h('div.msg.user', {}, content);
  if (role === 'error') return h('div.msg.error', {}, content);
  return h('div.msg.assistant', {}, [h('div.avatar', {}, icon('leaf')), h('div.body', {}, md(content))]);
}

async function submit(text) {
  text = (text || '').trim();
  if (!text || state.busy) return false;
  state.busy = true;
  root.classList.remove('collapsed');
  if (log.querySelector('.chat-tips')) log.innerHTML = '';
  log.append(bubble('user', text));
  const body = h('div.body', {}, h('span.dots', {}, '思考中'));
  const pending = h('div.msg.assistant.pending', {}, [h('div.avatar', {}, icon('leaf')), body]);
  log.append(pending);
  log.scrollTop = log.scrollHeight;
  try {
    const r = await fetch(`/api/chat/${state.module}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: state.sessionId, ref: state.ref, engine: engineSel.value }),
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = ''; const texts = []; let linked = [];
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
        else if (ev.type === 'end' && ev.jobs?.length) linked = ev.jobs;
        else if (ev.type === 'tool') log.insertBefore(bubble('tool', ev.text), pending);
        else if (ev.type === 'error' || ev.type === 'engine') log.insertBefore(bubble('error', ev.text), pending);
        else if (ev.type === 'text') { texts.push(ev.text); pending.classList.remove('pending'); body.replaceChildren(md(texts.join('\n\n'))); }
        else if (ev.type === 'done' && ev.text) { pending.classList.remove('pending'); body.replaceChildren(md(ev.text)); }
        log.scrollTop = log.scrollHeight;
      }
    }
    if (!texts.length && body.querySelector('.dots')) pending.remove();
    if (linked.length) {
      await loadMessages(); // 已经跑完的任务此时已回帖
      log.append(h('div.msg.tool', {}, `⏳ 这轮提交了 ${linked.length} 个后台任务，完成后结果会自动发到这个对话`));
      log.scrollTop = log.scrollHeight;
    }
    document.dispatchEvent(new CustomEvent('agent-done', { detail: { module: state.module, ref: state.ref } }));
  } catch (e) {
    body.replaceChildren('出错：' + e.message);
  } finally {
    state.busy = false;
  }
}
