/**
 * Frontend Integration Tests
 * Drives the live API the way the storefront does, end to end over HTTP.
 *
 * Requirements verified:
 * 1. The guided flow (account -> consent -> measurements -> shape -> style) completes
 * 2. Measurements -> body shape profile, explained from the customer's own numbers
 * 3. Shape profile -> personalized recommendations, new releases and fit checks
 * 4. The limits the measurement form advertises are exactly the ones the API enforces
 * 5. Photo measurement requires the customer's usual sizes, and measures a real photo
 * 6. Editing a finished profile ("Update Style") doesn't take the profile away
 *
 * Run against a current API (see the README's "Is the server running your code?"):
 *
 *     node frontend/tests/integration.test.js
 *     API_BASE=http://localhost:8199 node frontend/tests/integration.test.js
 *
 * Every test creates its own throwaway account, so runs don't interfere.
 */

const fs = require('fs');
const path = require('path');

const API_BASE = process.env.API_BASE || 'http://localhost:8000';
const FORM_HTML = path.join(__dirname, '../pages/intake-flow.html');
const SAMPLE_PHOTO = path.join(
  __dirname, '../../images/products/mulberry-silk-wide-neck-vest-and-pant-set__duffel-bag-1.jpg');

const SHAPE_CLASSES = ['balanced', 'pear', 'apple', 'hourglass', 'straight', 'athletic'];
const SIZES = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL'];

// ============================================================================
// Test Utilities
// ============================================================================

class TestRunner {
  constructor() {
    this.results = [];
    this.currentTest = null;
  }

  async test(name, fn) {
    this.currentTest = name;
    try {
      await fn();
      this.pass(name);
    } catch (error) {
      this.fail(name, error.message);
    }
  }

  pass(name) {
    this.results.push({ status: '✅ PASS', name });
    console.log(`✅ PASS: ${name}`);
  }

  fail(name, reason) {
    this.results.push({ status: '❌ FAIL', name, reason });
    console.error(`❌ FAIL: ${name} - ${reason}`);
  }

  assert(condition, message) {
    if (!condition) throw new Error(message);
  }

  assertEquals(actual, expected, message) {
    if (actual !== expected) {
      throw new Error(`${message} - Expected: ${expected}, Got: ${actual}`);
    }
  }

  assertIsObject(obj, message) {
    if (typeof obj !== 'object' || obj === null) {
      throw new Error(`${message} - Expected object, got ${typeof obj}`);
    }
  }

  assertInRange(value, min, max, message) {
    if (value < min || value > max) {
      throw new Error(`${message} - Expected ${value} to be between ${min} and ${max}`);
    }
  }

  summary() {
    const passed = this.results.filter(r => r.status === '✅ PASS').length;
    const failed = this.results.filter(r => r.status === '❌ FAIL').length;
    console.log('\n' + '='.repeat(80));
    console.log(`SUMMARY: ${passed} passed, ${failed} failed out of ${this.results.length} tests`);
    console.log('='.repeat(80) + '\n');
    return { passed, failed, total: this.results.length };
  }
}

