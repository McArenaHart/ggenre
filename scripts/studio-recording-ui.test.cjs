const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const helpers = require("../static/js/studio-audio.js");

function harness(options = {}) {
  const elements = [], byId = {}, windowEvents = {}, posted = [];
  class Element {
    constructor(tag = "div", id = "") { this.tagName = tag.toUpperCase(); this.id = id; this.dataset = {}; this.classList = {toggle(){}}; this.events = {}; this.children = []; this.disabled = false; this.hidden = false; this.value = ""; this.textContent = ""; this.controls = true; this.paused = true; this.currentTime = 0; elements.push(this); if (id) byId[id] = this; }
    set src(value) { this.source = value; this.currentTime = 0; }
    get src() { return this.source; }
    setAttribute(name, value) { this[name] = value; }
    append(...children) { this.children.push(...children); }
    addEventListener(name, handler) { this.events[name] = handler; }
    async trigger(name = "click") { if (name === "click" && this.disabled) return; return this.events[name]?.({target: this, preventDefault: () => { this.prevented = true; }}); }
    matches(selector) { return selector === "audio" && this.tagName === "AUDIO"; }
    querySelector() { return {value: "csrf"}; }
    querySelectorAll(selector) {
      if (selector === 'label[for="import"]') return elements.filter(e => e.tagName === "LABEL" && e.htmlFor === "import");
      if (selector === "[data-saved-action]") return [byId.publish, byId.export];
      if (selector === "[data-track-remove]") return elements.filter(e => e.dataset.trackRemove !== undefined);
      if (selector === "[data-voice-part]") return elements.filter(e => e.dataset.voicePart !== undefined);
      if (selector === "[data-voice-solo]") return elements.filter(e => e.dataset.voiceSolo !== undefined);
      if (selector === "audio") return elements.filter(e => e.tagName === "AUDIO");
      return elements.filter(e => ["BUTTON", "INPUT", "SELECT", "AUDIO"].includes(e.tagName));
    }
    pause() { this.paused = true; this.events.pause?.(); } async play() { this.paused = false; this.events.play?.(); } removeAttribute(name) { delete this[name]; }
  }
  if(options.inputMode){new Element("select","studio-input-mode").value=options.inputMode;new Element("select","studio-audio-device").value="interface-1";new Element("select","studio-audio-channel").value="right";}
  const root = new Element("div", "studio"); root.dataset = {category: options.category || "secular", project: "7", user: "artist7", revision: "rev1", hasMix: "true", workletUrl: "worklet.js"};
  for (const id of ["status", "tracks", "take-info", "session-clock", "play-label"]) new Element("div", id);
  for (const id of ["record", "stop", "preview", "save", "rewind", "cancel-recording", "keep-take", "retry-take", "discard-take", "audition-take", "publish", "export"]) new Element("button", id);
  for (const [id, value] of [["track-name", "Harmony"], ["record-position", "12.5"], ["tempo", "80"], ["count-in", "4"], ["delay-correction", "0"]]) { const element = new Element("input", id); element.value = value; }
  new Element("input", "import"); new Element("meter", "input-meter"); new Element("span", "level-label");
  for (const id of ["import-track-label", "import-zone-label"]) new Element("label", id).htmlFor = "import";
  new Element("select", "import-kind").value = options.importKind || "backing";
  new Element("audio", "mix-preview"); new Element("audio", "take-preview");
  new Element("button", "auto-master").dataset.url = "/studio/project/7/master/";
  new Element("audio", "master-preview").hidden = true;
  new Element("button", "save-master").hidden = true;
  new Element("div", "take-review").hidden = true; byId.stop.disabled = true; byId["cancel-recording"].hidden = true; byId["cancel-recording"].disabled = true;
  const tracks = options.tracks || [{id: 1, name: "Beat", url: "private.wav", gain: 1, offset: 0, trim_start: 0, trim_end: 0, muted: false}];
  new Element("script", "studio-tracks").textContent = JSON.stringify(tracks);
  let inputConstraints, decodeCalls = 0;
  let recordingOptions, failUpload = false, reloads = 0, cancelled = 0, micStops = 0, beginCalls = 0; const drafts = [];
  if (options.recovery) { for (const id of ["recovery-panel", "recovery-info", "recovery-status"]) new Element("div", id); byId["recovery-panel"].hidden = true; for (const id of ["restore-draft", "discard-draft"]) new Element("button", id); }
  function buffer(channels = 1, length = 4410, sampleRate = 44100) {
    const samples = Array.from({length: channels}, () => new Float32Array(length));
    return {numberOfChannels: channels, length, sampleRate, duration: length / sampleRate, getChannelData: c => samples[c], copyToChannel: (data, c) => samples[c].set(data)};
  }
  const stream = {getTracks: () => [{stop() { micStops++; }}], getAudioTracks: () => [{getSettings: () => ({})}]};
  const sandbox = {StudioInputs:require("../static/js/studio-inputs.js"), StudioVoices: require("../static/js/studio-voices.js"), sessionStorage: {getItem: () => null, setItem(){}}, setTimeout: (fn, ms) => { if (options.onUploadWait && ms === 120000) { options.onUploadWait(fn); return undefined; } return setTimeout(fn, options.decodeHangOnce && ms === 20000 ? 5 : ms); }, clearTimeout, document: {getElementById: id => byId[id], createElement: tag => new Element(tag)}, window: {AudioWorkletNode: class {}, addEventListener: (name, callback) => windowEvents[name] = callback},
    navigator: {mediaDevices: {getUserMedia: async constraints => {inputConstraints=constraints;return options.microphone || stream;}}}, AudioContext: class {constructor() { this.sampleRate = 44100; } async resume() {} createBuffer(...args) { return buffer(...args); } async decodeAudioData() { if (++decodeCalls <= (options.decodeRejects || 0)) throw new Error("Unsupported browser codec"); return buffer(); }},
    StudioAudio: {...helpers, async begin(given) { beginCalls++; recordingOptions = given; if (options.preparation) await options.preparation; return {stop() { recordingOptions.onDone({samples: new Float32Array(4410), sampleRate: 44100, position: given.position}); }, cancel() { cancelled++; }}; }},
    OfflineAudioContext: class {async decodeAudioData() { decodeCalls++; if (options.decodeHangOnce && decodeCalls === 1) return new Promise(() => {}); if (decodeCalls <= (options.decodeRejects || 0)) throw new Error("Unsupported browser codec"); return buffer(); } createBufferSource() { return {connect(node) { return node; }, start() {}}; } createGain() { return {gain: {value: 1}, connect() {}}; } async startRendering() { return buffer(2); }},
    location: {reload() { reloads++; }}, URL: {createObjectURL: () => "blob:test", revokeObjectURL() {}}, Blob, FormData, Float32Array, DataView, ArrayBuffer, Number, Math, JSON, confirm: () => true,
    fetch: async (url, request) => { if (!request) return {ok: true, arrayBuffer: async () => new ArrayBuffer(44)}; posted.push({url, body: request.body}); if (url === "/studio/project/7/master/") return {ok: true, headers: {get: () => "audio/wav"}, blob: async () => new Blob(["mastered"], {type: "audio/wav"})}; if (url === "/studio/audio/convert/") return {ok: !options.convertFail, blob: async () => new Blob(["converted"]), json: async () => ({error: "Audio conversion failed"})}; if (options.trackResponse && url === "/studio/project/7/track/") return options.trackResponse; return {ok: !failUpload, json: async () => failUpload ? {error: "Upload failed; retry"} : {ok: true}}; }};
  if (options.recovery) sandbox.StudioDrafts = class {
    async read() { return options.snapshot; }
    async write(value) { if (options.failRecovery) throw new Error("Quota exceeded"); drafts.push(structuredClone(value)); }
    async clear() { drafts.push(null); }
  };
  vm.createContext(sandbox); vm.runInContext(fs.readFileSync(require.resolve("../static/js/studio.js"), "utf8"), sandbox);
  return {constraints:()=>inputConstraints, decodeCalls:()=>decodeCalls, byId, elements, posted, windowEvents, options: () => recordingOptions, drafts, stream, cancelled: () => cancelled, micStops: () => micStops, beginCalls: () => beginCalls, ready: () => new Promise(resolve => setImmediate(resolve)), fail() { failUpload = true; }, succeed() { failUpload = false; }, reloads: () => reloads};
}
test("import preserves filename, selected vocal kind, timeline position and existing edits", async () => {
  const h = harness({importKind: "vocal"});
  const original = Object.assign(new Blob(["compressed audio"], {type: "audio/mpeg"}), {name: "My harmony.mp3"});
  h.byId.import.files = [original];
  await h.byId.import.trigger("change");
  assert.equal(h.posted.length, 1);
  const data = h.posted[0].body;
  assert.equal(data.get("name"), "My harmony");
  assert.equal(data.get("kind"), "vocal");
  assert.equal(data.get("original_file"), "1");
  assert.equal(data.get("offset"), "12.5");
  assert.equal(data.get("revision"), "rev1");
  assert.equal(JSON.parse(data.get("tracks"))[0].id, 1);
  assert.equal(data.get("audio").type, "audio/mpeg");
  assert.equal(data.get("audio").size, original.size);
  assert.equal(await data.get("audio").text(), "compressed audio");
  assert.equal(h.reloads(), 1);
  assert.equal(h.decodeCalls(), 0, "Import uploads the original without browser decoding or WAV expansion");
});

