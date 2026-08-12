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
    const loaded = await this.loadRecommendations();
    if (!loaded) return; // loadRecommendations already rendered its own error state
    this.displayProfile();
    this.displayRecommendations();
  }

  async loadSessionData() {
    try {
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
      console.log('Loading recommendations for session:', this.sessionId);

      // Get user_id from session data
      const userId = this.sessionData?.userId || localStorage.getItem('userId');
      const url = userId
        ? `${API_BASE}/recommendations/${this.sessionId}?k=20&user_id=${userId}`
        : `${API_BASE}/recommendations/${this.sessionId}?k=20`;

      const response = await fetch(url);

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        console.error('API Error:', response.status, errorBody);
        const err = new Error(errorBody.detail || `Request failed (${response.status})`);
        err.sessionMissing = response.status === 400 && /session .* not found/i.test(errorBody.detail || '');
        throw err;
      }

      const data = await response.json();
      console.log('API Response:', data);

      this.recommendations = data.recommendations || [];
      console.log('Loaded recommendations:', this.recommendations.length);

      this.filteredRecommendations = [...this.recommendations];
      return true;
    } catch (error) {
      console.error('Recommendations error:', error);

      if (error.sessionMissing) {
        // Stale state pointing at a session the backend no longer has
        // (e.g. dev database reset, or an old bookmark/tab). Clear
        // localStorage AND strip ?session=... from the URL -- getSessionId()
        // reads the URL param first, so leaving it in place meant reloading
        // this exact page kept re-requesting the same dead session_id no
        // matter what got cleared from localStorage.
        localStorage.removeItem('currentSessionId');
        localStorage.removeItem('intakeSession');
        if (new URLSearchParams(window.location.search).has('session')) {
          history.replaceState(null, '', window.location.pathname);
        }
        document.getElementById('recommendationsList').innerHTML = `
          <div style="grid-column: 1/-1; text-align: center; padding: 3rem 1rem;">
            <p style="color: #d32f2f; margin-bottom: 1rem;">⚠️ Your style profile session has expired</p>
            <p style="color: #666; margin-bottom: 1.5rem;">Please retake the style quiz to get fresh recommendations.</p>
            <a href="intake-flow.html" class="btn btn-primary" style="display: inline-block;">Complete Intake Flow</a>
          </div>
        `;
        return false;
      }

      document.getElementById('recommendationsList').innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 3rem 1rem;">
          <p style="color: #d32f2f; margin-bottom: 1rem;">⚠️ Could not load recommendations</p>
          <p style="color: #666; margin-bottom: 1.5rem;">Please try again in a moment.</p>
          <a href="intake-flow.html" class="btn btn-primary" style="display: inline-block;">Complete Intake Flow</a>
        </div>
      `;
      return false;
    }
  }

  displayProfile() {
    const container = document.getElementById('profileSummary');
    if (!this.sessionData || !this.sessionData.shapeProfile) {
      container.innerHTML = '<p style="font-size: 0.9rem; color: #999;">Complete intake flow to see profile</p>';
      return;
    }

    const profile = this.sessionData.shapeProfile;
    const measurements = this.sessionData.measurements || {};

    const sizesByCategory = profile.size_recommendation_by_category || {};
    const topsSize = sizesByCategory.tops || sizesByCategory.dresses || Object.values(sizesByCategory)[0] || 'M';
    const bottomsSize = sizesByCategory.skirts || sizesByCategory.trousers || topsSize;

    container.innerHTML = `
      <div class="profile-item">
        <div class="profile-label">Shape</div>
        <div class="profile-value" style="text-transform: capitalize;">${profile.shape_class || 'Unknown'}</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Tops Size</div>
        <div class="profile-value">${topsSize}</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Bottoms Size</div>
        <div class="profile-value">${bottomsSize}</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Bust</div>
        <div class="profile-value">${measurements.bust ? measurements.bust + ' cm' : 'N/A'}</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">Waist</div>
        <div class="profile-value">${measurements.waist ? measurements.waist + ' cm' : 'N/A'}</div>
      </div>
    `;
  }

  displayRecommendations() {
    const container = document.getElementById('recommendationsList');

    if (this.filteredRecommendations.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1/-1; padding: 3rem 1rem; text-align: center;">
          <h2 style="margin-top: 0; color: #333;">No Results Found</h2>
          <p style="color: #666; margin-bottom: 2rem;">
            No recommendations match your selected filters.
          </p>
          <button onclick="document.querySelectorAll('input[name=category]').forEach(cb => cb.checked = false); this.dispatchEvent(new Event('change'));" class="btn btn-secondary" style="display: inline-block; margin-bottom: 1rem;">Clear Filters</button>
        </div>
      `;
      return;
    }

    container.innerHTML = this.filteredRecommendations
      .map(rec => `
        <a href="../../product.html?slug=${rec.slug}" class="product-link">
          <div class="product-image" style="background: linear-gradient(135deg, #f5f5f5 0%, #efefef 100%); border-radius: 8px; padding: 0.5rem; margin-bottom: 1rem;">
            <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='280'%3E%3Crect fill='%23f0f0f0' width='220' height='280'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='12' fill='%23999'%3E${encodeURIComponent(rec.name)}%3C/text%3E%3C/svg%3E" alt="${rec.name}" style="width: 100%; display: block;" />
          </div>
          <h3 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">${rec.name}</h3>
          <p style="margin: 0 0 0.5rem 0; color: #666; font-size: 0.85rem;">${rec.category}</p>
          <p style="margin: 0 0 0.75rem 0; color: #333; font-weight: 600;">$${rec.price.toFixed(2)}</p>
          <p style="margin: 0; font-size: 0.85rem; color: #0066cc;">Perfect for your ${this.sessionData?.shapeProfile?.shape_class || 'body'} shape →</p>
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
    container.innerHTML = `
      <div style="grid-column: 1/-1; padding: 3rem 1rem; text-align: center;">
        <h2 style="margin-top: 0; color: #d32f2f;">⚠️ ${message}</h2>
        <p style="color: #666; margin-bottom: 2rem;">
          Let's get started with your personalized style profile.
        </p>
        <a href="intake-flow.html" class="btn btn-primary" style="display: inline-block;">Complete Intake Flow</a>
      </div>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new RecommendationsPage();
});