/** A logged-in throwaway customer, with helpers that send their token. */
class Customer {
  static async create(label) {
    const username = `it_${label}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const password = `${Math.random().toString(36).slice(2)}Aa1!${Date.now()}`;
    const register = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email: `${username}@example.test`, password }),
    });
    if (!register.ok) throw new Error(`register failed (${register.status})`);
    const login = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!login.ok) throw new Error(`login failed (${login.status})`);
    const { token, user_id: userId } = await login.json();
    return new Customer(token, userId);
  }

  constructor(token, userId) {
    this.token = token;
    this.userId = userId;
  }

  request(method, route, body) {
    const headers = { Authorization: `Bearer ${this.token}` };
    let payload = body;
    if (body !== undefined && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    return fetch(`${API_BASE}${route}`, { method, headers, body: payload });
  }

  async json(method, route, body) {
    const response = await this.request(method, route, body);
    const data = await response.json().catch(() => null);
    return { response, data };
  }

  /** A new session with consent on record; returns its id. */
  async consentedSession() {
    const { response, data } = await this.json('POST', '/intake/session');
    if (!response.ok) throw new Error(`session failed (${response.status})`);
    const consent = await this.request('POST', '/intake/consent', {
      session_id: data.session_id, photo_consent: true, measurement_consent: true,
    });
    if (!consent.ok) throw new Error(`consent failed (${consent.status})`);
    return data.session_id;
  }

  /** Consent, measurements and preferences: a finished profile. */
  async completedSession(measurements, preferences = {}) {
    const sessionId = await this.consentedSession();
    const confirm = await this.json('POST', '/intake/confirm', {
      session_id: sessionId, manual_overrides: measurements,
    });
    if (!confirm.response.ok) throw new Error(`confirm failed (${confirm.response.status})`);
    const prefs = await this.request('POST', '/intake/preferences', {
      session_id: sessionId,
      preferred_colors: ['Ebony'],
      preferred_silhouettes: ['fitted'],
      occasions: ['work'],
      ...preferences,
    });
    if (!prefs.ok) throw new Error(`preferences failed (${prefs.status})`);
    return { sessionId, shapeProfile: confirm.data.shape_profile };
  }

  photoScan(sessionId, { top, bottom, heightCm = 170 } = {}) {
    const form = new FormData();
    form.append('session_id', sessionId);
    form.append('height_cm', String(heightCm));
    if (top) form.append('usual_top_size', top);
    if (bottom) form.append('usual_bottom_size', bottom);
    form.append('photo', new Blob([fs.readFileSync(SAMPLE_PHOTO)], { type: 'image/jpeg' }), 'photo.jpg');
    return this.json('POST', '/intake/photo-measure', form);
  }
}

/** The min/max each measurement input on the form declares. */
function formLimits() {
  const html = fs.readFileSync(FORM_HTML, 'utf8');
  const limits = {};
  for (const field of ['bust', 'waist', 'hips', 'height']) {
    const match = html.match(new RegExp(`id="${field}"[^>]*min="(\\d+)"[^>]*max="(\\d+)"`));
    if (!match) throw new Error(`no min/max on the ${field} input in intake-flow.html`);
    limits[field] = { min: Number(match[1]), max: Number(match[2]) };
  }
  return limits;
}

// ============================================================================
// API Integration Tests
// ============================================================================

async function testAPIIntegration(runner) {
  console.log('\n📋 API INTEGRATION TESTS\n');

  let customer = null;
  let sessionId = null;

  await runner.test('Intake requires a logged-in customer', async () => {
    const response = await fetch(`${API_BASE}/intake/session`, { method: 'POST' });
    runner.assertEquals(response.status, 401, 'Anonymous session creation should be refused');
  });

  await runner.test('POST /intake/session creates a session for the logged-in customer', async () => {
    customer = await Customer.create('flow');
    const { response, data } = await customer.json('POST', '/intake/session');
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assert(data.session_id, 'Missing session_id');
    runner.assertEquals(data.user_id, customer.userId, 'Session belongs to the wrong user');
    runner.assertEquals(data.status, 'initiated', 'Initial status should be "initiated"');
    runner.assert(data.created_at, 'Missing created_at timestamp');
    sessionId = data.session_id;
  });

  await runner.test('POST /intake/consent records photo and measurement consent', async () => {
    const { response, data } = await customer.json('POST', '/intake/consent', {
      session_id: sessionId, photo_consent: true, measurement_consent: true,
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assertEquals(data.session_id, sessionId, 'Session ID mismatch');
    runner.assertEquals(data.consent_recorded, true, 'Consent not recorded');
  });

  await runner.test('POST /intake/confirm translates measurements → body shape profile', async () => {
    const { response, data } = await customer.json('POST', '/intake/confirm', {
      session_id: sessionId,
      manual_overrides: { bust: 88, waist: 70, hips: 102, height: 165 },
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const profile = data.shape_profile;
    runner.assertIsObject(profile, 'Missing shape_profile');
    runner.assert(SHAPE_CLASSES.includes(profile.shape_class), `Invalid shape_class: ${profile.shape_class}`);
    runner.assert(profile.shape_summary, 'Missing shape_summary');
    runner.assertIsObject(profile.comparisons_cm, 'Missing comparisons_cm');
    const sizes = profile.size_recommendation_by_category;
    runner.assertIsObject(sizes, 'Missing size_recommendation_by_category');
    runner.assert(SIZES.includes(sizes.tops), `Invalid tops size: ${sizes.tops}`);
  });

  await runner.test('POST /intake/preferences completes the profile', async () => {
    const { response, data } = await customer.json('POST', '/intake/preferences', {
      session_id: sessionId,
      preferred_colors: ['Ebony', 'Sky Captain'],
      preferred_silhouettes: ['fitted', 'flowing'],
      occasions: ['work', 'casual'],
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assertEquals(data.status, 'complete', 'Session should be complete');
    runner.assertEquals(data.intake_complete, true, 'intake_complete should be true');
  });

  await runner.test('GET /recommendations/{session_id} returns matching products', async () => {
    const { response, data } = await customer.json('GET', `/recommendations/${sessionId}?k=10`);
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assert(Array.isArray(data.recommendations), 'recommendations should be array');
    runner.assert(data.recommendations.length > 0, 'Should have recommendations');
    const rec = data.recommendations[0];
    runner.assert(rec.sku, 'Missing SKU');
    runner.assert(rec.name, 'Missing name');
    runner.assert(rec.category, 'Missing category');
    runner.assert(rec.price !== undefined, 'Missing price');
    runner.assert(Array.isArray(rec.colors), 'colors should be array');
    runner.assert(Array.isArray(rec.sizes), 'sizes should be array');
  });

  await runner.test('GET /new-releases/{session_id} returns matched new products', async () => {
    const { response, data } = await customer.json('GET', `/new-releases/${sessionId}?limit=10`);
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assert(Array.isArray(data), 'Response should be array');
    // The latest drop counts as new even between collections, so a real
    // catalog never leaves this down to a single fallback item.
    runner.assert(data.length >= 3, `Expected several new releases, got ${data.length}`);
    const item = data[0];
    runner.assert(item.sku, 'Missing SKU');
    runner.assertInRange(item.match_score, 0, 1, 'match_score should be 0-1');
    runner.assert(Array.isArray(item.matched_attributes), 'matched_attributes should be array');
    runner.assert(item.reason, 'Missing reason');
  });

  await runner.test('GET /account/profile returns the finished profile', async () => {
    const { response, data } = await customer.json('GET', '/account/profile');
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assertEquals(data && data.session_id, sessionId, 'Account should show this session');
  });
}

// ============================================================================
// Body Shape Tests
// ============================================================================

async function testBodyShape(runner) {
  console.log('\n📐 BODY SHAPE TESTS\n');

  const customer = await Customer.create('shape');

  // The reported case: equal bust and hips used to be classified pear.
  await runner.test('Equal bust and hips are never classified pear', async () => {
    const { shapeProfile } = await customer.completedSession({ bust: 107, waist: 90, hips: 107, height: 165 });
    runner.assert(shapeProfile.shape_class !== 'pear', `Got ${shapeProfile.shape_class}`);
    runner.assert(!/hips are \d+ cm fuller/i.test(shapeProfile.shape_summary),
      `Summary contradicts the measurements: ${shapeProfile.shape_summary}`);
    runner.assertEquals(shapeProfile.comparisons_cm.bust_minus_hips, 0, 'bust - hips should be 0');
    runner.assert(!('shoulder_hip' in shapeProfile.ratios), 'No invented shoulder/hip ratio');
  });

  await runner.test('Hips distinctly fuller than the bust is classified pear', async () => {
    const { shapeProfile } = await customer.completedSession({ bust: 84, waist: 66, hips: 102, height: 165 });
    runner.assertEquals(shapeProfile.shape_class, 'pear', 'Shape');
    runner.assert(/hips are 18 cm fuller than your bust/i.test(shapeProfile.shape_summary),
      `Summary should state the difference: ${shapeProfile.shape_summary}`);
  });

  await runner.test('A retired occasion from a stale page is dropped, not rejected', async () => {
    const sessionId = await customer.consentedSession();
    await customer.request('POST', '/intake/confirm', {
      session_id: sessionId, manual_overrides: { bust: 90, waist: 72, hips: 98, height: 165 },
    });
    const { response } = await customer.json('POST', '/intake/preferences', {
      session_id: sessionId, preferred_colors: ['Ebony'], occasions: ['gym'],
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
  });
}

// ============================================================================
// Measurement Limits Tests
// ============================================================================

async function testMeasurementLimits(runner) {
  console.log('\n📊 MEASUREMENT LIMITS TESTS\n');

  const limits = formLimits();
  const customer = await Customer.create('limits');
  const typical = { bust: 90, waist: 72, hips: 98, height: 165 };

  async function confirm(overrides) {
    const sessionId = await customer.consentedSession();
    return customer.request('POST', '/intake/confirm', {
      session_id: sessionId, manual_overrides: { ...typical, ...overrides },
    });
  }

  for (const [field, { min, max }] of Object.entries(limits)) {
    await runner.test(`API accepts ${field} at the form's limits (${min}-${max} cm)`, async () => {
      const low = await confirm({ [field]: min });
      runner.assert(low.ok, `${field}=${min} rejected (${low.status})`);
      const high = await confirm({ [field]: max });
      runner.assert(high.ok, `${field}=${max} rejected (${high.status})`);
    });

    await runner.test(`API rejects ${field} just outside the form's limits`, async () => {
      const below = await confirm({ [field]: min - 1 });
      runner.assertEquals(below.status, 400, `${field}=${min - 1} should be rejected`);
      const above = await confirm({ [field]: max + 1 });
      runner.assertEquals(above.status, 400, `${field}=${max + 1} should be rejected`);
    });
  }
}

