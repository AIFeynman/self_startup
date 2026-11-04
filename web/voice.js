// 语音：边说边转文字、停顿切句、朗读回复、开口打断。音频只在本机流转，转完即删。
// micButton({ icon, call, onLive(text), onFinal(text), onHint(text), onCall(on) })：不支持录音的环境返回 null
//   call=true 是通话：一直听，每句说完交给 onFinal；否则是听写，文字留在输入框里改
import { h } from './api.js';

const PAUSE_S = 0.8;        // 停这么久算一句说完
const ONSET_FRAMES = 3;     // 连续这么多帧够响才算开口（约 0.2 秒）
const PREROLL_FRAMES = 5;   // 开口前多留一点，不吃掉第一个字
const MIN_VOICED_S = 0.3;
const FIRST_PARTIAL_S = 0.2;
const PARTIAL_GAP_S = 0.2;  // 上次结果回来后隔这么久再转，模型约半秒一次
const SETTLE_S = 0.25;      // 静了这么久就提前转一次；真停下了，到点直接用这次的结果，不用再等一轮
const FREEZE_S = 14;        // 一句太长就先定下前面，只重转后面，不会越转越慢
const FREEZE_MIN_S = 8;
const MIN_LEVEL = 0.006;
const IDLE_S = 600;
const ECHO_TAIL_S = 0.6;    // 放完后房间里还有余音

let current = null; // 同一时间只开一路麦克风
export const voiceBusy = () => !!current;
export const inCall = () => !!current?.call;

// ---------- 朗读：按句排队，放在页面里播（浏览器的回声消除才消得掉），本机合成失败退回系统语音 ----------
let queue = [], cur = null, synthing = null, paused = false, lastEnd = 0;
let recent = [];    // 最近念过的句子，用来认出麦克风听到的是自己的声音
let spokenTurn = false;

function advance(job) {
  if (job.el) URL.revokeObjectURL(job.el.src);
  if (cur !== job) return;
  cur = null; lastEnd = performance.now();
  pump();
}
function playJob(job) {
  if (!spokenTurn) { spokenTurn = true; performance.mark('tts-first-play'); }
  job.el.play().catch(() => advance(job));
}
// 按顺序一次合成一句，只提前备两句：第一句不被后面的句子抢，打断后也不用等一长串合成完
function synthNext() {
  if (synthing) return;
  const job = [cur, ...queue].filter(Boolean).slice(0, 3).find((j) => !j.started);
  if (!job) return;
  job.started = true; synthing = job;
  job.abort = new AbortController();
  fetch('/api/voice/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: job.text }), signal: job.abort.signal })
    .then((r) => (r.ok ? r.blob() : null)).catch(() => null)
    .then((blob) => { job.resolve(blob); if (synthing === job) { synthing = null; synthNext(); } });
}
async function pump() {
  synthNext();
  if (cur || paused || !queue.length) return;
  const job = cur = queue.shift();
  synthNext();
  recent = [...recent.slice(-2), job.text];
  const blob = await job.blob;
  if (cur !== job) return;
  if (!blob) {
    if (!('speechSynthesis' in window)) return advance(job);
    const u = new SpeechSynthesisUtterance(job.text);
    u.lang = 'zh-CN'; u.onend = u.onerror = () => advance(job);
    job.utterance = u;
    speechSynthesis.speak(u);
    return;
  }
  job.el = new Audio(URL.createObjectURL(blob));
  job.el.onended = job.el.onerror = () => advance(job);
  if (!paused) playJob(job);
}
export const tts = {
  say(text) {
    const job = { text };
    job.blob = new Promise((resolve) => { job.resolve = resolve; });
    queue.push(job); // 边生成边合成，轮到时已经好了
    pump();
  },
  pause() {
    paused = true;
    cur?.el?.pause();
    if ('speechSynthesis' in window) speechSynthesis.pause();
  },
  resume() {
    paused = false;
    if ('speechSynthesis' in window) speechSynthesis.resume();
    if (cur?.el) playJob(cur); else pump();
  },
  stop() {
    synthing?.abort.abort(); synthing = null;
    queue = []; paused = false;
    const job = cur; cur = null;
    if (job) lastEnd = performance.now();
    job?.el?.pause();
    if (job?.el) URL.revokeObjectURL(job.el.src);
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  },
  newTurn() { spokenTurn = false; },
  active: () => !!cur || queue.length > 0,
  audible: () => !!cur || queue.length > 0 || performance.now() - lastEnd < ECHO_TAIL_S * 1000,
};

// 回复的文字流 → 一句句念。逗号处也切，长句不用等到句号才开口；第一段切得更短，合成时间短，开口更快
export function sentenceFeed(say) {
  let buf = '', inCode = false, spoke = false;
  const clean = (t) => t.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`#>|]/g, '').trim();
  const emit = (t) => {
    const fences = (t.match(/```/g) || []).length;
    const skip = inCode || fences > 0;
    if (fences % 2) inCode = !inCode;
    const text = clean(t);
    if (!skip && /[\p{L}\p{N}]/u.test(text)) { spoke = true; say(text); }
  };
  return {
    feed(delta) {
      buf += delta;
      for (;;) {
        const m = buf.match(/^[\s\S]*?(?:[。！？；!?;\n]+|[，,](?=[\s\S]))/);
        if (!m) return;
        if (/[，,]$/.test(m[0]) && m[0].length < (spoke ? 30 : 4)) {
          const hard = buf.match(/^[\s\S]*?[。！？；!?;\n]+/);
          if (!hard) return;
          buf = buf.slice(hard[0].length); emit(hard[0]);
          continue;
        }
        buf = buf.slice(m[0].length); emit(m[0]);
      }
    },
    flush() { if (buf) emit(buf); buf = ''; },
  };
}

