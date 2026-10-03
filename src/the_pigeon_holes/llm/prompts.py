"""Prompt fragments derived from the problem contract."""

from the_pigeon_holes.models.problem_contract import ProblemContract


def render_solve_contract(contract: ProblemContract) -> str:
    """Return the fixed signature block that the code-generation prompt must include."""
    goal = contract.optimisation_goal
    tie_breakers = ", then ".join(f"{m.direction} {m.name}" for m in goal.tie_breakers)
    objective = f"{goal.primary.direction} {goal.primary.name} ({goal.aggregation} across instances)"
    if tie_breakers:
        objective += f", ties broken by {tie_breakers}"
    return "\n\n".join([
        "Required function (name and signature must match exactly):\n"
        "```python\n" + contract.solve_signature + "\n    ...\n```",
        f"Objective: {objective}.",
    ])
