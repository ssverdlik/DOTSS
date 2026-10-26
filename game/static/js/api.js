let audioCtx = null;
function ensureAudio() {
  if (!audioCtx) { try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; } }
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

// Специальный обработчик для разблокировки звука на iOS
function unlockAudio() {
  if (!audioCtx) {
    try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume().then(() => {
      // Воспроизводим пустой звук для разблокировки
      const buffer = audioCtx.createBuffer(1, 1, 22050);
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(audioCtx.destination);
      source.start(0);
    });
  }
}
// Добавляем оба события для надежности
document.addEventListener('touchstart', unlockAudio, { once: true });
document.addEventListener('pointerdown', unlockAudio, { once: true });

function playSound(type) {
  if (state.muted) return;
  const ctx = ensureAudio(); if (!ctx) return;
  const now = ctx.currentTime;
  const master = ctx.createGain(); master.gain.value = 0.13; master.connect(ctx.destination);
  const tone = (freq, opts = {}) => {
    const { type = 'sine', start = now, dur = 0.15, vol = 0.5, freqEnd = null } = opts;
    const osc = ctx.createOscillator(); const g = ctx.createGain();
    osc.type = type; osc.frequency.setValueAtTime(freq, start);
    if (freqEnd !== null) osc.frequency.exponentialRampToValueAtTime(freqEnd, start + dur * 0.9);
    g.gain.setValueAtTime(0, start); g.gain.linearRampToValueAtTime(vol, start + 0.012);
    g.gain.exponentialRampToValueAtTime(0.001, start + dur);
    osc.connect(g).connect(master); osc.start(start); osc.stop(start + dur + 0.02);
  };
  switch (type) {
    case 'select': tone(880, { dur: 0.07, vol: 0.35 }); break;
    case 'expand': tone(400, { freqEnd: 900, dur: 0.16, vol: 0.45 }); break;
    case 'powerup': tone(320, { type: 'triangle', freqEnd: 1200, dur: 0.22, vol: 0.4 }); break;
    case 'attack':
      tone(220, { type: 'sawtooth', freqEnd: 60, dur: 0.22, vol: 0.5 });
      { const buf = ctx.createBuffer(1, 2048, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
        const noise = ctx.createBufferSource(); noise.buffer = buf;
        const ng = ctx.createGain(); ng.gain.setValueAtTime(0.12, now);
        ng.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
        noise.connect(ng).connect(master); noise.start(now); noise.stop(now + 0.12); }
      break;
    case 'capture':
      tone(600, { type: 'triangle', dur: 0.3, vol: 0.4 });
      tone(900, { type: 'triangle', start: now + 0.1, dur: 0.3, vol: 0.35 });
      tone(1200, { type: 'triangle', start: now + 0.2, dur: 0.4, vol: 0.3 }); break;
    case 'income':
      tone(700, { type: 'sine', dur: 0.15, vol: 0.3 });
      tone(1050, { type: 'sine', start: now + 0.1, dur: 0.25, vol: 0.3 }); break;
    case 'surrender':
      tone(400, { type: 'sine', freqEnd: 150, dur: 0.6, vol: 0.4 }); break;
    case 'error': tone(160, { type: 'square', dur: 0.12, vol: 0.3 }); break;
    case 'turn_end':
      tone(523, { dur: 0.45, vol: 0.25 });
      tone(659, { start: now + 0.08, dur: 0.45, vol: 0.22 });
      tone(784, { start: now + 0.16, dur: 0.45, vol: 0.2 }); break;
    case 'win':
      tone(523, { type: 'triangle', dur: 0.5, vol: 0.35 });
      tone(659, { type: 'triangle', start: now + 0.12, dur: 0.5, vol: 0.35 });
      tone(784, { type: 'triangle', start: now + 0.24, dur: 0.5, vol: 0.35 });
      tone(1047, { type: 'triangle', start: now + 0.36, dur: 0.7, vol: 0.4 }); break;
    case 'lose': tone(440, { type: 'sine', freqEnd: 220, dur: 0.5, vol: 0.3 }); break;
  }
}

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) {
    let msg = 'Ошибка';
    try { msg = (await r.json()).detail; } catch {}
    throw new Error(msg);
  }
  return r.json();
}