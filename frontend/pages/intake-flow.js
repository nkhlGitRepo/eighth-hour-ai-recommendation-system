/**
 * Intake Flow Controller
 * Orchestrates the multi-step intake process with backend API calls
 */

const API_BASE = window.EH_API_BASE;

// Ceiling on a photo-measurement request. The local pose model answers in about
// a second, but a hosted vendor can take tens of seconds and could hang
// outright -- fetch() has no default timeout, so without this the spinner would
// spin forever instead of showing the error panel.
const PHOTO_SCAN_TIMEOUT_MS = 60000;
// Photos are shrunk to this before upload (see shrinkPhotoForUpload). Above the
// server's 1280 px analysis size, so the server's own resize is the last step.
const PHOTO_UPLOAD_LONGEST_SIDE_PX = 1600;

class IntakeFlow {
  constructor() {
    // The style quiz is account-gated: a logged-out visitor is sent to
    // sign up before anything else here runs (before touching localStorage
    // session state or calling the backend at all).
    if (!isAuthenticated()) {
      window.location.href = 'signup.html?redirect=intake-flow.html&message=' +
        encodeURIComponent('Sign up to build your style profile.');
      return;
    }

    this.currentStep = 1;
    this.sessionId = null;
    this.userId = this.getAuthenticatedUserId();
    this.measurements = {};
    this.shapeProfile = null;
    this.styleProfile = null;
    this.recommendations = [];
    // Photo measurement screen state (transient -- never persisted, since the
    // image itself is never stored anywhere).
    this.selectedPhoto = null;
    this.previewUrl = null;
    this.pendingScanNote = null;
    // Whether the configured provider actually analyses the uploaded image.
    // null until the disclosure loads; treated as "does not" unless proven.
    this.photoDerivesFromImage = null;

    this.init();
  }

  init() {
    this.attachEventListeners();
    this.restoreSession();
    this.loadAvailableColors();

    // Check for step parameter in URL (e.g., ?step=2)
    const params = new URLSearchParams(window.location.search);
    const stepParam = params.get('step');
    if (stepParam) {
      const step = parseInt(stepParam);
      if (step >= 1 && step <= 5) {
        this.goToStep(step);
      }
    }
  }

