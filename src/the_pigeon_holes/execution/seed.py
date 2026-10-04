"""Structural starting programs for automatically prepared research contracts."""

from the_pigeon_holes.models.problem_contract import InterfaceDefinition


def default_seed(interface: InterfaceDefinition) -> str:
    """Preserve the instance shape for a single integer-list selection problem.

    This is a starting candidate, not a feasibility guarantee. The frozen scorer
    must still evaluate it; explicit user seeds never pass through this helper.
    """
    lists = [p for p in interface.parameters if p.python_type == "list[int]"]
    if interface.return_type == "list[int]" and len(lists) == 1:
        value = f"[0] * len({lists[0].name})"
    else:
        value = "[]" if interface.return_type.startswith("list") else "0"
    return interface.solve_signature + f"\n    return {value}\n"
