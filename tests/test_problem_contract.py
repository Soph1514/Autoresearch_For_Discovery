"""Tests for complete, immutable problem-contract preparation."""

import dataclasses
from unittest.mock import MagicMock

import pytest

from the_pigeon_holes.llm.prompts import render_solve_contract
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    FitnessFunctionRef,
    InterfaceDefinition,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    ProblemContract,
    ResourceLimits,
    build_problem_contract,
    validate_seed_program,
)

SEED = (
    "def solve(items: list[int], capacity: int) -> list[bool]:\n"
    "    return [False] * len(items)\n"
)
LEAN = "def solve (items : List Nat) (capacity : Nat) : List Bool -- maximise total_value"
GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "mean")
CASES = {
    "small": {"items": [3, 4, 5], "capacity": 7},
    "empty": {"items": [], "capacity": 0},
}
FITNESS = FitnessFunctionRef("test", "v1", "0" * 64)


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
        "optimisation_goal": goal
        or {
            "primary": {"name": "total_value", "direction": "maximize"},
            "aggregation": "mean",
        },
    }
    data.update(overrides)
    return data


def _limits():
    return ResourceLimits(
        case_time_seconds=2.0,
        candidate_time_seconds=10.0,
        memory_mb=512,
        max_iterations=100,
    )


def _build(client, seed=SEED, cases=CASES):
    return build_problem_contract(
        natural_language_spec="Pick items under capacity.",
        lean_specification=LEAN,
        seed_program=seed,
        evaluation_suite_id="knapsack-public-v1",
        evaluation_cases=cases,
        resource_limits=_limits(),
        fitness_function=FITNESS,
        model="claude-sonnet-5-5",
        client=client,
    )


def test_seed_validation_requires_exact_signature():
    signature = "def solve(x: int) -> int:"
    validate_seed_program("def solve(x: int) -> int:\n    return x\n", signature)
    with pytest.raises(ValueError, match="signature"):
        validate_seed_program("def solve(x: str) -> int:\n    return 0\n", signature)


@pytest.mark.parametrize("bad", ["def solve(x:", "def other(): pass", "x = 1"])
def test_seed_validation_rejects_bad_seed(bad):
    with pytest.raises(ValueError, match="seed_program"):
        validate_seed_program(bad, "def solve(x: int) -> int:")


def test_build_preserves_complete_interface_and_immutable_suite():
    client = _mock_client(_tool_output())
    contract = _build(client)

    assert contract.solve_signature == (
        "def solve(items: list[int], capacity: int) -> list[bool]:"
    )
    assert contract.interface.parameters == (
        Parameter("items", "list[int]"),
        Parameter("capacity", "int"),
    )
    assert contract.interface.schema_version == "python-interface-v1"
    assert contract.optimisation_goal == GOAL
    assert contract.evaluation_suite.id == "knapsack-public-v1"
    assert len(contract.evaluation_suite.cases) == 2
    assert contract.evaluation_suite.cases[0].materialize_inputs() == CASES["small"]
    assert client.messages.create.call_args.kwargs["model"] == "claude-sonnet-5-5"

    with pytest.raises(TypeError):
        contract.evaluation_suite.cases[0].inputs["capacity"] = 99
    with pytest.raises(TypeError):
        contract.evaluation_suite.cases[0].inputs["items"][0] = 99
    materialized = contract.evaluation_suite.cases[0].materialize_inputs()
    materialized["items"].append(99)
    assert contract.evaluation_suite.cases[0].materialize_inputs() == CASES["small"]


def test_contract_is_frozen():
    contract = _build(_mock_client(_tool_output()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.seed_program = "x"


def test_build_keeps_tie_breakers_and_aggregation():
    client = _mock_client(
        _tool_output(
            goal={
                "primary": {"name": "makespan", "direction": "minimize"},
                "aggregation": "worst_case",
                "tie_breakers": [{"name": "idle_time", "direction": "minimize"}],
            }
        )
    )
    contract = _build(client)
    assert contract.optimisation_goal == OptimisationGoal(
        MetricGoal("makespan", "minimize"),
        "worst_case",
        (MetricGoal("idle_time", "minimize"),),
    )


def test_build_rejects_inconsistent_signature():
    client = _mock_client(
        _tool_output(
            parameters=[{"name": "items", "python_type": "list[int]"}],
            signature_str="def solve(values: list[int]) -> list[bool]:",
        )
    )
    with pytest.raises(ValueError, match="parameter names"):
        _build(client)


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        ({"bad": {"items": [1]}}, "do not match signature parameters"),
        ({"bad": {"items": [1], "capacity": "large"}}, "must have type int"),
        ({}, "at least one case"),
    ],
)
def test_build_rejects_malformed_evaluation_suite(cases, message):
    with pytest.raises(ValueError, match=message):
        _build(_mock_client(_tool_output()), cases=cases)


