(() => {
  "use strict";
  const root = document.getElementById("studio");
  if (!root) return;
  const tracks = JSON.parse(document.getElementById("studio-tracks").textContent);
  const status = document.getElementById("status");
  const isAcapella = root.dataset.category === "acapella";
  const voiceTools = isAcapella && typeof StudioVoices !== "undefined" ? StudioVoices : null;
  const soloVoices = new Set(); let referenceGuide, selectedVoicePart = "Lead voice";
  const accompaniment = isAcapella ? "other voices" : "backing tracks";
  const preferenceKey = `ggenre-acapella:${root.dataset.user}:${root.dataset.project}`;
  function rememberVoiceSettings() {
    if (!voiceTools) return;
    try { sessionStorage.setItem(preferenceKey, JSON.stringify({revision: baseRevision, part: selectedVoicePart, tempo: Number(document.getElementById("tempo").value), countIn: document.getElementById("count-in").value, position: Number(document.getElementById("record-position").value), pitch: document.getElementById("reference-pitch")?.value || "60"})); } catch (_) {}
  }
  function monitorTracks() { return voiceTools ? voiceTools.monitoring(tracks, soloVoices) : tracks; }
  function syncSolo() {
    root.querySelectorAll("[data-voice-solo]").forEach(button => { const selected = soloVoices.has(Number(button.dataset.voiceSolo)); button.setAttribute("aria-pressed", String(selected)); button.classList.toggle("is-selected", selected); });
    const info = document.getElementById("acapella-monitor-status"); if (info) info.textContent = soloVoices.size ? `Solo listening: ${soloVoices.size} voice${soloVoices.size === 1 ? "" : "s"}. Save mix still includes every unmuted voice.` : "Listening to all unmuted voices.";
  }
  const csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
  let context, session, previewURL, takeURL, pendingTake, preparing = false, busy = false, dirty = false;
  let recordingToken = 0, recordingStream, orientation;
  let takeEstimate = 0, timeline, draftStore, draftTimer, checkpoint, recoveryWaiting = false, recovering = false;
  let baseRevision = root.dataset.revision || JSON.stringify(tracks);
  const trackInputs = new Map();
  function recoveryMessage(text) { const label = document.getElementById("recovery-status"); if (label) label.textContent = text; }
  function persistDraft() {
    if (!draftStore || recoveryWaiting || recovering) return;
    const take = pendingTake || checkpoint;
    if (!dirty && !take) { clearDraft(); return; }
    const snapshot = {schema: 1, base: baseRevision, tracks: tracks.map(track => ({...track})), take, tempo: Number(document.getElementById("tempo").value), correction: checkpoint && !pendingTake ? takeEstimate : Number(document.getElementById("delay-correction").value) || 0};
    recoveryMessage("Saving recovery copy on this browser…");
    draftStore.write(snapshot).then(() => recoveryMessage("Recovery copy saved on this browser · " + new Date().toLocaleTimeString())).catch(() => recoveryMessage("Local recovery could not be saved. Keep this tab open and save your work to GGenre."));
  }
  function scheduleDraft() { if (!draftStore) return; clearTimeout(draftTimer); draftTimer = setTimeout(persistDraft, 500); }
  async function clearDraft() {
    clearTimeout(draftTimer); checkpoint = null;
    if (draftStore) { try { await draftStore.clear(); recoveryMessage("Saved to GGenre. No local recovery copy pending."); } catch (_) { recoveryMessage("Saved to GGenre, but the older local recovery copy could not be removed."); } }
  }
  function syncTrackInputs(track) {
    const fields = trackInputs.get(track.id);
    if (fields) for (const [key, input] of Object.entries(fields)) { if (key === "muted") input.checked = track[key]; else input.value = track[key]; }
  }
  const buffers = new Map();
  const audioContext = () => context || (context = new AudioContext({latencyHint: "interactive", sampleRate: 44100}));
  let playbackOrigin = 0, previewSignature = "";
  function transportTime(seconds) {
    const clock = document.getElementById("session-clock");
    if (clock) { const value = Math.max(0, Number(seconds) || 0); clock.textContent = `${String(Math.floor(value / 60)).padStart(2, "0")}:${(value % 60).toFixed(2).padStart(5, "0")}`; }
    timeline?.setPlayhead?.(seconds);
  }
  function playbackState() {
    const player = document.getElementById("mix-preview"), label = document.getElementById("play-label");
    const playing = player?.paused === false;
    if (label) label.textContent = playing ? "Pause" : "Play";
    const button = document.getElementById("preview"); if (button) button.dataset.playing = String(playing);
    const stop = document.getElementById("stop"); if (stop) stop.disabled = !session && !Array.from(root.querySelectorAll("audio")).some(audio => audio.paused === false);
  }
  function bindTransportAudio(player, origin) {
    player.addEventListener("play", playbackState); player.addEventListener("pause", playbackState); player.addEventListener("ended", playbackState);
    player.addEventListener("timeupdate", () => { if (player.paused === false) transportTime(origin() + player.currentTime); });
  }
  function message(text) { status.textContent = text; }
  function changed() { dirty = true; root.querySelectorAll("[data-saved-action]").forEach(b => b.disabled = true); timeline?.render(); scheduleDraft(); }
  async function post(url, data) {
    const response = await fetch(url, {method: "POST", headers: {"X-CSRFToken": csrf}, body: data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to save. Please try again.");
    return result;
  }
  async function task(action) {
    if (busy || session || preparing || recovering || recoveryWaiting || orientation?.blocked()) return;
    busy = true; controls();
    try { await action(); } catch (error) { message(error.message || "Audio is unavailable in this browser."); }
    finally { busy = false; controls(); }
  }
  function wav(buffer) {
    const channels = Math.min(buffer.numberOfChannels, 2), length = buffer.length;
    const bytes = new ArrayBuffer(44 + length * channels * 2), view = new DataView(bytes);
    const word = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    word(0, "RIFF"); view.setUint32(4, bytes.byteLength - 8, true); word(8, "WAVE"); word(12, "fmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, channels, true);
    view.setUint32(24, buffer.sampleRate, true); view.setUint32(28, buffer.sampleRate * channels * 2, true);
    view.setUint16(32, channels * 2, true); view.setUint16(34, 16, true); word(36, "data"); view.setUint32(40, bytes.byteLength - 44, true);
    const samples = Array.from({length: channels}, (_, c) => buffer.getChannelData(c));
    let offset = 44;
    for (let i = 0; i < length; i++) for (let c = 0; c < channels; c++) {
      const value = Math.max(-1, Math.min(1, samples[c][i]));
      view.setInt16(offset, value * (value < 0 ? 32768 : 32767), true); offset += 2;
    }
    return new Blob([bytes], {type: "audio/wav"});
  }
  async function load(track) {
    if (!buffers.has(track.id)) {
      const pending = (async () => { const response = await fetch(track.url); if (!response.ok) throw new Error("Unable to load a private track. Refresh and sign in again."); return audioContext().decodeAudioData(await response.arrayBuffer()); })();
      buffers.set(track.id, pending);
      pending.catch(() => { if (buffers.get(track.id) === pending) buffers.delete(track.id); });
    }
    return buffers.get(track.id);
  }
  async function mix(extra = null, position = 0, audition = false) {
    const selected = audition ? monitorTracks() : tracks;
    const active = (extra ? [...selected, extra] : selected).filter(t => !t.muted);
    if (!active.length) throw new Error(isAcapella ? "Record or unmute at least one voice." : "Add or unmute at least one track.");
    const parts = await Promise.all(active.map(async track => {
      const buffer = track.buffer || await load(track);
      const start = Number(track.trim_start), end = Number(track.trim_end) || buffer.duration;
      if (start >= end || end > buffer.duration + 0.02) throw new Error("Check trim times for " + track.name);
      return {track, buffer, start, duration: Math.min(end, buffer.duration) - start};
    }));
    const fullDuration = Math.max(...parts.map(p => Number(p.track.offset) + p.duration));
    if (fullDuration > 300) throw new Error("The final mix must be five minutes or shorter.");
    const duration = fullDuration - position;
    if (duration <= 0) throw new Error("There is no audio after that position.");
    const offline = new OfflineAudioContext(2, Math.ceil(duration * 44100), 44100);
    for (const part of parts) {
      const source = offline.createBufferSource(), gain = offline.createGain();
      source.buffer = part.buffer; gain.gain.value = Number(part.track.gain);
      source.connect(gain).connect(offline.destination);
      const plan = StudioAudio.segment(part.track, part.buffer.duration, position);
      if (plan && plan.duration > 0) source.start(plan.delay, plan.start, plan.duration);
    }
    const rendered = await offline.startRendering();
    if (voiceTools) { const result = voiceTools.protect(rendered), label = document.getElementById("acapella-mix-health"); if (label) label.textContent = result.gain < 1 ? `Peak guard reduced the mix by ${(-20 * Math.log10(result.gain)).toFixed(1)} dB to avoid digital clipping.` : "Peak guard on · mix levels are within range."; }
    return wav(rendered);
  }
  async function upload(blob, offset = 0, name = null, kind = "vocal", preset = "", beatBpm = null) {
    if (blob.size > 64 * 1024 * 1024) throw new Error("Choose audio under 64 MB.");
    const buffer = await audioContext().decodeAudioData(await blob.arrayBuffer());
    if (!Number.isFinite(offset) || offset < 0 || offset + buffer.duration > 300.001) throw new Error("Keep the voice and its starting position within the five-minute project.");
    const data = new FormData(); data.append("audio", wav(buffer), "track.wav");
    data.append("name", name || document.getElementById("track-name").value || "Vocal");
    data.append("offset", String(offset)); data.append("kind", kind); data.append("beat_preset", preset);
    data.append("tempo", document.getElementById("tempo").value); if (beatBpm !== null) data.append("beat_bpm", String(beatBpm));
    data.append("tracks", JSON.stringify(tracks)); data.append("revision", baseRevision); rememberVoiceSettings();
    message("Saving track…");
    await post(`/studio/project/${root.dataset.project}/track/`, data);
    dirty = false; pendingTake = null; await clearDraft(); location.reload();
  }
  const container = document.getElementById("tracks");
  for (const [index, track] of tracks.entries()) {
    const fields = {}; trackInputs.set(track.id, fields);
    const card = document.createElement("section"); card.className = "studio-track-strip";
    const number = document.createElement("span"); number.className = "studio-track-number"; number.textContent = String(index + 1).padStart(2, "0");
    const title = document.createElement(isAcapella ? "input" : "h3");
    if (isAcapella) { title.type = "text"; title.className = "studio-voice-name"; title.value = track.name; title.maxLength = 100; title.setAttribute("aria-label", "Voice name"); fields.name = title;
      title.addEventListener("input", () => { track.name = title.value; listen.setAttribute("aria-label", "Listen to " + track.name); remove.setAttribute("aria-label", "Remove " + track.name); changed(); });
    } else title.textContent = track.name;
    title.title = track.name; card.append(number, title);
    const player = document.createElement("audio"); player.controls = true; player.src = track.url; player.controlsList = "nodownload"; card.append(player);
    bindTransportAudio(player, () => Number(track.offset));
    const timing = document.createElement("details"); timing.className = "studio-track-edit";
    const timingLabel = document.createElement("summary"); timingLabel.textContent = "Timing ▾";
    const timingPanel = document.createElement("div"); timingPanel.className = "studio-track-edit-panel"; timing.append(timingLabel, timingPanel);
    for (const [key, label, max] of [["gain", "VOL", 2], ["offset", "Start on timeline (seconds)", 300], ["trim_start", "Trim from (seconds)", 300], ["trim_end", "Trim to (0 = track end)", 300]]) {
      const wrapper = document.createElement(key === "gain" ? "div" : "label"); wrapper.className = key === "gain" ? "studio-track-fader" : "studio-timing-field";
      const text = document.createElement("label"); text.textContent = label;
      const input = document.createElement("input"); input.type = key === "gain" ? "range" : "number"; input.min = 0; input.max = max; input.step = "0.01"; input.value = track[key]; input.dataset.trackField = key; input.setAttribute("aria-label", track.name + " " + (key === "gain" ? "volume" : label));
      fields[key] = input; input.addEventListener("input", () => { track[key] = Number(input.value); changed(); });
      if (key === "gain") { wrapper.append(text, input); card.append(wrapper); }
      else { wrapper.textContent = label; wrapper.append(input); timingPanel.append(wrapper); }
    }
    const actions = document.createElement("div"); actions.className = "studio-track-actions";
    const label = document.createElement("label"), muted = document.createElement("input"); label.className = "studio-track-mute"; muted.type = "checkbox"; muted.checked = track.muted; fields.muted = muted;
    muted.addEventListener("change", () => { track.muted = muted.checked; changed(); }); label.append(muted, "Mute");
    const listen = document.createElement("button"); listen.type = "button"; listen.textContent = "▶"; listen.setAttribute("aria-label", "Listen to " + track.name); listen.title = "Audition original take";
    listen.addEventListener("click", () => task(async () => { pausePlayers(); await player.play(); }));
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.title = "Remove " + track.name; remove.setAttribute("aria-label", "Remove " + track.name); remove.dataset.trackRemove = "true";
    remove.addEventListener("click", () => task(async () => { if (confirm("Remove this track?")) { const data = new FormData(); data.append("tracks", JSON.stringify(tracks)); data.append("revision", baseRevision); await post(`/studio/track/${track.id}/delete/`, data); dirty = false; await clearDraft(); location.reload(); } }));
    actions.append(label);
    if (voiceTools) { const solo = document.createElement("button"); solo.type = "button"; solo.textContent = "Solo"; solo.className = "studio-voice-solo"; solo.dataset.voiceSolo = String(track.id); solo.setAttribute("aria-label", "Solo " + track.name); solo.setAttribute("aria-pressed", "false");
      solo.addEventListener("click", () => { if (session || preparing || busy) return; pausePlayers(); if (soloVoices.has(track.id)) soloVoices.delete(track.id); else soloVoices.add(track.id); syncSolo(); }); actions.append(solo);
    }
    actions.append(listen, timing, remove); card.append(actions); container.append(card);
  }
  document.getElementById("import").addEventListener("change", event => task(async () => {
    const file = event.target.files[0]; if (file) await upload(file, isAcapella ? Number(document.getElementById("record-position").value) || 0 : 0, null, isAcapella ? "vocal" : "backing");
  }));
  const recordButton = document.getElementById("record"), stopButton = document.getElementById("stop");
  const review = document.getElementById("take-review"), correction = document.getElementById("delay-correction");
  const meter = document.getElementById("input-meter"), levelLabel = document.getElementById("level-label");
  function controls() {
    const locked = !!session || preparing || busy || recovering || recoveryWaiting;
    root.querySelectorAll("button, input, select, audio").forEach(control => {
      if (control === stopButton || control.id === "cancel-recording" || control.id === "restore-draft" || control.id === "discard-draft" || control.id === "setup-toggle") return;
      if (control.matches("audio")) { control.controls = !locked; if (locked) control.pause(); return; }
      // Mix/publish buttons already disabled by unsaved edits must stay disabled.
      if (locked) { if (control.dataset.wasDisabled === undefined) control.dataset.wasDisabled = String(control.disabled); control.disabled = true; }
      else if (control.dataset.wasDisabled !== undefined) { control.disabled = control.dataset.wasDisabled === "true"; delete control.dataset.wasDisabled; }
    });
    const cancel = document.getElementById("cancel-recording");
    if (cancel) { cancel.hidden = !session && !preparing; cancel.disabled = !session && !preparing; }
    root.dataset.cancellable = String(!!session || preparing);
    orientation?.updateCapture({active: !!session || preparing, canStop: !!session});
    recordButton.disabled = locked || !!pendingTake;
    document.getElementById("import").disabled = locked || !!pendingTake;
    stopButton.disabled = !session && !Array.from(root.querySelectorAll("audio")).some(audio => audio.paused === false);
    root.dataset.state = session ? "recording" : pendingTake ? "review" : locked ? "busy" : "ready";
    root.querySelectorAll("[data-track-remove]").forEach(b => b.disabled = locked || !!pendingTake);
    document.getElementById("save").disabled = locked || !!pendingTake;
    root.querySelectorAll("[data-saved-action]").forEach(b => {
      b.disabled = locked || !!pendingTake || dirty || !root.dataset.hasMix;
    });
  }
  function pausePlayers() { referenceGuide?.stop(); referenceGuide = null; root.querySelectorAll("audio").forEach(player => player.pause()); }
  function takeBuffer() {
    const milliseconds = Number(correction.value);
    if (!Number.isFinite(milliseconds) || milliseconds < -1000 || milliseconds > 1000) throw new Error("Delay correction must be between -1000 and 1000 ms.");
    let samples = StudioAudio.compensate(pendingTake.samples, pendingTake.sampleRate, milliseconds);
    const remaining = Math.floor((300 - pendingTake.position) * pendingTake.sampleRate);
    samples = samples.subarray(0, remaining);
    const buffer = audioContext().createBuffer(1, samples.length, pendingTake.sampleRate);
    buffer.copyToChannel(samples, 0); return buffer;
  }
  function showTake(take, adjustment = 0) {
    pendingTake = take; correction.value = String(adjustment); review.hidden = false;
    document.getElementById("take-info").textContent = `${take.name} · ${(take.samples.length / take.sampleRate).toFixed(1)} seconds · starts at ${take.position.toFixed(2)} seconds`;
    try { const blob = wav(takeBuffer()); if (takeURL) URL.revokeObjectURL(takeURL); takeURL = URL.createObjectURL(blob); document.getElementById("take-preview").src = takeURL; }
    catch (error) { correction.value = "0"; message(error.message); }
    controls(); message(`Take ready. Listen with ${accompaniment}, adjust alignment, then keep or re-record.`);
  }
  function resetTake() {
    pausePlayers(); pendingTake = null; checkpoint = null; review.hidden = true; scheduleDraft();
    if (takeURL) { URL.revokeObjectURL(takeURL); takeURL = null; }
    document.getElementById("take-preview").removeAttribute("src"); controls();
    root.querySelectorAll("[data-saved-action]").forEach(b => b.disabled = dirty || !root.dataset.hasMix);
  }
  function selectedInputMode() { return !isAcapella && document.getElementById("studio-input-mode")?.value === "keyboard" ? "keyboard" : "microphone"; }
  function updateInputMode() { const mode=document.getElementById("studio-input-mode"); if(!mode)return;const keyboard=selectedInputMode()==="keyboard";const label=recordButton.querySelector("span:last-child");if(label)label.textContent=keyboard?"Record keyboard":(isAcapella?"Record voice":"Record vocal");const name=document.getElementById("track-name");if(name&&keyboard&&["Lead vocal","Lead voice","Vocal"].includes(name.value))name.value="Keyboard audio";else if(name&&!keyboard&&name.value==="Keyboard audio")name.value=isAcapella?"Lead voice":"Lead vocal";const heading=document.getElementById("studio-take-kind-label");if(heading)heading.textContent=keyboard?"NEXT KEYBOARD AUDIO TAKE":isAcapella?"BUILD YOUR VOCAL ARRANGEMENT":"NEXT VOCAL TAKE";const parts=document.getElementById("studio-voice-parts");if(parts)parts.hidden=keyboard;const meterSource=document.getElementById("studio-input-meter-source");if(meterSource)meterSource.textContent=keyboard?"LINE / USB":"MIC";if(!session&&!preparing)levelLabel.textContent=keyboard?"Your audio input activates when you record.":"Your microphone activates when you record.";const note=document.getElementById("studio-input-note");if(note)note.textContent=keyboard?"Connect the keyboard's audio output through an audio interface, or use its USB audio input if supported. Audio is captured as mono; use your interface's direct monitoring to listen.":"Record your voice using the selected microphone. Your microphone activates when you record."; }
  async function startRecording() {
    if (session || preparing || busy || pendingTake || recovering || recoveryWaiting || orientation?.blocked()) return;
    if (!navigator.mediaDevices || !window.AudioWorkletNode) { message("Synchronized recording requires HTTPS or localhost and a browser with AudioWorklet support."); return; }
    if (tracks.length >= 12) { message("Maximum 12 tracks. Remove one before recording."); return; }
    const position = Number(document.getElementById("record-position").value);
    const bpm = Number(document.getElementById("tempo").value), countIn = Number(document.getElementById("count-in").value);
    if (!Number.isFinite(position) || position < 0 || position > 299 || !Number.isFinite(bpm) || bpm < 40 || bpm > 240 || ![0, 4, 8].includes(countIn)) { message("Choose a start position from 0–299 seconds and a tempo from 40–240 BPM."); return; }
    rememberVoiceSettings();
    const keyboardInput=selectedInputMode()==="keyboard",takeKind=keyboardInput?"backing":"vocal";
    const attempt = ++recordingToken;
    preparing = true; pausePlayers(); controls(); message(`Preparing ${accompaniment} and audio input…`);
    let stream;
    try {
      const ctx = audioContext(); await ctx.resume();
      if (attempt !== recordingToken) return;
      const deviceId=document.getElementById("studio-audio-device")?.value||"";
      const inputConstraints=typeof StudioInputs!=="undefined"?StudioInputs.constraints(deviceId,keyboardInput):{audio:{channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false}};
      stream = await navigator.mediaDevices.getUserMedia(inputConstraints);
      if (attempt !== recordingToken) { stream.getTracks().forEach(track => track.stop()); return; }
      if(stream.getAudioTracks()[0]?.readyState==="ended")throw new Error("The audio input disconnected. Reconnect it and try again.");
      recordingStream = stream;
      takeEstimate = StudioAudio.estimatedDelay(ctx, stream);
      const name = document.getElementById("track-name").value || (keyboardInput?"Keyboard audio":"Vocal");
      const activeSession = await StudioAudio.begin({context: ctx, stream, tracks: monitorTracks(), load, position, bpm, countIn, channelSelection:document.getElementById("studio-audio-channel")?.value||"mix", workletURL: root.dataset.workletUrl,
        onMeter(peak) { if (attempt !== recordingToken) return; meter.value = peak; levelLabel.textContent = peak >= 0.98 ? "Clipping — reduce your input level." : peak < 0.005 ? "Very low input — check your audio input." : "Audio input active · headphones recommended"; },
        onProgress({remaining, elapsed, stopping}) {
          if (attempt !== recordingToken) return;
          transportTime(position + elapsed);
          message(stopping ? "Finishing audio take…" : remaining > 0 ? (countIn ? `Count-in: ${Math.min(countIn, Math.ceil(remaining / (60 / bpm)))} · ready to record` : "Ready to record…") : `Recording at ${(position + elapsed).toFixed(1)} s · Stop to review · Cancel to discard`);
        },
        onDone(take) {
          if (attempt !== recordingToken) return;
          recordingStream = undefined; session = null; meter.value = 0;
          if (take.samples.length < take.sampleRate * 0.1) { controls(); message("Recording cancelled. No take was added."); return; }
          checkpoint = null; showTake({...take, name, tempo: bpm, kind:takeKind}, takeEstimate); persistDraft();
        },
        onCheckpoint(take) { if (attempt !== recordingToken) return; checkpoint = {...take, name, tempo: bpm, kind:takeKind}; persistDraft(); },
        onError(error) {
          if (attempt !== recordingToken) return;
          recordingStream = undefined; session = null; preparing = false; meter.value = 0;
          if (checkpoint) { const partial = checkpoint; checkpoint = null; showTake(partial, takeEstimate); persistDraft(); message(error.message + " A partial take is available for review."); }
          else { controls(); message(error.message); }
        },
      });
      if (attempt !== recordingToken) { activeSession.cancel(); return; }
      session = activeSession;
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      if (attempt !== recordingToken) return;
      recordingStream = undefined;
      message(error.name === "NotAllowedError" ? "Audio input permission was denied. Allow audio access and try again." : error.name === "NotFoundError" ? "No audio input found. Connect a microphone or audio interface and try again." : error.name === "NotReadableError" ? "The audio input is unavailable. Close other apps using it and try again." : error.name === "OverconstrainedError" ? "The selected input is unavailable. Reconnect it or select another audio device." : error.message);
    } finally { if (attempt === recordingToken) { preparing = false; controls(); } }
  }
  async function cancelCurrentTake() {
    if (!session && !preparing) return;
    const cancelled = ++recordingToken;
    session?.cancel(); session = null;
    recordingStream?.getTracks().forEach(track => track.stop()); recordingStream = undefined;
    preparing = false; checkpoint = null; meter.value = 0;
    levelLabel.textContent = "Microphone inactive. Ready for another take.";
    pausePlayers(); transportTime(Number(document.getElementById("record-position").value) || 0); controls();
    await clearDraft(); if (dirty) persistDraft();
    if (recordingToken === cancelled) message("Recording cancelled. Existing tracks and edits were kept.");
  }
  document.getElementById("cancel-recording")?.addEventListener("click", cancelCurrentTake);
  function stopTransport() {
    if (session) session.stop();
    else { pausePlayers(); for (const player of root.querySelectorAll("audio")) player.currentTime = 0; transportTime(Number(document.getElementById("record-position").value) || 0); playbackState(); }
  }
  stopButton.addEventListener("click", stopTransport);
  bindTransportAudio(document.getElementById("mix-preview"), () => playbackOrigin);
  bindTransportAudio(document.getElementById("take-preview"), () => pendingTake?.position || 0);
  document.getElementById("rewind")?.addEventListener("click", () => {
    if (session || preparing || busy) return; pausePlayers();
    document.getElementById("record-position").value = "0"; timeline?.setPosition(0); transportTime(0);
    document.getElementById("mix-preview").currentTime = 0; message("Returned to the start.");
  });
  document.getElementById("setup-toggle")?.addEventListener("click", () => {
    const panel = document.getElementById("recording-setup"), button = document.getElementById("setup-toggle");
    if (!panel) return; const open = panel.classList.toggle("is-open"); button.setAttribute("aria-expanded", String(open));
  });
  recordButton.addEventListener("click", startRecording);
  document.getElementById("audition-take").addEventListener("click", () => task(async () => {
    if (!pendingTake) return;
    pausePlayers(); message("Preparing aligned take preview…");
    const extra = {buffer: takeBuffer(), name: pendingTake.name, offset: pendingTake.position, gain: 1, trim_start: 0, trim_end: 0, muted: false};
    const blob = await mix(extra, pendingTake.position, true);
    if (takeURL) URL.revokeObjectURL(takeURL); takeURL = URL.createObjectURL(blob);
    const player = document.getElementById("take-preview"); player.src = takeURL; await player.play(); message(`Reviewing the take with ${accompaniment}. Keep it when you are happy with alignment.`);
  }));
  correction.addEventListener("input", () => { document.getElementById("take-preview").pause(); message("Alignment changed. Click Listen with backing tracks to review the adjustment."); scheduleDraft(); });
  document.getElementById("keep-take").addEventListener("click", () => task(async () => {
    if (!pendingTake) return;
    pausePlayers(); await upload(wav(takeBuffer()), pendingTake.position, pendingTake.name, pendingTake.kind === "backing" ? "backing" : "vocal");
  }));
  document.getElementById("retry-take").addEventListener("click", () => {
    if (busy || !pendingTake) return;
    if (!confirm("Discard this unsaved take and record again?")) return;
    resetTake(); startRecording();
  });
  document.getElementById("discard-take").addEventListener("click", () => {
    if (busy || !pendingTake || !confirm("Discard this unsaved take?")) return;
    resetTake(); message("Take discarded. Your saved tracks are unchanged.");
  });
  document.getElementById("preview").addEventListener("click", async () => {
    const player = document.getElementById("mix-preview");
    if (player.paused === false) { player.pause(); playbackState(); message("Playback paused."); return; }
    await task(async () => {
      const position = Number(document.getElementById("record-position").value) || 0;
      const signature = JSON.stringify(tracks) + ":" + position + ":" + [...soloVoices].join(",");
      if (previewURL && previewSignature === signature && player.src === previewURL && player.currentTime > 0 && !player.ended) {
        await player.play(); playbackState(); message("Playing mix."); return;
      }
      message("Preparing preview…"); const blob = await mix(null, position, true); playbackOrigin = position; previewSignature = signature;
      if (previewURL) URL.revokeObjectURL(previewURL); previewURL = URL.createObjectURL(blob);
      player.src = previewURL; await player.play(); playbackState(); message("Playing mix.");
    });
  });
  document.getElementById("save").addEventListener("click", () => task(async () => {
    if (session || pendingTake) throw new Error("Finish reviewing your take before saving the mix.");
    message("Saving mix and edits…"); const data = new FormData(); data.append("audio", await mix(), "mix.wav"); data.append("tracks", JSON.stringify(tracks)); data.append("tempo", document.getElementById("tempo").value); data.append("revision", baseRevision);
    const result = await post(`/studio/project/${root.dataset.project}/save/`, data); baseRevision = result.revision || baseRevision; await clearDraft(); dirty = false; root.dataset.hasMix = "true";
    root.querySelectorAll("[data-saved-action]").forEach(b => b.disabled = false); message("Mix and edits saved. Ready to publish or export.");
  }));
  root.querySelectorAll("[data-voice-part]").forEach(button => button.addEventListener("click", () => {
    if (session || preparing || busy) return;
    selectedVoicePart = button.dataset.voicePart;
    document.getElementById("track-name").value = voiceTools ? voiceTools.nextName(selectedVoicePart, tracks) : selectedVoicePart; rememberVoiceSettings();
    root.querySelectorAll("[data-voice-part]").forEach(part => part.classList.toggle("is-selected", part === button));
  }));
  const beatSelect = document.getElementById("beat-preset");
  if (beatSelect && typeof StudioBeats !== "undefined") {
    const presets = JSON.parse(document.getElementById("studio-beat-presets").textContent), preview = document.getElementById("beat-preview");
    let beatURL;
    const backingOptions = () => ({mode:document.getElementById("backing-mode").value,key:Number(document.getElementById("backing-key").value),progression:document.getElementById("backing-progression").value});
    const selected = () => presets.find(preset => preset.id === beatSelect.value);
    function beatChanged() { const preset = selected(); if (preset) { document.getElementById("beat-description").textContent = preset.description; document.getElementById("beat-tempo").value = preset.bpm; } preview.pause(); const progression = document.getElementById("backing-progression"); progression.value = preset?.id === "gospel-worship" || preset?.id === "gospel-congregation" ? "worship" : preset?.id === "secular-rnb" ? "soul" : preset?.id === "secular-hiphop" ? "minor" : "major"; progression.dispatchEvent(new Event("change",{bubbles:true})); }
    for (const id of ["backing-mode","backing-key","backing-progression","beat-tempo","beat-bars"]) document.getElementById(id).addEventListener("change",()=>preview.pause());
    beatSelect.addEventListener("change", beatChanged); beatChanged();
    bindTransportAudio(preview, () => 0);
    preview.addEventListener("play", () => document.getElementById("preview-beat").textContent = "Stop preview");
    preview.addEventListener("pause", () => document.getElementById("preview-beat").textContent = "Preview");
    preview.addEventListener("ended", () => document.getElementById("preview-beat").textContent = "Preview");
    document.getElementById("preview-beat").addEventListener("click", async () => {
      if (!preview.paused) { preview.pause(); return; }
      await task(async () => {
        const preset = selected(), bpm = Number(document.getElementById("beat-tempo").value);
        message("Preparing instrumental preview…"); const buffer = await StudioBeats.render(preset, bpm, 4, backingOptions());
        if (beatURL) URL.revokeObjectURL(beatURL); beatURL = URL.createObjectURL(wav(buffer)); preview.src = beatURL; await preview.play(); message("Previewing " + preset.name + ".");
      });
    });
    document.getElementById("add-beat").addEventListener("click", () => task(async () => {
      const preset = selected(), bpm = Number(document.getElementById("beat-tempo").value), bars = Number(document.getElementById("beat-bars").value);
      message("Building your instrumental backing…"); const buffer = await StudioBeats.render(preset, bpm, bars, backingOptions());
      await upload(wav(buffer), 0, preset.name + " · " + backingOptions().mode + " · " + document.getElementById("backing-key").selectedOptions[0].textContent + " " + backingOptions().progression + " · " + bpm + " BPM", "beat", preset.id, bpm);
    }));
  }
  if (voiceTools) {
    try {
      const prefs = JSON.parse(sessionStorage.getItem(preferenceKey) || "null");
      if (prefs) { if (typeof prefs.part === "string" && prefs.part.trim()) selectedVoicePart = prefs.part.trim();
        if (["0", "4", "8"].includes(prefs.countIn)) { const input = document.getElementById("count-in"); input.value = prefs.countIn; input.dispatchEvent?.(new Event("change", {bubbles:true})); }
        if (Number.isFinite(prefs.position) && prefs.position >= 0 && prefs.position <= 299) document.getElementById("record-position").value = prefs.position;
        if (prefs.revision === baseRevision && Number.isInteger(prefs.tempo) && prefs.tempo >= 40 && prefs.tempo <= 240) document.getElementById("tempo").value = prefs.tempo;
        const pitch = document.getElementById("reference-pitch"); if (pitch && Number(prefs.pitch) >= 48 && Number(prefs.pitch) <= 72) { pitch.value = prefs.pitch; pitch.dispatchEvent?.(new Event("change", {bubbles:true})); }
      }
    } catch (_) {}
    document.getElementById("track-name").value = voiceTools.nextName(selectedVoicePart, tracks);
    document.getElementById("track-name").addEventListener("input", () => { selectedVoicePart = document.getElementById("track-name").value.trim() || "Voice"; rememberVoiceSettings(); });
    document.getElementById("count-in").addEventListener("change", rememberVoiceSettings);
    document.getElementById("record-position").addEventListener("input", rememberVoiceSettings);
    document.getElementById("tempo").addEventListener("input", () => { rememberVoiceSettings(); changed(); });
    document.getElementById("clear-solo")?.addEventListener("click", () => { if (session || preparing || busy) return; pausePlayers(); soloVoices.clear(); syncSolo(); });
    document.getElementById("reference-pitch")?.addEventListener("change", () => { referenceGuide?.stop(); rememberVoiceSettings(); });
    document.getElementById("play-reference")?.addEventListener("click", async () => {
      if (referenceGuide) { referenceGuide.stop(); referenceGuide = null; return; }
      await task(async () => { const ctx = audioContext(); await ctx.resume(); pausePlayers();
        const button = document.getElementById("play-reference"); button.textContent = "Stop note";
        referenceGuide = voiceTools.reference(ctx, Number(document.getElementById("reference-pitch").value), () => { referenceGuide = null; button.textContent = "Play note"; }); message("Reference note only — this is not added to your project.");
      });
    });
    syncSolo();
  }
  if (typeof StudioTimeline !== "undefined" && document.getElementById("studio-timeline")) {
    timeline = new StudioTimeline.Timeline({container: document.getElementById("studio-timeline"), category: root.dataset.category, tracks, load,
      onChange(track) { syncTrackInputs(track); changed(); },
      onSeek(value) { const input = document.getElementById("record-position"); input.value = value.toFixed(2); timeline.setPosition(value); transportTime(value); },
      locked: () => !!session || preparing || busy || recovering || recoveryWaiting,
      onError: error => message(error.message),
    });
    document.getElementById("record-position").addEventListener("input", event => { const value = Number(event.target.value) || 0; timeline.setPosition(value); transportTime(value); });
  }
  async function initializeRecovery() {
    if (typeof StudioDrafts === "undefined" || !document.getElementById("recovery-panel")) return;
    draftStore = new StudioDrafts(`${root.dataset.user}:${root.dataset.project}`);
    recovering = true; controls();
    try {
      const saved = await draftStore.read();
      if (!saved) { recoveryMessage("Local recovery is ready. Edits save here automatically; active recordings checkpoint every five seconds."); return; }
      const take = saved.take;
      const validTake = take && take.samples instanceof Float32Array && Number.isFinite(take.sampleRate) && take.sampleRate >= 8000 && take.sampleRate <= 96000 && Number.isFinite(take.position) && take.position >= 0 && take.position <= 299 && take.samples.length > 0 && take.samples.length <= 301 * take.sampleRate;
      const matching = saved.schema === 1 && saved.base === baseRevision;
      const validEdits = Array.isArray(saved.tracks) && saved.tracks.length === tracks.length && new Set(saved.tracks.map(item => item.id)).size === tracks.length && saved.tracks.every(item => tracks.some(track => track.id === item.id) && ["gain", "offset", "trim_start", "trim_end"].every(key => Number.isFinite(item[key]) && item[key] >= 0 && item[key] <= (key === "gain" ? 2 : 300)) && typeof item.muted === "boolean");
      if (!take && !saved.tracks?.length) return;
      recoveryWaiting = true; recoveryMessage("Recovery copy found. Choose Restore or Discard to continue."); document.getElementById("recovery-panel").hidden = false;
      const info = document.getElementById("recovery-info");
      info.textContent = matching ? "A local recovery copy is available from " + new Date(saved.savedAt).toLocaleString() + (validTake ? ", including an unfinished vocal take." : ".") : "This project has changed on GGenre since the recovery copy was saved. Older track edits will not replace the current project.";
      const restore = document.getElementById("restore-draft");
      restore.textContent = matching ? "Restore local work" : "Recover vocal take only"; restore.disabled = !(matching && validEdits) && !validTake;
      restore.addEventListener("click", () => {
        recoveryWaiting = false; document.getElementById("recovery-panel").hidden = true;
        if (matching && validEdits) { for (const item of saved.tracks) { const track = tracks.find(track => track.id === item.id); for (const key of ["gain", "offset", "trim_start", "trim_end", "muted"]) track[key] = item[key]; if (typeof item.name === "string" && item.name.trim() && item.name.length <= 100) track.name = item.name.trim(); syncTrackInputs(track); } changed(); }
        if (matching && voiceTools && Number.isInteger(saved.tempo) && saved.tempo >= 40 && saved.tempo <= 240) document.getElementById("tempo").value = saved.tempo;
        if (validTake) showTake(take, Number(saved.correction) || 0); rememberVoiceSettings();
        controls(); timeline?.render(); persistDraft(); message("Local work recovered. Review it before saving a mix to GGenre.");
      });
      document.getElementById("discard-draft").addEventListener("click", async () => {
        if (!confirm("Discard the local recovery copy? Your saved GGenre project stays unchanged.")) return;
        await clearDraft(); recoveryWaiting = false; document.getElementById("recovery-panel").hidden = true; controls();
      });
    } catch (_) { recoveryMessage("Local recovery is unavailable. Keep this tab open until your work is saved to GGenre."); }
    finally { recovering = false; controls(); }
  }
  if (typeof StudioOrientation !== "undefined") {
    orientation = StudioOrientation.mount({root, gate: document.getElementById("studio-orientation-gate"), stop: stopTransport, cancel: cancelCurrentTake});
  }
  if (timeline) timeline.setPosition(Number(document.getElementById("record-position").value) || 0);
  initializeRecovery();
  let audioDevicePicker;
  const inputModeSelect=document.getElementById("studio-input-mode"),audioDeviceSelect=document.getElementById("studio-audio-device"),findInputs=document.getElementById("studio-find-inputs");
  if(inputModeSelect){try{if(!isAcapella&&new URLSearchParams(location.search||"").get("input")==="keyboard"){inputModeSelect.value="keyboard";inputModeSelect.dispatchEvent?.(new Event("change",{bubbles:true}));}}catch(_){}inputModeSelect.addEventListener("change",updateInputMode);updateInputMode();}
  if(audioDeviceSelect&&findInputs&&typeof StudioInputs!=="undefined")audioDevicePicker=StudioInputs.mount({media:navigator.mediaDevices,select:audioDeviceSelect,scan:findInputs,status:text=>{const label=document.getElementById("studio-input-status");if(label)label.textContent=text;},enabled:()=>!session&&!preparing&&!busy&&!pendingTake});
  window.addEventListener("pagehide", () => { audioDevicePicker?.dispose(); referenceGuide?.stop(); session?.cancel(); });
  window.addEventListener("beforeunload", event => { if (dirty || session || preparing || pendingTake) { event.preventDefault(); event.returnValue = ""; } });
})();
