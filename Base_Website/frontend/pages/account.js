/**
 * Account Page Controller
 */
document.addEventListener("DOMContentLoaded", async () => {
  if (!isAuthenticated()) {
    window.location.href = "login.html?redirect=account.html";
    return;
  }

  const token = localStorage.getItem("authToken");
  const headers = { Authorization: `Bearer ${token}` };

  await loadIdentity(headers);
  await loadProfile(headers);
  attachActionHandlers(headers);
});

async function loadIdentity(headers) {
  const identityBox = document.getElementById("accountIdentity");
  try {
    const response = await fetch(`${AUTH_API_BASE}/auth/me`, { headers });
    if (!response.ok) throw new Error("session expired");
    const me = await response.json();
    identityBox.textContent = `Logged in as ${me.username} (${me.email})`;
  } catch (error) {
    // Token is invalid/expired -- send back to login rather than show a broken page.
    window.location.href = "login.html?redirect=account.html";
  }
}

async function loadProfile(headers) {
  const container = document.getElementById("profileSection");
  try {
    const response = await fetch(`${AUTH_API_BASE}/account/profile`, { headers });
    if (!response.ok) throw new Error("failed to load profile");
    const profile = await response.json();

    if (!profile) {
      container.innerHTML = `
        <p>You haven't completed your style profile yet.</p>
        <a href="intake-flow.html" class="btn">Start My Style Profile</a>
      `;
      return;
    }

    const sizesByCategory = profile.shape_profile?.size_recommendation_by_category || {};
    const topsSize = sizesByCategory.tops || sizesByCategory.dresses || Object.values(sizesByCategory)[0] || "N/A";
    const bottomsSize = sizesByCategory.skirts || sizesByCategory.trousers || topsSize;
    const shapeClass = profile.shape_profile?.shape_class || "Unknown";
    const colors = (profile.style_profile?.preferred_colors || []).join(", ") || "None selected";

    container.innerHTML = `
      <div class="profile-summary-card">
        <p><strong>Shape:</strong> ${escapeHtml(shapeClass)}</p>
        <p><strong>Tops Size:</strong> ${escapeHtml(String(topsSize))}</p>
        <p><strong>Bottoms Size:</strong> ${escapeHtml(String(bottomsSize))}</p>
        <p><strong>Preferred Colors:</strong> ${escapeHtml(colors)}</p>
      </div>
      <p style="margin-top: 1rem;">
        <a href="intake-flow.html?step=2">Update Style</a> &middot;
        <a href="recommendations.html">View Recommendations</a>
      </p>
    `;
  } catch (error) {
    container.innerHTML = "<p>Could not load your style profile right now.</p>";
  }
}

function attachActionHandlers(headers) {
  document.getElementById("logoutButton").addEventListener("click", async () => {
    await logoutAccount();
    window.location.href = "../../index.html";
  });

  document.getElementById("logoutAllButton").addEventListener("click", async () => {
    await logoutAllDevices();
    window.location.href = "../../index.html";
  });

  const errorBox = document.getElementById("changePasswordError");
  const successBox = document.getElementById("changePasswordSuccess");

  document.getElementById("changePasswordForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.remove("visible");
    successBox.style.display = "none";

    const currentPassword = document.getElementById("currentPassword").value;
    const newPassword = document.getElementById("newPassword").value;
    const confirmNewPassword = document.getElementById("confirmNewPassword").value;

    if (newPassword !== confirmNewPassword) {
      errorBox.textContent = "New passwords do not match.";
      errorBox.classList.add("visible");
      return;
    }

    try {
      const response = await fetch(`${AUTH_API_BASE}/auth/change-password`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Failed to change password");

      successBox.style.display = "";
      document.getElementById("changePasswordForm").reset();
    } catch (error) {
      errorBox.textContent = error.message || "Failed to change password.";
      errorBox.classList.add("visible");
    }
  });
}
