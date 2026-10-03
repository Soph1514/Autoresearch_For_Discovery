"""Immutable problem contract consumed by the evolutionary loop."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from the_pigeon_holes.execution.signature_extractor import (
    FUNCTION_NAME,
    MetricGoal,
    OptimisationGoal,
    extract_signature,
    verify_interface_syntax,
)

__all__ = [
    "MetricGoal",
    "OptimisationGoal",
    "ResourceLimits",
    "ProblemContract",
    "validate_seed_program",
    "build_problem_contract",
]


@dataclass(frozen=True)
class ResourceLimits:
    time_seconds: float
    memory_mb: int
    max_iterations: int


@dataclass(frozen=True)
class ProblemContract:
    natural_language_spec: str
    lean_specification: str
    solve_signature: str
    seed_program: str
    optimisation_goal: OptimisationGoal
    resource_limits: ResourceLimits
    evaluator_version: str


def validate_seed_program(seed_program: str) -> None:
    """Raise ValueError unless the seed is valid Python that defines a top-level `solve`."""
    try:
        tree = ast.parse(seed_program)
    except SyntaxError as exc:
        raise ValueError(f"seed_program is not valid Python: {exc}") from exc
    if not any(isinstance(n, ast.FunctionDef) and n.name == FUNCTION_NAME for n in tree.body):
        raise ValueError(f"seed_program must define a top-level '{FUNCTION_NAME}' function")


def build_problem_contract(
    *,
    natural_language_spec: str,
    lean_specification: str,
    seed_program: str,
    resource_limits: ResourceLimits,
    evaluator_version: str,
    model: str,
    client=None,
) -> ProblemContract:
    """Derive the interface and optimisation goal from the Lean statement and build a contract.

    Raises ValueError if the extracted interface is inconsistent or the seed program is invalid.
    """
    interface = extract_signature(lean_specification, model=model, client=client)
    verify_interface_syntax(interface)
    validate_seed_program(seed_program)
    return ProblemContract(
        natural_language_spec=natural_language_spec,
        lean_specification=lean_specification,
        solve_signature=interface.signature_str,
        seed_program=seed_program,
        optimisation_goal=interface.optimisation_goal,
        resource_limits=resource_limits,
        evaluator_version=evaluator_version,
    )
