(function () {
  "use strict";

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      document.cookie.split(";").forEach(function (cookie) {
        const trimmed = cookie.trim();
        if (trimmed.startsWith(name + "=")) {
          cookieValue = decodeURIComponent(trimmed.substring(name.length + 1));
        }
      });
    }
    return cookieValue;
  }

  const markButton = document.getElementById("mark-as-read");
  if (!markButton) {
    return;
  }

  markButton.addEventListener("click", function () {
    const markUrl = markButton.getAttribute("data-mark-url");
    if (!markUrl) {
      return;
    }

    fetch(markUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "Content-Type": "application/json",
      },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data.status === "success") {
          window.location.reload();
        }
      });
  });
})();
