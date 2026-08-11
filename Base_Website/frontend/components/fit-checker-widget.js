/**
 * Fit Checker Widget
 * Embeds on product pages to show personalized fit recommendations
 */

const API_BASE = 'http://localhost:8000';

class FitCheckerWidget {
  constructor(productSku, productName) {
    this.productSku = productSku;
    this.productName = productName;
    this.sessionId = this.getActiveSession();
    this.fitResult = null;

    if (this.sessionId) {
      this.init();
    }
  }

  getActiveSession() {
    return localStorage.getItem('currentSessionId');
  }

  async init() {
    const container = document.getElementById('fitCheckerWidget');
    if (!container) return;

    try {
      await this.checkFit();
      this.render();
    } catch (error) {
      console.error('Fit check error:', error);
      // Silently fail - widget is optional
    }
  }

  async checkFit() {
    const response = await fetch(`${API_BASE}/fit-check/${this.sessionId}/${this.productSku}`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Fit check failed');
    this.fitResult = await response.json();
  }

  render() {
    const container = document.getElementById('fitCheckerWidget');
    if (!container || !this.fitResult) return;

    const recommendedSize = this.fitResult.recommended_size;
    const confidence = Math.round(this.fitResult.confidence * 100);
    const fitScores = this.fitResult.fit_scores || {};

    container.innerHTML = `
      <div class="fit-checker-container">
        <h3>Fit Recommendation for You</h3>

        <div class="fit-recommendation">
          <div class="recommendation-box">
            <div class="recommendation-label">Recommended Size</div>
            <div class="recommendation-size">${recommendedSize}</div>
            <div class="confidence-badge">
              ${confidence}% confidence
            </div>
          </div>
        </div>

        <div class="fit-scores">
          <div class="fit-scores-label">How each size fits you:</div>
          <div class="score-bars">
            ${Object.entries(fitScores)
              .map(([size, score]) => {
                const percentage = Math.round(score * 100);
                const isRecommended = size === recommendedSize;
                return `
                  <div class="score-bar-row ${isRecommended ? 'recommended' : ''}">
                    <div class="size-label">${size}</div>
                    <div class="score-bar">
                      <div class="score-fill" style="width: ${percentage}%"></div>
                    </div>
                    <div class="score-value">${percentage}%</div>
                  </div>
                `;
              })
              .join('')}
          </div>
        </div>

        ${this.fitResult.fit_notes && this.fitResult.fit_notes.length > 0 ? `
          <div class="fit-notes">
            <div class="fit-notes-label">Fit Details</div>
            <ul class="fit-notes-list">
              ${this.fitResult.fit_notes
                .map(note => `<li>${note}</li>`)
                .join('')}
            </ul>
          </div>
        ` : ''}

        <div class="fit-actions">
          <button class="fit-feedback-btn" onclick="fitCheckerWidget.openFeedbackModal()">
            Share Your Fit Feedback
          </button>
        </div>
      </div>
    `;

    this.attachEventListeners();
  }

  attachEventListeners() {
    // Listeners attached inline in render
  }

  openFeedbackModal() {
    const modal = document.createElement('div');
    modal.className = 'fit-feedback-modal-overlay';
    modal.innerHTML = `
      <div class="fit-feedback-modal">
        <div class="modal-header">
          <h3>How did ${this.productName} fit?</h3>
          <button class="modal-close" onclick="this.closest('.fit-feedback-modal-overlay').remove()">×</button>
        </div>
        <div class="modal-body">
          <div class="feedback-option">
            <input type="radio" name="fit" id="fit-tight" value="too_tight" />
            <label for="fit-tight">
              <span class="option-name">Too Tight</span>
              <span class="option-desc">I need a larger size</span>
            </label>
          </div>
          <div class="feedback-option">
            <input type="radio" name="fit" id="fit-perfect" value="perfect" />
            <label for="fit-perfect">
              <span class="option-name">Perfect Fit</span>
              <span class="option-desc">The recommended size fit well</span>
            </label>
          </div>
          <div class="feedback-option">
            <input type="radio" name="fit" id="fit-loose" value="too_loose" />
            <label for="fit-loose">
              <span class="option-name">Too Loose</span>
              <span class="option-desc">I need a smaller size</span>
            </label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" onclick="this.closest('.fit-feedback-modal-overlay').remove()">Cancel</button>
          <button class="btn btn-primary" onclick="fitCheckerWidget.submitFeedback(event)">Submit Feedback</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  async submitFeedback(event) {
    const overlay = event.target.closest('.fit-feedback-modal-overlay');
    const selectedFit = overlay.querySelector('input[name="fit"]:checked');

    if (!selectedFit) {
      alert('Please select a fit option');
      return;
    }

    try {
      const userId = localStorage.getItem('userId');
      if (!userId) {
        throw new Error('User ID not found');
      }

      // Submit feedback to M10 backend
      const response = await fetch(`${API_BASE}/feedback/fit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          fit_check_id: this.fitResult.check_id || `${this.sessionId}-${this.productSku}`,
          product_sku: this.productSku,
          feedback_type: selectedFit.value,
          notes: `Fit feedback for ${this.productName}`,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to submit feedback');
      }

      overlay.remove();
      alert('Thank you for your feedback! This helps us improve recommendations.');
    } catch (error) {
      console.error('Feedback submission error:', error);
      alert('Error submitting feedback. Please try again.');
    }
  }
}

// Global reference for event handlers
let fitCheckerWidget;

// Initialize on product pages
document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const productSlug = params.get('slug');

  // Get product data (assumes PRODUCTS is loaded from data.js)
  if (typeof PRODUCTS !== 'undefined') {
    const product = PRODUCTS.find(p => p.slug === productSlug);
    if (product) {
      fitCheckerWidget = new FitCheckerWidget(product.slug, product.name);
    }
  }
});
