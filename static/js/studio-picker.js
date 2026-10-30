/* Theme-matched, keyboard-accessible select menus; native values still submit forms. */
(() => {
  "use strict";
  let opened;
  function enhance(select) {
    if (select.dataset.studioPicker) return;
    select.dataset.studioPicker = "true";
    const label = select.labels?.[0]?.firstChild?.textContent?.trim() || "Choose an option";
    const wrapper = document.createElement("div"); wrapper.className = "studio-picker";
    const trigger = document.createElement("button"); trigger.type = "button"; trigger.className = "studio-picker-trigger";
    trigger.setAttribute("role", "combobox"); trigger.setAttribute("aria-haspopup", "listbox"); trigger.setAttribute("aria-expanded", "false");
    const value = document.createElement("span"), arrow = document.createElement("i"); value.className = "studio-picker-value"; arrow.className = "fas fa-chevron-down"; arrow.setAttribute("aria-hidden", "true"); trigger.append(value, arrow);
    const menu = document.createElement("div"); menu.id = "studio-options-" + (select.id || Math.random().toString(36).slice(2)); menu.className = "studio-picker-menu"; menu.setAttribute("role", "listbox"); menu.setAttribute("aria-label", label); menu.hidden = true; trigger.setAttribute("aria-controls", menu.id);
    select.parentNode.insertBefore(wrapper, select); wrapper.append(select, trigger); document.body.append(menu);
    select.classList.add("studio-native-select"); select.tabIndex = -1; select.setAttribute("aria-hidden", "true");
    let index = select.selectedIndex, options = [];
    function close() { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); trigger.removeAttribute("aria-activedescendant"); if (opened === close) opened = null; }
    function highlight(next) {
      index = Math.max(0, Math.min(options.length - 1, next));
      options.forEach((option, i) => option.classList.toggle("is-active", i === index));
      if (options[index]) { trigger.setAttribute("aria-activedescendant", options[index].id); options[index].scrollIntoView({block: "nearest"}); }
    }
    function choose(next) {
      if (select.disabled || select.options[next]?.disabled) return;
      select.selectedIndex = next; select.dispatchEvent(new Event("change", {bubbles: true})); close(); trigger.focus();
    }
    function sync() {
      const selected = select.options[select.selectedIndex]; value.textContent = selected?.textContent || "Choose…";
      trigger.disabled = select.disabled; trigger.setAttribute("aria-label", label + ": " + value.textContent);
      options.forEach((node, i) => { node.setAttribute("aria-selected", String(i === select.selectedIndex)); });
      if (select.disabled) close();
    }
    function open() {
      if (select.disabled) return; opened?.();
      menu.replaceChildren(); options = Array.from(select.options).map((option, i) => {
        const row = document.createElement("div"); row.id = menu.id + "-" + i; row.className = "studio-picker-option"; row.setAttribute("role", "option"); row.setAttribute("aria-selected", String(i === select.selectedIndex));
        const name = document.createElement("strong"); name.textContent = option.textContent; row.append(name);
        if (option.dataset.description) { const hint = document.createElement("small"); hint.textContent = option.dataset.description; row.append(hint); }
        row.addEventListener("mousedown", event => event.preventDefault()); row.addEventListener("click", () => choose(i)); menu.append(row); return row;
      });
      const rect = trigger.getBoundingClientRect(), below = innerHeight - rect.bottom - 10;
      menu.style.width = Math.min(Math.max(rect.width, 160), innerWidth - 20) + "px";
      menu.style.left = Math.max(10, Math.min(rect.left, innerWidth - parseFloat(menu.style.width) - 10)) + "px";
      menu.style.maxHeight = Math.max(90, Math.min(280, below >= 150 ? below : rect.top - 10)) + "px";
      menu.style.top = below >= 150 ? rect.bottom + 6 + "px" : "auto";
      menu.style.bottom = below >= 150 ? "auto" : innerHeight - rect.top + 6 + "px";
      menu.hidden = false; trigger.setAttribute("aria-expanded", "true"); opened = close; highlight(select.selectedIndex);
    }
    trigger.addEventListener("click", () => menu.hidden ? open() : close());
    trigger.addEventListener("keydown", event => {
      if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Escape"].includes(event.key)) event.preventDefault();
      if (event.key === "Escape") return close();
      if (event.key === "Tab") return close();
      if (["Enter", " "].includes(event.key)) return menu.hidden ? open() : choose(index);
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        if (menu.hidden) open();
        else highlight(event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : index + (event.key === "ArrowDown" ? 1 : -1));
      }
    });
    document.addEventListener("pointerdown", event => { if (!wrapper.contains(event.target) && !menu.contains(event.target)) close(); });
    window.addEventListener("resize", close); window.addEventListener("scroll", event => { if (!menu.contains(event.target)) close(); }, true);
    select.addEventListener("focus", () => trigger.focus()); select.addEventListener("change", sync); new MutationObserver(sync).observe(select, {attributes: true, attributeFilter: ["disabled"]}); sync();
  }
  document.querySelectorAll(".studio-app select").forEach(enhance);
  const category = document.getElementById("category"), hint = document.getElementById("project-type-hint");
  if (category && hint) { const update = () => hint.textContent = category.selectedOptions[0]?.dataset.description || ""; category.addEventListener("change", update); update(); }
})();
