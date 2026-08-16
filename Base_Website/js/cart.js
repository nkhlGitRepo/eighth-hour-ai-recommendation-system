/**
 * cart.js
 * Minimal shopping cart persisted to localStorage. No backend involved —
 * this is a local demo, so "checkout" simply shows a message.
 */

const CART_KEY = "eighthHourCart";

function getCart() {
  const raw = localStorage.getItem(CART_KEY);
  return raw ? JSON.parse(raw) : [];
}

function saveCart(cart) {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
  updateCartCount();
}

function addToCart(slug, color, size, qty = 1) {
  const cart = getCart();
  const existing = cart.find((item) => item.slug === slug && item.color === color && item.size === size);
  if (existing) {
    existing.qty += qty;
  } else {
    cart.push({ slug, color, size, qty });
  }
  saveCart(cart);
}

function removeFromCart(index) {
  const cart = getCart();
  cart.splice(index, 1);
  saveCart(cart);
}

function cartItemCount() {
  return getCart().reduce((total, item) => total + item.qty, 0);
}

function updateCartCount() {
  const el = document.getElementById("cartCount");
  if (!el) return;
  const count = cartItemCount();
  el.textContent = count;
  // The header shows a bag icon; an empty bag shouldn't carry a "0" badge.
  el.setAttribute("data-empty", String(count === 0));
}

/* ------------------------------------------------------------------ drawer -- */

/**
 * The cart is a slide-out drawer rather than a page, matching the storefront.
 * cart.html still exists and still works as a direct link, so nothing depends
 * on the drawer being available.
 */

function openCartDrawer() {
  const drawer = document.getElementById("cartDrawer");
  if (!drawer) return;
  renderCartDrawer();
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  // Stop the page behind scrolling under the drawer.
  document.body.style.overflow = "hidden";
  document.getElementById("cartDrawerClose")?.focus();
}

function closeCartDrawer() {
  const drawer = document.getElementById("cartDrawer");
  if (!drawer) return;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function renderCartDrawer() {
  const list = document.getElementById("cartDrawerItems");
  const footer = document.getElementById("cartDrawerFooter");
  const totalEl = document.getElementById("cartDrawerTotal");
  if (!list) return;

  const cart = getCart();
  if (!cart.length) {
    list.innerHTML = `
      <div class="cart-drawer__empty">
        <p>Your cart is empty</p>
        <a class="btn btn-secondary" href="${cartRoot()}collection.html">Continue shopping</a>
      </div>`;
    if (footer) footer.hidden = true;
    return;
  }

  let total = 0;
  list.innerHTML = cart.map((item, index) => {
    const product = typeof PRODUCTS !== "undefined"
      ? PRODUCTS.find((p) => p.slug === item.slug) : null;
    if (!product) return "";
    total += product.price * item.qty;
    // Explicit colour: the drawer shows what was actually added, not the
    // customer's preferred colourway (see productImage()).
    const img = typeof productImage === "function"
      ? productImage(product, 0, product.name, 160, 210, item.color) : "";
    return `
      <div class="cart-drawer__row">
        <img src="${img}" alt="${product.name}" />
        <div class="cart-drawer__meta">
          <a href="${cartRoot()}product.html?slug=${product.slug}">${product.name}</a>
          <p class="muted">${item.color} · Size ${item.size}</p>
          <p class="muted">Qty ${item.qty}</p>
          <button type="button" class="cart-drawer__remove" data-index="${index}">Remove</button>
        </div>
        <div class="cart-drawer__price">$${(product.price * item.qty).toFixed(2)}</div>
      </div>`;
  }).join("");

  if (totalEl) totalEl.textContent = `$${total.toFixed(2)}`;
  if (footer) footer.hidden = false;

  list.querySelectorAll(".cart-drawer__remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      removeFromCart(Number(btn.dataset.index));
      renderCartDrawer();
      // Keep the standalone cart page in step when the drawer is used there.
      if (typeof renderCart === "function") renderCart();
    });
  });
}

/**
 * Path back to the site root. Pages live at two depths, so links built here
 * need the same prefix the shared chrome uses.
 */
function cartRoot() {
  return window.location.pathname.includes("/frontend/") ? "../../" : "";
}

document.addEventListener("DOMContentLoaded", () => {
  updateCartCount();

  document.getElementById("cartToggle")?.addEventListener("click", (event) => {
    event.preventDefault();          // the href is a no-JS fallback
    openCartDrawer();
  });
  document.getElementById("cartDrawerClose")?.addEventListener("click", closeCartDrawer);
  document.getElementById("cartDrawerOverlay")?.addEventListener("click", closeCartDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCartDrawer();
  });

  document.getElementById("cartDrawerCheckout")?.addEventListener("click", () => {
    alert("This is a demo storefront — checkout isn't connected to a payment provider.");
  });
});
