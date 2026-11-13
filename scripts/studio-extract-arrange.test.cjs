const test = require('node:test');
const assert = require('node:assert/strict');
const {plan} = require('../static/js/studio-extract-arrange.js');
const config = fade => ({crossfade_ms: fade, sections: [{start: 0, end: .5, gain: 1}, {start: 1, end: 1.5, gain: .5}, {start: 2, end: 2.5, gain: .25}]});

test('three sections join without gaps and subtract only crossfade overlap', () => {
  const result = plan(config(20), 8000, 24000);
  assert.deepEqual(result.fades, [160, 160]);
  assert.equal(result.length, 11680);
  assert.equal(plan(config(0), 8000, 24000).length, 12000);
});
test('source ranges can repeat while staying in intro-middle-outro order', () => {
  const state = config(20); state.sections.reverse();
  assert.deepEqual(plan(state, 8000, 24000).parts.map(p => p.start), [16000, 8000, 0]);
});
test('crossfades cannot consume more than half of an adjacent short part', () => {
  const state = {crossfade_ms: 500, sections: [{start: 0, end: .1, gain: 1}, {start: .1, end: .2, gain: 1}, {start: .2, end: .3, gain: 1}]};
  assert.deepEqual(plan(state, 8000, 24000).fades, [400, 400]);
});
test('invalid ranges and oversized arrangements are rejected', () => {
  for (const [key, value] of [['start', -1], ['end', 9], ['gain', 2], ['start', NaN]]) {
    const state = config(20); state.sections[0][key] = value;
    assert.throws(() => plan(state, 8000, 24000));
  }
  assert.throws(() => plan({crossfade_ms: 0, sections: [{start: 0, end: 360, gain: 1}].flatMap(p => [p,p,p])}, 8000, 2880000));
});
