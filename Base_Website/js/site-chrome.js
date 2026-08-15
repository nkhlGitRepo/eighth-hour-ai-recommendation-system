/**
 * site-chrome.js
 * Renders the shared header and footer into every page.
 *
 * Previously each of the 13 pages carried its own hand-copied 32-line header.
 * Keeping those in step by hand is what let the nav drift, so the markup now
 * lives here once and each page just declares where it goes.
 *
 * Contract with the other header scripts: this renders on DOMContentLoaded and
 * MUST be loaded before them, so its listener runs first and the elements they
 * look up (#menuToggle, #mainNav, #cartCount, #loginLink, #accountLink,
 * #logoutLink, #myRecommendationsLink, .style-profile-link, a.logo) already
 * exist by the time they run.
 */

// Where the site root sits relative to this page -- pages live at the root and
// under frontend/pages/, so every link below is prefixed with this. Derived
// from this script's own src, the one thing that points back at the root from
// either depth. (Same approach as placeholder.js; see SITE_ROOT there.)
const CHROME_ROOT = (function () {
  const self = document.currentScript && document.currentScript.getAttribute("src");
  return self ? self.replace(/js\/site-chrome\.js.*$/, "") : "";
})();

// Thin line icons matching the storefront's own header set.
const ICONS = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5" stroke-linecap="round"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="12" cy="8" r="4"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0" stroke-linecap="round"/></svg>',
  bag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M5 8h14l-1 12H6L5 8z" stroke-linejoin="round"/><path d="M9 8V6a3 3 0 0 1 6 0v2" stroke-linecap="round"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 9l6 6 6-6" stroke-linecap="round"/></svg>',
};

/**
 * The primary nav.
 *
 * "Shop" keeps the storefront's own dropdown of categories and fabrics. The
 * three entries after it are this project's features, given the same weight as
 * Size Guide and About so they read as part of the store rather than bolted on.
 */
function navItems() {
  return [
    {
      label: "Shop",
      href: "collection.html",
      children: [
        { label: "Tops", href: "collection.html?category=tops" },
        { label: "Skirts", href: "collection.html?category=skirts" },
        { label: "Dresses", href: "collection.html?category=dresses" },
        { label: "Trousers", href: "collection.html?category=trousers" },
        { label: "Vests", href: "collection.html?category=vests" },
        { label: "Co-ord Sets", href: "collection.html?category=co-ord-sets" },
        { label: "Handwoven Silks", href: "collection.html?fabric=handwoven-silk" },
        { label: "Natural Crepe", href: "collection.html?fabric=natural-crepe" },
      ],
    },
    // .style-profile-link: style-profile-link.js relabels this "Update Style"
    // once a profile exists, so no label is hardcoded as final here.
    { label: "My Style", href: "frontend/pages/intake-flow.html", className: "style-profile-link" },
    { label: "New Releases", href: "frontend/pages/new-releases.html" },
    // Hidden until a style profile exists -- recommendations-nav-link.js reveals it.
    { label: "My Recommendations", href: "frontend/pages/recommendations.html", id: "myRecommendationsLink", hidden: true },
    { label: "Size Guide", href: "size-guide.html" },
    { label: "About", href: "about.html" },
  ];
}

function linkHtml(item) {
  const attrs = [
    `href="${CHROME_ROOT}${item.href}"`,
    item.id ? `id="${item.id}"` : "",
    item.className ? `class="${item.className}"` : "",
    item.hidden ? 'style="display: none;"' : "",
  ].filter(Boolean).join(" ");
  return `<a ${attrs}>${item.label}</a>`;
}

