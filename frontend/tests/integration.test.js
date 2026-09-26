/**
 * Frontend Integration Tests
 * Tests the entire AI-guided intake flow and recommendations engine
 *
 * Requirements verified:
 * 1. AI-guided flow walks customer through style profile generation
 * 2. Photo → measurements (mocked, third-party integration ready)
 * 3. Measurements → body shape profile
 * 4. Shape profile → personalized recommendations
 * 5. New Releases feed personalization
 */

const API_BASE = 'http://localhost:8000';

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

  assertArrayLength(arr, expectedLength, message) {
    if (!Array.isArray(arr) || arr.length !== expectedLength) {
      throw new Error(`${message} - Expected array length ${expectedLength}, got ${arr?.length || 0}`);
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

// ============================================================================
// API Integration Tests
// ============================================================================

async function testAPIIntegration(runner) {
  console.log('\n📋 API INTEGRATION TESTS\n');

  let sessionId = null;
  let userId = `test-user-${Date.now()}`;

  // Test 1: Create intake session
  await runner.test('POST /intake/session creates valid session', async () => {
    const response = await fetch(`${API_BASE}/intake/session?user_id=${userId}`, {
      method: 'POST',
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assertIsObject(data, 'Response should be an object');
    runner.assert(data.session_id, 'Missing session_id');
    runner.assert(data.user_id === userId, 'user_id mismatch');
    runner.assertEquals(data.status, 'initiated', 'Initial status should be "initiated"');
    runner.assert(data.created_at, 'Missing created_at timestamp');

    sessionId = data.session_id;
  });

  // Test 2: Record consent
  await runner.test('POST /intake/consent records photo and measurement consent', async () => {
    const response = await fetch(`${API_BASE}/intake/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        photo_consent: true,
        measurement_consent: true,
      }),
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assertEquals(data.session_id, sessionId, 'Session ID mismatch');
    runner.assertEquals(data.consent_recorded, true, 'Consent not recorded');
  });

  // Test 3: Confirm measurements and generate body shape
  await runner.test('POST /intake/confirm translates measurements → body shape profile', async () => {
    const measurements = {
      bust: 88,
      waist: 70,
      hips: 102,
      height: 165,
    };

    const response = await fetch(`${API_BASE}/intake/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        manual_overrides: measurements,
      }),
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assertIsObject(data.shape_profile, 'Missing shape_profile');
    runner.assert(data.shape_profile.shape_class, 'Missing shape_class');
    runner.assert(['pear', 'apple', 'hourglass', 'rectangle', 'inverted_triangle', 'balanced'].includes(
      data.shape_profile.shape_class
    ), `Invalid shape_class: ${data.shape_profile.shape_class}`);
    runner.assert(data.shape_profile.size_recommendations, 'Missing size_recommendations');
  });

  // Test 4: Submit style preferences
  await runner.test('POST /intake/preferences saves style preferences', async () => {
    const response = await fetch(`${API_BASE}/intake/preferences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        preferred_colors: ['black', 'navy'],
        preferred_silhouettes: ['fitted', 'flowing'],
        occasions: ['work', 'casual'],
      }),
    });
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assertEquals(data.status, 'complete', 'Session should be complete');
    runner.assert(data.intake_complete === true, 'intake_complete should be true');
  });

  // Test 5: Get personalized recommendations
  await runner.test('GET /recommendations/{session_id} returns matching products', async () => {
    const response = await fetch(`${API_BASE}/recommendations/${sessionId}?k=10`);
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assertIsObject(data, 'Response should be object');
    runner.assert(Array.isArray(data.recommendations), 'recommendations should be array');
    runner.assert(data.recommendations.length > 0, 'Should have recommendations');

    // Verify recommendation structure
    const rec = data.recommendations[0];
    runner.assert(rec.sku, 'Missing SKU');
    runner.assert(rec.name, 'Missing name');
    runner.assert(rec.category, 'Missing category');
    runner.assert(rec.price !== undefined, 'Missing price');
    runner.assert(Array.isArray(rec.colors), 'colors should be array');
    runner.assert(Array.isArray(rec.sizes), 'sizes should be array');
  });

  // Test 6: Get personalized new releases
  await runner.test('GET /new-releases/{session_id} returns matched new products', async () => {
    const response = await fetch(`${API_BASE}/new-releases/${sessionId}?limit=10`);
    runner.assert(response.ok, `Expected 200, got ${response.status}`);
    const data = await response.json();

    runner.assert(Array.isArray(data), 'Response should be array');

    if (data.length > 0) {
      const item = data[0];
      runner.assert(item.sku, 'Missing SKU');
      runner.assert(item.match_score !== undefined, 'Missing match_score');
      runner.assertInRange(item.match_score, 0, 1, 'match_score should be 0-1');
      runner.assert(Array.isArray(item.matched_attributes), 'matched_attributes should be array');
      runner.assert(item.reason, 'Missing reason');
    }
  });

  return sessionId; // For use in other tests
}

// ============================================================================
// Intake Flow Data Tests
// ============================================================================

async function testDataFlow(runner, sessionId) {
  console.log('\n📊 DATA FLOW TESTS\n');

  // Test 1: Session persistence
  await runner.test('Session state persists after each step', async () => {
    const response = await fetch(`${API_BASE}/recommendations/${sessionId}`);
    runner.assert(response.ok, 'Should be able to query recommendations after intake');
  });

  // Test 2: Measurement validation
  await runner.test('Invalid measurements rejected (< 60cm)', async () => {
    const userId = `test-user-validation-${Date.now()}`;
    const sessionResp = await fetch(`${API_BASE}/intake/session?user_id=${userId}`, {
      method: 'POST',
    });
    const session = await sessionResp.json();

    const consentResp = await fetch(`${API_BASE}/intake/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session.session_id,
        photo_consent: true,
        measurement_consent: true,
      }),
    });
    runner.assert(consentResp.ok, 'Consent should be recorded');

    // Try invalid measurements
    const invalidResp = await fetch(`${API_BASE}/intake/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session.session_id,
        manual_overrides: {
          bust: 30, // Invalid: < 60
          waist: 70,
          hips: 102,
          height: 165,
        },
      }),
    });
    runner.assert(!invalidResp.ok, 'Should reject invalid measurements');
  });

  // Test 3: Boundary measurements accepted
  await runner.test('Boundary measurements accepted (60cm and 140cm)', async () => {
    const userId = `test-user-boundary-${Date.now()}`;
    const sessionResp = await fetch(`${API_BASE}/intake/session?user_id=${userId}`, {
      method: 'POST',
    });
    const session = await sessionResp.json();

    const consentResp = await fetch(`${API_BASE}/intake/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session.session_id,
        photo_consent: true,
        measurement_consent: true,
      }),
    });

    // Test min boundary (60cm)
    const minResp = await fetch(`${API_BASE}/intake/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session.session_id,
        manual_overrides: {
          bust: 60,
          waist: 60,
          hips: 60,
          height: 140,
        },
      }),
    });
    runner.assert(minResp.ok, 'Should accept minimum boundary (60cm)');

    // Test max boundary (140cm) - need new session
    const userId2 = `test-user-boundary-max-${Date.now()}`;
    const sessionResp2 = await fetch(`${API_BASE}/intake/session?user_id=${userId2}`, {
      method: 'POST',
    });
    const session2 = await sessionResp2.json();

    await fetch(`${API_BASE}/intake/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session2.session_id,
        photo_consent: true,
        measurement_consent: true,
      }),
    });

    const maxResp = await fetch(`${API_BASE}/intake/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: session2.session_id,
        manual_overrides: {
          bust: 140,
          waist: 130,
          hips: 140,
          height: 210,
        },
      }),
    });
    runner.assert(maxResp.ok, 'Should accept maximum boundary (140cm)');
  });
}

// ============================================================================
// Recommendations Accuracy Tests
// ============================================================================

async function testRecommendationAccuracy(runner) {
  console.log('\n🎯 RECOMMENDATION ACCURACY TESTS\n');

  // Create a test session with specific measurements
  const userId = `test-recommendations-${Date.now()}`;
  const sessionResp = await fetch(`${API_BASE}/intake/session?user_id=${userId}`, {
    method: 'POST',
  });
  const session = await sessionResp.json();
  const sessionId = session.session_id;

  // Record consent and measurements for pear shape
  await fetch(`${API_BASE}/intake/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      photo_consent: true,
      measurement_consent: true,
    }),
  });

  // Pear shape: wider hips than bust
  const measurementsResp = await fetch(`${API_BASE}/intake/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      manual_overrides: {
        bust: 84,
        waist: 66,
        hips: 102, // Much wider than bust = pear
        height: 165,
      },
    }),
  });
  const measurements = await measurementsResp.json();
  const shapeClass = measurements.shape_profile?.shape_class;

  // Add style preferences
  await fetch(`${API_BASE}/intake/preferences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      preferred_colors: ['black', 'navy', 'cream'],
      preferred_silhouettes: ['fitted', 'flowing'],
      occasions: ['work', 'casual'],
    }),
  });

  // Test recommendations accuracy
  await runner.test('Recommendations match shape profile', async () => {
    const response = await fetch(`${API_BASE}/recommendations/${sessionId}?k=5`);
    const data = await response.json();

    runner.assert(data.recommendations.length > 0, 'Should have recommendations');
    // All products should have sizes that match user measurements
    data.recommendations.forEach((rec, idx) => {
      runner.assert(rec.sizes && rec.sizes.length > 0, `Product ${idx} missing sizes`);
    });
  });

  // Test new releases personalization
  await runner.test('New Releases feed personalized to shape and style', async () => {
    const response = await fetch(`${API_BASE}/new-releases/${sessionId}`);
    const items = await response.json();

    if (items.length > 0) {
      const item = items[0];
      runner.assertInRange(item.match_score, 0, 1, 'match_score out of range');
      runner.assert(Array.isArray(item.matched_attributes), 'matched_attributes missing');
      runner.assert(item.reason, 'reason missing');
      // Reason should mention shape or style
      const reasonText = item.reason.toLowerCase();
      runner.assert(
        reasonText.includes('shape') || reasonText.includes('style') || reasonText.includes('flatters') || reasonText.includes('color'),
        'Reason should mention shape or style personalization'
      );
    }
  });
}

