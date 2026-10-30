// 板块页面模板：export default { render(container, ctx) }
export default {
  async render(el, { api, h }) {
    const notes = await api.get('/api/_example/notes');
    el.append(h('div.card', {}, notes.map((n) => h('div.item', {}, n.text))));
  },
};
