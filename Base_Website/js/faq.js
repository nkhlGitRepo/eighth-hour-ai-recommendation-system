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
];

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("faqContainer");
  if (!container) return;

  container.innerHTML = FAQ_GROUPS.map((group) => `
    <div class="faq-group">
      <h2>${group.topic}</h2>
      ${group.items.map(faqItemHtml).join("")}
    </div>
  `).join("");

  container.querySelectorAll(".faq-item").forEach((item) => {
    item.querySelector(".faq-question").addEventListener("click", () => {
      item.classList.toggle("open");
    });
  });
});

function faqItemHtml(item) {
  return `
    <div class="faq-item">
      <button class="faq-question">${item.q} <span>+</span></button>
      <div class="faq-answer">${item.a}</div>
    </div>`;
}