  getAuthenticatedUserId() {
    // Set by loginAccount() in auth.js -- always present once
    // isAuthenticated() is true (checked in the constructor above).
    return localStorage.getItem('userId');
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
          // This list replaces the fallback markup, and can arrive well after
          // the page did (30-60 s while a sleeping server wakes). By then the
          // customer may have ticked colours, or a returning customer's saved
          // ones were restored -- keep both rather than silently wiping them.
          const shown = Array.from(colorContainer.querySelectorAll('input[name="color"]'));
          const ticked = new Set(shown.filter(el => el.checked).map(el => el.value));
          // A saved colour the fallback list didn't include couldn't be restored
          // into it, so restore it now. One it did include is already reflected
          // above -- including if the customer has since unticked it.
          const wasShown = new Set(shown.map(el => el.value));
          (this.styleProfile?.preferred_colors || [])
            .filter(color => !wasShown.has(color))
            .forEach(color => ticked.add(color));

          colorContainer.replaceChildren(...availableColors.map(color => {
            const label = document.createElement('label');
            label.className = 'option-label';
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.name = 'color';
            input.value = color;
            input.checked = ticked.has(color);
            const name = document.createElement('span');
            name.textContent = color;
            label.append(input, name);
            return label;
          }));
          // This replaces the markup wholesale, so the colour samples have to be
          // (re)applied here. Applying them only on DOMContentLoaded decorated
          // the static fallback list and was then wiped the moment this fetch
          // resolved -- which is every time the API is reachable.
          renderColorSwatches();
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

    // `currentSessionId` is the key every OTHER page reads to find the
    // customer's profile: New Releases, the product page's fit-check widget,
    // the homepage recommendation strip, and the header's "My Recommendations"
    // link. It used to be written only by the two buttons on the final screen,
    // so a customer who completed their profile and then navigated via the
    // header left all of those believing no profile existed. The Recommendations
    // page was the one exception, because it also accepts ?session= in the URL
    // and the completion button supplies it -- which is why that page alone
    // appeared to work. Kept in step with the session here so there is one
    // writer rather than a side effect of a particular click.
    if (this.sessionId) {
      localStorage.setItem('currentSessionId', this.sessionId);
    } else {
      // Never store the string "null" -- every consumer treats any value as a
      // usable session id, so a stale placeholder is worse than an absent key.
      localStorage.removeItem('currentSessionId');
    }
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

    // Measurements screen
    ['bust', 'waist', 'hips', 'height'].forEach(field => {
      document.getElementById(field)?.addEventListener('change', () => this.updateMeasurementButton());
    });
    document.getElementById('measurementsPrev')?.addEventListener('click', () => this.goToStep(1));
    document.getElementById('measurementsNext')?.addEventListener('click', () => this.handleMeasurements());
    document.getElementById('photoCapture')?.addEventListener('click', (e) => {
      e.preventDefault();
      this.showPhotoScreen();
    });

    // Photo measurement screen (an alternate view of step 2, not its own step)
    document.getElementById('photoAck')?.addEventListener('change', () => this.updatePhotoScanButton());
    document.getElementById('photoHeight')?.addEventListener('input', () => this.updatePhotoScanButton());
    ['photoTopSize', 'photoBottomSize'].forEach(id => {
      document.getElementById(id)?.addEventListener('change', () => this.updatePhotoScanButton());
    });
    document.getElementById('photoFile')?.addEventListener('change', (e) => this.handlePhotoSelected(e));
    document.getElementById('photoScan')?.addEventListener('click', () => this.handlePhotoScan());
    document.getElementById('photoBack')?.addEventListener('click', () => this.goToStep(2));
    document.getElementById('photoManualEntry')?.addEventListener('click', (e) => {
      e.preventDefault();
      this.goToStep(2);
    });
    document.getElementById('photoErrorRetry')?.addEventListener('click', () => this.retryPhotoSelection());
    document.getElementById('photoErrorManual')?.addEventListener('click', () => this.goToStep(2));

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

  /**
   * If an API call failed because the backend no longer has this
   * session_id (e.g. a stale localStorage session_id restored via
   * restoreSession() from a dev database reset, or a very old bookmark),
   * clear the dead state and restart at step 1 instead of leaving the
   * user stuck retrying the same call against a session_id that will
   * never resolve. Returns true if it handled recovery.
   */
  recoverFromMissingSession(error) {
    if (!/session .* not found/i.test(error.message || '')) return false;
    this.clearSession();
    alert('Your style profile session has expired. Please start again.');
    location.reload();
    return true;
  }

  updateConsentButton() {
    const photoConsent = document.getElementById('photoConsent').checked;
    const measurementConsent = document.getElementById('measurementConsent').checked;
    document.getElementById('consentNext').disabled = !(photoConsent && measurementConsent);
  }

  /**
   * Render the "estimated from your photo" note on the measurements screen.
   * Shown once, immediately after a scan -- arriving at step 2 any other way
   * (from consent, or Back from the shape profile) clears it, so it never
   * lingers next to numbers the customer typed themselves.
   */
  renderScanNote() {
    const note = document.getElementById('measurementScanNote');
    if (!note) return;

    const pending = this.pendingScanNote;
    this.pendingScanNote = null;

    if (!pending) {
      note.hidden = true;
      note.textContent = '';
      note.className = 'measurement-scan-note';
      return;
    }

    note.textContent = pending.text;
    note.className = `measurement-scan-note ${pending.tone}`;
    note.hidden = false;
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

      const sessionResponse = await fetch(`${API_BASE}/intake/session`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('authToken')}` },
      });

      if (!sessionResponse.ok) {
        if (sessionResponse.status === 401) {
          window.location.href = 'login.html?redirect=intake-flow.html';
          return;
        }
        throw new Error(`Failed to create session: ${sessionResponse.status}`);
      }
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
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Server error (${response.status})`);
      }