function headerHtml() {
  const items = navItems().map((item) => {
    if (!item.children) return linkHtml(item);
    return `
      <div class="nav-group">
        <a class="nav-group-label" href="${CHROME_ROOT}${item.href}">${item.label}<span class="nav-caret">${ICONS.chevron}</span></a>
        <div class="nav-dropdown">
          ${item.children.map(linkHtml).join("")}
        </div>
      </div>`;
  }).join("");

  return `
    <div class="header-inner">
      <a class="logo" href="${CHROME_ROOT}index.html">
        <img src="${CHROME_ROOT}images/brand/logo-black.png" alt="Eighth Hour" />
      </a>

      <button class="menu-toggle" id="menuToggle" aria-label="Toggle menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>

      <nav class="main-nav" id="mainNav">${items}</nav>

      <div class="header-icons">
        <button class="icon-btn" id="searchToggle" type="button" aria-label="Search">${ICONS.search}</button>

        <!--
          Account lives behind the person icon, matching the storefront. All
          three links keep the IDs auth-nav-link.js toggles: it shows the plain
          link when logged out and the menu trigger when logged in.
        -->
        <div class="account-menu">
          <a class="icon-btn" id="loginLink" href="${CHROME_ROOT}frontend/pages/login.html" aria-label="Log in">${ICONS.user}</a>
          <button class="icon-btn" id="accountTrigger" type="button" aria-label="Account" aria-expanded="false" style="display: none;">${ICONS.user}</button>
          <div class="account-dropdown" id="accountDropdown">
            <a href="${CHROME_ROOT}frontend/pages/account.html" id="accountLink">My Account</a>
            <a href="#" id="logoutLink">Log Out</a>
          </div>
        </div>

        <a class="icon-btn cart-btn" href="${CHROME_ROOT}cart.html" aria-label="Cart">
          ${ICONS.bag}<span class="cart-count" id="cartCount">0</span>
        </a>
      </div>
    </div>

    <div class="header-search" id="headerSearch" hidden>
      <input type="search" id="searchInput" placeholder="Search products" aria-label="Search products" />
      <div class="search-results" id="searchResults"></div>
    </div>`;
}

function footerHtml() {
  const column = (title, links) => `
    <div class="footer-col">
      <h4>${title}</h4>
      ${links.map((l) => `<a href="${CHROME_ROOT}${l.href}">${l.label}</a>`).join("")}
    </div>`;

  return `
    <div class="footer-inner">
      <div class="footer-brand">
        <img src="${CHROME_ROOT}images/brand/logo-black.png" alt="Eighth Hour" />
      </div>
      ${column("Links", [
        { label: "Home page", href: "index.html" },
        { label: "Women", href: "collection.html" },
        { label: "Size Guide", href: "size-guide.html" },
        { label: "About", href: "about.html" },
      ])}
      ${column("Your Profile", [
        { label: "My Style", href: "frontend/pages/intake-flow.html" },
        { label: "New Releases", href: "frontend/pages/new-releases.html" },
        { label: "My Recommendations", href: "frontend/pages/recommendations.html" },
        { label: "My Account", href: "frontend/pages/account.html" },
      ])}
      ${column("Help", [
        { label: "Contact us", href: "contact.html" },
        { label: "FAQ", href: "faq.html" },
      ])}
    </div>
    <div class="footer-base">
      <div class="footer-legal">
        <a href="${CHROME_ROOT}faq.html">FAQ</a>
        <a href="${CHROME_ROOT}faq.html">Terms and Conditions</a>
        <a href="${CHROME_ROOT}faq.html">Privacy Policy</a>
      </div>
      <span class="footer-region">US</span>
    </div>`;
}

/** Client-side product search over the local catalog. */
function wireUpSearch() {
  const toggle = document.getElementById("searchToggle");
  const panel = document.getElementById("headerSearch");
  const input = document.getElementById("searchInput");
  const results = document.getElementById("searchResults");
  if (!toggle || !panel || !input || !results) return;

  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    if (query.length < 2 || typeof PRODUCTS === "undefined") {
      results.innerHTML = "";
      return;
    }
    const matches = PRODUCTS.filter((p) =>
      p.name.toLowerCase().includes(query) ||
      p.category.toLowerCase().includes(query) ||
      p.fabric.toLowerCase().includes(query)
    ).slice(0, 6);

    results.innerHTML = matches.length
      ? matches.map((p) => `
          <a href="${CHROME_ROOT}product.html?slug=${p.slug}">
            <img src="${typeof productImage === "function" ? productImage(p, 0, p.name, 80, 100) : ""}" alt="" />
            <span>${p.name}</span>
            <span class="search-price">$${p.price.toFixed(2)}</span>
          </a>`).join("")
      : `<p class="search-empty">No products match "${input.value.trim()}".</p>`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector("[data-site-header]");
  if (header) {
    header.className = "site-header";
    header.innerHTML = headerHtml();
  }
  const footer = document.querySelector("[data-site-footer]");
  if (footer) {
    footer.className = "site-footer";
    footer.innerHTML = footerHtml();
  }
  wireUpSearch();

  // Mark the current page in the nav.
  const here = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".main-nav a").forEach((link) => {
    if (link.getAttribute("href").split("?")[0].endsWith(here)) link.classList.add("current");
  });
});
