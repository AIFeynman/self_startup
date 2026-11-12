// 右侧对话面板：每个板块一个 Agent，调本地 Claude Code（Codex 备选）。
// openChat({module, ref, title, prefill, send, sessionId, fresh, expand})
//   send: 直接发送这条消息；prefill: 只填入输入框；fresh: 开新对话；sessionId: 打开指定会话。
import { imagePicker, imageList } from './_images.js';
import { api, h, md, toast } from './api.js';
import { icon, composer, chips, noteZone } from './ui.js';
import { inCall, sentenceFeed, tts } from './voice.js';

const TIPS = {
  review: ['今天的事项完成得怎么样？', '我今天盯 Agent 花了多少时间？哪里可以省？', '记一条经验：'],
  plan: ['帮我把今天的事按优先级排一下', '哪些事可以交给 Agent 自动跑？', '把第一件事拆细一点'],
  feed: ['今天最值得看的 5 条', '最近有什么 agent 相关的新论文？', '把「世界模型」加进兴趣词'],
  intel: ['这周 S/A 级的产品变化有哪些？', 'Anthropic 最近在产品上做了什么？', '对比一下最近的 AI 编程工具定价'],
  research: ['调研一下：', '对比一下最近的 AI 编程工具', '把最近的调研结论汇总一下'],
  learn: ['给我做一个学习计划：', '深读这篇论文：', '根据我的反馈调整学习计划'],
  agents: ['哪些会话在等我？', '总结各 Agent 进展', '卡住的怎么处理？'],
  talk: ['一起脑暴：', '我有个想法想理一理：', '帮我判断这件事值不值得做：'],
  kb: ['我之前关于 Agent 评测记过什么？', '汇总我这周的问题与经验', '我调研过哪些产品？'],
  wealth: ['现在这几个标的该加还是拿着，为什么？', '美团现在该卖多少股？', '这两个价位是怎么算出来的：'],
};

const state = { module: '', ref: '', title: '', sessionId: null, busy: false, stopping: false, turn: null };
let root, box, log, sessSel, engineSel, pictures;

// ---------- 朗读回复：讨论板块可开，通话时总是念；开口就打断（见 voice.js）----------
const speakable = () => state.module === 'talk';
const speakOn = () => { try { return localStorage.getItem('talk-speak') === '1'; } catch { return false; } };
const speaking = () => speakable() && (speakOn() || inCall());
const speakBtn = () => {
  const b = h('button.icon.speak' + (speakOn() ? '.on' : ''), { title: '朗读回复（开 / 关）', onclick: () => {
    const on = !speakOn();
    try { localStorage.setItem('talk-speak', on ? '1' : '0'); } catch { /* 无痕模式 */ }
    b.classList.toggle('on', on);
    if (!on) tts.stop();
  } }, icon('volume'));
  return b;
};
const stopServer = () => { if (state.sessionId) fetch(`/api/chat/stop/${state.sessionId}`, { method: 'POST' }).catch(() => {}); };
document.addEventListener('voice-interrupt', () => {
  if (!state.busy || state.stopping) return;
  state.stopping = true;
  stopServer();
});

export function initChat(el) {
  root = el;
  // 对话里提交的后台任务结束时，平台已把结果回帖到那个对话；正在看它就刷新
  document.addEventListener('job-done', (e) => {
    if (e.detail.chat_session_id && e.detail.chat_session_id === state.sessionId && !state.busy) loadMessages();
  });
}

export async function openChat({ module, ref = '', prefill = '', send = '', title = '', expand = true, fresh = false, sessionId = null, images = [] } = {}) {
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
  if (send || images.length) submit(send, images);
  else if (prefill) box.setValue(prefill);
}

export const closeChat = () => root.classList.add('collapsed');

// 自动刷新页面时用：对话进行中不刷新；刷新前记下打开的对话，刷新后恢复
export const chatBusy = () => state.busy;
export function chatSnapshot() {
  return { module: state.module, ref: state.ref, title: state.title, sessionId: state.sessionId,
    open: root && !root.classList.contains('collapsed'), draft: box?.querySelector('textarea')?.value || '' };
}

