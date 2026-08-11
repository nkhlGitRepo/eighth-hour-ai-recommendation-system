"""
M6 — Catalog Knowledge Base

Responsibility: Be the single grounded source of truth for recommendations.
Hybrid store: structured attributes + vector embeddings for semantic retrieval.

Guardrails applied:
- InjectionDefense: parameterized queries only
- InputValidator: validate query parameters
- AuditLogger: log retrieval operations
"""

import math
from py_src.guardrails.injection_defense import InjectionDefense
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.utils.math import cosine_similarity
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError


def mock_embed(text):
    """
    Mock embedding function (placeholder).
    In production: use OpenAI embeddings API or local embedding model.
    """
    # Simple deterministic hash-based embedding
    hash_val = 0
    for char in text:
        hash_val = ((hash_val << 5) - hash_val) + ord(char)
        hash_val = hash_val & hash_val  # Keep 32-bit

    dim = 128
    seed = abs(hash_val)
    embedding = []
    for i in range(dim):
        embedding.append(math.sin((seed + i) * 0.1) * 0.5)
    return embedding


class CatalogKB:
    """Hybrid catalog knowledge base with structured + vector retrieval."""

    CATALOG_VERSION = "1.0.0"

    def __init__(self, products=None):
        self.items = {}  # sku -> CatalogItem
        self.embeddings = {}  # sku -> embedding vector
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
        self.embeddings.clear()
        self.by_category.clear()
        self.by_fabric.clear()
        self.by_color.clear()

        for product in products:
            try:
                item = self._normalize_product(product)
                sku = item["sku"]

                self.items[sku] = item
                self.embeddings[sku] = mock_embed(self._embedding_text(item))

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
            "silhouette_class": self._infer_silhouette(product),
            "in_stock": True,
            "sizes_in_stock": {size: True for size in product.get("sizes", [])},
            "catalog_version": self.CATALOG_VERSION,
            "last_synced": self.last_synced,
        }

    def _infer_silhouette(self, product):
        """Infer silhouette class from product name."""
        name = product["name"].lower()
        if "vest" in name or "overlap" in name:
            return "fitted"
        if "wrap" in name:
            return "flowing"
        if "straight" in name:
            return "straight"
        if "pleated" in name or "a-line" in name:
            return "A-line"
        return "straight"

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

    def _embedding_text(self, item):
        """Generate embedding text from item."""
        return (
            f"{item['name']}. {item['description']}. {item['silhouette_class']} "
            f"silhouette. {item['fit_flatterers']}. Colors: {', '.join(item['colors'])}."
        )

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

            # Phase 2: Semantic ranking
            query_text = f"A piece that flatters {shape_class} shapes"
            query_vec = mock_embed(query_text)

            scored = []
            for item in candidates:
                vec = self.embeddings.get(item["sku"])
                if vec:
                    sim = cosine_similarity(query_vec, vec)
                    scored.append((item, sim))

            # Sort by score, take top k
            results = sorted(scored, key=lambda x: x[1], reverse=True)[:k]
            results = [item for item, score in results]

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
