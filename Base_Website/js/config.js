/**
 * Where the styling-engine API lives. Every script that calls the API reads
 * window.EH_API_BASE, so this is the one line to change if the API moves.
 *
 * Loaded before any other script on every page. Served from localhost (serve.py
 * during development) it points at the local API; anywhere else -- the GitHub
 * Pages site -- it points at the hosted API on Render.
 *
 * If Render gave the service a different address than the one below (it adds
 * a suffix when the name is taken), paste the address shown on the service's
 * Render dashboard here.
 */
window.EH_API_BASE = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)
  ? "http://localhost:8000"
  : "https://eighth-hour-api.onrender.com";