test("imports avoid a stalled browser decoder and send the original file once", async () => {
  const h = harness({decodeHangOnce:true});
  h.byId.import.files = [Object.assign(new Blob(["song"]), {name:"Song.mp3"})];
  await h.byId.import.trigger("change");
  assert.equal(h.posted[0].url,"/studio/project/7/track/");
  assert.equal(h.posted.length,1);
  assert.equal(h.decodeCalls(),0);
  assert.equal(h.reloads(),1);
  assert.equal(h.byId.preview.disabled,false);
  assert.equal(h.byId.import.disabled,false);
});

test("browser codec support does not cause a conversion download and second upload", async () => {
  const h = harness({decodeRejects: 1});
  h.byId.import.files = [Object.assign(new Blob(["audio"]), {name: "Backing.flac"})];
  await h.byId.import.trigger("change");
  assert.equal(h.posted.length, 1);
  assert.equal(h.posted[0].url, "/studio/project/7/track/");
  assert.equal(h.posted[0].body.get("kind"), "backing");
  assert.equal(h.reloads(), 1);
});

test("failed import permits selecting the same file again without changing the project", async () => {
  const h = harness({decodeRejects: 1, convertFail: true});
  h.byId.import.files = [Object.assign(new Blob(["audio"]), {name: "Bad.m4a"})];
  h.byId.import.value = "selected-file";
  h.fail();
  await h.byId.import.trigger("change");
  assert.match(h.byId.status.textContent, /Upload failed/);
  assert.equal(h.byId.import.value, "");
  assert.equal(h.byId.import.disabled, false);
  assert.equal(h.posted.length, 1);
  assert.equal(h.reloads(), 0);
});

