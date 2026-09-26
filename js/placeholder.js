/**
 * placeholder.js
 * Resolves the image to show for a product: the real photograph from
 * images/products/ when we have one, otherwise a generated inline SVG.
 *
 * The photographs are the studio shots from eighth-hour.com, stored locally
 * rather than hot-linked so the site renders offline and doesn't depend on
 * Shopify CDN URLs that carry version parameters.
 */

// A small neutral palette so cards don't all look identical.
const PLACEHOLDER_PALETTE = ["#e7e1d6", "#ddd6c8", "#d7cbb8", "#e3ddd0", "#cfc3ae"];

/**
 * Where the site root sits relative to the current page.
 *
 * Product image paths are stored root-relative in data.js ("images/..."), but
 * pages live at two depths -- index.html at the root and the intake/
 * recommendations pages under frontend/pages/ -- so a bare relative path would
 * 404 on one of them. Derived from this script's own src, which is the one
 * thing that reliably points back at the root from either depth.
 */
const SITE_ROOT = (function () {
  const self = document.currentScript && document.currentScript.getAttribute("src");
  if (!self) return "";
  return self.replace(/js\/placeholder\.js.*$/, "");
})();

/**
 * Image URL for a product, by index into its gallery.
 *
 * Falls back to the generated placeholder when the product has no photograph
 * at that index, so a product added to data.js without images still renders a
 * card rather than a broken image icon.
 *
 * @param product  a PRODUCTS entry, or a slug string to look one up by
 * @param index    which gallery image (0 = primary)
 * @param label    alt/placeholder text when falling back
 */
/**
 * The customer's colour preferences from their style profile, parsed once per
 * page rather than on every card.
 */
let _preferredColors = null;
function preferredColors() {
  if (_preferredColors) return _preferredColors;
  try {
    const saved = JSON.parse(localStorage.getItem("intakeSession") || "{}");
    _preferredColors = (saved.styleProfile && saved.styleProfile.preferred_colors) || [];
  } catch (error) {
    _preferredColors = [];        // corrupt storage: behave as if none were set
  }
  return _preferredColors;
}

/**
 * Which colourway to show a product in, absent an explicit choice.
 *
 * If the customer picked colour preferences and this product comes in one of
 * them, that colour wins -- so a recommendation card, and the product page it
 * leads to, both show the garment as they would actually buy it. Where several
 * preferred colours match, the product's own first matching colour is used:
 * deliberately independent of the order the preference checkboxes happened to
 * be ticked in, since they are a set rather than a ranking, so the same product
 * always resolves the same way.
 *
 * No preferences, or no overlap, gives the product's first colour -- exactly
 * what a visitor with no style profile sees.
 */
function preferredColorFor(product) {
  const colors = (product && product.colors) || [];
  if (!colors.length) return null;
  const wanted = preferredColors();
  if (!wanted.length) return colors[0];
  const set = new Set(wanted.map((c) => String(c).trim().toLowerCase()));
  return colors.find((c) => set.has(String(c).trim().toLowerCase())) || colors[0];
}

function productImage(product, index = 0, label = "", width = 600, height = 800, color = undefined) {
  const item =
    typeof product === "string"
      ? (typeof PRODUCTS !== "undefined" && PRODUCTS.find((p) => p.slug === product))
      : product;

  // Photographs are stored per colourway, so a customer selecting a colour sees
  // the garment in THAT colour rather than whichever one happens to be first.
  // Falls back to the default set when a colour has no photography of its own
  // (one variant on the real site genuinely has none), so the gallery still
  // shows the product instead of collapsing to a placeholder.
  // No explicit colour means "whatever this customer should see" -- so every
  // card across the site picks up the preferred colourway without each call
  // site having to know about preferences. The one caller that must NOT do
  // this is the cart, which passes the colour that was actually added.
  const wanted = color === undefined ? preferredColorFor(item) : color;

  let set = item && item.images;
  if (wanted && item && item.imagesByColor && item.imagesByColor[wanted]) {
    set = item.imagesByColor[wanted];
  }

  const src = set && set[index];
  if (src) return SITE_ROOT + src;
  return placeholderImage(label || (item && item.name) || String(product), width, height);
}

/** How many photographs exist for a product in a given colour. */
function productImageCount(product, color = undefined) {
  const item =
    typeof product === "string"
      ? (typeof PRODUCTS !== "undefined" && PRODUCTS.find((p) => p.slug === product))
      : product;
  if (!item) return 0;
  const wanted = color === undefined ? preferredColorFor(item) : color;
  if (wanted && item.imagesByColor && item.imagesByColor[wanted]) {
    return item.imagesByColor[wanted].length;
  }
  return (item.images || []).length;
}

function placeholderImage(label, width = 600, height = 800) {
  const bg = PLACEHOLDER_PALETTE[Math.abs(hashCode(label)) % PLACEHOLDER_PALETTE.length];
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <rect width="100%" height="100%" fill="${bg}" />
      <line x1="0" y1="0" x2="${width}" y2="${height}" stroke="#00000010" stroke-width="1" />
      <line x1="${width}" y1="0" x2="0" y2="${height}" stroke="#00000010" stroke-width="1" />
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
            font-family="Georgia, serif" font-size="${Math.max(14, width / 22)}" fill="#5b5044">
        ${escapeXml(label)}
      </text>
    </svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function hashCode(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return hash;
}

function escapeXml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
