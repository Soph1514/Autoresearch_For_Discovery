"""Tests for the exact first autocorrelation judge.

The float reference below follows the verifier in google-deepmind/alphaevolve_results
and the OpenEvolve examples (examples/alphaevolve_math_problems/first_autocorr_ineq),
Licensed under the Apache License v2.0. It is re-expressed in pure Python so the
suite needs no numpy, and it is used only as a differential reference.
"""

import random
from fractions import Fraction

import pytest

from the_pigeon_holes.judging.autocorrelation import (
    JUDGE_VERSION,
    SCALE,
    InvalidOutput,
    autoconvolution_peaks,
    beats_published_bound,
    c1,
    max_autoconvolution,
    support_fraction,
    validate_output,
)


def reference_c1(values):
    """Float C1 following the upstream formula: max(autoconv) / integral**2."""
    n = len(values)
    f = [max(float(v), 0.0) for v in values]
    dx = 0.5 / n
    integral = sum(f) * dx
    if integral * integral < 1e-8:
        raise ValueError("Function integral is too small.")
    best = 0.0
    for k in range(2 * n - 1):
        low = max(0, k - n + 1)
        high = min(k, n - 1)
        total = sum(f[i] * f[k - i] for i in range(low, high + 1)) * dx
        best = max(best, total)
    return best / (integral * integral)


# --- Known-answer oracles -------------------------------------------------------


def test_constant_function_has_c1_two_for_every_length():
    # For constant f on [-1/4, 1/4]: autoconv peak = 1/2, integral = 1/2, C1 = 2.
    for n in (2, 5, 17, 100):
        assert c1([SCALE] * n) == Fraction(2)


def test_single_spike_has_c1_two_n():
    # One nonzero cell: max conv = 1, S = 1, so C1 = 2n.
    for n in (4, 10):
        values = [0] * n
        values[n // 2] = SCALE
        assert c1(values) == Fraction(2 * n)


def test_constant_does_not_beat_published_bound():
    assert not beats_published_bound([SCALE] * 50)


def test_exact_value_for_small_hand_case():
    # q = [1, 2]: conv = [1, 4, 4], max = 4, S = 3, n = 2 -> C1 = 4 * 4 / 9.
    assert c1([SCALE, 2 * SCALE]) == Fraction(16, 9)


# --- Validity rules ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        [1],  # too short
        [],
        [0, 0, 0],  # zero integral
        [1, -1, 2],  # negative
        [1.0, 2, 3],  # float rejected: judge sees integers only
        [1, True, 2],  # bool is not an integer output
        "1234",
        None,
    ],
)
def test_invalid_outputs_are_rejected(bad):
    with pytest.raises(InvalidOutput):
        c1(bad)


def test_too_long_output_is_rejected():
    with pytest.raises(InvalidOutput):
        validate_output([SCALE] * 5000)


def test_tiny_integral_is_rejected():
    # One unit of 2**-40 over a long output has integral below the threshold.
    with pytest.raises(InvalidOutput, match="too small"):
        validate_output([1] + [0] * 999)


# --- Metamorphic properties ----------------------------------------------------


def _random_output(rng, n):
    values = [rng.randrange(0, SCALE) for _ in range(n)]
    if sum(values) == 0:
        values[0] = 1
    return values


def test_scale_invariance():
    rng = random.Random(1)
    for _ in range(30):
        values = _random_output(rng, rng.randrange(2, 40))
        assert c1(values) == c1([3 * v for v in values])


def test_reversal_invariance():
    rng = random.Random(2)
    for _ in range(30):
        values = _random_output(rng, rng.randrange(2, 40))
        assert c1(values) == c1(list(reversed(values)))


def test_zero_padding_changes_only_through_n():
    # Appending a zero cell keeps the autoconvolution peak and integral,
    # so C1 scales exactly with the length factor 2n.
    values = [SCALE, 3 * SCALE, 2 * SCALE, 5 * SCALE]
    padded = values + [0]
    assert c1(padded) == c1(values) * Fraction(5, 4)


# --- Differential check against the float reference ----------------------------


def test_exact_value_agrees_with_float_reference():
    rng = random.Random(3)
    for _ in range(40):
        n = rng.randrange(2, 60)
        values = _random_output(rng, n)
        exact = float(c1(values))
        reference = reference_c1(values)
        assert exact == pytest.approx(reference, rel=1e-9)


# --- Mutation check: a planted normalisation bug must be visible ---------------


def test_planted_factor_bug_is_detected_by_known_answer():
    # A judge that forgets the 2n factor reports 1/10 for constant f, not 2.
    values = [SCALE] * 10
    buggy = Fraction(max_autoconvolution(values), sum(values) ** 2)
    assert buggy != c1(values)
    assert c1(values) == Fraction(2)


# --- Determinism and descriptors -----------------------------------------------


def test_repeated_calls_are_identical():
    values = [4 * SCALE, 9 * SCALE, SCALE, 0, 7 * SCALE]
    assert c1(values) == c1(values)


def test_version_is_pinned():
    assert JUDGE_VERSION == "autocorrelation-exact-v1"


def test_descriptors_are_deterministic_and_bounded():
    values = [0, 3 * SCALE, 0, 5 * SCALE, 0, SCALE]
    assert support_fraction(values) == pytest.approx(3 / 6)
    peaks = autoconvolution_peaks(values)
    assert peaks == autoconvolution_peaks(list(values))
    assert 0 <= peaks <= 2 * len(values)
