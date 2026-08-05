"""Consent tracking for GDPR and BIPA compliance."""

import time


class ConsentTracker:
    """Tracks user consent for data processing."""

    def __init__(self):
        # user_id -> list of consent records
        self.consent_history = {}

    def record_consent(self, user_id, photo_consent, measurement_consent):
        """
        Record a consent decision.

        Args:
            user_id: User ID
            photo_consent: Boolean
            measurement_consent: Boolean

        Returns:
            Consent record dict
        """
        consent = {
            "timestamp": int(time.time()),
            "photo_consent": photo_consent,
            "measurement_consent": measurement_consent,
        }

        if user_id not in self.consent_history:
            self.consent_history[user_id] = []

        self.consent_history[user_id].append(consent)
        return consent

    def get_latest_consent(self, user_id):
        """
        Get the most recent consent record for a user.

        Args:
            user_id: User ID

        Returns:
            Consent dict or None
        """
        if user_id not in self.consent_history or not self.consent_history[user_id]:
            return None
        return self.consent_history[user_id][-1]

    def has_photo_consent(self, user_id):
        """Check if user has consented to photo processing."""
        consent = self.get_latest_consent(user_id)
        return consent.get("photo_consent", False) if consent else False

    def has_measurement_consent(self, user_id):
        """Check if user has consented to measurement processing."""
        consent = self.get_latest_consent(user_id)
        return consent.get("measurement_consent", False) if consent else False

    def withdraw_consent(self, user_id, consent_type=None):
        """
        Withdraw consent (photo, measurement, or both).

        Args:
            user_id: User ID
            consent_type: 'photo', 'measurement', or None for both

        Returns:
            New consent record with withdrawn consent
        """
        latest = self.get_latest_consent(user_id)
        if not latest:
            return None

        photo_consent = latest["photo_consent"]
        measurement_consent = latest["measurement_consent"]

        if consent_type == "photo" or consent_type is None:
            photo_consent = False
        if consent_type == "measurement" or consent_type is None:
            measurement_consent = False

        return self.record_consent(user_id, photo_consent, measurement_consent)

    def get_consent_summary(self, user_id):
        """Get a summary of user's current consent state."""
        consent = self.get_latest_consent(user_id)
        if not consent:
            return {
                "user_id": user_id,
                "has_any_consent": False,
                "photo_consent": False,
                "measurement_consent": False,
            }

        return {
            "user_id": user_id,
            "has_any_consent": (
                consent.get("photo_consent", False)
                or consent.get("measurement_consent", False)
            ),
            "photo_consent": consent.get("photo_consent", False),
            "measurement_consent": consent.get("measurement_consent", False),
            "last_updated": consent.get("timestamp"),
        }
