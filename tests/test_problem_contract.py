"""Tests for the ProblemContract builder and the solve-signature prompt block."""

import dataclasses
from unittest.mock import MagicMock

import pytest

from the_pigeon_holes.llm.prompts import render_solve_contract
from the_pigeon_holes.models.problem_contract import (
    MetricGoal,
    OptimisationGoal,
    ProblemContract,
    ResourceLimits,
    build_problem_contract,
    validate_seed_program,
)

SEED = "def solve(items: list[int], capacity: int) -> list[bool]:\n    return [False] * len(items)\n"
LEAN = "def solve (items : List Nat) (capacity : Nat) : List Bool -- maximise total_value"
GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "mean")
INSTANCE = {"items": [3, 4, 5], "capacity": 7}


def _mock_client(input_dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_extracted_interface"
    block.input = input_dict
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _tool_output(goal=None, **overrides):
    data = {
        "parameters": [
            {"name": "items", "python_type": "list[int]"},
            {"name": "capacity", "python_type": "int"},
        ],
        "return_type": "list[bool]",
        "signature_str": "def solve(items: list[int], capacity: int) -> list[bool]:",
        "pydantic_classes_code": "",
        "optimisation_goal": goal or {
            "primary": {"name": "total_value", "direction": "maximize"},
            "aggregation": "mean",
        },
    }
    data.update(overrides)
    return data


def _build(client, seed=SEED):
    return build_problem_contract(
        natural_language_spec="Pick items under capacity.",
        lean_specification=LEAN,
        seed_program=seed,
        instance_id="knapsack-01",
        instance=INSTANCE,
        resource_limits=ResourceLimits(2.0, 512, 100),
        evaluator_version="v1",
        model="claude-sonnet-5-5",
        client=client,
    )


def test_seed_validation_accepts_solve():
    validate_seed_program("def solve(x: int) -> int:\n    return x\n")


@pytest.mark.parametrize("bad", ["def solve(x:", "def other(): pass", "x = 1"])
def test_seed_validation_rejects_bad_seed(bad):
    with pytest.raises(ValueError, match="seed_program"):
        validate_seed_program(bad)


def test_contract_is_frozen():
    contract = ProblemContract(
        natural_language_spec="s",
        lean_specification=LEAN,
        solve_signature="def solve() -> int:",
        seed_program="def solve(): ...",
        instance_id="knapsack-01",
        instance=INSTANCE,
        optimisation_goal=GOAL,
        resource_limits=ResourceLimits(2.0, 512, 100),
        evaluator_version="v1",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.solve_signature = "x"


def test_build_contract_from_lean_statement():
    client = _mock_client(_tool_output())
    contract = _build(client)
    assert contract.solve_signature == "def solve(items: list[int], capacity: int) -> list[bool]:"
    assert contract.optimisation_goal == GOAL
    assert contract.instance_id == "knapsack-01"
    assert contract.instance == INSTANCE
    assert contract.resource_limits == ResourceLimits(2.0, 512, 100)
    assert client.messages.create.call_args.kwargs["model"] == "claude-sonnet-5-5"


def test_build_keeps_tie_breakers_and_aggregation():
    client = _mock_client(_tool_output(goal={
        "primary": {"name": "makespan", "direction": "minimize"},
        "aggregation": "worst_case",
        "tie_breakers": [{"name": "idle_time", "direction": "minimize"}],
    }))
    contract = _build(client)
    assert contract.optimisation_goal == OptimisationGoal(
        MetricGoal("makespan", "minimize"),
        "worst_case",
        (MetricGoal("idle_time", "minimize"),),
    )


def test_build_rejects_inconsistent_signature():
    client = _mock_client(_tool_output(
        parameters=[{"name": "items", "python_type": "list[int]"}],
        signature_str="def solve(values: list[int]) -> list[bool]:",
    ))
    with pytest.raises(ValueError, match="parameter names"):
        _build(client)


def test_build_rejects_unknown_direction():
    client = _mock_client(_tool_output(goal={
        "primary": {"name": "total_value", "direction": "largest"},
        "aggregation": "mean",
    }))
    with pytest.raises(ValueError, match="must be 'maximize' or 'minimize'"):
        _build(client)


def test_build_rejects_instance_not_matching_signature():
    client = _mock_client(_tool_output())
    with pytest.raises(ValueError, match="do not match signature parameters"):
        build_problem_contract(
            natural_language_spec="x",
            lean_specification=LEAN,
            seed_program=SEED,
            instance_id="bad",
            instance={"items": [1]},
            resource_limits=ResourceLimits(2.0, 512, 100),
            evaluator_version="v1",
            model="claude-sonnet-5-5",
            client=client,
        )


def test_build_rejects_invalid_seed():
    client = _mock_client(_tool_output())
    with pytest.raises(ValueError, match="seed_program"):
        _build(client, seed="def other(): pass")


def test_render_includes_signature_and_objective():
    contract = ProblemContract(
        natural_language_spec="x",
        lean_specification=LEAN,
        solve_signature="def solve(jobs: list[int]) -> int:",
        seed_program=SEED,
        instance_id="jobs-03",
        instance={"jobs": []},
        optimisation_goal=OptimisationGoal(
            MetricGoal("makespan", "minimize"), "worst_case", (MetricGoal("idle_time", "minimize"),)
        ),
        resource_limits=ResourceLimits(2.0, 512, 100),
        evaluator_version="v1",
    )
    text = render_solve_contract(contract)
    assert "def solve(jobs: list[int]) -> int:" in text
    assert "minimize makespan (worst_case across instances)" in text
    assert "ties broken by minimize idle_time" in text
