import { api, h, toast } from './api.js';

const style = h('style', {}, `
.image-picker { display: grid; gap: 6px; }
.image-picker .image-list, .chat-image-list { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0; }
.image-picker figure { position: relative; margin: 0; }
.image-picker img, .chat-image-list img { max-width: 120px; height: 86px; object-fit: contain; border: 1px solid var(--line); border-radius: 6px; }
.image-picker figure button { position: absolute; right: 0; top: 0; padding: 0 5px; }
.chat-image-list a { display: inline-flex; }
`);
document.head.append(style);

export const imageList = (images = []) => h('div.chat-image-list', {}, images.map((img) => h('a', { href: img.url, target: '_blank', rel: 'noopener' }, h('img', { src: img.url, alt: img.name, title: img.name }))));

export function imagePicker({ label = '添加图片', onChange = () => {} } = {}) {
  let images = [], uploading = false;
  const list = h('div.image-list');
  const status = h('span.muted', {}, '支持粘贴、拖入 · PNG / JPEG / WebP');
  const input = h('input', { type: 'file', multiple: true, accept: 'image/png,image/jpeg,image/webp', 'aria-label': label, hidden: true });
  const button = h('button.ghost', { type: 'button', onclick: () => input.click() }, '添加图片');
  const draw = () => {
    list.replaceChildren(...images.map((img) => h('figure', {}, [h('img', { src: img.url, alt: img.name }),
      h('button', { type: 'button', title: '移除图片', onclick: () => { images = images.filter((x) => x.id !== img.id); draw(); onChange(); } }, '×')])));
  };
  const add = async (files) => {
    if (uploading) return toast('图片正在添加，请稍等', true);
    if (images.length + files.length > 4) return toast('每次最多添加 4 张图片', true);
    uploading = true; button.disabled = true; status.textContent = '正在添加图片…'; onChange();
    try {
      for (const file of files) {
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('请选择 PNG、JPEG 或 WebP 图片');
        if (file.size > 8 * 1024 * 1024) throw new Error('每张图片不能超过 8 MB');
        const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
        images.push(await api.post('/api/chat/images', { name: file.name, data }));
        draw();
      }
    } catch (e) { toast(e.message || '图片添加失败', true); }
    finally { uploading = false; button.disabled = false; input.value = ''; status.textContent = '支持粘贴、拖入 · 每张最多 8 MB，共 4 张'; onChange(); }
  };
  input.addEventListener('change', () => add([...input.files]));
  const el = h('div.image-picker', {}, [h('div.row', {}, [button, status, input]), list]);
  return {
    el, value: () => images.map((img) => img.id), images: () => [...images], get busy() { return uploading; },
    clear: () => { images = []; draw(); onChange(); },
    restore: (saved) => { images = [...saved]; draw(); onChange(); },
    bind: (target) => {
      target.addEventListener('paste', (e) => { const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/')); if (files.length) { e.preventDefault(); add(files); } });
      target.addEventListener('dragover', (e) => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });
      target.addEventListener('drop', (e) => { const files = [...(e.dataTransfer?.files || [])]; if (files.length) { e.preventDefault(); add(files); } });
    },
  };
}
