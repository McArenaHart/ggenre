(function () {
  "use strict";

  let refreshTimer = null;
  let isRefreshing = false;

  function replaceFromDocument(currentDoc, nextDoc, selector) {
    const current = currentDoc.querySelector(selector);
    const next = nextDoc.querySelector(selector);
    if (current && next) {
      current.replaceWith(next);
    }
  }

  function refreshInbox() {
    if (isRefreshing) {
      return;
    }
    isRefreshing = true;
    fetch(window.location.href, { credentials: "include" })
      .then(function (response) {
        if (!response.ok) {
          return null;
        }
        return response.text();
      })
      .then(function (html) {
        if (!html) {
          return;
        }
        const parser = new DOMParser();
        const nextDoc = parser.parseFromString(html, "text/html");
        replaceFromDocument(document, nextDoc, ".chat-inbox-sidebar");
        replaceFromDocument(document, nextDoc, ".chat-inbox-preview");
      })
      .catch(function () {
        // The websocket event is best-effort; normal navigation still works.
      })
      .finally(function () {
        isRefreshing = false;
      });
  }

  window.addEventListener("ggenre:admin-counts", function () {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(refreshInbox, 250);
  });
})();
