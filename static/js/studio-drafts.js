/* Browser-local recovery. Each entry belongs to one signed-in artist and project. */
(function (scope) {
  "use strict";
  class Drafts {
    constructor(key, indexedDB = scope.indexedDB) { this.key = key; this.indexedDB = indexedDB; this.queue = Promise.resolve(); }
    async database() {
      if (!this.indexedDB) throw new Error("Local recovery is unavailable in this browser.");
      if (!this.connection) this.connection = new Promise((resolve, reject) => {
        const request = this.indexedDB.open("ggenre-studio-recovery", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("drafts");
        request.onsuccess = () => { const db = request.result; db.onversionchange = () => db.close(); resolve(db); };
        request.onerror = () => reject(request.error);
        request.onblocked = () => reject(new Error("Close other Studio tabs to enable local recovery."));
      });
      return this.connection;
    }
    operation(mode, action) {
      const run = this.queue.catch(() => {}).then(async () => {
        const db = await this.database();
        return new Promise((resolve, reject) => {
          const transaction = db.transaction("drafts", mode), request = action(transaction.objectStore("drafts"));
          let result;
          request.onsuccess = () => { result = request.result; };
          transaction.oncomplete = () => resolve(result);
          transaction.onerror = () => reject(transaction.error || request.error || new Error("Local recovery could not be saved."));
          transaction.onabort = () => reject(transaction.error || new Error("Local recovery was interrupted."));
        });
      });
      this.queue = run; return run;
    }
    read() { return this.operation("readonly", store => store.get(this.key)); }
    write(value) { return this.operation("readwrite", store => store.put({...value, savedAt: Date.now()}, this.key)); }
    clear() { return this.operation("readwrite", store => store.delete(this.key)); }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = Drafts;
  else scope.StudioDrafts = Drafts;
})(typeof window !== "undefined" ? window : globalThis);
