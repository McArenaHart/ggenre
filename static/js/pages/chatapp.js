(function () {
  "use strict";

  const STANDARD_EMOJI_CATEGORIES = {
    reactions: ["\u{1F600}", "\u{1F603}", "\u{1F604}", "\u{1F601}", "\u{1F606}", "\u{1F605}", "\u{1F602}", "\u{1F923}", "\u{1F60A}", "\u{1F642}", "\u{1F643}", "\u{1F609}", "\u{1F60C}", "\u{1F60D}", "\u{1F970}", "\u{1F618}", "\u{1F617}", "\u{1F619}", "\u{1F61A}", "\u{1F60B}", "\u{1F61B}", "\u{1F61C}", "\u{1F92A}", "\u{1F61D}", "\u{1F92D}", "\u{1F92B}", "\u{1F914}", "\u{1FAE1}", "\u{1F928}", "\u{1F610}", "\u{1F611}", "\u{1F636}", "\u{1FAE0}", "\u{1F644}", "\u{1F60F}", "\u{1F612}", "\u{1F62C}", "\u{1F62E}", "\u{1F62F}", "\u{1F632}", "\u{1F633}", "\u{1F97A}", "\u{1F979}", "\u{1F622}", "\u{1F62D}", "\u{1F624}", "\u{1F620}", "\u{1F621}", "\u{1F92F}", "\u{1F631}", "\u{1F628}", "\u{1F630}", "\u{1F634}", "\u{1F971}", "\u{1F924}", "\u{1F913}", "\u{1F60E}", "\u{1F973}", "\u{1F929}", "\u{1F920}", "\u{1F9D0}", "\u{1F607}", "\u{1F917}", "\u{1FAE3}", "\u{1FAE5}", "\u{1F910}", "\u{1F648}", "\u{1F649}", "\u{1F64A}", "\u{1F926}", "\u{1F937}", "\u{1F480}"],
    affection: ["\u2764\uFE0F", "\u{1FA77}", "\u{1F9E1}", "\u{1F49B}", "\u{1F49A}", "\u{1FA75}", "\u{1F499}", "\u{1F49C}", "\u{1F90E}", "\u{1F5A4}", "\u{1F90D}", "\u{1F496}", "\u{1F497}", "\u{1F493}", "\u{1F49E}", "\u{1F495}", "\u{1F498}", "\u{1F49D}", "\u{1F49F}", "\u2764\uFE0F\u200D\u{1F525}", "\u2764\uFE0F\u200D\u{1FA79}", "\u2763\uFE0F"],
    chemistry: ["\u{1F440}", "\u2728", "\u{1F4AB}", "\u{1F525}", "\u{1F339}", "\u{1F98B}", "\u{1F48C}", "\u{1F48B}"],
    gestures: ["\u{1F44D}", "\u{1F44E}", "\u{1F44C}", "\u270C\uFE0F", "\u{1F91E}", "\u{1F91F}", "\u{1F918}", "\u{1F919}", "\u{1F44B}", "\u{1F44F}", "\u{1F64C}", "\u{1F450}", "\u{1F932}", "\u{1F91D}", "\u{1F64F}", "\u{1F4AA}", "\u{1FAF6}", "\u{1F449}", "\u{1F448}", "\u261D\uFE0F", "\u{1F447}", "\u{1F446}", "\u270B", "\u{1F91A}", "\u{1F590}\uFE0F", "\u{1FAF5}", "\u{1F90C}"],
    celebration: ["\u2B50", "\u{1F31F}", "\u26A1", "\u{1F389}", "\u{1F38A}", "\u{1F3C6}", "\u{1F947}", "\u{1F4AF}", "\u{1F680}", "\u{1F4A5}", "\u{1F3AF}", "\u{1F48E}", "\u{1F451}", "\u2705", "\u274C", "\u2714\uFE0F", "\u2757", "\u2753"],
    music: ["\u{1F3B5}", "\u{1F3B6}", "\u{1F3A7}", "\u{1F3A4}", "\u{1F399}\uFE0F", "\u{1F3B8}", "\u{1F3B9}", "\u{1F941}", "\u{1F3B7}", "\u{1F3BA}", "\u{1F3BB}", "\u{1FA95}", "\u{1F4FB}", "\u{1F4BF}"],
    entertainment: ["\u{1F3AC}", "\u{1F3A5}", "\u{1F37F}", "\u{1F4FA}", "\u{1F3AD}", "\u{1F3AE}", "\u{1F579}\uFE0F", "\u{1F3B2}", "\u265F\uFE0F", "\u{1F0CF}", "\u{1F3A8}", "\u{1F4F8}", "\u{1F4F7}"],
    food: ["\u{1F355}", "\u{1F354}", "\u{1F35F}", "\u{1F32D}", "\u{1F357}", "\u{1F356}", "\u{1F32E}", "\u{1F32F}", "\u{1F35C}", "\u{1F35D}", "\u{1F363}", "\u{1F35A}", "\u{1F957}", "\u{1F96A}", "\u{1F373}", "\u{1F95E}", "\u{1F9C7}", "\u{1F366}", "\u{1F368}", "\u{1F369}", "\u{1F36A}", "\u{1F382}", "\u{1F370}", "\u{1F36B}", "\u{1F36C}", "\u{1F36D}", "\u{1F353}", "\u{1F349}", "\u{1F34D}", "\u{1F96D}", "\u{1F34E}", "\u2615", "\u{1F9CB}", "\u{1F964}", "\u{1F9C3}", "\u{1F4A7}"],
    travel: ["\u2708\uFE0F", "\u{1F697}", "\u{1F699}", "\u{1F3CD}\uFE0F", "\u{1F6B2}", "\u{1F686}", "\u{1F682}", "\u{1F6A2}", "\u{1F6F6}", "\u{1F3D5}\uFE0F", "\u{1F3D6}\uFE0F", "\u{1F3DD}\uFE0F", "\u{1F3DC}\uFE0F", "\u{1F3D4}\uFE0F", "\u26F0\uFE0F", "\u{1F30D}", "\u{1F30E}", "\u{1F30F}", "\u{1F5FA}\uFE0F", "\u{1F9F3}", "\u{1F4CD}", "\u{1F305}", "\u{1F304}", "\u{1F303}", "\u{1F306}"],
    nature: ["\u2600\uFE0F", "\u{1F31E}", "\u{1F324}\uFE0F", "\u26C5", "\u{1F327}\uFE0F", "\u26C8\uFE0F", "\u{1F308}", "\u{1F319}", "\u{1F338}", "\u{1F33A}", "\u{1F33B}", "\u{1F337}", "\u{1F340}", "\u{1F334}", "\u{1F30A}", "\u2744\uFE0F"],
    sports: ["\u26BD", "\u{1F3C0}", "\u{1F3C8}", "\u26BE", "\u{1F3BE}", "\u{1F3D0}", "\u{1F3C9}", "\u{1F94A}", "\u{1F3CB}\uFE0F", "\u{1F3C3}", "\u{1F6B4}", "\u{1F3CA}", "\u26F9\uFE0F"],
    ambition: ["\u{1F4BC}", "\u{1F4BB}", "\u{1F5A5}\uFE0F", "\u2328\uFE0F", "\u{1F4F1}", "\u{1F4CA}", "\u{1F4C8}", "\u{1F4C9}", "\u{1F4A1}", "\u{1F9E0}", "\u{1F4B0}", "\u{1F4B5}", "\u{1F4B8}", "\u{1F4DA}", "\u270D\uFE0F", "\u{1F4DD}"],
    conversation: ["\u{1F4AC}", "\u{1F5E8}\uFE0F", "\u{1F4AD}", "\u2754", "\u2755", "\u2049\uFE0F", "\u203C\uFE0F", "\u{1F4D6}"],
    social: ["\u{1F46F}", "\u{1F5E3}\uFE0F"],
    cute: ["\u263A\uFE0F", "\u{1F43B}", "\u{1F43C}", "\u{1F436}", "\u{1F431}"],
    animals: ["\u{1F42D}", "\u{1F439}", "\u{1F430}", "\u{1F98A}", "\u{1F428}", "\u{1F42F}", "\u{1F981}", "\u{1F438}", "\u{1F435}", "\u{1F427}", "\u{1F426}", "\u{1F41D}", "\u{1F422}", "\u{1F42C}"],
  };
  const STANDARD_EMOJIS = Array.from(
    new Set(
      Object.keys(STANDARD_EMOJI_CATEGORIES).reduce(function (allEmojis, categoryName) {
        return allEmojis.concat(STANDARD_EMOJI_CATEGORIES[categoryName]);
      }, [])
    )
  );
  const DEFAULT_MESSAGE_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
  const FLOATING_CHAT_OPEN_STORAGE_KEY = "ggenre:floating-chat-open";
  const initializedChatRoots = new WeakMap();

  function getSessionValue(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function setSessionValue(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
    } catch (error) {
      // Ignore storage failures in private or restricted browser modes.
    }
  }

  function insertAtCursor(input, value) {
    const start = input.selectionStart || input.value.length;
    const end = input.selectionEnd || input.value.length;
    input.value = input.value.slice(0, start) + value + input.value.slice(end);
    const nextPosition = start + value.length;
    input.focus();
    input.setSelectionRange(nextPosition, nextPosition);
  }

  function formatMessageTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatLastSeen(value) {
    if (!value) {
      return "Last seen recently";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Last seen recently";
    }

    const now = new Date();
    const diffMs = Math.max(0, now.getTime() - date.getTime());
    const minuteMs = 60 * 1000;
    const hourMs = 60 * minuteMs;
    const dayMs = 24 * hourMs;

    if (diffMs < minuteMs) {
      return "Last seen just now";
    }
    if (diffMs < hourMs) {
      const minutes = Math.max(1, Math.floor(diffMs / minuteMs));
      return "Last seen " + minutes + " minute" + (minutes === 1 ? "" : "s") + " ago";
    }
    if (diffMs < dayMs) {
      const hours = Math.max(1, Math.floor(diffMs / hourMs));
      return "Last seen " + hours + " hour" + (hours === 1 ? "" : "s") + " ago";
    }
    if (diffMs < 7 * dayMs) {
      const days = Math.max(1, Math.floor(diffMs / dayMs));
      return "Last seen " + days + " day" + (days === 1 ? "" : "s") + " ago";
    }

    const sameDay = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const sameAsYesterday = date.toDateString() === yesterday.toDateString();
    const timeText = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    if (sameDay) {
      return "Last seen today at " + timeText;
    }
    if (sameAsYesterday) {
      return "Last seen yesterday at " + timeText;
    }
    return "Last seen " + date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let index = 0; index < cookies.length; index += 1) {
      const cookie = cookies[index].trim();
      if (cookie.startsWith(name + "=")) {
        return decodeURIComponent(cookie.slice(name.length + 1));
      }
    }
    return "";
  }

  function initEmojiPicker(form, input) {
    if (form.querySelector("[data-chat-emoji-toggle]")) {
      return;
    }

    const wrapper = document.createElement("span");
    wrapper.className = "chat-emoji-picker";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "btn btn-outline-primary chat-emoji-toggle";
    toggle.setAttribute("data-chat-emoji-toggle", "");
    toggle.setAttribute("aria-label", "Add emoji");
    toggle.setAttribute("title", "Add emoji");
    toggle.textContent = "\u{1F60A}";

    const menu = document.createElement("div");
    menu.className = "chat-emoji-menu";
    menu.setAttribute("data-chat-emoji-menu", "");
    menu.hidden = true;

    STANDARD_EMOJIS.forEach(function (emoji) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-emoji-option";
      button.textContent = emoji;
      button.setAttribute("aria-label", "Insert emoji");
      button.addEventListener("click", function () {
        insertAtCursor(input, emoji);
        menu.hidden = true;
      });
      menu.appendChild(button);
    });

    toggle.addEventListener("click", function () {
      menu.hidden = !menu.hidden;
    });

    document.addEventListener("click", function (event) {
      if (!wrapper.contains(event.target)) {
        menu.hidden = true;
      }
    });

    wrapper.appendChild(toggle);
    wrapper.appendChild(menu);
    form.insertBefore(wrapper, input);
  }

  function initDirectChat(root) {
    if (!root || root.getAttribute("data-chat-initialized") === "1") {
      return;
    }

    const otherUserId = root.getAttribute("data-direct-chat-user");
    const currentUserId = root.getAttribute("data-current-user-id");
    const currentUser = root.getAttribute("data-current-user") || "";
    const otherUser = root.getAttribute("data-other-user") || "them";
    const historyUrl = root.getAttribute("data-chat-history-url") || "";
    const mediaUploadUrl = root.getAttribute("data-media-upload-url") || "";
    const messages = root.querySelector("[data-chat-messages]");
    const form = root.querySelector("[data-chat-form]");
    const input = root.querySelector("[data-chat-input]");
    const statusPill = root.querySelector("[data-chat-status-pill]");
    const toggle = root.querySelector("[data-chat-toggle]");
    const closeButton = root.querySelector("[data-chat-close]");
    const panel = root.querySelector("[data-chat-panel]");
    const chatWidgetType = root.getAttribute("data-chat-widget") || "";
    const isAdminContactWidget = chatWidgetType === "admin-contact";
    const isFloatingChatWidget = chatWidgetType === "admin-contact" || chatWidgetType === "mission-chat";
    const badge = root.querySelector("[data-admin-contact-badge]");
    const unreadUrl = document.body.getAttribute("data-admin-contact-unread-url");
    const markReadUrl = document.body.getAttribute("data-admin-contact-mark-read-url");
    const configuredRetentionMs = Number(root.getAttribute("data-message-retention-ms"));
    const messageCacheTtlMs = Number.isFinite(configuredRetentionMs) && configuredRetentionMs > 0
      ? configuredRetentionMs
      : DEFAULT_MESSAGE_CACHE_TTL_MS;
    let pendingMessage = null;
    let socketReady = false;
    let renderedOtpCode = "";
    let heartbeatInterval = null;
    let presenceRefreshInterval = null;
    let latestPresence = null;

    if (!otherUserId || !currentUserId || !messages || !form || !input) {
      return;
    }

    const sendButton = form.querySelector("button[type='submit']");
    initEmojiPicker(form, input);
    let mediaInput = null;
    if (mediaUploadUrl && !form.querySelector("[data-chat-media-input]")) {
      const mediaWrapper = document.createElement("span");
      mediaWrapper.className = "chat-media-picker";
      const mediaButton = document.createElement("button");
      mediaButton.type = "button";
      mediaButton.className = "btn btn-outline-primary chat-media-toggle";
      mediaButton.setAttribute("aria-label", "Share media: images, audio, video, PDF, or text files");
      mediaButton.setAttribute("aria-describedby", "chat-media-hint-" + otherUserId);
      mediaButton.innerHTML = '<i class="fas fa-paperclip" aria-hidden="true"></i>';
      const mediaHint = document.createElement("span");
      mediaHint.className = "chat-media-hint";
      mediaHint.id = "chat-media-hint-" + otherUserId;
      mediaHint.setAttribute("role", "tooltip");
      mediaHint.textContent = "Images, audio, video, PDF, text";
      mediaInput = document.createElement("input");
      mediaInput.type = "file";
      mediaInput.hidden = true;
      mediaInput.setAttribute("data-chat-media-input", "");
      mediaInput.accept = "image/*,audio/*,video/*,application/pdf,text/plain";
      mediaButton.addEventListener("click", function () {
        mediaInput.click();
      });
      mediaWrapper.appendChild(mediaButton);
      mediaWrapper.appendChild(mediaHint);
      form.insertBefore(mediaWrapper, input);
      form.appendChild(mediaInput);
    } else {
      mediaInput = form.querySelector("[data-chat-media-input]");
    }

    root.setAttribute("data-chat-initialized", "1");

    const chatIds = [Number(currentUserId), Number(otherUserId)].sort(function (a, b) {
      return a - b;
    });
    const storageKey = "direct-chat:" + chatIds[0] + ":" + chatIds[1];
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socketUrl = protocol + "://" + window.location.host + "/ws/chat/user/" + otherUserId + "/";
    const socket = new WebSocket(socketUrl);
    const status = document.createElement("small");
    status.className = "chat-connection-status";
    status.setAttribute("data-chat-status", "");
    status.textContent = "Connecting...";
    form.insertAdjacentElement("beforebegin", status);

    initializedChatRoots.set(root, function () {
      if (heartbeatInterval) {
        window.clearInterval(heartbeatInterval);
        heartbeatInterval = null;
      }
      if (presenceRefreshInterval) {
        window.clearInterval(presenceRefreshInterval);
        presenceRefreshInterval = null;
      }
      try {
        socket.close();
      } catch (error) {
        // Ignore socket cleanup errors during realtime widget swaps.
      }
      root.removeAttribute("data-chat-initialized");
    });

    function scrollToBottom() {
      messages.scrollTop = messages.scrollHeight;
    }

    function setConnectionStatus(text, state) {
      status.textContent = text;
      status.setAttribute("data-state", state || "");
    }

    function setPresenceStatus(text, state) {
      if (statusPill) {
        statusPill.setAttribute("data-state", state || "");
        statusPill.lastChild.textContent = text;
      }
    }

    function applyPresence(presence) {
      if (!presence) {
        return;
      }
      latestPresence = {
        is_online: Boolean(presence.is_online),
        last_seen_at: presence.last_seen_at || (latestPresence ? latestPresence.last_seen_at : null),
      };
      if (latestPresence.is_online) {
        setPresenceStatus("Online", "connected");
        return;
      }
      setPresenceStatus(formatLastSeen(latestPresence.last_seen_at), "idle");
    }

    function refreshPresenceText() {
      if (!latestPresence || latestPresence.is_online) {
        return;
      }
      setPresenceStatus(formatLastSeen(latestPresence.last_seen_at), "idle");
    }

    function setCanSend(canSend) {
      if (sendButton) {
        sendButton.disabled = !canSend;
      }
    }

    function loadStoredMessages() {
      const now = Date.now();
      const normalize = function (messages) {
        if (!Array.isArray(messages)) {
          return [];
        }
        return messages.filter(function (message) {
          let storedAt = Number(message.stored_at || message.created_at_timestamp || 0);
          if (!storedAt && message.created_at) {
            const createdAt = new Date(message.created_at).getTime();
            storedAt = Number.isNaN(createdAt) ? 0 : createdAt;
          }
          if (!storedAt) {
            return true;
          }
          return now - storedAt < messageCacheTtlMs;
        });
      };

      try {
        const localMessages = normalize(JSON.parse(window.localStorage.getItem(storageKey) || "[]"));
        if (localMessages.length) {
          window.sessionStorage.setItem(storageKey, JSON.stringify(localMessages));
          return localMessages;
        }
      } catch (error) {
        try {
          window.localStorage.removeItem(storageKey);
        } catch (removeError) { }
      }

      try {
        return normalize(JSON.parse(window.sessionStorage.getItem(storageKey) || "[]"));
      } catch (error) {
        return [];
      }
    }

    function saveStoredMessages(stored) {
      const now = Date.now();
      const messagesToStore = stored.slice(-250).map(function (message) {
        if (!message.stored_at) {
          message.stored_at = now;
        }
        return message;
      });
      const serialized = JSON.stringify(messagesToStore);
      window.sessionStorage.setItem(storageKey, serialized);
      try {
        window.localStorage.setItem(storageKey, serialized);
      } catch (error) { }
    }

    function createMessageId() {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
      }
      return "msg-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
    }

    function deliveryLabel(status) {
      if (status >= 2) {
        return "\u2713\u2713";
      }
      if (status === 1) {
        return "\u2713";
      }
      return "0";
    }

    function deliveryDescription(status) {
      if (status >= 2) {
        return "Read";
      }
      if (status === 1) {
        return "Delivered";
      }
      return "Not delivered";
    }

    function updateStoredMessageStatus(messageId, status) {
      if (!messageId) {
        return;
      }
      const stored = loadStoredMessages();
      let changed = false;
      stored.forEach(function (message) {
        if (message.client_id === messageId && Number(message.delivery_status || 0) < status) {
          message.delivery_status = status;
          changed = true;
        }
      });
      if (changed) {
        saveStoredMessages(stored);
      }
    }

    function updateDeliveryStatus(messageId, status) {
      if (!messageId) {
        return;
      }
      updateStoredMessageStatus(messageId, status);
      const delivery = messages.querySelector('[data-message-delivery="' + messageId + '"]');
      if (delivery) {
        delivery.textContent = deliveryLabel(status);
        delivery.setAttribute("aria-label", deliveryDescription(status));
        delivery.setAttribute("title", deliveryDescription(status));
      }
    }

    function sendMessage(value) {
      const body = value.trim();
      if (!body) {
        return false;
      }
      const message = {
        type: "message",
        client_id: createMessageId(),
        body: body,
        sender: currentUser,
        sender_id: currentUserId,
        recipient_id: otherUserId,
        created_at: new Date().toISOString(),
        stored_at: Date.now(),
        delivery_status: 0,
      };
      addMessage(message);
      storeMessage(message);
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ message: body, client_id: message.client_id }));
        return true;
      }
      pendingMessage = message;
      setConnectionStatus("Connecting", "pending");
      setCanSend(false);
      return true;
    }

    function storeMessage(message) {
      const stored = loadStoredMessages();
      const persistentMessageId = String(message.message_id || "");
      const existing = stored.find(function (item) {
        if (message.client_id && item.client_id === message.client_id) {
          return true;
        }
        return persistentMessageId && String(item.message_id || "") === persistentMessageId;
      });
      if (existing) {
        Object.assign(existing, message);
      } else {
        stored.push(message);
      }
      saveStoredMessages(stored);
    }

    function safeMediaType(type) {
      const normalized = String(type || "").toLowerCase();
      return ["image", "audio", "video", "file"].indexOf(normalized) >= 0 ? normalized : "file";
    }

    function safeMediaUrl(url) {
      const raw = String(url || "");
      if (!raw) {
        return "";
      }
      try {
        const parsed = new URL(raw, window.location.origin);
        if (["http:", "https:"].indexOf(parsed.protocol) < 0) {
          return "";
        }
        if (parsed.origin !== window.location.origin) {
          return "";
        }
        return parsed.href;
      } catch (error) {
        return "";
      }
    }

    function mediaTypeLabel(type) {
      if (type === "image") {
        return "Image";
      }
      if (type === "audio") {
        return "Audio";
      }
      if (type === "video") {
        return "Video";
      }
      return "File";
    }

    function mediaTypeIcon(type) {
      if (type === "image") {
        return "fa-image";
      }
      if (type === "audio") {
        return "fa-volume-up";
      }
      if (type === "video") {
        return "fa-play";
      }
      return "fa-file-alt";
    }

    function closeMediaViewer(viewer) {
      if (!viewer) {
        return;
      }
      viewer.querySelectorAll("audio, video").forEach(function (player) {
        player.pause();
        player.removeAttribute("src");
        player.load();
      });
      viewer.remove();
    }

    function openMediaViewer(media) {
      const type = safeMediaType(media.type);
      const url = safeMediaUrl(media.url);
      if (!url) {
        return;
      }
      const name = String(media.name || mediaTypeLabel(type));
      closeMediaViewer(document.querySelector("[data-chat-media-viewer]"));

      const overlay = document.createElement("div");
      overlay.className = "chat-media-viewer";
      overlay.setAttribute("data-chat-media-viewer", "");
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-label", "Media viewer");

      const dialog = document.createElement("div");
      dialog.className = "chat-media-viewer-dialog";
      const header = document.createElement("header");
      header.className = "chat-media-viewer-header";
      const title = document.createElement("div");
      const titleStrong = document.createElement("strong");
      titleStrong.textContent = name;
      const titleSpan = document.createElement("span");
      titleSpan.textContent = mediaTypeLabel(type);
      title.appendChild(titleStrong);
      title.appendChild(titleSpan);
      const closeButton = document.createElement("button");
      closeButton.type = "button";
      closeButton.className = "btn btn-outline-primary chat-media-viewer-close";
      closeButton.setAttribute("aria-label", "Close media viewer");
      closeButton.innerHTML = '<i class="fas fa-times" aria-hidden="true"></i>';
      header.appendChild(title);
      header.appendChild(closeButton);

      const body = document.createElement("div");
      body.className = "chat-media-viewer-body";
      if (type === "image") {
        const image = document.createElement("img");
        image.src = url;
        image.alt = name;
        body.appendChild(image);
      } else if (type === "audio") {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = url;
        body.appendChild(audio);
      } else if (type === "video") {
        const video = document.createElement("video");
        video.controls = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.src = url;
        body.appendChild(video);
      } else {
        const fileBox = document.createElement("div");
        fileBox.className = "chat-media-viewer-file";
        const icon = document.createElement("i");
        icon.className = "fas fa-file-alt";
        icon.setAttribute("aria-hidden", "true");
        const fileName = document.createElement("strong");
        fileName.textContent = name;
        const note = document.createElement("span");
        note.textContent = "Preview is limited for this file type.";
        const openLink = document.createElement("a");
        openLink.className = "btn btn-primary btn-sm";
        openLink.href = url;
        openLink.target = "_blank";
        openLink.rel = "noopener";
        openLink.textContent = "Open file";
        const frame = document.createElement("iframe");
        frame.className = "chat-media-viewer-frame";
        frame.src = url;
        frame.title = name;
        frame.setAttribute("sandbox", "");
        fileBox.appendChild(icon);
        fileBox.appendChild(fileName);
        fileBox.appendChild(note);
        fileBox.appendChild(frame);
        fileBox.appendChild(openLink);
        body.appendChild(fileBox);
      }

      dialog.appendChild(header);
      dialog.appendChild(body);
      overlay.appendChild(dialog);
      document.body.appendChild(overlay);
      closeButton.focus();

      closeButton.addEventListener("click", function () {
        closeMediaViewer(overlay);
      });
      overlay.addEventListener("click", function (event) {
        if (event.target === overlay) {
          closeMediaViewer(overlay);
        }
      });
      document.addEventListener("keydown", function handleEscape(event) {
        if (event.key === "Escape") {
          closeMediaViewer(overlay);
          document.removeEventListener("keydown", handleEscape);
        }
      });
    }

    function createMediaPreview(message) {
      const type = safeMediaType(message.media_type);
      const url = safeMediaUrl(message.media_url);
      if (!url) {
        return null;
      }
      const name = String(message.media_name || mediaTypeLabel(type));
      const mediaWrap = document.createElement("div");
      mediaWrap.className = "chat-message-media";
      const openButton = document.createElement("button");
      openButton.type = "button";
      openButton.className = "chat-media-open";
      openButton.setAttribute("data-media-url", url);
      openButton.setAttribute("aria-label", "Open " + mediaTypeLabel(type).toLowerCase() + ": " + name);

      const iconWrap = document.createElement("span");
      iconWrap.className = "chat-media-open-icon";
      const icon = document.createElement("i");
      icon.className = "fas " + mediaTypeIcon(type);
      icon.setAttribute("aria-hidden", "true");
      iconWrap.appendChild(icon);

      const label = document.createElement("span");
      label.className = "chat-media-open-label";
      const labelStrong = document.createElement("strong");
      labelStrong.textContent = name;
      const labelSpan = document.createElement("span");
      labelSpan.textContent = "Tap to open " + mediaTypeLabel(type).toLowerCase();
      label.appendChild(labelStrong);
      label.appendChild(labelSpan);

      openButton.appendChild(iconWrap);
      openButton.appendChild(label);
      openButton.addEventListener("click", function () {
        openMediaViewer({ type: type, url: url, name: name });
      });
      mediaWrap.appendChild(openButton);
      return mediaWrap;
    }

    function addMessage(message) {
      const messageId = message.client_id || "";
      const persistentMessageId = String(message.message_id || "");
      let existingItem = null;
      if (messageId) {
        existingItem = messages.querySelector('[data-message-client-id="' + messageId + '"]');
      }
      if (!existingItem && persistentMessageId) {
        existingItem = messages.querySelector('[data-message-id="' + persistentMessageId + '"]');
      }
      if (existingItem) {
        const existingHasMedia = Boolean(existingItem.querySelector(".chat-message-media"));
        const nextHasMedia = Boolean(message.media_url);
        if (existingHasMedia !== nextHasMedia) {
          existingItem.remove();
        } else {
          const existingMediaButton = existingItem.querySelector(".chat-media-open");
          const existingMediaUrl = existingMediaButton ? existingMediaButton.getAttribute("data-media-url") || "" : "";
          if (existingMediaUrl && message.media_url && existingMediaUrl !== safeMediaUrl(message.media_url)) {
            existingItem.remove();
          } else {
            if (messageId) {
              updateDeliveryStatus(messageId, Number(message.delivery_status || 1));
            }
            return;
          }
        }
      }
      if (existingItem && !document.body.contains(existingItem)) {
        existingItem = null;
      }
      if (existingItem) {
        if (messageId) {
          updateDeliveryStatus(messageId, Number(message.delivery_status || 1));
        }
        return;
      }
      const item = document.createElement("article");
      item.className = "chat-message";
      if (messageId) {
        item.setAttribute("data-message-client-id", messageId);
      }
      if (persistentMessageId) {
        item.setAttribute("data-message-id", persistentMessageId);
      }
      const isOwn = String(message.sender_id) === String(currentUserId) || message.sender === currentUser;
      if (isOwn) {
        item.classList.add("is-own");
      }

      const body = document.createElement("p");
      body.textContent = message.body || "";
      const mediaWrap = message.media_url ? createMediaPreview(message) : null;
      if (mediaWrap) {
        item.appendChild(mediaWrap);
      }

      const meta = document.createElement("span");
      meta.className = "chat-message-meta";
      meta.textContent = (isOwn ? "You" : (message.sender || otherUser)) + " - " + formatMessageTime(message.created_at);

      if (isOwn && messageId) {
        const delivery = document.createElement("span");
        const deliveryStatus = Number(message.delivery_status || 0);
        delivery.className = "chat-message-delivery";
        delivery.setAttribute("data-message-delivery", messageId);
        delivery.setAttribute("aria-label", deliveryDescription(deliveryStatus));
        delivery.setAttribute("title", deliveryDescription(deliveryStatus));
        delivery.textContent = deliveryLabel(deliveryStatus);
        meta.appendChild(delivery);
      }

      if (message.body) {
        item.appendChild(body);
      }
      item.appendChild(meta);
      messages.appendChild(item);
      scrollToBottom();
    }

    function uploadMedia(file) {
      if (!file || !mediaUploadUrl) {
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setConnectionStatus("Media must be 10MB or smaller", "closed");
        return;
      }
      const formData = new FormData();
      formData.append("media", file);
      formData.append("body", input.value.trim());
      setCanSend(false);
      fetch(mediaUploadUrl, {
        method: "POST",
        credentials: "include",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
      })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) {
              throw new Error(data.message || "Media upload failed.");
            }
            return data;
          });
        })
        .then(function (data) {
          if (data.message) {
            addMessage(data.message);
            storeMessage(data.message);
            input.value = "";
          }
          setConnectionStatus(socketReady ? "Connected" : "Connecting", socketReady ? "connected" : "pending");
        })
        .catch(function (error) {
          setConnectionStatus(error.message || "Media upload failed", "closed");
        })
        .finally(function () {
          setCanSend(socketReady);
          if (mediaInput) {
            mediaInput.value = "";
          }
        });
    }

    function mergeServerHistory(serverMessages) {
      if (!Array.isArray(serverMessages) || !serverMessages.length) {
        return;
      }
      serverMessages.forEach(function (message) {
        addMessage(message);
        storeMessage(message);
      });
      scrollToBottom();
    }

    function loadServerHistory() {
      if (!historyUrl) {
        return;
      }
      fetch(historyUrl, { credentials: "include" })
        .then(function (response) {
          if (!response.ok) {
            return null;
          }
          return response.json();
        })
        .then(function (data) {
          if (!data || !Array.isArray(data.messages)) {
            return;
          }
          applyPresence(data.presence);
          mergeServerHistory(data.messages);
        })
        .catch(function () { });
    }

    function updateAdminContactBadge(count) {
      if (!badge) {
        return;
      }
      const value = Number(count) || 0;
      badge.hidden = value <= 0;
      badge.textContent = value > 99 ? "99+" : String(value);
    }

    function renderOtpNotice(otp) {
      if (!isAdminContactWidget || !otp || !otp.code || renderedOtpCode === otp.code) {
        return;
      }
      renderedOtpCode = otp.code;
      const item = document.createElement("article");
      item.className = "chat-message is-otp";

      const title = document.createElement("strong");
      title.textContent = "Voting OTP from Admin";

      const body = document.createElement("p");
      body.textContent = "Use this OTP for voting access. Votes available: " + (otp.remaining_votes || 1) + ".";

      const code = document.createElement("span");
      code.className = "chat-otp-code";
      code.textContent = otp.code;

      item.appendChild(title);
      item.appendChild(body);
      item.appendChild(code);
      messages.appendChild(item);
      scrollToBottom();
    }

    function markAdminContactRead() {
      if (!isAdminContactWidget || !markReadUrl) {
        return;
      }
      fetch(markReadUrl, {
        method: "POST",
        credentials: "include",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
      }).then(function () {
        updateAdminContactBadge(0);
      }).catch(function () { });
    }

    let contactStateRequest = null;
    function refreshAdminContactState() {
      if (!isAdminContactWidget || !unreadUrl) {
        return;
      }
      if (contactStateRequest) return contactStateRequest;
      contactStateRequest = fetch(unreadUrl, { credentials: "include" })
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
          updateAdminContactBadge(data.unread_count);
          renderOtpNotice(data.otp);
        })
        .catch(function () { }).finally(function () { contactStateRequest = null; });
      return contactStateRequest;
    }

    function setWidgetOpen(isOpen) {
      root.classList.toggle("is-open", isOpen);
      if (isFloatingChatWidget) {
        document.body.classList.toggle("admin-contact-fullscreen-open", isOpen);
        setSessionValue(FLOATING_CHAT_OPEN_STORAGE_KEY, isOpen ? "1" : "0");
      }
      if (toggle) {
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      }
      if (panel) {
        panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
      }
      if (isOpen) {
        markAdminContactRead();
        window.setTimeout(function () {
          if (!isAdminContactWidget) {
            input.focus();
          }
          scrollToBottom();
        }, 0);
      }
    }

    loadStoredMessages().forEach(addMessage);
    setPresenceStatus("Last seen recently", "idle");
    loadServerHistory();
    if (statusPill) {
      presenceRefreshInterval = window.setInterval(refreshPresenceText, 60000);
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible") {
          refreshPresenceText();
        }
      });
    }
    if (isAdminContactWidget) {
      updateAdminContactBadge(root.getAttribute("data-admin-contact-unread"));
      renderOtpNotice({
        code: root.getAttribute("data-admin-contact-otp-code"),
        remaining_votes: root.getAttribute("data-admin-contact-otp-votes"),
      });
      refreshAdminContactState();
      window.setInterval(refreshAdminContactState, 30000);
    }

    setCanSend(false);

    socket.addEventListener("open", function () {
      socketReady = true;
      setConnectionStatus("Connected", "connected");
      setCanSend(true);
      if (heartbeatInterval) {
        window.clearInterval(heartbeatInterval);
      }
      heartbeatInterval = window.setInterval(function () {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, 30000);
      if (pendingMessage) {
        const queued = pendingMessage;
        pendingMessage = null;
        socket.send(JSON.stringify({ message: queued.body, client_id: queued.client_id }));
        input.value = "";
      }
    });

    socket.addEventListener("message", function (event) {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "receipt") {
          if (String(message.reader_id) === String(otherUserId)) {
            updateDeliveryStatus(message.message_id, 2);
          }
          return;
        }
        if (message.type === "presence") {
          if (String(message.user_id) === String(otherUserId)) {
            applyPresence(message);
          }
          return;
        }
        if (String(message.sender_id) === String(currentUserId) && message.client_id) {
          message.delivery_status = Math.max(Number(message.delivery_status || 0), 1);
        }
        addMessage(message);
        storeMessage(message);
        if (String(message.sender_id) !== String(currentUserId) && message.client_id && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "read", message_id: message.client_id }));
        }
      } catch (error) {
        return;
      }
    });

    socket.addEventListener("close", function (event) {
      socketReady = false;
      if (heartbeatInterval) {
        window.clearInterval(heartbeatInterval);
        heartbeatInterval = null;
      }
      const blockedByAuth = event.code === 4401 || event.code === 4403;
      setConnectionStatus(blockedByAuth ? "Chat locked" : "Realtime unavailable", "closed");
      setCanSend(false);
      if (!blockedByAuth && window.console && typeof window.console.warn === "function") {
        window.console.warn(
          "Chat websocket closed before connecting. Production must serve ASGI/Daphne and proxy websocket upgrades for:",
          socketUrl
        );
      }
    });

    socket.addEventListener("error", function () {
      if (!socketReady) {
        setConnectionStatus("Realtime unavailable", "closed");
        if (window.console && typeof window.console.warn === "function") {
          window.console.warn(
            "Chat websocket failed. Check ASGI/Daphne, Nginx websocket upgrade headers, and allowed hosts for:",
            socketUrl
          );
        }
      }
      if (heartbeatInterval) {
        window.clearInterval(heartbeatInterval);
        heartbeatInterval = null;
      }
      setCanSend(false);
    });

    window.addEventListener("beforeunload", function () {
      if (heartbeatInterval) {
        window.clearInterval(heartbeatInterval);
        heartbeatInterval = null;
      }
      if (presenceRefreshInterval) {
        window.clearInterval(presenceRefreshInterval);
        presenceRefreshInterval = null;
      }
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        return;
      }
      if (sendMessage(value)) {
        input.value = "";
      }
    });

    if (toggle) {
      toggle.addEventListener("click", function () {
        setWidgetOpen(!root.classList.contains("is-open"));
      });
    }

    if (mediaInput) {
      mediaInput.addEventListener("change", function () {
        uploadMedia(mediaInput.files && mediaInput.files[0]);
      });
    }

    if (closeButton) {
      closeButton.addEventListener("click", function () {
        setWidgetOpen(false);
      });
    }

    if (isFloatingChatWidget) {
      root.querySelectorAll(".admin-contact-nav a, .admin-contact-mission-head-actions a").forEach(function (link) {
        link.addEventListener("click", function () {
          setSessionValue(FLOATING_CHAT_OPEN_STORAGE_KEY, "0");
          document.body.classList.remove("admin-contact-fullscreen-open");
        });
      });
    }

    if (isAdminContactWidget) {
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && root.classList.contains("is-open")) {
          setWidgetOpen(false);
        }
      });
    }

    if (panel) {
      const shouldRestoreFloatingOpen = isFloatingChatWidget
        && (root.classList.contains("is-open") || getSessionValue(FLOATING_CHAT_OPEN_STORAGE_KEY) === "1");
      setWidgetOpen(shouldRestoreFloatingOpen);
    }
    scrollToBottom();
  }

  window.ggenreDisposeDirectChat = function (root) {
    const dispose = initializedChatRoots.get(root);
    if (!dispose) {
      return;
    }
    dispose();
    initializedChatRoots.delete(root);
  };

  window.ggenreInitDirectChat = initDirectChat;

  document.querySelectorAll("[data-direct-chat-user]").forEach(initDirectChat);
})();
