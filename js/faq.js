/**
 * faq.js
 * Holds the FAQ content (grouped by topic) and renders an accordion.
 * Content below is paraphrased in our own words, not copied from any site.
 */
const FAQ_GROUPS = [
  {
    topic: "Sizing",
    items: [
      { q: "What sizes do you offer?", a: "Sizes range from XXS to XXL across the collection. Check the size guide linked in the header for full measurements." },
      { q: "What if I'm between two sizes?", a: "We recommend checking the detailed measurements on the size guide first. If you're still unsure, our support team can help you pick." },
      { q: "Can I request custom measurements?", a: "Yes — select styles support custom sizing. Reach out to support with your measurements and the piece you're interested in." },
    ],
  },
  {
    topic: "Shipping",
    items: [
      { q: "How long does an order take to ship?", a: "Pieces are made to order, so please allow roughly two weeks for production before dispatch." },
      { q: "Do you ship internationally?", a: "Yes, we ship worldwide. Shipping costs are calculated at checkout based on destination and weight." },
      { q: "Who covers customs duties?", a: "Any customs duties or import taxes are the responsibility of the customer and are not included in the item price." },
    ],
  },
  {
    topic: "Orders & Returns",
    items: [
      { q: "Can I cancel my order?", a: "Orders can typically be cancelled within a short window after purchase — check your confirmation email for details." },
      { q: "What's your return policy?", a: "Because pieces are made to order, returns are accepted only in the case of an incorrect size, color, or item shipped." },
      { q: "Do you offer refunds for fit issues?", a: "Refunds aren't offered for personal fit preference — we encourage reviewing measurements carefully before ordering." },
    ],
  },
  {
    topic: "Payment & Offers",
    items: [
      { q: "Do you run sales or discounts?", a: "We don't run seasonal sales, in order to keep pricing fair and consistent for every customer and artisan involved." },
      { q: "Is there a discount for new customers?", a: "New subscribers to our newsletter receive a small welcome discount on their first order." },
    ],
  },
  {
    // Public retention/destruction policy for photo measurement. Linked
    // directly from the notice on the photo-upload screen, which is why this
    // group carries a stable anchor id.
    topic: "Photo & Measurement Data",
    id: "photo-measurement-data",
    items: [
      {
        q: "What happens to a photo I upload for measurement?",
        a: "It is used once, to estimate your measurements, and is then discarded. We do not save it to your account or our database, we never sell or share it for advertising, we never use it to identify you, and we never use it to train models. Only the resulting measurements are kept.",
      },
      {
        q: "Who processes my photo?",
        a: "In this demo the estimate is produced on our own server — your photo is not sent to any third party. If that ever changes, the notice on the upload screen will name the processor before you upload anything, because that notice is generated from the software actually in use rather than written by hand.",
      },
      {
        q: "How long do you keep my photo and measurements?",
        a: "The photo is not retained: it exists only for the few seconds needed to produce the estimate, and is released as soon as the request finishes. Your measurements are stored with your account so you don't have to re-enter them, and they are replaced whenever you retake your style profile.",
      },
      {
        q: "Do I have to use photo measurement?",
        a: "No. It is entirely optional — you can type your measurements in manually on the same step, and you can switch back to manual entry at any point. Photo upload also requires a separate, explicit confirmation before anything is sent.",
      },
      {
        q: "How accurate are photo-based measurements?",
        a: "In this demo build, photo measurement is not connected to a measurement service yet, so it does not analyse your photo at all \u2014 it fills in the same fixed sample values no matter what you upload (even an image that isn't a person). The upload screen says so before you upload, and the values are labelled as samples afterwards. Once a real measurement service is connected, results will be genuine automated estimates \u2014 still not a professional fitting, and still worth checking against a tape measure before buying.",
      },
      {
        q: "How do I withdraw consent or remove my measurements?",
        a: "Because the photo is never retained, there is nothing stored to delete. Your measurements can be replaced at any time by retaking your style profile from the My Style page.",
      },
    ],
  },
];

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("faqContainer");
  if (!container) return;

  container.innerHTML = FAQ_GROUPS.map((group) => `
    <div class="faq-group"${group.id ? ` id="${group.id}"` : ""}>
      <h2>${group.topic}</h2>
      ${group.items.map(faqItemHtml).join("")}
    </div>
  `).join("");

  container.querySelectorAll(".faq-item").forEach((item) => {
    item.querySelector(".faq-question").addEventListener("click", () => {
      item.classList.toggle("open");
    });
  });

  // The accordion renders after page load, so the browser has already given
  // up on any #hash in the URL by now. Deep links (e.g. the privacy notice on
  // the photo-upload screen pointing at #photo-measurement-data) need to be
  // resolved manually, with the group's answers opened so the policy is
  // actually readable on arrival rather than collapsed.
  const targetId = window.location.hash.slice(1);
  if (targetId) {
    const target = document.getElementById(targetId);
    if (target) {
      target.querySelectorAll(".faq-item").forEach((item) => item.classList.add("open"));
      // Opening the answers is the part that matters; scrolling is a nicety,
      // so don't let a missing/failing scrollIntoView break the accordion.
      if (typeof target.scrollIntoView === "function") {
        target.scrollIntoView();
      }
    }
  }
});

function faqItemHtml(item) {
  return `
    <div class="faq-item">
      <button class="faq-question">${item.q} <span>+</span></button>
      <div class="faq-answer">${item.a}</div>
    </div>`;
}
