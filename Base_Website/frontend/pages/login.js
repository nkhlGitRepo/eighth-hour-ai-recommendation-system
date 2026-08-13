/**
 * Login Page Controller
 */
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);
  const redirect = getValidRedirect(params.get("redirect"));

  if (params.get("justRegistered") === "true") {
    document.getElementById("registeredBanner").style.display = "";
  }

  // Preserve the redirect target across to the signup page's own switch link.
  if (redirect) {
    const signupLink = document.getElementById("signupSwitchLink");
    signupLink.href = `signup.html?redirect=${encodeURIComponent(redirect)}`;
  }

  const errorBox = document.getElementById("authError");
  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.classList.add("visible");
  };

  document.getElementById("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.remove("visible");

    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;

    try {
      await loginAccount(username, password);
      window.location.href = redirect ? redirect : "../../index.html";
    } catch (error) {
      showError(error.message || "Login failed. Please try again.");
    }
  });
});
