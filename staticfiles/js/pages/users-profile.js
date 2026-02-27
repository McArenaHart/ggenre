(function () {
  "use strict";

  function ensureImagePreview(container) {
    if (!container) {
      return null;
    }

    const existing = container.querySelector(".profile-preview");
    if (existing && existing.tagName === "IMG") {
      return existing;
    }

    const image = document.createElement("img");
    image.className = "rounded-circle gg-avatar profile-preview profile-avatar";
    image.width = 120;
    image.height = 120;
    image.alt = "Profile preview";

    if (existing) {
      existing.replaceWith(image);
    } else {
      container.appendChild(image);
    }

    return image;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const profilePictureInput = document.querySelector("input[name='profile_picture']");
    const avatarContainer = document.querySelector("[data-profile-avatar]");
    const fileStatus = document.querySelector("[data-profile-file-status]");

    if (!profilePictureInput) {
      return;
    }

    profilePictureInput.addEventListener("change", function () {
      const hasFile = Boolean(this.files && this.files[0]);
      const picker = this.closest(".profile-file-picker");

      if (picker) {
        picker.classList.toggle("is-selected", hasFile);
      }

      if (fileStatus) {
        fileStatus.textContent = hasFile ? "Selected: " + this.files[0].name : "No file selected.";
      }

      if (!hasFile) {
        return;
      }

      const previewImage = ensureImagePreview(avatarContainer);
      if (!previewImage) {
        return;
      }

      const reader = new FileReader();
      reader.onload = function (event) {
        previewImage.src = event.target.result;
      };
      reader.readAsDataURL(this.files[0]);
    });
  });
})();
