/**
 * auth.js
 * Shared account utilities: register/login/logout, escaping, and the
 * open-redirect guard for the `?redirect=` param used when the style quiz
 * sends a logged-out visitor to sign up. Named AUTH_API_BASE (not the
 * generic API_BASE some pages already declare, e.g. intake-flow.js) so
 * this file can be loaded alongside those without a redeclaration error.
 *
 * Loaded on: login.html, signup.html, account.html, intake-flow.html.
 */

const AUTH_API_BASE = window.EH_API_BASE;

// Only known, in-app pages are ever legitimate `?redirect=` targets --
// never navigate to the raw query param value itself (open-redirect guard).
const AUTH_VALID_REDIRECT_TARGETS = ["intake-flow.html", "account.html"];

function isAuthenticated() {
  return !!localStorage.getItem("authToken");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function getValidRedirect(param) {
  return AUTH_VALID_REDIRECT_TARGETS.includes(param) ? param : null;
}

async function registerAccount(username, email, password) {
  const response = await fetch(`${AUTH_API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Registration failed");
  return body;
}

async function loginAccount(username, password) {
  const response = await fetch(`${AUTH_API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Login failed");

  // Reuses the existing "userId" localStorage key so every existing
  // reader (e.g. fit-checker-widget.js) keeps working unchanged.
  localStorage.setItem("authToken", body.token);
  localStorage.setItem("userId", body.user_id);

  await hydrateProfileAfterLogin();
  return body;
}

/**
 * After login, pull the account's saved style profile (if any) into the
 * same localStorage shape intake-flow.js's saveSessionState() already
 * produces, so recommendations.html/new-releases.html/the nav link
 * immediately reflect the restored account with zero changes to those
 * files. Best-effort: login itself has already succeeded regardless of
 * whether this completes.
 */
async function hydrateProfileAfterLogin() {
  const token = localStorage.getItem("authToken");
  if (!token) return;

  try {
    const response = await fetch(`${AUTH_API_BASE}/account/profile`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return;

    const profile = await response.json();
    if (!profile) return;

    localStorage.setItem("currentSessionId", profile.session_id);
    localStorage.setItem(
      "intakeSession",
      JSON.stringify({
        userId: localStorage.getItem("userId"),
        sessionId: profile.session_id,
        step: 5,
        measurements: profile.measurements || {},
        shapeProfile: profile.shape_profile,
        styleProfile: profile.style_profile,
        recommendations: [],
      })
    );
  } catch (error) {
    // Best-effort hydration only.
  }
}

async function logoutAccount() {
  const token = localStorage.getItem("authToken");
  if (token) {
    try {
      await fetch(`${AUTH_API_BASE}/auth/logout`, {
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
}

async function logoutAllDevices() {
  const token = localStorage.getItem("authToken");
  if (token) {
    try {
      await fetch(`${AUTH_API_BASE}/auth/logout-all`, {
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
}
