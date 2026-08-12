/**
 * render-product.js
 * Looks up the product by ?slug= and renders its detail page, including
 * color/size selection and an "add to cart" action.
 * Runs only on product.html.
 */
const PRODUCT_API_BASE = "http://localhost:8000";

/**
 * Looks up this customer's fit-checked size for a product, if a style
 * profile session exists. Returns null (never throws) when there's no
 * active session, the request fails, or the recommended size isn't one
 * of the product's actual sizes -- callers fall back to the default.
 */
async function getRecommendedSize(productSku) {
  const sessionId = localStorage.getItem("currentSessionId");
  if (!sessionId) return null;

  try {
    const response = await fetch(`${PRODUCT_API_BASE}/fit-check/${sessionId}/${productSku}`, {
      method: "POST",
    });
    if (!response.ok) return null;
    const result = await response.json();
    return result.recommended_size || null;
  } catch (error) {
    return null;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const container = document.getElementById("productDetail");
  if (!container) return;

  const params = new URLSearchParams(window.location.search);
  const product = PRODUCTS.find((p) => p.slug === params.get("slug"));

  if (!product) {
    container.innerHTML = `<p>Product not found. <a href="collection.html">Back to shop</a>.</p>`;
    return;
  }

  document.getElementById("pageTitle").textContent = `${product.name} — Eighth Hour`;

  const recommendedSize = await getRecommendedSize(product.slug);
  const defaultSize = recommendedSize && product.sizes.includes(recommendedSize)
    ? recommendedSize
    : product.sizes[0];
  const selection = { color: product.colors[0], size: defaultSize };
  const mainImg = placeholderImage(product.name, 700, 900);
  const thumbs = [product.name, `${product.name} detail`, `${product.name} back`];

  container.innerHTML = `
    <div class="product-detail">
      <div>
        <div class="gallery-main"><img id="mainImage" src="${mainImg}" alt="${product.name}" /></div>
        <div class="gallery-thumbs">
          ${thumbs.map((label) => `<img src="${placeholderImage(label, 200, 260)}" alt="${label}" />`).join("")}
        </div>
      </div>
      <div>
        ${product.bestSeller ? '<span class="badge-best">Best Seller</span>' : ""}
        <h1>${product.name}</h1>
        <p class="price-lg">$${product.price.toFixed(2)}</p>
        <p class="muted">${product.description}</p>

        <div class="option-group">
          <h4>Color: <span id="selectedColor">${selection.color}</span></h4>
          <div class="swatch-row" id="colorRow">
            ${product.colors.map((c) => swatchHtml(c, c === selection.color)).join("")}
          </div>
        </div>

        <div class="option-group">
          <h4>Size: <span id="selectedSize">${selection.size}</span></h4>
          <div class="swatch-row" id="sizeRow">
            ${product.sizes.map((s) => swatchHtml(s, s === selection.size)).join("")}
          </div>
        </div>

        <button id="addToCartBtn">Add to Cart</button>

        <div class="detail-tabs">
          <div class="detail-tab">
            <h4>Fabric &amp; Care</h4>
            <p class="muted">${product.fabric}. Dry clean only. Cool iron on the reverse side. Natural, small-batch dyeing means slight shade variation between pieces.</p>
          </div>
          <div class="detail-tab">
            <h4>Shipping &amp; Returns</h4>
            <p class="muted">Made to order; standard dispatch lead time applies. Returns are accepted only for incorrect size, color, or shipment.</p>
          </div>
        </div>
      </div>
    </div>
  `;

  wireUpOptionRow("colorRow", "selectedColor", selection, "color");
  wireUpOptionRow("sizeRow", "selectedSize", selection, "size");

  document.getElementById("addToCartBtn").addEventListener("click", () => {
    addToCart(product.slug, selection.color, selection.size, 1);
    alert(`Added to cart: ${product.name} — ${selection.color}, size ${selection.size}`);
  });
});

function swatchHtml(value, selected) {
  return `<button type="button" class="swatch ${selected ? "selected" : ""}" data-value="${value}">${value}</button>`;
}

function wireUpOptionRow(rowId, labelId, selection, key) {
  const row = document.getElementById(rowId);
  row.querySelectorAll(".swatch").forEach((btn) => {
    btn.addEventListener("click", () => {
      selection[key] = btn.dataset.value;
      document.getElementById(labelId).textContent = btn.dataset.value;
      row.querySelectorAll(".swatch").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
    });
  });
}