function render(sessions) {
  root.innerHTML = '';
  sessSel = h('select', { title: '历史对话', onchange: async (e) => { state.sessionId = e.target.value ? +e.target.value : null; await loadMessages(); } },
    [h('option', { value: '' }, '＋ 新对话'), ...sessions.map((s) => h('option', { value: s.id, selected: s.id === state.sessionId }, (s.title || '对话').slice(0, 18)))]);
  engineSel = h('select', { title: '引擎' }, [h('option', { value: '' }, '默认引擎'), h('option', { value: 'claude' }, 'Claude Code'), h('option', { value: 'codex' }, 'Codex')]);
  log = noteZone(h('div.chat-log'), chatSource);
  const talk = state.module === 'talk';
  pictures = talk ? imagePicker({ label: '聊天图片', onChange: () => box?.update() }) : null;
  box = composer({ clearOnSend: true, hasContent: () => Boolean(pictures?.value().length), placeholder: talk ? '接着说…' : '问点什么，或让它直接帮你改…', hint: 'Enter 发送 · Shift+Enter 换行', voiceAutoSend: talk, onSubmit: (t) => submit(t) });
  if (pictures) { box.insertBefore(pictures.el, box.lastChild); pictures.bind(box); }
  const wideBtn = h('button.icon.chat-wide', { title: '加宽 / 还原（也可以拖左边缘调宽度）', onclick: () => toggleWide(wideBtn) }, icon('expand'));
  root.append(
    h('div.chat-resize', { title: '拖动调整宽度，双击还原', onmousedown: startResize, ondblclick: () => setWidth(420) }),
    h('div.chat-head', {}, [h('b', {}, `${state.title} · Agent`), sessSel, engineSel, speakable() ? speakBtn() : null, wideBtn,
      h('button.icon', { title: '收起', onclick: closeChat }, icon('x'))]),
    log, box);
}

// ---------- 面板宽度：拖左边缘调整，或一键加宽；记在本机 ----------
const MIN_W = 340;
const maxW = () => Math.max(MIN_W, window.innerWidth - 248 - 360); // 给侧边栏和页面主体留位置
function setWidth(w, save = true) {
  w = Math.round(Math.min(Math.max(w, MIN_W), maxW()));
  document.documentElement.style.setProperty('--chat-w', w + 'px');
  if (save) { try { localStorage.setItem('chat-w', w); } catch { /* 无痕模式 */ } }
  return w;
}
function toggleWide() {
  const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--chat-w')) || 420;
  setWidth(cur < maxW() * 0.9 ? maxW() : 420);
}
function startResize(e) {
  e.preventDefault();
  const handle = e.currentTarget;
  handle.classList.add('on'); document.body.classList.add('resizing');
  const move = (ev) => setWidth(window.innerWidth - ev.clientX, false);
  const up = (ev) => {
    setWidth(window.innerWidth - ev.clientX);
    handle.classList.remove('on'); document.body.classList.remove('resizing');
    window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
  };
  window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
}
try { const w = +localStorage.getItem('chat-w'); if (w) setWidth(w, false); } catch { /* 无痕模式 */ }

// 划线记便签的出处：这段对话，点开能回来
function chatSource() {
  if (!state.sessionId) return null;
  const name = sessSel?.value ? sessSel.selectedOptions[0]?.text : '';
  return { doc: `chat:${state.sessionId}`, title: name ? `${state.title}：${name}` : state.title, link: `#chat/${state.sessionId}`, type: 'Agent 对话' };
}

function tips() {
  return h('div.chat-tips', {}, [
    h('div', {}, state.module === 'talk' ? '脑暴、理思路、做判断都行，直接说。我能看到今天的事项和你的本地知识库，只讨论不改数据；聊完会自动整理成议题卡。' : '我能看到这个板块的当前数据和你的本地知识库，可以直接帮你查、改、记。'),
    chips((TIPS[state.module] || []).map((t) => ({ label: t, onClick: () => (t.endsWith('：') ? box.setValue(t) : submit(t)) })), { left: true }),
  ]);
}

// 学习板块的对话按「轮」编号、最新一轮在最上：长回复出来直接从头读，不用再滑回顶部
const newestFirst = () => state.module === 'learn';
const follow = () => { log.scrollTop = newestFirst() ? 0 : log.scrollHeight; };
function openTurn() {
  const t = h('div.turn', {}, h('div.turn-no', {}, `第 ${log.querySelectorAll('.turn').length + 1} 轮`));
  log.prepend(t);
  return t;
}

async function loadMessages() {
  log.innerHTML = '';
  if (!state.sessionId) { log.append(tips()); return; }
  const s = await api.get(`/api/chat/session/${state.sessionId}`);
  let host = log;
  for (const m of s.messages) {
    if (newestFirst() && (m.role === 'user' || host === log)) host = openTurn();
    host.append(bubble(m.role, m.content, m.images));
  }
  follow();
}

