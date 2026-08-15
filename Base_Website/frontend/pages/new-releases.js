/**
 * New Releases Page Controller
 *
 * Before a customer has a completed style profile, shows the newest
 * catalog arrivals with a prompt to complete their profile. Once a
 * completed profile/session exists, shows the personalized feed from
 * GET /new-releases/{session_id} (M9) instead.
 */

const API_BASE = 'http://localhost:8000';
const PREVIEW_COUNT = 6;

class NewReleasesPage {
  constructor() {
    this.sessionId = this.getSessionId();
    this.init();
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
    if (!this.sessionId) {
      this.renderPreview();
      return;
    }

    const feed = await this.loadPersonalizedFeed();
    if (feed === null) {
      // No completed profile yet (or the session is stale/incomplete) --
      // fall back to the same unpersonalized preview a first-time visitor
      // sees, rather than showing an error.
      this.renderPreview();
    } else if (feed.length === 0) {
      this.renderPersonalizedEmptyState();
    } else {
      this.renderPersonalized(feed);
    }
  }

  async loadPersonalizedFeed() {
    try {
      const response = await fetch(`${API_BASE}/new-releases/${this.sessionId}?limit=20`);
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      console.error('Failed to load personalized new releases:', error);
      return null;
    }
  }

  renderPreview() {
    document.getElementById('newReleasesSubtitle').textContent = 'Our newest arrivals';

    document.getElementById('newReleasesBanner').innerHTML = `
      <div class="loading" style="text-align: left; background: var(--color-surface); border: 1px solid var(--color-line); padding: 1.5rem; margin-bottom: 2rem;">
        <p style="margin: 0 0 0.75rem 0; color: var(--color-text);">✨ Here's what's new. Complete your style profile to see New Releases matched to your shape and style.</p>
        <a href="intake-flow.html" class="btn" style="display: inline-block;">Complete Your Style Profile</a>
      </div>
    `;

    const newest = [...PRODUCTS]
      .sort((a, b) => new Date(b.launchedAt) - new Date(a.launchedAt))
      .slice(0, PREVIEW_COUNT);

    const grid = document.getElementById('newReleasesGrid');
    if (newest.length === 0) {
      grid.innerHTML = '<div class="loading">No new arrivals right now -- check back soon.</div>';
      return;
    }

    grid.innerHTML = newest.map(product => this.buildPreviewCard(product)).join('');
  }

  renderPersonalizedEmptyState() {
    document.getElementById('newReleasesSubtitle').textContent = 'Matched to your shape and style';
    document.getElementById('newReleasesBanner').innerHTML = '';
    document.getElementById('newReleasesGrid').innerHTML = `
      <div class="loading">No new releases match your profile right now -- check back soon.</div>
    `;
  }

  renderPersonalized(feed) {
    document.getElementById('newReleasesSubtitle').textContent = 'Matched to your shape and style';
    document.getElementById('newReleasesBanner').innerHTML = '';
    document.getElementById('newReleasesGrid').innerHTML = feed
      .map(item => this.buildPersonalizedCard(item))
      .join('');
  }

  buildPreviewCard(product) {
    return `
      <a href="../../product.html?slug=${product.slug}" class="product-link">
        <div class="thumb">
            <img src="${productImage(product.sku || product.slug, 0, product.name, 450, 600)}" alt="${product.name}" loading="lazy" />
          </div>
        <span class="badge-best">New</span>
        <h3 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">${product.name}</h3>
        <p style="margin: 0 0 0.5rem 0; color: #666; font-size: 0.85rem;">${product.category}</p>
        <p style="margin: 0; color: #333; font-weight: 600;">$${product.price.toFixed(2)}</p>
      </a>
    `;
  }

  buildPersonalizedCard(item) {
    // The feed itself doesn't carry price -- cross-reference the local
    // catalog by slug (M9's "sku" is always the product slug) for display
    // details the personalization endpoint has no reason to duplicate.
    const product = PRODUCTS.find(p => p.slug === item.sku);
    const matchPercent = Math.round((item.match_score || 0) * 100);
    const recommendedSize = item.availability && item.availability.recommended_size;

    return `
      <a href="../../product.html?slug=${item.sku}" class="product-link">
        <div class="thumb">
            <img src="${productImage(item.sku || item.slug, 0, item.name, 450, 600)}" alt="${item.name}" loading="lazy" />
          </div>
        <span class="badge-best">${matchPercent}% Match</span>
        <h3 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">${item.name}</h3>
        <p style="margin: 0 0 0.5rem 0; color: #666; font-size: 0.85rem;">${item.category}</p>
        ${product ? `<p style="margin: 0 0 0.75rem 0; color: #333; font-weight: 600;">$${product.price.toFixed(2)}</p>` : ''}
        <p style="margin: 0 0 0.5rem 0; font-size: 0.85rem; color: #0066cc;">${item.reason || ''}</p>
        ${recommendedSize ? `<p style="margin: 0; font-size: 0.8rem; color: #666;">Recommended size: ${recommendedSize}</p>` : ''}
      </a>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new NewReleasesPage();
});
