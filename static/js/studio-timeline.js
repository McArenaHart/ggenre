(function (scope) {
  "use strict";
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function edit(track, duration, kind, delta) {
    const start = Number(track.trim_start), end = Number(track.trim_end) || duration, offset = Number(track.offset);
    if (![duration, delta, start, end, offset].every(Number.isFinite) || duration <= 0 || start < 0 || end <= start || end > duration + .02 || offset < 0) throw new Error("Fix the numeric trim settings before dragging this track.");
    const length = end - start, result = {...track};
    if (kind === "move") result.offset = clamp(offset + delta, 0, Math.max(0, 300 - length));
    else if (kind === "left") {
      const change = clamp(delta, Math.max(-start, -offset), length - .05);
      result.trim_start = start + change; result.offset = offset + change;
    } else if (kind === "right") result.trim_end = clamp(end + delta, start + .05, Math.min(duration, 300 - offset + start));
    else throw new Error("Unknown timeline edit.");
    for (const key of ["offset", "trim_start", "trim_end"]) result[key] = Math.round(result[key] * 1000) / 1000;
    return result;
  }
  function peaks(buffer, count = 1600) {
    const channels = Array.from({length: buffer.numberOfChannels || 1}, (_, index) => buffer.getChannelData(index));
    const samples = channels[0], output = []; count = Math.min(count, samples.length);
    for (let bin = 0; bin < Math.min(count, samples.length); bin++) {
      const from = Math.floor(bin * samples.length / count), to = Math.max(from + 1, Math.floor((bin + 1) * samples.length / count));
      let peak = 0; for (let i = from; i < to; i++) for (const channel of channels) peak = Math.max(peak, Math.abs(channel[i]));
      output.push(peak);
    }
    return output;
  }
  class Timeline {
    constructor({container, tracks, load, onChange, onSeek, locked, onError, category = ""}) {
      Object.assign(this, {container, tracks, load, onChange, onSeek, locked, onError, category});
      this.zoom = 16; this.rows = new Map(); this.position = 0;
      const header = document.createElement("div"); header.className = "studio-timeline-header";
      const heading = document.createElement("h2"); heading.textContent = "Arrangement";
      const tools = document.createElement("div"); tools.className = "studio-timeline-tools";
      const tips = document.createElement("details"); tips.className = "studio-timeline-help";
      const summary = document.createElement("summary"); summary.textContent = "Editing tips";
      const help = document.createElement("p"); help.textContent = "Drag clips to move them. Drag their edges to trim. Click the ruler to set your starting position. Zoom in for short clips. Waveforms are scaled for visibility; numeric timing controls are in each track's Timing menu.";
      tips.append(summary, help);
      const label = document.createElement("label"); label.textContent = "Zoom";
      this.scale = document.createElement("input"); this.scale.type = "range"; this.scale.min = "4"; this.scale.max = "64"; this.scale.value = String(this.zoom); this.scale.setAttribute("aria-label", "Timeline zoom");
      this.scale.addEventListener("input", () => { this.zoom = Number(this.scale.value); this.render(); }); label.append(this.scale);
      tools.append(tips, label); header.append(heading, tools);
      this.scroll = document.createElement("div"); this.scroll.className = "studio-timeline-scroll"; this.scroll.tabIndex = 0;
      this.ruler = document.createElement("div"); this.ruler.className = "studio-ruler";
      this.ruler.addEventListener("click", event => { if (!this.locked()) this.onSeek(clamp((event.clientX - this.ruler.getBoundingClientRect().left) / this.zoom, 0, 299)); });
      this.scroll.append(this.ruler); container.append(header, this.scroll);
      this.playheads = [];
      if (!tracks.length) {
        const empty = document.createElement("div"); empty.className = "studio-empty-arrangement";
        const wave = document.createElement("div"); wave.className = "studio-empty-wave"; wave.setAttribute("aria-hidden", "true");
        for (let i = 0; i < 7; i++) wave.append(document.createElement("b"));
        const title = document.createElement("h3"); title.textContent = "Make room for your sound";
        const text = document.createElement("p"); text.textContent = category === "acapella" ? "Record your first voice or import a vocal layer." : "Record your first vocal or bring in a beat.";
        const importLabel = document.createElement("label"); importLabel.htmlFor = "import"; importLabel.textContent = category === "acapella" ? "+ Import vocal" : "+ Import audio";
        empty.append(wave, title, text, importLabel); this.scroll.append(empty);
      }
      if (typeof scope.addEventListener === "function") scope.addEventListener("resize", () => this.render());
      for (const track of tracks) this.add(track);
      this.render();
    }
    async add(track) {
      const row = document.createElement("div"); row.className = "studio-lane"; row.dataset.tone = String(this.tracks.indexOf(track) % 3);
      const clip = document.createElement("div"); clip.className = "studio-clip";
      const title = document.createElement("span"); title.className = "studio-clip-name"; title.textContent = track.name;
      const canvas = document.createElement("canvas"); canvas.height = 64; canvas.setAttribute("aria-label", track.name + " waveform");
      const left = document.createElement("span"), right = document.createElement("span");
      left.className = "studio-trim studio-trim-left"; right.className = "studio-trim studio-trim-right";
      left.title = "Drag to trim the beginning"; right.title = "Drag to trim the end";
      clip.append(canvas, title, left, right); row.append(clip); this.scroll.append(row);
      const state = {track, row, clip, canvas, title}; this.rows.set(track.id, state);
      clip.addEventListener("pointerdown", event => {
        if (this.locked() || !state.buffer || event.button !== 0) return;
        const original = {...track}, startX = event.clientX;
        const kind = event.target === left ? "left" : event.target === right ? "right" : "move";
        try { edit(original, state.buffer.duration, kind, 0); } catch (error) { this.onError(error); return; }
        event.preventDefault(); clip.setPointerCapture(event.pointerId);
        const move = next => {
          try { Object.assign(track, edit(original, state.buffer.duration, kind, (next.clientX - startX) / this.zoom)); this.render(); this.onChange(track); }
          catch (error) { this.onError(error); }
        };
        const finish = () => { clip.removeEventListener("pointermove", move); clip.removeEventListener("pointerup", finish); clip.removeEventListener("pointercancel", cancel); };
        const cancel = () => { Object.assign(track, original); this.render(); this.onChange(track); finish(); };
        clip.addEventListener("pointermove", move); clip.addEventListener("pointerup", finish); clip.addEventListener("pointercancel", cancel);
      });
      try { state.buffer = await this.load(track); state.peaks = peaks(state.buffer); state.peakScale = Math.max(.001, ...state.peaks); this.render(); }
      catch (error) { title.textContent = track.name + " — waveform unavailable"; this.onError(error); }
    }
    setPosition(value) { this.position = value; this.playhead = value; this.render(); }
    setPlayhead(value) { this.playhead = value; for (const line of this.playheads) line.style.left = value * this.zoom + "px"; }
    render() {
      let duration = Math.max(30, this.position + 3, (this.scroll.clientWidth || 0) / this.zoom);
      for (const {track, buffer} of this.rows.values()) if (buffer) duration = Math.max(duration, Number(track.offset) + (Number(track.trim_end) || buffer.duration) - Number(track.trim_start) + 3);
      duration = Math.min(300, Math.ceil(duration / 5) * 5);
      const width = duration * this.zoom;
      this.playheads = []; this.ruler.style.width = width + "px"; this.ruler.replaceChildren();
      const step = this.zoom >= 16 ? 5 : 15;
      for (let seconds = 0; seconds <= duration; seconds += step) { const tick = document.createElement("span"); tick.style.left = seconds * this.zoom + "px"; tick.textContent = seconds + "s"; this.ruler.append(tick); }
      const marker = document.createElement("span"); marker.className = "studio-position"; marker.style.left = this.position * this.zoom + "px"; marker.textContent = "▼"; this.ruler.append(marker);
      for (const state of this.rows.values()) {
        const {track, buffer, row, clip, canvas} = state; state.title.textContent = track.name; canvas.setAttribute("aria-label", track.name + " waveform"); row.style.width = width + "px";
        if (!buffer) continue;
        const from = Number(track.trim_start), to = Number(track.trim_end) || buffer.duration;
        const clipWidth = Math.max(12, (to - from) * this.zoom);
        clip.style.left = Number(track.offset) * this.zoom + "px"; clip.style.width = clipWidth + "px"; clip.style.opacity = track.muted ? ".35" : "1";
        canvas.width = Math.min(4096, Math.ceil(clipWidth)); canvas.style.width = "100%";
        const context = canvas.getContext("2d"); context.clearRect(0, 0, canvas.width, 64); context.strokeStyle = ["#9ce6d8", "#d8c8ff", "#f3d7aa"][Number(row.dataset.tone)] || "#9ce6d8"; context.beginPath();
        for (let x = 0; x < canvas.width; x++) {
          const time = from + (to - from) * x / canvas.width;
          const index = Math.min(state.peaks.length - 1, Math.floor(time / buffer.duration * state.peaks.length));
          const amplitude = Math.min(1, (state.peaks[index] || 0) / state.peakScale * Number(track.gain)) * 27;
          context.moveTo(x, 32 - Math.max(1, amplitude)); context.lineTo(x, 32 + Math.max(1, amplitude));
        }
        context.stroke();
        if (!state.playhead) { state.playhead = document.createElement("span"); state.playhead.className = "studio-playhead"; state.playhead.setAttribute("aria-hidden", "true"); row.append(state.playhead); }
        state.playhead.style.left = (this.playhead ?? this.position) * this.zoom + "px"; this.playheads.push(state.playhead);
      }
    }
  }
  const api = {Timeline, edit, peaks};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else scope.StudioTimeline = api;
})(typeof window !== "undefined" ? window : globalThis);
