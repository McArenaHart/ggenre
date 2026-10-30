/* Shared-clock playback and raw microphone capture. No external audio service. */
(function (scope) {
  "use strict";
  function segment(track, duration, position) {
    const start = Number(track.trim_start || 0), end = Number(track.trim_end) || duration;
    const offset = Number(track.offset || 0), gain = Number(track.gain);
    if (![start, end, offset, gain, position].every(Number.isFinite) || start < 0 || end <= start || end > duration + 0.02 || offset < 0 || gain < 0 || gain > 2 || position < 0 || position >= 300) {
      throw new Error("Check trim times, volume, and position for " + track.name);
    }
    const skipped = Math.max(0, position - offset);
    const length = Math.min(end, duration) - start - skipped;
    return track.muted || length <= 0 ? null : {delay: Math.max(0, offset - position), start: start + skipped, duration: Math.min(length, 300 - Math.max(position, offset)), gain};
  }
  function compensate(samples, sampleRate, milliseconds) {
    const frames = Math.round(milliseconds * sampleRate / 1000);
    if (frames >= samples.length) throw new Error("Take is shorter than the delay correction. Record longer or reduce correction.");
    if (frames >= 0) return samples.slice(frames);
    const output = new Float32Array(samples.length - frames); output.set(samples, -frames); return output;
  }
  function estimatedDelay(context, stream) {
    const input = stream.getAudioTracks()[0]?.getSettings?.().latency || 0;
    return Math.min(1000, Math.round(((context.baseLatency || 0) + (context.outputLatency || 0) + input) * 1000));
  }
  async function begin({context, stream, tracks, load, position, bpm, countIn, workletURL, onMeter, onProgress, onDone, onError, onCheckpoint = () => {}, channelSelection = "mix", destination = context.destination, captureTail = estimatedDelay(context, stream) / 1000}) {
    if (!context.audioWorklet || typeof AudioWorkletNode === "undefined") throw new Error("Synchronized recording requires a browser with AudioWorklet support over HTTPS or localhost.");
    await context.audioWorklet.addModule(workletURL);
    const backing = await Promise.all(tracks.map(async track => {
      const buffer = await load(track); return {buffer, plan: segment(track, buffer.duration, position)};
    }));
    if(stream.getAudioTracks()[0]?.readyState === "ended") throw new Error("The audio input disconnected while preparing the take.");
    const node = new AudioWorkletNode(context, "ggenre-capture", {processorOptions:{channelSelection:["mix","left","right"].includes(channelSelection)?channelSelection:"mix"}});
    const microphone = context.createMediaStreamSource(stream), silent = context.createGain();
    silent.gain.value = 0;
    microphone.connect(node); node.connect(silent).connect(context.destination);
    const sources = [], chunks = [];
    let total = 0, checkpointAt = 0, finished = false, stopping = false;
    const countStart = context.currentTime + 0.25;
    const startTime = countStart + countIn * 60 / bpm;
    // Continue capture briefly after backing stops so delayed mic samples are retained.
    const tail = Math.max(0, Math.min(1, captureTail));
    const maxEnd = startTime + 300 - position + tail;
    function stopSources() { for (const source of sources) { try { source.stop(); } catch (_) {} source.disconnect(); } }
    function cleanup() {
      clearInterval(progress); stopSources(); microphone.disconnect(); node.disconnect(); silent.disconnect();
      stream.getTracks().forEach(track => track.stop()); context.removeEventListener("statechange", stateChanged);
    }
    function abort(error) { if (finished) return; finished = true; cleanup(); onError(error); }
    function stateChanged() { if (context.state !== "running") abort(new Error("Audio was interrupted. Keep this tab active while recording and try again.")); }
    const progress = setInterval(() => onProgress({remaining: Math.max(0, startTime - context.currentTime), elapsed: Math.max(0, context.currentTime - startTime), stopping}), 80);
    const session = {
      startTime,
      stop() {
        if (finished || stopping) return;
        stopping = true; stopSources();
        node.port.postMessage({type: "stop", frame: Math.ceil((context.currentTime < startTime ? context.currentTime : context.currentTime + tail) * context.sampleRate)});
      },
      cancel() { if (!finished) { finished = true; cleanup(); } },
    };
    node.port.onmessage = event => {
      if (finished) return;
      const data = event.data;
      if (data.type === "chunk") {
        chunks.push(data.samples); total += data.samples.length;
        if (total - checkpointAt >= context.sampleRate * 5) {
          checkpointAt = total; const samples = new Float32Array(total); let offset = 0;
          for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
          onCheckpoint({samples, sampleRate: context.sampleRate, position});
        }
      }
      else if (data.type === "meter") onMeter(data.peak);
      else if (data.type === "done") {
        finished = true; cleanup();
        const samples = new Float32Array(Math.min(total, data.frames)); let offset = 0;
        for (const chunk of chunks) { const part = chunk.subarray(0, samples.length - offset); samples.set(part, offset); offset += part.length; }
        onDone({samples, sampleRate: context.sampleRate, position});
      }
    };
    node.onprocessorerror = () => abort(new Error("Audio input capture stopped unexpectedly. Please try recording again."));
    context.addEventListener("statechange", stateChanged);
    stream.getAudioTracks()[0].addEventListener("ended", () => session.stop(), {once: true});
    try {
      node.port.postMessage({type: "arm", start: Math.ceil(startTime * context.sampleRate), end: Math.ceil(maxEnd * context.sampleRate)});
      for (const {buffer, plan} of backing) {
        if (!plan || plan.duration <= 0) continue;
        const source = context.createBufferSource(), gain = context.createGain(); source.buffer = buffer; gain.gain.value = plan.gain;
        source.connect(gain).connect(destination); source.start(startTime + plan.delay, plan.start, plan.duration); sources.push(source);
      }
      for (let beat = 0; beat < countIn; beat++) {
        const oscillator = context.createOscillator(), gain = context.createGain();
        const when = countStart + beat * 60 / bpm;
        oscillator.frequency.value = beat === 0 ? 1000 : 750;
        gain.gain.setValueAtTime(0.12, when); gain.gain.exponentialRampToValueAtTime(0.001, when + 0.07);
        oscillator.connect(gain).connect(destination); oscillator.start(when); oscillator.stop(when + 0.08); sources.push(oscillator);
      }
      return session;
    } catch (error) { cleanup(); throw error; }
  }
  const api = {segment, compensate, estimatedDelay, begin};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else scope.StudioAudio = api;
})(typeof window !== "undefined" ? window : globalThis);
