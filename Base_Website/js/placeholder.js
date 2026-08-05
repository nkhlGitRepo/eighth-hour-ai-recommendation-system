/**
 * placeholder.js
 * Generates a simple inline SVG "image" for a product, standing in for
 * real product photography (which we intentionally don't scrape/host here).
 */

// A small neutral palette so cards don't all look identical.
const PLACEHOLDER_PALETTE = ["#e7e1d6", "#ddd6c8", "#d7cbb8", "#e3ddd0", "#cfc3ae"];

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
