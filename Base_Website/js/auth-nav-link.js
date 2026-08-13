/**
 * auth-nav-link.js
 * Toggles the header's "Log In" link vs "My Account"/"Log Out" links based
 * on whether an account is logged in -- same convention as
 * recommendations-nav-link.js, shared by every page's header. Deliberately
 * has no top-level API_BASE-style constant (the one fetch call below uses
 * a literal URL) so it never collides with page-specific scripts that
 * already declare their own differently-scoped API base constant.
 */
document.addEventListener("DOMContentLoaded", () => {
  const loginLink = document.getElementById("loginLink");
  const accountLink = document.getElementById("accountLink");
  const logoutLink = document.getElementById("logoutLink");
  if (!loginLink || !accountLink || !logoutLink) return;

  const isAuthed = !!localStorage.getItem("authToken");
  loginLink.style.display = isAuthed ? "none" : "";
  accountLink.style.display = isAuthed ? "" : "none";
  logoutLink.style.display = isAuthed ? "" : "none";

  logoutLink.addEventListener("click", async (event) => {
    event.preventDefault();
    const token = localStorage.getItem("authToken");
    if (token) {
      try {
        await fetch("http://localhost:8000/auth/logout", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch (error) {
        // Best-effort server-side revocation -- still clear local state below.
      }
    }
    localStorage.removeItem("authToken");
    localStorage.removeItem("userId");
    localStorage.removeItem("currentSessionId");
    localStorage.removeItem("intakeSession");

    // Reuse the header's own logo link -- it already holds the correct
    // relative path to the homepage from wherever this page lives.
    const logoLink = document.querySelector("a.logo");
    window.location.href = logoLink ? logoLink.getAttribute("href") : "index.html";
  });
});
