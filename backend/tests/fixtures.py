"""Test fixtures for AI Engine tests."""

# Precise test measurements for each body shape
MEASUREMENTS = {
    "pear": {
        "bust": 86,
        "waist": 72,
        "hips": 102,
        "shoulder": 36,
        "height": 165,
    },
    "hourglass": {
        "bust": 96,
        "waist": 68,
        "hips": 96,
        "shoulder": 37,
        "height": 168,
    },
    "apple": {
        "bust": 92,
        "waist": 88,
        "hips": 90,
        "shoulder": 40,
        "height": 167,
    },
    "athletic": {
        "bust": 96,
        "waist": 72,
        "hips": 88,
        "shoulder": 41,
        "height": 172,
    },
    "straight": {
        "bust": 97,
        "waist": 88,
        "hips": 90,
        "shoulder": 38,
        "height": 166,
    },
    "balanced": {
        "bust": 92,
        "waist": 82,
        "hips": 98,
        "shoulder": 39,
        "height": 168,
    },
    "invalid_too_small": {
        "bust": 50,
        "waist": 40,
        "hips": 60,
        "height": 120,
    },
    "invalid_incomplete": {
        "bust": 90,
        "hips": 100,
    },
}

# Mock catalog products
PRODUCTS = [
    {
        "slug": "top-fitted-wrap",
        "name": "Fitted Wrap Top",
        "category": "Tops",
        "fabric": "Cotton",
        "price": 59.99,
        "colors": ["Black", "Navy", "Burgundy"],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "description": "A flattering wrap top perfect for pear shapes",
        "length": "Regular",
    },
    {
        "slug": "skirt-aline",
        "name": "A-Line Skirt",
        "category": "Skirts",
        "fabric": "Wool Blend",
        "price": 79.99,
        "colors": ["Black", "Gray", "Blue"],
        "sizes": ["XS", "S", "M", "L"],
        "description": "Classic A-line that flatters all shapes",
        "length": "Regular",
    },
    {
        "slug": "dress-wrap",
        "name": "Wrap Dress",
        "category": "Dresses",
        "fabric": "Jersey",
        "price": 89.99,
        "colors": ["Red", "Black", "Blue"],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "description": "Versatile wrap dress for hourglass shapes",
        "length": "Regular",
    },
    {
        "slug": "top-boat-neck",
        "name": "Boat-Neck Top",
        "category": "Tops",
        "fabric": "Linen",
        "price": 49.99,
        "colors": ["White", "Beige", "Navy"],
        # Stocks XS like the other Tops. This catalog only holds two Tops, so a
        # single one of them missing the customer's size drops the category
        # below MIN_RECOMMENDATIONS and M6 starts relaxing filters -- which
        # makes category-filter tests fail for a reason that has nothing to do
        # with category filtering. The real catalog carries every size on
        # nearly every product; the fixture should not be narrower.
        "sizes": ["XS", "S", "M", "L", "XL"],
        "description": "Broadens shoulders for athletic shapes",
        "length": "Regular",
    },
    {
        "slug": "vest-overlap",
        "name": "Overlap Vest",
        "category": "Vests",
        "fabric": "Cotton",
        "price": 69.99,
        "colors": ["Black", "Camel"],
        "sizes": ["XS", "S", "M", "L"],
        "description": "Emphasizes waist definition",
        "length": "Regular",
    },
]
