"""
Image upload validation.

The photo-measurement endpoint is the only place this app accepts a file,
and the file in question is a photo of someone's body -- so it gets checked
before the bytes are handed to anything else. Nothing here inspects image
*content*; it establishes only that the upload is a plausibly-real image of
a sane size, so a renamed executable or a multi-gigabyte stream can't reach
the sizing provider.
"""

from py_src.utils.errors import ModuleError

# 10 MB. Comfortably fits a modern phone photo while bounding how much a
# single request can make the server allocate.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# HEIC/HEIF is the DEFAULT camera format on iPhones, so leaving it out meant
# rejecting the most common real-world upload. AVIF is included because Pillow
# already decodes it. Both are ISO-BMFF containers, sniffed differently from
# the older formats (see _ISO_BMFF_BRANDS).
ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/heic", "image/heif", "image/avif",
}

# Some browsers/OSes send an empty or generic content type for HEIC. Rather
# than reject on that alone, these are treated as "unknown, sniff it" and the
# magic bytes decide -- the declared type was never trusted anyway.
SNIFFABLE_CONTENT_TYPES = {"", "application/octet-stream", "image/*"}

# Leading bytes each format must start with. The browser-declared
# Content-Type is attacker-controlled, so it is never trusted on its own --
# the file has to actually look like what it claims.
_MAGIC_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    # WEBP is "RIFF" + 4 size bytes + "WEBP", so it's checked in two pieces.
    "image/webp": [b"RIFF"],
}

# HEIC/HEIF/AVIF are ISO base-media containers: 4 size bytes, then "ftyp",
# then a brand identifying the flavour. Sniffing the brand is how we tell an
# iPhone photo from an MP4 that shares the same container.
_ISO_BMFF_BRANDS = {
    "image/heic": {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"},
    "image/heif": {b"mif1", b"msf1", b"heic", b"heix"},
    "image/avif": {b"avif", b"avis"},
}


def _iso_bmff_brand(image_bytes: bytes):
    """The ISO-BMFF brand of an upload, or None if it isn't one."""
    if len(image_bytes) < 12 or image_bytes[4:8] != b"ftyp":
        return None
    return image_bytes[8:12]


def sniff_content_type(image_bytes: bytes):
    """
    Best-effort format detection from the bytes alone, used when the client
    sends no usable content type (common for HEIC on some browsers).
    """
    for mime, signatures in _MAGIC_SIGNATURES.items():
        if any(image_bytes.startswith(sig) for sig in signatures):
            if mime == "image/webp" and not (
                len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP"
            ):
                continue
            return mime

    brand = _iso_bmff_brand(image_bytes)
    if brand:
        for mime, brands in _ISO_BMFF_BRANDS.items():
            if brand in brands:
                return mime
    return None


class ImageTooLargeError(ModuleError):
    """Raised when an upload exceeds MAX_IMAGE_BYTES (maps to HTTP 413)."""

    def __init__(self, message):
        super().__init__(message, "ImageValidator")


class ImageValidator:
    """Validates uploaded image bytes before any processing."""

    @staticmethod
    def normalize_content_type(content_type: str) -> str:
        """Strip any parameters (e.g. 'image/jpeg; charset=x') and lowercase."""
        if not isinstance(content_type, str):
            return ""
        return content_type.split(";")[0].strip().lower()

    @staticmethod
    def looks_like_image(image_bytes: bytes, content_type: str) -> bool:
        """True if the bytes actually match the claimed format's signature."""
        if content_type in _ISO_BMFF_BRANDS:
            brand = _iso_bmff_brand(image_bytes)
            # Accept any recognised image brand: browsers are inconsistent about
            # labelling HEIC vs HEIF, and rejecting on that mismatch alone would
            # refuse valid iPhone photos.
            known = set().union(*_ISO_BMFF_BRANDS.values())
            return brand in known if brand else False

        signatures = _MAGIC_SIGNATURES.get(content_type, [])
        if not any(image_bytes.startswith(sig) for sig in signatures):
            return False

        # WEBP's marker sits after the 4-byte RIFF size field.
        if content_type == "image/webp":
            return len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP"

        return True

    @staticmethod
    def validate(image_bytes: bytes, content_type: str) -> str:
        """
        Validate an uploaded image.

        Args:
            image_bytes: Raw uploaded data
            content_type: Client-declared MIME type

        Returns:
            The normalized content type.

        Raises:
            ImageTooLargeError: Upload exceeds MAX_IMAGE_BYTES (-> 413)
            ModuleError: Empty upload, disallowed type, or bytes that don't
                match the declared format (-> 400)
        """
        if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
            raise ModuleError("No image was uploaded", "ImageValidator")

        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ImageTooLargeError(
                f"Image is too large (limit {MAX_IMAGE_BYTES // (1024 * 1024)} MB)"
            )

        normalized = ImageValidator.normalize_content_type(content_type)

        # If the client didn't tell us (or said something useless), work it out
        # from the bytes instead of refusing outright.
        if normalized in SNIFFABLE_CONTENT_TYPES:
            sniffed = sniff_content_type(image_bytes)
            if sniffed:
                normalized = sniffed

        if normalized not in ALLOWED_IMAGE_TYPES:
            raise ModuleError(
                f"Unsupported image type '{normalized or 'unknown'}'. "
                f"Use a JPEG, PNG, HEIC, or WEBP photo.",
                "ImageValidator",
            )

        if not ImageValidator.looks_like_image(image_bytes, normalized):
            raise ModuleError(
                "That file doesn't appear to be a valid image. "
                "Please upload a real JPEG, PNG, or WEBP photo.",
                "ImageValidator",
            )

        return normalized
