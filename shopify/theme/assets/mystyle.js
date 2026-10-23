/*
 * MyStyle -- Eighth Hour's styling engine, in the store's theme.
 *
 * Config comes from snippets/mystyle-config.liquid (window.MyStyleConfig): the
 * API address, the signed-in customer's token (Liquid signs it server-side; a
 * guest has none), the page addresses and the brand's launch data.
 *
 * What it drives, wherever the markup is on the page:
 *   [data-mystyle-page="style"]            My Style: the five-step style profile
 *                                          (the header calls it Update Style once
 *                                          she has one)
 *   [data-mystyle-page="recommendations"]  My Recommendations
 *   [data-mystyle-page="new"]              New Releases
 *   [data-mystyle-fit]                     Fit Recommendation, on product pages
 *   [data-mystyle-picks]                   Picked for you, on the home page
 *   [data-mystyle-nav]                     the header links (snippets/mystyle-nav-link)
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
  var CATEGORY_ORDER = ['Tops', 'Skirts', 'Dresses', 'Vests', 'Trousers', 'Co-ord Sets', 'Jackets'];
  var SILHOUETTES = [['fitted', 'Fitted'], ['flowing', 'Flowing'], ['straight', 'Straight'], ['a_line', 'A-Line'], ['oversized', 'Oversized']];
  var OCCASIONS = [['work', 'Work'], ['casual', 'Casual'], ['evening', 'Evening'], ['weekend', 'Weekend']];
  var STEPS = ['Consent', 'Measurements', 'Shape Profile', 'Style Prefs', 'Complete'];
  var RANGES_CM = { bust: [70, 150], waist: [55, 130], hips: [80, 160], height: [140, 210] };
  var EXAMPLES = { in: { bust: 35, waist: 28, hips: 40, height: 65 }, cm: { bust: 88, waist: 70, hips: 102, height: 165 } };
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
  function withParam(url, param) { return url + (url.indexOf('?') === -1 ? '?' : '&') + param; }
  // Back to this page after signing in -- so a shopper who lands on a product
  // from an ad returns to it. Shopify's storefront sign-in link already does;
  // otherwise ask for it (return_to takes a relative path).
  function signInUrl() {
    if (/[?&]return_to=/.test(C.loginUrl)) return C.loginUrl;
    return withParam(C.loginUrl, 'return_to=' + encodeURIComponent(window.location.pathname + window.location.search));
  }

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

  // products.json prices are in the store's currency; show them in the
  // shopper's, as the theme does.
  function money(amount) {
    var currency = window.Shopify && Shopify.currency || {};
    var value = parseFloat(amount) * (parseFloat(currency.rate) || 1);
    if (isNaN(value)) return '';
    try {
      return new Intl.NumberFormat(document.documentElement.lang || 'en-US', { style: 'currency', currency: currency.active || 'USD' }).format(value);
    } catch (e) { return value.toFixed(2); }
  }

  // Ink that reads against a colour swatch, for the tick on a chosen one.
  function inkFor(hex) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return '#ffffff';
    var light = (0.299 * parseInt(m[1], 16) + 0.587 * parseInt(m[2], 16) + 0.114 * parseInt(m[3], 16)) / 255;
    return light > 0.6 ? '#121212' : '#ffffff';
  }

  // ---------------------------------------------------------------------- API

  function MyStyleError(message, status) { this.message = message; this.status = status; }

  var token = C.token || null;

  function freshToken() {
    return fetch(withParam(C.tokenUrl, '_=' + Date.now()), { credentials: 'same-origin' })
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

  var launchCategory = {};
  var launchStyle = {};
  (C.launch && C.launch.styles || []).forEach(function (style) {
    (style.skus || []).forEach(function (sku) {
      launchCategory[String(sku).toUpperCase()] = style.category;
      launchStyle[String(sku).toUpperCase()] = style;
    });
  });
  function categoryOf(p) {
    var v = (p.variants || []).filter(function (v) { return launchCategory[String(v.sku || '').toUpperCase()]; })[0];
    return v ? launchCategory[String(v.sku).toUpperCase()] : '';
  }
  function isLaunchProduct(p) { return !!categoryOf(p); }

  // The launch style a store product is, by the API's rule: every SKU on it
  // belongs to that one style (else it isn't a My Style piece).
  function styleOf(p) {
    var style = null;
    var variants = p.variants || [];
    for (var i = 0; i < variants.length; i++) {
      var s = launchStyle[String(variants[i].sku || '').toUpperCase()];
      if (!s || (style && s !== style)) return null;
      style = s;
    }
    return style;
  }
  function optionKey(value) { return String(value).trim().toLowerCase().replace(/[\s-]+/g, '_'); }

  // What the quiz may offer: only colours, silhouettes and occasions that
  // match a My Style piece she could buy now (a variant in stock), so every
  // choice applies to something in the store.
  function availableOptions(products) {
    var found = { colours: {}, silhouettes: {}, occasions: {} };
    products.forEach(function (p) {
      var style = styleOf(p);
      var inStock = (p.variants || []).filter(function (v) { return v.available; });
      if (!style || !inStock.length) return;
      var colourAt = -1;
      (p.options || []).forEach(function (o, i) { if (/^colou?r$/i.test(o.name || '')) colourAt = i; });
      inStock.forEach(function (v) {
        if (colourAt >= 0 && v.options[colourAt]) found.colours[String(v.options[colourAt]).trim().toLowerCase()] = true;
      });
      (style.silhouettes || []).forEach(function (s) { found.silhouettes[optionKey(s)] = true; });
      (style.occasions || []).forEach(function (o) { found.occasions[optionKey(o)] = true; });
    });
    return found;
  }

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

  // What the theme shows of a piece outside a product card (the quiz's
  // preview): handle -> { title, image, price, category, published }.
  var productInfo = {};
  var productsPromise = null;
  function storeProducts() {
    if (!productsPromise) {
      productsPromise = (function load(page, found) {
        return fetch(C.rootUrl + 'products.json?limit=250&page=' + page, { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : { products: [] }; })
          .then(function (data) {
            var products = data.products || [];
            products.filter(isLaunchProduct).forEach(function (p) {
              productInfo[p.handle] = {
                title: p.title,
                image: p.images && p.images[0] && p.images[0].src,
                price: p.variants && p.variants[0] && p.variants[0].price,
                category: categoryOf(p),
                published: p.published_at
              };
              found.push(slimProduct(p));
            });
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
      }).then(function (profile) {
        if (profile && profile.profile_token) saved(BACKUP_KEY, profile.profile_token);
        updateNav(!!profile);
        return profile;
      });
      profilePromise.catch(function () { profilePromise = null; });
    }
    return profilePromise;
  }
  function rememberProfile(profile) {
    if (profile && profile.profile_token) saved(BACKUP_KEY, profile.profile_token);
    profilePromise = Promise.resolve(profile);
    updateNav(!!profile);
  }
  function forgetProfile() {
    saved(BACKUP_KEY, null);
    profilePromise = Promise.resolve(null);
    updateNav(false);
  }

  // The header's links (snippets/mystyle-nav-link.liquid sets them from this
  // browser's backup on every page; this keeps them right as she changes it).
  function updateNav(hasProfile) {
    document.querySelectorAll('[data-mystyle-nav="style"]').forEach(function (a) {
      a.setAttribute('href', hasProfile ? withParam(C.pageUrl, 'step=style') : C.pageUrl);
      var label = a.querySelector('[data-mystyle-nav-label]') || a;
      label.textContent = hasProfile ? 'Update Style' : 'My Style';
    });
    document.querySelectorAll('[data-mystyle-nav="recommendations"]').forEach(function (a) {
      (a.closest('li') || a).style.display = hasProfile ? '' : 'none';
    });
  }

  // ------------------------------------------------------------- product cards

  // The theme's own product card, via the Section Rendering API, so a
  // recommendation looks exactly like any other product on the site and shows
  // Shopify's own price for this shopper's market. Each item: { handle, match,
  // category, reason, size, sizeTone, soldOut }; the extra lines go inside the
  // card's text column so they line up with its name and price.
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
        var item = card.item;
        var li = el('<li class="grid__item mystyle-card"></li>');
        li.dataset.category = item.category || '';
        var doc = new DOMParser().parseFromString(card.html, 'text/html');
        var section = doc.querySelector('.shopify-section') || doc.body;
        li.innerHTML = section.innerHTML;
        var info = (li.querySelector('.price') || li).closest('.card__information') || li;
        var heading = info.querySelector('.card__heading');
        if (item.match != null && heading) {
          heading.parentNode.insertBefore(el('<p class="mystyle-card__match">' + Math.round(item.match * 100) + '% match</p>'), heading);
        }
        if (item.category && heading) heading.insertAdjacentElement('afterend', el('<p class="mystyle-card__category">' + esc(item.category) + '</p>'));
        if (item.reason) info.appendChild(el('<p class="mystyle-card__reason">' + esc(inUnit(item.reason)) + '</p>'));
        if (item.size) info.appendChild(el('<p class="mystyle-card__size' + (item.sizeTone ? ' is-' + item.sizeTone : '') + '">' + esc(inUnit(item.size)) + '</p>'));
        if (item.soldOut) info.appendChild(el('<p class="mystyle-card__stock">Sold out in this size</p>'));
        list.appendChild(li);
      });
      if (!list.children.length) list.appendChild(el('<li class="mystyle-empty">' + esc(emptyText) + '</li>'));
    });
  }

  function getPicks(profile, k, onSlow) {
    return storeProducts().then(function (products) {
      return api('/shopify/recommendations', {
        method: 'POST', onSlow: onSlow,
        body: { session_id: profile.session_id, k: k, products: products, launch: C.launch }
      });
    }).then(function (data) { return data.recommendations; });
  }
  function sizeLine(item, prefix) {
    if (item.closest_available && item.size_note) return { size: item.size_note, sizeTone: 'closest' };
    return { size: item.recommended_size ? prefix + item.recommended_size : '', sizeTone: '' };
  }
  function pickCard(profile, item) {
    var line = sizeLine(item, 'Your size: ');
    return {
      handle: item.handle, category: item.category,
      reason: 'Suits your ' + (profile.shape_profile.shape_class || 'body') + ' shape',
      size: line.size, sizeTone: line.sizeTone, soldOut: item.in_stock_in_size === false
    };
  }

  // ------------------------------------------------------ product page: fit

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
    if (!styleOf(product)) return;                   // not a My Style piece
    var body = box.querySelector('[data-mystyle-fit-body]');
    box.hidden = false;
    var prompt = function (html) { body.innerHTML = '<p class="mystyle-fit__prompt">' + html + '</p>'; };

    // Shoppers often land here straight from an ad: tell them what My Style
    // would show them, and how to get it.
    var invite = function (title, text, action) {
      body.innerHTML = '<div class="mystyle-fit__invite"><p class="mystyle-fit__invite-title">' + esc(title) + '</p>' +
        '<p>' + esc(text) + '</p><a class="mystyle-btn mystyle-btn--small" href="' + esc(action[1]) + '">' + esc(action[0]) + '</a>' +
        (action[2] ? '<p class="mystyle-fit__invite-note">' + esc(action[2]) + '</p>' : '') + '</div>';
    };
    if (!token) {
      invite('How will this fit you?',
        'Sign in and answer a few quick questions to see your size in this piece, how it fits you, and styling tips for your shape.',
        ['Sign in to see your fit', signInUrl(), 'New here? You can create a free account on the next page.']);
      return;
    }
    prompt('Finding your size…');
    loadProfile(function () { prompt('Waking up My Style — this can take up to a minute.'); })
      .then(function (profile) {
        if (!profile) {
          invite('See how this fits you',
            'Build your style profile in about 5 minutes — with your measurements or a photo — to see your size in this piece and how it fits you.',
            ['Build my style profile', C.pageUrl]);
          return null;
        }
        return api('/shopify/fit-check', {
          method: 'POST',
          body: { session_id: profile.session_id, product: slimProduct(product), launch: C.launch }
        }).then(function (fit) { renderFit(box, body, fit); });
      })
      .catch(function (err) {
        if (err.status === 404) { box.hidden = true; return; }
        prompt(esc(err.message));
      });
  }

  function renderFit(box, body, fit) {
    var size = fit.recommended_size;
    var bars = SIZE_ORDER.filter(function (s) { return s in fit.fit_scores; }).map(function (s) {
      var pct = Math.round(fit.fit_scores[s] * 100);
      return '<li' + (s === size ? ' class="is-recommended"' : '') + '><span>' + esc(s) + '</span>' +
        '<span class="mystyle-bar"><span style="width:' + pct + '%"></span></span><span>' + pct + '%</span></li>';
    }).join('');
    body.innerHTML =
      '<div class="mystyle-fit__hero">' +
        '<span class="mystyle-label">' + (fit.closest_available ? 'Closest available size' : 'Recommended size') + '</span>' +
        '<span class="mystyle-fit__size">' + esc(size) + '</span>' +
        (fit.confidence != null ? '<span class="mystyle-pill">' + Math.round(fit.confidence * 100) + '% confidence</span>' : '') +
        '<button type="button" class="mystyle-link" data-select-size>Select ' + esc(size) + '</button>' +
      '</div>' +
      (fit.in_stock_in_size === false ? '<p class="mystyle-fit__stock">' + esc(size) + ' is sold out right now.</p>' : '') +
      ((fit.fit_by_area || []).length ? '<p class="mystyle-fit__sub">How ' + esc(size) + ' fits you:</p><ul class="mystyle-areas">' +
        fit.fit_by_area.map(function (a) {
          return '<li class="is-' + esc(String(a.fit).replace(/\s+/g, '-')) + '"><span>' + esc(capitalize(a.area)) + '</span><strong>' + esc(capitalize(a.fit)) + '</strong></li>';
        }).join('') + '</ul>' : '') +
      '<p class="mystyle-fit__sub">How each size fits you:</p>' +
      '<ul class="mystyle-bars">' + bars + '</ul>' +
      '<p class="mystyle-fit__sub">Fit Details</p>' +
      '<ul class="mystyle-ticks">' + fit.fit_notes.map(function (n) { return '<li>' + esc(inUnit(n)) + '</li>'; }).join('') + '</ul>' +
      ((fit.tips || []).length ? '<p class="mystyle-fit__sub">Tips for You</p><ul class="mystyle-tips">' +
        fit.tips.map(function (t) { return '<li>' + esc(inUnit(t)) + '</li>'; }).join('') + '</ul>' : '') +
      '<div class="mystyle-fit__feedback" data-feedback>' +
        '<button type="button" class="mystyle-btn mystyle-btn--secondary mystyle-btn--small" data-open>Share Your Fit Feedback</button></div>';
    body.querySelector('[data-select-size]').addEventListener('click', function () {
      if (!selectSize(box, size)) this.textContent = 'Choose ' + size + ' above';
    });
    var feedback = body.querySelector('[data-feedback]');
    feedback.querySelector('[data-open]').addEventListener('click', function () {
      feedback.innerHTML = '<p>Bought it? How did it fit?</p><div class="mystyle-fit__choices">' +
        '<button type="button" class="mystyle-btn mystyle-btn--secondary mystyle-btn--small" data-fit="too_tight">Too tight</button>' +
        '<button type="button" class="mystyle-btn mystyle-btn--secondary mystyle-btn--small" data-fit="perfect">Just right</button>' +
        '<button type="button" class="mystyle-btn mystyle-btn--secondary mystyle-btn--small" data-fit="too_loose">Too loose</button></div>';
    });
    feedback.addEventListener('click', function (e) {
      var choice = e.target.closest('[data-fit]');
      if (!choice || !fit.check_id) return;
      api('/shopify/feedback', { method: 'POST', body: {
        fit_check_id: fit.check_id, product_handle: fit.product_sku, feedback_type: choice.dataset.fit } })
        .then(function () { feedback.innerHTML = '<p>Thanks — that helps us size the next piece.</p>'; })
        .catch(function (err) { feedback.innerHTML = '<p>' + esc(err.message) + '</p>'; });
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
      intro.innerHTML = 'Chosen for your ' + esc(profile.shape_profile.shape_class || '') + ' shape and your style. <a href="' + esc(C.recommendationsUrl) + '">See all your recommendations</a>';
      return getPicks(profile, Number(section.dataset.count) || 4).then(function (items) {
        return renderCards(list, items.map(function (i) { return pickCard(profile, i); }), 'Your picks will appear here as the new collection arrives.');
      });
    }).catch(function () { section.hidden = true; });
  }

  // ------------------------------------------------------- page scaffolding

  function Page(root) {
    this.root = root;
    this.view = root.querySelector('[data-mystyle-view]');
    // These pages redraw in place (each quiz step, then picks arriving). With
    // the browser's scroll anchoring on, a step that grows after it is drawn
    // pushed the page down past its own top.
    document.documentElement.style.overflowAnchor = 'none';
  }
  Page.prototype.show = function (html) {
    this.view.innerHTML = html;
    if (this.shown && this.root.getBoundingClientRect().top < 0) this.root.scrollIntoView({ block: 'start', behavior: 'smooth' });
    this.shown = true;
  };
  Page.prototype.notice = function (title, text, action) {
    this.show('<div class="mystyle-notice"><h1>' + esc(title) + '</h1><p class="mystyle-subtitle">' + text + '</p>' +
      (action ? '<a class="mystyle-btn" href="' + esc(action[1]) + '">' + esc(action[0]) + '</a>' : '') + '</div>');
  };
  Page.prototype.slow = function () {
    var status = this.view.querySelector('[data-status]');
    if (status) status.textContent = 'Waking up My Style — this can take up to a minute the first time.';
  };
  Page.prototype.error = function (err) {
    var box = this.view.querySelector('[data-error]');
    if (box) { box.textContent = err.message || String(err); box.hidden = false; }
  };
  var LOADING = '<div class="mystyle-notice"><p class="mystyle-subtitle" data-status>Loading your style profile…</p></div>';

  // ------------------------------------------------- My Style: the quiz

  function Quiz(root) {
    Page.call(this, root);
    this.unit = unitPref();
    this.session = null;
    this.profile = null;
    this.photoNote = null;
  }
  Quiz.prototype = Object.create(Page.prototype);

  Quiz.prototype.card = function (step, inner, footer) {
    var progress = '';
    if (step) {
      progress = '<div class="mystyle-progress"><ol>' + STEPS.map(function (label, i) {
        return '<li' + (i < step ? ' class="is-active"' : '') + (i === step - 1 ? ' aria-current="step"' : '') + '>' +
          '<span class="mystyle-progress__num">' + (i + 1) + '</span><span class="mystyle-progress__label">' + label + '</span></li>';
      }).join('') + '</ol><div class="mystyle-progress__bar"><span style="width:' + (step / STEPS.length * 100) + '%"></span></div></div>';
    }
    this.show('<div class="mystyle-quiz">' + progress + '<div class="mystyle-quiz__screen">' + inner + '</div>' +
      (footer === false ? '' : '<div class="mystyle-quiz__footer"><button type="button" class="mystyle-text-link" data-fresh>Start Fresh</button>' +
        (this.profile ? '<span aria-hidden="true">·</span><button type="button" class="mystyle-text-link" data-delete>Delete my style profile</button>' : '') +
      '</div>') + '</div>');
    var self = this;
    var fresh = this.view.querySelector('[data-fresh]');
    if (fresh) fresh.addEventListener('click', function () { self.session = null; self.lastMeasurements = null; self.showConsent(); });
    var del = this.view.querySelector('[data-delete]');
    if (del) del.addEventListener('click', function () { self.deleteProfile(); });
  };

  Quiz.prototype.actions = function (back, next, nextType) {
    return '<div class="mystyle-actions">' +
      (back ? '<button type="button" class="mystyle-btn mystyle-btn--secondary" data-back>' + back + '</button>' : '<span></span>') +
      '<button type="' + (nextType || 'submit') + '" class="mystyle-btn" data-next>' + next + '</button></div>';
  };
  Quiz.prototype.onBack = function (handler) {
    var back = this.view.querySelector('[data-back]');
    if (back) back.addEventListener('click', handler.bind(this));
  };

  Quiz.prototype.start = function () {
    var self = this;
    if (!token) {
      this.card(0,
        '<h2>Get Your Personalized Style Profile</h2>' +
        '<p class="mystyle-subtitle">In 5 minutes, we’ll find your size in every piece and create recommendations tailored to your shape and style.</p>' +
        '<div class="mystyle-actions mystyle-actions--center"><a class="mystyle-btn" href="' + esc(signInUrl()) + '">Sign in to start</a></div>' +
        '<p class="mystyle-note">Your style profile is saved to your Eighth Hour account.</p>', false);
      return;
    }
    this.show(LOADING);
    loadProfile(function () { self.slow(); }).then(function (profile) {
      if (!profile) { self.showConsent(); return; }
      self.profile = profile;
      self.session = profile.session_id;
      if (/(^|[?&])step=style(&|$)/.test(window.location.search)) self.showPreferences(); else self.showComplete();
    }).catch(function (err) {
      self.show('<div class="mystyle-notice"><p class="mystyle-error">' + esc(err.message) + '</p></div>');
    });
  };

  Quiz.prototype.deleteProfile = function () {
    var self = this;
    if (!window.confirm('Delete your style profile? Your measurements and style choices will be removed from Eighth Hour.')) return;
    api('/shopify/profile', { method: 'DELETE' }).then(function () {
      forgetProfile();
      self.profile = null;
      self.session = null;
      self.showConsent();
    }).catch(function (err) { window.alert(err.message); });
  };

  // Step 1: consent
  Quiz.prototype.showConsent = function () {
    var self = this;
    this.card(1,
      '<form data-form novalidate>' +
        '<h2>Get Your Personalized Style Profile</h2>' +
        '<p class="mystyle-subtitle">In 5 minutes, we’ll create recommendations tailored to your shape and style.</p>' +
        '<div class="mystyle-box">' +
          '<h3>Consent to Data Processing</h3>' +
          '<label class="mystyle-check"><input type="checkbox" name="photo"><span>I consent to photo capture and measurement extraction</span></label>' +
          '<p class="mystyle-check__note">If you use a photo, we use it only to estimate your measurements. Your photo is not stored.</p>' +
          '<label class="mystyle-check"><input type="checkbox" name="measurements"><span>I consent to using my measurements for personalized recommendations</span></label>' +
          '<p class="mystyle-check__note">Your measurements help us find the perfect fit and style for you.</p>' +
        '</div>' +
        '<p class="mystyle-error" data-error hidden></p>' +
        this.actions(this.profile ? 'Back' : '', 'Continue') +
        '<p class="mystyle-note">You can delete your style profile at any time.</p>' +
      '</form>');
    var form = this.view.querySelector('[data-form]');
    var next = form.querySelector('[data-next]');
    var sync = function () { next.disabled = !(form.photo.checked && form.measurements.checked); };
    sync();
    form.addEventListener('change', sync);
    this.onBack(function () { this.showComplete(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (next.disabled) return;
      next.disabled = true;
      api('/shopify/session', { method: 'POST', body: { photo_consent: true, measurement_consent: true }, onSlow: function () { next.textContent = 'Waking up…'; } })
        .then(function (r) { self.session = r.session_id; self.showMeasurements(); })
        .catch(function (err) { next.disabled = false; next.textContent = 'Continue'; self.error(err); });
    });
  };

  // Step 2: measurements (typed, or estimated from a photo then checked)
  Quiz.prototype.toUnit = function (cm) { return this.unit === 'in' ? Math.round(cm / 2.54 * 2) / 2 : Math.round(cm * 10) / 10; };
  Quiz.prototype.toCm = function (value) { return this.unit === 'in' ? value * 2.54 : value; };
  Quiz.prototype.rangeText = function (field) {
    var r = RANGES_CM[field];
    return this.unit === 'in' ? Math.ceil(r[0] / 2.54) + '–' + Math.floor(r[1] / 2.54) + ' in' : r[0] + '–' + r[1] + ' cm';
  };

  Quiz.prototype.showMeasurements = function (values) {
    var self = this;
    values = values || this.lastMeasurements || {};
    var unitName = this.unit === 'in' ? 'in' : 'cm';
    var field = function (name, label, help) {
      var v = values[name] != null ? self.toUnit(values[name]) : '';
      return '<label class="mystyle-field"><span>' + label + ' (' + unitName + ')</span>' +
        '<input type="number" step="0.5" inputmode="decimal" name="' + name + '" value="' + esc(v) + '" placeholder="e.g., ' + EXAMPLES[self.unit][name] + '">' +
        '<small>' + help + ' (' + self.rangeText(name) + ')</small></label>';
    };
    var note = this.photoNote;
    this.photoNote = null;
    var updating = this.profile && !this.lastMeasurements && !values.bust;
    this.card(2,
      '<form data-form novalidate>' +
        '<div class="mystyle-heading-row"><h2>Your Measurements</h2>' +
          '<div class="mystyle-units" role="group" aria-label="Units">' +
            '<button type="button" data-unit="in"' + (this.unit === 'in' ? ' class="is-active"' : '') + '>in</button>' +
            '<button type="button" data-unit="cm"' + (this.unit === 'cm' ? ' class="is-active"' : '') + '>cm</button></div></div>' +
        '<p class="mystyle-subtitle">Tell us your body measurements for an accurate fit.</p>' +
        (updating ? '<p class="mystyle-callout">For your privacy, we never show the measurements you’ve saved. Enter them again to update your profile.</p>' : '') +
        (note ? '<p class="mystyle-callout is-' + note.tone + '">' + esc(note.text) + '</p>' : '') +
        '<div class="mystyle-fields">' +
          field('bust', 'Bust', 'Measure around fullest part') +
          field('waist', 'Waist', 'Measure natural waist') +
          field('hips', 'Hips', 'Measure fullest part') +
          field('height', 'Height', 'Your total height') +
        '</div>' +
        '<p class="mystyle-error" data-error hidden></p>' +
        this.actions('Back', 'Continue') +
        '<p class="mystyle-note">Don’t know your exact measurements? <button type="button" class="mystyle-link" data-photo>Use photo measurement</button></p>' +
      '</form>');
    var form = this.view.querySelector('[data-form]');
    form.querySelectorAll('[data-unit]').forEach(function (b) {
      b.addEventListener('click', function () {
        var current = self.readMeasurements(form, true);
        self.unit = b.dataset.unit;
        saved('mystyle:unit', self.unit);
        self.showMeasurements(current);
      });
    });
    form.querySelector('[data-photo]').addEventListener('click', function () { self.showPhoto(); });
    this.onBack(function () { if (this.profile && this.profile.shape_profile) this.showShape(this.profile.shape_profile); else this.showConsent(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var values = self.readMeasurements(form, false);
      if (!values) return;
      var next = form.querySelector('[data-next]');
      next.disabled = true;
      api('/shopify/measurements', { method: 'POST', body: Object.assign({ session_id: self.session }, values), onSlow: function () { next.textContent = 'Waking up…'; } })
        .then(function (r) { self.lastMeasurements = values; self.shape = r.shape_profile; self.showShape(r.shape_profile); })
        .catch(function (err) { next.disabled = false; next.textContent = 'Continue'; self.error(err); });
    });
  };

  // Values in cm, or null (with the problem shown) when anything is missing or
  // out of range. lenient: keep whatever is there, for switching units.
  Quiz.prototype.readMeasurements = function (form, lenient) {
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
    if (problems.length) { this.error({ message: problems.join('. ') + '.' }); return null; }
    return out;
  };

  Quiz.prototype.showPhoto = function () {
    var self = this;
    var sizes = SIZE_ORDER.map(function (s) { return '<option value="' + s + '">' + s + '</option>'; }).join('');
    var heightCm = this.lastMeasurements && this.lastMeasurements.height;
    var unitName = this.unit === 'in' ? 'in' : 'cm';
    this.card(2,
      '<form data-form novalidate>' +
        '<h2>Measure From a Photo</h2>' +
        '<p class="mystyle-subtitle">We’ll estimate your measurements from one full-body photo. You can check and edit every number before continuing.</p>' +
        '<div class="mystyle-box" data-disclosure><p class="mystyle-check__note">Loading privacy information…</p></div>' +
        ((this.root.querySelector('template[data-mystyle-framing]') || {}).innerHTML || '') +
        '<div class="mystyle-fields">' +
          '<label class="mystyle-field mystyle-field--wide"><span>Full-body photo</span><input type="file" name="photo" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"><small>JPEG, PNG, HEIC (iPhone) or WEBP</small></label>' +
          '<label class="mystyle-field"><span>Height (' + unitName + ')</span><input type="number" step="0.5" inputmode="decimal" name="height" value="' + (heightCm ? esc(this.toUnit(heightCm)) : '') + '" placeholder="e.g., ' + EXAMPLES[this.unit].height + '"><small>A photo alone can’t tell your scale (' + this.rangeText('height') + ')</small></label>' +
          '<span></span>' +
          '<label class="mystyle-field"><span>Usual size — tops</span><select name="top"><option value="">Select</option>' + sizes + '</select><small>Used for your bust and waist</small></label>' +
          '<label class="mystyle-field"><span>Usual size — bottoms</span><select name="bottom"><option value="">Select</option>' + sizes + '</select><small>Used for your hips and waist</small></label>' +
        '</div>' +
        '<p class="mystyle-callout">A photo can’t see body depth, so on its own it can be well off — your usual sizes keep your bust and hips grounded, the photo fine-tunes them, and your waist is worked out from your shape in the photo.</p>' +
        '<p class="mystyle-callout"><strong>How accurate is this?</strong> Our image recognition estimates are accurate to an average of about 3 cm from your measured bust, waist and hips. Loose clothing hides your shape — especially your waist — and makes the estimate less accurate.</p>' +
        '<label class="mystyle-check"><input type="checkbox" name="adult"><span>I’m 18 or older (or have a parent or guardian’s permission), and I understand my photo will be used only to estimate my measurements, as described above.</span></label>' +
        '<p class="mystyle-error" data-error hidden></p>' +
        this.actions('Back', 'Scan Photo') +
        '<p class="mystyle-note">Prefer not to upload a photo? <button type="button" class="mystyle-link" data-manual>Enter measurements manually</button></p>' +
      '</form>');
    var form = this.view.querySelector('[data-form]');
    form.querySelector('[data-manual]').addEventListener('click', function () { self.showMeasurements(); });
    this.onBack(function () { this.showMeasurements(); });
    api('/intake/photo-disclosure').then(function (d) {
      form.querySelector('[data-disclosure]').innerHTML =
        '<h3>Your photo</h3><p class="mystyle-check__note">Processed by ' + esc(d.processor_name) + '. ' + esc(d.retention) + '</p>';
    }).catch(function () {
      form.querySelector('[data-disclosure]').innerHTML = '<h3>Your photo</h3><p class="mystyle-check__note">Used only to estimate your measurements, and not stored.</p>';
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
      if (problems.length) { self.error({ message: problems.join('. ') + '.' }); return; }
      var next = form.querySelector('[data-next]');
      next.disabled = true;
      next.textContent = 'Estimating…';
      shrinkPhoto(file).then(function (photo) {
        var data = new FormData();
        data.append('session_id', self.session);
        data.append('height_cm', String(Math.round(heightCm * 10) / 10));
        data.append('photo', photo);
        data.append('usual_top_size', form.top.value);
        data.append('usual_bottom_size', form.bottom.value);
        return api('/intake/photo-measure', { method: 'POST', form: data, onSlow: function () { next.textContent = 'Still working…'; } });
      }).then(function (r) {
        var m = r.measurements || {};
        var checkable = (r.low_confidence_fields || []).filter(function (f) { return f in RANGES_CM; });
        self.photoNote = checkable.length
          ? { tone: 'caution', text: 'We estimated these from your photo, but weren’t fully confident about: ' + checkable.join(', ') + '. Please check them before continuing.' }
          : { tone: 'success', text: 'These measurements were estimated from your photo. Check them, edit anything that looks off, then continue.' };
        self.showMeasurements({ bust: m.bust, waist: m.waist, hips: m.hips, height: m.height || heightCm });
      }).catch(function (err) {
        next.disabled = false;
        next.textContent = 'Scan Photo';
        // A refused scan (too many this hour) says what to do itself; framing advice is for a scan that failed.
        self.error({ message: err.status === 429 ? err.message : err.message + ' It’s usually the framing or the pose: face the camera with your whole body in the shot and your arms a little away from your sides — or enter your measurements instead.' });
      });
    });
  };

  // Step 3: shape profile
  Quiz.prototype.showShape = function (shape) {
    var self = this;
    var unit = this.unit;
    var c = shape.comparisons_cm || {};
    var diff = function (value, fuller, smaller) {
      if (value == null) return '';
      return value === 0 ? 'The same' : length(Math.abs(value), unit) + ' ' + (value > 0 ? fuller : smaller);
    };
    var ratios = [
      ['Bust vs Hips', c.bust_minus_hips == null ? '' : (c.bust_minus_hips === 0 ? 'Even' :
        (c.bust_minus_hips > 0 ? 'Bust ' : 'Hips ') + length(Math.abs(c.bust_minus_hips), unit) + ' fuller')],
      ['Waist vs Bust', diff(c.bust_minus_waist, 'smaller', 'larger')],
      ['Waist vs Hips', diff(c.hips_minus_waist, 'smaller', 'larger')],
      ['Waist-to-Hip Ratio', shape.ratios && shape.ratios.waist_hip != null ? Number(shape.ratios.waist_hip).toFixed(2) : '']
    ].filter(function (r) { return r[1]; });
    this.card(3,
      '<h2>Your Shape Profile</h2>' +
      '<p class="mystyle-subtitle">Based on your measurements, here’s your shape and sizing recommendations.</p>' +
      '<div class="mystyle-box"><p class="mystyle-label">Shape class</p>' +
        '<p class="mystyle-value">' + esc(capitalize(shape.shape_class)) + '</p>' +
        (shape.shape_summary ? '<p class="mystyle-summary">' + esc(inUnit(shape.shape_summary, unit)) + '</p>' : '') + '</div>' +
      (ratios.length ? '<div class="mystyle-box"><p class="mystyle-label">How your measurements compare</p><dl class="mystyle-ratios">' +
        ratios.map(function (r) { return '<div><dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd></div>'; }).join('') + '</dl></div>' : '') +
      '<div class="mystyle-box"><p class="mystyle-label">Recommended sizes</p>' + sizeTiles(shape) + '</div>' +
      this.actions('Back', 'Continue to Style', 'button'));
    this.onBack(function () { self.showMeasurements(); });
    this.view.querySelector('[data-next]').addEventListener('click', function () { self.showPreferences(); });
  };

  // Step 4: style preferences -- only options that apply to something in the store
  Quiz.prototype.showPreferences = function () {
    var self = this;
    this.card(4, '<h2>Your Style Preferences</h2><p class="mystyle-subtitle" data-status>Loading the collection…</p>');
    storeProducts().then(function (products) { self.renderPreferences(availableOptions(products)); });
  };

  Quiz.prototype.renderPreferences = function (available) {
    var self = this;
    var current = (this.profile && this.profile.style_profile) || {};
    var picked = function (list, value) { return (list || []).some(function (v) { return String(v).toLowerCase() === String(value).toLowerCase(); }); };
    var colours = (C.launch.colors || []).filter(function (c) { return available.colours[String(c.name).toLowerCase()]; }).map(function (c) {
      return '<label class="mystyle-colour"><input type="checkbox" name="color" value="' + esc(c.name) + '"' + (picked(current.preferred_colors, c.name) ? ' checked' : '') + '>' +
        '<span><span class="mystyle-colour__swatch" style="background:' + esc(c.hex || '#ccc') + ';--ink:' + inkFor(c.hex) + '"></span>' +
        '<span class="mystyle-colour__name">' + esc(c.name) + '</span></span></label>';
    }).join('');
    var options = function (name, list, chosen, offered) {
      return list.filter(function (o) { return offered[o[0]]; }).map(function (o) {
        return '<label class="mystyle-option"><input type="checkbox" name="' + name + '" value="' + o[0] + '"' + (picked(chosen, o[0]) ? ' checked' : '') + '><span>' + o[1] + '</span></label>';
      }).join('');
    };
    var group = function (legend, html, cls) {
      return '<fieldset><legend>' + legend + '</legend>' +
        (html ? '<div class="' + cls + '">' + html + '</div>' : '<p class="mystyle-check__note mystyle-none">None in the collection yet.</p>') + '</fieldset>';
    };
    var silhouettes = options('silhouette', SILHOUETTES, current.preferred_silhouettes, available.silhouettes);
    var occasions = options('occasion', OCCASIONS, current.occasions, available.occasions);
    this.card(4,
      '<form data-form novalidate>' +
        '<h2>Your Style Preferences</h2>' +
        '<p class="mystyle-subtitle">Help us personalize recommendations by sharing your style preferences.</p>' +
        (colours || silhouettes || occasions ? '' : '<p class="mystyle-callout">Style choices will appear here as the new collection arrives. You can continue without them.</p>') +
        group('Preferred Colors', colours, 'mystyle-colours') +
        group('Preferred Silhouettes', silhouettes, 'mystyle-options') +
        group('Occasions', occasions, 'mystyle-options') +
        '<p class="mystyle-error" data-error hidden></p>' +
        this.actions('Back', 'Get Recommendations') +
      '</form>');
    var form = this.view.querySelector('[data-form]');
    this.onBack(function () {
      var shape = this.shape || (this.profile && this.profile.shape_profile);
      if (shape) this.showShape(shape); else this.showMeasurements();
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var values = function (name) { return Array.prototype.map.call(form.querySelectorAll('[name="' + name + '"]:checked'), function (i) { return i.value; }); };
      var next = form.querySelector('[data-next]');
      next.disabled = true;
      storeProducts().then(function (products) {
        return api('/shopify/preferences', { method: 'POST', onSlow: function () { next.textContent = 'Waking up…'; }, body: {
          session_id: self.session,
          preferred_colors: values('color'), preferred_silhouettes: values('silhouette'), occasions: values('occasion'),
          products: products, launch: C.launch } });
      }).then(function (r) {
        rememberProfile(r.profile);
        self.profile = r.profile;
        self.shape = null;
        self.lastMeasurements = null;
        self.showComplete();
      }).catch(function (err) {
        next.disabled = false;
        next.textContent = 'Get Recommendations';
        self.error(err);
      });
    });
  };

  // Step 5: complete, with a first look at her picks
  Quiz.prototype.showComplete = function () {
    var self = this;
    var profile = this.profile;
    this.card(5,
      '<div class="mystyle-complete">' +
        '<p class="mystyle-complete__tick" aria-hidden="true">✓</p>' +
        '<h2>Profile Complete!</h2>' +
        '<p>Your personalized style recommendations are ready.</p>' +
        '<ul class="mystyle-preview" data-preview><li class="mystyle-note" data-status>Finding your picks…</li></ul>' +
        '<div class="mystyle-actions">' +
          '<a class="mystyle-btn" href="' + esc(C.recommendationsUrl) + '">View All Recommendations</a>' +
          '<a class="mystyle-btn mystyle-btn--secondary" href="' + esc(C.shopUrl) + '">Continue Shopping</a></div>' +
        '<button type="button" class="mystyle-text-link mystyle-text-link--caps" data-back>← Back to Preferences</button>' +
      '</div>');
    this.onBack(function () { this.showPreferences(); });
    var preview = this.view.querySelector('[data-preview]');
    getPicks(profile, 4, function () { self.slow(); }).then(function (items) {
      var shown = items.filter(function (i) { return productInfo[i.handle]; });
      preview.innerHTML = shown.length ? shown.map(function (i) {
        var p = productInfo[i.handle];
        return '<li><a href="' + esc(C.rootUrl + 'products/' + i.handle) + '">' +
          (p.image ? '<img src="' + esc(withParam(p.image, 'width=300')) + '" alt="" loading="lazy" width="150" height="200">' : '<span class="mystyle-preview__blank"></span>') +
          '<span class="mystyle-preview__name">' + esc(p.title) + '</span><span class="mystyle-preview__price">' + esc(money(p.price)) + '</span></a></li>';
      }).join('') : '<li class="mystyle-note">Your picks will appear here as the new collection arrives.</li>';
    }).catch(function (err) { preview.innerHTML = '<li class="mystyle-error">' + esc(err.message) + '</li>'; });
  };

  function sizeTiles(shape) {
    return '<ul class="mystyle-size-tiles">' + Object.keys(shape.size_recommendation_by_category || {}).map(function (key) {
      var size = String(shape.size_recommendation_by_category[key]);
      var halves = size.split('/');
      if (halves.length === 2 && halves[0] === halves[1]) size = halves[0];   // co-ords "XS/XS" -> "XS"
      return '<li><span>' + esc(SIZE_LABELS[key] || key.replace(/([A-Z])/g, ' $1').toLowerCase()) + '</span><strong>' + esc(size) + '</strong></li>';
    }).join('') + '</ul>';
  }

  // ------------------------------------------------- My Recommendations

  function Recommendations(root) { Page.call(this, root); }
  Recommendations.prototype = Object.create(Page.prototype);

  Recommendations.prototype.start = function () {
    var self = this;
    var title = 'Your Personalized Recommendations';
    if (!token) { this.notice(title, 'Sign in to see pieces chosen for your shape and style.', ['Sign In', signInUrl()]); return; }
    this.show(LOADING);
    loadProfile(function () { self.slow(); }).then(function (profile) {
      if (!profile) { self.notice(title, 'Build your style profile and we’ll pick pieces for your shape and style.', ['Get Your Style Profile', C.pageUrl]); return; }
      self.render(profile);
    }).catch(function (err) { self.notice(title, esc(err.message)); });
  };

  Recommendations.prototype.render = function (profile) {
    var self = this;
    var shape = profile.shape_profile || {};
    var sizes = shape.size_recommendation_by_category || {};
    var style = profile.style_profile || {};
    var named = function (items, labels) {
      var map = {};
      (labels || []).forEach(function (o) { map[o[0]] = o[1]; });
      return (items || []).map(function (v) { return map[v] || v; }).join(', ') || 'Any';
    };
    var row = function (label, value) { return value ? '<div><dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd></div>' : ''; };
    this.show(
      '<div class="mystyle-recs">' +
        '<aside class="mystyle-recs__side">' +
          '<h2 class="mystyle-side-title">Filters</h2><div class="mystyle-filters" data-filters></div>' +
          '<h2 class="mystyle-side-title">Your Profile</h2>' +
          '<dl class="mystyle-profile-card">' +
            row('Shape', capitalize(shape.shape_class)) +
            row('Tops size', sizes.tops) + row('Bottoms size', sizes.trousers || sizes.skirts) + row('Dresses size', sizes.dresses) +
            row('Colors', named(style.preferred_colors)) +
            row('Silhouettes', named(style.preferred_silhouettes, SILHOUETTES)) +
            row('Occasions', named(style.occasions, OCCASIONS)) +
          '</dl>' +
          '<p class="mystyle-side-links"><a href="' + esc(withParam(C.pageUrl, 'step=style')) + '">Update Style</a></p>' +
        '</aside>' +
        '<div class="mystyle-recs__main">' +
          '<header class="mystyle-page-header"><h1>Your Personalized Recommendations</h1><p class="mystyle-subtitle">Based on your shape and style preferences</p></header>' +
          '<p class="mystyle-note" data-status></p>' +
          '<ul class="grid product-grid grid--2-col-tablet-down grid--4-col-desktop mystyle-grid" data-list></ul>' +
        '</div>' +
      '</div>');
    var list = this.view.querySelector('[data-list]');
    getPicks(profile, 24, function () { self.slow(); }).then(function (items) {
      var status = self.view.querySelector('[data-status]');
      if (status) status.textContent = '';
      self.filters(items);
      return renderCards(list, items.map(function (i) { return pickCard(profile, i); }), 'Your recommendations will appear here as the new collection arrives.');
    }).catch(function (err) { list.innerHTML = '<li class="mystyle-empty">' + esc(err.message) + '</li>'; });
  };

  Recommendations.prototype.filters = function (items) {
    var box = this.view.querySelector('[data-filters]');
    var list = this.view.querySelector('[data-list]');
    var present = {};
    items.forEach(function (i) { present[i.category] = true; });
    var categories = CATEGORY_ORDER.filter(function (c) { return present[c]; });
    box.innerHTML = categories.map(function (c) {
      return '<label class="mystyle-filter"><input type="checkbox" value="' + esc(c) + '"><span>' + esc(c) + '</span></label>';
    }).join('') || '<p class="mystyle-note">No filters yet.</p>';
    box.addEventListener('change', function () {
      var chosen = Array.prototype.map.call(box.querySelectorAll('input:checked'), function (i) { return i.value; });
      var shown = 0;
      list.querySelectorAll('.mystyle-card').forEach(function (card) {
        card.hidden = chosen.length > 0 && chosen.indexOf(card.dataset.category) === -1;
        if (!card.hidden) shown++;
      });
      var empty = list.querySelector('[data-filter-empty]');
      if (!shown && !empty) {
        empty = el('<li class="mystyle-empty" data-filter-empty>No recommendations match your selected filters. <button type="button" class="mystyle-link">Clear filters</button></li>');
        empty.querySelector('button').addEventListener('click', function () {
          box.querySelectorAll('input').forEach(function (i) { i.checked = false; });
          box.dispatchEvent(new Event('change'));
        });
        list.appendChild(empty);
      } else if (shown && empty) {
        empty.remove();
      }
    });
  };

  // ------------------------------------------------- New Releases

  // The engine's rule for "new" (M9, NEW_RELEASES_WINDOW_DAYS in the API's
  // constants): published within 30 days of today -- or, between drops,
  // within 30 days of the newest launch, so the latest drop stays new until
  // the next. Here for signed-out shoppers, who see the pieces without the
  // API; by date, as the API counts. Newest first.
  var NEW_WINDOW_DAYS = 30;
  function newReleases(products) {
    var day = 864e5;
    var today = Date.parse(new Date().toISOString().slice(0, 10));
    var dated = products.map(function (p) { return { p: p, t: Date.parse(String(p.published_at).slice(0, 10)) }; })
      .filter(function (x) { return !isNaN(x.t) && x.t <= today; });
    if (!dated.length) return [];
    var anchor = dated.some(function (x) { return today - x.t <= NEW_WINDOW_DAYS * day; })
      ? today : Math.max.apply(null, dated.map(function (x) { return x.t; }));
    return dated.filter(function (x) { return anchor - x.t <= NEW_WINDOW_DAYS * day; })
      .sort(function (a, b) { return b.t - a.t; })
      .map(function (x) { return x.p; });
  }

  function NewReleases(root) { Page.call(this, root); }
  NewReleases.prototype = Object.create(Page.prototype);

  NewReleases.prototype.start = function () {
    var self = this;
    this.show(
      '<header class="mystyle-page-header"><h1>New Releases</h1><p class="mystyle-subtitle" data-subtitle>The newest pieces from the collection</p></header>' +
      '<div data-banner></div><p class="mystyle-note" data-status></p>' +
      '<ul class="grid product-grid grid--2-col-tablet-down grid--5-col-desktop mystyle-grid" data-list></ul>');
    var list = this.view.querySelector('[data-list]');
    var banner = this.view.querySelector('[data-banner]');
    var invite = function (action, text) {
      banner.innerHTML = '<p class="mystyle-banner"><a href="' + esc(action[1]) + '">' + esc(action[0]) + '</a> ' + text + '</p>';
    };
    var newest = function () {
      return storeProducts().then(function (products) {
        var items = newReleases(products.filter(styleOf))
          .map(function (p) { return { handle: p.handle, category: productInfo[p.handle] && productInfo[p.handle].category }; });
        return renderCards(list, items, 'New pieces will appear here as the collection arrives.');
      });
    };
    if (!token) { invite(['Sign in', signInUrl()], 'to see how each piece matches your shape and style.'); newest(); return; }
    loadProfile(function () { self.slow(); }).then(function (profile) {
      if (!profile) { invite(['Build your style profile', C.pageUrl], 'to see your match and size for each piece.'); return newest(); }
      self.view.querySelector('[data-subtitle]').textContent = 'Matched to your shape and style';
      return storeProducts().then(function (products) {
        return api('/shopify/new-releases', { method: 'POST', onSlow: function () { self.slow(); },
          body: { session_id: profile.session_id, limit: 20, products: products, launch: C.launch } });
      }).then(function (data) {
        var status = self.view.querySelector('[data-status]');
        if (status) status.textContent = '';
        return renderCards(list, data.items.map(function (i) {
          var a = i.availability || {};
          var line = sizeLine(a, 'Recommended size: ');
          return { handle: i.handle, match: i.match_score, category: i.category, reason: i.reason,
                   size: line.size, sizeTone: line.sizeTone, soldOut: i.in_stock_in_size === false };
        }), 'New pieces matched to you will appear here as the collection arrives.');
      });
    }).catch(function (err) { list.innerHTML = '<li class="mystyle-empty">' + esc(err.message) + '</li>'; });
  };

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

  var PAGES = { style: Quiz, recommendations: Recommendations, 'new': NewReleases };

  function boot() {
    document.querySelectorAll('[data-mystyle-fit]').forEach(initFit);
    document.querySelectorAll('[data-mystyle-picks]').forEach(initPicks);
    document.querySelectorAll('[data-mystyle-page]').forEach(function (root) {
      var Kind = PAGES[root.dataset.mystylePage] || Quiz;
      new Kind(root).start();
    });
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