// ============================================================================
// Photo Measurement Tests
// ============================================================================

async function testPhotoMeasurement(runner) {
  console.log('\n📷 PHOTO MEASUREMENT TESTS\n');

  const customer = await Customer.create('photo');

  await runner.test('Photo measurement requires the usual sizes', async () => {
    const sessionId = await customer.consentedSession();
    for (const sizes of [{}, { top: 'S' }, { bottom: 'S' }, { top: 'S', bottom: 'huge' }]) {
      const { response, data } = await customer.photoScan(sessionId, sizes);
      runner.assertEquals(response.status, 400, `Sizes ${JSON.stringify(sizes)} should be refused`);
      runner.assert(/sizes you usually wear/.test(data && data.detail), `Unexpected message: ${data && data.detail}`);
    }
  });

  await runner.test('A real photo is measured within the stated sizes', async () => {
    const sessionId = await customer.consentedSession();
    const { response, data } = await customer.photoScan(sessionId, { top: 'S', bottom: 'S' });
    runner.assert(response.ok, `Expected 200, got ${response.status}: ${data && data.detail}`);
    const m = data.measurements;
    runner.assertEquals(m.height, 170, 'Stated height should be kept');
    const sizes = data.shape_profile.size_recommendation_by_category;
    runner.assertEquals(sizes.tops, 'S', 'Stated top size should be kept');
    runner.assertEquals(sizes.skirts, 'S', 'Stated bottom size should be kept');
  });
}

