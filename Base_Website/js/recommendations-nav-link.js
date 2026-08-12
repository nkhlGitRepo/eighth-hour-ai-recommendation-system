/**
 * recommendations-nav-link.js
 * Shows the "My Recommendations" header link only once the customer has
 * completed their style profile (so there are recommendations to return
 * to) -- shared by every page's header, since intake-flow.js is the only
 * script that knows the profile's actual completion state.
 */
document.addEventListener("DOMContentLoaded", () => {
  const link = document.getElementById("myRecommendationsLink");
  if (!link) return;

  const sessionId = localStorage.getItem("currentSessionId");
  if (!sessionId) return;

  try {
    const saved = JSON.parse(localStorage.getItem("intakeSession") || "{}");
    if (saved.styleProfile) {
      link.style.display = "";
    }
  } catch (error) {
    // Corrupt localStorage -- leave the link hidden rather than guess.
  }
});
