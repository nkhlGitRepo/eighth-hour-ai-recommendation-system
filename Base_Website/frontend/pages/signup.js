/**
 * Signup Page Controller
 */
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);
  const redirect = getValidRedirect(params.get("redirect"));
  const message = params.get("message");

  if (message) {
    document.getElementById("authSubtitle").textContent = message;
  }

  // Preserve the redirect target across to the login page's own switch link.
  if (redirect) {
    const loginLink = document.getElementById("loginSwitchLink");
    loginLink.href = `login.html?redirect=${encodeURIComponent(redirect)}`;
  }

  const errorBox = document.getElementById("authError");
  const showError = (text) => {
    errorBox.textContent = text;
    errorBox.classList.add("visible");
  };

  document.getElementById("signupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.remove("visible");

    const username = document.getElementById("username").value.trim();
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    const confirmPassword = document.getElementById("confirmPassword").value;

    if (password !== confirmPassword) {
      showError("Passwords do not match.");
      return;
    }

    try {
      await registerAccount(username, email, password);
      // Registration only creates the account -- the decided flow logs
      // the user in explicitly afterward, it never auto-authenticates here.
      const params = new URLSearchParams({ justRegistered: "true" });
      if (redirect) params.set("redirect", redirect);
      window.location.href = `login.html?${params.toString()}`;
    } catch (error) {
      showError(error.message || "Registration failed. Please try again.");
    }
  });
});
