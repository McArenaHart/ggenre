(function (scope) {
  'use strict';
  function plan(config, rate, frames) {
    if (!Array.isArray(config.sections) || config.sections.length !== 3) throw new Error('Choose an intro, middle and outro.');
    const fade = Number(config.crossfade_ms);
    if (!Number.isFinite(fade) || fade < 0 || fade > 500) throw new Error('Use a crossfade from 0 to 500 ms.');
    const parts = config.sections.map(part => {
      const start = Math.round(Number(part.start) * rate), end = Math.round(Number(part.end) * rate), gain = Number(part.gain);
      if (![start, end, gain].every(Number.isFinite) || start < 0 || end > frames || end - start < Math.ceil(rate * .1) || gain < 0 || gain > 1) throw new Error('Each part needs at least 0.1 seconds inside the source. Volume must be 0–100%.');
      return {start, end, gain};
    });
    const fades = [0, 1].map(i => Math.min(Math.round(fade * rate / 1000), Math.floor((parts[i].end - parts[i].start) / 2), Math.floor((parts[i + 1].end - parts[i + 1].start) / 2)));
    const length = parts.reduce((sum, part) => sum + part.end - part.start, 0) - fades[0] - fades[1];
    if (length > rate * 360) throw new Error('Keep the joined instrumental within six minutes.');
    return {parts, fades, length};
  }
  if (typeof module !== 'undefined') module.exports = {plan};
  scope.StudioExtractArrange = {plan};
  if (typeof document === 'undefined') return;
  const root = document.getElementById('extract-arranger');
  if (!root) return;
  const state = JSON.parse(document.getElementById('extract-config').textContent);
  const get = id => document.getElementById(id), rate = Number(root.dataset.rate);
  const status = get('extract-status'), original = get('extract-original'), preview = get('extract-preview-player');
  const rows = [], sourceUrl = root.dataset.source;
  let buffer, peaks, url, busy = false, dirty = false;
  const draftKey = 'ggenre-extract-draft:' + sourceUrl;
  const saveDraft = () => {
    try { localStorage.setItem(draftKey, JSON.stringify({base: root.dataset.revision, state, title: get('extract-title').value})); }
    catch (_) { status.textContent = 'Local recovery is unavailable. Keep this tab open until you save.'; }
  };
  const pause = () => { original.pause(); preview.pause(); };
  original.addEventListener('play', () => preview.pause());
  preview.addEventListener('play', () => original.pause());
  function update() {
    let valid = !!buffer;
    try {
      if (buffer) { const result = plan(state, rate, buffer.length); get('extract-duration').textContent = `Joined length: ${(result.length / rate).toFixed(2)} seconds · Intro → Middle → Outro · ${state.crossfade_ms} ms joins`; }
    } catch (error) { valid = false; status.textContent = error.message; }
    get('extract-preview').disabled = busy || !valid;
    get('extract-save').disabled = busy || !valid;
    if (get('extract-use')) get('extract-use').disabled = busy || dirty;
    root.querySelectorAll('input, select, [data-section-play]').forEach(input => { input.disabled = busy; });
    get('extract-load').disabled = busy;
  }
  function changed() {
    dirty = true; pause(); preview.hidden = true;
    if (url) { URL.revokeObjectURL(url); url = null; preview.removeAttribute('src'); }
    status.textContent = 'Edits ready. Preview the joins, then save your joined instrumental.';
    rows.forEach(draw); update();
    saveDraft();
  }
  function draw(row) {
    const canvas = row.canvas, ctx = canvas.getContext('2d'), part = state.sections[row.index];
    const w = canvas.width, h = canvas.height, duration = buffer.duration;
    ctx.clearRect(0, 0, w, h);
    const left = part.start / duration * w, right = part.end / duration * w;
    ctx.fillStyle = '#43c6b52d'; ctx.fillRect(left, 0, right - left, h);
    ctx.strokeStyle = '#aab5d2'; ctx.beginPath();
    peaks.forEach((peak, i) => { const x = i / peaks.length * w, size = peak * h * .45; ctx.moveTo(x, h / 2 - size); ctx.lineTo(x, h / 2 + size); }); ctx.stroke();
    ctx.fillStyle = '#55e0ca'; ctx.fillRect(left, 0, 4, h); ctx.fillRect(Math.max(0, right - 4), 0, 4, h);
    row.start.value = Number(part.start).toFixed(3); row.end.value = Number(part.end).toFixed(3);
    row.volume.textContent = `${Math.round(part.gain * 100)}%`;
  }
  function makeRows() {
    ['Intro', 'Middle', 'Outro'].forEach((name, index) => {
      const card = document.createElement('section'); card.className = 'extract-part';
      const heading = document.createElement('h2'); heading.textContent = `${index + 1}. ${name}`; card.append(heading);
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 110; canvas.setAttribute('aria-label', `${name} source waveform; use the start and end controls for exact times.`); card.append(canvas);
      const row = {index, canvas};
      for (const [key, title] of [['start', 'Start (seconds)'], ['end', 'End (seconds)'], ['gain', 'Volume']]) {
        const label = document.createElement('label'); label.textContent = `${name} ${title}`;
        const input = document.createElement('input'); input.type = key === 'gain' ? 'range' : 'number'; input.min = '0'; input.max = key === 'gain' ? '1' : String(buffer.duration); input.step = key === 'gain' ? '.01' : '.001'; input.value = state.sections[index][key];
        label.append(input); card.append(label); row[key] = input;
        if (key === 'gain') { row.volume = document.createElement('output'); label.append(row.volume); }
        input.addEventListener('input', () => { state.sections[index][key] = input.value === '' ? NaN : Number(input.value); changed(); });
      }
      const listen = document.createElement('button'); listen.type = 'button'; listen.className = 'studio-button studio-outline'; listen.textContent = `Preview ${name}`; listen.dataset.sectionPlay = 'true';
      listen.addEventListener('click', () => run(() => renderPreview(index))); card.append(listen);
      let handle;
      function drag(event) {
        if (!handle || busy) return;
        const bounds = canvas.getBoundingClientRect(), part = state.sections[index];
        const value = Math.max(0, Math.min(buffer.duration, (event.clientX - bounds.left) / bounds.width * buffer.duration));
        part[handle] = handle === 'start' ? Math.min(value, part.end - .1) : Math.max(value, part.start + .1);
        changed();
      }
      canvas.addEventListener('pointerdown', event => {
        if (busy) return;
        const bounds = canvas.getBoundingClientRect(), seconds = (event.clientX - bounds.left) / bounds.width * buffer.duration, part = state.sections[index];
        handle = Math.abs(seconds - part.start) <= Math.abs(seconds - part.end) ? 'start' : 'end'; canvas.setPointerCapture(event.pointerId); drag(event);
      });
      canvas.addEventListener('pointermove', drag);
      for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(event, () => { handle = null; });
      rows.push(row); get('extract-sections').append(card); draw(row);
    });
  }
  async function run(action) {
    if (busy) return;
    busy = true; update();
    try { await action(); } catch (error) { status.textContent = error.message || 'Unable to prepare this instrumental.'; }
    finally { busy = false; update(); }
  }
  async function renderPreview(index = null) {
    pause(); status.textContent = 'Preparing your preview…';
    const result = plan(state, rate, buffer.length);
    const parts = index === null ? result.parts : [result.parts[index]], fades = index === null ? result.fades : [];
    const length = parts.reduce((sum, p) => sum + p.end - p.start, 0) - fades.reduce((sum, n) => sum + n, 0);
    const offline = new OfflineAudioContext(2, length, rate);
    let position = 0;
    parts.forEach((part, i) => {
      const node = offline.createBufferSource(), gain = offline.createGain(), time = position / rate, duration = (part.end - part.start) / rate;
      node.buffer = buffer; node.connect(gain).connect(offline.destination);
      gain.gain.setValueAtTime(part.gain, time);
      if (i > 0 && fades[i - 1]) { gain.gain.setValueAtTime(0, time); gain.gain.linearRampToValueAtTime(part.gain, time + fades[i - 1] / rate); }
      if (i < parts.length - 1 && fades[i]) { gain.gain.setValueAtTime(part.gain, time + duration - fades[i] / rate); gain.gain.linearRampToValueAtTime(0, time + duration); }
      node.start(time, part.start / rate, duration); position += part.end - part.start - (fades[i] || 0);
    });
    const audio = await offline.startRendering();
    // Browser preview uses a PCM WAV, matching the saved sample rate and length.
    const bytes = new ArrayBuffer(44 + audio.length * 4), view = new DataView(bytes);
    function word(at, text) { [...text].forEach((char, i) => view.setUint8(at + i, char.charCodeAt(0))); }
    word(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); word(8, 'WAVE'); word(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 2, true); view.setUint32(24, rate, true); view.setUint32(28, rate * 4, true); view.setUint16(32, 4, true); view.setUint16(34, 16, true); word(36, 'data'); view.setUint32(40, audio.length * 4, true);
    const channels = [audio.getChannelData(0), audio.getChannelData(1)];
    for (let i = 0; i < audio.length; i++) for (let c = 0; c < 2; c++) { const value = Math.max(-1, Math.min(1, channels[c][i])); view.setInt16(44 + i * 4 + c * 2, value * (value < 0 ? 32768 : 32767), true); }
    if (url) URL.revokeObjectURL(url);
    url = URL.createObjectURL(new Blob([bytes], {type: 'audio/wav'})); preview.src = url; preview.hidden = false;
    await preview.play(); status.textContent = index === null ? 'Playing your intro, middle and outro as one continuous extract.' : 'Playing the selected section.';
  }
  get('extract-load').addEventListener('click', () => run(async () => {
    status.textContent = 'Loading the original waveform…';
    const response = await fetch(sourceUrl, {cache: 'no-store'});
    if (!response.ok) throw new Error('This source is unavailable. Reload the library and try again.');
    buffer = await new OfflineAudioContext(2, 1, rate).decodeAudioData(await response.arrayBuffer());
    const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
    peaks = Array.from({length: 640}, (_, bin) => {
      let peak = 0; for (let i = Math.floor(bin * buffer.length / 640); i < Math.floor((bin + 1) * buffer.length / 640); i++) for (const channel of channels) peak = Math.max(peak, Math.abs(channel[i])); return peak;
    });
    makeRows(); get('extract-load').hidden = true; status.textContent = 'Drag the handles or enter times to shape each section.';
  }));
  get('extract-fade').value = String(state.crossfade_ms);
  get('extract-fade').addEventListener('change', event => { state.crossfade_ms = Number(event.target.value); changed(); });
  get('extract-title').addEventListener('input', changed);
  get('extract-preview').addEventListener('click', () => run(() => renderPreview()));
  get('extract-save').addEventListener('click', () => run(async () => {
    plan(state, rate, buffer.length); pause(); status.textContent = 'Saving your joined instrumental…';
    const data = new FormData(); data.append('title', get('extract-title').value); data.append('revision', root.dataset.revision); data.append('config', JSON.stringify(state));
    const response = await fetch(root.dataset.save, {method: 'POST', headers: {'X-CSRFToken': root.querySelector('[name=csrfmiddlewaretoken]').value}, body: data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save this arrangement.');
    dirty = false; try { localStorage.removeItem(draftKey); } catch (_) {} location.href = result.url;
  }));
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pagehide', () => { if (url) URL.revokeObjectURL(url); });
  try {
    const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
    if (draft && draft.base === root.dataset.revision && Array.isArray(draft.state?.sections) && draft.state.sections.length === 3) {
      const panel = document.createElement('div'), label = document.createElement('p');
      label.textContent = 'Unsaved section edits are available on this browser.'; panel.append(label);
      for (const restore of [true, false]) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'studio-button studio-outline';
        button.textContent = restore ? 'Restore section edits' : 'Discard local copy';
        button.addEventListener('click', () => {
          if (restore) { Object.assign(state, draft.state); get('extract-title').value = draft.title; get('extract-fade').value = String(state.crossfade_ms); changed(); }
          else localStorage.removeItem(draftKey);
          panel.remove();
        }); panel.append(button);
      } status.before(panel);
    }
  } catch (_) {}
  update();
})(typeof window === 'undefined' ? globalThis : window);
