(function () {
  "use strict";

  function updateSourceVisualState() {
    const fileInput = document.getElementById("id_file");
    const youtubeInput = document.getElementById("id_youtube_url");
    const filePanel = document.querySelector('[data-source-panel="file"]');
    const youtubePanel = document.querySelector('[data-source-panel="youtube"]');

    if (!fileInput || !youtubeInput || !filePanel || !youtubePanel) {
      return;
    }

    const hasFile = Boolean(fileInput.files && fileInput.files.length);
    const hasYoutube = Boolean((youtubeInput.value || "").trim());

    filePanel.classList.toggle("is-active", hasFile && !hasYoutube);
    youtubePanel.classList.toggle("is-active", hasYoutube && !hasFile);
  }

  function updateFileStatus(inputId, statusSelector, emptyText) {
    const input = document.getElementById(inputId);
    const status = document.querySelector(statusSelector);

    if (!input || !status) {
      return;
    }

    const hasFile = Boolean(input.files && input.files.length);
    const filePicker = input.closest(".upload-file-picker");
    status.textContent = hasFile ? "Selected: " + input.files[0].name : emptyText;
    status.classList.toggle("is-selected", hasFile);
    if (filePicker) {
      filePicker.classList.toggle("is-selected", hasFile);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const forms = document.querySelectorAll(".needs-validation");
    Array.prototype.slice.call(forms).forEach(function (form) {
      form.addEventListener(
        "submit",
        function (event) {
          if (!form.checkValidity()) {
            event.preventDefault();
            event.stopPropagation();
          }

          form.classList.add("was-validated");
        },
        false
      );
    });

    const fileInput = document.getElementById("id_file");
    const thumbnailInput = document.getElementById("id_thumbnail");
    const youtubeInput = document.getElementById("id_youtube_url");

    if (fileInput) {
      fileInput.addEventListener("change", function () {
        updateFileStatus("id_file", "[data-file-status]", "Select a file to upload.");
        updateSourceVisualState();
      });
    }

    if (thumbnailInput) {
      thumbnailInput.addEventListener("change", function () {
        updateFileStatus("id_thumbnail", "[data-thumb-status]", "No thumbnail selected.");
      });
    }

    if (youtubeInput) {
      youtubeInput.addEventListener("input", updateSourceVisualState);
    }

    updateFileStatus("id_file", "[data-file-status]", "Select a file to upload.");
    updateFileStatus("id_thumbnail", "[data-thumb-status]", "No thumbnail selected.");
    updateSourceVisualState();
  });
})();
