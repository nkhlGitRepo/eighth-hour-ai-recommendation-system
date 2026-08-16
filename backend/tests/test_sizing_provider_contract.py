"""
Reusable contract suite for sizing providers.

============================================================================
IF YOU ARE PLUGGING IN A REAL SIZING VENDOR, START HERE.
============================================================================

Add your provider class to PROVIDERS_UNDER_TEST below and run:

    pytest tests/test_sizing_provider_contract.py -v

Everything in this file is an invariant the rest of the application relies
on. If your provider passes, the intake flow, shape profiler, fit checker,
and recommendation engine will all work with it unchanged. If it fails, the
failure message says exactly which assumption is violated -- which is much
cheaper than discovering it as a wrong dress size in the UI.

The single most common real-world failure is units: this codebase is
centimetres end to end (see constants.MEASUREMENT_RANGES, SIZE_BOUNDARIES),
while many vendors return inches. `test_units_are_centimetres` and
`test_values_within_supported_ranges` exist to catch exactly that.
"""

import pytest

from py_src.constants import MEASUREMENT_RANGES
from py_src.modules.m2_sizing_integration import (
    Measurements,
    MockSizingProvider,
    SizingProvider,
)
from py_src.utils.errors import ModuleError


# --------------------------------------------------------------------------
# Register providers to verify here. A real vendor gets added alongside the
# mock; both must satisfy every test below.
# --------------------------------------------------------------------------
PROVIDERS_UNDER_TEST = [
    MockSizingProvider,
]


# A real (if tiny) JPEG header + padding. Providers that actually decode the
# image may need a genuine fixture image instead; the mock ignores content.
SAMPLE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 256
SAMPLE_HEIGHT_CM = 170.0

REQUIRED_FIELDS = ("bust", "waist", "hips", "height")
REQUIRED_DISCLOSURE_KEYS = (
    "processor_name",
    "sends_image_offsite",
    "stores_image",
    "derives_from_image",
    "retention",
)


@pytest.fixture(params=PROVIDERS_UNDER_TEST, ids=lambda cls: cls.__name__)
def provider(request):
    """Each registered provider, instantiated fresh."""
    return request.param()


def _extract(provider):
    """
    Get measurements from whichever path the provider supports, so this suite
    works for upload-based and photo_ref-based vendors alike.
    """
    try:
        return provider.extract_from_image(SAMPLE_JPEG, "image/jpeg", SAMPLE_HEIGHT_CM)
    except ModuleError as err:
        if "does not support direct image upload" not in str(err):
            raise
        return provider.extract_measurements("contract-test-photo.jpg", SAMPLE_HEIGHT_CM)


