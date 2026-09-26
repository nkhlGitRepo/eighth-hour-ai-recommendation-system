/**
 * Home Page Recommendations Loader
 * Shows personalized recommendations if user has completed intake
 */

const API_BASE = 'http://localhost:8000';

class HomeRecommendationsLoader {
  constructor() {
    this.sessionId = localStorage.getItem('currentSessionId');
    if (this.sessionId) {
      this.loadAndDisplay();
    }
  }

  async loadAndDisplay() {
    try {
      const response = await fetch(`${API_BASE}/recommendations/${this.sessionId}?k=6`);
      if (!response.ok) return;

      const data = await response.json();
      const recommendations = data.recommendations || [];

      if (recommendations.length > 0) {
        this.displayRecommendations(recommendations);
      }
    } catch (error) {
      console.error('Failed to load recommendations:', error);
    }
  }

  displayRecommendations(recommendations) {
    const section = document.getElementById('recommendedSection');
    const grid = document.getElementById('recommendedGrid');

    if (!section || !grid) return;

    // Build product cards
    grid.innerHTML = recommendations
      .map(product => this.buildProductCard(product))
      .join('');

    // Show section
    section.style.display = 'block';
  }

  buildProductCard(product) {
    // Uses the storefront's own .product-card, so a recommended item on the
    // homepage is visually identical to any other product. The grey gradient
    // wrapper this replaced was a stand-in from before the catalog had
    // photography, and it stayed sitting behind the real image once one existed.
    const slug = product.slug || product.sku;
    return `
      <a href="product.html?slug=${slug}" class="product-card">
        <div class="thumb">
          <img src="${productImage(slug, 0, product.name, 450, 600)}" alt="${product.name}" loading="lazy" />
        </div>
        <div class="name">${product.name}</div>
        <div class="price">$${product.price.toFixed(2)}</div>
      </a>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new HomeRecommendationsLoader();
});
