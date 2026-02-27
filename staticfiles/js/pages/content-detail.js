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
    panel.classList.toggle("active");
  }

  async function submitDetailVote(button, contentId) {
    const voteValue = parseInt(button.dataset.value, 10);
    const voteUrl = button.dataset.url;
    const otpCode = (document.getElementById("otpCode_" + contentId)?.value || "").trim();
    const voterTag = (document.getElementById("voterTag_" + contentId)?.value || "").trim();
    const messageElem = document.getElementById("voteMessage_" + contentId);

    if (!otpCode || !voterTag) {
      if (messageElem) {
        messageElem.style.display = "block";
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = "OTP and voter tag are required.";
      }
      return;
    }

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
        setTimeout(function () {
          window.location.reload();
        }, 1200);
      } else {
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = data.message || "Vote failed.";
      }
    } catch (error) {
      if (messageElem) {
        messageElem.style.display = "block";
        messageElem.className = "small mt-2 mb-0 text-danger";
        messageElem.textContent = "Network error while submitting vote.";
      }
      console.error("Error submitting vote:", error);
    }
  }

  window.toggleDetailVoting = toggleDetailVoting;
  window.submitDetailVote = submitDetailVote;
})();