// 听到的是不是自己念的：两个字一组，和最近念过的句子重合过半就算
function isEcho(text) {
  const norm = (t) => t.replace(/[^\p{L}\p{N}]/gu, '');
  const said = norm(recent.join('')), t = norm(text);
  if (t.length < 2 || !said) return false;
  let hit = 0;
  for (let i = 0; i < t.length - 1; i++) if (said.includes(t.slice(i, i + 2))) hit++;
  return hit / (t.length - 1) >= 0.5;
}

function wavOf(chunks, rate) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const n = Math.floor(total * 16000 / rate);
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, n * 2, true);
  let ci = 0, off = 0;
  for (let i = 0; i < n; i++) {
    const at = Math.floor(i * rate / 16000);
    while (at - off >= chunks[ci].length) { off += chunks[ci].length; ci++; }
    v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, chunks[ci][at - off])) * 32767, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

async function decode(chunks, rate) {
  const r = await fetch('/api/voice/live', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wavOf(chunks, rate) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `转写失败 ${r.status}`);
  return d.text || '';
}

export function micButton({ icon, call = false, onLive, onFinal, onHint, onCall }) {
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) return null;
  const listening = call ? '通话中：直接说，停一下就发送；回复朗读时开口就打断。再点结束' : '正在听：说的话直接进输入框，改好再发。再点结束';
  const btn = h('button.mic', { type: 'button', title: call ? '语音通话：点一下开始，再点一下结束' : '语音输入：点一下开始说，再点一下结束', onclick: () => (self ? stop() : start()) }, icon('mic'));
  let self = null, hintTimer;
  const flash = (t) => { onHint(t); clearTimeout(hintTimer); hintTimer = setTimeout(() => onHint(''), 4000); };

  function stop(discard = false) {
    if (!self) return;
    const s = self;
    self = null; current = null;
    btn.classList.remove('rec');
    document.removeEventListener('keydown', s.onKey);
    s.node.onaudioprocess = null;
    s.node.disconnect(); s.src.disconnect();
    s.stream.getTracks().forEach((t) => t.stop());
    s.ctx.close();
    if (call) tts.stop();
    if (!discard && s.endUtterance) s.endUtterance();
    onCall?.(false);
    onHint('');
  }

  async function start() {
    if (current) return flash('另一个输入框正在听');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      return flash(e.name === 'NotAllowedError' ? '麦克风没有授权，在浏览器地址栏左侧打开' : '打不开麦克风：' + e.message);
    }
    fetch('/api/voice/prepare', { method: 'POST' }).then(async (r) => {
      if (r.ok) return;
      const d = await r.json().catch(() => ({}));
      stop(true); flash(d.detail || '语音输入用不了');
    }).catch(() => {});
    const ctx = new AudioContext({ sampleRate: 16000 });
    const rate = ctx.sampleRate;
    if (ctx.state === 'suspended') ctx.resume();
    const src = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(1024, 1, 1);
    const dt = 1024 / rate;
    let floor = MIN_LEVEL / 3, boost = 1; // boost：真听到过自己的声音（回声没消干净）就把朗读时的门槛再抬高
    let pre = [], run = 0, speech = false, chunks = [], voiced = 0, silent = 0, heard = 0, idle = 0;
    let frozen = [], shown = '', seq = 0, inflight = false, lastDone = 0, announced = false, tentative = false;
    let tail = Promise.resolve(), settled = null;

    const gate = () => Math.max(MIN_LEVEL, floor * 3) * (call && tts.audible() ? 2.5 * boost : 1);
    const failed = (e) => { stop(true); flash(e.message); };
    const interruptOnce = () => {
      if (announced || !call) return;
      announced = true;
      tts.stop();
      document.dispatchEvent(new Event('voice-interrupt'));
    };
    const dropAsEcho = () => {
      speech = false; chunks = []; frozen = []; seq++; tentative = false; settled = null;
      boost = Math.min(boost * 1.5, 6);
      tts.resume();
    };
    const show = (text) => {
      if (!self || !speech) return;
      if (tentative) {
        if (text.length < 2) return;
        if (isEcho(text)) return dropAsEcho();
        tentative = false;
      }
      if (!text) return;
      interruptOnce();
      if (!shown) performance.mark('first-text');
      shown = text;
      onLive(text);
    };
    const partial = () => {
      inflight = true;
      const mine = ++seq, parts = frozen;
      const job = decode(chunks.slice(), rate);
      if (silent >= SETTLE_S) settled = job;
      job.then(async (t) => {
        inflight = false; lastDone = heard;
        if (mine !== seq) return;
        const head = await Promise.all(parts);
        if (mine === seq) show([...head, t].filter(Boolean).join('，'));
      }).catch((e) => { inflight = false; failed(e); });
    };
    const freeze = () => { // 在最安静的地方切开：前面定稿，后面接着转
      const levels = chunks.map((c) => Math.sqrt(c.reduce((a, x) => a + x * x, 0) / c.length));
      const lo = Math.floor(FREEZE_MIN_S / dt);
      const cut = lo + levels.slice(lo).indexOf(Math.min(...levels.slice(lo)));
      frozen = [...frozen, decode(chunks.slice(0, cut), rate)];
      chunks = chunks.slice(cut); seq++;
    };
    const endUtterance = () => {
      if (!speech) return;
      speech = false;
      performance.mark('speech-end');
      const parts = voiced >= MIN_VOICED_S ? [...frozen, settled || decode(chunks.slice(), rate)] : [];
      const wasTentative = tentative, wasAnnounced = announced;
      chunks = []; frozen = []; seq++; tentative = false; shown = ''; settled = null;
      tail = tail.then(() => Promise.all(parts)).then((texts) => {
        const text = texts.filter(Boolean).join('，');
        if (wasTentative && (!text || isEcho(text))) { if (text) boost = Math.min(boost * 1.5, 6); tts.resume(); return; }
        if (text && !wasAnnounced) interruptOnce();
        performance.mark('final-text');
        onFinal(text);
      }).catch(failed);
    };

    node.onaudioprocess = (e) => {
      if (!btn.isConnected) return stop(true);
      const x = new Float32Array(e.inputBuffer.getChannelData(0));
      const level = Math.sqrt(x.reduce((a, v) => a + v * v, 0) / x.length);
      if (!speech) {
        floor = level < floor ? floor * 0.9 + level * 0.1 : floor * 0.995 + level * 0.005;
        pre.push(x); if (pre.length > PREROLL_FRAMES) pre.shift();
        run = level > gate() ? run + 1 : 0;
        idle += dt;
        if (idle > IDLE_S) { stop(true); return flash('很久没听到说话，已结束'); }
        if (run < ONSET_FRAMES) return;
        performance.mark('speech-start');
        speech = true; chunks = pre; pre = []; run = 0; voiced = dt * ONSET_FRAMES; silent = 0; heard = 0; lastDone = 0; idle = 0;
        announced = false; shown = ''; frozen = [];
        tentative = call && tts.audible(); // 可能是自己的声音：先暂停，等转出文字再判断
        if (tentative) { performance.mark('tts-paused'); tts.pause(); }
        return;
      }
      chunks.push(x); heard += dt;
      if (level > gate() * 0.7) { voiced += dt; silent = 0; settled = null; } else silent += dt;
      if (silent >= PAUSE_S) return endUtterance();
      if (chunks.length * dt > FREEZE_S) freeze();
      if (!inflight && !settled && heard >= FIRST_PARTIAL_S && (heard - lastDone >= PARTIAL_GAP_S || silent >= SETTLE_S)) partial();
    };
    src.connect(node); node.connect(ctx.destination); // 不接到输出 onaudioprocess 不跑；输出缓冲是空的，不会放出声
    const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); stop(true); } };
    document.addEventListener('keydown', onKey);
    self = current = { call, stream, ctx, src, node, onKey, endUtterance };
    btn.classList.add('rec');
    onHint(listening);
    onCall?.(true);
  }
  return btn;
}
