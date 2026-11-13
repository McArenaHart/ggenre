/* Offline tools keep source recordings intact. No audio leaves this server. */
window.StudioProcessing = {
  mount(card, track, api) {
    const panel = document.createElement("details");
    panel.className = "studio-track-edit studio-audio-tools";
    const heading = document.createElement("summary"); heading.textContent = "Tools"; heading.title = "Audio tools";
    const body = document.createElement("div"); body.className = "studio-track-edit-panel";
    panel.append(heading, body); card.querySelector(".studio-track-actions").append(panel);
    function select(label, values) {
      const wrapper = document.createElement("label"), input = document.createElement("select");
      wrapper.textContent = label;
      for (const [value, text] of values) { const option = document.createElement("option"); option.value = value; option.textContent = text; input.append(option); }
      wrapper.append(input); body.append(wrapper); return input;
    }
    const operations = [["denoise", "Reduce noise"]];
    if (track.kind === "vocal") operations.push(["tune", "Vocal pitch correction"]);
    if (!api.isAcapella) operations.push(["separate", "Extract instrumental"]);
    const operation = select("Tool", operations);
    const strength = select("Noise reduction", [["6", "Gentle · 6 dB"], ["10", "Medium · 10 dB"], ["18", "Strong · 18 dB"]]);
    const cutoff = select("Rumble cutoff", [["40", "40 Hz · bass voices"], ["60", "60 Hz"], ["100", "100 Hz"]]);
    const hum = select("Electrical hum", [["off", "Off"], ["50", "50 Hz"], ["60", "60 Hz"]]);
    const key = select("Song key", ["C", "C♯ / D♭", "D", "D♯ / E♭", "E", "F", "F♯ / G♭", "G", "G♯ / A♭", "A", "A♯ / B♭", "B"].map((v, i) => [String(i), v]));
    const scale = select("Scale", [["major", "Major"], ["minor", "Natural minor"], ["chromatic", "Chromatic"]]);
    const amount = select("Correction strength", [["0.5", "Gentle · 50%"], ["0.8", "Firm · 80%"], ["1", "Full · 100%"]]);
    const speed = select("Retune speed", [["100", "Smooth · 100 ms"], ["40", "Fast · 40 ms"], ["0", "Immediate effect"]]);
    const permission = document.createElement("label"), consent = document.createElement("input"); consent.type = "checkbox";
    permission.append(consent, " I have permission to reuse this recording."); body.append(permission);
    const note = document.createElement("p"); note.textContent = "Process after recording. Noise reduction targets steady hiss, rumble and hum. Strong settings may affect the voice. Tune one voice at a time; skip vocal percussion. Extraction may leave vocal bleed. Unused processing previews may expire after 30 days; apply or save a result to keep it."; body.append(note);
    const run = document.createElement("button"); run.type = "button";
    function update() {
      for (const control of [strength, cutoff, hum]) control.parentElement.hidden = operation.value !== "denoise";
      for (const control of [key, scale, amount, speed]) control.parentElement.hidden = operation.value !== "tune";
      permission.hidden = operation.value !== "separate";
      run.textContent = operation.value === "separate" ? "Extract instrumental" : "Process a copy";
    }
    operation.addEventListener("change", update); update();
    const status = document.createElement("p"); status.setAttribute("role", "status");
    const progress = document.createElement("progress");
    progress.max = 100;
    progress.hidden = true;
    progress.style.width = "100%";
    progress.setAttribute("aria-label", "Instrumental extraction progress");
    const preview = document.createElement("audio"); preview.controls = true; preview.controlsList = 'nodownload'; preview.hidden = true;
    preview.addEventListener("play", () => card.querySelectorAll("audio").forEach(p => { if (p !== preview) p.pause(); }));
    const apply = document.createElement("button"); apply.type = "button"; apply.textContent = "Use processed track"; apply.hidden = true;
    const library = document.createElement("button"); library.type = "button"; library.textContent = "Save to instrumental library"; library.hidden = true;
    const arrange = document.createElement('a'); arrange.textContent = 'Edit intro / middle / outro'; arrange.className = 'studio-button studio-outline'; arrange.hidden = true;
    body.append(run, status, progress, preview, apply, library, arrange);
    const close = document.createElement("button"); close.type = "button";
    close.className = "studio-audio-tools-close"; close.textContent = "Close audio tools";
    close.addEventListener("click", () => { panel.open = false; }); body.append(close);
    let jobId = track.audio_job || null, timer, jobOperation = track.audio_operation;
    function updateProgress(jobStatus) {
      progress.hidden = jobOperation !== "separate" || !["queued", "running", "ready"].includes(jobStatus);
      if (jobStatus === "running") progress.removeAttribute("value");
      else progress.value = jobStatus === "ready" ? 100 : 0;
    }
    async function poll() {
      if (document.hidden) { timer = setTimeout(poll, 5000); return; }
      const requestedJob = jobId;
      try {
        const response = await fetch(`/studio/audio-jobs/${requestedJob}/`, {cache: "no-store"});
        if (requestedJob !== jobId) return;
        if (!response.ok) throw new Error("Unable to read processing status. Reload to reconnect.");
        const job = await response.json();
        if (requestedJob !== jobId) return;
        updateProgress(job.status);
        status.textContent = job.error || {
          queued: "Waiting for the audio worker. You can close these tools and return later.",
          running: jobOperation === "separate"
            ? "Extracting the instrumental. Full songs can take several minutes on this server."
            : "Processing the recording. You can close these tools and return later.",
        }[job.status] || `Audio task: ${job.status}.`;
        if (job.status === "ready") {
          preview.src = job.url; preview.hidden = apply.hidden = false;
          library.hidden = jobOperation !== "separate";
          arrange.hidden = jobOperation !== 'separate'; arrange.href = `/studio/audio-jobs/${jobId}/arrange/`;
          status.textContent = "Ready. Compare using the original track's play button. Applying mutes the original and adds a separate track.";
          return;
        }
        if (["failed", "applied", "expired"].includes(job.status)) { run.disabled = false; return; }
        timer = setTimeout(poll, 3000);
      } catch (error) { if (requestedJob === jobId) { updateProgress(null); status.textContent = error.message; run.disabled = false; } }
    }
    const runTask = action => api.task(async () => {
      try { await action(); }
      catch (error) { status.textContent = error.message; throw error; }
    });
    run.addEventListener("click", () => runTask(async () => {
      const selectedOperation = operation.value;
      if (selectedOperation === "separate" && !consent.checked) throw new Error("Confirm you have permission to reuse this recording.");
      const data = new FormData(); data.append("operation", selectedOperation);
      data.append("strength", selectedOperation === "tune" ? amount.value : strength.value);
      for (const [name, value] of Object.entries({key: key.value, scale: scale.value, speed: speed.value, cutoff: cutoff.value, hum: hum.value, permission: consent.checked ? "yes" : "no"})) data.append(name, value);
      const job = await api.post(`/studio/track/${track.id}/process/`, data); jobId = job.id; jobOperation = selectedOperation;
      clearTimeout(timer); preview.hidden = apply.hidden = library.hidden = arrange.hidden = true;
      updateProgress("queued");
      status.textContent = "Queued. You may continue editing; save edits before applying the result. Processing requires the audio worker.";
      timer = setTimeout(poll, 3000);
    }));
    for (const button of [apply, library]) button.addEventListener("click", () => runTask(async () => {
      if (!api.canApply()) throw new Error("Save your mix and keep or discard the pending take before applying audio processing.");
      const data = new FormData(); data.append("revision", api.revision()); data.append("library", button === library ? "yes" : "no");
      await api.post(`/studio/audio-jobs/${jobId}/apply/`, data);
      if (button === library) location.href = '/studio/instrumentals/'; else location.reload();
    }));
    if (jobId) { panel.open = true; poll(); }
    window.addEventListener("pagehide", () => clearTimeout(timer), {once: true});
    return {
      open(tool) {
        if (!operations.some(([value]) => value === tool)) return false;
        operation.value = tool; update(); panel.open = true;
        return true;
      }
    };
  }
};
