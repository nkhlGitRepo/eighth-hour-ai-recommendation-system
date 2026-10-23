/*
 * MyStyle -- Eighth Hour's styling engine, in the store's theme.
 *
 * Config comes from snippets/mystyle-config.liquid (window.MyStyleConfig): the
 * API address, the signed-in customer's token (Liquid signs it server-side; a
 * guest has none), the sign-in URL and the brand's launch data.
 *
 * What it drives, wherever the markup is on the page:
 *   [data-mystyle-page]   the My Style page: quiz, profile, Picked for you, New for you
 *   [data-mystyle-fit]    Find my size, on product pages
 *   [data-mystyle-picks]  Picked for you, on the home page
 *
 * Products are read from the store itself (/products.json), in the shopper's
 * browser, and sent with each request -- so prices, stock and newly uploaded
 * pieces are always the store's own. Only first-drop pieces (by SKU, from the
 * launch data) are sent; the API checks again.
 */
(function () {
  'use strict';

  var C = window.MyStyleConfig;
  if (!C || window.MyStyle) return;

  var SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL'];
  var SIZE_LABELS = { tops: 'tops', skirts: 'skirts', dresses: 'dresses', trousers: 'trousers', vests: 'vests', coOrds: 'co-ords' };
  var SILHOUETTES = [['fitted', 'Fitted'], ['flowing', 'Flowing'], ['straight', 'Straight'], ['a_line', 'A-Line'], ['oversized', 'Oversized']];
  var OCCASIONS = [['work', 'Work'], ['casual', 'Casual'], ['evening', 'Evening'], ['weekend', 'Weekend']];
  var RANGES_CM = { bust: [70, 150], waist: [55, 130], hips: [80, 160], height: [140, 210] };
  var PHOTO_LONGEST_SIDE_PX = 1600;
  var BACKUP_KEY = 'mystyle:profile:' + (C.customerId || 'guest');
  var SLOW_MS = 4000;

  // ------------------------------------------------------------------ helpers

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function el(html) {
    var t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  function saved(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { return null; }
  }
  function capitalize(text) { return String(text || '').replace(/^./, function (c) { return c.toUpperCase(); }); }

  // The engine works in cm; everything she reads is in the unit she measures in
  // (inches on this US store, unless she switches the quiz to cm).
  function unitPref() { return saved('mystyle:unit') || C.defaultUnit || 'in'; }
  function length(cm, unit) {
    if (unit !== 'in') return (Math.round(cm * 10) / 10) + ' cm';
    if (cm >= 120) {   // a height (hers or the fit model's): feet and inches
      var inches = Math.round(cm / 2.54);
      return Math.floor(inches / 12) + ' ft ' + (inches % 12) + ' in';
    }
    var halves = Math.round(cm / 2.54 * 2);
    if (!halves) return 'under ½ in';
    return (Math.floor(halves / 2) || '') + (halves % 2 ? '½' : '') + ' in';
  }
  function inUnit(text, unit) {
    unit = unit || unitPref();
    return String(text || '').replace(/(\d+(?:\.\d+)?) ?cm\b/g, function (m, cm) { return length(parseFloat(cm), unit); });
  }
  function signInUrl() {
    var back = window.location.pathname + window.location.search;
    return C.loginUrl + (C.loginUrl.indexOf('?') === -1 ? '?' : '&') + 'return_url=' + encodeURIComponent(back);
  }

  // ---------------------------------------------------------------------- API

  function MyStyleError(message, status) { this.message = message; this.status = status; }

  var token = C.token || null;

  function freshToken() {
    return fetch(C.tokenUrl + (C.tokenUrl.indexOf('?') === -1 ? '?' : '&') + '_=' + Date.now(), { credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (text) { token = (JSON.parse(text) || {}).token || null; return token; })
      .catch(function () { return null; });
  }

  // opts: method, body (JSON), form (FormData), onSlow (called once if the API
  // is slow -- it sleeps when idle on its current hosting).
  function api(path, opts, retried) {
    opts = opts || {};
    var headers = {};
    if (token) headers['X-MyStyle-Customer'] = token;
    var init = { method: opts.method || 'GET', headers: headers };
    if (opts.form) init.body = opts.form;
    else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    var slow = opts.onSlow ? setTimeout(opts.onSlow, SLOW_MS) : null;
    return fetch(C.apiBase + path, init).then(function (res) {
      if (slow) clearTimeout(slow);
      if (res.status === 401 && token && !retried) {
        return freshToken().then(function () { return api(path, opts, true); });
      }
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) throw new MyStyleError(data.detail || 'Something went wrong. Please try again.', res.status);
        return data;
      });
    }, function () {
      if (slow) clearTimeout(slow);
      throw new MyStyleError('We couldn’t reach My Style just now. Please try again in a moment.', 0);
    });
  }

  // ----------------------------------------------------------------- products

  var launchSkus = {};
  (C.launch && C.launch.styles || []).forEach(function (style) {
    (style.skus || []).forEach(function (sku) { launchSkus[String(sku).toUpperCase()] = true; });
  });

  function slimProduct(p) {
    var tags = Array.isArray(p.tags) ? p.tags : String(p.tags || '').split(',');
    return {
      handle: p.handle,
      title: p.title,
      tags: tags.map(function (t) { return String(t).trim(); }).filter(Boolean),
      body: String(p.body_html || p.description || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 2000),
      published_at: p.published_at,
      options: (p.options || []).map(function (o) { return typeof o === 'string' ? { name: o } : { name: o.name, values: o.values }; }),
      variants: (p.variants || []).map(function (v) {
        return { sku: v.sku || '', available: !!v.available, options: [v.option1, v.option2, v.option3].filter(function (x) { return x != null; }) };
      })
    };
  }
  function isLaunchProduct(p) {
    return (p.variants || []).some(function (v) { return launchSkus[String(v.sku || '').toUpperCase()]; });
  }

  var productsPromise = null;
  function storeProducts() {
    if (!productsPromise) {
      productsPromise = (function load(page, found) {
        return fetch(C.rootUrl + 'products.json?limit=250&page=' + page, { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : { products: [] }; })
          .then(function (data) {
            var products = data.products || [];
            products.filter(isLaunchProduct).forEach(function (p) { found.push(slimProduct(p)); });
            return products.length === 250 && page < 8 ? load(page + 1, found) : found;
          });
      })(1, []).catch(function () { return []; });
    }
    return productsPromise;
  }

  // ------------------------------------------------------------------ profile

  var profilePromise = null;
  function loadProfile(onSlow) {
    if (!token) return Promise.resolve(null);
    if (!profilePromise) {
      profilePromise = api('/shopify/profile', { onSlow: onSlow }).then(function (data) {
        if (data.profile) return data.profile;
        var backup = saved(BACKUP_KEY);
        if (!backup) return null;
        // The API lost its copy (its hosting resets): rebuild from the
        // encrypted backup kept in this browser.
        return api('/shopify/restore', { method: 'POST', body: { profile_token: backup }, onSlow: onSlow })
          .then(function (r) { return r.profile; })
          .catch(function (err) { if (err.status === 401) saved(BACKUP_KEY, null); return null; });
      });
      profilePromise.catch(function () { profilePromise = null; });
    }
    return profilePromise;
  }
  function rememberProfile(profile) {
    if (profile && profile.profile_token) saved(BACKUP_KEY, profile.profile_token);
    profilePromise = Promise.resolve(profile);
  }

  // -------------------------------------------------------------------- cards

  // The theme's own product card, via the Section Rendering API, so a
  // recommendation looks exactly like any other product on the site and shows
  // Shopify's own price for this shopper's market.
  function renderCards(list, items, emptyText) {
    list.innerHTML = '';
    if (!items.length) {
      list.appendChild(el('<li class="mystyle-empty">' + esc(emptyText) + '</li>'));
      return Promise.resolve();
    }
    return Promise.all(items.map(function (item) {
      return fetch(C.rootUrl + 'products/' + encodeURIComponent(item.handle) + '?section_id=mystyle-card', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.text() : null; })
        .catch(function () { return null; })
        .then(function (html) { return { item: item, html: html }; });
    })).then(function (cards) {
      cards.forEach(function (card) {
        if (!card.html) return;                  // not available in this market
        var li = el('<li class="grid__item mystyle-card"></li>');
        var doc = new DOMParser().parseFromString(card.html, 'text/html');
        var section = doc.querySelector('.shopify-section') || doc.body;
        li.innerHTML = section.innerHTML;
        var item = card.item;
        var note = item.size_note || (item.recommended_size ? 'Your size: ' + item.recommended_size : '');
        if (item.reason) li.appendChild(el('<p class="mystyle-card__reason">' + esc(inUnit(item.reason)) + '</p>'));
        if (note) li.appendChild(el('<p class="mystyle-card__size' + (item.closest_available ? ' is-closest' : '') + '">' + esc(inUnit(note)) + '</p>'));
        if (item.in_stock_in_size === false) li.appendChild(el('<p class="mystyle-card__stock">Sold out in this size</p>'));
        list.appendChild(li);
      });
      if (!list.children.length) list.appendChild(el('<li class="mystyle-empty">' + esc(emptyText) + '</li>'));
    });
  }

  function loadPicks(profile, list, k, onSlow) {
    return storeProducts().then(function (products) {
      return api('/shopify/recommendations', {
        method: 'POST', onSlow: onSlow,
        body: { session_id: profile.session_id, k: k, products: products, launch: C.launch }
      });
    }).then(function (data) {
      return renderCards(list, data.recommendations, 'Your picks will appear here as the new collection arrives.');
    });
  }
  function loadNew(profile, list, limit, onSlow) {
    return storeProducts().then(function (products) {
      return api('/shopify/new-releases', {
        method: 'POST', onSlow: onSlow,
        body: { session_id: profile.session_id, limit: limit, products: products, launch: C.launch }
      });
    }).then(function (data) {
      return renderCards(list, data.items.map(function (i) {
        var a = i.availability || {};
        return { handle: i.handle, reason: i.reason, recommended_size: a.recommended_size,
                 closest_available: a.closest_available, size_note: a.size_note };
      }), 'New pieces matched to you will appear here.');
    });
  }

  // ------------------------------------------------------------ find my size

  function selectSize(scope, size) {
    var form = scope.closest('product-info, .product, main') || document;
    var inputs = form.querySelectorAll('input[type="radio"]');
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (/^size/i.test(input.name || '') && input.value === size && !input.disabled) {
        input.click();
        return true;
      }
    }
    var selects = form.querySelectorAll('select');
    for (var j = 0; j < selects.length; j++) {
      var select = selects[j];
      if (!/size/i.test(select.name || select.id || '')) continue;
      for (var k = 0; k < select.options.length; k++) {
        if (select.options[k].value === size) {
          select.value = size;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
      }
    }
    return false;
  }

  function initFit(box) {
    var product;
    try { product = JSON.parse(box.querySelector('[data-mystyle-product]').textContent); } catch (e) { return; }
    if (!isLaunchProduct(product)) return;           // not a My Style piece
    var body = box.querySelector('[data-mystyle-fit-body]');
    box.hidden = false;

    if (!token) {
      body.innerHTML = '<p class="mystyle-fit__prompt"><a href="' + esc(signInUrl()) + '">Sign in</a> to see the size that fits you best.</p>';
      return;
    }
    body.innerHTML = '<p class="mystyle-muted">Finding your size…</p>';
    loadProfile(function () { body.innerHTML = '<p class="mystyle-muted">Waking up My Style — this can take up to a minute.</p>'; })
      .then(function (profile) {
        if (!profile) {
          body.innerHTML = '<p class="mystyle-fit__prompt"><a href="' + esc(C.pageUrl) + '">Build your style profile</a> to see the size that fits you best.</p>';
          return null;
        }
        return api('/shopify/fit-check', {
          method: 'POST',
          body: { session_id: profile.session_id, product: slimProduct(product), launch: C.launch }
        }).then(function (fit) { renderFit(box, body, fit); });
      })
      .catch(function (err) {
        if (err.status === 404) { box.hidden = true; return; }
        body.innerHTML = '<p class="mystyle-muted">' + esc(err.message) + '</p>';
      });
  }

  function renderFit(box, body, fit) {
    var size = fit.recommended_size;
    var label = fit.closest_available ? 'Closest available size' : 'Your size';
    var bars = SIZE_ORDER.filter(function (s) { return s in fit.fit_scores; }).map(function (s) {
      var pct = Math.round(fit.fit_scores[s] * 100);
      return '<li class="' + (s === size ? 'is-recommended' : '') + '"><span>' + esc(s) + '</span>' +
        '<span class="mystyle-bar"><span style="width:' + pct + '%"></span></span><span>' + pct + '%</span></li>';
    }).join('');
    body.innerHTML =
      '<div class="mystyle-fit__result">' +
        '<span class="mystyle-fit__label">' + esc(label) + '</span>' +
        '<span class="mystyle-fit__size">' + esc(size) + '</span>' +
        '<button type="button" class="mystyle-link" data-select-size>Select ' + esc(size) + '</button>' +
      '</div>' +
      (fit.in_stock_in_size === false ? '<p class="mystyle-fit__stock">' + esc(size) + ' is sold out right now.</p>' : '') +
      '<ul class="mystyle-fit__notes">' + fit.fit_notes.map(function (n) { return '<li>' + esc(inUnit(n)) + '</li>'; }).join('') + '</ul>' +
      '<details class="mystyle-fit__details"><summary>How each size fits you</summary><ul class="mystyle-bars">' + bars + '</ul></details>' +
      '<div class="mystyle-fit__feedback" data-feedback><span>Bought it? How did it fit?</span>' +
        '<button type="button" data-fit="too_tight">Too tight</button>' +
        '<button type="button" data-fit="perfect">Just right</button>' +
        '<button type="button" data-fit="too_loose">Too loose</button></div>';
    body.querySelector('[data-select-size]').addEventListener('click', function () {
      if (!selectSize(box, size)) this.textContent = 'Choose ' + size + ' above';
    });
    var feedback = body.querySelector('[data-feedback]');
    feedback.addEventListener('click', function (e) {
      var choice = e.target.closest('[data-fit]');
      if (!choice || !fit.check_id) return;
      api('/shopify/feedback', { method: 'POST', body: {
        fit_check_id: fit.check_id, product_handle: fit.product_sku, feedback_type: choice.dataset.fit } })
        .then(function () { feedback.innerHTML = '<span>Thanks — that helps us size the next piece.</span>'; })
        .catch(function (err) { feedback.innerHTML = '<span>' + esc(err.message) + '</span>'; });
    });
  }

  // ---------------------------------------------------------- home: picks

  function initPicks(section) {
    var list = section.querySelector('[data-mystyle-list]');
    var intro = section.querySelector('[data-mystyle-intro]');
    if (!token) {
      intro.innerHTML = 'Find your fit and pieces chosen for your shape. <a href="' + esc(signInUrl()) + '">Sign in</a> to start.';
      section.hidden = false;
      return;
    }
    loadProfile().then(function (profile) {
      section.hidden = false;
      if (!profile) {
        intro.innerHTML = 'Answer a few questions and we’ll pick pieces for your shape and style. <a href="' + esc(C.pageUrl) + '">Build your style profile</a>';
        return;
      }
      intro.textContent = 'Chosen for your ' + (profile.shape_profile.shape_class || '') + ' shape and your style.';
      return loadPicks(profile, list, Number(section.dataset.count) || 4);
    }).catch(function () { section.hidden = true; });
  }

  // --------------------------------------------------------- the My Style page

  function MyStylePage(root) {
    this.root = root;
    this.view = root.querySelector('[data-mystyle-view]');
    this.unit = unitPref();
    this.session = null;
    this.profile = null;
    this.photoNote = null;
  }

  MyStylePage.prototype.slow = function () {
    var status = this.root.querySelector('[data-mystyle-status]');
    if (status) status.textContent = 'Waking up My Style — this can take up to a minute the first time.';
  };

  MyStylePage.prototype.show = function (html) {
    this.view.innerHTML = html;
    this.root.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  MyStylePage.prototype.error = function (target, err) {
    var box = this.view.querySelector(target || '[data-mystyle-error]');
    if (box) { box.textContent = err.message || String(err); box.hidden = false; }
  };

  MyStylePage.prototype.start = function () {
    var self = this;
    if (!token) {
      this.show(
        '<div class="mystyle-panel mystyle-center">' +
          '<h2>Your personal style profile</h2>' +
          '<p>Tell us your measurements — or use a photo — and we’ll find your size in every piece and pick styles for your shape.</p>' +
          '<a class="button" href="' + esc(signInUrl()) + '">Sign in to start</a>' +
          '<p class="mystyle-muted">A style profile is saved to your Eighth Hour account.</p>' +
        '</div>');
      return;
    }
    this.show('<div class="mystyle-panel mystyle-center"><p class="mystyle-muted" data-mystyle-status>Loading your style profile…</p></div>');
    loadProfile(function () { self.slow(); }).then(function (profile) {
      if (profile) self.showProfile(profile); else self.showConsent();
    }).catch(function (err) {
      self.show('<div class="mystyle-panel"><p class="mystyle-error">' + esc(err.message) + '</p></div>');
    });
  };

  // Step 1: consent
  MyStylePage.prototype.showConsent = function () {
    var self = this;
    this.show(
      '<form class="mystyle-panel" data-step="consent">' +
        '<p class="mystyle-step">Step 1 of 4</p>' +
        '<h2>Before we start</h2>' +
        '<label class="mystyle-check"><input type="checkbox" name="photo" required> <span><strong>I consent to photo capture and measurement extraction.</strong> If you use a photo, we use it only to estimate your measurements. Your photo is not stored.</span></label>' +
        '<label class="mystyle-check"><input type="checkbox" name="measurements" required> <span><strong>I consent to using my measurements for personalized recommendations.</strong> Your measurements help us find your size and the styles that suit you.</span></label>' +
        '<p class="mystyle-muted">You can delete your style profile at any time from this page.</p>' +
        '<p class="mystyle-error" data-mystyle-error hidden></p>' +
        '<button class="button" type="submit">Continue</button>' +
      '</form>');
    this.view.querySelector('form').addEventListener('submit', function (e) {
      e.preventDefault();
      var button = this.querySelector('button');
      button.disabled = true;
      api('/shopify/session', { method: 'POST', body: { photo_consent: true, measurement_consent: true }, onSlow: function () { button.textContent = 'Waking up…'; } })
        .then(function (r) { self.session = r.session_id; self.showMeasurements(); })
        .catch(function (err) { button.disabled = false; button.textContent = 'Continue'; self.error(null, err); });
    });
  };

  // Step 2: measurements (typed, or estimated from a photo then checked)
  MyStylePage.prototype.toUnit = function (cm) { return this.unit === 'in' ? Math.round(cm / 2.54 * 2) / 2 : Math.round(cm * 10) / 10; };
  MyStylePage.prototype.toCm = function (value) { return this.unit === 'in' ? value * 2.54 : value; };
  MyStylePage.prototype.rangeText = function (field) {
    var r = RANGES_CM[field];
    return this.unit === 'in' ? Math.ceil(r[0] / 2.54) + '–' + Math.floor(r[1] / 2.54) + ' in' : r[0] + '–' + r[1] + ' cm';
  };

  MyStylePage.prototype.showMeasurements = function (values) {
    var self = this;
    values = values || this.lastMeasurements || {};
    var field = function (name, label, hint) {
      var v = values[name] != null ? self.toUnit(values[name]) : '';
      return '<label class="mystyle-field"><span>' + label + '</span>' +
        '<input type="number" step="0.5" inputmode="decimal" name="' + name + '" value="' + esc(v) + '" required>' +
        '<small>' + hint + ' (' + self.rangeText(name) + ')</small></label>';
    };
    var note = this.photoNote;
    this.photoNote = null;
    this.show(
      '<form class="mystyle-panel" data-step="measure" novalidate>' +
        '<p class="mystyle-step">Step 2 of 4</p>' +
        '<h2>Your measurements</h2>' +
        '<div class="mystyle-units" role="group" aria-label="Units">' +
          '<button type="button" data-unit="in"' + (this.unit === 'in' ? ' class="is-active"' : '') + '>inches</button>' +
          '<button type="button" data-unit="cm"' + (this.unit === 'cm' ? ' class="is-active"' : '') + '>cm</button></div>' +
        (note ? '<p class="mystyle-note is-' + note.tone + '">' + esc(note.text) + '</p>' : '') +
        '<div class="mystyle-fields">' +
          field('bust', 'Bust', 'Around the fullest part') +
          field('waist', 'Waist', 'Around your natural waist') +
          field('hips', 'Hips', 'Around the fullest part') +
          field('height', 'Height', 'Your total height') +
        '</div>' +
        '<p class="mystyle-error" data-mystyle-error hidden></p>' +
        '<button class="button" type="submit">See my shape profile</button>' +
        '<p class="mystyle-alt">Don’t know your measurements? <button type="button" class="mystyle-link" data-photo>Use a photo instead</button></p>' +
      '</form>');
    var form = this.view.querySelector('form');
    form.querySelectorAll('[data-unit]').forEach(function (b) {
      b.addEventListener('click', function () {
        var current = self.readMeasurements(form, true);
        self.unit = b.dataset.unit;
        saved('mystyle:unit', self.unit);
        self.showMeasurements(current);
      });
    });
    form.querySelector('[data-photo]').addEventListener('click', function () { self.showPhoto(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var values = self.readMeasurements(form, false);
      if (!values) return;
      var button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      api('/shopify/measurements', { method: 'POST', body: Object.assign({ session_id: self.session }, values), onSlow: function () { button.textContent = 'Waking up…'; } })
        .then(function (r) { self.lastMeasurements = values; self.showShape(r.shape_profile); })
        .catch(function (err) { button.disabled = false; button.textContent = 'See my shape profile'; self.error(null, err); });
    });
  };

  // Values in cm, or null (with the problem shown) when anything is missing or
  // out of range. lenient: keep whatever is there, for switching units.
  MyStylePage.prototype.readMeasurements = function (form, lenient) {
    var out = {};
    var problems = [];
    var self = this;
    Object.keys(RANGES_CM).forEach(function (name) {
      var raw = parseFloat(form.querySelector('[name="' + name + '"]').value);
      if (isNaN(raw)) { if (!lenient) problems.push(capitalize(name) + ' is needed'); return; }
      var cm = Math.round(self.toCm(raw) * 10) / 10;
      var r = RANGES_CM[name];
      if (!lenient && (cm < r[0] || cm > r[1])) problems.push(capitalize(name) + ' should be ' + self.rangeText(name));
      out[name] = cm;
    });
    if (problems.length) { this.error(null, { message: problems.join('. ') + '.' }); return null; }
    return out;
  };

  MyStylePage.prototype.showPhoto = function () {
    var self = this;
    var sizes = SIZE_ORDER.map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join('');
    var heightCm = this.lastMeasurements && this.lastMeasurements.height;
    this.show(
      '<form class="mystyle-panel" data-step="photo" novalidate>' +
        '<p class="mystyle-step">Step 2 of 4</p>' +
        '<h2>Measure from a photo</h2>' +
        '<div class="mystyle-disclosure" data-disclosure><p class="mystyle-muted">Loading privacy information…</p></div>' +
        ((this.root.querySelector('template[data-mystyle-framing]') || {}).innerHTML || '') +
        '<div class="mystyle-fields">' +
          '<label class="mystyle-field"><span>Full-body photo</span><input type="file" name="photo" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" required><small>JPEG, PNG, HEIC (iPhone) or WEBP</small></label>' +
          '<label class="mystyle-field"><span>Your height</span><input type="number" step="0.5" inputmode="decimal" name="height" value="' + (heightCm ? esc(this.toUnit(heightCm)) : '') + '" required><small>A photo alone can’t tell your scale (' + this.rangeText('height') + ')</small></label>' +
          '<label class="mystyle-field"><span>Usual size — tops</span><select name="top" required><option value="">Select</option>' + sizes + '</select><small>Used for your bust and waist</small></label>' +
          '<label class="mystyle-field"><span>Usual size — bottoms</span><select name="bottom" required><option value="">Select</option>' + sizes + '</select><small>Used for your hips and waist</small></label>' +
        '</div>' +
        '<p class="mystyle-muted">A photo can’t see body depth, so on its own it can be well off — your usual sizes keep your bust and hips grounded, the photo fine-tunes them, and your waist is worked out from your shape in the photo.</p>' +
        '<p class="mystyle-note"><strong>How accurate is this?</strong> Our image recognition estimates are accurate to an average of about 3 cm from your measured bust, waist and hips. Loose clothing hides your shape — especially your waist — and makes the estimate less accurate. You can check and edit every number before continuing.</p>' +
        '<label class="mystyle-check"><input type="checkbox" name="adult" required> <span>I’m 18 or older (or have a parent or guardian’s permission), and I understand my photo will be used only to estimate my measurements, as described above.</span></label>' +
        '<p class="mystyle-error" data-mystyle-error hidden></p>' +
        '<button class="button" type="submit">Scan photo</button>' +
        '<p class="mystyle-alt">Prefer not to upload a photo? <button type="button" class="mystyle-link" data-manual>Enter measurements instead</button></p>' +
      '</form>');
    var form = this.view.querySelector('form');
    form.querySelector('[data-manual]').addEventListener('click', function () { self.showMeasurements(); });
    api('/intake/photo-disclosure').then(function (d) {
      form.querySelector('[data-disclosure]').innerHTML =
        '<p><strong>Your photo:</strong> processed by ' + esc(d.processor_name) + '. ' + esc(d.retention) + '</p>';
    }).catch(function () {
      form.querySelector('[data-disclosure]').innerHTML = '<p>Your photo is used only to estimate your measurements and is not stored.</p>';
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var file = form.photo.files[0];
      var height = parseFloat(form.height.value);
      var problems = [];
      if (!file) problems.push('Choose a photo');
      if (isNaN(height)) problems.push('Height is needed');
      if (!form.top.value || !form.bottom.value) problems.push('Choose the sizes you usually wear');
      if (!form.adult.checked) problems.push('Please confirm the statement above the button');
      var heightCm = self.toCm(height);
      if (!isNaN(height) && (heightCm < RANGES_CM.height[0] || heightCm > RANGES_CM.height[1])) problems.push('Height should be ' + self.rangeText('height'));
      if (problems.length) { self.error(null, { message: problems.join('. ') + '.' }); return; }
      var button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      button.textContent = 'Estimating your measurements…';
      shrinkPhoto(file).then(function (photo) {
        var data = new FormData();
        data.append('session_id', self.session);
        data.append('height_cm', String(Math.round(heightCm * 10) / 10));
        data.append('photo', photo);
        data.append('usual_top_size', form.top.value);
        data.append('usual_bottom_size', form.bottom.value);
        return api('/intake/photo-measure', { method: 'POST', form: data, onSlow: function () { button.textContent = 'Still working — waking up My Style…'; } });
      }).then(function (r) {
        var m = r.measurements || {};
        var checkable = (r.low_confidence_fields || []).filter(function (f) { return f in RANGES_CM; });
        self.photoNote = checkable.length
          ? { tone: 'caution', text: 'We estimated these from your photo, but weren’t fully confident about: ' + checkable.join(', ') + '. Please check them before continuing.' }
          : { tone: 'success', text: 'These measurements were estimated from your photo. Check them, edit anything that looks off, then continue.' };
        self.showMeasurements({ bust: m.bust, waist: m.waist, hips: m.hips, height: m.height || heightCm });
      }).catch(function (err) {
        button.disabled = false;
        button.textContent = 'Scan photo';
        self.error(null, { message: err.message + ' It’s usually the framing or the pose: face the camera with your whole body in the shot and your arms a little away from your sides — or enter your measurements instead.' });
      });
    });
  };

  // Step 3: shape profile
  MyStylePage.prototype.showShape = function (shape) {
    var self = this;
    this.show(
      '<div class="mystyle-panel" data-step="shape">' +
        '<p class="mystyle-step">Step 3 of 4</p>' +
        shapeHtml(shape, false, this.unit) +
        '<div class="mystyle-actions"><button type="button" class="button button--secondary" data-back>Edit measurements</button>' +
        '<button type="button" class="button" data-next>Continue to style</button></div>' +
      '</div>');
    this.view.querySelector('[data-back]').addEventListener('click', function () { self.showMeasurements(); });
    this.view.querySelector('[data-next]').addEventListener('click', function () { self.showPreferences(); });
  };

  // Step 4: style choices
  MyStylePage.prototype.showPreferences = function (current) {
    var self = this;
    current = current || {};
    var picked = function (list, value) { return (list || []).some(function (v) { return String(v).toLowerCase() === String(value).toLowerCase(); }); };
    var colours = (C.launch.colors || []).map(function (c) {
      return '<label class="mystyle-swatch"><input type="checkbox" name="color" value="' + esc(c.name) + '"' + (picked(current.preferred_colors, c.name) ? ' checked' : '') + '>' +
        '<span><span class="mystyle-swatch__sample" style="background:' + esc(c.hex || '#ccc') + '"></span>' + esc(c.name) + '</span></label>';
    }).join('');
    var options = function (name, list, chosen) {
      return list.map(function (o) {
        return '<label class="mystyle-pill"><input type="checkbox" name="' + name + '" value="' + o[0] + '"' + (picked(chosen, o[0]) ? ' checked' : '') + '><span>' + o[1] + '</span></label>';
      }).join('');
    };
    this.show(
      '<form class="mystyle-panel" data-step="style">' +
        (this.profile ? '' : '<p class="mystyle-step">Step 4 of 4</p>') +
        '<h2>Your style</h2>' +
        '<fieldset><legend>Colors you love</legend><div class="mystyle-swatches">' + colours + '</div></fieldset>' +
        '<fieldset><legend>Silhouettes</legend><div class="mystyle-pills">' + options('silhouette', SILHOUETTES, current.preferred_silhouettes) + '</div></fieldset>' +
        '<fieldset><legend>Occasions</legend><div class="mystyle-pills">' + options('occasion', OCCASIONS, current.occasions) + '</div></fieldset>' +
        '<p class="mystyle-error" data-mystyle-error hidden></p>' +
        '<button class="button" type="submit">' + (this.profile ? 'Save my style' : 'See my picks') + '</button>' +
      '</form>');
    var form = this.view.querySelector('form');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var values = function (name) { return Array.prototype.map.call(form.querySelectorAll('[name="' + name + '"]:checked'), function (i) { return i.value; }); };
      var button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      storeProducts().then(function (products) {
        return api('/shopify/preferences', { method: 'POST', onSlow: function () { button.textContent = 'Waking up…'; }, body: {
          session_id: self.session || (self.profile && self.profile.session_id),
          preferred_colors: values('color'), preferred_silhouettes: values('silhouette'), occasions: values('occasion'),
          products: products, launch: C.launch } });
      }).then(function (r) {
        rememberProfile(r.profile);
        self.showProfile(r.profile);
      }).catch(function (err) {
        button.disabled = false;
        button.textContent = self.profile ? 'Save my style' : 'See my picks';
        self.error(null, err);
      });
    });
  };

  // The finished profile, with Picked for you and New for you
  MyStylePage.prototype.showProfile = function (profile) {
    var self = this;
    this.profile = profile;
    this.session = profile.session_id;
    var style = profile.style_profile || {};
    var list = function (items, labels) {
      var map = {};
      (labels || []).forEach(function (o) { map[o[0]] = o[1]; });
      return (items || []).map(function (v) { return map[v] || v; }).join(', ') || 'Any';
    };
    this.show(
      '<div class="mystyle-panel" data-step="profile">' +
        shapeHtml(profile.shape_profile, true, this.unit) +
        '<dl class="mystyle-style"><div><dt>Colors</dt><dd>' + esc(list(style.preferred_colors)) + '</dd></div>' +
        '<div><dt>Silhouettes</dt><dd>' + esc(list(style.preferred_silhouettes, SILHOUETTES)) + '</dd></div>' +
        '<div><dt>Occasions</dt><dd>' + esc(list(style.occasions, OCCASIONS)) + '</dd></div></dl>' +
        '<div class="mystyle-actions">' +
          '<button type="button" class="button button--secondary" data-edit-style>Update my style</button>' +
          '<button type="button" class="button button--secondary" data-remeasure>Update my measurements</button></div>' +
      '</div>' +
      '<div class="mystyle-results">' +
        '<h2>Picked for you</h2><p class="mystyle-muted" data-mystyle-status></p>' +
        '<ul class="grid product-grid grid--2-col-tablet-down grid--4-col-desktop mystyle-grid" data-picks></ul>' +
        '<h2>New for you</h2>' +
        '<ul class="grid product-grid grid--2-col-tablet-down grid--4-col-desktop mystyle-grid" data-new></ul>' +
      '</div>' +
      '<div class="mystyle-panel mystyle-danger">' +
        '<p>Want us to forget your measurements and style? This deletes your style profile from Eighth Hour.</p>' +
        '<button type="button" class="mystyle-link" data-delete>Delete my style profile</button>' +
        '<p class="mystyle-error" data-mystyle-error hidden></p>' +
      '</div>');
    this.view.querySelector('[data-edit-style]').addEventListener('click', function () { self.showPreferences(style); });
    this.view.querySelector('[data-remeasure]').addEventListener('click', function () { self.profile = null; self.showConsent(); });
    this.view.querySelector('[data-delete]').addEventListener('click', function () {
      if (!window.confirm('Delete your style profile? Your measurements and style choices will be removed.')) return;
      api('/shopify/profile', { method: 'DELETE' }).then(function () {
        saved(BACKUP_KEY, null);
        profilePromise = Promise.resolve(null);
        self.profile = null;
        self.session = null;
        self.showConsent();
      }).catch(function (err) { self.error(null, err); });
    });
    var slow = function () { self.slow(); };
    loadPicks(profile, this.view.querySelector('[data-picks]'), 8, slow)
      .catch(function (err) { self.view.querySelector('[data-picks]').innerHTML = '<li class="mystyle-empty">' + esc(err.message) + '</li>'; });
    loadNew(profile, this.view.querySelector('[data-new]'), 8, slow)
      .catch(function (err) { self.view.querySelector('[data-new]').innerHTML = '<li class="mystyle-empty">' + esc(err.message) + '</li>'; });
  };

  function shapeHtml(shape, compact, unit) {
    shape = shape || {};
    var c = shape.comparisons_cm || {};
    var diff = function (value, fuller, smaller) {
      if (value == null) return '';
      return value === 0 ? 'the same' : length(Math.abs(value), unit) + ' ' + (value > 0 ? fuller : smaller);
    };
    var comparisons = [
      ['Bust vs hips', c.bust_minus_hips == null ? '' : (c.bust_minus_hips === 0 ? 'Even' :
        (c.bust_minus_hips > 0 ? 'Bust ' : 'Hips ') + length(Math.abs(c.bust_minus_hips), unit) + ' fuller')],
      ['Waist vs bust', diff(c.bust_minus_waist, 'smaller', 'larger')],
      ['Waist vs hips', diff(c.hips_minus_waist, 'smaller', 'larger')]
    ].filter(function (row) { return row[1]; });
    var sizes = Object.keys(shape.size_recommendation_by_category || {}).map(function (key) {
      var size = String(shape.size_recommendation_by_category[key]);
      var halves = size.split('/');
      if (halves.length === 2 && halves[0] === halves[1]) size = halves[0];   // co-ords "XS/XS" -> "XS"
      return '<li><span>' + esc(SIZE_LABELS[key] || key.replace(/([A-Z])/g, ' $1').toLowerCase()) + '</span><strong>' +
        esc(size) + '</strong></li>';
    }).join('');
    var summary = inUnit(shape.shape_summary, unit);
    return '<h2>' + (compact ? 'Your style profile' : 'Your shape profile') + '</h2>' +
      '<p class="mystyle-shape"><strong>' + esc(capitalize(shape.shape_class)) + '</strong></p>' +
      (summary ? '<p>' + esc(summary) + '</p>' : '') +
      (comparisons.length && !compact ? '<ul class="mystyle-compare">' + comparisons.map(function (r) {
        return '<li><span>' + esc(r[0]) + '</span><strong>' + esc(r[1]) + '</strong></li>'; }).join('') + '</ul>' : '') +
      '<h3>Your sizes</h3><ul class="mystyle-sizes">' + sizes + '</ul>' +
      (!compact && shape.fit_notes && shape.fit_notes.length ? '<ul class="mystyle-tips">' + shape.fit_notes.map(function (n) {
        return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' : '');
  }

  // Shrink a photo before upload: phones take 12-48 MP images, and the API only
  // needs ~1600 px. Falls back to the original if the browser can't decode it.
  function shrinkPhoto(file) {
    if (!window.createImageBitmap) return Promise.resolve(file);
    return createImageBitmap(file, { imageOrientation: 'from-image' }).then(function (bitmap) {
      var scale = Math.min(1, PHOTO_LONGEST_SIDE_PX / Math.max(bitmap.width, bitmap.height));
      if (scale === 1 && file.type === 'image/jpeg') { if (bitmap.close) bitmap.close(); return file; }
      var canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      if (bitmap.close) bitmap.close();
      return new Promise(function (resolve) { canvas.toBlob(resolve, 'image/jpeg', 0.92); })
        .then(function (blob) { return blob ? new File([blob], 'photo.jpg', { type: 'image/jpeg' }) : file; });
    }).catch(function () { return file; });
  }

  // ---------------------------------------------------------------------- boot

  function boot() {
    document.querySelectorAll('[data-mystyle-fit]').forEach(initFit);
    document.querySelectorAll('[data-mystyle-picks]').forEach(initPicks);
    document.querySelectorAll('[data-mystyle-page]').forEach(function (root) { new MyStylePage(root).start(); });
  }

  // setToken: lets a reviewer previewing the unpublished theme (who is staff,
  // not a signed-in customer) try the signed-in experience with a token minted
  // for a test customer id. A token is only accepted if it carries the theme's
  // signature, so this grants nothing on its own.
  function setToken(value) {
    token = value || null;
    profilePromise = null;
    BACKUP_KEY = 'mystyle:profile:' + (value ? String(value).split('.')[1] : 'guest');
    boot();
  }

  window.MyStyle = { api: api, loadProfile: loadProfile, storeProducts: storeProducts, setToken: setToken };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
