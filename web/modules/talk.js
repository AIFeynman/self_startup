// 讨论：说出想法，Agent 在右侧对话面板里帮忙理思路、给建议（只读）；讨论完「整理」，确认后再存。
import { startCall } from '../voice_rt.js';

const OPENERS = ['我有个想法想理一理：', '帮我想想这件事该不该做：', '我卡在一个问题上：'];
const DOING_NOW = (m) => {
  if (m.talk === 'listening') return '在听';
  if (m.talk === 'speaking') return '在说';
  if (m.searching) return '在搜索';
  if (m.thinking) return m.doing || '在想';
  return '等你说';
};

export default {
  async render(el, { api, h, md, ui, toast, openChat, refresh }) {
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
    const draftWrap = h('div');

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
    const startRt = async () => {
      callBtn.disabled = true;
      chip.hidden = false; chip.textContent = '连接中';
      rtLog.replaceChildren();
      box.hidden = true;
      try {
        const call = await startCall({
          onStatus: (m) => { chip.textContent = DOING_NOW(m); },
          onUser: (t) => line('user', t),
          onReply: (t) => line('fast', t),
          onSlow: (t) => line('slow', md(t)),
          onFallback: (why) => { toast(why); setTimeout(() => box.querySelector('.mic')?.click(), 0); },
          onEnd: () => endRt(),
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
      ui.pageHead('讨论', '把没想清楚的事说出来。这里只讨论，不改数据；要留下的结论，整理确认后再保存'),
      callWrap,
      box,
      ui.chips(OPENERS.map((t) => ({ label: t, onClick: () => box.setValue(t) }))),
      draftWrap,
    );

    const showDraft = (s) => {
      draftWrap.replaceChildren();
      const title = h('input', { type: 'text', value: s.title });
      const content = h('textarea', { value: s.content });
      const steps = s.next_steps.map((t) => ({ check: h('input', { type: 'checkbox', checked: true }), text: h('input', { type: 'text', value: t }) }));
      const save = h('button.primary', { onclick: async () => {
        save.disabled = true;
        try {
          const r = await api.post(`/api/talk/summaries/${s.id}/save`, { title: title.value, content: content.value,
            next_steps: steps.filter((x) => x.check.checked).map((x) => x.text.value) });
          toast(`已存入知识库${r.task_ids.length ? `，加了 ${r.task_ids.length} 件今天的事项` : ''}`);
          refresh();
        } catch (e) { toast('保存失败：' + e.message); save.disabled = false; }
      } }, s.next_steps.length ? '确认保存' : '存入知识库');
      draftWrap.append(ui.section('整理结果', '改好再存，不存就不会写入'), h('div.card.talk-draft', {}, [
        title, content,
        steps.length ? h('div.muted', {}, '勾选的下一步会加到今天的事项') : null,
        ...steps.map((x) => h('label', {}, [x.check, x.text])),
        h('div.acts', {}, [save, h('button.ghost', { onclick: () => draftWrap.replaceChildren() }, '先不存')]),
      ]));
      draftWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const organize = async (id, btn) => {
      btn.disabled = true; btn.textContent = '整理中…';
      try {
        showDraft(await api.post('/api/talk/organize', { session_id: id }));
      } catch (e) { toast('整理失败：' + e.message); }
      btn.disabled = false; btn.textContent = '整理';
    };

    const [sessions, saved] = await Promise.all([api.get('/api/chat/talk/sessions'), api.get('/api/talk/summaries?limit=50')]);
    const savedOf = (id) => saved.find((s) => s.session_id === id && s.saved_at);
    const pendingOf = (id) => saved.find((s) => s.session_id === id && !s.saved_at);
    if (!sessions.length) { el.append(ui.empty('还没有讨论', '说一句话就能开始')); return; }
    el.append(ui.section('最近的讨论'), h('div.card', {}, sessions.slice(0, 20).map((s) => {
      const btn = h('button.sm', { onclick: () => organize(s.id, btn) }, '整理');
      const draft = !savedOf(s.id) && pendingOf(s.id);
      return h('div.talk-row', {}, [
        h('a.t', { href: '#talk', onclick: (e) => { e.preventDefault(); open(s.id); } }, s.title || '讨论'),
        h('span.muted', {}, (s.updated_at || '').slice(5, 16).replace('T', ' ')),
        savedOf(s.id) ? h('span.muted', {}, '已保存') : null,
        draft ? h('button.sm.ghost', { onclick: () => showDraft(draft) }, '看草稿') : null,
        btn,
      ]);
    })));
  },
};
