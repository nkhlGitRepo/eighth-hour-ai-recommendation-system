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

  // The header shows a single person icon, as the storefront does. Logged out
  // it links straight to the login page; logged in it becomes a menu trigger
  // holding My Account and Log Out, so the icon never changes position.
  const trigger = document.getElementById("accountTrigger");
  const menu = document.querySelector(".account-menu");
  const isAuthed = !!localStorage.getItem("authToken");

  loginLink.style.display = isAuthed ? "none" : "";
  if (trigger) trigger.style.display = isAuthed ? "" : "none";

  if (trigger && menu) {
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = menu.classList.toggle("open");
      trigger.setAttribute("aria-expanded", String(open));
    });
    // Clicking anywhere else, or pressing Escape, closes it.
    document.addEventListener("click", () => {
      menu.classList.remove("open");
      trigger.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        menu.classList.remove("open");
        trigger.setAttribute("aria-expanded", "false");
      }
    });
    menu.querySelector(".account-dropdown")
      .addEventListener("click", (event) => event.stopPropagation());
  }

  logoutLink.addEventListener("click", async (event) => {
    event.preventDefault();
    const token = localStorage.getItem("authToken");
    if (token) {
      try {
        await fetch(`${window.EH_API_BASE}/auth/logout`, {
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
