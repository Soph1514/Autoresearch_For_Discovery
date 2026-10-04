import random
from fractions import Fraction
import pytest
from the_pigeon_holes.fitness.sidon_refinement import convolution, exact_score, validate
from the_pigeon_holes.fitness.autocorrelation import c1


def test_packed_coefficients_match_independent_direct_convolution():
    rng = random.Random(42)
    for n in [2, 3, 7, 32, 65]:
        q = [rng.randrange(2**40) for _ in range(n)]
        expected = [sum(q[i]*q[k-i] for i in range(n) if 0 <= k-i < n) for k in range(2*n-1)]
        assert convolution(q) == expected
        assert exact_score(q) == c1(q)


def test_uniform_full_resolution_has_exact_score_two():
    assert exact_score([2**40]*30000) == Fraction(2)


@pytest.mark.parametrize('q', [[0,0], [True,2**40], [-1,2**40], [2**61,2**40], [1.0,2**40]])
def test_reject_invalid_witnesses(q):
    with pytest.raises(ValueError):
        validate(q)
