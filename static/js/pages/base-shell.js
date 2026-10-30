(function () {
  "use strict";

  const THEME_STORAGE_KEY = "ggenre-theme";
  const THEME_DARK = "dark";
  const THEME_LIGHT = "light";
  const THEME_COLOR_DARK = "#05060d";
  const THEME_COLOR_LIGHT = "#f4f8ff";

  const PWA_INSTALL_DISMISSED_KEY = "ggenre-pwa-install-dismissed-at";
  const PWA_INSTALL_DISMISS_WINDOW_MS = 1000 * 60 * 60 * 24 * 5;

  let deferredInstallPrompt = null;
  let activeServiceWorkerRegistration = null;

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

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // Ignore storage write errors.
    }
  }

  function removeStorage(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      // Ignore storage delete errors.
    }
  }

  function readStoredTheme() {
    const storedTheme = readStorage(THEME_STORAGE_KEY);
    if (storedTheme === THEME_DARK || storedTheme === THEME_LIGHT) {
      return storedTheme;
    }
    return null;
  }

  function writeStoredTheme(theme) {
    writeStorage(THEME_STORAGE_KEY, theme);
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

  function syncThemeColorMeta(theme) {
    const themeColorMeta = document.querySelector('meta[name="theme-color"]');
    if (!themeColorMeta) {
      return;
    }
    themeColorMeta.setAttribute("content", theme === THEME_LIGHT ? THEME_COLOR_LIGHT : THEME_COLOR_DARK);
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
    syncThemeColorMeta(normalizedTheme);
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

  function isStandaloneMode() {
    return (
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  }

  function isIOSInstallableDevice() {
    const ua = window.navigator.userAgent || "";
    const isIOS = /iphone|ipad|ipod/i.test(ua);
    const isWebKit = /webkit/i.test(ua);
    return isIOS && isWebKit;
  }

  function shouldSuppressInstallUI() {
    const dismissedAtRaw = readStorage(PWA_INSTALL_DISMISSED_KEY);
    if (!dismissedAtRaw) {
      return false;
    }

    const dismissedAt = Number(dismissedAtRaw);
    if (!Number.isFinite(dismissedAt)) {
      return false;
    }

    return Date.now() - dismissedAt < PWA_INSTALL_DISMISS_WINDOW_MS;
  }

  function dismissInstallUI() {
    writeStorage(PWA_INSTALL_DISMISSED_KEY, String(Date.now()));
    refreshInstallUI();
  }

  function clearInstallDismissal() {
    removeStorage(PWA_INSTALL_DISMISSED_KEY);
  }

  function refreshInstallUI() {
    const installButtons = document.querySelectorAll("[data-pwa-install]");
    const installSheet = document.querySelector("[data-pwa-install-sheet]");
    const installAction = document.querySelector("[data-pwa-install-action]");
    const installDismiss = document.querySelector("[data-pwa-install-dismiss]");
    const installTitle = document.querySelector("[data-pwa-install-title]");
    const installText = document.querySelector("[data-pwa-install-text]");
    const standalone = isStandaloneMode();
    const canInstall = Boolean(deferredInstallPrompt) && !standalone;
    const iosInstallHint = isIOSInstallableDevice() && !standalone && !canInstall;
    const showInstall = (canInstall || iosInstallHint) && !shouldSuppressInstallUI();

    installButtons.forEach(function (button) {
      button.hidden = !canInstall || !showInstall;
      button.classList.toggle("is-visible", canInstall && showInstall);
    });

    if (installSheet) {
      installSheet.hidden = !showInstall;
      document.body.classList.toggle("has-install-sheet", showInstall);
    }

    if (installAction) {
      installAction.hidden = iosInstallHint;
      installAction.disabled = !canInstall;
    }

    if (installTitle && installText && installDismiss) {
      if (iosInstallHint) {
        installTitle.textContent = "Install On iPhone";
        installText.textContent = "In Safari, tap Share and choose Add to Home Screen.";
        installDismiss.textContent = "Got it";
      } else {
        installTitle.textContent = "Install Genre Genius";
        installText.textContent = "Open faster, work offline, and use it like a native mobile app.";
        installDismiss.textContent = "Not now";
      }
    }
  }

  function triggerInstallPrompt() {
    if (!deferredInstallPrompt) {
      return;
    }

    const promptEvent = deferredInstallPrompt;
    deferredInstallPrompt = null;

    promptEvent
      .prompt()
      .then(function () {
        return promptEvent.userChoice;
      })
      .then(function (result) {
        if (!result || result.outcome !== "accepted") {
          dismissInstallUI();
          return;
        }
        clearInstallDismissal();
        refreshInstallUI();
      })
      .catch(function () {
        dismissInstallUI();
      });
  }

  function initInstallFlow() {
    const installButtons = document.querySelectorAll("[data-pwa-install]");
    const installAction = document.querySelector("[data-pwa-install-action]");
    const installDismiss = document.querySelector("[data-pwa-install-dismiss]");

    installButtons.forEach(function (button) {
      button.addEventListener("click", triggerInstallPrompt);
    });

    if (installAction) {
      installAction.addEventListener("click", triggerInstallPrompt);
    }

    if (installDismiss) {
      installDismiss.addEventListener("click", dismissInstallUI);
    }

    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      deferredInstallPrompt = event;
      clearInstallDismissal();
      refreshInstallUI();
    });

    window.addEventListener("appinstalled", function () {
      deferredInstallPrompt = null;
      clearInstallDismissal();
      refreshInstallUI();
    });

    refreshInstallUI();
  }

  function getUpdateToastNodes() {
    return {
      toast: document.querySelector("[data-pwa-update-toast]"),
      applyButton: document.querySelector("[data-pwa-update-apply]"),
      dismissButton: document.querySelector("[data-pwa-update-dismiss]"),
    };
  }

  function showUpdateToast(registration) {
    const { toast, applyButton, dismissButton } = getUpdateToastNodes();
    if (!toast) {
      return;
    }

    toast.hidden = false;
    document.body.classList.add("has-update-toast");

    if (applyButton) {
      applyButton.onclick = function () {
        const waitingWorker = registration.waiting || (activeServiceWorkerRegistration && activeServiceWorkerRegistration.waiting);
        if (waitingWorker) {
          waitingWorker.postMessage({ type: "SKIP_WAITING" });
        }
      };
    }

    if (dismissButton) {
      dismissButton.onclick = function () {
        toast.hidden = true;
        document.body.classList.remove("has-update-toast");
      };
    }
  }

  function initServiceWorker() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) {
      return;
    }

    const body = document.body;
    const serviceWorkerUrl = body && body.dataset.serviceWorkerUrl ? body.dataset.serviceWorkerUrl : "/service-worker.js";

    navigator.serviceWorker
      .register(serviceWorkerUrl, { scope: "/" })
      .then(function (registration) {
        activeServiceWorkerRegistration = registration;

        if (registration.waiting) {
          showUpdateToast(registration);
        }

        registration.addEventListener("updatefound", function () {
          const installingWorker = registration.installing;
          if (!installingWorker) {
            return;
          }

          installingWorker.addEventListener("statechange", function () {
            if (installingWorker.state === "installed" && navigator.serviceWorker.controller) {
              showUpdateToast(registration);
            }
          });
        });
      })
      .catch(function (error) {
        console.error("Service worker registration failed:", error);
      });

    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (window.__ggenreSwReloading) {
        return;
      }
      window.__ggenreSwReloading = true;
      window.location.reload();
    });
  }

  function updateNetworkPill(isOnline, stickyWhenOffline) {
    const pill = document.querySelector("[data-pwa-network-pill]");
    if (!pill) {
      return;
    }

    pill.hidden = false;
    pill.classList.toggle("is-online", Boolean(isOnline));
    pill.classList.toggle("is-offline", !isOnline);
    pill.textContent = isOnline ? "Back online" : "You're offline";

    if (isOnline) {
      window.setTimeout(function () {
        if (!stickyWhenOffline) {
          pill.hidden = true;
        }
      }, 2200);
    }
  }

  function initNetworkStateIndicator() {
    const pill = document.querySelector("[data-pwa-network-pill]");
    if (!pill) {
      return;
    }

    window.addEventListener("offline", function () {
      updateNetworkPill(false, true);
    });

    window.addEventListener("online", function () {
      updateNetworkPill(true, false);
    });

    if (!navigator.onLine) {
      updateNetworkPill(false, true);
    }
  }

  function syncAdminChatBadges(unreadCount) {
    const count = Number(unreadCount) || 0;
    document.querySelectorAll("[data-admin-chat-badge]").forEach(function (badge) {
      badge.textContent = String(count);
      badge.hidden = count <= 0;
    });
  }

  function showAdminChatToast(unreadCount, inboxUrl, message) {
    if (!inboxUrl || (unreadCount <= 0 && !message)) {
      return;
    }

    const existing = document.querySelector("[data-admin-chat-toast]");
    if (existing) {
      existing.remove();
    }

    const toast = document.createElement("a");
    toast.href = inboxUrl;
    toast.className = "pwa-network-pill is-online";
    toast.setAttribute("data-admin-chat-toast", "");
    toast.setAttribute("role", "status");
    toast.textContent = message || (unreadCount === 1 ? "New admin chat message" : unreadCount + " admin chat messages");
    document.body.appendChild(toast);

    window.setTimeout(function () {
      toast.remove();
    }, 4200);
  }

  function initAdminChatUnreadPolling() {
    const body = document.body;
    if (
      !body ||
      body.dataset.authenticated !== "1" ||
      body.dataset.userRole !== "admin" ||
      !body.dataset.adminChatUnreadUrl
    ) {
      return;
    }

    const unreadUrl = body.dataset.adminChatUnreadUrl;
    const inboxUrl = body.dataset.adminChatInboxUrl;
    const firstBadge = document.querySelector("[data-admin-chat-badge]");
    let lastCount = Number(firstBadge ? firstBadge.textContent : "0") || 0;
    let lastMissionRequestCount = Number(body.dataset.adminMissionRequestCount || "0") || 0;

    let unreadPollRequest = null;
    function pollUnread() {
      if (unreadPollRequest) return unreadPollRequest;
      unreadPollRequest = fetch(unreadUrl, { credentials: "include" })
        .then(function (response) {
          if (!response.ok) {
            return null;
          }
          return response.json();
        })
        .then(function (data) {
          if (!data) {
            return;
          }
          const nextUnreadCount = Number(data.unread_count) || 0;
          const nextMissionRequestCount = Number(data.mission_request_count) || 0;
          const nextCount = Number(data.total_action_count) || (nextUnreadCount + nextMissionRequestCount);
          syncAdminChatBadges(nextCount);
          if (nextMissionRequestCount > lastMissionRequestCount) {
            const added = nextMissionRequestCount - lastMissionRequestCount;
            showAdminChatToast(
              nextCount,
              inboxUrl,
              added === 1 ? "New mission request" : added + " new mission requests"
            );
          } else if (nextCount > lastCount) {
            showAdminChatToast(nextCount, inboxUrl);
          }
          lastCount = nextCount;
          lastMissionRequestCount = nextMissionRequestCount;
        })
        .catch(function () {
          // Ignore polling failures; the next interval can recover.
        }).finally(function () { unreadPollRequest = null; });
      return unreadPollRequest;
    }

    pollUnread();
    window.setInterval(pollUnread, 3000);
  }

  let floatingChatRefreshPending = false;

  function refreshFloatingChatWidget() {
    const currentWidget = document.querySelector(".admin-contact-chat");
    if (!currentWidget || floatingChatRefreshPending) {
      return;
    }

    floatingChatRefreshPending = true;
    const wasOpen = currentWidget.classList.contains("is-open");
    const url = window.location.pathname + window.location.search;
    fetch(url, {
      credentials: "include",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
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
        const parsed = new DOMParser().parseFromString(html, "text/html");
        const nextWidget = parsed.querySelector(".admin-contact-chat");
        if (!nextWidget) {
          if (typeof window.ggenreDisposeDirectChat === "function") {
            window.ggenreDisposeDirectChat(currentWidget);
          }
          currentWidget.remove();
          document.body.classList.remove("admin-contact-fullscreen-open");
          return;
        }
        if (typeof window.ggenreDisposeDirectChat === "function") {
          window.ggenreDisposeDirectChat(currentWidget);
        }
        currentWidget.replaceWith(nextWidget);
        if (wasOpen) {
          nextWidget.classList.add("is-open");
          const panel = nextWidget.querySelector("[data-chat-panel]");
          const toggle = nextWidget.querySelector("[data-chat-toggle]");
          if (panel) {
            panel.setAttribute("aria-hidden", "false");
          }
          if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
          }
          document.body.classList.add("admin-contact-fullscreen-open");
        }
        if (typeof window.ggenreInitDirectChat === "function") {
          window.ggenreInitDirectChat(nextWidget);
        }
        if (typeof window.ggenreInitMissionPanels === "function") {
          window.ggenreInitMissionPanels(nextWidget);
        }
      })
      .catch(function () {
        // The mission panel itself still receives mission updates; widget replacement can retry on the next event.
      })
      .finally(function () {
        floatingChatRefreshPending = false;
      });
  }

  function navigateActiveMissionChat(data) {
    if (!data || data.status !== "mission_active") {
      return;
    }
    const body = document.body;
    const chatPage = document.querySelector(".chat-page[data-direct-chat-user]");
    if (!body || body.dataset.userRole === "admin" || !chatPage) {
      return;
    }
    const currentUserId = Number(chatPage.getAttribute("data-current-user-id") || "0");
    const currentChatUserId = Number(chatPage.getAttribute("data-direct-chat-user") || "0");
    const requesterId = Number(data.requester_id || "0");
    const opponentId = Number(data.opponent_id || "0");
    if (!currentUserId || !requesterId || !opponentId) {
      return;
    }
    const missionChatUserId = currentUserId === requesterId ? opponentId : (currentUserId === opponentId ? requesterId : 0);
    if (!missionChatUserId || currentChatUserId === missionChatUserId) {
      return;
    }
    window.location.href = "/chat/u/" + String(missionChatUserId) + "/";
  }

  function initUserEventSocket() {
    const body = document.body;
    if (!body || body.dataset.authenticated !== "1") {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(protocol + "://" + window.location.host + "/ws/events/");

    socket.addEventListener("message", function (event) {
      let data = null;
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (!data || !data.type) {
        return;
      }

      if (data.type === "admin_counts") {
        const unreadCount = Number(data.unread_count) || 0;
        const missionRequestCount = Number(data.mission_request_count) || 0;
        const totalCount = Number(data.total_action_count) || (unreadCount + missionRequestCount);
        syncAdminChatBadges(totalCount);
        window.dispatchEvent(new CustomEvent("ggenre:admin-counts", { detail: data }));
        if (body.dataset.userRole === "admin") {
          showAdminChatToast(
            totalCount,
            body.dataset.adminChatInboxUrl,
            missionRequestCount > 0 ? "Admin inbox updated" : ""
          );
        }
        return;
      }

      if (data.type === "mission_updated") {
        window.dispatchEvent(new CustomEvent("ggenre:mission-updated", { detail: data }));
        refreshFloatingChatWidget();
        navigateActiveMissionChat(data);
      }
    });
  }

  function initFloatingBackButton() {
    const button = document.querySelector("[data-floating-back]");
    if (!button) {
      return;
    }

    const currentUrl = window.location.pathname + window.location.search;
    const fallbackUrl = button.getAttribute("data-fallback-url") || "/";
    const fallbackPath = new URL(fallbackUrl, window.location.origin).pathname;
    const previousUrl = window.sessionStorage.getItem("app-last-page-url");
    let hasInternalReferrer = false;
    try {
      hasInternalReferrer = Boolean(document.referrer) && new URL(document.referrer).origin === window.location.origin;
    } catch (error) {
      hasInternalReferrer = false;
    }
    const hasShiftedPages = Boolean(previousUrl && previousUrl !== currentUrl) || hasInternalReferrer;
    const isFallbackPage = window.location.pathname === fallbackPath;
    if (!isFallbackPage || hasShiftedPages) {
      button.classList.add("is-visible");
    }
    window.sessionStorage.setItem("app-last-page-url", currentUrl);

    button.addEventListener("click", function () {
      if (window.history.length > 1) {
        window.history.back();
        return;
      }
      window.location.href = fallbackUrl;
    });
  }

  applyTheme(resolveTheme());

  document.addEventListener("DOMContentLoaded", function () {
    initThemeToggle();
    initNavbarOutsideClick();
    initAnnouncements();
    initInstallFlow();
    initServiceWorker();
    initNetworkStateIndicator();
    initUserEventSocket();
    initAdminChatUnreadPolling();
    initFloatingBackButton();
  });
})();