      const data = await response.json();
      this.shapeProfile = data.shape_profile;

      this.saveSessionState();
      this.goToStep(3);
    } catch (error) {
      console.error('Measurements error:', error);
      if (this.recoverFromMissingSession(error)) return;
      alert('Error processing measurements: ' + error.message);
    }
  }

  // =======================================================================
  // Photo measurement
  //
  // screen-photo is an alternate view of step 2, NOT a sixth step: the
  // progress bar keeps reading "Measurements" and currentStep stays 2. It's
  // shown by swapping the active .intake-screen directly rather than through
  // goToStep(), which is reserved for the five real steps. Leaving works for
  // free because goToStep() clears `active` from every .intake-screen.
  // =======================================================================

  showPhotoScreen() {
    // Without a session there is nothing to attach a scan to, and the failure
    // would otherwise surface at the very end as "we couldn't measure that
    // photo" -- blaming a photo that was never sent. Catch it before the
    // customer picks a file and does the work of framing a shot.
    if (!this.sessionId) {
      this.handleMissingSession();
      return;
    }

    document.querySelectorAll('.intake-screen').forEach(screen => {
      screen.classList.remove('active');
    });
    document.getElementById('screen-photo').classList.add('active');
    window.scrollTo(0, 0);

    this.resetPhotoScreen();
    this.loadPhotoDisclosure();
  }

  resetPhotoScreen() {
    this.selectedPhoto = null;

    const fileInput = document.getElementById('photoFile');
    if (fileInput) fileInput.value = '';

    const ack = document.getElementById('photoAck');
    if (ack) ack.checked = false;

    // Carry over a height already typed on the manual screen -- it's the
    // same measurement, so asking twice would be pointless friction.
    const heightInput = document.getElementById('photoHeight');
    if (heightInput) {
      heightInput.value = this.measurements.height || document.getElementById('height')?.value || '';
    }

    ['photoTopSize', 'photoBottomSize'].forEach(id => {
      const select = document.getElementById(id);
      if (select) select.value = '';
    });

    this.hidePhotoPreview();
    this.clearPhotoError();
    this.setPhotoScanning(false);
    this.updatePhotoScanButton();
  }

  /**
   * Render the privacy notice from the backend's active-provider disclosure
   * rather than hardcoded copy, so it can never claim something untrue about
   * where the photo goes. Fails CLOSED: if the disclosure can't be loaded the
   * upload controls stay hidden, because collecting a body photo without a
   * notice we can stand behind is worse than the feature being unavailable.
   */
  async loadPhotoDisclosure() {
    const container = document.getElementById('photoDisclosure');
    const body = document.getElementById('photoUploadBody');
    if (!container || !body) return;

    body.hidden = true;
    container.innerHTML = '<div class="loading">Loading privacy information...</div>';

    try {
      const response = await fetch(`${API_BASE}/intake/photo-disclosure`);
      if (!response.ok) throw new Error(`status ${response.status}`);
      const disclosure = await response.json();

      const offsite = disclosure.sends_image_offsite === true;
      // Explicit false check: a provider that forgets the field shouldn't be
      // treated as if it really analyses photos.
      const derives = disclosure.derives_from_image === true;
      this.photoDerivesFromImage = derives;

      container.className = `photo-disclosure${offsite ? ' offsite' : ''}${derives ? '' : ' placeholder'}`;
      container.innerHTML = `
        ${derives ? '' : `
          <p class="disclosure-demo-warning">
            <strong>Demo mode — your photo is not analysed.</strong>
            This build isn't connected to a measurement service yet, so it fills in the
            same fixed sample measurements no matter what you upload. Any image, even
            one that isn't a person, returns identical numbers. Treat the values as a
            placeholder and replace them with your real measurements.
          </p>
        `}
        <h3>Before you upload</h3>
        <ul>
          <li><strong>What we collect:</strong> a photo of your body.</li>
          <li><strong>What it's used for:</strong> ${
            derives
              ? `estimating your measurements for size recommendations — nothing else.
                 It is never used to identify you, for advertising, or to train models,
                 and it is never sold.`
              : `nothing, in this build. Your photo is received and immediately discarded
                 without being examined. It is never used to identify you, for
                 advertising, or to train models, and it is never sold.`
          }</li>
          <li><strong>Who handles it:</strong>
              <span class="disclosure-processor">${escapeHtml(disclosure.processor_name)}</span>${
                offsite
                  ? ' — your photo is sent to this processor outside our servers.'
                  : ' — your photo is not sent to any third party.'
              }</li>
          <li><strong>How long we keep it:</strong> ${escapeHtml(disclosure.retention)}</li>
          ${derives ? `
          <li>These are automated estimates, not a professional fitting. You can edit
              any measurement afterwards.</li>` : ''}
        </ul>
        <p style="margin: 0.75rem 0 0;">
          <a href="../../faq.html#photo-measurement-data">Read the full photo &amp; measurement data policy</a>
        </p>
      `;
      body.hidden = false;
    } catch (error) {
      console.error('Could not load photo disclosure:', error);
      container.className = 'photo-disclosure';
      container.innerHTML = `
        <h3>Photo measurement is unavailable</h3>
        <p style="margin: 0;">We can't confirm how your photo would be handled right now,
        so we've disabled photo upload. Please
        <a href="#" id="photoDisclosureFallback">enter your measurements manually</a> instead.</p>
      `;
      document.getElementById('photoDisclosureFallback')?.addEventListener('click', (e) => {
        e.preventDefault();
        this.goToStep(2);
      });
      body.hidden = true;
    }
  }

  handlePhotoSelected(event) {
    this.clearPhotoError();
    const file = event.target.files && event.target.files[0];

    if (!file) {
      this.selectedPhoto = null;
      this.hidePhotoPreview();
      this.updatePhotoScanButton();
      return;
    }

    this.selectedPhoto = file;

    // Local preview so the customer can confirm they picked the right image
    // before anything is uploaded. Object URL is revoked on replace/leave.
    const preview = document.getElementById('photoPreview');
    const image = document.getElementById('photoPreviewImage');
    if (preview && image) {
      this.revokePreviewUrl();
      this.previewUrl = URL.createObjectURL(file);
      image.src = this.previewUrl;
      preview.hidden = false;
    }

    this.updatePhotoScanButton();
  }

  hidePhotoPreview() {
    this.revokePreviewUrl();
    const preview = document.getElementById('photoPreview');
    const image = document.getElementById('photoPreviewImage');
    if (preview) preview.hidden = true;
    if (image) image.removeAttribute('src');
  }

  revokePreviewUrl() {
    if (this.previewUrl) {
      URL.revokeObjectURL(this.previewUrl);
      this.previewUrl = null;
    }
  }

  updatePhotoScanButton() {
    const button = document.getElementById('photoScan');
    if (!button) return;

    const height = parseFloat(document.getElementById('photoHeight')?.value);
    const acknowledged = document.getElementById('photoAck')?.checked;
    const validHeight = !isNaN(height) && height >= 140 && height <= 210;
    // Required: the photo is measured against the sizes the customer wears.
    const sizesChosen = ['photoTopSize', 'photoBottomSize']
      .every(id => document.getElementById(id)?.value);

    button.disabled = !(this.selectedPhoto && validHeight && acknowledged && sizesChosen);
  }

  /**
   * Show the single photo-measurement error panel.
   *
   * Every failure funnels through here on purpose -- unreadable file, no person
   * detected, unusable pose, oversized upload, server down, and (once a paid
   * vendor is configured) timeouts, rate limits and auth failures. The customer
   * gets one consistent message and two ways forward; the underlying reason is
   * logged for developers but never rendered, so vendor error text and internal
   * details can't leak into the page.
   */
  showPhotoError(technicalReason) {
    if (technicalReason) {
      console.error('Photo measurement failed:', technicalReason);
    }
    const box = document.getElementById('photoError');
    if (!box) return;
    box.hidden = false;
    box.scrollIntoView?.({ block: 'nearest' });
  }

  /**
   * Recover from having no session: say so plainly and return to step 1, which
   * is where a session (and the consent it records) is created. Deliberately
   * does NOT quietly create a session and re-record consent on the customer's
   * behalf -- consent is the one thing that must stay an explicit action.
   */
  handleMissingSession() {
    this.clearPhotoError();
    alert('Your style profile session has ended, so there was nothing to attach the scan to. Your photo was fine — please confirm consent again and we\'ll pick up from there.');
    this.goToStep(1);
  }

  clearPhotoError() {
    const box = document.getElementById('photoError');
    if (box) box.hidden = true;
  }

  /** Clear the chosen file so the customer can pick a different photo. */
  retryPhotoSelection() {
    this.clearPhotoError();
    this.selectedPhoto = null;
    const fileInput = document.getElementById('photoFile');
    if (fileInput) {
      fileInput.value = '';
      fileInput.focus();
    }
    this.hidePhotoPreview();
    this.updatePhotoScanButton();
  }

  setPhotoScanning(scanning) {
    const indicator = document.getElementById('photoScanning');
    if (indicator) indicator.hidden = !scanning;

    const scanButton = document.getElementById('photoScan');
    const backButton = document.getElementById('photoBack');
    const fileInput = document.getElementById('photoFile');

    if (scanning) {
      if (scanButton) scanButton.disabled = true;
      if (backButton) backButton.disabled = true;
      if (fileInput) fileInput.disabled = true;
    } else {
      if (backButton) backButton.disabled = false;
      if (fileInput) fileInput.disabled = false;
      this.updatePhotoScanButton();
    }
  }

  async handlePhotoScan() {
    this.clearPhotoError();

    const height = parseFloat(document.getElementById('photoHeight').value);
    if (!this.selectedPhoto || isNaN(height)) {
      this.showPhotoError('missing photo or height before submit');
      return;
    }

    this.setPhotoScanning(true);

    try {
      // The session is created by the consent step; if the customer deep-linked
      // straight to ?step=2, used Start Fresh, or the saved state was cleared,
      // there may not be one. This is NOT a problem with their photo, so it
      // must not be reported through the photo error panel.
      if (!this.sessionId) {
        this.setPhotoScanning(false);
        this.handleMissingSession();
        return;
      }

      const formData = new FormData();
      formData.append('session_id', this.sessionId);
      formData.append('height_cm', String(height));
      formData.append('photo', await shrinkPhotoForUpload(this.selectedPhoto));
      // Required (the scan button stays disabled until both are chosen): the
      // backend anchors bust on the top size and waist/hips on the bottom size,
      // and the photo adjusts within them. A photo alone was measured missing
      // by ~17 cm on average.
      formData.append('usual_top_size', document.getElementById('photoTopSize').value);
      formData.append('usual_bottom_size', document.getElementById('photoBottomSize').value);

      // Abort rather than hang if the measurement service stops responding.
      // A local model is fast, but a hosted vendor may not be -- and a request
      // that never settles would leave the customer watching a spinner.
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), PHOTO_SCAN_TIMEOUT_MS);

      let response;
      try {
        // NOTE: no Content-Type header -- the browser must set it so the
        // multipart boundary is included.
        response = await fetch(`${API_BASE}/intake/photo-measure`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${localStorage.getItem('authToken')}` },
          body: formData,
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeout);
      }

      if (response.status === 401) {
        window.location.href = 'login.html?redirect=intake-flow.html';
        return;
      }

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Could not process that photo (${response.status})`);
      }

      const data = await response.json();
      const extracted = data.measurements || {};

      this.measurements = {
        bust: extracted.bust,
        waist: extracted.waist,
        hips: extracted.hips,
        height: extracted.height,
      };
      this.shapeProfile = data.shape_profile;
      this.saveSessionState();

      this.hidePhotoPreview();

      // Return to the measurements screen rather than jumping ahead to the
      // shape profile: the whole point of scanning is the numbers, so the
      // customer should see and be able to correct them first. The shape
      // profile has already been generated server-side, and pressing Continue
      // re-submits whatever is in these fields -- so any edit made here is
      // honored rather than silently overwritten by the scan's values.
      const lowConfidence = data.low_confidence_fields || [];

      if (this.photoDerivesFromImage === false) {
        // Demo mode: nothing examined the photo, so saying these were
        // "estimated from your photo" would simply be untrue.
        this.pendingScanNote = {
          tone: 'caution',
          text: 'Demo mode: these are fixed sample measurements, not taken from your photo — ' +
                'every image returns the same values. Please replace them with your real ' +
                'measurements before continuing.',
        };
      } else if (lowConfidence.length > 0) {
        this.pendingScanNote = {
          tone: 'caution',
          text: `We estimated these from your photo, but weren't fully confident about: ${lowConfidence.join(', ')}. Please double-check them before continuing.`,
        };
      } else {
        this.pendingScanNote = {
          tone: 'success',
          text: 'These measurements were estimated from your photo. Review them, edit anything that looks off, then continue.',
        };
      }

      this.goToStep(2);
    } catch (error) {
      console.error('Photo measurement error:', error);
      if (this.recoverFromMissingSession(error)) return;
      this.showPhotoError(error);
    } finally {
      this.setPhotoScanning(false);
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

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || 'Failed to save preferences');
      }

      this.saveSessionState();
      await this.loadRecommendations();
      this.goToStep(5);
    } catch (error) {
      console.error('Preferences error:', error);
      if (this.recoverFromMissingSession(error)) return;
      alert('Error saving preferences: ' + error.message);
    }
  }

  async loadRecommendations() {
    try {
      const response = await fetch(`${API_BASE}/recommendations/${this.sessionId}?k=4&user_id=${this.userId}`);
      if (!response.ok) throw new Error('Failed to load recommendations');
      const data = await response.json();
      this.recommendations = data.recommendations || [];
      console.log('Loaded recommendations:', this.recommendations.length);
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

    if (step === 2) {
      if (this.measurements.bust) {
        document.getElementById('bust').value = this.measurements.bust;
        document.getElementById('waist').value = this.measurements.waist;
        document.getElementById('hips').value = this.measurements.hips;
        document.getElementById('height').value = this.measurements.height;
        this.updateMeasurementButton();
      }
      this.renderScanNote();
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
    const comparisons = this.shapeComparisons(profile);

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
        <p class="shape-summary">
          ${profile.shape_summary || this.getShapeDescription(profile.shape_class)}
        </p>
      </div>

      ${comparisons.length ? `
      <div class="profile-item">
        <div class="profile-label">How Your Measurements Compare</div>
        <div class="profile-ratios">
          ${comparisons.map(item => `
            <div class="ratio-item">
              <div class="ratio-label">${item.label}</div>
              <div class="ratio-value">${item.value}</div>
            </div>
          `).join('')}
        </div>
      </div>` : ''}

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

  async displayRecommendationsPreview() {
    const container = document.getElementById('recommendationPreview');
    if (!container) return;

    // Recommendations are loaded once, when preferences are submitted. Returning
    // to this screen later -- a reload, or restoreSession() putting the customer
    // back on step 5 -- leaves the list empty, and this used to sit on
    // "Loading recommendations..." forever because nothing ever fetched them
    // again. Fetch them here instead of assuming an earlier step did.
    if ((!this.recommendations || this.recommendations.length === 0) && this.sessionId) {
      container.innerHTML = '<p style="text-align: center; color: #999;">Loading recommendations...</p>';
      await this.loadRecommendations();
      this.saveSessionState();
    }

    if (!this.recommendations || this.recommendations.length === 0) {
      container.innerHTML =
        '<p style="text-align: center; color: #999;">' +
        'We couldn\'t load your recommendations just now. ' +
        '<a href="recommendations.html">View them here</a>.</p>';
      return;
    }

    const preview = this.recommendations.slice(0, 4);

    // Reuses the storefront's own product card so this preview matches the
    // rest of the site. It previously drew a grey gradient box with the product
    // name written inside it -- a stand-in from before the catalog had any
    // photography, which was simply never revisited once real images landed.
    container.innerHTML = `
      <div class="product-grid completion-preview">
        ${preview.map(product => {
          const slug = product.slug || product.sku;
          return `
          <a class="product-card" href="../../product.html?slug=${slug}">
            <div class="thumb">
              <img src="${productImage(slug, 0, product.name, 450, 600)}"
                   alt="${product.name}" loading="lazy" />
            </div>
            <div class="name">${product.name}</div>
            <div class="price">$${product.price.toFixed(2)}</div>
          </a>`;
        }).join('')}
      </div>
    `;
  }

  /**
   * The comparisons the shape is decided on, in centimetres a customer can
   * check against their own tape measure -- rather than bare ratios, which read
   * as "off" (Bust/Waist 1.19 beside Waist/Hip 0.84) and once included a
   * shoulder/hip figure that was invented whenever no shoulder was measured.
   *
   * Uses the profile's own comparisons_cm when present. A profile saved before
   * that field existed falls back to the measurements it was made from.
   */
  shapeComparisons(profile) {
    let diffs = profile.comparisons_cm;
    const m = this.measurements || {};
    if (!diffs && m.bust && m.waist && m.hips) {
      const [bust, waist, hips] = [m.bust, m.waist, m.hips].map(Number);
      diffs = {
        bust_minus_hips: bust - hips,
        bust_minus_waist: bust - waist,
        hips_minus_waist: hips - waist,
      };
    }
    if (!diffs) return [];

    const cm = (value) => `${Math.round(Math.abs(value))} cm`;
    const waistAgainst = (gap) => Math.round(gap) === 0 ? 'Same'
      : `${cm(gap)} ${gap > 0 ? 'smaller' : 'larger'}`;
    const items = [
      {
        label: 'Bust vs Hips',
        value: Math.round(diffs.bust_minus_hips) === 0 ? 'Even'
          : diffs.bust_minus_hips > 0 ? `Bust ${cm(diffs.bust_minus_hips)} fuller`
          : `Hips ${cm(diffs.bust_minus_hips)} fuller`,
      },
      { label: 'Waist vs Bust', value: waistAgainst(diffs.bust_minus_waist) },
      { label: 'Waist vs Hips', value: waistAgainst(diffs.hips_minus_waist) },
    ];
    const ratios = profile.ratios || {};
    if (ratios.waist_hip) {
      items.push({ label: 'Waist-to-Hip Ratio', value: Number(ratios.waist_hip).toFixed(2) });
    }
    return items;
  }

  /**
   * Fallback text for a profile saved before the API explained each shape from
   * the customer's own measurements (shape_summary). Keyed by the API's class
   * names -- this previously used "rectangle" and "inverted_triangle", which the
   * API never returns, so straight and athletic shapes got the generic line.
   */
  getShapeDescription(shapeClass) {
    const descriptions = {
      pear: 'Fuller through the hips than the bust.',
      athletic: 'Fuller through the bust than the hips, with a straighter waist.',
      hourglass: 'A clearly defined waist.',
      apple: 'Fullest through the middle.',
      straight: 'Neither bust nor hips distinctly fuller, and little waist definition.',
      balanced: 'Neither bust nor hips distinctly fuller, with a moderately defined waist.',
    };
    return descriptions[shapeClass] || 'Your unique shape deserves styles tailored to you.';
  }

  viewRecommendations() {
    this.saveSessionState();
    window.location.href = `./recommendations.html?session=${this.sessionId}`;
  }

  continueShopping() {
    this.saveSessionState();
    window.location.href = '../../index.html';
  }
}

/**
 * A copy of the photo no larger than the analysis needs, as a JPEG.
 *
 * The server analyses photos at ~1280 px, but phones shoot 12-48 megapixels,
 * and decoding a full-size WEBP or HEIC there costs hundreds of megabytes --
 * enough to crash the server. Shrinking here also makes the upload far faster
 * on a phone connection. The browser applies the photo's EXIF rotation when
 * decoding, so the copy is the right way up. If the browser can't decode the
 * format (HEIC in desktop Chrome, say), the original is sent unchanged.
 */
async function shrinkPhotoForUpload(file, longestSide = PHOTO_UPLOAD_LONGEST_SIDE_PX) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, longestSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.type === 'image/jpeg') {
      bitmap.close?.();
      return file;
    }
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    // JPEG has no transparency: without a fill, a transparent PNG would
    // upload as a person on a black background.
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    return blob ? new File([blob], 'photo.jpg', { type: 'image/jpeg' }) : file;
  } catch (error) {
    console.warn('Sending the photo at its original size:', error);
    return file;
  }
}

