/**
 * render-collection.js
 * Reads ?category= and/or ?fabric= from the URL, builds the filter sidebar,
 * and re-renders the product grid whenever a filter checkbox changes.
 * Runs only on collection.html.
 */
document.addEventListener("DOMContentLoaded", () => {
  const grid = document.getElementById("productGrid");
  if (!grid) return; // not on the collection page

  const params = new URLSearchParams(window.location.search);
  const state = {
    categories: new Set(params.get("category") ? [params.get("category")] : []),
    fabrics: new Set(params.get("fabric") ? [params.get("fabric")] : []),
  };

  setHeading(state);
  buildFilterPanel(state);
  renderGrid(state);

  // Filters are collapsed behind a button, as on the storefront. Opened
  // automatically when arriving with a filter already applied via the URL,
  // so the reason the grid is narrowed is visible.
  const toggle = document.getElementById("filterToggle");
  const panel = document.getElementById("filterPanel");
  if (toggle && panel) {
    if (state.categories.size || state.fabrics.size) panel.classList.add("open");
    toggle.addEventListener("click", () => panel.classList.toggle("open"));
  }
});

function setHeading(state) {
  const heading = document.getElementById("collectionHeading");
  const title = document.getElementById("pageTitle");
  let label = "Shop All";
  if (state.categories.size) {
    label = CATEGORIES.find((c) => slugify(c) === [...state.categories][0]) || label;
  } else if (state.fabrics.size) {
    label = FABRICS.find((f) => slugify(f) === [...state.fabrics][0]) || label;
  }
  heading.textContent = label;
  title.textContent = `${label} — Eighth Hour`;
}

function buildFilterPanel(state) {
  const panel = document.getElementById("filterPanel");
  panel.innerHTML = `
    <div><h4>Category</h4>
    ${CATEGORIES.map((c) => checkboxHtml("category", c, state.categories)).join("")}
    </div>
    <div><h4>Fabric</h4>
    ${FABRICS.map((f) => checkboxHtml("fabric", f, state.fabrics)).join("")}</div>
  `;
  panel.querySelectorAll("input[type=checkbox]").forEach((box) => {
    box.addEventListener("change", () => {
      const group = box.dataset.group === "category" ? state.categories : state.fabrics;
      if (box.checked) group.add(box.value);
      else group.delete(box.value);
      renderGrid(state);
    });
  });
}

function checkboxHtml(group, label, selectedSet) {
  const value = slugify(label);
  const checked = selectedSet.has(value) ? "checked" : "";
  return `
    <label>
      <input type="checkbox" data-group="${group}" value="${value}" ${checked} />
      ${label}
    </label>`;
}

function renderGrid(state) {
  const grid = document.getElementById("productGrid");
  const count = document.getElementById("resultCount");

  const results = PRODUCTS.filter((product) => {
    const matchesCategory = state.categories.size === 0 || state.categories.has(product.categorySlug);
    const matchesFabric = state.fabrics.size === 0 || state.fabrics.has(product.fabricSlug);
    return matchesCategory && matchesFabric;
  });

  count.textContent = `${results.length} product${results.length === 1 ? "" : "s"}`;
  grid.innerHTML = results.map(productCardHtml).join("") || `<p class="muted">No products match this filter.</p>`;
}
