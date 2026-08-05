# Eighth Hour — Local Demo Clone

A local, static recreation of eighth-hour.com's structure and functionality,
built for reference/learning purposes. Plain HTML, CSS, and vanilla JS —
no build step, no framework, no dependencies.

## What this is (and isn't)

This clone matches the **real site's**:
- page structure and navigation (category + fabric collections, product pages, FAQ, about, contact, cart)
- product catalog data — real names, prices, colors, categories, and fabrics gathered from the live site
- client-side behavior (filtering, variant selection, a working localStorage cart)
- overall visual language (minimalist, neutral palette, serif headings)

It intentionally does **not** include:
- the real product photography or logo (replaced with generated placeholder graphics)
- the site's exact marketing/description copy (rewritten in our own words)
- any backend, payment processing, or real checkout

## How to run it

No installation needed. Either:

1. **Just open it**: double-click `index.html` to open it in a browser.
2. **Or serve it locally** (recommended, avoids any browser file-access quirks):
   ```bash
   cd "Eighth Hour"
   python3 -m http.server 8000
   ```
   Then visit http://localhost:8000

## File structure

```
Eighth Hour/
├── index.html              Homepage (hero, category tiles, best sellers)
├── collection.html         Shop page — filtered via ?category= or ?fabric=
├── product.html            Product detail — loaded via ?slug=
├── cart.html               Cart contents (localStorage-backed)
├── about.html              Brand story
├── faq.html                FAQ accordion
├── contact.html            Contact form (UI only, no backend)
├── css/
│   └── style.css           Single stylesheet for the whole site
├── js/
│   ├── data.js              Product catalog — single source of truth
│   ├── placeholder.js       Generates placeholder artwork (no real photos used)
│   ├── cart.js              localStorage cart logic, shared by all pages
│   ├── menu.js              Mobile nav toggle, shared by all pages
│   ├── faq.js               FAQ content + accordion behavior
│   ├── render-home.js        Renders homepage tiles/best-sellers + shared product card
│   ├── render-collection.js  Filters + renders the shop grid
│   ├── render-product.js     Renders product detail + variant selection
│   └── render-cart.js        Renders cart contents
└── README.md
```

## Extending it

To add or edit a product, edit `js/data.js` only — every page (home, collection,
product, cart) reads from that same array, so there's nothing else to update.
