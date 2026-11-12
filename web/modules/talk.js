// 讨论：语音或打字直接聊，脑暴、理思路、做判断都行（Agent 自己判断，只读）。聊完自动整理成「议题卡」存档（后端见 app/modules/talk.py）；
// 结论记进判断台账、下一步加到今天事项由人点。下面还有框架库（判断卡）。路由：#talk、#talk/t/<议题 id>
import { startCall } from '../voice_rt.js';
import { framesSection } from './_frames.js';

const OPENERS = ['一起脑暴：', '我有个想法想理一理：', '帮我判断这件事值不值得做：', '我卡在一个问题上：'];
const DOING_NOW = (m) => {
  if (m.talk === 'listening') return '在听';
  if (m.talk === 'speaking') return '在说';
  if (m.thinking) return m.doing || '在想';
  return '等你说';
};

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const yuan = (v) => `¥${(v || 0).toFixed(v < 0.01 ? 4 : 2)}`;
const mb = (b) => `${Math.max((b || 0) / 1048576, 0.1).toFixed(1)} MB`;

function callHistory(calls, { api, h, md, toast, onResume, onDeleted }) {
  const detail = h('div.call-detail', { hidden: true });
  const show = async (c) => {
    let d;
    try { d = await api.get(`/api/voice/calls/${c.id}`); } catch (e) { toast('打不开：' + e.message); return; }
    const audio = h('audio', { controls: true, preload: 'metadata', src: `/api/voice/calls/${c.id}/audio` });
    const seek = (t) => { audio.currentTime = t; audio.play().catch(() => {}); };
    const WHO = { user: '你', fast: '接话' };
    const rows = d.events.flatMap((e) => {
      const time = h('button.call-time', { onclick: () => seek(e.t) }, clock(e.t));
      if (WHO[e.kind]) return [h('div.call-line.' + e.kind, {}, [time, h('span', {}, e.text + (e.interrupted ? '（被打断）' : ''))])];
      if (e.kind === 'slow_full') return [h('details.call-line', {}, [h('summary', {}, [time, '完整回答']), h('div', {}, md(e.text))])];
      if (e.kind === 'search') return [h('details.call-line', {}, [h('summary', {}, [time, `搜索「${e.query}」${e.took_s} 秒`]), h('pre', {}, JSON.stringify(e.found, null, 1))])];
      if (e.kind === 'tool' && e.text) return [h('div.call-line.muted', {}, [time, e.text.replace('mcp__voice_search__', '')])];
      if (e.kind === 'tool' && e.name !== 'web_search') return [h('details.call-line', {}, [h('summary', {}, [time, `工具 ${e.name}`]), h('pre', {}, JSON.stringify({ args: e.args, out: e.out }, null, 1))])];
      if (e.kind === 'forward') return [h('div.call-line.muted', {}, [time, `模型没调工具，补转到 ${e.to}`])];
      return [];
    });
    detail.hidden = false;
    detail.replaceChildren(
      h('div.muted', {}, `${c.started_at.slice(5, 16).replace('T', ' ')} · ${clock(c.duration_s)} · ${c.responses} 次回应 · 文本入 ${c.input_text} 音频入 ${c.input_audio} 文本出 ${c.output_text} 音频出 ${c.output_audio} token · 约 ${yuan(c.cost_yuan)}`),
      audio, h('div.call-lines', {}, rows.length ? rows : h('div.muted', {}, '这通电话没有说话内容')));
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  const remove = async (c) => {
    if (!confirm(`删除这通电话的录音和说过的话？（${mb(c.size_bytes)}，删了找不回来）`)) return;
    try { await api.del(`/api/voice/calls/${c.id}`); onDeleted(); } catch (e) { toast('没删成：' + e.message); }
  };
  return h('div.card', {}, [...calls.slice(0, 30).map((c) => h('div.talk-row', {}, [
    h('a.t', { href: '#talk', onclick: (e) => { e.preventDefault(); show(c); } }, c.title || '（没说话）'),
    h('span.muted', {}, (c.started_at || '').slice(5, 16).replace('T', ' ')),
    h('span.muted', {}, clock(c.duration_s || 0)),
    h('span.muted', {}, yuan(c.cost_yuan)),
    h('span.muted', {}, mb(c.size_bytes)),
    h('button.ghost.sm', { onclick: () => onResume(c) }, '接着聊'),
    h('button.ghost.sm', { onclick: () => remove(c) }, '删除'),
  ])), detail]);
}

function toolPermissions(tools, { api, h, toast }) {
  return h('div.card', {}, tools.map((t) => {
    const box = h('input', { type: 'checkbox', checked: t.enabled, onchange: async () => {
      try { await api.put('/api/settings', { voice_rt: { permissions: { [t.key]: box.checked } } }); toast(`${t.label}已${box.checked ? '打开' : '关闭'}`); }
      catch (e) { box.checked = !box.checked; toast('没改成：' + e.message); }
    } });
    return h('label.tool-row', {}, [box, h('div', {}, [h('div', {}, t.label), h('div.muted', {}, t.access)])]);
  }));
}

const SECS = [['goal', '目标'], ['lenses', '看问题的角度'], ['options', '可选方案'], ['headroom', '空间判断'], ['quality', '怎么算做好'], ['risks', '风险和反模式']];

function topicCard(t, { api, h, ui, toast, openChat }, { open = false, onChange }) {
  const c = t.card;
  const el = h('div.card.tp-card' + (open ? '.open' : ''), { id: 'tp-' + t.id });
  const resume = () => openChat({ module: 'talk', title: '讨论 · ' + t.title, sessionId: t.session_id });
  const head = () => [
    h('div.tp-meta', {}, [c.mode ? h('span.tag', {}, c.mode) : null, t.frame ? h('span.tag.gray', { title: '讨论套用的判断卡' }, t.frame.title) : null,
      h('span.muted', {}, (t.updated_at || '').slice(5, 16).replace('T', ' '))]),
    h('div.tp-q', {}, t.title),
    c.goal ? h('div.tp-goal', {}, c.goal) : null,
  ];
  const collapsed = () => el.replaceChildren(...head(),
    c.conclusions.length ? h('div.tp-concl', {}, [h('b', {}, '结论：'), c.conclusions[0], c.conclusions.length > 1 ? h('span.muted', {}, ` 等 ${c.conclusions.length} 条`) : null]) : null,
    h('div.tp-acts', {}, [h('button.ghost.sm', { onclick: (e) => { e.stopPropagation(); expanded(); } }, '展开议题卡'),
      h('button.ghost.sm', { onclick: (e) => { e.stopPropagation(); resume(); } }, [ui.icon('chat'), '接着聊'])]));
  const recorded = new Set(t.judgments.map((j) => j.text));
  const expanded = () => {
    const secs = SECS.filter(([k]) => (k === 'goal' ? false : c[k]?.length)).map(([k, name]) => h('div.tp-sec', {}, [h('h4', {}, name),
      h('ul', {}, c[k].map((x) => h('li', {}, k === 'options' ? [h('b', {}, x.name), x.how ? '：' + x.how : ''] : x)))]));
    const concl = c.conclusions.map((x) => {
      const btn = recorded.has(x) ? h('span.tag.ok', {}, '已记进台账') : h('button.ghost.sm', { title: '作为你自己的判断记进知识库 · 判断台账，到期会提醒复查', onclick: async () => {
        btn.disabled = true;
        try { t = await api.post(`/api/talk/topics/${t.id}/judgments`, { text: x }); recorded.add(x); btn.replaceWith(h('span.tag.ok', {}, '已记进台账')); toast('记进判断台账了'); }
        catch (e) { btn.disabled = false; toast(e.message, true); }
      } }, '记进台账');
      return h('li.tp-li', {}, [h('span', {}, x), btn]);
    });
    const steps = c.next_steps.map((x) => ({ x, box: h('input', { type: 'checkbox', checked: true }) }));
    const addSteps = h('button.sm', { onclick: async () => {
      const picked = steps.filter((s) => s.box.checked).map((s) => s.x);
      if (!picked.length) return toast('先勾选要加的下一步', true);
      addSteps.disabled = true;
      try { const r = await api.post(`/api/talk/topics/${t.id}/tasks`, { next_steps: picked }); toast(`今天的事项共 ${r.task_ids.length} 件来自这次讨论`); }
      catch (e) { toast(e.message, true); }
      addSteps.disabled = false;
    } }, '加到今天的事项');
    const redo = h('button.ghost.sm', { onclick: async () => {
      redo.disabled = true; redo.textContent = '整理中…';
      try { await api.post('/api/talk/topics/refresh', { session_id: t.session_id }); onChange(t.id); }
      catch (e) { toast('整理失败：' + e.message, true); redo.disabled = false; redo.textContent = '重新整理'; }
    } }, '重新整理');
    el.classList.add('open');
    el.replaceChildren(...head(),
      secs.length ? h('div.tp-secs', {}, secs) : null,
      concl.length ? h('div.tp-sec', {}, [h('h4', {}, '结论'), h('ul', {}, concl)]) : null,
      c.open_questions.length ? h('div.tp-sec', {}, [h('h4', {}, '待定问题'), h('ul', {}, c.open_questions.map((x) => h('li', {}, x)))]) : null,
      steps.length ? h('div.tp-sec', {}, [h('h4', {}, '下一步'), ...steps.map((s) => h('label.tp-step', {}, [s.box, s.x])), addSteps]) : null,
      h('div.tp-acts', {}, [h('button.sm', { onclick: resume }, [ui.icon('chat'), '接着聊']), redo, h('span.grow'),
        h('button.ghost.sm', { onclick: () => { el.classList.remove('open'); collapsed(); } }, '收起')]));
  };
  el.addEventListener('click', () => { if (!el.classList.contains('open')) expanded(); });
  if (open) expanded(); else collapsed();
  return el;
}

export default {
  async render(el, ctx) {
    const { api, h, md, ui, toast, openChat, refresh, sub } = ctx;
    // 一次通话里说的每句都接着同一个对话
    let calling = false, called = false;
    const start = (text) => { openChat({ module: 'talk', title: '讨论', fresh: !called, send: text }); called = calling; };
    const open = (id) => openChat({ module: 'talk', title: '讨论', sessionId: id });
    const box = ui.composer({
      placeholder: '说出你在想的事，或者打字…',
      hint: '点麦克风开始通话：说完停一下自动发送，回复会念出来，开口就能打断',
      voiceAutoSend: true,
      onVoiceCall: (on) => { calling = on; called = false; if (on) { fetch('/api/chat/warm/talk', { method: 'POST' }).catch(() => {}); fetch('/api/voice/speak/prepare', { method: 'POST' }).catch(() => {}); } },
      onSubmit: (t) => { start(t); },
    });

    // 实时通话：连不上或中途断了，退回上面输入框的本地通话，下一句接着说
    const callWrap = h('div.rt-call');
    let hangup = null;
    const callBtn = h('button.primary', { onclick: () => (hangup ? hangup() : startRt()) }, '开始实时通话');
    const chip = h('span.rt-chip', { hidden: true });
    const rtLog = h('div.rt-log', { hidden: true });
    const line = (who, content) => { rtLog.hidden = false; rtLog.append(h('div.rt-line.' + who, {}, content)); rtLog.scrollTop = rtLog.scrollHeight; };
    const endRt = () => {
      hangup = null;
      callBtn.textContent = '开始实时通话';
      callBtn.disabled = false;
      chip.hidden = true;
      box.hidden = false;
      window.removeEventListener('hashchange', hangRt);
    };
    const hangRt = () => hangup?.();
    let callId = null;
    const showCost = async () => {  // 挂断后等服务端把最后的用量写完
      const id = callId;
      callId = null;
      if (!id) return;
      await new Promise((r) => setTimeout(r, 800));
      const c = await api.get(`/api/voice/calls/${id}`).catch(() => null);
      if (c?.responses) line('cost', `这通电话 ${clock(c.duration_s)}，${c.responses} 次回应，约 ${yuan(c.cost_yuan)}`);
    };
    const startRt = async (resume) => {
      callBtn.disabled = true;
      chip.hidden = false; chip.textContent = '连接中';
      rtLog.replaceChildren();
      box.hidden = true;
      try {
        const call = await startCall({
          resume,
          onReady: (m) => { callId = m.call; if (m.resumed) line('cost', '接着上次聊，直接说就行'); },
          onStatus: (m) => { chip.textContent = DOING_NOW(m); },
          onUser: (t) => line('user', t),
          onReply: (t) => line('fast', t),
          onSlow: (t) => line('slow', md(t)),
          onFallback: (why) => { toast(why); setTimeout(() => box.querySelector('.mic')?.click(), 0); },
          onEnd: () => { endRt(); showCost(); },
        });
        hangup = call.hangup;
        callBtn.textContent = '结束通话';
        callBtn.disabled = false;
        window.addEventListener('hashchange', hangRt);
      } catch (e) {
        endRt();
        toast(e.name === 'NotAllowedError' ? '麦克风没有授权，在浏览器地址栏左侧打开' : '通话打不开：' + e.message);
      }
    };
    const rtInfo = await api.get('/api/voice/rt/status').catch(() => null);
    if (rtInfo?.configured) callWrap.append(h('div.rt-bar', {}, [callBtn, chip]), rtLog);

    el.append(
      ui.pageHead('讨论', '脑暴、理思路、做判断都在这里，语音或打字直接聊，不用选类型。聊完自动整理成议题卡存档'),
      callWrap,
      box,
      ui.chips(OPENERS.map((t) => ({ label: t, onClick: () => box.setValue(t) }))),
    );

    const [sessions, topics, calls, tools, usage] = await Promise.all([api.get('/api/chat/talk/sessions'), api.get('/api/talk/topics?limit=100'),
      api.get('/api/voice/calls').catch(() => []), api.get('/api/voice/tools').catch(() => []), api.get('/api/voice/calls/usage').catch(() => ({}))]);
    const resumeCall = (c) => {
      if (hangup) { toast('先挂断现在这通电话'); return; }
      startRt(c.id);
      callWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    const focus = sub?.[0] === 't' ? +sub[1] : 0;
    const topicOf = Object.fromEntries(topics.map((t) => [t.session_id, t]));
    const pending = sessions.filter((s) => !topicOf[s.id] || (s.updated_at || '') > (topicOf[s.id].updated_at || '')).slice(0, 8);
    const now = async (s, btn) => {
      btn.disabled = true; btn.textContent = '整理中…';
      try { const t = await api.post('/api/talk/topics/refresh', { session_id: s.id }); location.hash = `#talk/t/${t.id}`; }
      catch (e) { toast('整理失败：' + e.message, true); btn.disabled = false; btn.textContent = '现在整理'; }
    };
    if (pending.length) el.append(ui.section('还在聊 / 待整理', '最后一句话之后闲置 5 分钟会自动整理成议题卡'), h('div.card', {}, pending.map((s) => {
      const btn = h('button.sm.ghost', { onclick: () => now(s, btn) }, '现在整理');
      return h('div.talk-row', {}, [h('a.t', { href: '#talk', onclick: (e) => { e.preventDefault(); open(s.id); } }, s.title || '讨论'),
        h('span.muted', {}, (s.updated_at || '').slice(5, 16).replace('T', ' ')), topicOf[s.id] ? h('span.muted', {}, '有新内容') : null, btn]);
    })));
    el.append(ui.section('议题', topics.length ? `${topics.length} 个 · 每次讨论一张，接着聊会更新同一张` : ''),
      topics.length ? h('div.tp-list', {}, topics.map((t) => topicCard(t, ctx, { open: t.id === focus, onChange: (id) => { location.hash = `#talk/t/${id}`; refresh(); } })))
        : ui.empty('还没有议题', '说一句话就能开始，聊完自动整理成议题卡'));
    if (focus) setTimeout(() => document.getElementById('tp-' + focus)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
    el.append(await framesSection(ctx));
    if (calls.length) el.append(ui.section('历史通话', `录音和全部内容都只存在本机，共占 ${mb(usage.bytes)}`), callHistory(calls, { api, h, md, toast, onResume: resumeCall, onDeleted: () => (hangup ? toast('删好了') : refresh()) }));
    if (tools.length) el.append(ui.section('通话工具权限', '关掉的工具从下一通电话起不给模型，通话中调用也不执行'), toolPermissions(tools, { api, h, toast }));
  },
};
