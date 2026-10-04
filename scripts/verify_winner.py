"""Evaluate a saved winner on held-out grid sizes, always inside Docker."""
import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from the_pigeon_holes.evaluation.production import create_evaluator
from the_pigeon_holes.evolution.models import ProgramCandidate, EvolutionOperator, TokenUsage
from the_pigeon_holes.models.problem_contract import EvaluationCase, EvaluationSuite, ResourceLimits
from the_pigeon_holes.ui.storage import contract_from_dict, encode

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('artifact', type=Path)
p.add_argument('--sizes', type=int, nargs='+', default=[48, 96, 256])
p.add_argument('--seconds', type=float, default=10)
p.add_argument('--candidate', help='Explicit candidate ID for a checkpoint during a live run')
a = p.parse_args()
record = json.loads(a.artifact.read_text())
problem = replace(contract_from_dict(record['contract']),
    evaluation_suite=EvaluationSuite('held-out-v1', tuple(EvaluationCase(f'n-{n}', {'n':n}) for n in a.sizes)),
    resource_limits=ResourceLimits(a.seconds, a.seconds*len(a.sizes)+5, 512, 100000))
raw = (record['evidence']['candidates'][a.candidate] if a.candidate
       else (record.get('outcome') or {}).get('best_candidate'))
if raw is None:
    p.error('Run has no final winner yet; specify --candidate for a checkpoint')
candidate = ProgramCandidate(**{**raw, 'operator':EvolutionOperator(raw['operator']),
    'generation_usage':TokenUsage(**raw['generation_usage'])})
evaluator = create_evaluator(problem)
result = asyncio.run(evaluator.evaluate([candidate], problem))[0]
output = {'candidate_id': candidate.id, 'evaluation':encode(result), 'numerical':evaluator.evidence[candidate.id],
    'scope':'Held-out grid sizes; not a proof for all inputs or of optimality.'}
path = a.artifact.parent / (f'held-out-{a.candidate}.json' if a.candidate else 'held-out.json')
path.write_text(json.dumps(output, indent=2))
print(json.dumps(encode(result), indent=2))
print(path.resolve())
