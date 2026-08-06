/**
 * Recommendations Page Controller
 * Displays personalized recommendations based on intake session
 */

const API_BASE = 'http://localhost:8000';

class RecommendationsPage {
  constructor() {
    this.sessionId = this.getSessionId();
    this.recommendations = [];
    this.sessionData = null;
    this.filteredRecommendations = [];

    if (this.sessionId) {
      this.init();
    } else {
      this.showError('No style profile found. Please complete the intake flow first.');
    }
  }

  getSessionId() {
    const params = new URLSearchParams(window.location.search);
    let sessionId = params.get('session');
    if (!sessionId) {
      sessionId = localStorage.getItem('currentSessionId');
    }
    return sessionId;
  }

  async init() {
    this.attachEventListeners();
    await this.loadSessionData();
    await this.loadRecommendations();
    this.displayProfile();
    this.displayRecommendations();
  }

  async loadSessionData() {
    try {
      // In a real app, we'd have a /session/{id} endpoint
      // For now, we'll store session data in localStorage after intake
      const saved = localStorage.getItem('intakeSession');
      if (saved) {
        this.sessionData = JSON.parse(saved);
      }
    } catch (error) {
      console.error('Failed to load session data:', error);
    }
  }

  async loadRecommendations() {
    try {
      const response = await fetch(`${API_BASE}/recommendations/${this.sessionId}?k=20`);
      if (!response.ok) throw new Error('Failed to load recommendations');
      const data = await response.json();
      this.recommendations = data.recommendations || [];
      this.filteredRecommendations = [...this.recommendations];
    } catch (error) {
      console.error('Recommendations error:', error);
      this.showError('Could not load recommendations. Please try again.');
    }
  }

  displayProfile() {
    const container = document.getElementById('profileSummary');
    if (!this.sessionData || !this.sessionData.shapeProfile) {
      container.innerHTML = '<p>Profile data not available</p>';
      return;
    }

    const profile = this.sessionData.shapeProfile;
    const measurements = this.sessionData.measurements || {};

    container.innerHTML = `
      <div class="profile-item">
        <div class="profile-label">Shape</div>
        <div class="profile-value">${(profile.shape_class || 'Unknown').toUpperCase()}</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Size</div>
        <div class="profile-value">
          ${profile.size_recommendations?.[0]?.size || 'M'}
        </div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Bust</div>
        <div class="profile-value">${measurements.bust || 'N/A'} cm</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Waist</div>
        <div class="profile-value">${measurements.waist || 'N/A'} cm</div>
      </div>
    `;
  }

  displayRecommendations() {
    const container = document.getElementById('recommendationsList');

    if (this.filteredRecommendations.length === 0) {
      container.innerHTML = '<p class="loading">No recommendations found. Please try different filters.</p>';
      return;
    }

    container.innerHTML = this.filteredRecommendations
      .map(rec => `
        <a href="../product.html?slug=${rec.slug}" class="product-card">
          <div class="product-card-image">
            <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='400'%3E%3Crect fill='%23f0f0f0' width='300' height='400'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='16' fill='%23999'%3E${rec.name}%3C/text%3E%3C/svg%3E" alt="${rec.name}" />
          </div>
          <div class="product-card-name">${rec.name}</div>
          <div class="product-card-category">${rec.category}</div>
          <div class="product-card-price">$${rec.price.toFixed(2)}</div>
          <div class="product-card-why">
            Perfect for your ${this.sessionData?.shapeProfile?.shape_class || 'body'} shape
          </div>
        </a>
      `)
      .join('');
  }

  attachEventListeners() {
    document.querySelectorAll('input[name="category"]').forEach(checkbox => {
      checkbox.addEventListener('change', () => this.applyFilters());
    });
  }

  applyFilters() {
    const selectedCategories = Array.from(
      document.querySelectorAll('input[name="category"]:checked')
    ).map(el => el.value);

    if (selectedCategories.length === 0) {
      this.filteredRecommendations = [...this.recommendations];
    } else {
      this.filteredRecommendations = this.recommendations.filter(rec =>
        selectedCategories.includes(rec.category)
      );
    }

    this.displayRecommendations();
  }

  showError(message) {
    const container = document.getElementById('recommendationsList');
    container.innerHTML = `<p style="grid-column: 1/-1; text-align: center; color: #d32f2f; padding: 2rem;">${message}</p>`;
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  new RecommendationsPage();
});
