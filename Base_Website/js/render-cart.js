/**
 * render-cart.js
 * Renders the contents of the localStorage cart on cart.html.
 */
document.addEventListener("DOMContentLoaded", () => {
  const list = document.getElementById("cartList");
  if (!list) return;
  renderCart();

  document.getElementById("checkoutBtn").addEventListener("click", () => {
    alert("This is a local demo — checkout is not implemented.");
  });
});

function renderCart() {
  const list = document.getElementById("cartList");
  const totalEl = document.getElementById("cartTotal");
  const cart = getCart();

  if (cart.length === 0) {
    list.innerHTML = `<p class="muted">Your cart is empty. <a href="collection.html">Continue shopping</a>.</p>`;
    totalEl.textContent = "";
    return;
  }

  let total = 0;
  list.innerHTML = cart.map((item, index) => {
    const product = PRODUCTS.find((p) => p.slug === item.slug);
    if (!product) return "";
    const lineTotal = product.price * item.qty;
    total += lineTotal;
    const img = productImage(product, 0, product.name, 160, 210);
    return `
      <div class="cart-row">
        <img src="${img}" alt="${product.name}" />
        <div>
          <div>${product.name}</div>
          <div class="muted">${item.color} · Size ${item.size} · Qty ${item.qty}</div>
        </div>
        <div>$${lineTotal.toFixed(2)}</div>
        <button class="btn-outline" onclick="removeAndRerender(${index})">Remove</button>
      </div>`;
  }).join("");

  totalEl.textContent = `Total: $${total.toFixed(2)}`;
}

function removeAndRerender(index) {
  removeFromCart(index);
  renderCart();
}