function bubble(role, content, images = []) {
  if (role === 'tool') return h('div.msg.tool', { title: content }, '⚙ ' + content);
  if (role === 'user') return h('div.msg.user', {}, [content, images?.length ? imageList(images) : null]);
  if (role === 'error') return h('div.msg.error', {}, content);
  const long = (content || '').length > 600;
  return h('div.msg.assistant' + (long ? '.long' : ''), {}, [h('div.avatar', {}, icon('leaf')), h('div.body', {}, [
    long ? h('button.sm.ghost.read-btn', { title: '在大窗口里阅读', onclick: () => openReader(content) }, [icon('expand'), '阅读']) : null,
    md(content)])]);
}

// 长回复（深读结果、调研结论…）是要读的内容：在页面中间的大窗口里排版阅读，Esc 关闭
function openReader(content) {
  const close = () => { ov.remove(); document.removeEventListener('keydown', esc); window.removeEventListener('hashchange', close); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  const ov = h('div.reader', { onclick: (e) => { if (e.target === ov) close(); } }, h('article.reader-doc', {}, [
    h('div.reader-bar', {}, [h('span.muted', {}, `${state.title} · Agent 回复`), h('span.grow'),
      h('button.sm.ghost', { onclick: () => navigator.clipboard?.writeText(content) }, '复制'),
      h('button.icon', { title: '关闭 (Esc)', onclick: close }, icon('x'))]),
    noteZone(h('div.reader-body', {}, md(content)), chatSource),
  ]));
  document.addEventListener('keydown', esc);
  window.addEventListener('hashchange', close); // 点了站内链接就关掉
  document.body.append(ov);
}

async function submit(text, attached = []) {
  text = (text || '').trim();
  if (pictures?.busy) { toast('图片正在添加，请稍等', true); return false; }
  const sentPictures = pictures;
  const images = attached.length ? attached : (pictures?.images() || []);
  if ((!text && !images.length) || (state.busy && !state.stopping)) return false;
  while (state.busy) await state.turn; // 被打断的上一轮很快收尾，等它存好再发这一句
  let endTurn;
  state.turn = new Promise((resolve) => { endTurn = resolve; });
  state.busy = true; state.stopping = false;
  pictures?.clear();
  tts.newTurn();
  performance.mark('chat-submit');
  const voice = sentenceFeed((t) => { if (speaking() && !state.stopping) tts.say(t); });
  root.classList.remove('collapsed');
  if (log.querySelector('.chat-tips')) log.innerHTML = '';
  const host = newestFirst() ? openTurn() : log;
  host.append(bubble('user', text, images));
  const body = h('div.body', {}, h('span.dots', {}, '思考中'));
  const pending = h('div.msg.assistant.pending', {}, [h('div.avatar', {}, icon('leaf')), body]);
  host.append(pending);
  follow();
  try {
    const r = await fetch(`/api/chat/${state.module}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: state.sessionId, ref: state.ref, engine: engineSel.value, images: images.map((img) => img.id) }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || '发送失败');
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '', live = ''; const texts = []; let linked = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === 'meta') { state.sessionId = ev.session_id; if (state.stopping) stopServer(); }
        else if (ev.type === 'end' && ev.jobs?.length) linked = ev.jobs;
        else if (ev.type === 'tool') pending.before(bubble('tool', ev.text));
        else if (ev.type === 'error' || ev.type === 'engine') pending.before(bubble('error', ev.text));
        else if (ev.type === 'delta') { if (!live) performance.mark('reply-delta'); live += ev.text; voice.feed(ev.text); pending.classList.remove('pending'); body.replaceChildren(md([...texts, live].join('\n\n'))); }
        else if (ev.type === 'text') { if (!live) voice.feed(ev.text); voice.flush(); live = ''; texts.push(ev.text); pending.classList.remove('pending'); body.replaceChildren(md(texts.join('\n\n'))); }
        else if (ev.type === 'done' && ev.text) { pending.classList.remove('pending'); body.replaceChildren(md(ev.text)); }
        follow();
      }
    }
    if (!texts.length && body.querySelector('.dots')) pending.remove();
    if (linked.length) {
      await loadMessages(); // 已经跑完的任务此时已回帖
      (newestFirst() ? log.querySelector('.turn') : log).append(h('div.msg.tool', {}, `⏳ 这轮提交了 ${linked.length} 个后台任务，完成后结果会自动发到这个对话`));
      follow();
    }
    document.dispatchEvent(new CustomEvent('agent-done', { detail: { module: state.module, ref: state.ref } }));
  } catch (e) {
    body.replaceChildren('出错：' + e.message);
    if (sentPictures && !sentPictures.value().length) sentPictures.restore(images);
    return false;
  } finally {
    state.busy = false; state.stopping = false;
    endTurn();
  }
}
