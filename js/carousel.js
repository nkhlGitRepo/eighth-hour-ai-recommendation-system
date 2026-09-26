/**
 * carousel.js
 * The homepage hero carousel: three slides, auto-advancing, with clickable dots.
 *
 * Deliberately plain: a transform on a flex track plus an interval. No library,
 * no touch-gesture layer -- the storefront's hero is a simple rotating banner
 * and anything more would be weight for its own sake.
 */

const HERO_INTERVAL_MS = 6000;

document.addEventListener("DOMContentLoaded", () => {
  const carousel = document.getElementById("heroCarousel");
  const track = document.getElementById("heroTrack");
  const dotsHolder = document.getElementById("heroDots");
  if (!carousel || !track || !dotsHolder) return;

  const slides = [...track.querySelectorAll(".hero-slide")];
  if (slides.length < 2) return;

  let index = 0;
  let timer = null;

  const dots = slides.map((_, i) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "hero-dot";
    dot.setAttribute("role", "tab");
    dot.setAttribute("aria-label", `Slide ${i + 1} of ${slides.length}`);
    dot.addEventListener("click", () => {
      show(i);
      restart();
    });
    dotsHolder.appendChild(dot);
    return dot;
  });

  function show(next) {
    index = (next + slides.length) % slides.length;
    track.style.transform = `translateX(-${index * 100}%)`;
    dots.forEach((d, i) => {
      d.classList.toggle("active", i === index);
      d.setAttribute("aria-selected", String(i === index));
    });
    slides.forEach((s, i) => s.setAttribute("aria-hidden", String(i !== index)));
  }

  function restart() {
    clearInterval(timer);
    // Honour a reduced-motion preference by simply not auto-advancing; the
    // dots still work, so no content becomes unreachable. Guarded because
    // matchMedia is absent in some non-browser environments, and an exception
    // here would silently kill auto-advance rather than just the check.
    const reduceMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    timer = setInterval(() => show(index + 1), HERO_INTERVAL_MS);
  }

  // Pause while the pointer is over the banner, so a slide can't change out
  // from under someone reading it.
  carousel.addEventListener("mouseenter", () => clearInterval(timer));
  carousel.addEventListener("mouseleave", restart);

  show(0);
  restart();
});
