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
function productImage(product, index = 0, label = "", width = 600, height = 800) {
  const item =
    typeof product === "string"
      ? (typeof PRODUCTS !== "undefined" && PRODUCTS.find((p) => p.slug === product))
      : product;
  const src = item && item.images && item.images[index];
  if (src) return SITE_ROOT + src;
  return placeholderImage(label || (item && item.name) || String(product), width, height);
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
