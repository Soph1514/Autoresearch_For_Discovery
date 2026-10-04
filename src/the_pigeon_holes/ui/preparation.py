"""Bind a server-recorded Lean check to an immutable custom research contract."""
import asyncio
import hashlib
import os
from pydantic import BaseModel, Field
from the_pigeon_holes.fitness.registry import configured_registry
from the_pigeon_holes.models.problem_contract import ResourceLimits, build_problem_contract


class ContractInput(BaseModel):
    formalization_id: str
    seed_program: str = Field(min_length=1, max_length=64000)
    evaluation_suite_id: str = Field(min_length=1, max_length=200)
    evaluation_cases: dict[str, dict] = Field(min_length=1, max_length=1000)
    fitness_function_id: str = Field(min_length=1, max_length=200)
    fitness_function_version: str = Field(min_length=1, max_length=200)
    alignment_reviewed: bool = False
    case_time_seconds: float = Field(default=5, gt=0, le=300, allow_inf_nan=False)
    candidate_time_seconds: float = Field(default=60, gt=0, le=3600, allow_inf_nan=False)
    memory_mb: int = Field(default=512, gt=0, le=32768)
    max_iterations: int = Field(default=100000, gt=0)


def make_evaluator(contract):
    """Build generic sandbox execution around the contract's trusted fitness function."""
    from the_pigeon_holes.evaluation.production import create_evaluator
    evaluator = create_evaluator(contract)
    if not callable(getattr(evaluator, 'evaluate', None)):
        raise ValueError('Evaluator factory must return an async CandidateEvaluator.')
    return evaluator


async def prepare_contract(body, artifact, *, builder=build_problem_contract, registry=None,
                           client_factory=None):
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
    model = os.environ.get('RESEARCH_MODEL')
    if not model:
        raise RuntimeError('Configure RESEARCH_MODEL for interface extraction and candidate generation.')
    limits = ResourceLimits(body.case_time_seconds, body.candidate_time_seconds, body.memory_mb, body.max_iterations)
    active_registry = registry or configured_registry()
    fitness_function = active_registry.find(
        body.fitness_function_id, body.fitness_function_version
    )
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
