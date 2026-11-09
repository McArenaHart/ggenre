const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const audio = require("../static/js/studio-audio.js");
const base = {name: "Vocal", trim_start: 1, trim_end: 9, offset: 4, gain: 0.5, muted: false};

test("backing starts on shared timeline and seeks inside a trimmed track", () => {
  assert.deepEqual(audio.segment(base, 10, 0), {delay: 4, start: 1, duration: 8, gain: 0.5});
  assert.deepEqual(audio.segment(base, 10, 7), {delay: 0, start: 4, duration: 5, gain: 0.5});
  assert.equal(audio.segment(base, 10, 12), null);
  assert.equal(audio.segment({...base, muted: true}, 10, 0), null);
});
test("timeline limits and malformed trims are handled", () => {
  assert.equal(audio.segment({...base, offset: 358}, 10, 0).duration, 2);
  assert.throws(() => audio.segment({...base, trim_start: 10}, 10, 0));
  assert.throws(() => audio.segment({...base, gain: NaN}, 10, 0));
});

test("full songs can play through six minutes while later starts are rejected", () => {
  const song = {...base, trim_start: 0, trim_end: 0, offset: 0};
  assert.equal(audio.segment(song, 333, 0).duration, 333);
  assert.equal(audio.segment(song, 360, 0).duration, 360);
  assert.throws(() => audio.segment(song, 361, 360));
});
test("positive and negative delay corrections move a known vocal impulse", () => {
  const samples = new Float32Array([0, 0, 1, 0, 0]);
  assert.deepEqual([...audio.compensate(samples, 1000, 2)], [1, 0, 0]);
  assert.deepEqual([...audio.compensate(samples, 1000, -2)], [0, 0, 0, 0, 1, 0, 0]);
  assert.deepEqual([...samples], [0, 0, 1, 0, 0]);
  assert.throws(() => audio.compensate(samples, 1000, 5));
});
function capture(sampleRate = 48000, channelSelection = "mix") {
  const messages = [];
  const sandbox = {sampleRate, currentFrame: 0, Float32Array, Infinity, Math,
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: data => messages.push(data)}; } },
    registerProcessor: (name, klass) => sandbox.Processor = klass};
  vm.createContext(sandbox); vm.runInContext(fs.readFileSync(require.resolve("../static/js/studio-capture-worklet.js"), "utf8"), sandbox);
  const processor = new sandbox.Processor({processorOptions:{channelSelection}});
  return {processor, sandbox, messages,
    send(data) { processor.port.onmessage({data}); },
    block(frame, values) {
      sandbox.currentFrame = frame;
      const output = new Float32Array(values.length).fill(1);
      processor.process([[new Float32Array(values)]], [[output]]);
      assert.ok(output.every(value => value === 0), "mic monitoring must remain silent");
    },
    samples() { return messages.filter(data => data.type === "chunk").flatMap(data => [...data.samples]); }};
}
test("worklet captures exact frame boundaries and excludes count-in", () => {
  const recorder = capture(); recorder.send({type: "arm", start: 3, end: 10});
  recorder.block(0, [0, 1, 2, 3, 4, 5]); recorder.block(6, [6, 7, 8, 9, 10, 11]);
  assert.deepEqual(recorder.samples(), [3, 4, 5, 6, 7, 8, 9]);
  assert.equal(recorder.messages.at(-1).frames, 7);
});
test("stopping during count-in yields no audio", () => {
  const recorder = capture(); recorder.send({type: "arm", start: 100, end: 1000});
  recorder.block(0, [0, 1, 2]); recorder.send({type: "stop", frame: 3});
  assert.deepEqual(recorder.samples(), []); assert.equal(recorder.messages.at(-1).frames, 0);
});
test("late stop messages report the requested length even after a render block", () => {
  const recorder = capture(); recorder.send({type: "arm", start: 2, end: 1000});
  recorder.block(0, [0, 1, 2, 3, 4, 5, 6, 7]); recorder.sandbox.currentFrame = 8;
  recorder.send({type: "stop", frame: 5}); assert.equal(recorder.messages.at(-1).frames, 3);
});
test("chunk boundaries do not lose samples at different device sample rates", () => {
  for (const rate of [44100, 48000, 96000]) {
    const recorder = capture(rate); recorder.send({type: "arm", start: 17, end: 10001});
    for (let frame = 0; frame < 10112; frame += 128) recorder.block(frame, Array.from({length: 128}, (_, i) => (frame + i) / 20000));
    assert.equal(recorder.samples().length, 9984);
    assert.equal(recorder.messages.at(-1).frames, 9984);
    assert.ok(Math.abs(recorder.samples()[0] - 17 / 20000) < 1e-7);
    assert.ok(Math.abs(recorder.samples().at(-1) - 10000 / 20000) < 1e-7);
  }
});
test("reported latency is estimated without requiring optional browser properties", () => {
  assert.equal(audio.estimatedDelay({}, {getAudioTracks: () => [{}]}), 0);
  assert.equal(audio.estimatedDelay({baseLatency: 0.01, outputLatency: 0.02}, {getAudioTracks: () => [{getSettings: () => ({latency: 0.03})}]}), 60);
});

test("active capture checkpoints are complete independent copies and final stops are trimmed", async () => {
  let node, checkpoint, completed;
  const previous = global.AudioWorkletNode;
  global.AudioWorkletNode = class {
    constructor() { node = this; this.port = {postMessage() {}}; }
    connect() { return this; } disconnect() {}
  };
  const graph = () => ({gain: {value: 1}, connect() { return this; }, disconnect() {}});
  const context = {currentTime: 0, sampleRate: 1000, destination: {}, audioWorklet: {async addModule() {}}, createMediaStreamSource: graph, createGain: graph, addEventListener() {}, removeEventListener() {}};
  const track = {stop() {}, addEventListener() {}, getSettings: () => ({})};
  let session;
  try {
    session = await audio.begin({context, stream: {getTracks: () => [track], getAudioTracks: () => [track]}, tracks: [], load() {}, position: 0, bpm: 80, countIn: 0, workletURL: "test", onMeter() {}, onProgress() {}, onError: error => { throw error; }, onCheckpoint: value => checkpoint = value, onDone: value => completed = value});
    const chunk = new Float32Array(5000).fill(.25);
    node.port.onmessage({data: {type: "chunk", samples: chunk}});
    assert.equal(checkpoint.samples.length, 5000);
    chunk[0] = .5;
    assert.equal(checkpoint.samples[0], .25);
    node.port.onmessage({data: {type: "chunk", samples: new Float32Array(1000)}});
    node.port.onmessage({data: {type: "done", frames: 5500}});
    assert.equal(completed.samples.length, 5500);
  } finally { session?.cancel(); global.AudioWorkletNode = previous; }
});


test("external stereo input mixes or selects channels without monitoring feedback",()=>{
 for(const [selection,expected] of [["mix",[.5,0]],["left",[1,.5]],["right",[0,-.5]]]){
 const recorder=capture(48000,selection);recorder.send({type:"arm",start:0,end:2});const output=new Float32Array(2).fill(1);
 recorder.processor.process([[Float32Array.from([1,.5]),Float32Array.from([0,-.5])]],[[output]]);
 assert.deepEqual(recorder.samples(),expected);assert.deepEqual([...output],[0,0]);
 }
 const mono=capture(48000,"right");mono.send({type:"arm",start:0,end:2});mono.block(0,[.2,.3]);assert.ok(Math.abs(mono.samples()[0]-.2)<1e-6);
});
