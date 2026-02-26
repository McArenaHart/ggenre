(function ($) {
  "use strict";

  const $window = $(window);

  $("body.fixed-nav .sidebar").on("mousewheel DOMMouseScroll wheel", function (e) {
    if ($window.width() <= 768) {
      return;
    }

    const original = e.originalEvent;
    const delta = original.wheelDelta || -original.detail;
    this.scrollTop += (delta < 0 ? 1 : -1) * 30;
    e.preventDefault();
  });

  const categoryCarousel = $(".owl-carousel-category");
  if (categoryCarousel.length) {
    categoryCarousel.owlCarousel({
      items: 8,
      lazyLoad: true,
      pagination: false,
      loop: true,
      autoPlay: 2000,
      navigation: true,
      stopOnHover: true,
      navigationText: ["<i class='fa fa-chevron-left'></i>", "<i class='fa fa-chevron-right'></i>"],
    });
  }

  const loginCarousel = $(".owl-carousel-login");
  if (loginCarousel.length) {
    loginCarousel.owlCarousel({
      items: 1,
      lazyLoad: true,
      pagination: true,
      autoPlay: 4000,
      loop: true,
      singleItem: true,
      navigation: false,
      stopOnHover: true,
    });
  }

  $('[data-toggle="tooltip"]').tooltip();

  function initSmartScrollButton() {
    const scrollButton = document.querySelector(".scroll-to-top");
    if (!scrollButton) {
      return;
    }

    const prefersReducedMotion =
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let lastScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
    let ticking = false;
    let idleTimer = null;

    function updateScrollButton() {
      const currentY = window.pageYOffset || document.documentElement.scrollTop || 0;
      const maxScroll = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
      const progress = Math.min(1, currentY / maxScroll);
      const progressDegrees = Math.round(progress * 360);
      const scrollingDown = currentY > lastScrollY + 2;
      const showThreshold = 260;
      const nearBottom = currentY > maxScroll - 160;
      const shouldShow = currentY > showThreshold && (!scrollingDown || nearBottom);

      scrollButton.style.setProperty("--scroll-progress", progressDegrees + "deg");
      scrollButton.classList.toggle("is-visible", shouldShow);
      scrollButton.classList.toggle("is-condensed", shouldShow && scrollingDown && !nearBottom);

      if (idleTimer) {
        window.clearTimeout(idleTimer);
      }

      if (shouldShow && !scrollingDown) {
        idleTimer = window.setTimeout(function () {
          scrollButton.classList.add("is-condensed");
        }, 1600);
      }

      lastScrollY = currentY;
      ticking = false;
    }

    function onScrollLikeEvent() {
      if (ticking) {
        return;
      }
      ticking = true;
      window.requestAnimationFrame(updateScrollButton);
    }

    scrollButton.addEventListener("click", function (event) {
      event.preventDefault();
      window.scrollTo({
        top: 0,
        behavior: prefersReducedMotion ? "auto" : "smooth",
      });
    });

    window.addEventListener("scroll", onScrollLikeEvent, { passive: true });
    window.addEventListener("resize", onScrollLikeEvent);
    updateScrollButton();
  }

  initSmartScrollButton();
})(jQuery);

function incrementViews(contentId) {
  const csrfTokenElement = document.querySelector('[name=csrfmiddlewaretoken]');
  const csrfToken = csrfTokenElement ? csrfTokenElement.value : null;

  if (!csrfToken || !contentId) {
    return;
  }

  fetch(`/content/increment-views/${contentId}/`, {
    method: "POST",
    headers: {
      "X-CSRFToken": csrfToken,
      "X-Requested-With": "XMLHttpRequest",
    },
    credentials: "same-origin",
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      const viewCountElement = document.querySelector(`.view-count[data-content-id="${contentId}"]`);
      if (viewCountElement && typeof data.new_viewers !== "undefined") {
        viewCountElement.textContent = data.new_viewers;
      }
    })
    .catch((error) => console.error("Error updating views:", error));
}

document.addEventListener("DOMContentLoaded", function () {
  function getInitials(name) {
    const base = (name || "").trim();
    if (!base) {
      return "U";
    }

    const parts = base.replace(/[_-]+/g, " ").split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    const cleaned = parts[0].replace(/[^a-zA-Z0-9]/g, "");
    return (cleaned.slice(0, 2) || "U").toUpperCase();
  }

  function buildAvatarMarkup(profileUrl, username) {
    const url = (profileUrl || "").trim();
    const lowerUrl = url.toLowerCase();
    const usesDefaultAvatar =
      !url ||
      lowerUrl.includes("/static/defaults/profile.png") ||
      lowerUrl.includes("/static/img/default-profile.png");

    if (usesDefaultAvatar) {
      return `<span class="rounded-circle gg-avatar-fallback mr-2" style="--gg-avatar-size: 30px;" role="img" aria-label="${username}">${getInitials(username)}</span>`;
    }

    return `<img src="${url}" alt="${username}" class="rounded-circle gg-avatar mr-2" width="30" height="30">`;
  }

  document.querySelectorAll(".add-comment-form").forEach((form) => {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();

      const formData = new FormData(form);
      const url = form.action;
      const commentSection = form.closest(".card-footer");
      const commentCountElement = commentSection ? commentSection.querySelector(".comment-count") : null;

      try {
        const response = await fetch(url, {
          method: "POST",
          body: formData,
          headers: {
            "X-CSRFToken": formData.get("csrfmiddlewaretoken"),
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        const data = await response.json();
        if (data.status !== "success" || !commentSection) {
          alert(data.message || "Unable to add comment.");
          return;
        }

        const newComment = document.createElement("div");
        newComment.classList.add("border", "rounded", "p-2", "mb-2", "bg-white", "d-flex", "align-items-center");
        newComment.innerHTML = `
          ${buildAvatarMarkup(data.comment.user_profile, data.comment.user)}
          <div>
            <p class="mb-0"><a href="/users/profile/${data.comment.user_id}/"><strong>${data.comment.user}</strong></a> - ${data.comment.timestamp}</p>
            <p class="mb-0">${data.comment.text}</p>
          </div>
        `;

        commentSection.insertBefore(newComment, form);
        if (commentCountElement) {
          commentCountElement.textContent = data.comment_count;
        }

        const textarea = form.querySelector('textarea[name="text"]');
        if (textarea) {
          textarea.value = "";
        }
      } catch (error) {
        console.error("Error adding comment:", error);
        alert("Failed to add comment. Please try again.");
      }
    });
  });

  document.querySelectorAll("video, audio").forEach((media) => {
    let hasIncremented = false;

    media.addEventListener("timeupdate", function () {
      if (hasIncremented || media.currentTime < 5) {
        return;
      }

      const card = media.closest(".card");
      const viewCountElement = card ? card.querySelector(".view-count") : null;
      const contentId = viewCountElement ? viewCountElement.getAttribute("data-content-id") : null;

      if (contentId) {
        incrementViews(contentId);
        hasIncremented = true;
      }
    });

    media.addEventListener("seeked", function () {
      if (media.currentTime < 5) {
        hasIncremented = false;
      }
    });
  });
});

window.togglePassword = function togglePassword(inputId) {
  const passwordInput = document.getElementById(inputId);
  if (!passwordInput) {
    return;
  }

  const icon = passwordInput.parentElement ? passwordInput.parentElement.querySelector("i") : null;
  const isPassword = passwordInput.type === "password";

  passwordInput.type = isPassword ? "text" : "password";

  if (icon) {
    icon.classList.toggle("fa-eye", !isPassword);
    icon.classList.toggle("fa-eye-slash", isPassword);
  }
};