def test_structured_types_reach_contract_and_prompt_without_execution():
    supporting_code = (
        "class Item(BaseModel):\n"
        "    weight: int\n"
        "    label: str\n"
    )
    output = _tool_output(
        parameters=[{"name": "items", "python_type": "list[Item]"}],
        return_type="int",
        signature_str="def solve(items: list[Item]) -> int:",
        pydantic_classes_code=supporting_code,
    )
    contract = build_problem_contract(
        natural_language_spec="Choose structured items.",
        lean_specification="structure Item where weight : Nat; label : String",
        seed_program="def solve(items: list[Item]) -> int:\n    return 0\n",
        evaluation_suite_id="items-v1",
        evaluation_cases={
            "one": {"items": [{"weight": 2, "label": "a"}]},
        },
        resource_limits=_limits(),
        fitness_function=FITNESS,
        model="claude-sonnet-5-5",
        client=_mock_client(output),
    )

    prompt = render_solve_contract(contract)
    assert contract.interface.supporting_types_code == supporting_code
    assert "class Item(BaseModel)" in prompt
    assert "def solve(items: list[Item]) -> int:" in prompt
    assert "weight\": 2" not in prompt
    assert contract.evaluation_suite.cases[0].materialize_inputs()["items"][0]["weight"] == 2


def test_structured_input_field_type_is_validated():
    output = _tool_output(
        parameters=[{"name": "item", "python_type": "Item"}],
        return_type="int",
        signature_str="def solve(item: Item) -> int:",
        pydantic_classes_code="class Item(BaseModel):\n    weight: int\n",
    )
    with pytest.raises(ValueError, match="inputs.item.weight must have type int"):
        build_problem_contract(
            natural_language_spec="x",
            lean_specification="structure Item where weight : Nat",
            seed_program="def solve(item: Item) -> int:\n    return 0\n",
            evaluation_suite_id="bad",
            evaluation_cases={"bad": {"item": {"weight": "heavy"}}},
            resource_limits=_limits(),
            fitness_function=FITNESS,
            model="claude-sonnet-5-5",
            client=_mock_client(output),
        )


def test_supporting_code_is_parsed_but_not_executed_during_preparation():
    output = _tool_output(
        parameters=[{"name": "item", "python_type": "Item"}],
        return_type="int",
        signature_str="def solve(item: Item) -> int:",
        pydantic_classes_code=(
            "class Item(BaseModel):\n"
            "    weight: int\n\n"
            "raise RuntimeError('must not execute during preparation')\n"
        ),
    )
    contract = build_problem_contract(
        natural_language_spec="x",
        lean_specification="structure Item where weight : Nat",
        seed_program="def solve(item: Item) -> int:\n    return 0\n",
        evaluation_suite_id="safe-parse",
        evaluation_cases={"case": {"item": {"weight": 1}}},
        resource_limits=_limits(),
        fitness_function=FITNESS,
        model="claude-sonnet-5-5",
        client=_mock_client(output),
    )

    assert "must not execute" in contract.interface.supporting_types_code


def test_direct_contract_validates_metrics_resources_and_interface():
    with pytest.raises(ValueError, match="unique"):
        OptimisationGoal(
            MetricGoal("score", "maximize"),
            "mean",
            (MetricGoal("score", "minimize"),),
        )
    with pytest.raises(ValueError, match="candidate_time_seconds"):
        ResourceLimits(2.0, 1.0, 128, 100)
    with pytest.raises(ValueError, match="evaluation case 'bad'.*must have type int"):
        ProblemContract(
            natural_language_spec="x",
            lean_specification="def solve (x : Int) : Int",
            interface=InterfaceDefinition(
                "python-interface-v1",
                (Parameter("x", "int"),),
                "int",
                "def solve(x: int) -> int:",
            ),
            seed_program="def solve(x: int) -> int:\n    return x\n",
            evaluation_suite=EvaluationSuite(
                "bad", (EvaluationCase("bad", {"x": "no"}),)
            ),
            optimisation_goal=GOAL,
            resource_limits=_limits(),
            fitness_function=FITNESS,
        )


def test_build_accepts_a_pre_extracted_interface_without_calling_a_model():
    """A reviewed interface must reach the contract byte-identically, with no model call."""
    from the_pigeon_holes.execution.signature_extractor import ExtractedInterface

    extracted = ExtractedInterface(
        function_name="solve",
        parameters=[Parameter("items", "list[int]"), Parameter("capacity", "int")],
        return_type="list[bool]",
        signature_str="def solve(items: list[int], capacity: int) -> list[bool]:",
        pydantic_classes_code="",
        optimisation_goal=GOAL,
    )
    client = MagicMock()
    client.messages.create.side_effect = AssertionError("extraction must not be called")

    contract = build_problem_contract(
        natural_language_spec="Pick items under capacity.",
        lean_specification=LEAN,
        seed_program=SEED,
        evaluation_suite_id="knapsack-public-v1",
        evaluation_cases=CASES,
        resource_limits=_limits(),
        fitness_function=FITNESS,
        client=client,
        extracted=extracted,
    )

    assert contract.interface == InterfaceDefinition.from_extracted(extracted)
    assert contract.optimisation_goal == GOAL
    client.messages.create.assert_not_called()


def test_build_requires_a_model_when_no_interface_is_supplied():
    with pytest.raises(ValueError, match="model or an extracted interface"):
        build_problem_contract(
            natural_language_spec="Pick items under capacity.",
            lean_specification=LEAN,
            seed_program=SEED,
            evaluation_suite_id="knapsack-public-v1",
            evaluation_cases=CASES,
            resource_limits=_limits(),
            fitness_function=FITNESS,
        )
