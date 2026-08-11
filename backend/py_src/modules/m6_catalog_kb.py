"""
M6 — Catalog Knowledge Base

Responsibility: Be the single grounded source of truth for recommendations.
Structured attribute store: hard filters (category, fabric, size, colors,
silhouette, occasion) plus deterministic shape/category-affinity ranking.

Guardrails applied:
- InjectionDefense: parameterized queries only
- AuditLogger: log retrieval operations

Note: consent is verified upstream by M5 before a session reaches
retrieve() (session completion already guarantees consent), so this module
takes no ConsentTracker dependency of its own.
"""

from py_src.constants import SHAPE_CATEGORY_AFFINITY
from py_src.guardrails.injection_defense import InjectionDefense
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError


def shape_affinity_score(shape_class, item):
    """
    How well a catalog item suits a given body shape, as a single 0-1 score.

    1.0 if the item's flatters_shapes specifically includes this shape
    (an exact, keyword-derived match -- see CatalogKB._infer_flatters_shapes).
    Otherwise, the shared SHAPE_CATEGORY_AFFINITY score for the item's
    category (max 0.85), which always sorts below any specific match.

    Shared between M6 (ranking candidates) and M9 (scoring New Releases
    items) so the two can never disagree about how "well a shape suits a
    category" trades off against "this exact item is a known match".
    """
    if shape_class in item.get("flatters_shapes", []):
        return 1.0
    return SHAPE_CATEGORY_AFFINITY.get(shape_class, {}).get(item.get("category", ""), 0.5)


