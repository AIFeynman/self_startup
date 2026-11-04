// 语音输入：麦克风按钮。点一下开始录，再点一下结束，Esc 取消；录音发到本机转写，音频不留存。
// micButton({ icon, onText(text), onHint(text) })：不支持录音的环境返回 null
import { h } from './api.js';

const MAX_SECONDS = 600;
let current = null; // 同一时间只录一段

export const voiceBusy = () => !!current;

const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export function micButton({ icon, onText, onHint }) {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return null;
  let rec, stream, timer, seconds = 0, cancelled = false, busy = false, hintTimer;
  const btn = h('button.mic', { type: 'button', title: '语音输入：点一下开始说，再点一下结束', onclick: () => toggle() }, icon('mic'));
  const flash = (t) => { onHint(t); clearTimeout(hintTimer); hintTimer = setTimeout(() => onHint(''), 4000); };
  const onKey = (e) => { if (e.key === 'Escape' && rec?.state === 'recording') { e.preventDefault(); cancelled = true; rec.stop(); } };
  const finish = () => {
    clearInterval(timer);
    document.removeEventListener('keydown', onKey);
    stream?.getTracks().forEach((t) => t.stop());
    btn.classList.remove('rec');
    current = null;
  };

  async function upload(blob) {
    busy = true; btn.classList.add('wait'); onHint('正在转文字…');
    try {
      const r = await fetch('/api/voice/transcribe', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return flash(d.detail || `转写失败（${r.status}）`);
      if (!d.text) return flash('没听到说话，再试一次');
      onHint('');
      onText(d.text);
    } catch (e) {
      flash('转写失败：' + e.message);
    } finally {
      busy = false; btn.classList.remove('wait');
    }
  }

  async function toggle() {
    if (busy) return;
    if (rec?.state === 'recording') return rec.stop();
    if (current) return flash('另一个输入框正在录音');
    current = btn;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      current = null;
      return flash(e.name === 'NotAllowedError' ? '麦克风权限被拒绝，在浏览器设置里打开' : '打不开麦克风：' + e.message);
    }
    const chunks = [];
    rec = new MediaRecorder(stream);
    cancelled = false; seconds = 0;
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      finish();
      if (cancelled) return onHint('');
      upload(new Blob(chunks, { type: rec.mimeType }));
    };
    rec.start();
    document.dispatchEvent(new CustomEvent('voice-start'));
    document.addEventListener('keydown', onKey);
    btn.classList.add('rec');
    onHint('正在听… 0:00（再点一下结束，Esc 取消）');
    timer = setInterval(() => {
      seconds += 1;
      onHint(`正在听… ${fmt(seconds)}（再点一下结束，Esc 取消）`);
      if (seconds >= MAX_SECONDS) rec.stop();
    }, 1000);
  }
  return btn;
}
