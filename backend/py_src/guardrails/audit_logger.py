"""Audit logging for compliance and security."""

import json
import time
from py_src.utils.logger import logger


class AuditLogger:
    """Logs access and operations for compliance (GDPR, BIPA)."""

    # PII-safe event names (no user data in event name)
    EVENTS = {
        # Phase 0 events
        "PROFILE_CREATED": "User created body shape profile",
        "PROFILE_RETRIEVED": "User retrieved profile",
        "RECOMMENDATION_RETRIEVED": "User requested recommendations",
        # Phase 1 events
        "INTAKE_STARTED": "User started intake flow",
        "INTAKE_COMPLETED": "User completed intake flow",
        "MEASUREMENTS_EXTRACTED": "Body measurements extracted from photo",
        "PREFERENCES_CAPTURED": "User style preferences captured",
        "PHOTO_UPLOADED": "User photo uploaded",
        # Phase 3 events
        "FIT_CHECK_COMPLETED": "Product fit assessment completed",
        "FIT_CHECK_SAVED_TO_HISTORY": "Fit check saved to user history",
        "HISTORY_RETRIEVED": "User history retrieved",
        "HISTORY_DELETED": "User history deleted (GDPR right-to-be-forgotten)",
        "SESSION_CHECKS_RETRIEVED": "Session fit checks retrieved",
        "TREND_ANALYSIS_COMPLETED": "Fit preference trend analysis completed",
        "NEW_RELEASES_FEED_GENERATED": "Personalized new releases feed generated",
        # General events
        "CONSENT_RECORDED": "Consent recorded",
        "CONSENT_WITHDRAWN": "Consent withdrawn",
        "ACCESS_GRANTED": "Access granted to resource",
        "ACCESS_DENIED": "Access denied to resource",
        "INVALID_INPUT": "Invalid input rejected",
        "INJECTION_DETECTED": "Potential injection detected",
    }

    @staticmethod
    def log_event(event_type, user_id, context=None):
        """
        Log a compliance-safe event (no PII in the log itself).

        Args:
            event_type: Key from EVENTS dict (e.g., 'PROFILE_CREATED')
            user_id: User ID (hashed in production)
            context: Dict with additional safe context (no PII)
        """
        if event_type not in AuditLogger.EVENTS:
            return

        event_data = {
            "timestamp": int(time.time()),
            "event_type": event_type,
            "user_hash": hash(user_id) if user_id else None,
            "context": context or {},
        }

        logger.info(f"AUDIT: {AuditLogger.EVENTS[event_type]}", event_data)

    @staticmethod
    def log_access_attempt(user_id, resource_id, granted):
        """Log access attempt."""
        event_type = "ACCESS_GRANTED" if granted else "ACCESS_DENIED"
        AuditLogger.log_event(event_type, user_id, {"resource": resource_id})

    @staticmethod
    def log_invalid_input(user_id, reason):
        """Log invalid input rejection."""
        AuditLogger.log_event("INVALID_INPUT", user_id, {"reason": reason})

    @staticmethod
    def log_injection_detection(user_id, injection_type, sanitized_input):
        """Log potential injection attempt."""
        AuditLogger.log_event(
            "INJECTION_DETECTED",
            user_id,
            {"type": injection_type, "input_length": len(sanitized_input)},
        )
