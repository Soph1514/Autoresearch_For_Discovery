"""Prompt fragments derived from the problem contract."""

from the_pigeon_holes.models.problem_contract import ProblemContract


def render_solve_contract(contract: ProblemContract) -> str:
    """Render the complete interface without exposing evaluation-suite values."""
    goal = contract.optimisation_goal
    tie_breakers = ", then ".join(f"{m.direction} {m.name}" for m in goal.tie_breakers)
    objective = (
        f"{goal.primary.direction} {goal.primary.name} "
        f"({goal.aggregation} across evaluation cases)"
    )
    if tie_breakers:
        objective += f", ties broken by {tie_breakers}"
    sections = []
    supporting_types = contract.interface.supporting_types_code.strip()
    if supporting_types:
        sections.append(
            "Required supporting interface types (definitions only; do not modify):\n"
            "```python\nfrom pydantic import BaseModel\n\n"
            + supporting_types
            + "\n```"
        )
    sections.extend(
        [
            "Required function (name and signature must match exactly):\n"
            "```python\n" + contract.solve_signature + "\n    ...\n```",
            f"Objective: {objective}.",
        ]
    )
    return "\n\n".join(sections)