/**
 * Turn each colour option into a tile: a large sample of the colour with its
 * name beneath. Customers choose by eye -- most won't recognise a Pantone name
 * like "Sky Captain" -- so the sample is the main thing and the name a caption.
 *
 * Rendered from colorHex() rather than written into the markup, so the sample a
 * customer picks from is the same value the product pages paint their swatches
 * with -- two hardcoded copies would eventually disagree.
 *
 * The sample goes INSIDE the span, not between the input and the span: the
 * checked-state styling is `input:checked + span`, an adjacent-sibling rule that
 * an element inserted between the two would silently break.
 */
function renderColorSwatches() {
  if (typeof colorHex !== 'function') return;   // data.js absent; names still work
  document.querySelectorAll('.color-options input[name="color"]').forEach((input) => {
    const label = input.nextElementSibling;
    if (!label || label.querySelector('.color-swatch')) return;

    const name = document.createElement('span');
    name.className = 'color-name';
    name.textContent = label.textContent.trim();
    label.textContent = '';

    const hex = colorHex(input.value);
    const sample = document.createElement('i');
    sample.className = 'color-swatch';
    sample.style.background = hex;
    // The tick drawn on a selected sample must read against it: white on the
    // dark colours, near-black on the light ones.
    sample.style.setProperty('--swatch-ink', swatchInk(hex));
    // Decorative: the colour's name is already the accessible label, so a
    // screen reader announcing it twice would be noise.
    sample.setAttribute('aria-hidden', 'true');

    label.append(sample, name);
    // Hovering the tile shows the hex too, for anyone matching a colour exactly.
    input.closest('label').title = `${name.textContent} (${hex})`;
  });
}

/** Ink for marks drawn on a colour: dark on light colours, white on dark ones. */
function swatchInk(hex) {
  const value = String(hex).replace('#', '');
  const full = value.length === 3 ? value.split('').map((c) => c + c).join('') : value;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  if ([r, g, b].some(Number.isNaN)) return '#ffffff';
  // WCAG relative luminance.
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.4 ? '#121212' : '#ffffff';
}

document.addEventListener('DOMContentLoaded', () => {
  renderColorSwatches();
  new IntakeFlow();
});
