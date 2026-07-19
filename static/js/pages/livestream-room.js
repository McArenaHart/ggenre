(function () {
  "use strict";

  const root = document.querySelector("[data-stream-key]");
  if (!root) {
    return;
  }

  const streamKey = root.getAttribute("data-stream-key");
  const isHost = root.getAttribute("data-is-host") === "1";
  const localVideo = root.querySelector("[data-local-video]");
  const remoteVideo = root.querySelector("[data-remote-video]");
  const cameraButton = root.querySelector("[data-camera-toggle]");
  const cameraFlipButton = root.querySelector("[data-camera-flip]");
  const statusLabel = root.querySelector("[data-live-status]");
  const emptyState = root.querySelector("[data-stage-empty]");
  const chatMessages = root.querySelector("[data-chat-messages]");
  const chatForm = root.querySelector("[data-chat-form]");
  const chatInput = root.querySelector("[data-chat-input]");
  const currentUserId = root.getAttribute("data-current-user-id");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(protocol + "://" + window.location.host + "/ws/livestream/" + streamKey + "/");
  const peers = new Map();
  let localStream = null;
  let currentVideoDeviceId = null;
  const standardEmojis = [
    "😀",
    "😂",
    "😊",
    "😍",
    "👍",
    "🙏",
    "👏",
    "🔥",
    "❤️",
    "🎵",
    "🎤",
    "⭐",
    "✨",
    "😎",
    "😢",
    "😮",
    "🙌",
    "💯",
    "✅",
    "👋",
  ];

  const rtcConfig = {
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  };

  function setStatus(text) {
    if (statusLabel) {
      statusLabel.textContent = text;
    }
  }

  function showVideoReady() {
    if (emptyState) {
      emptyState.style.display = "none";
    }
  }

  function send(message) {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }

  function scrollChatToBottom() {
    if (chatMessages) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  function addChatMessage(message) {
    if (!chatMessages) {
      return;
    }

    const item = document.createElement("article");
    item.className = "chat-message";
    if (String(message.sender_id) === String(currentUserId)) {
      item.classList.add("is-own");
    }

    const sender = document.createElement("strong");
    sender.textContent = message.sender || "Viewer";

    const body = document.createElement("p");
    body.textContent = message.body || "";

    item.appendChild(sender);
    item.appendChild(body);
    chatMessages.appendChild(item);
    scrollChatToBottom();
  }

  function insertAtCursor(input, value) {
    const start = input.selectionStart || input.value.length;
    const end = input.selectionEnd || input.value.length;
    input.value = input.value.slice(0, start) + value + input.value.slice(end);
    const nextPosition = start + value.length;
    input.focus();
    input.setSelectionRange(nextPosition, nextPosition);
  }

  function initEmojiPicker() {
    if (!chatForm || !chatInput || chatForm.querySelector("[data-chat-emoji-toggle]")) {
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
    toggle.textContent = "😊";

    const menu = document.createElement("div");
    menu.className = "chat-emoji-menu";
    menu.hidden = true;

    standardEmojis.forEach(function (emoji) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-emoji-option";
      button.textContent = emoji;
      button.setAttribute("aria-label", "Insert " + emoji);
      button.addEventListener("click", function () {
        insertAtCursor(chatInput, emoji);
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
    chatForm.insertBefore(wrapper, chatInput);
  }

  async function getVideoInputDevices() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter(function (device) {
      return device.kind === "videoinput";
    });
  }

  function getStreamVideoDeviceId(stream) {
    return stream
      .getVideoTracks()
      .map(function (track) {
        return track.getSettings().deviceId;
      })
      .find(Boolean);
  }

  function replaceVideoTrack(newTrack) {
    if (!localStream || !newTrack) {
      return;
    }

    localStream.getVideoTracks().forEach(function (oldTrack) {
      localStream.removeTrack(oldTrack);
      oldTrack.stop();
    });
    localStream.addTrack(newTrack);
    localVideo.srcObject = localStream;

    peers.forEach(function (peer) {
      const sender = peer.getSenders().find(function (item) {
        return item.track && item.track.kind === "video";
      });
      if (sender) {
        sender.replaceTrack(newTrack);
      }
    });
  }

  async function ensureCamera(deviceId) {
    if (localStream && (!deviceId || deviceId === currentVideoDeviceId)) {
      return localStream;
    }

    const constraints = {
      video: deviceId
        ? { deviceId: { exact: deviceId } }
        : true,
      audio: true,
    };

    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (!localStream) {
      localStream = stream;
      localVideo.srcObject = localStream;
    } else {
      const newVideoTrack = stream.getVideoTracks()[0];
      replaceVideoTrack(newVideoTrack);
      stream.getTracks().forEach(function (track) {
        if (track.kind !== "video") {
          track.stop();
        }
      });
    }

    currentVideoDeviceId = getStreamVideoDeviceId(localStream);
    showVideoReady();
    return localStream;
  }

  async function flipCamera() {
    try {
      await ensureCamera();
      const cameras = await getVideoInputDevices();
      if (cameras.length < 2) {
        setStatus("No second camera available");
        return;
      }

      const currentIndex = cameras.findIndex(function (device) {
        return device.deviceId === currentVideoDeviceId;
      });
      const nextIndex = currentIndex < 0 ? 1 : (currentIndex + 1) % cameras.length;
      const nextDevice = cameras[nextIndex] || cameras[0];

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: nextDevice.deviceId } },
        audio: false,
      });
      const newVideoTrack = stream.getVideoTracks()[0];
      if (!newVideoTrack) {
        setStatus("Unable to switch camera");
        return;
      }

      replaceVideoTrack(newVideoTrack);
      currentVideoDeviceId = nextDevice.deviceId;
      setStatus("Camera flipped");
    } catch (error) {
      setStatus("Camera flip failed");
    }
  }

  function createPeer(peerId) {
    if (peers.has(peerId)) {
      return peers.get(peerId);
    }

    const peer = new RTCPeerConnection(rtcConfig);
    peers.set(peerId, peer);

    peer.onicecandidate = function (event) {
      if (event.candidate) {
        send({ event: "ice_candidate", target: peerId, payload: event.candidate });
      }
    };

    peer.ontrack = function (event) {
      remoteVideo.srcObject = event.streams[0];
      showVideoReady();
      setStatus("Live");
    };

    if (isHost && localStream) {
      localStream.getTracks().forEach(function (track) {
        peer.addTrack(track, localStream);
      });
    }

    return peer;
  }

  async function offerToViewer(peerId) {
    await ensureCamera();
    const peer = createPeer(peerId);
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    send({ event: "offer", target: peerId, payload: offer });
  }

  async function handleOffer(peerId, offer) {
    const peer = createPeer(peerId);
    await peer.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await peer.createAnswer();
    await peer.setLocalDescription(answer);
    send({ event: "answer", target: peerId, payload: answer });
  }

  async function handleAnswer(peerId, answer) {
    const peer = createPeer(peerId);
    await peer.setRemoteDescription(new RTCSessionDescription(answer));
  }

  async function handleIce(peerId, candidate) {
    const peer = createPeer(peerId);
    await peer.addIceCandidate(new RTCIceCandidate(candidate));
  }

  socket.addEventListener("open", function () {
    setStatus("Connected");
    if (!isHost) {
      send({ event: "viewer_ready" });
    }
  });

  socket.addEventListener("close", function () {
    setStatus("Disconnected");
  });

  socket.addEventListener("message", async function (event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }

    try {
      if (isHost && (message.event === "viewer_joined" || message.event === "viewer_ready")) {
        await offerToViewer(message.peer_id);
      } else if (!isHost && message.event === "offer") {
        await handleOffer(message.peer_id, message.payload);
      } else if (isHost && message.event === "answer") {
        await handleAnswer(message.peer_id, message.payload);
      } else if (message.event === "ice_candidate") {
        await handleIce(message.peer_id, message.payload);
      } else if (message.event === "peer_left" && peers.has(message.peer_id)) {
        peers.get(message.peer_id).close();
        peers.delete(message.peer_id);
      } else if (message.event === "chat_message") {
        addChatMessage(message.payload || {});
      }
    } catch (error) {
      setStatus("Connection issue");
    }
  });

  if (cameraButton) {
    cameraButton.addEventListener("click", async function () {
      try {
        await ensureCamera();
        setStatus("Camera ready");
      } catch (error) {
        setStatus("Camera blocked");
      }
    });
  }

  if (cameraFlipButton) {
    cameraFlipButton.addEventListener("click", function () {
      flipCamera();
    });
  }

  if (chatForm && chatInput) {
    initEmojiPicker();
    chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const value = chatInput.value.trim();
      if (!value) {
        return;
      }
      send({ event: "chat_message", message: value });
      chatInput.value = "";
    });
  }
})();