test("Acapella forces imported files to vocal tracks", async () => {
  const h = harness({category: "acapella", importKind: "backing"});
  h.byId.import.files = [Object.assign(new Blob(["audio"]), {name: "Bass.wav"})];
  await h.byId.import.trigger("change");
  assert.equal(h.posted[0].body.get("kind"), "vocal");
});

test("a slow upload stays locked and handles success after the two-minute notice", async () => {
  let complete, waitingNotice;
  const trackResponse = new Promise(resolve => { complete = resolve; });
  const h = harness({trackResponse, onUploadWait: callback => { waitingNotice = callback; }});
  h.byId.import.files = [Object.assign(new Blob(["audio"]), {name: "Slow.wav"})];
  const pending = h.byId.import.trigger("change");
  await h.ready();
  waitingNotice(); await h.ready();
  try {
    assert.equal(h.byId.import.disabled, true);
    assert.match(h.byId.status.textContent, /Still uploading/i);
    await h.byId.import.trigger("change");
    assert.equal(h.posted.length, 1);
  } finally { complete({ok: true, json: async () => ({ok: true})}); await pending; }
  assert.equal(h.reloads(), 1);
});

test("a server rejection after the slow-upload notice preserves the take for retry", async () => {
  let complete, waitingNotice;
  const trackResponse = new Promise(resolve => { complete = resolve; });
  const h = harness({trackResponse, onUploadWait: callback => { waitingNotice = callback; }});
  await h.byId.record.trigger(); await h.byId.stop.trigger();
  const pending = h.byId["keep-take"].trigger();
  await h.ready(); waitingNotice(); await h.ready();
  complete({ok: false, json: async () => ({error: "Track limit reached"})}); await pending;
  assert.match(h.byId.status.textContent, /Track limit reached/);
  assert.equal(h.byId["take-review"].hidden, false);
  assert.equal(h.byId["keep-take"].disabled, false);
  assert.equal(h.reloads(), 0);
});