// ============================================================================
// Update Style Tests
// ============================================================================

async function testUpdatingAFinishedProfile(runner) {
  console.log('\n✏️  UPDATE STYLE TESTS\n');

  const customer = await Customer.create('update');
  const { sessionId } = await customer.completedSession({ bust: 90, waist: 72, hips: 98, height: 165 });

  // Update Style: re-measure the finished session, then leave part-way.
  const rescan = await customer.photoScan(sessionId, { top: 'M', bottom: 'M', heightCm: 172 });

  await runner.test('Re-measuring a finished profile keeps it available', async () => {
    runner.assert(rescan.response.ok, `Re-scan failed (${rescan.response.status})`);
    const { data } = await customer.json('GET', '/account/profile');
    runner.assertEquals(data && data.session_id, sessionId, 'Account lost the profile');
    runner.assertEquals(data.measurements.height, 172, 'Account should show the new measurements');
  });

  await runner.test('Recommendations, new releases and fit checks keep working mid-edit', async () => {
    const recs = await customer.json('GET', `/recommendations/${sessionId}?k=1`);
    runner.assert(recs.response.ok, `Recommendations ${recs.response.status}`);
    const releases = await customer.request('GET', `/new-releases/${sessionId}?limit=5`);
    runner.assert(releases.ok, `New releases ${releases.status}`);
    const sku = recs.data.recommendations[0].sku;
    const fit = await customer.request('POST', `/fit-check/${sessionId}/${sku}`);
    runner.assert(fit.ok, `Fit check ${fit.status}`);
  });
}

