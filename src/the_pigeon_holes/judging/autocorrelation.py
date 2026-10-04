"""Exact judge for the first autocorrelation inequality.

A candidate returns integers ``q[0..n-1]``. They denote the step function with
values ``q[i] / 2**SCALE_BITS`` on ``n`` equal cells of the interval
``[-1/4, 1/4]``, so the cell width is ``dx = 1/(2n)``.

The constant is

    C1(f) = max(f * f) / (integral of f)**2

For this discretisation the scale factors cancel, which gives an exact
rational value:

    C1 = 2n * max_k conv[k] / S**2,   conv[k] = sum_i q[i] * q[k-i],  S = sum q

No floating point is used anywhere in validation or scoring.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence

JUDGE_VERSION = "autocorrelation-exact-v1"

SCALE_BITS = 40
SCALE = 1 << SCALE_BITS

MIN_POINTS = 2
MAX_POINTS = 4096

# Integral threshold from the upstream verifier: integral**2 must be at least 1e-8.
MIN_INTEGRAL_SQUARED = Fraction(1, 10**8)

# Historical 2025 upper-bound comparator, not the current best-known bound. The float literal is
# converted exactly, so comparisons against it are exact. The bound itself is
# a published float value, not a certified one.
PUBLISHED_UPPER_BOUND = Fraction(1.5052939684401607)


class InvalidOutput(ValueError):
    """The candidate output breaks a rule of the problem family."""


def validate_output(values: object) -> list[int]:
    """Return the output as a list of ints, or raise ``InvalidOutput``."""
    if not isinstance(values, (list, tuple)):
        raise InvalidOutput("output must be a list or tuple of integers")
    n = len(values)
    if not MIN_POINTS <= n <= MAX_POINTS:
        raise InvalidOutput(f"length {n} outside [{MIN_POINTS}, {MAX_POINTS}]")
    for index, value in enumerate(values):
        if type(value) is not int:
            raise InvalidOutput(f"non-integer value at index {index}")
        if value < 0:
            raise InvalidOutput(f"negative value at index {index}")
    total = sum(values)
    if total == 0:
        raise InvalidOutput("integral is zero")
    integral = Fraction(total, SCALE) / (2 * n)
    if integral * integral < MIN_INTEGRAL_SQUARED:
        raise InvalidOutput("integral is too small")
    return list(values)


def max_autoconvolution(values: Sequence[int]) -> int:
    """Return ``max_k sum_i values[i] * values[k - i]`` exactly."""
    n = len(values)
    best = 0
    for k in range(2 * n - 1):
        low = max(0, k - n + 1)
        high = min(k, n - 1)
        total = 0
        for i in range(low, high + 1):
            total += values[i] * values[k - i]
        if total > best:
            best = total
    return best


def c1(values: object) -> Fraction:
    """Return the exact constant C1 for a valid output."""
    q = validate_output(values)
    n = len(q)
    total = sum(q)
    return Fraction(2 * n * max_autoconvolution(q), total * total)


def beats_published_bound(values: object) -> bool:
    """True when the exact C1 is strictly below the published upper bound."""
    return c1(values) < PUBLISHED_UPPER_BOUND


def support_fraction(values: object) -> float:
    """Descriptor: fraction of cells with a nonzero value."""
    q = validate_output(values)
    return sum(1 for value in q if value) / len(q)


def autoconvolution_peaks(values: object) -> int:
    """Descriptor: strict local maxima of the autoconvolution sequence."""
    q = validate_output(values)
    n = len(q)
    conv = [
        sum(q[i] * q[k - i] for i in range(max(0, k - n + 1), min(k, n - 1) + 1))
        for k in range(2 * n - 1)
    ]
    return sum(
        1
        for k in range(1, len(conv) - 1)
        if conv[k] > conv[k - 1] and conv[k] > conv[k + 1]
    )


SUPPORT_BINS = 4
PEAK_CAP = 8


def descriptor_cell(values: object) -> tuple[int, int]:
    """Archive cell: coarse support fraction and capped peak count.

    Cells are integers so that candidates in the same cell compete directly
    under the exact objective, and candidates in different cells are kept apart.
    """
    support = support_fraction(values)
    return (min(int(support * SUPPORT_BINS), SUPPORT_BINS - 1), min(autoconvolution_peaks(values), PEAK_CAP))