test("recording locks controls, preserves the timeline, and unlocks take review", async () => {
  const h = harness(); await h.byId.record.trigger();
  assert.equal(h.options().position, 12.5); assert.equal(h.options().countIn, 4);
  assert.equal(h.byId.record.disabled, true); assert.equal(h.byId.stop.disabled, false);
  assert.equal(h.byId["mix-preview"].controls, false);
  await h.byId.stop.trigger();
  assert.equal(h.byId["take-review"].hidden, false); assert.equal(h.byId["keep-take"].disabled, false);
  assert.equal(h.byId.save.disabled, true); assert.equal(h.posted.length, 0);
  assert.equal(h.byId["mix-preview"].controls, true);
});

test("import labels explain unfinished takes instead of silently ignoring clicks", async () => {
  const h = harness(); await h.byId.record.trigger(); await h.byId.stop.trigger();
  assert.equal(h.byId.import.disabled, true);
  await h.byId["import-track-label"].trigger();
  assert.equal(h.byId["import-track-label"].prevented, true);
  assert.match(h.byId.status.textContent, /Keep or discard the unfinished take/);
});

test("import labels explain pending recovery and allow the picker once resolved", async () => {
  const h = harness({recovery: true, snapshot: recoverySnapshot()}); await h.ready();
  await h.byId["import-zone-label"].trigger();
  assert.match(h.byId.status.textContent, /Restore or Discard/);
  await h.byId["restore-draft"].trigger();
  h.byId["import-zone-label"].prevented = false;
  await h.byId["import-zone-label"].trigger();
  assert.equal(h.byId["import-zone-label"].prevented, false);
  assert.equal(h.byId.import.disabled, false);
});
test("keeping the vocal sends its offset and current backing-track edits", async () => {
  const h = harness();
  const gain = h.elements.find(e => e.dataset.trackField === "gain");
  gain.value = "0.45"; await gain.trigger("input");
  await h.byId.record.trigger(); await h.byId.stop.trigger(); await h.byId["keep-take"].trigger();
  assert.equal(h.posted.length, 1); assert.equal(h.posted[0].body.get("offset"), "12.5");
  assert.equal(JSON.parse(h.posted[0].body.get("tracks"))[0].gain, .45);
  assert.equal(h.reloads(), 1);
});
test("failed upload preserves the take and allows retry without re-recording", async () => {
  const h = harness(); await h.byId.record.trigger(); await h.byId.stop.trigger();
  h.fail(); await h.byId["keep-take"].trigger();
  assert.equal(h.byId["take-review"].hidden, false); assert.equal(h.reloads(), 0);
  assert.match(h.byId.status.textContent, /Upload failed/);
  h.succeed(); await h.byId["keep-take"].trigger(); assert.equal(h.reloads(), 1);
});
test("cancelling the count-in restores editing without creating a take", async () => {
  const h = harness(); await h.byId.record.trigger();
  h.options().onDone({samples: new Float32Array(0), sampleRate: 44100, position: 12.5});
  assert.equal(h.byId["take-review"].hidden, true); assert.equal(h.byId.record.disabled, false);
  assert.equal(h.byId.save.disabled, false); assert.equal(h.byId.publish.disabled, false);
  assert.equal(h.posted.length, 0);
});
test("discarding a take leaves saved audio and export eligibility unchanged", async () => {
  const h = harness(); await h.byId.record.trigger(); await h.byId.stop.trigger(); await h.byId["discard-take"].trigger();
  assert.equal(h.byId["take-review"].hidden, true); assert.equal(h.byId.record.disabled, false);
  assert.equal(h.byId.export.disabled, false); assert.equal(h.posted.length, 0);
});