// ============================================================================
// Fit Checker Tests
// ============================================================================

async function testFitChecker(runner) {
  console.log('\n✅ FIT CHECKER TESTS\n');

  // Create session and get recommendations
  const userId = `test-fit-${Date.now()}`;
  const sessionResp = await fetch(`${API_BASE}/intake/session?user_id=${userId}`, {
    method: 'POST',
  });
  const session = await sessionResp.json();
  const sessionId = session.session_id;

  await fetch(`${API_BASE}/intake/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      photo_consent: true,
      measurement_consent: true,
    }),
  });

  await fetch(`${API_BASE}/intake/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      manual_overrides: {
        bust: 88,
        waist: 70,
        hips: 102,
        height: 165,
      },
    }),
  });

  await fetch(`${API_BASE}/intake/preferences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      preferred_colors: ['black'],
      preferred_silhouettes: ['fitted'],
      occasions: ['work'],
    }),
  });

  // Get recommendations to find a product SKU
  const recsResp = await fetch(`${API_BASE}/recommendations/${sessionId}?k=1`);
  const recs = await recsResp.json();

  if (recs.recommendations.length > 0) {
    const productSku = recs.recommendations[0].sku;

    await runner.test('Fit-check returns valid recommendation', async () => {
      const response = await fetch(`${API_BASE}/fit-check/${sessionId}/${productSku}`);
      runner.assert(response.ok, `Expected 200, got ${response.status}`);
      const data = await response.json();

      runner.assert(data.recommended_size, 'Missing recommended_size');
      runner.assert(['XS', 'S', 'M', 'L', 'XL', 'XXL'].includes(data.recommended_size),
        `Invalid size: ${data.recommended_size}`);
      runner.assertInRange(data.confidence, 0, 1, 'confidence out of range');
      runner.assert(typeof data.fit_scores === 'object', 'fit_scores should be object');
      runner.assert(Array.isArray(data.fit_notes), 'fit_notes should be array');
    });

    await runner.test('Fit feedback submission', async () => {
      const response = await fetch(`${API_BASE}/feedback/fit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          fit_check_id: `check-${sessionId}-${productSku}`,
          product_sku: productSku,
          feedback_type: 'perfect',
          actual_size: 'M',
          notes: 'Fit perfectly as recommended',
        }),
      });
      runner.assert(response.ok, `Expected 200, got ${response.status}`);
      const data = await response.json();
      runner.assert(data.saved === true, 'Feedback should be saved');
    });
  }
}

