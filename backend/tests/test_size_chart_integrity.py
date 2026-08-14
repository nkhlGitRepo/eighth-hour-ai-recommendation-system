"""
Integrity of the size chart and the boundary tables derived from it.

These are structural invariants, not behaviour of any one module. They exist
because the chart is edited by hand from a published source, and a plausible-
looking edit can break things a long way downstream in ways no single module's
tests would catch -- most importantly the photo estimator's guarantee that a
customer who states "M tops" is never recommended a different size, which
depends on every chart value looking up to its own size.
"""

import pytest

from py_src.constants import (
    HIP_SIZE_BOUNDARIES,
    MEASUREMENT_RANGES,
    SIZE_BOUNDARIES,
    SIZE_CHART_SOURCE,
    SIZE_STEP_CM,
    STANDARD_SIZES,
    STANDARD_SIZE_CHART,
    WAIST_SIZE_BOUNDARIES,
)

DIMENSIONS = ("bust", "waist", "hips")
BOUNDARIES = {
    "bust": SIZE_BOUNDARIES,
    "waist": WAIST_SIZE_BOUNDARIES,
    "hips": HIP_SIZE_BOUNDARIES,
}


def find_size(measurement, boundaries):
    for size, (low, high) in boundaries.items():
        if low <= measurement < high:
            return size
    return None


@pytest.mark.parametrize("dimension", DIMENSIONS)
class TestBoundariesCoverEveryBody:
    def test_bands_are_contiguous(self, dimension):
        """No gaps and no overlaps -- each band starts where the last ended."""
        bands = [BOUNDARIES[dimension][size] for size in STANDARD_SIZES]
        for (_, previous_high), (next_low, _) in zip(bands, bands[1:]):
            assert previous_high == next_low

    def test_bands_span_the_whole_supported_range(self, dimension):
        """
        Every measurement the API accepts must map to some size. The published
        chart stops well short of both ends, so the outermost bands have to open
        out to the validation limits.
        """
        floor, ceiling = MEASUREMENT_RANGES[dimension]
        assert BOUNDARIES[dimension][STANDARD_SIZES[0]][0] == floor
        assert BOUNDARIES[dimension][STANDARD_SIZES[-1]][1] == ceiling
        for measurement in range(int(floor), int(ceiling)):
            assert find_size(measurement, BOUNDARIES[dimension]) is not None

    def test_bands_never_run_backwards(self, dimension):
        for size in STANDARD_SIZES:
            low, high = BOUNDARIES[dimension][size]
            assert high > low, f"{dimension}/{size} band is empty or inverted"

    def test_bands_ascend_with_size(self, dimension):
        lows = [BOUNDARIES[dimension][size][0] for size in STANDARD_SIZES]
        assert lows == sorted(lows)


@pytest.mark.parametrize("dimension", DIMENSIONS)
class TestChartAgreesWithItsOwnBoundaries:
    def test_every_chart_value_looks_up_to_its_own_size(self, dimension):
        """
        The invariant the photo estimator's stated-size anchoring rests on: the
        measurement a size is cut for must itself infer that size. If this broke,
        a customer stating "M" could be shown a recommendation of S even with the
        photo contributing nothing at all.
        """
        for size in STANDARD_SIZES:
            value = STANDARD_SIZE_CHART[size][dimension]
            assert find_size(value, BOUNDARIES[dimension]) == size, (
                f"{dimension} {value}cm is what {size} is cut for, but looks up "
                f"as {find_size(value, BOUNDARIES[dimension])}"
            )

    def test_every_published_range_maps_entirely_to_its_own_size(self, dimension):
        """
        Stronger than the midpoint check: a body anywhere inside the range the
        published chart gives for a size must infer that size, top to bottom.
        """
        for size, row in SIZE_CHART_SOURCE.items():
            low, high = row[dimension]
            for measurement in (low, (low + high) / 2, high - 0.01):
                assert find_size(measurement, BOUNDARIES[dimension]) == size, (
                    f"{dimension} {measurement}cm is published as {size} but "
                    f"looks up as {find_size(measurement, BOUNDARIES[dimension])}"
                )

    def test_chart_values_ascend_with_size(self, dimension):
        values = [STANDARD_SIZE_CHART[size][dimension] for size in STANDARD_SIZES]
        assert values == sorted(values)
        assert len(set(values)) == len(values), "two sizes are cut for the same measurement"


class TestChartShape:
    def test_chart_covers_exactly_the_standard_sizes(self):
        assert set(STANDARD_SIZE_CHART) == set(STANDARD_SIZES)
        for size in STANDARD_SIZES:
            assert set(STANDARD_SIZE_CHART[size]) == set(DIMENSIONS)

    def test_xxs_is_not_reachable(self):
        """
        It used to exist in the boundary tables only -- absent from the size
        chart and never offered in the UI -- so a small body could be told to
        buy a size with no defined measurements. The smallest band now absorbs
        that range instead.
        """
        for dimension in DIMENSIONS:
            assert "XXS" not in BOUNDARIES[dimension]
            floor = MEASUREMENT_RANGES[dimension][0]
            assert find_size(floor, BOUNDARIES[dimension]) == STANDARD_SIZES[0]

    @pytest.mark.parametrize("dimension", DIMENSIONS)
    def test_size_step_is_positive_and_plausible(self, dimension):
        """Used as a fixed cm-per-size unit in M7's scoring, so a nonsensical
        value would quietly distort every fit score."""
        assert 3.0 < SIZE_STEP_CM[dimension] < 15.0

    def test_source_chart_bands_widen_or_hold_with_size(self):
        """
        A sanity check on hand-entered data: real charts do not get tighter as
        sizes grow. This is what flagged the published S hip row (93-94cm, a 1cm
        band) as an outlier worth widening.
        """
        for dimension in DIMENSIONS:
            widths = [
                row[dimension][1] - row[dimension][0]
                for row in SIZE_CHART_SOURCE.values()
            ]
            assert min(widths) >= 3.0, (
                f"{dimension} has a {min(widths)}cm band -- too narrow to be a "
                f"real size range; check the source data"
            )
