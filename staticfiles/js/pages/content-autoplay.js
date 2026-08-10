(function () {
  "use strict";

  const AUTOPLAY_STORAGE_KEY = "ggenre-autoplay-enabled";
  const QUEUE_STORAGE_KEY = "ggenre-content-queue";

  class ContentAutoplay {
    constructor() {
      this.autoplayEnabled = this.readAutoplayPreference();
      this.queue = [];
      this.currentIndex = -1;
      this.init();
    }

    init() {
      this.setupAutoplayToggle();
      this.buildQueue();
      this.observeVideoEnd();
      this.syncAutoplayUI();
    }

    readAutoplayPreference() {
      try {
        const stored = window.localStorage.getItem(AUTOPLAY_STORAGE_KEY);
        return stored === "true" ? true : false;
      } catch (error) {
        return false;
      }
    }

    saveAutoplayPreference(enabled) {
      try {
        window.localStorage.setItem(AUTOPLAY_STORAGE_KEY, enabled ? "true" : "false");
      } catch (error) {
        // Ignore storage errors
      }
    }

    setupAutoplayToggle() {
      const toggleButton = document.querySelector("[data-autoplay-toggle]");
      if (!toggleButton) return;

      toggleButton.addEventListener("click", () => {
        this.autoplayEnabled = !this.autoplayEnabled;
        this.saveAutoplayPreference(this.autoplayEnabled);
        this.syncAutoplayUI();
      });
    }

    syncAutoplayUI() {
      const toggleButton = document.querySelector("[data-autoplay-toggle]");
      if (!toggleButton) return;

      const statusIndicator = toggleButton.querySelector("[data-autoplay-status]");
      const icon = toggleButton.querySelector("i");

      toggleButton.classList.toggle("autoplay-enabled", this.autoplayEnabled);
      toggleButton.setAttribute("aria-pressed", this.autoplayEnabled ? "true" : "false");

      if (statusIndicator) {
        statusIndicator.textContent = this.autoplayEnabled ? "On" : "Off";
      }

      if (icon) {
        icon.classList.toggle("fa-toggle-on", this.autoplayEnabled);
        icon.classList.toggle("fa-toggle-off", !this.autoplayEnabled);
      }
    }

    buildQueue() {
      // Get all up-next content items in order
      const upNextCards = document.querySelectorAll("[data-up-next-content-id]");
      this.queue = Array.from(upNextCards).map((card) => ({
        id: card.getAttribute("data-up-next-content-id"),
        url: card.getAttribute("href"),
        title: card.querySelector("h6")?.textContent || "Unknown",
      }));
    }

    observeVideoEnd() {
      // Check if page has video element
      const video = document.querySelector(".watch-player video");
      const iframe = document.querySelector(".watch-player iframe");

      if (video) {
        video.addEventListener("ended", () => {
          if (this.autoplayEnabled && this.queue.length > 0) {
            this.showAutoplayCountdown();
          }
        });
      }

      // For YouTube iframes, we need a different approach
      if (iframe && iframe.src.includes("youtube")) {
        this.setupYouTubeListener();
      }
    }

    setupYouTubeListener() {
      // Load YouTube API if not already loaded
      if (window.YT === undefined) {
        const tag = document.createElement("script");
        tag.src = "https://www.youtube.com/iframe_api";
        document.head.appendChild(tag);
      }

      window.onYouTubeIframeAPIReady = () => {
        const iframe = document.querySelector(".watch-player iframe");
        if (iframe) {
          const player = new YT.Player(iframe, {
            events: {
              onStateChange: (event) => {
                // State 0 = ended
                if (event.data === 0 && this.autoplayEnabled && this.queue.length > 0) {
                  this.showAutoplayCountdown();
                }
              },
            },
          });
        }
      };
    }

    showAutoplayCountdown() {
      if (this.queue.length === 0) return;

      const countdown = document.querySelector("[data-autoplay-countdown]");
      if (!countdown) {
        this.createCountdownUI();
      }

      const countdownContainer = document.querySelector("[data-autoplay-countdown]");
      const nextContent = this.queue[0];

      if (countdownContainer) {
        countdownContainer.style.display = "block";
        const titleEl = countdownContainer.querySelector("[data-next-title]");
        const countEl = countdownContainer.querySelector("[data-countdown-time]");

        if (titleEl) titleEl.textContent = nextContent.title;

        let seconds = 5;
        countEl.textContent = seconds;

        const interval = setInterval(() => {
          seconds--;
          countEl.textContent = seconds;

          if (seconds <= 0) {
            clearInterval(interval);
            window.location.href = nextContent.url;
          }
        }, 1000);

        // Cancel button
        const cancelBtn = countdownContainer.querySelector("[data-cancel-autoplay]");
        if (cancelBtn) {
          cancelBtn.addEventListener("click", () => {
            clearInterval(interval);
            countdownContainer.style.display = "none";
          });
        }
      }
    }

    createCountdownUI() {
      const player = document.querySelector(".watch-player");
      if (!player) return;

      const countdown = document.createElement("div");
      countdown.setAttribute("data-autoplay-countdown", "");
      countdown.className = "watch-autoplay-countdown";
      countdown.innerHTML = `
        <div class="countdown-card">
          <h5>Up Next</h5>
          <p class="countdown-title" data-next-title></p>
          <div class="countdown-timer">
            <span data-countdown-time>5</span>s
          </div>
          <button type="button" class="btn btn-sm btn-outline-light" data-cancel-autoplay>
            Cancel
          </button>
        </div>
      `;
      countdown.style.display = "none";
      player.appendChild(countdown);
    }

    playNext() {
      if (this.queue.length > 0) {
        const nextContent = this.queue[0];
        window.location.href = nextContent.url;
      }
    }
  }

  // Initialize on DOM ready
  document.addEventListener("DOMContentLoaded", () => {
    window.contentAutoplay = new ContentAutoplay();
  });

  // Expose play next function globally for button clicks
  window.playNextContent = function () {
    if (window.contentAutoplay) {
      window.contentAutoplay.playNext();
    }
  };
})();