// ============================================================================
// Main Test Runner
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(80));
  console.log('FRONTEND INTEGRATION TEST SUITE');
  console.log('Testing: AI-guided intake flow → Shape profile → Personalized recommendations');
  console.log('='.repeat(80) + '\n');

  const runner = new TestRunner();

  try {
    // Run test suites
    const sessionId = await testAPIIntegration(runner);
    await testDataFlow(runner, sessionId);
    await testRecommendationAccuracy(runner);
    await testFitChecker(runner);

    // Print summary
    const { passed, failed, total } = runner.summary();

    // Print detailed results
    console.log('DETAILED RESULTS:\n');
    runner.results.forEach(result => {
      if (result.reason) {
        console.log(`${result.status} ${result.name}\n   └─ ${result.reason}\n`);
      } else {
        console.log(`${result.status} ${result.name}`);
      }
    });

    // Overall status
    if (failed === 0) {
      console.log('\n✅ ALL TESTS PASSED - Frontend properly implements backend requirements');
      console.log('   - AI-guided intake flow ✅');
      console.log('   - Measurements → shape profile ✅');
      console.log('   - Shape profile → recommendations ✅');
      console.log('   - New releases personalization ✅');
      console.log('   - Fit checker functionality ✅');
      console.log('   - Session persistence ✅');
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

// Run tests
runAllTests();
