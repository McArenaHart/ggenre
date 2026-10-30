(function (scope) {
  "use strict";
  function needsLandscape(width, height) { return width <= 900 && height > width; }
  function mount({root, gate, stop, cancel}) {
    if (!gate) return null;
    const media = scope.matchMedia ? scope.matchMedia("(max-width: 900px) and (orientation: portrait)") : null;
    const actions = gate.querySelector("[data-orientation-actions]");
    const stopButton = gate.querySelector("[data-orientation-stop]");
    const cancelButton = gate.querySelector("[data-orientation-cancel]");
    const description = gate.querySelector("[data-orientation-description]");
    let blocked = false, active = false;
    function update() {
      const previous = blocked;
      blocked = media ? media.matches : needsLandscape(scope.innerWidth, scope.innerHeight);
      gate.hidden = !blocked; root.inert = blocked;
      gate.setAttribute("aria-hidden", String(!blocked));
      if (blocked && !previous) gate.focus({preventScroll: true});
    }
    stopButton.addEventListener("click", stop); cancelButton.addEventListener("click", cancel);
    if (media?.addEventListener) media.addEventListener("change", update);
    else if (media?.addListener) media.addListener(update);
    scope.addEventListener("resize", update); update();
    return {
      blocked: () => blocked,
      updateCapture({active: running, canStop}) {
        active = running; actions.hidden = !active; stopButton.disabled = !canStop; cancelButton.disabled = !active;
        description.textContent = active ? "A take is in progress. Rotate back to landscape, or stop or cancel it below." : "The Studio needs a wider canvas. Turn your phone sideways to record and arrange your music.";
      },
    };
  }
  const api = {needsLandscape, mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else scope.StudioOrientation = api;
})(typeof window !== "undefined" ? window : globalThis);