function recoverySnapshot(overrides = {}) {
  return {schema: 1, base: "rev1", savedAt: Date.now(), tracks: [{id: 1, gain: .3, offset: 4, trim_start: 0, trim_end: 0, muted: false}], ...overrides};
}
test("local edits are offered for restore and do not overwrite the server automatically", async () => {
  const h = harness({recovery: true, snapshot: recoverySnapshot()}); await h.ready();
  assert.equal(h.byId["recovery-panel"].hidden, false); assert.equal(h.byId.record.disabled, true);
  const gain = h.elements.find(e => e.dataset.trackField === "gain");
  assert.equal(Number(gain.value), 1);
  await h.byId["restore-draft"].trigger();
  assert.equal(Number(gain.value), .3); assert.equal(h.byId.record.disabled, false);
  assert.equal(h.byId.publish.disabled, true); assert.equal(h.posted.length, 0);
});
test("an unfinished take is recovered into review without uploading", async () => {
  const take = {name: "Recovered", samples: new Float32Array(4410), sampleRate: 44100, position: 2};
  const h = harness({recovery: true, snapshot: recoverySnapshot({take})}); await h.ready(); await h.byId["restore-draft"].trigger();
  assert.equal(h.byId["take-review"].hidden, false); assert.equal(h.byId["keep-take"].disabled, false);
  assert.equal(h.byId.record.disabled, true); assert.equal(h.posted.length, 0);
});
test("stale recovery preserves current server edits while allowing vocal recovery", async () => {
  const take = {name: "Recovered", samples: new Float32Array(4410), sampleRate: 44100, position: 2};
  const h = harness({recovery: true, snapshot: recoverySnapshot({base: "old", take})}); await h.ready();
  assert.match(h.byId["restore-draft"].textContent, /take only/);
  await h.byId["restore-draft"].trigger();
  assert.equal(Number(h.elements.find(e => e.dataset.trackField === "gain").value), 1);
  assert.equal(h.byId["take-review"].hidden, false);
});
test("unavailable recovery storage leaves recording usable", async () => {
  const h = harness({recovery: true, failRecovery: true}); await h.ready(); await h.byId.record.trigger(); await h.byId.stop.trigger(); await h.ready();
  assert.match(h.byId["recovery-status"].textContent, /could not be saved/);
  assert.equal(h.byId["keep-take"].disabled, false);
});

test("live recording checkpoints persist and become reviewable after interruption", async () => {
  const h = harness({recovery: true}); await h.ready(); await h.byId.record.trigger();
  h.options().onCheckpoint({samples: new Float32Array(220500), sampleRate: 44100, position: 12.5}); await h.ready();
  assert.equal(h.drafts.at(-1).take.samples.length, 220500);
  h.options().onError(new Error("Capture interrupted")); await h.ready();
  assert.equal(h.byId["take-review"].hidden, false);
  assert.equal(h.byId["keep-take"].disabled, false);
  assert.match(h.byId.status.textContent, /partial take/);
});

test("custom transport plays, pauses, and stops mixed audio", async () => {
  const h = harness(); h.byId["record-position"].value = "0";
  await h.byId.preview.trigger();
  assert.equal(h.byId["mix-preview"].paused, false);
  assert.equal(h.byId.stop.disabled, false);
  h.byId["mix-preview"].currentTime = .05;
  await h.byId.preview.trigger();
  assert.equal(h.byId["mix-preview"].paused, true);
  await h.byId.preview.trigger();
  assert.equal(h.byId["mix-preview"].currentTime, .05, "Play resumes from the paused position");
  await h.byId.stop.trigger();
  assert.equal(h.byId["mix-preview"].paused, true);
  assert.equal(h.byId["mix-preview"].currentTime, 0);
});

test("return to start updates transport position without discarding edits", async () => {
  const h = harness();
  const gain = h.elements.find(e => e.dataset.trackField === "gain"); gain.value = ".4"; await gain.trigger("input");
  await h.byId.rewind.trigger();
  assert.equal(h.byId["record-position"].value, "0");
  assert.equal(h.byId["session-clock"].textContent, "00:00.00");
  assert.equal(h.byId.publish.disabled, true);
  assert.equal(h.posted.length, 0);
});

