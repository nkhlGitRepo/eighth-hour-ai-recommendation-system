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
    return `
      <a href="product.html?slug=${product.slug}" class="product-link">
        <div class="product-image" style="background: linear-gradient(135deg, #f5f5f5 0%, #efefef 100%); border-radius: 8px; padding: 0.5rem;">
          <img src="${productImage(product.sku || product.slug, 0, product.name, 220, 280)}" alt="${product.name}" style="width: 100%; display: block;" />
        </div>
        <h3>${product.name}</h3>
        <p class="product-meta">${product.category}</p>
        <p class="product-price">$${product.price.toFixed(2)}</p>
      </a>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new HomeRecommendationsLoader();
});
