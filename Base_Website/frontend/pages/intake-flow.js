/**
 * Intake Flow Controller
 * Orchestrates the multi-step intake process with backend API calls
 */

const API_BASE = 'http://localhost:8000';

class IntakeFlow {
  constructor() {
    this.currentStep = 1;
    this.sessionId = null;
    this.userId = this.generateUserId();
    this.measurements = {};
    this.shapeProfile = null;
    this.styleProfile = null;
    this.recommendations = [];

    this.init();
  }

  init() {
    this.attachEventListeners();
    this.restoreSession();
    this.loadAvailableColors();
  }

  generateUserId() {
    let userId = localStorage.getItem('userId');
    if (!userId) {
      userId = `user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      localStorage.setItem('userId', userId);
    }
    return userId;
  }

  async loadAvailableColors() {
    try {
      const response = await fetch(`${API_BASE}/catalog/stats`);
      if (!response.ok) return;

      const stats = await response.json();
      const availableColors = stats.colors || [];

      if (availableColors.length > 0) {
        const colorContainer = document.querySelector('.color-options');
        if (colorContainer) {
          colorContainer.innerHTML = availableColors
            .map(color => `
              <label class="option-label">
                <input type="checkbox" name="color" value="${color}" />
                <span>${color}</span>
              </label>
            `)
            .join('');
        }
      }
    } catch (error) {
      console.warn('Could not load available colors:', error);
    }
  }

  restoreSession() {
    const savedSession = localStorage.getItem('intakeSession');
    if (savedSession) {
      try {
        const session = JSON.parse(savedSession);
        this.userId = session.userId || this.userId;
        this.sessionId = session.sessionId;
        this.measurements = session.measurements || {};
        this.shapeProfile = session.shapeProfile;
        this.styleProfile = session.styleProfile;
        this.recommendations = session.recommendations || [];
        if (session.step) {
          this.goToStep(session.step);
        }
      } catch (error) {
        console.warn('Failed to restore session:', error);
      }
    }
  }

  saveSessionState() {
    localStorage.setItem('intakeSession', JSON.stringify({
      userId: this.userId,
      sessionId: this.sessionId,
      step: this.currentStep,
      measurements: this.measurements,
      shapeProfile: this.shapeProfile,
      styleProfile: this.styleProfile,
      recommendations: this.recommendations,
    }));
  }

  attachEventListeners() {
    // Start fresh link
    const startFreshLink = document.getElementById('startFreshLink');
    if (startFreshLink) {
      startFreshLink.addEventListener('click', (e) => {
        e.preventDefault();
        if (confirm('This will clear all saved progress and start a new style profile. Continue?')) {
          this.clearSession();
          location.reload();
        }
      });
    }

    // Consent screen
    const photoConsent = document.getElementById('photoConsent');
    const measurementConsent = document.getElementById('measurementConsent');
    photoConsent?.addEventListener('change', () => this.updateConsentButton());
    measurementConsent?.addEventListener('change', () => this.updateConsentButton());
    document.getElementById('consentNext')?.addEventListener('click', () => this.handleConsent());
    document.getElementById('consentSkip')?.addEventListener('click', () => {
      if (this.sessionId) {
        this.goToStep(2);
      } else {
        alert('Please accept consent to continue.');
      }
    });

    // Measurements screen
    ['bust', 'waist', 'hips', 'height'].forEach(field => {
      document.getElementById(field)?.addEventListener('change', () => this.updateMeasurementButton());
    });
    document.getElementById('measurementsPrev')?.addEventListener('click', () => this.goToStep(1));
    document.getElementById('measurementsNext')?.addEventListener('click', () => this.handleMeasurements());
    document.getElementById('photoCapture')?.addEventListener('click', (e) => {
      e.preventDefault();
      alert('Photo measurement integration coming soon. Please enter measurements manually.');
    });

    // Profile screen
    document.getElementById('profilePrev')?.addEventListener('click', () => this.goToStep(2));
    document.getElementById('profileNext')?.addEventListener('click', () => this.goToStep(4));

    // Preferences screen
    document.getElementById('preferencesPrev')?.addEventListener('click', () => this.goToStep(3));
    document.getElementById('preferencesNext')?.addEventListener('click', () => this.handlePreferences());

    // Complete screen
    document.getElementById('completePrev')?.addEventListener('click', () => this.goToStep(4));
    document.getElementById('viewRecommendations')?.addEventListener('click', () => this.viewRecommendations());
    document.getElementById('continueShopping')?.addEventListener('click', () => this.continueShopping());
  }

  clearSession() {
    localStorage.removeItem('intakeSession');
    localStorage.removeItem('currentSessionId');
    this.sessionId = null;
    this.measurements = {};
    this.shapeProfile = null;
    this.styleProfile = null;
    this.recommendations = [];
  }

  updateConsentButton() {
    const photoConsent = document.getElementById('photoConsent').checked;
    const measurementConsent = document.getElementById('measurementConsent').checked;
    document.getElementById('consentNext').disabled = !(photoConsent && measurementConsent);
  }

  updateMeasurementButton() {
    const bust = document.getElementById('bust').value;
    const waist = document.getElementById('waist').value;
    const hips = document.getElementById('hips').value;
    const height = document.getElementById('height').value;
    document.getElementById('measurementsNext').disabled = !(bust && waist && hips && height);
  }

  async handleConsent() {
    try {
      const photoConsent = document.getElementById('photoConsent').checked;
      const measurementConsent = document.getElementById('measurementConsent').checked;

      const sessionResponse = await fetch(`${API_BASE}/intake/session?user_id=${this.userId}`, {
        method: 'POST',
      });

      if (!sessionResponse.ok) throw new Error(`Failed to create session: ${sessionResponse.status}`);
      const session = await sessionResponse.json();
      this.sessionId = session.session_id;
      this.userId = session.user_id;

      const consentResponse = await fetch(`${API_BASE}/intake/consent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.sessionId,
          photo_consent: photoConsent,
          measurement_consent: measurementConsent,
        }),
      });

      if (!consentResponse.ok) {
        const errorText = await consentResponse.text();
        throw new Error(`Failed to record consent: ${consentResponse.status}`);
      }

      await fetch(`${API_BASE}/consent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: this.userId,
          photo_consent: photoConsent,
          measurement_consent: measurementConsent,
        }),
      });

      this.saveSessionState();
      this.goToStep(2);
    } catch (error) {
      console.error('Consent error:', error);
      alert('Error recording consent: ' + error.message);
    }
  }

  async handleMeasurements() {
    try {
      const bust = parseFloat(document.getElementById('bust').value);
      const waist = parseFloat(document.getElementById('waist').value);
      const hips = parseFloat(document.getElementById('hips').value);
      const height = parseFloat(document.getElementById('height').value);

      if (isNaN(bust) || isNaN(waist) || isNaN(hips) || isNaN(height)) {
        throw new Error('Invalid measurement values - please enter numbers');
      }

      this.measurements = { bust, waist, hips, height };

      const response = await fetch(`${API_BASE}/intake/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.sessionId,
          manual_overrides: this.measurements,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server error (${response.status})`);
      }

      const data = await response.json();
      this.shapeProfile = data.shape_profile;

      this.saveSessionState();
      this.goToStep(3);
    } catch (error) {
      console.error('Measurements error:', error);
      alert('Error processing measurements: ' + error.message);
    }
  }

  async handlePreferences() {
    try {
      let colors = Array.from(document.querySelectorAll('input[name="color"]:checked')).map(el => el.value);
      const silhouettes = Array.from(document.querySelectorAll('input[name="silhouette"]:checked')).map(el => el.value);
      const occasions = Array.from(document.querySelectorAll('input[name="occasion"]:checked')).map(el => el.value);

      this.styleProfile = {
        preferred_colors: colors,
        preferred_silhouettes: silhouettes,
        occasions: occasions,
      };

      const response = await fetch(`${API_BASE}/intake/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.sessionId,
          preferred_colors: colors,
          preferred_silhouettes: silhouettes,
          occasions: occasions,
        }),
      });

      if (!response.ok) throw new Error('Failed to save preferences');

      this.saveSessionState();
      await this.loadRecommendations();
      this.goToStep(5);
    } catch (error) {
      console.error('Preferences error:', error);
      alert('Error saving preferences: ' + error.message);
    }
  }

  async loadRecommendations() {
    try {
      const response = await fetch(`${API_BASE}/recommendations/${this.sessionId}?k=4`);
      if (!response.ok) throw new Error('Failed to load recommendations');
      const data = await response.json();
      this.recommendations = data.recommendations || [];
    } catch (error) {
      console.error('Recommendations error:', error);
      this.recommendations = [];
    }
  }

  goToStep(step) {
    this.currentStep = step;
    this.updateProgress();

    document.querySelectorAll('.intake-screen').forEach(screen => {
      screen.classList.remove('active');
    });
    document.getElementById(`screen-${this.getScreenName(step)}`).classList.add('active');

    if (step === 2 && this.measurements.bust) {
      document.getElementById('bust').value = this.measurements.bust;
      document.getElementById('waist').value = this.measurements.waist;
      document.getElementById('hips').value = this.measurements.hips;
      document.getElementById('height').value = this.measurements.height;
      this.updateMeasurementButton();
    }

    if (step === 3) {
      if (this.shapeProfile) {
        this.displayProfile();
      } else {
        const container = document.getElementById('profileContent');
        if (container) {
          container.innerHTML = '<div class="loading">No profile data yet. Please go back and enter measurements.</div>';
        }
      }
    }

    if (step === 4) {
      if (this.styleProfile) {
        this.styleProfile.preferred_colors?.forEach(color => {
          const checkbox = document.querySelector(`input[name="color"][value="${color}"]`);
          if (checkbox) checkbox.checked = true;
        });
        this.styleProfile.preferred_silhouettes?.forEach(silhouette => {
          const checkbox = document.querySelector(`input[name="silhouette"][value="${silhouette}"]`);
          if (checkbox) checkbox.checked = true;
        });
        this.styleProfile.occasions?.forEach(occasion => {
          const checkbox = document.querySelector(`input[name="occasion"][value="${occasion}"]`);
          if (checkbox) checkbox.checked = true;
        });
      }
    }

    if (step === 5) {
      this.displayRecommendationsPreview();
    }

    this.saveSessionState();
    window.scrollTo(0, 0);
  }

  getScreenName(step) {
    const screens = ['consent', 'measurements', 'profile', 'preferences', 'complete'];
    return screens[step - 1] || 'consent';
  }

  updateProgress() {
    document.querySelectorAll('.step').forEach((step, index) => {
      step.classList.toggle('active', index + 1 <= this.currentStep);
    });

    const progressPercent = (this.currentStep / 5) * 100;
    document.querySelector('.progress-fill').style.width = `${progressPercent}%`;
  }

  displayProfile() {
    const container = document.getElementById('profileContent');
    if (!this.shapeProfile) {
      container.innerHTML = '<p>Profile data not available</p>';
      return;
    }

    const profile = this.shapeProfile;
    const ratios = profile.ratios || {};

    const sizesByCategory = profile.size_recommendation_by_category || {};
    const sizesArray = Object.entries(sizesByCategory).map(([category, size]) => ({
      category: category.replace(/([A-Z])/g, ' $1').trim(),
      size
    }));

    container.innerHTML = `
      <div class="profile-item">
        <div class="profile-label">Shape Class</div>
        <div class="profile-value" style="text-transform: capitalize;">
          ${profile.shape_class || 'Unknown'}
        </div>
        <p style="color: #999; font-size: 0.9rem; margin-top: 0.5rem;">
          ${this.getShapeDescription(profile.shape_class)}
        </p>
      </div>

      <div class="profile-item">
        <div class="profile-label">Your Ratios</div>
        <div class="profile-ratios">
          <div class="ratio-item">
            <div class="ratio-label">Bust/Waist</div>
            <div class="ratio-value">${(ratios.bust_waist || 0).toFixed(2)}</div>
          </div>
          <div class="ratio-item">
            <div class="ratio-label">Waist/Hip</div>
            <div class="ratio-value">${(ratios.waist_hip || 0).toFixed(2)}</div>
          </div>
          <div class="ratio-item">
            <div class="ratio-label">Shoulder/Hip</div>
            <div class="ratio-value">${(ratios.shoulder_hip || 0).toFixed(2)}</div>
          </div>
        </div>
      </div>

      <div class="profile-item">
        <div class="profile-label">Recommended Sizes</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 1rem; margin-top: 1rem;">
          ${sizesArray.map(rec => `
            <div style="padding: 0.75rem; background: white; border: 1px solid #ddd; border-radius: 6px; text-align: center;">
              <div style="color: #999; font-size: 0.85rem;">${rec.category || 'General'}</div>
              <div style="font-weight: 600; font-size: 1.1rem; color: #333;">${rec.size || 'N/A'}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    document.getElementById('profileNext').disabled = false;
  }

  displayRecommendationsPreview() {
    const container = document.getElementById('recommendationPreview');
    if (!container) return;

    if (!this.recommendations || this.recommendations.length === 0) {
      container.innerHTML = '<p style="text-align: center; color: #999;">Loading recommendations...</p>';
      return;
    }

    const preview = this.recommendations.slice(0, 4);
    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1.5rem; margin-top: 1.5rem;">
        ${preview.map(product => `
          <div style="text-align: center;">
            <div style="width: 100%; aspect-ratio: 3/4; background: linear-gradient(135deg, #f5f5f5 0%, #efefef 100%); border-radius: 8px; margin-bottom: 0.75rem; display: flex; align-items: center; justify-content: center; font-size: 0.9rem; color: #999;">
              ${product.name}
            </div>
            <h4 style="margin: 0.5rem 0 0.25rem 0; font-size: 0.9rem;">${product.name}</h4>
            <p style="margin: 0 0 0.5rem 0; color: #666; font-size: 0.85rem;">${product.category}</p>
            <p style="margin: 0; font-weight: 600; color: #333;">$${product.price.toFixed(2)}</p>
          </div>
        `).join('')}
      </div>
    `;
  }

  getShapeDescription(shapeClass) {
    const descriptions = {
      pear: 'Your hips are fuller than your bust. Styles that balance proportions work beautifully on you.',
      apple: 'Fuller in the bust and mid-section. Styles with focus at the neckline and legs are flattering.',
      hourglass: 'Balanced curves with defined waist. You can wear fitted styles with confidence.',
      rectangle: 'Balanced proportions with less waist definition. Structured and layered styles suit you.',
      inverted_triangle: 'Broader shoulders and narrower hips. Styles that balance your proportions work best.',
      balanced: 'Well-proportioned with even distribution. You can wear a variety of styles beautifully.',
    };
    return descriptions[shapeClass] || 'Your unique shape deserves styles tailored to you.';
  }

  viewRecommendations() {
    localStorage.setItem('currentSessionId', this.sessionId);
    window.location.href = `./recommendations.html?session=${this.sessionId}`;
  }

  continueShopping() {
    localStorage.setItem('currentSessionId', this.sessionId);
    window.location.href = '../index.html';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new IntakeFlow();
});