class CatalogKB:
    """Structured catalog knowledge base with attribute-based retrieval."""

    CATALOG_VERSION = "1.0.0"

    def __init__(self, products=None):
        self.items = {}  # sku -> CatalogItem
        self.catalog_version = self.CATALOG_VERSION
        self.last_synced = None

        # Indexes for fast filtering
        self.by_category = {}
        self.by_fabric = {}
        self.by_color = {}

        if products:
            self.rebuild(products)
        logger.info("M6 initialized", {"version": self.CATALOG_VERSION})

    def rebuild(self, products):
        """Rebuild the KB from fresh product data."""
        if not isinstance(products, list):
            raise ModuleError("Products must be a list", "M6")

        self.items.clear()
        self.by_category.clear()
        self.by_fabric.clear()
        self.by_color.clear()

        for product in products:
            try:
                item = self._normalize_product(product)
                sku = item["sku"]

                self.items[sku] = item

                # Index by category
                if item["category"] not in self.by_category:
                    self.by_category[item["category"]] = set()
                self.by_category[item["category"]].add(sku)

                # Index by fabric
                if item["fabric"] not in self.by_fabric:
                    self.by_fabric[item["fabric"]] = set()
                self.by_fabric[item["fabric"]].add(sku)

                # Index by colors
                for color in item["colors"]:
                    if color not in self.by_color:
                        self.by_color[color] = set()
                    self.by_color[color].add(sku)

            except Exception as err:
                logger.warn(
                    "Failed to normalize product",
                    {"product": product.get("slug"), "error": str(err)},
                )

        self.last_synced = 0  # Placeholder
        logger.info("M6 catalog rebuilt", {"item_count": len(self.items)})

    def _normalize_product(self, product):
        """Normalize a product to CatalogItem format."""
        return {
            "sku": product["slug"],
            "slug": product["slug"],
            "name": product["name"],
            "category": product["category"],
            "fabric": product["fabric"],
            "price": product["price"],
            "colors": product.get("colors", []),
            "sizes": product.get("sizes", []),
            "description": product.get("description", ""),
            "length": product.get("length", "Regular"),
            "fit_flatterers": self._infer_fit_flatterers(product),
            "flatters_shapes": self._infer_flatters_shapes(product),
            "silhouette_class": product.get("silhouette") or self._infer_silhouette(product),
            "occasions": self._infer_occasions(product),
            "launched_at": product.get("launched_at"),
            "in_stock": True,
            "sizes_in_stock": {size: True for size in product.get("sizes", [])},
            "catalog_version": self.CATALOG_VERSION,
            "last_synced": self.last_synced,
        }

    def _infer_silhouette(self, product):
        """Infer silhouette class from product name (fallback when the product
        has no explicit 'silhouette' field). Values match M4's VALID_SILHOUETTES."""
        name = product["name"].lower()
        if "vest" in name or "overlap" in name:
            return "fitted"
        if "wrap" in name:
            return "flowing"
        if "straight" in name:
            return "straight"
        if "pleated" in name or "a-line" in name:
            return "a_line"
        return "straight"

    def _infer_occasions(self, product):
        """
        Infer which occasions a product suits from its category.

        Deterministic, category-based heuristic (same style as
        _infer_silhouette/_infer_fit_flatterers above) since the catalog
        doesn't carry per-product occasion tags. Occasions with no
        corresponding product type (e.g. "gym") are intentionally left
        unmapped rather than forced onto formalwear.
        """
        category_occasions = {
            "Vests": ["work", "casual"],
            "Tops": ["work", "casual", "weekend"],
            "Skirts": ["work", "casual", "evening"],
            "Trousers": ["work", "casual"],
            "Dresses": ["evening", "date_night", "casual"],
            "Co-ord Sets": ["evening", "work", "date_night"],
        }
        return category_occasions.get(product["category"], [])

    # Which body shapes a name-keyword suggests a product flatters, grounded
    # in the same styling guidance M3's _generate_fit_notes already tells
    # customers (e.g. "wrap dresses are made for hourglass shapes"). Every
    # product also flatters "balanced" -- M3 tells balanced customers most
    # silhouettes work for them.
    KEYWORD_SHAPE_AFFINITY = {
        "wrap": ["pear", "hourglass", "apple"],
        "vest": ["pear", "hourglass", "apple", "athletic"],
        "pintuck": ["hourglass", "straight"],
        "wide-neck": ["athletic", "apple"],
        "boat-neck": ["athletic", "apple"],
        "pleated": ["pear", "athletic"],
        "a-line": ["pear", "athletic"],
        "straight": ["straight"],
    }

    def _infer_flatters_shapes(self, product):
        """
        Infer which body shape classes a product genuinely flatters, from
        the same name keywords used by _infer_fit_flatterers. Returns real
        BODY_SHAPE_CLASSES values (not free text) so callers can do an
        exact list-membership check instead of string-matching a
        human-readable description.
        """
        name = product["name"].lower()
        shapes = set()
        for keyword, matched_shapes in self.KEYWORD_SHAPE_AFFINITY.items():
            if keyword in name:
                shapes.update(matched_shapes)

        if not shapes:
            shapes.update(["straight", "balanced"])

        shapes.add("balanced")
        return sorted(shapes)

    def _infer_fit_flatterers(self, product):
        """Infer fit flatterers from product name."""
        hints = []
        name = product["name"].lower()

        if "straight" in name:
            hints.append("suits straight shapes")
        if "wrap" in name:
            hints.append("flatters pear and hourglass")
        if "vest" in name:
            hints.append("emphasizes waist")
        if "pintuck" in name:
            hints.append("adds structure")
        if "wide-neck" in name:
            hints.append("balances narrow shoulders")
        if "boat-neck" in name:
            hints.append("broadens shoulders")

        return "; ".join(hints) if hints else "versatile fit"

    def retrieve(self, query_params, user_id=None, consent_tracker=None):
        """
        Main retrieval method with guardrails.

        Args:
            query_params: Dict with shape_class, categories, etc.
            user_id: Optional user ID for audit logging
            consent_tracker: Unused (kept for API compatibility)

        Returns:
            List of CatalogItem dicts ranked by relevance
        """
        try:
            # Guardrail: Apply injection defense (sanitize parameters)
            safe_query = InjectionDefense.build_safe_retrieval_query(query_params)

            shape_class = safe_query.get("shape_class")
            categories = safe_query.get("categories", [])
            preferred_colors = safe_query.get("preferred_colors", [])
            preferred_silhouettes = safe_query.get("preferred_silhouettes", [])
            occasions = safe_query.get("occasions", [])
            fabrics = safe_query.get("fabrics", [])
            size = safe_query.get("size")
            k = safe_query.get("k", 10)

            # Phase 1: Hard filters (structured)
            candidates = list(self.items.values())

            if categories:
                candidates = [
                    item for item in candidates if item["category"] in categories
                ]

            if fabrics:
                candidates = [item for item in candidates if item["fabric"] in fabrics]

            if size:
                candidates = [
                    item
                    for item in candidates
                    if item["sizes_in_stock"].get(size)
                    and item["in_stock"]
                ]

            if preferred_colors:
                candidates = [
                    item
                    for item in candidates
                    if any(c in preferred_colors for c in item["colors"])
                ]

            if preferred_silhouettes:
                candidates = [
                    item
                    for item in candidates
                    if item["silhouette_class"] in preferred_silhouettes
                ]

            if occasions:
                candidates = [
                    item
                    for item in candidates
                    if any(o in occasions for o in item["occasions"])
                ]

            # Phase 2: Shape-based ranking. A specific flatters_shapes match
            # always scores 1.0, strictly above any SHAPE_CATEGORY_AFFINITY
            # fallback (max 0.85), so a single score naturally produces the
            # same two-tier ordering without a separate tiebreak key -- see
            # shape_affinity_score() above.
            results = sorted(
                candidates,
                key=lambda item: shape_affinity_score(shape_class, item),
                reverse=True,
            )[:k]

            logger.debug(
                "M6 retrieval",
                {
                    "shape_class": shape_class,
                    "categories": len(categories),
                    "colors": len(preferred_colors),
                    "results": len(results),
                },
            )

            # Audit: Log successful retrieval if user context provided
            if user_id:
                AuditLogger.log_event(
                    "RECOMMENDATION_RETRIEVED",
                    user_id,
                    {
                        "shape_class": shape_class,
                        "num_results": len(results),
                        "categories_requested": len(categories),
                    }
                )

            return results

        except Exception as err:
            logger.error("M6 retrieval failed", err)
            raise

    def get_item(self, sku):
        """Get item by SKU (guarded)."""
        if not isinstance(sku, str) or len(sku) == 0:
            return None
        return self.items.get(sku)

    def validate_item_availability(self, sku, size, color):
        """Validate item availability (used by future fit-checker)."""
        item = self.items.get(sku)
        if not item:
            return {"valid": False, "reason": "SKU not found"}
        if not item["in_stock"]:
            return {"valid": False, "reason": "Out of stock"}
        if not item["sizes_in_stock"].get(size):
            return {"valid": False, "reason": f"Size {size} unavailable"}
        if color not in item["colors"]:
            return {"valid": False, "reason": f"Color {color} unavailable"}
        return {"valid": True}

    def stats(self):
        """Return catalog statistics."""
        return {
            "total_items": len(self.items),
            "categories": sorted(list(self.by_category.keys())),
            "fabrics": sorted(list(self.by_fabric.keys())),
            "colors": sorted(list(self.by_color.keys())),
            "catalog_version": self.CATALOG_VERSION,
            "last_synced": self.last_synced,
        }
