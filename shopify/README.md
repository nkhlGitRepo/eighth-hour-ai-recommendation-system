# MyStyle on the Eighth Hour Shopify store

The styling engine is added to the US store (www.eighth-hour.com) as part of a
**separate, unpublished theme** — a copy of the real site. Nothing else in the
store is changed: no app, no products, no pages, no menus, no settings. The
team decides when that theme goes live.

| | |
|---|---|
| Real site (unpublished draft, the base) | `theme-export-www-eighth-hour-com-eighthours-2` — theme **155211825389** |
| **MyStyle working copy** (the only theme this touches) | copy of the above — theme **189550657773** |
| Published theme today | `Signature Theme` (162607530221) — the "pre-orders open soon" placeholder; not touched |
| Styling API | https://eighth-hour-api.onrender.com (`backend/`, the `/shopify/*` endpoints) |

## What the working copy adds

The pages follow the original MyStyle storefront (`Base_Website/` in this repo),
in the store's own type, header and product cards. Everything she reads is in inches
(she can switch the quiz to cm).

- **Header links** after "Shop", on desktop and mobile: **My Style** (it reads
  **Update Style** once she has a profile), **New Releases**, and **My
  Recommendations** (shown once she has a profile).
- **My Style** — `/collections/all?view=mystyle`: the five-step style profile
  (Consent, Measurements — typed or from a photo — Shape Profile, Style Prefs,
  Complete with a first look at her picks). Update Style opens it at Style Prefs
  (`&step=style`) with her choices filled in. Guests are asked to sign in. The style
  step offers **only colours, silhouettes and occasions found on a piece in stock**,
  so every choice applies to something; more appear as pieces are uploaded.
- **My Recommendations** — `/collections/all?view=mystyle-recommendations`:
  category filters and her profile (shape, sizes, style choices) beside her picks.
- **New Releases** — `/collections/all?view=mystyle-new`: the first-drop pieces
  with her match, the reason and her size on each; guests see the pieces and an
  invitation to sign in.
- **Fit Recommendation** under the size picker on every launch piece: her size and
  confidence; **how that size fits her at each area** the garment is sized on
  (roomy / relaxed / true to size / close / snug, from where she sits in the brand's
  published range); how each size fits; fit and length notes; **Tips for You** —
  which size to choose when she measures a different one at an area (weighing the
  piece's cut and fabric), and a styling tip for her shape and the piece's
  silhouette (`STYLING_TIPS` in `backend/py_src/constants.py`, copy the brand can
  edit); "Select M"; and fit feedback. When a piece doesn't come in her size: "Your
  size is XXS. This piece comes in XS–L, so XS is the closest fit available."
  **Signed out** (e.g. arriving from an ad), it invites her to sign in and see her
  fit, and the sign-in brings her back to the same product.
- **Picked for you** on the home page, under "Shop by Category".
- **The size drawer shows the October 2026 size guide**, generated from the engine's
  chart (it used to read each product's `custom.size_chart` field, which the live
  theme also uses, so those fields are left alone).

Everything lives in theme files: `shopify/theme/` (new files) plus six small, anchored
edits to the brand's files, listed in `build_theme.py`.

**Fit feedback** ("Share Your Fit Feedback") is saved against her anonymous id, the
product and the size check. Nothing reads it yet — using it to adjust her sizes is a
planned engine feature — and on the free hosting it's lost whenever the API
restarts.

## How it works

- **Who is signed in.** The theme's Liquid signs the customer's id with a secret
  (`snippets/mystyle-token.liquid`); the API checks the signature
  (`backend/py_src/shopify/theme_auth.py`). Guests get no token, and every `/shopify/*`
  endpoint refuses them, so only signed-in customers can build a profile.
- **Products.** The shopper's browser reads the store's own `/products.json` and sends
  the launch pieces with each request. Stock and colours are Shopify's; cards are the
  theme's own product cards, with Shopify's prices for her market.
- **Launch data** (`snippets/mystyle-launch-data.liquid`, private): the first drop's
  styles, SKUs, silhouettes, occasions and the six launch colours, from the brand's
  "Capsule 1 for website" sheet. A product is used only when **every** SKU on it is
  listed under one style — so the Essentials being retired never appear.
- **Measurements stay on the server.** Once entered, they are never sent back to a
  browser. A backup of the profile is kept in her browser, **encrypted** with a key
  only the API has, so the profile survives the API's free hosting wiping its
  database on restart.

## Secrets (in `shopify/private/`, never committed)

`shopify/private/secrets.env` holds:

- `MYSTYLE_THEME_SECRET` — shared by the theme (build_theme.py writes it into
  `snippets/mystyle-secret.liquid`) and the API.
- `MYSTYLE_SERVER_KEY` — **API only**. Derives customers' user ids, the backup's
  encryption key and the admin token. Never rotate it: saved profiles are keyed by it.
- `MYSTYLE_ADMIN_TOKEN` — for deleting a customer's data on a privacy request.

Both `MYSTYLE_*` keys must be set in **Render → eighth-hour-api → Environment**. Until
they are, every store request is refused (the integration is off).

## Build and push (only to the working copy)

```bash
# 1. Once: download the working copy into shopify/private/theme-original
shopify theme pull --store eighth-hour-us.myshopify.com --theme 189550657773 --path shopify/private/theme-original

# 2. Assemble: brand theme + MyStyle files + private snippets + the six edits
backend/venv/bin/python shopify/build_theme.py

# 3. Push ONLY the MyStyle files, ONLY to the working copy (never --live, never --publish)
cd shopify/private/theme-build && shopify theme push --store eighth-hour-us.myshopify.com \
  --theme 189550657773 --nodelete $(sed 's/^/--only /' .mystyle-files | tr '\n' ' ')
```

## Trying it in a preview

Preview: https://www.eighth-hour.com/?preview_theme_id=189550657773 (staff only while
the store has its password). As staff you are not a signed-in customer, so you see the
guest view. To try the signed-in experience with a test customer:

