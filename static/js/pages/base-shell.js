(function () {
  "use strict";
  const THEME_STORAGE_KEY = "ggenre-theme";
  const THEME_DARK = "dark";
  const THEME_LIGHT = "light";

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      document.cookie.split(";").forEach(function (cookie) {
        const trimmed = cookie.trim();
        if (trimmed.startsWith(name + "=")) {
          cookieValue = decodeURIComponent(trimmed.substring(name.length + 1));
        }
      });
    }
    return cookieValue;
  }

  function readStoredTheme() {
    try {
      const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (storedTheme === THEME_DARK || storedTheme === THEME_LIGHT) {
        return storedTheme;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  function writeStoredTheme(theme) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (error) {
      // Ignore localStorage errors and continue with in-memory theme state.
    }
  }

  function resolveTheme() {
    const storedTheme = readStoredTheme();
    if (storedTheme) {
      return storedTheme;
    }

    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      return THEME_LIGHT;
    }

    return THEME_DARK;
  }

  function syncThemeToggleUI(theme) {
    const isLightMode = theme === THEME_LIGHT;
    const isDarkMode = theme === THEME_DARK;
    const nextThemeLabel = isLightMode ? "Dark" : "Light";
    const nextThemeLabelLower = nextThemeLabel.toLowerCase();
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      const icon = button.querySelector("i");
      const label = button.querySelector("[data-theme-label]");

      button.setAttribute("aria-pressed", isDarkMode ? "true" : "false");
      button.setAttribute("aria-label", "Switch to " + nextThemeLabelLower + " mode");
      button.setAttribute("title", "Switch to " + nextThemeLabelLower + " mode");

      if (icon) {
        icon.classList.toggle("fa-sun", !isLightMode);
        icon.classList.toggle("fa-moon", isLightMode);
      }

      if (label) {
        label.textContent = nextThemeLabel;
      }
    });
  }

  function applyTheme(theme) {
    const body = document.body;
    if (!body) {
      return;
    }

    const normalizedTheme = theme === THEME_LIGHT ? THEME_LIGHT : THEME_DARK;
    body.dataset.theme = normalizedTheme;
    body.classList.toggle("theme-light", normalizedTheme === THEME_LIGHT);
    body.classList.toggle("theme-dark", normalizedTheme === THEME_DARK);
    syncThemeToggleUI(normalizedTheme);
  }

  function initThemeToggle() {
    const body = document.body;
    if (!body) {
      return;
    }

    const toggleButtons = document.querySelectorAll("[data-theme-toggle]");
    if (!toggleButtons.length) {
      return;
    }

    toggleButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        const currentTheme = body.dataset.theme === THEME_LIGHT ? THEME_LIGHT : THEME_DARK;
        const nextTheme = currentTheme === THEME_LIGHT ? THEME_DARK : THEME_LIGHT;
        applyTheme(nextTheme);
        writeStoredTheme(nextTheme);
      });
    });
  }

  function initNavbarOutsideClick() {
    const navbarToggler = document.querySelector(".navbar-toggler");
    const navbarCollapse = document.querySelector(".navbar-collapse");

    if (!navbarToggler || !navbarCollapse) {
      return;
    }

    document.addEventListener("click", function (event) {
      const clickInside =
        navbarCollapse.contains(event.target) || navbarToggler.contains(event.target);

      if (clickInside || !navbarCollapse.classList.contains("show")) {
        return;
      }

      if (window.$) {
        window.$(".navbar-collapse").collapse("hide");
      } else {
        navbarCollapse.classList.remove("show");
      }
    });
  }

  function renderAnnouncementPopup(announcements, dismissUrlTemplate) {
    if (!Array.isArray(announcements) || !announcements.length) {
      return;
    }

    const existingPopup = document.querySelector(".announcement-popup");
    if (existingPopup) {
      existingPopup.remove();
    }

    const popup = document.createElement("div");
    popup.className = "announcement-popup";

    announcements.forEach(function (announcement) {
      if (!announcement || !announcement.id) {
        return;
      }

      const content = document.createElement("div");
      content.className = "announcement-content";

      const title = document.createElement("h4");
      title.textContent = announcement.title || "Announcement";

      const message = document.createElement("p");
      message.textContent = announcement.message || "";

      const dismissButton = document.createElement("button");
      dismissButton.type = "button";
      dismissButton.textContent = "Dismiss";
      dismissButton.addEventListener("click", function () {
        const dismissUrl = dismissUrlTemplate.replace("0", encodeURIComponent(announcement.id));
        fetch(dismissUrl, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Content-Type": "application/json",
          },
          credentials: "include",
        })
          .then(function (response) {
            if (!response.ok) {
              return;
            }
            popup.remove();
          })
          .catch(function (error) {
            console.error("Dismiss announcement failed:", error);
          });
      });

      content.appendChild(title);
      content.appendChild(message);
      content.appendChild(dismissButton);
      popup.appendChild(content);
    });

    if (popup.children.length) {
      document.body.appendChild(popup);
    }
  }

  function initAnnouncements() {
    const body = document.body;
    if (!body || body.dataset.authenticated !== "1") {
      return;
    }

    const announcementsUrl = body.dataset.announcementsUrl;
    const dismissUrlTemplate = body.dataset.dismissAnnouncementTemplate;

    if (!announcementsUrl || !dismissUrlTemplate) {
      return;
    }

    fetch(announcementsUrl, { credentials: "include" })
      .then(function (response) {
        if (!response.ok) {
          return null;
        }
        return response.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.announcements)) {
          return;
        }
        renderAnnouncementPopup(data.announcements, dismissUrlTemplate);
      })
      .catch(function (error) {
        console.error("Announcement loading failed:", error);
    });
  }

  applyTheme(resolveTheme());

  document.addEventListener("DOMContentLoaded", function () {
    initThemeToggle();
    initNavbarOutsideClick();
    initAnnouncements();
  });
})();
