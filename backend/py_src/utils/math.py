"""Mathematical utilities: vector operations, similarity, etc."""

import math


def cosine_similarity(a, b):
    """
    Cosine similarity between two vectors.

    Args:
        a: Vector A (list or similar)
        b: Vector B (list or similar)

    Returns:
        Similarity score 0-1
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0

    for i in range(len(a)):
        dot += a[i] * b[i]
        mag_a += a[i] * a[i]
        mag_b += b[i] * b[i]

    denominator = math.sqrt(mag_a) * math.sqrt(mag_b)
    return 0.0 if denominator == 0 else dot / denominator


def clamp(value, min_val, max_val):
    """
    Clamp a value within a range.

    Args:
        value: The value to clamp
        min_val: Minimum value
        max_val: Maximum value

    Returns:
        Clamped value
    """
    return max(min_val, min(max_val, value))