```bash
python3 shopify/mint_test_token.py
```

then in the browser console on the preview: `MyStyle.setToken('<token>')`. Delete the
test profile from the My Style page afterwards.

## When the launch assets are uploaded

Nothing to change: My Style reads the store's products live and picks up the first-drop
pieces by SKU as they appear. Check:

1. The nine styles show **Fit Recommendation** on their product pages.
2. My Recommendations and New Releases show them, and their colours appear in the quiz.
3. If a piece is uploaded with a SKU the sheet doesn't list, add it to its style in
   `shopify/private/mystyle-launch-data.liquid`, rebuild and push.

## Adding the next drop

Add its styles, SKUs, tags and colours to `shopify/private/mystyle-launch-data.liquid`,
then build and push. Categories: Tops, Vests, Dresses, Co-ord Sets, Skirts, Trousers,
Jackets. Silhouettes: Fitted, Flowing, Straight, A-Line, Oversized. Occasions: Work,
Casual, Evening, Weekend.

## Rotating the theme secret

If someone with access to the theme's code leaves, or the secret may have been seen:
put a new `MYSTYLE_THEME_SECRET` in `secrets.env` and in Render, rebuild and push.
Customers simply get fresh tokens on their next page load; nothing is lost.

## A customer's privacy request

Shopify forwards privacy requests only to apps, so they're handled by hand. To delete
everything kept about one customer (her Shopify customer id is in the admin URL of
her customer page):

```bash
curl -X POST https://eighth-hour-api.onrender.com/shopify/admin/delete-customer \
  -H "Content-Type: application/json" -H "X-MyStyle-Admin: $MYSTYLE_ADMIN_TOKEN" \
  -d '{"store": "eighth-hour-us", "customer_id": "<id>"}'
```

Customers can also delete their own profile from the My Style page.

## Going live (the team's decision)

1. Check nobody has edited the base theme since the working copy was made; if they
   have, make a fresh copy of it, pull it, rebuild and push.
2. Move the API to a paid Render plan with a persistent disk (the free plan sleeps
   after 15 minutes and wipes its database on restart; the browser backup restores
   profiles, but a paid plan is the robust setup).
3. Publish the working copy (Online Store → Themes → Publish) and remove the store
   password when ready. The previous theme stays in the library for rollback.

## Known trade-off

The theme secret is readable by anyone with access to the theme's code. What that
could expose is limited — not measurements; at most a customer's sizes and style
choices — and one client acting as many customers is refused and logged. Moving to a
Shopify app (App Proxy) removes the secret from the theme entirely; the API's identity
check is the only part that changes.
