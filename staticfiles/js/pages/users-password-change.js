(function () {
  "use strict";

  const root = document.querySelector(".users-password-change-page");
  if (!root) {
    return;
  }

  root.querySelectorAll("input").forEach(function (input) {
    if (!input.classList.contains("form-control")) {
      input.classList.add("form-control");
    }
  });

  root.querySelectorAll(".password-toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      const targetId = button.getAttribute("data-target");
      const passwordInput = document.getElementById(targetId);
      const icon = button.querySelector("i");

      if (!passwordInput) {
        return;
      }

      const isPassword = passwordInput.type === "password";
      passwordInput.type = isPassword ? "text" : "password";

      if (icon) {
        icon.classList.toggle("fa-eye", !isPassword);
        icon.classList.toggle("fa-eye-slash", isPassword);
      }
    });
  });

  const newPasswordInput = document.getElementById("id_new_password1") || root.querySelector("input[name='new_password1']");
  const confirmPasswordInput = document.getElementById("id_new_password2") || root.querySelector("input[name='new_password2']");
  const strengthBar = document.getElementById("passwordStrength");
  const matchMessage = document.getElementById("passwordMatchMessage");

  if (newPasswordInput && strengthBar) {
    newPasswordInput.addEventListener("input", function () {
      const password = newPasswordInput.value || "";
      strengthBar.className = "";

      if (!password.length) {
        strengthBar.style.width = "0";
        return;
      }

      if (password.length < 6) {
        strengthBar.classList.add("strength-weak");
      } else if (password.length < 10) {
        strengthBar.classList.add("strength-medium");
      } else {
        strengthBar.classList.add("strength-strong");
      }
    });
  }

  if (confirmPasswordInput && newPasswordInput && matchMessage) {
    confirmPasswordInput.addEventListener("input", function () {
      if (!confirmPasswordInput.value.length) {
        matchMessage.textContent = "";
        matchMessage.classList.remove("text-success", "text-danger");
        return;
      }

      if (confirmPasswordInput.value !== newPasswordInput.value) {
        matchMessage.textContent = "Passwords do not match";
        matchMessage.classList.remove("text-success");
        matchMessage.classList.add("text-danger");
      } else {
        matchMessage.textContent = "Passwords match";
        matchMessage.classList.remove("text-danger");
        matchMessage.classList.add("text-success");
      }
    });
  }
})();
