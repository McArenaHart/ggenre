const test = require("node:test");
const assert = require("node:assert/strict");
const {edit, peaks} = require("../static/js/studio-timeline.js");
const track = {trim_start: 2, trim_end: 8, offset: 10};
test("moving a clip preserves trims and stays within the project", () => {
  assert.deepEqual(edit(track, 12, "move", 5), {...track, offset: 15});
  assert.equal(edit(track, 12, "move", -100).offset, 0);
  assert.equal(edit(track, 12, "move", 500).offset, 354);
  assert.equal(track.offset, 10);
});
test("left trim keeps the clip's right edge in place", () => {
  const changed = edit(track, 12, "left", 1.5);
  assert.equal(changed.trim_start, 3.5); assert.equal(changed.offset, 11.5);
  assert.equal(changed.offset + changed.trim_end - changed.trim_start, 16);
  const extended = edit(track, 12, "left", -100);
  assert.equal(extended.trim_start, 0); assert.equal(extended.offset, 8);
});
test("trim handles cannot cross or expose samples beyond the source", () => {
  assert.equal(edit(track, 12, "left", 100).trim_start, 7.95);
  assert.equal(edit(track, 12, "right", -100).trim_end, 2.05);
  assert.equal(edit(track, 12, "right", 100).trim_end, 12);
  assert.equal(edit({...track, offset: 356}, 12, "right", 100).trim_end, 6);
  assert.throws(() => edit({...track, trim_start: NaN}, 12, "move", 1));
});
test("waveform peaks retain transients including very short recordings", () => {
  const samples = new Float32Array([0, -.9, .1, 0]);
  assert.deepEqual(peaks({getChannelData: () => samples}, 2).map(n => Math.round(n * 10)), [9, 1]);
  assert.equal(peaks({getChannelData: () => samples}).length, 4);
});

test("waveform includes audio present only in the right stereo channel", () => {
  const result = peaks({numberOfChannels: 2, getChannelData: index => new Float32Array(index ? [.8, -.7] : [0, 0])}, 2);
  assert.equal(Math.round(result[0] * 10), 8);
});
