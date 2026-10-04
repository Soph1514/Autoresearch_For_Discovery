"""Verify pinned published AC1 data and measure projection loss.

Does not execute downloaded code or modify the registered fitness benchmark.
"""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'research/published-sidon'


from the_pigeon_holes.fitness.sidon_refinement import exact_score


def project(q, n):
    """Area-average onto n equal cells using exact overlap lengths, then round."""
    m = len(q)
    result = []
    for j in range(n):
        left, right = j*m, (j+1)*m
        weighted = sum(q[i] * (min(right, (i+1)*n) - max(left, i*n))
                       for i in range(left//n, min(m, (right+n-1)//n)))
        result.append((weighted + m//2)//m)
    return result


def main():
    raw = (DATA/'ttt_ac1_sequence.json').read_bytes()
    provenance = json.loads((DATA/'provenance.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == provenance['sha256']
    values = json.loads(raw, parse_float=Decimal)['sequence']
    assert len(values) == 30000 and all(x >= 0 for x in values)
    q = [int(x * (1 << 40) + Decimal('.5')) for x in values]
    scores = {}
    for n in [32, 64, 128, 1319, 4096, 30000]:
        score = exact_score(project(q, n))
        scores[str(n)] = {'c1':float(score), 'exact':str(score)}
    result={'provenance':provenance,'quantization':'nearest nonnegative integer times 2^-40',
            'scores':scores,'scope':'Full-resolution independent certificate; projected scores are distinct benchmarks.'}
    (DATA/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