// ============================================================================
// Fit Checker Tests
// ============================================================================

async function testFitChecker(runner) {
  console.log('\n✅ FIT CHECKER TESTS\n');

  const customer = await Customer.create('fit');
  const { sessionId, shapeProfile } = await customer.completedSession(
    { bust: 88, waist: 70, hips: 102, height: 165 });
  const recs = await customer.json('GET', `/recommendations/${sessionId}?k=1`);
  const product = recs.data.recommendations[0];

  await runner.test('Fit-check recommends the size shown on the profile', async () => {
    const { response, data } = await customer.json('POST', `/fit-check/${sessionId}/${product.sku}`);
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assert(SIZES.includes(data.recommended_size), `Invalid size: ${data.recommended_size}`);
    runner.assertInRange(data.confidence, 0, 1, 'confidence out of range');
    runner.assert(typeof data.fit_scores === 'object', 'fit_scores should be object');
    runner.assert(Array.isArray(data.fit_notes), 'fit_notes should be array');
    const key = { Skirts: 'skirts', Trousers: 'trousers', Dresses: 'dresses', Vests: 'vests', Tops: 'tops' }[product.category];
    if (key) {
      runner.assertEquals(data.recommended_size, shapeProfile.size_recommendation_by_category[key],
        'Fit check disagrees with the profile');
    }
  });

  await runner.test('Fit feedback submission', async () => {
    const { response, data } = await customer.json('POST', '/feedback/fit', {
      user_id: customer.userId,
      fit_check_id: `check-${sessionId}-${product.sku}`,
      product_sku: product.sku,
      feedback_type: 'perfect',
      actual_size: 'M',
      notes: 'Fit perfectly as recommended',
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    runner.assertEquals(data.saved, true, 'Feedback should be saved');
  });
}

// ============================================================================
// Main Test Runner
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(80));
  console.log('FRONTEND INTEGRATION TEST SUITE');
  console.log(`API: ${API_BASE}`);
  console.log('='.repeat(80) + '\n');

  const runner = new TestRunner();

  try {
    await testAPIIntegration(runner);
    await testBodyShape(runner);
    await testMeasurementLimits(runner);
    await testPhotoMeasurement(runner);
    await testUpdatingAFinishedProfile(runner);
    await testFitChecker(runner);

    const { failed } = runner.summary();

    console.log('DETAILED RESULTS:\n');
    runner.results.forEach(result => {
      if (result.reason) {
        console.log(`${result.status} ${result.name}\n   └─ ${result.reason}\n`);
      } else {
        console.log(`${result.status} ${result.name}`);
      }
    });

    if (failed === 0) {
      console.log('\n✅ ALL TESTS PASSED');
      process.exit(0);
    } else {
      console.log(`\n❌ ${failed} TEST(S) FAILED - Review results above`);
      process.exit(1);
    }
  } catch (error) {
    console.error('Fatal error:', error.message);
    process.exit(1);
  }
}

runAllTests();
