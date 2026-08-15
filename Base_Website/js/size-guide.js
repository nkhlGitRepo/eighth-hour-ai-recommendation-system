/**
 * size-guide.js
 * Expand/collapse for the size chart sections.
 *
 * The panels start closed and are `hidden` in the markup, so the page is usable
 * (and the tables reachable) even if this script never runs.
 */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".size-accordion-head").forEach((head) => {
    head.addEventListener("click", () => {
      const body = head.nextElementSibling;
      const open = head.getAttribute("aria-expanded") === "true";
      head.setAttribute("aria-expanded", String(!open));
      body.hidden = open;
    });
  });
});
