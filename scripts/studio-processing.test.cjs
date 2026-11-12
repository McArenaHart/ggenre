const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function harness(track, acapella = false) {
  const elements = [], requests = [], tasks = [], timers = [];
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.style = {}; this.hidden = false; this.value = ''; elements.push(this); }
    append(...children) { for (const child of children) { this.children.push(child); if (typeof child === 'object') child.parentElement = this; if (this.tag === 'select' && !this.value) this.value = child.value; } }
    setAttribute() {}
    removeAttribute(name) { delete this[name]; }
    addEventListener(event, fn) { this.events[event] = fn; }
    querySelector() { return this; }
    querySelectorAll() { return []; }
  }
  const scope = {window: {addEventListener() {}}, document: {createElement: tag => new Element(tag)},
    FormData, clearTimeout() {}, setTimeout: fn => { timers.push(fn); return timers.length; },
    fetch: async () => ({ok: true, json: async () => ({status: 'ready', url: '/private-result/'})}),
    location: {reload() { scope.reloads++; }}, reloads: 0};
  vm.createContext(scope);
  vm.runInContext(fs.readFileSync('static/js/studio-processing.js', 'utf8'), scope);
  let dirty = false;
  scope.window.StudioProcessing.mount(new Element('section'), track, {
    isAcapella: acapella, task: fn => tasks.push(fn()), post: async (url, data) => { requests.push({url, data}); return {id: 6 + requests.length}; },
    canApply: () => !dirty, revision: () => 'revision',
  });
  return {elements, requests, tasks, timers, scope, dirty(value) { dirty = value; }};
}

test('processing previews a copy, blocks unsaved edits and sends revision on apply', async () => {
  const h = harness({id: 1, kind: 'vocal'});
  const buttons = h.elements.filter(e => e.tag === 'button');
  buttons[0].events.click(); await h.tasks.pop();
  assert.equal(h.requests[0].url, '/studio/track/1/process/');
  await h.timers.pop()();
  const player = h.elements.find(e => e.tag === 'audio');
  assert.equal(player.src, '/private-result/'); assert.equal(player.hidden, false);
  h.dirty(true); buttons[1].events.click();
  await assert.rejects(h.tasks.pop(), /Save your mix/);
  h.dirty(false); buttons[1].events.click(); await h.tasks.pop();
  assert.equal(h.requests[1].data.get('revision'), 'revision');
  assert.equal(h.scope.reloads, 1);
});

test('instrumental extraction requires permission and Acapella only offers voice tools', async () => {
  const h = harness({id: 2, kind: 'backing'});
  const operation = h.elements.find(e => e.tag === 'select');
  operation.value = 'separate'; operation.events.change();
  h.elements.find(e => e.tag === 'button').events.click();
  await assert.rejects(h.tasks.pop(), /permission/);
  assert.ok(h.elements.some(e => e.textContent === 'Confirm you have permission to reuse this recording.'));
  assert.equal(h.requests.length, 0);
  const a = harness({id: 3, kind: 'vocal'}, true);
  assert.deepEqual(a.elements.find(e => e.tag === 'select').children.map(e => e.value), ['denoise', 'tune']);
});

test('a delayed preview from an older task cannot replace the currently queued result', async () => {
  const h = harness({id: 1, kind: 'vocal'});
  const run = h.elements.find(e => e.tag === 'button');
  run.events.click(); await h.tasks.pop();
  let finish;
  h.scope.fetch = () => new Promise(resolve => { finish = resolve; });
  const oldPoll = h.timers.shift()();
  run.events.click(); await h.tasks.pop();
  finish({ok: true, json: async () => ({status: 'ready', url: '/older-result/'})});
  await oldPoll;
  assert.equal(h.elements.find(e => e.tag === 'audio').hidden, true);
});

test('an unfinished task reports errors and allows a new processing attempt', async () => {
  const h = harness({id: 1, kind: 'vocal'});
  const run = h.elements.find(e => e.tag === 'button');
  run.events.click(); await h.tasks.pop();
  h.scope.fetch = async () => ({ok: true, json: async () => ({status: 'failed', error: 'Engine unavailable'})});
  await h.timers.shift()();
  assert.ok(h.elements.some(e => e.textContent === 'Engine unavailable'));
  assert.equal(h.elements.find(e => e.tag === 'audio').hidden, true);
  run.events.click(); await h.tasks.pop();
  assert.equal(h.requests.length, 2);
});

test('expired previews stop polling and allow processing the original again', async () => {
  const h = harness({id: 1, kind: 'vocal'});
  const run = h.elements.find(e => e.tag === 'button');
  run.events.click(); await h.tasks.pop();
  h.scope.fetch = async () => ({ok: true, json: async () => ({status: 'expired', error: 'This temporary result expired. Process the original track again.'})});
  await h.timers.shift()();
  assert.ok(h.elements.some(e => /temporary result expired/.test(e.textContent)));
  assert.equal(h.elements.find(e => e.tag === 'audio').hidden, true);
  assert.equal(h.timers.length, 0);
  run.events.click(); await h.tasks.pop();
  assert.equal(h.requests.length, 2);
});

test('extraction shows an empty bar while queued, animates while running, and fills when ready', async () => {
  const h = harness({id: 2, kind: 'backing'});
  const operation = h.elements.find(e => e.tag === 'select');
  const consent = h.elements.find(e => e.type === 'checkbox');
  const progress = h.elements.find(e => e.tag === 'progress');
  operation.value = 'separate';
  consent.checked = true;
  h.elements.find(e => e.tag === 'button').events.click();
  await h.tasks.pop();
  assert.equal(progress.hidden, false);
  assert.equal(progress.value, 0);
  h.scope.fetch = async () => ({ok: true, json: async () => ({status: 'running'})});
  await h.timers.shift()();
  assert.equal(progress.hidden, false);
  assert.equal(progress.value, undefined);
  h.scope.fetch = async () => ({ok: true, json: async () => ({status: 'ready', url: '/private-result/'})});
  await h.timers.shift()();
  assert.equal(progress.value, 100);
});
