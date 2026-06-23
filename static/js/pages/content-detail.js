(function () {
  "use strict";

  function getCsrfToken() {
    const tokenInput = document.querySelector("input[name='csrfmiddlewaretoken']");
    return tokenInput ? tokenInput.value : "";
  }

  function toggleDetailVoting(button) {
    const panel = button.closest(".watch-vote-panel");
    if (!panel) {
      return;
    }
    const isOpen = panel.classList.toggle("active");
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }

  async function submitDetailVote(button, contentId) {
    const voteValue = parseInt(button.dataset.value, 10);
    const voteUrl = button.dataset.url;
    const inputGroup = button.closest(".watch-vote-options")?.querySelector(".watch-vote-inputs");
    const tokensPaused = inputGroup?.dataset.tokensPaused === "true";
    const otpCode = (document.getElementById("otpCode_" + contentId)?.value || "").trim();
    const voterTag = (document.getElementById("voterTag_" + contentId)?.value || "").trim();
    const messageElem = document.getElementById("voteMessage_" + contentId);
    const voteOptions = button.closest(".watch-vote-options");
    const optionButtons = voteOptions ? Array.from(voteOptions.querySelectorAll("[data-vote-submit]")) : [button];

    if ((!tokensPaused && !otpCode) || !voterTag) {
      if (messageElem) {
        messageElem.style.display = "block";
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = tokensPaused ? "Voter tag is required." : "OTP and voter tag are required.";
      }
      return;
    }

    optionButtons.forEach((optionButton) => {
      optionButton.disabled = true;
    });

    try {
      const response = await fetch(voteUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          vote_value: voteValue,
          otp_code: otpCode,
          voter_tag: voterTag,
        }),
      });

      const data = await response.json();
      if (!messageElem) {
        return;
      }

      messageElem.style.display = "block";
      if (data.status === "success") {
        messageElem.className = "small mt-2 mb-0 text-success";
        messageElem.textContent = data.message;
        if (data.chat_url) {
          const chatLink = document.createElement("a");
          chatLink.href = data.chat_url;
          chatLink.className = "btn btn-sm btn-primary ml-2";
          chatLink.textContent = "Open chat";
          messageElem.appendChild(chatLink);

          if (data.inbox_url) {
            const inboxLink = document.createElement("a");
            inboxLink.href = data.inbox_url;
            inboxLink.className = "btn btn-sm btn-outline-primary ml-2";
            inboxLink.textContent = "Inbox";
            messageElem.appendChild(inboxLink);
          }
        } else {
          setTimeout(function () {
            window.location.reload();
          }, 1200);
        }
      } else {
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = data.message || "Vote failed.";
        optionButtons.forEach((optionButton) => {
          optionButton.disabled = false;
        });
      }
    } catch (error) {
      if (messageElem) {
        messageElem.style.display = "block";
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = "Network error while submitting vote.";
      }
      optionButtons.forEach((optionButton) => {
        optionButton.disabled = false;
      });
      console.error("Error submitting vote:", error);
    }
  }

  document.addEventListener("click", function (event) {
    const toggleButton = event.target.closest("[data-vote-toggle]");
    if (toggleButton) {
      event.preventDefault();
      toggleDetailVoting(toggleButton);
      return;
    }

    const submitButton = event.target.closest("[data-vote-submit]");
    if (submitButton) {
      event.preventDefault();
      submitDetailVote(submitButton, submitButton.dataset.contentId);
    }
  });

  window.toggleDetailVoting = toggleDetailVoting;
  window.submitDetailVote = submitDetailVote;
})();
