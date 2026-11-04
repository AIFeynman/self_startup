// 讨论：说出想法，Agent 在右侧对话面板里帮忙理思路、给建议（只读）；讨论完「整理」，确认后再存。
const OPENERS = ['我有个想法想理一理：', '帮我想想这件事该不该做：', '我卡在一个问题上：'];

export default {
  async render(el, { api, h, md, ui, toast, openChat, refresh }) {
    const start = (text) => openChat({ module: 'talk', title: '讨论', fresh: true, send: text });
    const open = (id) => openChat({ module: 'talk', title: '讨论', sessionId: id });
    const box = ui.composer({
      placeholder: '说出你在想的事，或者打字…',
      hint: '点麦克风开始说，再点一下结束，说完自动发送',
      voiceAutoSend: true,
      onSubmit: (t) => { start(t); },
    });
    const draftWrap = h('div');
    el.append(
      ui.pageHead('讨论', '把没想清楚的事说出来。这里只讨论，不改数据；要留下的结论，整理确认后再保存'),
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
