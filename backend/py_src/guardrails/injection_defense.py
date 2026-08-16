"""Defense against injection attacks."""

import re
from py_src.constants import BODY_SHAPE_CLASSES
from py_src.utils.sanitization import sanitize_text


class InjectionDefense:
    """Protects against prompt injection, query injection, and command injection."""

    @staticmethod
    def build_safe_retrieval_query(params):
        """
        Build a safe retrieval query from user-supplied parameters.
        All values are validated and bound as parameters.

        Args:
            params: Dict with shape_class, categories, preferred_colors,
                preferred_silhouettes, occasions, fabrics, size, k

        Returns:
            Safe parameterized query dict
        """
        shape_class = params.get("shape_class")
        categories = params.get("categories", [])
        preferred_colors = params.get("preferred_colors", [])
        preferred_silhouettes = params.get("preferred_silhouettes", [])
        occasions = params.get("occasions", [])
        fabrics = params.get("fabrics", [])
        size = params.get("size")
        sizes_by_category = params.get("sizes_by_category")
        k = params.get("k", 10)

        # Validate and normalize each parameter
        safe_shape = shape_class if shape_class in BODY_SHAPE_CLASSES else "balanced"

        safe_categories = (
            [c for c in categories if isinstance(c, str)][:10]
            if isinstance(categories, list)
            else []
        )

        safe_colors = (
            [c for c in preferred_colors if isinstance(c, str)][:10]
            if isinstance(preferred_colors, list)
            else []
        )

        safe_silhouettes = (
            [s for s in preferred_silhouettes if isinstance(s, str)][:10]
            if isinstance(preferred_silhouettes, list)
            else []
        )

        safe_occasions = (
            [o for o in occasions if isinstance(o, str)][:10]
            if isinstance(occasions, list)
            else []
        )

        safe_fabrics = (
            [f for f in fabrics if isinstance(f, str)][:10]
            if isinstance(fabrics, list)
            else []
        )

        safe_size = size if isinstance(size, str) else None

        # Per-category sizes, for customers whose top and bottom sizes differ.
        # Allowlisted here like everything else: this dict reaches a filter, so
        # it gets the same treatment as the single `size` it supplements rather
        # than being trusted because M3 happens to be the current caller.
        safe_sizes_by_category = (
            {
                category: value
                for category, value in list(sizes_by_category.items())[:20]
                if isinstance(category, str) and isinstance(value, str)
            }
            if isinstance(sizes_by_category, dict)
            else {}
        )

        safe_k = max(1, min(int(k) if isinstance(k, (int, str)) else 10, 100))

        return {
            "shape_class": safe_shape,
            "categories": safe_categories,
            "preferred_colors": safe_colors,
            "preferred_silhouettes": safe_silhouettes,
            "occasions": safe_occasions,
            "fabrics": safe_fabrics,
            "size": safe_size,
            "sizes_by_category": safe_sizes_by_category,
            "k": safe_k,
        }

    @staticmethod
    def sanitize_for_llm(user_text):
        """
        Sanitize LLM input to prevent prompt injection.
        Uses shared sanitization + removes injection-specific keywords.

        Args:
            user_text: Customer-supplied text

        Returns:
            Sanitized text safe for LLM input
        """
        text = sanitize_text(user_text)

        # Remove common prompt-injection keywords
        dangerous = [
            "ignore",
            "forget",
            "override",
            "discard",
            "jailbreak",
            "system prompt",
        ]
        for word in dangerous:
            text = re.sub(rf"\b{word}\b", "", text, flags=re.IGNORECASE)

        return text

    @staticmethod
    def is_valid_sku(sku, valid_skus):
        """
        Validate that a given SKU is one we actually know about.

        Args:
            sku: SKU string
            valid_skus: Set or dict of known SKUs

        Returns:
            Boolean
        """
        if not isinstance(sku, str):
            return False
        if isinstance(valid_skus, (set, dict)):
            return sku in valid_skus
        return False

    @staticmethod
    def escape_json(string):
        """
        Escape a string for safe JSON serialization.

        Args:
            string: String to escape

        Returns:
            Escaped string
        """
        if not isinstance(string, str):
            return ""
        return (
            string.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    @staticmethod
    def is_valid_color(color, valid_colors):
        """
        Validate a color against a whitelist.

        Args:
            color: User-supplied color
            valid_colors: Set or list of known colors

        Returns:
            Boolean
        """
        if not isinstance(color, str):
            return False
        if isinstance(valid_colors, set):
            return color in valid_colors
        if isinstance(valid_colors, list):
            return color in valid_colors
        return False

    @staticmethod
    def is_valid_category(category, valid_categories):
        """
        Validate product type/category against a whitelist.

        Args:
            category: Category string
            valid_categories: Set or list of valid categories

        Returns:
            Boolean
        """
        if not isinstance(category, str):
            return False
        if isinstance(valid_categories, set):
            return category in valid_categories
        if isinstance(valid_categories, list):
            return category in valid_categories
        return False
