/**
 * render-home.js
 * Populates the homepage's category tiles and best-seller grid.
 * Runs only on index.html.
 */
document.addEventListener("DOMContentLoaded", () => {
  renderCategoryTiles();
  renderBestSellers();
});

function renderCategoryTiles() {
  const grid = document.getElementById("categoryGrid");
  if (!grid) return;
  grid.innerHTML = CATEGORIES.map((category) => {
    const slug = slugify(category);
    // Represent each category with the first product filed under it, so the
    // tiles show real garments instead of generated swatches. Falls back to a
    // placeholder for any category with nothing in it yet.
    const first = PRODUCTS.find((p) => p.category === category);
    const img = first
      ? productImage(first, 0, category, 500, 650)
      : placeholderImage(category, 500, 650);
    return `
      <a class="category-tile" href="collection.html?category=${slug}">
        <img src="${img}" alt="${category}" />
        <span>${category}</span>
      </a>`;
  }).join("");
}

function renderBestSellers() {
  const grid = document.getElementById("bestSellerGrid");
  if (!grid) return;
  const bestSellers = PRODUCTS.filter((product) => product.bestSeller);
  grid.innerHTML = bestSellers.map(productCardHtml).join("");
}

// Shared by home + collection pages. Mirrors the storefront's card: image,
// then the colours it comes in, then name and price -- all left-aligned.
function productCardHtml(product) {
  const img = productImage(product, 0, product.name, 450, 600);
  const swatches = (product.colors || [])
    .map((c) => `<i style="background:${colorHex(c)}" title="${c}"></i>`)
    .join("");
  return `
    <a class="product-card" href="product.html?slug=${product.slug}">
      <div class="thumb"><img src="${img}" alt="${product.name}" loading="lazy" /></div>
      ${swatches ? `<div class="swatches">${swatches}</div>` : ""}
      ${product.bestSeller ? '<span class="badge-best">Best Seller</span>' : ""}
      <div class="name">${product.name}</div>
      <div class="price">$${product.price.toFixed(2)}</div>
    </a>`;
}

