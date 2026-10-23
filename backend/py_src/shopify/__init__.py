"""
The engine's side of the Shopify storefront integration.

The storefront integration lives entirely in a theme (no Shopify app): the
theme identifies the signed-in customer to the API with a token it signs in
Liquid (theme_auth), sends the live product list it can see with each request
(catalog), and keeps a signed copy of the customer's profile in her browser so
it survives the API losing its database (profile_token).
"""
