const test = require('node:test');
const assert = require('node:assert/strict');
const {History} = require('../static/js/studio-history.js');
test('undo and redo preserve clip settings and branch after a new edit', () => {
  const h = new History([{gain: 1, offset: 0, muted: false}]);
  h.record([{gain: .5, offset: 2, muted: true}]);
  assert.deepEqual(h.undo(), [{gain: 1, offset: 0, muted: false}]);
  assert.deepEqual(h.redo(), [{gain: .5, offset: 2, muted: true}]);
  h.undo(); h.record([{gain: .8, offset: 1, muted: false}]);
  assert.equal(h.redo(), null);
  assert.equal(h.undo()[0].gain, 1);
});
test('history bounds memory and ignores unchanged snapshots', () => {
  const h = new History({offset: 0}, 3);
  for (let i = 1; i < 10; i++) h.record({offset: i});
  h.record({offset: 9}); assert.equal(h.states.length, 3);
  assert.equal(h.undo().offset, 8); assert.equal(h.undo().offset, 7);
  assert.equal(h.undo(), null);
});
