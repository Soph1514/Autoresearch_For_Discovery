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


def test_published_witness_reproduces_bound_without_downsampling():
    import json
    from decimal import Decimal
    from pathlib import Path
    data = json.loads((Path(__file__).parents[1]/'research/published-sidon/ttt_ac1_sequence.json').read_text(), parse_float=Decimal)
    q = [int(x*2**40+Decimal('.5')) for x in data['sequence']]
    assert len(q) == 30000
    score = exact_score(q)
    assert Fraction('1.5028628') < score < Fraction('1.502863')


def test_refinement_rejects_changed_resolution_and_floats():
    from the_pigeon_holes.models.problem_contract import EvaluationCase
    from the_pigeon_holes.fitness.sidon_refinement import SidonRefinementFitness
    case = EvaluationCase('tiny', {'initial':[2**40]*3})
    fitness = SidonRefinementFitness()
    assert not fitness.evaluate_case(case,[2**40]*2).valid
    assert not fitness.evaluate_case(case,[float(2**40)]*3).valid
    assert fitness.evaluate_case(case,[2**40]*3).metrics['c1'] == 2


def test_live_leader_data_digest_and_exact_score():
    import hashlib
    import json
    from decimal import Decimal
    from pathlib import Path
    folder = Path(__file__).parents[1]/'research/published-sidon'
    raw = (folder/'arena-leading-witness.json').read_bytes()
    record = json.loads((folder/'arena-verification.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == record['source_sha256']
    values = json.loads(raw, parse_float=Decimal)['data']['values']
    peak = max(values)
    q = [int(x/peak*2**40+Decimal('.5')) for x in values]
    assert len(q) == 65536
    assert exact_score(q) == Fraction(record['exact'])
