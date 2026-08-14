"""
Tests for ImageValidator -- the guard on the only file-upload surface in
the app, which happens to accept photos of people's bodies.
"""

import pytest

from py_src.guardrails.image_validation import (
    ImageValidator,
    ImageTooLargeError,
    MAX_IMAGE_BYTES,
    ALLOWED_IMAGE_TYPES,
    sniff_content_type,
)
from py_src.utils.errors import ModuleError


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


class TestAcceptsRealImages:
    @pytest.mark.parametrize("data,mime", [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
    ])
    def test_accepts_supported_formats(self, data, mime):
        assert ImageValidator.validate(data, mime) == mime

    def test_normalizes_content_type_parameters(self):
        """Browsers may append parameters; the base type is what matters."""
        assert ImageValidator.validate(JPEG, "image/jpeg; charset=binary") == "image/jpeg"

    def test_normalizes_case(self):
        assert ImageValidator.validate(PNG, "IMAGE/PNG") == "image/png"

    def test_accepts_exactly_at_the_size_cap(self):
        at_cap = JPEG + b"\x00" * (MAX_IMAGE_BYTES - len(JPEG))
        assert len(at_cap) == MAX_IMAGE_BYTES
        assert ImageValidator.validate(at_cap, "image/jpeg") == "image/jpeg"


class TestRejectsBadUploads:
    def test_rejects_empty_upload(self):
        with pytest.raises(ModuleError):
            ImageValidator.validate(b"", "image/jpeg")

    def test_rejects_none(self):
        with pytest.raises(ModuleError):
            ImageValidator.validate(None, "image/jpeg")

    def test_rejects_oversized_upload_with_dedicated_error(self):
        """Distinct error type so the endpoint can answer 413 rather than 400."""
        too_big = JPEG + b"\x00" * MAX_IMAGE_BYTES
        with pytest.raises(ImageTooLargeError):
            ImageValidator.validate(too_big, "image/jpeg")

    @pytest.mark.parametrize("mime", [
        "application/pdf", "text/plain", "image/gif", "image/svg+xml",
    ])
    def test_rejects_disallowed_types(self, mime):
        """A type we don't support is refused even if the bytes are an image."""
        with pytest.raises(ModuleError):
            ImageValidator.validate(JPEG, mime)

    @pytest.mark.parametrize("mime", ["application/octet-stream", "", None])
    def test_unhelpful_content_types_fall_back_to_sniffing(self, mime):
        """
        Deliberate behaviour change: rather than refuse when the client sends no
        usable content type (common for HEIC on some browsers), decide from the
        bytes. The declared type was never trusted on its own anyway.
        """
        assert ImageValidator.validate(JPEG, mime) == "image/jpeg"

    @pytest.mark.parametrize("mime", ["application/octet-stream", "", None])
    def test_sniffing_still_refuses_bytes_that_are_not_an_image(self, mime):
        """Sniffing is a fallback, not a bypass."""
        with pytest.raises(ModuleError):
            ImageValidator.validate(b"definitely not an image at all", mime)

    def test_svg_is_not_allowed(self):
        """SVG is XML and can carry script -- deliberately excluded."""
        assert "image/svg+xml" not in ALLOWED_IMAGE_TYPES


class TestMagicByteSniffing:
    """The declared Content-Type is attacker-controlled and never trusted alone."""

    def test_rejects_text_file_renamed_as_jpeg(self):
        with pytest.raises(ModuleError) as exc:
            ImageValidator.validate(b"this is just text, not an image", "image/jpeg")
        assert "valid image" in str(exc.value)

    def test_rejects_executable_renamed_as_png(self):
        macho = b"\xcf\xfa\xed\xfe" + b"\x00" * 64  # Mach-O header
        with pytest.raises(ModuleError):
            ImageValidator.validate(macho, "image/png")

    def test_rejects_png_bytes_declared_as_jpeg(self):
        """Content and declared type must agree with each other."""
        with pytest.raises(ModuleError):
            ImageValidator.validate(PNG, "image/jpeg")

    def test_rejects_riff_that_is_not_webp(self):
        """A RIFF container that isn't WEBP (e.g. WAV audio) must not pass."""
        wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 32
        with pytest.raises(ModuleError):
            ImageValidator.validate(wav, "image/webp")

    def test_rejects_truncated_webp(self):
        with pytest.raises(ModuleError):
            ImageValidator.validate(b"RIFF" + b"\x00\x00\x00\x00", "image/webp")

    def test_looks_like_image_is_exposed_for_reuse(self):
        assert ImageValidator.looks_like_image(JPEG, "image/jpeg") is True
        assert ImageValidator.looks_like_image(b"nope", "image/jpeg") is False


# ISO-BMFF containers: 4 size bytes, "ftyp", then a brand.
def _iso(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 64


HEIC = _iso(b"heic")
HEIF = _iso(b"mif1")
AVIF = _iso(b"avif")
MP4 = _iso(b"mp42")


class TestPhoneCameraFormats:
    """
    Regression: HEIC is the DEFAULT iPhone camera format and was originally
    missing from the allowlist, so ordinary phone photos were rejected before
    reaching the model -- and the rejection wasn't even logged.
    """

    @pytest.mark.parametrize("data,mime", [
        (HEIC, "image/heic"),
        (HEIC, "image/heif"),   # browsers label these inconsistently
        (HEIF, "image/heif"),
        (HEIF, "image/heic"),
        (AVIF, "image/avif"),
    ])
    def test_accepts_heic_heif_avif(self, data, mime):
        assert ImageValidator.validate(data, mime) in ALLOWED_IMAGE_TYPES

    @pytest.mark.parametrize("declared", ["", "application/octet-stream", "image/*"])
    def test_sniffs_format_when_client_sends_no_usable_type(self, declared):
        """
        Some browsers/OSes send nothing useful for HEIC. Falling back to the
        bytes is what stops a valid photo being refused over a missing header.
        """
        assert ImageValidator.validate(HEIC, declared) == "image/heic"

    @pytest.mark.parametrize("data,expected", [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (HEIC, "image/heic"),
        (AVIF, "image/avif"),
    ])
    def test_sniffing_identifies_each_supported_format(self, data, expected):
        assert sniff_content_type(data) == expected

    def test_sniffing_returns_none_for_unknown_bytes(self):
        assert sniff_content_type(b"not any known format at all") is None


class TestVideoContainersStillRejected:
    """
    HEIC and MP4 share the ISO-BMFF container, so accepting HEIC must not
    accidentally wave through video files.
    """

    def test_rejects_mp4_declared_as_heic(self):
        with pytest.raises(ModuleError):
            ImageValidator.validate(MP4, "image/heic")

    def test_sniffing_does_not_classify_mp4_as_an_image(self):
        assert sniff_content_type(MP4) is None

    def test_rejects_truncated_iso_container(self):
        with pytest.raises(ModuleError):
            ImageValidator.validate(b"\x00\x00\x00\x18ftyp", "image/heic")
