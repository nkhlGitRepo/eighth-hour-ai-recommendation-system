"""Shared text sanitization utilities."""

import re


def sanitize_text(text: str) -> str:
    """
    Sanitize text: remove control characters, collapse spaces, limit length.
    Core sanitization used across validators and guardrails.

    Args:
        text: The text to sanitize

    Returns:
        Sanitized text
    """
    if not isinstance(text, str):
        return ""

    # Remove control characters (keep alphanumeric, punctuation, whitespace)
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', text)

    # Collapse multiple whitespaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()

    # Limit length
    if len(sanitized) > 1000:
        sanitized = sanitized[:1000].strip()

    return sanitized
