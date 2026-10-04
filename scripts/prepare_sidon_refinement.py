"""Register a published-witness refinement contract after a real Docker seed check."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from the_pigeon_holes.evaluation.production import SandboxCandidateEvaluator
from the_pigeon_holes.execution.container_runner import ContainerLimits
from the_pigeon_holes.evolution.models import ProgramCandidate, EvolutionOperator, TokenUsage
from the_pigeon_holes.fitness.sidon_refinement import SidonRefinementFitness
from the_pigeon_holes.models.problem_contract import InterfaceDefinition, Parameter, EvaluationCase, EvaluationSuite, ResourceLimits
from the_pigeon_holes.ui.storage import ArtifactStore, contract_from_dict, encode

ROOT = Path(__file__).resolve().parents[1]

async def main():
    data = ROOT/'research/published-sidon'
    provenance = json.loads((data/'provenance.json').read_text())
    raw = (data/'ttt_ac1_sequence.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance['sha256']
    initial = [int(x * 2**40 + Decimal('.5')) for x in json.loads(raw, parse_float=Decimal)['sequence']]
    from zipfile import ZipFile
    with ZipFile(ROOT/'output/demo-verification/sidon-reasoning-evidence.zip') as bundle:
        prior = json.loads(bundle.read('1c04e4c1-21aa-48f7-8562-0c298c60595c/run.json'))
    seed = 'def solve(initial: list[int]) -> list[int]:\n    return list(initial)\n'
    contract = replace(contract_from_dict(prior['contract']),
        natural_language_spec=(
            'Sidon sets: full-resolution published-witness refinement.\n\n'
            'Minimize exact C1 = 2*n*max(convolve(q,q))/sum(q)^2. '
            'Input initial is the published TTT-Discover 30000-piece witness, quantized to units 2^-40; '
            'its verified score is 1.5028628982558014. Return a nonnegative integer list of the same length. '
            'The input is a public construction, not a hidden answer. Improve it with full-resolution local '
            'refinement, competing perturbations or restarts; retaining initial is an admissible fallback. '
            'No numpy/scipy: standard library only. Use exact big-integer Kronecker packing to compute '
            'convolution efficiently: pack coefficients into fixed byte slots with base greater than '
            'n*max(q)^2, square the packed integer, and decode. Avoid O(n^2) loops. '
            'Use a bounded deterministic search that fits the execution limit. Do not claim a published '
            'record from floating-point estimates. Output integers <=2^60; preserve nonzero integral. '
            'This full-resolution construction-refinement task is distinct from the earlier 32/64/128 '
            'algorithm benchmark. Source: https://github.com/test-time-training/discover, MIT license.'),
        interface=InterfaceDefinition('sidon-refinement-interface-v1',(Parameter('initial','list[int]'),),
            'list[int]','def solve(initial: list[int]) -> list[int]:'),
        seed_program=seed,
        evaluation_suite=EvaluationSuite('sidon-published-30000-refinement-v1',(EvaluationCase('published-30000',{'initial':initial}),)),
        resource_limits=ResourceLimits(15,90,512,100000), fitness_function=SidonRefinementFitness.reference)
    evaluator=SandboxCandidateEvaluator(SidonRefinementFitness(),ContainerLimits(memory_mb=512,timeout_seconds=15))
    # Reuse only record structure, never the old candidate's code or metrics.
    raw_candidate=prior['evidence']['candidates']['candidate-000000']
    candidate=ProgramCandidate(**{**raw_candidate,'source_code':seed,'operator':EvolutionOperator(raw_candidate['operator']),
        'generation_usage':TokenUsage(**raw_candidate['generation_usage'])})
    result=(await evaluator.evaluate([candidate],contract))[0]
    assert result.valid, result
    record = evaluator.evidence[candidate.id]
    witness = record['cases']['published-30000']['fitness_evidence']
    (data/'sandbox-baseline.json').write_text(json.dumps({
        'evaluation':encode(result), 'image':record['image'],
        'fitness_function':record['fitness_function'], 'cells':len(witness['output']),
        'c1_exact':witness['c1_exact'],
        'output_sha256':hashlib.sha256(json.dumps(witness['output']).encode()).hexdigest(),
        'scope':'Identity seed output equals the quantized pinned source; duplicate arrays omitted.'},indent=2)+'\n')
    identity='sidon-published-30000-refinement-v1'
    ArtifactStore(ROOT/'runs/research.sqlite3').put('contract',identity,{'contract':encode(contract),
        'provenance':{**(prior.get('provenance') or {}),'published_baseline':provenance,
            'scope':'New full-resolution refinement interface; numerical validation, not a new Lean proof.'}})
    print(json.dumps({'contract_id':identity,'baseline':encode(result)},indent=2))

if __name__ == '__main__':
    asyncio.run(main())
