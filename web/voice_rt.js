// 快慢思考通话：麦克风 16k PCM 发给服务端，收 24k PCM 播放；开口时服务端发 clear，立刻停播。
// startCall({ onReady, onStatus, onUser, onReply, onSlow, onFallback, onEnd, onMetrics }) → { hangup() }
const FRAME = 1024;
const OUT_RATE = 24000;
const LOUD = 0.03; // 播放时麦克风超过这个响度算开口。服务端判定要一秒左右，这里先压低声音，打断才跟手
const LOUD_FRAMES = 2;
const DUCK_MS = 1500; // 压低后这么久服务端没确认，算误判，声音恢复

export async function startCall({ onReady, onStatus, onUser, onReply, onSlow, onFallback, onEnd, onMetrics }) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const mic = new AudioContext({ sampleRate: 16000 });
  const out = new AudioContext({ sampleRate: OUT_RATE });
  if (mic.state === 'suspended') mic.resume();
  if (out.state === 'suspended') out.resume();
  const src = mic.createMediaStreamSource(stream);
  const node = mic.createScriptProcessor(FRAME, 1, 1);
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/voice/rt`);
  ws.binaryType = 'arraybuffer';

  const gain = out.createGain();
  gain.connect(out.destination);
  let playing = [], nextAt = 0, closed = false, fellBack = false, loud = 0, duckTimer = null, duckAt = 0;
  const unduck = () => { clearTimeout(duckTimer); duckTimer = null; gain.gain.value = 1; };
  const duck = () => {
    if (duckTimer) return;
    gain.gain.value = 0;
    duckAt = performance.now();
    duckTimer = setTimeout(unduck, DUCK_MS);
    onMetrics?.({ ducked: true });
  };
  const clear = () => { playing.forEach((s) => { try { s.stop(); } catch { /* 已经放完 */ } }); playing = []; nextAt = 0; unduck(); };
  const play = (buf) => {
    const pcm = new Int16Array(buf);
    const audio = out.createBuffer(1, pcm.length, OUT_RATE);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const s = out.createBufferSource();
    s.buffer = audio; s.connect(gain);
    nextAt = Math.max(out.currentTime + 0.02, nextAt);
    s.start(nextAt); nextAt += audio.duration;
    playing.push(s);
    s.onended = () => { playing = playing.filter((x) => x !== s); };
  };
  const finish = () => {
    if (closed) return;
    closed = true;
    node.onaudioprocess = null;
    node.disconnect(); src.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    clear(); mic.close(); out.close();
    if (ws.readyState <= WebSocket.OPEN) ws.close();
    onEnd?.();
  };

  node.onaudioprocess = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    const x = e.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(x.length);
    let sum = 0;
    for (let i = 0; i < x.length; i++) { pcm[i] = Math.max(-1, Math.min(1, x[i])) * 32767; sum += x[i] * x[i]; }
    ws.send(pcm.buffer);
    loud = Math.sqrt(sum / x.length) > LOUD && nextAt > out.currentTime ? loud + 1 : 0;
    if (loud >= LOUD_FRAMES) duck();
  };
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return play(e.data);
    const m = JSON.parse(e.data);
    if (m.type === 'clear') { if (duckTimer) onMetrics?.({ barge_silent_ms: performance.now() - duckAt }); clear(); }
    else if (m.type === 'ready') onReady?.(m);
    else if (m.type === 'status') onStatus?.(m);
    else if (m.type === 'user') onUser?.(m.text);
    else if (m.type === 'reply') onReply?.(m.text);
    else if (m.type === 'slow') onSlow?.(m.text);
    else if (m.type === 'metrics') onMetrics?.(m);
    else if (m.type === 'fallback') { fellBack = true; onFallback?.(m.reason); finish(); }
    else if (m.type === 'end') finish();
  };
  ws.onclose = () => { if (!closed && !fellBack) { onFallback?.('实时通话断了，切回本地'); } finish(); };
  src.connect(node); node.connect(mic.destination); // 不接到输出 onaudioprocess 不跑；输出缓冲是空的，不会放出声
  return { hangup: () => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'hangup' })); fellBack = true; finish(); } };
}
