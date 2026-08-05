"""Input validation and sanitization."""

from py_src.utils.sanitization import sanitize_text


class InputValidator:
    """Validates measurements, preferences, and other user inputs."""

    @staticmethod
    def validate_measurements(measurements):
        """
        Validate measurements for sanity.

        Args:
            measurements: Dict with bust, waist, hips, height, etc.

        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []

        # Type check
        if not isinstance(measurements, dict):
            return {"valid": False, "errors": ["Measurements must be a dict"]}

        bust = measurements.get("bust")
        waist = measurements.get("waist")
        hips = measurements.get("hips")
        height = measurements.get("height")
        inseam = measurements.get("inseam")

        # Presence checks
        if bust is None:
            errors.append("bust is required")
        if waist is None:
            errors.append("waist is required")
        if hips is None:
            errors.append("hips is required")
        if height is None:
            errors.append("height is required")

        # Type checks
        if bust is not None and not isinstance(bust, (int, float)):
            errors.append("bust must be a number")
        if waist is not None and not isinstance(waist, (int, float)):
            errors.append("waist must be a number")
        if hips is not None and not isinstance(hips, (int, float)):
            errors.append("hips must be a number")
        if height is not None and not isinstance(height, (int, float)):
            errors.append("height must be a number")

        # Range checks (cm) - only if type is correct
        if bust is not None and isinstance(bust, (int, float)) and (bust < 70 or bust > 150):
            errors.append("bust out of range (70-150 cm)")
        if waist is not None and isinstance(waist, (int, float)) and (waist < 55 or waist > 130):
            errors.append("waist out of range (55-130 cm)")
        if hips is not None and isinstance(hips, (int, float)) and (hips < 80 or hips > 160):
            errors.append("hips out of range (80-160 cm)")
        if height is not None and isinstance(height, (int, float)) and (height < 140 or height > 210):
            errors.append("height out of range (140-210 cm)")
        if inseam is not None and isinstance(inseam, (int, float)) and (inseam < 60 or inseam > 100):
            errors.append("inseam out of range (60-100 cm)")

        return {"valid": len(errors) == 0, "errors": errors}

    @staticmethod
    def validate_preferences(preferences):
        """
        Validate style preferences.

        Args:
            preferences: Dict with colors, silhouettes, etc.

        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []

        if not isinstance(preferences, dict):
            return {"valid": False, "errors": ["Preferences must be a dict"]}

        colors = preferences.get("colors")
        silhouettes = preferences.get("silhouettes")
        occasions = preferences.get("occasions")
        free_text_notes = preferences.get("free_text_notes")

        # Array checks
        if colors and not isinstance(colors, list):
            errors.append("colors must be an array")
        if silhouettes and not isinstance(silhouettes, list):
            errors.append("silhouettes must be an array")
        if occasions and not isinstance(occasions, list):
            errors.append("occasions must be an array")

        # Array length checks
        if colors and len(colors) > 20:
            errors.append("colors array too long (max 20)")
        if silhouettes and len(silhouettes) > 20:
            errors.append("silhouettes array too long (max 20)")
        if occasions and len(occasions) > 20:
            errors.append("occasions array too long (max 20)")

        # Free text checks
        if free_text_notes is not None and not isinstance(free_text_notes, str):
            errors.append("free_text_notes must be a string")
        if isinstance(free_text_notes, str) and len(free_text_notes) > 1000:
            errors.append("free_text_notes too long (max 1000 chars)")

        return {"valid": len(errors) == 0, "errors": errors}

    @staticmethod
    def sanitize_text(text):
        """Sanitize free-text input."""
        return sanitize_text(text)

    @staticmethod
    def validate_skus(skus, catalog_items):
        """
        Validate that an array of SKUs exists in the catalog.

        Args:
            skus: List of SKUs
            catalog_items: Dict or set of valid SKUs

        Returns:
            Dict with 'valid' bool and 'invalid_skus' list
        """
        if not isinstance(skus, list):
            return {"valid": False, "invalid_skus": []}

        invalid = []
        for sku in skus:
            if isinstance(catalog_items, dict):
                if sku not in catalog_items:
                    invalid.append(sku)
            elif isinstance(catalog_items, set):
                if sku not in catalog_items:
                    invalid.append(sku)

        return {"valid": len(invalid) == 0, "invalid_skus": invalid}

    @staticmethod
    def validate_user_id(user_id):
        """Validate user_id format (non-empty string, max 256 chars)."""
        return (
            isinstance(user_id, str)
            and len(user_id) > 0
            and len(user_id) <= 256
        )

    @staticmethod
    def validate_consent(consent):
        """
        Validate consent record has required fields.

        Args:
            consent: Dict with timestamp, photo_consent, measurement_consent

        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []

        if not isinstance(consent, dict):
            return {"valid": False, "errors": ["Consent must be a dict"]}

        timestamp = consent.get("timestamp")
        photo_consent = consent.get("photo_consent")
        measurement_consent = consent.get("measurement_consent")

        if not timestamp:
            errors.append("consent requires timestamp")
        if not isinstance(photo_consent, bool):
            errors.append("photo_consent must be boolean")
        if not isinstance(measurement_consent, bool):
            errors.append("measurement_consent must be boolean")

        return {"valid": len(errors) == 0, "errors": errors}
