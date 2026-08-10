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
  const micButton = root.querySelector("[data-mic-toggle]");
  const screenShareButton = root.querySelector("[data-screen-share]");
  const fullscreenButton = root.querySelector("[data-fullscreen-toggle]");
  const cameraSelect = root.querySelector("[data-camera-select]");
  const micSelect = root.querySelector("[data-mic-select]");
  const statusLabel = root.querySelector("[data-live-status]");
  const chatStatus = root.querySelector("[data-chat-status]");
  const viewerCountLabel = root.querySelector("[data-viewer-count]");
  const durationLabel = root.querySelector("[data-live-duration]");
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
  let currentAudioDeviceId = null;
  let preferredFacingMode = "user";
  let cameraEnabled = false;
  let micEnabled = true;
  let isScreenSharing = false;
  let screenShareTrack = null;
  let cameraDeviceBeforeScreenShare = null;
  let restoringCameraAfterScreenShare = false;
  let liveDurationTimer = null;
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

  const rtcConfig = {
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  };

  function setStatus(text) {
    if (statusLabel) {
      statusLabel.textContent = text;
    }
  }

  function setChatStatus(text) {
    if (chatStatus) {
      chatStatus.textContent = text;
    }
  }

  function setViewerCount(count) {
    if (viewerCountLabel) {
      viewerCountLabel.textContent = String(Math.max(0, Number(count) || 0));
    }
  }

  function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remaining = seconds % 60;
    if (hours > 0) {
      return [hours, minutes, remaining].map(function (part) {
        return String(part).padStart(2, "0");
      }).join(":");
    }
    return [minutes, remaining].map(function (part) {
      return String(part).padStart(2, "0");
    }).join(":");
  }

  function startDurationClock() {
    const startedAt = root.getAttribute("data-stream-started-at");
    if (!durationLabel || !startedAt) {
      return;
    }
    const startedAtMs = new Date(startedAt).getTime();
    if (Number.isNaN(startedAtMs)) {
      return;
    }
    window.clearInterval(liveDurationTimer);
    const tick = function () {
      durationLabel.textContent = formatDuration((Date.now() - startedAtMs) / 1000);
    };
    tick();
    liveDurationTimer = window.setInterval(tick, 1000);
  }

  function updateHostButtons() {
    if (cameraButton) {
      cameraButton.setAttribute("aria-pressed", cameraEnabled ? "true" : "false");
      cameraButton.classList.toggle("is-danger", !cameraEnabled);
      cameraButton.querySelector("i").className = cameraEnabled ? "fas fa-video" : "fas fa-video-slash";
    }
    if (micButton) {
      micButton.setAttribute("aria-pressed", micEnabled ? "true" : "false");
      micButton.classList.toggle("is-danger", !micEnabled);
      micButton.querySelector("i").className = micEnabled ? "fas fa-microphone" : "fas fa-microphone-slash";
    }
    if (screenShareButton) {
      screenShareButton.setAttribute("aria-pressed", isScreenSharing ? "true" : "false");
      screenShareButton.classList.toggle("is-danger", isScreenSharing);
      screenShareButton.querySelector("i").className = isScreenSharing ? "fas fa-stop-circle" : "fas fa-desktop";
      const label = screenShareButton.querySelector("span");
      if (label) {
        label.textContent = isScreenSharing ? "Stop Share" : "Screen";
      }
    }
    if (cameraFlipButton && isScreenSharing) {
      cameraFlipButton.disabled = true;
    }
    if (cameraSelect) {
      cameraSelect.disabled = isScreenSharing;
    }
  }

  function showVideoReady() {
    if (emptyState) {
      emptyState.style.display = "none";
    }
  }

  function showVideoEmpty(text) {
    if (emptyState) {
      emptyState.style.display = "";
      const label = emptyState.querySelector("span");
      if (label && text) {
        label.textContent = text;
      }
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
    toggle.textContent = "\u{1F60A}";

    const menu = document.createElement("div");
    menu.className = "chat-emoji-menu";
    menu.hidden = true;

    STANDARD_EMOJIS.forEach(function (emoji) {
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

  async function getAudioInputDevices() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter(function (device) {
      return device.kind === "audioinput";
    });
  }

  function setSelectOptions(select, devices, fallbackLabel, selectedId) {
    if (!select) {
      return;
    }
    select.innerHTML = "";
    devices.forEach(function (device, index) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || fallbackLabel + " " + (index + 1);
      option.selected = Boolean(selectedId && selectedId === device.deviceId);
      select.appendChild(option);
    });
    if (!devices.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = fallbackLabel;
      select.appendChild(option);
    }
  }

  async function refreshDevicePickers() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return;
    }
    try {
      const cameras = await getVideoInputDevices();
      const microphones = await getAudioInputDevices();
      setSelectOptions(cameraSelect, cameras, "Camera", currentVideoDeviceId);
      setSelectOptions(micSelect, microphones, "Microphone", currentAudioDeviceId);
      if (cameraFlipButton) {
        cameraFlipButton.disabled = isScreenSharing || cameras.length < 2;
      }
      if (cameraSelect) {
        cameraSelect.disabled = isScreenSharing;
      }
    } catch (error) {
      setStatus("Device list unavailable");
    }
  }

  function getStreamVideoDeviceId(stream) {
    return stream
      .getVideoTracks()
      .map(function (track) {
        return track.getSettings().deviceId;
      })
      .find(Boolean);
  }

  function getStreamAudioDeviceId(stream) {
    return stream
      .getAudioTracks()
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

  async function ensureCamera(options) {
    const settings = options || {};
    const deviceId = settings.videoDeviceId || currentVideoDeviceId;
    const audioDeviceId = settings.audioDeviceId || currentAudioDeviceId;
    if (localStream && (!settings.force) && (!settings.videoDeviceId || settings.videoDeviceId === currentVideoDeviceId) && (!settings.audioDeviceId || settings.audioDeviceId === currentAudioDeviceId)) {
      return localStream;
    }

    const constraints = {
      video: deviceId
        ? { deviceId: { exact: deviceId } }
        : { facingMode: { ideal: preferredFacingMode }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: audioDeviceId ? { deviceId: { exact: audioDeviceId } } : true,
    };

    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (!localStream) {
      localStream = stream;
      localVideo.srcObject = localStream;
    } else {
      const newVideoTrack = stream.getVideoTracks()[0];
      const newAudioTrack = stream.getAudioTracks()[0];
      replaceVideoTrack(newVideoTrack);
      if (newAudioTrack) {
        localStream.getAudioTracks().forEach(function (oldTrack) {
          localStream.removeTrack(oldTrack);
          oldTrack.stop();
        });
        localStream.addTrack(newAudioTrack);
        peers.forEach(function (peer) {
          const sender = peer.getSenders().find(function (item) {
            return item.track && item.track.kind === "audio";
          });
          if (sender) {
            sender.replaceTrack(newAudioTrack);
          }
        });
      }
      stream.getTracks().forEach(function (track) {
        if (!localStream.getTracks().includes(track)) {
          track.stop();
        }
      });
    }

    currentVideoDeviceId = getStreamVideoDeviceId(localStream);
    currentAudioDeviceId = getStreamAudioDeviceId(localStream);
    cameraEnabled = localStream.getVideoTracks().some(function (track) {
      return track.enabled;
    });
    micEnabled = localStream.getAudioTracks().every(function (track) {
      return track.enabled;
    });
    updateHostButtons();
    await refreshDevicePickers();
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
      preferredFacingMode = preferredFacingMode === "user" ? "environment" : "user";

      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          deviceId: { exact: nextDevice.deviceId },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      const newVideoTrack = stream.getVideoTracks()[0];
      if (!newVideoTrack) {
        setStatus("Unable to switch camera");
        return;
      }

      replaceVideoTrack(newVideoTrack);
      currentVideoDeviceId = nextDevice.deviceId;
      if (cameraSelect) {
        cameraSelect.value = currentVideoDeviceId;
      }
      setStatus("Camera flipped");
    } catch (error) {
      setStatus("Camera flip failed");
    }
  }

  function toggleMic() {
    if (!localStream) {
      return;
    }
    micEnabled = !micEnabled;
    localStream.getAudioTracks().forEach(function (track) {
      track.enabled = micEnabled;
    });
    updateHostButtons();
    setStatus(micEnabled ? "Mic live" : "Mic muted");
  }

  async function toggleCamera() {
    if (isScreenSharing) {
      await stopScreenShare();
      return;
    }
    if (!localStream) {
      await ensureCamera({ force: true });
      setStatus("Camera ready");
      return;
    }
    cameraEnabled = !cameraEnabled;
    localStream.getVideoTracks().forEach(function (track) {
      track.enabled = cameraEnabled;
    });
    updateHostButtons();
    if (cameraEnabled) {
      showVideoReady();
      setStatus("Camera live");
    } else {
      showVideoEmpty("Camera is off.");
      setStatus("Camera off");
    }
  }

  async function restoreCameraAfterScreenShare() {
    if (restoringCameraAfterScreenShare) {
      return;
    }
    restoringCameraAfterScreenShare = true;
    try {
      const restoreDeviceId = cameraDeviceBeforeScreenShare || currentVideoDeviceId;
      isScreenSharing = false;
      screenShareTrack = null;
      await ensureCamera({ videoDeviceId: restoreDeviceId, force: true });
      cameraEnabled = true;
      showVideoReady();
      setStatus("Camera live");
    } catch (error) {
      isScreenSharing = false;
      screenShareTrack = null;
      cameraEnabled = false;
      showVideoEmpty("Screen sharing stopped. Start your camera again.");
      setStatus("Camera restore failed");
    } finally {
      restoringCameraAfterScreenShare = false;
      cameraDeviceBeforeScreenShare = null;
      updateHostButtons();
      refreshDevicePickers();
    }
  }

  async function stopScreenShare() {
    if (!isScreenSharing) {
      return;
    }
    const track = screenShareTrack;
    if (track && track.readyState !== "ended") {
      track.stop();
    }
    await restoreCameraAfterScreenShare();
  }

  async function startScreenShare() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      setStatus("Screen share unavailable");
      return;
    }
    try {
      await ensureCamera();
      cameraDeviceBeforeScreenShare = currentVideoDeviceId;
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          cursor: "always",
          displaySurface: "monitor",
        },
        audio: false,
      });
      const screenTrack = displayStream.getVideoTracks()[0];
      if (!screenTrack) {
        setStatus("Screen share failed");
        return;
      }
      replaceVideoTrack(screenTrack);
      screenShareTrack = screenTrack;
      isScreenSharing = true;
      cameraEnabled = true;
      updateHostButtons();
      refreshDevicePickers();
      setStatus("Sharing screen");
      screenTrack.addEventListener("ended", async function () {
        await restoreCameraAfterScreenShare();
      });
    } catch (error) {
      cameraDeviceBeforeScreenShare = null;
      isScreenSharing = false;
      screenShareTrack = null;
      updateHostButtons();
      setStatus("Screen share cancelled");
    }
  }

  async function toggleScreenShare() {
    if (isScreenSharing) {
      await stopScreenShare();
      return;
    }
    await startScreenShare();
  }

  function toggleFullscreen() {
    const target = root.querySelector(".livestream-stage") || root;
    if (!document.fullscreenElement) {
      target.requestFullscreen?.();
      return;
    }
    document.exitFullscreen?.();
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
    setChatStatus("Realtime chat connected");
    if (!isHost) {
      send({ event: "viewer_ready" });
    }
  });

  socket.addEventListener("close", function () {
    setStatus("Disconnected");
    setChatStatus("Realtime chat disconnected");
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
      } else if (message.event === "viewer_count") {
        setViewerCount(message.payload && message.payload.count);
      } else if (message.event === "host_joined") {
        setStatus("Host connected");
      }
    } catch (error) {
      setStatus("Connection issue");
    }
  });

  if (cameraButton) {
    cameraButton.addEventListener("click", async function () {
      try {
        await toggleCamera();
      } catch (error) {
        setStatus("Camera blocked");
      }
    });
  }

  if (micButton) {
    micButton.addEventListener("click", async function () {
      try {
        if (!localStream) {
          await ensureCamera();
        }
        toggleMic();
      } catch (error) {
        setStatus("Microphone blocked");
      }
    });
  }

  if (cameraFlipButton) {
    cameraFlipButton.addEventListener("click", function () {
      flipCamera();
    });
  }

  if (screenShareButton) {
    screenShareButton.addEventListener("click", function () {
      toggleScreenShare();
    });
  }

  if (fullscreenButton) {
    fullscreenButton.addEventListener("click", function () {
      toggleFullscreen();
    });
  }

  if (cameraSelect) {
    cameraSelect.addEventListener("change", async function () {
      try {
        await ensureCamera({ videoDeviceId: cameraSelect.value, force: true });
        setStatus("Camera switched");
      } catch (error) {
        setStatus("Camera switch failed");
      }
    });
  }

  if (micSelect) {
    micSelect.addEventListener("change", async function () {
      try {
        await ensureCamera({ audioDeviceId: micSelect.value, force: true });
        setStatus("Microphone switched");
      } catch (error) {
        setStatus("Microphone switch failed");
      }
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

  updateHostButtons();
  refreshDevicePickers();
  startDurationClock();
})();
