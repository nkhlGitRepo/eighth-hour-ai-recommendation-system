/**
 * style-profile-link.js
 * Sets the header's style-profile link to "My Style" (no completed profile
 * yet) or "Update Style" (profile already complete) -- shared by every
 * page's header, using the same completion signal recommendations-nav-
 * link.js already checks, so the two links can never disagree.
 */
document.addEventListener("DOMContentLoaded", () => {
  const link = document.querySelector(".style-profile-link");
  if (!link) return;

  let hasCompletedProfile = false;
  try {
    const saved = JSON.parse(localStorage.getItem("intakeSession") || "{}");
    hasCompletedProfile = !!saved.styleProfile;
  } catch (error) {
    // Corrupt localStorage -- treat as no completed profile rather than guess.
  }

  const basePath = link.getAttribute("href").split("?")[0];
  if (hasCompletedProfile) {
    link.textContent = "Update Style";
    link.setAttribute("href", `${basePath}?step=2`);
  } else {
    link.textContent = "My Style";
    link.setAttribute("href", basePath);
  }
});
