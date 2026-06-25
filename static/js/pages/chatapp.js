(function () {
  "use strict";

  const STANDARD_EMOJIS = [
    "\u{1F600}",
    "\u{1F602}",
    "\u{1F60A}",
    "\u{1F60D}",
    "\u{1F44D}",
    "\u{1F64F}",
    "\u{1F44F}",
    "\u{1F525}",
    "\u2764\uFE0F",
    "\u{1F3B5}",
    "\u{1F3A4}",
    "\u2B50",
    "\u2728",
    "\u{1F60E}",
    "\u{1F622}",
    "\u{1F62E}",
    "\u{1F64C}",
    "\u{1F4AF}",
    "\u2705",
    "\u{1F44B}",
  ];

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
    const messages = root.querySelector("[data-chat-messages]");
    const form = root.querySelector("[data-chat-form]");
    const input = root.querySelector("[data-chat-input]");
    const statusPill = root.querySelector("[data-chat-status-pill]");
    const toggle = root.querySelector("[data-chat-toggle]");
    const closeButton = root.querySelector("[data-chat-close]");
    const panel = root.querySelector("[data-chat-panel]");
    const isAdminContactWidget = root.getAttribute("data-chat-widget") === "admin-contact";
    const badge = root.querySelector("[data-admin-contact-badge]");
    const unreadUrl = document.body.getAttribute("data-admin-contact-unread-url");
    const markReadUrl = document.body.getAttribute("data-admin-contact-mark-read-url");
    let pendingMessage = null;
    let socketReady = false;
    let renderedOtpCode = "";

    if (!otherUserId || !currentUserId || !messages || !form || !input) {
      return;
    }

    const sendButton = form.querySelector("button[type='submit']");
    initEmojiPicker(form, input);

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

    function scrollToBottom() {
      messages.scrollTop = messages.scrollHeight;
    }

    function setStatus(text, state) {
      status.textContent = text;
      status.setAttribute("data-state", state || "");
      if (statusPill) {
        statusPill.setAttribute("data-state", state || "");
        statusPill.lastChild.textContent = text;
      }
    }

    function setCanSend(canSend) {
      if (sendButton) {
        sendButton.disabled = !canSend;
      }
    }

    function loadStoredMessages() {
      try {
        return JSON.parse(window.sessionStorage.getItem(storageKey) || "[]");
      } catch (error) {
        return [];
      }
    }

    function saveStoredMessages(stored) {
      window.sessionStorage.setItem(storageKey, JSON.stringify(stored.slice(-250)));
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
        delivery_status: 0,
      };
      addMessage(message);
      storeMessage(message);
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ message: body, client_id: message.client_id }));
        return true;
      }
      pendingMessage = message;
      setStatus("Connecting", "pending");
      setCanSend(false);
      return true;
    }

    function storeMessage(message) {
      const stored = loadStoredMessages();
      const existing = message.client_id ? stored.find(function (item) {
        return item.client_id === message.client_id;
      }) : null;
      if (existing) {
        Object.assign(existing, message);
      } else {
        stored.push(message);
      }
      saveStoredMessages(stored);
    }

    function addMessage(message) {
      const messageId = message.client_id || "";
      if (messageId) {
        const existingDelivery = messages.querySelector('[data-message-delivery="' + messageId + '"]');
        if (existingDelivery) {
          updateDeliveryStatus(messageId, Number(message.delivery_status || 1));
          return;
        }
      }
      const item = document.createElement("article");
      item.className = "chat-message";
      const isOwn = String(message.sender_id) === String(currentUserId) || message.sender === currentUser;
      if (isOwn) {
        item.classList.add("is-own");
      }

      const body = document.createElement("p");
      body.textContent = message.body || "";

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

      item.appendChild(body);
      item.appendChild(meta);
      messages.appendChild(item);
      scrollToBottom();
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
      }).catch(function () {});
    }

    function refreshAdminContactState() {
      if (!isAdminContactWidget || !unreadUrl) {
        return;
      }
      fetch(unreadUrl, { credentials: "include" })
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
        .catch(function () {});
    }

    function setWidgetOpen(isOpen) {
      root.classList.toggle("is-open", isOpen);
      if (toggle) {
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      }
      if (panel) {
        panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
      }
      if (isOpen) {
        markAdminContactRead();
        window.setTimeout(function () {
          input.focus();
          scrollToBottom();
        }, 0);
      }
    }

    loadStoredMessages().forEach(addMessage);
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
      setStatus("Online", "connected");
      setCanSend(true);
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
      const blockedByAuth = event.code === 4401 || event.code === 4403;
      setStatus(blockedByAuth ? "Chat locked" : "Realtime unavailable", "closed");
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
        setStatus("Realtime unavailable", "closed");
        if (window.console && typeof window.console.warn === "function") {
          window.console.warn(
            "Chat websocket failed. Check ASGI/Daphne, Nginx websocket upgrade headers, and allowed hosts for:",
            socketUrl
          );
        }
      }
      setCanSend(false);
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

    if (closeButton) {
      closeButton.addEventListener("click", function () {
        setWidgetOpen(false);
      });
    }

    if (panel) {
      panel.setAttribute("aria-hidden", "true");
    }
    scrollToBottom();
  }

  document.querySelectorAll("[data-direct-chat-user]").forEach(initDirectChat);
})();
