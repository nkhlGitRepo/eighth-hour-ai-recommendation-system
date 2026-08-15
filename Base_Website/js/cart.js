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

// Keep the header cart count correct on every page load.
document.addEventListener("DOMContentLoaded", updateCartCount);
