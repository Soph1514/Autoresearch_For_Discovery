"""Provider-neutral prompts for semantic program variation."""

from __future__ import annotations

from collections.abc import Sequence

from the_pigeon_holes.llm.prompts import render_solve_contract
from the_pigeon_holes.models.problem_contract import ProblemContract

from .models import (
    CandidateEvaluation,
    EvolutionOperator,
    IslandState,
    MutationStrength,
    ProgramCandidate,
)


def _render_candidate(
    heading: str,
    candidate: ProgramCandidate,
    evaluation: CandidateEvaluation | None,
) -> str:
    if evaluation is None:
        evidence = "No evaluation is available."
    elif evaluation.valid:
        evidence = f"Verified valid. Metrics: {dict(evaluation.metrics)!r}."
    else:
        evidence = (
            "INVALID. "
            f"Failure stage: {evaluation.failure_stage or 'unknown'}. "
            f"Reasons: {evaluation.failure_reasons!r}. "
            f"Partial metrics are not valid fitness: {dict(evaluation.partial_metrics)!r}."
        )
    return "\n".join(
        [
            heading,
            f"Candidate ID: {candidate.id}",
            f"Original hypothesis: {candidate.hypothesis}",
            f"Measured evidence: {evidence}",
            "```python",
            candidate.source_code.rstrip(),
            "```",
        ]
    )


def render_generation_prompt(
    *,
    problem: ProblemContract,
    island: IslandState,
    operator: EvolutionOperator,
    mutation_strength: MutationStrength,
    parents: Sequence[tuple[ProgramCandidate, CandidateEvaluation | None]],
    inspirations: Sequence[tuple[ProgramCandidate, CandidateEvaluation | None]],
) -> str:
    """Render all fixed constraints and selected evidence into one request."""
    sections = [
        "You are evolving an executable algorithm for a fixed mathematical problem.",
        "PROBLEM\n" + problem.natural_language_spec.strip(),
        "LEAN FORMALIZATION (specification context, not proof of the Python code)\n"
        + problem.lean_specification.strip(),
        render_solve_contract(problem),
        (
            "EVOLUTION OPERATION\n"
            f"Island search mode: {island.search_mode.value}.\n"
            f"Operator: {operator.value}.\n"
            f"Mutation strength: {mutation_strength.value}."
        ),
    ]

    for index, (candidate, evaluation) in enumerate(parents, start=1):
        sections.append(_render_candidate(f"DIRECT PARENT {index}", candidate, evaluation))
    for index, (candidate, evaluation) in enumerate(inspirations, start=1):
        label = "UNVERIFIED INSPIRATION" if evaluation and not evaluation.valid else "INSPIRATION"
        sections.append(_render_candidate(f"{label} {index}", candidate, evaluation))

    sections.append(
        "OUTPUT REQUIREMENTS\n"
        "Return a falsifiable hypothesis, a predicted measurable effect, an explicit "
        "falsification condition, concise mechanism tags, and a complete Python source "
        "module implementing the exact required solve signature. Private helper functions "
        "are allowed. Do not modify or reproduce the evaluator."
    )
    return "\n\n".join(section for section in sections if section.strip())
