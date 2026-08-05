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
    const img = placeholderImage(category, 500, 650);
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

// Shared by home + collection pages.
function productCardHtml(product) {
  const img = placeholderImage(product.name, 450, 600);
  return `
    <a class="product-card" href="product.html?slug=${product.slug}">
      <div class="thumb"><img src="${img}" alt="${product.name}" /></div>
      ${product.bestSeller ? '<span class="badge-best">Best Seller</span><br/>' : ""}
      <div class="name">${product.name}</div>
      <div class="price">$${product.price.toFixed(2)}</div>
    </a>`;
}
