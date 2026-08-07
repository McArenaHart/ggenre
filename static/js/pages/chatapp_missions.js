(function () {
    "use strict";

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

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify(payload || {}),
            credentials: "same-origin",
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { status: "error", message: "Unexpected server response." };
        }
        if (!response.ok) {
            const requestError = new Error(data.message || "Request failed.");
            requestError.statusCode = response.status;
            requestError.errorCode = data.error_code || "";
            requestError.errorType = data.error_type || "system";
            throw requestError;
        }
        return data;
    }

    async function postForm(url, formData) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: formData,
            credentials: "same-origin",
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { status: "error", message: "Unexpected server response." };
        }
        if (!response.ok) {
            const requestError = new Error(data.message || "Request failed.");
            requestError.statusCode = response.status;
            requestError.errorCode = data.error_code || "";
            requestError.errorType = data.error_type || "system";
            throw requestError;
        }
        return data;
    }

    async function getJson(url) {
        const response = await fetch(url, {
            method: "GET",
            headers: {
                "Accept": "application/json",
            },
            credentials: "same-origin",
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { status: "error", message: "Unexpected server response." };
        }
        if (!response.ok) {
            const requestError = new Error(data.message || "Request failed.");
            requestError.statusCode = response.status;
            requestError.errorCode = data.error_code || "";
            requestError.errorType = data.error_type || "system";
            throw requestError;
        }
        return data;
    }

    function setText(el, text) {
        if (!el) {
            return;
        }
        el.textContent = text;
    }

    function missionActionUrl(missionId) {
        return "/chat/missions/" + missionId + "/action/";
    }

    function tokenReviewUrl(requestId) {
        return "/chat/token-purchases/" + requestId + "/review/";
    }

    function missionDetailUrl(template, missionId) {
        return String(template || "").replace("/0/", "/" + String(missionId) + "/");
    }

    function userChatUrl(userId) {
        return "/chat/u/" + String(userId) + "/";
    }

    function formatTimer(seconds) {
        const safe = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(safe / 60);
        const remainder = safe % 60;
        return String(minutes).padStart(2, "0") + ":" + String(remainder).padStart(2, "0");
    }

    function initPlayerPanel(root) {
        if (!root || root.getAttribute("data-mission-panel-initialized") === "1") {
            return;
        }
        const panel = root.querySelector("[data-player-mission-panel]");
        if (!panel) {
            return;
        }
        root.setAttribute("data-mission-panel-initialized", "1");

        let activeMissionId = null;
        let missionCountdownTimer = null;
        let missionAutoRefreshTimer = null;
        let missionDiscoveryTimer = null;
        let missionAutoRefreshPending = false;
        let isRefreshingMission = false;
        let popupActionName = "";
        let lastDismissedPopupKey = "";
        let currentPopupKey = "";
        const statusEl = panel.querySelector("[data-mission-status]");
        const tokenStatusEl = panel.querySelector("[data-token-request-status]");
        const requestMissionBtn = panel.querySelector("[data-mission-request-btn]");
        const refreshBtn = panel.querySelector("[data-mission-refresh-btn]");
        const proofExplanation = panel.querySelector("[data-proof-explanation]");
        const proofImage = panel.querySelector("[data-proof-image]");
        const tokenCount = panel.querySelector("[data-token-count]");
        const tokenChannel = panel.querySelector("[data-token-channel]");
        const tokenReference = panel.querySelector("[data-token-reference]");
        const tokenRequestBtn = panel.querySelector("[data-token-request-btn]");
        const missionRequestUrl = root.getAttribute("data-mission-request-url");
        const missionLatestUrl = root.getAttribute("data-mission-latest-url");
        const missionDetailTemplate = root.getAttribute("data-mission-detail-template");
        const tokenRequestUrl = root.getAttribute("data-token-request-url");
        const opponentStatusEl = panel.querySelector("[data-opponent-status]");
        const missionTimerEl = panel.querySelector("[data-mission-timer]");
        const missionTimerTrackEl = panel.querySelector("[data-mission-timer-track]");
        const missionTimerFillEl = panel.querySelector("[data-mission-timer-fill]");
        const matchmakingCardEl = panel.querySelector("[data-mission-search-card]");
        const opponentCardEl = panel.querySelector("[data-opponent-card]");
        const opponentAvatarEl = panel.querySelector("[data-opponent-avatar]");
        const opponentNameEl = panel.querySelector("[data-opponent-name]");
        const opponentMetaEl = panel.querySelector("[data-opponent-meta]");
        const missionInstructionEl = panel.querySelector("[data-mission-instruction]");
        const missionInstructionLabelEl = missionInstructionEl ? missionInstructionEl.querySelector("span") : null;
        const missionInstructionTextEl = missionInstructionEl ? missionInstructionEl.querySelector("strong") : null;
        const missionPopupEl = panel.querySelector("[data-mission-popup]");
        const missionPopupTitleEl = panel.querySelector("[data-mission-popup-title]");
        const missionPopupBodyEl = panel.querySelector("[data-mission-popup-body]");
        const missionPopupMetaEl = panel.querySelector("[data-mission-popup-meta]");
        const missionPopupActionBtn = panel.querySelector("[data-mission-popup-action]");
        const missionPopupCloseBtn = panel.querySelector("[data-mission-popup-close]");
        const missionActionRow = panel.querySelector("[data-mission-action-row]");
        const proofRow = panel.querySelector("[data-proof-row]");
        const actionButtons = {};
        panel.querySelectorAll("[data-mission-action]").forEach(function (button) {
            actionButtons[button.getAttribute("data-mission-action")] = button;
        });

        if (statusEl) {
            const seededMissionId = Number(statusEl.getAttribute("data-latest-mission-id") || "0");
            if (seededMissionId > 0) {
                activeMissionId = seededMissionId;
            }
        }

        function showMatchmaking(visible) {
            if (!matchmakingCardEl) {
                return;
            }
            matchmakingCardEl.hidden = !visible;
        }

        function closeMissionPopup() {
            if (missionPopupEl) {
                missionPopupEl.hidden = true;
            }
        }

        function renderMissionPopup(mission) {
            if (!missionPopupEl || !mission) {
                return;
            }
            const popupStatuses = {
                opponent_proposed: true,
                mission_proposed: true,
                mission_active: true,
            };
            if (!popupStatuses[mission.status]) {
                closeMissionPopup();
                return;
            }

            const popupKey = String(mission.id) + ":" + String(mission.status) + ":" + String(mission.mission_template_id || "none");
            if (lastDismissedPopupKey === popupKey) {
                return;
            }
            currentPopupKey = popupKey;

            const otherPlayer = mission.other_player_profile || mission.opponent_profile || mission.requester_profile;
            const opponentName = otherPlayer && otherPlayer.username
                ? otherPlayer.username
                : "your opponent";
            const instruction = mission.mission_instruction || "Mission details are being prepared.";
            popupActionName = "";

            if (mission.status === "opponent_proposed") {
                setText(missionPopupTitleEl, "Opponent Found");
                setText(missionPopupBodyEl, "Admin matched you with " + opponentName + ".");
                setText(
                    missionPopupMetaEl,
                    mission.viewer_role === "opponent"
                        ? "Waiting for the requesting player to confirm the match."
                        : "Accept this opponent or request another match."
                );
                if (missionPopupActionBtn) {
                    missionPopupActionBtn.hidden = mission.viewer_role === "opponent";
                    missionPopupActionBtn.textContent = "Accept Opponent";
                }
                popupActionName = mission.viewer_role === "opponent" ? "" : "accept_opponent";
            } else if (mission.status === "mission_proposed") {
                setText(
                    missionPopupTitleEl,
                    mission.viewer_role === "opponent" ? "Mission Chat" : "Your Secret Mission"
                );
                setText(missionPopupBodyEl, instruction);
                setText(
                    missionPopupMetaEl,
                    mission.viewer_role === "opponent"
                        ? "Wait for the requester to start the timer, then play your role in the opponent chat."
                        : "Accept the mission to start the timer and unlock the opponent chat."
                );
                if (missionPopupActionBtn) {
                    missionPopupActionBtn.hidden = mission.viewer_role === "opponent";
                    missionPopupActionBtn.textContent = "Accept Mission";
                }
                popupActionName = mission.viewer_role === "opponent" ? "" : "accept_mission";
            } else {
                setText(missionPopupTitleEl, "Mission Started");
                setText(missionPopupBodyEl, "Chat with " + opponentName + " directly and complete the mission before the timer ends.");
                setText(missionPopupMetaEl, instruction);
                if (missionPopupActionBtn) {
                    missionPopupActionBtn.hidden = !(otherPlayer && otherPlayer.id);
                    missionPopupActionBtn.textContent = "Open Opponent Chat";
                }
                popupActionName = otherPlayer && otherPlayer.id ? "open_opponent_chat:" + String(otherPlayer.id) : "";
            }

            missionPopupEl.hidden = false;
        }

        function stopMissionCountdown() {
            if (missionCountdownTimer) {
                window.clearInterval(missionCountdownTimer);
                missionCountdownTimer = null;
            }
        }

        function clearMissionAutoRefresh() {
            if (missionAutoRefreshTimer) {
                window.clearTimeout(missionAutoRefreshTimer);
                missionAutoRefreshTimer = null;
            }
            missionAutoRefreshPending = false;
        }

        function scheduleMissionDiscovery() {
            if (missionDiscoveryTimer || activeMissionId || !missionLatestUrl) {
                return;
            }
            missionDiscoveryTimer = window.setInterval(function () {
                if (!activeMissionId) {
                    refreshLatestMission({ silent: true });
                }
            }, 8000);
        }

        function clearMissionDiscovery() {
            if (missionDiscoveryTimer) {
                window.clearInterval(missionDiscoveryTimer);
                missionDiscoveryTimer = null;
            }
        }

        function missionActionErrorMessage(error) {
            if (error && error.errorCode === "chat_proof_empty") {
                return "No chat proof captured yet. Keep chatting until the mission instruction is clearly completed, then submit again.";
            }
            if (error && error.errorType === "permission") {
                return "This action is not available to you for this mission.";
            }
            if (error && error.errorType === "user_action") {
                return error.message || "The mission requirements are not complete yet.";
            }
            return error && error.message ? error.message : "Mission update failed.";
        }

        function scheduleMissionAutoRefresh(delayMs) {
            if (!activeMissionId || missionAutoRefreshPending || isRefreshingMission) {
                return;
            }
            missionAutoRefreshPending = true;
            missionAutoRefreshTimer = window.setTimeout(function () {
                missionAutoRefreshPending = false;
                missionAutoRefreshTimer = null;
                refreshMission({ silent: true, source: "auto" });
            }, delayMs);
        }

        function setTimerProgress(percent) {
            if (!missionTimerTrackEl || !missionTimerFillEl) {
                return;
            }
            const clamped = Math.min(100, Math.max(0, Number(percent) || 0));
            missionTimerTrackEl.hidden = false;
            missionTimerTrackEl.classList.toggle("is-complete", clamped <= 0);
            missionTimerFillEl.style.width = String(clamped) + "%";
        }

        function setVisible(el, visible) {
            if (!el) {
                return;
            }
            el.hidden = !visible;
        }

        function resetMissionControls() {
            Object.keys(actionButtons).forEach(function (actionName) {
                actionButtons[actionName].disabled = true;
                actionButtons[actionName].hidden = true;
            });
            setVisible(missionActionRow, false);
            setVisible(proofRow, false);
            if (requestMissionBtn) {
                requestMissionBtn.hidden = false;
                requestMissionBtn.disabled = false;
                requestMissionBtn.textContent = "Request Mission";
            }
        }

        function showMissionAction(actionName, disabled) {
            const button = actionButtons[actionName];
            if (!button) {
                return;
            }
            button.hidden = false;
            button.disabled = Boolean(disabled);
            setVisible(missionActionRow, true);
        }

        function renderOpponentSummary(mission) {
            const opponent = mission && (mission.other_player_profile || mission.opponent_profile);
            const isMatching = mission && (
                mission.status === "requested" ||
                mission.status === "matching"
            );
            showMatchmaking(Boolean(isMatching));
            if (isMatching) {
                scheduleMissionAutoRefresh(5000);
            } else {
                clearMissionAutoRefresh();
            }

            if (!opponent || !opponent.username) {
                if (opponentCardEl) {
                    opponentCardEl.hidden = true;
                }
                setText(opponentStatusEl, "");
                return;
            }
            if (opponentCardEl) {
                opponentCardEl.hidden = false;
            }
            if (opponentAvatarEl) {
                opponentAvatarEl.src = opponent.profile_picture_url || "";
            }
            setText(opponentNameEl, opponent.username);
            setText(
                opponentMetaEl,
                "Badge L" + String(opponent.badge_level || 1) +
                " | Points " + String(opponent.current_points || 0) +
                " | Homepage Wins " + String(opponent.homepage_wins || 0)
            );
            setText(
                opponentStatusEl,
                "Opponent Found: " + opponent.username +
                " | Badge L" + String(opponent.badge_level || 1) +
                " | Points " + String(opponent.current_points || 0)
            );
        }

        function renderMissionInstruction(mission) {
            const statusesWithInstruction = {
                mission_proposed: true,
                mission_active: true,
                proof_submitted: true,
                under_review: true,
                approved: true,
                rejected: true,
                cooldown_vote_required: true,
            };
            if (!missionInstructionEl || !missionInstructionTextEl) {
                return;
            }
            if (!mission || !statusesWithInstruction[mission.status] || !mission.mission_instruction) {
                missionInstructionEl.hidden = true;
                setText(missionInstructionLabelEl, "Mission");
                setText(missionInstructionTextEl, "");
                return;
            }
            setText(missionInstructionLabelEl, mission.mission_instruction_label || "Mission");
            setText(missionInstructionTextEl, mission.mission_instruction);
            missionInstructionEl.hidden = false;
        }

        function renderTimerStatus(mission) {
            stopMissionCountdown();
            if (!mission || mission.status !== "mission_active") {
                if (missionTimerTrackEl) {
                    missionTimerTrackEl.hidden = true;
                    missionTimerTrackEl.classList.remove("is-complete");
                }
                setText(missionTimerEl, "");
                return;
            }
            const seconds = Number(mission.timer_seconds || 0);
            const startedAt = mission.started_at ? new Date(mission.started_at) : null;
            if (!seconds || !startedAt || Number.isNaN(startedAt.getTime())) {
                setTimerProgress(100);
                setText(missionTimerEl, "Game timer active.");
                return;
            }

            const endsAtMs = startedAt.getTime() + (seconds * 1000);
            const tick = function () {
                const remaining = Math.floor((endsAtMs - Date.now()) / 1000);
                if (remaining <= 0) {
                    setText(missionTimerEl, "Game timer: 00:00");
                    setTimerProgress(0);
                    setText(statusEl, "Game timer complete. Submit proof or request a new challenge.");
                    stopMissionCountdown();
                    scheduleMissionAutoRefresh(2500);
                    return;
                }
                setTimerProgress((remaining / seconds) * 100);
                setText(missionTimerEl, "Game timer: " + formatTimer(remaining));
            };
            tick();
            missionCountdownTimer = window.setInterval(tick, 1000);
        }

        function renderMissionStatus(mission) {
            if (!mission) {
                setText(statusEl, "No mission requested yet.");
                resetMissionControls();
                scheduleMissionDiscovery();
                return;
            }
            activeMissionId = mission.id;
            clearMissionDiscovery();
            const statusMessages = {
                requested: "Welcome to GGenre Secret Mission. Please wait while we find a suitable opponent...",
                matching: "Welcome to GGenre Secret Mission. Please wait while we find a suitable opponent...",
                opponent_proposed: mission.viewer_role === "opponent"
                    ? "You were matched for a Secret Mission. Waiting for the requesting player to confirm."
                    : "Opponent found. Accept this opponent or find another.",
                mission_proposed: "Your secret mission is ready.",
                mission_proposed_opponent: "A secret mission is being prepared. Wait for the requester to start, then chat naturally.",
                mission_active: "Mission started. Open your opponent chat and complete the mission before the timer ends.",
                proof_submitted: "Proof submitted. Admin will review it. You can keep chatting with this opponent from your inbox.",
                under_review: "Proof is under admin review.",
                approved: "Victory approved. Extra votes awarded. You can keep chatting with this opponent from your inbox.",
                rejected: "Proof not sufficient. Please upload better evidence.",
                cooldown_vote_required: "Before another challenge, please support your previous opponent winner.",
                closed: "Mission complete. You can request a new mission, and your opponent chat stays available from your inbox.",
            };
            const statusKey = mission.status === "mission_proposed" && mission.viewer_role === "opponent"
                ? "mission_proposed_opponent"
                : mission.status;
            setText(statusEl, statusMessages[statusKey] || ("Mission #" + mission.id + ": " + mission.status));
            resetMissionControls();
            if (requestMissionBtn) {
                const requestEnabledStatuses = {
                    approved: true,
                    rejected: true,
                    closed: true,
                };
                requestMissionBtn.disabled = !requestEnabledStatuses[mission.status];
                requestMissionBtn.textContent = requestEnabledStatuses[mission.status] ? "Request New Mission" : "Mission Requested";
                requestMissionBtn.hidden = mission.status === "mission_active";
            }
            if (mission.status === "opponent_proposed" && mission.viewer_role !== "opponent") {
                showMissionAction("find_another_opponent", false);
                showMissionAction("accept_opponent", false);
            } else if (mission.status === "mission_proposed" && mission.viewer_role !== "opponent") {
                showMissionAction(
                    "request_another_mission",
                    Number(mission.reroll_count || 0) >= Number(mission.max_rerolls || 0)
                );
                showMissionAction("accept_mission", false);
            } else if (mission.status === "mission_active") {
                showMissionAction("submit_proof", false);
                setVisible(missionActionRow, false);
                setVisible(proofRow, true);
            }
            renderOpponentSummary(mission);
            renderMissionInstruction(mission);
            renderTimerStatus(mission);
            renderMissionPopup(mission);
        }

        async function requestMission() {
            try {
                setText(statusEl, "Welcome to GGenre Secret Mission. Please wait while we find a suitable opponent...");
                const data = await postJson(missionRequestUrl, {});
                renderMissionStatus(data.mission);
            } catch (error) {
                setText(statusEl, missionActionErrorMessage(error));
            }
        }

        async function refreshMission(options) {
            const opts = options || {};
            const silent = Boolean(opts.silent);
            if (!activeMissionId) {
                refreshLatestMission({ silent: silent });
                return;
            }
            if (isRefreshingMission) {
                return;
            }
            try {
                isRefreshingMission = true;
                if (!silent) {
                    setText(statusEl, "Refreshing mission status...");
                }
                const data = await getJson(missionDetailUrl(missionDetailTemplate, activeMissionId));
                renderMissionStatus(data.mission);
            } catch (error) {
                setText(statusEl, error.message);
            } finally {
                isRefreshingMission = false;
            }
        }

        async function refreshLatestMission(options) {
            const opts = options || {};
            const silent = Boolean(opts.silent);
            if (!missionLatestUrl) {
                if (!silent) {
                    setText(statusEl, "No active mission to refresh.");
                }
                return;
            }
            try {
                if (!silent) {
                    setText(statusEl, "Checking for mission updates...");
                }
                const data = await getJson(missionLatestUrl);
                renderMissionStatus(data.mission);
            } catch (error) {
                if (!silent) {
                    setText(statusEl, error.message);
                }
            }
        }

        async function runMissionAction(action) {
            if (!activeMissionId) {
                setText(statusEl, "Create a mission first.");
                return;
            }
            try {
                setText(statusEl, "Updating mission...");
                const payload = { action: action };
                if (action === "submit_proof") {
                    const explanation = proofExplanation ? proofExplanation.value.trim() : "";
                    const formData = new FormData();
                    formData.append("action", "submit_proof");
                    formData.append("explanation", explanation);
                    if (proofImage && proofImage.files && proofImage.files[0]) {
                        formData.append("screenshot", proofImage.files[0]);
                    }
                    const uploadData = await postForm(missionActionUrl(activeMissionId), formData);
                    renderMissionStatus(uploadData.mission);
                    if (uploadData.message) {
                        setText(statusEl, uploadData.message);
                    }
                    if (proofImage) {
                        proofImage.value = "";
                    }
                    return;
                }
                const data = await postJson(missionActionUrl(activeMissionId), payload);
                renderMissionStatus(data.mission);
                if (data.message) {
                    setText(statusEl, data.message);
                }
            } catch (error) {
                setText(statusEl, missionActionErrorMessage(error));
            }
        }

        async function submitTokenRequest() {
            const requestedTokens = Number(tokenCount && tokenCount.value ? tokenCount.value : 0);
            if (!requestedTokens || requestedTokens < 1) {
                setText(tokenStatusEl, "Enter a valid token amount.");
                return;
            }
            try {
                setText(tokenStatusEl, "Submitting token request...");
                const data = await postJson(tokenRequestUrl, {
                    requested_tokens: requestedTokens,
                    payment_channel: tokenChannel ? tokenChannel.value.trim() : "",
                    payment_reference: tokenReference ? tokenReference.value.trim() : "",
                });
                setText(
                    tokenStatusEl,
                    "Token request #" + data.token_request.id + " submitted (" + data.token_request.status + ")."
                );
            } catch (error) {
                setText(tokenStatusEl, error.message);
            }
        }

        if (requestMissionBtn) {
            requestMissionBtn.addEventListener("click", requestMission);
        }
        if (refreshBtn) {
            refreshBtn.addEventListener("click", function () {
                refreshMission({ silent: false, source: "manual" });
            });
        }

        panel.querySelectorAll("[data-mission-action]").forEach(function (button) {
            button.addEventListener("click", function () {
                runMissionAction(button.getAttribute("data-mission-action"));
            });
        });

        if (tokenRequestBtn) {
            tokenRequestBtn.addEventListener("click", submitTokenRequest);
        }

        if (missionPopupCloseBtn) {
            missionPopupCloseBtn.addEventListener("click", function () {
                lastDismissedPopupKey = currentPopupKey;
                closeMissionPopup();
            });
        }

        if (missionPopupActionBtn) {
            missionPopupActionBtn.addEventListener("click", function () {
                if (!popupActionName) {
                    closeMissionPopup();
                    return;
                }
                if (popupActionName.indexOf("open_opponent_chat:") === 0) {
                    window.location.href = userChatUrl(popupActionName.split(":")[1]);
                    return;
                }
                runMissionAction(popupActionName);
            });
        }

        if (activeMissionId) {
            refreshMission({ silent: true, source: "bootstrap" });
        } else {
            resetMissionControls();
            showMatchmaking(false);
            scheduleMissionDiscovery();
            if (opponentCardEl) {
                opponentCardEl.hidden = true;
            }
        }

        window.addEventListener("ggenre:mission-updated", function (event) {
            const detail = event.detail || {};
            const missionId = Number(detail.mission_id || 0);
            if (activeMissionId && missionId && missionId !== activeMissionId) {
                return;
            }
            if (activeMissionId) {
                refreshMission({ silent: true, source: "realtime" });
            } else {
                refreshLatestMission({ silent: true });
            }
        });
    }

    function initAdminPanel(root) {
        const panel = root.querySelector("[data-admin-review-panel]");
        if (!panel) {
            return;
        }

        const missionIdInput = panel.querySelector("[data-review-mission-id]");
        const evidenceIdInput = panel.querySelector("[data-review-evidence-id]");
        const reviewNotesInput = panel.querySelector("[data-review-notes]");
        const missionStatusEl = panel.querySelector("[data-review-status]");
        const tokenRequestIdInput = panel.querySelector("[data-review-token-request-id]");
        const tokenCountInput = panel.querySelector("[data-review-token-count]");
        const tokenNotesInput = panel.querySelector("[data-review-token-notes]");
        const tokenStatusEl = panel.querySelector("[data-token-review-status]");

        panel.querySelectorAll("[data-review-action]").forEach(function (button) {
            button.addEventListener("click", async function () {
                const missionId = Number(missionIdInput && missionIdInput.value ? missionIdInput.value : 0);
                const evidenceId = Number(evidenceIdInput && evidenceIdInput.value ? evidenceIdInput.value : 0);
                if (!missionId || !evidenceId) {
                    setText(missionStatusEl, "Enter Mission ID and Evidence ID.");
                    return;
                }
                try {
                    setText(missionStatusEl, "Submitting mission review...");
                    const data = await postJson(missionActionUrl(missionId), {
                        action: button.getAttribute("data-review-action"),
                        evidence_id: evidenceId,
                        review_notes: reviewNotesInput ? reviewNotesInput.value.trim() : "",
                    });
                    setText(missionStatusEl, "Mission #" + data.mission.id + " updated: " + data.mission.status);
                } catch (error) {
                    setText(missionStatusEl, error.message);
                }
            });
        });

        panel.querySelectorAll("[data-token-review-action]").forEach(function (button) {
            button.addEventListener("click", async function () {
                const requestId = Number(tokenRequestIdInput && tokenRequestIdInput.value ? tokenRequestIdInput.value : 0);
                if (!requestId) {
                    setText(tokenStatusEl, "Enter Token Request ID.");
                    return;
                }
                try {
                    setText(tokenStatusEl, "Submitting token review...");
                    const data = await postJson(tokenReviewUrl(requestId), {
                        action: button.getAttribute("data-token-review-action"),
                        approved_tokens: Number(tokenCountInput && tokenCountInput.value ? tokenCountInput.value : 0),
                        review_notes: tokenNotesInput ? tokenNotesInput.value.trim() : "",
                    });
                    setText(tokenStatusEl, "Request #" + data.token_request.id + " updated: " + data.token_request.status);
                } catch (error) {
                    setText(tokenStatusEl, error.message);
                }
            });
        });
    }

    window.ggenreInitMissionPanels = function (root) {
        initPlayerPanel(root);
        initAdminPanel(root);
    };

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".chat-page, [data-chat-widget='admin-contact'], [data-chat-widget='mission-chat']").forEach(function (root) {
            window.ggenreInitMissionPanels(root);
        });
    });
})();