test("Cancel take discards active recording, releases the mic, and preserves edits", async () => {
  const h = harness({recovery: true}); await h.ready();
  const gain = h.elements.find(e => e.dataset.trackField === "gain"); gain.value = ".35"; await gain.trigger("input");
  await h.byId.record.trigger();
  assert.equal(h.byId["cancel-recording"].hidden, false);
  assert.equal(h.byId["cancel-recording"].disabled, false);
  h.options().onCheckpoint({samples: new Float32Array(220500), sampleRate: 44100, position: 12.5});
  await h.byId["cancel-recording"].trigger(); await h.ready();
  assert.equal(h.cancelled(), 1); assert.ok(h.micStops() >= 1);
  assert.equal(h.byId["take-review"].hidden, true);
  assert.equal(h.byId.record.disabled, false);
  assert.equal(h.byId["cancel-recording"].hidden, true);
  assert.equal(h.posted.length, 0);
  assert.equal(h.drafts.at(-1).take, null);
  assert.equal(h.drafts.at(-1).tracks[0].gain, .35);
  h.options().onDone({samples: new Float32Array(4410), sampleRate: 44100, position: 12.5});
  assert.equal(h.byId["take-review"].hidden, true, "late callbacks cannot resurrect cancelled audio");
});
test("cancel while microphone permission is pending prevents recording when it resolves", async () => {
  let resolve;
  const microphone = new Promise(done => resolve = done), h = harness({microphone});
  const starting = h.byId.record.trigger(); await h.ready();
  assert.equal(h.byId["cancel-recording"].disabled, false);
  await h.byId["cancel-recording"].trigger(); resolve(h.stream); await starting;
  assert.equal(h.beginCalls(), 0); assert.ok(h.micStops() >= 1);
  assert.equal(h.byId.record.disabled, false); assert.equal(h.posted.length, 0);
});
test("cancel while backing tracks prepare also cancels a late audio session", async () => {
  let resolve; const preparation = new Promise(done => resolve = done), h = harness({preparation});
  const starting = h.byId.record.trigger(); await h.ready();
  await h.byId["cancel-recording"].trigger(); resolve(); await starting;
  assert.equal(h.cancelled(), 1); assert.equal(h.byId.record.disabled, false);
  assert.equal(h.byId["take-review"].hidden, true); assert.equal(h.posted.length, 0);
});


test("Acapella solo limits recording guides while save preserves every voice", async () => {
 const tracks=[1,2].map(id=>({id,name:id===1?"Lead voice":"Alto",url:"voice.wav",gain:1,offset:0,trim_start:0,trim_end:0,muted:false}));
 const h=harness({category:"acapella",tracks});
 assert.equal(h.byId["track-name"].value,"Lead voice 2");
 const solo=h.elements.find(e=>e.dataset.voiceSolo==="2"); await solo.trigger();
 await h.byId.record.trigger(); assert.deepEqual(Array.from(h.options().tracks,t=>t.id),[2]);
 await h.byId["cancel-recording"].trigger();
 const name=h.elements.find(e=>e.className==="studio-voice-name");name.value="Lead polished";await name.trigger("input");
 await h.byId.save.trigger(); const submitted=JSON.parse(h.posted[0].body.get("tracks"));
 assert.equal(submitted.length,2);assert.equal(submitted[0].name,"Lead polished");assert.equal(h.posted[0].body.get("revision"),"rev1");
});


test("keyboard audio chooses exact interface and channel and saves as backing",async()=>{
 const h=harness({inputMode:"keyboard"});await h.byId.record.trigger();assert.equal(h.constraints().audio.deviceId.exact,"interface-1");assert.equal(h.constraints().audio.channelCount.ideal,2);assert.equal(h.options().channelSelection,"right");await h.byId.stop.trigger();await h.byId["keep-take"].trigger();assert.equal(h.posted[0].body.get("kind"),"backing");
});
test("Acapella retains vocal-only capture even with keyboard source selected",async()=>{
 const h=harness({category:"acapella",inputMode:"keyboard"});await h.byId.record.trigger();assert.equal(h.constraints().audio.channelCount,1);await h.byId.stop.trigger();await h.byId["keep-take"].trigger();assert.equal(h.posted[0].body.get("kind"),"vocal");
});

test("Auto Master previews the mix and saves the mastered WAV only on request", async () => {
  const h = harness();
  await h.byId["auto-master"].trigger();
  assert.equal(h.posted.length, 1);
  assert.equal(h.posted[0].url, "/studio/project/7/master/");
  assert.equal(h.byId["master-preview"].hidden, false);
  await h.byId["save-master"].trigger();
  assert.equal(h.posted[1].url, "/studio/project/7/save/");
  assert.equal(await h.posted[1].body.get("audio").text(), "mastered");
  assert.equal(h.posted[1].body.get("revision"), "rev1");
});