class TestProviderContract:
    """Invariants every sizing provider must satisfy."""

    def test_implements_the_interface(self, provider):
        assert isinstance(provider, SizingProvider)

    def test_returns_a_measurements_object(self, provider):
        assert isinstance(_extract(provider), Measurements)

    def test_all_required_fields_present_and_numeric(self, provider):
        m = _extract(provider)
        for field in REQUIRED_FIELDS:
            value = getattr(m, field)
            assert value is not None, f"{field} must be populated"
            assert isinstance(value, (int, float)), f"{field} must be numeric, got {type(value)}"
            assert not isinstance(value, bool), f"{field} must be a number, not a bool"

    def test_units_are_centimetres(self, provider):
        """
        This codebase is centimetres everywhere. A provider returning inches
        must convert before returning -- otherwise every size recommendation
        downstream is wrong by a factor of ~2.54.
        """
        assert _extract(provider).unit == "cm"

    def test_values_within_supported_ranges(self, provider):
        """
        Values must fall inside the ranges InputValidator enforces, or the
        extraction will be rejected before it reaches the shape profiler.
        Also the practical canary for an inches/cm mix-up.
        """
        m = _extract(provider)
        # Every field the provider populates, not just the required four.
        #
        # This used to check REQUIRED_FIELDS only, and that gap shipped a real
        # bug: a provider returned a shoulder of 26.5cm (valid range 30-60),
        # nothing objected because shoulder is optional, and the session was
        # then permanently unreadable by the fit checker and the new-releases
        # feed while the recommendation engine kept working. "Optional" means
        # the field may be absent, not that it may hold any value.
        for field in MEASUREMENT_RANGES:
            value = getattr(m, field, None)
            if value is None:
                continue                      # not populated: legitimately optional
            low, high = MEASUREMENT_RANGES[field]
            assert low <= value <= high, (
                f"{field}={value} is outside the supported range {low}-{high} cm. "
                f"If your vendor returns inches, convert to cm before returning. "
                f"An out-of-range optional field is stored happily and then "
                f"rejected by every module that validates its input."
            )

    def test_honors_the_supplied_height(self, provider):
        """
        Height is the customer-supplied scale reference. A provider that
        ignores it will size everyone as though they were the default height.
        """
        assert _extract(provider).height == pytest.approx(SAMPLE_HEIGHT_CM)

    def test_provenance_is_populated(self, provider):
        m = _extract(provider)
        assert m.provider, "provider name must be set (shown to the customer and audited)"
        assert m.provider_version, "provider_version must be set"

    def test_confidence_scores_are_valid_probabilities(self, provider):
        m = _extract(provider)
        assert m.confidence_scores, "at least one confidence score is required"
        for field, score in m.confidence_scores.items():
            assert isinstance(score, (int, float)), f"confidence for {field} must be numeric"
            assert 0.0 <= score <= 1.0, f"confidence for {field}={score} must be within 0-1"

    def test_empty_upload_is_rejected(self, provider):
        """A provider must not invent measurements from nothing."""
        try:
            with pytest.raises(ModuleError):
                provider.extract_from_image(b"", "image/jpeg", SAMPLE_HEIGHT_CM)
        except ModuleError as err:
            # Upload-unsupported providers are exempt from this one.
            if "does not support direct image upload" not in str(err):
                raise

    def test_declares_a_disclosure(self, provider):
        """
        The upload screen renders its legal notice from this, so a provider
        cannot ship without stating how it handles a customer's photo.
        """
        disclosure = provider.disclosure
        assert isinstance(disclosure, dict)
        for key in REQUIRED_DISCLOSURE_KEYS:
            assert key in disclosure, f"disclosure must declare '{key}'"

        assert isinstance(disclosure["sends_image_offsite"], bool)
        assert isinstance(disclosure["stores_image"], bool)
        assert isinstance(disclosure["derives_from_image"], bool)
        assert disclosure["processor_name"].strip(), "processor_name must be non-empty"
        assert disclosure["retention"].strip(), "retention statement must be non-empty"

    def test_offsite_provider_says_so_in_plain_language(self, provider):
        """
        If images leave this server, the retention text has to actually tell
        the customer that -- a `True` flag with reassuring copy would be
        worse than no disclosure at all.
        """
        disclosure = provider.disclosure
        if disclosure["sends_image_offsite"]:
            text = f"{disclosure['processor_name']} {disclosure['retention']}".lower()
            assert any(
                word in text for word in ("send", "shared", "share", "transfer", "third")
            ), "a provider that transmits images offsite must disclose that in its text"

    def test_placeholder_provider_does_not_vary_with_the_image(self, provider):
        """
        A provider declaring derives_from_image=False is asserting it ignores
        the photo. Verify that's actually true -- two very different images
        must give identical measurements. If they differ, the flag is wrong and
        the UI would mislabel real analysis as placeholder data.
        """
        if provider.disclosure["derives_from_image"]:
            pytest.skip("provider claims to analyse the image; covered below")

        a = provider.extract_from_image(SAMPLE_JPEG, "image/jpeg", SAMPLE_HEIGHT_CM)
        b = provider.extract_from_image(
            b"\x89PNG\r\n\x1a\n" + b"\x11" * 4096, "image/png", SAMPLE_HEIGHT_CM
        )
        assert a.bust == b.bust and a.waist == b.waist and a.hips == b.hips

    def test_analysing_provider_actually_varies_with_the_image(self, provider):
        """
        The converse: a provider claiming derives_from_image=True must not
        return the same numbers for two completely different images, or it is
        a placeholder masquerading as a real measurement service -- the exact
        situation that would mislead a customer about their own body.
        """
        if not provider.disclosure["derives_from_image"]:
            pytest.skip("provider is a declared placeholder; covered above")

        a = provider.extract_from_image(SAMPLE_JPEG, "image/jpeg", SAMPLE_HEIGHT_CM)
        b = provider.extract_from_image(
            b"\x89PNG\r\n\x1a\n" + b"\x11" * 4096, "image/png", SAMPLE_HEIGHT_CM
        )
        assert (a.bust, a.waist, a.hips) != (b.bust, b.waist, b.hips), (
            "provider declares derives_from_image=True but returned identical "
            "measurements for two different images"
        )
