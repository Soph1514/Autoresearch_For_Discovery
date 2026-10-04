"""Bind a server-recorded Lean check to an immutable custom research contract."""
import asyncio
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from pydantic import BaseModel, Field
from the_pigeon_holes.fitness.compiler import compile_fitness, load_lean_fitness, VERSION
from the_pigeon_holes.fitness.registry import configured_registry
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, ResourceLimits, build_problem_contract,
)


class ContractInput(BaseModel):
    formalization_id: str
    seed_program: str | None = Field(default=None, max_length=64000)
    evaluation_suite_id: str = Field(min_length=1, max_length=200)
    evaluation_cases: dict[str, dict] | None = Field(default=None, min_length=1, max_length=1000)
    fitness_function_id: str | None = Field(default=None, min_length=1, max_length=200)
    fitness_function_version: str | None = Field(default=None, min_length=1, max_length=200)
    alignment_reviewed: bool = False
    case_time_seconds: float = Field(default=5, gt=0, le=300, allow_inf_nan=False)
    candidate_time_seconds: float = Field(default=60, gt=0, le=3600, allow_inf_nan=False)
    memory_mb: int = Field(default=512, gt=0, le=32768)
    max_iterations: int = Field(default=100000, gt=0)


def make_evaluator(contract, *, store=None, registry=None):
    """Build generic sandbox execution around the contract's trusted fitness function."""
    from the_pigeon_holes.evaluation.production import create_evaluator
    active = registry if registry is not None else configured_registry()
    reference = contract.fitness_function
    # Registered scorers always take precedence, including digest-mismatch failures.
    registered = any(r.id == reference.id and r.version == reference.version for r in active.references())
    if not registered and reference.version == VERSION and reference.id.startswith('lean-'):
        saved = store.get('fitness', reference.id) if store is not None else None
        if saved is None:
            raise ValueError('Compiled evaluator not found. Prepare the contract again.')
        try:
            fitness = load_lean_fitness(Path(saved['artifact']), reference)
        except OSError as error:
            raise ValueError('Compiled evaluator files are missing. Prepare the contract again.') from error
        active.register(fitness)
    evaluator = create_evaluator(contract, registry=active)
    if not callable(getattr(evaluator, 'evaluate', None)):
        raise ValueError('Evaluator factory must return an async CandidateEvaluator.')
    return evaluator


async def prepare_contract(body, artifact, *, builder=build_problem_contract, registry=None,
                           client_factory=None, store=None, lean_project=None):
    if artifact is None:
        raise ValueError('Formalization not found. Submit and check the problem first.')
    result = artifact['result']
    if not result['lean_checked']:
        raise ValueError('Lean must pass checking before contract preparation.')
    provenance = result.get('check_artifact')
    if not provenance or provenance.get('source_sha256') != hashlib.sha256(result['lean'].encode()).hexdigest():
        raise ValueError('A matching Lean check artifact is required. Redeploy the checker and check again.')
    if provenance.get('exit_code') != 0 or not all(provenance.get(k) for k in ('toolchain', 'dependencies', 'command', 'lean_version')):
        raise ValueError('Lean check provenance is incomplete.')
    if result['status'] != 'checked' and not body.alignment_reviewed:
        raise ValueError('Review the Lean statement against the problem and acknowledge its alignment before continuing.')
    limits = ResourceLimits(body.case_time_seconds, body.candidate_time_seconds, body.memory_mb, body.max_iterations)
    active_registry = registry if registry is not None else configured_registry()
    if bool(body.fitness_function_id) != bool(body.fitness_function_version):
        raise ValueError('Select both the fitness function ID and version, or neither to compile Lean.')
    if not body.fitness_function_id:
        if store is None:
            raise RuntimeError('An artifact store is required to save the compiled evaluator.')
        project = Path(lean_project or os.environ.get('RESEARCH_LEAN_PROJECT') or
                       Path(__file__).resolve().parents[3] / 'problems' / 'lean')
        def compile_contract():
            fitness = compile_fitness(statement=artifact['input']['problem'],
                instance=next(iter(body.evaluation_cases.values())) if body.evaluation_cases is not None else None,
                lean_source=result['lean'],
                lean_project=project, artifacts=store.path.parent / 'fitness',
                provenance={'formalization_id': body.formalization_id,
                            'check_artifact': provenance, 'fidelity': result.get('fidelity'),
                            'alignment_reviewed': body.alignment_reviewed})
            cases = body.evaluation_cases if body.evaluation_cases is not None else fitness.manifest['generated_cases']
            contract = replace(fitness.contract(seed_program=body.seed_program or None, limits=limits),
                evaluation_suite=EvaluationSuite(body.evaluation_suite_id, tuple(
                    EvaluationCase(identity, inputs) for identity, inputs in cases.items())))
            fitness.validate_contract(contract)
            store.put('fitness', fitness.reference.id,
                      {'artifact': str(fitness.artifact), 'manifest': fitness.manifest})
            return contract
        return await asyncio.to_thread(compile_contract)
    if body.evaluation_cases is None:
        raise ValueError('Provide case inputs for the registered fitness function.')
    fitness_function = active_registry.find(
        body.fitness_function_id, body.fitness_function_version
    )
    if not body.seed_program:
        from the_pigeon_holes.pipeline.runner import PROBLEMS
        known = PROBLEMS.get(body.fitness_function_id.replace('_', '-'))
        if known is None:
            raise ValueError('Provide a seed program for this registered fitness function.')
        contract = replace(known.contract(), natural_language_spec=artifact['input']['problem'],
            lean_specification=result['lean'], resource_limits=limits,
            evaluation_suite=EvaluationSuite(body.evaluation_suite_id, tuple(
                EvaluationCase(identity, inputs) for identity, inputs in body.evaluation_cases.items())))
        fitness_function.validate_contract(contract)
        return contract
    model = os.environ.get('RESEARCH_MODEL')
    if not model:
        raise RuntimeError('Configure RESEARCH_MODEL for interface extraction and candidate generation.')
    if client_factory is None:
        import anthropic
        client_factory = lambda: anthropic.Anthropic(timeout=90, max_retries=0)
    # The synchronous extractor has its own bounded HTTP request; no implicit retries.
    def build():
        with client_factory() as client:
            contract = builder(natural_language_spec=artifact['input']['problem'], lean_specification=result['lean'],
                seed_program=body.seed_program, evaluation_suite_id=body.evaluation_suite_id,
                evaluation_cases=body.evaluation_cases, resource_limits=limits,
                fitness_function=fitness_function.reference, model=model, client=client)
            fitness_function.validate_contract(contract)
            return contract
    return await asyncio.to_thread(build)
