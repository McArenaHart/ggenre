(function(scope) {
  'use strict';
  class History {
    constructor(initial, limit = 60) { this.limit = limit; this.states = [JSON.stringify(initial)]; this.index = 0; }
    record(value) {
      const state = JSON.stringify(value);
      if (state === this.states[this.index]) return;
      this.states.splice(this.index + 1); this.states.push(state);
      if (this.states.length > this.limit) this.states.shift();
      this.index = this.states.length - 1;
    }
    undo() { if (this.index > 0) return JSON.parse(this.states[--this.index]); return null; }
    redo() { if (this.index + 1 < this.states.length) return JSON.parse(this.states[++this.index]); return null; }
  }
  if (typeof module !== 'undefined') module.exports = {History};
  else scope.StudioHistory = {History};
})(typeof window !== 'undefined' ? window : globalThis);
